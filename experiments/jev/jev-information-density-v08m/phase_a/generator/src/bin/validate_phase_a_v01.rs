use anyhow::{Context, Result, ensure};
use jev_decision_world_v01::{WorldTemplate, validate_jsonl};
use serde_json::Value;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

const TOLERANCE: f64 = 1.0e-12;

fn read_json(path: &Path) -> Result<Value> {
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}

fn distribution(episode: &Value) -> Result<Vec<f64>> {
    episode["gold_targets"][0]["value"]["probabilities"]
        .as_array()
        .context("choice probabilities missing")?
        .iter()
        .map(|entry| entry["probability"].as_f64().context("probability missing"))
        .collect()
}

fn close(left: &[f64], right: &[f64]) -> bool {
    left.len() == right.len()
        && left.iter().zip(right).all(|(a, b)| (a - b).abs() <= TOLERANCE)
}

fn top(values: &[f64]) -> usize {
    values
        .iter()
        .enumerate()
        .max_by(|a, b| a.1.total_cmp(b.1))
        .map(|(index, _)| index)
        .unwrap()
}

fn diff_chars(left: &str, right: &str) -> usize {
    let shared = left.chars().zip(right.chars()).filter(|(a, b)| a != b).count();
    shared + left.chars().skip(right.chars().count()).count() + right.chars().skip(left.chars().count()).count()
}

fn next_json_line(reader: &mut impl BufRead) -> Result<Option<Value>> {
    let mut line = String::new();
    if reader.read_line(&mut line)? == 0 {
        return Ok(None);
    }
    Ok(Some(serde_json::from_str(line.trim_end())?))
}

fn validate_partition(run: &Path, partition: &str, expected_neighborhoods: usize) -> Result<Value> {
    let exact_path = run.join(format!("{partition}-exact-world-episodes.jsonl"));
    let canonical_path = run.join(format!("{partition}-canonical-episodes.jsonl"));
    let certificate_path = run.join(format!("{partition}-contrast-certificates.jsonl"));
    let templates_path = run.join("world-templates.json");
    let templates_value = read_json(&templates_path)?;
    ensure!(templates_value["contract"] == "jev-like-decision-world/v0.1", "template contract drift");
    let templates: Vec<WorldTemplate> = serde_json::from_value(templates_value["templates"].clone())?;
    let exact_report = validate_jsonl(&exact_path, &templates)?;
    ensure!(exact_report.failed == 0, "exact-world validation failed: {:?}", exact_report.errors);
    ensure!(exact_report.episodes == expected_neighborhoods * 4, "exact episode count drift");

    let mut exact = BufReader::new(File::open(&exact_path)?);
    let mut canonical = BufReader::new(File::open(&canonical_path)?);
    let mut certificates = BufReader::new(File::open(&certificate_path)?);
    let mut episode_ids = std::collections::BTreeSet::new();
    let mut family_ids = std::collections::BTreeSet::new();
    let mut template_ids = std::collections::BTreeSet::new();
    let mut neighborhoods = 0usize;
    let mut surface_edit_failures = 0usize;
    let mut target_failures = 0usize;
    let mut schema_failures = 0usize;
    let mut independence_failures = 0usize;
    let mut fact_flip_failures = 0usize;

    loop {
        let Some(certificate) = next_json_line(&mut certificates)? else { break };
        neighborhoods += 1;
        let mut exact_rows = Vec::with_capacity(4);
        let mut canonical_rows = Vec::with_capacity(4);
        for _ in 0..4 {
            exact_rows.push(next_json_line(&mut exact)?.context("truncated exact episode stream")?);
            canonical_rows.push(next_json_line(&mut canonical)?.context("truncated canonical episode stream")?);
        }
        ensure!(certificate["nuisance_axes"]["independent"] == true, "nuisance independence certificate missing");
        ensure!(certificate["nuisance_axes"]["sham"] != certificate["nuisance_axes"]["neutral"], "nuisance axes are not distinct");
        ensure!(certificate["episode_ids"]["anchor"] == exact_rows[0]["episode_id"], "anchor id mismatch");
        ensure!(certificate["episode_ids"]["fact_flip"] == exact_rows[1]["episode_id"], "fact id mismatch");
        ensure!(certificate["episode_ids"]["sham"] == exact_rows[2]["episode_id"], "sham id mismatch");
        ensure!(certificate["episode_ids"]["neutral"] == exact_rows[3]["episode_id"], "neutral id mismatch");
        let distributions: Vec<Vec<f64>> = exact_rows.iter().map(distribution).collect::<Result<_>>()?;
        let cert_before: Vec<f64> = certificate["exact_target_before"].as_array().context("before target missing")?.iter().map(|v| v.as_f64().context("before value missing")).collect::<Result<_>>()?;
        let cert_after: Vec<f64> = certificate["exact_target_after"].as_array().context("after target missing")?.iter().map(|v| v.as_f64().context("after value missing")).collect::<Result<_>>()?;
        let cert_sham: Vec<f64> = certificate["exact_sham_target"].as_array().context("sham target missing")?.iter().map(|v| v.as_f64().context("sham value missing")).collect::<Result<_>>()?;
        let cert_neutral: Vec<f64> = certificate["exact_neutral_target"].as_array().context("neutral target missing")?.iter().map(|v| v.as_f64().context("neutral value missing")).collect::<Result<_>>()?;
        let cert_joint: Vec<f64> = certificate["exact_joint_nuisance_target"].as_array().context("joint target missing")?.iter().map(|v| v.as_f64().context("joint value missing")).collect::<Result<_>>()?;
        let target_ok = close(&distributions[0], &cert_before)
            && close(&distributions[1], &cert_after)
            && close(&distributions[2], &cert_sham)
            && close(&distributions[3], &cert_neutral)
            && close(&distributions[0], &distributions[2])
            && close(&distributions[0], &distributions[3])
            && close(&distributions[0], &cert_joint);
        if !target_ok { target_failures += 1; }
        if top(&distributions[0]) == top(&distributions[1]) { fact_flip_failures += 1; }
        let texts: Vec<&str> = canonical_rows.iter().map(|row| row["state"]["observable"]["content"].as_str().unwrap()).collect();
        let surface_ok = texts[0].lines().count() == 4
            && texts[0].lines().zip(texts[1].lines()).filter(|(a, b)| a != b).count() == 1
            && texts[0].lines().zip(texts[2].lines()).filter(|(a, b)| a != b).count() == 1
            && texts[0].lines().zip(texts[3].lines()).filter(|(a, b)| a != b).count() == 1
            && diff_chars(texts[0].lines().nth(1).unwrap(), texts[1].lines().nth(1).unwrap()) == 1
            && diff_chars(texts[0].lines().nth(2).unwrap(), texts[2].lines().nth(2).unwrap()) == 1
            && diff_chars(texts[0].lines().nth(3).unwrap(), texts[3].lines().nth(3).unwrap()) == 1;
        if !surface_ok { surface_edit_failures += 1; }
        let schema_ok = (1..4).all(|index| canonical_rows[0]["runtime_schema"] == canonical_rows[index]["runtime_schema"] && canonical_rows[0]["queries"] == canonical_rows[index]["queries"] && canonical_rows[0]["identity"]["world_instance_id"] == canonical_rows[index]["identity"]["world_instance_id"]);
        if !schema_ok { schema_failures += 1; }
        if certificate["nuisance_axes"]["independent"] != true { independence_failures += 1; }
        for row in &exact_rows {
            let id = row["episode_id"].as_str().context("episode id missing")?;
            ensure!(episode_ids.insert(id.to_string()), "duplicate episode id");
            family_ids.insert(row["template"]["family_id"].as_str().unwrap().to_string());
            template_ids.insert(row["template"]["template_id"].as_str().unwrap().to_string());
        }
    }
    ensure!(neighborhoods == expected_neighborhoods, "certificate count drift");
    ensure!(next_json_line(&mut exact)?.is_none(), "extra exact episodes");
    ensure!(next_json_line(&mut canonical)?.is_none(), "extra canonical episodes");
    ensure!(next_json_line(&mut certificates)?.is_none(), "extra certificates");
    ensure!(target_failures == 0, "target preservation failures: {target_failures}");
    ensure!(fact_flip_failures == 0, "fact flip failures: {fact_flip_failures}");
    ensure!(surface_edit_failures == 0, "surface edit failures: {surface_edit_failures}");
    ensure!(schema_failures == 0, "schema/world failures: {schema_failures}");
    ensure!(independence_failures == 0, "independence failures: {independence_failures}");
    Ok(serde_json::json!({
        "partition": partition,
        "neighborhoods": neighborhoods,
        "episodes": neighborhoods * 4,
        "episode_id_count": episode_ids.len(),
        "family_count": family_ids.len(),
        "family_ids": family_ids,
        "template_ids": template_ids,
        "exact_world_validation": exact_report,
        "target_failures": target_failures,
        "fact_flip_failures": fact_flip_failures,
        "surface_edit_failures": surface_edit_failures,
        "schema_failures": schema_failures,
        "independence_failures": independence_failures
    }))
}

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let run = PathBuf::from(args.next().context("expected run directory")?);
    let output = PathBuf::from(args.next().context("expected output path")?);
    ensure!(args.next().is_none(), "unexpected arguments");
    let train = validate_partition(&run, "train", 12_000)?;
    let eval = validate_partition(&run, "eval", 2_000)?;
    let train_families: std::collections::BTreeSet<String> = train["family_ids"]
        .as_array().context("train family ids missing")?
        .iter().map(|value| value.as_str().unwrap().to_string()).collect();
    let eval_families: std::collections::BTreeSet<String> = eval["family_ids"]
        .as_array().context("eval family ids missing")?
        .iter().map(|value| value.as_str().unwrap().to_string()).collect();
    let train_templates: std::collections::BTreeSet<String> = train["template_ids"]
        .as_array().context("train template ids missing")?
        .iter().map(|value| value.as_str().unwrap().to_string()).collect();
    let eval_templates: std::collections::BTreeSet<String> = eval["template_ids"]
        .as_array().context("eval template ids missing")?
        .iter().map(|value| value.as_str().unwrap().to_string()).collect();
    let family_overlap: Vec<String> = train_families.intersection(&eval_families).cloned().collect();
    let template_overlap: Vec<String> = train_templates.intersection(&eval_templates).cloned().collect();
    ensure!(family_overlap.is_empty(), "train/eval family overlap: {family_overlap:?}");
    ensure!(template_overlap.is_empty(), "train/eval template overlap: {template_overlap:?}");
    let report = serde_json::json!({
        "status": "PHASE_A0_INDEPENDENT_EXACT_WORLD_VALIDATION_PASS",
        "protocol": "jev-information-density/v0.8m-phase-a",
        "run_identity": "phase-a-v01-clean",
        "train": train,
        "eval": eval,
        "train_eval_family_overlap": family_overlap,
        "train_eval_template_overlap": template_overlap,
        "model_contact": false,
        "feature_extraction": false,
        "training": false,
        "evaluation_inference": false,
        "protected_evaluation_bodies_opened": false,
        "phoenix_access": false,
        "implementation_note": "independent validator; generator self-validation is not used as the sole gate"
    });
    if let Some(parent) = output.parent() { fs::create_dir_all(parent)?; }
    let mut writer = BufWriter::new(File::create(&output)?);
    serde_json::to_writer_pretty(&mut writer, &report)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}
