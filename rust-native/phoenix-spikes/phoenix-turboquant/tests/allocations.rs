use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

use phoenix_turboquant::{
    write_quantized_artifact_new, ArtifactAuthority, BatchSearchScratch, BlockLocalTopKConfig,
    SearchExecution, SearchKernel, SearchScratch,
};
use tempfile::tempdir;

const DIMENSION: usize = 768;
const ROWS: usize = 4_096;

struct CountingAllocator;

static COUNTING: AtomicBool = AtomicBool::new(false);
static ALLOCATIONS: AtomicUsize = AtomicUsize::new(0);

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        record_allocation();
        System.alloc(layout)
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        record_allocation();
        System.alloc_zeroed(layout)
    }

    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        record_allocation();
        System.realloc(pointer, layout, new_size)
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        System.dealloc(pointer, layout)
    }
}

fn record_allocation() {
    if COUNTING.load(Ordering::Relaxed) {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
    }
}

#[test]
fn warmed_search_path_has_zero_heap_allocations() {
    let vectors = normalized_vectors();
    let ids: Vec<u64> = (1..=ROWS as u64).collect();
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(4)
        .build()
        .unwrap();
    for bits in [2, 4] {
        let directory = tempdir().unwrap();
        let path = directory.path().join(format!("allocation-{bits}.phxq1"));
        let index = write_quantized_artifact_new(
            &path,
            ArtifactAuthority::synthetic(b"allocation-gate-v1"),
            &ids,
            &vectors,
            DIMENSION,
            bits,
        )
        .unwrap();
        let query = &vectors[17 * DIMENSION..18 * DIMENSION];
        let mut scratch = SearchScratch::new(DIMENSION, 64);
        let mut output = Vec::with_capacity(64);
        index
            .search_into(query, 64, SearchKernel::Auto, &mut scratch, &mut output)
            .unwrap();

        ALLOCATIONS.store(0, Ordering::SeqCst);
        COUNTING.store(true, Ordering::SeqCst);
        index
            .search_into(query, 64, SearchKernel::Auto, &mut scratch, &mut output)
            .unwrap();
        COUNTING.store(false, Ordering::SeqCst);
        assert_eq!(
            ALLOCATIONS.load(Ordering::SeqCst),
            0,
            "{bits}-bit search allocated"
        );

        index.prepare_query(query, &mut scratch).unwrap();
        pool.install(|| {
            index
                .search_prepared_with_execution_into(
                    64,
                    SearchKernel::Auto,
                    SearchExecution::Rayon,
                    &mut scratch,
                    &mut output,
                )
                .unwrap();
        });
        ALLOCATIONS.store(0, Ordering::SeqCst);
        COUNTING.store(true, Ordering::SeqCst);
        pool.install(|| {
            index
                .search_prepared_with_execution_into(
                    64,
                    SearchKernel::Auto,
                    SearchExecution::Rayon,
                    &mut scratch,
                    &mut output,
                )
                .unwrap();
        });
        COUNTING.store(false, Ordering::SeqCst);
        assert_eq!(
            ALLOCATIONS.load(Ordering::SeqCst),
            0,
            "{bits}-bit Rayon search allocated"
        );

        let queries =
            [17, 29, 41, 53].map(|row| vectors[row * DIMENSION..(row + 1) * DIMENSION].to_vec());
        let mut batch_scratch = BatchSearchScratch::new(DIMENSION, queries.len(), 64);
        let mut batch_outputs = (0..queries.len())
            .map(|_| Vec::with_capacity(64))
            .collect::<Vec<_>>();
        pool.install(|| {
            index
                .search_batch_parallel_into(
                    &queries,
                    64,
                    SearchKernel::Auto,
                    &mut batch_scratch,
                    &mut batch_outputs,
                )
                .unwrap();
        });
        let capacities = (
            batch_scratch.capacities(),
            batch_outputs.iter().map(Vec::capacity).collect::<Vec<_>>(),
        );
        ALLOCATIONS.store(0, Ordering::SeqCst);
        COUNTING.store(true, Ordering::SeqCst);
        pool.install(|| {
            index
                .search_batch_parallel_into(
                    &queries,
                    64,
                    SearchKernel::Auto,
                    &mut batch_scratch,
                    &mut batch_outputs,
                )
                .unwrap();
        });
        COUNTING.store(false, Ordering::SeqCst);
        assert_eq!(
            ALLOCATIONS.load(Ordering::SeqCst),
            0,
            "{bits}-bit batch search allocated"
        );
        assert_eq!(
            capacities,
            (
                batch_scratch.capacities(),
                batch_outputs.iter().map(Vec::capacity).collect::<Vec<_>>()
            )
        );

        let config = BlockLocalTopKConfig {
            block_rows: 512,
            local_k: 64,
        };
        pool.install(|| {
            index
                .search_batch_block_local_into(
                    &queries,
                    64,
                    SearchKernel::Auto,
                    config,
                    &mut batch_scratch,
                    &mut batch_outputs,
                )
                .unwrap();
        });
        let capacities = batch_scratch.capacities();
        ALLOCATIONS.store(0, Ordering::SeqCst);
        COUNTING.store(true, Ordering::SeqCst);
        pool.install(|| {
            index
                .search_batch_block_local_into(
                    &queries,
                    64,
                    SearchKernel::Auto,
                    config,
                    &mut batch_scratch,
                    &mut batch_outputs,
                )
                .unwrap();
        });
        COUNTING.store(false, Ordering::SeqCst);
        assert_eq!(
            ALLOCATIONS.load(Ordering::SeqCst),
            0,
            "{bits}-bit block-local search allocated"
        );
        assert_eq!(capacities, batch_scratch.capacities());
    }
}

fn normalized_vectors() -> Vec<f32> {
    let mut vectors = Vec::with_capacity(ROWS * DIMENSION);
    for row in 0..ROWS {
        let start = vectors.len();
        let mut norm = 0.0_f32;
        for column in 0..DIMENSION {
            let value = ((((row + 1) * 131 + column * 17) % 997) as f32 / 498.5) - 1.0;
            norm += value * value;
            vectors.push(value);
        }
        let inverse = norm.sqrt().recip();
        for value in &mut vectors[start..] {
            *value *= inverse;
        }
    }
    vectors
}
