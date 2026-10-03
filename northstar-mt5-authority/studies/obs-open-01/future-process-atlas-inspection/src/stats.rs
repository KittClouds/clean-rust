use std::collections::BTreeMap;
use wide::f64x4;

pub fn weights(values: &[(f64, u32)], sampling: &str) -> Vec<f64> {
    if values.is_empty() {
        return Vec::new();
    }
    if sampling == "ANCHOR_WEIGHTED" {
        return vec![1.0 / values.len() as f64; values.len()];
    }
    let mut counts = BTreeMap::<u32, usize>::new();
    for &(_, session) in values {
        *counts.entry(session).or_default() += 1;
    }
    let session_mass = 1.0 / counts.len() as f64;
    values
        .iter()
        .map(|(_, session)| session_mass / counts[session] as f64)
        .collect()
}

pub fn weighted_quantile(values: &[(f64, u32)], weights: &[f64], p: f64) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    let mut order: Vec<usize> = (0..values.len()).collect();
    order.sort_unstable_by(|&a, &b| {
        values[a]
            .0
            .total_cmp(&values[b].0)
            .then_with(|| values[a].1.cmp(&values[b].1))
    });
    let target = p.clamp(0.0, 1.0) * weights.iter().sum::<f64>();
    let mut cumulative = 0.0;
    for index in order {
        cumulative += weights[index];
        if cumulative >= target {
            return Some(values[index].0);
        }
    }
    values
        .iter()
        .max_by(|a, b| a.0.total_cmp(&b.0))
        .map(|x| x.0)
}

pub fn weighted_mean(values: &[(f64, u32)], weights: &[f64]) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    let mut accum = f64x4::splat(0.0);
    let mut weight_accum = f64x4::splat(0.0);
    let chunks = values.len() / 4;
    for index in 0..chunks {
        let offset = index * 4;
        let value = f64x4::new([
            values[offset].0,
            values[offset + 1].0,
            values[offset + 2].0,
            values[offset + 3].0,
        ]);
        let weight = f64x4::new([
            weights[offset],
            weights[offset + 1],
            weights[offset + 2],
            weights[offset + 3],
        ]);
        accum += value * weight;
        weight_accum += weight;
    }
    let mut numerator = accum.reduce_add();
    let mut denominator = weight_accum.reduce_add();
    for index in chunks * 4..values.len() {
        numerator += values[index].0 * weights[index];
        denominator += weights[index];
    }
    (denominator > 0.0).then_some(numerator / denominator)
}

pub fn type7_quantile(values: &[usize], p: f64) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let x = (sorted.len() - 1) as f64 * p;
    let lower = x.floor() as usize;
    let upper = x.ceil() as usize;
    let fraction = x - lower as f64;
    Some(sorted[lower] as f64 + fraction * (sorted[upper] - sorted[lower]) as f64)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sampling_units_do_not_alias() {
        let values = [(0.0, 0), (0.0, 0), (10.0, 1)];
        let anchor = weights(&values, "ANCHOR_WEIGHTED");
        let session = weights(&values, "SESSION_WEIGHTED");
        assert!((weighted_mean(&values, &anchor).expect("mean") - 10.0 / 3.0).abs() < 1e-12);
        assert!((weighted_mean(&values, &session).expect("mean") - 5.0).abs() < 1e-12);
    }
}
