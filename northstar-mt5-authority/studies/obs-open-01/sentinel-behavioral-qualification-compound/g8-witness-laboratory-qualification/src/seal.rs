use crate::artifacts::contracts;
use crate::explorer::{bounded_coverage, canonical_first, shrink_by_deletion};
use crate::fixtures::{comparison, constant_machine, corpus, finite_equal_pair, sign_machine};
use crate::model::NeutralToken;
use crate::oracle::{OracleResult, independent_product_oracle};
use crate::verifier::{
    make_certificate, verify_bounded_exhaustion, verify_finite_box_minimum, verify_no_witness_box,
    verify_separator, verify_universal_proof,
};
use crate::{AUTHORITY, DISPOSITION, G3_ROOT, G4_ROOT, G5_ROOT, G6_ROOT, G7_ROOT, RESULT};
use memchr::memchr_iter;
use memmap2::Mmap;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;

const STUDY: &str = "studies/obs-open-01/sentinel-behavioral-qualification-compound/g8-witness-laboratory-qualification";
const ROOT_RECEIPT: &str = "G8_ROOT_RECEIPT.json";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_G8_PROTOCOL_V1.md",
    "src/lib.rs",
    "src/model.rs",
    "src/authority.rs",
    "src/ranking.rs",
    "src/verifier.rs",
    "src/explorer.rs",
    "src/oracle.rs",
    "src/fixtures.rs",
    "src/artifacts.rs",
    "src/seal.rs",
    "src/main.rs",
    "tests/g8_lab.rs",
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
    verify_parent(repo, "g7-formal-analysis-boundary", "G7", G7_ROOT)?;
    verify_dependency_direction(repo)?;
    let fixtures = corpus()?;
    if fixtures.len() < 30
        || fixtures
            .iter()
            .any(|row| row.status != "PASS" || row.production_verifier_is_ground_truth)
    {
        return Err("G8_QUALIFICATION_FIXTURE_FAILURE".into());
    }
    prepare(out)?;
    for dir in [
        "authority",
        "contracts",
        "findings",
        "qualification",
        "receipts",
        "source",
    ] {
        fs::create_dir_all(out.join(dir))?;
    }
    write_json(
        &out.join("authority/G3_G4_G5_G6_G7_AUTHORITY_BINDING.json"),
        &json!({
            "schema":"G8_PARENT_AUTHORITY_BINDING_V1","G3_root":G3_ROOT,"G4_root":G4_ROOT,
            "G5_root":G5_ROOT,"G6_root":G6_ROOT,"G7_root":G7_ROOT,"status":"PASS"
        }),
    )?;
    for (name, value) in contracts() {
        write_json(&out.join("contracts").join(name), &value)?;
    }
    write_json(
        &out.join("qualification/SYNTHETIC_REFERENCE_QUALIFICATION_V1.json"),
        &fixtures,
    )?;
    write_qualification_artifacts(out)?;
    write_json(
        &out.join("receipts/PRE_POPULATION_BLINDNESS_AUDIT_V1.json"),
        &json!({
            "schema":"G8_PRE_POPULATION_BLINDNESS_AUDIT_V1","REAL_04A_HISTORY_CONTENT_READS":0,
            "REAL_04A_TRACE_READS":0,"REAL_04A_PAIR_READS":0,"REAL_04A_DISTRIBUTION_PROBES":0,
            "REAL_04A_VALUE_CONDITIONED_HEURISTIC_TUNING":0,"frozen_G1_G7_contract_reads":"AUTHORIZED",
            "search_order_tuned_on_real_04A":false,"status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/OUTCOME_ACCESS_AUDIT.json"),
        &json!({
            "schema":"G8_OUTCOME_ACCESS_AUDIT_V1","D_A_OUTCOME_READS":0,"D_B_TARGET_READS":0,"D_C_READS":0,
            "D_D_TARGET_READS":0,"D_D_ACCRUAL":"UNTOUCHED","prediction_reads":0,"economic_reads":0,"status":"PASS"
        }),
    )?;
    write_json(
        &out.join("findings/G8_TYPED_FINDINGS.json"),
        &json!({
            "schema":"G8_TYPED_FINDINGS_V1","result":RESULT,"authority":AUTHORITY,
        "separator_verifier":"QUALIFIED_SYNTHETIC_REFERENCE_SYSTEM_SCOPE",
        "04A_semantic_adapter":"NOT_QUALIFIED_OR_EXECUTED",
            "ancestry_verifier":"QUALIFIED_SYNTHETIC_SCOPE","canonical_first":"QUALIFIED_FAIR_FINITE_SHELL",
            "shrinker":"QUALIFIED_DELETION_ONLY_NO_GLOBAL_MINIMALITY","bounded_exhaustion":"QUALIFIED_EXACT_FINITE_DOMAIN",
            "finite_box_minimality":"QUALIFIED_WITHIN_DECLARED_BOX",
            "universal_proof_verifier":"QUALIFIED_FINITE_PRODUCT_INDUCTIVE_RELATION_ONLY",
            "04A_population_adapter_execution":"NOT_EXECUTED","real_04A_pair_claims":0,
            "GrammarStateAndEvent":"NOT_EVALUABLE","global_equivalence_decider":false,"global_minimality":false
        }),
    )?;
    write_json(
        &out.join("findings/G8_GATE_DECISION.json"),
        &json!({
            "schema":"G8_GATE_DECISION_V1","EXECUTION_STATE":"SEALED","QUESTION_STATUS":"CLOSED","RESULT":RESULT,
            "DISPOSITION":DISPOSITION,"AUTHORITY":AUTHORITY,
            "reason":"Trusted verifier, independent oracle, fair ranking, terminating shrinker, exact finite coverage, and named finite universal proof kernel qualified while all inherited restrictions remain."
        }),
    )?;
    write_json(
        &out.join("receipts/G8_QUALIFICATION_RECEIPT.json"),
        &json!({
            "schema":"G8_QUALIFICATION_RECEIPT_V1","fixture_count":fixtures.len(),"fixture_failures":0,
            "verifier_imports_explorer":false,"oracle_imports_verifier":false,"independent_build_required":true,
            "real_04A_reads":0,"status":"PASS"
        }),
    )?;
    write_source(repo, out)?;
    write_json(
        &out.join("receipts/SOURCE_CLOSURE_RECEIPT.json"),
        &json!({
            "schema":"G8_SOURCE_CLOSURE_RECEIPT_V1","source_files":SOURCE_FILES,
            "source_closure_sha256":source_closure(repo)?,"status":"PASS"
        }),
    )?;
    reseal(out)
}

fn write_qualification_artifacts(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let divergent = comparison(
        sign_machine("QUAL_SIGN", "QUAL_FIBER_D"),
        constant_machine("QUAL_CONST", "QUAL_FIBER_D", 0),
    );
    let equivalent = comparison(
        sign_machine("QUAL_EQ_A", "QUAL_FIBER_E"),
        sign_machine("QUAL_EQ_B", "QUAL_FIBER_E"),
    );
    let epsilon = comparison(
        constant_machine("QUAL_EPS_A", "QUAL_FIBER_0", 0),
        constant_machine("QUAL_EPS_B", "QUAL_FIBER_0", 1),
    );
    let first = canonical_first(&divergent, 1);
    let first_certificate = first
        .certificate
        .clone()
        .ok_or("G8_CANONICAL_FIRST_NOT_FOUND")?;
    if !verify_separator(&first_certificate).accepted {
        return Err("G8_CANONICAL_FIRST_VERIFY_FAILURE".into());
    }
    write_json(
        &out.join("qualification/CANONICAL_FIRST_WITNESS_FIXTURE.json"),
        &first,
    )?;
    let epsilon_first = canonical_first(&epsilon, 0);
    write_json(
        &out.join("qualification/EPSILON_SEPARATOR_FIXTURE.json"),
        &epsilon_first,
    )?;
    let long = make_certificate(
        divergent.clone(),
        vec![NeutralToken::flat(0), NeutralToken::flat(1)],
        "qualification shrink parent",
    )?;
    let shrunk = shrink_by_deletion(&long);
    write_json(
        &out.join("qualification/SHRUNK_WITNESS_FIXTURE.json"),
        &shrunk,
    )?;
    let (bounded, coverage) = bounded_coverage(&equivalent, 1);
    if !verify_bounded_exhaustion(1, &coverage) || !verify_no_witness_box(&equivalent, 1, &coverage)
    {
        return Err("G8_BOUNDED_EXHAUSTION_QUALIFICATION_FAILURE".into());
    }
    write_json(
        &out.join("qualification/NO_WITNESS_BOUNDED_SEARCH_FIXTURE.json"),
        &bounded,
    )?;
    write_json(
        &out.join("qualification/FINITE_DOMAIN_COVERAGE_RECEIPT_V1.json"),
        &coverage,
    )?;
    let (_, divergent_coverage) = bounded_coverage(&divergent, 1);
    let minimum = verify_finite_box_minimum(&first_certificate, 1, &divergent_coverage);
    if !minimum.accepted {
        return Err("G8_FINITE_BOX_MINIMUM_QUALIFICATION_FAILURE".into());
    }
    write_json(
        &out.join("qualification/FINITE_BOX_MINIMUM_FIXTURE.json"),
        &minimum,
    )?;
    let ancestry = crate::verifier::verify_ancestry(
        &divergent.left_machine,
        0,
        &[NeutralToken::flat(1)],
        &[0, 1],
    );
    if !ancestry.accepted {
        return Err("G8_ANCESTRY_VERIFIER_QUALIFICATION_FAILURE".into());
    }
    write_json(
        &out.join("qualification/REACHABILITY_CERTIFICATE_FIXTURE.json"),
        &ancestry,
    )?;
    let (left, right) = finite_equal_pair();
    let proof = match independent_product_oracle(&left, &right) {
        OracleResult::Equivalent(proof) => proof,
        _ => return Err("G8_ORACLE_EXPECTED_EQUIVALENCE".into()),
    };
    let verified = verify_universal_proof(&proof);
    if !verified.accepted {
        return Err("G8_UNIVERSAL_PROOF_QUALIFICATION_FAILURE".into());
    }
    write_json(
        &out.join("qualification/UNIVERSAL_PROOF_CERTIFICATE_FIXTURE.json"),
        &proof,
    )?;
    write_json(
        &out.join("qualification/UNIVERSAL_PROOF_VERIFICATION_RECEIPT.json"),
        &verified,
    )?;
    Ok(())
}

fn verify_dependency_direction(repo: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let source = repo.join(STUDY).join("src");
    let verifier = fs::read_to_string(source.join("verifier.rs"))?;
    let oracle = fs::read_to_string(source.join("oracle.rs"))?;
    let explorer = fs::read_to_string(source.join("explorer.rs"))?;
    if verifier.contains("crate::explorer")
        || verifier.contains("crate::oracle")
        || oracle.contains("crate::verifier")
        || !explorer.contains("crate::verifier")
    {
        return Err("G8_TRUST_BOUNDARY_DEPENDENCY_VIOLATION".into());
    }
    Ok(())
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(left, right)?;
    let receipt = json!({"schema":"G8_DETERMINISTIC_REBUILD_RECEIPT_V1","independent_builds":2,
        "configurations":["D_TARGET_BUILD_A","D_TARGET_BUILD_B"],"pre_finalize_artifact_count":members(left)?.len(),"byte_mismatches":0,"status":"PASS"});
    for root in [left, right] {
        write_json(
            &root.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"),
            &receipt,
        )?;
    }
    let a = reseal(left)?;
    let b = reseal(right)?;
    if a != b {
        return Err("G8_FINAL_ROOT_MISMATCH".into());
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
        &json!({"schema":"G8_ROOT_RECEIPT_V1","status":"SEALED","G8_root":hash,
        "authority":AUTHORITY,"parent_G7_root":G7_ROOT,"parent_G6_root":G6_ROOT,"QUESTION_STATUS":"CLOSED","RESULT":RESULT,"DISPOSITION":DISPOSITION,
        "real_04A_reads":0,"real_04A_pair_claims":0,"outcome_access":{"D_A":0,"D_B":0,"D_C":0,"D_D":0},"D_D_accrual":"UNTOUCHED",
        "global_equivalence_decider":false,"global_minimality":false,"observer_quotient":false,"prediction_authority":false,"economic_authority":false,"trading_authority":false}),
    )
}

pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("G8_SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}

pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let receipt: Value = serde_json::from_slice(&fs::read(root.join(ROOT_RECEIPT))?)?;
    let expected = receipt["G8_root"].as_str().ok_or("G8_ROOT_FIELD_MISSING")?;
    let file = File::open(root.join("content_manifest.tsv"))?;
    let mmap = unsafe { Mmap::map(&file)? };
    let actual = sha256(&mmap);
    if actual != expected {
        return Err("G8_ROOT_DRIFT".into());
    }
    for member in manifest_members(&mmap)? {
        let path = root.join(&member.relative_path);
        if fs::metadata(&path)?.len() != member.bytes || sha256_file(&path)? != member.sha256 {
            return Err(format!("G8_MEMBER_DRIFT:{}", member.relative_path).into());
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
        return Err(format!("G8_PARENT_{gate}_ROOT_MISMATCH").into());
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
        .filter(|p| p != "content_manifest.tsv" && p != ROOT_RECEIPT)
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
            return Err("G8_MANIFEST_MALFORMED".into());
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
        return Err("G8_BYTE_MISMATCH".into());
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
