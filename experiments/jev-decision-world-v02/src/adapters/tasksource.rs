use anyhow::{Context, Result};

use super::common::hard_choice_episode;
use crate::types::{CandidateDefinition, CandidateKind};

pub const ADAPTER_ID: &str = "tasksource_zero_shot_nli_v0.2";

pub fn normalize_row(
    row: &serde_json::Value,
    row_id: &str,
    revision: &str,
    split: &str,
) -> Result<crate::types::CanonicalEpisode> {
    let premise = row
        .get("premise")
        .and_then(serde_json::Value::as_str)
        .context("tasksource row missing premise")?;
    let hypothesis = row
        .get("hypothesis")
        .and_then(serde_json::Value::as_str)
        .context("tasksource row missing hypothesis")?;
    let task = row
        .get("task")
        .and_then(serde_json::Value::as_str)
        .context("tasksource row missing task")?;
    let label = match row
        .get("labels")
        .and_then(serde_json::Value::as_u64)
        .context("tasksource row missing labels")?
    {
        0 => "entailment",
        1 => "neutral",
        2 => "contradiction",
        other => anyhow::bail!("tasksource NLI label {other} outside 0..2"),
    };
    let candidates = [
        ("entailment", "The hypothesis is supported by the premise."),
        ("neutral", "The premise does not determine the hypothesis."),
        (
            "contradiction",
            "The hypothesis conflicts with the premise.",
        ),
    ]
    .into_iter()
    .map(|(name, description)| CandidateDefinition {
        candidate_id: name.to_string(),
        candidate_semantic_id: name.to_string(),
        kind: CandidateKind::Label,
        name: Some(name.to_string()),
        description: Some(description.to_string()),
        aliases: Vec::new(),
        opaque_id: None,
        parent_candidate_semantic_id: None,
        order_rank: None,
        mutually_exclusive_group_id: Some("nli-choice".to_string()),
        independent_allowed: false,
    })
    .collect();
    let text = format!("Premise: {premise}\nHypothesis: {hypothesis}");
    let mut episode = hard_choice_episode(
        ADAPTER_ID,
        "0.2.0",
        "tasksource/zero-shot-label-nli",
        revision,
        split,
        row_id,
        &text,
        Some("Determine the NLI relation between premise and hypothesis."),
        label,
        candidates,
        vec![
            "aggregate source with many upstream datasets".to_string(),
            format!("upstream task={task}"),
            "excluded from primary benchmark until lineage joins are complete".to_string(),
        ],
        Some(task.to_string()),
        None,
    )?;
    episode
        .evaluation_constraints
        .excluded_from_primary_benchmark = true;
    episode
        .evaluation_constraints
        .notes
        .push("aggregate-wrapper overlap quarantine".to_string());
    episode.identity.task_family_ids = vec!["choice".to_string(), "nli".to_string()];
    Ok(episode)
}
