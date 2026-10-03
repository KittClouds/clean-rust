use std::path::PathBuf;

use anyhow::Result;
use clap::Parser;
use gliner25_rs::processor::{SchemaTask, TaskType};
use phoenix_gliner25_eval::features::FeatureEngine;
use serde_json::{Value, json};

#[derive(Parser)]
struct Args {
    #[arg(long)]
    model: PathBuf,
    #[arg(long, default_value_t = 8)]
    threads: usize,
    #[arg(long)]
    output: PathBuf,
}

fn trace_json(engine: &mut FeatureEngine, text: &str, tasks: &[SchemaTask]) -> Result<Value> {
    let trace = engine.trace(text, tasks)?;
    let mapped_tasks: Vec<Value> = trace
        .record
        .tasks
        .iter()
        .map(|task| {
            json!({
                "task": task.task_name,
                "task_type": match task.task_type {
                    TaskType::Entities => "entities",
                    TaskType::Relations => "relations",
                    TaskType::Classifications => "classifications",
                },
                "labels": task.labels,
                "prompt_tok_idx": task.prompt_tok_idx,
                "field_tok_indices": task.field_tok_indices,
            })
        })
        .collect();
    let classifications: Vec<Value> = trace
        .classifications
        .iter()
        .map(|row| {
            json!({
                "task": row.task,
                "labels": row.labels,
                "logits": row.logits,
            })
        })
        .collect();
    Ok(json!({
        "input_ids": trace.record.input_ids,
        "attention_mask": trace.record.attention_mask,
        "tasks": mapped_tasks,
        "word_to_token_maps": trace.record.word_to_token_maps,
        "word_to_char_maps": trace.record.word_to_char_maps,
        "classifications": classifications,
    }))
}

fn main() -> Result<()> {
    let args = Args::parse();
    gliner25_rs::init("phoenix-gliner25-parity-trace");
    let mut engine = FeatureEngine::new(&args.model, args.threads)?;
    let classification = trace_json(
        &mut engine,
        "Delete the temporary archive",
        &[
            SchemaTask::classification(
                "intent",
                vec!["read".into(), "write".into(), "delete".into()],
            ),
            SchemaTask::multi_label_classification(
                "effects",
                vec![
                    "read_only".into(),
                    "create".into(),
                    "modify".into(),
                    "delete".into(),
                ],
            ),
        ],
    )?;
    let joint = trace_json(
        &mut engine,
        "Alice works for Acme in Paris. Bob joined Acme last year.",
        &[
            SchemaTask::Entities(vec![
                "person".into(),
                "organization".into(),
                "location".into(),
            ]),
            SchemaTask::Relations("works_for".into(), vec!["head".into(), "tail".into()]),
            SchemaTask::Relations("located_in".into(), vec!["head".into(), "tail".into()]),
        ],
    )?;
    let joint_tasks = [
        SchemaTask::Entities(vec![
            "person".into(),
            "organization".into(),
            "location".into(),
        ]),
        SchemaTask::Relations("works_for".into(), vec!["head".into(), "tail".into()]),
        SchemaTask::Relations("located_in".into(), vec!["head".into(), "tail".into()]),
    ];
    let joint_raw = engine.trace(
        "Alice works for Acme in Paris. Bob joined Acme last year.",
        &joint_tasks,
    )?;
    let endpoint_spans = [(0, 1), (3, 4), (5, 6), (7, 8), (9, 10)];
    let explicit_logits = engine.explicit_logits(&joint_raw, &[0, 1, 2], &endpoint_spans)?;
    let relation_states = engine.relation_states(&joint_raw, &[(3, 4), (5, 6)])?;
    let relation_pairs = [
        [0, 0, 1, 3, 4],
        [0, 0, 1, 9, 10],
        [0, 7, 8, 3, 4],
        [0, 7, 8, 9, 10],
        [1, 0, 1, 5, 6],
    ];
    let relation_logits =
        engine.relation_logits(&joint_raw, &relation_states, 2, &relation_pairs)?;
    let payload = json!({
        "classification": classification,
        "joint": joint,
        "joint_numeric": {
            "entity_query_order": ["person", "organization", "location"],
            "endpoint_spans": endpoint_spans,
            "explicit_logits_query_major": explicit_logits,
            "relation_pairs": relation_pairs,
            "relation_logits": relation_logits,
        },
    });
    std::fs::write(&args.output, serde_json::to_vec_pretty(&payload)?)?;
    println!("{}", serde_json::to_string_pretty(&payload)?);
    Ok(())
}
