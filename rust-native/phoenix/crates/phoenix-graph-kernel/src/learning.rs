use compact_str::CompactString;
use hashbrown::{HashMap, HashSet};
use phoenix_types::{
    GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthOperation,
    GraphTruthSourceGenerationRef,
};
use serde::{Deserialize, Serialize};
use smallvec::SmallVec;
use std::error::Error;
use std::fmt;

use crate::{GraphTruthAtomKey, GraphTruthCommit};

pub const GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION: u16 = 1;
pub const GRAPH_PROPOSAL_FEATURE_DIM: usize = 16;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphProposalStatus {
    #[default]
    Generated,
    ReviewedSupport,
    ReviewedContradiction,
    Deferred,
    Rejected,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphProposalOutcomeKind {
    Uncommitted,
    Active,
    Superseded,
    Retracted,
    Reverted,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct GraphProposalFeatures(pub [i16; GRAPH_PROPOSAL_FEATURE_DIM]);

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphProposalObservation {
    pub proposal_id: CompactString,
    pub atom: GraphTruthAtomKey,
    pub family: CompactString,
    pub source_kind: CompactString,
    pub target_kind: CompactString,
    pub truth: GraphTruthDescriptor,
    pub status: GraphProposalStatus,
    #[serde(default)]
    pub evidence_refs: SmallVec<[CompactString; 4]>,
    pub features: GraphProposalFeatures,
    pub shadow_score_millis: Option<u16>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphProposalBatchReceipt {
    pub schema_version: u16,
    pub receipt_id: CompactString,
    pub scope_key: CompactString,
    pub generation: u64,
    pub created_at: i64,
    pub compiler_policy: GraphTruthCompilerPolicy,
    #[serde(default)]
    pub source_generations: SmallVec<[GraphTruthSourceGenerationRef; 4]>,
    pub model_id: Option<CompactString>,
    pub proposals: Vec<GraphProposalObservation>,
}

impl GraphProposalBatchReceipt {
    pub fn validate(&self) -> Result<(), GraphProposalReceiptError> {
        if self.schema_version != GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION {
            return Err(GraphProposalReceiptError::UnsupportedSchemaVersion(
                self.schema_version,
            ));
        }
        if self.receipt_id.trim().is_empty() {
            return Err(GraphProposalReceiptError::EmptyReceiptId);
        }
        if self.scope_key.trim().is_empty() {
            return Err(GraphProposalReceiptError::EmptyScopeKey);
        }
        if self.generation == 0 {
            return Err(GraphProposalReceiptError::ZeroGeneration);
        }
        if self.created_at <= 0 {
            return Err(GraphProposalReceiptError::InvalidTimestamp);
        }
        if self.proposals.is_empty() {
            return Err(GraphProposalReceiptError::EmptyProposals);
        }
        if self.source_generations.is_empty() {
            return Err(GraphProposalReceiptError::MissingSourceGeneration);
        }
        for value in [
            self.compiler_policy.compiler_id.as_str(),
            self.compiler_policy.compiler_version.as_str(),
            self.compiler_policy.policy_id.as_str(),
            self.compiler_policy.policy_version.as_str(),
        ] {
            if value.trim().is_empty() {
                return Err(GraphProposalReceiptError::EmptyCompilerPolicy);
            }
        }

        let mut proposal_ids = HashSet::with_capacity(self.proposals.len());
        let mut atoms = HashSet::with_capacity(self.proposals.len());
        let mut source_ids = HashSet::with_capacity(self.source_generations.len());
        for source in &self.source_generations {
            if source.source_id.trim().is_empty() {
                return Err(GraphProposalReceiptError::EmptySourceId);
            }
            if !source_ids.insert(source.source_id.as_str()) {
                return Err(GraphProposalReceiptError::DuplicateSourceId(
                    source.source_id.clone(),
                ));
            }
        }
        for proposal in &self.proposals {
            if proposal.proposal_id.trim().is_empty() {
                return Err(GraphProposalReceiptError::EmptyProposalId);
            }
            if !proposal_ids.insert(proposal.proposal_id.as_str()) {
                return Err(GraphProposalReceiptError::DuplicateProposalId(
                    proposal.proposal_id.clone(),
                ));
            }
            if !atoms.insert(&proposal.atom) {
                return Err(GraphProposalReceiptError::DuplicateAtom(
                    proposal.atom.clone(),
                ));
            }
            if proposal
                .shadow_score_millis
                .is_some_and(|score| score > 1000)
            {
                return Err(GraphProposalReceiptError::InvalidShadowScore(
                    proposal.shadow_score_millis.unwrap_or_default(),
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphProposalOutcome {
    pub receipt_id: CompactString,
    pub proposal_id: CompactString,
    pub atom: GraphTruthAtomKey,
    pub outcome: GraphProposalOutcomeKind,
    pub commit_id: Option<CompactString>,
    pub commit_generation: Option<u64>,
}

pub fn project_graph_proposal_outcomes(
    receipts: &[GraphProposalBatchReceipt],
    commits: &[GraphTruthCommit],
) -> Result<Vec<GraphProposalOutcome>, GraphProposalReceiptError> {
    for receipt in receipts {
        receipt.validate()?;
    }

    let mut ordered = commits.iter().collect::<Vec<_>>();
    ordered.sort_unstable_by_key(|commit| commit.header.generation);
    let mut resolution = HashMap::<&str, GraphProposalOutcomeKind>::with_capacity(ordered.len());
    for commit in &ordered {
        resolution.insert(commit.commit_id(), GraphProposalOutcomeKind::Active);
        let resolved = match commit.header.operation {
            GraphTruthOperation::Supersede => Some(GraphProposalOutcomeKind::Superseded),
            GraphTruthOperation::Retract => Some(GraphProposalOutcomeKind::Retracted),
            GraphTruthOperation::Revert => Some(GraphProposalOutcomeKind::Reverted),
            GraphTruthOperation::Assert => None,
        };
        if let Some(outcome) = resolved {
            for referenced in commit
                .header
                .predecessor_commit_ids
                .iter()
                .chain(commit.header.reverses_commit_id.iter())
            {
                resolution.insert(referenced.as_str(), outcome);
            }
        }
    }

    let mut commit_by_receipt_atom = HashMap::<(&str, GraphTruthAtomKey), &GraphTruthCommit>::new();
    for commit in &ordered {
        if commit.header.receipt_ids.is_empty() {
            continue;
        }
        for atom in commit
            .atom_keys()
            .map_err(|_| GraphProposalReceiptError::InvalidCommitAtoms)?
        {
            for receipt_id in &commit.header.receipt_ids {
                commit_by_receipt_atom.insert((receipt_id.as_str(), atom.clone()), commit);
            }
        }
    }

    let capacity = receipts.iter().map(|receipt| receipt.proposals.len()).sum();
    let mut outcomes = Vec::with_capacity(capacity);
    for receipt in receipts {
        for proposal in &receipt.proposals {
            let commit = commit_by_receipt_atom
                .get(&(receipt.receipt_id.as_str(), proposal.atom.clone()))
                .copied();
            outcomes.push(GraphProposalOutcome {
                receipt_id: receipt.receipt_id.clone(),
                proposal_id: proposal.proposal_id.clone(),
                atom: proposal.atom.clone(),
                outcome: commit
                    .and_then(|value| resolution.get(value.commit_id()).copied())
                    .unwrap_or(GraphProposalOutcomeKind::Uncommitted),
                commit_id: commit.map(|value| value.header.commit_id.clone()),
                commit_generation: commit.map(|value| value.header.generation),
            });
        }
    }
    outcomes.sort_unstable_by(|left, right| {
        left.receipt_id
            .cmp(&right.receipt_id)
            .then_with(|| left.proposal_id.cmp(&right.proposal_id))
    });
    Ok(outcomes)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GraphProposalReceiptError {
    UnsupportedSchemaVersion(u16),
    EmptyReceiptId,
    EmptyScopeKey,
    ZeroGeneration,
    InvalidTimestamp,
    EmptyProposals,
    MissingSourceGeneration,
    EmptySourceId,
    DuplicateSourceId(CompactString),
    EmptyCompilerPolicy,
    EmptyProposalId,
    DuplicateProposalId(CompactString),
    DuplicateAtom(GraphTruthAtomKey),
    InvalidShadowScore(u16),
    InvalidCommitAtoms,
}

impl fmt::Display for GraphProposalReceiptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "invalid graph proposal receipt: {self:?}")
    }
}

impl Error for GraphProposalReceiptError {}
