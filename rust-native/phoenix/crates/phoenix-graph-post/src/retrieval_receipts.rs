use phoenix_graph_kernel::{KernelExpandedRegion, KernelWalkResult};
use serde::{Deserialize, Serialize};

use crate::api::{
    GraphRankedCausalExplanationAnswer, GraphRankedHistoryAnswer, GraphRankedSlotAnswer,
};
use crate::retrieval::GraphRetrievedRegion;

pub const NATIVE_RETRIEVAL_RECEIPT_VERSION: &str = "phoenix-native-graph-retrieval-v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphNativeRetrievalStrategy {
    SimpleRegionExpansion,
    BoundedWalk,
    BoundedWalkPcst,
    StructuralDiffusionRerank,
    CausalPathFeatureRerank,
}

impl GraphNativeRetrievalStrategy {
    pub fn label(self) -> &'static str {
        match self {
            Self::SimpleRegionExpansion => "simple_region_expansion",
            Self::BoundedWalk => "bounded_walk",
            Self::BoundedWalkPcst => "bounded_walk_pcst",
            Self::StructuralDiffusionRerank => "structural_diffusion_rerank",
            Self::CausalPathFeatureRerank => "causal_path_feature_rerank",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphNativeRegionReceipt {
    pub vertex_count: usize,
    pub asserted_edge_count: usize,
    pub candidate_edge_count: usize,
    pub anchor_count: usize,
    pub seed_count: usize,
    pub included_count: usize,
    pub truncated: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphNativeWalkReceipt {
    pub pcst_compacted: bool,
    pub total_prize_millis: i32,
    pub total_cost_millis: i32,
    pub contradiction_debt_millis: i32,
    pub stale_evidence_millis: i32,
    pub considered_edges: usize,
    pub pruned_by_node_budget: usize,
    pub pruned_by_edge_budget: usize,
    pub pruned_by_family_fanout: usize,
    pub pruned_by_island_budget: usize,
    pub pruned_by_contradiction_debt: usize,
    pub pruned_by_stale_evidence: usize,
    pub projected_csr_memory_bytes: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphNativeStructuralReceipt {
    pub diffusion: String,
    pub candidate_count: usize,
    pub selected_model: Option<String>,
    pub selected_delta_millis: Option<i32>,
    pub selected_proximity_millis: Option<u32>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphNativeCausalPathReceipt {
    pub candidate_count: usize,
    pub selected_depth: Option<usize>,
    pub selected_score_millis: Option<i64>,
    pub selected_path_stability_millis: Option<u32>,
    pub selected_support_strength_millis: Option<u32>,
    pub selected_temporal_fitness_millis: Option<u32>,
    pub selected_evidence_ref_count: Option<usize>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphNativeRetrievalReceipt {
    pub source_version: String,
    pub strategy: GraphNativeRetrievalStrategy,
    pub strategy_label: String,
    pub region: GraphNativeRegionReceipt,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub walk: Option<GraphNativeWalkReceipt>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub structural: Option<GraphNativeStructuralReceipt>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub causal_path: Option<GraphNativeCausalPathReceipt>,
}

impl GraphRetrievedRegion {
    pub(crate) fn from_simple_expansion(
        anchor_vertex_ids: Vec<String>,
        expanded: &KernelExpandedRegion,
    ) -> Self {
        let mut region = Self {
            vertex_count: expanded.snapshot.vertices.len(),
            asserted_edge_count: expanded.snapshot.asserted_edges.len(),
            candidate_edge_count: expanded.snapshot.candidate_edges.len(),
            truncated: expanded.truncated,
            anchor_vertex_ids,
            seed_vertex_ids: expanded.seed_vertex_ids.clone(),
            included_vertex_ids: expanded.included_vertex_ids.clone(),
            native_retrieval_receipt: None,
        };
        region.native_retrieval_receipt = Some(GraphNativeRetrievalReceipt::region_only(
            GraphNativeRetrievalStrategy::SimpleRegionExpansion,
            &region,
        ));
        region
    }

    pub(crate) fn from_bounded_walk(
        anchor_vertex_ids: Vec<String>,
        walk: &KernelWalkResult,
        pcst_compacted: bool,
    ) -> Self {
        let strategy = if pcst_compacted {
            GraphNativeRetrievalStrategy::BoundedWalkPcst
        } else {
            GraphNativeRetrievalStrategy::BoundedWalk
        };
        let mut region = Self {
            vertex_count: walk.snapshot.vertices.len(),
            asserted_edge_count: walk.snapshot.asserted_edges.len(),
            candidate_edge_count: walk.snapshot.candidate_edges.len(),
            truncated: walk.truncated,
            anchor_vertex_ids,
            seed_vertex_ids: walk.seed_vertex_ids.clone(),
            included_vertex_ids: walk.included_vertex_ids.clone(),
            native_retrieval_receipt: None,
        };
        region.native_retrieval_receipt = Some(GraphNativeRetrievalReceipt::from_walk(
            strategy,
            &region,
            walk,
            pcst_compacted,
        ));
        region
    }
}

impl GraphNativeRetrievalReceipt {
    pub fn region_only(
        strategy: GraphNativeRetrievalStrategy,
        region: &GraphRetrievedRegion,
    ) -> Self {
        Self {
            source_version: NATIVE_RETRIEVAL_RECEIPT_VERSION.to_owned(),
            strategy,
            strategy_label: strategy.label().to_owned(),
            region: GraphNativeRegionReceipt::from_region(region),
            walk: None,
            structural: None,
            causal_path: None,
        }
    }

    pub fn from_walk(
        strategy: GraphNativeRetrievalStrategy,
        region: &GraphRetrievedRegion,
        walk: &KernelWalkResult,
        pcst_compacted: bool,
    ) -> Self {
        Self {
            source_version: NATIVE_RETRIEVAL_RECEIPT_VERSION.to_owned(),
            strategy,
            strategy_label: strategy.label().to_owned(),
            region: GraphNativeRegionReceipt::from_region(region),
            walk: Some(GraphNativeWalkReceipt::from_walk(walk, pcst_compacted)),
            structural: None,
            causal_path: None,
        }
    }

    pub fn with_structural(
        mut self,
        diffusion: impl Into<String>,
        answer: &GraphRankedStructuralAnswer<'_>,
    ) -> Self {
        self.strategy = GraphNativeRetrievalStrategy::StructuralDiffusionRerank;
        self.strategy_label = self.strategy.label().to_owned();
        self.structural = Some(answer.structural_receipt(diffusion.into()));
        self
    }

    pub fn with_causal_path_features(
        mut self,
        answer: &GraphRankedCausalExplanationAnswer,
    ) -> Self {
        self.strategy = GraphNativeRetrievalStrategy::CausalPathFeatureRerank;
        self.strategy_label = self.strategy.label().to_owned();
        self.causal_path = Some(GraphNativeCausalPathReceipt::from_answer(answer));
        self
    }
}

impl GraphNativeRegionReceipt {
    fn from_region(region: &GraphRetrievedRegion) -> Self {
        Self {
            vertex_count: region.vertex_count,
            asserted_edge_count: region.asserted_edge_count,
            candidate_edge_count: region.candidate_edge_count,
            anchor_count: region.anchor_vertex_ids.len(),
            seed_count: region.seed_vertex_ids.len(),
            included_count: region.included_vertex_ids.len(),
            truncated: region.truncated,
        }
    }
}

impl GraphNativeWalkReceipt {
    fn from_walk(walk: &KernelWalkResult, pcst_compacted: bool) -> Self {
        Self {
            pcst_compacted,
            total_prize_millis: walk.total_prize_millis,
            total_cost_millis: walk.total_cost_millis,
            contradiction_debt_millis: walk.contradiction_debt_millis,
            stale_evidence_millis: walk.stale_evidence_millis,
            considered_edges: walk.stats.considered_edges,
            pruned_by_node_budget: walk.stats.pruned_by_node_budget,
            pruned_by_edge_budget: walk.stats.pruned_by_edge_budget,
            pruned_by_family_fanout: walk.stats.pruned_by_family_fanout,
            pruned_by_island_budget: walk.stats.pruned_by_island_budget,
            pruned_by_contradiction_debt: walk.stats.pruned_by_contradiction_debt,
            pruned_by_stale_evidence: walk.stats.pruned_by_stale_evidence,
            projected_csr_memory_bytes: walk.stats.projected_csr_memory_bytes,
        }
    }
}

pub enum GraphRankedStructuralAnswer<'a> {
    World(&'a GraphRankedSlotAnswer),
    History(&'a GraphRankedHistoryAnswer),
    Causal(&'a GraphRankedCausalExplanationAnswer),
}

impl GraphRankedStructuralAnswer<'_> {
    fn structural_receipt(&self, diffusion: String) -> GraphNativeStructuralReceipt {
        match self {
            Self::World(answer) => GraphNativeStructuralReceipt {
                diffusion,
                candidate_count: answer.candidates.len(),
                selected_model: answer
                    .selected
                    .as_ref()
                    .and_then(|candidate| candidate.graph_structural_rerank.as_ref())
                    .map(|score| score.model.clone()),
                selected_delta_millis: answer
                    .selected
                    .as_ref()
                    .and_then(|candidate| candidate.graph_structural_rerank.as_ref())
                    .map(|score| score.applied_delta_millis),
                selected_proximity_millis: answer
                    .selected
                    .as_ref()
                    .and_then(|candidate| candidate.graph_structural_rerank.as_ref())
                    .map(|score| score.proximity_score_millis),
            },
            Self::History(answer) => GraphNativeStructuralReceipt {
                diffusion,
                candidate_count: answer.candidates.len(),
                selected_model: answer
                    .selected
                    .as_ref()
                    .and_then(|candidate| candidate.graph_structural_rerank.as_ref())
                    .map(|score| score.model.clone()),
                selected_delta_millis: answer
                    .selected
                    .as_ref()
                    .and_then(|candidate| candidate.graph_structural_rerank.as_ref())
                    .map(|score| score.applied_delta_millis),
                selected_proximity_millis: answer
                    .selected
                    .as_ref()
                    .and_then(|candidate| candidate.graph_structural_rerank.as_ref())
                    .map(|score| score.proximity_score_millis),
            },
            Self::Causal(answer) => GraphNativeStructuralReceipt {
                diffusion,
                candidate_count: answer.candidates.len(),
                selected_model: answer
                    .selected
                    .as_ref()
                    .and_then(|candidate| candidate.graph_structural_rerank.as_ref())
                    .map(|score| score.model.clone()),
                selected_delta_millis: answer
                    .selected
                    .as_ref()
                    .and_then(|candidate| candidate.graph_structural_rerank.as_ref())
                    .map(|score| score.applied_delta_millis),
                selected_proximity_millis: answer
                    .selected
                    .as_ref()
                    .and_then(|candidate| candidate.graph_structural_rerank.as_ref())
                    .map(|score| score.proximity_score_millis),
            },
        }
    }
}

impl GraphNativeCausalPathReceipt {
    fn from_answer(answer: &GraphRankedCausalExplanationAnswer) -> Self {
        let selected = answer.selected.as_ref();
        Self {
            candidate_count: answer.candidates.len(),
            selected_depth: selected.map(|path| path.hops.len()),
            selected_score_millis: selected.map(|path| (path.answer_score * 1000.0).round() as i64),
            selected_path_stability_millis: selected.map(|path| score_millis(path.path_stability)),
            selected_support_strength_millis: selected
                .map(|path| score_millis(path.support_strength)),
            selected_temporal_fitness_millis: selected
                .map(|path| score_millis(path.temporal_fitness)),
            selected_evidence_ref_count: selected.map(|path| path.evidence_refs.len()),
        }
    }
}

fn score_millis(value: f64) -> u32 {
    (value.clamp(0.0, 1.0) * 1000.0).round() as u32
}
