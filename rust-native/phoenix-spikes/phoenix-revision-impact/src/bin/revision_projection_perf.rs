use std::alloc::{GlobalAlloc, Layout, System};
use std::hint::black_box;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant};

use compact_str::format_compact;
use phoenix_revision_impact::{
    ConstraintSeed, EvidenceRef, GraphGeneration, InferenceAuthority, InferenceEdgeSeed,
    InferenceNodeSeed, InferenceProjectionInput, RevisionAnalysisViews,
};
use phoenix_types::{ConstraintKind, StoryInterval, StoryTime};

const NODES: usize = 50_000;
const CONSTRAINTS: usize = 100_000;
const RELATIONS: usize = 200_000;
const MEMBERSHIPS: usize = 50_000;
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
}

fn main() {
    let mut samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        let (constraints, inference) = fixture();
        let baseline_bytes = CURRENT_BYTES.load(Ordering::Relaxed);
        PEAK_BYTES.store(baseline_bytes, Ordering::Relaxed);
        let baseline_calls = ALLOCATION_CALLS.load(Ordering::Relaxed);
        let started = Instant::now();
        let views = RevisionAnalysisViews::project(GraphGeneration(73), constraints, inference)
            .expect("projection benchmark fixture");
        let elapsed = started.elapsed();
        assert_eq!(views.constraint_graph.atoms().len(), CONSTRAINTS);
        assert_eq!(
            views.inference_graph.edge_metadata().len(),
            RELATIONS + MEMBERSHIPS
        );
        black_box(&views);
        samples.push(Sample {
            elapsed,
            allocation_calls: ALLOCATION_CALLS
                .load(Ordering::Relaxed)
                .saturating_sub(baseline_calls),
            peak_additional_bytes: PEAK_BYTES
                .load(Ordering::Relaxed)
                .saturating_sub(baseline_bytes),
        });
    }
    samples.sort_unstable_by_key(|sample| sample.elapsed);
    let median = samples[SAMPLES / 2];
    let rows = CONSTRAINTS + RELATIONS + MEMBERSHIPS;
    println!(
        "nodes={NODES} constraints={CONSTRAINTS} relations={RELATIONS} memberships={MEMBERSHIPS}"
    );
    println!("samples_ms={}", format_samples(&samples));
    println!("median_ms={:.3}", median.elapsed.as_secs_f64() * 1_000.0);
    println!(
        "rows_per_second={:.0}",
        rows as f64 / median.elapsed.as_secs_f64()
    );
    println!("projection_allocation_calls={}", median.allocation_calls);
    println!(
        "projection_peak_additional_mib={:.3}",
        median.peak_additional_bytes as f64 / (1024.0 * 1024.0)
    );
}

fn record_allocation(size: usize) {
    ALLOCATION_CALLS.fetch_add(1, Ordering::Relaxed);
    increase_current(size);
}

fn increase_current(size: usize) {
    let current = CURRENT_BYTES.fetch_add(size, Ordering::Relaxed) + size;
    PEAK_BYTES.fetch_max(current, Ordering::Relaxed);
}

fn fixture() -> (Vec<ConstraintSeed>, InferenceProjectionInput) {
    let accepted_nodes = (0..NODES)
        .map(|index| InferenceNodeSeed {
            node_id: format_compact!("node:{index:05}"),
            embedding_text: format_compact!("benchmark node {index}"),
            node_type: match index % 5 {
                0 => "document",
                1 => "chunk",
                2 => "entity",
                3 => "event",
                _ => "episode",
            }
            .into(),
        })
        .collect();
    let relations = (0..RELATIONS)
        .map(|index| inference_edge("relation", index, (index * 17 + 3) % NODES))
        .collect();
    let memberships = (0..MEMBERSHIPS)
        .map(|index| inference_edge("membership", index, (index * 7 + 1) % NODES))
        .collect();
    let constraints = (0..CONSTRAINTS)
        .map(|index| ConstraintSeed {
            constraint_id: format_compact!("constraint:{index:05}"),
            source_id: format_compact!("fact:{:05}", index % (NODES / 2)),
            dependent_id: format_compact!("scene:{:05}", (index * 11) % (NODES / 2)),
            kind: match index % 4 {
                0 => ConstraintKind::RequiresKnowledge,
                1 => ConstraintKind::RequiresState,
                2 => ConstraintKind::RequiresTemporalOrder,
                _ => ConstraintKind::CausalSupport,
            },
            valid_interval: StoryInterval {
                valid_from: StoryTime(index as i64),
                valid_to_exclusive: Some(StoryTime(index as i64 + 1)),
            },
            evidence: vec![EvidenceRef::anchored(format_compact!(
                "evidence:{index:05}"
            ))],
            confidence_millis: 900,
        })
        .collect();
    (
        constraints,
        InferenceProjectionInput {
            accepted_nodes,
            relations,
            memberships,
        },
    )
}

fn inference_edge(prefix: &str, index: usize, target: usize) -> InferenceEdgeSeed {
    InferenceEdgeSeed {
        edge_id: format_compact!("{prefix}:{index:05}"),
        source_id: format_compact!("node:{:05}", index % NODES),
        target_id: format_compact!("node:{target:05}"),
        relation_type: format_compact!("relation_type:{}", index % 32),
        authority: InferenceAuthority::Asserted,
        evidence_ids: Vec::new(),
        confidence_millis: 900,
    }
}

fn format_samples(samples: &[Sample]) -> String {
    samples
        .iter()
        .map(|sample| format!("{:.3}", sample.elapsed.as_secs_f64() * 1_000.0))
        .collect::<Vec<_>>()
        .join(",")
}
