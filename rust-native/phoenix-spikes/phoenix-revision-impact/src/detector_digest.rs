use std::collections::BTreeMap;

use compact_str::CompactString;
use phoenix_types::{ConstraintKind, DependencyClass, GraphTruthDigest};

use super::{
    classification_rank, plane_rank, CanonicalCoverageRequest, CoverageStatus, GraphGeneration,
    RevisionImpact, RippleConfig, REVISION_IMPACT_REPORT_SCHEMA,
};

pub(super) fn digest_report(
    generation: GraphGeneration,
    base_digest: GraphTruthDigest,
    mutation_digest: GraphTruthDigest,
    impacts: &[RevisionImpact],
    requests: &BTreeMap<CompactString, CanonicalCoverageRequest>,
    config: RippleConfig,
) -> GraphTruthDigest {
    let mut hasher = blake3::Hasher::new();
    hash_str(&mut hasher, REVISION_IMPACT_REPORT_SCHEMA);
    hash_u64(&mut hasher, generation.0);
    hasher.update(&base_digest.0);
    hasher.update(&mutation_digest.0);
    hash_config(&mut hasher, config);
    hash_u64(&mut hasher, requests.len() as u64);
    for (scene_id, request) in requests {
        hash_str(&mut hasher, scene_id);
        hash_planes(&mut hasher, &request.required_planes);
        hash_planes(&mut hasher, &request.unavailable_planes);
    }
    hash_u64(&mut hasher, impacts.len() as u64);
    for impact in impacts {
        hash_impact(&mut hasher, impact);
    }
    GraphTruthDigest(*hasher.finalize().as_bytes())
}

fn hash_config(hasher: &mut blake3::Hasher, config: RippleConfig) {
    hash_u64(hasher, config.max_representative_paths as u64);
    hash_u64(hasher, config.max_path_length as u64);
    hash_u64(hasher, config.max_signals_per_component as u64);
    hash_u64(hasher, config.max_visited_states as u64);
    hash_u64(hasher, config.max_traversed_edges as u64);
    hash_u64(hasher, u64::from(config.min_soft_score_millis));
}

fn hash_impact(hasher: &mut blake3::Hasher, impact: &RevisionImpact) {
    hash_str(hasher, &impact.scene_id.0);
    hasher.update(&[classification_rank(impact.classification)]);
    hash_u64(hasher, u64::from(impact.score_millis));
    hasher.update(&[0x10]);
    hash_u64(hasher, impact.violated_constraints.len() as u64);
    for constraint in &impact.violated_constraints {
        hash_constraint(hasher, constraint);
    }
    hasher.update(&[0x11]);
    hash_u64(hasher, impact.support_loss_constraints.len() as u64);
    for constraint in &impact.support_loss_constraints {
        hash_constraint(hasher, constraint);
    }
    hasher.update(&[0x12]);
    hash_u64(hasher, impact.causal_paths.len() as u64);
    for path in &impact.causal_paths {
        hash_str(hasher, &path.source_id);
        hash_str(hasher, &path.origin_evidence_id);
        hash_strings(hasher, &path.node_ids);
        hash_strings(hasher, &path.constraint_ids);
        hash_strings(hasher, &path.evidence_ids);
        hasher.update(&[classification_rank(path.classification)]);
        hash_u64(hasher, u64::from(path.score_millis));
    }
    hash_u64(hasher, impact.coverage.planes.len() as u64);
    for row in &impact.coverage.planes {
        hasher.update(&[plane_rank(row.plane), coverage_rank(row.status)]);
        hash_u64(hasher, row.projected_constraints as u64);
    }
    hash_planes(hasher, &impact.coverage.required_planes);
    hash_planes(hasher, &impact.coverage.missing_required_planes);
    hasher.update(&[u8::from(impact.coverage.classification_supported)]);
}

fn hash_constraint(hasher: &mut blake3::Hasher, constraint: &super::ConstraintImpact) {
    hash_str(hasher, &constraint.constraint_id);
    hasher.update(&[
        constraint_kind_rank(constraint.kind),
        dependency_rank(constraint.dependency_class),
    ]);
    hash_i64(hasher, constraint.valid_interval.valid_from.0);
    match constraint.valid_interval.valid_to_exclusive {
        Some(end) => {
            hasher.update(&[1]);
            hash_i64(hasher, end.0);
        }
        None => {
            hasher.update(&[0]);
        }
    }
    hash_u64(hasher, u64::from(constraint.confidence_millis));
    hash_u64(hasher, constraint.evidence.len() as u64);
    for evidence in &constraint.evidence {
        hash_str(hasher, &evidence.evidence_id);
        hash_optional_str(hasher, evidence.document_id.as_deref());
        match evidence.source_range {
            Some(range) => {
                hasher.update(&[1]);
                hash_u64(hasher, u64::from(range.start));
                hash_u64(hasher, u64::from(range.end));
            }
            None => {
                hasher.update(&[0]);
            }
        }
    }
}

fn hash_planes(hasher: &mut blake3::Hasher, planes: &[phoenix_types::CoveragePlane]) {
    hash_u64(hasher, planes.len() as u64);
    for plane in planes {
        hasher.update(&[plane_rank(*plane)]);
    }
}

fn hash_strings(hasher: &mut blake3::Hasher, values: &[CompactString]) {
    hash_u64(hasher, values.len() as u64);
    for value in values {
        hash_str(hasher, value);
    }
}

fn hash_optional_str(hasher: &mut blake3::Hasher, value: Option<&str>) {
    if let Some(value) = value {
        hasher.update(&[1]);
        hash_str(hasher, value);
    } else {
        hasher.update(&[0]);
    }
}

const fn coverage_rank(status: CoverageStatus) -> u8 {
    match status {
        CoverageStatus::Covered => 0,
        CoverageStatus::Partial => 1,
        CoverageStatus::Unavailable => 2,
    }
}

const fn dependency_rank(class: DependencyClass) -> u8 {
    match class {
        DependencyClass::HardRequirement => 0,
        DependencyClass::DefeasibleSupport => 1,
        DependencyClass::WeakAssociation => 2,
    }
}

const fn constraint_kind_rank(kind: ConstraintKind) -> u8 {
    match kind {
        ConstraintKind::RequiresKnowledge => 0,
        ConstraintKind::RequiresWitness => 1,
        ConstraintKind::RequiresAlive => 2,
        ConstraintKind::RequiresPossession => 3,
        ConstraintKind::RequiresReachability => 4,
        ConstraintKind::RequiresState => 5,
        ConstraintKind::RequiresTemporalOrder => 6,
        ConstraintKind::MutuallyExclusiveStates => 7,
        ConstraintKind::CausalSupport => 8,
        ConstraintKind::Motivation => 9,
        ConstraintKind::Foreshadowing => 10,
        ConstraintKind::Mention => 11,
        ConstraintKind::ThematicEcho => 12,
    }
}

fn hash_i64(hasher: &mut blake3::Hasher, value: i64) {
    hasher.update(&value.to_le_bytes());
}

fn hash_u64(hasher: &mut blake3::Hasher, value: u64) {
    hasher.update(&value.to_le_bytes());
}

fn hash_str(hasher: &mut blake3::Hasher, value: &str) {
    hash_u64(hasher, value.len() as u64);
    hasher.update(value.as_bytes());
}
