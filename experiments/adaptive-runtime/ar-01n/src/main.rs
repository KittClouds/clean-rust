use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_01n::{
    MappedDataset, SAME_BLOCK_DOMAINS, SAME_BLOCK_EVERY, SAME_BLOCK_HORIZONS, SameBlockHorizon,
    SameBlockSnapshot, SameBlockSummary, TOTAL_COMMITS, same_block_control_all, write_dataset,
};

#[derive(Clone, Copy, Debug, Default)]
struct PairClass {
    initial_control_better: bool,
    persistent: bool,
    transient: bool,
    none: bool,
}

#[derive(Clone, Copy, Debug, Default)]
struct StreamStats {
    rows: usize,
    matched: usize,
    initial_control_better: usize,
    mean_delta: f64,
    g3_better_rate: f64,
    reversal_rate: f64,
    mean_distance: f64,
    mean_utility_gap: f64,
    max_utility_gap: f64,
    persistent: usize,
    transient: usize,
    none: usize,
}

fn stream_name(family: u8, replicate: usize) -> &'static str {
    match (family, replicate) {
        (0, 0) => "L0-original",
        (2, 0) => "L2-shifted-17",
        (2, 1) => "L2-shifted-36",
        _ => "unknown",
    }
}

fn domain_name(domain: u8) -> &'static str {
    match domain {
        1 => "N1-k2-shortlist",
        2 => "N2-full-7x7",
        _ => "unknown",
    }
}

fn control_present(snapshot: &SameBlockSnapshot, slot: usize) -> bool {
    if slot == 0 {
        snapshot.control_a.present
    } else {
        snapshot.control_b.present
    }
}

fn control_utility(snapshot: &SameBlockSnapshot, slot: usize) -> f32 {
    if slot == 0 {
        snapshot.control_a.utility
    } else {
        snapshot.control_b.utility
    }
}

fn control_gap(snapshot: &SameBlockSnapshot, slot: usize) -> f32 {
    if slot == 0 {
        snapshot.control_a.regret_gap
    } else {
        snapshot.control_b.regret_gap
    }
}

fn delta(horizon: &SameBlockHorizon, slot: usize) -> f32 {
    if slot == 0 {
        horizon.g3_vs_control_a_train_delta
    } else {
        horizon.g3_vs_control_b_train_delta
    }
}

fn distance(horizon: &SameBlockHorizon, slot: usize) -> f32 {
    if slot == 0 {
        horizon.g3_control_a_parameter_distance
    } else {
        horizon.g3_control_b_parameter_distance
    }
}

fn class(snapshot: &SameBlockSnapshot, slot: usize) -> PairClass {
    if !control_present(snapshot, slot) {
        return PairClass::default();
    }
    let initial_control_better = control_utility(snapshot, slot) > snapshot.g3_utility + 1.0e-7;
    if !initial_control_better {
        return PairClass::default();
    }
    let first_reversal_horizon = snapshot
        .horizons
        .iter()
        .find(|horizon| delta(horizon, slot) < -1.0e-7)
        .map_or(0, |horizon| horizon.horizon);
    let persistent = first_reversal_horizon > 0
        && snapshot
            .horizons
            .iter()
            .filter(|horizon| horizon.horizon >= first_reversal_horizon)
            .all(|horizon| delta(horizon, slot) < -1.0e-7);
    PairClass {
        initial_control_better,
        persistent,
        transient: first_reversal_horizon > 0 && !persistent,
        none: first_reversal_horizon == 0,
    }
}

fn rate(numerator: usize, denominator: usize) -> f64 {
    if denominator == 0 {
        0.0
    } else {
        numerator as f64 / denominator as f64
    }
}

fn summarize(
    results: &[SameBlockSummary],
    domain: u8,
    family: u8,
    replicate: usize,
    slot: usize,
    horizon_index: usize,
) -> StreamStats {
    let rows: Vec<&SameBlockSnapshot> = results
        .iter()
        .flat_map(|result| result.snapshots.iter())
        .filter(|snapshot| {
            snapshot.domain == domain
                && snapshot.family == family
                && snapshot.replicate == replicate
                && control_present(snapshot, slot)
        })
        .collect();
    let initial_control_better = rows
        .iter()
        .filter(|snapshot| class(snapshot, slot).initial_control_better)
        .count();
    let persistent = rows
        .iter()
        .filter(|snapshot| class(snapshot, slot).persistent)
        .count();
    let transient = rows
        .iter()
        .filter(|snapshot| class(snapshot, slot).transient)
        .count();
    let none = rows
        .iter()
        .filter(|snapshot| class(snapshot, slot).none)
        .count();
    let utility_gaps: Vec<f32> = rows
        .iter()
        .map(|snapshot| control_gap(snapshot, slot))
        .collect();
    StreamStats {
        rows: results
            .iter()
            .flat_map(|result| result.snapshots.iter())
            .filter(|snapshot| {
                snapshot.domain == domain
                    && snapshot.family == family
                    && snapshot.replicate == replicate
            })
            .count(),
        matched: rows.len(),
        initial_control_better,
        mean_delta: rows
            .iter()
            .map(|snapshot| f64::from(delta(&snapshot.horizons[horizon_index], slot)))
            .sum::<f64>()
            / rows.len().max(1) as f64,
        g3_better_rate: rate(
            rows.iter()
                .filter(|snapshot| delta(&snapshot.horizons[horizon_index], slot) < -1.0e-7)
                .count(),
            rows.len(),
        ),
        reversal_rate: rate(
            rows.iter()
                .filter(|snapshot| {
                    class(snapshot, slot).initial_control_better
                        && delta(&snapshot.horizons[horizon_index], slot) < -1.0e-7
                })
                .count(),
            initial_control_better,
        ),
        mean_distance: rows
            .iter()
            .map(|snapshot| f64::from(distance(&snapshot.horizons[horizon_index], slot)))
            .sum::<f64>()
            / rows.len().max(1) as f64,
        mean_utility_gap: utility_gaps
            .iter()
            .map(|value| f64::from(*value))
            .sum::<f64>()
            / utility_gaps.len().max(1) as f64,
        max_utility_gap: utility_gaps.iter().copied().fold(0.0, f32::max) as f64,
        persistent,
        transient,
        none,
    }
}

fn render_horizon(horizon: &SameBlockHorizon, slot: usize) -> String {
    let control_train_loss = if slot == 0 {
        horizon.control_a_train_loss
    } else {
        horizon.control_b_train_loss
    };
    let control_validation_loss = if slot == 0 {
        horizon.control_a_validation_loss
    } else {
        horizon.control_b_validation_loss
    };
    format!(
        "{{\"horizon\":{},\"g3_train_loss\":{:.8},\"control_train_loss\":{:.8},\"g3_validation_loss\":{:.8},\"control_validation_loss\":{:.8},\"g3_vs_control_train_delta\":{:.8},\"g3_control_parameter_distance\":{:.8}}}",
        horizon.horizon,
        horizon.g3_train_loss,
        control_train_loss,
        horizon.g3_validation_loss,
        control_validation_loss,
        delta(horizon, slot),
        distance(horizon, slot),
    )
}

fn render_snapshots(results: &[SameBlockSummary]) -> String {
    let mut out = String::from(
        "seed,domain,family,replicate,global_commit,group_left,group_right,selected_pair,control_slot,matched,g3_utility,g3_stratum,control_utility,utility_gap,horizon,g3_train_loss,control_train_loss,g3_vs_control_train_delta,g3_validation_loss,control_validation_loss,g3_control_parameter_distance\n",
    );
    for result in results {
        for snapshot in &result.snapshots {
            for slot in 0..2 {
                let info = if slot == 0 {
                    snapshot.control_a
                } else {
                    snapshot.control_b
                };
                for horizon in &snapshot.horizons {
                    let control_train_loss = if slot == 0 {
                        horizon.control_a_train_loss
                    } else {
                        horizon.control_b_train_loss
                    };
                    let control_validation_loss = if slot == 0 {
                        horizon.control_a_validation_loss
                    } else {
                        horizon.control_b_validation_loss
                    };
                    writeln!(
                        out,
                        "{:016x},{},{},{},{},{},{},{},control_{},{},{:.8},{},{:.8},{:.8},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8}",
                        result.seed,
                        domain_name(snapshot.domain),
                        stream_name(snapshot.family, snapshot.replicate),
                        snapshot.replicate,
                        snapshot.global_commit,
                        snapshot.group_left,
                        snapshot.group_right,
                        snapshot.selected_pair,
                        if slot == 0 { 'a' } else { 'b' },
                        info.present,
                        snapshot.g3_utility,
                        snapshot.g3_stratum,
                        info.utility,
                        info.regret_gap,
                        horizon.horizon,
                        horizon.g3_train_loss,
                        control_train_loss,
                        delta(horizon, slot),
                        horizon.g3_validation_loss,
                        control_validation_loss,
                        distance(horizon, slot),
                    )
                    .expect("String cannot fail");
                }
            }
        }
    }
    out
}

fn render_runs(results: &[SameBlockSummary]) -> String {
    let mut out = String::from(
        "domain,family,control_slot,horizon,rows,matched,initial_control_better,mean_delta,g3_better_rate,reversal_rate,mean_parameter_distance,mean_utility_gap,max_utility_gap,persistent_reversal,transient_reversal,no_reversal\n",
    );
    let streams = [(0_u8, 0_usize), (2, 0), (2, 1)];
    for domain in SAME_BLOCK_DOMAINS {
        for (family, replicate) in streams {
            for slot in 0..2 {
                for (horizon_index, horizon) in SAME_BLOCK_HORIZONS.iter().enumerate() {
                    let stats = summarize(results, domain, family, replicate, slot, horizon_index);
                    writeln!(
                        out,
                        "{},{},control_{},{},{},{},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{},{},{}",
                        domain_name(domain),
                        stream_name(family, replicate),
                        if slot == 0 { 'a' } else { 'b' },
                        horizon,
                        stats.rows,
                        stats.matched,
                        stats.initial_control_better,
                        stats.mean_delta,
                        stats.g3_better_rate,
                        stats.reversal_rate,
                        stats.mean_distance,
                        stats.mean_utility_gap,
                        stats.max_utility_gap,
                        stats.persistent,
                        stats.transient,
                        stats.none,
                    )
                    .expect("String cannot fail");
                }
            }
        }
    }
    out
}

fn render_snapshot_json(snapshot: &SameBlockSnapshot) -> String {
    let horizons = (0..2)
        .flat_map(|slot| {
            snapshot
                .horizons
                .iter()
                .map(move |horizon| render_horizon(horizon, slot))
        })
        .collect::<Vec<_>>();
    format!(
        "{{\"domain\":\"{}\",\"family\":\"{}\",\"replicate\":{},\"global_commit\":{},\"group_left\":{},\"group_right\":{},\"selected_pair\":{},\"g3_utility\":{:.8},\"g3_stratum\":{},\"control_a\":{{\"present\":{},\"utility\":{:.8},\"utility_gap\":{:.8}}},\"control_b\":{{\"present\":{},\"utility\":{:.8},\"utility_gap\":{:.8}}},\"horizons\":[{}]}}",
        domain_name(snapshot.domain),
        stream_name(snapshot.family, snapshot.replicate),
        snapshot.replicate,
        snapshot.global_commit,
        snapshot.group_left,
        snapshot.group_right,
        snapshot.selected_pair,
        snapshot.g3_utility,
        snapshot.g3_stratum,
        snapshot.control_a.present,
        snapshot.control_a.utility,
        snapshot.control_a.regret_gap,
        snapshot.control_b.present,
        snapshot.control_b.utility,
        snapshot.control_b.regret_gap,
        horizons.join(","),
    )
}

fn render_report(results: &[SameBlockSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 600_000 + 1_000);
    out.push_str(
        "{\n  \"schema\": \"adaptive-runtime-ar-01n/v1\",\n  \"scope\": \"engineering-only\",\n  \"task\": \"three-class-spiral\",\n  \"protocol\": \"diagnostic-only same-block matched-program control; N1 uses the selected pair's K2 top-2 x top-2 shortlist; N2 uses the full 7 x 7 action grammar; L0 original schedule and L2 shifted schedules at phases 17 and 36; same-block utility matching tolerance is 5e-5; paired branches share continuation streams\",\n  \"results\": [\n",
    );
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        let snapshots = result
            .snapshots
            .iter()
            .map(render_snapshot_json)
            .collect::<Vec<_>>();
        write!(
            out,
            "    {{\"seed\":{},\"final_train_loss\":{:.8},\"final_validation_loss\":{:.8},\"final_train_accuracy\":{:.8},\"final_validation_accuracy\":{:.8},\"snapshots\":[{}]}}",
            result.seed,
            result.final_train_loss,
            result.final_validation_loss,
            result.final_train_accuracy,
            result.final_validation_accuracy,
            snapshots.join(","),
        )
        .expect("String cannot fail");
    }
    out.push_str("\n  ]\n}\n");
    out
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("spiral-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = same_block_control_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-01n-report.json"),
        render_report(&results),
    )?;
    fs::write(artifact_dir.join("ar-01n-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-01n-snapshots.csv"),
        render_snapshots(&results),
    )?;
    println!("AR-01N — same-block matched-program control");
    println!(
        "trajectory: G3 stratified-64, N1 K2 shortlist and N2 full 7x7 same-block controls, {} commits, {} snapshots/seed",
        TOTAL_COMMITS, SAME_BLOCK_EVERY
    );
    println!(
        "dataset: {} samples (read-only mmap); streams: L0, L2 phase 17, L2 phase 36",
        dataset.samples().len()
    );
    for domain in SAME_BLOCK_DOMAINS {
        for (family, replicate) in [(0_u8, 0_usize), (2, 0), (2, 1)] {
            for slot in 0..2 {
                let stats = summarize(
                    &results,
                    domain,
                    family,
                    replicate,
                    slot,
                    SAME_BLOCK_HORIZONS.len() - 1,
                );
                println!(
                    "{} {} control_{} h=64: rows={} matched={} initial_control_better={} mean_delta={:.6} G3_better={:.1}% reversal={:.1}% mean_gap={:.6} persistent={} transient={} none={}",
                    domain_name(domain),
                    stream_name(family, replicate),
                    if slot == 0 { 'a' } else { 'b' },
                    stats.rows,
                    stats.matched,
                    stats.initial_control_better,
                    stats.mean_delta,
                    stats.g3_better_rate * 100.0,
                    stats.reversal_rate * 100.0,
                    stats.mean_utility_gap,
                    stats.persistent,
                    stats.transient,
                    stats.none,
                );
            }
        }
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}
