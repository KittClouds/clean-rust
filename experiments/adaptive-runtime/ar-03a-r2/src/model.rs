use std::fs::{self, File, OpenOptions};
use std::io::{self, BufWriter, Write};
use std::mem::size_of;
use std::path::Path;

use bytemuck::{Pod, Zeroable, cast_slice};
use memchr::memmem;
use memmap2::{Mmap, MmapOptions};
use wide::f32x4;
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout};

pub const INPUTS: usize = 8;
pub const HIDDEN_1: usize = 8;
pub const HIDDEN_2: usize = 8;
pub const CLASSES: usize = 3;
pub const TRAIN_SAMPLES: usize = 96;
pub const BATCH_SIZE: usize = 16;
pub const VERIFIER_SIZE: usize = 48;
pub const LOWER_BOUND: f32 = -2.0;
pub const UPPER_BOUND: f32 = 2.0;
pub const ACTION_VALUES: [f32; 7] = [0.0, -0.02, 0.02, -0.01, 0.01, -0.005, 0.005];
pub const PARAMS: usize =
    INPUTS * HIDDEN_1 + HIDDEN_1 + HIDDEN_1 * HIDDEN_2 + HIDDEN_2 + HIDDEN_2 * CLASSES + CLASSES;
const MAGIC: &[u8; 8] = b"AR03R2D1";
const HEADER_BYTES: usize = size_of::<DatasetHeader>();

const W1: usize = 0;
const B1: usize = W1 + INPUTS * HIDDEN_1;
const W2: usize = B1 + HIDDEN_1;
const B2: usize = W2 + HIDDEN_1 * HIDDEN_2;
const W3: usize = B2 + HIDDEN_2;
const B3: usize = W3 + HIDDEN_2 * CLASSES;

#[derive(Clone, Copy, Debug, FromBytes, Immutable, IntoBytes, KnownLayout, Pod, Zeroable)]
#[repr(C)]
struct DatasetHeader {
    magic: [u8; 8],
    sample_count: u32,
    row_stride: u32,
}

#[derive(Clone, Copy, Debug, FromBytes, Immutable, IntoBytes, KnownLayout, Pod, Zeroable)]
#[repr(C)]
pub struct Sample {
    pub x: [f32; INPUTS],
    pub target: u32,
}

pub struct MappedDataset {
    mmap: Mmap,
}

impl MappedDataset {
    pub fn generate_write_open(path: impl AsRef<Path>, seed: u64) -> io::Result<Self> {
        let samples = generate_dataset(seed);
        write_dataset(path.as_ref(), &samples)?;
        Self::open(path)
    }

    pub fn open(path: impl AsRef<Path>) -> io::Result<Self> {
        let file = OpenOptions::new().read(true).open(path)?;
        // SAFETY: the file is opened read-only and the mapping is owned by Self.
        let mmap = unsafe { MmapOptions::new().map(&file)? };
        if mmap.len() < HEADER_BYTES || memmem::find(&mmap[..8], MAGIC) != Some(0) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "AR-03A-R2 dataset magic mismatch",
            ));
        }
        let header = DatasetHeader::ref_from_bytes(&mmap[..HEADER_BYTES])
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "invalid dataset header"))?;
        if header.sample_count as usize != TRAIN_SAMPLES
            || header.row_stride as usize != size_of::<Sample>()
            || mmap.len() != HEADER_BYTES + TRAIN_SAMPLES * size_of::<Sample>()
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "AR-03A-R2 dataset layout mismatch",
            ));
        }
        Ok(Self { mmap })
    }

    #[inline]
    pub fn samples(&self) -> &[Sample] {
        bytemuck::try_cast_slice(&self.mmap[HEADER_BYTES..]).expect("validated binary layout")
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Model {
    pub parameters: [f32; PARAMS],
}

impl Model {
    pub fn initial(seed: u64) -> Self {
        let mut rng = NormalRng::new(seed);
        let parameters = std::array::from_fn(|_| (0.16 * rng.normal()) as f32);
        Self { parameters }
    }

    #[inline]
    pub fn logits(&self, sample: &Sample) -> ([f32; CLASSES], [f32; HIDDEN_1], [f32; HIDDEN_2]) {
        let mut hidden_1 = [0.0; HIDDEN_1];
        for (unit, activation) in hidden_1.iter_mut().enumerate() {
            let offset = W1 + unit * INPUTS;
            *activation = (dot8(&self.parameters[offset..offset + INPUTS], &sample.x)
                + self.parameters[B1 + unit])
                .max(0.0);
        }

        let mut hidden_2 = [0.0; HIDDEN_2];
        for (unit, activation) in hidden_2.iter_mut().enumerate() {
            let offset = W2 + unit * HIDDEN_1;
            *activation = (dot8(&self.parameters[offset..offset + HIDDEN_1], &hidden_1)
                + self.parameters[B2 + unit])
                .max(0.0);
        }

        let mut logits = [0.0; CLASSES];
        for (class, logit) in logits.iter_mut().enumerate() {
            let offset = W3 + class * HIDDEN_2;
            *logit = dot8(&self.parameters[offset..offset + HIDDEN_2], &hidden_2)
                + self.parameters[B3 + class];
        }
        (logits, hidden_1, hidden_2)
    }

    #[inline]
    pub fn loss_one(&self, sample: &Sample) -> f32 {
        let logits = self.logits(sample).0;
        let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        let exponential_sum = logits
            .iter()
            .map(|value| (*value - maximum).exp())
            .sum::<f32>();
        maximum + exponential_sum.ln() - logits[sample.target as usize]
    }

    pub fn loss(&self, samples: &[Sample]) -> f32 {
        assert!(!samples.is_empty());
        samples
            .iter()
            .map(|sample| self.loss_one(sample))
            .sum::<f32>()
            / samples.len() as f32
    }

    pub fn gradient_one(&self, sample: &Sample) -> (f32, [f32; PARAMS]) {
        let (logits, hidden_1, hidden_2) = self.logits(sample);
        let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        let exponential_sum = logits
            .iter()
            .map(|value| (*value - maximum).exp())
            .sum::<f32>();
        let mut output_error = [0.0; CLASSES];
        for (class, error) in output_error.iter_mut().enumerate() {
            *error = (logits[class] - maximum).exp() / exponential_sum;
        }
        output_error[sample.target as usize] -= 1.0;

        let mut gradient = [0.0; PARAMS];
        let mut hidden_2_error = [0.0; HIDDEN_2];
        for class in 0..CLASSES {
            let offset = W3 + class * HIDDEN_2;
            gradient[B3 + class] = output_error[class];
            for input in 0..HIDDEN_2 {
                gradient[offset + input] = output_error[class] * hidden_2[input];
                hidden_2_error[input] += output_error[class] * self.parameters[offset + input];
            }
        }

        let mut hidden_1_error = [0.0; HIDDEN_1];
        for unit in 0..HIDDEN_2 {
            let error = if hidden_2[unit] > 0.0 {
                hidden_2_error[unit]
            } else {
                0.0
            };
            gradient[B2 + unit] = error;
            let offset = W2 + unit * HIDDEN_1;
            for input in 0..HIDDEN_1 {
                gradient[offset + input] = error * hidden_1[input];
                hidden_1_error[input] += error * self.parameters[offset + input];
            }
        }

        for unit in 0..HIDDEN_1 {
            let error = if hidden_1[unit] > 0.0 {
                hidden_1_error[unit]
            } else {
                0.0
            };
            gradient[B1 + unit] = error;
            let offset = W1 + unit * INPUTS;
            for input in 0..INPUTS {
                gradient[offset + input] = error * sample.x[input];
            }
        }

        let loss = maximum + exponential_sum.ln() - logits[sample.target as usize];
        (loss, gradient)
    }
}

fn dot8(weights: &[f32], values: &[f32; 8]) -> f32 {
    let left = f32x4::from([weights[0], weights[1], weights[2], weights[3]])
        * f32x4::from([values[0], values[1], values[2], values[3]]);
    let right = f32x4::from([weights[4], weights[5], weights[6], weights[7]])
        * f32x4::from([values[4], values[5], values[6], values[7]]);
    left.to_array().into_iter().sum::<f32>() + right.to_array().into_iter().sum::<f32>()
}

fn write_dataset(path: &Path, samples: &[Sample; TRAIN_SAMPLES]) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let header = DatasetHeader {
        magic: *MAGIC,
        sample_count: TRAIN_SAMPLES as u32,
        row_stride: size_of::<Sample>() as u32,
    };
    let mut output = BufWriter::new(File::create(path)?);
    output.write_all(header.as_bytes())?;
    output.write_all(cast_slice(samples))?;
    output.flush()
}

pub(crate) fn generate_dataset(seed: u64) -> [Sample; TRAIN_SAMPLES] {
    let mut rng = NormalRng::new(seed);
    std::array::from_fn(|_| {
        let latent = std::array::from_fn::<_, INPUTS, _>(|_| rng.normal() as f32);
        let interaction = latent[0] * latent[1] + latent[2] * latent[3] - latent[4] * latent[5]
            + latent[6] * latent[7];
        let noise_scale = 0.04 + 0.18 / (1.0 + (-0.7 * interaction).exp());
        let mut observed = latent;
        for coordinate in 0..INPUTS {
            observed[coordinate] = latent[coordinate] + noise_scale * rng.normal() as f32;
        }

        let scores = [
            latent[0] * latent[1] + 0.60 * latent[2].sin() - 0.35 * latent[4] * latent[5]
                + 0.25 * latent[6],
            latent[2] * latent[3] + 0.60 * latent[4].sin() - 0.35 * latent[6] * latent[7]
                + 0.25 * latent[0],
            latent[4] * latent[5] + 0.60 * latent[6].sin() - 0.35 * latent[0] * latent[1]
                + 0.25 * latent[2],
        ];
        let target = scores
            .iter()
            .enumerate()
            .max_by(|left, right| left.1.total_cmp(right.1))
            .map_or(0, |(class, _)| class) as u32;
        Sample {
            x: observed,
            target,
        }
    })
}

struct NormalRng {
    state: u64,
    spare: Option<f64>,
}

impl NormalRng {
    fn new(seed: u64) -> Self {
        Self {
            state: seed,
            spare: None,
        }
    }

    fn uniform_open(&mut self) -> f64 {
        let mut value = self.state;
        value ^= value << 7;
        value ^= value >> 9;
        value ^= value << 8;
        self.state = value;
        ((value >> 11) as f64 + 0.5) / ((1_u64 << 53) as f64)
    }

    fn normal(&mut self) -> f64 {
        if let Some(spare) = self.spare.take() {
            return spare;
        }
        let radius = (-2.0 * self.uniform_open().ln()).sqrt();
        let angle = std::f64::consts::TAU * self.uniform_open();
        self.spare = Some(radius * angle.sin());
        radius * angle.cos()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_training_rows_have_frozen_shape_and_finite_values() {
        let samples = generate_dataset(0xa303_dada_0000_0001);
        assert_eq!(samples.len(), TRAIN_SAMPLES);
        assert!(samples.iter().all(|sample| {
            sample.target < CLASSES as u32 && sample.x.iter().all(|value| value.is_finite())
        }));
        assert_eq!(size_of::<Sample>(), 36);
    }

    #[test]
    fn model_gradient_matches_centered_finite_difference() {
        let sample = generate_dataset(0xa303_dada_0000_0001)[0];
        let model = Model::initial(0xa303_1a17_0000_0001);
        let (loss, gradient) = model.gradient_one(&sample);
        assert!(loss.is_finite());
        assert!(gradient.iter().all(|value| value.is_finite()));
        for &parameter in &[0_usize, 71, 103, 168, PARAMS - 1] {
            let epsilon = 1.0e-3;
            let mut plus = model;
            let mut minus = model;
            plus.parameters[parameter] += epsilon;
            minus.parameters[parameter] -= epsilon;
            let numeric = (plus.loss_one(&sample) - minus.loss_one(&sample)) / (2.0 * epsilon);
            assert!((numeric - gradient[parameter]).abs() < 2.0e-3);
        }
    }
}
