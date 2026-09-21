use adaptive_runtime_ar_02a_r2::{CLASSES, HIDDEN_1, HIDDEN_2, Model, PARAMS, Sample};

pub fn input_features(samples: &[Sample]) -> Vec<Vec<f64>> {
    standardize(vec![
        samples.iter().map(|sample| f64::from(sample.x0)).collect(),
        samples.iter().map(|sample| f64::from(sample.x1)).collect(),
    ])
}

pub fn current_state_features(model: &Model, samples: &[Sample]) -> Vec<Vec<f64>> {
    let mut rows = Vec::with_capacity(samples.len());
    for &sample in samples {
        let logits = logits(model, sample);
        let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        let normalizer = logits
            .iter()
            .map(|value| (*value - maximum).exp())
            .sum::<f32>();
        let probabilities = std::array::from_fn::<_, CLASSES, _>(|class| {
            (logits[class] - maximum).exp() / normalizer
        });
        let loss = normalizer.ln() + maximum - logits[sample.target as usize];
        let best_other = logits
            .iter()
            .enumerate()
            .filter(|(class, _)| *class != sample.target as usize)
            .map(|(_, value)| *value)
            .fold(f32::NEG_INFINITY, f32::max);
        let margin = logits[sample.target as usize] - best_other;
        let entropy = probabilities
            .iter()
            .map(|probability| {
                if *probability > 0.0 {
                    -*probability * probability.ln()
                } else {
                    0.0
                }
            })
            .sum::<f32>();
        rows.push(vec![f64::from(loss), f64::from(margin), f64::from(entropy)]);
    }
    standardize_rows(rows)
}

pub fn per_example_gradients(model: &Model, samples: &[Sample]) -> Vec<[f32; PARAMS]> {
    samples
        .iter()
        .map(|sample| model.gradient(std::slice::from_ref(sample)).1)
        .collect()
}

pub fn gradient_features(gradients: &[[f32; PARAMS]]) -> Vec<Vec<f64>> {
    gradients
        .iter()
        .map(|gradient| gradient.iter().map(|value| f64::from(*value)).collect())
        .collect()
}

pub fn standardize_rows(mut rows: Vec<Vec<f64>>) -> Vec<Vec<f64>> {
    if rows.is_empty() {
        return rows;
    }
    let dimensions = rows[0].len();
    assert!(rows.iter().all(|row| row.len() == dimensions));
    for dimension in 0..dimensions {
        let mean = rows.iter().map(|row| row[dimension]).sum::<f64>() / rows.len() as f64;
        let variance = rows
            .iter()
            .map(|row| {
                let difference = row[dimension] - mean;
                difference * difference
            })
            .sum::<f64>()
            / rows.len() as f64;
        let standard_deviation = variance.sqrt();
        let scale = if standard_deviation > 1.0e-12 {
            standard_deviation
        } else {
            1.0
        };
        for row in &mut rows {
            row[dimension] = (row[dimension] - mean) / scale;
        }
    }
    rows
}

fn standardize(columns: Vec<Vec<f64>>) -> Vec<Vec<f64>> {
    let row_count = columns.first().map_or(0, Vec::len);
    assert!(columns.iter().all(|column| column.len() == row_count));
    let mut rows = vec![vec![0.0; columns.len()]; row_count];
    for (dimension, column) in columns.iter().enumerate() {
        for (row, value) in column.iter().enumerate() {
            rows[row][dimension] = *value;
        }
    }
    standardize_rows(rows)
}

fn logits(model: &Model, sample: Sample) -> [f32; CLASSES] {
    const W1: usize = 0;
    const B1: usize = W1 + 2 * HIDDEN_1;
    const W2: usize = B1 + HIDDEN_1;
    const B2: usize = W2 + HIDDEN_1 * HIDDEN_2;
    const W3: usize = B2 + HIDDEN_2;
    const B3: usize = W3 + HIDDEN_2 * CLASSES;

    let mut hidden_1 = [0.0_f32; HIDDEN_1];
    for (unit, value) in hidden_1.iter_mut().enumerate() {
        let offset = W1 + unit * 2;
        *value = (model.parameters[offset] * sample.x0
            + model.parameters[offset + 1] * sample.x1
            + model.parameters[B1 + unit])
            .max(0.0);
    }
    let mut hidden_2 = [0.0_f32; HIDDEN_2];
    for (unit, value) in hidden_2.iter_mut().enumerate() {
        let offset = W2 + unit * HIDDEN_1;
        let mut pre_activation = model.parameters[B2 + unit];
        for (input, &activation) in hidden_1.iter().enumerate() {
            pre_activation += model.parameters[offset + input] * activation;
        }
        *value = pre_activation.max(0.0);
    }
    let mut logits = [0.0_f32; CLASSES];
    for (class, logit) in logits.iter_mut().enumerate() {
        let offset = W3 + class * HIDDEN_2;
        *logit = model.parameters[B3 + class];
        for (input, &activation) in hidden_2.iter().enumerate() {
            *logit += model.parameters[offset + input] * activation;
        }
    }
    logits
}

#[cfg(test)]
mod tests {
    use super::*;
    use adaptive_runtime_ar_02a_r2::{TRAIN_SAMPLES, generate_gaussian_cells};

    #[test]
    fn state_features_and_gradients_are_finite_and_per_example() {
        let dataset = generate_gaussian_cells();
        let train = &dataset.samples[..TRAIN_SAMPLES];
        let model = Model::initial();
        let features = current_state_features(&model, train);
        let gradients = per_example_gradients(&model, train);
        assert_eq!(features.len(), TRAIN_SAMPLES);
        assert_eq!(features[0].len(), 3);
        assert_eq!(gradients.len(), TRAIN_SAMPLES);
        assert!(features.iter().flatten().all(|value| value.is_finite()));
        assert!(gradients.iter().flatten().all(|value| value.is_finite()));
    }
}
