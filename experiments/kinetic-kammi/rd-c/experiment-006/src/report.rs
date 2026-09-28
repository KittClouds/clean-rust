use std::fmt::Write as FmtWrite;

use crate::{
    episodes::Episode,
    inspection::{InspectionOutcome, QueryReceiptStats},
    routing::{BUDGETS, Lane},
    runtime::RunResult,
    scoring::{FeatureValueModel, FrozenDomainTable, SmoothedValueModel},
};

pub fn build_report(
    runs: &[RunResult],
    episodes: &[Episode],
    e005: &FrozenDomainTable,
    smoothed: &SmoothedValueModel,
    feature: &FeatureValueModel,
    receipts: &[(Lane, usize, QueryReceiptStats)],
) -> String {
    let floor = runs
        .iter()
        .filter(|run| run.lane == Lane::NoInspection)
        .filter(|run| run.task_completed)
        .count();
    let mut out = String::with_capacity(20_000);
    writeln!(out, "# R&D-C Experiment 006 — Inspection Under Failure\n").unwrap();
    writeln!(out, "## Question and contract\n").unwrap();
    writeln!(out, "This held-out test attacks the E005 domain value table with shifted values, stale second-source replies, self-conflicting candidates, timeouts, transport failures, malformed results, and four unseen domains (8–11). The router sees the public frame before paying; source replies live in a separate fixture and are released only after a paid query. No held-out label or source outcome enters routing.\n").unwrap();
    writeln!(out, "The four typed outcomes produce explicit proposals. `Confirmed` keeps the active action; a unique, signed, high-confidence `Contradicted` result proposes its alternative; `Unknown` and `Failed` return the compiled runtime to `OBSERVING`. An unresolved proposal never reuses the active task action. No source revision is trusted by authority.\n").unwrap();
    writeln!(out, "The simulated endpoint honors stable query IDs: after a crash following a paid response but before its result receipt, resume performs one idempotent lookup and records the cached outcome. Query attempts, retries, paid charges, resolver calls, and task action effects are counted separately. This endpoint behavior is a harness contract, not a claim about external tools.\n").unwrap();

    writeln!(out, "## Paired results\n").unwrap();
    writeln!(out, "| Lane | Budget | Completed | Δ vs no-inspection | Wrong→right | Right→wrong | Unresolved | Avoided wrong commits | Paid units | Endpoint attempts / retries | Resolver calls | p50 / p95 task ms | p50 / p95 query ms | p50 / p95 resolver μs | Journal B / task | Receipt B / call | Paid units / completion | Replay |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|").unwrap();
    for lane in Lane::ALL {
        let budgets: &[usize] = if lane == Lane::NoInspection {
            &[0]
        } else {
            &BUDGETS
        };
        for budget in budgets {
            let group = select(runs, lane, *budget);
            let n = group.len();
            let completed = group.iter().filter(|run| run.task_completed).count();
            let wrong_right = group
                .iter()
                .filter(|run| run.outcome == "wrong_to_right")
                .count();
            let right_wrong = group
                .iter()
                .filter(|run| run.outcome == "right_to_wrong")
                .count();
            let unresolved = group.iter().filter(|run| run.reobserve).count();
            let avoided = group
                .iter()
                .filter(|run| run.outcome == "unresolved_active_wrong")
                .count();
            let replay = group.iter().filter(|run| run.replay_identity_ok).count();
            let task_q = quantiles(group.iter().map(|run| run.wall_ns).collect());
            let resolve_q = quantiles(group.iter().map(|run| run.resolver_ns as u128).collect());
            let query_q = quantiles(
                group
                    .iter()
                    .filter(|run| run.query_id.is_some())
                    .map(|run| run.query_ns as u128)
                    .collect(),
            );
            let journal_bytes = group
                .iter()
                .map(|run| run.task_journal_bytes as u128)
                .sum::<u128>()
                / n.max(1) as u128;
            let stats = receipts
                .iter()
                .find(|(receipt_lane, receipt_budget, _)| {
                    receipt_lane == &lane && receipt_budget == budget
                })
                .map(|row| row.2)
                .unwrap_or_default();
            let delta = completed as isize - floor as isize;
            let paid_per_completion = stats.charges as f64 / completed.max(1) as f64;
            let receipt_per_call =
                stats.bytes.saturating_sub(8) as f64 / stats.outcomes.max(1) as f64;
            writeln!(out, "| {} | {} | {completed}/{n} ({:.1}%) | {delta:+} | {wrong_right} | {right_wrong} | {unresolved} | {avoided} | {} | {} / {} | {} | {:.3} / {:.3} | {:.3} / {:.3} | {:.2} / {:.2} | {} | {:.1} | {:.3} | {replay}/{n} |",
                lane.label(), budget, percent(completed, n), stats.charges, stats.attempts, stats.retries, stats.outcomes,
                task_q.0 as f64 / 1e6, task_q.1 as f64 / 1e6,
                query_q.0 as f64 / 1e6, query_q.1 as f64 / 1e6,
                resolve_q.0 as f64 / 1e3, resolve_q.1 as f64 / 1e3,
                journal_bytes, receipt_per_call, paid_per_completion).unwrap();
        }
    }
    writeln!(out, "\nBudgets are exact distinct paid-query counts for the four router lanes. `Δ vs no-inspection` is the measured completion change after each lane has paid those calls; cost is also shown as paid units per completion. No conversion between query units and task completion is assumed. The no-inspection floor performs zero queries.\n").unwrap();

    writeln!(out, "## Outcome handling\n").unwrap();
    writeln!(out, "| Inspection result | Queries | Proposed reobserve | Actionable proposals | Wrong→right | Right→wrong | Active-wrong commits avoided |\n|---|---:|---:|---:|---:|---:|---:|").unwrap();
    for outcome in [
        InspectionOutcome::Confirmed,
        InspectionOutcome::Contradicted,
        InspectionOutcome::Unknown,
        InspectionOutcome::Failed,
    ] {
        let rows = runs
            .iter()
            .filter(|run| run.inspection_outcome == Some(outcome))
            .collect::<Vec<_>>();
        let reobserve = rows.iter().filter(|run| run.reobserve).count();
        let gain = rows
            .iter()
            .filter(|run| run.outcome == "wrong_to_right")
            .count();
        let harm = rows
            .iter()
            .filter(|run| run.outcome == "right_to_wrong")
            .count();
        let avoided = rows
            .iter()
            .filter(|run| run.outcome == "unresolved_active_wrong")
            .count();
        writeln!(
            out,
            "| {} | {} | {reobserve} | {} | {gain} | {harm} | {avoided} |",
            outcome.label(),
            rows.len(),
            rows.len() - reobserve
        )
        .unwrap();
    }
    writeln!(out, "\nAn unresolved result leaves the task at `OBSERVING`; it adds no task action effect. Active-wrong cases in that group count as avoided wrong commits, while active-right cases lose a completion opportunity and remain incomplete.\n").unwrap();

    writeln!(out, "## Domain shift and unseen domains\n").unwrap();
    writeln!(out, "| Domain | Bank | E005 table score | Smoothed mean | Uncertainty | Conservative score | Feature mean score | Budget-64 queries | Budget-64 Δ outcomes | Budget-64 completions |\n|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|").unwrap();
    for domain in 0..12u8 {
        let development = if domain < 8 { "seen" } else { "unseen" };
        let e005_score = e005.score(domain);
        let estimate = smoothed.estimate(domain);
        let domain_eps = episodes
            .iter()
            .filter(|episode| episode.domain == domain)
            .collect::<Vec<_>>();
        let feature_score = if let Some(episode) = domain_eps.first() {
            feature.score(episode.frame, episode.confidence)
        } else {
            0.0
        };
        let runs_domain = runs
            .iter()
            .filter(|run| {
                run.lane == Lane::SmoothedEstimate && run.budget == 64 && run.domain == domain
            })
            .collect::<Vec<_>>();
        let queried = runs_domain
            .iter()
            .filter(|run| run.query_id.is_some())
            .count();
        let gains = runs_domain
            .iter()
            .filter(|run| run.outcome == "wrong_to_right")
            .count();
        let harms = runs_domain
            .iter()
            .filter(|run| run.outcome == "right_to_wrong")
            .count();
        let complete = runs_domain.iter().filter(|run| run.task_completed).count();
        writeln!(out, "| {domain} | {development} | {e005_score:.3} | {:.3} | {:.3} | {:.3} | {feature_score:.3} | {queried} | +{gains}/-{harms} | {complete}/{} |", estimate.mean, estimate.uncertainty, estimate.lower_value, domain_eps.len()).unwrap();
    }
    writeln!(out, "\nDomain 6 is the fresh-looking shared-error attack: both observers agree, age is zero, warnings are clear, and the inspected source echoes the wrong proposal. Domains 3 and 5 invert or flatten E005's previously near-certain values. Domains 8–11 have no development examples and test transfer without a domain lookup. The table's last columns show smoothed-router selection and outcomes; the paired-results table compares all routers at each equal budget.\n").unwrap();

    writeln!(out, "## Unseen-domain paired comparison at budget 64\n").unwrap();
    writeln!(out, "| Lane | Paid queries in domains 8–11 | Wrong→right | Right→wrong | Unresolved | Completed | Δ vs unseen no-inspection floor |\n|---|---:|---:|---:|---:|---:|---:|").unwrap();
    let unseen_floor = runs
        .iter()
        .filter(|run| run.lane == Lane::NoInspection && run.domain >= 8)
        .filter(|run| run.task_completed)
        .count();
    for lane in Lane::ALL {
        let budget = if lane == Lane::NoInspection { 0 } else { 64 };
        let group = runs
            .iter()
            .filter(|run| run.lane == lane && run.budget == budget && run.domain >= 8)
            .collect::<Vec<_>>();
        let queries = group.iter().filter(|run| run.query_id.is_some()).count();
        let gains = group
            .iter()
            .filter(|run| run.outcome == "wrong_to_right")
            .count();
        let harms = group
            .iter()
            .filter(|run| run.outcome == "right_to_wrong")
            .count();
        let unresolved = group.iter().filter(|run| run.reobserve).count();
        let completed = group.iter().filter(|run| run.task_completed).count();
        writeln!(
            out,
            "| {} | {queries} | {gains} | {harms} | {unresolved} | {completed}/{} | {:+} |",
            lane.label(),
            group.len(),
            completed as isize - unseen_floor as isize
        )
        .unwrap();
    }
    writeln!(out, "\nThe unseen slice has 128 episodes. The E005 and E006 smoothed tables assign unseen domain IDs a neutral route score, so their selected calls are determined by deterministic tie-breaking against the other bank items. The feature model uses public frame values and no domain ID. This slice is part of the same held-out bank, and its small per-domain counts limit transfer claims.\n").unwrap();

    writeln!(out, "## Router definitions\n").unwrap();
    writeln!(out, "- **E005 domain table:** frozen E005 development model; unseen domain IDs receive neutral score zero.\n- **Smoothed estimate:** E006 development mean shrunk toward zero with eight prior-equivalent observations; selection score is posterior mean minus half its estimated standard error.\n- **Feature estimate:** ridge-regularized linear model trained on eight public features only; domain ID is not a feature. Its eight weights are recorded in `development/feature-model.csv`.\n- **Matched random:** deterministic BLAKE3 ranking over the same episode IDs and exact query budgets.\n- **No-inspection:** execute only the active proposal and make no inspection call.\n").unwrap();

    writeln!(out, "## Runtime and receipt gates\n").unwrap();
    let routed = runs.iter().filter(|run| run.query_id.is_some()).count();
    let illegal = runs.iter().map(|run| run.illegal_commits).sum::<usize>();
    let rejected = runs.iter().map(|run| run.rejected_proposals).sum::<usize>();
    let duplicates = runs.iter().map(|run| run.duplicate_actions).sum::<usize>();
    let missing = runs.iter().map(|run| run.missing_actions).sum::<usize>();
    let replay_fail = runs.iter().filter(|run| !run.replay_identity_ok).count();
    let receipt_pass = receipts.iter().all(|(_, budget, stats)| {
        stats.outcomes == *budget
            && stats.charges == *budget
            && stats.queries == *budget
            && stats.identity != [0; 32]
    });
    let no_fallback = runs
        .iter()
        .filter(|run| run.reobserve && run.selected_action.is_some())
        .count();
    writeln!(out, "- Routed episodes: {routed}\n- Illegal commits: {illegal}\n- Rejected proposals: {rejected}\n- Duplicate action effects: {duplicates}\n- Missing action effects: {missing}\n- Task replay failures: {replay_fail}\n- Unknown/failed fallback-to-active violations: {no_fallback}\n- Query receipt budgets and hash chains: **{}**\n", if receipt_pass { "PASS" } else { "FAIL" }).unwrap();
    writeln!(out, "## Interpretation limits\n\nAll data and inspection services are synthetic, deterministic proxies. The held-out bank has 384 episodes, including only 32 examples per domain and 128 total in unseen domains. The result tests routing, explicit abstention, receipt recovery, and replay contracts; it does not estimate a production inspector's error rates or financial cost. The paired score must be treated as bank-specific evidence until repeated on independently constructed domains and sources.\n").unwrap();
    let _ = feature.weights();
    out
}

#[derive(Clone, Debug)]
pub struct CrashRecoveryResult {
    pub point: &'static str,
    pub queries: usize,
    pub attempts: usize,
    pub retries: usize,
    pub charges: usize,
    pub outcomes: usize,
    pub task_action_effects: usize,
    pub duplicate_actions: usize,
    pub replay_ok: bool,
}

pub fn crash_section(rows: &[CrashRecoveryResult]) -> String {
    let mut out = String::with_capacity(2_000);
    writeln!(out, "## Crash injection and resume\n").unwrap();
    writeln!(out, "| Crash boundary | Query intents | Endpoint attempts | Retries | Paid charges | Result receipts | Task action effects | Duplicate effects | Replay |\n|---|---:|---:|---:|---:|---:|---:|---:|---|").unwrap();
    for row in rows {
        writeln!(
            out,
            "| {} | {} | {} | {} | {} | {} | {} | {} | {} |",
            row.point,
            row.queries,
            row.attempts,
            row.retries,
            row.charges,
            row.outcomes,
            row.task_action_effects,
            row.duplicate_actions,
            if row.replay_ok { "PASS" } else { "FAIL" }
        )
        .unwrap();
    }
    let pass = rows.len() == 3
        && rows.iter().all(|row| {
            row.queries == 1
                && row.charges == 1
                && row.outcomes == 1
                && row.task_action_effects == 1
                && row.duplicate_actions == 0
                && row.replay_ok
        });
    writeln!(out, "\n- Crash recovery gate: **{}**\n- Endpoint result cache and local receipt were replayed independently; paid query units and task action effects stayed separate.\n", if pass { "PASS" } else { "FAIL" }).unwrap();
    out
}

fn select(runs: &[RunResult], lane: Lane, budget: usize) -> Vec<&RunResult> {
    runs.iter()
        .filter(|run| run.lane == lane && run.budget == budget)
        .collect()
}

fn quantiles(mut values: Vec<u128>) -> (u128, u128) {
    if values.is_empty() {
        return (0, 0);
    }
    values.sort_unstable();
    let pick =
        |percentile: usize| values[(values.len() * percentile).div_ceil(100).saturating_sub(1)];
    (pick(50), pick(95))
}

fn percent(part: usize, whole: usize) -> f64 {
    100.0 * part as f64 / whole.max(1) as f64
}
