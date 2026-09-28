use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_01i::{
    INDIFFERENCE_SNAPSHOTS, IndifferenceSnapshot, IndifferenceSummary, MappedDataset,
    indifference_all, write_dataset,
};

#[derive(Clone, Copy, Debug, Default)]
struct SeedStats {
    selected_snapshots: usize,
    mean_block_regret: f64,
    median_block_regret: f64,
    p90_block_regret: f64,
    p95_block_regret: f64,
    p99_block_regret: f64,
    max_block_regret: f64,
    mean_program_regret: f64,
    median_program_regret: f64,
    p90_program_regret: f64,
    p95_program_regret: f64,
    p99_program_regret: f64,
    max_program_regret: f64,
    mean_selected_block_rank: f64,
    tail_block_1e5: f64,
    tail_block_1e4: f64,
    tail_block_1e3: f64,
    tail_block_1e2: f64,
    tail_program_1e5: f64,
    tail_program_1e4: f64,
    tail_program_1e3: f64,
    tail_program_1e2: f64,
    mean_near_1pct: f64,
    mean_near_5pct: f64,
    selected_near_1pct: f64,
    selected_near_5pct: f64,
    selected_block_positive: f64,
    selected_block_harmful: f64,
    selected_program_positive: f64,
    selected_program_harmful: f64,
    mean_positive_blocks: f64,
    mean_neutral_blocks: f64,
    mean_harmful_blocks: f64,
}

fn quantile(values: &[f32], fraction: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut ordered = values.to_vec();
    ordered.sort_by(f32::total_cmp);
    let index = ((ordered.len() - 1) as f64 * fraction).round() as usize;
    ordered[index] as f64
}

fn mean(values: &[f32]) -> f64 {
    if values.is_empty() {
        0.0
    } else {
        values.iter().map(|value| *value as f64).sum::<f64>() / values.len() as f64
    }
}

fn rate(values: &[bool]) -> f64 {
    if values.is_empty() {
        0.0
    } else {
        values.iter().filter(|&&value| value).count() as f64 / values.len() as f64
    }
}

fn summarize(result: &IndifferenceSummary) -> SeedStats {
    let selected: Vec<&IndifferenceSnapshot> = result
        .snapshots
        .iter()
        .filter(|snapshot| snapshot.selected_present)
        .collect();
    let block_regrets: Vec<f32> = selected
        .iter()
        .map(|snapshot| snapshot.selected_block_regret)
        .collect();
    let program_regrets: Vec<f32> = selected
        .iter()
        .map(|snapshot| snapshot.selected_program_regret)
        .collect();
    let block_ranks: Vec<f32> = selected
        .iter()
        .map(|snapshot| snapshot.selected_block_rank as f32)
        .collect();
    let near_1pct: Vec<f32> = result
        .snapshots
        .iter()
        .map(|snapshot| snapshot.near_relative_1pct as f32 / snapshot.block_count as f32)
        .collect();
    let near_5pct: Vec<f32> = result
        .snapshots
        .iter()
        .map(|snapshot| snapshot.near_relative_5pct as f32 / snapshot.block_count as f32)
        .collect();
    let block_tail = |threshold: f32| {
        rate(
            &selected
                .iter()
                .map(|snapshot| snapshot.selected_block_regret > threshold)
                .collect::<Vec<_>>(),
        )
    };
    let program_tail = |threshold: f32| {
        rate(
            &selected
                .iter()
                .map(|snapshot| snapshot.selected_program_regret > threshold)
                .collect::<Vec<_>>(),
        )
    };
    SeedStats {
        selected_snapshots: selected.len(),
        mean_block_regret: mean(&block_regrets),
        median_block_regret: quantile(&block_regrets, 0.50),
        p90_block_regret: quantile(&block_regrets, 0.90),
        p95_block_regret: quantile(&block_regrets, 0.95),
        p99_block_regret: quantile(&block_regrets, 0.99),
        max_block_regret: block_regrets.iter().copied().fold(0.0, f32::max) as f64,
        mean_program_regret: mean(&program_regrets),
        median_program_regret: quantile(&program_regrets, 0.50),
        p90_program_regret: quantile(&program_regrets, 0.90),
        p95_program_regret: quantile(&program_regrets, 0.95),
        p99_program_regret: quantile(&program_regrets, 0.99),
        max_program_regret: program_regrets.iter().copied().fold(0.0, f32::max) as f64,
        mean_selected_block_rank: mean(&block_ranks),
        tail_block_1e5: block_tail(1.0e-5),
        tail_block_1e4: block_tail(1.0e-4),
        tail_block_1e3: block_tail(1.0e-3),
        tail_block_1e2: block_tail(1.0e-2),
        tail_program_1e5: program_tail(1.0e-5),
        tail_program_1e4: program_tail(1.0e-4),
        tail_program_1e3: program_tail(1.0e-3),
        tail_program_1e2: program_tail(1.0e-2),
        mean_near_1pct: mean(&near_1pct),
        mean_near_5pct: mean(&near_5pct),
        selected_near_1pct: rate(
            &selected
                .iter()
                .map(|snapshot| snapshot.selected_block_near_1pct)
                .collect::<Vec<_>>(),
        ),
        selected_near_5pct: rate(
            &selected
                .iter()
                .map(|snapshot| snapshot.selected_block_near_5pct)
                .collect::<Vec<_>>(),
        ),
        selected_block_positive: rate(
            &selected
                .iter()
                .map(|snapshot| snapshot.selected_block_positive)
                .collect::<Vec<_>>(),
        ),
        selected_block_harmful: rate(
            &selected
                .iter()
                .map(|snapshot| snapshot.selected_block_harmful)
                .collect::<Vec<_>>(),
        ),
        selected_program_positive: rate(
            &selected
                .iter()
                .map(|snapshot| snapshot.selected_program_positive)
                .collect::<Vec<_>>(),
        ),
        selected_program_harmful: rate(
            &selected
                .iter()
                .map(|snapshot| snapshot.selected_program_harmful)
                .collect::<Vec<_>>(),
        ),
        mean_positive_blocks: mean(
            &result
                .snapshots
                .iter()
                .map(|snapshot| snapshot.positive_blocks as f32)
                .collect::<Vec<_>>(),
        ),
        mean_neutral_blocks: mean(
            &result
                .snapshots
                .iter()
                .map(|snapshot| snapshot.neutral_blocks as f32)
                .collect::<Vec<_>>(),
        ),
        mean_harmful_blocks: mean(
            &result
                .snapshots
                .iter()
                .map(|snapshot| snapshot.harmful_blocks as f32)
                .collect::<Vec<_>>(),
        ),
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("spiral-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = indifference_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-01i-report.json"),
        render_report(&results),
    )?;
    fs::write(artifact_dir.join("ar-01i-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-01i-snapshots.csv"),
        render_snapshots(&results),
    )?;
    println!("AR-01I — opportunity indifference geometry");
    println!(
        "trajectory: G3 stratified-64, K2, {} commits, {} snapshots/seed",
        adaptive_runtime_ar_01i::TOTAL_COMMITS,
        INDIFFERENCE_SNAPSHOTS,
    );
    println!(
        "dataset: {} samples (read-only mmap)",
        dataset.samples().len()
    );
    for result in &results {
        let stats = summarize(result);
        println!(
            "seed={:016x}: val_loss={:.6} val_acc={:.1}% mean_block_regret={:.6} p95={:.6} mean_rank={:.1} near5={:.1}% harmful_block={:.1}%",
            result.seed,
            result.final_validation_loss,
            result.final_validation_accuracy * 100.0,
            stats.mean_block_regret,
            stats.p95_block_regret,
            stats.mean_selected_block_rank,
            stats.mean_near_5pct * 100.0,
            stats.selected_block_harmful * 100.0,
        );
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(results: &[IndifferenceSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 30_000 + 1_000);
    out.push_str(
        "{\n  \"schema\": \"adaptive-runtime-ar-01i/v1\",\n  \"scope\": \"engineering-only\",\n  \"task\": \"three-class-spiral\",\n  \"protocol\": \"diagnostic-only opportunity indifference audit of fixed G3 stratified-64 trajectories; K2 top-2x2 candidates; full-96 immediate utility reference; 62 temporary planning blocks (61 pairs plus one singleton); snapshots every 50 commits; three seeds; no shadow measurement affects commits\",\n  \"results\": [\n",
    );
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        let stats = summarize(result);
        write!(
            out,
            "    {{\"seed\":{},\"final_train_loss\":{:.8},\"final_validation_loss\":{:.8},\"final_train_accuracy\":{:.8},\"final_validation_accuracy\":{:.8},\"summary\":{},\"snapshots\":[{}]}}",
            result.seed,
            result.final_train_loss,
            result.final_validation_loss,
            result.final_train_accuracy,
            result.final_validation_accuracy,
            render_stats(stats),
            result
                .snapshots
                .iter()
                .map(render_snapshot)
                .collect::<Vec<_>>()
                .join(","),
        )
        .expect("String cannot fail");
    }
    out.push_str("\n  ]\n}\n");
    out
}

fn render_stats(stats: SeedStats) -> String {
    format!(
        "{{\"selected_snapshots\":{},\"mean_block_regret\":{:.8},\"median_block_regret\":{:.8},\"p90_block_regret\":{:.8},\"p95_block_regret\":{:.8},\"p99_block_regret\":{:.8},\"max_block_regret\":{:.8},\"mean_program_regret\":{:.8},\"median_program_regret\":{:.8},\"p90_program_regret\":{:.8},\"p95_program_regret\":{:.8},\"p99_program_regret\":{:.8},\"max_program_regret\":{:.8},\"mean_selected_block_rank\":{:.8},\"tail_block_1e5\":{:.8},\"tail_block_1e4\":{:.8},\"tail_block_1e3\":{:.8},\"tail_block_1e2\":{:.8},\"tail_program_1e5\":{:.8},\"tail_program_1e4\":{:.8},\"tail_program_1e3\":{:.8},\"tail_program_1e2\":{:.8},\"mean_near_1pct\":{:.8},\"mean_near_5pct\":{:.8},\"selected_near_1pct\":{:.8},\"selected_near_5pct\":{:.8},\"selected_block_positive\":{:.8},\"selected_block_harmful\":{:.8},\"selected_program_positive\":{:.8},\"selected_program_harmful\":{:.8},\"mean_positive_blocks\":{:.8},\"mean_neutral_blocks\":{:.8},\"mean_harmful_blocks\":{:.8}}}",
        stats.selected_snapshots,
        stats.mean_block_regret,
        stats.median_block_regret,
        stats.p90_block_regret,
        stats.p95_block_regret,
        stats.p99_block_regret,
        stats.max_block_regret,
        stats.mean_program_regret,
        stats.median_program_regret,
        stats.p90_program_regret,
        stats.p95_program_regret,
        stats.p99_program_regret,
        stats.max_program_regret,
        stats.mean_selected_block_rank,
        stats.tail_block_1e5,
        stats.tail_block_1e4,
        stats.tail_block_1e3,
        stats.tail_block_1e2,
        stats.tail_program_1e5,
        stats.tail_program_1e4,
        stats.tail_program_1e3,
        stats.tail_program_1e2,
        stats.mean_near_1pct,
        stats.mean_near_5pct,
        stats.selected_near_1pct,
        stats.selected_near_5pct,
        stats.selected_block_positive,
        stats.selected_block_harmful,
        stats.selected_program_positive,
        stats.selected_program_harmful,
        stats.mean_positive_blocks,
        stats.mean_neutral_blocks,
        stats.mean_harmful_blocks,
    )
}

fn render_snapshot(snapshot: &IndifferenceSnapshot) -> String {
    format!(
        "{{\"global_commit\":{},\"block_count\":{},\"best_utility\":{:.8},\"selected_block_utility\":{:.8},\"selected_program_utility\":{:.8},\"selected_block_regret\":{:.8},\"selected_program_regret\":{:.8},\"selected_block_rank\":{},\"selected_present\":{},\"near_abs_1e5\":{},\"near_abs_1e4\":{},\"near_abs_1e3\":{},\"near_abs_1e2\":{},\"near_relative_1pct\":{},\"near_relative_5pct\":{},\"positive_blocks\":{},\"neutral_blocks\":{},\"harmful_blocks\":{},\"selected_block_near_1pct\":{},\"selected_block_near_5pct\":{},\"selected_block_positive\":{},\"selected_block_harmful\":{},\"selected_program_positive\":{},\"selected_program_harmful\":{}}}",
        snapshot.global_commit,
        snapshot.block_count,
        snapshot.best_utility,
        snapshot.selected_block_utility,
        snapshot.selected_program_utility,
        snapshot.selected_block_regret,
        snapshot.selected_program_regret,
        snapshot.selected_block_rank,
        snapshot.selected_present,
        snapshot.near_abs_1e5,
        snapshot.near_abs_1e4,
        snapshot.near_abs_1e3,
        snapshot.near_abs_1e2,
        snapshot.near_relative_1pct,
        snapshot.near_relative_5pct,
        snapshot.positive_blocks,
        snapshot.neutral_blocks,
        snapshot.harmful_blocks,
        snapshot.selected_block_near_1pct,
        snapshot.selected_block_near_5pct,
        snapshot.selected_block_positive,
        snapshot.selected_block_harmful,
        snapshot.selected_program_positive,
        snapshot.selected_program_harmful,
    )
}

#[allow(clippy::needless_range_loop)]
fn render_runs(results: &[IndifferenceSummary]) -> String {
    let mut out = String::from(
        "seed,final_train_loss,final_validation_loss,final_train_accuracy,final_validation_accuracy,selected_snapshots,mean_block_regret,median_block_regret,p90_block_regret,p95_block_regret,p99_block_regret,max_block_regret,mean_program_regret,median_program_regret,p90_program_regret,p95_program_regret,p99_program_regret,max_program_regret,mean_selected_block_rank,tail_block_1e5,tail_block_1e4,tail_block_1e3,tail_block_1e2,tail_program_1e5,tail_program_1e4,tail_program_1e3,tail_program_1e2,mean_near_1pct,mean_near_5pct,selected_near_1pct,selected_near_5pct,selected_block_positive,selected_block_harmful,selected_program_positive,selected_program_harmful,mean_positive_blocks,mean_neutral_blocks,mean_harmful_blocks\n",
    );
    for result in results {
        let stats = summarize(result);
        writeln!(
            out,
            "{:016x},{:.8},{:.8},{:.8},{:.8},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8}",
            result.seed,
            result.final_train_loss,
            result.final_validation_loss,
            result.final_train_accuracy,
            result.final_validation_accuracy,
            stats.selected_snapshots,
            stats.mean_block_regret,
            stats.median_block_regret,
            stats.p90_block_regret,
            stats.p95_block_regret,
            stats.p99_block_regret,
            stats.max_block_regret,
            stats.mean_program_regret,
            stats.median_program_regret,
            stats.p90_program_regret,
            stats.p95_program_regret,
            stats.p99_program_regret,
            stats.max_program_regret,
            stats.mean_selected_block_rank,
            stats.tail_block_1e5,
            stats.tail_block_1e4,
            stats.tail_block_1e3,
            stats.tail_block_1e2,
            stats.tail_program_1e5,
            stats.tail_program_1e4,
            stats.tail_program_1e3,
            stats.tail_program_1e2,
            stats.mean_near_1pct,
            stats.mean_near_5pct,
            stats.selected_near_1pct,
            stats.selected_near_5pct,
            stats.selected_block_positive,
            stats.selected_block_harmful,
            stats.selected_program_positive,
            stats.selected_program_harmful,
            stats.mean_positive_blocks,
            stats.mean_neutral_blocks,
            stats.mean_harmful_blocks,
        )
        .expect("String cannot fail");
    }
    out
}

fn render_snapshots(results: &[IndifferenceSummary]) -> String {
    let mut out = String::from(
        "seed,global_commit,block_count,best_utility,selected_block_utility,selected_program_utility,selected_block_regret,selected_program_regret,selected_block_rank,selected_present,near_abs_1e5,near_abs_1e4,near_abs_1e3,near_abs_1e2,near_relative_1pct,near_relative_5pct,positive_blocks,neutral_blocks,harmful_blocks,selected_block_near_1pct,selected_block_near_5pct,selected_block_positive,selected_block_harmful,selected_program_positive,selected_program_harmful\n",
    );
    for result in results {
        for snapshot in &result.snapshots {
            writeln!(
                out,
                "{:016x},{},{},{:.8},{:.8},{:.8},{:.8},{:.8},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
                result.seed,
                snapshot.global_commit,
                snapshot.block_count,
                snapshot.best_utility,
                snapshot.selected_block_utility,
                snapshot.selected_program_utility,
                snapshot.selected_block_regret,
                snapshot.selected_program_regret,
                snapshot.selected_block_rank,
                snapshot.selected_present,
                snapshot.near_abs_1e5,
                snapshot.near_abs_1e4,
                snapshot.near_abs_1e3,
                snapshot.near_abs_1e2,
                snapshot.near_relative_1pct,
                snapshot.near_relative_5pct,
                snapshot.positive_blocks,
                snapshot.neutral_blocks,
                snapshot.harmful_blocks,
                snapshot.selected_block_near_1pct,
                snapshot.selected_block_near_5pct,
                snapshot.selected_block_positive,
                snapshot.selected_block_harmful,
                snapshot.selected_program_positive,
                snapshot.selected_program_harmful,
            )
            .expect("String cannot fail");
        }
    }
    out
}
