//! Desktop workspace bridge for the native GLiNER BI relation/post model code.
//!
//! This intentionally exposes only the BI-small NER seed pieces needed by the
//! runtime dynamic NER lane, without pulling a second Phoenix workspace graph.

#[path = "../../../../../rust-native/phoenix/crates/phoenix-rel-post/src/gliclass.rs"]
mod gliclass;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-rel-post/src/gliclass_instruct.rs"]
mod gliclass_instruct;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-rel-post/src/gliclass_instruct_format.rs"]
mod gliclass_instruct_format;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-rel-post/src/gliclass_instruct_runtime.rs"]
mod gliclass_instruct_runtime;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-rel-post/src/gliner_bi.rs"]
mod gliner_bi;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-rel-post/src/gliner_bi_tensors.rs"]
mod gliner_bi_tensors;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-rel-post/src/gliner_x.rs"]
mod gliner_x;
#[path = "../../../../../rust-native/phoenix/crates/phoenix-rel-post/src/gliner_x_tensors.rs"]
mod gliner_x_tensors;
#[allow(dead_code)]
#[path = "../../../../../rust-native/phoenix/crates/phoenix-rel-post/src/ort_runtime.rs"]
mod ort_runtime;

pub use gliclass::{
    GliclassClassificationType, GliclassError, GliclassLabelScore, GliclassModel,
    GliclassModelMetadata, GliclassPredictOptions, GliclassPrediction,
};
pub use gliclass_instruct::{
    GliclassInstructError, GliclassInstructMetadata, GliclassInstructModel,
    GliclassInstructPredictOptions,
};
pub use gliclass_instruct_format::{
    build_hierarchical_scores as build_gliclass_instruct_hierarchical_scores,
    flatten_hierarchical_labels as flatten_gliclass_instruct_hierarchical_labels,
    GliclassInstructExample, GliclassInstructLabel,
};
pub use gliner_bi::{
    GlinerBiError, GlinerBiLabelSet, GlinerBiModel, GlinerBiModelMetadata, GlinerBiOverlapPolicy,
    GlinerBiPredictOptions, GlinerBiPrediction, GlinerBiSequencePrediction,
};
pub use gliner_x::{GlinerXError, GlinerXMetadata, GlinerXModel, GlinerXPrediction};
