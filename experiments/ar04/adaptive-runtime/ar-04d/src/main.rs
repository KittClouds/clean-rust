#[allow(dead_code)]
#[path = "../../ar-03d-r1/src/protocol.rs"]
mod frozen_protocol;
#[allow(dead_code)]
#[path = "../../ar-03a-r2/src/model.rs"]
mod model;

mod analysis;
mod experiment;
mod protocol;
mod runtime;

use std::path::PathBuf;
use std::time::Instant;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let output = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("artifacts/run-20260926-ar04d-v1"));
    let report = experiment::run(&output)?;
    println!(
        "AR-04D collection complete: {} crossed cells, {} trajectories, {} decisions, {} master panels, population {}; elapsed {:.1}s; artifacts at {}",
        report.cells,
        report.trajectories,
        report.decisions,
        report.master_panels,
        report.population_size,
        started.elapsed().as_secs_f64(),
        output.display(),
    );
    Ok(())
}
