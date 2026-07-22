use crate::decision_trajectory_binary::*;
use crate::{
    candidate_group_identity, graph_decision_candidate_identity, CandidateDatasetCertificate,
    CandidateGenerationPerformanceReceipt, CandidateSourceCount, DecisionCandidateSourceKind,
    ExactRange, FrozenCandidateGroupRecord, FrozenDecisionProvenanceSection, FrozenDecisionRecord,
    FrozenDecisionSectionKind, FrozenDecisionSectionManifest, FrozenDecisionTrajectoryTables,
    FrozenGraphDecisionTrajectoryError, FrozenGraphDecisionTrajectoryManifest,
    FrozenGraphDecisionTrajectoryPaths, FrozenSelectedActionRecord, FrozenSplitIndexRecord,
    FrozenStateIdentityRecord, GraphDecisionLeakageCertificate, GraphDecisionSplit,
    GraphDecisionTrajectoryExample, FROZEN_GRAPH_DECISION_TRAJECTORIES_SCHEMA,
};
use compact_str::CompactString;
use hashbrown::{HashMap, HashSet};
use memmap2::Mmap;
use serde::de::DeserializeOwned;
use std::fs::File;
use std::path::Path;

pub struct FrozenGraphDecisionTrajectoryBundle;

impl FrozenGraphDecisionTrajectoryBundle {
    pub fn write(
        examples: Vec<GraphDecisionTrajectoryExample>,
        performance: Vec<CandidateGenerationPerformanceReceipt>,
        root: impl AsRef<Path>,
    ) -> Result<FrozenGraphDecisionTrajectoryPaths, FrozenGraphDecisionTrajectoryError> {
        let tables = flatten_and_certify(examples)?;
        validate_performance(&tables, &performance)?;
        let section_bytes = encode_sections(&tables)?;
        let (binary, section_spans) = encode_binary(&section_bytes)?;
        let binary_digest = format!("b3-{}", blake3::hash(&binary).to_hex());
        let dataset_id: CompactString = binary_digest.clone().into();
        let section_manifests = section_bytes
            .iter()
            .zip(section_spans)
            .zip(FrozenDecisionSectionKind::ALL)
            .map(
                |((bytes, (offset, length)), kind)| FrozenDecisionSectionManifest {
                    kind,
                    offset,
                    length,
                    blake3: format!("b3-{}", blake3::hash(bytes).to_hex()).into(),
                },
            )
            .collect::<Vec<_>>();
        let binary_name = format!("{dataset_id}.fgdt");
        let manifest_name = format!("{dataset_id}.manifest.json");
        let split_counts = split_counts(&tables.split_index);
        let manifest = FrozenGraphDecisionTrajectoryManifest {
            schema_version: FROZEN_GRAPH_DECISION_TRAJECTORIES_SCHEMA.into(),
            dataset_id: dataset_id.clone(),
            binary_file: binary_name.clone().into(),
            binary_blake3: binary_digest.into(),
            binary_bytes: binary.len() as u64,
            decisions: tables.decisions.len() as u64,
            candidates: tables.candidate_actions.len() as u64,
            train_decisions: split_counts[0],
            validation_decisions: split_counts[1],
            test_decisions: split_counts[2],
            sections: section_manifests,
            leakage_certificate: tables.provenance.leakage_certificate.clone(),
            candidate_certificate: tables.provenance.candidate_certificate.clone(),
        };
        let performance_certificate = performance_certificate(&dataset_id, performance)?;
        let performance_bytes = serde_json::to_vec_pretty(&performance_certificate)?;
        let performance_name = format!(
            "{}.candidate-performance.json",
            performance_certificate.receipt_id
        );
        let manifest_bytes = serde_json::to_vec_pretty(&manifest)?;

        let root = root.as_ref();
        std::fs::create_dir_all(root)?;
        let binary_path = root.join(binary_name);
        let performance_path = root.join(performance_name);
        let manifest_path = root.join(manifest_name);
        write_immutable(&binary_path, &binary)?;
        write_immutable(&performance_path, &performance_bytes)?;
        write_immutable(&manifest_path, &manifest_bytes)?;
        Ok(FrozenGraphDecisionTrajectoryPaths {
            manifest: manifest_path,
            binary: binary_path,
            performance_receipt: performance_path,
            dataset_id,
        })
    }
}

pub struct FrozenGraphDecisionTrajectoryMapped {
    manifest: FrozenGraphDecisionTrajectoryManifest,
    mmap: Mmap,
}

impl FrozenGraphDecisionTrajectoryMapped {
    pub fn open(
        manifest_path: impl AsRef<Path>,
    ) -> Result<Self, FrozenGraphDecisionTrajectoryError> {
        let manifest_path = manifest_path.as_ref();
        let manifest: FrozenGraphDecisionTrajectoryManifest =
            serde_json::from_slice(&std::fs::read(manifest_path)?)?;
        validate_manifest_shape(&manifest)?;
        let binary_path = manifest_path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join(manifest.binary_file.as_str());
        let file = File::open(binary_path)?;
        let mmap = unsafe { Mmap::map(&file)? };
        if mmap.len() as u64 != manifest.binary_bytes
            || format!("b3-{}", blake3::hash(&mmap).to_hex()) != manifest.binary_blake3
            || format!("b3-{}", blake3::hash(&mmap).to_hex()) != manifest.dataset_id
        {
            return Err(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
                "binary identity",
            ));
        }
        let spans = decode_header(&mmap)?;
        for ((section, (offset, length)), kind) in manifest
            .sections
            .iter()
            .zip(spans)
            .zip(FrozenDecisionSectionKind::ALL)
        {
            if section.kind != kind || section.offset != offset || section.length != length {
                return Err(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
                    "section directory",
                ));
            }
            let bytes = checked_section(&mmap, offset, length)?;
            if format!("b3-{}", blake3::hash(bytes).to_hex()) != section.blake3 {
                return Err(FrozenGraphDecisionTrajectoryError::CorruptArtifact(
                    "section identity",
                ));
            }
        }
        let mapped = Self { manifest, mmap };
        let tables = mapped.tables()?;
        validate_flat_tables(&tables, &mapped.manifest)?;
        Ok(mapped)
    }

    pub fn manifest(&self) -> &FrozenGraphDecisionTrajectoryManifest {
        &self.manifest
    }

    pub fn section_bytes(&self, kind: FrozenDecisionSectionKind) -> &[u8] {
        let section = &self.manifest.sections[kind as usize - 1];
        let start = section.offset as usize;
        let end = start + section.length as usize;
        &self.mmap[start..end]
    }

    pub fn tables(
        &self,
    ) -> Result<FrozenDecisionTrajectoryTables, FrozenGraphDecisionTrajectoryError> {
        Ok(FrozenDecisionTrajectoryTables {
            decisions: self.decode(FrozenDecisionSectionKind::DecisionRecords)?,
            states: self.decode(FrozenDecisionSectionKind::PreStateIdentities)?,
            candidate_groups: self.decode(FrozenDecisionSectionKind::CandidateGroupOffsets)?,
            candidate_actions: self.decode(FrozenDecisionSectionKind::CandidateActionPayloads)?,
            selected_actions: self.decode(FrozenDecisionSectionKind::SelectedActionLabels)?,
            evidence: self.decode(FrozenDecisionSectionKind::EvidenceReferences)?,
            rewards: self.decode(FrozenDecisionSectionKind::RewardVectors)?,
            deltas: self.decode(FrozenDecisionSectionKind::GraphDeltaReferences)?,
            split_index: self.decode(FrozenDecisionSectionKind::TemporalSplitIndex)?,
            provenance: self.decode(FrozenDecisionSectionKind::ProvenanceLeakageCertificate)?,
        })
    }

    fn decode<T: DeserializeOwned>(
        &self,
        kind: FrozenDecisionSectionKind,
    ) -> Result<T, FrozenGraphDecisionTrajectoryError> {
        Ok(serde_json::from_slice(self.section_bytes(kind))?)
    }
}

fn flatten_and_certify(
    mut examples: Vec<GraphDecisionTrajectoryExample>,
) -> Result<FrozenDecisionTrajectoryTables, FrozenGraphDecisionTrajectoryError> {
    if examples.is_empty() {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput("examples"));
    }
    examples.sort_unstable_by(|left, right| {
        left.observation_cutoff
            .cmp(&right.observation_cutoff)
            .then_with(|| left.decision_id.cmp(&right.decision_id))
    });
    validate_temporal_split(&examples)?;

    let mut decisions = Vec::with_capacity(examples.len());
    let mut states = Vec::with_capacity(examples.len());
    let mut groups = Vec::with_capacity(examples.len());
    let candidate_capacity = examples
        .iter()
        .map(|example| example.candidate_group.candidates.len())
        .sum();
    let evidence_capacity = examples
        .iter()
        .map(|example| example.evidence_references.len())
        .sum();
    let mut candidates = Vec::with_capacity(candidate_capacity);
    let mut selected = Vec::with_capacity(examples.len());
    let mut evidence = Vec::with_capacity(evidence_capacity);
    let mut rewards = Vec::with_capacity(examples.len());
    let mut deltas = Vec::with_capacity(examples.len());
    let mut split_index = Vec::with_capacity(examples.len());
    let mut provenance = Vec::with_capacity(examples.len());
    let mut decision_ids = HashSet::with_capacity(examples.len());
    let mut group_ids = HashSet::with_capacity(examples.len());
    let mut fingerprints = HashMap::with_capacity(examples.len());
    let mut leakage = GraphDecisionLeakageCertificate {
        decisions_checked: examples.len() as u64,
        evidence_checked: evidence_capacity as u64,
        correct_action_candidate_coverage_basis_points: 10_000,
        missing_correct_actions: 0,
        evidence_after_cutoff: 0,
        post_decision_edges_in_pre_state: 0,
        duplicate_fingerprints_across_splits: 0,
        future_episode_memberships_exposed: 0,
        held_out_facts_in_training_topology: 0,
        outcomes_used_as_inputs: 0,
        label_influenced_candidate_groups: 0,
    };

    for example in examples {
        validate_example_shape(&example)?;
        if !decision_ids.insert(example.decision_id.clone()) {
            return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
                "duplicate decision id",
            ));
        }
        if !group_ids.insert(example.candidate_group.candidate_group_id.clone()) {
            return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
                "duplicate candidate group id",
            ));
        }
        if let Some(prior_split) = fingerprints.insert(
            example.provenance.decision_fingerprint.clone(),
            example.split,
        ) {
            if prior_split != example.split {
                leakage.duplicate_fingerprints_across_splits += 1;
            } else {
                return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
                    "duplicate decision fingerprint",
                ));
            }
        }
        accumulate_leakage(&example, &mut leakage);

        let action_offset = candidates.len() as u64;
        let expected_group_identity = candidate_group_identity(&example.candidate_group.candidates);
        if expected_group_identity != example.candidate_group.generation.candidate_identity
            || example.candidate_group.generation.candidate_count as usize
                != example.candidate_group.candidates.len()
        {
            return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
                "candidate generation receipt",
            ));
        }
        let selected_identity = graph_decision_candidate_identity(&example.selected_action)?;
        let mut selected_local = None;
        for (index, candidate) in example.candidate_group.candidates.iter().enumerate() {
            candidate.action.validate_candidate()?;
            if candidate.action.header().approval.is_some()
                || candidate.action.header().decision_id != example.decision_id
                || candidate.action.header().pre_state_id != example.pre_state_snapshot_id
                || candidate.action.header().decided_at != example.observation_cutoff
                || candidate.action.header().authority != example.authority
                || graph_decision_candidate_identity(&candidate.action)?
                    != candidate.action_identity
            {
                return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
                    "candidate action binding",
                ));
            }
            if candidate.action_identity == selected_identity
                && selected_local.replace(index).is_some()
            {
                return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
                    "duplicate selected candidate",
                ));
            }
        }
        let Some(selected_local) = selected_local else {
            return Err(FrozenGraphDecisionTrajectoryError::Leakage(
                "correct action absent from candidate group",
            ));
        };
        let action_range = ExactRange {
            offset: action_offset,
            length: example.candidate_group.candidates.len() as u64,
        };
        let evidence_range = ExactRange {
            offset: evidence.len() as u64,
            length: example.evidence_references.len() as u64,
        };
        let ordinal = decisions.len() as u64;
        decisions.push(FrozenDecisionRecord {
            decision_id: example.decision_id.clone(),
            observation_cutoff: example.observation_cutoff,
            state_ordinal: ordinal,
            candidate_group_ordinal: ordinal,
            candidate_actions: action_range,
            selected_label_ordinal: ordinal,
            evidence: evidence_range,
            reward_ordinal: ordinal,
            delta_ordinal: ordinal,
            provenance_ordinal: ordinal,
            split: example.split,
        });
        states.push(FrozenStateIdentityRecord {
            pre_state_snapshot_id: example.pre_state_snapshot_id,
            post_state_snapshot_id: example.post_state_snapshot_id,
        });
        groups.push(FrozenCandidateGroupRecord {
            candidate_group_id: example.candidate_group.candidate_group_id,
            candidate_identity: expected_group_identity,
            action_range,
            generation: example.candidate_group.generation,
        });
        candidates.extend(example.candidate_group.candidates);
        selected.push(FrozenSelectedActionRecord {
            selected_action_identity: selected_identity,
            selected_candidate_ordinal: action_offset + selected_local as u64,
            action: example.selected_action,
        });
        evidence.extend(example.evidence_references);
        rewards.push(example.reward_vector);
        deltas.push(example.delta);
        split_index.push(FrozenSplitIndexRecord {
            decision_ordinal: ordinal,
            observation_cutoff: example.observation_cutoff,
            split: example.split,
        });
        provenance.push(example.provenance);
    }
    if !leakage.passes() {
        return Err(FrozenGraphDecisionTrajectoryError::Leakage(
            leakage_failure(&leakage),
        ));
    }
    let candidate_certificate = candidate_certificate(&groups);
    Ok(FrozenDecisionTrajectoryTables {
        decisions,
        states,
        candidate_groups: groups,
        candidate_actions: candidates,
        selected_actions: selected,
        evidence,
        rewards,
        deltas,
        split_index,
        provenance: FrozenDecisionProvenanceSection {
            entries: provenance,
            leakage_certificate: leakage,
            candidate_certificate,
        },
    })
}

fn validate_example_shape(
    example: &GraphDecisionTrajectoryExample,
) -> Result<(), FrozenGraphDecisionTrajectoryError> {
    if example.decision_id.trim().is_empty()
        || example.observation_cutoff <= 0
        || example.pre_state_snapshot_id.trim().is_empty()
        || example.post_state_snapshot_id.trim().is_empty()
        || example.candidate_group.candidate_group_id.trim().is_empty()
        || example.candidate_group.candidates.is_empty()
        || example.delta.before_delta_id.trim().is_empty()
        || example.delta.after_delta_id.trim().is_empty()
        || example.provenance.decision_fingerprint.trim().is_empty()
        || example.provenance.label_authority_id.trim().is_empty()
        || example.provenance.source_receipt_ids.is_empty()
        || example.provenance.label_available_at < example.observation_cutoff
    {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "decision example",
        ));
    }
    example.selected_action.validate()?;
    example.reward_vector.validate()?;
    if example.selected_action.header().decision_id != example.decision_id
        || example.selected_action.header().pre_state_id != example.pre_state_snapshot_id
        || example.selected_action.header().decided_at != example.observation_cutoff
        || example.selected_action.header().authority != example.authority
        || example.reward_vector.decision_id != example.decision_id
    {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "decision authority binding",
        ));
    }
    let mut evidence_ids = HashSet::with_capacity(example.evidence_references.len());
    for item in &example.evidence_references {
        if item.evidence_id.trim().is_empty()
            || item.authority_id.trim().is_empty()
            || !evidence_ids.insert(item.evidence_id.as_str())
        {
            return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
                "evidence references",
            ));
        }
    }
    let example_evidence = example
        .evidence_references
        .iter()
        .map(|item| item.evidence_id.as_str())
        .collect::<HashSet<_>>();
    if example
        .selected_action
        .evidence()
        .iter()
        .any(|item| !example_evidence.contains(item.evidence_id.as_str()))
    {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "selected evidence binding",
        ));
    }
    Ok(())
}

fn accumulate_leakage(
    example: &GraphDecisionTrajectoryExample,
    certificate: &mut GraphDecisionLeakageCertificate,
) {
    certificate.evidence_after_cutoff += example
        .evidence_references
        .iter()
        .filter(|item| item.available_at > example.observation_cutoff)
        .count() as u64;
    if example
        .provenance
        .leakage_witness
        .pre_state_max_fact_available_at
        > example.observation_cutoff
    {
        certificate.evidence_after_cutoff += 1;
    }
    certificate.post_decision_edges_in_pre_state += example
        .provenance
        .leakage_witness
        .post_decision_edges_in_pre_state;
    certificate.future_episode_memberships_exposed += example
        .provenance
        .leakage_witness
        .future_episode_memberships_in_features;
    certificate.held_out_facts_in_training_topology += example
        .provenance
        .leakage_witness
        .validation_test_facts_in_training_topology;
    certificate.outcomes_used_as_inputs += example
        .provenance
        .leakage_witness
        .outcome_fields_used_as_inputs;
    certificate.label_influenced_candidate_groups += u64::from(
        example
            .provenance
            .leakage_witness
            .candidate_generation_used_held_out_label,
    );
}

fn validate_temporal_split(
    examples: &[GraphDecisionTrajectoryExample],
) -> Result<(), FrozenGraphDecisionTrajectoryError> {
    let bounds = |split| {
        let mut values = examples
            .iter()
            .filter(|example| example.split == split)
            .map(|example| example.observation_cutoff);
        let first = values.next()?;
        Some(values.fold((first, first), |(min, max), value| {
            (min.min(value), max.max(value))
        }))
    };
    let Some((_, train_max)) = bounds(GraphDecisionSplit::Train) else {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "train split",
        ));
    };
    let Some((validation_min, validation_max)) = bounds(GraphDecisionSplit::Validation) else {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "validation split",
        ));
    };
    let Some((test_min, _)) = bounds(GraphDecisionSplit::Test) else {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "test split",
        ));
    };
    if train_max >= validation_min || validation_max >= test_min {
        return Err(FrozenGraphDecisionTrajectoryError::Leakage(
            "temporal split overlap",
        ));
    }
    Ok(())
}

fn candidate_certificate(groups: &[FrozenCandidateGroupRecord]) -> CandidateDatasetCertificate {
    let mut counts = groups
        .iter()
        .map(|group| group.action_range.length as u32)
        .collect::<Vec<_>>();
    counts.sort_unstable();
    let percentile = |basis_points: usize| {
        let rank = counts.len().saturating_mul(basis_points).saturating_add(99) / 100;
        counts[rank.saturating_sub(1).min(counts.len() - 1)]
    };
    let mut composition = [0_u32; 12];
    let mut invalid = 0_u64;
    let mut allocations = 0_u64;
    for group in groups {
        invalid += u64::from(group.generation.invalid_candidates_rejected);
        allocations = allocations.saturating_add(group.generation.allocation_volume_bytes);
        for count in &group.generation.hard_negative_composition {
            composition[count.source as usize] =
                composition[count.source as usize].saturating_add(count.count);
        }
    }
    CandidateDatasetCertificate {
        candidate_groups: groups.len() as u64,
        candidates: counts.iter().map(|value| u64::from(*value)).sum(),
        candidate_count_min: counts[0],
        candidate_count_p50: percentile(50),
        candidate_count_p95: percentile(95),
        candidate_count_max: *counts.last().unwrap_or(&0),
        hard_negative_composition: all_sources()
            .into_iter()
            .enumerate()
            .filter_map(|(index, source)| {
                (composition[index] > 0).then_some(CandidateSourceCount {
                    source,
                    count: composition[index],
                })
            })
            .collect(),
        invalid_candidates_rejected: invalid,
        allocation_volume_bytes: allocations,
        candidate_identities: groups
            .iter()
            .map(|group| group.candidate_identity.clone())
            .collect(),
    }
}

fn all_sources() -> [DecisionCandidateSourceKind; 12] {
    [
        DecisionCandidateSourceKind::ActiveCompatibleEpisode,
        DecisionCandidateSourceKind::TemporallyPlausibleEpisode,
        DecisionCandidateSourceKind::SameEntityEpisode,
        DecisionCandidateSourceKind::RelatedEntityEpisode,
        DecisionCandidateSourceKind::DifficultNearNeighborEpisode,
        DecisionCandidateSourceKind::SameRelationHardNegative,
        DecisionCandidateSourceKind::EvidenceConfusableAlternative,
        DecisionCandidateSourceKind::TemporallyPlausibleIncorrectAction,
        DecisionCandidateSourceKind::StructurallyValidSemanticNegative,
        DecisionCandidateSourceKind::MinimalEditRepairAlternative,
        DecisionCandidateSourceKind::ExplicitCreateEpisode,
        DecisionCandidateSourceKind::ExplicitAbstain,
    ]
}
