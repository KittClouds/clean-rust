use g_reasoner_34m_parity::kernel::fast_distmult_sum as reasoner_cpu;
use gfm_rag_8m_parity::kernel::fast_distmult_sum as rag_cpu;
use gfm_wgpu_kernel::{DispatchPolicy, DistMultInput, GpuKernelRuntime};

#[test]
fn gpu_matches_both_established_gfm_kernels_and_repeats_exactly() {
    let fixture = fixture(257, 2_113, 19, 7);
    let input = fixture.input();
    let (rag, _) = rag_cpu(
        input.offsets,
        input.sources,
        input.relation_ids,
        input.input,
        input.relations,
        input.boundary,
        input.dim,
    )
    .unwrap();
    let (reasoner, _) = reasoner_cpu(
        input.offsets,
        input.sources,
        input.relation_ids,
        input.input,
        input.relations,
        input.boundary,
        input.dim,
    )
    .unwrap();
    assert_eq!(rag, reasoner);

    let runtime = match GpuKernelRuntime::request(DispatchPolicy::default()) {
        Ok(runtime) => runtime,
        Err(error) => {
            eprintln!("GPU parity skipped because no adapter is available: {error}");
            return;
        }
    };
    let resident = runtime.upload(input).unwrap();
    let first = resident.execute().unwrap();
    let second = resident.execute().unwrap();
    assert_eq!(first.values, second.values);
    let max_abs = max_abs(&rag, &first.values);
    assert!(max_abs <= 1.0e-5, "GPU parity drift {max_abs}");
    assert_eq!(first.receipt.output_values, rag.len() as u64);
}

#[test]
fn residency_budget_rejects_before_gpu_allocation() {
    let fixture = fixture(64, 256, 8, 4);
    let policy = DispatchPolicy {
        maximum_resident_bytes: 1,
        ..Default::default()
    };
    let runtime = match GpuKernelRuntime::request(policy) {
        Ok(runtime) => runtime,
        Err(_) => return,
    };
    let error = match runtime.upload(fixture.input()) {
        Ok(_) => panic!("one-byte residency budget unexpectedly admitted the kernel"),
        Err(error) => error,
    };
    assert!(error.to_string().contains("configured"));
}

struct Fixture {
    offsets: Vec<u64>,
    sources: Vec<u32>,
    relation_ids: Vec<u32>,
    input: Vec<f32>,
    relations: Vec<f32>,
    boundary: Vec<f32>,
    dim: usize,
}

impl Fixture {
    fn input(&self) -> DistMultInput<'_> {
        DistMultInput {
            offsets: &self.offsets,
            sources: &self.sources,
            relation_ids: &self.relation_ids,
            input: &self.input,
            relations: &self.relations,
            boundary: &self.boundary,
            dim: self.dim,
        }
    }
}

fn fixture(nodes: usize, edges: usize, dim: usize, relation_count: usize) -> Fixture {
    let mut offsets = Vec::with_capacity(nodes + 1);
    offsets.push(0);
    for node in 0..nodes {
        let end = (edges * (node + 1) / nodes) as u64;
        offsets.push(end);
    }
    let sources = (0..edges)
        .map(|edge| ((edge * 17 + edge / 7) % nodes) as u32)
        .collect();
    let relation_ids = (0..edges)
        .map(|edge| (edge % relation_count) as u32)
        .collect();
    let input = values(nodes * dim, 29, 0.0078125);
    let relations = values(relation_count * dim, 13, -0.00390625);
    let boundary = values(nodes * dim, 7, 0.001953125);
    Fixture {
        offsets,
        sources,
        relation_ids,
        input,
        relations,
        boundary,
        dim,
    }
}

fn values(count: usize, multiplier: usize, scale: f32) -> Vec<f32> {
    (0..count)
        .map(|index| ((index * multiplier % 251) as f32 - 125.0) * scale)
        .collect()
}

fn max_abs(left: &[f32], right: &[f32]) -> f32 {
    left.iter()
        .zip(right)
        .map(|(left, right)| (left - right).abs())
        .fold(0.0, f32::max)
}
