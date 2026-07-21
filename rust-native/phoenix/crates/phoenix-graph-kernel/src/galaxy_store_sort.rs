use crate::GalaxyStoreError;

const RADIX_BITS: u32 = 11;
const RADIX: usize = 1 << RADIX_BITS;
const RADIX_MASK: u64 = (RADIX as u64) - 1;

pub(crate) struct MortonRadixScratch {
    order: Vec<u32>,
    spare: Vec<u32>,
    counts: Vec<u32>,
}

impl MortonRadixScratch {
    pub(crate) fn new() -> Self {
        Self {
            order: Vec::new(),
            spare: Vec::new(),
            counts: vec![0; RADIX],
        }
    }

    pub(crate) fn sort(&mut self, keys: &[u64]) -> Result<&[u32], GalaxyStoreError> {
        let nodes = u32::try_from(keys.len()).map_err(|_| {
            GalaxyStoreError::Invalid("Morton key count exceeds u32 identity space".to_owned())
        })?;
        self.order.resize(keys.len(), 0);
        self.spare.resize(keys.len(), 0);
        for (node, slot) in (0..nodes).zip(&mut self.order) {
            *slot = node;
        }
        for shift in (0..64).step_by(RADIX_BITS as usize) {
            self.counts.fill(0);
            for &node in &self.order {
                self.counts[digit(keys[node as usize], shift as u32)] += 1;
            }
            let mut prefix = 0u32;
            for count in &mut self.counts {
                let bucket_count = *count;
                *count = prefix;
                prefix += bucket_count;
            }
            for &node in &self.order {
                let bucket = digit(keys[node as usize], shift as u32);
                let destination = self.counts[bucket] as usize;
                self.spare[destination] = node;
                self.counts[bucket] += 1;
            }
            std::mem::swap(&mut self.order, &mut self.spare);
        }
        Ok(&self.order)
    }
}

#[inline]
fn digit(key: u64, shift: u32) -> usize {
    ((key >> shift) & RADIX_MASK) as usize
}

#[cfg(test)]
mod tests {
    use super::MortonRadixScratch;

    #[test]
    fn exactly_matches_key_then_node_comparison_order() {
        let mut state = 0xd1b5_4a32_d192_ed03u64;
        let keys = (0..131_071)
            .map(|node| {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                if node % 19 == 0 {
                    state & !0xff
                } else {
                    state
                }
            })
            .collect::<Vec<_>>();
        let mut expected = (0..keys.len() as u32).collect::<Vec<_>>();
        expected.sort_unstable_by_key(|node| (keys[*node as usize], *node));
        let mut scratch = MortonRadixScratch::new();
        assert_eq!(scratch.sort(&keys).unwrap(), expected);
    }

    #[test]
    fn duplicate_keys_keep_ascending_stable_identity() {
        let mut scratch = MortonRadixScratch::new();
        assert_eq!(scratch.sort(&[9, 1, 9, 1, 9]).unwrap(), [1, 3, 0, 2, 4]);
    }
}
