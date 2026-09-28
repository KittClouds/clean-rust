use crate::{DiscoveryNodeKind, DiscoveryViewError};
use phoenix_graph_kernel::{KernelBiTemporal, KernelEdge, KernelVertexClass};

pub(crate) fn edge_key(edge: &KernelEdge) -> (&str, &str, &str) {
    (&edge.source_id.0, &edge.target_id.0, &edge.edge_type.0)
}

pub(crate) fn edge_confidence(edge: &KernelEdge) -> Result<f32, DiscoveryViewError> {
    let confidence = edge.provenance.confidence.unwrap_or(1.0);
    if !confidence.is_finite() || !(0.0..=1.0).contains(&confidence) {
        return Err(DiscoveryViewError::Invalid(format!(
            "asserted edge has invalid confidence: {} -> {} ({confidence})",
            edge.source_id.0, edge.target_id.0
        )));
    }
    Ok(confidence as f32)
}

pub(crate) fn temporal(value: KernelBiTemporal) -> Option<(u8, i64, i64, i64, i64)> {
    let mut flags = 0_u8;
    if value.valid_from.is_some() {
        flags |= 1;
    }
    if value.valid_to.is_some() {
        flags |= 2;
    }
    if value.recorded_at.is_some() {
        flags |= 4;
    }
    if value.expired_at.is_some() {
        flags |= 8;
    }
    (flags != 0).then_some((
        flags,
        value.valid_from.unwrap_or_default(),
        value.valid_to.unwrap_or_default(),
        value.recorded_at.unwrap_or_default(),
        value.expired_at.unwrap_or_default(),
    ))
}

pub(crate) fn vertex_kind_code(value: &KernelVertexClass) -> u16 {
    match value {
        KernelVertexClass::Document => DiscoveryNodeKind::Document,
        KernelVertexClass::Chunk => DiscoveryNodeKind::Chunk,
        KernelVertexClass::Entity => DiscoveryNodeKind::Entity,
        KernelVertexClass::Alias => DiscoveryNodeKind::Alias,
        KernelVertexClass::Mention => DiscoveryNodeKind::Mention,
        KernelVertexClass::TimeAnchor => DiscoveryNodeKind::TimeAnchor,
        KernelVertexClass::CalendarAnchor => DiscoveryNodeKind::CalendarAnchor,
        KernelVertexClass::Narrative => DiscoveryNodeKind::Narrative,
        KernelVertexClass::Episode => DiscoveryNodeKind::Episode,
        KernelVertexClass::Memory => DiscoveryNodeKind::Memory,
        KernelVertexClass::Task => DiscoveryNodeKind::Task,
        KernelVertexClass::State => DiscoveryNodeKind::State,
        KernelVertexClass::Event => DiscoveryNodeKind::Event,
        KernelVertexClass::Generic => DiscoveryNodeKind::Generic,
    }
    .code()
}
