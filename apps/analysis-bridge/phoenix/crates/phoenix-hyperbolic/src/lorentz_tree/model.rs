use serde::{Deserialize, Serialize};

use super::error::LorentzResult;
use super::geometry::{validate_non_negative, validate_positive, HyperboloidPoint};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum LorentzTreeKind {
    Identity,
    Relationship,
    Location,
    Event,
    Temporal,
    Causal,
    Mechanical,
    Emotional,
    Political,
    Evidence,
    Provenance,
    Contradiction,
    Abstraction,
    Species,
    PowerSystem,
    DocumentStructure,
}

impl LorentzTreeKind {
    #[inline]
    pub fn is_compatible_with(self, other: Self) -> bool {
        if self == other {
            return true;
        }
        matches!(
            (self, other),
            (Self::Relationship, Self::Emotional)
                | (Self::Emotional, Self::Relationship)
                | (Self::Temporal, Self::Causal)
                | (Self::Causal, Self::Temporal)
                | (Self::Evidence, Self::Provenance)
                | (Self::Provenance, Self::Evidence)
                | (Self::Mechanical, Self::PowerSystem)
                | (Self::PowerSystem, Self::Mechanical)
                | (Self::Event, Self::Temporal)
                | (Self::Temporal, Self::Event)
        )
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum LorentzQueryMode {
    AnchorSearch,
    DirectLookup,
    HierarchicalExpansion,
    CrossHierarchySynthesis,
    Contradiction,
}

impl Default for LorentzQueryMode {
    fn default() -> Self {
        Self::DirectLookup
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LorentzNode {
    pub node_id: String,
    pub label: String,
    pub point: HyperboloidPoint,
    pub point_ref: Option<String>,
    pub node_confidence: f32,
    pub geometry_version: u64,
}

impl LorentzNode {
    pub fn new(
        node_id: impl Into<String>,
        label: impl Into<String>,
        point: HyperboloidPoint,
    ) -> LorentzResult<Self> {
        point.validate()?;
        Ok(Self {
            node_id: node_id.into(),
            label: label.into(),
            point,
            point_ref: None,
            node_confidence: 1.0,
            geometry_version: 1,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LorentzTree {
    pub tree_id: String,
    pub tree_kind: LorentzTreeKind,
    pub label: String,
    pub root_node_id: Option<String>,
    pub geometry_version: u64,
}

impl LorentzTree {
    pub fn new(
        tree_id: impl Into<String>,
        tree_kind: LorentzTreeKind,
        label: impl Into<String>,
    ) -> Self {
        Self {
            tree_id: tree_id.into(),
            tree_kind,
            label: label.into(),
            root_node_id: None,
            geometry_version: 1,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LorentzTreeMembership {
    pub tree_id: String,
    pub node_id: String,
    pub parent_node_id: Option<String>,
    pub level: u32,
    pub local_rank: u32,
    pub path_key: String,
    pub branch_weight: f32,
    pub confidence: f32,
    pub source_count: u32,
    pub geometry_version: u64,
}

impl LorentzTreeMembership {
    pub fn root(tree_id: impl Into<String>, node_id: impl Into<String>) -> Self {
        let tree_id = tree_id.into();
        let node_id = node_id.into();
        Self {
            path_key: format!("{tree_id}/{node_id}"),
            tree_id,
            node_id,
            parent_node_id: None,
            level: 0,
            local_rank: 0,
            branch_weight: 1.0,
            confidence: 1.0,
            source_count: 1,
            geometry_version: 1,
        }
    }

    pub fn child(
        tree_id: impl Into<String>,
        node_id: impl Into<String>,
        parent_node_id: impl Into<String>,
        parent_level: u32,
        local_rank: u32,
        parent_path_key: &str,
    ) -> Self {
        let tree_id = tree_id.into();
        let node_id = node_id.into();
        let parent_node_id = parent_node_id.into();
        Self {
            path_key: format!("{parent_path_key}/{node_id}"),
            tree_id,
            node_id,
            parent_node_id: Some(parent_node_id),
            level: parent_level.saturating_add(1),
            local_rank,
            branch_weight: 1.0,
            confidence: 1.0,
            source_count: 1,
            geometry_version: 1,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LorentzTreeQuery {
    pub point: HyperboloidPoint,
    pub tree_kinds: Vec<LorentzTreeKind>,
    pub tree_ids: Vec<String>,
    pub target_level: Option<u32>,
    pub mode: LorentzQueryMode,
}

impl LorentzTreeQuery {
    pub fn new(point: HyperboloidPoint) -> LorentzResult<Self> {
        point.validate()?;
        Ok(Self {
            point,
            tree_kinds: Vec::new(),
            tree_ids: Vec::new(),
            target_level: None,
            mode: LorentzQueryMode::DirectLookup,
        })
    }

    pub fn with_tree_kinds(mut self, tree_kinds: Vec<LorentzTreeKind>) -> Self {
        self.tree_kinds = tree_kinds;
        self
    }

    pub fn with_tree_ids(mut self, tree_ids: Vec<String>) -> Self {
        self.tree_ids = tree_ids;
        self
    }

    pub fn with_target_level(mut self, target_level: u32) -> Self {
        self.target_level = Some(target_level);
        self
    }

    pub fn with_mode(mut self, mode: LorentzQueryMode) -> Self {
        self.mode = mode;
        self
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LorentzScoreConfig {
    pub geometry_weight: f32,
    pub tree_kind_weight: f32,
    pub hierarchy_weight: f32,
    pub branch_weight: f32,
    pub evidence_weight: f32,
    pub confidence_weight: f32,
    pub unsupported_cross_tree_penalty: f32,
    pub tree_drift_penalty: f32,
    pub level_mismatch_penalty: f32,
    pub distance_scale: f32,
}

impl Default for LorentzScoreConfig {
    fn default() -> Self {
        Self {
            geometry_weight: 0.38,
            tree_kind_weight: 0.18,
            hierarchy_weight: 0.14,
            branch_weight: 0.08,
            evidence_weight: 0.06,
            confidence_weight: 0.08,
            unsupported_cross_tree_penalty: 0.18,
            tree_drift_penalty: 0.14,
            level_mismatch_penalty: 0.12,
            distance_scale: 2.0,
        }
    }
}

impl LorentzScoreConfig {
    pub fn validate(self) -> LorentzResult<Self> {
        for (field, value) in [
            ("geometry_weight", self.geometry_weight),
            ("tree_kind_weight", self.tree_kind_weight),
            ("hierarchy_weight", self.hierarchy_weight),
            ("branch_weight", self.branch_weight),
            ("evidence_weight", self.evidence_weight),
            ("confidence_weight", self.confidence_weight),
            (
                "unsupported_cross_tree_penalty",
                self.unsupported_cross_tree_penalty,
            ),
            ("tree_drift_penalty", self.tree_drift_penalty),
            ("level_mismatch_penalty", self.level_mismatch_penalty),
        ] {
            validate_non_negative(field, value)?;
        }
        validate_positive("distance_scale", self.distance_scale)?;
        Ok(self)
    }
}
