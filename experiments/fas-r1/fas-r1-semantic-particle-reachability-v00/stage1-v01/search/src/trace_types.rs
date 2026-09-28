use crate::{MergeMode, SearchAllocationPolicy};
use r1_search::{Arm, RunTrace};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug)]
pub struct Stage1Run {
    pub trace: RunTrace,
    pub manifest: Stage1RunManifest,
    /// Per-expansion diagnostics extending the frozen Stage 0 event schema.
    /// This vector is aligned with `trace.events` and emitted by the v2 writer.
    pub event_diagnostics: Vec<Stage1TraceEventDiagnostic>,
    /// Raw ordering scores for initial and event assignments. These stay out
    /// of Stage 0, where `q_terminal` remains calibrated confidence.
    pub initial_selection_scores: Vec<f64>,
    pub event_selection_scores: Vec<f64>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Stage1RunManifest {
    pub schema: String,
    pub arm: Arm,
    pub merge_mode: MergeMode,
    pub proposal_id: String,
    pub selector_id: String,
    pub value_id: String,
    pub learned_sample_temperature: Option<f64>,
    pub selector_surface: String,
    pub value_surface: String,
    pub value_scoring_policy: String,
    pub particle_allocation_policy: String,
    pub search_allocation_policy: SearchAllocationPolicy,
    pub allocation_trace_semantics: String,
    pub value_evaluated: bool,
    pub selector_calls: u64,
    pub value_calls: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Stage1TraceEventDiagnostic {
    /// The selected particle differs from the nominal round-robin slot.
    pub scheduler_slot_mismatch: bool,
    /// True only when the V_reach max-value fallback selected the particle.
    pub value_based_allocation: bool,
    /// State discarded by the assignment merge, captured before mutation.
    pub merge_loser: Option<MergeParticleSnapshot>,
    /// State retained by the assignment merge, captured before mutation.
    pub merge_kept: Option<MergeParticleSnapshot>,
    /// Particle ID retired by the merge, if the loser had a distinct ID.
    pub merge_retired_particle_id: Option<u32>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct MergeParticleSnapshot {
    pub particle_id: u32,
    pub parent_particle_id: Option<u32>,
    pub ancestry_id: u64,
    pub event_index: Option<u64>,
    pub initial_particle_id: Option<u32>,
    pub depth: u32,
    pub assignment: Vec<u8>,
    pub latent_state: Vec<f32>,
    pub value: f32,
}
