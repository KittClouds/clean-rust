use super::*;
use crate::observer::{Observer, PhaseSummary};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Dh03Condition {
    Immediate,
    Quiet,
    RetainBoth,
    SuppressEligibility,
    RestoreState,
    SuppressBoth,
}

impl Dh03Condition {
    fn distractors(self) -> bool {
        matches!(
            self,
            Self::RetainBoth | Self::SuppressEligibility | Self::RestoreState | Self::SuppressBoth
        )
    }

    fn suppress_eligibility(self) -> bool {
        matches!(self, Self::SuppressEligibility | Self::SuppressBoth)
    }

    fn restore_state(self) -> bool {
        matches!(self, Self::RestoreState | Self::SuppressBoth)
    }
}

#[derive(Debug, Serialize)]
pub struct InterventionPhaseSummary {
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
    fn summary(&self) -> InterventionPhaseSummary {
        let n = self.n.max(1) as f64;
        InterventionPhaseSummary {
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
pub struct Dh03Outcome {
    pub outcome: Outcome,
    pub diagnostics: Option<[PhaseSummary; 2]>,
    pub intervention: [InterventionPhaseSummary; 2],
    pub observer_array_bytes: usize,
    pub intervention_array_bytes: usize,
    pub final_weight_floor_fraction: f64,
    pub final_weight_ceiling_fraction: f64,
    pub acquisition_state_sha256: [u8; 32],
}

impl Simulator<'_> {
    pub fn run_dh03(
        &mut self,
        task: &Task,
        condition: Dh03Condition,
        shuffled: &Layer,
        observe: bool,
    ) -> Dh03Outcome {
        let initial = self.weights.clone();
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
        let mut state = StateSnapshot::new(self);
        let intervention_array_bytes = 4 * cue_trace.len() + state.array_bytes();
        let mut intervention: [InterventionAccum; 2] =
            std::array::from_fn(|_| InterventionAccum::default());
        let mut blocks = vec![0_usize; 8];
        let mut phase_correct = [0; 2];
        let mut probe_a = 0.0;
        let mut acquisition_state_sha256 = [0; 32];
        let allocations = crate::allocations();
        let start = Instant::now();
        for (trial, row) in task.schedule.iter().enumerate() {
            let phase = usize::from(trial >= trials / 2);
            let effective = if phase == 0 {
                Dh03Condition::Immediate
            } else {
                condition
            };
            self.eligibility.fill(0.0);
            self.scale = 1.0;
            self.dan.fill(0.5);
            let action = self.event(&task.patterns[row[0]]);
            if let Some(o) = &mut observer {
                o.capture_cue(&self.eligibility, &self.probabilities);
            }
            if effective.distractors() {
                cue_trace.copy_from_slice(&self.eligibility);
                state.capture(self);
            }
            match effective {
                Dh03Condition::Immediate => {}
                Dh03Condition::Quiet => {
                    for _ in &row[1..] {
                        self.event(&blank);
                    }
                }
                _ => {
                    for &d in &row[1..] {
                        self.event(&task.patterns[d]);
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
                if effective.suppress_eligibility() {
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
                if effective.restore_state() {
                    state.restore(self);
                    audit.state_restored += 1;
                    audit.state_error = audit.state_error.max(state.max_abs_error(self));
                }
            }
            let correct = action == task.expected(trial, row[0]);
            let reward = if correct { 1.0 } else { -1.0 };
            if let Some(o) = &mut observer {
                let step = if self.disabled {
                    0.0
                } else {
                    self.eta * reward * self.scale
                };
                o.at_reward(
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
            if matches!(effective, Dh03Condition::Immediate) {
                for _ in 0..(row.len() - 1) * (self.post.len() + 1) {
                    self.rng.next();
                }
            }
            if correct {
                blocks[trial / (trials / 8)] += 1;
                phase_correct[phase] += 1;
            }
            if trial + 1 == trials / 2 {
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
            }
        }
        let probe_b = self.probe(task, true);
        let seconds = start.elapsed().as_secs_f64();
        let hot_allocations = crate::allocations() - allocations;
        assert!(
            self.weights
                .iter()
                .all(|w| w.is_finite() && *w >= 0.0 && *w <= 2.0)
        );
        Dh03Outcome {
            outcome: Outcome {
                accuracy: (phase_correct[0] + phase_correct[1]) as f64 / trials as f64,
                acquisition: phase_correct[0] as f64 / (trials / 2) as f64,
                reversal: phase_correct[1] as f64 / (trials / 2) as f64,
                late_acquisition: blocks[3] as f64 / (trials / 8) as f64,
                late_reversal: blocks[7] as f64 / (trials / 8) as f64,
                probe_acquisition: probe_a,
                probe_reversal: probe_b,
                curve: blocks
                    .into_iter()
                    .map(|v| v as f64 / (trials / 8) as f64)
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
                    .zip(initial)
                    .filter(|(a, b)| **a != *b)
                    .count(),
                max_gain_mass_error: self.max_gain_mass_error,
            },
            diagnostics: observer.as_ref().map(Observer::summary),
            intervention: std::array::from_fn(|i| intervention[i].summary()),
            observer_array_bytes,
            intervention_array_bytes,
            final_weight_floor_fraction: self.weights.iter().filter(|&&w| w == 0.0).count() as f64
                / self.weights.len() as f64,
            final_weight_ceiling_fraction: self.weights.iter().filter(|&&w| w == 2.0).count()
                as f64
                / self.weights.len() as f64,
            acquisition_state_sha256,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const CONDITIONS: [Dh03Condition; 6] = [
        Dh03Condition::Immediate,
        Dh03Condition::Quiet,
        Dh03Condition::RetainBoth,
        Dh03Condition::SuppressEligibility,
        Dh03Condition::RestoreState,
        Dh03Condition::SuppressBoth,
    ];

    #[test]
    fn all_conditions_start_from_identical_acquired_state() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 811, 16, 12, 64);
        for arm in ["E", "Z"] {
            let hashes: Vec<_> = CONDITIONS
                .into_iter()
                .map(|condition| {
                    Simulator::new(&graph, &graph.route, 551, 16.0, 0.05, arm)
                        .run_dh03(&task, condition, &graph.route, true)
                        .acquisition_state_sha256
                })
                .collect();
            assert!(hashes.iter().all(|hash| *hash == hashes[0]));
        }
    }

    #[test]
    fn factorial_interventions_remove_only_assigned_channels() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 99, 16, 12, 64);
        for condition in CONDITIONS[2..].iter().copied() {
            let result = Simulator::new(&graph, &graph.route, 3, 16.0, 0.05, "E").run_dh03(
                &task,
                condition,
                &graph.route,
                true,
            );
            let raw = &result.intervention[1];
            let delivered = &result.diagnostics.as_ref().unwrap()[1];
            assert_eq!(raw.interval_trials, 32);
            assert!(raw.raw_interval_eligibility_l1_mean > 0.0);
            assert!(raw.pre_restore_state_mean_abs_mean > 0.0);
            if condition.suppress_eligibility() {
                assert_eq!(delivered.interval_eligibility_l1_mean, 0.0);
                assert_eq!(raw.eligibility_suppression_applied_trials, 32);
                assert_eq!(raw.eligibility_suppression_max_abs_error, 0.0);
            } else {
                assert!(delivered.interval_eligibility_l1_mean > 0.0);
            }
            if condition.restore_state() {
                assert_eq!(raw.state_restoration_applied_trials, 32);
                assert_eq!(raw.state_restoration_max_abs_error, 0.0);
            }
        }
    }

    #[test]
    fn retain_both_matches_dh02_distractor_exactly() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 2, 16, 12, 64);
        for arm in ["E", "Z"] {
            let mut old = Simulator::new(&graph, &graph.route, 4, 4.0, 0.05, arm);
            let mut new = Simulator::new(&graph, &graph.route, 4, 4.0, 0.05, arm);
            let a = old.run_dh02(&task, Condition::Distractor, &graph.route, true, true);
            let b = new.run_dh03(&task, Dh03Condition::RetainBoth, &graph.route, true);
            assert_eq!(old.weights, new.weights);
            assert_eq!(a.outcome.curve, b.outcome.curve);
            assert_eq!(a.outcome.probe_acquisition, b.outcome.probe_acquisition);
            assert_eq!(a.outcome.probe_reversal, b.outcome.probe_reversal);
        }
    }

    #[test]
    fn observer_cannot_change_factorial_learning_or_actions() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 91, 16, 12, 64);
        for condition in CONDITIONS {
            let mut observed = Simulator::new(&graph, &graph.route, 7, 16.0, 0.05, "E");
            let mut bare = Simulator::new(&graph, &graph.route, 7, 16.0, 0.05, "E");
            let a = observed.run_dh03(&task, condition, &graph.route, true);
            let b = bare.run_dh03(&task, condition, &graph.route, false);
            assert_eq!(observed.weights, bare.weights);
            assert_eq!(a.outcome.curve, b.outcome.curve);
            assert_eq!(a.outcome.probe_reversal, b.outcome.probe_reversal);
            assert_eq!(a.outcome.hot_allocations, 0);
            assert_eq!(b.outcome.hot_allocations, 0);
        }
    }

    #[test]
    fn fixed_weights_preserve_paired_cue_actions_and_rng() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 33, 16, 12, 64);
        let outcomes: Vec<_> = CONDITIONS
            .into_iter()
            .map(|condition| {
                Simulator::new(&graph, &graph.route, 44, 4.0, 0.05, "Z").run_dh03(
                    &task,
                    condition,
                    &graph.route,
                    true,
                )
            })
            .collect();
        for outcome in &outcomes {
            assert_eq!(outcome.outcome.curve, outcomes[0].outcome.curve);
            assert_eq!(outcome.outcome.changed_weights, 0);
            assert_eq!(outcome.outcome.hot_allocations, 0);
        }
        assert_eq!(outcomes[0].outcome.stimulus_events, 64);
        for outcome in &outcomes[1..] {
            assert_eq!(outcome.outcome.stimulus_events, 32 + 32 * 13);
        }
    }

    #[test]
    #[ignore = "explicit DH03 instrumented benchmark"]
    fn benchmark_dh03_factorial() {
        let graph = Graph::fixture();
        let task = Task::new(&graph, 771, 16, 12, 512);
        let mut times = Vec::new();
        for _ in 0..21 {
            let result = Simulator::new(&graph, &graph.route, 992, 16.0, 0.05, "E").run_dh03(
                &task,
                Dh03Condition::SuppressBoth,
                &graph.route,
                true,
            );
            assert_eq!(result.outcome.hot_allocations, 0);
            times.push(result.outcome.seconds);
        }
        times.sort_by(f64::total_cmp);
        println!(
            "DH03 factorial median_seconds={} p95_seconds={} hot_allocations=0",
            times[10], times[19]
        );
    }
}
