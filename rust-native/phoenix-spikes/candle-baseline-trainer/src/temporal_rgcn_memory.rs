use crate::telemetry::{working_set_bytes, ThreadAllocationSnapshot};
use crate::CandleTrainerError;
use phoenix_graph_research::{
    TemporalRgcnConfig, TemporalRgcnStagedInput, TemporalRgcnWeights, TEMPORAL_RGCN_HIDDEN,
};
use wide::f32x8;

const HIDDEN: usize = TEMPORAL_RGCN_HIDDEN;
const MATRIX: usize = HIDDEN * HIDDEN;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct FusedTrainingProfile {
    pub parameter_bytes: u64,
    pub gradient_arena_bytes: u64,
    pub allocation_volume_bytes: u64,
    pub allocation_count: u64,
    pub epoch_allocation_volume_bytes: u64,
    pub epoch_allocation_count: u64,
    pub working_set_bytes: u64,
}

pub(crate) struct FusedTrainingOutcome {
    pub weights: TemporalRgcnWeights,
    pub profile: FusedTrainingProfile,
}

pub(crate) fn train_fused_temporal_rgcn16(
    staged: &TemporalRgcnStagedInput,
    config: TemporalRgcnConfig,
) -> Result<FusedTrainingOutcome, CandleTrainerError> {
    validate_staged(staged)?;
    let allocations = ThreadAllocationSnapshot::now();
    let mut weights = initialize_weights(
        config.seed,
        staged.graph.node_types.len(),
        staged.graph.relation_batches.len(),
    );
    let mut arena = GradientArena::new(
        staged.graph.node_types.len(),
        staged.graph.relation_batches.len(),
    );
    let parameter_bytes = weight_bytes(&weights)?;
    let gradient_arena_bytes = arena.bytes()?;
    let epoch_allocations = ThreadAllocationSnapshot::now();
    let before_working_set = working_set_bytes()?;
    for _ in 0..config.epochs {
        train_epoch(&mut weights, &mut arena, staged, config)?;
    }
    let working_set_bytes = before_working_set.max(working_set_bytes()?);
    let epoch_delta = epoch_allocations.elapsed();
    let allocation_delta = allocations.elapsed();
    if epoch_delta.bytes != 0 || epoch_delta.count != 0 {
        return Err(CandleTrainerError::Contract(
            "temporal fused epoch allocated",
        ));
    }
    Ok(FusedTrainingOutcome {
        weights,
        profile: FusedTrainingProfile {
            parameter_bytes,
            gradient_arena_bytes,
            allocation_volume_bytes: allocation_delta.bytes,
            allocation_count: allocation_delta.count,
            epoch_allocation_volume_bytes: epoch_delta.bytes,
            epoch_allocation_count: epoch_delta.count,
            working_set_bytes,
        },
    })
}

struct GradientArena {
    encoded: Vec<[f32; HIDDEN]>,
    encoded_grad: Vec<[f32; HIDDEN]>,
    node_grad: Vec<f32>,
    self_grad: Vec<f32>,
    relation_grad: Vec<f32>,
    decoder_grad: Vec<f32>,
    bias_grad: Vec<f32>,
}

impl GradientArena {
    fn new(nodes: usize, relations: usize) -> Self {
        Self {
            encoded: vec![[0.0; HIDDEN]; nodes],
            encoded_grad: vec![[0.0; HIDDEN]; nodes],
            node_grad: vec![0.0; nodes * HIDDEN],
            self_grad: vec![0.0; MATRIX],
            relation_grad: vec![0.0; relations * MATRIX],
            decoder_grad: vec![0.0; relations * HIDDEN],
            bias_grad: vec![0.0; relations],
        }
    }

    fn clear_gradients(&mut self) {
        self.encoded_grad.fill([0.0; HIDDEN]);
        self.node_grad.fill(0.0);
        self.self_grad.fill(0.0);
        self.relation_grad.fill(0.0);
        self.decoder_grad.fill(0.0);
        self.bias_grad.fill(0.0);
    }

    fn bytes(&self) -> Result<u64, CandleTrainerError> {
        let elements = self
            .encoded
            .capacity()
            .checked_mul(HIDDEN)
            .and_then(|value| value.checked_add(self.encoded_grad.capacity() * HIDDEN))
            .and_then(|value| value.checked_add(self.node_grad.capacity()))
            .and_then(|value| value.checked_add(self.self_grad.capacity()))
            .and_then(|value| value.checked_add(self.relation_grad.capacity()))
            .and_then(|value| value.checked_add(self.decoder_grad.capacity()))
            .and_then(|value| value.checked_add(self.bias_grad.capacity()))
            .ok_or(CandleTrainerError::Contract("temporal arena bytes"))?;
        u64::try_from(elements * size_of::<f32>())
            .map_err(|_| CandleTrainerError::Contract("temporal arena bytes"))
    }
}

fn train_epoch(
    weights: &mut TemporalRgcnWeights,
    arena: &mut GradientArena,
    staged: &TemporalRgcnStagedInput,
    config: TemporalRgcnConfig,
) -> Result<(), CandleTrainerError> {
    encode(weights, arena, staged);
    arena.clear_gradients();
    decoder_backward(weights, arena, staged)?;
    relu_backward(arena);
    encoder_backward(weights, arena, staged);
    sgd_update(weights, arena, config);
    if !weights_finite(weights) {
        return Err(CandleTrainerError::Contract(
            "temporal fused non-finite weights",
        ));
    }
    Ok(())
}

fn encode(
    weights: &TemporalRgcnWeights,
    arena: &mut GradientArena,
    staged: &TemporalRgcnStagedInput,
) {
    arena.encoded.fill([0.0; HIDDEN]);
    for node in 0..arena.encoded.len() {
        let source = row(&weights.node_embeddings, node);
        transform_add(&mut arena.encoded[node], source, &weights.self_weight, 1.0);
    }
    for (relation, batch) in staged.graph.relation_batches.iter().enumerate() {
        let matrix = matrix(&weights.relation_weights, relation);
        for edge in 0..batch.sources.len() {
            let source = row(&weights.node_embeddings, batch.sources[edge] as usize);
            transform_add(
                &mut arena.encoded[batch.targets[edge] as usize],
                source,
                matrix,
                batch.normalizers[edge],
            );
        }
    }
    for values in &mut arena.encoded {
        for value in values {
            *value = value.max(0.0);
        }
    }
}

fn decoder_backward(
    weights: &TemporalRgcnWeights,
    arena: &mut GradientArena,
    staged: &TemporalRgcnStagedInput,
) -> Result<(), CandleTrainerError> {
    let train = &staged.train;
    let inverse_examples = 1.0 / train.labels.len() as f32;
    for index in 0..train.labels.len() {
        let source_index = train.sources[index] as usize;
        let target_index = train.targets[index] as usize;
        let relation = train.relations[index] as usize;
        let source = &arena.encoded[source_index];
        let target = &arena.encoded[target_index];
        let decoder = row(&weights.decoder_relations, relation);
        let logit = simd_triple(source, target, decoder) + weights.decoder_bias[relation];
        let logit_grad = (sigmoid(logit) - f32::from(train.labels[index])) * inverse_examples;
        add_scaled_product(
            row_mut(&mut arena.decoder_grad, relation),
            source,
            target,
            logit_grad,
        );
        arena.bias_grad[relation] += logit_grad;
        add_scaled_product(
            &mut arena.encoded_grad[source_index],
            target,
            decoder,
            logit_grad,
        );
        add_scaled_product(
            &mut arena.encoded_grad[target_index],
            source,
            decoder,
            logit_grad,
        );
    }
    Ok(())
}

fn relu_backward(arena: &mut GradientArena) {
    for (encoded, gradient) in arena.encoded.iter().zip(&mut arena.encoded_grad) {
        for feature in 0..HIDDEN {
            if encoded[feature] <= 0.0 {
                gradient[feature] = 0.0;
            }
        }
    }
}

fn encoder_backward(
    weights: &TemporalRgcnWeights,
    arena: &mut GradientArena,
    staged: &TemporalRgcnStagedInput,
) {
    for node in 0..arena.encoded_grad.len() {
        let source = row(&weights.node_embeddings, node);
        transform_backward(
            row_mut(&mut arena.node_grad, node),
            &mut arena.self_grad,
            &arena.encoded_grad[node],
            source,
            &weights.self_weight,
            1.0,
        );
    }
    for (relation, batch) in staged.graph.relation_batches.iter().enumerate() {
        let matrix = matrix(&weights.relation_weights, relation);
        let gradient = matrix_mut(&mut arena.relation_grad, relation);
        for edge in 0..batch.sources.len() {
            let source_index = batch.sources[edge] as usize;
            let target_index = batch.targets[edge] as usize;
            transform_backward(
                row_mut(&mut arena.node_grad, source_index),
                gradient,
                &arena.encoded_grad[target_index],
                row(&weights.node_embeddings, source_index),
                matrix,
                batch.normalizers[edge],
            );
        }
    }
}

fn transform_backward(
    input_grad: &mut [f32],
    matrix_grad: &mut [f32],
    output_grad: &[f32; HIDDEN],
    input: &[f32],
    weights: &[f32],
    scale: f32,
) {
    for output in 0..HIDDEN {
        let row_scale = output_grad[output] * scale;
        add_scaled(
            input_grad,
            &weights[output * HIDDEN..(output + 1) * HIDDEN],
            row_scale,
        );
        add_scaled(
            &mut matrix_grad[output * HIDDEN..(output + 1) * HIDDEN],
            input,
            row_scale,
        );
    }
}

fn sgd_update(
    weights: &mut TemporalRgcnWeights,
    arena: &GradientArena,
    config: TemporalRgcnConfig,
) {
    update_regularized(
        &mut weights.node_embeddings,
        &arena.node_grad,
        config.learning_rate,
        config.l2,
    );
    update_regularized(
        &mut weights.self_weight,
        &arena.self_grad,
        config.learning_rate,
        config.l2,
    );
    update_regularized(
        &mut weights.relation_weights,
        &arena.relation_grad,
        config.learning_rate,
        config.l2,
    );
    update_regularized(
        &mut weights.decoder_relations,
        &arena.decoder_grad,
        config.learning_rate,
        config.l2,
    );
    update_plain(
        &mut weights.decoder_bias,
        &arena.bias_grad,
        config.learning_rate,
    );
}

fn initialize_weights(seed: u64, nodes: usize, relations: usize) -> TemporalRgcnWeights {
    let mut random = SplitMix64(seed);
    let mut self_weight = initialized(&mut random, MATRIX, 0.01);
    for diagonal in 0..HIDDEN {
        self_weight[diagonal * HIDDEN + diagonal] += 1.0;
    }
    TemporalRgcnWeights {
        node_embeddings: initialized(&mut random, nodes * HIDDEN, 0.2),
        self_weight,
        relation_weights: initialized(&mut random, relations * MATRIX, 0.02),
        decoder_relations: initialized(&mut random, relations * HIDDEN, 0.2),
        decoder_bias: vec![0.0; relations],
    }
}

fn initialized(random: &mut SplitMix64, count: usize, scale: f32) -> Vec<f32> {
    (0..count).map(|_| random.signed_unit() * scale).collect()
}

fn validate_staged(staged: &TemporalRgcnStagedInput) -> Result<(), CandleTrainerError> {
    let train = &staged.train;
    if staged.graph.node_types.is_empty()
        || staged.graph.relation_batches.is_empty()
        || train.labels.is_empty()
        || train.sources.len() != train.labels.len()
        || train.targets.len() != train.labels.len()
        || train.relations.len() != train.labels.len()
    {
        return Err(CandleTrainerError::Contract("temporal fused shapes"));
    }
    Ok(())
}

fn weight_bytes(weights: &TemporalRgcnWeights) -> Result<u64, CandleTrainerError> {
    let elements = weights
        .node_embeddings
        .capacity()
        .checked_add(weights.self_weight.capacity())
        .and_then(|value| value.checked_add(weights.relation_weights.capacity()))
        .and_then(|value| value.checked_add(weights.decoder_relations.capacity()))
        .and_then(|value| value.checked_add(weights.decoder_bias.capacity()))
        .ok_or(CandleTrainerError::Contract("temporal parameter bytes"))?;
    u64::try_from(elements * size_of::<f32>())
        .map_err(|_| CandleTrainerError::Contract("temporal parameter bytes"))
}

fn weights_finite(weights: &TemporalRgcnWeights) -> bool {
    [
        &weights.node_embeddings,
        &weights.self_weight,
        &weights.relation_weights,
        &weights.decoder_relations,
        &weights.decoder_bias,
    ]
    .into_iter()
    .all(|values| values.iter().all(|value| value.is_finite()))
}

fn transform_add(target: &mut [f32; HIDDEN], source: &[f32], matrix: &[f32], scale: f32) {
    for (output, value) in target.iter_mut().enumerate() {
        *value += simd_dot(&matrix[output * HIDDEN..(output + 1) * HIDDEN], source) * scale;
    }
}

fn simd_dot(left: &[f32], right: &[f32]) -> f32 {
    let low: [f32; 8] = (load(left, 0) * load(right, 0)).into();
    let high: [f32; 8] = (load(left, 8) * load(right, 8)).into();
    low.into_iter().chain(high).sum()
}

fn simd_triple(left: &[f32], right: &[f32], relation: &[f32]) -> f32 {
    let low: [f32; 8] = (load(left, 0) * load(right, 0) * load(relation, 0)).into();
    let high: [f32; 8] = (load(left, 8) * load(right, 8) * load(relation, 8)).into();
    low.into_iter().chain(high).sum()
}

fn add_scaled(target: &mut [f32], source: &[f32], scale: f32) {
    let scale = f32x8::splat(scale);
    store(target, 0, load(target, 0) + load(source, 0) * scale);
    store(target, 8, load(target, 8) + load(source, 8) * scale);
}

fn add_scaled_product(target: &mut [f32], left: &[f32], right: &[f32], scale: f32) {
    let scale = f32x8::splat(scale);
    store(
        target,
        0,
        load(target, 0) + load(left, 0) * load(right, 0) * scale,
    );
    store(
        target,
        8,
        load(target, 8) + load(left, 8) * load(right, 8) * scale,
    );
}

fn update_regularized(values: &mut [f32], gradients: &[f32], rate: f32, l2: f32) {
    for (value, gradient) in values.iter_mut().zip(gradients) {
        *value -= rate * (*gradient + l2 * *value);
    }
}

fn update_plain(values: &mut [f32], gradients: &[f32], rate: f32) {
    for (value, gradient) in values.iter_mut().zip(gradients) {
        *value -= rate * *gradient;
    }
}

fn load(values: &[f32], offset: usize) -> f32x8 {
    f32x8::from(<[f32; 8]>::try_from(&values[offset..offset + 8]).expect("SIMD row"))
}

fn store(values: &mut [f32], offset: usize, vector: f32x8) {
    let lanes: [f32; 8] = vector.into();
    values[offset..offset + 8].copy_from_slice(&lanes);
}

fn row(values: &[f32], index: usize) -> &[f32] {
    &values[index * HIDDEN..(index + 1) * HIDDEN]
}

fn row_mut(values: &mut [f32], index: usize) -> &mut [f32] {
    &mut values[index * HIDDEN..(index + 1) * HIDDEN]
}

fn matrix(values: &[f32], index: usize) -> &[f32] {
    &values[index * MATRIX..(index + 1) * MATRIX]
}

fn matrix_mut(values: &mut [f32], index: usize) -> &mut [f32] {
    &mut values[index * MATRIX..(index + 1) * MATRIX]
}

fn sigmoid(value: f32) -> f32 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exponential = value.exp();
        exponential / (1.0 + exponential)
    }
}

struct SplitMix64(u64);

impl SplitMix64 {
    fn signed_unit(&mut self) -> f32 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        let mixed = value ^ (value >> 31);
        let unit = (mixed >> 40) as f32 / (1_u32 << 24) as f32;
        unit * 2.0 - 1.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use phoenix_graph_research::{
        RgcnGraphBatch, RgcnQueryBatch, RgcnRelationBatch, TemporalRgcnStagingProfile,
    };

    #[derive(Clone, Copy)]
    enum Parameter {
        Node(usize),
        SelfWeight(usize),
        Relation(usize),
        Decoder(usize),
        Bias(usize),
    }

    #[test]
    fn fused_gradients_match_central_differences() {
        let staged = fixture();
        let weights = positive_weights();
        let mut arena = GradientArena::new(3, 2);
        encode(&weights, &mut arena, &staged);
        arena.clear_gradients();
        decoder_backward(&weights, &mut arena, &staged).expect("decoder gradient");
        relu_backward(&mut arena);
        encoder_backward(&weights, &mut arena, &staged);
        let checks = [
            (Parameter::Node(0), arena.node_grad[0]),
            (Parameter::SelfWeight(0), arena.self_grad[0]),
            (Parameter::Relation(0), arena.relation_grad[0]),
            (Parameter::Decoder(0), arena.decoder_grad[0]),
            (Parameter::Bias(0), arena.bias_grad[0]),
        ];
        for (parameter, analytic) in checks {
            let numeric = central_difference(&weights, &staged, parameter);
            assert!(
                (analytic - numeric).abs() < 0.000_2,
                "analytic {analytic} numeric {numeric}"
            );
        }
    }

    fn fixture() -> TemporalRgcnStagedInput {
        TemporalRgcnStagedInput {
            graph: RgcnGraphBatch {
                node_types: vec![0, 1, 2],
                relation_batches: vec![
                    RgcnRelationBatch {
                        sources: vec![0],
                        targets: vec![1],
                        normalizers: vec![1.0],
                    },
                    RgcnRelationBatch {
                        sources: vec![1],
                        targets: vec![0],
                        normalizers: vec![1.0],
                    },
                ],
                relation_count: 2,
            },
            train: RgcnQueryBatch {
                sources: vec![0, 0],
                targets: vec![1, 2],
                relations: vec![0, 0],
                labels: vec![true, false],
            },
            profile: TemporalRgcnStagingProfile {
                source_facts: 1,
                train_facts: 1,
                directed_messages: 2,
                training_examples: 2,
                staged_bytes: 0,
                staging_micros: 0,
                train_topology_blake3: "b3-fixture".into(),
                train_only: true,
            },
            source_dataset_id: "source".into(),
            source_binary_blake3: "b3-source".into(),
            task_id: "task".into(),
            task_binary_blake3: "b3-task".into(),
            base_relation_count: 1,
            config: TemporalRgcnConfig::default(),
        }
    }

    fn positive_weights() -> TemporalRgcnWeights {
        TemporalRgcnWeights {
            node_embeddings: vec![0.1; 3 * HIDDEN],
            self_weight: vec![0.05; MATRIX],
            relation_weights: vec![0.03; 2 * MATRIX],
            decoder_relations: vec![0.07; 2 * HIDDEN],
            decoder_bias: vec![0.01; 2],
        }
    }

    fn central_difference(
        weights: &TemporalRgcnWeights,
        staged: &TemporalRgcnStagedInput,
        parameter: Parameter,
    ) -> f32 {
        let epsilon = 0.001;
        let mut low = weights.clone();
        let mut high = weights.clone();
        *parameter_value(&mut low, parameter) -= epsilon;
        *parameter_value(&mut high, parameter) += epsilon;
        (data_loss(&high, staged) - data_loss(&low, staged)) / (2.0 * epsilon)
    }

    fn parameter_value(weights: &mut TemporalRgcnWeights, parameter: Parameter) -> &mut f32 {
        match parameter {
            Parameter::Node(index) => &mut weights.node_embeddings[index],
            Parameter::SelfWeight(index) => &mut weights.self_weight[index],
            Parameter::Relation(index) => &mut weights.relation_weights[index],
            Parameter::Decoder(index) => &mut weights.decoder_relations[index],
            Parameter::Bias(index) => &mut weights.decoder_bias[index],
        }
    }

    fn data_loss(weights: &TemporalRgcnWeights, staged: &TemporalRgcnStagedInput) -> f32 {
        let mut arena = GradientArena::new(3, 2);
        encode(weights, &mut arena, staged);
        let mut total = 0.0;
        for index in 0..staged.train.labels.len() {
            let relation = staged.train.relations[index] as usize;
            let logit = simd_triple(
                &arena.encoded[staged.train.sources[index] as usize],
                &arena.encoded[staged.train.targets[index] as usize],
                row(&weights.decoder_relations, relation),
            ) + weights.decoder_bias[relation];
            let label = f32::from(staged.train.labels[index]);
            total += logit.max(0.0) - logit * label + (-logit.abs()).exp().ln_1p();
        }
        total / staged.train.labels.len() as f32
    }
}
