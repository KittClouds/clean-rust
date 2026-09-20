pub use adaptive_runtime_ar_00c_int1::SNAPSHOT_EPOCHS;
use adaptive_runtime_ar_00c_int1::{PairRecord, run as run_int1};

const PARAMS: usize = 17;
const GROUPS: usize = 9;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct Group {
    indices: [usize; 3],
    len: usize,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct Partition {
    groups: [Group; GROUPS],
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct CaptureSummary {
    pub snapshot_epoch: usize,
    pub partition: &'static str,
    pub total_absolute_mass: f32,
    pub captured_absolute_mass: f32,
    pub absolute_capture_fraction: f32,
    pub total_harmful_mass: f32,
    pub captured_harmful_mass: f32,
    pub harmful_capture_fraction: f32,
    pub total_synergy_mass: f32,
    pub captured_synergy_mass: f32,
    pub synergy_capture_fraction: f32,
    pub top10_captured: usize,
    pub top10_fraction: f32,
    pub same_hidden_pairs: usize,
    pub same_hidden_captured: usize,
    pub w1_b1_pairs: usize,
    pub w1_b1_captured: usize,
}

#[derive(Clone, Debug)]
pub struct AuditReport {
    pub summaries: Vec<CaptureSummary>,
}

const STRUCTURAL: Partition = Partition {
    groups: [
        Group {
            indices: [0, 1, 8],
            len: 3,
        },
        Group {
            indices: [2, 3, 9],
            len: 3,
        },
        Group {
            indices: [4, 5, 10],
            len: 3,
        },
        Group {
            indices: [6, 7, 11],
            len: 3,
        },
        Group {
            indices: [12, 0, 0],
            len: 1,
        },
        Group {
            indices: [13, 0, 0],
            len: 1,
        },
        Group {
            indices: [14, 0, 0],
            len: 1,
        },
        Group {
            indices: [15, 0, 0],
            len: 1,
        },
        Group {
            indices: [16, 0, 0],
            len: 1,
        },
    ],
};

#[derive(Clone, Copy, Debug)]
struct GroupRng {
    state: u64,
}

impl GroupRng {
    const fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    fn next(&mut self) -> u64 {
        let mut value = self.state;
        value ^= value << 7;
        value ^= value >> 9;
        value ^= value << 8;
        self.state = value;
        value
    }

    fn next_partition(&mut self) -> Partition {
        let mut indices = [0usize; PARAMS];
        for (index, value) in indices.iter_mut().enumerate() {
            *value = index;
        }
        for index in (1..PARAMS).rev() {
            indices.swap(index, (self.next() as usize) % (index + 1));
        }
        let mut partition = Partition::default();
        let mut cursor = 0;
        for (group_index, group) in partition.groups.iter_mut().enumerate() {
            let len = if group_index < 4 { 3 } else { 1 };
            group.len = len;
            group.indices[..len].copy_from_slice(&indices[cursor..cursor + len]);
            cursor += len;
        }
        partition
    }
}

fn random_partition_at(epoch: usize) -> Partition {
    let mut rng = GroupRng::new(0x2b7e_1516_28ae_d2a6);
    (0..=epoch).fold(Partition::default(), |_, _| rng.next_partition())
}

fn same_hidden_unit(index: usize, other: usize) -> bool {
    let first = match index {
        0..=7 => Some(index / 2),
        8..=11 => Some(index - 8),
        _ => None,
    };
    let second = match other {
        0..=7 => Some(other / 2),
        8..=11 => Some(other - 8),
        _ => None,
    };
    first.is_some() && first == second
}

fn w1_b1_same_unit(first: usize, second: usize) -> bool {
    ((first < 8 && (8..=11).contains(&second)) || (second < 8 && (8..=11).contains(&first)))
        && same_hidden_unit(first, second)
}

fn co_grouped(partition: Partition, first: usize, second: usize) -> bool {
    partition.groups.iter().any(|group| {
        group.indices[..group.len].contains(&first) && group.indices[..group.len].contains(&second)
    })
}

fn summarize(
    pairs: &[PairRecord],
    partition: Partition,
    label: &'static str,
    epoch: usize,
) -> CaptureSummary {
    let mut ordered = pairs.to_vec();
    ordered.sort_by(|left, right| right.interaction.abs().total_cmp(&left.interaction.abs()));
    let total_absolute_mass = pairs.iter().map(|pair| pair.interaction.abs()).sum::<f32>();
    let captured_absolute_mass = pairs
        .iter()
        .filter(|pair| co_grouped(partition, pair.first, pair.second))
        .map(|pair| pair.interaction.abs())
        .sum::<f32>();
    let total_harmful_mass = pairs
        .iter()
        .filter(|pair| pair.interaction > 0.0)
        .map(|pair| pair.interaction)
        .sum::<f32>();
    let captured_harmful_mass = pairs
        .iter()
        .filter(|pair| pair.interaction > 0.0 && co_grouped(partition, pair.first, pair.second))
        .map(|pair| pair.interaction)
        .sum::<f32>();
    let total_synergy_mass = pairs
        .iter()
        .filter(|pair| pair.interaction < 0.0)
        .map(|pair| -pair.interaction)
        .sum::<f32>();
    let captured_synergy_mass = pairs
        .iter()
        .filter(|pair| pair.interaction < 0.0 && co_grouped(partition, pair.first, pair.second))
        .map(|pair| -pair.interaction)
        .sum::<f32>();
    let top10_captured = ordered
        .iter()
        .take(10)
        .filter(|pair| co_grouped(partition, pair.first, pair.second))
        .count();
    let same_hidden_pairs = pairs
        .iter()
        .filter(|pair| same_hidden_unit(pair.first, pair.second))
        .count();
    let same_hidden_captured = pairs
        .iter()
        .filter(|pair| {
            same_hidden_unit(pair.first, pair.second)
                && co_grouped(partition, pair.first, pair.second)
        })
        .count();
    let w1_b1_pairs = pairs
        .iter()
        .filter(|pair| w1_b1_same_unit(pair.first, pair.second))
        .count();
    let w1_b1_captured = pairs
        .iter()
        .filter(|pair| {
            w1_b1_same_unit(pair.first, pair.second)
                && co_grouped(partition, pair.first, pair.second)
        })
        .count();
    CaptureSummary {
        snapshot_epoch: epoch,
        partition: label,
        total_absolute_mass,
        captured_absolute_mass,
        absolute_capture_fraction: captured_absolute_mass / total_absolute_mass,
        total_harmful_mass,
        captured_harmful_mass,
        harmful_capture_fraction: if total_harmful_mass > 0.0 {
            captured_harmful_mass / total_harmful_mass
        } else {
            0.0
        },
        total_synergy_mass,
        captured_synergy_mass,
        synergy_capture_fraction: if total_synergy_mass > 0.0 {
            captured_synergy_mass / total_synergy_mass
        } else {
            0.0
        },
        top10_captured,
        top10_fraction: top10_captured as f32 / 10.0,
        same_hidden_pairs,
        same_hidden_captured,
        w1_b1_pairs,
        w1_b1_captured,
    }
}

pub fn run(samples: &[adaptive_runtime_ar_00::Sample]) -> AuditReport {
    let map = run_int1(samples);
    let mut summaries = Vec::with_capacity(SNAPSHOT_EPOCHS.len() * 2);
    for &epoch in &SNAPSHOT_EPOCHS {
        let pairs = map
            .pairs
            .iter()
            .copied()
            .filter(|pair| pair.snapshot_epoch == epoch)
            .collect::<Vec<_>>();
        summaries.push(summarize(&pairs, STRUCTURAL, "E2-structural", epoch));
        summaries.push(summarize(
            &pairs,
            random_partition_at(epoch),
            "E3-randomized",
            epoch,
        ));
    }
    AuditReport { summaries }
}

pub fn xor_samples_for_tests() -> [adaptive_runtime_ar_00::Sample; 4] {
    adaptive_runtime_ar_00::xor_samples()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn audit_has_two_partitions_at_each_snapshot() {
        let report = run(&xor_samples_for_tests());
        assert_eq!(report.summaries.len(), SNAPSHOT_EPOCHS.len() * 2);
        assert!(report.summaries.iter().all(|row| row.top10_captured <= 10));
    }

    #[test]
    fn reconstruction_is_deterministic() {
        assert_eq!(
            run(&xor_samples_for_tests()).summaries,
            run(&xor_samples_for_tests()).summaries
        );
    }
}
