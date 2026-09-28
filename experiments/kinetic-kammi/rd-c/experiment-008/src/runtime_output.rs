use crate::routing::Lane;
use crate::runtime::{CrashResult, GroupResult, TraceRow};
use std::{
    fs::File,
    io::{BufWriter, Write},
    path::Path,
};

pub fn write_traces(
    path: impl AsRef<Path>,
    rows: &[TraceRow],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(128 * 1024, File::create(path)?);
    writeln!(
        writer,
        "world_id,lane,budget,lambda,offer_mode,episode_id,source_id,signal_episode_id,offer_version_initial,offer_version_used,offer_availability,offer_independent,offer_history_bucket,offer_age_bucket,quote_price,offer_request_cost_units,query_kind,active,proposed,correct,baseline_right,after_right,delta,estimated_delta,estimated_value"
    )?;
    for row in rows {
        writeln!(
            writer,
            "{},{},{},{:.3},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{:.6},{:.6}",
            row.world_id,
            row.lane,
            row.budget,
            row.lambda,
            row.offer_mode,
            row.episode_id,
            row.source_id,
            row.signal_episode_id,
            row.offer_version_initial,
            row.offer_version_used,
            row.offer_availability,
            row.offer_independent,
            row.offer_history_bucket,
            row.offer_age_bucket,
            row.quote_price,
            row.offer_request_cost_units,
            row.query_kind,
            row.active,
            row.proposed.map_or(String::new(), |v| v.to_string()),
            row.correct,
            row.baseline_right,
            row.after_right,
            row.delta,
            row.estimated_delta,
            row.estimated_value
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

pub fn write_group_stats(
    path: impl AsRef<Path>,
    rows: &[GroupResult],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(128 * 1024, File::create(path)?);
    writeln!(
        writer,
        "world_id,stratum,lane,budget,lambda,offer_mode,episodes,baseline_right,baseline_wrong,completed,completion_delta,wrong_to_right,right_to_wrong,unresolved_baseline_right,unresolved_baseline_wrong,avoided_wrong,confirmed,contradicted,unknown,failed,offers_obtained,offer_refresh_requests,query_attempts,paid_queries,query_charges,offer_charges,query_cost_units,offer_cost_units,total_cost_units,unused_budget,task_p50_us,task_p95_us,plan_elapsed_us,observer_time_us,journal_bytes,offer_receipt_bytes,receipt_identity,replay_identity_ok,duplicate_charges,illegal_commits,task_action_effects,random_call_residual"
    )?;
    for row in rows {
        let o = row.outcomes;
        let total_cost = row.query_cost_units + row.offer_cost_units;
        let fields = [
            row.world_id.to_string(),
            row.stratum.clone(),
            row.lane.clone(),
            row.budget.to_string(),
            format!("{:.3}", row.lambda),
            row.offer_mode.clone(),
            row.total_episodes.to_string(),
            o.baseline_right.to_string(),
            o.baseline_wrong.to_string(),
            row.completed.to_string(),
            o.delta().to_string(),
            o.wrong_to_right.to_string(),
            o.right_to_wrong.to_string(),
            o.unresolved_baseline_right.to_string(),
            o.unresolved_baseline_wrong.to_string(),
            o.avoided_wrong.to_string(),
            o.query_confirmed.to_string(),
            o.query_contradicted.to_string(),
            o.query_unknown.to_string(),
            o.query_failed.to_string(),
            row.offers_obtained.to_string(),
            row.offer_refresh_requests.to_string(),
            row.query_attempts.to_string(),
            row.paid_queries.to_string(),
            row.query_charges.to_string(),
            row.offer_charges.to_string(),
            row.query_cost_units.to_string(),
            row.offer_cost_units.to_string(),
            total_cost.to_string(),
            row.unused_budget.to_string(),
            row.task_latency_us.to_string(),
            row.task_latency_p95_us.to_string(),
            row.plan_elapsed_us.to_string(),
            row.observer_time_us.to_string(),
            row.journal_bytes.to_string(),
            row.offer_receipt_bytes.to_string(),
            row.receipt_identity.clone(),
            row.replay_identity_ok.to_string(),
            row.duplicate_charges.to_string(),
            row.illegal_commits.to_string(),
            row.task_action_effects.to_string(),
            row.random_call_residual.to_string(),
        ];
        writeln!(writer, "{}", fields.join(","))?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

pub fn write_crash_results(
    path: impl AsRef<Path>,
    rows: &[CrashResult],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(8 * 1024, File::create(path)?);
    writeln!(
        writer,
        "boundary,result,endpoint_attempts,retries,paid_charges,paid_cost_units,journal_paid_requests,endpoint_effects,duplicate_charges,replay_identity_ok"
    )?;
    for r in rows {
        writeln!(
            writer,
            "{},{},{},{},{},{},{},{},{},{}",
            r.boundary,
            r.result,
            r.endpoint_attempts,
            r.retries,
            r.paid_charges,
            r.paid_cost_units,
            r.journal_paid_requests,
            r.endpoint_effects,
            r.duplicate_charges,
            r.replay_identity_ok
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

pub fn write_matched_rows(
    path: impl AsRef<Path>,
    references: &[GroupResult],
    random: &[GroupResult],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(16 * 1024, File::create(path)?);
    writeln!(
        writer,
        "paired_world,reference_lane,budget,lambda,offer_mode,reference_calls,random_calls,call_residual,reference_query_spend,random_query_spend,query_spend_residual,reference_offer_spend,random_offer_spend,offer_spend_residual,reference_total_spend,random_total_spend,total_spend_residual"
    )?;
    for reference in references {
        let Some(random_lane) = (match reference.lane.as_str() {
            "offer_simple" => Some(Lane::MatchedRandomSimple),
            "offer_fitted" => Some(Lane::MatchedRandomFitted),
            "shuffled_offers" => Some(Lane::MatchedRandomShuffled),
            _ => None,
        }) else {
            continue;
        };
        if let Some(control) = random.iter().find(|g| {
            g.world_id == reference.world_id
                && g.budget == reference.budget
                && g.lambda == reference.lambda
                && g.offer_mode == reference.offer_mode
                && g.lane == random_lane.label()
        }) {
            let reference_total = reference.query_cost_units + reference.offer_cost_units;
            let random_total = control.query_cost_units + control.offer_cost_units;
            let fields = [
                reference.world_id.to_string(),
                reference.lane.clone(),
                reference.budget.to_string(),
                format!("{:.3}", reference.lambda),
                reference.offer_mode.clone(),
                reference.paid_queries.to_string(),
                control.paid_queries.to_string(),
                (control.paid_queries as i64 - reference.paid_queries as i64).to_string(),
                reference.query_cost_units.to_string(),
                control.query_cost_units.to_string(),
                (control.query_cost_units as i64 - reference.query_cost_units as i64).to_string(),
                reference.offer_cost_units.to_string(),
                control.offer_cost_units.to_string(),
                (control.offer_cost_units as i64 - reference.offer_cost_units as i64).to_string(),
                reference_total.to_string(),
                random_total.to_string(),
                (random_total as i64 - reference_total as i64).to_string(),
            ];
            writeln!(writer, "{}", fields.join(","))?;
        }
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}
