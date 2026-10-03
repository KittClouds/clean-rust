use hashbrown::HashSet;
use r1_search::{annotate_posthoc, prefix_metrics, read_jsonl, write_jsonl, PrefixBudget};
use r1_stage1_search::{
    run, verify_replay, Arm, Edit, MergeMode, PolicyCosts, PolicyError, PolicyLatentUpdate,
    PolicyScores, PolicyValue, RunConfig, SearchAllocationPolicy, SearchError, SearchPolicy,
    SelectorInput, SemanticFeatures, Stage1RunConfig, TransitionInput, ValueInput,
    ValueRefreshPolicy,
};
use r1_world::{Clause, InferenceTask, Task};
use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

struct StubPolicy {
    proposal_calls: u64,
    selector_calls: u64,
    value_calls: u64,
    value_budgets: Vec<u64>,
}

impl StubPolicy {
    fn new() -> Self {
        Self {
            proposal_calls: 0,
            selector_calls: 0,
            value_calls: 0,
            value_budgets: Vec::new(),
        }
    }
}

impl SearchPolicy for StubPolicy {
    fn score_edits(
        &mut self,
        input: TransitionInput<'_>,
        candidates: &[Edit],
    ) -> Result<PolicyScores, PolicyError> {
        self.proposal_calls += 1;
        let logits = candidates
            .iter()
            .map(|edit| {
                f32::from(edit.entity) * 0.11
                    + f32::from(edit.new_role) * 0.29
                    + input.latent_state.first().copied().unwrap_or_default() * 0.03
            })
            .collect();
        Ok(PolicyScores {
            logits,
            costs: PolicyCosts {
                logits_scored: candidates.len() as u64,
                encoder_forward_calls: 1,
                encoder_tokens: input.task.clauses.len() as u64 + 1,
                gpu_active_ns: 2,
            },
        })
    }

    fn advance_latent(
        &mut self,
        input: TransitionInput<'_>,
        selected: Edit,
    ) -> Result<PolicyLatentUpdate, PolicyError> {
        let mut next_state = input.latent_state.to_vec();
        if let Some(value) = next_state.first_mut() {
            *value = (*value
                + input.remaining_budget as f32 * 0.001
                + f32::from(selected.entity) * 0.01
                + f32::from(selected.new_role) * 0.02)
                .tanh();
        }
        Ok(PolicyLatentUpdate {
            next_state,
            costs: PolicyCosts {
                gpu_active_ns: 7,
                ..PolicyCosts::default()
            },
        })
    }

    fn q_terminal(&mut self, input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError> {
        self.selector_calls += 1;
        let role_zero = input.assignment.iter().filter(|&&role| role == 0).count();
        let feature_signal = input
            .features
            .global_embedding
            .first()
            .copied()
            .unwrap_or_default();
        Ok(PolicyValue {
            value: role_zero as f32 / input.assignment.len() as f32 + feature_signal * 0.001,
            selection_score: None,
            costs: PolicyCosts {
                encoder_forward_calls: 1,
                encoder_tokens: 1,
                gpu_active_ns: 3,
                ..PolicyCosts::default()
            },
        })
    }

    fn v_reach(&mut self, input: ValueInput<'_>) -> Result<PolicyValue, PolicyError> {
        self.value_calls += 1;
        self.value_budgets.push(input.remaining_budget);
        let role_zero = input.assignment.iter().filter(|&&role| role == 0).count();
        let depth_signal = input.depth as f32 * 0.001;
        let remaining = input.remaining_budget as f32;
        let latent_signal = input.latent_state.first().copied().unwrap_or_default();
        Ok(PolicyValue {
            value: (role_zero as f32 / input.assignment.len() as f32
                + depth_signal
                + latent_signal * 0.01
                + remaining * 0.0001)
                .clamp(0.0, 1.0),
            selection_score: None,
            costs: PolicyCosts {
                encoder_forward_calls: 1,
                encoder_tokens: input.task.clauses.len() as u64 + 1,
                gpu_active_ns: 5,
                ..PolicyCosts::default()
            },
        })
    }
}

fn world(n: u16, k: u8, role_anonymous: bool) -> (Task, InferenceTask) {
    let clauses = if n >= 3 {
        vec![
            Clause::Different { a: 0, b: 1 },
            Clause::Same { a: 1, b: 2 },
        ]
    } else {
        Vec::new()
    };
    let task = Task {
        id: format!("stage1-task-{n}-{k}-{role_anonymous}"),
        family_id: format!("stage1-family-{n}-{k}-{role_anonymous}"),
        seed: 0x7531,
        n,
        k,
        clauses,
        role_anonymous,
    };
    let inference = r1_world::render_task(&task, 0x2026).inference;
    (task, inference)
}

fn features(task: &InferenceTask) -> SemanticFeatures {
    let clauses = task.clauses.len();
    let entities = usize::from(task.n);
    let roles = usize::from(task.k);
    SemanticFeatures::from_projection(
        task,
        4,
        vec![0.1; clauses * 4].into_boxed_slice(),
        vec![0.25, -0.5, 0.75, 1.0].into_boxed_slice(),
    )
    .unwrap_or_else(|_| {
        // Preserve a loud test failure if projection fixture metadata is malformed.
        SemanticFeatures {
            hidden_dim: 4,
            constraint_count: clauses,
            entity_count: entities,
            role_count: roles,
            constraint_embeddings: vec![0.1; clauses * 4].into_boxed_slice(),
            global_embedding: vec![0.25, -0.5, 0.75, 1.0].into_boxed_slice(),
            constraint_mask: vec![1; clauses].into_boxed_slice(),
            entity_incidence: vec![0; clauses * entities].into_boxed_slice(),
            role_incidence: vec![0; clauses * roles].into_boxed_slice(),
            entity_mask: vec![1; entities].into_boxed_slice(),
            role_mask: vec![1; roles].into_boxed_slice(),
        }
    })
}

fn config(arm: Arm, budget: u64, width: u16) -> Stage1RunConfig {
    let mut base = RunConfig::new(arm, budget, width, 0x4455);
    base.latent_dim = 8;
    base.resample_period = 4;
    base.minimum_particle_budget = 1;
    let mut result = Stage1RunConfig::from_stage0(base);
    result.proposal_id = "deterministic-stub-v1".to_owned();
    result.selector_id = "deterministic-q-stub-v1".to_owned();
    result.value_id = "deterministic-v-stub-v1".to_owned();
    result
}

#[test]
fn all_arms_share_policy_hooks_and_charge_every_expansion() {
    let (_, task) = world(4, 2, true);
    let task_features = features(&task);
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
        let mut policy = StubPolicy::new();
        let result = run(&task, &task_features, config(arm, 40, 4), &mut policy).unwrap();
        let trace = &result.trace;
        assert_eq!(trace.events.len(), 40, "{arm:?}");
        assert_eq!(trace.ledger.expansions, 40, "{arm:?}");
        assert_eq!(trace.ledger.proposal_calls, 40, "{arm:?}");
        assert_eq!(
            trace.ledger.value_calls,
            unique_q_states(trace) + result.manifest.value_calls
        );
        assert_eq!(result.manifest.selector_calls, unique_q_states(trace));
        assert_eq!(result.manifest.value_calls, policy.value_calls);
        assert_eq!(
            result.manifest.value_evaluated,
            matches!(arm, Arm::MergedWidth | Arm::CanonicalMerge | Arm::Particle)
        );
        assert_eq!(
            trace.ledger.encoder_forward_calls,
            policy.selector_calls + policy.value_calls + policy.proposal_calls
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
        let expected_gpu_ns = policy.proposal_calls * 2
            + policy.selector_calls * 3
            + policy.value_calls * 5
            + if arm == Arm::RandomWidth {
                0
            } else {
                trace.events.len() as u64 * 7
            };
        assert_eq!(trace.ledger.gpu_active_ns, expected_gpu_ns, "{arm:?}");
        assert_eq!(
            trace.events.last().unwrap().cumulative_active_ns,
            trace.ledger.cpu_active_ns + trace.ledger.gpu_active_ns,
            "{arm:?} active prefix must include CPU and GPU time"
        );
        assert!(trace
            .events
            .iter()
            .all(|event| event.latent_state_after.len() == 8));
        if arm == Arm::RandomWidth {
            assert!(trace
                .events
                .iter()
                .all(|event| event.latent_state_after.iter().all(|value| *value == 0.0)));
        }
        assert!(trace.selected_event.is_some() || trace.selected_initial_particle.is_some());
    }
}

#[test]
fn same_horizon_refresh_charges_current_budget_scores() {
    let (_, task) = world(4, 2, true);
    let task_features = features(&task);
    let mut policy = StubPolicy::new();
    let mut cfg = config(Arm::Particle, 24, 4);
    cfg.value_refresh_policy = ValueRefreshPolicy::EveryExpansion;
    let result = run(&task, &task_features, cfg, &mut policy).unwrap();

    assert_eq!(
        result.manifest.value_scoring_policy,
        "same-horizon-live-and-merge-refresh-v01"
    );
    assert!(result.manifest.value_calls > 24 + 4);
    assert_eq!(result.manifest.value_calls, policy.value_calls);
    assert_eq!(
        result.trace.ledger.value_calls,
        unique_q_states(&result.trace) + policy.value_calls
    );
    for remaining in 0..24 {
        assert!(
            policy.value_budgets.contains(&remaining),
            "no reachability value was evaluated at remaining budget {remaining}"
        );
    }
}

#[test]
fn resample_boundary_refresh_uses_broad_allocation_between_value_decisions() {
    let (_, task) = world(4, 2, true);
    let task_features = features(&task);
    let mut policy = StubPolicy::new();
    let mut cfg = config(Arm::Particle, 24, 4);
    cfg.merge_mode = MergeMode::None;
    cfg.value_refresh_policy = ValueRefreshPolicy::ResampleBoundary;
    let result = run(&task, &task_features, cfg, &mut policy).unwrap();

    assert_eq!(
        result.manifest.value_scoring_policy,
        "resample-boundary-live-and-merge-refresh-v01"
    );
    assert_eq!(
        result.manifest.particle_allocation_policy,
        "round-robin-between-resample-boundaries-v01"
    );
    assert_eq!(
        result
            .trace
            .events
            .iter()
            .take(4)
            .map(|event| event.particle_id)
            .collect::<Vec<_>>(),
        vec![0, 1, 2, 3]
    );
    let resamples = result
        .trace
        .events
        .iter()
        .filter(|event| event.resampled)
        .count() as u64;
    assert!(resamples > 0);
    assert_eq!(
        policy.value_calls,
        24 + 4 + 3 * resamples,
        "transition and initial scores plus live-particle refreshes at resample boundaries"
    );
    assert_eq!(result.manifest.value_calls, policy.value_calls);
    assert_eq!(
        result.trace.ledger.value_calls,
        unique_q_states(&result.trace) + policy.value_calls
    );
}

#[test]
fn resampling_respects_width_cap_until_a_particle_is_old_enough_to_retire() {
    let (_, task) = world(4, 2, true);
    let task_features = features(&task);
    let mut policy = StubPolicy::new();
    let mut cfg = config(Arm::Particle, 24, 4);
    cfg.merge_mode = MergeMode::None;
    cfg.base.minimum_particle_budget = 8;
    cfg.value_refresh_policy = ValueRefreshPolicy::ResampleBoundary;
    let result = run(&task, &task_features, cfg, &mut policy).unwrap();

    assert_eq!(result.trace.ledger.peak_live_particles, 4);
    assert_eq!(result.trace.ledger.resampling_ops, 0);
    assert_eq!(policy.value_calls, 4 + 24);
    assert_eq!(result.manifest.value_calls, policy.value_calls);
}

#[test]
fn protected_spine_preserves_sampled_depth_then_uses_remaining_width() {
    let (_, task) = world(4, 2, true);
    let task_features = features(&task);
    let mut depth_policy = StubPolicy::new();
    let sampled = run(
        &task,
        &task_features,
        config(Arm::SampledDepth, 256, 8),
        &mut depth_policy,
    )
    .unwrap();

    let mut spine_config = config(Arm::LearnedWidth, 256, 8);
    spine_config.allocation_policy =
        SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget: 192 };
    let mut spine_policy = StubPolicy::new();
    let spine = run(
        &task,
        &task_features,
        spine_config.clone(),
        &mut spine_policy,
    )
    .unwrap();
    let mut standard_policy = StubPolicy::new();
    let standard = run(
        &task,
        &task_features,
        config(Arm::LearnedWidth, 256, 8),
        &mut standard_policy,
    )
    .unwrap();

    assert_eq!(spine.trace.ledger.expansions, 256);
    assert_eq!(spine.trace.ledger.allocation_decisions, 256);
    assert_eq!(spine.trace.ledger.nonnominal_allocation_decisions, 0);
    assert!(spine
        .trace
        .events
        .iter()
        .all(|event| !event.value_allocation_non_nominal));
    assert_eq!(spine.trace.ledger.peak_live_particles, 8);
    assert_eq!(spine.trace.ledger.merges, 0);
    assert_eq!(spine.manifest.value_calls, 0);
    assert_eq!(spine.manifest.schema, "r1-stage1-run-manifest-v4");
    assert_eq!(
        spine.manifest.search_allocation_policy,
        SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget: 192 }
    );
    assert_ne!(standard.trace.header.trace_id, spine.trace.header.trace_id);

    for (spine_event, sampled_event) in spine.trace.events[..192]
        .iter()
        .zip(&sampled.trace.events[..192])
    {
        assert_eq!(spine_event.particle_id, 0);
        assert_eq!(
            spine_event.assignment_before,
            sampled_event.assignment_before
        );
        assert_eq!(spine_event.assignment_after, sampled_event.assignment_after);
        assert_eq!(
            spine_event.latent_state_before,
            sampled_event.latent_state_before
        );
        assert_eq!(
            spine_event.latent_state_after,
            sampled_event.latent_state_after
        );
        assert_eq!(spine_event.edit, sampled_event.edit);
        assert_eq!(spine_event.rng_state_before, sampled_event.rng_state_before);
        assert_eq!(spine_event.rng_state_after, sampled_event.rng_state_after);
        assert_eq!(spine_event.log_probability, sampled_event.log_probability);
    }

    let branch_ids = spine.trace.events[192..]
        .iter()
        .map(|event| event.particle_id)
        .collect::<Vec<_>>();
    assert_eq!(
        branch_ids,
        (0..64)
            .map(|offset| (offset % 7 + 1) as u32)
            .collect::<Vec<_>>()
    );
    let mut last_assignments = spine
        .trace
        .header
        .initial_particles
        .iter()
        .map(|particle| particle.assignment.clone())
        .collect::<Vec<_>>();
    let mut last_rng_states = spine
        .trace
        .header
        .initial_particles
        .iter()
        .map(|particle| particle.rng_state)
        .collect::<Vec<_>>();
    for event in &spine.trace.events {
        let particle_id = event.particle_id as usize;
        assert_eq!(event.assignment_before, last_assignments[particle_id]);
        assert_eq!(event.rng_state_before, last_rng_states[particle_id]);
        last_assignments[particle_id] = event.assignment_after.clone();
        last_rng_states[particle_id] = event.rng_state_after;
    }
    let mut replay_policy = StubPolicy::new();
    let replay = verify_replay(
        &task,
        &task_features,
        spine_config,
        &mut replay_policy,
        &spine,
    )
    .unwrap();
    assert!(replay.passed);
}

#[test]
fn protected_spine_rejects_configurations_that_change_its_semantics() {
    let (_, task) = world(4, 2, true);
    let task_features = features(&task);
    let mut policy = StubPolicy::new();

    let mut wrong_arm = config(Arm::Particle, 200, 8);
    wrong_arm.allocation_policy =
        SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget: 192 };
    assert!(run(&task, &task_features, wrong_arm, &mut policy).is_err());

    let mut wrong_budget = config(Arm::LearnedWidth, 192, 8);
    wrong_budget.allocation_policy =
        SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget: 192 };
    assert!(run(&task, &task_features, wrong_budget, &mut policy).is_err());

    let mut wrong_width = config(Arm::LearnedWidth, 200, 1);
    wrong_width.allocation_policy =
        SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget: 192 };
    assert!(run(&task, &task_features, wrong_width, &mut policy).is_err());

    let mut wrong_merge = config(Arm::LearnedWidth, 200, 8);
    wrong_merge.merge_mode = MergeMode::RawAssignment;
    wrong_merge.allocation_policy =
        SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget: 192 };
    assert!(run(&task, &task_features, wrong_merge, &mut policy).is_err());

    let mut fork_at_depth_limit = config(Arm::LearnedWidth, u64::from(u32::MAX) + 2, 2);
    fork_at_depth_limit.allocation_policy = SearchAllocationPolicy::ForkFromSpineThenWidth {
        spine_budget: u64::from(u32::MAX),
    };
    assert!(run(&task, &task_features, fork_at_depth_limit, &mut policy).is_err());

    let mut fork_branch_overflow = config(Arm::LearnedWidth, u64::from(u32::MAX) + 1, 2);
    fork_branch_overflow.allocation_policy =
        SearchAllocationPolicy::ForkFromSpineThenWidth { spine_budget: 1 };
    assert!(run(&task, &task_features, fork_branch_overflow, &mut policy).is_err());
}

#[test]
fn forked_spine_clones_deep_state_and_preserves_independent_rng_lineages() {
    let (_, task) = world(4, 2, true);
    let task_features = features(&task);
    let mut sampled_policy = StubPolicy::new();
    let sampled = run(
        &task,
        &task_features,
        config(Arm::SampledDepth, 256, 8),
        &mut sampled_policy,
    )
    .unwrap();

    let mut fork_config = config(Arm::LearnedWidth, 256, 8);
    fork_config.allocation_policy =
        SearchAllocationPolicy::ForkFromSpineThenWidth { spine_budget: 192 };
    let mut fork_policy = StubPolicy::new();
    let fork = run(&task, &task_features, fork_config.clone(), &mut fork_policy).unwrap();
    assert_eq!(fork.trace.ledger.expansions, 256);
    assert_eq!(fork.trace.ledger.allocation_decisions, 256);
    assert_eq!(fork.trace.ledger.nonnominal_allocation_decisions, 0);
    assert_eq!(fork.trace.ledger.peak_live_particles, 8);
    assert_eq!(fork.trace.ledger.merges, 0);
    assert_eq!(fork.trace.ledger.resampling_ops, 0);
    assert_eq!(fork.manifest.value_calls, 0);
    assert_eq!(
        fork.manifest.search_allocation_policy,
        SearchAllocationPolicy::ForkFromSpineThenWidth { spine_budget: 192 }
    );

    for (fork_event, sampled_event) in fork.trace.events[..192]
        .iter()
        .zip(&sampled.trace.events[..192])
    {
        assert_eq!(fork_event.particle_id, 0);
        assert_eq!(
            fork_event.assignment_before,
            sampled_event.assignment_before
        );
        assert_eq!(fork_event.assignment_after, sampled_event.assignment_after);
        assert_eq!(
            fork_event.latent_state_after,
            sampled_event.latent_state_after
        );
        assert_eq!(fork_event.rng_state_after, sampled_event.rng_state_after);
    }

    let expected_branches = (0..64)
        .map(|offset| (offset % 7 + 1) as u32)
        .collect::<Vec<_>>();
    assert_eq!(
        fork.trace.events[192..]
            .iter()
            .map(|event| event.particle_id)
            .collect::<Vec<_>>(),
        expected_branches
    );
    let spine_end = &fork.trace.events[191];
    let spine_ancestry_id = spine_end.ancestry_id;
    let mut branch_seen = [false; 8];
    let mut branch_ancestry = HashSet::new();
    let mut branch_ancestry_by_id = [None; 8];
    let mut last_event_indices = [None; 8];
    let mut last_latents = fork
        .trace
        .header
        .initial_particles
        .iter()
        .map(|particle| particle.latent_state.clone())
        .collect::<Vec<_>>();
    let mut last_assignments = fork
        .trace
        .header
        .initial_particles
        .iter()
        .map(|particle| particle.assignment.clone())
        .collect::<Vec<_>>();
    let mut last_rng_states = fork
        .trace
        .header
        .initial_particles
        .iter()
        .map(|particle| particle.rng_state)
        .collect::<Vec<_>>();
    for event in &fork.trace.events {
        let particle_id = event.particle_id as usize;
        if particle_id != 0 && !branch_seen[particle_id] {
            assert_eq!(event.parent_particle_id, Some(0));
            assert_eq!(event.parent_event_index, Some(spine_end.event_index));
            assert_eq!(event.particle_depth, 193);
            assert_eq!(event.assignment_before, spine_end.assignment_after);
            assert_eq!(event.latent_state_before, spine_end.latent_state_after);
            assert_eq!(
                event.rng_state_before,
                fork.trace.header.initial_particles[particle_id].rng_state
            );
            assert_ne!(event.ancestry_id, spine_ancestry_id);
            assert!(branch_ancestry.insert(event.ancestry_id));
            branch_ancestry_by_id[particle_id] = Some(event.ancestry_id);
            last_assignments[particle_id] = spine_end.assignment_after.clone();
            last_latents[particle_id] = spine_end.latent_state_after.clone();
            last_rng_states[particle_id] =
                fork.trace.header.initial_particles[particle_id].rng_state;
            last_event_indices[particle_id] = Some(spine_end.event_index);
            branch_seen[particle_id] = true;
        } else if particle_id != 0 {
            assert_eq!(event.parent_particle_id, Some(0));
            assert_eq!(event.parent_event_index, last_event_indices[particle_id]);
            assert_eq!(Some(event.ancestry_id), branch_ancestry_by_id[particle_id]);
        }
        assert_eq!(event.assignment_before, last_assignments[particle_id]);
        assert_eq!(event.latent_state_before, last_latents[particle_id]);
        assert_eq!(event.rng_state_before, last_rng_states[particle_id]);
        last_assignments[particle_id] = event.assignment_after.clone();
        last_latents[particle_id] = event.latent_state_after.clone();
        last_rng_states[particle_id] = event.rng_state_after;
        last_event_indices[particle_id] = Some(event.event_index);
    }
    assert!(branch_seen[1..].iter().all(|seen| *seen));
    assert_eq!(branch_ancestry.len(), 7);

    let mut replay_policy = StubPolicy::new();
    let replay = verify_replay(
        &task,
        &task_features,
        fork_config,
        &mut replay_policy,
        &fork,
    )
    .unwrap();
    assert!(replay.passed);
}

fn unique_q_states(trace: &r1_stage1_search::RunTrace) -> u64 {
    let mut states = HashSet::<Vec<u8>>::new();
    for initial in &trace.header.initial_particles {
        states.insert(initial.assignment.clone());
    }
    for event in &trace.events {
        states.insert(event.assignment_after.clone());
    }
    states.len() as u64
}

#[test]
fn latent_update_is_conditioned_on_the_selected_edit() {
    let (_, task) = world(4, 2, true);
    let task_features = features(&task);
    let mut policy = StubPolicy::new();
    let trace = run(&task, &task_features, config(Arm::Depth, 4, 1), &mut policy)
        .unwrap()
        .trace;
    for event in &trace.events {
        let edit = event.edit.expect("each completed expansion has an edit");
        let previous = event.latent_state_before[0];
        let expected = (previous
            + (event.remaining_budget + 1) as f32 * 0.001
            + f32::from(edit.entity) * 0.01
            + f32::from(edit.new_role) * 0.02)
            .tanh();
        assert_eq!(event.latent_state_after[0], expected);
    }
}

#[test]
fn canonical_and_raw_merge_paths_and_particle_resampling_are_recorded() {
    let (_, task) = world(1, 2, true);
    let task_features = features(&task);

    let mut raw_config = config(Arm::MergedWidth, 32, 4);
    raw_config.merge_mode = MergeMode::RawAssignment;
    let mut raw_policy = StubPolicy::new();
    let raw = run(&task, &task_features, raw_config, &mut raw_policy).unwrap();
    assert!(raw
        .trace
        .events
        .iter()
        .any(|event| event.raw_duplicate_detected));
    assert!(raw.trace.ledger.merges > 0);

    let mut canonical_config = config(Arm::CanonicalMerge, 32, 4);
    canonical_config.merge_mode = MergeMode::CanonicalAssignment;
    let mut canonical_policy = StubPolicy::new();
    let canonical = run(
        &task,
        &task_features,
        canonical_config,
        &mut canonical_policy,
    )
    .unwrap();
    assert!(canonical
        .trace
        .events
        .iter()
        .any(|event| event.canonical_duplicate_detected));
    assert!(canonical.trace.ledger.merges > 0);

    let (_, particle_task) = world(4, 2, true);
    let particle_features = features(&particle_task);
    let mut particle_policy = StubPolicy::new();
    let particle = run(
        &particle_task,
        &particle_features,
        config(Arm::Particle, 40, 4),
        &mut particle_policy,
    )
    .unwrap();
    assert!(particle.trace.ledger.resampling_ops > 0);
    assert!(particle.trace.ledger.peak_live_particles <= 4);
}

#[test]
fn particle_resampling_does_not_exceed_width_when_only_source_is_live() {
    let (_, task) = world(4, 2, true);
    let task_features = features(&task);
    let mut policy = StubPolicy::new();
    let result = run(
        &task,
        &task_features,
        config(Arm::Particle, 16, 1),
        &mut policy,
    )
    .unwrap();

    assert_eq!(result.trace.ledger.expansions, 16);
    assert_eq!(result.trace.ledger.peak_live_particles, 1);
    assert_eq!(result.trace.ledger.resampling_ops, 0);
}

#[test]
fn deterministic_policy_replays_and_stage0_trace_io_accepts_full_events() {
    let (private, task) = world(4, 2, true);
    let features = features(&task);
    let cfg = config(Arm::Particle, 24, 4);
    let mut first_policy = StubPolicy::new();
    let first = run(&task, &features, cfg.clone(), &mut first_policy).unwrap();
    let mut replay_policy = StubPolicy::new();
    let replay = verify_replay(&task, &features, cfg, &mut replay_policy, &first).unwrap();
    assert!(replay.passed, "{replay:?}");

    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "r1-stage1-search-{}-{nonce}.jsonl",
        std::process::id()
    ));
    write_jsonl(&path, &first.trace).unwrap();
    let decoded = read_jsonl(&path).unwrap();
    fs::remove_file(&path).unwrap();
    assert_eq!(decoded, first.trace);

    let sidecar = annotate_posthoc(&private, &first.trace).unwrap();
    let prefix = prefix_metrics(
        &first.trace,
        &sidecar,
        PrefixBudget::Expansions(first.trace.ledger.expansions),
    )
    .unwrap();
    assert_eq!(prefix.completed_expansions, 24);
    assert!(prefix.reachability_including_initial);
    let final_event = first.trace.events.last().unwrap();
    for budget in [
        PrefixBudget::ActiveNs(final_event.cumulative_active_ns),
        PrefixBudget::WallNs(final_event.cumulative_wall_ns),
    ] {
        let timed = prefix_metrics(&first.trace, &sidecar, budget).unwrap();
        assert_eq!(timed.completed_expansions, 24);
        assert!(timed.reachability_including_initial);
    }
}

#[test]
fn sampling_temperature_is_manifested_replayed_and_bound_to_trace_identity() {
    let (_, task) = world(4, 2, true);
    let task_features = features(&task);
    let mut ordinary_config = config(Arm::LearnedWidth, 24, 4);
    let mut ordinary_policy = StubPolicy::new();
    let ordinary = run(
        &task,
        &task_features,
        ordinary_config.clone(),
        &mut ordinary_policy,
    )
    .unwrap();

    let mut cold_config = ordinary_config.clone();
    cold_config.learned_sample_temperature = 0.25;
    let mut cold_policy = StubPolicy::new();
    let cold = run(&task, &task_features, cold_config.clone(), &mut cold_policy).unwrap();
    assert_eq!(cold.manifest.learned_sample_temperature, Some(0.25));
    assert_ne!(ordinary.trace.header.trace_id, cold.trace.header.trace_id);

    let mut depth_default_config = config(Arm::Depth, 24, 4);
    let mut depth_default_policy = StubPolicy::new();
    let depth_default = run(
        &task,
        &task_features,
        depth_default_config.clone(),
        &mut depth_default_policy,
    )
    .unwrap();
    depth_default_config.learned_sample_temperature = 0.25;
    let mut depth_changed_policy = StubPolicy::new();
    let depth_changed = run(
        &task,
        &task_features,
        depth_default_config,
        &mut depth_changed_policy,
    )
    .unwrap();
    assert_eq!(
        depth_default.trace.header.trace_id,
        depth_changed.trace.header.trace_id
    );
    assert_eq!(
        depth_default
            .trace
            .events
            .iter()
            .map(|event| event.assignment_after.as_slice())
            .collect::<Vec<_>>(),
        depth_changed
            .trace
            .events
            .iter()
            .map(|event| event.assignment_after.as_slice())
            .collect::<Vec<_>>()
    );

    let mut replay_policy = StubPolicy::new();
    let replay = verify_replay(
        &task,
        &task_features,
        cold_config.clone(),
        &mut replay_policy,
        &cold,
    )
    .unwrap();
    assert!(replay.passed, "{replay:?}");

    let mut mismatched_config = cold_config.clone();
    mismatched_config.learned_sample_temperature = 1.0;
    let mut mismatched_policy = StubPolicy::new();
    let mismatched = verify_replay(
        &task,
        &task_features,
        mismatched_config,
        &mut mismatched_policy,
        &cold,
    )
    .unwrap();
    assert!(!mismatched.passed);

    ordinary_config.learned_sample_temperature = 0.0;
    let mut invalid_policy = StubPolicy::new();
    assert!(matches!(
        run(&task, &task_features, ordinary_config, &mut invalid_policy),
        Err(SearchError::InvalidConfig(_))
    ));
}
