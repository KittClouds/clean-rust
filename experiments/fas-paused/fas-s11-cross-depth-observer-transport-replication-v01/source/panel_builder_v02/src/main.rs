mod ancestry;
mod generate;
mod model;

use std::collections::BTreeMap;
use std::error::Error;
use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

use ancestry::{Denylist, build_denylist};
use generate::{QUOTAS, SEED, TOTAL_QUARTETS, generate_all, ledger_row, scoped_identity_hash};
use hashbrown::HashSet;
use model::{CandidateLedgerRow, PanelEventRow, Quartet};
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

const PANEL_ID: &str = "fas-s11-fresh-quartet-panel-v02";

#[derive(Serialize)]
struct Authorization {
    authorization_id: &'static str,
    source: &'static str,
    panel_construction_authorized: bool,
    tokenizer_loaded: bool,
    model_loaded: bool,
    feature_extraction_performed: bool,
    observer_replay_performed: bool,
    probe_fitting_performed: bool,
    panel_only_boundary: &'static str,
}

#[derive(Serialize)]
struct ParentCheck {
    parent_id: String,
    expected_root_sha256: String,
    observed_root_sha256: String,
    root_verified: bool,
    relevant_payload_checks: BTreeMap<String, bool>,
}

#[derive(Serialize)]
struct ParentReceipt {
    receipt_id: &'static str,
    status: &'static str,
    checks: Vec<ParentCheck>,
    source_file_hashes: BTreeMap<String, String>,
    tokenizer_loaded: bool,
    model_loaded: bool,
}

#[derive(Serialize)]
struct DenylistReceipt {
    receipt_id: &'static str,
    status: &'static str,
    identity_hash_count: usize,
    input_hash_count: usize,
    identity_hash_file_sha256: String,
    input_hash_file_sha256: String,
    source_rows: Vec<(String, u64)>,
    hash_only: bool,
}

#[derive(Serialize)]
struct ConstructionReceipt {
    receipt_id: &'static str,
    status: &'static str,
    panel_id: &'static str,
    protocol_root_sha256: String,
    panel_correction_json_sha256: String,
    panel_correction_markdown_sha256: String,
    failed_v01_construction_receipt_sha256: String,
    failed_v01_candidate_ledger_sha256: String,
    duplicate_rejected_candidates: usize,
    world_seed_label: &'static str,
    world_seed_label_sha256: String,
    world_seed_u64: u64,
    candidate_quartets: usize,
    selected_quartets: usize,
    selected_event_rows: usize,
    target_class_counts: BTreeMap<String, usize>,
    candidate_ledger_sha256: String,
    selected_quartets_sha256: String,
    selected_events_sha256: String,
    deterministic_repeat_parity: bool,
    independent_semantic_validator_pending: bool,
    tokenizer_loaded: bool,
    model_loaded: bool,
    feature_extraction_performed: bool,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("FAS-S11 panel construction failed closed: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let project = PathBuf::from(args.next().ok_or("missing S11 project directory")?);
    let ancestry_root = PathBuf::from(args.next().ok_or("missing codex-runs directory")?);
    let output = PathBuf::from(args.next().ok_or("missing new panel output directory")?);
    if args.next().is_some() {
        return Err("unexpected extra arguments".into());
    }
    if output.exists() {
        return Err(format!(
            "refusing to overwrite existing construction: {}",
            output.display()
        )
        .into());
    }

    let contract_path = project.join("contracts/s11-confirmatory-contract-v01.json");
    let contract: Value = serde_json::from_slice(&fs::read(&contract_path)?)?;
    let protocol_root = verify_s11_protocol(&project)?;
    verify_collision_amendment(&project, &output, &protocol_root)?;
    let parent_receipt = verify_parents(&project, &ancestry_root, &contract)?;

    let s01_root =
        ancestry_root.join("fas-s01-frozen-sensor-transfer-cartography/s01-2-v01-sealed");
    let s09_root = ancestry_root.join("fas-s09-depthwise-decision-subspace-emergence-v09");
    let s01_corpus = s01_root.join("corpus/counterfactual-quartets-v01.jsonl");
    let s09_rows = s09_root.join("inputs/token-only-feature-rows-v02.jsonl");
    let denylist = build_denylist(&s01_corpus, &s09_rows)?;

    let mut quartets = generate_all();
    if quartets.len() != TOTAL_QUARTETS
        || quartets
            .iter()
            .enumerate()
            .any(|(i, q)| q.ordinal != i as u64)
    {
        return Err("candidate universe ordinal/count invariant failed".into());
    }
    let (selection, duplicate_rejected) = select_panel(&quartets, &denylist)?;
    let repeated = generate_all();
    let repeat_parity = repeated.len() == quartets.len()
        && repeated
            .iter()
            .zip(&quartets)
            .all(|(a, b)| serde_json::to_vec(a).ok() == serde_json::to_vec(b).ok());
    if !repeat_parity {
        return Err("immediate complete-universe regeneration did not reproduce bytes".into());
    }
    let selected_indices: HashSet<usize> = selection.iter().copied().collect();
    let selected: Vec<Quartet> = selection
        .iter()
        .map(|&index| quartets[index].clone())
        .collect();
    let mut candidates: Vec<CandidateLedgerRow> = Vec::with_capacity(quartets.len());
    let mut class_counts = [0_usize; 3];
    let mut selected_input_hashes = HashSet::with_capacity(QUOTAS.iter().sum::<usize>() * 4);
    let mut duplicate_selected_input_count = 0_usize;
    for (index, q) in quartets.iter_mut().enumerate() {
        let identity_fresh = candidate_identity_fresh(q, &denylist);
        let input_hashes_fresh = q
            .variants
            .iter()
            .all(|event| !denylist.input_hashes.contains(&event.input_sha256));
        let is_selected = selected_indices.contains(&index);
        if is_selected {
            class_counts[q.exact_target as usize] += 1;
            for event in &q.variants {
                if !selected_input_hashes.insert(event.input_sha256.clone()) {
                    duplicate_selected_input_count += 1;
                }
            }
        }
        candidates.push(ledger_row(
            q,
            identity_fresh,
            input_hashes_fresh,
            is_selected,
            duplicate_rejected.contains(&index),
        )?);
    }

    // Create-new output preserves any failed construction as a separate, inspectable attempt.
    create_layout(&output)?;
    copy_construction_inputs(&project, &output)?;
    write_json(
        &output.join("authorization-v02.json"),
        &Authorization {
            authorization_id: "FAS-S11-PANEL-CONSTRUCTION-CORRECTION-USER-AUTHORIZATION-V02",
            source: "explicit user authorization for panel construction; versioned collision-admission correction",
            panel_construction_authorized: true,
            tokenizer_loaded: false,
            model_loaded: false,
            feature_extraction_performed: false,
            observer_replay_performed: false,
            probe_fitting_performed: false,
            panel_only_boundary: "stop after panel construction, independent validation, and seal",
        },
    )?;
    write_json(
        &output.join("preflight/parent-verification-v02.json"),
        &parent_receipt,
    )?;
    let denylist_receipt = write_denylist(&output, &denylist)?;
    write_json(
        &output.join("corpus/term-inventory-v02.json"),
        &generate::term_inventory(),
    )?;
    write_jsonl(
        &output.join("corpus/candidate-ledger-v02.jsonl"),
        candidates.iter(),
    )?;
    write_jsonl(
        &output.join("corpus/selected-quartets-v02.jsonl"),
        selected.iter(),
    )?;
    let selected_events: Vec<PanelEventRow> = selected.iter().flat_map(event_rows).collect();
    write_jsonl(
        &output.join("corpus/selected-events-v02.jsonl"),
        selected_events.iter(),
    )?;

    let count_map = BTreeMap::from([
        ("0".to_owned(), class_counts[0]),
        ("1".to_owned(), class_counts[1]),
        ("2".to_owned(), class_counts[2]),
    ]);
    let gate_failures = (class_counts != QUOTAS)
        || selected.len() != 5_318
        || selected_events.len() != 21_272
        || duplicate_selected_input_count != 0
        || candidates.iter().any(|candidate| {
            candidate.selected && (!candidate.identity_fresh || !candidate.input_hashes_fresh)
        });
    let status = if gate_failures {
        "PANEL_CONSTRUCTION_FAIL_CLOSED"
    } else {
        "PANEL_CONSTRUCTED_PENDING_INDEPENDENT_VALIDATION"
    };
    let receipt = ConstructionReceipt {
        receipt_id: "FAS_S11_PANEL_CONSTRUCTION_RECEIPT_V02",
        status,
        panel_id: PANEL_ID,
        protocol_root_sha256: protocol_root,
        panel_correction_json_sha256: sha_file(
            &project.join("amendments/s11-panel-collision-admission-correction-v01.json"),
        )?,
        panel_correction_markdown_sha256: sha_file(
            &project.join("amendments/S11-PANEL-COLLISION-ADMISSION-CORRECTION-V01.md"),
        )?,
        failed_v01_construction_receipt_sha256: sha_file(
            &output
                .parent()
                .ok_or("panel output has no parent")?
                .join("panel-construction-v01/receipts/construction-receipt-v01.json"),
        )?,
        failed_v01_candidate_ledger_sha256: sha_file(
            &output
                .parent()
                .ok_or("panel output has no parent")?
                .join("panel-construction-v01/corpus/candidate-ledger-v01.jsonl"),
        )?,
        duplicate_rejected_candidates: duplicate_rejected.len(),
        world_seed_label: "FAS-S11-V01-WORLD-SEED",
        world_seed_label_sha256: "dc6ba106053b430501713ebcc4f4d5963bfa861a5b2c1d4ca4b0ac58e81c178a"
            .to_owned(),
        world_seed_u64: SEED,
        candidate_quartets: quartets.len(),
        selected_quartets: selected.len(),
        selected_event_rows: selected_events.len(),
        target_class_counts: count_map,
        candidate_ledger_sha256: sha_file(&output.join("corpus/candidate-ledger-v02.jsonl"))?,
        selected_quartets_sha256: sha_file(&output.join("corpus/selected-quartets-v02.jsonl"))?,
        selected_events_sha256: sha_file(&output.join("corpus/selected-events-v02.jsonl"))?,
        deterministic_repeat_parity: repeat_parity,
        independent_semantic_validator_pending: true,
        tokenizer_loaded: false,
        model_loaded: false,
        feature_extraction_performed: false,
    };
    write_json(
        &output.join("receipts/construction-receipt-v02.json"),
        &receipt,
    )?;
    write_json(
        &output.join("preflight/ancestry-denylist-receipt-v02.json"),
        &denylist_receipt,
    )?;
    if gate_failures {
        write_json(
            &output.join("construction-failure-v02.json"),
            &BTreeMap::from([
                ("status", "PANEL_CONSTRUCTION_FAIL_CLOSED"),
                (
                    "duplicate_selected_input_hashes",
                    &duplicate_selected_input_count.to_string(),
                ),
                (
                    "disposition",
                    "preserved without replacement or reselection",
                ),
            ]),
        )?;
        return Err(
            "fixed quota, freshness, row-count, or selected-input uniqueness gate failed".into(),
        );
    }

    println!(
        "S11_PANEL_BUILT status={status} quartets={} rows={} denylist_ids={} denylist_inputs={} selected_duplicate_inputs={duplicate_selected_input_count}",
        selected.len(),
        selected_events.len(),
        denylist.identities.len(),
        denylist.input_hashes.len()
    );
    Ok(())
}

fn select_panel(
    quartets: &[Quartet],
    denylist: &Denylist,
) -> Result<(Vec<usize>, HashSet<usize>), String> {
    let mut by_class: [Vec<(Vec<u8>, u64, usize)>; 3] = std::array::from_fn(|_| Vec::new());
    for (index, q) in quartets.iter().enumerate() {
        if q.exact_target > 2 {
            return Err("exact target class is outside [0,2]".to_owned());
        }
        if !candidate_identity_fresh(q, denylist)
            || q.variants
                .iter()
                .any(|event| denylist.input_hashes.contains(&event.input_sha256))
        {
            continue;
        }
        let key = generate::selection_key(q);
        by_class[q.exact_target as usize].push((
            generate::selection_hash(q.exact_target, &key).to_vec(),
            q.ordinal,
            index,
        ));
    }
    let mut selected = Vec::with_capacity(QUOTAS.iter().sum());
    let mut duplicate_rejected = HashSet::new();
    let mut admitted_inputs = HashSet::with_capacity(QUOTAS.iter().sum::<usize>() * 4);
    for class in 0..3 {
        by_class[class].sort_unstable_by(|a, b| a.0.cmp(&b.0).then(a.1.cmp(&b.1)));
        let mut admitted = 0;
        for (_, _, index) in &by_class[class] {
            if admitted == QUOTAS[class] {
                break;
            }
            let event_hashes: Vec<&str> = quartets[*index]
                .variants
                .iter()
                .map(|event| event.input_sha256.as_str())
                .collect();
            let internal_unique =
                event_hashes.iter().collect::<HashSet<_>>().len() == event_hashes.len();
            if !internal_unique
                || event_hashes
                    .iter()
                    .any(|hash| admitted_inputs.contains(*hash))
            {
                duplicate_rejected.insert(*index);
                continue;
            }
            for hash in event_hashes {
                admitted_inputs.insert(hash.to_owned());
            }
            selected.push(*index);
            admitted += 1;
        }
        if admitted != QUOTAS[class] {
            return Err(format!(
                "collision-aware admission filled {admitted}/{} candidates in exact-target class {class}",
                QUOTAS[class]
            ));
        }
    }
    selected.sort_unstable_by_key(|index| quartets[*index].ordinal);
    Ok((selected, duplicate_rejected))
}

fn candidate_identity_fresh(q: &Quartet, denylist: &Denylist) -> bool {
    !denylist
        .identities
        .contains(&scoped_identity_hash("world", &q.world_id))
        && !denylist
            .identities
            .contains(&scoped_identity_hash("episode", &q.episode_id))
        && !denylist
            .identities
            .contains(&scoped_identity_hash("quartet", &q.quartet_id))
        && q.variants.iter().all(|event| {
            !denylist
                .identities
                .contains(&scoped_identity_hash("event", &event.event_id))
        })
}

fn event_rows(q: &Quartet) -> Vec<PanelEventRow> {
    q.variants
        .iter()
        .map(|event| PanelEventRow {
            ordinal: q.ordinal,
            world_id: q.world_id.clone(),
            episode_id: q.episode_id.clone(),
            quartet_id: q.quartet_id.clone(),
            world_family_id: q.world_family_id,
            track_id: q.track_id.clone(),
            context_split: q.context_split,
            entity_split: q.entity_split,
            latent_regime_id: q.latent_world.regime_id,
            canonical_context_id: q
                .latent_world
                .current_exact_world_state
                .canonical_context_id
                .clone(),
            canonical_entity_id: q
                .latent_world
                .current_exact_world_state
                .canonical_entity_id
                .clone(),
            context_term_id: event.context_term_id,
            context_term: event.context_term.clone(),
            entity_term_id: event.entity_term_id,
            entity_term: event.entity_term.clone(),
            observation_template_id: event.observation_template_id,
            query_template_id: event.query_template_id,
            state_id: q.state_id,
            event_id: event.event_id.clone(),
            variant_id: event.variant_id.clone(),
            exact_target: event.exact_target,
            target_candidate_identity: event.target_candidate_identity,
            candidate_identity_order: event.candidate_identity_order.clone(),
            candidate_text_order: event.candidate_text_order.clone(),
            query_semantics: event.query_semantics.clone(),
            current_exact_world_state: q.latent_world.current_exact_world_state.clone(),
            time_step: q.latent_world.time_step,
            feedback_marker: q.latent_world.feedback_marker.clone(),
            feedback_reveal_step: None,
            render_seed: q.render_seed,
            input_text: event.input_text.clone(),
            input_sha256: event.input_sha256.clone(),
        })
        .collect()
}

fn create_layout(root: &Path) -> Result<(), Box<dyn Error>> {
    fs::create_dir_all(root)?;
    for child in ["preflight", "corpus", "receipts", "inputs"] {
        fs::create_dir(root.join(child))?;
    }
    Ok(())
}

fn verify_collision_amendment(
    project: &Path,
    output: &Path,
    protocol_root: &str,
) -> Result<(), Box<dyn Error>> {
    let amendment_path =
        project.join("amendments/s11-panel-collision-admission-correction-v01.json");
    let amendment: Value = serde_json::from_slice(&fs::read(amendment_path)?)?;
    if amendment["status"] != "FROZEN_CONSTRUCTION_CORRECTION_PRE_MODEL_CONTACT"
        || amendment["parent_protocol_root_sha256"] != protocol_root
        || amendment["authority"]["panel_construction_authorized"] != true
        || amendment["authority"]["tokenizer_loaded"] != false
        || amendment["authority"]["model_loaded"] != false
        || amendment["authority"]["feature_extraction_performed"] != false
        || amendment["trigger"]["duplicate_event_rows"] != 189
        || amendment["trigger"]["repeated_input_hashes"] != 170
    {
        return Err("S11 collision-admission correction identity/authority mismatch".into());
    }
    let attempt = output
        .parent()
        .ok_or("panel v02 output has no parent")?
        .join("panel-construction-v01");
    let old_receipt: Value = serde_json::from_slice(&fs::read(
        attempt.join("receipts/construction-receipt-v01.json"),
    )?)?;
    let old_failure: Value =
        serde_json::from_slice(&fs::read(attempt.join("construction-failure-v01.json"))?)?;
    if old_receipt["status"] != "PANEL_CONSTRUCTION_FAIL_CLOSED"
        || old_failure["status"] != "PANEL_CONSTRUCTION_FAIL_CLOSED"
        || old_failure["duplicate_selected_input_hashes"] != "189"
    {
        return Err("preserved v01 attempt does not match the amended construction failure".into());
    }
    Ok(())
}

fn copy_construction_inputs(project: &Path, output: &Path) -> Result<(), Box<dyn Error>> {
    let files = [
        (
            "FAS-S11-PROTOCOL-V01.md",
            "inputs/protocol/FAS-S11-PROTOCOL-V01.md",
        ),
        (
            "contracts/s11-confirmatory-contract-v01.json",
            "inputs/protocol/s11-confirmatory-contract-v01.json",
        ),
        (
            "seals/protocol-seal-v01.json",
            "inputs/protocol/protocol-seal-v01.json",
        ),
        (
            "amendments/S11-PANEL-COLLISION-ADMISSION-CORRECTION-V01.md",
            "inputs/amendment/S11-PANEL-COLLISION-ADMISSION-CORRECTION-V01.md",
        ),
        (
            "amendments/s11-panel-collision-admission-correction-v01.json",
            "inputs/amendment/s11-panel-collision-admission-correction-v01.json",
        ),
    ];
    fs::create_dir(output.join("inputs/protocol"))?;
    fs::create_dir(output.join("inputs/amendment"))?;
    for (source, target) in files {
        copy_new(&project.join(source), &output.join(target))?;
    }
    Ok(())
}

fn copy_new(source: &Path, target: &Path) -> Result<(), Box<dyn Error>> {
    use std::io::copy;
    let mut source_file = File::open(source)?;
    let mut target_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(target)?;
    copy(&mut source_file, &mut target_file)?;
    target_file.sync_all()?;
    Ok(())
}

fn write_denylist(root: &Path, denylist: &Denylist) -> Result<DenylistReceipt, Box<dyn Error>> {
    let mut identities: Vec<&String> = denylist.identities.iter().collect();
    let mut inputs: Vec<&String> = denylist.input_hashes.iter().collect();
    identities.sort_unstable();
    inputs.sort_unstable();
    let identities_path = root.join("preflight/denylist-identities-v02-sha256.txt");
    let inputs_path = root.join("preflight/denylist-input-v02-sha256.txt");
    write_hash_lines(
        &identities_path,
        identities.iter().map(|value| value.as_str()),
    )?;
    write_hash_lines(&inputs_path, inputs.iter().map(|value| value.as_str()))?;
    Ok(DenylistReceipt {
        receipt_id: "FAS_S11_ANCESTRY_DENYLIST_RECEIPT_V02",
        status: "COMPLETE_HASH_ONLY_DENYLIST",
        identity_hash_count: identities.len(),
        input_hash_count: inputs.len(),
        identity_hash_file_sha256: sha_file(&identities_path)?,
        input_hash_file_sha256: sha_file(&inputs_path)?,
        source_rows: denylist.source_rows.clone(),
        hash_only: true,
    })
}

fn verify_s11_protocol(project: &Path) -> Result<String, Box<dyn Error>> {
    let seal: Value =
        serde_json::from_slice(&fs::read(project.join("seals/protocol-seal-v01.json"))?)?;
    let entries = seal["entries"]
        .as_array()
        .ok_or("protocol seal entries missing")?;
    let mut lines = Vec::with_capacity(entries.len());
    for entry in entries {
        let rel = entry["path"].as_str().ok_or("seal path missing")?;
        let path = project.join(rel.replace('/', std::path::MAIN_SEPARATOR_STR));
        let (digest, size) = sha_file_and_size(&path)?;
        if digest != entry["sha256"].as_str().unwrap_or_default()
            || size != entry["bytes"].as_u64().unwrap_or_default()
        {
            return Err(format!("sealed S11 protocol input changed: {rel}").into());
        }
        lines.push(format!("{}\t{}\t{}\n", rel, size, digest));
    }
    lines.sort_unstable();
    let root = sha256_hex(lines.concat().as_bytes());
    if root != seal["root_sha256"].as_str().unwrap_or_default()
        || root != "9f11fb59d0f01ed12ee9c9f1753ae990ce5bcb20cf4f799d35a11a39079a4598"
    {
        return Err("S11 protocol seal root mismatch".into());
    }
    Ok(root)
}

fn verify_parents(
    project: &Path,
    ancestry: &Path,
    contract: &Value,
) -> Result<ParentReceipt, Box<dyn Error>> {
    let p = &contract["parents"];
    let s01 = ancestry.join("fas-s01-frozen-sensor-transfer-cartography/s01-2-v01-sealed");
    let s09 = ancestry.join("fas-s09-depthwise-decision-subspace-emergence-v09");
    let s10 = ancestry.join("fas-s10-cross-depth-observer-transport-v03");
    let s01_tree = s01.join("seals/result-tree-seal-v01.json");
    let s09_tree = s09.join("result-tree-seal-v09.json");
    let s10_tree = s10.join("result-seal-v03.json");
    let (_s01_seal, s01_root) = verified_seal(&s01_tree)?;
    let (s09_seal, s09_root) = verified_seal(&s09_tree)?;
    let (_s10_seal, s10_root) = verified_seal(&s10_tree)?;
    expect_root(
        &s01_root,
        p["S01_2_construction_root_sha256"]
            .as_str()
            .unwrap_or_default(),
        "S01-2 construction",
    )?;
    expect_root(
        &s09_root,
        p["S09_result_tree_root_sha256"]
            .as_str()
            .unwrap_or_default(),
        "S09 result tree",
    )?;
    expect_root(
        &s10_root,
        p["S10_result_tree_root_sha256"]
            .as_str()
            .unwrap_or_default(),
        "S10 result tree",
    )?;

    let s01_corpus = s01.join("corpus/counterfactual-quartets-v01.jsonl");
    let s01_corpus_sha = sha_file(&s01_corpus)?;
    expect_root(
        &s01_corpus_sha,
        p["S01_2_corpus_sha256"].as_str().unwrap_or_default(),
        "S01-2 corpus",
    )?;
    let s09_rows = s09.join("inputs/token-only-feature-rows-v02.jsonl");
    let s09_rows_sha = sha_file(&s09_rows)?;
    let s09_input_entry = entry_hash(&s09_seal, "inputs/token-only-feature-rows-v02.jsonl")?;
    expect_root(&s09_rows_sha, s09_input_entry, "S09 token-only input rows")?;
    let s09_feature_seal: Value =
        serde_json::from_slice(&fs::read(s09.join("recovery-feature-cache-seal-v03.json"))?)?;
    expect_root(
        s09_feature_seal["root_sha256"].as_str().unwrap_or_default(),
        p["S09_feature_cache_root_sha256"]
            .as_str()
            .unwrap_or_default(),
        "S09 feature cache",
    )?;
    let s09_analysis_seal = s09.join("analysis-v09/analysis-seal-v09.json");
    expect_root(
        &sha_file(&s09_analysis_seal)?,
        p["S09_analysis_seal_file_sha256"]
            .as_str()
            .unwrap_or_default(),
        "S09 analysis seal file",
    )?;
    let s09_protocol_path = s09.join("inputs/project-snapshot/seals/protocol-seal-v09.json");
    let (_, s09_protocol_root) = verified_seal(&s09_protocol_path)?;
    expect_root(
        &s09_protocol_root,
        p["S09_protocol_root_sha256"].as_str().unwrap_or_default(),
        "S09 protocol",
    )?;
    let s10_results = s10.join("S10-TRANSPORT-RESULTS-V03.json");
    let s10_results_sha = sha_file(&s10_results)?;
    expect_root(
        &s10_results_sha,
        p["S10_results_json_sha256"].as_str().unwrap_or_default(),
        "S10 result JSON",
    )?;
    let s10_protocol_path = s10.join("inputs/project-snapshot/protocol-seal-v03.json");
    let (_, s10_protocol_root) = verified_seal(&s10_protocol_path)?;
    expect_root(
        &s10_protocol_root,
        p["S10_protocol_root_sha256"].as_str().unwrap_or_default(),
        "S10 protocol",
    )?;
    let s01_manifest: Value =
        serde_json::from_slice(&fs::read(s01.join("corpus/corpus-manifest-v01.json"))?)?;
    if s01_manifest["quartet_count"].as_u64() != Some(26_624)
        || s01_manifest["rendered_input_count"].as_u64() != Some(106_496)
        || s01_manifest["model_loaded"].as_bool() != Some(false)
        || s01_manifest["tokenizer_loaded"].as_bool() != Some(false)
        || s01_manifest["feature_extraction_performed"].as_bool() != Some(false)
    {
        return Err("S01-2 corpus manifest identity/no-contact gate failed".into());
    }

    let source_specs = [
        (
            "experiments/fas-s01-frozen-sensor-transfer-cartography/s01-2-v01/contracts/world-contract-v01.json",
            "S01_2_world_contract_sha256",
        ),
        (
            "experiments/fas-s01-frozen-sensor-transfer-cartography/s01-2-v01/generator/src/generate.rs",
            "S01_generator_generate_rs_sha256",
        ),
        (
            "experiments/fas-s01-frozen-sensor-transfer-cartography/s01-2-v01/generator/src/model.rs",
            "S01_generator_model_rs_sha256",
        ),
        (
            "experiments/fas-s01-frozen-sensor-transfer-cartography/s01-2-v01/generator/src/validate.rs",
            "S01_generator_validate_rs_sha256",
        ),
        (
            "experiments/fas-s10-cross-depth-observer-transport-v03/source/linear_core.py",
            "S10_linear_core_py_sha256",
        ),
        (
            "experiments/fas-s10-cross-depth-observer-transport-v03/source/run_s10_transport.py",
            "S10_run_transport_py_sha256",
        ),
        (
            "experiments/fas-s10-cross-depth-observer-transport-v03/source/s09_math.py",
            "S09_math_py_sha256",
        ),
    ];
    let repository = project
        .parent()
        .and_then(Path::parent)
        .ok_or("cannot resolve repository root from S11 project path")?;
    let mut source_file_hashes = BTreeMap::new();
    for (relative, key) in source_specs {
        let digest =
            sha_file(&repository.join(relative.replace('/', std::path::MAIN_SEPARATOR_STR)))?;
        expect_root(&digest, p[key].as_str().unwrap_or_default(), relative)?;
        source_file_hashes.insert(relative.to_owned(), digest);
    }

    let checks = vec![
        ParentCheck {
            parent_id: "S01-2".to_owned(),
            expected_root_sha256: p["S01_2_construction_root_sha256"]
                .as_str()
                .unwrap()
                .to_owned(),
            observed_root_sha256: s01_root,
            root_verified: true,
            relevant_payload_checks: BTreeMap::from([("corpus_sha256".to_owned(), true)]),
        },
        ParentCheck {
            parent_id: "S09".to_owned(),
            expected_root_sha256: p["S09_result_tree_root_sha256"]
                .as_str()
                .unwrap()
                .to_owned(),
            observed_root_sha256: s09_root,
            root_verified: true,
            relevant_payload_checks: BTreeMap::from([
                ("token_only_rows_entry_sha256".to_owned(), true),
                ("feature_cache_root_identity".to_owned(), true),
            ]),
        },
        ParentCheck {
            parent_id: "S10".to_owned(),
            expected_root_sha256: p["S10_result_tree_root_sha256"]
                .as_str()
                .unwrap()
                .to_owned(),
            observed_root_sha256: s10_root,
            root_verified: true,
            relevant_payload_checks: BTreeMap::from([("results_json_sha256".to_owned(), true)]),
        },
    ];
    Ok(ParentReceipt {
        receipt_id: "FAS_S11_PANEL_PARENT_VERIFICATION_V01",
        status: "PASS",
        checks,
        source_file_hashes,
        tokenizer_loaded: false,
        model_loaded: false,
    })
}

fn verified_seal(path: &Path) -> Result<(Value, String), Box<dyn Error>> {
    let value: Value = serde_json::from_slice(&fs::read(path)?)?;
    let computed = compute_tree_root(&value)?;
    let stated = value["root_sha256"].as_str().ok_or("parent root missing")?;
    expect_root(&computed, stated, &format!("tree root {}", path.display()))?;
    Ok((value, computed))
}

fn compute_tree_root(seal: &Value) -> Result<String, Box<dyn Error>> {
    let entries = seal["entries"].as_array().ok_or("seal entries missing")?;
    let mut rows: Vec<(String, u64, String)> = Vec::with_capacity(entries.len());
    for entry in entries {
        rows.push((
            entry["path"]
                .as_str()
                .ok_or("entry path missing")?
                .to_owned(),
            entry["bytes"].as_u64().ok_or("entry byte count missing")?,
            entry["sha256"]
                .as_str()
                .ok_or("entry digest missing")?
                .to_owned(),
        ));
    }
    rows.sort_unstable_by(|a, b| a.0.cmp(&b.0));
    let payload = rows
        .iter()
        .map(|(path, bytes, sha)| format!("{path}\t{bytes}\t{sha}\n"))
        .collect::<String>();
    Ok(sha256_hex(payload.as_bytes()))
}

fn entry_hash<'a>(seal: &'a Value, path: &str) -> Result<&'a str, Box<dyn Error>> {
    seal["entries"]
        .as_array()
        .ok_or("parent entries missing")?
        .iter()
        .find(|entry| entry["path"].as_str() == Some(path))
        .and_then(|entry| entry["sha256"].as_str())
        .ok_or_else(|| format!("parent seal lacks {path}").into())
}

fn expect_root(actual: &str, expected: &str, label: &str) -> Result<(), Box<dyn Error>> {
    if actual != expected {
        return Err(format!("{label} hash mismatch: expected {expected}, got {actual}").into());
    }
    Ok(())
}

fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), Box<dyn Error>> {
    let file = OpenOptions::new().write(true).create_new(true).open(path)?;
    let mut writer = BufWriter::new(file);
    serde_json::to_writer_pretty(&mut writer, value)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_jsonl<'a, T, I>(path: &Path, values: I) -> Result<(), Box<dyn Error>>
where
    T: Serialize + 'a,
    I: IntoIterator<Item = &'a T>,
{
    let file = OpenOptions::new().write(true).create_new(true).open(path)?;
    let mut writer = BufWriter::with_capacity(1 << 20, file);
    for value in values {
        serde_json::to_writer(&mut writer, value)?;
        writer.write_all(b"\n")?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_hash_lines<'a, I>(path: &Path, values: I) -> Result<(), Box<dyn Error>>
where
    I: IntoIterator<Item = &'a str>,
{
    let file = OpenOptions::new().write(true).create_new(true).open(path)?;
    let mut writer = BufWriter::with_capacity(1 << 18, file);
    for value in values {
        writer.write_all(value.as_bytes())?;
        writer.write_all(b"\n")?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn sha_file(path: &Path) -> Result<String, Box<dyn Error>> {
    Ok(sha_file_and_size(path)?.0)
}

fn sha_file_and_size(path: &Path) -> Result<(String, u64), Box<dyn Error>> {
    use std::io::Read;
    let mut file = File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 1 << 20];
    let mut size = 0_u64;
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
        size += read as u64;
    }
    Ok((format!("{:x}", digest.finalize()), size))
}

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
