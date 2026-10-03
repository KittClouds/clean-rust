mod model;
mod train;
mod util;

use anyhow::{Context, Result, ensure};
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};

const DEFAULT_RUN: &str = "experiments/fly-drop-00/artifacts/run-FLY-DROP-00-RUN1";

fn main() -> Result<()> {
    let run_dir = std::env::args().nth(1).unwrap_or_else(|| DEFAULT_RUN.to_owned());
    let run_dir = PathBuf::from(run_dir);
    let contract_path = run_dir.join("run-contract.json");
    let contract_bytes = fs::read(&contract_path).with_context(|| format!("read {}", contract_path.display()))?;
    let contract_sha = util::hex(&util::sha256(&contract_bytes));
    let sidecar = fs::read_to_string(run_dir.join("run-contract.sha256"))?;
    ensure!(sidecar.split_whitespace().next() == Some(contract_sha.as_str()), "run contract digest mismatch");
    let contract: Value = serde_json::from_slice(&contract_bytes)?;
    ensure!(contract["run_id"].as_str() == Some("FLY-DROP-00-RUN1"), "unexpected run identity");
    ensure!(contract["seal_sha256"].as_str() == Some("9dc9235c1b5ebf8c8a426f793100f9081cd1242523c27bab00331c2921e85918"), "wrong pretraining seal reference");
    ensure!(contract["status"].as_str() == Some("SEALED_BEFORE_COLLECTION"), "run contract is not sealed for collection");
    ensure!(util::sha256_file(Path::new("experiments/fly-drop-00/PRETRAINING-SEAL.json"))? == contract["seal_sha256"].as_str().unwrap(), "pretraining seal changed");
    let manifest_path = run_dir.join("execution-manifest.json");
    let manifest_bytes = fs::read(&manifest_path)?;
    ensure!(util::hex(&util::sha256(&manifest_bytes)) == contract["execution_manifest_sha256"].as_str().unwrap(), "execution manifest digest mismatch");
    let manifest: Value = serde_json::from_slice(&manifest_bytes)?;
    ensure!(manifest["fits"].as_array().context("execution manifest missing fits")?.len() == 656, "fit count is not 656");

    let frozen = contract["sealed_files"].as_array().context("run contract missing sealed files")?;
    println!("RUN1 pre-fit integrity pass: {} sealed files", frozen.len());
    for record in frozen {
        let path = PathBuf::from(record["path"].as_str().context("sealed file path missing")?);
        let actual = util::sha256_file(&path)?;
        ensure!(actual == record["sha256"].as_str().unwrap(), "sealed file hash changed: {}", path.display());
    }
    verify_run_sources(&contract)?;
    let operator_map = train::load_operators(&manifest)?;
    let train_data = train::load_training_data(&manifest)?;
    let unique_fit_ids: std::collections::HashSet<_> = manifest["fits"].as_array().unwrap().iter()
        .map(|fit| fit["fit_id"].as_str().unwrap().to_owned()).collect();
    ensure!(unique_fit_ids.len() == 656, "duplicate fit IDs in manifest");

    fs::create_dir_all(run_dir.join("fit-receipts"))?;
    fs::create_dir_all(run_dir.join("attempts"))?;
    let fits = manifest["fits"].as_array().unwrap();
    let mut completed = 0usize;
    for fit in fits {
        train::execute_fit(fit, &run_dir, &operator_map, &train_data)?;
        completed += 1;
        if completed % 8 == 0 || completed == fits.len() {
            println!("processed fit slots {completed}/{}", fits.len());
        }
    }
    train::write_collection_tables(fits, &run_dir)?;
    let run_receipt = serde_json::json!({
        "run_id": "FLY-DROP-00-RUN1",
        "status": "COLLECTION_COMPLETE",
        "planned_fits": 656,
        "completed_fit_receipts": completed,
        "epochs_per_fit": 20,
        "updates_per_fit": 1280,
        "total_optimizer_steps": 839680,
        "heldout_policy": "one terminal evaluation pass after optimizer update 1280; no validation reads",
        "analysis_performed": false,
    });
    let collection_receipt = run_dir.join("collection-receipt.json");
    if collection_receipt.exists() {
        let existing: Value = serde_json::from_slice(&fs::read(&collection_receipt)?)?;
        ensure!(existing == run_receipt, "existing collection receipt differs from this frozen collection");
    } else {
        util::write_new_json(&collection_receipt, &run_receipt)?;
    }
    Ok(())
}

fn verify_run_sources(contract: &Value) -> Result<()> {
    let sources = contract["run_files"].as_array().context("run-specific file hashes missing")?;
    for record in sources {
        let path = PathBuf::from(record["path"].as_str().context("run code path missing")?);
        ensure!(util::sha256_file(&path)? == record["sha256"].as_str().unwrap(), "run code/executable hash changed: {}", path.display());
    }
    Ok(())
}
