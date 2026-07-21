use vector_wgpu_kernel::{
    DispatchBackend, DispatchPolicy, MAX_CANDIDATES_PER_QUERY, VectorCorpusInput,
    VectorRerankBatch, normalize_rows,
};

#[test]
fn contract_rejects_unbounded_duplicate_and_nonresident_candidates() {
    let (values, ranks) = corpus_fixture(600, 8);
    let corpus = VectorCorpusInput {
        values: &values,
        lexical_ranks: &ranks,
        rows: 600,
        dimensions: 8,
    };
    let shape = corpus.validate().unwrap();
    let queries = values[..8].to_vec();
    let too_many = (0..=MAX_CANDIDATES_PER_QUERY).collect::<Vec<_>>();
    let error = VectorRerankBatch {
        queries: &queries,
        query_count: 1,
        candidate_offsets: &[0, MAX_CANDIDATES_PER_QUERY + 1],
        candidate_ids: &too_many,
        top_k: 8,
        minimum_similarity: -1.0,
    }
    .validate(shape)
    .unwrap_err();
    assert!(error.to_string().contains("bounded by 512"));

    let duplicate = VectorRerankBatch {
        queries: &queries,
        query_count: 1,
        candidate_offsets: &[0, 2],
        candidate_ids: &[7, 7],
        top_k: 2,
        minimum_similarity: -1.0,
    }
    .validate(shape)
    .unwrap_err();
    assert!(duplicate.to_string().contains("duplicate identities"));

    let outside = VectorRerankBatch {
        queries: &queries,
        query_count: 1,
        candidate_offsets: &[0, 1],
        candidate_ids: &[600],
        top_k: 1,
        minimum_similarity: -1.0,
    }
    .validate(shape)
    .unwrap_err();
    assert!(outside.to_string().contains("outside the resident corpus"));
}

#[test]
fn dispatch_policy_never_turns_a_small_query_into_gpu_all_pairs() {
    let (values, ranks) = corpus_fixture(256, 16);
    let corpus = VectorCorpusInput {
        values: &values,
        lexical_ranks: &ranks,
        rows: 256,
        dimensions: 16,
    }
    .validate()
    .unwrap();
    let queries = values[..16].to_vec();
    let batch = VectorRerankBatch {
        queries: &queries,
        query_count: 1,
        candidate_offsets: &[0, 4],
        candidate_ids: &[1, 7, 19, 31],
        top_k: 4,
        minimum_similarity: -1.0,
    }
    .validate(corpus)
    .unwrap();
    assert_eq!(batch.pairs, 4);
    assert_eq!(
        DispatchPolicy::default().select(batch, corpus.resident_bytes, true),
        DispatchBackend::Cpu
    );
}

fn corpus_fixture(rows: u32, dimensions: u32) -> (Vec<f32>, Vec<u32>) {
    let mut values = (0..rows * dimensions)
        .map(|index| ((index * 37 + 11) % 251) as f32 / 125.0 - 1.0)
        .collect::<Vec<_>>();
    normalize_rows(&mut values, rows, dimensions).unwrap();
    (values, (0..rows).rev().collect())
}
