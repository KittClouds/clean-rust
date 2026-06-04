mod build;
mod commitment;
mod compression;
mod contracts;
mod dual_write;
mod ids;
mod prepared;
mod projection;
mod relationship;
mod types;
mod verify;

use compact_str::CompactString;
use thiserror::Error;

use crate::types::GraphRebuildSnapshot;

pub use build::compile_graph_snapshot;
pub use dual_write::{compile_dual_write_snapshot, project_ui_edges, GraphCompilerDualWrite};
pub use types::{
    BundleCommitmentInput, BundleCommitmentPoint, BundleCommitmentPolicy, BundleCompressionInput,
    BundleCompressionModel, BundleCompressionPolicy, BundleEmbedding, BundlePrototype,
    BundleRerankScore, BundleRerankSource, EvidenceAnchor, EvidenceBundleKind, EvidenceKind,
    FactBundle, FactBundleCommitment, FactBundleCompression, FactBundlePrototypeScore, FactLane,
    FactRole, GraphAtom, GraphAtomKind, GraphCompileCounters, GraphCompileReceipts,
    GraphCompilerInput, GraphCompilerOutput, GraphPrototypeFamily, GraphRootReceipt,
    ProjectedGraphEdge, RelationFact,
};
pub use verify::{assert_graph_compile_invariants, verify_graph_compile_output};

#[derive(Debug, Error)]
pub enum GraphCompilerError {
    #[error("graph compiler invariant failed: {0}")]
    Invariant(CompactString),
}

pub fn compile_legacy_snapshot(snapshot: &GraphRebuildSnapshot) -> GraphCompilerOutput {
    compile_graph_snapshot(GraphCompilerInput {
        scope_kind: snapshot.scope_kind,
        scope_id: snapshot.scope_id.as_str(),
        built_at: snapshot.built_at,
        note_ids: &snapshot.note_ids,
        chunks: &snapshot.chunks,
        surface_hits: &[],
        mentions: &snapshot.mentions,
        mention_graph: None,
        lens_frames: &[],
        entity_anchors: &snapshot.entity_anchors,
        nodes: &snapshot.nodes,
        relationships: &snapshot.relationships,
        events: &snapshot.events,
        temporal_edges: &snapshot.temporal_edges,
        causal_edges: &snapshot.causal_edges,
        memory_state: &snapshot.memory_state,
        calendar_registry: snapshot.calendar_registry_summary.as_ref(),
        legacy_edges: &snapshot.edges,
        bundle_compression: None,
        bundle_commitment: None,
    })
}

pub fn compile_legacy_snapshot_strict(
    snapshot: &GraphRebuildSnapshot,
) -> Result<GraphCompilerOutput, GraphCompilerError> {
    let output = compile_legacy_snapshot(snapshot);
    assert_graph_compile_invariants(&output).map_err(GraphCompilerError::Invariant)?;
    Ok(output)
}
