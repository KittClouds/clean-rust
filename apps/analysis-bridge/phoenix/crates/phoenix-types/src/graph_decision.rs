use std::error::Error;
use std::fmt;

use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use smallvec::SmallVec;

use crate::{
    GraphDecisionActionContract, GraphDecisionActionKind, GraphDecisionApprovalRequirement,
    GraphDecisionAuthorityKind, GraphDecisionEvidenceRequirement, GraphDecisionRejectionReason,
};

pub const GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION: u16 = 1;
pub const GRAPH_DECISION_REWARD_SCHEMA_VERSION: u16 = 1;
pub const GRAPH_DECISION_REWARD_SCALE_MICROS: i32 = 1_000_000;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionAuthority {
    pub authority_id: CompactString,
    pub kind: GraphDecisionAuthorityKind,
    pub policy_id: CompactString,
    pub issued_at: i64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionApproval {
    pub approval_id: CompactString,
    pub approver_id: CompactString,
    pub approved_at: i64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionHeader {
    pub schema_version: u16,
    pub decision_id: CompactString,
    pub pre_state_id: CompactString,
    pub decided_at: i64,
    pub authority: GraphDecisionAuthority,
    pub approval: Option<GraphDecisionApproval>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionEvidenceRef {
    pub evidence_id: CompactString,
    pub authority_id: CompactString,
    pub available_at: i64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDeltaRejectionReason {
    UnsupportedByEvidence,
    ContradictsAuthoritativeState,
    Duplicate,
    StalePreState,
    InvalidScope,
    InvariantViolation,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDeltaDeferralReason {
    InsufficientEvidence,
    AwaitingHumanApproval,
    AwaitingSource,
    TemporalAmbiguity,
    ConflictingAuthority,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDiscrepancyClass {
    Contradiction,
    TemporalRevision,
    ContextualDifference,
    SourceDisagreement,
    DuplicateEvidence,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDecisionAbstentionReason {
    InsufficientEvidence,
    NoLegalAction,
    AmbiguousCandidates,
    AuthorityUnavailable,
    FutureInformationRequired,
    InvariantRisk,
}

pub type GraphDecisionEvidence = SmallVec<[GraphDecisionEvidenceRef; 4]>;

macro_rules! decision_parameters {
    ($name:ident { $($field:ident : $type:ty),+ $(,)? }) => {
        #[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
        #[serde(rename_all = "camelCase", deny_unknown_fields)]
        pub struct $name {
            pub header: GraphDecisionHeader,
            $(pub $field: $type,)+
        }
    };
}

decision_parameters!(AcceptDeltaAction {
    delta_id: CompactString,
    evidence: GraphDecisionEvidence,
});
decision_parameters!(RejectDeltaAction {
    delta_id: CompactString,
    reason: GraphDeltaRejectionReason,
    evidence: GraphDecisionEvidence,
});
decision_parameters!(DeferDeltaAction {
    delta_id: CompactString,
    reason: GraphDeltaDeferralReason,
    resume_after: Option<i64>,
    evidence: GraphDecisionEvidence,
});
decision_parameters!(MergeDeltaAction {
    delta_ids: SmallVec<[CompactString; 4]>,
    merged_delta_id: CompactString,
    evidence: GraphDecisionEvidence,
});
decision_parameters!(AttachToEpisodeAction {
    event_id: CompactString,
    episode_id: CompactString,
    candidate_set_id: CompactString,
    evidence: GraphDecisionEvidence,
});
decision_parameters!(CreateEpisodeAction {
    event_id: CompactString,
    episode_id: CompactString,
    candidate_set_id: CompactString,
    evidence: GraphDecisionEvidence,
});
decision_parameters!(LinkEvidenceAction {
    claim_id: CompactString,
    evidence: GraphDecisionEvidence,
});
decision_parameters!(ClassifyDiscrepancyAction {
    discrepancy_id: CompactString,
    assertion_ids: SmallVec<[CompactString; 4]>,
    classification: GraphDiscrepancyClass,
    evidence: GraphDecisionEvidence,
});
decision_parameters!(ProposeRelationAction {
    proposal_id: CompactString,
    source_id: CompactString,
    relation_type: CompactString,
    target_id: CompactString,
    evidence: GraphDecisionEvidence,
});
decision_parameters!(RepairGraphRegionAction {
    region_id: CompactString,
    repair_delta_id: CompactString,
    evidence: GraphDecisionEvidence,
});
decision_parameters!(AbstainAction {
    task_id: CompactString,
    candidate_set_id: Option<CompactString>,
    reason: GraphDecisionAbstentionReason,
    evidence: GraphDecisionEvidence,
});

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    content = "parameters",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum GraphDecisionAction {
    AcceptDelta(AcceptDeltaAction),
    RejectDelta(RejectDeltaAction),
    DeferDelta(DeferDeltaAction),
    MergeDelta(MergeDeltaAction),
    AttachToEpisode(AttachToEpisodeAction),
    CreateEpisode(CreateEpisodeAction),
    LinkEvidence(LinkEvidenceAction),
    ClassifyDiscrepancy(ClassifyDiscrepancyAction),
    ProposeRelation(ProposeRelationAction),
    RepairGraphRegion(RepairGraphRegionAction),
    Abstain(AbstainAction),
}

impl GraphDecisionAction {
    pub const fn kind(&self) -> GraphDecisionActionKind {
        match self {
            Self::AcceptDelta(_) => GraphDecisionActionKind::AcceptDelta,
            Self::RejectDelta(_) => GraphDecisionActionKind::RejectDelta,
            Self::DeferDelta(_) => GraphDecisionActionKind::DeferDelta,
            Self::MergeDelta(_) => GraphDecisionActionKind::MergeDelta,
            Self::AttachToEpisode(_) => GraphDecisionActionKind::AttachToEpisode,
            Self::CreateEpisode(_) => GraphDecisionActionKind::CreateEpisode,
            Self::LinkEvidence(_) => GraphDecisionActionKind::LinkEvidence,
            Self::ClassifyDiscrepancy(_) => GraphDecisionActionKind::ClassifyDiscrepancy,
            Self::ProposeRelation(_) => GraphDecisionActionKind::ProposeRelation,
            Self::RepairGraphRegion(_) => GraphDecisionActionKind::RepairGraphRegion,
            Self::Abstain(_) => GraphDecisionActionKind::Abstain,
        }
    }

    pub const fn contract(&self) -> GraphDecisionActionContract {
        self.kind().contract()
    }

    pub fn header(&self) -> &GraphDecisionHeader {
        match self {
            Self::AcceptDelta(value) => &value.header,
            Self::RejectDelta(value) => &value.header,
            Self::DeferDelta(value) => &value.header,
            Self::MergeDelta(value) => &value.header,
            Self::AttachToEpisode(value) => &value.header,
            Self::CreateEpisode(value) => &value.header,
            Self::LinkEvidence(value) => &value.header,
            Self::ClassifyDiscrepancy(value) => &value.header,
            Self::ProposeRelation(value) => &value.header,
            Self::RepairGraphRegion(value) => &value.header,
            Self::Abstain(value) => &value.header,
        }
    }

    pub fn evidence(&self) -> &[GraphDecisionEvidenceRef] {
        match self {
            Self::AcceptDelta(value) => &value.evidence,
            Self::RejectDelta(value) => &value.evidence,
            Self::DeferDelta(value) => &value.evidence,
            Self::MergeDelta(value) => &value.evidence,
            Self::AttachToEpisode(value) => &value.evidence,
            Self::CreateEpisode(value) => &value.evidence,
            Self::LinkEvidence(value) => &value.evidence,
            Self::ClassifyDiscrepancy(value) => &value.evidence,
            Self::ProposeRelation(value) => &value.evidence,
            Self::RepairGraphRegion(value) => &value.evidence,
            Self::Abstain(value) => &value.evidence,
        }
    }

    pub fn validate(&self) -> Result<(), GraphDecisionValidationError> {
        self.validate_for_role(GraphDecisionValidationRole::Execution)
    }

    pub fn validate_candidate(&self) -> Result<(), GraphDecisionValidationError> {
        self.validate_for_role(GraphDecisionValidationRole::Candidate)
    }

    fn validate_for_role(
        &self,
        role: GraphDecisionValidationRole,
    ) -> Result<(), GraphDecisionValidationError> {
        let contract = self.contract();
        validate_header(self.header(), contract, role)?;
        validate_evidence(self.evidence(), self.header().decided_at, contract)?;

        match self {
            Self::AcceptDelta(value) => require_id("deltaId", &value.delta_id),
            Self::RejectDelta(value) => require_id("deltaId", &value.delta_id),
            Self::DeferDelta(value) => {
                require_id("deltaId", &value.delta_id)?;
                if value
                    .resume_after
                    .is_some_and(|time| time <= value.header.decided_at)
                {
                    return Err(GraphDecisionValidationError::InvalidTimestamp(
                        "resumeAfter",
                    ));
                }
                Ok(())
            }
            Self::MergeDelta(value) => {
                require_id("mergedDeltaId", &value.merged_delta_id)?;
                if value.delta_ids.len() < 2 {
                    return Err(GraphDecisionValidationError::InsufficientInputs("deltaIds"));
                }
                validate_unique_ids("deltaIds", &value.delta_ids)?;
                if value.delta_ids.contains(&value.merged_delta_id) {
                    return Err(GraphDecisionValidationError::DuplicateInput(
                        value.merged_delta_id.clone(),
                    ));
                }
                Ok(())
            }
            Self::AttachToEpisode(value) => validate_ids(&[
                ("eventId", &value.event_id),
                ("episodeId", &value.episode_id),
                ("candidateSetId", &value.candidate_set_id),
            ]),
            Self::CreateEpisode(value) => validate_ids(&[
                ("eventId", &value.event_id),
                ("episodeId", &value.episode_id),
                ("candidateSetId", &value.candidate_set_id),
            ]),
            Self::LinkEvidence(value) => require_id("claimId", &value.claim_id),
            Self::ClassifyDiscrepancy(value) => {
                require_id("discrepancyId", &value.discrepancy_id)?;
                if value.assertion_ids.len() < 2 {
                    return Err(GraphDecisionValidationError::InsufficientInputs(
                        "assertionIds",
                    ));
                }
                validate_unique_ids("assertionIds", &value.assertion_ids)
            }
            Self::ProposeRelation(value) => {
                validate_ids(&[
                    ("proposalId", &value.proposal_id),
                    ("sourceId", &value.source_id),
                    ("relationType", &value.relation_type),
                    ("targetId", &value.target_id),
                ])?;
                if value.source_id == value.target_id {
                    return Err(GraphDecisionValidationError::InvalidParameter("targetId"));
                }
                Ok(())
            }
            Self::RepairGraphRegion(value) => validate_ids(&[
                ("regionId", &value.region_id),
                ("repairDeltaId", &value.repair_delta_id),
            ]),
            Self::Abstain(value) => {
                require_id("taskId", &value.task_id)?;
                if let Some(candidate_set_id) = &value.candidate_set_id {
                    require_id("candidateSetId", candidate_set_id)?;
                }
                Ok(())
            }
        }
    }
}

fn validate_header(
    header: &GraphDecisionHeader,
    contract: GraphDecisionActionContract,
    role: GraphDecisionValidationRole,
) -> Result<(), GraphDecisionValidationError> {
    if header.schema_version != GRAPH_DECISION_ONTOLOGY_SCHEMA_VERSION {
        return Err(GraphDecisionValidationError::UnsupportedSchemaVersion(
            header.schema_version,
        ));
    }
    validate_ids(&[
        ("decisionId", &header.decision_id),
        ("preStateId", &header.pre_state_id),
        ("authority.authorityId", &header.authority.authority_id),
        ("authority.policyId", &header.authority.policy_id),
    ])?;
    if header.decided_at <= 0 || header.authority.issued_at <= 0 {
        return Err(GraphDecisionValidationError::InvalidTimestamp("decidedAt"));
    }
    if header.authority.issued_at > header.decided_at {
        return Err(GraphDecisionValidationError::AuthorityIssuedAfterDecision);
    }
    if !contract
        .authority_requirements
        .contains(&header.authority.kind)
    {
        return Err(GraphDecisionValidationError::AuthorityInsufficient(
            header.authority.kind,
        ));
    }
    match (&header.approval, contract.human_approval) {
        (None, GraphDecisionApprovalRequirement::Mandatory)
            if role == GraphDecisionValidationRole::Execution =>
        {
            return Err(GraphDecisionValidationError::HumanApprovalRequired)
        }
        (Some(approval), _) => {
            validate_ids(&[
                ("approval.approvalId", &approval.approval_id),
                ("approval.approverId", &approval.approver_id),
            ])?;
            if approval.approved_at <= 0 || approval.approved_at > header.decided_at {
                return Err(GraphDecisionValidationError::InvalidApprovalTimestamp);
            }
        }
        (None, _) => {}
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum GraphDecisionValidationRole {
    Candidate,
    Execution,
}

fn validate_evidence(
    evidence: &[GraphDecisionEvidenceRef],
    decided_at: i64,
    contract: GraphDecisionActionContract,
) -> Result<(), GraphDecisionValidationError> {
    if evidence.is_empty()
        && contract.evidence_requirement == GraphDecisionEvidenceRequirement::Required
    {
        return Err(GraphDecisionValidationError::EvidenceRequired);
    }
    for (index, item) in evidence.iter().enumerate() {
        validate_ids(&[
            ("evidence.evidenceId", &item.evidence_id),
            ("evidence.authorityId", &item.authority_id),
        ])?;
        if item.available_at <= 0 {
            return Err(GraphDecisionValidationError::InvalidTimestamp(
                "evidence.availableAt",
            ));
        }
        if item.available_at > decided_at {
            return Err(GraphDecisionValidationError::FutureEvidence(
                item.evidence_id.clone(),
            ));
        }
        if evidence[..index]
            .iter()
            .any(|prior| prior.evidence_id == item.evidence_id)
        {
            return Err(GraphDecisionValidationError::DuplicateEvidence(
                item.evidence_id.clone(),
            ));
        }
    }
    Ok(())
}

fn validate_ids(
    values: &[(&'static str, &CompactString)],
) -> Result<(), GraphDecisionValidationError> {
    for (field, value) in values {
        require_id(field, value)?;
    }
    Ok(())
}

fn require_id(
    field: &'static str,
    value: &CompactString,
) -> Result<(), GraphDecisionValidationError> {
    if value.trim().is_empty() {
        return Err(GraphDecisionValidationError::MissingParameter(field));
    }
    Ok(())
}

fn validate_unique_ids(
    field: &'static str,
    values: &[CompactString],
) -> Result<(), GraphDecisionValidationError> {
    for (index, value) in values.iter().enumerate() {
        require_id(field, value)?;
        if values[..index].contains(value) {
            return Err(GraphDecisionValidationError::DuplicateInput(value.clone()));
        }
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GraphDecisionValidationError {
    UnsupportedSchemaVersion(u16),
    MissingParameter(&'static str),
    InvalidParameter(&'static str),
    InvalidTimestamp(&'static str),
    AuthorityIssuedAfterDecision,
    AuthorityInsufficient(GraphDecisionAuthorityKind),
    HumanApprovalRequired,
    InvalidApprovalTimestamp,
    EvidenceRequired,
    FutureEvidence(CompactString),
    DuplicateEvidence(CompactString),
    DuplicateInput(CompactString),
    InsufficientInputs(&'static str),
}

impl GraphDecisionValidationError {
    pub const fn rejection_reason(&self) -> GraphDecisionRejectionReason {
        match self {
            Self::UnsupportedSchemaVersion(_) => {
                GraphDecisionRejectionReason::UnsupportedSchemaVersion
            }
            Self::MissingParameter(_) | Self::InsufficientInputs(_) => {
                GraphDecisionRejectionReason::MissingParameter
            }
            Self::InvalidParameter(_) => GraphDecisionRejectionReason::InvalidParameter,
            Self::InvalidTimestamp(_) | Self::AuthorityIssuedAfterDecision => {
                GraphDecisionRejectionReason::InvalidTimestamp
            }
            Self::AuthorityInsufficient(_) => GraphDecisionRejectionReason::AuthorityInsufficient,
            Self::HumanApprovalRequired => GraphDecisionRejectionReason::HumanApprovalRequired,
            Self::InvalidApprovalTimestamp => GraphDecisionRejectionReason::InvalidApproval,
            Self::EvidenceRequired => GraphDecisionRejectionReason::EvidenceRequired,
            Self::FutureEvidence(_) => GraphDecisionRejectionReason::EvidenceUnavailableAtDecision,
            Self::DuplicateEvidence(_) | Self::DuplicateInput(_) => {
                GraphDecisionRejectionReason::DuplicateInput
            }
        }
    }
}

impl fmt::Display for GraphDecisionValidationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "invalid graph decision action: {self:?}")
    }
}

impl Error for GraphDecisionValidationError {}

#[derive(Debug)]
pub enum GraphDecisionDecodeError {
    Malformed(serde_json::Error),
    Invalid(GraphDecisionValidationError),
}

impl fmt::Display for GraphDecisionDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Malformed(error) => write!(formatter, "malformed graph decision action: {error}"),
            Self::Invalid(error) => error.fmt(formatter),
        }
    }
}

impl Error for GraphDecisionDecodeError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Malformed(error) => Some(error),
            Self::Invalid(error) => Some(error),
        }
    }
}

pub fn decode_graph_decision_action(
    bytes: &[u8],
) -> Result<GraphDecisionAction, GraphDecisionDecodeError> {
    let action: GraphDecisionAction =
        serde_json::from_slice(bytes).map_err(GraphDecisionDecodeError::Malformed)?;
    action
        .validate()
        .map_err(GraphDecisionDecodeError::Invalid)?;
    Ok(action)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDecisionRewardDimension {
    EvidenceSupport,
    TemporalConsistency,
    CanonicalIdentityPreservation,
    ContradictionReduction,
    MinimalEditCost,
    HumanAcceptance,
    FutureStability,
    AbstentionCorrectness,
}

impl GraphDecisionRewardDimension {
    pub const ALL: [Self; 8] = [
        Self::EvidenceSupport,
        Self::TemporalConsistency,
        Self::CanonicalIdentityPreservation,
        Self::ContradictionReduction,
        Self::MinimalEditCost,
        Self::HumanAcceptance,
        Self::FutureStability,
        Self::AbstentionCorrectness,
    ];
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum GraphDecisionRewardSignal {
    Pending,
    Observed {
        score_micros: i32,
        observed_at: i64,
        #[serde(default)]
        evidence: Vec<GraphDecisionEvidenceRef>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GraphDecisionRewardVector {
    pub schema_version: u16,
    pub decision_id: CompactString,
    pub evidence_support: GraphDecisionRewardSignal,
    pub temporal_consistency: GraphDecisionRewardSignal,
    pub canonical_identity_preservation: GraphDecisionRewardSignal,
    pub contradiction_reduction: GraphDecisionRewardSignal,
    pub minimal_edit_cost: GraphDecisionRewardSignal,
    pub human_acceptance: GraphDecisionRewardSignal,
    pub future_stability: GraphDecisionRewardSignal,
    pub abstention_correctness: GraphDecisionRewardSignal,
}

impl GraphDecisionRewardVector {
    pub fn dimensions(&self) -> [(GraphDecisionRewardDimension, &GraphDecisionRewardSignal); 8] {
        [
            (
                GraphDecisionRewardDimension::EvidenceSupport,
                &self.evidence_support,
            ),
            (
                GraphDecisionRewardDimension::TemporalConsistency,
                &self.temporal_consistency,
            ),
            (
                GraphDecisionRewardDimension::CanonicalIdentityPreservation,
                &self.canonical_identity_preservation,
            ),
            (
                GraphDecisionRewardDimension::ContradictionReduction,
                &self.contradiction_reduction,
            ),
            (
                GraphDecisionRewardDimension::MinimalEditCost,
                &self.minimal_edit_cost,
            ),
            (
                GraphDecisionRewardDimension::HumanAcceptance,
                &self.human_acceptance,
            ),
            (
                GraphDecisionRewardDimension::FutureStability,
                &self.future_stability,
            ),
            (
                GraphDecisionRewardDimension::AbstentionCorrectness,
                &self.abstention_correctness,
            ),
        ]
    }

    pub fn validate(&self) -> Result<(), GraphDecisionRewardError> {
        if self.schema_version != GRAPH_DECISION_REWARD_SCHEMA_VERSION {
            return Err(GraphDecisionRewardError::UnsupportedSchemaVersion(
                self.schema_version,
            ));
        }
        if self.decision_id.trim().is_empty() {
            return Err(GraphDecisionRewardError::MissingDecisionId);
        }
        for (dimension, signal) in self.dimensions() {
            if let GraphDecisionRewardSignal::Observed {
                score_micros,
                observed_at,
                evidence,
            } = signal
            {
                if !(-GRAPH_DECISION_REWARD_SCALE_MICROS..=GRAPH_DECISION_REWARD_SCALE_MICROS)
                    .contains(score_micros)
                {
                    return Err(GraphDecisionRewardError::ScoreOutOfRange {
                        dimension,
                        score_micros: *score_micros,
                    });
                }
                if *observed_at <= 0 {
                    return Err(GraphDecisionRewardError::InvalidTimestamp(dimension));
                }
                validate_reward_evidence(evidence, *observed_at, dimension)?;
            }
        }
        Ok(())
    }
}

fn validate_reward_evidence(
    evidence: &[GraphDecisionEvidenceRef],
    observed_at: i64,
    dimension: GraphDecisionRewardDimension,
) -> Result<(), GraphDecisionRewardError> {
    for (index, item) in evidence.iter().enumerate() {
        if item.evidence_id.trim().is_empty() || item.authority_id.trim().is_empty() {
            return Err(GraphDecisionRewardError::MalformedEvidence(dimension));
        }
        if item.available_at <= 0 || item.available_at > observed_at {
            return Err(GraphDecisionRewardError::FutureEvidence(dimension));
        }
        if evidence[..index]
            .iter()
            .any(|prior| prior.evidence_id == item.evidence_id)
        {
            return Err(GraphDecisionRewardError::DuplicateEvidence(dimension));
        }
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GraphDecisionRewardError {
    UnsupportedSchemaVersion(u16),
    MissingDecisionId,
    ScoreOutOfRange {
        dimension: GraphDecisionRewardDimension,
        score_micros: i32,
    },
    InvalidTimestamp(GraphDecisionRewardDimension),
    MalformedEvidence(GraphDecisionRewardDimension),
    FutureEvidence(GraphDecisionRewardDimension),
    DuplicateEvidence(GraphDecisionRewardDimension),
}

impl fmt::Display for GraphDecisionRewardError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "invalid graph decision reward vector: {self:?}")
    }
}

impl Error for GraphDecisionRewardError {}

#[cfg(test)]
#[path = "graph_decision_tests.rs"]
mod tests;
