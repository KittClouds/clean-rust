#[path = "../../../executor/src/collector.rs"]
mod collector;
#[path = "../../../executor/src/graph.rs"]
mod graph;
mod native_collect;
#[path = "../../../executor/src/reach_sim.rs"]
mod reach_sim;
#[path = "../../../executor/src/rng.rs"]
mod rng;
#[path = "../../../executor/src/task.rs"]
mod task;

use anyhow::{Context, Result, ensure};
use std::{env, path::PathBuf};

fn main() -> Result<()> {
    let mut args = env::args_os().skip(1);
    let mode = args.next().context("expected --collect")?;
    ensure!(
        mode.to_string_lossy() == "--collect",
        "only native collection is available"
    );
    let study = PathBuf::from(args.next().context("study root")?);
    let lineage = PathBuf::from(args.next().context("source lineage root")?);
    let task_run = PathBuf::from(args.next().context("frozen task-bank root")?);
    let output = PathBuf::from(args.next().context("empty collection output root")?);
    ensure!(args.next().is_none(), "unexpected trailing arguments");
    native_collect::run(&study, &lineage, &task_run, &output)
}
