#[allow(dead_code)]
#[path = "../../ar-03d-r1/src/protocol.rs"]
mod frozen_protocol;
#[allow(dead_code)]
#[path = "../../ar-03a-r2/src/model.rs"]
mod model;
#[allow(dead_code)]
#[path = "../../ar-03a-r2/src/partition.rs"]
mod partition;
#[allow(dead_code)]
#[path = "../../ar-03d-r1/src/runtime_partition.rs"]
mod runtime_partition;

mod analysis;
mod experiment;
mod protocol;

use std::path::PathBuf;
use std::time::Instant;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let output_dir = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("artifacts/run-20260921-ar04a-cv1"));
    let report = experiment::run(&output_dir)?;
    println!(
        "AR-04A diagnostic complete: {} frozen states, {} candidate actions, {} valid action-continuation pairs; elapsed {:.2}s; artifacts at {}",
        report.state_count,
        report.action_count,
        report.valid_action_continuation_pairs,
        started.elapsed().as_secs_f64(),
        output_dir.display(),
    );
    Ok(())
}
