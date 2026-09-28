use crate::model::{Model, PARAMS, Sample};

pub fn per_example_gradients(model: &Model, samples: &[Sample]) -> Vec<[f32; PARAMS]> {
    samples
        .iter()
        .map(|sample| model.gradient_one(sample).1)
        .collect()
}

pub fn gradient_features(gradients: &[[f32; PARAMS]]) -> Vec<Vec<f64>> {
    gradients
        .iter()
        .map(|gradient| gradient.iter().map(|value| f64::from(*value)).collect())
        .collect()
}
