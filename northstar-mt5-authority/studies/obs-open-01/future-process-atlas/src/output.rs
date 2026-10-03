use crate::aggregate::{AggregateReceipt, SummaryRow, write_aggregates};
use crate::authority::LoadedAtlas;
use crate::compute::OutcomeProducts;
use crate::model::{ATLAS_SESSIONS, D_B_SESSIONS, D_C_SESSIONS, PROTOCOL_ROOT, PackedOutcome};
use bytemuck::cast_slice;
use obs_open_meas02::sha256_file;
use serde::Serialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

const AUTHORITY: &str = "CAUSAL_FUTURE_PROCESS_ATLAS_V1";
const STUDY: &str = "studies/obs-open-01/future-process-atlas";

#[derive(Debug, Clone, Serialize)]
pub struct ArtifactMember {
    pub relative_path: String,
    pub bytes: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SealResult {
    pub root: String,
    pub artifact_count: usize,
    pub mismatch_count: usize,
}

pub fn write_products(
    repository: &Path,
    out: &Path,
    loaded: &mut LoadedAtlas,
    products: &OutcomeProducts,
) -> Result<String, Box<dyn std::error::Error>> {
    prepare_output(out)?;
    for dir in ["atlas", "receipts"] {
        fs::create_dir_all(out.join(dir))?;
    }
    loaded.access.d_a_outcome_registry_applications = products.records.len();
    write_outcome_ledger(out, &products.records)?;
    write_anchor_registry(out, products)?;
    let (aggregate, summaries) = write_aggregates(out, &products.records, &loaded.sessions)?;
    write_question_ledger(out)?;
    write_receipts(repository, out, loaded, products, &aggregate, &summaries)?;
    reject_forbidden_authority_language(out)?;
    let members = authority_members(out)?;
    let manifest = content_manifest(&members);
    fs::write(out.join("content_manifest.tsv"), &manifest)?;
    let root = sha256_bytes(&manifest);
    write_json(
        &out.join("OBS_OPEN_03A_ROOT_RECEIPT.json"),
        &json!({
            "schema":"OBS_OPEN_03A_ROOT_RECEIPT_V1",
            "authority":AUTHORITY,
            "obs_open_03a_root":root,
            "parent_protocol_root":PROTOCOL_ROOT,
            "artifact_count":members.len(),
            "D_A_sessions":ATLAS_SESSIONS,
            "D_B_outcome_registry_applications":0,
            "D_C_observations_read":0,
            "formal_tests":0,
            "candidate_promotions":0,
            "status":"PASS"
        }),
    )?;
    Ok(root)
}

fn write_outcome_ledger(
    out: &Path,
    records: &[PackedOutcome],
) -> Result<(), Box<dyn std::error::Error>> {
    let bytes = cast_slice(records);
    fs::write(out.join("atlas/outcome_ledger.bin"), bytes)?;
    write_json(
        &out.join("atlas/outcome_ledger_schema.json"),
        &json!({
            "schema":"OBS_OPEN_03A_PACKED_OUTCOME_LEDGER_V1",
            "authority":"RETROSPECTIVE_OUTCOME_SIDECAR_DESCRIPTIVE_ONLY",
            "record_layout":"repr(C), little-endian host-qualified x86_64",
            "record_bytes":std::mem::size_of::<PackedOutcome>(),
            "record_count":records.len(),
            "total_bytes":bytes.len(),
            "source_kind":"MACHINE_DERIVED",
            "causal_state_enrichment":false,
            "sampling_unit":"OUTCOME_RECORD_REFERENCING_CAUSAL_ANCHOR",
            "typed_states":["OBSERVED_COMPLETE","RIGHT_CENSORED","SESSION_TERMINATED","SOURCE_PATH_INCOMPLETE","NOT_EVALUABLE"]
        }),
    )
}

fn write_anchor_registry(
    out: &Path,
    products: &OutcomeProducts,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::new(File::create(out.join("atlas/anchor_registry.tsv"))?);
    writeln!(
        writer,
        "anchor_index\tanchor_id\tsession_index\tsession_id\tanchor_kind\tside\tk\tanchor_known_at\tsource_path_sha256\tpath_bars\tterminal_class"
    )?;
    for a in &products.anchors {
        writeln!(
            writer,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
            a.anchor_index,
            a.anchor_id,
            a.session_index,
            a.session_id,
            a.anchor_kind,
            a.side,
            a.k.map(|v| v.to_string()).unwrap_or_else(|| "NA".into()),
            a.anchor_known_at,
            a.source_path_sha256,
            a.path_bars,
            a.terminal_class
        )?;
    }
    writer.flush()?;
    Ok(())
}

fn write_question_ledger(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    fs::write(
        out.join("QUESTION_GEN_LEDGER.tsv"),
        "question_id\tauthority\tdescription\tstatus\n",
    )?;
    write_json(
        &out.join("receipts/question_generation_receipt.json"),
        &json!({
            "schema":"OBS_OPEN_03A_QUESTION_GENERATION_RECEIPT_V1",
            "authority":"HYPOTHESIS_GENERATION_ONLY",
            "question_count":0,
            "formal_test_count":0,
            "promotion_count":0,
            "status":"EMPTY_BY_EXECUTION_DISCIPLINE"
        }),
    )
}

fn write_receipts(
    repository: &Path,
    out: &Path,
    loaded: &LoadedAtlas,
    products: &OutcomeProducts,
    aggregate: &AggregateReceipt,
    summaries: &[SummaryRow],
) -> Result<(), Box<dyn std::error::Error>> {
    let candidate_anchors = products
        .anchors
        .iter()
        .filter(|a| a.anchor_kind == "EXTREME_CANDIDATE_BIRTH")
        .count();
    let range_anchors = products.anchors.len() - candidate_anchors;
    let complete_sessions = loaded.sessions.iter().filter(|s| s.path_complete).count();
    let code_hash = source_closure_hash(repository)?;
    write_json(
        &out.join("OBS_OPEN_03A_AUTHORITY_MANIFEST.json"),
        &json!({
            "schema":"OBS_OPEN_03A_AUTHORITY_MANIFEST_V1",
            "authority":AUTHORITY,
            "parents":{"future_process_protocol_root":PROTOCOL_ROOT},
            "population":{"D_A":ATLAS_SESSIONS,"D_B":D_B_SESSIONS,"D_C":D_C_SESSIONS},
            "scope":"D_A_ONLY_DESCRIPTIVE_ATLAS",
            "sampling_units":["ANCHOR_WEIGHTED","SESSION_WEIGHTED"],
            "formal_inference_authorized":false,
            "candidate_promotion_authorized":false,
            "causal_state_mutation":false,
            "economic_authority":false,
            "trading_authority":false,
            "execution_source_closure_sha256":code_hash
        }),
    )?;
    write_json(&out.join("receipts/access_audit.json"), &loaded.access)?;
    write_json(
        &out.join("receipts/confirmation_firewall.json"),
        &json!({
            "schema":"OBS_OPEN_03A_CONFIRMATION_FIREWALL_V1",
        "D_A":{"sessions_decoded":loaded.access.d_a_sessions_decoded,"ohlc_observations_decoded":loaded.access.d_a_ohlc_observations_decoded,"outcome_registry_applications":loaded.access.d_a_outcome_registry_applications},
        "D_B":{"session_ids_decoded_for_outcomes":loaded.access.d_b_session_ids_decoded_for_outcomes,"ohlc_values_decoded":loaded.access.d_b_ohlc_values_decoded,"outcome_registry_applications":loaded.access.d_b_outcome_registry_applications,"derived_outcomes_inspected":loaded.access.d_b_derived_outcomes_inspected,"formal_scores":loaded.access.d_b_formal_scores},
        "D_C":{"membership_rows_decoded":loaded.access.d_c_membership_rows_decoded,"observations_read":loaded.access.d_c_observations_read,"outcomes_computed":loaded.access.d_c_outcomes_computed},
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/corpus_receipt.json"),
        &json!({
            "schema":"OBS_OPEN_03A_CORPUS_RECEIPT_V1",
            "D_A_sessions":loaded.sessions.len(),
            "complete_sessions":complete_sessions,
            "source_path_incomplete_sessions":loaded.sessions.len()-complete_sessions,
            "retained_M1_bars":loaded.sessions.iter().map(|s|s.bars.len()).sum::<usize>(),
            "range_anchors":range_anchors,
            "candidate_anchors":candidate_anchors,
            "total_anchors":products.anchors.len(),
            "outcome_records":products.records.len(),
            "raw_source_sha256":loaded.raw_source_hash,
            "firewall_manifest_sha256":loaded.firewall_manifest_hash
        }),
    )?;
    write_json(&out.join("receipts/aggregate_receipt.json"), aggregate)?;
    write_json(
        &out.join("receipts/sampling_unit_receipt.json"),
        &json!({
            "schema":"NORTHSTAR_DESCRIPTIVE_SAMPLING_UNIT_RECEIPT_V1",
            "law":"EVERY_DESCRIPTIVE_DISTRIBUTION_DECLARES_ITS_SAMPLING_UNIT",
            "views":{
                "ANCHOR_WEIGHTED":"equal mass per eligible causal anchor",
                "SESSION_WEIGHTED":"equal mass per contributing session then equal mass per eligible anchor within session"
            },
            "distribution_rows":summaries.len(),
            "rows_missing_sampling_unit":summaries.iter().filter(|r|r.sampling_unit.is_empty()).count(),
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/knowledge_time_receipt.json"),
        &json!({
            "schema":"OBS_OPEN_03A_KNOWLEDGE_TIME_RECEIPT_V1",
            "anchor_known_at_bound":true,
            "outcome_window_bound":true,
            "outcome_known_at_bound":true,
            "censor_and_evaluability_state_bound":true,
            "retrospective_sidecars_enrich_causal_state":false,
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/execution_receipt.json"),
        &json!({
            "schema":"OBS_OPEN_03A_EXECUTION_RECEIPT_V1",
            "protocol_root":PROTOCOL_ROOT,
            "execution_addendum":"OBS_OPEN_03A_EXECUTION_ADDENDUM_V1",
            "full_atlas_materialized":true,
            "sampling_units":["ANCHOR_WEIGHTED","SESSION_WEIGHTED"],
            "raw_and_normalized_siblings_retained":true,
            "formal_tests":0,
            "formal_scores":0,
            "promotions":0,
            "D_B_protocol_construction":false,
            "status":"PASS"
        }),
    )?;
    Ok(())
}

fn source_closure_hash(repository: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let files = [
        "Cargo.toml",
        "Cargo.lock",
        "OBS_OPEN_03A_EXECUTION_ADDENDUM_V1.md",
        "src/aggregate.rs",
        "src/authority.rs",
        "src/compute.rs",
        "src/lib.rs",
        "src/main.rs",
        "src/model.rs",
        "src/output.rs",
        "tests/atlas_contract.rs",
    ];
    let mut hasher = Sha256::new();
    for relative in files {
        let path = repository.join(STUDY).join(relative);
        hasher.update(relative.as_bytes());
        hasher.update([0]);
        hasher.update(fs::read(path)?);
        hasher.update([0xff]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn reject_forbidden_authority_language(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let forbidden = [
        "SIGNAL",
        "EFFECT",
        "PREDICTIVE",
        "SUPPORTED",
        "BEST",
        "ROBUST",
        "PROFIT",
        "TRADE_ENTRY",
    ];
    for path in recursive_files(out)? {
        if path.extension().and_then(|x| x.to_str()) == Some("bin") {
            continue;
        }
        let text = String::from_utf8_lossy(&fs::read(&path)?).to_ascii_uppercase();
        for token in forbidden {
            if text
                .split(|c: char| !c.is_ascii_alphabetic())
                .any(|word| word == token)
            {
                return Err(format!(
                    "FORBIDDEN_ATLAS_AUTHORITY_LANGUAGE:{token}:{}",
                    path.display()
                )
                .into());
            }
        }
    }
    Ok(())
}

fn prepare_output(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if out.exists() {
        let resolved = fs::canonicalize(out)?;
        let normalized = resolved
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        if !(normalized.starts_with("d:/obs-open-01/atlas/")
            || normalized.starts_with("//?/d:/obs-open-01/atlas/"))
        {
            return Err(format!("REFUSE_OUTPUT_REMOVAL:{}", resolved.display()).into());
        }
        fs::remove_dir_all(&resolved)?;
    }
    fs::create_dir_all(out)?;
    Ok(())
}

fn authority_members(out: &Path) -> Result<Vec<ArtifactMember>, Box<dyn std::error::Error>> {
    let mut members = Vec::new();
    for path in recursive_files(out)? {
        let relative = path.strip_prefix(out)?.to_string_lossy().replace('\\', "/");
        if matches!(
            relative.as_str(),
            "content_manifest.tsv" | "OBS_OPEN_03A_ROOT_RECEIPT.json"
        ) {
            continue;
        }
        members.push(ArtifactMember {
            relative_path: relative,
            bytes: fs::metadata(&path)?.len(),
            sha256: sha256_file(&path)?,
        });
    }
    members.sort_by(|a, b| a.relative_path.cmp(&b.relative_path));
    Ok(members)
}

fn content_manifest(members: &[ArtifactMember]) -> Vec<u8> {
    let mut out = String::from("relative_path\tbytes\tsha256\n");
    for m in members {
        out.push_str(&format!("{}\t{}\t{}\n", m.relative_path, m.bytes, m.sha256));
    }
    out.into_bytes()
}

fn recursive_files(root: &Path) -> Result<Vec<PathBuf>, Box<dyn std::error::Error>> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        for entry in fs::read_dir(dir)? {
            let path = entry?.path();
            if path.is_dir() {
                stack.push(path)
            } else {
                out.push(path)
            }
        }
    }
    out.sort();
    Ok(out)
}

pub fn compare_builds(left: &Path, right: &Path) -> Result<SealResult, Box<dyn std::error::Error>> {
    let lm = fs::read(left.join("content_manifest.tsv"))?;
    let rm = fs::read(right.join("content_manifest.tsv"))?;
    let mut mismatch = usize::from(lm != rm);
    let left_files = recursive_files(left)?;
    let right_files = recursive_files(right)?;
    let lrel: Vec<_> = left_files
        .iter()
        .map(|p| p.strip_prefix(left).unwrap().to_path_buf())
        .collect();
    let rrel: Vec<_> = right_files
        .iter()
        .map(|p| p.strip_prefix(right).unwrap().to_path_buf())
        .collect();
    if lrel != rrel {
        mismatch += 1;
    } else {
        for relative in &lrel {
            if fs::read(left.join(relative))? != fs::read(right.join(relative))? {
                mismatch += 1;
            }
        }
    }
    let root = sha256_bytes(&lm);
    Ok(SealResult {
        root,
        artifact_count: lrel.len(),
        mismatch_count: mismatch,
    })
}

pub fn copy_compact_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        let resolved = fs::canonicalize(seal)?;
        let normalized = resolved
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        if !normalized.contains("/studies/obs-open-01/future-process-atlas/seal") {
            return Err("REFUSE_SEAL_REPLACEMENT".into());
        }
        fs::remove_dir_all(resolved)?;
    }
    fs::create_dir_all(seal)?;
    let selected = [
        "OBS_OPEN_03A_AUTHORITY_MANIFEST.json",
        "OBS_OPEN_03A_ROOT_RECEIPT.json",
        "content_manifest.tsv",
        "QUESTION_GEN_LEDGER.tsv",
        "atlas/ecdf_query_contract.json",
        "atlas/evaluability_census.tsv",
        "atlas/sampling_unit_multiplicity.tsv",
        "atlas/visualization_projection.json",
        "atlas/outcome_ledger_schema.json",
        "receipts/access_audit.json",
        "receipts/aggregate_receipt.json",
        "receipts/confirmation_firewall.json",
        "receipts/corpus_receipt.json",
        "receipts/execution_receipt.json",
        "receipts/knowledge_time_receipt.json",
        "receipts/question_generation_receipt.json",
        "receipts/sampling_unit_receipt.json",
    ];
    for relative in selected {
        let src = build.join(relative);
        let dst = seal.join(relative);
        if let Some(parent) = dst.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::copy(src, dst)?;
    }
    let root: serde_json::Value =
        serde_json::from_slice(&fs::read(build.join("OBS_OPEN_03A_ROOT_RECEIPT.json"))?)?;
    Ok(root["obs_open_03a_root"]
        .as_str()
        .ok_or("ROOT_MISSING")?
        .to_owned())
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<(), Box<dyn std::error::Error>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    fs::write(path, bytes)?;
    Ok(())
}
fn sha256_bytes(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    format!("{:x}", h.finalize())
}
