//! Pure sequential-f32 readout, matching the canonical decision arithmetic.
use crate::task::Task;
use serde::Serialize;
#[derive(Clone, Serialize)]
pub struct Readout {
    pub true_cue_scores: [f64; 16],
    pub null_cue_scores: [f64; 16],
    pub cue_max_normalized_drive_errors: [f64; 16],
    pub max_normalized_drive_error: f64,
    pub max_cue_score_error: f64,
    pub max_probability_error: f64,
    pub max_distractor_normalized_drive_error: f64,
    pub max_real_arithmetic_normalized_drive_error: f64,
}

pub fn audit(
    task: &Task,
    t: &[f32],
    n: &[f32],
    denom: &[f32],
    bias: &[f32],
    sign: &[f32],
) -> Readout {
    let mut out = Readout {
        true_cue_scores: [0.; 16],
        null_cue_scores: [0.; 16],
        cue_max_normalized_drive_errors: [0.; 16],
        max_normalized_drive_error: 0.,
        max_cue_score_error: 0.,
        max_probability_error: 0.,
        max_distractor_normalized_drive_error: 0.,
        max_real_arithmetic_normalized_drive_error: 0.,
    };
    for (cue, p) in task.patterns.iter().enumerate() {
        let mut ts = 0_f32;
        let mut ns = 0_f32;
        let mut max_drive = 0_f64;
        for j in 0..denom.len() {
            let ids = &p.edges[p.offsets[j]..p.offsets[j + 1]];
            let td: f32 = ids.iter().map(|&i| t[i]).sum();
            let nd: f32 = ids.iter().map(|&i| n[i]).sum();
            // Frozen gate: subtract the actual sequential f32 drives, then
            // divide by the model's frozen f32 denominator (in f32).
            let error = f64::from((td - nd) / denom[j]).abs();
            max_drive = max_drive.max(error);
            let tp = crate::simulation::sigmoid(2.0 * (td / denom[j] - bias[j]));
            let np = crate::simulation::sigmoid(2.0 * (nd / denom[j] - bias[j]));
            ts += sign[j] * (tp - 0.5);
            ns += sign[j] * (np - 0.5);
            if cue < 16 {
                out.max_probability_error = out.max_probability_error.max(f64::from(tp - np).abs());
                let real = ids
                    .iter()
                    .map(|&i| f64::from(t[i]) - f64::from(n[i]))
                    .sum::<f64>()
                    / f64::from(denom[j]);
                out.max_real_arithmetic_normalized_drive_error = out
                    .max_real_arithmetic_normalized_drive_error
                    .max(real.abs());
            }
        }
        if cue < 16 {
            out.true_cue_scores[cue] = f64::from(ts) / denom.len() as f64;
            out.null_cue_scores[cue] = f64::from(ns) / denom.len() as f64;
            out.cue_max_normalized_drive_errors[cue] = max_drive;
            out.max_normalized_drive_error = out.max_normalized_drive_error.max(max_drive);
            out.max_cue_score_error = out
                .max_cue_score_error
                .max((out.true_cue_scores[cue] - out.null_cue_scores[cue]).abs());
        } else {
            out.max_distractor_normalized_drive_error =
                out.max_distractor_normalized_drive_error.max(max_drive);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn saturation_matches_canonical_clamp_bit_for_bit() {
        for x in [-1e20_f32, -100., -30., 0., 30., 100., 1e20] {
            let expected = 1.0_f32 / (1.0 + (-x.clamp(-30., 30.)).exp());
            assert_eq!(crate::simulation::sigmoid(x).to_bits(), expected.to_bits());
        }
        let graph = crate::graph::Graph::fixture();
        let task = Task::new(&graph, 9200, 16, 12, 512);
        let weights = vec![1.; graph.kc_mb.edges.len()];
        let post = graph.kc_mb.n_post;
        for bias in [-1e10, 1e10] {
            let denom = vec![1.; post];
            let biases = vec![bias; post];
            let signs = vec![1.; post];
            let r = audit(&task, &weights, &weights, &denom, &biases, &signs);
            assert_eq!(r.max_cue_score_error, 0.);
            assert_eq!(r.max_normalized_drive_error, 0.);
            let margin = crate::simulation::old_map_margin_for_weights_dh08a(
                &task, &weights, post, &denom, &biases, &signs,
            );
            let from_scores = r
                .true_cue_scores
                .iter()
                .enumerate()
                .map(|(i, &s)| s * if task.labels[i] { 1. } else { -1. })
                .sum::<f64>()
                / 16.;
            assert_eq!(margin, from_scores);
        }
    }
}
