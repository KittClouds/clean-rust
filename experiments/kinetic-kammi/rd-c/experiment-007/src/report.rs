use rdc_runtime_contracts_v1::InspectionKind;
use std::{
    collections::{BTreeMap, HashMap},
    fs::File,
    io::Write,
    path::Path,
};

use crate::{
    domain::WorldBank,
    routing::{BUDGETS, Lane},
    runtime::{CrashResult, EpisodeTrace, GroupStats},
};

#[derive(Default)]
struct Aggregate {
    worlds: HashMap<u32, usize>,
    completed_by_world: HashMap<u32, u32>,
    episodes: usize,
    completed: u32,
    wrong_to_right: u32,
    right_to_wrong: u32,
    unresolved: u32,
    avoided: u32,
    illegal: u32,
    rejected: u32,
    actions: u32,
    replay_failures: u32,
    paid_cost: u64,
    receipt_bytes: u64,
    calls: u64,
    task_ns: Vec<u128>,
    query_ns: Vec<u64>,
    resolver_ns: Vec<u64>,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct Key {
    stratum: String,
    lane: &'static str,
    budget: usize,
}

pub fn write_outputs(
    run_dir: &Path,
    banks: &[WorldBank],
    traces: &[EpisodeTrace],
    groups: &[GroupStats],
    crashes: &[CrashResult],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut aggregates = BTreeMap::<Key, Aggregate>::new();
    for trace in traces {
        for stratum in [trace.stratum, "overall"] {
            let key = Key {
                stratum: stratum.to_owned(),
                lane: trace.lane.label(),
                budget: trace.budget,
            };
            let aggregate = aggregates.entry(key).or_default();
            aggregate.episodes += 1;
            aggregate.worlds.insert(trace.world_id, 1);
            aggregate.completed += trace.task_completed as u32;
            *aggregate
                .completed_by_world
                .entry(trace.world_id)
                .or_default() += trace.task_completed as u32;
            aggregate.wrong_to_right += trace.wrong_to_right as u32;
            aggregate.right_to_wrong += trace.right_to_wrong as u32;
            aggregate.unresolved += trace.unresolved as u32;
            aggregate.avoided += trace.avoided_wrong_commit as u32;
            aggregate.illegal += trace.illegal_commits;
            aggregate.rejected += trace.rejected_proposals;
            aggregate.actions += trace.action_effects;
            aggregate.replay_failures += (!trace.replay_identity_ok) as u32;
            aggregate.calls += (trace.inspection_kind.is_some()) as u64;
            if trace.query_cost_units > 0 {
                aggregate.paid_cost += trace.query_cost_units as u64;
            }
            aggregate.task_ns.push(trace.task_ns);
            if trace.query_ns > 0 {
                aggregate.query_ns.push(trace.query_ns);
            }
            if trace.resolver_ns > 0 {
                aggregate.resolver_ns.push(trace.resolver_ns);
            }
        }
    }
    for group in groups {
        for stratum in [group.stratum, "overall"] {
            let key = Key {
                stratum: stratum.to_owned(),
                lane: group.lane,
                budget: group.budget,
            };
            if let Some(aggregate) = aggregates.get_mut(&key) {
                aggregate.receipt_bytes += group.receipt_bytes;
            }
        }
    }
    write_summary_csv(run_dir.join("summary.csv"), &aggregates, traces)?;
    write_new_id_csv(run_dir.join("new-id-summary.csv"), traces)?;
    write_world_csv(run_dir.join("world-summary.csv"), banks, traces)?;
    write_crashes(run_dir.join("crash-results.csv"), crashes)?;
    write_markdown(
        run_dir.join("benchmark-report.md"),
        banks,
        &aggregates,
        traces,
        groups,
        crashes,
    )?;
    Ok(())
}

fn write_summary_csv(
    path: impl AsRef<Path>,
    aggregates: &BTreeMap<Key, Aggregate>,
    traces: &[EpisodeTrace],
) -> Result<(), Box<dyn std::error::Error>> {
    let floor = floor_completions(traces);
    let oracle = oracle_completions(traces);
    let mut writer = std::io::BufWriter::with_capacity(32 * 1024, File::create(path)?);
    writeln!(
        writer,
        "stratum,lane,budget,worlds,episodes,completed,floor_completed,net_completion_gain,wrong_to_right,right_to_wrong,unresolved,avoided_wrong_commits,paid_calls,marginal_gain_per_call,paid_cost_units,cost_units_per_completion,value_capture,mean_bank_gain,min_bank_gain,max_bank_gain,illegal_commits,rejected_proposals,action_effects,replay_failures,receipt_bytes,receipt_bytes_per_call,p50_task_ms,p95_task_ms,p50_query_ms,p95_query_ms,p50_resolver_us,p95_resolver_us"
    )?;
    for (key, aggregate) in aggregates {
        let floor_completed = aggregate
            .completed_by_world
            .keys()
            .map(|world| floor.get(world).copied().unwrap_or(0))
            .sum::<u32>();
        let oracle_gain = aggregate
            .completed_by_world
            .keys()
            .map(|world| {
                oracle
                    .get(&(*world, key.budget))
                    .copied()
                    .unwrap_or_else(|| floor.get(world).copied().unwrap_or(0))
                    as i64
                    - floor.get(world).copied().unwrap_or(0) as i64
            })
            .sum::<i64>();
        let gain = aggregate.completed as i64 - floor_completed as i64;
        let capture = if oracle_gain > 0 {
            format!("{:.6}", gain as f64 / oracle_gain as f64)
        } else {
            "NA".to_owned()
        };
        let bank_gains = aggregate
            .completed_by_world
            .iter()
            .map(|(world, completed)| {
                *completed as i32 - floor.get(world).copied().unwrap_or(0) as i32
            })
            .collect::<Vec<_>>();
        let mean_bank_gain = if bank_gains.is_empty() {
            0.0
        } else {
            bank_gains.iter().sum::<i32>() as f64 / bank_gains.len() as f64
        };
        let min_bank_gain = bank_gains.iter().min().copied().unwrap_or(0);
        let max_bank_gain = bank_gains.iter().max().copied().unwrap_or(0);
        let per_call = if aggregate.calls > 0 {
            gain as f64 / aggregate.calls as f64
        } else {
            0.0
        };
        let cost_per_completion = if aggregate.completed > 0 {
            aggregate.paid_cost as f64 / aggregate.completed as f64
        } else {
            0.0
        };
        let receipt_per_call = if aggregate.calls > 0 {
            aggregate.receipt_bytes as f64 / aggregate.calls as f64
        } else {
            0.0
        };
        writeln!(
            writer,
            "{},{},{},{},{},{},{},{},{},{},{},{},{},{:.6},{},{:.6},{},{:.6},{},{},{},{},{},{},{},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3}",
            key.stratum,
            key.lane,
            key.budget,
            aggregate.worlds.len(),
            aggregate.episodes,
            aggregate.completed,
            floor_completed,
            gain,
            aggregate.wrong_to_right,
            aggregate.right_to_wrong,
            aggregate.unresolved,
            aggregate.avoided,
            aggregate.calls,
            per_call,
            aggregate.paid_cost,
            cost_per_completion,
            capture,
            mean_bank_gain,
            min_bank_gain,
            max_bank_gain,
            aggregate.illegal,
            aggregate.rejected,
            aggregate.actions,
            aggregate.replay_failures,
            aggregate.receipt_bytes,
            receipt_per_call,
            percentile_u128(&aggregate.task_ns, 0.50) as f64 / 1_000_000.0,
            percentile_u128(&aggregate.task_ns, 0.95) as f64 / 1_000_000.0,
            percentile(&aggregate.query_ns, 0.50) as f64 / 1_000_000.0,
            percentile(&aggregate.query_ns, 0.95) as f64 / 1_000_000.0,
            percentile(&aggregate.resolver_ns, 0.50) as f64 / 1_000.0,
            percentile(&aggregate.resolver_ns, 0.95) as f64 / 1_000.0
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_new_id_csv(
    path: impl AsRef<Path>,
    traces: &[EpisodeTrace],
) -> Result<(), Box<dyn std::error::Error>> {
    let floor = floor_completions_new_ids(traces);
    let mut rows = BTreeMap::<(&'static str, usize), Aggregate>::new();
    for trace in traces.iter().filter(|row| row.domain_id >= 1000) {
        let key = (trace.lane.label(), trace.budget);
        let aggregate = rows.entry(key).or_default();
        aggregate.episodes += 1;
        aggregate.completed += trace.task_completed as u32;
        *aggregate
            .completed_by_world
            .entry(trace.world_id)
            .or_default() += trace.task_completed as u32;
        aggregate.wrong_to_right += trace.wrong_to_right as u32;
        aggregate.right_to_wrong += trace.right_to_wrong as u32;
        aggregate.unresolved += trace.unresolved as u32;
        aggregate.calls += (trace.inspection_kind.is_some()) as u64;
    }
    let mut writer = std::io::BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "lane,budget,episodes,completed,floor_completed,completion_gain,wrong_to_right,right_to_wrong,unresolved,paid_calls,marginal_gain_per_call"
    )?;
    for ((lane, budget), row) in rows {
        let floor_count = row
            .completed_by_world
            .keys()
            .map(|world| floor.get(world).copied().unwrap_or(0))
            .sum::<u32>();
        let gain = row.completed as i64 - floor_count as i64;
        let per_call = if row.calls > 0 {
            gain as f64 / row.calls as f64
        } else {
            0.0
        };
        writeln!(
            writer,
            "{lane},{budget},{},{},{},{gain},{},{},{},{},{per_call:.6}",
            row.episodes,
            row.completed,
            floor_count,
            row.wrong_to_right,
            row.right_to_wrong,
            row.unresolved,
            row.calls
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_world_csv(
    path: impl AsRef<Path>,
    banks: &[WorldBank],
    traces: &[EpisodeTrace],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = std::io::BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "world_id,stratum,base_error,helpful_accuracy,harmful_contradiction,unknown_rate,failed_rate,staleness_rate,base_query_cost,lane,budget,completed,floor_completed,gain"
    )?;
    for bank in banks {
        let floor = traces
            .iter()
            .filter(|row| row.world_id == bank.recipe.world_id && row.lane == Lane::NoInspection)
            .map(|row| row.task_completed as u32)
            .sum::<u32>();
        for lane in Lane::ROUTERS
            .into_iter()
            .chain([Lane::NoInspection, Lane::Oracle])
        {
            for budget in if lane == Lane::NoInspection {
                vec![0]
            } else {
                BUDGETS.to_vec()
            } {
                let completed = traces
                    .iter()
                    .filter(|row| {
                        row.world_id == bank.recipe.world_id
                            && row.lane == lane
                            && row.budget == budget
                    })
                    .map(|row| row.task_completed as u32)
                    .sum::<u32>();
                writeln!(
                    writer,
                    "{},{},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{},{},{},{},{},{}",
                    bank.recipe.world_id,
                    bank.recipe.stratum.label(),
                    bank.recipe.params.base_error,
                    bank.recipe.params.helpful_accuracy,
                    bank.recipe.params.harmful_contradiction,
                    bank.recipe.params.unknown_rate,
                    bank.recipe.params.failed_rate,
                    bank.recipe.params.staleness_rate,
                    bank.recipe.params.base_query_cost,
                    lane.label(),
                    budget,
                    completed,
                    floor,
                    completed as i64 - floor as i64
                )?;
            }
        }
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_crashes(
    path: impl AsRef<Path>,
    rows: &[CrashResult],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = std::io::BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "crash_boundary,endpoint_attempts,retries,paid_charges,result_receipts,duplicate_effects,replay_ok"
    )?;
    for row in rows {
        writeln!(
            writer,
            "{},{},{},{},{},{},{}",
            row.point,
            row.attempts,
            row.retries,
            row.charges,
            row.result_receipts,
            row.duplicate_effects,
            row.replay_ok
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_markdown(
    path: impl AsRef<Path>,
    banks: &[WorldBank],
    aggregates: &BTreeMap<Key, Aggregate>,
    traces: &[EpisodeTrace],
    groups: &[GroupStats],
    crashes: &[CrashResult],
) -> Result<(), Box<dyn std::error::Error>> {
    let floor = floor_completions(traces);
    let oracle = oracle_completions(traces);
    let mut text = String::with_capacity(16 * 1024);
    text.push_str("# R&D-C Experiment 007 — Query Value Transfer\n\n");
    text.push_str("## Frozen evaluation\n\n");
    text.push_str(&format!("- Development: {} independently seeded worlds, {} episodes; all router fits were frozen before held-out source and label fixtures were scored.\n", crate::domain::DEVELOPMENT_WORLDS, crate::domain::DEVELOPMENT_WORLDS * crate::domain::DEVELOPMENT_DOMAINS * crate::domain::EPISODES_PER_DOMAIN));
    text.push_str(&format!("- Held out: {} worlds, {} episodes, four preregistered strata; each world has four familiar IDs and eight new IDs.\n", banks.len(), banks.iter().map(|bank| bank.public.len()).sum::<usize>()));
    text.push_str("- Each router receives exactly 16, 32, or 64 paid calls per world. Query cost varies by world and episode and is reported separately in cost units.\n");
    text.push_str("- The feature router reuses E006's eight public features; its scoring function receives only that feature vector and query price. No world or domain ID, source reply, label, or oracle value enters its input.\n");
    text.push_str("- The evaluation oracle ranks realized task-completion deltas after the ordinary route plans are frozen; it is a measurement ceiling with no route authority.\n\n");
    text.push_str("## Overall paired results\n\n");
    text.push_str("Values pool all 16 held-out worlds (6,144 episodes per lane and budget). `Gain` is completion change from the paired zero-call floor. `Capture` is pooled gain divided by the evaluation-only oracle gain under the same call budget.\n\n");
    text.push_str("| Lane | Calls/world | Complete | Floor | Gain | Wrong→right | Right→wrong | Unresolved | Marginal gain/call | Paid cost | Capture | Mean bank gain | Min…max bank gain | Receipt B/call | Replay failures |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n");
    for lane in [
        Lane::DomainTable,
        Lane::SmoothedTable,
        Lane::FeatureRouter,
        Lane::MatchedRandom,
        Lane::NoInspection,
        Lane::Oracle,
    ] {
        for budget in if lane == Lane::NoInspection {
            vec![0]
        } else {
            BUDGETS.to_vec()
        } {
            let aggregate = find_overall(aggregates, lane, budget);
            if let Some(aggregate) = aggregate {
                let floor_count = aggregate
                    .completed_by_world
                    .keys()
                    .map(|world| floor.get(world).copied().unwrap_or(0))
                    .sum::<u32>();
                let gain = aggregate.completed as i64 - floor_count as i64;
                let oracle_gain = aggregate
                    .completed_by_world
                    .keys()
                    .map(|world| {
                        oracle
                            .get(&(*world, budget))
                            .copied()
                            .unwrap_or_else(|| floor.get(world).copied().unwrap_or(0))
                            as i64
                            - floor.get(world).copied().unwrap_or(0) as i64
                    })
                    .sum::<i64>();
                let capture = if oracle_gain > 0 {
                    format!("{:.3}", gain as f64 / oracle_gain as f64)
                } else {
                    "NA".to_owned()
                };
                let bank_gains = aggregate
                    .completed_by_world
                    .iter()
                    .map(|(world, completed)| {
                        *completed as i32 - floor.get(world).copied().unwrap_or(0) as i32
                    })
                    .collect::<Vec<_>>();
                let mean = if bank_gains.is_empty() {
                    0.0
                } else {
                    bank_gains.iter().sum::<i32>() as f64 / bank_gains.len() as f64
                };
                let bounds = format!(
                    "{}…{}",
                    bank_gains.iter().min().copied().unwrap_or(0),
                    bank_gains.iter().max().copied().unwrap_or(0)
                );
                let calls = aggregate.calls;
                let per_call = if calls > 0 {
                    gain as f64 / calls as f64
                } else {
                    0.0
                };
                let bytes_per_call = if calls > 0 {
                    aggregate.receipt_bytes as f64 / calls as f64
                } else {
                    0.0
                };
                text.push_str(&format!("| {} | {} | {}/{} | {} | {} | {} | {} | {} | {:.4} | {} | {} | {:.2} | {} | {:.1} | {} |\n", lane.label(), budget, aggregate.completed, aggregate.episodes, floor_count, gain, aggregate.wrong_to_right, aggregate.right_to_wrong, aggregate.unresolved, per_call, aggregate.paid_cost, capture, mean, bounds, bytes_per_call, aggregate.replay_failures));
            }
        }
    }
    text.push_str("\nAt 64 calls/world, feature routing did not transfer: its net completion change is below both the no-inspection floor and matched random. The evaluation-only ceiling confirms that useful inspection opportunities exist in these banks, while the frozen router does not select them reliably. These are descriptive results from synthetic generators.\n");
    text.push_str("\n### Cost and latency at 64 calls/world\n\n`p95 task` includes query and authority time; query latency also appears separately. Cost/completion divides paid cost units by total completed tasks.\n\n");
    text.push_str("| Lane | Net gain | Avoided wrong commits | Paid cost | Cost/completion | p95 task ms | p95 query ms | p95 resolver µs | Receipt B/call |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|\n");
    for lane in [
        Lane::DomainTable,
        Lane::SmoothedTable,
        Lane::FeatureRouter,
        Lane::MatchedRandom,
        Lane::NoInspection,
        Lane::Oracle,
    ] {
        let budget = if lane == Lane::NoInspection { 0 } else { 64 };
        if let Some(aggregate) = find_overall(aggregates, lane, budget) {
            let floor_count = aggregate
                .completed_by_world
                .keys()
                .map(|world| floor.get(world).copied().unwrap_or(0))
                .sum::<u32>();
            let gain = aggregate.completed as i64 - floor_count as i64;
            let cost_per_completion = if aggregate.completed > 0 {
                aggregate.paid_cost as f64 / aggregate.completed as f64
            } else {
                0.0
            };
            let receipt_per_call = if aggregate.calls > 0 {
                aggregate.receipt_bytes as f64 / aggregate.calls as f64
            } else {
                0.0
            };
            let task_p95 = percentile_u128(&aggregate.task_ns, 0.95) as f64 / 1_000_000.0;
            let query_p95 = percentile(&aggregate.query_ns, 0.95) as f64 / 1_000_000.0;
            let resolver_p95 = percentile(&aggregate.resolver_ns, 0.95) as f64 / 1_000.0;
            text.push_str(&format!(
                "| {} | {} | {} | {} | {:.4} | {:.3} | {:.3} | {:.3} | {:.1} |\n",
                lane.label(),
                gain,
                aggregate.avoided,
                aggregate.paid_cost,
                cost_per_completion,
                task_p95,
                query_p95,
                resolver_p95,
                receipt_per_call
            ));
        }
    }
    text.push_str("\n## New domain IDs at 64 calls/world\n\n");
    text.push_str("The slice includes all episodes whose domain IDs do not occur in development; per-world IDs are deliberately novel. `Paid calls` counts calls selected within this slice, out of the 1,024 calls made across the 16 worlds. See `new-id-summary.csv` for all budgets.\n\n");
    text.push_str("| Lane | Episodes | Complete | Floor | Gain | Wrong→right | Right→wrong | Slice paid calls |\n|---|---:|---:|---:|---:|---:|---:|---:|\n");
    let new_id_rows = new_id_aggregate(traces);
    for lane in [
        Lane::DomainTable,
        Lane::SmoothedTable,
        Lane::FeatureRouter,
        Lane::MatchedRandom,
        Lane::NoInspection,
        Lane::Oracle,
    ] {
        let budget = if lane == Lane::NoInspection { 0 } else { 64 };
        if let Some(row) = new_id_rows.get(&(lane.label(), budget)) {
            let floor_count = row
                .completed_by_world
                .keys()
                .map(|world| floor_new_id(traces, *world))
                .sum::<u32>();
            text.push_str(&format!(
                "| {} | {} | {} | {} | {} | {} | {} | {} |\n",
                lane.label(),
                row.episodes,
                row.completed,
                floor_count,
                row.completed as i64 - floor_count as i64,
                row.wrong_to_right,
                row.right_to_wrong,
                row.calls
            ));
        }
    }
    text.push_str("\n## Transfer by preregistered stratum at 64 calls/world\n\n");
    text.push_str("| Stratum | Lane | Complete | Floor | Gain | Wrong→right | Right→wrong | Unresolved | Capture |\n|---|---|---:|---:|---:|---:|---:|---:|---:|\n");
    for stratum in [
        "familiar_ids",
        "new_ids",
        "reliability_shift",
        "stale_sources",
    ] {
        for lane in [
            Lane::DomainTable,
            Lane::SmoothedTable,
            Lane::FeatureRouter,
            Lane::MatchedRandom,
            Lane::Oracle,
        ] {
            let key = Key {
                stratum: stratum.to_owned(),
                lane: lane.label(),
                budget: 64,
            };
            let Some(aggregate) = aggregates.get(&key) else {
                continue;
            };
            let floor_count = aggregate
                .completed_by_world
                .keys()
                .map(|world| floor.get(world).copied().unwrap_or(0))
                .sum::<u32>();
            let oracle_gain = aggregate
                .completed_by_world
                .keys()
                .map(|world| {
                    oracle
                        .get(&(*world, 64))
                        .copied()
                        .unwrap_or_else(|| floor.get(world).copied().unwrap_or(0))
                        as i64
                        - floor.get(world).copied().unwrap_or(0) as i64
                })
                .sum::<i64>();
            let gain = aggregate.completed as i64 - floor_count as i64;
            let capture = if oracle_gain > 0 {
                format!("{:.3}", gain as f64 / oracle_gain as f64)
            } else {
                "NA".to_owned()
            };
            text.push_str(&format!(
                "| {stratum} | {} | {} | {} | {gain} | {} | {} | {} | {capture} |\n",
                lane.label(),
                aggregate.completed,
                floor_count,
                aggregate.wrong_to_right,
                aggregate.right_to_wrong,
                aggregate.unresolved
            ));
        }
    }
    text.push_str("\n## Typed inspection outcomes\n\n");
    let mut outcomes = [0u64; 4];
    for row in traces.iter().filter(|row| row.inspection_kind.is_some()) {
        let slot = match row.inspection_kind.unwrap() {
            InspectionKind::Confirmed => 0,
            InspectionKind::Contradicted => 1,
            InspectionKind::Unknown => 2,
            InspectionKind::Failed => 3,
        };
        outcomes[slot] += 1;
    }
    text.push_str(&format!("Across repeated router and budget runs: Confirmed {}, Contradicted {}, Unknown {}, Failed {}. Unknown and Failed reobserved without a task action; the authority lane has no fallback-to-active transition.\n\n", outcomes[0], outcomes[1], outcomes[2], outcomes[3]));
    text.push_str("## Runtime and paid-action gates\n\n");
    let illegal = traces.iter().map(|row| row.illegal_commits).sum::<u32>();
    let rejected = traces.iter().map(|row| row.rejected_proposals).sum::<u32>();
    let duplicates = groups
        .iter()
        .map(|group| group.endpoint_attempts.saturating_sub(group.paid_queries))
        .sum::<usize>();
    let replay_failures = traces.iter().filter(|row| !row.replay_identity_ok).count();
    text.push_str(&format!("- Ordinary benchmark: illegal commits {illegal}; rejected proposals {rejected}; duplicate endpoint effects {duplicates}; replay failures {replay_failures}.\n"));
    text.push_str(&format!("- Group journals: {} router/budget groups; each routed group used exactly its call budget; every result receipt and query hash chain passed.\n", groups.iter().filter(|group| group.planned_queries > 0).count()));
    text.push_str("- Crash recovery:\n\n| Boundary | Attempts | Retries | Charges | Result receipts | Duplicate effects | Replay |\n|---|---:|---:|---:|---:|---:|---|\n");
    for row in crashes {
        text.push_str(&format!(
            "| {} | {} | {} | {} | {} | {} | {} |\n",
            row.point,
            row.attempts,
            row.retries,
            row.charges,
            row.result_receipts,
            row.duplicate_effects,
            if row.replay_ok { "PASS" } else { "FAIL" }
        ));
    }
    text.push_str("\nThe crash harness keeps a simulated endpoint stable-ID cache alive across client-journal recovery. A real endpoint must durably retain and honor the request ID to provide the same retry behavior.\n\n");
    text.push_str("## Interpretation limits\n\nAll data, task worlds, and inspection endpoints are synthetic deterministic proxies. Each held-out world has 384 tasks and 12 domains; estimates are world-level engineering evidence, not a production inspector error model. The feature router is an eight-weight ridge model over the fixed public schema, trained only on development worlds. Value capture is a finite-bank oracle ratio under the exact call budget; it is not a causal or broad-generalization claim.\n");
    let mut writer = std::io::BufWriter::new(File::create(path)?);
    writer.write_all(text.as_bytes())?;
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn floor_completions(traces: &[EpisodeTrace]) -> HashMap<u32, u32> {
    let mut floor = HashMap::new();
    for row in traces.iter().filter(|row| row.lane == Lane::NoInspection) {
        *floor.entry(row.world_id).or_default() += row.task_completed as u32;
    }
    floor
}

fn oracle_completions(traces: &[EpisodeTrace]) -> HashMap<(u32, usize), u32> {
    let mut values = HashMap::new();
    for row in traces.iter().filter(|row| row.lane == Lane::Oracle) {
        *values.entry((row.world_id, row.budget)).or_default() += row.task_completed as u32;
    }
    values
}

fn floor_completions_new_ids(traces: &[EpisodeTrace]) -> HashMap<u32, u32> {
    let mut floor = HashMap::new();
    for row in traces
        .iter()
        .filter(|row| row.lane == Lane::NoInspection && row.domain_id >= 1000)
    {
        *floor.entry(row.world_id).or_default() += row.task_completed as u32;
    }
    floor
}

fn floor_new_id(traces: &[EpisodeTrace], world_id: u32) -> u32 {
    traces
        .iter()
        .filter(|row| {
            row.world_id == world_id && row.lane == Lane::NoInspection && row.domain_id >= 1000
        })
        .map(|row| row.task_completed as u32)
        .sum()
}

fn new_id_aggregate(traces: &[EpisodeTrace]) -> BTreeMap<(&'static str, usize), Aggregate> {
    let mut rows = BTreeMap::<(&'static str, usize), Aggregate>::new();
    for row in traces.iter().filter(|trace| trace.domain_id >= 1000) {
        let aggregate = rows.entry((row.lane.label(), row.budget)).or_default();
        aggregate.episodes += 1;
        aggregate.completed += row.task_completed as u32;
        *aggregate
            .completed_by_world
            .entry(row.world_id)
            .or_default() += row.task_completed as u32;
        aggregate.wrong_to_right += row.wrong_to_right as u32;
        aggregate.right_to_wrong += row.right_to_wrong as u32;
        aggregate.unresolved += row.unresolved as u32;
        aggregate.calls += row.inspection_kind.is_some() as u64;
    }
    rows
}

fn find_overall(
    aggregates: &BTreeMap<Key, Aggregate>,
    lane: Lane,
    budget: usize,
) -> Option<&Aggregate> {
    aggregates
        .iter()
        .find(|(key, _)| {
            key.stratum == "overall" && key.lane == lane.label() && key.budget == budget
        })
        .map(|(_, value)| value)
}

fn percentile(values: &[u64], quantile: f32) -> u64 {
    if values.is_empty() {
        return 0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let index = ((sorted.len() - 1) as f32 * quantile).ceil() as usize;
    sorted[index.min(sorted.len() - 1)]
}

fn percentile_u128(values: &[u128], quantile: f32) -> u128 {
    if values.is_empty() {
        return 0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let index = ((sorted.len() - 1) as f32 * quantile).ceil() as usize;
    sorted[index.min(sorted.len() - 1)]
}
