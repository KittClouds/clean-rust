use std::{fs::OpenOptions, io, mem::size_of, path::Path};

use bytemuck::{Pod, Zeroable, cast_slice};
use memchr::memmem;
use memmap2::{Mmap, MmapOptions};
use wide::f32x4;
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout};

pub const HIDDEN_1: usize = 8;
pub const HIDDEN_2: usize = 8;
pub const CLASSES: usize = 3;
pub const TRAIN_SAMPLES: usize = 96;
pub const VALIDATION_SAMPLES: usize = 48;
pub const TOTAL_SAMPLES: usize = TRAIN_SAMPLES + VALIDATION_SAMPLES;
pub const BATCH_SIZE: usize = 16;
pub const TOTAL_COMMITS: usize = 4_800;
pub const AUDIT_EVERY: usize = 50;
pub const LOWER_BOUND: f32 = -2.0;
pub const UPPER_BOUND: f32 = 2.0;
pub const ACTION_VALUES: [f32; 7] = [0.0, -0.02, 0.02, -0.01, 0.01, -0.005, 0.005];
pub const PARAMS: usize =
    2 * HIDDEN_1 + HIDDEN_1 + HIDDEN_1 * HIDDEN_2 + HIDDEN_2 + HIDDEN_2 * CLASSES + CLASSES;
const HEADER_BYTES: usize = size_of::<DatasetHeader>();
const DATASET_MAGIC: &[u8; 8] = b"AR01SPIR";
const BYE: usize = PARAMS;

#[derive(Clone, Copy, Debug, FromBytes, Immutable, IntoBytes, KnownLayout, Pod, Zeroable)]
#[repr(C)]
pub struct DatasetHeader {
    pub magic: [u8; 8],
    pub sample_count: u32,
    pub row_stride: u32,
}

#[derive(Clone, Copy, Debug, FromBytes, Immutable, IntoBytes, KnownLayout, Pod, Zeroable)]
#[repr(C)]
pub struct Sample {
    pub x0: f32,
    pub x1: f32,
    pub target: u32,
}

#[derive(Clone, Copy, Debug)]
pub struct Dataset {
    pub samples: [Sample; TOTAL_SAMPLES],
}

pub fn spiral_dataset() -> Dataset {
    let mut samples = [Sample {
        x0: 0.0,
        x1: 0.0,
        target: 0,
    }; TOTAL_SAMPLES];
    let train_per_class = TRAIN_SAMPLES / CLASSES;
    let validation_per_class = VALIDATION_SAMPLES / CLASSES;
    for split in 0..2 {
        let per_class = if split == 0 {
            train_per_class
        } else {
            validation_per_class
        };
        let base = if split == 0 { 0 } else { TRAIN_SAMPLES };
        for class in 0..CLASSES {
            for offset in 0..per_class {
                let index = base + class * per_class + offset;
                let radius = 0.15 + 0.85 * offset as f32 / (per_class - 1) as f32;
                let fraction = offset as f32 / (per_class - 1) as f32;
                let angle = fraction * 4.0 + class as f32 * 2.094_395_2;
                let jitter = 0.035 * ((offset * 17 + class * 13 + split * 29) as f32).sin();
                samples[index] = Sample {
                    x0: (radius + jitter) * angle.cos(),
                    x1: (radius + jitter) * angle.sin(),
                    target: class as u32,
                };
            }
        }
    }
    Dataset { samples }
}

pub fn write_dataset(path: impl AsRef<Path>) -> io::Result<()> {
    let dataset = spiral_dataset();
    let header = DatasetHeader {
        magic: *DATASET_MAGIC,
        sample_count: TOTAL_SAMPLES as u32,
        row_stride: size_of::<Sample>() as u32,
    };
    let mut bytes = Vec::with_capacity(HEADER_BYTES + size_of_val(&dataset.samples));
    bytes.extend_from_slice(header.as_bytes());
    bytes.extend_from_slice(cast_slice(&dataset.samples));
    if let Some(parent) = path.as_ref().parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(path, bytes)
}

pub struct MappedDataset {
    mmap: Mmap,
}

impl MappedDataset {
    pub fn open(path: impl AsRef<Path>) -> io::Result<Self> {
        let file = OpenOptions::new().read(true).open(path)?;
        // SAFETY: the file is opened read-only and the mapping is owned by Self.
        let mmap = unsafe { MmapOptions::new().map(&file)? };
        if mmap.len() < HEADER_BYTES
            || memmem::find(&mmap[..DATASET_MAGIC.len()], DATASET_MAGIC) != Some(0)
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "AR-01 dataset magic mismatch",
            ));
        }
        let header = DatasetHeader::ref_from_bytes(&mmap[..HEADER_BYTES])
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "invalid AR-01 header"))?;
        if header.row_stride as usize != size_of::<Sample>()
            || header.sample_count as usize != TOTAL_SAMPLES
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "AR-01 dataset layout mismatch",
            ));
        }
        Ok(Self { mmap })
    }

    #[inline]
    pub fn samples(&self) -> &[Sample] {
        bytemuck::try_cast_slice(&self.mmap[HEADER_BYTES..]).expect("validated AR-01 mapping")
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Model {
    pub parameters: [f32; PARAMS],
}

const W1: usize = 0;
const B1: usize = W1 + 2 * HIDDEN_1;
const W2: usize = B1 + HIDDEN_1;
const B2: usize = W2 + HIDDEN_1 * HIDDEN_2;
const W3: usize = B2 + HIDDEN_2;
const B3: usize = W3 + HIDDEN_2 * CLASSES;

impl Model {
    pub fn initial() -> Self {
        let mut parameters = [0.0; PARAMS];
        for (index, value) in parameters.iter_mut().enumerate() {
            let phase = (index as f32 * 1.371_4).sin();
            *value = 0.22 * phase + 0.03 * ((index % 5) as f32 - 2.0);
        }
        Self { parameters }
    }

    #[inline]
    #[allow(clippy::needless_range_loop)]
    fn logits(&self, sample: Sample) -> ([f32; CLASSES], [f32; HIDDEN_1], [f32; HIDDEN_2]) {
        let mut hidden_1 = [0.0; HIDDEN_1];
        for (unit, value) in hidden_1.iter_mut().enumerate() {
            let offset = W1 + unit * 2;
            *value = (self.parameters[offset] * sample.x0
                + self.parameters[offset + 1] * sample.x1
                + self.parameters[B1 + unit])
                .max(0.0);
        }
        let mut hidden_2 = [0.0; HIDDEN_2];
        for (unit, value) in hidden_2.iter_mut().enumerate() {
            let offset = W2 + unit * HIDDEN_1;
            let mut pre = self.parameters[B2 + unit];
            for input in 0..HIDDEN_1 {
                pre += self.parameters[offset + input] * hidden_1[input];
            }
            *value = pre.max(0.0);
        }
        let mut logits = [0.0; CLASSES];
        for (class, logit) in logits.iter_mut().enumerate() {
            let offset = W3 + class * HIDDEN_2;
            *logit = self.parameters[B3 + class];
            for input in 0..HIDDEN_2 {
                *logit += self.parameters[offset + input] * hidden_2[input];
            }
        }
        (logits, hidden_1, hidden_2)
    }

    #[inline]
    pub fn predict(&self, sample: Sample) -> usize {
        let (logits, _, _) = self.logits(sample);
        logits
            .iter()
            .enumerate()
            .max_by(|left, right| left.1.total_cmp(right.1))
            .map_or(0, |(index, _)| index)
    }

    pub fn loss(&self, samples: &[Sample]) -> f32 {
        assert!(!samples.is_empty());
        let mut loss = 0.0;
        for &sample in samples {
            let (logits, _, _) = self.logits(sample);
            let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
            let normalizer = logits
                .iter()
                .map(|value| (*value - maximum).exp())
                .sum::<f32>();
            loss += normalizer.ln() + maximum - logits[sample.target as usize];
        }
        loss / samples.len() as f32
    }

    pub fn gradient(&self, samples: &[Sample]) -> (f32, [f32; PARAMS]) {
        assert!(!samples.is_empty());
        let mut gradient = [0.0; PARAMS];
        let mut loss = 0.0;
        for &sample in samples {
            let (logits, hidden_1, hidden_2) = self.logits(sample);
            let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
            let normalizer = logits
                .iter()
                .map(|value| (*value - maximum).exp())
                .sum::<f32>();
            loss += normalizer.ln() + maximum - logits[sample.target as usize];
            let mut output_error = [0.0; CLASSES];
            for class in 0..CLASSES {
                output_error[class] = (logits[class] - maximum).exp() / normalizer;
            }
            output_error[sample.target as usize] -= 1.0;

            let mut hidden_2_error = [0.0; HIDDEN_2];
            for class in 0..CLASSES {
                let offset = W3 + class * HIDDEN_2;
                gradient[B3 + class] += output_error[class];
                for input in 0..HIDDEN_2 {
                    gradient[offset + input] += output_error[class] * hidden_2[input];
                    hidden_2_error[input] += output_error[class] * self.parameters[offset + input];
                }
            }
            let mut hidden_1_error = [0.0; HIDDEN_1];
            for unit in 0..HIDDEN_2 {
                let pre_positive = hidden_2[unit] > 0.0;
                let error = if pre_positive {
                    hidden_2_error[unit]
                } else {
                    0.0
                };
                gradient[B2 + unit] += error;
                let offset = W2 + unit * HIDDEN_1;
                for input in 0..HIDDEN_1 {
                    gradient[offset + input] += error * hidden_1[input];
                    hidden_1_error[input] += error * self.parameters[offset + input];
                }
            }
            for unit in 0..HIDDEN_1 {
                let error = if hidden_1[unit] > 0.0 {
                    hidden_1_error[unit]
                } else {
                    0.0
                };
                let offset = W1 + unit * 2;
                gradient[offset] += error * sample.x0;
                gradient[offset + 1] += error * sample.x1;
                gradient[B1 + unit] += error;
            }
        }
        let inverse = 1.0 / samples.len() as f32;
        for value in &mut gradient {
            *value *= inverse;
        }
        (loss * inverse, gradient)
    }

    pub fn accuracy(&self, samples: &[Sample]) -> f32 {
        let correct = samples
            .iter()
            .filter(|sample| self.predict(**sample) == sample.target as usize)
            .count();
        correct as f32 / samples.len() as f32
    }

    pub fn mse(&self, samples: &[Sample]) -> f32 {
        let mut total = f32x4::splat(0.0);
        let full = samples.len() / 4 * 4;
        for chunk in samples[..full].chunks_exact(4) {
            let values = f32x4::from([
                self.predict(chunk[0]) as f32,
                self.predict(chunk[1]) as f32,
                self.predict(chunk[2]) as f32,
                self.predict(chunk[3]) as f32,
            ]);
            let targets = f32x4::from([
                chunk[0].target as f32,
                chunk[1].target as f32,
                chunk[2].target as f32,
                chunk[3].target as f32,
            ]);
            let delta = values - targets;
            total += delta * delta;
        }
        let mut scalar = total.to_array().iter().sum::<f32>();
        for sample in &samples[full..] {
            let delta = self.predict(*sample) as f32 - sample.target as f32;
            scalar += delta * delta;
        }
        scalar / samples.len() as f32
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Arm {
    F0Verifier16,
    F1Verifier24,
    F2Verifier32,
    F3Verifier48,
    F4Verifier64,
    F5Verifier96,
    F6AdamW,
    F7Sign,
}

impl Arm {
    pub const ALL: [Self; 8] = [
        Self::F0Verifier16,
        Self::F1Verifier24,
        Self::F2Verifier32,
        Self::F3Verifier48,
        Self::F4Verifier64,
        Self::F5Verifier96,
        Self::F6AdamW,
        Self::F7Sign,
    ];

    pub const fn label(self) -> &'static str {
        match self {
            Self::F0Verifier16 => "F0-verifier-16",
            Self::F1Verifier24 => "F1-verifier-24",
            Self::F2Verifier32 => "F2-verifier-32",
            Self::F3Verifier48 => "F3-verifier-48",
            Self::F4Verifier64 => "F4-verifier-64",
            Self::F5Verifier96 => "F5-verifier-96",
            Self::F6AdamW => "F6-adamw",
            Self::F7Sign => "F7-sign",
        }
    }

    const fn beam(self) -> Option<usize> {
        match self {
            Self::F0Verifier16
            | Self::F1Verifier24
            | Self::F2Verifier32
            | Self::F3Verifier48
            | Self::F4Verifier64
            | Self::F5Verifier96 => Some(2),
            Self::F6AdamW | Self::F7Sign => None,
        }
    }

    const fn runtime(self) -> bool {
        self.beam().is_some()
    }

    const fn commits_per_evidence(self) -> usize {
        match self {
            Self::F0Verifier16
            | Self::F1Verifier24
            | Self::F2Verifier32
            | Self::F3Verifier48
            | Self::F4Verifier64
            | Self::F5Verifier96 => 8,
            Self::F6AdamW | Self::F7Sign => 1,
        }
    }

    const fn verification(self) -> VerificationEvidence {
        match self {
            Self::F0Verifier16
            | Self::F1Verifier24
            | Self::F2Verifier32
            | Self::F3Verifier48
            | Self::F4Verifier64 => VerificationEvidence::IndependentBatch,
            Self::F5Verifier96 => VerificationEvidence::FullTrain,
            Self::F6AdamW | Self::F7Sign => VerificationEvidence::SameBatch,
        }
    }

    const fn verification_size(self) -> usize {
        match self {
            Self::F0Verifier16 => BATCH_SIZE,
            Self::F1Verifier24 => 24,
            Self::F2Verifier32 => 32,
            Self::F3Verifier48 => 48,
            Self::F4Verifier64 => 64,
            Self::F5Verifier96 => TRAIN_SAMPLES,
            Self::F6AdamW | Self::F7Sign => BATCH_SIZE,
        }
    }

    const fn evidence_rounds(self) -> usize {
        TOTAL_COMMITS / self.commits_per_evidence()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum VerificationEvidence {
    SameBatch,
    IndependentBatch,
    FullTrain,
}

pub const SEEDS: [u64; 3] = [
    0x2b7e_1516_28ae_d2a6,
    0x77a1_9d3c_4e28_0b51,
    0x1111_2222_3333_4444,
];

#[derive(Clone, Copy, Debug)]
struct Rng {
    state: u64,
}

impl Rng {
    const fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    fn next(&mut self) -> u64 {
        let mut value = self.state;
        value ^= value << 7;
        value ^= value >> 9;
        value ^= value << 8;
        self.state = value;
        value
    }
}

#[derive(Clone, Copy, Debug)]
struct AdamW {
    step: u32,
    first: [f32; PARAMS],
    second: [f32; PARAMS],
}

impl AdamW {
    const fn new() -> Self {
        Self {
            step: 0,
            first: [0.0; PARAMS],
            second: [0.0; PARAMS],
        }
    }

    #[allow(clippy::needless_range_loop)]
    fn step(&mut self, model: &mut Model, gradient: &[f32; PARAMS]) {
        self.step += 1;
        let beta1 = 0.9_f32;
        let beta2 = 0.999_f32;
        let learning_rate = 0.01_f32;
        let correction_1 = 1.0 - beta1.powi(self.step as i32);
        let correction_2 = 1.0 - beta2.powi(self.step as i32);
        for index in 0..PARAMS {
            self.first[index] = beta1 * self.first[index] + (1.0 - beta1) * gradient[index];
            self.second[index] =
                beta2 * self.second[index] + (1.0 - beta2) * gradient[index] * gradient[index];
            let first_hat = self.first[index] / correction_1;
            let second_hat = self.second[index] / correction_2;
            model.parameters[index] -= learning_rate * first_hat / (second_hat.sqrt() + 1e-8);
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Telemetry {
    pub proposal_evaluations: u64,
    pub compound_evaluations: u64,
    pub committed_programs: u64,
    pub committed_primitives: u64,
    pub pair_events: u64,
}

impl Telemetry {
    fn absorb(&mut self, other: Self) {
        self.proposal_evaluations += other.proposal_evaluations;
        self.compound_evaluations += other.compound_evaluations;
        self.committed_programs += other.committed_programs;
        self.committed_primitives += other.committed_primitives;
        self.pair_events += other.pair_events;
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Coverage {
    pub ever_pairs: u64,
    pub possible_pairs: u64,
    pub rounds: u64,
}

#[derive(Clone, Copy, Debug, Default)]
struct Group {
    left: usize,
    right: usize,
    len: usize,
}

#[allow(clippy::needless_range_loop)]
fn partition(round: usize) -> ([Group; PARAMS], usize) {
    let mut order = [0usize; PARAMS + 1];
    order[0] = BYE;
    for position in 1..=PARAMS {
        order[position] = (position - 1 + round) % PARAMS;
    }
    let mut groups = [Group::default(); PARAMS];
    let mut count = 0;
    for left in 0..=(PARAMS / 2) {
        let first = order[left];
        let second = order[PARAMS - left];
        if first == BYE {
            groups[count] = Group {
                left: second,
                right: second,
                len: 1,
            };
        } else if second == BYE {
            groups[count] = Group {
                left: first,
                right: first,
                len: 1,
            };
        } else {
            groups[count] = Group {
                left: first,
                right: second,
                len: 2,
            };
        }
        count += 1;
    }
    (groups, count)
}

fn batch_indices(seed: u64, step: usize, stream: u64) -> [usize; BATCH_SIZE] {
    let mut rng = Rng::new(seed ^ stream ^ (step as u64).wrapping_mul(0x9e37_79b9));
    let mut batch = [0usize; BATCH_SIZE];
    for value in &mut batch {
        *value = (rng.next() as usize) % TRAIN_SAMPLES;
    }
    batch
}

fn indexed_samples(samples: &[Sample], indices: &[usize; BATCH_SIZE]) -> [Sample; BATCH_SIZE] {
    let mut selected = [samples[0]; BATCH_SIZE];
    for (slot, &index) in indices.iter().enumerate() {
        selected[slot] = samples[index];
    }
    selected
}

fn sized_batch_indices(
    seed: u64,
    step: usize,
    stream: u64,
    count: usize,
) -> [usize; TRAIN_SAMPLES] {
    let mut rng = Rng::new(seed ^ stream ^ (step as u64).wrapping_mul(0x9e37_79b9));
    let mut batch = [0usize; TRAIN_SAMPLES];
    for value in &mut batch[..count] {
        *value = (rng.next() as usize) % TRAIN_SAMPLES;
    }
    batch
}

fn sized_indexed_samples(
    samples: &[Sample],
    indices: &[usize; TRAIN_SAMPLES],
    count: usize,
) -> [Sample; TRAIN_SAMPLES] {
    let mut selected = [samples[0]; TRAIN_SAMPLES];
    for (slot, &index) in indices[..count].iter().enumerate() {
        selected[slot] = samples[index];
    }
    selected
}

#[derive(Clone, Copy, Debug, Default)]
struct Action {
    delta: f32,
    utility: f32,
}

#[derive(Clone, Copy, Debug, Default)]
struct Program {
    left: usize,
    right: usize,
    deltas: [f32; 2],
    len: usize,
    utility: f32,
}

#[derive(Clone, Copy, Debug, Default)]
struct Selection {
    program: Option<Program>,
    group: Group,
    telemetry: Telemetry,
}

fn ordered_top(actions: &[Action; ACTION_VALUES.len()], width: usize) -> [usize; 5] {
    let mut order = [0usize; ACTION_VALUES.len()];
    for (index, value) in order.iter_mut().enumerate() {
        *value = index;
    }
    order.sort_by(|left, right| actions[*right].utility.total_cmp(&actions[*left].utility));
    let mut top = [0usize; 5];
    for index in 0..5 {
        top[index] = order[index.min(width.saturating_sub(1))];
    }
    top
}

fn singleton_actions(
    model: &Model,
    batch: &[Sample],
    baseline: f32,
    index: usize,
) -> ([Action; ACTION_VALUES.len()], u64) {
    let mut actions = [Action::default(); ACTION_VALUES.len()];
    for (action_index, &delta) in ACTION_VALUES.iter().enumerate() {
        let candidate_value = model.parameters[index] + delta;
        if !(LOWER_BOUND..=UPPER_BOUND).contains(&candidate_value) {
            continue;
        }
        let mut candidate = *model;
        candidate.parameters[index] = candidate_value;
        actions[action_index] = Action {
            delta,
            utility: baseline - candidate.loss(batch),
        };
    }
    (actions, ACTION_VALUES.len() as u64)
}

fn pair_utility(
    model: &Model,
    batch: &[Sample],
    baseline: f32,
    group: Group,
    left: f32,
    right: f32,
) -> f32 {
    let left_value = model.parameters[group.left] + left;
    let right_value = model.parameters[group.right] + right;
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&left_value)
        || !(LOWER_BOUND..=UPPER_BOUND).contains(&right_value)
    {
        return f32::NEG_INFINITY;
    }
    let mut candidate = *model;
    candidate.parameters[group.left] = left_value;
    candidate.parameters[group.right] = right_value;
    baseline - candidate.loss(batch)
}

fn single_utility(model: &Model, batch: &[Sample], baseline: f32, index: usize, delta: f32) -> f32 {
    let value = model.parameters[index] + delta;
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&value) {
        return f32::NEG_INFINITY;
    }
    let mut candidate = *model;
    candidate.parameters[index] = value;
    baseline - candidate.loss(batch)
}

fn best_runtime_program(
    model: &Model,
    proposal_batch: &[Sample],
    verify_batch: &[Sample],
    arm: Arm,
    group: Group,
) -> (Option<Program>, Telemetry) {
    let width = arm.beam().expect("runtime arm");
    let proposal_baseline = model.loss(proposal_batch);
    let verify_baseline = model.loss(verify_batch);
    if group.len == 1 {
        let (actions, proposals) =
            singleton_actions(model, proposal_batch, proposal_baseline, group.left);
        let mut best = Action::default();
        for action in actions {
            if action.utility > best.utility {
                best = action;
            }
        }
        let utility = single_utility(model, verify_batch, verify_baseline, group.left, best.delta);
        let telemetry = Telemetry {
            proposal_evaluations: proposals,
            compound_evaluations: 1,
            ..Telemetry::default()
        };
        return (
            (utility > 0.0).then_some(Program {
                left: group.left,
                right: group.right,
                deltas: [best.delta, 0.0],
                len: 1,
                utility,
            }),
            telemetry,
        );
    }

    let (left_actions, left_proposals) =
        singleton_actions(model, proposal_batch, proposal_baseline, group.left);
    let (right_actions, right_proposals) =
        singleton_actions(model, proposal_batch, proposal_baseline, group.right);
    let top_left = ordered_top(&left_actions, width);
    let top_right = ordered_top(&right_actions, width);
    let mut best = Program {
        left: group.left,
        right: group.right,
        len: 2,
        ..Program::default()
    };
    let mut compound_evaluations = 0;
    for &left in &top_left[..width] {
        for &right in &top_right[..width] {
            let utility = pair_utility(
                model,
                verify_batch,
                verify_baseline,
                group,
                ACTION_VALUES[left],
                ACTION_VALUES[right],
            );
            compound_evaluations += 1;
            if utility > best.utility {
                best = Program {
                    left: group.left,
                    right: group.right,
                    deltas: [ACTION_VALUES[left], ACTION_VALUES[right]],
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
            compound_evaluations,
            ..Telemetry::default()
        },
    )
}

fn same_program(left: Option<Program>, right: Option<Program>) -> bool {
    match (left, right) {
        (Some(left), Some(right)) => {
            left.left == right.left && left.right == right.right && left.deltas == right.deltas
        }
        (None, None) => true,
        _ => false,
    }
}

fn exact_pair_program(
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
) -> (Program, u64) {
    let mut best = Program {
        left: group.left,
        right: group.right,
        len: 2,
        ..Program::default()
    };
    let mut evaluations = 0;
    for &left in &ACTION_VALUES {
        for &right in &ACTION_VALUES {
            let utility = pair_utility(model, samples, baseline, group, left, right);
            evaluations += 1;
            if utility > best.utility {
                best = Program {
                    left: group.left,
                    right: group.right,
                    deltas: [left, right],
                    len: 2,
                    utility,
                };
            }
        }
    }
    (best, evaluations)
}

fn exact_program_value(model: &Model, samples: &[Sample], baseline: f32, program: Program) -> f32 {
    if program.len == 1 {
        single_utility(model, samples, baseline, program.left, program.deltas[0])
    } else {
        pair_utility(
            model,
            samples,
            baseline,
            Group {
                left: program.left,
                right: program.right,
                len: 2,
            },
            program.deltas[0],
            program.deltas[1],
        )
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct AuditSummary {
    pub snapshots: u64,
    pub reference_evaluations: u64,
    pub shortlist_misses: u64,
    pub verification_noise: u64,
    pub scheduler_misorders: u64,
    pub mean_reference_regret: f32,
    pub max_reference_regret: f32,
}

impl AuditSummary {
    fn add(&mut self, other: Self) {
        self.snapshots += other.snapshots;
        self.reference_evaluations += other.reference_evaluations;
        self.shortlist_misses += other.shortlist_misses;
        self.verification_noise += other.verification_noise;
        self.scheduler_misorders += other.scheduler_misorders;
        self.mean_reference_regret += other.mean_reference_regret;
        self.max_reference_regret = self.max_reference_regret.max(other.max_reference_regret);
    }

    fn finalize(mut self) -> Self {
        if self.snapshots > 0 {
            self.mean_reference_regret /= self.snapshots as f32;
        }
        self
    }
}

fn audit_snapshot(
    model: &Model,
    train: &[Sample],
    proposal_batch: &[Sample],
    arm: Arm,
    groups: &[Group; PARAMS],
    group_count: usize,
    selected: Selection,
) -> AuditSummary {
    let Some(width) = arm.beam() else {
        return AuditSummary::default();
    };
    let reference_baseline = model.loss(train);
    let mut reference_best = Program::default();
    let mut reference_best_group = Group::default();
    let mut reference_best_value = 0.0;
    let mut reference_evaluations = 0;
    let mut reference_blocks = [(Group::default(), Program::default()); PARAMS];
    let mut pair_count = 0;
    for &group in &groups[..group_count] {
        if group.len != 2 {
            continue;
        }
        let (program, evaluations) = exact_pair_program(model, train, reference_baseline, group);
        reference_evaluations += evaluations;
        reference_blocks[pair_count] = (group, program);
        if program.utility > reference_best_value {
            reference_best = program;
            reference_best_group = group;
            reference_best_value = program.utility;
        }
        pair_count += 1;
    }

    let (best_left, _) = singleton_actions(
        model,
        proposal_batch,
        model.loss(proposal_batch),
        reference_best_group.left,
    );
    let (best_right, _) = singleton_actions(
        model,
        proposal_batch,
        model.loss(proposal_batch),
        reference_best_group.right,
    );
    let top_left = ordered_top(&best_left, width);
    let top_right = ordered_top(&best_right, width);
    let left_kept = ACTION_VALUES
        .iter()
        .position(|value| (*value - reference_best.deltas[0]).abs() < 1e-7)
        .is_some_and(|index| top_left[..width].contains(&index));
    let right_kept = ACTION_VALUES
        .iter()
        .position(|value| (*value - reference_best.deltas[1]).abs() < 1e-7)
        .is_some_and(|index| top_right[..width].contains(&index));
    let shortlist_miss = u64::from(!(left_kept && right_kept));

    let selected_reference_value = selected.program.map_or(0.0, |program| {
        exact_program_value(model, train, reference_baseline, program)
    });
    let regret = (reference_best_value - selected_reference_value).max(0.0);
    let mut verification_noise = 0;
    let mut scheduler_misorders = 0;
    if let Some(selected_program) = selected.program {
        let selected_group = selected.group;
        let selected_reference = (0..pair_count)
            .find(|&index| {
                reference_blocks[index].0.left == selected_group.left
                    && reference_blocks[index].0.right == selected_group.right
            })
            .map(|index| reference_blocks[index].1);
        if selected_group.len == 2 && !same_program(Some(selected_program), selected_reference) {
            verification_noise = 1;
        } else if selected_group.len == 2
            && (selected_group.left != reference_best_group.left
                || selected_group.right != reference_best_group.right)
        {
            scheduler_misorders = 1;
        }
    }
    AuditSummary {
        snapshots: 1,
        reference_evaluations,
        shortlist_misses: shortlist_miss,
        verification_noise,
        scheduler_misorders,
        mean_reference_regret: regret,
        max_reference_regret: regret,
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct CurvePoint {
    pub step: usize,
    pub train_loss: f32,
    pub validation_loss: f32,
    pub train_accuracy: f32,
    pub validation_accuracy: f32,
}

#[derive(Clone, Debug)]
pub struct RunSummary {
    pub arm: Arm,
    pub seed: u64,
    pub final_train_loss: f32,
    pub final_validation_loss: f32,
    pub final_train_accuracy: f32,
    pub final_validation_accuracy: f32,
    pub final_mse: f32,
    pub telemetry: Telemetry,
    pub coverage: Coverage,
    pub audit: AuditSummary,
    pub curve: Vec<CurvePoint>,
}

fn commit(model: &mut Model, program: Program) {
    model.parameters[program.left] =
        (model.parameters[program.left] + program.deltas[0]).clamp(LOWER_BOUND, UPPER_BOUND);
    if program.len == 2 {
        model.parameters[program.right] =
            (model.parameters[program.right] + program.deltas[1]).clamp(LOWER_BOUND, UPPER_BOUND);
    }
}

fn update_sign(model: &mut Model, gradient: &[f32; PARAMS]) {
    for (parameter, &value) in model.parameters.iter_mut().zip(gradient) {
        let delta = if value > 0.0 {
            -0.02
        } else if value < 0.0 {
            0.02
        } else {
            0.0
        };
        *parameter = (*parameter + delta).clamp(LOWER_BOUND, UPPER_BOUND);
    }
}

fn mark_coverage(
    coverage: &mut [[bool; PARAMS]; PARAMS],
    groups: &[Group; PARAMS],
    count: usize,
) -> u64 {
    let mut events = 0;
    for &group in &groups[..count] {
        if group.len == 2 {
            coverage[group.left][group.right] = true;
            coverage[group.right][group.left] = true;
            events += 1;
        }
    }
    events
}

#[allow(clippy::needless_range_loop)]
fn coverage_summary(coverage: &[[bool; PARAMS]; PARAMS], rounds: usize) -> Coverage {
    let mut seen = 0;
    for left in 0..PARAMS {
        for right in left + 1..PARAMS {
            seen += u64::from(coverage[left][right]);
        }
    }
    Coverage {
        ever_pairs: seen,
        possible_pairs: (PARAMS * (PARAMS - 1) / 2) as u64,
        rounds: rounds as u64,
    }
}

pub fn run(samples: &[Sample], arm: Arm, seed: u64) -> RunSummary {
    assert_eq!(samples.len(), TOTAL_SAMPLES);
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let mut model = Model::initial();
    let mut optimizer = AdamW::new();
    let mut telemetry = Telemetry::default();
    let mut coverage = [[false; PARAMS]; PARAMS];
    let mut audit = AuditSummary::default();
    let mut curve = Vec::with_capacity(TOTAL_COMMITS / 10 + 1);

    for evidence_round in 0..arm.evidence_rounds() {
        let proposal_indices = batch_indices(seed, evidence_round, 0x5052_4f50_4f53_414c);
        let proposal_storage = indexed_samples(train, &proposal_indices);
        if arm == Arm::F6AdamW {
            let (_, gradient) = model.gradient(&proposal_storage);
            optimizer.step(&mut model, &gradient);
        } else if arm == Arm::F7Sign {
            let (_, gradient) = model.gradient(&proposal_storage);
            update_sign(&mut model, &gradient);
        } else {
            let verify_size = arm.verification_size();
            let independent_indices =
                sized_batch_indices(seed, evidence_round, 0x5645_5249_4659_5354, verify_size);
            let independent_storage =
                sized_indexed_samples(train, &independent_indices, verify_size);
            let verify_storage: &[Sample] = match arm.verification() {
                VerificationEvidence::SameBatch => &proposal_storage,
                VerificationEvidence::IndependentBatch => &independent_storage[..verify_size],
                VerificationEvidence::FullTrain => train,
            };
            for commit_index in 0..arm.commits_per_evidence() {
                let global_commit = evidence_round * arm.commits_per_evidence() + commit_index;
                let (groups, group_count) = partition(global_commit % PARAMS);
                mark_coverage(&mut coverage, &groups, group_count);
                let mut selection = Selection {
                    group: Group::default(),
                    ..Selection::default()
                };
                for &group in &groups[..group_count] {
                    let (candidate, candidate_telemetry) =
                        best_runtime_program(&model, &proposal_storage, verify_storage, arm, group);
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
                if global_commit.is_multiple_of(AUDIT_EVERY) {
                    audit.add(audit_snapshot(
                        &model,
                        train,
                        &proposal_storage,
                        arm,
                        &groups,
                        group_count,
                        selection,
                    ));
                }
                if let Some(program) = selection.program {
                    telemetry.committed_programs += 1;
                    telemetry.committed_primitives += program.len as u64;
                    commit(&mut model, program);
                }
            }
        }
        let completed_commits = (evidence_round + 1) * arm.commits_per_evidence();
        if completed_commits.is_multiple_of(10) || completed_commits == TOTAL_COMMITS {
            curve.push(CurvePoint {
                step: completed_commits - 1,
                train_loss: model.loss(train),
                validation_loss: model.loss(validation),
                train_accuracy: model.accuracy(train),
                validation_accuracy: model.accuracy(validation),
            });
        }
    }

    RunSummary {
        arm,
        seed,
        final_train_loss: model.loss(train),
        final_validation_loss: model.loss(validation),
        final_train_accuracy: model.accuracy(train),
        final_validation_accuracy: model.accuracy(validation),
        final_mse: model.mse(validation),
        telemetry,
        coverage: coverage_summary(&coverage, if arm.runtime() { TOTAL_COMMITS } else { 0 }),
        audit: audit.finalize(),
        curve,
    }
}

pub fn run_all(samples: &[Sample]) -> Vec<RunSummary> {
    let mut results = Vec::with_capacity(Arm::ALL.len() * SEEDS.len());
    for arm in Arm::ALL {
        for seed in SEEDS {
            results.push(run(samples, arm, seed));
        }
    }
    results
}

pub fn dataset_for_tests() -> Dataset {
    spiral_dataset()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_robin_pairing_covers_all_pairs() {
        let mut coverage = [[false; PARAMS]; PARAMS];
        for round in 0..PARAMS {
            let (groups, count) = partition(round);
            mark_coverage(&mut coverage, &groups, count);
        }
        assert!((0..PARAMS).all(|left| (left + 1..PARAMS).all(|right| coverage[left][right])));
    }

    #[test]
    fn dataset_mapping_round_trips() {
        let path = std::env::temp_dir().join(format!("ar01a-{}.bin", std::process::id()));
        write_dataset(&path).expect("write dataset");
        let mapped = MappedDataset::open(&path).expect("map dataset");
        assert_eq!(mapped.samples().len(), TOTAL_SAMPLES);
        assert!(
            mapped
                .samples()
                .iter()
                .all(|sample| (sample.target as usize) < CLASSES)
        );
        std::fs::remove_file(path).expect("remove dataset");
    }

    #[test]
    fn short_runtime_run_commits_a_program() {
        let dataset = spiral_dataset();
        let result = run(&dataset.samples, Arm::F2Verifier32, SEEDS[0]);
        assert!(result.telemetry.committed_programs > 0);
        assert!(result.telemetry.compound_evaluations > 0);
        assert!(result.coverage.ever_pairs > 0);
    }
}
