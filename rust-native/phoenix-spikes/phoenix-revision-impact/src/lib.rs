//! Deterministic identity, counterfactual overlays, and revision-analysis views.

pub mod adapter;
pub mod corpus_experiment;
pub mod detector;
pub mod identity;
pub mod inference_adapter;
pub mod overlay;
pub mod projection;
pub mod repair;
pub mod repair_directive;
pub mod repair_shadow;
mod repair_shadow_capability;
mod repair_shadow_deception;
mod repair_shadow_possession;
mod repair_shadow_prior_record;
mod repair_shadow_relationship;
mod repair_shadow_travel;
pub mod repair_simulation;
pub mod repair_source;
pub mod ripple;
pub mod truth_adapter;

pub use adapter::*;
pub use corpus_experiment::*;
pub use detector::*;
pub use identity::*;
pub use inference_adapter::*;
pub use overlay::*;
pub use projection::*;
pub use repair::*;
pub use repair_directive::*;
pub use repair_shadow::*;
pub use repair_shadow_capability::{
    CapabilityCost, CapabilityMode, CapabilityRuleRecord, KAI_POWER_OVERDRAW_DIRECTIVE_ID,
};
pub use repair_shadow_deception::TAMSIN_DECEPTION_DIRECTIVE_ID;
pub use repair_shadow_possession::{
    DuplicateClaimStatus, ObjectIdentityRuleRecord, HAZEL_KEY_DIRECTIVE_ID,
};
pub use repair_shadow_prior_record::MARA_PRIOR_RECORD_DIRECTIVE_ID;
pub use repair_shadow_relationship::HAZEL_ESPIONAGE_DIRECTIVE_ID;
pub use repair_shadow_travel::{
    TravelActivationCost, TravelMode, TravelRuleRecord, CONSTRAINED_PORTAL_DIRECTIVE_ID,
};
pub use repair_simulation::*;
pub use repair_source::*;
pub use ripple::*;
pub use truth_adapter::*;
