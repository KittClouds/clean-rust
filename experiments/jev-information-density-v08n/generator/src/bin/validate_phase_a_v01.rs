use anyhow::{Context, Result, ensure};
use jev_decision_world_v01::{WorldTemplate, validate_jsonl};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

const EPISODES_PER_NEIGHBORHOOD: usize = 11;
const NEUTRAL_COUNT: usize = 8;
const TOLERANCE: f64 = 1.0e-12;

fn read_json(path: &Path) -> Result<Value> { Ok(serde_json::from_slice(&fs::read(path)?)?) }
fn distribution(row: &Value) -> Result<Vec<f64>> { row["gold_targets"][0]["value"]["probabilities"].as_array().context("choice probabilities missing")?.iter().map(|p| p["probability"].as_f64().context("probability missing")).collect() }
fn close(a: &[f64], b: &[f64]) -> bool { a.len() == b.len() && a.iter().zip(b).all(|(x,y)| (x-y).abs() <= TOLERANCE) }
fn top(values: &[f64]) -> usize { values.iter().enumerate().max_by(|a,b| a.1.total_cmp(b.1)).unwrap().0 }
fn next_json(reader: &mut impl BufRead) -> Result<Option<Value>> { let mut line = String::new(); if reader.read_line(&mut line)? == 0 { return Ok(None); } Ok(Some(serde_json::from_str(line.trim_end())?)) }
fn diff_chars(a: &str, b: &str) -> usize { let common = a.chars().zip(b.chars()).filter(|(x,y)| x != y).count(); common + a.chars().skip(b.chars().count()).count() + b.chars().skip(a.chars().count()).count() }

fn validate_partition(run: &Path, partition: &str, neighborhoods_expected: usize) -> Result<Value> {
    let exact_path = run.join(format!("{partition}-exact-world-episodes.jsonl"));
    let canonical_path = run.join(format!("{partition}-canonical-episodes.jsonl"));
    let certificate_path = run.join(format!("{partition}-contrast-certificates.jsonl"));
    let template_value = read_json(&run.join("world-templates.json"))?;
    ensure!(template_value["contract"] == "jev-like-decision-world/v0.1", "template contract drift");
    let templates: Vec<WorldTemplate> = serde_json::from_value(template_value["templates"].clone())?;
    let exact_report = validate_jsonl(&exact_path, &templates)?;
    ensure!(exact_report.failed == 0, "exact-world failures: {:?}", exact_report.errors);
    ensure!(exact_report.episodes == neighborhoods_expected * EPISODES_PER_NEIGHBORHOOD, "episode count drift");
    let mut exact = BufReader::new(File::open(exact_path)?);
    let mut canonical = BufReader::new(File::open(canonical_path)?);
    let mut certificates = BufReader::new(File::open(certificate_path)?);
    let mut episode_ids = BTreeSet::new();
    let mut family_ids = BTreeSet::new();
    let mut template_ids = BTreeSet::new();
    let mut neighborhoods = 0usize;
    let mut failures = [0usize; 4];
    loop {
        let Some(certificate) = next_json(&mut certificates)? else { break };
        neighborhoods += 1;
        let mut exact_rows = Vec::with_capacity(EPISODES_PER_NEIGHBORHOOD);
        let mut canonical_rows = Vec::with_capacity(EPISODES_PER_NEIGHBORHOOD);
        for _ in 0..EPISODES_PER_NEIGHBORHOOD {
            exact_rows.push(next_json(&mut exact)?.context("truncated exact stream")?);
            canonical_rows.push(next_json(&mut canonical)?.context("truncated canonical stream")?);
        }
        let ids = certificate["episode_ids"]["neutrals"].as_array().context("neutral ids missing")?;
        ensure!(ids.len() == NEUTRAL_COUNT, "neutral id count drift");
        ensure!(certificate["episode_ids"]["anchor"] == exact_rows[0]["episode_id"], "anchor id drift");
        ensure!(certificate["episode_ids"]["fact_flip"] == exact_rows[1]["episode_id"], "fact id drift");
        ensure!(certificate["episode_ids"]["sham"] == exact_rows[2]["episode_id"], "sham id drift");
        for index in 0..NEUTRAL_COUNT { ensure!(ids[index] == exact_rows[index + 3]["episode_id"], "neutral id drift"); }
        let distributions: Vec<Vec<f64>> = exact_rows.iter().map(distribution).collect::<Result<_>>()?;
        let before: Vec<f64> = certificate["exact_target_before"].as_array().context("before target missing")?.iter().map(|v| v.as_f64().context("before value missing")).collect::<Result<_>>()?;
        let after: Vec<f64> = certificate["exact_target_after"].as_array().context("after target missing")?.iter().map(|v| v.as_f64().context("after value missing")).collect::<Result<_>>()?;
        let sham: Vec<f64> = certificate["exact_sham_target"].as_array().context("sham target missing")?.iter().map(|v| v.as_f64().context("sham value missing")).collect::<Result<_>>()?;
        let neutrals = certificate["exact_neutral_targets"].as_array().context("neutral targets missing")?;
        let joint: Vec<f64> = certificate["exact_joint_nuisance_target"].as_array().context("joint target missing")?.iter().map(|v| v.as_f64().context("joint value missing")).collect::<Result<_>>()?;
        let target_ok = close(&distributions[0], &before) && close(&distributions[1], &after) && close(&distributions[2], &sham) && close(&distributions[0], &distributions[2]) && close(&distributions[0], &joint) && neutrals.iter().enumerate().all(|(i,v)| v.as_array().map(|a| a.iter().filter_map(Value::as_f64).collect::<Vec<_>>()).map(|v| close(&distributions[0], &v) && close(&distributions[i+3], &v)).unwrap_or(false));
        if !target_ok { failures[0] += 1; }
        if top(&distributions[0]) == top(&distributions[1]) { failures[1] += 1; }
        let texts: Vec<Vec<&str>> = canonical_rows.iter().map(|row| row["state"]["observable"]["content"].as_str().unwrap().lines().collect()).collect();
        let surface_ok = texts.iter().all(|lines| lines.len() == 11) && (1..EPISODES_PER_NEIGHBORHOOD).all(|i| texts[0].iter().zip(&texts[i]).filter(|(a,b)| a != b).count() == 1) && diff_chars(texts[0][1], texts[1][1]) == 1 && diff_chars(texts[0][2], texts[2][2]) == 1 && (0..NEUTRAL_COUNT).all(|i| diff_chars(texts[0][i+3], texts[i+3][i+3]) == 1);
        if !surface_ok { failures[2] += 1; }
        let schema_ok = (1..EPISODES_PER_NEIGHBORHOOD).all(|i| canonical_rows[0]["runtime_schema"] == canonical_rows[i]["runtime_schema"] && canonical_rows[0]["queries"] == canonical_rows[i]["queries"] && canonical_rows[0]["identity"]["world_instance_id"] == canonical_rows[i]["identity"]["world_instance_id"]);
        if !schema_ok { failures[3] += 1; }
        for row in &exact_rows { ensure!(episode_ids.insert(row["episode_id"].as_str().context("episode id missing")?.to_string()), "duplicate episode id"); family_ids.insert(row["template"]["family_id"].as_str().unwrap().to_string()); template_ids.insert(row["template"]["template_id"].as_str().unwrap().to_string()); }
    }
    ensure!(neighborhoods == neighborhoods_expected, "certificate count drift");
    ensure!(next_json(&mut exact)?.is_none() && next_json(&mut canonical)?.is_none() && next_json(&mut certificates)?.is_none(), "extra partition rows");
    ensure!(failures == [0,0,0,0], "validation failures: {failures:?}");
    Ok(json!({"partition":partition,"neighborhoods":neighborhoods,"episodes":neighborhoods*EPISODES_PER_NEIGHBORHOOD,"episode_id_count":episode_ids.len(),"family_count":family_ids.len(),"family_ids":family_ids,"template_ids":template_ids,"exact_world_validation":exact_report,"target_failures":failures[0],"fact_flip_failures":failures[1],"surface_edit_failures":failures[2],"schema_failures":failures[3]}))
}

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let run = PathBuf::from(args.next().context("expected run directory")?);
    let output = PathBuf::from(args.next().context("expected output path")?);
    ensure!(args.next().is_none(), "unexpected arguments");
    let train = validate_partition(&run, "train", 12_000)?;
    let eval = validate_partition(&run, "eval", 2_000)?;
    let set = |value: &Value, key: &str| -> BTreeSet<String> { value[key].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_string()).collect() };
    let family_overlap: Vec<String> = set(&train,"family_ids").intersection(&set(&eval,"family_ids")).cloned().collect();
    let template_overlap: Vec<String> = set(&train,"template_ids").intersection(&set(&eval,"template_ids")).cloned().collect();
    ensure!(family_overlap.is_empty() && template_overlap.is_empty(), "train/eval overlap");
    let report = json!({"status":"V08N_N0_EXACT_WORLD_VALIDATION_PASS","protocol":"jev-information-density/v0.8n-base-v01","phase_identity":"v0.8N-base-v01","train":train,"eval":eval,"train_eval_family_overlap":family_overlap,"train_eval_template_overlap":template_overlap,"model_contact":false,"feature_extraction":false,"training":false,"evaluation_inference":false,"protected_evaluation_bodies_opened":false,"phoenix_access":false});
    if let Some(parent) = output.parent() { fs::create_dir_all(parent)?; }
    let mut writer = BufWriter::new(File::create(output)?);
    serde_json::to_writer_pretty(&mut writer, &report)?; writer.write_all(b"\n")?; writer.flush()?;
    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}
