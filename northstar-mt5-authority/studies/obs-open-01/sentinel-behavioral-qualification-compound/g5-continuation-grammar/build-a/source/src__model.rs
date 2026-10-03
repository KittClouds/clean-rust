use obs_open_04a_g1::model::{CompletedObservation, KernelContext, KernelState};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum StartReachability {
    ProvenReachable,
    ConstructivelyReachable,
    UpperEnvelopeOnly,
    Unknown,
    NotEvaluable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PresentationLayer {
    SourceGrammarInvalid,
    ContextPresentationInvalid,
    PrefixPresentationInvalid,
    KernelApplied,
    KernelRejected,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PresentationResult {
    pub layer: PresentationLayer,
    pub reason: Option<String>,
    pub state_unchanged: Option<bool>,
    pub continuation_after: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PresentabilityClass {
    Presentable,
    LeftOnly,
    RightOnly,
    SourceGrammarInvalid,
    ContextPresentationInvalid,
    PrefixPresentationInvalid,
    RequiresCoupling,
    RequiresObserverCorrespondence,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EpistemicStatus {
    Proven,
    ConstructivelyWitnessed,
    SoundOverapproximation,
    Conditional,
    Unknown,
    NotEvaluable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ApproximationDirection {
    Exact,
    UnderApproximation,
    OverApproximation,
    Mixed,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum NonvacuityClass {
    Nontrivial,
    EpsilonOnly,
    NoCommonNonemptyPresentation,
    Unknown,
    NotEvaluable,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StartingSituation {
    pub prefix_id: String,
    pub applied_prefix_length: u32,
    pub state: KernelState,
    pub context: KernelContext,
    pub reachability: StartReachability,
    pub reachability_receipt: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RelativeBarToken {
    pub token_id: String,
    pub open_delta_ticks: i64,
    pub high_delta_ticks: i64,
    pub low_delta_ticks: i64,
    pub close_delta_ticks: i64,
    pub coverage_complete: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CouplingContract {
    pub coupling_id: String,
    pub kind: String,
    pub prefix_sensitive: bool,
    pub observer_correspondence_dependency: String,
    pub identity_special_case: bool,
    pub temporal_alignment: String,
    pub price_alignment: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PairPresentation {
    pub class: PresentabilityClass,
    pub epistemic_status: EpistemicStatus,
    pub approximation: ApproximationDirection,
    pub left: PresentationResult,
    pub right: PresentationResult,
    pub conditional_on_start_reachability: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FixtureReceipt {
    pub fixture_id: String,
    pub purpose: String,
    pub left_prefix_length: u32,
    pub right_prefix_length: Option<u32>,
    pub token_count: u32,
    pub expected: String,
    pub observed: String,
    pub presentability: Option<PairPresentation>,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RealizedTokenPair {
    pub left: CompletedObservation,
    pub right: CompletedObservation,
}
