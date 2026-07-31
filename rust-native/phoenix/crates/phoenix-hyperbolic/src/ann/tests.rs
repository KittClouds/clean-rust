use super::archive::{validate_frozen, ArchiveLimits, HEADER_BYTES};
use super::*;
use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};

fn vector(id: u64, dimension: usize) -> Vec<f32> {
    (0..dimension)
        .map(|axis| {
            let mixed = id
                .wrapping_mul(0x9e37_79b9)
                .wrapping_add(axis as u64 * 0x85eb_ca6b);
            ((mixed >> 8) as u32 % 10_000) as f32 / 100_000.0 - 0.05
        })
        .collect()
}

fn build(rows: u64, dimension: usize) -> FrozenHnsw {
    let metric = PoincareMetric { curvature: 1.0 };
    let mut builder =
        HyperbolicHnswBuilder::try_new(dimension, metric, HnswBuildOptions::default())
            .expect("valid test configuration");
    for id in 1..=rows {
        builder
            .insert_with_id(
                StableVectorId::new(id * 10).expect("nonzero stable ID"),
                vector(id, dimension),
                NodeMetadata {
                    tag_mask: 1 << (id % 4),
                },
            )
            .expect("valid test row");
    }
    builder.freeze()
}

#[test]
fn stable_ids_filters_tombstones_and_reused_scratch_work_together() {
    let metric = PoincareMetric { curvature: 1.0 };
    let mut builder =
        HyperbolicHnswBuilder::try_new(8, metric, HnswBuildOptions::default()).unwrap();
    for id in 1..=128 {
        builder
            .insert_with_id(
                StableVectorId::new(id * 13).unwrap(),
                vector(id, 8),
                NodeMetadata {
                    tag_mask: 1 << (id % 3),
                },
            )
            .unwrap();
    }
    assert!(builder.delete(StableVectorId::new(13).unwrap()));
    let frozen = builder.freeze();
    let mut scratch = SearchScratch::new();
    let filter = TagFilter {
        require_any: 1 << 2,
        exclude_any: 0,
    };
    let first = frozen
        .search_with_scratch(
            &metric,
            &vector(2, 8),
            SearchParams {
                k: 8,
                ef_search: 64,
                filter_mode: FilterMode::Strict,
            },
            &filter,
            &mut scratch,
        )
        .unwrap()
        .to_vec();
    assert!(!first.is_empty());
    assert!(first.iter().all(|hit| hit.id.get() != 13));
    for query_id in 3..100 {
        let _ = frozen
            .search_with_scratch(
                &metric,
                &vector(query_id, 8),
                SearchParams::new(8, 64),
                &NoFilter,
                &mut scratch,
            )
            .unwrap();
    }
    let capacities = scratch.allocation_capacities();
    for query_id in 3..100 {
        let _ = frozen
            .search_with_scratch(
                &metric,
                &vector(query_id, 8),
                SearchParams::new(8, 64),
                &NoFilter,
                &mut scratch,
            )
            .unwrap();
    }
    assert_eq!(scratch.allocation_capacities(), capacities);
}

#[test]
fn deterministic_batch_order_produces_the_same_archive_hash() {
    let metric = PoincareMetric { curvature: 0.5 };
    let make = |reverse: bool| {
        let mut rows = (1..=96)
            .map(|id| {
                (
                    StableVectorId::new(id * 17).unwrap(),
                    vector(id, 12),
                    NodeMetadata::default(),
                )
            })
            .collect::<Vec<_>>();
        if reverse {
            rows.reverse();
        }
        let mut builder =
            HyperbolicHnswBuilder::try_new(12, metric, HnswBuildOptions::default()).unwrap();
        builder.insert_batch_deterministic(rows).unwrap();
        builder.freeze()
    };
    let left = make(false);
    let right = make(true);
    let directory = tempfile::tempdir().unwrap();
    let left_receipt = left.write_new(directory.path().join("left.pha")).unwrap();
    let right_receipt = right.write_new(directory.path().join("right.pha")).unwrap();
    assert_eq!(left_receipt.root_hash, right_receipt.root_hash);
    assert_eq!(
        std::fs::read(directory.path().join("left.pha")).unwrap(),
        std::fs::read(directory.path().join("right.pha")).unwrap()
    );
}

#[test]
fn deterministic_recall_floor_against_exact_search() {
    let frozen = build(1_024, 16);
    let metric = PoincareMetric { curvature: 1.0 };
    let mut scratch = SearchScratch::new();
    let queries = [3_u64, 41, 97, 181, 257, 389, 521, 683, 809, 997];
    let mut recovered = 0_usize;
    let mut expected = 0_usize;

    for query_id in queries {
        let query = vector(query_id, 16);
        let mut exact = (0..frozen.len() as u32)
            .map(|raw_id| {
                let dense_id = DenseVectorId(raw_id);
                (
                    metric.eval(&query, frozen.vector(dense_id).unwrap()),
                    frozen.stable_id(dense_id).unwrap(),
                )
            })
            .collect::<Vec<_>>();
        exact.sort_unstable_by(|left, right| {
            left.0
                .total_cmp(&right.0)
                .then_with(|| left.1.cmp(&right.1))
        });
        let exact_ids = exact
            .iter()
            .take(10)
            .map(|(_, stable_id)| *stable_id)
            .collect::<hashbrown::HashSet<_>>();
        let hits = frozen
            .search_with_scratch(
                &metric,
                &query,
                SearchParams::new(10, 128),
                &NoFilter,
                &mut scratch,
            )
            .unwrap();
        recovered += hits
            .iter()
            .filter(|hit| exact_ids.contains(&hit.id))
            .count();
        expected += exact_ids.len();
    }

    assert!(
        recovered * 100 >= expected * 90,
        "recall@10 fell below 90%: recovered {recovered} of {expected}"
    );
}

#[test]
fn verified_mmap_roundtrip_has_no_legacy_fallback() {
    let frozen = build(80, 10);
    let metric = PoincareMetric { curvature: 1.0 };
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("verified.pha");
    let receipt = frozen.write_new(&path).unwrap();
    let index = HyperbolicDiskHnsw::open(&path, metric).unwrap();
    assert_eq!(index.format(), ArchiveFormat::VerifiedV2);
    assert_eq!(
        index.archive_receipt().unwrap().root_hash,
        receipt.root_hash
    );
    let source = index.diskann_source().unwrap();
    assert_eq!(source.dimension(), frozen.dimension());
    assert_eq!(source.len(), frozen.len());
    assert_eq!(
        source.vectors().as_ptr(),
        index.vector(DenseVectorId(0)).unwrap().as_ptr()
    );
    assert_eq!(
        source.stable_id(DenseVectorId(0)),
        frozen.stable_id(DenseVectorId(0))
    );
    assert_eq!(index.len(), 80);
    assert_eq!(index.dimension(), 10);
    assert_eq!(
        index.stable_id(DenseVectorId(0)).unwrap(),
        StableVectorId::new(10).unwrap()
    );
    assert_eq!(index.vector(DenseVectorId(0)).unwrap(), vector(1, 10));
    let hits = index.search(&vector(42, 10), 5, 32);
    assert_eq!(hits[0].id, 41);
}

#[test]
fn metric_mismatch_and_corrupt_pages_fail_closed() {
    let frozen = build(32, 6);
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("corrupt.pha");
    frozen.write_new(&path).unwrap();
    let mismatch =
        HyperbolicDiskHnsw::open(&path, PoincareMetric { curvature: 0.125 }).unwrap_err();
    assert!(matches!(
        mismatch,
        HyperbolicDiskError::MetricMismatch { .. }
    ));

    let mut file = OpenOptions::new().write(true).open(&path).unwrap();
    file.seek(SeekFrom::Start(HEADER_BYTES as u64 + 16))
        .unwrap();
    file.write_all(&[0xA5]).unwrap();
    file.sync_all().unwrap();
    let corrupt = HyperbolicDiskHnsw::open(&path, PoincareMetric { curvature: 1.0 }).unwrap_err();
    assert!(matches!(
        corrupt,
        HyperbolicDiskError::CorruptSection { .. }
    ));
}

#[test]
fn legacy_format_requires_the_named_compatibility_entrypoint() {
    let frozen = build(24, 4);
    let packed = PackedHnswGraph::from_frozen(&frozen);
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("legacy.bin");
    packed.write_to_file(path.to_str().unwrap()).unwrap();
    assert!(matches!(
        HyperbolicDiskHnsw::open(&path, PoincareMetric { curvature: 1.0 }),
        Err(HyperbolicDiskError::UnsupportedArchive)
    ));
    let legacy = HyperbolicDiskHnsw::open_legacy(&path, PoincareMetric { curvature: 1.0 }).unwrap();
    assert_eq!(legacy.format(), ArchiveFormat::QuarantinedLegacyV1);
    assert_eq!(legacy.len(), frozen.len());
    assert!(matches!(
        legacy.diskann_source(),
        Err(HyperbolicDiskError::UnsupportedArchive)
    ));
}

#[test]
fn malformed_topology_and_oversized_limits_are_rejected() {
    let mut frozen = build(16, 4);
    frozen.base_neighbors[0] = 0;
    assert!(matches!(
        validate_frozen(&frozen, ArchiveLimits::default()),
        Err(HyperbolicDiskError::InvalidTopology(_))
    ));

    let frozen = build(16, 4);
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("limits.pha");
    frozen.write_new(&path).unwrap();
    let error = HyperbolicDiskHnsw::open_with_limits(
        &path,
        PoincareMetric { curvature: 1.0 },
        ArchiveLimits {
            maximum_bytes: 1024,
            ..ArchiveLimits::default()
        },
    )
    .unwrap_err();
    assert!(matches!(
        error,
        HyperbolicDiskError::OversizedArchive { .. }
    ));
}

#[test]
fn archive_truthfully_reports_diskann_readiness_gap() {
    let readiness = build(4, 3).diskann_readiness();
    assert!(readiness.base_graph_csr);
    assert!(readiness.page_aligned_sections);
    assert!(readiness.full_precision_vectors);
    assert!(!readiness.vamana_built);
    assert!(!readiness.pq_codes);
    assert!(!readiness.asynchronous_beam_io);
}

#[test]
fn deleting_the_entry_reselects_a_live_navigation_root() {
    let metric = PoincareMetric { curvature: 1.0 };
    let mut builder =
        HyperbolicHnswBuilder::try_new(6, metric, HnswBuildOptions::default()).unwrap();
    for id in 1..=64 {
        builder
            .insert_with_id(
                StableVectorId::new(id).unwrap(),
                vector(id, 6),
                NodeMetadata::default(),
            )
            .unwrap();
    }
    let old_entry = builder.entry_point().unwrap();
    let old_stable = builder.stable_id(old_entry).unwrap();
    assert!(builder.delete(old_stable));
    assert_ne!(builder.entry_point(), Some(old_entry));
    let frozen = builder.freeze();
    validate_frozen(&frozen, ArchiveLimits::default()).unwrap();
    let mut scratch = SearchScratch::new();
    let hits = frozen
        .search_with_scratch(
            &metric,
            &vector(17, 6),
            SearchParams::new(5, 32),
            &NoFilter,
            &mut scratch,
        )
        .unwrap();
    assert!(hits.iter().all(|hit| hit.id != old_stable));
}
