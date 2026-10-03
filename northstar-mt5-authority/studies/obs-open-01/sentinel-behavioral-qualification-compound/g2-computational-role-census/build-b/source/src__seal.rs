use crate::census::{self, CensusProducts};
use crate::model::{DependencyGraph, EdgeKind, ElementRole, Surface};
use crate::{AUTHORITY, G1_ROOT, GATE_ID};
use memchr::memchr_iter;
use memmap2::Mmap;
use obs_open_meas02::sha256_file;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;

const STUDY: &str =
    "studies/obs-open-01/sentinel-behavioral-qualification-compound/g2-computational-role-census";
const G1_SEAL: &str =
    "studies/obs-open-01/sentinel-behavioral-qualification-compound/g1-semantic-kernel/seal";
const ROOT_RECEIPT: &str = "G2_ROOT_RECEIPT.json";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_G2_PROTOCOL_V1.md",
    "src/census.rs",
    "src/emissions.rs",
    "src/graph.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/model.rs",
    "src/registry.rs",
    "src/seal.rs",
    "tests/g2_contract.rs",
];

#[derive(Debug, Serialize, PartialEq, Eq)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(repo: &Path, out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    prepare(out)?;
    for dir in ["authority", "contracts", "receipts", "findings", "source"] {
        fs::create_dir_all(out.join(dir))?;
    }
    let parent = bind_parent(repo)?;
    let products = census::execute()?;
    write_json(&out.join("authority/G1_AUTHORITY_BINDING.json"), &parent)?;
    write_contracts(out, &products)?;
    write_receipts(out, &products)?;
    write_findings(out, &products)?;
    write_source(repo, out)?;
    write_json(
        &out.join("receipts/SOURCE_CLOSURE_RECEIPT.json"),
        &json!({
            "schema":"G2_SOURCE_CLOSURE_RECEIPT_V1",
            "source_file_count":SOURCE_FILES.len(),
            "source_closure_sha256":source_closure(repo)?,
            "status":"PASS"
        }),
    )?;
    reseal(out)
}

fn bind_parent(repo: &Path) -> Result<Value, Box<dyn std::error::Error>> {
    let root = repo.join(G1_SEAL);
    let verified = obs_open_04a_g1::seal::verify(&root)?;
    if verified != G1_ROOT {
        return Err("G1_ROOT_DRIFT".into());
    }
    let receipt: Value = serde_json::from_slice(&fs::read(root.join("G1_ROOT_RECEIPT.json"))?)?;
    if receipt["RESULT"] != "EXACT_SEMANTIC_KERNEL_EXTRACTED"
        || receipt["DISPOSITION"] != "ADVANCE"
        || receipt["outcome_access"]["D_B"] != 0
        || receipt["outcome_access"]["D_C"] != 0
        || receipt["outcome_access"]["D_D"] != 0
    {
        return Err("G1_AUTHORITY_NOT_ADMISSIBLE".into());
    }
    let consumed = [
        "G1_ROOT_RECEIPT.json",
        "contracts/KERNEL_STATE_SCHEMA_V1.json",
        "contracts/KERNEL_CONTEXT_SCHEMA_V1.json",
        "contracts/KERNEL_INPUT_CONTRACT_V1.json",
        "contracts/KERNEL_EMISSION_CONTRACT_V1.json",
        "contracts/KERNEL_TRANSITION_DEPENDENCY_LEDGER_V1.json",
        "contracts/FIELD_PROVENANCE_MAP.json",
        "source/src__kernel.rs",
        "source/src__model.rs",
    ];
    let members = consumed
        .iter()
        .map(|path| Ok(json!({"path":path,"sha256":sha256_file(&root.join(path))?})))
        .collect::<Result<Vec<_>, obs_open_meas02::BuildError>>()?;
    Ok(json!({
        "schema":"G2_G1_AUTHORITY_BINDING_V1",
        "parent_authority":receipt["authority"],
        "parent_root":verified,
        "parent_result":receipt["RESULT"],
        "parent_disposition":receipt["DISPOSITION"],
        "consumed_members":members,
        "D_A_replay_performed":false,
        "outcome_population_reads":{"D_B":0,"D_C":0,"D_D":0},
        "status":"PASS"
    }))
}

fn write_contracts(
    out: &Path,
    products: &CensusProducts,
) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("contracts/COMPUTATIONAL_ROLE_TAXONOMY_V1.json"),
        &json!({
            "schema":"G2_COMPUTATIONAL_ROLE_TAXONOMY_V1",
            "candidate_axes":["Q","R_GUARD","R_ARITHMETIC","C","O","P","EMISSION"],
            "partition_claimed":false,
            "orthogonal_characteristics":["USED_IN_GUARD","READ_FROM_PRIOR_STATE","COPIED_FROM_INPUT","COPIED_FROM_PRIOR_STATE","AFFINE_UPDATE","PIECEWISE_AFFINE_UPDATE","NONLINEAR_UPDATE","CONSTANT_UPDATE","IDENTITY_BEARING","TIME_BEARING","STATIC_CONTEXT","USED_IN_ARITHMETIC","DERIVED_EMISSION","AUTHORITATIVE_STATE_OUTPUT","VALIDATION_ONLY","PROVENANCE_ONLY"],
            "carry_statuses":["MUTABLE_CARRIED_STATE","IMMUTABLE_CONTEXT","CURRENT_INPUT_ONLY","DERIVED_WITHIN_STEP","EMISSION_ONLY","PROVENANCE_ONLY"],
            "multi_role_policy":"PRESERVE_AND_LABEL_MULTI_ROLE_COLLISION",
            "governing_law":"CLASSIFY_USE_NOT_IMPORTANCE",
            "status":"FROZEN"
        }),
    )?;
    write_json(
        &out.join("contracts/KERNEL_ELEMENT_ROLE_CENSUS_V1.json"),
        &products.elements,
    )?;
    write_surface_tables(out, &products.elements)?;
    write_json(
        &out.join("contracts/CAUSAL_CARRY_STATUS_LEDGER_V1.json"),
        &products.carry_ledger,
    )?;
    write_json(
        &out.join("contracts/TRANSITION_DEPENDENCY_GRAPH_V1.json"),
        &products.graph,
    )?;
    write_dot(
        &out.join("contracts/TRANSITION_DEPENDENCY_GRAPH_V1.dot"),
        &products.graph,
    )?;
    write_json(
        &out.join("contracts/MULTI_ROLE_COLLISION_REGISTRY_V1.json"),
        &products.collisions,
    )?;
    write_json(
        &out.join("contracts/GRAMMAR_ROLE_BOUNDARY_V1.json"),
        &json!({
            "schema":"G2_GRAMMAR_ROLE_BOUNDARY_V1",
            "GrammarStateAndEvent":"NOT_EVALUABLE",
            "reason":"G1 propagated absent qualified grammar stream",
            "role_classification_attempted":false,
            "authority_manufactured":false,
            "status":"PASS"
        }),
    )?;
    Ok(())
}

fn write_surface_tables(
    out: &Path,
    elements: &[ElementRole],
) -> Result<(), Box<dyn std::error::Error>> {
    for (surface, name) in [
        (Surface::KernelState, "STATE_ROLE_TABLE_V1.json"),
        (Surface::ImmutableContext, "CONTEXT_ROLE_TABLE_V1.json"),
        (Surface::CurrentInput, "INPUT_ROLE_TABLE_V1.json"),
        (Surface::Emission, "EMISSION_ROLE_TABLE_V1.json"),
    ] {
        let rows = elements
            .iter()
            .filter(|x| x.surface == surface)
            .collect::<Vec<_>>();
        write_json(&out.join("contracts").join(name), &rows)?;
    }
    Ok(())
}

fn write_receipts(out: &Path, products: &CensusProducts) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("receipts/ROLE_AND_GRAPH_QUALIFICATION.json"),
        &products.qualification,
    )?;
    write_json(
        &out.join("receipts/ACCESS_AUDIT.json"),
        &json!({
            "schema":"G2_ACCESS_AUDIT_V1",
            "G1_sealed_artifacts_read":true,
            "D_A_replayed":false,
            "D_A_market_observations_read":0,
            "D_B":{"targets":0,"scores":0,"fitting":0,"observations":0},
            "D_C":{"membership":0,"observations":0,"outcomes":0},
            "D_D":{"targets":0,"scores":0,"decisions":0,"accrual_modified":false},
            "future_target_joins":0,
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/G2_NONREDESIGN_RECEIPT.json"),
        &json!({
            "schema":"G2_NONREDESIGN_RECEIPT_V1",
            "state_removed":0,
            "state_merged":0,
            "transition_refactored":0,
            "observer_semantics_changed":false,
            "importance_judgments":0,
            "removability_judgments":0,
            "minimality_claims":0,
            "status":"PASS"
        }),
    )?;
    Ok(())
}

fn write_findings(out: &Path, products: &CensusProducts) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("findings/G2_TYPED_FINDINGS.json"),
        &products.typed_findings,
    )?;
    write_json(
        &out.join("findings/G2_GATE_DECISION.json"),
        &json!({
            "schema":"G2_GATE_DECISION_V1",
            "GATE_ID":GATE_ID,
            "EXECUTION_STATE":"SEALED",
            "QUESTION_STATUS":"CLOSED",
            "RESULT":"COMPUTATIONAL_ROLE_CENSUS_SEALED",
            "DISPOSITION":"ADVANCE",
            "role_census_elements":products.elements.len(),
            "graph_nodes":products.graph.nodes.len(),
            "graph_edges":products.graph.edges.len(),
            "multi_role_collisions":products.elements.iter().filter(|x| x.multi_role_collision).count(),
            "GrammarStateAndEvent":"NOT_EVALUABLE",
            "redesign_performed":false,
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("findings/G2_NONCLAIMS.json"),
        &json!({
            "schema":"G2_NONCLAIMS_V1",
            "not_earned":["importance","redundancy","removability","minimal state","necessary memory","sufficiency","reachability","behavioral equivalence","formal machine family","prediction","mechanism","economics","trading"],
            "multi_role_collision_is_not_refactor_authority":true,
            "dependency_graph_is_not_reachability_graph":true
        }),
    )
}

fn write_dot(path: &Path, graph: &DependencyGraph) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(writer, "digraph G2 {{")?;
    writeln!(writer, "  rankdir=LR;")?;
    for node in &graph.nodes {
        writeln!(
            writer,
            "  \"{}\" [label=\"{}\"] ;",
            node.node_id, node.node_id
        )?;
    }
    for edge in &graph.edges {
        let label = edge_label(edge.kind);
        writeln!(
            writer,
            "  \"{}\" -> \"{}\" [label=\"{}\"] ;",
            edge.source, edge.target, label
        )?;
    }
    writeln!(writer, "}}")?;
    writer.flush()?;
    Ok(())
}

fn edge_label(value: EdgeKind) -> &'static str {
    match value {
        EdgeKind::Reads => "READS",
        EdgeKind::Guards => "GUARDS",
        EdgeKind::Updates => "UPDATES",
        EdgeKind::Derives => "DERIVES",
        EdgeKind::Emits => "EMITS",
        EdgeKind::Copies => "COPIES",
        EdgeKind::Resets => "RESETS",
        EdgeKind::Increments => "INCREMENTS",
        EdgeKind::Compares => "COMPARES",
    }
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(left, right)?;
    let receipt = json!({
        "schema":"G2_DETERMINISTIC_REBUILD_RECEIPT_V1",
        "independent_builds":2,
        "configurations":["D_TARGET_BUILD_A","D_TARGET_BUILD_B"],
        "pre_finalize_artifact_count":members(left)?.len(),
        "byte_mismatches":0,
        "status":"PASS"
    });
    for root in [left, right] {
        write_json(
            &root.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"),
            &receipt,
        )?;
    }
    let left_root = reseal(left)?;
    let right_root = reseal(right)?;
    if left_root != right_root {
        return Err("G2_FINAL_ROOT_MISMATCH".into());
    }
    for root in [left, right] {
        write_root(root, &left_root)?;
    }
    compare(left, right)?;
    Ok(left_root)
}

fn write_root(root: &Path, hash: &str) -> Result<(), Box<dyn std::error::Error>> {
    let decision: Value =
        serde_json::from_slice(&fs::read(root.join("findings/G2_GATE_DECISION.json"))?)?;
    write_json(
        &root.join(ROOT_RECEIPT),
        &json!({
            "schema":"G2_ROOT_RECEIPT_V1",
            "status":"SEALED",
            "authority":AUTHORITY,
            "G2_root":hash,
            "gate_id":GATE_ID,
            "gate_version":"V1",
            "parent_G1_root":G1_ROOT,
            "QUESTION_STATUS":decision["QUESTION_STATUS"],
            "RESULT":decision["RESULT"],
            "DISPOSITION":decision["DISPOSITION"],
            "role_census_elements":decision["role_census_elements"],
            "graph_nodes":decision["graph_nodes"],
            "graph_edges":decision["graph_edges"],
            "multi_role_collisions":decision["multi_role_collisions"],
            "grammar_state_event":"NOT_EVALUABLE",
            "outcome_access":{"D_A_market_rows":0,"D_B":0,"D_C":0,"D_D":0},
            "redesign_authority":false,
            "minimality_authority":false,
            "reachability_authority":false,
            "prediction_authority":false,
            "mechanism_authority":false,
            "economic_authority":false,
            "trading_authority":false
        }),
    )
}

pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("G2_SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}

pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let receipt: Value = serde_json::from_slice(&fs::read(root.join(ROOT_RECEIPT))?)?;
    let expected = receipt["G2_root"].as_str().ok_or("G2_ROOT_FIELD_MISSING")?;
    let manifest = root.join("content_manifest.tsv");
    let file = File::open(&manifest)?;
    let mmap = unsafe { Mmap::map(&file)? };
    let actual = sha256(&mmap);
    if expected != actual {
        return Err("G2_ROOT_DRIFT".into());
    }
    for member in manifest_members(&mmap)? {
        let path = root.join(&member.relative_path);
        if fs::metadata(&path)?.len() != member.bytes || sha256_file(&path)? != member.sha256 {
            return Err(format!("G2_MEMBER_DRIFT:{}", member.relative_path).into());
        }
    }
    Ok(actual)
}

fn prepare(out: &Path) -> std::io::Result<()> {
    if out.exists() {
        fs::remove_dir_all(out)?;
    }
    fs::create_dir_all(out)
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
    let mut output = Vec::with_capacity(paths.len());
    for relative_path in paths {
        if relative_path == "content_manifest.tsv" || relative_path == ROOT_RECEIPT {
            continue;
        }
        let path = root.join(&relative_path);
        output.push(Member {
            relative_path,
            bytes: fs::metadata(&path)?.len(),
            sha256: sha256_file(&path)?,
        });
    }
    Ok(output)
}

fn manifest_members(bytes: &[u8]) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut output = Vec::new();
    let mut start = 0usize;
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
            return Err("G2_MANIFEST_MALFORMED".into());
        }
        output.push(Member {
            relative_path: fields[0].into(),
            bytes: fields[1].parse()?,
            sha256: fields[2].into(),
        });
    }
    Ok(output)
}

fn collect(base: &Path, dir: &Path, out: &mut Vec<String>) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            collect(base, &path, out)?;
        } else {
            out.push(
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
        return Err("G2_BYTE_MISMATCH".into());
    }
    Ok(())
}

fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), Box<dyn std::error::Error>> {
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
    let mut hash = Sha256::new();
    for relative in SOURCE_FILES {
        hash.update(relative.as_bytes());
        hash.update([0]);
        hash.update(fs::read(repo.join(STUDY).join(relative))?);
        hash.update([0]);
    }
    Ok(format!("{:x}", hash.finalize()))
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

fn sha256(bytes: &[u8]) -> String {
    let mut hash = Sha256::new();
    hash.update(bytes);
    format!("{:x}", hash.finalize())
}
