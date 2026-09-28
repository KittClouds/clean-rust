#[allow(dead_code)]
#[path = "../../ar-03b/src/cost.rs"]
mod cost;
#[allow(dead_code)]
#[path = "../../ar-03b/src/features.rs"]
mod features;
#[allow(dead_code)]
#[path = "../../ar-03b/src/integrity.rs"]
mod integrity;
#[allow(dead_code)]
#[path = "../../ar-03b/src/metrics.rs"]
mod metrics;
#[allow(dead_code)]
#[path = "../../ar-03a-r2/src/model.rs"]
mod model;
mod output;
#[allow(dead_code)]
#[path = "../../ar-03a-r2/src/partition.rs"]
mod partition;
mod partition_methods;
#[allow(dead_code)]
mod protocol;
mod records;
mod run;
mod summary;

use std::path::PathBuf;
use std::time::Instant;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let mut arguments = std::env::args_os().skip(1);
    let output_dir = arguments
        .next()
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("artifacts/run-20260921-ar03c1"));
    let r2_artifact_dir = arguments
        .next()
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("../ar-03a-r2/artifacts/run-20260921-r2"));
    let b_artifact_dir = arguments
        .next()
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("../ar-03b/artifacts/run-20260921-ar03b1"));
    if arguments.next().is_some() {
        return Err(
            "usage: adaptive-runtime-ar-03c [OUTPUT_DIR] [R2_ARTIFACT_DIR] [AR03B_ARTIFACT_DIR]"
                .into(),
        );
    }
    run::run(&r2_artifact_dir, &b_artifact_dir, &output_dir)?;
    println!(
        "AR-03C diagnostic complete in {:.2}s; artifacts at {}",
        started.elapsed().as_secs_f64(),
        output_dir.display()
    );
    Ok(())
}
