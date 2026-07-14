use phoenix_graph_research::{
    evaluate_hyper_encoder_pair, stage_hyper_encoder, ExternalDatasetMapped,
    HyperRelationalCandidatePolicy, HyperRelationalTaskMapped,
};
use serde::Serialize;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Report<'a> {
    schema_version: &'static str,
    source_dataset_id: &'a str,
    task_id: &'a str,
    seed: u64,
    stage_micros: u64,
    pair_evaluation_micros: u64,
    staging: &'a phoenix_graph_research::HyperEncoderStagingProfile,
    pair: &'a phoenix_graph_research::HyperEncoderPairResult,
    test_partition_accessed: bool,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = std::env::args_os().skip(1);
    let source_manifest = PathBuf::from(arguments.next().ok_or("source manifest")?);
    let task_manifest = PathBuf::from(arguments.next().ok_or("task manifest")?);
    let output = PathBuf::from(arguments.next().ok_or("output report")?);
    if arguments.next().is_some() {
        return Err("usage: hyper_encoder_pair SOURCE TASK OUTPUT".into());
    }
    let source = ExternalDatasetMapped::open(source_manifest)?;
    let task = HyperRelationalTaskMapped::open(task_manifest, &source)?;
    let staged_started = Instant::now();
    let staged = stage_hyper_encoder(&source, &task)?;
    let stage_micros = micros(staged_started.elapsed());
    let seed = 0x51a7_e001_u64;
    let evaluation_started = Instant::now();
    let pair = evaluate_hyper_encoder_pair(
        &source,
        &task,
        &staged,
        seed,
        HyperRelationalCandidatePolicy::FullEntity,
    )?;
    let report = Report {
        schema_version: "phoenix-stare-compgcn-paired-validation/v1",
        source_dataset_id: source.manifest().dataset_id.as_str(),
        task_id: task.manifest().task_id.as_str(),
        seed,
        stage_micros,
        pair_evaluation_micros: micros(evaluation_started.elapsed()),
        staging: &staged.profile,
        pair: &pair,
        test_partition_accessed: false,
    };
    let bytes = serde_json::to_vec_pretty(&report)?;
    if let Some(parent) = output.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&output, &bytes)?;
    println!("{}", String::from_utf8(bytes)?);
    Ok(())
}

fn micros(duration: std::time::Duration) -> u64 {
    duration.as_micros().try_into().unwrap_or(u64::MAX)
}
