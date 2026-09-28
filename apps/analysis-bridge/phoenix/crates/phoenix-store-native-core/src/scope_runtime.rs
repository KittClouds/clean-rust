use std::collections::BTreeMap;
use std::sync::Arc;

use phoenix_semantic_v2::{
    CausalScopeSidecar, DirtyScopeRecord, DocumentArchive, DocumentManifest, DocumentSegmentKind,
    ErScopePatchSidecar, EventIdentityScopeSidecar, GraphScopeSidecar, MemoryScopeSidecar,
    RelationMentionSeedScopeSidecar, RelationScopePatchSidecar, ScopeLexSidecar,
    SemanticGraphScopeSidecar, StateSchemaScopeSidecar, TemporalScopeSidecar,
};
use phoenix_types::ScopeKey;
use serde::{Deserialize, Serialize};

use crate::StoreError;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct ArchiveSegmentMask {
    bits: u32,
}

impl ArchiveSegmentMask {
    pub fn empty() -> Self {
        Self { bits: 0 }
    }

    pub fn post_ingest_runtime() -> Self {
        Self::empty()
            .with_kind(DocumentSegmentKind::SentenceTable)
            .with_kind(DocumentSegmentKind::MentionTable)
            .with_kind(DocumentSegmentKind::ResolvedMentionTable)
            .with_kind(DocumentSegmentKind::ChunkTable)
            .with_kind(DocumentSegmentKind::EntityTable)
            .with_kind(DocumentSegmentKind::RelationTable)
            .with_kind(DocumentSegmentKind::NarrativeHitTable)
    }

    pub fn late_sidecar_runtime() -> Self {
        Self::empty()
            .with_kind(DocumentSegmentKind::EntityTable)
            .with_kind(DocumentSegmentKind::RelationTable)
    }

    pub fn event_identity_runtime() -> Self {
        Self::empty()
            .with_kind(DocumentSegmentKind::EventIdentitySubstrateTable)
            .with_kind(DocumentSegmentKind::EntityTable)
    }

    pub fn temporal_runtime() -> Self {
        Self::empty().with_kind(DocumentSegmentKind::TemporalSubstrateTable)
    }

    pub fn causal_runtime() -> Self {
        Self::empty()
            .with_kind(DocumentSegmentKind::CausalSubstrateTable)
            .with_kind(DocumentSegmentKind::MentionTable)
            .with_kind(DocumentSegmentKind::ResolvedMentionTable)
    }

    pub fn graph_runtime() -> Self {
        Self::empty().with_kind(DocumentSegmentKind::CausalSubstrateTable)
    }

    pub fn continuity_runtime() -> Self {
        Self::post_ingest_runtime()
            .union(Self::event_identity_runtime())
            .union(Self::temporal_runtime())
            .union(Self::causal_runtime())
    }

    pub fn sidecar_continuity_runtime() -> Self {
        Self::continuity_runtime().union(Self::graph_runtime())
    }

    pub fn with_kind(mut self, kind: DocumentSegmentKind) -> Self {
        self.bits |= Self::kind_bit(kind);
        self
    }

    pub fn union(mut self, other: Self) -> Self {
        self.bits |= other.bits;
        self
    }

    pub fn contains(self, kind: DocumentSegmentKind) -> bool {
        self.bits & Self::kind_bit(kind) != 0
    }

    pub fn contains_all(self, other: Self) -> bool {
        (self.bits & other.bits) == other.bits
    }

    pub fn bit_count(self) -> u32 {
        self.bits.count_ones()
    }

    pub fn raw_bits(self) -> u32 {
        self.bits
    }

    pub fn is_empty(self) -> bool {
        self.bits == 0
    }

    fn kind_bit(kind: DocumentSegmentKind) -> u32 {
        1u32 << (kind.as_u8() as u32 - 1)
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct ScopeSidecarMask {
    bits: u16,
}

impl ScopeSidecarMask {
    const LEXICAL: u16 = 1 << 0;
    const ER: u16 = 1 << 1;
    const RELATION: u16 = 1 << 2;
    const MEMORY: u16 = 1 << 3;
    const EVENT_IDENTITY: u16 = 1 << 4;
    const STATE_SCHEMA: u16 = 1 << 5;
    const CAUSAL: u16 = 1 << 6;
    const TEMPORAL: u16 = 1 << 7;
    const GRAPH: u16 = 1 << 8;
    const SEMANTIC_GRAPH: u16 = 1 << 9;
    const RELATION_SEED: u16 = 1 << 10;

    pub fn empty() -> Self {
        Self { bits: 0 }
    }

    pub fn post_ingest_runtime() -> Self {
        Self::empty()
            .with_lexical()
            .with_er()
            .with_relation()
            .with_memory()
            .with_event_identity()
    }

    pub fn late_sidecar_runtime() -> Self {
        Self::empty()
            .with_lexical()
            .with_er()
            .with_relation()
            .with_memory()
            .with_event_identity()
    }

    pub fn event_identity_runtime() -> Self {
        Self::empty().with_er().with_event_identity()
    }

    pub fn temporal_runtime() -> Self {
        Self::empty().with_event_identity().with_temporal()
    }

    pub fn causal_runtime() -> Self {
        Self::empty()
            .with_er()
            .with_event_identity()
            .with_temporal()
            .with_causal()
    }

    pub fn graph_runtime() -> Self {
        Self::empty()
            .with_event_identity()
            .with_temporal()
            .with_causal()
            .with_memory()
            .with_graph()
    }

    pub fn continuity_runtime() -> Self {
        Self::post_ingest_runtime()
            .with_state_schema()
            .with_temporal()
            .with_causal()
    }

    pub fn sidecar_continuity_runtime() -> Self {
        Self::continuity_runtime().with_graph()
    }

    pub fn with_lexical(mut self) -> Self {
        self.bits |= Self::LEXICAL;
        self
    }

    pub fn with_er(mut self) -> Self {
        self.bits |= Self::ER;
        self
    }

    pub fn with_relation(mut self) -> Self {
        self.bits |= Self::RELATION;
        self
    }

    pub fn with_memory(mut self) -> Self {
        self.bits |= Self::MEMORY;
        self
    }

    pub fn with_event_identity(mut self) -> Self {
        self.bits |= Self::EVENT_IDENTITY;
        self
    }

    pub fn with_state_schema(mut self) -> Self {
        self.bits |= Self::STATE_SCHEMA;
        self
    }

    pub fn with_causal(mut self) -> Self {
        self.bits |= Self::CAUSAL;
        self
    }

    pub fn with_temporal(mut self) -> Self {
        self.bits |= Self::TEMPORAL;
        self
    }

    pub fn with_graph(mut self) -> Self {
        self.bits |= Self::GRAPH;
        self
    }

    pub fn with_semantic_graph(mut self) -> Self {
        self.bits |= Self::SEMANTIC_GRAPH;
        self
    }

    pub fn with_relation_seed(mut self) -> Self {
        self.bits |= Self::RELATION_SEED;
        self
    }

    pub fn includes_lexical(self) -> bool {
        self.bits & Self::LEXICAL != 0
    }

    pub fn includes_er(self) -> bool {
        self.bits & Self::ER != 0
    }

    pub fn includes_relation(self) -> bool {
        self.bits & Self::RELATION != 0
    }

    pub fn includes_memory(self) -> bool {
        self.bits & Self::MEMORY != 0
    }

    pub fn includes_event_identity(self) -> bool {
        self.bits & Self::EVENT_IDENTITY != 0
    }

    pub fn includes_state_schema(self) -> bool {
        self.bits & Self::STATE_SCHEMA != 0
    }

    pub fn includes_causal(self) -> bool {
        self.bits & Self::CAUSAL != 0
    }

    pub fn includes_temporal(self) -> bool {
        self.bits & Self::TEMPORAL != 0
    }

    pub fn includes_graph(self) -> bool {
        self.bits & Self::GRAPH != 0
    }

    pub fn includes_semantic_graph(self) -> bool {
        self.bits & Self::SEMANTIC_GRAPH != 0
    }

    pub fn includes_relation_seed(self) -> bool {
        self.bits & Self::RELATION_SEED != 0
    }

    pub fn raw_bits(self) -> u16 {
        self.bits
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct ScopeImageSpec {
    pub archive_segments: ArchiveSegmentMask,
    pub sidecars: ScopeSidecarMask,
}

impl ScopeImageSpec {
    pub fn post_ingest() -> Self {
        Self {
            archive_segments: ArchiveSegmentMask::post_ingest_runtime(),
            sidecars: ScopeSidecarMask::post_ingest_runtime(),
        }
    }

    pub fn late_sidecars() -> Self {
        Self {
            archive_segments: ArchiveSegmentMask::late_sidecar_runtime(),
            sidecars: ScopeSidecarMask::late_sidecar_runtime(),
        }
    }

    pub fn event_identity() -> Self {
        Self {
            archive_segments: ArchiveSegmentMask::event_identity_runtime(),
            sidecars: ScopeSidecarMask::event_identity_runtime(),
        }
    }

    pub fn temporal() -> Self {
        Self {
            archive_segments: ArchiveSegmentMask::temporal_runtime(),
            sidecars: ScopeSidecarMask::temporal_runtime(),
        }
    }

    pub fn causal() -> Self {
        Self {
            archive_segments: ArchiveSegmentMask::causal_runtime(),
            sidecars: ScopeSidecarMask::causal_runtime(),
        }
    }

    pub fn graph() -> Self {
        Self {
            archive_segments: ArchiveSegmentMask::graph_runtime(),
            sidecars: ScopeSidecarMask::graph_runtime(),
        }
    }

    pub fn continuity() -> Self {
        Self {
            archive_segments: ArchiveSegmentMask::continuity_runtime(),
            sidecars: ScopeSidecarMask::continuity_runtime(),
        }
    }

    pub fn sidecar_continuity() -> Self {
        Self {
            archive_segments: ArchiveSegmentMask::sidecar_continuity_runtime(),
            sidecars: ScopeSidecarMask::sidecar_continuity_runtime(),
        }
    }

    pub fn with_archive_segments(mut self, archive_segments: ArchiveSegmentMask) -> Self {
        self.archive_segments = archive_segments;
        self
    }

    pub fn with_sidecars(mut self, sidecars: ScopeSidecarMask) -> Self {
        self.sidecars = sidecars;
        self
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct ScopeSidecarBundle {
    pub lexical: Option<ScopeLexSidecar>,
    pub er: Option<ErScopePatchSidecar>,
    pub relation: Option<RelationScopePatchSidecar>,
    pub memory: Option<MemoryScopeSidecar>,
    pub event_identity: Option<EventIdentityScopeSidecar>,
    pub state_schema: Option<StateSchemaScopeSidecar>,
    pub causal: Option<CausalScopeSidecar>,
    pub temporal: Option<TemporalScopeSidecar>,
    pub graph: Option<GraphScopeSidecar>,
    pub semantic_graph: Option<SemanticGraphScopeSidecar>,
    pub relation_seed: Option<RelationMentionSeedScopeSidecar>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScopeRuntimeIndices {
    pub document_ids: Arc<[String]>,
    pub document_created_at: BTreeMap<String, i64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ScopeRuntimeImage {
    pub dirty: DirtyScopeRecord,
    pub manifests: Arc<[DocumentManifest]>,
    pub archives: Arc<[DocumentArchive]>,
    pub sidecars: Arc<ScopeSidecarBundle>,
    pub indices: Arc<ScopeRuntimeIndices>,
    pub archive_segments: ArchiveSegmentMask,
    pub sidecar_mask: ScopeSidecarMask,
}

impl ScopeRuntimeImage {
    pub fn document_count(&self) -> usize {
        self.archives.len()
    }
}

pub trait PhoenixScopeRuntimeStore {
    fn load_scope_runtime_image(
        &self,
        dirty: &DirtyScopeRecord,
        spec: ScopeImageSpec,
    ) -> Result<ScopeRuntimeImage, StoreError>;

    fn load_scope_runtime_image_for_scope(
        &self,
        scope: &ScopeKey,
        spec: ScopeImageSpec,
    ) -> Result<Option<ScopeRuntimeImage>, StoreError>;

    fn load_scope_runtime_images(
        &self,
        spec: ScopeImageSpec,
    ) -> Result<Vec<ScopeRuntimeImage>, StoreError>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn continuity_runtime_routes_outline_ready_document_inputs() {
        let spec = ScopeImageSpec::continuity();

        for kind in [
            DocumentSegmentKind::SentenceTable,
            DocumentSegmentKind::MentionTable,
            DocumentSegmentKind::ResolvedMentionTable,
            DocumentSegmentKind::ChunkTable,
            DocumentSegmentKind::EntityTable,
            DocumentSegmentKind::RelationTable,
            DocumentSegmentKind::NarrativeHitTable,
            DocumentSegmentKind::EventIdentitySubstrateTable,
            DocumentSegmentKind::TemporalSubstrateTable,
            DocumentSegmentKind::CausalSubstrateTable,
        ] {
            assert!(
                spec.archive_segments.contains(kind),
                "continuity should load {kind:?}"
            );
        }
        assert!(spec.sidecars.includes_lexical());
        assert!(spec.sidecars.includes_er());
        assert!(spec.sidecars.includes_relation());
        assert!(spec.sidecars.includes_state_schema());
        assert!(spec.sidecars.includes_memory());
        assert!(spec.sidecars.includes_event_identity());
        assert!(spec.sidecars.includes_temporal());
        assert!(spec.sidecars.includes_causal());
        assert!(!spec.sidecars.includes_graph());
        assert!(!spec.sidecars.includes_semantic_graph());
    }

    #[test]
    fn sidecar_continuity_adds_graph_without_dropping_continuity_inputs() {
        let continuity = ScopeImageSpec::continuity();
        let sidecar_continuity = ScopeImageSpec::sidecar_continuity();

        assert!(sidecar_continuity
            .archive_segments
            .contains_all(continuity.archive_segments));
        assert_eq!(
            sidecar_continuity.archive_segments.raw_bits()
                & !continuity.archive_segments.raw_bits(),
            ArchiveSegmentMask::graph_runtime().raw_bits()
                & !continuity.archive_segments.raw_bits()
        );
        assert_eq!(
            sidecar_continuity.sidecars.raw_bits() & continuity.sidecars.raw_bits(),
            continuity.sidecars.raw_bits()
        );
        assert!(sidecar_continuity.sidecars.includes_graph());
        assert!(!sidecar_continuity.sidecars.includes_semantic_graph());
    }
}
