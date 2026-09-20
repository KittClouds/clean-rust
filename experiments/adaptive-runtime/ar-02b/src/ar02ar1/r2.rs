use super::*;
use std::io::{self, BufWriter, Write};
use std::path::Path;

const SNAPSHOT_STEPS: [usize; 3] = [600, 2_400, 4_200];
const PANEL_REPLICATES: usize = 64;
const PLACEBO_PARTITIONS: usize = 8;
const SAMPLES_PER_STRATUM: usize = 4;
const R2_SAMPLE_COUNT: usize = 48;
const UTILITY_EPSILON: f32 = 1.0e-8;
const PANEL_STREAM: u64 = 0x5232_5041_4e45_4c53;
const PLACEBO_STREAM: u64 = 0x5232_504c_4143_4542;

#[derive(Clone, Copy)]
struct ReplaySnapshot {
    step: usize,
    model: Model,
}

#[derive(Clone, Copy)]
enum PanelKind {
    IidWithReplacement,
    IidWithoutReplacement,
    CellWithoutReplacement,
    MarginWithoutReplacement,
    PlaceboWithoutReplacement(u8),
}

impl PanelKind {
    fn name(self) -> String {
        match self {
            Self::IidWithReplacement => "iid_with_replacement".to_owned(),
            Self::IidWithoutReplacement => "iid_without_replacement".to_owned(),
            Self::CellWithoutReplacement => "cell_stratified_wor".to_owned(),
            Self::MarginWithoutReplacement => "margin_stratified_wor".to_owned(),
            Self::PlaceboWithoutReplacement(id) => format!("hash_placebo_{id:02}"),
        }
    }

    fn stream_id(self) -> u64 {
        match self {
            Self::IidWithReplacement => 0,
            Self::IidWithoutReplacement => 1,
            Self::CellWithoutReplacement => 2,
            Self::MarginWithoutReplacement => 3,
            Self::PlaceboWithoutReplacement(id) => 16 + u64::from(id),
        }
    }
}

#[derive(Clone, Copy)]
struct Candidate {
    block: usize,
    program: Program,
    per_example_utility: [f32; TRAIN_SAMPLES],
    exact_utility: f32,
}

struct PanelRecord {
    seed: u64,
    snapshot_step: usize,
    method: String,
    panel: usize,
    candidate_count: usize,
    utility_rmse: f64,
    sign_error_rate: f64,
    within_block_regret_mean: f64,
    within_block_positive_regret_rate: f64,
    cross_block_opportunity_regret: f64,
    selected_block_within_regret: f64,
    selected_program_regret: f64,
    false_positive_authorization: bool,
    best_reference_utility: f64,
    selected_estimated_utility: f64,
    selected_reference_utility: f64,
    selected_block: i32,
    selected_left: i32,
    selected_right: i32,
    selected_left_delta: f32,
    selected_right_delta: f32,
    snapshot_train_loss: f32,
    snapshot_validation_loss: f32,
}

pub fn run_r2_audit(samples: &[Sample], output_dir: impl AsRef<Path>) -> io::Result<usize> {
    assert_eq!(samples.len(), TOTAL_SAMPLES);
    std::fs::create_dir_all(output_dir.as_ref())?;
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let cell_ids = std::array::from_fn(|index| (index / TRAIN_PER_CELL) as u8);
    let margin_strata = build_margin_strata(train);
    let cell_index = StrataIndex::new(&cell_ids, CELLS);
    let margin_index = StrataIndex::new(&margin_strata.ids, MARGIN_STRATA);
    let placebo_indices = std::array::from_fn(|partition| {
        let ids = placebo_strata(partition as u64);
        StrataIndex::new(&ids, CELLS)
    });
    let mut replay = Vec::with_capacity(R1_SEEDS.len() * SNAPSHOT_STEPS.len());
    let mut rows = Vec::with_capacity(
        R1_SEEDS.len() * SNAPSHOT_STEPS.len() * (4 + PLACEBO_PARTITIONS) * PANEL_REPLICATES,
    );

    for seed in R1_SEEDS {
        let snapshots = replay_reference_trajectory(train, seed);
        for snapshot in snapshots {
            let snapshot_train_loss = snapshot.model.loss(train);
            let snapshot_validation_loss = snapshot.model.loss(validation);
            replay.push((
                seed,
                snapshot,
                snapshot_train_loss,
                snapshot_validation_loss,
            ));
            let evidence_round = snapshot.step / COMMITS_PER_EVIDENCE;
            let proposal_ids = batch_indices(seed, evidence_round, PROPOSAL_STREAM);
            let proposal = indexed_samples(train, &proposal_ids);
            let (groups, group_count) = partition(snapshot.step % PARAMS);
            let candidates =
                shortlist_candidates(&snapshot.model, train, &proposal, &groups, group_count);
            assert!(!candidates.is_empty());
            let mut kinds = vec![
                PanelKind::IidWithReplacement,
                PanelKind::IidWithoutReplacement,
                PanelKind::CellWithoutReplacement,
                PanelKind::MarginWithoutReplacement,
            ];
            kinds.extend(
                (0..PLACEBO_PARTITIONS).map(|id| PanelKind::PlaceboWithoutReplacement(id as u8)),
            );

            for kind in kinds {
                for panel in 0..PANEL_REPLICATES {
                    let panel_seed = seed
                        ^ PANEL_STREAM
                        ^ (snapshot.step as u64).wrapping_mul(0x9e37_79b9)
                        ^ (panel as u64).wrapping_mul(0xd6e8_feb8_6659_fd93)
                        ^ kind.stream_id().wrapping_mul(0xa076_1d64_78bd_642f);
                    let panel_indices = draw_panel(
                        kind,
                        panel_seed,
                        &cell_index,
                        &margin_index,
                        &placebo_indices,
                    );
                    rows.push(audit_panel(
                        &candidates,
                        group_count,
                        panel_indices,
                        seed,
                        snapshot,
                        kind,
                        panel,
                        snapshot_train_loss,
                        snapshot_validation_loss,
                    ));
                }
            }
        }
        eprintln!(
            "AR-02A-R2 replayed P16/V48 random path for seed {seed:016x}: snapshots {:?}",
            SNAPSHOT_STEPS
        );
    }

    write_replay(
        output_dir.as_ref().join("r2-replay-checkpoints.csv"),
        &replay,
    )?;
    write_panels(output_dir.as_ref().join("r2-panel-audit.csv"), &rows)?;
    write_report(output_dir.as_ref().join("r2-diagnostic-report.json"), &rows)?;
    Ok(rows.len())
}

fn replay_reference_trajectory(train: &[Sample], seed: u64) -> Vec<ReplaySnapshot> {
    let mut cell_ids = [0_u8; TRAIN_SAMPLES];
    for (index, cell) in cell_ids.iter_mut().enumerate() {
        *cell = (index / TRAIN_PER_CELL) as u8;
    }
    let class_ids = std::array::from_fn(|index| train[index].target as u8);
    let margins = build_margin_strata(train);
    let class_index = StrataIndex::new(&class_ids, CLASSES);
    let cell_index = StrataIndex::new(&cell_ids, CELLS);
    let margin_index = StrataIndex::new(&margins.ids, MARGIN_STRATA);
    let mut model = Model::initial();
    let mut snapshots = Vec::with_capacity(SNAPSHOT_STEPS.len());

    for evidence_round in 0..SNAPSHOT_STEPS[2] / COMMITS_PER_EVIDENCE {
        let mut proposal_storage = [train[0]; TRAIN_SAMPLES];
        let proposal: &[Sample] = if BATCH_SIZE == TRAIN_SAMPLES {
            train
        } else {
            let ids = batch_indices(seed, evidence_round, PROPOSAL_STREAM);
            proposal_storage[..BATCH_SIZE].copy_from_slice(&indexed_samples(train, &ids));
            &proposal_storage[..BATCH_SIZE]
        };
        let verifier = make_verifier(
            train,
            VerifierKind::Random,
            48,
            seed,
            evidence_round,
            &class_index,
            &cell_index,
            &margin_index,
        );

        for inner in 0..COMMITS_PER_EVIDENCE {
            let global_commit = evidence_round * COMMITS_PER_EVIDENCE + inner;
            let (groups, group_count) = partition(global_commit % PARAMS);
            let proposal_baseline = model.loss(proposal);
            let verifier_baseline = verifier.loss(&model);
            let mut selected = None;
            for &group in &groups[..group_count] {
                let (candidate, _) = select_group(
                    &model,
                    proposal,
                    proposal_baseline,
                    &verifier,
                    verifier_baseline,
                    group,
                );
                if let Some(candidate) = candidate
                    && selected.is_none_or(|current: Program| candidate.utility > current.utility)
                {
                    selected = Some(candidate);
                }
            }
            if let Some(program) = selected {
                commit(&mut model, program);
            }
            let step = global_commit + 1;
            if SNAPSHOT_STEPS.contains(&step) {
                snapshots.push(ReplaySnapshot { step, model });
            }
            if step == SNAPSHOT_STEPS[2] {
                break;
            }
        }
        if (evidence_round + 1) * COMMITS_PER_EVIDENCE >= SNAPSHOT_STEPS[2] {
            break;
        }
    }
    assert_eq!(snapshots.len(), SNAPSHOT_STEPS.len());
    snapshots
}

fn shortlist_candidates(
    model: &Model,
    train: &[Sample],
    proposal: &[Sample],
    groups: &[Group; PARAMS],
    group_count: usize,
) -> Vec<Candidate> {
    let proposal_baseline = model.loss(proposal);
    let baseline: [f32; TRAIN_SAMPLES] =
        std::array::from_fn(|index| sample_loss(model, train[index]));
    let mut candidates = Vec::with_capacity(group_count * 4);
    for (block, &group) in groups[..group_count].iter().enumerate() {
        if group.len == 1 {
            let (actions, _) = singleton_actions(model, proposal, proposal_baseline, group.left);
            let mut best_action = Action::default();
            for action in actions {
                if action.utility > best_action.utility {
                    best_action = action;
                }
            }
            append_candidate(
                &mut candidates,
                model,
                train,
                &baseline,
                block,
                group,
                [best_action.delta, 0.0],
                1,
            );
            continue;
        }
        let (left_actions, _) = singleton_actions(model, proposal, proposal_baseline, group.left);
        let (right_actions, _) = singleton_actions(model, proposal, proposal_baseline, group.right);
        let top_left = ordered_top(&left_actions, 2);
        let top_right = ordered_top(&right_actions, 2);
        for &left in &top_left[..2] {
            for &right in &top_right[..2] {
                append_candidate(
                    &mut candidates,
                    model,
                    train,
                    &baseline,
                    block,
                    group,
                    [ACTION_VALUES[left], ACTION_VALUES[right]],
                    2,
                );
            }
        }
    }
    candidates
}

fn append_candidate(
    candidates: &mut Vec<Candidate>,
    model: &Model,
    train: &[Sample],
    baseline: &[f32; TRAIN_SAMPLES],
    block: usize,
    group: Group,
    deltas: [f32; 2],
    len: usize,
) {
    let left_value = model.parameters[group.left] + deltas[0];
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&left_value) {
        return;
    }
    if len == 2 {
        let right_value = model.parameters[group.right] + deltas[1];
        if !(LOWER_BOUND..=UPPER_BOUND).contains(&right_value) {
            return;
        }
    }
    let mut candidate_model = *model;
    candidate_model.parameters[group.left] = left_value;
    if len == 2 {
        candidate_model.parameters[group.right] = model.parameters[group.right] + deltas[1];
    }
    let mut per_example_utility = [0.0_f32; TRAIN_SAMPLES];
    for (index, utility) in per_example_utility.iter_mut().enumerate() {
        *utility = baseline[index] - sample_loss(&candidate_model, train[index]);
    }
    let exact_utility = per_example_utility.iter().sum::<f32>() / TRAIN_SAMPLES as f32;
    candidates.push(Candidate {
        block,
        program: Program {
            left: group.left,
            right: group.right,
            deltas,
            len,
            utility: 0.0,
        },
        per_example_utility,
        exact_utility,
    });
}

fn draw_panel(
    kind: PanelKind,
    seed: u64,
    cell_index: &StrataIndex,
    margin_index: &StrataIndex,
    placebo_indices: &[StrataIndex; PLACEBO_PARTITIONS],
) -> [usize; R2_SAMPLE_COUNT] {
    let mut rng = Rng::new(seed);
    match kind {
        PanelKind::IidWithReplacement => {
            let mut result = [0; R2_SAMPLE_COUNT];
            for index in &mut result {
                *index = rng.next() as usize % TRAIN_SAMPLES;
            }
            result
        }
        PanelKind::IidWithoutReplacement => sample_flat_wor(&mut rng),
        PanelKind::CellWithoutReplacement => sample_stratified_wor(&mut rng, cell_index),
        PanelKind::MarginWithoutReplacement => sample_stratified_wor(&mut rng, margin_index),
        PanelKind::PlaceboWithoutReplacement(id) => {
            sample_stratified_wor(&mut rng, &placebo_indices[id as usize])
        }
    }
}

fn sample_flat_wor(rng: &mut Rng) -> [usize; R2_SAMPLE_COUNT] {
    let mut order: [usize; TRAIN_SAMPLES] = std::array::from_fn(|index| index);
    for offset in 0..R2_SAMPLE_COUNT {
        let selected = offset + rng.next() as usize % (TRAIN_SAMPLES - offset);
        order.swap(offset, selected);
    }
    order[..R2_SAMPLE_COUNT]
        .try_into()
        .expect("fixed-size sample")
}

fn sample_stratified_wor(rng: &mut Rng, strata: &StrataIndex) -> [usize; R2_SAMPLE_COUNT] {
    let mut result = [0; R2_SAMPLE_COUNT];
    let mut cursor = 0;
    for stratum in 0..CELLS {
        let population = strata.lengths[stratum];
        assert_eq!(population, TRAIN_PER_CELL);
        let mut members = strata.indices[stratum];
        for offset in 0..SAMPLES_PER_STRATUM {
            let selected = offset + rng.next() as usize % (population - offset);
            members.swap(offset, selected);
            result[cursor] = members[offset];
            cursor += 1;
        }
    }
    assert_eq!(cursor, R2_SAMPLE_COUNT);
    result
}

fn placebo_strata(partition: u64) -> [u8; TRAIN_SAMPLES] {
    let mut ranked: [(u64, usize); TRAIN_SAMPLES] =
        std::array::from_fn(|index| (mix64(index as u64 ^ PLACEBO_STREAM ^ partition), index));
    ranked.sort_unstable_by(|left, right| left.0.cmp(&right.0).then_with(|| left.1.cmp(&right.1)));
    let mut ids = [0; TRAIN_SAMPLES];
    for (rank, &(_, sample_index)) in ranked.iter().enumerate() {
        ids[sample_index] = (rank / TRAIN_PER_CELL) as u8;
    }
    ids
}

fn mix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

fn audit_panel(
    candidates: &[Candidate],
    block_count: usize,
    panel_indices: [usize; R2_SAMPLE_COUNT],
    seed: u64,
    snapshot: ReplaySnapshot,
    kind: PanelKind,
    panel: usize,
    snapshot_train_loss: f32,
    snapshot_validation_loss: f32,
) -> PanelRecord {
    let estimates: Vec<f32> = candidates
        .iter()
        .map(|candidate| {
            panel_indices
                .iter()
                .map(|&index| candidate.per_example_utility[index])
                .sum::<f32>()
                / R2_SAMPLE_COUNT as f32
        })
        .collect();
    let mut squared_error = 0.0_f64;
    let mut sign_errors = 0_u64;
    let mut sign_count = 0_u64;
    for (candidate, &estimate) in candidates.iter().zip(&estimates) {
        let difference = f64::from(estimate - candidate.exact_utility);
        squared_error += difference * difference;
        if candidate.exact_utility.abs() > UTILITY_EPSILON {
            sign_count += 1;
            sign_errors += u64::from((estimate > 0.0) != (candidate.exact_utility > 0.0));
        }
    }

    let mut exact_block_best = [0.0_f32; PARAMS];
    let mut estimated_block_best = [0.0_f32; PARAMS];
    let mut estimated_block_choice = [None; PARAMS];
    for (index, candidate) in candidates.iter().enumerate() {
        exact_block_best[candidate.block] =
            exact_block_best[candidate.block].max(candidate.exact_utility);
        if estimates[index] > estimated_block_best[candidate.block] {
            estimated_block_best[candidate.block] = estimates[index];
            estimated_block_choice[candidate.block] = Some(index);
        }
    }
    let exact_best = exact_block_best[..block_count]
        .iter()
        .copied()
        .fold(0.0_f32, f32::max);
    let mut within_sum = 0.0_f64;
    let mut within_positive_regrets = 0_u64;
    let mut selected_block = None;
    let mut selected_estimate = 0.0_f32;
    for block in 0..block_count {
        let chosen_true =
            estimated_block_choice[block].map_or(0.0, |index| candidates[index].exact_utility);
        let regret = (exact_block_best[block] - chosen_true).max(0.0);
        within_sum += f64::from(regret);
        within_positive_regrets += u64::from(regret > UTILITY_EPSILON);
        if estimated_block_best[block] > selected_estimate {
            selected_estimate = estimated_block_best[block];
            selected_block = Some(block);
        }
    }
    let selected_candidate = selected_block.and_then(|block| estimated_block_choice[block]);
    let selected_reference =
        selected_candidate.map_or(0.0, |index| candidates[index].exact_utility);
    let selected_block_reference = selected_block.map_or(0.0, |block| exact_block_best[block]);
    let cross_block_regret = (exact_best - selected_block_reference).max(0.0);
    let selected_block_within = (selected_block_reference - selected_reference).max(0.0);
    let selected_program_regret = (exact_best - selected_reference).max(0.0);
    assert!(
        (selected_program_regret - cross_block_regret - selected_block_within).abs() < 1.0e-6,
        "selected regret must decompose into cross-block and within-block components"
    );

    let (block_id, left, right, left_delta, right_delta) =
        selected_candidate.map_or((-1, -1, -1, 0.0, 0.0), |index| {
            let candidate = candidates[index];
            (
                candidate.block as i32,
                candidate.program.left as i32,
                candidate.program.right as i32,
                candidate.program.deltas[0],
                candidate.program.deltas[1],
            )
        });
    PanelRecord {
        seed,
        snapshot_step: snapshot.step,
        method: kind.name(),
        panel,
        candidate_count: candidates.len(),
        utility_rmse: (squared_error / candidates.len() as f64).sqrt(),
        sign_error_rate: if sign_count == 0 {
            0.0
        } else {
            sign_errors as f64 / sign_count as f64
        },
        within_block_regret_mean: within_sum / block_count as f64,
        within_block_positive_regret_rate: within_positive_regrets as f64 / block_count as f64,
        cross_block_opportunity_regret: f64::from(cross_block_regret),
        selected_block_within_regret: f64::from(selected_block_within),
        selected_program_regret: f64::from(selected_program_regret),
        false_positive_authorization: selected_candidate.is_some()
            && selected_estimate > 0.0
            && selected_reference <= 0.0,
        best_reference_utility: f64::from(exact_best),
        selected_estimated_utility: f64::from(selected_estimate),
        selected_reference_utility: f64::from(selected_reference),
        selected_block: block_id,
        selected_left: left,
        selected_right: right,
        selected_left_delta: left_delta,
        selected_right_delta: right_delta,
        snapshot_train_loss,
        snapshot_validation_loss,
    }
}

fn write_replay(
    path: impl AsRef<Path>,
    replay: &[(u64, ReplaySnapshot, f32, f32)],
) -> io::Result<()> {
    let mut output = BufWriter::new(std::fs::File::create(path)?);
    writeln!(
        output,
        "seed,step,train_loss,validation_loss,parameter_fingerprint"
    )?;
    for &(seed, snapshot, train_loss, validation_loss) in replay {
        writeln!(
            output,
            "{seed:016x},{},{train_loss:.9},{validation_loss:.9},{:016x}",
            snapshot.step,
            parameter_fingerprint(&snapshot.model)
        )?;
    }
    output.flush()
}

fn parameter_fingerprint(model: &Model) -> u64 {
    model
        .parameters
        .iter()
        .enumerate()
        .fold(0xcbf2_9ce4_8422_2325_u64, |hash, (index, value)| {
            (hash ^ u64::from(value.to_bits()).wrapping_add(index as u64))
                .wrapping_mul(0x0000_0100_0000_01b3)
        })
}

fn write_panels(path: impl AsRef<Path>, rows: &[PanelRecord]) -> io::Result<()> {
    let mut output = BufWriter::new(std::fs::File::create(path)?);
    writeln!(
        output,
        "seed,snapshot_step,method,panel,candidate_count,utility_rmse,sign_error_rate,within_block_regret_mean,within_block_positive_regret_rate,cross_block_opportunity_regret,selected_block_within_regret,selected_program_regret,false_positive_authorization,best_reference_utility,selected_estimated_utility,selected_reference_utility,selected_block,selected_left,selected_right,selected_left_delta,selected_right_delta,snapshot_train_loss,snapshot_validation_loss"
    )?;
    for row in rows {
        writeln!(
            output,
            "{:016x},{},{},{},{},{:.12},{:.12},{:.12},{:.12},{:.12},{:.12},{:.12},{},{:.12},{:.12},{:.12},{},{},{},{:.9},{:.9},{:.9},{:.9}",
            row.seed,
            row.snapshot_step,
            row.method,
            row.panel,
            row.candidate_count,
            row.utility_rmse,
            row.sign_error_rate,
            row.within_block_regret_mean,
            row.within_block_positive_regret_rate,
            row.cross_block_opportunity_regret,
            row.selected_block_within_regret,
            row.selected_program_regret,
            row.false_positive_authorization,
            row.best_reference_utility,
            row.selected_estimated_utility,
            row.selected_reference_utility,
            row.selected_block,
            row.selected_left,
            row.selected_right,
            row.selected_left_delta,
            row.selected_right_delta,
            row.snapshot_train_loss,
            row.snapshot_validation_loss,
        )?;
    }
    output.flush()
}

fn write_report(path: impl AsRef<Path>, rows: &[PanelRecord]) -> io::Result<()> {
    let mut output = BufWriter::new(std::fs::File::create(path)?);
    writeln!(output, "{{")?;
    writeln!(
        output,
        "  \"protocol\": \"AR-02A-R2 frozen P16/V48 K2 snapshots; panel estimator diagnostic only\","
    )?;
    writeln!(
        output,
        "  \"snapshots\": {},",
        R1_SEEDS.len() * SNAPSHOT_STEPS.len()
    )?;
    writeln!(
        output,
        "  \"panel_replicates_per_snapshot_and_method\": {PANEL_REPLICATES},"
    )?;
    writeln!(output, "  \"placebo_partitions\": {PLACEBO_PARTITIONS},")?;
    writeln!(output, "  \"rows\": {},", rows.len())?;
    writeln!(output, "  \"methods\": [")?;
    let method_names = [
        "iid_with_replacement",
        "iid_without_replacement",
        "cell_stratified_wor",
        "margin_stratified_wor",
    ];
    let mut names: Vec<String> = method_names.iter().map(|name| (*name).to_owned()).collect();
    names.extend((0..PLACEBO_PARTITIONS).map(|id| format!("hash_placebo_{id:02}")));
    for (method_index, name) in names.iter().enumerate() {
        let selected: Vec<&PanelRecord> = rows.iter().filter(|row| &row.method == name).collect();
        let count = selected.len().max(1) as f64;
        let mean = |field: fn(&PanelRecord) -> f64| {
            selected.iter().map(|row| field(row)).sum::<f64>() / count
        };
        let suffix = if method_index + 1 == names.len() {
            ""
        } else {
            ","
        };
        writeln!(
            output,
            "    {{\"method\":\"{name}\",\"n\":{},\"mean_utility_rmse\":{:.12},\"mean_sign_error_rate\":{:.9},\"mean_within_block_regret\":{:.12},\"mean_cross_block_opportunity_regret\":{:.12},\"mean_selected_program_regret\":{:.12},\"false_positive_authorization_rate\":{:.9}}}{}",
            selected.len(),
            mean(|row| row.utility_rmse),
            mean(|row| row.sign_error_rate),
            mean(|row| row.within_block_regret_mean),
            mean(|row| row.cross_block_opportunity_regret),
            mean(|row| row.selected_program_regret),
            selected
                .iter()
                .filter(|row| row.false_positive_authorization)
                .count() as f64
                / count,
            suffix,
        )?;
    }
    writeln!(output, "  ]")?;
    writeln!(output, "}}")?;
    output.flush()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn placebo_partitions_are_deterministic_and_equal_sized() {
        for partition in 0..PLACEBO_PARTITIONS {
            let first = placebo_strata(partition as u64);
            assert_eq!(first, placebo_strata(partition as u64));
            let mut counts = [0; CELLS];
            for group in first {
                counts[group as usize] += 1;
            }
            assert_eq!(counts, [TRAIN_PER_CELL; CELLS]);
        }
        assert_ne!(placebo_strata(0), placebo_strata(1));
    }

    #[test]
    fn verifier_panels_have_frozen_cardinality_and_quota_mechanics() {
        let dataset = generate_gaussian_cells();
        let train = &dataset.samples[..TRAIN_SAMPLES];
        let cell_ids = std::array::from_fn(|index| (index / TRAIN_PER_CELL) as u8);
        let margin_strata = build_margin_strata(train);
        let cell_index = StrataIndex::new(&cell_ids, CELLS);
        let margin_index = StrataIndex::new(&margin_strata.ids, MARGIN_STRATA);
        let placebo_ids = placebo_strata(0);
        let placebo_index = StrataIndex::new(&placebo_ids, CELLS);
        let placebo_indices = [placebo_index; PLACEBO_PARTITIONS];
        let random = draw_panel(
            PanelKind::IidWithoutReplacement,
            7,
            &cell_index,
            &margin_index,
            &placebo_indices,
        );
        let mut unique = [false; TRAIN_SAMPLES];
        for index in random {
            assert!(!unique[index]);
            unique[index] = true;
        }
        for kind in [
            PanelKind::CellWithoutReplacement,
            PanelKind::MarginWithoutReplacement,
            PanelKind::PlaceboWithoutReplacement(0),
        ] {
            let panel = draw_panel(kind, 7, &cell_index, &margin_index, &placebo_indices);
            let mut seen = [false; TRAIN_SAMPLES];
            let mut counts = [0; CELLS];
            for index in panel {
                assert!(!seen[index]);
                seen[index] = true;
                let group = match kind {
                    PanelKind::CellWithoutReplacement => cell_ids[index],
                    PanelKind::MarginWithoutReplacement => margin_strata.ids[index],
                    PanelKind::PlaceboWithoutReplacement(_) => placebo_ids[index],
                    _ => unreachable!(),
                };
                counts[group as usize] += 1;
            }
            assert_eq!(counts, [SAMPLES_PER_STRATUM; CELLS]);
        }
    }

    #[test]
    fn replay_matches_the_committed_r1_validation_checkpoint() {
        let dataset = generate_gaussian_cells();
        let train = &dataset.samples[..TRAIN_SAMPLES];
        let validation = &dataset.samples[TRAIN_SAMPLES..];
        let snapshot = replay_reference_trajectory(train, R1_SEEDS[0])[0];
        let row = include_str!("../../../ar-02a-r1/artifacts/ar-02a-r1-curve.csv")
            .lines()
            .find(|line| line.starts_with("p16_v48_random,2b7e151628aed2a6,600,"))
            .expect("frozen R1 checkpoint exists");
        let fields: Vec<&str> = row.split(',').collect();
        assert_eq!(snapshot.step, 600);
        assert!((snapshot.model.loss(train) - fields[3].parse::<f32>().unwrap()).abs() < 1e-7);
        assert!((snapshot.model.loss(validation) - fields[4].parse::<f32>().unwrap()).abs() < 1e-7);
    }
}

mod variance;
pub use variance::run_r2_variance_audit;
