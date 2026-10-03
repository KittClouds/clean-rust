use anyhow::{Context, Result, ensure};
use memmap2::Mmap;
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
}

impl Layer {
    pub fn new(mut edges: Vec<Edge>, n_pre: usize, n_post: usize) -> Self {
        edges.sort_unstable_by_key(|e| (e.post, e.pre));
        assert!(edges.iter().all(|e| {
            (e.pre as usize) < n_pre && (e.post as usize) < n_post && e.count > 0
        }));
        assert!(edges.windows(2).all(|x| (x[0].pre, x[0].post) != (x[1].pre, x[1].post)));
        let mut offsets = vec![0; n_post + 1];
        for edge in &edges { offsets[edge.post as usize + 1] += 1; }
        for i in 1..offsets.len() { offsets[i] += offsets[i - 1]; }
        Self { edges, offsets, n_pre, n_post }
    }

    #[inline]
    pub fn row(&self, post: usize) -> std::ops::Range<usize> {
        self.offsets[post]..self.offsets[post + 1]
    }

    #[inline]
    pub fn normalized_projection(&self, input: &[f32], output: &mut [f32]) {
        for post in 0..self.n_post {
            let mut total = 0.0_f32;
            let mut sum = 0.0_f32;
            for edge in &self.edges[self.row(post)] {
                let count = edge.count as f32;
                total += count;
                sum += count * input[edge.pre as usize];
            }
            output[post] = if total > 0.0 { sum / total } else { 0.0 };
        }
    }
}

fn mapped(path: &Path) -> Result<Mmap> {
    let file = File::open(path).with_context(|| path.display().to_string())?;
    // SAFETY: inputs are hash-verified and read-only for the run.
    Ok(unsafe { Mmap::map(&file)? })
}

fn lines(map: &Mmap) -> impl Iterator<Item = Result<&str>> {
    memchr::memchr_iter(b'\n', map).scan(0, move |start, end| {
        let line = &map[*start..end];
        *start = end + 1;
        Some(std::str::from_utf8(line).map_err(Into::into))
    }).skip(1)
}

pub fn load(root: &Path, substrate: &str, side: &str, glut_sign: f32) -> Result<Graph> {
    let anatomy = root.join("inputs/anatomy");
    let nodes = mapped(&anatomy.join(format!("nodes-{side}.tsv")))?;
    let mut kinds = Vec::new();
    let mut local = Vec::new();
    let mut counts = [0usize; 5];
    let mut mb_sign = Vec::new();
    for line in lines(&nodes) {
        let line = line?;
        let mut cols = line.trim_end().split('\t');
        let _body: u64 = cols.next().context("body")?.parse()?;
        let kind: usize = cols.next().context("kind")?.parse()?;
        let nt = cols.next().context("nt")?;
        ensure!(kind < 5);
        kinds.push(kind);
        local.push(counts[kind] as u32);
        counts[kind] += 1;
        if kind == 2 {
            mb_sign.push(match nt {
                "gaba" => -1.0,
                "glutamate" => glut_sign,
                "acetylcholine" => 1.0,
                _ => 1.0,
            });
        }
    }
    let edge_root = if substrate == "fly" {
        anatomy.clone()
    } else {
        root.join(format!("inputs/null-graphs/{substrate}"))
    };
    let edges = mapped(&edge_root.join(format!("edges-{side}.tsv")))?;
    let mut groups: [Vec<Edge>; 5] = std::array::from_fn(|_| Vec::new());
    for line in lines(&edges) {
        let line = line?;
        let mut cols = line.trim_end().split('\t');
        let pre: usize = cols.next().context("pre")?.parse()?;
        let post: usize = cols.next().context("post")?.parse()?;
        let count: u32 = cols.next().context("weight")?.parse()?;
        ensure!(pre < kinds.len() && post < kinds.len() && count > 0);
        let group = match (kinds[pre], kinds[post]) {
            (0, 1) => 0,
            (1, 2) => 1,
            (1, 3) => 2,
            (2, 3) => 3,
            (3, 2) => 4,
            _ => continue,
        };
        groups[group].push(Edge { pre: local[pre], post: local[post], count });
    }
    ensure!(counts[..4].iter().all(|&x| x > 0));
    let [pn_kc, kc_mb, kc_dan, mb_dan, route] = groups;
    Ok(Graph {
        pn_kc: Layer::new(pn_kc, counts[0], counts[1]),
        kc_mb: Layer::new(kc_mb, counts[1], counts[2]),
        kc_dan: Layer::new(kc_dan, counts[1], counts[3]),
        mb_dan: Layer::new(mb_dan, counts[2], counts[3]),
        route: Layer::new(route, counts[3], counts[2]),
        mb_sign,
    })
}

pub fn canonical_edge_indices(graph: &Graph) -> Vec<usize> {
    let mut values: Vec<(u32, u32, u32, usize)> = graph.kc_mb.edges.iter()
        .enumerate().map(|(i, e)| (e.pre, e.post, e.count, i)).collect();
    values.sort_unstable_by_key(|x| (x.0, x.1, x.2));
    values.into_iter().map(|x| x.3).collect()
}
