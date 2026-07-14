use crate::hyper_encoder_examples::PreparedHyperExamples;
use crate::hyper_optimizer::{
    GradientBlockEconomics, HyperEpochEconomics, HyperGradientClipPolicy, HyperOptimizerConfig,
    HyperWeightDecaySemantics,
};
use crate::telemetry::ThreadAllocationSnapshot;
use crate::CandleTrainerError;
use phoenix_graph_research::{
    ExternalDatasetMapped, ExternalQualifierRecord, HyperEncoderMode, HyperEncoderStagedInput,
    HyperEncoderTrainingConfig, HyperEncoderWeights, HYPER_ENCODER_HIDDEN,
};

const HIDDEN: usize = HYPER_ENCODER_HIDDEN;

pub(crate) struct FusedHyperTrainingOutcome {
    pub weights: HyperEncoderWeights,
    pub gradient_arena_bytes: u64,
    pub epoch_allocation_bytes: u64,
    pub epoch_allocation_count: u64,
    pub optimizer_state_blake3: String,
    pub optimizer_steps: u64,
    pub final_epoch: HyperEpochEconomics,
}

pub(crate) fn train_fused_hyper_encoder16(
    source: &ExternalDatasetMapped,
    staged: &HyperEncoderStagedInput,
    examples: &PreparedHyperExamples,
    mode: HyperEncoderMode,
    config: HyperEncoderTrainingConfig,
    weights: HyperEncoderWeights,
) -> Result<FusedHyperTrainingOutcome, CandleTrainerError> {
    let optimizer = HyperOptimizerConfig::legacy(config, examples.len());
    train_fused_hyper_encoder16_with_optimizer(
        source, staged, examples, mode, config, optimizer, weights,
    )
}

pub(crate) fn train_fused_hyper_encoder16_with_optimizer(
    source: &ExternalDatasetMapped,
    staged: &HyperEncoderStagedInput,
    examples: &PreparedHyperExamples,
    mode: HyperEncoderMode,
    config: HyperEncoderTrainingConfig,
    optimizer: HyperOptimizerConfig,
    mut weights: HyperEncoderWeights,
) -> Result<FusedHyperTrainingOutcome, CandleTrainerError> {
    config.validate()?;
    optimizer.validate(examples.len())?;
    let mut arena = GradientArena::new(&weights);
    let gradient_arena_bytes = arena.bytes()?;
    let epoch_allocations = ThreadAllocationSnapshot::now();
    let mut final_epoch = None;
    let batch_size = optimizer.batch_size as usize;
    let mut optimizer_steps = 0_u64;
    let batch_context = TrainBatchContext {
        source,
        staged,
        examples,
        mode,
        optimizer,
    };
    for _ in 0..config.epochs {
        for start in (0..examples.len()).step_by(batch_size) {
            let end = (start + batch_size).min(examples.len());
            final_epoch = Some(train_batch(
                &batch_context,
                start,
                end,
                &mut weights,
                &mut arena,
            )?);
            optimizer_steps += 1;
        }
    }
    let epoch_delta = epoch_allocations.elapsed();
    if epoch_delta.bytes != 0 || epoch_delta.count != 0 {
        return Err(CandleTrainerError::Contract("hyper fused epoch allocated"));
    }
    Ok(FusedHyperTrainingOutcome {
        optimizer_state_blake3: weights_digest(&weights),
        optimizer_steps,
        weights,
        gradient_arena_bytes,
        epoch_allocation_bytes: epoch_delta.bytes,
        epoch_allocation_count: epoch_delta.count,
        final_epoch: final_epoch.ok_or(CandleTrainerError::Contract("hyper epoch economics"))?,
    })
}

struct GradientArena {
    encoded: Vec<[f32; HIDDEN]>,
    relation_encoded: Vec<[f32; HIDDEN]>,
    encoded_grad: Vec<[f32; HIDDEN]>,
    relation_encoded_grad: Vec<[f32; HIDDEN]>,
    node: Vec<f32>,
    direction: Vec<f32>,
    relation: Vec<f32>,
    relation_projection: Vec<f32>,
    qualifier_projection: Vec<f32>,
    bias: Vec<f32>,
}

impl GradientArena {
    fn new(weights: &HyperEncoderWeights) -> Self {
        let nodes = weights.node_embeddings.len() / HIDDEN;
        let relations = weights.decoder_bias.len();
        Self {
            encoded: vec![[0.0; HIDDEN]; nodes],
            relation_encoded: vec![[0.0; HIDDEN]; relations],
            encoded_grad: vec![[0.0; HIDDEN]; nodes],
            relation_encoded_grad: vec![[0.0; HIDDEN]; relations],
            node: vec![0.0; weights.node_embeddings.len()],
            direction: vec![0.0; weights.direction_weights.len()],
            relation: vec![0.0; weights.relation_embeddings.len()],
            relation_projection: vec![0.0; weights.relation_projection.len()],
            qualifier_projection: vec![0.0; weights.qualifier_projection.len()],
            bias: vec![0.0; weights.decoder_bias.len()],
        }
    }

    fn clear(&mut self) {
        self.encoded_grad.fill([0.0; HIDDEN]);
        self.relation_encoded_grad.fill([0.0; HIDDEN]);
        self.node.fill(0.0);
        self.direction.fill(0.0);
        self.relation.fill(0.0);
        self.relation_projection.fill(0.0);
        self.qualifier_projection.fill(0.0);
        self.bias.fill(0.0);
    }

    fn bytes(&self) -> Result<u64, CandleTrainerError> {
        let elements = self.node.capacity()
            + self.encoded.capacity() * HIDDEN
            + self.relation_encoded.capacity() * HIDDEN
            + self.encoded_grad.capacity() * HIDDEN
            + self.relation_encoded_grad.capacity() * HIDDEN
            + self.direction.capacity()
            + self.relation.capacity()
            + self.relation_projection.capacity()
            + self.qualifier_projection.capacity()
            + self.bias.capacity();
        u64::try_from(elements * size_of::<f32>())
            .map_err(|_| CandleTrainerError::Contract("hyper gradient arena bytes"))
    }
}

struct TrainBatchContext<'a> {
    source: &'a ExternalDatasetMapped,
    staged: &'a HyperEncoderStagedInput,
    examples: &'a PreparedHyperExamples,
    mode: HyperEncoderMode,
    optimizer: HyperOptimizerConfig,
}

fn train_batch(
    context: &TrainBatchContext<'_>,
    start: usize,
    end: usize,
    weights: &mut HyperEncoderWeights,
    gradients: &mut GradientArena,
) -> Result<HyperEpochEconomics, CandleTrainerError> {
    let source = context.source;
    let staged = context.staged;
    let examples = context.examples;
    let mode = context.mode;
    let optimizer = context.optimizer;
    let qualifiers = source.qualifiers()?;
    encode_graph(weights, gradients, staged, mode, &qualifiers);
    gradients.clear();
    let batch_examples = end - start;
    let gradient_multiplier = optimizer.gradient_multiplier(batch_examples);
    let mut qualifier_sum = [0.0; HIDDEN];
    let mut qualifier_state = [0.0; HIDDEN];
    let mut relation_state_grad = [0.0; HIDDEN];
    let mut qualifier_sum_grad = [0.0; HIDDEN];
    let mut binary_cross_entropy = 0.0_f64;
    for index in start..end {
        let source_node = examples.sources[index] as usize;
        let target_node = examples.targets[index] as usize;
        let relation = examples.relations[index] as usize;
        qualifier_sum.fill(0.0);
        if mode.uses_query_qualifiers() {
            accumulate_qualifiers(
                &mut qualifier_sum,
                &weights.node_embeddings,
                &weights.relation_embeddings,
                &qualifiers,
                refs_for(staged, mode),
                QualifierSpan::new(
                    examples.qualifier_offsets[index],
                    examples.qualifier_counts[index],
                ),
                mode,
            );
        }
        let mut relation_state = gradients.relation_encoded[relation];
        transform(
            &mut qualifier_state,
            &qualifier_sum,
            &weights.qualifier_projection,
        );
        for feature in 0..HIDDEN {
            relation_state[feature] += qualifier_state[feature];
        }
        let source_row = gradients.encoded[source_node];
        let target_row = gradients.encoded[target_node];
        let mut logit = weights.decoder_bias[relation];
        for feature in 0..HIDDEN {
            logit += source_row[feature] * target_row[feature] * relation_state[feature];
        }
        let gradient = (sigmoid(logit) - f32::from(examples.labels[index])) * gradient_multiplier;
        let probability = f64::from(sigmoid(logit)).clamp(f64::EPSILON, 1.0 - f64::EPSILON);
        binary_cross_entropy -= if examples.labels[index] {
            probability.ln()
        } else {
            (1.0 - probability).ln()
        };
        gradients.bias[relation] += gradient;
        relation_state_grad.fill(0.0);
        for feature in 0..HIDDEN {
            let source_value = source_row[feature];
            let target_value = target_row[feature];
            relation_state_grad[feature] = gradient * source_value * target_value;
            gradients.encoded_grad[source_node][feature] +=
                gradient * target_value * relation_state[feature];
            gradients.encoded_grad[target_node][feature] +=
                gradient * source_value * relation_state[feature];
            gradients.relation_encoded_grad[relation][feature] += relation_state_grad[feature];
        }
        if mode.uses_query_qualifiers() && mode.propagates_qualifier_gradients() {
            projection_input_backward(
                &mut qualifier_sum_grad,
                &mut gradients.qualifier_projection,
                &qualifier_sum,
                &weights.qualifier_projection,
                &relation_state_grad,
            );
            qualifiers_backward(
                &mut gradients.node,
                &mut gradients.relation,
                &weights.node_embeddings,
                &weights.relation_embeddings,
                &qualifiers,
                refs_for(staged, mode),
                examples.qualifier_offsets[index],
                examples.qualifier_counts[index],
                &qualifier_sum_grad,
                mode,
            );
        }
    }
    for relation in 0..gradients.relation_encoded.len() {
        projection_backward(
            &mut gradients.relation,
            &mut gradients.relation_projection,
            relation,
            row(&weights.relation_embeddings, relation),
            &weights.relation_projection,
            &gradients.relation_encoded_grad[relation],
        );
    }
    for node in 0..gradients.encoded.len() {
        for feature in 0..HIDDEN {
            if gradients.encoded[node][feature] <= 0.0 {
                gradients.encoded_grad[node][feature] = 0.0;
            }
        }
    }
    encoder_backward(weights, gradients, staged, mode, &qualifiers);
    let clip_scale = gradient_clip_scale(gradients, optimizer);
    let economics = HyperEpochEconomics {
        mean_binary_cross_entropy: binary_cross_entropy / batch_examples as f64,
        entity_embeddings: block_economics(
            &weights.node_embeddings,
            &gradients.node,
            optimizer,
            clip_scale,
        ),
        relation_embeddings: block_economics(
            &weights.relation_embeddings,
            &gradients.relation,
            optimizer,
            clip_scale,
        ),
        relation_projection: block_economics(
            &weights.relation_projection,
            &gradients.relation_projection,
            optimizer,
            clip_scale,
        ),
        qualifier_projection: block_economics(
            &weights.qualifier_projection,
            &gradients.qualifier_projection,
            optimizer,
            clip_scale,
        ),
        direction_matrices: block_economics(
            &weights.direction_weights,
            &gradients.direction,
            optimizer,
            clip_scale,
        ),
        decoder_bias: block_economics(
            &weights.decoder_bias,
            &gradients.bias,
            optimizer,
            clip_scale,
        ),
    };
    sgd(weights, gradients, optimizer, clip_scale);
    if !weights_finite(weights) {
        return Err(CandleTrainerError::Contract("hyper non-finite weights"));
    }
    Ok(economics)
}

fn block_economics(
    parameters: &[f32],
    gradients: &[f32],
    optimizer: HyperOptimizerConfig,
    clip_scale: f32,
) -> GradientBlockEconomics {
    let mut gradient_squared = 0.0_f64;
    let mut parameter_squared = 0.0_f64;
    let mut update_squared = 0.0_f64;
    let mut exactly_zero = 0_u64;
    for (&parameter, &gradient) in parameters.iter().zip(gradients) {
        let gradient = f64::from(gradient);
        let parameter = f64::from(parameter);
        let decay = if optimizer.weight_decay_semantics == HyperWeightDecaySemantics::None {
            0.0
        } else {
            f64::from(optimizer.weight_decay) * parameter
        };
        let update =
            f64::from(optimizer.learning_rate) * (gradient * f64::from(clip_scale) + decay);
        gradient_squared += gradient * gradient;
        parameter_squared += parameter * parameter;
        update_squared += update * update;
        exactly_zero += u64::from(gradient == 0.0);
    }
    let parameter_l2 = parameter_squared.sqrt();
    let update_l2 = update_squared.sqrt();
    GradientBlockEconomics {
        gradient_l2: gradient_squared.sqrt(),
        parameter_l2,
        update_l2,
        update_to_weight: if parameter_l2 == 0.0 {
            0.0
        } else {
            update_l2 / parameter_l2
        },
        exactly_zero_gradients: exactly_zero,
        parameters: parameters.len() as u64,
    }
}

fn encode_graph(
    weights: &HyperEncoderWeights,
    arena: &mut GradientArena,
    staged: &HyperEncoderStagedInput,
    mode: HyperEncoderMode,
    qualifiers: &[impl Qualifier],
) {
    arena.encoded.fill([0.0; HIDDEN]);
    let relations = staged.relation_batches.len();
    let mut composed = [0.0; HIDDEN];
    let mut qualifier_sum = [0.0; HIDDEN];
    let mut qualifier_state = [0.0; HIDDEN];
    for node in 0..arena.encoded.len() {
        multiply(
            &mut composed,
            row(&weights.node_embeddings, node),
            row(&weights.relation_embeddings, relations),
        );
        transform_add(
            &mut arena.encoded[node],
            &composed,
            matrix(&weights.direction_weights, 2),
            1.0,
        );
    }
    for (relation, batch) in staged.relation_batches.iter().enumerate() {
        let direction = usize::from(relation >= staged.base_relation_count as usize);
        for edge in 0..batch.sources.len() {
            let mut merged: [f32; HIDDEN] = row(&weights.relation_embeddings, relation)
                .try_into()
                .expect("relation row");
            if mode.uses_message_qualifiers() {
                qualifier_sum.fill(0.0);
                accumulate_qualifiers(
                    &mut qualifier_sum,
                    &weights.node_embeddings,
                    &weights.relation_embeddings,
                    qualifiers,
                    refs_for(staged, mode),
                    QualifierSpan::new(batch.qualifier_offsets[edge], batch.qualifier_counts[edge]),
                    mode,
                );
                transform(
                    &mut qualifier_state,
                    &qualifier_sum,
                    &weights.qualifier_projection,
                );
                for feature in 0..HIDDEN {
                    merged[feature] += qualifier_state[feature];
                }
            }
            multiply(
                &mut composed,
                row(&weights.node_embeddings, batch.sources[edge] as usize),
                &merged,
            );
            transform_add(
                &mut arena.encoded[batch.targets[edge] as usize],
                &composed,
                matrix(&weights.direction_weights, direction),
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
        transform(
            &mut arena.relation_encoded[relation],
            row(&weights.relation_embeddings, relation),
            &weights.relation_projection,
        );
    }
}

fn encoder_backward(
    weights: &HyperEncoderWeights,
    arena: &mut GradientArena,
    staged: &HyperEncoderStagedInput,
    mode: HyperEncoderMode,
    qualifiers: &[impl Qualifier],
) {
    let relations = staged.relation_batches.len();
    let mut qualifier_sum = [0.0; HIDDEN];
    let mut qualifier_state = [0.0; HIDDEN];
    let mut qualifier_sum_grad = [0.0; HIDDEN];
    let mut composed = [0.0; HIDDEN];
    let mut composed_grad = [0.0; HIDDEN];
    let mut merged_grad = [0.0; HIDDEN];
    for node in 0..arena.encoded.len() {
        multiply(
            &mut composed,
            row(&weights.node_embeddings, node),
            row(&weights.relation_embeddings, relations),
        );
        message_backward(
            &arena.encoded_grad[node],
            &composed,
            matrix(&weights.direction_weights, 2),
            matrix_mut(&mut arena.direction, 2),
            1.0,
            &mut composed_grad,
        );
        for (feature, gradient) in composed_grad.iter().copied().enumerate() {
            arena.node[node * HIDDEN + feature] +=
                gradient * weights.relation_embeddings[relations * HIDDEN + feature];
            arena.relation[relations * HIDDEN + feature] +=
                gradient * weights.node_embeddings[node * HIDDEN + feature];
        }
    }
    for (relation, batch) in staged.relation_batches.iter().enumerate() {
        let direction = usize::from(relation >= staged.base_relation_count as usize);
        for edge in 0..batch.sources.len() {
            let source = batch.sources[edge] as usize;
            let target = batch.targets[edge] as usize;
            let mut merged: [f32; HIDDEN] = row(&weights.relation_embeddings, relation)
                .try_into()
                .expect("relation row");
            qualifier_sum.fill(0.0);
            if mode.uses_message_qualifiers() {
                accumulate_qualifiers(
                    &mut qualifier_sum,
                    &weights.node_embeddings,
                    &weights.relation_embeddings,
                    qualifiers,
                    refs_for(staged, mode),
                    QualifierSpan::new(batch.qualifier_offsets[edge], batch.qualifier_counts[edge]),
                    mode,
                );
                transform(
                    &mut qualifier_state,
                    &qualifier_sum,
                    &weights.qualifier_projection,
                );
                for feature in 0..HIDDEN {
                    merged[feature] += qualifier_state[feature];
                }
            }
            multiply(
                &mut composed,
                row(&weights.node_embeddings, source),
                &merged,
            );
            message_backward(
                &arena.encoded_grad[target],
                &composed,
                matrix(&weights.direction_weights, direction),
                matrix_mut(&mut arena.direction, direction),
                batch.normalizers[edge],
                &mut composed_grad,
            );
            for feature in 0..HIDDEN {
                arena.node[source * HIDDEN + feature] += composed_grad[feature] * merged[feature];
                merged_grad[feature] =
                    composed_grad[feature] * weights.node_embeddings[source * HIDDEN + feature];
                arena.relation[relation * HIDDEN + feature] += merged_grad[feature];
            }
            if mode.uses_message_qualifiers() && mode.propagates_qualifier_gradients() {
                projection_input_backward(
                    &mut qualifier_sum_grad,
                    &mut arena.qualifier_projection,
                    &qualifier_sum,
                    &weights.qualifier_projection,
                    &merged_grad,
                );
                qualifiers_backward(
                    &mut arena.node,
                    &mut arena.relation,
                    &weights.node_embeddings,
                    &weights.relation_embeddings,
                    qualifiers,
                    refs_for(staged, mode),
                    batch.qualifier_offsets[edge],
                    batch.qualifier_counts[edge],
                    &qualifier_sum_grad,
                    mode,
                );
            }
        }
    }
}

fn message_backward(
    output_grad: &[f32; HIDDEN],
    input: &[f32; HIDDEN],
    matrix: &[f32],
    matrix_grad: &mut [f32],
    scale: f32,
    input_grad: &mut [f32; HIDDEN],
) {
    input_grad.fill(0.0);
    for target in 0..HIDDEN {
        for source in 0..HIDDEN {
            let gradient = output_grad[target] * scale;
            matrix_grad[target * HIDDEN + source] += gradient * input[source];
            input_grad[source] += gradient * matrix[target * HIDDEN + source];
        }
    }
}

fn projection_backward(
    relation_grad: &mut [f32],
    matrix_grad: &mut [f32],
    relation: usize,
    input: &[f32],
    matrix: &[f32],
    output_grad: &[f32; HIDDEN],
) {
    for target in 0..HIDDEN {
        for source in 0..HIDDEN {
            matrix_grad[target * HIDDEN + source] += output_grad[target] * input[source];
            relation_grad[relation * HIDDEN + source] +=
                output_grad[target] * matrix[target * HIDDEN + source];
        }
    }
}

fn projection_input_backward(
    input_grad: &mut [f32; HIDDEN],
    matrix_grad: &mut [f32],
    input: &[f32; HIDDEN],
    matrix: &[f32],
    output_grad: &[f32; HIDDEN],
) {
    input_grad.fill(0.0);
    for target in 0..HIDDEN {
        for source in 0..HIDDEN {
            matrix_grad[target * HIDDEN + source] += output_grad[target] * input[source];
            input_grad[source] += output_grad[target] * matrix[target * HIDDEN + source];
        }
    }
}

fn accumulate_qualifiers(
    sum: &mut [f32; HIDDEN],
    nodes: &[f32],
    relations: &[f32],
    qualifiers: &[impl Qualifier],
    refs: &[u32],
    span: QualifierSpan,
    mode: HyperEncoderMode,
) {
    for reference in &refs[span.offset as usize..(span.offset + span.count) as usize] {
        let qualifier = &qualifiers[*reference as usize];
        for feature in 0..HIDDEN {
            let entity = nodes[qualifier.object() as usize * HIDDEN + feature];
            let relation = relations[qualifier.predicate() as usize * HIDDEN + feature];
            sum[feature] += match mode {
                HyperEncoderMode::RoleOnly => relation,
                HyperEncoderMode::ValueOnly => entity,
                _ => entity * relation,
            };
        }
    }
}

#[derive(Clone, Copy)]
struct QualifierSpan {
    offset: u32,
    count: u32,
}

impl QualifierSpan {
    fn new(offset: u32, count: u32) -> Self {
        Self { offset, count }
    }
}

#[allow(clippy::too_many_arguments)]
fn qualifiers_backward(
    node_grad: &mut [f32],
    relation_grad: &mut [f32],
    nodes: &[f32],
    relations: &[f32],
    qualifiers: &[impl Qualifier],
    refs: &[u32],
    offset: u32,
    count: u32,
    sum_grad: &[f32; HIDDEN],
    mode: HyperEncoderMode,
) {
    for reference in &refs[offset as usize..(offset + count) as usize] {
        let qualifier = &qualifiers[*reference as usize];
        let node = qualifier.object() as usize;
        let relation = qualifier.predicate() as usize;
        for feature in 0..HIDDEN {
            if mode != HyperEncoderMode::RoleOnly {
                node_grad[node * HIDDEN + feature] += if mode == HyperEncoderMode::ValueOnly {
                    sum_grad[feature]
                } else {
                    sum_grad[feature] * relations[relation * HIDDEN + feature]
                };
            }
            if mode != HyperEncoderMode::ValueOnly {
                relation_grad[relation * HIDDEN + feature] += if mode == HyperEncoderMode::RoleOnly
                {
                    sum_grad[feature]
                } else {
                    sum_grad[feature] * nodes[node * HIDDEN + feature]
                };
            }
        }
    }
}

fn refs_for(staged: &HyperEncoderStagedInput, mode: HyperEncoderMode) -> &[u32] {
    if mode.uses_shuffled_qualifiers() {
        &staged.shuffled_qualifier_refs
    } else {
        &staged.canonical_qualifier_refs
    }
}

trait Qualifier {
    fn predicate(&self) -> u32;
    fn object(&self) -> u32;
}
impl Qualifier for ExternalQualifierRecord {
    fn predicate(&self) -> u32 {
        (*self).predicate()
    }
    fn object(&self) -> u32 {
        (*self).object()
    }
}

fn transform(output: &mut [f32; HIDDEN], input: &[f32], matrix: &[f32]) {
    output.fill(0.0);
    for target in 0..HIDDEN {
        for source in 0..HIDDEN {
            output[target] += input[source] * matrix[target * HIDDEN + source];
        }
    }
}
fn transform_add(output: &mut [f32; HIDDEN], input: &[f32; HIDDEN], weights: &[f32], scale: f32) {
    for target in 0..HIDDEN {
        let mut sum = 0.0;
        for source in 0..HIDDEN {
            sum += input[source] * weights[target * HIDDEN + source];
        }
        output[target] += sum * scale;
    }
}
fn multiply(output: &mut [f32; HIDDEN], left: &[f32], right: &[f32]) {
    for feature in 0..HIDDEN {
        output[feature] = left[feature] * right[feature];
    }
}
fn matrix(values: &[f32], index: usize) -> &[f32] {
    &values[index * HIDDEN * HIDDEN..(index + 1) * HIDDEN * HIDDEN]
}
fn matrix_mut(values: &mut [f32], index: usize) -> &mut [f32] {
    &mut values[index * HIDDEN * HIDDEN..(index + 1) * HIDDEN * HIDDEN]
}
fn row(values: &[f32], index: usize) -> &[f32] {
    &values[index * HIDDEN..(index + 1) * HIDDEN]
}
fn sigmoid(value: f32) -> f32 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let e = value.exp();
        e / (1.0 + e)
    }
}
#[rustfmt::skip]
fn sgd(weights: &mut HyperEncoderWeights, gradients: &GradientArena, optimizer: HyperOptimizerConfig, clip_scale: f32) {
    update(&mut weights.node_embeddings, &gradients.node, optimizer, clip_scale);
    update(&mut weights.direction_weights, &gradients.direction, optimizer, clip_scale);
    update(&mut weights.relation_embeddings, &gradients.relation, optimizer, clip_scale);
    update(&mut weights.relation_projection, &gradients.relation_projection, optimizer, clip_scale);
    update(&mut weights.qualifier_projection, &gradients.qualifier_projection, optimizer, clip_scale);
    update(&mut weights.decoder_bias, &gradients.bias, optimizer, clip_scale);
}
fn update(values: &mut [f32], gradients: &[f32], optimizer: HyperOptimizerConfig, clip_scale: f32) {
    for (value, gradient) in values.iter_mut().zip(gradients) {
        let gradient_step = optimizer.learning_rate * *gradient * clip_scale;
        match optimizer.weight_decay_semantics {
            HyperWeightDecaySemantics::None => *value -= gradient_step,
            HyperWeightDecaySemantics::CoupledL2 => {
                *value -= optimizer.learning_rate
                    * (*gradient * clip_scale + optimizer.weight_decay * *value);
            }
            HyperWeightDecaySemantics::Decoupled => {
                *value *= 1.0 - optimizer.learning_rate * optimizer.weight_decay;
                *value -= gradient_step;
            }
        }
    }
}

fn gradient_clip_scale(gradients: &GradientArena, optimizer: HyperOptimizerConfig) -> f32 {
    if optimizer.gradient_clip_policy == HyperGradientClipPolicy::None {
        return 1.0;
    }
    let mut squared = 0.0_f64;
    for values in [
        gradients.node.as_slice(),
        gradients.direction.as_slice(),
        gradients.relation.as_slice(),
        gradients.relation_projection.as_slice(),
        gradients.qualifier_projection.as_slice(),
        gradients.bias.as_slice(),
    ] {
        for &gradient in values {
            squared += f64::from(gradient) * f64::from(gradient);
        }
    }
    let norm = squared.sqrt() as f32;
    if norm <= optimizer.gradient_clip_norm {
        1.0
    } else {
        optimizer.gradient_clip_norm / norm
    }
}
#[rustfmt::skip]
fn weights_finite(weights: &HyperEncoderWeights) -> bool {
    [&weights.node_embeddings, &weights.direction_weights, &weights.relation_embeddings,
     &weights.relation_projection, &weights.qualifier_projection, &weights.decoder_bias]
        .into_iter().flatten().all(|value| value.is_finite())
}
#[rustfmt::skip]
fn weights_digest(weights: &HyperEncoderWeights) -> String {
    let mut h = blake3::Hasher::new();
    for tensor in [&weights.node_embeddings, &weights.direction_weights, &weights.relation_embeddings,
                   &weights.relation_projection, &weights.qualifier_projection, &weights.decoder_bias] {
        for value in tensor { h.update(&value.to_bits().to_le_bytes()); }
    }
    format!("b3-{}", h.finalize().to_hex())
}
