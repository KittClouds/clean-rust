//! Bounded sparse replay. The mapper consumes only committed weights and
//! ordered rows; target/error bits enter through `overlay_event` later.

use crate::{
    pi_sampler::{build_incidence, pair_support, select_pairs, PairCandidate},
    pi_types::*,
    q10sr::readout,
};
use anyhow::{Result, ensure};

fn weights(fixture: &ReplayFixtureEvent) -> Vec<f32> {
    fixture
        .initial_committed_bits
        .iter()
        .map(|bits| f32::from_bits(*bits))
        .collect()
}

#[inline]
pub fn sequential_row(row: &[u32], weights: &[f32]) -> f32 {
    row.iter()
        .fold(-0.0_f32, |sum, &coordinate| sum + weights[coordinate as usize])
}

pub fn full_readout(rows: &[Vec<u32>], weights: &[f32]) -> Vec<f32> {
    rows.iter().map(|row| sequential_row(row, weights)).collect()
}

fn endpoint(initial: f32, signed_step: i8) -> Result<f32> {
    ensure!(SIGNED_STEPS.contains(&signed_step));
    let mut value = initial;
    for _ in 0..signed_step.unsigned_abs() {
        value = readout::nextafter32(value, signed_step < 0)
            .ok_or_else(|| anyhow::anyhow!("endpoint stepped outside binary32"))?;
    }
    ensure!(
        value.is_finite()
            && value > 0.0
            && value < 2.0
            && readout::interior_steps(value, true, FINAL_RESERVE) >= FINAL_RESERVE
            && readout::interior_steps(value, false, FINAL_RESERVE) >= FINAL_RESERVE,
        "endpoint violates bounded f32 reserve"
    );
    Ok(value)
}

fn row_with_moves(
    row: &[u32],
    weights: &[f32],
    a: usize,
    value_a: Option<f32>,
    b: usize,
    value_b: Option<f32>,
) -> f32 {
    row.iter().fold(-0.0_f32, |sum, &coordinate| {
        let index = coordinate as usize;
        let value = if index == a {
            value_a.unwrap_or(weights[index])
        } else if index == b {
            value_b.unwrap_or(weights[index])
        } else {
            weights[index]
        };
        sum + value
    })
}

fn union_bits(
    support: &[RowSupport],
    rows: &[Vec<u32>],
    weights: &[f32],
    a: usize,
    value_a: Option<f32>,
    b: usize,
    value_b: Option<f32>,
    out: &mut [u32],
) {
    for row in support {
        out[row.union_position as usize] = row_with_moves(
            &rows[row.row as usize], weights, a, value_a, b, value_b,
        )
        .to_bits();
    }
}

fn changed_readout(support: &[RowSupport], baseline: &[u32], current: &[u32]) -> Vec<RowBits> {
    support
        .iter()
        .filter_map(|row| {
            let position = row.union_position as usize;
            (baseline[position] != current[position]).then_some(RowBits {
                row: row.row,
                union_position: row.union_position,
                readout_bits: current[position],
            })
        })
        .collect()
}

fn endpoint_map(
    step: i8,
    replacement: f32,
    support: &[RowSupport],
    baseline: &[u32],
    current: &[u32],
) -> EndpointMap {
    EndpointMap {
        signed_step: step,
        replacement_bits: replacement.to_bits(),
        changed_readout: changed_readout(support, baseline, current),
    }
}

pub(crate) fn interaction_values(
    support: &[RowSupport],
    baseline: &[u32],
    single_a: &[u32],
    single_b: &[u32],
    joint: &[u32],
) -> (Vec<InteractionValue>, f64) {
    let mut values = Vec::new();
    let mut sum_sq = 0.0;
    for row in support {
        let position = row.union_position as usize;
        let base = f64::from(f32::from_bits(baseline[position]));
        let a = f64::from(f32::from_bits(single_a[position]));
        let b = f64::from(f32::from_bits(single_b[position]));
        let both = f64::from(f32::from_bits(joint[position]));
        let interaction = both - a - b + base;
        sum_sq += interaction * interaction;
        if interaction.to_bits() != 0.0_f64.to_bits() {
            values.push(InteractionValue {
                row: row.row,
                union_position: row.union_position,
                value_bits: interaction.to_bits(),
            });
        }
    }
    (values, sum_sq.sqrt())
}

fn build_pair(
    rows: &[Vec<u32>],
    incidence: &[Vec<u32>],
    weights: &[f32],
    baseline: &[u32],
    baseline_norm: f64,
    category: String,
    candidate: PairCandidate,
) -> Result<PairMap> {
    let support = pair_support(rows, incidence, candidate.a, candidate.b);
    let baseline_union: Vec<u32> = support.iter().map(|row| baseline[row.row as usize]).collect();
    let mut scratch = vec![0_u32; support.len()];
    let mut a_values = Vec::with_capacity(SIGNED_STEPS.len());
    let mut b_values = Vec::with_capacity(SIGNED_STEPS.len());
    let mut single_a = Vec::with_capacity(SIGNED_STEPS.len());
    let mut single_b = Vec::with_capacity(SIGNED_STEPS.len());
    for &step in &SIGNED_STEPS {
        let replacement_a = endpoint(weights[candidate.a], step)?;
        union_bits(&support, rows, weights, candidate.a, Some(replacement_a), candidate.b, None, &mut scratch);
        a_values.push(scratch.clone());
        single_a.push(endpoint_map(step, replacement_a, &support, &baseline_union, &scratch));

        let replacement_b = endpoint(weights[candidate.b], step)?;
        union_bits(&support, rows, weights, candidate.a, None, candidate.b, Some(replacement_b), &mut scratch);
        b_values.push(scratch.clone());
        single_b.push(endpoint_map(step, replacement_b, &support, &baseline_union, &scratch));
    }
    let mut candidates = Vec::with_capacity(100);
    for (a_index, &step_a) in SIGNED_STEPS.iter().enumerate() {
        let replacement_a = f32::from_bits(single_a[a_index].replacement_bits);
        for (b_index, &step_b) in SIGNED_STEPS.iter().enumerate() {
            let replacement_b = f32::from_bits(single_b[b_index].replacement_bits);
            union_bits(&support, rows, weights, candidate.a, Some(replacement_a), candidate.b, Some(replacement_b), &mut scratch);
            let (interaction_sparse, interaction_norm) = interaction_values(
                &support, &baseline_union, &a_values[a_index], &b_values[b_index], &scratch,
            );
            candidates.push(CandidateMap {
                signed_steps: [step_a, step_b],
                replacement_bits: [replacement_a.to_bits(), replacement_b.to_bits()],
                joint_changed_readout: changed_readout(&support, &baseline_union, &scratch),
                interaction_sparse,
                interaction_norm,
                interaction_norm_normalized: interaction_norm / baseline_norm.max(NORMALIZATION_FLOOR),
            });
        }
    }
    ensure!(candidates.len() == 100);
    Ok(PairMap {
        category,
        coordinate_a: candidate.a as u32,
        coordinate_b: candidate.b as u32,
        shared_row_count: candidate.shared_rows,
        union_row_count: support.len(),
        support,
        single_a,
        single_b,
        candidates,
    })
}

pub fn build_event_map(input: MapInput<'_>) -> Result<EventMap> {
    let rows = &input.fixture.row_coordinate_ids;
    let weights = weights(input.fixture);
    ensure!(input.fixture.baseline_readout_bits.len() == rows.len());
    ensure!(input.fixture.baseline_readout_l2.is_finite());
    let incidence = build_incidence(rows, weights.len());
    let eligible = input
        .eligible_coordinates
        .iter()
        .copied()
        .filter(|&coordinate| coordinate < incidence.len() && !incidence[coordinate].is_empty())
        .collect::<Vec<_>>();
    let selected = select_pairs(
        rows,
        &incidence,
        &eligible,
        input.fixture.seed,
        input.fixture.tau,
        input.fixture.trial,
        input.shared_pair_count,
        input.disjoint_pair_count,
    )?;
    let baseline = &input.fixture.baseline_readout_bits;
    let mut pairs = Vec::with_capacity(selected.len());
    for (category, candidate) in selected {
        pairs.push(build_pair(rows, &incidence, &weights, baseline, input.fixture.baseline_readout_l2, category, candidate)?);
    }
    let shared_pair_count = pairs.iter().filter(|pair| pair.category == "shared").count();
    let disjoint_pair_count = pairs.iter().filter(|pair| pair.category == "disjoint").count();
    ensure!(shared_pair_count == input.shared_pair_count);
    ensure!(disjoint_pair_count == input.disjoint_pair_count);
    let mut coordinate_seen = vec![false; weights.len()];
    let mut row_seen = vec![false; rows.len()];
    for pair in &pairs {
        coordinate_seen[pair.coordinate_a as usize] = true;
        coordinate_seen[pair.coordinate_b as usize] = true;
        for row in &pair.support {
            row_seen[row.row as usize] = true;
        }
    }
    Ok(EventMap {
        event_key: input.fixture.event_key.clone(),
        seed: input.fixture.seed,
        side: input.fixture.side.clone(),
        tau: input.fixture.tau,
        trial: input.fixture.trial,
        fixture_event_key: input.fixture.event_key.clone(),
        baseline_readout_l2: input.fixture.baseline_readout_l2,
        pair_count: pairs.len(),
        shared_pair_count,
        disjoint_pair_count,
        selected_distinct_coordinate_count: coordinate_seen.into_iter().filter(|seen| *seen).count(),
        selected_distinct_row_count: row_seen.into_iter().filter(|seen| *seen).count(),
        pairs,
    })
}

fn changed_bit(endpoint: &[RowBits], position: usize, baseline: u32) -> u32 {
    endpoint.iter().find(|row| row.union_position as usize == position).map_or(baseline, |row| row.readout_bits)
}

fn overlay_pair(
    pair_index: usize,
    pair: &PairMap,
    baseline_bits: &[u32],
    target_bits: &[u32],
    baseline_error_norm: f64,
    baseline_mismatch: usize,
) -> Vec<OverlayCandidate> {
    let mut candidates = Vec::with_capacity(pair.candidates.len());
    for (candidate_index, candidate) in pair.candidates.iter().enumerate() {
        let a_index = SIGNED_STEPS.iter().position(|step| *step == candidate.signed_steps[0]).expect("frozen signed step");
        let b_index = SIGNED_STEPS.iter().position(|step| *step == candidate.signed_steps[1]).expect("frozen signed step");
        let mut additive_sq = 0.0;
        let mut joint_sq = 0.0;
        let mut mismatch = 0;
        let mut interaction_dot = 0.0;
        let mut interaction_sq = 0.0;
        let mut error_sq = 0.0;
        for row in 0..baseline_bits.len() {
            let base = f64::from(f32::from_bits(baseline_bits[row]));
            let target = f64::from(f32::from_bits(target_bits[row]));
            let error = base - target;
            error_sq += error * error;
            let support_position = pair.support.iter().position(|support| support.row as usize == row);
            let (joint, a, b, joint_bits) = if let Some(position) = support_position {
                let base_bits = baseline_bits[row];
                let a_bits = changed_bit(&pair.single_a[a_index].changed_readout, position, base_bits);
                let b_bits = changed_bit(&pair.single_b[b_index].changed_readout, position, base_bits);
                let joint_bits = changed_bit(&candidate.joint_changed_readout, position, base_bits);
                (f64::from(f32::from_bits(joint_bits)), f64::from(f32::from_bits(a_bits)), f64::from(f32::from_bits(b_bits)), joint_bits)
            } else {
                (base, base, base, baseline_bits[row])
            };
            let additive = base + (a - base) + (b - base);
            additive_sq += (additive - target) * (additive - target);
            joint_sq += (joint - target) * (joint - target);
            mismatch += usize::from(joint_bits != target_bits[row]);
            if let Some(value) = candidate.interaction_sparse.iter().find(|value| value.row as usize == row) {
                let interaction = f64::from_bits(value.value_bits);
                interaction_dot += interaction * -error;
                interaction_sq += interaction * interaction;
            }
        }
        let interaction_cosine = if interaction_sq > 0.0 && error_sq > 0.0 {
            interaction_dot / (interaction_sq.sqrt() * error_sq.sqrt())
        } else {
            0.0
        };
        let actual_joint_error_norm = joint_sq.sqrt();
        candidates.push(OverlayCandidate {
            pair_index,
            candidate_index,
            signed_steps: candidate.signed_steps,
            interaction_cosine_with_negative_error: interaction_cosine,
            additive_error_norm: additive_sq.sqrt(),
            actual_joint_error_norm,
            actual_joint_bitwise_mismatch_count: mismatch,
            pareto_improvement_vs_baseline: (actual_joint_error_norm <= baseline_error_norm && mismatch <= baseline_mismatch)
                && (actual_joint_error_norm < baseline_error_norm || mismatch < baseline_mismatch),
        });
    }
    candidates
}

pub fn overlay_event(input: OverlayInput<'_>) -> Result<OverlayEvent> {
    ensure!(input.target_readout_bits.len() == input.fixture.baseline_readout_bits.len());
    let mut baseline_error_sq = 0.0;
    let mut baseline_mismatch = 0;
    for (&actual, &target) in input.fixture.baseline_readout_bits.iter().zip(input.target_readout_bits) {
        let error = f64::from(f32::from_bits(actual)) - f64::from(f32::from_bits(target));
        baseline_error_sq += error * error;
        baseline_mismatch += usize::from(actual != target);
    }
    let baseline_error_norm = baseline_error_sq.sqrt();
    let mut candidates = Vec::with_capacity(input.map.pair_count * 100);
    for (pair_index, pair) in input.map.pairs.iter().enumerate() {
        candidates.extend(overlay_pair(pair_index, pair, &input.fixture.baseline_readout_bits, input.target_readout_bits, baseline_error_norm, baseline_mismatch));
    }
    ensure!(candidates.len() == input.map.pair_count * 100);
    Ok(OverlayEvent {
        event_key: input.map.event_key.clone(),
        baseline_error_norm,
        baseline_bitwise_mismatch_count: baseline_mismatch,
        candidates,
    })
}

pub fn fixture_event(
    event_key: impl Into<String>,
    seed: u64,
    side: impl Into<String>,
    tau: f32,
    trial: usize,
    rows: Vec<Vec<u32>>,
    initial_committed_bits: Vec<u32>,
) -> ReplayFixtureEvent {
    let weights: Vec<f32> = initial_committed_bits.iter().map(|bits| f32::from_bits(*bits)).collect();
    let baseline = full_readout(&rows, &weights);
    let baseline_readout_bits = baseline.iter().map(|value| value.to_bits()).collect();
    let baseline_readout_l2 = baseline.iter().map(|value| f64::from(*value) * f64::from(*value)).sum::<f64>().sqrt();
    ReplayFixtureEvent { event_key: event_key.into(), seed, side: side.into(), tau, trial, row_coordinate_ids: rows, initial_committed_bits, baseline_readout_bits, baseline_readout_l2 }
}

pub fn assert_full_oracle_parity(fixture: &ReplayFixtureEvent) -> Result<()> {
    let actual = full_readout(&fixture.row_coordinate_ids, &weights(fixture));
    ensure!(actual.iter().map(|value| value.to_bits()).collect::<Vec<_>>() == fixture.baseline_readout_bits);
    Ok(())
}

pub fn assert_representative_pair_parity(fixture: &ReplayFixtureEvent, map: &EventMap) -> Result<()> {
    let weights = weights(fixture);
    for category in ["shared", "disjoint"] {
        let pair = map.pairs.iter().find(|pair| pair.category == category).ok_or_else(|| anyhow::anyhow!("missing representative {category} pair"))?;
        let candidate = &pair.candidates[0];
        let a_value = f32::from_bits(candidate.replacement_bits[0]);
        let b_value = f32::from_bits(candidate.replacement_bits[1]);
        let make_weights = |a: Option<f32>, b: Option<f32>| {
            weights.iter().enumerate().map(|(index, value)| {
                if index == pair.coordinate_a as usize { a.unwrap_or(*value) }
                else if index == pair.coordinate_b as usize { b.unwrap_or(*value) }
                else { *value }
            }).collect::<Vec<_>>()
        };
        let single_a = full_readout(&fixture.row_coordinate_ids, &make_weights(Some(a_value), None));
        let single_b = full_readout(&fixture.row_coordinate_ids, &make_weights(None, Some(b_value)));
        let joint = full_readout(&fixture.row_coordinate_ids, &make_weights(Some(a_value), Some(b_value)));
        for row in &pair.support {
            let position = row.union_position as usize;
            let row_index = row.row as usize;
            let mapped = changed_bit(&candidate.joint_changed_readout, position, fixture.baseline_readout_bits[row_index]);
            ensure!(mapped == joint[row_index].to_bits());
            let interaction = f64::from(joint[row_index]) - f64::from(single_a[row_index]) - f64::from(single_b[row_index]) + f64::from(f32::from_bits(fixture.baseline_readout_bits[row_index]));
            let mapped_interaction = candidate.interaction_sparse.iter().find(|value| value.union_position as usize == position).map_or(0.0, |value| f64::from_bits(value.value_bits));
            ensure!(interaction.to_bits() == mapped_interaction.to_bits());
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pi_sampler::{build_incidence, pair_support, row_members, selected_disjoint_pairs, selected_shared_pairs};
    use std::time::Instant;

    fn dense_fixture() -> ReplayFixtureEvent {
        let mut rows = Vec::new();
        for row in 0..64_u32 {
            rows.push((0..14_u32).map(|coordinate| (coordinate + row) % 14).collect());
        }
        for row in 0..8_u32 { rows.push(vec![14 + row, 22 + row]); }
        for row in 0..8_u32 { rows.push(vec![14 + row]); }
        let weights = (0..30).map(|index| (1.0 + index as f32 / 100.0).to_bits()).collect();
        fixture_event("synthetic", 9721, "R", 4.0, 128, rows, weights)
    }

    #[test]
    fn full_oracle_preserves_empty_rows_order_duplicates_and_signed_zero() {
        let rows = vec![vec![], vec![0], vec![0, 1, 2], vec![0, 2, 1], vec![0, 0]];
        let values = full_readout(&rows, &[0.0_f32, 1.0, -1.0]);
        assert_eq!(values[0].to_bits(), 0x8000_0000);
        assert_eq!(values[1].to_bits(), 0);
        assert_eq!(values[2], 0.0);
        assert_eq!(values[3], 0.0);
        assert_eq!(values[4], 0.0);
        let cancellation = full_readout(&[vec![0, 1, 2], vec![0, 2, 1]], &[16_777_216.0, 1.0, -16_777_216.0]);
        assert_eq!(cancellation[0], 0.0);
        assert_eq!(cancellation[1], 1.0);
    }

    #[test]
    fn contract_fixture_has_frozen_pair_counts_and_all_hundred_candidates() {
        let fixture = dense_fixture();
        assert_full_oracle_parity(&fixture).unwrap();
        let eligible: Vec<usize> = (0..30).collect();
        let map = build_event_map(MapInput { fixture: &fixture, eligible_coordinates: &eligible, shared_pair_count: 64, disjoint_pair_count: 32 }).unwrap();
        assert_representative_pair_parity(&fixture, &map).unwrap();
        assert_eq!((map.pair_count, map.shared_pair_count, map.disjoint_pair_count), (96, 64, 32));
        assert!(map.selected_distinct_coordinate_count > 16 && map.selected_distinct_row_count > 16);
        assert!(map.pairs.iter().all(|pair| pair.candidates.len() == 100));
        assert!(map.pairs.iter().any(|pair| pair.category == "disjoint" && pair.candidates.iter().all(|candidate| candidate.interaction_sparse.is_empty())));
    }

    #[test]
    fn target_overlay_does_not_change_target_blind_map_identity() {
        let fixture = dense_fixture();
        let eligible: Vec<usize> = (0..30).collect();
        let first = build_event_map(MapInput { fixture: &fixture, eligible_coordinates: &eligible, shared_pair_count: 1, disjoint_pair_count: 1 }).unwrap();
        let second = build_event_map(MapInput { fixture: &fixture, eligible_coordinates: &eligible, shared_pair_count: 1, disjoint_pair_count: 1 }).unwrap();
        assert_eq!(serde_json::to_vec(&first).unwrap(), serde_json::to_vec(&second).unwrap());
        let target_a = fixture.baseline_readout_bits.clone();
        let mut target_b = target_a.clone(); target_b[0] ^= 1;
        let overlay_a = overlay_event(OverlayInput { map: &first, fixture: &fixture, target_readout_bits: &target_a }).unwrap();
        let overlay_b = overlay_event(OverlayInput { map: &second, fixture: &fixture, target_readout_bits: &target_b }).unwrap();
        assert_ne!(overlay_a.baseline_bitwise_mismatch_count, overlay_b.baseline_bitwise_mismatch_count);
        assert_eq!(serde_json::to_vec(&first).unwrap(), serde_json::to_vec(&second).unwrap());
    }

    #[test]
    fn support_keeps_row_order_duplicate_positions_and_distance() {
        let rows = [vec![2, 0, 2, 1], vec![], vec![1, 0]];
        let incidence = build_incidence(&rows, 3);
        let support = pair_support(&rows, &incidence, 0, 2);
        assert_eq!((support[0].row, support[0].positions_a.clone(), support[0].positions_b.clone(), support[0].position_distance), (0, vec![1], vec![0, 2], Some(1)));
        assert_eq!(support[1].row, 2);
        assert_eq!(support[1].positions_a, vec![1]);
        assert!(support[1].positions_b.is_empty());
    }

    #[test]
    fn supervisor_nonadditivity_case_is_retained_as_shared_interaction() {
        let rows = vec![vec![0, 1, 2]];
        let incidence = build_incidence(&rows, 3);
        let support = pair_support(&rows, &incidence, 0, 1);
        let baseline = [sequential_row(&rows[0], &[16_777_216.0, 1.0, -16_777_216.0]).to_bits()];
        let down = f32::from_bits(16_777_216.0_f32.to_bits() - 1);
        let up = f32::from_bits(1.0_f32.to_bits() + 1);
        let single_a = [sequential_row(&rows[0], &[down, 1.0, -16_777_216.0]).to_bits()];
        let single_b = [sequential_row(&rows[0], &[16_777_216.0, up, -16_777_216.0]).to_bits()];
        let joint = [sequential_row(&rows[0], &[down, up, -16_777_216.0]).to_bits()];
        let (sparse, norm) = interaction_values(&support, &baseline, &single_a, &single_b, &joint);
        assert_eq!(sparse.len(), 1);
        assert_eq!(f64::from_bits(sparse[0].value_bits), -2.0);
        assert_eq!(norm, 2.0);
    }

    #[test]
    fn realistic_incidence_sampler_is_bounded_and_does_not_materialize_pair_universe() {
        let coordinate_count = 10_000;
        let mut rows = vec![Vec::new(); 10_000];
        for row in rows.iter_mut().take(256) { row.extend(0..64_u32); }
        for coordinate in 64..coordinate_count { rows[256 + (coordinate - 64) % 9_744].push(coordinate as u32); }
        let eligible: Vec<usize> = (0..coordinate_count).collect();
        let before = crate::allocations();
        let started = Instant::now();
        let incidence = build_incidence(&rows, coordinate_count);
        let mut members = row_members(&incidence, rows.len(), &eligible);
        let shared = selected_shared_pairs(&incidence, &mut members, 9721, 4.0, 128, 64);
        let disjoint = selected_disjoint_pairs(&incidence, &eligible, 9721, 4.0, 128, 32);
        let elapsed = started.elapsed();
        let allocations = crate::allocations() - before;
        assert_eq!((shared.len(), disjoint.len()), (64, 32));
        assert!(elapsed.as_secs_f64() < 2.0, "sampler took {elapsed:?}");
        assert!(allocations < 100_000, "sampler allocations={allocations}");
    }
}
