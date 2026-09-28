//! Model + Adjudication Traits — stub-only interfaces.
//!
//! Actual model implementations (GLiNER, classifier, NLI) live in consuming
//! crates behind feature gates. This crate stays model-agnostic.

use compact_str::CompactString;
use phoenix_types::MentionEntityRef;
use smallvec::SmallVec;

use crate::types::{EntityLabel, LabelPack, LocalMentionId, MentionVote};
use phoenix_types::TextRange;

/// A new entity span discovered by a model.
#[derive(Clone, Debug)]
pub struct DiscoveredSpan {
    pub window_relative_range: TextRange,
    pub surface: CompactString,
    pub label: EntityLabel,
    pub confidence: f32,
}

// ---------------------------------------------------------------------------
// Model NER trait
// ---------------------------------------------------------------------------

/// Input window for model-based NER.
#[derive(Clone, Copy, Debug)]
pub struct ModelNerWindow<'a> {
    pub text: &'a str,
    pub window_start_sentence: u32,
    pub window_end_sentence: u32,
}

/// A model-discovery request used by batch-capable model adapters.
#[derive(Clone, Copy, Debug)]
pub struct ModelNerRequest<'a> {
    pub window: ModelNerWindow<'a>,
    pub label_pack: &'a LabelPack,
}

/// Trait for dynamic NER models (e.g. GLiNER).
///
/// Discover: find new spans the deterministic lanes missed.
/// Verify: label votes for uncertain native spans.
pub trait DynamicNerModel: Send + Sync {
    /// Find new entity spans using the label pack.
    fn discover(
        &self,
        window: &ModelNerWindow<'_>,
        label_pack: &LabelPack,
    ) -> Result<Vec<DiscoveredSpan>, NerModelError>;

    /// Find new entity spans for multiple windows.
    ///
    /// Model adapters can override this to batch by compatible label packs.
    /// The default preserves old behavior.
    fn discover_batch(
        &self,
        requests: &[ModelNerRequest<'_>],
    ) -> Result<Vec<Vec<DiscoveredSpan>>, NerModelError> {
        let mut outputs = Vec::with_capacity(requests.len());
        for request in requests {
            outputs.push(self.discover(&request.window, request.label_pack)?);
        }
        Ok(outputs)
    }

    /// Verify/re-label existing uncertain candidates.
    fn verify(
        &self,
        cases: &[VerificationCase],
    ) -> Result<Vec<(LocalMentionId, MentionVote)>, NerModelError>;
}

/// Error from model operations.
#[derive(Debug, thiserror::Error)]
pub enum NerModelError {
    #[error("model inference failed: {0}")]
    Inference(String),
    #[error("model not loaded")]
    NotLoaded,
}

/// A specific span to verify with the model.
#[derive(Clone, Debug)]
pub struct VerificationCase {
    pub mention_id: LocalMentionId,
    pub surface: CompactString,
    pub sentence_text: CompactString,
    pub candidate_labels: SmallVec<[EntityLabel; 4]>,
}

// ---------------------------------------------------------------------------
// Adjudication trait
// ---------------------------------------------------------------------------

/// Trait for mention adjudicators (classifier/NLI judge).
pub trait MentionAdjudicator: Send + Sync {
    /// Judge difficult cases — not mining, just verdicts.
    fn adjudicate(
        &self,
        cases: &[AdjudicationCase],
    ) -> Result<Vec<AdjudicationDecision>, AdjudicationError>;
}

/// Error from adjudication.
#[derive(Debug, thiserror::Error)]
pub enum AdjudicationError {
    #[error("adjudication failed: {0}")]
    Failed(String),
    #[error("adjudicator not available")]
    NotAvailable,
}

/// What the adjudicator is being asked.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InstructTask {
    SpanIsEntity,
    SpanLabelChoice,
    AliasAdjudication,
    CorefAdjudication,
    RelationEntailment,
    MentionModality,
    MentionPolarity,
}

/// A case submitted to the adjudicator.
#[derive(Clone, Debug)]
pub struct AdjudicationCase {
    pub mention_id: LocalMentionId,
    pub task: InstructTask,
    pub surface: CompactString,
    pub sentence_text: CompactString,
    pub neighbor_sentence: Option<CompactString>,
    pub candidate_labels: SmallVec<[EntityLabel; 4]>,
    pub candidate_entities: SmallVec<[MentionEntityRef; 4]>,
}

/// The adjudicator's verdict.
#[derive(Clone, Debug)]
pub struct AdjudicationDecision {
    pub mention_id: LocalMentionId,
    pub decision: DecisionKind,
    pub confidence: f32,
    pub chosen_label: Option<EntityLabel>,
    pub chosen_entity: Option<MentionEntityRef>,
    pub modality: Option<Modality>,
    pub polarity: Option<Polarity>,
}

/// Verdict kind.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DecisionKind {
    Accept,
    Reject,
    Relabel,
    NeedsMore,
}

/// Evidential modality.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Modality {
    Observed,
    Reported,
    Hypothetical,
    Desired,
    Conditional,
}

/// Assertion polarity.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Polarity {
    Positive,
    Negated,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn instruct_task_variants_exist() {
        let tasks = [
            InstructTask::SpanIsEntity,
            InstructTask::SpanLabelChoice,
            InstructTask::AliasAdjudication,
            InstructTask::CorefAdjudication,
            InstructTask::RelationEntailment,
            InstructTask::MentionModality,
            InstructTask::MentionPolarity,
        ];
        assert_eq!(tasks.len(), 7);
    }

    #[test]
    fn decision_kind_variants() {
        assert_ne!(DecisionKind::Accept, DecisionKind::Reject);
        assert_ne!(DecisionKind::Relabel, DecisionKind::NeedsMore);
    }
}
