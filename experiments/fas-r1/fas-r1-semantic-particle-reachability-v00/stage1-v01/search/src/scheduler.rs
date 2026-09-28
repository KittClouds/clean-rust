use crate::policy::sample_action;
use crate::run_config::{MergeMode, SearchAllocationPolicy, Stage1RunConfig, ValueRefreshPolicy};
use crate::{
    DeterministicRng, Edit, MergeParticleSnapshot, PolicyCosts, PolicyError, PolicyScores,
    ProposalStrategy, SearchPolicy, SelectorInput, SemanticFeatures, Stage1Run, Stage1RunManifest,
    Stage1TraceEventDiagnostic, TransitionInput, ValueInput,
};
use hashbrown::{HashMap, HashSet};
use r1_search::{
    Arm, InitialParticle, OperationCosts, OperationLedger, ProposalMode, ResamplingRecord,
    RunTrace, TraceEvent, TraceHeader,
};
use r1_world::{canonical_assignment, InferenceTask};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::time::Instant;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SearchError {
    InvalidConfig(String),
    Policy(String),
}

impl std::fmt::Display for SearchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidConfig(message) => write!(f, "invalid Stage 1 config: {message}"),
            Self::Policy(message) => write!(f, "Stage 1 policy failed: {message}"),
        }
    }
}

impl std::error::Error for SearchError {}

impl From<PolicyError> for SearchError {
    fn from(value: PolicyError) -> Self {
        Self::Policy(value.0)
    }
}

#[derive(Clone)]
struct Particle {
    id: u32,
    parent_particle_id: Option<u32>,
    ancestry_id: u64,
    assignment: Vec<u8>,
    latent: Vec<f32>,
    rng: DeterministicRng,
    depth: u32,
    last_event: Option<u64>,
    value: f32,
    allocations_since_spawn: u64,
    alive: bool,
    retired_by_merge: bool,
}

#[derive(Clone)]
struct Representative {
    particle_id: u32,
    event_index: Option<u64>,
    initial_id: Option<u32>,
    value: f32,
    particle: Particle,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct DynamicKey {
    assignment: Vec<u8>,
    latent_bits: Vec<u32>,
    remaining: u64,
    rng: u64,
}

impl DynamicKey {
    fn new(state: &Particle, remaining: u64) -> Self {
        Self {
            assignment: state.assignment.clone(),
            latent_bits: state.latent.iter().map(|value| value.to_bits()).collect(),
            remaining,
            rng: state.rng.state,
        }
    }
}

/// Run a full search under injectable proposal, terminal-selector, and
/// reachability-value callbacks. This function never receives a private Task,
/// solver output, or validator labels.
pub fn run(
    task: &InferenceTask,
    features: &SemanticFeatures,
    config: Stage1RunConfig,
    policy: &mut impl SearchPolicy,
) -> Result<Stage1Run, SearchError> {
    validate_config(task, features, &config)?;
    let start = Instant::now();
    let base = &config.base;
    let value_enabled = uses_v_reach(base.arm);
    let width = match base.arm {
        Arm::Depth | Arm::SampledDepth => 1,
        _ => base.width,
    };
    let count = if base.budget == 0 {
        1
    } else {
        width
            .min(base.budget.min(u64::from(u16::MAX)) as u16)
            .max(1)
    };
    let group = public_group(task.k, task.role_anonymous);
    let mut costs_initial = OperationCosts::default();
    let initial_assignment =
        select_initial_assignment(task, base.seed, config.initial_assignment.as_deref());
    let canonical_initial = canonical_assignment(&initial_assignment, &group);
    costs_initial.canonicalization_calls += 1;
    let mut particles = Vec::with_capacity(usize::from(count));
    let mut initial_particles = Vec::with_capacity(usize::from(count));
    let mut selected_event = None;
    let mut selected_initial = None;
    let mut selected_q = f32::NEG_INFINITY;
    let mut selected_score = f64::NEG_INFINITY;
    let mut terminal_scores = HashMap::<Vec<u8>, (f32, f64)>::new();
    let mut initial_selection_scores = Vec::with_capacity(usize::from(count));
    let mut event_selection_scores = Vec::with_capacity(base.budget.min(65_536) as usize);
    let mut selector_calls = 0u64;
    let mut reach_value_calls = 0u64;

    for id in 0..count {
        let particle_rng = DeterministicRng::new(seed_mix(
            base.seed ^ stable_hash(&task.id, &task.family_id),
            u32::from(id),
        ));
        let latent = vec![0.0f32; usize::from(base.latent_dim)];
        let (q, ranking_score, q_costs, q_cpu_ns, q_was_scored) =
            if let Some(&(cached, cached_rank)) = terminal_scores.get(&initial_assignment) {
                (cached, cached_rank, PolicyCosts::default(), 0, false)
            } else {
                let q_started = Instant::now();
                let result = policy.q_terminal(SelectorInput {
                    task_id: &task.id,
                    features,
                    assignment: &initial_assignment,
                })?;
                let elapsed = nanos(q_started.elapsed());
                let ranking_score = selector_rank(&result)?;
                terminal_scores.insert(initial_assignment.clone(), (result.value, ranking_score));
                selector_calls += 1;
                (result.value, ranking_score, result.costs, elapsed, true)
            };
        initial_selection_scores.push(serializable_rank(ranking_score));
        let (v, v_costs, v_cpu_ns) = if value_enabled {
            let v_started = Instant::now();
            let result = policy.v_reach(ValueInput {
                features,
                task,
                assignment: &initial_assignment,
                latent_state: &latent,
                remaining_budget: base.budget,
                depth: 0,
            })?;
            reach_value_calls += 1;
            (result.value, result.costs, nanos(v_started.elapsed()))
        } else {
            (0.0, PolicyCosts::default(), 0)
        };
        require_finite(q, "Q_terminal")?;
        if value_enabled {
            require_finite(v, "V_reach")?;
        }
        costs_initial.value_calls += u64::from(q_was_scored) + u64::from(value_enabled);
        add_policy_costs(&mut costs_initial, q_costs);
        add_policy_costs(&mut costs_initial, v_costs);
        costs_initial.cpu_active_ns += q_cpu_ns + v_cpu_ns;
        if !initial_particles.is_empty() {
            costs_initial.selection_comparisons += 1;
        }
        if ranking_score > selected_score {
            selected_score = ranking_score;
            selected_q = q;
            selected_initial = Some(u32::from(id));
        }
        initial_particles.push(InitialParticle {
            particle_id: u32::from(id),
            ancestry_id: u64::from(id),
            assignment: initial_assignment.clone(),
            canonical_key: canonical_initial.clone(),
            latent_state: latent.clone(),
            rng_state: particle_rng.state,
            q_terminal: q,
            v_reach: v,
        });
        particles.push(Particle {
            id: u32::from(id),
            parent_particle_id: None,
            ancestry_id: u64::from(id),
            assignment: initial_assignment.clone(),
            latent,
            rng: particle_rng,
            depth: 0,
            last_event: None,
            value: v,
            allocations_since_spawn: 0,
            alive: true,
            retired_by_merge: false,
        });
    }
    let header = TraceHeader {
        schema: "r1-stage1-hookable-trace-v1".to_owned(),
        trace_id: trace_id(task, &config, &initial_assignment),
        task_id: task.id.clone(),
        family_id: task.family_id.clone(),
        config: base.clone(),
        proposal_mode: proposal_mode(base.arm),
        initial_particles,
        initial_costs: costs_initial.clone(),
        initial_completion_active_ns: costs_initial
            .cpu_active_ns
            .saturating_add(costs_initial.gpu_active_ns),
        initial_completion_wall_ns: nanos(start.elapsed()),
        canonical_merge_public: matches!(config.merge_mode, MergeMode::CanonicalAssignment)
            && task.role_anonymous,
        public_symmetry_group_size: group.len() as u64,
        timing_kind: "measured_stage1_hook_runner".to_owned(),
        timing_granularity: "per_expansion_completion_aggregate".to_owned(),
    };
    let mut ledger = OperationLedger {
        peak_live_particles: u32::from(count),
        ..OperationLedger::default()
    };
    charge_initial(&mut ledger, &costs_initial);
    let initial_rep = Representative {
        particle_id: 0,
        event_index: None,
        initial_id: Some(0),
        value: particles[0].value,
        particle: particles[0].clone(),
    };
    let mut raw_seen = HashMap::<Vec<u8>, Representative>::new();
    let mut canonical_seen = HashMap::<Vec<u8>, Representative>::new();
    raw_seen.insert(initial_assignment, initial_rep.clone());
    canonical_seen.insert(canonical_initial, initial_rep);
    let mut dynamic_seen = HashSet::<DynamicKey>::new();
    for particle in &particles {
        dynamic_seen.insert(DynamicKey::new(particle, base.budget));
    }
    let mut events = Vec::<TraceEvent>::with_capacity(base.budget.min(65_536) as usize);
    let mut event_diagnostics = Vec::with_capacity(base.budget.min(65_536) as usize);
    let mut cursor = 0u32;

    for expansion in 1..=base.budget {
        let event_start = Instant::now();
        let nominal_id = ((expansion - 1) % u64::from(count)) as u32;
        let nominal_redirected = particles
            .iter()
            .find(|item| item.id == nominal_id)
            .is_some_and(|item| item.retired_by_merge);
        if nominal_redirected {
            ledger.redirected_future_expansions += 1;
        }
        let (chosen_index, value_based_allocation) = match config.allocation_policy {
            SearchAllocationPolicy::StandardRoundRobin if base.arm != Arm::Particle => {
                choose_round_robin(&particles, &mut cursor, count).map(|index| (index, false))
            }
            SearchAllocationPolicy::StandardRoundRobin => {
                if config.value_refresh_policy == ValueRefreshPolicy::ResampleBoundary {
                    choose_particle_round_robin(
                        &particles,
                        base.minimum_particle_budget,
                        &mut cursor,
                        width,
                    )
                    .map(|index| (index, false))
                } else {
                    choose_particle(&particles, base.minimum_particle_budget)
                }
            }
            SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget } => {
                // Delayed particles remain at their own seeded initial state; they are not
                // copied from the completed spine when the schedule switches phases.
                let target_id = if expansion <= spine_budget {
                    0
                } else {
                    1 + ((expansion - spine_budget - 1) % u64::from(count - 1)) as u32
                };
                particles
                    .iter()
                    .position(|particle| particle.id == target_id && particle.alive)
                    .map(|index| (index, false))
            }
            SearchAllocationPolicy::ForkFromSpineThenWidth { spine_budget } => {
                if expansion == spine_budget + 1 {
                    fork_particles_at_spine(&mut particles, spine_budget)?;
                }
                let target_id = if expansion <= spine_budget {
                    0
                } else {
                    1 + ((expansion - spine_budget - 1) % u64::from(count - 1)) as u32
                };
                particles
                    .iter()
                    .position(|particle| particle.id == target_id && particle.alive)
                    .map(|index| (index, false))
            }
        }
        .ok_or_else(|| SearchError::InvalidConfig("all particles were retired".to_owned()))?;
        let uses_scheduler_allocation = base.arm == Arm::Particle
            || config.allocation_policy != SearchAllocationPolicy::StandardRoundRobin;
        let scheduler_slot_mismatch = particles[chosen_index].id != nominal_id;
        let non_nominal = base.arm == Arm::Particle && scheduler_slot_mismatch;
        let mut particle = particles[chosen_index].clone();
        let before_assignment = particle.assignment.clone();
        let before_latent = particle.latent.clone();
        let rng_before = particle.rng.state;
        let remaining_before = base.budget - expansion + 1;
        let remaining_after = base.budget - expansion;
        let candidates = legal_edits(&particle.assignment, task.n, task.k);
        if candidates.is_empty() {
            return Err(SearchError::InvalidConfig(
                "state has no legal edit".to_owned(),
            ));
        }
        let strategy = strategy(base.arm);
        let scores = match strategy {
            ProposalStrategy::UniformSample => PolicyScores {
                logits: vec![0.0; candidates.len()],
                costs: PolicyCosts::default(),
            },
            _ => policy.score_edits(
                TransitionInput {
                    features,
                    task,
                    assignment: &particle.assignment,
                    latent_state: &particle.latent,
                    remaining_budget: remaining_before,
                    strategy,
                },
                &candidates,
            )?,
        };
        validate_scores(&scores, candidates.len())?;
        let (choice_index, log_probability) = sample_action(
            strategy,
            &scores.logits,
            config.learned_sample_temperature,
            &mut particle.rng,
        )?;
        let edit = candidates[choice_index];
        let mut transition_policy_costs = scores.costs;
        if strategy != ProposalStrategy::UniformSample {
            let latent_update = policy.advance_latent(
                TransitionInput {
                    features,
                    task,
                    assignment: &particle.assignment,
                    latent_state: &particle.latent,
                    remaining_budget: remaining_before,
                    strategy,
                },
                edit,
            )?;
            validate_latent_state(&latent_update.next_state, usize::from(base.latent_dim))?;
            combine_policy_costs(&mut transition_policy_costs, latent_update.costs);
            particle.latent = latent_update.next_state;
        }
        particle.assignment[usize::from(edit.entity)] = edit.new_role;
        particle.depth = particle.depth.saturating_add(1);
        particle.allocations_since_spawn = particle.allocations_since_spawn.saturating_add(1);
        let canonical_key = canonical_assignment(&particle.assignment, &group);
        let (q, ranking_score, q_costs, q_was_scored) =
            if let Some(&(cached, cached_rank)) = terminal_scores.get(&particle.assignment) {
                (cached, cached_rank, PolicyCosts::default(), false)
            } else {
                let q_started = Instant::now();
                let result = policy.q_terminal(SelectorInput {
                    task_id: &task.id,
                    features,
                    assignment: &particle.assignment,
                })?;
                let _q_cpu = nanos(q_started.elapsed());
                let ranking_score = selector_rank(&result)?;
                terminal_scores.insert(particle.assignment.clone(), (result.value, ranking_score));
                selector_calls += 1;
                (result.value, ranking_score, result.costs, true)
            };
        event_selection_scores.push(serializable_rank(ranking_score));
        let (value, value_costs) = if value_enabled {
            let result = policy.v_reach(ValueInput {
                features,
                task,
                assignment: &particle.assignment,
                latent_state: &particle.latent,
                remaining_budget: remaining_after,
                depth: particle.depth,
            })?;
            reach_value_calls += 1;
            (result.value, result.costs)
        } else {
            (0.0, PolicyCosts::default())
        };
        require_finite(q, "Q_terminal")?;
        if value_enabled {
            require_finite(value, "V_reach")?;
        }
        if ranking_score > selected_score {
            selected_score = ranking_score;
            selected_q = q;
            selected_initial = None;
            selected_event = Some(expansion - 1);
        }
        let event_index = expansion - 1;
        particle.value = value;
        let parent_event_index = particle.last_event;
        particle.last_event = Some(event_index);
        let transition = particle.clone();
        if let Some(slot) = particles.iter_mut().find(|item| item.id == particle.id) {
            *slot = particle.clone();
        }
        let mut refreshed_value_calls = 0u64;
        let mut refreshed_value_costs = PolicyCosts::default();
        let refresh_live_values = match config.value_refresh_policy {
            ValueRefreshPolicy::CachedTransition => false,
            ValueRefreshPolicy::EveryExpansion => true,
            ValueRefreshPolicy::ResampleBoundary => {
                let resample_due = base.arm == Arm::Particle
                    && expansion < base.budget
                    && expansion % base.resample_period == 0;
                let live_count = particles.iter().filter(|item| item.alive).count();
                let replacement_ready = live_count < usize::from(width)
                    || particles.iter().any(|item| {
                        item.alive && item.allocations_since_spawn >= base.minimum_particle_budget
                    });
                resample_due && replacement_ready
            }
        };
        if value_enabled && refresh_live_values {
            for live in particles
                .iter_mut()
                .filter(|item| item.alive && item.id != transition.id)
            {
                let result = policy.v_reach(ValueInput {
                    features,
                    task,
                    assignment: &live.assignment,
                    latent_state: &live.latent,
                    remaining_budget: remaining_after,
                    depth: live.depth,
                })?;
                require_finite(result.value, "V_reach")?;
                live.value = result.value;
                refreshed_value_calls += 1;
                reach_value_calls += 1;
                combine_policy_costs(&mut refreshed_value_costs, result.costs);
            }
        }
        let raw_duplicate = raw_seen.get(&transition.assignment).cloned().filter(|rep| {
            particles
                .iter()
                .any(|item| item.id == rep.particle_id && item.alive)
        });
        let canonical_duplicate = canonical_seen.get(&canonical_key).cloned().filter(|rep| {
            particles
                .iter()
                .any(|item| item.id == rep.particle_id && item.alive)
        });
        let strict_key = DynamicKey::new(&transition, remaining_after);
        let strict_duplicate = dynamic_seen.contains(&strict_key);
        dynamic_seen.insert(strict_key);
        let selected_rep = match config.merge_mode {
            MergeMode::None => None,
            MergeMode::RawAssignment => raw_duplicate.clone(),
            MergeMode::CanonicalAssignment => canonical_duplicate.clone(),
            MergeMode::StrictDynamicState => {
                if strict_duplicate {
                    raw_duplicate.clone().filter(|rep| {
                        DynamicKey::new(&rep.particle, remaining_after)
                            == DynamicKey::new(&transition, remaining_after)
                    })
                } else {
                    None
                }
            }
        };
        let mut raw_merge = false;
        let mut canonical_merge = false;
        let mut strict_merge = false;
        let mut representative = None;
        let mut merge_loser = None;
        let mut merge_kept = None;
        let mut merge_retired_particle_id = None;
        if let Some(mut previous) = selected_rep {
            if value_enabled && config.value_refresh_policy != ValueRefreshPolicy::CachedTransition
            {
                let result = policy.v_reach(ValueInput {
                    features,
                    task,
                    assignment: &previous.particle.assignment,
                    latent_state: &previous.particle.latent,
                    remaining_budget: remaining_after,
                    depth: previous.particle.depth,
                })?;
                require_finite(result.value, "V_reach")?;
                previous.value = result.value;
                previous.particle.value = result.value;
                refreshed_value_calls += 1;
                reach_value_calls += 1;
                combine_policy_costs(&mut refreshed_value_costs, result.costs);
            }
            let candidate_wins = value > previous.value;
            let retained = if candidate_wins {
                Representative {
                    particle_id: transition.id,
                    event_index: Some(event_index),
                    initial_id: None,
                    value,
                    particle: transition.clone(),
                }
            } else {
                previous.clone()
            };
            let loser_snapshot = if candidate_wins {
                snapshot_particle(
                    &previous.particle,
                    previous.event_index,
                    previous.initial_id,
                )
            } else {
                snapshot_particle(&transition, Some(event_index), None)
            };
            let kept_snapshot = if candidate_wins {
                snapshot_particle(&transition, Some(event_index), None)
            } else {
                snapshot_particle(
                    &previous.particle,
                    previous.event_index,
                    previous.initial_id,
                )
            };
            merge_retired_particle_id = (loser_snapshot.particle_id != kept_snapshot.particle_id)
                .then_some(loser_snapshot.particle_id);
            merge_loser = Some(loser_snapshot);
            merge_kept = Some(kept_snapshot);
            match config.merge_mode {
                MergeMode::RawAssignment => raw_merge = true,
                MergeMode::CanonicalAssignment => canonical_merge = true,
                MergeMode::StrictDynamicState => strict_merge = true,
                MergeMode::None => {}
            }
            let retired = apply_merge(&mut particles, &mut particle, &previous, candidate_wins);
            debug_assert_eq!(retired, merge_retired_particle_id);
            representative = Some(retained.clone());
            if candidate_wins {
                raw_seen.insert(transition.assignment.clone(), retained.clone());
                canonical_seen.insert(canonical_key.clone(), retained);
            }
        } else {
            update_representatives(
                &mut raw_seen,
                &mut canonical_seen,
                &particles,
                &transition,
                event_index,
                &canonical_key,
                value,
            );
        }
        let mut resampling = None;
        if base.arm == Arm::Particle
            && expansion < base.budget
            && expansion % base.resample_period == 0
        {
            resampling = resample(
                &mut particles,
                stable_hash(&task.id, &task.family_id),
                expansion,
                width,
                event_index,
                base.minimum_particle_budget,
            );
        }
        let mut costs = OperationCosts {
            proposal_calls: 1,
            logits_scored: transition_policy_costs.logits_scored,
            value_calls: u64::from(q_was_scored) + u64::from(value_enabled) + refreshed_value_calls,
            encoder_forward_calls: transition_policy_costs.encoder_forward_calls,
            encoder_tokens: transition_policy_costs.encoder_tokens,
            canonicalization_calls: 1,
            hash_probes: 3,
            merges: u64::from(raw_merge || canonical_merge || strict_merge),
            resampling_ops: u64::from(resampling.is_some()),
            allocation_decisions: u64::from(uses_scheduler_allocation),
            nonnominal_allocation_decisions: u64::from(non_nominal),
            selection_comparisons: 1,
            cpu_active_ns: nanos(event_start.elapsed()),
            gpu_active_ns: transition_policy_costs.gpu_active_ns,
        };
        add_policy_costs(&mut costs, q_costs);
        add_policy_costs(&mut costs, value_costs);
        add_policy_costs(&mut costs, refreshed_value_costs);
        let cumulative_active = ledger
            .cpu_active_ns
            .saturating_add(ledger.gpu_active_ns)
            .saturating_add(costs.cpu_active_ns)
            .saturating_add(costs.gpu_active_ns);
        let cumulative_wall = nanos(start.elapsed());
        let rep_particle = representative.as_ref().map(|rep| &rep.particle);
        let event = TraceEventDraft {
            event_index,
            global_expansion_index: expansion,
            particle_id: transition.id,
            nominal_slot_particle_id: nominal_id,
            nominal_slot_redirected: nominal_redirected,
            value_allocation_non_nominal: non_nominal,
            parent_particle_id: transition.parent_particle_id,
            parent_event_index,
            ancestry_id: transition.ancestry_id,
            particle_depth: transition.depth,
            assignment_before: before_assignment,
            assignment_after: transition.assignment.clone(),
            canonical_key: Some(canonical_key.clone()),
            latent_state_before: before_latent,
            latent_state_after: transition.latent.clone(),
            edit: Some(EditDraft {
                entity: edit.entity,
                new_role: edit.new_role,
            }),
            log_probability,
            v_reach: value,
            q_terminal: q,
            remaining_budget: remaining_after,
            selected: false,
            resampled: resampling.is_some(),
            resampling,
            raw_duplicate_detected: raw_duplicate.is_some(),
            canonical_duplicate_detected: canonical_duplicate.is_some(),
            full_dynamic_duplicate: strict_duplicate,
            raw_merge,
            canonical_merge,
            merge_representative_event: representative.as_ref().and_then(|rep| rep.event_index),
            merge_representative_initial_particle: representative
                .as_ref()
                .and_then(|rep| rep.initial_id),
            merge_representative_ancestry_id: representative
                .as_ref()
                .map(|rep| rep.particle.ancestry_id),
            representative_value: representative.as_ref().map(|rep| rep.value),
            merge_ancestry_ids: representative.as_ref().map(|rep| {
                if rep.particle.ancestry_id == transition.ancestry_id {
                    vec![transition.ancestry_id]
                } else {
                    vec![transition.ancestry_id, rep.particle.ancestry_id]
                }
            }),
            merge_representative_latent_state: rep_particle.map(|rep| rep.latent.clone()),
            merge_latent_divergence_l2: rep_particle
                .map(|rep| latent_distance(&transition.latent, &rep.latent)),
            rng_state_before: rng_before,
            rng_state_after: transition.rng.state,
            costs: costs.clone(),
            cumulative_active_ns: cumulative_active,
            cumulative_wall_ns: cumulative_wall,
        };
        let mut event = event;
        event.costs = costs.clone();
        events.push(event.into_trace_event()?);
        event_diagnostics.push(Stage1TraceEventDiagnostic {
            scheduler_slot_mismatch,
            value_based_allocation,
            merge_loser,
            merge_kept,
            merge_retired_particle_id,
        });
        charge(&mut ledger, &costs);
        ledger.peak_live_particles = ledger
            .peak_live_particles
            .max(particles.iter().filter(|item| item.alive).count() as u32);
    }

    if let Some(index) = selected_event {
        if let Some(event) = events.get_mut(index as usize) {
            event.selected = true;
        }
    }
    ledger.end_to_end_wall_ns = nanos(start.elapsed());
    let mut trace = RunTrace {
        header,
        events,
        ledger,
        selected_event,
        selected_initial_particle: selected_initial,
        selected_q_terminal: selected_q,
    };
    trace.ledger.trace_bytes_estimate = serde_json::to_vec(&(&trace, &event_diagnostics))
        .map(|bytes| bytes.len() as u64)
        .unwrap_or_default();
    Ok(Stage1Run {
        trace,
        manifest: Stage1RunManifest {
            schema: "r1-stage1-run-manifest-v4".to_owned(),
            arm: base.arm,
            merge_mode: config.merge_mode,
            proposal_id: config.proposal_id,
            selector_id: config.selector_id,
            value_id: config.value_id,
            learned_sample_temperature: (strategy(base.arm) == ProposalStrategy::LearnedSample)
                .then_some(config.learned_sample_temperature),
            selector_surface: "(H,h_global,a); no latent or budget".to_owned(),
            value_surface: "(H,h_global,a,s,b_remaining); evaluated only when used for merge retention or particle allocation".to_owned(),
            value_scoring_policy: if !value_enabled {
                "not-applicable".to_owned()
            } else {
                match config.value_refresh_policy {
                    ValueRefreshPolicy::CachedTransition => {
                        "cached-transition-score-v01".to_owned()
                    }
                    ValueRefreshPolicy::EveryExpansion => {
                        "same-horizon-live-and-merge-refresh-v01".to_owned()
                    }
                    ValueRefreshPolicy::ResampleBoundary => {
                        "resample-boundary-live-and-merge-refresh-v01".to_owned()
                    }
                }
            },
            particle_allocation_policy: if base.arm != Arm::Particle {
                "not-applicable".to_owned()
            } else if config.value_refresh_policy == ValueRefreshPolicy::ResampleBoundary {
                "round-robin-between-resample-boundaries-v01".to_owned()
            } else {
                "greedy-max-value-after-minimum-allocation-v01".to_owned()
            },
            search_allocation_policy: config.allocation_policy,
            allocation_trace_semantics: "Stage1 trace v2 records scheduler_slot_mismatch for any actual particle differing from the nominal round-robin slot and value_based_allocation only when the V_reach max-value fallback selected a particle; root-delayed particles remain at the initial assignment; forked particles copy the spine assignment, latent state, depth, and last-event pointer, receive a unique deterministic child ancestry, reset allocation age, and keep their independent pre-seeded RNG streams; initial_particles remains the pre-fork seed snapshot".to_owned(),
            value_evaluated: value_enabled,
            selector_calls,
            value_calls: reach_value_calls,
        },
        event_diagnostics,
        initial_selection_scores,
        event_selection_scores,
    })
}

#[cfg(test)]
#[path = "scheduler/merge_diagnostics_tests.rs"]
mod merge_diagnostics_tests;

#[path = "scheduler/support.rs"]
mod support;
use support::*;

#[cfg(test)]
mod initial_assignment_tests;
