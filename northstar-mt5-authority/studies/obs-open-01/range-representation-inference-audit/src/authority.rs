use crate::model::{PARENT_AUTHORITY, PARENT_ROOT, ParentEvidence};
use memchr::memmem;
use memmap2::Mmap;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::path::{Path, PathBuf};

const PARENT: &str = "studies/obs-open-01/range-representation-tournament-protocol/seal";

pub fn verify_parent(repo: &Path) -> Result<ParentEvidence, Box<dyn std::error::Error>> {
    let root = repo.join(PARENT);
    let receipt: Value = read_json(&root.join("03BP_ROOT_RECEIPT.json"))?;
    if receipt["obs_open_03bp_root"].as_str() != Some(PARENT_ROOT)
        || receipt["authority"].as_str() != Some(PARENT_AUTHORITY)
        || receipt["D_B_outcome_registry_applications"].as_u64() != Some(0)
        || receipt["D_B_target_values_computed"].as_u64() != Some(0)
        || receipt["D_B_target_values_read"].as_u64() != Some(0)
        || receipt["D_B_model_scores"].as_u64() != Some(0)
        || receipt["D_C_observations_read"].as_u64() != Some(0)
    {
        return Err("PARENT_ROOT_AUTHORITY_OR_FIREWALL_DRIFT".into());
    }
    let manifest_path = root.join("content_manifest.tsv");
    let manifest = map(&manifest_path)?;
    if sha256(&manifest) != PARENT_ROOT {
        return Err("PARENT_MANIFEST_ROOT_DRIFT".into());
    }
    let member_count = verify_manifest(&root, &manifest)?;
    if receipt["artifact_count"].as_u64() != Some(member_count as u64) {
        return Err("PARENT_ARTIFACT_COUNT_DRIFT".into());
    }

    let inference_path = root.join("contracts/INFERENCE_CONTRACT_V1.json");
    let protocol_path = root.join("03BP_PROTOCOL_V1.md");
    let inference = map(&inference_path)?;
    let protocol = map(&protocol_path)?;
    let inference_contract: Value = serde_json::from_slice(&inference)?;
    validate_frozen_contract(&inference_contract)?;

    let searched = [
        ("contracts/INFERENCE_CONTRACT_V1.json", &inference[..]),
        ("03BP_PROTOCOL_V1.md", &protocol[..]),
    ];
    Ok(ParentEvidence {
        member_count,
        inference_contract_sha256: sha256(&inference),
        protocol_sha256: sha256(&protocol),
        exact_word_occurrences: search_lines(&searched, "exact"),
        sign_reflection_occurrences: search_lines(&searched, "sign-reflection"),
        inference_contract,
    })
}

fn validate_frozen_contract(v: &Value) -> Result<(), Box<dyn std::error::Error>> {
    let checks = [
        (
            v["schema"].as_str() == Some("PAIRED_SESSION_SIGN_REFLECTION_V1"),
            "SCHEMA",
        ),
        (
            v["alternative"].as_str() == Some("mean paired Brier improvement > 0"),
            "ALTERNATIVE",
        ),
        (
            v["randomizations"].as_u64() == Some(9_999),
            "RANDOMIZATIONS",
        ),
        (v["seed"].as_u64() == Some(20_260_814), "SEED"),
        (v["p_min"].as_f64() == Some(0.0001), "P_MIN"),
    ];
    for (ok, field) in checks {
        if !ok {
            return Err(format!("PARENT_INFERENCE_CONTRACT_DRIFT:{field}").into());
        }
    }
    Ok(())
}

fn search_lines(files: &[(&str, &[u8])], needle: &str) -> Vec<String> {
    let needle_lower = needle.as_bytes();
    let mut out = Vec::new();
    for (name, bytes) in files {
        let lower: Vec<u8> = bytes.iter().map(u8::to_ascii_lowercase).collect();
        if memmem::find(&lower, needle_lower).is_none() {
            continue;
        }
        for (index, line) in String::from_utf8_lossy(bytes).lines().enumerate() {
            let lower_line = line.to_ascii_lowercase();
            let found = if needle
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
            {
                lower_line
                    .split(|ch: char| !ch.is_ascii_alphanumeric() && ch != '_')
                    .any(|word| word == needle)
            } else {
                lower_line.contains(needle)
            };
            if found {
                out.push(format!("{}:{}:{}", name, index + 1, line.trim()));
            }
        }
    }
    out
}

fn verify_manifest(root: &Path, bytes: &[u8]) -> Result<usize, Box<dyn std::error::Error>> {
    let text = std::str::from_utf8(bytes)?;
    let mut count = 0;
    for line in text.lines().skip(1) {
        let mut fields = line.split('\t');
        let relative = fields.next().ok_or("MANIFEST_PATH_MISSING")?;
        let size: u64 = fields.next().ok_or("MANIFEST_SIZE_MISSING")?.parse()?;
        let expected = fields.next().ok_or("MANIFEST_HASH_MISSING")?;
        if fields.next().is_some() || relative.contains("..") || Path::new(relative).is_absolute() {
            return Err("UNSAFE_OR_MALFORMED_PARENT_MEMBER".into());
        }
        let member = root.join(relative);
        if fs::metadata(&member)?.len() != size || sha256_file(&member)? != expected {
            return Err(format!("PARENT_MEMBER_DRIFT:{relative}").into());
        }
        count += 1;
    }
    Ok(count)
}

pub fn sha256_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let bytes = map(path)?;
    Ok(sha256(&bytes))
}

pub fn sha256(bytes: &[u8]) -> String {
    let mut hash = Sha256::new();
    hash.update(bytes);
    format!("{:x}", hash.finalize())
}

fn map(path: &Path) -> Result<Mmap, Box<dyn std::error::Error>> {
    Ok(unsafe { Mmap::map(&File::open(path)?) }?)
}

fn read_json(path: &Path) -> Result<Value, Box<dyn std::error::Error>> {
    Ok(serde_json::from_slice(&map(path)?)?)
}

pub fn parent_root(repo: &Path) -> PathBuf {
    repo.join(PARENT)
}
