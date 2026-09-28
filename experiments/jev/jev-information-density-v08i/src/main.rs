mod families;
mod generator;

use anyhow::{Context, Result, ensure};
use jev_decision_world_v01 as world;
use serde_json::{Value, json};
use std::fs::{self, File, OpenOptions};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

use families::{EVAL_PAIRS_PER_FAMILY, TRAIN_FAMILY_COUNT, TRAIN_PAIRS_PER_FAMILY};
use generator::build_triplet;

fn main() -> Result<()> {
    let args = Args::parse()?;
    run(&args)
}

struct Args {
    output: PathBuf,
    train_per_family: usize,
    eval_per_family: usize,
    seed: u64,
    run_identity: String,
    contract_sha256: String,
}

impl Args {
    fn parse() -> Result<Self> {
        let mut output = PathBuf::from(r"D:\codex-runs\jev-information-density-v08i\phase-a-v01");
        let mut train_per_family = TRAIN_PAIRS_PER_FAMILY;
        let mut eval_per_family = EVAL_PAIRS_PER_FAMILY;
        let mut seed = 20260921_u64;
        let mut run_identity = "phase-a-v01".to_string();
        let mut contract_sha256 = String::new();
        let mut iter = std::env::args().skip(1);
        while let Some(arg) = iter.next() {
            match arg.as_str() {
                "--output" => output = iter.next().context("--output requires a path")?.into(),
                "--train-per-family" => {
                    train_per_family = iter
                        .next()
                        .context("--train-per-family requires a number")?
                        .parse()?
                }
                "--eval-per-family" => {
                    eval_per_family = iter
                        .next()
                        .context("--eval-per-family requires a number")?
                        .parse()?
                }
                "--seed" => seed = iter.next().context("--seed requires a number")?.parse()?,
                "--run-identity" => {
                    run_identity = iter.next().context("--run-identity requires a value")?
                }
                "--contract-sha256" => {
                    contract_sha256 = iter.next().context("--contract-sha256 requires a value")?
                }
                other => anyhow::bail!("unknown argument: {other}"),
            }
        }
        ensure!(
            train_per_family > 0 && eval_per_family > 0,
            "pair counts must be positive"
        );
        Ok(Self {
            output,
            train_per_family,
            eval_per_family,
            seed,
            run_identity,
            contract_sha256,
        })
    }
}

fn run(args: &Args) -> Result<()> {
    prepare_output(&args.output)?;
    let families = families::all_families();
    ensure!(
        families.len() > TRAIN_FAMILY_COUNT,
        "need separate train and evaluation families"
    );

    let started = Instant::now();
    let mut exact_train = writer(&args.output.join("train-exact-world-episodes.jsonl"))?;
    let mut canonical_train = writer(&args.output.join("train-canonical-episodes.jsonl"))?;
    let mut train_certificates = writer(&args.output.join("train-contrast-certificates.jsonl"))?;
    let mut exact_eval = writer(&args.output.join("eval-exact-world-episodes.jsonl"))?;
    let mut canonical_eval = writer(&args.output.join("eval-canonical-episodes.jsonl"))?;
    let mut eval_certificates = writer(&args.output.join("eval-contrast-certificates.jsonl"))?;
    let mut templates = Vec::new();
    let mut train_pair_count = 0_usize;
    let mut eval_pair_count = 0_usize;
    let mut train_template_ids = std::collections::BTreeSet::new();
    let mut eval_template_ids = std::collections::BTreeSet::new();
    let mut train_episode_ids = std::collections::BTreeSet::new();
    let mut eval_episode_ids = std::collections::BTreeSet::new();

    for (family_index, spec) in families.iter().enumerate() {
        let partition = if family_index < TRAIN_FAMILY_COUNT {
            "train"
        } else {
            "eval"
        };
        let count = if partition == "train" {
            args.train_per_family
        } else {
            args.eval_per_family
        };
        let mut family_templates = std::collections::BTreeMap::new();
        for sequence in 0..count {
            let triplet =
                build_triplet(spec, partition, sequence, args.seed).with_context(|| {
                    format!("building {partition} contrast {} #{sequence}", spec.slug)
                })?;
            ensure!(triplet.partition == partition, "partition mismatch");
            ensure!(
                triplet.certificate["anchor_id"] == triplet.anchor_id,
                "certificate anchor identity mismatch"
            );
            ensure!(
                triplet.certificate["world_family_id"] == triplet.family_id,
                "certificate family identity mismatch"
            );
            for exact_episode in &triplet.exact_episodes {
                let template = generator::template(spec, partition, sequence % 4);
                world::validate_episode(exact_episode, &template)?;
                family_templates
                    .entry(template.template_id.clone())
                    .or_insert(template);
            }
            for episode in &triplet.canonical_episodes {
                let episode_id = episode["episode_id"]
                    .as_str()
                    .context("canonical episode missing episode_id")?
                    .to_string();
                if partition == "train" {
                    train_episode_ids.insert(episode_id);
                } else {
                    eval_episode_ids.insert(episode_id);
                }
            }
            if partition == "train" {
                train_pair_count += 1;
                for episode in &triplet.exact_episodes {
                    write_jsonl(&mut exact_train, episode)?;
                }
                for episode in &triplet.canonical_episodes {
                    write_jsonl_value(&mut canonical_train, episode)?;
                }
                write_jsonl_value(&mut train_certificates, &triplet.certificate)?;
            } else {
                eval_pair_count += 1;
                for episode in &triplet.exact_episodes {
                    write_jsonl(&mut exact_eval, episode)?;
                }
                for episode in &triplet.canonical_episodes {
                    write_jsonl_value(&mut canonical_eval, episode)?;
                }
                write_jsonl_value(&mut eval_certificates, &triplet.certificate)?;
            }
        }
        for (template_id, template) in family_templates {
            if partition == "train" {
                train_template_ids.insert(template_id);
            } else {
                eval_template_ids.insert(template_id);
            }
            templates.push(template);
        }
        println!(
            "{{\"event\":\"family_complete\",\"partition\":\"{partition}\",\"family\":\"{}\",\"pairs\":{count},\"elapsed_seconds\":{:.3}}}",
            spec.slug,
            started.elapsed().as_secs_f64()
        );
    }

    drop((
        exact_train,
        canonical_train,
        train_certificates,
        exact_eval,
        canonical_eval,
        eval_certificates,
    ));
    let train_family_ids: std::collections::BTreeSet<_> = families[..TRAIN_FAMILY_COUNT]
        .iter()
        .map(|f| format!("jev-v08i-train-family:{}", f.slug))
        .collect();
    let eval_family_ids: std::collections::BTreeSet<_> = families[TRAIN_FAMILY_COUNT..]
        .iter()
        .map(|f| format!("jev-v08i-eval-family:{}", f.slug))
        .collect();
    ensure!(
        train_family_ids.is_disjoint(&eval_family_ids),
        "train/eval family leakage"
    );
    ensure!(
        train_template_ids.is_disjoint(&eval_template_ids),
        "train/eval template leakage"
    );
    ensure!(
        train_episode_ids.is_disjoint(&eval_episode_ids),
        "train/eval episode identity leakage"
    );

    let templates_path = args.output.join("world-templates.json");
    let template_json: Vec<Value> = templates
        .iter()
        .map(serde_json::to_value)
        .collect::<std::result::Result<_, _>>()?;
    write_json(
        &templates_path,
        &json!({"contract":"jev-like-decision-world/v0.1","templates":template_json}),
    )?;
    let receipt = json!({
        "protocol":"jev-information-density/v0.8i-phase-a",
        "run_identity":args.run_identity,
        "protocol_contract_sha256":args.contract_sha256,
        "status":"CONTRAST_UNIVERSE_GENERATED_EXACTLY_NO_MODEL_CONTACT",
        "seed":args.seed,
        "train_pairs":train_pair_count,
        "eval_pairs":eval_pair_count,
        "train_episode_count":train_pair_count*3,
        "eval_episode_count":eval_pair_count*3,
        "train_family_count":TRAIN_FAMILY_COUNT,
        "eval_family_count":families.len()-TRAIN_FAMILY_COUNT,
        "train_family_ids":train_family_ids,
        "eval_family_ids":eval_family_ids,
        "train_template_ids":train_template_ids,
        "eval_template_ids":eval_template_ids,
        "train_episode_ids":train_episode_ids,
        "eval_episode_ids":eval_episode_ids,
        "train_template_count":train_template_ids.len(),
        "eval_template_count":eval_template_ids.len(),
        "train_eval_family_overlap":0,
        "train_eval_template_overlap":0,
        "exact_world_validation":"all generated v0.1 episodes validated against exact solver",
        "model_loaded":false,
        "model_inference":false,
        "feature_extraction":false,
        "training":false,
        "phoenix_access":false,
        "outputs":hash_outputs(&args.output)?
    });
    write_json(&args.output.join("generator-receipt.json"), &receipt)?;
    println!(
        "{{\"event\":\"generation_complete\",\"train_pairs\":{train_pair_count},\"eval_pairs\":{eval_pair_count},\"elapsed_seconds\":{:.3}}}",
        started.elapsed().as_secs_f64()
    );
    Ok(())
}

fn prepare_output(path: &Path) -> Result<()> {
    if path.exists() {
        ensure!(
            path.is_dir(),
            "output path exists but is not a directory: {}",
            path.display()
        );
        ensure!(
            fs::read_dir(path)?.next().is_none(),
            "output directory must be empty: {}",
            path.display()
        );
    } else {
        fs::create_dir_all(path).with_context(|| format!("creating {}", path.display()))?;
    }
    Ok(())
}

fn writer(path: &Path) -> Result<BufWriter<File>> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .with_context(|| format!("creating {}", path.display()))?;
    Ok(BufWriter::with_capacity(1 << 20, file))
}

fn write_jsonl<T: serde::Serialize>(writer: &mut BufWriter<File>, value: &T) -> Result<()> {
    serde_json::to_writer(&mut *writer, value)?;
    writer.write_all(b"\n")?;
    Ok(())
}

fn write_jsonl_value(writer: &mut BufWriter<File>, value: &Value) -> Result<()> {
    serde_json::to_writer(&mut *writer, value)?;
    writer.write_all(b"\n")?;
    Ok(())
}

fn write_json(path: &Path, value: &Value) -> Result<()> {
    let mut output = writer(path)?;
    serde_json::to_writer_pretty(&mut output, value)?;
    output.write_all(b"\n")?;
    output.flush()?;
    Ok(())
}

fn hash_outputs(root: &Path) -> Result<Value> {
    let mut entries = serde_json::Map::new();
    for name in [
        "train-exact-world-episodes.jsonl",
        "train-canonical-episodes.jsonl",
        "train-contrast-certificates.jsonl",
        "eval-exact-world-episodes.jsonl",
        "eval-canonical-episodes.jsonl",
        "eval-contrast-certificates.jsonl",
        "world-templates.json",
    ] {
        let path = root.join(name);
        let mut input = BufReader::with_capacity(
            1 << 20,
            File::open(&path).with_context(|| format!("opening {}", path.display()))?,
        );
        let byte_count = input.get_ref().metadata()?.len();
        let mut hasher = blake3::Hasher::new();
        let mut buffer = vec![0_u8; 1 << 20];
        loop {
            let count = input.read(&mut buffer)?;
            if count == 0 {
                break;
            }
            hasher.update(&buffer[..count]);
        }
        entries.insert(
            name.to_string(),
            json!({"bytes":byte_count,"blake3":hasher.finalize().to_hex().to_string()}),
        );
    }
    Ok(Value::Object(entries))
}
