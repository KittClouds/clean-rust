use phoenix_lexical_qps::{
    train_linear_ranker_v3, JudgmentIdentity, JudgmentReasonV3, LinearTrainingConfigV3,
    LinearTrainingReceiptV3, RankEvidenceV3, RelevanceTier,
};
use serde::{Deserialize, Serialize};

use super::locality::{
    complete_coverage_audit, select_configuration, CompleteCoverageAudit, DevelopmentSelection,
};
use super::*;

const CONTRACT: &str = "phoenix.memory.qps-v3-phase8.7-rarity-coverage-diagnostic/v3";
const PREFLIGHT_CONTRACT: &str = "phoenix.memory.qps-v3-phase8.7-rarity-coverage-preflight/v2";
const SIDECAR_CONTRACT: &str = "phoenix.qps.phase8.7-rarity-group-coverage-sidecar/v1";
const RELEASE_CONTRACT: &str =
    "phoenix.memory.qps-v3-phase8.7-release-rarity-group-coverage-sidecar/v1";
const RARITY_COVERAGE_SLOT: usize = RankEvidenceV3::MISSING_GROUP_ABSENCE;
const TARGETS: [JudgmentReasonV3; 5] = [
    JudgmentReasonV3::CommonTermDominance,
    JudgmentReasonV3::WrongConceptProximity,
    JudgmentReasonV3::PartialMatchSaturation,
    JudgmentReasonV3::DocumentConversationConfusion,
    JudgmentReasonV3::LongQueryFailure,
];

#[allow(clippy::too_many_arguments)]
pub(crate) fn diagnose(
    model_path: &Path,
    phase_6_path: &Path,
    phase_4_path: &Path,
    phase_3_path: &Path,
    graded_suite_path: &Path,
    canonical_phase_8_path: &Path,
    independent_ledger_path: &Path,
    independent_sidecar_path: &Path,
    release_sidecar_path: &Path,
    preflight_path: &Path,
    output_path: &Path,
) -> Result<Phase87Publication> {
    if output_path.exists() {
        bail!(
            "refusing to overwrite Phase 8.7 diagnostic {}",
            output_path.display()
        );
    }
    let artifact: LinearModelArtifactV3 = read_json(model_path, "Phase 7 model")?;
    let phase_6: FrozenPhase6 = read_json(phase_6_path, "Phase 6 receipt")?;
    let phase_4: FrozenPhase4 = read_json(phase_4_path, "Phase 4 receipt")?;
    let baseline_phase_3: FrozenPhase3 = read_json(phase_3_path, "Phase 3 receipt")?;
    let mut rarity_phase_3: FrozenPhase3 = read_json(phase_3_path, "Phase 3 receipt")?;
    let baseline_graded: GradedEvaluationSuiteV3 = read_json(graded_suite_path, "graded suite")?;
    let mut rarity_graded: GradedEvaluationSuiteV3 = read_json(graded_suite_path, "graded suite")?;
    let canonical: CanonicalPhase8 = read_json(canonical_phase_8_path, "canonical Phase 8")?;
    let independent: IndependentRarityCoverageSidecar = read_json(
        independent_sidecar_path,
        "independent rarity coverage sidecar",
    )?;
    let release: ReleaseRarityCoverageSidecar =
        read_json(release_sidecar_path, "release rarity coverage sidecar")?;
    let preflight: Phase87PreflightBinding = read_json(preflight_path, "Phase 8.7 preflight")?;
    validate_inputs(
        &artifact,
        &phase_6,
        &phase_4,
        &baseline_phase_3,
        &baseline_graded,
        &canonical,
        &independent,
        &release,
        &preflight,
        independent_sidecar_path,
        release_sidecar_path,
    )?;

    let original_ledger_identity =
        decode_hex_32(&sha256_bytes(&serde_json::to_vec(&phase_4.ledger)?))?;
    if original_ledger_identity != artifact.training_ledger_identity {
        bail!("Phase 8.7 source ledger is not the Phase 7 training ledger");
    }
    let independent_ledger_identity = file_identity(independent_ledger_path)?;
    let graded_identity = file_identity(graded_suite_path)?;
    if independent.canonical_ledger.sha256 != independent_ledger_identity.sha256
        || independent.canonical_graded_suite.sha256 != graded_identity.sha256
    {
        bail!("Phase 8.7 sidecar is not bound to supplied v9 artifacts");
    }

    let baseline = evaluate_all(
        &artifact.model_parameters,
        &phase_4.ledger,
        &phase_6.split,
        &baseline_phase_3,
        &baseline_graded,
    )?;
    if !baseline_matches(&baseline, &canonical) {
        bail!("Phase 8.7 baseline does not reproduce canonical Phase 8");
    }

    let mut rarity_ledger = phase_4.ledger.clone();
    let projection = project_ledger(&mut rarity_ledger, &independent)?;
    let graded_projection = project_graded(&mut rarity_graded, &independent)?;
    let release_projection = project_release(&mut rarity_phase_3, &release)?;
    rarity_ledger.validate().map_err(anyhow::Error::msg)?;
    rarity_graded.validate()?;

    let rarity_ledger_identity =
        decode_hex_32(&sha256_bytes(&serde_json::to_vec(&rarity_ledger)?))?;
    let (selected_config, configurations_evaluated, development) =
        select_configuration(&rarity_ledger, &phase_6.split, rarity_ledger_identity)?;
    let first = train_linear_ranker_v3(
        &rarity_ledger,
        &phase_6.split,
        rarity_ledger_identity,
        selected_config,
    )
    .map_err(anyhow::Error::msg)?;
    let second = train_linear_ranker_v3(
        &rarity_ledger,
        &phase_6.split,
        rarity_ledger_identity,
        selected_config,
    )
    .map_err(anyhow::Error::msg)?;
    let challenger = evaluate_all(
        &first.0,
        &rarity_ledger,
        &phase_6.split,
        &rarity_phase_3,
        &rarity_graded,
    )?;
    let targeted = targeted_residuals(&baseline, &challenger);
    let complete_coverage = complete_coverage_audit(
        &phase_4.ledger,
        &rarity_ledger,
        &phase_6.split,
        &artifact.model_parameters,
        &first.0,
    );
    let conclusion = conclusion(&baseline, &challenger, &targeted, complete_coverage);
    let gates = Phase87Gates {
        preflight_authorized_training: preflight.conclusion.authorize_phase_8_7b_learner_diagnostic,
        baseline_reproduces_canonical_phase_8: true,
        independent_ledger_byte_identical_to_v9: independent.canonical_ledger.sha256
            == "a28f906d13446e4c5c0b627bc6400e5112a48d413105d229fe053fefc92b35d8",
        independent_graded_byte_identical_to_v9: independent.canonical_graded_suite.sha256
            == "d9be32daca38e0b4cefd2680447ebeb5e8e6f5021c8f789917e468f9704af02b",
        all_active_labels_projected: projection.active_judgments == projection.projected_judgments,
        all_graded_candidates_projected: graded_projection.missing_candidates == 0,
        all_release_candidates_projected: release_projection.missing_candidates == 0,
        v2_release_substrate_bit_identical: release.gates.all_pass(),
        rarity_coverage_finite_and_bounded: projection.rarity_coverage_finite_and_bounded
            && graded_projection.rarity_coverage_finite_and_bounded
            && release_projection.rarity_coverage_finite_and_bounded,
        deterministic_training: first == second,
        monotonic_nonnegative_weights: first.0.weights.iter().all(|weight| *weight >= 0.0),
        canonical_schema_and_ledger_unchanged: true,
        production_promotion_forbidden: true,
    };
    if !gates.all_pass() {
        bail!("Phase 8.7 integrity gates failed: {gates:?}");
    }
    let receipt = Phase87Receipt {
        contract: CONTRACT,
        architecture:
            "diagnostic_only_slot_8_rarity_weighted_group_coverage_over_frozen_v2_substrate",
        group_weight:
            "max_over_resolved_expansions(expansion_quality_times_normalized_term_rarity)",
        candidate_numerator: "sum_candidate_independent_weights_of_matched_groups",
        candidate_expansion_quality_in_numerator: false,
        replaced_coordinate: RARITY_COVERAGE_SLOT,
        replaced_feature: "missing_group_absence",
        experimental_feature: "rarity_weighted_group_coverage",
        model_artifact: file_identity(model_path)?,
        phase_6_receipt: file_identity(phase_6_path)?,
        phase_4_receipt: file_identity(phase_4_path)?,
        phase_3_receipt: file_identity(phase_3_path)?,
        graded_suite: graded_identity,
        independent_ledger: independent_ledger_identity,
        independent_rarity_coverage_sidecar: file_identity(independent_sidecar_path)?,
        release_rarity_coverage_sidecar: file_identity(release_sidecar_path)?,
        preflight_receipt: file_identity(preflight_path)?,
        canonical_phase_8_receipt: file_identity(canonical_phase_8_path)?,
        producer_binary: current_binary_identity()?,
        projection,
        graded_projection,
        release_projection,
        selected_config,
        configurations_evaluated,
        development,
        training_receipt: first.1,
        diagnostic_model: first.0,
        baseline,
        challenger,
        targeted_residuals: targeted,
        complete_coverage,
        conclusion,
        gates,
        canonical_rank_evidence_schema_changed: false,
        canonical_ledger_changed: false,
        production_promotion_authorized: false,
        active_engine_after_diagnostic: "V2 active",
    };
    write_json_atomic(output_path, &receipt)?;
    Ok(Phase87Publication {
        contract: CONTRACT,
        output: file_identity(output_path)?,
        diagnostic_model_identity: receipt.diagnostic_model.identity(),
        conclusion,
        production_promotion_authorized: false,
        active_engine_after_diagnostic: "V2 active",
    })
}

#[allow(clippy::too_many_arguments)]
fn validate_inputs(
    artifact: &LinearModelArtifactV3,
    phase_6: &FrozenPhase6,
    phase_4: &FrozenPhase4,
    phase_3: &FrozenPhase3,
    graded: &GradedEvaluationSuiteV3,
    canonical: &CanonicalPhase8,
    independent: &IndependentRarityCoverageSidecar,
    release: &ReleaseRarityCoverageSidecar,
    preflight: &Phase87PreflightBinding,
    independent_sidecar_path: &Path,
    release_sidecar_path: &Path,
) -> Result<()> {
    if !artifact.validate_challenger()
        || !phase_6.phase_6_verified
        || !phase_4.phase_4_verified
        || !phase_3.phase_3_verified
        || canonical.phase_8_verified
    {
        bail!("Phase 8.7 requires verified 4/6/7 inputs and blocked Phase 8");
    }
    graded.validate()?;
    if independent.contract != SIDECAR_CONTRACT
        || independent.replaced_canonical_coordinate != RARITY_COVERAGE_SLOT
        || independent.experimental_feature != "rarity_weighted_group_coverage"
        || release.contract != RELEASE_CONTRACT
        || !release.gates.all_pass()
        || preflight.contract != PREFLIGHT_CONTRACT
        || !preflight.conclusion.authorize_phase_8_7b_learner_diagnostic
    {
        bail!("Phase 8.7 learner was not authorized by valid preflight evidence");
    }
    if preflight.independent_rarity_coverage_sidecar.sha256
        != file_identity(independent_sidecar_path)?.sha256
        || preflight.release_rarity_coverage_sidecar.sha256
            != file_identity(release_sidecar_path)?.sha256
    {
        bail!("Phase 8.7 preflight does not bind the supplied sidecars");
    }
    Ok(())
}

fn project_ledger(
    ledger: &mut RelevanceLedgerV3,
    sidecar: &IndependentRarityCoverageSidecar,
) -> Result<LedgerProjection> {
    let records = sidecar
        .pairs
        .iter()
        .map(|pair| (pair.judgment_identity.as_str(), pair))
        .collect::<HashMap<_, _>>();
    let mut root_by_identity = HashMap::<JudgmentIdentity, JudgmentIdentity>::new();
    for judgment in &ledger.judgments {
        let root = judgment
            .supersedes
            .and_then(|parent| root_by_identity.get(&parent).copied())
            .unwrap_or(judgment.identity);
        root_by_identity.insert(judgment.identity, root);
    }
    let active = ledger.active_model_training_indices();
    let mut projection = LedgerProjection {
        active_judgments: active.len(),
        rarity_coverage_finite_and_bounded: true,
        ..LedgerProjection::default()
    };
    for index in active {
        let judgment = &mut ledger.judgments[index];
        let root = root_by_identity
            .get(&judgment.identity)
            .context("active judgment root missing")?;
        let root_hex = hex(root.as_bytes());
        let pair = records
            .get(root_hex.as_str())
            .with_context(|| format!("missing rarity coverage for active root {root_hex}"))?;
        if hex(judgment.query_identity.as_bytes()) != pair.query_identity {
            bail!("rarity coverage root query identity mismatch");
        }
        let current_positive = hex(judgment.positive_document_version.as_bytes());
        let current_negative = hex(judgment.negative_document_version.as_bytes());
        let (positive, negative, reversed) =
            orient_pair(pair, &current_positive, &current_negative)?;
        projection.reversed_preferences += usize::from(reversed);
        projection.nonzero_pair_deltas += usize::from((positive - negative).abs() > 1.0e-6);
        projection.rarity_coverage_finite_and_bounded &= valid(positive) && valid(negative);
        judgment.positive_features.values[RARITY_COVERAGE_SLOT] = positive;
        judgment.negative_features.values[RARITY_COVERAGE_SLOT] = negative;
        projection.projected_judgments += 1;
    }
    Ok(projection)
}

fn orient_pair(
    pair: &PairRarityCoverage,
    current_positive: &str,
    current_negative: &str,
) -> Result<(f32, f32, bool)> {
    if current_positive == pair.positive_document_version
        && current_negative == pair.negative_document_version
    {
        Ok((
            pair.positive_rarity_weighted_group_coverage,
            pair.negative_rarity_weighted_group_coverage,
            false,
        ))
    } else if current_positive == pair.negative_document_version
        && current_negative == pair.positive_document_version
    {
        Ok((
            pair.negative_rarity_weighted_group_coverage,
            pair.positive_rarity_weighted_group_coverage,
            true,
        ))
    } else {
        bail!("active reviewed pair diverged from its mined root")
    }
}

fn project_graded(
    graded: &mut GradedEvaluationSuiteV3,
    sidecar: &IndependentRarityCoverageSidecar,
) -> Result<CandidateProjection> {
    let queries = sidecar
        .graded_queries
        .iter()
        .map(|query| (query.query_identity.as_str(), query))
        .collect::<HashMap<_, _>>();
    let mut projection = CandidateProjection {
        rarity_coverage_finite_and_bounded: true,
        ..CandidateProjection::default()
    };
    for query in &mut graded.queries {
        let Some(source) = queries.get(query.query_identity.as_str()) else {
            projection.missing_queries += 1;
            projection.missing_candidates += query.candidates.len();
            continue;
        };
        let candidates = source
            .candidates
            .iter()
            .map(|candidate| {
                (
                    (candidate.document_identity.as_str(), candidate.v2_order),
                    candidate,
                )
            })
            .collect::<HashMap<_, _>>();
        for candidate in &mut query.candidates {
            projection.candidates += 1;
            let Some(source) =
                candidates.get(&(candidate.document_identity.as_str(), candidate.v2_order))
            else {
                projection.missing_candidates += 1;
                continue;
            };
            if source.relevance_tier != candidate.relevance_tier {
                bail!("graded rarity coverage candidate changed V2 substrate");
            }
            projection.rarity_coverage_finite_and_bounded &=
                valid(source.rarity_weighted_group_coverage);
            candidate.rank_evidence_v3.values[RARITY_COVERAGE_SLOT] =
                source.rarity_weighted_group_coverage;
            projection.projected_candidates += 1;
        }
    }
    Ok(projection)
}

fn project_release(
    phase_3: &mut FrozenPhase3,
    sidecar: &ReleaseRarityCoverageSidecar,
) -> Result<CandidateProjection> {
    let mut projection = CandidateProjection {
        rarity_coverage_finite_and_bounded: true,
        ..CandidateProjection::default()
    };
    project_release_cohort(&mut phase_3.mixed_suite, &sidecar.mixed, &mut projection)?;
    project_release_cohort(
        &mut phase_3.longmemeval_release,
        &sidecar.longmemeval,
        &mut projection,
    )?;
    Ok(projection)
}

fn project_release_cohort(
    cohort: &mut FrozenCohort,
    sidecar: &ReleaseRarityCoverageCohort,
    projection: &mut CandidateProjection,
) -> Result<()> {
    let queries = sidecar
        .queries
        .iter()
        .map(|query| (query.query_identity.as_str(), query))
        .collect::<HashMap<_, _>>();
    for query in &mut cohort.queries {
        let Some(source) = queries.get(query.query_identity.as_str()) else {
            projection.missing_queries += 1;
            projection.missing_candidates += query.candidate_pool.len();
            continue;
        };
        let candidates = source
            .candidates
            .iter()
            .map(|candidate| {
                (
                    (candidate.document_identity.as_str(), candidate.v2_order),
                    candidate,
                )
            })
            .collect::<HashMap<_, _>>();
        for candidate in &mut query.candidate_pool {
            projection.candidates += 1;
            let Some(source) =
                candidates.get(&(candidate.document_identity.as_str(), candidate.v2_order))
            else {
                projection.missing_candidates += 1;
                continue;
            };
            if source.relevance_tier != candidate.relevance_tier {
                bail!("release rarity coverage candidate changed V2 substrate");
            }
            projection.rarity_coverage_finite_and_bounded &=
                valid(source.rarity_weighted_group_coverage);
            candidate.rank_evidence_v3.values[RARITY_COVERAGE_SLOT] =
                source.rarity_weighted_group_coverage;
            projection.projected_candidates += 1;
        }
    }
    Ok(())
}

fn targeted_residuals(
    baseline: &ModelEvaluation,
    challenger: &ModelEvaluation,
) -> Vec<TargetedResidual> {
    let baseline_by_reason = baseline
        .blind
        .classes
        .iter()
        .map(|class| (class.reason, class.evaluation))
        .collect::<HashMap<_, _>>();
    let challenger_by_reason = challenger
        .blind
        .classes
        .iter()
        .map(|class| (class.reason, class.evaluation))
        .collect::<HashMap<_, _>>();
    TARGETS
        .into_iter()
        .map(|reason| {
            let baseline = baseline_by_reason.get(&reason).copied().unwrap_or_default();
            let challenger = challenger_by_reason
                .get(&reason)
                .copied()
                .unwrap_or_default();
            TargetedResidual {
                reason,
                judgments: challenger.judgments,
                baseline_accuracy: baseline.model_accuracy,
                challenger_accuracy: challenger.model_accuracy,
                absolute_change: challenger.model_accuracy - baseline.model_accuracy,
            }
        })
        .collect()
}

fn conclusion(
    baseline: &ModelEvaluation,
    challenger: &ModelEvaluation,
    targeted: &[TargetedResidual],
    complete: CompleteCoverageAudit,
) -> RarityCoverageConclusion {
    let improved_targets = targeted
        .iter()
        .filter(|value| value.absolute_change > 0.0)
        .count();
    let global_quality_material = challenger.longmemeval.model.mean_reciprocal_rank
        >= baseline.longmemeval.model.mean_reciprocal_rank + 0.003
        || challenger.graded.ndcg_improvement >= baseline.graded.ndcg_improvement + 0.01;
    let targeted_effect_material = improved_targets >= 3;
    let targeted_regression_safe = targeted.iter().all(|value| value.absolute_change >= -0.005);
    let complete_coverage_safe = complete.absolute_change >= -0.005
        && challenger.mixed.model.mean_reciprocal_rank >= baseline.mixed.model.mean_reciprocal_rank;
    let migration_earned = migration_earned(
        global_quality_material,
        targeted_effect_material,
        targeted_regression_safe,
        complete_coverage_safe,
    );
    RarityCoverageConclusion {
        outcome: if migration_earned {
            "rarity_coverage_materially_explains_residuals"
        } else if global_quality_material && !targeted_effect_material {
            "rarity_coverage_improves_aggregate_quality_without_targeted_transfer"
        } else if global_quality_material && !targeted_regression_safe {
            "rarity_coverage_improves_aggregate_quality_but_harms_targeted_classes"
        } else if global_quality_material {
            "rarity_coverage_improves_aggregate_quality_but_fails_safety"
        } else {
            "rarity_coverage_does_not_materially_explain_residuals"
        },
        improved_target_classes: improved_targets,
        global_quality_material,
        targeted_effect_material,
        targeted_regression_safe,
        complete_coverage_safe,
        authorize_phase_8_7c_schema_migration: migration_earned,
        next_action: if migration_earned {
            "formalize_schema_and_run_append_only_legacy_migration"
        } else {
            "stop_schema_migration_and_analyze_why_pair_signal_does_not_transfer"
        },
    }
}

fn migration_earned(
    global_quality_material: bool,
    targeted_effect_material: bool,
    targeted_regression_safe: bool,
    complete_coverage_safe: bool,
) -> bool {
    global_quality_material
        && targeted_effect_material
        && targeted_regression_safe
        && complete_coverage_safe
}

#[inline]
fn valid(value: f32) -> bool {
    value.is_finite() && (0.0..=1.0).contains(&value)
}

fn hex<const N: usize>(bytes: [u8; N]) -> String {
    bytes.iter().map(|value| format!("{value:02x}")).collect()
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
struct LedgerProjection {
    active_judgments: usize,
    projected_judgments: usize,
    reversed_preferences: usize,
    nonzero_pair_deltas: usize,
    rarity_coverage_finite_and_bounded: bool,
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
struct CandidateProjection {
    candidates: usize,
    projected_candidates: usize,
    missing_queries: usize,
    missing_candidates: usize,
    rarity_coverage_finite_and_bounded: bool,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct TargetedResidual {
    reason: JudgmentReasonV3,
    judgments: usize,
    baseline_accuracy: f64,
    challenger_accuracy: f64,
    absolute_change: f64,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct RarityCoverageConclusion {
    outcome: &'static str,
    improved_target_classes: usize,
    global_quality_material: bool,
    targeted_effect_material: bool,
    targeted_regression_safe: bool,
    complete_coverage_safe: bool,
    authorize_phase_8_7c_schema_migration: bool,
    next_action: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct Phase87Gates {
    preflight_authorized_training: bool,
    baseline_reproduces_canonical_phase_8: bool,
    independent_ledger_byte_identical_to_v9: bool,
    independent_graded_byte_identical_to_v9: bool,
    all_active_labels_projected: bool,
    all_graded_candidates_projected: bool,
    all_release_candidates_projected: bool,
    v2_release_substrate_bit_identical: bool,
    rarity_coverage_finite_and_bounded: bool,
    deterministic_training: bool,
    monotonic_nonnegative_weights: bool,
    canonical_schema_and_ledger_unchanged: bool,
    production_promotion_forbidden: bool,
}

impl Phase87Gates {
    fn all_pass(self) -> bool {
        self.preflight_authorized_training
            && self.baseline_reproduces_canonical_phase_8
            && self.independent_ledger_byte_identical_to_v9
            && self.independent_graded_byte_identical_to_v9
            && self.all_active_labels_projected
            && self.all_graded_candidates_projected
            && self.all_release_candidates_projected
            && self.v2_release_substrate_bit_identical
            && self.rarity_coverage_finite_and_bounded
            && self.deterministic_training
            && self.monotonic_nonnegative_weights
            && self.canonical_schema_and_ledger_unchanged
            && self.production_promotion_forbidden
    }
}

#[derive(Debug, Serialize)]
struct Phase87Receipt {
    contract: &'static str,
    architecture: &'static str,
    group_weight: &'static str,
    candidate_numerator: &'static str,
    candidate_expansion_quality_in_numerator: bool,
    replaced_coordinate: usize,
    replaced_feature: &'static str,
    experimental_feature: &'static str,
    model_artifact: FileIdentity,
    phase_6_receipt: FileIdentity,
    phase_4_receipt: FileIdentity,
    phase_3_receipt: FileIdentity,
    graded_suite: FileIdentity,
    independent_ledger: FileIdentity,
    independent_rarity_coverage_sidecar: FileIdentity,
    release_rarity_coverage_sidecar: FileIdentity,
    preflight_receipt: FileIdentity,
    canonical_phase_8_receipt: FileIdentity,
    producer_binary: FileIdentity,
    projection: LedgerProjection,
    graded_projection: CandidateProjection,
    release_projection: CandidateProjection,
    selected_config: LinearTrainingConfigV3,
    configurations_evaluated: usize,
    development: DevelopmentSelection,
    training_receipt: LinearTrainingReceiptV3,
    diagnostic_model: LinearRankerV3,
    baseline: ModelEvaluation,
    challenger: ModelEvaluation,
    targeted_residuals: Vec<TargetedResidual>,
    complete_coverage: CompleteCoverageAudit,
    conclusion: RarityCoverageConclusion,
    gates: Phase87Gates,
    canonical_rank_evidence_schema_changed: bool,
    canonical_ledger_changed: bool,
    production_promotion_authorized: bool,
    active_engine_after_diagnostic: &'static str,
}

#[derive(Debug, Serialize)]
pub(crate) struct Phase87Publication {
    contract: &'static str,
    output: FileIdentity,
    diagnostic_model_identity: [u8; 32],
    conclusion: RarityCoverageConclusion,
    production_promotion_authorized: bool,
    active_engine_after_diagnostic: &'static str,
}

#[derive(Debug, Deserialize)]
struct IndependentRarityCoverageSidecar {
    contract: String,
    replaced_canonical_coordinate: usize,
    experimental_feature: String,
    canonical_ledger: InputFileIdentity,
    canonical_graded_suite: InputFileIdentity,
    pairs: Vec<PairRarityCoverage>,
    graded_queries: Vec<GradedRarityCoverageQuery>,
}

#[derive(Debug, Deserialize)]
struct PairRarityCoverage {
    judgment_identity: String,
    query_identity: String,
    positive_document_version: String,
    negative_document_version: String,
    positive_rarity_weighted_group_coverage: f32,
    negative_rarity_weighted_group_coverage: f32,
}

#[derive(Debug, Deserialize)]
struct GradedRarityCoverageQuery {
    query_identity: String,
    candidates: Vec<GradedRarityCoverageCandidate>,
}

#[derive(Debug, Deserialize)]
struct GradedRarityCoverageCandidate {
    document_identity: String,
    v2_order: usize,
    rarity_weighted_group_coverage: f32,
    relevance_tier: RelevanceTier,
}

#[derive(Debug, Deserialize)]
struct ReleaseRarityCoverageSidecar {
    contract: String,
    mixed: ReleaseRarityCoverageCohort,
    longmemeval: ReleaseRarityCoverageCohort,
    gates: ReleaseSidecarGates,
}

#[derive(Debug, Deserialize)]
struct ReleaseRarityCoverageCohort {
    queries: Vec<ReleaseRarityCoverageQuery>,
}

#[derive(Debug, Deserialize)]
struct ReleaseRarityCoverageQuery {
    query_identity: String,
    candidates: Vec<ReleaseRarityCoverageCandidate>,
}

#[derive(Debug, Deserialize)]
struct ReleaseRarityCoverageCandidate {
    document_identity: String,
    v2_order: usize,
    relevance_tier: RelevanceTier,
    rarity_weighted_group_coverage: f32,
}

#[derive(Debug, Deserialize)]
struct ReleaseSidecarGates {
    phase_3_verified: bool,
    mixed: ReleaseCohortParity,
    longmemeval: ReleaseCohortParity,
    rarity_coverage_is_finite_and_bounded: bool,
}

impl ReleaseSidecarGates {
    fn all_pass(&self) -> bool {
        self.phase_3_verified
            && self.mixed.all_pass()
            && self.longmemeval.all_pass()
            && self.rarity_coverage_is_finite_and_bounded
    }
}

#[derive(Debug, Deserialize)]
struct ReleaseCohortParity {
    query_count_equal: bool,
    candidate_pool_identity_equal: bool,
    v2_order_equal: bool,
    v2_score_bits_equal: bool,
    canonical_rank_evidence_equal: bool,
    relevance_tier_equal: bool,
}

impl ReleaseCohortParity {
    fn all_pass(&self) -> bool {
        self.query_count_equal
            && self.candidate_pool_identity_equal
            && self.v2_order_equal
            && self.v2_score_bits_equal
            && self.canonical_rank_evidence_equal
            && self.relevance_tier_equal
    }
}

#[derive(Debug, Deserialize)]
struct InputFileIdentity {
    sha256: String,
}

#[derive(Debug, Deserialize)]
struct Phase87PreflightBinding {
    contract: String,
    independent_rarity_coverage_sidecar: InputFileIdentity,
    release_rarity_coverage_sidecar: InputFileIdentity,
    conclusion: Phase87PreflightConclusionBinding,
}

#[derive(Debug, Deserialize)]
struct Phase87PreflightConclusionBinding {
    authorize_phase_8_7b_learner_diagnostic: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn aggregate_gain_cannot_authorize_schema_migration_by_itself() {
        assert!(!migration_earned(true, false, false, true));
        assert!(!migration_earned(true, true, false, true));
        assert!(migration_earned(true, true, true, true));
    }
}
