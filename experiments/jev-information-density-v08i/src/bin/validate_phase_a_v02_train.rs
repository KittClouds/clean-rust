use anyhow::{Context, Result, ensure};
use jev_decision_world_v01::{WorldTemplate, validate_jsonl};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let run = PathBuf::from(args.next().context("expected Phase-A run directory")?);
    let output = PathBuf::from(args.next().context("expected audit output path")?);
    ensure!(args.next().is_none(), "unexpected extra arguments");

    let template_path = run.join("world-templates.json");
    let template_value: Value = serde_json::from_slice(
        &fs::read(&template_path)
            .with_context(|| format!("reading {}", template_path.display()))?,
    )?;
    ensure!(
        template_value.get("contract").and_then(Value::as_str)
            == Some("jev-like-decision-world/v0.1"),
        "wrong world-template contract"
    );
    let templates: Vec<WorldTemplate> = serde_json::from_value(
        template_value
            .get("templates")
            .context("missing templates")?
            .clone(),
    )?;

    let train_path = run.join("train-exact-world-episodes.jsonl");
    let report = validate_jsonl(&train_path, &templates)?;
    ensure!(report.episodes == 36_000, "unexpected train episode count");
    ensure!(
        report.failed == 0,
        "exact-world validation failures: {:?}",
        report.errors
    );

    let receipt = serde_json::json!({
        "audit": "independent-exact-world-train-validation",
        "status": "PASS",
        "run_identity": "phase-a-v02-clean",
        "input_path": train_path,
        "input_bytes": fs::metadata(&train_path)?.len(),
        "template_path": template_path,
        "template_count": templates.len(),
        "episodes": report.episodes,
        "failed": report.failed,
        "errors": report.errors,
        "heldout_episode_bodies_opened": false,
        "model_contact": false,
        "phoenix_access": false
    });
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent)?;
    }
    let temporary = output.with_extension("json.tmp");
    fs::write(&temporary, serde_json::to_vec_pretty(&receipt)?)?;
    fs::rename(&temporary, &output)?;
    println!("{}", serde_json::to_string(&receipt)?);
    Ok(())
}
