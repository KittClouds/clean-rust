use crate::{
    CandidateGenerationPerformanceReceipt, CandidateGenerationReceipt, CandidateSourceCount,
    DecisionCandidateGroup, DecisionCandidateSourceKind, FrozenCandidateAction,
    FrozenGraphDecisionTrajectoryError,
};
use compact_str::CompactString;
use hashbrown::HashSet;
use phoenix_types::{
    AbstainAction, AttachToEpisodeAction, CreateEpisodeAction, GraphDecisionAbstentionReason,
    GraphDecisionAction, GraphDecisionEvidence, GraphDecisionEvidenceRef, GraphDecisionHeader,
};
use serde::{Deserialize, Serialize};
use std::time::Instant;

pub const EPISODE_CANDIDATE_GENERATOR_ID: &str = "phoenix-episode-assignment-candidate-generator";
pub const EPISODE_CANDIDATE_GENERATOR_VERSION: &str = "v1";
pub const GRAPH_DECISION_CANDIDATE_GENERATOR_ID: &str =
    "phoenix-graph-decision-candidate-generator";
pub const GRAPH_DECISION_CANDIDATE_GENERATOR_VERSION: &str = "v1";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EpisodeCandidateSeed {
    pub episode_id: CompactString,
    pub available_at: i64,
    pub active: bool,
    pub scope_compatible: bool,
    pub temporally_plausible: bool,
    pub same_entity: bool,
    pub related_entity: bool,
    pub difficult_near_neighbor: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EpisodeCandidateGenerationRequest {
    pub candidate_group_id: CompactString,
    pub event_id: CompactString,
    pub new_episode_id: CompactString,
    pub task_id: CompactString,
    pub header: GraphDecisionHeader,
    pub evidence: Vec<GraphDecisionEvidenceRef>,
    pub episode_seeds: Vec<EpisodeCandidateSeed>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EpisodeCandidateGeneration {
    pub group: DecisionCandidateGroup,
    pub performance: CandidateGenerationPerformanceReceipt,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionCandidateSeed {
    pub action: GraphDecisionAction,
    pub sources: Vec<DecisionCandidateSourceKind>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionCandidateGenerationRequest {
    pub candidate_group_id: CompactString,
    pub generator_input_id: CompactString,
    pub seeds: Vec<GraphDecisionCandidateSeed>,
}

pub fn generate_episode_assignment_candidates(
    request: &EpisodeCandidateGenerationRequest,
) -> Result<EpisodeCandidateGeneration, FrozenGraphDecisionTrajectoryError> {
    let started = Instant::now();
    validate_request(request)?;
    let generator_input_id = semantic_identity(request)?;
    let mut seeds = request.episode_seeds.clone();
    seeds.sort_unstable_by(|left, right| left.episode_id.cmp(&right.episode_id));

    let mut candidates = Vec::with_capacity(seeds.len().saturating_add(2));
    let mut seen = HashSet::with_capacity(seeds.len());
    let mut invalid_candidates_rejected = 0_u32;
    let header = candidate_header(&request.header);
    let evidence = candidate_evidence(&request.evidence);
    for seed in seeds {
        if seed.episode_id.trim().is_empty()
            || seed.available_at <= 0
            || seed.available_at > request.header.decided_at
            || !seed.active
            || !seed.scope_compatible
            || !seen.insert(seed.episode_id.clone())
        {
            invalid_candidates_rejected = invalid_candidates_rejected.saturating_add(1);
            continue;
        }
        let mut sources = vec![DecisionCandidateSourceKind::ActiveCompatibleEpisode];
        if seed.temporally_plausible {
            sources.push(DecisionCandidateSourceKind::TemporallyPlausibleEpisode);
        }
        if seed.same_entity {
            sources.push(DecisionCandidateSourceKind::SameEntityEpisode);
        }
        if seed.related_entity {
            sources.push(DecisionCandidateSourceKind::RelatedEntityEpisode);
        }
        if seed.difficult_near_neighbor {
            sources.push(DecisionCandidateSourceKind::DifficultNearNeighborEpisode);
        }
        let action = GraphDecisionAction::AttachToEpisode(AttachToEpisodeAction {
            header: header.clone(),
            event_id: request.event_id.clone(),
            episode_id: seed.episode_id,
            candidate_set_id: request.candidate_group_id.clone(),
            evidence: evidence.clone(),
        });
        push_candidate(&mut candidates, action, sources)?;
    }

    push_candidate(
        &mut candidates,
        GraphDecisionAction::CreateEpisode(CreateEpisodeAction {
            header: header.clone(),
            event_id: request.event_id.clone(),
            episode_id: request.new_episode_id.clone(),
            candidate_set_id: request.candidate_group_id.clone(),
            evidence: evidence.clone(),
        }),
        vec![DecisionCandidateSourceKind::ExplicitCreateEpisode],
    )?;
    push_candidate(
        &mut candidates,
        GraphDecisionAction::Abstain(AbstainAction {
            header,
            task_id: request.task_id.clone(),
            candidate_set_id: Some(request.candidate_group_id.clone()),
            reason: GraphDecisionAbstentionReason::InsufficientEvidence,
            evidence,
        }),
        vec![DecisionCandidateSourceKind::ExplicitAbstain],
    )?;

    let candidate_identity = candidate_group_identity(&candidates);
    let hard_negative_composition = source_composition(&candidates);
    let allocation_volume_bytes = candidate_allocation_volume(&candidates);
    let receipt = CandidateGenerationReceipt {
        generator_id: EPISODE_CANDIDATE_GENERATOR_ID.into(),
        generator_version: EPISODE_CANDIDATE_GENERATOR_VERSION.into(),
        generator_input_id,
        candidate_identity: candidate_identity.clone(),
        candidate_count: u32::try_from(candidates.len())
            .map_err(|_| FrozenGraphDecisionTrajectoryError::InvalidInput("candidate count"))?,
        hard_negative_composition,
        invalid_candidates_rejected,
        allocation_volume_bytes,
    };
    let latency = u64::try_from(started.elapsed().as_nanos())
        .unwrap_or(u64::MAX)
        .max(1);
    Ok(EpisodeCandidateGeneration {
        group: DecisionCandidateGroup {
            candidate_group_id: request.candidate_group_id.clone(),
            candidates,
            generation: receipt,
        },
        performance: CandidateGenerationPerformanceReceipt {
            candidate_identity,
            generation_latency_ns: latency,
            allocation_volume_bytes,
        },
    })
}

pub fn generate_graph_decision_candidates(
    request: &GraphDecisionCandidateGenerationRequest,
) -> Result<EpisodeCandidateGeneration, FrozenGraphDecisionTrajectoryError> {
    let started = Instant::now();
    if request.candidate_group_id.trim().is_empty()
        || request.generator_input_id.trim().is_empty()
        || request.seeds.is_empty()
    {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "graph decision candidate request",
        ));
    }
    let mut prepared = Vec::with_capacity(request.seeds.len());
    let mut invalid_candidates_rejected = 0_u32;
    for seed in &request.seeds {
        if seed.sources.is_empty() || seed.action.validate_candidate().is_err() {
            invalid_candidates_rejected = invalid_candidates_rejected.saturating_add(1);
            continue;
        }
        prepared.push((graph_decision_candidate_identity(&seed.action)?, seed));
    }
    prepared.sort_unstable_by(|left, right| left.0.cmp(&right.0));
    let mut candidates = Vec::with_capacity(prepared.len());
    for (identity, seed) in prepared {
        if candidates
            .last()
            .is_some_and(|prior: &FrozenCandidateAction| prior.action_identity == identity)
        {
            invalid_candidates_rejected = invalid_candidates_rejected.saturating_add(1);
            continue;
        }
        let mut sources = seed.sources.clone();
        sources.sort_unstable();
        sources.dedup();
        candidates.push(FrozenCandidateAction {
            action_identity: identity,
            sources,
            action: seed.action.clone(),
        });
    }
    if candidates.is_empty() {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "no valid graph decision candidates",
        ));
    }
    let candidate_identity = candidate_group_identity(&candidates);
    let allocation_volume_bytes = candidate_allocation_volume(&candidates);
    let group = DecisionCandidateGroup {
        candidate_group_id: request.candidate_group_id.clone(),
        generation: CandidateGenerationReceipt {
            generator_id: GRAPH_DECISION_CANDIDATE_GENERATOR_ID.into(),
            generator_version: GRAPH_DECISION_CANDIDATE_GENERATOR_VERSION.into(),
            generator_input_id: request.generator_input_id.clone(),
            candidate_identity: candidate_identity.clone(),
            candidate_count: u32::try_from(candidates.len())
                .map_err(|_| FrozenGraphDecisionTrajectoryError::InvalidInput("candidate count"))?,
            hard_negative_composition: source_composition(&candidates),
            invalid_candidates_rejected,
            allocation_volume_bytes,
        },
        candidates,
    };
    Ok(EpisodeCandidateGeneration {
        group,
        performance: CandidateGenerationPerformanceReceipt {
            candidate_identity,
            generation_latency_ns: u64::try_from(started.elapsed().as_nanos())
                .unwrap_or(u64::MAX)
                .max(1),
            allocation_volume_bytes,
        },
    })
}

pub fn graph_decision_candidate_identity(
    action: &GraphDecisionAction,
) -> Result<CompactString, FrozenGraphDecisionTrajectoryError> {
    phoenix_types::graph_decision_action_identity(action)
        .map_err(|_| FrozenGraphDecisionTrajectoryError::InvalidInput("candidate action identity"))
}

pub fn candidate_group_identity(candidates: &[FrozenCandidateAction]) -> CompactString {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix-candidate-group/v1\0");
    for candidate in candidates {
        hasher.update(&(candidate.action_identity.len() as u64).to_le_bytes());
        hasher.update(candidate.action_identity.as_bytes());
        for source in &candidate.sources {
            hasher.update(&[*source as u8]);
        }
        hasher.update(&[0xff]);
    }
    format!("b3-{}", hasher.finalize().to_hex()).into()
}

fn push_candidate(
    candidates: &mut Vec<FrozenCandidateAction>,
    action: GraphDecisionAction,
    sources: Vec<DecisionCandidateSourceKind>,
) -> Result<(), FrozenGraphDecisionTrajectoryError> {
    action.validate_candidate()?;
    let action_identity = graph_decision_candidate_identity(&action)?;
    if candidates
        .iter()
        .any(|candidate| candidate.action_identity == action_identity)
    {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "duplicate candidate action",
        ));
    }
    candidates.push(FrozenCandidateAction {
        action_identity,
        sources,
        action,
    });
    Ok(())
}

fn candidate_header(header: &GraphDecisionHeader) -> GraphDecisionHeader {
    let mut candidate = header.clone();
    candidate.approval = None;
    candidate
}

fn candidate_evidence(evidence: &[GraphDecisionEvidenceRef]) -> GraphDecisionEvidence {
    evidence.iter().cloned().collect()
}

fn validate_request(
    request: &EpisodeCandidateGenerationRequest,
) -> Result<(), FrozenGraphDecisionTrajectoryError> {
    if request.candidate_group_id.trim().is_empty()
        || request.event_id.trim().is_empty()
        || request.new_episode_id.trim().is_empty()
        || request.task_id.trim().is_empty()
        || request.header.decided_at <= 0
        || request.header.approval.is_some()
    {
        return Err(FrozenGraphDecisionTrajectoryError::InvalidInput(
            "episode candidate request",
        ));
    }
    Ok(())
}

fn semantic_identity<T: Serialize>(
    value: &T,
) -> Result<CompactString, FrozenGraphDecisionTrajectoryError> {
    let bytes = serde_json::to_vec(value)?;
    Ok(format!("b3-{}", blake3::hash(&bytes).to_hex()).into())
}

fn source_composition(candidates: &[FrozenCandidateAction]) -> Vec<CandidateSourceCount> {
    let mut counts = [0_u32; 12];
    for candidate in candidates {
        for source in &candidate.sources {
            counts[*source as usize] = counts[*source as usize].saturating_add(1);
        }
    }
    const SOURCES: [DecisionCandidateSourceKind; 12] = [
        DecisionCandidateSourceKind::ActiveCompatibleEpisode,
        DecisionCandidateSourceKind::TemporallyPlausibleEpisode,
        DecisionCandidateSourceKind::SameEntityEpisode,
        DecisionCandidateSourceKind::RelatedEntityEpisode,
        DecisionCandidateSourceKind::DifficultNearNeighborEpisode,
        DecisionCandidateSourceKind::SameRelationHardNegative,
        DecisionCandidateSourceKind::EvidenceConfusableAlternative,
        DecisionCandidateSourceKind::TemporallyPlausibleIncorrectAction,
        DecisionCandidateSourceKind::StructurallyValidSemanticNegative,
        DecisionCandidateSourceKind::MinimalEditRepairAlternative,
        DecisionCandidateSourceKind::ExplicitCreateEpisode,
        DecisionCandidateSourceKind::ExplicitAbstain,
    ];
    SOURCES
        .into_iter()
        .enumerate()
        .filter_map(|(index, source)| {
            (counts[index] > 0).then_some(CandidateSourceCount {
                source,
                count: counts[index],
            })
        })
        .collect()
}

fn candidate_allocation_volume(candidates: &[FrozenCandidateAction]) -> u64 {
    let fixed = candidates
        .len()
        .saturating_mul(std::mem::size_of::<FrozenCandidateAction>());
    let variable = candidates.iter().fold(0_usize, |sum, candidate| {
        sum.saturating_add(
            candidate.sources.capacity() * std::mem::size_of::<DecisionCandidateSourceKind>(),
        )
        .saturating_add(candidate.action_identity.capacity())
    });
    u64::try_from(fixed.saturating_add(variable)).unwrap_or(u64::MAX)
}
