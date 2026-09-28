use super::*;

fn apply_cue_permutation(task: &mut Task, old_to_new: &[usize; 4]) {
    let mut labels = [false; 4];
    for old in 0..4 {
        labels[old_to_new[old]] = task.labels[old];
    }
    let mut current_old = [0usize, 1, 2, 3];
    for target in 0..4 {
        let wanted_old = (0..4).find(|&old| old_to_new[old] == target).unwrap();
        let current = current_old
            .iter()
            .position(|&old| old == wanted_old)
            .unwrap();
        if current != target {
            task.patterns.swap(current, target);
        }
        current_old.swap(current, target);
    }
    task.labels[..4].copy_from_slice(&labels);
    for row in &mut task.schedule {
        for pattern in row {
            if *pattern < 4 {
                *pattern = old_to_new[*pattern];
            }
        }
    }
}

fn invert_cue_permutation(task: &mut Task, old_to_new: &[usize; 4]) {
    let mut inverse = [0usize; 4];
    for old in 0..4 {
        inverse[old_to_new[old]] = old;
    }
    apply_cue_permutation(task, &inverse);
}

pub(super) fn all_permutations() -> Vec<[usize; 4]> {
    let mut out = Vec::with_capacity(24);
    for a in 0..4 {
        for b in 0..4 {
            if b == a {
                continue;
            }
            for c in 0..4 {
                if c == a || c == b {
                    continue;
                }
                for d in 0..4 {
                    if d != a && d != b && d != c {
                        out.push([a, b, c, d]);
                    }
                }
            }
        }
    }
    out
}

fn sign3(value: f32) -> i8 {
    if value > 0.0 {
        1
    } else if value < 0.0 {
        -1
    } else {
        0
    }
}

fn compare_reference(
    sim: &Sim<'_>,
    original_task: &Task,
    transformed_task: &mut Task,
    inversion: bool,
    grad: &mut [f64],
    baseline: &mut [f32],
    changed_value: &mut f64,
    changed_sign: &mut u64,
    changed_target: &mut u64,
    pairs: &mut u64,
) {
    collector::reference_delta_into(sim, original_task, REFERENCE_LR, baseline, grad);
    let mut transformed = vec![0.0_f32; baseline.len()];
    let mut transformed_grad = vec![0.0_f64; baseline.len()];
    let mut transformed_sim = sim.clone();
    if inversion {
        for action in &mut transformed_sim.action_sign {
            *action = -*action;
        }
    }
    collector::reference_delta_into(
        &transformed_sim,
        transformed_task,
        REFERENCE_LR,
        &mut transformed,
        &mut transformed_grad,
    );
    for (&a, &b) in baseline.iter().zip(&transformed) {
        *changed_value = (*changed_value).max((f64::from(a) - f64::from(b)).abs());
        *changed_sign += u64::from(sign3(a) != sign3(b));
        *changed_target += u64::from(collector::target(a) != collector::target(b));
        *pairs += 1;
    }
}

fn fixture_snapshots<'a>(
    graph: &'a Graph,
    train: &TrainBlock,
    block_id: u64,
) -> Result<Vec<(usize, &'static str, Sim<'a>, Task)>> {
    // Lifetime of each Sim is tied to the supplied graph and is retained by the tuple.
    let task = Task::new(
        graph,
        train.task_seed,
        train.labels.clone(),
        train.schedule.clone(),
    );
    let mut sim = Sim::new(graph, train.task_seed ^ SIM_SEED_XOR, TAU, ETA);
    let mut local_abs = vec![0.0; sim.weights.len()];
    let mut local_signed = vec![0.0; sim.weights.len()];
    let mut delta = vec![0.0; sim.weights.len()];
    let mut snapshots = Vec::with_capacity(18);
    for trial in 0..=255 {
        let (_correct, reward) =
            sim.begin_trial_with_local(&task, trial, &mut local_abs, &mut local_signed);
        if TRIAL_FIXTURES.contains(&trial) {
            snapshots.push((trial, "after_begin_trial", sim.clone(), task.clone()));
        }
        sim.proposed_delta_into(reward, &mut delta);
        if TRIAL_FIXTURES.contains(&trial) {
            snapshots.push((trial, "after_proposed_delta", sim.clone(), task.clone()));
            snapshots.push((
                trial,
                "immediately_before_apply_delta",
                sim.clone(),
                task.clone(),
            ));
        }
        sim.apply_delta(&delta);
        ensure!(
            sim.finite(),
            "fixture replay became nonfinite at block={block_id} trial={trial}"
        );
    }
    Ok(snapshots)
}

fn fixtures_inner(study: &Path, lineage: &Path, out: &Path) -> Result<()> {
    ensure!(out.is_dir(), "output directory missing");
    verify_preflight_manifest(study, out)?;
    ensure!(
        !out.join("REPRESENTATION-FIXTURE-RECEIPT.json").exists(),
        "fixture receipt already exists"
    );
    let (training, _) = parse_blocks(study)?;
    let graph = graph::load(lineage, "fly", "L", -1.0)?;
    let mut permutations = all_permutations();
    permutations.sort_unstable();
    ensure!(permutations.len() == 24);
    let mut representation_checks = 0_u64;
    let mut d_checks = 0_u64;
    let mut cue_max_abs_g = 0.0_f64;
    let mut cue_sign_changes = 0_u64;
    let mut cue_target_changes = 0_u64;
    let mut cue_target_pairs = 0_u64;
    let mut inverse_max_abs_g = 0.0_f64;
    let mut inverse_sign_changes = 0_u64;
    let mut inverse_target_changes = 0_u64;
    let mut inverse_target_pairs = 0_u64;
    let mut inversion_checks = 0_u64;
    let mut snapshot_count = 0usize;
    let coordinates: Vec<usize> = (0..graph.kc_mb.edges.len()).collect();
    for block_id in BLOCKS {
        let train = training
            .blocks
            .get(&block_id.to_string())
            .context("fixture training block")?;
        let snapshots = fixture_snapshots(&graph, train, block_id)?;
        for (trial, phase, base_sim, mut base_task) in snapshots {
            snapshot_count += 1;
            let mut base_g = vec![0.0_f32; base_sim.weights.len()];
            let mut grad = vec![0.0_f64; base_sim.weights.len()];
            collector::reference_delta_into(
                &base_sim,
                &base_task,
                REFERENCE_LR,
                &mut base_g,
                &mut grad,
            );
            let original_task = base_task.clone();
            let base_probabilities = cue_probability_table(&original_task, &base_sim);
            let base_tuples: Vec<[RelTuple; 4]> = coordinates
                .iter()
                .map(|&coordinate| {
                    tuple_for_probabilities(
                        &original_task,
                        &base_sim,
                        coordinate,
                        &base_probabilities,
                    )
                })
                .collect::<Result<_>>()?;
            for &pi in &permutations {
                apply_cue_permutation(&mut base_task, &pi);
                let permuted_probabilities: [Vec<f32>; 4] = std::array::from_fn(|new_cue| {
                    let old_cue = (0..4).find(|&old| pi[old] == new_cue).unwrap();
                    base_probabilities[old_cue].clone()
                });
                for (&coordinate, base) in coordinates.iter().zip(&base_tuples) {
                    let changed = tuple_for_probabilities(
                        &base_task,
                        &base_sim,
                        coordinate,
                        &permuted_probabilities,
                    )?;
                    for old in 0..4 {
                        ensure!(
                            tuple_bytes(changed[pi[old]]) == tuple_bytes(base[old]),
                            "cue tuple permutation mismatch block={block_id} trial={trial} phase={phase} cue={old} coordinate={coordinate}"
                        );
                        representation_checks += 1;
                    }
                    ensure!(
                        sorted_tuple_bytes(changed) == sorted_tuple_bytes(*base),
                        "D cue permutation mismatch"
                    );
                    d_checks += 1;
                }
                compare_reference(
                    &base_sim,
                    &original_task,
                    &mut base_task,
                    false,
                    &mut grad,
                    &mut base_g,
                    &mut cue_max_abs_g,
                    &mut cue_sign_changes,
                    &mut cue_target_changes,
                    &mut cue_target_pairs,
                );
                invert_cue_permutation(&mut base_task, &pi);
            }
            let mut inverted_task = original_task.clone();
            for label in &mut inverted_task.labels {
                *label = !*label;
            }
            let mut inverted_sim = base_sim.clone();
            for action in &mut inverted_sim.action_sign {
                *action = -*action;
            }
            for &coordinate in &coordinates {
                let a = tuple_for_probabilities(
                    &original_task,
                    &base_sim,
                    coordinate,
                    &base_probabilities,
                )?;
                let b = tuple_for_probabilities(
                    &inverted_task,
                    &inverted_sim,
                    coordinate,
                    &base_probabilities,
                )?;
                ensure!(
                    a.map(tuple_bytes) == b.map(tuple_bytes),
                    "joint inversion tuple mismatch block={block_id} trial={trial} phase={phase} coordinate={coordinate}"
                );
                ensure!(
                    sorted_tuple_bytes(a) == sorted_tuple_bytes(b),
                    "joint inversion D mismatch"
                );
                inversion_checks += 1;
            }
            compare_reference(
                &base_sim,
                &original_task,
                &mut inverted_task,
                true,
                &mut grad,
                &mut base_g,
                &mut inverse_max_abs_g,
                &mut inverse_sign_changes,
                &mut inverse_target_changes,
                &mut inverse_target_pairs,
            );
        }
    }
    write_json(
        &out.join("REPRESENTATION-FIXTURE-RECEIPT.json"),
        &json!({
            "schema":"F4-SYMMETRY-01-representation-fixture-v1", "gate_id":"REPRESENTATION_INVARIANTS", "status":"PASS",
            "cue_permutations":24, "snapshot_count":snapshot_count, "all_kcmb_coordinates":coordinates.len(),
            "C_expected_transform_checks":representation_checks, "D_invariance_checks":d_checks,
            "joint_inversion_tuple_checks":inversion_checks, "first_mismatch":null
        }),
    )?;
    write_json(
        &out.join("TARGET-SYMMETRY-DIAGNOSTIC.json"),
        &json!({
            "schema":"F4-SYMMETRY-01-target-symmetry-diagnostic-v1", "status":"RECORDED",
            "cue_relabeling": {"max_abs_reference_difference":cue_max_abs_g, "three_way_sign_changes":cue_sign_changes, "threshold_channel_changes":cue_target_changes, "coordinate_pairs":cue_target_pairs},
            "joint_label_action_inversion": {"max_abs_reference_difference":inverse_max_abs_g, "three_way_sign_changes":inverse_sign_changes, "threshold_channel_changes":inverse_target_changes, "coordinate_pairs":inverse_target_pairs},
            "target_invariance_required":false, "rows_removed_due_to_target_changes":0
        }),
    )?;
    Ok(())
}

pub fn fixtures(study: &Path, lineage: &Path, out: &Path) -> Result<()> {
    let result = fixtures_inner(study, lineage, out);
    if let Err(error) = &result {
        let path = out.join("REPRESENTATION-FIXTURE-STOP-RECEIPT.json");
        if !path.exists() {
            let _ = write_json(
                &path,
                &json!({
                    "schema":"F4-SYMMETRY-01-failed-gate-v1",
                    "gate_id":"REPRESENTATION_INVARIANTS",
                    "status":"STOP",
                    "first_mismatch":format!("{error:#}"),
                    "measured_namespace_created":false
                }),
            );
        }
    }
    result
}
