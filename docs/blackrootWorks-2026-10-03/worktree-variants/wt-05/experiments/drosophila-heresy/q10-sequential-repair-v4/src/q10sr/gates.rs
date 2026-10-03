use super::{readout, repair::AppliedMove};
use crate::{capture::Snapshot, linear::DriveOperator};
use anyhow::{Result, ensure};
use serde::Serialize;

const CUE_TOLERANCE: f64 = 2.0e-6;
const AXIS_TOLERANCE: f64 = 2.0e-6;
const NORM_TOLERANCE: f64 = 2.0e-7;
const FLOOR: f64 = 1.0e-12;

fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}

fn norm(values: &[f64]) -> f64 {
    dot(values, values).sqrt()
}

#[derive(Clone, Debug, Serialize)]
pub struct FinalGates {
    pub passed: bool,
    pub sequential_bitwise_equal: bool,
    pub sequential_mismatch_count: usize,
    pub outside_support_changes: usize,
    pub changed_outside_interior: usize,
    pub lower_boundary_membership_difference: usize,
    pub upper_boundary_membership_difference: usize,
    pub new_boundary_memberships: usize,
    pub nonfinite_or_bounds_violations: usize,
    pub minimum_down_steps_capped: u32,
    pub minimum_up_steps_capped: u32,
    pub maximum_coordinate_steps_from_initial: u64,
    pub total_moves: usize,
    pub cue_linear_absolute_error: f64,
    pub cue_linear_normalized_error: f64,
    pub axis_absolute_error: f64,
    pub axis_normalized_error: f64,
    pub norm_absolute_error: f64,
    pub norm_normalized_error: f64,
    pub cue_tolerance: f64,
    pub axis_tolerance: f64,
    pub norm_tolerance: f64,
}

#[allow(clippy::too_many_arguments)]
pub fn audit(
    snapshot: &Snapshot,
    op: &DriveOperator,
    initial_alternate: &[f32],
    final_weights: &[f32],
    final_readout: &[f32],
    target_readout: &[f32],
    true_displacement: &[f64],
    interior: &[usize],
    path: &[AppliedMove],
) -> Result<FinalGates> {
    let n = snapshot.base.len();
    ensure!(
        initial_alternate.len() == n
            && final_weights.len() == n
            && true_displacement.len() == n
            && snapshot.axis.len() == n
            && snapshot.permitted.len() == n
    );
    let mut interior_mask = vec![false; n];
    for &coordinate in interior {
        ensure!(coordinate < n);
        interior_mask[coordinate] = true;
    }
    let sequential = readout::mismatch(op, final_readout, target_readout)?;
    let mut outside_support = 0;
    let mut changed_outside_interior = 0;
    let mut lower_difference = 0;
    let mut upper_difference = 0;
    let mut new_boundary = 0;
    let mut bounds = 0;
    let mut minimum_down = 16;
    let mut minimum_up = 16;
    let mut maximum_steps = 0;
    let mut final_displacement = Vec::with_capacity(n);
    for i in 0..n {
        let initial_bits = initial_alternate[i].to_bits();
        let final_bits = final_weights[i].to_bits();
        let changed = initial_bits != final_bits;
        outside_support += usize::from(!snapshot.permitted[i] && changed);
        changed_outside_interior += usize::from(changed && !interior_mask[i]);
        let true_lower = snapshot.target[i].to_bits() == 0.0f32.to_bits();
        let true_upper = snapshot.target[i].to_bits() == 2.0f32.to_bits();
        let final_lower = final_bits == 0.0f32.to_bits();
        let final_upper = final_bits == 2.0f32.to_bits();
        lower_difference += usize::from(true_lower != final_lower);
        upper_difference += usize::from(true_upper != final_upper);
        new_boundary += usize::from(!true_lower && !true_upper && (final_lower || final_upper));
        bounds +=
            usize::from(!final_weights[i].is_finite() || !(0.0..=2.0).contains(&final_weights[i]));
        if interior_mask[i] {
            minimum_down = minimum_down.min(readout::interior_steps(final_weights[i], true, 16));
            minimum_up = minimum_up.min(readout::interior_steps(final_weights[i], false, 16));
            maximum_steps = maximum_steps.max(readout::ulp_distance(
                initial_alternate[i],
                final_weights[i],
            ));
        }
        final_displacement.push(f64::from(final_weights[i]) - f64::from(snapshot.base[i]));
    }
    let true_drive = op.apply(true_displacement);
    let final_drive = op.apply(&final_displacement);
    let cue_error: Vec<_> = final_drive
        .iter()
        .zip(&true_drive)
        .map(|(actual, target)| actual - target)
        .collect();
    let cue_absolute = norm(&cue_error);
    let cue_normalized = cue_absolute / norm(&true_drive).max(FLOOR);
    let true_axis = dot(true_displacement, &snapshot.axis);
    let final_axis = dot(&final_displacement, &snapshot.axis);
    let axis_absolute = (final_axis - true_axis).abs();
    let axis_normalized = axis_absolute / true_axis.abs().max(FLOOR);
    let true_norm = norm(true_displacement);
    let final_norm = norm(&final_displacement);
    let norm_absolute = (final_norm - true_norm).abs();
    let norm_normalized = norm_absolute / true_norm.max(FLOOR);
    let passed = sequential.bitwise_mismatch_count == 0
        && outside_support == 0
        && changed_outside_interior == 0
        && lower_difference == 0
        && upper_difference == 0
        && new_boundary == 0
        && bounds == 0
        && minimum_down >= 16
        && minimum_up >= 16
        && maximum_steps <= 16
        && path.len() <= 64
        && cue_normalized <= CUE_TOLERANCE
        && axis_normalized <= AXIS_TOLERANCE
        && norm_normalized <= NORM_TOLERANCE;
    Ok(FinalGates {
        passed,
        sequential_bitwise_equal: sequential.bitwise_mismatch_count == 0,
        sequential_mismatch_count: sequential.bitwise_mismatch_count,
        outside_support_changes: outside_support,
        changed_outside_interior,
        lower_boundary_membership_difference: lower_difference,
        upper_boundary_membership_difference: upper_difference,
        new_boundary_memberships: new_boundary,
        nonfinite_or_bounds_violations: bounds,
        minimum_down_steps_capped: minimum_down,
        minimum_up_steps_capped: minimum_up,
        maximum_coordinate_steps_from_initial: maximum_steps,
        total_moves: path.len(),
        cue_linear_absolute_error: cue_absolute,
        cue_linear_normalized_error: cue_normalized,
        axis_absolute_error: axis_absolute,
        axis_normalized_error: axis_normalized,
        norm_absolute_error: norm_absolute,
        norm_normalized_error: norm_normalized,
        cue_tolerance: CUE_TOLERANCE,
        axis_tolerance: AXIS_TOLERANCE,
        norm_tolerance: NORM_TOLERANCE,
    })
}
