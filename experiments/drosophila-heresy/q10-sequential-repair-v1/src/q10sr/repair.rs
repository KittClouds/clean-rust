use super::{
    bank::{Direction, FINAL_RESERVE, coordinate_rows},
    readout::{
        Mismatch, interior_steps, mismatch, nextafter32, replay_row_with_move, ulp_distance,
    },
};
use crate::linear::DriveOperator;
use anyhow::{Result, ensure};
use hashbrown::HashMap;
use serde::Serialize;
use std::cmp::Ordering;

const BEAM_WIDTH: usize = 64;
const BRANCH_WIDTH: usize = 64;
const MAX_DEPTH: usize = 64;
const MAX_COORDINATE_STEPS: i8 = 16;

#[derive(Clone, Debug, Serialize)]
pub struct AppliedMove {
    pub coordinate: usize,
    pub direction: Direction,
    pub before_bits: u32,
    pub after_bits: u32,
}

#[derive(Clone, Debug, Serialize)]
pub struct SearchDiagnostics {
    pub entered: bool,
    pub exact_readout_found: bool,
    pub depth_reached: usize,
    pub states_expanded: usize,
    pub legal_successors_enumerated: usize,
    pub branch_successors_retained: usize,
    pub globally_unique_states_retained: usize,
    pub immediate_inverse_rejections: usize,
    pub coordinate_budget_rejections: usize,
    pub reserve_rejections: usize,
    pub path: Vec<AppliedMove>,
}

pub struct SearchResult {
    pub weights: Option<Vec<f32>>,
    pub readout: Option<Vec<f32>>,
    pub diagnostics: SearchDiagnostics,
}

#[derive(Clone, Debug)]
struct Objective {
    mismatches: usize,
    max_ulp: u64,
    sum_ulp: u64,
    squared_error: f64,
    moves: usize,
    max_coordinate_steps: i8,
}

impl Objective {
    fn from_mismatch(value: &Mismatch, moves: usize, max_coordinate_steps: i8) -> Self {
        Self {
            mismatches: value.bitwise_mismatch_count,
            max_ulp: value.maximum_ulp_distance,
            sum_ulp: value.sum_ulp_distances,
            squared_error: value.squared_error,
            moves,
            max_coordinate_steps,
        }
    }

    fn compare(&self, other: &Self) -> Ordering {
        self.mismatches
            .cmp(&other.mismatches)
            .then_with(|| self.max_ulp.cmp(&other.max_ulp))
            .then_with(|| self.sum_ulp.cmp(&other.sum_ulp))
            .then_with(|| self.squared_error.total_cmp(&other.squared_error))
            .then_with(|| self.moves.cmp(&other.moves))
            .then_with(|| self.max_coordinate_steps.cmp(&other.max_coordinate_steps))
    }
}

#[derive(Clone)]
struct BeamState {
    weights: Vec<f32>,
    readout: Vec<f32>,
    offsets: Vec<(usize, i8)>,
    path: Vec<AppliedMove>,
    objective: Objective,
}

#[derive(Clone)]
struct Candidate {
    coordinate: usize,
    direction: Direction,
    replacement: f32,
    updates: Vec<(usize, f32)>,
    next_offset: i8,
    objective: Objective,
}

fn offset_at(offsets: &[(usize, i8)], coordinate: usize) -> i8 {
    offsets
        .binary_search_by_key(&coordinate, |&(index, _)| index)
        .ok()
        .map_or(0, |at| offsets[at].1)
}

fn set_offset(offsets: &mut Vec<(usize, i8)>, coordinate: usize, value: i8) {
    match offsets.binary_search_by_key(&coordinate, |&(index, _)| index) {
        Ok(at) if value == 0 => {
            offsets.remove(at);
        }
        Ok(at) => offsets[at].1 = value,
        Err(at) if value != 0 => offsets.insert(at, (coordinate, value)),
        Err(_) => {}
    }
}

fn row_is_updated(updates: &[(usize, f32)], row: usize) -> bool {
    updates
        .binary_search_by_key(&row, |&(index, _)| index)
        .is_ok()
}

fn successor_objective(
    state: &BeamState,
    target: &[f32],
    updates: &[(usize, f32)],
    next_offset: i8,
) -> Objective {
    let mut mismatches = state.objective.mismatches;
    let mut sum_ulp = state.objective.sum_ulp;
    let mut squared_error = state.objective.squared_error;
    let mut ranking: Vec<_> = state
        .readout
        .iter()
        .zip(target)
        .enumerate()
        .map(|(row, (&actual, &truth))| (ulp_distance(actual, truth), row))
        .collect();
    ranking.sort_unstable_by(|a, b| b.cmp(a));
    let unaffected_max = ranking
        .iter()
        .find(|(_, row)| !row_is_updated(updates, *row))
        .map_or(0, |(distance, _)| *distance);
    let mut changed_max = 0;
    for &(row, value) in updates {
        let old = state.readout[row];
        let truth = target[row];
        mismatches = mismatches - usize::from(old.to_bits() != truth.to_bits())
            + usize::from(value.to_bits() != truth.to_bits());
        let old_distance = ulp_distance(old, truth);
        let new_distance = ulp_distance(value, truth);
        sum_ulp = sum_ulp - old_distance + new_distance;
        changed_max = changed_max.max(new_distance);
        let old_error = f64::from(old) - f64::from(truth);
        let new_error = f64::from(value) - f64::from(truth);
        squared_error += new_error * new_error - old_error * old_error;
    }
    Objective {
        mismatches,
        max_ulp: unaffected_max.max(changed_max),
        sum_ulp,
        squared_error: squared_error.max(0.0),
        moves: state.path.len() + 1,
        max_coordinate_steps: state.objective.max_coordinate_steps.max(next_offset.abs()),
    }
}

fn compare_candidates(a: &Candidate, b: &Candidate) -> Ordering {
    a.objective
        .compare(&b.objective)
        .then_with(|| a.coordinate.cmp(&b.coordinate))
        .then_with(|| {
            usize::from(a.direction == Direction::Up)
                .cmp(&usize::from(b.direction == Direction::Up))
        })
}

fn compare_states(a: &BeamState, b: &BeamState) -> Ordering {
    a.objective.compare(&b.objective).then_with(|| {
        a.weights
            .iter()
            .map(|value| value.to_bits())
            .cmp(b.weights.iter().map(|value| value.to_bits()))
    })
}

fn enumerate_candidates(
    op: &DriveOperator,
    coordinate_rows: &[Vec<usize>],
    interior: &[usize],
    target: &[f32],
    state: &BeamState,
    diagnostics: &mut SearchDiagnostics,
) -> Vec<Candidate> {
    let last = state.path.last();
    let mut candidates = Vec::with_capacity(interior.len() * 2);
    for &coordinate in interior {
        let current_offset = offset_at(&state.offsets, coordinate);
        for direction in [Direction::Down, Direction::Up] {
            if last.is_some_and(|movement| {
                movement.coordinate == coordinate && movement.direction != direction
            }) {
                diagnostics.immediate_inverse_rejections += 1;
                continue;
            }
            let step = if direction == Direction::Down { -1 } else { 1 };
            let next_offset = current_offset + step;
            if next_offset.abs() > MAX_COORDINATE_STEPS {
                diagnostics.coordinate_budget_rejections += 1;
                continue;
            }
            let Some(replacement) = nextafter32(state.weights[coordinate], direction.downward())
            else {
                diagnostics.reserve_rejections += 1;
                continue;
            };
            if !replacement.is_finite()
                || replacement <= 0.0
                || replacement >= 2.0
                || interior_steps(replacement, true, FINAL_RESERVE) < FINAL_RESERVE
                || interior_steps(replacement, false, FINAL_RESERVE) < FINAL_RESERVE
            {
                diagnostics.reserve_rejections += 1;
                continue;
            }
            let mut updates = Vec::with_capacity(coordinate_rows[coordinate].len());
            for &row in &coordinate_rows[coordinate] {
                let value = replay_row_with_move(op, row, &state.weights, coordinate, replacement);
                if value.to_bits() != state.readout[row].to_bits() {
                    updates.push((row, value));
                }
            }
            diagnostics.legal_successors_enumerated += 1;
            let objective = successor_objective(state, target, &updates, next_offset);
            candidates.push(Candidate {
                coordinate,
                direction,
                replacement,
                updates,
                next_offset,
                objective,
            });
        }
    }
    candidates.sort_unstable_by(compare_candidates);
    candidates.truncate(BRANCH_WIDTH);
    diagnostics.branch_successors_retained += candidates.len();
    candidates
}

fn apply_candidate(state: &BeamState, candidate: Candidate) -> BeamState {
    let mut weights = state.weights.clone();
    let before_bits = weights[candidate.coordinate].to_bits();
    weights[candidate.coordinate] = candidate.replacement;
    let mut readout = state.readout.clone();
    for &(row, value) in &candidate.updates {
        readout[row] = value;
    }
    let mut offsets = state.offsets.clone();
    set_offset(&mut offsets, candidate.coordinate, candidate.next_offset);
    let mut path = state.path.clone();
    path.push(AppliedMove {
        coordinate: candidate.coordinate,
        direction: candidate.direction,
        before_bits,
        after_bits: candidate.replacement.to_bits(),
    });
    BeamState {
        weights,
        readout,
        offsets,
        path,
        objective: candidate.objective,
    }
}

pub fn search(
    op: &DriveOperator,
    initial_weights: &[f32],
    initial_readout: &[f32],
    target: &[f32],
    interior: &[usize],
) -> Result<SearchResult> {
    ensure!(initial_weights.len() == op.coordinates);
    ensure!(initial_readout.len() == target.len() && target.len() == op.rows.len());
    let initial_mismatch = mismatch(op, initial_readout, target)?;
    if initial_mismatch.bitwise_mismatch_count == 0 {
        return Ok(SearchResult {
            weights: Some(initial_weights.to_vec()),
            readout: Some(initial_readout.to_vec()),
            diagnostics: SearchDiagnostics {
                entered: false,
                exact_readout_found: true,
                depth_reached: 0,
                states_expanded: 0,
                legal_successors_enumerated: 0,
                branch_successors_retained: 0,
                globally_unique_states_retained: 0,
                immediate_inverse_rejections: 0,
                coordinate_budget_rejections: 0,
                reserve_rejections: 0,
                path: Vec::new(),
            },
        });
    }
    let coordinate_rows = coordinate_rows(op);
    let mut diagnostics = SearchDiagnostics {
        entered: true,
        exact_readout_found: false,
        depth_reached: 0,
        states_expanded: 0,
        legal_successors_enumerated: 0,
        branch_successors_retained: 0,
        globally_unique_states_retained: 0,
        immediate_inverse_rejections: 0,
        coordinate_budget_rejections: 0,
        reserve_rejections: 0,
        path: Vec::new(),
    };
    let mut beam = vec![BeamState {
        weights: initial_weights.to_vec(),
        readout: initial_readout.to_vec(),
        offsets: Vec::new(),
        path: Vec::new(),
        objective: Objective::from_mismatch(&initial_mismatch, 0, 0),
    }];
    let mut seen = HashMap::<Vec<(usize, i8)>, usize>::new();
    seen.insert(Vec::new(), 0);
    for depth in 1..=MAX_DEPTH {
        diagnostics.depth_reached = depth;
        let mut next = Vec::new();
        for state in &beam {
            diagnostics.states_expanded += 1;
            for candidate in enumerate_candidates(
                op,
                &coordinate_rows,
                interior,
                target,
                state,
                &mut diagnostics,
            ) {
                let successor = apply_candidate(state, candidate);
                if seen
                    .get(&successor.offsets)
                    .is_some_and(|&old_depth| old_depth <= depth)
                {
                    continue;
                }
                seen.insert(successor.offsets.clone(), depth);
                next.push(successor);
            }
        }
        next.sort_unstable_by(compare_states);
        next.dedup_by(|a, b| a.offsets == b.offsets);
        next.truncate(BEAM_WIDTH);
        diagnostics.globally_unique_states_retained += next.len();
        if let Some(found) = next.iter().find(|state| state.objective.mismatches == 0) {
            diagnostics.exact_readout_found = true;
            diagnostics.path = found.path.clone();
            return Ok(SearchResult {
                weights: Some(found.weights.clone()),
                readout: Some(found.readout.clone()),
                diagnostics,
            });
        }
        if next.is_empty() {
            break;
        }
        beam = next;
    }
    Ok(SearchResult {
        weights: None,
        readout: None,
        diagnostics,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn one_step_search_repairs_a_single_sum() {
        let op = DriveOperator {
            cues: 1,
            posts: 1,
            coordinates: 2,
            rows: vec![vec![0, 1]],
        };
        let initial = vec![1.0f32, 1.0];
        let target_weights = vec![f32::from_bits(1.0f32.to_bits() + 1), 1.0];
        let actual = op.sequential(&initial);
        let target = op.sequential(&target_weights);
        if actual != target {
            let result = search(&op, &initial, &actual, &target, &[0, 1]).unwrap();
            assert!(result.diagnostics.exact_readout_found);
        }
    }
}
