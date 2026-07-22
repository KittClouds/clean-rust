use phoenix_graph_kernel::{
    KernelGraphSnapshot, KernelQueryView, KernelViewRequest, PhoenixGraphKernel,
};
use phoenix_semantic_v2::{GraphScopeSidecar, SemanticGraphScopeSidecar};
use phoenix_store_native_core::{
    PhoenixGraphKernelStoreV2, PhoenixGraphPatchStore, PhoenixSemanticGraphPatchStore,
};
use phoenix_types::ScopeKey;
use rustc_hash::FxHashMap;
use std::cell::RefCell;
use std::sync::Arc;

use crate::api::{
    candidate_graph_batch_for_query, load_projection_kernel,
    projection_kernel_from_committed_snapshot, GraphQueryError,
};
use crate::query_units::{QueryUnitIndexCacheKey, QueryUnitLexicalIndex};
use crate::retrieval::GraphRetrievedSeed;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub(crate) enum SeedQuerySurface {
    QueryText(String),
    EntitySlot { entity_id: String, slot_key: String },
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub(crate) struct SeedQueryCacheKey {
    pub surface: SeedQuerySurface,
    pub valid_at: Option<i64>,
    pub recorded_at: Option<i64>,
    pub include_candidate_graph: bool,
    pub kinds: Vec<String>,
    pub seed_limit: usize,
    pub oversample: usize,
}

#[derive(Default)]
struct ScopeRetrievalCache {
    seed_surfaces: FxHashMap<SeedQueryCacheKey, Vec<GraphRetrievedSeed>>,
    query_embeddings: FxHashMap<String, Vec<f32>>,
    lexical_indexes: FxHashMap<QueryUnitIndexCacheKey, Arc<QueryUnitLexicalIndex>>,
}

pub struct ScopeQuerySession {
    scope: ScopeKey,
    kernel: PhoenixGraphKernel,
    retrieval_cache: RefCell<ScopeRetrievalCache>,
}

impl ScopeQuerySession {
    pub fn scope(&self) -> &ScopeKey {
        &self.scope
    }

    pub fn view_as_of(&self, request: KernelViewRequest) -> KernelGraphSnapshot {
        self.kernel.view_as_of(request)
    }

    pub(crate) fn query_surface(&self, request: KernelViewRequest) -> KernelQueryView {
        self.kernel.query_view(request)
    }

    pub(crate) fn kernel(&self) -> &PhoenixGraphKernel {
        &self.kernel
    }

    pub(crate) fn cached_seed_surface(
        &self,
        key: &SeedQueryCacheKey,
    ) -> Option<Vec<GraphRetrievedSeed>> {
        self.retrieval_cache
            .borrow()
            .seed_surfaces
            .get(key)
            .cloned()
    }

    pub(crate) fn store_seed_surface(&self, key: SeedQueryCacheKey, seeds: &[GraphRetrievedSeed]) {
        self.retrieval_cache
            .borrow_mut()
            .seed_surfaces
            .insert(key, seeds.to_vec());
    }

    pub(crate) fn cached_query_embedding(&self, query_text: &str) -> Option<Vec<f32>> {
        self.retrieval_cache
            .borrow()
            .query_embeddings
            .get(query_text)
            .cloned()
    }

    pub(crate) fn store_query_embedding(&self, query_text: &str, embedding: &[f32]) {
        self.retrieval_cache
            .borrow_mut()
            .query_embeddings
            .insert(query_text.to_owned(), embedding.to_vec());
    }

    pub(crate) fn cached_query_unit_index(
        &self,
        key: &QueryUnitIndexCacheKey,
    ) -> Option<Arc<QueryUnitLexicalIndex>> {
        self.retrieval_cache
            .borrow()
            .lexical_indexes
            .get(key)
            .cloned()
    }

    pub(crate) fn store_query_unit_index(
        &self,
        key: QueryUnitIndexCacheKey,
        index: Arc<QueryUnitLexicalIndex>,
    ) {
        self.retrieval_cache
            .borrow_mut()
            .lexical_indexes
            .insert(key, index);
    }
}

pub fn open_scope_query_session<S>(
    store: &S,
    scope: &ScopeKey,
) -> Result<Option<ScopeQuerySession>, GraphQueryError>
where
    S: PhoenixGraphPatchStore + PhoenixSemanticGraphPatchStore + PhoenixGraphKernelStoreV2,
{
    let Some(kernel) = load_projection_kernel(store, scope)? else {
        return Ok(None);
    };
    Ok(Some(ScopeQuerySession {
        scope: scope.clone(),
        kernel,
        retrieval_cache: RefCell::new(ScopeRetrievalCache::default()),
    }))
}

pub fn open_scope_query_session_from_committed_snapshot(
    scope: &ScopeKey,
    snapshot: KernelGraphSnapshot,
    graph_sidecar: Option<&GraphScopeSidecar>,
    semantic_sidecar: Option<&SemanticGraphScopeSidecar>,
) -> Result<ScopeQuerySession, GraphQueryError> {
    let candidate_graph_batch = graph_sidecar
        .and_then(|sidecar| candidate_graph_batch_for_query(sidecar, semantic_sidecar));
    let kernel = projection_kernel_from_committed_snapshot(snapshot, candidate_graph_batch)?;
    Ok(ScopeQuerySession {
        scope: scope.clone(),
        kernel,
        retrieval_cache: RefCell::new(ScopeRetrievalCache::default()),
    })
}

#[cfg(test)]
mod tests {
    use phoenix_graph_kernel::{
        KernelEdge, KernelEdgeType, KernelGraphLayer, KernelMutationBatch, KernelMutationScope,
        KernelProvenance, KernelRelationClass, KernelVertex, KernelVertexClass, KernelVertexId,
        KernelViewRequest,
    };
    use phoenix_semantic_v2::{GraphDependencyManifest, SemanticGraphScopeSidecar};

    use super::*;

    fn candidate_batch(edge_id: &str) -> KernelMutationBatch {
        KernelMutationBatch {
            layer: KernelGraphLayer::Candidate,
            scope: KernelMutationScope::Candidate {
                scope_key: "scope".to_owned(),
            },
            recorded_at: Some(11),
            vertices: vec![
                KernelVertex {
                    id: KernelVertexId("graph::state::1".to_owned()),
                    kind: "state".to_owned(),
                    class: KernelVertexClass::State,
                    labels: Vec::new(),
                    weight: 1,
                    value: serde_json::json!({}),
                    attributes: serde_json::json!({}),
                    temporal: Default::default(),
                    provenance: KernelProvenance::default(),
                    entity_id: None,
                    search_chunk_id: None,
                    document_id: None,
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    chapter_id: None,
                    chapters: Vec::new(),
                    boundary_id: None,
                    boundary_ordinal: None,
                    boundary_kind: None,
                    boundary_ordinals: Vec::new(),
                    entity_facet: None,
                    calendar_facet: None,
                },
                KernelVertex {
                    id: KernelVertexId("graph::state::2".to_owned()),
                    kind: "state".to_owned(),
                    class: KernelVertexClass::State,
                    labels: Vec::new(),
                    weight: 1,
                    value: serde_json::json!({}),
                    attributes: serde_json::json!({}),
                    temporal: Default::default(),
                    provenance: KernelProvenance::default(),
                    entity_id: None,
                    search_chunk_id: None,
                    document_id: None,
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    chapter_id: None,
                    chapters: Vec::new(),
                    boundary_id: None,
                    boundary_ordinal: None,
                    boundary_kind: None,
                    boundary_ordinals: Vec::new(),
                    entity_facet: None,
                    calendar_facet: None,
                },
            ],
            edges: vec![KernelEdge {
                source_id: KernelVertexId("graph::state::1".to_owned()),
                target_id: KernelVertexId("graph::state::2".to_owned()),
                edge_type: KernelEdgeType(edge_id.to_owned()),
                relation_class: KernelRelationClass::Candidate,
                weight: 1,
                attributes: serde_json::json!({}),
                data: None,
                document_id: None,
                note_id: None,
                narrative_id: None,
                folder_id: None,
                folder_path: None,
                layer: KernelGraphLayer::Candidate,
                temporal: Default::default(),
                provenance: KernelProvenance::default(),
                resolution_facet: None,
            }],
        }
    }

    fn empty_snapshot() -> KernelGraphSnapshot {
        KernelGraphSnapshot::default()
    }

    #[test]
    fn open_session_from_committed_snapshot_reuses_loaded_projection_inputs() {
        let scope = ScopeKey {
            world_id: Some("world".to_owned()),
            ..Default::default()
        };

        let session =
            open_scope_query_session_from_committed_snapshot(&scope, empty_snapshot(), None, None)
                .unwrap();
        let snapshot = session.view_as_of(KernelViewRequest {
            valid_at: None,
            recorded_at: None,
            include_candidate_graph: true,
        });

        assert_eq!(session.scope(), &scope);
        assert!(snapshot.vertices.is_empty());
        assert!(snapshot.asserted_edges.is_empty());
        assert!(snapshot.candidate_edges.is_empty());
    }

    #[test]
    fn session_cache_round_trips_seed_surfaces() {
        let scope = ScopeKey {
            world_id: Some("world".to_owned()),
            ..Default::default()
        };
        let graph_sidecar = GraphScopeSidecar {
            scope: scope.clone(),
            ..Default::default()
        };
        let session = open_scope_query_session_from_committed_snapshot(
            &scope,
            empty_snapshot(),
            Some(&graph_sidecar),
            None,
        )
        .unwrap();
        let key = SeedQueryCacheKey {
            surface: SeedQuerySurface::EntitySlot {
                entity_id: "alice".to_owned(),
                slot_key: "entity.employer".to_owned(),
            },
            valid_at: Some(42),
            recorded_at: Some(64),
            include_candidate_graph: true,
            kinds: vec!["claim".to_owned(), "state".to_owned()],
            seed_limit: 8,
            oversample: 20,
        };
        let seeds = vec![GraphRetrievedSeed {
            node_id: "graph::state::1".to_owned(),
            node_kind: "state".to_owned(),
            score_millis: 950,
            distance_millis: 50,
            document_id: None,
            narrative_id: None,
            evidence_refs: Vec::new(),
        }];

        assert!(session.cached_seed_surface(&key).is_none());
        session.store_seed_surface(key.clone(), &seeds);
        assert_eq!(session.cached_seed_surface(&key), Some(seeds));
    }

    #[test]
    fn session_cache_round_trips_query_embeddings() {
        let scope = ScopeKey {
            world_id: Some("world".to_owned()),
            ..Default::default()
        };
        let graph_sidecar = GraphScopeSidecar {
            scope: scope.clone(),
            ..Default::default()
        };
        let session = open_scope_query_session_from_committed_snapshot(
            &scope,
            empty_snapshot(),
            Some(&graph_sidecar),
            None,
        )
        .unwrap();
        let embedding = vec![0.25_f32, 0.5, 0.75];

        assert!(session
            .cached_query_embedding("current entity.role for alice")
            .is_none());
        session.store_query_embedding("current entity.role for alice", &embedding);
        assert_eq!(
            session.cached_query_embedding("current entity.role for alice"),
            Some(embedding)
        );
    }

    #[test]
    fn session_cache_round_trips_query_unit_indexes() {
        let scope = ScopeKey {
            world_id: Some("world".to_owned()),
            ..Default::default()
        };
        let graph_sidecar = GraphScopeSidecar {
            scope: scope.clone(),
            ..Default::default()
        };
        let session = open_scope_query_session_from_committed_snapshot(
            &scope,
            empty_snapshot(),
            Some(&graph_sidecar),
            None,
        )
        .unwrap();
        let key = QueryUnitIndexCacheKey {
            valid_at: None,
            recorded_at: None,
            include_candidate_graph: true,
            kinds: vec!["chunk".to_owned(), "state".to_owned()],
        };
        let index = Arc::new(QueryUnitLexicalIndex::for_tests(&[
            ("graph::chunk::1", "chunk", "alice moved to the harbor"),
            ("graph::state::1", "state", "alice at harbor"),
        ]));

        assert!(session.cached_query_unit_index(&key).is_none());
        session.store_query_unit_index(key.clone(), index.clone());
        let cached = session
            .cached_query_unit_index(&key)
            .expect("cached lexical index");
        assert!(Arc::ptr_eq(&cached, &index));
    }

    #[test]
    fn session_query_surface_reuses_the_same_cached_arc() {
        let scope = ScopeKey {
            world_id: Some("world".to_owned()),
            ..Default::default()
        };
        let graph_sidecar = GraphScopeSidecar {
            scope: scope.clone(),
            ..Default::default()
        };
        let session = open_scope_query_session_from_committed_snapshot(
            &scope,
            empty_snapshot(),
            Some(&graph_sidecar),
            None,
        )
        .unwrap();
        let request = KernelViewRequest {
            include_candidate_graph: true,
            ..KernelViewRequest::default()
        };

        let first = session.query_surface(request.clone());
        let second = session.query_surface(request);
        assert!(Arc::ptr_eq(&first, &second));
    }

    #[test]
    fn stale_semantic_sidecar_is_excluded_from_query_session() {
        let scope = ScopeKey {
            world_id: Some("world".to_owned()),
            ..Default::default()
        };
        let graph_sidecar = GraphScopeSidecar {
            scope: scope.clone(),
            generation: 10,
            dependency_manifest: GraphDependencyManifest {
                event_identity_generation: Some(2),
                memory_generation: Some(3),
                ..Default::default()
            },
            ..Default::default()
        };
        let semantic_sidecar = SemanticGraphScopeSidecar {
            scope: scope.clone(),
            dependency_manifest: GraphDependencyManifest {
                graph_generation: Some(9),
                event_identity_generation: Some(2),
                memory_generation: Some(3),
                ..Default::default()
            },
            candidate_graph_batch: candidate_batch("semantic::same_process"),
            ..Default::default()
        };

        assert!(crate::api::candidate_graph_batch_for_query(
            &graph_sidecar,
            Some(&semantic_sidecar)
        )
        .is_none());
    }

    #[test]
    fn fresh_semantic_sidecar_is_visible_in_query_session() {
        let scope = ScopeKey {
            world_id: Some("world".to_owned()),
            ..Default::default()
        };
        let graph_sidecar = GraphScopeSidecar {
            scope: scope.clone(),
            generation: 10,
            dependency_manifest: GraphDependencyManifest {
                event_identity_generation: Some(2),
                memory_generation: Some(3),
                ..Default::default()
            },
            ..Default::default()
        };
        let semantic_sidecar = SemanticGraphScopeSidecar {
            scope: scope.clone(),
            dependency_manifest: GraphDependencyManifest {
                graph_generation: Some(10),
                event_identity_generation: Some(2),
                memory_generation: Some(3),
                ..Default::default()
            },
            candidate_graph_batch: candidate_batch("semantic::same_process"),
            ..Default::default()
        };

        let batch =
            crate::api::candidate_graph_batch_for_query(&graph_sidecar, Some(&semantic_sidecar))
                .expect("fresh semantic batch");

        assert_eq!(batch.edges.len(), 1);
        assert_eq!(batch.edges[0].edge_type.0, "semantic::same_process");
        assert_eq!(semantic_sidecar.scope, scope);
    }
}
