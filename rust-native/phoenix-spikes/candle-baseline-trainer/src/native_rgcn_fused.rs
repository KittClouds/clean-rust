use crate::telemetry::ThreadAllocationSnapshot;
use crate::{micros, model_tensor, CandleRgcnConfig, CandleTrainerError, SplitMix64};
use phoenix_graph_research::{
    score_rgcn16_tensors, FrozenModelTensor, RgcnGraphBatch, RgcnQueryBatch, RgcnStagedInput,
    RGCN_DECODER_BIAS, RGCN_DECODER_RELATION, RGCN_NODE_TYPE_EMBEDDING, RGCN_RELATION_WEIGHT,
    RGCN_SELF_WEIGHT,
};
use std::time::Instant;
use wide::f32x8;

const HIDDEN: usize = 16;
const MATRIX: usize = HIDDEN * HIDDEN;

pub(crate) struct FusedRgcnTrainingOutcome {
    pub tensors: Vec<FrozenModelTensor>,
    pub scores: Vec<f32>,
    pub training_micros: u64,
    pub canonical_scoring_micros: u64,
    pub parameter_bytes: u64,
    pub gradient_arena_bytes: u64,
    pub epoch_allocation_volume_bytes: u64,
    pub epoch_allocation_count: u64,
}

pub(crate) fn train_fused_rgcn16(
    staged: &RgcnStagedInput,
    config: CandleRgcnConfig,
    seed: u64,
) -> Result<FusedRgcnTrainingOutcome, CandleTrainerError> {
    validate(staged, config)?;
    let node_types = staged
        .graph
        .node_types
        .iter()
        .copied()
        .max()
        .and_then(|value| value.checked_add(1))
        .ok_or(CandleTrainerError::Contract("fused R-GCN node types"))?
        as usize;
    let message_relations = staged.graph.relation_batches.len();
    let decoder_relations = staged.graph.relation_count as usize;
    let mut weights = Weights::new(seed, node_types, message_relations, decoder_relations);
    let mut arena = GradientArena::new(
        staged.graph.node_types.len(),
        node_types,
        message_relations,
        decoder_relations,
    );
    let parameter_bytes = weights.bytes()?;
    let gradient_arena_bytes = arena.bytes()?;
    let epoch_allocations = ThreadAllocationSnapshot::now();
    let training_started = Instant::now();
    for _ in 0..config.epochs {
        train_epoch(&mut weights, &mut arena, staged, config)?;
    }
    let training_micros = micros(training_started.elapsed());
    let epoch_delta = epoch_allocations.elapsed();
    if epoch_delta.bytes != 0 || epoch_delta.count != 0 {
        return Err(CandleTrainerError::Contract("fused R-GCN epoch allocated"));
    }
    let tensors = weights.export();
    let scoring_started = Instant::now();
    let scores = score_rgcn16_tensors(&tensors, &staged.graph, &staged.validation)?;
    let canonical_scoring_micros = micros(scoring_started.elapsed());
    Ok(FusedRgcnTrainingOutcome {
        tensors,
        scores,
        training_micros,
        canonical_scoring_micros,
        parameter_bytes,
        gradient_arena_bytes,
        epoch_allocation_volume_bytes: epoch_delta.bytes,
        epoch_allocation_count: epoch_delta.count,
    })
}

struct Weights {
    node_types: Vec<f32>,
    self_weight: Vec<f32>,
    relation_weight: Vec<f32>,
    decoder: Vec<f32>,
    bias: Vec<f32>,
}

impl Weights {
    fn new(seed: u64, node_types: usize, messages: usize, decoders: usize) -> Self {
        let mut random = SplitMix64(seed);
        Self {
            node_types: initialized(&mut random, node_types * HIDDEN, 0.12),
            self_weight: initialized(&mut random, MATRIX, 0.12),
            relation_weight: initialized(&mut random, messages * MATRIX, 0.12),
            decoder: initialized(&mut random, decoders * HIDDEN, 0.12),
            bias: vec![0.0; decoders],
        }
    }

    fn export(&self) -> Vec<FrozenModelTensor> {
        vec![
            model_tensor(
                RGCN_NODE_TYPE_EMBEDDING,
                &[(self.node_types.len() / HIDDEN) as u64, HIDDEN as u64],
                self.node_types.clone(),
            ),
            model_tensor(
                RGCN_SELF_WEIGHT,
                &[HIDDEN as u64, HIDDEN as u64],
                self.self_weight.clone(),
            ),
            model_tensor(
                RGCN_RELATION_WEIGHT,
                &[
                    (self.relation_weight.len() / MATRIX) as u64,
                    HIDDEN as u64,
                    HIDDEN as u64,
                ],
                self.relation_weight.clone(),
            ),
            model_tensor(
                RGCN_DECODER_RELATION,
                &[(self.decoder.len() / HIDDEN) as u64, HIDDEN as u64],
                self.decoder.clone(),
            ),
            model_tensor(
                RGCN_DECODER_BIAS,
                &[self.bias.len() as u64],
                self.bias.clone(),
            ),
        ]
    }

    fn bytes(&self) -> Result<u64, CandleTrainerError> {
        byte_sum([
            self.node_types.capacity(),
            self.self_weight.capacity(),
            self.relation_weight.capacity(),
            self.decoder.capacity(),
            self.bias.capacity(),
        ])
    }
}

struct GradientArena {
    encoded: Vec<[f32; HIDDEN]>,
    encoded_grad: Vec<[f32; HIDDEN]>,
    node_type_grad: Vec<f32>,
    self_grad: Vec<f32>,
    relation_grad: Vec<f32>,
    decoder_grad: Vec<f32>,
    bias_grad: Vec<f32>,
}

impl GradientArena {
    fn new(nodes: usize, node_types: usize, messages: usize, decoders: usize) -> Self {
        Self {
            encoded: vec![[0.0; HIDDEN]; nodes],
            encoded_grad: vec![[0.0; HIDDEN]; nodes],
            node_type_grad: vec![0.0; node_types * HIDDEN],
            self_grad: vec![0.0; MATRIX],
            relation_grad: vec![0.0; messages * MATRIX],
            decoder_grad: vec![0.0; decoders * HIDDEN],
            bias_grad: vec![0.0; decoders],
        }
    }

    fn clear(&mut self) {
        self.encoded_grad.fill([0.0; HIDDEN]);
        self.node_type_grad.fill(0.0);
        self.self_grad.fill(0.0);
        self.relation_grad.fill(0.0);
        self.decoder_grad.fill(0.0);
        self.bias_grad.fill(0.0);
    }

    fn bytes(&self) -> Result<u64, CandleTrainerError> {
        byte_sum([
            self.encoded.capacity() * HIDDEN,
            self.encoded_grad.capacity() * HIDDEN,
            self.node_type_grad.capacity(),
            self.self_grad.capacity(),
            self.relation_grad.capacity(),
            self.decoder_grad.capacity(),
            self.bias_grad.capacity(),
        ])
    }
}

fn train_epoch(
    weights: &mut Weights,
    arena: &mut GradientArena,
    staged: &RgcnStagedInput,
    config: CandleRgcnConfig,
) -> Result<(), CandleTrainerError> {
    encode(weights, arena, &staged.graph);
    arena.clear();
    decoder_backward(weights, arena, &staged.train)?;
    relu_backward(arena);
    encoder_backward(weights, arena, &staged.graph);
    update_regularized(
        &mut weights.node_types,
        &arena.node_type_grad,
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
        &mut weights.relation_weight,
        &arena.relation_grad,
        config.learning_rate,
        config.l2,
    );
    update_regularized(
        &mut weights.decoder,
        &arena.decoder_grad,
        config.learning_rate,
        config.l2,
    );
    update_plain(&mut weights.bias, &arena.bias_grad, config.learning_rate);
    if !weights_finite(weights) {
        return Err(CandleTrainerError::Contract("fused R-GCN finite weights"));
    }
    Ok(())
}

fn encode(weights: &Weights, arena: &mut GradientArena, graph: &RgcnGraphBatch) {
    arena.encoded.fill([0.0; HIDDEN]);
    for (node, node_type) in graph.node_types.iter().copied().enumerate() {
        transform_add(
            &mut arena.encoded[node],
            row(&weights.node_types, node_type as usize),
            &weights.self_weight,
            1.0,
        );
    }
    for (relation, batch) in graph.relation_batches.iter().enumerate() {
        let matrix = matrix(&weights.relation_weight, relation);
        for edge in 0..batch.sources.len() {
            let source_type = graph.node_types[batch.sources[edge] as usize] as usize;
            transform_add(
                &mut arena.encoded[batch.targets[edge] as usize],
                row(&weights.node_types, source_type),
                matrix,
                batch.normalizers[edge],
            );
        }
    }
    arena
        .encoded
        .iter_mut()
        .for_each(|row| row.iter_mut().for_each(|value| *value = value.max(0.0)));
}

fn decoder_backward(
    weights: &Weights,
    arena: &mut GradientArena,
    queries: &RgcnQueryBatch,
) -> Result<(), CandleTrainerError> {
    let inverse_examples = 1.0 / queries.labels.len() as f32;
    for index in 0..queries.labels.len() {
        let source_index = queries.sources[index] as usize;
        let target_index = queries.targets[index] as usize;
        let relation = queries.relations[index] as usize;
        let source = arena.encoded[source_index];
        let target = arena.encoded[target_index];
        let decoder = row(&weights.decoder, relation);
        let logit = simd_triple(&source, &target, decoder) + weights.bias[relation];
        let gradient = (sigmoid(logit) - f32::from(queries.labels[index])) * inverse_examples;
        add_scaled_product(
            row_mut(&mut arena.decoder_grad, relation),
            &source,
            &target,
            gradient,
        );
        arena.bias_grad[relation] += gradient;
        add_scaled_product(
            &mut arena.encoded_grad[source_index],
            &target,
            decoder,
            gradient,
        );
        add_scaled_product(
            &mut arena.encoded_grad[target_index],
            &source,
            decoder,
            gradient,
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

fn encoder_backward(weights: &Weights, arena: &mut GradientArena, graph: &RgcnGraphBatch) {
    for (node, node_type) in graph.node_types.iter().copied().enumerate() {
        transform_backward(
            row_mut(&mut arena.node_type_grad, node_type as usize),
            &mut arena.self_grad,
            &arena.encoded_grad[node],
            row(&weights.node_types, node_type as usize),
            &weights.self_weight,
            1.0,
        );
    }
    for (relation, batch) in graph.relation_batches.iter().enumerate() {
        let weights_matrix = matrix(&weights.relation_weight, relation);
        let gradient_matrix = matrix_mut(&mut arena.relation_grad, relation);
        for edge in 0..batch.sources.len() {
            let source_type = graph.node_types[batch.sources[edge] as usize] as usize;
            transform_backward(
                row_mut(&mut arena.node_type_grad, source_type),
                gradient_matrix,
                &arena.encoded_grad[batch.targets[edge] as usize],
                row(&weights.node_types, source_type),
                weights_matrix,
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

fn initialized(random: &mut SplitMix64, count: usize, scale: f32) -> Vec<f32> {
    (0..count).map(|_| random.signed_unit() * scale).collect()
}

fn weights_finite(weights: &Weights) -> bool {
    [
        &weights.node_types,
        &weights.self_weight,
        &weights.relation_weight,
        &weights.decoder,
        &weights.bias,
    ]
    .into_iter()
    .all(|values| values.iter().all(|value| value.is_finite()))
}

fn transform_add(target: &mut [f32; HIDDEN], input: &[f32], weights: &[f32], scale: f32) {
    for (output, value) in target.iter_mut().enumerate() {
        *value += simd_dot(&weights[output * HIDDEN..(output + 1) * HIDDEN], input) * scale;
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

fn byte_sum<const N: usize>(capacities: [usize; N]) -> Result<u64, CandleTrainerError> {
    capacities
        .into_iter()
        .try_fold(0_usize, usize::checked_add)
        .and_then(|value| value.checked_mul(size_of::<f32>()))
        .and_then(|value| u64::try_from(value).ok())
        .ok_or(CandleTrainerError::Contract("fused R-GCN byte count"))
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
        let exp = value.exp();
        exp / (1.0 + exp)
    }
}

fn validate(staged: &RgcnStagedInput, config: CandleRgcnConfig) -> Result<(), CandleTrainerError> {
    if config.epochs == 0
        || config.learning_rate <= 0.0
        || !config.learning_rate.is_finite()
        || config.l2 < 0.0
        || !config.l2.is_finite()
        || staged.graph.node_types.is_empty()
        || staged.graph.relation_batches.is_empty()
        || staged.graph.relation_count == 0
        || staged.train.labels.is_empty()
        || staged.train.sources.len() != staged.train.labels.len()
        || staged.train.targets.len() != staged.train.labels.len()
        || staged.train.relations.len() != staged.train.labels.len()
    {
        return Err(CandleTrainerError::Contract("fused R-GCN contract"));
    }
    Ok(())
}
