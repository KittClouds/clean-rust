use anyhow::{Context, Result, ensure};

use super::common::hard_choice_episode;
use crate::types::{CandidateDefinition, CandidateKind};

pub const ADAPTER_ID: &str = "multitask_classification_v0.2";

pub fn normalize_row(
    row: &serde_json::Value,
    row_id: &str,
    revision: &str,
    split: &str,
) -> Result<crate::types::CanonicalEpisode> {
    let input = row
        .get("input")
        .and_then(serde_json::Value::as_str)
        .context("multitask row missing input")?;
    let parsed: serde_json::Value =
        serde_json::from_str(input).context("multitask input is not embedded JSON")?;
    let text = parsed
        .get("text")
        .and_then(serde_json::Value::as_str)
        .context("multitask input missing text")?;
    let instruction = parsed
        .get("instructions")
        .and_then(serde_json::Value::as_str);
    let choices = parsed
        .get("choices")
        .and_then(serde_json::Value::as_object)
        .context("multitask input missing choices")?;
    let labels = row
        .get("label")
        .and_then(serde_json::Value::as_array)
        .context("multitask row missing label vector")?;
    ensure!(
        labels.len() == choices.len(),
        "multitask label/choice length mismatch"
    );
    let selected = labels
        .iter()
        .position(|value| value.as_f64() == Some(1.0))
        .context("multitask row is not one-hot")?;
    let label = choices
        .keys()
        .nth(selected)
        .context("multitask selected choice missing")?;
    let candidates = choices
        .iter()
        .map(|(name, description)| CandidateDefinition {
            candidate_id: name.clone(),
            candidate_semantic_id: name.clone(),
            kind: CandidateKind::Label,
            name: Some(name.clone()),
            description: description.as_str().map(str::to_string),
            aliases: Vec::new(),
            opaque_id: None,
            parent_candidate_semantic_id: None,
            order_rank: None,
            mutually_exclusive_group_id: Some("source-choice".to_string()),
            independent_allowed: false,
        })
        .collect();
    hard_choice_episode(
        ADAPTER_ID,
        "0.2.0",
        "sr5434/multitask-classification-dataset",
        revision,
        split,
        row_id,
        text,
        instruction,
        label,
        candidates,
        vec!["current Hub metadata does not declare a license".to_string()],
        None,
        None,
    )
}
