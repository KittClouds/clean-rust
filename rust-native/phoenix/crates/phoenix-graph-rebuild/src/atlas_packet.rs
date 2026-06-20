use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};
use phoenix_types::EntityId;
use serde::{Deserialize, Serialize};

use crate::types::{
    GraphAnchor, GraphChunk, GraphDocumentCompilerHyperedge, GraphDocumentCompilerHyperedgeRole,
    GraphEmbeddingTarget, GraphEvent, GraphMemoryState, GraphNode, GraphRebuildSnapshot,
    GraphRelationship, GraphScopeKind, GraphTemporalEdge,
};

mod ids;
mod taxonomy;

use ids::{
    anchor_object_id, chunk_object_id, entity_object_id, event_object_id, fact_object_id,
    hyperedge_object_id, hyperedge_role_object_id, memory_object_id, note_object_id,
    story_edge_object_id,
};
use taxonomy::{
    admission_for_target, document_unit_kind, entity_kind_from_target, hyperedge_role_style_key,
    memory_style_key, relation_style_key, state_context_kind, status_for_admission,
    story_edge_lane, story_edge_style_key, target_lane, target_structural_role, target_style_key,
};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AtlasPacket {
    pub schema_version: CompactString,
    pub snapshot_id: CompactString,
    pub scope_kind: GraphScopeKind,
    pub scope_id: CompactString,
    pub built_at: u64,
    pub source_contract: AtlasSourceContract,
    pub objects: Vec<AtlasObject>,
    pub manifold_targets: Vec<ManifoldTarget>,
    pub counters: AtlasPacketCounters,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AtlasSourceContract {
    pub authority: CompactString,
    pub identity_authority: CompactString,
    pub vector_contract: CompactString,
    pub ts_graph_builder_role: CompactString,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphFamily {
    Registry,
    Entity,
    Structure,
    Fact,
    Discourse,
    Review,
    Evidence,
    Temporal,
    Causal,
    Memory,
    Hypergraph,
    Unknown,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum AtlasObjectStatus {
    Accepted,
    Proposed,
    Review,
    Rejected,
    Deferred,
    LedgerOnly,
    CompiledToGraph,
    Muted,
    PromotedToAnchor,
    Unknown,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ManifoldAdmission {
    Candidate,
    Admitted,
    Deferred,
    Rejected,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum AtlasVectorStatus {
    Missing,
    ModelVector,
    External,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AtlasObject {
    pub id: CompactString,
    pub family: GraphFamily,
    pub status: AtlasObjectStatus,
    pub kind: CompactString,
    pub label: CompactString,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub style_key: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lane: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub structural_role: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub document_unit_kind: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub state_context_kind: Option<CompactString>,
    #[serde(default)]
    pub registry_entity_id: Option<EntityId>,
    #[serde(default)]
    pub note_ids: Vec<CompactString>,
    #[serde(default)]
    pub chunk_ids: Vec<CompactString>,
    #[serde(default)]
    pub anchor_ids: Vec<CompactString>,
    #[serde(default)]
    pub evidence_ids: Vec<CompactString>,
    #[serde(default)]
    pub source_ids: Vec<CompactString>,
    #[serde(default)]
    pub target_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ManifoldTarget {
    pub id: CompactString,
    pub object_id: CompactString,
    pub family: GraphFamily,
    pub admission: ManifoldAdmission,
    pub status: AtlasObjectStatus,
    pub vector_status: AtlasVectorStatus,
    pub coordinate_source: CompactString,
    pub kind: CompactString,
    pub label: CompactString,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub entity_kind: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub style_key: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lane: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub structural_role: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub document_unit_kind: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub state_context_kind: Option<CompactString>,
    pub source_id: CompactString,
    #[serde(default)]
    pub registry_entity_id: Option<EntityId>,
    #[serde(default)]
    pub note_id: Option<CompactString>,
    #[serde(default)]
    pub chunk_id: Option<CompactString>,
    #[serde(default)]
    pub evidence_ids: Vec<CompactString>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub parent_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AtlasPacketCounters {
    pub objects: usize,
    pub manifold_targets: usize,
    pub registry_entities: usize,
    pub evidence_anchors: usize,
    pub model_vectors: usize,
    pub families: Vec<AtlasFamilyCount>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AtlasFamilyCount {
    pub family: GraphFamily,
    pub count: usize,
}

pub fn build_atlas_packet(snapshot: &GraphRebuildSnapshot) -> AtlasPacket {
    let mut objects = Vec::with_capacity(
        snapshot.note_ids.len()
            + snapshot.nodes.len()
            + snapshot.chunks.len()
            + snapshot.entity_anchors.len()
            + snapshot.relationships.len()
            + snapshot.events.len()
            + snapshot.temporal_edges.len()
            + snapshot.causal_edges.len()
            + snapshot.memory_state.len()
            + snapshot
                .document_compiler_summary
                .as_ref()
                .map(|summary| {
                    summary.hyperedges.len()
                        + summary
                            .hyperedges
                            .iter()
                            .map(|hyperedge| hyperedge.roles.len())
                            .sum::<usize>()
                })
                .unwrap_or(0),
    );
    let mut source_to_object = HashMap::<CompactString, CompactString>::new();
    let mut seen = HashSet::<CompactString>::new();

    for note_id in &snapshot.note_ids {
        push_object(
            &mut objects,
            &mut seen,
            &mut source_to_object,
            note_object(snapshot, note_id),
        );
    }
    for node in &snapshot.nodes {
        push_object(
            &mut objects,
            &mut seen,
            &mut source_to_object,
            entity_object(node),
        );
    }
    for chunk in &snapshot.chunks {
        push_object(
            &mut objects,
            &mut seen,
            &mut source_to_object,
            chunk_object(chunk),
        );
    }
    for anchor in &snapshot.entity_anchors {
        push_object(
            &mut objects,
            &mut seen,
            &mut source_to_object,
            anchor_object(anchor),
        );
    }
    for relationship in &snapshot.relationships {
        push_object(
            &mut objects,
            &mut seen,
            &mut source_to_object,
            relationship_object(relationship),
        );
    }
    for event in &snapshot.events {
        push_object(
            &mut objects,
            &mut seen,
            &mut source_to_object,
            event_object(event),
        );
    }
    for edge in &snapshot.temporal_edges {
        push_object(
            &mut objects,
            &mut seen,
            &mut source_to_object,
            story_edge_object(edge, GraphFamily::Temporal, "temporalFact"),
        );
    }
    for edge in &snapshot.causal_edges {
        push_object(
            &mut objects,
            &mut seen,
            &mut source_to_object,
            story_edge_object(edge, GraphFamily::Causal, "causalFact"),
        );
    }
    for state in &snapshot.memory_state {
        push_object(
            &mut objects,
            &mut seen,
            &mut source_to_object,
            memory_object(state),
        );
    }
    if let Some(compiler) = &snapshot.document_compiler_summary {
        for hyperedge in &compiler.hyperedges {
            push_object(
                &mut objects,
                &mut seen,
                &mut source_to_object,
                hyperedge_object(hyperedge),
            );
            for role in &hyperedge.roles {
                push_object(
                    &mut objects,
                    &mut seen,
                    &mut source_to_object,
                    hyperedge_role_object(hyperedge, role),
                );
            }
        }
    }

    let vector_status = vector_status_for(snapshot);
    let coordinate_source = coordinate_source_for(vector_status);
    let manifold_targets = snapshot
        .embedding_targets
        .iter()
        .map(|target| manifold_target(target, &source_to_object, vector_status, &coordinate_source))
        .collect::<Vec<_>>();
    let counters = packet_counters(&objects, &manifold_targets, snapshot);

    AtlasPacket {
        schema_version: "phoenix-atlas-packet/v1".into(),
        snapshot_id: snapshot.id.clone(),
        scope_kind: snapshot.scope_kind,
        scope_id: snapshot.scope_id.clone(),
        built_at: snapshot.built_at,
        source_contract: AtlasSourceContract {
            authority: "rust-atlas-packet".into(),
            identity_authority: "registry-entities-and-accepted-anchors".into(),
            vector_contract: if vector_status == AtlasVectorStatus::ModelVector {
                "model-vectors".into()
            } else {
                "vectors-missing".into()
            },
            ts_graph_builder_role: "native-atlas-packet-authority".into(),
        },
        objects,
        manifold_targets,
        counters,
    }
}

fn note_object(snapshot: &GraphRebuildSnapshot, note_id: &CompactString) -> AtlasObject {
    AtlasObject {
        id: note_object_id(note_id),
        family: GraphFamily::Structure,
        status: AtlasObjectStatus::Accepted,
        kind: "note".into(),
        label: format_compact!("Note {note_id}"),
        style_key: Some("document".into()),
        lane: Some("document_spine".into()),
        structural_role: Some("root".into()),
        document_unit_kind: None,
        state_context_kind: None,
        registry_entity_id: None,
        note_ids: vec![note_id.clone()],
        chunk_ids: Vec::new(),
        anchor_ids: Vec::new(),
        evidence_ids: Vec::new(),
        source_ids: vec![note_id.clone(), snapshot.scope_id.clone()],
        target_ids: Vec::new(),
    }
}

fn entity_object(node: &GraphNode) -> AtlasObject {
    AtlasObject {
        id: entity_object_id(&node.entity_id),
        family: GraphFamily::Registry,
        status: AtlasObjectStatus::Accepted,
        kind: node.kind.clone(),
        label: node.label.clone(),
        style_key: Some(node.kind.clone()),
        lane: Some("entity_anchor".into()),
        structural_role: Some("child".into()),
        document_unit_kind: None,
        state_context_kind: None,
        registry_entity_id: Some(node.entity_id.clone()),
        note_ids: node.note_ids.clone(),
        chunk_ids: Vec::new(),
        anchor_ids: node.anchor_ids.clone(),
        evidence_ids: node.anchor_ids.clone(),
        source_ids: vec![node.entity_id.0.as_str().into()],
        target_ids: Vec::new(),
    }
}

fn chunk_object(chunk: &GraphChunk) -> AtlasObject {
    AtlasObject {
        id: chunk_object_id(&chunk.id),
        family: GraphFamily::Structure,
        status: AtlasObjectStatus::LedgerOnly,
        kind: "chunk".into(),
        label: format_compact!("Chunk {}", chunk.ordinal + 1),
        style_key: Some("chunk".into()),
        lane: Some("chunk_spine".into()),
        structural_role: Some("spine".into()),
        document_unit_kind: None,
        state_context_kind: None,
        registry_entity_id: None,
        note_ids: vec![chunk.note_id.clone()],
        chunk_ids: vec![chunk.id.clone()],
        anchor_ids: Vec::new(),
        evidence_ids: Vec::new(),
        source_ids: vec![chunk.id.clone()],
        target_ids: Vec::new(),
    }
}

fn anchor_object(anchor: &GraphAnchor) -> AtlasObject {
    AtlasObject {
        id: anchor_object_id(&anchor.id),
        family: GraphFamily::Evidence,
        status: AtlasObjectStatus::Accepted,
        kind: "entityAnchor".into(),
        label: anchor.surface.clone(),
        style_key: Some("anchor".into()),
        lane: Some("anchor_evidence".into()),
        structural_role: Some("evidence".into()),
        document_unit_kind: None,
        state_context_kind: None,
        registry_entity_id: Some(anchor.entity_id.clone()),
        note_ids: vec![anchor.note_id.clone()],
        chunk_ids: anchor.chunk_id.iter().cloned().collect(),
        anchor_ids: vec![anchor.id.clone()],
        evidence_ids: vec![anchor.id.clone()],
        source_ids: vec![anchor.id.clone(), anchor.entity_id.0.as_str().into()],
        target_ids: vec![entity_object_id(&anchor.entity_id)],
    }
}

fn relationship_object(relationship: &GraphRelationship) -> AtlasObject {
    AtlasObject {
        id: fact_object_id(&relationship.id),
        family: GraphFamily::Fact,
        status: status_from_text(&relationship.status),
        kind: relationship.relation_type.clone(),
        label: format_compact!(
            "{} {} {}",
            relationship.source_entity_id.0,
            relationship.relation_type,
            relationship.target_entity_id.0
        ),
        style_key: Some(relation_style_key(
            relationship.relation_type.as_str(),
            relationship.rationale.as_str(),
        )),
        lane: Some("relationship_fact".into()),
        structural_role: Some("fact".into()),
        document_unit_kind: None,
        state_context_kind: None,
        registry_entity_id: None,
        note_ids: Vec::new(),
        chunk_ids: Vec::new(),
        anchor_ids: relationship.evidence_anchor_ids.clone(),
        evidence_ids: relationship.evidence_anchor_ids.clone(),
        source_ids: vec![relationship.id.clone()],
        target_ids: vec![
            entity_object_id(&relationship.source_entity_id),
            entity_object_id(&relationship.target_entity_id),
        ],
    }
}

fn event_object(event: &GraphEvent) -> AtlasObject {
    AtlasObject {
        id: event_object_id(&event.id),
        family: GraphFamily::Fact,
        status: AtlasObjectStatus::Accepted,
        kind: "event".into(),
        label: event.label.clone(),
        style_key: Some("eventNode".into()),
        lane: Some("event_identity".into()),
        structural_role: Some("fact".into()),
        document_unit_kind: None,
        state_context_kind: None,
        registry_entity_id: event.entity_ids.first().cloned(),
        note_ids: vec![event.note_id.clone()],
        chunk_ids: event.chunk_id.iter().cloned().collect(),
        anchor_ids: event.evidence_anchor_ids.clone(),
        evidence_ids: event.evidence_anchor_ids.clone(),
        source_ids: vec![event.id.clone()],
        target_ids: event.entity_ids.iter().map(entity_object_id).collect(),
    }
}

fn story_edge_object(edge: &GraphTemporalEdge, family: GraphFamily, kind: &str) -> AtlasObject {
    AtlasObject {
        id: story_edge_object_id(kind, &edge.id),
        family,
        status: AtlasObjectStatus::Accepted,
        kind: kind.into(),
        label: edge.relation_type.clone(),
        style_key: Some(story_edge_style_key(kind)),
        lane: Some(story_edge_lane(kind)),
        structural_role: Some("fact".into()),
        document_unit_kind: None,
        state_context_kind: None,
        registry_entity_id: None,
        note_ids: Vec::new(),
        chunk_ids: Vec::new(),
        anchor_ids: edge.evidence_ids.clone(),
        evidence_ids: edge.evidence_ids.clone(),
        source_ids: vec![
            edge.id.clone(),
            edge.source_id.clone(),
            edge.target_id.clone(),
        ],
        target_ids: vec![edge.source_id.clone(), edge.target_id.clone()],
    }
}

fn memory_object(state: &GraphMemoryState) -> AtlasObject {
    AtlasObject {
        id: memory_object_id(&state.id),
        family: GraphFamily::Memory,
        status: AtlasObjectStatus::Accepted,
        kind: "memoryState".into(),
        label: state.key.clone(),
        style_key: Some(memory_style_key(state.key.as_str(), state.value.as_str())),
        lane: Some("memory_state".into()),
        structural_role: Some("child".into()),
        document_unit_kind: None,
        state_context_kind: Some(memory_style_key(state.key.as_str(), state.value.as_str())),
        registry_entity_id: Some(state.entity_id.clone()),
        note_ids: state.note_id.iter().cloned().collect(),
        chunk_ids: Vec::new(),
        anchor_ids: state.evidence_ids.clone(),
        evidence_ids: state.evidence_ids.clone(),
        source_ids: vec![state.id.clone()],
        target_ids: vec![entity_object_id(&state.entity_id)],
    }
}

fn hyperedge_object(hyperedge: &GraphDocumentCompilerHyperedge) -> AtlasObject {
    AtlasObject {
        id: hyperedge_object_id(&hyperedge.id),
        family: GraphFamily::Hypergraph,
        status: status_from_text(&hyperedge.status),
        kind: "documentSituation".into(),
        label: hyperedge
            .trigger_predicate
            .clone()
            .unwrap_or_else(|| hyperedge.predicate.clone()),
        style_key: Some("relationship".into()),
        lane: Some("hypergraph".into()),
        structural_role: Some("fact".into()),
        document_unit_kind: None,
        state_context_kind: None,
        registry_entity_id: None,
        note_ids: Vec::new(),
        chunk_ids: Vec::new(),
        anchor_ids: Vec::new(),
        evidence_ids: hyperedge.evidence_span_ids.clone(),
        source_ids: vec![hyperedge.id.clone()],
        target_ids: hyperedge
            .roles
            .iter()
            .map(|role| hyperedge_role_object_id(&hyperedge.id, &role.id))
            .collect(),
    }
}

fn hyperedge_role_object(
    hyperedge: &GraphDocumentCompilerHyperedge,
    role: &GraphDocumentCompilerHyperedgeRole,
) -> AtlasObject {
    AtlasObject {
        id: hyperedge_role_object_id(&hyperedge.id, &role.id),
        family: GraphFamily::Hypergraph,
        status: role
            .resolved
            .map(|resolved| {
                if resolved {
                    AtlasObjectStatus::Accepted
                } else {
                    AtlasObjectStatus::Review
                }
            })
            .unwrap_or(AtlasObjectStatus::Unknown),
        kind: role
            .semantic_role
            .clone()
            .unwrap_or_else(|| role.role.clone()),
        label: role
            .surface
            .clone()
            .unwrap_or_else(|| role.target_id.clone()),
        style_key: Some(hyperedge_role_style_key(role)),
        lane: Some("hypergraph_role".into()),
        structural_role: Some(
            role.semantic_role
                .clone()
                .unwrap_or_else(|| role.role.clone()),
        ),
        document_unit_kind: if role.target_kind == "document_unit" {
            Some("document_unit".into())
        } else {
            None
        },
        state_context_kind: None,
        registry_entity_id: if role.target_kind == "entity" {
            Some(EntityId(role.target_id.as_str().to_owned()))
        } else {
            None
        },
        note_ids: Vec::new(),
        chunk_ids: Vec::new(),
        anchor_ids: Vec::new(),
        evidence_ids: if role.target_kind == "evidence_span" {
            vec![role.target_id.clone()]
        } else {
            Vec::new()
        },
        source_ids: vec![role.id.clone(), role.target_id.clone()],
        target_ids: vec![hyperedge_object_id(&hyperedge.id)],
    }
}

fn manifold_target(
    target: &GraphEmbeddingTarget,
    source_to_object: &HashMap<CompactString, CompactString>,
    vector_status: AtlasVectorStatus,
    coordinate_source: &CompactString,
) -> ManifoldTarget {
    let object_id = object_id_for_target(target, source_to_object);
    let family = family_for_target(target);
    let admission = admission_for_target(target);
    let lane = target_lane(target, family);
    let structural_role = target_structural_role(target, family, lane.as_deref());
    let document_unit_kind = document_unit_kind(target);
    let state_context_kind = state_context_kind(target);
    let style_key = target
        .style_key
        .clone()
        .or_else(|| state_context_kind.clone())
        .or_else(|| target_style_key(target, family, document_unit_kind.as_deref()));
    ManifoldTarget {
        id: target.id.clone(),
        object_id,
        family,
        admission,
        status: status_for_admission(admission),
        vector_status,
        coordinate_source: coordinate_source.clone(),
        kind: target.kind.clone(),
        label: target.label.clone(),
        entity_kind: target
            .entity_kind
            .clone()
            .or_else(|| entity_kind_from_target(target)),
        style_key,
        lane,
        structural_role,
        document_unit_kind,
        state_context_kind,
        source_id: target.source_id.clone(),
        registry_entity_id: target.entity_id.clone(),
        note_id: target.note_id.clone(),
        chunk_id: target.chunk_id.clone(),
        evidence_ids: target.evidence_ids.clone(),
        parent_ids: target.parent_ids.clone(),
    }
}

fn object_id_for_target(
    target: &GraphEmbeddingTarget,
    source_to_object: &HashMap<CompactString, CompactString>,
) -> CompactString {
    if let Some(object_id) = source_to_object.get(&target.source_id) {
        return object_id.clone();
    }
    if target.kind == "entity" {
        if let Some(entity_id) = &target.entity_id {
            return entity_object_id(entity_id);
        }
    }
    if target.kind == "note" {
        return note_object_id(&target.source_id);
    }
    if target.kind == "chunk" {
        return chunk_object_id(&target.source_id);
    }
    format_compact!("atlas:target-source:{}", target.source_id)
}

fn family_for_target(target: &GraphEmbeddingTarget) -> GraphFamily {
    if target.source_id.starts_with("review:") {
        return GraphFamily::Review;
    }
    if target.source_id.starts_with("discourse-") {
        return GraphFamily::Discourse;
    }
    if target.id.contains("hypergraph-role") {
        return GraphFamily::Hypergraph;
    }
    match target.kind.as_str() {
        "note" | "chunk" | "structureRoot" | "documentUnit" => GraphFamily::Structure,
        "entity" => GraphFamily::Registry,
        "anchor" | "evidenceSpan" => GraphFamily::Evidence,
        "graphFact" | "event" => GraphFamily::Fact,
        "temporalFact" => GraphFamily::Temporal,
        "causalFact" => GraphFamily::Causal,
        "memoryState" => GraphFamily::Memory,
        kind if kind.contains("hypergraph") || kind.contains("document") => GraphFamily::Hypergraph,
        _ => GraphFamily::Unknown,
    }
}

fn status_from_text(status: &str) -> AtlasObjectStatus {
    match status {
        "accepted" => AtlasObjectStatus::Accepted,
        "proposed" => AtlasObjectStatus::Proposed,
        "review" => AtlasObjectStatus::Review,
        "rejected" => AtlasObjectStatus::Rejected,
        "deferred" => AtlasObjectStatus::Deferred,
        "ledger_only" | "ledgerOnly" => AtlasObjectStatus::LedgerOnly,
        "compiled_to_graph" | "compiledToGraph" => AtlasObjectStatus::CompiledToGraph,
        "muted" => AtlasObjectStatus::Muted,
        "promoted_to_anchor" | "promotedToAnchor" => AtlasObjectStatus::PromotedToAnchor,
        _ => AtlasObjectStatus::Unknown,
    }
}

fn vector_status_for(snapshot: &GraphRebuildSnapshot) -> AtlasVectorStatus {
    if snapshot.embedding_vectors.is_empty() {
        AtlasVectorStatus::Missing
    } else {
        AtlasVectorStatus::ModelVector
    }
}

fn coordinate_source_for(status: AtlasVectorStatus) -> CompactString {
    match status {
        AtlasVectorStatus::Missing => "none".into(),
        AtlasVectorStatus::ModelVector => "model-vector".into(),
        AtlasVectorStatus::External => "external-vector".into(),
    }
}

fn packet_counters(
    objects: &[AtlasObject],
    manifold_targets: &[ManifoldTarget],
    snapshot: &GraphRebuildSnapshot,
) -> AtlasPacketCounters {
    let mut family_counts = HashMap::<GraphFamily, usize>::new();
    for object in objects {
        *family_counts.entry(object.family).or_insert(0) += 1;
    }
    let mut families = family_counts
        .into_iter()
        .map(|(family, count)| AtlasFamilyCount { family, count })
        .collect::<Vec<_>>();
    families.sort_by_key(|row| family_sort_key(row.family));
    AtlasPacketCounters {
        objects: objects.len(),
        manifold_targets: manifold_targets.len(),
        registry_entities: snapshot.nodes.len(),
        evidence_anchors: snapshot.entity_anchors.len(),
        model_vectors: snapshot.embedding_vectors.len(),
        families,
    }
}

fn push_object(
    objects: &mut Vec<AtlasObject>,
    seen: &mut HashSet<CompactString>,
    source_to_object: &mut HashMap<CompactString, CompactString>,
    object: AtlasObject,
) {
    if !seen.insert(object.id.clone()) {
        return;
    }
    for source_id in &object.source_ids {
        source_to_object
            .entry(source_id.clone())
            .or_insert_with(|| object.id.clone());
    }
    objects.push(object);
}

fn family_sort_key(family: GraphFamily) -> u8 {
    match family {
        GraphFamily::Registry => 0,
        GraphFamily::Entity => 1,
        GraphFamily::Structure => 2,
        GraphFamily::Fact => 3,
        GraphFamily::Discourse => 4,
        GraphFamily::Review => 5,
        GraphFamily::Evidence => 6,
        GraphFamily::Temporal => 7,
        GraphFamily::Causal => 8,
        GraphFamily::Memory => 9,
        GraphFamily::Hypergraph => 10,
        GraphFamily::Unknown => 255,
    }
}

#[cfg(test)]
mod tests;
