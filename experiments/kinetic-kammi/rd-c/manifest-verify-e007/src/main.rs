use serde_json::Value;
use std::{env, fs, path::{Path, PathBuf}};

fn digest(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let bytes = fs::read(path).map_err(|error| format!("{}: {error}", path.display()))?;
    Ok(blake3::hash(&bytes).to_hex().to_string())
}

fn check_map(root: &Path, map: &Value, label: &str) -> Result<usize, Box<dyn std::error::Error>> {
    let entries = map.as_object().ok_or("manifest hash map missing")?;
    let mut checked = 0usize;
    let mut bad = Vec::new();
    for (relative, expected) in entries {
        let path = root.join(relative);
        let actual = digest(&path)?;
        if Some(actual.as_str()) != expected.as_str() {
            bad.push(relative.clone());
        }
        checked += 1;
    }
    if !bad.is_empty() {
        return Err(format!("{label} hash mismatch: {}", bad.join(", ")).into());
    }
    Ok(checked)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args_os().skip(1).map(PathBuf::from);
    let run = args.next().ok_or("missing run dir")?;
    let project = args.next().ok_or("missing project root")?;
    let contracts = args.next().ok_or("missing contracts root")?;
    let root_report = args.next().ok_or("missing report mirror")?;
    let manifest: Value = serde_json::from_slice(&fs::read(run.join("manifest.json"))?)?;
    let artifacts = check_map(&run, &manifest["artifacts_blake3"], "artifact")?;
    let source_map = manifest["source_blake3"].as_object().ok_or("source map missing")?;
    let mut sources = 0usize;
    let mut bad_sources = Vec::new();
    for (relative, expected) in source_map {
        let relative = relative.as_str();
        let path = if let Some(suffix) = relative.strip_prefix("runtime-contracts-v1/") {
            contracts.join(suffix)
        } else {
            project.join(relative)
        };
        if Some(digest(&path)?.as_str()) != expected.as_str() {
            bad_sources.push(relative.to_owned());
        }
        sources += 1;
    }
    if !bad_sources.is_empty() {
        return Err(format!("source hash mismatch: {}", bad_sources.join(", ")).into());
    }
    let copied_e006 = run.join("inputs/e006");
    let e006_run = PathBuf::from(manifest["e006_provenance"]["run_path"].as_str().ok_or("E006 path missing")?);
    for (copy_name, source_name) in [
        ("manifest.json", "manifest.json"),
        ("benchmark-report.md", "benchmark-report.md"),
        ("crash-results.csv", "crash-recovery/crash-results.csv"),
    ] {
        if fs::read(copied_e006.join(copy_name))? != fs::read(e006_run.join(source_name))? {
            return Err(format!("E006 provenance copy mismatch: {copy_name}").into());
        }
    }
    if fs::read(root_report)? != fs::read(run.join("benchmark-report.md"))? {
        return Err("root report mirror differs from sealed run report".into());
    }
    println!("Verified {artifacts} artifact hashes and {sources} source hashes; E006 provenance copies and report mirror match.");
    Ok(())
}




