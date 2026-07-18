use crate::{GfmError, Result};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Edge {
    pub src: u32,
    pub relation: u32,
    pub dst: u32,
}

/// Packed incoming CSR. Every destination owns a stable, contiguous edge row.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IncomingCsr {
    node_count: usize,
    relation_count: usize,
    dst_offsets: Box<[u64]>,
    src_nodes: Box<[u32]>,
    relation_ids: Box<[u32]>,
}

impl IncomingCsr {
    pub fn from_edges(
        node_count: usize,
        relation_count: usize,
        edges: impl IntoIterator<Item = Edge>,
    ) -> Result<Self> {
        if node_count > u32::MAX as usize {
            return Err(GfmError::InvalidGraph("node count exceeds u32".into()));
        }
        if relation_count > u32::MAX as usize {
            return Err(GfmError::InvalidGraph("relation count exceeds u32".into()));
        }

        let mut edges: Vec<Edge> = edges.into_iter().collect();
        for edge in &edges {
            if edge.src as usize >= node_count || edge.dst as usize >= node_count {
                return Err(GfmError::InvalidGraph(format!(
                    "edge endpoint out of bounds: {edge:?} for {node_count} nodes"
                )));
            }
            if edge.relation as usize >= relation_count {
                return Err(GfmError::InvalidGraph(format!(
                    "relation {} out of bounds for {relation_count} relations",
                    edge.relation
                )));
            }
        }
        edges.sort_unstable_by_key(|edge| (edge.dst, edge.relation, edge.src));

        let mut offsets = vec![0_u64; node_count + 1];
        for edge in &edges {
            offsets[edge.dst as usize + 1] += 1;
        }
        for index in 1..offsets.len() {
            offsets[index] += offsets[index - 1];
        }

        let mut src_nodes = Vec::with_capacity(edges.len());
        let mut relation_ids = Vec::with_capacity(edges.len());
        for edge in edges {
            src_nodes.push(edge.src);
            relation_ids.push(edge.relation);
        }
        Ok(Self {
            node_count,
            relation_count,
            dst_offsets: offsets.into_boxed_slice(),
            src_nodes: src_nodes.into_boxed_slice(),
            relation_ids: relation_ids.into_boxed_slice(),
        })
    }

    pub fn node_count(&self) -> usize {
        self.node_count
    }

    pub fn relation_count(&self) -> usize {
        self.relation_count
    }

    pub fn edge_count(&self) -> usize {
        self.src_nodes.len()
    }

    pub fn dst_offsets(&self) -> &[u64] {
        &self.dst_offsets
    }

    pub fn src_nodes(&self) -> &[u32] {
        &self.src_nodes
    }

    pub fn relation_ids(&self) -> &[u32] {
        &self.relation_ids
    }

    pub fn incoming_range(&self, dst: usize) -> std::ops::Range<usize> {
        self.dst_offsets[dst] as usize..self.dst_offsets[dst + 1] as usize
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_relation_then_source_sorted_incoming_rows() {
        let graph = IncomingCsr::from_edges(
            4,
            3,
            [
                Edge {
                    src: 3,
                    relation: 1,
                    dst: 2,
                },
                Edge {
                    src: 1,
                    relation: 0,
                    dst: 2,
                },
                Edge {
                    src: 0,
                    relation: 0,
                    dst: 2,
                },
            ],
        )
        .unwrap();
        assert_eq!(graph.dst_offsets(), &[0, 0, 0, 3, 3]);
        assert_eq!(graph.src_nodes(), &[0, 1, 3]);
        assert_eq!(graph.relation_ids(), &[0, 0, 1]);
    }
}
