use serde::Serialize;
use std::{error::Error, fmt};

pub(crate) const MAX_NULL_ATTEMPTS: u16 = 64;
pub(crate) const ZERO_NORM_SQ: f64 = 1.0e-24;
// Frozen before any DH-07 measured seed is run. This accommodates committed-f32
// roundoff while remaining far below a scientifically meaningful direction cosine.
pub(crate) const DELIVERED_REL_NORM_TOL: f64 = 5.0e-6;
pub(crate) const DELIVERED_COS_TOL: f64 = 5.0e-6;
pub(crate) const TRUE_AXIS_COS_GATE: f64 = 5.0e-6;

#[derive(Clone, Debug, Serialize)]
pub struct NullEvent {
    pub reversal_trial: usize,
    pub support_size: usize,
    pub base_at_lower_bound: usize,
    pub base_at_upper_bound: usize,
    pub attempts: u16,
    pub candidate_rejections: u16,
    pub bound_rejections: u16,
    pub numeric_rejections: u16,
    pub low_rank_rejections: u16,
    pub zero_energy: bool,
    pub true_l1: f64,
    pub true_l2: f64,
    pub true_linf: f64,
    pub null_l1: f64,
    pub null_l2: f64,
    pub null_linf: f64,
    pub relative_l2_mismatch: f64,
    pub null_axis_cosine: f64,
    pub null_true_cosine: f64,
    pub true_axis_cosine: f64,
    pub null_hash: u64,
}

#[derive(Clone, Debug, Serialize)]
pub struct TrueDirectionAudit {
    pub reversal_trial: usize,
    pub support_size: usize,
    pub base_at_lower_bound: usize,
    pub base_at_upper_bound: usize,
    pub true_l1: f64,
    pub true_l2: f64,
    pub true_linf: f64,
    pub true_axis_cosine: f64,
    pub passes_axis_gate: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct NullFailure {
    pub reversal_trial: usize,
    pub support_size: usize,
    pub base_at_lower_bound: usize,
    pub base_at_upper_bound: usize,
    pub target_l2: f64,
    pub true_axis_cosine: f64,
    pub attempts: u16,
    pub bound_rejections: u16,
    pub numeric_rejections: u16,
    pub low_rank_rejections: u16,
    pub reason: &'static str,
    pub snapshot: Box<NullFailureSnapshot>,
}

#[derive(Clone, Debug, Serialize)]
pub struct NullFailureSnapshot {
    pub support_indices: Vec<u32>,
    pub base: Vec<f32>,
    pub true_target: Vec<f32>,
    pub masked_acquisition_axis: Vec<f64>,
}

impl fmt::Display for NullFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "DH07 null integrity failure at reversal trial {}: {} (support={}, bounds=({}, {}), target_l2={:.9e}, true_axis_cos={:.9e}, attempts={}, rejected bounds/numeric/rank={}/{}/{})",
            self.reversal_trial,
            self.reason,
            self.support_size,
            self.base_at_lower_bound,
            self.base_at_upper_bound,
            self.target_l2,
            self.true_axis_cosine,
            self.attempts,
            self.bound_rejections,
            self.numeric_rejections,
            self.low_rank_rejections,
        )
    }
}

impl Error for NullFailure {}

pub(crate) struct NullScratch {
    pub base: Vec<f32>,
    pub true_target: Vec<f32>,
    pub masked_axis: Vec<f64>,
    pub support: Vec<usize>,
    pub null_target: Vec<f32>,
    true_displacement: Vec<f64>,
    axis_unit: Vec<f64>,
    true_unit: Vec<f64>,
    candidate: Vec<f64>,
    delivered: Vec<f64>,
    permutation: Vec<usize>,
}

impl NullScratch {
    pub(crate) fn new(len: usize) -> Self {
        Self {
            base: vec![0.0; len],
            true_target: vec![0.0; len],
            masked_axis: vec![0.0; len],
            support: Vec::with_capacity(len),
            null_target: vec![0.0; len],
            true_displacement: vec![0.0; len],
            axis_unit: vec![0.0; len],
            true_unit: vec![0.0; len],
            candidate: vec![0.0; len],
            delivered: vec![0.0; len],
            permutation: Vec::with_capacity(len),
        }
    }

    pub(crate) fn begin_event(&mut self) {
        self.support.clear();
        self.masked_axis.fill(0.0);
    }

    pub(crate) fn array_bytes(&self) -> usize {
        4 * (self.base.len() + self.true_target.len() + self.null_target.len())
            + 8 * (self.masked_axis.len()
                + self.true_displacement.len()
                + self.axis_unit.len()
                + self.true_unit.len()
                + self.candidate.len()
                + self.delivered.len())
            + std::mem::size_of::<usize>() * (self.support.capacity() + self.permutation.capacity())
    }

    pub(crate) fn construct(
        &mut self,
        key: u64,
        reversal_trial: usize,
    ) -> Result<NullEvent, NullFailure> {
        let mut true_l1 = 0.0;
        let mut true_l2_sq = 0.0;
        let mut true_linf: f64 = 0.0;
        let mut axis_l2_sq = 0.0;
        let mut true_axis_dot = 0.0;
        let mut lower = 0;
        let mut upper = 0;
        self.true_displacement.fill(0.0);
        self.axis_unit.fill(0.0);
        self.true_unit.fill(0.0);
        for &ix in &self.support {
            let base = self.base[ix];
            lower += usize::from(base == 0.0);
            upper += usize::from(base == 2.0);
            let value = f64::from(self.true_target[ix]) - f64::from(base);
            self.true_displacement[ix] = value;
            true_l1 += value.abs();
            true_l2_sq += value * value;
            true_linf = true_linf.max(value.abs());
            axis_l2_sq += self.masked_axis[ix] * self.masked_axis[ix];
            true_axis_dot += value * self.masked_axis[ix];
        }
        let true_l2 = true_l2_sq.sqrt();
        let axis_l2 = axis_l2_sq.sqrt();
        let true_axis_cos = cosine_from(true_axis_dot, true_l2, axis_l2);
        if !true_l1.is_finite()
            || !true_l2_sq.is_finite()
            || !true_linf.is_finite()
            || !axis_l2_sq.is_finite()
            || !true_axis_dot.is_finite()
        {
            return Err(self.failure(
                reversal_trial,
                lower,
                upper,
                true_l2,
                true_axis_cos,
                0,
                0,
                0,
                0,
                "non-finite true intervention geometry",
            ));
        }
        if true_l2_sq <= ZERO_NORM_SQ {
            self.null_target.copy_from_slice(&self.base);
            return Ok(NullEvent {
                reversal_trial,
                support_size: self.support.len(),
                base_at_lower_bound: lower,
                base_at_upper_bound: upper,
                attempts: 0,
                candidate_rejections: 0,
                bound_rejections: 0,
                numeric_rejections: 0,
                low_rank_rejections: 0,
                zero_energy: true,
                true_l1,
                true_l2,
                true_linf,
                null_l1: 0.0,
                null_l2: 0.0,
                null_linf: 0.0,
                relative_l2_mismatch: 0.0,
                null_axis_cosine: 0.0,
                null_true_cosine: 0.0,
                true_axis_cosine: true_axis_cos,
                null_hash: hash_f32(&self.null_target, &self.support),
            });
        }
        if true_axis_cos.abs() > TRUE_AXIS_COS_GATE {
            return Err(self.failure(
                reversal_trial,
                lower,
                upper,
                true_l2,
                true_axis_cos,
                0,
                0,
                0,
                0,
                "realized true intervention exceeds acquisition-axis leakage gate",
            ));
        }
        if axis_l2 > 0.0 {
            for &ix in &self.support {
                self.axis_unit[ix] = self.masked_axis[ix] / axis_l2;
            }
        }
        let true_axis_projection = if axis_l2 > 0.0 {
            dot_on(&self.true_displacement, &self.axis_unit, &self.support)
        } else {
            0.0
        };
        let mut true_orth_sq = 0.0;
        for &ix in &self.support {
            let value = self.true_displacement[ix] - true_axis_projection * self.axis_unit[ix];
            self.true_unit[ix] = value;
            true_orth_sq += value * value;
        }
        if true_orth_sq > ZERO_NORM_SQ {
            let inv = true_orth_sq.sqrt().recip();
            for &ix in &self.support {
                self.true_unit[ix] *= inv;
            }
        } else {
            self.true_unit.fill(0.0);
        }
        let active_rank =
            usize::from(axis_l2_sq > ZERO_NORM_SQ) + usize::from(true_orth_sq > ZERO_NORM_SQ);
        if self.support.len() <= active_rank {
            return Err(self.failure(
                reversal_trial,
                lower,
                upper,
                true_l2,
                true_axis_cos,
                0,
                0,
                0,
                0,
                "support dimension does not exceed active constrained rank",
            ));
        }

        let mut bounds = 0_u16;
        let mut numeric = 0_u16;
        let mut low_rank = 0_u16;
        for attempt in 0..MAX_NULL_ATTEMPTS {
            self.candidate.fill(0.0);
            self.null_target.copy_from_slice(&self.base);
            self.permutation.clear();
            self.permutation.extend(0..self.support.len());
            let mut counter = CounterRng::new(key ^ u64::from(attempt));
            counter.shuffle(&mut self.permutation);
            for (position, &ix) in self.support.iter().enumerate() {
                let source = self.support[self.permutation[position]];
                let sign = if counter.next() & 1 == 0 { 1.0 } else { -1.0 };
                self.candidate[ix] = sign * self.true_displacement[source];
            }
            project_out(&mut self.candidate, &self.axis_unit, &self.support);
            project_out(&mut self.candidate, &self.true_unit, &self.support);
            project_out(&mut self.candidate, &self.axis_unit, &self.support);
            project_out(&mut self.candidate, &self.true_unit, &self.support);
            let candidate_sq = squared_norm_on(&self.candidate, &self.support);
            if candidate_sq <= ZERO_NORM_SQ {
                low_rank += 1;
                continue;
            }
            let scale = true_l2 / candidate_sq.sqrt();
            let mut feasible = true;
            for &ix in &self.support {
                let target = f64::from(self.base[ix]) + scale * self.candidate[ix];
                if !target.is_finite() || !(0.0..=2.0).contains(&target) {
                    feasible = false;
                    break;
                }
                self.null_target[ix] = target as f32;
            }
            if !feasible {
                bounds += 1;
                continue;
            }
            let audit = self.audit_committed(true_l2, axis_l2);
            if !audit.null_l1.is_finite()
                || !audit.null_l2.is_finite()
                || !audit.null_linf.is_finite()
                || !audit.relative_l2_mismatch.is_finite()
                || !audit.null_axis_cosine.is_finite()
                || !audit.null_true_cosine.is_finite()
                || audit.relative_l2_mismatch > DELIVERED_REL_NORM_TOL
                || audit.null_axis_cosine.abs() > DELIVERED_COS_TOL
                || audit.null_true_cosine.abs() > DELIVERED_COS_TOL
            {
                numeric += 1;
                continue;
            }
            return Ok(NullEvent {
                reversal_trial,
                support_size: self.support.len(),
                base_at_lower_bound: lower,
                base_at_upper_bound: upper,
                attempts: attempt + 1,
                candidate_rejections: attempt,
                bound_rejections: bounds,
                numeric_rejections: numeric,
                low_rank_rejections: low_rank,
                zero_energy: false,
                true_l1,
                true_l2,
                true_linf,
                null_l1: audit.null_l1,
                null_l2: audit.null_l2,
                null_linf: audit.null_linf,
                relative_l2_mismatch: audit.relative_l2_mismatch,
                null_axis_cosine: audit.null_axis_cosine,
                null_true_cosine: audit.null_true_cosine,
                true_axis_cosine: true_axis_cos,
                null_hash: hash_f32(&self.null_target, &self.support),
            });
        }
        Err(self.failure(
            reversal_trial,
            lower,
            upper,
            true_l2,
            true_axis_cos,
            MAX_NULL_ATTEMPTS,
            bounds,
            numeric,
            low_rank,
            "no feasible jointly orthogonal matched-energy direction",
        ))
    }

    pub(crate) fn audit_true(&self, reversal_trial: usize) -> TrueDirectionAudit {
        let mut l1 = 0.0;
        let mut l2_sq = 0.0;
        let mut linf: f64 = 0.0;
        let mut axis_sq = 0.0;
        let mut axis_dot = 0.0;
        let mut lower = 0;
        let mut upper = 0;
        for &ix in &self.support {
            let base = self.base[ix];
            lower += usize::from(base == 0.0);
            upper += usize::from(base == 2.0);
            let value = f64::from(self.true_target[ix]) - f64::from(base);
            l1 += value.abs();
            l2_sq += value * value;
            linf = linf.max(value.abs());
            axis_sq += self.masked_axis[ix] * self.masked_axis[ix];
            axis_dot += value * self.masked_axis[ix];
        }
        let l2 = l2_sq.sqrt();
        let axis_cosine = cosine_from(axis_dot, l2, axis_sq.sqrt());
        TrueDirectionAudit {
            reversal_trial,
            support_size: self.support.len(),
            base_at_lower_bound: lower,
            base_at_upper_bound: upper,
            true_l1: l1,
            true_l2: l2,
            true_linf: linf,
            true_axis_cosine: axis_cosine,
            passes_axis_gate: l2_sq <= ZERO_NORM_SQ
                || (axis_cosine.is_finite() && axis_cosine.abs() <= TRUE_AXIS_COS_GATE),
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn failure(
        &self,
        reversal_trial: usize,
        lower: usize,
        upper: usize,
        target_l2: f64,
        true_axis_cosine: f64,
        attempts: u16,
        bound_rejections: u16,
        numeric_rejections: u16,
        low_rank_rejections: u16,
        reason: &'static str,
    ) -> NullFailure {
        NullFailure {
            reversal_trial,
            support_size: self.support.len(),
            base_at_lower_bound: lower,
            base_at_upper_bound: upper,
            target_l2,
            true_axis_cosine,
            attempts,
            bound_rejections,
            numeric_rejections,
            low_rank_rejections,
            reason,
            snapshot: Box::new(NullFailureSnapshot {
                support_indices: self.support.iter().map(|&ix| ix as u32).collect(),
                base: self.support.iter().map(|&ix| self.base[ix]).collect(),
                true_target: self
                    .support
                    .iter()
                    .map(|&ix| self.true_target[ix])
                    .collect(),
                masked_acquisition_axis: self
                    .support
                    .iter()
                    .map(|&ix| self.masked_axis[ix])
                    .collect(),
            }),
        }
    }

    fn audit_committed(&mut self, true_l2: f64, axis_l2: f64) -> DeliveredAudit {
        self.delivered.fill(0.0);
        let mut l1 = 0.0;
        let mut l2_sq = 0.0;
        let mut linf: f64 = 0.0;
        let mut dot_axis = 0.0;
        let mut dot_true = 0.0;
        for &ix in &self.support {
            let value = f64::from(self.null_target[ix]) - f64::from(self.base[ix]);
            self.delivered[ix] = value;
            l1 += value.abs();
            l2_sq += value * value;
            linf = linf.max(value.abs());
            dot_axis += value * self.masked_axis[ix];
            dot_true += value * self.true_displacement[ix];
        }
        let l2 = l2_sq.sqrt();
        DeliveredAudit {
            null_l1: l1,
            null_l2: l2,
            null_linf: linf,
            relative_l2_mismatch: (l2 - true_l2).abs() / true_l2.max(f64::MIN_POSITIVE),
            null_axis_cosine: cosine_from(dot_axis, l2, axis_l2),
            null_true_cosine: cosine_from(dot_true, l2, true_l2),
        }
    }
}

struct DeliveredAudit {
    null_l1: f64,
    null_l2: f64,
    null_linf: f64,
    relative_l2_mismatch: f64,
    null_axis_cosine: f64,
    null_true_cosine: f64,
}

fn dot_on(a: &[f64], b: &[f64], support: &[usize]) -> f64 {
    support.iter().map(|&ix| a[ix] * b[ix]).sum()
}

fn squared_norm_on(values: &[f64], support: &[usize]) -> f64 {
    support.iter().map(|&ix| values[ix] * values[ix]).sum()
}

fn project_out(values: &mut [f64], unit: &[f64], support: &[usize]) {
    let coefficient = dot_on(values, unit, support);
    for &ix in support {
        values[ix] -= coefficient * unit[ix];
    }
}

fn cosine_from(dot: f64, a_norm: f64, b_norm: f64) -> f64 {
    let denominator = a_norm * b_norm;
    if denominator > 0.0 {
        dot / denominator
    } else {
        0.0
    }
}

fn mix64(mut value: u64) -> u64 {
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

struct CounterRng(u64);

impl CounterRng {
    fn new(key: u64) -> Self {
        Self(key ^ 0x4448_3037_4e55_4c4c)
    }

    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        mix64(self.0)
    }

    fn shuffle<T>(&mut self, values: &mut [T]) {
        for i in (1..values.len()).rev() {
            let j = (self.next() % (i as u64 + 1)) as usize;
            values.swap(i, j);
        }
    }
}

fn hash_f32(values: &[f32], support: &[usize]) -> u64 {
    let mut hash = 0x4448_3037_4841_5348_u64;
    for &ix in support {
        hash = mix64(hash ^ u64::from(values[ix].to_bits()) ^ ix as u64);
    }
    hash
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_synthetic_direction_is_committed_and_audited() {
        let mut scratch = NullScratch::new(8);
        scratch.begin_event();
        for ix in 0..8 {
            scratch.support.push(ix);
            scratch.base[ix] = 1.0;
            scratch.true_target[ix] = 1.0 + if ix % 2 == 0 { 0.1 } else { -0.1 };
            scratch.masked_axis[ix] = if ix < 4 { 1.0 } else { -1.0 };
        }
        let event = scratch.construct(7, 1).unwrap();
        assert!(!event.zero_energy);
        assert!(event.relative_l2_mismatch <= DELIVERED_REL_NORM_TOL);
        assert!(event.null_axis_cosine.abs() <= DELIVERED_COS_TOL);
        assert!(event.null_true_cosine.abs() <= DELIVERED_COS_TOL);
    }

    #[test]
    fn bounded_cone_impossibility_fails_closed() {
        let mut scratch = NullScratch::new(4);
        scratch.begin_event();
        for ix in 0..4 {
            scratch.support.push(ix);
            scratch.base[ix] = 0.0;
            scratch.true_target[ix] = 0.1;
            scratch.masked_axis[ix] = 0.0;
        }
        let failure = scratch.construct(9, 3).unwrap_err();
        assert_eq!(failure.attempts, MAX_NULL_ATTEMPTS);
        assert_eq!(
            failure.bound_rejections + failure.numeric_rejections + failure.low_rank_rejections,
            MAX_NULL_ATTEMPTS
        );
    }

    #[test]
    fn realized_true_axis_leakage_fails_before_search() {
        let mut scratch = NullScratch::new(4);
        scratch.begin_event();
        for ix in 0..4 {
            scratch.support.push(ix);
            scratch.base[ix] = 0.0;
            scratch.true_target[ix] = 0.1;
            scratch.masked_axis[ix] = 1.0;
        }
        let failure = scratch.construct(13, 5).unwrap_err();
        assert_eq!(failure.attempts, 0);
        assert_eq!(
            failure.reason,
            "realized true intervention exceeds acquisition-axis leakage gate"
        );
    }

    #[test]
    fn zero_energy_never_searches() {
        let mut scratch = NullScratch::new(4);
        scratch.begin_event();
        for ix in 0..4 {
            scratch.support.push(ix);
            scratch.base[ix] = 0.5;
            scratch.true_target[ix] = 0.5;
            scratch.masked_axis[ix] = 1.0;
        }
        let event = scratch.construct(11, 4).unwrap();
        assert!(event.zero_energy);
        assert_eq!(event.attempts, 0);
    }
}
