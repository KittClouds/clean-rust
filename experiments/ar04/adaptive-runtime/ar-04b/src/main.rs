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
mod stategen;

use std::path::PathBuf;
use std::time::Instant;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let output = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("artifacts/run-20260921-ar04b-v1"));
    let report = experiment::run(&output)?;
    println!(
        "AR-04B diagnostic complete: {} states, {} candidate actions, {} sentinel score rows; elapsed {:.2}s; artifacts at {}",
        report.states,
        report.actions,
        report.sentinel_rows,
        started.elapsed().as_secs_f64(),
        output.display(),
    );
    Ok(())
}
