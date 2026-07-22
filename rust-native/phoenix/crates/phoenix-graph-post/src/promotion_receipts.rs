use compact_str::CompactString;
use hashbrown::HashMap;
use phoenix_graph_kernel::{
    GraphProposalBatchReceipt, GraphProposalFeatures, GraphProposalObservation,
    GraphProposalStatus, GraphTruthAtomKey, KernelEdge, KernelVertex,
    GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
};
use phoenix_semantic_v2::{
    GraphScopeSidecar, SemanticCandidateStatus, SemanticEdgeFamily, SemanticGraphNodeKind,
    SemanticGraphScopeSidecar,
};
use phoenix_store_native_core::StoreError;
use phoenix_types::{
    GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthKind, GraphTruthPlane,
    GraphTruthSourceGenerationRef,
};

use crate::promotion_lanes::{
    plane_from_label, semantic_edge_plane, semantic_edge_type, semantic_source_generations,
    PromotionProposal,
};
use crate::promotion_learner::with_default_promotion_model;

const MAX_RECEIPT_PROPOSALS: usize = 4096;
const MAX_EVIDENCE_REFS: usize = 32;

pub(crate) fn build_graph_projection_proposal_receipt(
    sidecar: &GraphScopeSidecar,
    proposals: &[PromotionProposal],
    source_generations: &[GraphTruthSourceGenerationRef],
) -> Result<Option<GraphProposalBatchReceipt>, StoreError> {
    let proposal_count = proposals
        .iter()
        .map(|proposal| proposal.batch.vertices.len() + proposal.batch.edges.len())
        .sum::<usize>();
    if proposal_count == 0 {
        return Ok(None);
    }
    if proposal_count > MAX_RECEIPT_PROPOSALS {
        return Err(StoreError::Schema(format!(
            "graph projection proposal receipt has {proposal_count} rows; limit is {MAX_RECEIPT_PROPOSALS}"
        )));
    }

    with_default_promotion_model(|model| {
        let mut rows = Vec::with_capacity(proposal_count);
        for proposal in proposals {
            let lane = proposal.lane;
            let vertex_by_id = proposal
                .batch
                .vertices
                .iter()
                .map(|vertex| (vertex.id.0.as_str(), vertex))
                .collect::<HashMap<_, _>>();
            let atom_count = proposal.batch.vertices.len() + proposal.batch.edges.len();
            for vertex in &proposal.batch.vertices {
                let features = projection_vertex_features(proposal, vertex, atom_count);
                rows.push(GraphProposalObservation {
                    proposal_id: CompactString::new(projection_vertex_proposal_id(lane, vertex)),
                    atom: GraphTruthAtomKey::vertex(vertex.id.0.as_str()),
                    family: CompactString::new(lane.slug()),
                    source_kind: CompactString::new(vertex.kind.as_str()),
                    target_kind: CompactString::new(vertex_class_label(vertex)),
                    truth: lane.truth_descriptor(),
                    status: GraphProposalStatus::ReviewedSupport,
                    evidence_refs: Default::default(),
                    features,
                    shadow_score_millis: model.map(|value| value.score_millis(features)),
                });
            }
            for edge in &proposal.batch.edges {
                let features = projection_edge_features(proposal, edge, atom_count);
                rows.push(GraphProposalObservation {
                    proposal_id: CompactString::new(projection_edge_proposal_id(lane, edge)),
                    atom: GraphTruthAtomKey::edge(
                        edge.source_id.0.as_str(),
                        edge.target_id.0.as_str(),
                        edge.edge_type.0.as_str(),
                    ),
                    family: CompactString::new(lane.slug()),
                    source_kind: CompactString::new(
                        vertex_by_id
                            .get(edge.source_id.0.as_str())
                            .map(|vertex| vertex.kind.as_str())
                            .unwrap_or("unknown"),
                    ),
                    target_kind: CompactString::new(
                        vertex_by_id
                            .get(edge.target_id.0.as_str())
                            .map(|vertex| vertex.kind.as_str())
                            .unwrap_or("unknown"),
                    ),
                    truth: lane.truth_descriptor(),
                    status: GraphProposalStatus::ReviewedSupport,
                    evidence_refs: Default::default(),
                    features,
                    shadow_score_millis: model.map(|value| value.score_millis(features)),
                });
            }
        }
        rows.sort_unstable_by(|left, right| {
            left.family
                .cmp(&right.family)
                .then_with(|| left.proposal_id.cmp(&right.proposal_id))
        });
        let receipt = GraphProposalBatchReceipt {
            schema_version: GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
            receipt_id: graph_projection_receipt_id(sidecar, &rows)?.into(),
            scope_key: CompactString::new(sidecar.scope_key.as_str()),
            generation: sidecar.generation,
            created_at: sidecar.updated_at,
            compiler_policy: GraphTruthCompilerPolicy {
                compiler_id: "phoenix-graph-post".into(),
                compiler_version: env!("CARGO_PKG_VERSION").into(),
                policy_id: "graph-post-proposal:projection-lanes".into(),
                policy_version: "1".into(),
            },
            source_generations: source_generations.iter().cloned().collect(),
            model_id: model.map(|value| value.model_id.clone()),
            discovery_origin: None,
            proposals: rows,
        };
        receipt
            .validate()
            .map_err(|error| StoreError::Schema(error.to_string()))?;
        Ok(Some(receipt))
    })
}

pub(crate) fn build_semantic_proposal_receipt(
    sidecar: &SemanticGraphScopeSidecar,
) -> Result<Option<GraphProposalBatchReceipt>, StoreError> {
    if sidecar.candidate_edges.is_empty() {
        return Ok(None);
    }
    let node_by_id = sidecar
        .candidate_nodes
        .iter()
        .map(|node| (node.node_id.as_str(), node))
        .collect::<HashMap<_, _>>();
    let promoted_count = sidecar
        .candidate_edges
        .iter()
        .filter(|candidate| is_promoted(candidate.candidate_status))
        .count();
    if promoted_count > MAX_RECEIPT_PROPOSALS {
        return Err(StoreError::Schema(format!(
            "semantic proposal receipt has {promoted_count} promoted rows; limit is {MAX_RECEIPT_PROPOSALS}"
        )));
    }

    let mut candidates = sidecar.candidate_edges.iter().collect::<Vec<_>>();
    candidates.sort_unstable_by(|left, right| {
        status_rank(left.candidate_status)
            .cmp(&status_rank(right.candidate_status))
            .then_with(|| right.score_millis.cmp(&left.score_millis))
            .then_with(|| left.edge_id.cmp(&right.edge_id))
    });
    candidates.truncate(MAX_RECEIPT_PROPOSALS);

    with_default_promotion_model(|model| {
        let mut proposals = Vec::with_capacity(candidates.len());
        for candidate in candidates {
            let source = node_by_id.get(candidate.source_node_id.as_str()).copied();
            let target = node_by_id.get(candidate.target_node_id.as_str()).copied();
            let plane = semantic_edge_plane(
                source.and_then(|node| plane_from_label(node.truth_plane.as_deref())),
                target.and_then(|node| plane_from_label(node.truth_plane.as_deref())),
            )
            .unwrap_or(GraphTruthPlane::Unknown);
            let features = proposal_features(sidecar, candidate, source, target);
            proposals.push(GraphProposalObservation {
                proposal_id: CompactString::new(candidate.edge_id.as_str()),
                atom: GraphTruthAtomKey::edge(
                    candidate.source_node_id.as_str(),
                    candidate.target_node_id.as_str(),
                    semantic_edge_type(candidate.family),
                ),
                family: CompactString::new(family_label(candidate.family)),
                source_kind: CompactString::new(node_kind_label(candidate.source_kind)),
                target_kind: CompactString::new(node_kind_label(candidate.target_kind)),
                truth: GraphTruthDescriptor {
                    kind: GraphTruthKind::Semantic,
                    plane: Some(plane),
                },
                status: proposal_status(candidate.candidate_status),
                evidence_refs: candidate
                    .evidence_refs
                    .iter()
                    .take(MAX_EVIDENCE_REFS)
                    .map(CompactString::new)
                    .collect(),
                features,
                shadow_score_millis: model.map(|value| value.score_millis(features)),
            });
        }

        let receipt = GraphProposalBatchReceipt {
            schema_version: GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
            receipt_id: semantic_proposal_receipt_id(sidecar, &proposals)?.into(),
            scope_key: CompactString::new(sidecar.scope_key.as_str()),
            generation: sidecar.generation,
            created_at: sidecar.updated_at,
            compiler_policy: GraphTruthCompilerPolicy {
                compiler_id: "phoenix-graph-post".into(),
                compiler_version: env!("CARGO_PKG_VERSION").into(),
                policy_id: "graph-post-proposal:semantic-phase5".into(),
                policy_version: "1".into(),
            },
            source_generations: semantic_source_generations(sidecar).into_iter().collect(),
            model_id: model.map(|value| value.model_id.clone()),
            discovery_origin: None,
            proposals,
        };
        receipt
            .validate()
            .map_err(|error| StoreError::Schema(error.to_string()))?;
        Ok(Some(receipt))
    })
}

fn proposal_features(
    sidecar: &SemanticGraphScopeSidecar,
    candidate: &phoenix_semantic_v2::SemanticGraphEdgeCandidate,
    source: Option<&phoenix_semantic_v2::SemanticGraphNodeRecord>,
    target: Option<&phoenix_semantic_v2::SemanticGraphNodeRecord>,
) -> GraphProposalFeatures {
    let support = candidate.nli_support_millis.unwrap_or_default().min(1000) as i16;
    let contradiction = candidate
        .nli_contradiction_millis
        .unwrap_or_default()
        .min(1000) as i16;
    let threshold = sidecar
        .candidate_lifecycle_policy
        .family_thresholds
        .iter()
        .find(|row| row.family == candidate.family)
        .map(|row| row.min_score_millis)
        .unwrap_or(
            sidecar
                .candidate_lifecycle_policy
                .generated_min_score_millis,
        );
    let same_document = source
        .and_then(|node| node.document_id.as_deref())
        .zip(target.and_then(|node| node.document_id.as_deref()))
        .is_some_and(|(left, right)| left == right);
    let same_narrative = source
        .and_then(|node| node.narrative_id.as_deref())
        .zip(target.and_then(|node| node.narrative_id.as_deref()))
        .is_some_and(|(left, right)| left == right);
    let cross_document = source
        .and_then(|node| node.document_id.as_deref())
        .zip(target.and_then(|node| node.document_id.as_deref()))
        .is_some_and(|(left, right)| left != right);
    let status = candidate.candidate_status;
    GraphProposalFeatures([
        candidate.score_millis.min(1000) as i16,
        1000_i16.saturating_sub(candidate.distance_millis.min(1000) as i16),
        support,
        contradiction,
        support.saturating_sub(contradiction),
        scaled_count(candidate.evidence_refs.len(), 64),
        scaled_count(candidate.model_evidence.len(), 125),
        clamp_i16(candidate.score_millis as i64 - threshold as i64),
        flag(same_document),
        flag(same_narrative),
        flag(cross_document),
        flag(status == SemanticCandidateStatus::ReviewedSupport),
        flag(status == SemanticCandidateStatus::ReviewedContradiction),
        flag(status == SemanticCandidateStatus::Deferred),
        flag(status == SemanticCandidateStatus::Generated),
        flag(candidate.nli_support_millis.is_some()),
    ])
}

fn semantic_proposal_receipt_id(
    sidecar: &SemanticGraphScopeSidecar,
    proposals: &[GraphProposalObservation],
) -> Result<String, StoreError> {
    let encoded = rmp_serde::to_vec_named(&(
        sidecar.scope_key.as_str(),
        sidecar.generation,
        sidecar.resolved_dependency_manifest(),
        proposals,
    ))
    .map_err(|error| StoreError::Snapshot(format!("proposal receipt digest encode: {error}")))?;
    let mut lanes = [
        0x243f_6a88_85a3_08d3_u64,
        0x1319_8a2e_0370_7344_u64,
        0xa409_3822_299f_31d0_u64,
        0x082e_fa98_ec4e_6c89_u64,
    ];
    for (index, byte) in encoded.iter().copied().enumerate() {
        let lane = index & 3;
        lanes[lane] ^= byte as u64 + ((index as u64) << 8);
        lanes[lane] = lanes[lane].wrapping_mul(0x1000_0000_01b3).rotate_left(11);
    }
    let mut id = String::with_capacity(96);
    id.push_str("graph-proposal:semantic-phase5:");
    for lane in lanes {
        use std::fmt::Write;
        write!(&mut id, "{lane:016x}").expect("write string");
    }
    Ok(id)
}

fn graph_projection_receipt_id(
    sidecar: &GraphScopeSidecar,
    proposals: &[GraphProposalObservation],
) -> Result<String, StoreError> {
    let encoded = rmp_serde::to_vec_named(&(
        sidecar.scope_key.as_str(),
        sidecar.generation,
        sidecar.resolved_dependency_manifest(),
        proposals,
    ))
    .map_err(|error| StoreError::Snapshot(format!("projection receipt digest encode: {error}")))?;
    let mut id = String::with_capacity(96);
    id.push_str("graph-proposal:projection-lanes:");
    for lane in digest_lanes(&encoded) {
        use std::fmt::Write;
        write!(&mut id, "{lane:016x}").expect("write string");
    }
    Ok(id)
}

fn digest_lanes(bytes: &[u8]) -> [u64; 4] {
    let mut lanes = [
        0x243f_6a88_85a3_08d3_u64,
        0x1319_8a2e_0370_7344_u64,
        0xa409_3822_299f_31d0_u64,
        0x082e_fa98_ec4e_6c89_u64,
    ];
    for (index, byte) in bytes.iter().copied().enumerate() {
        let lane = index & 3;
        lanes[lane] ^= byte as u64 + ((index as u64) << 8);
        lanes[lane] = lanes[lane].wrapping_mul(0x1000_0000_01b3).rotate_left(11);
    }
    lanes
}

fn projection_vertex_proposal_id(
    lane: crate::promotion_lanes::PromotionLane,
    vertex: &KernelVertex,
) -> String {
    format!("{}:vertex:{}", lane.slug(), vertex.id.0)
}

fn projection_edge_proposal_id(
    lane: crate::promotion_lanes::PromotionLane,
    edge: &KernelEdge,
) -> String {
    format!(
        "{}:edge:{}:{}:{}",
        lane.slug(),
        edge.source_id.0,
        edge.target_id.0,
        edge.edge_type.0
    )
}

fn projection_vertex_features(
    proposal: &PromotionProposal,
    vertex: &KernelVertex,
    atom_count: usize,
) -> GraphProposalFeatures {
    let plane_score = proposal
        .lane
        .truth_descriptor()
        .plane
        .map(plane_feature)
        .unwrap_or_default();
    GraphProposalFeatures([
        lane_feature(proposal.lane),
        1000,
        0,
        scaled_count(proposal.batch.vertices.len(), 96),
        scaled_count(proposal.batch.edges.len(), 96),
        scaled_count(atom_count, 64),
        scaled_count(vertex.labels.len(), 125),
        clamp_i16(vertex.weight),
        plane_score,
        flag(vertex.entity_id.is_some()),
        flag(vertex.document_id.is_some()),
        flag(vertex.temporal.recorded_at.is_some()),
        flag(vertex.temporal.valid_from.is_some() || vertex.temporal.valid_to.is_some()),
        flag(vertex.provenance.confidence.is_some()),
        flag(vertex.attributes.is_object()),
        flag(vertex.value.is_object()),
    ])
}

fn projection_edge_features(
    proposal: &PromotionProposal,
    edge: &KernelEdge,
    atom_count: usize,
) -> GraphProposalFeatures {
    let plane_score = proposal
        .lane
        .truth_descriptor()
        .plane
        .map(plane_feature)
        .unwrap_or_default();
    GraphProposalFeatures([
        lane_feature(proposal.lane),
        0,
        1000,
        scaled_count(proposal.batch.vertices.len(), 96),
        scaled_count(proposal.batch.edges.len(), 96),
        scaled_count(atom_count, 64),
        scaled_count(edge.edge_type.0.len(), 16),
        clamp_i16(edge.weight),
        plane_score,
        relation_class_feature(edge),
        flag(edge.document_id.is_some()),
        flag(edge.temporal.recorded_at.is_some()),
        flag(edge.temporal.valid_from.is_some() || edge.temporal.valid_to.is_some()),
        flag(edge.provenance.confidence.is_some()),
        flag(edge.attributes.is_object()),
        flag(edge.data.is_some()),
    ])
}

fn lane_feature(lane: crate::promotion_lanes::PromotionLane) -> i16 {
    use crate::promotion_lanes::PromotionLane::*;
    match lane {
        SituationWorldState => 100,
        ModalFact(GraphTruthPlane::Reported) => 200,
        ModalFact(GraphTruthPlane::Conditional) => 300,
        ModalFact(GraphTruthPlane::Hypothetical) => 400,
        ModalFact(GraphTruthPlane::Planned) => 500,
        ModalFact(_) => 550,
        EventIdentityRoles => 650,
        TemporalAnchors => 750,
        CausalEdges => 850,
        SemanticPhase5(_) => 900,
        CrossDocumentIdentity => 1000,
    }
}

fn plane_feature(plane: GraphTruthPlane) -> i16 {
    match plane {
        GraphTruthPlane::WorldState => 100,
        GraphTruthPlane::Reported => 250,
        GraphTruthPlane::Conditional => 400,
        GraphTruthPlane::Hypothetical => 550,
        GraphTruthPlane::Planned => 700,
        GraphTruthPlane::Mixed => 850,
        GraphTruthPlane::Unknown => 0,
    }
}

fn relation_class_feature(edge: &KernelEdge) -> i16 {
    use phoenix_graph_kernel::KernelRelationClass::*;
    match edge.relation_class {
        Structural => 100,
        Semantic => 250,
        Identity => 400,
        Resolution => 500,
        Temporal => 600,
        Calendar => 700,
        Memory => 800,
        Narrative => 850,
        Candidate => 900,
        Custom => 1000,
    }
}

fn vertex_class_label(vertex: &KernelVertex) -> &'static str {
    use phoenix_graph_kernel::KernelVertexClass::*;
    match vertex.class {
        Document => "document",
        Chunk => "chunk",
        Entity => "entity",
        Alias => "alias",
        Mention => "mention",
        TimeAnchor => "timeAnchor",
        CalendarAnchor => "calendarAnchor",
        Narrative => "narrative",
        Episode => "episode",
        Memory => "memory",
        Task => "task",
        State => "state",
        Event => "event",
        Generic => "generic",
    }
}

fn proposal_status(status: SemanticCandidateStatus) -> GraphProposalStatus {
    match status {
        SemanticCandidateStatus::Generated => GraphProposalStatus::Generated,
        SemanticCandidateStatus::ReviewedSupport => GraphProposalStatus::ReviewedSupport,
        SemanticCandidateStatus::ReviewedContradiction => {
            GraphProposalStatus::ReviewedContradiction
        }
        SemanticCandidateStatus::Deferred => GraphProposalStatus::Deferred,
        SemanticCandidateStatus::Rejected => GraphProposalStatus::Rejected,
    }
}

fn is_promoted(status: SemanticCandidateStatus) -> bool {
    matches!(
        status,
        SemanticCandidateStatus::ReviewedSupport | SemanticCandidateStatus::ReviewedContradiction
    )
}

fn status_rank(status: SemanticCandidateStatus) -> u8 {
    match status {
        SemanticCandidateStatus::ReviewedSupport => 0,
        SemanticCandidateStatus::ReviewedContradiction => 1,
        SemanticCandidateStatus::Deferred => 2,
        SemanticCandidateStatus::Generated => 3,
        SemanticCandidateStatus::Rejected => 4,
    }
}

fn family_label(family: SemanticEdgeFamily) -> &'static str {
    use SemanticEdgeFamily::*;
    match family {
        ChunkNeighbor => "chunkNeighbor",
        ClaimSupport => "claimSupport",
        ClaimContradiction => "claimContradiction",
        StateSupport => "stateSupport",
        StateContradiction => "stateContradiction",
        ContradictorySupportRegion => "contradictorySupportRegion",
        SameSlotFamily => "sameSlotFamily",
        SameProcess => "sameProcess",
        RelatedEvent => "relatedEvent",
        MissingIntermediateCause => "missingIntermediateCause",
        EntityStateSupport => "entityStateSupport",
        EntityEventSupport => "entityEventSupport",
        EventNeighbor => "eventNeighbor",
        EntityRoleNeighbor => "entityRoleNeighbor",
        Unknown => "unknown",
    }
}

fn node_kind_label(kind: SemanticGraphNodeKind) -> &'static str {
    match kind {
        SemanticGraphNodeKind::Chunk => "chunk",
        SemanticGraphNodeKind::Claim => "claim",
        SemanticGraphNodeKind::State => "state",
        SemanticGraphNodeKind::Event => "event",
        SemanticGraphNodeKind::Entity => "entity",
        SemanticGraphNodeKind::Unknown => "unknown",
    }
}

fn scaled_count(count: usize, scale: i16) -> i16 {
    (count.min(1000) as i16).saturating_mul(scale).min(1000)
}

fn clamp_i16(value: i64) -> i16 {
    value.clamp(-1000, 1000) as i16
}

fn flag(value: bool) -> i16 {
    if value {
        1000
    } else {
        0
    }
}
