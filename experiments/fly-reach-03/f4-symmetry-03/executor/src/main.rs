#[path = "../../../executor/src/graph.rs"]
mod graph;
#[path = "../../../executor/src/collector.rs"]
mod collector;
#[path = "../../../executor/src/reach_sim.rs"]
mod reach_sim;
#[path = "../../../executor/src/rng.rs"]
mod rng;
#[path = "../../../executor/src/task.rs"]
mod task;
mod native_collect;

use anyhow::{Context, Result, ensure};
use graph::Graph;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    env,
    fs,
    path::{Path, PathBuf},
};
use task::{Pattern, Task};

const FIRST_CANDIDATE: u64 = 304_000;
const BATCH_SIZE: u64 = 8;
const MAX_BATCHES: u64 = 32;
const NAMED: [&str; 4] = ["0011", "0101", "0001", "0100"];
const SUBSTRATES: [&str; 9] = [
    "fly", "g001", "g002", "g003", "g004", "g005", "g006", "g007", "g008",
];
const SIDES: [&str; 2] = ["L", "R"];

#[derive(Deserialize)]
struct Cell {
    substrate: String,
    side: String,
    coordinates: Vec<usize>,
}

#[derive(Deserialize)]
struct CoordinateManifest {
    cells: Vec<Cell>,
}

#[derive(Serialize)]
struct CellCounts {
    substrate: String,
    side: String,
    sampled_coordinates: usize,
    patterns: BTreeMap<String, usize>,
}

#[derive(Serialize)]
struct BlockCounts {
    block_id: u64,
    total_sampled_coordinates: usize,
    patterns: BTreeMap<String, usize>,
    cells: Vec<CellCounts>,
}

#[derive(Serialize)]
struct BatchCounts {
    candidate_batch: u64,
    accepted: bool,
    supported_blocks_by_pattern: BTreeMap<String, usize>,
    blocks: Vec<BlockCounts>,
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn sha_file(path: &Path) -> Result<String> {
    Ok(sha256(&fs::read(path).with_context(|| path.display().to_string())?))
}

fn read_manifest(study: &Path) -> Result<(CoordinateManifest, Vec<u8>)> {
    let path = study.join("manifests/QUALIFICATION-MANIFEST.json");
    let bytes = fs::read(&path).with_context(|| path.display().to_string())?;
    let value = serde_json::from_slice(&bytes)?;
    Ok((value, bytes))
}

fn index_graphs(lineage: &Path, manifest: &CoordinateManifest) -> Result<Vec<(String, String, Graph, Vec<usize>)>> {
    let mut indexed = Vec::with_capacity(SUBSTRATES.len() * SIDES.len());
    for substrate in SUBSTRATES {
        for side in SIDES {
            let cell = manifest
                .cells
                .iter()
                .find(|cell| cell.substrate == substrate && cell.side == side)
                .with_context(|| format!("missing frozen cell {substrate}:{side}"))?;
            ensure!(cell.coordinates.len() == 64, "coordinate sample changed for {substrate}:{side}");
            let graph = graph::load(lineage, substrate, side, -1.0)?;
            ensure!(
                cell.coordinates.iter().all(|&coordinate| coordinate < graph.kc_mb.edges.len()),
                "coordinate outside KC-MB edge universe for {substrate}:{side}"
            );
            indexed.push((substrate.to_owned(), side.to_owned(), graph, cell.coordinates.clone()));
        }
    }
    ensure!(manifest.cells.len() == indexed.len(), "unexpected coordinate-manifest cells");
    Ok(indexed)
}

// This duplicates only the first four iterations of Task::new. They consume the
// same RNG stream and execute the same projection/selection operations; the
// structural parity fixture below checks all returned edge/offset/DAN bytes.
fn first_cue_patterns(graph: &Graph, seed: u64) -> Vec<Pattern> {
    let mut rng = rng::Rng(seed);
    let np = graph.pn_kc.n_pre;
    let nk = graph.pn_kc.n_post;
    let cues = 4;
    let mut pn = vec![0.0_f32; np];
    let mut kc = vec![0.0_f32; nk];
    let mut pn_order: Vec<usize> = (0..np).collect();
    let mut order: Vec<usize> = (0..nk).collect();
    let mut patterns = Vec::with_capacity(cues);
    for _ in 0..cues {
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
        let mut offsets = vec![0_usize];
        for post in 0..graph.kc_mb.n_post {
            for ix in graph.kc_mb.row(post) {
                if kc[graph.kc_mb.edges[ix].pre as usize] > 0.0 {
                    edges.push(ix);
                }
            }
            offsets.push(edges.len());
        }
        let mut dan = vec![0.0_f32; graph.kc_dan.n_post];
        graph.kc_dan.normalized_projection(&kc, &mut dan);
        patterns.push(Pattern { edges, offsets, dan });
    }
    patterns
}

fn parity_fixture(graph: &Graph, seed: u64) -> Result<()> {
    let labels = vec![true, false, true, false];
    let schedule = vec![vec![0, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4]];
    let full = Task::new(graph, seed, labels, schedule);
    let optimized = first_cue_patterns(graph, seed);
    ensure!(full.patterns.len() >= 4 && optimized.len() == 4);
    for cue in 0..4 {
        ensure!(full.patterns[cue].edges == optimized[cue].edges, "pattern edge mismatch at cue {cue}");
        ensure!(full.patterns[cue].offsets == optimized[cue].offsets, "pattern offset mismatch at cue {cue}");
        ensure!(
            full.patterns[cue].dan.iter().map(|x| x.to_bits()).eq(optimized[cue].dan.iter().map(|x| x.to_bits())),
            "pattern DAN mismatch at cue {cue}"
        );
    }
    Ok(())
}

fn pattern_counts(patterns: &[Pattern], coordinates: &[usize]) -> BTreeMap<String, usize> {
    let mut counts = BTreeMap::new();
    for coordinate in coordinates {
        let mut mask = 0_u8;
        for (cue, pattern) in patterns.iter().take(4).enumerate() {
            if pattern.edges.binary_search(coordinate).is_ok() {
                mask |= 1 << cue;
            }
        }
        *counts.entry(format!("{mask:04b}")).or_insert(0) += 1;
    }
    counts
}

fn candidate_block(
    block_id: u64,
    graphs: &[(String, String, Graph, Vec<usize>)],
) -> Result<BlockCounts> {
    let mut aggregate: BTreeMap<String, usize> = BTreeMap::new();
    let mut cells = Vec::with_capacity(graphs.len());
    let mut total = 0;
    for (substrate, side, graph, coordinates) in graphs {
        let patterns = first_cue_patterns(graph, block_id);
        let cell_counts = pattern_counts(&patterns, coordinates);
        total += coordinates.len();
        for (pattern, count) in &cell_counts {
            *aggregate.entry(pattern.clone()).or_insert(0) += count;
        }
        cells.push(CellCounts {
            substrate: substrate.clone(),
            side: side.clone(),
            sampled_coordinates: coordinates.len(),
            patterns: cell_counts,
        });
    }
    Ok(BlockCounts {
        block_id,
        total_sampled_coordinates: total,
        patterns: aggregate,
        cells,
    })
}

fn source_input_hashes(lineage: &Path, study: &Path, manifest_bytes: &[u8]) -> Result<BTreeMap<String, String>> {
    let mut hashes = BTreeMap::new();
    hashes.insert(
        "manifests/QUALIFICATION-MANIFEST.json".into(),
        sha256(manifest_bytes),
    );
    for side in SIDES {
        let node = PathBuf::from("inputs/anatomy").join(format!("nodes-{side}.tsv"));
        hashes.insert(node.to_string_lossy().into_owned(), sha_file(&lineage.join(&node))?);
        for substrate in SUBSTRATES {
            let edge = if substrate == "fly" {
                PathBuf::from("inputs/anatomy").join(format!("edges-{side}.tsv"))
            } else {
                PathBuf::from("inputs/null-graphs").join(substrate).join(format!("edges-{side}.tsv"))
            };
            hashes.insert(edge.to_string_lossy().into_owned(), sha_file(&lineage.join(&edge))?);
        }
    }
    let _ = study;
    Ok(hashes)
}

fn run(study: &Path, lineage: &Path, output: &Path) -> Result<()> {
    ensure!(output.is_dir(), "output directory must already exist");
    ensure!(
        fs::read_dir(output)?.next().is_none(),
        "output directory must be empty"
    );
    let (manifest, manifest_bytes) = read_manifest(study)?;
    let graphs = index_graphs(lineage, &manifest)?;
    parity_fixture(&graphs[0].2, FIRST_CANDIDATE)?;
    let mut batches = Vec::new();
    let mut accepted_ids = Vec::new();
    for batch in 0..MAX_BATCHES {
        let mut blocks = Vec::with_capacity(BATCH_SIZE as usize);
        for offset in 0..BATCH_SIZE {
            let block_id = FIRST_CANDIDATE + batch * BATCH_SIZE + offset;
            blocks.push(candidate_block(block_id, &graphs)?);
        }
        let supported: BTreeMap<String, usize> = NAMED
            .iter()
            .map(|pattern| {
                let count = blocks.iter().filter(|block| block.patterns.get(*pattern).copied().unwrap_or(0) > 0).count();
                ((*pattern).to_owned(), count)
            })
            .collect();
        let accepted = supported.values().all(|&count| count >= 6);
        if accepted {
            accepted_ids = blocks.iter().map(|block| block.block_id).collect();
        }
        batches.push(BatchCounts {
            candidate_batch: batch,
            accepted,
            supported_blocks_by_pattern: supported,
            blocks,
        });
        if accepted {
            break;
        }
    }
    let source_hashes = source_input_hashes(lineage, study, &manifest_bytes)?;
    let result = serde_json::json!({
        "schema":"F4-SYMMETRY-03-structure-only-screen-v1",
        "status": if accepted_ids.len() == 8 { "PASS" } else { "STOP_NO_STRUCTURAL_BATCH" },
        "qualification_only":true,
        "reads_reference_or_target_data":false,
        "candidate_first":FIRST_CANDIDATE,
        "candidate_last":FIRST_CANDIDATE + MAX_BATCHES * BATCH_SIZE - 1,
        "batch_size":BATCH_SIZE,
        "max_batches":MAX_BATCHES,
        "accepted_block_ids":accepted_ids,
        "required_patterns":NAMED,
        "required_supported_blocks_per_pattern":6,
        "coordinate_count_per_cell":64,
        "screened_cells":graphs.len(),
        "coordinate_manifest_sha256":sha256(&manifest_bytes),
        "source_input_sha256":source_hashes,
        "optimized_cue_pattern_generator_parity":"PASS",
        "selection_rule":"first ascending candidate batch with each named incidence pattern present in at least six of eight blocks; structural counts only",
        "batches":batches,
    });
    let out_path = output.join("STRUCTURAL-SCREEN.json");
    fs::write(&out_path, serde_json::to_vec_pretty(&result)?)?;
    println!(
        "{}",
        serde_json::to_string(&serde_json::json!({
            "status":result["status"],
            "accepted_block_ids":result["accepted_block_ids"],
            "batches_screened":result["batches"].as_array().map_or(0, Vec::len),
            "output":out_path,
        }))?
    );
    Ok(())
}

fn main() -> Result<()> {
    let mut args = env::args_os().skip(1);
    let mode = args.next().context("expected --screen")?;
    match mode.to_string_lossy().as_ref() {
        "--screen" => {
            let study = PathBuf::from(args.next().context("study root")?);
            let lineage = PathBuf::from(args.next().context("lineage root")?);
            let output = PathBuf::from(args.next().context("output root")?);
            ensure!(args.next().is_none(), "unexpected trailing arguments");
            run(&study, &lineage, &output)
        }
        "--collect" => {
            let study = PathBuf::from(args.next().context("study root")?);
            let lineage = PathBuf::from(args.next().context("lineage root")?);
            let task_run = PathBuf::from(args.next().context("task run root")?);
            let output = PathBuf::from(args.next().context("output root")?);
            ensure!(args.next().is_none(), "unexpected trailing arguments");
            native_collect::run(&study, &lineage, &task_run, &output)
        }
        _ => anyhow::bail!("unknown command"),
    }
}
