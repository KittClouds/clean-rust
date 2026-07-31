use std::cmp::{Ordering, Reverse};
use std::collections::BinaryHeap;
use std::mem::size_of;

use compact_str::CompactString;
use hashbrown::HashMap;

use crate::score::{measure_field, Coherence, PositionedGroup};
use crate::selection::{retain_dense_simd, retain_sparse, RankedCandidate};
use crate::tokenize::tokenize;
use crate::types::{
    CandidateSelection, DocumentId, FieldConfig, QpsConfig, QpsError, QueryGroup, SearchHit,
    SearchReceipt,
};

const NO_CHOICE: u64 = u64::MAX;

const fn pack_choice(term: u32, posting: u32) -> u64 {
    term as u64 | ((posting as u64) << 32)
}

#[inline]
fn coverage_factor(coverage: f32, exponent: f32) -> f32 {
    if exponent == 2.0 {
        coverage * coverage
    } else if exponent == 1.0 {
        coverage
    } else {
        coverage.powf(exponent)
    }
}

#[derive(Clone, Debug)]
pub(crate) struct StoredField {
    pub terms: Box<[u32]>,
    pub segments: Box<[u32]>,
}

#[derive(Clone, Debug)]
pub(crate) struct StoredDocument {
    pub external_id: u64,
    pub active: bool,
    pub fields: Box<[StoredField]>,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct DocumentMeta {
    pub external_id: u64,
}

#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct FieldRange {
    pub start: u32,
    pub len: u32,
}

#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct PostingRange {
    pub start: u32,
    pub len: u32,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct PostingRecord {
    pub document: u32,
    pub field: u16,
    /// Precomputed document-level BM25F impact, repeated on the document's
    /// field rows so positional pages remain independently addressable.
    pub impact: f32,
    pub position_start: u32,
    pub position_len: u32,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct IndexStats {
    pub documents: usize,
    pub terms: usize,
    pub posting_rows: usize,
    pub positions: usize,
    pub estimated_bytes: usize,
}

pub struct QpsIndex {
    config: QpsConfig,
    field_configs: Box<[FieldConfig]>,
    term_ids: HashMap<CompactString, u32>,
    terms: Box<[CompactString]>,
    documents: Box<[DocumentMeta]>,
    field_ranges: Box<[FieldRange]>,
    document_terms: Box<[u32]>,
    posting_ranges: Box<[PostingRange]>,
    postings: Box<[PostingRecord]>,
    positions: Box<[u32]>,
    segments: Box<[u32]>,
    document_frequency: Box<[u32]>,
    average_field_lengths: Box<[f32]>,
}

pub struct SearchScratch {
    epoch: u32,
    group_epoch: u32,
    document_stamp: Vec<u32>,
    group_stamp: Vec<u32>,
    lexical: Vec<f32>,
    coverage_weight: Vec<f32>,
    group_best_score: Vec<f32>,
    group_best_quality: Vec<f32>,
    group_best_choice: Vec<u64>,
    candidate_scores: Vec<f32>,
    choices: Vec<u64>,
    choice_stamp: Vec<u32>,
    touched: Vec<u32>,
    group_documents: Vec<u32>,
    selected_candidates: Vec<u32>,
    candidate_heap: BinaryHeap<Reverse<RankedCandidate>>,
    dense_candidates: Vec<RankedCandidate>,
    query_expansions: Vec<ResolvedExpansion>,
    query_ranges: Vec<PostingRange>,
    occurrences: Vec<PositionedGroup>,
    chosen_terms: Vec<Option<u32>>,
    chosen_postings: Vec<Option<u32>>,
}

#[derive(Clone, Copy)]
struct ResolvedExpansion {
    term: u32,
    quality: f32,
}

#[derive(Clone, Copy)]
enum SearchMode {
    Bounded,
    Exhaustive,
}

impl SearchScratch {
    pub fn new() -> Self {
        Self {
            epoch: 0,
            group_epoch: 0,
            document_stamp: Vec::new(),
            group_stamp: Vec::new(),
            lexical: Vec::new(),
            coverage_weight: Vec::new(),
            group_best_score: Vec::new(),
            group_best_quality: Vec::new(),
            group_best_choice: Vec::new(),
            candidate_scores: Vec::new(),
            choices: Vec::new(),
            choice_stamp: Vec::new(),
            touched: Vec::new(),
            group_documents: Vec::new(),
            selected_candidates: Vec::new(),
            candidate_heap: BinaryHeap::new(),
            dense_candidates: Vec::new(),
            query_expansions: Vec::new(),
            query_ranges: Vec::new(),
            occurrences: Vec::new(),
            chosen_terms: Vec::new(),
            chosen_postings: Vec::new(),
        }
    }

    pub fn with_document_capacity(documents: usize, maximum_query_groups: usize) -> Self {
        let mut scratch = Self::new();
        scratch.prepare(documents, maximum_query_groups);
        scratch
    }

    fn prepare(&mut self, documents: usize, maximum_query_groups: usize) {
        self.document_stamp.resize(documents, 0);
        self.group_stamp.resize(documents, 0);
        self.lexical.resize(documents, 0.0);
        self.coverage_weight.resize(documents, 0.0);
        self.group_best_score.resize(documents, 0.0);
        self.group_best_quality.resize(documents, 0.0);
        self.group_best_choice.resize(documents, NO_CHOICE);
        self.candidate_scores.resize(documents, 0.0);
        let choices = documents.saturating_mul(maximum_query_groups);
        self.choices.resize(choices, NO_CHOICE);
        self.choice_stamp.resize(choices, 0);
        self.touched.reserve(documents.min(4_096));
        self.group_documents.reserve(documents.min(4_096));
        self.selected_candidates.reserve(documents.min(256));
        self.candidate_heap.reserve(documents.min(256));
        self.dense_candidates.reserve(documents.min(8_192));
        self.query_expansions.reserve(maximum_query_groups);
        self.query_ranges.reserve(maximum_query_groups);
        self.chosen_terms.reserve(maximum_query_groups);
        self.chosen_postings.reserve(maximum_query_groups);
    }

    fn begin_query(&mut self) {
        self.epoch = self.epoch.wrapping_add(1);
        if self.epoch == 0 {
            self.document_stamp.fill(0);
            self.choice_stamp.fill(0);
            self.epoch = 1;
        }
        for document in self.touched.drain(..) {
            self.candidate_scores[document as usize] = 0.0;
        }
        self.selected_candidates.clear();
        self.candidate_heap.clear();
        self.dense_candidates.clear();
        self.query_expansions.clear();
        self.query_ranges.clear();
    }

    fn begin_group(&mut self) {
        self.group_epoch = self.group_epoch.wrapping_add(1);
        if self.group_epoch == 0 {
            self.group_stamp.fill(0);
            self.group_epoch = 1;
        }
        self.group_documents.clear();
    }

    fn capacity_fingerprint(&self) -> usize {
        self.document_stamp.capacity()
            + self.group_stamp.capacity()
            + self.lexical.capacity()
            + self.coverage_weight.capacity()
            + self.group_best_score.capacity()
            + self.group_best_quality.capacity()
            + self.group_best_choice.capacity()
            + self.candidate_scores.capacity()
            + self.choices.capacity()
            + self.choice_stamp.capacity()
            + self.touched.capacity()
            + self.group_documents.capacity()
            + self.selected_candidates.capacity()
            + self.candidate_heap.capacity()
            + self.dense_candidates.capacity()
            + self.query_expansions.capacity()
            + self.query_ranges.capacity()
            + self.occurrences.capacity()
            + self.chosen_terms.capacity()
            + self.chosen_postings.capacity()
    }
}

impl Default for SearchScratch {
    fn default() -> Self {
        Self::new()
    }
}

impl QpsIndex {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn from_parts(
        config: QpsConfig,
        field_configs: Box<[FieldConfig]>,
        term_ids: HashMap<CompactString, u32>,
        terms: Box<[CompactString]>,
        documents: Box<[DocumentMeta]>,
        field_ranges: Box<[FieldRange]>,
        document_terms: Box<[u32]>,
        posting_ranges: Box<[PostingRange]>,
        postings: Box<[PostingRecord]>,
        positions: Box<[u32]>,
        segments: Box<[u32]>,
        document_frequency: Box<[u32]>,
        average_field_lengths: Box<[f32]>,
    ) -> Self {
        Self {
            config,
            field_configs,
            term_ids,
            terms,
            documents,
            field_ranges,
            document_terms,
            posting_ranges,
            postings,
            positions,
            segments,
            document_frequency,
            average_field_lengths,
        }
    }

    pub fn search_into(
        &self,
        query: &str,
        top_k: usize,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
    ) -> Result<SearchReceipt, QpsError> {
        self.search_text_with_mode(query, top_k, scratch, output, SearchMode::Bounded)
    }

    /// Exhaustive positional oracle used to prove bounded candidate recall.
    /// This is intentionally not the serving path.
    pub fn search_exhaustive_into(
        &self,
        query: &str,
        top_k: usize,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
    ) -> Result<SearchReceipt, QpsError> {
        self.search_text_with_mode(query, top_k, scratch, output, SearchMode::Exhaustive)
    }

    fn search_text_with_mode(
        &self,
        query: &str,
        top_k: usize,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
        mode: SearchMode,
    ) -> Result<SearchReceipt, QpsError> {
        scratch.prepare(self.documents.len(), self.config.maximum_query_groups);
        scratch.begin_query();
        let tokens = tokenize(query);
        if tokens.is_empty() {
            return Err(QpsError::EmptyQuery);
        }
        if tokens.len() > self.config.maximum_query_groups {
            return Err(QpsError::QueryTooLarge);
        }
        for token in tokens {
            let start = scratch.query_expansions.len() as u32;
            if let Some(term) = self.term_ids.get(token.token.as_str()) {
                scratch.query_expansions.push(ResolvedExpansion {
                    term: *term,
                    quality: 1.0,
                });
            }
            scratch.query_ranges.push(PostingRange {
                start,
                len: scratch.query_expansions.len() as u32 - start,
            });
        }
        self.search_resolved(top_k, scratch, output, mode)
    }

    pub fn search_groups_into(
        &self,
        groups: &[QueryGroup<'_>],
        top_k: usize,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
    ) -> Result<SearchReceipt, QpsError> {
        self.search_groups_with_mode(groups, top_k, scratch, output, SearchMode::Bounded)
    }

    /// Exhaustive oracle for explicit expansion groups.
    pub fn search_groups_exhaustive_into(
        &self,
        groups: &[QueryGroup<'_>],
        top_k: usize,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
    ) -> Result<SearchReceipt, QpsError> {
        self.search_groups_with_mode(groups, top_k, scratch, output, SearchMode::Exhaustive)
    }

    fn search_groups_with_mode(
        &self,
        groups: &[QueryGroup<'_>],
        top_k: usize,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
        mode: SearchMode,
    ) -> Result<SearchReceipt, QpsError> {
        if groups.is_empty() {
            return Err(QpsError::EmptyQuery);
        }
        if groups.len() > self.config.maximum_query_groups {
            return Err(QpsError::QueryTooLarge);
        }
        scratch.prepare(self.documents.len(), self.config.maximum_query_groups);
        scratch.begin_query();
        for group in groups {
            if group.expansions.is_empty()
                || group.expansions.len() > self.config.maximum_expansions_per_group
            {
                return Err(QpsError::QueryTooLarge);
            }
            let start = scratch.query_expansions.len() as u32;
            for expansion in group.expansions {
                if !expansion.quality.is_finite()
                    || expansion.quality <= 0.0
                    || expansion.quality > 1.0
                {
                    return Err(QpsError::InvalidExpansionQuality);
                }
                let tokens = tokenize(expansion.term);
                if tokens.len() != 1 {
                    return Err(QpsError::InvalidExpansionTerm);
                }
                if let Some(term) = self.term_ids.get(tokens[0].token.as_str()) {
                    scratch.query_expansions.push(ResolvedExpansion {
                        term: *term,
                        quality: expansion.quality,
                    });
                }
            }
            scratch.query_ranges.push(PostingRange {
                start,
                len: scratch.query_expansions.len() as u32 - start,
            });
        }
        self.search_resolved(top_k, scratch, output, mode)
    }

    fn search_resolved(
        &self,
        top_k: usize,
        scratch: &mut SearchScratch,
        output: &mut Vec<SearchHit>,
        mode: SearchMode,
    ) -> Result<SearchReceipt, QpsError> {
        let capacity_before = scratch.capacity_fingerprint() + output.capacity();
        output.clear();
        let mut visited = 0_u32;
        let group_count = scratch.query_ranges.len();
        for group in 0..group_count {
            let range = scratch.query_ranges[group];
            if range.len == 1 {
                let expansion = scratch.query_expansions[range.start as usize];
                visited = visited.saturating_add(self.score_exact_group(group, expansion, scratch));
                continue;
            }

            scratch.begin_group();
            for expansion_index in range.start..range.start.saturating_add(range.len) {
                let expansion = scratch.query_expansions[expansion_index as usize];
                visited = visited.saturating_add(self.score_expansion(expansion, scratch));
            }
            for &document in &scratch.group_documents {
                let index = document as usize;
                if scratch.document_stamp[index] != scratch.epoch {
                    scratch.document_stamp[index] = scratch.epoch;
                    scratch.lexical[index] = 0.0;
                    scratch.coverage_weight[index] = 0.0;
                    scratch.touched.push(document);
                }
                scratch.lexical[index] += scratch.group_best_score[index];
                scratch.coverage_weight[index] += scratch.group_best_quality[index];
                let choice = index * self.config.maximum_query_groups + group;
                scratch.choices[choice] = scratch.group_best_choice[index];
                scratch.choice_stamp[choice] = scratch.epoch;
            }
        }

        let total_weight = group_count as f32;
        let mut covered_candidates = 0_u32;
        for &document in &scratch.touched {
            let index = document as usize;
            let coverage = scratch.coverage_weight[index] / total_weight;
            if coverage >= self.config.coverage_floor {
                scratch.candidate_scores[index] = scratch.lexical[index]
                    * coverage_factor(coverage, self.config.coverage_exponent);
                covered_candidates = covered_candidates.saturating_add(1);
            }
        }

        let candidate_limit = match mode {
            SearchMode::Exhaustive => covered_candidates as usize,
            SearchMode::Bounded => {
                let requested = if group_count == 1 {
                    // A single group has no inter-term proximity, order, or
                    // phrase signal. Retain room for field-exact reranking
                    // without paying the multi-term ambiguity budget.
                    top_k.saturating_mul(4).max(top_k)
                } else {
                    self.config
                        .minimum_candidate_pool
                        .max(top_k.saturating_mul(self.config.candidate_pool_multiplier))
                };
                requested
                    .min(self.config.maximum_candidate_pool)
                    .min(covered_candidates as usize)
            }
        };
        let selection = match mode {
            SearchMode::Exhaustive => {
                scratch.selected_candidates.clear();
                scratch.selected_candidates.extend(
                    scratch
                        .touched
                        .iter()
                        .copied()
                        .filter(|document| scratch.candidate_scores[*document as usize] > 0.0),
                );
                CandidateSelection::Exhaustive
            }
            SearchMode::Bounded => {
                let density = covered_candidates as f32 / self.documents.len().max(1) as f32;
                if density >= self.config.dense_simd_threshold {
                    retain_dense_simd(
                        &scratch.candidate_scores,
                        candidate_limit,
                        &mut scratch.dense_candidates,
                        &mut scratch.selected_candidates,
                    );
                    CandidateSelection::DenseSimd
                } else {
                    retain_sparse(
                        &scratch.candidate_scores,
                        &scratch.touched,
                        candidate_limit,
                        &mut scratch.candidate_heap,
                        &mut scratch.selected_candidates,
                    );
                    CandidateSelection::SparseTouched
                }
            }
        };

        let reranked_candidates = scratch.selected_candidates.len() as u32;
        let mut position_values_visited = 0_u32;
        for candidate_index in 0..scratch.selected_candidates.len() {
            let document = scratch.selected_candidates[candidate_index];
            let index = document as usize;
            let coverage = scratch.coverage_weight[index] / total_weight;
            let (coherence, opened_positions) = self.coherence(document, group_count, scratch);
            position_values_visited = position_values_visited.saturating_add(opened_positions);
            let multiplier = 1.0
                + self.config.proximity_weight * coherence.proximity
                + self.config.order_weight * coherence.order
                + self.config.phrase_weight * coherence.phrase
                + self.config.segment_weight * coherence.segment
                + coherence.exact_field;
            let lexical = scratch.lexical[index];
            output.push(SearchHit {
                document: DocumentId(document),
                external_id: self.documents[index].external_id,
                score: scratch.candidate_scores[index] * multiplier,
                lexical_score: lexical,
                coverage,
                proximity: coherence.proximity,
                order: coherence.order,
                phrase: coherence.phrase,
                segment: coherence.segment,
                exact_field: coherence.exact_field,
            });
        }
        output.sort_unstable_by(|left, right| {
            right
                .score
                .partial_cmp(&left.score)
                .unwrap_or(Ordering::Equal)
                .then_with(|| left.document.cmp(&right.document))
        });
        output.truncate(top_k);
        let capacity_after = scratch.capacity_fingerprint() + output.capacity();
        Ok(SearchReceipt {
            query_groups: group_count as u16,
            candidates: scratch.touched.len() as u32,
            covered_candidates,
            reranked_candidates,
            posting_rows_visited: visited,
            position_values_visited,
            selection,
            allocations_grew: capacity_after > capacity_before,
        })
    }

    fn score_exact_group(
        &self,
        group: usize,
        expansion: ResolvedExpansion,
        scratch: &mut SearchScratch,
    ) -> u32 {
        let range = self.posting_ranges[expansion.term as usize];
        let rows = self.posting_slice(range);
        let mut cursor = 0;
        while cursor < rows.len() {
            let document_start = cursor as u32;
            let document = rows[cursor].document;
            let score = rows[cursor].impact * expansion.quality;
            while cursor < rows.len() && rows[cursor].document == document {
                cursor += 1;
            }

            let index = document as usize;
            if scratch.document_stamp[index] != scratch.epoch {
                scratch.document_stamp[index] = scratch.epoch;
                scratch.lexical[index] = 0.0;
                scratch.coverage_weight[index] = 0.0;
                scratch.touched.push(document);
            }
            scratch.lexical[index] += score;
            scratch.coverage_weight[index] += expansion.quality;
            let choice = index * self.config.maximum_query_groups + group;
            scratch.choices[choice] = pack_choice(expansion.term, range.start + document_start);
            scratch.choice_stamp[choice] = scratch.epoch;
        }
        range.len
    }

    fn score_expansion(&self, expansion: ResolvedExpansion, scratch: &mut SearchScratch) -> u32 {
        let range = self.posting_ranges[expansion.term as usize];
        let rows = self.posting_slice(range);
        let mut cursor = 0;
        while cursor < rows.len() {
            let document_start = cursor as u32;
            let document = rows[cursor].document;
            let score = rows[cursor].impact * expansion.quality;
            while cursor < rows.len() && rows[cursor].document == document {
                cursor += 1;
            }
            let index = document as usize;
            if scratch.group_stamp[index] != scratch.group_epoch {
                scratch.group_stamp[index] = scratch.group_epoch;
                scratch.group_best_score[index] = score;
                scratch.group_best_quality[index] = expansion.quality;
                scratch.group_best_choice[index] =
                    pack_choice(expansion.term, range.start + document_start);
                scratch.group_documents.push(document);
            } else if score > scratch.group_best_score[index] {
                scratch.group_best_score[index] = score;
                scratch.group_best_quality[index] = expansion.quality;
                scratch.group_best_choice[index] =
                    pack_choice(expansion.term, range.start + document_start);
            }
        }
        range.len
    }

    fn coherence(
        &self,
        document: u32,
        group_count: usize,
        scratch: &mut SearchScratch,
    ) -> (Coherence, u32) {
        scratch.chosen_terms.clear();
        scratch.chosen_postings.clear();
        for group in 0..group_count {
            let choice = document as usize * self.config.maximum_query_groups + group;
            let selected =
                (scratch.choice_stamp[choice] == scratch.epoch).then_some(scratch.choices[choice]);
            scratch
                .chosen_terms
                .push(selected.map(|packed| packed as u32));
            scratch
                .chosen_postings
                .push(selected.map(|packed| (packed >> 32) as u32));
        }
        let mut best = Coherence::default();
        let mut best_total = -1.0_f32;
        let mut position_values_visited = 0_u32;
        for field in 0..self.field_configs.len() {
            scratch.occurrences.clear();
            for (group, posting_start) in scratch.chosen_postings.iter().enumerate() {
                let Some(posting_start) = posting_start else {
                    continue;
                };
                if let Some(posting) = self.postings[*posting_start as usize..]
                    .iter()
                    .take_while(|posting| posting.document == document)
                    .find(|posting| posting.field == field as u16)
                    .copied()
                {
                    position_values_visited =
                        position_values_visited.saturating_add(posting.position_len);
                    let start = posting.position_start as usize;
                    let end = start + posting.position_len as usize;
                    scratch.occurrences.extend(
                        self.positions[start..end]
                            .iter()
                            .copied()
                            .zip(self.segments[start..end].iter().copied())
                            .map(|(position, segment)| PositionedGroup {
                                position,
                                segment,
                                group: group as u8,
                            }),
                    );
                }
            }
            let range = self.field_range(document, field);
            let field_terms = &self.document_terms
                [range.start as usize..range.start as usize + range.len as usize];
            let measured = measure_field(
                &mut scratch.occurrences,
                &scratch.chosen_terms,
                field_terms,
                self.field_configs[field].exact_match_bonus,
                self.config.proximity_decay_tokens,
            );
            let total = self.config.proximity_weight * measured.proximity
                + self.config.order_weight * measured.order
                + self.config.phrase_weight * measured.phrase
                + self.config.segment_weight * measured.segment
                + measured.exact_field;
            if total > best_total {
                best_total = total;
                best = measured;
            }
        }
        (best, position_values_visited)
    }

    fn posting_slice(&self, range: PostingRange) -> &[PostingRecord] {
        &self.postings[range.start as usize..(range.start + range.len) as usize]
    }

    fn field_range(&self, document: u32, field: usize) -> FieldRange {
        self.field_ranges[document as usize * self.field_configs.len() + field]
    }

    pub fn stats(&self) -> IndexStats {
        let string_bytes = self.terms.iter().map(CompactString::len).sum::<usize>();
        IndexStats {
            documents: self.documents.len(),
            terms: self.terms.len(),
            posting_rows: self.postings.len(),
            positions: self.positions.len(),
            estimated_bytes: string_bytes
                + self.documents.len() * size_of::<DocumentMeta>()
                + self.field_ranges.len() * size_of::<FieldRange>()
                + self.document_terms.len() * size_of::<u32>()
                + self.posting_ranges.len() * size_of::<PostingRange>()
                + self.postings.len() * size_of::<PostingRecord>()
                + self.positions.len() * size_of::<u32>()
                + self.segments.len() * size_of::<u32>()
                + self.document_frequency.len() * size_of::<u32>()
                + self.average_field_lengths.len() * size_of::<f32>(),
        }
    }
}
