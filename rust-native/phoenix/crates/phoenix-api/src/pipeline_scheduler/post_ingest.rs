use std::time::Instant;

use phoenix_causal_post::api as causal_api;
use phoenix_event_identity_post::api as event_identity_api;
use phoenix_graph_post::api as graph_api;
use phoenix_memory_post::api as memory_api;
use phoenix_rel_post::api as rel_api;
use phoenix_semantic_v2::{
    CausalScopeSidecar, EventIdentityScopeSidecar, GraphScopeSidecar, MemoryScopeSidecar,
    RelationScopePatchSidecar, StateSchemaScopeSidecar, TemporalScopeSidecar,
};
use phoenix_state_schema_post::api as state_schema_api;
use phoenix_store_native_core::{
    PhoenixArchiveStoreV2, PhoenixCausalPatchStore, PhoenixErPatchStore,
    PhoenixEventIdentityPatchStore, PhoenixGraphKernelStoreV2, PhoenixGraphLearningStore,
    PhoenixGraphPatchStore, PhoenixMemoryPatchStore, PhoenixRelationPatchStore,
    PhoenixScopeRuntimeStore, PhoenixSemanticGraphPatchStore, PhoenixStateSchemaPatchStore,
    PhoenixTemporalPatchStore, ScopeImageSpec,
};
use phoenix_temporal_post::api as temporal_api;

use crate::{
    CausalRunReport, ContinuityRunReport, EventIdentityRunReport, GraphRunReport,
    LateSidecarRunReport, PipelineApiError, PostIngestRunReport, SidecarContinuityRunReport,
    StateSchemaRunReport, TemporalRunReport,
};

use super::context::PipelineGenerationContext;
use super::types::{PipelineRunRequest, PipelineStage, ScopeGenerationKey, StageProductEnvelope};

pub fn run_post_ingest_pipeline<S>(
    store: &S,
    request: PipelineRunRequest,
    glirel_model: Option<&phoenix_rel_post::GlirelModel>,
    relation_specs: &[phoenix_rel_post::GlirelRelationTypeSpec],
    relation_created_at: i64,
    memory_created_at: i64,
) -> Result<PostIngestRunReport, PipelineApiError>
where
    S: PhoenixArchiveStoreV2
        + PhoenixErPatchStore
        + PhoenixEventIdentityPatchStore
        + PhoenixRelationPatchStore
        + PhoenixMemoryPatchStore
        + PhoenixScopeRuntimeStore
        + PhoenixStateSchemaPatchStore,
{
    let mut context = PipelineGenerationContext::new(store, request)?;
    let mut report = PostIngestRunReport::default();
    let scope_keys = context.scope_keys().to_vec();

    for scope in scope_keys {
        while let Some(stage) = context.next_ready_stage_for_scope(&scope) {
            context.mark_stage_running(&scope, stage);
            let stage_started = Instant::now();
            match stage {
                PipelineStage::Relation => {
                    let relation_sidecar = run_relation_stage(
                        store,
                        &mut context,
                        &scope,
                        glirel_model,
                        relation_specs,
                        ScopeImageSpec::post_ingest(),
                        relation_created_at,
                    )?;
                    report.relation_scope_count += 1;
                    report.relation_case_count += relation_sidecar.1;
                    report.persisted_relation_edge_count +=
                        relation_sidecar.0.payload.edge_additions.len();
                    context.remember_relation_product(relation_sidecar.0);
                }
                PipelineStage::StateSchema => {
                    let analysis = context.analysis_for(&scope, ScopeImageSpec::post_ingest())?;
                    let relation_sidecar = context.relation_product(&scope);
                    let state_schema_sidecar = run_state_schema_stage(
                        store,
                        &scope,
                        &analysis,
                        relation_sidecar
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.relation.as_ref()),
                        relation_created_at,
                    )?;
                    report.state_schema_scope_count += 1;
                    report.state_schema_slot_family_count +=
                        state_schema_sidecar.payload.slot_families.len();
                    report.state_schema_slot_definition_count +=
                        state_schema_sidecar.payload.slot_definitions.len();
                    report.state_schema_active_definition_count += state_schema_sidecar
                        .payload
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
                    report.state_schema_candidate_count +=
                        state_schema_sidecar.payload.slot_candidates.len();
                    report.state_schema_write_proposal_count +=
                        state_schema_sidecar.payload.write_proposals.len();
                    context.remember_state_schema_product(state_schema_sidecar);
                }
                PipelineStage::Memory => {
                    let analysis = context.analysis_for(&scope, ScopeImageSpec::post_ingest())?;
                    let relation_sidecar = context.relation_product(&scope);
                    let state_schema_sidecar = context.state_schema_product(&scope);
                    let event_identity_product = context.event_identity_product(&scope);
                    let memory_sidecar = run_memory_stage(
                        store,
                        &scope,
                        &analysis,
                        relation_sidecar
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.relation.as_ref()),
                        state_schema_sidecar
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.state_schema.as_ref()),
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        analysis.runtime.sidecars.memory.as_ref(),
                        memory_created_at,
                    )?;
                    report.memory_scope_count += 1;
                    report.memory_state_count += memory_sidecar.payload.states.len();
                    report.memory_card_count += memory_sidecar.payload.entity_cards.len();
                    context.remember_memory_product(memory_sidecar);
                }
                PipelineStage::EventIdentity
                | PipelineStage::Temporal
                | PipelineStage::Causal
                | PipelineStage::Graph => {
                    unreachable!("post-ingest pipeline should not schedule {stage:?}")
                }
            }
            context.record_stage_elapsed(stage, elapsed_us(stage_started));
            context.mark_stage_complete(&scope, stage);
        }
    }

    report.scheduler = context.metrics().clone();
    Ok(report)
}

pub fn run_late_sidecar_pipeline<S>(
    store: &S,
    request: PipelineRunRequest,
    created_at: i64,
) -> Result<LateSidecarRunReport, PipelineApiError>
where
    S: PhoenixArchiveStoreV2
        + PhoenixErPatchStore
        + PhoenixEventIdentityPatchStore
        + PhoenixRelationPatchStore
        + PhoenixMemoryPatchStore
        + PhoenixScopeRuntimeStore
        + PhoenixStateSchemaPatchStore,
{
    let mut context = PipelineGenerationContext::new(store, request)?;
    let mut report = LateSidecarRunReport::default();
    let scope_keys = context.scope_keys().to_vec();

    for scope in scope_keys {
        while let Some(stage) = context.next_ready_stage_for_scope(&scope) {
            context.mark_stage_running(&scope, stage);
            match stage {
                PipelineStage::Relation => {
                    unreachable!("late sidecars should not schedule relation")
                }
                PipelineStage::StateSchema => {
                    let analysis = context.analysis_for(&scope, ScopeImageSpec::late_sidecars())?;
                    let state_schema_sidecar = run_state_schema_stage(
                        store,
                        &scope,
                        &analysis,
                        analysis.runtime.sidecars.relation.as_ref(),
                        created_at,
                    )?;
                    accumulate_state_schema_report(
                        &mut report.state_schema,
                        &state_schema_sidecar.payload,
                    );
                    context.remember_state_schema_product(state_schema_sidecar);
                }
                PipelineStage::Memory => {
                    let analysis = context.analysis_for(&scope, ScopeImageSpec::late_sidecars())?;
                    let state_schema_sidecar = context.state_schema_product(&scope);
                    let event_identity_product = context.event_identity_product(&scope);
                    let memory_sidecar = run_memory_stage(
                        store,
                        &scope,
                        &analysis,
                        analysis.runtime.sidecars.relation.as_ref(),
                        state_schema_sidecar
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.state_schema.as_ref()),
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        analysis.runtime.sidecars.memory.as_ref(),
                        created_at,
                    )?;
                    report.memory_scope_count += 1;
                    report.memory_state_count += memory_sidecar.payload.states.len();
                    report.memory_event_count += memory_sidecar.payload.events.len();
                    report.memory_claim_count += memory_sidecar.payload.claims.len();
                    report.memory_gap_count += memory_sidecar.payload.gaps.len();
                    report.memory_conflict_count += memory_sidecar.payload.conflicts.len();
                    report.memory_card_count += memory_sidecar.payload.entity_cards.len();
                    context.remember_memory_product(memory_sidecar);
                }
                PipelineStage::EventIdentity
                | PipelineStage::Temporal
                | PipelineStage::Causal
                | PipelineStage::Graph => {
                    unreachable!("late sidecar pipeline should not schedule {stage:?}")
                }
            }
            context.mark_stage_complete(&scope, stage);
        }
    }

    report.scheduler = context.metrics().clone();
    Ok(report)
}

pub fn run_event_identity_pipeline<S>(
    store: &S,
    request: PipelineRunRequest,
    created_at: i64,
) -> Result<EventIdentityRunReport, PipelineApiError>
where
    S: PhoenixArchiveStoreV2 + PhoenixEventIdentityPatchStore + PhoenixScopeRuntimeStore,
{
    let mut context = PipelineGenerationContext::new(store, request)?;
    let mut report = EventIdentityRunReport::default();
    let scope_keys = context.scope_keys().to_vec();

    for scope in scope_keys {
        while let Some(stage) = context.next_ready_stage_for_scope(&scope) {
            context.mark_stage_running(&scope, stage);
            match stage {
                PipelineStage::EventIdentity => {
                    let analysis =
                        context.analysis_for(&scope, ScopeImageSpec::event_identity())?;
                    let sidecar = run_event_identity_stage(
                        store,
                        &scope,
                        &analysis,
                        analysis.runtime.sidecars.event_identity.as_ref(),
                        created_at,
                    )?;
                    report.event_identity_scope_count += 1;
                    report.mention_packet_count += sidecar.payload.mention_packets.len();
                    report.hypothesis_count += sidecar.payload.identity_hypotheses.len();
                    report.canonical_event_count += sidecar.payload.canonical_events.len();
                    report.canonical_card_count += sidecar.payload.canonical_event_cards.len();
                    context.remember_event_identity_product(sidecar);
                }
                _ => unreachable!("event identity pipeline should not schedule {stage:?}"),
            }
            context.mark_stage_complete(&scope, stage);
        }
    }

    report.scheduler = context.metrics().clone();
    Ok(report)
}

pub fn run_temporal_pipeline<S>(
    store: &S,
    request: PipelineRunRequest,
    created_at: i64,
) -> Result<TemporalRunReport, PipelineApiError>
where
    S: PhoenixArchiveStoreV2 + PhoenixScopeRuntimeStore + PhoenixTemporalPatchStore,
{
    let mut context = PipelineGenerationContext::new(store, request)?;
    let mut report = TemporalRunReport::default();
    let scope_keys = context.scope_keys().to_vec();

    for scope in scope_keys {
        while let Some(stage) = context.next_ready_stage_for_scope(&scope) {
            context.mark_stage_running(&scope, stage);
            match stage {
                PipelineStage::Temporal => {
                    let analysis = context.analysis_for(&scope, ScopeImageSpec::temporal())?;
                    let event_identity_product = context.event_identity_product(&scope);
                    let temporal_sidecar = run_temporal_stage(
                        store,
                        &scope,
                        &analysis,
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        analysis.runtime.sidecars.temporal.as_ref(),
                        created_at,
                    )?;
                    report.temporal_scope_count += 1;
                    report.temporal_review_case_count += temporal_sidecar.1;
                    report.temporal_interval_count += temporal_sidecar.0.payload.intervals.len();
                    report.temporal_segment_count +=
                        temporal_sidecar.0.payload.timeline_segments.len();
                    report.temporal_gap_count += temporal_sidecar.0.payload.gaps.len();
                    report.temporal_card_count += temporal_sidecar.0.payload.memory_cards.len();
                    context.remember_temporal_product(temporal_sidecar.0);
                }
                _ => unreachable!("temporal pipeline should not schedule {stage:?}"),
            }
            context.mark_stage_complete(&scope, stage);
        }
    }

    report.scheduler = context.metrics().clone();
    Ok(report)
}

pub fn run_causal_pipeline<S>(
    store: &S,
    request: PipelineRunRequest,
    created_at: i64,
) -> Result<CausalRunReport, PipelineApiError>
where
    S: PhoenixArchiveStoreV2 + PhoenixScopeRuntimeStore + PhoenixCausalPatchStore,
{
    let mut context = PipelineGenerationContext::new(store, request)?;
    let mut report = CausalRunReport::default();
    let scope_keys = context.scope_keys().to_vec();

    for scope in scope_keys {
        while let Some(stage) = context.next_ready_stage_for_scope(&scope) {
            context.mark_stage_running(&scope, stage);
            match stage {
                PipelineStage::Causal => {
                    let analysis = context.analysis_for(&scope, ScopeImageSpec::causal())?;
                    let event_identity_product = context.event_identity_product(&scope);
                    let temporal_product = context.temporal_product(&scope);
                    let causal_sidecar = run_causal_stage(
                        store,
                        &scope,
                        &analysis,
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        temporal_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.temporal.as_ref()),
                        analysis.runtime.sidecars.causal.as_ref(),
                        created_at,
                    )?;
                    report.causal_scope_count += 1;
                    report.causal_review_case_count += causal_sidecar.1;
                    report.causal_edge_count += causal_sidecar.0.payload.edge_additions.len();
                    report.causal_chain_count += causal_sidecar.0.payload.chains.len();
                    report.causal_card_count += causal_sidecar.0.payload.memory_cards.len();
                    context.remember_causal_product(causal_sidecar.0);
                }
                _ => unreachable!("causal pipeline should not schedule {stage:?}"),
            }
            context.mark_stage_complete(&scope, stage);
        }
    }

    report.scheduler = context.metrics().clone();
    Ok(report)
}

pub fn run_graph_pipeline<S>(
    store: &S,
    request: PipelineRunRequest,
    created_at: i64,
) -> Result<GraphRunReport, PipelineApiError>
where
    S: PhoenixArchiveStoreV2
        + PhoenixScopeRuntimeStore
        + PhoenixGraphPatchStore
        + PhoenixGraphKernelStoreV2
        + PhoenixGraphLearningStore
        + PhoenixSemanticGraphPatchStore,
{
    let mut context = PipelineGenerationContext::new(store, request)?;
    let mut report = GraphRunReport::default();
    let scope_keys = context.scope_keys().to_vec();

    for scope in scope_keys {
        while let Some(stage) = context.next_ready_stage_for_scope(&scope) {
            context.mark_stage_running(&scope, stage);
            match stage {
                PipelineStage::Graph => {
                    let analysis = context.analysis_for(&scope, ScopeImageSpec::graph())?;
                    let event_identity_product = context.event_identity_product(&scope);
                    let temporal_product = context.temporal_product(&scope);
                    let causal_product = context.causal_product(&scope);
                    let memory_product = context.memory_product(&scope);
                    let sidecar = run_graph_stage(
                        store,
                        &scope,
                        &analysis,
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        temporal_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.temporal.as_ref()),
                        causal_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.causal.as_ref()),
                        memory_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.memory.as_ref()),
                        analysis.runtime.sidecars.graph.as_ref(),
                        created_at,
                    )?;
                    report.graph_scope_count += 1;
                    report.graph_projection_vertex_count +=
                        sidecar.payload.summary.projection_vertex_count;
                    report.graph_projection_edge_count +=
                        sidecar.payload.summary.projection_edge_count;
                    report.graph_claim_node_count += sidecar.payload.summary.claim_node_count;
                    report.graph_event_node_count += sidecar.payload.summary.event_node_count;
                    report.graph_state_node_count += sidecar.payload.summary.state_node_count;
                    context.remember_graph_product(sidecar);
                }
                _ => unreachable!("graph pipeline should not schedule {stage:?}"),
            }
            context.mark_stage_complete(&scope, stage);
        }
    }

    report.scheduler = context.metrics().clone();
    Ok(report)
}

pub fn run_sidecar_continuity_pipeline<S>(
    store: &S,
    request: PipelineRunRequest,
    created_at: i64,
) -> Result<SidecarContinuityRunReport, PipelineApiError>
where
    S: PhoenixArchiveStoreV2
        + PhoenixScopeRuntimeStore
        + PhoenixEventIdentityPatchStore
        + PhoenixTemporalPatchStore
        + PhoenixCausalPatchStore
        + PhoenixStateSchemaPatchStore
        + PhoenixMemoryPatchStore
        + PhoenixGraphPatchStore
        + PhoenixGraphKernelStoreV2
        + PhoenixGraphLearningStore
        + PhoenixSemanticGraphPatchStore,
{
    let mut context = PipelineGenerationContext::new(store, request)?;
    let mut report = SidecarContinuityRunReport::default();
    let scope_keys = context.scope_keys().to_vec();
    let runtime_spec = ScopeImageSpec::sidecar_continuity();

    for scope in scope_keys {
        while let Some(stage) = context.next_ready_stage_for_scope(&scope) {
            context.mark_stage_running(&scope, stage);
            match stage {
                PipelineStage::EventIdentity => {
                    let analysis = context.analysis_for(&scope, runtime_spec)?;
                    let sidecar = run_event_identity_stage(
                        store,
                        &scope,
                        &analysis,
                        analysis.runtime.sidecars.event_identity.as_ref(),
                        created_at,
                    )?;
                    report.event_identity.event_identity_scope_count += 1;
                    report.event_identity.mention_packet_count +=
                        sidecar.payload.mention_packets.len();
                    report.event_identity.hypothesis_count +=
                        sidecar.payload.identity_hypotheses.len();
                    report.event_identity.canonical_event_count +=
                        sidecar.payload.canonical_events.len();
                    report.event_identity.canonical_card_count +=
                        sidecar.payload.canonical_event_cards.len();
                    context.remember_event_identity_product(sidecar);
                }
                PipelineStage::Temporal => {
                    let analysis = context.analysis_for(&scope, runtime_spec)?;
                    let event_identity_product = context.event_identity_product(&scope);
                    let temporal_sidecar = run_temporal_stage(
                        store,
                        &scope,
                        &analysis,
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        analysis.runtime.sidecars.temporal.as_ref(),
                        created_at,
                    )?;
                    report.temporal.temporal_scope_count += 1;
                    report.temporal.temporal_review_case_count += temporal_sidecar.1;
                    report.temporal.temporal_interval_count +=
                        temporal_sidecar.0.payload.intervals.len();
                    report.temporal.temporal_segment_count +=
                        temporal_sidecar.0.payload.timeline_segments.len();
                    report.temporal.temporal_gap_count += temporal_sidecar.0.payload.gaps.len();
                    report.temporal.temporal_card_count +=
                        temporal_sidecar.0.payload.memory_cards.len();
                    context.remember_temporal_product(temporal_sidecar.0);
                }
                PipelineStage::Causal => {
                    let analysis = context.analysis_for(&scope, runtime_spec)?;
                    let event_identity_product = context.event_identity_product(&scope);
                    let temporal_product = context.temporal_product(&scope);
                    let causal_sidecar = run_causal_stage(
                        store,
                        &scope,
                        &analysis,
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        temporal_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.temporal.as_ref()),
                        analysis.runtime.sidecars.causal.as_ref(),
                        created_at,
                    )?;
                    report.causal.causal_scope_count += 1;
                    report.causal.causal_review_case_count += causal_sidecar.1;
                    report.causal.causal_edge_count +=
                        causal_sidecar.0.payload.edge_additions.len();
                    report.causal.causal_chain_count += causal_sidecar.0.payload.chains.len();
                    report.causal.causal_card_count += causal_sidecar.0.payload.memory_cards.len();
                    context.remember_causal_product(causal_sidecar.0);
                }
                PipelineStage::StateSchema => {
                    let analysis = context.analysis_for(&scope, runtime_spec)?;
                    let state_schema_sidecar = run_state_schema_stage(
                        store,
                        &scope,
                        &analysis,
                        analysis.runtime.sidecars.relation.as_ref(),
                        created_at,
                    )?;
                    accumulate_state_schema_report(
                        &mut report.late_sidecars.state_schema,
                        &state_schema_sidecar.payload,
                    );
                    context.remember_state_schema_product(state_schema_sidecar);
                }
                PipelineStage::Memory => {
                    let analysis = context.analysis_for(&scope, runtime_spec)?;
                    let state_schema_sidecar = context.state_schema_product(&scope);
                    let event_identity_product = context.event_identity_product(&scope);
                    let memory_sidecar = run_memory_stage(
                        store,
                        &scope,
                        &analysis,
                        analysis.runtime.sidecars.relation.as_ref(),
                        state_schema_sidecar
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.state_schema.as_ref()),
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        analysis.runtime.sidecars.memory.as_ref(),
                        created_at,
                    )?;
                    report.late_sidecars.memory_scope_count += 1;
                    report.late_sidecars.memory_state_count += memory_sidecar.payload.states.len();
                    report.late_sidecars.memory_event_count += memory_sidecar.payload.events.len();
                    report.late_sidecars.memory_claim_count += memory_sidecar.payload.claims.len();
                    report.late_sidecars.memory_gap_count += memory_sidecar.payload.gaps.len();
                    report.late_sidecars.memory_conflict_count +=
                        memory_sidecar.payload.conflicts.len();
                    report.late_sidecars.memory_card_count +=
                        memory_sidecar.payload.entity_cards.len();
                    context.remember_memory_product(memory_sidecar);
                }
                PipelineStage::Graph => {
                    let analysis = context.analysis_for(&scope, runtime_spec)?;
                    let event_identity_product = context.event_identity_product(&scope);
                    let temporal_product = context.temporal_product(&scope);
                    let causal_product = context.causal_product(&scope);
                    let memory_product = context.memory_product(&scope);
                    let sidecar = run_graph_stage(
                        store,
                        &scope,
                        &analysis,
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        temporal_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.temporal.as_ref()),
                        causal_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.causal.as_ref()),
                        memory_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.memory.as_ref()),
                        analysis.runtime.sidecars.graph.as_ref(),
                        created_at,
                    )?;
                    report.graph.graph_scope_count += 1;
                    report.graph.graph_projection_vertex_count +=
                        sidecar.payload.summary.projection_vertex_count;
                    report.graph.graph_projection_edge_count +=
                        sidecar.payload.summary.projection_edge_count;
                    report.graph.graph_claim_node_count += sidecar.payload.summary.claim_node_count;
                    report.graph.graph_event_node_count += sidecar.payload.summary.event_node_count;
                    report.graph.graph_state_node_count += sidecar.payload.summary.state_node_count;
                    context.remember_graph_product(sidecar);
                }
                PipelineStage::Relation => {
                    unreachable!("sidecar continuity pipeline should not schedule relation")
                }
            }
            context.mark_stage_complete(&scope, stage);
        }
    }

    report.scheduler = context.metrics().clone();
    report.event_identity.scheduler = report.scheduler.clone();
    report.temporal.scheduler = report.scheduler.clone();
    report.causal.scheduler = report.scheduler.clone();
    report.late_sidecars.scheduler = report.scheduler.clone();
    report.graph.scheduler = report.scheduler.clone();
    Ok(report)
}

#[allow(clippy::too_many_arguments)]
pub fn run_continuity_pipeline<S>(
    store: &S,
    request: PipelineRunRequest,
    event_identity_created_at: i64,
    temporal_created_at: i64,
    causal_created_at: i64,
    glirel_model: Option<&phoenix_rel_post::GlirelModel>,
    relation_specs: &[phoenix_rel_post::GlirelRelationTypeSpec],
    relation_created_at: i64,
    memory_created_at: i64,
) -> Result<ContinuityRunReport, PipelineApiError>
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
    let mut context = PipelineGenerationContext::new(store, request)?;
    let mut report = ContinuityRunReport::default();
    let scope_keys = context.scope_keys().to_vec();
    let runtime_spec = ScopeImageSpec::continuity();

    for scope in scope_keys {
        while let Some(stage) = context.next_ready_stage_for_scope(&scope) {
            context.mark_stage_running(&scope, stage);
            match stage {
                PipelineStage::EventIdentity => {
                    let analysis = context.analysis_for(&scope, runtime_spec)?;
                    let sidecar = run_event_identity_stage(
                        store,
                        &scope,
                        &analysis,
                        analysis.runtime.sidecars.event_identity.as_ref(),
                        event_identity_created_at,
                    )?;
                    report.event_identity.event_identity_scope_count += 1;
                    report.event_identity.mention_packet_count +=
                        sidecar.payload.mention_packets.len();
                    report.event_identity.hypothesis_count +=
                        sidecar.payload.identity_hypotheses.len();
                    report.event_identity.canonical_event_count +=
                        sidecar.payload.canonical_events.len();
                    report.event_identity.canonical_card_count +=
                        sidecar.payload.canonical_event_cards.len();
                    context.remember_event_identity_product(sidecar);
                }
                PipelineStage::Temporal => {
                    let analysis = context.analysis_for(&scope, runtime_spec)?;
                    let event_identity_product = context.event_identity_product(&scope);
                    let temporal_sidecar = run_temporal_stage(
                        store,
                        &scope,
                        &analysis,
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        analysis.runtime.sidecars.temporal.as_ref(),
                        temporal_created_at,
                    )?;
                    report.temporal.temporal_scope_count += 1;
                    report.temporal.temporal_review_case_count += temporal_sidecar.1;
                    report.temporal.temporal_interval_count +=
                        temporal_sidecar.0.payload.intervals.len();
                    report.temporal.temporal_segment_count +=
                        temporal_sidecar.0.payload.timeline_segments.len();
                    report.temporal.temporal_gap_count += temporal_sidecar.0.payload.gaps.len();
                    report.temporal.temporal_card_count +=
                        temporal_sidecar.0.payload.memory_cards.len();
                    context.remember_temporal_product(temporal_sidecar.0);
                }
                PipelineStage::Causal => {
                    let analysis = context.analysis_for(&scope, runtime_spec)?;
                    let event_identity_product = context.event_identity_product(&scope);
                    let temporal_product = context.temporal_product(&scope);
                    let causal_sidecar = run_causal_stage(
                        store,
                        &scope,
                        &analysis,
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        temporal_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.temporal.as_ref()),
                        analysis.runtime.sidecars.causal.as_ref(),
                        causal_created_at,
                    )?;
                    report.causal.causal_scope_count += 1;
                    report.causal.causal_review_case_count += causal_sidecar.1;
                    report.causal.causal_edge_count +=
                        causal_sidecar.0.payload.edge_additions.len();
                    report.causal.causal_chain_count += causal_sidecar.0.payload.chains.len();
                    report.causal.causal_card_count += causal_sidecar.0.payload.memory_cards.len();
                    context.remember_causal_product(causal_sidecar.0);
                }
                PipelineStage::Relation => {
                    let relation_sidecar = run_relation_stage(
                        store,
                        &mut context,
                        &scope,
                        glirel_model,
                        relation_specs,
                        ScopeImageSpec::continuity(),
                        relation_created_at,
                    )?;
                    report.post_ingest.relation_scope_count += 1;
                    report.post_ingest.relation_case_count += relation_sidecar.1;
                    report.post_ingest.persisted_relation_edge_count +=
                        relation_sidecar.0.payload.edge_additions.len();
                    context.remember_relation_product(relation_sidecar.0);
                }
                PipelineStage::StateSchema => {
                    let analysis = context.analysis_for(&scope, runtime_spec)?;
                    let relation_sidecar = context.relation_product(&scope);
                    let state_schema_sidecar = run_state_schema_stage(
                        store,
                        &scope,
                        &analysis,
                        relation_sidecar
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.relation.as_ref()),
                        relation_created_at,
                    )?;
                    report.post_ingest.state_schema_scope_count += 1;
                    report.post_ingest.state_schema_slot_family_count +=
                        state_schema_sidecar.payload.slot_families.len();
                    report.post_ingest.state_schema_slot_definition_count +=
                        state_schema_sidecar.payload.slot_definitions.len();
                    report.post_ingest.state_schema_active_definition_count += state_schema_sidecar
                        .payload
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
                    report.post_ingest.state_schema_candidate_count +=
                        state_schema_sidecar.payload.slot_candidates.len();
                    report.post_ingest.state_schema_write_proposal_count +=
                        state_schema_sidecar.payload.write_proposals.len();
                    context.remember_state_schema_product(state_schema_sidecar);
                }
                PipelineStage::Memory => {
                    let analysis = context.analysis_for(&scope, runtime_spec)?;
                    let relation_sidecar = context.relation_product(&scope);
                    let state_schema_sidecar = context.state_schema_product(&scope);
                    let event_identity_product = context.event_identity_product(&scope);
                    let memory_sidecar = run_memory_stage(
                        store,
                        &scope,
                        &analysis,
                        relation_sidecar
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.relation.as_ref()),
                        state_schema_sidecar
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.state_schema.as_ref()),
                        event_identity_product
                            .as_ref()
                            .map(|product| &product.payload)
                            .or(analysis.runtime.sidecars.event_identity.as_ref()),
                        analysis.runtime.sidecars.memory.as_ref(),
                        memory_created_at,
                    )?;
                    report.post_ingest.memory_scope_count += 1;
                    report.post_ingest.memory_state_count += memory_sidecar.payload.states.len();
                    report.post_ingest.memory_card_count +=
                        memory_sidecar.payload.entity_cards.len();
                    context.remember_memory_product(memory_sidecar);
                }
                PipelineStage::Graph => {
                    unreachable!("continuity pipeline should not schedule graph")
                }
            }
            context.mark_stage_complete(&scope, stage);
        }
    }

    report.state_schema = StateSchemaRunReport {
        state_schema_scope_count: report.post_ingest.state_schema_scope_count,
        slot_family_count: report.post_ingest.state_schema_slot_family_count,
        slot_definition_count: report.post_ingest.state_schema_slot_definition_count,
        active_definition_count: report.post_ingest.state_schema_active_definition_count,
        candidate_count: report.post_ingest.state_schema_candidate_count,
        write_proposal_count: report.post_ingest.state_schema_write_proposal_count,
    };
    report.scheduler = context.metrics().clone();
    report.event_identity.scheduler = report.scheduler.clone();
    report.temporal.scheduler = report.scheduler.clone();
    report.causal.scheduler = report.scheduler.clone();
    report.post_ingest.scheduler = report.scheduler.clone();
    Ok(report)
}

fn run_relation_stage<S>(
    store: &S,
    context: &mut PipelineGenerationContext<'_, S>,
    scope: &ScopeGenerationKey,
    glirel_model: Option<&phoenix_rel_post::GlirelModel>,
    relation_specs: &[phoenix_rel_post::GlirelRelationTypeSpec],
    spec: ScopeImageSpec,
    relation_created_at: i64,
) -> Result<(StageProductEnvelope<RelationScopePatchSidecar>, usize), PipelineApiError>
where
    S: PhoenixArchiveStoreV2 + PhoenixRelationPatchStore + PhoenixScopeRuntimeStore,
{
    let prepared = context.prepared_relation_input_for(scope, spec, relation_specs)?;
    let mut batch = prepared.batch.clone();
    if let Some(glirel_model) = glirel_model {
        for job in &prepared.model_jobs {
            context.record_relation_model_job(job);
            rel_api::run_glirel_job_with_input(&mut batch, &prepared, glirel_model, job)?;
        }
    } else {
        prepared.plan.apply_heuristic(&mut batch);
    }
    let decisions = rel_api::draft_decisions(&batch, relation_specs);
    let review_case_count = batch.review_cases.len();
    let analysis = context.analysis_for(scope, spec)?;
    let sidecar = rel_api::persist_patch_sidecar_with_existing(
        store,
        &batch,
        &decisions,
        relation_created_at,
        analysis.runtime.sidecars.relation.as_ref(),
    )?;
    Ok((
        StageProductEnvelope {
            key: scope.clone(),
            stage: PipelineStage::Relation,
            created_at: relation_created_at,
            input_fingerprint: scope.generation,
            payload: sidecar,
        },
        review_case_count,
    ))
}

fn run_event_identity_stage<S>(
    store: &S,
    scope: &ScopeGenerationKey,
    analysis: &phoenix_scope_analysis::ScopeAnalysisContext,
    event_identity_sidecar: Option<&EventIdentityScopeSidecar>,
    created_at: i64,
) -> Result<StageProductEnvelope<EventIdentityScopeSidecar>, PipelineApiError>
where
    S: PhoenixEventIdentityPatchStore,
{
    let mut batch =
        event_identity_api::derive_batch_from_analysis(analysis, event_identity_sidecar);
    event_identity_api::run_batch(&mut batch, created_at);
    let sidecar = event_identity_api::persist_patch_sidecar_with_existing(
        store,
        &batch,
        created_at,
        event_identity_sidecar,
    )?;
    Ok(StageProductEnvelope {
        key: scope.clone(),
        stage: PipelineStage::EventIdentity,
        created_at,
        input_fingerprint: scope.generation,
        payload: sidecar,
    })
}

fn run_temporal_stage<S>(
    store: &S,
    scope: &ScopeGenerationKey,
    analysis: &phoenix_scope_analysis::ScopeAnalysisContext,
    event_identity_sidecar: Option<&EventIdentityScopeSidecar>,
    temporal_sidecar: Option<&TemporalScopeSidecar>,
    created_at: i64,
) -> Result<(StageProductEnvelope<TemporalScopeSidecar>, usize), PipelineApiError>
where
    S: PhoenixTemporalPatchStore,
{
    let mut batch = temporal_api::derive_batch_from_analysis(
        analysis,
        event_identity_sidecar,
        temporal_sidecar,
    );
    temporal_api::run_batch(&mut batch, created_at);
    let review_case_count = batch.review_cases.len();
    let sidecar = temporal_api::persist_patch_sidecar_with_existing(
        store,
        &batch,
        created_at,
        temporal_sidecar,
    )?;
    Ok((
        StageProductEnvelope {
            key: scope.clone(),
            stage: PipelineStage::Temporal,
            created_at,
            input_fingerprint: scope.generation,
            payload: sidecar,
        },
        review_case_count,
    ))
}

fn run_causal_stage<S>(
    store: &S,
    scope: &ScopeGenerationKey,
    analysis: &phoenix_scope_analysis::ScopeAnalysisContext,
    event_identity_sidecar: Option<&EventIdentityScopeSidecar>,
    temporal_sidecar: Option<&TemporalScopeSidecar>,
    causal_sidecar: Option<&CausalScopeSidecar>,
    created_at: i64,
) -> Result<(StageProductEnvelope<CausalScopeSidecar>, usize), PipelineApiError>
where
    S: PhoenixCausalPatchStore,
{
    let mut batch = causal_api::derive_batch_from_analysis(
        analysis,
        event_identity_sidecar,
        temporal_sidecar,
        causal_sidecar,
    );
    causal_api::run_batch(&mut batch, created_at);
    let review_case_count = batch.review_cases.len();
    let sidecar =
        causal_api::persist_patch_sidecar_with_existing(store, &batch, created_at, causal_sidecar)?;
    Ok((
        StageProductEnvelope {
            key: scope.clone(),
            stage: PipelineStage::Causal,
            created_at,
            input_fingerprint: scope.generation,
            payload: sidecar,
        },
        review_case_count,
    ))
}

#[allow(clippy::too_many_arguments)]
fn run_graph_stage<S>(
    store: &S,
    scope: &ScopeGenerationKey,
    analysis: &phoenix_scope_analysis::ScopeAnalysisContext,
    event_identity_sidecar: Option<&EventIdentityScopeSidecar>,
    temporal_sidecar: Option<&TemporalScopeSidecar>,
    causal_sidecar: Option<&CausalScopeSidecar>,
    memory_sidecar: Option<&MemoryScopeSidecar>,
    graph_sidecar: Option<&GraphScopeSidecar>,
    created_at: i64,
) -> Result<StageProductEnvelope<GraphScopeSidecar>, PipelineApiError>
where
    S: PhoenixGraphPatchStore
        + PhoenixSemanticGraphPatchStore
        + PhoenixGraphKernelStoreV2
        + PhoenixGraphLearningStore,
{
    let batch = graph_api::derive_batch_from_analysis(
        analysis,
        event_identity_sidecar,
        temporal_sidecar,
        causal_sidecar,
        memory_sidecar,
    );
    let sidecar =
        graph_api::persist_patch_sidecar_with_existing(store, &batch, created_at, graph_sidecar)?;
    Ok(StageProductEnvelope {
        key: scope.clone(),
        stage: PipelineStage::Graph,
        created_at,
        input_fingerprint: scope.generation,
        payload: sidecar,
    })
}

fn run_state_schema_stage<S>(
    store: &S,
    scope: &ScopeGenerationKey,
    analysis: &phoenix_scope_analysis::ScopeAnalysisContext,
    relation_sidecar: Option<&RelationScopePatchSidecar>,
    created_at: i64,
) -> Result<StageProductEnvelope<StateSchemaScopeSidecar>, PipelineApiError>
where
    S: PhoenixStateSchemaPatchStore,
{
    let mut batch = state_schema_api::derive_batch_from_analysis(analysis, relation_sidecar);
    state_schema_api::run_batch(&mut batch, created_at);
    let sidecar = state_schema_api::persist_patch_sidecar_with_existing(
        store,
        &batch,
        created_at,
        analysis.runtime.sidecars.state_schema.as_ref(),
    )?;
    Ok(StageProductEnvelope {
        key: scope.clone(),
        stage: PipelineStage::StateSchema,
        created_at,
        input_fingerprint: scope.generation,
        payload: sidecar,
    })
}

#[allow(clippy::too_many_arguments)]
fn run_memory_stage<S>(
    store: &S,
    scope: &ScopeGenerationKey,
    analysis: &phoenix_scope_analysis::ScopeAnalysisContext,
    relation_sidecar: Option<&RelationScopePatchSidecar>,
    state_schema_sidecar: Option<&StateSchemaScopeSidecar>,
    event_identity_sidecar: Option<&phoenix_semantic_v2::EventIdentityScopeSidecar>,
    memory_sidecar: Option<&MemoryScopeSidecar>,
    created_at: i64,
) -> Result<StageProductEnvelope<MemoryScopeSidecar>, PipelineApiError>
where
    S: PhoenixMemoryPatchStore,
{
    let batch = memory_api::derive_batch_from_analysis(
        analysis,
        relation_sidecar,
        state_schema_sidecar,
        event_identity_sidecar,
        memory_sidecar,
    );
    let sidecar =
        memory_api::persist_patch_sidecar_with_existing(store, &batch, created_at, memory_sidecar)?;
    Ok(StageProductEnvelope {
        key: scope.clone(),
        stage: PipelineStage::Memory,
        created_at,
        input_fingerprint: scope.generation,
        payload: sidecar,
    })
}

fn accumulate_state_schema_report(
    report: &mut StateSchemaRunReport,
    sidecar: &StateSchemaScopeSidecar,
) {
    report.state_schema_scope_count += 1;
    report.slot_family_count += sidecar.slot_families.len();
    report.slot_definition_count += sidecar.slot_definitions.len();
    report.active_definition_count += sidecar
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
    report.candidate_count += sidecar.slot_candidates.len();
    report.write_proposal_count += sidecar.write_proposals.len();
}

fn elapsed_us(started: Instant) -> u64 {
    started.elapsed().as_micros() as u64
}
