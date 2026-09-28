use std::{
    fs::{File, OpenOptions},
    io::{self, Write},
    mem::size_of,
    path::Path,
};

use bytemuck::{Pod, Zeroable, cast_slice, try_cast_slice};
use memchr::memmem;
use memmap2::{Mmap, MmapOptions};
use wide::f32x4;
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout};

pub const INPUTS: usize = 2;
pub const HIDDEN: usize = 4;
pub const PARAMS: usize = INPUTS * HIDDEN + HIDDEN + HIDDEN + 1;
pub const DATASET_MAGIC: &[u8; 8] = b"AR00XOR\0";
const DATASET_HEADER_BYTES: usize = size_of::<DatasetHeader>();

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
    pub target: f32,
}

pub const fn xor_samples() -> [Sample; 4] {
    [
        Sample {
            x0: 0.0,
            x1: 0.0,
            target: 0.0,
        },
        Sample {
            x0: 0.0,
            x1: 1.0,
            target: 1.0,
        },
        Sample {
            x0: 1.0,
            x1: 0.0,
            target: 1.0,
        },
        Sample {
            x0: 1.0,
            x1: 1.0,
            target: 0.0,
        },
    ]
}

pub fn write_dataset(path: impl AsRef<Path>) -> io::Result<()> {
    let samples = xor_samples();
    let header = DatasetHeader {
        magic: *DATASET_MAGIC,
        sample_count: samples.len() as u32,
        row_stride: size_of::<Sample>() as u32,
    };
    let mut bytes = Vec::with_capacity(size_of::<DatasetHeader>() + size_of_val(&samples));
    bytes.extend_from_slice(header.as_bytes());
    bytes.extend_from_slice(cast_slice(&samples));
    if let Some(parent) = path.as_ref().parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut file = File::create(path)?;
    file.write_all(&bytes)
}

pub struct MappedDataset {
    mmap: Mmap,
    sample_count: usize,
}

impl MappedDataset {
    pub fn open(path: impl AsRef<Path>) -> io::Result<Self> {
        let file = OpenOptions::new().read(true).open(path)?;
        // SAFETY: the file is opened read-only and the mapping is owned by Self.
        let mmap = unsafe { MmapOptions::new().map(&file)? };
        if mmap.len() < DATASET_HEADER_BYTES
            || memmem::find(&mmap[..DATASET_MAGIC.len()], DATASET_MAGIC) != Some(0)
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "AR-00 dataset magic mismatch",
            ));
        }
        let (declared_sample_count, row_stride) = {
            let header = DatasetHeader::ref_from_bytes(&mmap[..DATASET_HEADER_BYTES])
                .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "invalid AR-00 header"))?;
            (header.sample_count as usize, header.row_stride as usize)
        };
        if row_stride != size_of::<Sample>() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "AR-00 sample stride mismatch",
            ));
        }
        let payload = &mmap[DATASET_HEADER_BYTES..];
        let rows = try_cast_slice::<u8, Sample>(payload).map_err(|_| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                "AR-00 sample alignment mismatch",
            )
        })?;
        let sample_count = rows.len();
        if sample_count != declared_sample_count {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "AR-00 sample count mismatch",
            ));
        }
        Ok(Self { mmap, sample_count })
    }

    #[inline]
    pub fn samples(&self) -> &[Sample] {
        try_cast_slice(&self.mmap[DATASET_HEADER_BYTES..]).expect("validated AR-00 mapping")
    }

    #[inline]
    pub const fn len(&self) -> usize {
        self.sample_count
    }

    #[inline]
    pub const fn is_empty(&self) -> bool {
        self.sample_count == 0
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Model {
    pub parameters: [f32; PARAMS],
}

impl Model {
    pub const fn initial() -> Self {
        Self {
            // W1 row-major, b1, W2, b2. Deliberately fixed and non-symmetric.
            parameters: [
                0.35, -0.42, -0.31, 0.27, 0.55, 0.18, -0.21, -0.49, 0.05, -0.08, 0.03, 0.02, 0.40,
                -0.60, 0.50, -0.70, 0.10,
            ],
        }
    }

    #[inline]
    pub fn predict(&self, sample: Sample) -> f32 {
        self.forward(sample).output
    }

    fn forward(&self, sample: Sample) -> Forward {
        let mut hidden = [0.0; HIDDEN];
        for (hidden_index, value) in hidden.iter_mut().enumerate() {
            let weight = hidden_index * INPUTS;
            let pre_activation = self.parameters[weight] * sample.x0
                + self.parameters[weight + 1] * sample.x1
                + self.parameters[INPUTS * HIDDEN + hidden_index];
            *value = pre_activation.max(0.0);
        }
        let output_start = INPUTS * HIDDEN + HIDDEN;
        let logit = hidden
            .iter()
            .enumerate()
            .map(|(index, value)| self.parameters[output_start + index] * value)
            .sum::<f32>()
            + self.parameters[PARAMS - 1];
        Forward {
            hidden,
            output: sigmoid(logit),
        }
    }

    pub fn loss_and_gradient(&self, samples: &[Sample]) -> (f32, [f32; PARAMS]) {
        assert!(!samples.is_empty(), "AR-00 requires at least one sample");
        let mut gradient = [0.0; PARAMS];
        let mut loss = 0.0;
        let output_start = INPUTS * HIDDEN + HIDDEN;
        for &sample in samples {
            let forward = self.forward(sample);
            let prediction = forward.output.clamp(1e-6, 1.0 - 1e-6);
            loss -=
                sample.target * prediction.ln() + (1.0 - sample.target) * (1.0 - prediction).ln();
            let output_error = forward.output - sample.target;
            for hidden_index in 0..HIDDEN {
                gradient[output_start + hidden_index] +=
                    output_error * forward.hidden[hidden_index];
                let hidden_error = output_error * self.parameters[output_start + hidden_index];
                let pre_activation = self.parameters[hidden_index * INPUTS] * sample.x0
                    + self.parameters[hidden_index * INPUTS + 1] * sample.x1
                    + self.parameters[INPUTS * HIDDEN + hidden_index];
                let local_error = if pre_activation > 0.0 {
                    hidden_error
                } else {
                    0.0
                };
                gradient[hidden_index * INPUTS] += local_error * sample.x0;
                gradient[hidden_index * INPUTS + 1] += local_error * sample.x1;
                gradient[INPUTS * HIDDEN + hidden_index] += local_error;
            }
            gradient[PARAMS - 1] += output_error;
        }
        let inverse_count = 1.0 / samples.len() as f32;
        for value in &mut gradient {
            *value *= inverse_count;
        }
        (loss * inverse_count, gradient)
    }

    pub fn accuracy(&self, samples: &[Sample]) -> f32 {
        let correct = samples
            .iter()
            .filter(|sample| (self.predict(**sample) >= 0.5) == (sample.target >= 0.5))
            .count();
        correct as f32 / samples.len() as f32
    }

    pub fn simd_mean_squared_error(&self, samples: &[Sample]) -> f32 {
        let mut total_vector = f32x4::splat(0.0);
        let chunks_end = samples.len() / 4 * 4;
        for chunk in samples[..chunks_end].chunks_exact(4) {
            let prediction = f32x4::from([
                self.predict(chunk[0]),
                self.predict(chunk[1]),
                self.predict(chunk[2]),
                self.predict(chunk[3]),
            ]);
            let target = f32x4::from([
                chunk[0].target,
                chunk[1].target,
                chunk[2].target,
                chunk[3].target,
            ]);
            let error = prediction - target;
            total_vector += error * error;
        }
        let mut total = total_vector.to_array().iter().sum::<f32>();
        for &sample in &samples[chunks_end..] {
            let error = self.predict(sample) - sample.target;
            total += error * error;
        }
        total / samples.len() as f32
    }
}

#[derive(Clone, Copy, Debug)]
struct Forward {
    hidden: [f32; HIDDEN],
    output: f32,
}

#[inline]
fn sigmoid(value: f32) -> f32 {
    1.0 / (1.0 + (-value).exp())
}

#[derive(Clone, Copy, Debug)]
pub struct AdamW {
    step: u32,
    first: [f32; PARAMS],
    second: [f32; PARAMS],
    learning_rate: f32,
    beta1: f32,
    beta2: f32,
    epsilon: f32,
}

impl AdamW {
    pub const fn new(learning_rate: f32) -> Self {
        Self {
            step: 0,
            first: [0.0; PARAMS],
            second: [0.0; PARAMS],
            learning_rate,
            beta1: 0.9,
            beta2: 0.999,
            epsilon: 1e-8,
        }
    }

    pub fn step(&mut self, model: &mut Model, gradient: &[f32; PARAMS]) {
        self.step += 1;
        let beta1_correction = 1.0 - self.beta1.powi(self.step as i32);
        let beta2_correction = 1.0 - self.beta2.powi(self.step as i32);
        for (index, &gradient_value) in gradient.iter().enumerate() {
            self.first[index] =
                self.beta1 * self.first[index] + (1.0 - self.beta1) * gradient_value;
            self.second[index] = self.beta2 * self.second[index]
                + (1.0 - self.beta2) * gradient_value * gradient_value;
            let first_hat = self.first[index] / beta1_correction;
            let second_hat = self.second[index] / beta2_correction;
            model.parameters[index] -=
                self.learning_rate * first_hat / (second_hat.sqrt() + self.epsilon);
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct ActionStats {
    pub selected: u64,
    pub no_op: u64,
    pub blocked: u64,
}

#[derive(Clone, Copy, Debug)]
pub struct ActionRuntime {
    enabled: [bool; PARAMS],
    lower: f32,
    upper: f32,
    action_step: f32,
    pub stats: ActionStats,
}

impl ActionRuntime {
    pub const fn new(action_step: f32, lower: f32, upper: f32) -> Self {
        Self {
            enabled: [true; PARAMS],
            lower,
            upper,
            action_step,
            stats: ActionStats {
                selected: 0,
                no_op: 0,
                blocked: 0,
            },
        }
    }

    pub fn set_enabled(&mut self, index: usize, enabled: bool) {
        self.enabled[index] = enabled;
    }

    pub fn apply(&mut self, model: &mut Model, gradient: &[f32; PARAMS]) {
        let previous = model.parameters;
        for index in 0..PARAMS {
            if !self.enabled[index] {
                self.stats.no_op += 1;
                continue;
            }
            let current = previous[index];
            let mut best_delta = 0.0;
            let mut best_utility = 0.0;
            for delta in [-self.action_step, self.action_step] {
                let candidate = current + delta;
                if !(self.lower..=self.upper).contains(&candidate) {
                    self.stats.blocked += 1;
                    continue;
                }
                // First-order utility: gradient descent prefers -gradient * delta.
                let utility = -gradient[index] * delta;
                if utility > best_utility {
                    best_utility = utility;
                    best_delta = delta;
                }
            }
            if best_delta == 0.0 {
                self.stats.no_op += 1;
            } else {
                model.parameters[index] = current + best_delta;
                self.stats.selected += 1;
            }
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RunResult {
    pub epochs: usize,
    pub final_loss: f32,
    pub final_accuracy: f32,
    pub final_mse: f32,
    pub action_stats: ActionStats,
}

pub fn run_adamw(samples: &[Sample], epochs: usize) -> RunResult {
    let mut model = Model::initial();
    let mut optimizer = AdamW::new(0.03);
    for _ in 0..epochs {
        let (_, gradient) = model.loss_and_gradient(samples);
        optimizer.step(&mut model, &gradient);
    }
    let (final_loss, _) = model.loss_and_gradient(samples);
    RunResult {
        epochs,
        final_loss,
        final_accuracy: model.accuracy(samples),
        final_mse: model.simd_mean_squared_error(samples),
        action_stats: ActionStats::default(),
    }
}

pub fn run_interposed(samples: &[Sample], epochs: usize) -> RunResult {
    let mut model = Model::initial();
    let mut runtime = ActionRuntime::new(0.02, -3.0, 3.0);
    for _ in 0..epochs {
        let (_, gradient) = model.loss_and_gradient(samples);
        runtime.apply(&mut model, &gradient);
    }
    let (final_loss, _) = model.loss_and_gradient(samples);
    RunResult {
        epochs,
        final_loss,
        final_accuracy: model.accuracy(samples),
        final_mse: model.simd_mean_squared_error(samples),
        action_stats: runtime.stats,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mapped_dataset_round_trips_without_copying_rows() {
        let path = std::env::temp_dir().join(format!("ar00-{}.bin", std::process::id()));
        write_dataset(&path).expect("write dataset");
        let mapped = MappedDataset::open(&path).expect("map dataset");
        assert_eq!(mapped.len(), 4);
        assert_eq!(mapped.samples()[1].target, 1.0);
        std::fs::remove_file(path).expect("remove temporary dataset");
    }

    #[test]
    fn authority_gate_blocks_disabled_and_out_of_bounds_actions() {
        let mut model = Model::initial();
        model.parameters[0] = 2.99;
        let gradient = [1.0; PARAMS];
        let mut runtime = ActionRuntime::new(0.02, -3.0, 3.0);
        runtime.set_enabled(1, false);
        runtime.apply(&mut model, &gradient);
        assert_eq!(model.parameters[1], Model::initial().parameters[1]);
        assert!(runtime.stats.blocked > 0);
        assert!(runtime.stats.no_op > 0);
    }

    #[test]
    fn both_arms_learn_xor() {
        let samples = xor_samples();
        let baseline = run_adamw(&samples, 3_000);
        let interposed = run_interposed(&samples, 3_000);
        assert_eq!(baseline.final_accuracy, 1.0);
        assert_eq!(interposed.final_accuracy, 1.0);
        assert!(interposed.action_stats.selected > 0);
        assert!(baseline.final_loss < 0.2);
        assert!(interposed.final_loss < 0.35);
    }
}
