use crate::anatomy::{AnatomyProducts, MultiplicityRow};
use crate::authority::{AtlasAuthority, sha256, sha256_file};
use crate::model::{AUTHORITY, PARENT_ROOT, PersistenceRow, SurfaceRow, WidthRow};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

const STUDY: &str = "studies/obs-open-01/future-process-atlas-inspection";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RebuildReceipt {
    pub schema: String,
    pub left_root: String,
    pub right_root: String,
    pub artifact_count: usize,
    pub mismatch_count: usize,
    pub status: String,
}

#[derive(Debug, Clone, Serialize)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn write_products(
    repository: &Path,
    out: &Path,
    parent: &AtlasAuthority,
    products: &AnatomyProducts,
) -> Result<String, Box<dyn std::error::Error>> {
    prepare_output(out)?;
    for dir in ["anatomy", "receipts"] {
        fs::create_dir_all(out.join(dir))?;
    }
    write_persistence(
        &out.join("anatomy/persistence_anatomy.tsv"),
        &products.persistence,
    )?;
    write_multiplicity(
        &out.join("anatomy/multiplicity_persistence_raw_axis.tsv"),
        &products.multiplicity_raw,
    )?;
    write_multiplicity(
        &out.join("anatomy/multiplicity_persistence_quartiles.tsv"),
        &products.multiplicity_quartiles,
    )?;
    write_surfaces(
        &out.join("anatomy/range_coordinate_anatomy.tsv"),
        &products.range_surfaces,
        false,
    )?;
    write_surfaces(
        &out.join("anatomy/range_iso_evaluation_time.tsv"),
        &products.range_surfaces,
        true,
    )?;
    write_surfaces(
        &out.join("anatomy/path_variation_control.tsv"),
        &products.path_variation_surfaces,
        false,
    )?;
    write_support(&out.join("anatomy/support_surface.tsv"), products)?;
    write_widths(&out.join("anatomy/range_width_by_k.tsv"), &products.widths)?;
    write_identifiability(&out.join("IDENTIFIABILITY_LEDGER.tsv"))?;
    write_questions(&out.join("QUESTION_GEN_LEDGER.tsv"))?;
    write_findings(&out.join("TYPED_DESCRIPTIVE_FINDINGS.json"), products)?;
    write_receipts(repository, out, parent, products)?;
    let members = members(out)?;
    let manifest = manifest(&members);
    fs::write(out.join("content_manifest.tsv"), &manifest)?;
    let root = sha256(&manifest);
    write_json(
        &out.join("OBS_OPEN_03AI_ROOT_RECEIPT.json"),
        &json!({
            "schema":"OBS_OPEN_03AI_ROOT_RECEIPT_V1",
            "authority":AUTHORITY,
            "authority_class":"DESCRIPTIVE_INSPECTION_SUPPLEMENT_ONLY",
            "parent_atlas_root":PARENT_ROOT,
            "obs_open_03ai_root":root,
            "artifact_count":members.len(),
            "D_A_parent_records_read":parent.records().len(),
            "D_B_outcome_applications":0,
            "D_B_reads":0,
            "D_C_reads":0,
            "formal_tests":0,
            "promotions":0,
            "new_outcome_families":0,
            "status":"PASS"
        }),
    )?;
    Ok(root)
}

fn write_persistence(path: &Path, rows: &[PersistenceRow]) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "age_minutes\tsampling_unit\tat_risk_anchors\tcontributing_sessions\tobserved_supersessions\tright_censored\tsession_terminated\tsource_path_incomplete\tnot_evaluable\tat_risk_mass\tevent_mass\tcensor_mass\tsurvival\tconditional_hazard"
    )?;
    for r in rows {
        writeln!(
            w,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{:.17}\t{:.17}\t{:.17}\t{:.17}\t{:.17}",
            r.age_minutes,
            r.sampling_unit,
            r.at_risk_anchors,
            r.contributing_sessions,
            r.observed_supersessions,
            r.right_censored,
            r.session_terminated,
            r.source_path_incomplete,
            r.not_evaluable,
            r.at_risk_mass,
            r.event_mass,
            r.censor_mass,
            r.survival,
            r.conditional_hazard
        )?;
    }
    w.flush()
}

fn write_multiplicity(path: &Path, rows: &[MultiplicityRow]) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "stratum_kind\tstratum_value\tretrospective_context\tcausal_at_candidate_birth\tage_minutes\tsampling_unit\tsessions_in_stratum\tcandidate_anchors_in_stratum\tat_risk_anchors\tcontributing_sessions\tobserved_supersessions\tsession_terminated\tsource_path_incomplete\tsurvival\tconditional_hazard"
    )?;
    for r in rows {
        writeln!(
            w,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{:.17}\t{:.17}",
            r.stratum_kind,
            r.stratum_value,
            r.retrospective_context,
            r.causal_at_candidate_birth,
            r.age_minutes,
            r.sampling_unit,
            r.sessions_in_stratum,
            r.candidate_anchors_in_stratum,
            r.at_risk_anchors,
            r.contributing_sessions,
            r.observed_supersessions,
            r.session_terminated,
            r.source_path_incomplete,
            r.survival,
            r.conditional_hazard
        )?;
    }
    w.flush()
}

fn write_surfaces(path: &Path, rows: &[SurfaceRow], iso_order: bool) -> std::io::Result<()> {
    let mut refs: Vec<_> = rows.iter().collect();
    if iso_order {
        refs.sort_by_key(|r| {
            (
                r.evaluation_minute_after_open,
                r.k,
                r.horizon_minutes,
                r.outcome_code,
                r.representation.clone(),
                r.sampling_unit.clone(),
            )
        });
    }
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "outcome_code\trepresentation\tk\tfreeze_minute_after_open\thorizon_minutes\tevaluation_minute_after_open\tiso_evaluation_coordinate\tsampling_unit\tobserved_complete\tcontributing_sessions\tright_censored\tsession_terminated\tsource_path_incomplete\tnot_evaluable\tq10\tq25\tq50\tq75\tq90\tmean"
    )?;
    for r in refs {
        writeln!(
            w,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
            r.outcome_code,
            r.representation,
            r.k,
            r.freeze_minute_after_open,
            r.horizon_minutes,
            r.evaluation_minute_after_open,
            r.evaluation_minute_after_open,
            r.sampling_unit,
            r.observed_complete,
            r.contributing_sessions,
            r.right_censored,
            r.session_terminated,
            r.source_path_incomplete,
            r.not_evaluable,
            opt(r.q10),
            opt(r.q25),
            opt(r.q50),
            opt(r.q75),
            opt(r.q90),
            opt(r.mean)
        )?;
    }
    w.flush()
}

fn write_support(path: &Path, p: &AnatomyProducts) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "surface_family\toutcome_code\trepresentation\tk\thorizon_minutes\tevaluation_minute_after_open\tsampling_unit\teligible_anchors\tcontributing_sessions\thorizon_complete\tright_censored\tsession_terminated\tsource_path_incomplete\tnot_evaluable"
    )?;
    for (family, rows) in [
        ("RANGE_COORDINATE", &p.range_surfaces),
        ("PATH_VARIATION_CONTROL", &p.path_variation_surfaces),
    ] {
        for r in rows {
            writeln!(
                w,
                "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
                family,
                r.outcome_code,
                r.representation,
                r.k,
                r.horizon_minutes,
                r.evaluation_minute_after_open,
                r.sampling_unit,
                r.observed_complete
                    + r.right_censored
                    + r.session_terminated
                    + r.source_path_incomplete
                    + r.not_evaluable,
                r.contributing_sessions,
                r.observed_complete,
                r.right_censored,
                r.session_terminated,
                r.source_path_incomplete,
                r.not_evaluable
            )?;
        }
    }
    w.flush()
}

fn write_widths(path: &Path, rows: &[WidthRow]) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "k\treconstructed_ranges\tcontributing_sessions\treconstruction_not_evaluable\tq10\tq25\tq50\tq75\tq90\tmean\tunit\tderivation"
    )?;
    for r in rows {
        writeln!(
            w,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
            r.k,
            r.reconstructed_ranges,
            r.contributing_sessions,
            r.reconstruction_not_evaluable,
            opt(r.q10),
            opt(r.q25),
            opt(r.q50),
            opt(r.q75),
            opt(r.q90),
            opt(r.mean),
            r.unit,
            r.derivation
        )?;
    }
    w.flush()
}

fn write_identifiability(path: &Path) -> std::io::Result<()> {
    fs::write(
        path,
        concat!(
            "object\tstatus\treceipt\n",
            "CANDIDATE_AGE_AT_BIRTH\tOBSERVER_IMPLIED_ZERO\tEvery candidate-birth anchor has age zero; survival age is the process time axis, not a birth-time predictor.\n",
            "LANDMARK_AGE_STATE\tNEW_ANCHOR_PROTOCOL_REQUIRED\tAge-conditioned future persistence requires causal landmark anchors O(t+u) conditional on survival to u.\n",
            "FINAL_SESSION_MULTIPLICITY\tRETROSPECTIVE_NOT_CAUSAL_AT_BIRTH\tFinal multiplicity becomes known only after session completion.\n",
            "CAUSAL_CANDIDATE_GENERATION_HISTORY\tFUTURE_PROTOCOL_REQUIRED\tAccumulated births or recent birth intensity were not constructed or evaluated here.\n",
            "K_AND_FREEZE_CLOCK\tPERFECTLY_ALIASED\tk minutes implies freeze at 09:30+k in this observer generation.\n",
            "PURE_SCALE_INDEPENDENT_OF_CLOCK\tNOT_IDENTIFIABLE\tThe current observer does not independently vary construction scale and freeze clock.\n",
            "RANGE_GEOMETRY_AT_FIXED_K\tDESCRIPTIVELY_AVAILABLE\tAcross-session frozen width midpoint and paths vary at fixed design coordinate k.\n",
            "RAW_AND_RANGE_Z\tPEER_REPRESENTATIONS\tNormalization is retained beside raw source-price geometry and denominator receipts.\n"
        ),
    )
}

fn write_questions(path: &Path) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "question_id\tauthority\tsource_kind\tsource_view\tobservation\tpossible_construction_explanation\tpossible_clock_explanation\tpossible_normalization_explanation\tpossible_censoring_support_explanation\tcausal_availability"
    )?;
    let rows = [
        [
            "Q01",
            "persistence survival and hazard",
            "non-constant descriptive attrition morphology across physical age",
            "strict supersession-chain construction may shape the curve",
            "age is elapsed physical time after candidate birth",
            "not applicable",
            "at-risk and termination geometry changes with age",
            "age is a process axis; a predictor requires a future landmark-anchor protocol",
        ],
        [
            "Q02",
            "anchor and session weighted persistence",
            "the two declared sampling units do not coincide everywhere",
            "sessions contribute unequal candidate counts",
            "session composition may vary over the observation clock",
            "not applicable",
            "unequal contribution and censoring are shown beside each curve",
            "sampling-unit choice is an estimand definition, not candidate information",
        ],
        [
            "Q03",
            "multiplicity by persistence anatomy",
            "persistence morphology varies across retrospective final-multiplicity strata",
            "strict-extreme generation mechanically determines multiplicity",
            "multiplicity can reflect differing observed session lengths",
            "not applicable",
            "small strata and incomplete paths remain visible",
            "final session multiplicity is unavailable at candidate birth",
        ],
        [
            "Q04",
            "causal-prefix question ledger",
            "retrospective multiplicity motivates a distinct unexecuted history question",
            "a future history representation must be frozen independently",
            "history window and causal clock require explicit design",
            "not applicable",
            "support is not evaluated in this supplement",
            "only births observed by t or a frozen recent-rate functional could be causal",
        ],
        [
            "Q05",
            "range terminal-location coordinate anatomy",
            "terminal-location morphology changes across k horizon and evaluation-clock views",
            "nested range construction couples neighboring k values",
            "k is exactly freeze minute after 09:30 and k+h is evaluation minute",
            "range width changes with k",
            "support twins show horizon termination and source gaps",
            "frozen geometry is available only at 09:30+k",
        ],
        [
            "Q06",
            "raw versus range-normalized geometry",
            "raw and range-z surfaces are not interchangeable descriptions",
            "the same price path is divided by a k-specific frozen width",
            "freeze and evaluation clocks remain coupled to k",
            "small or varying width can amplify normalized morphology",
            "width reconstruction and evaluability accompany the views",
            "both representations are retrospective atlas views of causally frozen geometry",
        ],
        [
            "Q07",
            "path-variation control anatomy",
            "path variation accumulates monotonically in ordinary descriptive views",
            "nonnegative path increments mechanically accumulate with horizon",
            "longer horizons observe more elapsed time",
            "raw and normalized views have different units",
            "horizon completion declines near session end",
            "a later probe must not receive credit merely for decoding elapsed time",
        ],
    ];
    for row in rows {
        writeln!(
            w,
            "{}\tHYPOTHESIS_GENERATION_ONLY\tMACHINE_DERIVED\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
            row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]
        )?;
    }
    w.flush()
}

fn write_findings(path: &Path, p: &AnatomyProducts) -> Result<(), Box<dyn std::error::Error>> {
    let persistence = |unit: &str, age: u16| {
        p.persistence
            .iter()
            .find(|r| r.sampling_unit == unit && r.age_minutes == age)
            .map(|r| json!({
                "survival":r.survival,"conditional_hazard":r.conditional_hazard,
                "at_risk_anchors":r.at_risk_anchors,"contributing_sessions":r.contributing_sessions
            }))
    };
    let quartile = |name: &str, age: u16| {
        p.multiplicity_quartiles
            .iter()
            .find(|r| r.sampling_unit == "SESSION_WEIGHTED" && r.stratum_value == name && r.age_minutes == age)
            .map(|r| json!({"survival":r.survival,"conditional_hazard":r.conditional_hazard,"sessions":r.sessions_in_stratum,"anchors":r.candidate_anchors_in_stratum}))
    };
    let width = |k: u8| {
        p.widths.iter().find(|r| r.k == k).map(
            |r| json!({"q25":r.q25,"median":r.q50,"q75":r.q75,"sessions":r.contributing_sessions}),
        )
    };
    write_json(
        path,
        &json!({
            "schema":"OBS_OPEN_03AI_TYPED_DESCRIPTIVE_FINDINGS_V1",
            "authority":"DESCRIPTIVE_ANATOMY_ONLY",
            "source_kind":"MACHINE_DERIVED",
            "parent_atlas_root":PARENT_ROOT,
            "findings":[
                {"finding_id":"PERSISTENCE_PROCESS_TIME_MORPHOLOGY","source_kind":"MACHINE_DERIVED","classification":"DESCRIPTIVE_ONLY","receipt":{"anchor_weighted":{"age_1":persistence("ANCHOR_WEIGHTED",1),"age_30":persistence("ANCHOR_WEIGHTED",30),"age_120":persistence("ANCHOR_WEIGHTED",120),"age_240":persistence("ANCHOR_WEIGHTED",240)},"session_weighted":{"age_1":persistence("SESSION_WEIGHTED",1),"age_30":persistence("SESSION_WEIGHTED",30),"age_120":persistence("SESSION_WEIGHTED",120),"age_240":persistence("SESSION_WEIGHTED",240)}},"limit":"Age is the survival-process axis; it is not a candidate-birth predictor."},
                {"finding_id":"SAMPLING_UNIT_DIVERGENCE","source_kind":"MACHINE_DERIVED","classification":"DESCRIPTIVE_ONLY","receipt":{"candidate_count_per_session_min":p.session_candidate_counts.iter().min(),"candidate_count_per_session_max":p.session_candidate_counts.iter().max(),"anchor_survival_age_60":persistence("ANCHOR_WEIGHTED",60),"session_survival_age_60":persistence("SESSION_WEIGHTED",60)},"limit":"The views answer random-anchor and random-session questions respectively."},
                {"finding_id":"RETROSPECTIVE_MULTIPLICITY_MORPHOLOGY","source_kind":"MACHINE_DERIVED","classification":"HYPOTHESIS_GENERATION_ONLY","receipt":{"Q1_age_60":quartile("Q1_LE_21",60),"Q2_age_60":quartile("Q2_22_TO_32",60),"Q3_age_60":quartile("Q3_33_TO_41",60),"Q4_age_60":quartile("Q4_GE_42",60)},"limit":"Final session multiplicity is retrospective and unavailable at candidate birth."},
                {"finding_id":"RANGE_WIDTH_DENOMINATOR_MORPHOLOGY","source_kind":"MACHINE_DERIVED","classification":"DESCRIPTIVE_ONLY","receipt":{"k1":width(1),"k5":width(5),"k15":width(15),"k30":width(30),"reconstructed_range_anchors":p.width_reconstructed},"limit":"Range width is both observed geometry and the denominator of RANGE_Z; raw and normalized surfaces remain peers."},
                {"finding_id":"K_FREEZE_CLOCK_ALIAS","source_kind":"ARTIFACT_DECLARED","classification":"NOT_IDENTIFIABLE","receipt":{"freeze_minute_after_open":"k","evaluation_minute_after_open":"k+h"},"limit":"Pure construction-scale morphology independent of freeze clock cannot be identified in this observer generation."},
                {"finding_id":"PATH_VARIATION_CONTROL","source_kind":"MACHINE_DERIVED","classification":"DESCRIPTIVE_ONLY","receipt":{"surface_rows":p.path_variation_surfaces.len()},"limit":"Nonnegative accumulated path variation can increase mechanically with elapsed horizon; a later probe must not receive credit for learning a stopwatch."}
            ],
            "formal_tests":0,"promotions":0
        }),
    )
}

fn write_receipts(
    repository: &Path,
    out: &Path,
    parent: &AtlasAuthority,
    p: &AnatomyProducts,
) -> Result<(), Box<dyn std::error::Error>> {
    let min = *p.session_candidate_counts.iter().min().unwrap_or(&0);
    let max = *p.session_candidate_counts.iter().max().unwrap_or(&0);
    write_json(
        &out.join("OBS_OPEN_03AI_AUTHORITY_MANIFEST.json"),
        &json!({"schema":"OBS_OPEN_03AI_AUTHORITY_MANIFEST_V1","authority":AUTHORITY,"parent_atlas_root":PARENT_ROOT,"scope":"SEALED_D_A_ATLAS_DERIVATIVES_ONLY","new_scientific_authority":false,"formal_inference":false,"target_selection":false,"source_closure_sha256":source_closure_hash(repository)?}),
    )?;
    write_json(
        &out.join("receipts/parent_authority_verification.json"),
        &json!({"schema":"OBS_OPEN_03AI_PARENT_VERIFICATION_V1","parent_root":PARENT_ROOT,"parent_member_count":parent.member_count,"parent_outcome_ledger_sha256":parent.ledger_hash,"parent_records":parent.records().len(),"status":"PASS"}),
    )?;
    write_json(
        &out.join("receipts/access_audit.json"),
        &json!({"schema":"OBS_OPEN_03AI_ACCESS_AUDIT_V1","D_A":{"sealed_parent_outcome_records_read":parent.records().len()},"D_B":{"reads":0,"outcome_applications":0,"scores":0},"D_C":{"reads":0,"observations":0},"raw_market_source_reads":0,"status":"PASS"}),
    )?;
    write_json(
        &out.join("receipts/sampling_unit_receipt.json"),
        &json!({"schema":"NORTHSTAR_DESCRIPTIVE_SAMPLING_UNIT_RECEIPT_V1","law":"EVERY_DESCRIPTIVE_DISTRIBUTION_DECLARES_ITS_SAMPLING_UNIT","views":{"ANCHOR_WEIGHTED":"equal mass per eligible causal anchor","SESSION_WEIGHTED":"equal mass per contributing session then equal mass per eligible anchor within session"},"candidate_count_per_session":{"min":min,"max":max},"status":"PASS"}),
    )?;
    write_json(
        &out.join("receipts/identifiability_receipt.json"),
        &json!({"schema":"OBS_OPEN_03AI_IDENTIFIABILITY_RECEIPT_V1","candidate_age_at_birth":"OBSERVER_IMPLIED_ZERO","landmark_age":"NEW_ANCHOR_PROTOCOL_REQUIRED","final_session_multiplicity":"RETROSPECTIVE_NOT_CAUSAL_AT_BIRTH","k_freeze_clock_relation":"PERFECT_ALIAS","pure_scale_independent_of_clock":"NOT_IDENTIFIABLE","status":"PASS"}),
    )?;
    write_json(
        &out.join("receipts/width_reconstruction_receipt.json"),
        &json!({"schema":"OBS_OPEN_03AI_WIDTH_RECONSTRUCTION_V1","method":"2*raw/range_z on exact sibling records with nonzero z","reconstructed_range_anchors":p.width_reconstructed,"expected_range_anchors":4620,"unreconstructed_range_anchors":4620usize.saturating_sub(p.width_reconstructed),"new_distance_or_geometry":false,"status":if p.width_reconstructed>0{"PASS"}else{"NOT_EVALUABLE"}}),
    )?;
    write_json(
        &out.join("receipts/execution_receipt.json"),
        &json!({"schema":"OBS_OPEN_03AI_EXECUTION_RECEIPT_V1","complete_parent_atlas_consumed":true,"candidate_duration_records":p.durations.len(),"persistence_rows":p.persistence.len(),"multiplicity_raw_rows":p.multiplicity_raw.len(),"multiplicity_quartile_rows":p.multiplicity_quartiles.len(),"range_surface_rows":p.range_surfaces.len(),"path_variation_rows":p.path_variation_surfaces.len(),"formal_tests":0,"promotions":0,"new_outcome_families":0,"D_B_reads":0,"D_C_reads":0,"status":"PASS"}),
    )?;
    Ok(())
}

fn source_closure_hash(repository: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let files = [
        "Cargo.toml",
        "Cargo.lock",
        "OBS_OPEN_03A_I_PROTOCOL_V1.md",
        "src/anatomy.rs",
        "src/authority.rs",
        "src/lib.rs",
        "src/main.rs",
        "src/model.rs",
        "src/output.rs",
        "src/stats.rs",
        "tests/anatomy_contract.rs",
    ];
    let mut h = Sha256::new();
    for rel in files {
        h.update(rel.as_bytes());
        h.update([0]);
        h.update(fs::read(repository.join(STUDY).join(rel))?);
        h.update([0xff]);
    }
    Ok(format!("{:x}", h.finalize()))
}

fn prepare_output(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if out.exists() {
        let r = fs::canonicalize(out)?;
        let n = r.to_string_lossy().replace('\\', "/").to_ascii_lowercase();
        if !(n.starts_with("d:/obs-open-01/atlas-inspection/")
            || n.starts_with("//?/d:/obs-open-01/atlas-inspection/"))
        {
            return Err(format!("REFUSE_OUTPUT_REMOVAL:{}", r.display()).into());
        }
        fs::remove_dir_all(r)?;
    }
    fs::create_dir_all(out)?;
    Ok(())
}
fn recursive(root: &Path) -> Result<Vec<PathBuf>, Box<dyn std::error::Error>> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_owned()];
    while let Some(dir) = stack.pop() {
        for e in fs::read_dir(dir)? {
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
fn members(out: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut v = Vec::new();
    for p in recursive(out)? {
        let rel = p.strip_prefix(out)?.to_string_lossy().replace('\\', "/");
        if matches!(
            rel.as_str(),
            "content_manifest.tsv" | "OBS_OPEN_03AI_ROOT_RECEIPT.json"
        ) {
            continue;
        }
        v.push(Member {
            relative_path: rel,
            bytes: fs::metadata(&p)?.len(),
            sha256: sha256_file(&p)?,
        });
    }
    v.sort_by(|a, b| a.relative_path.cmp(&b.relative_path));
    Ok(v)
}
fn manifest(m: &[Member]) -> Vec<u8> {
    let mut s = String::from("relative_path\tbytes\tsha256\n");
    for x in m {
        s.push_str(&format!("{}\t{}\t{}\n", x.relative_path, x.bytes, x.sha256));
    }
    s.into_bytes()
}
fn opt(v: Option<f64>) -> String {
    v.map(|x| format!("{x:.17}")).unwrap_or_else(|| "NA".into())
}
fn write_json(path: &Path, v: &impl Serialize) -> Result<(), Box<dyn std::error::Error>> {
    let mut b = serde_json::to_vec(v)?;
    b.push(b'\n');
    fs::write(path, b)?;
    Ok(())
}

pub fn compare_builds(
    left: &Path,
    right: &Path,
    receipt: &Path,
) -> Result<RebuildReceipt, Box<dyn std::error::Error>> {
    let lm = fs::read(left.join("content_manifest.tsv"))?;
    let rm = fs::read(right.join("content_manifest.tsv"))?;
    let lr: serde_json::Value =
        serde_json::from_slice(&fs::read(left.join("OBS_OPEN_03AI_ROOT_RECEIPT.json"))?)?;
    let rr: serde_json::Value =
        serde_json::from_slice(&fs::read(right.join("OBS_OPEN_03AI_ROOT_RECEIPT.json"))?)?;
    let lroot = lr["obs_open_03ai_root"]
        .as_str()
        .ok_or("LEFT_ROOT_MISSING")?
        .to_owned();
    let rroot = rr["obs_open_03ai_root"]
        .as_str()
        .ok_or("RIGHT_ROOT_MISSING")?
        .to_owned();
    let lfiles = recursive(left)?;
    let rfiles = recursive(right)?;
    let lrel: Vec<_> = lfiles
        .iter()
        .map(|p| p.strip_prefix(left).unwrap().to_owned())
        .collect();
    let rrel: Vec<_> = rfiles
        .iter()
        .map(|p| p.strip_prefix(right).unwrap().to_owned())
        .collect();
    let mut mismatches = usize::from(lm != rm || lroot != rroot) + usize::from(lrel != rrel);
    if lrel == rrel {
        for rel in &lrel {
            mismatches += usize::from(fs::read(left.join(rel))? != fs::read(right.join(rel))?);
        }
    }
    let result = RebuildReceipt {
        schema: "OBS_OPEN_03AI_REBUILD_RECEIPT_V1".into(),
        left_root: lroot,
        right_root: rroot,
        artifact_count: lrel.len(),
        mismatch_count: mismatches,
        status: if mismatches == 0 { "PASS" } else { "FAIL" }.into(),
    };
    write_json(receipt, &result)?;
    Ok(result)
}

pub fn copy_compact_seal(
    build: &Path,
    seal: &Path,
    rebuild: &Path,
) -> Result<String, Box<dyn std::error::Error>> {
    let rec: RebuildReceipt = serde_json::from_slice(&fs::read(rebuild)?)?;
    if rec.mismatch_count != 0 || rec.status != "PASS" {
        return Err("REBUILD_NOT_IDENTICAL".into());
    }
    if seal.exists() {
        let r = fs::canonicalize(seal)?;
        let n = r.to_string_lossy().replace('\\', "/").to_ascii_lowercase();
        if !n.contains("/studies/obs-open-01/future-process-atlas-inspection/seal") {
            return Err("REFUSE_SEAL_REPLACEMENT".into());
        }
        fs::remove_dir_all(r)?;
    }
    fs::create_dir_all(seal)?;
    let selected = [
        "OBS_OPEN_03AI_AUTHORITY_MANIFEST.json",
        "OBS_OPEN_03AI_ROOT_RECEIPT.json",
        "content_manifest.tsv",
        "IDENTIFIABILITY_LEDGER.tsv",
        "QUESTION_GEN_LEDGER.tsv",
        "TYPED_DESCRIPTIVE_FINDINGS.json",
        "anatomy/range_width_by_k.tsv",
        "receipts/access_audit.json",
        "receipts/execution_receipt.json",
        "receipts/identifiability_receipt.json",
        "receipts/parent_authority_verification.json",
        "receipts/sampling_unit_receipt.json",
        "receipts/width_reconstruction_receipt.json",
    ];
    for rel in selected {
        let dst = seal.join(rel);
        if let Some(p) = dst.parent() {
            fs::create_dir_all(p)?;
        }
        fs::copy(build.join(rel), dst)?;
    }
    fs::copy(rebuild, seal.join("receipts/rebuild_receipt.json"))?;
    Ok(rec.left_root)
}
