use super::*;
use crate::observer::{Observer, PhaseSummary};
use sha2::{Digest, Sha256};

#[derive(Clone, Copy, Debug, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Condition {
    Immediate,
    Quiet,
    Distractor,
}
#[derive(Serialize, Debug)]
pub struct DiagnosticOutcome {
    pub outcome: Outcome,
    pub diagnostics: Option<[PhaseSummary; 2]>,
    pub observer_array_bytes: usize,
    pub final_weight_floor_fraction: f64,
    pub final_weight_ceiling_fraction: f64,
    pub acquisition_state_sha256: [u8; 32],
}
impl Simulator<'_> {
    pub fn run_dh02(
        &mut self,
        task: &Task,
        condition: Condition,
        shuffled: &Layer,
        observe: bool,
        shared_acquisition: bool,
    ) -> DiagnosticOutcome {
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
        let mut blocks = vec![0_usize; 8];
        let mut phase_correct = [0; 2];
        let mut probe_a = 0.0;
        let mut acquisition_state_sha256 = [0; 32];
        let allocations = crate::allocations();
        let start = Instant::now();
        for (trial, row) in task.schedule.iter().enumerate() {
            let phase = usize::from(trial >= trials / 2);
            let effective = if shared_acquisition && phase == 0 {
                Condition::Immediate
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
            match effective {
                Condition::Immediate => {}
                Condition::Quiet => {
                    for _ in &row[1..] {
                        self.event(&blank);
                    }
                }
                Condition::Distractor => {
                    for &d in &row[1..] {
                        self.event(&task.patterns[d]);
                    }
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
            // Align the next cue's RNG stream without advancing neuronal time or state.
            if matches!(effective, Condition::Immediate) {
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
        let diagnostics = observer.as_ref().map(Observer::summary);
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
        };
        DiagnosticOutcome {
            outcome,
            diagnostics,
            observer_array_bytes,
            acquisition_state_sha256,
            final_weight_floor_fraction: self.weights.iter().filter(|&&w| w == 0.0).count() as f64
                / self.weights.len() as f64,
            final_weight_ceiling_fraction: self.weights.iter().filter(|&&w| w == 2.0).count()
                as f64
                / self.weights.len() as f64,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn conditions_start_reversal_from_identical_acquired_state() {
        let g = Graph::fixture();
        let t = Task::new(&g, 811, 16, 12, 64);
        for arm in ["E", "Z"] {
            let mut hashes = Vec::new();
            for c in [
                Condition::Immediate,
                Condition::Quiet,
                Condition::Distractor,
            ] {
                let r = Simulator::new(&g, &g.route, 551, 16.0, 0.05, arm)
                    .run_dh02(&t, c, &g.route, true, true);
                hashes.push(r.acquisition_state_sha256);
            }
            assert!(hashes.iter().all(|h| *h == hashes[0]));
        }
    }
    #[test]
    #[ignore = "explicit DH02 instrumented benchmark"]
    fn benchmark_dh02_observer() {
        let g = Graph::fixture();
        let t = Task::new(&g, 771, 16, 12, 512);
        let (r, _) = g.route.rewired(775);
        let mut times = Vec::new();
        for _ in 0..21 {
            let out = Simulator::new(&g, &g.route, 992, 16.0, 0.05, "E").run_dh02(
                &t,
                Condition::Distractor,
                &r,
                true,
                true,
            );
            assert_eq!(out.outcome.hot_allocations, 0);
            times.push(out.outcome.seconds);
        }
        times.sort_by(f64::total_cmp);
        println!(
            "DH02 synthetic instrumented median_seconds={} p95_seconds={} hot_allocations=0",
            times[10], times[19]
        );
    }
    #[test]
    fn blank_advances_dynamics_and_decay_without_sensory_eligibility() {
        let g = Graph::fixture();
        let t = Task::new(&g, 7, 16, 12, 32);
        let mut s = Simulator::new(&g, &g.route, 9, 4.0, 0.05, "E");
        s.event(&t.patterns[0]);
        let trace = s.eligibility.clone();
        let scale = s.scale;
        let events = s.events;
        let baseline = s.baseline.clone();
        let blank = Pattern {
            edges: vec![],
            offsets: vec![0; g.kc_mb.n_post + 1],
            dan: vec![0.0; g.kc_dan.n_post],
            active_kc: vec![],
        };
        s.event(&blank);
        assert_eq!(trace, s.eligibility);
        assert_eq!(s.scale, scale * s.lambda);
        assert_eq!(s.events, events + 1);
        assert_ne!(s.baseline, baseline);
    }
    #[test]
    fn observer_cannot_change_weights_or_actions_and_delay_decomposition_is_exact() {
        let g = Graph::fixture();
        let t = Task::new(&g, 99, 16, 12, 64);
        let (route, _) = g.route.rewired(101);
        for c in [
            Condition::Immediate,
            Condition::Quiet,
            Condition::Distractor,
        ] {
            let mut a = Simulator::new(&g, &g.route, 3, 16.0, 0.05, "E");
            let mut b = Simulator::new(&g, &g.route, 3, 16.0, 0.05, "E");
            let x = a.run_dh02(&t, c, &route, true, true);
            let y = b.run_dh02(&t, c, &route, false, true);
            assert_eq!(a.weights, b.weights);
            assert_eq!(x.outcome.curve, y.outcome.curve);
            assert_eq!(x.outcome.probe_reversal, y.outcome.probe_reversal);
            assert_eq!(x.outcome.hot_allocations, 0);
            assert_eq!(y.outcome.hot_allocations, 0);
            let d = x.diagnostics.unwrap();
            if !matches!(c, Condition::Distractor) {
                assert_eq!(d[1].interval_eligibility_l1_mean, 0.0);
            } else {
                assert!(d[1].interval_eligibility_l1_mean > 0.0);
            }
        }
    }
    #[test]
    fn distractor_condition_matches_frozen_dh01_engine() {
        let g = Graph::fixture();
        let t = Task::new(&g, 2, 16, 12, 64);
        for arm in ["E", "Z"] {
            let mut old = crate::baseline::Simulator::new(&g, &g.route, 4, 4.0, 0.05, arm);
            let mut new = Simulator::new(&g, &g.route, 4, 4.0, 0.05, arm);
            let a = old.run(&t);
            let b = new.run_dh02(&t, Condition::Distractor, &g.route, true, false);
            assert_eq!(old.weights, new.weights);
            assert_eq!(a.curve, b.outcome.curve);
            assert_eq!(a.probe_acquisition, b.outcome.probe_acquisition);
            assert_eq!(a.probe_reversal, b.outcome.probe_reversal);
        }
    }
    #[test]
    fn no_learning_conditions_share_actions_despite_different_delay_lengths() {
        let g = Graph::fixture();
        let t = Task::new(&g, 33, 16, 12, 64);
        let outcomes: Vec<_> = [
            Condition::Immediate,
            Condition::Quiet,
            Condition::Distractor,
        ]
        .into_iter()
        .map(|c| {
            Simulator::new(&g, &g.route, 44, 4.0, 0.05, "Z").run_dh02(&t, c, &g.route, true, true)
        })
        .collect();
        for o in &outcomes {
            assert_eq!(o.outcome.curve, outcomes[0].outcome.curve);
            assert_eq!(o.outcome.changed_weights, 0);
        }
        assert_eq!(outcomes[0].outcome.stimulus_events, 64);
        assert_eq!(outcomes[1].outcome.stimulus_events, 32 + 32 * 13);
    }
}
