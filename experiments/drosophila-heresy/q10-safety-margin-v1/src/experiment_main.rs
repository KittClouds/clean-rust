//! Qualification-only Stage A/B; no measured mode, no alternative endpoint.
use crate::{
    capture::Capture,
    graph::Graph,
    linear::{self, DriveOperator},
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
    path::{Path, PathBuf},
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
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
fn validate_config(mode: &str, c: &Config) -> Result<usize> {
    ensure!(
        mode == "stage-a" || mode == "stage-b",
        "only stage-a/stage-b qualification is implemented; measured execution forbidden"
    );
    let expected_seeds = if mode == "stage-a" {
        &[9201][..]
    } else {
        &[9202, 9203, 9204, 9205][..]
    };
    ensure!(
        c.seeds == expected_seeds,
        "seed set is not authorized for stage"
    );
    ensure!(c.taus == [4., 16.] && c.sides == ["R", "L"]);
    ensure!(c.conditions == [Dh07Condition::TruePerpendicular] && c.arms == ["E", "Z"]);
    ensure!(c.observe && c.threads == 8);
    ensure!(c.cues == 16 && c.delay_steps == 12 && c.trials == 512);
    ensure!(c.eta == 0.05 && c.glut_sign == -1. && c.input_salt == 858980352);
    Ok(1024 * c.seeds.len())
}
fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn weight_hash(weights: &[f32]) -> String {
    let mut hash = Sha256::new();
    for x in weights {
        hash.update(x.to_bits().to_le_bytes());
    }
    format!("{:x}", hash.finalize())
}
fn write_json(path: &Path, value: &impl serde::Serialize) -> Result<()> {
    let mut w = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(path)?);
    serde_json::to_writer_pretty(&mut w, value)?;
    w.write_all(b"\n")?;
    w.flush()?;
    Ok(())
}
fn source_manifest(root: &Path) -> Result<Vec<Value>> {
    fn visit(root: &Path, dir: &Path, out: &mut Vec<PathBuf>) -> Result<()> {
        for entry in std::fs::read_dir(dir)? {
            let p = entry?.path();
            if p.is_dir() {
                visit(root, &p, out)?;
            } else if p.extension().is_some_and(|x| x == "rs") {
                out.push(p.strip_prefix(root)?.to_owned());
            }
        }
        Ok(())
    }
    let mut paths = vec![
        PathBuf::from("Cargo.toml"),
        PathBuf::from("Cargo.lock"),
        PathBuf::from("PLAN.md"),
        PathBuf::from("CONTRACT.json"),
    ];
    visit(root, &root.join("src"), &mut paths)?;
    paths.sort();
    paths
        .iter()
        .map(|p| Ok(json!({"path":p,"sha256":hash_bytes(&std::fs::read(root.join(p))?)})))
        .collect()
}
fn canonical_hash<T: serde::Serialize>(run: &T) -> Result<String> {
    let mut value = serde_json::to_value(run)?;
    // Timing and observer capacity are implementation diagnostics, not replay state.
    value["outcome"]["seconds"] = Value::Null;
    value["diagnostics"] = Value::Null;
    value["observer_array_bytes"] = Value::Null;
    Ok(hash_bytes(&serde_json::to_vec(&value)?))
}
pub fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(
        args.len() == 5 && (args[1] == "stage-a" || args[1] == "stage-b"),
        "usage: q09-lfa stage-a|stage-b CONFIG ANATOMY OUTPUT; no other execution mode"
    );
    let config: Config = serde_json::from_reader(File::open(&args[2])?)?;
    let expected_total = validate_config(&args[1], &config)?;
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let contract: Value = serde_json::from_reader(File::open(root.join("CONTRACT.json"))?)?;
    ensure!(contract["protocol"] == "Q09-LFA");
    let plan_hash = hash_bytes(&std::fs::read(root.join("PLAN.md"))?);
    ensure!(
        contract["plan_sha256"]
            .as_str()
            .is_some_and(|h| h.eq_ignore_ascii_case(&plan_hash)),
        "frozen PLAN hash mismatch"
    );
    // Count discrepancy in current parent contract must be corrected/re-frozen by parent.
    // Never silently expand or change the frozen 256-event canonical task.
    ensure!(
        contract["expected_stage_a_states"] == 1024
            && contract["reversal_states_per_side_tau"] == 256,
        "contract count conflict: frozen task has 256 reversal events per slice/tau, 1024 Stage A total"
    );
    ensure!(
        contract["rank_cutoff"] == "sigma_i > sigma_max * max(rows, cols) * f64::EPSILON * 1000"
    );
    let audit_pool = rayon::ThreadPoolBuilder::new()
        .num_threads(config.threads)
        .build()?;
    let out = Path::new(&args[4]);
    std::fs::create_dir_all(out)?;
    let executable = std::env::current_exe()?;
    write_json(
        &out.join("pre-execution.json"),
        &json!({
            "protocol":"Q09-LFA","schema_version":1,"source":source_manifest(root)?,
            "executable":executable,"executable_sha256":hash_bytes(&std::fs::read(&executable)?),
            "config_sha256":hash_bytes(&std::fs::read(&args[2])?),
            "stage":args[1],"seeds":config.seeds,"expected_states":expected_total,
            "scientific_seed_bundles":0,"behavioral_inference":false,
            "analysis_threads":config.threads,
            "rank_multiplier":linear::RANK_MULTIPLIER,"rank_diagnostics":linear::RANK_DIAGNOSTICS,
            "integrity_tolerance":linear::INTEGRITY_TOLERANCE,
            "svd_epsilon":linear::SVD_EPSILON,"svd_max_iterations":linear::SVD_MAX_ITERATIONS
        }),
    )?;
    let mut total = 0;
    let mut failed = false;
    for &seed in &config.seeds {
        for side in &config.sides {
            for &tau in &config.taus {
                let graph = Graph::load(Path::new(&args[3]), side, config.glut_sign)?;
                let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733);
                ensure!(rewire.accepted > 0 && rewire.degree_preserved);
                let task = Task::new(&graph, seed ^ config.input_salt, 16, 12, 512);
                let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())?;
                let mut results = Vec::new();
                for arm in &config.arms {
                    let mut sim = Simulator::new(&graph, &graph.route, seed, tau, 0.05, arm);
                    let denom = sim.drive_denominators().to_vec();
                    if arm == "E" {
                        sim.capture = Some(Capture::new(sim.weights.len()));
                        sim.policy = Some(Policy::new(sim.weights.len()));
                    }
                    let run =
                        sim.run_dh07(&task, Dh07Condition::TruePerpendicular, &shuffled, true, 0)?;
                    ensure!(run.result.outcome.hot_allocations == 0);
                    ensure!(arm != "Z" || run.result.outcome.changed_weights == 0);
                    let mut events = Vec::new();
                    if let Some(policy) = sim.policy.take() {
                        ensure!(policy.count == 256);
                        let audited = audit_pool.install(|| {
                            policy.snapshots[..policy.count]
                                .par_iter()
                                .map(|s| {
                                    let save = seed == config.seeds[0]
                                        && side == "R"
                                        && tau == 4.
                                        && s.trial == 1;
                                    linear::audit(&op, s, &denom, save)
                                })
                                .collect::<Result<Vec<_>>>()
                        })?;
                        for (audit, replay) in audited {
                            failed |= !audit.integrity.valid;
                            total += 1;
                            if let Some(replay) = replay {
                                write_json(&out.join("replay-R-tau4-trial1.json"), &replay)?;
                            }
                            events.push(audit);
                        }
                    }
                    results.push(
                        json!({"arm":arm,"canonical_sha256":canonical_hash(&run.result)?,
                "final_weight_sha256":weight_hash(&sim.weights),
                "hot_allocations":run.result.outcome.hot_allocations,"events":events,
                "true_endpoint_sha256":sim.capture.as_ref().map(|c|&c.true_endpoint_sha256)}),
                    );
                }
                write_json(
                    &out.join(if args[1] == "stage-a" {
                        format!("{side}-tau{tau}.json")
                    } else {
                        format!("seed{seed}-{side}-tau{tau}.json")
                    }),
                    &json!({
            "protocol":"Q09-LFA","schema_version":1,"seed":seed,"side":side,"tau":tau,
            "post_len":graph.kc_mb.n_post,"drive_rows":op.rows.len(),
            "combined_rows":op.rows.len()+1,"results":results}),
                )?;
                println!("audit complete seed={seed} {side} tau={tau}");
            }
        }
    }
    ensure!(total == expected_total);
    // Stage B is an incremental sweep over seeds 9202..9205. Its receipt
    // reports the cumulative Q09 count (Stage A + new Stage B states), while
    // retaining the new-state count so the arithmetic is explicit.
    let cumulative_total = if args[1] == "stage-b" {
        total + 1024
    } else {
        total
    };
    let mut execution = json!({"protocol":"Q09-LFA","schema_version":1,
        "stage":args[1],"complete":true,"audited_states":cumulative_total,
        "scientific_seed_bundles":0,"behavioral_inference":false,
        "linear_integrity_valid":!failed,"box_feasibility":"NOT_TESTED",
        "alternative_seq32_equality":"NOT_TESTED"});
    if args[1] == "stage-b" {
        execution["new_audited_states"] = json!(total);
        execution["prior_stage_a_states"] = json!(1024);
    }
    write_json(&out.join("execution.json"), &execution)?;
    ensure!(
        !failed,
        "linear integrity failed; receipts retained, do not proceed"
    );
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn seed_and_mode_firewall() {
        let mut c: Config = serde_json::from_value(json!({
            "observe":true,"seeds":[9201],"taus":[4.,16.],"sides":["R","L"],
            "conditions":["true_perpendicular"],"arms":["E","Z"],"cues":16,
            "delay_steps":12,"trials":512,"eta":0.05,"glut_sign":-1.,
            "input_salt":858980352,"threads":8}))
        .unwrap();
        assert_eq!(validate_config("stage-a", &c).unwrap(), 1024);
        c.seeds = vec![9202, 9203, 9204, 9205];
        assert_eq!(validate_config("stage-b", &c).unwrap(), 4096);
        c.seeds = vec![9201];
        for mode in ["smoke", "run", "measured", "full", "qualify"] {
            assert!(validate_config(mode, &c).is_err());
        }
        for seed in [0, 7000, 8000, 9100, 9200, 9202, 9205] {
            c.seeds = vec![seed];
            assert!(validate_config("stage-a", &c).is_err());
        }
    }
}
