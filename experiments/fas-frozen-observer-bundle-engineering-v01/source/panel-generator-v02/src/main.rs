use std::collections::BTreeMap;
use std::error::Error;
use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Component, Path, PathBuf};
use std::time::Instant;

use hashbrown::HashSet;
use memchr::memchr_iter;
use memmap2::MmapOptions;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use fas_frozen_observer_bundle_panel_v02::generate::{
    EXPECTED_QUARTETS, GENERATOR_SEED, for_each_quartet, sha256_hex, term_inventory,
};
use fas_frozen_observer_bundle_panel_v02::model::{Quartet, TermInventory};

const ROWS_PER_QUARTET: usize = 4;
const EXPECTED_ROWS: usize = EXPECTED_QUARTETS * ROWS_PER_QUARTET;
const MIN_TEST_ROWS_PER_CLASS: u64 = 200;
const SPLIT_SEED: u64 = 2_026_092_502;
const E0_STATUS: &str = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT";
const E1_STATUS: &str = "E1_PANEL_SEALED_MODEL_CONTACT_NOT_AUTHORIZED";

#[derive(Clone, Debug, Serialize)]
struct FileEntry {
    path: String,
    bytes: u64,
    sha256: String,
}

#[derive(Clone, Debug)]
struct EndpointSupport {
    class_rows: Vec<u64>,
}

fn main() {
    if let Err(error) = dispatch() {
        eprintln!("FAS frozen observer bundle E1 stopped: {error}");
        std::process::exit(1);
    }
}

fn dispatch() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    match args
        .next()
        .and_then(|value| value.into_string().ok())
        .as_deref()
    {
        Some("materialize") => {
            let output_root = PathBuf::from(args.next().ok_or("missing output root")?);
            let world_contract = PathBuf::from(args.next().ok_or("missing world contract")?);
            let e0_manifest = PathBuf::from(args.next().ok_or("missing E0 seal manifest")?);
            if args.next().is_some() {
                return Err("unexpected materialize arguments".into());
            }
            materialize(&output_root, &world_contract, &e0_manifest)
        }
        Some("finalize") => {
            let output_root = PathBuf::from(args.next().ok_or("missing output root")?);
            let free_after = args
                .next()
                .ok_or("missing post-build D: free bytes")?
                .into_string()
                .map_err(|_| "post-build free bytes are not UTF-8")?
                .parse::<u64>()?;
            if args.next().is_some() {
                return Err("unexpected finalize arguments".into());
            }
            finalize(&output_root, free_after)
        }
        _ => Err("expected `materialize` or `finalize`".into()),
    }
}

fn materialize(
    output_root: &Path,
    world_contract_path: &Path,
    e0_manifest_path: &Path,
) -> Result<(), Box<dyn Error>> {
    let started = Instant::now();
    let (e0_root, e0_entries) = verify_e0(e0_manifest_path)?;
    let world_bytes = fs::read(world_contract_path)?;
    let world: Value = serde_json::from_slice(&world_bytes)?;
    verify_world_contract(&world, &world_bytes, &e0_entries)?;
    verify_preflight(output_root, &e0_root)?;
    ensure_only_preflight_exists(output_root)?;

    let contracts_dir = output_root.join("contracts");
    let corpus_dir = output_root.join("corpus");
    let panel_dir = output_root.join("panel");
    let labels_dir = output_root.join("labels");
    let receipts_dir = output_root.join("receipts");
    for dir in [
        &contracts_dir,
        &corpus_dir,
        &panel_dir,
        &labels_dir,
        &receipts_dir,
    ] {
        fs::create_dir_all(dir)?;
    }
    write_new(
        &contracts_dir.join("panel-world-contract-v01.json"),
        &world_bytes,
    )?;
    let e0_bytes = fs::read(e0_manifest_path)?;
    write_new(&contracts_dir.join("e0-seal-manifest-v01.json"), &e0_bytes)?;

    let inventory = term_inventory();
    validate_inventory(&inventory, &world)?;
    let inventory_bytes = serde_json::to_vec_pretty(&inventory)?;
    write_json_new(
        &corpus_dir.join("term-inventory-v01.json"),
        &inventory_bytes,
    )?;

    let split_plan = build_split_plan()?;
    let test_ids: HashSet<String> = split_plan
        .iter()
        .filter(|row| row.2)
        .map(|row| row.0.clone())
        .collect();
    let split_counts = split_plan.iter().fold([0_u64; 3], |mut counts, row| {
        counts[row.1 as usize] += 1;
        counts
    });
    if split_plan.len() != EXPECTED_QUARTETS || split_counts.iter().any(|count| *count == 0) {
        return Err("stratified split has an empty exact-target stratum".into());
    }

    let split_path = panel_dir.join("split-manifest-v01.jsonl");
    let input_path = panel_dir.join("panel-inputs-v01.jsonl");
    let row_manifest_path = panel_dir.join("row-manifest-v01.jsonl");
    let fit_labels_path = labels_dir.join("fit-labels-v01.jsonl");
    let eval_labels_path = labels_dir.join("eval-labels-v01.jsonl");
    let mut split_writer = new_writer(&split_path)?;
    let mut input_writer = new_writer(&input_path)?;
    let mut row_manifest_writer = new_writer(&row_manifest_path)?;
    let mut fit_writer = new_writer(&fit_labels_path)?;
    let mut eval_writer = new_writer(&eval_labels_path)?;

    let mut fit_support = empty_support();
    let mut eval_support = empty_eval_support();
    let mut quartets_seen = 0_usize;
    let mut rows_seen = 0_usize;
    let generation = for_each_quartet(|quartet| {
        let is_test = test_ids.contains(&quartet.quartet_id);
        write_jsonl(
            &mut split_writer,
            &json!({
                "quartet_id": quartet.quartet_id,
                "split": if is_test { "TEST" } else { "FIT" },
                "exact_target_stratum": quartet.exact_target,
                "split_assignment": "SHA256_SORT_WITHIN_EXACT_TARGET_CLASS_FLOOR_20_PERCENT_TEST",
            }),
        )?;
        write_quartet_rows(
            &quartet,
            is_test,
            &mut input_writer,
            &mut row_manifest_writer,
            &mut fit_writer,
            &mut eval_writer,
            &mut fit_support,
            &mut eval_support,
            &mut rows_seen,
        )?;
        quartets_seen += 1;
        Ok(())
    })?;
    for writer in [
        &mut split_writer,
        &mut input_writer,
        &mut row_manifest_writer,
        &mut fit_writer,
        &mut eval_writer,
    ] {
        finish_writer(writer)?;
    }
    if generation.total != EXPECTED_QUARTETS
        || quartets_seen != EXPECTED_QUARTETS
        || rows_seen != EXPECTED_ROWS
    {
        return Err(format!(
            "generated counts differ: generator={}, emitted quartets={}, rows={}",
            generation.total, quartets_seen, rows_seen
        )
        .into());
    }
    if test_ids.len() + (EXPECTED_QUARTETS - test_ids.len()) != EXPECTED_QUARTETS {
        return Err("split membership cardinality invariant failed".into());
    }

    let support_pass = support_pass(&fit_support, &eval_support);
    let support_receipt =
        build_support_receipt(&fit_support, &eval_support, support_pass, split_counts);
    write_json_new(
        &receipts_dir.join("support-receipt-v01.json"),
        &serde_json::to_vec_pretty(&support_receipt)?,
    )?;

    let core = json!({
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E1_PANEL_BUILD_CORE_V01",
        "e0_root_sha256": e0_root,
        "world_contract_sha256": sha256_hex(&world_bytes),
        "generator_seed": GENERATOR_SEED,
        "split_seed": SPLIT_SEED,
        "quartets": quartets_seen,
        "input_rows": rows_seen,
        "fit_quartets": EXPECTED_QUARTETS as u64 - split_counts.iter().sum::<u64>(),
        "test_quartets_by_exact_target_class": split_counts,
        "generation_enumerations": 2,
        "generator_enumeration_seconds": started.elapsed().as_secs_f64(),
        "model_loaded": false,
        "tokenizer_loaded": false,
        "feature_extraction_performed": false,
        "observer_fitting_performed": false,
        "feature_rows": 0,
        "historical_s01_corpus_or_cache_reused": false,
        "status": if support_pass { "PANEL_BUILT_SUPPORT_GATE_PASS_PENDING_FINAL_RESOURCE_RECEIPT" } else { "PANEL_BUILT_SUPPORT_GATE_FAIL_PRESERVED" },
    });
    write_json_new(
        &receipts_dir.join("panel-build-core-v01.json"),
        &serde_json::to_vec_pretty(&core)?,
    )?;
    println!(
        "panel materialized: quartets={quartets_seen}, rows={rows_seen}, support_pass={support_pass}, rows_per_second={:.1}",
        rows_seen as f64 / started.elapsed().as_secs_f64().max(0.001)
    );
    if !support_pass {
        return Err("support floor failed; artifacts preserved without an E1 seal".into());
    }
    Ok(())
}

fn finalize(output_root: &Path, free_after: u64) -> Result<(), Box<dyn Error>> {
    let receipts_dir = output_root.join("receipts");
    if output_root.join("e1-seal-v01.json").exists() {
        return Err("E1 seal already exists; refusing in-place rewrite".into());
    }
    let preflight: Value = read_json(&output_root.join("resource-preflight-v01.json"))?;
    let support: Value = read_json(&receipts_dir.join("support-receipt-v01.json"))?;
    let core: Value = read_json(&receipts_dir.join("panel-build-core-v01.json"))?;
    if support["support_gate_pass"] != true
        || core["model_loaded"] != false
        || core["tokenizer_loaded"] != false
    {
        return Err("E1 support or no-model-contact invariant failed; no seal emitted".into());
    }
    let total = preflight["target_volume_total_bytes"]
        .as_u64()
        .ok_or("preflight total bytes missing")?;
    let free_before = preflight["target_volume_free_bytes_before"]
        .as_u64()
        .ok_or("preflight free bytes missing")?;
    let projected_peak = preflight["projected_peak_bytes"]
        .as_u64()
        .ok_or("projected peak missing")?;
    let reserve = total / 10;
    let storage_pass =
        free_before >= projected_peak + reserve && free_after >= projected_peak + reserve;
    if !storage_pass {
        return Err("D: free space no longer accommodates projected peak plus 10 percent reserve; artifacts preserved without seal".into());
    }

    let build_receipt = json!({
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E1_PANEL_BUILD_V01",
        "status": "PANEL_BUILT_SUPPORT_AND_STORAGE_GATES_PASS",
        "e0_root_sha256": core["e0_root_sha256"],
        "world_contract_sha256": core["world_contract_sha256"],
        "generator_seed": GENERATOR_SEED,
        "split_seed": SPLIT_SEED,
        "quartets": core["quartets"],
        "input_rows": core["input_rows"],
        "fit_quartets": core["fit_quartets"],
        "test_quartets_by_exact_target_class": core["test_quartets_by_exact_target_class"],
        "generation_enumerations": core["generation_enumerations"],
        "generator_enumeration_seconds": core["generator_enumeration_seconds"],
        "support_receipt_sha256": hash_file(&receipts_dir.join("support-receipt-v01.json"))?.0,
        "support_gate_pass": true,
        "storage_gate_pass": storage_pass,
        "target_volume": "D:",
        "target_volume_total_bytes": total,
        "target_volume_free_bytes_before": free_before,
        "target_volume_free_bytes_after": free_after,
        "projected_peak_bytes": projected_peak,
        "required_free_reserve_bytes": reserve,
        "model_loaded": false,
        "tokenizer_loaded": false,
        "feature_extraction_performed": false,
        "observer_fitting_performed": false,
        "feature_rows": 0,
        "historical_s01_corpus_or_cache_reused": false,
        "status_after_seal": E1_STATUS,
    });
    write_json_new(
        &receipts_dir.join("panel-build-receipt-v01.json"),
        &serde_json::to_vec_pretty(&build_receipt)?,
    )?;

    let entries = collect_entries(output_root)?;
    let root = tree_root(&entries);
    let seal = json!({
        "seal_id": "FAS_FROZEN_OBSERVER_BUNDLE_E1_PANEL_SEAL_V02",
        "status": E1_STATUS,
        "root_sha256": root,
        "entry_count": entries.len(),
        "entries": entries,
        "e0_root_sha256": core["e0_root_sha256"],
        "model_contact_authorized": false,
        "fitting_authorized": false,
        "feature_extraction_performed": false,
        "created_utc_unix_seconds": now_unix_seconds(),
    });
    write_json_new(
        &output_root.join("e1-seal-v01.json"),
        &serde_json::to_vec_pretty(&seal)?,
    )?;
    println!("E1 sealed: root_sha256={root}; model_contact_authorized=false");
    Ok(())
}

fn verify_e0(path: &Path) -> Result<(String, BTreeMap<String, String>), Box<dyn Error>> {
    let seal: Value = read_json(path)?;
    if seal["status"] != E0_STATUS || seal["model_contact_authorized"] != false {
        return Err("E0 manifest is not a frozen no-model-contact seal".into());
    }
    let entries = seal["entries"].as_array().ok_or("E0 entries missing")?;
    let mut verified = Vec::with_capacity(entries.len());
    let mut by_path = BTreeMap::new();
    for item in entries {
        let relative = item["path"].as_str().ok_or("E0 entry path missing")?;
        let relative_path = Path::new(relative);
        if relative_path.is_absolute()
            || relative_path
                .components()
                .any(|part| part == Component::ParentDir)
        {
            return Err("E0 contains a non-local or parent-traversal path".into());
        }
        let (actual_hash, actual_bytes, _) = hash_file(relative_path)?;
        if actual_hash != item["sha256"].as_str().ok_or("E0 entry hash missing")?
            || actual_bytes != item["bytes"].as_u64().ok_or("E0 entry size missing")?
        {
            return Err(format!("E0 input changed: {relative}").into());
        }
        verified.push(FileEntry {
            path: relative.replace('\\', "/"),
            bytes: actual_bytes,
            sha256: actual_hash.clone(),
        });
        by_path.insert(relative.replace('\\', "/"), actual_hash);
    }
    verified.sort_by(|a, b| a.path.cmp(&b.path));
    let actual_root = tree_root(&verified);
    let root = seal["root_sha256"]
        .as_str()
        .ok_or("E0 root missing")?
        .to_owned();
    if actual_root != root {
        return Err("E0 root digest does not match its verified entries".into());
    }
    Ok((root, by_path))
}

fn verify_world_contract(
    world: &Value,
    world_bytes: &[u8],
    e0_entries: &BTreeMap<String, String>,
) -> Result<(), Box<dyn Error>> {
    let relative = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/panel-world-contract-v02.json";
    if world["panel_contract_id"] != "FAS_FROZEN_OBSERVER_BUNDLE_PANEL_WORLD_V02"
        || world["generator_seed"].as_u64() != Some(GENERATOR_SEED)
        || world["quartets"].as_u64() != Some(EXPECTED_QUARTETS as u64)
        || world["input_rows"].as_u64() != Some(EXPECTED_ROWS as u64)
        || world["minimum_test_rows_per_class"].as_u64() != Some(MIN_TEST_ROWS_PER_CLASS)
        || world["construction_authority"]["model_contact_authorized"] != false
        || world["construction_authority"]["observer_fitting_authorized"] != false
    {
        return Err(
            "panel world contract does not match the compiled E1 construction identity".into(),
        );
    }
    let actual = sha256_hex(world_bytes);
    if e0_entries.get(relative) != Some(&actual) {
        return Err("world contract hash is not bound by the E0 seal".into());
    }
    Ok(())
}

fn verify_preflight(output_root: &Path, expected_e0_root: &str) -> Result<(), Box<dyn Error>> {
    let preflight: Value = read_json(&output_root.join("resource-preflight-v01.json"))?;
    let total = preflight["target_volume_total_bytes"].as_u64().unwrap_or(0);
    let free = preflight["target_volume_free_bytes_before"]
        .as_u64()
        .unwrap_or(0);
    let projected = preflight["projected_peak_bytes"]
        .as_u64()
        .unwrap_or(u64::MAX);
    let reserve = preflight["required_free_reserve_bytes"]
        .as_u64()
        .unwrap_or(0);
    if preflight["preflight_status"] != "PASS"
        || preflight["target_volume"] != "D:"
        || preflight["e0_root_sha256"] != expected_e0_root
        || preflight["model_contact_authorized"] != false
        || projected > 4_000_000_000
        || reserve < total / 10
        || free < projected.saturating_add(reserve)
    {
        return Err("resource preflight is missing, stale, or outside the frozen cap".into());
    }
    Ok(())
}

fn ensure_only_preflight_exists(output_root: &Path) -> Result<(), Box<dyn Error>> {
    if !output_root.exists() {
        fs::create_dir_all(output_root)?;
        return Ok(());
    }
    let entries = fs::read_dir(output_root)?;
    for entry in entries {
        let entry = entry?;
        if entry.file_name() != "resource-preflight-v01.json" {
            return Err("E1 run root is not clean; preserving it and refusing to overwrite".into());
        }
    }
    Ok(())
}

fn validate_inventory(inventory: &TermInventory, world: &Value) -> Result<(), Box<dyn Error>> {
    if inventory.context_terms.len() != 32
        || inventory.entity_terms.len() != 32
        || inventory.train_side_style_ids != (0..16).collect::<Vec<u8>>()
        || inventory.novel_heldout_ids != (16..32).collect::<Vec<u8>>()
        || inventory.generator_seed != world["generator_seed"].as_u64().unwrap_or(0)
    {
        return Err("fresh term inventory does not match the frozen 32/16/16 allocation".into());
    }
    let all: HashSet<&str> = inventory
        .context_terms
        .iter()
        .chain(&inventory.entity_terms)
        .map(String::as_str)
        .collect();
    if all.len() != 64
        || inventory
            .context_terms
            .iter()
            .any(|term| term.contains("banu") || term.contains("deki"))
    {
        return Err("term inventory is not a disjoint fresh 64-term allocation".into());
    }
    Ok(())
}

fn build_split_plan() -> Result<Vec<(String, u8, bool)>, Box<dyn Error>> {
    let mut strata: [Vec<(String, String)>; 3] = std::array::from_fn(|_| Vec::new());
    for_each_quartet(|quartet| {
        let key = format!(
            "{SPLIT_SEED}|EXACT_TARGET_STRATIFIED_TEST|{}",
            quartet.quartet_id
        );
        strata[quartet.exact_target as usize]
            .push((sha256_hex(key.as_bytes()), quartet.quartet_id));
        Ok(())
    })?;
    let mut assignments = Vec::with_capacity(EXPECTED_QUARTETS);
    for (class, rows) in strata.iter_mut().enumerate() {
        rows.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.cmp(&b.1)));
        let test_count = rows.len() / 5;
        for (index, (_, quartet_id)) in rows.drain(..).enumerate() {
            assignments.push((quartet_id, class as u8, index < test_count));
        }
    }
    assignments.sort_by(|a, b| a.0.cmp(&b.0));
    Ok(assignments)
}

fn write_quartet_rows(
    quartet: &Quartet,
    is_test: bool,
    input: &mut BufWriter<File>,
    row_manifest: &mut BufWriter<File>,
    fit_labels: &mut BufWriter<File>,
    eval_labels: &mut BufWriter<File>,
    fit_support: &mut BTreeMap<String, EndpointSupport>,
    eval_support: &mut BTreeMap<String, EndpointSupport>,
    rows_seen: &mut usize,
) -> Result<(), Box<dyn Error>> {
    let in_domain =
        quartet.variants[0].context_term_id < 16 && quartet.variants[0].entity_term_id < 16;
    for (variant_index, variant) in quartet.variants.iter().enumerate() {
        let row_id = &variant.event_id;
        write_jsonl(
            input,
            &json!({
                "row_id": row_id,
                "quartet_id": quartet.quartet_id,
                "variant_id": variant.variant_id,
                "input_text": variant.input_text,
            }),
        )?;
        write_jsonl(
            row_manifest,
            &json!({
                "row_index": *rows_seen,
                "row_id": row_id,
                "quartet_id": quartet.quartet_id,
                "variant_id": variant.variant_id,
                "quartet_split": if is_test { "TEST" } else { "FIT" },
            }),
        )?;
        let labels = json!({
            "row_id": row_id,
            "quartet_id": quartet.quartet_id,
            "variant_id": variant.variant_id,
            "context_term_id": variant.context_term_id,
            "entity_term_id": variant.entity_term_id,
            "relation_id": quartet.relation_id,
            "state_id": quartet.state_id,
            "exact_target": quartet.exact_target,
            "both_terms_train_side": in_domain,
            "fit_eligibility": {
                "CONTEXT_IDENTITY": true,
                "ENTITY_IDENTITY": true,
                "RELATION_IDENTITY": in_domain,
                "OBSERVED_STATE": in_domain,
                "EXACT_TARGET": in_domain,
            },
            "score_strata": target_stratum(variant.context_term_id, variant.entity_term_id),
        });
        if is_test {
            write_jsonl(eval_labels, &labels)?;
            count_identity(
                eval_support,
                &variant.context_term_id,
                &variant.entity_term_id,
            );
            if in_domain {
                count_class(eval_support, "RELATION_IDENTITY", quartet.relation_id);
                count_class(eval_support, "OBSERVED_STATE", quartet.state_id);
            }
            let target_endpoint =
                target_stratum_name(variant.context_term_id, variant.entity_term_id);
            count_class(eval_support, target_endpoint, quartet.exact_target);
        } else {
            write_jsonl(fit_labels, &labels)?;
            count_class(fit_support, "CONTEXT_IDENTITY", variant.context_term_id);
            count_class(fit_support, "ENTITY_IDENTITY", variant.entity_term_id);
            if in_domain {
                count_class(fit_support, "RELATION_IDENTITY", quartet.relation_id);
                count_class(fit_support, "OBSERVED_STATE", quartet.state_id);
                count_class(fit_support, "EXACT_TARGET", quartet.exact_target);
            }
        }
        *rows_seen += 1;
        if variant_index >= ROWS_PER_QUARTET {
            return Err("quartet unexpectedly contains more than four variants".into());
        }
    }
    if quartet.variants.len() != ROWS_PER_QUARTET {
        return Err("quartet does not contain exactly four variants".into());
    }
    Ok(())
}

fn target_stratum(context_id: u8, entity_id: u8) -> &'static str {
    match (context_id >= 16, entity_id >= 16) {
        (false, false) => "IN_DOMAIN",
        (true, false) => "CONTEXT_NOVEL",
        (false, true) => "ENTITY_NOVEL",
        (true, true) => "BOTH_NOVEL",
    }
}

fn target_stratum_name(context_id: u8, entity_id: u8) -> &'static str {
    match (context_id >= 16, entity_id >= 16) {
        (false, false) => "EXACT_TARGET_IN_DOMAIN",
        (true, false) => "EXACT_TARGET_CONTEXT_NOVEL",
        (false, true) => "EXACT_TARGET_ENTITY_NOVEL",
        (true, true) => "EXACT_TARGET_BOTH_NOVEL",
    }
}

fn empty_support() -> BTreeMap<String, EndpointSupport> {
    BTreeMap::from([
        (
            "CONTEXT_IDENTITY".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 32],
            },
        ),
        (
            "ENTITY_IDENTITY".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 32],
            },
        ),
        (
            "RELATION_IDENTITY".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 2],
            },
        ),
        (
            "OBSERVED_STATE".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 3],
            },
        ),
        (
            "EXACT_TARGET".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 3],
            },
        ),
    ])
}

fn empty_eval_support() -> BTreeMap<String, EndpointSupport> {
    BTreeMap::from([
        (
            "CONTEXT_IDENTITY".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 32],
            },
        ),
        (
            "ENTITY_IDENTITY".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 32],
            },
        ),
        (
            "RELATION_IDENTITY".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 2],
            },
        ),
        (
            "OBSERVED_STATE".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 3],
            },
        ),
        (
            "EXACT_TARGET_IN_DOMAIN".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 3],
            },
        ),
        (
            "EXACT_TARGET_CONTEXT_NOVEL".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 3],
            },
        ),
        (
            "EXACT_TARGET_ENTITY_NOVEL".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 3],
            },
        ),
        (
            "EXACT_TARGET_BOTH_NOVEL".to_owned(),
            EndpointSupport {
                class_rows: vec![0; 3],
            },
        ),
    ])
}

fn count_identity(support: &mut BTreeMap<String, EndpointSupport>, context: &u8, entity: &u8) {
    count_class(support, "CONTEXT_IDENTITY", *context);
    count_class(support, "ENTITY_IDENTITY", *entity);
}

fn count_class(support: &mut BTreeMap<String, EndpointSupport>, endpoint: &str, class: u8) {
    if let Some(counts) = support.get_mut(endpoint) {
        if let Some(value) = counts.class_rows.get_mut(class as usize) {
            *value += 1;
        }
    }
}

fn support_pass(
    fit: &BTreeMap<String, EndpointSupport>,
    eval: &BTreeMap<String, EndpointSupport>,
) -> bool {
    fit.values()
        .all(|endpoint| endpoint.class_rows.iter().all(|count| *count > 0))
        && eval.values().all(|endpoint| {
            endpoint
                .class_rows
                .iter()
                .all(|count| *count >= MIN_TEST_ROWS_PER_CLASS)
        })
}

fn build_support_receipt(
    fit: &BTreeMap<String, EndpointSupport>,
    eval: &BTreeMap<String, EndpointSupport>,
    pass: bool,
    split_counts: [u64; 3],
) -> Value {
    let fit_support: BTreeMap<_, _> = fit
        .iter()
        .map(|(name, counts)| (name.clone(), counts.class_rows.clone()))
        .collect();
    let eval_support: BTreeMap<_, _> = eval
        .iter()
        .map(|(name, counts)| (name.clone(), counts.class_rows.clone()))
        .collect();
    json!({
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E1_SUPPORT_V01",
        "status": if pass { "PASS" } else { "FAIL_PRESERVED" },
        "fit_class_support": fit_support,
        "test_class_support": eval_support,
        "test_quartets_by_exact_target_class": split_counts,
        "minimum_fit_rows_per_class": 1,
        "minimum_test_rows_per_class": MIN_TEST_ROWS_PER_CLASS,
        "per_class_gate_pass": pass,
        "endpoint_count": 8,
        "support_gate_pass": pass,
        "target_slices_are_separate_endpoints": true,
        "no_bundle_average_or_cross_endpoint_rescue": true,
        "model_loaded": false,
        "tokenizer_loaded": false,
        "feature_extraction_performed": false,
    })
}

fn hash_file(path: &Path) -> Result<(String, u64, u64), Box<dyn Error>> {
    let file = File::open(path)?;
    let bytes = unsafe { MmapOptions::new().map(&file)? };
    let mut digest = Sha256::new();
    digest.update(&bytes);
    let line_count = memchr_iter(b'\n', &bytes).count() as u64;
    Ok((
        format!("{:x}", digest.finalize()),
        bytes.len() as u64,
        line_count,
    ))
}

fn collect_entries(root: &Path) -> Result<Vec<FileEntry>, Box<dyn Error>> {
    let mut paths = Vec::new();
    collect_files(root, root, &mut paths)?;
    paths.sort();
    let mut entries = Vec::with_capacity(paths.len());
    for relative in paths {
        let (sha256, bytes, _) = hash_file(&root.join(&relative))?;
        entries.push(FileEntry {
            path: relative.to_string_lossy().replace('\\', "/"),
            bytes,
            sha256,
        });
    }
    Ok(entries)
}

fn collect_files(
    root: &Path,
    current: &Path,
    output: &mut Vec<PathBuf>,
) -> Result<(), Box<dyn Error>> {
    for entry in fs::read_dir(current)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            collect_files(root, &path, output)?;
        } else if path.file_name().and_then(|name| name.to_str()) != Some("e1-seal-v01.json") {
            output.push(path.strip_prefix(root)?.to_owned());
        }
    }
    Ok(())
}

fn tree_root(entries: &[FileEntry]) -> String {
    let mut ordered = entries.to_vec();
    ordered.sort_by(|a, b| a.path.cmp(&b.path));
    let mut digest = Sha256::new();
    for entry in ordered {
        digest.update(entry.path.as_bytes());
        digest.update(b"\t");
        digest.update(entry.bytes.to_string().as_bytes());
        digest.update(b"\t");
        digest.update(entry.sha256.as_bytes());
        digest.update(b"\n");
    }
    format!("{:x}", digest.finalize())
}

fn read_json(path: &Path) -> Result<Value, Box<dyn Error>> {
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}

fn new_writer(path: &Path) -> Result<BufWriter<File>, Box<dyn Error>> {
    let file = OpenOptions::new().write(true).create_new(true).open(path)?;
    Ok(BufWriter::with_capacity(1 << 20, file))
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), Box<dyn Error>> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    if !bytes.ends_with(b"\n") {
        file.write_all(b"\n")?;
    }
    file.sync_all()?;
    Ok(())
}

fn write_json_new(path: &Path, bytes: &[u8]) -> Result<(), Box<dyn Error>> {
    write_new(path, bytes)
}

fn write_jsonl(writer: &mut BufWriter<File>, value: &Value) -> Result<(), Box<dyn Error>> {
    serde_json::to_writer(&mut *writer, value)?;
    writer.write_all(b"\n")?;
    Ok(())
}

fn finish_writer(writer: &mut BufWriter<File>) -> Result<(), Box<dyn Error>> {
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn now_unix_seconds() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |duration| duration.as_secs())
}

#[cfg(test)]
mod tests {
    use super::{
        MIN_TEST_ROWS_PER_CLASS, empty_eval_support, empty_support, support_pass, target_stratum,
    };

    #[test]
    fn target_strata_follow_the_frozen_16_16_partition() {
        assert_eq!(target_stratum(0, 15), "IN_DOMAIN");
        assert_eq!(target_stratum(16, 15), "CONTEXT_NOVEL");
        assert_eq!(target_stratum(15, 16), "ENTITY_NOVEL");
        assert_eq!(target_stratum(16, 16), "BOTH_NOVEL");
    }

    #[test]
    fn support_gate_requires_every_class_in_every_endpoint() {
        let mut fit = empty_support();
        let mut eval = empty_eval_support();
        for endpoint in fit.values_mut() {
            endpoint.class_rows.fill(1);
        }
        for endpoint in eval.values_mut() {
            endpoint.class_rows.fill(MIN_TEST_ROWS_PER_CLASS);
        }
        assert!(support_pass(&fit, &eval));
        eval.get_mut("EXACT_TARGET_BOTH_NOVEL").unwrap().class_rows[2] -= 1;
        assert!(!support_pass(&fit, &eval));
    }
}
