use crate::{GpuError, ResidentChainInput, TopKRecord};

#[derive(Clone, Debug, PartialEq)]
pub struct CpuChainOutput {
    pub hidden: Vec<f32>,
    pub logits: Vec<f32>,
    pub top_k: Vec<TopKRecord>,
}

pub fn cpu_resident_chain(input: ResidentChainInput<'_>) -> Result<CpuChainOutput, GpuError> {
    let shape = input.validate()?;
    let nodes = shape.nodes as usize;
    let dim = shape.dim as usize;
    let mut hidden = input.initial_hidden.to_vec();
    let mut aggregate = vec![0.0; hidden.len()];
    let mut update = vec![0.0; hidden.len()];
    let mut next = vec![0.0; hidden.len()];
    for layer in 0..shape.layers as usize {
        aggregate_distmult(&input, layer, &hidden, &mut aggregate, nodes, dim);
        dense_update(&input, layer, &hidden, &aggregate, &mut update, nodes, dim);
        normalize_residual(&input, layer, &hidden, &update, &mut next, nodes, dim);
        std::mem::swap(&mut hidden, &mut next);
    }
    let logits = score(&input, &hidden, nodes, dim, shape.score_dim as usize);
    let mut top_k = logits
        .iter()
        .enumerate()
        .map(|(node, &score)| TopKRecord {
            score: finite_score(score),
            node: node as u32,
        })
        .collect::<Vec<_>>();
    top_k.sort_unstable_by(|left, right| {
        right
            .score
            .total_cmp(&left.score)
            .then_with(|| left.node.cmp(&right.node))
    });
    top_k.truncate(shape.top_k as usize);
    Ok(CpuChainOutput {
        hidden,
        logits,
        top_k,
    })
}

fn aggregate_distmult(
    input: &ResidentChainInput<'_>,
    layer: usize,
    hidden: &[f32],
    output: &mut [f32],
    nodes: usize,
    dim: usize,
) {
    let relation_layer = layer * (input.layer_relations.len() / input.layers);
    for destination in 0..nodes {
        let row = destination * dim;
        output[row..row + dim].copy_from_slice(&input.boundary[row..row + dim]);
        for edge in input.offsets[destination] as usize..input.offsets[destination + 1] as usize {
            let source = input.sources[edge] as usize * dim;
            let relation = relation_layer + input.relation_ids[edge] as usize * dim;
            for axis in 0..dim {
                output[row + axis] = hidden[source + axis]
                    .mul_add(input.layer_relations[relation + axis], output[row + axis]);
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn dense_update(
    input: &ResidentChainInput<'_>,
    layer: usize,
    hidden: &[f32],
    aggregate: &[f32],
    output: &mut [f32],
    nodes: usize,
    dim: usize,
) {
    let matrix = layer * dim * dim;
    let bias = layer * dim;
    for node in 0..nodes {
        for out in 0..dim {
            let mut value = input.update_bias[bias + out];
            let weight = matrix + out * dim;
            let row = node * dim;
            for axis in 0..dim {
                value = hidden[row + axis].mul_add(input.old_weights[weight + axis], value);
                value =
                    aggregate[row + axis].mul_add(input.aggregate_weights[weight + axis], value);
            }
            output[row + out] = value;
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn normalize_residual(
    input: &ResidentChainInput<'_>,
    layer: usize,
    hidden: &[f32],
    update: &[f32],
    output: &mut [f32],
    nodes: usize,
    dim: usize,
) {
    let norm = layer * dim;
    for node in 0..nodes {
        let row = node * dim;
        let mean = update[row..row + dim].iter().copied().sum::<f32>() / dim as f32;
        let variance = update[row..row + dim]
            .iter()
            .map(|value| {
                let centered = *value - mean;
                centered * centered
            })
            .sum::<f32>()
            / dim as f32;
        let inverse_std = (variance + 1.0e-5).sqrt().recip();
        for axis in 0..dim {
            let normalized = (update[row + axis] - mean) * inverse_std;
            let activated = (normalized * input.norm_scale[norm + axis]
                + input.norm_bias[norm + axis])
                .max(0.0);
            output[row + axis] = activated + hidden[row + axis];
        }
    }
}

fn score(
    input: &ResidentChainInput<'_>,
    hidden: &[f32],
    nodes: usize,
    dim: usize,
    score_dim: usize,
) -> Vec<f32> {
    let mut logits = vec![0.0; nodes];
    for (node, logit) in logits.iter_mut().enumerate() {
        let row = node * dim;
        let mut score = input.scorer_output_bias;
        for out in 0..score_dim {
            let weight = out * dim;
            let mut activation = input.scorer_query_term[out] + input.scorer_bias[out];
            for axis in 0..dim {
                activation = hidden[row + axis]
                    .mul_add(input.scorer_hidden_weight[weight + axis], activation);
                if let (Some(entity), Some(entity_weight)) =
                    (input.scorer_entity, input.scorer_entity_weight)
                {
                    activation =
                        entity[row + axis].mul_add(entity_weight[weight + axis], activation);
                }
            }
            score = activation
                .max(0.0)
                .mul_add(input.scorer_output_weight[out], score);
        }
        *logit = score;
    }
    logits
}

fn finite_score(score: f32) -> f32 {
    if score.is_finite() {
        score
    } else {
        f32::NEG_INFINITY
    }
}
