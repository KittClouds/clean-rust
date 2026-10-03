//! Receipt-level hotspot profiler: per-bucket stage breakdown using the
//! instrumentation QPS already carries (SearchStageNanos + counters).
//! No new dependencies. Run: cargo run --release -p phoenix-lexical-qps
//! --example perf_probe

use std::time::Instant;

use phoenix_lexical_qps::{
    DocumentInput, Expansion, FieldConfig, QpsBuilder, QpsConfig, QueryGroup, SearchScratch,
};

const DOCS: usize = 10_000;
const TOKENS: usize = 96;
const VOCAB: usize = 512;
const TOP_K: usize = 10;
const WARM: usize = 200;
const MEASURED: usize = 2_000;

/// Exact replica of phoenix-qps-experiment's benchmark_corpus (xorshift,
/// '.' segments, phrase every 97th doc), PLUS a "common" token on even docs
/// (extra dense-lane bucket; phrase/multi buckets stay comparable).
fn benchmark_corpus() -> Vec<String> {
    let vocabulary = (0..VOCAB)
        .map(|index| format!("term{index}"))
        .collect::<Vec<_>>();
    (0..DOCS)
        .map(|document| {
            let mut state = (document as u64 + 1).wrapping_mul(0x9E37_79B9_7F4A_7C15);
            let mut text = String::with_capacity(768);
            for token in 0..TOKENS {
                state ^= state >> 12;
                state ^= state << 25;
                state ^= state >> 27;
                let word = &vocabulary[(state as usize) & (vocabulary.len() - 1)];
                text.push_str(word);
                text.push(if token % 24 == 23 { '.' } else { ' ' });
            }
            if document % 97 == 0 {
                text.push_str(" graph memory retrieval.");
            }
            if document % 2 == 0 {
                text.push_str(" common.");
            }
            // Skewed-bucket term: df~50 against common's df~5000. Exercises
            // block-max skipping (uniform terms cannot produce skew).
            if document % 200 == 0 {
                text.push_str(" rareterm.");
            }
            text
        })
        .collect()
}

fn main() {
    let corpus = benchmark_corpus();
    let fields = [FieldConfig::new("body", 1.0, 0.75, 0.0)];
    let mut builder =
        QpsBuilder::new(Vec::from(fields).into_boxed_slice(), QpsConfig::default()).unwrap();
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
    let stats = index.stats();
    println!(
        "index: {} docs, {} terms, {} posting rows, {} positions, {:.2} MiB estimated",
        stats.documents,
        stats.terms,
        stats.posting_rows,
        stats.positions,
        stats.estimated_bytes as f64 / 1_048_576.0
    );

    let buckets: &[(&str, &str)] = &[
        ("one-token", "term17"),
        ("multi-token", "term17 term203 term411"),
        ("phrase-like", "graph memory retrieval"),
        ("high-frequency", "common term0"),
        ("skewed", "rareterm common"),
        ("fuzzy-miss", "retrievel memry"),
        ("no-result", "neverindexedtoken"),
    ];
    println!(
        "{:<15} {:>10} {:>10} {:>10} {:>10} {:>10} {:>8} {:>8} {:>8} {:>8} {:>8} {:<13} {:>5} {:>8} {:>6} {:>6} {:>6} {:>8} {:>8} {:>10}",
        "bucket",
        "mean_ns",
        "accum",
        "select",
        "coher",
        "order",
        "cand",
        "coverd",
        "rerank",
        "rows",
        "posvals",
        "selection",
        "alloc",
        "avail",
        "bskip",
        "cdeath",
        "sdeath",
        "litdoc",
        "litavoid",
        "litchoices",
    );
    let mut scratch = SearchScratch::with_document_capacity(DOCS, 32);
    let mut hits = Vec::with_capacity(256);
    for (bucket, query) in buckets {
        for _ in 0..WARM {
            hits.clear();
            index
                .search_into(query, TOP_K, &mut scratch, &mut hits)
                .unwrap();
        }
        let start = Instant::now();
        for _ in 0..MEASURED {
            hits.clear();
            index
                .search_into(query, TOP_K, &mut scratch, &mut hits)
                .unwrap();
        }
        let mean_ns = start.elapsed().as_nanos() / MEASURED as u128;
        hits.clear();
        let receipt = index
            .search_into(query, TOP_K, &mut scratch, &mut hits)
            .unwrap();
        println!(
            "{:<15} {:>10} {:>10} {:>10} {:>10} {:>10} {:>8} {:>8} {:>8} {:>8} {:>8} {:<13?} {:>5} {:>8} {:>6} {:>6} {:>6} {:>8} {:>8} {:>10}",
            bucket,
            mean_ns,
            receipt.stages.accumulation,
            receipt.stages.selection,
            receipt.stages.coherence,
            receipt.stages.ordering,
            receipt.candidates,
            receipt.covered_candidates,
            receipt.reranked_candidates,
            receipt.posting_rows_visited,
            receipt.position_values_visited,
            receipt.selection,
            receipt.allocations_grew,
            receipt.posting_rows_available,
            receipt.blocks_skipped,
            receipt.coverage_impossible_deaths,
            receipt.score_bound_deaths,
            receipt.literal_documents_finalized,
            receipt.literal_scratch_documents_avoided,
            receipt.literal_choice_records_materialized,
        );
    }

    // REDLINE Phase 3C: diagnostic-only decomposition. This does not use or
    // mutate the serving result; it attributes merge, flat selection, classic
    // accumulation, heap selection, and null traversal independently.
    let diagnostics = [
        ("dense-3c", "term17 term203 term411"),
        ("high-3c", "common term0"),
        ("skewed-3c", "rareterm common"),
    ];
    println!(
        "{:<12} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8}",
        "phase3c", "rows", "docs", "flat", "fselect", "classic", "heap", "mnull", "cnull", "limit"
    );
    let mut diagnostic_scratch = SearchScratch::with_document_capacity(DOCS, 32);
    for (name, query) in diagnostics {
        for _ in 0..WARM {
            let _ = index
                .phase3c_diagnostics(query, TOP_K, &mut diagnostic_scratch)
                .unwrap();
        }
        let mut sums = [0_u128; 6];
        let mut last = None;
        for _ in 0..MEASURED {
            let receipt = index
                .phase3c_diagnostics(query, TOP_K, &mut diagnostic_scratch)
                .unwrap();
            sums[0] += u128::from(receipt.merge_flat_nanos);
            sums[1] += u128::from(receipt.flat_select_nanos);
            sums[2] += u128::from(receipt.classic_accum_nanos);
            sums[3] += u128::from(receipt.classic_heap_nanos);
            sums[4] += u128::from(receipt.merge_null_nanos);
            sums[5] += u128::from(receipt.classic_null_nanos);
            last = Some(receipt);
        }
        let receipt = last.expect("diagnostic measurement has one iteration");
        println!(
            "{:<12} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8}",
            name,
            receipt.posting_rows,
            receipt.documents_finalized,
            sums[0] / MEASURED as u128,
            sums[1] / MEASURED as u128,
            sums[2] / MEASURED as u128,
            sums[3] / MEASURED as u128,
            sums[4] / MEASURED as u128,
            sums[5] / MEASURED as u128,
            receipt.candidate_limit,
        );
    }

    // Transport fan-out arm on the phrase query.
    let g0 = [
        Expansion {
            term: "graph",
            quality: 1.0,
        },
        Expansion {
            term: "term17",
            quality: 0.6,
        },
        Expansion {
            term: "term18",
            quality: 0.4,
        },
    ];
    let g1 = [
        Expansion {
            term: "memory",
            quality: 1.0,
        },
        Expansion {
            term: "term203",
            quality: 0.6,
        },
        Expansion {
            term: "term204",
            quality: 0.4,
        },
    ];
    let g2 = [
        Expansion {
            term: "retrieval",
            quality: 1.0,
        },
        Expansion {
            term: "term411",
            quality: 0.6,
        },
        Expansion {
            term: "term412",
            quality: 0.4,
        },
    ];
    let groups = [
        QueryGroup { expansions: &g0 },
        QueryGroup { expansions: &g1 },
        QueryGroup { expansions: &g2 },
    ];
    for _ in 0..WARM {
        hits.clear();
        index
            .search_groups_into(&groups, TOP_K, &mut scratch, &mut hits)
            .unwrap();
    }
    let start = Instant::now();
    for _ in 0..MEASURED {
        hits.clear();
        index
            .search_groups_into(&groups, TOP_K, &mut scratch, &mut hits)
            .unwrap();
    }
    let mean_ns = start.elapsed().as_nanos() / MEASURED as u128;
    hits.clear();
    let receipt = index
        .search_groups_into(&groups, TOP_K, &mut scratch, &mut hits)
        .unwrap();
    println!(
        "{:<15} {:>10} {:>10} {:>10} {:>10} {:>10} {:>8} {:>8} {:>8} {:>8} {:>8} {:<13?} {:>5} {:>8} {:>6} {:>6} {:>6}",
        "transport-x3",
        mean_ns,
        receipt.stages.accumulation,
        receipt.stages.selection,
        receipt.stages.coherence,
        receipt.stages.ordering,
        receipt.candidates,
        receipt.covered_candidates,
        receipt.reranked_candidates,
        receipt.posting_rows_visited,
        receipt.position_values_visited,
        receipt.selection,
        receipt.allocations_grew,
        receipt.posting_rows_available,
        receipt.blocks_skipped,
        receipt.coverage_impossible_deaths,
        receipt.score_bound_deaths,
    );
    println!(
        "hits_transport_top3: {:?}",
        hits.iter()
            .take(3)
            .map(|h| h.external_id)
            .collect::<Vec<_>>()
    );
    let raw = receipt.transport_raw_expansion_rows as f64;
    let unique = receipt.transport_unique_group_documents as f64;
    let winning_rows = receipt.transport_winning_expansion_rows as f64;
    println!(
        "transport_phase4: A={} U={} nonliteral={} literal={} WanyRows={} deadRows={} outsidePoolRows={} uncovered={} collapse={:.3} authority={:.5} dead={:.5}",
        receipt.transport_raw_expansion_rows,
        receipt.transport_unique_group_documents,
        receipt.transport_nonliteral_winner_documents,
        receipt.transport_literal_winner_documents,
        receipt.transport_winning_expansion_rows,
        receipt.transport_rows_never_winner,
        receipt.transport_winner_rows_outside_pool,
        receipt.transport_touched_uncovered,
        raw / unique.max(1.0),
        winning_rows / raw.max(1.0),
        receipt.transport_rows_never_winner as f64 / raw.max(1.0),
    );

    // Lexical-only isolation arm: positional weights zeroed, so no position
    // payload is ever opened (reranked=0). Whatever remains is
    // accumulation + selection + ordering + per-hit evidence work.
    println!(
        "sizeof SearchHit: {} bytes (snapshot V2 hit was ~48 bytes)",
        std::mem::size_of::<phoenix_lexical_qps::SearchHit>()
    );
    let mut lex_config = QpsConfig::default();
    lex_config.proximity_weight = 0.0;
    lex_config.order_weight = 0.0;
    lex_config.phrase_weight = 0.0;
    lex_config.segment_weight = 0.0;
    let lex_fields = [FieldConfig::new("body", 1.0, 0.75, 0.0)];
    let mut lex_builder =
        QpsBuilder::new(Vec::from(lex_fields).into_boxed_slice(), lex_config).unwrap();
    for (document, text) in corpus.iter().enumerate() {
        let values = [text.as_str()];
        lex_builder
            .insert(DocumentInput {
                external_id: document as u64,
                fields: &values,
            })
            .unwrap();
    }
    let lex_index = lex_builder.build().unwrap();
    for _ in 0..WARM {
        hits.clear();
        lex_index
            .search_into("graph memory retrieval", TOP_K, &mut scratch, &mut hits)
            .unwrap();
    }
    let start = Instant::now();
    for _ in 0..MEASURED {
        hits.clear();
        lex_index
            .search_into("graph memory retrieval", TOP_K, &mut scratch, &mut hits)
            .unwrap();
    }
    let mean_ns = start.elapsed().as_nanos() / MEASURED as u128;
    hits.clear();
    let receipt = lex_index
        .search_into("graph memory retrieval", TOP_K, &mut scratch, &mut hits)
        .unwrap();
    println!(
        "{:<15} {:>10} {:>10} {:>10} {:>10} {:>10} {:>8} {:>8} {:>8} {:>8} {:>8} {:<13?} {:>5} {:>8} {:>6} {:>6} {:>6}",
        "lexical-only",
        mean_ns,
        receipt.stages.accumulation,
        receipt.stages.selection,
        receipt.stages.coherence,
        receipt.stages.ordering,
        receipt.candidates,
        receipt.covered_candidates,
        receipt.reranked_candidates,
        receipt.posting_rows_visited,
        receipt.position_values_visited,
        receipt.selection,
        receipt.allocations_grew,
        receipt.posting_rows_available,
        receipt.blocks_skipped,
        receipt.coverage_impossible_deaths,
        receipt.score_bound_deaths,
    );
}
