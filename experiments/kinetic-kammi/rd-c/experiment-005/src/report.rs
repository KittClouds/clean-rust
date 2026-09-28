use std::{collections::BTreeMap, fmt::Write as FmtWrite};

use hashbrown::HashMap;

use crate::{
    episodes::Episode,
    evaluation::EvalLabel,
    routing::{BUDGETS, Lane},
    runtime::RunResult,
    scoring::DevelopmentValueModel,
};

pub fn build_report(
    runs: &[RunResult],
    episodes: &[Episode],
    labels: &[EvalLabel],
    model: &DevelopmentValueModel,
    receipt_checks: &[(Lane, usize, usize, u64, String, bool)],
) -> String {
    let mut out = String::with_capacity(24_000);
    writeln!(out, "# R&D-C Experiment 005 — Value of Information\n").unwrap();
    writeln!(out, "## Question and boundaries\n").unwrap();
    writeln!(out, "This benchmark tests whether a paid, on-demand inspection result can improve a legal-but-wrong action. The public frame contains source recommendations, source-reported revisions, age, warnings, confidence, and an inspection-domain key. The inspection payload is absent from that frame. The source state was written to a separate fixture before runtime execution; each selected episode makes one lookup and receives a hash-chained receipt containing the returned result.\n").unwrap();
    writeln!(out, "The runtime authority remains the E002 compiled state machine. No trusted task revision was added to its contract, the inspection response contains no revision, and the authority has no revision guard. The observation witness and inspection resolver can propose an action; the existing transition schema authorizes only legal transitions.\n").unwrap();

    writeln!(out, "## Paired benchmark results\n").unwrap();
    writeln!(out, "| Router lane | Budget | Completed | Wrong legal actions | Wrong→right | Right→wrong | Illegal commits | Queries / resolver calls | p50 / p95 task ms | p50 / p95 query μs | p50 resolver μs | Journal B / task | Query receipt B / call | Query units / completion | Replay |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|").unwrap();
    for lane in Lane::ALL {
        for budget in BUDGETS {
            let group = group(runs, lane, budget);
            let n = group.len();
            let calls = group
                .iter()
                .map(|run| run.query_calls as usize)
                .sum::<usize>();
            let resolver_calls = group
                .iter()
                .filter(|run| run.resolver_action.is_some())
                .count();
            let completed = group.iter().filter(|run| run.task_completed).count();
            let wrong = group
                .iter()
                .filter(|run| run.selected_action != run.correct_action)
                .count();
            let illegal = group.iter().map(|run| run.illegal_commits).sum::<usize>();
            let replay = group.iter().filter(|run| run.replay_identity_ok).count();
            let conversions = routed_outcomes(&group);
            let task_q = quantiles(group.iter().map(|run| run.wall_ns).collect());
            let query_q = quantiles(
                group
                    .iter()
                    .filter(|run| run.query_calls > 0)
                    .map(|run| run.query_ns as u128)
                    .collect(),
            );
            let resolver_ns = group
                .iter()
                .map(|run| run.resolver_ns as u128)
                .sum::<u128>()
                / calls.max(1) as u128;
            let journal = group
                .iter()
                .map(|run| run.task_journal_bytes as u128)
                .sum::<u128>()
                / n.max(1) as u128;
            let receipt = group
                .iter()
                .filter(|run| run.query_calls > 0)
                .map(|run| run.query_receipt_bytes as u128)
                .sum::<u128>()
                / calls.max(1) as u128;
            let cost_per_complete = calls as f64 / completed.max(1) as f64;
            writeln!(out, "| {} | {} | {completed}/{n} ({:.1}%) | {} | {} | {} | {} | {calls} / {resolver_calls} | {:.3} / {:.3} | {:.2} / {:.2} | {:.2} | {} | {} | {:.3} | {replay}/{n} |",
                lane.label(), budget, percent(completed, n), wrong,
                conversions.get("wrong_to_right").copied().unwrap_or(0),
                conversions.get("right_to_wrong").copied().unwrap_or(0), illegal,
                task_q.0 as f64 / 1e6, task_q.1 as f64 / 1e6,
                query_q.0 as f64 / 1e3, query_q.1 as f64 / 1e3,
                resolver_ns as f64 / 1e3, journal, receipt, cost_per_complete).unwrap();
        }
    }
    writeln!(out, "\nTask latency includes query, durable E002 journaling, action simulation, close, and replay. Query and resolver timings are local nanosecond measurements and noisy at this workload size. Each tool lookup costs one query unit; no external model is called and external token/API cost is zero. Receipt bytes per call exclude the shared 8-byte file header; the run manifest records whole-file sizes.\n").unwrap();

    writeln!(out, "## Paired deltas against the E004 combined lane\n").unwrap();
    writeln!(out, "| Budget | Lane | Completion delta | Paired wins / losses / ties | Wrong-action delta |\n|---:|---|---:|---:|---:|").unwrap();
    for budget in BUDGETS {
        let baseline = completed_by_episode(runs, Lane::E004Combined, budget);
        let base_wrong = wrong_by_episode(runs, Lane::E004Combined, budget);
        for lane in [
            Lane::DevelopmentVoI,
            Lane::MatchedRandom,
            Lane::OfflineOracle,
        ] {
            let current = completed_by_episode(runs, lane, budget);
            let current_wrong = wrong_by_episode(runs, lane, budget);
            let mut wins = 0;
            let mut losses = 0;
            let mut ties = 0;
            for (id, done) in &current {
                match (*done, baseline[id]) {
                    (true, false) => wins += 1,
                    (false, true) => losses += 1,
                    _ => ties += 1,
                }
            }
            let delta = current.values().filter(|done| **done).count() as isize
                - baseline.values().filter(|done| **done).count() as isize;
            let wrong_delta = current_wrong.values().sum::<usize>() as isize
                - base_wrong.values().sum::<usize>() as isize;
            writeln!(
                out,
                "| {budget} | {} | {delta:+} | {wins} / {losses} / {ties} | {wrong_delta:+} |",
                lane.label()
            )
            .unwrap();
        }
    }

    writeln!(out, "\n## Fresh-looking shared-error pocket\n").unwrap();
    writeln!(out, "The `fresh_consistent_wrong` stratum has identical observer recommendations, age zero, and no warning bits. Its source-reported revision is one step behind the hidden task state, but the initial frame gives no way to detect that discrepancy. Twenty-four of the 32 separate inspection fixtures return the correct action; eight repeat the wrong action. This tests a fresh-looking shared error that age and warning checks cannot identify.\n").unwrap();
    writeln!(out, "| Lane | Budget | Routed in stratum | Wrong→right | Right→wrong | Both wrong | Completion in stratum |\n|---|---:|---:|---:|---:|---:|---:|").unwrap();
    for lane in Lane::ALL {
        for budget in [16, 32, 64] {
            let group = runs
                .iter()
                .filter(|run| {
                    run.lane == lane
                        && run.budget == budget
                        && run.class == "fresh_consistent_wrong"
                })
                .collect::<Vec<_>>();
            let routed = group.iter().filter(|run| run.escalated).collect::<Vec<_>>();
            let counts = routed
                .iter()
                .fold(BTreeMap::<&str, usize>::new(), |mut counts, run| {
                    *counts.entry(run.outcome).or_default() += 1;
                    counts
                });
            let completed = group.iter().filter(|run| run.task_completed).count();
            writeln!(
                out,
                "| {} | {budget} | {} | {} | {} | {} | {completed}/{} |",
                lane.label(),
                routed.len(),
                counts.get("wrong_to_right").copied().unwrap_or(0),
                counts.get("right_to_wrong").copied().unwrap_or(0),
                counts.get("both_wrong").copied().unwrap_or(0),
                group.len()
            )
            .unwrap();
        }
    }

    writeln!(out, "\n## Development-set expected value table\n").unwrap();
    writeln!(out, "The development router uses only the public inspection-domain key and the frozen development estimate. It ranks episodes by `(wrong→right − right→wrong) / development examples`, rounded to milli-completions per query. The table is fitted before held-out labels are opened.\n").unwrap();
    writeln!(out, "| Domain | Development examples | Wrong→right | Right→wrong | Estimated net benefit / query |\n|---:|---:|---:|---:|---:|").unwrap();
    for domain in 0..8 {
        let estimate = model.estimate(domain);
        writeln!(
            out,
            "| {domain} | {} | {} | {} | {} / 1000 |",
            estimate.examples,
            estimate.wrong_to_right,
            estimate.right_to_wrong,
            estimate.expected_benefit_milli()
        )
        .unwrap();
    }

    writeln!(out, "\n## Replay, budgets, and receipts\n").unwrap();
    writeln!(out, "| Lane | Budget | Query receipts | Receipt bytes | Final receipt hash | Hash-chain replay |\n|---|---:|---:|---:|---|---|").unwrap();
    for (lane, budget, count, bytes, identity, valid) in receipt_checks {
        writeln!(
            out,
            "| {} | {budget} | {count} | {bytes} | `{}` | {} |",
            lane.label(),
            &identity[..16.min(identity.len())],
            if *valid { "PASS" } else { "FAIL" }
        )
        .unwrap();
    }
    let exact = Lane::ALL.iter().all(|lane| {
        BUDGETS.iter().all(|budget| {
            let group = group(runs, *lane, *budget);
            group.iter().filter(|run| run.escalated).count() == *budget
                && group
                    .iter()
                    .map(|run| run.query_calls as usize)
                    .sum::<usize>()
                    == *budget
                && group
                    .iter()
                    .filter(|run| run.resolver_action.is_some())
                    .count()
                    == *budget
        })
    });
    let illegal = runs.iter().map(|run| run.illegal_commits).sum::<usize>();
    let duplicates = runs.iter().map(|run| run.duplicate_actions).sum::<usize>();
    let missing = runs.iter().map(|run| run.missing_actions).sum::<usize>();
    let replay_failures = runs.iter().filter(|run| !run.replay_identity_ok).count();
    writeln!(out, "\n- Exact resolver and tool budgets: **{}**\n- Illegal commits: **{illegal}**\n- Duplicate actions: **{duplicates}**\n- Missing actions: **{missing}**\n- E002 task replay failures: **{replay_failures}**\n", if exact { "PASS" } else { "FAIL" }).unwrap();

    writeln!(out, "## Method limits\n\nThe workload contains 256 synthetic held-out episodes and a disjoint 256-episode development set. The observers are frozen deterministic proxies. Inspection uses a stored synthetic second-source payload, not a live external tool or human review. The offline oracle sees held-out labels and inspection fixtures; it is a ceiling only and is not a deployable router. The E004 combined lane preserves the E004 selector and frame-only resolver while paying for and receipting the new query; it intentionally discards the returned payload as a control. The other executable lanes use the same signature-and-confidence resolver on inspected results.\n\nA `PASS` on this bank supports the runtime, query-receipt, and replay contracts only. It does not establish a real-world value-of-information estimate. The next promotion test needs independently sourced inspection results and a new held-out workload.\n").unwrap();
    let _ = (episodes, labels);
    out
}

fn group(runs: &[RunResult], lane: Lane, budget: usize) -> Vec<&RunResult> {
    runs.iter()
        .filter(|run| run.lane == lane && run.budget == budget)
        .collect()
}

fn routed_outcomes(group: &[&RunResult]) -> HashMap<&'static str, usize> {
    let mut counts = HashMap::new();
    for run in group.iter().filter(|run| run.escalated) {
        *counts.entry(run.outcome).or_default() += 1;
    }
    counts
}

fn completed_by_episode(runs: &[RunResult], lane: Lane, budget: usize) -> HashMap<u32, bool> {
    runs.iter()
        .filter(|run| run.lane == lane && run.budget == budget)
        .map(|run| (run.episode_id, run.task_completed))
        .collect()
}

fn wrong_by_episode(runs: &[RunResult], lane: Lane, budget: usize) -> HashMap<u32, usize> {
    runs.iter()
        .filter(|run| run.lane == lane && run.budget == budget)
        .map(|run| {
            (
                run.episode_id,
                usize::from(run.selected_action != run.correct_action),
            )
        })
        .collect()
}

fn quantiles(mut values: Vec<u128>) -> (u128, u128) {
    if values.is_empty() {
        return (0, 0);
    }
    values.sort_unstable();
    let pick = |p: usize| values[((values.len() * p).div_ceil(100)).saturating_sub(1)];
    (pick(50), pick(95))
}

fn percent(part: usize, whole: usize) -> f64 {
    100.0 * part as f64 / whole.max(1) as f64
}
