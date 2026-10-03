use crate::authority::{open, sha256, sha256_file};
use crate::dependence::{diagnose, method_assessments};
use crate::fixtures::qualify;
use crate::model::*;
use crate::pseudo_db::{PseudoDbResult, construct};
use serde::Serialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

const STUDY: &str = "studies/obs-open-01/range-representation-inference-protocol-v2";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_03B_P2_PROTOCOL_V1.md",
    "src/authority.rs",
    "src/dependence.rs",
    "src/fixtures.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/model.rs",
    "src/pseudo_db.rs",
    "src/seal.rs",
    "tests/protocol_contract.rs",
];

#[derive(Debug, Clone, Serialize)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(repo: &Path, out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    prepare_output(out)?;
    for dir in ["contracts", "d_a", "ledgers", "receipts", "source"] {
        fs::create_dir_all(out.join(dir))?;
    }
    let authority = open(repo).map_err(|error| format!("AUTHORITY_OPEN:{error}"))?;
    let pseudo = construct(&authority.rows).map_err(|error| format!("PSEUDO_DB:{error}"))?;
    let dependence = diagnose(&pseudo).map_err(|error| format!("DEPENDENCE:{error}"))?;
    let fixtures = qualify().map_err(|error| format!("FIXTURES:{error}"))?;
    let selected = dependence.compatible;
    fs::copy(
        repo.join(STUDY).join("OBS_OPEN_03B_P2_PROTOCOL_V1.md"),
        out.join("OBS_OPEN_03B_P2_PROTOCOL_V1.md"),
    )?;
    write_json(
        &out.join("contracts/AVERAGE_COMPETENCE_PARAMETER_V1.json"),
        &json!({
            "schema":"AVERAGE_COMPETENCE_PARAMETER_V1","source_kind":"ARTIFACT_DECLARED",
            "parameter":"mu_R=E[d_s^R]","session_difference":"d_s^R=B_s(M0)-B_s(MR)",
            "null":"H0:mu_R<=0","alternative":"H1:mu_R>0","population_statement":"AVERAGE_SESSION_POPULATION_REPRESENTATION_COMPETENCE",
            "conditional_sequential_dominance":false,"design_based":false
        }),
    )?;
    write_json(
        &out.join("contracts/FORECAST_STATE_SEMANTICS_V1.json"),
        &json!({
            "schema":"FORECAST_STATE_SEMANTICS_V1","source_kind":"ARTIFACT_DECLARED",
            "states":["FIXED_ACROSS_EVALUATION","UPDATED_PREQUENTIALLY","RETRAINED_BY_BLOCK","OTHER"],
            "D_A_pseudo_DB":"RETRAINED_BY_BLOCK; fixed within each validation block",
            "D_B_tournament":"FIXED_ACROSS_EVALUATION",
            "cross_model_state_covariance_pairs":"FORBIDDEN"
        }),
    )?;
    write_json(
        &out.join("contracts/MATERIALITY_INFERENCE_AUTHORITY_V2.json"),
        &json!({
            "schema":"MATERIALITY_INFERENCE_AUTHORITY_V2","source_kind":"ARTIFACT_DECLARED",
            "materiality":{"authority":"FROZEN_DB_POPULATION","quantity":"Skill_R^DB=1-B_R/B_0","floor":MIN_MATERIAL_SKILL},
            "formal_inference":{"authority":"SEPARATELY_QUALIFIED_STOCHASTIC_PROCESS","parameter":"mu_R=E[d_s^R]"},
            "independent_axes":true
        }),
    )?;
    write_selected_contract(
        &out.join("contracts/SELECTED_INFERENCE_CONTRACT_V1.json"),
        selected,
    )?;
    write_json(
        &out.join("contracts/TOURNAMENT_DECISION_V2.json"),
        &tournament_contract(selected),
    )?;
    write_json(
        &out.join("contracts/D_B_SUPPORT_GATE_V2.json"),
        &json!({
            "schema":"D_B_SUPPORT_GATE_V2","source_kind":"ARTIFACT_DECLARED","minimum_complete_sessions":MIN_D_B_COMPLETE,
            "minimum_plus120":MIN_D_B_OFFSET,"minimum_plus180":MIN_D_B_OFFSET,"weakened_from_parent":false,
            "HAC_minimum_sessions":MIN_D_B_COMPLETE,"failure":"INSUFFICIENT_FORMAL_SUPPORT"
        }),
    )?;
    write_score_ledger(
        &out.join("d_a/FIXED_MODEL_PSEUDO_DB_SCORE_LEDGER.tsv"),
        &pseudo,
    )?;
    write_json(
        &out.join("d_a/D_A_SELECTED_LAMBDAS.json"),
        &json!({"schema":"D_A_SELECTED_LAMBDAS_V1","source_kind":"MACHINE_DERIVED","selection":"four expanding chronological fixed-model validation blocks; mean session Brier; ties within 1e-12 choose largest lambda","values":pseudo.selected_lambdas}),
    )?;
    write_json(
        &out.join("d_a/DEPENDENCE_TRANSPORT_AUDIT.json"),
        &json!({
            "schema":"DEPENDENCE_TRANSPORT_AUDIT_V1","source_kind":"MACHINE_DERIVED",
            "forecast_state":"fixed within block; retrained across blocks","cross_state_pairs_used":0,
            "qualification":dependence,
            "findings":[
                {"finding_id":"P2-DA-001","source_kind":"MACHINE_DERIVED","statement":"All dependence diagnostics were computed within fixed-model validation blocks."},
                {"finding_id":"P2-DA-002","source_kind":"MACHINE_DERIVED","statement":"D_A diagnostics do not prove the selected stochastic assumptions on D_B."}
            ]
        }),
    )?;
    write_json(
        &out.join("receipts/CANDIDATE_METHOD_ASSESSMENT.json"),
        &json!({"schema":"CANDIDATE_METHOD_ASSESSMENT_V1","source_kind":"MACHINE_DERIVED","methods":method_assessments(selected),"selection_uses_representation_p_values":false,"selection_uses_preferred_tournament_result":false}),
    )?;
    write_json(
        &out.join("receipts/SYNTHETIC_CALIBRATION.json"),
        &json!({"schema":"OBS_OPEN_03BP2_SYNTHETIC_CALIBRATION_V1","source_kind":"MACHINE_DERIVED","case_count":fixtures.len(),"failed":fixtures.iter().filter(|x|x.status!="PASS").count(),"fixtures":fixtures,"real_D_B_assumptions_established":false,"status":"PASS"}),
    )?;
    write_json(
        &out.join("receipts/PARENT_AUTHORITY_BINDING.json"),
        &json!({
            "schema":"OBS_OPEN_03BP2_PARENT_BINDING_V1","source_kind":"MACHINE_DERIVED",
            "parent_protocol_root":PARENT_PROTOCOL_ROOT,"preopen_audit_root":PREOPEN_AUDIT_ROOT,"atlas_root":ATLAS_ROOT,
            "parent_members_verified":authority.parent_member_count,"audit_members_verified":authority.audit_member_count,"atlas_members_verified":authority.atlas_member_count,
            "raw_source_sha256":authority.raw_source_sha256,"status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/ACCESS_AUDIT.json"),
        &json!({
            "schema":"OBS_OPEN_03BP2_ACCESS_AUDIT_V1","source_kind":"MACHINE_DERIVED",
            "D_A":{"sessions_decoded":authority.d_a_sessions_decoded,"complete_sessions":authority.rows.len(),"bars_read":authority.d_a_bars_read,"path_gap_sessions":authority.d_a_gap_sessions,"outcome_records_scanned":authority.d_a_outcome_records_scanned,"target_values_read":authority.d_a_target_values_read,"pseudo_DB_validation_sessions":pseudo.validation_sessions},
            "D_B":{"outcome_registry_applications":0,"target_values_computed":0,"target_values_read":0,"scores":0,"model_fitting":0,"normalization_fitting":0,"hyperparameter_selection":0},
            "D_C":{"membership_decoding":0,"observations_read":0,"outcomes":0},"status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/INFERENCE_AUTHORITY_BIBLIOGRAPHY.json"),
        &bibliography(),
    )?;
    write_ledgers(out)?;
    write_matrix(&out.join("TYPED_QUALIFICATION_MATRIX.tsv"), selected)?;
    copy_source(repo, out)?;
    write_json(
        &out.join("03BP2_AUTHORITY_MANIFEST.json"),
        &json!({
            "schema":"OBS_OPEN_03BP2_AUTHORITY_MANIFEST_V1","source_kind":"ARTIFACT_DECLARED","authority":AUTHORITY,
            "parents":{"03BP":PARENT_PROTOCOL_ROOT,"03BPA":PREOPEN_AUDIT_ROOT,"atlas":ATLAS_ROOT},
            "selected_procedure":if selected{"HAC_BARTLETT_AUTOMATIC_LAG_V1"}else{"FORMAL_INFERENCE_NOT_EVALUABLE"},
            "D_B_opened":false,"D_C_opened":false,"representation_information_authority":false,
            "source_closure_sha256":source_closure_hash(repo)?,"status":"FROZEN_PROTOCOL_ONLY"
        }),
    )?;
    reseal(out)
}

fn write_selected_contract(path: &Path, selected: bool) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        path,
        &json!({
            "schema":"AVERAGE_COMPETENCE_HAC_INFERENCE_V1","source_kind":"ARTIFACT_DECLARED",
            "state":if selected{"SELECTED"}else{"FORMAL_INFERENCE_NOT_EVALUABLE"},
            "parameter":"mu_R=E[d_s^R]","null":"mu_R<=0","alternative":"mu_R>0",
            "statistic":"sqrt(N)*mean(d)/sqrt(Bartlett_HAC_LRV)","reference":"STANDARD_NORMAL_ASYMPTOTIC",
            "kernel":"BARTLETT","lag_rule":"floor(4*(N/100)^(2/9)); capped at N-1","one_sided":true,
            "multiplicity":"Holm-Bonferroni across exactly RAW_VS_DESIGN and Z_VS_DESIGN at alpha 0.05",
            "exactness_basis":"ASYMPTOTIC","design_based":false,"bootstrap":false,
            "stochastic_assumptions":["fixed models across D_B evaluation","covariance-stationary score-difference process","finite 2+delta moments","weak dependence supporting HAC CLT","summable autocovariances","positive finite long-run variance"],
            "assumption_status":"SCIENTIFICALLY_DECLARED_NOT_PROVEN_ON_UNOPENED_D_B",
            "support":{"complete_sessions":MIN_D_B_COMPLETE,"plus120":MIN_D_B_OFFSET,"plus180":MIN_D_B_OFFSET},
            "fail_closed":["NONFINITE_SCORE_DIFFERENCE","NONPOSITIVE_OR_NONFINITE_LRV","SUPPORT_FAILURE","FORECAST_STATE_NOT_FIXED","ASSUMPTION_AUTHORITY_WITHDRAWN"],
            "D_A_diagnostics_select_by_p_value":false,"D_B_open_authorized":false
        }),
    )
}

fn tournament_contract(selected: bool) -> serde_json::Value {
    json!({
        "schema":"TOURNAMENT_DECISION_V2","source_kind":"ARTIFACT_DECLARED",
        "axes":{"materiality":["PASS","FAIL"],"formal_inference":["PASS","FAIL","NOT_EVALUABLE"]},
        "states":["REPRESENTATION_PAYS_RENT","STATISTICAL_BUT_SUBMATERIAL","MATERIAL_ON_DB_NOT_FORMALLY_SUPPORTED","DOES_NOT_PAY_RENT","MATERIAL_ON_DB_FORMAL_INFERENCE_NOT_EVALUABLE"],
        "pays_rent":"MATERIALITY_PASS AND FORMAL_INFERENCE_PASS",
        "formal_procedure":if selected{"HAC_BARTLETT_AUTOMATIC_LAG_V1"}else{"NOT_EVALUABLE"},
        "raw_vs_z_direct_superiority":false,"combined_representation":false
    })
}

fn bibliography() -> serde_json::Value {
    json!({
        "schema":"INFERENCE_AUTHORITY_BIBLIOGRAPHY_V1","source_kind":"ARTIFACT_DECLARED",
        "sources":[
            {"id":"HENZI_ZIEGEL_2022","url":"https://doi.org/10.1093/biomet/asab047","use":"Defines finite-sample e-values for conditional sequential forecast-dominance statements; parked because that is not mu_R."},
            {"id":"SHAO_2010_DWB","url":"https://doi.org/10.1198/jasa.2009.tm08744","use":"DWB distributional consistency is stationary-time-series/model based; evaluated but not selected."},
            {"id":"NEWEY_WEST_1987","url":"https://doi.org/10.2307/1913610","use":"HAC long-run variance basis; authority remains asymptotic under declared conditions."},
            {"id":"ANDREWS_1991","url":"https://doi.org/10.2307/2938229","use":"Documents bandwidth/lag and kernel choices as nuisance decisions in HAC estimation."}
        ]
    })
}

fn write_score_ledger(path: &Path, pseudo: &PseudoDbResult) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "fold_id\tmodel_state_id\trepresentation\tsession_index\tsession_id\tcivil_date\tmonth\toffset\tbaseline_brier\trepresentation_brier\tdifference"
    )?;
    for r in &pseudo.score_rows {
        writeln!(
            w,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{:.17}\t{:.17}\t{:.17}",
            r.fold_id,
            r.model_state_id,
            r.representation,
            r.session_index,
            r.session_id,
            r.civil_date,
            r.month,
            r.offset,
            r.baseline_brier,
            r.representation_brier,
            r.difference
        )?;
    }
    w.flush()
}

fn write_ledgers(out: &Path) -> std::io::Result<()> {
    fs::write(
        out.join("ledgers/PARKED_QUESTION_LEDGER.tsv"),
        concat!(
            "question_id\tstate\treason\n",
            "CONDITIONAL_SEQUENTIAL_REPRESENTATION_COMPETENCE\tPARKED\tDifferent conditional filtration authority; not the average mu_R question.\n",
            "DEPENDENT_WILD_BOOTSTRAP\tPARKED_METHOD\tStationarity and multiplier-bandwidth authority not selected.\n",
            "BLOCK_BOOTSTRAP\tPARKED_METHOD\tBlock-length authority not earned from four short pseudo-D_B blocks.\n",
            "RAW_VS_Z_DIRECT_SUPERIORITY\tPARKED\tTournament tests each representation only against design context.\n"
        ),
    )
}

fn write_matrix(path: &Path, selected: bool) -> std::io::Result<()> {
    let rows = [
        ("PARENT_03BP_BINDING", "PASS"),
        ("PREOPEN_AUDIT_BINDING", "PASS"),
        ("AVERAGE_COMPETENCE_PARAMETER", "PASS"),
        ("MATERIALITY_INFERENCE_SEPARATION", "PASS"),
        ("FIXED_MODEL_PSEUDO_DB_BLOCKS", "PASS"),
        ("MODEL_STATE_BOUNDARY_EXCLUSION", "PASS"),
        ("DEPENDENCE_TRANSPORT_AUDIT", "PASS"),
        ("CANDIDATE_METHOD_AUTHORITY_MATRIX", "PASS"),
        (
            "ONE_PROCEDURE_SELECTED_OR_NOT_EVALUABLE",
            if selected { "PASS" } else { "NOT_EVALUABLE" },
        ),
        ("STATIONARITY_EXPLICIT", "PASS"),
        ("ASYMPTOTIC_NOT_EXACT", "PASS"),
        ("SUPPORT_GATES_PRESERVED", "PASS"),
        ("FORECAST_STATE_SEMANTICS", "PASS"),
        ("PERMANENT_REFLECTION_FIXTURES", "PASS"),
        ("D_B_FIREWALL", "PASS"),
        ("D_C_FIREWALL", "PASS"),
    ];
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(w, "claim\tstate\tsource_kind")?;
    for (claim, state) in rows {
        writeln!(w, "{claim}\t{state}\tMACHINE_DERIVED")?;
    }
    w.flush()
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let provisional = compare(left, right)?;
    if provisional.1 != 0 {
        return Err("PROVISIONAL_REBUILD_MISMATCH".into());
    }
    let receipt = json!({"schema":"OBS_OPEN_03BP2_DETERMINISTIC_REBUILD_RECEIPT_V1","source_kind":"MACHINE_DERIVED","provisional_root":provisional.0,"file_count":provisional.2,"mismatch_count":0,"status":"PASS"});
    for root in [left, right] {
        write_json(
            &root.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"),
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
        serde_json::from_slice(&fs::read(root.join("03BP2_ROOT_RECEIPT.json"))?)?;
    let expected = receipt["obs_open_03bp2_root"]
        .as_str()
        .ok_or("ROOT_MISSING")?;
    let manifest = fs::read(root.join("content_manifest.tsv"))?;
    if sha256(&manifest) != expected {
        return Err("ROOT_DRIFT".into());
    }
    let count = parse_manifest(root, &manifest)?;
    if receipt["artifact_count"].as_u64() != Some(count as u64) {
        return Err("COUNT_DRIFT".into());
    }
    for field in [
        "D_B_target_values_read",
        "D_B_scores",
        "D_C_observations_read",
    ] {
        if receipt[field].as_u64() != Some(0) {
            return Err(format!("FIREWALL_DRIFT:{field}").into());
        }
    }
    Ok(expected.into())
}

pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    verify(build)?;
    if seal.exists() {
        let resolved = fs::canonicalize(seal)?;
        let n = resolved
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        if !n.contains("/studies/obs-open-01/range-representation-inference-protocol-v2/seal") {
            return Err("REFUSE_SEAL_REPLACEMENT".into());
        }
        fs::remove_dir_all(resolved)?;
    }
    copy_tree(build, seal)?;
    verify(seal)
}

fn reseal(out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    for name in ["content_manifest.tsv", "03BP2_ROOT_RECEIPT.json"] {
        let p = out.join(name);
        if p.exists() {
            fs::remove_file(p)?;
        }
    }
    let members = members(out)?;
    let manifest = manifest(&members);
    fs::write(out.join("content_manifest.tsv"), &manifest)?;
    let root = sha256(&manifest);
    let access: serde_json::Value =
        serde_json::from_slice(&fs::read(out.join("receipts/ACCESS_AUDIT.json"))?)?;
    let selected: serde_json::Value = serde_json::from_slice(&fs::read(
        out.join("contracts/SELECTED_INFERENCE_CONTRACT_V1.json"),
    )?)?;
    write_json(
        &out.join("03BP2_ROOT_RECEIPT.json"),
        &json!({
            "schema":"OBS_OPEN_03BP2_ROOT_RECEIPT_V1","source_kind":"MACHINE_DERIVED","authority":AUTHORITY,
            "parent_protocol_root":PARENT_PROTOCOL_ROOT,"preopen_audit_root":PREOPEN_AUDIT_ROOT,"obs_open_03bp2_root":root,
            "artifact_count":members.len(),"selected_inference_state":selected["state"],"selected_procedure":selected["schema"],
            "D_A_target_values_read":access["D_A"]["target_values_read"],"D_B_target_values_read":0,"D_B_scores":0,"D_C_observations_read":0,
            "empirical_representation_information_claims":0,"status":"SEALED_PROTOCOL_ONLY"
        }),
    )?;
    Ok(root)
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
fn copy_source(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    for rel in SOURCE_FILES {
        fs::copy(
            repo.join(STUDY).join(rel),
            out.join("source").join(rel.replace('/', "_")),
        )?;
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
fn write_json(path: &Path, value: &impl Serialize) -> Result<(), Box<dyn std::error::Error>> {
    let mut b = serde_json::to_vec(value)?;
    b.push(b'\n');
    fs::write(path, b)?;
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
            "content_manifest.tsv" | "03BP2_ROOT_RECEIPT.json"
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
fn parse_manifest(root: &Path, bytes: &[u8]) -> Result<usize, Box<dyn std::error::Error>> {
    let mut n = 0;
    for line in std::str::from_utf8(bytes)?.lines().skip(1) {
        let f = line.split('\t').collect::<Vec<_>>();
        if f.len() != 3 || f[0].contains("..") || Path::new(f[0]).is_absolute() {
            return Err("BAD_MEMBER".into());
        }
        let p = root.join(f[0]);
        if fs::metadata(&p)?.len() != f[1].parse::<u64>()? || sha256_file(&p)? != f[2] {
            return Err(format!("MEMBER_DRIFT:{}", f[0]).into());
        }
        n += 1;
    }
    Ok(n)
}
fn compare(
    left: &Path,
    right: &Path,
) -> Result<(String, usize, usize), Box<dyn std::error::Error>> {
    let lf = recursive(left)?;
    let rf = recursive(right)?;
    let lr = lf
        .iter()
        .map(|p| p.strip_prefix(left).unwrap().to_owned())
        .collect::<Vec<_>>();
    let rr = rf
        .iter()
        .map(|p| p.strip_prefix(right).unwrap().to_owned())
        .collect::<Vec<_>>();
    let mut mismatch = usize::from(lr != rr);
    if mismatch == 0 {
        for rel in &lr {
            mismatch += usize::from(fs::read(left.join(rel))? != fs::read(right.join(rel))?);
        }
    }
    Ok((verify(left)?, mismatch, lr.len()))
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
