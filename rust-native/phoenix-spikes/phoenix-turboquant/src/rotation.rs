use crate::{Result, TurboQuantError};

pub const ROTATION_CONTRACT: &[u8] = b"phoenix/permute-sign-block-hadamard/2-rounds/splitmix64-v1";
const ROUND_COUNT: usize = 2;
const ROTATION_SEED: u64 = 0x7A11_5EED_D15C_A11E;

/// Deterministic orthogonal mixing transform with no dense matrix.
#[derive(Clone, Debug)]
pub struct Rotation {
    dimension: usize,
    block: usize,
    permutations: [Box<[u32]>; ROUND_COUNT],
    signs: [Box<[f32]>; ROUND_COUNT],
    inv_sqrt_block: f32,
}

impl Rotation {
    pub fn new(dimension: usize) -> Result<Self> {
        if dimension == 0 || !dimension.is_multiple_of(8) || dimension > u32::MAX as usize {
            return Err(TurboQuantError::InvalidDimension(dimension));
        }
        let block = 1usize << dimension.trailing_zeros();
        let mut random = SplitMix64::new(ROTATION_SEED ^ dimension as u64);
        let mut permutations = Vec::with_capacity(ROUND_COUNT);
        let mut signs = Vec::with_capacity(ROUND_COUNT);
        for _ in 0..ROUND_COUNT {
            let mut permutation = (0..dimension as u32).collect::<Vec<_>>();
            for index in (1..dimension).rev() {
                let selected = random.bounded(index + 1);
                permutation.swap(index, selected);
            }
            let sign_row = (0..dimension)
                .map(|_| {
                    if random.next_u64() & 1 == 0 {
                        -1.0
                    } else {
                        1.0
                    }
                })
                .collect::<Vec<_>>();
            permutations.push(permutation.into_boxed_slice());
            signs.push(sign_row.into_boxed_slice());
        }
        Ok(Self {
            dimension,
            block,
            permutations: [permutations.remove(0), permutations.remove(0)],
            signs: [signs.remove(0), signs.remove(0)],
            inv_sqrt_block: 1.0 / (block as f32).sqrt(),
        })
    }

    pub fn dimension(&self) -> usize {
        self.dimension
    }

    pub fn block(&self) -> usize {
        self.block
    }

    pub fn contract_hash(&self) -> [u8; 32] {
        let mut hasher = blake3::Hasher::new();
        hasher.update(ROTATION_CONTRACT);
        hasher.update(&(self.dimension as u64).to_le_bytes());
        hasher.update(&(self.block as u64).to_le_bytes());
        for round in 0..ROUND_COUNT {
            hasher.update(bytemuck::cast_slice(&self.permutations[round]));
            hasher.update(bytemuck::cast_slice(&self.signs[round]));
        }
        *hasher.finalize().as_bytes()
    }

    pub fn apply(&self, row: &mut [f32], scratch: &mut [f32]) {
        assert_eq!(row.len(), self.dimension);
        assert_eq!(scratch.len(), self.dimension);
        gather_signed(row, &self.permutations[0], &self.signs[0], scratch);
        self.hadamard_blocks(scratch);
        gather_signed(scratch, &self.permutations[1], &self.signs[1], row);
        self.hadamard_blocks(row);
    }

    fn hadamard_blocks(&self, row: &mut [f32]) {
        for block in row.chunks_exact_mut(self.block) {
            let mut width = 1;
            while width < self.block {
                for base in (0..self.block).step_by(width * 2) {
                    for lane in 0..width {
                        let left = block[base + lane];
                        let right = block[base + width + lane];
                        block[base + lane] = left + right;
                        block[base + width + lane] = left - right;
                    }
                }
                width *= 2;
            }
            for value in block {
                *value *= self.inv_sqrt_block;
            }
        }
    }
}

fn gather_signed(source: &[f32], permutation: &[u32], signs: &[f32], destination: &mut [f32]) {
    for ((output, &input), &sign) in destination.iter_mut().zip(permutation).zip(signs) {
        *output = source[input as usize] * sign;
    }
}

#[derive(Clone, Copy, Debug)]
struct SplitMix64 {
    state: u64,
}

impl SplitMix64 {
    const fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        value ^ (value >> 31)
    }

    fn bounded(&mut self, upper: usize) -> usize {
        ((self.next_u64() as u128 * upper as u128) >> 64) as usize
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rotation_preserves_norm_and_is_deterministic() {
        let rotation = Rotation::new(768).unwrap();
        assert_eq!(rotation.block(), 256);
        let mut first = (0..768)
            .map(|index| ((index * 37 % 101) as f32 - 50.0) / 50.0)
            .collect::<Vec<_>>();
        let expected = first.iter().map(|value| value * value).sum::<f32>();
        let mut second = first.clone();
        let mut scratch = vec![0.0; 768];
        rotation.apply(&mut first, &mut scratch);
        rotation.apply(&mut second, &mut scratch);
        let actual = first.iter().map(|value| value * value).sum::<f32>();
        assert_eq!(first, second);
        assert!((actual - expected).abs() / expected < 2e-5);
    }
}
