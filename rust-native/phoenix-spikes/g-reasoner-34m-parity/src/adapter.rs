use hashbrown::HashMap;

use crate::graph::{Edge, IncomingCsr};
use crate::{GfmError, Result};

#[derive(Clone, Debug)]
pub struct AssertedNode {
    pub stable_id: String,
    pub node_type: String,
}

#[derive(Clone, Debug)]
pub struct AssertedRelation {
    pub source_stable_id: String,
    pub relation: String,
    pub target_stable_id: String,
}

/// Read-only dense view derived from accepted graph truth. All asserted node
/// types share one dense index, matching G-reasoner's direct typed-node scorer.
#[derive(Debug)]
pub struct InferenceView {
    pub graph: IncomingCsr,
    pub node_ids: Box<[String]>,
    pub node_types: Box<[String]>,
    pub relation_names: Box<[String]>,
    nodes_by_type: HashMap<String, Box<[u32]>>,
}

impl InferenceView {
    pub fn from_asserted_snapshot(
        mut nodes: Vec<AssertedNode>,
        asserted_relations: Vec<AssertedRelation>,
        candidate_relation_count: usize,
    ) -> Result<Self> {
        if candidate_relation_count != 0 {
            return Err(GfmError::InvalidGraph(
                "candidate relations cannot enter the asserted inference adapter".into(),
            ));
        }
        nodes.sort_unstable_by(|left, right| left.stable_id.cmp(&right.stable_id));
        if nodes
            .windows(2)
            .any(|pair| pair[0].stable_id == pair[1].stable_id)
        {
            return Err(GfmError::InvalidGraph("duplicate stable node ID".into()));
        }
        if nodes
            .iter()
            .any(|node| node.stable_id.is_empty() || node.node_type.is_empty())
        {
            return Err(GfmError::InvalidGraph(
                "node stable ID and type must be nonempty".into(),
            ));
        }

        let node_index: HashMap<&str, u32> = nodes
            .iter()
            .enumerate()
            .map(|(index, node)| (node.stable_id.as_str(), index as u32))
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

        let direct_relation_count = relation_names.len() as u32;
        let mut edges = Vec::with_capacity(asserted_relations.len() * 2);
        for relation in asserted_relations {
            let src = node_index
                .get(relation.source_stable_id.as_str())
                .copied()
                .ok_or_else(|| unknown_node("source", &relation.source_stable_id))?;
            let dst = node_index
                .get(relation.target_stable_id.as_str())
                .copied()
                .ok_or_else(|| unknown_node("target", &relation.target_stable_id))?;
            let relation_id = relation_index[relation.relation.as_str()];
            edges.push(Edge {
                src,
                relation: relation_id,
                dst,
            });
            edges.push(Edge {
                src: dst,
                relation: relation_id + direct_relation_count,
                dst: src,
            });
        }
        drop(relation_index);
        let inverse_relation_names = relation_names
            .iter()
            .map(|relation| format!("inverse_{relation}"))
            .collect::<Vec<_>>();
        relation_names.extend(inverse_relation_names);

        let mut type_vectors: HashMap<String, Vec<u32>> = HashMap::new();
        for (index, node) in nodes.iter().enumerate() {
            type_vectors
                .entry(node.node_type.clone())
                .or_default()
                .push(index as u32);
        }
        let nodes_by_type = type_vectors
            .into_iter()
            .map(|(node_type, indices)| (node_type, indices.into_boxed_slice()))
            .collect();
        drop(node_index);
        let node_ids = nodes
            .iter()
            .map(|node| node.stable_id.clone())
            .collect::<Vec<_>>()
            .into_boxed_slice();
        let node_types = nodes
            .into_iter()
            .map(|node| node.node_type)
            .collect::<Vec<_>>()
            .into_boxed_slice();

        Ok(Self {
            graph: IncomingCsr::from_edges(node_ids.len(), relation_names.len(), edges)?,
            node_ids,
            node_types,
            relation_names: relation_names.into_boxed_slice(),
            nodes_by_type,
        })
    }

    pub fn nodes_for_type(&self, node_type: &str) -> &[u32] {
        self.nodes_by_type
            .get(node_type)
            .map_or(&[], |nodes| nodes.as_ref())
    }
}

fn unknown_node(endpoint: &str, stable_id: &str) -> GfmError {
    GfmError::InvalidGraph(format!("unknown {endpoint} node {stable_id}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn candidates_fail_closed() {
        let error = InferenceView::from_asserted_snapshot(Vec::new(), Vec::new(), 1).unwrap_err();
        assert!(error.to_string().contains("candidate relations"));
    }

    #[test]
    fn indexes_all_asserted_node_types_without_mutation() {
        let view = InferenceView::from_asserted_snapshot(
            vec![
                AssertedNode {
                    stable_id: "entity:z".into(),
                    node_type: "entity".into(),
                },
                AssertedNode {
                    stable_id: "document:a".into(),
                    node_type: "document".into(),
                },
            ],
            vec![AssertedRelation {
                source_stable_id: "entity:z".into(),
                relation: "mentions".into(),
                target_stable_id: "document:a".into(),
            }],
            0,
        )
        .unwrap();
        assert_eq!(view.node_ids.as_ref(), ["document:a", "entity:z"]);
        assert_eq!(view.nodes_for_type("document"), [0]);
        assert_eq!(view.nodes_for_type("entity"), [1]);
        assert_eq!(view.graph.edge_count(), 2);
        assert_eq!(
            view.relation_names.as_ref(),
            ["mentions", "inverse_mentions"]
        );
    }
}
