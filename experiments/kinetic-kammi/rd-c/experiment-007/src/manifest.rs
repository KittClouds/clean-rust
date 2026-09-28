use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use serde_json::json;

const E006_RUN: &str = r"C:\rd-c\experiment-006\artifacts\runs\e006-1790312837837870700";

pub fn new_run_dir(project_root: &Path) -> Result<(String, PathBuf), Box<dyn std::error::Error>> {
    let runs = project_root.join("artifacts/runs");
    fs::create_dir_all(&runs)?;
    let time = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let run_id = format!("e007-{time}");
    let run_dir = runs.join(&run_id);
    fs::create_dir(&run_dir)?;
    Ok((run_id, run_dir))
}

pub fn copy_e006_provenance(
    run_dir: &Path,
) -> Result<serde_json::Value, Box<dyn std::error::Error>> {
    let e006 = Path::new(E006_RUN);
    let input_dir = run_dir.join("inputs/e006");
    fs::create_dir_all(&input_dir)?;
    fs::copy(e006.join("manifest.json"), input_dir.join("manifest.json"))?;
    fs::copy(
        e006.join("benchmark-report.md"),
        input_dir.join("benchmark-report.md"),
    )?;
    fs::copy(
        e006.join("crash-recovery/crash-results.csv"),
        input_dir.join("crash-results.csv"),
    )?;
    let manifest_path = e006.join("manifest.json");
    let manifest: serde_json::Value = serde_json::from_slice(&fs::read(&manifest_path)?)?;
    Ok(json!({
        "run_id": manifest["run_id"],
        "run_path": E006_RUN,
        "manifest_blake3": hash_file(&manifest_path)?,
        "report_blake3": hash_file(&e006.join("benchmark-report.md"))?,
        "source_hash_count": manifest["source_blake3"].as_object().map_or(0, |value| value.len()),
    }))
}

pub fn seal(
    project_root: &Path,
    contracts_root: &Path,
    run_dir: &Path,
    run_id: &str,
    e006: &serde_json::Value,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut artifacts = BTreeMap::<String, String>::new();
    for path in collect_tree(run_dir)? {
        let relative = path
            .strip_prefix(run_dir)?
            .to_string_lossy()
            .replace('\\', "/");
        if relative != "manifest.json" {
            artifacts.insert(relative, hash_file(&path)?);
        }
    }
    let mut sources = BTreeMap::<String, String>::new();
    for relative in ["Cargo.toml", "Cargo.lock", "README.md", "BASELINE.md"] {
        let path = project_root.join(relative);
        if path.exists() {
            sources.insert(relative.to_owned(), hash_file(&path)?);
        }
    }
    add_sources(&mut sources, project_root, "src", "")?;
    add_sources(&mut sources, project_root, "tests", "")?;
    for relative in ["Cargo.toml", "Cargo.lock", "README.md"] {
        let path = contracts_root.join(relative);
        if path.exists() {
            sources.insert(
                format!("runtime-contracts-v1/{relative}"),
                hash_file(&path)?,
            );
        }
    }
    add_sources(&mut sources, contracts_root, "src", "runtime-contracts-v1/")?;
    add_sources(
        &mut sources,
        contracts_root,
        "tests",
        "runtime-contracts-v1/",
    )?;
    let input_source_count = sources.len();
    let value = json!({
        "experiment": "RDC-C-007",
        "run_id": run_id,
        "development_seed": format!("0x{:X}", crate::domain::DEVELOPMENT_SEED),
        "heldout_seed": format!("0x{:X}", crate::domain::HELDOUT_SEED),
        "runtime_seed": format!("0x{:X}", crate::runtime::RUN_SEED),
        "development_worlds": crate::domain::DEVELOPMENT_WORLDS,
        "development_episodes": crate::domain::DEVELOPMENT_WORLDS * crate::domain::DEVELOPMENT_DOMAINS * crate::domain::EPISODES_PER_DOMAIN,
        "heldout_worlds": crate::domain::HELDOUT_WORLDS,
        "heldout_episodes": crate::domain::HELDOUT_WORLDS * crate::domain::HELDOUT_DOMAINS * crate::domain::EPISODES_PER_DOMAIN,
        "budgets": crate::routing::BUDGETS,
        "router_feature_schema": ["bias", "observer_disagreement", "warning", "age", "confidence_gap", "revision_gap", "audit_selected", "stale_visible"],
        "feature_router_receives_domain_id": false,
        "feature_router_receives_world_id": false,
        "oracle_authority": "evaluation_only_after_frozen_route_plans",
        "inspection_outcomes": ["Confirmed", "Contradicted", "Unknown", "Failed"],
        "unknown_failed_policy": "reobserve_without_fallback_action",
        "endpoint_idempotency": "simulated endpoint cache keyed by stable request ID",
        "e006_provenance": e006,
        "artifacts_blake3": artifacts,
        "source_blake3": sources,
        "source_count": input_source_count,
    });
    fs::write(
        run_dir.join("manifest.json"),
        serde_json::to_vec_pretty(&value)?,
    )?;
    Ok(())
}

pub fn hash_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let bytes = fs::read(path)?;
    Ok(blake3::hash(&bytes).to_hex().to_string())
}

fn collect_tree(root: &Path) -> Result<Vec<PathBuf>, Box<dyn std::error::Error>> {
    let mut files = Vec::with_capacity(64);
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        for entry in fs::read_dir(directory)? {
            let entry = entry?;
            if entry.file_type()?.is_dir() {
                pending.push(entry.path());
            } else if entry.file_type()?.is_file() {
                files.push(entry.path());
            }
        }
    }
    files.sort_unstable();
    Ok(files)
}

fn add_sources(
    sources: &mut BTreeMap<String, String>,
    root: &Path,
    folder: &str,
    prefix: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    for path in collect_tree(&root.join(folder))? {
        let relative = path
            .strip_prefix(root)?
            .to_string_lossy()
            .replace('\\', "/");
        sources.insert(format!("{prefix}{relative}"), hash_file(&path)?);
    }
    Ok(())
}
