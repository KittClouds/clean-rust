use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00e_aud1::{AuditReport, CaptureSummary, run};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let report = run(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00e-aud1-report.json"),
        render_report(&report),
    )?;
    fs::write(
        artifact_dir.join("ar-00e-aud1-capture.csv"),
        render_csv(&report.summaries),
    )?;
    println!("AR-00E-AUD1 — Interaction Capture");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for row in &report.summaries {
        println!(
            "epoch={} {}: abs={:.4}% harmful={:.4}% synergy={:.4}% top10={}/10 same_hidden={}/{} w1b1={}/{}",
            row.snapshot_epoch,
            row.partition,
            row.absolute_capture_fraction * 100.0,
            row.harmful_capture_fraction * 100.0,
            row.synergy_capture_fraction * 100.0,
            row.top10_captured,
            row.same_hidden_captured,
            row.same_hidden_pairs,
            row.w1_b1_captured,
            row.w1_b1_pairs,
        );
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(report: &AuditReport) -> String {
    let mut output = String::with_capacity(12_000);
    output.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00e-aud1/v1\",\n  \"scope\": \"engineering-only\",\n  \"source\": \"AR-00C-INT1 frozen interaction map and AR-00E scheduler seed\",\n  \"summaries\": [\n");
    for (index, row) in report.summaries.iter().enumerate() {
        if index > 0 {
            output.push_str(",\n");
        }
        write_row_json(&mut output, row);
    }
    output.push_str("\n  ]\n}\n");
    output
}

fn write_row_json(output: &mut String, row: &CaptureSummary) {
    write!(
        output,
        "    {{\"epoch\": {}, \"partition\": \"{}\", \"absolute_capture_fraction\": {:.8}, \"harmful_capture_fraction\": {:.8}, \"synergy_capture_fraction\": {:.8}, \"top10_captured\": {}, \"same_hidden_captured\": {}, \"same_hidden_pairs\": {}, \"w1_b1_captured\": {}, \"w1_b1_pairs\": {}}}",
        row.snapshot_epoch,
        row.partition,
        row.absolute_capture_fraction,
        row.harmful_capture_fraction,
        row.synergy_capture_fraction,
        row.top10_captured,
        row.same_hidden_captured,
        row.same_hidden_pairs,
        row.w1_b1_captured,
        row.w1_b1_pairs,
    ).expect("String cannot fail");
}

fn render_csv(rows: &[CaptureSummary]) -> String {
    let mut output = String::with_capacity(rows.len() * 240);
    output.push_str("epoch,partition,absolute_capture_fraction,harmful_capture_fraction,synergy_capture_fraction,top10_captured,top10_fraction,same_hidden_captured,same_hidden_pairs,w1_b1_captured,w1_b1_pairs\n");
    for row in rows {
        writeln!(
            output,
            "{},{},{:.8},{:.8},{:.8},{},{:.8},{},{},{},{}",
            row.snapshot_epoch,
            row.partition,
            row.absolute_capture_fraction,
            row.harmful_capture_fraction,
            row.synergy_capture_fraction,
            row.top10_captured,
            row.top10_fraction,
            row.same_hidden_captured,
            row.same_hidden_pairs,
            row.w1_b1_captured,
            row.w1_b1_pairs,
        )
        .expect("String cannot fail");
    }
    output
}
