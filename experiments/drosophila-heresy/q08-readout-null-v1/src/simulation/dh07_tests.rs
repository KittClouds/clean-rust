use super::*;

const CONDITIONS: [Dh07Condition; 8] = [
    Dh07Condition::Immediate,
    Dh07Condition::Quiet,
    Dh07Condition::Neither,
    Dh07Condition::ParallelOnly,
    Dh07Condition::TruePerpendicular,
    Dh07Condition::NullPerpendicular,
    Dh07Condition::BothTrue,
    Dh07Condition::ParallelNull,
];

#[test]
fn interventions_and_same_rng_probe_are_exact() {
    let graph = Graph::fixture();
    let task = Task::new(&graph, 99, 16, 12, 64);
    for condition in CONDITIONS {
        let result = Simulator::new(&graph, &graph.route, 3, 16.0, 0.05, "E").run_dh07(
            &task,
            condition,
            &graph.route,
            true,
            0x7001,
        );
        if matches!(
            condition,
            Dh07Condition::NullPerpendicular | Dh07Condition::ParallelNull
        ) {
            let failure = match result {
                Ok(_) => panic!("strict null fixture unexpectedly passed"),
                Err(failure) => failure,
            };
            assert!(failure.true_axis_cosine.abs() > null_control::TRUE_AXIS_COS_GATE);
            continue;
        }
        let run = result.unwrap();
        assert_eq!(
            run.result.paired_final_old_probe + run.result.paired_final_reversal_probe,
            1.0
        );
        if condition.distractors() {
            let audit = &run.result.intervention[1];
            assert_eq!(audit.interval_trials, 32);
            assert!(audit.raw_interval_eligibility_l1_mean > 0.0);
            assert!(audit.pre_restore_state_mean_abs_mean > 0.0);
            assert_eq!(audit.state_restoration_applied_trials, 32);
            assert_eq!(audit.state_restoration_max_abs_error, 0.0);
            let delivered = &run.result.diagnostics.as_ref().unwrap()[1];
            assert_eq!(
                delivered.interval_eligibility_l1_mean == 0.0,
                condition == Dh07Condition::Neither
            );
        }
    }
}

#[test]
fn causal_cells_match_dh03_exactly() {
    let graph = Graph::fixture();
    let task = Task::new(&graph, 2, 16, 12, 64);
    for (current, parent) in [
        (
            Dh07Condition::BothTrue,
            crate::simulation::dh03::Dh03Condition::RestoreState,
        ),
        (
            Dh07Condition::Neither,
            crate::simulation::dh03::Dh03Condition::SuppressBoth,
        ),
    ] {
        let mut old = Simulator::new(&graph, &graph.route, 4, 4.0, 0.05, "E");
        let mut new = Simulator::new(&graph, &graph.route, 4, 4.0, 0.05, "E");
        let a = old.run_dh03(&task, parent, &graph.route, true);
        let b = new
            .run_dh07(&task, current, &graph.route, true, 0x7002)
            .unwrap();
        assert_eq!(old.weights, new.weights);
        assert_eq!(a.outcome.curve, b.result.outcome.curve);
        assert_eq!(a.outcome.probe_reversal, b.result.outcome.probe_reversal);
    }
}

#[test]
fn reference_geometry_is_finite_and_self_aligned() {
    let graph = Graph::fixture();
    let task = Task::new(&graph, 17, 16, 12, 64);
    let mut runs: Vec<_> = [
        Dh07Condition::Immediate,
        Dh07Condition::Quiet,
        Dh07Condition::Neither,
        Dh07Condition::ParallelOnly,
        Dh07Condition::TruePerpendicular,
        Dh07Condition::BothTrue,
    ]
    .into_iter()
    .map(|condition| {
        Simulator::new(&graph, &graph.route, 9, 16.0, 0.05, "E").run_dh07(
            &task,
            condition,
            &graph.route,
            true,
            0x7003,
        )
    })
    .collect::<Result<Vec<_>, _>>()
    .unwrap();
    let contrast = attach_immediate_reference_dh07(&mut runs);
    let immediate = &runs[0].result.immediate_reference.as_ref().unwrap();
    assert!((immediate.reversal_delta_cosine_to_immediate.unwrap() - 1.0).abs() < 1e-12);
    assert_eq!(
        immediate
            .distance_to_immediate_final_over_immediate_delta
            .unwrap(),
        0.0
    );
    assert!(
        contrast
            .both_minus_neither_norm_over_acquisition_norm
            .unwrap()
            > 0.0
    );
}

#[test]
fn all_conditions_share_acquisition_and_fixed_weight_actions() {
    let graph = Graph::fixture();
    let task = Task::new(&graph, 33, 16, 12, 64);
    let runs: Vec<_> = CONDITIONS
        .into_iter()
        .map(|condition| {
            Simulator::new(&graph, &graph.route, 44, 4.0, 0.05, "Z").run_dh07(
                &task,
                condition,
                &graph.route,
                true,
                0x7004,
            )
        })
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert!(runs.iter().all(|run| {
        run.result.acquisition_state_sha256 == runs[0].result.acquisition_state_sha256
    }));
    assert!(runs.iter().all(|run| {
        run.result.outcome.curve == runs[0].result.outcome.curve
            && run.result.outcome.changed_weights == 0
            && run.result.outcome.hot_allocations == 0
    }));
}

#[test]
fn trajectory_records_declared_checkpoints_from_acquired_state() {
    let graph = Graph::fixture();
    let task = Task::new(&graph, 42, 16, 12, 512);
    let run = Simulator::new(&graph, &graph.route, 44, 4.0, 0.05, "E")
        .run_dh07(&task, Dh07Condition::BothTrue, &graph.route, true, 0x7005)
        .unwrap();
    let points = &run.result.trajectory;
    assert_eq!(
        points.iter().map(|p| p.reversal_trials).collect::<Vec<_>>(),
        vec![0, 16, 32, 64, 128, 256]
    );
    assert!((points[0].acquisition_axis_coordinate.unwrap() - 1.0).abs() < 1e-6);
    assert!(points.iter().all(|p| p.old_map_margin.is_finite()));
    assert!(points.iter().all(|p| p.reversed_map_margin.is_finite()));
    assert!(run.result.outcome.hot_allocations == 0);
}

#[test]
#[ignore = "ancestor Q07-specific policy test; Q08 has dedicated tests"]
fn realized_bounded_policy_is_deterministic_and_fails_closed() {
    use crate::{capture::Capture, policy::Policy};

    let graph = Graph::fixture();
    let task = Task::new(&graph, 9000 ^ 858_980_352, 16, 12, 512);
    let run_once = || {
        let mut sim = Simulator::new(&graph, &graph.route, 9000, 4.0, 0.05, "E");
        sim.capture = Some(Capture::new(sim.weights.len()));
        sim.policy = Some(Policy::new(sim.weights.len(), 9000, 4.0, b'R'));
        let run = sim
            .run_dh07(
                &task,
                Dh07Condition::NullPerpendicular,
                &graph.route,
                true,
                0,
            )
            .unwrap();
        let policy = sim.policy.take().unwrap();
        let first_failure = policy.events.iter().find(|event| {
            let audit = &event.geometry;
            audit.axial_error_over_total_norm > 1e-7
                || audit.norm_relative_error > 1e-7
                || audit.residual_norm_relative_error > 1e-7
                || audit.residual_abs_cosine.is_none_or(|c| c > 1e-5)
                || audit.boundary_symmetric_difference != 0
                || audit.outside_support_changes != 0
                || audit.hot_allocations != 0
        });
        assert_eq!(policy.failed, first_failure.is_some());
        if !policy.failed {
            assert_eq!(policy.events.len(), 256);
        }
        (
            sim.weights,
            run.result.outcome.curve,
            policy.failed,
            policy.events,
        )
    };

    let first = run_once();
    let second = run_once();
    assert_eq!(first.0, second.0);
    assert_eq!(first.1, second.1);
    assert_eq!(first.2, second.2);
    assert_eq!(
        serde_json::to_vec(&first.3).unwrap(),
        serde_json::to_vec(&second.3).unwrap()
    );
}

#[test]
fn realized_geometry_reconstructs_and_full_corners_match_dh04() {
    let graph = Graph::fixture();
    let task = Task::new(&graph, 62, 16, 12, 64);
    let mut old_both = Simulator::new(&graph, &graph.route, 71, 4.0, 0.05, "E");
    let mut new_both = Simulator::new(&graph, &graph.route, 71, 4.0, 0.05, "E");
    let mut old_neither = Simulator::new(&graph, &graph.route, 71, 4.0, 0.05, "E");
    let mut new_neither = Simulator::new(&graph, &graph.route, 71, 4.0, 0.05, "E");
    let old_retained = old_both.run_dh04(
        &task,
        crate::simulation::dh04::Dh04Condition::EligibilityRetained,
        &graph.route,
        true,
    );
    let new_retained = new_both
        .run_dh07(&task, Dh07Condition::BothTrue, &graph.route, true, 0x7006)
        .unwrap();
    let old_suppressed = old_neither.run_dh04(
        &task,
        crate::simulation::dh04::Dh04Condition::EligibilitySuppressed,
        &graph.route,
        true,
    );
    let new_suppressed = new_neither
        .run_dh07(&task, Dh07Condition::Neither, &graph.route, true, 0x7007)
        .unwrap();
    assert_eq!(old_both.weights, new_both.weights);
    assert_eq!(old_neither.weights, new_neither.weights);
    assert_eq!(
        old_retained.result.outcome.curve,
        new_retained.result.outcome.curve
    );
    assert_eq!(
        old_suppressed.result.outcome.curve,
        new_suppressed.result.outcome.curve
    );
    for run in [new_retained, new_suppressed] {
        let geometry = run.result.geometry;
        assert_eq!(geometry.interval_trials, 32);
        assert!(geometry.reconstruction_max_abs_error <= 1e-6);
        assert!(
            (geometry.parallel_energy_fraction + geometry.perpendicular_energy_fraction - 1.0)
                .abs()
                < 1e-5
        );
        assert_eq!(
            geometry.q_negative + geometry.q_positive + geometry.q_zero,
            32
        );
    }
}

#[test]
#[ignore = "explicit non-measured real constructor qualification"]
fn qualify_dh07_real_constructor_seed_9000() {
    use serde_json::json;
    use std::{fs::OpenOptions, path::Path};

    let anatomy = Path::new("../dh06/artifacts/runs/20260915T201008Z/sealed/anatomy");
    let graph = Graph::load(anatomy, "R", -1.0).unwrap();
    let seed = 9000_u64;
    let tau = 4.0_f32;
    let task = Task::new(&graph, seed ^ 858_980_352, 16, 12, 512);
    let null_key = seed
        ^ u64::from(tau.to_bits()).rotate_left(17)
        ^ u64::from(b'R').rotate_left(7)
        ^ 0x4448_3037_4e55_4c4c;

    let mut true_receipts = Vec::new();
    let mut compatibility = Vec::new();
    for (condition, parent) in [
        (
            Dh07Condition::TruePerpendicular,
            crate::simulation::dh06::Dh06Condition::PerpendicularOnly,
        ),
        (
            Dh07Condition::BothTrue,
            crate::simulation::dh06::Dh06Condition::Both,
        ),
    ] {
        let mut current = Simulator::new(&graph, &graph.route, seed, tau, 0.05, "E");
        let run = current
            .run_dh07(&task, condition, &graph.route, true, null_key)
            .unwrap();
        let mut ancestor = Simulator::new(&graph, &graph.route, seed, tau, 0.05, "E");
        let parent_run = ancestor.run_dh06(&task, parent, &graph.route, true);
        let exact_weights = current.weights == ancestor.weights;
        let exact_curve = run.result.outcome.curve == parent_run.result.outcome.curve;
        compatibility.push(json!({
            "condition": condition,
            "dh06_condition": parent,
            "exact_final_weights": exact_weights,
            "exact_curve": exact_curve,
            "acquisition_hash_matches": run.result.acquisition_state_sha256
                == parent_run.result.acquisition_state_sha256,
        }));
        assert!(
            exact_weights
                && exact_curve
                && run.result.acquisition_state_sha256
                    == parent_run.result.acquisition_state_sha256
        );
        let max_abs_cosine = run
            .result
            .true_direction_events
            .iter()
            .map(|event| event.true_axis_cosine.abs())
            .fold(0.0_f64, f64::max);
        let first_axis_failure = run
            .result
            .true_direction_events
            .iter()
            .find(|event| !event.passes_axis_gate);
        true_receipts.push(json!({
            "condition": condition,
            "events": run.result.true_direction_events.len(),
            "max_abs_true_axis_cosine": max_abs_cosine,
            "first_axis_failure": first_axis_failure,
            "hot_allocations": run.result.outcome.hot_allocations,
        }));
    }

    let mut null_receipts = Vec::new();
    for condition in [
        Dh07Condition::NullPerpendicular,
        Dh07Condition::ParallelNull,
    ] {
        let mut sim = Simulator::new(&graph, &graph.route, seed, tau, 0.05, "E");
        match sim.run_dh07(&task, condition, &graph.route, true, null_key) {
            Ok(run) => null_receipts.push(json!({
                "condition": condition,
                "status": "constructor_succeeded",
                "events": run.result.null_events.len(),
                "max_attempts": run.result.null_events.iter().map(|event| event.attempts).max(),
            })),
            Err(failure) => null_receipts.push(json!({
                "condition": condition,
                "status": "blocked",
                "failure": failure,
            })),
        }
    }

    let parent_receipt = Path::new("../supervision/dh07/parent_audit.json");
    assert!(parent_receipt.exists());
    let receipt = json!({
        "protocol": "DH-07",
        "stage": "constructor_first_real_qualification",
        "measured_sample": false,
        "seed": seed,
        "tau": tau,
        "side": "R",
        "true_axis_cosine_gate": null_control::TRUE_AXIS_COS_GATE,
        "delivered_null_cosine_tolerance": null_control::DELIVERED_COS_TOL,
        "delivered_relative_l2_tolerance": null_control::DELIVERED_REL_NORM_TOL,
        "parent_lineage_receipt": parent_receipt,
        "dh06_compatibility": compatibility,
        "true_direction_diagnostics": true_receipts,
        "null_constructor": null_receipts,
        "interpretation": "A failed 64-attempt search establishes failure of this declared constructor only. A true-axis gate failure establishes that the strict only-direction-differs comparison is not met.",
    });
    std::fs::create_dir_all("qualification").unwrap();
    serde_json::to_writer_pretty(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open("qualification/constructor-first-real-seed9000.json")
            .unwrap(),
        &receipt,
    )
    .unwrap();
    println!("{}", serde_json::to_string_pretty(&receipt).unwrap());
}

#[test]
#[ignore = "explicit DH07 trajectory benchmark"]
fn benchmark_dh07_trajectory() {
    let graph = Graph::fixture();
    let task = Task::new(&graph, 771, 16, 12, 512);
    let mut times = Vec::new();
    for _ in 0..21 {
        let run = Simulator::new(&graph, &graph.route, 992, 16.0, 0.05, "E")
            .run_dh07(&task, Dh07Condition::BothTrue, &graph.route, true, 0x7008)
            .unwrap();
        assert_eq!(run.result.outcome.hot_allocations, 0);
        times.push(run.result.outcome.seconds);
    }
    times.sort_by(f64::total_cmp);
    println!(
        "DH07 trajectory median_seconds={} p95_seconds={} hot_allocations=0",
        times[10], times[19]
    );
}
