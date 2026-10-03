use crate::{graph::Graph, rng::Rng};

pub struct Pattern {
    pub edges: Vec<usize>,
    pub offsets: Vec<usize>,
    pub dan: Vec<f32>,
}

pub struct Task {
    pub patterns: Vec<Pattern>,
    pub cues: usize,
    pub labels: Vec<bool>,
    pub schedule: Vec<Vec<usize>>,
}

impl Task {
    pub fn new(graph: &Graph, pattern_seed: u64, labels: Vec<bool>, schedule: Vec<Vec<usize>>) -> Self {
        let cues = labels.len();
        let mut rng = Rng(pattern_seed);
        let np = graph.pn_kc.n_pre;
        let nk = graph.pn_kc.n_post;
        let mut pn = vec![0.0_f32; np];
        let mut kc = vec![0.0_f32; nk];
        let mut pn_order: Vec<usize> = (0..np).collect();
        let mut order: Vec<usize> = (0..nk).collect();
        let mut patterns = Vec::with_capacity(cues + 32);
        for _ in 0..cues + 32 {
            pn.fill(0.0);
            rng.shuffle(&mut pn_order);
            for &i in pn_order.iter().take((np / 5).max(1)) { pn[i] = 1.0; }
            graph.pn_kc.normalized_projection(&pn, &mut kc);
            let active = (nk / 20).max(1).min(nk - 1);
            order.select_nth_unstable_by(active, |&a, &b| {
                kc[b].total_cmp(&kc[a]).then(a.cmp(&b))
            });
            let mut active_kc = order[..active].to_vec();
            active_kc.sort_unstable();
            kc.fill(0.0);
            for &i in &active_kc { kc[i] = 1.0; }
            let mut edges = Vec::new();
            let mut offsets = vec![0usize];
            for post in 0..graph.kc_mb.n_post {
                for ix in graph.kc_mb.row(post) {
                    if kc[graph.kc_mb.edges[ix].pre as usize] > 0.0 { edges.push(ix); }
                }
                offsets.push(edges.len());
            }
            let mut dan = vec![0.0_f32; graph.kc_dan.n_post];
            graph.kc_dan.normalized_projection(&kc, &mut dan);
            patterns.push(Pattern { edges, offsets, dan });
        }
        assert!(schedule.iter().all(|row| row.len() == 13 && row[0] < cues && row[1..].iter().all(|&x| x >= cues && x < cues + 32)));
        Self { patterns, cues, labels, schedule }
    }
}
