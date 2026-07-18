use std::collections::BTreeSet;
use std::path::Path;

use phoenix_revision_impact::{
    InferenceAuthority, InferenceEdgeKind, InferenceEdgeSeed, InferenceGraph, InferenceNodeSeed,
    InferenceProjectionInput, RevisionAnalysisViews,
};
use serde::{Deserialize, Serialize};

use crate::{
    InferenceArtifactError, ReasonerAssets, ReasonerBundle, ReasonerInferenceOutput,
    ReasonerProjection, Result, project_reasoner, run_reasoner_candidate_set,
};

pub const MAX_REASONER_CANDIDATES: usize = 64;
pub const MAX_REASONER_START_NODES: usize = 8;
pub const MAX_REASONER_RESIDENT_NODES: usize = 256;

pub struct BoundedReasonerProjection {
    pub projection: ReasonerProjection,
    pub candidate_ids: Box<[String]>,
    pub receipt: BoundedReasonerBoundaryReceipt,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BoundedReasonerBoundaryReceipt {
    pub candidate_count: u32,
    pub start_node_count: u32,
    pub resident_node_count: u32,
    pub resident_edge_count: u32,
    pub omitted_neighbor_count: u32,
    pub excluded_candidate_edges: u64,
    pub excluded_rejected_edges: u64,
    pub no_topology_writes: bool,
    pub full_corpus_materialization_rejected: bool,
}

#[derive(Debug)]
pub struct BoundedReasonerInferenceOutput {
    pub inference: ReasonerInferenceOutput,
    pub boundary: BoundedReasonerBoundaryReceipt,
}

pub fn project_bounded_reasoner(
    graph: &InferenceGraph,
    candidate_node_ids: &[&str],
    start_node_ids: &[&str],
    requested_type: &str,
) -> Result<BoundedReasonerProjection> {
    let candidates = checked_ids(
        graph,
        candidate_node_ids,
        requested_type,
        MAX_REASONER_CANDIDATES,
        "candidate",
    )?;
    let starts = checked_ids(graph, start_node_ids, "", MAX_REASONER_START_NODES, "start")?;
    let mut selected = candidates.clone();
    selected.extend(starts.iter().cloned());

    let mut neighbors = BTreeSet::new();
    visit_graph_edges(graph, |source, target, _, _, _| {
        if selected.contains(source) {
            neighbors.insert(target.to_owned());
        }
        if selected.contains(target) {
            neighbors.insert(source.to_owned());
        }
    });
    neighbors.retain(|id| !selected.contains(id));
    let neighbor_count = neighbors.len();
    let available = MAX_REASONER_RESIDENT_NODES.saturating_sub(selected.len());
    selected.extend(neighbors.into_iter().take(available));

    let accepted_nodes = graph
        .nodes()
        .iter()
        .filter(|node| selected.contains(node.node_id.as_str()))
        .map(|node| InferenceNodeSeed {
            node_id: node.node_id.clone(),
            node_type: graph.node_types()[node.node_type_id as usize].clone(),
            embedding_text: node.embedding_text.clone(),
        })
        .collect::<Vec<_>>();
    let mut relations = Vec::new();
    let mut memberships = Vec::new();
    visit_graph_edges(graph, |source, target, relation, metadata, kind| {
        if !selected.contains(source) || !selected.contains(target) {
            return;
        }
        let seed = InferenceEdgeSeed {
            edge_id: metadata.edge_id.clone(),
            source_id: source.into(),
            target_id: target.into(),
            relation_type: relation.into(),
            authority: InferenceAuthority::Asserted,
            evidence_ids: metadata.evidence_ids.iter().cloned().collect(),
            confidence_millis: metadata.confidence_millis,
        };
        match kind {
            InferenceEdgeKind::Relation => relations.push(seed),
            InferenceEdgeKind::Membership => memberships.push(seed),
        }
    });
    let bounded = RevisionAnalysisViews::project(
        graph.generation(),
        Vec::new(),
        InferenceProjectionInput {
            accepted_nodes,
            relations,
            memberships,
        },
    )
    .map_err(|error| InferenceArtifactError::InvalidProjection(error.to_string()))?
    .inference_graph;
    let resident_edge_count = bounded.source_ids().len();
    let projection = project_reasoner(&bounded)?;
    let receipt = BoundedReasonerBoundaryReceipt {
        candidate_count: count(candidates.len()),
        start_node_count: count(starts.len()),
        resident_node_count: count(bounded.nodes().len()),
        resident_edge_count: count(resident_edge_count),
        omitted_neighbor_count: count(neighbor_count.saturating_sub(available)),
        excluded_candidate_edges: graph.receipt().excluded_candidate_edges as u64,
        excluded_rejected_edges: graph.receipt().excluded_rejected_edges as u64,
        no_topology_writes: true,
        full_corpus_materialization_rejected: true,
    };
    Ok(BoundedReasonerProjection {
        projection,
        candidate_ids: candidates
            .into_iter()
            .collect::<Vec<_>>()
            .into_boxed_slice(),
        receipt,
    })
}

#[allow(clippy::too_many_arguments)]
pub fn run_bounded_reasoner_complete(
    bundle_root: impl AsRef<Path>,
    assets: &ReasonerAssets,
    query: &str,
    start_node_ids: &[&str],
    requested_type: &str,
    candidate_node_ids: &[&str],
    top_k: usize,
    boundary: BoundedReasonerBoundaryReceipt,
) -> Result<BoundedReasonerInferenceOutput> {
    let bundle = ReasonerBundle::open(bundle_root.as_ref())?;
    if bundle.manifest.node_ids.len() > MAX_REASONER_RESIDENT_NODES {
        return Err(InferenceArtifactError::InvalidProjection(format!(
            "bounded reasoner bundle has {} nodes; maximum is {MAX_REASONER_RESIDENT_NODES}",
            bundle.manifest.node_ids.len()
        )));
    }
    if candidate_node_ids.is_empty() || candidate_node_ids.len() > MAX_REASONER_CANDIDATES {
        return Err(InferenceArtifactError::InvalidProjection(format!(
            "bounded reasoner requires 1..={MAX_REASONER_CANDIDATES} candidates"
        )));
    }
    let inference = run_reasoner_candidate_set(
        bundle_root,
        assets,
        query,
        start_node_ids,
        requested_type,
        candidate_node_ids,
        top_k.min(candidate_node_ids.len()),
    )?;
    assert_candidate_subset(
        inference
            .ranking
            .ranked_nodes
            .iter()
            .map(|node| node.stable_id.as_str()),
        candidate_node_ids,
    )?;
    Ok(BoundedReasonerInferenceOutput {
        inference,
        boundary,
    })
}

fn assert_candidate_subset<'a>(
    ranked_ids: impl IntoIterator<Item = &'a str>,
    candidate_node_ids: &[&str],
) -> Result<()> {
    let candidates = candidate_node_ids.iter().copied().collect::<BTreeSet<_>>();
    if let Some(leaked) = ranked_ids.into_iter().find(|id| !candidates.contains(id)) {
        return Err(InferenceArtifactError::InvalidProjection(format!(
            "bounded reasoner ranking escaped candidate set: {leaked}"
        )));
    }
    Ok(())
}

fn checked_ids(
    graph: &InferenceGraph,
    requested: &[&str],
    requested_type: &str,
    limit: usize,
    label: &str,
) -> Result<BTreeSet<String>> {
    if requested.is_empty() || requested.len() > limit {
        return Err(InferenceArtifactError::InvalidProjection(format!(
            "bounded reasoner requires 1..={limit} {label} nodes"
        )));
    }
    let ids = requested
        .iter()
        .map(|id| (*id).to_owned())
        .collect::<BTreeSet<_>>();
    if ids.len() != requested.len() {
        return Err(InferenceArtifactError::InvalidProjection(format!(
            "bounded reasoner {label} nodes must be unique"
        )));
    }
    for id in &ids {
        let index = graph.node_index(id).ok_or_else(|| {
            InferenceArtifactError::InvalidProjection(format!("unknown {label} node {id}"))
        })? as usize;
        let actual_type = graph.node_types()[graph.nodes()[index].node_type_id as usize].as_str();
        if !requested_type.is_empty() && actual_type != requested_type {
            return Err(InferenceArtifactError::InvalidProjection(format!(
                "{label} node {id} has type {actual_type}, expected {requested_type}"
            )));
        }
    }
    Ok(ids)
}

fn visit_graph_edges(
    graph: &InferenceGraph,
    mut visit: impl FnMut(
        &str,
        &str,
        &str,
        &phoenix_revision_impact::InferenceEdgeMetadata,
        InferenceEdgeKind,
    ),
) {
    for (target, window) in graph.incoming_offsets().windows(2).enumerate() {
        for edge in window[0] as usize..window[1] as usize {
            let source = graph.source_ids()[edge] as usize;
            let relation = graph.relation_type_ids()[edge] as usize;
            let metadata = &graph.edge_metadata()[edge];
            visit(
                &graph.nodes()[source].node_id,
                &graph.nodes()[target].node_id,
                &graph.relation_types()[relation],
                metadata,
                metadata.kind,
            );
        }
    }
}

fn count(value: usize) -> u32 {
    u32::try_from(value).unwrap_or(u32::MAX)
}

#[cfg(test)]
mod tests {
    use compact_str::CompactString;
    use phoenix_revision_impact::GraphGeneration;

    use super::*;

    #[test]
    fn projection_is_bounded_and_preserves_exact_candidate_ids() {
        let graph = fixture_graph(5);
        let bounded = project_bounded_reasoner(
            &graph,
            &["document:1", "document:2"],
            &["entity:seed"],
            "document",
        )
        .expect("bounded projection");

        assert_eq!(bounded.candidate_ids.as_ref(), ["document:1", "document:2"]);
        assert!(bounded.projection.view.node_ids.len() <= MAX_REASONER_RESIDENT_NODES);
        assert_eq!(bounded.receipt.candidate_count, 2);
        assert!(bounded.receipt.no_topology_writes);
        assert!(bounded.receipt.full_corpus_materialization_rejected);
    }

    #[test]
    fn projection_rejects_candidate_sets_above_the_hard_cap() {
        let graph = fixture_graph(MAX_REASONER_CANDIDATES + 1);
        let ids = (0..=MAX_REASONER_CANDIDATES)
            .map(|index| format!("document:{index}"))
            .collect::<Vec<_>>();
        let refs = ids.iter().map(String::as_str).collect::<Vec<_>>();

        let error = project_bounded_reasoner(&graph, &refs, &["entity:seed"], "document")
            .err()
            .expect("oversized set must fail");

        assert!(error.to_string().contains("1..=64 candidate"));
    }

    #[test]
    fn ranking_shield_rejects_ids_outside_the_exact_candidate_set() {
        let error = assert_candidate_subset(
            ["document:1", "document:leak"],
            &["document:1", "document:2"],
        )
        .expect_err("leaked ranking must fail closed");

        assert!(error.to_string().contains("escaped candidate set"));
    }

    fn fixture_graph(document_count: usize) -> InferenceGraph {
        let mut nodes = vec![InferenceNodeSeed {
            node_id: "entity:seed".into(),
            node_type: "entity".into(),
            embedding_text: "seed entity".into(),
        }];
        let mut memberships = Vec::new();
        for index in 0..document_count {
            let document_id = CompactString::from(format!("document:{index}"));
            nodes.push(InferenceNodeSeed {
                node_id: document_id.clone(),
                node_type: "document".into(),
                embedding_text: CompactString::from(format!("document {index}")),
            });
            memberships.push(InferenceEdgeSeed {
                edge_id: CompactString::from(format!("membership:{index}")),
                source_id: "entity:seed".into(),
                target_id: document_id,
                relation_type: "mentioned_in".into(),
                authority: InferenceAuthority::Asserted,
                evidence_ids: vec!["evidence:1".into()],
                confidence_millis: 900,
            });
        }
        RevisionAnalysisViews::project(
            GraphGeneration(1),
            Vec::new(),
            InferenceProjectionInput {
                accepted_nodes: nodes,
                relations: Vec::new(),
                memberships,
            },
        )
        .expect("fixture graph")
        .inference_graph
    }
}
