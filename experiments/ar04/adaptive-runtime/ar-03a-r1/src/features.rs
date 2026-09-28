use crate::model::{CLASSES, Model, PARAMS, Sample};

pub fn input_features(samples: &[Sample]) -> Vec<Vec<f64>> {
    let mut rows = vec![vec![0.0; crate::model::INPUTS]; samples.len()];
    for (sample_index, sample) in samples.iter().enumerate() {
        for (coordinate, &value) in sample.x.iter().enumerate() {
            rows[sample_index][coordinate] = f64::from(value);
        }
    }
    standardize_rows(rows)
}

pub fn current_state_features(model: &Model, samples: &[Sample]) -> Vec<Vec<f64>> {
    let mut rows = Vec::with_capacity(samples.len());
    for sample in samples {
        let logits = model.logits(sample).0;
        let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        let exponential_sum = logits
            .iter()
            .map(|value| (*value - maximum).exp())
            .sum::<f32>();
        let probabilities = std::array::from_fn::<_, CLASSES, _>(|class| {
            (logits[class] - maximum).exp() / exponential_sum
        });
        let loss = maximum + exponential_sum.ln() - logits[sample.target as usize];
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
        .map(|sample| model.gradient_one(sample).1)
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
