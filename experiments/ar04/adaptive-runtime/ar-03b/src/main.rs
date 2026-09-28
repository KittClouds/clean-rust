// Frozen R2 modules retain APIs not used by this diagnostic replay.
#[allow(dead_code)]
#[path = "../../ar-03a-r2/src/model.rs"]
mod model;
#[allow(dead_code)]
#[path = "../../ar-03a-r2/src/partition.rs"]
mod partition;

mod cost;
mod features;
mod integrity;
mod metrics;
mod output;
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
        .unwrap_or_else(|| root.join("artifacts/run-20260921-ar03b1"));
    let r2_artifact_dir = arguments
        .next()
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("../ar-03a-r2/artifacts/run-20260921-r2"));
    if arguments.next().is_some() {
        return Err("usage: adaptive-runtime-ar-03b [OUTPUT_DIR] [R2_ARTIFACT_DIR]".into());
    }
    run::run(&r2_artifact_dir, &output_dir)?;
    println!(
        "AR-03B diagnostic complete in {:.2}s; artifacts at {}",
        started.elapsed().as_secs_f64(),
        output_dir.display()
    );
    Ok(())
}
