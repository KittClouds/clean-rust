use std::path::PathBuf;
use std::time::Instant;

use anyhow::Result;
use clap::Parser;
use gliner25_rs::overlap::OverlapPolicy;
use gliner25_rs::processor::SchemaTask;
use phoenix_gliner25_eval::features::{
    AttributeGroupSpec, ClassificationTaskSpec, ConstraintExpr, FeatureEngine, JointConfig,
    JointEntitySpec, JointRelationSpec, JointSchemaSpec,
};
use serde::Serialize;
use serde_json::{Value, json};

#[derive(Parser)]
struct Args {
    #[arg(long, env = "GLINER25_MODEL")]
    model: PathBuf,
    #[arg(long, default_value_t = 8)]
    threads: usize,
    #[arg(long)]
    output: PathBuf,
}

#[derive(Serialize)]
struct FeatureRow {
    feature: &'static str,
    status: &'static str,
    elapsed_ms: f64,
    value: Value,
}

fn timed<T: Serialize>(
    name: &'static str,
    operation: impl FnOnce() -> Result<T>,
) -> Result<FeatureRow> {
    let started = Instant::now();
    let value = operation()?;
    Ok(FeatureRow {
        feature: name,
        status: "observed",
        elapsed_ms: started.elapsed().as_secs_f64() * 1_000.0,
        value: serde_json::to_value(value)?,
    })
}

fn main() -> Result<()> {
    let args = Args::parse();
    gliner25_rs::init("phoenix-gliner25-five-surface");
    let mut engine = FeatureEngine::new(&args.model, args.threads)?;
    let mut features = Vec::new();

    let filler = (0..900)
        .map(|index| format!("filler{index}"))
        .collect::<Vec<_>>()
        .join(" ");
    let long_text = format!("{filler} OpenAI appointed Sam Altman in San Francisco on Tuesday.");
    features.push(timed("long_context", || {
        engine.extract_entities_long(
            &long_text,
            &[
                "person".into(),
                "organization".into(),
                "location".into(),
                "date".into(),
            ],
            384,
            64,
            0.5,
        )
    })?);

    features.push(timed("unlimited_span_candidate", || {
        let cases = [
            ("The operation was named Recover Every Surviving Archive From The Abandoned Underground Observatory Beneath New Rome Before Dawn.", "operation_name", "The complete formal name of an operation"),
            ("The treaty titled Agreement for the Coordinated Recovery and Preservation of All Cultural Archives Lost During the Fall of New Rome was signed today.", "treaty_title", "The complete formal title of a treaty"),
            ("Witnesses remembered The Night When Every Star Above New Rome Turned Crimson And The Sea Rose Against The City.", "event_name", "The complete formal name of a historical event"),
        ];
        let mut attempts = Vec::new();
        for (text, label, description) in cases {
            let tasks = [SchemaTask::Entities(vec![label.into()])];
            let descriptions = vec![vec![(label.into(), description.into())]];
            let trace = engine.trace_with_descriptions(text, &tasks, &descriptions)?;
            let labels = vec![label.to_owned()];
            let mentions = engine.decode_mentions(&trace, 0.25, &labels, OverlapPolicy::Flat);
            attempts.push(json!({"text": text, "mentions": mentions}));
        }
        Ok(attempts)
    })?);

    features.push(timed("span_attributes", || {
        engine.extract_attributed(
            "The new iPhone camera is excellent, but the battery life is disappointing.",
            &["product".into()],
            &[AttributeGroupSpec {
                name: "sentiment".into(),
                labels: vec!["positive".into(), "negative".into(), "neutral".into()],
                applies_to: Some(vec!["product".into()]),
                multi_label: false,
                threshold: 0.5,
                qualify_labels: true,
            }],
            0.5,
        )
    })?);

    features.push(timed("constrained_classification", || {
        let tasks = vec![
            ClassificationTaskSpec {
                name: "intent".into(),
                labels: vec!["read".into(), "write".into(), "delete".into()],
                multi_label: false,
                min_labels: 1,
                max_labels: Some(1),
                ordered: false,
                threshold: 0.5,
                temperature: 1.0,
                default: None,
            },
            ClassificationTaskSpec {
                name: "effects".into(),
                labels: vec![
                    "read_only".into(),
                    "create".into(),
                    "modify".into(),
                    "delete".into(),
                ],
                multi_label: true,
                min_labels: 1,
                max_labels: None,
                ordered: false,
                threshold: 0.5,
                temperature: 1.0,
                default: None,
            },
        ];
        let label = |task: &str, value: &str| ConstraintExpr::Label {
            task: task.into(),
            label: value.into(),
        };
        engine.classify_constrained(
            "Delete the temporary archive",
            &tasks,
            &[
                ConstraintExpr::Implies {
                    when: Box::new(label("intent", "delete")),
                    then: Box::new(label("effects", "delete")),
                },
                ConstraintExpr::Excludes {
                    left: Box::new(label("intent", "read")),
                    right: Box::new(label("effects", "delete")),
                },
            ],
        )
    })?);

    features.push(timed("joint_information_extraction", || {
        let schema = JointSchemaSpec {
            entities: vec![
                JointEntitySpec {
                    name: "person".into(),
                    threshold: 0.5,
                    candidate_threshold: 0.05,
                    allow_nested: false,
                },
                JointEntitySpec {
                    name: "organization".into(),
                    threshold: 0.5,
                    candidate_threshold: 0.05,
                    allow_nested: false,
                },
                JointEntitySpec {
                    name: "location".into(),
                    threshold: 0.5,
                    candidate_threshold: 0.05,
                    allow_nested: false,
                },
            ],
            relations: vec![
                JointRelationSpec {
                    name: "works_for".into(),
                    head: vec!["person".into()],
                    tail: vec!["organization".into()],
                    threshold: 0.5,
                    candidate_threshold: 0.05,
                    allow_self: false,
                    max_per_head: Some(1),
                    max_per_tail: None,
                },
                JointRelationSpec {
                    name: "located_in".into(),
                    head: vec!["organization".into()],
                    tail: vec!["location".into()],
                    threshold: 0.5,
                    candidate_threshold: 0.05,
                    allow_self: false,
                    max_per_head: None,
                    max_per_tail: None,
                },
            ],
            no_self_loops: true,
        };
        engine.extract_joint(
            "Alice works for Acme in Paris. Bob joined Acme last year.",
            &schema,
            &JointConfig::default(),
        )
    })?);

    let receipt = json!({
        "contract": "phoenix-gliner25-rust-five-surface-v1",
        "model": args.model,
        "graph_publications": 0,
        "features": features,
    });
    if let Some(parent) = args.output.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&args.output, serde_json::to_vec_pretty(&receipt)?)?;
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    Ok(())
}
