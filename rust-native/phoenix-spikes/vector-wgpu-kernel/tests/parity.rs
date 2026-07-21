use vector_wgpu_kernel::{
    DispatchPolicy, GpuVectorRuntime, RawVectorInput, TopKRecord, VectorCorpusInput,
    VectorRerankBatch, cpu_exact_top_k, normalize_rows, quantize_symmetric_i8,
};

#[test]
fn gpu_normalization_and_quantization_match_cpu_oracles() {
    let rows = 37;
    let dimensions = 131;
    let raw = (0..rows * dimensions)
        .map(|index| ((index * 67 + 13) % 997) as f32 / 91.0 - 5.0)
        .collect::<Vec<_>>();
    let mut expected_normalized = raw.clone();
    normalize_rows(&mut expected_normalized, rows, dimensions).unwrap();
    let expected_quantized = quantize_symmetric_i8(&expected_normalized, rows, dimensions).unwrap();
    let runtime = GpuVectorRuntime::request(DispatchPolicy::default()).unwrap();
    let first = runtime
        .normalize_quantize(RawVectorInput {
            values: &raw,
            rows,
            dimensions,
        })
        .unwrap();
    let second = runtime
        .normalize_quantize(RawVectorInput {
            values: &raw,
            rows,
            dimensions,
        })
        .unwrap();

    assert_eq!(first.normalized, second.normalized);
    assert_eq!(first.quantized, second.quantized);
    assert_eq!(first.normalized.len(), expected_normalized.len());
    for (&actual, &expected) in first.normalized.iter().zip(&expected_normalized) {
        assert!((actual - expected).abs() <= 2.0e-6);
    }
    for (&actual, &expected) in first
        .quantized
        .values
        .iter()
        .zip(&expected_quantized.values)
    {
        assert!((i16::from(actual) - i16::from(expected)).abs() <= 1);
    }
    for (&actual, &expected) in first
        .quantized
        .scales
        .iter()
        .zip(&expected_quantized.scales)
    {
        assert!((actual - expected).abs() <= 2.0e-6);
    }
}

#[test]
fn gpu_multi_query_rerank_matches_cpu_oracle_and_repeats() {
    let fixture = fixture(257, 96, 33, 79, 12);
    let runtime = GpuVectorRuntime::request(DispatchPolicy {
        minimum_queries: 1,
        minimum_candidate_pairs: 1,
        minimum_scalar_fma_ops: 1,
        ..DispatchPolicy::default()
    })
    .expect("request GPU vector runtime");
    let resident = runtime.upload(fixture.corpus()).expect("upload corpus");
    let expected = cpu_exact_top_k(fixture.corpus(), fixture.batch()).unwrap();
    let first = resident.rerank(fixture.batch()).expect("first rerank");
    let second = resident.rerank(fixture.batch()).expect("repeat rerank");

    assert_eq!(first.top_k.offsets, expected.offsets);
    assert_eq!(first.top_k.offsets, second.top_k.offsets);
    assert_eq!(first.top_k.records, second.top_k.records);
    assert_records_close(&first.top_k.records, &expected.records);
    assert_eq!(first.receipt.batch.pairs, 33 * 79);
    assert!(first.receipt.returned_records <= 33 * 12);
    assert!(first.receipt.batch.readback_bytes < u64::from(33_u32 * 79) * 4);
}

#[test]
fn exact_ties_follow_lexical_rank_then_identity() {
    let mut values = vec![
        1.0, 0.0, 0.0, 0.0, // 0
        1.0, 0.0, 0.0, 0.0, // 1
        1.0, 0.0, 0.0, 0.0, // 2
        1.0, 0.0, 0.0, 0.0, // 3
    ];
    normalize_rows(&mut values, 4, 4).unwrap();
    let ranks = vec![3, 2, 0, 0];
    let query = vec![1.0, 0.0, 0.0, 0.0];
    let candidates = vec![3, 1, 2];
    let offsets = vec![0, 3];
    let corpus = VectorCorpusInput {
        values: &values,
        lexical_ranks: &ranks,
        rows: 4,
        dimensions: 4,
    };
    let batch = VectorRerankBatch {
        queries: &query,
        query_count: 1,
        candidate_offsets: &offsets,
        candidate_ids: &candidates,
        top_k: 3,
        minimum_similarity: -1.0,
    };
    let runtime = GpuVectorRuntime::request(DispatchPolicy::default()).unwrap();
    let resident = runtime.upload(corpus).unwrap();
    let actual = resident.rerank(batch).unwrap();
    assert_eq!(
        actual
            .top_k
            .query(0)
            .iter()
            .map(|record| record.candidate_id)
            .collect::<Vec<_>>(),
        vec![2, 3, 1]
    );
}

fn assert_records_close(actual: &[TopKRecord], expected: &[TopKRecord]) {
    assert_eq!(actual.len(), expected.len());
    for (actual, expected) in actual.iter().zip(expected) {
        assert_eq!(actual.candidate_id, expected.candidate_id);
        assert!(
            (actual.score - expected.score).abs() <= 2.0e-5,
            "score drift for {}: {} != {}",
            actual.candidate_id,
            actual.score,
            expected.score
        );
    }
}

struct Fixture {
    values: Vec<f32>,
    ranks: Vec<u32>,
    queries: Vec<f32>,
    offsets: Vec<u32>,
    candidates: Vec<u32>,
    rows: u32,
    dimensions: u32,
    query_count: u32,
    top_k: u32,
}

impl Fixture {
    fn corpus(&self) -> VectorCorpusInput<'_> {
        VectorCorpusInput {
            values: &self.values,
            lexical_ranks: &self.ranks,
            rows: self.rows,
            dimensions: self.dimensions,
        }
    }

    fn batch(&self) -> VectorRerankBatch<'_> {
        VectorRerankBatch {
            queries: &self.queries,
            query_count: self.query_count,
            candidate_offsets: &self.offsets,
            candidate_ids: &self.candidates,
            top_k: self.top_k,
            minimum_similarity: -0.25,
        }
    }
}

fn fixture(
    rows: u32,
    dimensions: u32,
    query_count: u32,
    candidates_per_query: u32,
    top_k: u32,
) -> Fixture {
    let mut values = (0..rows * dimensions)
        .map(|index| ((index * 73 + 29) % 1021) as f32 / 510.0 - 1.0)
        .collect::<Vec<_>>();
    normalize_rows(&mut values, rows, dimensions).unwrap();
    let mut queries = (0..query_count * dimensions)
        .map(|index| ((index * 43 + 17) % 997) as f32 / 498.0 - 1.0)
        .collect::<Vec<_>>();
    normalize_rows(&mut queries, query_count, dimensions).unwrap();
    let ranks = (0..rows).map(|row| (row * 193) % rows).collect();
    let mut offsets = Vec::with_capacity(query_count as usize + 1);
    let mut candidates = Vec::with_capacity((query_count * candidates_per_query) as usize);
    offsets.push(0);
    for query in 0..query_count {
        for slot in 0..candidates_per_query {
            candidates.push((query * 17 + slot * 31) % rows);
        }
        offsets.push(candidates.len() as u32);
    }
    Fixture {
        values,
        ranks,
        queries,
        offsets,
        candidates,
        rows,
        dimensions,
        query_count,
        top_k,
    }
}
