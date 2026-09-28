#![recursion_limit = "512"]

#[path = "../../../../jev-information-density-v08n/generator/src/families.rs"]
mod families;
#[path = "../../../../jev-information-density-v08n/generator/src/generator.rs"]
mod generator;

use anyhow::{Context, Result, ensure};
use jev_decision_world_v01 as world;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

const PANEL_IDENTITY: &str = "v0.8P-fresh-eval-panel-v01";
const PARTITION: &str = "eval_v08p";
const NEIGHBORHOODS_PER_FAMILY: usize = 500;

struct Args {
    output: PathBuf,
    contract: PathBuf,
    contract_sha256: String,
    seed: u64,
}

fn main() -> Result<()> {
    let args = parse_args()?;
    run(&args)
}

fn parse_args() -> Result<Args> {
    let mut output = None;
    let mut contract = None;
    let mut contract_sha256 = None;
    let mut seed = None;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--output" => output = Some(PathBuf::from(args.next().context("--output requires a path")?)),
            "--contract" => contract = Some(PathBuf::from(args.next().context("--contract requires a path")?)),
            "--contract-sha256" => contract_sha256 = Some(args.next().context("--contract-sha256 requires a value")?),
            "--seed" => seed = Some(args.next().context("--seed requires a number")?.parse::<u64>()?),
            other => anyhow::bail!("unknown argument: {other}"),
        }
    }
    Ok(Args {
        output: output.context("missing --output")?,
        contract: contract.context("missing --contract")?,
        contract_sha256: contract_sha256.context("missing --contract-sha256")?,
        seed: seed.context("missing --seed")?,
    })
}

fn run(args: &Args) -> Result<()> {
    ensure!(!args.output.exists(), "P panel output identity already exists: {}", args.output.display());
    let contract: Value = serde_json::from_slice(&fs::read(&args.contract).context("read P panel contract")?)?;
    ensure!(contract["identity"] == PANEL_IDENTITY, "P panel contract identity mismatch");
    ensure!(contract["freshness_and_scope"]["partition_namespace"] == PARTITION, "partition namespace mismatch");
    ensure!(contract["freshness_and_scope"]["generator_seed_derivation"]["seed"] == args.seed, "generator seed differs from sealed contract");
    ensure!(contract["freshness_and_scope"]["family_total"] == 2_000, "family total drift");

    let expected_families: Vec<String> = contract["freshness_and_scope"]["family_basis"]
        .as_array().context("family basis missing")?.iter()
        .map(|row| row["slug"].as_str().map(str::to_owned).context("family slug missing"))
        .collect::<Result<_>>()?;
    ensure!(expected_families.len() == 4, "expected exactly four contracted held-out families");

    let all = families::all_families();
    ensure!(families::TRAIN_FAMILY_COUNT < all.len(), "training/evaluation split missing");
    let eval = &all[families::TRAIN_FAMILY_COUNT..];
    let actual_families: BTreeSet<&str> = eval.iter().map(|spec| spec.slug).collect();
    let expected_set: BTreeSet<&str> = expected_families.iter().map(String::as_str).collect();
    ensure!(actual_families == expected_set, "frozen family source differs from P family contract");

    fs::create_dir(&args.output).context("create fresh P panel identity root")?;
    let mut exact = writer(&args.output.join("eval-exact-world-episodes.jsonl"))?;
    let mut canonical = writer(&args.output.join("eval-canonical-episodes.jsonl"))?;
    let mut certificates = writer(&args.output.join("eval-contrast-certificates.jsonl"))?;
    let mut templates = BTreeMap::<String, world::WorldTemplate>::new();
    let mut neighborhood_count = 0usize;
    let mut episode_count = 0usize;
    let mut family_counts = BTreeMap::<String, usize>::new();
    let mut candidate_catalog = BTreeMap::<String, Vec<Value>>::new();

    for family_slug in &expected_families {
        let spec = eval.iter().find(|spec| spec.slug == family_slug).context("contract family missing from frozen generator")?;
        for sequence in 0..NEIGHBORHOODS_PER_FAMILY {
            let triplet = generator::build_triplet(spec, PARTITION, sequence, args.seed)
                .with_context(|| format!("build P eval neighborhood {} #{sequence}", spec.slug))?;
            ensure!(triplet.partition == PARTITION, "partition label drift");
            ensure!(triplet.exact_episodes.len() == 11 && triplet.canonical_episodes.len() == 11, "episode count drift");
            let certificate = triplet.certificate;
            let schema_id = certificate["schema_family_id"].as_str().context("schema identity absent")?.to_owned();
            let candidates = triplet.canonical_episodes[0]["runtime_schema"]["candidates"]
                .as_array().context("candidate catalog absent")?.clone();
            if let Some(previous) = candidate_catalog.get(&schema_id) {
                ensure!(previous == &candidates, "candidate catalog changed within schema");
            } else {
                candidate_catalog.insert(schema_id, candidates);
            }
            for episode in &triplet.exact_episodes {
                serde_json::to_writer(&mut exact, episode)?;
                exact.write_all(b"\n")?;
            }
            for episode in &triplet.canonical_episodes {
                serde_json::to_writer(&mut canonical, episode)?;
                canonical.write_all(b"\n")?;
            }
            serde_json::to_writer(&mut certificates, &certificate)?;
            certificates.write_all(b"\n")?;

            let template = generator::template(spec, PARTITION, sequence % 4);
            templates.insert(template.template_id.clone(), template);
            *family_counts.entry(spec.slug.to_owned()).or_default() += 1;
            neighborhood_count += 1;
            episode_count += 11;
        }
    }
    exact.flush()?;
    canonical.flush()?;
    certificates.flush()?;
    drop((exact, canonical, certificates));

    ensure!(neighborhood_count == 2_000 && episode_count == 22_000, "P panel construction count drift");
    ensure!(family_counts.len() == 4 && family_counts.values().all(|count| *count == 500), "P family allocation drift");
    ensure!(candidate_catalog.len() == 4 && candidate_catalog.values().all(|rows| rows.len() == 4), "candidate catalog dimensions drift");
    ensure!(templates.len() == 16, "expected four frozen p0-p3 templates per family");

    let template_values: Vec<Value> = templates.values().map(serde_json::to_value).collect::<std::result::Result<_, _>>()?;
    let template_file = File::create(args.output.join("world-templates.json"))?;
    let mut template_writer = BufWriter::new(template_file);
    serde_json::to_writer_pretty(&mut template_writer, &json!({"contract":"jev-like-decision-world/v0.1","templates":template_values}))?;
    template_writer.write_all(b"\n")?;
    template_writer.flush()?;

    let receipt = json!({
        "status":"V08P_FRESH_PANEL_WORLD_GENERATION_COMPLETE_NO_MODEL_CONTACT",
        "identity":PANEL_IDENTITY,
        "protocol":"jev-information-density/v0.8p-fresh-heldout-panel-v01",
        "contract_sha256":args.contract_sha256,
        "generator_seed":args.seed,
        "partition_namespace":PARTITION,
        "family_neighborhood_counts":family_counts,
        "neighborhood_count":neighborhood_count,
        "exact_episode_count":episode_count,
        "canonical_episode_count":episode_count,
        "contrast_certificate_count":neighborhood_count,
        "template_count":templates.len(),
        "candidate_schemas":candidate_catalog.keys().collect::<Vec<_>>(),
        "source_generator_family_sha256":"e56885005487b36b573c1bf4d47741413ca72df0992ff62bcf48891eecacb429",
        "source_generator_logic_sha256":"f04a9b1d4f6682522e5957be3c0075db4bd7aa4e4e25968650f2ff24a42c7f5b",
        "exact_solver":"jev-decision-world-v01::solve_exact and validate_episode through frozen generator implementation",
        "head_load":false,
        "head_training":false,
        "evaluation_inference":false,
        "evaluation_metrics":false,
        "newtight_access":false,
        "legacy_evaluation_access":false,
        "phoenix_access":false
    });
    let receipt_path = args.output.join("generator-receipt.json");
    let mut receipt_writer = BufWriter::new(File::create(&receipt_path)?);
    serde_json::to_writer_pretty(&mut receipt_writer, &receipt)?;
    receipt_writer.write_all(b"\n")?;
    receipt_writer.flush()?;
    println!("{}", serde_json::to_string(&receipt)?);
    Ok(())
}

fn writer(path: &Path) -> Result<BufWriter<File>> {
    Ok(BufWriter::new(File::create(path).with_context(|| format!("create {}", path.display()))?))
}
