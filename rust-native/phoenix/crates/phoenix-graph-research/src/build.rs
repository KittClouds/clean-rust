use crate::model::*;
use compact_str::{format_compact, CompactString};
use hashbrown::HashMap;
use phoenix_graph_kernel::{
    project_graph_proposal_outcomes, GraphProposalBatchReceipt, GraphProposalOutcomeKind,
    GraphTruthCommit, KernelCheckpointData, KernelEdge, KernelVertex,
};
use phoenix_graph_rebuild::GraphDocumentCompilerSummary;
use serde::Serialize;

pub struct FrozenGraphResearchInput<'a> {
    pub checkpoint: &'a KernelCheckpointData,
    pub commits: &'a [GraphTruthCommit],
    pub proposal_receipts: &'a [GraphProposalBatchReceipt],
    pub document_compiler: Option<&'a GraphDocumentCompilerSummary>,
    pub document_compiler_observed_at_ms: Option<i64>,
    pub frozen_at_ms: i64,
    pub split_policy: TemporalSplitPolicy,
}

pub fn freeze_graph_research_snapshot(
    input: FrozenGraphResearchInput<'_>,
) -> Result<FrozenGraphResearchSnapshot, FrozenGraphResearchError> {
    input.split_policy.validate(input.frozen_at_ms)?;
    if input.checkpoint.meta.generation == 0 {
        return Err(FrozenGraphResearchError::ZeroCheckpointGeneration);
    }
    let mut builder = ResearchBuilder::new(&input)?;
    builder.kernel_nodes()?;
    builder.kernel_edges()?;
    builder.hypergraph_incidence()?;
    builder.proposals()?;
    builder.finish()
}

struct ResearchBuilder<'a> {
    input: &'a FrozenGraphResearchInput<'a>,
    nodes: Vec<ResearchNode>,
    edges: Vec<ResearchEdge>,
    incidences: Vec<ResearchIncidence>,
    proposals: Vec<ResearchProposal>,
    node_by_id: HashMap<CompactString, u32>,
    node_by_external_id: HashMap<CompactString, u32>,
}

impl<'a> ResearchBuilder<'a> {
    fn new(input: &'a FrozenGraphResearchInput<'a>) -> Result<Self, FrozenGraphResearchError> {
        let capacity = input.checkpoint.snapshot.vertices.len()
            + input
                .document_compiler
                .map_or(0, |value| value.hyperedges.len() * 2);
        Ok(Self {
            input,
            nodes: Vec::with_capacity(capacity),
            edges: Vec::with_capacity(
                input.checkpoint.snapshot.asserted_edges.len()
                    + input.checkpoint.snapshot.candidate_edges.len(),
            ),
            incidences: Vec::new(),
            proposals: Vec::new(),
            node_by_id: HashMap::with_capacity(capacity),
            node_by_external_id: HashMap::with_capacity(capacity * 2),
        })
    }

    fn kernel_nodes(&mut self) -> Result<(), FrozenGraphResearchError> {
        let mut vertices = self
            .input
            .checkpoint
            .snapshot
            .vertices
            .iter()
            .collect::<Vec<_>>();
        vertices.sort_unstable_by(|left, right| left.id.0.cmp(&right.id.0));
        for vertex in vertices {
            let available_at = vertex
                .temporal
                .recorded_at
                .unwrap_or(self.input.checkpoint.meta.created_at);
            self.ensure_not_future(available_at)?;
            let ordinal = self.push_node(ResearchNode {
                id: CompactString::new(&vertex.id.0),
                kind: CompactString::new(vertex_kind(vertex)),
                authority: ResearchAuthority::Asserted,
                split: self.input.split_policy.split(available_at),
                available_at_ms: available_at,
                source_generation: self.input.checkpoint.meta.generation,
            })?;
            self.alias_external(&vertex.id.0, ordinal);
            if let Some(value) = &vertex.entity_id {
                self.alias_external(value, ordinal);
            }
            if let Some(value) = &vertex.search_chunk_id {
                self.alias_external(value, ordinal);
            }
        }
        Ok(())
    }

    fn kernel_edges(&mut self) -> Result<(), FrozenGraphResearchError> {
        let mut rows = Vec::with_capacity(
            self.input.checkpoint.snapshot.asserted_edges.len()
                + self.input.checkpoint.snapshot.candidate_edges.len(),
        );
        rows.extend(
            self.input
                .checkpoint
                .snapshot
                .asserted_edges
                .iter()
                .map(|edge| (ResearchAuthority::Asserted, edge)),
        );
        rows.extend(
            self.input
                .checkpoint
                .snapshot
                .candidate_edges
                .iter()
                .map(|edge| (ResearchAuthority::Candidate, edge)),
        );
        rows.sort_unstable_by(|left, right| edge_key(left.1).cmp(&edge_key(right.1)));
        for (authority, edge) in rows {
            let available_at = edge
                .temporal
                .recorded_at
                .unwrap_or(self.input.checkpoint.meta.created_at);
            self.ensure_not_future(available_at)?;
            let source = self.lookup_vertex(&edge.source_id.0)?;
            let target = self.lookup_vertex(&edge.target_id.0)?;
            self.edges.push(ResearchEdge {
                source,
                target,
                relation: CompactString::new(&edge.edge_type.0),
                authority,
                split: self.input.split_policy.split(available_at),
                available_at_ms: available_at,
                weight: edge.weight as f32,
            });
        }
        Ok(())
    }

    fn hypergraph_incidence(&mut self) -> Result<(), FrozenGraphResearchError> {
        let Some(summary) = self.input.document_compiler else {
            return Ok(());
        };
        let observed_at = self
            .input
            .document_compiler_observed_at_ms
            .ok_or(FrozenGraphResearchError::FutureGraphData)?;
        self.ensure_not_future(observed_at)?;
        let split = self.input.split_policy.split(observed_at);
        let mut hyperedges = summary.hyperedges.iter().collect::<Vec<_>>();
        hyperedges.sort_unstable_by(|left, right| left.id.cmp(&right.id));
        for hyperedge in hyperedges {
            let hyperedge_id = format_compact!("hyperedge:{}", hyperedge.id);
            let hyperedge_ix = self.push_node(ResearchNode {
                id: hyperedge_id,
                kind: hyperedge
                    .frame
                    .clone()
                    .unwrap_or_else(|| hyperedge.predicate.clone()),
                authority: ResearchAuthority::Candidate,
                split,
                available_at_ms: observed_at,
                source_generation: self.input.checkpoint.meta.generation,
            })?;
            for role in &hyperedge.roles {
                let participant_ix = match self.node_by_external_id.get(&role.target_id).copied() {
                    Some(value) => value,
                    None => self.synthetic_candidate_node(
                        &role.target_kind,
                        &role.target_id,
                        observed_at,
                    )?,
                };
                if self.nodes[participant_ix as usize].available_at_ms > observed_at {
                    return Err(FrozenGraphResearchError::FutureGraphData);
                }
                self.incidences.push(ResearchIncidence {
                    hyperedge: hyperedge_ix,
                    participant: participant_ix,
                    role: role
                        .semantic_role
                        .clone()
                        .unwrap_or_else(|| role.role.clone()),
                    split,
                    resolved: role.resolved.unwrap_or(false),
                });
            }
        }
        Ok(())
    }

    fn proposals(&mut self) -> Result<(), FrozenGraphResearchError> {
        let outcomes =
            project_graph_proposal_outcomes(self.input.proposal_receipts, self.input.commits)
                .map_err(|error| FrozenGraphResearchError::ProposalHistory(error.to_string()))?;
        let outcome_by_key = outcomes
            .into_iter()
            .map(|row| ((row.receipt_id.clone(), row.proposal_id.clone()), row))
            .collect::<HashMap<_, _>>();
        let commit_time = self
            .input
            .commits
            .iter()
            .map(|commit| (commit.header.commit_id.as_str(), commit.header.committed_at))
            .collect::<HashMap<_, _>>();
        let mut receipts = self.input.proposal_receipts.iter().collect::<Vec<_>>();
        receipts.sort_unstable_by(|left, right| left.receipt_id.cmp(&right.receipt_id));
        for receipt in receipts {
            self.ensure_not_future(receipt.created_at)?;
            let mut proposals = receipt.proposals.iter().collect::<Vec<_>>();
            proposals.sort_unstable_by(|left, right| left.proposal_id.cmp(&right.proposal_id));
            for proposal in proposals {
                let key = (receipt.receipt_id.clone(), proposal.proposal_id.clone());
                let outcome = outcome_by_key.get(&key).ok_or_else(|| {
                    FrozenGraphResearchError::ProposalHistory(format!(
                        "missing outcome for {} / {}",
                        receipt.receipt_id, proposal.proposal_id
                    ))
                })?;
                let label_available_at = outcome
                    .commit_id
                    .as_ref()
                    .and_then(|id| commit_time.get(id.as_str()).copied())
                    .unwrap_or(self.input.frozen_at_ms);
                self.ensure_not_future(label_available_at)?;
                self.proposals.push(ResearchProposal {
                    proposal_id: proposal.proposal_id.clone(),
                    receipt_id: receipt.receipt_id.clone(),
                    feature_schema_id: feature_schema_id(receipt),
                    split: self
                        .input
                        .split_policy
                        .split(receipt.created_at.max(label_available_at)),
                    label: proposal_label(outcome.outcome),
                    observed_at_ms: receipt.created_at,
                    label_available_at_ms: label_available_at,
                    features: proposal.features.0,
                });
            }
        }
        Ok(())
    }

    fn finish(mut self) -> Result<FrozenGraphResearchSnapshot, FrozenGraphResearchError> {
        self.incidences.sort_unstable_by(|left, right| {
            left.hyperedge
                .cmp(&right.hyperedge)
                .then_with(|| left.role.cmp(&right.role))
                .then_with(|| left.participant.cmp(&right.participant))
        });
        let digest = dataset_digest(&(
            self.input.checkpoint.meta.checkpoint_id.as_str(),
            self.input.checkpoint.meta.generation,
            self.input.frozen_at_ms,
            self.input.split_policy,
            &self.nodes,
            &self.edges,
            &self.incidences,
            &self.proposals,
        ))?;
        Ok(FrozenGraphResearchSnapshot {
            dataset_id: format_compact!("b3-{digest}"),
            checkpoint_id: CompactString::new(&self.input.checkpoint.meta.checkpoint_id),
            checkpoint_generation: self.input.checkpoint.meta.generation,
            frozen_at_ms: self.input.frozen_at_ms,
            split_policy: self.input.split_policy,
            nodes: self.nodes,
            edges: self.edges,
            incidences: self.incidences,
            proposals: self.proposals,
        })
    }

    fn push_node(&mut self, node: ResearchNode) -> Result<u32, FrozenGraphResearchError> {
        if self.node_by_id.contains_key(&node.id) {
            return Err(FrozenGraphResearchError::DuplicateId(node.id.to_string()));
        }
        let ordinal = u32::try_from(self.nodes.len())
            .map_err(|_| FrozenGraphResearchError::CorruptArtifact("node ordinal overflow"))?;
        self.node_by_id.insert(node.id.clone(), ordinal);
        self.nodes.push(node);
        Ok(ordinal)
    }

    fn synthetic_candidate_node(
        &mut self,
        kind: &str,
        external_id: &str,
        observed_at: i64,
    ) -> Result<u32, FrozenGraphResearchError> {
        let id = format_compact!("candidate-target:{kind}:{external_id}");
        if let Some(value) = self.node_by_id.get(&id).copied() {
            return Ok(value);
        }
        let ordinal = self.push_node(ResearchNode {
            id,
            kind: CompactString::new(kind),
            authority: ResearchAuthority::Candidate,
            split: self.input.split_policy.split(observed_at),
            available_at_ms: observed_at,
            source_generation: self.input.checkpoint.meta.generation,
        })?;
        self.alias_external(external_id, ordinal);
        Ok(ordinal)
    }

    fn alias_external(&mut self, value: &str, ordinal: u32) {
        self.node_by_external_id
            .entry(CompactString::new(value))
            .or_insert(ordinal);
    }

    fn lookup_vertex(&self, id: &str) -> Result<u32, FrozenGraphResearchError> {
        self.node_by_external_id
            .get(id)
            .copied()
            .ok_or_else(|| FrozenGraphResearchError::MissingVertex(id.to_owned()))
    }

    fn ensure_not_future(&self, timestamp: i64) -> Result<(), FrozenGraphResearchError> {
        if timestamp <= 0 || timestamp > self.input.frozen_at_ms {
            Err(FrozenGraphResearchError::FutureGraphData)
        } else {
            Ok(())
        }
    }
}

fn vertex_kind(vertex: &KernelVertex) -> &str {
    if vertex.kind.is_empty() {
        "unknown"
    } else {
        &vertex.kind
    }
}

fn edge_key(edge: &KernelEdge) -> (&str, &str, &str) {
    (&edge.source_id.0, &edge.edge_type.0, &edge.target_id.0)
}

fn proposal_label(value: GraphProposalOutcomeKind) -> ResearchProposalLabel {
    match value {
        GraphProposalOutcomeKind::Uncommitted => ResearchProposalLabel::Uncommitted,
        GraphProposalOutcomeKind::Active => ResearchProposalLabel::Active,
        GraphProposalOutcomeKind::Superseded => ResearchProposalLabel::Superseded,
        GraphProposalOutcomeKind::Retracted => ResearchProposalLabel::Retracted,
        GraphProposalOutcomeKind::Reverted => ResearchProposalLabel::Reverted,
    }
}

fn feature_schema_id(receipt: &GraphProposalBatchReceipt) -> CompactString {
    format_compact!(
        "{}@{}:{}@{}",
        receipt.compiler_policy.compiler_id,
        receipt.compiler_policy.compiler_version,
        receipt.compiler_policy.policy_id,
        receipt.compiler_policy.policy_version
    )
}

fn dataset_digest(value: &impl Serialize) -> Result<String, FrozenGraphResearchError> {
    let bytes = serde_json::to_vec(value)?;
    Ok(blake3::hash(&bytes).to_hex().to_string())
}
