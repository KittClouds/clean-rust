use std::collections::BTreeSet;

use compact_str::CompactString;
use hashbrown::HashMap;
use phoenix_types::{ConstraintKind, DependencyClass, StoryInterval};
use serde::{Deserialize, Serialize};
use smallvec::SmallVec;
use thiserror::Error;

use crate::GraphGeneration;

pub const REVISION_ANALYSIS_VIEWS_SCHEMA: &str = "phoenix-revision-analysis-views/v1";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceRef {
    pub evidence_id: CompactString,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub document_id: Option<CompactString>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_range: Option<SourceRange>,
}

impl EvidenceRef {
    pub fn anchored(evidence_id: impl Into<CompactString>) -> Self {
        Self {
            evidence_id: evidence_id.into(),
            document_id: None,
            source_range: None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceRange {
    pub start: u32,
    pub end: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConstraintSeed {
    pub constraint_id: CompactString,
    pub source_id: CompactString,
    pub dependent_id: CompactString,
    pub kind: ConstraintKind,
    pub valid_interval: StoryInterval,
    pub evidence: Vec<EvidenceRef>,
    pub confidence_millis: u16,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConstraintNode {
    pub id: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConstraintAtom {
    pub constraint_id: CompactString,
    pub source: u32,
    pub dependent: u32,
    pub kind: ConstraintKind,
    pub strength: DependencyClass,
    pub valid_interval: StoryInterval,
    pub evidence: SmallVec<[EvidenceRef; 2]>,
    pub confidence_millis: u16,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConstraintGraph {
    generation: GraphGeneration,
    nodes: Box<[ConstraintNode]>,
    outgoing_offsets: Box<[u32]>,
    atoms: Box<[ConstraintAtom]>,
}

impl ConstraintGraph {
    pub const fn generation(&self) -> GraphGeneration {
        self.generation
    }

    pub fn nodes(&self) -> &[ConstraintNode] {
        &self.nodes
    }

    pub fn atoms(&self) -> &[ConstraintAtom] {
        &self.atoms
    }

    pub fn node_index(&self, id: &str) -> Option<u32> {
        self.nodes
            .binary_search_by(|node| node.id.as_str().cmp(id))
            .ok()
            .map(|index| index as u32)
    }

    pub fn outgoing(&self, node: u32) -> &[ConstraintAtom] {
        self.outgoing_with_start(node).1
    }

    pub(crate) fn outgoing_with_start(&self, node: u32) -> (u32, &[ConstraintAtom]) {
        let index = node as usize;
        let Some((&start, &end)) = self
            .outgoing_offsets
            .get(index)
            .zip(self.outgoing_offsets.get(index + 1))
        else {
            return (0, &[]);
        };
        (start, &self.atoms[start as usize..end as usize])
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InferenceAuthority {
    Asserted,
    Accepted,
    Candidate,
    Rejected,
}

impl InferenceAuthority {
    const fn admitted(self) -> bool {
        matches!(self, Self::Asserted | Self::Accepted)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct InferenceNodeSeed {
    pub node_id: CompactString,
    pub node_type: CompactString,
    pub embedding_text: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct InferenceEdgeSeed {
    pub edge_id: CompactString,
    pub source_id: CompactString,
    pub target_id: CompactString,
    pub relation_type: CompactString,
    pub authority: InferenceAuthority,
    #[serde(default)]
    pub evidence_ids: Vec<CompactString>,
    pub confidence_millis: u16,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InferenceProjectionInput {
    pub accepted_nodes: Vec<InferenceNodeSeed>,
    pub relations: Vec<InferenceEdgeSeed>,
    pub memberships: Vec<InferenceEdgeSeed>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InferenceNode {
    pub node_id: CompactString,
    pub node_type_id: u32,
    pub embedding_text: CompactString,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InferenceEdgeKind {
    Relation,
    Membership,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InferenceEdgeMetadata {
    pub edge_id: CompactString,
    pub kind: InferenceEdgeKind,
    pub evidence_ids: SmallVec<[CompactString; 2]>,
    pub confidence_millis: u16,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InferenceProjectionReceipt {
    pub input_relations: usize,
    pub input_memberships: usize,
    pub admitted_relations: usize,
    pub admitted_memberships: usize,
    pub excluded_candidate_edges: usize,
    pub excluded_rejected_edges: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InferenceGraph {
    generation: GraphGeneration,
    nodes: Box<[InferenceNode]>,
    node_types: Box<[CompactString]>,
    relation_types: Box<[CompactString]>,
    incoming_offsets: Box<[u32]>,
    source_ids: Box<[u32]>,
    relation_type_ids: Box<[u32]>,
    edge_metadata: Box<[InferenceEdgeMetadata]>,
    receipt: InferenceProjectionReceipt,
}

impl InferenceGraph {
    pub const fn generation(&self) -> GraphGeneration {
        self.generation
    }

    pub fn nodes(&self) -> &[InferenceNode] {
        &self.nodes
    }

    pub fn node_types(&self) -> &[CompactString] {
        &self.node_types
    }

    pub fn relation_types(&self) -> &[CompactString] {
        &self.relation_types
    }

    pub fn incoming_offsets(&self) -> &[u32] {
        &self.incoming_offsets
    }

    pub fn source_ids(&self) -> &[u32] {
        &self.source_ids
    }

    pub fn relation_type_ids(&self) -> &[u32] {
        &self.relation_type_ids
    }

    pub fn edge_metadata(&self) -> &[InferenceEdgeMetadata] {
        &self.edge_metadata
    }

    pub const fn receipt(&self) -> &InferenceProjectionReceipt {
        &self.receipt
    }

    pub fn node_index(&self, id: &str) -> Option<u32> {
        self.nodes
            .binary_search_by(|node| node.node_id.as_str().cmp(id))
            .ok()
            .map(|index| index as u32)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RevisionAnalysisViews {
    pub constraint_graph: ConstraintGraph,
    pub inference_graph: InferenceGraph,
}

impl RevisionAnalysisViews {
    pub fn project(
        generation: GraphGeneration,
        constraints: Vec<ConstraintSeed>,
        inference: InferenceProjectionInput,
    ) -> Result<Self, ProjectionError> {
        let constraint_graph = project_constraints(generation, constraints)?;
        let inference_graph = project_inference(generation, inference)?;
        Ok(Self {
            constraint_graph,
            inference_graph,
        })
    }

    pub fn generation(&self) -> GraphGeneration {
        debug_assert_eq!(
            self.constraint_graph.generation(),
            self.inference_graph.generation()
        );
        self.constraint_graph.generation()
    }
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum ProjectionError {
    #[error("duplicate {kind} id {id}")]
    DuplicateId {
        kind: &'static str,
        id: CompactString,
    },
    #[error("{kind} {id} has an empty required field")]
    EmptyField {
        kind: &'static str,
        id: CompactString,
    },
    #[error("constraint {0} has no evidence")]
    MissingConstraintEvidence(CompactString),
    #[error("invalid evidence range {0}")]
    InvalidEvidenceRange(CompactString),
    #[error("invalid story interval {0}")]
    InvalidStoryInterval(CompactString),
    #[error("confidence exceeds 1000 for {0}")]
    InvalidConfidence(CompactString),
    #[error("admitted edge {edge_id} references missing node {node_id}")]
    MissingInferenceNode {
        edge_id: CompactString,
        node_id: CompactString,
    },
    #[error("projection exceeds u32 indexing capacity")]
    IndexOverflow,
}

fn project_constraints(
    generation: GraphGeneration,
    mut seeds: Vec<ConstraintSeed>,
) -> Result<ConstraintGraph, ProjectionError> {
    seeds.sort_unstable_by(|left, right| left.constraint_id.cmp(&right.constraint_id));
    reject_duplicate_ids(
        seeds.iter().map(|seed| seed.constraint_id.as_str()),
        "constraint",
    )?;
    let mut node_ids = BTreeSet::new();
    for seed in &seeds {
        validate_constraint(seed)?;
        node_ids.insert(seed.source_id.clone());
        node_ids.insert(seed.dependent_id.clone());
    }
    let nodes = node_ids
        .into_iter()
        .map(|id| ConstraintNode { id })
        .collect::<Vec<_>>();
    ensure_u32(nodes.len().max(seeds.len()))?;
    let node_index = nodes
        .iter()
        .enumerate()
        .map(|(index, node)| (node.id.as_str(), index as u32))
        .collect::<HashMap<_, _>>();
    let mut atoms = seeds
        .into_iter()
        .map(|seed| ConstraintAtom {
            source: node_index[seed.source_id.as_str()],
            dependent: node_index[seed.dependent_id.as_str()],
            strength: seed.kind.dependency_class(),
            constraint_id: seed.constraint_id,
            kind: seed.kind,
            valid_interval: seed.valid_interval,
            evidence: seed.evidence.into_iter().collect(),
            confidence_millis: seed.confidence_millis,
        })
        .collect::<Vec<_>>();
    drop(node_index);
    atoms.sort_unstable_by(|left, right| {
        left.source
            .cmp(&right.source)
            .then_with(|| constraint_rank(left.kind).cmp(&constraint_rank(right.kind)))
            .then_with(|| left.dependent.cmp(&right.dependent))
            .then_with(|| left.constraint_id.cmp(&right.constraint_id))
    });
    let outgoing_offsets = csr_offsets(nodes.len(), atoms.iter().map(|atom| atom.source))?;
    Ok(ConstraintGraph {
        generation,
        nodes: nodes.into_boxed_slice(),
        outgoing_offsets,
        atoms: atoms.into_boxed_slice(),
    })
}

fn project_inference(
    generation: GraphGeneration,
    mut input: InferenceProjectionInput,
) -> Result<InferenceGraph, ProjectionError> {
    input
        .accepted_nodes
        .sort_unstable_by(|left, right| left.node_id.cmp(&right.node_id));
    reject_duplicate_ids(
        input
            .accepted_nodes
            .iter()
            .map(|node| node.node_id.as_str()),
        "inference node",
    )?;
    for node in &input.accepted_nodes {
        if node.node_id.is_empty() || node.node_type.is_empty() || node.embedding_text.is_empty() {
            return Err(ProjectionError::EmptyField {
                kind: "inference node",
                id: node.node_id.clone(),
            });
        }
    }
    ensure_u32(input.accepted_nodes.len())?;

    let mut node_types = input
        .accepted_nodes
        .iter()
        .map(|node| node.node_type.clone())
        .collect::<Vec<_>>();
    node_types.sort_unstable();
    node_types.dedup();
    let node_type_index = node_types
        .iter()
        .enumerate()
        .map(|(index, kind)| (kind.as_str(), index as u32))
        .collect::<HashMap<_, _>>();
    let nodes = input
        .accepted_nodes
        .into_iter()
        .map(|node| InferenceNode {
            node_type_id: node_type_index[node.node_type.as_str()],
            node_id: node.node_id,
            embedding_text: node.embedding_text,
        })
        .collect::<Vec<_>>();
    drop(node_type_index);
    let node_index = nodes
        .iter()
        .enumerate()
        .map(|(index, node)| (node.node_id.as_str(), index as u32))
        .collect::<HashMap<_, _>>();

    let mut receipt = InferenceProjectionReceipt {
        input_relations: input.relations.len(),
        input_memberships: input.memberships.len(),
        ..InferenceProjectionReceipt::default()
    };
    let mut admitted = Vec::with_capacity(input.relations.len() + input.memberships.len());
    collect_admitted(
        input.relations,
        InferenceEdgeKind::Relation,
        &node_index,
        &mut admitted,
        &mut receipt,
    )?;
    collect_admitted(
        input.memberships,
        InferenceEdgeKind::Membership,
        &node_index,
        &mut admitted,
        &mut receipt,
    )?;
    ensure_u32(admitted.len())?;
    admitted.sort_unstable_by(|left, right| left.seed.edge_id.cmp(&right.seed.edge_id));
    reject_duplicate_ids(
        admitted.iter().map(|edge| edge.seed.edge_id.as_str()),
        "admitted inference edge",
    )?;

    let mut relation_types = admitted
        .iter()
        .map(|edge| edge.seed.relation_type.clone())
        .collect::<Vec<_>>();
    relation_types.sort_unstable();
    relation_types.dedup();
    let relation_index = relation_types
        .iter()
        .enumerate()
        .map(|(index, relation)| (relation.as_str(), index as u32))
        .collect::<HashMap<_, _>>();
    let mut edges = admitted
        .into_iter()
        .map(|edge| IndexedInferenceEdge {
            source: node_index[edge.seed.source_id.as_str()],
            target: node_index[edge.seed.target_id.as_str()],
            relation_type: relation_index[edge.seed.relation_type.as_str()],
            metadata: InferenceEdgeMetadata {
                edge_id: edge.seed.edge_id,
                kind: edge.kind,
                evidence_ids: edge.seed.evidence_ids.into_iter().collect(),
                confidence_millis: edge.seed.confidence_millis,
            },
        })
        .collect::<Vec<_>>();
    drop(node_index);
    drop(relation_index);
    edges.sort_unstable_by(|left, right| {
        left.target
            .cmp(&right.target)
            .then_with(|| left.relation_type.cmp(&right.relation_type))
            .then_with(|| left.source.cmp(&right.source))
            .then_with(|| left.metadata.edge_id.cmp(&right.metadata.edge_id))
    });
    let incoming_offsets = csr_offsets(nodes.len(), edges.iter().map(|edge| edge.target))?;
    let mut source_ids = Vec::with_capacity(edges.len());
    let mut relation_type_ids = Vec::with_capacity(edges.len());
    let mut metadata = Vec::with_capacity(edges.len());
    for edge in edges {
        source_ids.push(edge.source);
        relation_type_ids.push(edge.relation_type);
        metadata.push(edge.metadata);
    }
    Ok(InferenceGraph {
        generation,
        nodes: nodes.into_boxed_slice(),
        node_types: node_types.into_boxed_slice(),
        relation_types: relation_types.into_boxed_slice(),
        incoming_offsets,
        source_ids: source_ids.into_boxed_slice(),
        relation_type_ids: relation_type_ids.into_boxed_slice(),
        edge_metadata: metadata.into_boxed_slice(),
        receipt,
    })
}

struct AdmittedEdge {
    seed: InferenceEdgeSeed,
    kind: InferenceEdgeKind,
}

struct IndexedInferenceEdge {
    source: u32,
    target: u32,
    relation_type: u32,
    metadata: InferenceEdgeMetadata,
}

fn collect_admitted(
    seeds: Vec<InferenceEdgeSeed>,
    kind: InferenceEdgeKind,
    node_index: &HashMap<&str, u32>,
    admitted: &mut Vec<AdmittedEdge>,
    receipt: &mut InferenceProjectionReceipt,
) -> Result<(), ProjectionError> {
    for seed in seeds {
        if seed.confidence_millis > 1000 {
            return Err(ProjectionError::InvalidConfidence(seed.edge_id));
        }
        if !seed.authority.admitted() {
            match seed.authority {
                InferenceAuthority::Candidate => receipt.excluded_candidate_edges += 1,
                InferenceAuthority::Rejected => receipt.excluded_rejected_edges += 1,
                InferenceAuthority::Asserted | InferenceAuthority::Accepted => unreachable!(),
            }
            continue;
        }
        if seed.edge_id.is_empty() || seed.relation_type.is_empty() {
            return Err(ProjectionError::EmptyField {
                kind: "inference edge",
                id: seed.edge_id,
            });
        }
        for node_id in [&seed.source_id, &seed.target_id] {
            if !node_index.contains_key(node_id.as_str()) {
                return Err(ProjectionError::MissingInferenceNode {
                    edge_id: seed.edge_id,
                    node_id: node_id.clone(),
                });
            }
        }
        match kind {
            InferenceEdgeKind::Relation => receipt.admitted_relations += 1,
            InferenceEdgeKind::Membership => receipt.admitted_memberships += 1,
        }
        admitted.push(AdmittedEdge { seed, kind });
    }
    Ok(())
}

fn validate_constraint(seed: &ConstraintSeed) -> Result<(), ProjectionError> {
    if seed.constraint_id.is_empty() || seed.source_id.is_empty() || seed.dependent_id.is_empty() {
        return Err(ProjectionError::EmptyField {
            kind: "constraint",
            id: seed.constraint_id.clone(),
        });
    }
    if !seed.valid_interval.is_well_formed() {
        return Err(ProjectionError::InvalidStoryInterval(
            seed.constraint_id.clone(),
        ));
    }
    if seed.confidence_millis > 1000 {
        return Err(ProjectionError::InvalidConfidence(
            seed.constraint_id.clone(),
        ));
    }
    if seed.evidence.is_empty() {
        return Err(ProjectionError::MissingConstraintEvidence(
            seed.constraint_id.clone(),
        ));
    }
    for evidence in &seed.evidence {
        if evidence.evidence_id.is_empty()
            || evidence
                .source_range
                .is_some_and(|range| range.start >= range.end)
        {
            return Err(ProjectionError::InvalidEvidenceRange(
                seed.constraint_id.clone(),
            ));
        }
    }
    Ok(())
}

fn csr_offsets(
    node_count: usize,
    sorted_node_ids: impl Iterator<Item = u32>,
) -> Result<Box<[u32]>, ProjectionError> {
    ensure_u32(node_count)?;
    let mut offsets = vec![0_u32; node_count + 1];
    for node in sorted_node_ids {
        let slot = node as usize + 1;
        offsets[slot] = offsets[slot]
            .checked_add(1)
            .ok_or(ProjectionError::IndexOverflow)?;
    }
    for index in 1..offsets.len() {
        offsets[index] = offsets[index]
            .checked_add(offsets[index - 1])
            .ok_or(ProjectionError::IndexOverflow)?;
    }
    Ok(offsets.into_boxed_slice())
}

fn reject_duplicate_ids<'a>(
    sorted: impl Iterator<Item = &'a str>,
    kind: &'static str,
) -> Result<(), ProjectionError> {
    let mut previous = None;
    for id in sorted {
        if previous == Some(id) {
            return Err(ProjectionError::DuplicateId {
                kind,
                id: id.into(),
            });
        }
        previous = Some(id);
    }
    Ok(())
}

fn ensure_u32(value: usize) -> Result<(), ProjectionError> {
    u32::try_from(value)
        .map(drop)
        .map_err(|_| ProjectionError::IndexOverflow)
}

const fn constraint_rank(kind: ConstraintKind) -> u8 {
    match kind {
        ConstraintKind::RequiresKnowledge => 0,
        ConstraintKind::RequiresWitness => 1,
        ConstraintKind::RequiresAlive => 2,
        ConstraintKind::RequiresPossession => 3,
        ConstraintKind::RequiresReachability => 4,
        ConstraintKind::RequiresState => 5,
        ConstraintKind::RequiresTemporalOrder => 6,
        ConstraintKind::MutuallyExclusiveStates => 7,
        ConstraintKind::CausalSupport => 8,
        ConstraintKind::Motivation => 9,
        ConstraintKind::Foreshadowing => 10,
        ConstraintKind::Mention => 11,
        ConstraintKind::ThematicEcho => 12,
    }
}

#[cfg(test)]
#[path = "projection_tests.rs"]
mod tests;
