#![recursion_limit = "512"]
#![allow(dead_code)] // Retained shared v08N helpers are not reachable from the R2 CLI.

#[path = "../../../jev-information-density-v08n/generator/src/families.rs"]
mod families;
#[path = "../../../jev-information-density-v08n/generator/src/generator.rs"]
mod generator;

use anyhow::{Context, Result, ensure};
use jev_decision_world_v01 as world;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

use families::{FamilySpec, TRAIN_FAMILY_COUNT};
use generator::{Triplet, build_triplet};

const TRAIN_SEED: u64 = 20_260_922;
const PANEL_SEED: u64 = 1_648_220_319;
const R2_PARTITION: &str = "eval_v08p_r2";
const R1_PARTITION: &str = "eval_v08p_r1";
const ROLES: [&str; 11] = [
    "anchor",
    "fact_flip",
    "sham",
    "neutral_1",
    "neutral_2",
    "neutral_3",
    "neutral_4",
    "neutral_5",
    "neutral_6",
    "neutral_7",
    "neutral_8",
];
const ORIGINAL_ROOT: &str = r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01";
const R1_ROOT: &str = r"D:\codex-runs\jev-information-density-v08p-r1\v0.8P-R1";
const R2_ROOT: &str = r"D:\codex-runs\jev-information-density-v08p-r2\v0.8P-R2";
const TRAIN_SCOPE_IDENTITIES: &str = r"D:\codex-runs\jev-information-density-v08p-r1\v0.8P-R1\replay-attempt-03\training-scope-identities.jsonl";
const PRIOR_PANEL_IDENTITIES: &str = r"D:\codex-runs\jev-information-density-v08p-r1\v0.8P-R1\prior-reconstruction\prior-panel-identities.jsonl";
const R2_EXCLUSIONS: &str = r"D:\codex-runs\jev-information-density-v08p-r2\v0.8P-R2\exclusions\five-field-exclusion-sets.json";
const TRAIN_REPLAY_ROOT: &str =
    r"D:\codex-runs\jev-information-density-v08p-r1\v0.8P-R1\replay-attempt-03";
const V05_DENYLIST: &str = r"D:\codex-runs\jev-information-density-v08p-v05\identity\run-1\canonical-e1-neighborhood-hash-denylist.json";
const V05_ROOT_SEAL: &str = r"C:\code land\clean-rust\experiments\jev-information-density-v08p-v05\provenance\v05-denylist-root-seal-v01.json";
const PRIOR_GENERATOR_RECEIPT: &str =
    r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\generator-receipt.json";
const P_RUN_CONTRACT: &str = r"C:\code land\clean-rust\experiments\jev-information-density-v08p\phase_b\phase-b-p-run-contract-v01.json";
const P_ANALYSIS_CONTRACT: &str = r"C:\code land\clean-rust\experiments\jev-information-density-v08p\phase_b\phase-b-p-analysis-contract-v01.json";
const P_PANEL_CONTRACT: &str = r"C:\code land\clean-rust\experiments\jev-information-density-v08p\phase_a\fresh-panel-contract-v01.json";
const P_CONTRACT_BUNDLE: &str = r"C:\code land\clean-rust\experiments\jev-information-density-v08p\contracts\contract-bundle-seal-v01.json";
const R1_TERMINAL_RECEIPT: &str = r"C:\code land\clean-rust\experiments\jev-information-density-v08p-r1\provenance\r1-terminal-disposition-v01.json";
const V08N_BASE_CONTRACT: &str =
    r"C:\code land\clean-rust\experiments\jev-information-density-v08n\phase-a-v01-contract.json";
const V08N_EVAL_PANEL_CONTRACT: &str = r"C:\code land\clean-rust\experiments\jev-information-density-v08n\eval-panel-v01-contract.json";
const R1_IDENTITY_SCHEMA: &str = r"C:\code land\clean-rust\experiments\jev-information-density-v08p-r1\contracts\identity-schema-r1-v01.json";

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
struct IdentityRow {
    partition_namespace: String,
    family_slug: String,
    family_id: String,
    sequence: u32,
    role: String,
    anchor_id: String,
    world_id: String,
    root_id: String,
    episode_id: String,
    full_rendered_input_hash: String,
    selector_input_hash: String,
}

#[derive(Serialize)]
struct WorldPayload<'a> {
    template_id: &'a str,
    sampled_world_u8: &'a [u8],
    world_sample_seed: u64,
}

#[derive(Serialize)]
struct RootPayload<'a> {
    partition_namespace: &'a str,
    family_slug: &'a str,
    sequence: u32,
    seed: u64,
    anchor_id: &'a str,
    template_id: &'a str,
    context_code: u64,
    world_id_sha256: &'a str,
}

#[derive(Clone, Copy, Serialize)]
struct OccurrenceSelectorInput<'a> {
    schema: &'static str,
    partition_namespace: &'a str,
    family_slug: &'a str,
    triplet_anchor_id: &'a str,
    role: &'a str,
    candidate_order_sha256: &'a str,
}

#[derive(Deserialize)]
struct SelectedNeighborhood {
    anchor_id: String,
    family_id: String,
}

#[derive(Deserialize)]
struct ScopeOccurrence {
    neighborhood_id: String,
    family_id: String,
    role: String,
    episode_id: String,
    input_sha256: String,
}

#[derive(Deserialize)]
struct Denylist {
    schema: String,
    count: usize,
    identity_sha256: Vec<String>,
}

#[derive(Serialize, Deserialize)]
struct ExclusionSets {
    schema: String,
    training_source_sha256: String,
    prior_source_sha256: String,
    e1_denylist_sha256: String,
    training: BTreeMap<String, Vec<String>>,
    prior_panel: BTreeMap<String, Vec<String>>,
    e1_neighborhood_hashes: Vec<String>,
}

fn main() -> Result<()> {
    std::thread::Builder::new()
        .name("jev-v08p-r2-construction".to_string())
        .stack_size(64 * 1024 * 1024)
        .spawn(execute)
        .context("spawn R2 construction worker")?
        .join()
        .map_err(|_| anyhow::anyhow!("R2 construction worker panicked"))?
}

fn execute() -> Result<()> {
    verify_parent_sources()?;
    let mut args = std::env::args().skip(1);
    let mode = args
        .next()
        .context("mode required: materialize-exclusions | admit-panel | final-audit")?;
    let out = PathBuf::from(args.next().context("output directory required")?);
    match mode.as_str() {
        "materialize-exclusions" => materialize_exclusions(&out),
        "admit-panel" => admit_panel(&out),
        "final-audit" => run_final_audit(&out),
        _ => anyhow::bail!("unknown mode: {mode}"),
    }
}

fn materialize_exclusions(out: &Path) -> Result<()> {
    prepare_empty(out)?;
    ensure_hash(
        Path::new(TRAIN_SCOPE_IDENTITIES),
        "0f5cd945f965c291b13375b16367085a8c4f3dced4e5996b0e1ffbadf279d191",
    )?;
    ensure_hash(
        Path::new(PRIOR_PANEL_IDENTITIES),
        "5936d6b4e9d6f651edc0406d844709c99108352459ae90494fa327ed7b110ebf",
    )?;
    ensure_hash(
        Path::new(V05_DENYLIST),
        "50eebeb5790c29b4a75c6f8df849eb4c2865d3c864932bbd7f636b7a0e52a2cd",
    )?;
    let training = read_identity_manifest(PathBuf::from(TRAIN_SCOPE_IDENTITIES))?;
    let prior = read_identity_manifest(PathBuf::from(PRIOR_PANEL_IDENTITIES))?;
    ensure!(
        training.len() == 55_000,
        "training exclusion row count mismatch"
    );
    ensure!(prior.len() == 22_000, "prior exclusion row count mismatch");

    let fields = [
        "world_id",
        "root_id",
        "episode_id",
        "full_rendered_input_hash",
        "selector_input_hash",
    ];
    let mut training_sets = BTreeMap::new();
    let mut prior_sets = BTreeMap::new();
    for field in fields {
        let training_values = training
            .iter()
            .map(|row| identity_field_digest(row, field))
            .collect::<BTreeSet<_>>();
        let prior_values = prior
            .iter()
            .map(|row| identity_field_digest(row, field))
            .collect::<BTreeSet<_>>();
        training_sets.insert(
            field.to_string(),
            training_values.into_iter().collect::<Vec<_>>(),
        );
        prior_sets.insert(
            field.to_string(),
            prior_values.into_iter().collect::<Vec<_>>(),
        );
    }

    let denylist: Denylist = serde_json::from_reader(BufReader::new(File::open(V05_DENYLIST)?))?;
    ensure!(
        denylist.schema == "canonical-neighborhood-id-sha256-set-v01" && denylist.count == 2_000,
        "v05 neighborhood denylist identity mismatch"
    );
    let e1_hashes = denylist
        .identity_sha256
        .into_iter()
        .collect::<BTreeSet<_>>();
    ensure!(
        e1_hashes.len() == 2_000,
        "v05 denylist contains duplicate hashes"
    );

    let sets = ExclusionSets {
        schema: "jev-v08p-r2-five-field-exclusions-v01".into(),
        training_source_sha256: "0f5cd945f965c291b13375b16367085a8c4f3dced4e5996b0e1ffbadf279d191"
            .into(),
        prior_source_sha256: "5936d6b4e9d6f651edc0406d844709c99108352459ae90494fa327ed7b110ebf"
            .into(),
        e1_denylist_sha256: "50eebeb5790c29b4a75c6f8df849eb4c2865d3c864932bbd7f636b7a0e52a2cd"
            .into(),
        training: training_sets,
        prior_panel: prior_sets,
        e1_neighborhood_hashes: e1_hashes.into_iter().collect(),
    };
    let exclusion_path = out.join("five-field-exclusion-sets.json");
    write_json(&exclusion_path, &serde_json::to_value(&sets)?)?;
    let exclusion_sha = sha256_file(&exclusion_path)?;
    write_json(
        &out.join("exclusion-set-receipt.json"),
        &json!({
            "status":"R2_EXCLUSION_SETS_SEALED",
            "exclusion_set_sha256":exclusion_sha,
            "training_source":{"sha256":sets.training_source_sha256,"rows":training.len()},
            "prior_panel_source":{"sha256":sets.prior_source_sha256,"rows":prior.len()},
            "e1_neighborhood_denylist_sha256":sets.e1_denylist_sha256,
            "e1_neighborhood_hash_count":sets.e1_neighborhood_hashes.len(),
            "field_digest_counts":{
                "training":sets.training.iter().map(|(k,v)|(k.clone(),v.len())).collect::<BTreeMap<_,_>>(),
                "prior_panel":sets.prior_panel.iter().map(|(k,v)|(k.clone(),v.len())).collect::<BTreeMap<_,_>>()
            },
            "source_access_audit":"explicit paths and verified SHA-256; application-level reads only",
            "r1_failed_panel_read":false,
            "e1_panel_body_read":false,
            "targets_predictions_metrics_features_read":false,
            "phoenix_access":false
        }),
    )?;
    Ok(())
}

fn identity_field_digest(row: &IdentityRow, field: &str) -> String {
    let value = match field {
        "world_id" => row.world_id.as_str(),
        "root_id" => row.root_id.as_str(),
        "episode_id" => row.episode_id.as_str(),
        "full_rendered_input_hash" => row.full_rendered_input_hash.as_str(),
        "selector_input_hash" => row.selector_input_hash.as_str(),
        _ => unreachable!("static identity field"),
    };
    let domain = format!("jev-v08p-r2-exclusion-v01:{field}:");
    sha256_concat(domain.as_bytes(), value.as_bytes())
}

fn candidate_identity_collisions(
    rows: &[IdentityRow],
    fields: &[&str],
    training: &HashMap<String, HashSet<String>>,
    prior: &HashMap<String, HashSet<String>>,
    admitted: &HashMap<String, HashSet<String>>,
) -> BTreeSet<(String, String, String)> {
    let mut collisions = BTreeSet::new();
    for row in rows {
        for field in fields {
            let digest = identity_field_digest(row, field);
            if training[*field].contains(&digest) {
                collisions.insert(((*field).into(), "training".into(), digest.clone()));
            }
            if prior[*field].contains(&digest) {
                collisions.insert(((*field).into(), "prior_panel".into(), digest.clone()));
            }
            if admitted[*field].contains(&digest) {
                collisions.insert(((*field).into(), "already_admitted_r2".into(), digest));
            }
        }
    }
    collisions
}

fn replay_training(out: &Path) -> Result<()> {
    prepare_empty(out)?;
    let selection_path =
        Path::new(ORIGINAL_ROOT).join("selection/selected-training-neighborhoods.jsonl");
    let scope_path =
        Path::new(ORIGINAL_ROOT).join("shared-feature-cache/training-only-feature-scope.jsonl");
    ensure_hash(
        &Path::new(ORIGINAL_ROOT).join("train-canonical-episodes.jsonl"),
        "212a6caae513b53f014569c9d07aa0aac64b94b2a90f0b01b70aa9b3f6d1e3ff",
    )?;
    ensure_hash(
        &Path::new(ORIGINAL_ROOT).join("train-exact-world-episodes.jsonl"),
        "55ae450f349d591b21b4780cf5c7e88abfbfb4c97c77e6f38c78efd1e06914d7",
    )?;
    ensure_hash(
        &Path::new(ORIGINAL_ROOT).join("train-contrast-certificates.jsonl"),
        "232f8132314a2a3555b499da6a70d07e82a591f072810d5132a0bf77c27be851",
    )?;
    ensure_hash(
        &Path::new(ORIGINAL_ROOT).join("selection/selection-contract.json"),
        "ac02dfaf98f05caca1a1c98b67bcfc551ab182abba77565b24ee4abc232ac226",
    )?;
    ensure_hash(
        &Path::new(ORIGINAL_ROOT).join("selection/selection-receipt.json"),
        "0096e87d0567cadb83ebdefaf74a5661b6950a182c9689ea34a246f19f08d473",
    )?;
    ensure_hash(
        &selection_path,
        "8e2a4a10790aac1e763b253e1fc6acc40022b9ff3b136061f0602e91219804ef",
    )?;
    ensure_hash(
        &scope_path,
        "aa8cba58f4a8ec46ed6ec8eaf0bfbe992b03b9fa58f815b4259d9fdfe2b009f3",
    )?;
    let selected = load_selected(&selection_path)?;
    ensure!(selected.len() == 5_000, "selected neighborhood count drift");

    let mut all_ids = create_writer(out.join("train-all-occurrence-identities.jsonl"))?;
    let mut selected_ids = create_writer(out.join("training-scope-identities.jsonl"))?;
    let mut selected_map: BTreeMap<String, IdentityRow> = BTreeMap::new();
    let mut all_episode_ids = BTreeSet::new();
    let fspecs = families::all_families();
    ensure!(fspecs.len() > TRAIN_FAMILY_COUNT, "family split missing");
    let mut triplets = 0usize;
    let mut occurrences = 0usize;
    let mut canonical_sha = Sha256::new();
    let mut canonical_b3 = blake3::Hasher::new();
    let mut exact_sha = Sha256::new();
    let mut exact_b3 = blake3::Hasher::new();
    let mut cert_sha = Sha256::new();
    let mut cert_b3 = blake3::Hasher::new();
    let mut replay_bytes = [0u64; 3];

    for spec in &fspecs[..TRAIN_FAMILY_COUNT] {
        for sequence in 0..1_000usize {
            let triplet =
                build_triplet(spec, "train", sequence, TRAIN_SEED).with_context(|| {
                    format!("replay train family {} sequence {sequence}", spec.slug)
                })?;
            hash_triplet(
                &mut exact_sha,
                &mut exact_b3,
                &mut replay_bytes[0],
                &triplet.exact_episodes,
            )?;
            hash_triplet(
                &mut canonical_sha,
                &mut canonical_b3,
                &mut replay_bytes[1],
                &triplet.canonical_episodes,
            )?;
            hash_one(
                &mut cert_sha,
                &mut cert_b3,
                &mut replay_bytes[2],
                &triplet.certificate,
            )?;
            for role in ROLES {
                let row = identity_row(&triplet, spec, "train", sequence, TRAIN_SEED, role)?;
                ensure!(
                    all_episode_ids.insert(row.episode_id.clone()),
                    "duplicate generated training episode identity"
                );
                write_jsonl(&mut all_ids, &row)?;
                occurrences += 1;
                if selected.contains_key(&triplet.anchor_id) {
                    ensure!(
                        selected.get(&triplet.anchor_id) == Some(&triplet.family_id),
                        "selection family mismatch"
                    );
                    ensure!(
                        selected_map
                            .insert(row.episode_id.clone(), row.clone())
                            .is_none(),
                        "duplicate selected episode id"
                    );
                    write_jsonl(&mut selected_ids, &row)?;
                }
            }
            triplets += 1;
        }
    }
    flush_all([&mut all_ids, &mut selected_ids])?;
    ensure!(
        triplets == 12_000 && occurrences == 132_000,
        "raw training replay count mismatch"
    );
    ensure!(
        all_episode_ids.len() == 132_000,
        "raw training episode IDs are not unique"
    );
    ensure!(
        selected_map.len() == 55_000,
        "selected sidecar is not 55,000 rows"
    );

    let scope_audit = compare_scope(&scope_path, &mut selected_map)?;
    ensure!(
        selected_map.is_empty(),
        "generated selected identities missing from sealed scope"
    );
    verify_raw_training_hashes(
        [
            hex(&canonical_sha.finalize()),
            hex(&exact_sha.finalize()),
            hex(&cert_sha.finalize()),
        ],
        [
            canonical_b3.finalize().to_hex().to_string(),
            exact_b3.finalize().to_hex().to_string(),
            cert_b3.finalize().to_hex().to_string(),
        ],
        [replay_bytes[1], replay_bytes[0], replay_bytes[2]],
    )?;
    write_json(
        &out.join("training-scope-parity.json"),
        &json!({
            "status":"TRAINING_IDENTITY_REPLAY_PASS",
            "generator_seed":TRAIN_SEED,
            "triplets":triplets,
            "raw_occurrences":occurrences,
            "selected_neighborhoods":selected.len(),
            "selected_occurrences":55_000,
            "raw_corpus_byte_parity":"PASS",
            "selected_scope_identity_parity":scope_audit,
            "targets_or_features_read_by_sidecar":"false",
            "phoenix_access":false
        }),
    )?;
    write_json(
        &out.join("training-source-access-receipt.json"),
        &json!({
            "status":"TRAINING_SOURCE_ACCESS_RECORDED",
            "audit_level":"application-level literal path/read-site receipt; not OS-level file-open telemetry",
            "sources":[
                {"path":selection_path,"sha256":"8e2a4a10790aac1e763b253e1fc6acc40022b9ff3b136061f0602e91219804ef","read":"field-selective anchor_id/family_id parse"},
                {"path":scope_path,"sha256":"aa8cba58f4a8ec46ed6ec8eaf0bfbe992b03b9fa58f815b4259d9fdfe2b009f3","read":"streaming field-selective identity parity parse"},
                {"path":Path::new(ORIGINAL_ROOT).join("train-canonical-episodes.jsonl"),"sha256":"212a6caae513b53f014569c9d07aa0aac64b94b2a90f0b01b70aa9b3f6d1e3ff","read":"hash only; regenerated byte parity source"},
                {"path":Path::new(ORIGINAL_ROOT).join("train-exact-world-episodes.jsonl"),"sha256":"55ae450f349d591b21b4780cf5c7e88abfbfb4c97c77e6f38c78efd1e06914d7","read":"hash only; regenerated byte parity source"},
                {"path":Path::new(ORIGINAL_ROOT).join("train-contrast-certificates.jsonl"),"sha256":"232f8132314a2a3555b499da6a70d07e82a591f072810d5132a0bf77c27be851","read":"hash only; regenerated byte parity source"},
                {"path":Path::new(ORIGINAL_ROOT).join("selection/selection-contract.json"),"sha256":"ac02dfaf98f05caca1a1c98b67bcfc551ab182abba77565b24ee4abc232ac226","read":"hash only"},
                {"path":Path::new(ORIGINAL_ROOT).join("selection/selection-receipt.json"),"sha256":"0096e87d0567cadb83ebdefaf74a5661b6950a182c9689ea34a246f19f08d473","read":"hash only"}
            ],
            "identity_fields_only_from_scope_source":["neighborhood_id","family_id","role","episode_id","input_sha256"],
            "targets_features_predictions_metrics_read":false,
            "phoenix_access":false
        }),
    )?;
    Ok(())
}

fn replay_prior(out: &Path) -> Result<()> {
    prepare_empty(out)?;
    ensure_hash(
        Path::new(PRIOR_GENERATOR_RECEIPT),
        "78de428afb7318074179ff8f674dde055c519624bf78930ce5102b8541a8eae7",
    )?;
    ensure_hash(
        Path::new(V05_DENYLIST),
        "50eebeb5790c29b4a75c6f8df849eb4c2865d3c864932bbd7f636b7a0e52a2cd",
    )?;
    let denylist: Denylist = serde_json::from_reader(BufReader::new(File::open(V05_DENYLIST)?))?;
    ensure!(
        denylist.schema == "canonical-neighborhood-id-sha256-set-v01" && denylist.count == 2_000,
        "v05 denylist identity mismatch"
    );
    let expected: BTreeSet<String> = denylist.identity_sha256.into_iter().collect();
    ensure!(expected.len() == 2_000, "v05 denylist duplicate digest");
    let fspecs = families::all_families();
    let mut hashes = BTreeSet::new();
    let mut identities = create_writer(out.join("prior-panel-identities.jsonl"))?;
    let mut canonical_b3 = blake3::Hasher::new();
    let mut exact_b3 = blake3::Hasher::new();
    let mut certificates_b3 = blake3::Hasher::new();
    let mut replay_bytes = [0u64; 3];
    let mut neighborhoods = 0usize;
    for spec in &fspecs[TRAIN_FAMILY_COUNT..] {
        for sequence in 0..500usize {
            let triplet = build_triplet(spec, "eval", sequence, TRAIN_SEED).with_context(|| {
                format!(
                    "reconstruct prior identity family {} sequence {sequence}",
                    spec.slug
                )
            })?;
            validate_triplet(&triplet, spec, "eval", sequence)?;
            hash_triplet_b3(&mut exact_b3, &mut replay_bytes[0], &triplet.exact_episodes)?;
            hash_triplet_b3(
                &mut canonical_b3,
                &mut replay_bytes[1],
                &triplet.canonical_episodes,
            )?;
            hash_one_b3(
                &mut certificates_b3,
                &mut replay_bytes[2],
                &triplet.certificate,
            )?;
            let id_hash = sha256(triplet.anchor_id.as_bytes());
            ensure!(
                hashes.insert(id_hash.clone()),
                "duplicate reconstructed prior neighborhood identity"
            );
            for role in ROLES {
                write_jsonl(
                    &mut identities,
                    &identity_row(&triplet, spec, "eval", sequence, TRAIN_SEED, role)?,
                )?;
            }
            neighborhoods += 1;
        }
    }
    flush(&mut identities)?;
    ensure!(
        neighborhoods == 2_000 && hashes == expected,
        "reconstructed prior panel does not equal v05 identity denylist"
    );
    ensure!(
        replay_bytes == [86_859_808, 221_638_270, 8_198_000],
        "prior eval replay byte counts differ from bound receipt"
    );
    ensure!(
        exact_b3.finalize().to_hex().as_str()
            == "41824c47591eda8ff4b9bea449500cd78b57985e8c25e4dd05399e0211c215c6",
        "prior eval exact-world replay hash mismatch"
    );
    ensure!(
        canonical_b3.finalize().to_hex().as_str()
            == "b8aef75bcd25a74e1b67bde5c912f065e850b0ec5228e1f68a74a3382ffb263b",
        "prior eval canonical replay hash mismatch"
    );
    ensure!(
        certificates_b3.finalize().to_hex().as_str()
            == "579141483b1ead71d30693493e44cbf62dc94c75690967c3fefb3101838186ba",
        "prior eval certificate replay hash mismatch"
    );
    write_jsonl_hashes(out.join("prior-neighborhood-id-hashes.jsonl"), &hashes)?;
    write_json(
        &out.join("prior-panel-identity-reconstruction.json"),
        &json!({
            "status":"PRIOR_PANEL_IDENTITY_RECONSTRUCTION_PASS",
            "source":"bound v08N generator/family spec replay only; no E1 panel body or E1 model output read",
            "neighborhoods":neighborhoods,
            "episodes":neighborhoods * ROLES.len(),
            "v05_neighborhood_hash_set_exact_match":true,
            "identity_fields":["world_id","root_id","episode_id","full_rendered_input_hash","selector_input_hash"],
            "raw_prior_targets_persisted":false,
            "phoenix_access":false
        }),
    )?;
    write_json(
        &out.join("prior-panel-source-access-receipt.json"),
        &json!({
            "status":"PRIOR_PANEL_SOURCE_ACCESS_RECORDED",
            "audit_level":"application-level literal path/read-site receipt; not OS-level file-open telemetry",
            "sources":[
                {"path":PRIOR_GENERATOR_RECEIPT,"sha256":"78de428afb7318074179ff8f674dde055c519624bf78930ce5102b8541a8eae7","read":"hash only; receipt not parsed"},
                {"path":V05_DENYLIST,"sha256":"50eebeb5790c29b4a75c6f8df849eb4c2865d3c864932bbd7f636b7a0e52a2cd","read":"hash then parse hashed neighborhood identities only"}
            ],
            "e1_panel_or_candidate_content_read":false,
            "e1_targets_predictions_metrics_features_read":false,
            "phoenix_access":false
        }),
    )?;
    Ok(())
}

fn admit_panel(out: &Path) -> Result<()> {
    prepare_empty(out)?;
    let exclusion_path = Path::new(R2_EXCLUSIONS);
    let exclusion_receipt_path = Path::new(R2_ROOT).join("exclusions/exclusion-set-receipt.json");
    let exclusion_receipt: Value =
        serde_json::from_reader(BufReader::new(File::open(exclusion_receipt_path)?))?;
    let bound_exclusion_sha = exclusion_receipt["exclusion_set_sha256"]
        .as_str()
        .context("exclusion receipt has no set hash")?;
    ensure_hash(exclusion_path, bound_exclusion_sha)?;
    let exclusions: ExclusionSets =
        serde_json::from_reader(BufReader::new(File::open(exclusion_path)?))?;
    ensure!(
        exclusions.schema == "jev-v08p-r2-five-field-exclusions-v01",
        "R2 exclusion-set schema mismatch"
    );
    let fields = [
        "world_id",
        "root_id",
        "episode_id",
        "full_rendered_input_hash",
        "selector_input_hash",
    ];
    let training_sets = exclusions
        .training
        .iter()
        .map(|(field, values)| {
            (
                field.clone(),
                values.iter().cloned().collect::<HashSet<_>>(),
            )
        })
        .collect::<HashMap<_, _>>();
    let prior_sets = exclusions
        .prior_panel
        .iter()
        .map(|(field, values)| {
            (
                field.clone(),
                values.iter().cloned().collect::<HashSet<_>>(),
            )
        })
        .collect::<HashMap<_, _>>();
    for field in fields {
        ensure!(
            training_sets.contains_key(field) && prior_sets.contains_key(field),
            "missing exclusion field {field}"
        );
    }
    let e1_denied = exclusions
        .e1_neighborhood_hashes
        .iter()
        .cloned()
        .collect::<HashSet<_>>();
    ensure!(
        e1_denied.len() == 2_000,
        "E1 neighborhood denylist count mismatch"
    );

    let mut exact = create_writer(out.join("panel-exact-world-episodes.jsonl"))?;
    let mut canonical = create_writer(out.join("panel-canonical-episodes.jsonl"))?;
    let mut certificates = create_writer(out.join("panel-contrast-certificates.jsonl"))?;
    let mut identities = create_writer(out.join("panel-occurrence-identities.jsonl"))?;
    let mut neighborhoods = create_writer(out.join("panel-neighborhoods.jsonl"))?;
    let mut feature_scope = create_writer(out.join("panel-feature-scope.jsonl"))?;
    let mut candidate_texts = create_writer(out.join("fresh-candidate-text-manifest.jsonl"))?;
    let mut admission_log = create_writer(out.join("online-admission-log.jsonl"))?;
    let fspecs = families::all_families();
    let mut eval_families: Vec<&FamilySpec> = fspecs[TRAIN_FAMILY_COUNT..].iter().collect();
    eval_families.sort_by_key(|spec| spec.slug);
    for spec in &eval_families {
        for (candidate_order, candidate) in spec.candidates.iter().enumerate() {
            let semantic_id = format!("{}::{}", spec.slug, candidate.suffix);
            let surface = format!("{} — {}", candidate.name, candidate.description);
            write_jsonl(
                &mut candidate_texts,
                &json!({
                    "schema_family_id":format!("jev-v08n-schema:{}", spec.slug),
                    "candidate_semantic_id":semantic_id,
                    "candidate_order":candidate_order,
                    "name":candidate.name,
                    "description":candidate.description,
                    "text":surface,
                    "text_sha256":sha256(surface.as_bytes())
                }),
            )?;
        }
    }

    let mut admitted_sets = fields
        .iter()
        .map(|field| ((*field).to_string(), HashSet::<String>::new()))
        .collect::<HashMap<_, _>>();
    let mut accepted_by_family = BTreeMap::<String, usize>::new();
    let mut rejected_by_family = BTreeMap::<String, usize>::new();
    let mut consumed_by_family = BTreeMap::<String, usize>::new();
    let mut accepted_candidate_keys = BTreeSet::<(String, u32)>::new();
    let mut budget_exhausted = false;
    let mut global_index = 0usize;

    'family_loop: for spec in eval_families {
        let mut family_accepted = 0usize;
        let mut family_rejected = 0usize;
        let mut family_consumed = 0usize;
        for ordinal in 0..700usize {
            if family_accepted == 500 {
                break;
            }
            family_consumed += 1;
            let triplet = build_triplet(spec, R2_PARTITION, ordinal, PANEL_SEED)
                .with_context(|| format!("build R2 family {} ordinal {ordinal}", spec.slug))?;
            validate_triplet(&triplet, spec, R2_PARTITION, ordinal)?;
            validate_semantic_neighborhood(&triplet, ordinal)?;
            let neighborhood_hash = sha256(triplet.anchor_id.as_bytes());
            let mut collision_records = BTreeSet::<(String, String, String)>::new();
            if e1_denied.contains(&neighborhood_hash) {
                collision_records.insert((
                    "neighborhood_id".to_string(),
                    "v05_e1_denylist".to_string(),
                    neighborhood_hash.clone(),
                ));
            }

            let mut identities_for_candidate = Vec::with_capacity(ROLES.len());
            for role in ROLES {
                identities_for_candidate.push(identity_row(
                    &triplet,
                    spec,
                    R2_PARTITION,
                    ordinal,
                    PANEL_SEED,
                    role,
                )?);
            }
            collision_records.extend(candidate_identity_collisions(
                &identities_for_candidate,
                &fields,
                &training_sets,
                &prior_sets,
                &admitted_sets,
            ));

            let accepted = collision_records.is_empty();
            let collision_fields = collision_records
                .iter()
                .map(|(field, _, _)| field.clone())
                .collect::<BTreeSet<_>>();
            write_jsonl(
                &mut admission_log,
                &json!({
                    "candidate_ordinal":ordinal,
                    "family":spec.slug,
                    "accepted":accepted,
                    "rejected":!accepted,
                    "collision_fields":collision_fields,
                    "collisions":collision_records.iter().map(|(field,against,digest)|json!({
                        "field":field,"against":against,"identity_sha256":digest
                    })).collect::<Vec<_>>()
                }),
            )?;

            if !accepted {
                family_rejected += 1;
                continue;
            }

            accepted_candidate_keys.insert((spec.slug.to_string(), ordinal as u32));
            write_triplet(&mut exact, &mut canonical, &mut certificates, &triplet)?;
            for (role_index, role) in ROLES.iter().enumerate() {
                let identity = &identities_for_candidate[role_index];
                write_jsonl(&mut identities, identity)?;
                let episode = &triplet.exact_episodes[role_index];
                write_jsonl(
                    &mut feature_scope,
                    &json!({
                        "index":global_index,
                        "neighborhood_id":triplet.anchor_id,
                        "family_id":triplet.family_id,
                        "family_slug":spec.slug,
                        "sequence":ordinal,
                        "role":role,
                        "episode_id":identity.episode_id,
                        "template_id":episode.template.template_id,
                        "text":episode.renderings[0].text,
                        "input_sha256":identity.full_rendered_input_hash
                    }),
                )?;
                global_index += 1;
                for field in fields {
                    admitted_sets
                        .get_mut(field)
                        .expect("initialized field set")
                        .insert(identity_field_digest(identity, field));
                }
            }
            write_jsonl(
                &mut neighborhoods,
                &json!({
                    "neighborhood_id":triplet.anchor_id,
                    "family_id":triplet.family_id,
                    "family_slug":spec.slug,
                    "sequence":ordinal,
                    "episode_roles":ROLES
                }),
            )?;
            family_accepted += 1;
        }
        accepted_by_family.insert(spec.slug.to_string(), family_accepted);
        rejected_by_family.insert(spec.slug.to_string(), family_rejected);
        consumed_by_family.insert(spec.slug.to_string(), family_consumed);
        if family_accepted != 500 {
            budget_exhausted = true;
            break 'family_loop;
        }
    }

    flush_all([
        &mut exact,
        &mut canonical,
        &mut certificates,
        &mut identities,
        &mut neighborhoods,
        &mut feature_scope,
        &mut candidate_texts,
        &mut admission_log,
    ])?;
    let accepted_total = accepted_by_family.values().sum::<usize>();
    let receipt_status = if budget_exhausted {
        "PANEL_ADMISSION_BUDGET_EXHAUSTED"
    } else {
        "R2_ONLINE_PANEL_ADMISSION_PASS"
    };
    write_json(
        &out.join("online-admission-receipt.json"),
        &json!({
            "status":receipt_status,
            "partition_namespace":R2_PARTITION,
            "seed":PANEL_SEED,
            "maximum_candidate_ordinal_exclusive":700,
            "accepted_by_family":accepted_by_family,
            "rejected_by_family":rejected_by_family,
            "consumed_by_family":consumed_by_family,
            "accepted_total":accepted_total,
            "admitted_occurrences":global_index,
            "e1_neighborhood_denylist_sha256":exclusions.e1_denylist_sha256,
            "whole_neighborhood_online_admission":true,
            "training_and_prior_five_field_collision_rejections_recorded":true,
            "internal_r2_overlap_rejections_recorded":true,
            "feature_extraction":false,
            "training":false,
            "inference":false,
            "phoenix_access":false
        }),
    )?;
    Ok(())
}

fn build_panel(out: &Path) -> Result<()> {
    prepare_empty(out)?;
    ensure_hash(
        Path::new(V05_DENYLIST),
        "50eebeb5790c29b4a75c6f8df849eb4c2865d3c864932bbd7f636b7a0e52a2cd",
    )?;
    let denylist: Denylist = serde_json::from_reader(BufReader::new(File::open(V05_DENYLIST)?))?;
    ensure!(
        denylist.schema == "canonical-neighborhood-id-sha256-set-v01" && denylist.count == 2_000,
        "v05 denylist identity mismatch"
    );
    let denied: HashSet<String> = denylist.identity_sha256.into_iter().collect();
    ensure!(denied.len() == 2_000, "v05 denylist duplicate digest");
    let fspecs = families::all_families();
    let mut exact = create_writer(out.join("panel-exact-world-episodes.jsonl"))?;
    let mut canonical = create_writer(out.join("panel-canonical-episodes.jsonl"))?;
    let mut certificates = create_writer(out.join("panel-contrast-certificates.jsonl"))?;
    let mut identities = create_writer(out.join("panel-occurrence-identities.jsonl"))?;
    let mut neighborhoods = create_writer(out.join("panel-neighborhoods.jsonl"))?;
    let mut feature_scope = create_writer(out.join("panel-feature-scope.jsonl"))?;
    let mut candidate_texts = create_writer(out.join("fresh-candidate-text-manifest.jsonl"))?;
    let mut accepted = BTreeMap::<String, usize>::new();
    let mut rejected = BTreeMap::<String, usize>::new();
    let mut accepted_anchor_hashes = BTreeSet::new();
    let mut eval_families: Vec<&FamilySpec> = fspecs[TRAIN_FAMILY_COUNT..].iter().collect();
    eval_families.sort_by_key(|spec| spec.slug);
    for spec in &eval_families {
        for (candidate_order, candidate) in spec.candidates.iter().enumerate() {
            let semantic_id = format!("{}::{}", spec.slug, candidate.suffix);
            let surface = format!("{} — {}", candidate.name, candidate.description);
            write_jsonl(
                &mut candidate_texts,
                &json!({
                    "schema_family_id":format!("jev-v08n-schema:{}", spec.slug),
                    "candidate_semantic_id":semantic_id,
                    "candidate_order":candidate_order,
                    "name":candidate.name,
                    "description":candidate.description,
                    "text":surface,
                    "text_sha256":sha256(surface.as_bytes())
                }),
            )?;
        }
    }
    let mut global_index = 0usize;

    for spec in eval_families {
        let mut family_accepted = 0usize;
        let mut family_rejected = 0usize;
        for sequence in 0..532usize {
            if family_accepted == 500 {
                break;
            }
            let triplet = build_triplet(spec, R1_PARTITION, sequence, PANEL_SEED)
                .with_context(|| format!("build R1 family {} sequence {sequence}", spec.slug))?;
            let nhash = sha256(triplet.anchor_id.as_bytes());
            if denied.contains(&nhash) {
                family_rejected += 1;
                ensure!(
                    family_rejected <= 32,
                    "fixed collision stream exhausted for {}",
                    spec.slug
                );
                continue;
            }
            validate_triplet(&triplet, spec, R1_PARTITION, sequence)?;
            validate_semantic_neighborhood(&triplet, sequence)?;
            ensure!(
                accepted_anchor_hashes.insert(nhash),
                "duplicate fresh panel neighborhood id"
            );
            write_triplet(&mut exact, &mut canonical, &mut certificates, &triplet)?;
            for (role_index, role) in ROLES.iter().enumerate() {
                write_jsonl(
                    &mut identities,
                    &identity_row(&triplet, spec, R1_PARTITION, sequence, PANEL_SEED, role)?,
                )?;
                let identity =
                    identity_row(&triplet, spec, R1_PARTITION, sequence, PANEL_SEED, role)?;
                let episode = &triplet.exact_episodes[role_index];
                write_jsonl(
                    &mut feature_scope,
                    &json!({
                        "index":global_index,
                        "neighborhood_id":triplet.anchor_id,
                        "family_id":triplet.family_id,
                        "family_slug":spec.slug,
                        "sequence":sequence,
                        "role":role,
                        "episode_id":identity.episode_id,
                        "template_id":episode.template.template_id,
                        "text":episode.renderings[0].text,
                        "input_sha256":identity.full_rendered_input_hash
                    }),
                )?;
                global_index += 1;
            }
            write_jsonl(
                &mut neighborhoods,
                &json!({
                    "neighborhood_id":triplet.anchor_id,
                    "family_id":triplet.family_id,
                    "family_slug":spec.slug,
                    "sequence":sequence,
                    "episode_roles":ROLES
                }),
            )?;
            family_accepted += 1;
        }
        ensure!(
            family_accepted == 500,
            "fixed bounded candidate stream did not yield 500 neighborhoods for {}",
            spec.slug
        );
        accepted.insert(spec.slug.to_string(), family_accepted);
        rejected.insert(spec.slug.to_string(), family_rejected);
    }
    flush_all([
        &mut exact,
        &mut canonical,
        &mut certificates,
        &mut identities,
        &mut neighborhoods,
        &mut feature_scope,
        &mut candidate_texts,
    ])?;
    ensure!(
        accepted_anchor_hashes.len() == 2_000,
        "fresh panel total count mismatch"
    );
    ensure!(
        global_index == 22_000,
        "fresh state feature scope count mismatch"
    );
    write_json(
        &out.join("panel-generation-receipt.json"),
        &json!({
            "status":"R1_PROVISIONAL_PANEL_GENERATED",
            "partition_namespace":R1_PARTITION,
            "seed":PANEL_SEED,
            "candidate_sequences_per_family":532,
            "accepted_by_family":accepted,
            "rejected_e1_id_collisions_by_family":rejected,
            "neighborhood_count":2_000,
            "episode_count":22_000,
            "episode_identity_count":22_000,
            "denylist_sha256":"50eebeb5790c29b4a75c6f8df849eb4c2865d3c864932bbd7f636b7a0e52a2cd",
            "semantic_validation":"PASS",
            "feature_extraction":false,
            "training":false,
            "inference":false,
            "phoenix_access":false
        }),
    )?;
    Ok(())
}

fn validate_triplet(
    triplet: &Triplet,
    spec: &FamilySpec,
    partition: &str,
    sequence: usize,
) -> Result<()> {
    ensure!(triplet.partition == partition, "partition mismatch");
    ensure!(
        triplet.canonical_episodes.len() == ROLES.len(),
        "canonical role count mismatch"
    );
    ensure!(
        triplet.exact_episodes.len() == ROLES.len(),
        "exact role count mismatch"
    );
    ensure!(
        triplet.certificate["anchor_id"].as_str() == Some(triplet.anchor_id.as_str()),
        "certificate anchor mismatch"
    );
    ensure!(
        triplet.certificate["world_family_id"].as_str() == Some(triplet.family_id.as_str()),
        "certificate family mismatch"
    );
    for episode in &triplet.exact_episodes {
        let t = generator::template(spec, partition, sequence % 4);
        world::validate_episode(episode, &t).context("exact solver validation failed")?;
    }
    Ok(())
}

fn validate_semantic_neighborhood(triplet: &Triplet, sequence: usize) -> Result<()> {
    let anchor_episode = &triplet.exact_episodes[0];
    let anchor_schema = &triplet.canonical_episodes[0]["runtime_schema"];
    ensure!(
        anchor_episode
            .template
            .template_id
            .ends_with(&format!("_p{}", sequence % 4)),
        "template profile does not follow frozen sequence allocation"
    );
    let anchor = choice_distribution(&triplet.exact_episodes[0])?;
    let fact = choice_distribution(&triplet.exact_episodes[1])?;
    let anchor_winner = argmax(&anchor);
    let fact_winner = argmax(&fact);
    ensure!(
        anchor_winner != fact_winner,
        "fact-flip exact MAP winner did not change"
    );
    for idx in 2..ROLES.len() {
        let episode = &triplet.exact_episodes[idx];
        let canonical = &triplet.canonical_episodes[idx];
        ensure!(
            episode.sampled_world == anchor_episode.sampled_world,
            "nuisance sibling changed latent world"
        );
        ensure!(
            episode.template == anchor_episode.template,
            "nuisance sibling changed exact-world template"
        );
        ensure!(
            episode.queries == anchor_episode.queries,
            "nuisance sibling changed query semantics"
        );
        ensure!(
            episode.evidence_state.visible_fact_ids
                == anchor_episode.evidence_state.visible_fact_ids,
            "nuisance sibling changed visible evidence inventory"
        );
        ensure!(
            episode.evidence_state.missing_fact_ids
                == anchor_episode.evidence_state.missing_fact_ids,
            "nuisance sibling changed missing evidence inventory"
        );
        ensure!(
            canonical["runtime_schema"] == anchor_schema.clone(),
            "nuisance sibling changed runtime candidate schema/order"
        );
        ensure!(
            episode.perturbation_links.len() == 1,
            "nuisance sibling does not have one intervention link"
        );
        let expected_fact_id = if idx == 2 {
            "ev-sham".to_string()
        } else {
            format!("ev-neutral-{}", idx - 2)
        };
        ensure!(
            episode.perturbation_links[0].affected_fact_ids == [expected_fact_id],
            "nuisance sibling intervention axis is not independent/declared"
        );
        let p = choice_distribution(&triplet.exact_episodes[idx])?;
        ensure!(
            p.len() == anchor.len(),
            "candidate target dimension mismatch"
        );
        ensure!(
            p.iter().zip(&anchor).all(|(a, b)| (a - b).abs() <= 1e-12),
            "same-target nuisance intervention changed exact posterior"
        );
        let a = triplet.exact_episodes[0].renderings[0].text.as_bytes();
        let b = triplet.exact_episodes[idx].renderings[0].text.as_bytes();
        ensure!(
            single_byte_edit(a, b),
            "nuisance view is not a one-byte surface edit"
        );
    }
    let a = triplet.exact_episodes[0].renderings[0].text.as_bytes();
    let f = triplet.exact_episodes[1].renderings[0].text.as_bytes();
    ensure!(
        single_byte_edit(a, f),
        "fact flip is not the contracted one-byte surface edit"
    );
    ensure!(
        triplet.exact_episodes[1].sampled_world == anchor_episode.sampled_world,
        "fact flip changed latent world"
    );
    ensure!(
        triplet.exact_episodes[1].template == anchor_episode.template,
        "fact flip changed template"
    );
    ensure!(
        triplet.exact_episodes[1].queries == anchor_episode.queries,
        "fact flip changed query semantics"
    );
    ensure!(
        triplet.canonical_episodes[1]["runtime_schema"] == anchor_schema.clone(),
        "fact flip changed runtime candidate schema/order"
    );
    ensure!(
        triplet.exact_episodes[1].perturbation_links.len() == 1
            && triplet.exact_episodes[1].perturbation_links[0].affected_fact_ids
                == vec!["ev-focus".to_string()],
        "fact flip intervention identity drift"
    );
    Ok(())
}

fn identity_row(
    triplet: &Triplet,
    spec: &FamilySpec,
    partition: &str,
    sequence: usize,
    seed: u64,
    role: &str,
) -> Result<IdentityRow> {
    let candidate_ids: Vec<String> = triplet.canonical_episodes[0]["runtime_schema"]["candidates"]
        .as_array()
        .context("anchor runtime schema candidate array missing")?
        .iter()
        .map(|candidate| {
            candidate["candidate_semantic_id"]
                .as_str()
                .map(str::to_owned)
                .context("candidate semantic ID missing")
        })
        .collect::<Result<_>>()?;
    ensure!(
        candidate_ids.len() == 4,
        "unexpected runtime candidate count"
    );
    let candidate_order = sha256(&serde_json::to_vec(&candidate_ids)?);
    let selector_input = OccurrenceSelectorInput {
        schema: "jev-information-density/v0.8p-r1-occurrence-selector-v01",
        partition_namespace: partition,
        family_slug: spec.slug,
        triplet_anchor_id: &triplet.anchor_id,
        role,
        candidate_order_sha256: &candidate_order,
    };
    let (exact, canonical) = select_occurrence(triplet, &selector_input)?;
    ensure!(
        canonical["episode_id"].as_str() == Some(exact.episode_id.as_str()),
        "canonical/exact episode ID mismatch"
    );
    ensure!(
        exact.renderings.len() == 1,
        "expected one rendered model input"
    );
    let rendered = exact.renderings[0].text.as_bytes();
    let canonical_render = canonical["state"]["observable"]["content"]
        .as_str()
        .context("canonical rendered input missing")?;
    ensure!(
        rendered == canonical_render.as_bytes(),
        "exact and canonical rendered input bytes differ"
    );
    let episode_candidate_ids: Vec<&str> = canonical["runtime_schema"]["candidates"]
        .as_array()
        .context("candidate array missing")?
        .iter()
        .map(|c| {
            c["candidate_semantic_id"]
                .as_str()
                .context("candidate semantic ID missing")
        })
        .collect::<Result<_>>()?;
    ensure!(
        episode_candidate_ids.len() == 4
            && episode_candidate_ids
                .iter()
                .copied()
                .eq(candidate_ids.iter().map(String::as_str)),
        "candidate semantic order drift"
    );
    let context_code = canonical["workload"]["context_code"]
        .as_u64()
        .context("context code missing")?;
    let world_payload = WorldPayload {
        template_id: &exact.template.template_id,
        sampled_world_u8: &exact.sampled_world,
        world_sample_seed: exact.provenance.world_sample_seed,
    };
    let world_canonical = serde_json::to_vec(&world_payload)?;
    let world_digest = sha256_concat(
        b"jev-information-density-v08p-r1/world/v1\0",
        &world_canonical,
    );
    let root_payload = RootPayload {
        partition_namespace: partition,
        family_slug: spec.slug,
        sequence: sequence as u32,
        seed,
        anchor_id: &triplet.anchor_id,
        template_id: &exact.template.template_id,
        context_code,
        world_id_sha256: &world_digest,
    };
    let root_digest = sha256_concat(
        b"jev-information-density-v08p-r1/root/v1\0",
        &serde_json::to_vec(&root_payload)?,
    );
    let selector_hash = sha256(&serde_json::to_vec(&selector_input)?);
    Ok(IdentityRow {
        partition_namespace: partition.to_string(),
        family_slug: spec.slug.to_string(),
        family_id: triplet.family_id.clone(),
        sequence: sequence as u32,
        role: role.to_string(),
        anchor_id: triplet.anchor_id.clone(),
        world_id: format!("world:sha256:{world_digest}"),
        root_id: format!("root:sha256:{root_digest}"),
        episode_id: exact.episode_id.clone(),
        full_rendered_input_hash: sha256(rendered),
        selector_input_hash: selector_hash,
    })
}

fn select_occurrence<'a>(
    triplet: &'a Triplet,
    request: &OccurrenceSelectorInput<'_>,
) -> Result<(&'a world::Episode, &'a Value)> {
    ensure!(
        triplet.partition == request.partition_namespace,
        "selector partition does not match Triplet"
    );
    ensure!(
        triplet.anchor_id == request.triplet_anchor_id,
        "selector anchor identity does not match Triplet"
    );
    ensure!(
        ROLES.iter().filter(|role| **role == request.role).count() == 1,
        "selector role is absent or duplicated"
    );
    let index = ROLES
        .iter()
        .position(|role| *role == request.role)
        .context("selector role is not declared")?;
    let exact = triplet
        .exact_episodes
        .get(index)
        .context("selector role is absent from exact episode objects")?;
    let canonical = triplet
        .canonical_episodes
        .get(index)
        .context("selector role is absent from canonical episode objects")?;
    ensure!(
        canonical["episode_id"].as_str() == Some(exact.episode_id.as_str()),
        "selector selected inconsistent episode objects"
    );
    let candidate_ids: Vec<&str> = canonical["runtime_schema"]["candidates"]
        .as_array()
        .context("selected candidate array missing")?
        .iter()
        .map(|candidate| {
            candidate["candidate_semantic_id"]
                .as_str()
                .context("selected candidate semantic ID missing")
        })
        .collect::<Result<_>>()?;
    ensure!(
        candidate_ids
            .iter()
            .all(|candidate| candidate.starts_with(&format!("{}::", request.family_slug))),
        "selector family does not match candidate semantics"
    );
    ensure!(
        sha256(&serde_json::to_vec(&candidate_ids)?) == request.candidate_order_sha256,
        "selector candidate order does not match selected episode"
    );
    Ok((exact, canonical))
}

fn run_final_audit(out: &Path) -> Result<()> {
    prepare_empty(out)?;
    let exclusion_path = Path::new(R2_EXCLUSIONS);
    let exclusion_receipt: Value = serde_json::from_reader(BufReader::new(File::open(
        Path::new(R2_ROOT).join("exclusions/exclusion-set-receipt.json"),
    )?))?;
    let bound_exclusion_sha = exclusion_receipt["exclusion_set_sha256"]
        .as_str()
        .context("exclusion receipt has no set hash")?;
    ensure_hash(exclusion_path, bound_exclusion_sha)?;
    let exclusions: ExclusionSets =
        serde_json::from_reader(BufReader::new(File::open(exclusion_path)?))?;
    let fields = [
        "world_id",
        "root_id",
        "episode_id",
        "full_rendered_input_hash",
        "selector_input_hash",
    ];
    let training_sets = exclusions
        .training
        .iter()
        .map(|(field, values)| {
            (
                field.clone(),
                values.iter().cloned().collect::<HashSet<_>>(),
            )
        })
        .collect::<HashMap<_, _>>();
    let prior_sets = exclusions
        .prior_panel
        .iter()
        .map(|(field, values)| {
            (
                field.clone(),
                values.iter().cloned().collect::<HashSet<_>>(),
            )
        })
        .collect::<HashMap<_, _>>();
    let e1_denied = exclusions
        .e1_neighborhood_hashes
        .iter()
        .cloned()
        .collect::<HashSet<_>>();

    let panel = read_identity_manifest(
        PathBuf::from(R2_ROOT).join("panel/panel-occurrence-identities.jsonl"),
    )?;
    let mut groups = BTreeMap::<(String, u32), Vec<IdentityRow>>::new();
    for row in panel {
        groups
            .entry((row.family_slug.clone(), row.sequence))
            .or_default()
            .push(row);
    }

    let mut log_accepted = BTreeSet::<(String, u32)>::new();
    let mut log_rejected = 0usize;
    let mut log_rows = 0usize;
    for line in BufReader::new(File::open(
        Path::new(R2_ROOT).join("panel/online-admission-log.jsonl"),
    )?)
    .lines()
    {
        let value: Value = serde_json::from_str(&line?)?;
        let family = value["family"]
            .as_str()
            .context("admission family missing")?
            .to_string();
        let ordinal = value["candidate_ordinal"]
            .as_u64()
            .context("admission ordinal missing")? as u32;
        if value["accepted"].as_bool() == Some(true) {
            ensure!(
                log_accepted.insert((family, ordinal)),
                "duplicate accepted admission key"
            );
        } else {
            ensure!(
                value["rejected"].as_bool() == Some(true),
                "admission disposition malformed"
            );
            log_rejected += 1;
        }
        log_rows += 1;
    }

    let mut panel_sets = fields
        .iter()
        .map(|field| ((*field).to_string(), HashSet::<String>::new()))
        .collect::<HashMap<_, _>>();
    let mut internal_seen = fields
        .iter()
        .map(|field| ((*field).to_string(), HashSet::<String>::new()))
        .collect::<HashMap<_, _>>();
    let mut internal_intersections = fields
        .iter()
        .map(|field| ((*field).to_string(), 0usize))
        .collect::<HashMap<_, _>>();
    let mut training_intersections = fields
        .iter()
        .map(|field| ((*field).to_string(), 0usize))
        .collect::<HashMap<_, _>>();
    let mut prior_intersections = fields
        .iter()
        .map(|field| ((*field).to_string(), 0usize))
        .collect::<HashMap<_, _>>();
    let mut e1_collisions = 0usize;
    let mut neighborhood_ids = BTreeSet::<String>::new();
    let mut bad_groups = Vec::<String>::new();
    let mut family_counts = BTreeMap::<String, usize>::new();

    for ((family, ordinal), rows) in &groups {
        if rows.len() != ROLES.len() {
            bad_groups.push(format!("{family}:{ordinal}:row_count:{}", rows.len()));
            continue;
        }
        let anchor = &rows[0].anchor_id;
        if !neighborhood_ids.insert(anchor.clone()) {
            bad_groups.push(format!("{family}:{ordinal}:duplicate_neighborhood_id"));
        }
        let roles = rows
            .iter()
            .map(|row| row.role.as_str())
            .collect::<BTreeSet<_>>();
        if rows
            .iter()
            .any(|row| row.anchor_id != *anchor || row.family_slug != *family)
            || roles.len() != ROLES.len()
            || ROLES.iter().any(|role| !roles.contains(role))
        {
            bad_groups.push(format!("{family}:{ordinal}:identity_or_role_mismatch"));
        }
        if e1_denied.contains(&sha256(anchor.as_bytes())) {
            e1_collisions += 1;
        }
        *family_counts.entry(family.clone()).or_default() += 1;

        for field in fields {
            let values = rows
                .iter()
                .map(|row| identity_field_digest(row, field))
                .collect::<BTreeSet<_>>();
            for digest in &values {
                if training_sets[field].contains(digest) {
                    *training_intersections.get_mut(field).unwrap() += 1;
                }
                if prior_sets[field].contains(digest) {
                    *prior_intersections.get_mut(field).unwrap() += 1;
                }
                if !internal_seen.get_mut(field).unwrap().insert(digest.clone()) {
                    *internal_intersections.get_mut(field).unwrap() += 1;
                }
                panel_sets.get_mut(field).unwrap().insert(digest.clone());
            }
        }
    }

    let expected_families = [
        ("exposure_control", 500usize),
        ("respiratory_monitoring", 500usize),
        ("salinity_control", 500usize),
        ("vibration_monitoring", 500usize),
    ]
    .into_iter()
    .collect::<BTreeMap<_, _>>();
    let fields_report = fields
        .iter()
        .map(|field| {
            (
                (*field).to_string(),
                json!({
                    "panel_unique_values":panel_sets[*field].len(),
                    "training_intersections":training_intersections[*field],
                    "prior_panel_intersections":prior_intersections[*field],
                    "internal_r2_cross_neighborhood_intersections":internal_intersections[*field]
                }),
            )
        })
        .collect::<BTreeMap<_, _>>();
    let family_ok = expected_families
        .iter()
        .all(|(family, count)| family_counts.get(*family) == Some(count));
    let overlap_ok = fields.iter().all(|field| {
        training_intersections[*field] == 0
            && prior_intersections[*field] == 0
            && internal_intersections[*field] == 0
    });
    let accepted_keys_equal = log_accepted == groups.keys().cloned().collect::<BTreeSet<_>>();
    let pass = groups.len() == 2_000
        && family_ok
        && bad_groups.is_empty()
        && e1_collisions == 0
        && overlap_ok
        && accepted_keys_equal
        && log_rejected + log_accepted.len() == log_rows;
    let status = if pass {
        "R2_FRESH_PANEL_FINAL_AUDIT_PASS"
    } else {
        "R2_FRESH_PANEL_FINAL_AUDIT_FAIL"
    };
    write_json(
        &out.join("r2-final-panel-audit.json"),
        &json!({
            "status":status,
            "neighborhoods":groups.len(),
            "occurrences":groups.values().map(Vec::len).sum::<usize>(),
            "family_counts":family_counts,
            "family_allocation_pass":family_ok,
            "field_reports":fields_report,
            "e1_neighborhood_id_collisions":e1_collisions,
            "bad_groups":bad_groups,
            "online_admission_keys_equal_final_panel":accepted_keys_equal,
            "admission_log_rows":log_rows,
            "rejected_candidate_count":log_rejected,
            "exclusion_set_sha256":sha256_file(exclusion_path)?,
            "phoenix_access":false
        }),
    )?;
    ensure!(pass, "R2 final online-admission audit failed");
    Ok(())
}

fn run_overlap_audit(out: &Path) -> Result<()> {
    prepare_empty(out)?;
    let train_all = read_identity_manifest(
        Path::new(TRAIN_REPLAY_ROOT).join("train-all-occurrence-identities.jsonl"),
    )?;
    let train_scope = read_identity_manifest(
        Path::new(TRAIN_REPLAY_ROOT).join("training-scope-identities.jsonl"),
    )?;
    let prior = read_identity_manifest(
        Path::new(R1_ROOT).join("prior-reconstruction/prior-panel-identities.jsonl"),
    )?;
    let panel = read_identity_manifest(
        Path::new(R1_ROOT).join("candidate-staging/panel-occurrence-identities.jsonl"),
    )?;
    ensure!(
        train_all.len() == 132_000,
        "training corpus identity row count mismatch"
    );
    ensure!(
        train_scope.len() == 55_000,
        "selected training identity row count mismatch"
    );
    ensure!(
        prior.len() == 22_000,
        "prior panel identity row count mismatch"
    );
    ensure!(
        panel.len() == 22_000,
        "fresh panel identity row count mismatch"
    );
    let fields = [
        "world_id",
        "root_id",
        "episode_id",
        "full_rendered_input_hash",
        "selector_input_hash",
    ];
    let mut report = serde_json::Map::new();
    for field in fields {
        let all_train = identity_values(&train_all, field);
        let selected_train = identity_values(&train_scope, field);
        let prior_values = identity_values(&prior, field);
        let panel_values = identity_values(&panel, field);
        let all_intersection = intersection(&all_train, &panel_values);
        let selected_intersection = intersection(&selected_train, &panel_values);
        let prior_intersection = intersection(&prior_values, &panel_values);
        ensure!(
            all_intersection.is_empty()
                && selected_intersection.is_empty()
                && prior_intersection.is_empty(),
            "five-field overlap failure on {field}"
        );
        report.insert(
            field.to_string(),
            json!({
                "all_raw_training_unique":all_train.len(),
                "selected_training_unique":selected_train.len(),
                "prior_panel_unique":prior_values.len(),
                "fresh_panel_unique":panel_values.len(),
                "raw_training_intersections":0,
                "selected_training_intersections":0,
                "prior_panel_intersections":0
            }),
        );
    }
    write_json(
        &out.join("five-field-overlap-audit.json"),
        &json!({
            "status":"FIVE_FIELD_OVERLAP_PASS",
            "field_reports":report,
            "e1_neighborhood_id_denylist_sha256":"50eebeb5790c29b4a75c6f8df849eb4c2865d3c864932bbd7f636b7a0e52a2cd",
            "v09_rows_or_mappings_used":false,
            "targets_features_predictions_metrics_read":false,
            "phoenix_access":false
        }),
    )?;
    Ok(())
}

fn read_identity_manifest(path: PathBuf) -> Result<Vec<IdentityRow>> {
    let reader = BufReader::with_capacity(1 << 20, File::open(path)?);
    let mut rows = Vec::new();
    for line in reader.lines() {
        rows.push(serde_json::from_str(&line?)?);
    }
    Ok(rows)
}

fn identity_values(rows: &[IdentityRow], field: &str) -> HashSet<String> {
    rows.iter()
        .map(|row| match field {
            "world_id" => row.world_id.clone(),
            "root_id" => row.root_id.clone(),
            "episode_id" => row.episode_id.clone(),
            "full_rendered_input_hash" => row.full_rendered_input_hash.clone(),
            "selector_input_hash" => row.selector_input_hash.clone(),
            _ => unreachable!("static field contract"),
        })
        .collect()
}

fn intersection(a: &HashSet<String>, b: &HashSet<String>) -> Vec<String> {
    a.iter()
        .filter(|value| b.contains(*value))
        .cloned()
        .collect()
}

fn choice_distribution(episode: &world::Episode) -> Result<Vec<f64>> {
    match &episode.gold_targets[0].value {
        world::GoldValue::Choice { probabilities, .. } => {
            Ok(probabilities.iter().map(|p| p.probability).collect())
        }
        _ => anyhow::bail!("expected choice target"),
    }
}

fn argmax(values: &[f64]) -> usize {
    values
        .iter()
        .enumerate()
        .max_by(|a, b| a.1.total_cmp(b.1))
        .map(|(i, _)| i)
        .unwrap_or(0)
}

fn single_byte_edit(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).filter(|(x, y)| x != y).count() == 1
}

fn write_triplet(
    exact: &mut BufWriter<File>,
    canonical: &mut BufWriter<File>,
    cert: &mut BufWriter<File>,
    triplet: &Triplet,
) -> Result<()> {
    for row in &triplet.exact_episodes {
        write_jsonl(exact, row)?;
    }
    for row in &triplet.canonical_episodes {
        write_jsonl(canonical, row)?;
    }
    write_jsonl(cert, &triplet.certificate)
}

fn load_selected(path: &Path) -> Result<HashMap<String, String>> {
    let mut selected = HashMap::with_capacity(5_000);
    for line in BufReader::new(File::open(path)?).lines() {
        let line = line?;
        let row: SelectedNeighborhood = serde_json::from_str(&line)?;
        ensure!(
            selected.insert(row.anchor_id, row.family_id).is_none(),
            "duplicate selected anchor"
        );
    }
    Ok(selected)
}

fn compare_scope(path: &Path, generated: &mut BTreeMap<String, IdentityRow>) -> Result<Value> {
    let mut rows = 0usize;
    let mut bad = 0usize;
    let reader = BufReader::with_capacity(1 << 20, File::open(path)?);
    for line in reader.lines() {
        let line = line?;
        let row: ScopeOccurrence = serde_json::from_str(&line)?;
        let Some(actual) = generated.remove(&row.episode_id) else {
            bad += 1;
            continue;
        };
        if actual.anchor_id != row.neighborhood_id
            || actual.family_id != row.family_id
            || actual.role != row.role
            || actual.full_rendered_input_hash != row.input_sha256
        {
            bad += 1;
        }
        rows += 1;
    }
    ensure!(
        rows == 55_000 && bad == 0,
        "sealed training scope did not match generator identity replay"
    );
    Ok(
        json!({"rows":rows,"mismatches":bad,"remaining_generated_rows":generated.len(),"fields_checked":["neighborhood_id/anchor_id","family_id","role","episode_id","input_sha256/full_rendered_input_hash"]}),
    )
}

fn verify_raw_training_hashes(sha: [String; 3], b3: [String; 3], bytes: [u64; 3]) -> Result<()> {
    let expected = [
        (
            "canonical",
            1_313_795_720u64,
            "212a6caae513b53f014569c9d07aa0aac64b94b2a90f0b01b70aa9b3f6d1e3ff",
            "9a4dc01d563e586ffe9c91dd4fac01bf94d9cafb4b9568c1e164de06105313fd",
        ),
        (
            "exact",
            518_925_239u64,
            "55ae450f349d591b21b4780cf5c7e88abfbfb4c97c77e6f38c78efd1e06914d7",
            "b8f2b41e0fabcc16f9d2b59cd968cd350e738a9156fed3907d89bc721c45ef03",
        ),
        (
            "certificates",
            48_708_000u64,
            "232f8132314a2a3555b499da6a70d07e82a591f072810d5132a0bf77c27be851",
            "e1e10dbd9330a1b7c78af95e53fc307ca8b17accc438bc6faa36e49474aed7b7",
        ),
    ];
    for index in 0..3 {
        ensure!(
            bytes[index] == expected[index].1,
            "raw replay byte length mismatch: {}",
            expected[index].0
        );
        ensure!(
            sha[index] == expected[index].2,
            "raw replay SHA-256 mismatch: {}",
            expected[index].0
        );
        ensure!(
            b3[index] == expected[index].3,
            "raw replay BLAKE3 mismatch: {}",
            expected[index].0
        );
    }
    Ok(())
}

fn hash_triplet<T: Serialize>(
    sha: &mut Sha256,
    b3: &mut blake3::Hasher,
    byte_count: &mut u64,
    rows: &[T],
) -> Result<()> {
    for row in rows {
        hash_one(sha, b3, byte_count, row)?;
    }
    Ok(())
}

fn hash_triplet_b3<T: Serialize>(
    b3: &mut blake3::Hasher,
    byte_count: &mut u64,
    rows: &[T],
) -> Result<()> {
    for row in rows {
        hash_one_b3(b3, byte_count, row)?;
    }
    Ok(())
}

fn hash_one_b3<T: Serialize>(
    b3: &mut blake3::Hasher,
    byte_count: &mut u64,
    value: &T,
) -> Result<()> {
    let bytes = serde_json::to_vec(value)?;
    b3.update(&bytes);
    b3.update(b"\n");
    *byte_count += bytes.len() as u64 + 1;
    Ok(())
}

fn hash_one<T: Serialize>(
    sha: &mut Sha256,
    b3: &mut blake3::Hasher,
    byte_count: &mut u64,
    value: &T,
) -> Result<()> {
    let bytes = serde_json::to_vec(value)?;
    sha.update(&bytes);
    b3.update(&bytes);
    sha.update(b"\n");
    b3.update(b"\n");
    *byte_count += bytes.len() as u64 + 1;
    Ok(())
}

fn ensure_hash(path: &Path, expected: &str) -> Result<()> {
    ensure!(
        sha256_file(path)? == expected,
        "source SHA-256 mismatch: {}",
        path.display()
    );
    Ok(())
}

fn verify_parent_sources() -> Result<()> {
    for (path, expected, label) in [
        (
            P_RUN_CONTRACT,
            "e345225b4a17fc18eb35fcab24cbe1d72bd0e34bed9de272f927a7be461853e6",
            "original P run contract",
        ),
        (
            P_ANALYSIS_CONTRACT,
            "84111122033fda65c84344317cfe3b50639b23be4c71f480ba665c67a23cc939",
            "original P analysis contract",
        ),
        (
            P_PANEL_CONTRACT,
            "ce3b7b97caecb27f3ad99439c0e67dca6e40af5da3db9ca2e356ea5e9f06f823",
            "original P fresh-panel contract",
        ),
        (
            P_CONTRACT_BUNDLE,
            "67cd6b7902111000dc93a0f81f9f20bc05a9c084732705ed8f9ad82fe965fa85",
            "original P contract bundle",
        ),
        (
            R1_TERMINAL_RECEIPT,
            "151e28a629cc6877084b5c4d5395309c3a73e346f5b589d1b0cc588027a6596b",
            "R1 terminal disposition",
        ),
        (
            V08N_BASE_CONTRACT,
            "f72947a53c7df85d12c7d9f91620c0c32925c047b0c556d9298038c80c51f103",
            "v08N base contract",
        ),
        (
            V08N_EVAL_PANEL_CONTRACT,
            "3fa547c0a2490c4cfb5d578a32dffeb8414c35daa5e59ef339ab1e148e2e9cd6",
            "v08N evaluation-panel contract",
        ),
        (
            R1_IDENTITY_SCHEMA,
            "a5d9bf108a1b14d05652b78021a55b74500ed55d6bdc759ff02c09560ea6f7ed",
            "R1 identity schema",
        ),
    ] {
        ensure_hash(Path::new(path), expected).with_context(|| format!("bound {label} changed"))?;
    }
    let bindings = [
        (
            "experiments/jev-information-density-v08n/generator/src/main.rs",
            "503d7cf9ddef1e42a4ef97cd9031ed23c3fabbac0060c0394d1c9919ebe32ea5",
        ),
        (
            "experiments/jev-information-density-v08n/generator/src/generator.rs",
            "f04a9b1d4f6682522e5957be3c0075db4bd7aa4e4e25968650f2ff24a42c7f5b",
        ),
        (
            "experiments/jev-information-density-v08n/generator/src/families.rs",
            "e56885005487b36b573c1bf4d47741413ca72df0992ff62bcf48891eecacb429",
        ),
        (
            "experiments/jev-information-density-v08n/generator/Cargo.toml",
            "b6203ad272dd973c14ab9c09aa5f15574a3ee95e466c1dce5475b6a3f1efcf98",
        ),
        (
            "experiments/jev-information-density-v08n/generator/Cargo.lock",
            "fff5f6d18141df5b3be89302460210c8ed1f3c3153fda2f1c849ec3306b61d2e",
        ),
        (
            "experiments/jev-decision-world-v01/Cargo.toml",
            "69374c00d54dac2251239fb7b3bb289b61cb6a9bca93853e71f6f484691df401",
        ),
        (
            "experiments/jev-decision-world-v01/Cargo.lock",
            "9b6d29d2e86f53360b1cf7226798eb04c9b790a935b6f024063f0e77cf0b6263",
        ),
        (
            "experiments/jev-decision-world-v01/src/exact.rs",
            "8bd90086573eb93a27f8950f35eec994a3f5b51fdeeffc0e3042105b6657a4f3",
        ),
        (
            "experiments/jev-decision-world-v01/src/lib.rs",
            "ace2147a281cb02ba2328ad5e9de84604a4e9b97606e26965ba906fd9b240470",
        ),
        (
            "experiments/jev-decision-world-v01/src/generate.rs",
            "03e636fc35595ce8d2d701a57158cae5b18cf14809426908d1c92c0e71bed67d",
        ),
        (
            "experiments/jev-decision-world-v01/src/families.rs",
            "da2ceacf7a1b921688e3e6dfcc1dc5af2d57c464bbf4d24322fe5e53fa157805",
        ),
        (
            "experiments/jev-decision-world-v01/src/main.rs",
            "341918f219f8ef6fea833958c9b2d2690db80d9d16676611255ba3eb2fc3bf0e",
        ),
        (
            "experiments/jev-decision-world-v01/src/types.rs",
            "49be9b4c2276c3cb9437a9a35295b583b08a13467835b29208f01fc975ea77ee",
        ),
        (
            "experiments/jev-decision-world-v01/src/validate.rs",
            "89e67736bf94ade30a4da4c33ac27ad3f1a5b962509ecd02bc38569e773ba7f3",
        ),
    ];
    for (path, expected) in bindings {
        ensure_hash(Path::new(path), expected)
            .with_context(|| format!("bound parent source changed: {path}"))?;
    }
    ensure_hash(
        Path::new(V05_ROOT_SEAL),
        "272a14e57c2dcf610568381c0c1c4673c7b40e368ac81b07d3e7160e4e5953a2",
    )
    .context("v05 denylist root-seal identity changed")?;
    Ok(())
}

fn sha256_file(path: &Path) -> Result<String> {
    let mut reader = BufReader::with_capacity(1 << 20, File::open(path)?);
    let mut h = Sha256::new();
    let mut buf = [0u8; 1 << 20];
    loop {
        let n = reader.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(hex(&h.finalize()))
}

fn sha256(bytes: &[u8]) -> String {
    hex(&Sha256::digest(bytes))
}
fn sha256_concat(domain: &[u8], bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(domain);
    h.update(bytes);
    hex(&h.finalize())
}
fn hex(bytes: &[u8]) -> String {
    const H: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(H[(b >> 4) as usize] as char);
        out.push(H[(b & 15) as usize] as char);
    }
    out
}

fn prepare_empty(path: &Path) -> Result<()> {
    ensure!(
        !path.exists(),
        "refusing to reuse an existing construction output: {}",
        path.display()
    );
    fs::create_dir_all(path)?;
    Ok(())
}

fn create_writer(path: PathBuf) -> Result<BufWriter<File>> {
    Ok(BufWriter::with_capacity(
        1 << 20,
        OpenOptions::new().write(true).create_new(true).open(path)?,
    ))
}

fn write_jsonl<T: Serialize>(writer: &mut BufWriter<File>, value: &T) -> Result<()> {
    serde_json::to_writer(&mut *writer, value)?;
    writer.write_all(b"\n")?;
    Ok(())
}

fn write_json(path: &Path, value: &Value) -> Result<()> {
    let mut writer = create_writer(path.to_path_buf())?;
    serde_json::to_writer_pretty(&mut writer, value)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

fn flush(writer: &mut BufWriter<File>) -> Result<()> {
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn flush_all<const N: usize>(writers: [&mut BufWriter<File>; N]) -> Result<()> {
    for writer in writers {
        writer.flush()?;
        writer.get_ref().sync_all()?;
    }
    Ok(())
}

fn write_jsonl_hashes(path: PathBuf, hashes: &BTreeSet<String>) -> Result<()> {
    let mut writer = create_writer(path)?;
    for hash in hashes {
        write_jsonl(&mut writer, &json!({"sha256":hash}))?;
    }
    flush(&mut writer)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hashes_are_sha256_lowercase_hex() {
        assert_eq!(
            sha256(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn surface_edit_gate_accepts_one_byte_only() {
        assert!(single_byte_edit(b"marker +", b"marker -"));
        assert!(!single_byte_edit(b"marker +", b"marker ++"));
        assert!(!single_byte_edit(b"marker +", b"marker xy"));
    }

    #[test]
    fn selector_payload_serialization_is_stable_and_role_sensitive() {
        let candidate_order = sha256(b"candidate-order");
        let a = OccurrenceSelectorInput {
            schema: "jev-information-density/v0.8p-r1-occurrence-selector-v01",
            partition_namespace: R2_PARTITION,
            family_slug: "exposure_control",
            triplet_anchor_id: "v08n-eval_v08p_r2-exposure_control-000004",
            role: "sham",
            candidate_order_sha256: &candidate_order,
        };
        let b = OccurrenceSelectorInput {
            role: "neutral_1",
            ..a
        };
        let ah = sha256(&serde_json::to_vec(&a).unwrap());
        let bh = sha256(&serde_json::to_vec(&b).unwrap());
        assert_ne!(ah, bh);
        assert_eq!(ah, sha256(&serde_json::to_vec(&a).unwrap()));
    }

    #[test]
    fn identity_schema_hash_domains_are_separated() {
        let payload = b"same-payload";
        assert_ne!(
            sha256_concat(b"world\0", payload),
            sha256_concat(b"root\0", payload)
        );
    }

    #[test]
    fn online_candidate_admission_rejects_any_one_field_collision() {
        let row = IdentityRow {
            partition_namespace: "r2".into(),
            family_slug: "exposure_control".into(),
            family_id: "family".into(),
            sequence: 7,
            role: "anchor".into(),
            anchor_id: "anchor".into(),
            world_id: "world".into(),
            root_id: "root".into(),
            episode_id: "episode".into(),
            full_rendered_input_hash: "rendered".into(),
            selector_input_hash: "selector".into(),
        };
        let fields = [
            "world_id",
            "root_id",
            "episode_id",
            "full_rendered_input_hash",
            "selector_input_hash",
        ];
        let empty = fields
            .iter()
            .map(|field| ((*field).to_string(), HashSet::new()))
            .collect::<HashMap<_, _>>();
        let mut prior = empty.clone();
        prior
            .get_mut("full_rendered_input_hash")
            .unwrap()
            .insert(identity_field_digest(&row, "full_rendered_input_hash"));
        let collisions = candidate_identity_collisions(&[row], &fields, &empty, &prior, &empty);
        assert_eq!(collisions.len(), 1);
        assert_eq!(
            collisions.iter().next().unwrap().0,
            "full_rendered_input_hash"
        );
        assert_eq!(collisions.iter().next().unwrap().1, "prior_panel");
    }

    #[test]
    fn one_bound_generator_triplet_passes_identity_and_exact_world_validation() {
        let spec = &families::all_families()[TRAIN_FAMILY_COUNT];
        let triplet = build_triplet(spec, R2_PARTITION, 0, PANEL_SEED).unwrap();
        validate_triplet(&triplet, spec, R2_PARTITION, 0).unwrap();
        validate_semantic_neighborhood(&triplet, 0).unwrap();
        let row = identity_row(&triplet, spec, R2_PARTITION, 0, PANEL_SEED, "anchor").unwrap();
        assert!(!row.world_id.is_empty());
        assert!(!row.root_id.is_empty());
        assert!(!row.episode_id.is_empty());
        assert_eq!(row.full_rendered_input_hash.len(), 64);
        assert_eq!(row.selector_input_hash.len(), 64);
    }
}
