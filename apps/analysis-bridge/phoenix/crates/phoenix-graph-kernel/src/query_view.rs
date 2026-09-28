use crate::{
    chrono_region::{expand_region_for_view, RegionTraversalCaches, RegionTraversalIndex},
    now_ms, KernelEdge, KernelExpandedRegion, KernelGraphSnapshot, KernelRegionProfile,
    KernelVertex, KernelViewRequest, PhoenixGraphKernel,
};
use rustc_hash::{FxHashMap, FxHashSet};
use std::sync::Arc;

#[derive(Clone, Debug, Default)]
pub struct KernelQuerySurface {
    vertices: Vec<KernelVertex>,
    vertex_index: FxHashMap<String, usize>,
    asserted_edges: Vec<KernelEdge>,
    candidate_edges: Vec<KernelEdge>,
    region_traversal_caches: Arc<RegionTraversalCaches>,
}

pub type KernelQueryView = Arc<KernelQuerySurface>;

impl KernelQuerySurface {
    pub fn vertices(&self) -> &[KernelVertex] {
        &self.vertices
    }

    pub fn asserted_edges(&self) -> &[KernelEdge] {
        &self.asserted_edges
    }

    pub fn candidate_edges(&self) -> &[KernelEdge] {
        &self.candidate_edges
    }

    pub fn snapshot(&self) -> KernelGraphSnapshot {
        KernelGraphSnapshot {
            vertices: self.vertices.clone(),
            asserted_edges: self.asserted_edges.clone(),
            candidate_edges: self.candidate_edges.clone(),
        }
    }

    pub(crate) fn vertex_index(&self) -> &FxHashMap<String, usize> {
        &self.vertex_index
    }

    pub(crate) fn region_traversal_index(
        &self,
        profile: KernelRegionProfile,
        edge_allowed: fn(&KernelEdge) -> bool,
    ) -> Arc<RegionTraversalIndex> {
        self.region_traversal_caches
            .get_or_build(self, profile, edge_allowed)
    }

    pub fn find_vertex(&self, vertex_id: &str) -> Option<&KernelVertex> {
        self.vertex_index
            .get(vertex_id)
            .map(|index| &self.vertices[*index])
    }

    pub fn expand_region(
        &self,
        anchor_vertex_ids: &[String],
        seed_vertex_ids: &[String],
        region_node_limit: usize,
        expansion_hops: usize,
        edge_allowed: fn(&KernelEdge) -> bool,
    ) -> KernelExpandedRegion {
        self.expand_region_with_profile(
            anchor_vertex_ids,
            seed_vertex_ids,
            region_node_limit,
            expansion_hops,
            edge_allowed,
            KernelRegionProfile::Generic,
        )
    }

    pub fn expand_region_with_profile(
        &self,
        anchor_vertex_ids: &[String],
        seed_vertex_ids: &[String],
        region_node_limit: usize,
        expansion_hops: usize,
        edge_allowed: fn(&KernelEdge) -> bool,
        profile: KernelRegionProfile,
    ) -> KernelExpandedRegion {
        expand_region_for_view(
            self,
            anchor_vertex_ids,
            seed_vertex_ids,
            region_node_limit,
            expansion_hops,
            edge_allowed,
            profile,
        )
    }
}

impl PhoenixGraphKernel {
    pub fn query_surface(&self, request: KernelViewRequest) -> KernelQueryView {
        let request = canonical_view_request(request);
        if let Some(cached) = self
            .query_surfaces
            .read()
            .expect("kernel query surface cache poisoned")
            .get(&request)
            .cloned()
        {
            return cached;
        }
        let surface = Arc::new(build_query_surface(self, &request));
        let mut cache = self
            .query_surfaces
            .write()
            .expect("kernel query surface cache poisoned");
        cache
            .entry(request)
            .or_insert_with(|| surface.clone())
            .clone()
    }

    pub fn query_view(&self, request: KernelViewRequest) -> KernelQueryView {
        self.query_surface(request)
    }
}

fn canonical_view_request(mut request: KernelViewRequest) -> KernelViewRequest {
    if request.valid_at.is_none() && request.recorded_at.is_none() {
        return request;
    }
    let valid_at = request.valid_at.unwrap_or_else(now_ms);
    request.valid_at = Some(valid_at);
    request.recorded_at = Some(request.recorded_at.unwrap_or(valid_at));
    request
}

fn build_query_surface(
    kernel: &PhoenixGraphKernel,
    request: &KernelViewRequest,
) -> KernelQuerySurface {
    if request.valid_at.is_none() && request.recorded_at.is_none() {
        return build_active_query_surface(kernel, request.include_candidate_graph);
    }
    build_visible_query_surface(
        kernel,
        request
            .valid_at
            .expect("canonical view request should resolve valid_at"),
        request
            .recorded_at
            .expect("canonical view request should resolve recorded_at"),
        request.include_candidate_graph,
    )
}

fn build_active_query_surface(
    kernel: &PhoenixGraphKernel,
    include_candidate_graph: bool,
) -> KernelQuerySurface {
    let mut vertices = kernel.vertices.values().cloned().collect::<Vec<_>>();
    sort_vertices(vertices.as_mut_slice());
    let mut asserted_edges = kernel.asserted_edges.values().cloned().collect::<Vec<_>>();
    sort_edges(asserted_edges.as_mut_slice());
    let mut candidate_edges = if include_candidate_graph {
        kernel.candidate_edges.values().cloned().collect::<Vec<_>>()
    } else {
        Vec::new()
    };
    sort_edges(candidate_edges.as_mut_slice());
    KernelQuerySurface {
        vertex_index: build_vertex_index(vertices.as_slice()),
        vertices,
        asserted_edges,
        candidate_edges,
        region_traversal_caches: Arc::new(RegionTraversalCaches::default()),
    }
}

fn build_visible_query_surface(
    kernel: &PhoenixGraphKernel,
    valid_at: i64,
    tx_at: i64,
    include_candidate_graph: bool,
) -> KernelQuerySurface {
    let mut vertices = kernel
        .vertex_history
        .values()
        .filter_map(|records| {
            records
                .iter()
                .rev()
                .find(|record| record.temporal.is_visible_at(valid_at, tx_at))
                .cloned()
        })
        .collect::<Vec<_>>();
    sort_vertices(vertices.as_mut_slice());
    let visible_vertex_ids = vertices
        .iter()
        .map(|vertex| vertex.id.0.as_str())
        .collect::<FxHashSet<_>>();
    let mut asserted_edges = kernel
        .asserted_edge_history
        .values()
        .filter_map(|records| {
            records
                .iter()
                .rev()
                .find(|record| record.temporal.is_visible_at(valid_at, tx_at))
                .cloned()
        })
        .filter(|edge| {
            visible_vertex_ids.contains(edge.source_id.0.as_str())
                && visible_vertex_ids.contains(edge.target_id.0.as_str())
        })
        .collect::<Vec<_>>();
    sort_edges(asserted_edges.as_mut_slice());
    let mut candidate_edges = if include_candidate_graph {
        kernel
            .candidate_edge_history
            .values()
            .filter_map(|records| {
                records
                    .iter()
                    .rev()
                    .find(|record| record.temporal.is_visible_at(valid_at, tx_at))
                    .cloned()
            })
            .filter(|edge| {
                visible_vertex_ids.contains(edge.source_id.0.as_str())
                    && visible_vertex_ids.contains(edge.target_id.0.as_str())
            })
            .collect::<Vec<_>>()
    } else {
        Vec::new()
    };
    sort_edges(candidate_edges.as_mut_slice());
    KernelQuerySurface {
        vertex_index: build_vertex_index(vertices.as_slice()),
        vertices,
        asserted_edges,
        candidate_edges,
        region_traversal_caches: Arc::new(RegionTraversalCaches::default()),
    }
}

fn sort_vertices(vertices: &mut [KernelVertex]) {
    vertices.sort_by(|left, right| left.id.0.cmp(&right.id.0));
}

fn sort_edges(edges: &mut [KernelEdge]) {
    edges.sort_by(|left, right| {
        left.source_id
            .0
            .cmp(&right.source_id.0)
            .then_with(|| left.target_id.0.cmp(&right.target_id.0))
            .then_with(|| left.edge_type.0.cmp(&right.edge_type.0))
    });
}

fn build_vertex_index(vertices: &[KernelVertex]) -> FxHashMap<String, usize> {
    vertices
        .iter()
        .enumerate()
        .map(|(index, vertex)| (vertex.id.0.clone(), index))
        .collect::<FxHashMap<_, _>>()
}

#[cfg(test)]
mod tests {
    use super::PhoenixGraphKernel;
    use crate::{
        KernelEdge, KernelEdgeType, KernelGraphLayer, KernelMutationBatch, KernelMutationScope,
        KernelVertex, KernelVertexId, KernelViewRequest,
    };
    use std::sync::Arc;

    #[test]
    fn query_view_expand_region_uses_visible_projection_without_full_snapshot() {
        let mut kernel = PhoenixGraphKernel::new();
        kernel
            .apply_kernel_batch(KernelMutationBatch {
                layer: KernelGraphLayer::Asserted,
                scope: KernelMutationScope::Full,
                recorded_at: None,
                vertices: vec![
                    vertex("entity", "entity"),
                    vertex("state", "state"),
                    vertex("claim", "claim"),
                    vertex("event", "event"),
                ],
                edges: vec![
                    edge("entity", "state", "state_of", KernelGraphLayer::Asserted),
                    edge("state", "claim", "supported_by", KernelGraphLayer::Asserted),
                ],
            })
            .expect("apply batch");
        kernel
            .apply_kernel_batch(KernelMutationBatch {
                layer: KernelGraphLayer::Candidate,
                scope: KernelMutationScope::Candidate {
                    scope_key: "test-region".to_owned(),
                },
                recorded_at: None,
                vertices: Vec::new(),
                edges: vec![edge(
                    "claim",
                    "event",
                    "semantic::same_process",
                    KernelGraphLayer::Candidate,
                )],
            })
            .expect("apply candidate batch");

        let view = kernel.query_view(KernelViewRequest {
            include_candidate_graph: true,
            ..KernelViewRequest::default()
        });
        let region =
            view.expand_region(&["entity".to_owned()], &["event".to_owned()], 8, 3, |_| {
                true
            });

        assert_eq!(view.vertices().len(), 4);
        assert_eq!(region.snapshot.vertices.len(), 4);
        assert_eq!(region.snapshot.candidate_edges.len(), 1);
        assert!(region
            .included_vertex_ids
            .iter()
            .any(|vertex_id| vertex_id == "event"));
    }

    #[test]
    fn query_surface_cache_reuses_requests_until_kernel_mutates() {
        let mut kernel = PhoenixGraphKernel::new();
        kernel
            .apply_kernel_batch(KernelMutationBatch {
                layer: KernelGraphLayer::Asserted,
                scope: KernelMutationScope::Full,
                recorded_at: None,
                vertices: vec![vertex("entity", "entity")],
                edges: Vec::new(),
            })
            .expect("apply batch");
        let request = KernelViewRequest {
            include_candidate_graph: true,
            ..KernelViewRequest::default()
        };

        let first = kernel.query_surface(request.clone());
        let second = kernel.query_surface(request.clone());
        assert!(Arc::ptr_eq(&first, &second));

        kernel
            .apply_kernel_batch(KernelMutationBatch {
                layer: KernelGraphLayer::Asserted,
                scope: KernelMutationScope::Session {
                    session_id: "query-cache-test".to_owned(),
                },
                recorded_at: None,
                vertices: vec![vertex("state", "state")],
                edges: vec![edge(
                    "state",
                    "entity",
                    "state_of",
                    KernelGraphLayer::Asserted,
                )],
            })
            .expect("apply session batch");

        let third = kernel.query_surface(request);
        assert!(!Arc::ptr_eq(&first, &third));
        assert_eq!(third.vertices().len(), 2);
    }

    fn vertex(id: &str, kind: &str) -> KernelVertex {
        KernelVertex {
            id: KernelVertexId(id.to_owned()),
            kind: kind.to_owned(),
            ..KernelVertex::default()
        }
    }

    fn edge(source: &str, target: &str, edge_type: &str, layer: KernelGraphLayer) -> KernelEdge {
        KernelEdge {
            source_id: KernelVertexId(source.to_owned()),
            target_id: KernelVertexId(target.to_owned()),
            edge_type: KernelEdgeType(edge_type.to_owned()),
            layer,
            ..KernelEdge::default()
        }
    }
}
