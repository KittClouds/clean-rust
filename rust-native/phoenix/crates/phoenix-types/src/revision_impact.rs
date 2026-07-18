use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use compact_str::CompactString;
use serde::{Deserialize, Serialize};

use crate::EntityId;

pub const REVISION_IMPACT_CONTRACT_SCHEMA_VERSION: u16 = 1;
pub const REVISION_IMPACT_GOLD_CORPUS_SCHEMA: &str = "phoenix-revision-impact-gold/v1";
pub const REVISION_IMPACT_GOLD_CASE_COUNT: usize = 7;

macro_rules! compact_id {
    ($name:ident) => {
        #[derive(
            Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize,
        )]
        #[serde(transparent)]
        pub struct $name(pub CompactString);

        impl From<&str> for $name {
            fn from(value: &str) -> Self {
                Self(value.into())
            }
        }

        impl From<String> for $name {
            fn from(value: String) -> Self {
                Self(value.into())
            }
        }
    };
}

compact_id!(FactId);
compact_id!(SceneId);
compact_id!(GoldCaseId);
compact_id!(RepairExpectationId);

#[derive(
    Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize,
)]
#[serde(transparent)]
pub struct StoryTime(pub i64);

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StoryInterval {
    pub valid_from: StoryTime,
    pub valid_to_exclusive: Option<StoryTime>,
}

impl StoryInterval {
    pub fn is_well_formed(self) -> bool {
        self.valid_to_exclusive
            .is_none_or(|end| self.valid_from < end)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct StateKind(pub CompactString);

impl From<&str> for StateKind {
    fn from(value: &str) -> Self {
        Self(value.into())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    content = "value",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum FactValue {
    Boolean(bool),
    Integer(i64),
    Text(CompactString),
    Entity(EntityId),
    DurationMinutes(i64),
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum StoryMutation {
    RetractFact {
        fact_id: FactId,
    },
    SupersedeFact {
        fact_id: FactId,
        replacement: FactValue,
        valid_from: StoryTime,
    },
    ShiftValidity {
        fact_id: FactId,
        new_interval: StoryInterval,
    },
    ChangeState {
        subject_id: EntityId,
        state_kind: StateKind,
        replacement: FactValue,
        valid_from: StoryTime,
    },
}

impl StoryMutation {
    fn intervals_are_well_formed(&self) -> bool {
        match self {
            Self::ShiftValidity { new_interval, .. } => new_interval.is_well_formed(),
            _ => true,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DependencyClass {
    HardRequirement,
    DefeasibleSupport,
    WeakAssociation,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ConstraintKind {
    RequiresKnowledge,
    RequiresWitness,
    RequiresAlive,
    RequiresPossession,
    RequiresReachability,
    RequiresState,
    RequiresTemporalOrder,
    MutuallyExclusiveStates,
    CausalSupport,
    Motivation,
    Foreshadowing,
    Mention,
    ThematicEcho,
}

impl ConstraintKind {
    pub const fn dependency_class(self) -> DependencyClass {
        match self {
            Self::RequiresKnowledge
            | Self::RequiresWitness
            | Self::RequiresAlive
            | Self::RequiresPossession
            | Self::RequiresReachability
            | Self::RequiresState
            | Self::RequiresTemporalOrder
            | Self::MutuallyExclusiveStates => DependencyClass::HardRequirement,
            Self::CausalSupport | Self::Motivation | Self::Foreshadowing => {
                DependencyClass::DefeasibleSupport
            }
            Self::Mention | Self::ThematicEcho => DependencyClass::WeakAssociation,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ImpactClassification {
    Broken,
    Suspicious,
    Unknown,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoveragePlane {
    Identity,
    Temporal,
    Belief,
    Lifecycle,
    Possession,
    Location,
    State,
    Relationship,
    Capability,
    Causal,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RepairTemplateKind {
    RestoreOriginalFact,
    ShiftReveal,
    DowngradeKnowledge,
    ReviseRequirementBearingStatement,
    MoveStateTransition,
    InsertIntermediateTravelEvent,
    TransferPossessionEarlier,
    SplitEvent,
    AddAlternativeCause,
    ReassignCausalAttribution,
    RebindActionToPriorRecord,
    ReclassifyAssertionAsDeception,
    AddCostedCapabilityOverdraw,
    AddConstrainedTravelMethod,
    ReclassifyAccessAsEspionage,
    RebindPossessionDependentAction,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GoldMutationFamily {
    DelayedReveal,
    EarlierDeath,
    ChangedWitness,
    ChangedPowerLimitation,
    ChangedTravelDuration,
    RemovedRelationship,
    ChangedPossession,
}

impl GoldMutationFamily {
    pub const ALL: [Self; REVISION_IMPACT_GOLD_CASE_COUNT] = [
        Self::DelayedReveal,
        Self::EarlierDeath,
        Self::ChangedWitness,
        Self::ChangedPowerLimitation,
        Self::ChangedTravelDuration,
        Self::RemovedRelationship,
        Self::ChangedPossession,
    ];

    fn accepts(self, mutation: &StoryMutation) -> bool {
        matches!(
            (self, mutation),
            (Self::DelayedReveal, StoryMutation::ShiftValidity { .. })
                | (Self::EarlierDeath, StoryMutation::ChangeState { .. })
                | (Self::ChangedWitness, StoryMutation::SupersedeFact { .. })
                | (
                    Self::ChangedPowerLimitation,
                    StoryMutation::SupersedeFact { .. } | StoryMutation::ChangeState { .. }
                )
                | (
                    Self::ChangedTravelDuration,
                    StoryMutation::SupersedeFact { .. }
                )
                | (Self::RemovedRelationship, StoryMutation::ChangeState { .. })
                | (Self::ChangedPossession, StoryMutation::ChangeState { .. })
        )
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GoldReviewStatus {
    PendingAuthorReview,
    AuthorReviewed,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GoldExpectedImpact {
    pub scene_id: SceneId,
    pub classification: ImpactClassification,
    pub constraint_kinds: Vec<ConstraintKind>,
    pub rationale: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GoldExpectedUnknown {
    pub scene_id: SceneId,
    pub missing_planes: Vec<CoveragePlane>,
    pub rationale: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GoldRepairExpectation {
    pub repair_id: RepairExpectationId,
    pub kind: RepairTemplateKind,
    pub target_scene_ids: Vec<SceneId>,
    pub rationale: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionImpactGoldCase {
    pub case_id: GoldCaseId,
    pub family: GoldMutationFamily,
    pub title: CompactString,
    pub mutation: StoryMutation,
    pub expected_impacts: Vec<GoldExpectedImpact>,
    pub expected_unknowns: Vec<GoldExpectedUnknown>,
    pub reasonable_repairs: Vec<GoldRepairExpectation>,
    pub review_status: GoldReviewStatus,
    pub reviewed_by: Option<CompactString>,
    pub reviewed_at_unix_ms: Option<i64>,
}

impl RevisionImpactGoldCase {
    pub fn is_author_reviewed(&self) -> bool {
        self.review_status == GoldReviewStatus::AuthorReviewed
            && self.reviewed_by.as_ref().is_some_and(|id| !id.is_empty())
            && self.reviewed_at_unix_ms.is_some()
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevisionImpactGoldCorpus {
    pub schema_version: CompactString,
    pub contract_schema_version: u16,
    pub cases: Vec<RevisionImpactGoldCase>,
}

impl RevisionImpactGoldCorpus {
    pub fn validate(&self) -> Result<(), RevisionImpactContractError> {
        if self.schema_version.as_str() != REVISION_IMPACT_GOLD_CORPUS_SCHEMA
            || self.contract_schema_version != REVISION_IMPACT_CONTRACT_SCHEMA_VERSION
        {
            return Err(RevisionImpactContractError::SchemaMismatch);
        }
        if self.cases.len() != REVISION_IMPACT_GOLD_CASE_COUNT {
            return Err(RevisionImpactContractError::CaseCount(self.cases.len()));
        }

        let mut case_ids = BTreeSet::new();
        let mut families = BTreeSet::new();
        for case in &self.cases {
            if !case_ids.insert(case.case_id.0.clone()) {
                return Err(RevisionImpactContractError::DuplicateCaseId(
                    case.case_id.0.clone(),
                ));
            }
            if !families.insert(case.family) {
                return Err(RevisionImpactContractError::DuplicateFamily(case.family));
            }
            validate_case(case)?;
        }
        for family in GoldMutationFamily::ALL {
            if !families.contains(&family) {
                return Err(RevisionImpactContractError::MissingFamily(family));
            }
        }
        Ok(())
    }

    pub fn author_review_complete(&self) -> bool {
        self.cases
            .iter()
            .all(RevisionImpactGoldCase::is_author_reviewed)
    }

    pub fn pending_author_review_ids(&self) -> Vec<GoldCaseId> {
        self.cases
            .iter()
            .filter(|case| !case.is_author_reviewed())
            .map(|case| case.case_id.clone())
            .collect()
    }
}

fn validate_case(case: &RevisionImpactGoldCase) -> Result<(), RevisionImpactContractError> {
    if !case.family.accepts(&case.mutation) {
        return Err(RevisionImpactContractError::MutationFamilyMismatch(
            case.case_id.0.clone(),
        ));
    }
    if !case.mutation.intervals_are_well_formed() {
        return Err(RevisionImpactContractError::InvalidInterval(
            case.case_id.0.clone(),
        ));
    }
    if case.expected_impacts.is_empty() {
        return Err(RevisionImpactContractError::MissingExpectedImpact(
            case.case_id.0.clone(),
        ));
    }
    if !case
        .expected_impacts
        .iter()
        .any(|impact| impact.classification == ImpactClassification::Broken)
    {
        return Err(RevisionImpactContractError::MissingBrokenImpact(
            case.case_id.0.clone(),
        ));
    }
    for impact in &case.expected_impacts {
        if impact.classification == ImpactClassification::Unknown {
            return Err(RevisionImpactContractError::UnknownInImpactList(
                case.case_id.0.clone(),
            ));
        }
        if impact.classification == ImpactClassification::Broken
            && !impact
                .constraint_kinds
                .iter()
                .any(|kind| kind.dependency_class() == DependencyClass::HardRequirement)
        {
            return Err(RevisionImpactContractError::BrokenWithoutHardConstraint(
                case.case_id.0.clone(),
            ));
        }
    }
    if case.expected_unknowns.is_empty() {
        return Err(RevisionImpactContractError::MissingExpectedUnknown(
            case.case_id.0.clone(),
        ));
    }
    if case
        .expected_unknowns
        .iter()
        .any(|unknown| unknown.missing_planes.is_empty())
    {
        return Err(RevisionImpactContractError::UnknownWithoutCoverageGap(
            case.case_id.0.clone(),
        ));
    }
    if case.reasonable_repairs.is_empty() {
        return Err(RevisionImpactContractError::MissingRepair(
            case.case_id.0.clone(),
        ));
    }
    match case.review_status {
        GoldReviewStatus::PendingAuthorReview
            if case.reviewed_by.is_some() || case.reviewed_at_unix_ms.is_some() =>
        {
            Err(RevisionImpactContractError::InvalidReviewMetadata(
                case.case_id.0.clone(),
            ))
        }
        GoldReviewStatus::AuthorReviewed if !case.is_author_reviewed() => Err(
            RevisionImpactContractError::InvalidReviewMetadata(case.case_id.0.clone()),
        ),
        _ => Ok(()),
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RevisionImpactContractError {
    SchemaMismatch,
    CaseCount(usize),
    DuplicateCaseId(CompactString),
    DuplicateFamily(GoldMutationFamily),
    MissingFamily(GoldMutationFamily),
    MutationFamilyMismatch(CompactString),
    InvalidInterval(CompactString),
    MissingExpectedImpact(CompactString),
    MissingBrokenImpact(CompactString),
    UnknownInImpactList(CompactString),
    BrokenWithoutHardConstraint(CompactString),
    MissingExpectedUnknown(CompactString),
    UnknownWithoutCoverageGap(CompactString),
    MissingRepair(CompactString),
    InvalidReviewMetadata(CompactString),
}

impl fmt::Display for RevisionImpactContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "revision impact contract validation failed: {self:?}"
        )
    }
}

impl Error for RevisionImpactContractError {}

#[cfg(test)]
#[path = "revision_impact_tests.rs"]
mod tests;
