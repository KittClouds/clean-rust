use crate::{
    AssertedDiscoveryView, DiscoveryIndexSlice, DiscoveryNodeKind, DiscoveryRelationFamily,
    DiscoveryViewError,
};
use phoenix_graph_kernel::{
    KernelBiTemporal, KernelEdge, KernelEdgeType, KernelGraphLayer, KernelProvenance,
    KernelRelationClass, KernelVertex, KernelVertexClass, KernelVertexId,
};

pub const DISCOVERY_SOURCE_PAGE_SIZE: usize = 4_096;

/// Bounded, repeatable access to one asserted graph generation.
///
/// Implementations must visit vertices by stable external identity and asserted
/// edges by `(source identity, target identity, relation identity)`. The writer
/// validates both orderings and fails closed instead of sorting rich records.
pub trait PagedAssertedDiscoverySource {
    fn generation(&self) -> Result<u64, DiscoveryViewError>;
    fn node_count(&self) -> Result<usize, DiscoveryViewError>;
    fn asserted_edge_count(&self) -> Result<usize, DiscoveryViewError>;
    fn candidate_edge_count(&self) -> Result<usize, DiscoveryViewError>;

    fn visit_nodes(
        &self,
        page_size: usize,
        visitor: &mut dyn FnMut(u64, &KernelVertex) -> Result<(), DiscoveryViewError>,
    ) -> Result<(), DiscoveryViewError>;

    fn visit_asserted_edges(
        &self,
        page_size: usize,
        visitor: &mut dyn FnMut(u64, u64, &KernelEdge) -> Result<(), DiscoveryViewError>,
    ) -> Result<(), DiscoveryViewError>;
}

impl PagedAssertedDiscoverySource for AssertedDiscoveryView {
    fn generation(&self) -> Result<u64, DiscoveryViewError> {
        Ok(self.manifest().generation)
    }

    fn node_count(&self) -> Result<usize, DiscoveryViewError> {
        Ok(self.node_count())
    }

    fn asserted_edge_count(&self) -> Result<usize, DiscoveryViewError> {
        Ok(self.edge_count())
    }

    fn candidate_edge_count(&self) -> Result<usize, DiscoveryViewError> {
        usize::try_from(self.manifest().excluded_candidate_edges).map_err(|_| {
            DiscoveryViewError::Invalid("candidate edge count exceeds usize capacity".to_owned())
        })
    }

    fn visit_nodes(
        &self,
        page_size: usize,
        visitor: &mut dyn FnMut(u64, &KernelVertex) -> Result<(), DiscoveryViewError>,
    ) -> Result<(), DiscoveryViewError> {
        for page_start in (0..self.node_count()).step_by(page_size.max(1)) {
            let page_end = page_start
                .saturating_add(page_size.max(1))
                .min(self.node_count());
            for index in page_start..page_end {
                let dense = u32::try_from(index).map_err(|_| {
                    DiscoveryViewError::Invalid("node dense identity exceeds u32".to_owned())
                })?;
                let vertex = KernelVertex {
                    id: KernelVertexId(self.node_external_id(dense)?.to_owned()),
                    class: kernel_vertex_class(self.node_kind(dense)?),
                    provenance: KernelProvenance {
                        evidence_refs: evidence_refs(self, self.node_evidence(dense)?)?,
                        ..Default::default()
                    },
                    ..Default::default()
                };
                visitor(index as u64 + 1, &vertex)?;
            }
        }
        Ok(())
    }

    fn visit_asserted_edges(
        &self,
        page_size: usize,
        visitor: &mut dyn FnMut(u64, u64, &KernelEdge) -> Result<(), DiscoveryViewError>,
    ) -> Result<(), DiscoveryViewError> {
        for page_start in (0..self.edge_count()).step_by(page_size.max(1)) {
            let page_end = page_start
                .saturating_add(page_size.max(1))
                .min(self.edge_count());
            for index in page_start..page_end {
                let dense = u32::try_from(index).map_err(|_| {
                    DiscoveryViewError::Invalid("edge dense identity exceeds u32".to_owned())
                })?;
                let packed = self.edge(dense)?;
                let relation = self
                    .manifest()
                    .relations
                    .get(packed.relation_code as usize)
                    .ok_or_else(|| {
                        DiscoveryViewError::Invalid(format!(
                            "edge relation code {} is missing",
                            packed.relation_code
                        ))
                    })?;
                let edge = KernelEdge {
                    source_id: KernelVertexId(self.node_external_id(packed.source)?.to_owned()),
                    target_id: KernelVertexId(self.node_external_id(packed.target)?.to_owned()),
                    edge_type: KernelEdgeType(relation.relation.clone()),
                    relation_class: kernel_relation_class(packed.family),
                    layer: KernelGraphLayer::Asserted,
                    temporal: KernelBiTemporal {
                        valid_from: packed.temporal.valid_from,
                        valid_to: packed.temporal.valid_to,
                        recorded_at: packed.temporal.recorded_at,
                        expired_at: packed.temporal.expired_at,
                    },
                    provenance: KernelProvenance {
                        confidence: Some(packed.confidence as f64),
                        evidence_refs: evidence_refs(self, self.edge_evidence(dense)?)?,
                        ..Default::default()
                    },
                    ..Default::default()
                };
                visitor(packed.source as u64 + 1, packed.target as u64 + 1, &edge)?;
            }
        }
        Ok(())
    }
}

fn evidence_refs(
    source: &AssertedDiscoveryView,
    indices: DiscoveryIndexSlice<'_>,
) -> Result<Vec<String>, DiscoveryViewError> {
    indices
        .iter()
        .map(|index| source.evidence_external_id(index).map(str::to_owned))
        .collect()
}

fn kernel_vertex_class(kind: DiscoveryNodeKind) -> KernelVertexClass {
    match kind {
        DiscoveryNodeKind::Document => KernelVertexClass::Document,
        DiscoveryNodeKind::Chunk => KernelVertexClass::Chunk,
        DiscoveryNodeKind::Entity => KernelVertexClass::Entity,
        DiscoveryNodeKind::Alias => KernelVertexClass::Alias,
        DiscoveryNodeKind::Mention => KernelVertexClass::Mention,
        DiscoveryNodeKind::TimeAnchor => KernelVertexClass::TimeAnchor,
        DiscoveryNodeKind::CalendarAnchor => KernelVertexClass::CalendarAnchor,
        DiscoveryNodeKind::Narrative => KernelVertexClass::Narrative,
        DiscoveryNodeKind::Episode => KernelVertexClass::Episode,
        DiscoveryNodeKind::Memory => KernelVertexClass::Memory,
        DiscoveryNodeKind::Task => KernelVertexClass::Task,
        DiscoveryNodeKind::State => KernelVertexClass::State,
        DiscoveryNodeKind::Event => KernelVertexClass::Event,
        DiscoveryNodeKind::Generic => KernelVertexClass::Generic,
    }
}

fn kernel_relation_class(family: DiscoveryRelationFamily) -> KernelRelationClass {
    match family {
        DiscoveryRelationFamily::Structural => KernelRelationClass::Structural,
        DiscoveryRelationFamily::Semantic => KernelRelationClass::Semantic,
        DiscoveryRelationFamily::Identity => KernelRelationClass::Identity,
        DiscoveryRelationFamily::Resolution => KernelRelationClass::Resolution,
        DiscoveryRelationFamily::Temporal => KernelRelationClass::Temporal,
        DiscoveryRelationFamily::Calendar => KernelRelationClass::Calendar,
        DiscoveryRelationFamily::Memory => KernelRelationClass::Memory,
        DiscoveryRelationFamily::Narrative => KernelRelationClass::Narrative,
        DiscoveryRelationFamily::Custom => KernelRelationClass::Custom,
    }
}
