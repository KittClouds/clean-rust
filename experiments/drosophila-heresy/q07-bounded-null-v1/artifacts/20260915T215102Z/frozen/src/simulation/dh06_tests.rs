use super::*;

    const CONDITIONS: [Dh06Condition; 6] = [
        Dh06Condition::Immediate,
        Dh06Condition::Quiet,
        Dh06Condition::Neither,
        Dh06Condition::ParallelOnly,
        Dh06Condition::PerpendicularOnly,
        Dh06Condition::Both,
    ];

    #[test]
    fn interventions_and_same_rng_probe_are_exact() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 99, 16, 12, 64);
        for condition in CONDITIONS {
            let run = Simulator::new(&graph, &graph.route, 3, 16.0, 0.05, "E").run_dh06(
                &task,
                condition,
                &graph.route,
                true,
            );
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
                    condition == Dh06Condition::Neither
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
                Dh06Condition::Both,
                crate::simulation::dh03::Dh03Condition::RestoreState,
            ),
            (
                Dh06Condition::Neither,
                crate::simulation::dh03::Dh03Condition::SuppressBoth,
            ),
        ] {
            let mut old = Simulator::new(&graph, &graph.route, 4, 4.0, 0.05, "E");
            let mut new = Simulator::new(&graph, &graph.route, 4, 4.0, 0.05, "E");
            let a = old.run_dh03(&task, parent, &graph.route, true);
            let b = new.run_dh06(&task, current, &graph.route, true);
            assert_eq!(old.weights, new.weights);
            assert_eq!(a.outcome.curve, b.result.outcome.curve);
            assert_eq!(a.outcome.probe_reversal, b.result.outcome.probe_reversal);
        }
    }

    #[test]
    fn reference_geometry_is_finite_and_self_aligned() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 17, 16, 12, 64);
        let mut runs: Vec<_> = CONDITIONS
            .into_iter()
            .map(|condition| {
                Simulator::new(&graph, &graph.route, 9, 16.0, 0.05, "E").run_dh06(
                    &task,
                    condition,
                    &graph.route,
                    true,
                )
            })
            .collect();
        let contrast = attach_immediate_reference_dh06(&mut runs);
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
                Simulator::new(&graph, &graph.route, 44, 4.0, 0.05, "Z").run_dh06(
                    &task,
                    condition,
                    &graph.route,
                    true,
                )
            })
            .collect();
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
        let run = Simulator::new(&graph, &graph.route, 44, 4.0, 0.05, "E").run_dh06(
            &task,
            Dh06Condition::Both,
            &graph.route,
            true,
        );
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
        let new_retained = new_both.run_dh06(&task, Dh06Condition::Both, &graph.route, true);
        let old_suppressed = old_neither.run_dh04(
            &task,
            crate::simulation::dh04::Dh04Condition::EligibilitySuppressed,
            &graph.route,
            true,
        );
        let new_suppressed =
            new_neither.run_dh06(&task, Dh06Condition::Neither, &graph.route, true);
        assert_eq!(old_both.weights, new_both.weights);
        assert_eq!(old_neither.weights, new_neither.weights);
        assert_eq!(old_retained.result.outcome.curve, new_retained.result.outcome.curve);
        assert_eq!(old_suppressed.result.outcome.curve, new_suppressed.result.outcome.curve);
        for run in [new_retained, new_suppressed] {
            let geometry = run.result.geometry;
            assert_eq!(geometry.interval_trials, 32);
            assert!(geometry.reconstruction_max_abs_error <= 1e-6);
            assert!((geometry.parallel_energy_fraction + geometry.perpendicular_energy_fraction - 1.0).abs() < 1e-5);
            assert_eq!(geometry.q_negative + geometry.q_positive + geometry.q_zero, 32);
        }
    }

    #[test]
    #[ignore = "explicit DH06 trajectory benchmark"]
    fn benchmark_dh06_trajectory() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 771, 16, 12, 512);
        let mut times = Vec::new();
        for _ in 0..21 {
            let run = Simulator::new(&graph, &graph.route, 992, 16.0, 0.05, "E").run_dh06(
                &task,
                Dh06Condition::Both,
                &graph.route,
                true,
            );
            assert_eq!(run.result.outcome.hot_allocations, 0);
            times.push(run.result.outcome.seconds);
        }
        times.sort_by(f64::total_cmp);
        println!(
            "DH06 trajectory median_seconds={} p95_seconds={} hot_allocations=0",
            times[10], times[19]
        );
    }

