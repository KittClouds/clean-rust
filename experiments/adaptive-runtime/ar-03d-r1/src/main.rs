mod experiment;
#[allow(dead_code)]
#[path = "../../ar-03a-r2/src/model.rs"]
mod model;
#[allow(dead_code)]
#[path = "../../ar-03a-r2/src/partition.rs"]
mod partition;
#[allow(dead_code)]
mod protocol;
mod runtime;
mod runtime_partition;

use std::path::PathBuf;
use std::time::Instant;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let output_dir = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("artifacts/run-20260921-ar03dr1-5x5"));
    let report = experiment::run(&output_dir)?;
    println!(
        "AR-03D-R1 paired runtime experiment complete: {} trajectories; elapsed {:.2}s; artifacts at {}",
        report.trajectory_count,
        started.elapsed().as_secs_f64(),
        output_dir.display(),
    );
    Ok(())
}
