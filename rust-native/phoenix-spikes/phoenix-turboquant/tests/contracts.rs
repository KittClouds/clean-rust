use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};

use phoenix_turboquant::{
    encode_vectors, exact_rerank_candidates_into, exact_search, write_quantized_artifact_new,
    ArtifactAuthority, BatchSearchScratch, BlockLocalTopKConfig, ExactSearchScratch,
    SearchExecution, SearchKernel, SearchScratch, TurboQuantError, VerifiedQuantizedIndex,
};
use rayon::ThreadPoolBuilder;
use tempfile::tempdir;

const DIMENSION: usize = 768;

fn normalized_vectors(rows: usize) -> Vec<f32> {
    let mut vectors = Vec::with_capacity(rows * DIMENSION);
    for row in 0..rows {
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

#[test]
fn encoded_output_is_thread_count_deterministic() {
    let vectors = normalized_vectors(33);
    let encode = |threads| {
        ThreadPoolBuilder::new()
            .num_threads(threads)
            .build()
            .unwrap()
            .install(|| encode_vectors(&vectors, 33, DIMENSION, 4).unwrap())
    };
    let serial = encode(1);
    let parallel = encode(4);
    assert_eq!(serial.codes, parallel.codes);
    assert_eq!(serial.scales, parallel.scales);
    assert_eq!(serial.codebook.hash(), parallel.codebook.hash());
}

#[test]
fn mmap_round_trip_preserves_contract_and_reuses_search_memory() {
    let rows = 128;
    let vectors = normalized_vectors(rows);
    let ids: Vec<u64> = (10_000..10_000 + rows as u64).collect();
    let authority = ArtifactAuthority::synthetic(b"mmap-round-trip-v1");
    let directory = tempdir().unwrap();
    let path = directory.path().join("round-trip.phxq1");
    let written =
        write_quantized_artifact_new(&path, authority, &ids, &vectors, DIMENSION, 4).unwrap();
    assert_eq!(written.len(), rows);
    assert_eq!(written.subject_ids().unwrap(), ids);
    drop(written);

    let index = VerifiedQuantizedIndex::open_expected(&path, Some(authority)).unwrap();
    let query = &vectors[37 * DIMENSION..38 * DIMENSION];
    let exact = exact_search(&vectors, &ids, DIMENSION, query, 16).unwrap();
    let quantized = index.search(query, 16, SearchKernel::Auto).unwrap();
    assert_eq!(exact[0].subject_id, ids[37]);
    assert!(quantized.iter().any(|hit| hit.subject_id == ids[37]));

    let mut scratch = SearchScratch::new(DIMENSION, 16);
    let mut output = Vec::with_capacity(16);
    index
        .search_into(query, 16, SearchKernel::Auto, &mut scratch, &mut output)
        .unwrap();
    let capacities = (scratch.capacities(), output.capacity());
    index
        .search_into(query, 16, SearchKernel::Auto, &mut scratch, &mut output)
        .unwrap();
    assert_eq!(capacities, (scratch.capacities(), output.capacity()));
}

#[test]
fn scalar_and_avx2_rankings_agree() {
    if !cfg!(target_arch = "x86_64") || !std::arch::is_x86_feature_detected!("avx2") {
        return;
    }
    let rows = 65;
    let vectors = normalized_vectors(rows);
    let ids: Vec<u64> = (1..=rows as u64).collect();
    let directory = tempdir().unwrap();
    let path = directory.path().join("kernels.phxq1");
    let index = write_quantized_artifact_new(
        &path,
        ArtifactAuthority::synthetic(b"kernel-parity-v1"),
        &ids,
        &vectors,
        DIMENSION,
        4,
    )
    .unwrap();
    let query = &vectors[11 * DIMENSION..12 * DIMENSION];
    let scalar = index.search(query, 32, SearchKernel::Scalar).unwrap();
    let avx2 = index.search(query, 32, SearchKernel::Avx2).unwrap();
    assert_eq!(scalar.len(), avx2.len());
    for (left, right) in scalar.iter().zip(&avx2) {
        assert_eq!(left.subject_id, right.subject_id);
        assert!((left.score - right.score).abs() <= 2.0e-5);
    }
}

#[test]
fn corruption_and_authority_mismatch_fail_closed() {
    let vectors = normalized_vectors(9);
    let ids: Vec<u64> = (1..=9).collect();
    let authority = ArtifactAuthority::synthetic(b"corruption-v1");
    let directory = tempdir().unwrap();
    let path = directory.path().join("corrupt.phxq1");
    let index =
        write_quantized_artifact_new(&path, authority, &ids, &vectors, DIMENSION, 2).unwrap();
    let codes_offset = index.header().codes_offset;
    drop(index);

    let mismatch = ArtifactAuthority::synthetic(b"different-authority");
    assert!(matches!(
        VerifiedQuantizedIndex::open_expected(&path, Some(mismatch)),
        Err(TurboQuantError::AuthorityMismatch(_))
    ));

    let mut file = OpenOptions::new().write(true).open(&path).unwrap();
    file.seek(SeekFrom::Start(codes_offset + 3)).unwrap();
    file.write_all(&[0xff]).unwrap();
    file.sync_all().unwrap();
    assert!(matches!(
        VerifiedQuantizedIndex::open(&path),
        Err(TurboQuantError::HashMismatch("codes"))
    ));
}

#[test]
fn rayon_and_serial_top64_are_identical_after_preparation() {
    let rows = 4_096;
    let vectors = normalized_vectors(rows);
    let ids: Vec<u64> = (1..=rows as u64).collect();
    let directory = tempdir().unwrap();
    let pool = ThreadPoolBuilder::new().num_threads(4).build().unwrap();
    for bits in [2, 4] {
        let path = directory.path().join(format!("parallel-{bits}.phxq1"));
        let index = write_quantized_artifact_new(
            &path,
            ArtifactAuthority::synthetic(b"parallel-parity-v1"),
            &ids,
            &vectors,
            DIMENSION,
            bits,
        )
        .unwrap();
        let expected = if bits == 2 {
            SearchExecution::Serial
        } else {
            SearchExecution::Rayon
        };
        assert_eq!(pool.install(|| index.recommended_execution()), expected);
        let query = &vectors[701 * DIMENSION..702 * DIMENSION];
        let mut serial_scratch = SearchScratch::new(DIMENSION, 64);
        let mut rayon_scratch = SearchScratch::new(DIMENSION, 64);
        let mut serial = Vec::with_capacity(64);
        let mut parallel = Vec::with_capacity(64);
        index.prepare_query(query, &mut serial_scratch).unwrap();
        index.prepare_query(query, &mut rayon_scratch).unwrap();
        index
            .search_prepared_with_execution_into(
                64,
                SearchKernel::Auto,
                SearchExecution::Serial,
                &mut serial_scratch,
                &mut serial,
            )
            .unwrap();
        pool.install(|| {
            index
                .search_prepared_with_execution_into(
                    64,
                    SearchKernel::Auto,
                    SearchExecution::Rayon,
                    &mut rayon_scratch,
                    &mut parallel,
                )
                .unwrap();
        });
        assert_eq!(serial, parallel, "{bits}-bit parallel ranking diverged");
    }
}

#[test]
fn packed_block_batch_matches_independent_queries() {
    let rows = 257;
    let vectors = normalized_vectors(rows);
    let ids: Vec<u64> = (1..=rows as u64).collect();
    let directory = tempdir().unwrap();
    let pool = ThreadPoolBuilder::new().num_threads(4).build().unwrap();
    let queries = [3, 17, 61, 89, 144, 201, 233, 256]
        .map(|row| vectors[row * DIMENSION..(row + 1) * DIMENSION].to_vec());
    for bits in [2, 4] {
        let path = directory.path().join(format!("batch-{bits}.phxq1"));
        let index = write_quantized_artifact_new(
            &path,
            ArtifactAuthority::synthetic(b"batch-parity-v1"),
            &ids,
            &vectors,
            DIMENSION,
            bits,
        )
        .unwrap();
        let expected = queries
            .iter()
            .map(|query| index.search(query, 64, SearchKernel::Avx2).unwrap())
            .collect::<Vec<_>>();
        for batch_size in [2, 4, 8] {
            let mut scratch = BatchSearchScratch::new(DIMENSION, batch_size, 64);
            let mut outputs = (0..batch_size)
                .map(|_| Vec::with_capacity(64))
                .collect::<Vec<_>>();
            pool.install(|| {
                index
                    .search_batch_parallel_into(
                        &queries[..batch_size],
                        64,
                        SearchKernel::Avx2,
                        &mut scratch,
                        &mut outputs,
                    )
                    .unwrap();
            });
            assert_eq!(outputs, expected[..batch_size], "{bits}-bit batch parity");
        }
    }
}

#[test]
fn block_local_top_k_preserves_candidates_and_exact_rerank() {
    let rows = 257;
    let vectors = normalized_vectors(rows);
    let ids: Vec<u64> = (1..=rows as u64).collect();
    let directory = tempdir().unwrap();
    let pool = ThreadPoolBuilder::new().num_threads(4).build().unwrap();
    let queries = [3, 17, 61, 89, 144, 201, 233, 256]
        .map(|row| vectors[row * DIMENSION..(row + 1) * DIMENSION].to_vec());
    let configs = [
        BlockLocalTopKConfig {
            block_rows: 256,
            local_k: 64,
        },
        BlockLocalTopKConfig {
            block_rows: 512,
            local_k: 96,
        },
        BlockLocalTopKConfig {
            block_rows: 1_024,
            local_k: 128,
        },
    ];
    for bits in [2, 4] {
        let path = directory.path().join(format!("block-local-{bits}.phxq1"));
        let index = write_quantized_artifact_new(
            &path,
            ArtifactAuthority::synthetic(b"block-local-parity-v1"),
            &ids,
            &vectors,
            DIMENSION,
            bits,
        )
        .unwrap();
        let mut batch_scratch = BatchSearchScratch::new(DIMENSION, queries.len(), 64);
        let mut expected = (0..queries.len())
            .map(|_| Vec::with_capacity(64))
            .collect::<Vec<_>>();
        pool.install(|| {
            index
                .search_batch_parallel_into(
                    &queries,
                    64,
                    SearchKernel::Avx2,
                    &mut batch_scratch,
                    &mut expected,
                )
                .unwrap();
        });
        for config in configs {
            for kernel in [SearchKernel::Scalar, SearchKernel::Avx2] {
                let mut scratch = BatchSearchScratch::new(DIMENSION, queries.len(), 64);
                let mut actual = (0..queries.len())
                    .map(|_| Vec::with_capacity(64))
                    .collect::<Vec<_>>();
                pool.install(|| {
                    index
                        .search_batch_block_local_into(
                            &queries,
                            64,
                            kernel,
                            config,
                            &mut scratch,
                            &mut actual,
                        )
                        .unwrap();
                });
                assert_eq!(actual, expected, "{bits}-bit {kernel:?} {config:?}");

                let mut expected_rerank_scratch = ExactSearchScratch::new(10);
                let mut actual_rerank_scratch = ExactSearchScratch::new(10);
                let mut expected_rerank = Vec::with_capacity(10);
                let mut actual_rerank = Vec::with_capacity(10);
                exact_rerank_candidates_into(
                    &vectors,
                    &ids,
                    DIMENSION,
                    &queries[0],
                    &expected[0],
                    10,
                    &mut expected_rerank_scratch,
                    &mut expected_rerank,
                )
                .unwrap();
                exact_rerank_candidates_into(
                    &vectors,
                    &ids,
                    DIMENSION,
                    &queries[0],
                    &actual[0],
                    10,
                    &mut actual_rerank_scratch,
                    &mut actual_rerank,
                )
                .unwrap();
                assert_eq!(actual_rerank, expected_rerank);
            }
        }
    }
}

#[test]
fn block_local_ties_follow_canonical_row_order() {
    let rows = 129;
    let one = normalized_vectors(1);
    let vectors = one.repeat(rows);
    let ids: Vec<u64> = (10_000..10_000 + rows as u64).collect();
    let directory = tempdir().unwrap();
    let pool = ThreadPoolBuilder::new().num_threads(4).build().unwrap();
    for bits in [2, 4] {
        let path = directory.path().join(format!("ties-{bits}.phxq1"));
        let index = write_quantized_artifact_new(
            &path,
            ArtifactAuthority::synthetic(b"block-local-ties-v1"),
            &ids,
            &vectors,
            DIMENSION,
            bits,
        )
        .unwrap();
        let queries = vec![one.clone()];
        let mut scratch = BatchSearchScratch::new(DIMENSION, 1, 64);
        let mut outputs = vec![Vec::with_capacity(64)];
        pool.install(|| {
            index
                .search_batch_block_local_into(
                    &queries,
                    64,
                    SearchKernel::Auto,
                    BlockLocalTopKConfig {
                        block_rows: 64,
                        local_k: 64,
                    },
                    &mut scratch,
                    &mut outputs,
                )
                .unwrap();
        });
        assert_eq!(
            outputs[0].iter().map(|hit| hit.row).collect::<Vec<_>>(),
            (0..64).collect::<Vec<_>>()
        );
    }
}

#[test]
fn invalid_batch_shapes_fail_closed() {
    let vectors = normalized_vectors(9);
    let ids: Vec<u64> = (1..=9).collect();
    let directory = tempdir().unwrap();
    let path = directory.path().join("batch-shape.phxq1");
    let index = write_quantized_artifact_new(
        &path,
        ArtifactAuthority::synthetic(b"batch-shape-v1"),
        &ids,
        &vectors,
        DIMENSION,
        2,
    )
    .unwrap();
    let mut scratch = BatchSearchScratch::new(DIMENSION, 8, 8);
    let mut no_outputs = Vec::new();
    assert!(matches!(
        index.search_batch_parallel_into::<Vec<f32>>(
            &[],
            8,
            SearchKernel::Auto,
            &mut scratch,
            &mut no_outputs,
        ),
        Err(TurboQuantError::InvalidBatchSize { actual: 0, .. })
    ));
    let queries = vec![vectors[..DIMENSION].to_vec()];
    assert!(matches!(
        index.search_batch_parallel_into(
            &queries,
            8,
            SearchKernel::Auto,
            &mut scratch,
            &mut no_outputs,
        ),
        Err(TurboQuantError::BatchOutputLength {
            actual: 0,
            expected: 1
        })
    ));
    let oversized = (0..9).map(|_| queries[0].clone()).collect::<Vec<_>>();
    let mut oversized_outputs = (0..9).map(|_| Vec::with_capacity(8)).collect::<Vec<_>>();
    assert!(matches!(
        index.search_batch_parallel_into(
            &oversized,
            8,
            SearchKernel::Auto,
            &mut scratch,
            &mut oversized_outputs,
        ),
        Err(TurboQuantError::InvalidBatchSize {
            actual: 9,
            maximum: 8
        })
    ));
}

#[test]
fn prepared_query_is_bound_to_its_quantizer_contract() {
    let vectors = normalized_vectors(16);
    let ids: Vec<u64> = (1..=16).collect();
    let directory = tempdir().unwrap();
    let two_path = directory.path().join("two.phxq1");
    let four_path = directory.path().join("four.phxq1");
    let authority = ArtifactAuthority::synthetic(b"prepared-contract-v1");
    let two =
        write_quantized_artifact_new(&two_path, authority, &ids, &vectors, DIMENSION, 2).unwrap();
    let four =
        write_quantized_artifact_new(&four_path, authority, &ids, &vectors, DIMENSION, 4).unwrap();
    let mut scratch = SearchScratch::new(DIMENSION, 8);
    let mut output = Vec::with_capacity(8);
    two.prepare_query(&vectors[..DIMENSION], &mut scratch)
        .unwrap();
    assert!(matches!(
        four.search_prepared_into(8, SearchKernel::Auto, &mut scratch, &mut output),
        Err(TurboQuantError::PreparedContractMismatch)
    ));
}

#[test]
fn exact_rerank_recovers_exact_order_inside_candidate_set() {
    let rows = 128;
    let vectors = normalized_vectors(rows);
    let ids: Vec<u64> = (1..=rows as u64).collect();
    let directory = tempdir().unwrap();
    let path = directory.path().join("rerank.phxq1");
    let index = write_quantized_artifact_new(
        &path,
        ArtifactAuthority::synthetic(b"exact-rerank-v1"),
        &ids,
        &vectors,
        DIMENSION,
        2,
    )
    .unwrap();
    let query = &vectors[79 * DIMENSION..80 * DIMENSION];
    let exact = exact_search(&vectors, &ids, DIMENSION, query, 10).unwrap();
    let candidates = index.search(query, 64, SearchKernel::Auto).unwrap();
    let mut scratch = ExactSearchScratch::new(10);
    let mut reranked = Vec::with_capacity(10);
    exact_rerank_candidates_into(
        &vectors,
        &ids,
        DIMENSION,
        query,
        &candidates,
        10,
        &mut scratch,
        &mut reranked,
    )
    .unwrap();
    assert_eq!(
        exact.iter().map(|hit| hit.row).collect::<Vec<_>>(),
        reranked.iter().map(|hit| hit.row).collect::<Vec<_>>()
    );
}
