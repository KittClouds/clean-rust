use phoenix_types::{BiTemporalWindow, EntityId, TextRange};
use serde::{Deserialize, Serialize};

use crate::{CanonicalEventId, TemporalAxisId};

#[derive(Clone, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct TemporalWorldlineId(pub String);

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum TemporalTruthStatus {
    #[default]
    Unknown,
    Observed,
    Asserted,
    Reported,
    Inferred,
    Planned,
    Conditional,
    Hypothetical,
    Negated,
    Contradicted,
}

impl TemporalTruthStatus {
    pub fn rank(self) -> u8 {
        match self {
            Self::Observed => 9,
            Self::Asserted => 8,
            Self::Inferred => 7,
            Self::Reported => 6,
            Self::Planned => 5,
            Self::Conditional => 4,
            Self::Hypothetical => 3,
            Self::Negated => 2,
            Self::Contradicted => 1,
            Self::Unknown => 0,
        }
    }

    pub fn as_key(self) -> &'static str {
        match self {
            Self::Unknown => "unknown",
            Self::Observed => "observed",
            Self::Asserted => "asserted",
            Self::Reported => "reported",
            Self::Inferred => "inferred",
            Self::Planned => "planned",
            Self::Conditional => "conditional",
            Self::Hypothetical => "hypothetical",
            Self::Negated => "negated",
            Self::Contradicted => "contradicted",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum BeliefStateKind {
    #[default]
    Believes,
    Knows,
    Observed,
    Reported,
    Doubts,
    Intends,
    Unaware,
    Contradicts,
}

impl BeliefStateKind {
    pub fn as_key(self) -> &'static str {
        match self {
            Self::Believes => "believes",
            Self::Knows => "knows",
            Self::Observed => "observed",
            Self::Reported => "reported",
            Self::Doubts => "doubts",
            Self::Intends => "intends",
            Self::Unaware => "unaware",
            Self::Contradicts => "contradicts",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum BeliefSourceKind {
    #[default]
    Narration,
    DirectObservation,
    Quote,
    Attribution,
    Conditional,
    Hypothetical,
    Planned,
    Negation,
    Frame,
}

impl BeliefSourceKind {
    pub fn as_key(self) -> &'static str {
        match self {
            Self::Narration => "narration",
            Self::DirectObservation => "directObservation",
            Self::Quote => "quote",
            Self::Attribution => "attribution",
            Self::Conditional => "conditional",
            Self::Hypothetical => "hypothetical",
            Self::Planned => "planned",
            Self::Negation => "negation",
            Self::Frame => "frame",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BeliefStateAtom {
    pub belief_id: String,
    pub document_id: String,
    pub proposition_id: Option<String>,
    pub event_id: Option<String>,
    pub canonical_event_id: Option<CanonicalEventId>,
    pub observer_entity_id: Option<EntityId>,
    pub subject_entity_id: Option<EntityId>,
    pub axis_id: TemporalAxisId,
    pub worldline_id: TemporalWorldlineId,
    pub kind: BeliefStateKind,
    pub truth_status: TemporalTruthStatus,
    pub source_kind: BeliefSourceKind,
    pub label: String,
    pub confidence_millis: u32,
    pub temporal: BiTemporalWindow,
    pub range: Option<TextRange>,
    #[serde(default)]
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BeliefStateCard {
    pub card_id: String,
    pub document_id: String,
    pub event_id: Option<String>,
    pub canonical_event_id: Option<CanonicalEventId>,
    pub observer_entity_id: Option<EntityId>,
    pub axis_id: TemporalAxisId,
    pub worldline_id: TemporalWorldlineId,
    pub strongest_kind: BeliefStateKind,
    pub strongest_truth_status: TemporalTruthStatus,
    pub confidence_millis: u32,
    pub temporal: BiTemporalWindow,
    #[serde(default)]
    pub source_belief_ids: Vec<String>,
    #[serde(default)]
    pub open_conflict_ids: Vec<String>,
    #[serde(default)]
    pub evidence_refs: Vec<String>,
}
