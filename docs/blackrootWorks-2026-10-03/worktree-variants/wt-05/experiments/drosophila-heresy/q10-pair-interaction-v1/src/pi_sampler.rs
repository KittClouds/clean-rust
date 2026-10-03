use crate::pi_types::RowSupport;
use anyhow::{Result, ensure};
use std::cmp::Ordering;

const SHARED_ROW_BUDGET: usize = 4_096;
const SHARED_MEMBER_SAMPLE: usize = 16;
const DISJOINT_PAIR_ATTEMPT_BUDGET: usize = 4_096;

#[derive(Clone, Copy)]
pub(crate) struct PairCandidate {
    pub(crate) a: usize,
    pub(crate) b: usize,
    pub(crate) shared_rows: usize,
    pub(crate) key: u64,
}

fn mix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

fn pair_key(seed: u64, tau: f32, trial: usize, category: u64, a: usize, b: usize) -> u64 {
    mix64(
        seed ^ u64::from(tau.to_bits())
            ^ trial as u64
            ^ category
            ^ (a as u64).wrapping_mul(0x9e37_79b1)
            ^ (b as u64).wrapping_mul(0xbf58_476d),
    )
}

pub(crate) fn build_incidence(rows: &[Vec<u32>], coordinate_count: usize) -> Vec<Vec<u32>> {
    let mut incidence = (0..coordinate_count).map(|_| Vec::new()).collect::<Vec<_>>();
    for (row, coordinates) in rows.iter().enumerate() {
        for &coordinate in coordinates {
            let support = &mut incidence[coordinate as usize];
            if support.last().copied() != Some(row as u32) {
                support.push(row as u32);
            }
        }
    }
    incidence
}

pub(crate) fn intersection_count(left: &[u32], right: &[u32], stop_after: usize) -> usize {
    let (mut left_index, mut right_index, mut count) = (0, 0, 0);
    while left_index < left.len() && right_index < right.len() {
        match left[left_index].cmp(&right[right_index]) {
            Ordering::Less => left_index += 1,
            Ordering::Greater => right_index += 1,
            Ordering::Equal => {
                count += 1;
                if count >= stop_after {
                    return count;
                }
                left_index += 1;
                right_index += 1;
            }
        }
    }
    count
}

pub(crate) fn row_members(
    incidence: &[Vec<u32>],
    row_count: usize,
    eligible: &[usize],
) -> Vec<Vec<usize>> {
    let mut members = (0..row_count).map(|_| Vec::new()).collect::<Vec<_>>();
    for &coordinate in eligible {
        for &row in &incidence[coordinate] {
            members[row as usize].push(coordinate);
        }
    }
    members
}

fn pair_seen(selected: &[PairCandidate], a: usize, b: usize) -> bool {
    selected.iter().any(|pair| {
        (pair.a == a && pair.b == b) || (pair.a == b && pair.b == a)
    })
}

pub(crate) fn selected_shared_pairs(
    incidence: &[Vec<u32>],
    members: &mut [Vec<usize>],
    seed: u64,
    tau: f32,
    trial: usize,
    count: usize,
) -> Vec<PairCandidate> {
    let mut row_order: Vec<usize> = (0..members.len()).collect();
    row_order.sort_unstable_by_key(|row| {
        pair_key(seed, tau, trial, 0x51, *row, row.wrapping_add(1))
    });
    let row_order = row_order.into_iter().take(SHARED_ROW_BUDGET).collect::<Vec<_>>();
    for &row in &row_order {
        let row_members = &mut members[row];
        row_members.sort_unstable_by_key(|coordinate| {
            pair_key(seed, tau, trial, 0x53, row, *coordinate)
        });
        row_members.truncate(SHARED_MEMBER_SAMPLE);
    }
    let mut selected = Vec::with_capacity(count);
    for round in 0..(SHARED_MEMBER_SAMPLE * SHARED_MEMBER_SAMPLE) {
        for &row in &row_order {
            let row_members = &members[row];
            if row_members.len() < 2 {
                continue;
            }
            let left = round % row_members.len();
            let stride = round / row_members.len() + 1;
            let right = (left + stride) % row_members.len();
            if left == right {
                continue;
            }
            let a = row_members[left];
            let b = row_members[right];
            if pair_seen(&selected, a, b) {
                continue;
            }
            let shared_rows = intersection_count(&incidence[a], &incidence[b], usize::MAX);
            if shared_rows == 0 {
                continue;
            }
            selected.push(PairCandidate {
                a,
                b,
                shared_rows,
                key: pair_key(seed, tau, trial, 0x51, a, b),
            });
            if selected.len() == count {
                return selected;
            }
        }
    }
    selected
}

pub(crate) fn selected_disjoint_pairs(
    incidence: &[Vec<u32>],
    eligible: &[usize],
    seed: u64,
    tau: f32,
    trial: usize,
    count: usize,
) -> Vec<PairCandidate> {
    let mut coordinates = eligible.to_vec();
    coordinates.sort_unstable_by_key(|coordinate| {
        pair_key(seed, tau, trial, 0xa7, *coordinate, coordinate.wrapping_add(1))
    });
    let mut selected = Vec::with_capacity(count);
    let mut attempts = 0;
    'outer: for stride in 1..coordinates.len().min(256) {
        for left in 0..coordinates.len() {
            attempts += 1;
            if attempts > DISJOINT_PAIR_ATTEMPT_BUDGET {
                break 'outer;
            }
            let right = (left + stride) % coordinates.len();
            if left == right {
                continue;
            }
            let a = coordinates[left];
            let b = coordinates[right];
            if pair_seen(&selected, a, b)
                || intersection_count(&incidence[a], &incidence[b], 1) != 0
            {
                continue;
            }
            selected.push(PairCandidate {
                a,
                b,
                shared_rows: 0,
                key: pair_key(seed, tau, trial, 0xa7, a, b),
            });
            if selected.len() == count {
                break 'outer;
            }
        }
    }
    selected
}

pub(crate) fn pair_support(
    rows: &[Vec<u32>],
    incidence: &[Vec<u32>],
    a: usize,
    b: usize,
) -> Vec<RowSupport> {
    let mut support = Vec::new();
    let mut row_ids = Vec::with_capacity(incidence[a].len() + incidence[b].len());
    let (mut left, mut right) = (0, 0);
    while left < incidence[a].len() || right < incidence[b].len() {
        let next = match (incidence[a].get(left), incidence[b].get(right)) {
            (Some(&left_row), Some(&right_row)) => {
                if left_row <= right_row {
                    left += 1;
                    left_row
                } else {
                    right += 1;
                    right_row
                }
            }
            (Some(&left_row), None) => {
                left += 1;
                left_row
            }
            (None, Some(&right_row)) => {
                right += 1;
                right_row
            }
            (None, None) => break,
        };
        if row_ids.last().copied() != Some(next) {
            row_ids.push(next);
        }
    }
    for row in row_ids {
        let coordinates = &rows[row as usize];
        let mut positions_a = Vec::new();
        let mut positions_b = Vec::new();
        for (position, &coordinate) in coordinates.iter().enumerate() {
            if coordinate as usize == a {
                positions_a.push(position as u16);
            }
            if coordinate as usize == b {
                positions_b.push(position as u16);
            }
        }
        if positions_a.is_empty() && positions_b.is_empty() {
            continue;
        }
        let distance = positions_a
            .iter()
            .flat_map(|left| positions_b.iter().map(move |right| left.abs_diff(*right)))
            .min();
        support.push(RowSupport {
            row,
            union_position: support.len() as u32,
            positions_a,
            positions_b,
            position_distance: distance,
        });
    }
    support
}

pub(crate) fn select_pairs(
    rows: &[Vec<u32>],
    incidence: &[Vec<u32>],
    eligible: &[usize],
    seed: u64,
    tau: f32,
    trial: usize,
    shared_count: usize,
    disjoint_count: usize,
) -> Result<Vec<(String, PairCandidate)>> {
    let mut members = row_members(incidence, rows.len(), eligible);
    let shared = selected_shared_pairs(
        incidence,
        &mut members,
        seed,
        tau,
        trial,
        shared_count,
    );
    let disjoint = selected_disjoint_pairs(
        incidence,
        eligible,
        seed,
        tau,
        trial,
        disjoint_count,
    );
    ensure!(shared.len() >= shared_count, "insufficient structural shared pairs");
    ensure!(
        disjoint.len() >= disjoint_count,
        "insufficient structural disjoint pairs"
    );
    let mut selected = Vec::with_capacity(shared_count + disjoint_count);
    selected.extend(
        shared
            .into_iter()
            .take(shared_count)
            .map(|candidate| ("shared".to_owned(), candidate)),
    );
    selected.extend(
        disjoint
            .into_iter()
            .take(disjoint_count)
            .map(|candidate| ("disjoint".to_owned(), candidate)),
    );
    Ok(selected)
}
