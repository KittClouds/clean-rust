use crate::{graph::{Graph, Layer}, rng::Rng, task::{Pattern, Task}};
use sha2::{Digest, Sha256};
use wide::f32x8;

#[derive(Clone)]
pub struct Sim<'a> {
    pub graph: &'a Graph,
    pub route: &'a Layer,
    pub weights: Vec<f32>,
    pub active: Vec<bool>,
    pub eligibility: Vec<f32>,
    pub baseline: Vec<f32>,
    pub post: Vec<f32>,
    pub probabilities: Vec<f32>,
    pub signed_post: Vec<f32>,
    pub dan: Vec<f32>,
    pub feedback: Vec<f32>,
    pub gain: Vec<f32>,
    pub bias: Vec<f32>,
    pub denom: Vec<f32>,
    pub action_sign: Vec<f32>,
    pub rng: Rng,
    pub lambda: f32,
    pub scale: f32,
    pub eta: f32,
    pub weights_frozen: bool,
    pub work: u64,
    pub events: u64,
    pub max_gain_mass_error: f32,
}

#[inline]
fn sigmoid(x: f32) -> f32 { 1.0 / (1.0 + (-x.clamp(-30.0, 30.0)).exp()) }

impl<'a> Sim<'a> {
    pub fn new(graph: &'a Graph, seed: u64, tau: f32, eta: f32) -> Self {
        let m = graph.kc_mb.n_post;
        let d = graph.kc_dan.n_post;
        let mut weights = vec![0.0; graph.kc_mb.edges.len()];
        let mut bias = vec![0.0; m];
        let mut denom = vec![1.0; m];
        for j in 0..m {
            let row = graph.kc_mb.row(j);
            let n = row.len();
            let total: f32 = graph.kc_mb.edges[row.clone()].iter().map(|e| e.count as f32).sum();
            for ix in row.clone() {
                weights[ix] = (0.15 * graph.kc_mb.edges[ix].count as f32 * n as f32 / total).min(2.0);
            }
            denom[j] = (0.05 * n as f32).sqrt().max(1.0);
            bias[j] = 0.05 * weights[row].iter().sum::<f32>() / denom[j];
        }
        let mut action_sign: Vec<f32> = (0..m).map(|i| if i % 2 == 0 { 1.0 } else { -1.0 }).collect();
        Rng(seed ^ 0xabcdef).shuffle(&mut action_sign);
        Self {
            graph, route: &graph.route, weights, active: vec![true; graph.kc_mb.edges.len()],
            eligibility: vec![0.0; graph.kc_mb.edges.len()], baseline: vec![0.5; m],
            post: vec![0.0; m], probabilities: vec![0.0; m], signed_post: vec![0.0; m],
            dan: vec![0.5; d], feedback: vec![0.0; d], gain: vec![0.0; m], bias, denom,
            action_sign, rng: Rng(seed ^ 0x778899), lambda: (-1.0 / tau).exp(), scale: 1.0,
            eta, weights_frozen: false, work: 0, events: 0, max_gain_mass_error: 0.0,
        }
    }

    #[inline]
    fn sample(&mut self, pattern: &Pattern) -> bool {
        let mut score = 0.0_f32;
        for j in 0..self.post.len() {
            let mut drive = 0.0_f32;
            for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] {
                if self.active[ix] { drive += self.weights[ix]; }
            }
            let p = sigmoid(2.0 * (drive / self.denom[j] - self.bias[j]));
            self.probabilities[j] = p;
            self.post[j] = if self.rng.unit() < p { 1.0 } else { 0.0 };
            score += self.action_sign[j] * (self.post[j] - 0.5);
        }
        let tie = self.rng.unit() < 0.5;
        self.work += pattern.edges.len() as u64;
        if score == 0.0 { tie } else { score > 0.0 }
    }

    #[inline]
    fn event(&mut self, pattern: &Pattern) -> bool {
        let action = self.sample(pattern);
        self.scale *= self.lambda;
        for j in 0..self.post.len() {
            let deviation = self.post[j] - self.baseline[j];
            for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j + 1]] {
                if self.active[ix] { self.eligibility[ix] += deviation / self.scale; }
            }
            self.baseline[j] = 0.99 * self.baseline[j] + 0.01 * self.post[j];
            self.signed_post[j] = self.post[j] * self.graph.mb_sign[j];
        }
        self.graph.mb_dan.normalized_projection(&self.signed_post, &mut self.feedback);
        for i in 0..self.dan.len() {
            let raw = 0.25 + 0.75 * sigmoid(20.0 * (pattern.dan[i] - 0.05) + 2.0 * self.feedback[i]);
            self.dan[i] = 0.5 * self.dan[i] + 0.5 * raw;
        }
        self.work += (pattern.edges.len() + self.graph.mb_dan.edges.len()) as u64;
        self.events += 1;
        action
    }

    pub fn proposed_delta_into(&mut self, reward: f32, delta: &mut [f32]) {
        assert_eq!(delta.len(), self.weights.len());
        for j in 0..self.gain.len() {
            let row = self.route.row(j);
            self.gain[j] = if row.is_empty() { 0.0 } else {
                self.route.edges[row.clone()].iter().map(|e| self.dan[e.pre as usize]).sum::<f32>() / row.len() as f32
            };
        }
        let mass: f32 = self.gain.iter().enumerate().map(|(j, g)| g * self.graph.kc_mb.row(j).len() as f32).sum();
        assert!(mass > 0.0);
        let norm = self.weights.len() as f32 / mass;
        for g in &mut self.gain { *g *= norm; }
        let mass2: f32 = self.gain.iter().enumerate().map(|(j, g)| g * self.graph.kc_mb.row(j).len() as f32).sum();
        self.max_gain_mass_error = self.max_gain_mass_error.max((mass2 / self.weights.len() as f32 - 1.0).abs());
        delta.fill(0.0);
        for j in 0..self.gain.len() {
            let row = self.graph.kc_mb.row(j);
            let step = self.eta * reward * self.gain[j] * self.scale;
            for ix in row { if self.active[ix] { delta[ix] = step * self.eligibility[ix]; } }
        }
        self.work += self.weights.len() as u64 + self.route.edges.len() as u64;
    }

    pub fn proposed_delta(&mut self, reward: f32) -> Vec<f32> {
        let mut delta = vec![0.0_f32; self.weights.len()];
        self.proposed_delta_into(reward, &mut delta);
        delta
    }

    pub fn apply_delta(&mut self, delta: &[f32]) {
        assert_eq!(delta.len(), self.weights.len());
        if self.weights_frozen { return; }
        for ((weight, &step), &active) in self.weights.iter_mut().zip(delta).zip(&self.active) {
            if active { *weight = (*weight + step).clamp(0.0, 2.0); }
        }
    }

    pub fn begin_trial(&mut self, task: &Task, trial: usize) -> (bool, f32) {
        let row = &task.schedule[trial % task.schedule.len()];
        self.eligibility.fill(0.0);
        self.scale = 1.0;
        self.dan.fill(0.5);
        let action = self.event(&task.patterns[row[0]]);
        for &distractor in &row[1..] { self.event(&task.patterns[distractor]); }
        let correct = action == task.labels[row[0]];
        (correct, if correct { 1.0 } else { -1.0 })
    }

    pub fn trial(&mut self, task: &Task, trial: usize) -> bool {
        let (correct, reward) = self.begin_trial(task, trial);
        let delta = self.proposed_delta(reward);
        self.apply_delta(&delta);
        correct
    }

    pub fn loss(&self, task: &Task, draws: &[Vec<u64>]) -> f64 {
        let mut eval = self.clone();
        let mut errors = 0usize;
        for row in draws {
            for cue in 0..task.cues {
                eval.rng = Rng(row[cue]);
                let action = eval.sample(&task.patterns[cue]);
                errors += usize::from(action != task.labels[cue]);
            }
        }
        errors as f64 / (draws.len() * task.cues) as f64
    }

    pub fn digest(&self) -> String {
        let mut h = Sha256::new();
        for values in [&self.weights, &self.eligibility, &self.baseline, &self.post,
                       &self.probabilities, &self.signed_post, &self.dan, &self.feedback, &self.gain] {
            for &value in values { h.update(value.to_bits().to_le_bytes()); }
        }
        for &active in &self.active { h.update([u8::from(active)]); }
        h.update(self.rng.0.to_le_bytes());
        h.update(self.scale.to_bits().to_le_bytes());
        h.update(self.work.to_le_bytes());
        h.update(self.events.to_le_bytes());
        format!("{:x}", h.finalize())
    }

    pub fn finite(&self) -> bool {
        self.weights.iter().chain(&self.eligibility).chain(&self.baseline).chain(&self.dan).all(|x| x.is_finite())
    }
}

fn reinforce_masked(weights: &mut [f32], eligibility: &[f32], active: &[bool], step: f32) {
    assert_eq!(weights.len(), eligibility.len());
    let n = weights.len() / 8 * 8;
    let factor = f32x8::splat(step);
    let zero = f32x8::splat(0.0);
    let cap = f32x8::splat(2.0);
    for ((w, e), a) in weights[..n].chunks_exact_mut(8).zip(eligibility[..n].chunks_exact(8)).zip(active[..n].chunks_exact(8)) {
        let mut out = [0.0_f32; 8];
        let wa = f32x8::from(<[f32; 8]>::try_from(&*w).unwrap());
        let eb = f32x8::from(<[f32; 8]>::try_from(e).unwrap());
        (wa + eb * factor).max(zero).min(cap).to_array().iter().enumerate().for_each(|(i, v)| { out[i] = if a[i] { *v } else { w[i] }; });
        w.copy_from_slice(&out);
    }
    for ((w, &e), &active) in weights[n..].iter_mut().zip(&eligibility[n..]).zip(&active[n..]) {
        if active { *w = (*w + step * e).clamp(0.0, 2.0); }
    }
}
