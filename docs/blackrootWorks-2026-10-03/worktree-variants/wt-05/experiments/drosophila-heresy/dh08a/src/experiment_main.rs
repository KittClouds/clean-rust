use crate::{
    capture::Capture,
    graph::Graph,
    policy::Policy,
    simulation::{Dh07Condition, Simulator},
    task::Task,
};
use anyhow::{ensure, Result};
use rayon::prelude::*;
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    fs::{File, OpenOptions},
    io::{BufWriter, Read, Write},
    path::Path,
    time::Instant,
};

const PROTOCOL: &str = "DH-08A";
const GLOBAL_MARKER: &str = "DH08A_MEASURED_SEEDS_OPENED.json";

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
    for weight in weights {
        hash.update(weight.to_bits().to_le_bytes());
    }
    format!("{:x}", hash.finalize())
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
        seal["protocol"] == PROTOCOL
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

    let global_marker = authorized_root.join(GLOBAL_MARKER);
    let mut global = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(global_marker)?;
    serde_json::to_writer_pretty(
        &mut global,
        &json!({
            "protocol":PROTOCOL,
            "measured_seeds_opened":true,
            "seed_range":"8000..8031",
            "run_root":run_root,
            "relaunch_forbidden":true
        }),
    )?;
    global.write_all(b"\n")?;
    global.flush()?;

    let mut marker = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(run_root.join("MEASURED_SEEDS_OPENED.json"))?;
    serde_json::to_writer_pretty(
        &mut marker,
        &json!({
            "protocol":PROTOCOL,
            "measured_seeds_opened":true,
            "seed_range":"8000..8031",
            "relaunch_forbidden":true
        }),
    )?;
    marker.write_all(b"\n")?;
    marker.flush()?;
    Ok(())
}

fn validate_config(mode: &str, config: &Config) -> Result<()> {
    ensure!(config.conditions == [Dh07Condition::TruePerpendicular]);
    ensure!(config.taus == [4.0, 16.0]);
    ensure!(config.sides == ["R", "L"]);
    ensure!(config.arms == ["E", "Z"]);
    ensure!(config.trials == 512 && config.cues == 16 && config.delay_steps == 12);
    ensure!(config.glut_sign == -1.0 && config.eta == 0.05);
    match mode {
        "run" => {
            ensure!(config.observe);
            ensure!(config.seeds == (8000..8032).collect::<Vec<_>>());
            ensure!(config.threads == 4);
        }
        "qualify" => {
            let reserved = (9100..9106).collect::<BTreeSet<_>>();
            ensure!(!config.seeds.is_empty() && config.seeds.len() <= 6);
            ensure!(config.seeds.iter().all(|seed| reserved.contains(seed)));
            ensure!(config.threads == 1);
        }
        _ => anyhow::bail!("unsupported execution mode"),
    }
    Ok(())
}

pub fn main() -> Result<()> {
    let args = std::env::args().collect::<Vec<_>>();
    ensure!(
        args.len() == 5 && (args[1] == "run" || args[1] == "qualify"),
        "usage: drosophila-heresy-dh08a <run|qualify> CONFIG ANATOMY OUTPUT"
    );
    let mode = &args[1];
    let config: Config = serde_json::from_reader(File::open(&args[2])?)?;
    validate_config(mode, &config)?;
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
    let mut total = 0_usize;
    for side in &config.sides {
        for &tau in &config.taus {
            let graph = Graph::load(Path::new(&args[3]), side, config.glut_sign)?;
            let rows: Result<Vec<_>> = pool.install(|| {
                config
                    .seeds
                    .par_iter()
                    .map(|&seed| -> Result<Value> {
                        let setup = Instant::now();
                        let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733);
                        ensure!(rewire.accepted > 0 && rewire.degree_preserved);
                        let task = Task::new(
                            &graph,
                            seed ^ config.input_salt,
                            config.cues,
                            config.delay_steps,
                            config.trials,
                        );
                        let mut results = Vec::with_capacity(config.arms.len());
                        for arm in &config.arms {
                            let mut sim = Simulator::new(
                                &graph,
                                &graph.route,
                                seed,
                                tau,
                                config.eta,
                                arm,
                            );
                            if arm == "E" {
                                sim.capture = Some(Capture::new(sim.weights.len()));
                                sim.policy = Some(Policy::new(
                                    sim.weights.len(),
                                    seed,
                                    tau,
                                    side.as_bytes()[0],
                                ));
                            }
                            let run = sim.run_dh07(
                                &task,
                                Dh07Condition::TruePerpendicular,
                                &shuffled,
                                config.observe,
                                0,
                            )?;
                            ensure!(run.result.outcome.hot_allocations == 0);
                            ensure!(arm != "Z" || run.result.outcome.changed_weights == 0);
                            let shadow = if let Some(policy) = sim.policy.take() {
                                ensure!(!policy.failed, "shadow geometry gate failed");
                                ensure!(policy.events.len() == 256, "shadow event count differs");
                                json!({"status":"PASSED","events":policy.events})
                            } else {
                                json!({"status":"FIXED_WEIGHT_CONTROL","events":[]})
                            };
                            results.push(json!({
                                "seed":seed,
                                "side":side,
                                "tau":tau,
                                "arm":arm,
                                "condition":Dh07Condition::TruePerpendicular,
                                "final_weight_sha256":weight_hash(&sim.weights),
                                "shadow":shadow,
                                "canonical":run.result
                            }));
                        }
                        Ok(json!({
                            "seed":seed,
                            "side":side,
                            "tau":tau,
                            "plastic_edges":graph.kc_mb.edges.len(),
                            "null_routing":rewire,
                            "setup_seconds":setup.elapsed().as_secs_f64(),
                            "results":results
                        }))
                    })
                    .collect()
            });
            let file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(out.join(format!("{side}-tau{tau}.jsonl")))?;
            let mut writer = BufWriter::new(file);
            for row in rows? {
                serde_json::to_writer(&mut writer, &row)?;
                writer.write_all(b"\n")?;
                total += config.arms.len();
            }
            writer.flush()?;
            println!("completed {side} tau={tau}");
        }
    }

    let receipt = json!({
        "protocol":PROTOCOL,
        "mode":mode,
        "complete":true,
        "outcome_rows":total,
        "fresh_seed_bundles":if mode=="run" {config.seeds.len()} else {0},
        "qualification_seed_bundles":if mode=="qualify" {config.seeds.len()} else {0},
        "configured_seeds":config.seeds,
        "specimens":1,
        "wall_seconds":started.elapsed().as_secs_f64(),
        "canonical_policy":"parallel-off true-perpendicular",
        "shadow":"event-local Q07 feasible-null endpoint; never committed",
        "reward_rule":"action_contingent",
        "autodiff":false,
        "backprop":false
    });
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(out.join("execution.json"))?;
    serde_json::to_writer_pretty(&mut file, &receipt)?;
    file.write_all(b"\n")?;
    println!("{receipt}");
    Ok(())
}
