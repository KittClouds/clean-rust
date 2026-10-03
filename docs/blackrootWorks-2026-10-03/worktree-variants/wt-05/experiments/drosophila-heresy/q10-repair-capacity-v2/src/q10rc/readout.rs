use super::types::{BaselineReceipt, CollateralReceipt, MoveBankReceipt, RowReceipts};
use crate::{capture::Snapshot, linear::DriveOperator};
use anyhow::{Result, ensure};
use sha2::{Digest, Sha256};

const WEIGHT_MIN: f32 = 0.0;
const WEIGHT_MAX: f32 = 2.0;
const POST_MOVE_RESERVE: u32 = 31;

#[derive(Clone)]
pub(crate) struct MoveColumn {
    pub coordinate: usize,
    pub direction: i8,
    pub post: usize,
    pub effects: [f64; 16],
}

pub(crate) struct MoveAudit {
    pub baseline: BaselineReceipt,
    pub bank: MoveBankReceipt,
    pub columns_by_post: Vec<Vec<MoveColumn>>,
    pub rows: RowReceipts,
    pub collateral: CollateralReceipt,
}

#[derive(Clone, Default)]
struct RowAccumulator {
    source: u32,
    permitted: u32,
    variable: u32,
    legal_minus: u32,
    legal_plus: u32,
    nonzero_minus: u32,
    nonzero_plus: u32,
    positive: u32,
    negative: u32,
    bitwise_zero: u32,
    helpful: u32,
    harmful: u32,
    max_abs: f64,
    positive_authority: f64,
    negative_authority: f64,
    best_reduction: f64,
}

pub(crate) struct ReadoutIndex {
    coord_rows: Vec<Vec<usize>>,
    posts: usize,
}

impl ReadoutIndex {
    pub fn new(op: &DriveOperator) -> Result<Self> {
        ensure!(op.cues == 16 && op.rows.len() == op.cues * op.posts);
        let mut coord_rows = vec![Vec::new(); op.coordinates];
        for (row, ids) in op.rows.iter().enumerate() {
            for &coordinate in ids {
                ensure!(coordinate < op.coordinates);
                coord_rows[coordinate].push(row);
            }
        }
        for rows in &coord_rows {
            if let Some(&first) = rows.first() {
                let post = first % op.posts;
                ensure!(rows.iter().all(|row| row % op.posts == post));
            }
        }
        Ok(Self {
            coord_rows,
            posts: op.posts,
        })
    }
}

#[inline]
fn sequential_row(weights: &[f32], ids: &[usize]) -> f32 {
    let mut sum = 0.0_f32;
    for &coordinate in ids {
        sum += weights[coordinate];
    }
    sum
}

#[inline]
fn sequential_row_with_override(
    weights: &[f32],
    ids: &[usize],
    coordinate: usize,
    replacement: f32,
) -> f32 {
    let mut sum = 0.0_f32;
    for &id in ids {
        sum += if id == coordinate {
            replacement
        } else {
            weights[id]
        };
    }
    sum
}

pub(crate) fn sequential(op: &DriveOperator, weights: &[f32]) -> Vec<f32> {
    assert_eq!(weights.len(), op.coordinates);
    op.rows
        .iter()
        .map(|ids| sequential_row(weights, ids))
        .collect()
}

#[inline]
fn nextafter32(value: f32, lower: bool) -> Option<f32> {
    if !value.is_finite() || value <= WEIGHT_MIN || value >= WEIGHT_MAX {
        return None;
    }
    let bits = value.to_bits();
    let next = if lower {
        f32::from_bits(bits.checked_sub(1)?)
    } else {
        f32::from_bits(bits.checked_add(1)?)
    };
    Some(next)
}

fn remaining_steps(value: f32, lower: bool, cap: u32) -> u32 {
    let mut current = value;
    let mut steps = 0;
    while steps < cap {
        let Some(next) = nextafter32(current, lower) else {
            break;
        };
        if !next.is_finite() || next <= WEIGHT_MIN || next >= WEIGHT_MAX {
            break;
        }
        current = next;
        steps += 1;
    }
    steps
}

fn ordered_f32(bits: u32) -> u32 {
    if bits & 0x8000_0000 != 0 {
        !bits
    } else {
        bits | 0x8000_0000
    }
}

fn ulp_distance(a: f32, b: f32) -> u64 {
    u64::from(ordered_f32(a.to_bits()).abs_diff(ordered_f32(b.to_bits())))
}

fn l2(values: &[f64]) -> f64 {
    values.iter().map(|x| x * x).sum::<f64>().sqrt()
}

fn build_baseline(op: &DriveOperator, alternate: &[f32], true_state: &[f32]) -> BaselineReceipt {
    let g_n = sequential(op, alternate);
    let g_t = sequential(op, true_state);
    let error: Vec<_> = g_n
        .iter()
        .zip(&g_t)
        .map(|(&n, &t)| f64::from(n) - f64::from(t))
        .collect();
    let bitwise_mismatch_count = g_n
        .iter()
        .zip(&g_t)
        .filter(|(n, t)| n.to_bits() != t.to_bits())
        .count();
    let signed_zero_mismatch_count = g_n
        .iter()
        .zip(&g_t)
        .filter(|(n, t)| **n == 0.0 && **t == 0.0 && n.to_bits() != t.to_bits())
        .count();
    BaselineReceipt {
        rows: error.len(),
        bitwise_mismatch_count,
        signed_zero_mismatch_count,
        error_l2: l2(&error),
        error_linf: error.iter().map(|x| x.abs()).fold(0.0, f64::max),
        alternate_bits: g_n.iter().map(|x| x.to_bits()).collect(),
        true_bits: g_t.iter().map(|x| x.to_bits()).collect(),
        error,
        ulp_distance: g_n
            .iter()
            .zip(&g_t)
            .map(|(&n, &t)| ulp_distance(n, t))
            .collect(),
    }
}

fn update_digest(
    digest: &mut Sha256,
    coordinate: usize,
    direction: i8,
    old: f32,
    new: Option<f32>,
    legality: u8,
    affected: &[(usize, f32)],
) {
    digest.update((coordinate as u64).to_le_bytes());
    digest.update(direction.to_le_bytes());
    digest.update(old.to_bits().to_le_bytes());
    digest.update(new.map_or(u32::MAX, f32::to_bits).to_le_bytes());
    digest.update([legality]);
    digest.update((affected.len() as u32).to_le_bytes());
    for &(row, output) in affected {
        digest.update((row as u32).to_le_bytes());
        digest.update(output.to_bits().to_le_bytes());
    }
}

#[allow(clippy::too_many_arguments)]
fn apply_row_effect(
    accumulator: &mut RowAccumulator,
    direction: i8,
    baseline_bits: u32,
    moved: f32,
    error: f64,
) -> f64 {
    if direction < 0 {
        accumulator.legal_minus += 1;
    } else {
        accumulator.legal_plus += 1;
    }
    if moved.to_bits() == baseline_bits {
        accumulator.bitwise_zero += 1;
        return 0.0;
    }
    let delta = f64::from(moved) - f64::from(f32::from_bits(baseline_bits));
    if direction < 0 {
        accumulator.nonzero_minus += 1;
    } else {
        accumulator.nonzero_plus += 1;
    }
    if delta > 0.0 {
        accumulator.positive += 1;
        accumulator.positive_authority += delta;
    } else if delta < 0.0 {
        accumulator.negative += 1;
        accumulator.negative_authority += -delta;
    }
    let before = error.abs();
    let after = (error + delta).abs();
    if after < before {
        accumulator.helpful += 1;
        accumulator.best_reduction = accumulator.best_reduction.max(before - after);
    } else if after > before {
        accumulator.harmful += 1;
    }
    accumulator.max_abs = accumulator.max_abs.max(delta.abs());
    delta
}

fn finish_rows(accumulators: Vec<RowAccumulator>, posts: usize, errors: &[f64]) -> RowReceipts {
    let mut out = RowReceipts::with_capacity(accumulators.len());
    for (row, value) in accumulators.into_iter().enumerate() {
        let error = errors[row];
        let zero_capacity = value.positive == 0 && value.negative == 0;
        let one_sided = !zero_capacity && (value.positive == 0 || value.negative == 0);
        let no_helpful = error != 0.0 && value.helpful == 0;
        let mut flags = 0;
        flags |= u8::from(zero_capacity) * super::types::FLAG_ZERO_CAPACITY;
        flags |= u8::from(one_sided) * super::types::FLAG_ONE_SIDED;
        flags |= u8::from(no_helpful) * super::types::FLAG_NO_HELPFUL;
        out.cue.push((row / posts) as u16);
        out.mbon.push((row % posts) as u16);
        out.source_coordinates.push(value.source);
        out.permitted_coordinates.push(value.permitted);
        out.variable_coordinates.push(value.variable);
        out.legal_minus.push(value.legal_minus);
        out.legal_plus.push(value.legal_plus);
        out.nonzero_minus.push(value.nonzero_minus);
        out.nonzero_plus.push(value.nonzero_plus);
        out.positive_effects.push(value.positive);
        out.negative_effects.push(value.negative);
        out.bitwise_zero_effects.push(value.bitwise_zero);
        out.helpful_effects.push(value.helpful);
        out.harmful_effects.push(value.harmful);
        out.max_abs_single_effect.push(value.max_abs);
        out.summed_positive_authority.push(value.positive_authority);
        out.summed_absolute_negative_authority
            .push(value.negative_authority);
        out.best_single_reduction_fraction.push(if error != 0.0 {
            value.best_reduction / error.abs()
        } else {
            0.0
        });
        out.flags.push(flags);
    }
    out
}

pub(crate) fn audit_moves(
    op: &DriveOperator,
    index: &ReadoutIndex,
    snapshot: &Snapshot,
    alternate: &[f32],
    interior: &[usize],
) -> Result<MoveAudit> {
    ensure!(alternate.len() == op.coordinates && snapshot.target.len() == op.coordinates);
    let baseline = build_baseline(op, alternate, &snapshot.target);
    let mut variable = vec![false; op.coordinates];
    for &coordinate in interior {
        ensure!(coordinate < variable.len() && snapshot.permitted[coordinate]);
        variable[coordinate] = true;
    }
    let mut row_accumulators = vec![RowAccumulator::default(); op.rows.len()];
    for (row, ids) in op.rows.iter().enumerate() {
        row_accumulators[row].source = ids.len() as u32;
        row_accumulators[row].permitted = ids
            .iter()
            .filter(|&&coordinate| snapshot.permitted[coordinate])
            .count() as u32;
        row_accumulators[row].variable = ids
            .iter()
            .filter(|&&coordinate| variable[coordinate])
            .count() as u32;
    }

    let baseline_displacement: Vec<_> = alternate
        .iter()
        .zip(&snapshot.base)
        .map(|(&n, &b)| f64::from(n) - f64::from(b))
        .collect();
    let baseline_norm_sq: f64 = baseline_displacement.iter().map(|x| x * x).sum();
    let baseline_norm = baseline_norm_sq.sqrt();
    let mut digest = Sha256::new();
    let mut columns_by_post = vec![Vec::new(); index.posts];
    let mut legal_moves = 0;
    let mut zero_effect_moves = 0;
    let mut active_moves = 0;
    let mut numerical_nonzero_moves = 0;
    let mut minus_legal = 0;
    let mut plus_legal = 0;
    let mut illegal_non_adjacent = 0;
    let mut illegal_nonfinite_or_bounds = 0;
    let mut illegal_boundary = 0;
    let mut illegal_reserve = 0;
    let mut minimum_down = POST_MOVE_RESERVE;
    let mut minimum_up = POST_MOVE_RESERVE;
    let mut axis_abs_sum = 0.0;
    let mut norm_abs_sum = 0.0;
    let mut max_axis = 0.0_f64;
    let mut max_norm = 0.0_f64;

    for &coordinate in interior {
        let old = alternate[coordinate];
        for direction in [-1_i8, 1_i8] {
            let candidate = nextafter32(old, direction < 0);
            let mut legality = 0_u8;
            let mut affected = Vec::new();
            let Some(new) = candidate else {
                legality = 1;
                illegal_non_adjacent += 1;
                update_digest(
                    &mut digest,
                    coordinate,
                    direction,
                    old,
                    None,
                    legality,
                    &affected,
                );
                continue;
            };
            if !new.is_finite() || new <= WEIGHT_MIN || new >= WEIGHT_MAX {
                legality = 2;
                illegal_nonfinite_or_bounds += 1;
            } else if new == WEIGHT_MIN || new == WEIGHT_MAX {
                legality = 3;
                illegal_boundary += 1;
            }
            let down = remaining_steps(new, true, POST_MOVE_RESERVE);
            let up = remaining_steps(new, false, POST_MOVE_RESERVE);
            if legality == 0 && (down < POST_MOVE_RESERVE || up < POST_MOVE_RESERVE) {
                legality = 4;
                illegal_reserve += 1;
            }
            if legality != 0 {
                update_digest(
                    &mut digest,
                    coordinate,
                    direction,
                    old,
                    Some(new),
                    legality,
                    &affected,
                );
                continue;
            }

            legal_moves += 1;
            minus_legal += usize::from(direction < 0);
            plus_legal += usize::from(direction > 0);
            minimum_down = minimum_down.min(down);
            minimum_up = minimum_up.min(up);
            let rows = &index.coord_rows[coordinate];
            let post = rows.first().map_or(0, |row| row % index.posts);
            let mut effects = [0.0_f64; 16];
            let mut bitwise_changed = false;
            let mut numerically_changed = false;
            for &row in rows {
                let moved = sequential_row_with_override(alternate, &op.rows[row], coordinate, new);
                affected.push((row, moved));
                let cue = row / index.posts;
                let delta = apply_row_effect(
                    &mut row_accumulators[row],
                    direction,
                    baseline.alternate_bits[row],
                    moved,
                    baseline.error[row],
                );
                effects[cue] = delta;
                bitwise_changed |= moved.to_bits() != baseline.alternate_bits[row];
                numerically_changed |= delta != 0.0;
            }
            if bitwise_changed {
                active_moves += 1;
                numerical_nonzero_moves += usize::from(numerically_changed);
                columns_by_post[post].push(MoveColumn {
                    coordinate,
                    direction,
                    post,
                    effects,
                });
            } else {
                zero_effect_moves += 1;
            }
            let old_d = baseline_displacement[coordinate];
            let new_d = f64::from(new) - f64::from(snapshot.base[coordinate]);
            let axis_delta = (new_d - old_d) * snapshot.axis[coordinate];
            let moved_norm = (baseline_norm_sq - old_d * old_d + new_d * new_d).sqrt();
            let norm_delta = moved_norm - baseline_norm;
            axis_abs_sum += axis_delta.abs();
            norm_abs_sum += norm_delta.abs();
            max_axis = max_axis.max(axis_delta.abs());
            max_norm = max_norm.max(norm_delta.abs());
            update_digest(
                &mut digest,
                coordinate,
                direction,
                old,
                Some(new),
                legality,
                &affected,
            );
        }
    }
    ensure!(
        legal_moves
            + illegal_non_adjacent
            + illegal_nonfinite_or_bounds
            + illegal_boundary
            + illegal_reserve
            == interior.len() * 2
    );
    ensure!(active_moves + zero_effect_moves == legal_moves);
    let rows = finish_rows(row_accumulators, index.posts, &baseline.error);
    let denominator = legal_moves.max(1) as f64;
    Ok(MoveAudit {
        baseline,
        bank: MoveBankReceipt {
            candidate_moves: interior.len() * 2,
            legal_moves,
            illegal_non_adjacent,
            illegal_nonfinite_or_bounds,
            illegal_boundary,
            illegal_reserve,
            zero_effect_moves,
            active_moves,
            numerical_nonzero_moves,
            minus_legal,
            plus_legal,
            move_digest_sha256: format!("{:x}", digest.finalize()),
            minimum_remaining_down_steps_capped: minimum_down,
            minimum_remaining_up_steps_capped: minimum_up,
        },
        columns_by_post,
        rows,
        collateral: CollateralReceipt {
            max_abs_axis_delta: max_axis,
            max_abs_norm_delta: max_norm,
            mean_abs_axis_delta: axis_abs_sum / denominator,
            mean_abs_norm_delta: norm_abs_sum / denominator,
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{graph::Graph, task::Task};

    #[test]
    fn scalar_readout_matches_frozen_operator_order() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 77, 16, 12, 32);
        let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len()).unwrap();
        let weights: Vec<_> = (0..op.coordinates)
            .map(|i| (i % 31) as f32 * 0.001)
            .collect();
        assert_eq!(sequential(&op, &weights), op.sequential(&weights));
    }

    #[test]
    fn one_step_leaves_declared_reserve() {
        let value = 1.0_f32;
        for lower in [true, false] {
            let moved = nextafter32(value, lower).unwrap();
            assert!(remaining_steps(moved, true, POST_MOVE_RESERVE) >= POST_MOVE_RESERVE);
            assert!(remaining_steps(moved, false, POST_MOVE_RESERVE) >= POST_MOVE_RESERVE);
        }
    }

    #[test]
    fn ordered_ulp_distance_is_exact_for_neighbors() {
        let value = 1.0_f32;
        assert_eq!(ulp_distance(value, nextafter32(value, true).unwrap()), 1);
        assert_eq!(ulp_distance(value, nextafter32(value, false).unwrap()), 1);
    }
}
