use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Surface {
    KernelState,
    ImmutableContext,
    CurrentInput,
    DerivedWithinStep,
    Emission,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CarryStatus {
    MutableCarriedState,
    ImmutableContext,
    CurrentInputOnly,
    DerivedWithinStep,
    EmissionOnly,
    ProvenanceOnly,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Role {
    ControlStateQ,
    GuardRegister,
    ArithmeticRegister,
    ObservationO,
    StaticContextC,
    ProvenanceP,
    UsedInGuard,
    ReadFromPriorState,
    CopiedFromInput,
    CopiedFromPriorState,
    AffineUpdate,
    PiecewiseAffineUpdate,
    NonlinearUpdate,
    ConstantUpdate,
    IdentityBearing,
    TimeBearing,
    UsedInArithmetic,
    DerivedEmission,
    AuthoritativeStateOutput,
    ValidationOnly,
    ProvenanceOnly,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ElementRole {
    pub element_id: String,
    pub surface: Surface,
    pub carry_status: Vec<CarryStatus>,
    pub roles: Vec<Role>,
    pub origins: Vec<String>,
    pub update_or_use: String,
    pub read_by_future_transition: bool,
    pub used_in_explicit_emission: bool,
    pub multi_role_collision: bool,
    pub ancestor_binding: String,
    pub evaluability: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EdgeKind {
    Reads,
    Guards,
    Updates,
    Derives,
    Emits,
    Copies,
    Resets,
    Increments,
    Compares,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphNode {
    pub node_id: String,
    pub node_kind: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DependencyEdge {
    pub source: String,
    pub target: String,
    pub kind: EdgeKind,
    pub condition: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DependencyGraph {
    pub schema: &'static str,
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<DependencyEdge>,
    pub edge_kinds_present: Vec<EdgeKind>,
    pub dangling_edge_count: usize,
    pub status: &'static str,
}
