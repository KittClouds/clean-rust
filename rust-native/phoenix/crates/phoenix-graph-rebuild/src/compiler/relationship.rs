use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};

use super::ids::{
    anchor_evidence_id, atom_id, entity_atom_id, legacy_relation_key, relationship_edge_key,
    relationship_lane,
};
use super::projection::ProjectionProvenance;
use super::types::{
    EvidenceAnchor, EvidenceBundleKind, EvidenceKind, FactBundle, FactLane, FactRole, GraphAtom,
    GraphAtomKind, GraphCompilerOutput, ProjectedGraphEdge, RelationFact,
};
use crate::types::GraphRelationship;

pub(super) fn relationship_artifacts(
    output: &mut GraphCompilerOutput,
    evidence_seen: &mut HashSet<CompactString>,
    by_edge: &mut HashMap<CompactString, ProjectionProvenance>,
    relationships: &[GraphRelationship],
) {
    for relationship in relationships {
        let lane = relationship_lane(relationship);
        let id = format_compact!("fact:relationship:{}", relationship.id);
        let evidence =
            ensure_evidence_ids(output, evidence_seen, &relationship.evidence_anchor_ids);
        if lane == FactLane::CooccurrenceWeak {
            by_edge.insert(relationship_edge_key(relationship), provenance_bundle(&id));
            stage_bundle(output, relationship, id, lane, evidence);
            continue;
        }
        by_edge.insert(relationship_edge_key(relationship), provenance_fact(&id));
        promote_fact(output, relationship, id, lane, evidence);
    }
}

pub(super) fn legacy_relationship_keys(
    by_edge: &mut HashMap<CompactString, ProjectionProvenance>,
    relationships: &[GraphRelationship],
) {
    for relationship in relationships {
        let id = format_compact!("fact:relationship:{}", relationship.id);
        let provenance = if relationship_lane(relationship) == FactLane::CooccurrenceWeak {
            provenance_bundle(&id)
        } else {
            provenance_fact(&id)
        };
        by_edge.insert(legacy_relation_key(relationship), provenance);
    }
}

fn stage_bundle(
    output: &mut GraphCompilerOutput,
    relationship: &GraphRelationship,
    id: CompactString,
    lane: FactLane,
    evidence_ids: Vec<CompactString>,
) {
    output.bundles.push(FactBundle {
        id,
        lane,
        bundle_kind: relationship_bundle_kind(relationship, evidence_ids.len()),
        group_key: relationship_group_key(relationship),
        predicate: relationship.relation_type.clone(),
        source_record_id: relationship.id.clone(),
        status: relationship.status.clone(),
        evidence_ids,
        confidence: relationship.confidence,
        compression: None,
        commitment: None,
    });
}

fn relationship_bundle_kind(
    relationship: &GraphRelationship,
    evidence_count: usize,
) -> EvidenceBundleKind {
    let relation_type = relationship.relation_type.to_ascii_lowercase();
    if relation_type.contains("semantic") || relation_type.contains("similar") {
        EvidenceBundleKind::SemanticSimilarity
    } else if relation_type.contains("shadow") || relation_type.contains("identity") {
        EvidenceBundleKind::ShadowIdentity
    } else if evidence_count <= 1 {
        EvidenceBundleKind::Span
    } else {
        EvidenceBundleKind::Neighborhood
    }
}

fn relationship_group_key(relationship: &GraphRelationship) -> CompactString {
    let (left, right) = if relationship.source_entity_id <= relationship.target_entity_id {
        (
            &relationship.source_entity_id,
            &relationship.target_entity_id,
        )
    } else {
        (
            &relationship.target_entity_id,
            &relationship.source_entity_id,
        )
    };
    format_compact!("{}:{}:{}", relationship.relation_type, left.0, right.0)
}

fn promote_fact(
    output: &mut GraphCompilerOutput,
    relationship: &GraphRelationship,
    fact_id: CompactString,
    lane: FactLane,
    evidence_ids: Vec<CompactString>,
) {
    output.facts.push(RelationFact {
        id: fact_id.clone(),
        lane,
        predicate: relationship.relation_type.clone(),
        source_record_id: relationship.id.clone(),
        status: relationship.status.clone(),
        evidence_ids: evidence_ids.clone(),
        confidence: relationship.confidence,
        semantic_situation_id: None,
        semantic_frame: None,
        factuality: None,
        state_interval_ids: Vec::new(),
        event_ordering_ids: Vec::new(),
        temporal_conflict_ids: Vec::new(),
    });
    output.atoms.push(GraphAtom {
        id: atom_id("relationFact", &fact_id),
        kind: GraphAtomKind::RelationFact,
        source_id: fact_id.clone(),
        label: relationship.relation_type.clone(),
        note_id: None,
        chunk_id: None,
        entity_id: None,
        evidence_ids: evidence_ids.clone(),
    });
    role(
        output,
        &fact_id,
        "source",
        entity_atom_id(&relationship.source_entity_id),
        relationship.confidence,
    );
    role(
        output,
        &fact_id,
        "target",
        entity_atom_id(&relationship.target_entity_id),
        relationship.confidence,
    );
    for evidence_id in &evidence_ids {
        role(
            output,
            &fact_id,
            "evidence",
            evidence_id.clone(),
            relationship.confidence,
        );
    }
    projection(
        output,
        format_compact!("projection:fact-role:{}:source", relationship.id),
        fact_id.clone(),
        entity_atom_id(&relationship.source_entity_id),
        "role:source".into(),
        relationship.confidence,
    );
    projection(
        output,
        format_compact!("projection:fact-role:{}:target", relationship.id),
        fact_id.clone(),
        entity_atom_id(&relationship.target_entity_id),
        "role:target".into(),
        relationship.confidence,
    );
}

fn ensure_evidence_ids(
    output: &mut GraphCompilerOutput,
    evidence_seen: &mut HashSet<CompactString>,
    source_ids: &[CompactString],
) -> Vec<CompactString> {
    source_ids
        .iter()
        .map(|source_id| {
            let id = anchor_evidence_id(source_id);
            if evidence_seen.insert(id.clone()) {
                output.evidence_anchors.push(EvidenceAnchor {
                    id: id.clone(),
                    kind: EvidenceKind::SourceSpan,
                    note_id: None,
                    chunk_id: None,
                    source_range: None,
                    source_id: source_id.clone(),
                    confidence: 0.62,
                });
            }
            id
        })
        .collect()
}

fn role(
    output: &mut GraphCompilerOutput,
    fact_id: &CompactString,
    role_name: &str,
    atom_id: CompactString,
    confidence: f32,
) {
    output.roles.push(FactRole {
        fact_id: fact_id.clone(),
        role: role_name.into(),
        atom_id,
        confidence,
        semantic_role: None,
        slot_type: None,
        required: None,
        resolved: None,
    });
}

fn projection(
    output: &mut GraphCompilerOutput,
    id: CompactString,
    source_id: CompactString,
    target_id: CompactString,
    edge_type: CompactString,
    confidence: f32,
) {
    output.projected_edges.push(ProjectedGraphEdge {
        id,
        source_id: source_id.clone(),
        target_id,
        edge_type,
        projection_kind: "factRole".into(),
        source_fact_id: Some(source_id),
        source_bundle_id: None,
        confidence,
    });
}

fn provenance_fact(fact_id: &CompactString) -> ProjectionProvenance {
    ProjectionProvenance {
        fact_id: Some(fact_id.clone()),
        bundle_id: None,
    }
}

fn provenance_bundle(bundle_id: &CompactString) -> ProjectionProvenance {
    ProjectionProvenance {
        fact_id: None,
        bundle_id: Some(bundle_id.clone()),
    }
}
