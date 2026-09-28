use anyhow::{Context, Result, ensure};
use jev_decision_world_v01::{WorldTemplate, validate_jsonl};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

const PANEL_IDENTITY: &str = "v0.8P-fresh-eval-panel-v01";
const PARTITION: &str = "eval_v08p";
const NEIGHBORHOODS: usize = 2_000;
const EPISODES_PER_NEIGHBORHOOD: usize = 11;
const TOLERANCE: f64 = 1.0e-12;

fn sha256_file(path: &Path) -> Result<String> {
    let bytes = fs::read(path).with_context(|| format!("read {}", path.display()))?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

fn read_json(path: &Path) -> Result<Value> {
    Ok(serde_json::from_slice(&fs::read(path).with_context(|| format!("read {}", path.display()))?)?)
}

fn next_value(reader: &mut impl BufRead) -> Result<Option<Value>> {
    let mut line = String::new();
    if reader.read_line(&mut line)? == 0 { return Ok(None); }
    Ok(Some(serde_json::from_str(line.trim_end())?))
}

fn probabilities(row: &Value) -> Result<Vec<f64>> {
    row["gold_targets"][0]["value"]["probabilities"].as_array()
        .context("exact episode target missing")?.iter()
        .map(|entry| entry["probability"].as_f64().context("probability missing"))
        .collect()
}

fn canonical_distribution(row: &Value) -> Result<Vec<f64>> {
    row["gold_targets"][0]["target"]["distribution"].as_array()
        .context("canonical target missing")?.iter()
        .map(|entry| entry["probability"].as_f64().context("probability missing"))
        .collect()
}

fn close(a: &[f64], b: &[f64]) -> bool {
    a.len() == b.len() && a.iter().zip(b).all(|(left, right)| (left - right).abs() <= TOLERANCE)
}

fn top(values: &[f64]) -> usize {
    values.iter().enumerate().max_by(|a, b| a.1.total_cmp(b.1).then_with(|| b.0.cmp(&a.0))).map(|item| item.0).unwrap_or(0)
}

fn one_character_difference(a: &str, b: &str) -> bool {
    let left: Vec<char> = a.chars().collect();
    let right: Vec<char> = b.chars().collect();
    left.len() == right.len() && left.iter().zip(right.iter()).filter(|(x, y)| x != y).count() == 1
}

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let panel = PathBuf::from(args.next().context("usage: validate_panel <panel-root> <contract> <receipt-output>")?);
    let contract_path = PathBuf::from(args.next().context("missing contract path")?);
    let receipt_path = PathBuf::from(args.next().context("missing receipt output")?);
    ensure!(args.next().is_none(), "unexpected validator arguments");
    ensure!(!receipt_path.exists(), "exact-world receipt already exists");
    let contract = read_json(&contract_path)?;
    ensure!(contract["identity"] == PANEL_IDENTITY, "P contract identity mismatch");

    let templates_value = read_json(&panel.join("world-templates.json"))?;
    ensure!(templates_value["contract"] == "jev-like-decision-world/v0.1", "template contract mismatch");
    let templates: Vec<WorldTemplate> = serde_json::from_value(templates_value["templates"].clone())?;
    ensure!(templates.len() == 16, "expected 16 family/profile templates");
    let exact_path = panel.join("eval-exact-world-episodes.jsonl");
    let canonical_path = panel.join("eval-canonical-episodes.jsonl");
    let certificate_path = panel.join("eval-contrast-certificates.jsonl");
    let solver = validate_jsonl(&exact_path, &templates)?;
    ensure!(solver.failed == 0, "independent exact solver rejected episodes: {:?}", solver.errors);
    ensure!(solver.episodes == 22_000, "exact solver row count mismatch");

    let mut exact = BufReader::new(File::open(&exact_path)?);
    let mut canonical = BufReader::new(File::open(&canonical_path)?);
    let mut certificates = BufReader::new(File::open(&certificate_path)?);
    let expected_families: BTreeMap<String, usize> = contract["freshness_and_scope"]["family_basis"].as_array()
        .context("family basis missing")?.iter().map(|row| Ok((
            row["slug"].as_str().context("family slug missing")?.to_owned(),
            row["neighborhoods"].as_u64().context("family quota missing")? as usize,
        ))).collect::<Result<_>>()?;
    let mut family_counts = BTreeMap::<String, usize>::new();
    let mut episode_ids = BTreeSet::new();
    let mut anchor_ids = BTreeSet::new();
    let mut target_failures = 0usize;
    let mut fact_failures = 0usize;
    let mut surface_failures = 0usize;
    let mut schema_failures = 0usize;

    for _ in 0..NEIGHBORHOODS {
        let cert = next_value(&mut certificates)?.context("certificate stream truncated")?;
        ensure!(cert["partition"] == PARTITION, "wrong partition namespace");
        let anchor_id = cert["anchor_id"].as_str().context("anchor ID missing")?.to_owned();
        ensure!(anchor_ids.insert(anchor_id.clone()), "duplicate anchor ID: {anchor_id}");
        ensure!(cert["neutral_candidate_count"] == 8, "neutral count drift: {anchor_id}");
        ensure!(cert["nuisance_axes"]["independent"] == true && cert["nuisance_axes"]["pairwise_distinct"] == true, "nuisance-axis independence failed: {anchor_id}");
        ensure!(cert["nuisance_axes"]["sham"] != cert["nuisance_axes"]["neutral"][0], "sham and neutral axis collided: {anchor_id}");
        let mut exact_rows = Vec::with_capacity(EPISODES_PER_NEIGHBORHOOD);
        let mut canonical_rows = Vec::with_capacity(EPISODES_PER_NEIGHBORHOOD);
        for _ in 0..EPISODES_PER_NEIGHBORHOOD {
            exact_rows.push(next_value(&mut exact)?.context("exact episode stream truncated")?);
            canonical_rows.push(next_value(&mut canonical)?.context("canonical episode stream truncated")?);
        }
        let expected_ids = [
            cert["episode_ids"]["anchor"].as_str().context("anchor episode ID missing")?,
            cert["episode_ids"]["fact_flip"].as_str().context("fact episode ID missing")?,
            cert["episode_ids"]["sham"].as_str().context("sham episode ID missing")?,
        ];
        ensure!(exact_rows[0]["episode_id"] == expected_ids[0] && exact_rows[1]["episode_id"] == expected_ids[1] && exact_rows[2]["episode_id"] == expected_ids[2], "anchor/fact/sham identity mismatch: {anchor_id}");
        let neutral_ids = cert["episode_ids"]["neutrals"].as_array().context("neutral IDs missing")?;
        ensure!(neutral_ids.len() == 8, "neutral ID list size mismatch: {anchor_id}");
        for index in 0..8 { ensure!(exact_rows[index + 3]["episode_id"] == neutral_ids[index], "neutral identity/order mismatch: {anchor_id}"); }
        let mut ids_local = BTreeSet::new();
        for index in 0..EPISODES_PER_NEIGHBORHOOD {
            let exact_row = &exact_rows[index];
            let canonical_row = &canonical_rows[index];
            let episode_id = exact_row["episode_id"].as_str().context("episode ID absent")?.to_owned();
            ensure!(ids_local.insert(episode_id.clone()) && episode_ids.insert(episode_id.clone()), "duplicate episode identity: {episode_id}");
            ensure!(canonical_row["episode_id"] == episode_id, "exact/canonical episode identity mismatch");
            ensure!(exact_row["template"]["family_id"] == exact_rows[0]["template"]["family_id"], "latent template family differs within neighborhood");
            ensure!(exact_row["template"]["template_id"] == exact_rows[0]["template"]["template_id"], "template differs within neighborhood");
            ensure!(exact_row["sampled_world"] == exact_rows[0]["sampled_world"], "sampled world differs within neighborhood");
            ensure!(canonical_row["identity"]["world_instance_id"] == canonical_rows[0]["identity"]["world_instance_id"], "canonical world identity differs");
            ensure!(canonical_row["queries"] == canonical_rows[0]["queries"], "query changed within neighborhood");
            ensure!(canonical_row["runtime_schema"] == canonical_rows[0]["runtime_schema"], "schema/candidate order changed within neighborhood");
            let expected_parent = format!("{anchor_id}-anchor");
            if index == 0 {
                ensure!(exact_row["perturbation_links"].as_array().map_or(true, |links| links.is_empty()), "anchor unexpectedly has a perturbation parent");
            } else {
                let links = exact_row["perturbation_links"].as_array().context("sibling intervention link missing")?;
                ensure!(links.len() == 1 && links[0]["parent_episode_id"] == expected_parent, "sibling has non-single or misbound intervention: {episode_id}");
            }
        }

        let targets: Vec<Vec<f64>> = exact_rows.iter().map(probabilities).collect::<Result<_>>()?;
        let canonical_targets: Vec<Vec<f64>> = canonical_rows.iter().map(canonical_distribution).collect::<Result<_>>()?;
        let cert_before: Vec<f64> = cert["exact_target_before"].as_array().context("cert before target missing")?.iter().map(|v| v.as_f64().context("cert target value invalid")).collect::<Result<_>>()?;
        let cert_after: Vec<f64> = cert["exact_target_after"].as_array().context("cert after target missing")?.iter().map(|v| v.as_f64().context("cert target value invalid")).collect::<Result<_>>()?;
        let invariant = targets.iter().skip(2).enumerate().all(|(i, target)| close(&targets[0], target) && close(&canonical_targets[0], &canonical_targets[i + 2]));
        if !invariant || !close(&targets[0], &canonical_targets[0]) || !close(&targets[0], &cert_before) || !close(&targets[1], &cert_after) { target_failures += 1; }
        if top(&targets[0]) == top(&targets[1]) { fact_failures += 1; }
        let anchor_text = canonical_rows[0]["state"]["observable"]["content"].as_str().context("anchor content absent")?;
        for sibling in canonical_rows.iter().skip(1) {
            let text = sibling["state"]["observable"]["content"].as_str().context("sibling content absent")?;
            let a_lines: Vec<&str> = anchor_text.lines().collect();
            let b_lines: Vec<&str> = text.lines().collect();
            if !one_character_difference(anchor_text, text) || a_lines.len() != b_lines.len() || a_lines.iter().zip(&b_lines).filter(|(a, b)| a != b).count() != 1 { surface_failures += 1; break; }
        }
        let expected_schema = cert["schema_family_id"].as_str().context("schema ID missing")?;
        let slug = expected_schema.rsplit(':').next().unwrap_or_default();
        ensure!(expected_families.contains_key(slug), "unexpected family {slug}");
        if canonical_rows.iter().any(|row| row["identity"]["schema_family_id"] != expected_schema) { schema_failures += 1; }
        *family_counts.entry(slug.to_owned()).or_default() += 1;
    }

    ensure!(next_value(&mut exact)?.is_none(), "extra exact episode rows");
    ensure!(next_value(&mut canonical)?.is_none(), "extra canonical episode rows");
    ensure!(next_value(&mut certificates)?.is_none(), "extra contrast certificates");
    ensure!(family_counts == expected_families, "family quotas mismatch: {family_counts:?}");
    ensure!([target_failures, fact_failures, surface_failures, schema_failures] == [0, 0, 0, 0], "semantic validation failures: targets={target_failures}, fact={fact_failures}, surface={surface_failures}, schema={schema_failures}");

    if let Some(parent) = receipt_path.parent() { fs::create_dir_all(parent)?; }
    let receipt = json!({
        "status":"V08P_EXACT_WORLD_PANEL_VALIDATION_PASS",
        "identity":PANEL_IDENTITY,
        "contract_sha256":sha256_file(&contract_path)?,
        "partition_namespace":PARTITION,
        "family_neighborhood_counts":family_counts,
        "neighborhood_count":anchor_ids.len(),
        "episode_count":episode_ids.len(),
        "candidate_schemas":4,
        "exact_world_solver":{"episodes":solver.episodes,"failed":solver.failed,"errors":solver.errors},
        "semantic_audit":{"target_failures":target_failures,"fact_flip_failures":fact_failures,"surface_edit_failures":surface_failures,"schema_failures":schema_failures},
        "source_hashes":{
            "exact_episodes":sha256_file(&exact_path)?,
            "canonical_episodes":sha256_file(&canonical_path)?,
            "contrast_certificates":sha256_file(&certificate_path)?,
            "world_templates":sha256_file(&panel.join("world-templates.json"))?
        },
        "model_load":false,"head_load":false,"training":false,"evaluation_inference":false,
        "behavioral_metrics":false,"newtight_access":false,"legacy_evaluation_access":false,"phoenix_access":false
    });
    let mut out = BufWriter::new(File::create(&receipt_path)?);
    serde_json::to_writer_pretty(&mut out, &receipt)?;
    out.write_all(b"\n")?;
    out.flush()?;
    println!("{}", serde_json::to_string(&receipt)?);
    Ok(())
}
