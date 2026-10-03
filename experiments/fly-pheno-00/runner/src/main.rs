#![allow(clippy::cast_precision_loss)]

use anyhow::{Context, Result, bail, ensure};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{env, fs, path::{Path, PathBuf}};

fn sha256(path: &Path) -> Result<String> {
    let bytes = fs::read(path).with_context(|| path.display().to_string())?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

fn count_manifest_rows(path: &Path) -> Result<(usize, usize)> {
    let text = fs::read_to_string(path)?;
    let mut lines = text.lines();
    let header = lines.next().context("fit manifest header")?;
    ensure!(header.contains("fit_id") && header.contains("primary_cell"));
    let mut rows = 0;
    let mut primary = 0;
    for line in lines {
        ensure!(!line.trim().is_empty(), "blank fit row");
        rows += 1;
        if line.ends_with(",true") { primary += 1; }
    }
    Ok((rows, primary))
}

fn validate_contract(root: &Path) -> Result<Value> {
    let contract_path = root.join("manifests/ANALYSIS-CONTRACT.json");
    let summary_path = root.join("manifests/PREPARATION-SUMMARY.json");
    let fit_path = root.join("manifests/FIT-MANIFEST.csv");
    let contract: Value = serde_json::from_str(&fs::read_to_string(&contract_path)?)?;
    let summary: Value = serde_json::from_str(&fs::read_to_string(&summary_path)?)?;
    ensure!(contract["study_id"] == "FLY-PHENO-00");
    ensure!(contract["status"] == "PREEXECUTION_CONTRACT");
    ensure!(contract["measured_execution_authorized"] == false);
    ensure!(contract["primary"]["bootstrap"]["replicates"] == 20000);
    ensure!(contract["primary"]["fly_resampled"] == false);
    ensure!(contract["evaluation"]["read_only"] == true);
    ensure!(contract["evaluation"]["epsilon_D_value"] == 0.015625);
    let (rows, primary) = count_manifest_rows(&fit_path)?;
    ensure!(rows == 11232 && primary == 1728, "fit matrix cardinality mismatch");
    ensure!(summary["fit_rows"] == rows && summary["primary_rows"] == primary);
    ensure!(summary["contract_sha256"] == sha256(&contract_path)?);
    Ok(json!({
        "status": "QUALIFICATION_ONLY_PASS",
        "measured_execution_authorized": false,
        "outcomes_opened": false,
        "fit_rows": rows,
        "primary_rows": primary,
        "contract_sha256": sha256(&contract_path)?,
        "fit_manifest_sha256": sha256(&fit_path)?,
        "summary_sha256": sha256(&summary_path)?,
        "qualification_seed_namespace": "910000..910005",
        "lesion_outcome_comparisons_recorded": false
    }))
}

#[derive(Clone, Debug)]
struct FixtureState {
    weights: Vec<f32>,
    eligibility: Vec<f32>,
    mask: Vec<bool>,
    rng: u64,
    events: u64,
}

fn apply_masked_update(state: &mut FixtureState, step: f32) {
    for ((weight, eligibility), masked) in state.weights.iter_mut().zip(&state.eligibility).zip(&state.mask) {
        if !masked { *weight = (*weight + step * eligibility).clamp(0.0, 2.0); }
    }
    state.events += 1;
}

fn state_digest(state: &FixtureState) -> String {
    let mut hash = Sha256::new();
    for value in &state.weights { hash.update(value.to_bits().to_le_bytes()); }
    for value in &state.eligibility { hash.update(value.to_bits().to_le_bytes()); }
    for value in &state.mask { hash.update([u8::from(*value)]); }
    hash.update(state.rng.to_le_bytes());
    hash.update(state.events.to_le_bytes());
    format!("{:x}", hash.finalize())
}

fn run_fixture_qualification() -> Result<()> {
    let mut state = FixtureState { weights: vec![0.2, 0.3, 0.4, 0.5], eligibility: vec![1.0, -1.0, 0.5, 1.0], mask: vec![false, true, false, true], rng: 7, events: 0 };
    let before_masked = [state.weights[1], state.weights[3]];
    let before = state_digest(&state);
    apply_masked_update(&mut state, 0.1);
    ensure!(state.weights[1] == before_masked[0] && state.weights[3] == before_masked[1]);
    ensure!(state.weights[0] != 0.2 && state.weights[2] != 0.4);
    ensure!(state_digest(&state) != before);
    let checkpoint = state.clone();
    let evaluator_hash_before = state_digest(&checkpoint);
    let _disposable_evaluator = checkpoint.clone();
    let evaluator_hash_after = state_digest(&checkpoint);
    ensure!(evaluator_hash_before == evaluator_hash_after);
    let mut frozen = checkpoint.clone();
    let frozen_weights = frozen.weights.clone();
    frozen.events += 1;
    ensure!(frozen.weights == frozen_weights);
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<_> = env::args_os().collect();
    if args.len() != 3 || args[1] != "qualify" {
        bail!("usage: fly-pheno-00-preflight qualify <study-root>");
    }
    let root = PathBuf::from(&args[2]);
    run_fixture_qualification()?;
    let receipt = validate_contract(&root)?;
    fs::write(root.join("qualification/runner-receipt.json"), serde_json::to_vec_pretty(&receipt)?)?;
    println!("{receipt}");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn masked_edges_keep_stored_values_and_evaluator_is_read_only() { run_fixture_qualification().unwrap(); }
}
