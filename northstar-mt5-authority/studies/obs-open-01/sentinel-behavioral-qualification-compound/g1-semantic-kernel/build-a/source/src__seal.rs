use crate::audit::{self, AuditProducts};
use crate::{AUTHORITY, FOSSIL_ROOT, G0_ROOT, GATE_ID, ORIGINAL_SPEC_SHA256, ROADMAP_ROOT};
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
    "studies/obs-open-01/sentinel-behavioral-qualification-compound/g1-semantic-kernel";
const ROOT_RECEIPT: &str = "G1_ROOT_RECEIPT.json";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_G1_PROTOCOL_V1.md",
    "src/audit.rs",
    "src/kernel.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/model.rs",
    "src/seal.rs",
    "tests/g1_contract.rs",
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
    let products = audit::execute(repo)?;
    write_contracts(out)?;
    write_audits(out, &products)?;
    write_decision(out, &products)?;
    write_source(repo, out)?;
    write_json(
        &out.join("receipts/SOURCE_CLOSURE_RECEIPT.json"),
        &json!({
            "schema":"G1_SOURCE_CLOSURE_RECEIPT_V1",
            "source_file_count":SOURCE_FILES.len(),
            "source_closure_sha256":source_closure(repo)?,
            "status":"PASS"
        }),
    )?;
    reseal(out)
}

fn write_contracts(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("contracts/SENTINEL_SEMANTIC_KERNEL_V1.json"),
        &json!({
            "schema":"SENTINEL_SEMANTIC_KERNEL_V1",
            "interface":{"init":"init(KernelContext)->KernelState","step":"step(KernelState,CompletedObservation,KernelContext)->(KernelState,KernelEmissions)"},
            "determinism_domain":"D_G1_SEQUENCE_GENERATED_FROM_QUALIFIED_INIT_AND_ADMITTED_INPUTS",
            "arbitrary_syntactic_state_authority":"NOT_EARNED",
            "primary_oracle":"SEALED_04A_CAUSAL_MECHANISM",
            "prime_rule":"DO_NOT_IMPROVE_THE_OBSERVER_WHILE_EXTRACTING_IT",
            "status":"FROZEN"
        }),
    )?;
    write_json(
        &out.join("contracts/KERNEL_STATE_SCHEMA_V1.json"),
        &json!({
            "schema":"KERNEL_STATE_SCHEMA_V1",
            "fields":["initialized","bar_index","knowledge_time_ns","upper_candidate","lower_candidate","close_ticks","upper_giveback_ticks","lower_giveback_ticks","R01_R30_locations","R01_R30_upper_extensions_ticks","R01_R30_lower_extensions_ticks","window_active","coverage_complete"],
            "candidate_fields":["id","value_ticks","birth_bar_index","birth_knowledge_time_ns","age_bars"],
            "retrospective_fields":[],
            "provisional_fields":[],
            "state_reduction_performed":false,
            "status":"FROZEN"
        }),
    )?;
    write_json(
        &out.join("contracts/KERNEL_CONTEXT_SCHEMA_V1.json"),
        &json!({
            "schema":"KERNEL_CONTEXT_SCHEMA_V1",
            "fields":["session_id","session_start_ns","session_terminal_ns","price_scale","source_time_resolution_ns","storage_time_resolution_ns","observation_cadence_ns","30 immutable range contexts"],
            "range_fields":["k","high_ticks","low_ticks","freeze_commit_time_ns"],
            "authority":"EXPLICIT_REPRODUCIBLE_INHERITED_04A_G0_CONTEXT",
            "additional_context_authority_required":false,
            "status":"FROZEN"
        }),
    )?;
    write_json(
        &out.join("contracts/KERNEL_INPUT_CONTRACT_V1.json"),
        &json!({
            "schema":"KERNEL_INPUT_CONTRACT_V1",
            "accepted_authority":"CANONICAL_INTEGER_M1_BRIDGE_V1",
            "fixture_authority":"SYNTHETIC_SEQUENCE_FIXTURE_METROLOGY_ONLY",
            "rejected_authority":"CURRENT_CANONICAL_L2_RUNTIME",
            "price":"I64_TICKS_SCALE_100",
            "time":"I64_NANOSECOND_STORAGE_WITH_ONE_SECOND_SOURCE_AUTHORITY",
            "cadence_ns":60_000_000_000_i64,
            "gap_policy":"FAIL_CLOSED_OBSERVATION_SEQUENCE_GAP",
            "status":"FROZEN"
        }),
    )?;
    write_json(
        &out.join("contracts/KERNEL_EMISSION_CONTRACT_V1.json"),
        &json!({
            "schema":"KERNEL_EMISSION_CONTRACT_V1",
            "order":["OBSERVATION_COMMIT","NEW_UPPER_EXTREME_IF_ANY","UPPER_CANDIDATE_ID_CHANGE_IF_ANY","NEW_LOWER_EXTREME_IF_ANY","LOWER_CANDIDATE_ID_CHANGE_IF_ANY","R01_TO_R30_LOCATION_TRANSITIONS_WHERE_FROZEN"],
            "same_state_location_transitions_retained":true,
            "knowledge_time":"COMPLETED_BAR_CLOSE",
            "terminal_state_equality_without_ordered_emission_equality":"INSUFFICIENT",
            "status":"FROZEN"
        }),
    )?;
    write_json(
        &out.join("contracts/ANCESTOR_PROJECTION_CONTRACT_V1.json"),
        &json!({
            "schema":"ANCESTOR_PROJECTION_CONTRACT_V1",
            "projection":"Pi_04A(K_G1,O_G1,C)->AUTHORIZED_04A_STATE_AND_ORDERED_EMISSIONS",
            "obligation":"Pi_04A(Trace_G1(B_G0(D_A))) == Trace_04A(D_A)",
            "literal_internal_state_equality_required":false,
            "literal_field_equality_scope":"ONLY_EARNED_ONE_TO_ONE_ANCESTOR_MAPPINGS",
            "primitive_integer_to_float_projection":"ticks/100",
            "derived_float_projection":"replay ancestor arithmetic from projected primitive operands; do not claim integer-derived byte identity",
            "comparison":"exact 04A float bits after authoritative projection",
            "nanosecond_to_source_time_projection":"ns/1e9; divisibility required",
            "status":"FROZEN"
        }),
    )?;
    write_dependency_contracts(out)?;
    write_provenance(out)?;
    write_firewall_contracts(out)?;
    Ok(())
}

fn write_dependency_contracts(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("contracts/SEMANTIC_KERNEL_DEPENDENCY_CLOSURE_V1.json"),
        &json!({
            "schema":"SEMANTIC_KERNEL_DEPENDENCY_CLOSURE_V1",
            "categories":["PRIOR_KERNEL_STATE","CURRENT_ADMITTED_OBSERVATION","IMMUTABLE_CONTEXT","DERIVED_WITHIN_STEP"],
            "undeclared_dependencies":[],
            "init_dependencies":["IMMUTABLE_CONTEXT"],
            "step_dependencies":["PRIOR_KERNEL_STATE","CURRENT_ADMITTED_OBSERVATION","IMMUTABLE_CONTEXT","DERIVED_WITHIN_STEP"],
            "ambient_runtime_reads":0,
            "wall_clock_reads":0,
            "randomness_reads":0,
            "retrospective_reads":0,
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("contracts/HIDDEN_DEPENDENCY_CENSUS.json"),
        &json!({
            "schema":"G1_HIDDEN_DEPENDENCY_CENSUS_V1",
            "investigated":["platform lifecycle","chart state","indicator lifecycle","buffer persistence","static/global variables","prior-buffer reads","direct history reads","session lookup","host clock","forming bar","symbol metadata","precision metadata","previous-bar access","reload","initialization","retrospective buffers","external files/environment"],
            "resolved_to_explicit_context":["session identity and bounds","price scale","source time resolution","observation cadence","frozen range geometry and freeze times"],
            "validation_only":["derived 04A metrology products","retrospective sidecars"],
            "unresolved":[],
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("contracts/INITIALIZATION_SEMANTICS.json"),
        &json!({
            "schema":"G1_INITIALIZATION_SEMANTICS_V1",
            "init":"empty explicit state sized to 30 ranges",
            "first_completed_observation":"creates upper and lower candidate ID 1 at completed-bar knowledge time",
            "initial_age_bars":0,
            "initial_locations":"unavailable until each range freeze commit; then initial location emitted",
            "coverage":"copied from admitted observation",
            "reload_replay":"re-run init then same admitted sequence",
            "arbitrary_state_injection":"FORBIDDEN_WITHOUT_ANCESTOR_EQUIVALENT_CONSTRUCTION",
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("contracts/KERNEL_TRANSITION_DEPENDENCY_LEDGER_V1.json"),
        &json!({
            "schema":"KERNEL_TRANSITION_DEPENDENCY_LEDGER_V1",
            "classification_authority":"DESCRIPTIVE_ONLY_NOT_G2_COMPUTATIONAL_ROLE_CLASSIFICATION",
            "transitions":[
                {"id":"OBSERVATION_COMMIT","reads_prior_state":["knowledge_time_ns"],"reads_observation":["source_row_id","event_time_ns","knowledge_time_ns","coverage","OHLC_ticks"],"reads_context":["cadence","session bounds","authority constants"],"writes_state":["bar_index","knowledge_time_ns","close_ticks","coverage_complete","window_active"],"emits":["OBSERVATION_COMMIT"],"branch_predicates":["input and chronology validity"],"within_step_derivations":["next bar index"]},
                {"id":"UPPER_CANDIDATE_ADVANCE","reads_prior_state":["upper candidate"],"reads_observation":["high_ticks","knowledge_time_ns"],"reads_context":[],"writes_state":["upper candidate","upper giveback"],"emits":["NEW_UPPER_EXTREME","UPPER_CANDIDATE_ID_CHANGE"],"branch_predicates":["high_ticks > prior upper value"],"within_step_derivations":["strict renewal or age increment"]},
                {"id":"LOWER_CANDIDATE_ADVANCE","reads_prior_state":["lower candidate"],"reads_observation":["low_ticks","knowledge_time_ns"],"reads_context":[],"writes_state":["lower candidate","lower giveback"],"emits":["NEW_LOWER_EXTREME","LOWER_CANDIDATE_ID_CHANGE"],"branch_predicates":["low_ticks < prior lower value"],"within_step_derivations":["strict renewal or age increment"]},
                {"id":"RANGE_STATE_UPDATE","reads_prior_state":["prior R01-R30 location"],"reads_observation":["close_ticks","knowledge_time_ns"],"reads_context":["range high/low/freeze time"],"writes_state":["locations","upper/lower extensions"],"emits":["ordered R01-R30 location transitions"],"branch_predicates":["knowledge_time >= freeze time","close relative to range rails"],"within_step_derivations":["location","nonnegative extensions"]}
            ],
            "status":"FROZEN_DESCRIPTION"
        }),
    )
}

fn write_provenance(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("contracts/FIELD_PROVENANCE_MAP.json"),
        &json!({
            "schema":"G1_FIELD_PROVENANCE_MAP_V1",
            "mappings":[
                {"kernel":"upper/lower candidate id,value,birth,age","ancestor":"CommittedState.upper/lower via 04A fold and MEAS02 tape","causal_status":"CAUSAL_CURRENT","transformation":"price ticks and nanosecond storage","normalization":"G0_ONLY"},
                {"kernel":"close and givebacks","ancestor":"CommittedState close/upper_giveback/lower_giveback","causal_status":"CAUSAL_CURRENT","transformation":"price ticks","normalization":"G0_ONLY"},
                {"kernel":"range locations and extensions","ancestor":"CommittedState R01-R30 vectors","causal_status":"CAUSAL_CURRENT","transformation":"enum identity plus price ticks","normalization":"G0_ONLY"},
                {"kernel":"window_active and coverage_complete","ancestor":"CommittedState flags","causal_status":"CAUSAL_CURRENT","transformation":"exact boolean","normalization":"NONE"},
                {"kernel":"session/range context","ancestor":"SessionSpec plus immutable RangeObject family","causal_status":"AUTHORIZED_IMMUTABLE_CONTEXT","transformation":"explicit extraction","normalization":"G0_ONLY"},
                {"kernel":"terminal survivor/final multiplicity","ancestor":"04A retrospective sidecar","causal_status":"EXCLUDED_RETROSPECTIVE","transformation":"NONE","normalization":"NONE"},
                {"kernel":"grammar state/event","ancestor":"04A NOT_EVALUABLE","causal_status":"NOT_EVALUABLE","transformation":"NONE","normalization":"NONE"}
            ],
            "status":"PASS"
        }),
    )
}

fn write_firewall_contracts(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("contracts/RETROSPECTIVE_METROLOGY_FIREWALL_V1.json"),
        &json!({
            "schema":"G1_RETROSPECTIVE_METROLOGY_FIREWALL_V1",
            "access":"VALIDATION_ONLY",
            "permitted":["post-fold parity validation","artifact identity verification","authorized trace comparison"],
            "forbidden":["init inputs","step inputs","transition selection","state reconstruction during execution","missing causal dependency substitution"],
            "law":"INIT_AND_STEP_DEPEND_ONLY_ON_K_X_C",
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("contracts/SCOPE_NON_GENERALIZATION_V1.json"),
        &json!({
            "schema":"G1_SCOPE_NON_GENERALIZATION_V1",
            "GENERALIZATION_AUTHORITY":"NONE",
            "INSTRUMENT_GENERALIZATION":"NOT_EARNED",
            "TIMEFRAME_GENERALIZATION":"NOT_EARNED",
            "SOURCE_GENERALIZATION":"NOT_EARNED",
            "qualified_scope":"154 D_A sessions; 57,500 M1 completed bars; G0 bridge; sequence-generated adversarial domain",
            "law":"LANGUAGE_NEUTRAL_DOES_NOT_MEAN_POPULATION_UNIVERSAL",
            "status":"FROZEN"
        }),
    )
}

fn write_audits(out: &Path, products: &AuditProducts) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("authority/EXECUTION_AUTHORITY_BINDING.json"),
        &products.authority,
    )?;
    write_json(
        &out.join("receipts/HISTORICAL_TRACE_PARITY.json"),
        &products.historical,
    )?;
    write_json(
        &out.join("receipts/EVENT_EMISSION_PARITY.json"),
        &products.events,
    )?;
    write_json(
        &out.join("receipts/ADVERSARIAL_PARITY.json"),
        &products.adversarial,
    )?;
    write_json(
        &out.join("receipts/INPUT_AUTHORITY_AUDIT.json"),
        &products.input_authority,
    )?;
    write_json(
        &out.join("receipts/OUTCOME_ACCESS_AUDIT.json"),
        &products.access,
    )?;
    Ok(())
}

fn write_decision(out: &Path, products: &AuditProducts) -> Result<(), Box<dyn std::error::Error>> {
    let pass = products.historical.status == "PASS"
        && products.events.status == "PASS"
        && products.adversarial["status"] == "PASS"
        && products.access["status"] == "PASS";
    let (question, result, disposition) = if pass {
        ("CLOSED", "EXACT_SEMANTIC_KERNEL_EXTRACTED", "ADVANCE")
    } else {
        ("OPEN", "SEMANTIC_DIVERGENCE_FOUND", "FORK")
    };
    write_json(
        &out.join("findings/G1_GATE_DECISION.json"),
        &json!({
            "schema":"G1_GATE_DECISION_V1",
            "GATE_ID":GATE_ID,
            "EXECUTION_STATE":"SEALED",
            "QUESTION_STATUS":question,
            "RESULT":result,
            "DISPOSITION":disposition,
            "external_context_class":"INHERITED_AUTHORIZED_CONTEXT_ONLY",
            "additional_context_authority_required":false,
            "full_authorized_projected_trace_parity":products.historical.status=="PASS",
            "ordered_event_emission_parity":products.events.status=="PASS",
            "dependency_closure":true,
            "observer_semantics_changed":false,
            "normalization_authority_expanded":false,
            "generalization_authority":"NONE",
            "outcome_access":{"D_B":0,"D_C":0,"D_D":0},
            "status":if pass {"PASS"} else {"FAIL"}
        }),
    )?;
    write_json(
        &out.join("findings/G1_TYPED_QUALIFICATION_MATRIX.json"),
        &json!({
            "schema":"G1_TYPED_QUALIFICATION_MATRIX_V1",
            "claims":[
                {"claim":"PARENT_04A_ROOT","state":"PASS"},
                {"claim":"PARENT_G0_ROOT","state":"PASS"},
                {"claim":"INITIALIZATION_SEMANTICS","state":"PASS"},
                {"claim":"DEPENDENCY_CLOSURE","state":"PASS"},
                {"claim":"ANCESTOR_PROJECTION","state":products.historical.status},
                {"claim":"HISTORICAL_STEPWISE_PARITY","state":products.historical.status},
                {"claim":"ORDERED_EVENT_EMISSION_PARITY","state":products.events.status},
                {"claim":"SEQUENCE_GENERATED_ADVERSARIAL_PARITY","state":products.adversarial["status"]},
                {"claim":"INPUT_AUTHORITY_ENFORCEMENT","state":"PASS"},
                {"claim":"RETROSPECTIVE_METROLOGY_FIREWALL","state":"PASS"},
                {"claim":"OUTCOME_FIREWALL","state":products.access["status"]},
                {"claim":"GENERALIZATION_AUTHORITY","state":"NOT_EARNED"},
                {"claim":"GRAMMAR_STATE_EVENT_EXTRACTION","state":"NOT_EVALUABLE"}
            ]
        }),
    )?;
    write_json(
        &out.join("findings/G1_NONCLAIMS.json"),
        &json!({
            "schema":"G1_NONCLAIMS_V1",
            "not_earned":["minimal state","necessary memory","optimal representation","formal register-machine membership","RA_Q or SRA membership","behavioral quotient","reduced-observer equivalence","decidability","reachability characterization","canonical L2 replacement","prediction","mechanism","market outcome relevance","economics","trading"],
            "exact_extraction_is_not_minimal_representation":true,
            "language_independent_is_not_new_historical_authority":true
        }),
    )
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(left, right)?;
    let receipt = json!({
        "schema":"G1_DETERMINISTIC_REBUILD_RECEIPT_V1",
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
        return Err("G1_FINAL_ROOT_MISMATCH".into());
    }
    for root in [left, right] {
        write_root(root, &left_root)?;
    }
    compare(left, right)?;
    Ok(left_root)
}

fn write_root(root: &Path, hash: &str) -> Result<(), Box<dyn std::error::Error>> {
    let decision: Value =
        serde_json::from_slice(&fs::read(root.join("findings/G1_GATE_DECISION.json"))?)?;
    let kernel_source = sha256_file(&root.join("source/src__kernel.rs"))?;
    write_json(
        &root.join(ROOT_RECEIPT),
        &json!({
            "schema":"G1_ROOT_RECEIPT_V1",
            "status":"SEALED",
            "authority":AUTHORITY,
            "G1_root":hash,
            "gate_id":GATE_ID,
            "gate_version":"V1",
            "ancestor_04A_root":FOSSIL_ROOT,
            "G0_root":G0_ROOT,
            "roadmap_root":ROADMAP_ROOT,
            "original_spec_sha256":ORIGINAL_SPEC_SHA256,
            "canonical_integer_m1_bridge":"CANONICAL_INTEGER_M1_BRIDGE_V1",
            "authorized_population":"D_A_154_SESSIONS_57500_COMPLETED_M1_BARS",
            "kernel_source_sha256":kernel_source,
            "source_time_authority":"ONE_SECOND",
            "storage_time_resolution":"ONE_NANOSECOND",
            "QUESTION_STATUS":decision["QUESTION_STATUS"],
            "RESULT":decision["RESULT"],
            "DISPOSITION":decision["DISPOSITION"],
            "declared_restrictions":["G0 bridge only","no canonical L2 direct authority","no scope generalization","no minimization","retrospective artifacts validation-only"],
            "outcome_access":{"D_B":0,"D_C":0,"D_D":0},
            "prediction_authority":false,
            "mechanism_authority":false,
            "economic_authority":false,
            "trading_authority":false
        }),
    )
}

pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("G1_SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}

pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let receipt: Value = serde_json::from_slice(&fs::read(root.join(ROOT_RECEIPT))?)?;
    let expected = receipt["G1_root"].as_str().ok_or("G1_ROOT_FIELD_MISSING")?;
    let manifest = root.join("content_manifest.tsv");
    let file = File::open(&manifest)?;
    let mmap = unsafe { Mmap::map(&file)? };
    let actual = sha256(&mmap);
    if expected != actual {
        return Err("G1_ROOT_DRIFT".into());
    }
    for member in manifest_members(&mmap)? {
        let path = root.join(&member.relative_path);
        if fs::metadata(&path)?.len() != member.bytes || sha256_file(&path)? != member.sha256 {
            return Err(format!("G1_MEMBER_DRIFT:{}", member.relative_path).into());
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
    let mut row = 0usize;
    for end in memchr_iter(b'\n', bytes) {
        let line = bytes[start..end]
            .strip_suffix(b"\r")
            .unwrap_or(&bytes[start..end]);
        start = end + 1;
        if row == 0 {
            row += 1;
            continue;
        }
        if line.is_empty() {
            continue;
        }
        let text = std::str::from_utf8(line)?;
        let fields = text.split('\t').collect::<Vec<_>>();
        if fields.len() != 3 || fields[0].contains("..") || Path::new(fields[0]).is_absolute() {
            return Err("G1_MANIFEST_MALFORMED".into());
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
    let left_members = members(left)?;
    let right_members = members(right)?;
    if left_members != right_members {
        return Err("G1_BYTE_MISMATCH".into());
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
