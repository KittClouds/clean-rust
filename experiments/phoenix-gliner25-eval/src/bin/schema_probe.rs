//! Runs the pre-registered schema probe (probe/PREREGISTRATION.md) over the
//! frozen passages and writes one JSONL row per passage and setup.
//! Candidate-only: nothing is published to Phoenix.

use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::PathBuf;
use std::time::Instant;

use anyhow::{Context, Result};
use clap::Parser;
use gliner25_rs::overlap::OverlapPolicy;
use gliner25_rs::processor::SchemaTask;
use phoenix_gliner25_eval::features::{
    AttributeAssignment, AttributeGroupSpec, FeatureEngine, JointConfig, JointEntitySpec,
    JointRelationSpec, JointSchemaSpec,
};
use serde::Deserialize;
use serde_json::json;

#[derive(Parser)]
struct Args {
    #[arg(long, env = "GLINER25_MODEL")]
    model: PathBuf,
    #[arg(long, default_value_t = 8)]
    threads: usize,
    #[arg(long)]
    passages: PathBuf,
    #[arg(long)]
    output: PathBuf,
}

#[derive(Deserialize)]
struct Passage {
    id: String,
    text: String,
}

const ENTITY_THRESHOLD: f32 = 0.5;

fn labels() -> Vec<(String, String)> {
    [
        (
            "character",
            "A named individual person or being in the story, referred to by a proper name or nickname. Not a title, family role, or common noun.",
        ),
        (
            "faction",
            "A named group, organization, gang, company, or team.",
        ),
        (
            "location",
            "A named place: city, district, building, venue, or region.",
        ),
        (
            "item",
            "A named, specific object, vehicle, weapon, or technology with a proper name.",
        ),
        (
            "concept",
            "A named in-world category, substance, species, power class, or network, such as a drug or a class of superhumans.",
        ),
    ]
    .into_iter()
    .map(|(label, description)| (label.to_owned(), description.to_owned()))
    .collect()
}

fn relation(name: &str, head: &[&str], tail: &[&str], threshold: f32) -> JointRelationSpec {
    JointRelationSpec {
        name: name.into(),
        head: head.iter().map(|value| (*value).to_owned()).collect(),
        tail: tail.iter().map(|value| (*value).to_owned()).collect(),
        threshold,
        candidate_threshold: 0.05,
        allow_self: false,
        max_per_head: None,
        max_per_tail: None,
    }
}

fn joint_schema(threshold: f32) -> JointSchemaSpec {
    let entity = |name: &str| JointEntitySpec {
        name: name.into(),
        threshold: ENTITY_THRESHOLD,
        candidate_threshold: 0.05,
        allow_nested: false,
    };
    JointSchemaSpec {
        entities: ["character", "faction", "location", "item", "concept"]
            .into_iter()
            .map(entity)
            .collect(),
        relations: vec![
            relation("ally_of", &["character"], &["character"], threshold),
            relation("enemy_of", &["character", "faction"], &["character", "faction"], threshold),
            relation("family_of", &["character"], &["character"], threshold),
            relation("member_of", &["character"], &["faction"], threshold),
            relation("leads", &["character"], &["faction"], threshold),
            relation(
                "works_for",
                &["character", "faction"],
                &["character", "faction"],
                threshold,
            ),
            relation(
                "located_in",
                &["character", "faction", "location"],
                &["location"],
                threshold,
            ),
            relation("owns", &["character", "faction"], &["item", "location"], threshold),
        ],
        no_self_loops: true,
    }
}

fn main() -> Result<()> {
    let args = Args::parse();
    gliner25_rs::init("phoenix-gliner25-schema-probe");
    let mut engine = FeatureEngine::new(&args.model, args.threads)?;
    let descriptions = labels();
    let label_names: Vec<String> = descriptions.iter().map(|(label, _)| label.clone()).collect();
    let form = AttributeGroupSpec {
        name: "form".into(),
        labels: vec![
            "proper name".into(),
            "title or role".into(),
            "common noun".into(),
        ],
        applies_to: None,
        multi_label: false,
        threshold: 0.5,
        qualify_labels: true,
    };
    let passages = BufReader::new(File::open(&args.passages)?)
        .lines()
        .map(|line| Ok(serde_json::from_str::<Passage>(&line?)?))
        .collect::<Result<Vec<_>>>()?;
    let mut output = BufWriter::new(File::create(&args.output)?);
    let mut write = |row: serde_json::Value| -> Result<()> {
        serde_json::to_writer(&mut output, &row)?;
        output.write_all(b"\n")?;
        Ok(())
    };
    for passage in &passages {
        let text = passage.text.as_str();

        let started = Instant::now();
        let trace = engine.trace_with_descriptions(
            text,
            &[SchemaTask::Entities(label_names.clone())],
            &[descriptions.clone()],
        )?;
        let mentions =
            engine.decode_mentions(&trace, ENTITY_THRESHOLD, &label_names, OverlapPolicy::Flat);
        write(json!({
            "id": passage.id, "setup": "B1",
            "elapsed_ms": started.elapsed().as_secs_f64() * 1e3,
            "entities": mentions.iter().map(|m| json!({
                "text": m.text, "label": m.field, "score": m.score,
                "start": m.char_start, "end": m.char_end,
            })).collect::<Vec<_>>(),
        }))?;

        let started = Instant::now();
        let attributed = engine
            .extract_attributed_described(
                text,
                &label_names,
                &descriptions,
                std::slice::from_ref(&form),
                ENTITY_THRESHOLD,
            )
            .with_context(|| format!("attributes for {}", passage.id))?;
        write(json!({
            "id": passage.id, "setup": "B2",
            "elapsed_ms": started.elapsed().as_secs_f64() * 1e3,
            "entities": attributed.iter().map(|m| {
                let (form, form_confidence) = match m.attributes.get("form") {
                    Some(AttributeAssignment::Single(value)) => (value.label.clone(), value.confidence),
                    _ => (String::new(), 0.0),
                };
                json!({
                    "text": m.mention.text, "label": m.mention.field, "score": m.mention.score,
                    "start": m.mention.char_start, "end": m.mention.char_end,
                    "form": form, "form_confidence": form_confidence,
                })
            }).collect::<Vec<_>>(),
        }))?;

        for (setup, threshold) in [("C", 0.5_f32), ("C@0.3", 0.3), ("C@0.7", 0.7)] {
            let started = Instant::now();
            let joint = engine
                .extract_joint_described(
                    text,
                    &joint_schema(threshold),
                    &JointConfig::default(),
                    &descriptions,
                )
                .with_context(|| format!("joint for {}", passage.id))?;
            let by_id = joint
                .entities
                .iter()
                .map(|entity| (entity.id.clone(), entity))
                .collect::<std::collections::BTreeMap<_, _>>();
            write(json!({
                "id": passage.id, "setup": setup,
                "elapsed_ms": started.elapsed().as_secs_f64() * 1e3,
                "feasible": joint.feasible,
                "entities": joint.entities.iter().map(|e| json!({
                    "text": e.text, "label": e.entity_type, "score": e.confidence,
                    "start": e.start, "end": e.end,
                })).collect::<Vec<_>>(),
                "relations": joint.relations.iter().map(|r| json!({
                    "type": r.relation_type,
                    "head": by_id.get(&r.head).map(|e| e.text.clone()),
                    "tail": by_id.get(&r.tail).map(|e| e.text.clone()),
                    "confidence": r.confidence,
                })).collect::<Vec<_>>(),
            }))?;
        }
        eprintln!("{} done", passage.id);
    }
    output.flush()?;
    Ok(())
}
