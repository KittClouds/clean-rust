use phoenix_graph_kernel::{
    bounded_walk_projected_graph, entity_timeline_from_snapshot, slot_at_snapshot,
    what_changed_from_snapshot, KernelEdge, KernelGraphSnapshot, KernelLocalDiffusionKind,
    KernelQuerySurface, KernelRegionProfile, KernelSlotQueryRequest, KernelStateIssue,
    KernelVertex, KernelViewRequest, KernelWalkBudget, KernelWalkScoring, KernelWalkSeed,
    KernelWalkSeedFamily, KernelWhatChangedRequest,
};
use phoenix_store_native_core::{
    PhoenixGraphKernelStoreV2, PhoenixGraphPatchStore, PhoenixSemanticGraphPatchStore,
    PhoenixSemanticIndexStore,
};
use phoenix_types::ScopeKey;
use serde::{Deserialize, Serialize};

use crate::api::{
    load_projection_kernel, rank_causal_explanation_answer, rank_history_answer,
    rank_world_state_answer, GraphCausalExplanationQueryRequest, GraphHistoryQueryRequest,
    GraphQueryError,
};
use crate::diffusion_metrics::{
    metrics_from_causal, metrics_from_history, metrics_from_world_state,
};
use crate::eval::GraphEvalMetrics;
use crate::phase4_graph_scoring::{
    apply_graph_structural_causal_with_diffusion, apply_graph_structural_history_with_diffusion,
    apply_graph_structural_world_state_with_diffusion,
};
use crate::retrieval::{
    GraphRetrievedCausalExplanationQueryRequest, GraphRetrievedHistoryQueryRequest,
    GraphRetrievedRegion, GraphRetrievedSeed, GraphRetrievedWorldStateQueryRequest,
};
use crate::retrieval_causal::{build_causal_region, causal_edge_allowed};
use crate::retrieval_common::{now_ms, retrieve_query_seeds};
use crate::retrieval_history::{build_history_region, history_edge_allowed};
use crate::retrieval_receipts::{
    GraphNativeRetrievalReceipt, GraphNativeRetrievalStrategy, GraphRankedStructuralAnswer,
};
use crate::retrieval_world::{build_world_state_region, world_state_edge_allowed};

const WORLD_RETRIEVAL_KINDS: [&str; 5] = ["state", "claim", "event", "chunk", "entity"];
const HISTORY_RETRIEVAL_KINDS: [&str; 5] = ["state", "claim", "event", "chunk", "entity"];
const CAUSAL_RETRIEVAL_KINDS: [&str; 5] = ["event", "claim", "entity", "chunk", "state"];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphRetrievalAblationCase {
    SimpleRegionExpansion,
    BoundedWalk,
    BoundedWalkPcst,
    StructuralDiffusionPpr,
    StructuralDiffusionHeat,
    CausalPathFeatureRerank,
}

impl GraphRetrievalAblationCase {
    pub fn label(self) -> &'static str {
        match self {
            Self::SimpleRegionExpansion => "simple_region_expansion",
            Self::BoundedWalk => "bounded_walk",
            Self::BoundedWalkPcst => "bounded_walk_pcst",
            Self::StructuralDiffusionPpr => "structural_diffusion_ppr",
            Self::StructuralDiffusionHeat => "structural_diffusion_heat",
            Self::CausalPathFeatureRerank => "causal_path_feature_rerank",
        }
    }

    fn diffusion_kind(self) -> Option<KernelLocalDiffusionKind> {
        match self {
            Self::StructuralDiffusionPpr => Some(KernelLocalDiffusionKind::PersonalizedPagerank),
            Self::StructuralDiffusionHeat => Some(KernelLocalDiffusionKind::HeatKernel),
            _ => None,
        }
    }

    fn diffusion_label(self) -> Option<&'static str> {
        match self {
            Self::StructuralDiffusionPpr => Some("personalized_pagerank"),
            Self::StructuralDiffusionHeat => Some("heat_kernel"),
            _ => None,
        }
    }

    fn strategy(self) -> GraphNativeRetrievalStrategy {
        match self {
            Self::SimpleRegionExpansion => GraphNativeRetrievalStrategy::SimpleRegionExpansion,
            Self::BoundedWalk => GraphNativeRetrievalStrategy::BoundedWalk,
            Self::BoundedWalkPcst => GraphNativeRetrievalStrategy::BoundedWalkPcst,
            Self::StructuralDiffusionPpr | Self::StructuralDiffusionHeat => {
                GraphNativeRetrievalStrategy::StructuralDiffusionRerank
            }
            Self::CausalPathFeatureRerank => GraphNativeRetrievalStrategy::CausalPathFeatureRerank,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphRetrievalAblationCaseResult {
    pub case_name: String,
    pub case_kind: GraphRetrievalAblationCase,
    pub strategy: GraphNativeRetrievalStrategy,
    pub metrics: GraphEvalMetrics,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub receipt: Option<GraphNativeRetrievalReceipt>,
}

pub fn default_retrieval_ablation_cases() -> Vec<GraphRetrievalAblationCase> {
    vec![
        GraphRetrievalAblationCase::SimpleRegionExpansion,
        GraphRetrievalAblationCase::BoundedWalk,
        GraphRetrievalAblationCase::BoundedWalkPcst,
        GraphRetrievalAblationCase::StructuralDiffusionPpr,
        GraphRetrievalAblationCase::StructuralDiffusionHeat,
        GraphRetrievalAblationCase::CausalPathFeatureRerank,
    ]
}

pub fn evaluate_world_state_retrieval_ablation_cases<S>(
    store: &S,
    scope: &ScopeKey,
    request: &GraphRetrievedWorldStateQueryRequest,
    cases: &[GraphRetrievalAblationCase],
) -> Result<Option<Vec<GraphRetrievalAblationCaseResult>>, GraphQueryError>
where
    S: PhoenixGraphPatchStore
        + PhoenixSemanticGraphPatchStore
        + PhoenixSemanticIndexStore
        + PhoenixGraphKernelStoreV2,
{
    let Some(kernel) = load_projection_kernel(store, scope)? else {
        return Ok(None);
    };
    let seeds = retrieve_query_seeds(
        store,
        scope,
        request.query_text.as_str(),
        &WORLD_RETRIEVAL_KINDS,
        request.seed_limit,
        request.oversample,
    )?;
    let snapshot = kernel.view_as_of(KernelViewRequest {
        valid_at: request.valid_at,
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
    });
    let view = kernel.query_view(KernelViewRequest {
        valid_at: request.valid_at,
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
    });
    let query = KernelSlotQueryRequest {
        entity_id: request.entity_id.clone(),
        slot_key: request.slot_key.clone(),
        valid_at: request.valid_at,
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
    };
    let mut rows = Vec::with_capacity(cases.len());
    for case in cases {
        if *case == GraphRetrievalAblationCase::CausalPathFeatureRerank {
            continue;
        }
        let (region_snapshot, mut region) =
            world_region_for_case(*case, &snapshot, &view, request, &seeds);
        let base = rank_world_state_answer(
            request.truth_plane,
            &region_snapshot.vertices,
            &region_snapshot.candidate_edges,
            &slot_at_snapshot(&region_snapshot, &query),
        );
        let mut ranked = base.clone();
        if let Some(diffusion) = case.diffusion_kind() {
            apply_graph_structural_world_state_with_diffusion(
                region.anchor_vertex_ids.as_slice(),
                &region_snapshot,
                &mut ranked,
                diffusion,
            );
            attach_structural_receipt(
                &mut region,
                case.diffusion_label().unwrap_or_default(),
                GraphRankedStructuralAnswer::World(&ranked),
            );
        }
        rows.push(result_row(
            *case,
            metrics_from_world_state(
                &base,
                &ranked,
                seeds.len(),
                region.clone(),
                &region_snapshot.candidate_edges,
            ),
            region.native_retrieval_receipt.clone(),
        ));
    }
    Ok(Some(rows))
}

pub fn evaluate_history_retrieval_ablation_cases<S>(
    store: &S,
    scope: &ScopeKey,
    request: &GraphRetrievedHistoryQueryRequest,
    cases: &[GraphRetrievalAblationCase],
) -> Result<Option<Vec<GraphRetrievalAblationCaseResult>>, GraphQueryError>
where
    S: PhoenixGraphPatchStore
        + PhoenixSemanticGraphPatchStore
        + PhoenixSemanticIndexStore
        + PhoenixGraphKernelStoreV2,
{
    let Some(kernel) = load_projection_kernel(store, scope)? else {
        return Ok(None);
    };
    let seeds = retrieve_query_seeds(
        store,
        scope,
        request.query_text.as_str(),
        &HISTORY_RETRIEVAL_KINDS,
        request.seed_limit,
        request.oversample,
    )?;
    let until_valid_at = request.until_valid_at.unwrap_or_else(now_ms);
    let snapshot = kernel.view_as_of(KernelViewRequest {
        valid_at: Some(until_valid_at),
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
    });
    let view = kernel.query_view(KernelViewRequest {
        valid_at: Some(until_valid_at),
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
    });
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
    let mut rows = Vec::with_capacity(cases.len());
    for case in cases {
        if *case == GraphRetrievalAblationCase::CausalPathFeatureRerank {
            continue;
        }
        let (region_snapshot, mut region) =
            history_region_for_case(*case, &snapshot, &view, request, &seeds);
        let base = rank_history_from_region(&query, until_valid_at, &region_snapshot);
        let mut ranked = base.clone();
        if let Some(diffusion) = case.diffusion_kind() {
            apply_graph_structural_history_with_diffusion(
                region.anchor_vertex_ids.as_slice(),
                &region_snapshot,
                &mut ranked,
                diffusion,
            );
            attach_structural_receipt(
                &mut region,
                case.diffusion_label().unwrap_or_default(),
                GraphRankedStructuralAnswer::History(&ranked),
            );
        }
        rows.push(result_row(
            *case,
            metrics_from_history(
                &base,
                &ranked,
                seeds.len(),
                region.clone(),
                &region_snapshot.candidate_edges,
            ),
            region.native_retrieval_receipt.clone(),
        ));
    }
    Ok(Some(rows))
}

pub fn evaluate_causal_retrieval_ablation_cases<S>(
    store: &S,
    scope: &ScopeKey,
    request: &GraphRetrievedCausalExplanationQueryRequest,
    cases: &[GraphRetrievalAblationCase],
) -> Result<Option<Vec<GraphRetrievalAblationCaseResult>>, GraphQueryError>
where
    S: PhoenixGraphPatchStore
        + PhoenixSemanticGraphPatchStore
        + PhoenixSemanticIndexStore
        + PhoenixGraphKernelStoreV2,
{
    let Some(kernel) = load_projection_kernel(store, scope)? else {
        return Ok(None);
    };
    let seeds = retrieve_query_seeds(
        store,
        scope,
        request.query_text.as_str(),
        &CAUSAL_RETRIEVAL_KINDS,
        request.seed_limit,
        request.oversample,
    )?;
    let snapshot = kernel.view_as_of(KernelViewRequest {
        valid_at: request.valid_at,
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
    });
    let view = kernel.query_view(KernelViewRequest {
        valid_at: request.valid_at,
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
    });
    let query = GraphCausalExplanationQueryRequest {
        target_vertex_id: request.target_vertex_id.clone(),
        valid_at: request.valid_at,
        recorded_at: request.recorded_at,
        include_candidate_graph: request.include_candidate_graph,
        max_depth: request.max_depth,
        limit: request.limit,
        truth_plane: request.truth_plane,
    };
    let mut rows = Vec::with_capacity(cases.len());
    for case in cases {
        let (region_snapshot, mut region) =
            causal_region_for_case(*case, &snapshot, &view, request, &seeds);
        let base = rank_causal_explanation_answer(&query, &region_snapshot);
        let mut ranked = base.clone();
        match case {
            GraphRetrievalAblationCase::StructuralDiffusionPpr
            | GraphRetrievalAblationCase::StructuralDiffusionHeat => {
                let diffusion = case.diffusion_kind().expect("structural case");
                apply_graph_structural_causal_with_diffusion(
                    region.anchor_vertex_ids.as_slice(),
                    &region_snapshot,
                    &mut ranked,
                    diffusion,
                );
                attach_structural_receipt(
                    &mut region,
                    case.diffusion_label().unwrap_or_default(),
                    GraphRankedStructuralAnswer::Causal(&ranked),
                );
            }
            GraphRetrievalAblationCase::CausalPathFeatureRerank => {
                attach_causal_path_receipt(&mut region, &ranked);
            }
            _ => {}
        }
        rows.push(result_row(
            *case,
            metrics_from_causal(
                &base,
                &ranked,
                seeds.len(),
                region.clone(),
                &region_snapshot.candidate_edges,
            ),
            region.native_retrieval_receipt.clone(),
        ));
    }
    Ok(Some(rows))
}

fn world_region_for_case(
    case: GraphRetrievalAblationCase,
    snapshot: &KernelGraphSnapshot,
    view: &KernelQuerySurface,
    request: &GraphRetrievedWorldStateQueryRequest,
    seeds: &[GraphRetrievedSeed],
) -> (KernelGraphSnapshot, GraphRetrievedRegion) {
    match case {
        GraphRetrievalAblationCase::SimpleRegionExpansion => {
            build_world_state_region(snapshot, request, seeds)
        }
        GraphRetrievalAblationCase::BoundedWalk => bounded_region(
            view,
            world_anchors(view.vertices(), &request.entity_id, Some(&request.slot_key)),
            seeds,
            request.region_node_limit,
            request.expansion_hops,
            KernelRegionProfile::WorldState,
            false,
            world_state_edge_allowed,
        ),
        _ => bounded_region(
            view,
            world_anchors(view.vertices(), &request.entity_id, Some(&request.slot_key)),
            seeds,
            request.region_node_limit,
            request.expansion_hops,
            KernelRegionProfile::WorldState,
            true,
            world_state_edge_allowed,
        ),
    }
}

fn history_region_for_case(
    case: GraphRetrievalAblationCase,
    snapshot: &KernelGraphSnapshot,
    view: &KernelQuerySurface,
    request: &GraphRetrievedHistoryQueryRequest,
    seeds: &[GraphRetrievedSeed],
) -> (KernelGraphSnapshot, GraphRetrievedRegion) {
    match case {
        GraphRetrievalAblationCase::SimpleRegionExpansion => {
            build_history_region(snapshot, request, seeds)
        }
        GraphRetrievalAblationCase::BoundedWalk => bounded_region(
            view,
            world_anchors(
                view.vertices(),
                &request.entity_id,
                request.slot_key.as_deref(),
            ),
            seeds,
            request.region_node_limit,
            request.expansion_hops,
            KernelRegionProfile::History,
            false,
            history_edge_allowed,
        ),
        _ => bounded_region(
            view,
            world_anchors(
                view.vertices(),
                &request.entity_id,
                request.slot_key.as_deref(),
            ),
            seeds,
            request.region_node_limit,
            request.expansion_hops,
            KernelRegionProfile::History,
            true,
            history_edge_allowed,
        ),
    }
}

fn causal_region_for_case(
    case: GraphRetrievalAblationCase,
    snapshot: &KernelGraphSnapshot,
    view: &KernelQuerySurface,
    request: &GraphRetrievedCausalExplanationQueryRequest,
    seeds: &[GraphRetrievedSeed],
) -> (KernelGraphSnapshot, GraphRetrievedRegion) {
    match case {
        GraphRetrievalAblationCase::SimpleRegionExpansion => {
            build_causal_region(snapshot, request, seeds)
        }
        GraphRetrievalAblationCase::BoundedWalk => bounded_region(
            view,
            causal_anchors(view.vertices(), &request.target_vertex_id),
            seeds,
            request.region_node_limit,
            request.expansion_hops,
            KernelRegionProfile::Causal,
            false,
            causal_edge_allowed,
        ),
        _ => bounded_region(
            view,
            causal_anchors(view.vertices(), &request.target_vertex_id),
            seeds,
            request.region_node_limit,
            request.expansion_hops,
            KernelRegionProfile::Causal,
            true,
            causal_edge_allowed,
        ),
    }
}

fn bounded_region(
    view: &KernelQuerySurface,
    anchors: Vec<String>,
    seeds: &[GraphRetrievedSeed],
    region_node_limit: usize,
    expansion_hops: usize,
    profile: KernelRegionProfile,
    compact: bool,
    edge_allowed: fn(&KernelEdge) -> bool,
) -> (KernelGraphSnapshot, GraphRetrievedRegion) {
    let walk_seeds = seeds
        .iter()
        .filter(|seed| view.find_vertex(seed.node_id.as_str()).is_some())
        .map(|seed| KernelWalkSeed {
            vertex_id: seed.node_id.clone(),
            family: KernelWalkSeedFamily::Graph,
            prize_millis: seed.score_millis,
            evidence_refs: seed.evidence_refs.clone(),
        })
        .collect::<Vec<_>>();
    let walk = bounded_walk_projected_graph(
        view,
        anchors.as_slice(),
        walk_seeds.as_slice(),
        KernelWalkBudget {
            max_nodes: region_node_limit,
            max_edges: region_node_limit.saturating_mul(4).max(64),
            max_depth: expansion_hops,
            max_per_family_fanout: 16,
            max_per_island_expansion: region_node_limit.max(8),
            profile,
            compact,
            projected_csr_diagnostics: true,
            ..KernelWalkBudget::default()
        },
        KernelWalkScoring::default(),
        edge_allowed,
    );
    let region = GraphRetrievedRegion::from_bounded_walk(anchors, &walk, compact);
    (walk.snapshot, region)
}

fn rank_history_from_region(
    query: &GraphHistoryQueryRequest,
    until_valid_at: i64,
    region: &KernelGraphSnapshot,
) -> crate::api::GraphRankedHistoryAnswer {
    let timeline = entity_timeline_from_snapshot(
        region,
        &query.entity_id,
        Some((query.since_valid_at, until_valid_at)),
        query.recorded_at.or(Some(until_valid_at)),
    );
    let changes = what_changed_from_snapshot(
        &timeline,
        &KernelWhatChangedRequest {
            entity_id: query.entity_id.clone(),
            slot_key: query.slot_key.clone(),
            since_valid_at: query.since_valid_at,
            until_valid_at: Some(until_valid_at),
            recorded_at: query.recorded_at,
            include_candidate_graph: query.include_candidate_graph,
        },
    );
    let conflicts = timeline_issues(
        &timeline.vertices,
        "conflict",
        &query.entity_id,
        query.slot_key.as_deref(),
    );
    let gaps = timeline_issues(
        &timeline.vertices,
        "gap",
        &query.entity_id,
        query.slot_key.as_deref(),
    );
    rank_history_answer(
        query,
        until_valid_at,
        &timeline.vertices,
        &timeline.vertices,
        &timeline.asserted_edges,
        &timeline.candidate_edges,
        &changes,
        &conflicts,
        &gaps,
    )
}

fn attach_structural_receipt(
    region: &mut GraphRetrievedRegion,
    diffusion: &str,
    answer: GraphRankedStructuralAnswer<'_>,
) {
    if let Some(receipt) = region.native_retrieval_receipt.take() {
        region.native_retrieval_receipt = Some(receipt.with_structural(diffusion, &answer));
    }
}

fn attach_causal_path_receipt(
    region: &mut GraphRetrievedRegion,
    answer: &crate::api::GraphRankedCausalExplanationAnswer,
) {
    let receipt = region.native_retrieval_receipt.take().unwrap_or_else(|| {
        GraphNativeRetrievalReceipt::region_only(
            GraphNativeRetrievalStrategy::CausalPathFeatureRerank,
            region,
        )
    });
    region.native_retrieval_receipt = Some(receipt.with_causal_path_features(answer));
}

fn result_row(
    case: GraphRetrievalAblationCase,
    metrics: GraphEvalMetrics,
    receipt: Option<GraphNativeRetrievalReceipt>,
) -> GraphRetrievalAblationCaseResult {
    GraphRetrievalAblationCaseResult {
        case_name: case.label().to_owned(),
        case_kind: case,
        strategy: case.strategy(),
        metrics,
        receipt,
    }
}

fn world_anchors(
    vertices: &[KernelVertex],
    entity_id: &str,
    slot_key: Option<&str>,
) -> Vec<String> {
    let mut anchors = vertices
        .iter()
        .filter(|vertex| vertex.entity_id.as_deref() == Some(entity_id))
        .filter(|vertex| {
            vertex.kind == "entity"
                || slot_key
                    .map(|slot_key| slot_key_of(vertex) == Some(slot_key))
                    .unwrap_or(true)
        })
        .map(|vertex| vertex.id.0.clone())
        .collect::<Vec<_>>();
    anchors.sort();
    anchors.dedup();
    anchors
}

fn causal_anchors(vertices: &[KernelVertex], target_vertex_id: &str) -> Vec<String> {
    let mut anchors = vec![target_vertex_id.to_owned()];
    if let Some(target) = vertices
        .iter()
        .find(|vertex| vertex.id.0 == target_vertex_id)
    {
        if let Some(entity_id) = target.entity_id.as_deref() {
            anchors.extend(
                vertices
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
    anchors
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
