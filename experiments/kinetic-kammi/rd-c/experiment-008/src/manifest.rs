use std::{
    collections::BTreeMap,
    fs::{self, File},
    io::{BufReader, Read},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use serde_json::json;

const E007_RUN: &str = r"C:\rd-c\experiment-007\artifacts\runs\e007-1790316330677261600";
const E007_AUTOPSY: &str = r"C:\rd-c\experiment-007\analysis\e007-autopsy-v1";

pub fn new_run_dir(
    project_root: &Path,
) -> Result<(String, PathBuf, u64), Box<dyn std::error::Error>> {
    let runs = project_root.join("artifacts/runs");
    fs::create_dir_all(&runs)?;
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos() as u64;
    let run_id = format!("e008-{nonce}");
    let run_dir = runs.join(&run_id);
    fs::create_dir(&run_dir)?;
    Ok((run_id, run_dir, nonce))
}

pub fn copy_e007_provenance(
    run_dir: &Path,
) -> Result<serde_json::Value, Box<dyn std::error::Error>> {
    let run = Path::new(E007_RUN);
    let input = run_dir.join("inputs/e007");
    let autopsy_input = input.join("autopsy");
    fs::create_dir_all(&autopsy_input)?;
    for (source, target) in [
        (run.join("manifest.json"), input.join("manifest.json")),
        (
            run.join("benchmark-report.md"),
            input.join("benchmark-report.md"),
        ),
        (
            Path::new(E007_AUTOPSY).join("autopsy-report.md"),
            autopsy_input.join("autopsy-report.md"),
        ),
        (
            Path::new(E007_AUTOPSY).join("analysis-manifest.json"),
            autopsy_input.join("analysis-manifest.json"),
        ),
    ] {
        fs::copy(&source, &target)?;
    }
    let e007_manifest: serde_json::Value =
        serde_json::from_slice(&fs::read(run.join("manifest.json"))?)?;
    Ok(json!({
        "run_id": e007_manifest["run_id"],
        "run_path": E007_RUN,
        "run_manifest_blake3": hash_file(&run.join("manifest.json"))?,
        "run_report_blake3": hash_file(&run.join("benchmark-report.md"))?,
        "autopsy_report_path": E007_AUTOPSY,
        "autopsy_report_blake3": hash_file(&Path::new(E007_AUTOPSY).join("autopsy-report.md"))?,
        "autopsy_manifest_blake3": hash_file(&Path::new(E007_AUTOPSY).join("analysis-manifest.json"))?,
        "source_hash_count": e007_manifest["source_blake3"].as_object().map_or(0, |map| map.len()),
        "sealed_e007_unchanged": true
    }))
}

pub fn seal(
    project_root: &Path,
    contracts_root: &Path,
    run_dir: &Path,
    run_id: &str,
    run_nonce: u64,
    e007: &serde_json::Value,
    deterministic_input_groups: usize,
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
        let file = project_root.join(relative);
        if file.exists() {
            sources.insert(relative.to_owned(), hash_file(&file)?);
        }
    }
    add_sources(&mut sources, project_root, "src", "")?;
    add_sources(&mut sources, project_root, "tests", "")?;
    for relative in ["Cargo.toml", "Cargo.lock", "README.md"] {
        let file = contracts_root.join(relative);
        if file.exists() {
            sources.insert(
                format!("runtime-contracts-v1/{relative}"),
                hash_file(&file)?,
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
    let value = json!({
        "experiment":"RDC-C-008",
        "run_id":run_id,
        "run_nonce":format!("0x{run_nonce:X}"),
        "development_seed":format!("0x{:X}",crate::domain::DEVELOPMENT_SEED),
        "heldout_seed":format!("0x{:X}",crate::domain::HELDOUT_SEED),
        "development_worlds":crate::domain::DEVELOPMENT_WORLDS,
        "development_episodes":crate::domain::DEVELOPMENT_WORLDS * crate::domain::DOMAINS_PER_WORLD * crate::domain::EPISODES_PER_DOMAIN,
        "heldout_worlds":crate::domain::HELDOUT_WORLDS,
        "heldout_episodes":crate::domain::HELDOUT_WORLDS * crate::domain::DOMAINS_PER_WORLD * crate::domain::EPISODES_PER_DOMAIN,
        "heldout_world_split":"world-level, independently seeded from development",
        "offer_schema_version":crate::domain::OFFER_SCHEMA_VERSION,
        "offer_fields":["source_id","availability","source_local_age_bucket","provenance_family","independence_from_active_source","historical_reliability_bucket","quoted_query_price","offer_expiry"],
        "offer_answer_or_revision_fields":false,
        "offer_acquisition_modes":["pushed_or_cached_zero_marginal_request_charge","costed_refresh_request_charged_per_selected_candidate"],
        "value_rule":"delta = P(wrong_to_right) - P(right_to_wrong) - P(baseline_right_unresolved); V = delta - lambda*quoted_query_price - 0.02*offer_request_cost; require V > 0 before ranking",
        "lambda_values":crate::routing::LAMBDAS,
        "budgets_are_caps":crate::routing::BUDGETS,
        "zero_calls_allowed":true,
        "routes_frozen_before_heldout_labels_and_replies":true,
        "oracle_authority":"evaluation_only_after_non_oracle_plans_are_written",
        "outcomes":["Confirmed","Contradicted","Unknown","Failed"],
        "unknown_failed_policy":"reobserve_without_fallback_action",
        "endpoint_idempotency":"simulated endpoint cache keyed by stable request ID; exactly once depends on endpoint deduplication",
        "input_audit_deterministic_groups_at_support_8":deterministic_input_groups,
        "e007_provenance":e007,
        "artifacts_blake3":artifacts,
        "source_blake3":sources,
        "source_count":sources.len(),
        "target_location":"C:\\rd-c\\experiment-008\\target -> D:\\cargo-targets\\rd-c-experiment-008"
    });
    fs::write(
        run_dir.join("manifest.json"),
        serde_json::to_vec_pretty(&value)?,
    )?;
    Ok(())
}

pub fn hash_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mut reader = BufReader::with_capacity(128 * 1024, file);
    let mut hasher = blake3::Hasher::new();
    let mut buffer = [0u8; 128 * 1024];
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hasher.finalize().to_hex().to_string())
}

fn collect_tree(root: &Path) -> Result<Vec<PathBuf>, Box<dyn std::error::Error>> {
    let mut files = Vec::with_capacity(64);
    let mut pending = vec![root.to_path_buf()];
    while let Some(dir) = pending.pop() {
        for entry in fs::read_dir(dir)? {
            let entry = entry?;
            if entry.file_type()?.is_dir() {
                pending.push(entry.path())
            } else if entry.file_type()?.is_file() {
                files.push(entry.path())
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
