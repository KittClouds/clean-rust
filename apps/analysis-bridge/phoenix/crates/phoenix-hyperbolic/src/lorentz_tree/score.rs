use core::cmp::Ordering;
use serde::{Deserialize, Serialize};

use super::error::LorentzResult;
use super::geometry::{hyperbolic_distance, hyperbolic_similarity01};
use super::model::{
    LorentzNode, LorentzQueryMode, LorentzScoreConfig, LorentzTree, LorentzTreeKind,
    LorentzTreeMembership, LorentzTreeQuery,
};

#[derive(Clone, Debug)]
pub struct LorentzCandidateRef<'a, T> {
    pub candidate_id: T,
    pub node: &'a LorentzNode,
    pub tree: Option<&'a LorentzTree>,
    pub membership: Option<&'a LorentzTreeMembership>,
    pub has_cross_tree_support: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LorentzCandidateScore<T> {
    pub candidate_id: T,
    pub node_id: String,
    pub tree_id: Option<String>,
    pub tree_kind: Option<LorentzTreeKind>,
    pub score: f32,
    pub hyperbolic_distance: f32,
    pub geometry_similarity: f32,
    pub tree_kind_match: f32,
    pub hierarchy_alignment: f32,
    pub branch_strength: f32,
    pub evidence_strength: f32,
    pub confidence: f32,
    pub unsupported_cross_tree_penalty: f32,
    pub tree_drift_penalty: f32,
    pub level_mismatch_penalty: f32,
}

pub fn score_lorentz_candidate<T: Clone>(
    query: &LorentzTreeQuery,
    candidate: LorentzCandidateRef<'_, T>,
    config: LorentzScoreConfig,
) -> LorentzResult<LorentzCandidateScore<T>> {
    let config = config.validate()?;
    query.point.validate()?;
    candidate.node.point.validate()?;

    let distance = hyperbolic_distance(query.point, candidate.node.point)?;
    let geometry_similarity =
        hyperbolic_similarity01(query.point, candidate.node.point, config.distance_scale)?
            * candidate.node.node_confidence.clamp(0.0, 1.0);
    let tree_kind_match = match candidate.tree {
        Some(tree) => tree_kind_match(query, tree.tree_kind),
        None if query.tree_kinds.is_empty() => 0.75,
        None => 0.0,
    };
    let hierarchy_alignment = match candidate.membership {
        Some(membership) => hierarchy_alignment_score(query, membership),
        None if query.target_level.is_none() => 0.5,
        None => 0.0,
    };
    let branch_strength = candidate
        .membership
        .map(|membership| membership.branch_weight.clamp(0.0, 1.0))
        .unwrap_or(0.0);
    let evidence_strength = candidate
        .membership
        .map(|membership| source_count_score(membership.source_count))
        .unwrap_or(0.0);
    let confidence = match candidate.membership {
        Some(membership) => {
            let node_conf = candidate.node.node_confidence.clamp(0.0, 1.0);
            let member_conf = membership.confidence.clamp(0.0, 1.0);
            (0.45 * node_conf + 0.55 * member_conf).clamp(0.0, 1.0)
        }
        None => candidate.node.node_confidence.clamp(0.0, 1.0),
    };
    let needs_cross_tree_support = matches!(
        query.mode,
        LorentzQueryMode::CrossHierarchySynthesis | LorentzQueryMode::Contradiction
    );
    let unsupported_cross_tree_penalty =
        if needs_cross_tree_support && !candidate.has_cross_tree_support {
            config.unsupported_cross_tree_penalty
        } else {
            0.0
        };
    let tree_drift_penalty = if query.tree_kinds.is_empty() {
        0.0
    } else {
        config.tree_drift_penalty * (1.0 - tree_kind_match).clamp(0.0, 1.0)
    };
    let level_mismatch_penalty = match (query.target_level, candidate.membership) {
        (Some(target), Some(membership)) => {
            let diff = target.abs_diff(membership.level) as f32;
            config.level_mismatch_penalty * (diff / 8.0).clamp(0.0, 1.0)
        }
        (Some(_), None) => config.level_mismatch_penalty,
        (None, _) => 0.0,
    };

    let raw = (config.geometry_weight * geometry_similarity)
        + (config.tree_kind_weight * tree_kind_match)
        + (config.hierarchy_weight * hierarchy_alignment)
        + (config.branch_weight * branch_strength)
        + (config.evidence_weight * evidence_strength)
        + (config.confidence_weight * confidence)
        - unsupported_cross_tree_penalty
        - tree_drift_penalty
        - level_mismatch_penalty;

    Ok(LorentzCandidateScore {
        candidate_id: candidate.candidate_id,
        node_id: candidate.node.node_id.clone(),
        tree_id: candidate.tree.map(|tree| tree.tree_id.clone()),
        tree_kind: candidate.tree.map(|tree| tree.tree_kind),
        score: raw,
        hyperbolic_distance: distance,
        geometry_similarity,
        tree_kind_match,
        hierarchy_alignment,
        branch_strength,
        evidence_strength,
        confidence,
        unsupported_cross_tree_penalty,
        tree_drift_penalty,
        level_mismatch_penalty,
    })
}

pub fn rank_lorentz_candidates<'a, T: Clone + Ord>(
    query: &LorentzTreeQuery,
    candidates: impl IntoIterator<Item = LorentzCandidateRef<'a, T>>,
    config: LorentzScoreConfig,
) -> LorentzResult<Vec<LorentzCandidateScore<T>>> {
    let mut scores = candidates
        .into_iter()
        .map(|candidate| score_lorentz_candidate(query, candidate, config))
        .collect::<LorentzResult<Vec<_>>>()?;
    scores.sort_by(compare_candidate_scores);
    Ok(scores)
}

pub(crate) fn compare_candidate_scores<T: Ord>(
    left: &LorentzCandidateScore<T>,
    right: &LorentzCandidateScore<T>,
) -> Ordering {
    compare_score_desc(left.score, right.score)
        .then_with(|| {
            left.hyperbolic_distance
                .total_cmp(&right.hyperbolic_distance)
        })
        .then_with(|| left.tree_id.cmp(&right.tree_id))
        .then_with(|| left.node_id.cmp(&right.node_id))
        .then_with(|| left.candidate_id.cmp(&right.candidate_id))
}

fn tree_kind_match(query: &LorentzTreeQuery, candidate: LorentzTreeKind) -> f32 {
    if query.tree_kinds.is_empty() {
        return match query.mode {
            LorentzQueryMode::AnchorSearch => 0.5,
            LorentzQueryMode::DirectLookup => 0.75,
            LorentzQueryMode::HierarchicalExpansion => expansion_mode_match(candidate),
            LorentzQueryMode::CrossHierarchySynthesis => synthesis_mode_match(candidate),
            LorentzQueryMode::Contradiction => contradiction_mode_match(candidate),
        };
    }
    if query.tree_kinds.contains(&candidate) {
        1.0
    } else if query
        .tree_kinds
        .iter()
        .any(|kind| kind.is_compatible_with(candidate))
    {
        0.65
    } else {
        0.0
    }
}

fn expansion_mode_match(kind: LorentzTreeKind) -> f32 {
    match kind {
        LorentzTreeKind::Identity
        | LorentzTreeKind::Event
        | LorentzTreeKind::Temporal
        | LorentzTreeKind::Causal
        | LorentzTreeKind::DocumentStructure => 0.85,
        LorentzTreeKind::Evidence | LorentzTreeKind::Provenance => 0.70,
        _ => 0.50,
    }
}

fn synthesis_mode_match(kind: LorentzTreeKind) -> f32 {
    match kind {
        LorentzTreeKind::Identity
        | LorentzTreeKind::Causal
        | LorentzTreeKind::Temporal
        | LorentzTreeKind::Evidence
        | LorentzTreeKind::Provenance
        | LorentzTreeKind::Contradiction => 0.85,
        _ => 0.55,
    }
}

fn contradiction_mode_match(kind: LorentzTreeKind) -> f32 {
    match kind {
        LorentzTreeKind::Contradiction
        | LorentzTreeKind::Evidence
        | LorentzTreeKind::Provenance => 1.0,
        LorentzTreeKind::Temporal | LorentzTreeKind::Causal | LorentzTreeKind::Identity => 0.65,
        _ => 0.30,
    }
}

fn hierarchy_alignment_score(query: &LorentzTreeQuery, membership: &LorentzTreeMembership) -> f32 {
    let level_score = match query.target_level {
        Some(target) => {
            let diff = target.abs_diff(membership.level) as f32;
            (1.0 / (1.0 + diff)).clamp(0.0, 1.0)
        }
        None => 0.65,
    };
    let tree_id_score = if query.tree_ids.is_empty() {
        0.65
    } else if query.tree_ids.contains(&membership.tree_id) {
        1.0
    } else {
        0.0
    };
    ((0.55 * level_score) + (0.45 * tree_id_score)).clamp(0.0, 1.0)
}

fn source_count_score(source_count: u32) -> f32 {
    if source_count == 0 {
        0.0
    } else {
        ((source_count as f32).ln_1p() / 8.0_f32.ln_1p()).clamp(0.0, 1.0)
    }
}

#[inline]
fn compare_score_desc(a: f32, b: f32) -> Ordering {
    b.partial_cmp(&a).unwrap_or(Ordering::Equal)
}
