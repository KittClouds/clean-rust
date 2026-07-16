use crate::{
    DerivedFeatureRow, RankingEvaluationError, RankingEvaluationReport, RankingMetrics,
    RankingTask, ResearchSplit, SplitQueryOmissions, StructuralBaselineFamily,
    StructuralBaselineRun, TaskRankingReport, TrainTopologyFeatureSnapshot,
    RANKING_EVALUATION_SCHEMA,
};
use compact_str::{format_compact, CompactString};
use serde::Serialize;

pub fn evaluate_ranking_scores(
    rows: &[DerivedFeatureRow],
    scores: &[f32],
    split: ResearchSplit,
) -> Result<Option<RankingMetrics>, RankingEvaluationError> {
    if rows.len() != scores.len() {
        return Err(RankingEvaluationError::ScoreShape);
    }
    if scores.iter().any(|score| !score.is_finite()) {
        return Err(RankingEvaluationError::NonFiniteScore);
    }
    let mut order = rows
        .iter()
        .enumerate()
        .filter_map(|(index, row)| (row.split == split).then_some(index))
        .collect::<Vec<_>>();
    if order.is_empty() {
        return Ok(None);
    }
    order.sort_unstable_by_key(|&index| (rows[index].positive_index, rows[index].candidate));
    let mut reciprocal_rank = 0.0_f64;
    let mut hits = [0.0_f64; 3];
    let mut queries = 0_u64;
    let mut candidates = 0_u64;
    let mut start = 0_usize;
    while start < order.len() {
        let query = rows[order[start]].positive_index;
        let mut end = start + 1;
        while end < order.len() && rows[order[end]].positive_index == query {
            end += 1;
        }
        let group = &order[start..end];
        if group
            .iter()
            .any(|&index| rows[index].split != rows[group[0]].split)
        {
            return Err(RankingEvaluationError::MixedGroupSplit);
        }
        let positives = group
            .iter()
            .filter(|&&index| rows[index].label)
            .copied()
            .collect::<Vec<_>>();
        if positives.len() != 1 {
            return Err(RankingEvaluationError::InvalidGroup);
        }
        if group.len() < 2 {
            start = end;
            continue;
        }
        let positive_score = scores[positives[0]];
        let mut greater = 0_u64;
        let mut tied_negatives = 0_u64;
        for &index in group {
            if rows[index].label {
                continue;
            }
            if scores[index] > positive_score {
                greater += 1;
            } else if scores[index] == positive_score {
                tied_negatives += 1;
            }
        }
        let average_rank = 1.0 + greater as f64 + tied_negatives as f64 * 0.5;
        reciprocal_rank += 1.0 / average_rank;
        let tie_block = (tied_negatives + 1) as f64;
        for (slot, cutoff) in [1_u64, 3, 10].into_iter().enumerate() {
            hits[slot] += ((cutoff as i64 - greater as i64) as f64 / tie_block).clamp(0.0, 1.0);
        }
        queries += 1;
        candidates += group.len() as u64;
        start = end;
    }
    if queries == 0 {
        return Ok(None);
    }
    Ok(Some(RankingMetrics {
        queries,
        candidates,
        mean_reciprocal_rank: reciprocal_rank / queries as f64,
        hits_at_1: hits[0] / queries as f64,
        hits_at_3: hits[1] / queries as f64,
        hits_at_10: hits[2] / queries as f64,
    }))
}

pub fn run_structural_ranking_baselines(
    features: &TrainTopologyFeatureSnapshot,
) -> Result<RankingEvaluationReport, RankingEvaluationError> {
    validate_identity(features)?;
    let link_prediction = task_report(
        RankingTask::TypedLinkPrediction,
        &features.link_rows,
        &[
            StructuralBaselineFamily::LinkCommonNeighbors,
            StructuralBaselineFamily::LinkRelationPrior,
            StructuralBaselineFamily::LinkPreferentialAttachment,
        ],
    )?;
    let hyperedge_role_completion = task_report(
        RankingTask::HyperedgeRoleCompletion,
        &features.incidence_rows,
        &[
            StructuralBaselineFamily::RoleParticipantPrior,
            StructuralBaselineFamily::RoleGlobalPrior,
            StructuralBaselineFamily::RoleStructuralComposite,
        ],
    )?;
    let mut report = RankingEvaluationReport {
        schema_version: RANKING_EVALUATION_SCHEMA.into(),
        report_id: "pending".into(),
        derivation_id: features.derivation_id.clone(),
        evaluation_protocol_id: features.evaluation_protocol_id.clone(),
        tie_policy: "filtered candidates; average rank for ties; fractional Hits@K at tie boundary"
            .into(),
        link_prediction,
        hyperedge_role_completion,
    };
    report.report_id = content_id(&report)?;
    Ok(report)
}

fn task_report(
    task: RankingTask,
    rows: &[DerivedFeatureRow],
    families: &[StructuralBaselineFamily],
) -> Result<TaskRankingReport, RankingEvaluationError> {
    let mut runs = Vec::with_capacity(families.len());
    for &family in families {
        let scores = rows
            .iter()
            .map(|row| structural_score(family, &row.features))
            .collect::<Vec<_>>();
        runs.push(StructuralBaselineRun {
            family,
            train: evaluate_ranking_scores(rows, &scores, ResearchSplit::Train)?,
            validation: evaluate_ranking_scores(rows, &scores, ResearchSplit::Validation)?,
            held_out_test: None,
        });
    }
    let selected = select_family(&runs);
    if let Some(family) = selected {
        let scores = rows
            .iter()
            .map(|row| structural_score(family, &row.features))
            .collect::<Vec<_>>();
        let test = evaluate_ranking_scores(rows, &scores, ResearchSplit::Test)?;
        if let Some(run) = runs.iter_mut().find(|run| run.family == family) {
            run.held_out_test = test;
        }
    }
    Ok(TaskRankingReport {
        task,
        status: if selected.is_some() {
            CompactString::new("selected-on-validation")
        } else {
            CompactString::new("insufficient-validation-queries")
        },
        selected_family: selected,
        selection_rule: "highest validation filtered MRR; highest validation Hits@10 tie-break; stable family order final tie-break".into(),
        zero_negative_queries_omitted: SplitQueryOmissions {
            train: zero_negative_queries(rows, ResearchSplit::Train),
            validation: zero_negative_queries(rows, ResearchSplit::Validation),
            test: zero_negative_queries(rows, ResearchSplit::Test),
        },
        runs,
    })
}

fn zero_negative_queries(rows: &[DerivedFeatureRow], split: ResearchSplit) -> u64 {
    let mut positives = rows
        .iter()
        .filter(|row| row.split == split && row.label)
        .map(|row| row.positive_index)
        .collect::<Vec<_>>();
    let mut negatives = rows
        .iter()
        .filter(|row| row.split == split && !row.label)
        .map(|row| row.positive_index)
        .collect::<Vec<_>>();
    positives.sort_unstable();
    positives.dedup();
    negatives.sort_unstable();
    negatives.dedup();
    positives
        .into_iter()
        .filter(|query| negatives.binary_search(query).is_err())
        .count() as u64
}

fn select_family(runs: &[StructuralBaselineRun]) -> Option<StructuralBaselineFamily> {
    let mut selected: Option<(StructuralBaselineFamily, &RankingMetrics)> = None;
    for run in runs {
        let Some(metrics) = run.validation.as_ref() else {
            continue;
        };
        let replace = selected.is_none_or(|(_, current)| {
            metrics.mean_reciprocal_rank > current.mean_reciprocal_rank
                || (metrics.mean_reciprocal_rank == current.mean_reciprocal_rank
                    && metrics.hits_at_10 > current.hits_at_10)
        });
        if replace {
            selected = Some((run.family, metrics));
        }
    }
    selected.map(|(family, _)| family)
}

fn structural_score(family: StructuralBaselineFamily, features: &[f32; 16]) -> f32 {
    match family {
        StructuralBaselineFamily::LinkCommonNeighbors => features[6] + features[7],
        StructuralBaselineFamily::LinkRelationPrior => features[4] + features[5],
        StructuralBaselineFamily::LinkPreferentialAttachment => features[10],
        StructuralBaselineFamily::RoleParticipantPrior => features[1],
        StructuralBaselineFamily::RoleGlobalPrior => features[3],
        StructuralBaselineFamily::RoleStructuralComposite => features[..8].iter().copied().sum(),
    }
}

fn validate_identity(
    features: &TrainTopologyFeatureSnapshot,
) -> Result<(), RankingEvaluationError> {
    let mut candidate = features.clone();
    candidate.derivation_id = "pending".into();
    if content_id(&candidate)? != features.derivation_id
        || !features.audit.train_only
        || !features.audit.leave_one_positive_out
        || features.feature_certificates.iter().any(|row| {
            !row.label_free || !row.leave_one_positive_out || row.fit_split != ResearchSplit::Train
        })
    {
        return Err(RankingEvaluationError::Identity);
    }
    Ok(())
}

fn content_id(value: &impl Serialize) -> Result<CompactString, RankingEvaluationError> {
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}
