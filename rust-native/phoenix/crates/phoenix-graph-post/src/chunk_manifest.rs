use phoenix_chunker_native::ChunkLens;
use phoenix_store_native_core::{ChunkManifest, ChunkManifestDirtyPlan};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LensGraphRebuildPlan {
    pub document_id: String,
    pub rebuild_hints: bool,
    pub rebuild_lenses: Vec<ChunkLens>,
    pub rebuild_graph_edges_only: bool,
    pub preserve_manual_edges: bool,
    pub preserve_accepted_candidates: bool,
    pub preserve_rejected_candidates: bool,
    pub preserve_graph_positions: bool,
    pub preserve_stable_entity_ids: bool,
    pub preserve_stable_chunk_ids: bool,
}

pub fn plan_lens_graph_rebuild(
    previous: Option<&ChunkManifest>,
    current: &ChunkManifest,
) -> LensGraphRebuildPlan {
    LensGraphRebuildPlan::from_dirty_plan(current.dirty_plan_against(previous))
}

impl LensGraphRebuildPlan {
    pub fn from_dirty_plan(dirty: ChunkManifestDirtyPlan) -> Self {
        Self {
            document_id: dirty.document_id,
            rebuild_hints: dirty.rebuild_hints,
            rebuild_lenses: dirty.rebuild_lenses,
            rebuild_graph_edges_only: dirty.rebuild_graph_edges_only,
            preserve_manual_edges: dirty.preserve_manual_edges,
            preserve_accepted_candidates: dirty.preserve_accepted_candidates,
            preserve_rejected_candidates: dirty.preserve_rejected_candidates,
            preserve_graph_positions: dirty.preserve_graph_positions,
            preserve_stable_entity_ids: dirty.preserve_stable_entity_ids,
            preserve_stable_chunk_ids: dirty.preserve_stable_chunk_ids,
        }
    }
}
