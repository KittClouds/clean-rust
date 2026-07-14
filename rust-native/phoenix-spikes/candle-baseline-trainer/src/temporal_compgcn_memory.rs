use crate::telemetry::{working_set_bytes, ThreadAllocationSnapshot};
use crate::CandleTrainerError;
use phoenix_graph_research::{
    TemporalCompgcnConfig, TemporalCompgcnWeights, TemporalComposition, TemporalRelationUpdate,
    TemporalRgcnStagedInput, TEMPORAL_COMPGCN_DIRECTIONS, TEMPORAL_COMPGCN_HIDDEN,
};
use std::time::Instant;
use wide::f32x8;

const HIDDEN: usize = TEMPORAL_COMPGCN_HIDDEN;
const MATRIX: usize = HIDDEN * HIDDEN;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct CompgcnTrainingProfile {
    pub parameter_bytes: u64,
    pub gradient_arena_bytes: u64,
    pub allocation_volume_bytes: u64,
    pub allocation_count: u64,
    pub epoch_allocation_volume_bytes: u64,
    pub epoch_allocation_count: u64,
    pub working_set_bytes: u64,
    pub relation_state_bytes: u64,
    pub composition_kernel_micros: u64,
}

pub(crate) struct CompgcnTrainingOutcome {
    pub weights: TemporalCompgcnWeights,
    pub profile: CompgcnTrainingProfile,
}

pub(crate) fn train_fused_temporal_compgcn16(
    staged: &TemporalRgcnStagedInput,
    config: TemporalCompgcnConfig,
) -> Result<CompgcnTrainingOutcome, CandleTrainerError> {
    validate_staged(staged, config)?;
    let allocations = ThreadAllocationSnapshot::now();
    let nodes = staged.graph.node_types.len();
    let relations = staged.graph.relation_batches.len();
    let mut weights = initialize_weights(config.base.seed, nodes, relations);
    let mut arena = GradientArena::new(nodes, relations);
    let parameter_bytes = weight_bytes(&weights)?;
    let gradient_arena_bytes = arena.bytes()?;
    let relation_state_bytes = u64::try_from((relations + 1) * HIDDEN * size_of::<f32>())
        .map_err(|_| CandleTrainerError::Contract("CompGCN relation bytes"))?;
    let epoch_allocations = ThreadAllocationSnapshot::now();
    let before_working_set = working_set_bytes()?;
    let mut composition_kernel_micros = 0_u64;
    for _ in 0..config.base.epochs {
        composition_kernel_micros = composition_kernel_micros.saturating_add(train_epoch(
            &mut weights,
            &mut arena,
            staged,
            config,
        )?);
    }
    let working_set_bytes = before_working_set.max(working_set_bytes()?);
    let epoch_delta = epoch_allocations.elapsed();
    let allocation_delta = allocations.elapsed();
    if epoch_delta.bytes != 0 || epoch_delta.count != 0 {
        return Err(CandleTrainerError::Contract(
            "CompGCN fused epoch allocated",
        ));
    }
    Ok(CompgcnTrainingOutcome {
        weights,
        profile: CompgcnTrainingProfile {
            parameter_bytes,
            gradient_arena_bytes,
            allocation_volume_bytes: allocation_delta.bytes,
            allocation_count: allocation_delta.count,
            epoch_allocation_volume_bytes: epoch_delta.bytes,
            epoch_allocation_count: epoch_delta.count,
            working_set_bytes,
            relation_state_bytes,
            composition_kernel_micros,
        },
    })
}

struct GradientArena {
    encoded: Vec<[f32; HIDDEN]>,
    relation_encoded: Vec<[f32; HIDDEN]>,
    encoded_grad: Vec<[f32; HIDDEN]>,
    relation_encoded_grad: Vec<[f32; HIDDEN]>,
    node_grad: Vec<f32>,
    direction_grad: Vec<f32>,
    relation_grad: Vec<f32>,
    projection_grad: Vec<f32>,
    bias_grad: Vec<f32>,
}

impl GradientArena {
    fn new(nodes: usize, relations: usize) -> Self {
        Self {
            encoded: vec![[0.0; HIDDEN]; nodes],
            relation_encoded: vec![[0.0; HIDDEN]; relations],
            encoded_grad: vec![[0.0; HIDDEN]; nodes],
            relation_encoded_grad: vec![[0.0; HIDDEN]; relations],
            node_grad: vec![0.0; nodes * HIDDEN],
            direction_grad: vec![0.0; TEMPORAL_COMPGCN_DIRECTIONS * MATRIX],
            relation_grad: vec![0.0; (relations + 1) * HIDDEN],
            projection_grad: vec![0.0; MATRIX],
            bias_grad: vec![0.0; relations],
        }
    }

    fn clear_gradients(&mut self) {
        self.encoded_grad.fill([0.0; HIDDEN]);
        self.relation_encoded_grad.fill([0.0; HIDDEN]);
        self.node_grad.fill(0.0);
        self.direction_grad.fill(0.0);
        self.relation_grad.fill(0.0);
        self.projection_grad.fill(0.0);
        self.bias_grad.fill(0.0);
    }

    fn bytes(&self) -> Result<u64, CandleTrainerError> {
        let elements = self
            .encoded
            .capacity()
            .checked_mul(HIDDEN)
            .and_then(|value| value.checked_add(self.relation_encoded.capacity() * HIDDEN))
            .and_then(|value| value.checked_add(self.encoded_grad.capacity() * HIDDEN))
            .and_then(|value| value.checked_add(self.relation_encoded_grad.capacity() * HIDDEN))
            .and_then(|value| value.checked_add(self.node_grad.capacity()))
            .and_then(|value| value.checked_add(self.direction_grad.capacity()))
            .and_then(|value| value.checked_add(self.relation_grad.capacity()))
            .and_then(|value| value.checked_add(self.projection_grad.capacity()))
            .and_then(|value| value.checked_add(self.bias_grad.capacity()))
            .ok_or(CandleTrainerError::Contract("CompGCN arena bytes"))?;
        u64::try_from(elements * size_of::<f32>())
            .map_err(|_| CandleTrainerError::Contract("CompGCN arena bytes"))
    }
}

fn train_epoch(
    weights: &mut TemporalCompgcnWeights,
    arena: &mut GradientArena,
    staged: &TemporalRgcnStagedInput,
    config: TemporalCompgcnConfig,
) -> Result<u64, CandleTrainerError> {
    let composition_started = Instant::now();
    encode(weights, arena, staged, config);
    let composition_micros = composition_started
        .elapsed()
        .as_micros()
        .try_into()
        .unwrap_or(u64::MAX);
    arena.clear_gradients();
    decoder_backward(weights, arena, staged)?;
    relation_decoder_backward(weights, arena, config);
    relu_backward(arena);
    encoder_backward(weights, arena, staged, config);
    sgd_update(weights, arena, config);
    if !weights_finite(weights) {
        return Err(CandleTrainerError::Contract("CompGCN non-finite weights"));
    }
    Ok(composition_micros)
}

fn encode(
    weights: &TemporalCompgcnWeights,
    arena: &mut GradientArena,
    staged: &TemporalRgcnStagedInput,
    config: TemporalCompgcnConfig,
) {
    arena.encoded.fill([0.0; HIDDEN]);
    let relations = staged.graph.relation_batches.len();
    let mut composed = [0.0; HIDDEN];
    let self_relation = row(&weights.relation_embeddings, relations);
    let self_matrix = matrix(&weights.direction_weights, 2);
    for node in 0..arena.encoded.len() {
        compose(
            &mut composed,
            row(&weights.node_embeddings, node),
            self_relation,
            config.composition,
        );
        transform_add(&mut arena.encoded[node], &composed, self_matrix, 1.0);
    }
    for (relation, batch) in staged.graph.relation_batches.iter().enumerate() {
        let direction = usize::from(relation >= staged.base_relation_count as usize);
        let direction_matrix = matrix(&weights.direction_weights, direction);
        let relation_state = row(&weights.relation_embeddings, relation);
        for edge in 0..batch.sources.len() {
            compose(
                &mut composed,
                row(&weights.node_embeddings, batch.sources[edge] as usize),
                relation_state,
                config.composition,
            );
            transform_add(
                &mut arena.encoded[batch.targets[edge] as usize],
                &composed,
                direction_matrix,
                batch.normalizers[edge],
            );
        }
    }
    for values in &mut arena.encoded {
        for value in values {
            *value = value.max(0.0);
        }
    }
    for relation in 0..relations {
        let state = row(&weights.relation_embeddings, relation);
        if config.relation_update == TemporalRelationUpdate::Frozen {
            arena.relation_encoded[relation].copy_from_slice(state);
        } else {
            arena.relation_encoded[relation] = [0.0; HIDDEN];
            transform_add(
                &mut arena.relation_encoded[relation],
                state,
                &weights.relation_projection,
                1.0,
            );
        }
    }
}

fn decoder_backward(
    weights: &TemporalCompgcnWeights,
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
        let decoder = &arena.relation_encoded[relation];
        let logit = simd_triple(source, target, decoder) + weights.decoder_bias[relation];
        let gradient = (sigmoid(logit) - f32::from(train.labels[index])) * inverse_examples;
        add_scaled_product(
            &mut arena.relation_encoded_grad[relation],
            source,
            target,
            gradient,
        );
        arena.bias_grad[relation] += gradient;
        add_scaled_product(
            &mut arena.encoded_grad[source_index],
            target,
            decoder,
            gradient,
        );
        add_scaled_product(
            &mut arena.encoded_grad[target_index],
            source,
            decoder,
            gradient,
        );
    }
    Ok(())
}

fn relation_decoder_backward(
    weights: &TemporalCompgcnWeights,
    arena: &mut GradientArena,
    config: TemporalCompgcnConfig,
) {
    for relation in 0..arena.relation_encoded.len() {
        if config.relation_update == TemporalRelationUpdate::Frozen {
            add_scaled(
                row_mut(&mut arena.relation_grad, relation),
                &arena.relation_encoded_grad[relation],
                1.0,
            );
        } else {
            transform_backward(
                row_mut(&mut arena.relation_grad, relation),
                &mut arena.projection_grad,
                &arena.relation_encoded_grad[relation],
                row(&weights.relation_embeddings, relation),
                &weights.relation_projection,
                1.0,
            );
        }
    }
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
    weights: &TemporalCompgcnWeights,
    arena: &mut GradientArena,
    staged: &TemporalRgcnStagedInput,
    config: TemporalCompgcnConfig,
) {
    let relations = staged.graph.relation_batches.len();
    let mut composed = [0.0; HIDDEN];
    let mut composed_grad = [0.0; HIDDEN];
    for node in 0..arena.encoded_grad.len() {
        let entity = row(&weights.node_embeddings, node);
        let relation = row(&weights.relation_embeddings, relations);
        compose(&mut composed, entity, relation, config.composition);
        composed_grad.fill(0.0);
        transform_backward(
            &mut composed_grad,
            matrix_mut(&mut arena.direction_grad, 2),
            &arena.encoded_grad[node],
            &composed,
            matrix(&weights.direction_weights, 2),
            1.0,
        );
        composition_backward(
            row_mut(&mut arena.node_grad, node),
            row_mut(&mut arena.relation_grad, relations),
            &composed_grad,
            entity,
            relation,
            config.composition,
        );
    }
    for (relation_index, batch) in staged.graph.relation_batches.iter().enumerate() {
        let direction = usize::from(relation_index >= staged.base_relation_count as usize);
        for edge in 0..batch.sources.len() {
            let source_index = batch.sources[edge] as usize;
            let entity = row(&weights.node_embeddings, source_index);
            let relation = row(&weights.relation_embeddings, relation_index);
            compose(&mut composed, entity, relation, config.composition);
            composed_grad.fill(0.0);
            transform_backward(
                &mut composed_grad,
                matrix_mut(&mut arena.direction_grad, direction),
                &arena.encoded_grad[batch.targets[edge] as usize],
                &composed,
                matrix(&weights.direction_weights, direction),
                batch.normalizers[edge],
            );
            composition_backward(
                row_mut(&mut arena.node_grad, source_index),
                row_mut(&mut arena.relation_grad, relation_index),
                &composed_grad,
                entity,
                relation,
                config.composition,
            );
        }
    }
}

fn composition_backward(
    entity_grad: &mut [f32],
    relation_grad: &mut [f32],
    output_grad: &[f32; HIDDEN],
    entity: &[f32],
    relation: &[f32],
    composition: TemporalComposition,
) {
    match composition {
        TemporalComposition::Multiply => {
            add_scaled_product(entity_grad, output_grad, relation, 1.0);
            add_scaled_product(relation_grad, output_grad, entity, 1.0);
        }
        TemporalComposition::Subtract => {
            add_scaled(entity_grad, output_grad, 1.0);
            add_scaled(relation_grad, output_grad, -1.0);
        }
        TemporalComposition::CircularCorrelation => {
            for feature in 0..HIDDEN {
                let mut entity_value = 0.0_f32;
                let mut relation_value = 0.0_f32;
                for shift in 0..HIDDEN {
                    entity_value += output_grad[shift] * relation[(feature + shift) % HIDDEN];
                    relation_value +=
                        output_grad[shift] * entity[(feature + HIDDEN - shift) % HIDDEN];
                }
                entity_grad[feature] += entity_value;
                relation_grad[feature] += relation_value;
            }
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
    weights: &mut TemporalCompgcnWeights,
    arena: &GradientArena,
    config: TemporalCompgcnConfig,
) {
    let rate = config.base.learning_rate;
    let l2 = config.base.l2;
    update_regularized(&mut weights.node_embeddings, &arena.node_grad, rate, l2);
    update_regularized(
        &mut weights.direction_weights,
        &arena.direction_grad,
        rate,
        l2,
    );
    if config.relation_update == TemporalRelationUpdate::JointLinear {
        update_regularized(
            &mut weights.relation_embeddings,
            &arena.relation_grad,
            rate,
            l2,
        );
        update_regularized(
            &mut weights.relation_projection,
            &arena.projection_grad,
            rate,
            l2,
        );
    }
    update_plain(&mut weights.decoder_bias, &arena.bias_grad, rate);
}

fn initialize_weights(seed: u64, nodes: usize, relations: usize) -> TemporalCompgcnWeights {
    let mut random = SplitMix64(seed ^ 0x434f_4d50_4743_4e01);
    let mut directions = initialized(&mut random, TEMPORAL_COMPGCN_DIRECTIONS * MATRIX, 0.02);
    for direction in 0..TEMPORAL_COMPGCN_DIRECTIONS {
        for diagonal in 0..HIDDEN {
            directions[direction * MATRIX + diagonal * HIDDEN + diagonal] += 1.0;
        }
    }
    let mut projection = initialized(&mut random, MATRIX, 0.01);
    for diagonal in 0..HIDDEN {
        projection[diagonal * HIDDEN + diagonal] += 1.0;
    }
    TemporalCompgcnWeights {
        node_embeddings: initialized(&mut random, nodes * HIDDEN, 0.2),
        direction_weights: directions,
        relation_embeddings: initialized(&mut random, (relations + 1) * HIDDEN, 0.2),
        relation_projection: projection,
        decoder_bias: vec![0.0; relations],
    }
}

fn validate_staged(
    staged: &TemporalRgcnStagedInput,
    config: TemporalCompgcnConfig,
) -> Result<(), CandleTrainerError> {
    config
        .validate()
        .map_err(|_| CandleTrainerError::Contract("CompGCN configuration"))?;
    let train = &staged.train;
    if config.base != staged.config
        || staged.graph.node_types.is_empty()
        || staged.graph.relation_batches.is_empty()
        || train.labels.is_empty()
        || train.sources.len() != train.labels.len()
        || train.targets.len() != train.labels.len()
        || train.relations.len() != train.labels.len()
    {
        return Err(CandleTrainerError::Contract("CompGCN staged shapes"));
    }
    Ok(())
}

fn weight_bytes(weights: &TemporalCompgcnWeights) -> Result<u64, CandleTrainerError> {
    let elements = weights
        .node_embeddings
        .capacity()
        .checked_add(weights.direction_weights.capacity())
        .and_then(|value| value.checked_add(weights.relation_embeddings.capacity()))
        .and_then(|value| value.checked_add(weights.relation_projection.capacity()))
        .and_then(|value| value.checked_add(weights.decoder_bias.capacity()))
        .ok_or(CandleTrainerError::Contract("CompGCN parameter bytes"))?;
    u64::try_from(elements * size_of::<f32>())
        .map_err(|_| CandleTrainerError::Contract("CompGCN parameter bytes"))
}

fn weights_finite(weights: &TemporalCompgcnWeights) -> bool {
    [
        &weights.node_embeddings,
        &weights.direction_weights,
        &weights.relation_embeddings,
        &weights.relation_projection,
        &weights.decoder_bias,
    ]
    .into_iter()
    .all(|values| values.iter().all(|value| value.is_finite()))
}

fn compose(
    output: &mut [f32; HIDDEN],
    entity: &[f32],
    relation: &[f32],
    composition: TemporalComposition,
) {
    match composition {
        TemporalComposition::Multiply => {
            for feature in 0..HIDDEN {
                output[feature] = entity[feature] * relation[feature];
            }
        }
        TemporalComposition::Subtract => {
            for feature in 0..HIDDEN {
                output[feature] = entity[feature] - relation[feature];
            }
        }
        TemporalComposition::CircularCorrelation => {
            for shift in 0..HIDDEN {
                let mut value = 0.0_f32;
                for feature in 0..HIDDEN {
                    value += entity[feature] * relation[(feature + shift) % HIDDEN];
                }
                output[shift] = value;
            }
        }
    }
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

fn initialized(random: &mut SplitMix64, count: usize, scale: f32) -> Vec<f32> {
    (0..count).map(|_| random.signed_unit() * scale).collect()
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
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }

    fn signed_unit(&mut self) -> f32 {
        let unit = (self.next() >> 40) as f32 / (1_u32 << 24) as f32;
        unit * 2.0 - 1.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn circular_correlation_backward_matches_central_difference() {
        let entity = std::array::from_fn::<_, HIDDEN, _>(|index| index as f32 / 17.0 - 0.3);
        let relation = std::array::from_fn::<_, HIDDEN, _>(|index| 0.2 - index as f32 / 31.0);
        let output_grad = std::array::from_fn::<_, HIDDEN, _>(|index| index as f32 / 23.0 - 0.1);
        let mut entity_grad = [0.0; HIDDEN];
        let mut relation_grad = [0.0; HIDDEN];
        composition_backward(
            &mut entity_grad,
            &mut relation_grad,
            &output_grad,
            &entity,
            &relation,
            TemporalComposition::CircularCorrelation,
        );
        let epsilon = 0.001_f32;
        let mut plus = entity;
        plus[4] += epsilon;
        let mut minus = entity;
        minus[4] -= epsilon;
        let numeric = (composition_loss(&plus, &relation, &output_grad)
            - composition_loss(&minus, &relation, &output_grad))
            / (2.0 * epsilon);
        assert!((entity_grad[4] - numeric).abs() < 0.001);
    }

    #[test]
    fn frozen_relation_arm_does_not_update_relation_states() {
        let mut weights = initialize_weights(7, 1, 2);
        let before = weights.relation_embeddings.clone();
        let mut arena = GradientArena::new(1, 2);
        arena.relation_grad.fill(1.0);
        arena.projection_grad.fill(1.0);
        let projection = weights.relation_projection.clone();
        let config = TemporalCompgcnConfig {
            relation_update: TemporalRelationUpdate::Frozen,
            ..TemporalCompgcnConfig::default()
        };
        sgd_update(&mut weights, &arena, config);
        assert_eq!(weights.relation_embeddings, before);
        assert_eq!(weights.relation_projection, projection);
    }

    fn composition_loss(entity: &[f32], relation: &[f32], gradient: &[f32]) -> f32 {
        let mut output = [0.0; HIDDEN];
        compose(
            &mut output,
            entity,
            relation,
            TemporalComposition::CircularCorrelation,
        );
        output.iter().zip(gradient).map(|(a, b)| a * b).sum()
    }
}
