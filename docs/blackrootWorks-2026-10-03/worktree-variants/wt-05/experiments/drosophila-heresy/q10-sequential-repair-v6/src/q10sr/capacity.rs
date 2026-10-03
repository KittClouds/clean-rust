use super::bank::{FINAL_RESERVE, LegalMove, RowEffect, coordinate_rows};
use super::readout::{interior_steps, nextafter32, replay_row_with_move};
use crate::linear::DriveOperator;
use anyhow::{Result, ensure};
use hashbrown::HashMap;
use nalgebra::{DMatrix, DVector, linalg::SymmetricEigen};
use serde::Serialize;

const RANK_MULTIPLIER: f64 = 1000.0;
const CAPACITY_TOLERANCE: f64 = 2.0e-10;
const COEFFICIENT_RESOLUTION: f64 = 1.0e-12;
const CAPACITY_STEPS: u8 = 16;

#[derive(Clone, Debug, Serialize)]
pub struct Capacity {
    pub status: &'static str,
    pub rows: usize,
    pub legal_columns: usize,
    pub nonzero_columns: usize,
    pub unique_nonzero_columns: usize,
    pub columns_materialized: bool,
    pub rank: usize,
    pub cutoff: f64,
    pub error_norm: f64,
    pub reachable_norm: f64,
    pub unreachable_norm: f64,
    pub normalized_unreachable: f64,
    pub relaxed_l1: f64,
    pub relaxed_l2: f64,
    pub relaxed_linf: f64,
    pub relaxed_nonzero_coefficients: usize,
    pub relaxed_l1_over_move_budget: f64,
    pub relaxed_linf_over_coordinate_budget: f64,
}

#[derive(Clone)]
struct UniqueColumn {
    effects: Vec<RowEffect>,
    multiplicity: usize,
}

fn signature(effects: &[RowEffect]) -> Vec<(usize, u64)> {
    effects
        .iter()
        .map(|effect| (effect.row, effect.value.to_bits()))
        .collect()
}

fn unique_columns(moves: &[LegalMove]) -> Vec<UniqueColumn> {
    let mut lookup = HashMap::<Vec<(usize, u64)>, usize>::new();
    let mut columns = Vec::<UniqueColumn>::new();
    for movement in moves.iter().filter(|movement| !movement.effects.is_empty()) {
        let key = signature(&movement.effects);
        if let Some(&column) = lookup.get(&key) {
            columns[column].multiplicity += 1;
        } else {
            let column = columns.len();
            lookup.insert(key, column);
            columns.push(UniqueColumn {
                effects: movement.effects.clone(),
                multiplicity: 1,
            });
        }
    }
    columns
}

fn empty_capacity(rows: usize, legal_columns: usize, error_norm: f64) -> Capacity {
    Capacity {
        status: "CAPACITY_ZERO_OR_EMPTY_BANK",
        rows,
        legal_columns,
        nonzero_columns: 0,
        unique_nonzero_columns: 0,
        columns_materialized: true,
        rank: 0,
        cutoff: 0.0,
        error_norm,
        reachable_norm: 0.0,
        unreachable_norm: error_norm,
        normalized_unreachable: error_norm / error_norm.max(1.0e-12),
        relaxed_l1: 0.0,
        relaxed_l2: 0.0,
        relaxed_linf: 0.0,
        relaxed_nonzero_coefficients: 0,
        relaxed_l1_over_move_budget: 0.0,
        relaxed_linf_over_coordinate_budget: 0.0,
    }
}

pub fn analyze(moves: &[LegalMove], actual: &[f32], target: &[f32]) -> Result<Capacity> {
    ensure!(actual.len() == target.len());
    let rows = actual.len();
    let error = DVector::from_iterator(
        rows,
        actual
            .iter()
            .zip(target)
            .map(|(&a, &t)| f64::from(a) - f64::from(t)),
    );
    let error_norm = error.norm();
    let columns = unique_columns(moves);
    let nonzero_columns = columns.iter().map(|column| column.multiplicity).sum();
    if columns.is_empty() {
        return Ok(empty_capacity(rows, moves.len(), error_norm));
    }

    // Work in readout space. If A is the full move-effect matrix, the
    // symmetric Gram matrix G = A A^T has the same nonzero left singular
    // subspace as A, but its dimension is the number of readout rows (784 in
    // the real anatomy) rather than the number of ULP moves (often 15k+).
    // Duplicate columns are represented by their multiplicity in G.
    let mut gram = DMatrix::<f64>::zeros(rows, rows);
    for column in &columns {
        let multiplicity = column.multiplicity as f64;
        for left in &column.effects {
            for right in &column.effects {
                gram[(left.row, right.row)] += multiplicity * left.value * right.value;
            }
        }
    }

    let eigen = SymmetricEigen::new(gram);
    let sigma_max = eigen
        .eigenvalues
        .iter()
        .copied()
        .map(|value| value.max(0.0).sqrt())
        .fold(0.0, f64::max);
    let cutoff = sigma_max * rows.max(columns.len()) as f64 * f64::EPSILON * RANK_MULTIPLIER;
    let cutoff_squared = cutoff * cutoff;
    let active = eigen
        .eigenvalues
        .iter()
        .map(|&value| value > cutoff_squared && value.is_finite())
        .collect::<Vec<_>>();
    let rank = active.iter().filter(|&&is_active| is_active).count();

    let mut reachable = DVector::zeros(rows);
    for (index, &is_active) in active.iter().enumerate() {
        if is_active {
            let projection = eigen.eigenvectors.column(index).dot(&error);
            reachable += eigen.eigenvectors.column(index) * projection;
        }
    }
    let unreachable = &error - &reachable;
    let unreachable_norm = unreachable.norm();
    let normalized_unreachable = unreachable_norm / error_norm.max(1.0e-12);

    // For exact events only, recover the minimum-L2 relaxed full-bank move
    // coefficients. For an effect column e with multiplicity m, the
    // duplicated full matrix is equivalent to a compressed column sqrt(m)e.
    // Its minimum-norm coefficient per original move is therefore:
    //   -sum_k (u_k . error) (e . u_k) / lambda_k.
    // Partial events are fail-closed by the caller and do not need this
    // expensive diagnostic; leaving it zero also keeps the hot path bounded.
    let mut relaxed_l1 = 0.0;
    let mut relaxed_l2_sq = 0.0;
    let mut relaxed_linf = 0.0_f64;
    let mut relaxed_nonzero = 0;
    if rank > 0 && normalized_unreachable <= CAPACITY_TOLERANCE {
        for column in &columns {
            let mut per_move = 0.0;
            for (index, &is_active) in active.iter().enumerate() {
                if is_active {
                    let eigenvalue = eigen.eigenvalues[index];
                    let projection = eigen.eigenvectors.column(index).dot(&error);
                    let effect_projection = column
                        .effects
                        .iter()
                        .map(|effect| effect.value * eigen.eigenvectors[(effect.row, index)])
                        .sum::<f64>();
                    per_move -= projection * effect_projection / eigenvalue;
                }
            }
            relaxed_l1 += per_move.abs() * column.multiplicity as f64;
            relaxed_l2_sq += per_move * per_move * column.multiplicity as f64;
            relaxed_linf = relaxed_linf.max(per_move.abs());
            if per_move.abs() > COEFFICIENT_RESOLUTION {
                relaxed_nonzero += column.multiplicity;
            }
        }
    }

    let finite = [
        error_norm,
        reachable.norm(),
        unreachable_norm,
        normalized_unreachable,
        relaxed_l1,
        relaxed_l2_sq,
        relaxed_linf,
    ]
    .into_iter()
    .all(f64::is_finite);
    let status = if !finite {
        "CAPACITY_NUMERICALLY_AMBIGUOUS"
    } else if normalized_unreachable <= CAPACITY_TOLERANCE {
        "CAPACITY_EXACT_WITHIN_TOLERANCE"
    } else {
        "CAPACITY_PARTIAL"
    };
    Ok(Capacity {
        status,
        rows,
        legal_columns: moves.len(),
        nonzero_columns,
        unique_nonzero_columns: columns.len(),
        columns_materialized: true,
        rank,
        cutoff,
        error_norm,
        reachable_norm: reachable.norm(),
        unreachable_norm,
        normalized_unreachable,
        relaxed_l1,
        relaxed_l2: relaxed_l2_sq.sqrt(),
        relaxed_linf,
        relaxed_nonzero_coefficients: relaxed_nonzero,
        relaxed_l1_over_move_budget: relaxed_l1 / 64.0,
        relaxed_linf_over_coordinate_budget: relaxed_linf / 16.0,
    })
}

pub fn analyze_multistep(
    op: &DriveOperator,
    weights: &[f32],
    baseline: &[f32],
    actual: &[f32],
    target: &[f32],
    interior: &[usize],
) -> Result<Capacity> {
    ensure!(weights.len() == op.coordinates);
    ensure!(baseline.len() == op.rows.len());
    ensure!(actual.len() == target.len() && actual.len() == op.rows.len());
    let rows = actual.len();
    let error = DVector::from_iterator(
        rows,
        actual
            .iter()
            .zip(target)
            .map(|(&a, &t)| f64::from(a) - f64::from(t)),
    );
    let error_norm = error.norm();
    let coordinate_rows = coordinate_rows(op);
    let mut gram = DMatrix::<f64>::zeros(rows, rows);
    let mut legal_columns = 0;
    let mut nonzero_columns = 0;

    // Stream each legal committed position directly into A A^T. This keeps
    // the multi-step audit's memory bounded by readout rows instead of
    // materializing up to 32 effect vectors per interior coordinate.
    for &coordinate in interior {
        let current = weights[coordinate];
        for direction in [
            super::bank::Direction::Down,
            super::bank::Direction::Up,
        ] {
            let mut replacement = current;
            for _step in 1..=CAPACITY_STEPS {
                let Some(next) = nextafter32(replacement, direction.downward()) else {
                    break;
                };
                replacement = next;
                if !replacement.is_finite()
                    || replacement <= 0.0
                    || replacement >= 2.0
                    || interior_steps(replacement, true, FINAL_RESERVE) < FINAL_RESERVE
                    || interior_steps(replacement, false, FINAL_RESERVE) < FINAL_RESERVE
                {
                    break;
                }
                legal_columns += 1;
                let mut effects = Vec::with_capacity(coordinate_rows[coordinate].len());
                for &row in &coordinate_rows[coordinate] {
                    let committed = replay_row_with_move(
                        op,
                        row,
                        weights,
                        coordinate,
                        replacement,
                    );
                    if committed.to_bits() != baseline[row].to_bits() {
                        effects.push((row, f64::from(committed) - f64::from(baseline[row])));
                    }
                }
                if effects.is_empty() {
                    continue;
                }
                nonzero_columns += 1;
                for &(left_row, left_value) in &effects {
                    for &(right_row, right_value) in &effects {
                        gram[(left_row, right_row)] += left_value * right_value;
                    }
                }
            }
        }
    }

    if legal_columns == 0 {
        return Ok(empty_capacity(rows, 0, error_norm));
    }
    let eigen = SymmetricEigen::new(gram);
    let sigma_max = eigen
        .eigenvalues
        .iter()
        .copied()
        .map(|value| value.max(0.0).sqrt())
        .fold(0.0, f64::max);
    let cutoff = sigma_max * rows.max(legal_columns) as f64 * f64::EPSILON * RANK_MULTIPLIER;
    let cutoff_squared = cutoff * cutoff;
    let mut reachable = DVector::zeros(rows);
    let mut rank = 0;
    for (index, &value) in eigen.eigenvalues.iter().enumerate() {
        if value > cutoff_squared && value.is_finite() {
            rank += 1;
            let projection = eigen.eigenvectors.column(index).dot(&error);
            reachable += eigen.eigenvectors.column(index) * projection;
        }
    }
    let unreachable = &error - &reachable;
    let unreachable_norm = unreachable.norm();
    let normalized_unreachable = unreachable_norm / error_norm.max(1.0e-12);
    let finite = [
        error_norm,
        reachable.norm(),
        unreachable_norm,
        normalized_unreachable,
    ]
    .into_iter()
    .all(f64::is_finite);
    let status = if !finite {
        "CAPACITY_NUMERICALLY_AMBIGUOUS"
    } else if normalized_unreachable <= CAPACITY_TOLERANCE {
        "CAPACITY_EXACT_WITHIN_TOLERANCE"
    } else {
        "CAPACITY_PARTIAL"
    };
    Ok(Capacity {
        status,
        rows,
        legal_columns,
        nonzero_columns,
        unique_nonzero_columns: 0,
        columns_materialized: false,
        rank,
        cutoff,
        error_norm,
        reachable_norm: reachable.norm(),
        unreachable_norm,
        normalized_unreachable,
        relaxed_l1: 0.0,
        relaxed_l2: 0.0,
        relaxed_linf: 0.0,
        relaxed_nonzero_coefficients: 0,
        relaxed_l1_over_move_budget: 0.0,
        relaxed_linf_over_coordinate_budget: 0.0,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::q10sr::bank::Direction;

    fn movement(row: usize, value: f64) -> LegalMove {
        LegalMove {
            coordinate: row,
            direction: Direction::Up,
            replacement_bits: 1.0f32.to_bits() + 1,
            effects: vec![RowEffect {
                row,
                value,
                committed_bits: 1.0f32.to_bits() + 1,
            }],
        }
    }

    #[test]
    fn capacity_detects_a_spanned_error() {
        let result = analyze(
            &[movement(0, 1.0), movement(1, 1.0)],
            &[1.0, 2.0],
            &[0.0, 0.0],
        )
        .unwrap();
        assert_eq!(result.rank, 2);
        assert_eq!(result.status, "CAPACITY_EXACT_WITHIN_TOLERANCE");
        assert!(result.unreachable_norm < 1.0e-12);
        assert!((result.relaxed_l2 - 5.0_f64.sqrt()).abs() < 1.0e-10);
    }

    #[test]
    fn capacity_detects_an_unspanned_error() {
        let result = analyze(&[movement(0, 1.0)], &[1.0, 1.0], &[0.0, 0.0]).unwrap();
        assert_eq!(result.rank, 1);
        assert_eq!(result.status, "CAPACITY_PARTIAL");
        assert!(result.unreachable_norm > 0.9);
    }
}
