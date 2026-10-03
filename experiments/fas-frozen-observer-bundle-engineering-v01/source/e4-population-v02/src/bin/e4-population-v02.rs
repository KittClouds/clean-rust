use std::collections::HashSet;
use std::env;
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use fas_frozen_capability_fabric_e4_population_v02::identity::{E1_ROOT_SHA256, sha256_hex};
use fas_frozen_capability_fabric_e4_population_v02::{
    PopulationPaths, prepare_population, verify_population_stage_authorization, write_population,
};
use serde::Deserialize;
use sha2::{Digest, Sha256};

const PROJECT_RELATIVE: &str = "experiments/fas-frozen-observer-bundle-engineering-v01";
const CONTRACT_RELATIVE: &str =
    "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v06-final.json";
const CONTRACT_SEAL_RELATIVE: &str =
    "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v06-seal.json";
const OUTPUT_ROOT: &str = r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-v01";
const CONTRACT_ID: &str = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06";
const SEAL_ID: &str = "FAS_E4_0_CONTRACT_V06_SEAL";
const CONTRACT_ARTIFACT_ID: &str = "E4_0_CONTRACT_V06_FINAL";
const EXPECTED_PREDECESSOR_ROOTS: [(&str, &str); 4] = [
    (
        "e0_v10_root_sha256",
        "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd",
    ),
    ("e1_v04_root_sha256", E1_ROOT_SHA256),
    (
        "e2_v07_root_sha256",
        "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a",
    ),
    (
        "e3_v02_bundle_root_sha256",
        "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1",
    ),
];

#[derive(Deserialize)]
struct SealManifest {
    schema: String,
    status: String,
    seal_id: String,
    stage: String,
    path_root_kind: String,
    contract_sha256: String,
    contract_seal_root_sha256: Option<String>,
    exact_predecessor_roots: serde_json::Value,
    entries: Vec<SealEntry>,
    entry_count: u64,
    root_sha256: String,
}

#[derive(Deserialize)]
struct SealEntry {
    artifact_id: String,
    path: String,
    bytes: u64,
    sha256: String,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("E4-0 population generation stopped before or during materialization: {error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), String> {
    let mut args = env::args_os().skip(1);
    let auth_path = args
        .next()
        .map(PathBuf::from)
        .ok_or("usage: e4-population-v02 <authorized-stage-receipt.json>")?;
    if args.next().is_some() {
        return Err("usage: e4-population-v02 <authorized-stage-receipt.json>".into());
    }

    let workspace = find_workspace_root(&env::current_dir().map_err(|e| e.to_string())?)?;
    let contract_path = workspace.join(CONTRACT_RELATIVE);
    let seal_path = workspace.join(CONTRACT_SEAL_RELATIVE);
    let contract_bytes = fs::read(&contract_path).map_err(|error| {
        format!(
            "read final E4-0 v06 contract {}: {error}",
            contract_path.display()
        )
    })?;
    let contract_sha256 = sha256_hex(&contract_bytes);
    verify_contract_id(&contract_bytes)?;

    let seal_bytes = fs::read(&seal_path).map_err(|error| {
        format!(
            "read final E4-0 contract seal {}: {error}",
            seal_path.display()
        )
    })?;
    let seal_manifest_sha256 = sha256_hex(&seal_bytes);
    let seal: SealManifest = serde_json::from_slice(&seal_bytes)
        .map_err(|error| format!("decode final E4-0 contract seal: {error}"))?;
    let contract_root = verify_contract_seal(&workspace, &seal, &contract_sha256)?;

    let expected_output_root = Path::new(OUTPUT_ROOT);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("system clock predates Unix epoch: {error}"))?
        .as_secs();
    let permit = verify_population_stage_authorization(
        &auth_path,
        &contract_sha256,
        &seal_manifest_sha256,
        &contract_root,
        expected_output_root,
        now,
    )?;

    // Complete all read-only population and freshness gates before creating the output root.
    let paths = PopulationPaths::workstation_defaults();
    let plan = prepare_population(&paths)?;
    let written = write_population(&plan, &permit)?;
    let receipt_path = written
        .output_root
        .join("receipts/population-generation-receipt-v01.json");
    let mut stdout = std::io::BufWriter::new(std::io::stdout().lock());
    writeln!(stdout, "status={}", written.receipt.status).map_err(|error| error.to_string())?;
    writeln!(stdout, "output_root={}", written.output_root.display())
        .map_err(|error| error.to_string())?;
    writeln!(stdout, "receipt={}", receipt_path.display()).map_err(|error| error.to_string())?;
    writeln!(
        stdout,
        "quartets={}",
        written.receipt.selected_whole_quartet_prefix
    )
    .map_err(|error| error.to_string())?;
    writeln!(
        stdout,
        "feature_rows={}",
        written.receipt.unique_feature_rows
    )
    .map_err(|error| error.to_string())?;
    stdout.flush().map_err(|error| error.to_string())?;
    Ok(())
}

fn find_workspace_root(start: &Path) -> Result<PathBuf, String> {
    for candidate in start.ancestors() {
        if candidate
            .join(PROJECT_RELATIVE)
            .join("contracts/e4-0-artifact-seal-schema-v01.json")
            .is_file()
            && candidate.join(".git").exists()
        {
            return candidate
                .canonicalize()
                .map_err(|error| format!("canonicalize workspace root: {error}"));
        }
    }
    Err("could not find clean-rust workspace root containing the E4 artifact-seal schema".into())
}

fn verify_contract_id(contract_bytes: &[u8]) -> Result<(), String> {
    let value: serde_json::Value = serde_json::from_slice(contract_bytes)
        .map_err(|error| format!("decode final E4-0 contract: {error}"))?;
    let found = value
        .get("contract_id")
        .and_then(serde_json::Value::as_str)
        .or_else(|| value.get("id").and_then(serde_json::Value::as_str));
    if found != Some(CONTRACT_ID) {
        return Err(format!(
            "expected final contract identity {CONTRACT_ID}, found {}",
            found.unwrap_or("<missing>")
        ));
    }
    Ok(())
}

fn verify_contract_seal(
    workspace: &Path,
    seal: &SealManifest,
    expected_contract_sha256: &str,
) -> Result<String, String> {
    if seal.schema != "FAS_E4_0_ARTIFACT_SEAL_V01"
        || seal.status != "SEALED"
        || seal.seal_id != SEAL_ID
        || seal.stage != "E4_0_CONTRACT"
        || seal.path_root_kind != "WORKSPACE_ROOT"
        || seal.contract_sha256 != expected_contract_sha256
        || seal.contract_seal_root_sha256.is_some()
        || seal.entry_count != seal.entries.len() as u64
        || seal.entries.is_empty()
    {
        return Err("contract seal manifest identity or required fields differ from v06".into());
    }
    verify_predecessor_roots(&seal.exact_predecessor_roots)?;

    let mut ids = HashSet::with_capacity(seal.entries.len());
    let mut paths = HashSet::with_capacity(seal.entries.len());
    let mut entries = seal.entries.iter().collect::<Vec<_>>();
    entries.sort_unstable_by(|left, right| {
        left.artifact_id
            .as_bytes()
            .cmp(right.artifact_id.as_bytes())
    });
    let mut root_input = Vec::with_capacity(entries.len() * 128);
    let mut contract_member_matches = false;
    for entry in &entries {
        if entry.artifact_id.is_empty()
            || !ids.insert(entry.artifact_id.as_str())
            || !paths.insert(entry.path.as_str())
            || !safe_relative_posix_path(&entry.path)
            || !is_lower_hex_digest(&entry.sha256)
        {
            return Err("contract seal has duplicate IDs/paths or an unsafe entry".into());
        }
        root_input.extend_from_slice(entry.artifact_id.as_bytes());
        root_input.push(b'\t');
        root_input.extend_from_slice(entry.path.as_bytes());
        root_input.push(b'\t');
        root_input.extend_from_slice(entry.bytes.to_string().as_bytes());
        root_input.push(b'\t');
        root_input.extend_from_slice(entry.sha256.as_bytes());
        root_input.push(b'\n');

        let path = workspace.join(entry.path.replace('/', std::path::MAIN_SEPARATOR_STR));
        let canonical = path
            .canonicalize()
            .map_err(|error| format!("resolve sealed contract member {}: {error}", entry.path))?;
        if !canonical.starts_with(workspace) || !canonical.is_file() {
            return Err(format!(
                "sealed contract member is outside workspace or not a file: {}",
                entry.path
            ));
        }
        let (sha256, bytes) = hash_file(&canonical)?;
        if bytes != entry.bytes || sha256 != entry.sha256 {
            return Err(format!(
                "sealed contract member bytes/hash mismatch: {}",
                entry.path
            ));
        }
        if entry.artifact_id == CONTRACT_ARTIFACT_ID
            && entry.path == CONTRACT_RELATIVE
            && entry.sha256 == expected_contract_sha256
        {
            contract_member_matches = true;
        }
    }
    let computed_root = sha256_hex(&root_input);
    if computed_root != seal.root_sha256 || !contract_member_matches {
        return Err("contract seal root or final-contract membership does not verify".into());
    }
    Ok(computed_root)
}

fn verify_predecessor_roots(value: &serde_json::Value) -> Result<(), String> {
    let object = value
        .as_object()
        .ok_or("contract seal predecessor-root object missing")?;
    if object.len() != EXPECTED_PREDECESSOR_ROOTS.len()
        || EXPECTED_PREDECESSOR_ROOTS.iter().any(|(key, expected)| {
            object.get(*key).and_then(serde_json::Value::as_str) != Some(*expected)
        })
    {
        return Err("contract seal predecessor roots differ from frozen E0/E1/E2/E3".into());
    }
    Ok(())
}

fn safe_relative_posix_path(path: &str) -> bool {
    !path.is_empty()
        && !path.starts_with('/')
        && !path.contains('\\')
        && !path.contains('\t')
        && !path.contains('\n')
        && Path::new(path)
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
}

fn is_lower_hex_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn hash_file(path: &Path) -> Result<(String, u64), String> {
    let mut file = File::open(path).map_err(|error| format!("open sealed member: {error}"))?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; 1 << 20];
    let mut bytes = 0_u64;
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|error| format!("read sealed member: {error}"))?;
        if read == 0 {
            break;
        }
        bytes += read as u64;
        hasher.update(&buffer[..read]);
    }
    let digest = hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    Ok((digest, bytes))
}

#[cfg(test)]
mod tests {
    use std::fs;

    use super::{
        CONTRACT_ARTIFACT_ID, CONTRACT_RELATIVE, EXPECTED_PREDECESSOR_ROOTS, PROJECT_RELATIVE,
        SEAL_ID, SealEntry, SealManifest, find_workspace_root, is_lower_hex_digest,
        safe_relative_posix_path, sha256_hex, verify_contract_seal,
    };

    #[test]
    fn seal_path_validation_rejects_unsafe_and_non_posix_paths() {
        for valid in [
            "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v06-final.json",
            "source/e4-population-v02/src/lib.rs",
        ] {
            assert!(safe_relative_posix_path(valid), "{valid}");
        }
        for invalid in [
            "",
            "/absolute/file",
            "..\\outside",
            "a/../b",
            "a\\b",
            "a\tb",
            "a\nb",
        ] {
            assert!(!safe_relative_posix_path(invalid), "{invalid:?}");
        }
    }

    #[test]
    fn seal_digest_syntax_is_exact_lowercase_sha256() {
        assert!(is_lower_hex_digest(&"a".repeat(64)));
        assert!(!is_lower_hex_digest(&"A".repeat(64)));
        assert!(!is_lower_hex_digest(&"0".repeat(63)));
    }

    #[test]
    fn workspace_discovery_returns_repository_root_from_project_and_repo_cwds() {
        let temp = std::env::temp_dir().join(format!("e4-workspace-root-{}", std::process::id()));
        let _ = fs::remove_dir_all(&temp);
        let project = temp.join(PROJECT_RELATIVE);
        fs::create_dir_all(project.join("contracts")).expect("create synthetic project marker");
        fs::write(temp.join(".git"), "gitdir: synthetic\n").expect("write repository marker");
        fs::write(
            project.join("contracts/e4-0-artifact-seal-schema-v01.json"),
            b"{}\n",
        )
        .expect("write E4 seal-schema marker");

        let expected = temp
            .canonicalize()
            .expect("canonicalize synthetic repository");
        assert_eq!(
            find_workspace_root(&project).expect("find from project cwd"),
            expected
        );
        assert_eq!(
            find_workspace_root(&temp).expect("find from repository cwd"),
            expected
        );

        fs::remove_dir_all(temp).expect("remove synthetic workspace");
    }

    #[test]
    fn contract_seal_accepts_repository_root_relative_contract_member() {
        let temp =
            std::env::temp_dir().join(format!("e4-contract-seal-path-{}", std::process::id()));
        let _ = fs::remove_dir_all(&temp);
        let contract_path = temp.join(CONTRACT_RELATIVE);
        fs::create_dir_all(contract_path.parent().expect("contract parent"))
            .expect("create synthetic contract path");
        let contract_bytes = b"synthetic sealed E4-0 contract\n";
        fs::write(&contract_path, contract_bytes).expect("write synthetic contract");
        let contract_sha = sha256_hex(contract_bytes);
        let entry = SealEntry {
            artifact_id: CONTRACT_ARTIFACT_ID.to_owned(),
            path: CONTRACT_RELATIVE.to_owned(),
            bytes: contract_bytes.len() as u64,
            sha256: contract_sha.clone(),
        };
        let mut root_line = Vec::new();
        root_line.extend_from_slice(entry.artifact_id.as_bytes());
        root_line.push(b'\t');
        root_line.extend_from_slice(entry.path.as_bytes());
        root_line.push(b'\t');
        root_line.extend_from_slice(entry.bytes.to_string().as_bytes());
        root_line.push(b'\t');
        root_line.extend_from_slice(entry.sha256.as_bytes());
        root_line.push(b'\n');
        let root_sha = sha256_hex(&root_line);
        let predecessor_roots = serde_json::json!({
            "e0_v10_root_sha256": EXPECTED_PREDECESSOR_ROOTS[0].1,
            "e1_v04_root_sha256": EXPECTED_PREDECESSOR_ROOTS[1].1,
            "e2_v07_root_sha256": EXPECTED_PREDECESSOR_ROOTS[2].1,
            "e3_v02_bundle_root_sha256": EXPECTED_PREDECESSOR_ROOTS[3].1,
        });
        let manifest = SealManifest {
            schema: "FAS_E4_0_ARTIFACT_SEAL_V01".to_owned(),
            status: "SEALED".to_owned(),
            seal_id: SEAL_ID.to_owned(),
            stage: "E4_0_CONTRACT".to_owned(),
            path_root_kind: "WORKSPACE_ROOT".to_owned(),
            contract_sha256: contract_sha.clone(),
            contract_seal_root_sha256: None,
            exact_predecessor_roots: predecessor_roots,
            entries: vec![entry],
            entry_count: 1,
            root_sha256: root_sha.clone(),
        };
        let workspace = temp
            .canonicalize()
            .expect("canonicalize synthetic repository");
        assert_eq!(
            verify_contract_seal(&workspace, &manifest, &contract_sha)
                .expect("verify workspace-root seal"),
            root_sha,
        );

        fs::remove_dir_all(temp).expect("remove synthetic contract seal workspace");
    }
}
