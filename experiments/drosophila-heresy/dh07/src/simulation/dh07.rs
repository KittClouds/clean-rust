use super::*;
use crate::observer::{Observer, PhaseSummary};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[path = "dh07_null.rs"]
mod null_control;
pub use null_control::{NullEvent, NullFailure, TrueDirectionAudit};
use null_control::NullScratch;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Dh07Condition {
    Immediate,
    Quiet,
    Neither,
    ParallelOnly,
    TruePerpendicular,
    NullPerpendicular,
    BothTrue,
    ParallelNull,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum OffAxis {
    None,
    True,
    Null,
}

impl Dh07Condition {
    fn distractors(self) -> bool {
        matches!(
            self,
            Self::Neither
                | Self::ParallelOnly
                | Self::TruePerpendicular
                | Self::NullPerpendicular
                | Self::BothTrue
                | Self::ParallelNull
        )
    }

    fn geometry(self) -> Option<(bool, OffAxis)> {
        match self {
            Self::Neither => Some((false, OffAxis::None)),
            Self::ParallelOnly => Some((true, OffAxis::None)),
            Self::TruePerpendicular => Some((false, OffAxis::True)),
            Self::NullPerpendicular => Some((false, OffAxis::Null)),
            Self::BothTrue => Some((true, OffAxis::True)),
            Self::ParallelNull => Some((true, OffAxis::Null)),
            Self::Immediate | Self::Quiet => None,
        }
    }
}

#[derive(Debug, Serialize)]
pub struct InterventionSummary {
    pub interval_trials: u64,
    pub raw_interval_eligibility_l1_mean: f64,
    pub pre_restore_state_mean_abs_mean: f64,
    pub eligibility_suppression_applied_trials: u64,
    pub state_restoration_applied_trials: u64,
    pub eligibility_suppression_max_abs_error: f32,
    pub state_restoration_max_abs_error: f32,
}

#[derive(Debug, Serialize)]
pub struct QWindowSummary {
    pub negative: u64,
    pub positive: u64,
    pub zero: u64,
}

#[derive(Debug, Serialize)]
pub struct GeometrySummary {
    pub interval_trials: u64,
    pub realized_interval_l1_mean: f64,
    pub interval_l2_sq: f64,
    pub parallel_l2_sq: f64,
    pub perpendicular_l2_sq: f64,
    pub parallel_energy_fraction: f64,
    pub perpendicular_energy_fraction: f64,
    pub q_negative: u64,
    pub q_positive: u64,
    pub q_zero: u64,
    pub support_zero_events: u64,
    pub reconstruction_max_abs_error: f32,
    pub windows: [QWindowSummary; 5],
}

#[derive(Default)]
struct GeometryAccum {
    n: u64,
    interval_l1: f64,
    interval_l2_sq: f64,
    parallel_l2_sq: f64,
    perpendicular_l2_sq: f64,
    q_negative: u64,
    q_positive: u64,
    q_zero: u64,
    support_zero: u64,
    reconstruction_error: f32,
    windows: [QWindowAccum; 5],
}

#[derive(Default)]
struct QWindowAccum {
    negative: u64,
    positive: u64,
    zero: u64,
}

impl GeometryAccum {
    fn summary(&self) -> GeometrySummary {
        let total = self.interval_l2_sq.max(f64::MIN_POSITIVE);
        GeometrySummary {
            interval_trials: self.n,
            realized_interval_l1_mean: self.interval_l1 / self.n.max(1) as f64,
            interval_l2_sq: self.interval_l2_sq,
            parallel_l2_sq: self.parallel_l2_sq,
            perpendicular_l2_sq: self.perpendicular_l2_sq,
            parallel_energy_fraction: self.parallel_l2_sq / total,
            perpendicular_energy_fraction: self.perpendicular_l2_sq / total,
            q_negative: self.q_negative,
            q_positive: self.q_positive,
            q_zero: self.q_zero,
            support_zero_events: self.support_zero,
            reconstruction_max_abs_error: self.reconstruction_error,
            windows: std::array::from_fn(|index| QWindowSummary {
                negative: self.windows[index].negative,
                positive: self.windows[index].positive,
                zero: self.windows[index].zero,
            }),
        }
    }
}

#[derive(Default)]
struct InterventionAccum {
    n: u64,
    raw_interval_l1: f64,
    state_mean_abs: f64,
    eligibility_suppressed: u64,
    state_restored: u64,
    eligibility_error: f32,
    state_error: f32,
}

impl InterventionAccum {
    fn summary(&self) -> InterventionSummary {
        let n = self.n.max(1) as f64;
        InterventionSummary {
            interval_trials: self.n,
            raw_interval_eligibility_l1_mean: self.raw_interval_l1 / n,
            pre_restore_state_mean_abs_mean: self.state_mean_abs / n,
            eligibility_suppression_applied_trials: self.eligibility_suppressed,
            state_restoration_applied_trials: self.state_restored,
            eligibility_suppression_max_abs_error: self.eligibility_error,
            state_restoration_max_abs_error: self.state_error,
        }
    }
}

struct StateSnapshot {
    baseline: Vec<f32>,
    post: Vec<f32>,
    probabilities: Vec<f32>,
    signed_post: Vec<f32>,
    dan: Vec<f32>,
    feedback: Vec<f32>,
    gain: Vec<f32>,
}

impl StateSnapshot {
    fn new(sim: &Simulator<'_>) -> Self {
        Self {
            baseline: vec![0.0; sim.baseline.len()],
            post: vec![0.0; sim.post.len()],
            probabilities: vec![0.0; sim.probabilities.len()],
            signed_post: vec![0.0; sim.signed_post.len()],
            dan: vec![0.0; sim.dan.len()],
            feedback: vec![0.0; sim.feedback.len()],
            gain: vec![0.0; sim.gain.len()],
        }
    }

    fn capture(&mut self, sim: &Simulator<'_>) {
        self.baseline.copy_from_slice(&sim.baseline);
        self.post.copy_from_slice(&sim.post);
        self.probabilities.copy_from_slice(&sim.probabilities);
        self.signed_post.copy_from_slice(&sim.signed_post);
        self.dan.copy_from_slice(&sim.dan);
        self.feedback.copy_from_slice(&sim.feedback);
        self.gain.copy_from_slice(&sim.gain);
    }

    fn restore(&self, sim: &mut Simulator<'_>) {
        sim.baseline.copy_from_slice(&self.baseline);
        sim.post.copy_from_slice(&self.post);
        sim.probabilities.copy_from_slice(&self.probabilities);
        sim.signed_post.copy_from_slice(&self.signed_post);
        sim.dan.copy_from_slice(&self.dan);
        sim.feedback.copy_from_slice(&self.feedback);
        sim.gain.copy_from_slice(&self.gain);
    }

    fn mean_abs_drift(&self, sim: &Simulator<'_>) -> f64 {
        let mut total = 0.0;
        let mut n = 0;
        macro_rules! add {
            ($saved:expr, $live:expr) => {
                for (&a, &b) in $saved.iter().zip($live) {
                    total += (a as f64 - b as f64).abs();
                    n += 1;
                }
            };
        }
        add!(&self.baseline, &sim.baseline);
        add!(&self.post, &sim.post);
        add!(&self.probabilities, &sim.probabilities);
        add!(&self.signed_post, &sim.signed_post);
        add!(&self.dan, &sim.dan);
        add!(&self.feedback, &sim.feedback);
        add!(&self.gain, &sim.gain);
        total / n as f64
    }

    fn max_abs_error(&self, sim: &Simulator<'_>) -> f32 {
        let mut error = 0.0_f32;
        macro_rules! check {
            ($saved:expr, $live:expr) => {
                for (&a, &b) in $saved.iter().zip($live) {
                    error = error.max((a - b).abs());
                }
            };
        }
        check!(&self.baseline, &sim.baseline);
        check!(&self.post, &sim.post);
        check!(&self.probabilities, &sim.probabilities);
        check!(&self.signed_post, &sim.signed_post);
        check!(&self.dan, &sim.dan);
        check!(&self.feedback, &sim.feedback);
        check!(&self.gain, &sim.gain);
        error
    }

    fn array_bytes(&self) -> usize {
        4 * (self.baseline.len()
            + self.post.len()
            + self.probabilities.len()
            + self.signed_post.len()
            + self.dan.len()
            + self.feedback.len()
            + self.gain.len())
    }
}

#[derive(Debug, Serialize)]
pub struct WeightGeometry {
    pub initial_old_map_margin: f64,
    pub acquired_old_map_margin: f64,
    pub final_old_map_margin: f64,
    pub final_reversal_map_margin: f64,
    pub acquisition_axis_coordinate: Option<f64>,
    pub distance_from_initial_over_acquisition_norm: Option<f64>,
    pub reversal_delta_over_acquisition_norm: Option<f64>,
}

#[derive(Debug, Serialize)]
pub struct ReferenceGeometry {
    pub reversal_delta_cosine_to_immediate: Option<f64>,
    pub distance_to_immediate_final_over_immediate_delta: Option<f64>,
}

#[derive(Debug, Serialize)]
pub struct Dh07Outcome {
    pub outcome: Outcome,
    pub diagnostics: Option<[PhaseSummary; 2]>,
    pub intervention: [InterventionSummary; 2],
    pub geometry: GeometrySummary,
    pub weight_geometry: WeightGeometry,
    pub immediate_reference: Option<ReferenceGeometry>,
    pub paired_final_old_probe: f64,
    pub paired_final_reversal_probe: f64,
    pub observer_array_bytes: usize,
    pub intervention_array_bytes: usize,
    pub acquisition_state_sha256: [u8; 32],
    pub trajectory: Vec<TrajectoryPoint>,
    pub null_events: Vec<NullEvent>,
    pub true_direction_events: Vec<TrueDirectionAudit>,
}

#[derive(Debug, Serialize)]
pub struct TrajectoryPoint {
    pub reversal_trials: usize,
    pub old_map_margin: f64,
    pub reversed_map_margin: f64,
    pub acquisition_axis_coordinate: Option<f64>,
    pub acquisition_axis_projection: Option<f64>,
    pub reversal_parallel_projection: Option<f64>,
    pub reversal_perpendicular_norm: Option<f64>,
}

pub struct Dh07Run {
    pub condition: Dh07Condition,
    pub result: Dh07Outcome,
    initial: Vec<f32>,
    acquired: Vec<f32>,
    final_weights: Vec<f32>,
}

#[derive(Debug, Serialize)]
pub struct EligibilityContrastGeometry {
    pub both_minus_neither_projection_on_negative_acquisition_axis: Option<f64>,
    pub both_minus_neither_cosine_to_immediate_reversal_delta: Option<f64>,
    pub both_minus_neither_norm_over_acquisition_norm: Option<f64>,
}

fn dot_difference(a: &[f32], b: &[f32], c: &[f32], d: &[f32]) -> f64 {
    a.iter()
        .zip(b)
        .zip(c)
        .zip(d)
        .map(|(((&x, &y), &u), &v)| (x as f64 - y as f64) * (u as f64 - v as f64))
        .sum()
}

fn squared_difference(a: &[f32], b: &[f32]) -> f64 {
    dot_difference(a, b, a, b)
}

fn safe_ratio(numerator: f64, denominator: f64) -> Option<f64> {
    (denominator > 0.0).then_some(numerator / denominator)
}

fn cosine(a: &[f32], b: &[f32], c: &[f32], d: &[f32]) -> Option<f64> {
    let numerator = dot_difference(a, b, c, d);
    let denominator = (squared_difference(a, b) * squared_difference(c, d)).sqrt();
    safe_ratio(numerator, denominator)
}

fn realized_delta(weight: f32, eligibility: f32, step: f32) -> f32 {
    (weight + step * eligibility).clamp(0.0, 2.0) - weight
}

fn reversal_window(trials: usize) -> usize {
    match trials {
        1..=16 => 0,
        17..=32 => 1,
        33..=64 => 2,
        65..=128 => 3,
        _ => 4,
    }
}

struct GeometryInput<'a> {
    parallel: bool,
    off_axis: OffAxis,
    cue_trace: &'a [f32],
    initial: &'a [f32],
    acquired: &'a [f32],
    geometry: &'a mut GeometryAccum,
    reversal_trials: usize,
    null_key: u64,
    null_scratch: &'a mut NullScratch,
    null_events: &'a mut Vec<NullEvent>,
    true_direction_events: &'a mut Vec<TrueDirectionAudit>,
}

pub fn attach_immediate_reference_dh07(runs: &mut [Dh07Run]) -> EligibilityContrastGeometry {
    let immediate = runs
        .iter()
        .position(|run| run.condition == Dh07Condition::Immediate)
        .expect("missing immediate reference");
    let reference_acquired = runs[immediate].acquired.clone();
    let reference_final = runs[immediate].final_weights.clone();
    for run in runs.iter_mut() {
        let delta_cosine = cosine(
            &run.final_weights,
            &run.acquired,
            &reference_final,
            &reference_acquired,
        );
        let reference_norm = squared_difference(&reference_final, &reference_acquired).sqrt();
        let distance = squared_difference(&run.final_weights, &reference_final).sqrt();
        run.result.immediate_reference = Some(ReferenceGeometry {
            reversal_delta_cosine_to_immediate: delta_cosine,
            distance_to_immediate_final_over_immediate_delta: safe_ratio(distance, reference_norm),
        });
    }
    let both = runs
        .iter()
        .find(|run| run.condition == Dh07Condition::BothTrue)
        .expect("missing both condition");
    let neither = runs
        .iter()
        .find(|run| run.condition == Dh07Condition::Neither)
        .expect("missing neither condition");
    let acquisition_norm_sq = squared_difference(&both.acquired, &both.initial);
    let contrast_norm = squared_difference(&both.final_weights, &neither.final_weights).sqrt();
    EligibilityContrastGeometry {
        both_minus_neither_projection_on_negative_acquisition_axis: safe_ratio(
            -dot_difference(
                &both.final_weights,
                &neither.final_weights,
                &both.acquired,
                &both.initial,
            ),
            acquisition_norm_sq,
        ),
        both_minus_neither_cosine_to_immediate_reversal_delta: cosine(
            &both.final_weights,
            &neither.final_weights,
            &reference_final,
            &reference_acquired,
        ),
        both_minus_neither_norm_over_acquisition_norm: safe_ratio(
            contrast_norm,
            acquisition_norm_sq.sqrt(),
        ),
    }
}

impl Simulator<'_> {
    fn trajectory_point_dh07(
        &self,
        task: &Task,
        initial: &[f32],
        acquired: &[f32],
        reversal_trials: usize,
    ) -> TrajectoryPoint {
        let old_map_margin = self.old_map_margin_dh07(task);
        let acquisition_norm_sq = squared_difference(acquired, initial);
        let acquisition_norm = acquisition_norm_sq.sqrt();
        let acquisition_axis_coordinate = safe_ratio(
            dot_difference(&self.weights, initial, acquired, initial),
            acquisition_norm_sq,
        );
        let acquisition_axis_projection = safe_ratio(
            dot_difference(&self.weights, initial, acquired, initial),
            acquisition_norm,
        );
        let reversal_parallel_projection = safe_ratio(
            dot_difference(&self.weights, acquired, acquired, initial),
            acquisition_norm,
        );
        let reversal_sq = squared_difference(&self.weights, acquired);
        let parallel_sq = reversal_parallel_projection
            .map(|value| value * value)
            .unwrap_or(0.0);
        let reversal_perpendicular_norm = (reversal_sq - parallel_sq).max(0.0).sqrt();
        TrajectoryPoint {
            reversal_trials,
            old_map_margin,
            reversed_map_margin: -old_map_margin,
            acquisition_axis_coordinate,
            acquisition_axis_projection,
            reversal_parallel_projection,
            reversal_perpendicular_norm: safe_ratio(reversal_perpendicular_norm, acquisition_norm),
        }
    }

    fn old_map_margin_dh07(&self, task: &Task) -> f64 {
        let mut total = 0.0;
        for cue in 0..task.cues {
            let pattern = &task.patterns[cue];
            let mut score = 0.0;
            for j in 0..self.post.len() {
                let drive: f32 = pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]]
                    .iter()
                    .map(|&index| self.weights[index])
                    .sum();
                let probability = sigmoid(2.0 * (drive / self.denom[j] - self.bias[j]));
                score += self.action_sign[j] * (probability - 0.5);
            }
            let target = if task.labels[cue] { 1.0 } else { -1.0 };
            total += target * score as f64 / self.post.len() as f64;
        }
        total / task.cues as f64
    }

    fn paired_probe_dh07(&mut self, task: &Task) -> (f64, f64) {
        let saved = self.rng.clone();
        self.rng = Rng(0x44_480_044);
        let mut old = 0;
        let mut reversed = 0;
        for _ in 0..16 {
            for cue in 0..task.cues {
                let action = self.sample(&task.patterns[cue]);
                old += usize::from(action == task.labels[cue]);
                reversed += usize::from(action != task.labels[cue]);
            }
        }
        self.rng = saved;
        let n = (16 * task.cues) as f64;
        (old as f64 / n, reversed as f64 / n)
    }

    fn apply_dh07_geometric_reward(
        &mut self,
        reward: f32,
        input: GeometryInput<'_>,
    ) -> Result<(), NullFailure> {
        let GeometryInput {
            parallel,
            off_axis,
            cue_trace,
            initial,
            acquired,
            geometry,
            reversal_trials,
            null_key,
            null_scratch,
            null_events,
            true_direction_events,
        } = input;
        if self.disabled {
            return Ok(());
        }
        if self.uniform {
            self.gain.fill(1.0);
        } else {
            for j in 0..self.gain.len() {
                let row = self.route.row(j);
                self.gain[j] = if row.is_empty() {
                    0.0
                } else {
                    self.route.edges[row.clone()]
                        .iter()
                        .map(|e| self.dan[e.pre as usize])
                        .sum::<f32>()
                        / row.len() as f32
                };
            }
            let mass: f32 = self
                .gain
                .iter()
                .enumerate()
                .map(|(j, g)| g * self.graph.kc_mb.row(j).len() as f32)
                .sum();
            assert!(mass > 0.0, "no delivered modulation");
            let norm = self.weights.len() as f32 / mass;
            for g in &mut self.gain {
                *g *= norm;
            }
        }
        let mass: f32 = self
            .gain
            .iter()
            .enumerate()
            .map(|(j, g)| g * self.graph.kc_mb.row(j).len() as f32)
            .sum();
        self.max_gain_mass_error = self
            .max_gain_mass_error
            .max((mass / self.weights.len() as f32 - 1.0).abs());

        let mut q = 0.0_f64;
        let mut support_norm_sq = 0.0_f64;
        let mut interval_l2_sq = 0.0_f64;
        for j in 0..self.gain.len() {
            let step = self.eta * reward * self.gain[j] * self.scale;
            for ix in self.graph.kc_mb.row(j) {
                let retained = realized_delta(self.weights[ix], self.eligibility[ix], step);
                let suppressed = realized_delta(self.weights[ix], cue_trace[ix], step);
                let delta = retained - suppressed;
                interval_l2_sq += f64::from(delta) * f64::from(delta);
                if delta != 0.0 {
                    let axis = f64::from(acquired[ix] - initial[ix]);
                    q += f64::from(delta) * axis;
                    support_norm_sq += axis * axis;
                }
            }
        }
        let coefficient = if support_norm_sq > 0.0 {
            q / support_norm_sq
        } else {
            geometry.support_zero += 1;
            0.0
        };
        let mut interval_l1 = 0.0_f64;
        let mut parallel_l2_sq = 0.0_f64;
        let mut perpendicular_l2_sq = 0.0_f64;
        let mut reconstruction_error = 0.0_f32;
        null_scratch.begin_event();
        for j in 0..self.gain.len() {
            let step = self.eta * reward * self.gain[j] * self.scale;
            for ix in self.graph.kc_mb.row(j) {
                let weight = self.weights[ix];
                let retained_new = (weight + step * self.eligibility[ix]).clamp(0.0, 2.0);
                let suppressed_new = (weight + step * cue_trace[ix]).clamp(0.0, 2.0);
                let delta = retained_new - suppressed_new;
                let axis = if delta != 0.0 {
                    f64::from(acquired[ix] - initial[ix])
                } else {
                    0.0
                };
                let parallel_component = (coefficient * axis) as f32;
                let perpendicular = delta - parallel_component;
                let base = (suppressed_new
                    + if parallel { parallel_component } else { 0.0 })
                    .clamp(0.0, 2.0);
                let true_target = if parallel {
                    retained_new
                } else {
                    (suppressed_new + perpendicular).clamp(0.0, 2.0)
                };
                null_scratch.base[ix] = base;
                null_scratch.true_target[ix] = true_target;
                if delta != 0.0 {
                    null_scratch.support.push(ix);
                    null_scratch.masked_axis[ix] = axis;
                }
                interval_l1 += f64::from(delta.abs());
                parallel_l2_sq +=
                    f64::from(parallel_component) * f64::from(parallel_component);
                perpendicular_l2_sq +=
                    f64::from(perpendicular) * f64::from(perpendicular);
                reconstruction_error = reconstruction_error.max(
                    (delta - parallel_component - perpendicular).abs(),
                );
            }
        }
        true_direction_events.push(null_scratch.audit_true(reversal_trials));
        match off_axis {
            OffAxis::None => self.weights.copy_from_slice(&null_scratch.base),
            OffAxis::True => self.weights.copy_from_slice(&null_scratch.true_target),
            OffAxis::Null => {
                let event = null_scratch.construct(null_key, reversal_trials)?;
                self.weights.copy_from_slice(&null_scratch.null_target);
                null_events.push(event);
            }
        }
        geometry.n += 1;
        geometry.interval_l1 += interval_l1;
        geometry.interval_l2_sq += interval_l2_sq;
        geometry.parallel_l2_sq += parallel_l2_sq;
        geometry.perpendicular_l2_sq += perpendicular_l2_sq;
        geometry.reconstruction_error = geometry.reconstruction_error.max(reconstruction_error);
        if q < -1e-12 {
            geometry.q_negative += 1;
            geometry.windows[reversal_window(reversal_trials)].negative += 1;
        } else if q > 1e-12 {
            geometry.q_positive += 1;
            geometry.windows[reversal_window(reversal_trials)].positive += 1;
        } else {
            geometry.q_zero += 1;
            geometry.windows[reversal_window(reversal_trials)].zero += 1;
        }
        self.work += (self.weights.len()
            + if self.uniform {
                0
            } else {
                self.route.edges.len()
            }) as u64;
        Ok(())
    }

    pub fn run_dh07(
        &mut self,
        task: &Task,
        condition: Dh07Condition,
        shuffled: &Layer,
        observe: bool,
        null_key: u64,
    ) -> Result<Dh07Run, NullFailure> {
        let initial = self.weights.clone();
        let initial_old_map_margin = self.old_map_margin_dh07(task);
        let trials = task.schedule.len();
        assert!(trials.is_multiple_of(8));
        let blank = Pattern {
            edges: Vec::new(),
            offsets: vec![0; self.graph.kc_mb.n_post + 1],
            dan: vec![0.0; self.graph.kc_dan.n_post],
            active_kc: Vec::new(),
        };
        let mut observer = observe.then(|| Observer::new(self.graph));
        let observer_array_bytes = observer.as_ref().map_or(0, Observer::array_bytes);
        let mut cue_trace = vec![0.0; self.eligibility.len()];
        let mut acquired = vec![0.0; self.weights.len()];
        let mut state = StateSnapshot::new(self);
        let mut null_scratch = NullScratch::new(self.weights.len());
        let mut null_events = Vec::with_capacity(trials / 2);
        let mut true_direction_events = Vec::with_capacity(trials / 2);
        let intervention_array_bytes = 4 * (cue_trace.len() + acquired.len())
            + state.array_bytes()
            + null_scratch.array_bytes();
        let mut intervention: [InterventionAccum; 2] =
            std::array::from_fn(|_| InterventionAccum::default());
        let mut blocks = vec![0_usize; 8];
        let mut phase_correct = [0; 2];
        let mut probe_a = 0.0;
        let mut acquired_old_map_margin = 0.0;
        let mut acquisition_state_sha256 = [0; 32];
        let mut trajectory = Vec::with_capacity(6);
        let mut geometry = GeometryAccum::default();
        let allocations = crate::allocations();
        let start = Instant::now();
        for (trial, row) in task.schedule.iter().enumerate() {
            let phase = usize::from(trial >= trials / 2);
            let effective = if phase == 0 {
                Dh07Condition::Immediate
            } else {
                condition
            };
            self.eligibility.fill(0.0);
            self.scale = 1.0;
            self.dan.fill(0.5);
            let action = self.event(&task.patterns[row[0]]);
            if let Some(observer) = &mut observer {
                observer.capture_cue(&self.eligibility, &self.probabilities);
            }
            if effective.distractors() {
                cue_trace.copy_from_slice(&self.eligibility);
                state.capture(self);
            }
            match effective {
                Dh07Condition::Immediate => {}
                Dh07Condition::Quiet => {
                    for _ in &row[1..] {
                        self.event(&blank);
                    }
                }
                _ => {
                    for &distractor in &row[1..] {
                        self.event(&task.patterns[distractor]);
                    }
                }
            }
            if effective.distractors() {
                let audit = &mut intervention[phase];
                audit.n += 1;
                audit.raw_interval_l1 += self
                    .eligibility
                    .iter()
                    .zip(&cue_trace)
                    .map(|(&total, &cue)| ((total - cue) * self.scale).abs() as f64)
                    .sum::<f64>();
                audit.state_mean_abs += state.mean_abs_drift(self);
                if effective == Dh07Condition::Neither {
                    audit.eligibility_suppressed += 1;
                    audit.eligibility_error = 0.0;
                }
                state.restore(self);
                audit.state_restored += 1;
                audit.state_error = audit.state_error.max(state.max_abs_error(self));
            }
            let correct = action == task.expected(trial, row[0]);
            let reward = if correct { 1.0 } else { -1.0 };
            if let Some(observer) = &mut observer {
                let step = if self.disabled {
                    0.0
                } else {
                    self.eta * reward * self.scale
                };
                observer.at_reward(
                    phase,
                    self.graph,
                    shuffled,
                    &self.dan,
                    &self.weights,
                    if effective == Dh07Condition::Neither {
                        &cue_trace
                    } else {
                        &self.eligibility
                    },
                    self.scale,
                    step,
                );
            }
            if let Some((parallel, off_axis)) = effective.geometry() {
                let reversal_trials = trial + 1 - trials / 2;
                self.apply_dh07_geometric_reward(
                    reward,
                    GeometryInput {
                        parallel,
                        off_axis,
                        cue_trace: &cue_trace,
                        initial: &initial,
                        acquired: &acquired,
                        geometry: &mut geometry,
                        reversal_trials,
                        null_key,
                        null_scratch: &mut null_scratch,
                        null_events: &mut null_events,
                        true_direction_events: &mut true_direction_events,
                    },
                )?;
                if effective == Dh07Condition::Neither {
                    self.eligibility.copy_from_slice(&cue_trace);
                }
            } else {
                self.reward(reward);
            }
            if effective == Dh07Condition::Immediate {
                for _ in 0..(row.len() - 1) * (self.post.len() + 1) {
                    self.rng.next();
                }
            }
            if correct {
                blocks[trial / (trials / 8)] += 1;
                phase_correct[phase] += 1;
            }
            if trial + 1 == trials / 2 {
                acquired.copy_from_slice(&self.weights);
                let mut hash = Sha256::new();
                for array in [
                    &self.weights,
                    &self.eligibility,
                    &self.baseline,
                    &self.post,
                    &self.dan,
                    &self.feedback,
                    &self.gain,
                ] {
                    for value in array {
                        hash.update(value.to_bits().to_le_bytes());
                    }
                }
                hash.update(self.rng.0.to_le_bytes());
                acquisition_state_sha256 = hash.finalize().into();
                probe_a = self.probe(task, false);
                acquired_old_map_margin = self.old_map_margin_dh07(task);
                    trajectory.push(self.trajectory_point_dh07(task, &initial, &acquired, 0));
            }
            if phase == 1 {
                let reversal_trials = trial + 1 - trials / 2;
                if [16, 32, 64, 128, 256].contains(&reversal_trials) {
                    trajectory.push(self.trajectory_point_dh07(
                        task,
                        &initial,
                        &acquired,
                        reversal_trials,
                    ));
                }
            }
        }
        let probe_b = self.probe(task, true);
        let (paired_old, paired_reversed) = self.paired_probe_dh07(task);
        let final_old_map_margin = self.old_map_margin_dh07(task);
        let acquisition_norm_sq = squared_difference(&acquired, &initial);
        let coordinate = safe_ratio(
            dot_difference(&self.weights, &initial, &acquired, &initial),
            acquisition_norm_sq,
        );
        let distance = squared_difference(&self.weights, &initial).sqrt();
        let reversal_delta = squared_difference(&self.weights, &acquired).sqrt();
        let seconds = start.elapsed().as_secs_f64();
        let hot_allocations = crate::allocations() - allocations;
        let final_weights = self.weights.clone();
        let outcome = Outcome {
            accuracy: (phase_correct[0] + phase_correct[1]) as f64 / trials as f64,
            acquisition: phase_correct[0] as f64 / (trials / 2) as f64,
            reversal: phase_correct[1] as f64 / (trials / 2) as f64,
            late_acquisition: blocks[3] as f64 / (trials / 8) as f64,
            late_reversal: blocks[7] as f64 / (trials / 8) as f64,
            probe_acquisition: probe_a,
            probe_reversal: probe_b,
            curve: blocks
                .into_iter()
                .map(|value| value as f64 / (trials / 8) as f64)
                .collect(),
            seconds,
            work: self.work,
            stimulus_events: self.events,
            state_bytes: 4
                * (self.weights.len() * 2 + self.baseline.len() * 8 + self.dan.len() * 2),
            hot_allocations,
            unique_cue_codes: task.unique_cue_codes(),
            changed_weights: self
                .weights
                .iter()
                .zip(&initial)
                .filter(|(a, b)| *a != *b)
                .count(),
            max_gain_mass_error: self.max_gain_mass_error,
        };
        Ok(Dh07Run {
            condition,
            result: Dh07Outcome {
                outcome,
                diagnostics: observer.as_ref().map(Observer::summary),
                intervention: std::array::from_fn(|index| intervention[index].summary()),
                geometry: geometry.summary(),
                weight_geometry: WeightGeometry {
                    initial_old_map_margin,
                    acquired_old_map_margin,
                    final_old_map_margin,
                    final_reversal_map_margin: -final_old_map_margin,
                    acquisition_axis_coordinate: coordinate,
                    distance_from_initial_over_acquisition_norm: safe_ratio(
                        distance,
                        acquisition_norm_sq.sqrt(),
                    ),
                    reversal_delta_over_acquisition_norm: safe_ratio(
                        reversal_delta,
                        acquisition_norm_sq.sqrt(),
                    ),
                },
                immediate_reference: None,
                paired_final_old_probe: paired_old,
                paired_final_reversal_probe: paired_reversed,
                observer_array_bytes,
                intervention_array_bytes,
                acquisition_state_sha256,
                trajectory,
                null_events,
                true_direction_events,
            },
            initial,
            acquired,
            final_weights,
        })
    }
}


#[cfg(test)]
#[path = "dh07_tests.rs" ]
mod tests;

