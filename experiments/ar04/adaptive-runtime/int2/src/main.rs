use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_int2::{Category, TopologyReport, TopologySummary, run};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let report = run(dataset.samples());
    fs::write(
        artifact_dir.join("int2-report.json"),
        render_report(&report),
    )?;
    fs::write(
        artifact_dir.join("int2-topology.csv"),
        render_csv(&report.summaries),
    )?;
    println!("INT2 — Interaction Topology");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for row in &report.summaries {
        println!(
            "epoch={} category={}: n={} harmful={:.2}% synergy={:.2}% mean_abs={:.8} q95={:.8} max={:.8} null_ratio={:.3} p={:.4}",
            row.snapshot_epoch,
            row.category.label(),
            row.observed.count,
            row.observed.harmful_rate * 100.0,
            row.observed.synergistic_rate * 100.0,
            row.observed.mean_absolute_interaction,
            row.observed.q95_absolute_interaction,
            row.observed.max_absolute_interaction,
            row.null.observed_over_null,
            row.null.empirical_p_ge_observed,
        );
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(report: &TopologyReport) -> String {
    let mut output = String::with_capacity(60_000);
    output.push_str("{\n  \"schema\": \"adaptive-runtime-int2/v1\",\n");
    output.push_str("  \"scope\": \"engineering-only\",\n");
    output.push_str("  \"permutations\": 512,\n  \"seed\": \"0x8f3c1a275d90b4e1\",\n");
    output.push_str("  \"summaries\": [\n");
    for (index, row) in report.summaries.iter().enumerate() {
        if index > 0 {
            output.push_str(",\n");
        }
        write_summary(&mut output, row);
    }
    output.push_str("\n  ],\n  \"pair_source\": \"AR-00C-INT1\"\n}\n");
    output
}

fn write_summary(output: &mut String, row: &TopologySummary) {
    let observed = row.observed;
    let null = row.null;
    write!(
        output,
        "    {{\"epoch\": {}, \"category\": \"{}\", \"count\": {}, \"harmful_pairs\": {}, \"synergistic_pairs\": {}, \"harmful_rate\": {:.8}, \"synergistic_rate\": {:.8}, \"mean_interaction\": {:.8}, \"mean_absolute_interaction\": {:.8}, \"q90_absolute_interaction\": {:.8}, \"q95_absolute_interaction\": {:.8}, \"max_absolute_interaction\": {:.8}, \"null_mean_absolute\": {:.8}, \"null_q95_mean_absolute\": {:.8}, \"observed_over_null\": {:.8}, \"empirical_p_ge_observed\": {:.8}}}",
        row.snapshot_epoch,
        row.category.label(),
        observed.count,
        observed.harmful_pairs,
        observed.synergistic_pairs,
        observed.harmful_rate,
        observed.synergistic_rate,
        observed.mean_interaction,
        observed.mean_absolute_interaction,
        observed.q90_absolute_interaction,
        observed.q95_absolute_interaction,
        observed.max_absolute_interaction,
        null.null_mean_absolute,
        null.null_q95_mean_absolute,
        null.observed_over_null,
        null.empirical_p_ge_observed,
    )
    .expect("String cannot fail");
}

fn render_csv(rows: &[TopologySummary]) -> String {
    let mut output = String::with_capacity(rows.len() * 280);
    output.push_str("epoch,category,count,harmful_pairs,synergistic_pairs,harmful_rate,synergistic_rate,mean_interaction,mean_absolute_interaction,q90_absolute_interaction,q95_absolute_interaction,max_absolute_interaction,null_mean_absolute,null_q95_mean_absolute,observed_over_null,empirical_p_ge_observed\n");
    for row in rows {
        let observed = row.observed;
        let null = row.null;
        writeln!(
            output,
            "{},{},{},{},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8}",
            row.snapshot_epoch,
            row.category.label(),
            observed.count,
            observed.harmful_pairs,
            observed.synergistic_pairs,
            observed.harmful_rate,
            observed.synergistic_rate,
            observed.mean_interaction,
            observed.mean_absolute_interaction,
            observed.q90_absolute_interaction,
            observed.q95_absolute_interaction,
            observed.max_absolute_interaction,
            null.null_mean_absolute,
            null.null_q95_mean_absolute,
            null.observed_over_null,
            null.empirical_p_ge_observed,
        )
        .expect("String cannot fail");
    }
    output
}

#[allow(dead_code)]
const _: [Category; 6] = Category::all();
