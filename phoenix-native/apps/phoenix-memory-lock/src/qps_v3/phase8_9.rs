use std::cmp::Ordering;
use std::path::{Path, PathBuf};

use phoenix_lexical_qps::{
    JudgmentIdentity, JudgmentReasonV3, LeakageSplitV3, LinearRankerV3, PrimarySplitV3,
    RankEvidenceV3, RelevanceLedgerV3, RelevanceTier, RANK_EVIDENCE_V3_FEATURE_COUNT,
    RANK_EVIDENCE_V3_FEATURE_NAMES,
};
use serde::{Deserialize, Serialize};

use super::train::LinearModelArtifactV3;
use super::*;

const CONTRACT: &str = "phoenix.memory.qps-v3-phase8.9-group-distribution-proof/v1";
const INDEPENDENT_CONTRACT: &str = "phoenix.qps.phase8.9-group-distribution-sidecar/v1";
const RELEASE_CONTRACT: &str =
    "phoenix.memory.qps-v3-phase8.9-release-group-distribution-sidecar/v1";
const EPSILON: f32 = 1.0e-6;
const REQUIRED_ORIENTATION: f64 = 0.70;
const MINIMUM_DIRECTIONAL: usize = 20;
const MINIMUM_SOURCE_DIRECTIONAL: usize = 5;
const REQUIRED_SOURCE_ORIENTATION: f64 = 0.60;
const MINIMUM_TRANSFER_DIRECTIONAL: usize = 10;
const TRANSFER_REJECTION_FLOOR: f64 = 0.50;
const TRANSFER_SUPPORT: f64 = 0.55;

#[allow(clippy::too_many_arguments)]
pub(crate) fn diagnose(
    model_path: &Path,
    phase_6_path: &Path,
    phase_4_path: &Path,
    phase_3_path: &Path,
    independent_ledger_path: &Path,
    graded_suite_path: &Path,
    independent_sidecar_path: &Path,
    release_sidecar_path: &Path,
    output_path: &Path,
) -> Result<Phase89Publication> {
    if output_path.exists() {
        bail!(
            "refusing to overwrite Phase 8.9 proof {}",
            output_path.display()
        );
    }
    let model: LinearModelArtifactV3 = read_json(model_path, "model artifact")?;
    let phase_6: FrozenPhase6 = read_json(phase_6_path, "Phase 6 receipt")?;
    let phase_4: FrozenPhase4 = read_json(phase_4_path, "Phase 4 receipt")?;
    let phase_3: FrozenPhase3 = read_json(phase_3_path, "Phase 3 receipt")?;
    let independent: IndependentSidecar =
        read_json(independent_sidecar_path, "independent group sidecar")?;
    let release: ReleaseSidecar = read_json(release_sidecar_path, "release group sidecar")?;
    let graded: GradedSuite = read_json(graded_suite_path, "graded suite")?;
    validate_inputs(
        &model,
        &phase_6,
        &phase_4,
        &phase_3,
        &independent,
        &release,
        &graded,
        independent_ledger_path,
        graded_suite_path,
    )?;

    let residuals = development_residuals(&phase_4.ledger, &phase_6.split, &model, &independent)?;
    let monotonic_impossible = residuals
        .iter()
        .filter(|row| row.monotonic_impossible)
        .count();
    if residuals.len() != 194 || monotonic_impossible != 28 {
        bail!(
            "Phase 8.9 residual cohort drifted from Phase 8.8: {} errors / {} impossible",
            residuals.len(),
            monotonic_impossible
        );
    }
    let mut evaluations = Vec::with_capacity(4);
    let mut selected = None;
    for primitive in [
        Primitive::Weakest,
        Primitive::Q25,
        Primitive::Q33,
        Primitive::Balance,
    ] {
        let evaluation = evaluate_primitive(
            primitive,
            &residuals,
            &graded,
            &independent,
            &phase_3,
            &release,
            &model.model_parameters,
        )?;
        let passes = evaluation.gates.migration_preflight_passes;
        evaluations.push(evaluation);
        if passes {
            selected = Some(primitive);
            break;
        }
    }

    let interesting = evaluations.iter().any(|evaluation| {
        evaluation.development.overall.directional() >= MINIMUM_DIRECTIONAL
            && evaluation.development.overall.orientation_accuracy() >= 0.60
    });
    let conclusion = match selected {
        Some(_) => "EVIDENCE_SUFFICIENT_FOR_MIGRATION",
        None if interesting => "EVIDENCE_INTERESTING_BUT_INSUFFICIENT",
        None => "GROUP_DISTRIBUTION_HYPOTHESIS_REJECTED",
    };
    let receipt = Phase89Receipt {
        contract: CONTRACT,
        mission: "falsify_or_support_information_loss_from_per_group_aggregation",
        residual_cohort: ResidualCohortDefinition {
            split: "development_only",
            target: "pairs_incorrect_under_canonical_phase7_model",
            blind_labels_read: false,
            external_cohorts: "transfer_rejection_only_after_development_design",
            residual_pairs: residuals.len(),
            monotonic_impossible_pairs: monotonic_impossible,
        },
        group_strength: GroupStrengthDefinition {
            raw: "expansion_quality * sum_field_bm25f_impact_of_selected_posting",
            bounded: "raw/(1+raw)",
            selected_evidence: "existing_best_posting_choice_per_query_group",
            unmatched_groups: "explicit_zero_excluded_from_matched_tail_statistics",
            learned_function_used: false,
        },
        primitive_definitions: PrimitiveDefinitions {
            weakest: "minimum_nonzero_matched_group_strength",
            q25: "sorted_nonzero_strengths[floor(0.25*(n-1))]",
            q33: "sorted_nonzero_strengths[floor((1/3)*(n-1))]",
            balance: "1/(n*sum_j((s_j/sum_k(s_k))^2))",
        },
        thresholds: Thresholds {
            required_orientation: REQUIRED_ORIENTATION,
            minimum_directional: MINIMUM_DIRECTIONAL,
            minimum_source_directional: MINIMUM_SOURCE_DIRECTIONAL,
            required_source_orientation: REQUIRED_SOURCE_ORIENTATION,
            minimum_transfer_directional: MINIMUM_TRANSFER_DIRECTIONAL,
            transfer_rejection_floor: TRANSFER_REJECTION_FLOOR,
            transfer_support: TRANSFER_SUPPORT,
        },
        model_artifact: file_identity(model_path)?,
        phase_6_receipt: file_identity(phase_6_path)?,
        phase_4_receipt: file_identity(phase_4_path)?,
        phase_3_receipt: file_identity(phase_3_path)?,
        independent_ledger: file_identity(independent_ledger_path)?,
        graded_suite: file_identity(graded_suite_path)?,
        independent_sidecar: file_identity(independent_sidecar_path)?,
        release_sidecar: file_identity(release_sidecar_path)?,
        producer_binary: current_binary_identity()?,
        integrity_gates: IntegrityGates {
            phase_4_6_3_verified: true,
            independent_ledger_byte_identical_to_v9: true,
            independent_graded_byte_identical_to_v9: true,
            independent_profiles_finite_bounded_and_aligned: true,
            release_substrate_bit_identical: true,
            canonical_residual_count_194: true,
            canonical_monotonic_impossible_count_28: true,
            blind_labels_not_read_for_design: true,
        },
        profile_example: profile_example(),
        residual_rows: residuals.iter().map(ResidualRow::from).collect(),
        evaluations,
        selected_primitive: selected,
        conclusion,
        canonical_rank_evidence_schema_changed: false,
        canonical_ledger_changed: false,
        canonical_model_retrained: false,
        production_promotion_authorized: false,
        active_engine_after_preflight: "V2 active",
    };
    write_json_atomic(output_path, &receipt)?;
    Ok(Phase89Publication {
        contract: CONTRACT,
        output: file_identity(output_path)?,
        residual_pairs: receipt.residual_cohort.residual_pairs,
        evaluated_primitives: receipt.evaluations.len(),
        selected_primitive: selected,
        conclusion,
        production_promotion_authorized: false,
        active_engine_after_preflight: "V2 active",
    })
}

#[allow(clippy::too_many_arguments)]
fn validate_inputs(
    model: &LinearModelArtifactV3,
    phase_6: &FrozenPhase6,
    phase_4: &FrozenPhase4,
    phase_3: &FrozenPhase3,
    independent: &IndependentSidecar,
    release: &ReleaseSidecar,
    graded_suite: &GradedSuite,
    independent_ledger_path: &Path,
    graded_suite_path: &Path,
) -> Result<()> {
    if !model.validate_challenger()
        || !phase_6.phase_6_verified
        || !phase_4.phase_4_verified
        || !phase_3.phase_3_verified
        || independent.contract != INDEPENDENT_CONTRACT
        || release.contract != RELEASE_CONTRACT
        || !release.gates.all_pass()
    {
        bail!("Phase 8.9 input contract or qualification failed");
    }
    phase_4.ledger.validate().map_err(anyhow::Error::msg)?;
    let ledger = file_identity(independent_ledger_path)?;
    let graded = file_identity(graded_suite_path)?;
    if independent.canonical_ledger.sha256 != ledger.sha256
        || independent.canonical_graded_suite.sha256 != graded.sha256
        || ledger.sha256 != "a28f906d13446e4c5c0b627bc6400e5112a48d413105d229fe053fefc92b35d8"
        || graded.sha256 != "d9be32daca38e0b4cefd2680447ebeb5e8e6f5021c8f789917e468f9704af02b"
    {
        bail!("Phase 8.9 independent substrate is not byte-identical to v9");
    }
    if independent.pairs.iter().any(|pair| {
        pair.positive_strengths.len() != pair.negative_strengths.len()
            || !valid_profile(&pair.positive_strengths)
            || !valid_profile(&pair.negative_strengths)
    }) {
        bail!("Phase 8.9 independent pair profile is invalid");
    }
    let graded_profiles = independent
        .graded_queries
        .iter()
        .map(|query| (query.query_identity.as_str(), query))
        .collect::<HashMap<_, _>>();
    for query in &graded_suite.queries {
        let profile = graded_profiles
            .get(query.query_identity.as_str())
            .context("independent graded profile query missing")?;
        let candidates = profile
            .candidates
            .iter()
            .map(|candidate| (candidate.document_identity.as_str(), candidate))
            .collect::<HashMap<_, _>>();
        for candidate in &query.candidates {
            let profile = candidates
                .get(candidate.document_identity.as_str())
                .context("independent graded candidate profile missing")?;
            if profile.strengths.len() != candidate.rank_evidence_v3.query_groups as usize
                || !valid_profile(&profile.strengths)
            {
                bail!("independent graded candidate profile is invalid");
            }
        }
    }
    Ok(())
}

fn valid_profile(values: &[f32]) -> bool {
    !values.is_empty()
        && values
            .iter()
            .all(|value| value.is_finite() && (0.0..=1.0).contains(value))
}

fn development_residuals(
    ledger: &RelevanceLedgerV3,
    split: &LeakageSplitV3,
    model: &LinearModelArtifactV3,
    sidecar: &IndependentSidecar,
) -> Result<Vec<Residual>> {
    let records = sidecar
        .pairs
        .iter()
        .map(|pair| (pair.judgment_identity.as_str(), pair))
        .collect::<HashMap<_, _>>();
    let assignments = split
        .assignments
        .iter()
        .map(|row| (row.judgment_identity, row.primary_split))
        .collect::<HashMap<_, _>>();
    let mut roots = HashMap::<JudgmentIdentity, JudgmentIdentity>::new();
    for judgment in &ledger.judgments {
        let root = judgment
            .supersedes
            .and_then(|parent| roots.get(&parent).copied())
            .unwrap_or(judgment.identity);
        roots.insert(judgment.identity, root);
    }
    let mut residuals = Vec::new();
    for index in ledger.active_model_training_indices() {
        let judgment = &ledger.judgments[index];
        if assignments.get(&judgment.identity) != Some(&PrimarySplitV3::Development)
            || pair_is_correct(&model.model_parameters, judgment)?
        {
            continue;
        }
        let root = roots
            .get(&judgment.identity)
            .context("active judgment root missing")?;
        let root_hex = hex(root.as_bytes());
        let pair = records
            .get(root_hex.as_str())
            .with_context(|| format!("group profile missing for root {root_hex}"))?;
        let current_positive = hex(judgment.positive_document_version.as_bytes());
        let current_negative = hex(judgment.negative_document_version.as_bytes());
        let (positive, negative, reversed) =
            orient_profiles(pair, &current_positive, &current_negative)?;
        if positive.len() != judgment.positive_features.query_groups as usize
            || negative.len() != judgment.negative_features.query_groups as usize
        {
            bail!("group profile length disagrees with canonical evidence");
        }
        let feature_deltas = std::array::from_fn(|feature| {
            judgment.positive_features.values[feature] - judgment.negative_features.values[feature]
        });
        residuals.push(Residual {
            judgment_identity: hex(judgment.identity.as_bytes()),
            root_identity: root_hex,
            dataset: pair.dataset.clone(),
            reason: judgment.reason,
            query_groups: judgment.positive_features.query_groups,
            reversed_review: reversed,
            positive: positive.to_vec(),
            negative: negative.to_vec(),
            feature_deltas,
            monotonic_impossible: !feature_deltas.iter().any(|delta| *delta > 0.0),
        });
    }
    Ok(residuals)
}

fn pair_is_correct(
    model: &LinearRankerV3,
    judgment: &phoenix_lexical_qps::PairwiseJudgmentV3,
) -> Result<bool> {
    let positive = model
        .score(judgment.positive_features)
        .context("positive score")?;
    let negative = model
        .score(judgment.negative_features)
        .context("negative score")?;
    Ok(compare_ranked(
        judgment.positive_tier,
        positive,
        &hex(judgment.positive_document_version.as_bytes()),
        judgment.negative_tier,
        negative,
        &hex(judgment.negative_document_version.as_bytes()),
    ) == Ordering::Less)
}

fn orient_profiles<'a>(
    pair: &'a PairProfile,
    positive: &str,
    negative: &str,
) -> Result<(&'a [f32], &'a [f32], bool)> {
    if positive == pair.positive_document_version && negative == pair.negative_document_version {
        Ok((&pair.positive_strengths, &pair.negative_strengths, false))
    } else if positive == pair.negative_document_version
        && negative == pair.positive_document_version
    {
        Ok((&pair.negative_strengths, &pair.positive_strengths, true))
    } else {
        bail!("active review documents diverged from mined root")
    }
}

fn evaluate_primitive(
    primitive: Primitive,
    residuals: &[Residual],
    graded: &GradedSuite,
    independent: &IndependentSidecar,
    phase_3: &FrozenPhase3,
    release: &ReleaseSidecar,
    model: &LinearRankerV3,
) -> Result<PrimitiveEvaluation> {
    let development = audit_development(primitive, residuals);
    let independent_transfer = audit_graded_transfer(primitive, graded, independent, model)?;
    let longmemeval_transfer = audit_release_transfer(
        primitive,
        &phase_3.longmemeval_release,
        &release.longmemeval,
        model,
        "longmemeval",
    )?;
    let mixed_transfer = audit_release_transfer(
        primitive,
        &phase_3.mixed_suite,
        &release.mixed,
        model,
        "mixed",
    )?;
    let source_support = development
        .by_source
        .iter()
        .filter(|row| {
            row.counts.directional() >= MINIMUM_SOURCE_DIRECTIONAL
                && row.counts.orientation_accuracy() >= REQUIRED_SOURCE_ORIENTATION
        })
        .count();
    let independent_ok = transfer_not_rejected(&independent_transfer.overall);
    let longmemeval_ok = transfer_not_rejected(&longmemeval_transfer.overall);
    let transfer_supported = independent_transfer.overall.orientation_accuracy()
        >= TRANSFER_SUPPORT
        || longmemeval_transfer.overall.orientation_accuracy() >= TRANSFER_SUPPORT;
    let gates = PrimitiveGates {
        minimum_directional_pairs: development.overall.directional() >= MINIMUM_DIRECTIONAL,
        orientation_at_least_0_70: development.overall.orientation_accuracy()
            >= REQUIRED_ORIENTATION,
        at_least_two_development_sources: source_support >= 2,
        independent_transfer_not_rejected: independent_ok,
        longmemeval_transfer_not_rejected: longmemeval_ok,
        at_least_one_external_transfer_supported: transfer_supported,
        migration_preflight_passes: development.overall.directional() >= MINIMUM_DIRECTIONAL
            && development.overall.orientation_accuracy() >= REQUIRED_ORIENTATION
            && source_support >= 2
            && independent_ok
            && longmemeval_ok
            && transfer_supported,
    };
    Ok(PrimitiveEvaluation {
        primitive,
        development,
        independent_transfer,
        longmemeval_transfer,
        mixed_transfer,
        gates,
    })
}

fn transfer_not_rejected(counts: &DirectionCounts) -> bool {
    counts.directional() < MINIMUM_TRANSFER_DIRECTIONAL
        || counts.orientation_accuracy() >= TRANSFER_REJECTION_FLOOR
}

fn audit_development(primitive: Primitive, residuals: &[Residual]) -> DevelopmentAudit {
    let mut overall = DirectionCounts::default();
    let mut impossible = DirectionCounts::default();
    let mut classes = HashMap::<String, DirectionCounts>::new();
    let mut sources = HashMap::<String, DirectionCounts>::new();
    let mut groups = HashMap::<String, DirectionCounts>::new();
    let mut shapes = HashMap::<String, DirectionCounts>::new();
    let mut deltas = Vec::with_capacity(residuals.len());
    for row in residuals {
        let delta = primitive.value(&row.positive) - primitive.value(&row.negative);
        let direction = Direction::from_delta(delta);
        overall.record(direction);
        if row.monotonic_impossible {
            impossible.record(direction);
        }
        classes
            .entry(format!("{:?}", row.reason))
            .or_default()
            .record(direction);
        sources
            .entry(row.dataset.clone())
            .or_default()
            .record(direction);
        groups
            .entry(group_bucket(row.query_groups))
            .or_default()
            .record(direction);
        if row.dataset == "locomo" {
            shapes
                .entry("locomo_multi_session".into())
                .or_default()
                .record(direction);
        }
        if row.query_groups >= 8 {
            shapes
                .entry("g8_plus".into())
                .or_default()
                .record(direction);
        }
        if row.query_groups > 16 {
            shapes
                .entry("long_query_g17_plus".into())
                .or_default()
                .record(direction);
        }
        deltas.push(delta);
    }
    DevelopmentAudit {
        overall,
        monotonic_impossible: impossible,
        newly_distinguishable_monotonic_impossible: impossible.directional(),
        correctly_oriented_new_monotonic_impossible: impossible.preferred_higher,
        by_class: sorted_breakdown(classes),
        by_source: sorted_breakdown(sources),
        by_group_count: sorted_breakdown(groups),
        by_shape: sorted_breakdown(shapes),
        redundancy: redundancy_audit(&deltas, residuals),
    }
}

fn audit_graded_transfer(
    primitive: Primitive,
    graded: &GradedSuite,
    sidecar: &IndependentSidecar,
    model: &LinearRankerV3,
) -> Result<TransferAudit> {
    let profiles = sidecar
        .graded_queries
        .iter()
        .map(|query| (query.query_identity.as_str(), query))
        .collect::<HashMap<_, _>>();
    let mut overall = DirectionCounts::default();
    let mut by_source = HashMap::<String, DirectionCounts>::new();
    let mut residual_queries = 0;
    for query in &graded.queries {
        let profile = profiles
            .get(query.query_identity.as_str())
            .context("graded group profile missing")?;
        let profile_candidates = profile
            .candidates
            .iter()
            .map(|candidate| (candidate.document_identity.as_str(), candidate))
            .collect::<HashMap<_, _>>();
        let mut ranked = query.candidates.iter().collect::<Vec<_>>();
        ranked.sort_unstable_by(|left, right| {
            let left_score = model
                .score(left.rank_evidence_v3)
                .unwrap_or(f32::NEG_INFINITY);
            let right_score = model
                .score(right.rank_evidence_v3)
                .unwrap_or(f32::NEG_INFINITY);
            compare_ranked(
                left.relevance_tier,
                left_score,
                &left.document_identity,
                right.relevance_tier,
                right_score,
                &right.document_identity,
            )
        });
        let maximum_grade = ranked
            .iter()
            .map(|candidate| candidate.grade)
            .max()
            .unwrap_or(0);
        let Some(negative) = ranked
            .first()
            .filter(|candidate| candidate.grade < maximum_grade)
        else {
            continue;
        };
        let positive = ranked
            .iter()
            .find(|candidate| candidate.grade == maximum_grade)
            .context("maximum-grade candidate missing")?;
        let positive_profile = profile_candidates
            .get(positive.document_identity.as_str())
            .context("positive graded profile missing")?;
        let negative_profile = profile_candidates
            .get(negative.document_identity.as_str())
            .context("negative graded profile missing")?;
        let direction = Direction::from_delta(
            primitive.value(&positive_profile.strengths)
                - primitive.value(&negative_profile.strengths),
        );
        overall.record(direction);
        by_source
            .entry(profile.dataset.clone())
            .or_default()
            .record(direction);
        residual_queries += 1;
    }
    Ok(TransferAudit {
        cohort: "independent_graded",
        residual_definition: "canonical_top_candidate_has_lower_grade_than_query_maximum",
        residual_queries,
        overall,
        by_shape_or_source: sorted_breakdown(by_source),
    })
}

fn audit_release_transfer(
    primitive: Primitive,
    frozen: &FrozenCohort,
    sidecar: &ReleaseCohort,
    model: &LinearRankerV3,
    cohort: &'static str,
) -> Result<TransferAudit> {
    let profiles = sidecar
        .queries
        .iter()
        .map(|query| (query.query_identity.as_str(), query))
        .collect::<HashMap<_, _>>();
    let mut overall = DirectionCounts::default();
    let mut shapes = HashMap::<String, DirectionCounts>::new();
    let mut residual_queries = 0;
    for query in &frozen.queries {
        let profile = profiles
            .get(query.query_identity.as_str())
            .context("release group profile missing")?;
        let profile_candidates = profile
            .candidates
            .iter()
            .map(|candidate| (candidate.document_identity.as_str(), candidate))
            .collect::<HashMap<_, _>>();
        let relevant = query
            .oracle_locations
            .iter()
            .map(|oracle| oracle.document_identity.as_str())
            .collect::<HashSet<_>>();
        let mut ranked = query.candidate_pool.iter().collect::<Vec<_>>();
        ranked.sort_unstable_by(|left, right| {
            let left_score = model
                .score(left.rank_evidence_v3)
                .unwrap_or(f32::NEG_INFINITY);
            let right_score = model
                .score(right.rank_evidence_v3)
                .unwrap_or(f32::NEG_INFINITY);
            compare_ranked(
                left.relevance_tier,
                left_score,
                &left.document_identity,
                right.relevance_tier,
                right_score,
                &right.document_identity,
            )
        });
        let Some(negative) = ranked
            .first()
            .filter(|candidate| !relevant.contains(candidate.document_identity.as_str()))
        else {
            continue;
        };
        let Some(positive) = ranked
            .iter()
            .find(|candidate| relevant.contains(candidate.document_identity.as_str()))
        else {
            continue;
        };
        let positive_profile = profile_candidates
            .get(positive.document_identity.as_str())
            .context("release oracle profile missing")?;
        let negative_profile = profile_candidates
            .get(negative.document_identity.as_str())
            .context("release blocker profile missing")?;
        let direction = Direction::from_delta(
            primitive.value(&positive_profile.strengths)
                - primitive.value(&negative_profile.strengths),
        );
        overall.record(direction);
        shapes
            .entry(query.query_shape.clone())
            .or_default()
            .record(direction);
        residual_queries += 1;
    }
    Ok(TransferAudit {
        cohort,
        residual_definition: "canonical_top_candidate_non_oracle_vs_highest_ranked_oracle",
        residual_queries,
        overall,
        by_shape_or_source: sorted_breakdown(shapes),
    })
}

fn compare_ranked(
    left_tier: RelevanceTier,
    left_score: f32,
    left_identity: &str,
    right_tier: RelevanceTier,
    right_score: f32,
    right_identity: &str,
) -> Ordering {
    left_tier
        .cmp(&right_tier)
        .then_with(|| right_score.total_cmp(&left_score))
        .then_with(|| left_identity.cmp(right_identity))
}

fn redundancy_audit(deltas: &[f32], residuals: &[Residual]) -> RedundancyAudit {
    let mut best_index = 0;
    let mut best = 0.0_f64;
    for feature in 0..RANK_EVIDENCE_V3_FEATURE_COUNT {
        let feature_deltas = residuals
            .iter()
            .map(|row| row.feature_deltas[feature])
            .collect::<Vec<_>>();
        let correlation = pearson(deltas, &feature_deltas).abs();
        if correlation > best {
            best = correlation;
            best_index = feature;
        }
    }
    RedundancyAudit {
        maximum_absolute_pair_delta_correlation: best,
        most_correlated_feature_index: best_index,
        most_correlated_feature_name: RANK_EVIDENCE_V3_FEATURE_NAMES[best_index],
    }
}

fn pearson(left: &[f32], right: &[f32]) -> f64 {
    if left.is_empty() || left.len() != right.len() {
        return 0.0;
    }
    let left_mean = left.iter().map(|value| *value as f64).sum::<f64>() / left.len() as f64;
    let right_mean = right.iter().map(|value| *value as f64).sum::<f64>() / right.len() as f64;
    let mut covariance = 0.0;
    let mut left_variance = 0.0;
    let mut right_variance = 0.0;
    for (&left, &right) in left.iter().zip(right) {
        let left = left as f64 - left_mean;
        let right = right as f64 - right_mean;
        covariance += left * right;
        left_variance += left * left;
        right_variance += right * right;
    }
    covariance / (left_variance * right_variance).sqrt().max(f64::EPSILON)
}

fn group_bucket(groups: u16) -> String {
    match groups {
        0..=1 => "g1",
        2..=3 => "g2_3",
        4..=7 => "g4_7",
        _ => "g8_plus",
    }
    .to_owned()
}

fn sorted_breakdown(values: HashMap<String, DirectionCounts>) -> Vec<Breakdown> {
    let mut rows = values
        .into_iter()
        .map(|(key, counts)| Breakdown { key, counts })
        .collect::<Vec<_>>();
    rows.sort_unstable_by(|left, right| left.key.cmp(&right.key));
    rows
}

fn profile_example() -> ProfileExample {
    let a = [0.81, 0.79, 0.76, 0.74, 0.71, 0.69, 0.67, 0.64];
    let b = [0.99, 0.98, 0.97, 0.95, 0.38, 0.36, 0.34, 0.31];
    ProfileExample {
        a,
        b,
        weakest: [Primitive::Weakest.value(&a), Primitive::Weakest.value(&b)],
        q25: [Primitive::Q25.value(&a), Primitive::Q25.value(&b)],
        q33: [Primitive::Q33.value(&a), Primitive::Q33.value(&b)],
        balance: [Primitive::Balance.value(&a), Primitive::Balance.value(&b)],
    }
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path, label: &str) -> Result<T> {
    serde_json::from_slice(&fs::read(path)?)
        .with_context(|| format!("decode {label} {}", path.display()))
}

fn hex<const N: usize>(bytes: [u8; N]) -> String {
    bytes.iter().map(|value| format!("{value:02x}")).collect()
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Primitive {
    Weakest,
    Q25,
    Q33,
    Balance,
}

impl Primitive {
    fn value(self, profile: &[f32]) -> f32 {
        let mut matched = profile
            .iter()
            .copied()
            .filter(|value| *value > EPSILON)
            .collect::<Vec<_>>();
        if matched.is_empty() {
            return 0.0;
        }
        matched.sort_unstable_by(f32::total_cmp);
        match self {
            Self::Weakest => matched[0],
            Self::Q25 => matched[((matched.len() - 1) as f32 * 0.25).floor() as usize],
            Self::Q33 => matched[((matched.len() - 1) as f32 / 3.0).floor() as usize],
            Self::Balance => {
                let sum = matched.iter().sum::<f32>();
                let concentration = matched
                    .iter()
                    .map(|value| {
                        let probability = *value / sum;
                        probability * probability
                    })
                    .sum::<f32>();
                1.0 / (matched.len() as f32 * concentration)
            }
        }
    }
}

#[derive(Clone, Copy)]
enum Direction {
    Higher,
    Equal,
    Lower,
}

impl Direction {
    fn from_delta(delta: f32) -> Self {
        if delta > EPSILON {
            Self::Higher
        } else if delta < -EPSILON {
            Self::Lower
        } else {
            Self::Equal
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
struct DirectionCounts {
    target_pairs: usize,
    preferred_higher: usize,
    equal: usize,
    preferred_lower: usize,
    distinguishable_pairs: usize,
    orientation_accuracy: f64,
}

impl DirectionCounts {
    fn record(&mut self, direction: Direction) {
        self.target_pairs += 1;
        match direction {
            Direction::Higher => self.preferred_higher += 1,
            Direction::Equal => self.equal += 1,
            Direction::Lower => self.preferred_lower += 1,
        }
        self.distinguishable_pairs = self.preferred_higher + self.preferred_lower;
        self.orientation_accuracy = self.preferred_higher as f64 / self.directional().max(1) as f64;
    }

    fn directional(&self) -> usize {
        self.preferred_higher + self.preferred_lower
    }

    fn orientation_accuracy(&self) -> f64 {
        self.preferred_higher as f64 / self.directional().max(1) as f64
    }
}

struct Residual {
    judgment_identity: String,
    root_identity: String,
    dataset: String,
    reason: JudgmentReasonV3,
    query_groups: u16,
    reversed_review: bool,
    positive: Vec<f32>,
    negative: Vec<f32>,
    feature_deltas: [f32; RANK_EVIDENCE_V3_FEATURE_COUNT],
    monotonic_impossible: bool,
}

#[derive(Debug, Serialize)]
struct ResidualRow {
    judgment_identity: String,
    root_identity: String,
    dataset: String,
    reason: JudgmentReasonV3,
    query_groups: u16,
    reversed_review: bool,
    monotonic_impossible: bool,
    positive_strengths: Vec<f32>,
    negative_strengths: Vec<f32>,
}

impl From<&Residual> for ResidualRow {
    fn from(row: &Residual) -> Self {
        Self {
            judgment_identity: row.judgment_identity.clone(),
            root_identity: row.root_identity.clone(),
            dataset: row.dataset.clone(),
            reason: row.reason,
            query_groups: row.query_groups,
            reversed_review: row.reversed_review,
            monotonic_impossible: row.monotonic_impossible,
            positive_strengths: row.positive.clone(),
            negative_strengths: row.negative.clone(),
        }
    }
}

#[derive(Debug, Serialize)]
struct DevelopmentAudit {
    overall: DirectionCounts,
    monotonic_impossible: DirectionCounts,
    newly_distinguishable_monotonic_impossible: usize,
    correctly_oriented_new_monotonic_impossible: usize,
    by_class: Vec<Breakdown>,
    by_source: Vec<Breakdown>,
    by_group_count: Vec<Breakdown>,
    by_shape: Vec<Breakdown>,
    redundancy: RedundancyAudit,
}

#[derive(Debug, Serialize)]
struct TransferAudit {
    cohort: &'static str,
    residual_definition: &'static str,
    residual_queries: usize,
    overall: DirectionCounts,
    by_shape_or_source: Vec<Breakdown>,
}

#[derive(Debug, Serialize)]
struct Breakdown {
    key: String,
    counts: DirectionCounts,
}

#[derive(Debug, Serialize)]
struct RedundancyAudit {
    maximum_absolute_pair_delta_correlation: f64,
    most_correlated_feature_index: usize,
    most_correlated_feature_name: &'static str,
}

#[derive(Debug, Serialize)]
struct PrimitiveEvaluation {
    primitive: Primitive,
    development: DevelopmentAudit,
    independent_transfer: TransferAudit,
    longmemeval_transfer: TransferAudit,
    mixed_transfer: TransferAudit,
    gates: PrimitiveGates,
}

#[derive(Debug, Serialize)]
struct PrimitiveGates {
    minimum_directional_pairs: bool,
    orientation_at_least_0_70: bool,
    at_least_two_development_sources: bool,
    independent_transfer_not_rejected: bool,
    longmemeval_transfer_not_rejected: bool,
    at_least_one_external_transfer_supported: bool,
    migration_preflight_passes: bool,
}

#[derive(Debug, Serialize)]
struct ResidualCohortDefinition {
    split: &'static str,
    target: &'static str,
    blind_labels_read: bool,
    external_cohorts: &'static str,
    residual_pairs: usize,
    monotonic_impossible_pairs: usize,
}

#[derive(Debug, Serialize)]
struct GroupStrengthDefinition {
    raw: &'static str,
    bounded: &'static str,
    selected_evidence: &'static str,
    unmatched_groups: &'static str,
    learned_function_used: bool,
}

#[derive(Debug, Serialize)]
struct PrimitiveDefinitions {
    weakest: &'static str,
    q25: &'static str,
    q33: &'static str,
    balance: &'static str,
}

#[derive(Debug, Serialize)]
struct Thresholds {
    required_orientation: f64,
    minimum_directional: usize,
    minimum_source_directional: usize,
    required_source_orientation: f64,
    minimum_transfer_directional: usize,
    transfer_rejection_floor: f64,
    transfer_support: f64,
}

#[derive(Debug, Serialize)]
struct ProfileExample {
    a: [f32; 8],
    b: [f32; 8],
    weakest: [f32; 2],
    q25: [f32; 2],
    q33: [f32; 2],
    balance: [f32; 2],
}

#[derive(Debug, Serialize)]
struct Phase89Receipt {
    contract: &'static str,
    mission: &'static str,
    residual_cohort: ResidualCohortDefinition,
    group_strength: GroupStrengthDefinition,
    primitive_definitions: PrimitiveDefinitions,
    thresholds: Thresholds,
    model_artifact: FileIdentity,
    phase_6_receipt: FileIdentity,
    phase_4_receipt: FileIdentity,
    phase_3_receipt: FileIdentity,
    independent_ledger: FileIdentity,
    graded_suite: FileIdentity,
    independent_sidecar: FileIdentity,
    release_sidecar: FileIdentity,
    producer_binary: FileIdentity,
    integrity_gates: IntegrityGates,
    profile_example: ProfileExample,
    residual_rows: Vec<ResidualRow>,
    evaluations: Vec<PrimitiveEvaluation>,
    selected_primitive: Option<Primitive>,
    conclusion: &'static str,
    canonical_rank_evidence_schema_changed: bool,
    canonical_ledger_changed: bool,
    canonical_model_retrained: bool,
    production_promotion_authorized: bool,
    active_engine_after_preflight: &'static str,
}

#[derive(Debug, Serialize)]
struct IntegrityGates {
    phase_4_6_3_verified: bool,
    independent_ledger_byte_identical_to_v9: bool,
    independent_graded_byte_identical_to_v9: bool,
    independent_profiles_finite_bounded_and_aligned: bool,
    release_substrate_bit_identical: bool,
    canonical_residual_count_194: bool,
    canonical_monotonic_impossible_count_28: bool,
    blind_labels_not_read_for_design: bool,
}

#[derive(Debug, Serialize)]
pub(crate) struct Phase89Publication {
    contract: &'static str,
    output: FileIdentity,
    residual_pairs: usize,
    evaluated_primitives: usize,
    selected_primitive: Option<Primitive>,
    conclusion: &'static str,
    production_promotion_authorized: bool,
    active_engine_after_preflight: &'static str,
}

#[derive(Debug, Deserialize)]
struct FrozenPhase6 {
    split: LeakageSplitV3,
    phase_6_verified: bool,
}

#[derive(Debug, Deserialize)]
struct FrozenPhase4 {
    ledger: RelevanceLedgerV3,
    phase_4_verified: bool,
}

#[derive(Debug, Deserialize)]
struct FrozenPhase3 {
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
    rank_evidence_v3: RankEvidenceV3,
    relevance_tier: RelevanceTier,
}

#[derive(Debug, Deserialize)]
struct FrozenOracle {
    document_identity: String,
}

#[derive(Debug, Deserialize)]
struct IndependentSidecar {
    contract: String,
    canonical_ledger: BoundFile,
    canonical_graded_suite: BoundFile,
    pairs: Vec<PairProfile>,
    graded_queries: Vec<GradedProfileQuery>,
}

#[derive(Debug, Deserialize)]
struct PairProfile {
    judgment_identity: String,
    dataset: String,
    positive_document_version: String,
    negative_document_version: String,
    positive_strengths: Vec<f32>,
    negative_strengths: Vec<f32>,
}

#[derive(Debug, Deserialize)]
struct GradedProfileQuery {
    dataset: String,
    query_identity: String,
    candidates: Vec<ProfileCandidate>,
}

#[derive(Debug, Deserialize)]
struct ProfileCandidate {
    document_identity: String,
    strengths: Vec<f32>,
}

#[derive(Debug, Deserialize)]
struct ReleaseSidecar {
    contract: String,
    mixed: ReleaseCohort,
    longmemeval: ReleaseCohort,
    gates: ReleaseGates,
}

#[derive(Debug, Deserialize)]
struct ReleaseCohort {
    queries: Vec<ReleaseProfileQuery>,
}

#[derive(Debug, Deserialize)]
struct ReleaseProfileQuery {
    query_identity: String,
    candidates: Vec<ProfileCandidate>,
}

#[derive(Debug, Deserialize)]
struct ReleaseGates {
    phase_3_verified: bool,
    mixed: Parity,
    longmemeval: Parity,
    strengths_are_finite_and_bounded: bool,
    profile_group_counts_match_evidence: bool,
}

impl ReleaseGates {
    fn all_pass(&self) -> bool {
        self.phase_3_verified
            && self.mixed.all_pass()
            && self.longmemeval.all_pass()
            && self.strengths_are_finite_and_bounded
            && self.profile_group_counts_match_evidence
    }
}

#[derive(Debug, Deserialize)]
struct Parity {
    query_count_equal: bool,
    candidate_pool_identity_equal: bool,
    v2_order_equal: bool,
    v2_score_bits_equal: bool,
    canonical_rank_evidence_equal: bool,
    relevance_tier_equal: bool,
}

impl Parity {
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
struct GradedSuite {
    queries: Vec<GradedQuery>,
}

#[derive(Debug, Deserialize)]
struct GradedQuery {
    query_identity: String,
    candidates: Vec<GradedCandidate>,
}

#[derive(Debug, Deserialize)]
struct GradedCandidate {
    document_identity: String,
    rank_evidence_v3: RankEvidenceV3,
    relevance_tier: RelevanceTier,
    grade: u8,
}

#[derive(Debug, Deserialize)]
struct BoundFile {
    #[allow(dead_code)]
    path: PathBuf,
    #[allow(dead_code)]
    bytes: u64,
    sha256: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preregistered_profile_example_has_better_tail_and_balance_for_a() {
        let example = profile_example();
        assert!(example.weakest[0] > example.weakest[1]);
        assert!(example.q25[0] > example.q25[1]);
        assert!(example.q33[0] > example.q33[1]);
        assert!(example.balance[0] > example.balance[1]);
    }

    #[test]
    fn unmatched_groups_do_not_redefine_matched_tail() {
        let profile = [0.0, 0.8, 0.6, 0.0];
        assert_eq!(
            Primitive::Weakest.value(&profile).to_bits(),
            0.6_f32.to_bits()
        );
        assert!(Primitive::Balance.value(&profile) > 0.9);
    }
}
