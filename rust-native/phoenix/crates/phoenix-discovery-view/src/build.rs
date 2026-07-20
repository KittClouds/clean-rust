use crate::columns::{edge_confidence, edge_key, temporal, vertex_kind_code};
use crate::format::{
    content_address, hex, BinaryHeader, DiscoveryRelationEntry, DiscoverySectionManifest,
    DiscoveryViewManifest, IdentityRefRecord, LeF32, LeI64, LeU16, LeU32, LeU64, SectionHeader,
    SectionKind, BINARY_FILE, BINARY_HEADER_BYTES, DISCOVERY_VIEW_SCHEMA, MANIFEST_FILE,
    SECTION_ALIGNMENT, SECTION_COUNT,
};
use crate::{DiscoveryRelationFamily, DiscoveryRelationPolicy, DiscoveryViewError};
use hashbrown::{HashMap, HashSet};
use phoenix_graph_kernel::{KernelEdge, KernelGraphLayer, KernelGraphSnapshot, KernelVertex};
use rayon::prelude::*;
use smallvec::SmallVec;
use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use zerocopy::AsBytes;

static BUILD_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DiscoveryAuthorityBinding {
    pub generation: u64,
    pub source_snapshot_id: String,
    pub source_snapshot_digest: [u8; 32],
    pub evidence_registry_digest: [u8; 32],
}

impl DiscoveryAuthorityBinding {
    fn validate(&self) -> Result<(), DiscoveryViewError> {
        if self.generation == 0 {
            return Err(DiscoveryViewError::Invalid(
                "discovery generation must be non-zero".to_owned(),
            ));
        }
        if self.source_snapshot_id.trim().is_empty() {
            return Err(DiscoveryViewError::Invalid(
                "source snapshot identity is empty".to_owned(),
            ));
        }
        if self.source_snapshot_digest == [0; 32] || self.evidence_registry_digest == [0; 32] {
            return Err(DiscoveryViewError::Invalid(
                "authority binding contains an unset digest".to_owned(),
            ));
        }
        Ok(())
    }
}

pub fn write_asserted_discovery_view(
    snapshot: &KernelGraphSnapshot,
    authority: &DiscoveryAuthorityBinding,
    policy: &DiscoveryRelationPolicy,
    artifact_root: impl AsRef<Path>,
) -> Result<DiscoveryViewManifest, DiscoveryViewError> {
    authority.validate()?;
    policy.validate()?;
    let policy_digest = policy.digest()?;
    let prepared = PreparedColumns::from_snapshot(snapshot)?;
    let root = artifact_root.as_ref();
    fs::create_dir_all(root)?;
    let temporary = temporary_build_directory(root, authority.generation)?;

    let result = write_prepared(
        &prepared,
        authority,
        policy,
        policy_digest,
        snapshot.candidate_edges.len(),
        &temporary,
    );
    let (manifest, artifact_digest) = match result {
        Ok(value) => value,
        Err(error) => {
            let _ = fs::remove_dir_all(&temporary);
            return Err(error);
        }
    };
    let final_directory = root.join(hex(&artifact_digest));
    match fs::rename(&temporary, &final_directory) {
        Ok(()) => return Ok(manifest),
        Err(_) if final_directory.exists() => {
            fs::remove_dir_all(&temporary)?;
            let existing = crate::AssertedDiscoveryView::open(&final_directory)?;
            if existing.manifest() == &manifest {
                return Ok(manifest);
            }
        }
        Err(error) => {
            let _ = fs::remove_dir_all(&temporary);
            return Err(error.into());
        }
    }
    Err(DiscoveryViewError::Invalid(format!(
        "content address {} resolves to a different manifest",
        manifest.artifact_digest
    )))
}

fn temporary_build_directory(root: &Path, generation: u64) -> Result<PathBuf, DiscoveryViewError> {
    let sequence = BUILD_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let path = root.join(format!(
        ".building-{}-{generation}-{sequence}",
        std::process::id()
    ));
    match fs::create_dir(&path) {
        Ok(()) => Ok(path),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            Err(DiscoveryViewError::BuildCollision(path))
        }
        Err(error) => Err(error.into()),
    }
}

fn write_prepared(
    prepared: &PreparedColumns,
    authority: &DiscoveryAuthorityBinding,
    policy: &DiscoveryRelationPolicy,
    policy_digest: [u8; 32],
    excluded_candidate_edges: usize,
    directory: &Path,
) -> Result<(DiscoveryViewManifest, [u8; 32]), DiscoveryViewError> {
    let binary_path = directory.join(BINARY_FILE);
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&binary_path)?;
    let mut writer = BinaryWriter::new(file)?;
    prepared.write_sections(&mut writer)?;
    let (mut file, sections, payload_digest, binary_bytes) = writer.finish()?;
    let artifact_digest = content_address(
        authority.generation,
        &authority.source_snapshot_id,
        authority.source_snapshot_digest,
        authority.evidence_registry_digest,
        policy_digest,
        payload_digest,
        excluded_candidate_edges as u64,
        &prepared.relations,
    );
    let header = BinaryHeader::new(
        authority.generation,
        prepared.node_hashes.len(),
        prepared.edge_hashes.len(),
        prepared.edge_temporal_flags.len(),
        prepared.evidence_hashes.len(),
        excluded_candidate_edges,
        artifact_digest,
        payload_digest,
        authority.source_snapshot_digest,
        authority.evidence_registry_digest,
        policy_digest,
        sections,
    );
    file.seek(SeekFrom::Start(0))?;
    file.write_all(header.as_bytes())?;
    file.sync_all()?;

    let section_manifest = sections
        .iter()
        .map(|section| DiscoverySectionManifest {
            kind: section.kind(),
            offset: section.offset(),
            count: section.count(),
            element_bytes: section.element_bytes().into(),
        })
        .collect();
    let manifest = DiscoveryViewManifest {
        schema_version: DISCOVERY_VIEW_SCHEMA.to_owned(),
        artifact_digest: hex(&artifact_digest),
        payload_digest: hex(&payload_digest),
        generation: authority.generation,
        source_snapshot_id: authority.source_snapshot_id.clone(),
        source_snapshot_digest: hex(&authority.source_snapshot_digest),
        evidence_registry_digest: hex(&authority.evidence_registry_digest),
        relation_policy_id: policy.policy_id.clone(),
        relation_policy_version: policy.policy_version.clone(),
        relation_policy_digest: hex(&policy_digest),
        node_count: prepared.node_hashes.len() as u64,
        edge_count: prepared.edge_hashes.len() as u64,
        temporal_edge_count: prepared.edge_temporal_flags.len() as u64,
        evidence_identity_count: prepared.evidence_hashes.len() as u64,
        node_evidence_links: prepared.node_evidence_indices.len() as u64,
        edge_evidence_links: prepared.edge_evidence_indices.len() as u64,
        excluded_candidate_edges: excluded_candidate_edges as u64,
        admitted_candidate_edges: 0,
        binary_file: BINARY_FILE.to_owned(),
        binary_bytes,
        sections: section_manifest,
        relations: prepared.relations.clone(),
    };
    let manifest_bytes = serde_json::to_vec(&manifest)?;
    let mut manifest_file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(directory.join(MANIFEST_FILE))?;
    manifest_file.write_all(&manifest_bytes)?;
    manifest_file.sync_all()?;
    Ok((manifest, artifact_digest))
}

struct BinaryWriter {
    writer: BufWriter<File>,
    position: u64,
    payload_hasher: blake3::Hasher,
    sections: [SectionHeader; SECTION_COUNT],
    section_index: usize,
}

impl BinaryWriter {
    fn new(file: File) -> Result<Self, DiscoveryViewError> {
        let mut writer = BufWriter::new(file);
        writer.write_all(&vec![0_u8; BINARY_HEADER_BYTES])?;
        let mut value = Self {
            writer,
            position: BINARY_HEADER_BYTES as u64,
            payload_hasher: blake3::Hasher::new(),
            sections: [SectionHeader::default(); SECTION_COUNT],
            section_index: 0,
        };
        value.align(false)?;
        Ok(value)
    }

    fn section<T: AsBytes>(
        &mut self,
        kind: SectionKind,
        values: &[T],
    ) -> Result<(), DiscoveryViewError> {
        self.align(true)?;
        let bytes = values.as_bytes();
        self.sections[self.section_index] =
            SectionHeader::new(kind, std::mem::size_of::<T>(), self.position, values.len());
        self.section_index += 1;
        self.writer.write_all(bytes)?;
        self.payload_hasher.update(bytes);
        self.position += bytes.len() as u64;
        Ok(())
    }

    fn bytes(&mut self, kind: SectionKind, values: &[u8]) -> Result<(), DiscoveryViewError> {
        self.section(kind, values)
    }

    fn align(&mut self, hash_padding: bool) -> Result<(), DiscoveryViewError> {
        let aligned = self.position.div_ceil(SECTION_ALIGNMENT) * SECTION_ALIGNMENT;
        let padding = (aligned - self.position) as usize;
        if padding > 0 {
            let zeros = [0_u8; SECTION_ALIGNMENT as usize];
            self.writer.write_all(&zeros[..padding])?;
            if hash_padding {
                self.payload_hasher.update(&zeros[..padding]);
            }
            self.position = aligned;
        }
        Ok(())
    }

    fn finish(
        mut self,
    ) -> Result<(File, [SectionHeader; SECTION_COUNT], [u8; 32], u64), DiscoveryViewError> {
        if self.section_index != SECTION_COUNT {
            return Err(DiscoveryViewError::Invalid(format!(
                "wrote {} discovery sections, expected {SECTION_COUNT}",
                self.section_index
            )));
        }
        self.writer.flush()?;
        let digest = *self.payload_hasher.finalize().as_bytes();
        let file = self
            .writer
            .into_inner()
            .map_err(|error| error.into_error())?;
        Ok((file, self.sections, digest, self.position))
    }
}

struct PreparedColumns {
    node_hashes: Vec<LeU64>,
    node_collisions: Vec<LeU16>,
    node_kinds: Vec<LeU16>,
    node_evidence_offsets: Vec<LeU64>,
    node_evidence_indices: Vec<LeU32>,
    edge_hashes: Vec<LeU64>,
    edge_collisions: Vec<LeU16>,
    edge_sources: Vec<LeU32>,
    edge_targets: Vec<LeU32>,
    edge_relations: Vec<LeU16>,
    edge_families: Vec<LeU16>,
    edge_confidences: Vec<LeF32>,
    edge_temporal_indices: Vec<LeU32>,
    edge_temporal_flags: Vec<u8>,
    edge_valid_from: Vec<LeI64>,
    edge_valid_to: Vec<LeI64>,
    edge_recorded_at: Vec<LeI64>,
    edge_expired_at: Vec<LeI64>,
    edge_evidence_offsets: Vec<LeU64>,
    edge_evidence_indices: Vec<LeU32>,
    evidence_hashes: Vec<LeU64>,
    evidence_collisions: Vec<LeU16>,
    outgoing_offsets: Vec<LeU64>,
    outgoing_edges: Vec<LeU32>,
    incoming_offsets: Vec<LeU64>,
    incoming_edges: Vec<LeU32>,
    identity_refs: Vec<IdentityRefRecord>,
    identity_slab: Vec<u8>,
    relations: Vec<DiscoveryRelationEntry>,
}

impl PreparedColumns {
    fn from_snapshot(snapshot: &KernelGraphSnapshot) -> Result<Self, DiscoveryViewError> {
        require_u32_capacity(snapshot.vertices.len(), "vertex")?;
        require_u32_capacity(snapshot.asserted_edges.len(), "edge")?;
        let mut vertices = snapshot.vertices.iter().collect::<Vec<_>>();
        if !vertices.is_sorted_by(|left, right| left.id.0 <= right.id.0) {
            vertices.par_sort_unstable_by(|left, right| left.id.0.cmp(&right.id.0));
        }
        reject_duplicate_vertices(&vertices)?;
        let dense = vertices
            .iter()
            .enumerate()
            .map(|(index, vertex)| (vertex.id.0.as_str(), index as u32))
            .collect::<HashMap<_, _>>();

        let mut edges = snapshot.asserted_edges.iter().collect::<Vec<_>>();
        for edge in &edges {
            validate_asserted_edge(edge)?;
            if !dense.contains_key(edge.source_id.0.as_str())
                || !dense.contains_key(edge.target_id.0.as_str())
            {
                return Err(DiscoveryViewError::Invalid(format!(
                    "asserted edge {} -> {} references a missing vertex",
                    edge.source_id.0, edge.target_id.0
                )));
            }
        }
        if !edges.is_sorted_by(|left, right| edge_key(left) <= edge_key(right)) {
            edges.par_sort_unstable_by(|left, right| edge_key(left).cmp(&edge_key(right)));
        }
        reject_duplicate_edges(&edges)?;

        let evidence = evidence_identities(&vertices, &edges);
        require_u32_capacity(evidence.len(), "evidence identity")?;
        let evidence_dense = evidence
            .iter()
            .enumerate()
            .map(|(index, value)| (*value, index as u32))
            .collect::<HashMap<_, _>>();
        let relations = relation_dictionary(&edges)?;
        let relation_dense = relations
            .iter()
            .map(|entry| (entry.relation.as_str(), entry.code))
            .collect::<HashMap<_, _>>();

        let (node_hashes, node_collisions) = stable_string_identities(
            b"phoenix-discovery-node/v1\0",
            &vertices
                .iter()
                .map(|vertex| vertex.id.0.as_str())
                .collect::<Vec<_>>(),
        )?;
        let (evidence_hashes, evidence_collisions) =
            stable_string_identities(b"phoenix-discovery-evidence/v1\0", &evidence)?;
        let (edge_hashes, edge_collisions) = stable_edge_identities(&edges)?;
        let (node_evidence_offsets, node_evidence_indices) =
            vertex_evidence_columns(&vertices, &evidence_dense)?;
        let (edge_evidence_offsets, edge_evidence_indices) =
            edge_evidence_columns(&edges, &evidence_dense)?;

        let mut edge_sources = Vec::with_capacity(edges.len());
        let mut edge_targets = Vec::with_capacity(edges.len());
        let mut edge_relations = Vec::with_capacity(edges.len());
        let mut edge_families = Vec::with_capacity(edges.len());
        let mut edge_confidences = Vec::with_capacity(edges.len());
        let mut edge_temporal_indices = Vec::with_capacity(edges.len());
        let mut edge_temporal_flags = Vec::new();
        let mut edge_valid_from = Vec::new();
        let mut edge_valid_to = Vec::new();
        let mut edge_recorded_at = Vec::new();
        let mut edge_expired_at = Vec::new();
        for edge in &edges {
            edge_sources.push(LeU32::new(dense[edge.source_id.0.as_str()]));
            edge_targets.push(LeU32::new(dense[edge.target_id.0.as_str()]));
            edge_relations.push(LeU16::new(relation_dense[edge.edge_type.0.as_str()]));
            let family = DiscoveryRelationFamily::from_kernel(&edge.relation_class)
                .expect("candidate relation was rejected before column construction");
            edge_families.push(LeU16::new(family.code()));
            edge_confidences.push(LeF32::new(edge_confidence(edge)?));
            if let Some((flags, valid_from, valid_to, recorded_at, expired_at)) =
                temporal(edge.temporal.clone())
            {
                edge_temporal_indices.push(LeU32::new(
                    u32::try_from(edge_temporal_flags.len()).map_err(|_| {
                        DiscoveryViewError::Invalid(
                            "temporal edge count exceeds u32 capacity".to_owned(),
                        )
                    })?,
                ));
                edge_temporal_flags.push(flags);
                edge_valid_from.push(LeI64::new(valid_from));
                edge_valid_to.push(LeI64::new(valid_to));
                edge_recorded_at.push(LeI64::new(recorded_at));
                edge_expired_at.push(LeI64::new(expired_at));
            } else {
                edge_temporal_indices.push(LeU32::new(u32::MAX));
            }
        }
        let (outgoing_offsets, outgoing_edges) =
            adjacency(vertices.len(), edge_sources.iter().map(|value| value.get()))?;
        let (incoming_offsets, incoming_edges) =
            adjacency(vertices.len(), edge_targets.iter().map(|value| value.get()))?;
        let (identity_refs, identity_slab) = identity_slab(&vertices, &evidence)?;
        drop(relation_dense);

        Ok(Self {
            node_hashes,
            node_collisions,
            node_kinds: vertices
                .iter()
                .map(|vertex| LeU16::new(vertex_kind_code(&vertex.class)))
                .collect(),
            node_evidence_offsets,
            node_evidence_indices,
            edge_hashes,
            edge_collisions,
            edge_sources,
            edge_targets,
            edge_relations,
            edge_families,
            edge_confidences,
            edge_temporal_indices,
            edge_temporal_flags,
            edge_valid_from,
            edge_valid_to,
            edge_recorded_at,
            edge_expired_at,
            edge_evidence_offsets,
            edge_evidence_indices,
            evidence_hashes,
            evidence_collisions,
            outgoing_offsets,
            outgoing_edges,
            incoming_offsets,
            incoming_edges,
            identity_refs,
            identity_slab,
            relations,
        })
    }

    fn write_sections(&self, writer: &mut BinaryWriter) -> Result<(), DiscoveryViewError> {
        writer.section(SectionKind::NodeStableHash, &self.node_hashes)?;
        writer.section(SectionKind::NodeCollision, &self.node_collisions)?;
        writer.section(SectionKind::NodeKind, &self.node_kinds)?;
        writer.section(
            SectionKind::NodeEvidenceOffsets,
            &self.node_evidence_offsets,
        )?;
        writer.section(
            SectionKind::NodeEvidenceIndices,
            &self.node_evidence_indices,
        )?;
        writer.section(SectionKind::EdgeStableHash, &self.edge_hashes)?;
        writer.section(SectionKind::EdgeCollision, &self.edge_collisions)?;
        writer.section(SectionKind::EdgeSource, &self.edge_sources)?;
        writer.section(SectionKind::EdgeTarget, &self.edge_targets)?;
        writer.section(SectionKind::EdgeRelation, &self.edge_relations)?;
        writer.section(SectionKind::EdgeFamily, &self.edge_families)?;
        writer.section(SectionKind::EdgeConfidence, &self.edge_confidences)?;
        writer.section(SectionKind::EdgeTemporalIndex, &self.edge_temporal_indices)?;
        writer.section(SectionKind::EdgeTemporalFlags, &self.edge_temporal_flags)?;
        writer.section(SectionKind::EdgeValidFrom, &self.edge_valid_from)?;
        writer.section(SectionKind::EdgeValidTo, &self.edge_valid_to)?;
        writer.section(SectionKind::EdgeRecordedAt, &self.edge_recorded_at)?;
        writer.section(SectionKind::EdgeExpiredAt, &self.edge_expired_at)?;
        writer.section(
            SectionKind::EdgeEvidenceOffsets,
            &self.edge_evidence_offsets,
        )?;
        writer.section(
            SectionKind::EdgeEvidenceIndices,
            &self.edge_evidence_indices,
        )?;
        writer.section(SectionKind::EvidenceStableHash, &self.evidence_hashes)?;
        writer.section(SectionKind::EvidenceCollision, &self.evidence_collisions)?;
        writer.section(SectionKind::OutgoingOffsets, &self.outgoing_offsets)?;
        writer.section(SectionKind::OutgoingEdges, &self.outgoing_edges)?;
        writer.section(SectionKind::IncomingOffsets, &self.incoming_offsets)?;
        writer.section(SectionKind::IncomingEdges, &self.incoming_edges)?;
        writer.section(SectionKind::IdentityRefs, &self.identity_refs)?;
        writer.bytes(SectionKind::IdentitySlab, &self.identity_slab)?;
        Ok(())
    }
}

fn validate_asserted_edge(edge: &KernelEdge) -> Result<(), DiscoveryViewError> {
    if edge.layer != KernelGraphLayer::Asserted
        || DiscoveryRelationFamily::from_kernel(&edge.relation_class).is_none()
    {
        return Err(DiscoveryViewError::Invalid(format!(
            "candidate edge was presented through asserted input: {} -> {} ({})",
            edge.source_id.0, edge.target_id.0, edge.edge_type.0
        )));
    }
    if edge.source_id.0.is_empty() || edge.target_id.0.is_empty() || edge.edge_type.0.is_empty() {
        return Err(DiscoveryViewError::Invalid(
            "asserted edge identity contains an empty component".to_owned(),
        ));
    }
    Ok(())
}

fn reject_duplicate_vertices(vertices: &[&KernelVertex]) -> Result<(), DiscoveryViewError> {
    if vertices.iter().any(|vertex| vertex.id.0.is_empty()) {
        return Err(DiscoveryViewError::Invalid(
            "asserted vertex identity is empty".to_owned(),
        ));
    }
    if let Some(pair) = vertices.windows(2).find(|pair| pair[0].id == pair[1].id) {
        return Err(DiscoveryViewError::Invalid(format!(
            "duplicate asserted vertex {}",
            pair[0].id.0
        )));
    }
    Ok(())
}

fn require_u32_capacity(count: usize, label: &str) -> Result<(), DiscoveryViewError> {
    if count > u32::MAX as usize {
        return Err(DiscoveryViewError::Invalid(format!(
            "{label} count exceeds u32 capacity"
        )));
    }
    Ok(())
}

fn reject_duplicate_edges(edges: &[&KernelEdge]) -> Result<(), DiscoveryViewError> {
    if let Some(pair) = edges
        .windows(2)
        .find(|pair| edge_key(pair[0]) == edge_key(pair[1]))
    {
        return Err(DiscoveryViewError::Invalid(format!(
            "duplicate asserted edge {} -> {} ({})",
            pair[0].source_id.0, pair[0].target_id.0, pair[0].edge_type.0
        )));
    }
    Ok(())
}

fn evidence_identities<'a>(
    vertices: &[&'a KernelVertex],
    edges: &[&'a KernelEdge],
) -> Vec<&'a str> {
    let mut evidence = Vec::new();
    for vertex in vertices {
        evidence.extend(vertex.provenance.evidence_refs.iter().map(String::as_str));
    }
    for edge in edges {
        evidence.extend(edge.provenance.evidence_refs.iter().map(String::as_str));
    }
    evidence.retain(|value| !value.is_empty());
    evidence.par_sort_unstable();
    evidence.dedup();
    evidence
}

fn relation_dictionary(
    edges: &[&KernelEdge],
) -> Result<Vec<DiscoveryRelationEntry>, DiscoveryViewError> {
    let mut pairs = edges
        .iter()
        .map(|edge| {
            (
                edge.edge_type.0.as_str(),
                DiscoveryRelationFamily::from_kernel(&edge.relation_class)
                    .expect("candidate relation was rejected"),
            )
        })
        .collect::<Vec<_>>();
    pairs.sort_unstable_by(|left, right| left.0.cmp(right.0));
    let mut entries: Vec<DiscoveryRelationEntry> = Vec::new();
    for (relation, family) in pairs {
        if let Some(last) = entries.last() {
            if last.relation == relation {
                if last.family != family {
                    return Err(DiscoveryViewError::Invalid(format!(
                        "relation {relation} has conflicting families"
                    )));
                }
                continue;
            }
        }
        let code = u16::try_from(entries.len()).map_err(|_| {
            DiscoveryViewError::Invalid("relation dictionary exceeds u16 capacity".to_owned())
        })?;
        entries.push(DiscoveryRelationEntry {
            code,
            relation: relation.to_owned(),
            family,
        });
    }
    Ok(entries)
}

fn stable_string_identities(
    domain: &[u8],
    identities: &[&str],
) -> Result<(Vec<LeU64>, Vec<LeU16>), DiscoveryViewError> {
    let identities = identities
        .par_iter()
        .map(|identity| stable_identity(domain, &[identity.as_bytes()]))
        .collect::<Vec<_>>();
    reject_stable_collisions(&identities)?;
    Ok((
        identities
            .iter()
            .map(|(hash, _)| LeU64::new(*hash))
            .collect(),
        identities.iter().map(|(_, tag)| LeU16::new(*tag)).collect(),
    ))
}

fn stable_edge_identities(
    edges: &[&KernelEdge],
) -> Result<(Vec<LeU64>, Vec<LeU16>), DiscoveryViewError> {
    let identities = edges
        .par_iter()
        .map(|edge| {
            stable_identity(
                b"phoenix-discovery-edge/v1\0",
                &[
                    edge.source_id.0.as_bytes(),
                    edge.target_id.0.as_bytes(),
                    edge.edge_type.0.as_bytes(),
                ],
            )
        })
        .collect::<Vec<_>>();
    reject_stable_collisions(&identities)?;
    Ok((
        identities
            .iter()
            .map(|(hash, _)| LeU64::new(*hash))
            .collect(),
        identities.iter().map(|(_, tag)| LeU16::new(*tag)).collect(),
    ))
}

fn stable_identity(domain: &[u8], parts: &[&[u8]]) -> (u64, u16) {
    let mut hasher = blake3::Hasher::new();
    hasher.update(domain);
    for part in parts {
        hasher.update(part);
        hasher.update(&[0]);
    }
    let digest = hasher.finalize();
    (
        u64::from_le_bytes(digest.as_bytes()[..8].try_into().unwrap()),
        u16::from_le_bytes(digest.as_bytes()[8..10].try_into().unwrap()),
    )
}

fn reject_stable_collisions(identities: &[(u64, u16)]) -> Result<(), DiscoveryViewError> {
    let mut seen = HashSet::with_capacity(identities.len());
    for identity in identities {
        if !seen.insert(*identity) {
            return Err(DiscoveryViewError::Invalid(
                "distinct identities collided across the 80-bit stable numeric key".to_owned(),
            ));
        }
    }
    Ok(())
}

fn vertex_evidence_columns(
    vertices: &[&KernelVertex],
    evidence: &HashMap<&str, u32>,
) -> Result<(Vec<LeU64>, Vec<LeU32>), DiscoveryViewError> {
    evidence_columns(
        vertices
            .iter()
            .map(|vertex| vertex.provenance.evidence_refs.as_slice()),
        evidence,
    )
}

fn edge_evidence_columns(
    edges: &[&KernelEdge],
    evidence: &HashMap<&str, u32>,
) -> Result<(Vec<LeU64>, Vec<LeU32>), DiscoveryViewError> {
    evidence_columns(
        edges
            .iter()
            .map(|edge| edge.provenance.evidence_refs.as_slice()),
        evidence,
    )
}

fn evidence_columns<'a>(
    rows: impl Iterator<Item = &'a [String]>,
    evidence: &HashMap<&str, u32>,
) -> Result<(Vec<LeU64>, Vec<LeU32>), DiscoveryViewError> {
    let mut offsets = vec![LeU64::new(0)];
    let mut indices = Vec::new();
    for values in rows {
        let mut values = values
            .iter()
            .filter_map(|value| (!value.is_empty()).then_some(value.as_str()))
            .collect::<SmallVec<[&str; 4]>>();
        values.sort_unstable();
        values.dedup();
        for value in values {
            let index = evidence.get(value).ok_or_else(|| {
                DiscoveryViewError::Invalid(format!("evidence identity disappeared: {value}"))
            })?;
            indices.push(LeU32::new(*index));
        }
        offsets.push(LeU64::new(indices.len() as u64));
    }
    Ok((offsets, indices))
}

fn adjacency(
    node_count: usize,
    endpoints: impl Iterator<Item = u32> + Clone,
) -> Result<(Vec<LeU64>, Vec<LeU32>), DiscoveryViewError> {
    let mut offsets = vec![0_u64; node_count + 1];
    let mut edge_count = 0_usize;
    for endpoint in endpoints.clone() {
        let slot = endpoint as usize;
        if slot >= node_count {
            return Err(DiscoveryViewError::Invalid(
                "CSR endpoint is out of range".to_owned(),
            ));
        }
        offsets[slot + 1] += 1;
        edge_count += 1;
    }
    for index in 1..offsets.len() {
        offsets[index] += offsets[index - 1];
    }
    let mut cursor = offsets[..node_count].to_vec();
    let mut edges = vec![LeU32::new(0); edge_count];
    for (edge, endpoint) in endpoints.enumerate() {
        let slot = endpoint as usize;
        let destination = cursor[slot] as usize;
        edges[destination] = LeU32::new(u32::try_from(edge).map_err(|_| {
            DiscoveryViewError::Invalid("edge count exceeds u32 capacity".to_owned())
        })?);
        cursor[slot] += 1;
    }
    Ok((offsets.into_iter().map(LeU64::new).collect(), edges))
}

fn identity_slab(
    vertices: &[&KernelVertex],
    evidence: &[&str],
) -> Result<(Vec<IdentityRefRecord>, Vec<u8>), DiscoveryViewError> {
    let capacity = vertices
        .iter()
        .map(|vertex| vertex.id.0.len())
        .chain(evidence.iter().map(|value| value.len()))
        .sum();
    let mut slab = Vec::with_capacity(capacity);
    let mut refs = Vec::with_capacity(vertices.len() + evidence.len());
    for vertex in vertices {
        push_identity(&mut refs, &mut slab, &vertex.id.0)?;
    }
    for value in evidence {
        push_identity(&mut refs, &mut slab, value)?;
    }
    Ok((refs, slab))
}

fn push_identity(
    refs: &mut Vec<IdentityRefRecord>,
    slab: &mut Vec<u8>,
    value: &str,
) -> Result<(), DiscoveryViewError> {
    let offset = slab.len() as u64;
    slab.extend_from_slice(value.as_bytes());
    refs.push(IdentityRefRecord::new(
        offset,
        u32::try_from(value.len()).map_err(|_| {
            DiscoveryViewError::Invalid("identity string exceeds u32 capacity".to_owned())
        })?,
    ));
    Ok(())
}
