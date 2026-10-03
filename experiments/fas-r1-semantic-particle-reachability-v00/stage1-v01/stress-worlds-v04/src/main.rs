use std::error::Error;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

use r1_stage1_stress_worlds_v04::{
    generate_batch, make_support_manifest, private_diagnostics_bytes, private_task_bytes,
    public_projection_bytes, sha256_hex, StressBatch, WorldRecord, BATCH_SIZE,
    EXPECTED_CANONICAL_CLASSES, EXPECTED_RAW_SOLUTIONS, K, SOLUTION_CAP,
};
use serde::Serialize;

const PRIVATE_TASKS: &str = "private-tasks.jsonl";
const PUBLIC_TASKS: &str = "public-tasks.jsonl";
const PRIVATE_DIAGNOSTICS: &str = "private-diagnostics.jsonl";
const SUPPORT_MANIFEST: &str = "stress-support-manifest-v04.json";
const GENERATION_RECEIPT: &str = "private-generation-receipt-v04.json";

#[derive(Serialize)]
struct ArtifactHash {
    path: &'static str,
    sha256: String,
    bytes: usize,
}

#[derive(Serialize)]
struct SourceHash {
    path: String,
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
    graph_recipe: &'static str,
    size_counts: Vec<SizeCount>,
    solution_cap: usize,
    exact_class_contract: &'static str,
    attempts: usize,
    lfm_or_model_contact_performed: bool,
    probe_or_training_performed: bool,
    output_hashes: Vec<ArtifactHash>,
    worlds: Vec<&'a WorldRecord>,
}

#[derive(Serialize)]
struct SizeCount {
    n: u16,
    worlds: usize,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("r1-stage1-stress-worlds-v04: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let output = args
        .next()
        .map(PathBuf::from)
        .ok_or("usage: r1-stage1-stress-worlds-v04 NEW_OUTPUT_DIR")?;
    if args.next().is_some() {
        return Err("usage: r1-stage1-stress-worlds-v04 NEW_OUTPUT_DIR".into());
    }
    if output.exists() {
        return Err(format!("refusing to overwrite existing output {}", output.display()).into());
    }

    let generation_started = Instant::now();
    let batch = generate_batch()?;
    validate_batch_shape(&batch)?;

    let private_bytes = private_task_bytes(&batch.worlds)?;
    let public_bytes = public_projection_bytes(&batch.worlds)?;
    let diagnostics_bytes = private_diagnostics_bytes(&batch.worlds)?;
    let support_value = make_support_manifest(&public_bytes, &batch.worlds);
    let support_bytes = json_document(&support_value)?;
    let source_hashes = source_hashes()?;
    let output_hashes = vec![
        artifact_hash(PRIVATE_TASKS, &private_bytes),
        artifact_hash(PUBLIC_TASKS, &public_bytes),
        artifact_hash(PRIVATE_DIAGNOSTICS, &diagnostics_bytes),
        artifact_hash(SUPPORT_MANIFEST, &support_bytes),
    ];
    let receipt = GenerationReceipt {
        schema: "R1_STAGE1_STRESS_GENERATION_V04",
        status: "STRESS_GENERATION_COMPLETE",
        source_identity: "fas-r1-semantic-particle-reachability-v00/stage1-v01/stress-worlds-v04",
        source_hashes,
        generator_seed: "0x5231535452455353 + world_index * 0x9e3779b97f4a7c15; SplitMix64",
        requested_worlds: BATCH_SIZE,
        accepted_worlds: batch.worlds.len(),
        graph_model: "planted role-anonymous 3-coloring; Different clauses only",
        graph_recipe: "four triangle-core modules; two-edge locks within each pair; four cross-pair edges fix the remaining relative map; two leaves per module constrained to the third role",
        size_counts: vec![SizeCount {
            n: 20,
            worlds: batch.worlds.len(),
        }],
        solution_cap: SOLUTION_CAP,
        exact_class_contract: "full exact exhaustion; 54 raw assignments; 9 classes modulo six role automorphisms",
        attempts: batch.worlds.len(),
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
    write_new(&output.join(PRIVATE_DIAGNOSTICS), &diagnostics_bytes)?;
    write_new(&output.join(SUPPORT_MANIFEST), &support_bytes)?;
    write_new(&output.join(GENERATION_RECEIPT), &receipt_bytes)?;

    println!("output={}", output.display());
    println!(
        "worlds={} attempts={}",
        batch.worlds.len(),
        batch.worlds.len()
    );
    println!("max_exact_solve_ms={}", batch.max_solver_elapsed_ms);
    println!("total_exact_solve_ms={}", batch.total_solver_elapsed_ms);
    println!(
        "generation_elapsed_ms={}",
        generation_started.elapsed().as_millis()
    );
    for hash in &receipt.output_hashes {
        println!("{} sha256={} bytes={}", hash.path, hash.sha256, hash.bytes);
    }
    println!("{} sha256={}", SUPPORT_MANIFEST, sha256_hex(&support_bytes));
    println!(
        "{} sha256={}",
        GENERATION_RECEIPT,
        sha256_hex(&receipt_bytes)
    );
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
            || world.record.raw_solution_count != EXPECTED_RAW_SOLUTIONS
            || world.record.canonical_solution_class_count != EXPECTED_CANONICAL_CLASSES
            || world.record.exact_count_status != "EXHAUSTED"
            || world.record.independent_validator_checks != EXPECTED_RAW_SOLUTIONS
        {
            return Err(format!("batch world {index} violates the v04 stress contract").into());
        }
    }
    if batch.worlds.iter().any(|world| world.task.n != 20) {
        return Err("v04 worlds must all have n=20".into());
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
    let mut paths = vec![
        ("Cargo.toml".to_owned(), root.join("Cargo.toml")),
        ("Cargo.lock".to_owned(), root.join("Cargo.lock")),
        ("src/lib.rs".to_owned(), root.join("src/lib.rs")),
        ("src/main.rs".to_owned(), root.join("src/main.rs")),
    ];
    let world_root = root.join("../../stage0-v01/world");
    paths.push((
        "stage0-v01/world/Cargo.toml".to_owned(),
        world_root.join("Cargo.toml"),
    ));
    let world_source = world_root.join("src");
    let mut world_files: Vec<PathBuf> = fs::read_dir(&world_source)?
        .map(|entry| entry.map(|item| item.path()))
        .collect::<Result<_, _>>()?;
    world_files.retain(|path| path.extension().is_some_and(|extension| extension == "rs"));
    world_files.sort();
    for path in world_files {
        let name = path
            .file_name()
            .ok_or("Stage 0 source file has no filename")?
            .to_string_lossy();
        paths.push((format!("stage0-v01/world/src/{name}"), path));
    }

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
