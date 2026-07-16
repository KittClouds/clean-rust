use hashbrown::{HashMap, HashSet};
use phoenix_graph_kernel::{
    GraphTruthCommit, KernelEdge, KernelGraphLayer, KernelMutationBatch, KernelMutationScope,
    KernelRelationClass, KernelVertex,
};
use phoenix_semantic_v2::{
    GraphDependencyManifest, GraphScopeSidecar, SemanticCandidateStatus, SemanticEdgeFamily,
    SemanticGraphScopeSidecar,
};
use phoenix_store_native_core::{PhoenixGraphKernelStoreV2, PhoenixGraphLearningStore, StoreError};
use phoenix_types::{
    GraphTruthCommitHeader, GraphTruthCompilerPolicy, GraphTruthDigest, GraphTruthOperation,
    GraphTruthPlane, GraphTruthSourceGenerationRef,
};
use serde::Serialize;
use serde_json::Value;

use crate::promotion_receipts::{
    build_graph_projection_proposal_receipt, build_semantic_proposal_receipt,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub(crate) enum PromotionLane {
    SituationWorldState,
    ModalFact(GraphTruthPlane),
    EventIdentityRoles,
    TemporalAnchors,
    CausalEdges,
    SemanticPhase5(GraphTruthPlane),
    CrossDocumentIdentity,
}

pub(crate) struct PromotionProposal {
    pub(crate) lane: PromotionLane,
    pub(crate) batch: KernelMutationBatch,
}

pub(crate) fn append_graph_projection_commits<S>(
    store: &S,
    sidecar: &GraphScopeSidecar,
    committed_at: i64,
) -> Result<(), StoreError>
where
    S: PhoenixGraphKernelStoreV2 + PhoenixGraphLearningStore + ?Sized,
{
    let proposals = graph_projection_proposals(sidecar);
    if proposals.is_empty() {
        return Ok(());
    }
    let manifest = sidecar.resolved_dependency_manifest();
    let sources = graph_source_generations(sidecar);
    let receipt = build_graph_projection_proposal_receipt(sidecar, &proposals, &sources)?;
    if let Some(receipt) = receipt.as_ref() {
        store.append_graph_proposal_receipt(receipt)?;
    }
    let legacy_digest = legacy_graph_projection_hash(sidecar)?;
    let legacy_commit_id = legacy_graph_projection_commit_id(legacy_digest);
    let supersede_first = store.load_graph_truth_commit(&legacy_commit_id)?.is_some();
    append_proposals(
        store,
        proposals,
        &manifest,
        &sources,
        committed_at,
        supersede_first.then_some(legacy_commit_id.as_str()),
        receipt
            .as_ref()
            .map(|value| std::slice::from_ref(&value.receipt_id))
            .unwrap_or_default(),
    )
}

pub(crate) fn append_semantic_phase5_promotion_commits<S>(
    store: &S,
    sidecar: &SemanticGraphScopeSidecar,
) -> Result<(), StoreError>
where
    S: PhoenixGraphKernelStoreV2 + PhoenixGraphLearningStore + ?Sized,
{
    let receipt = build_semantic_proposal_receipt(sidecar)?;
    if let Some(receipt) = receipt.as_ref() {
        store.append_graph_proposal_receipt(receipt)?;
    }
    let proposals = semantic_phase5_proposals(sidecar);
    if proposals.is_empty() {
        return Ok(());
    }
    let manifest = sidecar.resolved_dependency_manifest();
    let sources = semantic_source_generations(sidecar);
    append_proposals(
        store,
        proposals,
        &manifest,
        &sources,
        sidecar.updated_at,
        None,
        receipt
            .as_ref()
            .map(|value| std::slice::from_ref(&value.receipt_id))
            .unwrap_or_default(),
    )
}

fn append_proposals<S>(
    store: &S,
    proposals: Vec<PromotionProposal>,
    manifest: &GraphDependencyManifest,
    sources: &[GraphTruthSourceGenerationRef],
    committed_at: i64,
    supersede_first: Option<&str>,
    receipt_ids: &[compact_str::CompactString],
) -> Result<(), StoreError>
where
    S: PhoenixGraphKernelStoreV2 + ?Sized,
{
    for (index, proposal) in proposals.into_iter().enumerate() {
        let digest = promotion_idempotency_hash(manifest, proposal.lane, &proposal.batch)?;
        let commit_id = promotion_commit_id(proposal.lane, digest);
        if let Some(existing) = store.load_graph_truth_commit(&commit_id)? {
            store.append_graph_truth_commit(&existing)?;
            continue;
        }
        let generation = store
            .kernel_current_generation()?
            .checked_add(1)
            .ok_or_else(|| StoreError::Query("graph truth generation overflow".to_owned()))?;
        let predecessor = if index == 0 { supersede_first } else { None };
        let commit = build_promotion_commit(
            proposal,
            (sources, receipt_ids),
            commit_id,
            digest,
            generation,
            committed_at,
            predecessor,
        )?;
        store.append_graph_truth_commit(&commit)?;
    }
    Ok(())
}

fn graph_projection_proposals(sidecar: &GraphScopeSidecar) -> Vec<PromotionProposal> {
    split_projection_batch(&sidecar.graph_batch, graph_lane_order())
}

pub(crate) fn semantic_phase5_proposals(
    sidecar: &SemanticGraphScopeSidecar,
) -> Vec<PromotionProposal> {
    let node_plane = sidecar
        .candidate_nodes
        .iter()
        .map(|node| {
            (
                node.node_id.as_str(),
                plane_from_label(node.truth_plane.as_deref()),
            )
        })
        .collect::<HashMap<_, _>>();
    let promoted = sidecar
        .candidate_edges
        .iter()
        .filter_map(|candidate| {
            if !matches!(
                candidate.candidate_status,
                SemanticCandidateStatus::ReviewedSupport
                    | SemanticCandidateStatus::ReviewedContradiction
            ) {
                return None;
            }
            let plane = semantic_edge_plane(
                node_plane
                    .get(candidate.source_node_id.as_str())
                    .copied()
                    .flatten(),
                node_plane
                    .get(candidate.target_node_id.as_str())
                    .copied()
                    .flatten(),
            )?;
            Some((
                (
                    candidate.source_node_id.as_str(),
                    candidate.target_node_id.as_str(),
                    semantic_edge_type(candidate.family),
                ),
                plane,
            ))
        })
        .collect::<HashMap<_, _>>();
    if promoted.is_empty() {
        return Vec::new();
    }

    let mut edge_groups = promotion_lane_order()
        .into_iter()
        .filter_map(|lane| match lane {
            PromotionLane::SemanticPhase5(plane) => Some((plane, Vec::new())),
            _ => None,
        })
        .collect::<Vec<_>>();
    let mut referenced = HashSet::new();
    for edge in &sidecar.candidate_graph_batch.edges {
        let key = (
            edge.source_id.0.as_str(),
            edge.target_id.0.as_str(),
            edge.edge_type.0.as_str(),
        );
        let Some(plane) = promoted.get(&key).copied() else {
            continue;
        };
        let mut edge = edge.clone();
        edge.layer = KernelGraphLayer::Asserted;
        edge.relation_class = KernelRelationClass::Semantic;
        if let Some((_, edges)) = edge_groups.iter_mut().find(|(item, _)| *item == plane) {
            referenced.insert(edge.source_id.0.clone());
            referenced.insert(edge.target_id.0.clone());
            edges.push(edge);
        }
    }
    let mut seen_vertices = HashSet::new();
    edge_groups
        .into_iter()
        .filter_map(|(plane, mut edges)| {
            if edges.is_empty() {
                return None;
            }
            edges.sort_by(edge_sort_key);
            let mut vertices = sidecar
                .candidate_graph_batch
                .vertices
                .iter()
                .filter(|vertex| referenced.contains(vertex.id.0.as_str()))
                .filter(|vertex| seen_vertices.insert(vertex.id.0.clone()))
                .cloned()
                .collect::<Vec<_>>();
            vertices.sort_by(|left, right| left.id.0.cmp(&right.id.0));
            stamp_truth_plane(&mut vertices, &mut edges, plane);
            Some(PromotionProposal {
                lane: PromotionLane::SemanticPhase5(plane),
                batch: KernelMutationBatch {
                    layer: KernelGraphLayer::Asserted,
                    scope: lane_projection_scope(
                        &sidecar.scope_key,
                        PromotionLane::SemanticPhase5(plane),
                    ),
                    recorded_at: Some(sidecar.updated_at),
                    vertices,
                    edges,
                },
            })
        })
        .collect()
}

fn split_projection_batch(
    batch: &KernelMutationBatch,
    lanes: Vec<PromotionLane>,
) -> Vec<PromotionProposal> {
    let vertices = batch
        .vertices
        .iter()
        .map(|vertex| (vertex.id.0.as_str(), vertex))
        .collect::<HashMap<_, _>>();
    let vertex_lanes = batch
        .vertices
        .iter()
        .map(|vertex| (vertex.id.0.as_str(), vertex_lane(vertex, &vertices)))
        .collect::<HashMap<_, _>>();

    lanes
        .into_iter()
        .filter_map(|lane| {
            let mut lane_vertices = batch
                .vertices
                .iter()
                .filter(|vertex| vertex_lanes.get(vertex.id.0.as_str()) == Some(&lane))
                .cloned()
                .collect::<Vec<_>>();
            let mut lane_edges = batch
                .edges
                .iter()
                .filter(|edge| edge_lane(edge, &vertex_lanes) == lane)
                .cloned()
                .collect::<Vec<_>>();
            if lane_vertices.is_empty() && lane_edges.is_empty() {
                return None;
            }
            lane_vertices.sort_by(|left, right| left.id.0.cmp(&right.id.0));
            lane_edges.sort_by(edge_sort_key);
            stamp_lane_truth_plane(lane, &mut lane_vertices, &mut lane_edges);
            Some(PromotionProposal {
                lane,
                batch: KernelMutationBatch {
                    layer: KernelGraphLayer::Asserted,
                    scope: lane_batch_scope(&batch.scope, lane),
                    recorded_at: batch.recorded_at,
                    vertices: lane_vertices,
                    edges: lane_edges,
                },
            })
        })
        .collect()
}

fn stamp_lane_truth_plane(
    lane: PromotionLane,
    vertices: &mut [KernelVertex],
    edges: &mut [KernelEdge],
) {
    if let Some(plane) = lane.truth_descriptor().plane {
        stamp_truth_plane(vertices, edges, plane);
    }
}

fn stamp_truth_plane(
    vertices: &mut [KernelVertex],
    edges: &mut [KernelEdge],
    plane: GraphTruthPlane,
) {
    for vertex in vertices {
        stamp_truth_plane_metadata(&mut vertex.attributes, plane);
    }
    for edge in edges {
        stamp_truth_plane_metadata(&mut edge.attributes, plane);
    }
}

fn stamp_truth_plane_metadata(value: &mut Value, plane: GraphTruthPlane) {
    if !value.is_object() {
        *value = Value::Object(Default::default());
    }
    if let Some(object) = value.as_object_mut() {
        object
            .entry("truthPlane")
            .or_insert_with(|| Value::String(truth_plane_label(plane).to_owned()));
    }
}

fn truth_plane_label(plane: GraphTruthPlane) -> &'static str {
    match plane {
        GraphTruthPlane::WorldState => "worldState",
        GraphTruthPlane::Reported => "reported",
        GraphTruthPlane::Conditional => "conditional",
        GraphTruthPlane::Hypothetical => "hypothetical",
        GraphTruthPlane::Planned => "planned",
        GraphTruthPlane::Mixed => "mixed",
        GraphTruthPlane::Unknown => "unknown",
    }
}

fn lane_batch_scope(scope: &KernelMutationScope, lane: PromotionLane) -> KernelMutationScope {
    match scope {
        KernelMutationScope::Projection { scope_key } => lane_projection_scope(scope_key, lane),
        _ => scope.clone(),
    }
}

fn lane_projection_scope(scope_key: &str, lane: PromotionLane) -> KernelMutationScope {
    KernelMutationScope::Projection {
        scope_key: format!("{scope_key}::promotion::{}", lane.slug()),
    }
}

fn vertex_lane(vertex: &KernelVertex, vertices: &HashMap<&str, &KernelVertex>) -> PromotionLane {
    let id = vertex.id.0.as_str();
    if is_temporal_vertex(vertex) {
        return PromotionLane::TemporalAnchors;
    }
    if id.starts_with("graph::event::canonical::") {
        return PromotionLane::EventIdentityRoles;
    }
    if id.starts_with("graph::belief::") || id.starts_with("graph::view::belief::") {
        return modal_lane(vertex_plane(vertex));
    }
    if id.starts_with("graph::view::event::") {
        return PromotionLane::EventIdentityRoles;
    }
    if id.starts_with("graph::view::memory::") {
        return modal_lane(vertex_plane(vertex));
    }
    if id.starts_with("graph::value::claim::") {
        let claim_id = id.trim_start_matches("graph::value::claim::");
        let claim_vertex = format!("graph::claim::{claim_id}");
        return vertices
            .get(claim_vertex.as_str())
            .map(|vertex| modal_lane(vertex_plane(vertex)))
            .unwrap_or(PromotionLane::SituationWorldState);
    }
    if is_causal_endpoint_vertex(vertex) {
        return PromotionLane::CausalEdges;
    }
    modal_lane(vertex_plane(vertex))
}

fn edge_lane(edge: &KernelEdge, vertex_lanes: &HashMap<&str, PromotionLane>) -> PromotionLane {
    let edge_type = edge.edge_type.0.as_str();
    if edge_type == "canonicalized_as" {
        return PromotionLane::CrossDocumentIdentity;
    }
    if edge_type == "causal_link" {
        return PromotionLane::CausalEdges;
    }
    if edge_type.starts_with("role::") {
        return PromotionLane::EventIdentityRoles;
    }
    if is_temporal_edge(edge) {
        return PromotionLane::TemporalAnchors;
    }
    vertex_lanes
        .get(edge.source_id.0.as_str())
        .copied()
        .or_else(|| vertex_lanes.get(edge.target_id.0.as_str()).copied())
        .unwrap_or(PromotionLane::SituationWorldState)
}

fn is_temporal_vertex(vertex: &KernelVertex) -> bool {
    vertex.kind == "time_anchor"
        || vertex.id.0.starts_with("graph::time_anchor::")
        || vertex.id.0.starts_with("calendar::")
}

fn is_temporal_edge(edge: &KernelEdge) -> bool {
    matches!(
        edge.relation_class,
        KernelRelationClass::Temporal | KernelRelationClass::Calendar
    ) || matches!(
        edge.edge_type.0.as_str(),
        "anchored_by" | "starts_at" | "ends_at" | "occurs_at" | "contains"
    ) || edge.edge_type.0.starts_with("temporal::")
}

fn is_causal_endpoint_vertex(vertex: &KernelVertex) -> bool {
    vertex.provenance.source.as_deref() == Some("causal")
        || string_field(&vertex.attributes, "sourceClass")
            .is_some_and(|value| value.starts_with("causal"))
        || string_field(&vertex.value, "eventType") == Some("causalEndpoint")
}

fn vertex_plane(vertex: &KernelVertex) -> GraphTruthPlane {
    string_field(&vertex.value, "modality")
        .or_else(|| string_field(&vertex.value, "truthStatus"))
        .or_else(|| string_field(&vertex.value, "beliefKind"))
        .and_then(|value| plane_from_label(Some(value)))
        .unwrap_or(GraphTruthPlane::WorldState)
}

pub(crate) fn plane_from_label(value: Option<&str>) -> Option<GraphTruthPlane> {
    let plane = match value?.trim() {
        "world" | "worldState" | "asserted" | "observed" | "inferred" | "negated" | "knows" => {
            GraphTruthPlane::WorldState
        }
        "reported" | "reportedSpeech" | "attributedClaim" => GraphTruthPlane::Reported,
        "conditional" => GraphTruthPlane::Conditional,
        "hypothetical" | "doubts" => GraphTruthPlane::Hypothetical,
        "planned" | "intends" => GraphTruthPlane::Planned,
        _ => return None,
    };
    Some(plane)
}

fn modal_lane(plane: GraphTruthPlane) -> PromotionLane {
    match plane {
        GraphTruthPlane::Reported
        | GraphTruthPlane::Conditional
        | GraphTruthPlane::Hypothetical
        | GraphTruthPlane::Planned => PromotionLane::ModalFact(plane),
        _ => PromotionLane::SituationWorldState,
    }
}

pub(crate) fn semantic_edge_plane(
    source: Option<GraphTruthPlane>,
    target: Option<GraphTruthPlane>,
) -> Option<GraphTruthPlane> {
    match (source, target) {
        (Some(left), Some(right)) if left == right => Some(left),
        (Some(GraphTruthPlane::WorldState), Some(other)) if other.is_assertable() => Some(other),
        (Some(other), Some(GraphTruthPlane::WorldState)) if other.is_assertable() => Some(other),
        (Some(plane), None) | (None, Some(plane)) if plane.is_assertable() => Some(plane),
        (None, None) => Some(GraphTruthPlane::WorldState),
        _ => None,
    }
}

fn string_field<'a>(value: &'a Value, key: &str) -> Option<&'a str> {
    value.get(key).and_then(Value::as_str)
}

fn edge_sort_key(left: &KernelEdge, right: &KernelEdge) -> std::cmp::Ordering {
    (
        left.source_id.0.as_str(),
        left.target_id.0.as_str(),
        left.edge_type.0.as_str(),
    )
        .cmp(&(
            right.source_id.0.as_str(),
            right.target_id.0.as_str(),
            right.edge_type.0.as_str(),
        ))
}

fn build_promotion_commit(
    proposal: PromotionProposal,
    provenance: (
        &[GraphTruthSourceGenerationRef],
        &[compact_str::CompactString],
    ),
    commit_id: String,
    idempotency_hash: GraphTruthDigest,
    generation: u64,
    committed_at: i64,
    supersedes: Option<&str>,
) -> Result<GraphTruthCommit, StoreError> {
    let (sources, receipt_ids) = provenance;
    let mut commit = GraphTruthCommit {
        header: GraphTruthCommitHeader {
            commit_id: commit_id.into(),
            generation,
            operation: if supersedes.is_some() {
                GraphTruthOperation::Supersede
            } else {
                GraphTruthOperation::Assert
            },
            truth: proposal.lane.truth_descriptor(),
            compiler_policy: GraphTruthCompilerPolicy {
                compiler_id: "phoenix-graph-post".into(),
                compiler_version: env!("CARGO_PKG_VERSION").into(),
                policy_id: proposal.lane.policy_id().into(),
                policy_version: "1".into(),
            },
            idempotency_hash,
            committed_at,
            ..GraphTruthCommitHeader::default()
        },
        batch: proposal.batch,
    };
    commit
        .header
        .source_generations
        .extend(sources.iter().cloned());
    commit
        .header
        .receipt_ids
        .extend(receipt_ids.iter().cloned());
    if let Some(predecessor) = supersedes {
        commit
            .header
            .predecessor_commit_ids
            .push(predecessor.to_owned().into());
    }
    commit
        .validate()
        .map_err(|error| StoreError::Schema(error.to_string()))?;
    Ok(commit)
}

fn graph_lane_order() -> Vec<PromotionLane> {
    vec![
        PromotionLane::SituationWorldState,
        PromotionLane::ModalFact(GraphTruthPlane::Reported),
        PromotionLane::ModalFact(GraphTruthPlane::Conditional),
        PromotionLane::ModalFact(GraphTruthPlane::Hypothetical),
        PromotionLane::ModalFact(GraphTruthPlane::Planned),
        PromotionLane::EventIdentityRoles,
        PromotionLane::TemporalAnchors,
        PromotionLane::CausalEdges,
        PromotionLane::CrossDocumentIdentity,
    ]
}

fn promotion_lane_order() -> Vec<PromotionLane> {
    let mut lanes = graph_lane_order();
    lanes.insert(
        lanes.len() - 1,
        PromotionLane::SemanticPhase5(GraphTruthPlane::WorldState),
    );
    lanes.insert(
        lanes.len() - 1,
        PromotionLane::SemanticPhase5(GraphTruthPlane::Reported),
    );
    lanes.insert(
        lanes.len() - 1,
        PromotionLane::SemanticPhase5(GraphTruthPlane::Conditional),
    );
    lanes.insert(
        lanes.len() - 1,
        PromotionLane::SemanticPhase5(GraphTruthPlane::Hypothetical),
    );
    lanes.insert(
        lanes.len() - 1,
        PromotionLane::SemanticPhase5(GraphTruthPlane::Planned),
    );
    lanes
}

fn graph_source_generations(sidecar: &GraphScopeSidecar) -> Vec<GraphTruthSourceGenerationRef> {
    let manifest = sidecar.resolved_dependency_manifest();
    let mut rows = source_rows(
        sidecar.scope_key.as_str(),
        [
            ("event-identity", manifest.event_identity_generation),
            ("temporal", manifest.temporal_generation),
            ("causal", manifest.causal_generation),
            ("memory", manifest.memory_generation),
        ],
    );
    if rows.is_empty() {
        rows.push(GraphTruthSourceGenerationRef {
            source_id: format!("graph-post:{}", sidecar.scope_key).into(),
            generation: sidecar.generation,
        });
    }
    rows
}

pub(crate) fn semantic_source_generations(
    sidecar: &SemanticGraphScopeSidecar,
) -> Vec<GraphTruthSourceGenerationRef> {
    let manifest = sidecar.resolved_dependency_manifest();
    let mut rows = source_rows(
        sidecar.scope_key.as_str(),
        [
            ("semantic-graph", Some(sidecar.generation)),
            ("graph-post", manifest.graph_generation),
            ("memory", manifest.memory_generation),
            ("event-identity", manifest.event_identity_generation),
        ],
    );
    if rows.is_empty() {
        rows.push(GraphTruthSourceGenerationRef {
            source_id: format!("semantic-graph:{}", sidecar.scope_key).into(),
            generation: sidecar.generation,
        });
    }
    rows
}

fn source_rows<const N: usize>(
    scope_key: &str,
    sources: [(&str, Option<u64>); N],
) -> Vec<GraphTruthSourceGenerationRef> {
    sources
        .into_iter()
        .filter_map(|(label, generation)| {
            generation.map(|generation| GraphTruthSourceGenerationRef {
                source_id: format!("{label}:{scope_key}").into(),
                generation,
            })
        })
        .collect()
}

fn promotion_idempotency_hash<T: Serialize>(
    manifest: &GraphDependencyManifest,
    lane: PromotionLane,
    batch: &T,
) -> Result<GraphTruthDigest, StoreError> {
    let encoded = rmp_serde::to_vec_named(&(manifest, lane.policy_id(), batch))
        .map_err(|error| StoreError::Snapshot(format!("promotion digest encode: {error}")))?;
    digest_bytes(lane.policy_id().as_bytes(), &encoded)
}

fn legacy_graph_projection_hash(
    sidecar: &GraphScopeSidecar,
) -> Result<GraphTruthDigest, StoreError> {
    let encoded = rmp_serde::to_vec_named(&(
        sidecar.scope_key.as_str(),
        sidecar.resolved_dependency_manifest(),
        &sidecar.graph_batch,
    ))
    .map_err(|error| StoreError::Snapshot(format!("graph projection digest encode: {error}")))?;
    digest_bytes(b"graph-post-asserted-projection", &encoded)
}

fn digest_bytes(domain: &[u8], payload: &[u8]) -> Result<GraphTruthDigest, StoreError> {
    let mut lanes = [
        0x7cf1_45c9_3b27_d4a1_u64,
        0x94d0_49bb_1331_11eb_u64,
        0x2545_f491_4f6c_dd1d_u64,
        0x9e37_79b9_7f4a_7c15_u64,
    ];
    mix_digest(&mut lanes, domain);
    mix_digest(&mut lanes, payload);
    let mut bytes = [0u8; 32];
    for (index, value) in lanes.into_iter().enumerate() {
        bytes[index * 8..(index + 1) * 8].copy_from_slice(&value.to_le_bytes());
    }
    Ok(GraphTruthDigest(bytes))
}

fn mix_digest(lanes: &mut [u64; 4], bytes: &[u8]) {
    for (index, byte) in bytes.iter().copied().enumerate() {
        let lane = index & 3;
        lanes[lane] ^= byte as u64 + ((index as u64) << 8);
        lanes[lane] =
            lanes[lane].wrapping_mul(0x1000_0000_01b3).rotate_left(13) ^ 0x9e37_79b9_7f4a_7c15;
    }
    for lane in lanes {
        *lane ^= bytes.len() as u64;
        *lane = lane.rotate_left(17).wrapping_mul(0xff51_afd7_ed55_8ccd);
    }
}

fn promotion_commit_id(lane: PromotionLane, digest: GraphTruthDigest) -> String {
    let mut value = String::with_capacity(128);
    value.push_str("graph-truth:graph-post:promotion:");
    value.push_str(lane.slug());
    value.push(':');
    push_hex_digest(&mut value, digest.0);
    value
}

fn legacy_graph_projection_commit_id(digest: GraphTruthDigest) -> String {
    let mut value = String::with_capacity(96);
    value.push_str("graph-truth:graph-post:projection:");
    push_hex_digest(&mut value, digest.0);
    value
}

pub(crate) fn semantic_edge_type(family: SemanticEdgeFamily) -> &'static str {
    match family {
        SemanticEdgeFamily::ChunkNeighbor => "semantic::chunk_neighbor",
        SemanticEdgeFamily::ClaimSupport => "semantic::claim_support",
        SemanticEdgeFamily::ClaimContradiction => "semantic::claim_contradiction",
        SemanticEdgeFamily::StateSupport => "semantic::state_support",
        SemanticEdgeFamily::StateContradiction => "semantic::state_contradiction",
        SemanticEdgeFamily::ContradictorySupportRegion => "semantic::contradictory_support_region",
        SemanticEdgeFamily::SameSlotFamily => "semantic::same_slot_family",
        SemanticEdgeFamily::SameProcess => "semantic::same_process",
        SemanticEdgeFamily::RelatedEvent => "semantic::related_event",
        SemanticEdgeFamily::MissingIntermediateCause => "semantic::missing_intermediate_cause",
        SemanticEdgeFamily::EntityStateSupport => "semantic::entity_state_support",
        SemanticEdgeFamily::EntityEventSupport => "semantic::entity_event_support",
        SemanticEdgeFamily::EventNeighbor => "semantic::event_neighbor",
        SemanticEdgeFamily::EntityRoleNeighbor => "semantic::entity_role_neighbor",
        SemanticEdgeFamily::Unknown => "semantic::unknown",
    }
}

fn push_hex_digest(output: &mut String, digest: [u8; 32]) {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for byte in digest {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
}
