use hashbrown::{HashMap, HashSet};

use crate::graph::{Edge, IncomingCsr};
use crate::{GfmError, Result};

#[derive(Clone, Debug)]
pub struct AssertedEntity {
    pub stable_id: String,
}

#[derive(Clone, Debug)]
pub struct AssertedRelation {
    pub source_stable_id: String,
    pub relation: String,
    pub target_stable_id: String,
}

#[derive(Clone, Debug)]
pub struct AssertedMembership {
    pub entity_stable_id: String,
    pub document_stable_id: String,
}

/// Read-only dense view derived from accepted graph truth.
///
/// Candidate relations are an explicit separate input and are rejected if they
/// leak into construction. Document membership is reversed only in this view;
/// no Phoenix edge or persistent ID is changed.
#[derive(Debug)]
pub struct InferenceView {
    pub graph: IncomingCsr,
    pub entity_ids: Box<[String]>,
    pub relation_names: Box<[String]>,
    pub document_ids: Box<[String]>,
    pub entity_documents: Box<[Box<[u32]>]>,
}

impl InferenceView {
    pub fn from_asserted_snapshot(
        entities: Vec<AssertedEntity>,
        asserted_relations: Vec<AssertedRelation>,
        asserted_memberships: Vec<AssertedMembership>,
        candidate_relation_count: usize,
    ) -> Result<Self> {
        if candidate_relation_count != 0 {
            return Err(GfmError::InvalidGraph(
                "candidate relations cannot enter the asserted inference adapter".into(),
            ));
        }

        let mut entity_ids: Vec<String> = entities.into_iter().map(|e| e.stable_id).collect();
        entity_ids.sort_unstable();
        if entity_ids.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(GfmError::InvalidGraph("duplicate stable entity ID".into()));
        }
        let entity_index: HashMap<&str, u32> = entity_ids
            .iter()
            .enumerate()
            .map(|(index, id)| (id.as_str(), index as u32))
            .collect();

        let mut relation_names: Vec<String> = asserted_relations
            .iter()
            .map(|edge| edge.relation.clone())
            .collect();
        relation_names.sort_unstable();
        relation_names.dedup();
        let relation_index: HashMap<&str, u32> = relation_names
            .iter()
            .enumerate()
            .map(|(index, relation)| (relation.as_str(), index as u32))
            .collect();

        let mut edges = Vec::with_capacity(asserted_relations.len());
        for relation in asserted_relations {
            let src = *entity_index
                .get(relation.source_stable_id.as_str())
                .ok_or_else(|| {
                    GfmError::InvalidGraph(format!(
                        "unknown source entity {}",
                        relation.source_stable_id
                    ))
                })?;
            let dst = *entity_index
                .get(relation.target_stable_id.as_str())
                .ok_or_else(|| {
                    GfmError::InvalidGraph(format!(
                        "unknown target entity {}",
                        relation.target_stable_id
                    ))
                })?;
            let relation_id = relation_index[relation.relation.as_str()];
            edges.push(Edge {
                src,
                relation: relation_id,
                dst,
            });
        }

        let mut document_set = HashSet::new();
        for membership in &asserted_memberships {
            document_set.insert(membership.document_stable_id.clone());
        }
        let mut document_ids: Vec<String> = document_set.into_iter().collect();
        document_ids.sort_unstable();
        let document_index: HashMap<&str, u32> = document_ids
            .iter()
            .enumerate()
            .map(|(index, id)| (id.as_str(), index as u32))
            .collect();
        let mut entity_documents = vec![Vec::<u32>::new(); entity_ids.len()];
        for membership in asserted_memberships {
            let entity = *entity_index
                .get(membership.entity_stable_id.as_str())
                .ok_or_else(|| {
                    GfmError::InvalidGraph(format!(
                        "unknown membership entity {}",
                        membership.entity_stable_id
                    ))
                })? as usize;
            entity_documents[entity].push(document_index[membership.document_stable_id.as_str()]);
        }
        for documents in &mut entity_documents {
            documents.sort_unstable();
            documents.dedup();
        }
        drop(document_index);
        drop(relation_index);
        drop(entity_index);

        Ok(Self {
            graph: IncomingCsr::from_edges(entity_ids.len(), relation_names.len(), edges)?,
            entity_ids: entity_ids.into_boxed_slice(),
            relation_names: relation_names.into_boxed_slice(),
            document_ids: document_ids.into_boxed_slice(),
            entity_documents: entity_documents
                .into_iter()
                .map(Vec::into_boxed_slice)
                .collect::<Vec<_>>()
                .into_boxed_slice(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn candidates_fail_closed() {
        let error = InferenceView::from_asserted_snapshot(Vec::new(), Vec::new(), Vec::new(), 1)
            .unwrap_err();
        assert!(error.to_string().contains("candidate relations"));
    }
}
