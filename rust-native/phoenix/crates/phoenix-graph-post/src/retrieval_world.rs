use phoenix_graph_kernel::{
    slot_at_snapshot, KernelEdge, KernelQuerySurface, KernelRegionProfile, KernelSlotQueryRequest,
    KernelViewRequest,
};
use phoenix_store_native_core::{
    PhoenixGraphKernelStoreV2, PhoenixGraphPatchStore, PhoenixLexicalQueryStore,
    PhoenixSemanticGraphPatchStore, PhoenixSemanticIndexStore,
};
use phoenix_types::ScopeKey;

use crate::api::{rank_world_state_answer, GraphQueryError, GraphWorldStateQueryRequest};
use crate::phase4_graph_scoring::apply_graph_structural_world_state;
use crate::phase4_scoring::apply_phase4_world_state;
use crate::query_session::{ScopeQuerySession, SeedQuerySurface};
use crate::retrieval::{
    open_retrieved_query_session, GraphRetrievedWorldStateAnswer,
    GraphRetrievedWorldStateQueryRequest,
};
use crate::retrieval_common::{
    build_region_from_snapshot, build_region_from_view_profile, graph_local_entity_slot_seeds,
    retrieve_query_seeds_with_session,
};
use crate::runtime_telemetry::{measure_graph_runtime, GraphRuntimeMetric};

const WORLD_RETRIEVAL_KINDS: [&str; 5] = ["state", "claim", "event", "chunk", "entity"];

pub(crate) fn retrieved_world_state_impl<S>(
    store: &S,
    scope: &ScopeKey,
    request: &GraphRetrievedWorldStateQueryRequest,
) -> Result<Option<GraphRetrievedWorldStateAnswer>, GraphQueryError>
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
    retrieved_world_state_with_session_impl(store, &session, request)
}

pub(crate) fn retrieved_world_state_with_session_impl<S>(
    store: &S,
    session: &ScopeQuerySession,
    request: &GraphRetrievedWorldStateQueryRequest,
) -> Result<Option<GraphRetrievedWorldStateAnswer>, GraphQueryError>
where
    S: PhoenixLexicalQueryStore + PhoenixSemanticIndexStore,
{
    let _timer = measure_graph_runtime(GraphRuntimeMetric::RetrievedWorldState);
    let view_request = world_view_request(request);
    let view = {
        let _timer = measure_graph_runtime(GraphRuntimeMetric::BuildQueryView);
        session.query_surface(view_request.clone())
    };
    let mut seeds = graph_local_entity_slot_seeds(
        &view,
        request.entity_id.as_str(),
        request.slot_key.as_str(),
        request.seed_limit,
    );
    if seeds.is_empty() {
        seeds = retrieve_query_seeds_with_session(
            store,
            session,
            request.query_text.as_str(),
            &WORLD_RETRIEVAL_KINDS,
            request.seed_limit,
            request.oversample,
            world_seed_surface(request),
            view_request,
            &view,
        )?;
    }
    Ok(Some(answer_world_state_from_view(&view, request, seeds)))
}

pub(crate) fn build_world_state_region(
    snapshot: &phoenix_graph_kernel::KernelGraphSnapshot,
    request: &GraphRetrievedWorldStateQueryRequest,
    seeds: &[crate::retrieval::GraphRetrievedSeed],
) -> (
    phoenix_graph_kernel::KernelGraphSnapshot,
    crate::retrieval::GraphRetrievedRegion,
) {
    let anchors = snapshot
        .vertices
        .iter()
        .filter(|vertex| vertex.entity_id.as_deref() == Some(request.entity_id.as_str()))
        .filter(|vertex| {
            vertex.kind == "entity" || slot_key_of(vertex) == Some(request.slot_key.as_str())
        })
        .map(|vertex| vertex.id.0.clone())
        .collect::<Vec<_>>();
    build_region_from_snapshot(
        snapshot,
        anchors,
        seeds,
        request.region_node_limit,
        request.expansion_hops,
        world_state_edge_allowed,
    )
}

pub(crate) fn build_world_state_region_from_view(
    view: &KernelQuerySurface,
    request: &GraphRetrievedWorldStateQueryRequest,
    seeds: &[crate::retrieval::GraphRetrievedSeed],
) -> (
    phoenix_graph_kernel::KernelGraphSnapshot,
    crate::retrieval::GraphRetrievedRegion,
) {
    let anchors = {
        let _timer = measure_graph_runtime(GraphRuntimeMetric::CollectRegionAnchors);
        view.vertices()
            .iter()
            .filter(|vertex| vertex.entity_id.as_deref() == Some(request.entity_id.as_str()))
            .filter(|vertex| {
                vertex.kind == "entity" || slot_key_of(vertex) == Some(request.slot_key.as_str())
            })
            .map(|vertex| vertex.id.0.clone())
            .collect::<Vec<_>>()
    };
    build_region_from_view_profile(
        view,
        anchors,
        seeds,
        request.region_node_limit,
        request.expansion_hops,
        world_state_edge_allowed,
        KernelRegionProfile::WorldState,
    )
}

fn slot_key_of(vertex: &phoenix_graph_kernel::KernelVertex) -> Option<&str> {
    vertex
        .value
        .get("slotKey")
        .and_then(serde_json::Value::as_str)
        .or_else(|| {
            vertex
                .attributes
                .get("slotKey")
                .and_then(serde_json::Value::as_str)
        })
}

pub(crate) fn world_seed_surface(
    request: &GraphRetrievedWorldStateQueryRequest,
) -> SeedQuerySurface {
    SeedQuerySurface::EntitySlot {
        entity_id: request.entity_id.clone(),
        slot_key: request.slot_key.clone(),
    }
}

pub(crate) fn world_view_request(
    request: &GraphRetrievedWorldStateQueryRequest,
) -> KernelViewRequest {
    KernelViewRequest {
        valid_at: request.valid_at,
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
    }
}

pub(crate) fn answer_world_state_from_view(
    view: &KernelQuerySurface,
    request: &GraphRetrievedWorldStateQueryRequest,
    seeds: Vec<crate::retrieval::GraphRetrievedSeed>,
) -> GraphRetrievedWorldStateAnswer {
    let (region_snapshot, region) = build_world_state_region_from_view(view, request, &seeds);
    let answer = slot_at_snapshot(
        &region_snapshot,
        &KernelSlotQueryRequest {
            entity_id: request.entity_id.clone(),
            slot_key: request.slot_key.clone(),
            valid_at: request.valid_at,
            recorded_at: request.recorded_at,
            include_candidate_graph: request.include_candidate_graph,
        },
    );
    let ranked = {
        let _timer = measure_graph_runtime(GraphRuntimeMetric::RankedWorldState);
        let mut ranked = rank_world_state_answer(
            request.truth_plane,
            &region_snapshot.vertices,
            &region_snapshot.candidate_edges,
            &answer,
        );
        apply_phase4_world_state(request.query_text.as_str(), &mut ranked);
        apply_graph_structural_world_state(
            region.anchor_vertex_ids.as_slice(),
            &region_snapshot,
            &mut ranked,
        );
        ranked
    };
    GraphRetrievedWorldStateAnswer {
        query_text: request.query_text.clone(),
        query: GraphWorldStateQueryRequest {
            entity_id: request.entity_id.clone(),
            slot_key: request.slot_key.clone(),
            valid_at: request.valid_at,
            recorded_at: request.recorded_at,
            include_candidate_graph: request.include_candidate_graph,
            truth_plane: request.truth_plane,
        },
        answer: ranked,
        seeds,
        region,
    }
}

pub(crate) fn world_state_edge_allowed(edge: &KernelEdge) -> bool {
    matches!(
        edge.edge_type.0.as_str(),
        "state_of" | "state_value" | "supported_by" | "about" | "under_view"
    ) || (edge.edge_type.0.starts_with("semantic::")
        && edge.edge_type.0 != "semantic::related_event"
        && edge.edge_type.0 != "semantic::missing_intermediate_cause")
}
