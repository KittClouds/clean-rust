use crate::linear::DriveOperator;
use anyhow::{Result, ensure};
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
pub struct Mismatch {
    pub bitwise_mismatch_count: usize,
    pub maximum_ulp_distance: u64,
    pub sum_ulp_distances: u64,
    pub maximum_absolute_error: f64,
    pub squared_error: f64,
    pub signed_zero_mismatches: usize,
    pub nonfinite_count: usize,
    pub by_cue: Vec<usize>,
    pub by_post: Vec<usize>,
}

#[inline]
pub fn ordered_key(value: f32) -> u32 {
    let bits = value.to_bits();
    if bits & 0x8000_0000 == 0 {
        bits ^ 0x8000_0000
    } else {
        !bits
    }
}

#[inline]
pub fn ulp_distance(a: f32, b: f32) -> u64 {
    u64::from(ordered_key(a).abs_diff(ordered_key(b)))
}

#[inline]
pub fn nextafter32(value: f32, downward: bool) -> Option<f32> {
    if !value.is_finite() {
        return None;
    }
    if value == 0.0 {
        return Some(if downward {
            f32::from_bits(0x8000_0001)
        } else {
            f32::from_bits(1)
        });
    }
    let bits = value.to_bits();
    let next = if (value > 0.0) == downward {
        bits.checked_sub(1)?
    } else {
        bits.checked_add(1)?
    };
    Some(f32::from_bits(next))
}

pub fn interior_steps(mut value: f32, downward: bool, cap: u32) -> u32 {
    let mut steps = 0;
    while steps < cap {
        let Some(next) = nextafter32(value, downward) else {
            break;
        };
        if !next.is_finite() || next <= 0.0 || next >= 2.0 {
            break;
        }
        value = next;
        steps += 1;
    }
    steps
}

pub fn sequential(op: &DriveOperator, weights: &[f32]) -> Vec<f32> {
    op.sequential(weights)
}

pub fn replay_row(op: &DriveOperator, row: usize, weights: &[f32]) -> f32 {
    op.rows[row].iter().map(|&i| weights[i]).sum()
}

pub fn replay_row_with_move(
    op: &DriveOperator,
    row: usize,
    weights: &[f32],
    coordinate: usize,
    replacement: f32,
) -> f32 {
    op.rows[row]
        .iter()
        .map(|&i| {
            if i == coordinate {
                replacement
            } else {
                weights[i]
            }
        })
        .sum()
}

pub fn mismatch(op: &DriveOperator, actual: &[f32], target: &[f32]) -> Result<Mismatch> {
    ensure!(actual.len() == target.len() && actual.len() == op.rows.len());
    let mut out = Mismatch {
        bitwise_mismatch_count: 0,
        maximum_ulp_distance: 0,
        sum_ulp_distances: 0,
        maximum_absolute_error: 0.0,
        squared_error: 0.0,
        signed_zero_mismatches: 0,
        nonfinite_count: 0,
        by_cue: vec![0; op.cues],
        by_post: vec![0; op.posts],
    };
    for (row, (&a, &t)) in actual.iter().zip(target).enumerate() {
        out.nonfinite_count += usize::from(!a.is_finite() || !t.is_finite());
        if a.to_bits() != t.to_bits() {
            out.bitwise_mismatch_count += 1;
            out.by_cue[row / op.posts] += 1;
            out.by_post[row % op.posts] += 1;
            out.signed_zero_mismatches +=
                usize::from(a == 0.0 && t == 0.0 && a.to_bits() != t.to_bits());
        }
        let distance = ulp_distance(a, t);
        out.maximum_ulp_distance = out.maximum_ulp_distance.max(distance);
        out.sum_ulp_distances = out.sum_ulp_distances.saturating_add(distance);
        let error = f64::from(a) - f64::from(t);
        out.maximum_absolute_error = out.maximum_absolute_error.max(error.abs());
        out.squared_error += error * error;
    }
    ensure!(out.nonfinite_count == 0, "nonfinite sequential readout");
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ordered_distance_handles_sign_and_zero() {
        assert_eq!(ulp_distance(1.0, f32::from_bits(1.0f32.to_bits() + 1)), 1);
        assert_eq!(ulp_distance(-0.0, 0.0), 1);
        assert!(ordered_key(-1.0) < ordered_key(-0.0));
        assert!(ordered_key(0.0) < ordered_key(1.0));
    }

    #[test]
    fn nextafter_is_adjacent_for_positive_weights() {
        let value = 1.0f32;
        assert_eq!(
            nextafter32(value, true).unwrap().to_bits(),
            value.to_bits() - 1
        );
        assert_eq!(
            nextafter32(value, false).unwrap().to_bits(),
            value.to_bits() + 1
        );
    }
}
