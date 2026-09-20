use adaptive_runtime_ar_00::{Sample, xor_samples};
pub use adaptive_runtime_ar_00c_int1::SNAPSHOT_EPOCHS;
use adaptive_runtime_ar_00c_int1::{
    InteractionMap, PairRecord, ParameterGroup, parameter_group, run as run_int1,
};

pub const PERMUTATIONS: usize = 512;
const PERMUTATION_SEED: u64 = 0x8f3c_1a27_5d90_b4e1;
const CATEGORY_COUNT: usize = 6;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
#[repr(u8)]
pub enum Category {
    #[default]
    SameHiddenUnit = 0,
    DifferentHiddenUnits = 1,
    W1B1SameUnit = 2,
    W1W1SameUnit = 3,
    CrossLayer = 4,
    Other = 5,
}

impl Category {
    pub const fn label(self) -> &'static str {
        match self {
            Self::SameHiddenUnit => "same-hidden-unit",
            Self::DifferentHiddenUnits => "different-hidden-units",
            Self::W1B1SameUnit => "w1-b1-same-unit",
            Self::W1W1SameUnit => "w1-w1-same-unit",
            Self::CrossLayer => "cross-layer",
            Self::Other => "other",
        }
    }

    pub const fn all() -> [Self; CATEGORY_COUNT] {
        [
            Self::SameHiddenUnit,
            Self::DifferentHiddenUnits,
            Self::W1B1SameUnit,
            Self::W1W1SameUnit,
            Self::CrossLayer,
            Self::Other,
        ]
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct Descriptor {
    group: ParameterGroup,
    hidden_unit: Option<u8>,
}

const fn descriptor(index: usize) -> Descriptor {
    let group = parameter_group(index);
    let hidden_unit = match index {
        0..=7 => Some((index / 2) as u8),
        8..=11 => Some((index - 8) as u8),
        _ => None,
    };
    Descriptor { group, hidden_unit }
}

const ORIGINAL_DESCRIPTORS: [Descriptor; 17] = [
    descriptor(0),
    descriptor(1),
    descriptor(2),
    descriptor(3),
    descriptor(4),
    descriptor(5),
    descriptor(6),
    descriptor(7),
    descriptor(8),
    descriptor(9),
    descriptor(10),
    descriptor(11),
    descriptor(12),
    descriptor(13),
    descriptor(14),
    descriptor(15),
    descriptor(16),
];

fn same_hidden_unit(first: Descriptor, second: Descriptor) -> bool {
    first.hidden_unit.is_some() && first.hidden_unit == second.hidden_unit
}

fn category_matches(category: Category, first: Descriptor, second: Descriptor) -> bool {
    match category {
        Category::SameHiddenUnit => same_hidden_unit(first, second),
        Category::DifferentHiddenUnits => {
            first.hidden_unit.is_some()
                && second.hidden_unit.is_some()
                && first.hidden_unit != second.hidden_unit
        }
        Category::W1B1SameUnit => {
            ((first.group == ParameterGroup::W1 && second.group == ParameterGroup::B1)
                || (first.group == ParameterGroup::B1 && second.group == ParameterGroup::W1))
                && same_hidden_unit(first, second)
        }
        Category::W1W1SameUnit => {
            first.group == ParameterGroup::W1
                && second.group == ParameterGroup::W1
                && same_hidden_unit(first, second)
        }
        Category::CrossLayer => {
            let first_input = matches!(first.group, ParameterGroup::W1 | ParameterGroup::B1);
            let second_input = matches!(second.group, ParameterGroup::W1 | ParameterGroup::B1);
            first_input != second_input
        }
        Category::Other => !Category::all()[..5]
            .iter()
            .copied()
            .any(|view| category_matches(view, first, second)),
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct CategoryStats {
    pub count: usize,
    pub harmful_pairs: usize,
    pub synergistic_pairs: usize,
    pub harmful_rate: f32,
    pub synergistic_rate: f32,
    pub mean_interaction: f32,
    pub mean_absolute_interaction: f32,
    pub q90_absolute_interaction: f32,
    pub q95_absolute_interaction: f32,
    pub max_absolute_interaction: f32,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct NullStats {
    pub permutations: usize,
    pub observed_mean_absolute: f32,
    pub null_mean_absolute: f32,
    pub null_q95_mean_absolute: f32,
    pub observed_over_null: f32,
    pub empirical_p_ge_observed: f32,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct TopologySummary {
    pub snapshot_epoch: usize,
    pub category: Category,
    pub observed: CategoryStats,
    pub null: NullStats,
}

#[derive(Clone, Debug)]
pub struct TopologyReport {
    pub interaction_map: InteractionMap,
    pub summaries: Vec<TopologySummary>,
}

#[derive(Clone, Copy, Debug)]
struct SmallRng {
    state: u64,
}

impl SmallRng {
    const fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    fn next_u64(&mut self) -> u64 {
        let mut value = self.state;
        value ^= value << 7;
        value ^= value >> 9;
        value ^= value << 8;
        self.state = value;
        value
    }

    fn shuffle<const N: usize>(&mut self, values: &mut [usize; N]) {
        for index in (1..N).rev() {
            let swap = (self.next_u64() as usize) % (index + 1);
            values.swap(index, swap);
        }
    }
}

fn quantile(values: &mut [f32], fraction: f32) -> f32 {
    if values.is_empty() {
        return 0.0;
    }
    values.sort_by(|left, right| left.total_cmp(right));
    let index = ((values.len() - 1) as f32 * fraction).round() as usize;
    values[index.min(values.len() - 1)]
}

fn category_stats<I>(pairs: I, category: Category, descriptors: &[Descriptor; 17]) -> CategoryStats
where
    I: IntoIterator<Item = PairRecord>,
{
    let mut interactions = Vec::with_capacity(136);
    let mut harmful_pairs = 0;
    let mut synergistic_pairs = 0;
    let mut sum = 0.0;
    for pair in pairs {
        if !category_matches(category, descriptors[pair.first], descriptors[pair.second]) {
            continue;
        }
        if pair.is_harmful() {
            harmful_pairs += 1;
        }
        if pair.is_synergistic() {
            synergistic_pairs += 1;
        }
        sum += pair.interaction;
        interactions.push(pair.interaction.abs());
    }
    let count = interactions.len();
    if count == 0 {
        return CategoryStats::default();
    }
    let mut quantile_values = interactions.clone();
    let mean_absolute_interaction = interactions.iter().sum::<f32>() / count as f32;
    CategoryStats {
        count,
        harmful_pairs,
        synergistic_pairs,
        harmful_rate: harmful_pairs as f32 / count as f32,
        synergistic_rate: synergistic_pairs as f32 / count as f32,
        mean_interaction: sum / count as f32,
        mean_absolute_interaction,
        q90_absolute_interaction: quantile(&mut quantile_values, 0.90),
        q95_absolute_interaction: quantile(&mut quantile_values, 0.95),
        max_absolute_interaction: interactions.into_iter().fold(0.0, f32::max),
    }
}

fn null_summary(
    pairs: &[PairRecord],
    category: Category,
    observed: CategoryStats,
    snapshot_index: usize,
) -> NullStats {
    let mut rng = SmallRng::new(PERMUTATION_SEED ^ snapshot_index as u64);
    let mut permutation_indices = [0usize; 17];
    let mut null_values = Vec::with_capacity(PERMUTATIONS);
    let mut ge_observed = 0;
    for index in 0..PERMUTATIONS {
        permutation_indices
            .iter_mut()
            .enumerate()
            .for_each(|(slot, value)| {
                *value = slot;
            });
        rng.shuffle(&mut permutation_indices);
        let mut descriptors = [Descriptor::default(); 17];
        for (slot, &source) in permutation_indices.iter().enumerate() {
            descriptors[slot] = ORIGINAL_DESCRIPTORS[source];
        }
        let stats = category_stats(pairs.iter().copied(), category, &descriptors);
        null_values.push(stats.mean_absolute_interaction);
        if stats.mean_absolute_interaction >= observed.mean_absolute_interaction {
            ge_observed += 1;
        }
        let _ = index;
    }
    let mut quantile_values = null_values.clone();
    let null_mean_absolute = null_values.iter().sum::<f32>() / PERMUTATIONS as f32;
    NullStats {
        permutations: PERMUTATIONS,
        observed_mean_absolute: observed.mean_absolute_interaction,
        null_mean_absolute,
        null_q95_mean_absolute: quantile(&mut quantile_values, 0.95),
        observed_over_null: if null_mean_absolute > 0.0 {
            observed.mean_absolute_interaction / null_mean_absolute
        } else {
            0.0
        },
        empirical_p_ge_observed: (ge_observed + 1) as f32 / (PERMUTATIONS + 1) as f32,
    }
}

pub fn run(samples: &[Sample]) -> TopologyReport {
    let interaction_map = run_int1(samples);
    let mut summaries = Vec::with_capacity(SNAPSHOT_EPOCHS.len() * CATEGORY_COUNT);
    for (snapshot_index, &epoch) in SNAPSHOT_EPOCHS.iter().enumerate() {
        let snapshot_pairs = interaction_map
            .pairs
            .iter()
            .copied()
            .filter(|pair| pair.snapshot_epoch == epoch)
            .collect::<Vec<_>>();
        for category in Category::all() {
            let observed = category_stats(
                snapshot_pairs.iter().copied(),
                category,
                &ORIGINAL_DESCRIPTORS,
            );
            let null = null_summary(&snapshot_pairs, category, observed, snapshot_index);
            summaries.push(TopologySummary {
                snapshot_epoch: epoch,
                category,
                observed,
                null,
            });
        }
    }
    TopologyReport {
        interaction_map,
        summaries,
    }
}

pub fn xor_samples_for_tests() -> [Sample; 4] {
    xor_samples()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn topology_has_all_snapshot_category_rows() {
        let report = run(&xor_samples());
        assert_eq!(
            report.summaries.len(),
            SNAPSHOT_EPOCHS.len() * CATEGORY_COUNT
        );
        assert_eq!(
            report.interaction_map.pairs.len(),
            SNAPSHOT_EPOCHS.len() * 136
        );
        assert!(
            report
                .summaries
                .iter()
                .all(|row| row.null.permutations == PERMUTATIONS)
        );
    }

    #[test]
    fn structural_views_are_nonempty_and_deterministic() {
        let first = run(&xor_samples());
        let second = run(&xor_samples());
        assert_eq!(first.summaries, second.summaries);
        for category in Category::all() {
            assert!(
                first
                    .summaries
                    .iter()
                    .filter(|row| row.category == category)
                    .any(|row| row.observed.count > 0)
            );
        }
    }
}
