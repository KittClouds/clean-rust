use northstar_rl_core::{Digest, EnvStepRecord, identified, identity};

use crate::{Error, EvaluationAggregate, EvaluationReceipt, EvaluationSpec, Result};

pub fn evaluate_step_tapes(
    spec: &EvaluationSpec,
    subject_class: &str,
    subject_id: Digest,
    episodes: &[(Digest, Vec<EnvStepRecord>)],
) -> Result<EvaluationReceipt> {
    if !spec.deterministic_policy_inference || spec.policy_selection_uses_evaluation {
        return Err(Error::Contract(
            "evaluation must use deterministic inference and cannot select on evaluation".into(),
        ));
    }
    let expected = &spec.evaluation_episode_ids;
    let actual = episodes.iter().map(|(id, _)| *id).collect::<Vec<_>>();
    if &actual != expected || episodes.iter().any(|(_, steps)| steps.is_empty()) {
        return Err(Error::Contract(
            "evaluation episodes do not exactly match the frozen scorecard".into(),
        ));
    }
    let mut normalized_return = 0.0;
    let mut gross_pnl = 0.0;
    let mut turnover = 0.0;
    let mut friction = 0.0;
    let mut max_drawdown = 0.0_f64;
    let mut absolute_exposure = 0.0;
    let mut step_count = 0_u64;
    let mut terminal_count = 0_u64;
    for (_, steps) in episodes {
        for step in steps {
            if !step.reward.is_finite()
                || step.reward_primitive_vector.iter().any(|v| !v.is_finite())
            {
                return Err(Error::Contract("non-finite evaluation primitive".into()));
            }
            normalized_return += step.reward;
            gross_pnl += step.reward_primitive_vector[0];
            turnover += step.reward_primitive_vector[4];
            friction += step.reward_primitive_vector[8];
            absolute_exposure += step.reward_primitive_vector[9].abs();
            max_drawdown = max_drawdown.max(step.reward_primitive_vector[11]);
            step_count += 1;
            terminal_count += u64::from(step.terminated || step.truncated);
        }
    }
    let available = [
        ("normalized_return_sum", normalized_return),
        ("gross_mark_to_market_sum", gross_pnl),
        ("turnover_sum", turnover),
        ("total_friction_sum", friction),
        ("max_drawdown", max_drawdown),
        (
            "mean_absolute_exposure",
            absolute_exposure / step_count as f64,
        ),
        ("step_count", step_count as f64),
        ("terminal_count", terminal_count as f64),
    ];
    let mut aggregates = Vec::with_capacity(spec.metrics.len());
    for rule in &spec.metrics {
        let value = available
            .iter()
            .find(|(id, _)| *id == rule.metric_id)
            .map(|(_, value)| *value)
            .ok_or_else(|| {
                Error::Contract(format!(
                    "evaluation metric {} is not implemented",
                    rule.metric_id
                ))
            })?;
        aggregates.push(EvaluationAggregate {
            metric_id: rule.metric_id.clone(),
            value,
            episode_count: episodes.len() as u64,
        });
    }
    let deterministic_rebuild_hash =
        identity(b"northstar-evaluation-step-input-v1", &episodes.to_vec())?;
    let receipt = EvaluationReceipt {
        schema_version: "EVALUATION_RECEIPT_V1".into(),
        evaluation_spec_id: spec.evaluation_spec_id,
        subject_class: subject_class.into(),
        subject_id,
        episode_ids: actual,
        aggregates,
        deterministic_rebuild_hash,
        receipt_id: Digest::ZERO,
    };
    Ok(identified(
        b"northstar-evaluation-receipt-v1",
        receipt,
        |value, digest| value.receipt_id = digest,
    )?)
}
