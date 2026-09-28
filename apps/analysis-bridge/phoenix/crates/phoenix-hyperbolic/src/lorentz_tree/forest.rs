use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

use super::error::{LorentzResult, LorentzTreeError};
use super::model::{LorentzNode, LorentzScoreConfig, LorentzTree, LorentzTreeMembership};
use super::score::{rank_lorentz_candidates, LorentzCandidateRef, LorentzCandidateScore};
use super::LorentzTreeQuery;

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LorentzForest {
    pub nodes: BTreeMap<String, LorentzNode>,
    pub trees: BTreeMap<String, LorentzTree>,
    pub memberships: BTreeMap<(String, String), LorentzTreeMembership>,
    #[serde(skip)]
    children: BTreeMap<(String, String), Vec<String>>,
    #[serde(skip)]
    node_tree_index: BTreeMap<String, BTreeSet<String>>,
}

impl LorentzForest {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn rebuild_indexes(&mut self) {
        self.children.clear();
        self.node_tree_index.clear();
        for ((tree_id, node_id), membership) in &self.memberships {
            self.node_tree_index
                .entry(node_id.clone())
                .or_default()
                .insert(tree_id.clone());
            if let Some(parent_node_id) = &membership.parent_node_id {
                self.children
                    .entry((tree_id.clone(), parent_node_id.clone()))
                    .or_default()
                    .push(node_id.clone());
            }
        }
        for child_ids in self.children.values_mut() {
            child_ids.sort();
            child_ids.dedup();
        }
    }

    pub fn add_tree(&mut self, tree: LorentzTree) -> LorentzResult<()> {
        if self.trees.contains_key(&tree.tree_id) {
            return Err(LorentzTreeError::DuplicateTree(tree.tree_id));
        }
        self.trees.insert(tree.tree_id.clone(), tree);
        Ok(())
    }

    pub fn add_node(&mut self, node: LorentzNode) -> LorentzResult<()> {
        node.point.validate()?;
        if self.nodes.contains_key(&node.node_id) {
            return Err(LorentzTreeError::DuplicateNode(node.node_id));
        }
        self.nodes.insert(node.node_id.clone(), node);
        Ok(())
    }

    pub fn attach_root(
        &mut self,
        tree_id: impl Into<String>,
        node_id: impl Into<String>,
    ) -> LorentzResult<()> {
        let tree_id = tree_id.into();
        let node_id = node_id.into();
        self.ensure_tree_exists(&tree_id)?;
        self.ensure_node_exists(&node_id)?;
        let key = (tree_id.clone(), node_id.clone());
        if self.memberships.contains_key(&key) {
            return Err(LorentzTreeError::DuplicateMembership { tree_id, node_id });
        }
        self.memberships.insert(
            key,
            LorentzTreeMembership::root(tree_id.clone(), node_id.clone()),
        );
        if let Some(tree) = self.trees.get_mut(&tree_id) {
            tree.root_node_id.get_or_insert_with(|| node_id.clone());
        }
        self.node_tree_index
            .entry(node_id)
            .or_default()
            .insert(tree_id);
        Ok(())
    }

    pub fn attach_child(
        &mut self,
        tree_id: impl Into<String>,
        parent_node_id: impl Into<String>,
        node_id: impl Into<String>,
        local_rank: u32,
    ) -> LorentzResult<()> {
        let tree_id = tree_id.into();
        let parent_node_id = parent_node_id.into();
        let node_id = node_id.into();
        self.ensure_tree_exists(&tree_id)?;
        self.ensure_node_exists(&parent_node_id)?;
        self.ensure_node_exists(&node_id)?;
        let key = (tree_id.clone(), node_id.clone());
        if self.memberships.contains_key(&key) {
            return Err(LorentzTreeError::DuplicateMembership { tree_id, node_id });
        }
        let parent_key = (tree_id.clone(), parent_node_id.clone());
        let parent =
            self.memberships
                .get(&parent_key)
                .ok_or_else(|| LorentzTreeError::InvalidParent {
                    tree_id: tree_id.clone(),
                    parent_node_id: parent_node_id.clone(),
                })?;
        if self.would_create_cycle(&tree_id, &node_id, &parent_node_id)? {
            return Err(LorentzTreeError::CycleRejected {
                tree_id,
                node_id,
                parent_node_id,
            });
        }
        let membership = LorentzTreeMembership::child(
            tree_id.clone(),
            node_id.clone(),
            parent_node_id.clone(),
            parent.level,
            local_rank,
            &parent.path_key,
        );
        self.memberships
            .insert((tree_id.clone(), node_id.clone()), membership);
        self.children
            .entry((tree_id.clone(), parent_node_id))
            .or_default()
            .push(node_id.clone());
        self.node_tree_index
            .entry(node_id)
            .or_default()
            .insert(tree_id);
        Ok(())
    }

    pub fn children_of(
        &self,
        tree_id: &str,
        parent_node_id: &str,
    ) -> LorentzResult<Vec<&LorentzNode>> {
        self.ensure_tree_exists(tree_id)?;
        self.ensure_node_exists(parent_node_id)?;
        let key = (tree_id.to_owned(), parent_node_id.to_owned());
        let Some(child_ids) = self.children.get(&key) else {
            return Ok(Vec::new());
        };
        child_ids
            .iter()
            .map(|child_id| {
                self.nodes
                    .get(child_id)
                    .ok_or_else(|| LorentzTreeError::MissingNode(child_id.clone()))
            })
            .collect()
    }

    pub fn ancestors_of(&self, tree_id: &str, node_id: &str) -> LorentzResult<Vec<&LorentzNode>> {
        self.ensure_tree_exists(tree_id)?;
        self.ensure_node_exists(node_id)?;
        let mut out = Vec::new();
        let mut cursor = node_id.to_owned();
        let mut seen = BTreeSet::new();
        loop {
            if !seen.insert(cursor.clone()) {
                return Err(LorentzTreeError::CycleRejected {
                    tree_id: tree_id.to_owned(),
                    node_id: node_id.to_owned(),
                    parent_node_id: cursor,
                });
            }
            let key = (tree_id.to_owned(), cursor.clone());
            let membership =
                self.memberships
                    .get(&key)
                    .ok_or_else(|| LorentzTreeError::MissingMembership {
                        tree_id: tree_id.to_owned(),
                        node_id: cursor.clone(),
                    })?;
            let Some(parent_id) = &membership.parent_node_id else {
                break;
            };
            let parent = self
                .nodes
                .get(parent_id)
                .ok_or_else(|| LorentzTreeError::MissingNode(parent_id.clone()))?;
            out.push(parent);
            cursor = parent_id.clone();
        }
        Ok(out)
    }

    pub fn candidate_refs(&self) -> Vec<LorentzCandidateRef<'_, String>> {
        let mut candidates = Vec::with_capacity(self.memberships.len());
        for ((tree_id, node_id), membership) in &self.memberships {
            let Some(node) = self.nodes.get(node_id) else {
                continue;
            };
            let Some(tree) = self.trees.get(tree_id) else {
                continue;
            };
            let has_cross_tree_support = self
                .node_tree_index
                .get(node_id)
                .map(|tree_ids| tree_ids.len() > 1)
                .unwrap_or(false);
            candidates.push(LorentzCandidateRef {
                candidate_id: format!("{tree_id}:{node_id}"),
                node,
                tree: Some(tree),
                membership: Some(membership),
                has_cross_tree_support,
            });
        }
        candidates
    }

    pub fn rank(
        &self,
        query: &LorentzTreeQuery,
        config: LorentzScoreConfig,
    ) -> LorentzResult<Vec<LorentzCandidateScore<String>>> {
        rank_lorentz_candidates(query, self.candidate_refs(), config)
    }

    fn ensure_tree_exists(&self, tree_id: &str) -> LorentzResult<()> {
        if self.trees.contains_key(tree_id) {
            Ok(())
        } else {
            Err(LorentzTreeError::MissingTree(tree_id.to_owned()))
        }
    }

    fn ensure_node_exists(&self, node_id: &str) -> LorentzResult<()> {
        if self.nodes.contains_key(node_id) {
            Ok(())
        } else {
            Err(LorentzTreeError::MissingNode(node_id.to_owned()))
        }
    }

    fn would_create_cycle(
        &self,
        tree_id: &str,
        node_id: &str,
        parent_node_id: &str,
    ) -> LorentzResult<bool> {
        let mut cursor = Some(parent_node_id.to_owned());
        let mut seen = BTreeSet::new();
        while let Some(current) = cursor {
            if current == node_id || !seen.insert(current.clone()) {
                return Ok(true);
            }
            let key = (tree_id.to_owned(), current);
            cursor = self
                .memberships
                .get(&key)
                .and_then(|membership| membership.parent_node_id.clone());
        }
        Ok(false)
    }
}
