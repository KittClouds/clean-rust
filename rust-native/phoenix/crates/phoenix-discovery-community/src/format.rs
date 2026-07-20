use serde::{Deserialize, Serialize};
use std::mem::size_of;
use zerocopy::{AsBytes, FromBytes, FromZeroes, Unaligned};

pub const COMMUNITY_ARTIFACT_SCHEMA: &str = "phoenix-deterministic-community-artifact/v2";
pub(crate) const BINARY_FILE: &str = "communities.bin";
pub(crate) const MANIFEST_FILE: &str = "manifest.json";
pub(crate) const BINARY_MAGIC: [u8; 8] = *b"PHXCOM01";
pub(crate) const BINARY_VERSION: u16 = 1;
pub(crate) const SECTION_COUNT: usize = 16;
pub(crate) const ALIGNMENT: u64 = 64;

#[repr(u16)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum SectionKind {
    NodeCommunity = 1,
    CommunityStableHash = 2,
    CommunityCollision = 3,
    CommunityComponent = 4,
    CommunitySize = 5,
    AffinityOffsets = 6,
    AffinityTargets = 7,
    AffinityWeights = 8,
    BridgeNodes = 9,
    BridgeNeighborCommunities = 10,
    BridgeTotalStrength = 11,
    BridgeBoundaryStrength = 12,
    BridgeParticipation = 13,
    BridgeBoundary = 14,
    BridgeConductance = 15,
    BridgeScore = 16,
}

impl SectionKind {
    pub(crate) const ALL: [Self; SECTION_COUNT] = [
        Self::NodeCommunity,
        Self::CommunityStableHash,
        Self::CommunityCollision,
        Self::CommunityComponent,
        Self::CommunitySize,
        Self::AffinityOffsets,
        Self::AffinityTargets,
        Self::AffinityWeights,
        Self::BridgeNodes,
        Self::BridgeNeighborCommunities,
        Self::BridgeTotalStrength,
        Self::BridgeBoundaryStrength,
        Self::BridgeParticipation,
        Self::BridgeBoundary,
        Self::BridgeConductance,
        Self::BridgeScore,
    ];

    pub(crate) const fn code(self) -> u16 {
        self as u16
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CommunitySectionManifest {
    pub kind: u16,
    pub offset: u64,
    pub count: u64,
    pub element_bytes: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CommunityArtifactManifest {
    pub schema_version: String,
    pub artifact_digest: String,
    pub payload_digest: String,
    pub source_discovery_digest: String,
    pub generation: u64,
    pub relation_policy_digest: String,
    pub community_policy_id: String,
    pub community_policy_version: String,
    pub community_policy_digest: String,
    pub node_count: u64,
    pub core_node_count: u64,
    pub selected_edge_count: u64,
    pub component_count: u64,
    pub community_count: u64,
    pub affinity_count: u64,
    pub bridge_count: u64,
    pub admitted_candidate_edges: u64,
    pub binary_file: String,
    pub binary_bytes: u64,
    pub sections: Vec<CommunitySectionManifest>,
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct SectionHeader {
    kind: [u8; 2],
    element_bytes: [u8; 2],
    reserved: [u8; 4],
    offset: [u8; 8],
    count: [u8; 8],
    byte_len: [u8; 8],
}

impl SectionHeader {
    pub(crate) fn new(kind: SectionKind, element_bytes: usize, offset: u64, count: usize) -> Self {
        Self {
            kind: kind.code().to_le_bytes(),
            element_bytes: (element_bytes as u16).to_le_bytes(),
            reserved: [0; 4],
            offset: offset.to_le_bytes(),
            count: (count as u64).to_le_bytes(),
            byte_len: (element_bytes as u64 * count as u64).to_le_bytes(),
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
    magic: [u8; 8],
    version: [u8; 2],
    section_count: [u8; 2],
    header_bytes: [u8; 4],
    generation: [u8; 8],
    node_count: [u8; 8],
    core_node_count: [u8; 8],
    selected_edge_count: [u8; 8],
    component_count: [u8; 8],
    community_count: [u8; 8],
    affinity_count: [u8; 8],
    bridge_count: [u8; 8],
    admitted_candidate_edges: [u8; 8],
    artifact_digest: [u8; 32],
    payload_digest: [u8; 32],
    source_discovery_digest: [u8; 32],
    relation_policy_digest: [u8; 32],
    community_policy_digest: [u8; 32],
    sections: [SectionHeader; SECTION_COUNT],
}

impl BinaryHeader {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        generation: u64,
        node_count: usize,
        core_node_count: usize,
        selected_edge_count: usize,
        component_count: usize,
        community_count: usize,
        affinity_count: usize,
        bridge_count: usize,
        artifact_digest: [u8; 32],
        payload_digest: [u8; 32],
        source_discovery_digest: [u8; 32],
        relation_policy_digest: [u8; 32],
        community_policy_digest: [u8; 32],
        sections: [SectionHeader; SECTION_COUNT],
    ) -> Self {
        Self {
            magic: BINARY_MAGIC,
            version: BINARY_VERSION.to_le_bytes(),
            section_count: (SECTION_COUNT as u16).to_le_bytes(),
            header_bytes: (size_of::<Self>() as u32).to_le_bytes(),
            generation: generation.to_le_bytes(),
            node_count: (node_count as u64).to_le_bytes(),
            core_node_count: (core_node_count as u64).to_le_bytes(),
            selected_edge_count: (selected_edge_count as u64).to_le_bytes(),
            component_count: (component_count as u64).to_le_bytes(),
            community_count: (community_count as u64).to_le_bytes(),
            affinity_count: (affinity_count as u64).to_le_bytes(),
            bridge_count: (bridge_count as u64).to_le_bytes(),
            admitted_candidate_edges: 0_u64.to_le_bytes(),
            artifact_digest,
            payload_digest,
            source_discovery_digest,
            relation_policy_digest,
            community_policy_digest,
            sections,
        }
    }

    pub(crate) fn magic(&self) -> [u8; 8] {
        self.magic
    }
    pub(crate) fn version(&self) -> u16 {
        u16::from_le_bytes(self.version)
    }
    pub(crate) fn section_count(&self) -> u16 {
        u16::from_le_bytes(self.section_count)
    }
    pub(crate) fn header_bytes(&self) -> u32 {
        u32::from_le_bytes(self.header_bytes)
    }
    pub(crate) fn generation(&self) -> u64 {
        u64::from_le_bytes(self.generation)
    }
    pub(crate) fn counts(&self) -> [u64; 7] {
        [
            u64::from_le_bytes(self.node_count),
            u64::from_le_bytes(self.core_node_count),
            u64::from_le_bytes(self.selected_edge_count),
            u64::from_le_bytes(self.component_count),
            u64::from_le_bytes(self.community_count),
            u64::from_le_bytes(self.affinity_count),
            u64::from_le_bytes(self.bridge_count),
        ]
    }
    pub(crate) fn admitted_candidate_edges(&self) -> u64 {
        u64::from_le_bytes(self.admitted_candidate_edges)
    }
    pub(crate) fn artifact_digest(&self) -> [u8; 32] {
        self.artifact_digest
    }
    pub(crate) fn payload_digest(&self) -> [u8; 32] {
        self.payload_digest
    }
    pub(crate) fn source_discovery_digest(&self) -> [u8; 32] {
        self.source_discovery_digest
    }
    pub(crate) fn relation_policy_digest(&self) -> [u8; 32] {
        self.relation_policy_digest
    }
    pub(crate) fn community_policy_digest(&self) -> [u8; 32] {
        self.community_policy_digest
    }
    pub(crate) fn sections(&self) -> &[SectionHeader; SECTION_COUNT] {
        &self.sections
    }
}

pub(crate) const HEADER_BYTES: usize = size_of::<BinaryHeader>();

pub(crate) fn hex(bytes: &[u8; 32]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

pub(crate) fn parse_hex(value: &str) -> Option<[u8; 32]> {
    if value.len() != 64 {
        return None;
    }
    let mut bytes = [0_u8; 32];
    for (index, slot) in bytes.iter_mut().enumerate() {
        *slot = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16).ok()?;
    }
    Some(bytes)
}

pub(crate) fn content_address(
    generation: u64,
    source_digest: [u8; 32],
    relation_digest: [u8; 32],
    policy_digest: [u8; 32],
    payload_digest: [u8; 32],
    counts: [u64; 7],
) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix-deterministic-community-artifact/v1\0");
    hasher.update(&generation.to_le_bytes());
    hasher.update(&source_digest);
    hasher.update(&relation_digest);
    hasher.update(&policy_digest);
    hasher.update(&payload_digest);
    for count in counts {
        hasher.update(&count.to_le_bytes());
    }
    *hasher.finalize().as_bytes()
}
