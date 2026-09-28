use std::error::Error;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

use r1_stage1_stress_worlds_v05::{
    generate_batch, load_config, make_support_manifest, private_diagnostics_bytes,
    private_task_bytes, public_projection_bytes, public_search_starts_bytes, sha256_hex,
    StressBatch, WorldRecord, EXPECTED_CANONICAL_CLASSES, EXPECTED_RAW_SOLUTIONS,
    EXPECTED_ROLE_AUTOMORPHISMS,
};
use serde::Serialize;

const PRIVATE_TASKS: &str = "private-tasks.jsonl";
const PUBLIC_TASKS: &str = "public-tasks.jsonl";
const PRIVATE_DIAGNOSTICS: &str = "private-diagnostics.jsonl";
const PUBLIC_SEARCH_STARTS: &str = "public-search-starts-v05.jsonl";
const SUPPORT_MANIFEST: &str = "stress-support-manifest-v05-1.json";
const CONFIG_COPY: &str = "stress-config-v05.json";
const GENERATION_RECEIPT: &str = "private-generation-receipt-v05-1.json";

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
    config_sha256: String,
    generator_seed: &'static str,
    requested_worlds: usize,
    accepted_worlds: usize,
    graph_model: &'static str,
    graph_recipe: &'static str,
    scenario_counts: Vec<ScenarioReceipt>,
    split_counts: Vec<SizeCount>,
    solution_cap: usize,
    exact_class_contract: &'static str,
    dense_overlay_contract: &'static str,
    decoy_contract: &'static str,
    paired_world_count: usize,
    search_start_contract: &'static str,
    attempts: usize,
    lfm_or_model_contact_performed: bool,
    probe_or_training_performed: bool,
    output_hashes: Vec<ArtifactHash>,
    worlds: Vec<&'a WorldRecord>,
}

#[derive(Serialize)]
struct SizeCount {
    split: &'static str,
    worlds: usize,
}

#[derive(Serialize)]
struct ScenarioReceipt {
    scenario_id: &'static str,
    worlds: usize,
    train: usize,
    validation: usize,
    qualification: usize,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("r1-stage1-stress-worlds-v05: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let (config_path, output) = parse_args()?;
    if output.exists() {
        return Err(format!("refusing to overwrite existing output {}", output.display()).into());
    }
    let config_bytes = fs::read(&config_path)?;
    let config = load_config(&config_bytes)?;
    let generation_started = Instant::now();
    let batch = generate_batch(&config)?;
    validate_batch_shape(&batch, &config_bytes)?;

    let private_bytes = private_task_bytes(&batch.worlds)?;
    let public_bytes = public_projection_bytes(&batch.worlds)?;
    let search_start_bytes = public_search_starts_bytes(&batch.worlds)?;
    let diagnostics_bytes = private_diagnostics_bytes(&batch.worlds)?;
    let support_value = make_support_manifest(
        &public_bytes,
        &search_start_bytes,
        &config_bytes,
        &batch.worlds,
    );
    let support_bytes = json_document(&support_value)?;
    let source_hashes = source_hashes(&config_bytes)?;
    let output_hashes = vec![
        artifact_hash(PRIVATE_TASKS, &private_bytes),
        artifact_hash(PUBLIC_TASKS, &public_bytes),
        artifact_hash(PUBLIC_SEARCH_STARTS, &search_start_bytes),
        artifact_hash(PRIVATE_DIAGNOSTICS, &diagnostics_bytes),
        artifact_hash(SUPPORT_MANIFEST, &support_bytes),
        artifact_hash(CONFIG_COPY, &config_bytes),
    ];
    let scenario_counts = [
        "base-random",
        "base-swap-trap",
        "dense-random",
        "dense-swap-trap",
    ]
    .into_iter()
    .map(|scenario_id| ScenarioReceipt {
        scenario_id,
        worlds: batch
            .worlds
            .iter()
            .filter(|world| world.record.scenario_id == scenario_id)
            .count(),
        train: count(&batch, scenario_id, "train"),
        validation: count(&batch, scenario_id, "validation"),
        qualification: count(&batch, scenario_id, "qualification"),
    })
    .collect();
    let receipt = GenerationReceipt {
        schema: "R1_STAGE1_STRESS_GENERATION_V05_1",
        status: "STRESS_GENERATION_COMPLETE",
        source_identity: "fas-r1-semantic-particle-reachability-v00/stage1-v01/stress-worlds-v05.1-support-manifest-repair",
        source_hashes,
        config_sha256: sha256_hex(&config_bytes),
        generator_seed: "0x5231535452455354 + paired_world_index * 0x9e3779b97f4a7c15; SplitMix64",
        requested_worlds: config.batch_size,
        accepted_worlds: batch.worlds.len(),
        graph_model: "planted role-anonymous 3-coloring; Different clauses only",
        graph_recipe: "four triangle-core modules; paired two-edge locks; four cross-pair locks; base or ten-edge implied 0-2 overlay",
        scenario_counts,
        split_counts: vec![
            SizeCount { split: "train", worlds: count_split(&batch, "train") },
            SizeCount { split: "validation", worlds: count_split(&batch, "validation") },
            SizeCount { split: "qualification", worlds: count_split(&batch, "qualification") },
        ],
        solution_cap: config.solution_cap,
        exact_class_contract: "full exact exhaustion; 54 raw assignments; 9 classes modulo six role automorphisms",
        dense_overlay_contract: "ten additional Different clauses are implied by the module-0/module-2 relative-color lock",
        decoy_contract: "public witness-derived module-1 role-0/role-1 swap is the declared warm-start basin diagnostic; exactly two bridge conflicts and either single anchor repair remains at two conflicts",
        paired_world_count: 24,
        search_start_contract: "public-search-starts-v05.jsonl provides the declared planner initial state; independent random assignments are derived from world_seed XOR initial_state_seed_tag using SplitMix64 unbiased bounded sampling and are shared across base/dense; swap-trap starts are exposed witness-derived assignments; this sidecar is excluded from sensor extraction",
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
    write_new(&output.join(PUBLIC_SEARCH_STARTS), &search_start_bytes)?;
    write_new(&output.join(PRIVATE_DIAGNOSTICS), &diagnostics_bytes)?;
    write_new(&output.join(SUPPORT_MANIFEST), &support_bytes)?;
    write_new(&output.join(CONFIG_COPY), &config_bytes)?;
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

fn parse_args() -> Result<(PathBuf, PathBuf), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let mut config = None;
    let mut output = None;
    while let Some(argument) = args.next() {
        match argument.to_string_lossy().as_ref() {
            "--config" if config.is_none() => config = args.next().map(PathBuf::from),
            "--output" if output.is_none() => output = args.next().map(PathBuf::from),
            _ => return Err(
                "usage: r1-stage1-stress-worlds-v05 --config CONFIG_JSON --output NEW_OUTPUT_DIR"
                    .into(),
            ),
        }
    }
    Ok((
        config.ok_or("missing --config CONFIG_JSON")?,
        output.ok_or("missing --output NEW_OUTPUT_DIR")?,
    ))
}

fn validate_batch_shape(batch: &StressBatch, config_bytes: &[u8]) -> Result<(), Box<dyn Error>> {
    if batch.worlds.len() != 96 {
        return Err(format!("batch has {} worlds, expected 96", batch.worlds.len()).into());
    }
    for (index, world) in batch.worlds.iter().enumerate() {
        let scenario_index = index % 4;
        let expected_scenario = [
            "base-random",
            "base-swap-trap",
            "dense-random",
            "dense-swap-trap",
        ][scenario_index];
        if world.record.index != index
            || world.task.id != world.record.task_id
            || world.task.family_id != world.record.family_id
            || world.task.n != 20
            || world.task.k != 3
            || !world.task.role_anonymous
            || world
                .task
                .clauses
                .iter()
                .any(|clause| !matches!(clause, r1_world::Clause::Different { .. }))
            || world.record.raw_solution_count != EXPECTED_RAW_SOLUTIONS
            || world.record.canonical_solution_class_count != EXPECTED_CANONICAL_CLASSES
            || world.record.role_automorphism_count != EXPECTED_ROLE_AUTOMORPHISMS
            || world.record.scenario_id != expected_scenario
            || world.search_start.task_id != world.task.id
            || world.search_start.family_id != world.task.family_id
            || world.search_start.paired_world_id != world.record.paired_world_id
            || world.search_start.density_level != world.record.density_level
            || world.search_start.start_kind != world.record.start_kind
            || world.search_start.assignment.len() != 20
            || world.search_start.assignment.iter().any(|role| *role >= 3)
            || sha256_hex(&world.search_start.assignment) != world.search_start.assignment_sha256
        {
            return Err(format!("v05 world {index} violates its source contract").into());
        }
    }
    if batch
        .worlds
        .iter()
        .filter(|world| world.record.split == "train")
        .count()
        != 64
        || batch
            .worlds
            .iter()
            .filter(|world| world.record.split == "validation")
            .count()
            != 16
        || batch
            .worlds
            .iter()
            .filter(|world| world.record.split == "qualification")
            .count()
            != 16
    {
        return Err("v05 roster does not satisfy the 64/16/16 split".into());
    }
    for pair_chunk in batch.worlds.chunks_exact(4) {
        if pair_chunk.iter().any(|world| {
            world.record.paired_world_id != pair_chunk[0].record.paired_world_id
                || world.record.seed != pair_chunk[0].record.seed
                || world.record.split != pair_chunk[0].record.split
        }) || pair_chunk[0].search_start.assignment != pair_chunk[2].search_start.assignment
        {
            return Err(
                "v05 paired variants do not share their seed, split, or random start".into(),
            );
        }
    }
    let mut paired_ids = hashbrown::HashSet::with_capacity(24);
    for world in &batch.worlds {
        paired_ids.insert(world.record.paired_world_id.as_str());
    }
    if paired_ids.len() != 24 {
        return Err(format!(
            "v05 roster has {} paired worlds, expected 24",
            paired_ids.len()
        )
        .into());
    }
    let support = make_support_manifest(
        &public_projection_bytes(&batch.worlds)?,
        &public_search_starts_bytes(&batch.worlds)?,
        config_bytes,
        &batch.worlds,
    );
    if support
        .scenario_counts
        .iter()
        .any(|count| count.train != 16 || count.validation != 4 || count.qualification != 4)
    {
        return Err("v05 scenario split balance changed".into());
    }
    Ok(())
}

fn count(batch: &StressBatch, scenario: &str, split: &str) -> usize {
    batch
        .worlds
        .iter()
        .filter(|world| world.record.scenario_id == scenario && world.record.split == split)
        .count()
}

fn count_split(batch: &StressBatch, split: &str) -> usize {
    batch
        .worlds
        .iter()
        .filter(|world| world.record.split == split)
        .count()
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

fn source_hashes(config_bytes: &[u8]) -> Result<Vec<SourceHash>, Box<dyn Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let mut paths = vec![
        ("Cargo.toml".to_owned(), root.join("Cargo.toml")),
        ("Cargo.lock".to_owned(), root.join("Cargo.lock")),
        ("src/lib.rs".to_owned(), root.join("src/lib.rs")),
        ("src/main.rs".to_owned(), root.join("src/main.rs")),
        ("src/rng.rs".to_owned(), root.join("src/rng.rs")),
        ("src/artifacts.rs".to_owned(), root.join("src/artifacts.rs")),
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
            .ok_or("Stage0 source file has no filename")?
            .to_string_lossy();
        paths.push((format!("stage0-v01/world/src/{name}"), path));
    }
    let mut hashes = paths
        .into_iter()
        .map(|(name, path)| {
            let bytes = fs::read(path)?;
            Ok(SourceHash {
                path: name,
                sha256: sha256_hex(&bytes),
            })
        })
        .collect::<Result<Vec<_>, std::io::Error>>()?;
    hashes.push(SourceHash {
        path: "configs/stress-config-v05.json".into(),
        sha256: sha256_hex(config_bytes),
    });
    Ok(hashes)
}
