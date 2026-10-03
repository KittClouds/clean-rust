//! Stage 0 construction smoke. This binary has no model or tokenizer dependency.

use std::collections::BTreeSet;
use std::fs::{self, File};
use std::io::{BufWriter, Read, Write};
use std::path::{Path, PathBuf};

use r1_search::{
    annotate_posthoc, prefix_metrics, read_jsonl, run, verify_replay, write_jsonl, Arm,
    PrefixBudget, RunConfig,
};
use r1_world::{
    automorphisms, canonical_assignment, enumerate_solutions, generate_smoke_batch, render_task,
    validate, validate_independent, Task,
};
use serde::Serialize;
use sha2::{Digest, Sha256};

const SOLUTION_CAP: usize = 4096;
const DEFAULT_COUNT: usize = 96;
const EXPANSION_BUDGET: u64 = 64;
const WIDTH: u16 = 4;
const BASE_SEED: u64 = 0xF451_2026_0925_0001;

#[derive(Serialize)]
struct TaskEvidence {
    task_id: String,
    family_id: String,
    n: u16,
    k: u8,
    role_anonymous: bool,
    raw_solution_count: usize,
    canonical_solution_class_count: usize,
    automorphism_count: usize,
    exact_count_status: &'static str,
    independent_validator_agreement: bool,
    symmetry_validity_preserved: bool,
}

#[derive(Serialize)]
struct RunEvidence {
    task_id: String,
    arm: Arm,
    trace_path: String,
    sidecar_path: String,
    trace_sha256: String,
    sidecar_sha256: String,
    expansions: u64,
    replay_pass: bool,
    full_prefix_reachability: bool,
    full_prefix_selected_valid: bool,
    initial_valid: bool,
    end_to_end_wall_ns: u64,
    cpu_active_ns: u64,
    redirected_future_expansions: u64,
}

#[derive(Serialize)]
struct Receipt<'a> {
    schema: &'static str,
    status: &'a str,
    base_seed: u64,
    accepted_worlds: usize,
    expected_worlds: usize,
    expected_runs: usize,
    completed_runs: usize,
    multiplicity_strata_observed: Vec<String>,
    role_modes_observed: Vec<String>,
    all_expansion_ledgers_balanced: bool,
    all_replays_passed: bool,
    all_independent_validators_agreed: bool,
    all_symmetry_checks_passed: bool,
    model_contact_performed: bool,
    training_performed: bool,
    evaluation_performed: bool,
    trace_timing_kind: &'static str,
    operating_system: String,
    architecture: String,
    executable: String,
    command_args: Vec<String>,
    error: Option<String>,
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 || args.len() > 3 {
        eprintln!("usage: r1-runner OUTPUT_ROOT [WORLD_COUNT]");
        std::process::exit(2);
    }
    let output_root = PathBuf::from(&args[1]);
    let count = match args.get(2) {
        Some(value) => match value.parse::<usize>() {
            Ok(value) if value > 0 => value,
            _ => {
                eprintln!("WORLD_COUNT must be a positive integer");
                std::process::exit(2);
            }
        },
        None => DEFAULT_COUNT,
    };
    if output_root.exists() {
        eprintln!(
            "attempt directory already exists; refusing overwrite: {}",
            output_root.display()
        );
        std::process::exit(2);
    }
    if let Err(error) = fs::create_dir(&output_root) {
        eprintln!("cannot create a new attempt directory: {error}");
        std::process::exit(2);
    }

    match execute(&output_root, count) {
        Ok(receipt) => {
            if let Err(error) = write_json(&output_root.join("construction-receipt.json"), &receipt)
            {
                eprintln!("cannot write construction receipt: {error}");
                std::process::exit(1);
            }
            println!("{}", receipt.status);
        }
        Err(error) => {
            let receipt = Receipt {
                schema: "R1_STAGE0_CONSTRUCTION_RECEIPT_V01",
                status: "R1_CONSTRUCTION_FAILED",
                base_seed: BASE_SEED,
                accepted_worlds: 0,
                expected_worlds: count,
                expected_runs: 0,
                completed_runs: 0,
                multiplicity_strata_observed: Vec::new(),
                role_modes_observed: Vec::new(),
                all_expansion_ledgers_balanced: false,
                all_replays_passed: false,
                all_independent_validators_agreed: false,
                all_symmetry_checks_passed: false,
                model_contact_performed: false,
                training_performed: false,
                evaluation_performed: false,
                trace_timing_kind: "measured_cpu_and_wall",
                operating_system: std::env::consts::OS.to_owned(),
                architecture: std::env::consts::ARCH.to_owned(),
                executable: std::env::current_exe()
                    .map(|p| p.display().to_string())
                    .unwrap_or_default(),
                command_args: std::env::args().collect(),
                error: Some(error.clone()),
            };
            let _ = write_json(&output_root.join("construction-receipt.json"), &receipt);
            eprintln!("R1_CONSTRUCTION_FAILED: {error}");
            std::process::exit(1);
        }
    }
}

fn execute(output_root: &Path, count: usize) -> Result<Receipt<'static>, String> {
    let tasks = generate_smoke_batch(BASE_SEED, count).map_err(|e| e.to_string())?;
    if tasks.len() != count {
        return Err(format!(
            "generator returned {} tasks, expected {count}",
            tasks.len()
        ));
    }
    let mut task_writer = BufWriter::new(
        File::create(output_root.join("private-tasks.jsonl")).map_err(|e| e.to_string())?,
    );
    let mut public_writer = BufWriter::new(
        File::create(output_root.join("public-tasks.jsonl")).map_err(|e| e.to_string())?,
    );
    let mut task_evidence = Vec::with_capacity(count);
    let mut run_evidence = Vec::new();
    let mut strata = BTreeSet::new();
    let mut role_modes = BTreeSet::new();
    let trace_dir = output_root.join("traces");
    let sidecar_dir = output_root.join("posthoc");
    fs::create_dir(&trace_dir).map_err(|e| e.to_string())?;
    fs::create_dir(&sidecar_dir).map_err(|e| e.to_string())?;

    for (task_index, task) in tasks.iter().enumerate() {
        let solutions = enumerate_solutions(task, SOLUTION_CAP).map_err(|e| e.to_string())?;
        if solutions.is_empty() {
            return Err(format!("task {} has no valid assignment", task.id));
        }
        let group = automorphisms(task);
        if group.is_empty() {
            return Err(format!("task {} has no identity automorphism", task.id));
        }
        let classes: BTreeSet<_> = solutions
            .iter()
            .map(|assignment| canonical_assignment(assignment, &group))
            .collect();
        let mut independent_agreement = true;
        let mut symmetry_preserved = true;
        for solution in &solutions {
            independent_agreement &=
                validate(task, solution) && validate_independent(task, solution);
            let canonical = canonical_assignment(solution, &group);
            symmetry_preserved &=
                validate(task, &canonical) && canonical_assignment(&canonical, &group) == canonical;
            for permutation in &group {
                let permuted: Vec<u8> = solution
                    .iter()
                    .map(|&role| permutation[usize::from(role)])
                    .collect();
                symmetry_preserved &= validate(task, &permuted);
            }
        }
        if !independent_agreement || !symmetry_preserved {
            return Err(format!("validator or symmetry failure on task {}", task.id));
        }
        let stratum = solution_stratum(classes.len());
        strata.insert(stratum.to_owned());
        role_modes.insert(if task.role_anonymous {
            "role_anonymous".to_owned()
        } else {
            "role_specific".to_owned()
        });
        task_evidence.push(TaskEvidence {
            task_id: task.id.clone(),
            family_id: task.family_id.clone(),
            n: task.n,
            k: task.k,
            role_anonymous: task.role_anonymous,
            raw_solution_count: solutions.len(),
            canonical_solution_class_count: classes.len(),
            automorphism_count: group.len(),
            exact_count_status: "EXHAUSTED",
            independent_validator_agreement: independent_agreement,
            symmetry_validity_preserved: symmetry_preserved,
        });
        write_jsonl_value(&mut task_writer, task)?;
        let rendered = render_task(task, BASE_SEED ^ task_index as u64);
        write_jsonl_value(&mut public_writer, &rendered.inference)?;

        for arm in arms_for(task) {
            let arm_name = format!("{arm:?}").to_lowercase();
            let stem = format!("task-{task_index:03}-{arm_name}");
            let config = RunConfig::new(
                arm,
                EXPANSION_BUDGET,
                if matches!(arm, Arm::Depth | Arm::SampledDepth) {
                    1
                } else {
                    WIDTH
                },
                BASE_SEED ^ task_index as u64,
            );
            let trace = run(&rendered.inference, config).map_err(|e| e.to_string())?;
            if trace.events.len() as u64 != EXPANSION_BUDGET
                || trace.ledger.expansions != EXPANSION_BUDGET
            {
                return Err(format!("expansion ledger imbalance in {stem}"));
            }
            let replay = verify_replay(&rendered.inference, &trace)
                .map_err(|e| format!("replay failure in {stem}: {e}"))?;
            let sidecar = annotate_posthoc(task, &trace)
                .map_err(|e| format!("posthoc failure in {stem}: {e}"))?;
            let full = prefix_metrics(&trace, &sidecar, PrefixBudget::Expansions(EXPANSION_BUDGET))
                .map_err(|e| format!("prefix failure in {stem}: {e}"))?;
            let trace_path = trace_dir.join(format!("{stem}.jsonl"));
            let sidecar_path = sidecar_dir.join(format!("{stem}.json"));
            write_jsonl(&trace_path, &trace).map_err(|e| e.to_string())?;
            let recovered = read_jsonl(&trace_path)
                .map_err(|e| format!("trace readback failure in {stem}: {e}"))?;
            let recovered_replay = verify_replay(&rendered.inference, &recovered)
                .map_err(|e| format!("readback replay failure in {stem}: {e}"))?;
            if !recovered_replay.passed {
                return Err(format!("readback replay mismatch in {stem}"));
            }
            write_json(&sidecar_path, &sidecar)?;
            run_evidence.push(RunEvidence {
                task_id: task.id.clone(),
                arm,
                trace_path: format!("traces/{stem}.jsonl"),
                sidecar_path: format!("posthoc/{stem}.json"),
                trace_sha256: sha256_file(&trace_path)?,
                sidecar_sha256: sha256_file(&sidecar_path)?,
                expansions: trace.ledger.expansions,
                replay_pass: replay.passed,
                full_prefix_reachability: full.reachability_including_initial,
                full_prefix_selected_valid: full.selected_state_valid,
                initial_valid: sidecar.initial_valid,
                end_to_end_wall_ns: trace.ledger.end_to_end_wall_ns,
                cpu_active_ns: trace.ledger.cpu_active_ns,
                redirected_future_expansions: trace.ledger.redirected_future_expansions,
            });
        }
    }
    task_writer.flush().map_err(|e| e.to_string())?;
    public_writer.flush().map_err(|e| e.to_string())?;
    write_json(&output_root.join("task-evidence.json"), &task_evidence)?;
    write_json(&output_root.join("run-evidence.json"), &run_evidence)?;

    let required: BTreeSet<_> = ["1", "2-4", "5-16", "17+"]
        .into_iter()
        .map(str::to_owned)
        .collect();
    let complete = count == DEFAULT_COUNT
        && strata == required
        && role_modes.len() == 2
        && run_evidence
            .iter()
            .all(|run| run.replay_pass && run.expansions == EXPANSION_BUDGET);
    let receipt = Receipt {
        schema: "R1_STAGE0_CONSTRUCTION_RECEIPT_V01",
        status: if complete {
            "R1_CONSTRUCTION_READY"
        } else {
            "R1_DIAGNOSTIC_COMPLETE"
        },
        base_seed: BASE_SEED,
        accepted_worlds: tasks.len(),
        expected_worlds: count,
        expected_runs: run_evidence.len(),
        completed_runs: run_evidence.len(),
        multiplicity_strata_observed: strata.into_iter().collect(),
        role_modes_observed: role_modes.into_iter().collect(),
        all_expansion_ledgers_balanced: true,
        all_replays_passed: run_evidence.iter().all(|run| run.replay_pass),
        all_independent_validators_agreed: true,
        all_symmetry_checks_passed: true,
        model_contact_performed: false,
        training_performed: false,
        evaluation_performed: false,
        trace_timing_kind: "measured_cpu_and_wall",
        operating_system: std::env::consts::OS.to_owned(),
        architecture: std::env::consts::ARCH.to_owned(),
        executable: std::env::current_exe()
            .map(|p| p.display().to_string())
            .unwrap_or_default(),
        command_args: std::env::args().collect(),
        error: None,
    };
    Ok(receipt)
}

fn arms_for(task: &Task) -> Vec<Arm> {
    let mut arms = vec![
        Arm::Depth,
        Arm::SampledDepth,
        Arm::RandomWidth,
        Arm::LearnedWidth,
        Arm::MergedWidth,
    ];
    if task.role_anonymous {
        arms.extend([Arm::CanonicalMerge, Arm::Particle]);
    }
    arms
}

fn solution_stratum(count: usize) -> &'static str {
    match count {
        0 => "0",
        1 => "1",
        2..=4 => "2-4",
        5..=16 => "5-16",
        _ => "17+",
    }
}

fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let file = File::create(path).map_err(|e| e.to_string())?;
    let mut writer = BufWriter::new(file);
    serde_json::to_writer_pretty(&mut writer, value).map_err(|e| e.to_string())?;
    writer.flush().map_err(|e| e.to_string())
}

fn write_jsonl_value<T: Serialize>(writer: &mut impl Write, value: &T) -> Result<(), String> {
    serde_json::to_writer(&mut *writer, value).map_err(|e| e.to_string())?;
    writer.write_all(b"\n").map_err(|e| e.to_string())
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut file = File::open(path).map_err(|e| e.to_string())?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let len = file.read(&mut buffer).map_err(|e| e.to_string())?;
        if len == 0 {
            break;
        }
        digest.update(&buffer[..len]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

#[cfg(test)]
mod tests {
    use super::solution_stratum;

    #[test]
    fn canonical_count_buckets_have_exact_boundaries() {
        assert_eq!(solution_stratum(1), "1");
        assert_eq!(solution_stratum(2), "2-4");
        assert_eq!(solution_stratum(4), "2-4");
        assert_eq!(solution_stratum(5), "5-16");
        assert_eq!(solution_stratum(16), "5-16");
        assert_eq!(solution_stratum(17), "17+");
    }
}
