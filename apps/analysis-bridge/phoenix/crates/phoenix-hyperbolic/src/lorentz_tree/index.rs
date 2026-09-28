use roaring::RoaringBitmap;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

use super::error::{LorentzResult, LorentzTreeError};
use super::forest::LorentzForest;
use super::model::{
    LorentzNode, LorentzScoreConfig, LorentzTree, LorentzTreeKind, LorentzTreeMembership,
    LorentzTreeQuery,
};
use super::score::{rank_lorentz_candidates, LorentzCandidateRef, LorentzCandidateScore};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LorentzMembershipRow {
    pub tree_ord: u32,
    pub node_ord: u32,
    pub parent_node_ord: u32,
    pub level: u32,
}

impl LorentzMembershipRow {
    pub const NO_PARENT: u32 = u32::MAX;
}

#[derive(Clone, Debug, PartialEq)]
pub struct LorentzForestIndex {
    pub nodes: Vec<LorentzNode>,
    pub trees: Vec<LorentzTree>,
    pub memberships: Vec<LorentzTreeMembership>,
    pub rows: Vec<LorentzMembershipRow>,
    pub child_offsets: Vec<u32>,
    pub child_memberships: Vec<u32>,
    pub(crate) node_ord_by_id: BTreeMap<String, u32>,
    pub(crate) tree_ord_by_id: BTreeMap<String, u32>,
    pub(crate) membership_ord_by_key: BTreeMap<(u32, u32), u32>,
    pub(crate) all_members: RoaringBitmap,
    pub(crate) tree_members: BTreeMap<u32, RoaringBitmap>,
    pub(crate) kind_trees: BTreeMap<LorentzTreeKind, RoaringBitmap>,
    pub(crate) level_members: BTreeMap<u32, RoaringBitmap>,
    pub(crate) node_members: BTreeMap<u32, RoaringBitmap>,
}

impl LorentzForestIndex {
    pub fn from_forest(forest: &LorentzForest) -> LorentzResult<Self> {
        let nodes = forest.nodes.values().cloned().collect::<Vec<_>>();
        let trees = forest.trees.values().cloned().collect::<Vec<_>>();
        let mut node_ord_by_id = BTreeMap::new();
        let mut tree_ord_by_id = BTreeMap::new();
        for (ord, node) in nodes.iter().enumerate() {
            node.point.validate()?;
            node_ord_by_id.insert(node.node_id.clone(), ord_u32(ord, "node")?);
        }
        for (ord, tree) in trees.iter().enumerate() {
            tree_ord_by_id.insert(tree.tree_id.clone(), ord_u32(ord, "tree")?);
        }

        let memberships = forest
            .memberships
            .values()
            .cloned()
            .collect::<Vec<LorentzTreeMembership>>();
        Self::from_parts(nodes, trees, memberships)
    }

    pub(crate) fn from_parts(
        nodes: Vec<LorentzNode>,
        trees: Vec<LorentzTree>,
        memberships: Vec<LorentzTreeMembership>,
    ) -> LorentzResult<Self> {
        let mut node_ord_by_id = BTreeMap::new();
        let mut tree_ord_by_id = BTreeMap::new();
        for (ord, node) in nodes.iter().enumerate() {
            node.point.validate()?;
            node_ord_by_id.insert(node.node_id.clone(), ord_u32(ord, "node")?);
        }
        for (ord, tree) in trees.iter().enumerate() {
            tree_ord_by_id.insert(tree.tree_id.clone(), ord_u32(ord, "tree")?);
        }

        let mut memberships = memberships;
        memberships.sort_by(|left, right| {
            left.tree_id
                .cmp(&right.tree_id)
                .then_with(|| left.node_id.cmp(&right.node_id))
        });
        let mut rows = Vec::with_capacity(memberships.len());
        let mut membership_ord_by_key = BTreeMap::new();
        let mut all_members = RoaringBitmap::new();
        let mut tree_members = BTreeMap::<u32, RoaringBitmap>::new();
        let mut kind_trees = BTreeMap::<LorentzTreeKind, RoaringBitmap>::new();
        let mut level_members = BTreeMap::<u32, RoaringBitmap>::new();
        let mut node_members = BTreeMap::<u32, RoaringBitmap>::new();

        for (ord, membership) in memberships.iter().enumerate() {
            let ord = ord_u32(ord, "membership")?;
            let tree_ord = *tree_ord_by_id
                .get(&membership.tree_id)
                .ok_or_else(|| LorentzTreeError::MissingTree(membership.tree_id.clone()))?;
            let node_ord = *node_ord_by_id
                .get(&membership.node_id)
                .ok_or_else(|| LorentzTreeError::MissingNode(membership.node_id.clone()))?;
            let parent_node_ord = match &membership.parent_node_id {
                Some(parent_id) => *node_ord_by_id
                    .get(parent_id)
                    .ok_or_else(|| LorentzTreeError::MissingNode(parent_id.clone()))?,
                None => LorentzMembershipRow::NO_PARENT,
            };
            if membership_ord_by_key
                .insert((tree_ord, node_ord), ord)
                .is_some()
            {
                return Err(LorentzTreeError::DuplicateMembership {
                    tree_id: membership.tree_id.clone(),
                    node_id: membership.node_id.clone(),
                });
            }
            rows.push(LorentzMembershipRow {
                tree_ord,
                node_ord,
                parent_node_ord,
                level: membership.level,
            });
            all_members.insert(ord);
            tree_members.entry(tree_ord).or_default().insert(ord);
            kind_trees
                .entry(trees[tree_ord as usize].tree_kind)
                .or_default()
                .insert(tree_ord);
            level_members
                .entry(membership.level)
                .or_default()
                .insert(ord);
            node_members.entry(node_ord).or_default().insert(ord);
        }

        let (child_offsets, child_memberships) = build_child_ranges(&rows, &membership_ord_by_key)?;
        Ok(Self {
            nodes,
            trees,
            memberships,
            rows,
            child_offsets,
            child_memberships,
            node_ord_by_id,
            tree_ord_by_id,
            membership_ord_by_key,
            all_members,
            tree_members,
            kind_trees,
            level_members,
            node_members,
        })
    }

    pub fn candidate_pool(&self, query: &LorentzTreeQuery) -> RoaringBitmap {
        let mut pool = self.all_members.clone();
        if !query.tree_ids.is_empty() {
            let mut by_tree = RoaringBitmap::new();
            for tree_id in &query.tree_ids {
                if let Some(tree_ord) = self.tree_ord_by_id.get(tree_id) {
                    if let Some(members) = self.tree_members.get(tree_ord) {
                        by_tree |= members;
                    }
                }
            }
            pool &= by_tree;
        }
        if !query.tree_kinds.is_empty() {
            let mut by_kind = RoaringBitmap::new();
            for tree in &self.trees {
                if query
                    .tree_kinds
                    .iter()
                    .any(|kind| kind.is_compatible_with(tree.tree_kind))
                {
                    if let Some(tree_ord) = self.tree_ord_by_id.get(&tree.tree_id) {
                        if let Some(members) = self.tree_members.get(tree_ord) {
                            by_kind |= members;
                        }
                    }
                }
            }
            pool &= by_kind;
        }
        pool
    }

    pub fn rank(
        &self,
        query: &LorentzTreeQuery,
        config: LorentzScoreConfig,
    ) -> LorentzResult<Vec<LorentzCandidateScore<String>>> {
        let refs = self.candidate_refs_from_bitmap(&self.candidate_pool(query));
        rank_lorentz_candidates(query, refs, config)
    }

    pub fn children_of(
        &self,
        tree_id: &str,
        parent_node_id: &str,
    ) -> LorentzResult<Vec<&LorentzNode>> {
        let membership_ord = self.membership_ord(tree_id, parent_node_id)?;
        let start = self.child_offsets[membership_ord as usize] as usize;
        let end = self.child_offsets[membership_ord as usize + 1] as usize;
        self.child_memberships[start..end]
            .iter()
            .map(|child_membership_ord| {
                let row = self.row(*child_membership_ord)?;
                self.nodes
                    .get(row.node_ord as usize)
                    .ok_or_else(|| LorentzTreeError::IndexInvariant("child node ord".to_owned()))
            })
            .collect()
    }

    pub fn members_at_level(&self, level: u32) -> RoaringBitmap {
        self.level_members.get(&level).cloned().unwrap_or_default()
    }

    pub fn candidate_ids(&self, bitmap: &RoaringBitmap) -> Vec<String> {
        bitmap
            .iter()
            .filter_map(|membership_ord| self.candidate_id(membership_ord).ok())
            .collect()
    }

    pub(crate) fn candidate_refs_from_bitmap(
        &self,
        bitmap: &RoaringBitmap,
    ) -> Vec<LorentzCandidateRef<'_, String>> {
        bitmap
            .iter()
            .filter_map(|membership_ord| self.candidate_ref(membership_ord).ok())
            .collect()
    }

    pub(crate) fn candidate_ref(
        &self,
        membership_ord: u32,
    ) -> LorentzResult<LorentzCandidateRef<'_, String>> {
        let row = self.row(membership_ord)?;
        let node = self.node(row.node_ord)?;
        let tree = self.tree(row.tree_ord)?;
        let membership = self.membership(membership_ord)?;
        let has_cross_tree_support = self
            .node_members
            .get(&row.node_ord)
            .map(|members| members.len() > 1)
            .unwrap_or(false);
        Ok(LorentzCandidateRef {
            candidate_id: format!("{}:{}", tree.tree_id, node.node_id),
            node,
            tree: Some(tree),
            membership: Some(membership),
            has_cross_tree_support,
        })
    }

    fn candidate_id(&self, membership_ord: u32) -> LorentzResult<String> {
        let row = self.row(membership_ord)?;
        Ok(format!(
            "{}:{}",
            self.tree(row.tree_ord)?.tree_id,
            self.node(row.node_ord)?.node_id
        ))
    }

    fn membership_ord(&self, tree_id: &str, node_id: &str) -> LorentzResult<u32> {
        let tree_ord = self
            .tree_ord_by_id
            .get(tree_id)
            .ok_or_else(|| LorentzTreeError::MissingTree(tree_id.to_owned()))?;
        let node_ord = self
            .node_ord_by_id
            .get(node_id)
            .ok_or_else(|| LorentzTreeError::MissingNode(node_id.to_owned()))?;
        self.membership_ord_by_key
            .get(&(*tree_ord, *node_ord))
            .copied()
            .ok_or_else(|| LorentzTreeError::MissingMembership {
                tree_id: tree_id.to_owned(),
                node_id: node_id.to_owned(),
            })
    }

    fn row(&self, ord: u32) -> LorentzResult<&LorentzMembershipRow> {
        self.rows
            .get(ord as usize)
            .ok_or_else(|| LorentzTreeError::IndexInvariant("membership ord".to_owned()))
    }

    fn node(&self, ord: u32) -> LorentzResult<&LorentzNode> {
        self.nodes
            .get(ord as usize)
            .ok_or_else(|| LorentzTreeError::IndexInvariant("node ord".to_owned()))
    }

    fn tree(&self, ord: u32) -> LorentzResult<&LorentzTree> {
        self.trees
            .get(ord as usize)
            .ok_or_else(|| LorentzTreeError::IndexInvariant("tree ord".to_owned()))
    }

    fn membership(&self, ord: u32) -> LorentzResult<&LorentzTreeMembership> {
        self.memberships
            .get(ord as usize)
            .ok_or_else(|| LorentzTreeError::IndexInvariant("membership ord".to_owned()))
    }
}

fn build_child_ranges(
    rows: &[LorentzMembershipRow],
    membership_ord_by_key: &BTreeMap<(u32, u32), u32>,
) -> LorentzResult<(Vec<u32>, Vec<u32>)> {
    let mut temp = BTreeMap::<u32, Vec<u32>>::new();
    for (child_ord, row) in rows.iter().enumerate() {
        if row.parent_node_ord == LorentzMembershipRow::NO_PARENT {
            continue;
        }
        let parent_ord = membership_ord_by_key
            .get(&(row.tree_ord, row.parent_node_ord))
            .copied()
            .ok_or_else(|| LorentzTreeError::InvalidParent {
                tree_id: row.tree_ord.to_string(),
                parent_node_id: row.parent_node_ord.to_string(),
            })?;
        temp.entry(parent_ord)
            .or_default()
            .push(ord_u32(child_ord, "child membership")?);
    }

    let mut offsets = Vec::with_capacity(rows.len() + 1);
    let mut flat = Vec::new();
    offsets.push(0);
    for parent_ord in 0..rows.len() {
        let mut children = temp.remove(&(parent_ord as u32)).unwrap_or_default();
        children.sort_by(|left, right| {
            let left_row = rows[*left as usize];
            let right_row = rows[*right as usize];
            left_row
                .node_ord
                .cmp(&right_row.node_ord)
                .then_with(|| left.cmp(right))
        });
        children.dedup();
        flat.extend(children);
        offsets.push(ord_u32(flat.len(), "child offset")?);
    }
    Ok((offsets, flat))
}

fn ord_u32(value: usize, label: &str) -> LorentzResult<u32> {
    u32::try_from(value)
        .map_err(|_| LorentzTreeError::IndexInvariant(format!("{label} count exceeds u32")))
}
