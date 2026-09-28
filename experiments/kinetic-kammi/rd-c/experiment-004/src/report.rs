use hashbrown::HashMap;
use std::fmt::Write as FmtWrite;

use crate::{episodes::Episode, routing::Policy, runtime::RunResult};

pub fn build_report(runs: &[RunResult], episodes: &[Episode], budgets: &[usize]) -> String {
    let mut out = String::with_capacity(16_000);
    writeln!(
        out,
        "# R&D-C Experiment 004 — Information Boundary and Routing Test\n"
    )
    .unwrap();
    writeln!(out, "## Decision boundary\n").unwrap();
    writeln!(out, "The Experiment 002 runtime authority owns workflow state and recovery count. Its contract has no trusted task/world revision input. Experiment 003 encoded the revision inside observation evidence, so that was not an independent authority signal. E004 therefore keeps truth revision and correct-action labels in a separate evaluation file; neither observer nor resolver receives them. No deterministic stale-revision guard can be compiled until the production runtime contract supplies a trusted revision.\n").unwrap();
    writeln!(out, "The public frame contains goal, source recommendations, source-reported revisions, age buckets, and warning bits. Both frozen observers and the resolver receive the same frame. The resolver's only tools are `inspect_evidence(1)` and `inspect_evidence(2)`, which return the corresponding recorded recommendation, reported revision, age, warning, and content marker. The resolver chooses the least-warned/youngest source, with source 1 as the final tie-break. When evidence appears fresh, it applies the public goal/revision contract; when sources report age or warning signals, it requests a refresh. It does not see either observer proposal or evaluation label.\n").unwrap();
    writeln!(out, "The witness emits only `NoSignal` or `InspectEvidence(source_id, reason)`. It flags agreement on the same cited source when its visible age is nonzero, it carries a warning, or its recommendation conflicts with the public goal/reported-revision contract. It cannot name an action or state.\n").unwrap();
    writeln!(out, "## Frozen workload and methods\n").unwrap();
    writeln!(out, "- Fresh held-out bank: {} episodes, 8 strata × 16, seed `0x{:X}`.\n- Four fixed resolver-call budgets: {}. Every policy receives the identical selected episode IDs per budget; random uses a BLAKE3-ranked fixed ordering.\n- Policies: disagreement, confidence need, combined (witness first, then disagreement, then confidence need), and matched random. Call plans use only public episode features and are frozen before labels are scored.\n- Same Experiment 002 compiled authority, action simulator, journal format, and replay procedure in every lane.\n- Observers are deterministic frozen proxies; the resolver is deterministic local code. This measures the routing harness, not an LLM deliberator. Model calls, model tokens, and external inference cost are zero by construction.\n", episodes.len(), crate::episodes::HELDOUT_SEED, budgets.iter().map(usize::to_string).collect::<Vec<_>>().join(", ")).unwrap();
    writeln!(out, "\n## Paired results\n").unwrap();
    writeln!(out, "| Policy | Calls / budget | Completion | Wrong legal actions | Illegal commits | Rejections | Duplicate / missing actions | Replay identity | p50 / p95 task ms | Observer ns / task | Resolver ns / call | Tools / task | Tool ns / call | Tokens / task | Journal bytes / task | Cost / completed task |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|").unwrap();
    for policy in Policy::ALL {
        for budget in budgets {
            let group = runs
                .iter()
                .filter(|r| r.policy == policy && r.budget == *budget)
                .collect::<Vec<_>>();
            let n = group.len();
            let completed = group.iter().filter(|r| r.task_completed).count();
            let wrong = group.iter().filter(|r| r.wrong_legal_action).count();
            let illegal = group.iter().map(|r| r.illegal_commits).sum::<usize>();
            let rejected = group.iter().map(|r| r.rejected_proposals).sum::<usize>();
            let duplicates = group.iter().map(|r| r.duplicate_actions).sum::<usize>();
            let missing = group.iter().map(|r| r.missing_actions).sum::<usize>();
            let replay_ok = group.iter().filter(|r| r.replay_identity_ok).count();
            let wall = quantiles(group.iter().map(|r| r.wall_ns).collect());
            let observer = mean(
                group
                    .iter()
                    .map(|r| (r.observer_a_ns + r.observer_b_ns) as u128),
            );
            let resolver_ns = mean(group.iter().map(|r| r.resolver_ns as u128));
            let tool_ns = mean(group.iter().map(|r| r.tool_ns as u128));
            let tool_calls = group.iter().map(|r| r.tool_calls as usize).sum::<usize>();
            let tokens = group.iter().map(|r| r.resolver_tokens as u64).sum::<u64>();
            let journal_bytes = mean(group.iter().map(|r| r.journal_bytes as u128));
            let cost = group
                .iter()
                .map(|r| r.external_model_cost_micros)
                .sum::<u64>();
            writeln!(out, "| {} | {} / {} | {}/{} ({:.1}%) | {} | {} | {} | {} / {} | {}/{} | {:.3} / {:.3} | {:.1} | {:.1} | {:.2} | {:.1} | {:.2} | {:.1} | ${:.6} |",
                policy.label(), budget, n, completed, n, percent(completed, n), wrong, illegal, rejected,
                duplicates, missing, replay_ok, replay_ok, wall.0 as f64 / 1e6, wall.1 as f64 / 1e6,
                observer as f64 / n.max(1) as f64,
                resolver_ns as f64 / (*budget).max(1) as f64,
                tool_calls as f64 / n.max(1) as f64,
                tool_ns as f64 / (*budget).max(1) as f64,
                tokens as f64 / n.max(1) as f64,
                journal_bytes as f64 / n.max(1) as f64,
                cost as f64 / 1_000_000.0 / completed.max(1) as f64).unwrap();
        }
    }
    writeln!(out, "\nObserver, resolver, and tool times are instrumented local nanosecond intervals and will be noisy at this scale. Task p50/p95 include durable journaling and contract-aware replay. Resolver tool calls are local reads; the cost column divides external inference cost by completed tasks (zero here because no model is called).\n").unwrap();
    writeln!(out, "## Equal-budget paired deltas vs matched random\n").unwrap();
    writeln!(out, "| Budget | Policy | Completion delta | Paired wins / losses / ties | Wrong-action delta |\n|---:|---|---:|---:|---:|").unwrap();
    for budget in budgets {
        let baseline = by_episode(runs, Policy::RandomMatched, *budget);
        let base_wrong = by_episode_wrong(runs, Policy::RandomMatched, *budget);
        for policy in [Policy::Disagreement, Policy::Confidence, Policy::Combined] {
            let current = by_episode(runs, policy, *budget);
            let current_wrong = by_episode_wrong(runs, policy, *budget);
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
            let delta = current.values().filter(|v| **v).count() as isize
                - baseline.values().filter(|v| **v).count() as isize;
            let wrong_delta = current_wrong.values().sum::<usize>() as isize
                - base_wrong.values().sum::<usize>() as isize;
            writeln!(
                out,
                "| {} | {} | {:+} | {} / {} / {} | {:+} |",
                budget,
                policy.label(),
                delta,
                wins,
                losses,
                ties,
                wrong_delta
            )
            .unwrap();
        }
    }
    writeln!(out, "\n## Shared-error pocket\n").unwrap();
    let reference = runs
        .iter()
        .filter(|r| r.policy == Policy::Disagreement && r.budget == budgets[0]);
    let mut seen = HashMap::new();
    for run in reference {
        seen.entry(run.episode_id).or_insert(run);
    }
    let shared_wrong = seen
        .values()
        .filter(|r| r.raw_active == r.raw_shadow && r.raw_active != r.correct_action)
        .count();
    let witnessed = seen
        .values()
        .filter(|r| {
            r.raw_active == r.raw_shadow && r.raw_active != r.correct_action && r.witness != "none"
        })
        .count();
    let missed = shared_wrong.saturating_sub(witnessed);
    let witness_alarms = seen.values().filter(|r| r.witness != "none").count();
    let false_alarms = witness_alarms.saturating_sub(witnessed);
    writeln!(out, "On this bank, the frozen observers agreed on the same wrong action in {shared_wrong} episodes. The witness requested evidence inspection for {witnessed} of those and missed {missed}; it emitted {witness_alarms} inspection proposals in total, including {false_alarms} on episodes without a shared wrong action. It can catch fresh misleading recommendations when they conflict with the visible goal/reported-revision contract, but it cannot identify a fresh source that lies consistently about its revision and recommendation.\n").unwrap();
    writeln!(out, "## Gate checks\n").unwrap();
    let calls_exact = Policy::ALL.iter().all(|policy| {
        budgets.iter().all(|budget| {
            let group = runs
                .iter()
                .filter(|r| r.policy == *policy && r.budget == *budget);
            group.map(|r| r.escalated as usize).sum::<usize>() == *budget
        })
    });
    writeln!(out, "- Exact call budgets in every lane: **{}**\n- Illegal commits: **{}**\n- Duplicate actions: **{}**\n- Replay identity failures: **{}**\n- Missing actions: **{}**\n",
        yes_no(calls_exact), runs.iter().map(|r| r.illegal_commits).sum::<usize>(),
        runs.iter().map(|r| r.duplicate_actions).sum::<usize>(),
        runs.iter().filter(|r| !r.replay_identity_ok).count(),
        runs.iter().map(|r| r.missing_actions).sum::<usize>()).unwrap();
    writeln!(out, "## Limits and promotion boundary\n\nThis is a synthetic routing benchmark over 128 procedurally generated episodes and hand-coded observers/resolver. It can compare routing rules and verify the authority/replay contract; it cannot estimate production observer quality, real model token cost, or whether disagreement predicts errors in naturally occurring tasks. The resolver does not receive a truth revision. Because the current authority lacks that field, E004 does not claim deterministic stale-revision rejection. The witness is a routing proposal, not authority. Promotion requires the reported paired result plus an external runtime contract that explicitly supplies authoritative revision before adding a stale guard.\n").unwrap();
    out
}

fn by_episode(runs: &[RunResult], policy: Policy, budget: usize) -> HashMap<u32, bool> {
    runs.iter()
        .filter(|r| r.policy == policy && r.budget == budget)
        .map(|r| (r.episode_id, r.task_completed))
        .collect()
}

fn by_episode_wrong(runs: &[RunResult], policy: Policy, budget: usize) -> HashMap<u32, usize> {
    runs.iter()
        .filter(|r| r.policy == policy && r.budget == budget)
        .map(|r| (r.episode_id, r.wrong_legal_action as usize))
        .collect()
}

fn mean(values: impl Iterator<Item = u128>) -> u128 {
    let (sum, count) = values.fold((0u128, 0u128), |(sum, n), value| (sum + value, n + 1));
    sum / count.max(1)
}

fn quantiles(mut values: Vec<u128>) -> (u128, u128) {
    if values.is_empty() {
        return (0, 0);
    }
    values.sort_unstable();
    let pick = |percent: usize| values[((values.len() * percent).div_ceil(100)).saturating_sub(1)];
    (pick(50), pick(95))
}

fn percent(part: usize, whole: usize) -> f64 {
    100.0 * part as f64 / whole.max(1) as f64
}

fn yes_no(value: bool) -> &'static str {
    if value { "PASS" } else { "FAIL" }
}
