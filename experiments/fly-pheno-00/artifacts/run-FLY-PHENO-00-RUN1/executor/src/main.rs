mod graph;
mod rng;
mod sim;
mod task;

use anyhow::{Context, Result, ensure};
use csv::ReaderBuilder;
use graph::{Graph, canonical_edge_indices};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use sim::Sim;
use std::{collections::{BTreeMap, BTreeSet}, fs::{self, File, OpenOptions}, io::{BufWriter, Read, Write}, path::{Path,}, sync::Arc, time::Instant};
use task::Task;

const CHECKPOINTS: [usize; 11] = [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512];
const ETA: f32 = 0.05;
const TAU: f32 = 16.0;
const GLUT_SIGN: f32 = -1.0;
const THREADS: usize = 4;

#[derive(Clone, Debug)]
struct FitRow { fit_id: u64, substrate: String, graph_seed: u64, side: String, block: u64, family: String, m: u32, severity: f64, arm: String }

#[derive(Deserialize)]
struct TrainBlock { task_seed: u64, labels: Vec<bool>, schedule: Vec<Vec<usize>> }
#[derive(Deserialize)]
struct TrainBank { blocks: BTreeMap<String, TrainBlock> }
#[derive(Deserialize)]
struct EvalBank { response_draws_u64: Vec<Vec<u64>> }

#[derive(Serialize)]
struct OutcomeRow<'a> {
    substrate: &'a str, graph: &'a str, side: &'a str, block: u64, lesion_m: u32, family: &'a str,
    severity: f64, arm: &'a str, checkpoint: i32, loss: f64, competent: bool, weight_distance: f64,
    state_digest: String, stored_mask_unchanged: bool, finite: bool,
}

fn hash_file(path: &Path) -> Result<String> {
    let mut file = File::open(path).with_context(|| path.display().to_string())?;
    let mut hash = Sha256::new(); let mut buf = [0u8; 65_536];
    loop { let n = file.read(&mut buf)?; if n == 0 { break; } hash.update(&buf[..n]); }
    Ok(format!("{:x}", hash.finalize()))
}

fn parse_fit_manifest(path: &Path) -> Result<Vec<FitRow>> {
    let mut reader = ReaderBuilder::new().has_headers(true).from_path(path)?;
    let mut rows = Vec::new();
    for record in reader.records() {
        let r = record?;
        rows.push(FitRow {
            fit_id: r[0].parse()?, substrate: r[1].to_string(), graph_seed: r[2].parse()?, side: r[3].to_string(),
            block: r[4].parse()?, family: r[5].to_string(), m: r[6].parse()?, severity: r[7].parse()?, arm: r[8].to_string(),
        });
    }
    ensure!(rows.len() == 11_232, "fit manifest row count changed");
    ensure!(rows.iter().enumerate().all(|(i, r)| r.fit_id == i as u64));
    Ok(rows)
}

fn verify_seal(study: &Path) -> Result<Value> {
    eprintln!("verify_seal_begin");
    let seal_path = study.join("manifests/PREEXECUTION-SEAL.json");
    let sidecar = fs::read_to_string(study.join("manifests/PREEXECUTION-SEAL.sha256"))?;
    let expected = sidecar.split_whitespace().next().context("seal sidecar")?;
    ensure!(hash_file(&seal_path)? == expected, "pre-execution seal checksum mismatch");
    eprintln!("verify_seal_checksum");
    let seal: Value = serde_json::from_reader(File::open(&seal_path)?)?;
    eprintln!("verify_seal_json");
    ensure!(seal["status"] == "PREEXECUTION_SEALED_NOT_AUTHORIZED");
    ensure!(seal["before_task_execution"] == true && seal["measured_execution_authorized"] == false);
    for entry in seal["key_hashes"].as_array().context("key hashes")? {
        let rel = entry["path"].as_str().context("key path")?;
        let path = study.join(rel);
        ensure!(hash_file(&path)? == entry["sha256"].as_str().unwrap(), "key hash mismatch: {rel}");
        ensure!(path.metadata()?.len() == entry["bytes"].as_u64().unwrap(), "key size mismatch: {rel}");
    }
    eprintln!("verify_seal_keys");
    for entry in seal["dependency_entries"].as_array().context("dependency entries")? {
        let rel = entry["path"].as_str().context("dependency path")?;
        let path = study.join(rel);
        ensure!(hash_file(&path)? == entry["sha256"].as_str().unwrap(), "dependency hash mismatch: {rel}");
    }
    eprintln!("verify_seal_dependencies");
    let protected: Value = serde_json::from_reader(File::open(study.join("provenance/PROTECTED-DH08A-TREE-RECEIPT.json"))?)?;
    ensure!(protected["unchanged"] == true && protected["before"]["root_sha256"] == protected["after"]["root_sha256"]);
    ensure!(protected["outcome_files_opened_for_inspection"] == false && protected["result_artifacts_copied"] == false);
    Ok(seal)
}

fn read_orders(study: &Path, graph: &Graph, substrate: &str, side: &str) -> Result<BTreeMap<(String, u32), Vec<usize>>> {
    let canonical = canonical_edge_indices(graph);
    let mut by_key = BTreeMap::new();
    let base = study.join("inputs/lesion-permutations").join(substrate).join(side);
    let files = std::iter::once(("high_degree_targeted".to_string(), 0, base.join("high-degree.order.u32le")))
        .chain((1..=4).map(|m| ("uniform_random".to_string(), m, base.join(format!("random-m{m}.order.u32le")))));
    for (family, m, path) in files {
        let bytes = fs::read(path)?; ensure!(bytes.len() % 4 == 0);
        let mut order = Vec::with_capacity(bytes.len() / 4);
        for chunk in bytes.chunks_exact(4) { order.push(u32::from_le_bytes(chunk.try_into().unwrap()) as usize); }
        ensure!(order.len() == canonical.len() && order.iter().copied().collect::<BTreeSet<_>>().len() == order.len());
        by_key.insert((family, m), order.into_iter().map(|i| canonical[i]).collect());
    }
    Ok(by_key)
}

fn mask_for(order: &[usize], severity: f64, n: usize) -> Vec<bool> {
    let mut active = vec![true; n];
    let count = (severity * order.len() as f64).floor() as usize;
    for &ix in order.iter().take(count) { active[ix] = false; }
    active
}

fn distance(a: &[f32], b: &[f32]) -> f64 {
    a.iter().zip(b).map(|(&x, &y)| { let d = f64::from(x) - f64::from(y); d * d }).sum::<f64>().sqrt()
}

fn run_block(study: &Path, graph: Arc<Graph>, substrate: &str, side: &str, block: u64, train: &TrainBlock, comp: &EvalBank, meas: &EvalBank, rows: &[FitRow]) -> Result<(Vec<String>, Vec<String>, bool)> {
    let task = Task::new(&graph, train.task_seed, train.labels.clone(), train.schedule.clone());
    let mut pre = Sim::new(&graph, train.task_seed, TAU, ETA);
    for trial in 0..512 { pre.trial(&task, trial); }
    ensure!(pre.finite());
    let evaluator_before = pre.digest();
    let competence_loss = pre.loss(&task, &comp.response_draws_u64);
    ensure!(pre.digest() == evaluator_before);
    ensure!((competence_loss - pre.loss(&task, &comp.response_draws_u64)).abs() == 0.0, "evaluator is not deterministic");
    let competent = competence_loss <= 0.25;
    let pre_weights = pre.weights.clone();
    let pre_digest = pre.digest();
    let mut out = Vec::new();
    let mut receipts = Vec::new();
    let mut conditions: BTreeMap<(String, u32, String), Vec<&FitRow>> = BTreeMap::new();
    for row in rows { conditions.entry((row.family.clone(), row.m, row.severity.to_string())).or_default().push(row); }
    for ((family, m, severity_key), cell) in conditions {
        let severity: f64 = severity_key.parse()?;
        let active = if family == "sham" { vec![true; pre.weights.len()] } else {
            let orders = read_orders(study, &graph, substrate, side)?;
            mask_for(orders.get(&(family.clone(), m)).context("lesion order")?, severity, pre.weights.len())
        };
        let mut adaptive = pre.clone(); adaptive.active = active.clone(); adaptive.weights_frozen = false;
        let mut frozen = adaptive.clone(); frozen.weights_frozen = true;
        let mut sims = vec![adaptive, frozen];
        let initial_adaptive_loss = sims[0].loss(&task, &meas.response_draws_u64);
        let initial_frozen_loss = sims[1].loss(&task, &meas.response_draws_u64);
        ensure!(initial_adaptive_loss.to_bits() == initial_frozen_loss.to_bits(), "paired t0 losses differ");
        for arm_index in 0..2 {
            let arm = if arm_index == 0 { "adaptive" } else { "weight_frozen" };
            let mut checkpoints: BTreeMap<i32, (f64, String, f64, bool)> = BTreeMap::new();
            checkpoints.insert(0, (sims[arm_index].loss(&task, &meas.response_draws_u64), sims[arm_index].digest(), distance(&sims[arm_index].weights, &pre_weights), sims[arm_index].finite()));
            for trial in 1..=512 {
                sims[arm_index].trial(&task, trial - 1);
                if CHECKPOINTS.contains(&trial) {
                    checkpoints.insert(trial as i32, (sims[arm_index].loss(&task, &meas.response_draws_u64), sims[arm_index].digest(), distance(&sims[arm_index].weights, &pre_weights), sims[arm_index].finite()));
                }
            }
            for (checkpoint, (loss, digest, dist, finite)) in checkpoints {
                let stored_ok = sims[arm_index].weights.iter().zip(&pre_weights).zip(&sims[arm_index].active).all(|((a, b), active)| *active || a.to_bits() == b.to_bits());
                let row = cell.iter().find(|r| r.arm == arm).context("paired arm row")?;
                let mut buffer = Vec::new();
                serde_json::to_writer(&mut buffer, &OutcomeRow { substrate, graph: substrate, side, block, lesion_m: m, family: &family, severity, arm, checkpoint, loss, competent, weight_distance: dist, state_digest: digest.clone(), stored_mask_unchanged: stored_ok, finite }).unwrap();
                buffer.push(b'\n'); out.push(String::from_utf8(buffer).unwrap());
                receipts.push(format!("{{\"fit_id\":{},\"arm\":\"{}\",\"checkpoint\":{},\"loss\":{},\"competent\":{},\"finite\":{},\"state_digest\":\"{}\"}}\n", row.fit_id, arm, checkpoint, loss, competent, finite, digest));
            }
        }
    }
    // Pre-lesion sham endpoint is a separate analysis anchor.
    for row in rows.iter().filter(|r| r.family == "sham") {
        let mut pre_eval = pre.clone(); pre_eval.weights_frozen = row.arm == "weight_frozen";
        let loss = pre_eval.loss(&task, &meas.response_draws_u64);
        let mut buffer = Vec::new();
        serde_json::to_writer(&mut buffer, &OutcomeRow { substrate, graph: substrate, side, block, lesion_m: 0, family: "sham", severity: 0.0, arm: &row.arm, checkpoint: -1, loss, competent, weight_distance: 0.0, state_digest: pre_digest.clone(), stored_mask_unchanged: true, finite: pre.finite() }).unwrap();
        buffer.push(b'\n'); out.push(String::from_utf8(buffer).unwrap());
    }
    Ok((out, receipts, competent))
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    ensure!(args.len() == 3, "usage: executor STUDY_ROOT RUN_ROOT");
    let study = fs::canonicalize(&args[1])?;
    let run_root = fs::canonicalize(&args[2])?;
    let started = Instant::now();
    eprintln!("run1_preflight_start");
    let seal = verify_seal(&study)?;
    eprintln!("run1_seal_verified");
    let fit_path = study.join("manifests/FIT-MANIFEST.csv");
    let fit_hash = hash_file(&fit_path)?;
    ensure!(fit_hash == seal["cardinality"]["fit_manifest_sha256"].as_str().unwrap());
    let rows = parse_fit_manifest(&fit_path)?;
    eprintln!("run1_manifest_verified");
    let train: TrainBank = serde_json::from_reader(File::open(study.join("inputs/banks/training.json"))?)?;
    let comp: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/competence.json"))?)?;
    let meas: EvalBank = serde_json::from_reader(File::open(study.join("inputs/banks/measurement.json"))?)?;
    ensure!(comp.response_draws_u64 != meas.response_draws_u64 && comp.response_draws_u64.len() == 256 && meas.response_draws_u64.len() == 256);
    let mut grouped: BTreeMap<(String, String, u64), Vec<FitRow>> = BTreeMap::new();
    for row in rows { grouped.entry((row.substrate.clone(), row.side.clone(), row.block)).or_default().push(row); }
    ensure!(grouped.len() == 216);
    fs::create_dir_all(&run_root)?;
    let outcomes = OpenOptions::new().create_new(true).write(true).open(run_root.join("final-outcomes.jsonl"))?;
    let receipts = OpenOptions::new().create_new(true).write(true).open(run_root.join("fit-receipts.jsonl"))?;
    let mut outcome_writer = BufWriter::new(outcomes); let mut receipt_writer = BufWriter::new(receipts);
    let mut competent_count = 0usize;
    let mut completed = 0usize;
    eprintln!("run1_collection_start blocks={}", grouped.len());
    for ((substrate, side, block), block_rows) in grouped {
        let graph = Arc::new(graph::load(&study, &substrate, &side, GLUT_SIGN)?);
        let train_block = train.blocks.get(&block.to_string()).context("training block")?;
        let (lines, receipts, competent) = run_block(&study, graph, &substrate, &side, block, train_block, &comp, &meas, &block_rows)?;
        for line in lines { outcome_writer.write_all(line.as_bytes())?; }
        for line in receipts { receipt_writer.write_all(line.as_bytes())?; }
        completed += 1; competent_count += usize::from(competent);
        if completed % 4 == 0 { eprintln!("collection_progress blocks={completed}/216"); }
    }
    outcome_writer.flush()?; receipt_writer.flush()?;
    let receipt = serde_json::json!({
        "schema":"FLY-PHENO-00-collection-receipt-v1", "run_id":"FLY-PHENO-00-RUN1", "status":"COLLECTION_COMPLETE",
        "comparative_summaries_printed":false, "fit_manifest_sha256":fit_hash, "declared_fit_rows":11232,
        "completed_base_blocks":completed, "competent_base_blocks":competent_count, "threads":THREADS,
        "outcome_path":"final-outcomes.jsonl", "fit_receipts_path":"fit-receipts.jsonl", "wall_seconds":started.elapsed().as_secs_f64(),
        "preexecution_seal_sha256":hash_file(&study.join("manifests/PREEXECUTION-SEAL.json"))?, "integrity_gate_pending":true,
    });
    let mut file = OpenOptions::new().create_new(true).write(true).open(run_root.join("collection-receipt.json"))?;
    serde_json::to_writer_pretty(&mut file, &receipt)?; file.write_all(b"\n")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn severity_masks_are_nested_and_exact() {
        let order: Vec<usize> = (0..100).collect();
        let a = mask_for(&order, 0.01, 100); let b = mask_for(&order, 0.10, 100);
        assert_eq!(a.iter().filter(|x| !**x).count(), 1); assert_eq!(b.iter().filter(|x| !**x).count(), 10);
        assert!(a.iter().zip(&b).all(|(x, y)| *x || !*y));
    }
}
