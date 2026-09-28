use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::PathBuf;

use anyhow::{Context, Result, bail};
use jev_decision_world_v02::types::CanonicalEpisode;
use serde::Serialize;

#[derive(Serialize)]
struct SchemaMetadata {
    contract: String,
    episode_id: String,
    source_episode_id: String,
    ontology_regime: String,
    world_regime: String,
    factorial_cell: String,
    topology_class: String,
    transformation: String,
}

fn main() -> Result<()> {
    let options = Options::parse(std::env::args().skip(1))?;
    let input = BufReader::new(File::open(&options.input)?);
    let mut episodes = BufWriter::new(File::create(&options.episodes)?);
    let mut metadata = BufWriter::new(File::create(&options.metadata)?);
    let mut count = 0_usize;
    for (line_number, line) in input.lines().enumerate() {
        if line_number >= options.limit {
            break;
        }
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let mut episode: CanonicalEpisode = serde_json::from_str(&line)
            .with_context(|| format!("parse episode line {}", line_number + 1))?;
        let source_id = episode.identity.episode_id.clone();
        episode.identity.episode_id = format!("{source_id}-ontology-ood-v04");
        episode.identity.schema_family_id =
            format!("v04-ontology-heldout-deep-narrow-{}", count % 3);
        episode.identity.surface_renderer_id = "v04-heldout-schema-renderer".to_string();
        episode.runtime_schema.schema_id = format!("v04-heldout-schema-{}", count % 3);
        episode.runtime_schema.schema_family_id = episode.identity.schema_family_id.clone();
        for candidate in &mut episode.runtime_schema.candidates {
            let semantic = candidate.candidate_semantic_id.clone();
            candidate.name = Some(format!("Term_{}", count % 7));
            candidate.description = Some(format!(
                "Held-out definition: the runtime criterion represented by semantic key {semantic}."
            ));
            candidate.aliases = vec![format!("variant_alias_{}", count % 11)];
            candidate.opaque_id = Some(format!("Q{:04}", (count * 17) % 10000));
        }
        make_deep_narrow_hierarchy(&mut episode);
        episode.identity.semantic_fingerprint = blake3::hash(&episode.semantic_content_bytes()?)
            .to_hex()
            .to_string();
        serde_json::to_writer(&mut episodes, &episode)?;
        episodes.write_all(b"\n")?;
        let world_regime = if episode.identity.world_family_id.starts_with("world_ood") {
            "ood"
        } else {
            "id"
        };
        let record = SchemaMetadata {
            contract: "jev-frozen-saturation-true-ood-gate/v0.4".to_string(),
            episode_id: episode.identity.episode_id.clone(),
            source_episode_id: source_id,
            ontology_regime: "ood".to_string(),
            world_regime: world_regime.to_string(),
            factorial_cell: format!("ontology_ood_world_{world_regime}"),
            topology_class: "deep_narrow".to_string(),
            transformation: "opaque_surface_rebinding_plus_deep_narrow_runtime_hierarchy"
                .to_string(),
        };
        serde_json::to_writer(&mut metadata, &record)?;
        metadata.write_all(b"\n")?;
        count += 1;
    }
    episodes.flush()?;
    metadata.flush()?;
    println!("{{\"episodes\":{count}}}");
    Ok(())
}

fn make_deep_narrow_hierarchy(episode: &mut CanonicalEpisode) {
    for set in &episode.runtime_schema.candidate_sets {
        let mut previous: Option<String> = None;
        for candidate_id in &set.candidate_ids {
            if let Some(candidate) = episode
                .runtime_schema
                .candidates
                .iter_mut()
                .find(|candidate| candidate.candidate_id == *candidate_id)
            {
                candidate.parent_candidate_semantic_id = previous.clone();
                previous = Some(candidate.candidate_semantic_id.clone());
            }
        }
    }
}

struct Options {
    input: PathBuf,
    episodes: PathBuf,
    metadata: PathBuf,
    limit: usize,
}

impl Options {
    fn parse(mut args: impl Iterator<Item = String>) -> Result<Self> {
        let mut input = None;
        let mut episodes = None;
        let mut metadata = None;
        let mut limit = usize::MAX;
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--input" => input = Some(PathBuf::from(args.next().context("--input path")?)),
                "--episodes" => {
                    episodes = Some(PathBuf::from(args.next().context("--episodes path")?))
                }
                "--metadata" => {
                    metadata = Some(PathBuf::from(args.next().context("--metadata path")?))
                }
                "--limit" => limit = args.next().context("--limit value")?.parse()?,
                other => bail!("unknown argument {other}"),
            }
        }
        Ok(Self {
            input: input.context("--input is required")?,
            episodes: episodes.context("--episodes is required")?,
            metadata: metadata.context("--metadata is required")?,
            limit,
        })
    }
}
