mod census;
mod graph;
mod synthetic;

use anyhow::{Context, Result, ensure};
use graph::{BuildManifest, build_all};
use std::fs;
use std::path::Path;
use synthetic::build_teacher_worlds;

const STAGE: &str = r"D:\fly-drop-00-stage\columns";
const ROOT: &str = "experiments/fly-drop-00";
const ARTIFACTS: &str = "experiments/fly-drop-00/artifacts";

fn main() -> Result<()> {
    graph::verify_fixture_projection()?;
    census::verify_fixture()?;
    if std::env::args().nth(1).as_deref() == Some("--verify-only") {
        println!("projection and singular-spectrum fixtures passed");
        return Ok(());
    }
    let root = Path::new(ROOT);
    let artifacts = Path::new(ARTIFACTS);
    ensure!(!artifacts.exists(), "refusing to overwrite existing artifact tree: {}", artifacts.display());
    let stage = Path::new(STAGE);
    let receipt_path = stage.join("columns-receipt.json");
    let receipt: serde_json::Value = serde_json::from_slice(
        &fs::read(&receipt_path).with_context(|| format!("read {}", receipt_path.display()))?,
    )?;
    let rows = receipt["source_rows"].as_u64().context("missing source_rows")? as usize;
    let source_sha = receipt["source_sha256"].as_str().context("missing source hash")?.to_owned();
    fs::create_dir_all(artifacts.join("operators"))?;
    fs::create_dir_all(artifacts.join("teachers"))?;

    let mut manifest = BuildManifest::new(rows, source_sha);
    build_all(stage, artifacts, &mut manifest)?;
    build_teacher_worlds(artifacts, &mut manifest)?;
    let manifest_path = artifacts.join("pretraining-manifest.json");
    fs::write(&manifest_path, serde_json::to_vec_pretty(&manifest)?)?;
    println!("wrote {}", manifest_path.display());
    let _ = root;
    Ok(())
}
