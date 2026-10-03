//! Q10-DA1 core: target-blind support partitioning and additive readout replay.
//!
//! This module deliberately stops at the distributed readout seam. It has no
//! endpoint geometry gate, protocol runner, receipt writer, or interaction
//! search. A coordinate is scored only on its complete structural row support;
//! selected supports are disjoint before any target-conditioned score is read.

use crate::{
    linear::DriveOperator,
    q10sr::readout::{self, interior_steps, nextafter32},
};
use serde::Serialize;

pub const FINAL_RESERVE: u32 = 16;
pub const STEP_VOCABULARY: [i8; 11] = [0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16];
pub const SELECTOR_SALTS: [u64; 4] = [
    0xDA01_0000_0000_0001,
    0xDA01_0000_0000_0002,
    0xDA01_0000_0000_0003,
    0xDA01_0000_0000_0004,
];

#[derive(Clone, Debug, Serialize)]
pub struct SupportIncidence {
    pub row_count: usize,
    pub rows_by_coordinate: Vec<Vec<usize>>,
}

impl SupportIncidence {
    pub fn from_operator(operator: &DriveOperator) -> Self {
        let mut rows_by_coordinate = vec![Vec::new(); operator.coordinates];
        for (row, coordinates) in operator.rows.iter().enumerate() {
            for &coordinate in coordinates {
                let rows = &mut rows_by_coordinate[coordinate];
                if rows.last().copied() != Some(row) {
                    rows.push(row);
                }
            }
        }
        Self {
            row_count: operator.rows.len(),
            rows_by_coordinate,
        }
    }

    pub fn rows(&self, coordinate: usize) -> &[usize] {
        &self.rows_by_coordinate[coordinate]
    }

    pub fn overlaps(&self, left: usize, right: usize) -> bool {
        let (mut a, mut b) = (0, 0);
        let left_rows = self.rows(left);
        let right_rows = self.rows(right);
        while a < left_rows.len() && b < right_rows.len() {
            match left_rows[a].cmp(&right_rows[b]) {
                std::cmp::Ordering::Less => a += 1,
                std::cmp::Ordering::Greater => b += 1,
                std::cmp::Ordering::Equal => return true,
            }
        }
        false
    }

    pub fn post_ids(&self, coordinate: usize, posts: usize) -> Vec<usize> {
        let mut ids = self
            .rows(coordinate)
            .iter()
            .map(|&row| row % posts)
            .collect::<Vec<_>>();
        ids.sort_unstable();
        ids.dedup();
        ids
    }

    pub fn cue_ids(&self, coordinate: usize, posts: usize) -> Vec<usize> {
        let mut ids = self
            .rows(coordinate)
            .iter()
            .map(|&row| row / posts)
            .collect::<Vec<_>>();
        ids.sort_unstable();
        ids.dedup();
        ids
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct GreedySelection {
    pub ordered_coordinates: Vec<usize>,
    pub selected_coordinates: Vec<usize>,
    pub excluded_coordinates: Vec<usize>,
    pub covered_rows: Vec<usize>,
}

fn mix(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

pub fn stable_hash_order(
    coordinates: &[usize],
    seed: u64,
    event_key: u64,
    selector_salt: u64,
) -> Vec<usize> {
    let mut ordered = coordinates.to_vec();
    ordered.sort_unstable_by_key(|&coordinate| {
        (
            // Keep the domains independent.  In particular, an event key is
            // allowed to identify tau/trial/side without carrying the seed;
            // XORing all fields together would otherwise make a seed-bearing
            // event key cancel the explicit seed input.
            mix(seed ^ 0xDA01_5345_4544_0001)
                ^ mix(event_key ^ 0xDA01_4556_454E_5401)
                ^ mix(selector_salt ^ 0xDA01_5341_4C54_0001)
                ^ mix(coordinate as u64 ^ 0xDA01_434F_4F52_4401),
            coordinate,
        )
    });
    ordered
}

pub fn greedy_maximal_support_disjoint(
    ordered_coordinates: &[usize],
    incidence: &SupportIncidence,
) -> GreedySelection {
    let mut occupied = vec![false; incidence.row_count];
    let mut selected = Vec::with_capacity(ordered_coordinates.len());
    let mut excluded = Vec::new();
    for &coordinate in ordered_coordinates {
        let support = incidence.rows(coordinate);
        let fits = support
            .iter()
            .all(|&row| !occupied.get(row).copied().unwrap_or(true));
        if fits {
            selected.push(coordinate);
            for &row in support {
                occupied[row] = true;
            }
        } else {
            excluded.push(coordinate);
        }
    }
    let covered_rows = occupied
        .iter()
        .enumerate()
        .filter_map(|(row, &used)| used.then_some(row))
        .collect();
    GreedySelection {
        ordered_coordinates: ordered_coordinates.to_vec(),
        selected_coordinates: selected,
        excluded_coordinates: excluded,
        covered_rows,
    }
}

pub fn four_greedy_maximal_sets(
    coordinates: &[usize],
    incidence: &SupportIncidence,
    seed: u64,
    event_key: u64,
) -> [GreedySelection; 4] {
    let eligible = coordinates
        .iter()
        .copied()
        .filter(|&coordinate| !incidence.rows(coordinate).is_empty())
        .collect::<Vec<_>>();
    std::array::from_fn(|index| {
        let order = stable_hash_order(&eligible, seed, event_key, SELECTOR_SALTS[index]);
        greedy_maximal_support_disjoint(&order, incidence)
    })
}

#[derive(Clone, Copy, Debug, Serialize)]
pub struct RowChange {
    pub row: usize,
    pub before_bits: u32,
    pub after_bits: u32,
}

#[derive(Clone, Debug, Serialize)]
pub struct CoordinateChoice {
    pub coordinate: usize,
    pub selected_step: i8,
    pub before_bits: u32,
    pub after_bits: u32,
    pub support_rows: Vec<usize>,
    pub support_post_ids: Vec<usize>,
    pub support_cue_ids: Vec<usize>,
    pub one_post_support: bool,
    pub candidate_count: usize,
    pub legal_candidate_count: usize,
    pub initial_mismatch_count: usize,
    pub final_mismatch_count: usize,
    pub mismatch_gain: isize,
    pub initial_squared_error: f64,
    pub final_squared_error: f64,
    pub squared_error_gain: f64,
    pub initial_l2: f64,
    pub final_l2: f64,
    pub mismatch_reduced: bool,
    pub squared_error_reduced: bool,
    pub pareto_improvement: bool,
    pub l2_increased_vs_initial: bool,
    pub row_changes: Vec<RowChange>,
}

#[derive(Clone, Copy)]
struct SupportMetrics {
    mismatches: usize,
    squared_error: f64,
}

fn support_metrics(
    operator: &DriveOperator,
    support: &[usize],
    weights: &[f32],
    target_readout: &[f32],
    coordinate: usize,
    replacement: f32,
) -> SupportMetrics {
    let mut metrics = SupportMetrics {
        mismatches: 0,
        squared_error: 0.0,
    };
    for &row in support {
        let actual = readout::replay_row_with_move(
            operator,
            row,
            weights,
            coordinate,
            replacement,
        );
        let target = target_readout[row];
        metrics.mismatches += usize::from(actual.to_bits() != target.to_bits());
        let error = f64::from(actual) - f64::from(target);
        metrics.squared_error += error * error;
    }
    metrics
}

fn legal_replacement(initial: f32, step: i8) -> Option<f32> {
    if step == 0 {
        return Some(initial);
    }
    let downward = step < 0;
    let mut value = initial;
    for _ in 0..step.unsigned_abs() {
        value = nextafter32(value, downward)?;
    }
    if !value.is_finite()
        || value <= 0.0
        || value >= 2.0
        || interior_steps(value, true, FINAL_RESERVE) < FINAL_RESERVE
        || interior_steps(value, false, FINAL_RESERVE) < FINAL_RESERVE
    {
        return None;
    }
    Some(value)
}

fn better(metrics: SupportMetrics, best: SupportMetrics) -> bool {
    metrics.mismatches < best.mismatches
        || (metrics.mismatches == best.mismatches
            && metrics.squared_error.total_cmp(&best.squared_error).is_lt())
}

pub fn optimize_coordinate(
    operator: &DriveOperator,
    incidence: &SupportIncidence,
    initial_weights: &[f32],
    initial_readout: &[f32],
    target_readout: &[f32],
    coordinate: usize,
) -> CoordinateChoice {
    assert_eq!(incidence.row_count, operator.rows.len());
    assert_eq!(initial_weights.len(), operator.coordinates);
    assert_eq!(initial_readout.len(), operator.rows.len());
    assert_eq!(target_readout.len(), operator.rows.len());
    assert!(coordinate < operator.coordinates);

    let support = incidence.rows(coordinate);
    let initial = support_metrics(
        operator,
        support,
        initial_weights,
        target_readout,
        coordinate,
        initial_weights[coordinate],
    );
    let mut best_step = 0;
    let mut best_bits = initial_weights[coordinate].to_bits();
    let mut best_metrics = initial;
    let mut legal_candidate_count = 0;
    for &step in &STEP_VOCABULARY {
        let Some(replacement) = legal_replacement(initial_weights[coordinate], step) else {
            continue;
        };
        legal_candidate_count += 1;
        let metrics = support_metrics(
            operator,
            support,
            initial_weights,
            target_readout,
            coordinate,
            replacement,
        );
        if (step == 0 && best_step == 0) || better(metrics, best_metrics) {
            best_step = step;
            best_bits = replacement.to_bits();
            best_metrics = metrics;
        }
    }

    let mut row_changes = Vec::with_capacity(support.len());
    for &row in support {
        let before = readout::replay_row(operator, row, initial_weights);
        let after = readout::replay_row_with_move(
            operator,
            row,
            initial_weights,
            coordinate,
            f32::from_bits(best_bits),
        );
        row_changes.push(RowChange {
            row,
            before_bits: before.to_bits(),
            after_bits: after.to_bits(),
        });
    }
    let initial_l2 = initial.squared_error.sqrt();
    let final_l2 = best_metrics.squared_error.sqrt();
    let mismatch_reduced = best_metrics.mismatches < initial.mismatches;
    let squared_error_reduced = best_metrics.squared_error < initial.squared_error;
    let pareto_improvement = best_metrics.mismatches <= initial.mismatches
        && best_metrics.squared_error <= initial.squared_error
        && (mismatch_reduced || squared_error_reduced);
    CoordinateChoice {
        coordinate,
        selected_step: best_step,
        before_bits: initial_weights[coordinate].to_bits(),
        after_bits: best_bits,
        support_rows: support.to_vec(),
        support_post_ids: incidence.post_ids(coordinate, operator.posts),
        support_cue_ids: incidence.cue_ids(coordinate, operator.posts),
        one_post_support: incidence.post_ids(coordinate, operator.posts).len() <= 1,
        candidate_count: STEP_VOCABULARY.len(),
        legal_candidate_count,
        initial_mismatch_count: initial.mismatches,
        final_mismatch_count: best_metrics.mismatches,
        mismatch_gain: initial.mismatches as isize - best_metrics.mismatches as isize,
        initial_squared_error: initial.squared_error,
        final_squared_error: best_metrics.squared_error,
        squared_error_gain: initial.squared_error - best_metrics.squared_error,
        initial_l2,
        final_l2,
        mismatch_reduced,
        squared_error_reduced,
        pareto_improvement,
        l2_increased_vs_initial: best_metrics.squared_error > initial.squared_error,
        row_changes,
    }
}

#[derive(Debug)]
pub struct ReplayCheck {
    pub final_weights: Vec<f32>,
    pub assembled_readout: Vec<f32>,
    pub full_replay: Vec<f32>,
    pub bitwise_equal: bool,
}

pub fn assemble_and_replay(
    operator: &DriveOperator,
    incidence: &SupportIncidence,
    initial_weights: &[f32],
    initial_readout: &[f32],
    choices: &[CoordinateChoice],
) -> Result<ReplayCheck, &'static str> {
    if initial_weights.len() != operator.coordinates
        || initial_readout.len() != operator.rows.len()
    {
        return Err("initial replay dimensions do not match operator");
    }
    let mut final_weights = initial_weights.to_vec();
    let mut assembled_readout = initial_readout.to_vec();
    let mut used_coordinates = vec![false; operator.coordinates];
    let mut occupied_rows = vec![false; operator.rows.len()];
    for choice in choices {
        if choice.coordinate >= operator.coordinates
            || used_coordinates[choice.coordinate]
            || choice.support_rows != incidence.rows(choice.coordinate)
        {
            return Err("choice coordinate/support mismatch");
        }
        used_coordinates[choice.coordinate] = true;
        for &row in incidence.rows(choice.coordinate) {
            if occupied_rows[row] {
                return Err("coordinate supports overlap");
            }
            occupied_rows[row] = true;
            assembled_readout[row] = readout::replay_row_with_move(
                operator,
                row,
                initial_weights,
                choice.coordinate,
                f32::from_bits(choice.after_bits),
            );
        }
        final_weights[choice.coordinate] = f32::from_bits(choice.after_bits);
    }
    let full_replay = readout::sequential(operator, &final_weights);
    let bitwise_equal = assembled_readout
        .iter()
        .zip(&full_replay)
        .all(|(assembled, replay)| assembled.to_bits() == replay.to_bits());
    Ok(ReplayCheck {
        final_weights,
        assembled_readout,
        full_replay,
        bitwise_equal,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn operator(rows: Vec<Vec<usize>>, coordinates: usize, posts: usize) -> DriveOperator {
        DriveOperator {
            cues: rows.len() / posts,
            posts,
            coordinates,
            rows,
        }
    }

    fn bits(values: &[f32]) -> Vec<u32> {
        values.iter().map(|value| value.to_bits()).collect()
    }

    #[test]
    fn support_selection_rejects_overlap_even_when_effect_is_zero() {
        let op = operator(vec![vec![0, 1], vec![0, 1], vec![2]], 3, 1);
        let incidence = SupportIncidence::from_operator(&op);
        let selection = greedy_maximal_support_disjoint(&[0, 1, 2], &incidence);
        assert_eq!(selection.selected_coordinates, vec![0, 2]);
        assert_eq!(selection.excluded_coordinates, vec![1]);
        assert!(incidence.overlaps(0, 1));
    }

    #[test]
    fn zero_fallback_preserves_signed_zero_and_empty_sum() {
        let op = operator(vec![Vec::new(), vec![0]], 1, 1);
        let incidence = SupportIncidence::from_operator(&op);
        let initial = vec![-0.0_f32];
        let initial_readout = readout::sequential(&op, &initial);
        assert_eq!(initial_readout[0].to_bits(), 0x8000_0000);
        let choice = optimize_coordinate(
            &op,
            &incidence,
            &initial,
            &initial_readout,
            &initial_readout,
            0,
        );
        assert_eq!(choice.selected_step, 0);
        assert_eq!(choice.before_bits, 0x8000_0000);
        assert_eq!(choice.after_bits, 0x8000_0000);
        assert_eq!(choice.row_changes[0].after_bits, 0x8000_0000);
    }

    #[test]
    fn disjoint_union_matches_full_sequential_replay_bit_for_bit() {
        let op = operator(vec![vec![0, 0], vec![1], vec![2, 2], Vec::new()], 3, 1);
        let incidence = SupportIncidence::from_operator(&op);
        let initial = vec![0.75_f32, 1.0, 1.25];
        let mut target = initial.clone();
        target[0] = nextafter32(target[0], false).unwrap();
        target[2] = nextafter32(target[2], true).unwrap();
        let initial_readout = readout::sequential(&op, &initial);
        let target_readout = readout::sequential(&op, &target);
        let choices = vec![
            optimize_coordinate(
                &op,
                &incidence,
                &initial,
                &initial_readout,
                &target_readout,
                0,
            ),
            optimize_coordinate(
                &op,
                &incidence,
                &initial,
                &initial_readout,
                &target_readout,
                2,
            ),
        ];
        let replay = assemble_and_replay(
            &op,
            &incidence,
            &initial,
            &initial_readout,
            &choices,
        )
        .unwrap();
        assert!(replay.bitwise_equal);
        assert_eq!(bits(&replay.full_replay), bits(&target_readout));
    }

    #[test]
    fn zero_in_vocabulary_prevents_mismatch_regression() {
        let op = operator(vec![vec![0]], 1, 1);
        let incidence = SupportIncidence::from_operator(&op);
        let initial = vec![1.0_f32];
        let initial_readout = readout::sequential(&op, &initial);
        let target = vec![nextafter32(1.0, false).unwrap()];
        let choice = optimize_coordinate(
            &op,
            &incidence,
            &initial,
            &initial_readout,
            &target,
            0,
        );
        assert!(choice.final_mismatch_count <= choice.initial_mismatch_count);
    }

    #[test]
    fn fixed_disjoint_set_matches_bruteforce_lexicographic_optimum() {
        let op = operator(vec![vec![0], vec![0, 0], vec![1], vec![1, 1]], 2, 1);
        let incidence = SupportIncidence::from_operator(&op);
        let initial = vec![1.0_f32, 1.25];
        let plus = nextafter32(initial[0], false).unwrap();
        let below_two = nextafter32(
            nextafter32(nextafter32(2.0_f32, true).unwrap(), true).unwrap(),
            true,
        )
        .unwrap();
        let target = vec![plus, below_two, 1.25, 2.5];
        let initial_readout = readout::sequential(&op, &initial);
        let choices = vec![
            optimize_coordinate(
                &op,
                &incidence,
                &initial,
                &initial_readout,
                &target,
                0,
            ),
            optimize_coordinate(
                &op,
                &incidence,
                &initial,
                &initial_readout,
                &target,
                1,
            ),
        ];
        assert_eq!(choices[0].selected_step, 1);
        assert!(choices[0].l2_increased_vs_initial);
        assert!(!choices[0].pareto_improvement);

        let mut brute: Option<(usize, f64, [i8; 2])> = None;
        for &step0 in &STEP_VOCABULARY {
            let Some(value0) = legal_replacement(initial[0], step0) else {
                continue;
            };
            for &step1 in &STEP_VOCABULARY {
                let Some(value1) = legal_replacement(initial[1], step1) else {
                    continue;
                };
                let candidate = vec![value0, value1];
                let actual = readout::sequential(&op, &candidate);
                let mismatches = actual
                    .iter()
                    .zip(&target)
                    .filter(|(a, t)| a.to_bits() != t.to_bits())
                    .count();
                let squared_error = actual
                    .iter()
                    .zip(&target)
                    .map(|(&a, &t)| {
                        let error = f64::from(a) - f64::from(t);
                        error * error
                    })
                    .sum::<f64>();
                let better_than_brute = brute.as_ref().map_or(true, |(old_mismatch, old_sq, _)| {
                    mismatches < *old_mismatch
                        || (mismatches == *old_mismatch
                            && squared_error.total_cmp(old_sq).is_lt())
                });
                if better_than_brute {
                    brute = Some((mismatches, squared_error, [step0, step1]));
                }
            }
        }
        let (_, _, brute_steps) = brute.unwrap();
        assert_eq!(
            [choices[0].selected_step, choices[1].selected_step],
            brute_steps
        );
    }

    #[test]
    fn support_metric_replay_has_no_hot_loop_allocations() {
        let op = operator(vec![vec![0, 1, 0], vec![1, 0]], 2, 1);
        let initial = vec![0.75_f32, 1.25];
        let target = readout::sequential(&op, &initial);
        let before = crate::allocations();
        for _ in 0..1024 {
            std::hint::black_box(support_metrics(
                &op,
                &[0, 1],
                &initial,
                &target,
                0,
                initial[0],
            ));
        }
        assert_eq!(crate::allocations(), before);
    }

    #[test]
    fn four_orders_are_deterministic_and_report_single_post_support() {
        let op = operator(vec![vec![0], vec![1], vec![2], vec![3]], 4, 2);
        let incidence = SupportIncidence::from_operator(&op);
        let sets = four_greedy_maximal_sets(&[0, 1, 2, 3], &incidence, 7, 11);
        let again = four_greedy_maximal_sets(&[0, 1, 2, 3], &incidence, 7, 11);
        for (left, right) in sets.iter().zip(&again) {
            assert_eq!(left.ordered_coordinates, right.ordered_coordinates);
            assert_eq!(left.selected_coordinates, right.selected_coordinates);
        }
        for coordinate in 0..4 {
            assert!(incidence.post_ids(coordinate, op.posts).len() <= 1);
            assert_eq!(incidence.cue_ids(coordinate, op.posts).len(), 1);
        }
    }
}
