use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use anyhow::{Context, Result, ensure};
use jev_decision_world_v01::{
    GenerationConfig, RenderFormat, all_templates, generate_episode, observation_perturbation,
    surface_perturbation, world_perturbation,
};
use jev_decision_world_v02::synthetic::from_v01;
use jev_decision_world_v02::types::CanonicalEpisode;
use jev_decision_world_v02::validate::validate_episode;
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
struct BankManifest {
    protocol: String,
    base_per_template: usize,
    episodes: usize,
    query_objects: usize,
    sibling_classes: Vec<String>,
    output: String,
}

fn main() -> Result<()> {
    let output_dir = PathBuf::from(
        std::env::var("JEV_READOUT_OUTPUT")
            .unwrap_or_else(|_| r"D:\codex-runs\jev-frozen-readout-v01".to_string()),
    );
    fs::create_dir_all(&output_dir).with_context(|| format!("create {}", output_dir.display()))?;
    let base_per_template = std::env::var("JEV_READOUT_BASE_PER_TEMPLATE")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(300)
        .max(1);
    let episodes = generate_bank(base_per_template)?;
    for episode in &episodes {
        validate_episode(episode)?;
    }
    let jsonl = output_dir.join("readout-episodes.jsonl");
    write_jsonl(&jsonl, &episodes)?;
    let manifest = BankManifest {
        protocol: "jev-frozen-compatibility-readout-v0.2".to_string(),
        base_per_template,
        episodes: episodes.len(),
        query_objects: episodes.iter().map(|episode| episode.queries.len()).sum(),
        sibling_classes: vec![
            "surface_invariance".to_string(),
            "observation_intervention".to_string(),
            "world_intervention".to_string(),
        ],
        output: jsonl.display().to_string(),
    };
    fs::write(
        output_dir.join("bank-manifest.json"),
        serde_json::to_vec_pretty(&manifest)?,
    )?;
    println!(
        "validated_episodes={} query_objects={} output_dir={}",
        manifest.episodes,
        manifest.query_objects,
        output_dir.display()
    );
    Ok(())
}

fn generate_bank(base_per_template: usize) -> Result<Vec<CanonicalEpisode>> {
    let config = GenerationConfig {
        seed: 0x004a_4556_5244_3032,
        count: 1,
        visibility_probability: 0.80,
    };
    let mut episodes = Vec::with_capacity(base_per_template * 12);
    for (template_index, template) in all_templates().into_iter().enumerate() {
        for offset in 0..base_per_template {
            let sequence = template_index * base_per_template + offset;
            let parent = generate_episode(&template, sequence, &config)?;
            let parent_id = parent.episode_id.clone();
            episodes.push(from_v01(&parent, &template)?);

            let surface = surface_perturbation(&parent, &template, RenderFormat::Prose)?;
            episodes.push(from_v01(&surface, &template)?);

            if let Some(fact_id) = parent.evidence_state.visible_fact_ids.first() {
                let child = observation_perturbation(&parent, &template, fact_id)?;
                episodes.push(from_v01(&child, &template)?);
            }

            let variable = intervention_variable(&template.family_id);
            let variable_index = template
                .variable_index(variable)
                .with_context(|| format!("missing intervention variable {variable}"))?;
            let width = template.variables[variable_index].domain.len();
            ensure!(width > 1, "intervention variable must have two values");
            let current = usize::from(parent.sampled_world[variable_index]);
            let next = ((current + 1) % width) as u8;
            let child = world_perturbation(&parent, &template, variable, next)?;
            ensure!(
                child.episode_id.starts_with(&parent_id),
                "world sibling id mismatch"
            );
            episodes.push(from_v01(&child, &template)?);
        }
    }
    Ok(episodes)
}

fn intervention_variable(family_id: &str) -> &'static str {
    match family_id {
        "system_diagnosis" => "root_cause",
        "support_routing" => "route",
        "network_incident" => "incident_type",
        _ => "root_cause",
    }
}

fn write_jsonl(path: &PathBuf, episodes: &[CanonicalEpisode]) -> Result<()> {
    let file = File::create(path).with_context(|| format!("create {}", path.display()))?;
    let mut writer = BufWriter::new(file);
    for episode in episodes {
        serde_json::to_writer(&mut writer, episode)?;
        writer.write_all(b"\n")?;
    }
    writer
        .flush()
        .with_context(|| format!("flush {}", path.display()))?;
    Ok(())
}
