use phoenix_graph_kernel::{
    KernelEdge, KernelQuerySurface, KernelRegionProfile, KernelViewRequest,
};
use phoenix_store_native_core::{
    PhoenixGraphKernelStoreV2, PhoenixGraphPatchStore, PhoenixLexicalQueryStore,
    PhoenixSemanticGraphPatchStore, PhoenixSemanticIndexStore,
};
use phoenix_types::ScopeKey;

use crate::api::{
    rank_causal_explanation_answer, GraphCausalExplanationQueryRequest, GraphQueryError,
};
use crate::phase4_graph_scoring::apply_graph_structural_causal;
use crate::phase4_scoring::apply_phase4_causal;
use crate::query_session::{ScopeQuerySession, SeedQuerySurface};
use crate::retrieval::{
    open_retrieved_query_session, GraphRetrievedCausalExplanationAnswer,
    GraphRetrievedCausalExplanationQueryRequest, GraphRetrievedSeed,
};
use crate::retrieval_common::{
    build_region_from_snapshot, build_region_from_view_profile, graph_local_target_seeds,
    retrieve_query_seeds_with_session,
};
use crate::runtime_telemetry::{measure_graph_runtime, GraphRuntimeMetric};

const CAUSAL_RETRIEVAL_KINDS: [&str; 5] = ["event", "claim", "entity", "chunk", "state"];

pub(crate) fn retrieved_causal_explanation_impl<S>(
    store: &S,
    scope: &ScopeKey,
    request: &GraphRetrievedCausalExplanationQueryRequest,
) -> Result<Option<GraphRetrievedCausalExplanationAnswer>, GraphQueryError>
where
    S: PhoenixGraphPatchStore
        + PhoenixGraphKernelStoreV2
        + PhoenixLexicalQueryStore
        + PhoenixSemanticGraphPatchStore
        + PhoenixSemanticIndexStore,
{
    let Some(session) = open_retrieved_query_session(store, scope)? else {
        return Ok(None);
    };
    retrieved_causal_explanation_with_session_impl(store, &session, request)
}

pub(crate) fn retrieved_causal_explanation_with_session_impl<S>(
    store: &S,
    session: &ScopeQuerySession,
    request: &GraphRetrievedCausalExplanationQueryRequest,
) -> Result<Option<GraphRetrievedCausalExplanationAnswer>, GraphQueryError>
where
    S: PhoenixLexicalQueryStore + PhoenixSemanticIndexStore,
{
    let _timer = measure_graph_runtime(GraphRuntimeMetric::RetrievedCausalExplanation);
    let view_request = KernelViewRequest {
        valid_at: request.valid_at,
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
    };
    let view = {
        let _timer = measure_graph_runtime(GraphRuntimeMetric::BuildQueryView);
        session.query_surface(view_request.clone())
    };
    let mut seeds =
        graph_local_target_seeds(&view, request.target_vertex_id.as_str(), request.seed_limit);
    if seeds.is_empty() {
        seeds = retrieve_query_seeds_with_session(
            store,
            session,
            request.query_text.as_str(),
            &CAUSAL_RETRIEVAL_KINDS,
            request.seed_limit,
            request.oversample,
            SeedQuerySurface::QueryText(request.query_text.clone()),
            view_request,
            &view,
        )?;
    }
    let (region_snapshot, region) = build_causal_region_from_view(&view, request, &seeds);
    let query = GraphCausalExplanationQueryRequest {
        target_vertex_id: request.target_vertex_id.clone(),
        valid_at: request.valid_at,
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
        max_depth: request.max_depth,
        limit: request.limit,
        truth_plane: request.truth_plane,
    };
    let ranked = {
        let _timer = measure_graph_runtime(GraphRuntimeMetric::RankedCausalExplanation);
        let mut ranked = rank_causal_explanation_answer(&query, &region_snapshot);
        apply_phase4_causal(
            request.query_text.as_str(),
            &region_snapshot.vertices,
            &mut ranked,
        );
        apply_graph_structural_causal(
            region.anchor_vertex_ids.as_slice(),
            &region_snapshot,
            &mut ranked,
        );
        ranked
    };
    Ok(Some(GraphRetrievedCausalExplanationAnswer {
        query_text: request.query_text.clone(),
        answer: ranked,
        query,
        seeds,
        region,
    }))
}

pub(crate) fn build_causal_region(
    snapshot: &phoenix_graph_kernel::KernelGraphSnapshot,
    request: &GraphRetrievedCausalExplanationQueryRequest,
    seeds: &[GraphRetrievedSeed],
) -> (
    phoenix_graph_kernel::KernelGraphSnapshot,
    crate::retrieval::GraphRetrievedRegion,
) {
    let mut anchors = vec![request.target_vertex_id.clone()];
    if let Some(target) = snapshot
        .vertices
        .iter()
        .find(|vertex| vertex.id.0 == request.target_vertex_id)
    {
        if let Some(entity_id) = target.entity_id.as_deref() {
            anchors.extend(
                snapshot
                    .vertices
                    .iter()
                    .filter(|vertex| {
                        vertex.kind == "entity" && vertex.entity_id.as_deref() == Some(entity_id)
                    })
                    .map(|vertex| vertex.id.0.clone()),
            );
        }
    }
    anchors.sort();
    anchors.dedup();
    build_region_from_snapshot(
        snapshot,
        anchors,
        seeds,
        request.region_node_limit,
        request.expansion_hops,
        causal_edge_allowed,
    )
}

pub(crate) fn build_causal_region_from_view(
    view: &KernelQuerySurface,
    request: &GraphRetrievedCausalExplanationQueryRequest,
    seeds: &[GraphRetrievedSeed],
) -> (
    phoenix_graph_kernel::KernelGraphSnapshot,
    crate::retrieval::GraphRetrievedRegion,
) {
    let mut anchors = {
        let _timer = measure_graph_runtime(GraphRuntimeMetric::CollectRegionAnchors);
        let mut anchors = vec![request.target_vertex_id.clone()];
        if let Some(target) = view.find_vertex(request.target_vertex_id.as_str()) {
            if let Some(entity_id) = target.entity_id.as_deref() {
                anchors.extend(
                    view.vertices()
                        .iter()
                        .filter(|vertex| {
                            vertex.kind == "entity"
                                && vertex.entity_id.as_deref() == Some(entity_id)
                        })
                        .map(|vertex| vertex.id.0.clone()),
                );
            }
        }
        anchors
    };
    anchors.sort();
    anchors.dedup();
    build_region_from_view_profile(
        view,
        anchors,
        seeds,
        request.region_node_limit,
        request.expansion_hops,
        causal_edge_allowed,
        KernelRegionProfile::Causal,
    )
}

pub(crate) fn causal_edge_allowed(edge: &KernelEdge) -> bool {
    matches!(
        edge.edge_type.0.as_str(),
        "causal_link" | "supported_by" | "canonicalized_as" | "subject" | "object" | "under_view"
    ) || matches!(
        edge.edge_type.0.as_str(),
        "semantic::same_process"
            | "semantic::related_event"
            | "semantic::missing_intermediate_cause"
    )
}
