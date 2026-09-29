use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Read, Write};
use std::path::{Path, PathBuf};

use fas_frozen_capability_fabric_e4_population_v02::{PopulationPaths, PopulationPermit, prepare_population};
use serde::Serialize;
use sha2::{Digest, Sha256};

#[derive(Serialize)]
struct Entry {
    path: &'static str,
    bytes: u64,
    sha256: String,
}

#[derive(Serialize)]
struct Seal {
    schema: &'static str,
    purpose: &'static str,
    population_namespace: &'static str,
    seed: u64,
    quartets: usize,
    primary_rows: usize,
    class_support_minimum: u64,
    protected_e4_panel_read: bool,
    files: Vec<Entry>,
}

fn hash_file(path: &Path) -> Result<(String, u64), String> {
    let mut file = File::open(path).map_err(|e| e.to_string())?;
    let mut hash = Sha256::new();
    let mut bytes = 0u64;
    let mut buffer = [0u8; 1 << 20];
    loop {
        let n = file.read(&mut buffer).map_err(|e| e.to_string())?;
        if n == 0 { break; }
        hash.update(&buffer[..n]);
        bytes += n as u64;
    }
    Ok((format!("{:x}", hash.finalize()), bytes))
}

fn new_writer(path: &Path) -> Result<BufWriter<File>, String> {
    let file = OpenOptions::new().write(true).create_new(true).open(path)
        .map_err(|e| format!("{}: {e}", path.display()))?;
    Ok(BufWriter::with_capacity(1 << 20, file))
}

fn line<T: Serialize>(writer: &mut BufWriter<File>, row: &T) -> Result<(), String> {
    serde_json::to_writer(&mut *writer, row).map_err(|e| e.to_string())?;
    writer.write_all(b"\n").map_err(|e| e.to_string())
}

fn run(output: PathBuf) -> Result<(), String> {
    if output.exists() { return Err("output already exists".into()); }
    let plan = prepare_population(&PopulationPaths::workstation_defaults())?;
    let permit = PopulationPermit::scale_comparison(output.clone());
    fs::create_dir(&output).map_err(|e| e.to_string())?;
    let mut inputs = new_writer(&output.join("inputs.jsonl"))?;
    let mut manifest = new_writer(&output.join("rows.jsonl"))?;
    let mut labels = new_writer(&output.join("labels-sealed.jsonl"))?;
    let mut count = 0usize;
    plan.emit_quartets(&permit, |quartet| {
        for row in &quartet.primary_rows {
            line(&mut inputs, &row.input)?;
            line(&mut manifest, &row.manifest)?;
            line(&mut labels, &row.label)?;
            count += 1;
        }
        Ok(())
    })?;
    for writer in [&mut inputs, &mut manifest, &mut labels] {
        writer.flush().map_err(|e| e.to_string())?;
        writer.get_ref().sync_all().map_err(|e| e.to_string())?;
    }
    drop((inputs, manifest, labels));
    if count != plan.quartet_count() * 4 { return Err("row count mismatch".into()); }
    let mut files = Vec::new();
    for name in ["inputs.jsonl", "rows.jsonl", "labels-sealed.jsonl"] {
        let (sha256, bytes) = hash_file(&output.join(name))?;
        files.push(Entry { path: name, bytes, sha256 });
    }
    let seal = Seal {
        schema: "phoenix.e4-scale-independent-population/v1",
        purpose: "Same fresh E4-shaped primary TEST for 230M and 1.2B; labels stay closed until predictions seal",
        population_namespace: fas_frozen_capability_fabric_e4_population_v02::identity::POPULATION_NAMESPACE,
        seed: fas_frozen_capability_fabric_e4_population_v02::identity::WORLD_RENDER_SEED,
        quartets: plan.quartet_count(), primary_rows: count,
        class_support_minimum: plan.receipt.selected_primary_support.minimum_class_count(),
        protected_e4_panel_read: false, files,
    };
    let mut out = new_writer(&output.join("population-seal.json"))?;
    serde_json::to_writer_pretty(&mut out, &seal).map_err(|e| e.to_string())?;
    out.write_all(b"\n").map_err(|e| e.to_string())?;
    out.flush().map_err(|e| e.to_string())?;
    println!("independent E4-shaped TEST sealed: {} rows", count);
    Ok(())
}

fn main() {
    let mut args = std::env::args_os().skip(1);
    let output = args.next().map(PathBuf::from).expect("output directory required");
    assert!(args.next().is_none(), "one output directory only");
    let result = std::thread::Builder::new()
        .name("e4-scale-population".to_owned())
        .stack_size(16 << 20)
        .spawn(move || run(output))
        .expect("spawn population worker")
        .join()
        .expect("population worker panicked");
    if let Err(error) = result {
        eprintln!("independent population failed: {error}");
        std::process::exit(2);
    }
}
