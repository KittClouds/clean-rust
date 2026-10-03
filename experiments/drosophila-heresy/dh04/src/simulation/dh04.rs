use super::*;
use crate::observer::{Observer, PhaseSummary};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Dh04Condition {
    Immediate,
    Quiet,
    EligibilityRetained,
    EligibilitySuppressed,
}

impl Dh04Condition {
    fn distractors(self) -> bool {
        matches!(
            self,
            Self::EligibilityRetained | Self::EligibilitySuppressed
        )
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
pub struct Dh04Outcome {
    pub outcome: Outcome,
    pub diagnostics: Option<[PhaseSummary; 2]>,
    pub intervention: [InterventionSummary; 2],
    pub weight_geometry: WeightGeometry,
    pub immediate_reference: Option<ReferenceGeometry>,
    pub paired_final_old_probe: f64,
    pub paired_final_reversal_probe: f64,
    pub observer_array_bytes: usize,
    pub intervention_array_bytes: usize,
    pub acquisition_state_sha256: [u8; 32],
}

pub struct Dh04Run {
    pub condition: Dh04Condition,
    pub result: Dh04Outcome,
    initial: Vec<f32>,
    acquired: Vec<f32>,
    final_weights: Vec<f32>,
}

#[derive(Debug, Serialize)]
pub struct EligibilityContrastGeometry {
    pub retained_minus_suppressed_projection_on_negative_acquisition_axis: Option<f64>,
    pub retained_minus_suppressed_cosine_to_immediate_reversal_delta: Option<f64>,
    pub retained_minus_suppressed_norm_over_acquisition_norm: Option<f64>,
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

pub fn attach_immediate_reference(runs: &mut [Dh04Run]) -> EligibilityContrastGeometry {
    let immediate = runs
        .iter()
        .position(|run| run.condition == Dh04Condition::Immediate)
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
    let retained = runs
        .iter()
        .find(|run| run.condition == Dh04Condition::EligibilityRetained)
        .expect("missing retained condition");
    let suppressed = runs
        .iter()
        .find(|run| run.condition == Dh04Condition::EligibilitySuppressed)
        .expect("missing suppressed condition");
    let acquisition_norm_sq = squared_difference(&retained.acquired, &retained.initial);
    let contrast_norm =
        squared_difference(&retained.final_weights, &suppressed.final_weights).sqrt();
    EligibilityContrastGeometry {
        retained_minus_suppressed_projection_on_negative_acquisition_axis: safe_ratio(
            -dot_difference(
                &retained.final_weights,
                &suppressed.final_weights,
                &retained.acquired,
                &retained.initial,
            ),
            acquisition_norm_sq,
        ),
        retained_minus_suppressed_cosine_to_immediate_reversal_delta: cosine(
            &retained.final_weights,
            &suppressed.final_weights,
            &reference_final,
            &reference_acquired,
        ),
        retained_minus_suppressed_norm_over_acquisition_norm: safe_ratio(
            contrast_norm,
            acquisition_norm_sq.sqrt(),
        ),
    }
}

impl Simulator<'_> {
    fn old_map_margin(&self, task: &Task) -> f64 {
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

    fn paired_probe(&mut self, task: &Task) -> (f64, f64) {
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

    pub fn run_dh04(
        &mut self,
        task: &Task,
        condition: Dh04Condition,
        shuffled: &Layer,
        observe: bool,
    ) -> Dh04Run {
        let initial = self.weights.clone();
        let initial_old_map_margin = self.old_map_margin(task);
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
        let intervention_array_bytes = 4 * (cue_trace.len() + acquired.len()) + state.array_bytes();
        let mut intervention: [InterventionAccum; 2] =
            std::array::from_fn(|_| InterventionAccum::default());
        let mut blocks = vec![0_usize; 8];
        let mut phase_correct = [0; 2];
        let mut probe_a = 0.0;
        let mut acquired_old_map_margin = 0.0;
        let mut acquisition_state_sha256 = [0; 32];
        let allocations = crate::allocations();
        let start = Instant::now();
        for (trial, row) in task.schedule.iter().enumerate() {
            let phase = usize::from(trial >= trials / 2);
            let effective = if phase == 0 {
                Dh04Condition::Immediate
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
                Dh04Condition::Immediate => {}
                Dh04Condition::Quiet => {
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
                if effective == Dh04Condition::EligibilitySuppressed {
                    self.eligibility.copy_from_slice(&cue_trace);
                    audit.eligibility_suppressed += 1;
                    let error = self
                        .eligibility
                        .iter()
                        .zip(&cue_trace)
                        .map(|(&a, &b)| (a - b).abs())
                        .fold(0.0_f32, f32::max);
                    audit.eligibility_error = audit.eligibility_error.max(error);
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
                    &self.eligibility,
                    self.scale,
                    step,
                );
            }
            self.reward(reward);
            if effective == Dh04Condition::Immediate {
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
                acquired_old_map_margin = self.old_map_margin(task);
            }
        }
        let probe_b = self.probe(task, true);
        let (paired_old, paired_reversed) = self.paired_probe(task);
        let final_old_map_margin = self.old_map_margin(task);
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
        Dh04Run {
            condition,
            result: Dh04Outcome {
                outcome,
                diagnostics: observer.as_ref().map(Observer::summary),
                intervention: std::array::from_fn(|index| intervention[index].summary()),
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
            },
            initial,
            acquired,
            final_weights,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const CONDITIONS: [Dh04Condition; 4] = [
        Dh04Condition::Immediate,
        Dh04Condition::Quiet,
        Dh04Condition::EligibilityRetained,
        Dh04Condition::EligibilitySuppressed,
    ];

    #[test]
    fn interventions_and_same_rng_probe_are_exact() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 99, 16, 12, 64);
        for condition in CONDITIONS {
            let run = Simulator::new(&graph, &graph.route, 3, 16.0, 0.05, "E").run_dh04(
                &task,
                condition,
                &graph.route,
                true,
            );
            assert_eq!(
                run.result.paired_final_old_probe + run.result.paired_final_reversal_probe,
                1.0
            );
            if condition.distractors() {
                let audit = &run.result.intervention[1];
                assert_eq!(audit.interval_trials, 32);
                assert!(audit.raw_interval_eligibility_l1_mean > 0.0);
                assert!(audit.pre_restore_state_mean_abs_mean > 0.0);
                assert_eq!(audit.state_restoration_applied_trials, 32);
                assert_eq!(audit.state_restoration_max_abs_error, 0.0);
                let delivered = &run.result.diagnostics.as_ref().unwrap()[1];
                assert_eq!(
                    delivered.interval_eligibility_l1_mean == 0.0,
                    condition == Dh04Condition::EligibilitySuppressed
                );
            }
        }
    }

    #[test]
    fn causal_cells_match_dh03_exactly() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 2, 16, 12, 64);
        for (current, parent) in [
            (
                Dh04Condition::EligibilityRetained,
                crate::simulation::dh03::Dh03Condition::RestoreState,
            ),
            (
                Dh04Condition::EligibilitySuppressed,
                crate::simulation::dh03::Dh03Condition::SuppressBoth,
            ),
        ] {
            let mut old = Simulator::new(&graph, &graph.route, 4, 4.0, 0.05, "E");
            let mut new = Simulator::new(&graph, &graph.route, 4, 4.0, 0.05, "E");
            let a = old.run_dh03(&task, parent, &graph.route, true);
            let b = new.run_dh04(&task, current, &graph.route, true);
            assert_eq!(old.weights, new.weights);
            assert_eq!(a.outcome.curve, b.result.outcome.curve);
            assert_eq!(a.outcome.probe_reversal, b.result.outcome.probe_reversal);
        }
    }

    #[test]
    fn reference_geometry_is_finite_and_self_aligned() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 17, 16, 12, 64);
        let mut runs: Vec<_> = CONDITIONS
            .into_iter()
            .map(|condition| {
                Simulator::new(&graph, &graph.route, 9, 16.0, 0.05, "E").run_dh04(
                    &task,
                    condition,
                    &graph.route,
                    true,
                )
            })
            .collect();
        let contrast = attach_immediate_reference(&mut runs);
        let immediate = &runs[0].result.immediate_reference.as_ref().unwrap();
        assert!((immediate.reversal_delta_cosine_to_immediate.unwrap() - 1.0).abs() < 1e-12);
        assert_eq!(
            immediate
                .distance_to_immediate_final_over_immediate_delta
                .unwrap(),
            0.0
        );
        assert!(
            contrast
                .retained_minus_suppressed_norm_over_acquisition_norm
                .unwrap()
                > 0.0
        );
    }

    #[test]
    fn all_conditions_share_acquisition_and_fixed_weight_actions() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 33, 16, 12, 64);
        let runs: Vec<_> = CONDITIONS
            .into_iter()
            .map(|condition| {
                Simulator::new(&graph, &graph.route, 44, 4.0, 0.05, "Z").run_dh04(
                    &task,
                    condition,
                    &graph.route,
                    true,
                )
            })
            .collect();
        assert!(runs.iter().all(|run| {
            run.result.acquisition_state_sha256 == runs[0].result.acquisition_state_sha256
        }));
        assert!(runs.iter().all(|run| {
            run.result.outcome.curve == runs[0].result.outcome.curve
                && run.result.outcome.changed_weights == 0
                && run.result.outcome.hot_allocations == 0
        }));
    }

    #[test]
    #[ignore = "explicit DH04 geometry benchmark"]
    fn benchmark_dh04_geometry() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 771, 16, 12, 512);
        let mut times = Vec::new();
        for _ in 0..21 {
            let run = Simulator::new(&graph, &graph.route, 992, 16.0, 0.05, "E").run_dh04(
                &task,
                Dh04Condition::EligibilityRetained,
                &graph.route,
                true,
            );
            assert_eq!(run.result.outcome.hot_allocations, 0);
            times.push(run.result.outcome.seconds);
        }
        times.sort_by(f64::total_cmp);
        println!(
            "DH04 geometry median_seconds={} p95_seconds={} hot_allocations=0",
            times[10], times[19]
        );
    }
}
