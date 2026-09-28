use super::readout::{interior_steps, nextafter32, replay_row_with_move};
use crate::linear::DriveOperator;
use anyhow::{Result, ensure};
use hashbrown::HashMap;
use serde::Serialize;
use sha2::{Digest, Sha256};

pub const FINAL_RESERVE: u32 = 16;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Direction {
    Down,
    Up,
}

impl Direction {
    #[inline]
    pub fn downward(self) -> bool {
        matches!(self, Self::Down)
    }

    #[inline]
    fn code(self) -> u8 {
        if self.downward() { 0 } else { 1 }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct RowEffect {
    pub row: usize,
    pub value: f64,
    pub committed_bits: u32,
}

#[derive(Clone, Debug, Serialize)]
pub struct LegalMove {
    pub coordinate: usize,
    pub direction: Direction,
    pub replacement_bits: u32,
    pub effects: Vec<RowEffect>,
}

impl LegalMove {
    pub fn replacement(&self) -> f32 {
        f32::from_bits(self.replacement_bits)
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct RowAuthority {
    pub movable: usize,
    pub high_slack: usize,
    pub positive: usize,
    pub negative: usize,
    pub zero: usize,
}

#[derive(Clone, Debug, Serialize)]
pub struct BankDiagnostics {
    pub attempted_moves: usize,
    pub legal_moves: usize,
    pub legal_down: usize,
    pub legal_up: usize,
    pub rejected_nonfinite_or_bounds: usize,
    pub rejected_reserve: usize,
    pub zero_effect_moves: usize,
    pub nonzero_effect_moves: usize,
    pub unique_nonzero_effects: usize,
    pub duplicate_nonzero_effects: usize,
    pub effect_entries: usize,
    pub minimum_remaining_down_steps_capped: u32,
    pub minimum_remaining_up_steps_capped: u32,
    pub provenance_sha256: String,
    pub row_authority: Vec<RowAuthority>,
}

pub struct MoveBank {
    pub moves: Vec<LegalMove>,
    pub coordinate_rows: Vec<Vec<usize>>,
    pub diagnostics: BankDiagnostics,
}

pub fn coordinate_rows(op: &DriveOperator) -> Vec<Vec<usize>> {
    let mut out = vec![Vec::new(); op.coordinates];
    for (row, ids) in op.rows.iter().enumerate() {
        for &coordinate in ids {
            if out[coordinate].last().copied() != Some(row) {
                out[coordinate].push(row);
            }
        }
    }
    out
}

fn signature(effects: &[RowEffect]) -> Vec<(usize, u64)> {
    effects
        .iter()
        .map(|effect| (effect.row, effect.value.to_bits()))
        .collect()
}

pub fn build(
    op: &DriveOperator,
    weights: &[f32],
    baseline: &[f32],
    interior: &[usize],
) -> Result<MoveBank> {
    ensure!(weights.len() == op.coordinates && baseline.len() == op.rows.len());
    ensure!(interior.windows(2).all(|pair| pair[0] < pair[1]));
    let coordinate_rows = coordinate_rows(op);
    let mut row_authority = vec![
        RowAuthority {
            movable: 0,
            high_slack: 0,
            positive: 0,
            negative: 0,
            zero: 0,
        };
        op.rows.len()
    ];
    for &coordinate in interior {
        let high_slack = interior_steps(weights[coordinate], true, 32) >= 32
            && interior_steps(weights[coordinate], false, 32) >= 32;
        for &row in &coordinate_rows[coordinate] {
            row_authority[row].movable += 1;
            row_authority[row].high_slack += usize::from(high_slack);
        }
    }

    let mut hasher = Sha256::new();
    let mut moves = Vec::with_capacity(interior.len() * 2);
    let mut legal_down = 0;
    let mut legal_up = 0;
    let mut rejected_bounds = 0;
    let mut rejected_reserve = 0;
    let mut zero_effect = 0;
    let mut effect_entries = 0;
    let mut minimum_down = 32;
    let mut minimum_up = 32;
    let mut unique = HashMap::<Vec<(usize, u64)>, usize>::new();

    for &coordinate in interior {
        let current = weights[coordinate];
        for direction in [Direction::Down, Direction::Up] {
            hasher.update((coordinate as u64).to_le_bytes());
            hasher.update([direction.code()]);
            let Some(replacement) = nextafter32(current, direction.downward()) else {
                rejected_bounds += 1;
                hasher.update([0]);
                continue;
            };
            if !replacement.is_finite() || replacement <= 0.0 || replacement >= 2.0 {
                rejected_bounds += 1;
                hasher.update([1]);
                continue;
            }
            let down_steps = interior_steps(replacement, true, FINAL_RESERVE);
            let up_steps = interior_steps(replacement, false, FINAL_RESERVE);
            if down_steps < FINAL_RESERVE || up_steps < FINAL_RESERVE {
                rejected_reserve += 1;
                hasher.update([2]);
                continue;
            }
            minimum_down = minimum_down.min(down_steps);
            minimum_up = minimum_up.min(up_steps);
            let mut effects = Vec::with_capacity(coordinate_rows[coordinate].len());
            for &row in &coordinate_rows[coordinate] {
                let committed = replay_row_with_move(op, row, weights, coordinate, replacement);
                let delta = f64::from(committed) - f64::from(baseline[row]);
                match delta.total_cmp(&0.0) {
                    std::cmp::Ordering::Greater => row_authority[row].positive += 1,
                    std::cmp::Ordering::Less => row_authority[row].negative += 1,
                    std::cmp::Ordering::Equal => row_authority[row].zero += 1,
                }
                if committed.to_bits() != baseline[row].to_bits() {
                    effects.push(RowEffect {
                        row,
                        value: delta,
                        committed_bits: committed.to_bits(),
                    });
                }
            }
            effects.sort_unstable_by_key(|effect| effect.row);
            hasher.update([3]);
            hasher.update(replacement.to_bits().to_le_bytes());
            hasher.update((effects.len() as u64).to_le_bytes());
            for effect in &effects {
                hasher.update((effect.row as u64).to_le_bytes());
                hasher.update(effect.value.to_bits().to_le_bytes());
                hasher.update(effect.committed_bits.to_le_bytes());
            }
            legal_down += usize::from(direction == Direction::Down);
            legal_up += usize::from(direction == Direction::Up);
            zero_effect += usize::from(effects.is_empty());
            effect_entries += effects.len();
            if !effects.is_empty() {
                *unique.entry(signature(&effects)).or_insert(0) += 1;
            }
            moves.push(LegalMove {
                coordinate,
                direction,
                replacement_bits: replacement.to_bits(),
                effects,
            });
        }
    }
    let nonzero = moves.len() - zero_effect;
    let unique_nonzero = unique.len();
    Ok(MoveBank {
        diagnostics: BankDiagnostics {
            attempted_moves: interior.len() * 2,
            legal_moves: moves.len(),
            legal_down,
            legal_up,
            rejected_nonfinite_or_bounds: rejected_bounds,
            rejected_reserve,
            zero_effect_moves: zero_effect,
            nonzero_effect_moves: nonzero,
            unique_nonzero_effects: unique_nonzero,
            duplicate_nonzero_effects: nonzero.saturating_sub(unique_nonzero),
            effect_entries,
            minimum_remaining_down_steps_capped: minimum_down,
            minimum_remaining_up_steps_capped: minimum_up,
            provenance_sha256: format!("{:x}", hasher.finalize()),
            row_authority,
        },
        moves,
        coordinate_rows,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn coordinate_rows_are_unique_and_ordered() {
        let op = DriveOperator {
            cues: 1,
            posts: 2,
            coordinates: 3,
            rows: vec![vec![0, 1, 1], vec![1, 2]],
        };
        assert_eq!(coordinate_rows(&op), vec![vec![0], vec![0, 1], vec![1]]);
    }
}
