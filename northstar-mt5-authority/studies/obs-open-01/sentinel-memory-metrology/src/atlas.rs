//! Atlas computation is intentionally implemented in `metrology` so one streaming
//! pass owns state reconstruction, collision accounting, and descriptive morphology.
//! This module is retained as a sealed boundary for future atlas-only projections.

pub const ATLAS_AUTHORITY: &str = "D_A_OBSERVED_NO_OUTCOME_JOIN";
