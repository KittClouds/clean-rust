use std::collections::{BTreeMap, BTreeSet};

use compact_str::CompactString;
use phoenix_types::{
    GoldCaseId, GraphTruthDigest, RepairTemplateKind, SceneId, REVISION_IMPACT_GOLD_CASE_COUNT,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{
    EditCost, EditId, EvidenceRef, GraphEditOperation, ProposedEdit, RepairPrecondition,
    RevisionImpactReport, DETERMINISTIC_REPAIR_SCHEMA,
};

pub const AUTHOR_REPAIR_DIRECTIVE_SCHEMA: &str = "phoenix.author-repair-directives/v1";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuthorRepairDirective {
    pub case_id: GoldCaseId,
    pub directive_id: CompactString,
    pub template: RepairTemplateKind,
    pub target_scene_ids: Vec<SceneId>,
    pub intent: CompactString,
    pub required_outcomes: Vec<CompactString>,
    pub rejected_templates: Vec<RepairTemplateKind>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuthorRepairDirectiveCorpus {
    pub schema_version: CompactString,
    pub source_review_token: CompactString,
    pub reviewed_by: CompactString,
    pub reviewed_at_unix_ms: i64,
    pub cases: Vec<AuthorRepairDirective>,
}

impl AuthorRepairDirectiveCorpus {
    pub fn validate(&self) -> Result<(), AuthorRepairDirectiveError> {
        if self.schema_version.as_str() != AUTHOR_REPAIR_DIRECTIVE_SCHEMA {
            return Err(AuthorRepairDirectiveError::SchemaMismatch);
        }
        if self.source_review_token.is_empty()
            || self.reviewed_by.is_empty()
            || self.reviewed_at_unix_ms <= 0
        {
            return Err(AuthorRepairDirectiveError::MissingReviewAuthority);
        }
        if self.cases.len() != REVISION_IMPACT_GOLD_CASE_COUNT {
            return Err(AuthorRepairDirectiveError::CaseCount(self.cases.len()));
        }
        let mut case_ids = BTreeSet::new();
        let mut directive_ids = BTreeSet::new();
        for directive in &self.cases {
            if !case_ids.insert(directive.case_id.0.clone()) {
                return Err(AuthorRepairDirectiveError::DuplicateCase(
                    directive.case_id.0.clone(),
                ));
            }
            if !directive_ids.insert(directive.directive_id.clone()) {
                return Err(AuthorRepairDirectiveError::DuplicateDirective(
                    directive.directive_id.clone(),
                ));
            }
            validate_directive(directive)?;
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<GraphTruthDigest, serde_json::Error> {
        Ok(GraphTruthDigest(
            *blake3::hash(&serde_json::to_vec(self)?).as_bytes(),
        ))
    }

    pub fn for_case(&self, case_id: &str) -> Option<&AuthorRepairDirective> {
        self.cases
            .iter()
            .find(|directive| directive.case_id.0 == case_id)
    }
}

pub struct AuthorDirectiveGenerationInput<'a> {
    pub report: &'a RevisionImpactReport,
    pub directives: &'a [AuthorRepairDirective],
    pub author_locked_ids: &'a BTreeSet<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuthorDirectiveGenerationReceipt {
    pub schema: CompactString,
    pub directive_count: usize,
    pub emitted_candidates: usize,
    pub skipped_locked_directive_ids: Vec<CompactString>,
    pub deterministic: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuthorDirectiveGenerationResult {
    pub candidates: Vec<ProposedEdit>,
    pub receipt: AuthorDirectiveGenerationReceipt,
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum AuthorRepairDirectiveError {
    #[error("author repair directive schema mismatch")]
    SchemaMismatch,
    #[error("author repair directive review authority is incomplete")]
    MissingReviewAuthority,
    #[error("author repair directive corpus contains {0} cases")]
    CaseCount(usize),
    #[error("duplicate author repair case {0}")]
    DuplicateCase(CompactString),
    #[error("duplicate author repair directive {0}")]
    DuplicateDirective(CompactString),
    #[error("author repair directive {0} is incomplete")]
    IncompleteDirective(CompactString),
    #[error("author repair directive {0} uses a non-author template")]
    InvalidTemplate(CompactString),
    #[error("author repair directive {0} rejects its preferred template")]
    RejectsPreferredTemplate(CompactString),
}

pub fn generate_author_directed_repairs(
    input: AuthorDirectiveGenerationInput<'_>,
) -> AuthorDirectiveGenerationResult {
    let mut candidates = BTreeMap::<EditId, ProposedEdit>::new();
    let mut skipped_locked = Vec::new();
    for directive in input.directives {
        let target_ids = directive
            .target_scene_ids
            .iter()
            .map(|scene| scene.0.clone())
            .collect::<Vec<_>>();
        if target_ids
            .iter()
            .any(|target| input.author_locked_ids.contains(target))
        {
            skipped_locked.push(directive.directive_id.clone());
            continue;
        }
        let constraints = constraints_for_targets(input.report, &target_ids);
        let evidence = evidence_for_constraints(input.report, &constraints);
        let mut preconditions = target_ids
            .iter()
            .cloned()
            .map(|target_id| RepairPrecondition::AuthorUnlocked { target_id })
            .collect::<Vec<_>>();
        preconditions.extend(
            constraints
                .iter()
                .cloned()
                .map(|constraint_id| RepairPrecondition::ConstraintExists { constraint_id }),
        );
        preconditions.extend(
            evidence
                .iter()
                .map(|anchor| RepairPrecondition::EvidenceAnchored {
                    evidence_id: anchor.evidence_id.clone(),
                }),
        );
        let edit = ProposedEdit {
            schema: DETERMINISTIC_REPAIR_SCHEMA.into(),
            edit_id: EditId(directive.directive_id.clone()),
            template: directive.template,
            target_ids,
            operations: vec![GraphEditOperation::ApplyAuthorDirective {
                directive_id: directive.directive_id.clone(),
                intent: directive.intent.clone(),
                required_outcomes: directive.required_outcomes.clone(),
            }],
            preconditions,
            source_constraints: constraints,
            evidence,
            source_bindings: Vec::new(),
            preserves_mutation: true,
            estimated_cost: EditCost {
                scenes_changed: directive.target_scene_ids.len().min(u16::MAX as usize) as u16,
                evidence_spans_changed: 0,
                semantic_distance_millis: 300,
                rollback_penalty_millis: 0,
            },
        };
        candidates.insert(edit.edit_id.clone(), edit);
    }
    let mut candidates = candidates.into_values().collect::<Vec<_>>();
    candidates.sort_unstable_by(|left, right| left.edit_id.cmp(&right.edit_id));
    skipped_locked.sort_unstable();
    AuthorDirectiveGenerationResult {
        receipt: AuthorDirectiveGenerationReceipt {
            schema: AUTHOR_REPAIR_DIRECTIVE_SCHEMA.into(),
            directive_count: input.directives.len(),
            emitted_candidates: candidates.len(),
            skipped_locked_directive_ids: skipped_locked,
            deterministic: true,
        },
        candidates,
    }
}

pub const fn is_author_directed_template(template: RepairTemplateKind) -> bool {
    matches!(
        template,
        RepairTemplateKind::ReassignCausalAttribution
            | RepairTemplateKind::RebindActionToPriorRecord
            | RepairTemplateKind::ReclassifyAssertionAsDeception
            | RepairTemplateKind::AddCostedCapabilityOverdraw
            | RepairTemplateKind::AddConstrainedTravelMethod
            | RepairTemplateKind::ReclassifyAccessAsEspionage
            | RepairTemplateKind::RebindPossessionDependentAction
    )
}

fn validate_directive(directive: &AuthorRepairDirective) -> Result<(), AuthorRepairDirectiveError> {
    if directive.case_id.0.is_empty()
        || directive.directive_id.is_empty()
        || directive.target_scene_ids.is_empty()
        || directive.intent.is_empty()
        || directive.required_outcomes.is_empty()
        || directive
            .target_scene_ids
            .iter()
            .any(|scene| scene.0.is_empty())
        || directive
            .required_outcomes
            .iter()
            .any(CompactString::is_empty)
    {
        return Err(AuthorRepairDirectiveError::IncompleteDirective(
            directive.directive_id.clone(),
        ));
    }
    if !is_author_directed_template(directive.template) {
        return Err(AuthorRepairDirectiveError::InvalidTemplate(
            directive.directive_id.clone(),
        ));
    }
    if directive.rejected_templates.contains(&directive.template) {
        return Err(AuthorRepairDirectiveError::RejectsPreferredTemplate(
            directive.directive_id.clone(),
        ));
    }
    Ok(())
}

fn constraints_for_targets(
    report: &RevisionImpactReport,
    target_ids: &[CompactString],
) -> Vec<CompactString> {
    let targets = target_ids
        .iter()
        .map(CompactString::as_str)
        .collect::<BTreeSet<_>>();
    let mut constraints = report
        .authoritative_impacts
        .iter()
        .filter(|impact| targets.contains(impact.scene_id.0.as_str()))
        .flat_map(|impact| {
            impact
                .violated_constraints
                .iter()
                .chain(&impact.support_loss_constraints)
        })
        .map(|constraint| constraint.constraint_id.clone())
        .collect::<Vec<_>>();
    constraints.sort_unstable();
    constraints.dedup();
    constraints
}

fn evidence_for_constraints(
    report: &RevisionImpactReport,
    constraint_ids: &[CompactString],
) -> Vec<EvidenceRef> {
    let constraints = constraint_ids
        .iter()
        .map(CompactString::as_str)
        .collect::<BTreeSet<_>>();
    let mut evidence = report
        .authoritative_impacts
        .iter()
        .flat_map(|impact| {
            impact
                .violated_constraints
                .iter()
                .chain(&impact.support_loss_constraints)
        })
        .filter(|constraint| constraints.contains(constraint.constraint_id.as_str()))
        .flat_map(|constraint| constraint.evidence.iter().cloned())
        .collect::<Vec<_>>();
    evidence.sort_unstable_by(|left, right| left.evidence_id.cmp(&right.evidence_id));
    evidence.dedup_by(|left, right| left.evidence_id == right.evidence_id);
    evidence
}

#[cfg(test)]
#[path = "repair_directive_tests.rs"]
mod tests;
