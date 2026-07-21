use gfm_wgpu_kernel::{
    GpuResidentChainRuntime, ResidentChainInput, TopKRecord, cpu_resident_chain,
};

const GPU_BUDGET: u64 = 512 * 1024 * 1024;

#[test]
fn resident_chain_matches_cpu_with_compact_top_k_for_both_model_shapes() {
    let runtime = GpuResidentChainRuntime::request(GPU_BUDGET).unwrap();
    for entity_enabled in [false, true] {
        let fixture = Fixture::new(777, 32, 3, 24, 6, entity_enabled);
        let input = fixture.input(17);
        let cpu = cpu_resident_chain(input).unwrap();
        let resident = runtime.upload(input).unwrap();
        let trace = resident.execute_trace().unwrap();
        assert_close_slice(&trace.hidden, &cpu.hidden, 4.0e-4);
        assert_close_slice(&trace.logits, &cpu.logits, 5.0e-4);

        let compact = resident.execute_top_k().unwrap();
        let gpu_expected = ranked(&trace.logits, 17);
        assert_top_k(&compact.top_k, &gpu_expected, 0.0);
        assert_top_k(&compact.top_k, &cpu.top_k, 5.0e-4);
        assert_eq!(compact.timing.readback_bytes, 17 * 8);
        assert_eq!(trace.timing.readback_bytes, (777 * (32 + 1) * 4) as u64);
        assert!(compact.timing.readback_bytes * 700 < trace.timing.readback_bytes);

        let repeated = resident.execute_top_k().unwrap();
        assert_eq!(repeated.top_k, compact.top_k);
    }
}

#[test]
fn resident_chain_validation_fails_closed() {
    let fixture = Fixture::new(8, 8, 2, 4, 2, false);
    let mut input = fixture.input(3);
    input.top_k = 0;
    assert!(input.validate().unwrap_err().to_string().contains("top_k"));
    input = fixture.input(3);
    input.sources = &[99];
    input.relation_ids = &[0];
    input.offsets = &[0, 1, 1, 1, 1, 1, 1, 1, 1];
    assert!(
        input
            .validate()
            .unwrap_err()
            .to_string()
            .contains("identity")
    );
}

struct Fixture {
    offsets: Vec<u64>,
    sources: Vec<u32>,
    relation_ids: Vec<u32>,
    hidden: Vec<f32>,
    boundary: Vec<f32>,
    relations: Vec<f32>,
    old_weights: Vec<f32>,
    aggregate_weights: Vec<f32>,
    update_bias: Vec<f32>,
    norm_scale: Vec<f32>,
    norm_bias: Vec<f32>,
    scorer_hidden_weight: Vec<f32>,
    entity: Option<Vec<f32>>,
    scorer_entity_weight: Option<Vec<f32>>,
    query_term: Vec<f32>,
    scorer_bias: Vec<f32>,
    scorer_output_weight: Vec<f32>,
    dim: usize,
    layers: usize,
    score_dim: usize,
}

impl Fixture {
    fn new(
        nodes: usize,
        dim: usize,
        layers: usize,
        score_dim: usize,
        fanout: usize,
        entity_enabled: bool,
    ) -> Self {
        let mut offsets = Vec::with_capacity(nodes + 1);
        let mut sources = Vec::with_capacity(nodes * fanout);
        let mut relation_ids = Vec::with_capacity(nodes * fanout);
        offsets.push(0);
        for node in 0..nodes {
            for edge in 0..fanout {
                sources.push(((node * 17 + edge * 29 + 3) % nodes) as u32);
                relation_ids.push(((node + edge * 3) % 7) as u32);
            }
            offsets.push(sources.len() as u64);
        }
        let node_values = nodes * dim;
        let layer_matrix = layers * dim * dim;
        let layer_vector = layers * dim;
        let score_matrix = score_dim * dim;
        Self {
            offsets,
            sources,
            relation_ids,
            hidden: values(node_values, 0.08, 1),
            boundary: values(node_values, 0.015, 2),
            relations: values(layers * 7 * dim, 0.04, 3),
            old_weights: values(layer_matrix, 0.025, 4),
            aggregate_weights: values(layer_matrix, 0.018, 5),
            update_bias: values(layer_vector, 0.01, 6),
            norm_scale: (0..layer_vector)
                .map(|index| 0.9 + value(index, 0.08, 7).abs())
                .collect(),
            norm_bias: values(layer_vector, 0.01, 8),
            scorer_hidden_weight: values(score_matrix, 0.03, 9),
            entity: entity_enabled.then(|| values(node_values, 0.06, 10)),
            scorer_entity_weight: entity_enabled.then(|| values(score_matrix, 0.02, 11)),
            query_term: values(score_dim, 0.04, 12),
            scorer_bias: values(score_dim, 0.01, 13),
            scorer_output_weight: values(score_dim, 0.05, 14),
            dim,
            layers,
            score_dim,
        }
    }

    fn input(&self, top_k: usize) -> ResidentChainInput<'_> {
        ResidentChainInput {
            offsets: &self.offsets,
            sources: &self.sources,
            relation_ids: &self.relation_ids,
            initial_hidden: &self.hidden,
            boundary: &self.boundary,
            layer_relations: &self.relations,
            old_weights: &self.old_weights,
            aggregate_weights: &self.aggregate_weights,
            update_bias: &self.update_bias,
            norm_scale: &self.norm_scale,
            norm_bias: &self.norm_bias,
            scorer_hidden_weight: &self.scorer_hidden_weight,
            scorer_entity: self.entity.as_deref(),
            scorer_entity_weight: self.scorer_entity_weight.as_deref(),
            scorer_query_term: &self.query_term,
            scorer_bias: &self.scorer_bias,
            scorer_output_weight: &self.scorer_output_weight,
            scorer_output_bias: 0.017,
            dim: self.dim,
            layers: self.layers,
            score_dim: self.score_dim,
            top_k,
        }
    }
}

fn values(count: usize, scale: f32, salt: usize) -> Vec<f32> {
    (0..count).map(|index| value(index, scale, salt)).collect()
}

fn value(index: usize, scale: f32, salt: usize) -> f32 {
    let mixed = index
        .wrapping_mul(1_664_525)
        .wrapping_add(salt.wrapping_mul(1_013_904_223));
    ((mixed % 2_003) as f32 / 1_001.0 - 1.0) * scale
}

fn assert_close_slice(actual: &[f32], expected: &[f32], tolerance: f32) {
    assert_eq!(actual.len(), expected.len());
    let (index, delta) = actual
        .iter()
        .zip(expected)
        .enumerate()
        .map(|(index, (actual, expected))| {
            let scale = expected.abs().max(1.0);
            (index, (actual - expected).abs() / scale)
        })
        .max_by(|left, right| left.1.total_cmp(&right.1))
        .unwrap();
    assert!(
        delta <= tolerance,
        "relative drift {delta} at value {index} exceeds {tolerance}"
    );
}

fn assert_top_k(actual: &[TopKRecord], expected: &[TopKRecord], tolerance: f32) {
    assert_eq!(actual.len(), expected.len());
    for (actual, expected) in actual.iter().zip(expected) {
        assert_eq!(
            actual.node, expected.node,
            "actual ({}, {}) expected ({}, {})",
            actual.node, actual.score, expected.node, expected.score
        );
        let scale = expected.score.abs().max(1.0);
        assert!((actual.score - expected.score).abs() <= tolerance * scale);
    }
}

fn ranked(logits: &[f32], top_k: usize) -> Vec<TopKRecord> {
    let mut records = logits
        .iter()
        .enumerate()
        .map(|(node, &score)| TopKRecord {
            score,
            node: node as u32,
        })
        .collect::<Vec<_>>();
    records.sort_unstable_by(|left, right| {
        right
            .score
            .total_cmp(&left.score)
            .then_with(|| left.node.cmp(&right.node))
    });
    records.truncate(top_k);
    records
}
