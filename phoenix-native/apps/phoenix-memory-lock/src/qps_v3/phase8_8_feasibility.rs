use std::cmp::Ordering;

use phoenix_lexical_qps::{
    JudgmentReasonV3, LeakageSplitV3, LinearRankerV3, PrimarySplitV3, RankEvidenceV3,
    RelevanceLedgerV3, RelevanceTier, RANK_EVIDENCE_V3_FEATURE_COUNT,
    RANK_EVIDENCE_V3_FEATURE_NAMES,
};

use super::train::LinearModelArtifactV3;
use super::*;

const CONTRACT: &str = "phoenix.memory.qps-v3-phase8.8-monotone-feasibility/v1";
const MINIMUM_DEVELOPMENT_ERRORS: usize = 30;
const MINIMUM_EXPRESSIBLE_ERROR_FRACTION: f64 = 0.70;
const MAXIMUM_EXACT_COLLISION_FRACTION: f64 = 0.10;
const MINIMUM_TARGET_CLASS_EXPRESSIBLE_FRACTION: f64 = 0.50;
const MINIMUM_TARGET_CLASSES_EXPRESSIBLE: usize = 3;
const NEAR_COLLISION_EPSILON: f32 = 1.0e-6;
const COVERAGE_FEATURES: [usize; 6] = [6, 7, 8, 9, 14, 29];
const TARGET_REASONS: [JudgmentReasonV3; 4] = [
    JudgmentReasonV3::PartialMatchSaturation,
    JudgmentReasonV3::PhraseOrderFailure,
    JudgmentReasonV3::CommonTermDominance,
    JudgmentReasonV3::LengthPriorFailure,
];

pub(crate) fn audit(
    model_path: &Path,
    phase_6_path: &Path,
    phase_4_path: &Path,
    phase_8_v2_path: &Path,
    output_path: &Path,
) -> Result<FeasibilityPublication> {
    if output_path.exists() {
        bail!(
            "refusing to overwrite Phase 8.8 feasibility receipt {}",
            output_path.display()
        );
    }
    let model: LinearModelArtifactV3 = read_json(model_path, "model artifact")?;
    if !model.validate_challenger() {
        bail!("Phase 8.8 feasibility requires a valid Phase 7 model");
    }
    let phase_6: FrozenPhase6 = read_json(phase_6_path, "Phase 6 receipt")?;
    if phase_6.contract != "phoenix.memory.qps-v3-leakage-split/v1"
        || !phase_6.phase_6_verified
        || !phase_6.split.audit.is_qualified()
    {
        bail!("Phase 8.8 feasibility requires a verified Phase 6 split");
    }
    let phase_4: FrozenPhase4 = read_json(phase_4_path, "Phase 4 receipt")?;
    if phase_4.contract != "phoenix.memory.qps-v3-ledger-qualification/v1"
        || !phase_4.phase_4_verified
    {
        bail!("Phase 8.8 feasibility requires a verified Phase 4 ledger");
    }
    phase_4.ledger.validate().map_err(anyhow::Error::msg)?;
    let phase_8: FrozenPhase8V2 = read_json(phase_8_v2_path, "Phase 8 v2 receipt")?;
    if phase_8.contract != super::quality::CONTRACT
        || phase_8.phase_8_verified
        || phase_8.model_identity != model.model_identity
    {
        bail!("Phase 8.8 feasibility requires the failed, model-bound Phase 8 v2 receipt");
    }

    let assignments = phase_6
        .split
        .assignments
        .iter()
        .map(|assignment| (assignment.judgment_identity, assignment.primary_split))
        .collect::<HashMap<_, _>>();
    let development = phase_4
        .ledger
        .active_model_training_judgments()
        .into_iter()
        .filter(|judgment| {
            assignments.get(&judgment.identity) == Some(&PrimarySplitV3::Development)
        })
        .collect::<Vec<_>>();
    if development.len() != phase_6.split.audit.development_judgments {
        bail!("development audit did not project every Phase 6 judgment exactly once");
    }

    let mut feature_maximum_deltas = [0.0_f32; RANK_EVIDENCE_V3_FEATURE_COUNT];
    let mut duplicate_maximum_difference = 0.0_f32;
    let mut overall = FeasibilityCounts::default();
    let mut classes = all_reasons()
        .into_iter()
        .map(ClassFeasibility::new)
        .collect::<Vec<_>>();

    for judgment in development {
        let differences =
            feature_differences(judgment.positive_features, judgment.negative_features);
        for (maximum, difference) in feature_maximum_deltas.iter_mut().zip(differences) {
            *maximum = maximum.max(difference.abs());
        }
        for evidence in [judgment.positive_features, judgment.negative_features] {
            duplicate_maximum_difference = duplicate_maximum_difference.max(
                (evidence.values[RankEvidenceV3::MATCHED_GROUP_FRACTION]
                    - evidence.values[RankEvidenceV3::MISSING_GROUP_ABSENCE])
                    .abs(),
            );
        }

        let class = classes
            .iter_mut()
            .find(|class| class.reason == judgment.reason)
            .expect("all judgment reasons are represented");
        class.development_judgments += 1;
        overall.development_judgments += 1;
        if pair_is_correct(&model.model_parameters, judgment)? {
            continue;
        }
        class.canonical_errors += 1;
        overall.canonical_errors += 1;
        let category = classify_error(
            judgment.positive_tier,
            judgment.negative_tier,
            &differences,
            judgment.positive_document_version.as_bytes(),
            judgment.negative_document_version.as_bytes(),
        );
        class.observe(category);
        overall.observe(category);
        if judgment.reason == JudgmentReasonV3::LengthPriorFailure {
            class.observe_length_delta(differences[RankEvidenceV3::DOCUMENT_LENGTH_PRIOR]);
        }
    }
    overall.finish();
    for class in &mut classes {
        class.finish();
    }

    let feature_visibility = feature_maximum_deltas
        .iter()
        .enumerate()
        .map(|(index, maximum_pair_delta)| FeatureVisibility {
            index,
            name: RANK_EVIDENCE_V3_FEATURE_NAMES[index],
            maximum_pair_delta: *maximum_pair_delta,
            development_ranking_dead: *maximum_pair_delta == 0.0,
        })
        .collect::<Vec<_>>();
    let coverage_weight = coverage_weight_audit(&model.model_parameters);
    let target_classes_expressible = classes
        .iter()
        .filter(|class| TARGET_REASONS.contains(&class.reason))
        .filter(|class| {
            class.canonical_errors > 0
                && class.expressible_error_fraction >= MINIMUM_TARGET_CLASS_EXPRESSIBLE_FRACTION
        })
        .count();
    let gates = FeasibilityGates {
        development_only: true,
        every_development_judgment_projected: overall.development_judgments
            == phase_6.split.audit.development_judgments,
        at_least_30_canonical_errors: overall.canonical_errors >= MINIMUM_DEVELOPMENT_ERRORS,
        expressible_error_fraction_at_least_0_70: overall.expressible_error_fraction
            >= MINIMUM_EXPRESSIBLE_ERROR_FRACTION,
        exact_collision_fraction_at_most_0_10: overall.exact_collision_fraction
            <= MAXIMUM_EXACT_COLLISION_FRACTION,
        at_least_three_target_classes_majority_expressible: target_classes_expressible
            >= MINIMUM_TARGET_CLASSES_EXPRESSIBLE,
        duplicate_coverage_coordinate_proven: duplicate_maximum_difference <= f32::EPSILON,
        canonical_schema_unchanged: true,
        canonical_ledger_unchanged: true,
        blind_labels_not_read: true,
    };
    let authorize_phase_8_8_training = gates.all_pass();
    let receipt = FeasibilityReceipt {
        contract: CONTRACT,
        architecture: "development-only monotonic-cone and collision audit; no training",
        model_artifact: file_identity(model_path)?,
        phase_6_receipt: file_identity(phase_6_path)?,
        phase_4_receipt: file_identity(phase_4_path)?,
        phase_8_v2_receipt: file_identity(phase_8_v2_path)?,
        producer_binary: current_binary_identity()?,
        thresholds: FeasibilityThresholds {
            minimum_development_errors: MINIMUM_DEVELOPMENT_ERRORS,
            minimum_expressible_error_fraction: MINIMUM_EXPRESSIBLE_ERROR_FRACTION,
            maximum_exact_collision_fraction: MAXIMUM_EXACT_COLLISION_FRACTION,
            minimum_target_class_expressible_fraction: MINIMUM_TARGET_CLASS_EXPRESSIBLE_FRACTION,
            minimum_target_classes_expressible: MINIMUM_TARGET_CLASSES_EXPRESSIBLE,
            near_collision_epsilon: NEAR_COLLISION_EPSILON,
        },
        overall,
        classes,
        feature_visibility,
        duplicate_coverage_coordinate: DuplicateCoverageCoordinate {
            matched_group_fraction_index: RankEvidenceV3::MATCHED_GROUP_FRACTION,
            missing_group_absence_index: RankEvidenceV3::MISSING_GROUP_ABSENCE,
            maximum_absolute_difference: duplicate_maximum_difference,
            mathematically_duplicate: duplicate_maximum_difference <= f32::EPSILON,
        },
        coverage_weight,
        target_classes_expressible,
        gates,
        authorize_phase_8_8_training,
        canonical_rank_evidence_schema_changed: false,
        canonical_ledger_changed: false,
        active_engine_after_audit: "V2 active",
    };
    write_json_atomic(output_path, &receipt)?;
    Ok(FeasibilityPublication {
        contract: CONTRACT,
        output: file_identity(output_path)?,
        overall: receipt.overall,
        target_classes_expressible,
        gates,
        authorize_phase_8_8_training,
    })
}

fn pair_is_correct(
    model: &LinearRankerV3,
    judgment: &phoenix_lexical_qps::PairwiseJudgmentV3,
) -> Result<bool> {
    let positive_score = model
        .score(judgment.positive_features)
        .context("invalid positive development evidence")?;
    let negative_score = model
        .score(judgment.negative_features)
        .context("invalid negative development evidence")?;
    Ok(judgment
        .positive_tier
        .cmp(&judgment.negative_tier)
        .then_with(|| negative_score.total_cmp(&positive_score))
        .then_with(|| {
            judgment
                .positive_document_version
                .cmp(&judgment.negative_document_version)
        })
        == Ordering::Less)
}

fn feature_differences(
    positive: RankEvidenceV3,
    negative: RankEvidenceV3,
) -> [f32; RANK_EVIDENCE_V3_FEATURE_COUNT] {
    let mut differences = [0.0; RANK_EVIDENCE_V3_FEATURE_COUNT];
    for (index, difference) in differences.iter_mut().enumerate() {
        *difference = positive.values[index] - negative.values[index];
    }
    differences
}

fn classify_error(
    positive_tier: RelevanceTier,
    negative_tier: RelevanceTier,
    differences: &[f32; RANK_EVIDENCE_V3_FEATURE_COUNT],
    positive_identity: [u8; 32],
    negative_identity: [u8; 32],
) -> ErrorCategory {
    if positive_tier > negative_tier {
        return ErrorCategory::ConstitutionallyBlocked;
    }
    debug_assert_eq!(positive_tier, negative_tier);
    let exact_collision = differences.iter().all(|difference| *difference == 0.0);
    let near_collision = differences
        .iter()
        .all(|difference| difference.abs() <= NEAR_COLLISION_EPSILON);
    if differences.iter().any(|difference| *difference > 0.0) {
        ErrorCategory::ConeExpressible { near_collision }
    } else {
        let tie_break_rescuable =
            differences.contains(&0.0) && positive_identity < negative_identity;
        ErrorCategory::ScoreImpossible {
            exact_collision,
            near_collision,
            tie_break_rescuable,
        }
    }
}

fn coverage_weight_audit(model: &LinearRankerV3) -> CoverageWeightAudit {
    let total_weight = model.weights.iter().copied().sum::<f32>();
    let coverage_weight = COVERAGE_FEATURES
        .iter()
        .map(|index| model.weights[*index])
        .sum::<f32>();
    let matched = model.weights[RankEvidenceV3::MATCHED_GROUP_FRACTION];
    let missing = model.weights[RankEvidenceV3::MISSING_GROUP_ABSENCE];
    let effective = matched + missing;
    CoverageWeightAudit {
        feature_indices: COVERAGE_FEATURES,
        feature_names: COVERAGE_FEATURES.map(|index| RANK_EVIDENCE_V3_FEATURE_NAMES[index]),
        feature_weights: COVERAGE_FEATURES.map(|index| model.weights[index]),
        coverage_weight,
        total_model_weight: total_weight,
        coverage_weight_fraction: coverage_weight / total_weight.max(f32::EPSILON),
        duplicate_direction_effective_weight: effective,
        duplicate_direction_l2_ratio: if effective > 0.0 {
            (matched.mul_add(matched, missing * missing)) / (effective * effective)
        } else {
            0.0
        },
    }
}

fn all_reasons() -> [JudgmentReasonV3; 12] {
    [
        JudgmentReasonV3::PartialMatchSaturation,
        JudgmentReasonV3::ScatteredTerms,
        JudgmentReasonV3::PhraseOrderFailure,
        JudgmentReasonV3::IdentifierCollision,
        JudgmentReasonV3::FuzzyCollision,
        JudgmentReasonV3::WeakFieldEvidence,
        JudgmentReasonV3::CommonTermDominance,
        JudgmentReasonV3::LengthPriorFailure,
        JudgmentReasonV3::WrongConceptProximity,
        JudgmentReasonV3::DocumentConversationConfusion,
        JudgmentReasonV3::LongQueryFailure,
        JudgmentReasonV3::RealUserCorrection,
    ]
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path, label: &str) -> Result<T> {
    serde_json::from_slice(&fs::read(path)?)
        .with_context(|| format!("decode {label} {}", path.display()))
}

#[derive(Clone, Copy)]
enum ErrorCategory {
    ConeExpressible {
        near_collision: bool,
    },
    ScoreImpossible {
        exact_collision: bool,
        near_collision: bool,
        tie_break_rescuable: bool,
    },
    ConstitutionallyBlocked,
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
struct FeasibilityCounts {
    development_judgments: usize,
    canonical_errors: usize,
    cone_expressible_errors: usize,
    monotone_score_impossible_errors: usize,
    constitutionally_blocked_errors: usize,
    exact_feature_collisions: usize,
    near_feature_collisions: usize,
    stable_tie_break_rescuable: usize,
    expressible_error_fraction: f64,
    exact_collision_fraction: f64,
}

impl FeasibilityCounts {
    fn observe(&mut self, category: ErrorCategory) {
        match category {
            ErrorCategory::ConeExpressible { near_collision } => {
                self.cone_expressible_errors += 1;
                self.near_feature_collisions += usize::from(near_collision);
            }
            ErrorCategory::ScoreImpossible {
                exact_collision,
                near_collision,
                tie_break_rescuable,
            } => {
                self.monotone_score_impossible_errors += 1;
                self.exact_feature_collisions += usize::from(exact_collision);
                self.near_feature_collisions += usize::from(near_collision);
                self.stable_tie_break_rescuable += usize::from(tie_break_rescuable);
            }
            ErrorCategory::ConstitutionallyBlocked => {
                self.constitutionally_blocked_errors += 1;
            }
        }
    }

    fn finish(&mut self) {
        let errors = self.canonical_errors.max(1) as f64;
        self.expressible_error_fraction = self.cone_expressible_errors as f64 / errors;
        self.exact_collision_fraction = self.exact_feature_collisions as f64 / errors;
    }
}

#[derive(Clone, Copy, Debug, Serialize)]
struct ClassFeasibility {
    reason: JudgmentReasonV3,
    development_judgments: usize,
    canonical_errors: usize,
    cone_expressible_errors: usize,
    monotone_score_impossible_errors: usize,
    constitutionally_blocked_errors: usize,
    exact_feature_collisions: usize,
    near_feature_collisions: usize,
    stable_tie_break_rescuable: usize,
    expressible_error_fraction: f64,
    exact_collision_fraction: f64,
    length_prior_positive_delta: usize,
    length_prior_zero_delta: usize,
    length_prior_negative_delta: usize,
}

impl ClassFeasibility {
    const fn new(reason: JudgmentReasonV3) -> Self {
        Self {
            reason,
            development_judgments: 0,
            canonical_errors: 0,
            cone_expressible_errors: 0,
            monotone_score_impossible_errors: 0,
            constitutionally_blocked_errors: 0,
            exact_feature_collisions: 0,
            near_feature_collisions: 0,
            stable_tie_break_rescuable: 0,
            expressible_error_fraction: 0.0,
            exact_collision_fraction: 0.0,
            length_prior_positive_delta: 0,
            length_prior_zero_delta: 0,
            length_prior_negative_delta: 0,
        }
    }

    fn observe(&mut self, category: ErrorCategory) {
        let mut counts = FeasibilityCounts::default();
        counts.observe(category);
        self.cone_expressible_errors += counts.cone_expressible_errors;
        self.monotone_score_impossible_errors += counts.monotone_score_impossible_errors;
        self.constitutionally_blocked_errors += counts.constitutionally_blocked_errors;
        self.exact_feature_collisions += counts.exact_feature_collisions;
        self.near_feature_collisions += counts.near_feature_collisions;
        self.stable_tie_break_rescuable += counts.stable_tie_break_rescuable;
    }

    fn observe_length_delta(&mut self, delta: f32) {
        match delta.total_cmp(&0.0) {
            Ordering::Greater => self.length_prior_positive_delta += 1,
            Ordering::Equal => self.length_prior_zero_delta += 1,
            Ordering::Less => self.length_prior_negative_delta += 1,
        }
    }

    fn finish(&mut self) {
        let errors = self.canonical_errors.max(1) as f64;
        self.expressible_error_fraction = self.cone_expressible_errors as f64 / errors;
        self.exact_collision_fraction = self.exact_feature_collisions as f64 / errors;
    }
}

#[derive(Debug, Serialize)]
struct FeatureVisibility {
    index: usize,
    name: &'static str,
    maximum_pair_delta: f32,
    development_ranking_dead: bool,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct DuplicateCoverageCoordinate {
    matched_group_fraction_index: usize,
    missing_group_absence_index: usize,
    maximum_absolute_difference: f32,
    mathematically_duplicate: bool,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct CoverageWeightAudit {
    feature_indices: [usize; 6],
    feature_names: [&'static str; 6],
    feature_weights: [f32; 6],
    coverage_weight: f32,
    total_model_weight: f32,
    coverage_weight_fraction: f32,
    duplicate_direction_effective_weight: f32,
    duplicate_direction_l2_ratio: f32,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct FeasibilityThresholds {
    minimum_development_errors: usize,
    minimum_expressible_error_fraction: f64,
    maximum_exact_collision_fraction: f64,
    minimum_target_class_expressible_fraction: f64,
    minimum_target_classes_expressible: usize,
    near_collision_epsilon: f32,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct FeasibilityGates {
    development_only: bool,
    every_development_judgment_projected: bool,
    at_least_30_canonical_errors: bool,
    expressible_error_fraction_at_least_0_70: bool,
    exact_collision_fraction_at_most_0_10: bool,
    at_least_three_target_classes_majority_expressible: bool,
    duplicate_coverage_coordinate_proven: bool,
    canonical_schema_unchanged: bool,
    canonical_ledger_unchanged: bool,
    blind_labels_not_read: bool,
}

impl FeasibilityGates {
    fn all_pass(self) -> bool {
        self.development_only
            && self.every_development_judgment_projected
            && self.at_least_30_canonical_errors
            && self.expressible_error_fraction_at_least_0_70
            && self.exact_collision_fraction_at_most_0_10
            && self.at_least_three_target_classes_majority_expressible
            && self.duplicate_coverage_coordinate_proven
            && self.canonical_schema_unchanged
            && self.canonical_ledger_unchanged
            && self.blind_labels_not_read
    }
}

#[derive(Debug, Serialize)]
struct FeasibilityReceipt {
    contract: &'static str,
    architecture: &'static str,
    model_artifact: FileIdentity,
    phase_6_receipt: FileIdentity,
    phase_4_receipt: FileIdentity,
    phase_8_v2_receipt: FileIdentity,
    producer_binary: FileIdentity,
    thresholds: FeasibilityThresholds,
    overall: FeasibilityCounts,
    classes: Vec<ClassFeasibility>,
    feature_visibility: Vec<FeatureVisibility>,
    duplicate_coverage_coordinate: DuplicateCoverageCoordinate,
    coverage_weight: CoverageWeightAudit,
    target_classes_expressible: usize,
    gates: FeasibilityGates,
    authorize_phase_8_8_training: bool,
    canonical_rank_evidence_schema_changed: bool,
    canonical_ledger_changed: bool,
    active_engine_after_audit: &'static str,
}

#[derive(Debug, Serialize)]
pub struct FeasibilityPublication {
    contract: &'static str,
    output: FileIdentity,
    overall: FeasibilityCounts,
    target_classes_expressible: usize,
    gates: FeasibilityGates,
    authorize_phase_8_8_training: bool,
}

#[derive(Debug, Deserialize)]
struct FrozenPhase6 {
    contract: String,
    split: LeakageSplitV3,
    phase_6_verified: bool,
}

#[derive(Debug, Deserialize)]
struct FrozenPhase4 {
    contract: String,
    ledger: RelevanceLedgerV3,
    phase_4_verified: bool,
}

#[derive(Debug, Deserialize)]
struct FrozenPhase8V2 {
    contract: String,
    model_identity: [u8; 32],
    phase_8_verified: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn monotonic_cone_requires_at_least_one_positive_delta() {
        let positive = [0.0; RANK_EVIDENCE_V3_FEATURE_COUNT];
        assert!(matches!(
            classify_error(
                RelevanceTier::AdmissiblePartial,
                RelevanceTier::AdmissiblePartial,
                &positive,
                [2; 32],
                [1; 32]
            ),
            ErrorCategory::ScoreImpossible {
                exact_collision: true,
                ..
            }
        ));
        let mut mixed = [-0.1; RANK_EVIDENCE_V3_FEATURE_COUNT];
        mixed[3] = 0.1;
        assert!(matches!(
            classify_error(
                RelevanceTier::AdmissiblePartial,
                RelevanceTier::AdmissiblePartial,
                &mixed,
                [2; 32],
                [1; 32]
            ),
            ErrorCategory::ConeExpressible { .. }
        ));
    }

    #[test]
    fn worse_constitutional_tier_is_never_score_repairable() {
        assert!(matches!(
            classify_error(
                RelevanceTier::AdmissiblePartial,
                RelevanceTier::CompleteExpandedGroups,
                &[1.0; RANK_EVIDENCE_V3_FEATURE_COUNT],
                [1; 32],
                [2; 32]
            ),
            ErrorCategory::ConstitutionallyBlocked
        ));
    }
}
