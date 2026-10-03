use super::bank::{LegalMove, RowEffect};
use anyhow::{Result, ensure};
use hashbrown::HashMap;
use nalgebra::{DMatrix, DVector};
use serde::Serialize;

const RANK_MULTIPLIER: f64 = 1000.0;
const CAPACITY_TOLERANCE: f64 = 2.0e-10;
const COEFFICIENT_RESOLUTION: f64 = 1.0e-12;

#[derive(Clone, Debug, Serialize)]
pub struct Capacity {
    pub status: &'static str,
    pub rows: usize,
    pub legal_columns: usize,
    pub nonzero_columns: usize,
    pub unique_nonzero_columns: usize,
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
        return Ok(Capacity {
            status: "CAPACITY_ZERO_OR_EMPTY_BANK",
            rows,
            legal_columns: moves.len(),
            nonzero_columns: 0,
            unique_nonzero_columns: 0,
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
        });
    }

    // Duplicate columns are represented by one column scaled by sqrt(m).
    // This preserves the full-bank column space and its minimum-L2 solution.
    let matrix = DMatrix::from_fn(rows, columns.len(), |row, column| {
        let scale = (columns[column].multiplicity as f64).sqrt();
        columns[column]
            .effects
            .binary_search_by_key(&row, |effect| effect.row)
            .ok()
            .map_or(0.0, |at| columns[column].effects[at].value * scale)
    });
    let svd = matrix.svd(true, true);
    let singular = &svd.singular_values;
    let sigma_max = singular.iter().copied().fold(0.0, f64::max);
    let cutoff = sigma_max * rows.max(columns.len()) as f64 * f64::EPSILON * RANK_MULTIPLIER;
    let rank = singular.iter().filter(|&&sigma| sigma > cutoff).count();
    let u = svd.u.context("capacity SVD omitted U")?;
    let vt = svd.v_t.context("capacity SVD omitted Vt")?;
    let mut reachable = DVector::zeros(rows);
    let mut compressed_coefficients = vec![0.0; columns.len()];
    for k in 0..rank {
        let coefficient = u.column(k).dot(&error);
        reachable += u.column(k) * coefficient;
        let solve_coefficient = -coefficient / singular[k];
        for column in 0..columns.len() {
            compressed_coefficients[column] += vt[(k, column)] * solve_coefficient;
        }
    }
    let unreachable = &error - &reachable;
    let unreachable_norm = unreachable.norm();
    let normalized_unreachable = unreachable_norm / error_norm.max(1.0e-12);
    let mut relaxed_l1 = 0.0;
    let mut relaxed_l2_sq = 0.0;
    let mut relaxed_linf = 0.0_f64;
    let mut relaxed_nonzero = 0;
    for (coefficient, column) in compressed_coefficients.iter().zip(&columns) {
        let root = (column.multiplicity as f64).sqrt();
        let per_move = *coefficient / root;
        relaxed_l1 += per_move.abs() * column.multiplicity as f64;
        relaxed_l2_sq += per_move * per_move * column.multiplicity as f64;
        relaxed_linf = relaxed_linf.max(per_move.abs());
        if per_move.abs() > COEFFICIENT_RESOLUTION {
            relaxed_nonzero += column.multiplicity;
        }
    }
    let finite = [
        error_norm,
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

trait ContextOption<T> {
    fn context(self, message: &'static str) -> Result<T>;
}

impl<T> ContextOption<T> for Option<T> {
    fn context(self, message: &'static str) -> Result<T> {
        self.ok_or_else(|| anyhow::anyhow!(message))
    }
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
    }
}
