use crate::DiscoveryRelationFamily;
use serde::{Deserialize, Serialize};
use std::mem::size_of;
use zerocopy::{AsBytes, FromBytes, FromZeroes, Unaligned};

pub const DISCOVERY_VIEW_SCHEMA: &str = "phoenix-asserted-discovery-view/v1";
pub(crate) const BINARY_SCHEMA_VERSION: u16 = 1;
pub(crate) const BINARY_MAGIC: [u8; 8] = *b"PHXADV01";
pub(crate) const BINARY_FILE: &str = "view.bin";
pub(crate) const MANIFEST_FILE: &str = "manifest.json";
pub(crate) const SECTION_COUNT: usize = 28;
pub(crate) const SECTION_ALIGNMENT: u64 = 64;

#[repr(u16)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub(crate) enum SectionKind {
    NodeStableHash = 1,
    NodeCollision = 2,
    NodeKind = 3,
    NodeEvidenceOffsets = 4,
    NodeEvidenceIndices = 5,
    EdgeStableHash = 6,
    EdgeCollision = 7,
    EdgeSource = 8,
    EdgeTarget = 9,
    EdgeRelation = 10,
    EdgeFamily = 11,
    EdgeConfidence = 12,
    EdgeTemporalIndex = 13,
    EdgeTemporalFlags = 14,
    EdgeValidFrom = 15,
    EdgeValidTo = 16,
    EdgeRecordedAt = 17,
    EdgeExpiredAt = 18,
    EdgeEvidenceOffsets = 19,
    EdgeEvidenceIndices = 20,
    EvidenceStableHash = 21,
    EvidenceCollision = 22,
    OutgoingOffsets = 23,
    OutgoingEdges = 24,
    IncomingOffsets = 25,
    IncomingEdges = 26,
    IdentityRefs = 27,
    IdentitySlab = 28,
}

impl SectionKind {
    pub(crate) const ALL: [Self; SECTION_COUNT] = [
        Self::NodeStableHash,
        Self::NodeCollision,
        Self::NodeKind,
        Self::NodeEvidenceOffsets,
        Self::NodeEvidenceIndices,
        Self::EdgeStableHash,
        Self::EdgeCollision,
        Self::EdgeSource,
        Self::EdgeTarget,
        Self::EdgeRelation,
        Self::EdgeFamily,
        Self::EdgeConfidence,
        Self::EdgeTemporalIndex,
        Self::EdgeTemporalFlags,
        Self::EdgeValidFrom,
        Self::EdgeValidTo,
        Self::EdgeRecordedAt,
        Self::EdgeExpiredAt,
        Self::EdgeEvidenceOffsets,
        Self::EdgeEvidenceIndices,
        Self::EvidenceStableHash,
        Self::EvidenceCollision,
        Self::OutgoingOffsets,
        Self::OutgoingEdges,
        Self::IncomingOffsets,
        Self::IncomingEdges,
        Self::IdentityRefs,
        Self::IdentitySlab,
    ];

    pub(crate) const fn code(self) -> u16 {
        self as u16
    }
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DiscoveryIdentityKind {
    Node = 1,
    Evidence = 2,
}

#[repr(u16)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DiscoveryNodeKind {
    Document = 1,
    Chunk = 2,
    Entity = 3,
    Alias = 4,
    Mention = 5,
    TimeAnchor = 6,
    CalendarAnchor = 7,
    Narrative = 8,
    Episode = 9,
    Memory = 10,
    Task = 11,
    State = 12,
    Event = 13,
    Generic = 14,
}

impl DiscoveryNodeKind {
    pub const fn code(self) -> u16 {
        self as u16
    }

    pub const fn from_code(code: u16) -> Option<Self> {
        match code {
            1 => Some(Self::Document),
            2 => Some(Self::Chunk),
            3 => Some(Self::Entity),
            4 => Some(Self::Alias),
            5 => Some(Self::Mention),
            6 => Some(Self::TimeAnchor),
            7 => Some(Self::CalendarAnchor),
            8 => Some(Self::Narrative),
            9 => Some(Self::Episode),
            10 => Some(Self::Memory),
            11 => Some(Self::Task),
            12 => Some(Self::State),
            13 => Some(Self::Event),
            14 => Some(Self::Generic),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveryRelationEntry {
    pub code: u16,
    pub relation: String,
    pub family: DiscoveryRelationFamily,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoverySectionManifest {
    pub kind: u16,
    pub offset: u64,
    pub count: u64,
    pub element_bytes: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveryViewManifest {
    pub schema_version: String,
    pub artifact_digest: String,
    pub payload_digest: String,
    pub generation: u64,
    pub source_snapshot_id: String,
    pub source_snapshot_digest: String,
    pub evidence_registry_digest: String,
    pub relation_policy_id: String,
    pub relation_policy_version: String,
    pub relation_policy_digest: String,
    pub node_count: u64,
    pub edge_count: u64,
    pub temporal_edge_count: u64,
    pub evidence_identity_count: u64,
    pub node_evidence_links: u64,
    pub edge_evidence_links: u64,
    pub excluded_candidate_edges: u64,
    pub admitted_candidate_edges: u64,
    pub binary_file: String,
    pub binary_bytes: u64,
    pub sections: Vec<DiscoverySectionManifest>,
    pub relations: Vec<DiscoveryRelationEntry>,
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct SectionHeader {
    pub kind: [u8; 2],
    pub element_bytes: [u8; 2],
    pub reserved: [u8; 4],
    pub offset: [u8; 8],
    pub count: [u8; 8],
    pub byte_len: [u8; 8],
}

impl SectionHeader {
    pub(crate) fn new(kind: SectionKind, element_bytes: usize, offset: u64, count: usize) -> Self {
        Self {
            kind: kind.code().to_le_bytes(),
            element_bytes: u16::try_from(element_bytes)
                .unwrap_or(u16::MAX)
                .to_le_bytes(),
            reserved: [0; 4],
            offset: offset.to_le_bytes(),
            count: u64::try_from(count).unwrap_or(u64::MAX).to_le_bytes(),
            byte_len: u64::try_from(element_bytes.saturating_mul(count))
                .unwrap_or(u64::MAX)
                .to_le_bytes(),
        }
    }

    pub(crate) fn kind(self) -> u16 {
        u16::from_le_bytes(self.kind)
    }
    pub(crate) fn element_bytes(self) -> u16 {
        u16::from_le_bytes(self.element_bytes)
    }
    pub(crate) fn offset(self) -> u64 {
        u64::from_le_bytes(self.offset)
    }
    pub(crate) fn count(self) -> u64 {
        u64::from_le_bytes(self.count)
    }
    pub(crate) fn byte_len(self) -> u64 {
        u64::from_le_bytes(self.byte_len)
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy)]
#[repr(C)]
pub(crate) struct BinaryHeader {
    pub magic: [u8; 8],
    pub schema_version: [u8; 2],
    pub section_count: [u8; 2],
    pub header_bytes: [u8; 4],
    pub generation: [u8; 8],
    pub node_count: [u8; 8],
    pub edge_count: [u8; 8],
    pub temporal_edge_count: [u8; 8],
    pub evidence_identity_count: [u8; 8],
    pub admitted_candidate_edges: [u8; 8],
    pub excluded_candidate_edges: [u8; 8],
    pub artifact_digest: [u8; 32],
    pub payload_digest: [u8; 32],
    pub source_snapshot_digest: [u8; 32],
    pub evidence_registry_digest: [u8; 32],
    pub policy_digest: [u8; 32],
    pub sections: [SectionHeader; SECTION_COUNT],
}

impl BinaryHeader {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        generation: u64,
        node_count: usize,
        edge_count: usize,
        temporal_edge_count: usize,
        evidence_identity_count: usize,
        excluded_candidate_edges: usize,
        artifact_digest: [u8; 32],
        payload_digest: [u8; 32],
        source_snapshot_digest: [u8; 32],
        evidence_registry_digest: [u8; 32],
        policy_digest: [u8; 32],
        sections: [SectionHeader; SECTION_COUNT],
    ) -> Self {
        Self {
            magic: BINARY_MAGIC,
            schema_version: BINARY_SCHEMA_VERSION.to_le_bytes(),
            section_count: (SECTION_COUNT as u16).to_le_bytes(),
            header_bytes: (size_of::<Self>() as u32).to_le_bytes(),
            generation: generation.to_le_bytes(),
            node_count: (node_count as u64).to_le_bytes(),
            edge_count: (edge_count as u64).to_le_bytes(),
            temporal_edge_count: (temporal_edge_count as u64).to_le_bytes(),
            evidence_identity_count: (evidence_identity_count as u64).to_le_bytes(),
            admitted_candidate_edges: 0_u64.to_le_bytes(),
            excluded_candidate_edges: (excluded_candidate_edges as u64).to_le_bytes(),
            artifact_digest,
            payload_digest,
            source_snapshot_digest,
            evidence_registry_digest,
            policy_digest,
            sections,
        }
    }
}

pub(crate) const BINARY_HEADER_BYTES: usize = size_of::<BinaryHeader>();

macro_rules! little_endian_value {
    ($name:ident, $primitive:ty, $size:expr, $from:ident) => {
        #[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
        #[repr(C)]
        pub(crate) struct $name(pub(crate) [u8; $size]);
        impl $name {
            pub(crate) fn new(value: $primitive) -> Self {
                Self(value.to_le_bytes())
            }
            pub(crate) fn get(self) -> $primitive {
                <$primitive>::$from(self.0)
            }
        }
    };
}

little_endian_value!(LeU16, u16, 2, from_le_bytes);
little_endian_value!(LeU32, u32, 4, from_le_bytes);
little_endian_value!(LeU64, u64, 8, from_le_bytes);
little_endian_value!(LeI64, i64, 8, from_le_bytes);

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct LeF32([u8; 4]);
impl LeF32 {
    pub(crate) fn new(value: f32) -> Self {
        Self(value.to_bits().to_le_bytes())
    }
    pub(crate) fn get(self) -> f32 {
        f32::from_bits(u32::from_le_bytes(self.0))
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct IdentityRefRecord {
    pub offset: [u8; 8],
    pub len: [u8; 4],
    pub reserved: [u8; 4],
}

impl IdentityRefRecord {
    pub(crate) fn new(offset: u64, len: u32) -> Self {
        Self {
            offset: offset.to_le_bytes(),
            len: len.to_le_bytes(),
            reserved: [0; 4],
        }
    }

    pub(crate) fn offset(self) -> u64 {
        u64::from_le_bytes(self.offset)
    }
    pub(crate) fn len(self) -> u32 {
        u32::from_le_bytes(self.len)
    }
}

pub(crate) fn hex(bytes: &[u8; 32]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

pub(crate) fn parse_hex(value: &str) -> Option<[u8; 32]> {
    if value.len() != 64 {
        return None;
    }
    let mut output = [0_u8; 32];
    for (index, byte) in output.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16).ok()?;
    }
    Some(output)
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn content_address(
    generation: u64,
    source_snapshot_id: &str,
    source_snapshot_digest: [u8; 32],
    evidence_registry_digest: [u8; 32],
    policy_digest: [u8; 32],
    payload_digest: [u8; 32],
    excluded_candidate_edges: u64,
    relations: &[DiscoveryRelationEntry],
) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix-asserted-discovery-view/v1\0");
    hasher.update(&generation.to_le_bytes());
    hasher.update(source_snapshot_id.as_bytes());
    hasher.update(&[0]);
    hasher.update(&source_snapshot_digest);
    hasher.update(&evidence_registry_digest);
    hasher.update(&policy_digest);
    hasher.update(&payload_digest);
    hasher.update(&excluded_candidate_edges.to_le_bytes());
    for relation in relations {
        hasher.update(&relation.code.to_le_bytes());
        hasher.update(&relation.family.code().to_le_bytes());
        hasher.update(relation.relation.as_bytes());
        hasher.update(&[0]);
    }
    *hasher.finalize().as_bytes()
}
