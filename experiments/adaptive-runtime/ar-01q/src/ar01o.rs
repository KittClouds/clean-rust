use super::*;

pub const OPEN_LOOP_HORIZONS: [usize; 7] = [1, 2, 4, 8, 16, 32, 64];
const OPEN_LOOP_MODE_CLOSED: u8 = 0;
const OPEN_LOOP_MODE_FROZEN: u8 = 1;
const OPEN_LOOP_FAMILY_FROZEN_BASE: u8 = 3;
const N2_DOMAIN: u8 = 2;
const MAX_FUTURE_COMMITS: usize = OPEN_LOOP_HORIZONS[OPEN_LOOP_HORIZONS.len() - 1] - 1;

#[derive(Clone, Copy, Debug, Default)]
pub struct OHorizon {
    pub horizon: usize,
    pub valid: bool,
    pub g3_train_loss: f32,
    pub control_train_loss: f32,
    pub delta_train_loss: f32,
    pub g3_validation_loss: f32,
    pub control_validation_loss: f32,
    pub parameter_distance: f32,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct OComparison {
    pub mode: u8,
    pub family: u8,
    pub replicate: usize,
    pub global_commit: usize,
    pub group_left: usize,
    pub group_right: usize,
    pub control_slot: u8,
    pub g3_delta_left: f32,
    pub g3_delta_right: f32,
    pub control_delta_left: f32,
    pub control_delta_right: f32,
    pub immediate_utility_gap: f32,
    pub first_divergence_step: usize,
    /// 0 none; 1 selected block/no-op changed; 2 program changed within the same block.
    pub divergence_kind: u8,
    pub g3_margin_at_divergence: f32,
    pub control_margin_at_divergence: f32,
    pub revisit_left_offset: usize,
    pub revisit_right_offset: usize,
    pub invalid_from_step: usize,
    /// usize::MAX when there was no frozen-action bounds failure.
    pub invalid_parameter: usize,
    pub horizons: [OHorizon; 7],
}

#[derive(Clone, Debug)]
pub struct OSeedSummary {
    pub seed: u64,
    pub final_train_loss: f32,
    pub final_validation_loss: f32,
    pub final_train_accuracy: f32,
    pub final_validation_accuracy: f32,
    pub selected_pair_snapshots: usize,
    pub matched_control_a: usize,
    pub matched_control_b: usize,
    pub comparisons: Vec<OComparison>,
}

#[derive(Clone, Copy)]
struct BaseSnapshot {
    model: Model,
    global_commit: usize,
    group: Group,
    g3_program: Program,
    g3_utility: f32,
    controls: [Option<MatchedControl>; MATCHED_CONTROLS],
}

#[derive(Clone, Copy, Debug, Default)]
struct ShadowDecision {
    program: Option<Program>,
    best_value: f32,
    runner_up_value: f32,
}

impl ShadowDecision {
    fn margin(self) -> f32 {
        (self.best_value - self.runner_up_value).max(0.0)
    }
}

fn shadow_decision(
    model: &Model,
    train: &[Sample],
    spec: ContinuationSpec,
    global_commit: usize,
) -> ShadowDecision {
    let evidence_round = global_commit / CONTINUATION_COMMITS_PER_EVIDENCE;
    let proposal_indices = batch_indices(spec.evidence_seed, evidence_round, 0x5052_4f50_4f53_414c);
    let proposal_storage = indexed_samples(train, &proposal_indices);
    let mut verify_storage = [train[0]; TRAIN_SAMPLES];
    fill_stratified_verifier(
        &mut verify_storage,
        train,
        spec.evidence_seed,
        evidence_round,
        64,
    );
    let verify_batches = [&verify_storage[..64]];
    let (groups, group_count) = partition((global_commit + spec.schedule_phase) % PARAMS);
    let mut result = ShadowDecision::default();
    for &group in &groups[..group_count] {
        let (candidate, _) = best_runtime_program(
            model,
            &proposal_storage,
            &verify_batches,
            Arm::G3Stratified64,
            group,
        );
        let score = candidate.map_or(0.0, |program| program.utility);
        if score > result.best_value {
            result.runner_up_value = result.best_value;
            result.best_value = score;
            result.program = candidate;
        } else if score > result.runner_up_value {
            result.runner_up_value = score;
        }
    }
    result
}

fn divergence_kind(left: Option<Program>, right: Option<Program>) -> u8 {
    if same_program(left, right) {
        return 0;
    }
    match (left, right) {
        (Some(left), Some(right))
            if left.left == right.left && left.right == right.right && left.len == right.len =>
        {
            2
        }
        _ => 1,
    }
}

fn record_first_divergence(
    comparison: &mut OComparison,
    step: usize,
    g3: ShadowDecision,
    control: ShadowDecision,
) {
    let kind = divergence_kind(g3.program, control.program);
    if comparison.first_divergence_step == 0 && kind != 0 {
        comparison.first_divergence_step = step;
        comparison.divergence_kind = kind;
        comparison.g3_margin_at_divergence = g3.margin();
        comparison.control_margin_at_divergence = control.margin();
    }
}

fn first_paired_revisit(
    global_commit: usize,
    phase: usize,
    coordinate: usize,
    other: usize,
) -> usize {
    for offset in 1..=PARAMS {
        let (groups, count) = partition((global_commit + offset + phase) % PARAMS);
        if groups[..count].iter().any(|group| {
            group.len == 2
                && (group.left == coordinate || group.right == coordinate)
                && !((group.left == coordinate && group.right == other)
                    || (group.left == other && group.right == coordinate))
        }) {
            return offset;
        }
    }
    0
}

fn base_comparison(
    mode: u8,
    family: u8,
    replicate: usize,
    snapshot: BaseSnapshot,
    control: MatchedControl,
    control_slot: usize,
    spec: ContinuationSpec,
) -> OComparison {
    OComparison {
        mode,
        family,
        replicate,
        global_commit: snapshot.global_commit,
        group_left: snapshot.group.left,
        group_right: snapshot.group.right,
        control_slot: control_slot as u8,
        g3_delta_left: snapshot.g3_program.deltas[0],
        g3_delta_right: snapshot.g3_program.deltas[1],
        control_delta_left: control.program.deltas[0],
        control_delta_right: control.program.deltas[1],
        immediate_utility_gap: (snapshot.g3_utility - control.utility).abs(),
        revisit_left_offset: first_paired_revisit(
            snapshot.global_commit,
            spec.schedule_phase,
            snapshot.group.left,
            snapshot.group.right,
        ),
        revisit_right_offset: first_paired_revisit(
            snapshot.global_commit,
            spec.schedule_phase,
            snapshot.group.right,
            snapshot.group.left,
        ),
        invalid_parameter: usize::MAX,
        ..OComparison::default()
    }
}

fn record_horizon(
    comparison: &mut OComparison,
    step: usize,
    g3: &Model,
    control: &Model,
    train: &[Sample],
    validation: &[Sample],
) {
    let Some(index) = OPEN_LOOP_HORIZONS
        .iter()
        .position(|&horizon| horizon == step)
    else {
        return;
    };
    let g3_train_loss = g3.loss(train);
    let control_train_loss = control.loss(train);
    comparison.horizons[index] = OHorizon {
        horizon: step,
        valid: true,
        g3_train_loss,
        control_train_loss,
        delta_train_loss: g3_train_loss - control_train_loss,
        g3_validation_loss: g3.loss(validation),
        control_validation_loss: control.loss(validation),
        parameter_distance: parameter_distance(g3, control),
    };
}

fn closed_loop_comparison(
    snapshot: BaseSnapshot,
    control: MatchedControl,
    control_slot: usize,
    spec: ContinuationSpec,
    train: &[Sample],
    validation: &[Sample],
) -> OComparison {
    let mut comparison = base_comparison(
        OPEN_LOOP_MODE_CLOSED,
        spec.family,
        spec.replicate,
        snapshot,
        control,
        control_slot,
        spec,
    );
    let mut g3 = snapshot.model;
    let mut matched = snapshot.model;
    commit(&mut g3, snapshot.g3_program);
    commit(&mut matched, control.program);
    record_horizon(&mut comparison, 1, &g3, &matched, train, validation);

    for step in 2..=OPEN_LOOP_HORIZONS[OPEN_LOOP_HORIZONS.len() - 1] {
        let future_commit = snapshot.global_commit + step - 1;
        let g3_decision = shadow_decision(&g3, train, spec, future_commit);
        let control_decision = shadow_decision(&matched, train, spec, future_commit);
        record_first_divergence(&mut comparison, step, g3_decision, control_decision);
        if let Some(program) = g3_decision.program {
            commit(&mut g3, program);
        }
        if let Some(program) = control_decision.program {
            commit(&mut matched, program);
        }
        record_horizon(&mut comparison, step, &g3, &matched, train, validation);
    }
    comparison
}

fn program_illegal_parameter(model: &Model, program: Option<Program>) -> Option<usize> {
    let program = program?;
    let left_value = model.parameters[program.left] + program.deltas[0];
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&left_value) {
        return Some(program.left);
    }
    if program.len == 2 {
        let right_value = model.parameters[program.right] + program.deltas[1];
        if !(LOWER_BOUND..=UPPER_BOUND).contains(&right_value) {
            return Some(program.right);
        }
    }
    None
}

fn frozen_program_comparison(
    snapshot: BaseSnapshot,
    control: MatchedControl,
    control_slot: usize,
    train: &[Sample],
    validation: &[Sample],
    base_programs: &[Option<Program>],
    spec: ContinuationSpec,
) -> OComparison {
    let mut comparison = base_comparison(
        OPEN_LOOP_MODE_FROZEN,
        OPEN_LOOP_FAMILY_FROZEN_BASE,
        0,
        snapshot,
        control,
        control_slot,
        spec,
    );
    let mut g3 = snapshot.model;
    let mut matched = snapshot.model;
    commit(&mut g3, snapshot.g3_program);
    commit(&mut matched, control.program);
    record_horizon(&mut comparison, 1, &g3, &matched, train, validation);

    for step in 2..=OPEN_LOOP_HORIZONS[OPEN_LOOP_HORIZONS.len() - 1] {
        let future_commit = snapshot.global_commit + step - 1;
        let g3_decision = shadow_decision(&g3, train, spec, future_commit);
        let control_decision = shadow_decision(&matched, train, spec, future_commit);
        record_first_divergence(&mut comparison, step, g3_decision, control_decision);

        let frozen = base_programs.get(future_commit).copied().flatten();
        let g3_illegal = program_illegal_parameter(&g3, frozen);
        let control_illegal = program_illegal_parameter(&matched, frozen);
        if let Some(parameter) = g3_illegal.or(control_illegal) {
            comparison.invalid_from_step = step;
            comparison.invalid_parameter = parameter;
            break;
        }
        if let Some(program) = frozen {
            commit(&mut g3, program);
            commit(&mut matched, program);
        }
        record_horizon(&mut comparison, step, &g3, &matched, train, validation);
    }
    comparison
}

fn run_open_loop_diagnostic(samples: &[Sample], seed: u64) -> OSeedSummary {
    assert_eq!(samples.len(), TOTAL_SAMPLES);
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let mut model = Model::initial();
    let mut base_programs = Vec::with_capacity(TOTAL_COMMITS + MAX_FUTURE_COMMITS + 1);
    let mut base_snapshots = Vec::with_capacity(SAME_BLOCK_SNAPSHOTS);
    let mut selected_pair_snapshots = 0;
    let mut matched_counts = [0usize; MATCHED_CONTROLS];
    let total_base_commits = TOTAL_COMMITS + MAX_FUTURE_COMMITS + 1;

    for global_commit in 0..total_base_commits {
        let (proposal_batch, _groups, _group_count, selection) =
            g3_context(&model, train, seed, global_commit);
        if global_commit < TOTAL_COMMITS
            && global_commit.is_multiple_of(SAME_BLOCK_EVERY)
            && let Some(program) = selection.program.filter(|program| program.len == 2)
        {
            selected_pair_snapshots += 1;
            let baseline = model.loss(train);
            let utility = exact_program_value(&model, train, baseline, program);
            let controls = same_block_controls(
                &model,
                train,
                &proposal_batch,
                selection.group,
                Some(program),
                utility,
                N2_DOMAIN,
                seed,
                global_commit,
            );
            for slot in 0..MATCHED_CONTROLS {
                matched_counts[slot] += usize::from(controls[slot].is_some());
            }
            base_snapshots.push(BaseSnapshot {
                model,
                global_commit,
                group: selection.group,
                g3_program: program,
                g3_utility: utility,
                controls,
            });
        }
        base_programs.push(selection.program);
        commit_optional(&mut model, selection.program);
    }

    let final_model = {
        let mut replay = Model::initial();
        for program in base_programs.iter().take(TOTAL_COMMITS).flatten().copied() {
            commit(&mut replay, program);
        }
        replay
    };
    let mut comparisons = Vec::with_capacity(
        base_snapshots.len() * (SAME_BLOCK_SCHEDULE_PHASES.len() * MATCHED_CONTROLS + 1),
    );
    for snapshot in base_snapshots {
        for spec in same_block_specs(seed) {
            for slot in 0..MATCHED_CONTROLS {
                if let Some(control) = snapshot.controls[slot] {
                    comparisons.push(closed_loop_comparison(
                        snapshot, control, slot, spec, train, validation,
                    ));
                }
            }
        }
        let original_spec = same_block_specs(seed)[0];
        for slot in 0..MATCHED_CONTROLS {
            if let Some(control) = snapshot.controls[slot] {
                comparisons.push(frozen_program_comparison(
                    snapshot,
                    control,
                    slot,
                    train,
                    validation,
                    &base_programs,
                    original_spec,
                ));
            }
        }
    }

    OSeedSummary {
        seed,
        final_train_loss: final_model.loss(train),
        final_validation_loss: final_model.loss(validation),
        final_train_accuracy: final_model.accuracy(train),
        final_validation_accuracy: final_model.accuracy(validation),
        selected_pair_snapshots,
        matched_control_a: matched_counts[0],
        matched_control_b: matched_counts[1],
        comparisons,
    }
}

pub fn open_loop_diagnostic_all(samples: &[Sample]) -> Vec<OSeedSummary> {
    SEEDS
        .into_iter()
        .map(|seed| run_open_loop_diagnostic(samples, seed))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decision_divergence_distinguishes_block_and_program() {
        let base = Program {
            left: 3,
            right: 9,
            deltas: [0.01, -0.01],
            len: 2,
            utility: 0.1,
        };
        let changed_program = Program {
            deltas: [0.02, -0.01],
            ..base
        };
        let changed_block = Program { left: 4, ..base };
        assert_eq!(divergence_kind(Some(base), Some(base)), 0);
        assert_eq!(divergence_kind(Some(base), Some(changed_program)), 2);
        assert_eq!(divergence_kind(Some(base), Some(changed_block)), 1);
        assert_eq!(divergence_kind(None, Some(base)), 1);
    }

    #[test]
    fn frozen_actions_fail_closed_at_bounds() {
        let mut model = Model::initial();
        let program = Program {
            left: 0,
            right: 1,
            deltas: [0.02, 0.0],
            len: 2,
            ..Program::default()
        };
        model.parameters[0] = UPPER_BOUND;
        assert_eq!(program_illegal_parameter(&model, Some(program)), Some(0));
        assert_eq!(program_illegal_parameter(&model, None), None);
    }

    #[test]
    fn paired_revisit_is_found_without_counting_original_pair() {
        let (groups, count) = partition(0);
        let first = groups[..count]
            .iter()
            .find(|group| group.len == 2)
            .copied()
            .expect("at least one pair");
        assert!(first_paired_revisit(0, 0, first.left, first.right) > 0);
        assert!(first_paired_revisit(0, 0, first.right, first.left) > 0);
    }

    #[test]
    fn closed_loop_shadow_selection_matches_n_continuation_policy() {
        let dataset = spiral_dataset();
        let train = &dataset.samples[..TRAIN_SAMPLES];
        let model = Model::initial();
        for spec in same_block_specs(SEEDS[0]) {
            for global_commit in [0, 50, 100] {
                let shadow = shadow_decision(&model, train, spec, global_commit);
                let inherited = continuation_selection(&model, train, spec, global_commit);
                assert!(same_program(shadow.program, inherited.program));
            }
        }
    }
}
