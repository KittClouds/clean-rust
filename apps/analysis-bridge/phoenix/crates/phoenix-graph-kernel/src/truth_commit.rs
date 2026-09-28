use compact_str::CompactString;
use hashbrown::{HashMap, HashSet};
use phoenix_types::{
    GraphTruthCommitHeader, GraphTruthOperation, GraphTruthVocabularyError,
    GRAPH_TRUTH_COMMIT_SCHEMA_VERSION,
};
use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fmt;

use crate::{KernelEdge, KernelGraphLayer, KernelMutationBatch, KernelMutationScope, KernelVertex};

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphTruthCommit {
    #[serde(flatten)]
    pub header: GraphTruthCommitHeader,
    pub batch: KernelMutationBatch,
}

impl GraphTruthCommit {
    pub fn commit_id(&self) -> &str {
        self.header.commit_id.as_str()
    }

    pub fn scope(&self) -> &KernelMutationScope {
        &self.batch.scope
    }

    pub fn validate(&self) -> Result<(), GraphTruthCommitError> {
        self.header
            .truth
            .validate()
            .map_err(GraphTruthCommitError::Vocabulary)?;
        if self.header.schema_version != GRAPH_TRUTH_COMMIT_SCHEMA_VERSION {
            return Err(GraphTruthCommitError::UnsupportedSchemaVersion(
                self.header.schema_version,
            ));
        }
        if self.header.commit_id.trim().is_empty() {
            return Err(GraphTruthCommitError::EmptyCommitId);
        }
        if self.header.generation == 0 {
            return Err(GraphTruthCommitError::ZeroGeneration);
        }
        if self.header.committed_at <= 0 {
            return Err(GraphTruthCommitError::InvalidTimestamp);
        }
        if self.header.idempotency_hash.is_zero() {
            return Err(GraphTruthCommitError::ZeroIdempotencyHash);
        }
        self.validate_sources()?;
        self.validate_receipts()?;
        self.validate_compiler_policy()?;
        self.validate_operation()?;
        self.validate_batch()?;
        self.atom_keys()?;
        Ok(())
    }

    pub fn atom_keys(&self) -> Result<Vec<GraphTruthAtomKey>, GraphTruthCommitError> {
        let mut keys = Vec::with_capacity(self.batch.vertices.len() + self.batch.edges.len());
        let mut seen = HashSet::with_capacity(keys.capacity());
        for vertex in &self.batch.vertices {
            let key = GraphTruthAtomKey::from_vertex(vertex);
            if !seen.insert(key.clone()) {
                return Err(GraphTruthCommitError::DuplicateAtom(key));
            }
            keys.push(key);
        }
        for edge in &self.batch.edges {
            let key = GraphTruthAtomKey::from_edge(edge);
            if !seen.insert(key.clone()) {
                return Err(GraphTruthCommitError::DuplicateAtom(key));
            }
            keys.push(key);
        }
        Ok(keys)
    }

    fn validate_sources(&self) -> Result<(), GraphTruthCommitError> {
        if self.header.source_generations.is_empty() {
            return Err(GraphTruthCommitError::MissingSourceGeneration);
        }
        let mut seen = HashSet::with_capacity(self.header.source_generations.len());
        for source in &self.header.source_generations {
            if source.source_id.trim().is_empty() {
                return Err(GraphTruthCommitError::EmptySourceId);
            }
            if !seen.insert(source.source_id.as_str()) {
                return Err(GraphTruthCommitError::DuplicateSourceId(
                    source.source_id.clone(),
                ));
            }
        }
        Ok(())
    }

    fn validate_receipts(&self) -> Result<(), GraphTruthCommitError> {
        let mut seen = HashSet::with_capacity(self.header.receipt_ids.len());
        for receipt_id in &self.header.receipt_ids {
            if receipt_id.trim().is_empty() {
                return Err(GraphTruthCommitError::EmptyReceiptId);
            }
            if !seen.insert(receipt_id.as_str()) {
                return Err(GraphTruthCommitError::DuplicateReceiptId(
                    receipt_id.clone(),
                ));
            }
        }
        Ok(())
    }

    fn validate_compiler_policy(&self) -> Result<(), GraphTruthCommitError> {
        let policy = &self.header.compiler_policy;
        for (field, value) in [
            ("compilerId", policy.compiler_id.as_str()),
            ("compilerVersion", policy.compiler_version.as_str()),
            ("policyId", policy.policy_id.as_str()),
            ("policyVersion", policy.policy_version.as_str()),
        ] {
            if value.trim().is_empty() {
                return Err(GraphTruthCommitError::EmptyCompilerPolicyField(field));
            }
        }
        Ok(())
    }

    fn validate_operation(&self) -> Result<(), GraphTruthCommitError> {
        let predecessors = &self.header.predecessor_commit_ids;
        let reversal = self.header.reverses_commit_id.as_ref();
        let mut seen = HashSet::with_capacity(predecessors.len());
        for predecessor in predecessors {
            if predecessor.trim().is_empty() {
                return Err(GraphTruthCommitError::EmptyPredecessorId);
            }
            if predecessor == self.header.commit_id {
                return Err(GraphTruthCommitError::SelfReference);
            }
            if !seen.insert(predecessor.as_str()) {
                return Err(GraphTruthCommitError::DuplicatePredecessorId(
                    predecessor.clone(),
                ));
            }
        }
        if reversal == Some(&self.header.commit_id) {
            return Err(GraphTruthCommitError::SelfReference);
        }
        if reversal.is_some_and(|commit_id| commit_id.trim().is_empty()) {
            return Err(GraphTruthCommitError::EmptyReversalId);
        }

        match self.header.operation {
            GraphTruthOperation::Assert => {
                if !predecessors.is_empty() || reversal.is_some() {
                    return Err(GraphTruthCommitError::UnexpectedLineageReference(
                        GraphTruthOperation::Assert,
                    ));
                }
            }
            GraphTruthOperation::Supersede => {
                if predecessors.is_empty() {
                    return Err(GraphTruthCommitError::MissingPredecessor(
                        GraphTruthOperation::Supersede,
                    ));
                }
                if reversal.is_some() {
                    return Err(GraphTruthCommitError::UnexpectedReversal(
                        GraphTruthOperation::Supersede,
                    ));
                }
            }
            GraphTruthOperation::Retract => {
                if predecessors.is_empty() {
                    return Err(GraphTruthCommitError::MissingPredecessor(
                        GraphTruthOperation::Retract,
                    ));
                }
                if reversal.is_some() {
                    return Err(GraphTruthCommitError::UnexpectedReversal(
                        GraphTruthOperation::Retract,
                    ));
                }
            }
            GraphTruthOperation::Revert => {
                if reversal.is_none() {
                    return Err(GraphTruthCommitError::MissingReversal);
                }
                if !predecessors.is_empty() {
                    return Err(GraphTruthCommitError::UnexpectedPredecessor(
                        GraphTruthOperation::Revert,
                    ));
                }
            }
        }
        Ok(())
    }

    fn validate_batch(&self) -> Result<(), GraphTruthCommitError> {
        if self.batch.layer != KernelGraphLayer::Asserted {
            return Err(GraphTruthCommitError::CandidateBatch);
        }
        if matches!(self.batch.scope, KernelMutationScope::Candidate { .. }) {
            return Err(GraphTruthCommitError::CandidateScope);
        }
        for edge in &self.batch.edges {
            if edge.layer != KernelGraphLayer::Asserted {
                return Err(GraphTruthCommitError::CandidateEdge(
                    GraphTruthAtomKey::from_edge(edge),
                ));
            }
        }
        let is_empty = self.batch.vertices.is_empty() && self.batch.edges.is_empty();
        match self.header.operation {
            GraphTruthOperation::Assert | GraphTruthOperation::Supersede if is_empty => Err(
                GraphTruthCommitError::EmptyMutationBatch(self.header.operation),
            ),
            GraphTruthOperation::Retract | GraphTruthOperation::Revert if !is_empty => Err(
                GraphTruthCommitError::UnexpectedMutationBatch(self.header.operation),
            ),
            _ => Ok(()),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", tag = "kind")]
pub enum GraphTruthAtomKey {
    Vertex {
        vertex_id: CompactString,
    },
    Edge {
        source_id: CompactString,
        target_id: CompactString,
        edge_type: CompactString,
    },
}

impl GraphTruthAtomKey {
    pub fn vertex(vertex_id: &str) -> Self {
        Self::Vertex {
            vertex_id: CompactString::new(vertex_id),
        }
    }

    pub fn edge(source_id: &str, target_id: &str, edge_type: &str) -> Self {
        Self::Edge {
            source_id: CompactString::new(source_id),
            target_id: CompactString::new(target_id),
            edge_type: CompactString::new(edge_type),
        }
    }

    fn from_vertex(vertex: &KernelVertex) -> Self {
        Self::vertex(&vertex.id.0)
    }

    fn from_edge(edge: &KernelEdge) -> Self {
        Self::edge(&edge.source_id.0, &edge.target_id.0, &edge.edge_type.0)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GraphTruthCommitError {
    Vocabulary(GraphTruthVocabularyError),
    UnsupportedSchemaVersion(u16),
    EmptyCommitId,
    ZeroGeneration,
    InvalidTimestamp,
    ZeroIdempotencyHash,
    MissingSourceGeneration,
    EmptySourceId,
    DuplicateSourceId(CompactString),
    EmptyReceiptId,
    DuplicateReceiptId(CompactString),
    EmptyCompilerPolicyField(&'static str),
    EmptyPredecessorId,
    DuplicatePredecessorId(CompactString),
    EmptyReversalId,
    SelfReference,
    MissingPredecessor(GraphTruthOperation),
    UnexpectedPredecessor(GraphTruthOperation),
    MissingReversal,
    UnexpectedReversal(GraphTruthOperation),
    UnexpectedLineageReference(GraphTruthOperation),
    CandidateBatch,
    CandidateScope,
    CandidateEdge(GraphTruthAtomKey),
    EmptyMutationBatch(GraphTruthOperation),
    UnexpectedMutationBatch(GraphTruthOperation),
    DuplicateAtom(GraphTruthAtomKey),
}

impl fmt::Display for GraphTruthCommitError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "invalid graph truth commit: {self:?}")
    }
}

impl Error for GraphTruthCommitError {}

#[derive(Debug, Default)]
pub struct GraphTruthLineage {
    commits: Vec<GraphTruthCommit>,
    commit_index_by_id: HashMap<CompactString, usize>,
    active_commit_by_atom: HashMap<GraphTruthAtomKey, usize>,
}

impl GraphTruthLineage {
    pub fn build(mut commits: Vec<GraphTruthCommit>) -> Result<Self, GraphTruthLineageError> {
        commits.sort_unstable_by(|left, right| {
            left.header
                .generation
                .cmp(&right.header.generation)
                .then_with(|| left.header.commit_id.cmp(&right.header.commit_id))
        });

        let mut commit_index_by_id = HashMap::<CompactString, usize>::with_capacity(commits.len());
        let mut active_commit_by_atom = HashMap::<GraphTruthAtomKey, usize>::new();
        let mut active_keys_by_commit = vec![Vec::<GraphTruthAtomKey>::new(); commits.len()];
        let mut previous_generation = None;

        for index in 0..commits.len() {
            let commit = &commits[index];
            commit
                .validate()
                .map_err(|source| GraphTruthLineageError::InvalidCommit {
                    commit_id: commit.header.commit_id.clone(),
                    source,
                })?;
            if previous_generation == Some(commit.header.generation) {
                return Err(GraphTruthLineageError::DuplicateGeneration(
                    commit.header.generation,
                ));
            }
            previous_generation = Some(commit.header.generation);
            if commit_index_by_id.contains_key(&commit.header.commit_id) {
                return Err(GraphTruthLineageError::DuplicateCommitId(
                    commit.header.commit_id.clone(),
                ));
            }

            let referenced_ids = match commit.header.operation {
                GraphTruthOperation::Supersede | GraphTruthOperation::Retract => commit
                    .header
                    .predecessor_commit_ids
                    .iter()
                    .collect::<Vec<_>>(),
                GraphTruthOperation::Revert => {
                    commit.header.reverses_commit_id.iter().collect::<Vec<_>>()
                }
                GraphTruthOperation::Assert => Vec::new(),
            };
            for referenced_id in referenced_ids {
                let Some(&referenced_index) = commit_index_by_id.get(referenced_id) else {
                    return Err(GraphTruthLineageError::MissingReferencedCommit {
                        commit_id: commit.header.commit_id.clone(),
                        referenced_commit_id: referenced_id.clone(),
                    });
                };
                if active_keys_by_commit[referenced_index].is_empty() {
                    return Err(GraphTruthLineageError::InactiveReferencedCommit {
                        commit_id: commit.header.commit_id.clone(),
                        referenced_commit_id: referenced_id.clone(),
                    });
                }
                for atom in active_keys_by_commit[referenced_index].drain(..) {
                    if active_commit_by_atom.get(&atom) == Some(&referenced_index) {
                        active_commit_by_atom.remove(&atom);
                    }
                }
            }

            let atom_keys =
                commit
                    .atom_keys()
                    .map_err(|source| GraphTruthLineageError::InvalidCommit {
                        commit_id: commit.header.commit_id.clone(),
                        source,
                    })?;
            for atom in &atom_keys {
                if let Some(&active_index) = active_commit_by_atom.get(atom) {
                    return Err(GraphTruthLineageError::AtomAlreadyActive {
                        atom: atom.clone(),
                        active_commit_id: commits[active_index].header.commit_id.clone(),
                        incoming_commit_id: commit.header.commit_id.clone(),
                    });
                }
                active_commit_by_atom.insert(atom.clone(), index);
            }
            active_keys_by_commit[index] = atom_keys;
            commit_index_by_id.insert(commit.header.commit_id.clone(), index);
        }

        Ok(Self {
            commits,
            commit_index_by_id,
            active_commit_by_atom,
        })
    }

    pub fn commits(&self) -> &[GraphTruthCommit] {
        &self.commits
    }

    pub fn active_atom_count(&self) -> usize {
        self.active_commit_by_atom.len()
    }

    pub fn commit_by_id(&self, commit_id: &str) -> Option<&GraphTruthCommit> {
        self.commit_index_by_id
            .get(commit_id)
            .map(|&index| &self.commits[index])
    }

    pub fn active_commit_for_atom(&self, atom: &GraphTruthAtomKey) -> Option<&GraphTruthCommit> {
        self.active_commit_by_atom
            .get(atom)
            .map(|&index| &self.commits[index])
    }

    pub fn active_vertex_commit(&self, vertex_id: &str) -> Option<&GraphTruthCommit> {
        self.active_commit_for_atom(&GraphTruthAtomKey::vertex(vertex_id))
    }

    pub fn active_edge_commit(
        &self,
        source_id: &str,
        target_id: &str,
        edge_type: &str,
    ) -> Option<&GraphTruthCommit> {
        self.active_commit_for_atom(&GraphTruthAtomKey::edge(source_id, target_id, edge_type))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GraphTruthLineageError {
    InvalidCommit {
        commit_id: CompactString,
        source: GraphTruthCommitError,
    },
    DuplicateCommitId(CompactString),
    DuplicateGeneration(u64),
    MissingReferencedCommit {
        commit_id: CompactString,
        referenced_commit_id: CompactString,
    },
    InactiveReferencedCommit {
        commit_id: CompactString,
        referenced_commit_id: CompactString,
    },
    AtomAlreadyActive {
        atom: GraphTruthAtomKey,
        active_commit_id: CompactString,
        incoming_commit_id: CompactString,
    },
}

impl fmt::Display for GraphTruthLineageError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "invalid graph truth lineage: {self:?}")
    }
}

impl Error for GraphTruthLineageError {}

#[cfg(test)]
mod tests {
    use super::*;
    use phoenix_types::{
        GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthDigest, GraphTruthKind,
        GraphTruthPlane, GraphTruthSourceGenerationRef,
    };
    use serde_json::json;

    fn commit(
        id: &str,
        generation: u64,
        operation: GraphTruthOperation,
        vertex_id: Option<&str>,
    ) -> GraphTruthCommit {
        let mut header = GraphTruthCommitHeader {
            commit_id: CompactString::new(id),
            generation,
            operation,
            truth: GraphTruthDescriptor {
                kind: GraphTruthKind::Assertion,
                plane: Some(GraphTruthPlane::WorldState),
            },
            source_generations: [GraphTruthSourceGenerationRef {
                source_id: CompactString::new("memory:scope-1"),
                generation,
            }]
            .into_iter()
            .collect(),
            receipt_ids: [CompactString::new(format!("receipt:{id}"))]
                .into_iter()
                .collect(),
            compiler_policy: GraphTruthCompilerPolicy {
                compiler_id: CompactString::new("phoenix-graph-post"),
                compiler_version: CompactString::new("1"),
                policy_id: CompactString::new("graph-truth"),
                policy_version: CompactString::new("1"),
            },
            idempotency_hash: GraphTruthDigest([((generation % 255) + 1) as u8; 32]),
            committed_at: generation as i64,
            ..GraphTruthCommitHeader::default()
        };
        if operation == GraphTruthOperation::Supersede {
            header
                .predecessor_commit_ids
                .push(CompactString::new("commit-1"));
        }
        GraphTruthCommit {
            header,
            batch: KernelMutationBatch {
                layer: KernelGraphLayer::Asserted,
                scope: KernelMutationScope::Projection {
                    scope_key: "scope-1".to_owned(),
                },
                recorded_at: Some(generation as i64),
                vertices: vertex_id
                    .map(|vertex_id| KernelVertex {
                        id: crate::KernelVertexId(vertex_id.to_owned()),
                        kind: "claim".to_owned(),
                        value: json!({"id": vertex_id}),
                        attributes: json!({}),
                        ..KernelVertex::default()
                    })
                    .into_iter()
                    .collect(),
                edges: Vec::new(),
            },
        }
    }

    #[test]
    fn commit_rejects_unknown_and_mixed_assertion_planes() {
        for plane in [GraphTruthPlane::Unknown, GraphTruthPlane::Mixed] {
            let mut value = commit("commit-1", 1, GraphTruthOperation::Assert, Some("claim-1"));
            value.header.truth.plane = Some(plane);
            assert!(matches!(
                value.validate(),
                Err(GraphTruthCommitError::Vocabulary(_))
            ));
        }
    }

    #[test]
    fn commit_rejects_candidate_batches() {
        let mut value = commit("commit-1", 1, GraphTruthOperation::Assert, Some("claim-1"));
        value.batch.layer = KernelGraphLayer::Candidate;
        assert_eq!(value.validate(), Err(GraphTruthCommitError::CandidateBatch));
    }

    #[test]
    fn lineage_resolves_one_active_commit_and_its_evidence() {
        let first = commit("commit-1", 1, GraphTruthOperation::Assert, Some("claim-1"));
        let second = commit(
            "commit-2",
            2,
            GraphTruthOperation::Supersede,
            Some("claim-1"),
        );
        let lineage = GraphTruthLineage::build(vec![second, first]).expect("valid lineage");
        let active = lineage
            .active_vertex_commit("claim-1")
            .expect("active claim commit");

        assert_eq!(active.commit_id(), "commit-2");
        assert_eq!(active.header.source_generations[0].generation, 2);
        assert_eq!(active.header.receipt_ids[0].as_str(), "receipt:commit-2");
        assert_eq!(lineage.active_atom_count(), 1);
    }

    #[test]
    fn lineage_rejects_two_active_commits_for_one_atom() {
        let first = commit("commit-1", 1, GraphTruthOperation::Assert, Some("claim-1"));
        let second = commit("commit-2", 2, GraphTruthOperation::Assert, Some("claim-1"));
        assert!(matches!(
            GraphTruthLineage::build(vec![first, second]),
            Err(GraphTruthLineageError::AtomAlreadyActive { .. })
        ));
    }

    #[test]
    fn retraction_removes_the_active_atom() {
        let first = commit("commit-1", 1, GraphTruthOperation::Assert, Some("claim-1"));
        let mut retract = commit("commit-2", 2, GraphTruthOperation::Retract, None);
        retract
            .header
            .predecessor_commit_ids
            .push(CompactString::new("commit-1"));
        let lineage = GraphTruthLineage::build(vec![first, retract]).expect("valid retraction");

        assert!(lineage.active_vertex_commit("claim-1").is_none());
        assert_eq!(lineage.active_atom_count(), 0);
    }

    #[test]
    fn lineage_indexes_thousands_of_active_atoms() {
        const COMMIT_COUNT: u64 = 4_096;
        let commits = (1..=COMMIT_COUNT)
            .map(|generation| {
                commit(
                    &format!("commit-{generation}"),
                    generation,
                    GraphTruthOperation::Assert,
                    Some(&format!("claim-{generation}")),
                )
            })
            .collect();
        let lineage = GraphTruthLineage::build(commits).expect("large valid lineage");

        assert_eq!(lineage.active_atom_count(), COMMIT_COUNT as usize);
        assert_eq!(
            lineage
                .active_vertex_commit("claim-4096")
                .map(GraphTruthCommit::commit_id),
            Some("commit-4096")
        );
    }

    #[test]
    fn serialized_contract_keeps_scope_inside_the_single_batch() {
        let value = commit("commit-1", 1, GraphTruthOperation::Assert, Some("claim-1"));
        let json = serde_json::to_value(value).expect("serialize commit");

        assert_eq!(json["commitId"], "commit-1");
        assert_eq!(json["batch"]["scope"]["kind"], "projection");
        assert!(json.get("scope").is_none());
        assert_eq!(json["sourceGenerations"][0]["generation"], 1);
    }
}
