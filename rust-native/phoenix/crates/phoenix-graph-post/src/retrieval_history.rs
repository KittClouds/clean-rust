use phoenix_graph_kernel::{
    entity_timeline_from_snapshot, what_changed_from_snapshot, KernelEdge, KernelQuerySurface,
    KernelRegionProfile, KernelStateIssue, KernelVertex, KernelViewRequest,
    KernelWhatChangedRequest,
};
use phoenix_store_native_core::{
    PhoenixGraphKernelStoreV2, PhoenixGraphPatchStore, PhoenixLexicalQueryStore,
    PhoenixSemanticGraphPatchStore, PhoenixSemanticIndexStore,
};
use phoenix_types::ScopeKey;

use crate::api::{rank_history_answer, GraphHistoryQueryRequest, GraphQueryError};
use crate::phase4_graph_scoring::apply_graph_structural_history;
use crate::phase4_scoring::apply_phase4_history;
use crate::query_session::{ScopeQuerySession, SeedQuerySurface};
use crate::retrieval::{
    open_retrieved_query_session, GraphRetrievedHistoryAnswer, GraphRetrievedHistoryQueryRequest,
    GraphRetrievedSeed,
};
use crate::retrieval_common::{
    build_region_from_snapshot, build_region_from_view_profile, graph_local_entity_slot_seeds,
    now_ms, retrieve_query_seeds_with_session,
};
use crate::runtime_telemetry::{measure_graph_runtime, GraphRuntimeMetric};

const HISTORY_RETRIEVAL_KINDS: [&str; 5] = ["state", "claim", "event", "chunk", "entity"];

pub(crate) fn retrieved_history_impl<S>(
    store: &S,
    scope: &ScopeKey,
    request: &GraphRetrievedHistoryQueryRequest,
) -> Result<Option<GraphRetrievedHistoryAnswer>, GraphQueryError>
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
    retrieved_history_with_session_impl(store, &session, request)
}

pub(crate) fn retrieved_history_with_session_impl<S>(
    store: &S,
    session: &ScopeQuerySession,
    request: &GraphRetrievedHistoryQueryRequest,
) -> Result<Option<GraphRetrievedHistoryAnswer>, GraphQueryError>
where
    S: PhoenixLexicalQueryStore + PhoenixSemanticIndexStore,
{
    let _timer = measure_graph_runtime(GraphRuntimeMetric::RetrievedHistory);
    let until_valid_at = history_until_valid_at(request);
    let view_request = history_view_request(request, until_valid_at);
    let view = {
        let _timer = measure_graph_runtime(GraphRuntimeMetric::BuildQueryView);
        session.query_surface(view_request.clone())
    };
    let mut seeds = request
        .slot_key
        .as_deref()
        .map(|slot_key| {
            graph_local_entity_slot_seeds(
                &view,
                request.entity_id.as_str(),
                slot_key,
                request.seed_limit,
            )
        })
        .unwrap_or_default();
    if seeds.is_empty() {
        seeds = retrieve_query_seeds_with_session(
            store,
            session,
            request.query_text.as_str(),
            &HISTORY_RETRIEVAL_KINDS,
            request.seed_limit,
            request.oversample,
            history_seed_surface(request),
            view_request,
            &view,
        )?;
    }
    Ok(Some(answer_history_from_view(
        &view,
        request,
        until_valid_at,
        seeds,
    )))
}

pub(crate) fn build_history_region(
    snapshot: &phoenix_graph_kernel::KernelGraphSnapshot,
    request: &GraphRetrievedHistoryQueryRequest,
    seeds: &[GraphRetrievedSeed],
) -> (
    phoenix_graph_kernel::KernelGraphSnapshot,
    crate::retrieval::GraphRetrievedRegion,
) {
    let anchors = snapshot
        .vertices
        .iter()
        .filter(|vertex| vertex.entity_id.as_deref() == Some(request.entity_id.as_str()))
        .filter(|vertex| {
            vertex.kind == "entity"
                || request
                    .slot_key
                    .as_deref()
                    .map(|slot_key| slot_key_of(vertex) == Some(slot_key))
                    .unwrap_or(true)
        })
        .map(|vertex| vertex.id.0.clone())
        .collect::<Vec<_>>();
    build_region_from_snapshot(
        snapshot,
        anchors,
        seeds,
        request.region_node_limit,
        request.expansion_hops,
        history_edge_allowed,
    )
}

pub(crate) fn build_history_region_from_view(
    view: &KernelQuerySurface,
    request: &GraphRetrievedHistoryQueryRequest,
    seeds: &[GraphRetrievedSeed],
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
                vertex.kind == "entity"
                    || request
                        .slot_key
                        .as_deref()
                        .map(|slot_key| slot_key_of(vertex) == Some(slot_key))
                        .unwrap_or(true)
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
        history_edge_allowed,
        KernelRegionProfile::History,
    )
}

fn timeline_issues(
    vertices: &[KernelVertex],
    issue_kind: &str,
    entity_id: &str,
    slot_key: Option<&str>,
) -> Vec<KernelStateIssue> {
    let mut issues = vertices
        .iter()
        .filter(|vertex| vertex.kind == issue_kind)
        .filter(|vertex| vertex.entity_id.as_deref() == Some(entity_id))
        .filter(|vertex| {
            slot_key
                .map(|key| slot_key_of(vertex) == Some(key))
                .unwrap_or(true)
        })
        .map(|vertex| KernelStateIssue {
            issue_vertex_id: vertex.id.0.clone(),
            entity_id: vertex.entity_id.clone().unwrap_or_default(),
            slot_key: slot_key_of(vertex).unwrap_or_default().to_owned(),
            issue_kind: string_attr(&vertex.value, "kind")
                .unwrap_or(issue_kind)
                .to_owned(),
            reason: string_attr(&vertex.attributes, "reason").map(str::to_owned),
            detail: string_attr(&vertex.value, "detail").map(str::to_owned),
            status: string_attr(&vertex.value, "status").map(str::to_owned),
            preferred_claim_id: string_attr(&vertex.attributes, "preferredClaimId")
                .map(str::to_owned),
            temporal: vertex.temporal.clone(),
            supporting_claim_ids: string_list_attr(&vertex.attributes, "claimIds"),
        })
        .collect::<Vec<_>>();
    issues.sort_by(|left, right| {
        left.temporal
            .valid_from
            .cmp(&right.temporal.valid_from)
            .then_with(|| left.issue_vertex_id.cmp(&right.issue_vertex_id))
    });
    issues
}

pub(crate) fn history_edge_allowed(edge: &KernelEdge) -> bool {
    matches!(
        edge.edge_type.0.as_str(),
        "state_of" | "state_value" | "supported_by" | "about" | "under_view"
    ) || (edge.edge_type.0.starts_with("semantic::")
        && edge.edge_type.0 != "semantic::missing_intermediate_cause")
}

fn slot_key_of(vertex: &KernelVertex) -> Option<&str> {
    string_attr(&vertex.value, "slotKey").or_else(|| string_attr(&vertex.attributes, "slotKey"))
}

fn string_attr<'a>(value: &'a serde_json::Value, key: &str) -> Option<&'a str> {
    value.get(key).and_then(serde_json::Value::as_str)
}

fn string_list_attr(value: &serde_json::Value, key: &str) -> Vec<String> {
    value
        .get(key)
        .and_then(serde_json::Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(serde_json::Value::as_str)
        .map(str::to_owned)
        .collect::<Vec<_>>()
}

pub(crate) fn history_seed_surface(
    request: &GraphRetrievedHistoryQueryRequest,
) -> SeedQuerySurface {
    request
        .slot_key
        .as_deref()
        .map(|slot_key| SeedQuerySurface::EntitySlot {
            entity_id: request.entity_id.clone(),
            slot_key: slot_key.to_owned(),
        })
        .unwrap_or_else(|| SeedQuerySurface::QueryText(request.query_text.clone()))
}

pub(crate) fn history_until_valid_at(request: &GraphRetrievedHistoryQueryRequest) -> i64 {
    request.until_valid_at.unwrap_or_else(now_ms)
}

pub(crate) fn history_view_request(
    request: &GraphRetrievedHistoryQueryRequest,
    until_valid_at: i64,
) -> KernelViewRequest {
    KernelViewRequest {
        valid_at: Some(until_valid_at),
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
    }
}

pub(crate) fn answer_history_from_view(
    view: &KernelQuerySurface,
    request: &GraphRetrievedHistoryQueryRequest,
    until_valid_at: i64,
    seeds: Vec<GraphRetrievedSeed>,
) -> GraphRetrievedHistoryAnswer {
    let (region_snapshot, region) = build_history_region_from_view(view, request, &seeds);
    let timeline = entity_timeline_from_snapshot(
        &region_snapshot,
        &request.entity_id,
        Some((request.since_valid_at, until_valid_at)),
        request.recorded_at.or(Some(until_valid_at)),
    );
    let changes = what_changed_from_snapshot(
        &timeline,
        &KernelWhatChangedRequest {
            entity_id: request.entity_id.clone(),
            slot_key: request.slot_key.clone(),
            since_valid_at: request.since_valid_at,
            until_valid_at: Some(until_valid_at),
            recorded_at: request.recorded_at,
            include_candidate_graph: request.include_candidate_graph,
        },
    );
    let query = GraphHistoryQueryRequest {
        entity_id: request.entity_id.clone(),
        slot_key: request.slot_key.clone(),
        since_valid_at: request.since_valid_at,
        until_valid_at: Some(until_valid_at),
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
        truth_plane: request.truth_plane,
        limit: request.limit,
    };
    let ranked = {
        let _timer = measure_graph_runtime(GraphRuntimeMetric::RankedHistory);
        let mut ranked = rank_history_answer(
            &query,
            until_valid_at,
            &timeline.vertices,
            &timeline.vertices,
            &timeline.asserted_edges,
            &timeline.candidate_edges,
            &changes,
            &timeline_issues(
                &timeline.vertices,
                "conflict",
                &request.entity_id,
                request.slot_key.as_deref(),
            ),
            &timeline_issues(
                &timeline.vertices,
                "gap",
                &request.entity_id,
                request.slot_key.as_deref(),
            ),
        );
        apply_phase4_history(request.query_text.as_str(), &mut ranked);
        apply_graph_structural_history(
            region.anchor_vertex_ids.as_slice(),
            &region_snapshot,
            &mut ranked,
        );
        ranked
    };
    GraphRetrievedHistoryAnswer {
        query_text: request.query_text.clone(),
        answer: ranked,
        query,
        seeds,
        region,
    }
}
