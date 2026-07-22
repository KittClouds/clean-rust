use crate::{
    CandidateGenerationPerformanceCertificate, CandidateGenerationPerformanceReceipt, ExactRange,
    FrozenDecisionTrajectoryTables, FrozenGraphDecisionTrajectoryError,
    FrozenGraphDecisionTrajectoryManifest, FrozenSplitIndexRecord,
    FROZEN_GRAPH_DECISION_SECTION_COUNT, FROZEN_GRAPH_DECISION_TRAJECTORIES_BINARY_VERSION,
    FROZEN_GRAPH_DECISION_TRAJECTORIES_SCHEMA,
};
use compact_str::CompactString;
use hashbrown::HashSet;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

const MAGIC: [u8; 8] = *b"PHXFGD01";
const HEADER_BYTES: usize = 8 + 2 + 2 + 8 + FROZEN_GRAPH_DECISION_SECTION_COUNT * 16;
const PERFORMANCE_SCHEMA: &str = "phoenix-candidate-generation-performance/v1";
type EncodedDecisionBinary = (Vec<u8>, Vec<(u64, u64)>);

pub(crate) fn encode_sections(
    tables: &FrozenDecisionTrajectoryTables,
) -> Result<Vec<Vec<u8>>, FrozenGraphDecisionTrajectoryError> {
    Ok(vec![
        serde_json::to_vec(&tables.decisions)?,
        serde_json::to_vec(&tables.states)?,
        serde_json::to_vec(&tables.candidate_groups)?,
        serde_json::to_vec(&tables.candidate_actions)?,
        serde_json::to_vec(&tables.selected_actions)?,
        serde_json::to_vec(&tables.evidence)?,
        serde_json::to_vec(&tables.rewards)?,
        serde_json::to_vec(&tables.deltas)?,
        serde_json::to_vec(&tables.split_index)?,
        serde_json::to_vec(&tables.provenance)?,
    ])
}

pub(crate) fn encode_binary(
    sections: &[Vec<u8>],
) -> Result<EncodedDecisionBinary, FrozenGraphDecisionTrajectoryError> {
    if sections.len() != FROZEN_GRAPH_DECISION_SECTION_COUNT {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "section count",
        ));
    }
    let total = sections
        .iter()
        .try_fold(HEADER_BYTES, |sum, section| sum.checked_add(section.len()))
        .ok_or(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "binary size overflow",
        ))?;
    let mut bytes = vec![0_u8; HEADER_BYTES];
    bytes[..8].copy_from_slice(&MAGIC);
    bytes[8..10].copy_from_slice(&FROZEN_GRAPH_DECISION_TRAJECTORIES_BINARY_VERSION.to_le_bytes());
    bytes[10..12].copy_from_slice(&(FROZEN_GRAPH_DECISION_SECTION_COUNT as u16).to_le_bytes());
    bytes[12..20].copy_from_slice(&(total as u64).to_le_bytes());
    let mut spans = Vec::with_capacity(sections.len());
    let mut offset = HEADER_BYTES;
    for (index, section) in sections.iter().enumerate() {
        let directory = 20 + index * 16;
        bytes[directory..directory + 8].copy_from_slice(&(offset as u64).to_le_bytes());
        bytes[directory + 8..directory + 16].copy_from_slice(&(section.len() as u64).to_le_bytes());
        spans.push((offset as u64, section.len() as u64));
        bytes.extend_from_slice(section);
        offset += section.len();
    }
    Ok((bytes, spans))
}

pub(crate) fn decode_header(
    bytes: &[u8],
) -> Result<Vec<(u64, u64)>, FrozenGraphDecisionTrajectoryError> {
    if bytes.len() < HEADER_BYTES
        || bytes[..8] != MAGIC
        || read_u16(bytes, 8)? != FROZEN_GRAPH_DECISION_TRAJECTORIES_BINARY_VERSION
        || read_u16(bytes, 10)? as usize != FROZEN_GRAPH_DECISION_SECTION_COUNT
        || read_u64(bytes, 12)? != bytes.len() as u64
    {
        return Err(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
            "binary header",
        ));
    }
    let mut spans = Vec::with_capacity(FROZEN_GRAPH_DECISION_SECTION_COUNT);
    let mut expected = HEADER_BYTES as u64;
    for index in 0..FROZEN_GRAPH_DECISION_SECTION_COUNT {
        let directory = 20 + index * 16;
        let offset = read_u64(bytes, directory)?;
        let length = read_u64(bytes, directory + 8)?;
        if offset != expected || offset.checked_add(length).is_none() {
            return Err(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
                "section range",
            ));
        }
        expected += length;
        spans.push((offset, length));
    }
    if expected != bytes.len() as u64 {
        return Err(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
            "section coverage",
        ));
    }
    Ok(spans)
}

pub(crate) fn validate_manifest_shape(
    manifest: &FrozenGraphDecisionTrajectoryManifest,
) -> Result<(), FrozenGraphDecisionTrajectoryError> {
    if manifest.schema_version != FROZEN_GRAPH_DECISION_TRAJECTORIES_SCHEMA
        || manifest.dataset_id.trim().is_empty()
        || manifest.binary_file.trim().is_empty()
        || manifest.sections.len() != FROZEN_GRAPH_DECISION_SECTION_COUNT
        || !manifest.leakage_certificate.passes()
    {
        return Err(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
            "manifest contract",
        ));
    }
    Ok(())
}

pub(crate) fn validate_flat_tables(
    tables: &FrozenDecisionTrajectoryTables,
    manifest: &FrozenGraphDecisionTrajectoryManifest,
) -> Result<(), FrozenGraphDecisionTrajectoryError> {
    let count = tables.decisions.len();
    if count == 0
        || tables.states.len() != count
        || tables.candidate_groups.len() != count
        || tables.selected_actions.len() != count
        || tables.rewards.len() != count
        || tables.deltas.len() != count
        || tables.split_index.len() != count
        || tables.provenance.entries.len() != count
        || manifest.decisions != count as u64
        || manifest.candidates != tables.candidate_actions.len() as u64
        || tables.provenance.leakage_certificate != manifest.leakage_certificate
        || tables.provenance.candidate_certificate != manifest.candidate_certificate
        || !tables.provenance.leakage_certificate.passes()
    {
        return Err(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
            "section cardinality",
        ));
    }
    for (ordinal, decision) in tables.decisions.iter().enumerate() {
        validate_range(decision.candidate_actions, tables.candidate_actions.len())?;
        validate_range(decision.evidence, tables.evidence.len())?;
        if decision.state_ordinal != ordinal as u64
            || decision.candidate_group_ordinal != ordinal as u64
            || decision.selected_label_ordinal != ordinal as u64
            || decision.reward_ordinal != ordinal as u64
            || decision.delta_ordinal != ordinal as u64
            || decision.provenance_ordinal != ordinal as u64
            || tables.candidate_groups[ordinal].action_range != decision.candidate_actions
            || tables.split_index[ordinal].decision_ordinal != ordinal as u64
            || tables.split_index[ordinal].split != decision.split
            || tables.selected_actions[ordinal].selected_candidate_ordinal
                < decision.candidate_actions.offset
            || tables.selected_actions[ordinal].selected_candidate_ordinal
                >= decision.candidate_actions.end().unwrap_or(0)
        {
            return Err(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
                "record references",
            ));
        }
        tables.selected_actions[ordinal].action.validate()?;
        tables.rewards[ordinal].validate()?;
    }
    Ok(())
}

fn validate_range(
    range: ExactRange,
    available: usize,
) -> Result<(), FrozenGraphDecisionTrajectoryError> {
    if range.end().is_none_or(|end| end > available as u64) {
        return Err(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
            "exact range",
        ));
    }
    Ok(())
}

pub(crate) fn checked_section(
    bytes: &[u8],
    offset: u64,
    length: u64,
) -> Result<&[u8], FrozenGraphDecisionTrajectoryError> {
    let start = usize::try_from(offset)
        .map_err(|_| FrozenGraphDecisionTrajectoryError::CorruptArtifact("section offset"))?;
    let len = usize::try_from(length)
        .map_err(|_| FrozenGraphDecisionTrajectoryError::CorruptArtifact("section length"))?;
    let end = start
        .checked_add(len)
        .ok_or(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
            "section overflow",
        ))?;
    bytes
        .get(start..end)
        .ok_or(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
            "section bounds",
        ))
}

pub(crate) fn validate_performance(
    tables: &FrozenDecisionTrajectoryTables,
    performance: &[CandidateGenerationPerformanceReceipt],
) -> Result<(), FrozenGraphDecisionTrajectoryError> {
    if performance.len() != tables.candidate_groups.len() {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "candidate performance count",
        ));
    }
    let identities = performance
        .iter()
        .map(|receipt| receipt.candidate_identity.as_str())
        .collect::<HashSet<_>>();
    let invalid_metrics = performance
        .iter()
        .any(|receipt| receipt.generation_latency_ns == 0 || receipt.allocation_volume_bytes == 0);
    if identities.len() != performance.len()
        || invalid_metrics
        || tables
            .candidate_groups
            .iter()
            .any(|group| !identities.contains(group.candidate_identity.as_str()))
    {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "candidate performance receipt",
        ));
    }
    Ok(())
}

pub(crate) fn performance_certificate(
    dataset_id: &CompactString,
    groups: Vec<CandidateGenerationPerformanceReceipt>,
) -> Result<CandidateGenerationPerformanceCertificate, FrozenGraphDecisionTrajectoryError> {
    let generation_latency_ns = groups
        .iter()
        .try_fold(0_u64, |sum, item| {
            sum.checked_add(item.generation_latency_ns)
        })
        .ok_or(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "performance latency overflow",
        ))?;
    let allocation_volume_bytes = groups
        .iter()
        .try_fold(0_u64, |sum, item| {
            sum.checked_add(item.allocation_volume_bytes)
        })
        .ok_or(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "performance allocation overflow",
        ))?;
    let mut identity_input = serde_json::to_vec(&groups)?;
    identity_input.extend_from_slice(dataset_id.as_bytes());
    let receipt_id: CompactString = format!("b3-{}", blake3::hash(&identity_input).to_hex()).into();
    Ok(CandidateGenerationPerformanceCertificate {
        schema_version: PERFORMANCE_SCHEMA.into(),
        dataset_id: dataset_id.clone(),
        receipt_id,
        group_count: groups.len() as u64,
        generation_latency_ns,
        allocation_volume_bytes,
        groups,
    })
}

pub(crate) fn split_counts(index: &[FrozenSplitIndexRecord]) -> [u64; 3] {
    let mut counts = [0_u64; 3];
    for item in index {
        counts[item.split as usize - 1] += 1;
    }
    counts
}

pub(crate) fn leakage_failure(
    certificate: &crate::GraphDecisionLeakageCertificate,
) -> &'static str {
    if certificate.missing_correct_actions > 0 {
        "correct action candidate coverage"
    } else if certificate.evidence_after_cutoff > 0 {
        "evidence after observation cutoff"
    } else if certificate.post_decision_edges_in_pre_state > 0 {
        "post-decision edge in pre-state"
    } else if certificate.duplicate_fingerprints_across_splits > 0 {
        "duplicate decision fingerprint across splits"
    } else if certificate.future_episode_memberships_exposed > 0 {
        "future episode membership exposed"
    } else if certificate.held_out_facts_in_training_topology > 0 {
        "held-out fact in training topology"
    } else if certificate.outcomes_used_as_inputs > 0 {
        "outcome used as input"
    } else {
        "candidate generation influenced by held-out label"
    }
}

fn read_u16(bytes: &[u8], offset: usize) -> Result<u16, FrozenGraphDecisionTrajectoryError> {
    Ok(u16::from_le_bytes(
        bytes
            .get(offset..offset + 2)
            .ok_or(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
                "u16 range",
            ))?
            .try_into()
            .map_err(|_| FrozenGraphDecisionTrajectoryError::CorruptArtifact("u16"))?,
    ))
}

fn read_u64(bytes: &[u8], offset: usize) -> Result<u64, FrozenGraphDecisionTrajectoryError> {
    Ok(u64::from_le_bytes(
        bytes
            .get(offset..offset + 8)
            .ok_or(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
                "u64 range",
            ))?
            .try_into()
            .map_err(|_| FrozenGraphDecisionTrajectoryError::CorruptArtifact("u64"))?,
    ))
}

pub(crate) fn write_immutable(
    path: &Path,
    bytes: &[u8],
) -> Result<(), FrozenGraphDecisionTrajectoryError> {
    if path.exists() {
        return if std::fs::read(path)? == bytes {
            Ok(())
        } else {
            Err(FrozenGraphDecisionTrajectoryError::ArtifactExists(
                path.to_path_buf(),
            ))
        };
    }
    let temporary = temporary_path(path);
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)?;
    if let Err(error) = file.write_all(bytes).and_then(|_| file.sync_all()) {
        let _ = std::fs::remove_file(&temporary);
        return Err(error.into());
    }
    if path.exists() {
        let _ = std::fs::remove_file(&temporary);
        return if std::fs::read(path)? == bytes {
            Ok(())
        } else {
            Err(FrozenGraphDecisionTrajectoryError::ArtifactExists(
                path.to_path_buf(),
            ))
        };
    }
    std::fs::rename(temporary, path)?;
    Ok(())
}

fn temporary_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("decision-trajectories");
    path.with_file_name(format!(".{name}.tmp-{}", std::process::id()))
}
