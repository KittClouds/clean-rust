use std::error::Error;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use r1_stage1_stress_worlds_v03::{
    generate_batch, make_support_manifest, private_task_bytes, public_projection_bytes, sha256_hex,
    StressBatch, WorldRecord, BATCH_SIZE, K, SOLUTION_CAP,
};
use serde::Serialize;

const PRIVATE_TASKS: &str = "private-tasks.jsonl";
const PUBLIC_TASKS: &str = "public-tasks.jsonl";
const SUPPORT_MANIFEST: &str = "stress-support-manifest-v03.json";
const GENERATION_RECEIPT: &str = "private-generation-receipt-v03.json";

#[derive(Serialize)]
struct ArtifactHash {
    path: &'static str,
    sha256: String,
    bytes: usize,
}

#[derive(Serialize)]
struct SourceHash {
    path: &'static str,
    sha256: String,
}

#[derive(Serialize)]
struct GenerationReceipt<'a> {
    schema: &'static str,
    status: &'static str,
    source_identity: &'static str,
    source_hashes: Vec<SourceHash>,
    generator_seed: &'static str,
    requested_worlds: usize,
    accepted_worlds: usize,
    graph_model: &'static str,
    density_profile_note: &'static str,
    solution_cap: usize,
    target_canonical_classes: &'static str,
    attempts: usize,
    rejected_too_many_classes_or_cap: usize,
    rejected_too_few_classes: usize,
    lfm_or_model_contact_performed: bool,
    probe_or_training_performed: bool,
    output_hashes: Vec<ArtifactHash>,
    worlds: Vec<&'a WorldRecord>,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("r1-stage1-stress-worlds-v03: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let output = args
        .next()
        .map(PathBuf::from)
        .ok_or("usage: r1-stage1-stress-worlds NEW_OUTPUT_DIR")?;
    if args.next().is_some() {
        return Err("usage: r1-stage1-stress-worlds NEW_OUTPUT_DIR".into());
    }
    if output.exists() {
        return Err(format!("refusing to overwrite existing output {}", output.display()).into());
    }

    eprintln!("generating deterministic {BATCH_SIZE}-world planted coloring batch");
    let batch = generate_batch()?;
    validate_batch_shape(&batch)?;

    let private_bytes = private_task_bytes(&batch.worlds)?;
    let public_bytes = public_projection_bytes(&batch.worlds)?;
    let support_value = make_support_manifest(&public_bytes, &batch.worlds);
    let support_bytes = json_document(&support_value)?;
    let source_hashes = source_hashes()?;
    let output_hashes = vec![
        artifact_hash(PRIVATE_TASKS, &private_bytes),
        artifact_hash(PUBLIC_TASKS, &public_bytes),
        artifact_hash(SUPPORT_MANIFEST, &support_bytes),
    ];
    let receipt = GenerationReceipt {
        schema: "R1_STAGE1_STRESS_GENERATION_V03",
        status: "STRESS_GENERATION_COMPLETE",
        source_identity: "fas-r1-semantic-particle-reachability-v00/stage1-v01/stress-worlds-v03",
        source_hashes,
        generator_seed: "0x5231535452455353; per-candidate SplitMix64 seed derivation",
        requested_worlds: BATCH_SIZE,
        accepted_worlds: batch.worlds.len(),
        graph_model: "planted balanced 3-coloring; sampled inter-color Different edges only",
        density_profile_note: "profile labels identify adaptive search starts, not stratified observed density bands; actual probability, edge count, and all-pair density are recorded per world",
        solution_cap: SOLUTION_CAP,
        target_canonical_classes: "5..=16 after role automorphisms",
        attempts: batch.attempts,
        rejected_too_many_classes_or_cap: batch.rejected_too_many,
        rejected_too_few_classes: batch.rejected_too_few,
        lfm_or_model_contact_performed: false,
        probe_or_training_performed: false,
        output_hashes,
        worlds: batch.worlds.iter().map(|world| &world.record).collect(),
    };
    let receipt_bytes = json_document(&receipt)?;

    let parent = output
        .parent()
        .ok_or("output directory must have a parent")?;
    fs::create_dir_all(parent)?;
    fs::create_dir(&output)?;
    write_new(&output.join(PRIVATE_TASKS), &private_bytes)?;
    write_new(&output.join(PUBLIC_TASKS), &public_bytes)?;
    write_new(&output.join(SUPPORT_MANIFEST), &support_bytes)?;
    write_new(&output.join(GENERATION_RECEIPT), &receipt_bytes)?;

    let n20_ms: Vec<u128> = batch
        .worlds
        .iter()
        .filter(|world| world.task.n == 20)
        .map(|world| world.record.solve_elapsed_ms)
        .collect();
    let max_n20_ms = n20_ms.into_iter().max().unwrap_or(0);
    println!("output={}", output.display());
    println!("worlds={} attempts={}", batch.worlds.len(), batch.attempts);
    println!(
        "rejected_too_many_or_cap={} rejected_too_few={}",
        batch.rejected_too_many, batch.rejected_too_few
    );
    println!("n20_max_exact_solve_ms={max_n20_ms}");
    for hash in &receipt.output_hashes {
        println!("{} sha256={} bytes={}", hash.path, hash.sha256, hash.bytes);
    }
    println!("{} sha256={}", SUPPORT_MANIFEST, sha256_hex(&support_bytes));
    Ok(())
}

fn validate_batch_shape(batch: &StressBatch) -> Result<(), Box<dyn Error>> {
    if batch.worlds.len() != BATCH_SIZE {
        return Err(format!(
            "batch has {} worlds, expected {BATCH_SIZE}",
            batch.worlds.len()
        )
        .into());
    }
    for (index, world) in batch.worlds.iter().enumerate() {
        if world.record.index != index
            || world.task.n != world.record.n
            || world.task.k != K
            || !world.task.role_anonymous
            || world
                .task
                .clauses
                .iter()
                .any(|clause| !matches!(clause, r1_world::Clause::Different { .. }))
            || !(5..=16).contains(&world.record.canonical_solution_class_count)
            || world.record.exact_count_status != "EXHAUSTED"
            || world.record.independent_validator_checks != world.record.raw_solution_count
        {
            return Err(format!("batch world {index} violates the stress contract").into());
        }
    }
    Ok(())
}

fn artifact_hash(path: &'static str, bytes: &[u8]) -> ArtifactHash {
    ArtifactHash {
        path,
        sha256: sha256_hex(bytes),
        bytes: bytes.len(),
    }
}

fn json_document<T: Serialize>(value: &T) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut bytes = serde_json::to_vec_pretty(value)?;
    bytes.push(b'\n');
    Ok(bytes)
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), Box<dyn Error>> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.flush()?;
    file.sync_all()?;
    Ok(())
}

fn source_hashes() -> Result<Vec<SourceHash>, Box<dyn Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let paths = [
        ("Cargo.toml", root.join("Cargo.toml")),
        ("src/lib.rs", root.join("src/lib.rs")),
        ("src/main.rs", root.join("src/main.rs")),
    ];
    paths
        .into_iter()
        .map(|(name, path)| {
            let bytes = fs::read(path)?;
            Ok(SourceHash {
                path: name,
                sha256: sha256_hex(&bytes),
            })
        })
        .collect::<Result<Vec<_>, std::io::Error>>()
        .map_err(Into::into)
}
