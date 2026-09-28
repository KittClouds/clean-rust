use crate::{
    capture::Capture,
    graph::Graph,
    policy::Policy,
    simulation::{Dh07Condition, Simulator},
    task::Task,
};
use anyhow::{Result, ensure};
use rayon::prelude::*;
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    fs::{File, OpenOptions},
    io::{BufWriter, Read, Write},
    path::Path,
    time::Instant,
};

#[derive(Deserialize)]
struct Config {
    observe: bool,
    seeds: Vec<u64>,
    taus: Vec<f32>,
    sides: Vec<String>,
    conditions: Vec<Dh07Condition>,
    arms: Vec<String>,
    cues: usize,
    delay_steps: usize,
    trials: usize,
    eta: f32,
    glut_sign: f32,
    input_salt: u64,
    threads: usize,
}

fn weight_hash(weights: &[f32]) -> String {
    let mut hash = Sha256::new();
    for w in weights {
        hash.update(w.to_bits().to_le_bytes());
    }
    format!("{:x}", hash.finalize())
}
fn is_null(c: Dh07Condition) -> bool {
    matches!(
        c,
        Dh07Condition::NullPerpendicular | Dh07Condition::ParallelNull
    )
}

fn file_hash(path: &Path) -> Result<String> {
    let mut file = File::open(path)?;
    let mut hash = Sha256::new();
    let mut buffer = [0_u8; 65_536];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hash.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hash.finalize()))
}

fn authorize_measured_run(config_path: &Path, anatomy_path: &Path, out: &Path) -> Result<()> {
    let executable = std::fs::canonicalize(std::env::current_exe()?)?;
    let sealed = executable
        .parent()
        .ok_or_else(|| anyhow::anyhow!("executable has no parent"))?;
    ensure!(
        sealed.file_name().is_some_and(|name| name == "sealed"),
        "measured execution requires the frozen executable"
    );
    let run_root = sealed
        .parent()
        .ok_or_else(|| anyhow::anyhow!("sealed directory has no run root"))?;
    let authorized_root =
        std::fs::canonicalize(Path::new(env!("CARGO_MANIFEST_DIR")).join("artifacts/runs"))?;
    ensure!(
        run_root.parent() == Some(authorized_root.as_path()),
        "measured execution is outside the repository run authority"
    );
    ensure!(
        std::fs::canonicalize(config_path)? == sealed.join("config.json"),
        "measured config is not the sealed config"
    );
    ensure!(
        std::fs::canonicalize(anatomy_path)? == sealed.join("anatomy"),
        "measured anatomy is not the sealed anatomy"
    );
    ensure!(
        std::fs::canonicalize(out)? == run_root,
        "measured output is not the frozen run root"
    );
    let seal_path = run_root.join("seal.json");
    let seal: Value = serde_json::from_reader(File::open(&seal_path)?)?;
    ensure!(
        seal["protocol"] == "DH-07R"
            && seal["before_task_execution"] == true
            && seal["status_at_seal"] == "FROZEN_UNOPENED",
        "invalid measured-run seal"
    );
    let fingerprints = seal["fingerprints"]
        .as_object()
        .ok_or_else(|| anyhow::anyhow!("seal fingerprints missing"))?;
    let executable_name = executable
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| anyhow::anyhow!("non-Unicode executable name"))?;
    ensure!(
        fingerprints.get(executable_name).and_then(Value::as_str)
            == Some(file_hash(&executable)?.as_str()),
        "frozen executable hash differs from seal"
    );
    ensure!(
        fingerprints.get("config.json").and_then(Value::as_str)
            == Some(file_hash(config_path)?.as_str()),
        "frozen config hash differs from seal"
    );
    let mut anatomy_files = 0_usize;
    for entry in std::fs::read_dir(anatomy_path)? {
        let path = entry?.path();
        if !path.is_file() {
            continue;
        }
        anatomy_files += 1;
        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or_else(|| anyhow::anyhow!("non-Unicode anatomy filename"))?;
        let windows_key = format!("anatomy\\{name}");
        let slash_key = format!("anatomy/{name}");
        let expected = fingerprints
            .get(&windows_key)
            .or_else(|| fingerprints.get(&slash_key))
            .and_then(Value::as_str);
        ensure!(
            expected == Some(file_hash(&path)?.as_str()),
            "anatomy hash differs from seal: {name}"
        );
    }
    let sealed_anatomy_files = fingerprints
        .keys()
        .filter(|key| key.starts_with("anatomy\\") || key.starts_with("anatomy/"))
        .count();
    ensure!(
        anatomy_files == sealed_anatomy_files,
        "anatomy manifest membership differs from seal"
    );
    let global_marker = authorized_root.join("DH07R_MEASURED_SEEDS_OPENED.json");
    let mut global = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(global_marker)?;
    serde_json::to_writer_pretty(
        &mut global,
        &json!({
            "protocol":"DH-07R", "measured_seeds_opened":true,
            "seed_range":"7000..7031", "run_root":run_root,
            "relaunch_forbidden":true
        }),
    )?;
    global.write_all(b"\n")?;
    global.flush()?;
    let marker = run_root.join("MEASURED_SEEDS_OPENED.json");
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(marker)?;
    serde_json::to_writer_pretty(
        &mut file,
        &json!({
            "protocol":"DH-07R", "measured_seeds_opened":true,
            "seed_range":"7000..7031", "relaunch_forbidden":true
        }),
    )?;
    file.write_all(b"\n")?;
    file.flush()?;
    Ok(())
}

pub fn main() -> Result<()> {
    let args = std::env::args().collect::<Vec<_>>();
    ensure!(
        args.len() == 5 && (args[1] == "run" || args[1] == "qualify"),
        "usage: drosophila-heresy-dh07r <run|qualify> CONFIG ANATOMY OUTPUT"
    );
    let mode = &args[1];
    let config: Config = serde_json::from_reader(File::open(&args[2])?)?;
    if mode == "run" {
        ensure!(config.observe && config.seeds == (7000..7032).collect::<Vec<_>>());
        ensure!(
            config.taus == [4., 16.] && config.sides == ["R", "L"] && config.arms == ["E", "Z"]
        );
        ensure!(config.threads == 4);
    } else {
        let qualification = (9006..9011).collect::<BTreeSet<_>>();
        ensure!(
            !config.seeds.is_empty()
                && config.seeds.len() <= 2
                && config.seeds.iter().all(|s| qualification.contains(s))
        );
        ensure!(!config.taus.is_empty() && config.taus.iter().all(|tau| *tau == 4. || *tau == 16.));
        ensure!(!config.sides.is_empty() && config.sides.iter().all(|s| s == "R" || s == "L"));
        ensure!(config.arms == ["E", "Z"] && config.threads == 1);
    }
    ensure!(
        config.conditions
            == [
                Dh07Condition::Immediate,
                Dh07Condition::Quiet,
                Dh07Condition::Neither,
                Dh07Condition::ParallelOnly,
                Dh07Condition::TruePerpendicular,
                Dh07Condition::NullPerpendicular,
                Dh07Condition::BothTrue,
                Dh07Condition::ParallelNull
            ]
    );
    ensure!(config.trials == 512 && config.cues == 16 && config.delay_steps == 12);
    ensure!(config.glut_sign == -1. && config.eta == 0.05);
    let out = Path::new(&args[4]);
    if mode == "run" {
        authorize_measured_run(Path::new(&args[2]), Path::new(&args[3]), out)?;
    } else {
        std::fs::create_dir_all(out)?;
    }
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(config.threads)
        .build()?;
    let started = Instant::now();
    let mut total = 0;
    for side in &config.sides {
        for &tau in &config.taus {
            let graph = Graph::load(Path::new(&args[3]), side, config.glut_sign)?;
            let rows:Result<Vec<_>>=pool.install(||config.seeds.par_iter().map(|&seed|->Result<Value>{
            let setup=Instant::now();let (shuffled,rewire)=graph.route.rewired(seed^0x887733);
            ensure!(rewire.accepted>0&&rewire.degree_preserved);
            let task=Task::new(&graph,seed^config.input_salt,config.cues,config.delay_steps,config.trials);
            let mut results=Vec::with_capacity(config.conditions.len()*config.arms.len());
            for arm in &config.arms {for &condition in &config.conditions {
                let mut sim=Simulator::new(&graph,&graph.route,seed,tau,config.eta,arm);
                if arm=="E"&&is_null(condition) {
                    sim.capture=Some(Capture::new(sim.weights.len()));
                    sim.policy=Some(Policy::new(sim.weights.len(),seed,tau,side.as_bytes()[0]));
                }
                let run=sim.run_dh07(&task,condition,&shuffled,config.observe,0)?;
                ensure!(run.result.outcome.hot_allocations==0);
                ensure!(arm!="Z"||run.result.outcome.changed_weights==0);
                let manipulation=if let Some(policy)=sim.policy.take() {
                    ensure!(!policy.failed&&policy.audits.len()==256);
                    json!({"status":"PASSED","events":policy.audits})
                } else {json!({"status":"NOT_APPLICABLE","events":[]})};
                results.push(json!({"seed":seed,"side":side,"tau":tau,"arm":arm,"condition":condition,
                    "final_weight_sha256":weight_hash(&sim.weights),"manipulation":manipulation,"result":run.result}));
            }}
            Ok(json!({"seed":seed,"side":side,"tau":tau,"plastic_edges":graph.kc_mb.edges.len(),
                "null_routing":rewire,"setup_seconds":setup.elapsed().as_secs_f64(),"results":results}))
        }).collect());
            let file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(out.join(format!("{side}-tau{tau}.jsonl")))?;
            let mut writer = BufWriter::new(file);
            for row in rows? {
                serde_json::to_writer(&mut writer, &row)?;
                writer.write_all(b"\n")?;
                total += 16;
            }
            writer.flush()?;
            println!("completed {side} tau={tau}");
        }
    }
    let receipt = json!({"protocol":"DH-07R","mode":mode,"complete":true,"outcome_rows":total,
        "fresh_seed_bundles":if mode=="run" {config.seeds.len()} else {0},
        "qualification_seed_bundles":if mode=="qualify" {config.seeds.len()} else {0},
        "specimens":1,"wall_seconds":started.elapsed().as_secs_f64(),"configured_seeds":config.seeds,
        "reward_rule":"action_contingent","shared":"exogenous task streams and simulator RNG",
        "intervention":"adaptive feasible residual direction replacement","autodiff":false,"backprop":false});
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(out.join("execution.json"))?;
    serde_json::to_writer_pretty(&mut file, &receipt)?;
    file.write_all(b"\n")?;
    println!("{receipt}");
    Ok(())
}
