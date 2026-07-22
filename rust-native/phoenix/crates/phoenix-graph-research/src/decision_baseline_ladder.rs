use compact_str::{format_compact, CompactString};
use hashbrown::HashSet;
use serde::Serialize;

use crate::{
    evaluate_native_decisions, DecisionBaselineLadderReport, DecisionBaselineResult,
    DecisionBaselineRung, DecisionBaselineSubmission, GraphDecisionSplit,
    NativeDecisionEvaluationError, NativeDecisionEvaluationProtocol,
    DECISION_BASELINE_LADDER_SCHEMA,
};

pub fn run_native_decision_baseline_ladder(
    tables: &crate::FrozenDecisionTrajectoryTables,
    protocol: &NativeDecisionEvaluationProtocol,
    submissions: Vec<DecisionBaselineSubmission>,
) -> Result<DecisionBaselineLadderReport, NativeDecisionEvaluationError> {
    if protocol.partition == GraphDecisionSplit::Test {
        return Err(NativeDecisionEvaluationError::TestLocked);
    }
    if submissions.len() != DecisionBaselineRung::REQUIRED.len()
        || submissions
            .iter()
            .zip(DecisionBaselineRung::REQUIRED)
            .any(|(submission, expected)| submission.rung != expected)
    {
        return Err(NativeDecisionEvaluationError::BaselineOrder);
    }
    let mut model_ids = HashSet::with_capacity(submissions.len());
    let mut rungs = Vec::with_capacity(submissions.len());
    for submission in submissions {
        if submission.model_id.trim().is_empty()
            || submission.feature_manifest_id.trim().is_empty()
            || !model_ids.insert(submission.model_id.clone())
            || submission.enabled_feature_families != submission.rung.enabled_features()
        {
            return Err(NativeDecisionEvaluationError::InvalidInput(
                "baseline identity or feature manifest",
            ));
        }
        if submission
            .inputs
            .iter()
            .any(|input| input.prediction.producer_model_id != submission.model_id)
        {
            return Err(NativeDecisionEvaluationError::Identity(
                "baseline prediction producer",
            ));
        }
        let report = evaluate_native_decisions(tables, protocol, &submission.inputs)?;
        rungs.push(DecisionBaselineResult {
            rung: submission.rung,
            isolated_feature: submission.rung.isolated_feature(),
            model_id: submission.model_id,
            feature_manifest_id: submission.feature_manifest_id,
            enabled_feature_families: submission.enabled_feature_families,
            report,
        });
    }
    let mut report = DecisionBaselineLadderReport {
        schema_version: DECISION_BASELINE_LADDER_SCHEMA.into(),
        ladder_id: "pending".into(),
        protocol_id: protocol.protocol_id.clone(),
        dataset_id: protocol.dataset_id.clone(),
        single_task_only: true,
        test_accessed: false,
        rungs,
    };
    report.ladder_id = content_id(&report)?;
    Ok(report)
}

fn content_id(value: &impl Serialize) -> Result<CompactString, NativeDecisionEvaluationError> {
    Ok(format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}
