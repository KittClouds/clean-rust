use std::time::Instant;

use vector_wgpu_kernel::{
    CpuResidentCorpus, DispatchPolicy, GpuVectorRuntime, VectorCorpusInput, VectorRerankBatch,
    normalize_rows,
};

fn main() {
    let rows = 20_000_u32;
    let dimensions = 256_u32;
    let queries = 2_048_u32;
    let candidates_per_query = 128_u32;
    let top_k = 16_u32;
    let fixture = Fixture::new(rows, dimensions, queries, candidates_per_query, top_k);
    let runtime = GpuVectorRuntime::request(DispatchPolicy::default()).expect("request GPU");
    let resident = runtime.upload(fixture.corpus()).expect("upload corpus");
    assert_eq!(
        resident.dispatch_backend(fixture.batch(), true).unwrap(),
        vector_wgpu_kernel::DispatchBackend::Gpu
    );
    resident.rerank(fixture.batch()).expect("warm GPU");
    let cpu_resident = CpuResidentCorpus::new(fixture.corpus()).expect("validate CPU corpus");

    let cpu_started = Instant::now();
    let cpu = cpu_resident.rerank(fixture.batch()).expect("CPU oracle");
    let cpu_ms = cpu_started.elapsed().as_secs_f64() * 1_000.0;
    let mut gpu_ms = Vec::with_capacity(5);
    let mut last = None;
    for _ in 0..5 {
        let started = Instant::now();
        last = Some(resident.rerank(fixture.batch()).expect("GPU rerank"));
        gpu_ms.push(started.elapsed().as_secs_f64() * 1_000.0);
    }
    gpu_ms.sort_by(f64::total_cmp);
    let gpu = last.unwrap();
    let (overlap, maximum_score_drift) = compare(&gpu.top_k, &cpu);
    assert!(
        overlap >= 0.99,
        "top-k overlap {overlap:.6} fell below 0.99"
    );
    assert!(
        maximum_score_drift <= 2.0e-5,
        "score drift {maximum_score_drift:.9} exceeded tolerance"
    );
    println!(
        "vector-rerank rows={rows} dim={dimensions} queries={queries} candidates={} pairs={} cpu_ms={cpu_ms:.3} gpu_p50_ms={:.3} overlap={overlap:.6} max_score_drift={maximum_score_drift:.9} dispatch_us={} readback_us={} returned={} adapter={}",
        candidates_per_query,
        queries * candidates_per_query,
        gpu_ms[gpu_ms.len() / 2],
        gpu.receipt.dispatch_micros,
        gpu.receipt.readback_micros,
        gpu.receipt.returned_records,
        runtime.adapter_receipt().name,
    );
}

fn compare(
    actual: &vector_wgpu_kernel::CompactTopKOutput,
    expected: &vector_wgpu_kernel::CompactTopKOutput,
) -> (f64, f32) {
    let mut matched = 0_u64;
    let mut total = 0_u64;
    let mut maximum_score_drift = 0.0_f32;
    for query in 0..actual.offsets.len().saturating_sub(1) {
        let actual_row = actual.query(query);
        let expected_row = expected.query(query);
        total += expected_row.len() as u64;
        for actual_record in actual_row {
            if let Some(expected_record) = expected_row
                .iter()
                .find(|record| record.candidate_id == actual_record.candidate_id)
            {
                matched += 1;
                maximum_score_drift =
                    maximum_score_drift.max((actual_record.score - expected_record.score).abs());
            }
        }
    }
    (matched as f64 / total.max(1) as f64, maximum_score_drift)
}

struct Fixture {
    values: Vec<f32>,
    ranks: Vec<u32>,
    query_values: Vec<f32>,
    offsets: Vec<u32>,
    candidates: Vec<u32>,
    rows: u32,
    dimensions: u32,
    queries: u32,
    top_k: u32,
}

impl Fixture {
    fn new(rows: u32, dimensions: u32, queries: u32, candidate_count: u32, top_k: u32) -> Self {
        let mut values = (0..rows * dimensions)
            .map(|index| ((index * 73 + 29) % 1021) as f32 / 510.0 - 1.0)
            .collect::<Vec<_>>();
        normalize_rows(&mut values, rows, dimensions).unwrap();
        let mut query_values = (0..queries * dimensions)
            .map(|index| ((index * 43 + 17) % 997) as f32 / 498.0 - 1.0)
            .collect::<Vec<_>>();
        normalize_rows(&mut query_values, queries, dimensions).unwrap();
        let mut offsets = Vec::with_capacity(queries as usize + 1);
        let mut candidates = Vec::with_capacity((queries * candidate_count) as usize);
        offsets.push(0);
        for query in 0..queries {
            for slot in 0..candidate_count {
                candidates.push((query * 17 + slot * 31) % rows);
            }
            offsets.push(candidates.len() as u32);
        }
        Self {
            values,
            ranks: (0..rows).collect(),
            query_values,
            offsets,
            candidates,
            rows,
            dimensions,
            queries,
            top_k,
        }
    }

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
            queries: &self.query_values,
            query_count: self.queries,
            candidate_offsets: &self.offsets,
            candidate_ids: &self.candidates,
            top_k: self.top_k,
            minimum_similarity: -1.0,
        }
    }
}
