use bm25_turbo::BM25Builder;
use phoenix_qps_experiment::{
    benchmark_corpus, judged_fixture, representative_fixture, CandidateSelection, DocumentInput,
    Expansion, FieldConfig, FixtureDocument, JudgedQuery, QpsBuilder, QpsConfig, QpsIndex,
    QueryGroup, SearchScratch,
};

fn build_fixture(documents: &[FixtureDocument]) -> (QpsIndex, Vec<String>) {
    let fields = [
        FieldConfig::new("title", 3.0, 0.35, 0.45),
        FieldConfig::new("body", 1.0, 0.75, 0.15),
    ];
    let mut builder = QpsBuilder::new(fields, QpsConfig::default()).unwrap();
    for document in documents {
        let values = [document.title.as_str(), document.body.as_str()];
        builder
            .insert(DocumentInput {
                external_id: document.external_id,
                fields: &values,
            })
            .unwrap();
    }
    let flattened = documents.iter().map(FixtureDocument::flattened).collect();
    (builder.build().unwrap(), flattened)
}

fn build_judged() -> (QpsIndex, Vec<String>, Vec<JudgedQuery>) {
    let (documents, queries) = judged_fixture();
    let (index, flattened) = build_fixture(&documents);
    (index, flattened, queries)
}

#[test]
fn positional_bm25f_solves_the_frozen_adversarial_qrels() {
    let (index, _, queries) = build_judged();
    let mut scratch = SearchScratch::new();
    let mut output = Vec::new();
    for query in queries {
        index
            .search_into(query.text, 5, &mut scratch, &mut output)
            .unwrap();
        assert_eq!(
            output.first().map(|hit| hit.external_id),
            Some(query.relevant_external_id),
            "query: {}",
            query.text
        );
    }
}

#[test]
fn judged_quality_is_at_least_bm25_and_strictly_better_on_one_query() {
    let (index, flattened, queries) = build_judged();
    let corpus = flattened.iter().map(String::as_str).collect::<Vec<_>>();
    let bm25 = BM25Builder::new().build_from_corpus(&corpus).unwrap();
    let (documents, _) = judged_fixture();
    let mut qps_reciprocal_rank = 0.0_f32;
    let mut bm25_reciprocal_rank = 0.0_f32;
    let mut scratch = SearchScratch::new();
    let mut output = Vec::new();
    for query in &queries {
        index
            .search_into(query.text, documents.len(), &mut scratch, &mut output)
            .unwrap();
        let qps_rank = output
            .iter()
            .position(|hit| hit.external_id == query.relevant_external_id)
            .unwrap();
        qps_reciprocal_rank += 1.0 / (qps_rank + 1) as f32;

        let results = bm25.search(query.text, documents.len()).unwrap();
        let bm25_rank = results
            .doc_ids
            .iter()
            .position(|document| {
                documents[*document as usize].external_id == query.relevant_external_id
            })
            .unwrap();
        bm25_reciprocal_rank += 1.0 / (bm25_rank + 1) as f32;
    }
    assert!(qps_reciprocal_rank >= bm25_reciprocal_rank);
    assert!(qps_reciprocal_rank > bm25_reciprocal_rank);
}

#[test]
fn representative_quality_is_not_worse_than_bm25() {
    let (documents, queries) = representative_fixture();
    let (index, flattened) = build_fixture(&documents);
    let corpus = flattened.iter().map(String::as_str).collect::<Vec<_>>();
    let bm25 = BM25Builder::new().build_from_corpus(&corpus).unwrap();
    let mut qps_rr = 0.0_f32;
    let mut bm25_rr = 0.0_f32;
    let mut scratch = SearchScratch::new();
    let mut output = Vec::new();
    for query in &queries {
        index
            .search_into(query.text, documents.len(), &mut scratch, &mut output)
            .unwrap();
        let qps_rank = output
            .iter()
            .position(|hit| hit.external_id == query.relevant_external_id)
            .unwrap();
        qps_rr += 1.0 / (qps_rank + 1) as f32;
        let results = bm25.search(query.text, documents.len()).unwrap();
        let bm25_rank = results
            .doc_ids
            .iter()
            .position(|document| {
                documents[*document as usize].external_id == query.relevant_external_id
            })
            .unwrap();
        bm25_rr += 1.0 / (bm25_rank + 1) as f32;
    }
    assert!(qps_rr >= bm25_rr);
}

#[test]
fn bounded_candidates_match_the_exhaustive_positional_oracle() {
    let corpus = benchmark_corpus(1_000);
    let fields = [FieldConfig::new("body", 1.0, 0.75, 0.0)];
    let mut builder = QpsBuilder::new(fields, QpsConfig::default()).unwrap();
    for (document, text) in corpus.iter().enumerate() {
        let values = [text.as_str()];
        builder
            .insert(DocumentInput {
                external_id: document as u64,
                fields: &values,
            })
            .unwrap();
    }
    let index = builder.build().unwrap();
    let queries = [
        "term17",
        "term17 term203 term411",
        "graph memory retrieval",
        "term0 term1",
        "retrievel memry",
        "neverindexedtoken",
    ];
    let mut bounded_scratch = SearchScratch::new();
    let mut exhaustive_scratch = SearchScratch::new();
    let mut bounded = Vec::new();
    let mut exhaustive = Vec::new();
    for query in queries {
        let receipt = index
            .search_into(query, 10, &mut bounded_scratch, &mut bounded)
            .unwrap();
        index
            .search_exhaustive_into(query, 10, &mut exhaustive_scratch, &mut exhaustive)
            .unwrap();
        assert!(
            receipt.reranked_candidates <= 256,
            "query opened an unbounded positional pool: {query}"
        );
        assert_eq!(
            bounded
                .iter()
                .map(|hit| hit.external_id)
                .collect::<Vec<_>>(),
            exhaustive
                .iter()
                .map(|hit| hit.external_id)
                .collect::<Vec<_>>(),
            "bounded candidate drift for query {query}"
        );
    }
}

#[test]
fn adaptive_selector_uses_sparse_and_dense_lanes() {
    let fields = [FieldConfig::new("body", 1.0, 0.75, 0.0)];
    let mut builder = QpsBuilder::new(fields, QpsConfig::default()).unwrap();
    for document in 0..256_u64 {
        let text = if document < 8 {
            "common background needle cobalt anchor"
        } else {
            "common background"
        };
        let values = [text];
        builder
            .insert(DocumentInput {
                external_id: document,
                fields: &values,
            })
            .unwrap();
    }
    let index = builder.build().unwrap();
    let mut scratch = SearchScratch::new();
    let mut output = Vec::new();
    let sparse = index
        .search_into("needle cobalt anchor", 5, &mut scratch, &mut output)
        .unwrap();
    let dense = index
        .search_into("common", 5, &mut scratch, &mut output)
        .unwrap();
    assert_eq!(sparse.selection, CandidateSelection::SparseTouched);
    assert_eq!(dense.selection, CandidateSelection::DenseSimd);
}

#[test]
fn removal_uses_the_stored_manifest_and_cannot_return_the_document() {
    let fields = [FieldConfig::new("body", 1.0, 0.75, 0.0)];
    let mut builder = QpsBuilder::new(fields, QpsConfig::default()).unwrap();
    let first = ["red dragon armor"];
    let second = ["blue dragon shield"];
    builder
        .insert(DocumentInput {
            external_id: 1,
            fields: &first,
        })
        .unwrap();
    builder
        .insert(DocumentInput {
            external_id: 2,
            fields: &second,
        })
        .unwrap();
    assert!(builder.remove(1));
    let index = builder.build().unwrap();
    let mut scratch = SearchScratch::new();
    let mut output = Vec::new();
    index
        .search_into("red dragon armor", 10, &mut scratch, &mut output)
        .unwrap();
    assert!(output.iter().all(|hit| hit.external_id != 1));
}

#[test]
fn expansion_groups_choose_one_alternative_instead_of_double_counting() {
    let fields = [FieldConfig::new("body", 1.0, 0.75, 0.0)];
    let mut builder = QpsBuilder::new(fields, QpsConfig::default()).unwrap();
    let both = ["car automobile"];
    let one = ["car"];
    builder
        .insert(DocumentInput {
            external_id: 1,
            fields: &both,
        })
        .unwrap();
    builder
        .insert(DocumentInput {
            external_id: 2,
            fields: &one,
        })
        .unwrap();
    let index = builder.build().unwrap();
    let expansions = [
        Expansion {
            term: "car",
            quality: 1.0,
        },
        Expansion {
            term: "automobile",
            quality: 0.8,
        },
    ];
    let groups = [QueryGroup {
        expansions: &expansions,
    }];
    let mut scratch = SearchScratch::new();
    let mut output = Vec::new();
    index
        .search_groups_into(&groups, 10, &mut scratch, &mut output)
        .unwrap();
    let combined = output
        .iter()
        .find(|hit| hit.external_id == 1)
        .unwrap()
        .lexical_score;
    let car_only = [Expansion {
        term: "car",
        quality: 1.0,
    }];
    let car_group = [QueryGroup {
        expansions: &car_only,
    }];
    index
        .search_groups_into(&car_group, 10, &mut scratch, &mut output)
        .unwrap();
    let car = output
        .iter()
        .find(|hit| hit.external_id == 1)
        .unwrap()
        .lexical_score;
    let automobile_only = [Expansion {
        term: "automobile",
        quality: 0.8,
    }];
    let automobile_group = [QueryGroup {
        expansions: &automobile_only,
    }];
    index
        .search_groups_into(&automobile_group, 10, &mut scratch, &mut output)
        .unwrap();
    let automobile = output
        .iter()
        .find(|hit| hit.external_id == 1)
        .unwrap()
        .lexical_score;
    assert!((combined - car.max(automobile)).abs() < 1.0e-6);
}

#[test]
fn warmed_scratch_and_output_do_not_grow() {
    let (index, _, _) = build_judged();
    let mut scratch = SearchScratch::with_document_capacity(64, 32);
    let mut output = Vec::with_capacity(16);
    index
        .search_into("red dragon armor", 10, &mut scratch, &mut output)
        .unwrap();
    let receipt = index
        .search_into("red dragon armor", 10, &mut scratch, &mut output)
        .unwrap();
    assert!(!receipt.allocations_grew);
}
