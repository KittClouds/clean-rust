use g_reasoner_34m_parity::adapter as reasoner;
use gfm_rag_8m_parity::adapter as gfm;
use hashbrown::{HashMap, HashSet};
use phoenix_revision_impact::{InferenceEdgeKind, InferenceGraph};
use serde::{Deserialize, Serialize};

use crate::{InferenceArtifactError, Result};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MembershipRecord {
    pub container_id: String,
    pub member_id: String,
    pub relation: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProjectionAuthorityReceipt {
    pub admitted_relations: u64,
    pub admitted_memberships: u64,
    pub excluded_candidate_edges: u64,
    pub excluded_rejected_edges: u64,
    pub admitted_candidate_edges: u64,
}

pub struct GfmProjection {
    pub view: gfm::InferenceView,
    pub memberships: Vec<MembershipRecord>,
    pub snapshot_digest: String,
    pub authority: ProjectionAuthorityReceipt,
}

pub struct ReasonerProjection {
    pub view: reasoner::InferenceView,
    pub embedding_texts: Box<[String]>,
    pub memberships: Vec<MembershipRecord>,
    pub snapshot_digest: String,
    pub authority: ProjectionAuthorityReceipt,
}

pub fn project_gfm(graph: &InferenceGraph) -> Result<GfmProjection> {
    let entity_ids = node_ids_for_type(graph, "entity");
    if entity_ids.is_empty() {
        return Err(InferenceArtifactError::InvalidProjection(
            "GFM-RAG requires at least one authoritative entity".into(),
        ));
    }
    let entity_set = entity_ids
        .iter()
        .map(String::as_str)
        .collect::<HashSet<_>>();
    let mut relations = Vec::new();
    let mut memberships = Vec::new();
    let mut gfm_memberships = Vec::new();
    visit_edges(graph, |source, target, relation, kind| match kind {
        InferenceEdgeKind::Relation
            if entity_set.contains(source) && entity_set.contains(target) =>
        {
            relations.push(gfm::AssertedRelation {
                source_stable_id: source.into(),
                relation: relation.into(),
                target_stable_id: target.into(),
            });
        }
        InferenceEdgeKind::Membership => {
            memberships.push(MembershipRecord {
                container_id: source.into(),
                member_id: target.into(),
                relation: relation.into(),
            });
            let pair = if is_node_type(graph, source, "document") && entity_set.contains(target) {
                Some((target, source))
            } else if is_node_type(graph, target, "document") && entity_set.contains(source) {
                Some((source, target))
            } else {
                None
            };
            if let Some((entity, document)) = pair {
                gfm_memberships.push(gfm::AssertedMembership {
                    entity_stable_id: entity.into(),
                    document_stable_id: document.into(),
                });
            }
        }
        InferenceEdgeKind::Relation => {}
    });
    if relations.is_empty() {
        return Err(InferenceArtifactError::InvalidProjection(
            "GFM-RAG requires an asserted entity relation".into(),
        ));
    }
    if gfm_memberships.is_empty() {
        return Err(InferenceArtifactError::InvalidProjection(
            "GFM-RAG requires an asserted entity-document membership".into(),
        ));
    }
    drop(entity_set);
    let entities = entity_ids
        .into_iter()
        .map(|stable_id| gfm::AssertedEntity { stable_id })
        .collect();
    let view = gfm::InferenceView::from_asserted_snapshot(entities, relations, gfm_memberships, 0)?;
    Ok(GfmProjection {
        view,
        memberships,
        snapshot_digest: snapshot_digest(graph),
        authority: authority_receipt(graph),
    })
}

pub fn project_reasoner(graph: &InferenceGraph) -> Result<ReasonerProjection> {
    if graph.nodes().is_empty() {
        return Err(InferenceArtifactError::InvalidProjection(
            "G-reasoner requires authoritative nodes".into(),
        ));
    }
    let nodes = graph
        .nodes()
        .iter()
        .map(|node| reasoner::AssertedNode {
            stable_id: node.node_id.to_string(),
            node_type: graph.node_types()[node.node_type_id as usize].to_string(),
        })
        .collect();
    let mut relations = Vec::with_capacity(graph.source_ids().len());
    let mut memberships = Vec::new();
    visit_edges(graph, |source, target, relation, kind| {
        relations.push(reasoner::AssertedRelation {
            source_stable_id: source.into(),
            relation: relation.into(),
            target_stable_id: target.into(),
        });
        if kind == InferenceEdgeKind::Membership {
            memberships.push(MembershipRecord {
                container_id: source.into(),
                member_id: target.into(),
                relation: relation.into(),
            });
        }
    });
    if relations.is_empty() {
        return Err(InferenceArtifactError::InvalidProjection(
            "G-reasoner requires an asserted relation or membership".into(),
        ));
    }
    let view = reasoner::InferenceView::from_asserted_snapshot(nodes, relations, 0)?;
    let texts_by_id = graph
        .nodes()
        .iter()
        .map(|node| (node.node_id.as_str(), node.embedding_text.as_str()))
        .collect::<HashMap<_, _>>();
    let embedding_texts = view
        .node_ids
        .iter()
        .map(|id| {
            texts_by_id.get(id.as_str()).map_or_else(
                || {
                    Err(InferenceArtifactError::InvalidProjection(format!(
                        "missing embedding text for {id}"
                    )))
                },
                |text| Ok((*text).to_owned()),
            )
        })
        .collect::<Result<Vec<_>>>()?
        .into_boxed_slice();
    Ok(ReasonerProjection {
        view,
        embedding_texts,
        memberships,
        snapshot_digest: snapshot_digest(graph),
        authority: authority_receipt(graph),
    })
}

pub fn snapshot_digest(graph: &InferenceGraph) -> String {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix.authoritative-inference-graph.v1\0");
    hasher.update(&graph.generation().0.to_le_bytes());
    for kind in graph.node_types() {
        update_text(&mut hasher, kind);
    }
    for node in graph.nodes() {
        update_text(&mut hasher, &node.node_id);
        hasher.update(&node.node_type_id.to_le_bytes());
        update_text(&mut hasher, &node.embedding_text);
    }
    for relation in graph.relation_types() {
        update_text(&mut hasher, relation);
    }
    for value in graph.incoming_offsets() {
        hasher.update(&value.to_le_bytes());
    }
    for value in graph.source_ids() {
        hasher.update(&value.to_le_bytes());
    }
    for value in graph.relation_type_ids() {
        hasher.update(&value.to_le_bytes());
    }
    for metadata in graph.edge_metadata() {
        update_text(&mut hasher, &metadata.edge_id);
        hasher.update(&[match metadata.kind {
            InferenceEdgeKind::Relation => 0,
            InferenceEdgeKind::Membership => 1,
        }]);
        hasher.update(&metadata.confidence_millis.to_le_bytes());
        for evidence in &metadata.evidence_ids {
            update_text(&mut hasher, evidence);
        }
    }
    let receipt = graph.receipt();
    for count in [
        receipt.input_relations,
        receipt.input_memberships,
        receipt.admitted_relations,
        receipt.admitted_memberships,
        receipt.excluded_candidate_edges,
        receipt.excluded_rejected_edges,
    ] {
        hasher.update(&(count as u64).to_le_bytes());
    }
    hasher.finalize().to_hex().to_string()
}

fn visit_edges(graph: &InferenceGraph, mut visit: impl FnMut(&str, &str, &str, InferenceEdgeKind)) {
    for (target, window) in graph.incoming_offsets().windows(2).enumerate() {
        for edge in window[0] as usize..window[1] as usize {
            let source = graph.source_ids()[edge] as usize;
            let relation = graph.relation_type_ids()[edge] as usize;
            visit(
                &graph.nodes()[source].node_id,
                &graph.nodes()[target].node_id,
                &graph.relation_types()[relation],
                graph.edge_metadata()[edge].kind,
            );
        }
    }
}

fn node_ids_for_type(graph: &InferenceGraph, node_type: &str) -> Vec<String> {
    graph
        .nodes()
        .iter()
        .filter(|node| graph.node_types()[node.node_type_id as usize] == node_type)
        .map(|node| node.node_id.to_string())
        .collect()
}

fn is_node_type(graph: &InferenceGraph, node_id: &str, expected: &str) -> bool {
    graph.node_index(node_id).is_some_and(|index| {
        let node = &graph.nodes()[index as usize];
        graph.node_types()[node.node_type_id as usize] == expected
    })
}

fn authority_receipt(graph: &InferenceGraph) -> ProjectionAuthorityReceipt {
    let receipt = graph.receipt();
    ProjectionAuthorityReceipt {
        admitted_relations: receipt.admitted_relations as u64,
        admitted_memberships: receipt.admitted_memberships as u64,
        excluded_candidate_edges: receipt.excluded_candidate_edges as u64,
        excluded_rejected_edges: receipt.excluded_rejected_edges as u64,
        admitted_candidate_edges: 0,
    }
}

fn update_text(hasher: &mut blake3::Hasher, value: &str) {
    hasher.update(&(value.len() as u64).to_le_bytes());
    hasher.update(value.as_bytes());
}
