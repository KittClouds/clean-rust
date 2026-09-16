use crate::{graph::Graph, rng::Rng};

pub struct Pattern {
    pub edges: Vec<usize>,
    pub offsets: Vec<usize>,
    pub dan: Vec<f32>,
    pub active_kc: Vec<usize>,
}
pub struct Task {
    pub patterns: Vec<Pattern>,
    pub cues: usize,
    pub labels: Vec<bool>,
    pub schedule: Vec<Vec<usize>>,
}

impl Task {
    pub fn new(graph: &Graph, seed: u64, cues: usize, distractors: usize, trials: usize) -> Self {
        let mut rng = Rng(seed);
        let np = graph.pn_kc.n_pre;
        let nk = graph.pn_kc.n_post;
        let mut pn = vec![0.0; np];
        let mut kc = vec![0.0; nk];
        let mut pn_order: Vec<_> = (0..np).collect();
        let mut order: Vec<_> = (0..nk).collect();
        let mut patterns = Vec::new();
        for _ in 0..cues + 32 {
            pn.fill(0.0);
            rng.shuffle(&mut pn_order);
            for &i in pn_order.iter().take((np / 5).max(1)) {
                pn[i] = 1.0;
            }
            graph.pn_kc.normalized_projection(&pn, &mut kc);
            let active = (nk / 20).max(1).min(nk - 1);
            order.select_nth_unstable_by(active, |&a, &b| kc[b].total_cmp(&kc[a]).then(a.cmp(&b)));
            let mut active_kc = order[..active].to_vec();
            active_kc.sort_unstable();
            kc.fill(0.0);
            for &i in &active_kc {
                kc[i] = 1.0;
            }
            let mut edges = Vec::new();
            let mut offsets = vec![0];
            for j in 0..graph.kc_mb.n_post {
                for ix in graph.kc_mb.row(j) {
                    if kc[graph.kc_mb.edges[ix].pre as usize] > 0.0 {
                        edges.push(ix);
                    }
                }
                offsets.push(edges.len());
            }
            let mut dan = vec![0.0; graph.kc_dan.n_post];
            graph.kc_dan.normalized_projection(&kc, &mut dan);
            patterns.push(Pattern {
                edges,
                offsets,
                dan,
                active_kc,
            });
        }
        let mut labels: Vec<_> = (0..cues).map(|i| i % 2 == 0).collect();
        rng.shuffle(&mut labels);
        let schedule = (0..trials)
            .map(|_| {
                let mut row = Vec::with_capacity(distractors + 1);
                row.push(rng.index(cues));
                for _ in 0..distractors {
                    row.push(cues + rng.index(32));
                }
                row
            })
            .collect();
        Self {
            patterns,
            cues,
            labels,
            schedule,
        }
    }
    pub fn expected(&self, trial: usize, cue: usize) -> bool {
        self.labels[cue] ^ (trial >= self.schedule.len() / 2)
    }
    pub fn unique_cue_codes(&self) -> usize {
        (0..self.cues)
            .filter(|&i| !(0..i).any(|j| self.patterns[j].active_kc == self.patterns[i].active_kc))
            .count()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reversal_flips_every_target_and_labels_are_balanced() {
        let t = Task::new(&Graph::fixture(), 123, 16, 4, 32);
        assert_eq!(t.labels.iter().filter(|&&v| v).count(), 8);
        for c in 0..16 {
            assert_ne!(t.expected(0, c), t.expected(16, c));
        }
        assert!(
            t.schedule
                .iter()
                .all(|r| r.len() == 5 && r[0] < 16 && r[1..].iter().all(|&v| v >= 16))
        );
    }
}
