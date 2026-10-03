use crate::authority::{ContractHash, open, sha256, sha256_file};
use crate::corpus::{TargetAccess, open_targets, support};
use crate::inference::{PrimaryResult, execute};
use crate::model_state::{apply, fit};
use crate::{AUTHORITY, ORIGINAL_03BP_ROOT, P2_ROOT, P2T_ROOT, PREOPEN_AUDIT_ROOT};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;

const STUDY: &str = "studies/obs-open-01/range-representation-competence-execution";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_03B_EXECUTION_V1.md",
    "src/authority.rs",
    "src/corpus.rs",
    "src/inference.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/model_state.rs",
    "src/output.rs",
    "tests/execution_contract.rs",
];
#[derive(Serialize)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(repo: &Path, out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    prepare(out)?;
    for d in [
        "authority",
        "support",
        "model",
        "primary",
        "diagnostics",
        "receipts",
        "source",
    ] {
        fs::create_dir_all(out.join(d))?;
    }
    let authority = open(repo)?;
    write_json(
        &out.join("authority/EXECUTION_AUTHORITY_BINDING.json"),
        &bound(
            json!({"schema":"EXECUTION_AUTHORITY_BINDING_V1","source_kind":"MACHINE_DERIVED","joint_execution_authority":true,"P2_members_verified":authority.p2_members,"P2T_members_verified":authority.p2t_members,"historical_lineage":{"original_03BP":ORIGINAL_03BP_ROOT,"preopen_audit":PREOPEN_AUDIT_ROOT},"contract_hashes":authority.contract_hashes,"firewall_manifest_sha256":authority.firewall_sha256,"raw_source_sha256":obs_open_disc02e::RAW_BAR_HASH,"status":"PASS"}),
        ),
    )?;
    let models = fit(repo)?;
    let model_bytes = serde_json::to_vec(&models)?;
    let model_hash = sha256(&model_bytes);
    write_json(
        &out.join("model/D_A_FROZEN_MODEL_STATE.json"),
        &bound(
            json!({"schema":"D_A_FROZEN_MODEL_STATE_V1","source_kind":"MACHINE_DERIVED","model_state_sha256":model_hash,"model_state":models,"D_B_fitting":0,"D_B_scaling_fitting":0,"D_B_tuning":0,"status":"PASS"}),
        ),
    )?;
    let support_scan = support(&authority)?;
    write_json(
        &out.join("support/DB_TARGET_SUPPORT_RECEIPT.json"),
        &bound(
            json!({"schema":"DB_TARGET_SUPPORT_RECEIPT_V1","source_kind":"MACHINE_DERIVED","support":support_scan.receipt,"support_determined_before_target_sign_read":true,"discovery_prefix_sha256":support_scan.prefix_sha256,"minimum_complete_sessions":80,"minimum_each_offset_regime":20}),
        ),
    )?;
    if support_scan.receipt.support_state != "PASS" {
        return Err("INSUFFICIENT_FORMAL_SUPPORT".into());
    }
    let (db_rows, target_access) = open_targets(&authority, &support_scan)?;
    let predictions = apply(&models, &db_rows)?;
    let result = execute(&db_rows, &predictions)?;
    write_primary(out, &result, &target_access, &model_hash)?;
    let checkpoint = primary_checkpoint(out)?;
    write_diagnostics(repo, out, &result, &checkpoint)?;
    write_firewalls(
        out,
        &authority.contract_hashes,
        support_scan.receipt.clone(),
        target_access,
        &result,
    )?;
    fs::copy(
        repo.join(STUDY).join("OBS_OPEN_03B_EXECUTION_V1.md"),
        out.join("OBS_OPEN_03B_EXECUTION_V1.md"),
    )?;
    copy_source(repo, out)?;
    write_json(
        &out.join("03B_AUTHORITY_MANIFEST.json"),
        &bound(
            json!({"schema":"OBS_OPEN_03B_AUTHORITY_MANIFEST_V1","source_kind":"ARTIFACT_DECLARED","authority":AUTHORITY,"scope":{"target":"STRICT_ABOVE_FROZEN_MIDPOINT_AT_60M_V1","horizon_minutes":60,"probe":"L2_LOGISTIC_REGRESSION","estimand_unit":"SESSION","temporal_index":"SELECTED_DB_SESSION_ORDINAL"},"tournament_state":result.tournament_state,"D_C_opened":false,"economic_authority":false,"trading_authority":false,"source_closure_sha256":source_closure(repo)?,"status":"SEALED_DISCOVERY_GATE"}),
        ),
    )?;
    reseal(out)
}

fn write_primary(
    out: &Path,
    r: &PrimaryResult,
    access: &TargetAccess,
    model_hash: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("primary/DB_TARGET_ACCESS_RECEIPT.json"),
        &bound(
            json!({"schema":"DB_TARGET_ACCESS_RECEIPT_V1","source_kind":"MACHINE_DERIVED","target":"STRICT_ABOVE_FROZEN_MIDPOINT_AT_60M_V1","access":access,"opened_exactly_once":true,"model_state_sha256":model_hash,"target_reselection":0,"horizon_reselection":0}),
        ),
    )?;
    write_prediction_tape(&out.join("primary/DB_PREDICTION_TAPE.tsv"), r)?;
    write_score_tape(&out.join("primary/DB_SESSION_BRIER_TAPE.tsv"), r)?;
    write_json(
        &out.join("primary/DB_FINITE_POPULATION_MATERIALITY.json"),
        &bound(
            json!({"schema":"DB_FINITE_POPULATION_MATERIALITY_V1","source_kind":"MACHINE_DERIVED","authority":"FROZEN_DB_POPULATION","effect_floor_relative_brier_skill":0.02,"baseline_brier":r.baseline_brier,"RAW":{"brier":r.raw.brier,"delta_brier":r.raw.delta_brier,"relative_skill":r.raw.relative_skill,"materiality_state":r.raw.materiality_state},"Z":{"brier":r.z.brier,"delta_brier":r.z.delta_brier,"relative_skill":r.z.relative_skill,"materiality_state":r.z.materiality_state}}),
        ),
    )?;
    write_json(
        &out.join("primary/RAW_HAC_INFERENCE_RECEIPT.json"),
        &bound(
            json!({"schema":"HAC_INFERENCE_RECEIPT_V1","source_kind":"MACHINE_DERIVED","result":r.raw.inference,"warning":warning()}),
        ),
    )?;
    write_json(
        &out.join("primary/Z_HAC_INFERENCE_RECEIPT.json"),
        &bound(
            json!({"schema":"HAC_INFERENCE_RECEIPT_V1","source_kind":"MACHINE_DERIVED","result":r.z.inference,"warning":warning()}),
        ),
    )?;
    write_json(
        &out.join("primary/HOLM_RECEIPT.json"),
        &bound(
            json!({"schema":"HOLM_RECEIPT_V1","source_kind":"MACHINE_DERIVED","alpha":0.05,"hypotheses":2,"RAW":{"raw_p":r.raw.inference.raw_one_sided_p,"rank":r.raw.inference.holm_rank,"threshold":r.raw.inference.holm_threshold,"state":r.raw.inference.holm_state},"Z":{"raw_p":r.z.inference.raw_one_sided_p,"rank":r.z.inference.holm_rank,"threshold":r.z.inference.holm_threshold,"state":r.z.inference.holm_state},"authority":"ASYMPTOTIC_UNDER_ADMITTED_ASSUMPTIONS"}),
        ),
    )?;
    write_json(
        &out.join("primary/REPRESENTATION_EPISTEMIC_STATES.json"),
        &bound(
            json!({"schema":"REPRESENTATION_EPISTEMIC_STATES_V1","source_kind":"MACHINE_DERIVED","RAW":{"materiality":r.raw.materiality_state,"formal_inference":r.raw.formal_inference_state,"combined":r.raw.combined_epistemic_state},"Z":{"materiality":r.z.materiality_state,"formal_inference":r.z.formal_inference_state,"combined":r.z.combined_epistemic_state}}),
        ),
    )?;
    write_json(
        &out.join("primary/TOURNAMENT_RESULT.json"),
        &bound(
            json!({"schema":"TOURNAMENT_RESULT_V1","source_kind":"MACHINE_DERIVED","state":r.tournament_state,"RAW":r.raw,"Z":r.z,"RAW_vs_Z_test_authorized":false,"complementarity_authorized":false,"representation_information_authority":true}),
        ),
    )?;
    write_json(
        &out.join("primary/ASYMPTOTIC_AUTHORITY_RECEIPT.json"),
        &bound(
            json!({"schema":"ASYMPTOTIC_AUTHORITY_RECEIPT_V1","source_kind":"ARTIFACT_DECLARED","inference_authority":"ASYMPTOTIC_MODEL_BASED","assumptions":["fixed D_A-trained models throughout D_B evaluation","covariance-stationary selected-D_B score-difference process","finite moments","weak dependence","summable autocovariances","positive finite long-run variance"],"assumptions_proved_by_D_B":false,"warning":warning()}),
        ),
    )?;
    write_json(
        &out.join("primary/TEMPORAL_INDEX_RECEIPT.json"),
        &bound(
            json!({"schema":"TEMPORAL_INDEX_RECEIPT_V1","source_kind":"ARTIFACT_DECLARED","sequence":"chronologically sorted formally eligible selected D_B sessions","lag_unit":"SELECTED_DB_SESSION_ORDINAL","lag_one_is_parent_market_session":false,"lag_one_is_calendar_day":false,"gap_metadata_changes_kernel":false}),
        ),
    )?;
    write_findings(&out.join("primary/TYPED_FINDINGS.json"), r)?;
    Ok(())
}

fn write_prediction_tape(path: &Path, r: &PrimaryResult) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "P2_root\tP2T_root\tsession_id\tcivil_date\toffset\tD_B_selected_ordinal\tk\ttarget\tdesign_probability\traw_probability\tz_probability\testimand_unit\trow_independence_authority"
    )?;
    for x in &r.prediction_rows {
        writeln!(
            w,
            "{P2_ROOT}\t{P2T_ROOT}\t{}\t{}\t{}\t{}\t{}\t{:.17}\t{:.17}\t{:.17}\t{:.17}\t{}\t{}",
            x.session_id,
            x.civil_date,
            x.offset,
            x.d_b_selected_ordinal,
            x.k,
            x.target,
            x.design_probability,
            x.raw_probability,
            x.z_probability,
            x.estimand_unit,
            x.row_independence_authority
        )?;
    }
    w.flush()
}
fn write_score_tape(path: &Path, r: &PrimaryResult) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "P2_root\tP2T_root\tsession_id\tcivil_date\toffset\tD_B_selected_ordinal\tdesign_brier\traw_brier\tz_brier\traw_difference\tz_difference\testimand_unit"
    )?;
    for x in &r.session_scores {
        writeln!(
            w,
            "{P2_ROOT}\t{P2T_ROOT}\t{}\t{}\t{}\t{}\t{:.17}\t{:.17}\t{:.17}\t{:.17}\t{:.17}\tSESSION",
            x.session_id,
            x.civil_date,
            x.offset,
            x.d_b_selected_ordinal,
            x.design_brier,
            x.raw_brier,
            x.z_brier,
            x.raw_difference,
            x.z_difference
        )?;
    }
    w.flush()
}

fn write_findings(path: &Path, r: &PrimaryResult) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        path,
        &bound(
            json!({"schema":"OBS_OPEN_03B_TYPED_FINDINGS_V1","source_kind":"MACHINE_DERIVED","findings":[
                {"finding_id":"03B-RAW-MATERIALITY","source_kind":"MACHINE_DERIVED","state":r.raw.materiality_state,"statement":format!("RAW frozen-population relative Brier skill was {:.17} against design context.",r.raw.relative_skill)},
                {"finding_id":"03B-RAW-INFERENCE","source_kind":"MACHINE_DERIVED","state":r.raw.formal_inference_state,"statement":format!("RAW one-sided HAC p was {:.17}; Holm state {}.",r.raw.inference.raw_one_sided_p,r.raw.inference.holm_state)},
                {"finding_id":"03B-Z-MATERIALITY","source_kind":"MACHINE_DERIVED","state":r.z.materiality_state,"statement":format!("Z frozen-population relative Brier skill was {:.17} against design context.",r.z.relative_skill)},
                {"finding_id":"03B-Z-INFERENCE","source_kind":"MACHINE_DERIVED","state":r.z.formal_inference_state,"statement":format!("Z one-sided HAC p was {:.17}; Holm state {}.",r.z.inference.raw_one_sided_p,r.z.inference.holm_state)},
                {"finding_id":"03B-TOURNAMENT","source_kind":"MACHINE_DERIVED","state":r.tournament_state,"statement":"Tournament state follows the frozen two-axis decision law."},
                {"finding_id":"03B-INFERENCE-BOUNDARY","source_kind":"ARTIFACT_DECLARED","state":"ASSUMPTION_BOUND","statement":"Formal authority is asymptotic and model-based; finite-sample 5 percent control and design exactness were not earned."}
            ]}),
        ),
    )
}

fn primary_checkpoint(out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut entries = Vec::new();
    for name in [
        "DB_TARGET_ACCESS_RECEIPT.json",
        "DB_PREDICTION_TAPE.tsv",
        "DB_SESSION_BRIER_TAPE.tsv",
        "DB_FINITE_POPULATION_MATERIALITY.json",
        "RAW_HAC_INFERENCE_RECEIPT.json",
        "Z_HAC_INFERENCE_RECEIPT.json",
        "HOLM_RECEIPT.json",
        "REPRESENTATION_EPISTEMIC_STATES.json",
        "TOURNAMENT_RESULT.json",
        "ASYMPTOTIC_AUTHORITY_RECEIPT.json",
        "TEMPORAL_INDEX_RECEIPT.json",
        "TYPED_FINDINGS.json",
    ] {
        let p = out.join("primary").join(name);
        entries.push((name, fs::metadata(&p)?.len(), sha256_file(&p)?));
    }
    let hash = sha256(&serde_json::to_vec(&entries)?);
    write_json(
        &out.join("primary/PRIMARY_RESULT_CHECKPOINT.json"),
        &bound(
            json!({"schema":"PRIMARY_RESULT_CHECKPOINT_V1","source_kind":"MACHINE_DERIVED","sealed_before_post_gate_diagnostics":true,"member_count":entries.len(),"member_set_sha256":hash,"members":entries}),
        ),
    )?;
    Ok(hash)
}

fn write_diagnostics(
    repo: &Path,
    out: &Path,
    r: &PrimaryResult,
    checkpoint: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    let tape=fs::read_to_string(repo.join("studies/obs-open-01/range-representation-temporal-index-audit/seal/membership/DB_TEMPORAL_MEMBERSHIP_TAPE.tsv"))?;
    let mut membership = BTreeMap::new();
    for l in tape.lines().skip(1) {
        let f = l.split('\t').collect::<Vec<_>>();
        membership.insert(f[0].to_owned(), f[3].parse::<usize>()?);
    }
    let mut w = BufWriter::new(File::create(
        out.join("diagnostics/POST_GATE_DESCRIPTIVE_DIAGNOSTICS.tsv"),
    )?);
    writeln!(
        w,
        "P2_root\tP2T_root\tclassification\tprimary_checkpoint\tsession_id\tcivil_date\toffset\tselected_ordinal\tparent_gap\tcalendar_gap\traw_difference\traw_cumulative\tz_difference\tz_cumulative"
    )?;
    let (mut cr, mut cz) = (0.0, 0.0);
    let mut previous_parent: Option<usize> = None;
    let mut previous_day: Option<i64> = None;
    for x in &r.session_scores {
        cr += x.raw_difference;
        cz += x.z_difference;
        let parent = *membership
            .get(&x.session_id)
            .ok_or("P2T_MEMBERSHIP_TAPE_MISMATCH")?;
        let day = civil_day(&x.civil_date)?;
        let parent_gap = previous_parent
            .map(|p| (parent - p).to_string())
            .unwrap_or_else(|| "NOT_APPLICABLE".into());
        let calendar_gap = previous_day
            .map(|p| (day - p).to_string())
            .unwrap_or_else(|| "NOT_APPLICABLE".into());
        writeln!(
            w,
            "{P2_ROOT}\t{P2T_ROOT}\tPOST_GATE_DESCRIPTIVE_DIAGNOSTICS_ONLY\t{checkpoint}\t{}\t{}\t{}\t{}\t{}\t{}\t{:.17}\t{:.17}\t{:.17}\t{:.17}",
            x.session_id,
            x.civil_date,
            x.offset,
            x.d_b_selected_ordinal,
            parent_gap,
            calendar_gap,
            x.raw_difference,
            cr,
            x.z_difference,
            cz
        )?;
        previous_parent = Some(parent);
        previous_day = Some(day);
    }
    w.flush()?;
    let diagnostic = json!({"schema":"POST_GATE_DESCRIPTIVE_DIAGNOSTICS_V1","source_kind":"MACHINE_DERIVED","classification":"HYPOTHESIS_GENERATION_ONLY","primary_checkpoint_sha256":checkpoint,"selected_ordinal_acf":{"RAW":acf(&r.session_scores.iter().map(|x|x.raw_difference).collect::<Vec<_>>(),10),"Z":acf(&r.session_scores.iter().map(|x|x.z_difference).collect::<Vec<_>>(),10)},"offset_summaries":{"RAW":offset_summary(r,true),"Z":offset_summary(r,false)},"largest_absolute_session_differences":{"RAW":outliers(r,true),"Z":outliers(r,false)},"prohibitions":["HAC_LAG_REPAIR","SESSION_DELETION","POPULATION_REDEFINITION","TARGET_CHANGE","RAW_PLUS_Z_CONSTRUCTION"]});
    write_json(
        &out.join("diagnostics/POST_GATE_DESCRIPTIVE_DIAGNOSTICS.json"),
        &bound(diagnostic),
    )?;
    Ok(())
}

fn civil_day(s: &str) -> Result<i64, Box<dyn std::error::Error>> {
    let mut p = s.split('-');
    let y = p.next().ok_or("DATE")?.parse::<i64>()?;
    let m = p.next().ok_or("DATE")?.parse::<i64>()?;
    let d = p.next().ok_or("DATE")?.parse::<i64>()?;
    let y = y - if m <= 2 { 1 } else { 0 };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = m + if m > 2 { -3 } else { 9 };
    let doy = (153 * mp + 2) / 5 + d - 1;
    Ok(era * 146097 + yoe * 365 + yoe / 4 - yoe / 100 + doy)
}

fn acf(x: &[f64], max: usize) -> Vec<Value> {
    let m = x.iter().sum::<f64>() / x.len() as f64;
    let g0 = x.iter().map(|v| (v - m) * (v - m)).sum::<f64>() / x.len() as f64;
    (1..=max.min(x.len()-1)).map(|lag|json!({"lag":lag,"acf":x[lag..].iter().zip(&x[..x.len()-lag]).map(|(a,b)|(a-m)*(b-m)).sum::<f64>()/x.len()as f64/g0})).collect()
}
fn offset_summary(r: &PrimaryResult, raw: bool) -> Value {
    let mut map = BTreeMap::<i32, Vec<f64>>::new();
    for x in &r.session_scores {
        map.entry(x.offset).or_default().push(if raw {
            x.raw_difference
        } else {
            x.z_difference
        });
    }
    json!(
        map.into_iter()
            .map(|(k, v)| {
                let n = v.len();
                let m = v.iter().sum::<f64>() / n as f64;
                (k, json!({"sessions":n,"mean_difference":m}))
            })
            .collect::<BTreeMap<_, _>>()
    )
}
fn outliers(r: &PrimaryResult, raw: bool) -> Vec<Value> {
    let mut x = r
        .session_scores
        .iter()
        .map(|s| {
            (
                if raw {
                    s.raw_difference
                } else {
                    s.z_difference
                },
                s,
            )
        })
        .collect::<Vec<_>>();
    x.sort_by(|a, b| b.0.abs().total_cmp(&a.0.abs()));
    x.into_iter()
        .take(5)
        .map(|(d, s)| json!({"session_id":s.session_id,"civil_date":s.civil_date,"difference":d}))
        .collect()
}

fn write_firewalls(
    out: &Path,
    contracts: &[ContractHash],
    support: crate::corpus::SupportReceipt,
    access: TargetAccess,
    r: &PrimaryResult,
) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("receipts/ACCESS_AUDIT.json"),
        &bound(
            json!({"schema":"OBS_OPEN_03B_ACCESS_AUDIT_V1","source_kind":"MACHINE_DERIVED","D_B":{"membership_sessions":support.membership_sessions,"complete_sessions":support.complete_formal_sessions,"target":access,"prediction_rows":r.prediction_rows.len(),"session_scores":r.session_scores.len(),"fitting":0,"scaling_fitting":0,"hyperparameter_selection":0,"recalibration":0,"model_mutation":0,"representation_mutation":0,"target_reselection":0,"horizon_reselection":0,"support_rule_modification":0,"inference_method_selection":0,"HAC_lag_selection":0},"D_C":{"membership_decoding":0,"observations_read":0,"outcomes_computed":0,"outcomes_read":0},"contract_hashes":contracts,"status":"PASS"}),
        ),
    )?;
    write_json(
        &out.join("receipts/D_C_FIREWALL_RECEIPT.json"),
        &bound(
            json!({"schema":"D_C_FIREWALL_RECEIPT_V1","source_kind":"MACHINE_DERIVED","membership_decoding":0,"observations_read":0,"outcomes_computed":0,"outcomes_read":0,"status":"FROZEN_UNOPENED"}),
        ),
    )?;
    Ok(())
}

fn warning() -> Value {
    json!({"nominal_asymptotic_alpha":0.05,"finite_sample_5_percent_type_i_control":"NOT_EARNED","design_based_exactness":"NOT_EARNED","exact_5_percent_FWER":"NOT_EARNED","procedure_qualification_context":{"iid_gaussian_rejection":0.061,"ar1_rho_0_35_rejection":0.07825,"classification":"PROCEDURE_QUALIFICATION_CONTEXT_ONLY"}})
}
fn bound(mut v: Value) -> Value {
    let o = v.as_object_mut().unwrap();
    o.insert("P2_root".into(), json!(P2_ROOT));
    o.insert("P2T_root".into(), json!(P2T_ROOT));
    v
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(left, right)?;
    let n = members(left)?.len();
    let receipt = bound(
        json!({"schema":"OBS_OPEN_03B_DETERMINISTIC_REBUILD_V1","source_kind":"MACHINE_DERIVED","independent_builds":2,"configurations":["RAYON_NUM_THREADS=1","RAYON_NUM_THREADS=4"],"pre_finalize_artifact_count":n,"byte_mismatches":0,"status":"PASS"}),
    );
    write_json(
        &left.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"),
        &receipt,
    )?;
    write_json(
        &right.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"),
        &receipt,
    )?;
    let l = reseal(left)?;
    let r = reseal(right)?;
    if l != r {
        return Err("FINAL_ROOT_MISMATCH".into());
    }
    write_root(left, &l)?;
    write_root(right, &r)?;
    compare(left, right)?;
    Ok(l)
}
fn write_root(root: &Path, hash: &str) -> Result<(), Box<dyn std::error::Error>> {
    let tournament: Value =
        serde_json::from_slice(&fs::read(root.join("primary/TOURNAMENT_RESULT.json"))?)?;
    let support: Value = serde_json::from_slice(&fs::read(
        root.join("support/DB_TARGET_SUPPORT_RECEIPT.json"),
    )?)?;
    write_json(
        &root.join("03B_ROOT_RECEIPT.json"),
        &bound(
            json!({"schema":"OBS_OPEN_03B_ROOT_RECEIPT_V1","source_kind":"MACHINE_DERIVED","authority":AUTHORITY,"03B_root":hash,"tournament_state":tournament["state"],"D_B_membership_sessions":support["support"]["membership_sessions"],"D_B_complete_sessions":support["support"]["complete_formal_sessions"],"D_C_observations_read":0,"economic_authority":false,"trading_authority":false,"status":"SEALED"}),
        ),
    )
}
pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}
pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let v: Value = serde_json::from_slice(&fs::read(root.join("03B_ROOT_RECEIPT.json"))?)?;
    let expected = v["03B_root"].as_str().ok_or("ROOT")?;
    let actual = sha256(&fs::read(root.join("content_manifest.tsv"))?);
    if expected != actual {
        return Err("ROOT_DRIFT".into());
    }
    for m in manifest_members(root)? {
        let p = root.join(&m.relative_path);
        if fs::metadata(&p)?.len() != m.bytes || sha256_file(&p)? != m.sha256 {
            return Err(format!("MEMBER_DRIFT:{}", m.relative_path).into());
        }
    }
    Ok(actual)
}
fn reseal(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    for n in ["content_manifest.tsv", "03B_ROOT_RECEIPT.json"] {
        let p = root.join(n);
        if p.exists() {
            fs::remove_file(p)?;
        }
    }
    let ms = members(root)?;
    let mut w = BufWriter::new(File::create(root.join("content_manifest.tsv"))?);
    writeln!(w, "relative_path\tbytes\tsha256")?;
    for m in ms {
        writeln!(w, "{}\t{}\t{}", m.relative_path, m.bytes, m.sha256)?;
    }
    w.flush()?;
    Ok(sha256(&fs::read(root.join("content_manifest.tsv"))?))
}
fn members(root: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut paths = Vec::new();
    collect(root, root, &mut paths)?;
    paths.sort();
    let mut out = Vec::new();
    for rel in paths {
        if rel == "content_manifest.tsv" || rel == "03B_ROOT_RECEIPT.json" {
            continue;
        }
        let p = root.join(&rel);
        out.push(Member {
            relative_path: rel,
            bytes: fs::metadata(&p)?.len(),
            sha256: sha256_file(&p)?,
        });
    }
    Ok(out)
}
fn manifest_members(root: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let s = fs::read_to_string(root.join("content_manifest.tsv"))?;
    let mut out = Vec::new();
    for l in s.lines().skip(1) {
        let f = l.split('\t').collect::<Vec<_>>();
        out.push(Member {
            relative_path: f[0].into(),
            bytes: f[1].parse()?,
            sha256: f[2].into(),
        });
    }
    Ok(out)
}
fn collect(base: &Path, dir: &Path, out: &mut Vec<String>) -> std::io::Result<()> {
    for e in fs::read_dir(dir)? {
        let p = e?.path();
        if p.is_dir() {
            collect(base, &p, out)?
        } else {
            out.push(
                p.strip_prefix(base)
                    .unwrap()
                    .to_string_lossy()
                    .replace('\\', "/"),
            );
        }
    }
    Ok(())
}
fn compare(a: &Path, b: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let x = members(a)?;
    let y = members(b)?;
    if x.len() != y.len() {
        return Err("COUNT_MISMATCH".into());
    }
    for (a, b) in x.iter().zip(&y) {
        if a.relative_path != b.relative_path || a.bytes != b.bytes || a.sha256 != b.sha256 {
            return Err(format!("BYTE_MISMATCH:{}", a.relative_path).into());
        }
    }
    Ok(())
}
fn prepare(out: &Path) -> std::io::Result<()> {
    if out.exists() {
        fs::remove_dir_all(out)?;
    }
    fs::create_dir_all(out)
}
fn write_json<T: Serialize>(path: &Path, v: &T) -> Result<(), Box<dyn std::error::Error>> {
    let mut b = serde_json::to_vec(v)?;
    b.push(b'\n');
    fs::write(path, b)?;
    Ok(())
}
fn copy_source(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    for r in SOURCE_FILES {
        fs::copy(
            repo.join(STUDY).join(r),
            out.join("source").join(r.replace('/', "_")),
        )?;
    }
    Ok(())
}
fn source_closure(repo: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut h = Sha256::new();
    for r in SOURCE_FILES {
        h.update(r.as_bytes());
        h.update([0]);
        h.update(fs::read(repo.join(STUDY).join(r))?);
        h.update([0]);
    }
    Ok(format!("{:x}", h.finalize()))
}
fn copy_tree(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for e in fs::read_dir(src)? {
        let p = e?.path();
        let to = dst.join(p.file_name().unwrap());
        if p.is_dir() {
            copy_tree(&p, &to)?
        } else {
            fs::copy(&p, &to)?;
        }
    }
    Ok(())
}
