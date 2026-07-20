use crate::format::{
    content_address, hex, parse_hex, BinaryHeader, CommunityArtifactManifest, SectionHeader,
    SectionKind, ALIGNMENT, BINARY_FILE, BINARY_MAGIC, BINARY_VERSION, COMMUNITY_ARTIFACT_SCHEMA,
    HEADER_BYTES, MANIFEST_FILE, SECTION_COUNT,
};
use crate::CommunityArtifactError;
use memmap2::{Mmap, MmapOptions};
use phoenix_discovery_view::DiscoveryStableId;
use std::fs::File;
use std::path::{Path, PathBuf};
use zerocopy::Ref;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BridgeMetricView {
    pub node: u32,
    pub neighboring_communities: u32,
    pub total_strength: u64,
    pub boundary_strength: u64,
    pub participation_micros: u32,
    pub boundary_micros: u32,
    pub conductance_micros: u32,
    pub score_micros: u32,
}

#[derive(Clone, Copy)]
pub struct SparseAffinitySlice<'a> {
    targets: &'a [u8],
    weights: &'a [u8],
}

impl<'a> SparseAffinitySlice<'a> {
    pub fn len(self) -> usize {
        self.targets.len() / 4
    }

    pub fn is_empty(self) -> bool {
        self.targets.is_empty()
    }

    pub fn get(self, index: usize) -> Option<(u32, u64)> {
        Some((
            read_u32(self.targets, index)?,
            read_u64(self.weights, index)?,
        ))
    }

    pub fn iter(self) -> impl ExactSizeIterator<Item = (u32, u64)> + 'a {
        self.targets
            .chunks_exact(4)
            .zip(self.weights.chunks_exact(8))
            .map(|(target, weight)| {
                (
                    u32::from_le_bytes(target.try_into().expect("four-byte target")),
                    u64::from_le_bytes(weight.try_into().expect("eight-byte weight")),
                )
            })
    }
}

pub struct DeterministicCommunityArtifact {
    root: PathBuf,
    manifest: CommunityArtifactManifest,
    map: Mmap,
    header: BinaryHeader,
}

impl DeterministicCommunityArtifact {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, CommunityArtifactError> {
        let root = root.as_ref().to_path_buf();
        let manifest: CommunityArtifactManifest =
            serde_json::from_slice(&std::fs::read(root.join(MANIFEST_FILE))?)?;
        validate_manifest(&root, &manifest)?;
        let file = File::open(root.join(BINARY_FILE))?;
        let map = unsafe { MmapOptions::new().map(&file)? };
        let header =
            *Ref::<_, BinaryHeader>::new_unaligned(map.get(..HEADER_BYTES).ok_or_else(|| {
                CommunityArtifactError::Invalid("community header is truncated".to_owned())
            })?)
            .ok_or_else(|| {
                CommunityArtifactError::Invalid("community header layout is invalid".to_owned())
            })?;
        validate_header(&manifest, &map, &header)?;
        Ok(Self {
            root,
            manifest,
            map,
            header,
        })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn manifest(&self) -> &CommunityArtifactManifest {
        &self.manifest
    }

    pub fn validate_payload(&self) -> Result<(), CommunityArtifactError> {
        let first = self.section(SectionKind::NodeCommunity)?.offset() as usize;
        let expected = required_digest(&self.manifest.payload_digest, "payload")?;
        let actual = blake3::hash(self.map.get(first..).ok_or_else(|| {
            CommunityArtifactError::Invalid("payload offset is outside mapping".to_owned())
        })?);
        if actual.as_bytes() != &expected {
            return Err(CommunityArtifactError::Invalid(
                "community payload digest mismatch".to_owned(),
            ));
        }
        validate_values(&self.manifest, &self.map, &self.header)
    }

    pub fn node_community(&self, node: u32) -> Result<Option<u32>, CommunityArtifactError> {
        let index = bounded(node, self.manifest.node_count, "node")?;
        let community = read_u32(self.section_bytes(SectionKind::NodeCommunity)?, index)
            .expect("validated node-community section");
        Ok((community != u32::MAX).then_some(community))
    }

    pub fn community_identity(
        &self,
        community: u32,
    ) -> Result<DiscoveryStableId, CommunityArtifactError> {
        let index = bounded(community, self.manifest.community_count, "community")?;
        Ok(DiscoveryStableId {
            hash: read_u64(self.section_bytes(SectionKind::CommunityStableHash)?, index)
                .expect("validated community hash section"),
            collision: read_u16(self.section_bytes(SectionKind::CommunityCollision)?, index)
                .expect("validated community collision section"),
        })
    }

    pub fn community_component(&self, community: u32) -> Result<u32, CommunityArtifactError> {
        self.community_u32(community, SectionKind::CommunityComponent)
    }

    pub fn community_size(&self, community: u32) -> Result<u32, CommunityArtifactError> {
        self.community_u32(community, SectionKind::CommunitySize)
    }

    pub fn affinities(
        &self,
        community: u32,
    ) -> Result<SparseAffinitySlice<'_>, CommunityArtifactError> {
        let index = bounded(community, self.manifest.community_count, "community")?;
        let offsets = self.section_bytes(SectionKind::AffinityOffsets)?;
        let start = read_u64(offsets, index).expect("validated affinity offset") as usize;
        let end = read_u64(offsets, index + 1).expect("validated affinity offset") as usize;
        Ok(SparseAffinitySlice {
            targets: byte_range(
                self.section_bytes(SectionKind::AffinityTargets)?,
                start,
                end,
                4,
            )?,
            weights: byte_range(
                self.section_bytes(SectionKind::AffinityWeights)?,
                start,
                end,
                8,
            )?,
        })
    }

    pub fn bridge(&self, bridge: u32) -> Result<BridgeMetricView, CommunityArtifactError> {
        let index = bounded(bridge, self.manifest.bridge_count, "bridge")?;
        Ok(BridgeMetricView {
            node: self.value_u32(SectionKind::BridgeNodes, index)?,
            neighboring_communities: self
                .value_u32(SectionKind::BridgeNeighborCommunities, index)?,
            total_strength: self.value_u64(SectionKind::BridgeTotalStrength, index)?,
            boundary_strength: self.value_u64(SectionKind::BridgeBoundaryStrength, index)?,
            participation_micros: self.value_u32(SectionKind::BridgeParticipation, index)?,
            boundary_micros: self.value_u32(SectionKind::BridgeBoundary, index)?,
            conductance_micros: self.value_u32(SectionKind::BridgeConductance, index)?,
            score_micros: self.value_u32(SectionKind::BridgeScore, index)?,
        })
    }

    pub fn bridge_for_node(
        &self,
        node: u32,
    ) -> Result<Option<BridgeMetricView>, CommunityArtifactError> {
        bounded(node, self.manifest.node_count, "node")?;
        let mut low = 0_u32;
        let mut high = self.manifest.bridge_count as u32;
        while low < high {
            let middle = low + (high - low) / 2;
            let row = self.bridge(middle)?;
            match row.node.cmp(&node) {
                std::cmp::Ordering::Less => low = middle + 1,
                std::cmp::Ordering::Greater => high = middle,
                std::cmp::Ordering::Equal => return Ok(Some(row)),
            }
        }
        Ok(None)
    }

    fn community_u32(
        &self,
        community: u32,
        section: SectionKind,
    ) -> Result<u32, CommunityArtifactError> {
        let index = bounded(community, self.manifest.community_count, "community")?;
        self.value_u32(section, index)
    }

    fn value_u32(&self, section: SectionKind, index: usize) -> Result<u32, CommunityArtifactError> {
        read_u32(self.section_bytes(section)?, index).ok_or_else(|| {
            CommunityArtifactError::Invalid("u32 section index is invalid".to_owned())
        })
    }

    fn value_u64(&self, section: SectionKind, index: usize) -> Result<u64, CommunityArtifactError> {
        read_u64(self.section_bytes(section)?, index).ok_or_else(|| {
            CommunityArtifactError::Invalid("u64 section index is invalid".to_owned())
        })
    }

    fn section(&self, kind: SectionKind) -> Result<SectionHeader, CommunityArtifactError> {
        self.header
            .sections()
            .iter()
            .copied()
            .find(|section| section.kind() == kind.code())
            .ok_or_else(|| {
                CommunityArtifactError::Invalid(format!("missing section {}", kind.code()))
            })
    }

    fn section_bytes(&self, kind: SectionKind) -> Result<&[u8], CommunityArtifactError> {
        let section = self.section(kind)?;
        let start = section.offset() as usize;
        let end = start
            .checked_add(section.byte_len() as usize)
            .ok_or_else(|| CommunityArtifactError::Invalid("section range overflow".to_owned()))?;
        self.map
            .get(start..end)
            .ok_or_else(|| CommunityArtifactError::Invalid("section is outside mapping".to_owned()))
    }
}

fn validate_manifest(
    root: &Path,
    manifest: &CommunityArtifactManifest,
) -> Result<(), CommunityArtifactError> {
    if manifest.schema_version != COMMUNITY_ARTIFACT_SCHEMA
        || manifest.binary_file != BINARY_FILE
        || manifest.generation == 0
        || manifest.admitted_candidate_edges != 0
    {
        return Err(CommunityArtifactError::Invalid(
            "manifest violates community schema or asserted authority".to_owned(),
        ));
    }
    let artifact = required_digest(&manifest.artifact_digest, "artifact")?;
    let payload = required_digest(&manifest.payload_digest, "payload")?;
    let source = required_digest(&manifest.source_discovery_digest, "source discovery")?;
    let relation = required_digest(&manifest.relation_policy_digest, "relation policy")?;
    let policy = required_digest(&manifest.community_policy_digest, "community policy")?;
    let actual = content_address(
        manifest.generation,
        source,
        relation,
        policy,
        payload,
        manifest_counts(manifest),
    );
    if actual != artifact
        || root.file_name().and_then(|name| name.to_str()) != Some(hex(&actual).as_str())
    {
        return Err(CommunityArtifactError::Invalid(
            "community content address does not match manifest or directory".to_owned(),
        ));
    }
    Ok(())
}

fn validate_header(
    manifest: &CommunityArtifactManifest,
    map: &[u8],
    header: &BinaryHeader,
) -> Result<(), CommunityArtifactError> {
    if header.magic() != BINARY_MAGIC
        || header.version() != BINARY_VERSION
        || header.section_count() as usize != SECTION_COUNT
        || header.header_bytes() as usize != HEADER_BYTES
        || header.generation() != manifest.generation
        || header.counts() != manifest_counts(manifest)
        || header.admitted_candidate_edges() != 0
        || header.artifact_digest() != required_digest(&manifest.artifact_digest, "artifact")?
        || header.payload_digest() != required_digest(&manifest.payload_digest, "payload")?
        || header.source_discovery_digest()
            != required_digest(&manifest.source_discovery_digest, "source discovery")?
        || header.relation_policy_digest()
            != required_digest(&manifest.relation_policy_digest, "relation policy")?
        || header.community_policy_digest()
            != required_digest(&manifest.community_policy_digest, "community policy")?
        || map.len() as u64 != manifest.binary_bytes
    {
        return Err(CommunityArtifactError::Invalid(
            "community binary header does not match manifest".to_owned(),
        ));
    }
    validate_sections(manifest, map, header)
}

fn validate_sections(
    manifest: &CommunityArtifactManifest,
    map: &[u8],
    header: &BinaryHeader,
) -> Result<(), CommunityArtifactError> {
    if manifest.sections.len() != SECTION_COUNT {
        return Err(CommunityArtifactError::Invalid(
            "community manifest section count is invalid".to_owned(),
        ));
    }
    let expected = [
        manifest.node_count,
        manifest.community_count,
        manifest.community_count,
        manifest.community_count,
        manifest.community_count,
        manifest.community_count + 1,
        manifest.affinity_count,
        manifest.affinity_count,
        manifest.bridge_count,
        manifest.bridge_count,
        manifest.bridge_count,
        manifest.bridge_count,
        manifest.bridge_count,
        manifest.bridge_count,
        manifest.bridge_count,
        manifest.bridge_count,
    ];
    let bytes = [4_u16, 8, 2, 4, 4, 8, 4, 8, 4, 4, 8, 8, 4, 4, 4, 4];
    let mut previous_end = HEADER_BYTES as u64;
    for (index, section) in header.sections().iter().enumerate() {
        let kind = SectionKind::ALL[index];
        let manifest_section = &manifest.sections[index];
        if section.kind() != kind.code()
            || section.element_bytes() != bytes[index]
            || section.count() != expected[index]
            || section.byte_len()
                != u64::from(section.element_bytes()).saturating_mul(section.count())
            || section.offset() % ALIGNMENT != 0
            || section.offset() < previous_end
            || manifest_section.kind != section.kind()
            || manifest_section.offset != section.offset()
            || manifest_section.count != section.count()
            || manifest_section.element_bytes != u32::from(section.element_bytes())
            || section
                .offset()
                .checked_add(section.byte_len())
                .is_none_or(|end| end > map.len() as u64)
        {
            return Err(CommunityArtifactError::Invalid(format!(
                "community section {} has invalid shape",
                kind.code()
            )));
        }
        previous_end = section.offset() + section.byte_len();
    }
    Ok(())
}

fn validate_values(
    manifest: &CommunityArtifactManifest,
    map: &[u8],
    header: &BinaryHeader,
) -> Result<(), CommunityArtifactError> {
    let node_communities = section_slice(map, header.sections()[0])?;
    let mut assigned = 0_u64;
    for index in 0..manifest.node_count as usize {
        let community = read_u32(node_communities, index).expect("validated node community");
        if community != u32::MAX && u64::from(community) >= manifest.community_count {
            return Err(CommunityArtifactError::Invalid(
                "node-community assignment is invalid".to_owned(),
            ));
        }
        assigned += u64::from(community != u32::MAX);
    }
    if assigned != manifest.core_node_count {
        return Err(CommunityArtifactError::Invalid(
            "assigned core-node count does not match manifest".to_owned(),
        ));
    }
    let community_sizes = section_slice(map, header.sections()[4])?;
    let mut size_sum = 0_u64;
    for index in 0..manifest.community_count as usize {
        let size = read_u32(community_sizes, index).expect("validated community size");
        if size == 0 {
            return Err(CommunityArtifactError::Invalid(
                "community has zero members".to_owned(),
            ));
        }
        size_sum += u64::from(size);
    }
    if size_sum != manifest.core_node_count {
        return Err(CommunityArtifactError::Invalid(
            "community sizes do not cover core nodes exactly".to_owned(),
        ));
    }
    let offsets = section_slice(map, header.sections()[5])?;
    let mut previous = 0_u64;
    for index in 0..=manifest.community_count as usize {
        let value = read_u64(offsets, index).expect("validated offset bytes");
        if value < previous || value > manifest.affinity_count {
            return Err(CommunityArtifactError::Invalid(
                "sparse affinity offsets are invalid".to_owned(),
            ));
        }
        previous = value;
    }
    if previous != manifest.affinity_count {
        return Err(CommunityArtifactError::Invalid(
            "sparse affinity terminal offset is invalid".to_owned(),
        ));
    }
    let targets = section_slice(map, header.sections()[6])?;
    for index in 0..manifest.affinity_count as usize {
        if read_u32(targets, index).expect("validated affinity target")
            >= manifest.community_count as u32
        {
            return Err(CommunityArtifactError::Invalid(
                "sparse affinity target is invalid".to_owned(),
            ));
        }
    }
    let bridge_nodes = section_slice(map, header.sections()[8])?;
    for index in 0..manifest.bridge_count as usize {
        if u64::from(read_u32(bridge_nodes, index).expect("validated bridge node"))
            >= manifest.node_count
        {
            return Err(CommunityArtifactError::Invalid(
                "bridge node is out of bounds".to_owned(),
            ));
        }
        for section in [12_usize, 13, 14, 15] {
            if read_u32(section_slice(map, header.sections()[section])?, index)
                .expect("validated bridge metric")
                > 1_000_000
            {
                return Err(CommunityArtifactError::Invalid(
                    "bridge metric exceeds fixed-point range".to_owned(),
                ));
            }
        }
    }
    Ok(())
}

fn manifest_counts(manifest: &CommunityArtifactManifest) -> [u64; 7] {
    [
        manifest.node_count,
        manifest.core_node_count,
        manifest.selected_edge_count,
        manifest.component_count,
        manifest.community_count,
        manifest.affinity_count,
        manifest.bridge_count,
    ]
}

fn section_slice(map: &[u8], section: SectionHeader) -> Result<&[u8], CommunityArtifactError> {
    let start = section.offset() as usize;
    let end = start + section.byte_len() as usize;
    map.get(start..end).ok_or_else(|| {
        CommunityArtifactError::Invalid("section range is outside mapping".to_owned())
    })
}

fn byte_range(
    bytes: &[u8],
    start: usize,
    end: usize,
    width: usize,
) -> Result<&[u8], CommunityArtifactError> {
    let start = start
        .checked_mul(width)
        .ok_or_else(|| CommunityArtifactError::Invalid("slice start overflow".to_owned()))?;
    let end = end
        .checked_mul(width)
        .ok_or_else(|| CommunityArtifactError::Invalid("slice end overflow".to_owned()))?;
    bytes.get(start..end).ok_or_else(|| {
        CommunityArtifactError::Invalid("sparse slice is outside section".to_owned())
    })
}

fn bounded(value: u32, count: u64, kind: &str) -> Result<usize, CommunityArtifactError> {
    if u64::from(value) >= count {
        return Err(CommunityArtifactError::Invalid(format!(
            "{kind} index {value} is out of bounds"
        )));
    }
    Ok(value as usize)
}

fn required_digest(value: &str, kind: &str) -> Result<[u8; 32], CommunityArtifactError> {
    parse_hex(value)
        .ok_or_else(|| CommunityArtifactError::Invalid(format!("{kind} digest is malformed")))
}

fn read_u16(bytes: &[u8], index: usize) -> Option<u16> {
    let start = index.checked_mul(2)?;
    Some(u16::from_le_bytes(
        bytes.get(start..start + 2)?.try_into().ok()?,
    ))
}

fn read_u32(bytes: &[u8], index: usize) -> Option<u32> {
    let start = index.checked_mul(4)?;
    Some(u32::from_le_bytes(
        bytes.get(start..start + 4)?.try_into().ok()?,
    ))
}

fn read_u64(bytes: &[u8], index: usize) -> Option<u64> {
    let start = index.checked_mul(8)?;
    Some(u64::from_le_bytes(
        bytes.get(start..start + 8)?.try_into().ok()?,
    ))
}
