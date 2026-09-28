use std::{collections::BTreeMap, io::Write, path::Path};

use hashbrown::HashMap;

use crate::{
    domain::WorldBank,
    runtime::{CrashResult, GroupResult, TraceRow},
};

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct SummaryKey {
    lane: String,
    stratum: String,
    budget: usize,
    lambda_milli: i32,
    offer_mode: String,
}

#[derive(Default)]
struct SummaryValues {
    deltas: Vec<f64>,
    costs: Vec<f64>,
    queries: Vec<f64>,
    times: Vec<f64>,
    task_p95s: Vec<f64>,
    plan_times: Vec<f64>,
    bytes: Vec<f64>,
    wrong_to_right: u64,
    right_to_wrong: u64,
    unresolved_right: u64,
    unresolved_wrong: u64,
    avoided_wrong: u64,
    positive_worlds: u32,
    negative_worlds: u32,
    completed: u64,
}

pub fn write_outputs(
    run_dir: &Path,
    heldout: &[WorldBank],
    traces: &[TraceRow],
    groups: &[GroupResult],
    crashes: &[CrashResult],
    audit_rows: usize,
    deterministic_groups: usize,
) -> Result<(), Box<dyn std::error::Error>> {
    write_world_summary(run_dir.join("world-summary.csv"), groups)?;
    write_summary(run_dir.join("summary.csv"), groups)?;
    write_frontier(run_dir.join("completion-cost-frontier.csv"), groups)?;
    write_calibration(run_dir.join("value-calibration.csv"), traces)?;
    write_offer_quality(run_dir.join("offer-quality-calibration.csv"), traces)?;
    crate::runtime::write_matched_rows(
        run_dir.join("matched-random-audit.csv"),
        groups,
        &groups
            .iter()
            .filter(|g| g.lane.starts_with("matched_random_"))
            .cloned()
            .collect::<Vec<_>>(),
    )?;
    crate::runtime::write_crash_results(run_dir.join("crash-results.csv"), crashes)?;
    let report = build_report(
        heldout,
        traces,
        groups,
        crashes,
        audit_rows,
        deterministic_groups,
    );
    let path = run_dir.join("benchmark-report.md");
    let mut file = std::fs::File::create(&path)?;
    file.write_all(report.as_bytes())?;
    file.sync_all()?;
    Ok(())
}

fn write_world_summary(
    path: impl AsRef<Path>,
    groups: &[GroupResult],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut w = std::io::BufWriter::with_capacity(128 * 1024, std::fs::File::create(path)?);
    writeln!(
        w,
        "world_id,stratum,lane,budget,lambda,offer_mode,baseline_completion,completion,completion_delta,wrong_to_right,right_to_wrong,unresolved_baseline_right,unresolved_baseline_wrong,avoided_wrong,offers_obtained,refresh_requests,paid_queries,query_cost,offer_cost,total_cost,unused_budget,task_p50_us,observer_time_us,journal_bytes,offer_receipt_bytes,replay_identity_ok,duplicate_charges,illegal_commits,task_p95_us,plan_elapsed_us"
    )?;
    let baseline = baselines(groups);
    for g in groups {
        let b = baseline.get(&g.world_id).copied().unwrap_or(0);
        writeln!(
            w,
            "{},{},{},{},{:.3},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
            g.world_id,
            g.stratum,
            g.lane,
            g.budget,
            g.lambda,
            g.offer_mode,
            b,
            g.completed,
            g.completed as i64 - b as i64,
            g.outcomes.wrong_to_right,
            g.outcomes.right_to_wrong,
            g.outcomes.unresolved_baseline_right,
            g.outcomes.unresolved_baseline_wrong,
            g.outcomes.avoided_wrong,
            g.offers_obtained,
            g.offer_refresh_requests,
            g.paid_queries,
            g.query_cost_units,
            g.offer_cost_units,
            g.query_cost_units + g.offer_cost_units,
            g.unused_budget,
            g.task_latency_us,
            g.observer_time_us,
            g.journal_bytes,
            g.offer_receipt_bytes,
            g.replay_identity_ok,
            g.duplicate_charges,
            g.illegal_commits,
            g.task_latency_p95_us,
            g.plan_elapsed_us
        )?;
    }
    w.flush()?;
    w.get_ref().sync_all()?;
    Ok(())
}

fn write_summary(
    path: impl AsRef<Path>,
    groups: &[GroupResult],
) -> Result<(), Box<dyn std::error::Error>> {
    let baseline = baselines(groups);
    let mut map = HashMap::<SummaryKey, SummaryValues>::with_capacity(256);
    for g in groups {
        let key = SummaryKey {
            lane: g.lane.clone(),
            stratum: g.stratum.clone(),
            budget: g.budget,
            lambda_milli: (g.lambda * 1000.0).round() as i32,
            offer_mode: g.offer_mode.clone(),
        };
        let v = map.entry(key).or_default();
        let delta = g.completed as i64 - baseline.get(&g.world_id).copied().unwrap_or(0) as i64;
        v.deltas.push(delta as f64);
        v.costs
            .push((g.query_cost_units + g.offer_cost_units) as f64);
        v.queries.push(g.paid_queries as f64);
        v.times.push(g.task_latency_us as f64);
        v.task_p95s.push(g.task_latency_p95_us as f64);
        v.plan_times.push(g.plan_elapsed_us as f64);
        v.bytes
            .push((g.journal_bytes + g.offer_receipt_bytes) as f64);
        v.wrong_to_right += g.outcomes.wrong_to_right as u64;
        v.right_to_wrong += g.outcomes.right_to_wrong as u64;
        v.unresolved_right += g.outcomes.unresolved_baseline_right as u64;
        v.unresolved_wrong += g.outcomes.unresolved_baseline_wrong as u64;
        v.avoided_wrong += g.outcomes.avoided_wrong as u64;
        v.completed += g.completed as u64;
        if delta > 0 {
            v.positive_worlds += 1
        } else if delta < 0 {
            v.negative_worlds += 1
        }
    }
    let mut entries = map.into_iter().collect::<Vec<_>>();
    entries.sort_by(|(a, _), (b, _)| {
        a.lane
            .cmp(&b.lane)
            .then(a.stratum.cmp(&b.stratum))
            .then(a.budget.cmp(&b.budget))
            .then(a.lambda_milli.cmp(&b.lambda_milli))
            .then(a.offer_mode.cmp(&b.offer_mode))
    });
    let mut w = std::io::BufWriter::with_capacity(64 * 1024, std::fs::File::create(path)?);
    writeln!(
        w,
        "lane,stratum,budget,lambda,offer_mode,worlds,mean_completion_delta,sd_world_completion_delta,positive_worlds,negative_worlds,mean_paid_queries,mean_query_cost_units,mean_offer_cost_units,mean_total_cost_units,mean_world_p50_task_us,p50_world_p50_task_us,p95_world_p50_task_us,mean_journal_bytes,wrong_to_right,right_to_wrong,unresolved_baseline_right,unresolved_baseline_wrong,avoided_wrong,mean_world_p95_task_us,p95_world_p95_task_us,mean_plan_elapsed_us"
    )?;
    for (k, v) in entries {
        let n = v.deltas.len();
        let mean = avg(&v.deltas);
        let sd = stddev(&v.deltas, mean);
        let latency_p50 = quantile(&mut v.times.clone(), 0.50);
        let latency_p95 = quantile(&mut v.times.clone(), 0.95);
        writeln!(
            w,
            "{},{},{},{:.3},{},{},{:.4},{:.4},{},{},{:.3},{:.3},{:.3},{:.3},{:.2},{:.2},{:.2},{:.1},{},{},{},{},{},{:.2},{:.2},{:.2}",
            k.lane,
            k.stratum,
            k.budget,
            k.lambda_milli as f32 / 1000.0,
            k.offer_mode,
            n,
            mean,
            sd,
            v.positive_worlds,
            v.negative_worlds,
            avg(&v.queries),
            query_cost_from_groups(groups, &k),
            offer_cost_from_groups(groups, &k),
            avg(&v.costs),
            avg(&v.times),
            latency_p50,
            latency_p95,
            avg(&v.bytes),
            v.wrong_to_right,
            v.right_to_wrong,
            v.unresolved_right,
            v.unresolved_wrong,
            v.avoided_wrong,
            avg(&v.task_p95s),
            quantile(&mut v.task_p95s.clone(), 0.95),
            avg(&v.plan_times)
        )?;
    }
    w.flush()?;
    w.get_ref().sync_all()?;
    Ok(())
}

fn write_frontier(
    path: impl AsRef<Path>,
    groups: &[GroupResult],
) -> Result<(), Box<dyn std::error::Error>> {
    let baseline = baselines(groups);
    let mut map = BTreeMap::<(String, usize, i32, String), Vec<(f64, f64, f64)>>::new();
    for g in groups {
        if g.lane == "no_inspection" || g.lane == "evaluation_oracle" {
            continue;
        }
        let delta = g.completed as f64 - baseline.get(&g.world_id).copied().unwrap_or(0) as f64;
        map.entry((
            g.lane.clone(),
            g.budget,
            (g.lambda * 1000.0).round() as i32,
            g.offer_mode.clone(),
        ))
        .or_default()
        .push((
            delta,
            (g.query_cost_units + g.offer_cost_units) as f64,
            g.paid_queries as f64,
        ));
    }
    let mut w = std::io::BufWriter::with_capacity(32 * 1024, std::fs::File::create(path)?);
    writeln!(
        w,
        "lane,budget,lambda,offer_mode,worlds,mean_completion_gain,sd_world_gain,mean_total_cost_units,mean_paid_queries,positive_gain_worlds"
    )?;
    for ((lane, budget, lambda, mode), rows) in map {
        let ds = rows.iter().map(|r| r.0).collect::<Vec<_>>();
        let costs = rows.iter().map(|r| r.1).collect::<Vec<_>>();
        let calls = rows.iter().map(|r| r.2).collect::<Vec<_>>();
        let mean = avg(&ds);
        writeln!(
            w,
            "{lane},{budget},{:.3},{mode},{},{mean:.4},{:.4},{:.3},{:.3},{}",
            lambda as f32 / 1000.0,
            rows.len(),
            stddev(&ds, mean),
            avg(&costs),
            avg(&calls),
            ds.iter().filter(|d| **d > 0.0).count()
        )?;
    }
    w.flush()?;
    w.get_ref().sync_all()?;
    Ok(())
}

fn write_calibration(
    path: impl AsRef<Path>,
    traces: &[TraceRow],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut grouped = HashMap::<(String, usize, i32, String), Vec<&TraceRow>>::new();
    for t in traces {
        if t.lane.starts_with("matched_random_") || t.lane == "evaluation_oracle" {
            continue;
        }
        grouped
            .entry((
                t.lane.clone(),
                t.budget,
                (t.lambda * 1000.0).round() as i32,
                t.offer_mode.clone(),
            ))
            .or_default()
            .push(t);
    }
    let mut w = std::io::BufWriter::with_capacity(32 * 1024, std::fs::File::create(path)?);
    writeln!(
        w,
        "lane,budget,lambda,offer_mode,score_bin,queries,mean_predicted_delta,mean_realized_delta,mean_predicted_value,mean_realized_net_value,mean_query_price,worlds"
    )?;
    let mut entries = grouped.into_iter().collect::<Vec<_>>();
    entries.sort_by(|a, b| a.0.cmp(&b.0));
    for ((lane, budget, lm, mode), mut rows) in entries {
        rows.sort_by(|a, b| a.estimated_value.total_cmp(&b.estimated_value));
        let chunks = rows.len().clamp(1, 5);
        for bin in 0..chunks {
            let start = bin * rows.len() / chunks;
            let end = (bin + 1) * rows.len() / chunks;
            let slice = &rows[start..end];
            let pd = slice
                .iter()
                .map(|t| t.estimated_delta as f64)
                .collect::<Vec<_>>();
            let rd = slice.iter().map(|t| t.delta as f64).collect::<Vec<_>>();
            let pv = slice
                .iter()
                .map(|t| t.estimated_value as f64)
                .collect::<Vec<_>>();
            let rv = slice
                .iter()
                .map(|t| {
                    t.delta as f64
                        - (lm as f64 / 1000.0) * t.quote_price as f64
                        - crate::routing::LAMBDA_OFFER_COST as f64
                            * t.offer_request_cost_units as f64
                })
                .collect::<Vec<_>>();
            let price = slice
                .iter()
                .map(|t| t.quote_price as f64)
                .collect::<Vec<_>>();
            let worlds = slice
                .iter()
                .map(|t| t.world_id)
                .collect::<std::collections::HashSet<_>>()
                .len();
            writeln!(
                w,
                "{lane},{budget},{:.3},{mode},{},{},{:.5},{:.5},{:.5},{:.5},{:.3},{worlds}",
                lm as f32 / 1000.0,
                bin + 1,
                slice.len(),
                avg(&pd),
                avg(&rd),
                avg(&pv),
                avg(&rv),
                avg(&price)
            )?;
        }
    }
    w.flush()?;
    w.get_ref().sync_all()?;
    Ok(())
}

fn write_offer_quality(
    path: impl AsRef<Path>,
    traces: &[TraceRow],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut map = HashMap::<(String, usize, i32, String, String), Vec<&TraceRow>>::new();
    for t in traces {
        if t.lane.starts_with("matched_random_") || t.lane == "evaluation_oracle" {
            continue;
        }
        let quality = if t.offer_history_bucket <= 1 {
            "low_history"
        } else if t.offer_history_bucket == 2 {
            "mid_history"
        } else {
            "high_history"
        };
        let availability = match t.offer_availability {
            0 => "available",
            1 => "degraded",
            _ => "unavailable",
        };
        let key = (
            t.lane.clone(),
            t.budget,
            (t.lambda * 1000.0).round() as i32,
            t.offer_mode.clone(),
            format!(
                "{quality}_{availability}_independent_{}",
                t.offer_independent
            ),
        );
        map.entry(key).or_default().push(t);
    }
    let mut rows = map.into_iter().collect::<Vec<_>>();
    rows.sort_by(|a, b| a.0.cmp(&b.0));
    let mut w = std::io::BufWriter::with_capacity(32 * 1024, std::fs::File::create(path)?);
    writeln!(
        w,
        "lane,budget,lambda,offer_mode,offer_quality_bin,queries,mean_predicted_delta,mean_realized_delta,mean_predicted_value,mean_realized_net_value"
    )?;
    for ((lane, budget, lm, mode, quality), samples) in rows {
        let p = samples
            .iter()
            .map(|t| t.estimated_delta as f64)
            .collect::<Vec<_>>();
        let d = samples.iter().map(|t| t.delta as f64).collect::<Vec<_>>();
        let pv = samples
            .iter()
            .map(|t| t.estimated_value as f64)
            .collect::<Vec<_>>();
        let rv = samples
            .iter()
            .map(|t| {
                t.delta as f64
                    - lm as f64 / 1000.0 * t.quote_price as f64
                    - crate::routing::LAMBDA_OFFER_COST as f64 * t.offer_request_cost_units as f64
            })
            .collect::<Vec<_>>();
        writeln!(
            w,
            "{lane},{budget},{:.3},{mode},{quality},{},{:.5},{:.5},{:.5},{:.5}",
            lm as f32 / 1000.0,
            samples.len(),
            avg(&p),
            avg(&d),
            avg(&pv),
            avg(&rv)
        )?;
    }
    w.flush()?;
    w.get_ref().sync_all()?;
    Ok(())
}

fn build_report(
    heldout: &[WorldBank],
    traces: &[TraceRow],
    groups: &[GroupResult],
    crashes: &[CrashResult],
    audit_rows: usize,
    deterministic_groups: usize,
) -> String {
    let baseline = baselines(groups);
    let all_replay = groups.iter().all(|g| g.replay_identity_ok);
    let no_illegal = groups.iter().all(|g| g.illegal_commits == 0);
    let no_duplicates = groups.iter().all(|g| g.duplicate_charges == 0);
    let crash_pass = crashes
        .iter()
        .all(|c| c.replay_identity_ok && c.duplicate_charges == 0);
    let mut out = String::new();
    out.push_str("# R&D-C / Experiment 008 — Source Offer\n\n");
    out.push_str("**Status: synthetic engineering benchmark, exploratory.** The run uses 8 independently seeded development worlds and 16 held-out worlds (6,144 held-out episodes). Ordinary route plans were frozen before held-out labels and source replies were written. The oracle is evaluation-only. E007 remains sealed and is included as hashed provenance.\n\n");
    out.push_str("## Decision contract\n\n");
    out.push_str("The runtime estimates `Δ = P(wrong→right) − P(right→wrong) − P(baseline-right unresolved)`. It computes `Vλ = Δ̂ − λ × quoted query price − 0.02 × offer request cost`, requires `Vλ > 0`, then ranks eligible candidates by positive value. Budgets 16/32/64 are maximum calls per world; zero calls are valid. Price λ values are 0.000, 0.010, and 0.030. Avoided wrong commits are reported separately from completion.\n\n");
    out.push_str("The costed mode tests a paid quote refresh for a candidate selected from the pushed/cached snapshot. A returned quote is receipted and value is recomputed before inspection. It therefore measures marginal quote refresh cost and quote changes; the initial snapshot remains zero-marginal.\n\n");
    out.push_str("## Integrity gates\n\n");
    out.push_str(&format!("- Illegal authority commits: **{}** ({}).\n- Duplicate endpoint charges in benchmark lanes: **{}** ({}).\n- Journal replay identities: **{} / {} plans passed** ({}).\n- Injected crash boundaries: **{} / {} passed** ({}).\n- Offer input audit rows: **{}**; deterministic field or field-pair/full-signature groups with support ≥8: **{}** ({}).\n\n",groups.iter().map(|g|g.illegal_commits as u64).sum::<u64>(),if no_illegal{"PASS"}else{"FAIL"},groups.iter().map(|g|g.duplicate_charges as u64).sum::<u64>(),if no_duplicates{"PASS"}else{"FAIL"},groups.iter().filter(|g|g.replay_identity_ok).count(),groups.len(),if all_replay{"PASS"}else{"FAIL"},crashes.iter().filter(|c|c.replay_identity_ok&&c.duplicate_charges==0).count(),crashes.len(),if crash_pass{"PASS"}else{"FAIL"},audit_rows,deterministic_groups,if deterministic_groups==0{"none detected"}else{"flagged; held-out bank retained unchanged"}));
    if deterministic_groups > 0 {
        out.push_str("The input audit flagged at least one repeated offer signature. It is retained as a visible low-support held-out collision; the bank was not retuned, and the fitted policy does not use full-signature lookup. Treat model transfer as exploratory rather than promoting on pooled completion alone.\n\n");
    }
    out.push_str("`Unknown` and `Failed` remain no-action typed results. Replay covers the authority receipt identity, paid-query journal, and hash-chained offer receipts. Exactly-once charging depends on endpoint deduplication by stable request ID.\n\n");
    out.push_str("## Held-out completion frontier\n\n");
    out.push_str("Values below are means over worlds; world is the variability unit. `completion gain` is relative to the paired zero-inspection floor. Query and offer costs are reported separately in `summary.csv` and `completion-cost-frontier.csv`.\n\n");
    out.push_str("| Lane | Stratum | Cap | λ | Offer path | Mean completion gain | Worlds with gain | Mean calls | Mean total cost |\n|---|---|---:|---:|---|---:|---:|---:|---:|\n");
    for lane in [
        "e007_eight_feature_positive_stop",
        "offer_simple",
        "offer_fitted",
        "shuffled_offers",
        "matched_random_offer_simple",
        "matched_random_offer_fitted",
        "matched_random_shuffled_offers",
        "evaluation_oracle",
    ] {
        for (stratum, budget, lambda, mode) in [
            ("all", 64, 0.0, "pushed_or_cached"),
            ("all", 64, 0.01, "pushed_or_cached"),
            ("all", 64, 0.03, "pushed_or_cached"),
            ("all", 64, 0.01, "costed_refresh_request"),
            ("reliability_shift", 64, 0.01, "pushed_or_cached"),
            ("new_ids", 64, 0.01, "pushed_or_cached"),
            (
                "historical_reliability_misleading",
                64,
                0.01,
                "costed_refresh_request",
            ),
        ] {
            if let Some((gain, positive, calls, cost)) =
                summary_cell(groups, &baseline, lane, stratum, budget, lambda, mode)
            {
                out.push_str(&format!("| {lane} | {stratum} | {budget} | {lambda:.3} | {mode} | {gain:.2} | {positive} | {calls:.2} | {cost:.2} |\n"));
            }
        }
    }
    out.push_str("\nThe full world-by-world and stratum-by-stratum results are in `world-summary.csv`; pooled episode counts are not used for uncertainty. The matched-random audit records call-count and spend residuals after paid quote refresh.\n\n");
    out.push_str("## Outcome accounting\n\n");
    out.push_str("For each queried episode, the report preserves wrong→right, right→wrong, unresolved baseline-right, unresolved baseline-wrong, and avoided wrong commits as distinct counts. A query returning `Unknown` or `Failed` can avoid a wrong commit but strands a baseline-right episode; it does not authorize the active action. Selected-query calibration is in `value-calibration.csv`, grouped by predicted-value bins and source-quality bins. Unselected inspection outcomes are not treated as observed runtime events.\n\n");
    out.push_str("## Limitations\n\n");
    out.push_str("This is a deterministic synthetic harness with generated offers and source replies. Held-out world variation tests the specified shifts, not deployment transfer. The simple rule is hand-specified; the fitted value estimate is trained only on development worlds. The evaluation oracle uses held-out truth and source replies after ordinary route plans are frozen and is an upper-bound diagnostic only. Cost units are synthetic and are not monetary prices.\n\n");
    out.push_str(&format!("Run contains {} held-out worlds, {} selected-query trace rows, and {} world-plan rows. E007 zero-call control has {} selected calls across its held-out plans.\n",heldout.len(),traces.len(),groups.len(),groups.iter().filter(|g|g.lane=="e007_eight_feature_positive_stop").map(|g|g.paid_queries).sum::<usize>()));
    out
}

fn summary_cell(
    groups: &[GroupResult],
    baseline: &HashMap<u32, usize>,
    lane: &str,
    stratum: &str,
    budget: usize,
    lambda: f32,
    mode: &str,
) -> Option<(f64, usize, f64, f64)> {
    let rows = groups
        .iter()
        .filter(|g| {
            g.lane == lane
                && g.budget == budget
                && (g.lambda - lambda).abs() < 0.0001
                && g.offer_mode == mode
                && (stratum == "all" || g.stratum == stratum)
        })
        .collect::<Vec<_>>();
    if rows.is_empty() {
        return None;
    }
    let deltas = rows
        .iter()
        .map(|g| g.completed as f64 - baseline.get(&g.world_id).copied().unwrap_or(0) as f64)
        .collect::<Vec<_>>();
    let calls = rows
        .iter()
        .map(|g| g.paid_queries as f64)
        .collect::<Vec<_>>();
    let cost = rows
        .iter()
        .map(|g| (g.query_cost_units + g.offer_cost_units) as f64)
        .collect::<Vec<_>>();
    Some((
        avg(&deltas),
        deltas.iter().filter(|d| **d > 0.0).count(),
        avg(&calls),
        avg(&cost),
    ))
}

fn baselines(groups: &[GroupResult]) -> HashMap<u32, usize> {
    groups
        .iter()
        .filter(|g| g.lane == "no_inspection")
        .map(|g| (g.world_id, g.completed))
        .collect()
}
fn avg(values: &[f64]) -> f64 {
    if values.is_empty() {
        0.0
    } else {
        values.iter().sum::<f64>() / values.len() as f64
    }
}
fn stddev(values: &[f64], mean: f64) -> f64 {
    if values.len() < 2 {
        0.0
    } else {
        (values.iter().map(|x| (x - mean) * (x - mean)).sum::<f64>() / (values.len() - 1) as f64)
            .sqrt()
    }
}
fn quantile(values: &mut [f64], q: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    values.sort_by(f64::total_cmp);
    let i = ((values.len() - 1) as f64 * q).round() as usize;
    values[i]
}
fn query_cost_from_groups(groups: &[GroupResult], key: &SummaryKey) -> f64 {
    avg(&groups
        .iter()
        .filter(|g| key_matches(g, key))
        .map(|g| g.query_cost_units as f64)
        .collect::<Vec<_>>())
}
fn offer_cost_from_groups(groups: &[GroupResult], key: &SummaryKey) -> f64 {
    avg(&groups
        .iter()
        .filter(|g| key_matches(g, key))
        .map(|g| g.offer_cost_units as f64)
        .collect::<Vec<_>>())
}
fn key_matches(g: &GroupResult, key: &SummaryKey) -> bool {
    g.lane == key.lane
        && g.stratum == key.stratum
        && g.budget == key.budget
        && (g.lambda * 1000.0).round() as i32 == key.lambda_milli
        && g.offer_mode == key.offer_mode
}
