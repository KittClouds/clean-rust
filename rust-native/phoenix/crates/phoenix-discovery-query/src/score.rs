pub(crate) const SCORE_SCALE: u64 = 1_000_000;
const LOG_STEPS: usize = 24;

pub(crate) fn probability_log2_micros(probability_micros: u32) -> i64 {
    if probability_micros == 0 {
        return -60_000_000;
    }
    fixed_log2_micros(u64::from(probability_micros)) - fixed_log2_micros(SCORE_SCALE)
}

pub(crate) fn log2_lift_micros(signal_micros: u32) -> i64 {
    let signal = u64::from(signal_micros.min(1_000_000));
    fixed_log2_micros(SCORE_SCALE + signal) - fixed_log2_micros(SCORE_SCALE)
}

pub(crate) fn weighted(value: i64, weight_millis: u16) -> i64 {
    value.saturating_mul(i64::from(weight_millis)) / 1_000
}

pub(crate) fn confidence_micros(confidence: f32) -> u32 {
    if !confidence.is_finite() {
        return 1;
    }
    (confidence.clamp(0.000_001, 1.0) * SCORE_SCALE as f32).round() as u32
}

fn fixed_log2_micros(value: u64) -> i64 {
    debug_assert!(value > 0);
    let integer = 63 - value.leading_zeros() as i64;
    let mut normalized = (u128::from(value) << 63) >> integer;
    let mut fraction = 0_u64;
    for bit in 1..=LOG_STEPS {
        normalized = (normalized * normalized) >> 63;
        if normalized >= (2_u128 << 63) {
            normalized >>= 1;
            fraction |= 1_u64 << (LOG_STEPS - bit);
        }
    }
    integer * 1_000_000 + ((fraction * 1_000_000) >> LOG_STEPS) as i64
}

#[cfg(test)]
mod tests {
    use super::{log2_lift_micros, probability_log2_micros};

    #[test]
    fn fixed_log_is_deterministic_and_monotonic() {
        assert_eq!(probability_log2_micros(1_000_000), 0);
        assert!((probability_log2_micros(500_000) + 1_000_000).abs() < 2);
        assert!(probability_log2_micros(900_000) > probability_log2_micros(100_000));
        assert_eq!(log2_lift_micros(0), 0);
        assert!((log2_lift_micros(1_000_000) - 1_000_000).abs() < 2);
    }
}
