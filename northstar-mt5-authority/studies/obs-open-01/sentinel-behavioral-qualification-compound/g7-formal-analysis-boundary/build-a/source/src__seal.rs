use crate::analysis::{machinery_permissions, property_records};
use crate::artifacts::contracts;
use crate::fixtures::corpus;
use crate::{AUTHORITY, DISPOSITION, G3_ROOT, G4_ROOT, G5_ROOT, G6_ROOT, RESULT};
use hashbrown::HashSet;
use memchr::memchr_iter;
use memmap2::Mmap;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;

const STUDY: &str =
    "studies/obs-open-01/sentinel-behavioral-qualification-compound/g7-formal-analysis-boundary";
const ROOT_RECEIPT: &str = "G7_ROOT_RECEIPT.json";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_G7_PROTOCOL_V1.md",
    "src/lib.rs",
    "src/model.rs",
    "src/analysis.rs",
    "src/artifacts.rs",
    "src/fixtures.rs",
    "src/seal.rs",
    "src/main.rs",
    "tests/g7_boundary.rs",
];

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(repo: &Path, out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    verify_parent(repo, "g3-reachable-transition-semantics", "G3", G3_ROOT)?;
    verify_parent(repo, "g4-preservation-surface", "G4", G4_ROOT)?;
    verify_parent(repo, "g5-continuation-grammar", "G5", G5_ROOT)?;
    verify_parent(repo, "g6-behavioral-equivalence", "G6", G6_ROOT)?;
    verify_parent_restrictions(repo)?;
    qualify_analysis()?;
    prepare(out)?;
    for dir in ["authority", "contracts", "findings", "receipts", "source"] {
        fs::create_dir_all(out.join(dir))?;
    }

    write_json(
        &out.join("authority/G3_G4_G5_G6_AUTHORITY_BINDING.json"),
        &json!({
            "schema":"G7_PARENT_AUTHORITY_BINDING_V1",
            "G3":{"root":G3_ROOT,"authority":"OBS_OPEN_G3_SOUND_REACHABILITY_ENVELOPE_V1"},
            "G4":{"root":G4_ROOT,"authority":"OBS_OPEN_G4_CAUSAL_OBSERVER_PRESERVATION_SURFACE_WITH_BLIND_SPOTS_V1"},
            "G5":{"root":G5_ROOT,"authority":"OBS_OPEN_G5_SOUND_PARAMETRIC_ADMISSIBLE_CONTINUATION_ENVELOPE_V1"},
            "G6":{"root":G6_ROOT,"authority":"OBS_OPEN_G6_FIBERWISE_BEHAVIORAL_EQUIVALENCE_CONTRACT_WITH_RESTRICTIONS_V1"},
            "status":"PASS"
        }),
    )?;
    for (name, value) in contracts() {
        write_json(&out.join("contracts").join(name), &value)?;
    }
    write_json(
        &out.join("receipts/OUTCOME_ACCESS_AUDIT.json"),
        &json!({
            "schema":"G7_OUTCOME_ACCESS_AUDIT_V1",
            "D_A_OUTCOME_READS":0,"D_B_TARGET_READS":0,"D_C_READS":0,"D_D_TARGET_READS":0,
            "D_D_ACCRUAL":"UNTOUCHED","REAL_HISTORY_PAIRS_INSPECTED":0,"production_judges_built":0,
            "quotient_operations":0,"minimization_operations":0,"status":"PASS"
        }),
    )?;
    let properties = property_records();
    write_json(
        &out.join("findings/G7_TYPED_FINDINGS.json"),
        &json!({
            "schema":"G7_TYPED_FINDINGS_V1",
            "result":RESULT,"authority":AUTHORITY,
            "required_properties":properties.len(),
            "primary_metatheoretic_statuses":properties.iter().map(|row| json!({"property":row.property_id,"signature":row.problem_signature_id,"status":row.metatheoretic_status,"certification":row.certification_authority})).collect::<Vec<_>>(),
            "reachability":"UNKNOWN_WITH_EXACT_POSITIVE_ANCESTRY_CERTIFICATES",
            "invariant_preservation":"LANGUAGE_PARAMETERIZED_RESTRICTED_INDUCTIVENESS_ONLY",
            "behavioral_equivalence":"UNKNOWN_WITH_RESTRICTED_UNIVERSAL_PROOF_CERTIFICATION",
            "behavioral_non_equivalence":"RECOGNIZABLE_WITHIN_QUALIFIED_FIBER",
            "witness_existence":"RECOGNIZABLE_WITH_EXACT_CERTIFICATE_VERIFIER",
            "witness_minimality":"UNKNOWN_GLOBALLY_BOUNDED_FINITE_BOX_ONLY",
            "RA_Q_transfer":"NO_WHOLE_OBSERVER_THEOREM_BRIDGE_EARNED",
            "GrammarStateAndEvent":"NOT_EVALUABLE",
            "real_pair_claims":0
        }),
    )?;
    write_json(
        &out.join("findings/G7_NONCLAIMS.json"),
        &json!({
            "schema":"G7_NONCLAIMS_V1",
            "real_pair_equivalent":false,"real_pair_non_equivalent":false,"real_separator_exists":false,
            "minimal_separator_exists":false,"quotient_exists":false,"field_redundancy":false,
            "whole_observer_single_formalism":false,"bounded_unsat_implies_equivalence":false,
            "search_failure_implies_equivalence":false,"omega_trace":false,"liveness":false,
            "prediction":false,"economic":false,"trading":false
        }),
    )?;
    write_json(
        &out.join("findings/G7_GATE_DECISION.json"),
        &json!({
            "schema":"G7_GATE_DECISION_V1","EXECUTION_STATE":"SEALED","QUESTION_STATUS":"CLOSED",
            "RESULT":RESULT,"DISPOSITION":DISPOSITION,"AUTHORITY":AUTHORITY,
            "reason":"All six problem signatures are classified; inherited approximation, blind-spot, theorem-transfer, and lower-cone restrictions limit authorized machinery."
        }),
    )?;
    write_json(
        &out.join("receipts/G7_QUALIFICATION_RECEIPT.json"),
        &json!({
            "schema":"G7_QUALIFICATION_RECEIPT_V1",
            "required_property_count":6,"unique_problem_signature_count":6,
            "fixture_count":corpus().len(),"fixture_failures":0,
            "machinery_permission_records":machinery_permissions().len(),
            "real_history_pairs_inspected":0,"production_judges_built":0,"status":"PASS"
        }),
    )?;
    write_source(repo, out)?;
    write_json(
        &out.join("receipts/SOURCE_CLOSURE_RECEIPT.json"),
        &json!({
            "schema":"G7_SOURCE_CLOSURE_RECEIPT_V1","source_files":SOURCE_FILES,
            "source_closure_sha256":source_closure(repo)?,"status":"PASS"
        }),
    )?;
    reseal(out)
}

fn qualify_analysis() -> Result<(), Box<dyn std::error::Error>> {
    let properties = property_records();
    let ids = properties
        .iter()
        .map(|row| row.property_id)
        .collect::<HashSet<_>>();
    let signatures = properties
        .iter()
        .map(|row| row.problem_signature_id)
        .collect::<HashSet<_>>();
    if properties.len() != 6 || ids.len() != 6 || signatures.len() != 6 {
        return Err("G7_PROPERTY_SIGNATURE_FAILURE".into());
    }
    if properties.iter().any(|row| {
        row.semantic_target.is_empty()
            || row.promise_domain.is_empty()
            || row.input_encoding.is_empty()
    }) {
        return Err("G7_INCOMPLETE_PROPERTY_RECORD".into());
    }
    let fixtures = corpus();
    if fixtures.len() < 28
        || fixtures
            .iter()
            .any(|row| row.status != "PASS" || row.earns_metatheorem)
    {
        return Err("G7_FIXTURE_AUTHORITY_FAILURE".into());
    }
    let permission_ids = machinery_permissions()
        .iter()
        .map(|row| row.problem_signature_id)
        .collect::<HashSet<_>>();
    if permission_ids != signatures {
        return Err("G7_MACHINERY_PERMISSION_COVERAGE_FAILURE".into());
    }
    Ok(())
}

fn verify_parent_restrictions(repo: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let base = repo.join("studies/obs-open-01/sentinel-behavioral-qualification-compound");
    let g4: Value = serde_json::from_slice(&fs::read(
        base.join("g4-preservation-surface/seal/findings/G4_TYPED_FINDINGS.json"),
    )?)?;
    let blind_spot_preserved = g4["blind_spots"].as_array().is_some_and(|rows| {
        rows.iter()
            .any(|row| row.as_str() == Some("GrammarStateAndEvent"))
    });
    if !blind_spot_preserved {
        return Err("G7_G4_BLIND_SPOT_DRIFT".into());
    }
    let g6: Value = serde_json::from_slice(&fs::read(
        base.join("g6-behavioral-equivalence/seal/findings/G6_TYPED_FINDINGS.json"),
    )?)?;
    if g6["relation_scope"].as_str() != Some("FIBERWISE")
        || g6["omega_trace_authority"].as_str() != Some("NOT_EARNED")
    {
        return Err("G7_G6_SEMANTIC_SCOPE_DRIFT".into());
    }
    Ok(())
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(left, right)?;
    let receipt = json!({
        "schema":"G7_DETERMINISTIC_REBUILD_RECEIPT_V1","independent_builds":2,
        "configurations":["D_TARGET_BUILD_A","D_TARGET_BUILD_B"],
        "pre_finalize_artifact_count":members(left)?.len(),"byte_mismatches":0,"status":"PASS"
    });
    for root in [left, right] {
        write_json(
            &root.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"),
            &receipt,
        )?;
    }
    let a = reseal(left)?;
    let b = reseal(right)?;
    if a != b {
        return Err("G7_FINAL_ROOT_MISMATCH".into());
    }
    for root in [left, right] {
        write_root(root, &a)?;
    }
    compare(left, right)?;
    Ok(a)
}

fn write_root(root: &Path, hash: &str) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &root.join(ROOT_RECEIPT),
        &json!({
            "schema":"G7_ROOT_RECEIPT_V1","status":"SEALED","G7_root":hash,
            "authority":AUTHORITY,"parent_G3_root":G3_ROOT,"parent_G4_root":G4_ROOT,
            "parent_G5_root":G5_ROOT,"parent_G6_root":G6_ROOT,
            "QUESTION_STATUS":"CLOSED","RESULT":RESULT,"DISPOSITION":DISPOSITION,
            "required_properties":6,"production_judge_authority":false,"real_pair_search":0,
            "outcome_access":{"D_A":0,"D_B":0,"D_C":0,"D_D":0},"D_D_accrual":"UNTOUCHED",
            "quotient_authority":false,"prediction_authority":false,"economic_authority":false,"trading_authority":false
        }),
    )
}

pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("G7_SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}

pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let receipt: Value = serde_json::from_slice(&fs::read(root.join(ROOT_RECEIPT))?)?;
    let expected = receipt["G7_root"].as_str().ok_or("G7_ROOT_FIELD_MISSING")?;
    let file = File::open(root.join("content_manifest.tsv"))?;
    let mmap = unsafe { Mmap::map(&file)? };
    let actual = sha256(&mmap);
    if actual != expected {
        return Err("G7_ROOT_DRIFT".into());
    }
    for member in manifest_members(&mmap)? {
        let path = root.join(&member.relative_path);
        if fs::metadata(&path)?.len() != member.bytes || sha256_file(&path)? != member.sha256 {
            return Err(format!("G7_MEMBER_DRIFT:{}", member.relative_path).into());
        }
    }
    Ok(actual)
}

fn verify_parent(
    repo: &Path,
    dir: &str,
    gate: &str,
    expected: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    let path = repo
        .join("studies/obs-open-01/sentinel-behavioral-qualification-compound")
        .join(dir)
        .join("seal")
        .join(format!("{gate}_ROOT_RECEIPT.json"));
    let value: Value = serde_json::from_slice(&fs::read(path)?)?;
    if value[format!("{gate}_root")].as_str() != Some(expected)
        || value["status"].as_str() != Some("SEALED")
    {
        return Err(format!("G7_PARENT_{gate}_ROOT_MISMATCH").into());
    }
    Ok(())
}

fn prepare(path: &Path) -> std::io::Result<()> {
    if path.exists() {
        fs::remove_dir_all(path)?;
    }
    fs::create_dir_all(path)
}

fn reseal(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    for name in ["content_manifest.tsv", ROOT_RECEIPT] {
        let path = root.join(name);
        if path.exists() {
            fs::remove_file(path)?;
        }
    }
    let mut writer = BufWriter::new(File::create(root.join("content_manifest.tsv"))?);
    writeln!(writer, "relative_path\tbytes\tsha256")?;
    for member in members(root)? {
        writeln!(
            writer,
            "{}\t{}\t{}",
            member.relative_path, member.bytes, member.sha256
        )?;
    }
    writer.flush()?;
    Ok(sha256(&fs::read(root.join("content_manifest.tsv"))?))
}

fn members(root: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut paths = Vec::new();
    collect(root, root, &mut paths)?;
    paths.sort_unstable();
    paths
        .into_iter()
        .filter(|path| path != "content_manifest.tsv" && path != ROOT_RECEIPT)
        .map(|relative_path| {
            let path = root.join(&relative_path);
            Ok(Member {
                bytes: fs::metadata(&path)?.len(),
                sha256: sha256_file(&path)?,
                relative_path,
            })
        })
        .collect()
}

fn manifest_members(bytes: &[u8]) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut output = Vec::new();
    let mut start = 0;
    for (row, end) in memchr_iter(b'\n', bytes).enumerate() {
        let line = bytes[start..end]
            .strip_suffix(b"\r")
            .unwrap_or(&bytes[start..end]);
        start = end + 1;
        if row == 0 || line.is_empty() {
            continue;
        }
        let fields = std::str::from_utf8(line)?.split('\t').collect::<Vec<_>>();
        if fields.len() != 3 || fields[0].contains("..") || Path::new(fields[0]).is_absolute() {
            return Err("G7_MANIFEST_MALFORMED".into());
        }
        output.push(Member {
            relative_path: fields[0].into(),
            bytes: fields[1].parse()?,
            sha256: fields[2].into(),
        });
    }
    Ok(output)
}

fn collect(base: &Path, dir: &Path, output: &mut Vec<String>) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            collect(base, &path, output)?;
        } else {
            output.push(
                path.strip_prefix(base)
                    .expect("descendant")
                    .to_string_lossy()
                    .replace('\\', "/"),
            );
        }
    }
    Ok(())
}

fn compare(left: &Path, right: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if members(left)? != members(right)? {
        return Err("G7_BYTE_MISMATCH".into());
    }
    Ok(())
}

fn write_json<T: Serialize + ?Sized>(
    path: &Path,
    value: &T,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    fs::write(path, bytes)?;
    Ok(())
}

fn write_source(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    for relative in SOURCE_FILES {
        fs::copy(
            repo.join(STUDY).join(relative),
            out.join("source").join(relative.replace('/', "__")),
        )?;
    }
    Ok(())
}

fn source_closure(repo: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut hasher = Sha256::new();
    for relative in SOURCE_FILES {
        hasher.update(relative.as_bytes());
        hasher.update([0]);
        hasher.update(fs::read(repo.join(STUDY).join(relative))?);
        hasher.update([0]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn copy_tree(source: &Path, destination: &Path) -> std::io::Result<()> {
    fs::create_dir_all(destination)?;
    for entry in fs::read_dir(source)? {
        let path = entry?.path();
        let target = destination.join(path.file_name().expect("filename"));
        if path.is_dir() {
            copy_tree(&path, &target)?;
        } else {
            fs::copy(path, target)?;
        }
    }
    Ok(())
}

fn sha256_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file)? };
    Ok(sha256(&mmap))
}
fn sha256(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}
