use crate::Result;

use super::validate;

/// Fixed-order scalar reference. Edge and feature iteration order is stable.
pub fn scalar_distmult_sum(
    offsets: &[u64],
    sources: &[u32],
    relation_ids: &[u32],
    input: &[f32],
    relations: &[f32],
    boundary: &[f32],
    dim: usize,
) -> Result<Vec<f32>> {
    let (nodes, _) = validate(
        offsets,
        sources,
        relation_ids,
        input,
        relations,
        boundary,
        dim,
    )?;
    let mut output = boundary.to_vec();
    for dst in 0..nodes {
        let output_row = &mut output[dst * dim..(dst + 1) * dim];
        for edge in offsets[dst] as usize..offsets[dst + 1] as usize {
            let source = sources[edge] as usize;
            let relation = relation_ids[edge] as usize;
            let source_row = &input[source * dim..(source + 1) * dim];
            let relation_row = &relations[relation * dim..(relation + 1) * dim];
            for feature in 0..dim {
                output_row[feature] += source_row[feature] * relation_row[feature];
            }
        }
    }
    Ok(output)
}
