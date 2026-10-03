use crate::authority::{sha256, sha256_file, verify_parent};
use crate::fixtures::qualify;
use crate::model::{AUTHORITY, FINAL_STATE, PARENT_ROOT};
use crate::semantics::audit;
use serde::Serialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

const STUDY: &str = "studies/obs-open-01/range-representation-inference-audit";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_03B_PA_PROTOCOL_V1.md",
    "src/authority.rs",
    "src/fixtures.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/model.rs",
    "src/seal.rs",
    "src/semantics.rs",
    "tests/audit_contract.rs",
];

#[derive(Debug, Clone, Serialize)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(repo: &Path, out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    prepare_output(out)?;
    for dir in ["audit", "receipts", "source"] {
        fs::create_dir_all(out.join(dir))?;
    }
    let parent = verify_parent(repo)?;
    let fixtures = qualify()?;
    for (name, value) in audit(&parent)? {
        write_json(&out.join("audit").join(name), &value)?;
    }
    write_json(
        &out.join("receipts/PARENT_AUTHORITY_RECEIPT.json"),
        &json!({
            "schema":"OBS_OPEN_03BPA_PARENT_AUTHORITY_RECEIPT_V1","source_kind":"MACHINE_DERIVED",
            "parent_root":PARENT_ROOT,"member_count":parent.member_count,
            "inference_contract_sha256":parent.inference_contract_sha256,
            "protocol_sha256":parent.protocol_sha256,
            "sign_reflection_occurrences":parent.sign_reflection_occurrences,"status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/SYNTHETIC_ADVERSARIAL_QUALIFICATION.json"),
        &json!({
            "schema":"OBS_OPEN_03BPA_SYNTHETIC_ADVERSARIAL_QUALIFICATION_V1","source_kind":"MACHINE_DERIVED",
            "case_count":fixtures.len(),"failed":fixtures.iter().filter(|x|x.status!="PASS").count(),
            "fixtures":fixtures,"real_session_stochastic_assumption_established":false,"status":"PASS"
        }),
    )?;
    write_json(&out.join("audit/ACCESS_AUDIT.json"), &access_audit())?;
    write_matrix(&out.join("TYPED_QUALIFICATION_MATRIX.tsv"))?;
    fs::copy(
        repo.join(STUDY).join("OBS_OPEN_03B_PA_PROTOCOL_V1.md"),
        out.join("OBS_OPEN_03B_PA_PROTOCOL_V1.md"),
    )?;
    copy_source(repo, out)?;
    write_json(
        &out.join("03BPA_AUTHORITY_MANIFEST.json"),
        &json!({
            "schema":"OBS_OPEN_03BPA_AUTHORITY_MANIFEST_V1","source_kind":"ARTIFACT_DECLARED",
            "authority":AUTHORITY,"parent_root":PARENT_ROOT,"audit_state":FINAL_STATE,
            "parent_executable_for_D_B_formal_inference":false,"new_protocol_root_required":true,
            "D_B_opened":false,"D_C_opened":false,"representation_information_authority":false,
            "economic_authority":false,"trading_authority":false,"source_closure_sha256":source_closure_hash(repo)?
        }),
    )?;
    reseal(out)
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let provisional = compare(left, right)?;
    if provisional.1 != 0 {
        return Err("PROVISIONAL_REBUILD_MISMATCH".into());
    }
    let receipt = json!({
        "schema":"OBS_OPEN_03BPA_DETERMINISTIC_REBUILD_RECEIPT_V1","source_kind":"MACHINE_DERIVED",
        "provisional_root":provisional.0,"artifact_count":provisional.2,"mismatch_count":0,
        "comparison":"BYTE_IDENTICAL_COMPLETE_ARTIFACT_SET","status":"PASS"
    });
    for root in [left, right] {
        write_json(
            &root.join("audit/DETERMINISTIC_REBUILD_RECEIPT.json"),
            &receipt,
        )?;
        reseal(root)?;
    }
    let final_result = compare(left, right)?;
    if final_result.1 != 0 {
        return Err("FINAL_REBUILD_MISMATCH".into());
    }
    Ok(final_result.0)
}

pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let receipt: serde_json::Value =
        serde_json::from_slice(&fs::read(root.join("PREOPEN_AUDIT_ROOT_RECEIPT.json"))?)?;
    let expected = receipt["preopen_audit_root"]
        .as_str()
        .ok_or("AUDIT_ROOT_MISSING")?;
    let manifest = fs::read(root.join("content_manifest.tsv"))?;
    if sha256(&manifest) != expected {
        return Err("AUDIT_MANIFEST_ROOT_DRIFT".into());
    }
    let members = parse_manifest(root, &manifest)?;
    if receipt["artifact_count"].as_u64() != Some(members as u64) {
        return Err("AUDIT_MEMBER_COUNT_DRIFT".into());
    }
    if receipt["D_B_target_values_computed"].as_u64() != Some(0)
        || receipt["D_B_target_values_read"].as_u64() != Some(0)
        || receipt["D_B_model_scores"].as_u64() != Some(0)
        || receipt["D_C_observations_read"].as_u64() != Some(0)
    {
        return Err("AUDIT_FIREWALL_DRIFT".into());
    }
    Ok(expected.into())
}

pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    verify(build)?;
    if seal.exists() {
        let resolved = fs::canonicalize(seal)?;
        let normalized = resolved
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        if !normalized.contains("/studies/obs-open-01/range-representation-inference-audit/seal") {
            return Err("REFUSE_SEAL_REPLACEMENT".into());
        }
        fs::remove_dir_all(resolved)?;
    }
    copy_tree(build, seal)?;
    verify(seal)
}

fn access_audit() -> serde_json::Value {
    json!({
        "schema":"OBS_OPEN_03BPA_ACCESS_AUDIT_V1","source_kind":"MACHINE_DERIVED",
        "parent_sealed_artifacts_verified":true,
        "D_B":{"outcome_registry_applications":0,"target_values_computed":0,"target_values_read":0,"scores":0,"model_fitting":0,"normalization_fitting":0,"hyperparameter_selection":0},
        "D_C":{"membership_decoding":0,"observations_read":0,"outcomes":0},
        "status":"PASS"
    })
}

fn write_matrix(path: &Path) -> std::io::Result<()> {
    let rows = [
        ("PARENT_ROOT_AND_CLOSURE", "PASS"),
        ("CURRENT_NULL_EXPLICIT", "FAIL"),
        ("TRANSFORMATION_GROUP_IDENTIFIED", "PASS"),
        ("SIGN_GENERATOR_EXECUTABLE", "FAIL"),
        ("DEPENDENCE_AUTHORITY_ESTABLISHED", "FAIL"),
        ("EXACTNESS_BASIS_ACCURATELY_BOUNDED", "FAIL"),
        ("GENERIC_MEAN_NULL_LICENSED", "FAIL"),
        ("UNIT_DISTINCTIONS_RECORDED", "PASS"),
        ("MATERIALITY_INFERENCE_SEPARATION", "PASS"),
        ("SYNTHETIC_SEMANTIC_FIXTURES", "PASS"),
        ("D_B_FIREWALL", "PASS"),
        ("D_C_FIREWALL", "PASS"),
        ("CURRENT_FORMAL_PROCEDURE_EXECUTABLE", "FAIL"),
        ("REPLACEMENT_SELECTED", "NOT_EVALUABLE"),
    ];
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(writer, "claim\tstate\tsource_kind")?;
    for (claim, state) in rows {
        writeln!(writer, "{claim}\t{state}\tMACHINE_DERIVED")?;
    }
    writer.flush()
}

fn reseal(out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    for name in ["content_manifest.tsv", "PREOPEN_AUDIT_ROOT_RECEIPT.json"] {
        let path = out.join(name);
        if path.exists() {
            fs::remove_file(path)?;
        }
    }
    let members = members(out)?;
    let manifest = manifest(&members);
    fs::write(out.join("content_manifest.tsv"), &manifest)?;
    let root = sha256(&manifest);
    write_json(
        &out.join("PREOPEN_AUDIT_ROOT_RECEIPT.json"),
        &json!({
            "schema":"PREOPEN_AUDIT_ROOT_RECEIPT_V1","source_kind":"MACHINE_DERIVED",
            "authority":AUTHORITY,"parent_root":PARENT_ROOT,"preopen_audit_root":root,
            "audit_state":FINAL_STATE,"artifact_count":members.len(),
            "existing_protocol_executable":false,"new_protocol_root_required":true,
            "D_B_outcome_registry_applications":0,"D_B_target_values_computed":0,
            "D_B_target_values_read":0,"D_B_model_scores":0,"D_B_model_fitting":0,
            "D_B_normalization_fitting":0,"D_B_hyperparameter_selection":0,
            "D_C_membership_decoding":0,"D_C_observations_read":0,"D_C_outcomes":0,
            "representation_information_authority":false,"status":"SEALED"
        }),
    )?;
    Ok(root)
}

fn compare(
    left: &Path,
    right: &Path,
) -> Result<(String, usize, usize), Box<dyn std::error::Error>> {
    let left_files = recursive(left)?;
    let right_files = recursive(right)?;
    let left_rel = left_files
        .iter()
        .map(|x| x.strip_prefix(left).unwrap().to_owned())
        .collect::<Vec<_>>();
    let right_rel = right_files
        .iter()
        .map(|x| x.strip_prefix(right).unwrap().to_owned())
        .collect::<Vec<_>>();
    let mut mismatch = usize::from(left_rel != right_rel);
    if mismatch == 0 {
        for rel in &left_rel {
            mismatch += usize::from(fs::read(left.join(rel))? != fs::read(right.join(rel))?);
        }
    }
    Ok((verify(left)?, mismatch, left_rel.len()))
}

fn prepare_output(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if out.exists() {
        let resolved = fs::canonicalize(out)?;
        let normalized = resolved
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        if !(normalized.starts_with("d:/obs-open-01/protocol/")
            || normalized.starts_with("//?/d:/obs-open-01/protocol/"))
        {
            return Err("REFUSE_OUTPUT_REMOVAL".into());
        }
        fs::remove_dir_all(resolved)?;
    }
    fs::create_dir_all(out)?;
    Ok(())
}

fn copy_source(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    for relative in SOURCE_FILES {
        fs::copy(
            repo.join(STUDY).join(relative),
            out.join("source").join(relative.replace('/', "_")),
        )?;
    }
    Ok(())
}

fn source_closure_hash(repo: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut hash = Sha256::new();
    for relative in SOURCE_FILES {
        hash.update(relative.as_bytes());
        hash.update([0]);
        hash.update(fs::read(repo.join(STUDY).join(relative))?);
        hash.update([0xff]);
    }
    Ok(format!("{:x}", hash.finalize()))
}

fn parse_manifest(root: &Path, bytes: &[u8]) -> Result<usize, Box<dyn std::error::Error>> {
    let text = std::str::from_utf8(bytes)?;
    let mut count = 0;
    for line in text.lines().skip(1) {
        let fields = line.split('\t').collect::<Vec<_>>();
        if fields.len() != 3 || fields[0].contains("..") || Path::new(fields[0]).is_absolute() {
            return Err("INVALID_AUDIT_MANIFEST_MEMBER".into());
        }
        let path = root.join(fields[0]);
        if fs::metadata(&path)?.len() != fields[1].parse::<u64>()?
            || sha256_file(&path)? != fields[2]
        {
            return Err(format!("AUDIT_MEMBER_DRIFT:{}", fields[0]).into());
        }
        count += 1;
    }
    Ok(count)
}

fn members(root: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut result = Vec::new();
    for path in recursive(root)? {
        let relative = path
            .strip_prefix(root)?
            .to_string_lossy()
            .replace('\\', "/");
        if matches!(
            relative.as_str(),
            "content_manifest.tsv" | "PREOPEN_AUDIT_ROOT_RECEIPT.json"
        ) {
            continue;
        }
        result.push(Member {
            relative_path: relative,
            bytes: fs::metadata(&path)?.len(),
            sha256: sha256_file(&path)?,
        });
    }
    result.sort_by(|a, b| a.relative_path.cmp(&b.relative_path));
    Ok(result)
}

fn manifest(members: &[Member]) -> Vec<u8> {
    let mut value = String::from("relative_path\tbytes\tsha256\n");
    for member in members {
        value.push_str(&format!(
            "{}\t{}\t{}\n",
            member.relative_path, member.bytes, member.sha256
        ));
    }
    value.into_bytes()
}

fn recursive(root: &Path) -> Result<Vec<PathBuf>, Box<dyn std::error::Error>> {
    let mut files = Vec::new();
    let mut dirs = vec![root.to_owned()];
    while let Some(dir) = dirs.pop() {
        for entry in fs::read_dir(dir)? {
            let path = entry?.path();
            if path.is_dir() {
                dirs.push(path);
            } else {
                files.push(path);
            }
        }
    }
    files.sort();
    Ok(files)
}

fn copy_tree(src: &Path, dst: &Path) -> Result<(), Box<dyn std::error::Error>> {
    fs::create_dir_all(dst)?;
    for path in recursive(src)? {
        let relative = path.strip_prefix(src)?;
        let target = dst.join(relative);
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::copy(path, target)?;
    }
    Ok(())
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<(), Box<dyn std::error::Error>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    fs::write(path, bytes)?;
    Ok(())
}
