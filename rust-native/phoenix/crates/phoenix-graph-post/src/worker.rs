use phoenix_semantic_v2::{
    scope_storage_key, CausalScopeSidecar, DirtyScopeRecord, DocumentArchive, DocumentRevisionRef,
    EventIdentityScopeSidecar, GraphDependencyManifest, GraphScopeSidecar, ScopeOrd,
    SessionArchive, TemporalScopeSidecar,
};
use phoenix_store_native_core::{
    PhoenixArchiveStoreV2, PhoenixGraphKernelStoreV2, PhoenixGraphLearningStore,
    PhoenixGraphPatchStore, PhoenixScopeRuntimeStore, ScopeImageSpec, StoreError,
};
use phoenix_types::{ScopeKey, SessionId};
use serde::{Deserialize, Serialize};

use crate::compile::{compile_graph_projection_with_archives, CompiledGraphProjection};
use crate::promotion_lanes::append_graph_projection_commits;

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphScopeReviewBatch {
    pub scope: ScopeKey,
    pub scope_key: String,
    pub scope_ord: ScopeOrd,
    pub session_id: Option<SessionId>,
    pub dirty: Option<DirtyScopeRecord>,
    #[serde(default)]
    pub document_refs: Vec<DocumentRevisionRef>,
    pub event_identity_generation: Option<u64>,
    pub temporal_generation: Option<u64>,
    pub causal_generation: Option<u64>,
    pub memory_generation: Option<u64>,
    pub graph_generation: Option<u64>,
    pub compiled: CompiledGraphProjection,
}

pub fn derive_scope_review_batch(
    archives: &[DocumentArchive],
    session: Option<&SessionArchive>,
    dirty: Option<&DirtyScopeRecord>,
    event_identity_sidecar: Option<&EventIdentityScopeSidecar>,
    temporal_sidecar: Option<&TemporalScopeSidecar>,
    causal_sidecar: Option<&CausalScopeSidecar>,
    memory_sidecar: Option<&phoenix_semantic_v2::MemoryScopeSidecar>,
) -> GraphScopeReviewBatch {
    let scope = archives
        .first()
        .map(|archive| archive.manifest.scope.clone())
        .or_else(|| dirty.as_ref().map(|record| record.scope.clone()))
        .or_else(|| {
            event_identity_sidecar
                .as_ref()
                .map(|value| value.scope.clone())
        })
        .or_else(|| temporal_sidecar.as_ref().map(|value| value.scope.clone()))
        .or_else(|| causal_sidecar.as_ref().map(|value| value.scope.clone()))
        .or_else(|| memory_sidecar.as_ref().map(|value| value.scope.clone()))
        .unwrap_or_default();
    let scope_key = archives
        .first()
        .map(|archive| archive.manifest.scope_key.clone())
        .or_else(|| dirty.as_ref().map(|record| record.scope_key.clone()))
        .or_else(|| {
            event_identity_sidecar
                .as_ref()
                .map(|value| value.scope_key.clone())
        })
        .or_else(|| {
            temporal_sidecar
                .as_ref()
                .map(|value| value.scope_key.clone())
        })
        .or_else(|| causal_sidecar.as_ref().map(|value| value.scope_key.clone()))
        .or_else(|| memory_sidecar.as_ref().map(|value| value.scope_key.clone()))
        .unwrap_or_else(|| scope_storage_key(&scope));
    let scope_ord = archives
        .first()
        .map(|archive| archive.manifest.scope_ord)
        .or_else(|| dirty.as_ref().map(|record| record.scope_ord))
        .or_else(|| {
            event_identity_sidecar
                .as_ref()
                .and_then(|value| value.scope_ord)
        })
        .or_else(|| temporal_sidecar.as_ref().and_then(|value| value.scope_ord))
        .or_else(|| causal_sidecar.as_ref().and_then(|value| value.scope_ord))
        .or_else(|| memory_sidecar.as_ref().and_then(|value| value.scope_ord))
        .unwrap_or_default();
    let session_id = archives
        .iter()
        .find_map(|archive| archive.manifest.session_id.clone())
        .or_else(|| session.map(|value| value.session_id.clone()));
    let document_refs = session
        .map(|value| {
            value
                .document_refs
                .iter()
                .filter(|reference| scope_storage_key(&reference.scope) == scope_key)
                .cloned()
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let recorded_at = [
        event_identity_sidecar.map(|value| value.updated_at),
        temporal_sidecar.map(|value| value.updated_at),
        causal_sidecar.map(|value| value.updated_at),
        memory_sidecar.map(|value| value.updated_at),
    ]
    .into_iter()
    .flatten()
    .max();
    let compiled = compile_graph_projection_with_archives(
        &scope_key,
        archives,
        event_identity_sidecar,
        temporal_sidecar,
        causal_sidecar,
        memory_sidecar,
        recorded_at,
    );

    GraphScopeReviewBatch {
        scope,
        scope_key,
        scope_ord,
        session_id,
        dirty: dirty.cloned(),
        document_refs,
        event_identity_generation: event_identity_sidecar.map(|value| value.generation),
        temporal_generation: temporal_sidecar.map(|value| value.generation),
        causal_generation: causal_sidecar.map(|value| value.generation),
        memory_generation: memory_sidecar.map(|value| value.generation),
        graph_generation: None,
        compiled,
    }
}

pub fn derive_scope_review_batch_from_store<S>(
    store: &S,
    dirty: &DirtyScopeRecord,
    session: Option<&SessionArchive>,
) -> Result<GraphScopeReviewBatch, StoreError>
where
    S: PhoenixScopeRuntimeStore,
{
    let runtime = store.load_scope_runtime_image(dirty, ScopeImageSpec::graph())?;
    let analysis =
        phoenix_scope_analysis::ScopeAnalysisContext::from_runtime_image(runtime, session);
    let mut batch = derive_scope_review_batch(
        analysis.archives(),
        None,
        Some(&analysis.dirty),
        analysis.runtime.sidecars.event_identity.as_ref(),
        analysis.runtime.sidecars.temporal.as_ref(),
        analysis.runtime.sidecars.causal.as_ref(),
        analysis.runtime.sidecars.memory.as_ref(),
    );
    batch.session_id = analysis.session_id.clone();
    batch.document_refs = analysis.document_refs.as_ref().to_vec();
    Ok(batch)
}

pub fn derive_dirty_scope_review_batches<S>(
    store: &S,
    session_id: Option<&SessionId>,
) -> Result<Vec<GraphScopeReviewBatch>, StoreError>
where
    S: PhoenixArchiveStoreV2 + PhoenixScopeRuntimeStore,
{
    let session = match session_id {
        Some(value) => store.load_latest_session_archive(value)?,
        None => None,
    };
    let mut dirty = store.list_dirty_scopes()?;
    dirty.sort_by(|left, right| left.scope_key.cmp(&right.scope_key));
    dirty
        .into_iter()
        .map(|record| derive_scope_review_batch_from_store(store, &record, session.as_ref()))
        .collect()
}

pub fn build_graph_patch_sidecar(
    batch: &GraphScopeReviewBatch,
    created_at: i64,
) -> GraphScopeSidecar {
    let dependency_manifest = graph_dependency_manifest(
        batch.event_identity_generation,
        batch.temporal_generation,
        batch.causal_generation,
        batch.memory_generation,
    );
    GraphScopeSidecar {
        scope: batch.scope.clone(),
        scope_key: batch.scope_key.clone(),
        scope_ord: Some(batch.scope_ord),
        session_id: batch.session_id.clone(),
        updated_at: created_at,
        generation: created_at as u64,
        graph_batch: batch.compiled.graph_batch.clone(),
        dependency_manifest,
        event_identity_generation: dependency_manifest.event_identity_generation,
        temporal_generation: dependency_manifest.temporal_generation,
        causal_generation: dependency_manifest.causal_generation,
        memory_generation: dependency_manifest.memory_generation,
        summary: batch.compiled.summary.clone(),
    }
}

pub fn persist_graph_patch_sidecar<S>(
    store: &S,
    batch: &GraphScopeReviewBatch,
    created_at: i64,
) -> Result<GraphScopeSidecar, StoreError>
where
    S: PhoenixGraphPatchStore + PhoenixGraphKernelStoreV2 + PhoenixGraphLearningStore,
{
    let existing = store.load_graph_patch_sidecar(&batch.scope)?;
    persist_graph_patch_sidecar_with_existing(store, batch, created_at, existing.as_ref())
}

pub fn persist_graph_patch_sidecar_with_existing<S>(
    store: &S,
    batch: &GraphScopeReviewBatch,
    created_at: i64,
    existing: Option<&GraphScopeSidecar>,
) -> Result<GraphScopeSidecar, StoreError>
where
    S: PhoenixGraphPatchStore + PhoenixGraphKernelStoreV2 + PhoenixGraphLearningStore,
{
    let updates = build_graph_patch_sidecar(batch, created_at);
    let merged = match existing {
        Some(existing) => merge_graph_patch_sidecars(existing.clone(), updates),
        None => updates,
    };
    append_graph_projection_commits(store, &merged, created_at)?;
    store.persist_graph_patch_sidecar(&merged)?;
    Ok(merged)
}

pub fn apply_graph_patch_sidecar(batch: &mut GraphScopeReviewBatch, sidecar: &GraphScopeSidecar) {
    batch.graph_generation = Some(sidecar.generation);
    batch.compiled = CompiledGraphProjection {
        graph_batch: sidecar.graph_batch.clone(),
        summary: sidecar.summary.clone(),
    };
}

fn merge_graph_patch_sidecars(
    mut existing: GraphScopeSidecar,
    updates: GraphScopeSidecar,
) -> GraphScopeSidecar {
    let updates_manifest = updates.resolved_dependency_manifest();
    existing.updated_at = existing.updated_at.max(updates.updated_at);
    existing.generation = existing.generation.max(updates.generation);
    existing.graph_batch = updates.graph_batch;
    existing.dependency_manifest = updates_manifest;
    existing.event_identity_generation = updates.event_identity_generation;
    existing.temporal_generation = updates.temporal_generation;
    existing.causal_generation = updates.causal_generation;
    existing.memory_generation = updates.memory_generation;
    existing.summary = updates.summary;
    existing
}

fn graph_dependency_manifest(
    event_identity_generation: Option<u64>,
    temporal_generation: Option<u64>,
    causal_generation: Option<u64>,
    memory_generation: Option<u64>,
) -> GraphDependencyManifest {
    GraphDependencyManifest {
        event_identity_generation,
        temporal_generation,
        causal_generation,
        memory_generation,
        graph_generation: None,
    }
}

#[cfg(test)]
mod tests {
    use phoenix_graph_kernel::{
        KernelEdge, KernelEdgeType, KernelGraphLayer, KernelGraphSnapshot, KernelMutationBatch,
        KernelMutationScope, KernelRelationClass, KernelVertex, KernelVertexClass, KernelVertexId,
        PhoenixGraphKernel,
    };
    use phoenix_semantic_v2::{scope_storage_key, GraphCompilerSummary};
    use phoenix_store_native_core::{PhoenixGraphKernelStoreV2, PhoenixGraphLearningStore};
    use phoenix_store_overgraph::PhoenixOvergraphStore;
    use std::path::PathBuf;

    use crate::promotion_learner::GraphPromotionTrainingConfig;
    use crate::promotion_training::fit_shadow_promotion_model_from_history;

    use super::*;

    #[test]
    fn merge_graph_sidecar_keeps_fresh_projection_payload() {
        let existing = GraphScopeSidecar {
            updated_at: 100,
            generation: 100,
            graph_batch: KernelMutationBatch {
                recorded_at: Some(100),
                ..Default::default()
            },
            summary: GraphCompilerSummary {
                projection_vertex_count: 1,
                ..Default::default()
            },
            ..Default::default()
        };
        let updates = GraphScopeSidecar {
            updated_at: 50,
            generation: 50,
            graph_batch: KernelMutationBatch {
                recorded_at: Some(200),
                ..Default::default()
            },
            dependency_manifest: graph_dependency_manifest(Some(2), Some(3), Some(4), Some(5)),
            event_identity_generation: Some(2),
            temporal_generation: Some(3),
            causal_generation: Some(4),
            memory_generation: Some(5),
            summary: GraphCompilerSummary {
                projection_vertex_count: 2,
                projection_edge_count: 3,
                ..Default::default()
            },
            ..Default::default()
        };

        let merged = merge_graph_patch_sidecars(existing, updates);

        assert_eq!(merged.updated_at, 100);
        assert_eq!(merged.generation, 100);
        assert_eq!(merged.graph_batch.recorded_at, Some(200));
        assert_eq!(
            merged.dependency_manifest,
            graph_dependency_manifest(Some(2), Some(3), Some(4), Some(5))
        );
        assert_eq!(merged.event_identity_generation, Some(2));
        assert_eq!(merged.temporal_generation, Some(3));
        assert_eq!(merged.causal_generation, Some(4));
        assert_eq!(merged.memory_generation, Some(5));
        assert_eq!(merged.summary.projection_vertex_count, 2);
        assert_eq!(merged.summary.projection_edge_count, 3);
    }

    #[test]
    fn graph_projection_commit_rebuilds_after_derived_topology_is_cleared() {
        let store = PhoenixOvergraphStore::open(temp_store_path("graph-post-commit-rebuild"))
            .expect("open store");
        let scope = ScopeKey::default();
        let scope_key = scope_storage_key(&scope);
        let projection_batch = test_projection_batch(&scope_key);
        let batch = GraphScopeReviewBatch {
            scope: scope.clone(),
            scope_key: scope_key.clone(),
            compiled: CompiledGraphProjection {
                graph_batch: projection_batch.clone(),
                summary: GraphCompilerSummary {
                    projection_vertex_count: projection_batch.vertices.len(),
                    projection_edge_count: projection_batch.edges.len(),
                    ..Default::default()
                },
            },
            event_identity_generation: Some(7),
            temporal_generation: Some(11),
            causal_generation: Some(13),
            memory_generation: Some(17),
            ..Default::default()
        };

        persist_graph_patch_sidecar(&store, &batch, 1234).expect("persist graph");
        let committed = store
            .load_live_kernel_snapshot()
            .expect("load committed snapshot");
        let proposed = snapshot_from_graph_truth_commits(&store);

        assert_eq!(committed.vertices, proposed.vertices);
        assert_eq!(committed.asserted_edges, proposed.asserted_edges);
        store
            .publish_kernel_topology(&KernelGraphSnapshot::default())
            .expect("clear derived topology");
        let rebuilt = store
            .publish_kernel_topology(&committed)
            .expect("rebuild topology from commits");
        assert_eq!(rebuilt.vertices, proposed.vertices.len());
        assert_eq!(rebuilt.asserted_edges, proposed.asserted_edges.len());
        assert_eq!(rebuilt.candidate_edges, 0);
        let policy_ids = store
            .load_graph_truth_commits()
            .unwrap()
            .into_iter()
            .map(|commit| commit.header.compiler_policy.policy_id.to_string())
            .collect::<Vec<_>>();
        assert!(policy_ids.len() > 1, "{policy_ids:?}");
        assert_eq!(
            policy_ids.first().map(String::as_str),
            Some("graph-post-promotion:situation-world-state")
        );
        assert!(policy_ids
            .iter()
            .any(|id| id == "graph-post-promotion:reported-facts"));
        assert!(policy_ids
            .iter()
            .any(|id| id == "graph-post-promotion:event-identity-roles"));
        assert!(policy_ids
            .iter()
            .any(|id| id == "graph-post-promotion:temporal-anchors-relations"));
        assert!(policy_ids
            .iter()
            .any(|id| id == "graph-post-promotion:causal-edges"));
        assert!(policy_ids
            .iter()
            .any(|id| id == "graph-post-promotion:cross-document-identity"));
        let receipts = store
            .load_graph_proposal_receipts()
            .expect("load proposal receipts");
        let commits = store
            .load_graph_truth_commits()
            .expect("load graph truth commits");
        assert_eq!(receipts.len(), 1);
        assert!(commits
            .iter()
            .all(|commit| commit.header.receipt_ids.as_slice()
                == std::slice::from_ref(&receipts[0].receipt_id)));
        let before_train = store
            .load_live_kernel_snapshot()
            .expect("snapshot before shadow training");
        let history_model = fit_shadow_promotion_model_from_history(
            "graph-post-projection-shadow-test",
            &receipts,
            &commits,
            GraphPromotionTrainingConfig::default(),
        )
        .expect("fit shadow model from real graph-post projection history");
        let after_train = store
            .load_live_kernel_snapshot()
            .expect("snapshot after shadow training");
        assert_eq!(before_train, after_train);
        assert_eq!(
            history_model.outcome_examples.len(),
            receipts[0].proposals.len()
        );
        assert!(history_model
            .outcome_examples
            .iter()
            .all(|row| row.outcome == phoenix_graph_kernel::GraphProposalOutcomeKind::Active));
    }

    fn snapshot_from_graph_truth_commits(store: &PhoenixOvergraphStore) -> KernelGraphSnapshot {
        let mut kernel = PhoenixGraphKernel::default();
        for commit in store
            .load_graph_truth_commits()
            .expect("load graph truth commits")
        {
            kernel
                .apply_kernel_batch(commit.batch)
                .expect("apply commit batch");
        }
        kernel.snapshot_kernel()
    }

    fn test_projection_batch(scope_key: &str) -> KernelMutationBatch {
        KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Projection {
                scope_key: scope_key.to_owned(),
            },
            recorded_at: Some(1234),
            vertices: vec![
                KernelVertex {
                    id: KernelVertexId("graph::claim::world".to_owned()),
                    kind: "claim".to_owned(),
                    class: KernelVertexClass::Generic,
                    weight: 1,
                    value: serde_json::json!({"modality": "asserted"}),
                    attributes: serde_json::json!({}),
                    ..Default::default()
                },
                KernelVertex {
                    id: KernelVertexId("graph::claim::reported".to_owned()),
                    kind: "claim".to_owned(),
                    class: KernelVertexClass::Generic,
                    weight: 1,
                    value: serde_json::json!({"modality": "reported"}),
                    attributes: serde_json::json!({}),
                    ..Default::default()
                },
                KernelVertex {
                    id: KernelVertexId("graph::event::canonical::cause".to_owned()),
                    kind: "event".to_owned(),
                    class: KernelVertexClass::Event,
                    weight: 1,
                    value: serde_json::json!({"eventType": "canonical"}),
                    attributes: serde_json::json!({}),
                    ..Default::default()
                },
                KernelVertex {
                    id: KernelVertexId("graph::event::memory::effect".to_owned()),
                    kind: "event".to_owned(),
                    class: KernelVertexClass::Event,
                    weight: 1,
                    value: serde_json::json!({"eventType": "memory"}),
                    attributes: serde_json::json!({}),
                    ..Default::default()
                },
                KernelVertex {
                    id: KernelVertexId("graph::time_anchor::anchor::t1".to_owned()),
                    kind: "time_anchor".to_owned(),
                    class: KernelVertexClass::TimeAnchor,
                    weight: 1,
                    value: serde_json::json!({"label": "t1"}),
                    attributes: serde_json::json!({}),
                    ..Default::default()
                },
            ],
            edges: vec![
                test_edge("graph::claim::world", "entity::alice", "subject"),
                test_edge("graph::claim::reported", "entity::bob", "subject"),
                test_edge(
                    "graph::event::canonical::cause",
                    "entity::alice",
                    "role::agent",
                ),
                test_edge(
                    "graph::event::canonical::cause",
                    "graph::time_anchor::anchor::t1",
                    "anchored_by",
                ),
                test_edge(
                    "graph::event::canonical::cause",
                    "graph::event::memory::effect",
                    "causal_link",
                ),
                test_edge(
                    "graph::event::memory::effect",
                    "graph::event::canonical::cause",
                    "canonicalized_as",
                ),
            ],
        }
    }

    fn test_edge(source: &str, target: &str, edge_type: &str) -> KernelEdge {
        KernelEdge {
            source_id: KernelVertexId(source.to_owned()),
            target_id: KernelVertexId(target.to_owned()),
            edge_type: KernelEdgeType(edge_type.to_owned()),
            relation_class: if edge_type == "anchored_by" {
                KernelRelationClass::Temporal
            } else if edge_type == "canonicalized_as" {
                KernelRelationClass::Identity
            } else {
                KernelRelationClass::Semantic
            },
            weight: 1,
            attributes: serde_json::json!({}),
            layer: KernelGraphLayer::Asserted,
            ..Default::default()
        }
    }

    fn temp_store_path(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "phoenix-graph-post-{name}-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ))
    }
}
