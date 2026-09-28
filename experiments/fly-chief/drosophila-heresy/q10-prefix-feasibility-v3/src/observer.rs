//! Read-only shadow accounting. This module never owns mutable learner state.
use crate::graph::{Graph, Layer};
use serde::Serialize;

#[derive(Default)]
struct Accum {
    n: u64,
    cue: f64,
    interval: f64,
    combined: f64,
    share: f64,
    cancellation: f64,
    floor: f64,
    ceiling: f64,
    clips: f64,
    saturated: f64,
    probability: f64,
    routing_rms: f64,
    routing_cosine: f64,
    a_uniform: f64,
    b_uniform: f64,
    dan_cv: f64,
    small_route: u64,
}
#[derive(Serialize, Debug)]
pub struct PhaseSummary {
    pub trials: u64,
    pub cue_eligibility_l1_mean: f64,
    pub interval_eligibility_l1_mean: f64,
    pub combined_eligibility_l1_mean: f64,
    pub cue_share_of_component_l1_mean: f64,
    pub cancellation_fraction_mean: f64,
    pub weight_floor_fraction_mean: f64,
    pub weight_ceiling_fraction_mean: f64,
    pub proposed_clip_fraction_mean: f64,
    pub cue_output_saturation_fraction: f64,
    pub cue_probability_mean: f64,
    pub routing_relative_rms_ab_mean: f64,
    pub routing_cosine_ab_mean: f64,
    pub routing_rms_a_uniform_mean: f64,
    pub routing_rms_b_uniform_mean: f64,
    pub dan_coefficient_of_variation_mean: f64,
    pub route_rms_below_one_percent_fraction: f64,
}
pub struct Observer {
    cue: Vec<f32>,
    ga: Vec<f32>,
    gb: Vec<f32>,
    phases: [Accum; 2],
    cue_saturated: f64,
    cue_probability: f64,
}

/// Exactly the DH-01 candidate route averaging and mass normalization.
fn gains(graph: &Graph, route: &Layer, dan: &[f32], out: &mut [f32]) {
    for (j, g) in out.iter_mut().enumerate() {
        let row = route.row(j);
        *g = if row.is_empty() {
            0.0
        } else {
            route.edges[row.clone()]
                .iter()
                .map(|e| dan[e.pre as usize])
                .sum::<f32>()
                / row.len() as f32
        };
    }
    let mass: f32 = out
        .iter()
        .enumerate()
        .map(|(j, g)| g * graph.kc_mb.row(j).len() as f32)
        .sum();
    assert!(mass > 0.0);
    let norm = graph.kc_mb.edges.len() as f32 / mass;
    for g in out {
        *g *= norm;
    }
}
impl Observer {
    pub fn new(graph: &Graph) -> Self {
        Self {
            cue: vec![0.0; graph.kc_mb.edges.len()],
            ga: vec![0.0; graph.kc_mb.n_post],
            gb: vec![0.0; graph.kc_mb.n_post],
            phases: std::array::from_fn(|_| Accum::default()),
            cue_saturated: 0.0,
            cue_probability: 0.0,
        }
    }
    pub fn capture_cue(&mut self, trace: &[f32], probabilities: &[f32]) {
        self.cue.copy_from_slice(trace);
        self.cue_saturated = probabilities
            .iter()
            .filter(|&&p| p <= 0.01 || p >= 0.99)
            .count() as f64
            / probabilities.len() as f64;
        self.cue_probability =
            probabilities.iter().map(|&p| p as f64).sum::<f64>() / probabilities.len() as f64;
    }
    #[allow(clippy::too_many_arguments)]
    pub fn at_reward(
        &mut self,
        phase: usize,
        graph: &Graph,
        shuffled: &Layer,
        dan: &[f32],
        weights: &[f32],
        trace: &[f32],
        scale: f32,
        step: f32,
    ) {
        let a = &mut self.phases[phase];
        a.n += 1;
        let mut cue = 0.0;
        let mut interval = 0.0;
        let mut combined = 0.0;
        let mut clipped = 0;
        for ((&w, &e), &c) in weights.iter().zip(trace).zip(&self.cue) {
            let c = c as f64 * scale as f64;
            let total = e as f64 * scale as f64;
            cue += c.abs();
            interval += (total - c).abs();
            combined += total.abs();
            let proposed = w + step * e;
            if !(0.0..=2.0).contains(&proposed) {
                clipped += 1;
            }
        }
        a.cue += cue;
        a.interval += interval;
        a.combined += combined;
        if cue + interval > 0.0 {
            a.share += cue / (cue + interval);
            a.cancellation += 1.0 - combined / (cue + interval);
        }
        a.clips += clipped as f64 / weights.len() as f64;
        a.floor += weights.iter().filter(|&&w| w == 0.0).count() as f64 / weights.len() as f64;
        a.ceiling += weights.iter().filter(|&&w| w == 2.0).count() as f64 / weights.len() as f64;
        a.saturated += self.cue_saturated;
        a.probability += self.cue_probability;
        gains(graph, &graph.route, dan, &mut self.ga);
        gains(graph, shuffled, dan, &mut self.gb);
        let mut diff = 0.0;
        let mut aa = 0.0;
        let mut bb = 0.0;
        let mut ab = 0.0;
        let mut au = 0.0;
        let mut bu = 0.0;
        for (j, (&x, &y)) in self.ga.iter().zip(&self.gb).enumerate() {
            let d = graph.kc_mb.row(j).len() as f64;
            let x = x as f64;
            let y = y as f64;
            diff += d * (x - y).powi(2);
            aa += d * x * x;
            bb += d * y * y;
            ab += d * x * y;
            au += d * (x - 1.0).powi(2);
            bu += d * (y - 1.0).powi(2);
        }
        let rms = (diff / aa).sqrt();
        a.routing_rms += rms;
        a.routing_cosine += ab / (aa * bb).sqrt();
        a.a_uniform += (au / weights.len() as f64).sqrt();
        a.b_uniform += (bu / weights.len() as f64).sqrt();
        if rms < 0.01 {
            a.small_route += 1;
        }
        let mean = dan.iter().map(|&x| x as f64).sum::<f64>() / dan.len() as f64;
        let variance =
            dan.iter().map(|&x| (x as f64 - mean).powi(2)).sum::<f64>() / dan.len() as f64;
        a.dan_cv += variance.sqrt() / mean;
    }
    pub fn array_bytes(&self) -> usize {
        4 * (self.cue.len() + self.ga.len() + self.gb.len())
    }
    pub fn summary(&self) -> [PhaseSummary; 2] {
        std::array::from_fn(|i| {
            let a = &self.phases[i];
            let n = a.n.max(1) as f64;
            PhaseSummary {
                trials: a.n,
                cue_eligibility_l1_mean: a.cue / n,
                interval_eligibility_l1_mean: a.interval / n,
                combined_eligibility_l1_mean: a.combined / n,
                cue_share_of_component_l1_mean: a.share / n,
                cancellation_fraction_mean: a.cancellation / n,
                weight_floor_fraction_mean: a.floor / n,
                weight_ceiling_fraction_mean: a.ceiling / n,
                proposed_clip_fraction_mean: a.clips / n,
                cue_output_saturation_fraction: a.saturated / n,
                cue_probability_mean: a.probability / n,
                routing_relative_rms_ab_mean: a.routing_rms / n,
                routing_cosine_ab_mean: a.routing_cosine / n,
                routing_rms_a_uniform_mean: a.a_uniform / n,
                routing_rms_b_uniform_mean: a.b_uniform / n,
                dan_coefficient_of_variation_mean: a.dan_cv / n,
                route_rms_below_one_percent_fraction: a.small_route as f64 / n,
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn same_route_has_zero_shadow_difference_and_quiet_has_no_interval_credit() {
        let g = Graph::fixture();
        let mut o = Observer::new(&g);
        let e = vec![0.5; g.kc_mb.edges.len()];
        o.capture_cue(&e, &vec![0.5; g.kc_mb.n_post]);
        o.at_reward(
            0,
            &g,
            &g.route,
            &vec![0.6; g.route.n_pre],
            &e,
            &e,
            0.25,
            0.0,
        );
        let s = o.summary();
        assert_eq!(s[0].interval_eligibility_l1_mean, 0.0);
        assert_eq!(s[0].cue_share_of_component_l1_mean, 1.0);
        assert_eq!(s[0].routing_relative_rms_ab_mean, 0.0);
        assert!((s[0].routing_cosine_ab_mean - 1.0).abs() < 1e-12);
    }
}
