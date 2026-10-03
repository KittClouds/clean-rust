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
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::Path,
    time::Instant,
};

const PROTOCOL: &str = "Q08-ReadoutNull-v1";

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

fn validate_config(mode: &str, config: &Config) -> Result<()> {
    ensure!(config.conditions == [Dh07Condition::TruePerpendicular]);
    ensure!(config.taus == [4.0]);
    ensure!(config.sides == ["R", "L"]);
    ensure!(config.arms == ["E", "Z"]);
    ensure!(config.trials == 512 && config.cues == 16 && config.delay_steps == 12);
    ensure!(config.glut_sign == -1.0 && config.eta == 0.05);
    ensure!(
        mode == "smoke",
        "only one-seed smoke is enabled pending review"
    );
    ensure!(
        config.seeds == [9200],
        "only qualification seed 9200 is enabled"
    );
    ensure!(config.threads == 1 && config.observe);
    Ok(())
}

pub fn main() -> Result<()> {
    let args = std::env::args().collect::<Vec<_>>();
    ensure!(
        args.len() == 5 && args[1] == "smoke",
        "usage: q08-readout-null-v1 <smoke> CONFIG ANATOMY OUTPUT"
    );
    let mode = &args[1];
    let config: Config = serde_json::from_reader(File::open(&args[2])?)?;
    validate_config(mode, &config)?;
    let out = Path::new(&args[4]);
    std::fs::create_dir_all(out)?;

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
                            if let Some(policy) = &mut sim.policy { policy.rotor.set_posts(graph.kc_mb.edges.iter().map(|e|e.post as usize)); }
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

                                ensure!(policy.events.len() == 256, "shadow event count differs");
                                json!({"status":if policy.failed {"CONSTRUCTOR_FAILED"}else{"PASSED"},"events":policy.events})
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
        "fresh_seed_bundles":0,
        "qualification_seed_bundles":config.seeds.len(),
        "configured_seeds":config.seeds,
        "specimens":1,
        "wall_seconds":started.elapsed().as_secs_f64(),
        "canonical_policy":"parallel-off true-perpendicular",
        "shadow":"event-local readout-null endpoint; never committed",
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

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn execution_firewall_accepts_only_the_authorized_one_seed_smoke() {
        let mut config: Config =
            serde_json::from_str(include_str!("../smoke-config.json")).unwrap();
        assert!(validate_config("smoke", &config).is_ok());
        for mode in ["run", "qualify", "measured", "full"] {
            assert!(validate_config(mode, &config).is_err());
        }
        for seed in [9201, 9205, 7000, 8000, 9100, 0] {
            config.seeds = vec![seed];
            assert!(validate_config("smoke", &config).is_err());
        }
        config.seeds = (9200..9206).collect();
        assert!(validate_config("smoke", &config).is_err());
    }
}
