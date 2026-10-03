use std::error::Error;
use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

use serde::Serialize;
use sha2::{Digest, Sha256};

use fas_s01_2_world::generate::{
    for_each_quartet, sha256_hex, term_inventory, write_repeat_digest,
};
use fas_s01_2_world::validate::validate_run;

#[derive(Serialize)]
struct CorpusManifest {
    manifest_id: &'static str,
    project_id: &'static str,
    phase_id: &'static str,
    generator_seed: u64,
    quartet_count: usize,
    rendered_input_count: usize,
    corpus_relative_path: &'static str,
    corpus_bytes: u64,
    corpus_sha256: String,
    deterministic_regeneration_sha256: String,
    term_inventory_sha256: String,
    world_contract_sha256: String,
    model_loaded: bool,
    tokenizer_loaded: bool,
    feature_extraction_performed: bool,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("FAS-S01-2 construction failed closed: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let command = args.next().ok_or("expected `materialize` or `validate`")?;
    let output_root = PathBuf::from(args.next().ok_or("missing output root")?);
    let contract_path = PathBuf::from(args.next().ok_or("missing world-contract path")?);
    if args.next().is_some() {
        return Err("unexpected extra arguments".into());
    }

    match command.to_string_lossy().as_ref() {
        "materialize" => materialize(&output_root, &contract_path),
        "validate" => validate_run(&output_root, &contract_path),
        _ => Err("expected `materialize` or `validate`".into()),
    }
}

fn materialize(output_root: &Path, contract_path: &Path) -> Result<(), Box<dyn Error>> {
    let contract_bytes = fs::read(contract_path)?;
    let _: serde_json::Value = serde_json::from_slice(&contract_bytes)?;
    let world_contract_sha256 = sha256_hex(&contract_bytes);
    let corpus_dir = output_root.join("corpus");
    fs::create_dir_all(&corpus_dir)?;

    let inventory = term_inventory();
    let inventory_bytes = serde_json::to_vec_pretty(&inventory)?;
    let inventory_path = corpus_dir.join("term-inventory-v01.json");
    write_new(&inventory_path, &inventory_bytes)?;

    let corpus_path = corpus_dir.join("counterfactual-quartets-v01.jsonl");
    let corpus_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&corpus_path)?;
    let mut writer = BufWriter::with_capacity(1 << 20, corpus_file);
    let mut digest = Sha256::new();
    let counts = for_each_quartet(|quartet| {
        let mut bytes = serde_json::to_vec(&quartet)?;
        bytes.push(b'\n');
        writer.write_all(&bytes)?;
        digest.update(&bytes);
        Ok(())
    })?;
    writer.flush()?;
    let corpus_bytes = writer.get_ref().metadata()?.len();
    writer.get_ref().sync_all()?;
    drop(writer);
    let corpus_sha256 = format!("{:x}", digest.finalize());
    let (_, deterministic_regeneration_sha256) = write_repeat_digest()?;
    if corpus_sha256 != deterministic_regeneration_sha256 {
        return Err("materialized corpus differs from immediate deterministic regeneration".into());
    }

    let inventory_sha256 = sha256_hex(&inventory_bytes);
    let manifest = CorpusManifest {
        manifest_id: "FASS01_S01_2_CORPUS_MANIFEST_V01",
        project_id: "fas-s01-frozen-sensor-transfer-cartography",
        phase_id: "S01-2-v01",
        generator_seed: inventory.generator_seed,
        quartet_count: counts.total,
        rendered_input_count: counts.total * 4,
        corpus_relative_path: "corpus/counterfactual-quartets-v01.jsonl",
        corpus_bytes,
        corpus_sha256,
        deterministic_regeneration_sha256,
        term_inventory_sha256: inventory_sha256,
        world_contract_sha256,
        model_loaded: false,
        tokenizer_loaded: false,
        feature_extraction_performed: false,
    };
    let mut manifest_bytes = serde_json::to_vec_pretty(&manifest)?;
    manifest_bytes.push(b'\n');
    write_new(
        &corpus_dir.join("corpus-manifest-v01.json"),
        &manifest_bytes,
    )?;
    println!(
        "materialized {} quartets / {} inputs",
        counts.total,
        counts.total * 4
    );
    println!("corpus_sha256={}", manifest.corpus_sha256);
    Ok(())
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), Box<dyn Error>> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
