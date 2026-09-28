use std::hint::black_box;

use crate::model::{CLASSES, HIDDEN_1, HIDDEN_2, Model, PARAMS, Sample};

pub const PROJECTION_DIMENSIONS: usize = 32;
pub const PROJECTION_SEED: u64 = 0xa303_4252_0000_0001;
const W2: usize = 72;
const W3: usize = W2 + HIDDEN_1 * HIDDEN_2 + HIDDEN_2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Proxy {
    FullGradient,
    OutputLayer,
    LastHiddenLayer,
    RandomProjection,
    SignGradient,
}

impl Proxy {
    pub const ALL: [Self; 5] = [
        Self::FullGradient,
        Self::OutputLayer,
        Self::LastHiddenLayer,
        Self::RandomProjection,
        Self::SignGradient,
    ];

    pub const fn name(self) -> &'static str {
        match self {
            Self::FullGradient => "full_gradient_171",
            Self::OutputLayer => "output_layer_27",
            Self::LastHiddenLayer => "last_hidden_layer_72",
            Self::RandomProjection => "rademacher_projection_32",
            Self::SignGradient => "sign_gradient_171",
        }
    }

    pub const fn dimensions(self) -> usize {
        match self {
            Self::FullGradient | Self::SignGradient => PARAMS,
            Self::OutputLayer => PARAMS - W3,
            Self::LastHiddenLayer => HIDDEN_1 * HIDDEN_2 + HIDDEN_2,
            Self::RandomProjection => PROJECTION_DIMENSIONS,
        }
    }
}

#[derive(Clone, Debug)]
pub struct Projection {
    coefficients: Vec<f32>,
}

impl Projection {
    pub fn frozen() -> Self {
        let scale = 1.0_f32 / (PROJECTION_DIMENSIONS as f32).sqrt();
        let coefficients = (0..PARAMS * PROJECTION_DIMENSIONS)
            .map(|index| {
                let sign = mix64(PROJECTION_SEED ^ index as u64) & 1;
                if sign == 0 { scale } else { -scale }
            })
            .collect();
        Self { coefficients }
    }

    fn project(&self, gradient: &[f32; PARAMS]) -> Vec<f64> {
        let mut output = vec![0.0_f64; PROJECTION_DIMENSIONS];
        for (input, &value) in gradient.iter().enumerate() {
            let row = &self.coefficients
                [input * PROJECTION_DIMENSIONS..(input + 1) * PROJECTION_DIMENSIONS];
            for (target, coefficient) in output.iter_mut().zip(row) {
                *target += f64::from(value * coefficient);
            }
        }
        output
    }
}

pub fn acquire(
    proxy: Proxy,
    model: &Model,
    samples: &[Sample],
    projection: &Projection,
) -> Vec<Vec<f64>> {
    match proxy {
        Proxy::FullGradient => samples
            .iter()
            .map(|sample| {
                model
                    .gradient_one(sample)
                    .1
                    .iter()
                    .map(|value| f64::from(*value))
                    .collect()
            })
            .collect(),
        Proxy::OutputLayer => samples
            .iter()
            .map(|sample| output_layer_gradient(model, sample))
            .collect(),
        Proxy::LastHiddenLayer => samples
            .iter()
            .map(|sample| last_hidden_layer_gradient(model, sample))
            .collect(),
        Proxy::RandomProjection => samples
            .iter()
            .map(|sample| projection.project(&model.gradient_one(sample).1))
            .collect(),
        Proxy::SignGradient => samples
            .iter()
            .map(|sample| {
                model
                    .gradient_one(sample)
                    .1
                    .iter()
                    .map(|value| f64::from(value.signum()))
                    .collect()
            })
            .collect(),
    }
}

pub fn measure_acquisition_ns(
    proxy: Proxy,
    model: &Model,
    samples: &[Sample],
    projection: &Projection,
    repetitions: usize,
) -> u128 {
    assert!(repetitions > 0);
    let mut durations = Vec::with_capacity(repetitions);
    for _ in 0..repetitions {
        let started = std::time::Instant::now();
        let features = acquire(proxy, model, samples, projection);
        black_box(&features);
        durations.push(started.elapsed().as_nanos());
    }
    durations.sort_unstable();
    durations[durations.len() / 2]
}

fn output_layer_gradient(model: &Model, sample: &Sample) -> Vec<f64> {
    let (logits, _, hidden_2) = model.logits(sample);
    let output_error = softmax_error(&logits, sample.target as usize);
    let mut gradient = Vec::with_capacity(PARAMS - W3);
    for error in output_error.iter().copied() {
        for &activation in hidden_2.iter() {
            gradient.push(f64::from(error * activation));
        }
    }
    gradient.extend(output_error.iter().map(|value| f64::from(*value)));
    gradient
}

fn last_hidden_layer_gradient(model: &Model, sample: &Sample) -> Vec<f64> {
    let (logits, hidden_1, hidden_2) = model.logits(sample);
    let output_error = softmax_error(&logits, sample.target as usize);
    let mut hidden_2_error = [0.0_f32; HIDDEN_2];
    for (class, error) in output_error.iter().copied().enumerate() {
        let output_offset = W3 + class * HIDDEN_2;
        for (input, hidden_error) in hidden_2_error.iter_mut().enumerate() {
            *hidden_error += error * model.parameters[output_offset + input];
        }
    }
    let mut gradient = Vec::with_capacity(HIDDEN_1 * HIDDEN_2 + HIDDEN_2);
    let mut bias_gradient = [0.0_f32; HIDDEN_2];
    for unit in 0..HIDDEN_2 {
        let error = if hidden_2[unit] > 0.0 {
            hidden_2_error[unit]
        } else {
            0.0
        };
        bias_gradient[unit] = error;
        for &activation in hidden_1.iter() {
            gradient.push(f64::from(error * activation));
        }
    }
    gradient.extend(bias_gradient.iter().map(|value| f64::from(*value)));
    gradient
}

fn softmax_error(logits: &[f32; CLASSES], target: usize) -> [f32; CLASSES] {
    let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let exponential_sum = logits
        .iter()
        .map(|value| (*value - maximum).exp())
        .sum::<f32>();
    let mut error = std::array::from_fn(|class| (logits[class] - maximum).exp() / exponential_sum);
    error[target] -= 1.0;
    error
}

fn mix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::Model;

    #[test]
    fn direct_layer_features_match_slices_of_full_gradient() {
        let samples = crate::model::generate_dataset(0xa303_dada_0000_0001);
        let model = Model::initial(0xa303_1a17_0000_0001);
        for sample in samples.iter().take(12) {
            let full = model.gradient_one(sample).1;
            let output = output_layer_gradient(&model, sample);
            let hidden = last_hidden_layer_gradient(&model, sample);
            assert_eq!(output.len(), 27);
            assert_eq!(hidden.len(), 72);
            for (actual, expected) in output.iter().zip(&full[W3..]) {
                assert_eq!(*actual, f64::from(*expected));
            }
            for (actual, expected) in hidden.iter().zip(&full[W2..W3]) {
                assert_eq!(*actual, f64::from(*expected));
            }
        }
    }

    #[test]
    fn fixed_projection_and_sign_features_are_deterministic() {
        let sample = crate::model::generate_dataset(0xa303_dada_0000_0001)[0];
        let model = Model::initial(0xa303_1a17_0000_0001);
        let projection = Projection::frozen();
        assert_eq!(projection.coefficients, Projection::frozen().coefficients);
        let gradient = model.gradient_one(&sample).1;
        let projected = projection.project(&gradient);
        let signed: Vec<_> = gradient
            .iter()
            .map(|value| f64::from(value.signum()))
            .collect();
        assert_eq!(projected.len(), 32);
        assert_eq!(signed.len(), PARAMS);
        assert!(projected.iter().all(|value| value.is_finite()));
        assert!(signed.iter().all(|value| [-1.0, 0.0, 1.0].contains(value)));
    }
}
