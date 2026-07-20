use crate::DiscoveryCandidateLedger;
use hashbrown::HashSet;
use phoenix_graph_kernel::{
    DiscoveryPathProposalOrigin, GraphProposalBatchReceipt, GraphProposalFeatures,
    GraphProposalObservation, GraphProposalReceiptError, GraphProposalStatus, GraphTruthAtomKey,
    GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
};
use phoenix_store_native_core::{
    GraphProposalReceiptAppend, PhoenixGraphLearningStore, StoreError,
};
use phoenix_types::{
    GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthSourceGenerationRef,
};
use serde::Serialize;
use thiserror::Error;

const DISCOVERY_PROPOSAL_POLICY_ID: &str = "phoenix-discovery-human-atom-proposal";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HumanGraphProposalIdentification {
    pub source_path_receipt_id: String,
    pub scope_key: String,
    pub identified_by_user_id: String,
    pub identification_rationale: String,
    pub created_at: i64,
    pub atom: GraphTruthAtomKey,
    pub family: String,
    pub source_kind: String,
    pub target_kind: String,
    pub truth: GraphTruthDescriptor,
    pub supporting_path_node_indices: Vec<u32>,
    pub supporting_path_edge_indices: Vec<u32>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GraphProposalBatchPublication {
    pub receipt: GraphProposalBatchReceipt,
    pub append: GraphProposalReceiptAppend,
    pub topology_writes: u32,
}

#[derive(Debug, Error)]
pub enum DiscoveryGraphProposalError {
    #[error("invalid discovery graph proposal: {0}")]
    Invalid(String),
    #[error(transparent)]
    Receipt(#[from] GraphProposalReceiptError),
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

impl DiscoveryCandidateLedger {
    pub fn publish_human_graph_proposal<S>(
        &self,
        store: &S,
        mut identification: HumanGraphProposalIdentification,
    ) -> Result<GraphProposalBatchPublication, DiscoveryGraphProposalError>
    where
        S: PhoenixGraphLearningStore + ?Sized,
    {
        validate_identification(&identification)?;
        let path_receipt = self
            .load_path_receipt(&identification.source_path_receipt_id)
            .map_err(|error| DiscoveryGraphProposalError::Invalid(error.to_string()))?;
        canonicalize_support(
            &mut identification.supporting_path_node_indices,
            path_receipt.path.node_identities.len(),
            "node",
        )?;
        canonicalize_support(
            &mut identification.supporting_path_edge_indices,
            path_receipt.path.edges.len(),
            "edge",
        )?;
        let required_nodes = match &identification.atom {
            GraphTruthAtomKey::Vertex { .. } => 1,
            GraphTruthAtomKey::Edge { .. } => 2,
        };
        if identification.supporting_path_node_indices.len() < required_nodes
            || identification.supporting_path_edge_indices.is_empty()
        {
            return Err(DiscoveryGraphProposalError::Invalid(
                "a proposed atom must name its supporting path nodes and at least one evidence edge"
                    .to_owned(),
            ));
        }

        let evidence_refs = selected_evidence_refs(
            &path_receipt.path.edges,
            &identification.supporting_path_edge_indices,
        );
        if evidence_refs.is_empty() {
            return Err(DiscoveryGraphProposalError::Invalid(
                "selected path support contains no authoritative evidence".to_owned(),
            ));
        }
        let proposal_id = proposal_identity(&identification)?;
        let origin = DiscoveryPathProposalOrigin {
            source_path_receipt_id: identification.source_path_receipt_id.clone().into(),
            identified_by_user_id: identification.identified_by_user_id.into(),
            identification_rationale: identification.identification_rationale.into(),
            supporting_path_node_indices: identification
                .supporting_path_node_indices
                .into_iter()
                .collect(),
            supporting_path_edge_indices: identification
                .supporting_path_edge_indices
                .into_iter()
                .collect(),
        };
        let proposal = GraphProposalObservation {
            proposal_id: proposal_id.into(),
            atom: identification.atom,
            family: identification.family.into(),
            source_kind: identification.source_kind.into(),
            target_kind: identification.target_kind.into(),
            truth: identification.truth,
            status: GraphProposalStatus::Generated,
            evidence_refs: evidence_refs.into_iter().map(Into::into).collect(),
            features: GraphProposalFeatures::default(),
            shadow_score_millis: None,
        };
        let mut receipt = GraphProposalBatchReceipt {
            schema_version: GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
            receipt_id: "pending".into(),
            scope_key: identification.scope_key.into(),
            generation: path_receipt.authority.graph_generation,
            created_at: identification.created_at,
            compiler_policy: GraphTruthCompilerPolicy {
                compiler_id: "phoenix-discovery-runtime".into(),
                compiler_version: env!("CARGO_PKG_VERSION").into(),
                policy_id: DISCOVERY_PROPOSAL_POLICY_ID.into(),
                policy_version: "1".into(),
            },
            source_generations: [GraphTruthSourceGenerationRef {
                source_id: format!("discovery-path-receipt:{}", path_receipt.receipt_id).into(),
                generation: path_receipt.authority.graph_generation,
            }]
            .into_iter()
            .collect(),
            model_id: None,
            discovery_origin: Some(origin),
            proposals: vec![proposal],
        };
        receipt.receipt_id = receipt_identity(&receipt)?.into();
        receipt.validate()?;
        let append = store.append_graph_proposal_receipt(&receipt)?;
        Ok(GraphProposalBatchPublication {
            receipt,
            append,
            topology_writes: 0,
        })
    }
}

fn validate_identification(
    identification: &HumanGraphProposalIdentification,
) -> Result<(), DiscoveryGraphProposalError> {
    if identification.scope_key.trim().is_empty()
        || identification.identified_by_user_id.trim().is_empty()
        || identification.identification_rationale.trim().is_empty()
        || identification.created_at <= 0
        || identification.family.trim().is_empty()
        || identification.source_kind.trim().is_empty()
        || identification.target_kind.trim().is_empty()
    {
        return Err(DiscoveryGraphProposalError::Invalid(
            "human, rationale, scope, timestamp, and typed atom fields are required".to_owned(),
        ));
    }
    identification.truth.validate().map_err(|error| {
        DiscoveryGraphProposalError::Invalid(format!("truth descriptor: {error:?}"))
    })?;
    let atom_valid = match &identification.atom {
        GraphTruthAtomKey::Vertex { vertex_id } => !vertex_id.trim().is_empty(),
        GraphTruthAtomKey::Edge {
            source_id,
            target_id,
            edge_type,
        } => {
            !source_id.trim().is_empty()
                && !target_id.trim().is_empty()
                && !edge_type.trim().is_empty()
                && source_id != target_id
        }
    };
    if !atom_valid {
        return Err(DiscoveryGraphProposalError::Invalid(
            "the proposed atom identity is incomplete or self-referential".to_owned(),
        ));
    }
    Ok(())
}

fn canonicalize_support(
    values: &mut [u32],
    path_len: usize,
    kind: &str,
) -> Result<(), DiscoveryGraphProposalError> {
    values.sort_unstable();
    if values.windows(2).any(|window| window[0] == window[1]) {
        return Err(DiscoveryGraphProposalError::Invalid(format!(
            "duplicate supporting path {kind} index"
        )));
    }
    if values.iter().any(|value| *value as usize >= path_len) {
        return Err(DiscoveryGraphProposalError::Invalid(format!(
            "supporting path {kind} index is out of bounds"
        )));
    }
    Ok(())
}

fn selected_evidence_refs(
    edges: &[phoenix_discovery_query::EdgeReceipt],
    selected_edges: &[u32],
) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut evidence = Vec::new();
    for edge_index in selected_edges {
        for identity in &edges[*edge_index as usize].evidence {
            let value = format!(
                "query-stable-id:{:016x}:{:04x}",
                identity.hash, identity.collision
            );
            if seen.insert(value.clone()) {
                evidence.push(value);
            }
        }
    }
    evidence
}

fn proposal_identity(
    identification: &HumanGraphProposalIdentification,
) -> Result<String, serde_json::Error> {
    content_identity(
        b"phoenix-discovery-proposed-atom/v1\0",
        &(
            &identification.source_path_receipt_id,
            &identification.atom,
            &identification.supporting_path_node_indices,
            &identification.supporting_path_edge_indices,
        ),
    )
}

fn receipt_identity(receipt: &GraphProposalBatchReceipt) -> Result<String, serde_json::Error> {
    let mut content = receipt.clone();
    content.receipt_id = "pending".into();
    content_identity(b"phoenix-discovery-graph-proposal-batch/v1\0", &content)
}

fn content_identity<T: Serialize>(domain: &[u8], value: &T) -> Result<String, serde_json::Error> {
    let bytes = serde_json::to_vec(value)?;
    let mut hasher = blake3::Hasher::new();
    hasher.update(domain);
    hasher.update(&bytes);
    Ok(hasher.finalize().to_hex().to_string())
}
