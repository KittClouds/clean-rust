use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDecisionActionKind {
    AcceptDelta,
    RejectDelta,
    DeferDelta,
    MergeDelta,
    AttachToEpisode,
    CreateEpisode,
    LinkEvidence,
    ClassifyDiscrepancy,
    ProposeRelation,
    RepairGraphRegion,
    Abstain,
}

impl GraphDecisionActionKind {
    pub const ALL: [Self; 11] = [
        Self::AcceptDelta,
        Self::RejectDelta,
        Self::DeferDelta,
        Self::MergeDelta,
        Self::AttachToEpisode,
        Self::CreateEpisode,
        Self::LinkEvidence,
        Self::ClassifyDiscrepancy,
        Self::ProposeRelation,
        Self::RepairGraphRegion,
        Self::Abstain,
    ];

    pub const fn contract(self) -> GraphDecisionActionContract {
        match self {
            Self::AcceptDelta => GraphDecisionActionContract {
                kind: self,
                required_parameters: &["header", "deltaId", "evidence"],
                legal_preconditions: &[
                    GraphDecisionPrecondition::PreStateExists,
                    GraphDecisionPrecondition::ProposalOpen,
                    GraphDecisionPrecondition::DeltaInvariantSafe,
                    GraphDecisionPrecondition::EvidenceAvailableAtDecision,
                    GraphDecisionPrecondition::ActorAuthorized,
                ],
                deterministic_postconditions: &[
                    GraphDecisionPostcondition::ProposalAccepted,
                    GraphDecisionPostcondition::TruthCommitRequired,
                ],
                graph_invariants: MUTATION_INVARIANTS,
                evidence_requirement: GraphDecisionEvidenceRequirement::Required,
                authority_requirements: HUMAN_AUTHORITIES,
                universal_rejection_reasons: COMMON_REJECTIONS,
                rejection_reasons: MUTATION_REJECTIONS,
                reversible: false,
                human_approval: GraphDecisionApprovalRequirement::Mandatory,
            },
            Self::RejectDelta => GraphDecisionActionContract {
                kind: self,
                required_parameters: &["header", "deltaId", "reason"],
                legal_preconditions: &[
                    GraphDecisionPrecondition::PreStateExists,
                    GraphDecisionPrecondition::ProposalOpen,
                    GraphDecisionPrecondition::ActorAuthorized,
                ],
                deterministic_postconditions: &[GraphDecisionPostcondition::ProposalRejected],
                graph_invariants: DECISION_INVARIANTS,
                evidence_requirement: GraphDecisionEvidenceRequirement::Optional,
                authority_requirements: HUMAN_AUTHORITIES,
                universal_rejection_reasons: COMMON_REJECTIONS,
                rejection_reasons: DISPOSITION_REJECTIONS,
                reversible: false,
                human_approval: GraphDecisionApprovalRequirement::Mandatory,
            },
            Self::DeferDelta => GraphDecisionActionContract {
                kind: self,
                required_parameters: &["header", "deltaId", "reason"],
                legal_preconditions: &[
                    GraphDecisionPrecondition::PreStateExists,
                    GraphDecisionPrecondition::ProposalOpen,
                    GraphDecisionPrecondition::ActorAuthorized,
                ],
                deterministic_postconditions: &[GraphDecisionPostcondition::ProposalDeferred],
                graph_invariants: DECISION_INVARIANTS,
                evidence_requirement: GraphDecisionEvidenceRequirement::Optional,
                authority_requirements: REVIEW_AUTHORITIES,
                universal_rejection_reasons: COMMON_REJECTIONS,
                rejection_reasons: DISPOSITION_REJECTIONS,
                reversible: true,
                human_approval: GraphDecisionApprovalRequirement::NotRequired,
            },
            Self::MergeDelta => GraphDecisionActionContract {
                kind: self,
                required_parameters: &["header", "deltaIds", "mergedDeltaId", "evidence"],
                legal_preconditions: &[
                    GraphDecisionPrecondition::PreStateExists,
                    GraphDecisionPrecondition::AllProposalsOpen,
                    GraphDecisionPrecondition::DeltaInvariantSafe,
                    GraphDecisionPrecondition::EvidenceAvailableAtDecision,
                    GraphDecisionPrecondition::ActorAuthorized,
                ],
                deterministic_postconditions: &[
                    GraphDecisionPostcondition::ProposalsMerged,
                    GraphDecisionPostcondition::MergedDeltaPending,
                ],
                graph_invariants: MUTATION_INVARIANTS,
                evidence_requirement: GraphDecisionEvidenceRequirement::Required,
                authority_requirements: HUMAN_AUTHORITIES,
                universal_rejection_reasons: COMMON_REJECTIONS,
                rejection_reasons: MUTATION_REJECTIONS,
                reversible: false,
                human_approval: GraphDecisionApprovalRequirement::Mandatory,
            },
            Self::AttachToEpisode => GraphDecisionActionContract {
                kind: self,
                required_parameters: &[
                    "header",
                    "eventId",
                    "episodeId",
                    "candidateSetId",
                    "evidence",
                ],
                legal_preconditions: &[
                    GraphDecisionPrecondition::PreStateExists,
                    GraphDecisionPrecondition::TargetExists,
                    GraphDecisionPrecondition::CandidateSetContainsTarget,
                    GraphDecisionPrecondition::CandidateSetContainsNoFutureFacts,
                    GraphDecisionPrecondition::EpisodeScopeCompatible,
                    GraphDecisionPrecondition::ActorAuthorized,
                ],
                deterministic_postconditions: &[GraphDecisionPostcondition::EventAttachedToEpisode],
                graph_invariants: EPISODE_INVARIANTS,
                evidence_requirement: GraphDecisionEvidenceRequirement::Required,
                authority_requirements: HUMAN_AUTHORITIES,
                universal_rejection_reasons: COMMON_REJECTIONS,
                rejection_reasons: EPISODE_REJECTIONS,
                reversible: false,
                human_approval: GraphDecisionApprovalRequirement::Mandatory,
            },
            Self::CreateEpisode => GraphDecisionActionContract {
                kind: self,
                required_parameters: &[
                    "header",
                    "eventId",
                    "episodeId",
                    "candidateSetId",
                    "evidence",
                ],
                legal_preconditions: &[
                    GraphDecisionPrecondition::PreStateExists,
                    GraphDecisionPrecondition::CandidateSetContainsNoFutureFacts,
                    GraphDecisionPrecondition::CanonicalIdAvailable,
                    GraphDecisionPrecondition::ActorAuthorized,
                ],
                deterministic_postconditions: &[
                    GraphDecisionPostcondition::EpisodeCreated,
                    GraphDecisionPostcondition::EventAttachedToEpisode,
                ],
                graph_invariants: EPISODE_INVARIANTS,
                evidence_requirement: GraphDecisionEvidenceRequirement::Required,
                authority_requirements: HUMAN_AUTHORITIES,
                universal_rejection_reasons: COMMON_REJECTIONS,
                rejection_reasons: EPISODE_REJECTIONS,
                reversible: false,
                human_approval: GraphDecisionApprovalRequirement::Mandatory,
            },
            Self::LinkEvidence => GraphDecisionActionContract {
                kind: self,
                required_parameters: &["header", "claimId", "evidence"],
                legal_preconditions: &[
                    GraphDecisionPrecondition::PreStateExists,
                    GraphDecisionPrecondition::TargetExists,
                    GraphDecisionPrecondition::EvidenceAvailableAtDecision,
                    GraphDecisionPrecondition::ActorAuthorized,
                ],
                deterministic_postconditions: &[GraphDecisionPostcondition::EvidenceLinked],
                graph_invariants: DECISION_INVARIANTS,
                evidence_requirement: GraphDecisionEvidenceRequirement::Required,
                authority_requirements: EVIDENCE_AUTHORITIES,
                universal_rejection_reasons: COMMON_REJECTIONS,
                rejection_reasons: EVIDENCE_REJECTIONS,
                reversible: false,
                human_approval: GraphDecisionApprovalRequirement::NotRequired,
            },
            Self::ClassifyDiscrepancy => GraphDecisionActionContract {
                kind: self,
                required_parameters: &[
                    "header",
                    "discrepancyId",
                    "assertionIds",
                    "classification",
                    "evidence",
                ],
                legal_preconditions: &[
                    GraphDecisionPrecondition::PreStateExists,
                    GraphDecisionPrecondition::DiscrepancyOpen,
                    GraphDecisionPrecondition::EvidenceAvailableAtDecision,
                    GraphDecisionPrecondition::ActorAuthorized,
                ],
                deterministic_postconditions: &[GraphDecisionPostcondition::DiscrepancyClassified],
                graph_invariants: DECISION_INVARIANTS,
                evidence_requirement: GraphDecisionEvidenceRequirement::Required,
                authority_requirements: HUMAN_AUTHORITIES,
                universal_rejection_reasons: COMMON_REJECTIONS,
                rejection_reasons: DISCREPANCY_REJECTIONS,
                reversible: false,
                human_approval: GraphDecisionApprovalRequirement::Mandatory,
            },
            Self::ProposeRelation => GraphDecisionActionContract {
                kind: self,
                required_parameters: &[
                    "header",
                    "proposalId",
                    "sourceId",
                    "relationType",
                    "targetId",
                    "evidence",
                ],
                legal_preconditions: &[
                    GraphDecisionPrecondition::PreStateExists,
                    GraphDecisionPrecondition::EndpointsExist,
                    GraphDecisionPrecondition::RelationAbsent,
                    GraphDecisionPrecondition::EvidenceAvailableAtDecision,
                    GraphDecisionPrecondition::ActorAuthorized,
                ],
                deterministic_postconditions: &[
                    GraphDecisionPostcondition::RelationProposalCreated,
                ],
                graph_invariants: PROPOSAL_INVARIANTS,
                evidence_requirement: GraphDecisionEvidenceRequirement::Required,
                authority_requirements: PROPOSAL_AUTHORITIES,
                universal_rejection_reasons: COMMON_REJECTIONS,
                rejection_reasons: PROPOSAL_REJECTIONS,
                reversible: true,
                human_approval: GraphDecisionApprovalRequirement::NotRequired,
            },
            Self::RepairGraphRegion => GraphDecisionActionContract {
                kind: self,
                required_parameters: &["header", "regionId", "repairDeltaId", "evidence"],
                legal_preconditions: &[
                    GraphDecisionPrecondition::PreStateExists,
                    GraphDecisionPrecondition::RegionRevisionMatches,
                    GraphDecisionPrecondition::DeltaInvariantSafe,
                    GraphDecisionPrecondition::EvidenceAvailableAtDecision,
                    GraphDecisionPrecondition::ActorAuthorized,
                ],
                deterministic_postconditions: &[
                    GraphDecisionPostcondition::RegionRepairAccepted,
                    GraphDecisionPostcondition::TruthCommitRequired,
                ],
                graph_invariants: MUTATION_INVARIANTS,
                evidence_requirement: GraphDecisionEvidenceRequirement::Required,
                authority_requirements: HUMAN_AUTHORITIES,
                universal_rejection_reasons: COMMON_REJECTIONS,
                rejection_reasons: MUTATION_REJECTIONS,
                reversible: false,
                human_approval: GraphDecisionApprovalRequirement::Mandatory,
            },
            Self::Abstain => GraphDecisionActionContract {
                kind: self,
                required_parameters: &["header", "taskId", "reason"],
                legal_preconditions: &[
                    GraphDecisionPrecondition::PreStateExists,
                    GraphDecisionPrecondition::ActorAuthorized,
                ],
                deterministic_postconditions: &[GraphDecisionPostcondition::AbstentionRecorded],
                graph_invariants: DECISION_INVARIANTS,
                evidence_requirement: GraphDecisionEvidenceRequirement::Optional,
                authority_requirements: ALL_AUTHORITIES,
                universal_rejection_reasons: COMMON_REJECTIONS,
                rejection_reasons: ABSTENTION_REJECTIONS,
                reversible: true,
                human_approval: GraphDecisionApprovalRequirement::NotRequired,
            },
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDecisionAuthorityKind {
    Compiler,
    Policy,
    EvidenceCurator,
    Operator,
    AuthoritativeCommitter,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDecisionEvidenceRequirement {
    Required,
    Optional,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDecisionApprovalRequirement {
    Mandatory,
    NotRequired,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDecisionPrecondition {
    PreStateExists,
    TargetExists,
    EndpointsExist,
    ProposalOpen,
    AllProposalsOpen,
    DeltaInvariantSafe,
    EvidenceAvailableAtDecision,
    CandidateSetContainsTarget,
    CandidateSetContainsNoFutureFacts,
    EpisodeScopeCompatible,
    CanonicalIdAvailable,
    DiscrepancyOpen,
    RelationAbsent,
    RegionRevisionMatches,
    ActorAuthorized,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDecisionPostcondition {
    ProposalAccepted,
    ProposalRejected,
    ProposalDeferred,
    ProposalsMerged,
    MergedDeltaPending,
    TruthCommitRequired,
    EventAttachedToEpisode,
    EpisodeCreated,
    EvidenceLinked,
    DiscrepancyClassified,
    RelationProposalCreated,
    RegionRepairAccepted,
    AbstentionRecorded,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDecisionInvariant {
    PreStateImmutable,
    DecisionAppendOnly,
    EvidenceLineagePreserved,
    NoFutureInformation,
    StableCanonicalIds,
    NoOrphanEdges,
    NoDuplicateActiveRelation,
    EpisodeMembershipUniqueAtDecisionTime,
    TruthChangesRequireCommit,
    CandidateSetImmutable,
    RewardVectorNotScalarized,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphDecisionRejectionReason {
    UnsupportedSchemaVersion,
    MalformedAction,
    MissingParameter,
    InvalidParameter,
    InvalidTimestamp,
    MissingPreState,
    MissingTarget,
    ProposalNotOpen,
    ConflictingDisposition,
    DuplicateInput,
    EvidenceRequired,
    EvidenceUnavailableAtDecision,
    AuthorityMissing,
    AuthorityInsufficient,
    HumanApprovalRequired,
    InvalidApproval,
    CandidateNotInSet,
    CandidateSetContainsFutureInformation,
    EpisodeScopeMismatch,
    CanonicalIdUnavailable,
    DiscrepancyNotOpen,
    RelationAlreadyActive,
    RegionRevisionMismatch,
    GraphInvariantViolation,
    AbstentionNotJustified,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDecisionActionContract {
    pub kind: GraphDecisionActionKind,
    pub required_parameters: &'static [&'static str],
    pub legal_preconditions: &'static [GraphDecisionPrecondition],
    pub deterministic_postconditions: &'static [GraphDecisionPostcondition],
    pub graph_invariants: &'static [GraphDecisionInvariant],
    pub evidence_requirement: GraphDecisionEvidenceRequirement,
    pub authority_requirements: &'static [GraphDecisionAuthorityKind],
    pub universal_rejection_reasons: &'static [GraphDecisionRejectionReason],
    pub rejection_reasons: &'static [GraphDecisionRejectionReason],
    pub reversible: bool,
    pub human_approval: GraphDecisionApprovalRequirement,
}

const HUMAN_AUTHORITIES: &[GraphDecisionAuthorityKind] = &[
    GraphDecisionAuthorityKind::Operator,
    GraphDecisionAuthorityKind::AuthoritativeCommitter,
];
const REVIEW_AUTHORITIES: &[GraphDecisionAuthorityKind] = &[
    GraphDecisionAuthorityKind::Policy,
    GraphDecisionAuthorityKind::Operator,
    GraphDecisionAuthorityKind::AuthoritativeCommitter,
];
const EVIDENCE_AUTHORITIES: &[GraphDecisionAuthorityKind] = &[
    GraphDecisionAuthorityKind::Compiler,
    GraphDecisionAuthorityKind::EvidenceCurator,
    GraphDecisionAuthorityKind::Operator,
    GraphDecisionAuthorityKind::AuthoritativeCommitter,
];
const PROPOSAL_AUTHORITIES: &[GraphDecisionAuthorityKind] = &[
    GraphDecisionAuthorityKind::Compiler,
    GraphDecisionAuthorityKind::Policy,
    GraphDecisionAuthorityKind::Operator,
    GraphDecisionAuthorityKind::AuthoritativeCommitter,
];
const ALL_AUTHORITIES: &[GraphDecisionAuthorityKind] = &[
    GraphDecisionAuthorityKind::Compiler,
    GraphDecisionAuthorityKind::Policy,
    GraphDecisionAuthorityKind::EvidenceCurator,
    GraphDecisionAuthorityKind::Operator,
    GraphDecisionAuthorityKind::AuthoritativeCommitter,
];

const DECISION_INVARIANTS: &[GraphDecisionInvariant] = &[
    GraphDecisionInvariant::PreStateImmutable,
    GraphDecisionInvariant::DecisionAppendOnly,
    GraphDecisionInvariant::EvidenceLineagePreserved,
    GraphDecisionInvariant::NoFutureInformation,
    GraphDecisionInvariant::RewardVectorNotScalarized,
];
const MUTATION_INVARIANTS: &[GraphDecisionInvariant] = &[
    GraphDecisionInvariant::PreStateImmutable,
    GraphDecisionInvariant::DecisionAppendOnly,
    GraphDecisionInvariant::EvidenceLineagePreserved,
    GraphDecisionInvariant::NoFutureInformation,
    GraphDecisionInvariant::StableCanonicalIds,
    GraphDecisionInvariant::NoOrphanEdges,
    GraphDecisionInvariant::TruthChangesRequireCommit,
    GraphDecisionInvariant::RewardVectorNotScalarized,
];
const EPISODE_INVARIANTS: &[GraphDecisionInvariant] = &[
    GraphDecisionInvariant::PreStateImmutable,
    GraphDecisionInvariant::DecisionAppendOnly,
    GraphDecisionInvariant::EvidenceLineagePreserved,
    GraphDecisionInvariant::NoFutureInformation,
    GraphDecisionInvariant::StableCanonicalIds,
    GraphDecisionInvariant::EpisodeMembershipUniqueAtDecisionTime,
    GraphDecisionInvariant::CandidateSetImmutable,
    GraphDecisionInvariant::TruthChangesRequireCommit,
    GraphDecisionInvariant::RewardVectorNotScalarized,
];
const PROPOSAL_INVARIANTS: &[GraphDecisionInvariant] = &[
    GraphDecisionInvariant::PreStateImmutable,
    GraphDecisionInvariant::DecisionAppendOnly,
    GraphDecisionInvariant::EvidenceLineagePreserved,
    GraphDecisionInvariant::NoFutureInformation,
    GraphDecisionInvariant::StableCanonicalIds,
    GraphDecisionInvariant::NoOrphanEdges,
    GraphDecisionInvariant::NoDuplicateActiveRelation,
    GraphDecisionInvariant::RewardVectorNotScalarized,
];

const COMMON_REJECTIONS: &[GraphDecisionRejectionReason] = &[
    GraphDecisionRejectionReason::UnsupportedSchemaVersion,
    GraphDecisionRejectionReason::MalformedAction,
    GraphDecisionRejectionReason::MissingParameter,
    GraphDecisionRejectionReason::InvalidParameter,
    GraphDecisionRejectionReason::InvalidTimestamp,
    GraphDecisionRejectionReason::MissingPreState,
    GraphDecisionRejectionReason::AuthorityMissing,
    GraphDecisionRejectionReason::AuthorityInsufficient,
    GraphDecisionRejectionReason::HumanApprovalRequired,
    GraphDecisionRejectionReason::InvalidApproval,
];
const DISPOSITION_REJECTIONS: &[GraphDecisionRejectionReason] = &[
    GraphDecisionRejectionReason::ProposalNotOpen,
    GraphDecisionRejectionReason::ConflictingDisposition,
    GraphDecisionRejectionReason::AuthorityInsufficient,
    GraphDecisionRejectionReason::HumanApprovalRequired,
    GraphDecisionRejectionReason::InvalidApproval,
];
const MUTATION_REJECTIONS: &[GraphDecisionRejectionReason] = &[
    GraphDecisionRejectionReason::ProposalNotOpen,
    GraphDecisionRejectionReason::EvidenceRequired,
    GraphDecisionRejectionReason::EvidenceUnavailableAtDecision,
    GraphDecisionRejectionReason::GraphInvariantViolation,
    GraphDecisionRejectionReason::AuthorityInsufficient,
    GraphDecisionRejectionReason::HumanApprovalRequired,
    GraphDecisionRejectionReason::InvalidApproval,
];
const EPISODE_REJECTIONS: &[GraphDecisionRejectionReason] = &[
    GraphDecisionRejectionReason::MissingTarget,
    GraphDecisionRejectionReason::CandidateNotInSet,
    GraphDecisionRejectionReason::CandidateSetContainsFutureInformation,
    GraphDecisionRejectionReason::EpisodeScopeMismatch,
    GraphDecisionRejectionReason::CanonicalIdUnavailable,
    GraphDecisionRejectionReason::EvidenceRequired,
    GraphDecisionRejectionReason::AuthorityInsufficient,
    GraphDecisionRejectionReason::HumanApprovalRequired,
];
const EVIDENCE_REJECTIONS: &[GraphDecisionRejectionReason] = &[
    GraphDecisionRejectionReason::MissingTarget,
    GraphDecisionRejectionReason::EvidenceRequired,
    GraphDecisionRejectionReason::EvidenceUnavailableAtDecision,
    GraphDecisionRejectionReason::AuthorityInsufficient,
];
const DISCREPANCY_REJECTIONS: &[GraphDecisionRejectionReason] = &[
    GraphDecisionRejectionReason::DiscrepancyNotOpen,
    GraphDecisionRejectionReason::EvidenceRequired,
    GraphDecisionRejectionReason::EvidenceUnavailableAtDecision,
    GraphDecisionRejectionReason::AuthorityInsufficient,
    GraphDecisionRejectionReason::HumanApprovalRequired,
];
const PROPOSAL_REJECTIONS: &[GraphDecisionRejectionReason] = &[
    GraphDecisionRejectionReason::MissingTarget,
    GraphDecisionRejectionReason::RelationAlreadyActive,
    GraphDecisionRejectionReason::EvidenceRequired,
    GraphDecisionRejectionReason::EvidenceUnavailableAtDecision,
    GraphDecisionRejectionReason::AuthorityInsufficient,
];
const ABSTENTION_REJECTIONS: &[GraphDecisionRejectionReason] = &[
    GraphDecisionRejectionReason::MissingParameter,
    GraphDecisionRejectionReason::AuthorityInsufficient,
    GraphDecisionRejectionReason::AbstentionNotJustified,
];
