use crate::rng::Rng;
use anyhow::{Context, Result, ensure};
use hashbrown::HashSet;
use memmap2::Mmap;
use serde::Serialize;
use std::{fs::File, path::Path};

#[derive(Clone, Copy, Debug)]
pub struct Edge {
    pub pre: u32,
    pub post: u32,
    pub count: u32,
}
#[derive(Clone)]
pub struct Layer {
    pub edges: Vec<Edge>,
    pub offsets: Vec<usize>,
    pub n_pre: usize,
    pub n_post: usize,
}
#[derive(Clone)]
pub struct Graph {
    pub pn_kc: Layer,
    pub kc_mb: Layer,
    pub kc_dan: Layer,
    pub mb_dan: Layer,
    pub route: Layer,
    pub mb_sign: Vec<f32>,
    pub nt_uncertain: usize,
}
#[derive(Serialize, Debug)]
pub struct NullReceipt {
    pub edges: usize,
    pub attempts: usize,
    pub accepted: usize,
    pub retained_fraction: f64,
    pub degree_preserved: bool,
    pub source_strength_preserved: bool,
}

fn key(pre: u32, post: u32) -> u64 {
    ((pre as u64) << 32) | post as u64
}
impl Layer {
    pub fn new(mut edges: Vec<Edge>, n_pre: usize, n_post: usize) -> Self {
        edges.sort_unstable_by_key(|e| (e.post, e.pre));
        assert!(
            edges
                .iter()
                .all(|e| (e.pre as usize) < n_pre && (e.post as usize) < n_post && e.count > 0)
        );
        assert!(
            edges
                .windows(2)
                .all(|es| (es[0].pre, es[0].post) != (es[1].pre, es[1].post))
        );
        let mut offsets = vec![0; n_post + 1];
        for e in &edges {
            offsets[e.post as usize + 1] += 1;
        }
        for i in 1..offsets.len() {
            offsets[i] += offsets[i - 1];
        }
        Self {
            edges,
            offsets,
            n_pre,
            n_post,
        }
    }
    pub fn row(&self, target: usize) -> std::ops::Range<usize> {
        self.offsets[target]..self.offsets[target + 1]
    }
    fn invariants(&self) -> (Vec<usize>, Vec<usize>, Vec<u64>) {
        let mut a = vec![0; self.n_pre];
        let mut b = vec![0; self.n_post];
        let mut s = vec![0; self.n_pre];
        for e in &self.edges {
            a[e.pre as usize] += 1;
            b[e.post as usize] += 1;
            s[e.pre as usize] += e.count as u64;
        }
        (a, b, s)
    }
    pub fn rewired(&self, seed: u64) -> (Self, NullReceipt) {
        let mut edges = self.edges.clone();
        let original: HashSet<_> = edges.iter().map(|e| key(e.pre, e.post)).collect();
        let mut pairs = original.clone();
        let mut rng = Rng(seed);
        let mut accepted = 0;
        let attempts = 20 * edges.len();
        for _ in 0..attempts {
            if edges.len() < 2 {
                break;
            }
            let i = rng.index(edges.len());
            let j = rng.index(edges.len());
            let a = edges[i];
            let b = edges[j];
            if a.pre == b.pre
                || a.post == b.post
                || pairs.contains(&key(a.pre, b.post))
                || pairs.contains(&key(b.pre, a.post))
            {
                continue;
            }
            pairs.remove(&key(a.pre, a.post));
            pairs.remove(&key(b.pre, b.post));
            pairs.insert(key(a.pre, b.post));
            pairs.insert(key(b.pre, a.post));
            edges[i].post = b.post;
            edges[j].post = a.post;
            accepted += 1;
        }
        let result = Self::new(edges, self.n_pre, self.n_post);
        let before = self.invariants();
        let after = result.invariants();
        let receipt = NullReceipt {
            edges: self.edges.len(),
            attempts,
            accepted,
            retained_fraction: pairs.iter().filter(|k| original.contains(*k)).count() as f64
                / pairs.len().max(1) as f64,
            degree_preserved: before.0 == after.0 && before.1 == after.1,
            source_strength_preserved: before.2 == after.2,
        };
        assert!(receipt.degree_preserved && receipt.source_strength_preserved);
        (result, receipt)
    }
    pub fn normalized_projection(&self, input: &[f32], output: &mut [f32]) {
        for (j, out) in output.iter_mut().enumerate() {
            let mut total = 0.0;
            let mut sum = 0.0;
            for e in &self.edges[self.row(j)] {
                let c = e.count as f32;
                sum += c * input[e.pre as usize];
                total += c;
            }
            *out = if total > 0.0 { sum / total } else { 0.0 };
        }
    }
}

fn lines(map: &Mmap) -> impl Iterator<Item = Result<&str>> {
    memchr::memchr_iter(b'\n', map)
        .scan(0, move |start, end| {
            let line = &map[*start..end];
            *start = end + 1;
            Some(std::str::from_utf8(line).map_err(Into::into))
        })
        .skip(1)
}
fn mapped(path: &Path) -> Result<Mmap> {
    let file = File::open(path).with_context(|| path.display().to_string())?;
    // SAFETY: experiment source files are read-only throughout a run and hash-verified by the launcher.
    Ok(unsafe { Mmap::map(&file)? })
}
impl Graph {
    pub fn routing_motifs(&self, route: &Layer) -> [u64; 2] {
        let feedback: HashSet<_> = self
            .mb_dan
            .edges
            .iter()
            .map(|e| key(e.pre, e.post))
            .collect();
        let kc_dan: HashSet<_> = self
            .kc_dan
            .edges
            .iter()
            .map(|e| key(e.pre, e.post))
            .collect();
        let mut reciprocal = 0;
        let mut feedforward = 0;
        for e in &route.edges {
            if feedback.contains(&key(e.post, e.pre)) {
                reciprocal += 1;
            }
            for k in &self.kc_mb.edges[self.kc_mb.row(e.post as usize)] {
                if kc_dan.contains(&key(k.pre, e.pre)) {
                    feedforward += 1;
                }
            }
        }
        [reciprocal, feedforward]
    }
    pub fn load(root: &Path, side: &str, glut_sign: f32) -> Result<Self> {
        let nodes = mapped(&root.join(format!("nodes-{side}.tsv")))?;
        let mut kinds = Vec::new();
        let mut local = Vec::new();
        let mut counts = [0; 5];
        let mut mb_sign = Vec::new();
        let mut nt_uncertain = 0;
        for line in lines(&nodes) {
            let line = line?;
            let mut cols = line.trim_end().split('\t');
            let _body: u64 = cols.next().context("body")?.parse()?;
            let k: usize = cols.next().context("kind")?.parse()?;
            ensure!(k < 5);
            let nt = cols.next().context("nt")?;
            kinds.push(k);
            local.push(counts[k] as u32);
            counts[k] += 1;
            if k == 2 {
                mb_sign.push(match nt {
                    "gaba" => -1.0,
                    "glutamate" => glut_sign,
                    "acetylcholine" => 1.0,
                    _ => {
                        nt_uncertain += 1;
                        1.0
                    }
                });
            }
        }
        let edges = mapped(&root.join(format!("edges-{side}.tsv")))?;
        let mut groups: [Vec<Edge>; 5] = std::array::from_fn(|_| Vec::new());
        for line in lines(&edges) {
            let line = line?;
            let mut cols = line.trim_end().split('\t');
            let pre: usize = cols.next().context("pre")?.parse()?;
            let post: usize = cols.next().context("post")?.parse()?;
            let count: u32 = cols.next().context("count")?.parse()?;
            ensure!(pre < kinds.len() && post < kinds.len() && count > 0);
            let group = match (kinds[pre], kinds[post]) {
                (0, 1) => 0,
                (1, 2) => 1,
                (1, 3) => 2,
                (2, 3) => 3,
                (3, 2) => 4,
                _ => continue,
            };
            groups[group].push(Edge {
                pre: local[pre],
                post: local[post],
                count,
            });
        }
        ensure!(counts[..4].iter().all(|&n| n > 0));
        let [a, b, c, d, e] = groups;
        Ok(Self {
            pn_kc: Layer::new(a, counts[0], counts[1]),
            kc_mb: Layer::new(b, counts[1], counts[2]),
            kc_dan: Layer::new(c, counts[1], counts[3]),
            mb_dan: Layer::new(d, counts[2], counts[3]),
            route: Layer::new(e, counts[3], counts[2]),
            mb_sign,
            nt_uncertain,
        })
    }
    pub fn rewire_signal(&self, seed: u64) -> (Self, Vec<NullReceipt>) {
        let (a, ra) = self.pn_kc.rewired(seed ^ 11);
        let (b, rb) = self.kc_mb.rewired(seed ^ 22);
        let (c, rc) = self.kc_dan.rewired(seed ^ 33);
        let (d, rd) = self.mb_dan.rewired(seed ^ 44);
        (
            Self {
                pn_kc: a,
                kc_mb: b,
                kc_dan: c,
                mb_dan: d,
                route: self.route.clone(),
                mb_sign: self.mb_sign.clone(),
                nt_uncertain: self.nt_uncertain,
            },
            vec![ra, rb, rc, rd],
        )
    }
    #[cfg(test)]
    pub fn fixture() -> Self {
        fn layer(a: usize, b: usize, seed: u64) -> Layer {
            let mut rng = Rng(seed);
            let mut edges = Vec::new();
            for post in 0..b {
                for pre in 0..a {
                    if rng.unit() < 0.3 {
                        edges.push(Edge {
                            pre: pre as u32,
                            post: post as u32,
                            count: 1 + (pre % 5) as u32,
                        });
                    }
                }
            }
            Layer::new(edges, a, b)
        }
        Self {
            pn_kc: layer(20, 64, 1),
            kc_mb: layer(64, 8, 2),
            kc_dan: layer(64, 12, 3),
            mb_dan: layer(8, 12, 4),
            route: layer(12, 8, 5),
            mb_sign: vec![1.0; 8],
            nt_uncertain: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn null_preserves_degrees_and_strength_without_duplicates() {
        let g = Graph::fixture();
        let (n, r) = g.kc_mb.rewired(928);
        assert!(
            r.degree_preserved
                && r.source_strength_preserved
                && r.accepted > 0
                && r.retained_fraction < 0.9
        );
        assert_eq!(n.edges.len(), g.kc_mb.edges.len());
    }
    #[test]
    fn complete_graph_null_is_reported_degenerate() {
        let edges = (0..4)
            .flat_map(|pre| {
                (0..3).map(move |post| Edge {
                    pre,
                    post,
                    count: 1,
                })
            })
            .collect();
        let (_, r) = Layer::new(edges, 4, 3).rewired(4);
        assert_eq!(r.accepted, 0);
        assert_eq!(r.retained_fraction, 1.0);
    }
    #[test]
    fn projection_direction_is_pre_to_post() {
        let l = Layer::new(
            vec![Edge {
                pre: 1,
                post: 0,
                count: 3,
            }],
            2,
            1,
        );
        let mut out = [0.0];
        l.normalized_projection(&[9.0, 2.0], &mut out);
        assert_eq!(out, [2.0]);
    }
}
