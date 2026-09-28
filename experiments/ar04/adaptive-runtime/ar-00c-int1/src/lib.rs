use std::cmp::Ordering;

use adaptive_runtime_ar_00::{ActionRuntime, Model, PARAMS, Sample, xor_samples};
use hashbrown::HashMap;

pub const SNAPSHOT_EPOCHS: [usize; 4] = [0, 100, 1_000, 3_000];
pub const ACTION_STEP: f32 = 0.02;
pub const LOWER_BOUND: f32 = -3.0;
pub const UPPER_BOUND: f32 = 3.0;

const MAGNITUDES: &[f32] = &[
    ACTION_STEP,
    ACTION_STEP * 0.5,
    ACTION_STEP * 0.25,
    ACTION_STEP * 0.125,
    ACTION_STEP * 0.0625,
];

const PARAMETER_LABELS: [&str; PARAMS] = [
    "W1[0,0]", "W1[0,1]", "W1[1,0]", "W1[1,1]", "W1[2,0]", "W1[2,1]", "W1[3,0]", "W1[3,1]",
    "b1[0]", "b1[1]", "b1[2]", "b1[3]", "W2[0]", "W2[1]", "W2[2]", "W2[3]", "b2",
];

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
#[repr(u8)]
pub enum ParameterGroup {
    #[default]
    W1 = 0,
    B1 = 1,
    W2 = 2,
    B2 = 3,
}

impl ParameterGroup {
    pub const fn label(self) -> &'static str {
        match self {
            Self::W1 => "W1",
            Self::B1 => "b1",
            Self::W2 => "W2",
            Self::B2 => "b2",
        }
    }

    const fn ordinal(self) -> u8 {
        self as u8
    }
}

pub const fn parameter_group(index: usize) -> ParameterGroup {
    match index {
        0..=7 => ParameterGroup::W1,
        8..=11 => ParameterGroup::B1,
        12..=15 => ParameterGroup::W2,
        16 => ParameterGroup::B2,
        _ => panic!("AR-00C-INT1 parameter index out of range"),
    }
}

pub const fn parameter_label(index: usize) -> &'static str {
    PARAMETER_LABELS[index]
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct PreferredAction {
    pub delta: f32,
    pub utility: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PairRecord {
    pub snapshot_epoch: usize,
    pub first: usize,
    pub second: usize,
    pub first_delta: f32,
    pub second_delta: f32,
    pub first_utility: f32,
    pub second_utility: f32,
    pub first_singleton_effect: f32,
    pub second_singleton_effect: f32,
    pub pair_effect: f32,
    pub interaction: f32,
}

impl PairRecord {
    pub fn is_harmful(self) -> bool {
        self.interaction > 1e-7
    }

    pub fn is_synergistic(self) -> bool {
        self.interaction < -1e-7
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct SnapshotSummary {
    pub epoch: usize,
    pub selected_actions: usize,
    pub pair_count: usize,
    pub harmful_pairs: usize,
    pub synergistic_pairs: usize,
    pub mean_interaction: f32,
    pub max_harmful_interaction: f32,
    pub strongest_synergy: f32,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct GroupSummary {
    pub snapshot_epoch: usize,
    pub first_group: ParameterGroup,
    pub second_group: ParameterGroup,
    pub pair_count: usize,
    pub harmful_pairs: usize,
    pub synergistic_pairs: usize,
    pub mean_interaction: f32,
    pub max_harmful_interaction: f32,
    pub strongest_synergy: f32,
}

#[derive(Clone, Debug)]
pub struct InteractionMap {
    pub snapshots: Vec<SnapshotSummary>,
    pub pairs: Vec<PairRecord>,
    pub groups: Vec<GroupSummary>,
}

#[derive(Clone, Copy, Debug)]
struct Snapshot {
    epoch: usize,
    model: Model,
}

#[derive(Clone, Copy, Debug, Default)]
struct GroupAccumulator {
    pair_count: usize,
    harmful_pairs: usize,
    synergistic_pairs: usize,
    sum_interaction: f32,
    max_harmful_interaction: f32,
    strongest_synergy: f32,
}

fn capture_snapshots(samples: &[Sample]) -> [Snapshot; SNAPSHOT_EPOCHS.len()] {
    let mut model = Model::initial();
    let mut snapshots = [Snapshot {
        epoch: 0,
        model: Model::initial(),
    }; SNAPSHOT_EPOCHS.len()];
    let mut next_snapshot = 0;
    for epoch in 0..=SNAPSHOT_EPOCHS[SNAPSHOT_EPOCHS.len() - 1] {
        if next_snapshot < SNAPSHOT_EPOCHS.len() && epoch == SNAPSHOT_EPOCHS[next_snapshot] {
            snapshots[next_snapshot] = Snapshot { epoch, model };
            next_snapshot += 1;
        }
        if epoch == SNAPSHOT_EPOCHS[SNAPSHOT_EPOCHS.len() - 1] {
            break;
        }
        let (_, gradient) = model.loss_and_gradient(samples);
        let mut runtime = ActionRuntime::new(ACTION_STEP, LOWER_BOUND, UPPER_BOUND);
        runtime.apply(&mut model, &gradient);
    }
    snapshots
}

fn preferred_singleton(
    model: &Model,
    samples: &[Sample],
    index: usize,
    baseline_loss: f32,
) -> PreferredAction {
    let current = model.parameters[index];
    let mut best = PreferredAction::default();
    for &magnitude in MAGNITUDES {
        for delta in [-magnitude, magnitude] {
            let candidate = current + delta;
            if !(LOWER_BOUND..=UPPER_BOUND).contains(&candidate) {
                continue;
            }
            let mut candidate_model = *model;
            candidate_model.parameters[index] = candidate;
            let candidate_loss = candidate_model.loss_and_gradient(samples).0;
            let utility = baseline_loss - candidate_loss;
            if utility > best.utility {
                best = PreferredAction { delta, utility };
            }
        }
    }
    best
}

fn pair_record(
    snapshot: Snapshot,
    samples: &[Sample],
    baseline_loss: f32,
    first: usize,
    first_action: PreferredAction,
    second: usize,
    second_action: PreferredAction,
) -> PairRecord {
    let mut first_model = snapshot.model;
    first_model.parameters[first] += first_action.delta;
    let first_singleton_effect = first_model.loss_and_gradient(samples).0 - baseline_loss;

    let mut second_model = snapshot.model;
    second_model.parameters[second] += second_action.delta;
    let second_singleton_effect = second_model.loss_and_gradient(samples).0 - baseline_loss;

    let mut pair_model = snapshot.model;
    pair_model.parameters[first] += first_action.delta;
    pair_model.parameters[second] += second_action.delta;
    let pair_effect = pair_model.loss_and_gradient(samples).0 - baseline_loss;
    let interaction = pair_effect - (first_singleton_effect + second_singleton_effect);

    PairRecord {
        snapshot_epoch: snapshot.epoch,
        first,
        second,
        first_delta: first_action.delta,
        second_delta: second_action.delta,
        first_utility: first_action.utility,
        second_utility: second_action.utility,
        first_singleton_effect,
        second_singleton_effect,
        pair_effect,
        interaction,
    }
}

fn cmp_group_summary(left: &GroupSummary, right: &GroupSummary) -> Ordering {
    left.snapshot_epoch
        .cmp(&right.snapshot_epoch)
        .then_with(|| {
            (left.first_group.ordinal(), left.second_group.ordinal())
                .cmp(&(right.first_group.ordinal(), right.second_group.ordinal()))
        })
}

fn summarize_groups(pairs: &[PairRecord]) -> Vec<GroupSummary> {
    let mut accumulators = HashMap::<(usize, u8, u8), GroupAccumulator>::new();
    for &pair in pairs {
        let first_group = parameter_group(pair.first).ordinal();
        let second_group = parameter_group(pair.second).ordinal();
        let entry = accumulators
            .entry((pair.snapshot_epoch, first_group, second_group))
            .or_default();
        entry.pair_count += 1;
        entry.sum_interaction += pair.interaction;
        if pair.is_harmful() {
            entry.harmful_pairs += 1;
            entry.max_harmful_interaction = entry.max_harmful_interaction.max(pair.interaction);
        }
        if pair.is_synergistic() {
            entry.synergistic_pairs += 1;
            if entry.strongest_synergy == 0.0 {
                entry.strongest_synergy = pair.interaction;
            } else {
                entry.strongest_synergy = entry.strongest_synergy.min(pair.interaction);
            }
        }
    }
    let mut groups = accumulators
        .into_iter()
        .map(|((epoch, first, second), value)| GroupSummary {
            snapshot_epoch: epoch,
            first_group: match first {
                0 => ParameterGroup::W1,
                1 => ParameterGroup::B1,
                2 => ParameterGroup::W2,
                3 => ParameterGroup::B2,
                _ => unreachable!(),
            },
            second_group: match second {
                0 => ParameterGroup::W1,
                1 => ParameterGroup::B1,
                2 => ParameterGroup::W2,
                3 => ParameterGroup::B2,
                _ => unreachable!(),
            },
            pair_count: value.pair_count,
            harmful_pairs: value.harmful_pairs,
            synergistic_pairs: value.synergistic_pairs,
            mean_interaction: value.sum_interaction / value.pair_count as f32,
            max_harmful_interaction: value.max_harmful_interaction,
            strongest_synergy: value.strongest_synergy,
        })
        .collect::<Vec<_>>();
    groups.sort_by(cmp_group_summary);
    groups
}

pub fn run(samples: &[Sample]) -> InteractionMap {
    let snapshots = capture_snapshots(samples);
    let mut snapshot_summaries = Vec::with_capacity(snapshots.len());
    let mut pairs = Vec::with_capacity(snapshots.len() * (PARAMS * (PARAMS - 1) / 2));
    for snapshot in snapshots {
        let baseline_loss = snapshot.model.loss_and_gradient(samples).0;
        let actions: [PreferredAction; PARAMS] = std::array::from_fn(|index| {
            preferred_singleton(&snapshot.model, samples, index, baseline_loss)
        });
        let selected_actions = actions.iter().filter(|action| action.delta != 0.0).count();
        let start = pairs.len();
        for first in 0..PARAMS {
            for second in first + 1..PARAMS {
                pairs.push(pair_record(
                    snapshot,
                    samples,
                    baseline_loss,
                    first,
                    actions[first],
                    second,
                    actions[second],
                ));
            }
        }
        let snapshot_pairs = &pairs[start..];
        let pair_count = snapshot_pairs.len();
        let harmful_pairs = snapshot_pairs
            .iter()
            .filter(|pair| pair.is_harmful())
            .count();
        let synergistic_pairs = snapshot_pairs
            .iter()
            .filter(|pair| pair.is_synergistic())
            .count();
        let sum_interaction = snapshot_pairs
            .iter()
            .map(|pair| pair.interaction)
            .sum::<f32>();
        let max_harmful_interaction = snapshot_pairs
            .iter()
            .map(|pair| pair.interaction)
            .filter(|&value| value > 0.0)
            .fold(0.0, f32::max);
        let strongest_synergy = snapshot_pairs
            .iter()
            .map(|pair| pair.interaction)
            .filter(|&value| value < 0.0)
            .fold(0.0, f32::min);
        snapshot_summaries.push(SnapshotSummary {
            epoch: snapshot.epoch,
            selected_actions,
            pair_count,
            harmful_pairs,
            synergistic_pairs,
            mean_interaction: sum_interaction / pair_count as f32,
            max_harmful_interaction,
            strongest_synergy,
        });
    }
    InteractionMap {
        snapshots: snapshot_summaries,
        groups: summarize_groups(&pairs),
        pairs,
    }
}

pub fn xor_samples_for_tests() -> [Sample; 4] {
    xor_samples()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn complete_pair_map_has_all_snapshot_pairs() {
        let map = run(&xor_samples());
        assert_eq!(map.snapshots.len(), SNAPSHOT_EPOCHS.len());
        assert_eq!(map.pairs.len(), SNAPSHOT_EPOCHS.len() * 136);
        assert!(
            map.snapshots
                .iter()
                .all(|summary| summary.pair_count == 136)
        );
        assert!(map.pairs.iter().any(|pair| pair.interaction.abs() > 1e-7));
    }

    #[test]
    fn pair_interaction_signs_are_classified() {
        let map = run(&xor_samples());
        assert!(map.pairs.iter().any(|pair| pair.is_harmful()));
        assert!(map.pairs.iter().any(|pair| pair.is_synergistic()));
        assert!(!map.groups.is_empty());
    }
}
