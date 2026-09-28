use std::collections::BTreeMap;
use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

use r1_search::{
    annotate_posthoc, prefix_metrics, read_jsonl, run, verify_replay, write_jsonl, Arm,
    PrefixBudget, RunConfig,
};
use r1_world::{render_task, Clause, InferenceTask, Task};

fn symbolic_task(n: u16, k: u8, role_anonymous: bool) -> Task {
    let clauses = if n >= 2 && k >= 2 {
        vec![Clause::Same { a: 0, b: 1 }]
    } else {
        Vec::new()
    };
    Task {
        id: format!("opaque-task-{n}-{k}-{role_anonymous}"),
        family_id: format!("opaque-family-{n}-{k}-{role_anonymous}"),
        seed: 0x4a31_0091,
        n,
        k,
        clauses,
        role_anonymous,
    }
}

fn public_task(n: u16, k: u8, role_anonymous: bool) -> InferenceTask {
    let task = symbolic_task(n, k, role_anonymous);
    render_task(&task, 0x1f31_2026).inference
}

fn config(arm: Arm, budget: u64, width: u16, seed: u64) -> RunConfig {
    let mut config = RunConfig::new(arm, budget, width, seed);
    config.latent_dim = 8;
    config.resample_period = 8;
    config.minimum_particle_budget = 1;
    config
}

#[test]
fn all_arms_consume_exact_transition_budget_and_never_need_a_validator() {
    let task = public_task(4, 2, true);
    let arms = [
        Arm::Depth,
        Arm::SampledDepth,
        Arm::RandomWidth,
        Arm::LearnedWidth,
        Arm::MergedWidth,
        Arm::CanonicalMerge,
        Arm::Particle,
    ];
    for arm in arms {
        let trace = run(&task, config(arm, 64, 4, 0x7a12)).expect("model-free run");
        assert_eq!(trace.events.len(), 64, "{arm:?}");
        assert_eq!(trace.ledger.expansions, 64, "{arm:?}");
        assert_eq!(trace.ledger.proposal_calls, 64, "{arm:?}");
        assert_eq!(
            trace.ledger.value_calls,
            2 * 64 + trace.header.initial_particles.len() as u64 * 2
        );
        assert_eq!(
            trace.ledger.merges,
            trace
                .events
                .iter()
                .filter(|event| event.raw_merge || event.canonical_merge)
                .count() as u64
        );
        assert_eq!(
            trace.ledger.resampling_ops,
            trace.events.iter().filter(|event| event.resampled).count() as u64
        );
        assert_eq!(
            trace.ledger.selection_comparisons,
            trace.header.initial_particles.len().saturating_sub(1) as u64
                + trace.events.len() as u64
        );
        assert_eq!(
            trace.ledger.allocation_decisions,
            trace
                .events
                .iter()
                .filter(|event| event.costs.allocation_decisions > 0)
                .count() as u64
        );
        assert_eq!(
            trace.ledger.nonnominal_allocation_decisions,
            trace
                .events
                .iter()
                .filter(|event| event.value_allocation_non_nominal)
                .count() as u64
        );
        assert_eq!(
            trace.ledger.redirected_future_expansions,
            trace
                .events
                .iter()
                .filter(|event| event.nominal_slot_redirected)
                .count() as u64
        );
        assert!(trace
            .events
            .iter()
            .all(|event| event.latent_state_after.len() == 8));
    }

    let projection_json = serde_json::to_value(&task).expect("public projection serializes");
    for forbidden in [
        "seed",
        "solutions",
        "solver",
        "automorphisms",
        "clauses_typed",
    ] {
        assert!(
            projection_json.get(forbidden).is_none(),
            "public projection has {forbidden}"
        );
    }
    assert!(run(&public_task(2, 1, false), config(Arm::Depth, 8, 1, 3)).is_err());
}

#[test]
fn width_slots_are_distributed_and_merging_only_recycles_future_slots() {
    let task = public_task(5, 3, false);
    let trace = run(&task, config(Arm::LearnedWidth, 64, 4, 9021)).unwrap();
    let mut counts = BTreeMap::<u32, usize>::new();
    for event in &trace.events {
        *counts.entry(event.particle_id).or_default() += 1;
    }
    assert_eq!(counts.len(), 4);
    assert!(counts.values().all(|count| *count == 16));

    let repeated = public_task(1, 2, true);
    for arm in [Arm::MergedWidth, Arm::CanonicalMerge, Arm::Particle] {
        let trace =
            run(&repeated, config(arm, 64, 4, 711)).expect("merge scheduler keeps a live pool");
        assert_eq!(trace.ledger.expansions, 64);
        assert_eq!(trace.events.len(), 64);
        assert!(trace.ledger.peak_live_particles >= 1);
        assert!(trace
            .events
            .iter()
            .any(|event| event.raw_duplicate_detected || event.canonical_duplicate_detected));
        assert_eq!(
            trace.ledger.redirected_future_expansions,
            trace
                .events
                .iter()
                .filter(|event| event.nominal_slot_redirected)
                .count() as u64
        );
        assert!(trace.ledger.redirected_future_expansions > 0, "{arm:?}");
    }

    let divergent = run(
        &public_task(1, 2, false),
        config(Arm::MergedWidth, 128, 4, 319),
    )
    .unwrap();
    assert!(divergent.events.iter().any(|event| {
        event
            .merge_latent_divergence_l2
            .is_some_and(|distance| distance.is_finite() && distance > 0.0)
    }));
}

#[test]
fn replay_and_jsonl_preserve_semantics_and_full_trace() {
    let private = symbolic_task(4, 2, true);
    let rendered = render_task(&private, 0x18a2);
    let trace = run(&rendered.inference, config(Arm::Particle, 64, 4, 77001)).unwrap();
    let replay = verify_replay(&rendered.inference, &trace).unwrap();
    assert!(replay.passed, "{replay:?}");
    assert!(replay.semantic_match);
    assert!(replay.timestamps_monotone);

    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("r1-search-{}-{nonce}.jsonl", std::process::id()));
    write_jsonl(&path, &trace).unwrap();
    let decoded = read_jsonl(&path).unwrap();
    fs::remove_file(&path).unwrap();
    assert_eq!(decoded, trace);
    assert!(decoded
        .events
        .iter()
        .all(|event| event.latent_state_before.len() == 8));
}

#[test]
fn reachability_and_selection_are_distinct_and_prefixes_are_monotone() {
    let private = symbolic_task(2, 2, true);
    let rendered = render_task(&private, 0x8812);
    let mut witnessed_separation = false;
    let mut chosen_trace = None;
    let mut chosen_sidecar = None;
    for seed in 0..96 {
        let trace = run(&rendered.inference, config(Arm::LearnedWidth, 48, 4, seed)).unwrap();
        let sidecar = annotate_posthoc(&private, &trace).unwrap();
        let full = prefix_metrics(&trace, &sidecar, PrefixBudget::Expansions(48)).unwrap();
        if full.reachability_excluding_initial && !full.selected_state_valid {
            witnessed_separation = true;
            chosen_trace = Some(trace);
            chosen_sidecar = Some(sidecar);
            break;
        }
    }
    assert!(
        witnessed_separation,
        "stub selector should expose a search/selection failure case"
    );
    let trace = chosen_trace.unwrap();
    let sidecar = chosen_sidecar.unwrap();
    for prefix in [
        PrefixBudget::ActiveNs(trace.header.initial_completion_active_ns.saturating_sub(1)),
        PrefixBudget::WallNs(trace.header.initial_completion_wall_ns.saturating_sub(1)),
    ] {
        let before_initial = prefix_metrics(&trace, &sidecar, prefix).unwrap();
        assert!(!before_initial.reachability_including_initial);
        assert!(!before_initial.selected_state_valid);
        assert_eq!(before_initial.distinct_valid_classes_reached, 0);
    }
    let mut previous_r = false;
    let mut previous_s = false;
    for budget in 0..=trace.ledger.expansions {
        let metrics = prefix_metrics(&trace, &sidecar, PrefixBudget::Expansions(budget)).unwrap();
        assert!(metrics.completed_expansions >= budget.min(trace.ledger.expansions));
        assert!(!previous_r || metrics.reachability_including_initial);
        assert!(!previous_s || metrics.reachability_excluding_initial);
        previous_r = metrics.reachability_including_initial;
        previous_s = metrics.reachability_excluding_initial;
    }
    let active_limits = trace
        .events
        .iter()
        .map(|event| event.cumulative_active_ns)
        .collect::<Vec<_>>();
    let wall_limits = trace
        .events
        .iter()
        .map(|event| event.cumulative_wall_ns)
        .collect::<Vec<_>>();
    assert_time_prefix_monotone(&trace, &sidecar, active_limits, true);
    assert_time_prefix_monotone(&trace, &sidecar, wall_limits, false);
}

fn assert_time_prefix_monotone(
    trace: &r1_search::RunTrace,
    sidecar: &r1_search::PosthocSidecar,
    limits: Vec<u64>,
    active: bool,
) {
    let mut sorted = limits;
    sorted.sort_unstable();
    sorted.dedup();
    let mut was_reachable = false;
    for limit in sorted {
        let prefix = if active {
            PrefixBudget::ActiveNs(limit)
        } else {
            PrefixBudget::WallNs(limit)
        };
        let metrics = prefix_metrics(trace, sidecar, prefix).unwrap();
        assert!(!was_reachable || metrics.reachability_including_initial);
        was_reachable = metrics.reachability_including_initial;
    }
}
