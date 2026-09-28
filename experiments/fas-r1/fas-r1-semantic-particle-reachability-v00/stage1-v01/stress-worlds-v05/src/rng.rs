use crate::StressError;

pub(crate) fn parse_hex_u64(value: &str) -> Result<u64, StressError> {
    let digits = value
        .strip_prefix("0x")
        .ok_or_else(|| StressError("seed values must use 0x-prefixed hexadecimal".into()))?;
    u64::from_str_radix(digits, 16)
        .map_err(|error| StressError(format!("invalid hex seed {value}: {error}")))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct SplitMix64(u64);

impl SplitMix64 {
    pub(crate) fn new(seed: u64) -> Self {
        Self(seed)
    }

    pub(crate) fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }

    pub(crate) fn bounded(&mut self, bound: u64) -> u64 {
        assert!(bound > 0, "bounded RNG requires a nonzero bound");
        let threshold = bound.wrapping_neg() % bound;
        loop {
            let value = self.next_u64();
            if value >= threshold {
                return value % bound;
            }
        }
    }

    pub(crate) fn shuffle<T>(&mut self, values: &mut [T]) {
        for end in (1..values.len()).rev() {
            let index = (self.next_u64() as usize) % (end + 1);
            values.swap(end, index);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::SplitMix64;

    #[test]
    fn bounded_sampling_is_repeatable_and_stays_in_range() {
        let mut left = SplitMix64::new(0x5249_5354_4152_5435);
        let mut right = SplitMix64::new(0x5249_5354_4152_5435);
        for _ in 0..2048 {
            let sample = left.bounded(3);
            assert!(sample < 3);
            assert_eq!(sample, right.bounded(3));
        }
    }
}
