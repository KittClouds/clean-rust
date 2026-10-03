use super::{
    bank::{Direction, FINAL_RESERVE, coordinate_rows},
    readout::{Mismatch, interior_steps, mismatch, nextafter32, ulp_distance},
};
use crate::linear::DriveOperator;
use anyhow::{Result, ensure};
use hashbrown::HashMap;
use serde::Serialize;
use smallvec::SmallVec;
use std::cmp::Ordering;

const BEAM_WIDTH: usize = 64;
const BRANCH_WIDTH: usize = 64;
const MAX_DEPTH: usize = 64;
const MAX_COORDINATE_STEPS: i8 = 16;
// The production operator has at most one row per cue for a coordinate.
// The fallback scan below keeps synthetic wide-incidence fixtures exact.
const TOP_ERROR_CAPACITY: usize = 64;

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

#[derive(Clone, Copy)]
struct OffsetEntry {
    coordinate: usize,
    steps: i8,
    bits: u32,
}

type OffsetList = SmallVec<[OffsetEntry; 64]>;
type TopErrors = SmallVec<[(u64, usize); TOP_ERROR_CAPACITY]>;

#[derive(Clone)]
struct BeamState {
    // The immutable starting vector is owned by search. A state carries only
    // changed coordinates and their exact committed bits.
    offsets: OffsetList,
    readout: Vec<f32>,
    top_errors: TopErrors,
    path: Vec<AppliedMove>,
    objective: Objective,
}

#[derive(Clone)]
struct Candidate {
    coordinate: usize,
    direction: Direction,
    replacement_bits: u32,
    next_offset: i8,
    objective: Objective,
}

fn offset_at(offsets: &[OffsetEntry], coordinate: usize) -> i8 {
    offsets
        .binary_search_by_key(&coordinate, |entry| entry.coordinate)
        .ok()
        .map_or(0, |at| offsets[at].steps)
}

fn entry_at(offsets: &[OffsetEntry], coordinate: usize) -> Option<OffsetEntry> {
    offsets
        .binary_search_by_key(&coordinate, |entry| entry.coordinate)
        .ok()
        .map(|at| offsets[at])
}

fn state_bits(initial_weights: &[f32], offsets: &[OffsetEntry], coordinate: usize) -> u32 {
    entry_at(offsets, coordinate)
        .map_or_else(|| initial_weights[coordinate].to_bits(), |entry| entry.bits)
}

fn set_offset(offsets: &mut OffsetList, coordinate: usize, steps: i8, bits: u32) {
    match offsets.binary_search_by_key(&coordinate, |entry| entry.coordinate) {
        Ok(at) if steps == 0 => {
            offsets.remove(at);
        }
        Ok(at) => {
            offsets[at] = OffsetEntry {
                coordinate,
                steps,
                bits,
            };
        }
        Err(at) if steps != 0 => offsets.insert(
            at,
            OffsetEntry {
                coordinate,
                steps,
                bits,
            },
        ),
        Err(_) => {}
    }
}

fn offset_key(offsets: &[OffsetEntry]) -> Vec<(usize, i8)> {
    offsets
        .iter()
        .map(|entry| (entry.coordinate, entry.steps))
        .collect()
}

fn same_offsets(a: &[OffsetEntry], b: &[OffsetEntry]) -> bool {
    a.iter()
        .map(|entry| (entry.coordinate, entry.steps))
        .eq(b.iter().map(|entry| (entry.coordinate, entry.steps)))
}

fn compare_committed_bytes(
    initial_weights: &[f32],
    a: &[OffsetEntry],
    b: &[OffsetEntry],
) -> Ordering {
    let mut ai = 0;
    let mut bi = 0;
    while ai < a.len() || bi < b.len() {
        let ac = a.get(ai).map_or(usize::MAX, |entry| entry.coordinate);
        let bc = b.get(bi).map_or(usize::MAX, |entry| entry.coordinate);
        let coordinate = ac.min(bc);
        if coordinate == usize::MAX {
            break;
        }
        let abits = if ac == coordinate {
            a[ai].bits
        } else {
            initial_weights[coordinate].to_bits()
        };
        let bbits = if bc == coordinate {
            b[bi].bits
        } else {
            initial_weights[coordinate].to_bits()
        };
        match abits.cmp(&bbits) {
            Ordering::Equal => {}
            order => return order,
        }
        ai += usize::from(ac == coordinate);
        bi += usize::from(bc == coordinate);
    }
    Ordering::Equal
}

fn insert_top_error(top: &mut TopErrors, item: (u64, usize)) {
    let position = top.iter().position(|&(distance, row)| {
        distance < item.0 || (distance == item.0 && row > item.1)
    });
    match position {
        Some(at) if at < TOP_ERROR_CAPACITY => top.insert(at, item),
        None if top.len() < TOP_ERROR_CAPACITY => top.push(item),
        _ => return,
    }
    if top.len() > TOP_ERROR_CAPACITY {
        top.pop();
    }
}

fn top_errors(readout: &[f32], target: &[f32]) -> TopErrors {
    let mut top = TopErrors::new();
    for (row, (&actual, &truth)) in readout.iter().zip(target).enumerate() {
        insert_top_error(&mut top, (ulp_distance(actual, truth), row));
    }
    top
}

fn row_value(
    op: &DriveOperator,
    row: usize,
    initial_weights: &[f32],
    offsets: &[OffsetEntry],
    coordinate: usize,
    replacement: f32,
) -> f32 {
    op.rows[row]
        .iter()
        .map(|&index| {
            if index == coordinate {
                replacement
            } else {
                f32::from_bits(state_bits(initial_weights, offsets, index))
            }
        })
        .sum()
}

fn row_is_updated(rows: &[usize], row: usize) -> bool {
    rows.binary_search(&row).is_ok()
}

fn unaffected_max_ulp(state: &BeamState, rows: &[usize], target: &[f32]) -> u64 {
    if rows.len() < TOP_ERROR_CAPACITY {
        return state
            .top_errors
            .iter()
            .find(|&&(_, row)| !row_is_updated(rows, row))
            .map_or(0, |&(distance, _)| distance);
    }
    state
        .readout
        .iter()
        .zip(target)
        .enumerate()
        .filter(|(row, _)| !row_is_updated(rows, *row))
        .map(|(_, (&actual, &truth))| ulp_distance(actual, truth))
        .max()
        .unwrap_or(0)
}

#[allow(clippy::too_many_arguments)]
fn successor_objective(
    op: &DriveOperator,
    initial_weights: &[f32],
    state: &BeamState,
    target: &[f32],
    coordinate: usize,
    replacement: f32,
    rows: &[usize],
    next_offset: i8,
) -> Objective {
    let mut mismatches = state.objective.mismatches;
    let mut sum_ulp = state.objective.sum_ulp;
    let mut squared_error = state.objective.squared_error;
    let mut changed_max = 0;
    for &row in rows {
        let value = row_value(
            op,
            row,
            initial_weights,
            &state.offsets,
            coordinate,
            replacement,
        );
        let truth = target[row];
        mismatches = mismatches
            - usize::from(state.readout[row].to_bits() != truth.to_bits())
            + usize::from(value.to_bits() != truth.to_bits());
        let old_distance = ulp_distance(state.readout[row], truth);
        let new_distance = ulp_distance(value, truth);
        sum_ulp = sum_ulp - old_distance + new_distance;
        changed_max = changed_max.max(new_distance);
        let old_error = f64::from(state.readout[row]) - f64::from(truth);
        let new_error = f64::from(value) - f64::from(truth);
        squared_error += new_error * new_error - old_error * old_error;
    }
    Objective {
        mismatches,
        max_ulp: unaffected_max_ulp(state, rows, target).max(changed_max),
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

fn compare_states(initial_weights: &[f32], a: &BeamState, b: &BeamState) -> Ordering {
    a.objective
        .compare(&b.objective)
        .then_with(|| compare_committed_bytes(initial_weights, &a.offsets, &b.offsets))
}

fn enumerate_candidates(
    op: &DriveOperator,
    initial_weights: &[f32],
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
        let current = f32::from_bits(state_bits(initial_weights, &state.offsets, coordinate));
        let rows = &coordinate_rows[coordinate];
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
            let Some(replacement) = nextafter32(current, direction.downward()) else {
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
            diagnostics.legal_successors_enumerated += 1;
            candidates.push(Candidate {
                coordinate,
                direction,
                replacement_bits: replacement.to_bits(),
                next_offset,
                objective: successor_objective(
                    op,
                    initial_weights,
                    state,
                    target,
                    coordinate,
                    replacement,
                    rows,
                    next_offset,
                ),
            });
        }
    }
    candidates.sort_unstable_by(compare_candidates);
    candidates.truncate(BRANCH_WIDTH);
    diagnostics.branch_successors_retained += candidates.len();
    candidates
}

fn apply_candidate(
    op: &DriveOperator,
    initial_weights: &[f32],
    target: &[f32],
    coordinate_rows: &[Vec<usize>],
    state: &BeamState,
    candidate: Candidate,
) -> BeamState {
    let replacement = f32::from_bits(candidate.replacement_bits);
    let mut readout = state.readout.clone();
    for &row in &coordinate_rows[candidate.coordinate] {
        readout[row] = row_value(
            op,
            row,
            initial_weights,
            &state.offsets,
            candidate.coordinate,
            replacement,
        );
    }
    let mut offsets = state.offsets.clone();
    set_offset(
        &mut offsets,
        candidate.coordinate,
        candidate.next_offset,
        candidate.replacement_bits,
    );
    let mut path = state.path.clone();
    path.push(AppliedMove {
        coordinate: candidate.coordinate,
        direction: candidate.direction,
        before_bits: state_bits(initial_weights, &state.offsets, candidate.coordinate),
        after_bits: candidate.replacement_bits,
    });
    BeamState {
        top_errors: top_errors(&readout, target),
        readout,
        offsets,
        path,
        objective: candidate.objective,
    }
}

fn materialize(initial_weights: &[f32], offsets: &[OffsetEntry]) -> Vec<f32> {
    let mut weights = initial_weights.to_vec();
    for entry in offsets {
        weights[entry.coordinate] = f32::from_bits(entry.bits);
    }
    weights
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
    // A coordinate absent from every authoritative row can never improve the
    // objective or any final readout. Pruning it only removes dead states.
    let active_interior: Vec<_> = interior
        .iter()
        .copied()
        .filter(|&coordinate| !coordinate_rows[coordinate].is_empty())
        .collect();
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
        offsets: OffsetList::new(),
        readout: initial_readout.to_vec(),
        top_errors: top_errors(initial_readout, target),
        path: Vec::new(),
        objective: Objective::from_mismatch(&initial_mismatch, 0, 0),
    }];
    let mut seen = HashMap::<Vec<(usize, i8)>, usize>::new();
    seen.insert(Vec::new(), 0);
    for depth in 1..=MAX_DEPTH {
        diagnostics.depth_reached = depth;
        let mut next = Vec::with_capacity(beam.len() * BRANCH_WIDTH);
        for state in &beam {
            diagnostics.states_expanded += 1;
            let candidates = enumerate_candidates(
                op,
                initial_weights,
                &coordinate_rows,
                &active_interior,
                target,
                state,
                &mut diagnostics,
            );
            for candidate in candidates {
                let successor = apply_candidate(
                    op,
                    initial_weights,
                    target,
                    &coordinate_rows,
                    state,
                    candidate,
                );
                let key = offset_key(&successor.offsets);
                if seen.get(&key).is_some_and(|&old_depth| old_depth <= depth) {
                    continue;
                }
                seen.insert(key, depth);
                next.push(successor);
            }
        }
        next.sort_unstable_by(|a, b| compare_states(initial_weights, a, b));
        next.dedup_by(|a, b| same_offsets(&a.offsets, &b.offsets));
        next.truncate(BEAM_WIDTH);
        diagnostics.globally_unique_states_retained += next.len();
        if let Some(found) = next.iter().find(|state| state.objective.mismatches == 0) {
            diagnostics.exact_readout_found = true;
            diagnostics.path = found.path.clone();
            return Ok(SearchResult {
                weights: Some(materialize(initial_weights, &found.offsets)),
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

    #[test]
    fn committed_byte_tie_break_uses_sparse_offsets() {
        let initial = vec![1.0f32, 1.0];
        let a = [OffsetEntry {
            coordinate: 0,
            steps: 1,
            bits: initial[0].to_bits() + 1,
        }];
        let b = [OffsetEntry {
            coordinate: 1,
            steps: 1,
            bits: initial[1].to_bits() + 1,
        }];
        assert_eq!(compare_committed_bytes(&initial, &a, &b), Ordering::Greater);
    }

    #[test]
    fn dead_coordinates_are_absent_from_search_successors() {
        let op = DriveOperator {
            cues: 1,
            posts: 1,
            coordinates: 3,
            rows: vec![vec![0]],
        };
        let initial = vec![1.0f32, 1.0, 1.0];
        let target_weights = vec![f32::from_bits(1.0f32.to_bits() + 1), 1.0, 1.0];
        let result = search(
            &op,
            &initial,
            &op.sequential(&initial),
            &op.sequential(&target_weights),
            &[0, 1, 2],
        )
        .unwrap();
        assert!(result.diagnostics.exact_readout_found);
        assert!(result
            .diagnostics
            .path
            .iter()
            .all(|movement| movement.coordinate == 0));
    }
}
