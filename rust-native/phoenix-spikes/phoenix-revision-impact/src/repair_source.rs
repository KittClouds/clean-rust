use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use compact_str::CompactString;
use phoenix_types::GraphTruthDigest;
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{
    simulate_repair_candidate, GraphEditOperation, GraphGeneration, ProposedEdit, RepairCandidate,
    RepairSimulationError, RepairSimulationInput, RevisionRequirementSidecar, SourceRange,
};

pub const REPAIR_SOURCE_BINDING_SCHEMA: &str = "phoenix.repair-source-binding/v1";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceEditBinding {
    pub operation_index: u16,
    pub constraint_id: CompactString,
    pub scene_id: CompactString,
    pub evidence_id: CompactString,
    pub document_id: CompactString,
    pub source_range: SourceRange,
    pub expected_span_digest: GraphTruthDigest,
    pub replacement: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceDocument {
    pub document_id: CompactString,
    contents: Arc<[u8]>,
}

impl SourceDocument {
    pub fn utf8(document_id: impl Into<CompactString>, text: impl AsRef<str>) -> Self {
        Self {
            document_id: document_id.into(),
            contents: Arc::from(text.as_ref().as_bytes()),
        }
    }

    pub fn bytes(&self) -> &[u8] {
        &self.contents
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceDocumentSet {
    generation: GraphGeneration,
    documents: Vec<SourceDocument>,
    digest: GraphTruthDigest,
}

impl SourceDocumentSet {
    pub fn new(
        generation: GraphGeneration,
        mut documents: Vec<SourceDocument>,
    ) -> Result<Self, RepairSourceError> {
        if documents
            .iter()
            .any(|document| document.document_id.is_empty())
        {
            return Err(RepairSourceError::EmptyDocumentId);
        }
        documents.sort_unstable_by(|left, right| left.document_id.cmp(&right.document_id));
        if let Some(pair) = documents
            .windows(2)
            .find(|pair| pair[0].document_id == pair[1].document_id)
        {
            return Err(RepairSourceError::DuplicateDocument(
                pair[0].document_id.clone(),
            ));
        }
        let digest = digest_documents(generation, &documents);
        Ok(Self {
            generation,
            documents,
            digest,
        })
    }

    pub const fn generation(&self) -> GraphGeneration {
        self.generation
    }

    pub fn documents(&self) -> &[SourceDocument] {
        &self.documents
    }

    pub const fn digest(&self) -> GraphTruthDigest {
        self.digest
    }

    pub fn document(&self, document_id: &str) -> Option<&SourceDocument> {
        self.documents
            .binary_search_by(|document| document.document_id.as_str().cmp(document_id))
            .ok()
            .map(|index| &self.documents[index])
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ShadowSourceValidationReceipt {
    pub schema: CompactString,
    pub generation: GraphGeneration,
    pub original_documents_digest: GraphTruthDigest,
    pub revised_documents_digest: GraphTruthDigest,
    pub rebuilt_requirements_digest: GraphTruthDigest,
    pub changed_document_ids: Vec<CompactString>,
    pub bound_constraint_ids: Vec<CompactString>,
    pub removed_requirement_ids: Vec<CompactString>,
    pub document_bytes_before: usize,
    pub document_bytes_after: usize,
    pub exact_operation_coverage: bool,
    pub original_documents_unchanged: bool,
    pub no_source_writes: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ShadowSourceResult {
    pub revised_documents: SourceDocumentSet,
    pub rebuilt_requirements: RevisionRequirementSidecar,
    pub receipt: ShadowSourceValidationReceipt,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceValidatedRepairCandidate {
    pub candidate: RepairCandidate,
    pub source_validation: ShadowSourceValidationReceipt,
}

#[derive(Debug, Error)]
pub enum RepairSourceError {
    #[error("source document ID is empty")]
    EmptyDocumentId,
    #[error("duplicate source document {0}")]
    DuplicateDocument(CompactString),
    #[error("repair candidate is already source-bound")]
    AlreadyBound,
    #[error("constraint {0} has no exact source anchor")]
    UnanchoredConstraint(CompactString),
    #[error("constraint {0} has ambiguous source anchors")]
    AmbiguousAnchors(CompactString),
    #[error("source document {0} is unavailable")]
    MissingDocument(CompactString),
    #[error("source range is invalid for {0}")]
    InvalidRange(CompactString),
    #[error("source range splits a UTF-8 character in {0}")]
    InvalidUtf8Boundary(CompactString),
    #[error("source binding digest changed for {0}")]
    SpanDigestMismatch(CompactString),
    #[error("source edits overlap in {0}")]
    OverlappingEdits(CompactString),
    #[error("source binding does not match operation {0}")]
    BindingOperationMismatch(u16),
    #[error("source binding coverage is incomplete")]
    IncompleteBindingCoverage,
    #[error("source generation does not match repair generation")]
    GenerationMismatch,
    #[error("shadow sidecar serialization failed: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error(transparent)]
    Simulation(#[from] RepairSimulationError),
}

pub fn bind_repair_sources(
    edit: &ProposedEdit,
    documents: &SourceDocumentSet,
) -> Result<ProposedEdit, RepairSourceError> {
    if !edit.source_bindings.is_empty() {
        return Err(RepairSourceError::AlreadyBound);
    }
    let mut bound = edit.clone();
    for (operation_index, operation) in edit.operations.iter().enumerate() {
        let GraphEditOperation::RemoveRequirementBearingStatement {
            constraint_id,
            scene_id,
            evidence,
        } = operation
        else {
            continue;
        };
        let mut anchors = evidence
            .iter()
            .filter_map(|anchor| {
                Some((
                    anchor.evidence_id.clone(),
                    anchor.document_id.clone()?,
                    anchor.source_range?,
                ))
            })
            .collect::<Vec<_>>();
        anchors.sort_unstable_by(|left, right| {
            left.0
                .cmp(&right.0)
                .then_with(|| left.1.cmp(&right.1))
                .then_with(|| left.2.start.cmp(&right.2.start))
                .then_with(|| left.2.end.cmp(&right.2.end))
        });
        anchors.dedup();
        if anchors.is_empty() {
            return Err(RepairSourceError::UnanchoredConstraint(
                constraint_id.clone(),
            ));
        }
        if anchors.len() != 1 {
            return Err(RepairSourceError::AmbiguousAnchors(constraint_id.clone()));
        }
        let (evidence_id, document_id, source_range) = anchors.remove(0);
        let document = documents
            .document(&document_id)
            .ok_or_else(|| RepairSourceError::MissingDocument(document_id.clone()))?;
        let span = checked_span(document, source_range)?;
        bound.source_bindings.push(SourceEditBinding {
            operation_index: u16::try_from(operation_index)
                .map_err(|_| RepairSourceError::BindingOperationMismatch(u16::MAX))?,
            constraint_id: constraint_id.clone(),
            scene_id: scene_id.clone(),
            evidence_id,
            document_id,
            source_range,
            expected_span_digest: digest_bytes(span),
            replacement: CompactString::new(""),
        });
    }
    bound
        .source_bindings
        .sort_unstable_by_key(|binding| binding.operation_index);
    Ok(bound)
}

pub fn apply_source_bound_edit(
    documents: &SourceDocumentSet,
    requirements: &RevisionRequirementSidecar,
    edit: &ProposedEdit,
) -> Result<ShadowSourceResult, RepairSourceError> {
    if documents.generation() != requirements.generation {
        return Err(RepairSourceError::GenerationMismatch);
    }
    validate_binding_coverage(edit)?;
    let original_digest = documents.digest();
    let mut by_document = BTreeMap::<&str, Vec<&SourceEditBinding>>::new();
    for binding in &edit.source_bindings {
        by_document
            .entry(binding.document_id.as_str())
            .or_default()
            .push(binding);
    }
    let mut changed_document_ids = Vec::with_capacity(by_document.len());
    let mut revised = Vec::with_capacity(documents.documents.len());
    for document in &documents.documents {
        let Some(bindings) = by_document.get_mut(document.document_id.as_str()) else {
            revised.push(document.clone());
            continue;
        };
        bindings.sort_unstable_by_key(|binding| binding.source_range.start);
        validate_non_overlapping(&document.document_id, bindings)?;
        revised.push(rewrite_document(document, bindings)?);
        changed_document_ids.push(document.document_id.clone());
    }
    if by_document
        .keys()
        .any(|document_id| documents.document(document_id).is_none())
    {
        let missing = by_document
            .keys()
            .find(|document_id| documents.document(document_id).is_none())
            .expect("missing document key");
        return Err(RepairSourceError::MissingDocument((*missing).into()));
    }
    let revised_documents = SourceDocumentSet::new(documents.generation(), revised)?;
    let removed_requirement_ids = edit
        .source_bindings
        .iter()
        .map(|binding| binding.constraint_id.clone())
        .collect::<BTreeSet<_>>();
    let mut rebuilt_requirements = requirements.clone();
    rebuilt_requirements
        .requirements
        .retain(|row| !removed_requirement_ids.contains(&row.constraint_id));
    let bound_constraint_ids = removed_requirement_ids.iter().cloned().collect::<Vec<_>>();
    let original_documents_unchanged = documents.digest() == original_digest;
    let receipt = ShadowSourceValidationReceipt {
        schema: REPAIR_SOURCE_BINDING_SCHEMA.into(),
        generation: documents.generation(),
        original_documents_digest: original_digest,
        revised_documents_digest: revised_documents.digest(),
        rebuilt_requirements_digest: digest_requirements(&rebuilt_requirements)?,
        changed_document_ids,
        bound_constraint_ids: bound_constraint_ids.clone(),
        removed_requirement_ids: bound_constraint_ids,
        document_bytes_before: total_bytes(documents),
        document_bytes_after: total_bytes(&revised_documents),
        exact_operation_coverage: true,
        original_documents_unchanged,
        no_source_writes: true,
    };
    Ok(ShadowSourceResult {
        revised_documents,
        rebuilt_requirements,
        receipt,
    })
}

pub fn simulate_source_bound_candidate(
    input: RepairSimulationInput<'_>,
    documents: &SourceDocumentSet,
    edit: &ProposedEdit,
) -> Result<SourceValidatedRepairCandidate, RepairSourceError> {
    if documents.generation() != input.base.generation() {
        return Err(RepairSourceError::GenerationMismatch);
    }
    let shadow = apply_source_bound_edit(documents, input.requirements, edit)?;
    let candidate = simulate_repair_candidate(input, edit)?;
    Ok(SourceValidatedRepairCandidate {
        candidate,
        source_validation: shadow.receipt,
    })
}

fn validate_binding_coverage(edit: &ProposedEdit) -> Result<(), RepairSourceError> {
    let required = edit
        .operations
        .iter()
        .enumerate()
        .filter_map(|(index, operation)| match operation {
            GraphEditOperation::RemoveRequirementBearingStatement {
                constraint_id,
                scene_id,
                evidence,
            } => Some((index, constraint_id, scene_id, evidence)),
            GraphEditOperation::DropOriginalMutation { .. }
            | GraphEditOperation::ReplaceOriginalMutation { .. }
            | GraphEditOperation::ApplyAuthorDirective { .. } => None,
        })
        .collect::<Vec<_>>();
    if required.len() != edit.source_bindings.len() {
        return Err(RepairSourceError::IncompleteBindingCoverage);
    }
    let mut seen = BTreeSet::new();
    for binding in &edit.source_bindings {
        if !seen.insert(binding.operation_index) {
            return Err(RepairSourceError::BindingOperationMismatch(
                binding.operation_index,
            ));
        }
        let Some((_, constraint_id, scene_id, evidence)) = required
            .iter()
            .find(|(index, _, _, _)| *index == usize::from(binding.operation_index))
        else {
            return Err(RepairSourceError::BindingOperationMismatch(
                binding.operation_index,
            ));
        };
        if binding.constraint_id != **constraint_id
            || binding.scene_id != **scene_id
            || !evidence
                .iter()
                .any(|anchor| anchor.evidence_id == binding.evidence_id)
        {
            return Err(RepairSourceError::BindingOperationMismatch(
                binding.operation_index,
            ));
        }
    }
    Ok(())
}

fn validate_non_overlapping(
    document_id: &str,
    bindings: &[&SourceEditBinding],
) -> Result<(), RepairSourceError> {
    if bindings.windows(2).any(|pair| {
        pair[0].source_range.end > pair[1].source_range.start
            || pair[0].source_range.start == pair[0].source_range.end
    }) {
        return Err(RepairSourceError::OverlappingEdits(document_id.into()));
    }
    Ok(())
}

fn rewrite_document(
    document: &SourceDocument,
    bindings: &[&SourceEditBinding],
) -> Result<SourceDocument, RepairSourceError> {
    for binding in bindings {
        let span = checked_span(document, binding.source_range)?;
        if digest_bytes(span) != binding.expected_span_digest {
            return Err(RepairSourceError::SpanDigestMismatch(
                binding.constraint_id.clone(),
            ));
        }
    }
    let removed = bindings
        .iter()
        .map(|binding| (binding.source_range.end - binding.source_range.start) as usize)
        .sum::<usize>();
    let added = bindings
        .iter()
        .map(|binding| binding.replacement.len())
        .sum::<usize>();
    let capacity = document
        .bytes()
        .len()
        .checked_sub(removed)
        .and_then(|length| length.checked_add(added))
        .ok_or_else(|| RepairSourceError::InvalidRange(document.document_id.clone()))?;
    let mut output = Vec::with_capacity(capacity);
    let mut cursor = 0;
    for binding in bindings {
        let start = binding.source_range.start as usize;
        let end = binding.source_range.end as usize;
        output.extend_from_slice(&document.bytes()[cursor..start]);
        output.extend_from_slice(binding.replacement.as_bytes());
        cursor = end;
    }
    output.extend_from_slice(&document.bytes()[cursor..]);
    Ok(SourceDocument {
        document_id: document.document_id.clone(),
        contents: Arc::from(output),
    })
}

fn checked_span(document: &SourceDocument, range: SourceRange) -> Result<&[u8], RepairSourceError> {
    if range.start >= range.end || range.end as usize > document.bytes().len() {
        return Err(RepairSourceError::InvalidRange(
            document.document_id.clone(),
        ));
    }
    let text = std::str::from_utf8(document.bytes())
        .map_err(|_| RepairSourceError::InvalidUtf8Boundary(document.document_id.clone()))?;
    if !text.is_char_boundary(range.start as usize) || !text.is_char_boundary(range.end as usize) {
        return Err(RepairSourceError::InvalidUtf8Boundary(
            document.document_id.clone(),
        ));
    }
    Ok(&document.bytes()[range.start as usize..range.end as usize])
}

fn digest_documents(generation: GraphGeneration, documents: &[SourceDocument]) -> GraphTruthDigest {
    let mut hasher = blake3::Hasher::new();
    hasher.update(REPAIR_SOURCE_BINDING_SCHEMA.as_bytes());
    hasher.update(&generation.0.to_le_bytes());
    for document in documents {
        hash_len(&mut hasher, document.document_id.len());
        hasher.update(document.document_id.as_bytes());
        hash_len(&mut hasher, document.bytes().len());
        hasher.update(document.bytes());
    }
    GraphTruthDigest(*hasher.finalize().as_bytes())
}

fn digest_requirements(
    requirements: &RevisionRequirementSidecar,
) -> Result<GraphTruthDigest, serde_json::Error> {
    Ok(digest_bytes(&serde_json::to_vec(requirements)?))
}

fn digest_bytes(bytes: &[u8]) -> GraphTruthDigest {
    GraphTruthDigest(*blake3::hash(bytes).as_bytes())
}

fn total_bytes(documents: &SourceDocumentSet) -> usize {
    documents
        .documents
        .iter()
        .map(|document| document.bytes().len())
        .sum()
}

fn hash_len(hasher: &mut blake3::Hasher, length: usize) {
    hasher.update(&(length as u64).to_le_bytes());
}

#[cfg(test)]
#[path = "repair_source_tests.rs"]
mod tests;
