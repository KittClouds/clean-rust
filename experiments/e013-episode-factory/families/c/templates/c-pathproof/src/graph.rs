#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct NodeId(pub u32);

#[derive(Clone, Debug)]
pub struct CompactGraph {
    offsets: Box<[u32]>,
    edges: Box<[NodeId]>,
}

impl CompactGraph {
    pub fn from_sorted_edges(node_count: usize, edges: &[(NodeId, NodeId)]) -> Option<Self> {
        if node_count > u32::MAX as usize || edges.len() > u32::MAX as usize {
            return None;
        }
        let mut offsets = vec![0_u32; node_count + 1];
        for &(from, to) in edges {
            if from.0 as usize >= node_count || to.0 as usize >= node_count {
                return None;
            }
            offsets[from.0 as usize + 1] = offsets[from.0 as usize + 1].checked_add(1)?;
        }
        for index in 1..offsets.len() {
            offsets[index] = offsets[index].checked_add(offsets[index - 1])?;
        }
        let mut packed = vec![NodeId(0); edges.len()];
        let mut cursor = offsets[..node_count].to_vec();
        for &(from, to) in edges {
            let slot = cursor[from.0 as usize] as usize;
            packed[slot] = to;
            cursor[from.0 as usize] += 1;
        }
        Some(Self { offsets: offsets.into_boxed_slice(), edges: packed.into_boxed_slice() })
    }

    pub fn neighbors(&self, node: NodeId) -> Option<&[NodeId]> {
        let index = node.0 as usize;
        let start = *self.offsets.get(index)? as usize;
        let end = *self.offsets.get(index + 1)? as usize;
        self.edges.get(start..end)
    }
}
