mod graph;
mod plasticity;
mod rng;
mod simulation;
mod task;

use anyhow::{Context, Result, ensure};
use graph::Graph;
use rayon::prelude::*;
use serde::Deserialize;
use serde_json::json;
use std::{
    alloc::{GlobalAlloc, Layout, System},
    cell::Cell,
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::Path,
    time::Instant,
};

struct CountingAllocator;
thread_local! { static ALLOCATIONS:Cell<u64>=const{Cell::new(0)}; }
// SAFETY: every allocation is delegated unchanged to the process System allocator.
unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let _ = ALLOCATIONS.try_with(|n| n.set(n.get() + 1));
        unsafe { System.alloc(layout) }
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) }
    }
    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        let _ = ALLOCATIONS.try_with(|n| n.set(n.get() + 1));
        unsafe { System.realloc(ptr, layout, size) }
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        let _ = ALLOCATIONS.try_with(|n| n.set(n.get() + 1));
        unsafe { System.alloc_zeroed(layout) }
    }
}
#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;
pub fn allocations() -> u64 {
    ALLOCATIONS.with(Cell::get)
}

#[derive(Deserialize)]
struct Config {
    seeds: Vec<u64>,
    settings: Vec<Setting>,
    suites: Vec<Suite>,
    trials: usize,
    eta: f32,
    threads: usize,
}
#[derive(Deserialize)]
struct Setting {
    name: String,
    tau: f32,
    glut_sign: f32,
}
#[derive(Deserialize)]
struct Suite {
    name: String,
    side: String,
    cues: usize,
    distractors: usize,
    input_salt: u64,
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(
        args.len() == 5 && args[1] == "run",
        "usage: drosophila-heresy run CONFIG ANATOMY OUTPUT_DIRECTORY"
    );
    let config: Config = serde_json::from_reader(File::open(&args[2])?)?;
    ensure!(
        config.trials >= 32
            && config.trials.is_multiple_of(8)
            && config.threads > 0
            && config.threads <= 8
    );
    let root = Path::new(&args[3]);
    let out = Path::new(&args[4]);
    std::fs::create_dir_all(out)?;
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(config.threads)
        .build()?;
    let start = Instant::now();
    let mut total_rows = 0;
    for suite in &config.suites {
        ensure!(suite.cues >= 2 && suite.cues % 2 == 0 && suite.distractors <= 32);
        for setting in &config.settings {
            ensure!(setting.tau >= 1.0 && setting.glut_sign.abs() == 1.0);
            let graph = Graph::load(root, &suite.side, setting.glut_sign)?;
            let file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(out.join(format!("{}-{}.jsonl", suite.name, setting.name)))?;
            let rows:Result<Vec<_>>=pool.install(||config.seeds.par_iter().map(|&seed|->Result<_>{
                let total_start=Instant::now();
                let (rewired,nulls)=graph.rewire_signal(seed^0x771122);
                let (route,route_receipt)=graph.route.rewired(seed^0x887733);
                ensure!(route_receipt.accepted>0 && route_receipt.retained_fraction<0.95,"degenerate routing control");
                let task_a=task::Task::new(&graph,seed^suite.input_salt,suite.cues,suite.distractors,config.trials);
                let task_c=task::Task::new(&rewired,seed^suite.input_salt,suite.cues,suite.distractors,config.trials);
                let mut results=Vec::new();
                for arm in ["A","B","C","D","E","Z"] {
                    let (g,t)=if arm=="C"||arm=="D"{(&rewired,&task_c)}else{(&graph,&task_a)};
                    let r=if arm=="B"||arm=="D"{&route}else{&g.route};
                    let mut sim=simulation::Simulator::new(g,r,seed,setting.tau,config.eta,arm);
                    let result=sim.run(t);
                    ensure!(result.hot_allocations==0,"hot loop allocated");
                    ensure!(arm!="Z"||result.changed_weights==0,"no-learning control changed weights");
                    results.push(json!({"suite":suite.name,"side":suite.side,"setting":setting.name,"tau":setting.tau,
                        "glut_sign":setting.glut_sign,"seed":seed,"arm":arm,"outcome":result}));
                }
                Ok(json!({"seed":seed,"null_signal":nulls,"null_routing":route_receipt,
                    "nodes":{"pn":graph.pn_kc.n_pre,"kc":graph.kc_mb.n_pre,"mbon":graph.kc_mb.n_post,"dan":graph.route.n_pre},
                    "plastic_edges":graph.kc_mb.edges.len(),"route_edges":graph.route.edges.len(),"nt_uncertain_mbons":graph.nt_uncertain,
                    "motifs_anatomical":graph.routing_motifs(&graph.route),"motifs_route_null":graph.routing_motifs(&route),
                    "setup_and_execution_seconds":total_start.elapsed().as_secs_f64(),"results":results}))
            }).collect());
            let rows = rows?;
            let mut writer = BufWriter::new(file);
            for row in rows {
                serde_json::to_writer(&mut writer, &row)?;
                writer.write_all(b"\n")?;
                total_rows += 6;
            }
            writer.flush()?;
            println!(
                "completed {} {}: {} paired seeds, {} arm outcomes",
                suite.name,
                setting.name,
                config.seeds.len(),
                config.seeds.len() * 6
            );
        }
    }
    let receipt = json!({"complete":true,"outcome_rows":total_rows,"wall_seconds":start.elapsed().as_secs_f64(),
        "threads":config.threads,"config":args[2],"autodiff":false,"learning_rule_search":false});
    let f = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(out.join("execution.json"))
        .context("write receipt")?;
    serde_json::to_writer_pretty(f, &receipt)?;
    println!("{receipt}");
    Ok(())
}
