//! Surface Router — the brain of NER routing decisions.
//!
//! Builds `NerNeedVector` per sentence/window from workspace state, then
//! emits `NerRoute` decisions. Cheap and merciless: only routes to expensive
//! model lanes when the evidence demands it.

use rustc_hash::FxHashMap;
use smallvec::SmallVec;

use phoenix_alex::{SurfaceHit, SurfaceHitKind};
use phoenix_types::SentenceSpan;

use crate::known_lane::KnownCandidate;
use crate::native_lane::{NativeCandidate, NativeDiscoveryLane};
use crate::schema::DynamicSchemaBuilder;
use crate::semantic_router::{SemanticLabelRouter, SemanticRouteInput};
use crate::types::{AdjudicateCase, LabelBankContext, MentionKind, NerNeedVector, NerRoute};

/// Budget cap: max model-discovery seeds per document.
///
/// The dynamic lane is a precision layer over native discovery; keeping this
/// budget tight preserves the sub-second warm path on long documents.
const MAX_MODEL_WINDOWS: usize = 20;
/// Sentence padding around a target sentence for model windows.
const MODEL_SENTENCE_PAD: usize = 1;

/// The surface router that plans NER routes for each text window.
pub struct SurfaceRouter {
    /// Max model windows allowed per call.
    pub max_model_windows: usize,
}

impl Default for SurfaceRouter {
    fn default() -> Self {
        Self {
            max_model_windows: MAX_MODEL_WINDOWS,
        }
    }
}

impl SurfaceRouter {
    /// Build per-sentence need vectors from known + native candidates.
    pub fn build_need_vectors(
        &self,
        text: &str,
        sentences: &[SentenceSpan],
        known: &[KnownCandidate],
        native: &[NativeCandidate],
        surface_hits: &[SurfaceHit],
    ) -> Vec<NerNeedVector> {
        let num_sentences = sentences.len();
        if num_sentences == 0 {
            return Vec::new();
        }
        let mut needs = vec![NerNeedVector::default(); num_sentences];
        let mut known_named_by_sentence = vec![0u16; num_sentences];
        let mut native_named_by_sentence = vec![0u16; num_sentences];
        let mut native_entity_like_by_sentence = vec![0u16; num_sentences];
        let mut relation_or_evidence_cue_by_sentence = vec![false; num_sentences];
        let mut ambiguous_native_by_sentence = vec![false; num_sentences];

        // Count normalized surface frequencies across native candidates.
        let mut surface_counts = FxHashMap::<&str, u16>::default();
        for c in native {
            if c.mention_kind != MentionKind::Pronoun {
                *surface_counts.entry(c.normalized.as_str()).or_insert(0) += 1;
            }
        }

        // Accumulate known-lane signals.
        for c in known {
            let idx = c.sentence_index as usize;
            if let Some(need) = needs.get_mut(idx) {
                need.has_known_seed = true;
                need.candidate_count = need.candidate_count.saturating_add(1);
                known_named_by_sentence[idx] = known_named_by_sentence[idx].saturating_add(1);
            }
        }

        // Accumulate native-lane signals.
        for c in native {
            let idx = c.sentence_index as usize;
            let Some(need) = needs.get_mut(idx) else {
                continue;
            };
            need.candidate_count = need.candidate_count.saturating_add(1);
            match c.mention_kind {
                MentionKind::Pronoun => {
                    need.has_pronoun = true;
                    ambiguous_native_by_sentence[idx] = true;
                }
                MentionKind::Nominal => {
                    need.has_nominal_role = true;
                    ambiguous_native_by_sentence[idx] = true;
                    native_entity_like_by_sentence[idx] =
                        native_entity_like_by_sentence[idx].saturating_add(1);
                }
                MentionKind::Named => {
                    need.has_unknown_cap_span = true;
                    need.unknown_named_count = need.unknown_named_count.saturating_add(1);
                    native_named_by_sentence[idx] = native_named_by_sentence[idx].saturating_add(1);
                    native_entity_like_by_sentence[idx] =
                        native_entity_like_by_sentence[idx].saturating_add(1);
                }
            }
            if surface_counts
                .get(c.normalized.as_str())
                .copied()
                .unwrap_or(0)
                > 1
            {
                need.has_repeated_unknown_surface = true;
            }
        }

        // Dialogue cue detection (SIMD).
        for sentence in sentences {
            if let Some(need) = needs.get_mut(sentence.index) {
                need.has_dialogue_structure = NativeDiscoveryLane::has_dialogue_cue(text, sentence);
            }
        }

        for hit in surface_hits {
            let Some(idx) =
                sentence_index_for_range(sentences, hit.source_range.start, hit.source_range.end)
            else {
                continue;
            };
            let Some(need) = needs.get_mut(idx) else {
                continue;
            };
            match hit.kind {
                SurfaceHitKind::TemporalCue | SurfaceHitKind::CausalCue => {
                    need.has_causal_or_temporal_cue = true;
                }
                SurfaceHitKind::RelationCue | SurfaceHitKind::EvidenceCue => {
                    relation_or_evidence_cue_by_sentence[idx] = true;
                    need.has_domain_signature = true;
                }
                SurfaceHitKind::StructureCue | SurfaceHitKind::GuardCue => {
                    need.has_domain_signature = true;
                }
                SurfaceHitKind::EntityAlias => {}
            }
        }

        // Chunk-hint signals used by downstream substrate guidance.
        for (idx, need) in needs.iter_mut().enumerate() {
            let known_named = usize::from(known_named_by_sentence[idx]);
            let native_named = usize::from(native_named_by_sentence[idx]);
            let native_entity_like = usize::from(native_entity_like_by_sentence[idx]);
            let has_ambiguous_native = ambiguous_native_by_sentence[idx];
            let relation_or_evidence_cue = relation_or_evidence_cue_by_sentence[idx];
            need.has_entity_pair = known_named + native_named >= 2
                || (relation_or_evidence_cue && known_named + native_entity_like >= 2);
            need.has_ambiguous_reference = has_ambiguous_native && known_named + native_named > 0;
            need.has_named_event_candidate =
                need.has_causal_or_temporal_cue && known_named + native_entity_like > 0;
        }

        needs
    }

    /// Plan routes from need vectors.
    pub fn plan_routes(
        &self,
        text: &str,
        sentences: &[SentenceSpan],
        needs: &[NerNeedVector],
        schema_builder: &DynamicSchemaBuilder,
        known: &[KnownCandidate],
        native: &[NativeCandidate],
        label_bank_context: Option<&LabelBankContext<'_>>,
        semantic_label_router: Option<&(dyn SemanticLabelRouter + Send + Sync)>,
    ) -> Vec<NerRoute> {
        let mut routes = Vec::new();
        let mut model_window_count = 0usize;

        // Score and sort sentences by priority (descending).
        let mut scored: Vec<(usize, u16)> = needs
            .iter()
            .enumerate()
            .map(|(i, need)| (i, Self::need_priority(need)))
            .collect();
        scored.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));

        let mut marked_model = vec![false; sentences.len()];

        for (sent_idx, _priority) in &scored {
            let need = &needs[*sent_idx];

            // Already enough model windows?
            if model_window_count >= self.max_model_windows {
                break;
            }

            if Self::needs_model_discovery(need) {
                // Mark this sentence + padding for model discovery.
                let start = sent_idx.saturating_sub(MODEL_SENTENCE_PAD);
                let end = (*sent_idx + MODEL_SENTENCE_PAD + 1).min(sentences.len());
                for slot in &mut marked_model[start..end] {
                    *slot = true;
                }
                model_window_count += 1;
            }
        }

        // Merge contiguous marked sentences into model-discovery windows.
        let mut model_windows = Vec::<(usize, usize)>::new();
        let mut i = 0usize;
        while i < marked_model.len() {
            if !marked_model[i] {
                i += 1;
                continue;
            }
            let start = i;
            while i < marked_model.len() && marked_model[i] {
                i += 1;
            }
            model_windows.push((start, i));
        }

        let semantic_hints = semantic_label_router
            .map(|router| {
                let inputs = model_windows
                    .iter()
                    .map(|(start, end)| SemanticRouteInput {
                        document_text: text,
                        window_text: window_text(text, sentences, *start, *end).unwrap_or(""),
                        sentences,
                        window_start_sentence: *start as u32,
                        window_end_sentence: *end as u32,
                        known,
                        native,
                        context_domain: label_bank_context
                            .and_then(|context| context.domain_profile),
                    })
                    .collect::<Vec<_>>();
                router.route_windows(&inputs)
            })
            .unwrap_or_else(|| vec![None; model_windows.len()]);

        for ((start, end), semantic_hint) in model_windows.into_iter().zip(semantic_hints) {
            let label_pack = schema_builder.build_pack_for_window_v3(
                start as u32,
                end as u32,
                known,
                native,
                label_bank_context,
                semantic_hint.as_ref(),
            );
            routes.push(NerRoute::ModelDiscovery {
                window_start_sentence: start as u32,
                window_end_sentence: end as u32,
                label_pack,
            });
        }

        // Check for adjudication-worthy sentences (many candidates, low agreement).
        for (sent_idx, need) in needs.iter().enumerate() {
            if Self::needs_adjudication(need) {
                let cases = Self::gather_adjudication_cases(sent_idx as u32, native);
                if !cases.is_empty() {
                    routes.push(NerRoute::Adjudicate { cases });
                }
            }
        }

        routes
    }

    /// Priority score for a sentence — higher means more likely to need model.
    fn need_priority(need: &NerNeedVector) -> u16 {
        let mut p = 0u16;
        if need.has_repeated_unknown_surface {
            p += 5;
        }
        p += need.unknown_named_count.min(4);
        if need.has_dialogue_structure {
            p += 3;
        }
        if need.has_nominal_role {
            p += 2;
        }
        if need.has_pronoun {
            p += 1;
        }
        if need.has_known_seed {
            p += 1;
        }
        if need.has_entity_pair {
            p += 2;
        }
        if need.has_domain_signature {
            p += 1;
        }
        if need.has_causal_or_temporal_cue {
            p += 2;
        }
        if need.has_named_event_candidate {
            p += 3;
        }
        if need.has_ambiguous_reference {
            p += 2;
        }
        p
    }

    /// Should we send this sentence to model discovery?
    fn needs_model_discovery(need: &NerNeedVector) -> bool {
        need.has_repeated_unknown_surface
            || need.unknown_named_count >= 3
            || (need.has_pronoun
                && need.unknown_named_count > 0
                && (need.has_known_seed
                    || need.has_dialogue_structure
                    || need.has_repeated_unknown_surface))
            || (need.has_nominal_role && (need.has_unknown_cap_span || need.has_dialogue_structure))
            || (need.has_known_seed && need.has_repeated_unknown_surface)
            || need.has_named_event_candidate
            || (need.has_domain_signature && need.has_entity_pair)
    }

    /// Should we route this sentence to adjudication?
    fn needs_adjudication(need: &NerNeedVector) -> bool {
        need.candidate_count >= 4 && need.unknown_named_count >= 2 && need.has_known_seed
    }

    fn gather_adjudication_cases(
        sentence_index: u32,
        native: &[NativeCandidate],
    ) -> SmallVec<[AdjudicateCase; 8]> {
        native
            .iter()
            .filter(|c| c.sentence_index == sentence_index && c.mention_kind == MentionKind::Named)
            .take(8)
            .map(|c| AdjudicateCase {
                mention_id: c.mention_id,
                surface: c.surface.clone(),
                sentence_index,
                candidate_entity_refs: c.entity_ref.iter().cloned().collect(),
                candidate_labels: SmallVec::new(),
            })
            .collect()
    }
}

fn sentence_index_for_range(sentences: &[SentenceSpan], start: u32, end: u32) -> Option<usize> {
    let midpoint = start + end.saturating_sub(start) / 2;
    sentences
        .iter()
        .position(|sentence| midpoint >= sentence.range.start && midpoint < sentence.range.end)
}

fn window_text<'a>(
    text: &'a str,
    sentences: &[SentenceSpan],
    start_sentence: usize,
    end_sentence: usize,
) -> Option<&'a str> {
    let first = sentences.get(start_sentence)?;
    let last = sentences.get(end_sentence.checked_sub(1)?)?;
    text.get(first.range.start as usize..last.range.end as usize)
}

#[cfg(test)]
mod tests {
    use super::*;
    use compact_str::CompactString;
    use phoenix_alex::{AlexSnapshotId, PatternId};
    use phoenix_types::TextRange;

    #[test]
    fn need_priority_empty_is_zero() {
        let need = NerNeedVector::default();
        assert_eq!(SurfaceRouter::need_priority(&need), 0);
    }

    #[test]
    fn default_model_window_budget_stays_tight() {
        assert_eq!(SurfaceRouter::default().max_model_windows, 20);
    }

    #[test]
    fn need_priority_accumulates() {
        let need = NerNeedVector {
            has_repeated_unknown_surface: true,
            unknown_named_count: 2,
            has_dialogue_structure: true,
            ..Default::default()
        };
        // 5 + 2 + 3 = 10
        assert_eq!(SurfaceRouter::need_priority(&need), 10);
    }

    #[test]
    fn needs_model_discovery_for_repeated() {
        let need = NerNeedVector {
            has_repeated_unknown_surface: true,
            ..Default::default()
        };
        assert!(SurfaceRouter::needs_model_discovery(&need));
    }

    #[test]
    fn no_model_for_clean_known() {
        let need = NerNeedVector {
            has_known_seed: true,
            ..Default::default()
        };
        assert!(!SurfaceRouter::needs_model_discovery(&need));
    }

    #[test]
    fn adjudication_needs_high_candidate_count() {
        let need = NerNeedVector {
            candidate_count: 4,
            unknown_named_count: 2,
            has_known_seed: true,
            ..Default::default()
        };
        assert!(SurfaceRouter::needs_adjudication(&need));
    }

    #[test]
    fn no_adjudication_for_low_candidates() {
        let need = NerNeedVector {
            candidate_count: 1,
            unknown_named_count: 0,
            has_known_seed: false,
            ..Default::default()
        };
        assert!(!SurfaceRouter::needs_adjudication(&need));
    }

    #[test]
    fn surface_cues_drive_need_vector_without_text_substring_checks() {
        let text = "Aella met Kai.";
        let sentences = [SentenceSpan {
            index: 0,
            range: TextRange {
                start: 0,
                end: text.len() as u32,
            },
        }];
        let hits = [
            surface_hit(SurfaceHitKind::CausalCue, 6, 9, "because"),
            surface_hit(SurfaceHitKind::RelationCue, 6, 9, "approved"),
        ];
        let native = [
            native_candidate(1, 0, 5, "Aella"),
            native_candidate(2, 10, 13, "Kai"),
        ];
        let user_type_labels = [crate::types::EntityLabel::new("DragonHouse")];
        let label_bank_context = LabelBankContext {
            user_type_labels: &user_type_labels,
            ..Default::default()
        };
        let router = SurfaceRouter::default();
        let needs = router.build_need_vectors(text, &sentences, &[], &native, &hits);
        let routes = router.plan_routes(
            text,
            &sentences,
            &needs,
            &DynamicSchemaBuilder::default(),
            &[],
            &native,
            Some(&label_bank_context),
            None,
        );

        assert!(needs[0].has_causal_or_temporal_cue);
        assert!(needs[0].has_domain_signature);
        assert!(needs[0].has_entity_pair);
        assert!(needs[0].has_named_event_candidate);
        let route_pack = routes
            .iter()
            .find_map(|route| match route {
                NerRoute::ModelDiscovery { label_pack, .. } => Some(label_pack),
                _ => None,
            })
            .expect("model discovery route");
        assert!(route_pack
            .labels
            .iter()
            .any(|label| label.as_str() == "DragonHouse"));
        assert!(route_pack.label_sources.iter().any(|(label, source)| {
            label.as_str() == "DragonHouse" && *source == crate::types::LabelBankSource::UserType
        }));
        assert!(!text.contains("because"));
        assert!(!text.contains("approved"));
    }

    fn surface_hit(kind: SurfaceHitKind, start: u32, end: u32, normalized: &str) -> SurfaceHit {
        SurfaceHit {
            snapshot_id: AlexSnapshotId(1),
            pattern_id: PatternId(1),
            kind,
            source_range: TextRange { start, end },
            normalized_range: TextRange {
                start: 0,
                end: normalized.len() as u32,
            },
            surface: CompactString::from(normalized),
            normalized: CompactString::from(normalized),
            confidence: 1.0,
        }
    }

    fn native_candidate(id: u64, start: u32, end: u32, surface: &str) -> NativeCandidate {
        NativeCandidate {
            mention_id: crate::types::LocalMentionId(id),
            range: TextRange { start, end },
            surface: CompactString::from(surface),
            normalized: CompactString::from(surface.to_ascii_lowercase()),
            mention_kind: MentionKind::Named,
            entity_ref: None,
            votes: SmallVec::new(),
            sentence_index: 0,
        }
    }
}
