use crate::format::{
    content_address, parse_hex, BinaryHeader, DiscoveryViewManifest, IdentityRefRecord, LeF32,
    LeI64, LeU16, LeU32, LeU64, SectionHeader, SectionKind, BINARY_FILE, BINARY_HEADER_BYTES,
    BINARY_MAGIC, BINARY_SCHEMA_VERSION, DISCOVERY_VIEW_SCHEMA, MANIFEST_FILE, SECTION_ALIGNMENT,
    SECTION_COUNT,
};
use crate::{DiscoveryNodeKind, DiscoveryRelationFamily, DiscoveryViewError};
use memmap2::{Mmap, MmapOptions};
use std::fs::File;
use std::mem::size_of;
use std::path::{Path, PathBuf};
use zerocopy::{FromBytes, Ref, Unaligned};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DiscoveryStableId {
    pub hash: u64,
    pub collision: u16,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct DiscoveryTemporalView {
    pub valid_from: Option<i64>,
    pub valid_to: Option<i64>,
    pub recorded_at: Option<i64>,
    pub expired_at: Option<i64>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct DiscoveryEdgeView {
    pub identity: DiscoveryStableId,
    pub source: u32,
    pub target: u32,
    pub relation_code: u16,
    pub family: DiscoveryRelationFamily,
    pub confidence: f32,
    pub temporal: DiscoveryTemporalView,
}

#[derive(Clone, Copy)]
pub struct DiscoveryIndexSlice<'a> {
    bytes: &'a [u8],
}

impl<'a> DiscoveryIndexSlice<'a> {
    pub fn len(self) -> usize {
        self.bytes.len() / size_of::<u32>()
    }

    pub fn is_empty(self) -> bool {
        self.bytes.is_empty()
    }

    pub fn get(self, index: usize) -> Option<u32> {
        let start = index.checked_mul(size_of::<u32>())?;
        let bytes: [u8; 4] = self.bytes.get(start..start + 4)?.try_into().ok()?;
        Some(u32::from_le_bytes(bytes))
    }

    pub fn iter(self) -> impl ExactSizeIterator<Item = u32> + 'a {
        self.bytes
            .chunks_exact(4)
            .map(|bytes| u32::from_le_bytes(bytes.try_into().expect("four-byte chunk")))
    }
}

pub struct AssertedDiscoveryView {
    root: PathBuf,
    manifest: DiscoveryViewManifest,
    map: Mmap,
    header: BinaryHeader,
}

impl AssertedDiscoveryView {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, DiscoveryViewError> {
        let root = root.as_ref().to_path_buf();
        let manifest: DiscoveryViewManifest =
            serde_json::from_slice(&std::fs::read(root.join(MANIFEST_FILE))?)?;
        validate_manifest(&root, &manifest)?;
        let file = File::open(root.join(BINARY_FILE))?;
        let map = unsafe { MmapOptions::new().map(&file)? };
        let header = *Ref::<_, BinaryHeader>::new_unaligned(
            map.get(..BINARY_HEADER_BYTES).ok_or_else(|| {
                DiscoveryViewError::Invalid("binary header is truncated".to_owned())
            })?,
        )
        .ok_or_else(|| DiscoveryViewError::Invalid("binary header layout is invalid".to_owned()))?;
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

    pub fn manifest(&self) -> &DiscoveryViewManifest {
        &self.manifest
    }

    pub fn node_count(&self) -> usize {
        self.manifest.node_count as usize
    }

    pub fn edge_count(&self) -> usize {
        self.manifest.edge_count as usize
    }

    pub fn validate_payload(&self) -> Result<(), DiscoveryViewError> {
        let first = self.section(SectionKind::NodeStableHash)?.offset() as usize;
        let expected = parse_hex(&self.manifest.payload_digest).ok_or_else(|| {
            DiscoveryViewError::Invalid("manifest payload digest is malformed".to_owned())
        })?;
        let actual = blake3::hash(self.map.get(first..).ok_or_else(|| {
            DiscoveryViewError::Invalid("payload offset is outside the mapping".to_owned())
        })?);
        if actual.as_bytes() != &expected {
            return Err(DiscoveryViewError::Invalid(
                "binary payload digest mismatch".to_owned(),
            ));
        }
        Ok(())
    }

    pub fn node_identity(&self, node: u32) -> Result<DiscoveryStableId, DiscoveryViewError> {
        let index = bounded(node, self.node_count(), "node")?;
        Ok(DiscoveryStableId {
            hash: self.records::<LeU64>(SectionKind::NodeStableHash)?[index].get(),
            collision: self.records::<LeU16>(SectionKind::NodeCollision)?[index].get(),
        })
    }

    pub fn node_kind(&self, node: u32) -> Result<DiscoveryNodeKind, DiscoveryViewError> {
        let index = bounded(node, self.node_count(), "node")?;
        let code = self.records::<LeU16>(SectionKind::NodeKind)?[index].get();
        DiscoveryNodeKind::from_code(code).ok_or_else(|| {
            DiscoveryViewError::Invalid(format!("unknown discovery node kind {code}"))
        })
    }

    pub fn evidence_identity(
        &self,
        evidence: u32,
    ) -> Result<DiscoveryStableId, DiscoveryViewError> {
        let index = bounded(
            evidence,
            self.manifest.evidence_identity_count as usize,
            "evidence",
        )?;
        Ok(DiscoveryStableId {
            hash: self.records::<LeU64>(SectionKind::EvidenceStableHash)?[index].get(),
            collision: self.records::<LeU16>(SectionKind::EvidenceCollision)?[index].get(),
        })
    }

    pub fn edge(&self, edge: u32) -> Result<DiscoveryEdgeView, DiscoveryViewError> {
        let index = bounded(edge, self.edge_count(), "edge")?;
        let family_code = self.records::<LeU16>(SectionKind::EdgeFamily)?[index].get();
        Ok(DiscoveryEdgeView {
            identity: DiscoveryStableId {
                hash: self.records::<LeU64>(SectionKind::EdgeStableHash)?[index].get(),
                collision: self.records::<LeU16>(SectionKind::EdgeCollision)?[index].get(),
            },
            source: self.records::<LeU32>(SectionKind::EdgeSource)?[index].get(),
            target: self.records::<LeU32>(SectionKind::EdgeTarget)?[index].get(),
            relation_code: self.records::<LeU16>(SectionKind::EdgeRelation)?[index].get(),
            family: DiscoveryRelationFamily::from_code(family_code).ok_or_else(|| {
                DiscoveryViewError::Invalid(format!("unknown relation family {family_code}"))
            })?,
            confidence: self.records::<LeF32>(SectionKind::EdgeConfidence)?[index].get(),
            temporal: self.edge_temporal(index)?,
        })
    }

    pub fn node_external_id(&self, node: u32) -> Result<&str, DiscoveryViewError> {
        let index = bounded(node, self.node_count(), "node")?;
        self.identity(index)
    }

    pub fn node_dense_for_external_id(
        &self,
        external_id: &str,
    ) -> Result<Option<u32>, DiscoveryViewError> {
        let mut left = 0_usize;
        let mut right = self.node_count();
        while left < right {
            let middle = left + (right - left) / 2;
            match self.identity(middle)?.cmp(external_id) {
                std::cmp::Ordering::Less => left = middle + 1,
                std::cmp::Ordering::Greater => right = middle,
                std::cmp::Ordering::Equal => return Ok(Some(middle as u32)),
            }
        }
        Ok(None)
    }

    pub fn evidence_external_id(&self, evidence: u32) -> Result<&str, DiscoveryViewError> {
        let evidence_count = self.manifest.evidence_identity_count as usize;
        let dense = bounded(evidence, evidence_count, "evidence")?;
        self.identity(self.node_count() + dense)
    }

    pub fn outgoing_edges(&self, node: u32) -> Result<DiscoveryIndexSlice<'_>, DiscoveryViewError> {
        self.adjacency(
            node,
            SectionKind::OutgoingOffsets,
            SectionKind::OutgoingEdges,
        )
    }

    pub fn incoming_edges(&self, node: u32) -> Result<DiscoveryIndexSlice<'_>, DiscoveryViewError> {
        self.adjacency(
            node,
            SectionKind::IncomingOffsets,
            SectionKind::IncomingEdges,
        )
    }

    pub fn node_evidence(&self, node: u32) -> Result<DiscoveryIndexSlice<'_>, DiscoveryViewError> {
        self.indexed_values(
            node,
            self.node_count(),
            SectionKind::NodeEvidenceOffsets,
            SectionKind::NodeEvidenceIndices,
            "node",
        )
    }

    pub fn edge_evidence(&self, edge: u32) -> Result<DiscoveryIndexSlice<'_>, DiscoveryViewError> {
        self.indexed_values(
            edge,
            self.edge_count(),
            SectionKind::EdgeEvidenceOffsets,
            SectionKind::EdgeEvidenceIndices,
            "edge",
        )
    }

    fn time(&self, section: SectionKind, index: usize) -> Result<i64, DiscoveryViewError> {
        Ok(self.records::<LeI64>(section)?[index].get())
    }

    fn edge_temporal(&self, edge: usize) -> Result<DiscoveryTemporalView, DiscoveryViewError> {
        let index = self.records::<LeU32>(SectionKind::EdgeTemporalIndex)?[edge].get();
        if index == u32::MAX {
            return Ok(DiscoveryTemporalView::default());
        }
        let index = bounded(
            index,
            self.manifest.temporal_edge_count as usize,
            "temporal edge",
        )?;
        let flags = self.section_bytes(SectionKind::EdgeTemporalFlags)?[index];
        Ok(DiscoveryTemporalView {
            valid_from: optional_time(flags, 1, self.time(SectionKind::EdgeValidFrom, index)?),
            valid_to: optional_time(flags, 2, self.time(SectionKind::EdgeValidTo, index)?),
            recorded_at: optional_time(flags, 4, self.time(SectionKind::EdgeRecordedAt, index)?),
            expired_at: optional_time(flags, 8, self.time(SectionKind::EdgeExpiredAt, index)?),
        })
    }

    fn identity(&self, ref_index: usize) -> Result<&str, DiscoveryViewError> {
        let record = *self
            .records::<IdentityRefRecord>(SectionKind::IdentityRefs)?
            .get(ref_index)
            .ok_or_else(|| DiscoveryViewError::Invalid("identity ref is missing".to_owned()))?;
        let start = usize::try_from(record.offset())
            .map_err(|_| DiscoveryViewError::Invalid("identity offset overflow".to_owned()))?;
        let end = start
            .checked_add(record.len() as usize)
            .ok_or_else(|| DiscoveryViewError::Invalid("identity range overflow".to_owned()))?;
        std::str::from_utf8(
            self.section_bytes(SectionKind::IdentitySlab)?
                .get(start..end)
                .ok_or_else(|| {
                    DiscoveryViewError::Invalid("identity range is invalid".to_owned())
                })?,
        )
        .map_err(|_| DiscoveryViewError::Invalid("identity is not UTF-8".to_owned()))
    }

    fn adjacency(
        &self,
        node: u32,
        offsets: SectionKind,
        edges: SectionKind,
    ) -> Result<DiscoveryIndexSlice<'_>, DiscoveryViewError> {
        self.indexed_values(node, self.node_count(), offsets, edges, "node")
    }

    fn indexed_values(
        &self,
        index: u32,
        limit: usize,
        offsets: SectionKind,
        values: SectionKind,
        label: &str,
    ) -> Result<DiscoveryIndexSlice<'_>, DiscoveryViewError> {
        let index = bounded(index, limit, label)?;
        let offsets = self.records::<LeU64>(offsets)?;
        let start = offsets[index].get() as usize;
        let end = offsets[index + 1].get() as usize;
        let bytes = self.section_bytes(values)?;
        let byte_start = start
            .checked_mul(size_of::<u32>())
            .ok_or_else(|| DiscoveryViewError::Invalid("index range overflow".to_owned()))?;
        let byte_end = end
            .checked_mul(size_of::<u32>())
            .ok_or_else(|| DiscoveryViewError::Invalid("index range overflow".to_owned()))?;
        Ok(DiscoveryIndexSlice {
            bytes: bytes.get(byte_start..byte_end).ok_or_else(|| {
                DiscoveryViewError::Invalid("indexed values are outside their section".to_owned())
            })?,
        })
    }

    fn records<T: FromBytes + Unaligned>(
        &self,
        kind: SectionKind,
    ) -> Result<Ref<&[u8], [T]>, DiscoveryViewError> {
        Ref::<_, [T]>::new_slice(self.section_bytes(kind)?).ok_or_else(|| {
            DiscoveryViewError::Invalid(format!("section {kind:?} has an invalid record layout"))
        })
    }

    fn section_bytes(&self, kind: SectionKind) -> Result<&[u8], DiscoveryViewError> {
        let section = self.section(kind)?;
        let start = section.offset() as usize;
        let end = start
            .checked_add(section.byte_len() as usize)
            .ok_or_else(|| DiscoveryViewError::Invalid("section range overflow".to_owned()))?;
        self.map.get(start..end).ok_or_else(|| {
            DiscoveryViewError::Invalid(format!("section {kind:?} is outside the mapping"))
        })
    }

    fn section(&self, kind: SectionKind) -> Result<SectionHeader, DiscoveryViewError> {
        self.header
            .sections
            .iter()
            .copied()
            .find(|section| section.kind() == kind.code())
            .ok_or_else(|| DiscoveryViewError::Invalid(format!("missing section {kind:?}")))
    }
}

fn validate_manifest(
    root: &Path,
    manifest: &DiscoveryViewManifest,
) -> Result<(), DiscoveryViewError> {
    if manifest.schema_version != DISCOVERY_VIEW_SCHEMA {
        return Err(DiscoveryViewError::Invalid(format!(
            "unsupported manifest schema {}",
            manifest.schema_version
        )));
    }
    if manifest.admitted_candidate_edges != 0 {
        return Err(DiscoveryViewError::Invalid(
            "manifest admitted candidate edges".to_owned(),
        ));
    }
    if manifest.generation == 0
        || manifest.source_snapshot_id.trim().is_empty()
        || manifest.relation_policy_id.trim().is_empty()
        || manifest.relation_policy_version.trim().is_empty()
        || manifest.binary_file != BINARY_FILE
        || manifest.temporal_edge_count > manifest.edge_count
    {
        return Err(DiscoveryViewError::Invalid(
            "manifest authority or count contract is invalid".to_owned(),
        ));
    }
    if root.file_name().and_then(|value| value.to_str()) != Some(&manifest.artifact_digest) {
        return Err(DiscoveryViewError::Invalid(
            "artifact directory does not match its content address".to_owned(),
        ));
    }
    if manifest.sections.len() != SECTION_COUNT {
        return Err(DiscoveryViewError::Invalid(
            "manifest section count is invalid".to_owned(),
        ));
    }
    for (index, relation) in manifest.relations.iter().enumerate() {
        if relation.code as usize != index
            || relation.relation.is_empty()
            || (index > 0 && manifest.relations[index - 1].relation >= relation.relation)
        {
            return Err(DiscoveryViewError::Invalid(
                "relation dictionary is not canonical".to_owned(),
            ));
        }
    }
    Ok(())
}

fn validate_header(
    manifest: &DiscoveryViewManifest,
    map: &Mmap,
    header: &BinaryHeader,
) -> Result<(), DiscoveryViewError> {
    if header.magic != BINARY_MAGIC
        || u16::from_le_bytes(header.schema_version) != BINARY_SCHEMA_VERSION
        || u16::from_le_bytes(header.section_count) as usize != SECTION_COUNT
        || u32::from_le_bytes(header.header_bytes) as usize != BINARY_HEADER_BYTES
    {
        return Err(DiscoveryViewError::Invalid(
            "binary header contract mismatch".to_owned(),
        ));
    }
    if u64::from_le_bytes(header.admitted_candidate_edges) != 0
        || u64::from_le_bytes(header.excluded_candidate_edges) != manifest.excluded_candidate_edges
    {
        return Err(DiscoveryViewError::Invalid(
            "binary candidate-edge authority mismatch".to_owned(),
        ));
    }
    for (expected, section) in SectionKind::ALL.iter().zip(header.sections.iter()) {
        if section.kind() != expected.code()
            || section.offset() % SECTION_ALIGNMENT != 0
            || section.byte_len()
                != section
                    .count()
                    .saturating_mul(section.element_bytes().into())
        {
            return Err(DiscoveryViewError::Invalid(format!(
                "binary section contract mismatch for {expected:?}"
            )));
        }
        let end = section
            .offset()
            .checked_add(section.byte_len())
            .ok_or_else(|| {
                DiscoveryViewError::Invalid("binary section length overflow".to_owned())
            })?;
        if end > map.len() as u64 {
            return Err(DiscoveryViewError::Invalid(format!(
                "binary section {expected:?} is truncated"
            )));
        }
    }
    let expected_artifact = parse_hex(&manifest.artifact_digest)
        .ok_or_else(|| DiscoveryViewError::Invalid("artifact digest is malformed".to_owned()))?;
    let expected_payload = parse_hex(&manifest.payload_digest)
        .ok_or_else(|| DiscoveryViewError::Invalid("payload digest is malformed".to_owned()))?;
    let expected_source = parse_hex(&manifest.source_snapshot_digest).ok_or_else(|| {
        DiscoveryViewError::Invalid("source snapshot digest is malformed".to_owned())
    })?;
    let expected_registry = parse_hex(&manifest.evidence_registry_digest).ok_or_else(|| {
        DiscoveryViewError::Invalid("evidence registry digest is malformed".to_owned())
    })?;
    let expected_policy = parse_hex(&manifest.relation_policy_digest).ok_or_else(|| {
        DiscoveryViewError::Invalid("relation policy digest is malformed".to_owned())
    })?;
    let recomputed_artifact = content_address(
        manifest.generation,
        &manifest.source_snapshot_id,
        expected_source,
        expected_registry,
        expected_policy,
        expected_payload,
        manifest.excluded_candidate_edges,
        &manifest.relations,
    );
    if header.artifact_digest != expected_artifact
        || recomputed_artifact != expected_artifact
        || header.payload_digest != expected_payload
        || header.source_snapshot_digest != expected_source
        || header.evidence_registry_digest != expected_registry
        || header.policy_digest != expected_policy
        || u64::from_le_bytes(header.generation) != manifest.generation
        || u64::from_le_bytes(header.node_count) != manifest.node_count
        || u64::from_le_bytes(header.edge_count) != manifest.edge_count
        || u64::from_le_bytes(header.temporal_edge_count) != manifest.temporal_edge_count
        || u64::from_le_bytes(header.evidence_identity_count) != manifest.evidence_identity_count
        || map.len() as u64 != manifest.binary_bytes
    {
        return Err(DiscoveryViewError::Invalid(
            "binary header does not match its manifest".to_owned(),
        ));
    }
    validate_section_shapes(manifest, header)
}

fn validate_section_shapes(
    manifest: &DiscoveryViewManifest,
    header: &BinaryHeader,
) -> Result<(), DiscoveryViewError> {
    let node = manifest.node_count;
    let edge = manifest.edge_count;
    let temporal = manifest.temporal_edge_count;
    let evidence = manifest.evidence_identity_count;
    let identity = node.saturating_add(evidence);
    for (kind, expected_count, expected_bytes) in [
        (SectionKind::NodeStableHash, node, 8),
        (SectionKind::NodeCollision, node, 2),
        (SectionKind::NodeKind, node, 2),
        (SectionKind::NodeEvidenceOffsets, node + 1, 8),
        (
            SectionKind::NodeEvidenceIndices,
            manifest.node_evidence_links,
            4,
        ),
        (SectionKind::EdgeStableHash, edge, 8),
        (SectionKind::EdgeCollision, edge, 2),
        (SectionKind::EdgeSource, edge, 4),
        (SectionKind::EdgeTarget, edge, 4),
        (SectionKind::EdgeRelation, edge, 2),
        (SectionKind::EdgeFamily, edge, 2),
        (SectionKind::EdgeConfidence, edge, 4),
        (SectionKind::EdgeTemporalIndex, edge, 4),
        (SectionKind::EdgeTemporalFlags, temporal, 1),
        (SectionKind::EdgeValidFrom, temporal, 8),
        (SectionKind::EdgeValidTo, temporal, 8),
        (SectionKind::EdgeRecordedAt, temporal, 8),
        (SectionKind::EdgeExpiredAt, temporal, 8),
        (SectionKind::EdgeEvidenceOffsets, edge + 1, 8),
        (
            SectionKind::EdgeEvidenceIndices,
            manifest.edge_evidence_links,
            4,
        ),
        (SectionKind::EvidenceStableHash, evidence, 8),
        (SectionKind::EvidenceCollision, evidence, 2),
        (SectionKind::OutgoingOffsets, node + 1, 8),
        (SectionKind::OutgoingEdges, edge, 4),
        (SectionKind::IncomingOffsets, node + 1, 8),
        (SectionKind::IncomingEdges, edge, 4),
        (
            SectionKind::IdentityRefs,
            identity,
            size_of::<IdentityRefRecord>() as u64,
        ),
    ] {
        let section = header.sections[(kind.code() - 1) as usize];
        if section.count() != expected_count || u64::from(section.element_bytes()) != expected_bytes
        {
            return Err(DiscoveryViewError::Invalid(format!(
                "section {kind:?} shape does not match the manifest"
            )));
        }
    }
    let slab = header.sections[(SectionKind::IdentitySlab.code() - 1) as usize];
    if slab.element_bytes() != 1 {
        return Err(DiscoveryViewError::Invalid(
            "identity slab element width is invalid".to_owned(),
        ));
    }
    Ok(())
}

fn bounded(value: u32, limit: usize, label: &str) -> Result<usize, DiscoveryViewError> {
    let value = value as usize;
    if value >= limit {
        return Err(DiscoveryViewError::Invalid(format!(
            "{label} index {value} is out of range {limit}"
        )));
    }
    Ok(value)
}

fn optional_time(flags: u8, bit: u8, value: i64) -> Option<i64> {
    (flags & bit != 0).then_some(value)
}
