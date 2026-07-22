use crate::temporal_rgcn::{finish_temporal_encoding, frequency_rows};
use crate::temporal_rgcn_artifact::TemporalLeF32;
use crate::{
    TemporalCompgcnConfig, TemporalCompgcnError, TemporalCompgcnMapped, TemporalCompgcnWeights,
    TemporalComposition, TemporalRelationUpdate, TemporalRgcnEncoded, TemporalRgcnStagedInput,
    TEMPORAL_COMPGCN_DIRECTIONS, TEMPORAL_COMPGCN_HIDDEN,
};
use compact_str::CompactString;
use zerocopy::Ref;

const HIDDEN: usize = TEMPORAL_COMPGCN_HIDDEN;
const MATRIX: usize = HIDDEN * HIDDEN;

pub fn encode_temporal_compgcn(
    model: &TemporalCompgcnMapped,
    staged: &TemporalRgcnStagedInput,
) -> Result<TemporalRgcnEncoded, TemporalCompgcnError> {
    let manifest = model.manifest();
    if manifest.source_dataset_id != staged.source_dataset_id
        || manifest.source_binary_blake3 != staged.source_binary_blake3
        || manifest.task_id != staged.task_id
        || manifest.task_binary_blake3 != staged.task_binary_blake3
        || manifest.candidate_universe as usize != staged.graph.node_types.len()
        || manifest.directed_relation_count as usize != staged.graph.relation_batches.len()
        || manifest.training.train_topology_blake3 != staged.profile.train_topology_blake3
        || manifest.config.base != staged.config
    {
        return Err(TemporalCompgcnError::InvalidContract("model source"));
    }
    let weights = TemporalCompgcnWeights {
        node_embeddings: values(model.node_embeddings()?),
        direction_weights: values(model.direction_weights()?),
        relation_embeddings: values(model.relation_embeddings()?),
        relation_projection: values(model.relation_projection()?),
        decoder_bias: values(model.decoder_bias()?),
    };
    encode_temporal_compgcn_weights(
        manifest.model_id.clone(),
        manifest.task_id.clone(),
        &weights,
        staged,
        manifest.config,
    )
}

pub fn encode_temporal_compgcn_weights(
    model_id: CompactString,
    task_id: CompactString,
    weights: &TemporalCompgcnWeights,
    staged: &TemporalRgcnStagedInput,
    config: TemporalCompgcnConfig,
) -> Result<TemporalRgcnEncoded, TemporalCompgcnError> {
    config.validate()?;
    if task_id != staged.task_id || config.base != staged.config {
        return Err(TemporalCompgcnError::InvalidContract("weight source"));
    }
    let nodes = staged.graph.node_types.len();
    let relations = staged.graph.relation_batches.len();
    if weights.node_embeddings.len() != nodes * HIDDEN
        || weights.direction_weights.len() != TEMPORAL_COMPGCN_DIRECTIONS * MATRIX
        || weights.relation_embeddings.len() != (relations + 1) * HIDDEN
        || weights.relation_projection.len() != MATRIX
        || weights.decoder_bias.len() != relations
    {
        return Err(TemporalCompgcnError::InvalidContract("weight shape"));
    }
    let mut encoded = vec![[0.0_f32; HIDDEN]; nodes];
    let mut composed = [0.0_f32; HIDDEN];
    let self_relation = row(&weights.relation_embeddings, relations);
    let self_matrix = matrix(&weights.direction_weights, 2);
    for (node, target) in encoded.iter_mut().enumerate() {
        compose(
            &mut composed,
            row(&weights.node_embeddings, node),
            self_relation,
            config.composition,
        );
        transform_add(target, &composed, self_matrix, 1.0);
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
                &mut encoded[batch.targets[edge] as usize],
                &composed,
                direction_matrix,
                batch.normalizers[edge],
            );
        }
    }
    encoded.iter_mut().for_each(|features| {
        features
            .iter_mut()
            .for_each(|value| *value = value.max(0.0));
    });
    let decoder = (0..relations)
        .map(|relation| {
            let source = row(&weights.relation_embeddings, relation);
            if config.relation_update == TemporalRelationUpdate::Frozen {
                <[f32; HIDDEN]>::try_from(source).expect("relation row")
            } else {
                let mut projected = [0.0_f32; HIDDEN];
                transform_add(&mut projected, source, &weights.relation_projection, 1.0);
                projected
            }
        })
        .collect();
    finish_temporal_encoding(
        model_id,
        task_id,
        encoded,
        decoder,
        weights.decoder_bias.clone(),
        config.base.residual_scale,
        frequency_rows(&staged.graph),
    )
    .map_err(TemporalCompgcnError::Control)
}

pub(crate) fn compose(
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

fn transform_add(target: &mut [f32; HIDDEN], source: &[f32], weights: &[f32], scale: f32) {
    for output in 0..HIDDEN {
        let row = &weights[output * HIDDEN..(output + 1) * HIDDEN];
        target[output] += row
            .iter()
            .zip(source)
            .map(|(weight, value)| weight * value)
            .sum::<f32>()
            * scale;
    }
}

fn row(values: &[f32], index: usize) -> &[f32] {
    &values[index * HIDDEN..(index + 1) * HIDDEN]
}

fn matrix(values: &[f32], index: usize) -> &[f32] {
    &values[index * MATRIX..(index + 1) * MATRIX]
}

fn values(values: Ref<&[u8], [TemporalLeF32]>) -> Vec<f32> {
    values.iter().copied().map(TemporalLeF32::get).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compositions_have_fixed_exact_operation_order() {
        let entity = std::array::from_fn::<_, HIDDEN, _>(|index| index as f32 + 0.25);
        let relation = std::array::from_fn::<_, HIDDEN, _>(|index| 2.0 - index as f32 * 0.125);
        let mut output = [0.0; HIDDEN];
        compose(
            &mut output,
            &entity,
            &relation,
            TemporalComposition::Multiply,
        );
        assert_eq!(output[5].to_bits(), (entity[5] * relation[5]).to_bits());
        compose(
            &mut output,
            &entity,
            &relation,
            TemporalComposition::Subtract,
        );
        assert_eq!(output[9].to_bits(), (entity[9] - relation[9]).to_bits());
        compose(
            &mut output,
            &entity,
            &relation,
            TemporalComposition::CircularCorrelation,
        );
        let mut reference = 0.0_f32;
        for feature in 0..HIDDEN {
            reference += entity[feature] * relation[(feature + 3) % HIDDEN];
        }
        assert_eq!(output[3].to_bits(), reference.to_bits());
    }
}
