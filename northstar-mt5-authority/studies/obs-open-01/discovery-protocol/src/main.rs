use obs_open_disc02p::*;
use serde::Serialize;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

const BASE: &str = "studies/obs-open-01/discovery-protocol";
const MEAS_ROOT_RECEIPT: &str =
    "studies/obs-open-01/measurement-surface/seal/meas02_root_receipt.json";
const MEAS_MANIFEST: &str =
    "studies/obs-open-01/measurement-surface/seal/measurement_authority_manifest.json";
const MEAS_FIREWALL: &str =
    "studies/obs-open-01/measurement-surface/seal/receipts/confirmation_firewall_receipt.json";
const UNIVERSE_RECEIPT: &str =
    "studies/obs-open-01/qualification/universe/seal/universe_qualification_root_receipt.json";

const CAPSULE_FILES: &[&str] = &[
    ".gitignore",
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_DISC_02P_PROTOCOL_V1.md",
    "OBS_OPEN_DISC_02P_CHECKPOINT_20260814.md",
    "contracts/authority_v1.json",
    "contracts/measurement_registry_v1.json",
    "contracts/inference_v1.json",
    "contracts/candidate_schema_v1.json",
    "contracts/confirmation_v1.json",
    "src/lib.rs",
    "src/main.rs",
    "tests/protocol_contract.rs",
];

fn canonical_json(path: &Path, value: &impl Serialize) -> AnyResult<()> {
    fs::write(path, canonical_json_bytes(value)?)?;
    Ok(())
}

fn source(relative: &str) -> String {
    format!("{BASE}/{relative}")
}

fn declared_reads() -> Vec<(String, String)> {
    let mut reads = vec![
        (MEAS_ROOT_RECEIPT.into(), "BIND_MEAS02_ROOT".into()),
        (MEAS_MANIFEST.into(), "BIND_MEAS02_AUTHORITY".into()),
        (
            MEAS_FIREWALL.into(),
            "VERIFY_PARENT_CONFIRMATION_FIREWALL".into(),
        ),
        (UNIVERSE_RECEIPT.into(), "BIND_FROZEN_POPULATIONS".into()),
    ];
    reads.extend(
        CAPSULE_FILES
            .iter()
            .map(|relative| (source(relative), "HASH_PROTOCOL_CAPSULE".into())),
    );
    reads
}

fn require_str(value: &Value, pointer: &str, expected: &str) -> AnyResult<()> {
    if value.pointer(pointer).and_then(Value::as_str) != Some(expected) {
        return Err(format!("PARENT_AUTHORITY_MISMATCH:{pointer}:{expected}").into());
    }
    Ok(())
}

fn require_u64(value: &Value, pointer: &str, expected: u64) -> AnyResult<()> {
    if value.pointer(pointer).and_then(Value::as_u64) != Some(expected) {
        return Err(format!("PARENT_AUTHORITY_MISMATCH:{pointer}:{expected}").into());
    }
    Ok(())
}

fn validate_parents(
    meas_root: &Value,
    meas_manifest: &Value,
    meas_firewall: &Value,
    universe: &Value,
) -> AnyResult<()> {
    require_str(meas_root, "/meas02_root", MEAS02_ROOT)?;
    require_str(
        meas_root,
        "/authority",
        "CAUSAL_SESSION_PROCESS_MEASUREMENT_V1",
    )?;
    require_u64(meas_root, "/confirmation_observation_rows_read", 0)?;
    require_str(meas_manifest, "/observer_instance", OBSERVER_INSTANCE)?;
    require_str(meas_manifest, "/parents/instrument/root", INST01_ROOT)?;
    require_str(meas_manifest, "/parents/clock_universe/root", UNIVERSE_ROOT)?;
    require_str(meas_firewall, "/confirmation_status", "FROZEN_UNOPENED")?;
    require_u64(meas_firewall, "/confirmation_observation_rows_read", 0)?;
    require_u64(meas_firewall, "/confirmation_membership_rows_read", 0)?;
    require_str(universe, "/qualification_root_sha256", UNIVERSE_ROOT)?;
    require_u64(universe, "/discovery_sessions", DISCOVERY_SESSIONS)?;
    require_u64(universe, "/confirmation_sessions", CONFIRMATION_SESSIONS)?;
    require_str(universe, "/confirmation_status", "FROZEN_UNOPENED")?;
    Ok(())
}

fn synthetic_receipt() -> AnyResult<Value> {
    let balance_rows = vec![(1, 10.0), (1, 10.0), (1, 10.0), (1, 10.0), (2, 0.0)];
    let balanced = session_balanced_values(&balance_rows);
    let balanced_mean = balanced.iter().map(|x| x.1).sum::<f64>() / balanced.len() as f64;
    if balanced != vec![(1, 10.0), (2, 0.0)] || balanced_mean != 5.0 {
        return Err("SESSION_WEIGHTING_FIXTURE_FAILED".into());
    }

    let null = vec![vec![0.0; 6]; 16];
    let null_observed = observed_max_abs_t(&null)?;
    let null_reference = sign_flip_max_t_distribution(&null, RANDOMIZATIONS, RANDOM_SEED, 1)?;
    let (_, null_p) = plus_one_p(null_observed, &null_reference);
    if null_p != 1.0 {
        return Err("COMPLETE_NULL_FIXTURE_PROMOTED".into());
    }

    let effect: Vec<Vec<f64>> = (0..24)
        .map(|session| {
            (0..6)
                .map(|cell| 2.0 + session as f64 * 0.01 + cell as f64 * 0.02)
                .collect()
        })
        .collect();
    let effect_observed = observed_max_abs_t(&effect)?;
    let one = sign_flip_max_t_distribution(&effect, RANDOMIZATIONS, RANDOM_SEED, 1)?;
    let four = sign_flip_max_t_distribution(&effect, RANDOMIZATIONS, RANDOM_SEED, 4)?;
    if one != four {
        return Err("PARALLEL_RANDOMIZATION_NOT_DETERMINISTIC".into());
    }
    let (exceedances, effect_p) = plus_one_p(effect_observed, &one);
    let decision = monte_carlo_decision(exceedances, RANDOMIZATIONS, ALPHA / FORMAL_TESTS as f64)?;
    if decision != NumericalDecision::Pass {
        return Err(format!("INJECTED_EFFECT_NOT_RESOLVED:{decision:?}").into());
    }

    let anchor = canonical_anchor(&[
        ("K02_T01".into(), -4.0),
        ("K01_T02".into(), 4.0),
        ("K03_T01".into(), 3.0),
    ]);
    if anchor.as_deref() != Some("K01_T02") {
        return Err("CANONICAL_ANCHOR_TIEBREAK_FAILED".into());
    }
    if temporal_sign_status(1.0, &[1.0, 0.5, 2.0]) != "TEMPORALLY_SUPPORTED"
        || temporal_sign_status(1.0, &[1.0, -0.5, 2.0]) != "TEMPORALLY_UNSTABLE"
        || temporal_sign_status(1.0, &[1.0, 0.0, 2.0]) != "TEMPORAL_SUPPORT_INSUFFICIENT"
    {
        return Err("TEMPORAL_STATUS_FIXTURE_FAILED".into());
    }

    let packed = [
        PackedSurfaceCell {
            session: 1,
            coordinate: 1,
            value: 3.0,
        },
        PackedSurfaceCell {
            session: 2,
            coordinate: 1,
            value: -2.0,
        },
    ];
    let hash_one = packed_surface_hash(&packed);
    let hash_two = packed_surface_hash(&packed);
    if hash_one != hash_two {
        return Err("PACKED_SURFACE_HASH_NOT_DETERMINISTIC".into());
    }

    Ok(json!({
        "schema":"OBS_OPEN_DISC02P_SYNTHETIC_QUALIFICATION_V1",
        "status":"PASS",
        "real_market_rows_read":0,
        "confirmation_rows_read":0,
        "checks":{
            "equal_session_weighting":"PASS",
            "complete_null_not_promoted":"PASS",
            "injected_surface_effect_resolved":"PASS",
            "nested_surface_max_statistic":"PASS",
            "canonical_anchor_tie_break":"PASS",
            "temporal_sign_reversal":"PASS",
            "temporal_zero_is_insufficient":"PASS",
            "parallel_1_vs_4_threads":"PASS_BYTE_IDENTICAL",
            "packed_zero_copy_surface_hash":"PASS"
        },
        "null_p":null_p,
        "injected_effect_p":effect_p,
        "injected_effect_exceedances":exceedances,
        "randomizations":RANDOMIZATIONS,
        "seed":RANDOM_SEED,
        "packed_surface_sha256":hash_one
    }))
}

fn write_matrix(path: &Path) -> AnyResult<()> {
    let claims = [
        (
            "MEAS02_PARENT_BINDING",
            "PASS",
            "sealed root and observer instance",
        ),
        (
            "TWO_QUESTION_FAMILIES_ONLY",
            "PASS",
            "A running-extreme; B fixed-range session process",
        ),
        (
            "SESSION_INFERENTIAL_UNIT",
            "PASS",
            "synthetic unequal-chain fixture",
        ),
        (
            "NESTED_RANGE_SURFACE",
            "PASS",
            "single support-aware k,tau surface",
        ),
        (
            "FORMAL_ESTIMAND_REGISTRY",
            "PASS",
            "three natural-null surface contrasts",
        ),
        (
            "DESCRIPTIVE_FORMAL_SEPARATION",
            "PASS",
            "positive constrained measurements are descriptive",
        ),
        (
            "CENSORING_SEMANTICS",
            "PASS",
            "terminal survivors right-censored for supersession",
        ),
        (
            "NUMERICAL_RESOLUTION",
            "PASS",
            "plus-one p_min and tenfold headroom",
        ),
        (
            "MONTE_CARLO_DECISION_PRECISION",
            "PASS",
            "Wilson 99 percent fail-closed rule",
        ),
        (
            "MULTIPLICITY",
            "PASS",
            "maxT within surface and Holm across three families",
        ),
        (
            "TEMPORAL_ROBUSTNESS",
            "PASS",
            "frozen month offset LOMO and chronological views",
        ),
        (
            "GRAMMAR_EXCLUSION",
            "PASS",
            "capability preserved; substantive family excluded",
        ),
        (
            "DISCOVERY_FIREWALL",
            "PASS",
            "zero MEAS-02 full-corpus values read",
        ),
        (
            "CONFIRMATION_FIREWALL",
            "PASS",
            "zero confirmation rows read",
        ),
        (
            "DETERMINISTIC_REBUILD",
            "PASS",
            "two byte-identical protocol builds",
        ),
    ];
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(writer, "claim\tstatus\tevidence")?;
    for (claim, status, evidence) in claims {
        writeln!(writer, "{claim}\t{status}\t{evidence}")?;
    }
    Ok(())
}

fn build_once(repo: &Path, out: &Path) -> AnyResult<String> {
    fs::create_dir_all(out.join("contracts"))?;
    fs::create_dir_all(out.join("source"))?;
    fs::create_dir_all(out.join("receipts"))?;
    let mut reader = AuthorityReader::new(repo, declared_reads())?;

    let meas_root = reader.read_json(MEAS_ROOT_RECEIPT)?;
    let meas_manifest = reader.read_json(MEAS_MANIFEST)?;
    let meas_firewall = reader.read_json(MEAS_FIREWALL)?;
    let universe = reader.read_json(UNIVERSE_RECEIPT)?;
    validate_parents(&meas_root, &meas_manifest, &meas_firewall, &universe)?;

    let mut capsule = BTreeMap::new();
    for relative in CAPSULE_FILES {
        capsule.insert(*relative, reader.read(&source(relative))?);
    }
    reader.assert_complete()?;

    let authority: Value = serde_json::from_slice(&capsule["contracts/authority_v1.json"])?;
    let measurements: Value =
        serde_json::from_slice(&capsule["contracts/measurement_registry_v1.json"])?;
    let inference: Value = serde_json::from_slice(&capsule["contracts/inference_v1.json"])?;
    let candidate: Value = serde_json::from_slice(&capsule["contracts/candidate_schema_v1.json"])?;
    let confirmation: Value = serde_json::from_slice(&capsule["contracts/confirmation_v1.json"])?;
    validate_contracts(
        &authority,
        &measurements,
        &inference,
        &candidate,
        &confirmation,
    )?;

    for relative in CAPSULE_FILES {
        let target = if relative.starts_with("contracts/") || relative.ends_with(".md") {
            out.join(relative)
        } else {
            out.join("source").join(relative.replace('/', "__"))
        };
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(target, &capsule[relative])?;
    }

    canonical_json(
        &out.join("protocol_authority_manifest.json"),
        &json!({
            "schema":"OBS_OPEN_DISC02P_PROTOCOL_AUTHORITY_V1",
            "authority":"OBS_OPEN_DISC02P_FROZEN_PROTOCOL_V1",
            "parents":{"meas02_root":MEAS02_ROOT,"instrument_root":INST01_ROOT,"universe_root":UNIVERSE_ROOT},
            "observer_instance":OBSERVER_INSTANCE,
            "discovery":{"sessions":DISCOVERY_SESSIONS,"state":"MEAS02_DISCOVERY_UNOPENED","substantive_rows_read":0},
            "confirmation":{"sessions":CONFIRMATION_SESSIONS,"state":"FROZEN_UNOPENED","observation_rows_read":0,"membership_rows_read":0},
            "formal_tests":FORMAL_TESTS,
            "question_families":["RUNNING_EXTREME_PROCESS","FIXED_RANGE_SESSION_PROCESS"],
            "maximum_authority":"DISCOVERY_AND_CONFIRMATION_PROTOCOL_FROZEN__EXECUTION_NOT_AUTHORIZED",
            "economic_authority":false,
            "trading_authority":false
        }),
    )?;
    canonical_json(
        &out.join("receipts/parent_binding_receipt.json"),
        &json!({"schema":"OBS_OPEN_DISC02P_PARENT_BINDING_V1","status":"PASS","meas02_root":MEAS02_ROOT,"instrument_root":INST01_ROOT,"universe_root":UNIVERSE_ROOT,"observer_instance":OBSERVER_INSTANCE}),
    )?;
    canonical_json(
        &out.join("receipts/access_audit_receipt.json"),
        &json!({"schema":"OBS_OPEN_DISC02P_ACCESS_AUDIT_V1","status":"PASS","declared_reads":reader.receipts(),"declared_read_count":reader.receipts().len(),"undeclared_reads":0,"raw_market_files_read":0,"meas02_measurement_rows_read":0,"discovery_substantive_rows_read":0,"confirmation_membership_rows_read":0,"confirmation_observation_rows_read":0}),
    )?;
    canonical_json(
        &out.join("receipts/firewall_receipt.json"),
        &json!({"schema":"OBS_OPEN_DISC02P_FIREWALL_V1","status":"PASS","discovery_state":"MEAS02_DISCOVERY_UNOPENED","discovery_substantive_rows_read":0,"confirmation_state":"FROZEN_UNOPENED","confirmation_rows_read":0,"execution_authorized":false}),
    )?;
    canonical_json(
        &out.join("receipts/numerical_resolution_receipt.json"),
        &json!({"schema":"OBS_OPEN_DISC02P_NUMERICAL_RESOLUTION_V1","status":"PASS","formal_tests":FORMAL_TESTS,"alpha":ALPHA,"headroom_factor":10,"minimum_required_randomizations":minimum_randomizations(ALPHA,FORMAL_TESTS,10),"frozen_randomizations":RANDOMIZATIONS,"minimum_attainable_p":minimum_attainable_p(RANDOMIZATIONS),"strictest_first_holm_threshold":ALPHA/FORMAL_TESTS as f64,"maximum_p_min_allowed":ALPHA/(FORMAL_TESTS as f64*10.0),"monte_carlo_decision":"WILSON_99_PERCENT_FAIL_CLOSED"}),
    )?;
    canonical_json(
        &out.join("receipts/synthetic_qualification_receipt.json"),
        &synthetic_receipt()?,
    )?;
    canonical_json(
        &out.join("receipts/deterministic_rebuild_receipt.json"),
        &json!({"schema":"OBS_OPEN_DISC02P_DETERMINISTIC_REBUILD_V1","status":"PASS","method":"TWO_INDEPENDENT_OUTPUT_DIRECTORIES_BYTE_IDENTICAL","thread_parity":"ONE_VS_FOUR_BYTE_IDENTICAL","build_labels_excluded":true}),
    )?;
    write_matrix(&out.join("typed_qualification_matrix.tsv"))?;
    write_manifest_and_root(out)
}

fn collect_files(base: &Path, dir: &Path, out: &mut Vec<PathBuf>) -> AnyResult<()> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            collect_files(base, &path, out)?;
        } else {
            let rel = path.strip_prefix(base)?.to_path_buf();
            if rel != Path::new("content_manifest.tsv")
                && rel != Path::new("disc02p_root_receipt.json")
            {
                out.push(rel);
            }
        }
    }
    Ok(())
}

fn write_manifest_and_root(out: &Path) -> AnyResult<String> {
    let mut files = Vec::new();
    collect_files(out, out, &mut files)?;
    files.sort();
    let manifest_path = out.join("content_manifest.tsv");
    let mut writer = BufWriter::new(File::create(&manifest_path)?);
    writeln!(writer, "relative_path\tbytes\tsha256")?;
    for rel in &files {
        let path = out.join(rel);
        writeln!(
            writer,
            "{}\t{}\t{}",
            rel.to_string_lossy().replace('\\', "/"),
            fs::metadata(&path)?.len(),
            sha256_file(&path)?
        )?;
    }
    drop(writer);
    let root = sha256_file(&manifest_path)?;
    canonical_json(
        &out.join("disc02p_root_receipt.json"),
        &json!({"schema":"OBS_OPEN_DISC02P_ROOT_RECEIPT_V1","status":"PASS","authority":"OBS_OPEN_DISC02P_FROZEN_PROTOCOL_V1","disc02p_root":root,"manifest_rows":files.len(),"meas02_root":MEAS02_ROOT,"discovery_substantive_rows_read":0,"confirmation_rows_read":0,"discovery_execution_authorized":false}),
    )?;
    Ok(root)
}

fn compare_dirs(a: &Path, b: &Path) -> AnyResult<()> {
    let mut left = Vec::new();
    let mut right = Vec::new();
    collect_all(a, a, &mut left)?;
    collect_all(b, b, &mut right)?;
    left.sort();
    right.sort();
    if left != right {
        return Err("DETERMINISTIC_BUILD_FILE_SET_MISMATCH".into());
    }
    for rel in left {
        if fs::read(a.join(&rel))? != fs::read(b.join(&rel))? {
            return Err(format!("DETERMINISTIC_BUILD_BYTE_MISMATCH:{}", rel.display()).into());
        }
    }
    Ok(())
}

fn collect_all(base: &Path, dir: &Path, out: &mut Vec<PathBuf>) -> AnyResult<()> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            collect_all(base, &path, out)?;
        } else {
            out.push(path.strip_prefix(base)?.to_path_buf());
        }
    }
    Ok(())
}

fn checked_remove(base: &Path, target: &Path) -> AnyResult<()> {
    let base = fs::canonicalize(base)?;
    let parent = target.parent().ok_or("TARGET_HAS_NO_PARENT")?;
    fs::create_dir_all(parent)?;
    let parent = fs::canonicalize(parent)?;
    if !parent.starts_with(&base) {
        return Err("REFUSING_REMOVE_OUTSIDE_PROTOCOL_ROOT".into());
    }
    if target.exists() {
        fs::remove_dir_all(target)?;
    }
    Ok(())
}

fn copy_dir(src: &Path, dst: &Path) -> AnyResult<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let path = entry.path();
        let target = dst.join(entry.file_name());
        if path.is_dir() {
            copy_dir(&path, &target)?;
        } else {
            fs::copy(path, target)?;
        }
    }
    Ok(())
}

fn main() -> AnyResult<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 || args[1] != "seal" {
        return Err("usage: obs-open-disc02p seal <repo>".into());
    }
    let repo = fs::canonicalize(&args[2])?;
    let base = repo.join(BASE);
    let a = base.join("seal-build-a");
    let b = base.join("seal-build-b");
    let seal = base.join("seal");
    for target in [&a, &b, &seal] {
        checked_remove(&base, target)?;
    }
    let left_root = build_once(&repo, &a)?;
    let right_root = build_once(&repo, &b)?;
    compare_dirs(&a, &b)?;
    if left_root != right_root {
        return Err("DETERMINISTIC_LOGICAL_ROOT_MISMATCH".into());
    }
    copy_dir(&a, &seal)?;
    println!("DISC02P_ROOT={left_root}");
    println!("BUILD_PARITY=PASS_BYTE_IDENTICAL");
    println!("DISCOVERY_SUBSTANTIVE_ROWS_READ=0");
    println!("CONFIRMATION_ROWS_READ=0");
    println!("DISCOVERY_EXECUTION_AUTHORIZED=false");
    Ok(())
}
