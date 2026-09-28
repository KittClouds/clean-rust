use crate::{
    graph::{Graph, Layer},
    plasticity::reinforce,
    rng::Rng,
    task::{Pattern, Task},
};
use serde::Serialize;
use std::time::Instant;
#[cfg(test)]
mod dh03;
#[cfg(test)]
mod dh04;
#[cfg(test)]
mod dh06;
mod dh07;
#[cfg(test)]
mod experiment;
#[cfg(test)]
#[allow(unused_imports)]
pub use dh06::{Dh06Condition, attach_immediate_reference_dh06};
pub use dh07::{Dh07Condition, attach_immediate_reference_dh07};
#[cfg(test)]
pub use experiment::Condition;

pub struct Simulator<'a> {
    graph: &'a Graph,
    route: &'a Layer,
    pub weights: Vec<f32>,
    pub capture: Option<crate::capture::Capture>,
    pub policy: Option<crate::policy::Policy>,
    eligibility: Vec<f32>,
    baseline: Vec<f32>,
    post: Vec<f32>,
    probabilities: Vec<f32>,
    signed_post: Vec<f32>,
    dan: Vec<f32>,
    feedback: Vec<f32>,
    gain: Vec<f32>,
    bias: Vec<f32>,
    denom: Vec<f32>,
    action_sign: Vec<f32>,
    rng: Rng,
    lambda: f32,
    scale: f32,
    eta: f32,
    uniform: bool,
    disabled: bool,
    pub work: u64,
    events: u64,
    max_gain_mass_error: f32,
}
#[derive(Serialize, Debug)]
pub struct Outcome {
    pub accuracy: f64,
    pub acquisition: f64,
    pub reversal: f64,
    pub late_acquisition: f64,
    pub late_reversal: f64,
    pub probe_acquisition: f64,
    pub probe_reversal: f64,
    pub curve: Vec<f64>,
    pub seconds: f64,
    pub work: u64,
    pub stimulus_events: u64,
    pub state_bytes: usize,
    pub hot_allocations: u64,
    pub unique_cue_codes: usize,
    pub changed_weights: usize,
    pub max_gain_mass_error: f32,
}
fn sigmoid(x: f32) -> f32 {
    1.0 / (1.0 + (-x.clamp(-30.0, 30.0)).exp())
}
impl<'a> Simulator<'a> {
    pub fn new(
        graph: &'a Graph,
        route: &'a Layer,
        seed: u64,
        tau: f32,
        eta: f32,
        arm: &str,
    ) -> Self {
        let m = graph.kc_mb.n_post;
        let d = graph.kc_dan.n_post;
        let mut weights = vec![0.0; graph.kc_mb.edges.len()];
        let mut bias = vec![0.0; m];
        let mut denom = vec![1.0; m];
        for j in 0..m {
            let row = graph.kc_mb.row(j);
            let n = row.len();
            let total: f32 = graph.kc_mb.edges[row.clone()]
                .iter()
                .map(|e| e.count as f32)
                .sum();
            for i in row {
                weights[i] = (0.15 * graph.kc_mb.edges[i].count as f32 * n as f32 / total).min(2.0);
            }
            denom[j] = (0.05 * n as f32).sqrt().max(1.0);
            bias[j] = 0.05 * weights[graph.kc_mb.row(j)].iter().sum::<f32>() / denom[j];
        }
        let mut action_sign: Vec<_> = (0..m)
            .map(|i| if i % 2 == 0 { 1.0 } else { -1.0 })
            .collect();
        Rng(seed ^ 0xabcdef).shuffle(&mut action_sign);
        Self {
            graph,
            route,
            eligibility: vec![0.0; weights.len()],
            weights,
            baseline: vec![0.5; m],
            post: vec![0.0; m],
            probabilities: vec![0.0; m],
            signed_post: vec![0.0; m],
            dan: vec![0.5; d],
            feedback: vec![0.0; d],
            gain: vec![0.0; m],
            bias,
            denom,
            action_sign,
            rng: Rng(seed ^ 0x778899),
            lambda: (-1.0 / tau).exp(),
            scale: 1.0,
            eta,
            capture: None,
            policy: None,
            uniform: arm == "E",
            disabled: arm == "Z",
            work: 0,
            events: 0,
            max_gain_mass_error: 0.0,
        }
    }
    fn sample(&mut self, pattern: &Pattern) -> bool {
        let mut score = 0.0;
        for j in 0..self.post.len() {
            let mut drive = 0.0;
            for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] {
                drive += self.weights[ix];
            }
            let p = sigmoid(2.0 * (drive / self.denom[j] - self.bias[j]));
            self.probabilities[j] = p;
            self.post[j] = if self.rng.unit() < p { 1.0 } else { 0.0 };
            score += self.action_sign[j] * (self.post[j] - 0.5);
        }
        // Always consume the tie draw, keeping paired random streams aligned.
        let tie = self.rng.unit() < 0.5;
        self.work += pattern.edges.len() as u64;
        if score == 0.0 { tie } else { score > 0.0 }
    }
    fn event(&mut self, pattern: &Pattern) -> bool {
        let action = self.sample(pattern);
        self.scale *= self.lambda;
        for j in 0..self.post.len() {
            let deviation = self.post[j] - self.baseline[j];
            for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] {
                self.eligibility[ix] += deviation / self.scale;
            }
            self.baseline[j] = 0.99 * self.baseline[j] + 0.01 * self.post[j];
            self.signed_post[j] = self.post[j] * self.graph.mb_sign[j];
        }
        self.graph
            .mb_dan
            .normalized_projection(&self.signed_post, &mut self.feedback);
        for i in 0..self.dan.len() {
            let raw =
                0.25 + 0.75 * sigmoid(20.0 * (pattern.dan[i] - 0.05) + 2.0 * self.feedback[i]);
            self.dan[i] = 0.5 * self.dan[i] + 0.5 * raw;
        }
        self.work += (pattern.edges.len() + self.graph.mb_dan.edges.len()) as u64;
        self.events += 1;
        action
    }
    fn reward(&mut self, reward: f32) {
        if self.disabled {
            return;
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
        for j in 0..self.gain.len() {
            let row = self.graph.kc_mb.row(j);
            reinforce(
                &mut self.weights[row.clone()],
                &self.eligibility[row],
                self.eta * reward * self.gain[j] * self.scale,
            );
        }
        self.work += (self.weights.len()
            + if self.uniform {
                0
            } else {
                self.route.edges.len()
            }) as u64;
    }
    fn probe(&mut self, task: &Task, reversed: bool) -> f64 {
        let saved = self.rng.clone();
        self.rng = Rng(0x910022 + u64::from(reversed));
        let mut correct = 0;
        for _ in 0..16 {
            for cue in 0..task.cues {
                if self.sample(&task.patterns[cue]) == (task.labels[cue] ^ reversed) {
                    correct += 1;
                }
            }
        }
        self.rng = saved;
        correct as f64 / (16 * task.cues) as f64
    }
    #[cfg(test)]
    pub fn run(&mut self, task: &Task) -> Outcome {
        let initial = self.weights.clone();
        let mut blocks = vec![0_usize; 8];
        let trials = task.schedule.len();
        assert!(trials.is_multiple_of(8));
        let mut correct_a = 0;
        let mut correct_b = 0;
        let mut late_a = 0;
        let mut late_b = 0;
        let mut probe_a = 0.0;
        let allocations = crate::allocations();
        let start = Instant::now();
        for (trial, row) in task.schedule.iter().enumerate() {
            self.eligibility.fill(0.0);
            self.scale = 1.0;
            self.dan.fill(0.5);
            let action = self.event(&task.patterns[row[0]]);
            for &distractor in &row[1..] {
                self.event(&task.patterns[distractor]);
            }
            let correct = action == task.expected(trial, row[0]);
            self.reward(if correct { 1.0 } else { -1.0 });
            if correct {
                blocks[trial / (trials / 8)] += 1;
                if trial < trials / 2 {
                    correct_a += 1;
                } else {
                    correct_b += 1;
                }
                if (trials * 3 / 8..trials / 2).contains(&trial) {
                    late_a += 1;
                }
                if trial >= trials * 7 / 8 {
                    late_b += 1;
                }
            }
            if trial + 1 == trials / 2 {
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
        Outcome {
            accuracy: (correct_a + correct_b) as f64 / trials as f64,
            acquisition: correct_a as f64 / (trials / 2) as f64,
            reversal: correct_b as f64 / (trials / 2) as f64,
            late_acquisition: late_a as f64 / (trials / 8) as f64,
            late_reversal: late_b as f64 / (trials / 8) as f64,
            probe_acquisition: probe_a,
            probe_reversal: probe_b,
            curve: blocks
                .into_iter()
                .map(|x| x as f64 / (trials / 8) as f64)
                .collect(),
            seconds,
            work: self.work,
            stimulus_events: self.events,
            state_bytes: 4
                * (self.weights.len() * 2 + self.baseline.len() * 7 + self.dan.len() * 2),
            hot_allocations,
            unique_cue_codes: task.unique_cue_codes(),
            changed_weights: self
                .weights
                .iter()
                .zip(initial)
                .filter(|(a, b)| **a != *b)
                .count(),
            max_gain_mass_error: self.max_gain_mass_error,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn synthetic_smoke_all_arms_are_finite_and_hot_loop_does_not_allocate() {
        let original = Graph::fixture();
        let (rewired, _) = original.rewire_signal(990);
        let (route, _) = original.route.rewired(333);
        for arm in ["A", "B", "C", "D", "E", "Z"] {
            let g = if arm == "C" || arm == "D" {
                &rewired
            } else {
                &original
            };
            let route = if arm == "B" || arm == "D" {
                &route
            } else {
                &g.route
            };
            let t = Task::new(g, 99, 16, 4, 32);
            let mut s = Simulator::new(g, route, 5, 4.0, 0.05, arm);
            let r = s.run(&t);
            assert_eq!(r.hot_allocations, 0);
            assert!(r.accuracy.is_finite());
            if arm == "Z" {
                assert_eq!(r.changed_weights, 0);
            } else {
                assert!(r.changed_weights > 0);
                assert!(r.max_gain_mass_error < 1e-5);
            }
        }
    }
    #[test]
    fn deterministic_replay_and_target_changes_do_not_change_pre_reward_action() {
        let g = Graph::fixture();
        let t = Task::new(&g, 94, 16, 4, 32);
        let mut a = Simulator::new(&g, &g.route, 66, 16.0, 0.05, "A");
        let mut b = Simulator::new(&g, &g.route, 66, 16.0, 0.05, "A");
        assert_eq!(a.event(&t.patterns[0]), b.event(&t.patterns[0]));
        assert_eq!(a.weights, b.weights);
        a.reward(1.0);
        b.reward(-1.0);
        assert_ne!(a.weights, b.weights);
    }
    #[test]
    fn full_simulation_replays_bit_for_bit() {
        let g = Graph::fixture();
        let t = Task::new(&g, 908, 16, 4, 64);
        let mut a = Simulator::new(&g, &g.route, 187, 16.0, 0.05, "A");
        let mut b = Simulator::new(&g, &g.route, 187, 16.0, 0.05, "A");
        let x = a.run(&t);
        let y = b.run(&t);
        assert_eq!(x.curve, y.curve);
        assert_eq!(a.weights, b.weights);
        assert_eq!(x.work, y.work);
    }
    #[test]
    fn synthetic_positive_control_learns_simple_associations() {
        let g = Graph::fixture();
        let mut learned = 0.0;
        let mut frozen = 0.0;
        for seed in 0..16 {
            let t = Task::new(&g, seed + 700, 2, 0, 1024);
            learned += Simulator::new(&g, &g.route, seed, 16.0, 0.05, "E")
                .run(&t)
                .late_acquisition;
            frozen += Simulator::new(&g, &g.route, seed, 16.0, 0.05, "Z")
                .run(&t)
                .late_acquisition;
        }
        assert!(
            learned / 16.0 > 0.6 && (learned - frozen) / 16.0 > 0.05,
            "learned={} frozen={}",
            learned / 16.0,
            frozen / 16.0
        );
    }
    #[test]
    #[ignore = "explicit performance qualification"]
    fn benchmark_synthetic_simulator() {
        let g = Graph::fixture();
        let t = Task::new(&g, 321, 16, 12, 512);
        let mut times = Vec::new();
        let mut operations = 0;
        for _ in 0..21 {
            let r = Simulator::new(&g, &g.route, 432, 16.0, 0.05, "A").run(&t);
            assert_eq!(r.hot_allocations, 0);
            operations = r.work;
            times.push(r.seconds);
        }
        times.sort_by(f64::total_cmp);
        println!(
            "synthetic benchmark median_seconds={} p95_seconds={} work_per_run={} allocations=0",
            times[10], times[19], operations
        );
    }
}
