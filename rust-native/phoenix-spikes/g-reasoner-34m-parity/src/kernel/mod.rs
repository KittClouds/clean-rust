mod avx2;
mod scalar;

pub use avx2::{FastKernel, fast_distmult_sum};
pub use scalar::scalar_distmult_sum;

use crate::{GfmError, Result};

pub(crate) fn validate(
    offsets: &[u64],
    sources: &[u32],
    relation_ids: &[u32],
    input: &[f32],
    relations: &[f32],
    boundary: &[f32],
    dim: usize,
) -> Result<(usize, usize)> {
    if dim == 0 || offsets.is_empty() {
        return Err(GfmError::Shape(
            "kernel requires nodes and a nonzero dimension".into(),
        ));
    }
    let nodes = offsets.len() - 1;
    if sources.len() != relation_ids.len() || offsets[nodes] as usize != sources.len() {
        return Err(GfmError::Shape("CSR edge sections disagree".into()));
    }
    if input.len() != nodes * dim || boundary.len() != input.len() {
        return Err(GfmError::Shape(format!(
            "node state/boundary must be {nodes}x{dim}"
        )));
    }
    if !relations.len().is_multiple_of(dim) {
        return Err(GfmError::Shape(
            "relation state is not row-major R x D".into(),
        ));
    }
    let relation_count = relations.len() / dim;
    if sources.iter().any(|&source| source as usize >= nodes)
        || relation_ids
            .iter()
            .any(|&relation| relation as usize >= relation_count)
    {
        return Err(GfmError::Shape("CSR index exceeds tensor extent".into()));
    }
    Ok((nodes, relation_count))
}
