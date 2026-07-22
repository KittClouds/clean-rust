use crate::GalaxyGpuError;

const RADIX_BITS: u32 = 11;
const RADIX: usize = 1 << RADIX_BITS;
const RADIX_MASK: u64 = (RADIX as u64) - 1;

/// Reusable stable LSD radix workspace for `(Morton key, stable node identity)`.
///
/// Initial node order is ascending, so stable passes make the node identity the
/// exact tie-breaker without moving a second key alongside every record.
pub struct MortonRadixScratch {
    order: Vec<u32>,
    spare: Vec<u32>,
    counts: Vec<u32>,
}

impl Default for MortonRadixScratch {
    fn default() -> Self {
        Self::new()
    }
}

impl MortonRadixScratch {
    pub fn new() -> Self {
        Self {
            order: Vec::new(),
            spare: Vec::new(),
            counts: vec![0; RADIX],
        }
    }

    pub fn sort(&mut self, keys: &[u64]) -> Result<&[u32], GalaxyGpuError> {
        let nodes = u32::try_from(keys.len()).map_err(|_| {
            GalaxyGpuError::Input("Morton key count exceeds u32 identity space".to_owned())
        })?;
        self.order.resize(keys.len(), 0);
        self.spare.resize(keys.len(), 0);
        for (node, slot) in (0..nodes).zip(&mut self.order) {
            *slot = node;
        }

        for shift in (0..64).step_by(RADIX_BITS as usize) {
            self.counts.fill(0);
            for &node in &self.order {
                let digit = digit(keys[node as usize], shift as u32);
                self.counts[digit] += 1;
            }
            let mut prefix = 0u32;
            for count in &mut self.counts {
                let bucket_count = *count;
                *count = prefix;
                prefix += bucket_count;
            }
            for &node in &self.order {
                let digit = digit(keys[node as usize], shift as u32);
                let destination = self.counts[digit] as usize;
                self.spare[destination] = node;
                self.counts[digit] += 1;
            }
            std::mem::swap(&mut self.order, &mut self.spare);
        }
        Ok(&self.order)
    }

    pub fn resident_bytes(&self) -> usize {
        (self.order.capacity() + self.spare.capacity()) * size_of::<u32>()
            + self.counts.capacity() * size_of::<u32>()
    }
}

#[inline]
fn digit(key: u64, shift: u32) -> usize {
    ((key >> shift) & RADIX_MASK) as usize
}
