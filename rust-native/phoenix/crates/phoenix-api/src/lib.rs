//! Canonical discovery and orchestration façade for Phoenix post-ingest
//! pipeline stages.

pub mod depth_audit;
mod pipeline_scheduler;

use serde::{Deserialize, Serialize};

use phoenix_alex::{api as alex_api, AlexError, Lexicon};
use phoenix_causal_post::api as causal_api;
use phoenix_er_post::api as er_api;
use phoenix_event_identity_post::api as event_identity_api;
use phoenix_graph_kernel::{project_graph_proposal_outcomes, GraphProposalOutcome};
use phoenix_graph_post::api as graph_api;
use phoenix_graph_rebuild::GraphDocumentCompilerSummary;
use phoenix_graph_research::{
    certify_evaluation_protocol, derive_train_topology_features, freeze_graph_research_snapshot,
    run_baseline_ladder_for_protocol, run_structural_ranking_baselines, tensorize_frozen_graph,
    BaselineLadderReport, EvaluationPolicy, FrozenGraphResearchBundle, FrozenGraphResearchError,
    FrozenGraphResearchInput, FrozenGraphResearchPaths, FrozenTensorBundle, FrozenTensorPaths,
    RankingEvaluationError, RankingEvaluationReport, ResearchEvaluationError,
    ResearchEvaluationProtocol, TemporalSplitPolicy, TensorizationPolicy,
    TrainTopologyFeaturePolicy, TrainTopologyFeatureSnapshot,
};
use phoenix_memory_post::api as memory_api;
use phoenix_rel_post::api as rel_api;
use phoenix_state_schema_post::api as state_schema_api;
use phoenix_store_native_core::{
    PhoenixArchiveStoreV2, PhoenixCausalPatchStore, PhoenixErPatchStore,
    PhoenixEventIdentityPatchStore, PhoenixGraphKernelStoreV2, PhoenixGraphLearningStore,
    PhoenixGraphPatchStore, PhoenixLexicalQueryStore, PhoenixMemoryPatchStore,
    PhoenixRelationPatchStore, PhoenixScopeRuntimeStore, PhoenixSemanticGraphPatchStore,
    PhoenixSemanticIndexStore, PhoenixStateSchemaPatchStore, PhoenixTemporalPatchStore, StoreError,
};
use phoenix_temporal_post::api as temporal_api;
use phoenix_types::{LexiconEntry, ScopeKey, SessionId};
pub use pipeline_scheduler::{
    PipelineGenerationContext, PipelineRunMetrics, PipelineRunRequest, PipelineRunShape,
    PipelineStage, PipelineStageStatus, ScopeGenerationKey, StageProductEnvelope,
};
use std::path::Path;

#[derive(Debug, thiserror::Error)]
pub enum PipelineApiError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Alex(#[from] AlexError),
    #[error(transparent)]
    Relation(#[from] phoenix_rel_post::GlirelWorkerError),
}

#[derive(Debug, thiserror::Error)]
pub enum GraphResearchExportError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Research(#[from] FrozenGraphResearchError),
    #[error(transparent)]
    Evaluation(#[from] ResearchEvaluationError),
    #[error(transparent)]
    Ranking(#[from] RankingEvaluationError),
    #[error("cannot freeze graph research data without a kernel checkpoint")]
    MissingCheckpoint,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GraphResearchTensorExportPaths {
    pub research: FrozenGraphResearchPaths,
    pub tensors: FrozenTensorPaths,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphResearchEvaluation {
    pub protocol: ResearchEvaluationProtocol,
    pub baselines: BaselineLadderReport,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PostIngestRunReport {
    pub relation_scope_count: usize,
    pub relation_case_count: usize,
    pub persisted_relation_edge_count: usize,
    pub state_schema_scope_count: usize,
    pub state_schema_slot_family_count: usize,
    pub state_schema_slot_definition_count: usize,
    pub state_schema_active_definition_count: usize,
    pub state_schema_candidate_count: usize,
    pub state_schema_write_proposal_count: usize,
    pub memory_scope_count: usize,
    pub memory_state_count: usize,
    pub memory_card_count: usize,
    #[serde(default)]
    pub scheduler: PipelineRunMetrics,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StateSchemaRunReport {
    pub state_schema_scope_count: usize,
    pub slot_family_count: usize,
    pub slot_definition_count: usize,
    pub active_definition_count: usize,
    pub candidate_count: usize,
    pub write_proposal_count: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LateSidecarRunReport {
    pub state_schema: StateSchemaRunReport,
    pub memory_scope_count: usize,
    pub memory_state_count: usize,
    pub memory_event_count: usize,
    pub memory_claim_count: usize,
    pub memory_gap_count: usize,
    pub memory_conflict_count: usize,
    pub memory_card_count: usize,
    #[serde(default)]
    pub scheduler: PipelineRunMetrics,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EventIdentityRunReport {
    pub event_identity_scope_count: usize,
    pub mention_packet_count: usize,
    pub hypothesis_count: usize,
    pub canonical_event_count: usize,
    pub canonical_card_count: usize,
    #[serde(default)]
    pub scheduler: PipelineRunMetrics,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CausalRunReport {
    pub causal_scope_count: usize,
    pub causal_review_case_count: usize,
    pub causal_edge_count: usize,
    pub causal_chain_count: usize,
    pub causal_card_count: usize,
    #[serde(default)]
    pub scheduler: PipelineRunMetrics,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalRunReport {
    pub temporal_scope_count: usize,
    pub temporal_review_case_count: usize,
    pub temporal_interval_count: usize,
    pub temporal_segment_count: usize,
    pub temporal_gap_count: usize,
    pub temporal_card_count: usize,
    #[serde(default)]
    pub scheduler: PipelineRunMetrics,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphRunReport {
    pub graph_scope_count: usize,
    pub graph_projection_vertex_count: usize,
    pub graph_projection_edge_count: usize,
    pub graph_claim_node_count: usize,
    pub graph_event_node_count: usize,
    pub graph_state_node_count: usize,
    #[serde(default)]
    pub scheduler: PipelineRunMetrics,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ContinuityRunReport {
    pub event_identity: EventIdentityRunReport,
    pub temporal: TemporalRunReport,
    pub causal: CausalRunReport,
    pub state_schema: StateSchemaRunReport,
    pub post_ingest: PostIngestRunReport,
    #[serde(default)]
    pub scheduler: PipelineRunMetrics,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SidecarContinuityRunReport {
    pub event_identity: EventIdentityRunReport,
    pub temporal: TemporalRunReport,
    pub causal: CausalRunReport,
    pub late_sidecars: LateSidecarRunReport,
    pub graph: GraphRunReport,
    #[serde(default)]
    pub scheduler: PipelineRunMetrics,
}

pub struct PhoenixPipelineApi<S> {
    store: S,
}

impl<S> PhoenixPipelineApi<S> {
    pub fn new(store: S) -> Self {
        Self { store }
    }

    pub fn into_store(self) -> S {
        self.store
    }

    pub fn store(&self) -> &S {
        &self.store
    }

    pub fn chunker(&self) -> ChunkerStageApi {
        ChunkerStageApi
    }

    pub fn alex(&self) -> AlexStageApi {
        AlexStageApi
    }

    pub fn er(&self) -> ErStageApi<'_, S> {
        ErStageApi { store: &self.store }
    }

    pub fn event_identity(&self) -> EventIdentityStageApi<'_, S> {
        EventIdentityStageApi { store: &self.store }
    }

    pub fn causal(&self) -> CausalStageApi<'_, S> {
        CausalStageApi { store: &self.store }
    }

    pub fn state_schema(&self) -> StateSchemaStageApi<'_, S> {
        StateSchemaStageApi { store: &self.store }
    }

    pub fn temporal(&self) -> TemporalStageApi<'_, S> {
        TemporalStageApi { store: &self.store }
    }

    pub fn graph(&self) -> GraphStageApi<'_, S> {
        GraphStageApi { store: &self.store }
    }

    pub fn rel(&self) -> RelStageApi<'_, S> {
        RelStageApi { store: &self.store }
    }

    pub fn memory(&self) -> MemoryStageApi<'_, S> {
        MemoryStageApi { store: &self.store }
    }
}

impl<S> PhoenixPipelineApi<S>
where
    S: PhoenixArchiveStoreV2
        + PhoenixErPatchStore
        + PhoenixEventIdentityPatchStore
        + PhoenixRelationPatchStore
        + PhoenixMemoryPatchStore
        + PhoenixScopeRuntimeStore
        + PhoenixCausalPatchStore
        + PhoenixStateSchemaPatchStore
        + PhoenixTemporalPatchStore,
{
    pub fn run_post_ingest_scope(
        &self,
        session_id: Option<&SessionId>,
        glirel_model: &phoenix_rel_post::GlirelModel,
        relation_specs: &[phoenix_rel_post::GlirelRelationTypeSpec],
        relation_created_at: i64,
        memory_created_at: i64,
    ) -> Result<PostIngestRunReport, PipelineApiError> {
        pipeline_scheduler::run_post_ingest_pipeline(
            &self.store,
            PipelineRunRequest::post_ingest(session_id),
            Some(glirel_model),
            relation_specs,
            relation_created_at,
            memory_created_at,
        )
    }

    pub fn run_post_ingest_scope_heuristic(
        &self,
        session_id: Option<&SessionId>,
        relation_specs: &[phoenix_rel_post::GlirelRelationTypeSpec],
        relation_created_at: i64,
        memory_created_at: i64,
    ) -> Result<PostIngestRunReport, PipelineApiError> {
        pipeline_scheduler::run_post_ingest_pipeline(
            &self.store,
            PipelineRunRequest::post_ingest(session_id),
            None,
            relation_specs,
            relation_created_at,
            memory_created_at,
        )
    }

    pub fn run_late_sidecar_scope(
        &self,
        session_id: Option<&SessionId>,
        created_at: i64,
    ) -> Result<LateSidecarRunReport, PipelineApiError> {
        pipeline_scheduler::run_late_sidecar_pipeline(
            &self.store,
            PipelineRunRequest::late_sidecars(session_id),
            created_at,
        )
    }

    pub fn run_causal_scope(
        &self,
        session_id: Option<&SessionId>,
        created_at: i64,
    ) -> Result<CausalRunReport, PipelineApiError> {
        pipeline_scheduler::run_causal_pipeline(
            &self.store,
            PipelineRunRequest::causal(session_id),
            created_at,
        )
    }

    pub fn run_event_identity_scope(
        &self,
        session_id: Option<&SessionId>,
        created_at: i64,
    ) -> Result<EventIdentityRunReport, PipelineApiError> {
        pipeline_scheduler::run_event_identity_pipeline(
            &self.store,
            PipelineRunRequest::event_identity(session_id),
            created_at,
        )
    }

    pub fn run_temporal_scope(
        &self,
        session_id: Option<&SessionId>,
        created_at: i64,
    ) -> Result<TemporalRunReport, PipelineApiError> {
        pipeline_scheduler::run_temporal_pipeline(
            &self.store,
            PipelineRunRequest::temporal(session_id),
            created_at,
        )
    }

    pub fn run_graph_scope(
        &self,
        session_id: Option<&SessionId>,
        created_at: i64,
    ) -> Result<GraphRunReport, PipelineApiError>
    where
        S: PhoenixGraphPatchStore
            + PhoenixGraphKernelStoreV2
            + PhoenixGraphLearningStore
            + PhoenixSemanticGraphPatchStore,
    {
        pipeline_scheduler::run_graph_pipeline(
            &self.store,
            PipelineRunRequest::graph(session_id),
            created_at,
        )
    }

    pub fn run_sidecar_continuity_scope(
        &self,
        session_id: Option<&SessionId>,
        created_at: i64,
    ) -> Result<SidecarContinuityRunReport, PipelineApiError>
    where
        S: PhoenixGraphPatchStore
            + PhoenixGraphKernelStoreV2
            + PhoenixGraphLearningStore
            + PhoenixSemanticGraphPatchStore,
    {
        pipeline_scheduler::run_sidecar_continuity_pipeline(
            &self.store,
            PipelineRunRequest::sidecar_continuity(session_id),
            created_at,
        )
    }

    pub fn run_state_schema_scope(
        &self,
        session_id: Option<&SessionId>,
        created_at: i64,
    ) -> Result<StateSchemaRunReport, PipelineApiError> {
        let mut batches = state_schema_api::derive_batches(&self.store, session_id)?;
        let mut slot_family_count = 0usize;
        let mut slot_definition_count = 0usize;
        let mut active_definition_count = 0usize;
        let mut candidate_count = 0usize;
        let mut write_proposal_count = 0usize;
        for batch in &mut batches {
            state_schema_api::run_batch(batch, created_at);
            let sidecar = state_schema_api::persist_patch_sidecar(&self.store, batch, created_at)?;
            slot_family_count += sidecar.slot_families.len();
            slot_definition_count += sidecar.slot_definitions.len();
            active_definition_count += sidecar
                .slot_definitions
                .iter()
                .filter(|definition| {
                    matches!(
                        definition.lifecycle,
                        phoenix_semantic_v2::StateSlotLifecycle::Active
                            | phoenix_semantic_v2::StateSlotLifecycle::Stable
                    )
                })
                .count();
            candidate_count += sidecar.slot_candidates.len();
            write_proposal_count += sidecar.write_proposals.len();
        }
        Ok(StateSchemaRunReport {
            state_schema_scope_count: batches.len(),
            slot_family_count,
            slot_definition_count,
            active_definition_count,
            candidate_count,
            write_proposal_count,
        })
    }

    pub fn run_continuity_scope(
        &self,
        session_id: Option<&SessionId>,
        event_identity_created_at: i64,
        temporal_created_at: i64,
        causal_created_at: i64,
        glirel_model: &phoenix_rel_post::GlirelModel,
        relation_specs: &[phoenix_rel_post::GlirelRelationTypeSpec],
        relation_created_at: i64,
        memory_created_at: i64,
    ) -> Result<ContinuityRunReport, PipelineApiError> {
        pipeline_scheduler::run_continuity_pipeline(
            &self.store,
            PipelineRunRequest::continuity(session_id),
            event_identity_created_at,
            temporal_created_at,
            causal_created_at,
            Some(glirel_model),
            relation_specs,
            relation_created_at,
            memory_created_at,
        )
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ChunkerStageApi;

impl ChunkerStageApi {
    pub fn sentence_ranges(&self, text: &str) -> Vec<(usize, usize)> {
        phoenix_chunker_native::api::sentence_ranges(text)
    }

    pub fn build_chunks(
        &self,
        text: &str,
        config: &phoenix_chunker_native::ChunkerConfig,
    ) -> Vec<phoenix_chunker_native::Chunk> {
        phoenix_chunker_native::api::chunk_ranges(text, config)
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct AlexStageApi;

impl AlexStageApi {
    pub fn build_lexicon(&self, entries: &[LexiconEntry]) -> Result<Lexicon, AlexError> {
        alex_api::build_lexicon(entries)
    }

    pub fn build_snapshot(
        &self,
        entries: &[LexiconEntry],
    ) -> Result<phoenix_types::LexiconSnapshot, AlexError> {
        alex_api::build_snapshot(entries)
    }

    pub fn scan_text(
        &self,
        lexicon: &Lexicon,
        text: &str,
        scope: &ScopeKey,
    ) -> Vec<phoenix_types::KnownMatch> {
        alex_api::scan_text(lexicon, text, scope)
    }
}

pub struct ErStageApi<'a, S> {
    store: &'a S,
}

impl<'a, S> ErStageApi<'a, S>
where
    S: PhoenixArchiveStoreV2,
{
    pub fn derive_batches(
        &self,
        session_id: Option<&SessionId>,
    ) -> Result<Vec<phoenix_er_post::ErScopeReviewBatch>, StoreError> {
        er_api::derive_batches(self.store, session_id)
    }
}

impl<'a, S> ErStageApi<'a, S>
where
    S: PhoenixArchiveStoreV2 + PhoenixErPatchStore,
{
    pub fn derive_batches_with_replay(
        &self,
        session_id: Option<&SessionId>,
    ) -> Result<Vec<phoenix_er_post::ErScopeReviewBatch>, StoreError> {
        er_api::derive_batches_with_replay(self.store, session_id)
    }
}

pub struct EventIdentityStageApi<'a, S> {
    store: &'a S,
}

impl<'a, S> EventIdentityStageApi<'a, S>
where
    S: PhoenixArchiveStoreV2 + PhoenixEventIdentityPatchStore + PhoenixScopeRuntimeStore,
{
    pub fn derive_batches(
        &self,
        session_id: Option<&SessionId>,
    ) -> Result<Vec<phoenix_event_identity_post::EventIdentityScopeReviewBatch>, StoreError> {
        event_identity_api::derive_batches(self.store, session_id)
    }

    pub fn run_scope(
        &self,
        batch: &mut phoenix_event_identity_post::EventIdentityScopeReviewBatch,
        created_at: i64,
    ) {
        event_identity_api::run_batch(batch, created_at);
    }
}

pub struct CausalStageApi<'a, S> {
    store: &'a S,
}

impl<'a, S> CausalStageApi<'a, S>
where
    S: PhoenixArchiveStoreV2 + PhoenixCausalPatchStore + PhoenixScopeRuntimeStore,
{
    pub fn derive_batches(
        &self,
        session_id: Option<&SessionId>,
    ) -> Result<Vec<phoenix_causal_post::CausalScopeReviewBatch>, StoreError> {
        causal_api::derive_batches(self.store, session_id)
    }

    pub fn run_scope(
        &self,
        batch: &mut phoenix_causal_post::CausalScopeReviewBatch,
        created_at: i64,
    ) {
        causal_api::run_batch(batch, created_at);
    }
}

pub struct StateSchemaStageApi<'a, S> {
    store: &'a S,
}

impl<'a, S> StateSchemaStageApi<'a, S>
where
    S: PhoenixArchiveStoreV2 + PhoenixRelationPatchStore + PhoenixStateSchemaPatchStore,
{
    pub fn derive_batches(
        &self,
        session_id: Option<&SessionId>,
    ) -> Result<Vec<phoenix_state_schema_post::StateSchemaScopeReviewBatch>, StoreError> {
        state_schema_api::derive_batches(self.store, session_id)
    }

    pub fn run_scope(
        &self,
        batch: &mut phoenix_state_schema_post::StateSchemaScopeReviewBatch,
        created_at: i64,
    ) {
        state_schema_api::run_batch(batch, created_at);
    }
}

pub struct TemporalStageApi<'a, S> {
    store: &'a S,
}

impl<'a, S> TemporalStageApi<'a, S>
where
    S: PhoenixArchiveStoreV2 + PhoenixTemporalPatchStore + PhoenixScopeRuntimeStore,
{
    pub fn derive_batches(
        &self,
        session_id: Option<&SessionId>,
    ) -> Result<Vec<phoenix_temporal_post::TemporalScopeReviewBatch>, StoreError> {
        temporal_api::derive_batches(self.store, session_id)
    }

    pub fn run_scope(
        &self,
        batch: &mut phoenix_temporal_post::TemporalScopeReviewBatch,
        created_at: i64,
    ) {
        temporal_api::run_batch(batch, created_at);
    }
}

pub struct GraphStageApi<'a, S> {
    store: &'a S,
}

impl<'a, S> GraphStageApi<'a, S>
where
    S: PhoenixArchiveStoreV2
        + PhoenixCausalPatchStore
        + PhoenixEventIdentityPatchStore
        + PhoenixGraphKernelStoreV2
        + PhoenixGraphPatchStore
        + PhoenixLexicalQueryStore
        + PhoenixMemoryPatchStore
        + PhoenixSemanticGraphPatchStore
        + PhoenixSemanticIndexStore
        + PhoenixScopeRuntimeStore
        + PhoenixTemporalPatchStore,
{
    pub fn derive_batches(
        &self,
        session_id: Option<&SessionId>,
    ) -> Result<Vec<phoenix_graph_post::GraphScopeReviewBatch>, StoreError> {
        graph_api::derive_batches(self.store, session_id)
    }

    pub fn proposal_outcomes(&self) -> Result<Vec<GraphProposalOutcome>, StoreError>
    where
        S: PhoenixGraphLearningStore,
    {
        let receipts = self.store.load_graph_proposal_receipts()?;
        let commits = self.store.load_graph_truth_commits()?;
        project_graph_proposal_outcomes(&receipts, &commits)
            .map_err(|error| StoreError::Schema(error.to_string()))
    }

    pub fn freeze_research_snapshot(
        &self,
        root: impl AsRef<Path>,
        frozen_at_ms: i64,
        split_policy: TemporalSplitPolicy,
        document_compiler: Option<&GraphDocumentCompilerSummary>,
        document_compiler_observed_at_ms: Option<i64>,
    ) -> Result<FrozenGraphResearchPaths, GraphResearchExportError>
    where
        S: PhoenixGraphLearningStore,
    {
        let checkpoint = self
            .store
            .load_kernel_checkpoint()?
            .ok_or(GraphResearchExportError::MissingCheckpoint)?;
        let commits = self.store.load_graph_truth_commits()?;
        let proposal_receipts = self.store.load_graph_proposal_receipts()?;
        let snapshot = freeze_graph_research_snapshot(FrozenGraphResearchInput {
            checkpoint: &checkpoint,
            commits: &commits,
            proposal_receipts: &proposal_receipts,
            document_compiler,
            document_compiler_observed_at_ms,
            frozen_at_ms,
            split_policy,
        })?;
        FrozenGraphResearchBundle::write(&snapshot, root).map_err(Into::into)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn freeze_research_tensors(
        &self,
        research_root: impl AsRef<Path>,
        tensor_root: impl AsRef<Path>,
        frozen_at_ms: i64,
        split_policy: TemporalSplitPolicy,
        tensor_policy: TensorizationPolicy,
        document_compiler: Option<&GraphDocumentCompilerSummary>,
        document_compiler_observed_at_ms: Option<i64>,
    ) -> Result<GraphResearchTensorExportPaths, GraphResearchExportError>
    where
        S: PhoenixGraphLearningStore,
    {
        let checkpoint = self
            .store
            .load_kernel_checkpoint()?
            .ok_or(GraphResearchExportError::MissingCheckpoint)?;
        let commits = self.store.load_graph_truth_commits()?;
        let proposal_receipts = self.store.load_graph_proposal_receipts()?;
        let research = freeze_graph_research_snapshot(FrozenGraphResearchInput {
            checkpoint: &checkpoint,
            commits: &commits,
            proposal_receipts: &proposal_receipts,
            document_compiler,
            document_compiler_observed_at_ms,
            frozen_at_ms,
            split_policy,
        })?;
        let tensors = tensorize_frozen_graph(&research, tensor_policy)?;
        let research_paths = FrozenGraphResearchBundle::write(&research, research_root)?;
        let tensor_paths = FrozenTensorBundle::write(&tensors, tensor_root)?;
        Ok(GraphResearchTensorExportPaths {
            research: research_paths,
            tensors: tensor_paths,
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn evaluate_research_baselines(
        &self,
        frozen_at_ms: i64,
        split_policy: TemporalSplitPolicy,
        tensor_policy: TensorizationPolicy,
        evaluation_policy: EvaluationPolicy,
        document_compiler: Option<&GraphDocumentCompilerSummary>,
        document_compiler_observed_at_ms: Option<i64>,
    ) -> Result<GraphResearchEvaluation, GraphResearchExportError>
    where
        S: PhoenixGraphLearningStore,
    {
        let checkpoint = self
            .store
            .load_kernel_checkpoint()?
            .ok_or(GraphResearchExportError::MissingCheckpoint)?;
        let commits = self.store.load_graph_truth_commits()?;
        let proposal_receipts = self.store.load_graph_proposal_receipts()?;
        let research = freeze_graph_research_snapshot(FrozenGraphResearchInput {
            checkpoint: &checkpoint,
            commits: &commits,
            proposal_receipts: &proposal_receipts,
            document_compiler,
            document_compiler_observed_at_ms,
            frozen_at_ms,
            split_policy,
        })?;
        let tensors = tensorize_frozen_graph(&research, tensor_policy)?;
        let protocol = certify_evaluation_protocol(&research, &tensors, evaluation_policy.clone())?;
        let baselines = run_baseline_ladder_for_protocol(&tensors, &protocol)?;
        Ok(GraphResearchEvaluation {
            protocol,
            baselines,
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn derive_research_topology_features(
        &self,
        frozen_at_ms: i64,
        split_policy: TemporalSplitPolicy,
        tensor_policy: TensorizationPolicy,
        evaluation_policy: EvaluationPolicy,
        feature_policy: TrainTopologyFeaturePolicy,
        document_compiler: Option<&GraphDocumentCompilerSummary>,
        document_compiler_observed_at_ms: Option<i64>,
    ) -> Result<TrainTopologyFeatureSnapshot, GraphResearchExportError>
    where
        S: PhoenixGraphLearningStore,
    {
        let checkpoint = self
            .store
            .load_kernel_checkpoint()?
            .ok_or(GraphResearchExportError::MissingCheckpoint)?;
        let commits = self.store.load_graph_truth_commits()?;
        let proposal_receipts = self.store.load_graph_proposal_receipts()?;
        let research = freeze_graph_research_snapshot(FrozenGraphResearchInput {
            checkpoint: &checkpoint,
            commits: &commits,
            proposal_receipts: &proposal_receipts,
            document_compiler,
            document_compiler_observed_at_ms,
            frozen_at_ms,
            split_policy,
        })?;
        let tensors = tensorize_frozen_graph(&research, tensor_policy)?;
        let protocol = certify_evaluation_protocol(&research, &tensors, evaluation_policy)?;
        derive_train_topology_features(&research, &tensors, &protocol, feature_policy)
            .map_err(Into::into)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn evaluate_structural_rankings(
        &self,
        frozen_at_ms: i64,
        split_policy: TemporalSplitPolicy,
        tensor_policy: TensorizationPolicy,
        evaluation_policy: EvaluationPolicy,
        feature_policy: TrainTopologyFeaturePolicy,
        document_compiler: Option<&GraphDocumentCompilerSummary>,
        document_compiler_observed_at_ms: Option<i64>,
    ) -> Result<RankingEvaluationReport, GraphResearchExportError>
    where
        S: PhoenixGraphLearningStore,
    {
        let features = self.derive_research_topology_features(
            frozen_at_ms,
            split_policy,
            tensor_policy,
            evaluation_policy,
            feature_policy,
            document_compiler,
            document_compiler_observed_at_ms,
        )?;
        run_structural_ranking_baselines(&features).map_err(Into::into)
    }

    pub fn current_slot(
        &self,
        scope: &ScopeKey,
        entity_id: &str,
        slot_key: &str,
        recorded_at: Option<i64>,
    ) -> Result<Option<graph_api::GraphRankedSlotAnswer>, graph_api::GraphQueryError> {
        graph_api::current_slot(self.store, scope, entity_id, slot_key, recorded_at)
    }

    pub fn open_query_session(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<graph_api::ScopeQuerySession>, graph_api::GraphQueryError> {
        graph_api::open_scope_query_session(self.store, scope)
    }

    pub fn slot_at(
        &self,
        scope: &ScopeKey,
        request: &graph_api::GraphWorldStateQueryRequest,
    ) -> Result<Option<graph_api::GraphRankedSlotAnswer>, graph_api::GraphQueryError> {
        graph_api::slot_at(self.store, scope, request)
    }

    pub fn slot_at_with_session(
        &self,
        session: &graph_api::ScopeQuerySession,
        request: &graph_api::GraphWorldStateQueryRequest,
    ) -> graph_api::GraphRankedSlotAnswer {
        graph_api::slot_at_with_session(session, request)
    }

    pub fn what_is_unresolved(
        &self,
        scope: &ScopeKey,
        request: &phoenix_graph_kernel::KernelUnresolvedQueryRequest,
    ) -> Result<Option<Vec<phoenix_graph_kernel::KernelStateIssue>>, graph_api::GraphQueryError>
    {
        graph_api::what_is_unresolved(self.store, scope, request)
    }

    pub fn what_is_unresolved_with_session(
        &self,
        session: &graph_api::ScopeQuerySession,
        request: &phoenix_graph_kernel::KernelUnresolvedQueryRequest,
    ) -> Vec<phoenix_graph_kernel::KernelStateIssue> {
        graph_api::what_is_unresolved_with_session(session, request)
    }

    pub fn what_changed(
        &self,
        scope: &ScopeKey,
        request: &phoenix_graph_kernel::KernelWhatChangedRequest,
    ) -> Result<Option<Vec<phoenix_graph_kernel::KernelStateChange>>, graph_api::GraphQueryError>
    {
        graph_api::what_changed(self.store, scope, request)
    }

    pub fn what_changed_with_session(
        &self,
        session: &graph_api::ScopeQuerySession,
        request: &phoenix_graph_kernel::KernelWhatChangedRequest,
    ) -> Vec<phoenix_graph_kernel::KernelStateChange> {
        graph_api::what_changed_with_session(session, request)
    }

    pub fn history(
        &self,
        scope: &ScopeKey,
        request: &graph_api::GraphHistoryQueryRequest,
    ) -> Result<Option<graph_api::GraphRankedHistoryAnswer>, graph_api::GraphQueryError> {
        graph_api::history(self.store, scope, request)
    }

    pub fn history_with_session(
        &self,
        session: &graph_api::ScopeQuerySession,
        request: &graph_api::GraphHistoryQueryRequest,
    ) -> graph_api::GraphRankedHistoryAnswer {
        graph_api::history_with_session(session, request)
    }

    pub fn causal_explanation(
        &self,
        scope: &ScopeKey,
        request: &graph_api::GraphCausalExplanationQueryRequest,
    ) -> Result<Option<graph_api::GraphRankedCausalExplanationAnswer>, graph_api::GraphQueryError>
    {
        graph_api::causal_explanation(self.store, scope, request)
    }

    pub fn causal_explanation_with_session(
        &self,
        session: &graph_api::ScopeQuerySession,
        request: &graph_api::GraphCausalExplanationQueryRequest,
    ) -> graph_api::GraphRankedCausalExplanationAnswer {
        graph_api::causal_explanation_with_session(session, request)
    }

    pub fn ranked_query(
        &self,
        scope: &ScopeKey,
        request: &graph_api::GraphRankedQueryRequest,
    ) -> Result<Option<graph_api::GraphRankedQueryAnswer>, graph_api::GraphQueryError> {
        graph_api::ranked_query(self.store, scope, request)
    }

    pub fn ranked_query_with_session(
        &self,
        session: &graph_api::ScopeQuerySession,
        request: &graph_api::GraphRankedQueryRequest,
    ) -> graph_api::GraphRankedQueryAnswer {
        graph_api::ranked_query_with_session(session, request)
    }

    pub fn retrieved_world_state(
        &self,
        scope: &ScopeKey,
        request: &graph_api::GraphRetrievedWorldStateQueryRequest,
    ) -> Result<Option<graph_api::GraphRetrievedWorldStateAnswer>, graph_api::GraphQueryError> {
        graph_api::retrieved_world_state(self.store, scope, request)
    }

    pub fn retrieved_world_state_with_session(
        &self,
        session: &graph_api::ScopeQuerySession,
        request: &graph_api::GraphRetrievedWorldStateQueryRequest,
    ) -> Result<Option<graph_api::GraphRetrievedWorldStateAnswer>, graph_api::GraphQueryError> {
        graph_api::retrieved_world_state_with_session(self.store, session, request)
    }

    pub fn retrieved_history(
        &self,
        scope: &ScopeKey,
        request: &graph_api::GraphRetrievedHistoryQueryRequest,
    ) -> Result<Option<graph_api::GraphRetrievedHistoryAnswer>, graph_api::GraphQueryError> {
        graph_api::retrieved_history(self.store, scope, request)
    }

    pub fn retrieved_history_with_session(
        &self,
        session: &graph_api::ScopeQuerySession,
        request: &graph_api::GraphRetrievedHistoryQueryRequest,
    ) -> Result<Option<graph_api::GraphRetrievedHistoryAnswer>, graph_api::GraphQueryError> {
        graph_api::retrieved_history_with_session(self.store, session, request)
    }

    pub fn retrieved_causal_explanation(
        &self,
        scope: &ScopeKey,
        request: &graph_api::GraphRetrievedCausalExplanationQueryRequest,
    ) -> Result<Option<graph_api::GraphRetrievedCausalExplanationAnswer>, graph_api::GraphQueryError>
    {
        graph_api::retrieved_causal_explanation(self.store, scope, request)
    }

    pub fn retrieved_causal_explanation_with_session(
        &self,
        session: &graph_api::ScopeQuerySession,
        request: &graph_api::GraphRetrievedCausalExplanationQueryRequest,
    ) -> Result<Option<graph_api::GraphRetrievedCausalExplanationAnswer>, graph_api::GraphQueryError>
    {
        graph_api::retrieved_causal_explanation_with_session(self.store, session, request)
    }

    pub fn retrieved_query(
        &self,
        scope: &ScopeKey,
        request: &graph_api::GraphRetrievedQueryRequest,
    ) -> Result<Option<graph_api::GraphRetrievedQueryAnswer>, graph_api::GraphQueryError> {
        graph_api::retrieved_query(self.store, scope, request)
    }
}

pub struct RelStageApi<'a, S> {
    store: &'a S,
}

impl<'a, S> RelStageApi<'a, S>
where
    S: PhoenixArchiveStoreV2 + PhoenixErPatchStore + PhoenixRelationPatchStore,
{
    pub fn derive_batches(
        &self,
        session_id: Option<&SessionId>,
    ) -> Result<Vec<phoenix_rel_post::RelationScopeReviewBatch>, StoreError> {
        rel_api::derive_batches(self.store, session_id)
    }
}

pub struct MemoryStageApi<'a, S> {
    store: &'a S,
}

impl<'a, S> MemoryStageApi<'a, S>
where
    S: PhoenixArchiveStoreV2
        + PhoenixErPatchStore
        + PhoenixRelationPatchStore
        + PhoenixMemoryPatchStore
        + PhoenixEventIdentityPatchStore
        + PhoenixStateSchemaPatchStore,
{
    pub fn derive_batches(
        &self,
        session_id: Option<&SessionId>,
    ) -> Result<Vec<phoenix_memory_post::MemoryScopeReviewBatch>, StoreError> {
        memory_api::derive_batches(self.store, session_id)
    }
}

#[cfg(test)]
mod tests {
    use super::PhoenixPipelineApi;
    use phoenix_types::{EntityId, LexiconEntry, ScopeKey};

    #[test]
    fn chunker_and_alex_stage_api_smoke() {
        let api = PhoenixPipelineApi::new(());
        let chunker = api.chunker();
        let alex = api.alex();
        let _causal = api.causal();
        let _temporal = api.temporal();
        let text = "Alice works for Dynamis. Dynamis is in New Rome.";
        let sentences = chunker.sentence_ranges(text);
        assert_eq!(sentences.len(), 2);

        let entries = vec![
            LexiconEntry {
                entity_id: EntityId("e1".to_owned()),
                label: "Alice".to_owned(),
                aliases: Vec::new(),
                kind: Some(phoenix_types::EntityKind::Character),
                gender: None,
                number: None,
                scope: ScopeKey::default(),
            },
            LexiconEntry {
                entity_id: EntityId("e2".to_owned()),
                label: "Dynamis".to_owned(),
                aliases: Vec::new(),
                kind: Some(phoenix_types::EntityKind::Organization),
                gender: None,
                number: None,
                scope: ScopeKey::default(),
            },
        ];
        let lexicon = alex.build_lexicon(&entries).expect("build lexicon");
        let matches = alex.scan_text(&lexicon, text, &ScopeKey::default());
        assert!(!matches.is_empty());
    }
}
