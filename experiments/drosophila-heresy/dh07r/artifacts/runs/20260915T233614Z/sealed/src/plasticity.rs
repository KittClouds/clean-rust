use wide::f32x8;

/// Only local eligibility, current weight, and the delivered modulator enter.
/// `step` includes eta and an exact lazy exponential eligibility-decay scale.
pub fn reinforce(weights: &mut [f32], eligibility: &[f32], step: f32) {
    assert_eq!(weights.len(), eligibility.len());
    let n = weights.len() / 8 * 8;
    let factor = f32x8::splat(step);
    let zero = f32x8::splat(0.0);
    let cap = f32x8::splat(2.0);
    for (w, e) in weights[..n]
        .chunks_exact_mut(8)
        .zip(eligibility[..n].chunks_exact(8))
    {
        let a = f32x8::from(<[f32; 8]>::try_from(&*w).unwrap());
        let b = f32x8::from(<[f32; 8]>::try_from(e).unwrap());
        w.copy_from_slice(&(a + b * factor).max(zero).min(cap).to_array());
    }
    for (w, e) in weights[n..].iter_mut().zip(&eligibility[n..]) {
        *w = (*w + step * e).clamp(0.0, 2.0);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn simd_matches_scalar_including_tail_and_bounds() {
        let mut w: Vec<_> = (0..39).map(|x| x as f32 / 20.0).collect();
        let e: Vec<_> = (0..39).map(|x| (x as f32 - 20.0) * 0.1).collect();
        let expected: Vec<_> = w
            .iter()
            .zip(&e)
            .map(|(a, b)| (a + 0.13 * b).clamp(0.0, 2.0))
            .collect();
        reinforce(&mut w, &e, 0.13);
        for (a, b) in w.iter().zip(expected) {
            assert!((a - b).abs() < 1e-6);
        }
    }
    #[test]
    fn no_modulation_or_no_eligibility_cannot_change_weights() {
        let base = vec![0.25; 19];
        let mut w = base.clone();
        reinforce(&mut w, &[1.0; 19], 0.0);
        assert_eq!(w, base);
        reinforce(&mut w, &[0.0; 19], 9.0);
        assert_eq!(w, base);
    }
    #[test]
    fn lazy_trace_equals_explicit_decay() {
        for tau in [4.0_f32, 16.0] {
            for delay in [4, 12] {
                let lambda = (-1.0 / tau).exp();
                let mut actual = 0.0;
                let mut stored = 0.0;
                let mut scale = 1.0;
                for event in 0..=delay {
                    let value = if event % 3 == 0 { 0.7 } else { -0.2 };
                    actual = lambda * actual + value;
                    scale *= lambda;
                    stored += value / scale;
                }
                assert!((actual - stored * scale).abs() < 2e-6);
            }
        }
    }
}
