use phoenix_lexical_qps::{
    train_linear_ranker_v3, JudgmentIdentity, LinearTrainingConfigV3, LinearTrainingReceiptV3,
    PrimarySplitV3,
};

use super::*;

const CONTRACT: &str = "phoenix.memory.qps-v3-phase8.6-locality-diagnostic/v1";
const LOCALITY_SLOT: usize = RankEvidenceV3::MISSING_GROUP_ABSENCE;

#[allow(clippy::too_many_arguments)]
pub(crate) fn diagnose(
    model_path: &Path,
    phase_6_path: &Path,
    phase_4_path: &Path,
    phase_3_path: &Path,
    graded_suite_path: &Path,
    canonical_phase_8_path: &Path,
    independent_ledger_path: &Path,
    independent_locality_path: &Path,
    release_locality_path: &Path,
    output_path: &Path,
) -> Result<Phase86Publication> {
    if output_path.exists() {
        bail!(
            "refusing to overwrite Phase 8.6 receipt {}",
            output_path.display()
        );
    }
    let artifact: LinearModelArtifactV3 = read_json(model_path, "Phase 7 model")?;
    let phase_6: FrozenPhase6 = read_json(phase_6_path, "Phase 6 receipt")?;
    let phase_4: FrozenPhase4 = read_json(phase_4_path, "Phase 4 receipt")?;
    let baseline_phase_3: FrozenPhase3 = read_json(phase_3_path, "Phase 3 receipt")?;
    let mut locality_phase_3: FrozenPhase3 = read_json(phase_3_path, "Phase 3 receipt")?;
    let baseline_graded: GradedEvaluationSuiteV3 = read_json(graded_suite_path, "graded suite")?;
    let mut locality_graded: GradedEvaluationSuiteV3 =
        read_json(graded_suite_path, "graded suite")?;
    let canonical: CanonicalPhase8 = read_json(canonical_phase_8_path, "canonical Phase 8")?;
    let independent: IndependentLocalitySidecar =
        read_json(independent_locality_path, "independent locality sidecar")?;
    let release: ReleaseLocalitySidecar =
        read_json(release_locality_path, "release locality sidecar")?;
    validate_inputs(
        &artifact,
        &phase_6,
        &phase_4,
        &baseline_phase_3,
        &baseline_graded,
        &canonical,
        &independent,
        &release,
    )?;

    let original_ledger_identity =
        decode_hex_32(&sha256_bytes(&serde_json::to_vec(&phase_4.ledger)?))?;
    if original_ledger_identity != artifact.training_ledger_identity {
        bail!("Phase 8.6 source ledger is not the Phase 7 training ledger");
    }
    let independent_ledger_identity = file_identity(independent_ledger_path)?;
    let graded_identity = file_identity(graded_suite_path)?;
    if independent.canonical_ledger.sha256 != independent_ledger_identity.sha256
        || independent.canonical_graded_suite.sha256 != graded_identity.sha256
    {
        bail!("independent locality sidecar is not bound to the supplied v9 artifacts");
    }

    let baseline = evaluate_all(
        &artifact.model_parameters,
        &phase_4.ledger,
        &phase_6.split,
        &baseline_phase_3,
        &baseline_graded,
    )?;
    if !baseline_matches(&baseline, &canonical) {
        bail!("Phase 8.6 baseline does not reproduce canonical Phase 8");
    }

    let mut locality_ledger = phase_4.ledger.clone();
    let projection = project_ledger(&mut locality_ledger, &independent)?;
    let graded_projection = project_graded(&mut locality_graded, &independent)?;
    let release_projection = project_release(&mut locality_phase_3, &release)?;
    locality_ledger.validate().map_err(anyhow::Error::msg)?;
    locality_graded.validate()?;

    let locality_ledger_identity =
        decode_hex_32(&sha256_bytes(&serde_json::to_vec(&locality_ledger)?))?;
    let (selected_config, configurations_evaluated, development) =
        select_configuration(&locality_ledger, &phase_6.split, locality_ledger_identity)?;
    let first = train_linear_ranker_v3(
        &locality_ledger,
        &phase_6.split,
        locality_ledger_identity,
        selected_config,
    )
    .map_err(anyhow::Error::msg)?;
    let second = train_linear_ranker_v3(
        &locality_ledger,
        &phase_6.split,
        locality_ledger_identity,
        selected_config,
    )
    .map_err(anyhow::Error::msg)?;
    let challenger = evaluate_all(
        &first.0,
        &locality_ledger,
        &phase_6.split,
        &locality_phase_3,
        &locality_graded,
    )?;
    let targeted = targeted_residuals(&baseline, &challenger);
    let complete_coverage = complete_coverage_audit(
        &phase_4.ledger,
        &locality_ledger,
        &phase_6.split,
        &artifact.model_parameters,
        &first.0,
    );
    let conclusion = conclusion(&baseline, &challenger, &targeted, complete_coverage);
    let gates = Phase86Gates {
        baseline_reproduces_canonical_phase_8: true,
        independent_ledger_byte_identical_to_v9: independent.canonical_ledger.sha256
            == "a28f906d13446e4c5c0b627bc6400e5112a48d413105d229fe053fefc92b35d8",
        independent_graded_byte_identical_to_v9: independent.canonical_graded_suite.sha256
            == "d9be32daca38e0b4cefd2680447ebeb5e8e6f5021c8f789917e468f9704af02b",
        all_active_labels_projected: projection.active_judgments == projection.projected_judgments,
        all_graded_candidates_projected: graded_projection.missing_candidates == 0,
        all_release_candidates_projected: release_projection.missing_candidates == 0,
        v2_release_substrate_bit_identical: release.gates.all_pass(),
        locality_finite_and_bounded: projection.locality_finite_and_bounded
            && graded_projection.locality_finite_and_bounded
            && release_projection.locality_finite_and_bounded,
        deterministic_training: first == second,
        monotonic_nonnegative_weights: first.0.weights.iter().all(|weight| *weight >= 0.0),
        production_promotion_forbidden: true,
    };
    if !gates.all_pass() {
        bail!("Phase 8.6 integrity gates failed: {gates:?}");
    }
    let receipt = Phase86Receipt {
        contract: CONTRACT,
        architecture: "diagnostic_only_slot_8_locality_over_frozen_v2_substrate",
        replaced_coordinate: LOCALITY_SLOT,
        replaced_feature: "missing_group_absence",
        experimental_feature: "matched_group_locality",
        model_artifact: file_identity(model_path)?,
        phase_6_receipt: file_identity(phase_6_path)?,
        phase_4_receipt: file_identity(phase_4_path)?,
        phase_3_receipt: file_identity(phase_3_path)?,
        graded_suite: graded_identity,
        independent_ledger: independent_ledger_identity,
        independent_locality_sidecar: file_identity(independent_locality_path)?,
        release_locality_sidecar: file_identity(release_locality_path)?,
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
        production_promotion_authorized: false,
        active_engine_after_diagnostic: "V2 active",
    };
    write_json_atomic(output_path, &receipt)?;
    Ok(Phase86Publication {
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
    independent: &IndependentLocalitySidecar,
    release: &ReleaseLocalitySidecar,
) -> Result<()> {
    if !artifact.validate_challenger()
        || !phase_6.phase_6_verified
        || !phase_4.phase_4_verified
        || !phase_3.phase_3_verified
        || canonical.phase_8_verified
    {
        bail!("Phase 8.6 requires the verified 4/6/7 inputs and blocked Phase 8");
    }
    graded.validate()?;
    if independent.contract != "phoenix.qps.phase8.6-locality-sidecar/v1"
        || independent.replaced_canonical_coordinate != LOCALITY_SLOT
        || independent.experimental_feature != "matched_group_locality"
        || release.contract != "phoenix.memory.qps-v3-phase8.6-release-locality-sidecar/v1"
        || !release.gates.all_pass()
    {
        bail!("invalid Phase 8.6 locality sidecar contract");
    }
    Ok(())
}

fn project_ledger(
    ledger: &mut RelevanceLedgerV3,
    sidecar: &IndependentLocalitySidecar,
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
        locality_finite_and_bounded: true,
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
            .with_context(|| format!("missing locality for active root {root_hex}"))?;
        if hex(judgment.query_identity.as_bytes()) != pair.query_identity {
            bail!("locality root query identity mismatch");
        }
        let current_positive = hex(judgment.positive_document_version.as_bytes());
        let current_negative = hex(judgment.negative_document_version.as_bytes());
        let (positive, negative, reversed) = if current_positive == pair.positive_document_version
            && current_negative == pair.negative_document_version
        {
            (pair.positive_locality, pair.negative_locality, false)
        } else if current_positive == pair.negative_document_version
            && current_negative == pair.positive_document_version
        {
            (pair.negative_locality, pair.positive_locality, true)
        } else {
            bail!("active reviewed pair diverged from its mined root");
        };
        projection.reversed_preferences += usize::from(reversed);
        projection.nonzero_pair_deltas += usize::from(positive.to_bits() != negative.to_bits());
        projection.locality_finite_and_bounded &=
            valid_locality(positive) && valid_locality(negative);
        judgment.positive_features.values[LOCALITY_SLOT] = positive;
        judgment.negative_features.values[LOCALITY_SLOT] = negative;
        projection.projected_judgments += 1;
    }
    Ok(projection)
}

fn project_graded(
    graded: &mut GradedEvaluationSuiteV3,
    sidecar: &IndependentLocalitySidecar,
) -> Result<CandidateProjection> {
    let queries = sidecar
        .graded_queries
        .iter()
        .map(|query| (query.query_identity.as_str(), query))
        .collect::<HashMap<_, _>>();
    let mut projection = CandidateProjection {
        locality_finite_and_bounded: true,
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
                bail!("graded locality candidate changed V2 substrate");
            }
            projection.locality_finite_and_bounded &= valid_locality(source.matched_group_locality);
            candidate.rank_evidence_v3.values[LOCALITY_SLOT] = source.matched_group_locality;
            projection.projected_candidates += 1;
        }
    }
    Ok(projection)
}

fn project_release(
    phase_3: &mut FrozenPhase3,
    sidecar: &ReleaseLocalitySidecar,
) -> Result<CandidateProjection> {
    let mut projection = CandidateProjection {
        locality_finite_and_bounded: true,
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
    sidecar: &ReleaseLocalityCohort,
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
                bail!("release locality candidate changed V2 substrate");
            }
            projection.locality_finite_and_bounded &= valid_locality(source.matched_group_locality);
            candidate.rank_evidence_v3.values[LOCALITY_SLOT] = source.matched_group_locality;
            projection.projected_candidates += 1;
        }
    }
    Ok(())
}

pub(super) fn select_configuration(
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    ledger_identity: [u8; 32],
) -> Result<(LinearTrainingConfigV3, usize, DevelopmentSelection)> {
    const EPOCHS: [u16; 6] = [16, 32, 64, 128, 256, 512];
    const LEARNING_RATES: [f32; 4] = [0.005, 0.01, 0.025, 0.05];
    const L2_PENALTIES: [f32; 2] = [0.0001, 0.001];
    let mut best = None::<(LinearTrainingConfigV3, DevelopmentSelection, f32)>;
    let mut evaluated = 0;
    for epochs in EPOCHS {
        for learning_rate in LEARNING_RATES {
            for l2_penalty in L2_PENALTIES {
                let config = LinearTrainingConfigV3 {
                    epochs,
                    learning_rate,
                    l2_penalty,
                };
                let trained = train_linear_ranker_v3(ledger, split, ledger_identity, config)
                    .map_err(anyhow::Error::msg)?;
                let development = development_evaluation(&trained.0, ledger, split);
                evaluated += 1;
                if best.as_ref().is_none_or(|(_, prior, loss)| {
                    development.accuracy > prior.accuracy
                        || (development.accuracy == prior.accuracy
                            && trained.1.final_pairwise_loss < *loss)
                }) {
                    best = Some((config, development, trained.1.final_pairwise_loss));
                }
            }
        }
    }
    best.map(|(config, development, _)| (config, evaluated, development))
        .context("Phase 8.6 development grid produced no model")
}

fn development_evaluation(
    model: &LinearRankerV3,
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
) -> DevelopmentSelection {
    let assignments = split
        .assignments
        .iter()
        .map(|value| (value.judgment_identity, value.primary_split))
        .collect::<HashMap<_, _>>();
    let mut evaluation = DevelopmentSelection::default();
    for judgment in ledger
        .active_model_training_judgments()
        .into_iter()
        .filter(|judgment| {
            assignments.get(&judgment.identity) == Some(&PrimarySplitV3::Development)
        })
    {
        evaluation.judgments += 1;
        evaluation.correctly_ordered += usize::from(
            model
                .score(judgment.positive_features)
                .unwrap_or(f32::NEG_INFINITY)
                > model
                    .score(judgment.negative_features)
                    .unwrap_or(f32::NEG_INFINITY),
        );
    }
    evaluation.accuracy = evaluation.correctly_ordered as f32 / evaluation.judgments.max(1) as f32;
    evaluation
}

fn targeted_residuals(
    baseline: &ModelEvaluation,
    challenger: &ModelEvaluation,
) -> Vec<TargetedResidual> {
    const TARGETS: [JudgmentReasonV3; 7] = [
        JudgmentReasonV3::PhraseOrderFailure,
        JudgmentReasonV3::PartialMatchSaturation,
        JudgmentReasonV3::DocumentConversationConfusion,
        JudgmentReasonV3::WrongConceptProximity,
        JudgmentReasonV3::CommonTermDominance,
        JudgmentReasonV3::LengthPriorFailure,
        JudgmentReasonV3::ScatteredTerms,
    ];
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

pub(super) fn complete_coverage_audit(
    baseline_ledger: &RelevanceLedgerV3,
    locality_ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    baseline: &LinearRankerV3,
    challenger: &LinearRankerV3,
) -> CompleteCoverageAudit {
    let assignments = split
        .assignments
        .iter()
        .map(|value| (value.judgment_identity, value.primary_split))
        .collect::<HashMap<_, _>>();
    let baseline_by_id = baseline_ledger
        .active_model_training_judgments()
        .into_iter()
        .map(|judgment| (judgment.identity, judgment))
        .collect::<HashMap<_, _>>();
    let mut audit = CompleteCoverageAudit::default();
    for locality in locality_ledger
        .active_model_training_judgments()
        .into_iter()
        .filter(|judgment| {
            assignments.get(&judgment.identity) == Some(&PrimarySplitV3::BlindTest)
                && judgment.positive_features.missing_groups == 0
                && judgment.negative_features.missing_groups == 0
        })
    {
        let original = baseline_by_id[&locality.identity];
        audit.judgments += 1;
        audit.baseline_correct += usize::from(
            baseline
                .score(original.positive_features)
                .unwrap_or(f32::NEG_INFINITY)
                > baseline
                    .score(original.negative_features)
                    .unwrap_or(f32::NEG_INFINITY),
        );
        audit.challenger_correct += usize::from(
            challenger
                .score(locality.positive_features)
                .unwrap_or(f32::NEG_INFINITY)
                > challenger
                    .score(locality.negative_features)
                    .unwrap_or(f32::NEG_INFINITY),
        );
    }
    audit.baseline_accuracy = audit.baseline_correct as f64 / audit.judgments.max(1) as f64;
    audit.challenger_accuracy = audit.challenger_correct as f64 / audit.judgments.max(1) as f64;
    audit.absolute_change = audit.challenger_accuracy - audit.baseline_accuracy;
    audit
}

fn conclusion(
    baseline: &ModelEvaluation,
    challenger: &ModelEvaluation,
    targeted: &[TargetedResidual],
    complete: CompleteCoverageAudit,
) -> LocalityConclusion {
    let improved_targets = targeted
        .iter()
        .filter(|value| value.absolute_change > 0.0)
        .count();
    let material = challenger.longmemeval.model.mean_reciprocal_rank
        >= baseline.longmemeval.model.mean_reciprocal_rank + 0.003
        || challenger.graded.ndcg_improvement >= baseline.graded.ndcg_improvement + 0.01
        || improved_targets >= 4;
    let safe = complete.absolute_change >= -0.005
        && challenger.mixed.model.mean_reciprocal_rank >= baseline.mixed.model.mean_reciprocal_rank;
    LocalityConclusion {
        outcome: if material && safe {
            "locality_materially_explains_residuals"
        } else if material {
            "locality_improves_residuals_but_harms_complete_coverage"
        } else {
            "locality_does_not_materially_explain_residuals"
        },
        improved_target_classes: improved_targets,
        complete_coverage_safe: safe,
        authorize_phase_8_6b_schema_migration: material && safe,
        next_action: if material && safe {
            "formalize_schema_and_run_append_only_legacy_migration"
        } else {
            "stop_schema_migration_and_select_the_next_residual_primitive"
        },
    }
}

#[inline]
fn valid_locality(value: f32) -> bool {
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
    locality_finite_and_bounded: bool,
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
struct CandidateProjection {
    candidates: usize,
    projected_candidates: usize,
    missing_queries: usize,
    missing_candidates: usize,
    locality_finite_and_bounded: bool,
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
pub(super) struct DevelopmentSelection {
    pub(super) judgments: usize,
    pub(super) correctly_ordered: usize,
    pub(super) accuracy: f32,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct TargetedResidual {
    reason: JudgmentReasonV3,
    judgments: usize,
    baseline_accuracy: f64,
    challenger_accuracy: f64,
    absolute_change: f64,
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
pub(super) struct CompleteCoverageAudit {
    pub(super) judgments: usize,
    pub(super) baseline_correct: usize,
    pub(super) challenger_correct: usize,
    pub(super) baseline_accuracy: f64,
    pub(super) challenger_accuracy: f64,
    pub(super) absolute_change: f64,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct LocalityConclusion {
    outcome: &'static str,
    improved_target_classes: usize,
    complete_coverage_safe: bool,
    authorize_phase_8_6b_schema_migration: bool,
    next_action: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct Phase86Gates {
    baseline_reproduces_canonical_phase_8: bool,
    independent_ledger_byte_identical_to_v9: bool,
    independent_graded_byte_identical_to_v9: bool,
    all_active_labels_projected: bool,
    all_graded_candidates_projected: bool,
    all_release_candidates_projected: bool,
    v2_release_substrate_bit_identical: bool,
    locality_finite_and_bounded: bool,
    deterministic_training: bool,
    monotonic_nonnegative_weights: bool,
    production_promotion_forbidden: bool,
}

impl Phase86Gates {
    fn all_pass(self) -> bool {
        self.baseline_reproduces_canonical_phase_8
            && self.independent_ledger_byte_identical_to_v9
            && self.independent_graded_byte_identical_to_v9
            && self.all_active_labels_projected
            && self.all_graded_candidates_projected
            && self.all_release_candidates_projected
            && self.v2_release_substrate_bit_identical
            && self.locality_finite_and_bounded
            && self.deterministic_training
            && self.monotonic_nonnegative_weights
            && self.production_promotion_forbidden
    }
}

#[derive(Debug, Serialize)]
struct Phase86Receipt {
    contract: &'static str,
    architecture: &'static str,
    replaced_coordinate: usize,
    replaced_feature: &'static str,
    experimental_feature: &'static str,
    model_artifact: FileIdentity,
    phase_6_receipt: FileIdentity,
    phase_4_receipt: FileIdentity,
    phase_3_receipt: FileIdentity,
    graded_suite: FileIdentity,
    independent_ledger: FileIdentity,
    independent_locality_sidecar: FileIdentity,
    release_locality_sidecar: FileIdentity,
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
    conclusion: LocalityConclusion,
    gates: Phase86Gates,
    production_promotion_authorized: bool,
    active_engine_after_diagnostic: &'static str,
}

#[derive(Debug, Serialize)]
pub(crate) struct Phase86Publication {
    contract: &'static str,
    output: FileIdentity,
    diagnostic_model_identity: [u8; 32],
    conclusion: LocalityConclusion,
    production_promotion_authorized: bool,
    active_engine_after_diagnostic: &'static str,
}

#[derive(Debug, Deserialize)]
struct IndependentLocalitySidecar {
    contract: String,
    replaced_canonical_coordinate: usize,
    experimental_feature: String,
    canonical_ledger: InputFileIdentity,
    canonical_graded_suite: InputFileIdentity,
    pairs: Vec<PairLocality>,
    graded_queries: Vec<GradedLocalityQuery>,
}

#[derive(Debug, Deserialize)]
struct PairLocality {
    judgment_identity: String,
    query_identity: String,
    positive_document_version: String,
    negative_document_version: String,
    positive_locality: f32,
    negative_locality: f32,
}

#[derive(Debug, Deserialize)]
struct GradedLocalityQuery {
    query_identity: String,
    candidates: Vec<GradedLocalityCandidate>,
}

#[derive(Debug, Deserialize)]
struct GradedLocalityCandidate {
    document_identity: String,
    v2_order: usize,
    matched_group_locality: f32,
    relevance_tier: RelevanceTier,
}

#[derive(Debug, Deserialize)]
struct ReleaseLocalitySidecar {
    contract: String,
    mixed: ReleaseLocalityCohort,
    longmemeval: ReleaseLocalityCohort,
    gates: ReleaseSidecarGates,
}

#[derive(Debug, Deserialize)]
struct ReleaseLocalityCohort {
    queries: Vec<ReleaseLocalityQuery>,
}

#[derive(Debug, Deserialize)]
struct ReleaseLocalityQuery {
    query_identity: String,
    candidates: Vec<ReleaseLocalityCandidate>,
}

#[derive(Debug, Deserialize)]
struct ReleaseLocalityCandidate {
    document_identity: String,
    v2_order: usize,
    relevance_tier: RelevanceTier,
    matched_group_locality: f32,
}

#[derive(Debug, Deserialize)]
struct ReleaseSidecarGates {
    phase_3_verified: bool,
    mixed: ReleaseCohortParity,
    longmemeval: ReleaseCohortParity,
    locality_is_finite_and_bounded: bool,
}

impl ReleaseSidecarGates {
    fn all_pass(&self) -> bool {
        self.phase_3_verified
            && self.mixed.all_pass()
            && self.longmemeval.all_pass()
            && self.locality_is_finite_and_bounded
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
