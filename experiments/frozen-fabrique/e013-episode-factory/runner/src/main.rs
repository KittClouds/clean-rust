use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use e013_episode_factory::{
    build_episode, materialize_snapshot, BuildEpisodeOptions, EpisodeFamily, GenerationContext,
    MatchedPairContext, RepoSnapshot, RepoTemplate,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Serialize)]
struct BankSeal<'a> {
    schema: &'static str,
    bank_id: &'a str,
    status: &'static str,
    model_contact_authorized: bool,
    protocol_sha256: String,
    protocol_lock_sha256: String,
    construction_contract_sha256: String,
    source_intake_sha256: String,
    seed_receipt_sha256: String,
    seed_sha256: String,
    scratch_root: String,
    cargo_target_dir: String,
    compile_timeout_secs: u64,
    validation_timeout_secs: u64,
    source_files: Vec<FileHash>,
    repositories: Vec<RepoSnapshot>,
    episodes: Vec<EpisodeRoot>,
    cell_empty_counts: BTreeMap<String, usize>,
    total_tasks: usize,
    total_empty_valid: usize,
    total_truth_changing_pairs: usize,
    max_public_frame_bytes: usize,
    root_sha256: String,
}

#[derive(Serialize)]
struct FileHash {
    path: String,
    bytes: u64,
    sha256: String,
}

#[derive(Serialize)]
struct EpisodeRoot {
    episode_id: String,
    task_id: String,
    repo_id: String,
    family_id: String,
    root_sha256: String,
    valid_count: usize,
}

struct Args {
    bank: String,
    output: PathBuf,
    seed_file: PathBuf,
}

#[derive(Deserialize)]
struct SeedReceipt {
    seeds: Vec<SeedEntry>,
}

#[derive(Deserialize)]
struct SeedEntry {
    bank: String,
    sha256: String,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("E013 construction stopped: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args = parse_args()?;
    let base = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("runner has no parent")?
        .to_path_buf();
    let contract_path = base.join("contract-v0.2.json");
    let source_intake_path = base.join("source-intake-v0.1.json");
    let contract_hash = hash_file(&contract_path)?;
    let protocol_sha256 = "840be748b8aed6b9b642c3c622f079a61c847c61d0e5c9842b04a2a229aa6bdc";
    let protocol_lock_sha256 = "9bd4cfeac86e613ddb7f46ef1b4f8ec92d2aedf702b260323822cb3c53e97ba2";
    let program_root = PathBuf::from(r"C:\rd-c\selective-cognition-action-region-program\experiment-013-trust-signal");
    if hash_file(&program_root.join("E013-TRUST-SIGNAL-DEVELOPMENT-PROTOCOL-v0.2.md"))? != protocol_sha256
        || hash_file(&program_root.join("E013-PROTOCOL-LOCK-v0.2.json"))? != protocol_lock_sha256
    {
        return Err("sealed E013 v0.2 protocol or lock drifted".into());
    }
    let source_intake_hash = hash_file(&source_intake_path)?;
    let seed = read_seed(&args.seed_file)?;
    let seed_hash = hash_bytes(&seed);
    let scratch_root = PathBuf::from(env::var_os("E013_SCRATCH_ROOT").ok_or("E013_SCRATCH_ROOT is required")?);
    let cargo_target_dir = PathBuf::from(env::var_os("E013_CARGO_TARGET_DIR").ok_or("E013_CARGO_TARGET_DIR is required")?);
    if !scratch_root.is_dir() || !cargo_target_dir.is_dir() {
        return Err("configured scratch and Cargo target directories must already exist".into());
    }
    let compile_timeout_secs = 120;
    let validation_timeout_secs = 30;
    let seed_receipt_path = base.join("PREGEN-SEED-RECEIPT-v0.2.json");
    let seed_receipt_hash = hash_file(&seed_receipt_path)?;
    let seed_receipt: SeedReceipt = serde_json::from_slice(&fs::read(&seed_receipt_path)?)?;
    let expected_seed = seed_receipt
        .seeds
        .iter()
        .find(|entry| entry.bank == args.bank)
        .ok_or("missing pre-generation seed receipt entry")?;
    if expected_seed.sha256 != seed_hash {
        return Err("seed differs from pre-generation receipt".into());
    }

    let (templates, families, expected_repos, tasks_per_cell, expected_tasks, expected_empty) =
        match args.bank.as_str() {
            "E013-C" => (
                e013_bank_c::repository_templates(),
                e013_bank_c::families(),
                4usize,
                16u16,
                512usize,
                32usize,
            ),
            "E013-D" => (
                e013_bank_d::repository_templates(),
                e013_bank_d::families(),
                6usize,
                12u16,
                576usize,
                48usize,
            ),
            _ => return Err("bank must be E013-C or E013-D".into()),
        };
    if templates.len() != expected_repos || families.len() != 8 {
        return Err("repository/family count differs from contract".into());
    }
    ensure_unique_ids(&templates, &families)?;
    if args.output.exists() {
        return Err(format!("output already exists: {}", args.output.display()).into());
    }
    fs::create_dir_all(&args.output)?;
    let attempt_path = args.output.join("ATTEMPT-IN-PROGRESS.txt");
    write_new(
        &attempt_path,
        format!("bank={}\nmodel_contact_authorized=false\n", args.bank).as_bytes(),
    )?;

    let source_files = hash_source_tree(&base)?;
    let mut repositories = Vec::with_capacity(templates.len());
    let mut episodes = Vec::with_capacity(expected_tasks);
    let mut cell_empty_counts = BTreeMap::new();
    let mut total_truth_changing_pairs = 0usize;
    let mut max_public_frame_bytes = 0usize;
    for template in &templates {
        let snapshot_root = args.output.join("snapshots").join(&template.repo_id);
        if let Some(parent) = snapshot_root.parent() {
            fs::create_dir_all(parent)?;
        }
        let repo = materialize_snapshot(template, &snapshot_root)?;
        repositories.push(repo.clone());
        for family in &families {
            let family_id = family.family_id();
            let cell_id = format!("{}:{}:{}", args.bank, repo.repo_id, family_id);
            let cell_seed = derive_u64(&seed, &[args.bank.as_str(), &repo.repo_id, family_id, "cell"]);
            let empty_ordinal = (cell_seed % u64::from(tasks_per_cell)) as u16;
            let (pair_first, pair_second) = pair_ordinals(cell_seed, empty_ordinal, tasks_per_cell)?;
            let pair_id = opaque_id(&seed, &[args.bank.as_str(), &repo.repo_id, family_id, "pair"]);
            let pair_pool_seed = derive_u64(&seed, &[args.bank.as_str(), &repo.repo_id, family_id, "pair-pool"]);
            let pair_order_seed = derive_u64(&seed, &[args.bank.as_str(), &repo.repo_id, family_id, "pair-order"]);
            let mut pair_rows = Vec::with_capacity(2);
            let mut empty_seen = 0usize;
            for ordinal in 0..tasks_per_cell {
                let ordinal_text = ordinal.to_string();
                let generation_seed = derive_u64(
                    &seed,
                    &[args.bank.as_str(), &repo.repo_id, family_id, &ordinal_text, "generation"],
                );
                let ordinary_order_seed = derive_u64(
                    &seed,
                    &[args.bank.as_str(), &repo.repo_id, family_id, &ordinal_text, "order"],
                );
                let matched_pair = if ordinal == pair_first || ordinal == pair_second {
                    Some(MatchedPairContext {
                        pair_id: pair_id.clone(),
                        member_index: u8::from(ordinal == pair_second),
                        candidate_pool_seed: pair_pool_seed,
                        candidate_order_seed: pair_order_seed,
                    })
                } else {
                    None
                };
                let candidate_order_seed = if matched_pair.is_some() {
                    pair_order_seed
                } else {
                    ordinary_order_seed
                };
                let episode_id = opaque_id(
                    &seed,
                    &[args.bank.as_str(), &repo.repo_id, family_id, &ordinal_text, "episode"],
                );
                let task_id = opaque_id(
                    &seed,
                    &[args.bank.as_str(), &repo.repo_id, family_id, &ordinal_text, "task"],
                );
                let context = GenerationContext {
                    bank_id: args.bank.clone(),
                    family_id: family_id.to_owned(),
                    episode_id: episode_id.clone(),
                    task_id: task_id.clone(),
                    cell_id: cell_id.clone(),
                    cell_task_ordinal: ordinal,
                    cell_task_count: tasks_per_cell,
                    cell_empty_ordinal: empty_ordinal,
                    cell_seed,
                    generation_seed,
                    candidate_order_seed,
                    repo: repo.clone(),
                    repo_snapshot_root: snapshot_root.clone(),
                    matched_pair: matched_pair.clone(),
                };
                let draft = family.generate(&context)?;
                let public_frame_bytes = draft.task.text.len()
                    + draft.candidates.iter().map(|candidate| candidate.unified_diff.len()).sum::<usize>()
                    + draft.visible_evidence.iter().map(|asset| asset.bytes.len()).sum::<usize>()
                    + draft.visible_fixtures.iter().map(|asset| asset.bytes.len()).sum::<usize>();
                max_public_frame_bytes = max_public_frame_bytes.max(public_frame_bytes);
                let result = build_episode(
                    &context,
                    &draft,
                    &BuildEpisodeOptions {
                        output_dir: args.output.join("episodes").join(&episode_id),
                        protocol_sha256: protocol_sha256.to_owned(),
                        protocol_lock_sha256: protocol_lock_sha256.to_owned(),
                        construction_contract_sha256: contract_hash.clone(),
                        scratch_root: scratch_root.clone(),
                        cargo_target_dir: cargo_target_dir.clone(),
                        compile_timeout_secs,
                        validation_timeout_secs,
                    },
                )?;
                let valid_count = result.private_receipt.valid_candidate_ids.len();
                if valid_count == 0 {
                    empty_seen += 1;
                }
                if (ordinal == empty_ordinal) != (valid_count == 0) {
                    return Err(format!("empty-valid assignment failed in {cell_id}").into());
                }
                if matched_pair.is_some() {
                    pair_rows.push((
                        result.manifest.candidates.iter().map(|record| record.patch_sha256.clone()).collect::<Vec<_>>(),
                        result.manifest.candidate_order.clone(),
                        result.private_receipt.valid_candidate_ids.clone(),
                    ));
                }
                episodes.push(EpisodeRoot {
                    episode_id,
                    task_id,
                    repo_id: repo.repo_id.clone(),
                    family_id: family_id.to_owned(),
                    root_sha256: result.seal.root_sha256,
                    valid_count,
                });
            }
            if empty_seen != 1 {
                return Err(format!("cell {cell_id} has {empty_seen} empty-valid tasks").into());
            }
            if pair_rows.len() != 2
                || pair_rows[0].0 != pair_rows[1].0
                || pair_rows[0].1 != pair_rows[1].1
                || pair_rows[0].2.is_empty()
                || pair_rows[1].2.is_empty()
                || pair_rows[0].2 == pair_rows[1].2
            {
                return Err(format!("truth-changing pair invariant failed in {cell_id}").into());
            }
            total_truth_changing_pairs += 1;
            cell_empty_counts.insert(cell_id, empty_seen);
        }
    }
    let total_empty_valid = episodes.iter().filter(|episode| episode.valid_count == 0).count();
    if episodes.len() != expected_tasks || total_empty_valid != expected_empty {
        return Err("bank totals differ from contract".into());
    }
    let mut seal = BankSeal {
        schema: "e013-bank-seal/v0.1",
        bank_id: &args.bank,
        status: "CONSTRUCTION_SEALED_PENDING_INDEPENDENT_AUDIT",
        model_contact_authorized: false,
        protocol_sha256: protocol_sha256.to_owned(),
        protocol_lock_sha256: protocol_lock_sha256.to_owned(),
        construction_contract_sha256: contract_hash,
        source_intake_sha256: source_intake_hash,
        seed_receipt_sha256: seed_receipt_hash,
        seed_sha256: seed_hash,
        scratch_root: scratch_root.to_string_lossy().into_owned(),
        cargo_target_dir: cargo_target_dir.to_string_lossy().into_owned(),
        compile_timeout_secs,
        validation_timeout_secs,
        source_files,
        repositories,
        episodes,
        cell_empty_counts,
        total_tasks: expected_tasks,
        total_empty_valid,
        total_truth_changing_pairs,
        max_public_frame_bytes,
        root_sha256: String::new(),
    };
    seal.root_sha256 = hash_bytes(&serde_json::to_vec(&seal)?);
    write_new(
        &args.output.join("BANK-SEAL-v0.2.json"),
        &serde_json::to_vec_pretty(&seal)?,
    )?;
    fs::remove_file(attempt_path)?;
    println!("{} root {}", args.bank, seal.root_sha256);
    Ok(())
}

fn parse_args() -> Result<Args, Box<dyn std::error::Error>> {
    let mut values = env::args().skip(1);
    let bank = values.next().ok_or("usage: e013-bank-runner E013-C|E013-D OUTPUT SEED_FILE")?;
    let output = PathBuf::from(values.next().ok_or("missing output path")?);
    let seed_file = PathBuf::from(values.next().ok_or("missing seed file")?);
    if values.next().is_some() {
        return Err("unexpected extra argument".into());
    }
    Ok(Args { bank, output, seed_file })
}

fn read_seed(path: &Path) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let bytes = fs::read(path)?;
    if bytes.len() < 32 {
        return Err("seed file must contain at least 32 random bytes".into());
    }
    Ok(bytes)
}

fn derive_u64(seed: &[u8], parts: &[&str]) -> u64 {
    let mut hash = Sha256::new();
    hash.update(seed);
    for part in parts {
        hash.update((part.len() as u64).to_le_bytes());
        hash.update(part.as_bytes());
    }
    u64::from_le_bytes(hash.finalize()[..8].try_into().expect("sha256 has eight bytes"))
}

fn opaque_id(seed: &[u8], parts: &[&str]) -> String {
    let mut hash = Sha256::new();
    hash.update(seed);
    for part in parts {
        hash.update((part.len() as u64).to_le_bytes());
        hash.update(part.as_bytes());
    }
    let digest = hash.finalize();
    digest[..16].iter().map(|byte| format!("{byte:02x}")).collect()
}

fn pair_ordinals(cell_seed: u64, empty: u16, count: u16) -> Result<(u16, u16), Box<dyn std::error::Error>> {
    if count < 3 {
        return Err("at least three tasks per cell required for a nonempty pair".into());
    }
    let choices = (0..count).filter(|ordinal| *ordinal != empty).collect::<Vec<_>>();
    let first_index = ((cell_seed >> 8) as usize) % choices.len();
    let second_offset = 1 + (((cell_seed >> 24) as usize) % (choices.len() - 1));
    let second_index = (first_index + second_offset) % choices.len();
    Ok((choices[first_index], choices[second_index]))
}

fn ensure_unique_ids(
    templates: &[RepoTemplate],
    families: &[Box<dyn EpisodeFamily>],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut repos = BTreeSet::new();
    for template in templates {
        if !repos.insert(&template.repo_id) {
            return Err("duplicate repository ID".into());
        }
    }
    let mut family_ids = BTreeSet::new();
    for family in families {
        if !family_ids.insert(family.family_id()) {
            return Err("duplicate family ID".into());
        }
    }
    Ok(())
}

fn hash_source_tree(base: &Path) -> Result<Vec<FileHash>, Box<dyn std::error::Error>> {
    let mut paths = Vec::new();
    for root in [base.join("factory/src"), base.join("families/c/src"), base.join("families/d/src"), base.join("runner/src")] {
        if root.exists() {
            visit_files(&root, &mut paths)?;
        }
    }
    paths.sort();
    paths
        .into_iter()
        .map(|path| {
            let relative = path.strip_prefix(base)?.to_string_lossy().replace('\\', "/");
            let bytes = fs::metadata(&path)?.len();
            let sha256 = hash_file(&path)?;
            Ok(FileHash { path: relative, bytes, sha256 })
        })
        .collect()
}

fn visit_files(dir: &Path, output: &mut Vec<PathBuf>) -> Result<(), Box<dyn std::error::Error>> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            visit_files(&path, output)?;
        } else if path.is_file() {
            output.push(path);
        }
    }
    Ok(())
}

fn hash_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut file = File::open(path)?;
    let mut hash = Sha256::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        hash.update(&buffer[..count]);
    }
    Ok(format!("{:x}", hash.finalize()))
}

fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{derive_u64, opaque_id, pair_ordinals};

    #[test]
    fn namespaced_seeds_do_not_collide_across_banks_or_purposes() {
        let seed = [7u8; 32];
        let c = derive_u64(&seed, &["E013-C", "repo", "family", "0", "generation"]);
        let d = derive_u64(&seed, &["E013-D", "repo", "family", "0", "generation"]);
        let order = derive_u64(&seed, &["E013-C", "repo", "family", "0", "order"]);
        assert_ne!(c, d);
        assert_ne!(c, order);
        assert_eq!(c, derive_u64(&seed, &["E013-C", "repo", "family", "0", "generation"]));
    }

    #[test]
    fn opaque_ids_hide_ordinal_and_are_stable() {
        let seed = [23u8; 32];
        let first = opaque_id(&seed, &["E013-C", "repo", "family", "0", "episode"]);
        let second = opaque_id(&seed, &["E013-C", "repo", "family", "1", "episode"]);
        assert_eq!(first.len(), 32);
        assert_ne!(first, second);
        assert_eq!(first, opaque_id(&seed, &["E013-C", "repo", "family", "0", "episode"]));
        assert!(first.bytes().all(|byte| byte.is_ascii_hexdigit()));
    }

    #[test]
    fn pair_members_are_distinct_and_avoid_empty_slot() {
        for count in [12, 16] {
            for empty in 0..count {
                let (first, second) = pair_ordinals(0x4afe_b831_7d63_9912, empty, count).unwrap();
                assert_ne!(first, second);
                assert_ne!(first, empty);
                assert_ne!(second, empty);
                assert!(first < count && second < count);
            }
        }
    }
}
