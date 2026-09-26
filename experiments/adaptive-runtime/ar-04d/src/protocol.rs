use crate::model::{Sample, TRAIN_SAMPLES};

pub const DATASET_COUNT: usize = 5;
pub const INITIALIZATION_COUNT: usize = 5;
pub const CELL_COUNT: usize = DATASET_COUNT * INITIALIZATION_COUNT;
pub const RUNTIME_STEPS: usize = 4_200;
pub const COMMITS_PER_EVIDENCE: usize = 4;
pub const EVIDENCE_ROUNDS: usize = RUNTIME_STEPS / COMMITS_PER_EVIDENCE;
pub const PANEL_SIZE: usize = 128;
pub const POOLED_PANEL_COUNT: usize = 16;
pub const POOLED_PANEL_SIZE: usize = POOLED_PANEL_COUNT * PANEL_SIZE;
pub const MASTER_PANEL_COUNT: usize = EVIDENCE_ROUNDS;
pub const POPULATION_SIZE: usize = 4_096;
pub const POPULATION_CHUNKS: usize = POPULATION_SIZE.div_ceil(TRAIN_SAMPLES);
pub const CHECKPOINTS: [usize; 4] = [0, 600, 2_400, RUNTIME_STEPS];

const TRAINING_PREFIX: u64 = 0xa404_d401_0000_0000;
const MEASUREMENT_PREFIX: u64 = 0xa404_d402_0000_0000;
const INITIALIZATION_PREFIX: u64 = 0xa404_d403_0000_0000;
const STREAM_PREFIX: u64 = 0xa404_d404_0000_0000;
const PANEL_DRAW_PREFIX: u64 = 0xa404_d405_0000_0000;
const PANEL_ORDER_PREFIX: u64 = 0xa404_d406_0000_0000;
const POPULATION_PREFIX: u64 = 0xa404_d407_0000_0000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Arm {
    SentinelK1,
    SentinelK4Cyclic,
    SentinelK16Cyclic,
    SentinelK16Blocked,
    SentinelK16Pooled,
    SentinelK64Cyclic,
    SentinelFresh,
}

impl Arm {
    pub const ALL: [Self; 7] = [
        Self::SentinelK1,
        Self::SentinelK4Cyclic,
        Self::SentinelK16Cyclic,
        Self::SentinelK16Blocked,
        Self::SentinelK16Pooled,
        Self::SentinelK64Cyclic,
        Self::SentinelFresh,
    ];

    pub const fn name(self) -> &'static str {
        match self {
            Self::SentinelK1 => "sentinel_k1",
            Self::SentinelK4Cyclic => "sentinel_k4_cyclic",
            Self::SentinelK16Cyclic => "sentinel_k16_cyclic",
            Self::SentinelK16Blocked => "sentinel_k16_blocked",
            Self::SentinelK16Pooled => "sentinel_k16_pooled",
            Self::SentinelK64Cyclic => "sentinel_k64_cyclic",
            Self::SentinelFresh => "sentinel_fresh",
        }
    }

    pub const fn panel_size(self) -> usize {
        match self {
            Self::SentinelK16Pooled => POOLED_PANEL_SIZE,
            _ => PANEL_SIZE,
        }
    }

    pub const fn bank_size(self) -> usize {
        match self {
            Self::SentinelK1 => 1,
            Self::SentinelK4Cyclic => 4,
            Self::SentinelK16Cyclic | Self::SentinelK16Blocked | Self::SentinelK16Pooled => 16,
            Self::SentinelK64Cyclic => 64,
            Self::SentinelFresh => MASTER_PANEL_COUNT,
        }
    }

    pub const fn support_size(self, evidence_round: usize) -> usize {
        match self {
            Self::SentinelK16Pooled => POOLED_PANEL_SIZE,
            Self::SentinelFresh => (evidence_round + 1) * PANEL_SIZE,
            _ => Self::bank_size(self) * PANEL_SIZE,
        }
    }

    pub const fn is_pooled(self) -> bool {
        matches!(self, Self::SentinelK16Pooled)
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
    cell_id * MASTER_PANEL_COUNT + panel_id
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

pub const fn panel_id_for_round(arm: Arm, evidence_round: usize) -> usize {
    match arm {
        Arm::SentinelK1 | Arm::SentinelK16Pooled => 0,
        Arm::SentinelK4Cyclic => evidence_round % 4,
        Arm::SentinelK16Cyclic => evidence_round % 16,
        Arm::SentinelK16Blocked => blocked_panel_id(evidence_round),
        Arm::SentinelK64Cyclic => evidence_round % 64,
        Arm::SentinelFresh => evidence_round,
    }
}

pub const fn blocked_panel_id(evidence_round: usize) -> usize {
    let first_ten = 10 * 66;
    if evidence_round < first_ten {
        evidence_round / 66
    } else {
        10 + (evidence_round - first_ten) / 65
    }
}

pub const fn cyclic_exposure_count(panel_id: usize, bank_size: usize) -> usize {
    let full_cycles = EVIDENCE_ROUNDS / bank_size;
    let remainder = EVIDENCE_ROUNDS % bank_size;
    full_cycles + if panel_id < remainder { 1 } else { 0 }
}

pub const fn blocked_exposure_count(panel_id: usize) -> usize {
    if panel_id < 10 { 66 } else { 65 }
}

pub fn all_role_seeds() -> Vec<u64> {
    let panel_count = CELL_COUNT * MASTER_PANEL_COUNT;
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
        for panel_id in 0..MASTER_PANEL_COUNT {
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
            .all(|value| (0xa404_d401..=0xa404_d407).contains(&(value >> 32)))
}

pub fn panel_from_seeds(seed_a: u64, seed_b: u64, order_seed: u64) -> [Sample; PANEL_SIZE] {
    let first = crate::model::generate_dataset(seed_a);
    let second = crate::model::generate_dataset(seed_b);
    let mut source = [first[0]; PANEL_SIZE];
    source[..64].copy_from_slice(&first[..64]);
    source[64..].copy_from_slice(&second[..64]);
    let order = sample_order(order_seed);
    std::array::from_fn(|index| source[order[index]])
}

pub fn sample_order(seed: u64) -> [usize; PANEL_SIZE] {
    let mut order = std::array::from_fn(|index| index);
    let mut state = seed;
    for index in (1..PANEL_SIZE).rev() {
        state = state.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let random = mix64(state);
        order.swap(index, random as usize % (index + 1));
    }
    order
}

pub fn mix64(mut value: u64) -> u64 {
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
    fn seed_roles_are_unique_and_namespaced() {
        assert!(seeds_are_unique_and_namespaced());
        assert_eq!(EVIDENCE_ROUNDS, 1_050);
        assert_eq!(CELL_COUNT * MASTER_PANEL_COUNT, 26_250);
    }

    #[test]
    fn arm_panel_sizes_and_supports_are_frozen() {
        assert_eq!(Arm::ALL.len(), 7);
        assert_eq!(Arm::SentinelK16Pooled.panel_size(), 2_048);
        assert_eq!(Arm::SentinelK16Pooled.support_size(0), 2_048);
        assert_eq!(Arm::SentinelFresh.support_size(1049), 134_400);
    }

    #[test]
    fn blocked_schedule_matches_cyclic_exposure_counts() {
        for panel_id in 0..16 {
            let blocked = (0..EVIDENCE_ROUNDS)
                .filter(|&round| blocked_panel_id(round) == panel_id)
                .count();
            assert_eq!(blocked, cyclic_exposure_count(panel_id, 16));
            assert_eq!(blocked, blocked_exposure_count(panel_id));
        }
    }
}
