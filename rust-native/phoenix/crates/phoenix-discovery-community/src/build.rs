use crate::format::{
    content_address, hex, parse_hex, BinaryHeader, CommunityArtifactManifest,
    CommunitySectionManifest, SectionHeader, SectionKind, ALIGNMENT, BINARY_FILE,
    COMMUNITY_ARTIFACT_SCHEMA, HEADER_BYTES, MANIFEST_FILE, SECTION_COUNT,
};
use crate::graph::SemanticCoreGraph;
use crate::leiden::{deterministic_leiden, PartitionResult};
use crate::metrics::{compute_metrics, CommunityMetrics};
use crate::{CommunityArtifactError, DeterministicCommunityPolicy};
use phoenix_discovery_view::{AssertedDiscoveryView, DiscoveryRelationPolicy};
use std::fs::{self, File, OpenOptions};
use std::io::{BufReader, BufWriter, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use zerocopy::AsBytes;

static BUILD_SEQUENCE: AtomicU64 = AtomicU64::new(1);

pub fn write_deterministic_community_artifact(
    source: &AssertedDiscoveryView,
    relation_policy: &DiscoveryRelationPolicy,
    policy: &DeterministicCommunityPolicy,
    artifact_root: impl AsRef<Path>,
) -> Result<CommunityArtifactManifest, CommunityArtifactError> {
    policy.validate(relation_policy)?;
    let graph = SemanticCoreGraph::build(source, relation_policy, policy)?;
    let partition = deterministic_leiden(&graph, policy)?;
    let metrics = compute_metrics(&graph, &partition, policy)?;
    let root = artifact_root.as_ref();
    fs::create_dir_all(root)?;
    let temporary = temporary_directory(root, source.manifest().generation)?;
    let result = write_artifact(
        source,
        relation_policy,
        policy,
        &graph,
        &partition,
        &metrics,
        &temporary,
    );
    let manifest = match result {
        Ok(manifest) => manifest,
        Err(error) => {
            let _ = fs::remove_dir_all(&temporary);
            return Err(error);
        }
    };
    let final_directory = root.join(&manifest.artifact_digest);
    match fs::rename(&temporary, &final_directory) {
        Ok(()) => Ok(manifest),
        Err(_) if final_directory.exists() => {
            fs::remove_dir_all(&temporary)?;
            let existing = crate::DeterministicCommunityArtifact::open(&final_directory)?;
            if existing.manifest() == &manifest {
                Ok(manifest)
            } else {
                Err(CommunityArtifactError::Invalid(format!(
                    "community content address {} resolves to a different manifest",
                    manifest.artifact_digest
                )))
            }
        }
        Err(error) => {
            let _ = fs::remove_dir_all(&temporary);
            Err(error.into())
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn write_artifact(
    source: &AssertedDiscoveryView,
    relation_policy: &DiscoveryRelationPolicy,
    policy: &DeterministicCommunityPolicy,
    graph: &SemanticCoreGraph,
    partition: &PartitionResult,
    metrics: &CommunityMetrics,
    directory: &Path,
) -> Result<CommunityArtifactManifest, CommunityArtifactError> {
    let binary_path = directory.join(BINARY_FILE);
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&binary_path)?;
    let mut writer = BinaryWriter::new(file)?;
    writer.section(SectionKind::NodeCommunity, &partition.node_community)?;
    writer.section(
        SectionKind::CommunityStableHash,
        &partition
            .communities
            .iter()
            .map(|community| community.stable.hash)
            .collect::<Vec<_>>(),
    )?;
    writer.section(
        SectionKind::CommunityCollision,
        &partition
            .communities
            .iter()
            .map(|community| community.stable.collision)
            .collect::<Vec<_>>(),
    )?;
    writer.section(
        SectionKind::CommunityComponent,
        &partition
            .communities
            .iter()
            .map(|community| community.component)
            .collect::<Vec<_>>(),
    )?;
    writer.section(
        SectionKind::CommunitySize,
        &partition
            .communities
            .iter()
            .map(|community| community.size)
            .collect::<Vec<_>>(),
    )?;
    writer.section(SectionKind::AffinityOffsets, &metrics.affinity_offsets)?;
    writer.section(SectionKind::AffinityTargets, &metrics.affinity_targets)?;
    writer.section(SectionKind::AffinityWeights, &metrics.affinity_weights)?;
    writer.section(
        SectionKind::BridgeNodes,
        &metrics
            .bridges
            .iter()
            .map(|bridge| bridge.node)
            .collect::<Vec<_>>(),
    )?;
    writer.section(
        SectionKind::BridgeNeighborCommunities,
        &metrics
            .bridges
            .iter()
            .map(|bridge| bridge.neighboring_communities)
            .collect::<Vec<_>>(),
    )?;
    writer.section(
        SectionKind::BridgeTotalStrength,
        &metrics
            .bridges
            .iter()
            .map(|bridge| bridge.total_strength)
            .collect::<Vec<_>>(),
    )?;
    writer.section(
        SectionKind::BridgeBoundaryStrength,
        &metrics
            .bridges
            .iter()
            .map(|bridge| bridge.boundary_strength)
            .collect::<Vec<_>>(),
    )?;
    writer.section(
        SectionKind::BridgeParticipation,
        &metrics
            .bridges
            .iter()
            .map(|bridge| bridge.participation_micros)
            .collect::<Vec<_>>(),
    )?;
    writer.section(
        SectionKind::BridgeBoundary,
        &metrics
            .bridges
            .iter()
            .map(|bridge| bridge.boundary_micros)
            .collect::<Vec<_>>(),
    )?;
    writer.section(
        SectionKind::BridgeConductance,
        &metrics
            .bridges
            .iter()
            .map(|bridge| bridge.conductance_micros)
            .collect::<Vec<_>>(),
    )?;
    writer.section(
        SectionKind::BridgeScore,
        &metrics
            .bridges
            .iter()
            .map(|bridge| bridge.score_micros)
            .collect::<Vec<_>>(),
    )?;
    let (mut file, sections) = writer.finish()?;
    let payload_digest = payload_digest(&mut file, sections[0].offset())?;
    let source_digest = required_digest(
        &source.manifest().artifact_digest,
        "source discovery artifact",
    )?;
    let relation_digest =
        required_digest(&source.manifest().relation_policy_digest, "relation policy")?;
    let policy_digest = policy.digest(relation_policy)?;
    let artifact_digest = content_address(
        source.manifest().generation,
        source_digest,
        relation_digest,
        policy_digest,
        payload_digest,
        [
            graph.node_count as u64,
            graph.core_nodes.len() as u64,
            graph.edges.len() as u64,
            graph.component_count() as u64,
            partition.communities.len() as u64,
            metrics.affinity_targets.len() as u64,
            metrics.bridges.len() as u64,
        ],
    );
    let header = BinaryHeader::new(
        source.manifest().generation,
        graph.node_count,
        graph.core_nodes.len(),
        graph.edges.len(),
        graph.component_count(),
        partition.communities.len(),
        metrics.affinity_targets.len(),
        metrics.bridges.len(),
        artifact_digest,
        payload_digest,
        source_digest,
        relation_digest,
        policy_digest,
        sections,
    );
    file.seek(SeekFrom::Start(0))?;
    file.write_all(header.as_bytes())?;
    file.sync_all()?;
    let binary_bytes = file.metadata()?.len();
    let manifest = CommunityArtifactManifest {
        schema_version: COMMUNITY_ARTIFACT_SCHEMA.to_owned(),
        artifact_digest: hex(&artifact_digest),
        payload_digest: hex(&payload_digest),
        source_discovery_digest: hex(&source_digest),
        generation: source.manifest().generation,
        relation_policy_digest: hex(&relation_digest),
        community_policy_id: policy.policy_id().to_owned(),
        community_policy_version: policy.policy_version().to_owned(),
        community_policy_digest: hex(&policy_digest),
        node_count: graph.node_count as u64,
        core_node_count: graph.core_nodes.len() as u64,
        selected_edge_count: graph.edges.len() as u64,
        component_count: graph.component_count() as u64,
        community_count: partition.communities.len() as u64,
        affinity_count: metrics.affinity_targets.len() as u64,
        bridge_count: metrics.bridges.len() as u64,
        admitted_candidate_edges: 0,
        binary_file: BINARY_FILE.to_owned(),
        binary_bytes,
        sections: sections
            .iter()
            .map(|section| CommunitySectionManifest {
                kind: section.kind(),
                offset: section.offset(),
                count: section.count(),
                element_bytes: u32::from(section.element_bytes()),
            })
            .collect(),
    };
    let manifest_file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(directory.join(MANIFEST_FILE))?;
    let mut manifest_writer = BufWriter::new(manifest_file);
    serde_json::to_writer(&mut manifest_writer, &manifest)?;
    manifest_writer.write_all(b"\n")?;
    manifest_writer.flush()?;
    manifest_writer.get_ref().sync_all()?;
    Ok(manifest)
}

fn payload_digest(file: &mut File, offset: u64) -> Result<[u8; 32], CommunityArtifactError> {
    file.seek(SeekFrom::Start(offset))?;
    let mut reader = BufReader::new(file);
    let mut hasher = blake3::Hasher::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(*hasher.finalize().as_bytes())
}

fn required_digest(value: &str, kind: &str) -> Result<[u8; 32], CommunityArtifactError> {
    parse_hex(value)
        .ok_or_else(|| CommunityArtifactError::Invalid(format!("{kind} digest is malformed")))
}

fn temporary_directory(root: &Path, generation: u64) -> Result<PathBuf, CommunityArtifactError> {
    let sequence = BUILD_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let path = root.join(format!(
        ".building-{}-{generation}-{sequence}",
        std::process::id()
    ));
    fs::create_dir(&path)?;
    Ok(path)
}

trait LittleEndianValue: Copy {
    const BYTES: usize;
    fn write_le(self, writer: &mut impl Write) -> std::io::Result<()>;
}

macro_rules! little_endian_value {
    ($type:ty) => {
        impl LittleEndianValue for $type {
            const BYTES: usize = std::mem::size_of::<Self>();
            fn write_le(self, writer: &mut impl Write) -> std::io::Result<()> {
                writer.write_all(&self.to_le_bytes())
            }
        }
    };
}

little_endian_value!(u16);
little_endian_value!(u32);
little_endian_value!(u64);

struct BinaryWriter {
    writer: BufWriter<File>,
    sections: Vec<SectionHeader>,
}

impl BinaryWriter {
    fn new(file: File) -> Result<Self, CommunityArtifactError> {
        let mut writer = BufWriter::new(file);
        writer.write_all(&vec![0_u8; HEADER_BYTES])?;
        Ok(Self {
            writer,
            sections: Vec::with_capacity(SECTION_COUNT),
        })
    }

    fn section<T: LittleEndianValue>(
        &mut self,
        kind: SectionKind,
        values: &[T],
    ) -> Result<(), CommunityArtifactError> {
        let position = self.writer.stream_position()?;
        let aligned = position.div_ceil(ALIGNMENT) * ALIGNMENT;
        if aligned > position {
            self.writer
                .write_all(&vec![0_u8; (aligned - position) as usize])?;
        }
        for &value in values {
            value.write_le(&mut self.writer)?;
        }
        self.sections
            .push(SectionHeader::new(kind, T::BYTES, aligned, values.len()));
        Ok(())
    }

    fn finish(mut self) -> Result<(File, [SectionHeader; SECTION_COUNT]), CommunityArtifactError> {
        self.writer.flush()?;
        let file = self
            .writer
            .into_inner()
            .map_err(|error| error.into_error())?;
        let sections: [SectionHeader; SECTION_COUNT] = self.sections.try_into().map_err(|_| {
            CommunityArtifactError::Invalid("binary section count mismatch".to_owned())
        })?;
        Ok((file, sections))
    }
}
