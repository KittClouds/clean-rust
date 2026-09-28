use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00c_int1::{
    InteractionMap, PairRecord, SNAPSHOT_EPOCHS, parameter_group, parameter_label, run,
};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let map = run(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00c-int1-report.json"),
        render_report(&map),
    )?;
    fs::write(
        artifact_dir.join("ar-00c-int1-pairs.csv"),
        render_pairs(&map.pairs),
    )?;
    println!("AR-00C-INT1 — Pairwise Action Interaction Map");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for summary in &map.snapshots {
        println!(
            "epoch={}: selected={} pairs={} harmful={} synergistic={} mean={:.8} max_harmful={:.8} strongest_synergy={:.8}",
            summary.epoch,
            summary.selected_actions,
            summary.pair_count,
            summary.harmful_pairs,
            summary.synergistic_pairs,
            summary.mean_interaction,
            summary.max_harmful_interaction,
            summary.strongest_synergy,
        );
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(map: &InteractionMap) -> String {
    let mut report = String::with_capacity(20_000);
    report.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00c-int1/v1\",\n");
    report.push_str("  \"scope\": \"engineering-only\",\n");
    report.push_str("  \"frozen_from\": \"adaptive-runtime-ar-00/v1\",\n");
    report.push_str("  \"definition\": \"pair loss change minus singleton loss changes\",\n");
    report.push_str("  \"action_magnitudes\": [0.02, 0.01, 0.005, 0.0025, 0.00125],\n");
    report.push_str("  \"snapshot_epochs\": [0, 100, 1000, 3000],\n  \"snapshots\": [\n");
    for (index, summary) in map.snapshots.iter().enumerate() {
        if index > 0 {
            report.push_str(",\n");
        }
        write!(
            report,
            "    {{\"epoch\": {}, \"selected_actions\": {}, \"pair_count\": {}, \"harmful_pairs\": {}, \"synergistic_pairs\": {}, \"mean_interaction\": {:.8}, \"max_harmful_interaction\": {:.8}, \"strongest_synergy\": {:.8}}}",
            summary.epoch,
            summary.selected_actions,
            summary.pair_count,
            summary.harmful_pairs,
            summary.synergistic_pairs,
            summary.mean_interaction,
            summary.max_harmful_interaction,
            summary.strongest_synergy,
        )
        .expect("String cannot fail");
    }
    report.push_str("\n  ],\n  \"group_summaries\": [\n");
    for (index, summary) in map.groups.iter().enumerate() {
        if index > 0 {
            report.push_str(",\n");
        }
        write!(
            report,
            "    {{\"epoch\": {}, \"first_group\": \"{}\", \"second_group\": \"{}\", \"pair_count\": {}, \"harmful_pairs\": {}, \"synergistic_pairs\": {}, \"mean_interaction\": {:.8}, \"max_harmful_interaction\": {:.8}, \"strongest_synergy\": {:.8}}}",
            summary.snapshot_epoch,
            summary.first_group.label(),
            summary.second_group.label(),
            summary.pair_count,
            summary.harmful_pairs,
            summary.synergistic_pairs,
            summary.mean_interaction,
            summary.max_harmful_interaction,
            summary.strongest_synergy,
        )
        .expect("String cannot fail");
    }
    report.push_str("\n  ],\n  \"pair_csv\": \"ar-00c-int1-pairs.csv\"\n}\n");
    report
}

fn render_pairs(pairs: &[PairRecord]) -> String {
    let mut csv = String::with_capacity(pairs.len() * 240);
    csv.push_str("snapshot_epoch,first,first_label,first_group,first_delta,first_utility,first_singleton_effect,second,second_label,second_group,second_delta,second_utility,second_singleton_effect,pair_effect,interaction,classification\n");
    for pair in pairs {
        let classification = if pair.is_harmful() {
            "harmful"
        } else if pair.is_synergistic() {
            "synergy"
        } else {
            "near-additive"
        };
        writeln!(
            csv,
            "{},{},\"{}\",{},{:.8},{:.8},{:.8},{},\"{}\",{},{:.8},{:.8},{:.8},{:.8},{:.8},{}",
            pair.snapshot_epoch,
            pair.first,
            parameter_label(pair.first),
            parameter_group(pair.first).label(),
            pair.first_delta,
            pair.first_utility,
            pair.first_singleton_effect,
            pair.second,
            parameter_label(pair.second),
            parameter_group(pair.second).label(),
            pair.second_delta,
            pair.second_utility,
            pair.second_singleton_effect,
            pair.pair_effect,
            pair.interaction,
            classification,
        )
        .expect("String cannot fail");
    }
    csv
}

#[allow(dead_code)]
const _: [usize; 4] = SNAPSHOT_EPOCHS;
