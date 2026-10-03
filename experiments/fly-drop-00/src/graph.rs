use crate::census::{self, MatrixCensus};
use anyhow::{Context, Result, ensure};
use bytemuck::{cast_slice, cast_slice_mut};
use hashbrown::HashMap;
use memmap2::{Mmap, MmapMut, MmapOptions};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

pub const WIDTH: usize = 128;
pub const ADAPTER_SEEDS: [u64; 4] = [1101, 1102, 1103, 1104];
pub const DEGREE_SEEDS: [u64; 4] = [2101, 2102, 2103, 2104];
pub const RANDOM_SEEDS: [u64; 4] = [3101, 3102, 3103, 3104];
pub const DENSE_SEEDS: [u64; 4] = [5101, 5102, 5103, 5104];
const EXPECTED_ROWS: usize = 151_856_684;
const EXPECTED_NODES: usize = 88_384_522;
const EXPECTED_SOURCE_SHA: &str = "e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1";
const GOLDEN: u64 = 0x9e37_79b9_7f4a_7c15;
const PRE_MIX: u64 = 0x7072_652d_6e75_6c6c;
const POST_MIX: u64 = 0x706f_7374_2d6e_756c;

#[derive(Clone, Copy, Default)]
#[repr(C)]
struct NodeMeta {
    incoming_weight: u64,
    buckets: [u8; 4],
}

#[derive(Serialize)]
pub struct BuildManifest {
    pub source_rows: usize,
    pub source_sha256: String,
    pub source_columns: Vec<ColumnReceipt>,
    pub endpoint_count: usize,
    pub endpoint_universe_sha256: String,
    pub adapters: Vec<AdapterReceipt>,
    pub fixture_projection_verified: bool,
    pub graphs: Vec<GraphReceipt>,
    pub operators: Vec<OperatorReceipt>,
    pub teacher_worlds: Vec<crate::synthetic::TeacherReceipt>,
}

#[derive(Serialize)]
pub struct ColumnReceipt {
    source_column: String,
    bytes: u64,
    sha256: String,
}

#[derive(Serialize)]
pub struct AdapterReceipt {
    seed: u64,
    bucket_rule: String,
    bucket_populations: Vec<u64>,
    map_sha256: String,
}

#[derive(Serialize)]
pub struct GraphReceipt {
    arm: String,
    seed: Option<u64>,
    rows: usize,
    canonical_row_stream_sha256: String,
    construction: String,
}

#[derive(Serialize)]
pub struct OperatorReceipt {
    arm: String,
    graph_seed: Option<u64>,
    adapter_seed: Option<u64>,
    control_seed: Option<u64>,
    matrix_file: String,
    matrix_sha256: String,
    census: MatrixCensus,
}

impl BuildManifest {
    pub fn new(source_rows: usize, source_sha256: String) -> Self {
        Self {
            source_rows,
            source_sha256,
            source_columns: Vec::new(),
            endpoint_count: 0,
            endpoint_universe_sha256: String::new(),
            adapters: Vec::new(),
            fixture_projection_verified: false,
            graphs: Vec::new(),
            operators: Vec::new(),
            teacher_worlds: Vec::new(),
        }
    }
}

struct Columns {
    pre: Mmap,
    post: Mmap,
    weight: Mmap,
}

impl Columns {
    fn open(stage: &Path, expected_rows: usize, source_sha: &str) -> Result<Self> {
        let receipt: serde_json::Value = serde_json::from_slice(&fs::read(stage.join("columns-receipt.json"))?)?;
        ensure!(receipt["source_sha256"].as_str() == Some(source_sha), "staged source hash differs from preflight");
        ensure!(source_sha == EXPECTED_SOURCE_SHA, "unexpected MaleCNS v1.0 source identity");
        ensure!(receipt["source_rows"].as_u64() == Some(expected_rows as u64), "row count mismatch");
        ensure!(expected_rows == EXPECTED_ROWS, "unexpected source row count");
        let mut maps = Vec::with_capacity(3);
        let mut receipts = Vec::with_capacity(3);
        for (column, file_name) in [("body_pre", "pre.i64le"), ("body_post", "post.i64le"), ("weight", "weight.i64le")] {
            let path = stage.join(file_name);
            let file = File::open(&path).with_context(|| format!("open {}", path.display()))?;
            // SAFETY: staged column files are immutable for the duration of this process.
            let map = unsafe { MmapOptions::new().map(&file)? };
            ensure!(map.len() == expected_rows * 8, "bad byte length for {file_name}");
            let hash = hex(&Sha256::digest(&map));
            let column_receipt = receipt["columns"].as_array().context("missing column receipts")?
                .iter().find(|r| r["source_column"].as_str() == Some(column)).context("column receipt missing")?;
            ensure!(column_receipt["sha256"].as_str() == Some(hash.as_str()), "staged hash mismatch for {file_name}");
            ensure!(column_receipt["bytes"].as_u64() == Some(map.len() as u64), "staged byte count mismatch");
            receipts.push(ColumnReceipt { source_column: column.to_owned(), bytes: map.len() as u64, sha256: hash });
            maps.push(map);
        }
        Ok(Self { pre: maps.remove(0), post: maps.remove(0), weight: maps.remove(0) })
    }

    fn pre(&self) -> &[i64] { cast_slice(&self.pre) }
    fn post(&self) -> &[i64] { cast_slice(&self.post) }
    fn weight(&self) -> &[i64] { cast_slice(&self.weight) }
}

pub fn build_all(stage: &Path, artifacts: &Path, manifest: &mut BuildManifest) -> Result<()> {
    verify_fixture_projection()?;
    manifest.fixture_projection_verified = true;
    println!("verifying staged source columns");
    let columns = Columns::open(stage, manifest.source_rows, &manifest.source_sha256)?;
    let expected = [
        ("body_pre", "pre.i64le"), ("body_post", "post.i64le"), ("weight", "weight.i64le"),
    ];
    let staged: serde_json::Value = serde_json::from_slice(&fs::read(stage.join("columns-receipt.json"))?)?;
    for ((name, _), receipt) in expected.iter().zip(staged["columns"].as_array().unwrap()) {
        let _ = name;
        manifest.source_columns.push(ColumnReceipt {
            source_column: receipt["source_column"].as_str().unwrap().to_owned(),
            bytes: receipt["bytes"].as_u64().unwrap(),
            sha256: receipt["sha256"].as_str().unwrap().to_owned(),
        });
    }
    println!("building 88M-endpoint incoming-strength index");
    let mut nodes = make_node_index(&columns)?;
    ensure!(nodes.len() == EXPECTED_NODES, "source endpoint count differs from preflight");
    let mut universe: Vec<i64> = nodes.keys().copied().collect();
    universe.sort_unstable();
    manifest.endpoint_count = universe.len();
    manifest.endpoint_universe_sha256 = hash_ids(&universe);
    let mut bucket_populations = [[0u64; WIDTH]; 4];
    install_adapters(&universe, &mut nodes, &mut bucket_populations, &mut manifest.adapters);

    println!("projecting released MaleCNS rows");
    build_real_male(&columns, &nodes, &bucket_populations, artifacts, manifest)?;
    for &seed in &DEGREE_SEEDS {
        println!("building degree-preserving graph seed {seed}");
        build_degree_null(seed, &columns, &nodes, &bucket_populations, artifacts, manifest)?;
    }
    for &seed in &RANDOM_SEEDS {
        println!("building random-sparse graph seed {seed}");
        build_random_null(seed, &columns, &universe, &mut nodes, &bucket_populations, artifacts, manifest)?;
    }
    for &seed in &DENSE_SEEDS { build_dense(seed, artifacts, manifest)?; }
    build_identity(artifacts, manifest)?;
    ensure!(manifest.operators.len() == 41, "expected 41 unique frozen operators");
    let unique_files: std::collections::HashSet<_> = manifest.operators.iter().map(|op| op.matrix_file.as_str()).collect();
    ensure!(unique_files.len() == manifest.operators.len(), "operator filenames collide");
    Ok(())
}

fn make_node_index(columns: &Columns) -> Result<HashMap<i64, NodeMeta>> {
    let mut nodes: HashMap<i64, NodeMeta> = HashMap::with_capacity(EXPECTED_NODES);
    for ((&pre, &post), &weight) in columns.pre().iter().zip(columns.post()).zip(columns.weight()) {
        ensure!(pre >= 0 && post >= 0 && weight > 0, "invalid endpoint or nonpositive weight in source");
        nodes.entry(pre).or_default();
        let post_meta = nodes.entry(post).or_default();
        post_meta.incoming_weight = post_meta.incoming_weight.checked_add(weight as u64).context("incoming weight overflow")?;
    }
    Ok(nodes)
}

fn install_adapters(universe: &[i64], nodes: &mut HashMap<i64, NodeMeta>, all_populations: &mut [[u64; WIDTH]; 4], out: &mut Vec<AdapterReceipt>) {
    let mut hashers: [Sha256; 4] = std::array::from_fn(|_| Sha256::new());
    let mut populations = [[0u64; WIDTH]; 4];
    for &id in universe {
        let meta = nodes.get_mut(&id).expect("universe came from node map");
        for (slot, &seed) in ADAPTER_SEEDS.iter().enumerate() {
            let bucket = (splitmix64((id as u64) ^ seed) & 127) as u8;
            meta.buckets[slot] = bucket;
            populations[slot][bucket as usize] += 1;
            hashers[slot].update(id.to_le_bytes());
            hashers[slot].update([bucket]);
        }
    }
    *all_populations = populations;
    for (i, &seed) in ADAPTER_SEEDS.iter().enumerate() {
        out.push(AdapterReceipt {
            seed,
            bucket_rule: "SplitMix64(u64(id) XOR seed) AND 127".to_owned(),
            bucket_populations: populations[i].to_vec(),
            map_sha256: hex(&hashers[i].clone().finalize()),
        });
    }
}

fn build_real_male(columns: &Columns, nodes: &HashMap<i64, NodeMeta>, populations: &[[u64; WIDTH]; 4], artifacts: &Path, manifest: &mut BuildManifest) -> Result<()> {
    let mut hasher = RowHasher::new("FLY-DROP-00/canonical-rows/v1");
    let mut matrices = empty_matrices();
    for ((&pre, &post), &weight) in columns.pre().iter().zip(columns.post()).zip(columns.weight()) {
        hasher.push(pre, post, weight);
        project_row(pre, post, weight, nodes, populations, &mut matrices)?;
    }
    manifest.graphs.push(GraphReceipt { arm: "malecns".into(), seed: None, rows: columns.pre().len(), canonical_row_stream_sha256: hasher.finish(), construction: "released source row order and values".into() });
    write_graph_matrices("malecns", None, &matrices, populations, artifacts, manifest)
}

fn build_degree_null(seed: u64, columns: &Columns, nodes: &HashMap<i64, NodeMeta>, populations: &[[u64; WIDTH]; 4], artifacts: &Path, manifest: &mut BuildManifest) -> Result<()> {
    let scratch = PathBuf::from(format!(r"D:\fly-drop-00-stage\degree-pre-{seed}.i64le"));
    let mut source = File::open(Path::new(r"D:\fly-drop-00-stage\columns\pre.i64le"))?;
    let mut target = OpenOptions::new().write(true).create_new(true).open(&scratch)
        .with_context(|| format!("scratch already exists or cannot create: {}", scratch.display()))?;
    std::io::copy(&mut source, &mut target)?;
    target.flush()?;
    drop(target);
    let scratch_file = OpenOptions::new().read(true).write(true).open(&scratch)?;
    // SAFETY: this process exclusively created the scratch copy and mutates it in place.
    let mut shuffled = unsafe { MmapMut::map_mut(&scratch_file)? };
    let ids: &mut [i64] = cast_slice_mut(&mut shuffled);
    let mut rng = SplitMix::new(seed ^ 0x6465_6772_6565_2d70);
    for i in (1..ids.len()).rev() {
        let j = rng.below((i + 1) as u64) as usize;
        ids.swap(i, j);
    }
    let mut hasher = RowHasher::new("FLY-DROP-00/canonical-rows/v1");
    let mut matrices = empty_matrices();
    for (i, (&post, &weight)) in columns.post().iter().zip(columns.weight()).enumerate() {
        let pre = ids[i];
        hasher.push(pre, post, weight);
        project_row(pre, post, weight, nodes, populations, &mut matrices)?;
    }
    manifest.graphs.push(GraphReceipt { arm: "degree-preserved-shuffle".into(), seed: Some(seed), rows: ids.len(), canonical_row_stream_sha256: hasher.finish(), construction: "Fisher-Yates permutation of the complete body_pre column; body_post and weight stay at original row positions; loops and duplicates retained".into() });
    write_graph_matrices("degree", Some(seed), &matrices, populations, artifacts, manifest)?;
    drop(shuffled);
    drop(scratch_file);
    fs::remove_file(&scratch)?;
    Ok(())
}

fn build_random_null(seed: u64, columns: &Columns, universe: &[i64], nodes: &mut HashMap<i64, NodeMeta>, populations: &[[u64; WIDTH]; 4], artifacts: &Path, manifest: &mut BuildManifest) -> Result<()> {
    for meta in nodes.values_mut() { meta.incoming_weight = 0; }
    let mut post_rng = SplitMix::new(seed ^ POST_MIX);
    for &weight in columns.weight() {
        let post = universe[post_rng.below(universe.len() as u64) as usize];
        let meta = nodes.get_mut(&post).expect("sampled from universe");
        meta.incoming_weight = meta.incoming_weight.checked_add(weight as u64).context("random-null incoming weight overflow")?;
    }
    let mut pre_rng = SplitMix::new(seed ^ PRE_MIX);
    post_rng = SplitMix::new(seed ^ POST_MIX);
    let mut hasher = RowHasher::new("FLY-DROP-00/canonical-rows/v1");
    let mut matrices = empty_matrices();
    for &weight in columns.weight() {
        let pre = universe[pre_rng.below(universe.len() as u64) as usize];
        let post = universe[post_rng.below(universe.len() as u64) as usize];
        hasher.push(pre, post, weight);
        project_row(pre, post, weight, nodes, populations, &mut matrices)?;
    }
    manifest.graphs.push(GraphReceipt { arm: "random-sparse".into(), seed: Some(seed), rows: columns.weight().len(), canonical_row_stream_sha256: hasher.finish(), construction: "independent unbiased uniform endpoint draws from sorted frozen universe for pre and post; source row weight retained; loops and duplicates retained".into() });
    write_graph_matrices("random", Some(seed), &matrices, populations, artifacts, manifest)?;
    for meta in nodes.values_mut() { meta.incoming_weight = 0; }
    for (&post, &weight) in columns.post().iter().zip(columns.weight()) {
        let meta = nodes.get_mut(&post).expect("source endpoint map");
        meta.incoming_weight += weight as u64;
    }
    Ok(())
}

fn build_dense(seed: u64, artifacts: &Path, manifest: &mut BuildManifest) -> Result<()> {
    let mut rng = SplitMix::new(seed ^ 0x6465_6e73_652d_7631);
    let mut matrix = vec![0.0f64; WIDTH * WIDTH];
    for row in matrix.chunks_exact_mut(WIDTH) {
        let mut total = 0.0;
        for value in row.iter_mut() { *value = -rng.uniform_open().ln(); total += *value; }
        for value in row { *value /= total; }
    }
    write_operator("dense", None, None, Some(seed), &matrix, None, artifacts, manifest)
}

fn build_identity(artifacts: &Path, manifest: &mut BuildManifest) -> Result<()> {
    let mut matrix = vec![0.0f64; WIDTH * WIDTH];
    for i in 0..WIDTH { matrix[i * WIDTH + i] = 1.0; }
    write_operator("identity", None, None, None, &matrix, None, artifacts, manifest)
}

fn empty_matrices() -> Vec<Vec<f64>> { (0..4).map(|_| vec![0.0; WIDTH * WIDTH]).collect() }

fn project_row(pre: i64, post: i64, weight: i64, nodes: &HashMap<i64, NodeMeta>, populations: &[[u64; WIDTH]; 4], matrices: &mut [Vec<f64>]) -> Result<()> {
    let src = nodes.get(&pre).context("source endpoint missing")?;
    let dst = nodes.get(&post).context("destination endpoint missing")?;
    let denominator = dst.incoming_weight;
    if denominator == 0 { return Ok(()); }
    let normalized = weight as f64 / denominator as f64;
    for adapter in 0..4 {
        let row = dst.buckets[adapter] as usize;
        let col = src.buckets[adapter] as usize;
        let population = populations[adapter][row];
        ensure!(population > 0, "nonempty node bucket has zero population");
        matrices[adapter][row * WIDTH + col] += normalized / population as f64;
    }
    Ok(())
}

fn write_graph_matrices(arm: &str, graph_seed: Option<u64>, matrices: &[Vec<f64>], populations: &[[u64; WIDTH]; 4], artifacts: &Path, manifest: &mut BuildManifest) -> Result<()> {
    for (adapter, matrix) in matrices.iter().enumerate() {
        let seed = ADAPTER_SEEDS[adapter];
        write_operator(arm, graph_seed, Some(seed), None, matrix, Some(populations[adapter]), artifacts, manifest)?;
    }
    Ok(())
}

fn write_operator(arm: &str, graph_seed: Option<u64>, adapter_seed: Option<u64>, control_seed: Option<u64>, matrix: &[f64], populations: Option<[u64; WIDTH]>, artifacts: &Path, manifest: &mut BuildManifest) -> Result<()> {
    let tag = match (graph_seed, adapter_seed, control_seed) {
        (Some(g), Some(a), None) => format!("{arm}-g{g}-a{a}"),
        (None, Some(a), None) => format!("{arm}-a{a}"),
        (Some(g), None, None) => format!("{arm}-g{g}"),
        (None, None, Some(s)) => format!("{arm}-s{s}"),
        (None, None, None) => arm.to_owned(),
        _ => anyhow::bail!("invalid operator identity tuple"),
    };
    let path = artifacts.join("operators").join(format!("{tag}.f64le"));
    let bytes: &[u8] = cast_slice(matrix);
    let mut file = OpenOptions::new().write(true).create_new(true).open(&path)
        .with_context(|| format!("refusing to overwrite operator {}", path.display()))?;
    file.write_all(bytes)?;
    file.flush()?;
    let matrix_hash = hex(&Sha256::digest(bytes));
    let census = census::analyze_matrix(matrix, populations)?;
    manifest.operators.push(OperatorReceipt {
        arm: arm.to_owned(), graph_seed, adapter_seed, control_seed,
        matrix_file: path.to_string_lossy().replace('\\', "/"),
        matrix_sha256: matrix_hash, census,
    });
    Ok(())
}

fn hash_ids(ids: &[i64]) -> String {
    let mut hash = Sha256::new();
    for id in ids { hash.update(id.to_le_bytes()); }
    hex(&hash.finalize())
}

pub(crate) fn verify_fixture_projection() -> Result<()> {
    let edges = [(10i64, 20i64, 2u64), (30, 20, 1), (20, 30, 3), (30, 40, 1)];
    let ids = [10i64, 20, 30, 40];
    let incoming = [0u64, 3, 3, 1];
    let mut x = [0.0f64; WIDTH];
    for (i, value) in x.iter_mut().enumerate() { *value = (i as f64 * 0.37).sin(); }
    for &seed in &ADAPTER_SEEDS {
        let bucket = |id: i64| (splitmix64((id as u64) ^ seed) & 127) as usize;
        let mut populations = [0.0f64; WIDTH];
        for id in ids { populations[bucket(id)] += 1.0; }
        let mut m = vec![0.0f64; WIDTH * WIDTH];
        for &(pre, post, w) in &edges {
            let d = incoming[ids.iter().position(|&id| id == post).unwrap()];
            if d > 0 { let r = bucket(post); let c = bucket(pre); m[r * WIDTH + c] += w as f64 / d as f64 / populations[r]; }
        }
        let mut direct = [0.0f64; WIDTH];
        for id in ids {
            let mut value = 0.0;
            for &(pre, post, w) in &edges {
                if post == id {
                    let d = incoming[ids.iter().position(|&candidate| candidate == post).unwrap()];
                    if d > 0 { value += (w as f64 / d as f64) * x[bucket(pre)]; }
                }
            }
            direct[bucket(id)] += value / populations[bucket(id)];
        }
        for row in 0..WIDTH {
            let projected: f64 = (0..WIDTH).map(|col| m[row * WIDTH + col] * x[col]).sum();
            ensure!((projected - direct[row]).abs() <= 1e-12, "exact projection fixture mismatch for adapter {seed}, row {row}");
        }
    }
    Ok(())
}

fn hex(bytes: &[u8]) -> String { bytes.iter().map(|b| format!("{b:02x}")).collect() }

fn splitmix64(value: u64) -> u64 {
    let mut z = value.wrapping_add(GOLDEN);
    z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    z ^ (z >> 31)
}

pub(crate) struct SplitMix { state: u64 }
impl SplitMix {
    pub(crate) fn new(seed: u64) -> Self { Self { state: seed } }
    pub(crate) fn next(&mut self) -> u64 { self.state = self.state.wrapping_add(GOLDEN); splitmix64(self.state.wrapping_sub(GOLDEN)) }
    pub(crate) fn below(&mut self, upper: u64) -> u64 {
        let threshold = upper.wrapping_neg() % upper;
        loop { let value = self.next(); if value >= threshold { return value % upper; } }
    }
    pub(crate) fn uniform_open(&mut self) -> f64 { ((self.next() >> 12) as f64 + 1.0) / 4_503_599_627_370_497.0 }
    pub(crate) fn normal(&mut self) -> f64 {
        (-2.0 * self.uniform_open().ln()).sqrt() * (std::f64::consts::TAU * self.uniform_open()).cos()
    }
}

struct RowHasher { sha: Sha256, buffer: Vec<u8> }
impl RowHasher {
    fn new(domain: &str) -> Self { let mut sha = Sha256::new(); sha.update(domain.as_bytes()); Self { sha, buffer: Vec::with_capacity(1 << 20) } }
    fn push(&mut self, pre: i64, post: i64, weight: i64) {
        self.buffer.extend_from_slice(&pre.to_le_bytes()); self.buffer.extend_from_slice(&post.to_le_bytes()); self.buffer.extend_from_slice(&weight.to_le_bytes());
        if self.buffer.len() >= 1 << 20 { self.sha.update(&self.buffer); self.buffer.clear(); }
    }
    fn finish(mut self) -> String { self.sha.update(&self.buffer); hex(&self.sha.finalize()) }
}
