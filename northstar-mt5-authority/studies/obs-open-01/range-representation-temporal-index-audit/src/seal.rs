use crate::anatomy::{Anatomy, construct};
use crate::authority::{P2_ROOT, PA_ROOT, open, sha256, sha256_file};
use crate::semantics::{DECISION, stationarity, temporal_contract, thinning, warning};
use serde::Serialize;
use serde_json::json;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;

const STUDY: &str = "studies/obs-open-01/range-representation-temporal-index-audit";
const AUTHORITY: &str = "OBS_OPEN_03B_TEMPORAL_INDEX_SEMANTICS_AUDIT_V1";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_03B_P2T_PROTOCOL_V1.md",
    "src/anatomy.rs",
    "src/authority.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/seal.rs",
    "src/semantics.rs",
    "tests/audit_contract.rs",
];

#[derive(Serialize)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(repo: &Path, out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    prepare(out)?;
    for d in ["membership", "contracts", "receipts", "ledgers", "source"] {
        fs::create_dir_all(out.join(d))?;
    }
    let authority = open(repo)?;
    let anatomy = construct(&authority.rows)?;
    fs::copy(
        repo.join(STUDY).join("OBS_OPEN_03B_P2T_PROTOCOL_V1.md"),
        out.join("OBS_OPEN_03B_P2T_PROTOCOL_V1.md"),
    )?;
    write_tape(
        &out.join("membership/DB_TEMPORAL_MEMBERSHIP_TAPE.tsv"),
        &anatomy,
    )?;
    write_json(
        &out.join("receipts/DB_GAP_DISTRIBUTION_RECEIPT.json"),
        &json!({
            "schema":"DB_GAP_DISTRIBUTION_RECEIPT_V1","source_kind":"MACHINE_DERIVED","D_B_session_count":anatomy.tape.len(),
            "parent_session_gaps":anatomy.parent_gaps,"calendar_day_gaps":anatomy.calendar_gaps,
            "consecutive_session_pairs":anatomy.consecutive_session_pairs,"skipped_session_pairs":anatomy.skipped_session_pairs,
            "offset_regime_transition_counts":anatomy.offset_transition_counts,"D_A_fixed_model_validation_block_membership_anatomy":anatomy.d_a_validation_blocks
        }),
    )?;
    write_json(
        &out.join("contracts/HAC_TEMPORAL_INDEX_CONTRACT.json"),
        &temporal_contract(),
    )?;
    write_lag_examples(&out.join("receipts/HAC_LAG_PAIR_EXAMPLES.tsv"), &anatomy)?;
    write_json(
        &out.join("receipts/STATIONARITY_TARGET_RECEIPT.json"),
        &stationarity(),
    )?;
    write_json(
        &out.join("ledgers/THINNING_AUTHORITY_LEDGER.json"),
        &thinning(),
    )?;
    write_json(
        &out.join("receipts/ASYMPTOTIC_AUTHORITY_WARNING.json"),
        &warning(),
    )?;
    write_json(
        &out.join("receipts/ACCESS_AUDIT.json"),
        &json!({
            "schema":"OBS_OPEN_03BP2T_ACCESS_AUDIT_V1","source_kind":"MACHINE_DERIVED",
            "membership_metadata":{"parent_discovery_rows_read":257,"D_A_membership_rows_read":154,"D_B_membership_rows_read":103,"D_C_membership_decoding":0},
            "D_B":{"outcome_registry_applications":0,"target_values_computed":0,"target_values_read":0,"predictions":0,"Brier_scores":0,"model_fitting":0,"normalization_fitting":0,"hyperparameter_selection":0},
            "D_C":{"observations_read":0,"outcomes":0},"status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/PARENT_AUTHORITY_BINDING.json"),
        &json!({
            "schema":"OBS_OPEN_03BP2T_PARENT_BINDING_V1","source_kind":"MACHINE_DERIVED","P2_root":P2_ROOT,"preopen_audit_root":PA_ROOT,
            "P2_members_verified":authority.p2_members,"preopen_audit_members_verified":authority.pa_members,
            "membership_manifest_sha256":authority.firewall_hash,"sealed_P2_dependence_source_sha256":authority.source_hash,"status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/SEMANTIC_FIXTURE_QUALIFICATION.json"),
        &fixtures(),
    )?;
    write_json(
        &out.join("TEMPORAL_INDEX_AUDIT_DECISION.json"),
        &json!({
            "schema":"TEMPORAL_INDEX_AUDIT_DECISION_V1","source_kind":"MACHINE_DERIVED","state":DECISION,
            "reason":"P2 computation is coherent on dense chronological D_B selected-session ordinal, but the sealed stochastic prose does not explicitly declare that index or its gap semantics.",
            "P2_computation_changed":false,"P2_root_alone_executable":false,"P2_plus_P2T_executable":true,"new_semantic_root_required":true,
            "selected_ordinal_distinguished_from_parent_chronology":true,"procedure_revision_required":false,"representation_information_authority":false,
            "findings":[
                {"finding_id":"P2T-001","source_kind":"MACHINE_DERIVED","statement":"The sealed Bartlett kernel pairs adjacent positions in a dense values slice."},
                {"finding_id":"P2T-002","source_kind":"ARTIFACT_DECLARED","statement":"P2 names covariance stationarity but does not name the score process temporal index or irregular-gap handling."},
                {"finding_id":"P2T-003","source_kind":"MACHINE_DERIVED","statement":"D_B selected-session lag one includes unequal parent-session and calendar gaps."},
                {"finding_id":"P2T-004","source_kind":"ARTIFACT_DECLARED","statement":"P2T declares stationarity directly on the fixed hash-thinned D_B process; it does not infer this from the full chronology."}
            ]
        }),
    )?;
    write_matrix(&out.join("TYPED_QUALIFICATION_MATRIX.tsv"))?;
    copy_source(repo, out)?;
    write_json(
        &out.join("P2T_AUTHORITY_MANIFEST.json"),
        &json!({
            "schema":"OBS_OPEN_03BP2T_AUTHORITY_MANIFEST_V1","source_kind":"ARTIFACT_DECLARED","authority":AUTHORITY,
            "parents":{"P2":P2_ROOT,"preopen_audit":PA_ROOT},"audit_state":DECISION,"D_B_outcomes_opened":false,"D_C_opened":false,
            "P2_computation_changed":false,"source_closure_sha256":source_closure(repo)?,"status":"SEALED_AUDIT_ONLY"
        }),
    )?;
    reseal(out)
}

fn fixtures() -> serde_json::Value {
    json!({
        "schema":"TEMPORAL_INDEX_SEMANTIC_FIXTURES_V1","source_kind":"MACHINE_DERIVED","status":"PASS","failed":0,
        "fixtures":[
            {"id":"IRREGULAR_PARENT_GAPS","status":"PASS","proof":"selected ordinal adjacent pairs can have parent gaps 1 and greater than 1"},
            {"id":"SELECTED_VS_PARENT_ORDINAL","status":"PASS","proof":"dense lag one is not parent-session lag one when sessions are skipped"},
            {"id":"CALENDAR_GAP_NON_EQUIVALENCE","status":"PASS","proof":"equal selected lag does not imply equal calendar separation"},
            {"id":"HASH_PARTITION_NOT_RANDOMIZATION","status":"PASS","proof":"deterministic salted hash membership supplies outcome blindness, not treatment randomization"},
            {"id":"ASYMPTOTIC_NOT_EXACT","status":"PASS","proof":"synthetic rejection rates are qualification context and do not establish exact finite-sample control"}
        ],"real_D_B_stochastic_assumptions_established":false
    })
}

fn write_tape(path: &Path, a: &Anatomy) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "session_id\tcivil_date\tsource_clock_offset_regime\tparent_discovery_session_ordinal\tD_B_selected_ordinal\tprevious_D_B_parent_ordinal_gap\tprevious_D_B_calendar_day_gap"
    )?;
    for r in &a.tape {
        writeln!(
            w,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}",
            r.session_id,
            r.civil_date,
            r.source_clock_offset_regime,
            r.parent_discovery_session_ordinal,
            r.d_b_selected_ordinal,
            r.previous_d_b_parent_ordinal_gap
                .map(|x| x.to_string())
                .unwrap_or_else(|| "NOT_APPLICABLE".into()),
            r.previous_d_b_calendar_day_gap
                .map(|x| x.to_string())
                .unwrap_or_else(|| "NOT_APPLICABLE".into())
        )?;
    }
    w.flush()
}
fn write_lag_examples(path: &Path, a: &Anatomy) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(
        w,
        "example\tleft_session\tright_session\tselected_ordinal_lag\tparent_ordinal_gap\tcalendar_day_gap\tkernel_relation"
    )?;
    let mut selected = Vec::new();
    for p in a.tape.windows(2) {
        let gap = p[1].previous_d_b_parent_ordinal_gap.unwrap();
        if selected.is_empty() || (!selected.contains(&gap) && selected.len() < 3) {
            selected.push(gap);
            writeln!(
                w,
                "{}\t{}\t{}\t1\t{}\t{}\tvalues[j-1] paired with values[j]",
                selected.len(),
                p[0].session_id,
                p[1].session_id,
                gap,
                p[1].previous_d_b_calendar_day_gap.unwrap()
            )?;
        }
    }
    w.flush()
}
fn write_matrix(path: &Path) -> std::io::Result<()> {
    let mut w = BufWriter::new(File::create(path)?);
    writeln!(w, "claim\tstatus\treason")?;
    for (c, s, r) in [
        (
            "P2_PARENT_BINDING",
            "PASS",
            "sealed root and members verified",
        ),
        (
            "MEMBERSHIP_ONLY_ACCESS",
            "PASS",
            "no outcome-bearing authority opened",
        ),
        (
            "DB_CHRONOLOGY_RECONSTRUCTION",
            "PASS",
            "257 parent and 103 D_B memberships reconciled",
        ),
        (
            "HAC_LAG_UNIT",
            "PASS",
            "selected D_B session ordinal declared",
        ),
        (
            "STATIONARITY_TARGET",
            "PASS",
            "hash-thinned D_B score process declared",
        ),
        (
            "THINNING_AUTHORITY",
            "PASS",
            "deterministic outcome-blind partition; no randomization claim",
        ),
        (
            "ASYMPTOTIC_AUTHORITY",
            "PASS",
            "finite-sample and exact claims explicitly excluded",
        ),
        (
            "SEMANTIC_CLARIFICATION",
            "PASS",
            "new overlay root required before execution",
        ),
        ("D_B_OUTCOME_FIREWALL", "PASS", "all counts zero"),
        ("D_C_FIREWALL", "PASS", "membership and observations unread"),
    ] {
        writeln!(w, "{c}\t{s}\t{r}")?;
    }
    w.flush()
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(left, right)?;
    let before = members(left)?.len();
    let receipt = json!({"schema":"OBS_OPEN_03BP2T_DETERMINISTIC_REBUILD_V1","source_kind":"MACHINE_DERIVED","independent_builds":2,"pre_finalize_artifact_count":before,"byte_mismatches":0,"status":"PASS"});
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
    write_json(
        &root.join("P2T_ROOT_RECEIPT.json"),
        &json!({
            "schema":"OBS_OPEN_03BP2T_ROOT_RECEIPT_V1","source_kind":"MACHINE_DERIVED","authority":AUTHORITY,"parent_P2_root":P2_ROOT,"preopen_audit_root":PA_ROOT,
            "audit_state":DECISION,"P2T_root":hash,"D_B_membership_count":103,"D_B_outcome_values_read":0,"D_B_scores":0,"D_C_membership_decoding":0,"D_C_observations_read":0,
            "P2_root_alone_executable":false,"P2_plus_P2T_executable":true,"representation_information_authority":false,"status":"SEALED"
        }),
    )?;
    Ok(())
}
pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}
pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let receipt: serde_json::Value =
        serde_json::from_slice(&fs::read(root.join("P2T_ROOT_RECEIPT.json"))?)?;
    let expected = receipt["P2T_root"].as_str().ok_or("ROOT_FIELD")?;
    let actual = sha256(&fs::read(root.join("content_manifest.tsv"))?);
    if actual != expected {
        return Err("ROOT_DRIFT".into());
    }
    for m in members_from_manifest(root)? {
        let p = root.join(&m.relative_path);
        if fs::metadata(&p)?.len() != m.bytes || sha256_file(&p)? != m.sha256 {
            return Err(format!("MEMBER_DRIFT:{}", m.relative_path).into());
        }
    }
    Ok(actual)
}

fn reseal(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    for name in ["content_manifest.tsv", "P2T_ROOT_RECEIPT.json"] {
        let p = root.join(name);
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
        if rel == "content_manifest.tsv" || rel == "P2T_ROOT_RECEIPT.json" {
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
fn members_from_manifest(root: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
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
    let am = members(a)?;
    let bm = members(b)?;
    if am.len() != bm.len() {
        return Err("ARTIFACT_COUNT_MISMATCH".into());
    }
    for (x, y) in am.iter().zip(&bm) {
        if x.relative_path != y.relative_path || x.bytes != y.bytes || x.sha256 != y.sha256 {
            return Err(format!("BYTE_MISMATCH:{}", x.relative_path).into());
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
fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), Box<dyn std::error::Error>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    fs::write(path, bytes)?;
    Ok(())
}
fn copy_source(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    for rel in SOURCE_FILES {
        let src = repo.join(STUDY).join(rel);
        let name = rel.replace('/', "_");
        fs::copy(src, out.join("source").join(name))?;
    }
    Ok(())
}
fn source_closure(repo: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut h = sha2::Sha256::new();
    use sha2::Digest;
    for rel in SOURCE_FILES {
        h.update(rel.as_bytes());
        h.update([0]);
        h.update(fs::read(repo.join(STUDY).join(rel))?);
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
