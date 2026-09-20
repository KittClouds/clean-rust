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
const MAX_VERIFY_BATCHES: usize = 6;
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

#[derive(
    Clone, Copy, Debug, PartialEq, FromBytes, Immutable, IntoBytes, KnownLayout, Pod, Zeroable,
)]
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
            let pre = self.parameters[offset] * sample.x0
                + self.parameters[offset + 1] * sample.x1
                + self.parameters[B1 + unit];
            #[cfg(feature = "tanh")]
            let activation = pre.tanh();
            #[cfg(not(feature = "tanh"))]
            let activation = pre.max(0.0);
            *value = activation;
        }
        let mut hidden_2 = [0.0; HIDDEN_2];
        for (unit, value) in hidden_2.iter_mut().enumerate() {
            let offset = W2 + unit * HIDDEN_1;
            let mut pre = self.parameters[B2 + unit];
            for input in 0..HIDDEN_1 {
                pre += self.parameters[offset + input] * hidden_1[input];
            }
            #[cfg(feature = "tanh")]
            let activation = pre.tanh();
            #[cfg(not(feature = "tanh"))]
            let activation = pre.max(0.0);
            *value = activation;
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
                #[cfg(feature = "tanh")]
                let error = hidden_2_error[unit] * (1.0 - hidden_2[unit] * hidden_2[unit]);
                #[cfg(not(feature = "tanh"))]
                let error = if hidden_2[unit] > 0.0 {
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
                #[cfg(feature = "tanh")]
                let error = hidden_1_error[unit] * (1.0 - hidden_1[unit] * hidden_1[unit]);
                #[cfg(not(feature = "tanh"))]
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
    G0FullTrain,
    G1Random64,
    G2Balanced64,
    G3Stratified64,
    G4FixedFull96,
    G5Aggregate3x32,
    G6Aggregate2x48,
    G7Aggregate6x16,
    G8AdamW,
    G9Sign,
}

impl Arm {
    pub const ALL: [Self; 10] = [
        Self::G0FullTrain,
        Self::G1Random64,
        Self::G2Balanced64,
        Self::G3Stratified64,
        Self::G4FixedFull96,
        Self::G5Aggregate3x32,
        Self::G6Aggregate2x48,
        Self::G7Aggregate6x16,
        Self::G8AdamW,
        Self::G9Sign,
    ];

    pub const fn label(self) -> &'static str {
        match self {
            Self::G0FullTrain => "G0-full-96",
            Self::G1Random64 => "G1-random-64",
            Self::G2Balanced64 => "G2-balanced-64",
            Self::G3Stratified64 => "G3-stratified-64",
            Self::G4FixedFull96 => "G4-fixed-full-96",
            Self::G5Aggregate3x32 => "G5-aggregate-3x32",
            Self::G6Aggregate2x48 => "G6-aggregate-2x48",
            Self::G7Aggregate6x16 => "G7-aggregate-6x16",
            Self::G8AdamW => "G8-adamw",
            Self::G9Sign => "G9-sign",
        }
    }

    const fn beam(self) -> Option<usize> {
        match self {
            Self::G0FullTrain
            | Self::G1Random64
            | Self::G2Balanced64
            | Self::G3Stratified64
            | Self::G4FixedFull96
            | Self::G5Aggregate3x32
            | Self::G6Aggregate2x48
            | Self::G7Aggregate6x16 => Some(2),
            Self::G8AdamW | Self::G9Sign => None,
        }
    }

    const fn runtime(self) -> bool {
        self.beam().is_some()
    }

    const fn commits_per_evidence(self) -> usize {
        match self {
            Self::G0FullTrain
            | Self::G1Random64
            | Self::G2Balanced64
            | Self::G3Stratified64
            | Self::G4FixedFull96
            | Self::G5Aggregate3x32
            | Self::G6Aggregate2x48
            | Self::G7Aggregate6x16 => 4,
            Self::G8AdamW | Self::G9Sign => 1,
        }
    }

    const fn verification(self) -> VerificationEvidence {
        match self {
            Self::G0FullTrain | Self::G4FixedFull96 => VerificationEvidence::FullTrain,
            Self::G1Random64
            | Self::G2Balanced64
            | Self::G3Stratified64
            | Self::G5Aggregate3x32
            | Self::G6Aggregate2x48
            | Self::G7Aggregate6x16 => VerificationEvidence::IndependentBatch,
            Self::G8AdamW | Self::G9Sign => VerificationEvidence::SameBatch,
        }
    }

    const fn verification_size(self) -> usize {
        match self {
            Self::G0FullTrain | Self::G4FixedFull96 => TRAIN_SAMPLES,
            Self::G1Random64 | Self::G2Balanced64 | Self::G3Stratified64 => 64,
            Self::G5Aggregate3x32 => 32,
            Self::G6Aggregate2x48 => 48,
            Self::G7Aggregate6x16 => BATCH_SIZE,
            Self::G8AdamW | Self::G9Sign => BATCH_SIZE,
        }
    }

    const fn verification_components(self) -> usize {
        match self {
            Self::G5Aggregate3x32 => 3,
            Self::G6Aggregate2x48 => 2,
            Self::G7Aggregate6x16 => 6,
            _ => 1,
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

fn fill_random_verifier(
    destination: &mut [Sample; TRAIN_SAMPLES],
    train: &[Sample],
    seed: u64,
    round: usize,
    stream: u64,
    count: usize,
) {
    let indices = sized_batch_indices(seed, round, stream, count);
    *destination = sized_indexed_samples(train, &indices, count);
}

fn fill_balanced_verifier(
    destination: &mut [Sample; TRAIN_SAMPLES],
    train: &[Sample],
    seed: u64,
    round: usize,
    count: usize,
) {
    let mut rng = Rng::new(seed ^ 0x4241_4c41_4e43_4544 ^ (round as u64).wrapping_mul(0x9e37_79b9));
    let per_class = TRAIN_SAMPLES / CLASSES;
    let base = count / CLASSES;
    let remainder = count % CLASSES;
    let mut cursor = 0;
    for class in 0..CLASSES {
        let class_count = base + usize::from(class < remainder);
        for _ in 0..class_count {
            let offset = (rng.next() as usize) % per_class;
            destination[cursor] = train[class * per_class + offset];
            cursor += 1;
        }
    }
}

fn fill_stratified_verifier(
    destination: &mut [Sample; TRAIN_SAMPLES],
    train: &[Sample],
    seed: u64,
    round: usize,
    count: usize,
) {
    let mut rng = Rng::new(seed ^ 0x5354_5241_5449_4649 ^ (round as u64).wrapping_mul(0x9e37_79b9));
    let per_class = TRAIN_SAMPLES / CLASSES;
    let strata = 8;
    for (slot, destination) in destination.iter_mut().take(count).enumerate() {
        let class = slot % CLASSES;
        let stratum = (slot / CLASSES) % strata;
        let offset = stratum * (per_class / strata) + (rng.next() as usize % (per_class / strata));
        *destination = train[class * per_class + offset];
    }
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

fn aggregate_loss(model: &Model, batches: &[&[Sample]]) -> f32 {
    batches.iter().map(|batch| model.loss(batch)).sum::<f32>() / batches.len() as f32
}

fn pair_utility_aggregate(
    model: &Model,
    batches: &[&[Sample]],
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
    baseline - aggregate_loss(&candidate, batches)
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

fn single_utility_aggregate(
    model: &Model,
    batches: &[&[Sample]],
    baseline: f32,
    index: usize,
    delta: f32,
) -> f32 {
    let value = model.parameters[index] + delta;
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&value) {
        return f32::NEG_INFINITY;
    }
    let mut candidate = *model;
    candidate.parameters[index] = value;
    baseline - aggregate_loss(&candidate, batches)
}

fn best_runtime_program(
    model: &Model,
    proposal_batch: &[Sample],
    verify_batches: &[&[Sample]],
    arm: Arm,
    group: Group,
) -> (Option<Program>, Telemetry) {
    let width = arm.beam().expect("runtime arm");
    let proposal_baseline = model.loss(proposal_batch);
    let verify_baseline = aggregate_loss(model, verify_batches);
    if group.len == 1 {
        let (actions, proposals) =
            singleton_actions(model, proposal_batch, proposal_baseline, group.left);
        let mut best = Action::default();
        for action in actions {
            if action.utility > best.utility {
                best = action;
            }
        }
        let utility = single_utility_aggregate(
            model,
            verify_batches,
            verify_baseline,
            group.left,
            best.delta,
        );
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
            let utility = pair_utility_aggregate(
                model,
                verify_batches,
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
        if arm == Arm::G8AdamW {
            let (_, gradient) = model.gradient(&proposal_storage);
            optimizer.step(&mut model, &gradient);
        } else if arm == Arm::G9Sign {
            let (_, gradient) = model.gradient(&proposal_storage);
            update_sign(&mut model, &gradient);
        } else {
            let verify_size = arm.verification_size();
            let component_count = arm.verification_components();
            let mut verify_storage = [[train[0]; TRAIN_SAMPLES]; MAX_VERIFY_BATCHES];
            match arm {
                Arm::G1Random64 => fill_random_verifier(
                    &mut verify_storage[0],
                    train,
                    seed,
                    evidence_round,
                    0x5645_5249_4644_4f4d,
                    verify_size,
                ),
                Arm::G2Balanced64 => fill_balanced_verifier(
                    &mut verify_storage[0],
                    train,
                    seed,
                    evidence_round,
                    verify_size,
                ),
                Arm::G3Stratified64 => fill_stratified_verifier(
                    &mut verify_storage[0],
                    train,
                    seed,
                    evidence_round,
                    verify_size,
                ),
                Arm::G5Aggregate3x32 | Arm::G6Aggregate2x48 | Arm::G7Aggregate6x16 => {
                    for (component, storage) in
                        verify_storage.iter_mut().take(component_count).enumerate()
                    {
                        fill_random_verifier(
                            storage,
                            train,
                            seed,
                            evidence_round,
                            0x5645_5249_4644_4f4d ^ (component as u64).wrapping_mul(0x9e37_79b9),
                            verify_size,
                        );
                    }
                }
                Arm::G0FullTrain | Arm::G4FixedFull96 | Arm::G8AdamW | Arm::G9Sign => {}
            }
            let mut verify_batches: [&[Sample]; MAX_VERIFY_BATCHES] = [train; MAX_VERIFY_BATCHES];
            if !matches!(arm.verification(), VerificationEvidence::FullTrain) {
                for component in 0..component_count {
                    verify_batches[component] = &verify_storage[component][..verify_size];
                }
            }
            let verify_batches = &verify_batches[..component_count];
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
                        best_runtime_program(&model, &proposal_storage, verify_batches, arm, group);
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

pub const DIAGNOSTIC_EVERY: usize = 50;
pub const DIAGNOSTIC_COMMITS_PER_EVIDENCE: usize = 4;
pub const DIAGNOSTIC_SNAPSHOTS: usize = TOTAL_COMMITS / DIAGNOSTIC_EVERY;
pub const DIAGNOSTIC_FAMILY_COUNT: usize = 4;
pub const DIAGNOSTIC_FAMILY_OFFSETS: [usize; DIAGNOSTIC_FAMILY_COUNT] = [0, 6, 9, 11];
pub const DIAGNOSTIC_FAMILY_COUNTS: [usize; DIAGNOSTIC_FAMILY_COUNT] = [6, 3, 2, 1];
pub const DIAGNOSTIC_FAMILY_SIZES: [usize; DIAGNOSTIC_FAMILY_COUNT] = [16, 32, 48, 96];
const DIAGNOSTIC_COMPONENTS: usize = 12;

#[derive(Clone, Copy, Debug, Default)]
struct DiagnosticFamilyAccumulator {
    snapshots: u64,
    sign_total: u64,
    sign_matches: u64,
    selected_samples: u64,
    selected_stddev_sum: f64,
    selected_snr_sum: f64,
    selected_positive_probability_sum: f64,
    selected_regret_sum: f64,
    selected_max_regret: f64,
    selected_block_matches: u64,
    selected_program_matches: u64,
    selected_winner_agreement_sum: f64,
    selected_mean_utility_error_sum: f64,
    component_winner_matches: u64,
    component_winner_total: u64,
    family_block_matches: u64,
    family_block_total: u64,
    family_block_value_error_sum: f64,
    component_block_matches: u64,
    component_block_total: u64,
    regret_stddev_sum: f64,
    regret_stddev_squared_sum: f64,
    regret_inverse_snr_sum: f64,
    regret_inverse_snr_squared_sum: f64,
    regret_sum: f64,
    regret_squared_sum: f64,
    regret_stddev_product_sum: f64,
    regret_inverse_snr_product_sum: f64,
}

impl DiagnosticFamilyAccumulator {
    #[allow(clippy::too_many_arguments)]
    fn add_selected(
        &mut self,
        stddev: f64,
        snr: f64,
        positive_probability: f64,
        regret: f64,
        selected_utility: f64,
        reference_utility: f64,
        winner_agreement: f64,
        block_matches: bool,
        program_matches: bool,
    ) {
        self.selected_samples += 1;
        self.selected_stddev_sum += stddev;
        self.selected_snr_sum += snr;
        self.selected_positive_probability_sum += positive_probability;
        self.selected_regret_sum += regret;
        self.selected_max_regret = self.selected_max_regret.max(regret);
        self.selected_block_matches += u64::from(block_matches);
        self.selected_program_matches += u64::from(program_matches);
        self.selected_winner_agreement_sum += winner_agreement;
        self.selected_mean_utility_error_sum += (selected_utility - reference_utility).abs();

        let inverse_snr = if snr.is_finite() {
            1.0 / (snr + 1.0e-9)
        } else {
            0.0
        };
        self.regret_stddev_sum += stddev;
        self.regret_stddev_squared_sum += stddev * stddev;
        self.regret_inverse_snr_sum += inverse_snr;
        self.regret_inverse_snr_squared_sum += inverse_snr * inverse_snr;
        self.regret_sum += regret;
        self.regret_squared_sum += regret * regret;
        self.regret_stddev_product_sum += stddev * regret;
        self.regret_inverse_snr_product_sum += inverse_snr * regret;
    }

    fn finalize(self) -> DiagnosticFamilySummary {
        let selected = self.selected_samples as f64;
        let sign_total = self.sign_total as f64;
        let component_total = self.component_winner_total as f64;
        let block_total = self.family_block_total as f64;
        DiagnosticFamilySummary {
            snapshots: self.snapshots,
            sign_reliability: ratio(self.sign_matches as f64, sign_total),
            sign_total: self.sign_total,
            sign_matches: self.sign_matches,
            selected_samples: self.selected_samples,
            mean_selected_stddev: self.selected_stddev_sum / selected.max(1.0),
            mean_selected_snr: self.selected_snr_sum / selected.max(1.0),
            mean_selected_positive_probability: self.selected_positive_probability_sum
                / selected.max(1.0),
            mean_selected_reference_regret: self.selected_regret_sum / selected.max(1.0),
            max_selected_reference_regret: self.selected_max_regret,
            selected_block_match_rate: ratio(self.selected_block_matches as f64, selected),
            selected_program_match_rate: ratio(self.selected_program_matches as f64, selected),
            mean_selected_winner_agreement: self.selected_winner_agreement_sum / selected.max(1.0),
            mean_selected_utility_error: self.selected_mean_utility_error_sum / selected.max(1.0),
            component_winner_match_rate: ratio(
                self.component_winner_matches as f64,
                component_total,
            ),
            component_winner_matches: self.component_winner_matches,
            component_winner_total: self.component_winner_total,
            family_best_block_match_rate: ratio(self.family_block_matches as f64, block_total),
            family_best_block_matches: self.family_block_matches,
            family_best_block_total: self.family_block_total,
            mean_family_block_value_error: self.family_block_value_error_sum / block_total.max(1.0),
            component_best_block_match_rate: ratio(
                self.component_block_matches as f64,
                self.component_block_total as f64,
            ),
            component_best_block_matches: self.component_block_matches,
            component_best_block_total: self.component_block_total,
            regret_stddev_correlation: correlation(
                self.regret_stddev_sum,
                self.regret_stddev_squared_sum,
                self.regret_sum,
                self.regret_squared_sum,
                self.regret_stddev_product_sum,
                self.selected_samples,
            ),
            regret_inverse_snr_correlation: correlation(
                self.regret_inverse_snr_sum,
                self.regret_inverse_snr_squared_sum,
                self.regret_sum,
                self.regret_squared_sum,
                self.regret_inverse_snr_product_sum,
                self.selected_samples,
            ),
        }
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct DiagnosticFamilySummary {
    pub snapshots: u64,
    pub sign_reliability: f64,
    pub sign_total: u64,
    pub sign_matches: u64,
    pub selected_samples: u64,
    pub mean_selected_stddev: f64,
    pub mean_selected_snr: f64,
    pub mean_selected_positive_probability: f64,
    pub mean_selected_reference_regret: f64,
    pub max_selected_reference_regret: f64,
    pub selected_block_match_rate: f64,
    pub selected_program_match_rate: f64,
    pub mean_selected_winner_agreement: f64,
    pub mean_selected_utility_error: f64,
    pub component_winner_match_rate: f64,
    pub component_winner_matches: u64,
    pub component_winner_total: u64,
    pub family_best_block_match_rate: f64,
    pub family_best_block_matches: u64,
    pub family_best_block_total: u64,
    pub mean_family_block_value_error: f64,
    pub component_best_block_match_rate: f64,
    pub component_best_block_matches: u64,
    pub component_best_block_total: u64,
    pub regret_stddev_correlation: f64,
    pub regret_inverse_snr_correlation: f64,
}

#[derive(Clone, Copy, Debug, Default)]
struct SelectedShadow {
    mean_utility: f64,
    stddev: f64,
    snr: f64,
    positive_probability: f64,
    winner_agreement: f64,
    candidate_matches_reference: bool,
}

#[derive(Clone, Copy, Debug, Default)]
struct DiagnosticSnapshot {
    reference_best_group: Group,
    reference_best_candidate: usize,
    selected_group: Group,
    selected_candidate: usize,
    selected_present: bool,
}

#[derive(Clone, Debug)]
pub struct DiagnosticSummary {
    pub seed: u64,
    pub snapshots: u64,
    pub shadow_evaluations: u64,
    pub reference_evaluations: u64,
    pub final_train_loss: f32,
    pub final_validation_loss: f32,
    pub final_train_accuracy: f32,
    pub final_validation_accuracy: f32,
    pub families: [DiagnosticFamilySummary; DIAGNOSTIC_FAMILY_COUNT],
    pub selected_block_match_rate: f64,
    pub selected_program_match_rate: f64,
}

fn ratio(numerator: f64, denominator: f64) -> f64 {
    if denominator > 0.0 {
        numerator / denominator
    } else {
        0.0
    }
}

fn correlation(sum_x: f64, sum_x2: f64, sum_y: f64, sum_y2: f64, sum_xy: f64, count: u64) -> f64 {
    let n = count as f64;
    if count < 2 {
        return 0.0;
    }
    let covariance = n * sum_xy - sum_x * sum_y;
    let variance_x = n * sum_x2 - sum_x * sum_x;
    let variance_y = n * sum_y2 - sum_y * sum_y;
    if variance_x <= 1.0e-18 || variance_y <= 1.0e-18 {
        0.0
    } else {
        covariance / (variance_x * variance_y).sqrt()
    }
}

fn diagnostic_candidates(
    model: &Model,
    proposal_batch: &[Sample],
    group: Group,
) -> ([Program; 4], usize) {
    let proposal_baseline = model.loss(proposal_batch);
    if group.len == 1 {
        let (actions, _) = singleton_actions(model, proposal_batch, proposal_baseline, group.left);
        let mut best = Action::default();
        for action in actions {
            if action.utility > best.utility {
                best = action;
            }
        }
        return (
            [
                Program {
                    left: group.left,
                    right: group.right,
                    deltas: [best.delta, 0.0],
                    len: 1,
                    ..Program::default()
                },
                Program::default(),
                Program::default(),
                Program::default(),
            ],
            1,
        );
    }

    let (left_actions, _) = singleton_actions(model, proposal_batch, proposal_baseline, group.left);
    let (right_actions, _) =
        singleton_actions(model, proposal_batch, proposal_baseline, group.right);
    let top_left = ordered_top(&left_actions, 2);
    let top_right = ordered_top(&right_actions, 2);
    let mut candidates = [Program::default(); 4];
    let mut cursor = 0;
    for &left in &top_left[..2] {
        for &right in &top_right[..2] {
            candidates[cursor] = Program {
                left: group.left,
                right: group.right,
                deltas: [ACTION_VALUES[left], ACTION_VALUES[right]],
                len: 2,
                ..Program::default()
            };
            cursor += 1;
        }
    }
    (candidates, 4)
}

fn argmax(values: &[f32], count: usize) -> usize {
    let mut best = 0;
    for index in 1..count {
        if values[index] > values[best] {
            best = index;
        }
    }
    best
}

fn utility_stats(values: &[f32], count: usize, selected: usize) -> SelectedShadow {
    if count == 0 || values[..count].iter().any(|value| !value.is_finite()) {
        return SelectedShadow {
            mean_utility: f64::NEG_INFINITY,
            ..SelectedShadow::default()
        };
    }
    let mut sum = 0.0_f64;
    let mut positive = 0_u64;
    for &value in &values[..count] {
        sum += value as f64;
        positive += u64::from(value > 0.0);
    }
    let mean = sum / count as f64;
    let mut variance = 0.0_f64;
    for &value in &values[..count] {
        let difference = value as f64 - mean;
        variance += difference * difference;
    }
    let denominator = (count.saturating_sub(1)) as f64;
    let stddev = if denominator > 0.0 {
        (variance / denominator).sqrt()
    } else {
        0.0
    };
    let snr = if count > 1 {
        mean.abs() / (stddev + 1.0e-9)
    } else {
        0.0
    };
    SelectedShadow {
        mean_utility: mean,
        stddev,
        snr,
        positive_probability: positive as f64 / count as f64,
        winner_agreement: 0.0,
        candidate_matches_reference: selected == argmax(values, count),
    }
}

fn group_matches(left: Group, right: Group) -> bool {
    left.left == right.left && left.right == right.right
}

#[allow(clippy::needless_range_loop, clippy::too_many_arguments)]
fn diagnostic_snapshot(
    model: &Model,
    train: &[Sample],
    proposal_batch: &[Sample],
    groups: &[Group; PARAMS],
    group_count: usize,
    selected: Selection,
    seed: u64,
    global_commit: usize,
    family_accumulators: &mut [DiagnosticFamilyAccumulator; DIAGNOSTIC_FAMILY_COUNT],
) -> (DiagnosticSnapshot, u64, u64) {
    let mut verifier_storage = [[train[0]; TRAIN_SAMPLES]; DIAGNOSTIC_COMPONENTS];
    let mut verifier_slices: [&[Sample]; DIAGNOSTIC_COMPONENTS] = [train; DIAGNOSTIC_COMPONENTS];
    let family_streams = [
        0x4831_3649_4e44_0000_u64,
        0x4833_3239_4e44_0000_u64,
        0x4832_3439_4e44_0000_u64,
    ];
    for family in 0..3 {
        let size = DIAGNOSTIC_FAMILY_SIZES[family];
        let offset = DIAGNOSTIC_FAMILY_OFFSETS[family];
        for component in 0..DIAGNOSTIC_FAMILY_COUNTS[family] {
            let index = offset + component;
            fill_random_verifier(
                &mut verifier_storage[index],
                train,
                seed,
                global_commit,
                family_streams[family] ^ (component as u64).wrapping_mul(0x9e37_79b9),
                size,
            );
        }
    }
    for family in 0..3 {
        let size = DIAGNOSTIC_FAMILY_SIZES[family];
        let offset = DIAGNOSTIC_FAMILY_OFFSETS[family];
        for component in 0..DIAGNOSTIC_FAMILY_COUNTS[family] {
            let index = offset + component;
            verifier_slices[index] = &verifier_storage[index][..size];
        }
    }
    let baseline = [
        model.loss(verifier_slices[0]),
        model.loss(verifier_slices[1]),
        model.loss(verifier_slices[2]),
        model.loss(verifier_slices[3]),
        model.loss(verifier_slices[4]),
        model.loss(verifier_slices[5]),
        model.loss(verifier_slices[6]),
        model.loss(verifier_slices[7]),
        model.loss(verifier_slices[8]),
        model.loss(verifier_slices[9]),
        model.loss(verifier_slices[10]),
        model.loss(train),
    ];
    let mut reference_best_utility = f32::NEG_INFINITY;
    let mut reference_best_group = Group::default();
    let mut reference_best_candidate = 0;
    let mut selected_shadow = [SelectedShadow::default(); DIAGNOSTIC_FAMILY_COUNT];
    let mut selected_candidate = 0;
    let mut selected_present = false;
    let mut shadow_evaluations = 0_u64;
    let mut reference_evaluations = 0_u64;
    let selected_group = selected.group;
    let mut family_block_values = [[f32::NEG_INFINITY; PARAMS]; DIAGNOSTIC_FAMILY_COUNT];
    let mut family_component_block_values =
        [[[f32::NEG_INFINITY; PARAMS]; DIAGNOSTIC_COMPONENTS]; DIAGNOSTIC_FAMILY_COUNT];

    for (group_index, &group) in groups[..group_count].iter().enumerate() {
        let (candidates, candidate_count) = diagnostic_candidates(model, proposal_batch, group);
        let mut utilities = [[f32::NEG_INFINITY; 4]; DIAGNOSTIC_COMPONENTS];
        for component in 0..DIAGNOSTIC_COMPONENTS {
            for candidate in 0..candidate_count {
                utilities[component][candidate] = exact_program_value(
                    model,
                    verifier_slices[component],
                    baseline[component],
                    candidates[candidate],
                );
                shadow_evaluations += 1;
            }
        }
        for candidate in 0..candidate_count {
            let reference_utility = utilities[DIAGNOSTIC_COMPONENTS - 1][candidate];
            if reference_utility > reference_best_utility {
                reference_best_utility = reference_utility;
                reference_best_group = group;
                reference_best_candidate = candidate;
            }
        }
        let reference_candidate = argmax(&utilities[DIAGNOSTIC_COMPONENTS - 1], candidate_count);
        for family in 0..DIAGNOSTIC_FAMILY_COUNT {
            let offset = DIAGNOSTIC_FAMILY_OFFSETS[family];
            let component_count = DIAGNOSTIC_FAMILY_COUNTS[family];
            let mut means = [f32::NEG_INFINITY; 4];
            for candidate in 0..candidate_count {
                let mut values = [0.0_f32; DIAGNOSTIC_COMPONENTS];
                for component in 0..component_count {
                    values[component] = utilities[offset + component][candidate];
                    let reference = utilities[DIAGNOSTIC_COMPONENTS - 1][candidate];
                    if values[component].is_finite() && reference.is_finite() {
                        family_accumulators[family].sign_total += 1;
                        family_accumulators[family].sign_matches +=
                            u64::from((values[component] > 0.0) == (reference > 0.0));
                    }
                }
                means[candidate] = utility_stats(&values, component_count, reference_candidate)
                    .mean_utility as f32;
            }
            let family_winner = argmax(&means, candidate_count);
            family_block_values[family][group_index] = means[family_winner];
            for component in 0..component_count {
                let component_winner = argmax(&utilities[offset + component], candidate_count);
                let component_best = utilities[offset + component][component_winner];
                family_component_block_values[family][component][group_index] = component_best;
                family_accumulators[family].component_winner_total += 1;
                family_accumulators[family].component_winner_matches +=
                    u64::from(component_winner == reference_candidate);
            }
            if group_matches(group, selected_group)
                && selected.program.is_some()
                && let Some(selected_index) = candidates[..candidate_count]
                    .iter()
                    .position(|candidate| same_program(Some(*candidate), selected.program))
            {
                let mut selected_values = [0.0_f32; DIAGNOSTIC_COMPONENTS];
                for component in 0..component_count {
                    selected_values[component] = utilities[offset + component][selected_index];
                }
                let mut selected_stats =
                    utility_stats(&selected_values, component_count, selected_index);
                let component_winners = (0..component_count)
                    .filter(|&component| {
                        argmax(&utilities[offset + component], candidate_count) == selected_index
                    })
                    .count();
                selected_stats.winner_agreement = component_winners as f64 / component_count as f64;
                selected_stats.candidate_matches_reference = selected_index == reference_candidate;
                selected_shadow[family] = selected_stats;
                selected_candidate = selected_index;
                selected_present = true;
            }
        }
        reference_evaluations += candidate_count as u64;
    }

    let reference_block_index = groups[..group_count]
        .iter()
        .position(|group| group_matches(*group, reference_best_group))
        .unwrap_or(0);
    for family in 0..DIAGNOSTIC_FAMILY_COUNT {
        let accumulator = &mut family_accumulators[family];
        let mut best_index = 0;
        let mut best_value = family_block_values[family][0];
        for group_index in 1..group_count {
            if family_block_values[family][group_index] > best_value {
                best_index = group_index;
                best_value = family_block_values[family][group_index];
            }
        }
        accumulator.family_block_total += 1;
        accumulator.family_block_matches += u64::from(best_index == reference_block_index);
        accumulator.family_block_value_error_sum +=
            (best_value as f64 - reference_best_utility as f64).abs();
        let component_count = DIAGNOSTIC_FAMILY_COUNTS[family];
        for component in 0..component_count {
            let mut component_best_index = 0;
            let mut component_best_value = family_component_block_values[family][component][0];
            for group_index in 1..group_count {
                let value = family_component_block_values[family][component][group_index];
                if value > component_best_value {
                    component_best_index = group_index;
                    component_best_value = value;
                }
            }
            accumulator.component_block_total += 1;
            accumulator.component_block_matches +=
                u64::from(component_best_index == reference_block_index);
        }
    }

    let selected_reference_utility = if selected_present {
        let (selected_candidates, selected_count) =
            diagnostic_candidates(model, proposal_batch, selected_group);
        let selected_index = selected_candidate.min(selected_count.saturating_sub(1));
        exact_program_value(
            model,
            train,
            baseline[DIAGNOSTIC_COMPONENTS - 1],
            selected_candidates[selected_index],
        )
    } else {
        f32::NEG_INFINITY
    };
    let selected_reference_regret = (reference_best_utility - selected_reference_utility).max(0.0);
    for family in 0..DIAGNOSTIC_FAMILY_COUNT {
        let accumulator = &mut family_accumulators[family];
        accumulator.snapshots += 1;
        if selected_present {
            let shadow = &mut selected_shadow[family];
            accumulator.add_selected(
                shadow.stddev,
                shadow.snr,
                shadow.positive_probability,
                selected_reference_regret as f64,
                shadow.mean_utility,
                selected_reference_utility as f64,
                shadow.winner_agreement,
                group_matches(selected_group, reference_best_group),
                group_matches(selected_group, reference_best_group)
                    && shadow.candidate_matches_reference
                    && selected_candidate == reference_best_candidate,
            );
        }
    }
    (
        DiagnosticSnapshot {
            reference_best_group,
            reference_best_candidate,
            selected_group,
            selected_candidate,
            selected_present,
        },
        shadow_evaluations,
        reference_evaluations,
    )
}

pub fn run_diagnostic(samples: &[Sample], seed: u64) -> DiagnosticSummary {
    assert_eq!(samples.len(), TOTAL_SAMPLES);
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let mut model = Model::initial();
    let mut accumulators = [DiagnosticFamilyAccumulator::default(); DIAGNOSTIC_FAMILY_COUNT];
    let mut shadow_evaluations = 0_u64;
    let mut reference_evaluations = 0_u64;
    let mut selected_block_matches = 0_u64;
    let mut selected_program_matches = 0_u64;

    for evidence_round in 0..(TOTAL_COMMITS / DIAGNOSTIC_COMMITS_PER_EVIDENCE) {
        let proposal_indices = batch_indices(seed, evidence_round, 0x5052_4f50_4f53_414c);
        let proposal_storage = indexed_samples(train, &proposal_indices);
        let mut verify_storage = [[train[0]; TRAIN_SAMPLES]; MAX_VERIFY_BATCHES];
        fill_stratified_verifier(&mut verify_storage[0], train, seed, evidence_round, 64);
        let verify_batches: [&[Sample]; MAX_VERIFY_BATCHES] =
            [&verify_storage[0][..64], train, train, train, train, train];
        for commit_index in 0..DIAGNOSTIC_COMMITS_PER_EVIDENCE {
            let global_commit = evidence_round * DIAGNOSTIC_COMMITS_PER_EVIDENCE + commit_index;
            let (groups, group_count) = partition(global_commit % PARAMS);
            let mut selection = Selection {
                group: Group::default(),
                ..Selection::default()
            };
            for &group in &groups[..group_count] {
                let (candidate, telemetry) = best_runtime_program(
                    &model,
                    &proposal_storage,
                    &verify_batches[..1],
                    Arm::G3Stratified64,
                    group,
                );
                selection.telemetry.absorb(telemetry);
                if let Some(candidate) = candidate
                    && selection
                        .program
                        .is_none_or(|current| candidate.utility > current.utility)
                {
                    selection.program = Some(candidate);
                    selection.group = group;
                }
            }
            if global_commit.is_multiple_of(DIAGNOSTIC_EVERY) {
                let (snapshot, shadow_count, reference_count) = diagnostic_snapshot(
                    &model,
                    train,
                    &proposal_storage,
                    &groups,
                    group_count,
                    selection,
                    seed,
                    global_commit,
                    &mut accumulators,
                );
                selected_block_matches += u64::from(
                    snapshot.selected_present
                        && group_matches(snapshot.selected_group, snapshot.reference_best_group),
                );
                selected_program_matches += u64::from(
                    snapshot.selected_present
                        && snapshot.selected_group.left == snapshot.reference_best_group.left
                        && snapshot.selected_group.right == snapshot.reference_best_group.right
                        && snapshot.selected_candidate == snapshot.reference_best_candidate,
                );
                shadow_evaluations += shadow_count;
                reference_evaluations += reference_count;
            }
            if let Some(program) = selection.program {
                commit(&mut model, program);
            }
        }
    }

    DiagnosticSummary {
        seed,
        snapshots: DIAGNOSTIC_SNAPSHOTS as u64,
        shadow_evaluations,
        reference_evaluations,
        final_train_loss: model.loss(train),
        final_validation_loss: model.loss(validation),
        final_train_accuracy: model.accuracy(train),
        final_validation_accuracy: model.accuracy(validation),
        families: accumulators.map(DiagnosticFamilyAccumulator::finalize),
        selected_block_match_rate: ratio(
            selected_block_matches as f64,
            DIAGNOSTIC_SNAPSHOTS as f64,
        ),
        selected_program_match_rate: ratio(
            selected_program_matches as f64,
            DIAGNOSTIC_SNAPSHOTS as f64,
        ),
    }
}

pub fn diagnostic_all(samples: &[Sample]) -> Vec<DiagnosticSummary> {
    SEEDS
        .into_iter()
        .map(|seed| run_diagnostic(samples, seed))
        .collect()
}

pub const INDIFFERENCE_EVERY: usize = 50;
pub const INDIFFERENCE_COMMITS_PER_EVIDENCE: usize = 4;
pub const INDIFFERENCE_SNAPSHOTS: usize = TOTAL_COMMITS / INDIFFERENCE_EVERY;

#[derive(Clone, Copy, Debug, Default)]
pub struct IndifferenceSnapshot {
    pub global_commit: usize,
    pub block_count: usize,
    pub best_utility: f32,
    pub selected_block_utility: f32,
    pub selected_program_utility: f32,
    pub selected_block_regret: f32,
    pub selected_program_regret: f32,
    pub selected_block_rank: usize,
    pub selected_present: bool,
    pub near_abs_1e5: usize,
    pub near_abs_1e4: usize,
    pub near_abs_1e3: usize,
    pub near_abs_1e2: usize,
    pub near_relative_1pct: usize,
    pub near_relative_5pct: usize,
    pub positive_blocks: usize,
    pub neutral_blocks: usize,
    pub harmful_blocks: usize,
    pub selected_block_near_1pct: bool,
    pub selected_block_near_5pct: bool,
    pub selected_block_positive: bool,
    pub selected_block_harmful: bool,
    pub selected_program_positive: bool,
    pub selected_program_harmful: bool,
}

#[derive(Clone, Debug)]
pub struct IndifferenceSummary {
    pub seed: u64,
    pub final_train_loss: f32,
    pub final_validation_loss: f32,
    pub final_train_accuracy: f32,
    pub final_validation_accuracy: f32,
    pub snapshots: Vec<IndifferenceSnapshot>,
}

fn count_near(values: &[f32; PARAMS], count: usize, best: f32, tolerance: f32) -> usize {
    values[..count]
        .iter()
        .filter(|&&value| best - value <= tolerance)
        .count()
}

fn count_relative_near(values: &[f32; PARAMS], count: usize, best: f32, fraction: f32) -> usize {
    let tolerance = best.abs().max(1.0e-9) * fraction;
    count_near(values, count, best, tolerance)
}

fn block_rank(values: &[f32; PARAMS], count: usize, selected: f32) -> usize {
    1 + values[..count]
        .iter()
        .filter(|&&value| value > selected + 1.0e-7)
        .count()
}

fn indifference_snapshot(
    model: &Model,
    train: &[Sample],
    proposal_batch: &[Sample],
    groups: &[Group; PARAMS],
    group_count: usize,
    selected: Selection,
    global_commit: usize,
) -> IndifferenceSnapshot {
    let baseline = model.loss(train);
    let mut block_values = [f32::NEG_INFINITY; PARAMS];
    let mut selected_block_utility = f32::NEG_INFINITY;
    let mut selected_program_utility = f32::NEG_INFINITY;
    let mut selected_present = false;
    for (group_index, &group) in groups[..group_count].iter().enumerate() {
        let (candidates, candidate_count) = diagnostic_candidates(model, proposal_batch, group);
        let mut best = f32::NEG_INFINITY;
        let mut selected_candidate = f32::NEG_INFINITY;
        let mut selected_found = false;
        for candidate in candidates.iter().take(candidate_count) {
            let utility = exact_program_value(model, train, baseline, *candidate);
            best = best.max(utility);
            if let Some(selected_program) = selected.program
                && group_matches(group, selected.group)
                && same_program(Some(*candidate), Some(selected_program))
            {
                selected_candidate = utility;
                selected_found = true;
            }
        }
        block_values[group_index] = best;
        if selected_found {
            selected_present = true;
            selected_block_utility = best;
            selected_program_utility = selected_candidate;
        }
    }
    let best_utility = block_values[..group_count]
        .iter()
        .copied()
        .fold(f32::NEG_INFINITY, f32::max);
    let selected_block_regret = if selected_present {
        (best_utility - selected_block_utility).max(0.0)
    } else {
        0.0
    };
    let selected_program_regret = if selected_present {
        (best_utility - selected_program_utility).max(0.0)
    } else {
        0.0
    };
    let near_abs_1e5 = count_near(&block_values, group_count, best_utility, 1.0e-5);
    let near_abs_1e4 = count_near(&block_values, group_count, best_utility, 1.0e-4);
    let near_abs_1e3 = count_near(&block_values, group_count, best_utility, 1.0e-3);
    let near_abs_1e2 = count_near(&block_values, group_count, best_utility, 1.0e-2);
    let near_relative_1pct = count_relative_near(&block_values, group_count, best_utility, 0.01);
    let near_relative_5pct = count_relative_near(&block_values, group_count, best_utility, 0.05);
    let neutral_tolerance = 1.0e-5;
    let positive_blocks = block_values[..group_count]
        .iter()
        .filter(|&&value| value > neutral_tolerance)
        .count();
    let neutral_blocks = block_values[..group_count]
        .iter()
        .filter(|&&value| value.abs() <= 1.0e-5)
        .count();
    let harmful_blocks = group_count - positive_blocks - neutral_blocks;
    let selected_block_rank = if selected_present {
        block_rank(&block_values, group_count, selected_block_utility)
    } else {
        0
    };
    IndifferenceSnapshot {
        global_commit,
        block_count: group_count,
        best_utility,
        selected_block_utility,
        selected_program_utility,
        selected_block_regret,
        selected_program_regret,
        selected_block_rank,
        selected_present,
        near_abs_1e5,
        near_abs_1e4,
        near_abs_1e3,
        near_abs_1e2,
        near_relative_1pct,
        near_relative_5pct,
        positive_blocks,
        neutral_blocks,
        harmful_blocks,
        selected_block_near_1pct: selected_present
            && selected_block_regret <= best_utility.abs().max(1.0e-9) * 0.01,
        selected_block_near_5pct: selected_present
            && selected_block_regret <= best_utility.abs().max(1.0e-9) * 0.05,
        selected_block_positive: selected_present && selected_block_utility > neutral_tolerance,
        selected_block_harmful: selected_present && selected_block_utility < -neutral_tolerance,
        selected_program_positive: selected_present && selected_program_utility > neutral_tolerance,
        selected_program_harmful: selected_present && selected_program_utility < -neutral_tolerance,
    }
}

pub fn run_indifference(samples: &[Sample], seed: u64) -> IndifferenceSummary {
    assert_eq!(samples.len(), TOTAL_SAMPLES);
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let mut model = Model::initial();
    let mut snapshots = Vec::with_capacity(INDIFFERENCE_SNAPSHOTS);
    for evidence_round in 0..(TOTAL_COMMITS / INDIFFERENCE_COMMITS_PER_EVIDENCE) {
        let proposal_indices = batch_indices(seed, evidence_round, 0x5052_4f50_4f53_414c);
        let proposal_storage = indexed_samples(train, &proposal_indices);
        let mut verify_storage = [[train[0]; TRAIN_SAMPLES]; MAX_VERIFY_BATCHES];
        fill_stratified_verifier(&mut verify_storage[0], train, seed, evidence_round, 64);
        let verify_batches: [&[Sample]; MAX_VERIFY_BATCHES] =
            [&verify_storage[0][..64], train, train, train, train, train];
        for commit_index in 0..INDIFFERENCE_COMMITS_PER_EVIDENCE {
            let global_commit = evidence_round * INDIFFERENCE_COMMITS_PER_EVIDENCE + commit_index;
            let (groups, group_count) = partition(global_commit % PARAMS);
            let mut selection = Selection {
                group: Group::default(),
                ..Selection::default()
            };
            for &group in &groups[..group_count] {
                let (candidate, telemetry) = best_runtime_program(
                    &model,
                    &proposal_storage,
                    &verify_batches[..1],
                    Arm::G3Stratified64,
                    group,
                );
                selection.telemetry.absorb(telemetry);
                if let Some(candidate) = candidate
                    && selection
                        .program
                        .is_none_or(|current| candidate.utility > current.utility)
                {
                    selection.program = Some(candidate);
                    selection.group = group;
                }
            }
            if global_commit.is_multiple_of(INDIFFERENCE_EVERY) {
                snapshots.push(indifference_snapshot(
                    &model,
                    train,
                    &proposal_storage,
                    &groups,
                    group_count,
                    selection,
                    global_commit,
                ));
            }
            if let Some(program) = selection.program {
                commit(&mut model, program);
            }
        }
    }
    IndifferenceSummary {
        seed,
        final_train_loss: model.loss(train),
        final_validation_loss: model.loss(validation),
        final_train_accuracy: model.accuracy(train),
        final_validation_accuracy: model.accuracy(validation),
        snapshots,
    }
}

pub fn indifference_all(samples: &[Sample]) -> Vec<IndifferenceSummary> {
    SEEDS
        .into_iter()
        .map(|seed| run_indifference(samples, seed))
        .collect()
}

pub const COUNTERFACTUAL_HORIZONS: [usize; 7] = [1, 2, 4, 8, 16, 32, 64];
pub const COUNTERFACTUAL_EVERY: usize = 50;
pub const COUNTERFACTUAL_COMMITS_PER_EVIDENCE: usize = 4;
pub const COUNTERFACTUAL_SNAPSHOTS: usize = TOTAL_COMMITS / COUNTERFACTUAL_EVERY;

#[derive(Clone, Copy, Debug, Default)]
pub struct OpportunityState {
    pub best_utility: f32,
    pub positive_blocks: usize,
    pub harmful_blocks: usize,
    pub mean_positive_utility: f32,
    pub median_positive_utility: f32,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct CounterfactualHorizon {
    pub horizon: usize,
    pub g3_train_loss: f32,
    pub greedy_train_loss: f32,
    pub delta_train_loss: f32,
    pub g3_validation_loss: f32,
    pub greedy_validation_loss: f32,
    pub g3_best_opportunity: f32,
    pub greedy_best_opportunity: f32,
    pub delta_best_opportunity: f32,
    pub g3_positive_blocks: usize,
    pub greedy_positive_blocks: usize,
    pub g3_harmful_blocks: usize,
    pub greedy_harmful_blocks: usize,
    pub g3_mean_positive_utility: f32,
    pub greedy_mean_positive_utility: f32,
    pub g3_median_positive_utility: f32,
    pub greedy_median_positive_utility: f32,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct CounterfactualSnapshot {
    pub global_commit: usize,
    pub selected_present: bool,
    pub g3_initial_utility: f32,
    pub greedy_initial_utility: f32,
    pub initial_regret: f32,
    pub g3_initial_harmful: bool,
    pub horizons: [CounterfactualHorizon; 7],
}

#[derive(Clone, Debug)]
pub struct CounterfactualSummary {
    pub seed: u64,
    pub final_train_loss: f32,
    pub final_validation_loss: f32,
    pub final_train_accuracy: f32,
    pub final_validation_accuracy: f32,
    pub snapshots: Vec<CounterfactualSnapshot>,
}

fn g3_selection_for_context(
    model: &Model,
    proposal_batch: &[Sample],
    verify_batch: &[Sample],
    groups: &[Group; PARAMS],
    group_count: usize,
) -> Selection {
    let mut selection = Selection {
        group: Group::default(),
        ..Selection::default()
    };
    let verify_batches = [verify_batch];
    for &group in &groups[..group_count] {
        let (candidate, telemetry) = best_runtime_program(
            model,
            proposal_batch,
            &verify_batches,
            Arm::G3Stratified64,
            group,
        );
        selection.telemetry.absorb(telemetry);
        if let Some(candidate) = candidate
            && selection
                .program
                .is_none_or(|current| candidate.utility > current.utility)
        {
            selection.program = Some(candidate);
            selection.group = group;
        }
    }
    selection
}

fn g3_context(
    model: &Model,
    train: &[Sample],
    seed: u64,
    global_commit: usize,
) -> ([Sample; BATCH_SIZE], [Group; PARAMS], usize, Selection) {
    let evidence_round = global_commit / COUNTERFACTUAL_COMMITS_PER_EVIDENCE;
    let proposal_indices = batch_indices(seed, evidence_round, 0x5052_4f50_4f53_414c);
    let proposal_storage = indexed_samples(train, &proposal_indices);
    let mut verify_storage = [train[0]; TRAIN_SAMPLES];
    fill_stratified_verifier(&mut verify_storage, train, seed, evidence_round, 64);
    let (groups, group_count) = partition(global_commit % PARAMS);
    let selection = g3_selection_for_context(
        model,
        &proposal_storage,
        &verify_storage[..64],
        &groups,
        group_count,
    );
    (proposal_storage, groups, group_count, selection)
}

fn full_reference_program(
    model: &Model,
    train: &[Sample],
    proposal_batch: &[Sample],
    groups: &[Group; PARAMS],
    group_count: usize,
) -> (Program, f32) {
    let baseline = model.loss(train);
    let mut best = Program::default();
    let mut best_utility = f32::NEG_INFINITY;
    for &group in &groups[..group_count] {
        let (candidates, candidate_count) = diagnostic_candidates(model, proposal_batch, group);
        for candidate in candidates.iter().take(candidate_count) {
            let utility = exact_program_value(model, train, baseline, *candidate);
            if utility > best_utility {
                best = *candidate;
                best_utility = utility;
            }
        }
    }
    (best, best_utility)
}

fn opportunity_state(
    model: &Model,
    train: &[Sample],
    seed: u64,
    next_global_commit: usize,
) -> OpportunityState {
    let evidence_round = next_global_commit / COUNTERFACTUAL_COMMITS_PER_EVIDENCE;
    let proposal_indices = batch_indices(seed, evidence_round, 0x5052_4f50_4f53_414c);
    let proposal_storage = indexed_samples(train, &proposal_indices);
    let (groups, group_count) = partition(next_global_commit % PARAMS);
    let baseline = model.loss(train);
    let mut values = [f32::NEG_INFINITY; PARAMS];
    for (group_index, &group) in groups[..group_count].iter().enumerate() {
        let (candidates, candidate_count) = diagnostic_candidates(model, &proposal_storage, group);
        for candidate in candidates.iter().take(candidate_count) {
            values[group_index] =
                values[group_index].max(exact_program_value(model, train, baseline, *candidate));
        }
    }
    let best_utility = values[..group_count]
        .iter()
        .copied()
        .fold(f32::NEG_INFINITY, f32::max);
    let neutral_tolerance = 1.0e-5;
    let positive_values: Vec<f32> = values[..group_count]
        .iter()
        .copied()
        .filter(|value| *value > neutral_tolerance)
        .collect();
    let positive_blocks = positive_values.len();
    let harmful_blocks = values[..group_count]
        .iter()
        .filter(|&&value| value < -neutral_tolerance)
        .count();
    let mean_positive_utility = if positive_values.is_empty() {
        0.0
    } else {
        positive_values.iter().sum::<f32>() / positive_values.len() as f32
    };
    let mut ordered = positive_values;
    ordered.sort_by(f32::total_cmp);
    let median_positive_utility = ordered.get(ordered.len() / 2).copied().unwrap_or(0.0);
    OpportunityState {
        best_utility,
        positive_blocks,
        harmful_blocks,
        mean_positive_utility,
        median_positive_utility,
    }
}

#[allow(clippy::too_many_arguments)]
fn counterfactual_snapshot(
    model: &Model,
    train: &[Sample],
    validation: &[Sample],
    seed: u64,
    global_commit: usize,
    proposal_batch: &[Sample],
    groups: &[Group; PARAMS],
    group_count: usize,
    selected: Selection,
) -> CounterfactualSnapshot {
    let baseline = model.loss(train);
    let g3_initial_utility = selected.program.map_or(0.0, |program| {
        exact_program_value(model, train, baseline, program)
    });
    let (greedy_program, greedy_initial_utility) =
        full_reference_program(model, train, proposal_batch, groups, group_count);
    let mut g3_model = *model;
    if let Some(program) = selected.program {
        commit(&mut g3_model, program);
    }
    let mut greedy_model = *model;
    commit(&mut greedy_model, greedy_program);
    let mut horizons = [CounterfactualHorizon::default(); 7];
    let mut horizon_index = 0;
    for committed in 1..=COUNTERFACTUAL_HORIZONS[COUNTERFACTUAL_HORIZONS.len() - 1] {
        if committed > 1 {
            let future_commit = global_commit + committed - 1;
            let (g3_proposal, g3_groups, g3_group_count, g3_selection) =
                g3_context(&g3_model, train, seed, future_commit);
            let (greedy_proposal, greedy_groups, greedy_group_count, greedy_selection) =
                g3_context(&greedy_model, train, seed, future_commit);
            let _ = (
                g3_proposal,
                g3_groups,
                g3_group_count,
                greedy_proposal,
                greedy_groups,
            );
            if let Some(program) = g3_selection.program {
                commit(&mut g3_model, program);
            }
            if let Some(program) = greedy_selection.program {
                commit(&mut greedy_model, program);
            }
            let _ = greedy_group_count;
        }
        if committed == COUNTERFACTUAL_HORIZONS[horizon_index] {
            let g3_opportunity =
                opportunity_state(&g3_model, train, seed, global_commit + committed);
            let greedy_opportunity =
                opportunity_state(&greedy_model, train, seed, global_commit + committed);
            horizons[horizon_index] = CounterfactualHorizon {
                horizon: committed,
                g3_train_loss: g3_model.loss(train),
                greedy_train_loss: greedy_model.loss(train),
                delta_train_loss: g3_model.loss(train) - greedy_model.loss(train),
                g3_validation_loss: g3_model.loss(validation),
                greedy_validation_loss: greedy_model.loss(validation),
                g3_best_opportunity: g3_opportunity.best_utility,
                greedy_best_opportunity: greedy_opportunity.best_utility,
                delta_best_opportunity: g3_opportunity.best_utility
                    - greedy_opportunity.best_utility,
                g3_positive_blocks: g3_opportunity.positive_blocks,
                greedy_positive_blocks: greedy_opportunity.positive_blocks,
                g3_harmful_blocks: g3_opportunity.harmful_blocks,
                greedy_harmful_blocks: greedy_opportunity.harmful_blocks,
                g3_mean_positive_utility: g3_opportunity.mean_positive_utility,
                greedy_mean_positive_utility: greedy_opportunity.mean_positive_utility,
                g3_median_positive_utility: g3_opportunity.median_positive_utility,
                greedy_median_positive_utility: greedy_opportunity.median_positive_utility,
            };
            horizon_index += 1;
            if horizon_index == COUNTERFACTUAL_HORIZONS.len() {
                break;
            }
        }
    }
    CounterfactualSnapshot {
        global_commit,
        selected_present: selected.program.is_some(),
        g3_initial_utility,
        greedy_initial_utility,
        initial_regret: (greedy_initial_utility - g3_initial_utility).max(0.0),
        g3_initial_harmful: g3_initial_utility < -1.0e-5,
        horizons,
    }
}

pub fn run_counterfactual(samples: &[Sample], seed: u64) -> CounterfactualSummary {
    assert_eq!(samples.len(), TOTAL_SAMPLES);
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let mut model = Model::initial();
    let mut snapshots = Vec::with_capacity(COUNTERFACTUAL_SNAPSHOTS);
    for evidence_round in 0..(TOTAL_COMMITS / COUNTERFACTUAL_COMMITS_PER_EVIDENCE) {
        for commit_index in 0..COUNTERFACTUAL_COMMITS_PER_EVIDENCE {
            let global_commit = evidence_round * COUNTERFACTUAL_COMMITS_PER_EVIDENCE + commit_index;
            let (proposal_batch, groups, group_count, selection) =
                g3_context(&model, train, seed, global_commit);
            if global_commit.is_multiple_of(COUNTERFACTUAL_EVERY) {
                snapshots.push(counterfactual_snapshot(
                    &model,
                    train,
                    validation,
                    seed,
                    global_commit,
                    &proposal_batch,
                    &groups,
                    group_count,
                    selection,
                ));
            }
            if let Some(program) = selection.program {
                commit(&mut model, program);
            }
        }
    }
    CounterfactualSummary {
        seed,
        final_train_loss: model.loss(train),
        final_validation_loss: model.loss(validation),
        final_train_accuracy: model.accuracy(train),
        final_validation_accuracy: model.accuracy(validation),
        snapshots,
    }
}

pub fn counterfactual_all(samples: &[Sample]) -> Vec<CounterfactualSummary> {
    SEEDS
        .into_iter()
        .map(|seed| run_counterfactual(samples, seed))
        .collect()
}

pub const MATCHED_HORIZONS: [usize; 7] = [1, 2, 4, 8, 16, 32, 64];
pub const MATCHED_EVERY: usize = 50;
pub const MATCHED_COMMITS_PER_EVIDENCE: usize = 4;
pub const MATCHED_SNAPSHOTS: usize = TOTAL_COMMITS / MATCHED_EVERY;
pub const MATCHED_CONTROLS: usize = 2;
pub const MATCHED_REGRET_TOLERANCE: f32 = 5.0e-5;
pub const MATCHED_NEUTRAL_TOLERANCE: f32 = 1.0e-5;

#[derive(Clone, Copy, Debug, Default)]
pub struct MatchedControlInfo {
    pub present: bool,
    pub utility: f32,
    pub regret: f32,
    pub stratum: u8,
    pub regret_gap: f32,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct MatchedHorizon {
    pub horizon: usize,
    pub g3_train_loss: f32,
    pub greedy_train_loss: f32,
    pub control_a_train_loss: f32,
    pub control_b_train_loss: f32,
    pub g3_validation_loss: f32,
    pub greedy_validation_loss: f32,
    pub control_a_validation_loss: f32,
    pub control_b_validation_loss: f32,
    pub g3_vs_greedy_train_delta: f32,
    pub g3_vs_control_a_train_delta: f32,
    pub g3_vs_control_b_train_delta: f32,
    pub g3_greedy_parameter_distance: f32,
    pub g3_control_a_parameter_distance: f32,
    pub g3_control_b_parameter_distance: f32,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct MatchedSnapshot {
    pub global_commit: usize,
    pub selected_present: bool,
    pub g3_utility: f32,
    pub g3_regret: f32,
    pub greedy_utility: f32,
    pub greedy_regret: f32,
    pub g3_stratum: u8,
    pub control_a: MatchedControlInfo,
    pub control_b: MatchedControlInfo,
    pub horizons: [MatchedHorizon; 7],
}

#[derive(Clone, Debug)]
pub struct MatchedSummary {
    pub seed: u64,
    pub final_train_loss: f32,
    pub final_validation_loss: f32,
    pub final_train_accuracy: f32,
    pub final_validation_accuracy: f32,
    pub snapshots: Vec<MatchedSnapshot>,
}

#[derive(Clone, Copy, Debug)]
struct CandidateRecord {
    program: Program,
    utility: f32,
    regret: f32,
    stratum: u8,
}

#[derive(Clone, Copy, Debug)]
struct MatchedControl {
    program: Program,
    utility: f32,
    regret: f32,
    stratum: u8,
    regret_gap: f32,
}

fn utility_stratum(utility: f32) -> u8 {
    if utility > MATCHED_NEUTRAL_TOLERANCE {
        1
    } else if utility < -MATCHED_NEUTRAL_TOLERANCE {
        2
    } else {
        0
    }
}

fn candidate_universe(
    model: &Model,
    train: &[Sample],
    proposal_batch: &[Sample],
    groups: &[Group; PARAMS],
    group_count: usize,
) -> Vec<CandidateRecord> {
    let baseline = model.loss(train);
    let mut candidates = Vec::with_capacity(group_count * 4);
    for &group in &groups[..group_count] {
        let (programs, count) = diagnostic_candidates(model, proposal_batch, group);
        for program in programs.iter().take(count).copied() {
            let utility = exact_program_value(model, train, baseline, program);
            candidates.push(CandidateRecord {
                program,
                utility,
                regret: 0.0,
                stratum: utility_stratum(utility),
            });
        }
    }
    let best_utility = candidates
        .iter()
        .map(|candidate| candidate.utility)
        .fold(f32::NEG_INFINITY, f32::max);
    for candidate in &mut candidates {
        candidate.regret = (best_utility - candidate.utility).max(0.0);
    }
    candidates
}

fn deterministic_match_key(seed: u64, global_commit: usize, index: usize) -> u64 {
    let mut value = seed
        ^ (global_commit as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15)
        ^ (index as u64).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value ^= value >> 30;
    value = value.wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value ^= value >> 27;
    value = value.wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

fn matched_controls(
    candidates: &[CandidateRecord],
    g3_program: Program,
    g3_utility: f32,
    seed: u64,
    global_commit: usize,
) -> [Option<MatchedControl>; MATCHED_CONTROLS] {
    let best_utility = candidates
        .iter()
        .map(|candidate| candidate.utility)
        .fold(f32::NEG_INFINITY, f32::max);
    let g3_regret = (best_utility - g3_utility).max(0.0);
    let mut eligible: Vec<(f32, u64, CandidateRecord)> = candidates
        .iter()
        .copied()
        .enumerate()
        .filter(|(_, candidate)| {
            !same_program(Some(candidate.program), Some(g3_program))
                && candidate.stratum == utility_stratum(g3_utility)
                && (candidate.regret - g3_regret).abs() <= MATCHED_REGRET_TOLERANCE
        })
        .map(|(index, candidate)| {
            (
                (candidate.regret - g3_regret).abs(),
                deterministic_match_key(seed, global_commit, index),
                candidate,
            )
        })
        .collect();
    eligible.sort_by(|left, right| {
        left.0
            .total_cmp(&right.0)
            .then_with(|| left.1.cmp(&right.1))
    });
    let mut selected = [None; MATCHED_CONTROLS];
    for (slot, (_, _, candidate)) in eligible.into_iter().take(MATCHED_CONTROLS).enumerate() {
        selected[slot] = Some(MatchedControl {
            program: candidate.program,
            utility: candidate.utility,
            regret: candidate.regret,
            stratum: candidate.stratum,
            regret_gap: (candidate.regret - g3_regret).abs(),
        });
    }
    selected
}

fn parameter_distance(left: &Model, right: &Model) -> f32 {
    left.parameters
        .iter()
        .zip(right.parameters)
        .map(|(left, right)| {
            let delta = left - right;
            delta * delta
        })
        .sum::<f32>()
        .sqrt()
}

fn commit_optional(model: &mut Model, program: Option<Program>) {
    if let Some(program) = program {
        commit(model, program);
    }
}

fn matched_control_info(control: Option<MatchedControl>) -> MatchedControlInfo {
    control.map_or(MatchedControlInfo::default(), |control| {
        MatchedControlInfo {
            present: true,
            utility: control.utility,
            regret: control.regret,
            stratum: control.stratum,
            regret_gap: control.regret_gap,
        }
    })
}

#[allow(clippy::too_many_arguments)]
fn matched_snapshot(
    model: &Model,
    train: &[Sample],
    validation: &[Sample],
    seed: u64,
    global_commit: usize,
    proposal_batch: &[Sample],
    groups: &[Group; PARAMS],
    group_count: usize,
    selected: Selection,
) -> MatchedSnapshot {
    let baseline = model.loss(train);
    let g3_program = selected.program;
    let g3_utility = g3_program.map_or(0.0, |program| {
        exact_program_value(model, train, baseline, program)
    });
    let candidates = candidate_universe(model, train, proposal_batch, groups, group_count);
    let best_utility = candidates
        .iter()
        .map(|candidate| candidate.utility)
        .fold(f32::NEG_INFINITY, f32::max);
    let greedy_program = candidates
        .iter()
        .max_by(|left, right| left.utility.total_cmp(&right.utility))
        .map(|candidate| candidate.program)
        .unwrap_or_default();
    let greedy_utility = candidates
        .iter()
        .find(|candidate| same_program(Some(candidate.program), Some(greedy_program)))
        .map_or(0.0, |candidate| candidate.utility);
    let controls = g3_program.map_or([None; MATCHED_CONTROLS], |program| {
        matched_controls(&candidates, program, g3_utility, seed, global_commit)
    });
    let mut branches = [*model; 4];
    commit_optional(&mut branches[0], g3_program);
    commit(&mut branches[1], greedy_program);
    commit_optional(&mut branches[2], controls[0].map(|control| control.program));
    commit_optional(&mut branches[3], controls[1].map(|control| control.program));
    let mut horizons = [MatchedHorizon::default(); 7];
    let mut horizon_index = 0;
    for committed in 1..=MATCHED_HORIZONS[MATCHED_HORIZONS.len() - 1] {
        if committed > 1 {
            let future_commit = global_commit + committed - 1;
            for branch in &mut branches {
                let (_, _, _, selection) = g3_context(branch, train, seed, future_commit);
                commit_optional(branch, selection.program);
            }
        }
        if committed == MATCHED_HORIZONS[horizon_index] {
            let g3_train_loss = branches[0].loss(train);
            let greedy_train_loss = branches[1].loss(train);
            let control_a_train_loss = branches[2].loss(train);
            let control_b_train_loss = branches[3].loss(train);
            horizons[horizon_index] = MatchedHorizon {
                horizon: committed,
                g3_train_loss,
                greedy_train_loss,
                control_a_train_loss,
                control_b_train_loss,
                g3_validation_loss: branches[0].loss(validation),
                greedy_validation_loss: branches[1].loss(validation),
                control_a_validation_loss: branches[2].loss(validation),
                control_b_validation_loss: branches[3].loss(validation),
                g3_vs_greedy_train_delta: g3_train_loss - greedy_train_loss,
                g3_vs_control_a_train_delta: g3_train_loss - control_a_train_loss,
                g3_vs_control_b_train_delta: g3_train_loss - control_b_train_loss,
                g3_greedy_parameter_distance: parameter_distance(&branches[0], &branches[1]),
                g3_control_a_parameter_distance: parameter_distance(&branches[0], &branches[2]),
                g3_control_b_parameter_distance: parameter_distance(&branches[0], &branches[3]),
            };
            horizon_index += 1;
            if horizon_index == MATCHED_HORIZONS.len() {
                break;
            }
        }
    }
    MatchedSnapshot {
        global_commit,
        selected_present: g3_program.is_some(),
        g3_utility,
        g3_regret: (best_utility - g3_utility).max(0.0),
        greedy_utility,
        greedy_regret: (best_utility - greedy_utility).max(0.0),
        g3_stratum: utility_stratum(g3_utility),
        control_a: matched_control_info(controls[0]),
        control_b: matched_control_info(controls[1]),
        horizons,
    }
}

pub fn run_matched_control(samples: &[Sample], seed: u64) -> MatchedSummary {
    assert_eq!(samples.len(), TOTAL_SAMPLES);
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let mut model = Model::initial();
    let mut snapshots = Vec::with_capacity(MATCHED_SNAPSHOTS);
    for evidence_round in 0..(TOTAL_COMMITS / MATCHED_COMMITS_PER_EVIDENCE) {
        for commit_index in 0..MATCHED_COMMITS_PER_EVIDENCE {
            let global_commit = evidence_round * MATCHED_COMMITS_PER_EVIDENCE + commit_index;
            let (proposal_batch, groups, group_count, selection) =
                g3_context(&model, train, seed, global_commit);
            if global_commit.is_multiple_of(MATCHED_EVERY) {
                snapshots.push(matched_snapshot(
                    &model,
                    train,
                    validation,
                    seed,
                    global_commit,
                    &proposal_batch,
                    &groups,
                    group_count,
                    selection,
                ));
            }
            commit_optional(&mut model, selection.program);
        }
    }
    MatchedSummary {
        seed,
        final_train_loss: model.loss(train),
        final_validation_loss: model.loss(validation),
        final_train_accuracy: model.accuracy(train),
        final_validation_accuracy: model.accuracy(validation),
        snapshots,
    }
}

pub fn matched_control_all(samples: &[Sample]) -> Vec<MatchedSummary> {
    SEEDS
        .into_iter()
        .map(|seed| run_matched_control(samples, seed))
        .collect()
}

pub const CONTINUATION_HORIZONS: [usize; 7] = [1, 2, 4, 8, 16, 32, 64];
pub const CONTINUATION_EVERY: usize = 50;
pub const CONTINUATION_COMMITS_PER_EVIDENCE: usize = 4;
pub const CONTINUATION_SNAPSHOTS: usize = TOTAL_COMMITS / CONTINUATION_EVERY;
pub const CONTINUATION_REPLICATES: usize = 2;
pub const CONTINUATION_STREAMS: usize = 7;
pub const CONTINUATION_SCHEDULE_PHASE: usize = 17;

#[derive(Clone, Copy, Debug, Default)]
pub struct ContinuationHorizon {
    pub horizon: usize,
    pub g3_train_loss: f32,
    pub control_a_train_loss: f32,
    pub control_b_train_loss: f32,
    pub g3_validation_loss: f32,
    pub control_a_validation_loss: f32,
    pub control_b_validation_loss: f32,
    pub g3_vs_control_a_train_delta: f32,
    pub g3_vs_control_b_train_delta: f32,
    pub g3_control_a_parameter_distance: f32,
    pub g3_control_b_parameter_distance: f32,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ContinuationSnapshot {
    pub family: u8,
    pub replicate: usize,
    pub global_commit: usize,
    pub g3_utility: f32,
    pub g3_regret: f32,
    pub control_a: MatchedControlInfo,
    pub control_b: MatchedControlInfo,
    pub horizons: [ContinuationHorizon; 7],
}

#[derive(Clone, Debug)]
pub struct ContinuationSummary {
    pub seed: u64,
    pub final_train_loss: f32,
    pub final_validation_loss: f32,
    pub final_train_accuracy: f32,
    pub final_validation_accuracy: f32,
    pub snapshots: Vec<ContinuationSnapshot>,
}

#[derive(Clone, Copy, Debug, Default)]
struct ContinuationSpec {
    family: u8,
    replicate: usize,
    evidence_seed: u64,
    schedule_phase: usize,
}

fn continuation_specs(seed: u64) -> [ContinuationSpec; CONTINUATION_STREAMS] {
    let mut specs = [ContinuationSpec::default(); CONTINUATION_STREAMS];
    specs[0] = ContinuationSpec {
        family: 0,
        evidence_seed: seed,
        ..ContinuationSpec::default()
    };
    let mut cursor = 1;
    for family in 1..=3 {
        for replicate in 0..CONTINUATION_REPLICATES {
            specs[cursor] = ContinuationSpec {
                family,
                replicate,
                evidence_seed: if family == 2 {
                    seed
                } else {
                    seed ^ 0x4c31_4556_4944_454e ^ ((family as usize * 17 + replicate) as u64)
                },
                schedule_phase: if family == 1 {
                    0
                } else {
                    CONTINUATION_SCHEDULE_PHASE + replicate * 19
                },
            };
            cursor += 1;
        }
    }
    specs
}

fn continuation_selection(
    model: &Model,
    train: &[Sample],
    spec: ContinuationSpec,
    global_commit: usize,
) -> Selection {
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
    let (groups, group_count) = partition((global_commit + spec.schedule_phase) % PARAMS);
    g3_selection_for_context(
        model,
        &proposal_storage,
        &verify_storage[..64],
        &groups,
        group_count,
    )
}

#[allow(clippy::too_many_arguments)]
fn continuation_snapshot(
    model: &Model,
    train: &[Sample],
    validation: &[Sample],
    spec: ContinuationSpec,
    global_commit: usize,
    g3_program: Option<Program>,
    g3_utility: f32,
    g3_regret: f32,
    controls: [Option<MatchedControl>; MATCHED_CONTROLS],
) -> ContinuationSnapshot {
    let mut branches = [*model; 3];
    commit_optional(&mut branches[0], g3_program);
    commit_optional(&mut branches[1], controls[0].map(|control| control.program));
    commit_optional(&mut branches[2], controls[1].map(|control| control.program));
    let mut horizons = [ContinuationHorizon::default(); 7];
    let mut horizon_index = 0;
    for committed in 1..=CONTINUATION_HORIZONS[CONTINUATION_HORIZONS.len() - 1] {
        if committed > 1 {
            let future_commit = global_commit + committed - 1;
            for branch in &mut branches {
                let selection = continuation_selection(branch, train, spec, future_commit);
                commit_optional(branch, selection.program);
            }
        }
        if committed == CONTINUATION_HORIZONS[horizon_index] {
            let g3_train_loss = branches[0].loss(train);
            let control_a_train_loss = branches[1].loss(train);
            let control_b_train_loss = branches[2].loss(train);
            horizons[horizon_index] = ContinuationHorizon {
                horizon: committed,
                g3_train_loss,
                control_a_train_loss,
                control_b_train_loss,
                g3_validation_loss: branches[0].loss(validation),
                control_a_validation_loss: branches[1].loss(validation),
                control_b_validation_loss: branches[2].loss(validation),
                g3_vs_control_a_train_delta: g3_train_loss - control_a_train_loss,
                g3_vs_control_b_train_delta: g3_train_loss - control_b_train_loss,
                g3_control_a_parameter_distance: parameter_distance(&branches[0], &branches[1]),
                g3_control_b_parameter_distance: parameter_distance(&branches[0], &branches[2]),
            };
            horizon_index += 1;
            if horizon_index == CONTINUATION_HORIZONS.len() {
                break;
            }
        }
    }
    ContinuationSnapshot {
        family: spec.family,
        replicate: spec.replicate,
        global_commit,
        g3_utility,
        g3_regret,
        control_a: matched_control_info(controls[0]),
        control_b: matched_control_info(controls[1]),
        horizons,
    }
}

pub fn run_continuation_robustness(samples: &[Sample], seed: u64) -> ContinuationSummary {
    assert_eq!(samples.len(), TOTAL_SAMPLES);
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let mut model = Model::initial();
    let mut snapshots = Vec::with_capacity(CONTINUATION_SNAPSHOTS * CONTINUATION_STREAMS);
    for evidence_round in 0..(TOTAL_COMMITS / CONTINUATION_COMMITS_PER_EVIDENCE) {
        for commit_index in 0..CONTINUATION_COMMITS_PER_EVIDENCE {
            let global_commit = evidence_round * CONTINUATION_COMMITS_PER_EVIDENCE + commit_index;
            let (proposal_batch, groups, group_count, selection) =
                g3_context(&model, train, seed, global_commit);
            if global_commit.is_multiple_of(CONTINUATION_EVERY) {
                let baseline = model.loss(train);
                let g3_utility = selection.program.map_or(0.0, |program| {
                    exact_program_value(&model, train, baseline, program)
                });
                let candidates =
                    candidate_universe(&model, train, &proposal_batch, &groups, group_count);
                let best_utility = candidates
                    .iter()
                    .map(|candidate| candidate.utility)
                    .fold(f32::NEG_INFINITY, f32::max);
                let controls = selection
                    .program
                    .map_or([None; MATCHED_CONTROLS], |program| {
                        matched_controls(&candidates, program, g3_utility, seed, global_commit)
                    });
                let g3_regret = (best_utility - g3_utility).max(0.0);
                for spec in continuation_specs(seed) {
                    let mut snapshot = continuation_snapshot(
                        &model,
                        train,
                        validation,
                        spec,
                        global_commit,
                        selection.program,
                        g3_utility,
                        g3_regret,
                        controls,
                    );
                    if selection.program.is_none() {
                        snapshot.control_a = MatchedControlInfo::default();
                        snapshot.control_b = MatchedControlInfo::default();
                    }
                    snapshots.push(snapshot);
                }
            }
            commit_optional(&mut model, selection.program);
        }
    }
    ContinuationSummary {
        seed,
        final_train_loss: model.loss(train),
        final_validation_loss: model.loss(validation),
        final_train_accuracy: model.accuracy(train),
        final_validation_accuracy: model.accuracy(validation),
        snapshots,
    }
}

pub fn continuation_robustness_all(samples: &[Sample]) -> Vec<ContinuationSummary> {
    SEEDS
        .into_iter()
        .map(|seed| run_continuation_robustness(samples, seed))
        .collect()
}

pub const SAME_BLOCK_HORIZONS: [usize; 7] = [1, 2, 4, 8, 16, 32, 64];
pub const SAME_BLOCK_EVERY: usize = 50;
pub const SAME_BLOCK_COMMITS_PER_EVIDENCE: usize = 4;
pub const SAME_BLOCK_SNAPSHOTS: usize = TOTAL_COMMITS / SAME_BLOCK_EVERY;
pub const SAME_BLOCK_DOMAINS: [u8; 2] = [1, 2];
pub const SAME_BLOCK_SCHEDULE_PHASES: [usize; 3] = [0, 17, 36];
pub const SAME_BLOCK_MATCH_TOLERANCE: f32 = MATCHED_REGRET_TOLERANCE;

#[derive(Clone, Copy, Debug, Default)]
pub struct SameBlockHorizon {
    pub horizon: usize,
    pub g3_train_loss: f32,
    pub control_a_train_loss: f32,
    pub control_b_train_loss: f32,
    pub g3_validation_loss: f32,
    pub control_a_validation_loss: f32,
    pub control_b_validation_loss: f32,
    pub g3_vs_control_a_train_delta: f32,
    pub g3_vs_control_b_train_delta: f32,
    pub g3_control_a_parameter_distance: f32,
    pub g3_control_b_parameter_distance: f32,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SameBlockSnapshot {
    pub domain: u8,
    pub family: u8,
    pub replicate: usize,
    pub global_commit: usize,
    pub group_left: usize,
    pub group_right: usize,
    pub selected_pair: bool,
    pub g3_utility: f32,
    pub g3_stratum: u8,
    pub control_a: MatchedControlInfo,
    pub control_b: MatchedControlInfo,
    pub horizons: [SameBlockHorizon; 7],
}

#[derive(Clone, Debug)]
pub struct SameBlockSummary {
    pub seed: u64,
    pub final_train_loss: f32,
    pub final_validation_loss: f32,
    pub final_train_accuracy: f32,
    pub final_validation_accuracy: f32,
    pub snapshots: Vec<SameBlockSnapshot>,
}

fn same_block_specs(seed: u64) -> [ContinuationSpec; 3] {
    [
        ContinuationSpec {
            family: 0,
            replicate: 0,
            evidence_seed: seed,
            schedule_phase: SAME_BLOCK_SCHEDULE_PHASES[0],
        },
        ContinuationSpec {
            family: 2,
            replicate: 0,
            evidence_seed: seed,
            schedule_phase: SAME_BLOCK_SCHEDULE_PHASES[1],
        },
        ContinuationSpec {
            family: 2,
            replicate: 1,
            evidence_seed: seed,
            schedule_phase: SAME_BLOCK_SCHEDULE_PHASES[2],
        },
    ]
}

fn same_block_candidate_programs(
    model: &Model,
    proposal_batch: &[Sample],
    group: Group,
    domain: u8,
) -> ([Program; ACTION_VALUES.len() * ACTION_VALUES.len()], usize) {
    let mut programs = [Program::default(); ACTION_VALUES.len() * ACTION_VALUES.len()];
    if group.len != 2 {
        return (programs, 0);
    }
    if domain == 1 {
        let (shortlist, count) = diagnostic_candidates(model, proposal_batch, group);
        programs[..count].copy_from_slice(&shortlist[..count]);
        return (programs, count);
    }
    let mut count = 0;
    for &left in &ACTION_VALUES {
        for &right in &ACTION_VALUES {
            programs[count] = Program {
                left: group.left,
                right: group.right,
                deltas: [left, right],
                len: 2,
                ..Program::default()
            };
            count += 1;
        }
    }
    (programs, count)
}

#[allow(clippy::too_many_arguments)]
fn same_block_controls(
    model: &Model,
    train: &[Sample],
    proposal_batch: &[Sample],
    group: Group,
    g3_program: Option<Program>,
    g3_utility: f32,
    domain: u8,
    seed: u64,
    global_commit: usize,
) -> [Option<MatchedControl>; MATCHED_CONTROLS] {
    let Some(g3_program) = g3_program else {
        return [None; MATCHED_CONTROLS];
    };
    if g3_program.len != 2 || group.len != 2 {
        return [None; MATCHED_CONTROLS];
    }
    let baseline = model.loss(train);
    let (programs, count) = same_block_candidate_programs(model, proposal_batch, group, domain);
    let g3_stratum = utility_stratum(g3_utility);
    let mut eligible: Vec<(f32, u64, MatchedControl)> = Vec::with_capacity(count);
    for (index, &program) in programs[..count].iter().enumerate() {
        if same_program(Some(program), Some(g3_program)) {
            continue;
        }
        let utility = exact_program_value(model, train, baseline, program);
        if utility_stratum(utility) != g3_stratum {
            continue;
        }
        let utility_gap = (utility - g3_utility).abs();
        if utility_gap > SAME_BLOCK_MATCH_TOLERANCE {
            continue;
        }
        eligible.push((
            utility_gap,
            deterministic_match_key(seed, global_commit, index),
            MatchedControl {
                program,
                utility,
                regret: (g3_utility - utility).max(0.0),
                stratum: utility_stratum(utility),
                regret_gap: utility_gap,
            },
        ));
    }
    eligible.sort_by(|left, right| {
        left.0
            .total_cmp(&right.0)
            .then_with(|| left.1.cmp(&right.1))
    });
    let mut selected = [None; MATCHED_CONTROLS];
    for (slot, (_, _, control)) in eligible.into_iter().take(MATCHED_CONTROLS).enumerate() {
        selected[slot] = Some(control);
    }
    selected
}

#[allow(clippy::too_many_arguments)]
fn same_block_snapshot(
    model: &Model,
    train: &[Sample],
    validation: &[Sample],
    spec: ContinuationSpec,
    global_commit: usize,
    group: Group,
    g3_program: Option<Program>,
    g3_utility: f32,
    domain: u8,
    controls: [Option<MatchedControl>; MATCHED_CONTROLS],
) -> SameBlockSnapshot {
    let mut branches = [*model; 3];
    commit_optional(&mut branches[0], g3_program);
    commit_optional(&mut branches[1], controls[0].map(|control| control.program));
    commit_optional(&mut branches[2], controls[1].map(|control| control.program));
    let mut horizons = [SameBlockHorizon::default(); 7];
    let mut horizon_index = 0;
    for committed in 1..=SAME_BLOCK_HORIZONS[SAME_BLOCK_HORIZONS.len() - 1] {
        if committed > 1 {
            let future_commit = global_commit + committed - 1;
            for branch in &mut branches {
                let selection = continuation_selection(branch, train, spec, future_commit);
                commit_optional(branch, selection.program);
            }
        }
        if committed == SAME_BLOCK_HORIZONS[horizon_index] {
            let g3_train_loss = branches[0].loss(train);
            let control_a_train_loss = branches[1].loss(train);
            let control_b_train_loss = branches[2].loss(train);
            horizons[horizon_index] = SameBlockHorizon {
                horizon: committed,
                g3_train_loss,
                control_a_train_loss,
                control_b_train_loss,
                g3_validation_loss: branches[0].loss(validation),
                control_a_validation_loss: branches[1].loss(validation),
                control_b_validation_loss: branches[2].loss(validation),
                g3_vs_control_a_train_delta: g3_train_loss - control_a_train_loss,
                g3_vs_control_b_train_delta: g3_train_loss - control_b_train_loss,
                g3_control_a_parameter_distance: parameter_distance(&branches[0], &branches[1]),
                g3_control_b_parameter_distance: parameter_distance(&branches[0], &branches[2]),
            };
            horizon_index += 1;
            if horizon_index == SAME_BLOCK_HORIZONS.len() {
                break;
            }
        }
    }
    SameBlockSnapshot {
        domain,
        family: spec.family,
        replicate: spec.replicate,
        global_commit,
        group_left: group.left,
        group_right: group.right,
        selected_pair: g3_program.is_some_and(|program| program.len == 2),
        g3_utility,
        g3_stratum: utility_stratum(g3_utility),
        control_a: matched_control_info(controls[0]),
        control_b: matched_control_info(controls[1]),
        horizons,
    }
}

pub fn run_same_block_control(samples: &[Sample], seed: u64) -> SameBlockSummary {
    assert_eq!(samples.len(), TOTAL_SAMPLES);
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let mut model = Model::initial();
    let mut snapshots = Vec::with_capacity(
        SAME_BLOCK_SNAPSHOTS * SAME_BLOCK_SCHEDULE_PHASES.len() * SAME_BLOCK_DOMAINS.len(),
    );
    for evidence_round in 0..(TOTAL_COMMITS / SAME_BLOCK_COMMITS_PER_EVIDENCE) {
        for commit_index in 0..SAME_BLOCK_COMMITS_PER_EVIDENCE {
            let global_commit = evidence_round * SAME_BLOCK_COMMITS_PER_EVIDENCE + commit_index;
            let (proposal_batch, _groups, _group_count, selection) =
                g3_context(&model, train, seed, global_commit);
            if global_commit.is_multiple_of(SAME_BLOCK_EVERY) {
                let baseline = model.loss(train);
                let g3_utility = selection.program.map_or(0.0, |program| {
                    exact_program_value(&model, train, baseline, program)
                });
                for domain in SAME_BLOCK_DOMAINS {
                    let controls = same_block_controls(
                        &model,
                        train,
                        &proposal_batch,
                        selection.group,
                        selection.program,
                        g3_utility,
                        domain,
                        seed,
                        global_commit,
                    );
                    for spec in same_block_specs(seed) {
                        snapshots.push(same_block_snapshot(
                            &model,
                            train,
                            validation,
                            spec,
                            global_commit,
                            selection.group,
                            selection.program,
                            g3_utility,
                            domain,
                            controls,
                        ));
                    }
                }
            }
            commit_optional(&mut model, selection.program);
        }
    }
    SameBlockSummary {
        seed,
        final_train_loss: model.loss(train),
        final_validation_loss: model.loss(validation),
        final_train_accuracy: model.accuracy(train),
        final_validation_accuracy: model.accuracy(validation),
        snapshots,
    }
}

pub fn same_block_control_all(samples: &[Sample]) -> Vec<SameBlockSummary> {
    SEEDS
        .into_iter()
        .map(|seed| run_same_block_control(samples, seed))
        .collect()
}

mod ar02a;
pub use ar02a::{
    AR02A_COMMITS, AR02A_METHODS, AR02A_SEEDS, GaussianMappedDataset, Method, RunResult,
    generate_gaussian_cells, run_ar02a, run_method, write_gaussian_dataset, write_results,
};

mod ar02ar1;
pub use ar02ar1::{
    PathSourceReport, R1_METHODS, R1_SEEDS, R1RunResult, R1Spec, VerifierKind, run_ar02a_r1,
    run_path_source_crossover, run_path_source_crossover_with_seeds, run_r1_method_for_commits,
    run_r2_audit, run_r2_variance_audit,
};

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
    fn diagnostic_family_layout_is_contiguous() {
        assert_eq!(DIAGNOSTIC_FAMILY_OFFSETS[0], 0);
        for family in 0..DIAGNOSTIC_FAMILY_COUNT - 1 {
            assert_eq!(
                DIAGNOSTIC_FAMILY_OFFSETS[family] + DIAGNOSTIC_FAMILY_COUNTS[family],
                DIAGNOSTIC_FAMILY_OFFSETS[family + 1]
            );
        }
        assert_eq!(
            DIAGNOSTIC_FAMILY_OFFSETS[DIAGNOSTIC_FAMILY_COUNT - 1]
                + DIAGNOSTIC_FAMILY_COUNTS[DIAGNOSTIC_FAMILY_COUNT - 1],
            12
        );
        assert_eq!(DIAGNOSTIC_FAMILY_SIZES, [16, 32, 48, 96]);
    }

    #[test]
    fn same_block_control_domains_have_frozen_widths() {
        let dataset = spiral_dataset();
        let model = Model::initial();
        let proposal = &dataset.samples[..BATCH_SIZE];
        let group = Group {
            left: 0,
            right: 1,
            len: 2,
        };
        let (_, shortlist_count) = same_block_candidate_programs(&model, proposal, group, 1);
        let (_, exhaustive_count) = same_block_candidate_programs(&model, proposal, group, 2);
        assert_eq!(shortlist_count, 4);
        assert_eq!(exhaustive_count, ACTION_VALUES.len() * ACTION_VALUES.len());
        assert_eq!(SAME_BLOCK_SCHEDULE_PHASES, [0, 17, 36]);
    }

    #[cfg(feature = "tanh")]
    #[test]
    fn tanh_backprop_matches_finite_differences_across_layers() {
        let dataset = generate_gaussian_cells();
        let sample = dataset.samples[0];
        let mut model = Model::initial();
        let (_, gradient) = model.gradient(std::slice::from_ref(&sample));
        let epsilon = 1.0e-3;
        for parameter in [0, 16, 24, 88, 96, 120] {
            let original = model.parameters[parameter];
            model.parameters[parameter] = original + epsilon;
            let plus = model.loss(std::slice::from_ref(&sample));
            model.parameters[parameter] = original - epsilon;
            let minus = model.loss(std::slice::from_ref(&sample));
            model.parameters[parameter] = original;
            let numeric = (plus - minus) / (2.0 * epsilon);
            assert!(
                (numeric - gradient[parameter]).abs() < 2.0e-3,
                "gradient mismatch at {parameter}: numeric={numeric}, analytic={}",
                gradient[parameter]
            );
        }
    }

    #[test]
    fn short_runtime_run_commits_a_program() {
        let dataset = spiral_dataset();
        let result = run(&dataset.samples, Arm::G2Balanced64, SEEDS[0]);
        assert!(result.telemetry.committed_programs > 0);
        assert!(result.telemetry.compound_evaluations > 0);
        assert!(result.coverage.ever_pairs > 0);
    }
}
