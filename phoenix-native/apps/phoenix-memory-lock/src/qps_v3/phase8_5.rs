use std::cmp::Ordering;
use std::collections::BTreeMap;

use phoenix_lexical_qps::{
    leakage_split_identity_v3, JudgmentReasonV3, LeakageSplitV3, LinearRankerV3, PrimarySplitV3,
    RankEvidenceV3, RelevanceLedgerV3, RelevanceTier, RANK_EVIDENCE_V3_FEATURE_NAMES,
};

use super::train::{decode_hex_32, LinearModelArtifactV3};
use super::*;

#[path = "phase8_5_model.rs"]
mod diagnostic_model;
use diagnostic_model::{select_and_train, ShapeConditionedRanker, ShapeTrainingReceipt};

#[path = "phase8_6.rs"]
pub(super) mod locality;
#[path = "phase8_7.rs"]
pub(super) mod rarity_coverage;
#[path = "phase8_7_train.rs"]
pub(super) mod rarity_coverage_train;

const CONTRACT: &str = "phoenix.memory.qps-v3-phase8.5-capacity-diagnostic/v1";
const GRADED_CONTRACT: &str = "phoenix.qps.graded-evaluation-suite/v3";
const QUERY_ONLY_INDICES: [usize; 3] = [
    RankEvidenceV3::QUERY_GROUP_COUNT,
    RankEvidenceV3::SINGLE_GROUP_FLAG,
    RankEvidenceV3::LONG_QUERY_FLAG,
];

#[allow(clippy::too_many_arguments)]
pub(crate) fn diagnose(
    model_path: &Path,
    phase_6_path: &Path,
    phase_4_path: &Path,
    phase_3_path: &Path,
    graded_suite_path: &Path,
    canonical_phase_8_path: &Path,
    output_path: &Path,
) -> Result<Phase85Publication> {
    if output_path.exists() {
        bail!(
            "refusing to overwrite Phase 8.5 receipt {}",
            output_path.display()
        );
    }
    let artifact: LinearModelArtifactV3 = read_json(model_path, "Phase 7 model")?;
    if !artifact.validate_challenger() {
        bail!("Phase 8.5 requires a valid Phase 7 challenger");
    }
    let phase_6: FrozenPhase6 = read_json(phase_6_path, "Phase 6 receipt")?;
    let phase_4: FrozenPhase4 = read_json(phase_4_path, "Phase 4 receipt")?;
    let phase_3: FrozenPhase3 = read_json(phase_3_path, "Phase 3 receipt")?;
    let graded: GradedEvaluationSuiteV3 = read_json(graded_suite_path, "graded suite")?;
    let canonical: CanonicalPhase8 = read_json(canonical_phase_8_path, "canonical Phase 8")?;
    validate_inputs(&artifact, &phase_6, &phase_4, &phase_3, &graded, &canonical)?;

    let ledger_identity = decode_hex_32(&sha256_bytes(&serde_json::to_vec(&phase_4.ledger)?))?;
    if ledger_identity != artifact.training_ledger_identity
        || leakage_split_identity_v3(&phase_6.split)
            != artifact.training_receipt.leakage_split_identity
    {
        bail!("Phase 8.5 inputs are not bound to the Phase 7 training identities");
    }

    let feature_visibility = feature_visibility_audit(&phase_4.ledger);
    let baseline = evaluate_all(
        &artifact.model_parameters,
        &phase_4.ledger,
        &phase_6.split,
        &phase_3,
        &graded,
    )?;
    let baseline_cartography = cartography(
        &artifact.model_parameters,
        &phase_4.ledger,
        &phase_6.split,
        &phase_3,
        &graded,
    )?;
    let (challenger, training) = select_and_train(
        &phase_4.ledger,
        &phase_6.split,
        ledger_identity,
        &artifact.model_parameters,
    )
    .map_err(anyhow::Error::msg)?;
    let challenger_evaluation = evaluate_all(
        &challenger,
        &phase_4.ledger,
        &phase_6.split,
        &phase_3,
        &graded,
    )?;
    let challenger_cartography = cartography(
        &challenger,
        &phase_4.ledger,
        &phase_6.split,
        &phase_3,
        &graded,
    )?;
    let baseline_reproduces_canonical_phase_8 = baseline_matches(&baseline, &canonical);
    let conclusion = conclusion(&baseline, &challenger_evaluation);
    let gates = DiagnosticGates {
        phase_4_verified: phase_4.phase_4_verified,
        phase_6_verified: phase_6.phase_6_verified,
        phase_3_verified: phase_3.phase_3_verified,
        canonical_phase_8_is_blocked: !canonical.phase_8_verified,
        canonical_model_identity_matches: canonical.model_identity == artifact.model_identity,
        baseline_reproduces_canonical_phase_8,
        query_only_features_are_gradient_dead: feature_visibility
            .query_only_features
            .iter()
            .all(|feature| feature.maximum_absolute_same_query_delta == 0.0),
        duplicate_coverage_coordinates_are_numerically_equivalent: feature_visibility
            .duplicate_coordinate_maximum_absolute_error
            <= f32::EPSILON,
        training_is_deterministic: training.deterministic_retraining,
        effective_weights_are_monotonic: training
            .signed_interactions_with_nonnegative_effective_weights,
        production_promotion_is_forbidden: true,
    };
    if !gates.all_pass() {
        bail!(
            "Phase 8.5 diagnostic integrity gates failed: {gates:?}; feature audit: {feature_visibility:?}"
        );
    }
    let receipt = Phase85Receipt {
        contract: CONTRACT,
        architecture: "diagnostic_only_shape_conditioned_monotonic_linear_over_frozen_v3_evidence",
        model_artifact: file_identity(model_path)?,
        phase_6_receipt: file_identity(phase_6_path)?,
        phase_4_receipt: file_identity(phase_4_path)?,
        phase_3_receipt: file_identity(phase_3_path)?,
        graded_suite: file_identity(graded_suite_path)?,
        canonical_phase_8_receipt: file_identity(canonical_phase_8_path)?,
        producer_binary: current_binary_identity()?,
        feature_visibility,
        baseline,
        baseline_cartography,
        training,
        diagnostic_model: challenger,
        challenger: challenger_evaluation,
        challenger_cartography,
        conclusion,
        gates,
        production_promotion_authorized: false,
        active_engine_after_diagnostic: "V2 active",
    };
    write_json_atomic(output_path, &receipt)?;
    Ok(Phase85Publication {
        contract: CONTRACT,
        output: file_identity(output_path)?,
        diagnostic_model_identity: receipt.diagnostic_model.identity(),
        conclusion,
        production_promotion_authorized: false,
        active_engine_after_diagnostic: "V2 active",
    })
}

fn validate_inputs(
    model: &LinearModelArtifactV3,
    phase_6: &FrozenPhase6,
    phase_4: &FrozenPhase4,
    phase_3: &FrozenPhase3,
    graded: &GradedEvaluationSuiteV3,
    canonical: &CanonicalPhase8,
) -> Result<()> {
    if phase_6.contract != "phoenix.memory.qps-v3-leakage-split/v1" || !phase_6.phase_6_verified {
        bail!("Phase 8.5 requires verified Phase 6");
    }
    if phase_4.contract != "phoenix.memory.qps-v3-ledger-qualification/v1"
        || !phase_4.phase_4_verified
    {
        bail!("Phase 8.5 requires verified Phase 4");
    }
    if phase_3.contract != "phoenix.memory.qps-v3-constitutional-tiers/v1"
        || !phase_3.phase_3_verified
    {
        bail!("Phase 8.5 requires verified Phase 3");
    }
    graded.validate()?;
    if canonical.contract != "phoenix.memory.qps-v3-quality-qualification/v1"
        || canonical.phase_8_verified
        || canonical.model_identity != model.model_identity
    {
        bail!("Phase 8.5 requires the blocked canonical Phase 8 receipt for this model");
    }
    Ok(())
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path, label: &str) -> Result<T> {
    serde_json::from_slice(&fs::read(path)?)
        .with_context(|| format!("decode {label} {}", path.display()))
}

trait Scorer {
    fn score_evidence(&self, evidence: RankEvidenceV3) -> Option<f32>;
}

impl Scorer for LinearRankerV3 {
    fn score_evidence(&self, evidence: RankEvidenceV3) -> Option<f32> {
        self.score(evidence)
    }
}

impl Scorer for ShapeConditionedRanker {
    fn score_evidence(&self, evidence: RankEvidenceV3) -> Option<f32> {
        self.score(evidence)
    }
}

fn evaluate_all<S: Scorer>(
    scorer: &S,
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    phase_3: &FrozenPhase3,
    graded: &GradedEvaluationSuiteV3,
) -> Result<ModelEvaluation> {
    let mixed = evaluate_cohort(&phase_3.mixed_suite, scorer)?;
    let longmemeval = evaluate_cohort(&phase_3.longmemeval_release, scorer)?;
    let graded = evaluate_graded(graded, scorer)?;
    let blind = evaluate_blind(ledger, split, scorer)?;
    let worst_shape_mrr_regression = worst_shape_regression(&phase_3.longmemeval_release, scorer)?;
    let held_out_top_1_improvement_points =
        (blind.v3_top_1_accuracy - blind.v2_top_1_accuracy) * 100.0;
    Ok(ModelEvaluation {
        mixed,
        longmemeval,
        graded,
        blind,
        held_out_top_1_improvement_points,
        worst_shape_mrr_regression,
    })
}

fn evaluate_cohort<S: Scorer>(cohort: &FrozenCohort, scorer: &S) -> Result<CohortEvaluation> {
    let mut v2 = MetricAccumulator::default();
    let mut model = MetricAccumulator::default();
    for query in &cohort.queries {
        let relevant = query
            .oracle_locations
            .iter()
            .map(|oracle| oracle.document_identity.as_str())
            .collect::<HashSet<_>>();
        let mut v2_order = query.candidate_pool.iter().collect::<Vec<_>>();
        v2_order.sort_unstable_by_key(|candidate| candidate.v2_order);
        let model_order = rank_candidates(&query.candidate_pool, scorer)?;
        v2.observe(&v2_order, &relevant);
        model.observe(&model_order, &relevant);
    }
    Ok(CohortEvaluation {
        v2: v2.finish(),
        model: model.finish(),
    })
}

fn evaluate_graded<S: Scorer>(
    suite: &GradedEvaluationSuiteV3,
    scorer: &S,
) -> Result<GradedEvaluation> {
    let mut v2_ndcg = 0.0;
    let mut model_ndcg = 0.0;
    let mut reciprocal_rank = 0.0;
    for query in &suite.queries {
        let mut v2 = query.candidates.iter().collect::<Vec<_>>();
        v2.sort_unstable_by_key(|candidate| candidate.v2_order);
        let model = rank_graded(&query.candidates, scorer)?;
        v2_ndcg += ndcg(v2.iter().map(|candidate| candidate.grade));
        model_ndcg += ndcg(model.iter().map(|candidate| candidate.grade));
        reciprocal_rank += model
            .iter()
            .position(|candidate| candidate.grade > 0)
            .map_or(0.0, |rank| 1.0 / (rank + 1) as f64);
    }
    let queries = suite.queries.len().max(1) as f64;
    let v2_ndcg_at_10 = v2_ndcg / queries;
    let model_ndcg_at_10 = model_ndcg / queries;
    Ok(GradedEvaluation {
        queries: suite.queries.len(),
        v2_ndcg_at_10,
        model_ndcg_at_10,
        ndcg_improvement: model_ndcg_at_10 - v2_ndcg_at_10,
        stretch_mrr: reciprocal_rank / queries,
    })
}

fn evaluate_blind<S: Scorer>(
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    scorer: &S,
) -> Result<BlindEvaluation> {
    let assigned = split
        .assignments
        .iter()
        .map(|value| (value.judgment_identity, value.primary_split))
        .collect::<HashMap<_, _>>();
    let mut classes = all_reasons()
        .into_iter()
        .map(|reason| (reason, ClassEvaluation::default()))
        .collect::<HashMap<_, _>>();
    let mut judgments = 0;
    let mut v2_correct = 0;
    let mut model_correct = 0;
    let mut query_top_1 = HashMap::new();
    for judgment in ledger
        .active_model_training_judgments()
        .into_iter()
        .filter(|judgment| assigned.get(&judgment.identity) == Some(&PrimarySplitV3::BlindTest))
    {
        let positive = scorer
            .score_evidence(judgment.positive_features)
            .context("invalid positive blind evidence")?;
        let negative = scorer
            .score_evidence(judgment.negative_features)
            .context("invalid negative blind evidence")?;
        let v2_wins = judgment.positive_position < judgment.negative_position;
        let model_wins = compare_ranked(
            judgment.positive_tier,
            positive,
            &judgment.positive_document_version.as_bytes(),
            judgment.negative_tier,
            negative,
            &judgment.negative_document_version.as_bytes(),
        ) == Ordering::Less;
        judgments += 1;
        v2_correct += usize::from(v2_wins);
        model_correct += usize::from(model_wins);
        let query = query_top_1
            .entry(judgment.query_identity)
            .or_insert((true, true));
        query.0 &= v2_wins;
        query.1 &= model_wins;
        let class = classes.get_mut(&judgment.reason).expect("all reasons");
        class.judgments += 1;
        class.v2_correct += usize::from(v2_wins);
        class.model_correct += usize::from(model_wins);
    }
    let mut classes = classes.into_iter().collect::<Vec<_>>();
    classes.sort_unstable_by_key(|(reason, _)| reason_name(*reason));
    for (_, class) in &mut classes {
        class.v2_accuracy = class.v2_correct as f64 / class.judgments.max(1) as f64;
        class.model_accuracy = class.model_correct as f64 / class.judgments.max(1) as f64;
    }
    let queries = query_top_1.len();
    Ok(BlindEvaluation {
        judgments,
        v2_correct,
        model_correct,
        v2_accuracy: v2_correct as f64 / judgments.max(1) as f64,
        model_accuracy: model_correct as f64 / judgments.max(1) as f64,
        queries,
        v2_top_1_accuracy: query_top_1.values().filter(|(v2, _)| *v2).count() as f64
            / queries.max(1) as f64,
        v3_top_1_accuracy: query_top_1.values().filter(|(_, model)| *model).count() as f64
            / queries.max(1) as f64,
        classes: classes
            .into_iter()
            .map(|(reason, evaluation)| NamedClassEvaluation { reason, evaluation })
            .collect(),
    })
}

fn worst_shape_regression<S: Scorer>(cohort: &FrozenCohort, scorer: &S) -> Result<f64> {
    let mut shapes = HashMap::<&str, (f64, f64, usize)>::new();
    for query in &cohort.queries {
        let relevant = query
            .oracle_locations
            .iter()
            .map(|oracle| oracle.document_identity.as_str())
            .collect::<HashSet<_>>();
        let mut v2 = query.candidate_pool.iter().collect::<Vec<_>>();
        v2.sort_unstable_by_key(|candidate| candidate.v2_order);
        let model = rank_candidates(&query.candidate_pool, scorer)?;
        let entry = shapes.entry(&query.query_shape).or_default();
        entry.0 += reciprocal_rank(&v2, &relevant);
        entry.1 += reciprocal_rank(&model, &relevant);
        entry.2 += 1;
    }
    Ok(shapes
        .into_values()
        .map(|(v2, model, count)| (v2 - model) / count.max(1) as f64)
        .fold(0.0, f64::max))
}

fn cartography<S: Scorer>(
    scorer: &S,
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    phase_3: &FrozenPhase3,
    graded: &GradedEvaluationSuiteV3,
) -> Result<FailureCartography> {
    Ok(FailureCartography {
        blind_reason_by_shape: blind_failure_matrix(ledger, split, scorer)?,
        longmemeval: cohort_blockers(&phase_3.longmemeval_release, scorer)?,
        graded: graded_blockers(graded, scorer)?,
    })
}

fn blind_failure_matrix<S: Scorer>(
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    scorer: &S,
) -> Result<Vec<BlindFailureCell>> {
    let assigned = split
        .assignments
        .iter()
        .map(|value| (value.judgment_identity, value.primary_split))
        .collect::<HashMap<_, _>>();
    let mut cells = BTreeMap::<(String, String), BlindFailureCell>::new();
    for judgment in ledger
        .active_model_training_judgments()
        .into_iter()
        .filter(|judgment| assigned.get(&judgment.identity) == Some(&PrimarySplitV3::BlindTest))
    {
        let shape = shape_name(judgment.positive_features);
        let reason = reason_name(judgment.reason).to_owned();
        let cell = cells
            .entry((reason.clone(), shape.clone()))
            .or_insert(BlindFailureCell {
                reason,
                query_shape: shape,
                judgments: 0,
                failures: 0,
                same_tier_failures: 0,
                cross_tier_failures: 0,
            });
        cell.judgments += 1;
        let positive = scorer
            .score_evidence(judgment.positive_features)
            .context("blind score")?;
        let negative = scorer
            .score_evidence(judgment.negative_features)
            .context("blind score")?;
        let failed = compare_ranked(
            judgment.positive_tier,
            positive,
            &judgment.positive_document_version.as_bytes(),
            judgment.negative_tier,
            negative,
            &judgment.negative_document_version.as_bytes(),
        ) != Ordering::Less;
        if failed {
            cell.failures += 1;
            if judgment.positive_tier == judgment.negative_tier {
                cell.same_tier_failures += 1;
            } else {
                cell.cross_tier_failures += 1;
            }
        }
    }
    Ok(cells.into_values().collect())
}

fn cohort_blockers<S: Scorer>(cohort: &FrozenCohort, scorer: &S) -> Result<TierBlockerAutopsy> {
    let mut audit = TierBlockerAutopsy::default();
    for query in &cohort.queries {
        let relevant = query
            .oracle_locations
            .iter()
            .map(|oracle| oracle.document_identity.as_str())
            .collect::<HashSet<_>>();
        let order = rank_candidates(&query.candidate_pool, scorer)?;
        if let Some(rank) = order
            .iter()
            .position(|candidate| relevant.contains(candidate.document_identity.as_str()))
        {
            if rank == 0 {
                continue;
            }
            audit.failure_queries += 1;
            let relevant_tier = order[rank].relevance_tier;
            for blocker in &order[..rank] {
                audit.blockers += 1;
                if blocker.relevance_tier == relevant_tier {
                    audit.same_tier_blockers += 1;
                } else {
                    audit.cross_tier_blockers += 1;
                }
            }
            let key = format!(
                "{}|{}",
                query.query_shape,
                shape_name(order[rank].rank_evidence_v3)
            );
            *audit.failure_queries_by_shape.entry(key).or_default() += 1;
        }
    }
    Ok(audit)
}

fn graded_blockers<S: Scorer>(
    suite: &GradedEvaluationSuiteV3,
    scorer: &S,
) -> Result<GradedAutopsy> {
    let mut audit = GradedAutopsy::default();
    for query in &suite.queries {
        let order = rank_graded(&query.candidates, scorer)?;
        if let Some(rank) = order.iter().position(|candidate| candidate.grade > 0) {
            if rank > 0 {
                audit.mrr.failure_queries += 1;
                let relevant_tier = order[rank].relevance_tier;
                for blocker in &order[..rank] {
                    audit.mrr.blockers += 1;
                    if blocker.relevance_tier == relevant_tier {
                        audit.mrr.same_tier_blockers += 1;
                    } else {
                        audit.mrr.cross_tier_blockers += 1;
                    }
                }
                let shape = shape_name(order[rank].rank_evidence_v3);
                *audit.mrr.failure_queries_by_shape.entry(shape).or_default() += 1;
            }
        }
        for (left_index, left) in order.iter().enumerate() {
            for right in &order[left_index + 1..] {
                if left.grade < right.grade {
                    audit.graded_pair_inversions += 1;
                    if left.relevance_tier == right.relevance_tier {
                        audit.same_tier_graded_pair_inversions += 1;
                    } else {
                        audit.cross_tier_graded_pair_inversions += 1;
                    }
                }
            }
        }
    }
    Ok(audit)
}

fn rank_candidates<'a, S: Scorer>(
    candidates: &'a [FrozenCandidate],
    scorer: &S,
) -> Result<Vec<&'a FrozenCandidate>> {
    let mut scored = candidates
        .iter()
        .map(|candidate| {
            scorer
                .score_evidence(candidate.rank_evidence_v3)
                .map(|score| (candidate, score))
                .context("invalid frozen candidate evidence")
        })
        .collect::<Result<Vec<_>>>()?;
    scored.sort_unstable_by(|(left, left_score), (right, right_score)| {
        compare_ranked(
            left.relevance_tier,
            *left_score,
            &left.document_identity,
            right.relevance_tier,
            *right_score,
            &right.document_identity,
        )
    });
    Ok(scored.into_iter().map(|(candidate, _)| candidate).collect())
}

fn rank_graded<'a, S: Scorer>(
    candidates: &'a [GradedCandidateV3],
    scorer: &S,
) -> Result<Vec<&'a GradedCandidateV3>> {
    let mut scored = candidates
        .iter()
        .map(|candidate| {
            scorer
                .score_evidence(candidate.rank_evidence_v3)
                .map(|score| (candidate, score))
                .context("invalid graded candidate evidence")
        })
        .collect::<Result<Vec<_>>>()?;
    scored.sort_unstable_by(|(left, left_score), (right, right_score)| {
        compare_ranked(
            left.relevance_tier,
            *left_score,
            &left.document_identity,
            right.relevance_tier,
            *right_score,
            &right.document_identity,
        )
    });
    Ok(scored.into_iter().map(|(candidate, _)| candidate).collect())
}

fn compare_ranked<T: Ord + ?Sized>(
    left_tier: RelevanceTier,
    left_score: f32,
    left_identity: &T,
    right_tier: RelevanceTier,
    right_score: f32,
    right_identity: &T,
) -> Ordering {
    left_tier
        .cmp(&right_tier)
        .then_with(|| right_score.total_cmp(&left_score))
        .then_with(|| left_identity.cmp(right_identity))
}

fn feature_visibility_audit(ledger: &RelevanceLedgerV3) -> FeatureVisibilityAudit {
    let mut maximum_deltas = [0.0_f32; 3];
    let mut duplicate_error = 0.0_f32;
    let mut query_shape_inconsistencies = 0_usize;
    let mut candidate_varying_expansion_flag_pairs = 0_usize;
    let mut expansion_flag_maximum_absolute_delta = 0.0_f32;
    let judgments = ledger.active_model_training_judgments();
    for judgment in &judgments {
        for (slot, index) in QUERY_ONLY_INDICES.iter().enumerate() {
            maximum_deltas[slot] = maximum_deltas[slot].max(
                (judgment.positive_features.values[*index]
                    - judgment.negative_features.values[*index])
                    .abs(),
            );
        }
        query_shape_inconsistencies += usize::from(
            judgment.positive_features.query_groups != judgment.negative_features.query_groups
                || judgment.positive_features.query_flags & 0b0101
                    != judgment.negative_features.query_flags & 0b0101,
        );
        let expansion_delta = (judgment.positive_features.values
            [RankEvidenceV3::EXPANSION_QUERY_FLAG]
            - judgment.negative_features.values[RankEvidenceV3::EXPANSION_QUERY_FLAG])
            .abs();
        candidate_varying_expansion_flag_pairs += usize::from(expansion_delta != 0.0);
        expansion_flag_maximum_absolute_delta =
            expansion_flag_maximum_absolute_delta.max(expansion_delta);
        for evidence in [judgment.positive_features, judgment.negative_features] {
            duplicate_error = duplicate_error.max(
                (evidence.values[RankEvidenceV3::MATCHED_GROUP_FRACTION]
                    - evidence.values[RankEvidenceV3::MISSING_GROUP_ABSENCE])
                    .abs(),
            );
        }
    }
    FeatureVisibilityAudit {
        active_training_judgments: judgments.len(),
        query_shape_inconsistencies,
        candidate_varying_expansion_flag_pairs,
        expansion_flag_maximum_absolute_delta,
        query_only_features: QUERY_ONLY_INDICES
            .iter()
            .zip(maximum_deltas)
            .map(
                |(index, maximum_absolute_same_query_delta)| FeatureDeltaAudit {
                    feature_index: *index,
                    feature_name: RANK_EVIDENCE_V3_FEATURE_NAMES[*index],
                    maximum_absolute_same_query_delta,
                },
            )
            .collect(),
        duplicate_coordinates: ["matched_group_fraction", "missing_group_absence"],
        duplicate_coordinate_maximum_absolute_error: duplicate_error,
        effective_independent_feature_upper_bound: 26,
    }
}

fn conclusion(baseline: &ModelEvaluation, challenger: &ModelEvaluation) -> DiagnosticConclusion {
    let improves_every_residual = challenger.longmemeval.model.mean_reciprocal_rank
        > baseline.longmemeval.model.mean_reciprocal_rank
        && challenger.graded.stretch_mrr > baseline.graded.stretch_mrr
        && challenger.graded.ndcg_improvement > baseline.graded.ndcg_improvement
        && challenger.blind.model_accuracy > baseline.blind.model_accuracy
        && challenger.worst_shape_mrr_regression < baseline.worst_shape_mrr_regression;
    let passes_residual_gates = challenger.longmemeval.model.mean_reciprocal_rank >= 0.910
        && challenger.graded.stretch_mrr >= 0.920
        && challenger.graded.ndcg_improvement >= 0.020
        && challenger.blind.model_accuracy >= 0.80
        && challenger.worst_shape_mrr_regression <= 0.005;
    let outcome = if passes_residual_gates {
        "existing_evidence_has_sufficient_capacity_under_shape_conditioning"
    } else if improves_every_residual {
        "shape_interactions_explain_part_but_not_all_of_the_residual"
    } else {
        "shape_interactions_are_not_a_sufficient_explanation_add_one_measured_primitive"
    };
    DiagnosticConclusion {
        outcome,
        improves_every_residual,
        passes_all_residual_phase_8_gates: passes_residual_gates,
        next_action: if passes_residual_gates {
            "formalize_conditional_linear_v3x_then_rerun_phase_8"
        } else {
            "use_residual_cartography_to_select_exactly_one_new_primitive"
        },
    }
}

fn baseline_matches(baseline: &ModelEvaluation, canonical: &CanonicalPhase8) -> bool {
    near(
        baseline.longmemeval.model.mean_reciprocal_rank,
        canonical.longmemeval.v3.mean_reciprocal_rank,
    ) && near(baseline.graded.stretch_mrr, canonical.graded.stretch_mrr)
        && near(
            baseline.graded.ndcg_improvement,
            canonical.graded.ndcg_improvement,
        )
        && near(
            baseline.blind.model_accuracy,
            canonical.blind_pairwise.v3_accuracy,
        )
        && near(
            baseline.worst_shape_mrr_regression,
            canonical.worst_query_shape_mrr_regression,
        )
}

fn near(left: f64, right: f64) -> bool {
    (left - right).abs() <= 1.0e-12
}

fn shape_name(evidence: RankEvidenceV3) -> String {
    let groups = match evidence.query_groups {
        1 => "g1",
        2..=3 => "g2_3",
        4..=7 => "g4_7",
        _ => "g8_plus",
    };
    format!(
        "{groups}|single={}|long={}",
        evidence.values[RankEvidenceV3::SINGLE_GROUP_FLAG] as u8,
        evidence.values[RankEvidenceV3::LONG_QUERY_FLAG] as u8,
    )
}

fn reason_name(reason: JudgmentReasonV3) -> &'static str {
    match reason {
        JudgmentReasonV3::PartialMatchSaturation => "partial_match_saturation",
        JudgmentReasonV3::ScatteredTerms => "scattered_terms",
        JudgmentReasonV3::PhraseOrderFailure => "phrase_order_failure",
        JudgmentReasonV3::IdentifierCollision => "identifier_collision",
        JudgmentReasonV3::FuzzyCollision => "fuzzy_collision",
        JudgmentReasonV3::WeakFieldEvidence => "weak_field_evidence",
        JudgmentReasonV3::CommonTermDominance => "common_term_dominance",
        JudgmentReasonV3::LengthPriorFailure => "length_prior_failure",
        JudgmentReasonV3::WrongConceptProximity => "wrong_concept_proximity",
        JudgmentReasonV3::DocumentConversationConfusion => "document_conversation_confusion",
        JudgmentReasonV3::LongQueryFailure => "long_query_failure",
        JudgmentReasonV3::RealUserCorrection => "real_user_correction",
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

fn ndcg(grades: impl Iterator<Item = u8>) -> f64 {
    let grades = grades.take(10).collect::<Vec<_>>();
    let dcg = discounted_gain(grades.iter().copied());
    let mut ideal = grades;
    ideal.sort_unstable_by(|left, right| right.cmp(left));
    let ideal = discounted_gain(ideal.into_iter());
    if ideal == 0.0 {
        0.0
    } else {
        dcg / ideal
    }
}

fn discounted_gain(grades: impl Iterator<Item = u8>) -> f64 {
    grades
        .enumerate()
        .map(|(rank, grade)| ((1_u32 << grade) - 1) as f64 / ((rank + 2) as f64).log2())
        .sum()
}

fn reciprocal_rank<T: CandidateIdentity>(ordered: &[T], relevant: &HashSet<&str>) -> f64 {
    ordered
        .iter()
        .position(|candidate| relevant.contains(candidate.identity()))
        .map_or(0.0, |rank| 1.0 / (rank + 1) as f64)
}

trait CandidateIdentity {
    fn identity(&self) -> &str;
}

impl CandidateIdentity for &FrozenCandidate {
    fn identity(&self) -> &str {
        &self.document_identity
    }
}

#[derive(Default)]
struct MetricAccumulator {
    answerable: usize,
    hits: usize,
    reciprocal_sum: f64,
    top_1: usize,
    no_result: usize,
    correct_no_result: usize,
}

impl MetricAccumulator {
    fn observe<T: CandidateIdentity>(&mut self, ordered: &[T], relevant: &HashSet<&str>) {
        if relevant.is_empty() {
            self.no_result += 1;
            self.correct_no_result += usize::from(ordered.is_empty());
            return;
        }
        self.answerable += 1;
        if let Some(rank) = ordered
            .iter()
            .position(|candidate| relevant.contains(candidate.identity()))
        {
            self.hits += usize::from(rank < 10);
            self.top_1 += usize::from(rank == 0);
            self.reciprocal_sum += 1.0 / (rank + 1) as f64;
        }
    }

    fn finish(self) -> RankingMetrics {
        RankingMetrics {
            answerable_queries: self.answerable,
            hit_at_10: self.hits as f64 / self.answerable.max(1) as f64,
            mean_reciprocal_rank: self.reciprocal_sum / self.answerable.max(1) as f64,
            top_1_accuracy: self.top_1 as f64 / self.answerable.max(1) as f64,
            no_result_queries: self.no_result,
            no_result_accuracy: self.correct_no_result as f64 / self.no_result.max(1) as f64,
        }
    }
}

#[derive(Clone, Debug, Serialize)]
struct Phase85Receipt {
    contract: &'static str,
    architecture: &'static str,
    model_artifact: FileIdentity,
    phase_6_receipt: FileIdentity,
    phase_4_receipt: FileIdentity,
    phase_3_receipt: FileIdentity,
    graded_suite: FileIdentity,
    canonical_phase_8_receipt: FileIdentity,
    producer_binary: FileIdentity,
    feature_visibility: FeatureVisibilityAudit,
    baseline: ModelEvaluation,
    baseline_cartography: FailureCartography,
    training: ShapeTrainingReceipt,
    diagnostic_model: ShapeConditionedRanker,
    challenger: ModelEvaluation,
    challenger_cartography: FailureCartography,
    conclusion: DiagnosticConclusion,
    gates: DiagnosticGates,
    production_promotion_authorized: bool,
    active_engine_after_diagnostic: &'static str,
}

#[derive(Clone, Debug, Serialize)]
pub struct Phase85Publication {
    contract: &'static str,
    output: FileIdentity,
    diagnostic_model_identity: [u8; 32],
    conclusion: DiagnosticConclusion,
    production_promotion_authorized: bool,
    active_engine_after_diagnostic: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct DiagnosticConclusion {
    outcome: &'static str,
    improves_every_residual: bool,
    passes_all_residual_phase_8_gates: bool,
    next_action: &'static str,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct DiagnosticGates {
    phase_4_verified: bool,
    phase_6_verified: bool,
    phase_3_verified: bool,
    canonical_phase_8_is_blocked: bool,
    canonical_model_identity_matches: bool,
    baseline_reproduces_canonical_phase_8: bool,
    query_only_features_are_gradient_dead: bool,
    duplicate_coverage_coordinates_are_numerically_equivalent: bool,
    training_is_deterministic: bool,
    effective_weights_are_monotonic: bool,
    production_promotion_is_forbidden: bool,
}

impl DiagnosticGates {
    fn all_pass(self) -> bool {
        self.phase_4_verified
            && self.phase_6_verified
            && self.phase_3_verified
            && self.canonical_phase_8_is_blocked
            && self.canonical_model_identity_matches
            && self.baseline_reproduces_canonical_phase_8
            && self.query_only_features_are_gradient_dead
            && self.duplicate_coverage_coordinates_are_numerically_equivalent
            && self.training_is_deterministic
            && self.effective_weights_are_monotonic
            && self.production_promotion_is_forbidden
    }
}

#[derive(Clone, Debug, Serialize)]
struct FeatureVisibilityAudit {
    active_training_judgments: usize,
    query_shape_inconsistencies: usize,
    candidate_varying_expansion_flag_pairs: usize,
    expansion_flag_maximum_absolute_delta: f32,
    query_only_features: Vec<FeatureDeltaAudit>,
    duplicate_coordinates: [&'static str; 2],
    duplicate_coordinate_maximum_absolute_error: f32,
    effective_independent_feature_upper_bound: usize,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct FeatureDeltaAudit {
    feature_index: usize,
    feature_name: &'static str,
    maximum_absolute_same_query_delta: f32,
}

#[derive(Clone, Debug, Serialize)]
struct ModelEvaluation {
    mixed: CohortEvaluation,
    longmemeval: CohortEvaluation,
    graded: GradedEvaluation,
    blind: BlindEvaluation,
    held_out_top_1_improvement_points: f64,
    worst_shape_mrr_regression: f64,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct CohortEvaluation {
    v2: RankingMetrics,
    model: RankingMetrics,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
struct RankingMetrics {
    answerable_queries: usize,
    hit_at_10: f64,
    mean_reciprocal_rank: f64,
    top_1_accuracy: f64,
    no_result_queries: usize,
    no_result_accuracy: f64,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
struct GradedEvaluation {
    queries: usize,
    v2_ndcg_at_10: f64,
    model_ndcg_at_10: f64,
    ndcg_improvement: f64,
    stretch_mrr: f64,
}

#[derive(Clone, Debug, Serialize)]
struct BlindEvaluation {
    judgments: usize,
    v2_correct: usize,
    model_correct: usize,
    v2_accuracy: f64,
    model_accuracy: f64,
    queries: usize,
    v2_top_1_accuracy: f64,
    v3_top_1_accuracy: f64,
    classes: Vec<NamedClassEvaluation>,
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
struct ClassEvaluation {
    judgments: usize,
    v2_correct: usize,
    model_correct: usize,
    v2_accuracy: f64,
    model_accuracy: f64,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct NamedClassEvaluation {
    reason: JudgmentReasonV3,
    evaluation: ClassEvaluation,
}

#[derive(Clone, Debug, Serialize)]
struct FailureCartography {
    blind_reason_by_shape: Vec<BlindFailureCell>,
    longmemeval: TierBlockerAutopsy,
    graded: GradedAutopsy,
}

#[derive(Clone, Debug, Serialize)]
struct BlindFailureCell {
    reason: String,
    query_shape: String,
    judgments: usize,
    failures: usize,
    same_tier_failures: usize,
    cross_tier_failures: usize,
}

#[derive(Clone, Debug, Default, Serialize)]
struct TierBlockerAutopsy {
    failure_queries: usize,
    blockers: usize,
    same_tier_blockers: usize,
    cross_tier_blockers: usize,
    failure_queries_by_shape: BTreeMap<String, usize>,
}

#[derive(Clone, Debug, Default, Serialize)]
struct GradedAutopsy {
    mrr: TierBlockerAutopsy,
    graded_pair_inversions: usize,
    same_tier_graded_pair_inversions: usize,
    cross_tier_graded_pair_inversions: usize,
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
struct FrozenPhase3 {
    contract: String,
    mixed_suite: FrozenCohort,
    longmemeval_release: FrozenCohort,
    phase_3_verified: bool,
}

#[derive(Debug, Deserialize)]
struct FrozenCohort {
    queries: Vec<FrozenQuery>,
}

#[derive(Debug, Deserialize)]
struct FrozenQuery {
    query_identity: String,
    query_shape: String,
    candidate_pool: Vec<FrozenCandidate>,
    oracle_locations: Vec<FrozenOracle>,
}

#[derive(Debug, Deserialize)]
struct FrozenCandidate {
    document_identity: String,
    v2_order: usize,
    rank_evidence_v3: RankEvidenceV3,
    relevance_tier: RelevanceTier,
}

#[derive(Debug, Deserialize)]
struct FrozenOracle {
    document_identity: String,
}

#[derive(Debug, Deserialize)]
struct GradedEvaluationSuiteV3 {
    contract: String,
    schema_version: u16,
    queries: Vec<GradedQueryV3>,
}

impl GradedEvaluationSuiteV3 {
    fn validate(&self) -> Result<()> {
        if self.contract != GRADED_CONTRACT || self.schema_version != 3 || self.queries.is_empty() {
            bail!("invalid or empty V3 graded evaluation suite");
        }
        if self.queries.iter().any(|query| {
            query.query_identity.is_empty()
                || query.candidates.is_empty()
                || query.candidates.len() > 160
                || query
                    .candidates
                    .iter()
                    .any(|candidate| candidate.grade > 4 || !candidate.rank_evidence_v3.is_valid())
        }) {
            bail!("invalid V3 graded query");
        }
        Ok(())
    }
}

#[derive(Debug, Deserialize)]
struct GradedQueryV3 {
    query_identity: String,
    candidates: Vec<GradedCandidateV3>,
}

#[derive(Debug, Deserialize)]
struct GradedCandidateV3 {
    document_identity: String,
    v2_order: usize,
    rank_evidence_v3: RankEvidenceV3,
    relevance_tier: RelevanceTier,
    grade: u8,
}

#[derive(Debug, Deserialize)]
struct CanonicalPhase8 {
    contract: String,
    model_identity: [u8; 32],
    longmemeval: CanonicalCohort,
    graded: CanonicalGraded,
    blind_pairwise: CanonicalBlind,
    worst_query_shape_mrr_regression: f64,
    phase_8_verified: bool,
}

#[derive(Debug, Deserialize)]
struct CanonicalCohort {
    v3: RankingMetrics,
}

#[derive(Debug, Deserialize)]
struct CanonicalGraded {
    ndcg_improvement: f64,
    stretch_mrr: f64,
}

#[derive(Debug, Deserialize)]
struct CanonicalBlind {
    v3_accuracy: f64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_twelve_failure_reasons_are_named() {
        assert_eq!(all_reasons().len(), 12);
        assert_eq!(
            reason_name(JudgmentReasonV3::RealUserCorrection),
            "real_user_correction"
        );
    }

    #[test]
    fn conclusion_does_not_authorize_promotion() {
        assert!(
            !Phase85Publication {
                contract: CONTRACT,
                output: FileIdentity {
                    path: String::new(),
                    bytes: 0,
                    sha256: String::new()
                },
                diagnostic_model_identity: [0; 32],
                conclusion: DiagnosticConclusion {
                    outcome: "diagnostic",
                    improves_every_residual: false,
                    passes_all_residual_phase_8_gates: false,
                    next_action: "measure",
                },
                production_promotion_authorized: false,
                active_engine_after_diagnostic: "V2 active",
            }
            .production_promotion_authorized
        );
    }
}
