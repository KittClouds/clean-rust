use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RepresentationId {
    History,
    SemanticTape,
    SourceTape,
    CurrentState,
    ReducedState,
}

impl RepresentationId {
    pub const fn name(self) -> &'static str {
        match self {
            Self::History => "RAW_COMPLETED_BAR_HISTORY_V1",
            Self::SemanticTape => "SEMANTIC_TRANSITION_TAPE_V1",
            Self::SourceTape => "EVENT_SOURCE_TAPE_V1",
            Self::CurrentState => "CURRENT_SENTINEL_STATE_V1",
            Self::ReducedState => "REDUCED_SENTINEL_GEOMETRY_V1",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RelationClass {
    Lossless,
    LossyQuotient,
    ConditionallyInvertible,
    ReconstructibleWithContext,
    NonReconstructible,
    NotYetEvaluable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Location {
    InZone,
    Above,
    Below,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CandidateState {
    pub id: u32,
    pub value: f64,
    pub birth_bar_index: u16,
    pub birth_knowledge_time: i64,
    pub age_bars: u16,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CommittedState {
    pub bar_index: u16,
    pub knowledge_time: i64,
    pub upper: CandidateState,
    pub lower: CandidateState,
    pub close: f64,
    pub upper_giveback: f64,
    pub lower_giveback: f64,
    pub range_locations: Vec<Option<Location>>,
    pub upper_extensions: Vec<Option<f64>>,
    pub lower_extensions: Vec<Option<f64>>,
    pub window_active: bool,
    pub coverage_complete: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReducedState {
    pub upper_value: f64,
    pub lower_value: f64,
    pub upper_giveback: f64,
    pub lower_giveback: f64,
    pub range_locations: Vec<Option<Location>>,
    pub upper_extensions: Vec<Option<f64>>,
    pub lower_extensions: Vec<Option<f64>>,
    pub window_active: bool,
    pub coverage_complete: bool,
}

impl From<&CommittedState> for ReducedState {
    fn from(state: &CommittedState) -> Self {
        Self {
            upper_value: state.upper.value,
            lower_value: state.lower.value,
            upper_giveback: state.upper_giveback,
            lower_giveback: state.lower_giveback,
            range_locations: state.range_locations.clone(),
            upper_extensions: state.upper_extensions.clone(),
            lower_extensions: state.lower_extensions.clone(),
            window_active: state.window_active,
            coverage_complete: state.coverage_complete,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceCommit {
    pub relative_bar_index: u16,
    pub event_time: i64,
    pub knowledge_time: i64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub new_upper: bool,
    pub new_lower: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RelationEdge {
    pub source_representation: String,
    pub target_representation: String,
    pub relation_class: RelationClass,
    pub required_context: Vec<String>,
    pub lost_degrees: Vec<String>,
    pub reconstruction_procedure: Option<String>,
    pub witness_artifact: Option<String>,
    pub status: String,
    pub authority_basis: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CollisionSummary {
    pub observations: usize,
    pub unique_exact_histories: usize,
    pub unique_semantic_event_tapes: usize,
    pub unique_event_source_tapes: usize,
    pub unique_current_states: usize,
    pub unique_reduced_representations: usize,
    pub semantic_collision_groups: usize,
    pub source_to_state_collision_groups: usize,
    pub state_to_reduced_collision_groups: usize,
    pub maximum_semantic_multiplicity: usize,
    pub maximum_state_multiplicity: usize,
    pub maximum_reduced_multiplicity: usize,
    pub interpretation: String,
}
