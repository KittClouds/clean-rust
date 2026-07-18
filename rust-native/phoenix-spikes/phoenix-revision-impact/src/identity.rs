use std::collections::BTreeSet;

use compact_str::CompactString;
use hashbrown::{HashMap, HashSet};
use phoenix_types::{DocumentId, EntityId};
use serde::{Deserialize, Serialize};
use smallvec::SmallVec;
use thiserror::Error;

pub const REVISION_IDENTITY_SCHEMA: &str = "phoenix-revision-identity/v1";
pub const IDENTITY_MATCH_THRESHOLD_MILLIS: u16 = 650;
pub const IDENTITY_PARTITION_THRESHOLD_MILLIS: u16 = 500;
pub const IDENTITY_AMBIGUITY_MARGIN_MILLIS: u16 = 60;

#[derive(
    Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize,
)]
#[serde(rename_all = "snake_case")]
pub enum RevisionIdentityKind {
    #[default]
    Scene,
    Event,
    Fact,
}

#[derive(
    Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize,
)]
#[serde(transparent)]
pub struct IdentityFingerprint(pub [u8; 32]);

impl IdentityFingerprint {
    pub fn from_normalized_text(text: &str) -> Self {
        Self(*blake3::hash(text.as_bytes()).as_bytes())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionIdentityRecord {
    pub stable_id: CompactString,
    pub kind: RevisionIdentityKind,
    pub document_id: DocumentId,
    pub semantic_fingerprint: IdentityFingerprint,
    #[serde(default)]
    pub evidence_anchor_fingerprints: SmallVec<[IdentityFingerprint; 4]>,
    #[serde(default)]
    pub participant_entity_ids: SmallVec<[EntityId; 4]>,
    #[serde(default)]
    pub neighbor_event_fingerprints: SmallVec<[IdentityFingerprint; 4]>,
    pub source_start: u32,
    pub source_end: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionIdentitySnapshot {
    pub revision: u64,
    pub records: Vec<RevisionIdentityRecord>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IdentityMatchBasis {
    pub same_document: bool,
    pub semantic_fingerprint_match: bool,
    pub shared_anchor_count: u16,
    pub shared_participant_count: u16,
    pub shared_neighbor_count: u16,
    pub source_distance: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IdentityMatch {
    pub previous_id: CompactString,
    pub current_id: CompactString,
    pub score_millis: u16,
    pub basis: IdentityMatchBasis,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IdentitySplit {
    pub previous_id: CompactString,
    pub current_ids: Vec<CompactString>,
    pub anchor_fingerprints: Vec<IdentityFingerprint>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IdentityMerge {
    pub previous_ids: Vec<CompactString>,
    pub current_id: CompactString,
    pub anchor_fingerprints: Vec<IdentityFingerprint>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IdentityAmbiguitySide {
    Previous,
    Current,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IdentityAmbiguity {
    pub side: IdentityAmbiguitySide,
    pub subject_id: CompactString,
    pub candidate_ids: Vec<CompactString>,
    pub top_score_millis: u16,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionIdentityMap {
    pub schema_version: CompactString,
    pub previous_revision: u64,
    pub current_revision: u64,
    pub scene_matches: Vec<IdentityMatch>,
    pub event_matches: Vec<IdentityMatch>,
    pub fact_matches: Vec<IdentityMatch>,
    pub splits: Vec<IdentitySplit>,
    pub merges: Vec<IdentityMerge>,
    pub ambiguous: Vec<IdentityAmbiguity>,
    pub unmatched_previous_ids: Vec<CompactString>,
    pub unmatched_current_ids: Vec<CompactString>,
}

#[derive(Clone, Debug)]
struct Candidate {
    previous: usize,
    current: usize,
    score_millis: u16,
    basis: IdentityMatchBasis,
}

#[derive(Clone, Debug)]
struct CandidateIndex {
    by_previous: Vec<SmallVec<[usize; 4]>>,
    by_current: Vec<SmallVec<[usize; 4]>>,
}

impl CandidateIndex {
    fn new(candidates: &[Candidate], previous_count: usize, current_count: usize) -> Self {
        let mut by_previous = vec![SmallVec::new(); previous_count];
        let mut by_current = vec![SmallVec::new(); current_count];
        for (candidate_index, candidate) in candidates.iter().enumerate() {
            by_previous[candidate.previous].push(candidate_index);
            by_current[candidate.current].push(candidate_index);
        }
        Self {
            by_previous,
            by_current,
        }
    }
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum RevisionIdentityError {
    #[error("duplicate {side} identity record {id}")]
    DuplicateRecord {
        side: &'static str,
        id: CompactString,
    },
    #[error("identity record {id} has an invalid source range")]
    InvalidSourceRange { id: CompactString },
}

pub fn resolve_revision_identity(
    previous: &RevisionIdentitySnapshot,
    current: &RevisionIdentitySnapshot,
) -> Result<RevisionIdentityMap, RevisionIdentityError> {
    let previous_records = canonical_records("previous", &previous.records)?;
    let current_records = canonical_records("current", &current.records)?;
    let candidates = build_candidates(&previous_records, &current_records);
    let candidate_index =
        CandidateIndex::new(&candidates, previous_records.len(), current_records.len());

    let mut used_previous = HashSet::new();
    let mut used_current = HashSet::new();
    let splits = detect_splits(
        &previous_records,
        &current_records,
        &candidates,
        &candidate_index,
        &mut used_previous,
        &mut used_current,
    );
    let merges = detect_merges(
        &previous_records,
        &current_records,
        &candidates,
        &candidate_index,
        &mut used_previous,
        &mut used_current,
    );

    let (ambiguous, ambiguous_previous, ambiguous_current) = detect_ambiguities(
        &previous_records,
        &current_records,
        &candidates,
        &candidate_index,
        &used_previous,
        &used_current,
    );
    used_previous.extend(ambiguous_previous);
    used_current.extend(ambiguous_current);

    let matches = resolve_mutual_best(
        &previous_records,
        &current_records,
        &candidates,
        &mut used_previous,
        &mut used_current,
    );

    let mut scene_matches = Vec::new();
    let mut event_matches = Vec::new();
    let mut fact_matches = Vec::new();
    for (kind, identity_match) in matches {
        match kind {
            RevisionIdentityKind::Scene => scene_matches.push(identity_match),
            RevisionIdentityKind::Event => event_matches.push(identity_match),
            RevisionIdentityKind::Fact => fact_matches.push(identity_match),
        }
    }

    let unmatched_previous_ids = previous_records
        .iter()
        .enumerate()
        .filter(|(index, _)| !used_previous.contains(index))
        .map(|(_, record)| record.stable_id.clone())
        .collect();
    let unmatched_current_ids = current_records
        .iter()
        .enumerate()
        .filter(|(index, _)| !used_current.contains(index))
        .map(|(_, record)| record.stable_id.clone())
        .collect();

    Ok(RevisionIdentityMap {
        schema_version: REVISION_IDENTITY_SCHEMA.into(),
        previous_revision: previous.revision,
        current_revision: current.revision,
        scene_matches,
        event_matches,
        fact_matches,
        splits,
        merges,
        ambiguous,
        unmatched_previous_ids,
        unmatched_current_ids,
    })
}

fn canonical_records(
    side: &'static str,
    records: &[RevisionIdentityRecord],
) -> Result<Vec<RevisionIdentityRecord>, RevisionIdentityError> {
    let mut records = records.to_vec();
    records.sort_unstable_by(|left, right| {
        left.kind
            .cmp(&right.kind)
            .then_with(|| left.stable_id.cmp(&right.stable_id))
    });
    for record in &mut records {
        if record.source_start > record.source_end {
            return Err(RevisionIdentityError::InvalidSourceRange {
                id: record.stable_id.clone(),
            });
        }
        record.evidence_anchor_fingerprints.sort_unstable();
        record.evidence_anchor_fingerprints.dedup();
        record
            .participant_entity_ids
            .sort_unstable_by(|left, right| left.0.cmp(&right.0));
        record.participant_entity_ids.dedup();
        record.neighbor_event_fingerprints.sort_unstable();
        record.neighbor_event_fingerprints.dedup();
    }
    if let Some(pair) = records
        .windows(2)
        .find(|pair| pair[0].kind == pair[1].kind && pair[0].stable_id == pair[1].stable_id)
    {
        return Err(RevisionIdentityError::DuplicateRecord {
            side,
            id: pair[0].stable_id.clone(),
        });
    }
    Ok(records)
}

fn build_candidates(
    previous: &[RevisionIdentityRecord],
    current: &[RevisionIdentityRecord],
) -> Vec<Candidate> {
    let mut semantic_index =
        HashMap::<(RevisionIdentityKind, IdentityFingerprint), SmallVec<[usize; 4]>>::new();
    let mut anchor_index =
        HashMap::<(RevisionIdentityKind, IdentityFingerprint), SmallVec<[usize; 4]>>::new();
    for (current_index, record) in current.iter().enumerate() {
        semantic_index
            .entry((record.kind, record.semantic_fingerprint))
            .or_default()
            .push(current_index);
        for anchor in &record.evidence_anchor_fingerprints {
            anchor_index
                .entry((record.kind, *anchor))
                .or_default()
                .push(current_index);
        }
    }

    let mut out = Vec::new();
    for (previous_index, left) in previous.iter().enumerate() {
        let mut candidate_indices = HashSet::<usize>::new();
        if let Some(indices) = semantic_index.get(&(left.kind, left.semantic_fingerprint)) {
            candidate_indices.extend(indices.iter().copied());
        }
        for anchor in &left.evidence_anchor_fingerprints {
            if let Some(indices) = anchor_index.get(&(left.kind, *anchor)) {
                candidate_indices.extend(indices.iter().copied());
            }
        }
        let mut candidate_indices = candidate_indices.into_iter().collect::<Vec<_>>();
        candidate_indices.sort_unstable();
        for current_index in candidate_indices {
            let right = &current[current_index];
            let basis = match_basis(left, right);
            out.push(Candidate {
                previous: previous_index,
                current: current_index,
                score_millis: score_basis(&basis),
                basis,
            });
        }
    }
    out.sort_unstable_by(|left, right| {
        left.previous
            .cmp(&right.previous)
            .then_with(|| right.score_millis.cmp(&left.score_millis))
            .then_with(|| left.current.cmp(&right.current))
    });
    out
}

fn match_basis(
    left: &RevisionIdentityRecord,
    right: &RevisionIdentityRecord,
) -> IdentityMatchBasis {
    IdentityMatchBasis {
        same_document: left.document_id == right.document_id,
        semantic_fingerprint_match: left.semantic_fingerprint == right.semantic_fingerprint,
        shared_anchor_count: overlap_count(
            &left.evidence_anchor_fingerprints,
            &right.evidence_anchor_fingerprints,
        ),
        shared_participant_count: overlap_entity_count(
            &left.participant_entity_ids,
            &right.participant_entity_ids,
        ),
        shared_neighbor_count: overlap_count(
            &left.neighbor_event_fingerprints,
            &right.neighbor_event_fingerprints,
        ),
        source_distance: left.source_start.abs_diff(right.source_start),
    }
}

fn score_basis(basis: &IdentityMatchBasis) -> u16 {
    let mut score = 0_u16;
    if basis.same_document {
        score += 180;
    }
    if basis.semantic_fingerprint_match {
        score += 320;
    }
    score += match basis.shared_anchor_count {
        0 => 0,
        1 => 360,
        _ => 480,
    };
    score += basis.shared_participant_count.saturating_mul(80).min(160);
    score += basis.shared_neighbor_count.saturating_mul(80).min(160);
    score += match basis.source_distance {
        0..=32 => 50,
        33..=256 => 30,
        257..=2048 => 10,
        _ => 0,
    };
    score.min(1000)
}

fn detect_splits(
    previous: &[RevisionIdentityRecord],
    current: &[RevisionIdentityRecord],
    candidates: &[Candidate],
    candidate_index: &CandidateIndex,
    used_previous: &mut HashSet<usize>,
    used_current: &mut HashSet<usize>,
) -> Vec<IdentitySplit> {
    let mut splits = Vec::new();
    for (previous_index, record) in previous.iter().enumerate() {
        if record.evidence_anchor_fingerprints.len() < 2 {
            continue;
        }
        let options = candidate_index.by_previous[previous_index]
            .iter()
            .map(|&index| &candidates[index])
            .filter(|candidate| {
                candidate.score_millis >= IDENTITY_PARTITION_THRESHOLD_MILLIS
                    && candidate.basis.shared_anchor_count > 0
            })
            .collect::<Vec<_>>();
        let Some(partition) = anchor_partition(
            &record.evidence_anchor_fingerprints,
            options
                .iter()
                .map(|candidate| {
                    (
                        candidate.current,
                        current[candidate.current]
                            .evidence_anchor_fingerprints
                            .as_slice(),
                    )
                })
                .collect(),
        ) else {
            continue;
        };
        used_previous.insert(previous_index);
        used_current.extend(partition.iter().copied());
        splits.push(IdentitySplit {
            previous_id: record.stable_id.clone(),
            current_ids: partition
                .iter()
                .map(|&index| current[index].stable_id.clone())
                .collect(),
            anchor_fingerprints: record.evidence_anchor_fingerprints.to_vec(),
        });
    }
    splits.sort_unstable_by(|left, right| left.previous_id.cmp(&right.previous_id));
    splits
}

fn detect_merges(
    previous: &[RevisionIdentityRecord],
    current: &[RevisionIdentityRecord],
    candidates: &[Candidate],
    candidate_index: &CandidateIndex,
    used_previous: &mut HashSet<usize>,
    used_current: &mut HashSet<usize>,
) -> Vec<IdentityMerge> {
    let mut merges = Vec::new();
    for (current_index, record) in current.iter().enumerate() {
        if used_current.contains(&current_index) || record.evidence_anchor_fingerprints.len() < 2 {
            continue;
        }
        let options = candidate_index.by_current[current_index]
            .iter()
            .map(|&index| &candidates[index])
            .filter(|candidate| {
                !used_previous.contains(&candidate.previous)
                    && candidate.score_millis >= IDENTITY_PARTITION_THRESHOLD_MILLIS
                    && candidate.basis.shared_anchor_count > 0
            })
            .collect::<Vec<_>>();
        let Some(partition) = anchor_partition(
            &record.evidence_anchor_fingerprints,
            options
                .iter()
                .map(|candidate| {
                    (
                        candidate.previous,
                        previous[candidate.previous]
                            .evidence_anchor_fingerprints
                            .as_slice(),
                    )
                })
                .collect(),
        ) else {
            continue;
        };
        used_current.insert(current_index);
        used_previous.extend(partition.iter().copied());
        merges.push(IdentityMerge {
            previous_ids: partition
                .iter()
                .map(|&index| previous[index].stable_id.clone())
                .collect(),
            current_id: record.stable_id.clone(),
            anchor_fingerprints: record.evidence_anchor_fingerprints.to_vec(),
        });
    }
    merges.sort_unstable_by(|left, right| left.current_id.cmp(&right.current_id));
    merges
}

fn anchor_partition(
    target: &[IdentityFingerprint],
    options: Vec<(usize, &[IdentityFingerprint])>,
) -> Option<Vec<usize>> {
    if options.len() < 2 {
        return None;
    }
    let target = target.iter().copied().collect::<BTreeSet<_>>();
    let mut selected = Vec::new();
    let mut covered = BTreeSet::new();
    for (index, anchors) in options {
        let shared = anchors
            .iter()
            .copied()
            .filter(|anchor| target.contains(anchor))
            .collect::<BTreeSet<_>>();
        if shared.is_empty() || shared.iter().any(|anchor| covered.contains(anchor)) {
            continue;
        }
        covered.extend(shared);
        selected.push(index);
    }
    if selected.len() >= 2 && covered == target {
        selected.sort_unstable();
        Some(selected)
    } else {
        None
    }
}

fn detect_ambiguities(
    previous: &[RevisionIdentityRecord],
    current: &[RevisionIdentityRecord],
    candidates: &[Candidate],
    candidate_index: &CandidateIndex,
    used_previous: &HashSet<usize>,
    used_current: &HashSet<usize>,
) -> (Vec<IdentityAmbiguity>, HashSet<usize>, HashSet<usize>) {
    let mut ambiguous = Vec::new();
    let mut ambiguous_previous = HashSet::new();
    let mut ambiguous_current = HashSet::new();
    let mut best_previous_score = HashMap::<usize, u16>::new();
    for candidate in candidates {
        if used_previous.contains(&candidate.previous) || used_current.contains(&candidate.current)
        {
            continue;
        }
        best_previous_score
            .entry(candidate.previous)
            .and_modify(|score| *score = (*score).max(candidate.score_millis))
            .or_insert(candidate.score_millis);
    }

    for (previous_index, previous_record) in previous.iter().enumerate() {
        if used_previous.contains(&previous_index) {
            continue;
        }
        let options = candidate_index.by_previous[previous_index]
            .iter()
            .map(|&index| &candidates[index])
            .filter(|candidate| {
                !used_current.contains(&candidate.current)
                    && candidate.score_millis >= IDENTITY_MATCH_THRESHOLD_MILLIS
            })
            .collect::<Vec<_>>();
        if is_ambiguous(&options) {
            ambiguous_previous.insert(previous_index);
            ambiguous_current.extend(options.iter().map(|candidate| candidate.current));
            ambiguous.push(IdentityAmbiguity {
                side: IdentityAmbiguitySide::Previous,
                subject_id: previous_record.stable_id.clone(),
                candidate_ids: options
                    .iter()
                    .map(|candidate| current[candidate.current].stable_id.clone())
                    .collect(),
                top_score_millis: options[0].score_millis,
            });
        }
    }

    for (current_index, current_record) in current.iter().enumerate() {
        if used_current.contains(&current_index) || ambiguous_current.contains(&current_index) {
            continue;
        }
        let mut options = candidate_index.by_current[current_index]
            .iter()
            .map(|&index| &candidates[index])
            .filter(|candidate| {
                !used_previous.contains(&candidate.previous)
                    && candidate.score_millis >= IDENTITY_MATCH_THRESHOLD_MILLIS
                    && best_previous_score
                        .get(&candidate.previous)
                        .is_some_and(|best| {
                            best.saturating_sub(candidate.score_millis)
                                < IDENTITY_AMBIGUITY_MARGIN_MILLIS
                        })
            })
            .collect::<Vec<_>>();
        options.sort_unstable_by(|left, right| {
            right
                .score_millis
                .cmp(&left.score_millis)
                .then_with(|| left.previous.cmp(&right.previous))
        });
        if is_ambiguous(&options) {
            ambiguous_current.insert(current_index);
            ambiguous_previous.extend(options.iter().map(|candidate| candidate.previous));
            ambiguous.push(IdentityAmbiguity {
                side: IdentityAmbiguitySide::Current,
                subject_id: current_record.stable_id.clone(),
                candidate_ids: options
                    .iter()
                    .map(|candidate| previous[candidate.previous].stable_id.clone())
                    .collect(),
                top_score_millis: options[0].score_millis,
            });
        }
    }
    ambiguous.sort_unstable_by(|left, right| {
        (left.side as u8)
            .cmp(&(right.side as u8))
            .then_with(|| left.subject_id.cmp(&right.subject_id))
    });
    (ambiguous, ambiguous_previous, ambiguous_current)
}

fn is_ambiguous(options: &[&Candidate]) -> bool {
    options.len() >= 2
        && options[0]
            .score_millis
            .saturating_sub(options[1].score_millis)
            < IDENTITY_AMBIGUITY_MARGIN_MILLIS
}

fn resolve_mutual_best(
    previous: &[RevisionIdentityRecord],
    current: &[RevisionIdentityRecord],
    candidates: &[Candidate],
    used_previous: &mut HashSet<usize>,
    used_current: &mut HashSet<usize>,
) -> Vec<(RevisionIdentityKind, IdentityMatch)> {
    let mut best_by_previous = HashMap::<usize, &Candidate>::new();
    let mut best_by_current = HashMap::<usize, &Candidate>::new();
    for candidate in candidates {
        if candidate.score_millis < IDENTITY_MATCH_THRESHOLD_MILLIS
            || used_previous.contains(&candidate.previous)
            || used_current.contains(&candidate.current)
        {
            continue;
        }
        best_by_previous
            .entry(candidate.previous)
            .and_modify(|best| {
                if candidate.score_millis > best.score_millis
                    || (candidate.score_millis == best.score_millis
                        && candidate.current < best.current)
                {
                    *best = candidate;
                }
            })
            .or_insert(candidate);
        best_by_current
            .entry(candidate.current)
            .and_modify(|best| {
                if candidate.score_millis > best.score_millis
                    || (candidate.score_millis == best.score_millis
                        && candidate.previous < best.previous)
                {
                    *best = candidate;
                }
            })
            .or_insert(candidate);
    }

    let mut matches = Vec::new();
    let mut ordered = best_by_previous.into_values().collect::<Vec<_>>();
    ordered.sort_unstable_by_key(|candidate| (candidate.previous, candidate.current));
    for candidate in ordered {
        let mutual = best_by_current
            .get(&candidate.current)
            .is_some_and(|best| best.previous == candidate.previous);
        if !mutual {
            continue;
        }
        used_previous.insert(candidate.previous);
        used_current.insert(candidate.current);
        matches.push((
            previous[candidate.previous].kind,
            IdentityMatch {
                previous_id: previous[candidate.previous].stable_id.clone(),
                current_id: current[candidate.current].stable_id.clone(),
                score_millis: candidate.score_millis,
                basis: candidate.basis.clone(),
            },
        ));
    }
    matches
}

fn overlap_count<T: Ord + Copy>(left: &[T], right: &[T]) -> u16 {
    let mut left_index = 0;
    let mut right_index = 0;
    let mut matches = 0_u16;
    while left_index < left.len() && right_index < right.len() {
        match left[left_index].cmp(&right[right_index]) {
            std::cmp::Ordering::Less => left_index += 1,
            std::cmp::Ordering::Greater => right_index += 1,
            std::cmp::Ordering::Equal => {
                matches = matches.saturating_add(1);
                left_index += 1;
                right_index += 1;
            }
        }
    }
    matches
}

fn overlap_entity_count(left: &[EntityId], right: &[EntityId]) -> u16 {
    let mut left_index = 0;
    let mut right_index = 0;
    let mut matches = 0_u16;
    while left_index < left.len() && right_index < right.len() {
        match left[left_index].0.cmp(&right[right_index].0) {
            std::cmp::Ordering::Less => left_index += 1,
            std::cmp::Ordering::Greater => right_index += 1,
            std::cmp::Ordering::Equal => {
                matches = matches.saturating_add(1);
                left_index += 1;
                right_index += 1;
            }
        }
    }
    matches
}

#[cfg(test)]
#[path = "identity_tests.rs"]
mod tests;
