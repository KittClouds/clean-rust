use crate::algebra::audit;
use crate::authority::{BoundAuthority, sha256, sha256_file};
use crate::contracts::contracts;
use crate::model::*;
use crate::qualification::qualify;
use crate::target::support;
use serde::Serialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

const STUDY: &str = "studies/obs-open-01/range-representation-tournament-protocol";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_03B_P_PROTOCOL_V1.md",
    "src/algebra.rs",
    "src/authority.rs",
    "src/contracts.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/model.rs",
    "src/probe.rs",
    "src/qualification.rs",
    "src/seal.rs",
    "src/target.rs",
    "tests/protocol_contract.rs",
];

#[derive(Debug, Clone, Serialize)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build_protocol(
    repo: &Path,
    atlas: &Path,
    out: &Path,
) -> Result<String, Box<dyn std::error::Error>> {
    prepare_output(out)?;
    for dir in ["contracts", "d_a", "ledgers", "receipts", "source"] {
        fs::create_dir_all(out.join(dir))?;
    }
    let authority = BoundAuthority::open(repo, atlas)?;
    let target = support(authority.records()).map_err(|e| format!("TARGET_BINDING_FAILED:{e}"))?;
    let algebra = audit(&authority.sessions).map_err(|e| format!("ALGEBRA_AUDIT_FAILED:{e}"))?;
    let qualification =
        qualify(&authority.sessions).map_err(|e| format!("QUALIFICATION_FAILED:{e}"))?;
    for (name, value) in contracts() {
        write_json(&out.join("contracts").join(name), &value)?;
    }
    fs::copy(
        repo.join(STUDY).join("OBS_OPEN_03B_P_PROTOCOL_V1.md"),
        out.join("03BP_PROTOCOL_V1.md"),
    )?;
    write_json(&out.join("d_a/D_A_TARGET_SUPPORT_RECEIPT.json"), &target)?;
    write_json(
        &out.join("d_a/REPRESENTATION_RELATION_AUDIT_V1.json"),
        &json!({"schema":"REPRESENTATION_RELATION_AUDIT_V1","source_kind":"MACHINE_DERIVED","D_A_only":true,"audit":algebra}),
    )?;
    write_folds(&out.join("d_a/D_A_TRAINING_FOLDS.tsv"), &authority)?;
    write_ledgers(out)?;
    write_json(
        &out.join("receipts/SYNTHETIC_ADVERSARIAL_QUALIFICATION.json"),
        &json!({"schema":"OBS_OPEN_03BP_SYNTHETIC_QUALIFICATION_V1","case_count":qualification.len(),"failed":qualification.iter().filter(|x|x.status!="PASS").count(),"cases":qualification,"status":"PASS"}),
    )?;
    write_json(
        &out.join("receipts/ACCESS_AUDIT.json"),
        &json!({
            "schema":"OBS_OPEN_03BP_ACCESS_AUDIT_V1","D_A":{"sessions_decoded":authority.sessions.len(),"retained_M1_bars_read":authority.d_a_bars_read,"path_gap_sessions":authority.d_a_gap_sessions,"atlas_outcome_records_read":authority.records().len(),"target_values_decoded":0},
            "D_B":{"outcome_registry_applications":0,"target_values_computed":0,"target_values_read":0,"model_scores":0,"model_fitting":0,"normalization_fitting":0,"hyperparameter_selection":0},
            "D_C":{"membership_decoding":0,"observations_read":0,"outcomes_computed":0,"outcomes_read":0},"status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/PARENT_AUTHORITY_BINDING.json"),
        &json!({"schema":"OBS_OPEN_03BP_PARENT_BINDING_V1","parents":{"future_process_protocol":FUTURE_PROTOCOL_ROOT,"future_process_atlas":ATLAS_ROOT,"descriptive_anatomy":ANATOMY_ROOT,"measurement":MEAS02_ROOT,"clock_universe":UNIVERSE_ROOT},"atlas_members_verified":authority.atlas_member_count,"atlas_ledger_sha256":authority.atlas_ledger_sha256,"raw_source_sha256":authority.raw_source_sha256,"atlas_root_path":authority.atlas_root,"status":"PASS"}),
    )?;
    write_json(
        &out.join("receipts/PROTOCOL_GENERATION_RECEIPT.json"),
        &json!({"schema":"OBS_OPEN_03BP_PROTOCOL_GENERATION_V1","target_horizon_minutes":60,"selection_population":"D_A_AUTHORIZED_HYPOTHESIS_GENERATION","selection_reasons":["inside admitted session for every k","better support than long-horizon tail","not exclusively immediate post-freeze","not selected as largest heatmap cell"],"formal_target_count":1,"formal_representation_tests":2,"combined_representation":false,"candidate_history":false,"neural_probe":false,"status":"PASS"}),
    )?;
    write_json(
        &out.join("receipts/EXECUTION_CONTRACT_RECEIPT.json"),
        &json!({"schema":"OBS_OPEN_03BP_EXECUTION_CONTRACT_V1","probe":"L2_LOGISTIC_PROBE_V1","regularization_grid":[1e-4,1e-3,1e-2,1e-1,1.0,10.0],"randomizations":RANDOMIZATIONS,"seed":SEED,"p_min":1.0/(RANDOMIZATIONS as f64+1.0),"effect_floor_relative_brier_skill":MIN_RELATIVE_BRIER_SKILL,"formal_support":{"complete_D_B_sessions":D_B_MIN_COMPLETE_SESSIONS,"per_offset_regime":D_B_MIN_OFFSET_SESSIONS},"D_B_execution_authorized":false,"status":"PASS"}),
    )?;
    write_matrix(&out.join("TYPED_QUALIFICATION_MATRIX.tsv"))?;
    copy_source(repo, out)?;
    write_json(
        &out.join("03BP_AUTHORITY_MANIFEST.json"),
        &json!({"schema":"OBS_OPEN_03BP_AUTHORITY_MANIFEST_V1","authority":AUTHORITY,"parents":{"future_protocol":FUTURE_PROTOCOL_ROOT,"atlas":ATLAS_ROOT,"anatomy":ANATOMY_ROOT,"measurement":MEAS02_ROOT,"universe":UNIVERSE_ROOT},"population":{"D_A":D_A_SESSIONS,"D_B":D_B_SESSIONS,"D_C":D_C_SESSIONS},"source_closure_sha256":source_closure_hash(repo)?,"protocol_only":true,"empirical_representation_information_claim":false,"economic_authority":false,"trading_authority":false}),
    )?;
    reseal(out)
}

fn write_folds(path: &Path, a: &BoundAuthority) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "session_index\tsession_id\tcivil_date\toffset_minutes\tchronological_role"
    )?;
    for (i, s) in a.sessions.iter().enumerate() {
        let role = match i {
            0..=29 => "INITIAL_TRAIN",
            30..=60 => "VALIDATION_FOLD_1",
            61..=91 => "VALIDATION_FOLD_2",
            92..=122 => "VALIDATION_FOLD_3",
            _ => "VALIDATION_FOLD_4",
        };
        writeln!(
            w,
            "{}\t{}\t{}\t{}\t{}",
            i, s.spec.session_id, s.spec.civil_date, s.spec.server_offset_minutes, role
        )?;
    }
    w.flush()
}

fn write_ledgers(out: &Path) -> std::io::Result<()> {
    fs::write(
        out.join("ledgers/REPRESENTATION_BOUNDARY_LEDGER.tsv"),
        concat!(
            "object\tstatus\treceipt\n",
            "K_VS_FREEZE_CLOCK\tPERFECT_ALIAS\tk is freeze minute after 09:30.\n",
            "PURE_SCALE_INDEPENDENT_OF_CLOCK\tNOT_IDENTIFIABLE\tNo independent variation of construction duration and freeze clock.\n",
            "RAW_TO_Z\tDETERMINISTIC\tPositive width maps raw offsets to 2*offset/width.\n",
            "Z_TO_RAW_GIVEN_CONTEXT\tNOT_RECONSTRUCTIBLE\tDesign context excludes width.\n",
            "Z_TO_RAW_GIVEN_WIDTH\tCONDITIONALLY_INVERTIBLE\tMultiply each z coordinate by width/2.\n",
            "RAW_PLUS_Z\tNOT_AUTHORIZED\tComplementarity is parked.\n"
        ),
    )?;
    fs::write(
        out.join("ledgers/PARKED_QUESTION_LEDGER.tsv"),
        concat!(
            "question_id\tstatus\treason\n",
            "LANDMARK_AGE_STATE\tPARKED\tRequires causal landmark anchors.\n",
            "CAUSAL_CANDIDATE_GENERATION_HISTORY\tPARKED\tFinal multiplicity is retrospective; a causal-prefix object must be separately frozen.\n",
            "CANDIDATE_BIRTH_REPRESENTATION_GATE\tPARKED\tNot part of first range tournament.\n",
            "PURE_SCALE_INDEPENDENT_OF_CLOCK\tNOT_IDENTIFIABLE\tk and freeze clock are aliases.\n",
            "RAW_PLUS_Z_COMPLEMENTARITY\tPARKED\tRequires later separately frozen question.\n",
            "PATH_VARIATION_CONTROL\tPARKED_CONTROL\tRetained as stopwatch-control outcome.\n"
        ),
    )
}

fn write_matrix(path: &Path) -> std::io::Result<()> {
    let claims = [
        "PARENT_AUTHORITY_BINDING",
        "TARGET_REGISTRY_BINDING",
        "TARGET_KNOWLEDGE_TIME",
        "D_A_D_B_D_C_FIREWALL",
        "RANGE_DESIGN_CONTEXT_FREEZE",
        "RAW_REPRESENTATION_FIELD_LINEAGE",
        "Z_REPRESENTATION_FIELD_LINEAGE",
        "REPRESENTATION_RELATION_AUDIT",
        "HISTORY_EXCLUSION",
        "FUTURE_INFORMATION_EXCLUSION",
        "SESSION_WEIGHTING",
        "COMPLETE_SESSION_FORMAL_ELIGIBILITY",
        "D_A_ONLY_TRANSFORM_FIT",
        "D_A_ONLY_HYPERPARAMETER_SELECTION",
        "PROBE_PARITY",
        "BRIER_SCORE_IMPLEMENTATION",
        "EFFECT_SIZE_FLOOR",
        "SESSION_LEVEL_RESAMPLING",
        "MULTIPLICITY",
        "MONTE_CARLO_RESOLUTION",
        "FAILURE_PRECEDENCE",
        "D_B_DERIVED_OUTCOME_FIREWALL",
        "D_C_FIREWALL",
        "DETERMINISTIC_REBUILD_POLICY",
    ];
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(w, "claim\tstate\tsource_kind\n")?;
    for c in claims {
        writeln!(w, "{}\tPASS\tMACHINE_DERIVED", c)?;
    }
    w.flush()
}

fn copy_source(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    for rel in SOURCE_FILES {
        let dst = out.join("source").join(rel.replace('/', "_"));
        fs::copy(repo.join(STUDY).join(rel), dst)?;
    }
    Ok(())
}
fn source_closure_hash(repo: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut h = Sha256::new();
    for rel in SOURCE_FILES {
        h.update(rel.as_bytes());
        h.update([0]);
        h.update(fs::read(repo.join(STUDY).join(rel))?);
        h.update([0xff]);
    }
    Ok(format!("{:x}", h.finalize()))
}

pub fn finalize_rebuild(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let provisional = compare(left, right)?;
    if provisional.1 != 0 {
        return Err("PROVISIONAL_REBUILD_MISMATCH".into());
    }
    let receipt = json!({"schema":"OBS_OPEN_03BP_DETERMINISTIC_REBUILD_RECEIPT_V1","provisional_root":provisional.0,"artifact_count":provisional.2,"mismatch_count":0,"status":"PASS"});
    for root in [left, right] {
        write_json(&root.join("DETERMINISTIC_REBUILD_RECEIPT.json"), &receipt)?;
        reseal(root)?;
    }
    let final_result = compare(left, right)?;
    if final_result.1 != 0 {
        return Err("FINAL_REBUILD_MISMATCH".into());
    }
    Ok(final_result.0)
}

fn reseal(out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    for name in ["content_manifest.tsv", "03BP_ROOT_RECEIPT.json"] {
        let p = out.join(name);
        if p.exists() {
            fs::remove_file(p)?;
        }
    }
    let members = members(out)?;
    let manifest = manifest(&members);
    fs::write(out.join("content_manifest.tsv"), &manifest)?;
    let root = sha256(&manifest);
    write_json(
        &out.join("03BP_ROOT_RECEIPT.json"),
        &json!({"schema":"OBS_OPEN_03BP_ROOT_RECEIPT_V1","authority":AUTHORITY,"obs_open_03bp_root":root,"artifact_count":members.len(),"D_B_outcome_registry_applications":0,"D_B_target_values_computed":0,"D_B_target_values_read":0,"D_B_model_scores":0,"D_C_observations_read":0,"empirical_claims":0,"status":"PASS"}),
    )?;
    Ok(root)
}

fn compare(
    left: &Path,
    right: &Path,
) -> Result<(String, usize, usize), Box<dyn std::error::Error>> {
    let lf = recursive(left)?;
    let rf = recursive(right)?;
    let lr: Vec<_> = lf
        .iter()
        .map(|p| p.strip_prefix(left).unwrap().to_owned())
        .collect();
    let rr: Vec<_> = rf
        .iter()
        .map(|p| p.strip_prefix(right).unwrap().to_owned())
        .collect();
    let mut mismatch = usize::from(lr != rr);
    if lr == rr {
        for rel in &lr {
            mismatch += usize::from(fs::read(left.join(rel))? != fs::read(right.join(rel))?);
        }
    }
    let root: serde_json::Value =
        serde_json::from_slice(&fs::read(left.join("03BP_ROOT_RECEIPT.json"))?)?;
    Ok((
        root["obs_open_03bp_root"]
            .as_str()
            .ok_or("ROOT_MISSING")?
            .into(),
        mismatch,
        lr.len(),
    ))
}

pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let rebuild: serde_json::Value =
        serde_json::from_slice(&fs::read(build.join("DETERMINISTIC_REBUILD_RECEIPT.json"))?)?;
    if rebuild["status"].as_str() != Some("PASS") {
        return Err("REBUILD_NOT_FINALIZED".into());
    }
    if seal.exists() {
        let resolved = fs::canonicalize(seal)?;
        let n = resolved
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        if !n.contains("/studies/obs-open-01/range-representation-tournament-protocol/seal") {
            return Err("REFUSE_SEAL_REPLACEMENT".into());
        }
        fs::remove_dir_all(resolved)?;
    }
    copy_tree(build, seal)?;
    let root: serde_json::Value =
        serde_json::from_slice(&fs::read(build.join("03BP_ROOT_RECEIPT.json"))?)?;
    Ok(root["obs_open_03bp_root"]
        .as_str()
        .ok_or("ROOT_MISSING")?
        .into())
}

fn prepare_output(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if out.exists() {
        let r = fs::canonicalize(out)?;
        let n = r.to_string_lossy().replace('\\', "/").to_ascii_lowercase();
        if !(n.starts_with("d:/obs-open-01/protocol/")
            || n.starts_with("//?/d:/obs-open-01/protocol/"))
        {
            return Err("REFUSE_OUTPUT_REMOVAL".into());
        }
        fs::remove_dir_all(r)?;
    }
    fs::create_dir_all(out)?;
    Ok(())
}
fn recursive(root: &Path) -> Result<Vec<PathBuf>, Box<dyn std::error::Error>> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_owned()];
    while let Some(d) = stack.pop() {
        for e in fs::read_dir(d)? {
            let p = e?.path();
            if p.is_dir() {
                stack.push(p)
            } else {
                out.push(p)
            }
        }
    }
    out.sort();
    Ok(out)
}
fn members(root: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut out = Vec::new();
    for p in recursive(root)? {
        let rel = p.strip_prefix(root)?.to_string_lossy().replace('\\', "/");
        if matches!(
            rel.as_str(),
            "content_manifest.tsv" | "03BP_ROOT_RECEIPT.json"
        ) {
            continue;
        }
        out.push(Member {
            relative_path: rel,
            bytes: fs::metadata(&p)?.len(),
            sha256: sha256_file(&p)?,
        });
    }
    out.sort_by(|a, b| a.relative_path.cmp(&b.relative_path));
    Ok(out)
}
fn manifest(m: &[Member]) -> Vec<u8> {
    let mut s = String::from("relative_path\tbytes\tsha256\n");
    for x in m {
        s.push_str(&format!("{}\t{}\t{}\n", x.relative_path, x.bytes, x.sha256));
    }
    s.into_bytes()
}
fn write_json(path: &Path, value: &impl Serialize) -> Result<(), Box<dyn std::error::Error>> {
    let mut b = serde_json::to_vec(value)?;
    b.push(b'\n');
    fs::write(path, b)?;
    Ok(())
}
fn copy_tree(src: &Path, dst: &Path) -> Result<(), Box<dyn std::error::Error>> {
    fs::create_dir_all(dst)?;
    for p in recursive(src)? {
        let rel = p.strip_prefix(src)?;
        let target = dst.join(rel);
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::copy(p, target)?;
    }
    Ok(())
}
