mod allocation;
#[cfg(test)]
mod baseline;
mod graph;
mod observer;
mod plasticity;
mod rng;
mod simulation;
mod task;
pub use allocation::allocations;
use anyhow::{Result, ensure};
use graph::Graph;
use rayon::prelude::*;
use serde::Deserialize;
use serde_json::json;
use simulation::{Dh03Condition, Simulator};
use std::{
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::Path,
    time::Instant,
};

#[derive(Deserialize)]
struct Config {
    observe: Option<bool>,
    seeds: Vec<u64>,
    taus: Vec<f32>,
    sides: Vec<String>,
    conditions: Vec<Dh03Condition>,
    arms: Vec<String>,
    cues: usize,
    delay_steps: usize,
    trials: usize,
    eta: f32,
    glut_sign: f32,
    input_salt: u64,
    threads: usize,
}
fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(
        args.len() == 5 && args[1] == "run",
        "usage: drosophila-heresy-dh03 run CONFIG ANATOMY OUTPUT"
    );
    let c: Config = serde_json::from_reader(File::open(&args[2])?)?;
    ensure!(
        c.trials >= 32 && c.trials.is_multiple_of(8) && c.cues >= 2 && c.cues.is_multiple_of(2)
    );
    ensure!(c.delay_steps <= 32 && c.threads > 0 && c.threads <= 8 && c.glut_sign.abs() == 1.0);
    ensure!(
        c.arms == ["E", "Z"]
            && c.conditions
                == [
                    Dh03Condition::Immediate,
                    Dh03Condition::Quiet,
                    Dh03Condition::RetainBoth,
                    Dh03Condition::SuppressEligibility,
                    Dh03Condition::RestoreState,
                    Dh03Condition::SuppressBoth,
                ]
            && !c.seeds.is_empty()
    );
    let out = Path::new(&args[4]);
    std::fs::create_dir_all(out)?;
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(c.threads)
        .build()?;
    let start = Instant::now();
    let mut count = 0;
    for side in &c.sides {
        for &tau in &c.taus {
            ensure!(tau >= 1.0);
            let graph = Graph::load(Path::new(&args[3]), side, c.glut_sign)?;
            let file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(out.join(format!("{side}-tau{tau}.jsonl")))?;
            let rows:Result<Vec<_>>=pool.install(||c.seeds.par_iter().map(|&seed|->Result<_>{
            let setup=Instant::now();let (route,receipt)=graph.route.rewired(seed^0x887733);
            ensure!(receipt.accepted>0 && receipt.retained_fraction<0.95 && receipt.degree_preserved);
            let task=task::Task::new(&graph,seed^c.input_salt,c.cues,c.delay_steps,c.trials);
            ensure!(task.unique_cue_codes()==c.cues);
            let mut results=Vec::new();
            for &condition in &c.conditions {for arm in &c.arms {
                let mut sim=Simulator::new(&graph,&graph.route,seed,tau,c.eta,arm);
                let result=sim.run_dh03(&task,condition,&route,c.observe.unwrap_or(true));
                ensure!(result.outcome.hot_allocations==0);
                ensure!(arm!="Z"||result.outcome.changed_weights==0);
                results.push(json!({"seed":seed,"side":side,"tau":tau,"condition":condition,"arm":arm,"result":result}));
            }}
            Ok(json!({"seed":seed,"null_routing":receipt,"motifs_anatomical":graph.routing_motifs(&graph.route),
                "nt_uncertain_mbons":graph.nt_uncertain,"plastic_edges":graph.kc_mb.edges.len(),
                "setup_and_execution_seconds":setup.elapsed().as_secs_f64(),"results":results}))
        }).collect());
            let mut writer = BufWriter::new(file);
            for row in rows? {
                serde_json::to_writer(&mut writer, &row)?;
                writer.write_all(b"\n")?;
                count += c.conditions.len() * c.arms.len();
            }
            writer.flush()?;
            println!("completed {side} tau={tau}: {} paired seeds", c.seeds.len());
        }
    }
    let receipt = json!({"complete":true,"protocol":"DH-03","outcome_rows":count,"wall_seconds":start.elapsed().as_secs_f64(),"threads":c.threads,
        "config":args[2],"observer_feeds_learner":false,"intervention_factors":["interval_eligibility","interval_state"],
        "all_factorial_cells_process_same_distractors":true,"autodiff":false,"learning_rule_search":false});
    serde_json::to_writer_pretty(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(out.join("execution.json"))?,
        &receipt,
    )?;
    println!("{receipt}");
    Ok(())
}
