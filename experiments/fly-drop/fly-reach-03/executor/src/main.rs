mod collector;
mod graph;
mod precision;
mod qualification;
mod reach_sim;
mod rng;
mod symmetry;
mod task;

use anyhow::{Context, Result, bail, ensure};
use hashbrown::HashSet;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    env, fs,
    path::{Path, PathBuf},
};

const EXPECTED_CONTRACT_SHA256: &str =
    "6beb47c4784a7d6e37a91e45688dd86e50b15291a8f0dbf07c56c71aefbe47a7";
const EXPECTED_SEAL_SCHEMA: &str = "FLY-REACH-03-v0.3-precode-seal-v2";
const EXPECTED_MACHINE_SCHEMA: &str = "FLY-REACH-03-math-objects-v0.3";
const EXPECTED_EXECUTION_SCHEMA: &str = "FLY-REACH-03-execution-contract-v0.1";

fn hash_file(path: &Path) -> Result<String> {
    let bytes = fs::read(path).with_context(|| path.display().to_string())?;
    let mut digest = Sha256::new();
    digest.update(bytes);
    Ok(format!("{:x}", digest.finalize()))
}

fn canonical_value(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let ordered: BTreeMap<String, Value> = map
                .iter()
                .map(|(key, value)| (key.clone(), canonical_value(value)))
                .collect();
            let mut output = Map::new();
            for (key, value) in ordered {
                output.insert(key, value);
            }
            Value::Object(output)
        }
        Value::Array(values) => Value::Array(values.iter().map(canonical_value).collect()),
        other => other.clone(),
    }
}

fn canonical_json(value: &Value) -> Result<Vec<u8>> {
    Ok(serde_json::to_vec(&canonical_value(value))?)
}

fn json_string<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .with_context(|| format!("missing string field {key}"))
}

fn verify_artifact(root: &Path, entry: &Value) -> Result<Value> {
    let relative = json_string(entry, "path")?;
    let path = root.join(relative);
    ensure!(path.is_file(), "missing sealed artifact {}", path.display());
    let bytes = fs::metadata(&path)?.len();
    let expected_bytes = entry
        .get("bytes")
        .and_then(Value::as_u64)
        .context("artifact bytes")?;
    let actual_hash = hash_file(&path)?;
    let expected_hash = json_string(entry, "sha256")?;
    ensure!(
        bytes == expected_bytes,
        "size mismatch for {}",
        path.display()
    );
    ensure!(
        actual_hash == expected_hash,
        "hash mismatch for {}",
        path.display()
    );
    Ok(json!({"path": relative, "bytes": bytes, "sha256": actual_hash, "pass": true}))
}

fn verify_authority(study: &Path) -> Result<Value> {
    let seal_path = study.join("MATH-CONTRACT-v0.3-SEAL.json");
    let seal: Value = serde_json::from_slice(&fs::read(&seal_path)?)?;
    ensure!(json_string(&seal, "schema")? == EXPECTED_SEAL_SCHEMA);
    ensure!(json_string(&seal, "status")? == "SEALED_PRE_CODE");
    ensure!(seal["execution_authorized"] == false);
    ensure!(seal["implementation_authorized"] == false);

    let contract_path = study.join("MATH-CONTRACT-v0.3-AUTHORITATIVE.md");
    ensure!(
        hash_file(&contract_path)? == EXPECTED_CONTRACT_SHA256,
        "authoritative contract hash mismatch"
    );
    let machine_path = study.join("math-objects-v0.3.json");
    let machine: Value = serde_json::from_slice(&fs::read(&machine_path)?)?;
    ensure!(json_string(&machine, "schema")? == EXPECTED_MACHINE_SCHEMA);
    ensure!(json_string(&machine, "version")? == "0.3");
    ensure!(machine["execution_authorized"] == false);
    let required: HashSet<&str> = [
        "target",
        "filtrations",
        "scoring",
        "support",
        "estimands",
        "weighting",
        "temporal",
        "uncertainty",
    ]
    .into_iter()
    .collect();
    for key in required {
        ensure!(
            machine.get(key).is_some(),
            "missing machine contract section {key}"
        );
    }

    let repo = study
        .parent()
        .context("study parent")?
        .parent()
        .context("repo parent")?;
    let controlling = seal["controlling_artifacts"]
        .as_array()
        .context("controlling artifacts")?
        .iter()
        .map(|entry| verify_artifact(study, entry))
        .collect::<Result<Vec<_>>>()?;
    let historical = seal["incorporated_historical_artifacts"]
        .as_array()
        .context("historical artifacts")?
        .iter()
        .map(|entry| verify_artifact(study, entry))
        .collect::<Result<Vec<_>>>()?;
    let receipts = seal["authoritative_reach02_receipts"]
        .as_array()
        .context("reach02 receipts")?
        .iter()
        .map(|entry| verify_artifact(repo, entry))
        .collect::<Result<Vec<_>>>()?;

    let run1 = repo.join(
        "experiments/fly-reach-02/artifacts/REACH02-RUN1/REACH02-RUN1-NONPROMOTABLE-RECEIPT.json",
    );
    let run1_value: Value = serde_json::from_slice(&fs::read(run1)?)?;
    ensure!(
        run1_value["non_promotable"] == true
            || run1_value["status"]
                .as_str()
                .unwrap_or("")
                .contains("NONPROMOTABLE")
    );

    Ok(json!({
        "schema": "FLY-REACH-03-authority-audit-v1",
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "machine_schema": EXPECTED_MACHINE_SCHEMA,
        "controlling_artifacts": controlling,
        "historical_artifacts": historical,
        "reach02_receipts": receipts,
        "run1_nonpromotable": true,
        "pass": true,
    }))
}

fn run_contract_roundtrip(study: &Path) -> Result<()> {
    let authority = verify_authority(study)?;
    let machine_path = study.join("math-objects-v0.3.json");
    let original: Value = serde_json::from_slice(&fs::read(&machine_path)?)?;
    let canonical = canonical_json(&original)?;
    let reparsed: Value = serde_json::from_slice(&canonical)?;
    let second = canonical_json(&reparsed)?;
    ensure!(
        canonical == second,
        "canonical contract round-trip changed bytes"
    );
    let output = json!({
        "schema": "FLY-REACH-03-runtime-contract-roundtrip-v1",
        "status": "PASS",
        "authority": authority,
        "machine_contract_sha256": hash_file(&machine_path)?,
        "canonical_bytes": canonical.len(),
        "canonical_sha256": format!("{:x}", Sha256::digest(&canonical)),
        "roundtrip_equal": true,
        "execution_authorized": false,
    });
    let execution_path = study.join("EXECUTION-CONTRACT-v0.1.json");
    let execution: Value = serde_json::from_slice(&fs::read(&execution_path)?)?;
    ensure!(json_string(&execution, "schema")? == EXPECTED_EXECUTION_SCHEMA);
    ensure!(execution["execution_authorized"] == false);
    ensure!(execution["authoritative_math_contract_sha256"] == EXPECTED_CONTRACT_SHA256);
    for key in [
        "target",
        "support",
        "primary_population",
        "filtrations",
        "sampling",
        "temporal",
        "estimator",
        "inference",
        "integrity",
    ] {
        ensure!(
            execution.get(key).is_some(),
            "missing execution contract section {key}"
        );
    }
    let filtration_keys: HashSet<&str> = execution["filtrations"]
        .as_object()
        .context("filtration object")?
        .keys()
        .map(String::as_str)
        .collect();
    for key in ["F0", "F1", "F2", "F3a", "F3b", "F4"] {
        ensure!(
            filtration_keys.contains(key),
            "missing executable filtration {key}"
        );
    }
    let execution_canonical = canonical_json(&execution)?;
    let execution_reparsed: Value = serde_json::from_slice(&execution_canonical)?;
    ensure!(execution_canonical == canonical_json(&execution_reparsed)?);
    let execution_sha256 = hash_file(&execution_path)?;
    let execution_output = json!({
        "schema": "FLY-REACH-03-execution-contract-roundtrip-v1",
        "status": "PASS",
        "execution_contract_sha256": execution_sha256,
        "canonical_bytes": execution_canonical.len(),
        "roundtrip_equal": true,
        "filtrations": ["F0", "F1", "F2", "F3a", "F3b", "F4"],
        "execution_authorized": false,
    });
    let output_dir = study.join("artifacts/preimplementation");
    fs::create_dir_all(&output_dir)?;
    fs::write(
        output_dir.join("REACH03-RUNTIME-CONTRACT-ROUNDTRIP.json"),
        serde_json::to_vec_pretty(&output)?,
    )?;
    fs::write(
        output_dir.join("REACH03-EXECUTION-CONTRACT-ROUNDTRIP.json"),
        serde_json::to_vec_pretty(&execution_output)?,
    )?;
    println!("{}", serde_json::to_string(&output)?);
    Ok(())
}

fn usage() -> ! {
    eprintln!("usage: fly-reach-03-executor --contract-roundtrip STUDY_ROOT");
    eprintln!("       fly-reach-03-executor --collector-fixture STUDY_ROOT LINEAGE_ROOT");
    eprintln!("       fly-reach-03-executor --f4-audit-fixture STUDY_ROOT LINEAGE_ROOT");
    eprintln!("       fly-reach-03-executor --qualification-collect STUDY_ROOT LINEAGE_ROOT");
    eprintln!("       fly-reach-03-executor --qualification-f4-audit STUDY_ROOT LINEAGE_ROOT");
    eprintln!("       fly-reach-03-executor --qualification-f4-features STUDY_ROOT LINEAGE_ROOT");
    eprintln!(
        "       fly-reach-03-executor --qualification-f4-features-v2 STUDY_ROOT LINEAGE_ROOT"
    );
    eprintln!(
        "       fly-reach-03-executor --qualification-f4-features-v3 STUDY_ROOT LINEAGE_ROOT"
    );
    eprintln!("       fly-reach-03-executor --precision-01-collect STUDY_ROOT LINEAGE_ROOT");
    eprintln!("       fly-reach-03-executor --qualification-repair-v2 STUDY_ROOT LINEAGE_ROOT");
    eprintln!(
        "       fly-reach-03-executor --f4-symmetry-01-collect STUDY_ROOT LINEAGE_ROOT OUTPUT_ROOT"
    );
    eprintln!(
        "       fly-reach-03-executor --f4-symmetry-01-fixtures STUDY_ROOT LINEAGE_ROOT OUTPUT_ROOT"
    );
    std::process::exit(2)
}

fn main() -> Result<()> {
    let mut args = env::args_os();
    let _program = args.next();
    let mode = args.next().unwrap_or_default();
    let study = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
    match mode.to_string_lossy().as_ref() {
        "--contract-roundtrip" => run_contract_roundtrip(&study),
        "--collector-fixture" => {
            let lineage = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            run_contract_roundtrip(&study)?;
            collector::run_fixture(&study, &lineage)
        }
        "--f4-audit-fixture" => {
            let lineage = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            run_contract_roundtrip(&study)?;
            collector::audit_f4_fixture(&study, &lineage)
        }
        "--qualification-collect" => {
            let lineage = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            run_contract_roundtrip(&study)?;
            qualification::run(&study, &lineage)
        }
        "--qualification-f4-audit" => {
            let lineage = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            run_contract_roundtrip(&study)?;
            qualification::audit_f4(&study, &lineage)
        }
        "--qualification-f4-features" => {
            let lineage = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            run_contract_roundtrip(&study)?;
            qualification::collect_f4_features(&study, &lineage)
        }
        "--qualification-f4-features-v2" => {
            let lineage = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            run_contract_roundtrip(&study)?;
            qualification::collect_f4_features_v2(&study, &lineage)
        }
        "--qualification-f4-features-v3" => {
            let lineage = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            run_contract_roundtrip(&study)?;
            qualification::collect_f4_features_v3(&study, &lineage)
        }
        "--precision-01-collect" => {
            let lineage = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            run_contract_roundtrip(&study)?;
            let study_worker = study.clone();
            let lineage_worker = lineage.clone();
            std::thread::Builder::new()
                .name("f4-precision-01-replay".to_string())
                .stack_size(32 * 1024 * 1024)
                .spawn(move || precision::collect(&study_worker, &lineage_worker))?
                .join()
                .map_err(|_| anyhow::anyhow!("precision replay worker panicked"))?
        }
        "--qualification-repair-v2" => {
            let lineage = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            run_contract_roundtrip(&study)?;
            qualification::repair_v2_from_v1(&study, &lineage)
        }
        "--f4-symmetry-01-collect" => {
            let lineage = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            let output = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            symmetry::collect(&study, &lineage, &output)
        }
        "--f4-symmetry-01-fixtures" => {
            let lineage = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            let output = args.next().map(PathBuf::from).unwrap_or_else(|| usage());
            symmetry::fixtures(&study, &lineage, &output)
        }
        _ => bail!("unknown mode"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_object_order_is_stable() {
        let a: Value = serde_json::from_str(r#"{"z":1,"a":{"y":2,"b":3}}"#).unwrap();
        let b: Value = serde_json::from_str(r#"{"a":{"b":3,"y":2},"z":1}"#).unwrap();
        assert_eq!(canonical_json(&a).unwrap(), canonical_json(&b).unwrap());
    }

    #[test]
    fn expected_hash_is_a_sha256_string() {
        assert_eq!(EXPECTED_CONTRACT_SHA256.len(), 64);
        assert!(
            EXPECTED_CONTRACT_SHA256
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit())
        );
    }
}
