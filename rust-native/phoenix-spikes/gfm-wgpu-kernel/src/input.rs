use crate::GpuError;

pub const WORKGROUP_WIDTH: u32 = 128;

#[derive(Clone, Copy)]
pub struct DistMultInput<'a> {
    pub offsets: &'a [u64],
    pub sources: &'a [u32],
    pub relation_ids: &'a [u32],
    pub input: &'a [f32],
    pub relations: &'a [f32],
    pub boundary: &'a [f32],
    pub dim: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ValidatedDistMult {
    pub nodes: u32,
    pub edges: u32,
    pub relations: u32,
    pub dim: u32,
    pub resident_bytes: u64,
    pub readback_bytes: u64,
    pub scalar_fma_ops: u64,
}

impl DistMultInput<'_> {
    pub fn validate(&self) -> Result<ValidatedDistMult, GpuError> {
        if self.dim == 0 || self.offsets.len() < 2 {
            return Err(GpuError::Shape(
                "kernel requires at least one node and a nonzero dimension".to_owned(),
            ));
        }
        let nodes = self.offsets.len() - 1;
        let edges = self.sources.len();
        if edges != self.relation_ids.len() || self.offsets[nodes] != edges as u64 {
            return Err(GpuError::Shape("CSR edge sections disagree".to_owned()));
        }
        if self.offsets[0] != 0 || self.offsets.windows(2).any(|pair| pair[0] > pair[1]) {
            return Err(GpuError::Shape(
                "CSR offsets must begin at zero and be monotonic".to_owned(),
            ));
        }
        let node_values = nodes
            .checked_mul(self.dim)
            .ok_or_else(|| GpuError::Shape("node tensor extent overflow".to_owned()))?;
        if self.input.len() != node_values || self.boundary.len() != node_values {
            return Err(GpuError::Shape(format!(
                "node state and boundary must both be {nodes}x{}",
                self.dim
            )));
        }
        if self.relations.is_empty() || !self.relations.len().is_multiple_of(self.dim) {
            return Err(GpuError::Shape(
                "relation state must be a nonempty row-major R x D tensor".to_owned(),
            ));
        }
        let relations = self.relations.len() / self.dim;
        if self.sources.iter().any(|&source| source as usize >= nodes)
            || self
                .relation_ids
                .iter()
                .any(|&relation| relation as usize >= relations)
        {
            return Err(GpuError::Shape(
                "CSR source or relation identity exceeds tensor extent".to_owned(),
            ));
        }
        let nodes = u32::try_from(nodes).map_err(|_| {
            GpuError::Shape("node count exceeds portable u32 GPU extent".to_owned())
        })?;
        let edges = u32::try_from(edges).map_err(|_| {
            GpuError::Shape("edge count exceeds portable u32 GPU extent".to_owned())
        })?;
        let relations = u32::try_from(relations).map_err(|_| {
            GpuError::Shape("relation count exceeds portable u32 GPU extent".to_owned())
        })?;
        let dim = u32::try_from(self.dim).map_err(|_| {
            GpuError::Shape("embedding dimension exceeds portable u32 GPU extent".to_owned())
        })?;
        if self
            .offsets
            .iter()
            .any(|&offset| offset > u64::from(u32::MAX))
        {
            return Err(GpuError::Shape(
                "CSR offset exceeds portable u32 GPU extent".to_owned(),
            ));
        }

        let offsets_bytes = bytes(self.offsets.len(), size_of::<u32>())?;
        let edge_bytes = bytes(self.sources.len(), size_of::<u32>())?
            .checked_mul(2)
            .ok_or_else(|| GpuError::Shape("edge byte extent overflow".to_owned()))?;
        let input_bytes = bytes(self.input.len(), size_of::<f32>())?;
        let relation_bytes = bytes(self.relations.len(), size_of::<f32>())?;
        let boundary_bytes = bytes(self.boundary.len(), size_of::<f32>())?;
        let output_bytes = boundary_bytes;
        let resident_bytes = offsets_bytes
            .checked_add(edge_bytes)
            .and_then(|value| value.checked_add(input_bytes))
            .and_then(|value| value.checked_add(relation_bytes))
            .and_then(|value| value.checked_add(boundary_bytes))
            .and_then(|value| value.checked_add(output_bytes))
            .and_then(|value| value.checked_add(32))
            .ok_or_else(|| GpuError::Shape("resident byte extent overflow".to_owned()))?;
        let scalar_fma_ops = u64::from(edges)
            .checked_mul(u64::from(dim))
            .ok_or_else(|| GpuError::Shape("operation count overflow".to_owned()))?;
        Ok(ValidatedDistMult {
            nodes,
            edges,
            relations,
            dim,
            resident_bytes,
            readback_bytes: output_bytes,
            scalar_fma_ops,
        })
    }
}

fn bytes(count: usize, width: usize) -> Result<u64, GpuError> {
    let value = count
        .checked_mul(width)
        .ok_or_else(|| GpuError::Shape("byte extent overflow".to_owned()))?;
    u64::try_from(value).map_err(|_| GpuError::Shape("byte extent exceeds u64".to_owned()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validation_rejects_nonmonotonic_csr() {
        let input = DistMultInput {
            offsets: &[0, 2, 1],
            sources: &[0],
            relation_ids: &[0],
            input: &[1.0, 2.0],
            relations: &[1.0],
            boundary: &[0.0, 0.0],
            dim: 1,
        };
        assert!(
            input
                .validate()
                .unwrap_err()
                .to_string()
                .contains("monotonic")
        );
    }

    #[test]
    fn validation_accounts_for_persistent_and_readback_bytes() {
        let input = DistMultInput {
            offsets: &[0, 1, 1],
            sources: &[1],
            relation_ids: &[0],
            input: &[1.0, 2.0, 3.0, 4.0],
            relations: &[0.5, 0.25],
            boundary: &[0.0; 4],
            dim: 2,
        };
        let shape = input.validate().unwrap();
        assert_eq!(shape.scalar_fma_ops, 2);
        assert_eq!(shape.readback_bytes, 16);
        assert_eq!(shape.resident_bytes, 108);
    }
}
