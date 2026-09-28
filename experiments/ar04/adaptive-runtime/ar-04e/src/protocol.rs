use crate::model::{Sample, TRAIN_SAMPLES};

pub const DATASET_COUNT: usize = 5;
pub const INITIALIZATION_COUNT: usize = 5;
pub const CELL_COUNT: usize = DATASET_COUNT * INITIALIZATION_COUNT;
pub const RUNTIME_STEPS: usize = 4_200;
pub const BASE_PANEL_SIZE: usize = 128;
pub const BASE_INTERVAL: usize = 4;
pub const BASE_ROUNDS: usize = RUNTIME_STEPS.div_ceil(BASE_INTERVAL);
pub const V512_INTERVAL: usize = 16;
pub const V512_ROUNDS: usize = RUNTIME_STEPS.div_ceil(V512_INTERVAL);
pub const V2048_INTERVAL: usize = 64;
pub const V2048_ROUNDS: usize = RUNTIME_STEPS.div_ceil(V2048_INTERVAL);
pub const MAX_BASE_PANELS: usize = BASE_ROUNDS * 16;
pub const POPULATION_SIZE: usize = 4_096;
pub const POPULATION_CHUNKS: usize = POPULATION_SIZE.div_ceil(TRAIN_SAMPLES);
pub const CHECKPOINTS: [usize; 4] = [0, 600, 2_400, RUNTIME_STEPS];

const TRAINING_PREFIX: u64 = 0xa405_e401_0000_0000;
const MEASUREMENT_PREFIX: u64 = 0xa405_e402_0000_0000;
const INITIALIZATION_PREFIX: u64 = 0xa405_e403_0000_0000;
const STREAM_PREFIX: u64 = 0xa405_e404_0000_0000;
const PANEL_DRAW_PREFIX: u64 = 0xa405_e405_0000_0000;
const PANEL_ORDER_PREFIX: u64 = 0xa405_e406_0000_0000;
const POPULATION_PREFIX: u64 = 0xa405_e407_0000_0000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Arm {
    FixedV128,
    FreshV128,
    FixedV512,
    FreshV512,
    FixedV2048,
    FreshV2048,
    FreshV512Cadence,
    FreshV2048Cadence,
}

impl Arm {
    pub const ALL: [Self; 8] = [
        Self::FixedV128,
        Self::FreshV128,
        Self::FixedV512,
        Self::FreshV512,
        Self::FixedV2048,
        Self::FreshV2048,
        Self::FreshV512Cadence,
        Self::FreshV2048Cadence,
    ];

    pub const fn name(self) -> &'static str {
        match self {
            Self::FixedV128 => "fixed_v128",
            Self::FreshV128 => "fresh_v128",
            Self::FixedV512 => "fixed_v512",
            Self::FreshV512 => "fresh_v512",
            Self::FixedV2048 => "fixed_v2048",
            Self::FreshV2048 => "fresh_v2048",
            Self::FreshV512Cadence => "fresh_v512_cadence16",
            Self::FreshV2048Cadence => "fresh_v2048_cadence64",
        }
    }

    pub const fn panel_size(self) -> usize {
        match self {
            Self::FixedV128 | Self::FreshV128 => 128,
            Self::FixedV512 | Self::FreshV512 | Self::FreshV512Cadence => 512,
            Self::FixedV2048 | Self::FreshV2048 | Self::FreshV2048Cadence => 2_048,
        }
    }

    pub const fn interval(self) -> usize {
        match self {
            Self::FreshV512Cadence => V512_INTERVAL,
            Self::FreshV2048Cadence => V2048_INTERVAL,
            _ => BASE_INTERVAL,
        }
    }

    pub const fn rounds(self) -> usize {
        match self {
            Self::FreshV512Cadence => V512_ROUNDS,
            Self::FreshV2048Cadence => V2048_ROUNDS,
            _ => BASE_ROUNDS,
        }
    }

    pub const fn support_size(self, evidence_round: usize) -> usize {
        match self {
            Self::FixedV128 | Self::FixedV512 | Self::FixedV2048 => self.panel_size(),
            _ => (evidence_round + 1) * self.panel_size(),
        }
    }

    pub const fn base_first(self, evidence_round: usize) -> usize {
        let width = self.panel_size() / BASE_PANEL_SIZE;
        if self.is_fixed() {
            0
        } else {
            evidence_round * width
        }
    }

    pub const fn is_fixed(self) -> bool {
        matches!(self, Self::FixedV128 | Self::FixedV512 | Self::FixedV2048)
    }
}

pub const fn seed(prefix: u64, one_based_index: usize) -> u64 {
    prefix | one_based_index as u64
}

pub const fn training_seed(dataset_id: usize) -> u64 {
    seed(TRAINING_PREFIX, dataset_id + 1)
}

pub const fn measurement_seed(dataset_id: usize) -> u64 {
    seed(MEASUREMENT_PREFIX, dataset_id + 1)
}

pub const fn initialization_seed(initialization_id: usize) -> u64 {
    seed(INITIALIZATION_PREFIX, initialization_id + 1)
}

pub const fn stream_seed(cell_id: usize) -> u64 {
    seed(STREAM_PREFIX, cell_id + 1)
}

pub const fn panel_global_index(cell_id: usize, panel_id: usize) -> usize {
    cell_id * MAX_BASE_PANELS + panel_id
}

pub const fn panel_draw_seed(cell_id: usize, panel_id: usize, draw_id: usize) -> u64 {
    seed(
        PANEL_DRAW_PREFIX,
        panel_global_index(cell_id, panel_id) * 2 + draw_id + 1,
    )
}

pub const fn panel_order_seed(cell_id: usize, panel_id: usize) -> u64 {
    seed(
        PANEL_ORDER_PREFIX,
        panel_global_index(cell_id, panel_id) + 1,
    )
}

pub const fn population_seed(dataset_id: usize, chunk: usize) -> u64 {
    seed(
        POPULATION_PREFIX,
        dataset_id * POPULATION_CHUNKS + chunk + 1,
    )
}

pub fn all_role_seeds() -> Vec<u64> {
    let panel_count = CELL_COUNT * MAX_BASE_PANELS;
    let mut seeds = Vec::with_capacity(
        DATASET_COUNT * (2 + POPULATION_CHUNKS)
            + INITIALIZATION_COUNT
            + CELL_COUNT
            + panel_count * 3,
    );
    for dataset_id in 0..DATASET_COUNT {
        seeds.push(training_seed(dataset_id));
        seeds.push(measurement_seed(dataset_id));
        for chunk in 0..POPULATION_CHUNKS {
            seeds.push(population_seed(dataset_id, chunk));
        }
    }
    for initialization_id in 0..INITIALIZATION_COUNT {
        seeds.push(initialization_seed(initialization_id));
    }
    for cell_id in 0..CELL_COUNT {
        seeds.push(stream_seed(cell_id));
        for panel_id in 0..MAX_BASE_PANELS {
            seeds.push(panel_order_seed(cell_id, panel_id));
            seeds.push(panel_draw_seed(cell_id, panel_id, 0));
            seeds.push(panel_draw_seed(cell_id, panel_id, 1));
        }
    }
    seeds
}

pub fn seeds_are_unique_and_namespaced() -> bool {
    let seeds = all_role_seeds();
    let unique: hashbrown::HashSet<_> = seeds.iter().copied().collect();
    seeds.len() == unique.len()
        && seeds
            .iter()
            .all(|value| (0xa405_e401..=0xa405_e407).contains(&(value >> 32)))
}

pub fn panel_from_seeds(seed_a: u64, seed_b: u64, order_seed: u64) -> [Sample; BASE_PANEL_SIZE] {
    let first = generate_prefix(seed_a, 64);
    let second = generate_prefix(seed_b, 64);
    let mut source = [first[0]; BASE_PANEL_SIZE];
    source[..64].copy_from_slice(&first[..64]);
    source[64..].copy_from_slice(&second[..64]);
    let order = sample_order(order_seed);
    std::array::from_fn(|index| source[order[index]])
}

fn generate_prefix(seed: u64, count: usize) -> Vec<Sample> {
    let mut rng = NormalRng::new(seed);
    (0..count)
        .map(|_| {
            let latent = std::array::from_fn::<_, 8, _>(|_| rng.normal() as f32);
            let interaction = latent[0] * latent[1] + latent[2] * latent[3] - latent[4] * latent[5]
                + latent[6] * latent[7];
            let noise_scale = 0.04 + 0.18 / (1.0 + (-0.7 * interaction).exp());
            let mut observed = latent;
            for coordinate in 0..8 {
                observed[coordinate] = latent[coordinate] + noise_scale * rng.normal() as f32;
            }
            let scores = [
                latent[0] * latent[1] + 0.60 * latent[2].sin() - 0.35 * latent[4] * latent[5]
                    + 0.25 * latent[6],
                latent[2] * latent[3] + 0.60 * latent[4].sin() - 0.35 * latent[6] * latent[7]
                    + 0.25 * latent[0],
                latent[4] * latent[5] + 0.60 * latent[6].sin() - 0.35 * latent[0] * latent[1]
                    + 0.25 * latent[2],
            ];
            let target = scores
                .iter()
                .enumerate()
                .max_by(|left, right| left.1.total_cmp(right.1))
                .map_or(0, |(class, _)| class) as u32;
            Sample {
                x: observed,
                target,
            }
        })
        .collect()
}

struct NormalRng {
    state: u64,
    spare: Option<f64>,
}

impl NormalRng {
    fn new(state: u64) -> Self {
        Self { state, spare: None }
    }

    fn uniform_open(&mut self) -> f64 {
        let mut value = self.state;
        value ^= value << 7;
        value ^= value >> 9;
        value ^= value << 8;
        self.state = value;
        ((value >> 11) as f64 + 0.5) / ((1_u64 << 53) as f64)
    }

    fn normal(&mut self) -> f64 {
        if let Some(spare) = self.spare.take() {
            return spare;
        }
        let radius = (-2.0 * self.uniform_open().ln()).sqrt();
        let angle = std::f64::consts::TAU * self.uniform_open();
        self.spare = Some(radius * angle.sin());
        radius * angle.cos()
    }
}

pub fn sample_order(seed: u64) -> [usize; BASE_PANEL_SIZE] {
    let mut order = std::array::from_fn(|index| index);
    let mut state = seed;
    for index in (1..BASE_PANEL_SIZE).rev() {
        state = state.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let random = mix64(state);
        order.swap(index, random as usize % (index + 1));
    }
    order
}

pub const fn mix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

pub fn sample_fingerprint(samples: &[Sample]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for sample in samples {
        for value in sample
            .x
            .into_iter()
            .chain(std::iter::once(sample.target as f32))
        {
            hash = (hash ^ u64::from(value.to_bits())).wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    hash
}

pub fn indices_fingerprint(indices: &[usize]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for &index in indices {
        hash = (hash ^ index as u64).wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_cadence_counts_are_frozen() {
        assert_eq!(BASE_ROUNDS, 1_050);
        assert_eq!(V512_ROUNDS, 263);
        assert_eq!(V2048_ROUNDS, 66);
        assert_eq!(
            Arm::FreshV128.rounds() * Arm::FreshV128.panel_size(),
            134_400
        );
        assert_eq!(
            Arm::FreshV512Cadence.rounds() * Arm::FreshV512Cadence.panel_size(),
            134_656
        );
        assert_eq!(
            Arm::FreshV2048Cadence.rounds() * Arm::FreshV2048Cadence.panel_size(),
            135_168
        );
    }

    #[test]
    fn seed_roles_are_unique_and_namespaced() {
        assert!(seeds_are_unique_and_namespaced());
        assert_eq!(MAX_BASE_PANELS, 16_800);
    }

    #[test]
    fn panel_prefix_matches_frozen_dataset_generator() {
        let seed = 0xa405_e405_0000_0001;
        let expected = crate::model::generate_dataset(seed);
        let prefix = generate_prefix(seed, 64);
        for (actual, expected) in prefix.iter().zip(&expected[..64]) {
            assert_eq!(actual.target, expected.target);
            assert_eq!(actual.x, expected.x);
        }
    }

    #[test]
    fn every_arm_has_valid_width_and_interval() {
        for arm in Arm::ALL {
            assert!(arm.panel_size().is_multiple_of(BASE_PANEL_SIZE));
            assert!(arm.interval() > 0);
            assert!(arm.rounds() * arm.interval() >= RUNTIME_STEPS);
            assert!(arm.rounds() * arm.interval() - RUNTIME_STEPS < arm.interval());
        }
    }
}
