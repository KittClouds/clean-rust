use crate::{GfmError, Result};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedRanking {
    pub node_indices: Vec<usize>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct StableRankedNode {
    pub stable_id: String,
    pub node_index: u32,
    pub logit: f32,
}

/// Production ranking receipt. The complete logit vector is retained for
/// downstream overlays and every ranked item carries its stable graph ID.
#[derive(Clone, Debug, PartialEq)]
pub struct StableTypedRanking {
    pub logits: Box<[f32]>,
    pub ranked_nodes: Vec<StableRankedNode>,
}

/// Selects logits only from the requested node type and returns dense graph
/// indices in deterministic score-descending, index-ascending order.
pub fn rank_typed_nodes(logits: &[f32], typed_nodes: &[u32], top_k: usize) -> Result<TypedRanking> {
    if typed_nodes
        .iter()
        .any(|&node| node as usize >= logits.len())
    {
        return Err(GfmError::InvalidGraph(
            "typed node index out of bounds".into(),
        ));
    }
    if typed_nodes
        .iter()
        .any(|&node| !logits[node as usize].is_finite())
    {
        return Err(GfmError::Shape("typed-node logits must be finite".into()));
    }
    let mut nodes: Vec<usize> = typed_nodes.iter().map(|&node| node as usize).collect();
    nodes.sort_unstable_by(|&left, &right| {
        logits[right]
            .total_cmp(&logits[left])
            .then_with(|| left.cmp(&right))
    });
    nodes.truncate(top_k.min(nodes.len()));
    Ok(TypedRanking {
        node_indices: nodes,
    })
}

pub fn rank_typed_nodes_stable(
    logits: &[f32],
    stable_node_ids: &[String],
    typed_nodes: &[u32],
    top_k: usize,
) -> Result<StableTypedRanking> {
    if logits.len() != stable_node_ids.len() {
        return Err(GfmError::Shape(
            "logits and stable node IDs disagree".into(),
        ));
    }
    let ranking = rank_typed_nodes(logits, typed_nodes, top_k)?;
    let ranked_nodes = ranking
        .node_indices
        .into_iter()
        .map(|node_index| StableRankedNode {
            stable_id: stable_node_ids[node_index].clone(),
            node_index: node_index as u32,
            logit: logits[node_index],
        })
        .collect();
    Ok(StableTypedRanking {
        logits: logits.to_vec().into_boxed_slice(),
        ranked_nodes,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn excludes_other_node_types() {
        let ranking = rank_typed_nodes(&[100.0, 1.0, 2.0, 50.0], &[1, 2], 2).unwrap();
        assert_eq!(ranking.node_indices, vec![2, 1]);
    }

    #[test]
    fn stable_ranking_preserves_logits_and_ids() {
        let ids = vec!["doc:a".into(), "event:b".into(), "doc:c".into()];
        let ranking = rank_typed_nodes_stable(&[0.25, 99.0, 0.75], &ids, &[0, 2], 2).unwrap();
        assert_eq!(&*ranking.logits, &[0.25, 99.0, 0.75]);
        assert_eq!(ranking.ranked_nodes[0].stable_id, "doc:c");
        assert_eq!(ranking.ranked_nodes[0].node_index, 2);
        assert_eq!(ranking.ranked_nodes[0].logit, 0.75);
    }
}
