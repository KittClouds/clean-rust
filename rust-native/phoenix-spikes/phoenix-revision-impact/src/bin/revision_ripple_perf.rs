use std::alloc::{GlobalAlloc, Layout, System};
use std::hint::black_box;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant};

use compact_str::format_compact;
use phoenix_revision_impact::{
    causal_ripple_search, ConstraintSeed, CounterfactualGraphView, EvidenceRef, GraphGeneration,
    InferenceProjectionInput, NamedSidecarDigest, RevisionAnalysisViews, RevisionEdgeRecord,
    RevisionFactRecord, RevisionGraphSnapshot, RevisionRequirementSidecar, RippleConfig,
    REVISION_REQUIREMENT_SIDECAR_SCHEMA,
};
use phoenix_types::{
    ConstraintKind, FactId, FactValue, GraphTruthDigest, StoryInterval, StoryMutation, StoryTime,
};

const NODES: usize = 50_000;
const EDGES: usize = 99_999;
const SAMPLES: usize = 3;

struct TrackingAllocator;

static CURRENT_BYTES: AtomicUsize = AtomicUsize::new(0);
static PEAK_BYTES: AtomicUsize = AtomicUsize::new(0);
static ALLOCATION_CALLS: AtomicUsize = AtomicUsize::new(0);

#[global_allocator]
static ALLOCATOR: TrackingAllocator = TrackingAllocator;

unsafe impl GlobalAlloc for TrackingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() {
            record_allocation(layout.size());
        }
        pointer
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc_zeroed(layout) };
        if !pointer.is_null() {
            record_allocation(layout.size());
        }
        pointer
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        CURRENT_BYTES.fetch_sub(layout.size(), Ordering::Relaxed);
        unsafe { System.dealloc(pointer, layout) };
    }

    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        let resized = unsafe { System.realloc(pointer, layout, new_size) };
        if !resized.is_null() {
            ALLOCATION_CALLS.fetch_add(1, Ordering::Relaxed);
            if new_size >= layout.size() {
                increase_current(new_size - layout.size());
            } else {
                CURRENT_BYTES.fetch_sub(layout.size() - new_size, Ordering::Relaxed);
            }
        }
        resized
    }
}

#[derive(Clone, Copy)]
struct Sample {
    elapsed: Duration,
    allocation_calls: usize,
    peak_additional_bytes: usize,
    retained_result_bytes: usize,
    visited_states: usize,
    traversed_edges: usize,
    path_nodes: usize,
    path_constraints: usize,
}

fn main() {
    let (base, views, requirements) = fixture();
    let overlay = CounterfactualGraphView::new(
        &base,
        vec![StoryMutation::RetractFact {
            fact_id: FactId::from("fact:ripple-root"),
        }],
    )
    .expect("benchmark overlay");
    let mut samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        let baseline_bytes = CURRENT_BYTES.load(Ordering::Relaxed);
        PEAK_BYTES.store(baseline_bytes, Ordering::Relaxed);
        let baseline_calls = ALLOCATION_CALLS.load(Ordering::Relaxed);
        let started = Instant::now();
        let result = causal_ripple_search(
            &overlay,
            &views.constraint_graph,
            &requirements,
            RippleConfig {
                max_traversed_edges: EDGES + 1,
                ..RippleConfig::default()
            },
        )
        .expect("ripple benchmark");
        let elapsed = started.elapsed();
        assert_eq!(result.impacts.len(), NODES);
        assert!(!result.receipt.truncation.truncated());
        black_box(&result);
        let (path_nodes, path_constraints) = result
            .impacts
            .iter()
            .flat_map(|impact| &impact.causal_paths)
            .fold((0, 0), |(nodes, constraints), path| {
                (
                    nodes + path.node_ids.len(),
                    constraints + path.constraint_ids.len(),
                )
            });
        samples.push(Sample {
            elapsed,
            allocation_calls: ALLOCATION_CALLS
                .load(Ordering::Relaxed)
                .saturating_sub(baseline_calls),
            peak_additional_bytes: PEAK_BYTES
                .load(Ordering::Relaxed)
                .saturating_sub(baseline_bytes),
            retained_result_bytes: CURRENT_BYTES
                .load(Ordering::Relaxed)
                .saturating_sub(baseline_bytes),
            visited_states: result.receipt.visited_states,
            traversed_edges: result.receipt.traversed_edges,
            path_nodes,
            path_constraints,
        });
    }
    samples.sort_unstable_by_key(|sample| sample.elapsed);
    let median = samples[SAMPLES / 2];
    println!("nodes={NODES} edges={EDGES} impacts={NODES}");
    println!("samples_ms={}", format_samples(&samples));
    println!("median_ms={:.3}", median.elapsed.as_secs_f64() * 1_000.0);
    println!(
        "edges_per_second={:.0}",
        median.traversed_edges as f64 / median.elapsed.as_secs_f64()
    );
    println!("visited_states={}", median.visited_states);
    println!("traversed_edges={}", median.traversed_edges);
    println!("materialized_path_nodes={}", median.path_nodes);
    println!("materialized_path_constraints={}", median.path_constraints);
    println!("ripple_allocation_calls={}", median.allocation_calls);
    println!(
        "ripple_peak_additional_mib={:.3}",
        median.peak_additional_bytes as f64 / (1024.0 * 1024.0)
    );
    println!(
        "retained_result_mib={:.3}",
        median.retained_result_bytes as f64 / (1024.0 * 1024.0)
    );
}

fn fixture() -> (
    RevisionGraphSnapshot,
    RevisionAnalysisViews,
    RevisionRequirementSidecar,
) {
    let generation = GraphGeneration(91);
    let fact_id = FactId::from("fact:ripple-root");
    let mut constraints = Vec::with_capacity(EDGES);
    constraints.push(soft_edge(0, &fact_id.0, "node:00000"));
    for node in 1..NODES {
        let source = format_compact!("node:{:05}", (node - 1) / 4);
        let target = format_compact!("node:{node:05}");
        constraints.push(soft_edge(node * 2 - 1, &source, &target));
        constraints.push(soft_edge(node * 2, &source, &target));
    }
    assert_eq!(constraints.len(), EDGES);
    let revision_edges = constraints
        .iter()
        .map(|constraint| RevisionEdgeRecord {
            edge_id: constraint.constraint_id.clone(),
            dependency_fact_ids: vec![fact_id.clone()],
            dependency_state_refs: Vec::new(),
        })
        .collect();
    let base = RevisionGraphSnapshot::new(
        generation,
        vec![RevisionFactRecord {
            fact_id,
            value: FactValue::Boolean(true),
            interval: StoryInterval {
                valid_from: StoryTime(0),
                valid_to_exclusive: None,
            },
        }],
        Vec::new(),
        revision_edges,
        vec![NamedSidecarDigest {
            sidecar_id: "ripple-perf".into(),
            digest: GraphTruthDigest([91; 32]),
        }],
    )
    .expect("benchmark base graph");
    let views = RevisionAnalysisViews::project(
        generation,
        constraints,
        InferenceProjectionInput::default(),
    )
    .expect("benchmark constraint graph");
    let requirements = RevisionRequirementSidecar {
        schema_version: REVISION_REQUIREMENT_SIDECAR_SCHEMA.into(),
        generation,
        requirements: Vec::new(),
    };
    (base, views, requirements)
}

fn soft_edge(index: usize, source: &str, target: &str) -> ConstraintSeed {
    ConstraintSeed {
        constraint_id: format_compact!("soft:{index:06}"),
        source_id: source.into(),
        dependent_id: target.into(),
        kind: ConstraintKind::CausalSupport,
        valid_interval: StoryInterval {
            valid_from: StoryTime(1),
            valid_to_exclusive: Some(StoryTime(2)),
        },
        evidence: vec![EvidenceRef::anchored("evidence:ripple-root")],
        confidence_millis: 900,
    }
}

fn record_allocation(size: usize) {
    ALLOCATION_CALLS.fetch_add(1, Ordering::Relaxed);
    increase_current(size);
}

fn increase_current(size: usize) {
    let current = CURRENT_BYTES.fetch_add(size, Ordering::Relaxed) + size;
    PEAK_BYTES.fetch_max(current, Ordering::Relaxed);
}

fn format_samples(samples: &[Sample]) -> String {
    samples
        .iter()
        .map(|sample| format!("{:.3}", sample.elapsed.as_secs_f64() * 1_000.0))
        .collect::<Vec<_>>()
        .join(",")
}
