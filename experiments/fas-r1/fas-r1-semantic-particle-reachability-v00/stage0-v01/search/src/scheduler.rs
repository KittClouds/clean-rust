use crate::policy::{
    apply_edit, propose, q_terminal_stub, seed_mix, update_latent, v_reach_stub, DeterministicRng,
};
use crate::types::{
    Arm, InitialParticle, OperationCosts, OperationLedger, ResamplingRecord, RunConfig, RunTrace,
    TraceEvent, TraceHeader,
};
use hashbrown::{HashMap, HashSet};
use r1_world::{canonical_assignment, InferenceTask};
use sha2::{Digest, Sha256};
use std::time::Instant;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SearchError {
    InvalidConfig(String),
    ReplayInput(String),
}

impl std::fmt::Display for SearchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidConfig(message) => write!(f, "invalid search config: {message}"),
            Self::ReplayInput(message) => write!(f, "invalid replay input: {message}"),
        }
    }
}

impl std::error::Error for SearchError {}

#[derive(Clone)]
struct Particle {
    id: u32,
    parent_particle_id: Option<u32>,
    ancestry_id: u64,
    assignment: Vec<u8>,
    latent_state: Vec<f32>,
    rng: DeterministicRng,
    depth: u32,
    last_event: Option<u64>,
    v_reach: f32,
    allocations_since_spawn: u64,
    retired_by_merge: bool,
    alive: bool,
}

#[derive(Clone)]
struct Representative {
    particle_id: u32,
    event_index: Option<u64>,
    initial_particle_id: Option<u32>,
    value: f32,
    particle: Particle,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct FullDynamicKey {
    assignment: Vec<u8>,
    latent_bits: Vec<u32>,
    remaining_budget: u64,
    rng_state: u64,
}

impl FullDynamicKey {
    fn new(assignment: &[u8], latent_state: &[f32], remaining_budget: u64, rng_state: u64) -> Self {
        Self {
            assignment: assignment.to_vec(),
            latent_bits: latent_state.iter().map(|value| value.to_bits()).collect(),
            remaining_budget,
            rng_state,
        }
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum MergeRule {
    None,
    Raw,
    Canonical,
}

/// Run a complete model-free trace from an inference projection.
///
/// This function receives no typed clauses, solution set, validator, or solver
/// metadata. Every loop iteration consumes exactly one expansion, including
/// repeated and later-merged states.
pub fn run(task: &InferenceTask, config: RunConfig) -> Result<RunTrace, SearchError> {
    validate_config(task, &config)?;
    let started = Instant::now();
    let requested_width = match config.arm {
        Arm::Depth | Arm::SampledDepth => 1,
        _ => config.width,
    };
    let particle_count = if config.budget == 0 {
        1
    } else {
        requested_width
            .min(config.budget.min(u64::from(u16::MAX)) as u16)
            .max(1)
    };
    if task.role_anonymous && task.k > 8 {
        return Err(SearchError::InvalidConfig(
            "role-anonymous public symmetry diagnostics require k <= 8".to_owned(),
        ));
    }
    let mut initial_costs = OperationCosts::default();
    let group_started = Instant::now();
    let public_group = public_role_group(task.k, task.role_anonymous);
    initial_costs.cpu_active_ns += nanos(group_started.elapsed());
    let proposal_mode = config.proposal_mode();
    let initial_assignment = make_initial_assignment(task, config.seed);
    let task_hash = stable_task_hash(&task.id, &task.family_id);
    let mut full_dynamic_seen = HashSet::<FullDynamicKey>::new();
    let canonical_started = Instant::now();
    let canonical_initial = canonical_assignment(&initial_assignment, &public_group);
    initial_costs.canonicalization_calls = 1;
    initial_costs.cpu_active_ns += nanos(canonical_started.elapsed());
    let mut initial_particles = Vec::with_capacity(usize::from(particle_count));
    let mut particles = Vec::with_capacity(usize::from(particle_count));
    let mut selected_event = None;
    let mut selected_initial_particle = None;
    let mut selected_q_terminal = f32::NEG_INFINITY;

    for particle_id in 0..particle_count {
        let op_started = Instant::now();
        let rng = DeterministicRng::new(seed_mix(config.seed ^ task_hash, u32::from(particle_id)));
        let latent_state = vec![0.0; usize::from(config.latent_dim)];
        let q_terminal = q_terminal_stub(&initial_assignment, task.k);
        let v_reach = v_reach_stub(&initial_assignment, &latent_state, config.budget, 0);
        initial_costs.value_calls += 2;
        if !initial_particles.is_empty() {
            initial_costs.selection_comparisons += 1;
        }
        if q_terminal > selected_q_terminal {
            selected_q_terminal = q_terminal;
            selected_initial_particle = Some(u32::from(particle_id));
        }
        initial_particles.push(InitialParticle {
            particle_id: u32::from(particle_id),
            ancestry_id: u64::from(particle_id),
            assignment: initial_assignment.clone(),
            canonical_key: canonical_initial.clone(),
            latent_state: latent_state.clone(),
            rng_state: rng.state,
            q_terminal,
            v_reach,
        });
        particles.push(Particle {
            id: u32::from(particle_id),
            parent_particle_id: None,
            ancestry_id: u64::from(particle_id),
            assignment: initial_assignment.clone(),
            latent_state,
            rng,
            depth: 0,
            last_event: None,
            v_reach,
            allocations_since_spawn: 0,
            retired_by_merge: false,
            alive: true,
        });
        full_dynamic_seen.insert(FullDynamicKey::new(
            &initial_assignment,
            &particles.last().expect("just pushed particle").latent_state,
            config.budget,
            rng.state,
        ));
        initial_costs.hash_probes += 1;
        initial_costs.cpu_active_ns += nanos(op_started.elapsed());
    }
    let initial_completion_active_ns = initial_costs.cpu_active_ns;
    let initial_completion_wall_ns = nanos(started.elapsed());
    let mut ledger = OperationLedger {
        peak_live_particles: u32::from(particle_count),
        ..OperationLedger::default()
    };

    let mut header = TraceHeader {
        schema: "r1-transition-trace-v1".to_owned(),
        trace_id: trace_id(task, &config, &initial_assignment),
        task_id: task.id.clone(),
        family_id: task.family_id.clone(),
        config: config.clone(),
        proposal_mode,
        initial_particles,
        initial_costs,
        initial_completion_active_ns,
        initial_completion_wall_ns,
        canonical_merge_public: matches!(config.arm, Arm::CanonicalMerge | Arm::Particle)
            && task.role_anonymous,
        public_symmetry_group_size: public_group.len() as u64,
        timing_kind: "measured_stage0_cpu_and_wall".to_owned(),
        timing_granularity: "per_expansion_completion_aggregate".to_owned(),
    };

    let mut events = Vec::with_capacity(config.budget.min(65_536) as usize);
    let mut raw_seen = HashMap::<Vec<u8>, Representative>::new();
    let mut canonical_seen = HashMap::<Vec<u8>, Representative>::new();
    let initial_rep = Representative {
        particle_id: 0,
        event_index: None,
        initial_particle_id: Some(0),
        value: particles[0].v_reach,
        particle: particles[0].clone(),
    };
    let map_started = Instant::now();
    raw_seen.insert(initial_assignment.clone(), initial_rep.clone());
    canonical_seen.insert(canonical_initial, initial_rep);
    let map_costs = OperationCosts {
        hash_probes: 2,
        cpu_active_ns: nanos(map_started.elapsed()),
        ..OperationCosts::default()
    };
    header.initial_costs.hash_probes += map_costs.hash_probes;
    header.initial_costs.cpu_active_ns += map_costs.cpu_active_ns;
    header.initial_completion_active_ns += map_costs.cpu_active_ns;
    header.initial_completion_wall_ns = nanos(started.elapsed());
    ledger.charge_initial(&header.initial_costs);
    let merge_rule = merge_rule(config.arm);
    let mut nominal_cursor = 0u32;

    for global_index in 1..=config.budget {
        let event_started = Instant::now();
        let nominal_slot_particle_id = ((global_index - 1) % u64::from(particle_count)) as u32;
        let nominal_slot_redirected = particles
            .iter()
            .find(|particle| particle.id == nominal_slot_particle_id)
            .is_some_and(|particle| particle.retired_by_merge);
        if nominal_slot_redirected {
            ledger.redirected_future_expansions += 1;
        }
        let chosen_index = if config.arm == Arm::Particle {
            choose_particle_value_guided(&particles, config.minimum_particle_budget)
        } else {
            choose_nominal_particle(&particles, &mut nominal_cursor, particle_count)
        }
        .ok_or_else(|| SearchError::ReplayInput("particle pool became empty".to_owned()))?;
        let value_allocation_non_nominal =
            config.arm == Arm::Particle && particles[chosen_index].id != nominal_slot_particle_id;

        let mut particle = particles[chosen_index].clone();
        let parent_event_index = particle.last_event;
        let rng_state_before = particle.rng.state;
        let assignment_before = particle.assignment.clone();
        let latent_state_before = particle.latent_state.clone();
        let remaining_budget = config.budget - global_index;
        let choice = propose(
            proposal_mode,
            &particle.assignment,
            &particle.latent_state,
            task.n,
            task.k,
            &mut particle.rng,
        )
        .ok_or_else(|| {
            SearchError::ReplayInput(
                "policy produced no legal edit for a searchable state".to_owned(),
            )
        })?;
        let edit = Some(choice.edit);
        let log_probability = choice.log_probability;
        let logits_scored = choice.logits_scored;
        apply_edit(&mut particle.assignment, choice.edit);
        update_latent(&mut particle.latent_state, choice.edit, particle.depth + 1);
        particle.depth = particle.depth.saturating_add(1);
        particle.allocations_since_spawn = particle.allocations_since_spawn.saturating_add(1);

        let canonical_key = canonical_assignment(&particle.assignment, &public_group);
        let v_reach = v_reach_stub(
            &particle.assignment,
            &particle.latent_state,
            remaining_budget,
            particle.depth,
        );
        let q_terminal = q_terminal_stub(&particle.assignment, task.k);
        if q_terminal > selected_q_terminal {
            selected_q_terminal = q_terminal;
            selected_initial_particle = None;
            selected_event = Some(global_index - 1);
        }
        particle.v_reach = v_reach;
        let transition_particle_id = particle.id;
        let transition_parent_particle_id = particle.parent_particle_id;
        let transition_ancestry_id = particle.ancestry_id;
        let transition_depth = particle.depth;
        let transition_assignment_after = particle.assignment.clone();
        let transition_latent_after = particle.latent_state.clone();
        let transition_rng_state_after = particle.rng.state;
        let full_dynamic_duplicate = !full_dynamic_seen.insert(FullDynamicKey::new(
            &particle.assignment,
            &particle.latent_state,
            remaining_budget,
            particle.rng.state,
        ));
        let raw_duplicate = raw_seen.get(&particle.assignment).cloned();
        let canonical_duplicate = canonical_seen.get(&canonical_key).cloned();
        let event_index = global_index - 1;
        particle.last_event = Some(event_index);
        let selected_duplicate = match merge_rule {
            MergeRule::None => None,
            MergeRule::Raw => raw_duplicate
                .clone()
                .filter(|rep| representative_is_live(rep, &particles)),
            MergeRule::Canonical => canonical_duplicate
                .clone()
                .filter(|rep| representative_is_live(rep, &particles)),
        };
        let (raw_merge, canonical_merge, representative, victim_particle) = resolve_merge(
            selected_duplicate.clone(),
            merge_rule,
            &particle,
            event_index,
            raw_duplicate.as_ref(),
            canonical_duplicate.as_ref(),
        );

        let mut costs = OperationCosts {
            proposal_calls: 1,
            logits_scored,
            value_calls: 2,
            canonicalization_calls: 1,
            hash_probes: 3,
            allocation_decisions: u64::from(config.arm == Arm::Particle),
            nonnominal_allocation_decisions: u64::from(value_allocation_non_nominal),
            selection_comparisons: 1,
            ..OperationCosts::default()
        };
        if raw_merge || canonical_merge {
            costs.merges = 1;
        }

        // Preserve the higher-valued representative snapshot when an
        // assignment-level merge returns to the current particle's own prior
        // state. Other losing particles retire and free only future slots.
        let candidate_is_representative = representative
            .as_ref()
            .is_some_and(|rep| rep.event_index == Some(event_index));
        install_merge_result(
            &mut particles,
            &mut particle,
            representative.as_ref(),
            victim_particle,
            candidate_is_representative,
        );
        if selected_duplicate.is_none() || candidate_is_representative {
            refresh_representative(
                &mut raw_seen,
                &mut canonical_seen,
                &particle,
                event_index,
                &canonical_key,
                v_reach,
                &particles,
            );
        }

        let resampling = if config.arm == Arm::Particle
            && global_index < config.budget
            && global_index % config.resample_period == 0
        {
            resample_particle(
                &mut particles,
                task_hash,
                global_index,
                requested_width,
                event_index,
                config.minimum_particle_budget,
            )
        } else {
            None
        };
        let resampled = resampling.is_some();
        if resampled {
            costs.resampling_ops = 1;
        }
        costs.cpu_active_ns = nanos(event_started.elapsed());
        let cumulative_active = ledger.cpu_active_ns + costs.cpu_active_ns;
        let cumulative_wall = nanos(started.elapsed());
        let merge_latent_divergence_l2 = representative
            .as_ref()
            .map(|rep| latent_divergence_l2(&transition_latent_after, &rep.particle.latent_state));
        let event = TraceEvent {
            event_index,
            global_expansion_index: global_index,
            particle_id: transition_particle_id,
            nominal_slot_particle_id,
            nominal_slot_redirected,
            value_allocation_non_nominal,
            parent_particle_id: transition_parent_particle_id,
            parent_event_index,
            ancestry_id: transition_ancestry_id,
            particle_depth: transition_depth,
            assignment_before,
            assignment_after: transition_assignment_after,
            canonical_key: Some(canonical_key),
            latent_state_before,
            latent_state_after: transition_latent_after,
            edit,
            log_probability,
            v_reach,
            q_terminal,
            remaining_budget,
            selected: false,
            resampled,
            resampling,
            raw_duplicate_detected: raw_duplicate.is_some(),
            canonical_duplicate_detected: canonical_duplicate.is_some(),
            full_dynamic_duplicate,
            raw_merge,
            canonical_merge,
            merge_representative_event: representative.as_ref().and_then(|rep| rep.event_index),
            merge_representative_initial_particle: representative
                .as_ref()
                .and_then(|rep| rep.initial_particle_id),
            merge_representative_ancestry_id: representative
                .as_ref()
                .map(|rep| rep.particle.ancestry_id),
            representative_value: representative.as_ref().map(|rep| rep.value),
            merge_ancestry_ids: representative.as_ref().map(|rep| {
                if rep.particle.ancestry_id == transition_ancestry_id {
                    vec![transition_ancestry_id]
                } else {
                    vec![transition_ancestry_id, rep.particle.ancestry_id]
                }
            }),
            merge_representative_latent_state: representative
                .as_ref()
                .map(|rep| rep.particle.latent_state.clone()),
            merge_latent_divergence_l2,
            rng_state_before,
            rng_state_after: transition_rng_state_after,
            costs: costs.clone(),
            cumulative_active_ns: cumulative_active,
            cumulative_wall_ns: cumulative_wall,
        };
        events.push(event);
        ledger.charge(&costs);
        ledger.peak_live_particles = ledger
            .peak_live_particles
            .max(particles.iter().filter(|candidate| candidate.alive).count() as u32);
    }

    if let Some(index) = selected_event {
        if let Some(event) = events.get_mut(index as usize) {
            event.selected = true;
        }
    }
    ledger.end_to_end_wall_ns = nanos(started.elapsed());
    let mut trace = RunTrace {
        header,
        events,
        ledger,
        selected_event,
        selected_initial_particle,
        selected_q_terminal,
    };
    trace.ledger.trace_bytes_estimate = serde_json::to_vec(&trace)
        .map(|bytes| bytes.len() as u64)
        .unwrap_or_default();
    Ok(trace)
}

fn validate_config(task: &InferenceTask, config: &RunConfig) -> Result<(), SearchError> {
    if task.n == 0 || task.k < 2 {
        return Err(SearchError::InvalidConfig(
            "n must be positive and k must be at least 2".to_owned(),
        ));
    }
    if config.width == 0 {
        return Err(SearchError::InvalidConfig(
            "width must be positive".to_owned(),
        ));
    }
    if config.latent_dim == 0 {
        return Err(SearchError::InvalidConfig(
            "latent_dim must be positive".to_owned(),
        ));
    }
    if matches!(config.arm, Arm::CanonicalMerge | Arm::Particle) {
        if !task.role_anonymous {
            return Err(SearchError::InvalidConfig(
                "canonical arms require the public role-anonymous grammar".to_owned(),
            ));
        }
        if task.k > 8 {
            return Err(SearchError::InvalidConfig(
                "public role permutation group is capped at k <= 8".to_owned(),
            ));
        }
    }
    if config.arm == Arm::Particle && config.resample_period == 0 {
        return Err(SearchError::InvalidConfig(
            "particle resample_period must be positive".to_owned(),
        ));
    }
    if config.arm == Arm::Particle && config.minimum_particle_budget == 0 {
        return Err(SearchError::InvalidConfig(
            "particle minimum allocation must be nonzero".to_owned(),
        ));
    }
    Ok(())
}

fn merge_rule(arm: Arm) -> MergeRule {
    match arm {
        Arm::MergedWidth => MergeRule::Raw,
        Arm::CanonicalMerge | Arm::Particle => MergeRule::Canonical,
        _ => MergeRule::None,
    }
}

fn resolve_merge(
    existing: Option<Representative>,
    rule: MergeRule,
    candidate: &Particle,
    event_index: u64,
    raw_duplicate: Option<&Representative>,
    canonical_duplicate: Option<&Representative>,
) -> (bool, bool, Option<Representative>, Option<u32>) {
    let Some(previous) = existing else {
        return (false, false, None, None);
    };
    let candidate_rep = Representative {
        particle_id: candidate.id,
        event_index: Some(event_index),
        initial_particle_id: None,
        value: candidate.v_reach,
        particle: candidate.clone(),
    };
    // Deterministic tie rule: retain the earlier state.
    let choose_candidate = candidate_rep.value > previous.value;
    let victim = if choose_candidate {
        (previous.particle_id != candidate.id).then_some(previous.particle_id)
    } else {
        Some(candidate.id)
    };
    let representative = if choose_candidate {
        Some(candidate_rep)
    } else {
        Some(previous)
    };
    (
        rule == MergeRule::Raw && raw_duplicate.is_some(),
        rule == MergeRule::Canonical && canonical_duplicate.is_some(),
        representative,
        victim,
    )
}

fn representative_is_live(rep: &Representative, particles: &[Particle]) -> bool {
    particles
        .iter()
        .any(|particle| particle.id == rep.particle_id && particle.alive)
}

fn refresh_representative(
    raw_seen: &mut HashMap<Vec<u8>, Representative>,
    canonical_seen: &mut HashMap<Vec<u8>, Representative>,
    particle: &Particle,
    event_index: u64,
    canonical_key: &[u8],
    value: f32,
    particles: &[Particle],
) {
    let representative = Representative {
        particle_id: particle.id,
        event_index: Some(event_index),
        initial_particle_id: None,
        value,
        particle: particle.clone(),
    };
    let raw_key = particle.assignment.clone();
    let replace_raw = raw_seen.get(&raw_key).is_none_or(|existing| {
        !representative_is_live(existing, particles) || value > existing.value
    });
    if replace_raw {
        raw_seen.insert(raw_key, representative.clone());
    }
    let canonical_key = canonical_key.to_vec();
    let replace_canonical = canonical_seen.get(&canonical_key).is_none_or(|existing| {
        !representative_is_live(existing, particles) || value > existing.value
    });
    if replace_canonical {
        canonical_seen.insert(canonical_key, representative);
    }
}

fn install_merge_result(
    particles: &mut [Particle],
    candidate: &mut Particle,
    representative: Option<&Representative>,
    victim_particle: Option<u32>,
    candidate_is_representative: bool,
) {
    match victim_particle {
        Some(victim_id) if victim_id == candidate.id => {
            if let Some(rep) = representative
                .filter(|rep| rep.particle_id != candidate.id && !candidate_is_representative)
            {
                candidate.alive = false;
                candidate.retired_by_merge = true;
                if let Some(slot) = particles
                    .iter_mut()
                    .find(|particle| particle.id == candidate.id)
                {
                    *slot = candidate.clone();
                }
                if let Some(slot) = particles
                    .iter_mut()
                    .find(|particle| particle.id == rep.particle_id)
                {
                    let allocation_age = slot.allocations_since_spawn;
                    let mut restored = rep.particle.clone();
                    restored.allocations_since_spawn = allocation_age;
                    restored.alive = true;
                    restored.retired_by_merge = false;
                    *slot = restored;
                }
                return;
            }
            if let Some(rep) = representative
                .filter(|rep| rep.particle_id == candidate.id && !candidate_is_representative)
            {
                let allocation_age = candidate.allocations_since_spawn;
                *candidate = rep.particle.clone();
                candidate.allocations_since_spawn = allocation_age;
                candidate.alive = true;
                candidate.retired_by_merge = false;
            } else {
                candidate.alive = false;
                candidate.retired_by_merge = true;
            }
            if let Some(slot) = particles
                .iter_mut()
                .find(|particle| particle.id == candidate.id)
            {
                *slot = candidate.clone();
            }
        }
        Some(victim_id) => {
            if let Some(victim) = particles
                .iter_mut()
                .find(|particle| particle.id == victim_id)
            {
                victim.alive = false;
                victim.retired_by_merge = true;
            }
            if let Some(slot) = particles
                .iter_mut()
                .find(|particle| particle.id == candidate.id)
            {
                *slot = candidate.clone();
            }
        }
        None => {
            if let Some(slot) = particles
                .iter_mut()
                .find(|particle| particle.id == candidate.id)
            {
                *slot = candidate.clone();
            }
        }
    }
}

fn choose_nominal_particle(
    particles: &[Particle],
    cursor: &mut u32,
    nominal_width: u16,
) -> Option<usize> {
    if !particles.iter().any(|particle| particle.alive) {
        return None;
    }
    let width = usize::from(nominal_width).max(1);
    let start_slot = (*cursor as usize) % width;
    *cursor = ((start_slot + 1) % width) as u32;
    for offset in 0..width {
        let id = ((start_slot + offset) % width) as u32;
        if let Some(index) = particles
            .iter()
            .position(|particle| particle.id == id && particle.alive)
        {
            return Some(index);
        }
    }
    particles.iter().position(|particle| particle.alive)
}

fn choose_particle_value_guided(particles: &[Particle], minimum_allocations: u64) -> Option<usize> {
    let mut live: Vec<(usize, &Particle)> = particles
        .iter()
        .enumerate()
        .filter(|(_, particle)| particle.alive)
        .collect();
    if live.is_empty() {
        return None;
    }
    if let Some((index, _)) = live
        .iter()
        .filter(|(_, particle)| particle.allocations_since_spawn < minimum_allocations)
        .min_by_key(|(_, particle)| (particle.allocations_since_spawn, particle.id))
    {
        return Some(*index);
    }
    live.sort_by(|(_, left), (_, right)| {
        right
            .v_reach
            .total_cmp(&left.v_reach)
            .then_with(|| left.id.cmp(&right.id))
    });
    live.first().map(|(index, _)| *index)
}

fn resample_particle(
    particles: &mut Vec<Particle>,
    task_hash: u64,
    global_index: u64,
    max_width: u16,
    event_index: u64,
    minimum_allocations: u64,
) -> Option<ResamplingRecord> {
    let live: Vec<(usize, &Particle)> = particles
        .iter()
        .enumerate()
        .filter(|(_, particle)| particle.alive)
        .collect();
    if live.is_empty() {
        return None;
    }
    let source_index = live
        .iter()
        .max_by(|(_, left), (_, right)| {
            left.v_reach
                .total_cmp(&right.v_reach)
                .then_with(|| right.id.cmp(&left.id))
        })
        .map(|(index, _)| *index)?;
    let source = particles[source_index].clone();
    let spawned_id = particles
        .iter()
        .map(|particle| particle.id)
        .max()
        .unwrap_or(0)
        + 1;
    let retired_id = if live.len() >= usize::from(max_width) && live.len() > 1 {
        live.iter()
            .filter(|(index, particle)| {
                *index != source_index && particle.allocations_since_spawn >= minimum_allocations
            })
            .min_by(|(_, left), (_, right)| {
                left.v_reach
                    .total_cmp(&right.v_reach)
                    .then_with(|| left.id.cmp(&right.id))
            })
            .map(|(_, particle)| particle.id)
    } else if live.len() >= usize::from(max_width) {
        return None;
    } else {
        None
    };
    if let Some(retired) = retired_id {
        if let Some(particle) = particles
            .iter_mut()
            .find(|candidate| candidate.id == retired)
        {
            particle.alive = false;
        }
    }
    let mut child = source.clone();
    child.id = spawned_id;
    child.parent_particle_id = Some(source.id);
    child.ancestry_id = source.ancestry_id
        ^ global_index.wrapping_mul(0x9E37_79B9_7F4A_7C15)
        ^ u64::from(spawned_id);
    child.rng = DeterministicRng::new(seed_mix(task_hash ^ global_index, spawned_id));
    child.allocations_since_spawn = 0;
    child.retired_by_merge = false;
    child.alive = true;
    particles.push(child.clone());
    Some(ResamplingRecord {
        source_particle_id: source.id,
        retired_particle_id: retired_id,
        spawned_particle_id: spawned_id,
        spawned_ancestry_id: child.ancestry_id,
        spawned_parent_event: source.last_event.or(Some(event_index)),
        spawned_assignment: child.assignment,
        spawned_latent_state: child.latent_state,
        spawned_rng_state: child.rng.state,
    })
}

fn make_initial_assignment(task: &InferenceTask, seed: u64) -> Vec<u8> {
    let mut rng = DeterministicRng::new(seed ^ stable_task_hash(&task.id, &task.family_id));
    (0..task.n)
        .map(|_| (rng.next_u64() % u64::from(task.k)) as u8)
        .collect()
}

fn public_role_group(k: u8, role_anonymous: bool) -> Vec<Vec<u8>> {
    if !role_anonymous {
        return vec![(0..k).collect()];
    }
    let mut current: Vec<u8> = (0..k).collect();
    let mut permutations = Vec::new();
    permute(&mut current, 0, &mut permutations);
    permutations
}

fn permute(values: &mut [u8], start: usize, output: &mut Vec<Vec<u8>>) {
    if start == values.len() {
        output.push(values.to_vec());
        return;
    }
    for index in start..values.len() {
        values.swap(start, index);
        permute(values, start + 1, output);
        values.swap(start, index);
    }
}

fn stable_task_hash(id: &str, family_id: &str) -> u64 {
    let mut hasher = Sha256::new();
    hasher.update(id.as_bytes());
    hasher.update([0xff]);
    hasher.update(family_id.as_bytes());
    let digest = hasher.finalize();
    u64::from_le_bytes(digest[..8].try_into().expect("fixed digest prefix"))
}

fn trace_id(task: &InferenceTask, config: &RunConfig, initial: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(task.id.as_bytes());
    hasher.update(task.family_id.as_bytes());
    hasher.update(serde_json::to_vec(config).unwrap_or_default());
    hasher.update(initial);
    let digest = hasher.finalize();
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn nanos(duration: std::time::Duration) -> u64 {
    duration.as_nanos().min(u128::from(u64::MAX)) as u64
}

fn latent_divergence_l2(left: &[f32], right: &[f32]) -> f32 {
    left.iter()
        .zip(right)
        .map(|(left, right)| (left - right).powi(2))
        .sum::<f32>()
        .sqrt()
}
