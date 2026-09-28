use super::*;

pub(super) fn validate_config(
    task: &InferenceTask,
    features: &SemanticFeatures,
    config: &Stage1RunConfig,
) -> Result<(), SearchError> {
    features
        .validate_for(task)
        .map_err(|error| SearchError::InvalidConfig(error.to_string()))?;
    let base = &config.base;
    if task.n == 0 || task.k < 2 {
        return Err(SearchError::InvalidConfig(
            "n must be positive and k must be at least two".to_owned(),
        ));
    }
    if base.width == 0 || base.latent_dim == 0 {
        return Err(SearchError::InvalidConfig(
            "width and latent_dim must be positive".to_owned(),
        ));
    }
    if config
        .initial_assignment
        .as_ref()
        .is_some_and(|assignment| {
            assignment.len() != usize::from(task.n) || assignment.iter().any(|role| *role >= task.k)
        })
    {
        return Err(SearchError::InvalidConfig(
            "explicit initial assignment must match n and use roles below k".to_owned(),
        ));
    }
    if !config.learned_sample_temperature.is_finite() || config.learned_sample_temperature <= 0.0 {
        return Err(SearchError::InvalidConfig(
            "learned-sample temperature must be finite and positive".to_owned(),
        ));
    }
    if base.arm == Arm::Particle && (base.resample_period == 0 || base.minimum_particle_budget == 0)
    {
        return Err(SearchError::InvalidConfig(
            "particle resampling period and minimum allocation must be positive".to_owned(),
        ));
    }
    if config.value_refresh_policy == ValueRefreshPolicy::ResampleBoundary
        && base.arm != Arm::Particle
    {
        return Err(SearchError::InvalidConfig(
            "resample-boundary value refresh requires the Particle arm".to_owned(),
        ));
    }
    let spine_budget = match config.allocation_policy {
        SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget }
        | SearchAllocationPolicy::ForkFromSpineThenWidth { spine_budget } => Some(spine_budget),
        SearchAllocationPolicy::StandardRoundRobin => None,
    };
    if let Some(spine_budget) = spine_budget {
        let fork_depth_exceeds_u32 = match config.allocation_policy {
            SearchAllocationPolicy::ForkFromSpineThenWidth { .. } => {
                let remaining = base.budget.saturating_sub(spine_budget);
                let branch_count = u64::from(base.width.saturating_sub(1).max(1));
                let max_branch_steps =
                    remaining / branch_count + u64::from(remaining % branch_count != 0);
                spine_budget.saturating_add(max_branch_steps) > u64::from(u32::MAX)
            }
            _ => false,
        };
        if base.arm != Arm::LearnedWidth
            || config.merge_mode != MergeMode::None
            || base.width < 2
            || spine_budget == 0
            || spine_budget >= base.budget
            || spine_budget >= u64::from(u32::MAX)
            || fork_depth_exceeds_u32
        {
            return Err(SearchError::InvalidConfig(
                "spine policies require LearnedWidth, no merging, width >= 2, a positive spine budget below budget/u32::MAX, and fork depth within u32".to_owned(),
            ));
        }
    }
    if config.merge_mode == MergeMode::CanonicalAssignment && (!task.role_anonymous || task.k > 8) {
        return Err(SearchError::InvalidConfig(
            "canonical merging requires public role anonymity and k <= 8".to_owned(),
        ));
    }
    if task.role_anonymous && task.k > 8 {
        return Err(SearchError::InvalidConfig(
            "public role permutation diagnostics require k <= 8".to_owned(),
        ));
    }
    Ok(())
}

pub(super) fn proposal_mode(arm: Arm) -> ProposalMode {
    match arm {
        Arm::Depth => ProposalMode::GreedyLearnedStub,
        Arm::RandomWidth => ProposalMode::UniformRandomStub,
        Arm::SampledDepth
        | Arm::LearnedWidth
        | Arm::MergedWidth
        | Arm::CanonicalMerge
        | Arm::Particle => ProposalMode::SampledLearnedStub,
    }
}

pub(super) fn strategy(arm: Arm) -> ProposalStrategy {
    match arm {
        Arm::Depth => ProposalStrategy::Greedy,
        Arm::RandomWidth => ProposalStrategy::UniformSample,
        Arm::SampledDepth
        | Arm::LearnedWidth
        | Arm::MergedWidth
        | Arm::CanonicalMerge
        | Arm::Particle => ProposalStrategy::LearnedSample,
    }
}

pub(super) fn legal_edits(assignment: &[u8], n: u16, k: u8) -> Vec<Edit> {
    let mut edits = Vec::with_capacity(usize::from(n) * usize::from(k.saturating_sub(1)));
    for entity in 0..n {
        let current = assignment[usize::from(entity)];
        for role in 0..k {
            if role != current {
                edits.push(Edit {
                    entity,
                    new_role: role,
                });
            }
        }
    }
    edits
}

pub(super) fn validate_scores(
    scores: &PolicyScores,
    candidate_count: usize,
) -> Result<(), SearchError> {
    if scores.logits.len() != candidate_count
        || scores.logits.iter().any(|value| !value.is_finite())
    {
        return Err(SearchError::Policy(
            "proposal must return one finite logit per legal edit".to_owned(),
        ));
    }
    Ok(())
}

pub(super) fn validate_latent_state(state: &[f32], latent_dim: usize) -> Result<(), SearchError> {
    if state.len() != latent_dim || state.iter().any(|value| !value.is_finite()) {
        return Err(SearchError::Policy(
            "proposal latent update must match configured dimension and be finite".to_owned(),
        ));
    }
    Ok(())
}

pub(super) fn combine_policy_costs(target: &mut PolicyCosts, additional: PolicyCosts) {
    target.logits_scored = target
        .logits_scored
        .saturating_add(additional.logits_scored);
    target.encoder_forward_calls = target
        .encoder_forward_calls
        .saturating_add(additional.encoder_forward_calls);
    target.encoder_tokens = target
        .encoder_tokens
        .saturating_add(additional.encoder_tokens);
    target.gpu_active_ns = target
        .gpu_active_ns
        .saturating_add(additional.gpu_active_ns);
}

pub(super) fn require_finite(value: f32, label: &str) -> Result<(), SearchError> {
    if value.is_finite() {
        Ok(())
    } else {
        Err(SearchError::Policy(format!(
            "{label} returned a non-finite value"
        )))
    }
}

pub(super) fn choose_round_robin(
    particles: &[Particle],
    cursor: &mut u32,
    width: u16,
) -> Option<usize> {
    let live = particles.iter().any(|particle| particle.alive);
    if !live {
        return None;
    }
    let slots = usize::from(width).max(1);
    let start = (*cursor as usize) % slots;
    *cursor = ((start + 1) % slots) as u32;
    for offset in 0..slots {
        let id = ((start + offset) % slots) as u32;
        if let Some(index) = particles
            .iter()
            .position(|particle| particle.id == id && particle.alive)
        {
            return Some(index);
        }
    }
    particles.iter().position(|particle| particle.alive)
}

pub(super) fn choose_particle(particles: &[Particle], minimum: u64) -> Option<(usize, bool)> {
    if let Some(index) = choose_under_allocated(particles, minimum) {
        Some((index, false))
    } else {
        particles
            .iter()
            .enumerate()
            .filter(|(_, particle)| particle.alive)
            .max_by(|(_, left), (_, right)| {
                left.value
                    .total_cmp(&right.value)
                    .then_with(|| right.id.cmp(&left.id))
            })
            .map(|(index, _)| (index, true))
    }
}

pub(super) fn choose_particle_round_robin(
    particles: &[Particle],
    minimum: u64,
    cursor: &mut u32,
    width: u16,
) -> Option<usize> {
    choose_under_allocated(particles, minimum)
        .or_else(|| choose_round_robin(particles, cursor, width))
}

fn choose_under_allocated(particles: &[Particle], minimum: u64) -> Option<usize> {
    particles
        .iter()
        .enumerate()
        .filter(|(_, particle)| particle.alive && particle.allocations_since_spawn < minimum)
        .min_by_key(|(_, particle)| (particle.allocations_since_spawn, particle.id))
        .map(|(index, _)| index)
}

pub(super) fn update_representatives(
    raw_seen: &mut HashMap<Vec<u8>, Representative>,
    canonical_seen: &mut HashMap<Vec<u8>, Representative>,
    particles: &[Particle],
    candidate: &Particle,
    event_index: u64,
    canonical: &[u8],
    value: f32,
) {
    let rep = Representative {
        particle_id: candidate.id,
        event_index: Some(event_index),
        initial_id: None,
        value,
        particle: candidate.clone(),
    };
    let replace = |existing: Option<&Representative>| {
        existing.is_none_or(|old| {
            !particles
                .iter()
                .any(|particle| particle.id == old.particle_id && particle.alive)
                || value > old.value
        })
    };
    let raw_key = candidate.assignment.clone();
    if replace(raw_seen.get(&raw_key)) {
        raw_seen.insert(raw_key, rep.clone());
    }
    let canonical_key = canonical.to_vec();
    if replace(canonical_seen.get(&canonical_key)) {
        canonical_seen.insert(canonical_key, rep);
    }
}

pub(super) fn apply_merge(
    particles: &mut [Particle],
    candidate: &mut Particle,
    previous: &Representative,
    candidate_wins: bool,
) -> Option<u32> {
    if candidate_wins {
        let retired = (previous.particle_id != candidate.id).then_some(previous.particle_id);
        if let Some(retired_id) = retired {
            if let Some(old) = particles
                .iter_mut()
                .find(|particle| particle.id == retired_id)
            {
                old.alive = false;
                old.retired_by_merge = true;
            }
        }
        candidate.alive = true;
        candidate.retired_by_merge = false;
        if let Some(slot) = particles
            .iter_mut()
            .find(|particle| particle.id == candidate.id)
        {
            *slot = candidate.clone();
        }
        retired
    } else if previous.particle_id == candidate.id {
        let age = candidate.allocations_since_spawn;
        *candidate = previous.particle.clone();
        candidate.allocations_since_spawn = age;
        candidate.alive = true;
        candidate.retired_by_merge = false;
        if let Some(slot) = particles
            .iter_mut()
            .find(|particle| particle.id == candidate.id)
        {
            *slot = candidate.clone();
        }
        None
    } else {
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
            .find(|particle| particle.id == previous.particle_id)
        {
            let age = slot.allocations_since_spawn;
            *slot = previous.particle.clone();
            slot.allocations_since_spawn = age;
            slot.alive = true;
            slot.retired_by_merge = false;
        }
        Some(candidate.id)
    }
}

pub(super) fn snapshot_particle(
    particle: &Particle,
    event_index: Option<u64>,
    initial_particle_id: Option<u32>,
) -> MergeParticleSnapshot {
    MergeParticleSnapshot {
        particle_id: particle.id,
        parent_particle_id: particle.parent_particle_id,
        ancestry_id: particle.ancestry_id,
        event_index,
        initial_particle_id,
        depth: particle.depth,
        assignment: particle.assignment.clone(),
        latent_state: particle.latent.clone(),
        value: particle.value,
    }
}

pub(super) fn fork_particles_at_spine(
    particles: &mut [Particle],
    spine_budget: u64,
) -> Result<(), SearchError> {
    let spine = particles
        .iter()
        .find(|particle| particle.id == 0 && particle.alive)
        .cloned()
        .ok_or_else(|| {
            SearchError::InvalidConfig("spine particle is not live at fork".to_owned())
        })?;
    if u64::from(spine.depth) != spine_budget
        || spine.last_event != Some(spine_budget.saturating_sub(1))
    {
        return Err(SearchError::InvalidConfig(
            "spine particle depth or event does not match configured fork boundary".to_owned(),
        ));
    }
    let mut used_ancestry_ids = particles
        .iter()
        .map(|particle| particle.ancestry_id)
        .collect::<HashSet<_>>();
    for branch in particles
        .iter_mut()
        .filter(|particle| particle.id != spine.id)
    {
        branch.parent_particle_id = Some(spine.id);
        branch.ancestry_id = fork_ancestry_id(
            spine.ancestry_id,
            spine_budget,
            branch.id,
            &mut used_ancestry_ids,
        )?;
        branch.assignment.clone_from(&spine.assignment);
        branch.latent.clone_from(&spine.latent);
        branch.depth = spine.depth;
        branch.last_event = spine.last_event;
        branch.value = spine.value;
        branch.allocations_since_spawn = 0;
        branch.alive = true;
        branch.retired_by_merge = false;
    }
    Ok(())
}

fn fork_ancestry_id(
    spine_ancestry_id: u64,
    spine_budget: u64,
    branch_id: u32,
    used_ancestry_ids: &mut HashSet<u64>,
) -> Result<u64, SearchError> {
    let mut nonce = 0_u64;
    loop {
        let mut hash = Sha256::new();
        hash.update(b"fas-r1-fork-ancestry-v01");
        hash.update(spine_ancestry_id.to_le_bytes());
        hash.update(spine_budget.to_le_bytes());
        hash.update(branch_id.to_le_bytes());
        hash.update(nonce.to_le_bytes());
        let digest = hash.finalize();
        let candidate = u64::from_le_bytes(digest[..8].try_into().unwrap_or([0; 8]));
        if used_ancestry_ids.insert(candidate) {
            return Ok(candidate);
        }
        nonce = nonce.checked_add(1).ok_or_else(|| {
            SearchError::InvalidConfig("fork ancestry identity space is exhausted".to_owned())
        })?;
    }
}

pub(super) fn resample(
    particles: &mut Vec<Particle>,
    task_hash: u64,
    expansion: u64,
    max_width: u16,
    event_index: u64,
    minimum: u64,
) -> Option<ResamplingRecord> {
    let source_index = particles
        .iter()
        .enumerate()
        .filter(|(_, particle)| particle.alive)
        .max_by(|(_, left), (_, right)| {
            left.value
                .total_cmp(&right.value)
                .then_with(|| right.id.cmp(&left.id))
        })
        .map(|(index, _)| index)?;
    let source = particles[source_index].clone();
    let live_count = particles.iter().filter(|particle| particle.alive).count();
    let retired_id = if live_count >= usize::from(max_width) {
        Some(
            particles
                .iter()
                .filter(|particle| {
                    particle.alive
                        && particle.id != source.id
                        && particle.allocations_since_spawn >= minimum
                })
                .min_by(|left, right| {
                    left.value
                        .total_cmp(&right.value)
                        .then_with(|| left.id.cmp(&right.id))
                })
                .map(|particle| particle.id)?,
        )
    } else {
        None
    };
    if let Some(id) = retired_id {
        if let Some(retired) = particles.iter_mut().find(|particle| particle.id == id) {
            retired.alive = false;
        }
    }
    let spawned_id = particles
        .iter()
        .map(|particle| particle.id)
        .max()
        .unwrap_or(0)
        + 1;
    let mut child = source.clone();
    child.id = spawned_id;
    child.parent_particle_id = Some(source.id);
    child.ancestry_id =
        source.ancestry_id ^ expansion.wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ u64::from(spawned_id);
    child.rng = DeterministicRng::new(seed_mix(task_hash ^ expansion, spawned_id));
    child.allocations_since_spawn = 0;
    child.alive = true;
    child.retired_by_merge = false;
    particles.push(child.clone());
    Some(ResamplingRecord {
        source_particle_id: source.id,
        retired_particle_id: retired_id,
        spawned_particle_id: spawned_id,
        spawned_ancestry_id: child.ancestry_id,
        spawned_parent_event: source.last_event.or(Some(event_index)),
        spawned_assignment: child.assignment,
        spawned_latent_state: child.latent,
        spawned_rng_state: child.rng.state,
    })
}

pub(super) fn public_group(k: u8, anonymous: bool) -> Vec<Vec<u8>> {
    if !anonymous {
        return vec![(0..k).collect()];
    }
    let mut values = (0..k).collect::<Vec<_>>();
    let mut result = Vec::new();
    permute(&mut values, 0, &mut result);
    result
}

pub(super) fn permute(values: &mut [u8], start: usize, output: &mut Vec<Vec<u8>>) {
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

pub(super) fn make_initial(task: &InferenceTask, seed: u64) -> Vec<u8> {
    let mut rng = DeterministicRng::new(seed ^ stable_hash(&task.id, &task.family_id));
    (0..task.n)
        .map(|_| (rng.next_u64() % u64::from(task.k)) as u8)
        .collect()
}

pub(super) fn select_initial_assignment(
    task: &InferenceTask,
    seed: u64,
    provided: Option<&[u8]>,
) -> Vec<u8> {
    provided
        .map(<[u8]>::to_vec)
        .unwrap_or_else(|| make_initial(task, seed))
}

pub(super) fn seed_mix(seed: u64, particle: u32) -> u64 {
    let mut rng =
        DeterministicRng::new(seed ^ u64::from(particle).wrapping_mul(0x9E37_79B9_7F4A_7C15));
    rng.next_u64()
}

pub(super) fn stable_hash(task_id: &str, family_id: &str) -> u64 {
    let mut hash = Sha256::new();
    hash.update(task_id.as_bytes());
    hash.update([0]);
    hash.update(family_id.as_bytes());
    let digest = hash.finalize();
    u64::from_le_bytes(digest[..8].try_into().unwrap_or([0; 8]))
}

pub(super) fn trace_id(task: &InferenceTask, config: &Stage1RunConfig, initial: &[u8]) -> String {
    let mut hash = Sha256::new();
    hash.update(task.id.as_bytes());
    hash.update(task.family_id.as_bytes());
    hash.update(initial);
    hash.update(config.base.seed.to_le_bytes());
    hash.update(config.base.budget.to_le_bytes());
    hash.update([config.base.arm as u8]);
    hash.update(config.base.width.to_le_bytes());
    hash.update(config.base.latent_dim.to_le_bytes());
    hash.update(config.base.resample_period.to_le_bytes());
    hash.update(config.base.minimum_particle_budget.to_le_bytes());
    if strategy(config.base.arm) == ProposalStrategy::LearnedSample
        && config.learned_sample_temperature != 1.0
    {
        hash.update([0x54]);
        hash.update(config.learned_sample_temperature.to_bits().to_le_bytes());
    }
    match config.allocation_policy {
        SearchAllocationPolicy::StandardRoundRobin => hash.update([0]),
        SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget } => {
            hash.update([1]);
            hash.update(spine_budget.to_le_bytes());
        }
        SearchAllocationPolicy::ForkFromSpineThenWidth { spine_budget } => {
            hash.update([2]);
            hash.update(spine_budget.to_le_bytes());
        }
    }
    hash.update([config.merge_mode as u8]);
    hash.update([config.value_refresh_policy as u8]);
    for identifier in [&config.proposal_id, &config.selector_id, &config.value_id] {
        hash.update((identifier.len() as u64).to_le_bytes());
        hash.update(identifier.as_bytes());
    }
    hash.finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

pub(super) fn latent_distance(left: &[f32], right: &[f32]) -> f32 {
    left.iter()
        .zip(right)
        .map(|(a, b)| (a - b).powi(2))
        .sum::<f32>()
        .sqrt()
}

pub(super) fn add_policy_costs(costs: &mut OperationCosts, policy: PolicyCosts) {
    costs.logits_scored += policy.logits_scored;
    costs.encoder_forward_calls += policy.encoder_forward_calls;
    costs.encoder_tokens += policy.encoder_tokens;
    costs.gpu_active_ns += policy.gpu_active_ns;
}

pub(super) fn charge_initial(ledger: &mut OperationLedger, costs: &OperationCosts) {
    ledger.value_calls += costs.value_calls;
    ledger.canonicalization_calls += costs.canonicalization_calls;
    ledger.hash_probes += costs.hash_probes;
    ledger.selection_comparisons += costs.selection_comparisons;
    ledger.cpu_active_ns += costs.cpu_active_ns;
    ledger.gpu_active_ns += costs.gpu_active_ns;
    ledger.encoder_forward_calls += costs.encoder_forward_calls;
    ledger.encoder_tokens += costs.encoder_tokens;
}

pub(super) fn charge(ledger: &mut OperationLedger, costs: &OperationCosts) {
    ledger.expansions += 1;
    ledger.proposal_calls += costs.proposal_calls;
    ledger.logits_scored += costs.logits_scored;
    ledger.value_calls += costs.value_calls;
    ledger.encoder_forward_calls += costs.encoder_forward_calls;
    ledger.encoder_tokens += costs.encoder_tokens;
    ledger.canonicalization_calls += costs.canonicalization_calls;
    ledger.hash_probes += costs.hash_probes;
    ledger.merges += costs.merges;
    ledger.resampling_ops += costs.resampling_ops;
    ledger.allocation_decisions += costs.allocation_decisions;
    ledger.nonnominal_allocation_decisions += costs.nonnominal_allocation_decisions;
    ledger.selection_comparisons += costs.selection_comparisons;
    ledger.cpu_active_ns += costs.cpu_active_ns;
    ledger.gpu_active_ns += costs.gpu_active_ns;
}

pub(super) fn nanos(duration: std::time::Duration) -> u64 {
    duration.as_nanos().min(u128::from(u64::MAX)) as u64
}

pub(super) fn selector_rank(value: &crate::PolicyValue) -> Result<f64, SearchError> {
    let score = value.selection_score.unwrap_or(f64::from(value.value));
    if score.is_nan() || score == f64::INFINITY {
        return Err(SearchError::Policy(
            "terminal ordering score must be finite or negative infinity".to_owned(),
        ));
    }
    Ok(score)
}

pub(super) fn serializable_rank(score: f64) -> f64 {
    if score == f64::NEG_INFINITY {
        -f64::MAX
    } else {
        score
    }
}

pub(super) fn uses_v_reach(arm: Arm) -> bool {
    matches!(arm, Arm::MergedWidth | Arm::CanonicalMerge | Arm::Particle)
}

#[derive(Clone, Debug, Serialize)]
pub(super) struct EditDraft {
    pub(super) entity: u16,
    pub(super) new_role: u8,
}

#[derive(Clone, Debug, Serialize)]
pub(super) struct TraceEventDraft {
    pub(super) event_index: u64,
    pub(super) global_expansion_index: u64,
    pub(super) particle_id: u32,
    pub(super) nominal_slot_particle_id: u32,
    pub(super) nominal_slot_redirected: bool,
    pub(super) value_allocation_non_nominal: bool,
    pub(super) parent_particle_id: Option<u32>,
    pub(super) parent_event_index: Option<u64>,
    pub(super) ancestry_id: u64,
    pub(super) particle_depth: u32,
    pub(super) assignment_before: Vec<u8>,
    pub(super) assignment_after: Vec<u8>,
    pub(super) canonical_key: Option<Vec<u8>>,
    pub(super) latent_state_before: Vec<f32>,
    pub(super) latent_state_after: Vec<f32>,
    pub(super) edit: Option<EditDraft>,
    pub(super) log_probability: f32,
    pub(super) v_reach: f32,
    pub(super) q_terminal: f32,
    pub(super) remaining_budget: u64,
    pub(super) selected: bool,
    pub(super) resampled: bool,
    pub(super) resampling: Option<ResamplingRecord>,
    pub(super) raw_duplicate_detected: bool,
    pub(super) canonical_duplicate_detected: bool,
    pub(super) full_dynamic_duplicate: bool,
    pub(super) raw_merge: bool,
    pub(super) canonical_merge: bool,
    pub(super) merge_representative_event: Option<u64>,
    pub(super) merge_representative_initial_particle: Option<u32>,
    pub(super) merge_representative_ancestry_id: Option<u64>,
    pub(super) representative_value: Option<f32>,
    pub(super) merge_ancestry_ids: Option<Vec<u64>>,
    pub(super) merge_representative_latent_state: Option<Vec<f32>>,
    pub(super) merge_latent_divergence_l2: Option<f32>,
    pub(super) rng_state_before: u64,
    pub(super) rng_state_after: u64,
    pub(super) costs: OperationCosts,
    pub(super) cumulative_active_ns: u64,
    pub(super) cumulative_wall_ns: u64,
}

impl TraceEventDraft {
    pub(super) fn into_trace_event(self) -> Result<TraceEvent, SearchError> {
        let value = serde_json::to_value(self)
            .map_err(|error| SearchError::InvalidConfig(error.to_string()))?;
        serde_json::from_value(value)
            .map_err(|error| SearchError::InvalidConfig(format!("trace event conversion: {error}")))
    }
}
