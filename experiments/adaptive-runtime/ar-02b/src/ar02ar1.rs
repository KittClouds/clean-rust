use super::*;
use std::path::Path;
use std::time::Instant;

const R1_COMMITS: usize = 4_800;
const COMMITS_PER_EVIDENCE: usize = 4;
const AUDIT_INTERVAL: usize = 50;
const TRAIN_PER_CELL: usize = 8;
const CELLS: usize = 12;
const MARGIN_BINS: usize = 4;
const MARGIN_STRATA: usize = CLASSES * MARGIN_BINS;
const PROPOSAL_STREAM: u64 = 0x5052_4f50_4f53_414c;
const VERIFY_STREAM: u64 = 0x4152_3032_5645_5249;
const ROTATING_STRATA_STREAM: u64 = 0x5231_5354_5241_5441;

pub const R1_SEEDS: [u64; 3] = SEEDS;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VerifierKind {
    Random,
    ClassWeighted,
    CellWeighted,
    MarginWeighted,
    FullTraining,
}

impl VerifierKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Random => "random",
            Self::ClassWeighted => "class_weighted",
            Self::CellWeighted => "cell_population_weighted",
            Self::MarginWeighted => "class_bayes_margin_weighted",
            Self::FullTraining => "full_training",
        }
    }

    const fn population_strata(self) -> usize {
        match self {
            Self::ClassWeighted => CLASSES,
            Self::CellWeighted | Self::MarginWeighted => CELLS,
            Self::Random | Self::FullTraining => 0,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct R1Spec {
    pub name: &'static str,
    pub proposal_size: usize,
    pub verifier_size: usize,
    pub verifier: VerifierKind,
}

const fn spec(
    name: &'static str,
    proposal_size: usize,
    verifier_size: usize,
    verifier: VerifierKind,
) -> R1Spec {
    R1Spec {
        name,
        proposal_size,
        verifier_size,
        verifier,
    }
}

pub const R1_METHODS: [R1Spec; 11] = [
    spec("p16_v16_random", 16, 16, VerifierKind::Random),
    spec(
        "p16_v16_class_weighted",
        16,
        16,
        VerifierKind::ClassWeighted,
    ),
    spec("p16_v16_cell_weighted", 16, 16, VerifierKind::CellWeighted),
    spec(
        "p16_v16_margin_weighted",
        16,
        16,
        VerifierKind::MarginWeighted,
    ),
    spec("p16_v48_random", 16, 48, VerifierKind::Random),
    spec(
        "p16_v48_class_weighted",
        16,
        48,
        VerifierKind::ClassWeighted,
    ),
    spec("p16_v48_cell_weighted", 16, 48, VerifierKind::CellWeighted),
    spec(
        "p16_v48_margin_weighted",
        16,
        48,
        VerifierKind::MarginWeighted,
    ),
    spec("p16_v96_full", 16, 96, VerifierKind::FullTraining),
    spec("p96_v16_random", 96, 16, VerifierKind::Random),
    spec("p96_v96_full", 96, 96, VerifierKind::FullTraining),
];

#[derive(Clone, Debug)]
pub struct R1RunResult {
    pub spec: R1Spec,
    pub seed: u64,
    pub final_train_loss: f32,
    pub final_validation_loss: f32,
    pub final_train_accuracy: f32,
    pub final_validation_accuracy: f32,
    pub optimizer_steps: usize,
    pub committed_programs: u64,
    pub committed_primitives: u64,
    pub proposal_evaluations: u64,
    pub proposal_sample_evaluations: u64,
    pub compound_evaluations: u64,
    pub compound_sample_evaluations: u64,
    pub schedule_pair_events: u64,
    pub full_train_utility_sum: f64,
    pub full_train_positive_commits: u64,
    pub harmful_commits: u64,
    pub mean_harmful_magnitude: f64,
    pub p90_harmful_magnitude: f64,
    pub p95_harmful_magnitude: f64,
    pub p99_harmful_magnitude: f64,
    pub max_harmful_magnitude: f64,
    pub regret_audits: u64,
    pub full_reference_candidate_evaluations: u64,
    pub mean_sampled_reference_regret: f64,
    pub cumulative_sampled_reference_regret: f64,
    pub p90_sampled_reference_regret: f64,
    pub p95_sampled_reference_regret: f64,
    pub p99_sampled_reference_regret: f64,
    pub max_sampled_reference_regret: f64,
    pub coverage: Coverage,
    pub elapsed_seconds: f64,
    pub curve: Vec<CurvePoint>,
}

#[derive(Clone, Copy)]
struct MarginStrata {
    ids: [u8; TRAIN_SAMPLES],
    margins: [f32; TRAIN_SAMPLES],
}

#[derive(Clone, Copy)]
struct VerifierBatch {
    samples: [Sample; TRAIN_SAMPLES],
    strata: [u8; TRAIN_SAMPLES],
    len: usize,
    kind: VerifierKind,
}

impl VerifierBatch {
    fn loss(&self, model: &Model) -> f32 {
        let samples = &self.samples[..self.len];
        if matches!(self.kind, VerifierKind::Random | VerifierKind::FullTraining) {
            return model.loss(samples);
        }
        let stratum_count = self.kind.population_strata();
        let mut sums = [0.0_f32; CELLS];
        let mut counts = [0_u16; CELLS];
        for (index, &sample) in samples.iter().enumerate() {
            let stratum = match self.kind {
                VerifierKind::ClassWeighted => sample.target as usize,
                VerifierKind::CellWeighted | VerifierKind::MarginWeighted => {
                    self.strata[index] as usize
                }
                VerifierKind::Random | VerifierKind::FullTraining => unreachable!(),
            };
            sums[stratum] += sample_loss(model, sample);
            counts[stratum] += 1;
        }
        equal_stratum_mean(&sums, &counts, stratum_count)
    }
}

#[derive(Clone, Copy)]
struct StrataIndex {
    indices: [[usize; TRAIN_SAMPLES]; CELLS],
    lengths: [usize; CELLS],
}

impl StrataIndex {
    fn new(group_ids: &[u8; TRAIN_SAMPLES], group_count: usize) -> Self {
        let mut result = Self {
            indices: [[0; TRAIN_SAMPLES]; CELLS],
            lengths: [0; CELLS],
        };
        for (sample_index, &group_id) in group_ids.iter().enumerate() {
            let group = group_id as usize;
            assert!(group < group_count);
            let slot = result.lengths[group];
            result.indices[group][slot] = sample_index;
            result.lengths[group] += 1;
        }
        assert!(result.lengths[..group_count].iter().all(|&count| count > 0));
        result
    }
}

pub fn run_r1_method_for_commits(
    samples: &[Sample],
    spec: R1Spec,
    seed: u64,
    commits: usize,
) -> R1RunResult {
    assert_eq!(samples.len(), TOTAL_SAMPLES);
    assert!([16, TRAIN_SAMPLES].contains(&spec.proposal_size));
    assert!([16, 48, TRAIN_SAMPLES].contains(&spec.verifier_size));
    assert!(commits > 0 && commits.is_multiple_of(COMMITS_PER_EVIDENCE));

    let started = Instant::now();
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let margins = build_margin_strata(train);
    let mut cell_ids = [0_u8; TRAIN_SAMPLES];
    for (index, cell) in cell_ids.iter_mut().enumerate() {
        *cell = (index / TRAIN_PER_CELL) as u8;
    }
    let class_index = StrataIndex::new(
        &std::array::from_fn(|index| train[index].target as u8),
        CLASSES,
    );
    let cell_index = StrataIndex::new(&cell_ids, CELLS);
    let margin_index = StrataIndex::new(&margins.ids, MARGIN_STRATA);

    let mut model = Model::initial();
    let mut coverage = [[false; PARAMS]; PARAMS];
    let mut telemetry = Telemetry::default();
    let mut curve = Vec::with_capacity(commits / AUDIT_INTERVAL + 1);
    let mut full_train_utility_sum = 0.0_f64;
    let mut full_train_positive_commits = 0_u64;
    let mut harmful_magnitudes = Vec::with_capacity(commits / 4);
    let mut regret_values = Vec::with_capacity(commits / AUDIT_INTERVAL + 1);
    let mut full_reference_candidate_evaluations = 0_u64;
    let mut proposal_sample_evaluations = 0_u64;
    let mut compound_sample_evaluations = 0_u64;

    for evidence_round in 0..commits / COMMITS_PER_EVIDENCE {
        let mut proposal_storage = [train[0]; TRAIN_SAMPLES];
        let proposal: &[Sample] = if spec.proposal_size == TRAIN_SAMPLES {
            train
        } else {
            let ids = batch_indices(seed, evidence_round, PROPOSAL_STREAM);
            proposal_storage[..BATCH_SIZE].copy_from_slice(&indexed_samples(train, &ids));
            &proposal_storage[..BATCH_SIZE]
        };
        let verifier = make_verifier(
            train,
            spec.verifier,
            spec.verifier_size,
            seed,
            evidence_round,
            &class_index,
            &cell_index,
            &margin_index,
        );

        for inner in 0..COMMITS_PER_EVIDENCE {
            let global_commit = evidence_round * COMMITS_PER_EVIDENCE + inner;
            let (groups, group_count) = partition(global_commit % PARAMS);
            mark_coverage(&mut coverage, &groups, group_count);
            let proposal_baseline = model.loss(proposal);
            let verifier_baseline = verifier.loss(&model);
            let mut selection = Selection::default();

            for &group in &groups[..group_count] {
                let (candidate, candidate_telemetry) = select_group(
                    &model,
                    proposal,
                    proposal_baseline,
                    &verifier,
                    verifier_baseline,
                    group,
                );
                selection.telemetry.absorb(candidate_telemetry);
                if let Some(candidate) = candidate
                    && selection
                        .program
                        .is_none_or(|current| candidate.utility > current.utility)
                {
                    selection.program = Some(candidate);
                    selection.group = group;
                }
            }
            selection.telemetry.pair_events = (group_count - 1) as u64;
            telemetry.absorb(selection.telemetry);
            proposal_sample_evaluations +=
                selection.telemetry.proposal_evaluations * spec.proposal_size as u64;
            compound_sample_evaluations +=
                selection.telemetry.compound_evaluations * spec.verifier_size as u64;

            let should_audit = global_commit.is_multiple_of(AUDIT_INTERVAL);
            if should_audit {
                let full_baseline = model.loss(train);
                let (best_reference_utility, candidate_evaluations) =
                    full_reference_best(&model, train, &groups, group_count, full_baseline);
                full_reference_candidate_evaluations += candidate_evaluations;
                let selected_reference_utility = selection.program.map_or(0.0, |program| {
                    exact_program_value(&model, train, full_baseline, program)
                });
                regret_values.push(f64::from(
                    (best_reference_utility - selected_reference_utility).max(0.0),
                ));
            }

            if let Some(program) = selection.program {
                let full_before = model.loss(train);
                commit(&mut model, program);
                let selected_full_utility = full_before - model.loss(train);
                full_train_utility_sum += f64::from(selected_full_utility);
                full_train_positive_commits += u64::from(selected_full_utility > 0.0);
                if selected_full_utility < 0.0 {
                    harmful_magnitudes.push(f64::from(-selected_full_utility));
                }
                telemetry.committed_programs += 1;
                telemetry.committed_primitives += program.len as u64;
            }

            if (global_commit + 1).is_multiple_of(AUDIT_INTERVAL) || global_commit + 1 == commits {
                curve.push(CurvePoint {
                    step: global_commit + 1,
                    train_loss: model.loss(train),
                    validation_loss: model.loss(validation),
                    train_accuracy: model.accuracy(train),
                    validation_accuracy: model.accuracy(validation),
                });
            }
        }
    }

    let harmful_summary = summarize(&mut harmful_magnitudes);
    let regret_summary = summarize(&mut regret_values);
    R1RunResult {
        spec,
        seed,
        final_train_loss: model.loss(train),
        final_validation_loss: model.loss(validation),
        final_train_accuracy: model.accuracy(train),
        final_validation_accuracy: model.accuracy(validation),
        optimizer_steps: commits,
        committed_programs: telemetry.committed_programs,
        committed_primitives: telemetry.committed_primitives,
        proposal_evaluations: telemetry.proposal_evaluations,
        proposal_sample_evaluations,
        compound_evaluations: telemetry.compound_evaluations,
        compound_sample_evaluations,
        schedule_pair_events: telemetry.pair_events,
        full_train_utility_sum,
        full_train_positive_commits,
        harmful_commits: harmful_summary.count,
        mean_harmful_magnitude: harmful_summary.mean,
        p90_harmful_magnitude: harmful_summary.p90,
        p95_harmful_magnitude: harmful_summary.p95,
        p99_harmful_magnitude: harmful_summary.p99,
        max_harmful_magnitude: harmful_summary.max,
        regret_audits: regret_summary.count,
        full_reference_candidate_evaluations,
        mean_sampled_reference_regret: regret_summary.mean,
        cumulative_sampled_reference_regret: regret_summary.sum,
        p90_sampled_reference_regret: regret_summary.p90,
        p95_sampled_reference_regret: regret_summary.p95,
        p99_sampled_reference_regret: regret_summary.p99,
        max_sampled_reference_regret: regret_summary.max,
        coverage: coverage_summary(&coverage, commits),
        elapsed_seconds: started.elapsed().as_secs_f64(),
        curve,
    }
}

pub fn run_ar02a_r1(
    samples: &[Sample],
    output_dir: impl AsRef<Path>,
) -> std::io::Result<Vec<R1RunResult>> {
    let mut results = Vec::with_capacity(R1_METHODS.len() * R1_SEEDS.len());
    for spec in R1_METHODS {
        for seed in R1_SEEDS {
            let result = run_r1_method_for_commits(samples, spec, seed, R1_COMMITS);
            eprintln!(
                "AR-02A-R1 {:<28} seed {:016x}: val loss {:.6}, accuracy {:.1}%, regret p95 {:.3e}, {:.2}s",
                spec.name,
                seed,
                result.final_validation_loss,
                result.final_validation_accuracy * 100.0,
                result.p95_sampled_reference_regret,
                result.elapsed_seconds,
            );
            results.push(result);
        }
    }
    output::write_results(output_dir, samples, &results)?;
    Ok(results)
}

fn select_group(
    model: &Model,
    proposal: &[Sample],
    proposal_baseline: f32,
    verifier: &VerifierBatch,
    verifier_baseline: f32,
    group: Group,
) -> (Option<Program>, Telemetry) {
    if group.len == 1 {
        let (actions, proposal_evaluations) =
            singleton_actions(model, proposal, proposal_baseline, group.left);
        let mut best_action = Action::default();
        for action in actions {
            if action.utility > best_action.utility {
                best_action = action;
            }
        }
        let utility = single_weighted_utility(
            model,
            verifier,
            verifier_baseline,
            group.left,
            best_action.delta,
        );
        return (
            (utility > 0.0).then_some(Program {
                left: group.left,
                right: group.right,
                deltas: [best_action.delta, 0.0],
                len: 1,
                utility,
            }),
            Telemetry {
                proposal_evaluations,
                compound_evaluations: 1,
                ..Telemetry::default()
            },
        );
    }

    let (left_actions, left_proposals) =
        singleton_actions(model, proposal, proposal_baseline, group.left);
    let (right_actions, right_proposals) =
        singleton_actions(model, proposal, proposal_baseline, group.right);
    let top_left = ordered_top(&left_actions, 2);
    let top_right = ordered_top(&right_actions, 2);
    let mut best = Program {
        left: group.left,
        right: group.right,
        len: 2,
        ..Program::default()
    };
    for &left_index in &top_left[..2] {
        for &right_index in &top_right[..2] {
            let left_delta = ACTION_VALUES[left_index];
            let right_delta = ACTION_VALUES[right_index];
            let utility = pair_weighted_utility(
                model,
                verifier,
                verifier_baseline,
                group,
                left_delta,
                right_delta,
            );
            if utility > best.utility {
                best = Program {
                    left: group.left,
                    right: group.right,
                    deltas: [left_delta, right_delta],
                    len: 2,
                    utility,
                };
            }
        }
    }
    (
        (best.utility > 0.0).then_some(best),
        Telemetry {
            proposal_evaluations: left_proposals + right_proposals,
            compound_evaluations: 4,
            ..Telemetry::default()
        },
    )
}

fn pair_weighted_utility(
    model: &Model,
    verifier: &VerifierBatch,
    baseline: f32,
    group: Group,
    left_delta: f32,
    right_delta: f32,
) -> f32 {
    let left_value = model.parameters[group.left] + left_delta;
    let right_value = model.parameters[group.right] + right_delta;
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&left_value)
        || !(LOWER_BOUND..=UPPER_BOUND).contains(&right_value)
    {
        return f32::NEG_INFINITY;
    }
    let mut candidate = *model;
    candidate.parameters[group.left] = left_value;
    candidate.parameters[group.right] = right_value;
    baseline - verifier.loss(&candidate)
}

fn single_weighted_utility(
    model: &Model,
    verifier: &VerifierBatch,
    baseline: f32,
    parameter: usize,
    delta: f32,
) -> f32 {
    let value = model.parameters[parameter] + delta;
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&value) {
        return f32::NEG_INFINITY;
    }
    let mut candidate = *model;
    candidate.parameters[parameter] = value;
    baseline - verifier.loss(&candidate)
}

fn make_verifier(
    train: &[Sample],
    kind: VerifierKind,
    size: usize,
    seed: u64,
    round: usize,
    class_index: &StrataIndex,
    cell_index: &StrataIndex,
    margin_index: &StrataIndex,
) -> VerifierBatch {
    let mut result = VerifierBatch {
        samples: [train[0]; TRAIN_SAMPLES],
        strata: [0; TRAIN_SAMPLES],
        len: size,
        kind,
    };
    if kind == VerifierKind::FullTraining {
        result.samples.copy_from_slice(train);
        return result;
    }
    if kind == VerifierKind::Random {
        let mut rng = Rng::new(seed ^ VERIFY_STREAM ^ (round as u64).wrapping_mul(0x9e37_79b9));
        for sample in &mut result.samples[..size] {
            *sample = train[(rng.next() as usize) % TRAIN_SAMPLES];
        }
        return result;
    }

    let group_count = kind.population_strata();
    let strata_index = match kind {
        VerifierKind::ClassWeighted => class_index,
        VerifierKind::CellWeighted => cell_index,
        VerifierKind::MarginWeighted => margin_index,
        VerifierKind::Random | VerifierKind::FullTraining => unreachable!(),
    };
    let mut quotas = [0_usize; CELLS];
    match (kind, size) {
        (VerifierKind::ClassWeighted, 16) => {
            quotas[..CLASSES].fill(5);
            let phase = (seed ^ ROTATING_STRATA_STREAM) as usize % CLASSES;
            quotas[(phase + round) % CLASSES] += 1;
        }
        (VerifierKind::ClassWeighted, 48) => quotas[..CLASSES].fill(16),
        (_, 16) => {
            quotas[..group_count].fill(1);
            let phase = (seed ^ ROTATING_STRATA_STREAM) as usize % group_count;
            let start = (phase + round * 4) % group_count;
            for offset in 0..4 {
                quotas[(start + offset) % group_count] += 1;
            }
        }
        (_, 48) => quotas[..group_count].fill(4),
        _ => unreachable!("R1 verifier-size matrix is frozen"),
    }

    let mut rng = Rng::new(
        seed ^ ROTATING_STRATA_STREAM
            ^ 0x9e37_79b9_7f4a_7c15
            ^ (round as u64).wrapping_mul(0xd6e8_feb8_6659_fd93),
    );
    let mut cursor = 0;
    for group in 0..group_count {
        for _ in 0..quotas[group] {
            let population = strata_index.lengths[group];
            let member = (rng.next() as usize) % population;
            let sample_index = strata_index.indices[group][member];
            result.samples[cursor] = train[sample_index];
            result.strata[cursor] = group as u8;
            cursor += 1;
        }
    }
    assert_eq!(cursor, size);
    result
}

fn build_margin_strata(train: &[Sample]) -> MarginStrata {
    let mut by_class = [[0_usize; TRAIN_SAMPLES / CLASSES]; CLASSES];
    let mut class_lengths = [0_usize; CLASSES];
    for (index, sample) in train.iter().enumerate() {
        let class = sample.target as usize;
        by_class[class][class_lengths[class]] = index;
        class_lengths[class] += 1;
    }
    assert!(
        class_lengths
            .iter()
            .all(|&length| length == TRAIN_SAMPLES / CLASSES)
    );

    let mut result = MarginStrata {
        ids: [0; TRAIN_SAMPLES],
        margins: [0.0; TRAIN_SAMPLES],
    };
    for class in 0..CLASSES {
        let mut ordered = [(0.0_f32, 0_usize); TRAIN_SAMPLES / CLASSES];
        for slot in 0..TRAIN_SAMPLES / CLASSES {
            let index = by_class[class][slot];
            let margin = bayes_class_margin(train[index]);
            result.margins[index] = margin;
            ordered[slot] = (margin, index);
        }
        ordered.sort_by(|left, right| {
            left.0
                .total_cmp(&right.0)
                .then_with(|| left.1.cmp(&right.1))
        });
        for (rank, &(_, index)) in ordered.iter().enumerate() {
            result.ids[index] =
                (class * MARGIN_BINS + rank / (TRAIN_SAMPLES / MARGIN_STRATA)) as u8;
        }
    }
    result
}

fn bayes_class_margin(sample: Sample) -> f32 {
    let mut class_log_likelihoods = [f32::NEG_INFINITY; CLASSES];
    for class in 0..CLASSES {
        let mut cell_scores = [f32::NEG_INFINITY; 4];
        let mut cursor = 0;
        for cell in 0..CELLS {
            let row = cell / 3;
            let column = cell % 3;
            if (row + column) % CLASSES == class {
                cell_scores[cursor] = cell_log_score(sample, cell);
                cursor += 1;
            }
        }
        class_log_likelihoods[class] = log_sum_exp(&cell_scores);
    }
    let target = sample.target as usize;
    let competing = class_log_likelihoods
        .iter()
        .enumerate()
        .filter(|(class, _)| *class != target)
        .map(|(_, &value)| value)
        .fold(f32::NEG_INFINITY, f32::max);
    class_log_likelihoods[target] - competing
}

fn cell_log_score(sample: Sample, cell: usize) -> f32 {
    let row = cell / 3;
    let column = cell % 3;
    let center_x = -0.9 + column as f32 * 0.9;
    let center_y = -0.9 + row as f32 * 0.6;
    let angle = 0.23 + cell as f32 * 0.37;
    let (sin, cos) = angle.sin_cos();
    let dx = sample.x0 - center_x;
    let dy = sample.x1 - center_y;
    let major = dx * cos + dy * sin;
    let minor = -dx * sin + dy * cos;
    -0.5 * ((major / 0.225).powi(2) + (minor / 0.095).powi(2))
}

fn log_sum_exp(values: &[f32]) -> f32 {
    let maximum = values.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    maximum
        + values
            .iter()
            .map(|value| (*value - maximum).exp())
            .sum::<f32>()
            .ln()
}

fn sample_loss(model: &Model, sample: Sample) -> f32 {
    let (logits, _, _) = model.logits(sample);
    let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let normalizer = logits
        .iter()
        .map(|value| (*value - maximum).exp())
        .sum::<f32>();
    normalizer.ln() + maximum - logits[sample.target as usize]
}

fn equal_stratum_mean(sums: &[f32; CELLS], counts: &[u16; CELLS], stratum_count: usize) -> f32 {
    let mut total = 0.0;
    for stratum in 0..stratum_count {
        assert!(
            counts[stratum] > 0,
            "every target stratum must be represented"
        );
        total += sums[stratum] / f32::from(counts[stratum]);
    }
    total / stratum_count as f32
}

fn full_reference_best(
    model: &Model,
    train: &[Sample],
    groups: &[Group; PARAMS],
    group_count: usize,
    baseline: f32,
) -> (f32, u64) {
    let mut best_utility = 0.0_f32;
    let mut evaluations = 0_u64;
    for &group in &groups[..group_count] {
        if group.len == 2 {
            let (candidate, count) = exact_pair_program(model, train, baseline, group);
            evaluations += count;
            best_utility = best_utility.max(candidate.utility);
        } else {
            for &delta in &ACTION_VALUES {
                let utility = single_utility(model, train, baseline, group.left, delta);
                evaluations += 1;
                best_utility = best_utility.max(utility);
            }
        }
    }
    (best_utility.max(0.0), evaluations)
}

#[derive(Clone, Copy, Debug, Default)]
struct DistributionSummary {
    count: u64,
    mean: f64,
    sum: f64,
    p90: f64,
    p95: f64,
    p99: f64,
    max: f64,
}

fn summarize(values: &mut [f64]) -> DistributionSummary {
    if values.is_empty() {
        return DistributionSummary::default();
    }
    values.sort_by(f64::total_cmp);
    let sum = values.iter().sum::<f64>();
    DistributionSummary {
        count: values.len() as u64,
        mean: sum / values.len() as f64,
        sum,
        p90: quantile_sorted(values, 0.90),
        p95: quantile_sorted(values, 0.95),
        p99: quantile_sorted(values, 0.99),
        max: *values.last().expect("nonempty values"),
    }
}

fn quantile_sorted(values: &[f64], quantile: f64) -> f64 {
    let index = ((values.len() - 1) as f64 * quantile).ceil() as usize;
    values[index]
}

mod output;

#[cfg(test)]
#[path = "ar02ar1/tests.rs"]
mod tests;

mod r2;
pub use r2::{run_r2_audit, run_r2_variance_audit};

mod ar02b;
pub use ar02b::{
    PathSourceReport, SourceConditioningReport, run_path_source_crossover,
    run_path_source_crossover_with_seeds, run_source_conditioning_null,
};
