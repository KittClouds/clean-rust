use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Clone, Serialize, Deserialize)]
pub struct Snapshot {
    pub trial: usize,
    pub base: Vec<f32>,
    pub target: Vec<f32>,
    pub axis: Vec<f64>,
    pub permitted: Vec<bool>,
}
impl Snapshot {
    fn new(n: usize) -> Self {
        Self { trial: 0, base: vec![0.; n], target: vec![0.; n],
               axis: vec![0.; n], permitted: vec![false; n] }
    }
    fn copy(&mut self, source: &Self) {
        self.trial = source.trial;
        self.base.copy_from_slice(&source.base);
        self.target.copy_from_slice(&source.target);
        self.axis.copy_from_slice(&source.axis);
        self.permitted.copy_from_slice(&source.permitted);
    }
}
#[derive(Default, Clone, Serialize)]
pub struct ClampEvent {
    pub trial: usize,
    pub clamp_coordinates: usize,
    pub clamp_l1: f64,
    pub clamp_l2_sq: f64,
    pub clamp_axis_dot: f64,
    pub clamp_coordinate_change: f64,
    pub commit_minus_clamp_l1: f64,
    pub commit_minus_clamp_axis_dot: f64,
    pub common_base_clamp_axis_dot: f64,
    pub common_base_clamp_l1: f64,
    pub incremental_clamp_axis_dot: f64,
    pub axis_norm_sq: f64,
    pub true_bound_count: usize,
    pub allowed_support: usize,
}
pub struct Capture {
    pub slots: Vec<Snapshot>,
    pub events: Vec<ClampEvent>,
    pub current: Snapshot,
    /// Exact committed-f32 ordinary-true endpoints, one per reversal event.
    pub true_endpoint_sha256: Vec<[u8; 32]>,
    event: ClampEvent,
    max_bounds: usize,
    min_bounds: usize,
}
impl Capture {
    pub fn new(n: usize) -> Self {
        Self { slots: (0..8).map(|_| Snapshot::new(n)).collect(),
               events: Vec::with_capacity(256), current: Snapshot::new(n),
               true_endpoint_sha256: Vec::with_capacity(256),
               event: ClampEvent::default(), max_bounds: 0, min_bounds: usize::MAX }
    }
    pub fn begin(&mut self, trial: usize, initial: &[f32], acquired: &[f32]) {
        self.current.trial = trial;
        self.event = ClampEvent { trial, ..Default::default() };
        for ((a, &w0), &wa) in self.current.axis.iter_mut().zip(initial).zip(acquired) {
            *a = f64::from(wa) - f64::from(w0);
            self.event.axis_norm_sq += *a * *a;
        }
    }
    pub fn edge(&mut self, i: usize, base: f32, target: f32, permitted: bool,
                candidate: f32, stored: f32) {
        self.current.base[i] = base;
        self.current.target[i] = target;
        self.current.permitted[i] = permitted;
        assert!(permitted || base == target, "true displacement outside pre-bound support");
        let clamped = candidate.clamp(0., 2.);
        let correction = f64::from(clamped) - f64::from(candidate);
        let rounding = f64::from(stored) - f64::from(clamped);
        self.event.clamp_coordinates += usize::from(correction != 0.);
        self.event.clamp_l1 += correction.abs();
        self.event.clamp_l2_sq += correction * correction;
        self.event.clamp_axis_dot += correction * self.current.axis[i];
        self.event.commit_minus_clamp_l1 += rounding.abs();
        self.event.commit_minus_clamp_axis_dot += rounding * self.current.axis[i];
        self.event.true_bound_count += usize::from(target == 0. || target == 2.);
        self.event.allowed_support += usize::from(permitted);
    }
    pub fn finish(&mut self) {
        let mut hash = Sha256::new();
        for value in &self.current.target {
            hash.update(value.to_bits().to_le_bytes());
        }
        self.true_endpoint_sha256.push(hash.finalize().into());
        self.event.incremental_clamp_axis_dot=self.event.clamp_axis_dot-self.event.common_base_clamp_axis_dot;
        self.event.clamp_coordinate_change = if self.event.axis_norm_sq > 0. {
            self.event.clamp_axis_dot / self.event.axis_norm_sq
        } else { 0. };
        if let Some(slot) = [1,16,32,64,128,256].iter().position(|&t| t == self.current.trial) {
            self.slots[slot].copy(&self.current);
        }
        if self.current.trial == 1 || self.event.true_bound_count > self.max_bounds {
            self.max_bounds = self.event.true_bound_count;
            self.slots[6].copy(&self.current);
        }
        if self.event.true_bound_count < self.min_bounds {
            self.min_bounds = self.event.true_bound_count;
            self.slots[7].copy(&self.current);
        }
        self.events.push(self.event.clone());
    }
    pub fn base_edge(&mut self,i:usize,candidate:f32,base:f32) {
        let correction=f64::from(base)-f64::from(candidate);
        self.event.common_base_clamp_axis_dot+=correction*self.current.axis[i];
        self.event.common_base_clamp_l1+=correction.abs();
    }
}
