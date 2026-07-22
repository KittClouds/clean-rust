use std::collections::{BTreeMap, BTreeSet};

use compact_str::{format_compact, CompactString};
use phoenix_types::{ConstraintKind, RepairTemplateKind, StoryInterval, StoryMutation, StoryTime};
use serde::{Deserialize, Serialize};

use crate::{
    EvidenceRef, RevisionGraphSnapshot, RevisionImpactReport, RevisionRequirementSidecar,
    SourceEditBinding,
};

pub const DETERMINISTIC_REPAIR_SCHEMA: &str = "phoenix.deterministic-repair/v1";

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct EditId(pub CompactString);

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EditCost {
    pub scenes_changed: u16,
    pub evidence_spans_changed: u16,
    pub semantic_distance_millis: u16,
    pub rollback_penalty_millis: u16,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum RepairPrecondition {
    MutationTargetExists { target_id: CompactString },
    ConstraintExists { constraint_id: CompactString },
    EvidenceAnchored { evidence_id: CompactString },
    AuthorUnlocked { target_id: CompactString },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum GraphEditOperation {
    DropOriginalMutation {
        target_id: CompactString,
    },
    ReplaceOriginalMutation {
        replacement: StoryMutation,
    },
    RemoveRequirementBearingStatement {
        constraint_id: CompactString,
        scene_id: CompactString,
        evidence: Vec<EvidenceRef>,
    },
    ApplyAuthorDirective {
        directive_id: CompactString,
        intent: CompactString,
        required_outcomes: Vec<CompactString>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProposedEdit {
    pub schema: CompactString,
    pub edit_id: EditId,
    pub template: RepairTemplateKind,
    pub target_ids: Vec<CompactString>,
    pub operations: Vec<GraphEditOperation>,
    pub preconditions: Vec<RepairPrecondition>,
    pub source_constraints: Vec<CompactString>,
    pub evidence: Vec<EvidenceRef>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub source_bindings: Vec<SourceEditBinding>,
    pub preserves_mutation: bool,
    pub estimated_cost: EditCost,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SkippedRepairTemplate {
    pub template: RepairTemplateKind,
    pub constraint_id: CompactString,
    pub reason: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RepairGenerationReceipt {
    pub schema: CompactString,
    pub considered_templates: usize,
    pub emitted_candidates: usize,
    pub skipped_templates: Vec<SkippedRepairTemplate>,
    pub unrepaired_impact_ids: Vec<CompactString>,
    pub deterministic: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RepairGenerationResult {
    pub candidates: Vec<ProposedEdit>,
    pub receipt: RepairGenerationReceipt,
}

pub struct RepairGenerationInput<'a> {
    pub base: &'a RevisionGraphSnapshot,
    pub mutations: &'a [StoryMutation],
    pub requirements: &'a RevisionRequirementSidecar,
    pub report: &'a RevisionImpactReport,
    pub author_locked_ids: &'a BTreeSet<CompactString>,
}

pub fn generate_deterministic_repairs(input: RepairGenerationInput<'_>) -> RepairGenerationResult {
    debug_assert_eq!(
        input.base.generation(),
        input.report.deterministic_receipt.generation
    );
    let mutation = input.mutations.first();
    let mutation_id = mutation.map_or_else(|| "mutation:none".into(), mutation_target_id);
    let requirements = input
        .requirements
        .requirements
        .iter()
        .map(|requirement| (requirement.constraint_id.as_str(), requirement))
        .collect::<BTreeMap<_, _>>();
    let mut candidates = BTreeMap::<EditId, ProposedEdit>::new();
    let mut skipped = Vec::new();
    let mut considered = 0_usize;
    let mut impacts_with_candidate = BTreeSet::new();

    if let Some(
        mutation @ (StoryMutation::RetractFact { .. }
        | StoryMutation::SupersedeFact { .. }
        | StoryMutation::ShiftValidity { .. }),
    ) = mutation
    {
        let constraints = all_violated_constraint_ids(input.report);
        if !constraints.is_empty() {
            let evidence = evidence_for_constraints(input.report, &constraints);
            let edit = ProposedEdit {
                schema: DETERMINISTIC_REPAIR_SCHEMA.into(),
                edit_id: EditId(format_compact!("edit:rollback:{}", safe_id(&mutation_id))),
                template: RepairTemplateKind::RestoreOriginalFact,
                target_ids: vec![mutation_id.clone()],
                operations: vec![GraphEditOperation::DropOriginalMutation {
                    target_id: mutation_target_id(mutation),
                }],
                preconditions: vec![RepairPrecondition::MutationTargetExists {
                    target_id: mutation_id.clone(),
                }],
                source_constraints: constraints,
                evidence,
                source_bindings: Vec::new(),
                preserves_mutation: false,
                estimated_cost: EditCost {
                    scenes_changed: 0,
                    evidence_spans_changed: 0,
                    semantic_distance_millis: 1_000,
                    rollback_penalty_millis: 1_000,
                },
            };
            candidates.insert(edit.edit_id.clone(), edit);
        }
    }

    for impact in &input.report.authoritative_impacts {
        let constraints = impact
            .violated_constraints
            .iter()
            .chain(&impact.support_loss_constraints)
            .map(|constraint| constraint.constraint_id.clone())
            .collect::<Vec<_>>();
        if constraints.is_empty() {
            continue;
        }
        let scene_id = impact.scene_id.0.clone();
        let locked = input.author_locked_ids.contains(&scene_id);
        for constraint in impact
            .violated_constraints
            .iter()
            .chain(&impact.support_loss_constraints)
        {
            for &template in templates_for_constraint(constraint.kind) {
                considered += 1;
                if !matches!(
                    template,
                    RepairTemplateKind::ReviseRequirementBearingStatement
                        | RepairTemplateKind::ShiftReveal
                        | RepairTemplateKind::MoveStateTransition
                ) {
                    skipped.push(SkippedRepairTemplate {
                        template,
                        constraint_id: constraint.constraint_id.clone(),
                        reason: unsupported_reason(template).into(),
                    });
                }
            }
        }
        if !locked {
            let operations = constraints
                .iter()
                .filter_map(|constraint_id| requirements.get(constraint_id.as_str()))
                .map(
                    |requirement| GraphEditOperation::RemoveRequirementBearingStatement {
                        constraint_id: requirement.constraint_id.clone(),
                        scene_id: scene_id.clone(),
                        evidence: requirement.evidence.clone(),
                    },
                )
                .collect::<Vec<_>>();
            if operations.len() == constraints.len() {
                let evidence = evidence_for_constraints(input.report, &constraints);
                let edit = ProposedEdit {
                    schema: DETERMINISTIC_REPAIR_SCHEMA.into(),
                    edit_id: EditId(format_compact!(
                        "edit:revise_statement:{}:{}",
                        safe_id(&mutation_id),
                        safe_id(&scene_id)
                    )),
                    template: RepairTemplateKind::ReviseRequirementBearingStatement,
                    target_ids: vec![scene_id.clone()],
                    operations,
                    preconditions: statement_preconditions(&scene_id, &constraints, &evidence),
                    source_constraints: constraints.clone(),
                    evidence: evidence.clone(),
                    source_bindings: Vec::new(),
                    preserves_mutation: true,
                    estimated_cost: EditCost {
                        scenes_changed: 1,
                        evidence_spans_changed: evidence.len().min(u16::MAX as usize) as u16,
                        semantic_distance_millis: 200,
                        rollback_penalty_millis: 0,
                    },
                };
                candidates.insert(edit.edit_id.clone(), edit);
                impacts_with_candidate.insert(scene_id.clone());
            }
        } else {
            skipped.push(SkippedRepairTemplate {
                template: RepairTemplateKind::ReviseRequirementBearingStatement,
                constraint_id: constraints[0].clone(),
                reason: "target is author-locked".into(),
            });
        }

        if let Some(replacement) = temporal_replacement(mutation, &impact.valid_intervals()) {
            let template = match replacement {
                StoryMutation::ShiftValidity { .. } => RepairTemplateKind::ShiftReveal,
                StoryMutation::ChangeState { .. } => RepairTemplateKind::MoveStateTransition,
                _ => unreachable!("temporal replacement shape"),
            };
            let template_is_compatible = constraints.iter().any(|id| {
                requirements.get(id.as_str()).is_some_and(|requirement| {
                    templates_for_constraint(requirement.kind).contains(&template)
                })
            });
            if template_is_compatible {
                let edit = ProposedEdit {
                    schema: DETERMINISTIC_REPAIR_SCHEMA.into(),
                    edit_id: EditId(format_compact!(
                        "edit:{}:{}:{}",
                        template_name(template),
                        safe_id(&mutation_id),
                        safe_id(&scene_id)
                    )),
                    template,
                    target_ids: vec![mutation_id.clone(), scene_id.clone()],
                    operations: vec![GraphEditOperation::ReplaceOriginalMutation { replacement }],
                    preconditions: vec![RepairPrecondition::MutationTargetExists {
                        target_id: mutation_id.clone(),
                    }],
                    source_constraints: constraints.clone(),
                    evidence: evidence_for_constraints(input.report, &constraints),
                    source_bindings: Vec::new(),
                    preserves_mutation: template == RepairTemplateKind::MoveStateTransition,
                    estimated_cost: EditCost {
                        scenes_changed: 1,
                        evidence_spans_changed: 1,
                        semantic_distance_millis: 350,
                        rollback_penalty_millis: u16::from(
                            template == RepairTemplateKind::ShiftReveal,
                        ) * 500,
                    },
                };
                candidates.insert(edit.edit_id.clone(), edit);
                impacts_with_candidate.insert(scene_id.clone());
            }
        }
    }
    let mut candidates = candidates.into_values().collect::<Vec<_>>();
    candidates.sort_by(|left, right| {
        right
            .preserves_mutation
            .cmp(&left.preserves_mutation)
            .then_with(|| {
                left.estimated_cost
                    .semantic_distance_millis
                    .cmp(&right.estimated_cost.semantic_distance_millis)
            })
            .then_with(|| template_rank(left.template).cmp(&template_rank(right.template)))
            .then_with(|| left.edit_id.cmp(&right.edit_id))
    });
    skipped.sort_by(|left, right| {
        left.constraint_id
            .cmp(&right.constraint_id)
            .then_with(|| template_rank(left.template).cmp(&template_rank(right.template)))
    });
    let unrepaired_impact_ids = input
        .report
        .authoritative_impacts
        .iter()
        .filter(|impact| {
            !impact.violated_constraints.is_empty() || !impact.support_loss_constraints.is_empty()
        })
        .filter(|impact| !impacts_with_candidate.contains(&impact.scene_id.0))
        .map(|impact| impact.scene_id.0.clone())
        .collect();
    RepairGenerationResult {
        receipt: RepairGenerationReceipt {
            schema: DETERMINISTIC_REPAIR_SCHEMA.into(),
            considered_templates: considered,
            emitted_candidates: candidates.len(),
            skipped_templates: skipped,
            unrepaired_impact_ids,
            deterministic: true,
        },
        candidates,
    }
}

trait ImpactIntervals {
    fn valid_intervals(&self) -> Vec<StoryInterval>;
}

impl ImpactIntervals for crate::RevisionImpact {
    fn valid_intervals(&self) -> Vec<StoryInterval> {
        self.violated_constraints
            .iter()
            .chain(&self.support_loss_constraints)
            .map(|constraint| constraint.valid_interval)
            .collect()
    }
}

fn temporal_replacement(
    mutation: Option<&StoryMutation>,
    intervals: &[StoryInterval],
) -> Option<StoryMutation> {
    let boundary = intervals
        .iter()
        .filter_map(|interval| interval.valid_to_exclusive)
        .max()
        .unwrap_or(StoryTime(0));
    match mutation? {
        StoryMutation::ShiftValidity { fact_id, .. } => Some(StoryMutation::ShiftValidity {
            fact_id: fact_id.clone(),
            new_interval: StoryInterval {
                valid_from: StoryTime(0),
                valid_to_exclusive: None,
            },
        }),
        StoryMutation::ChangeState {
            subject_id,
            state_kind,
            replacement,
            ..
        } => Some(StoryMutation::ChangeState {
            subject_id: subject_id.clone(),
            state_kind: state_kind.clone(),
            replacement: replacement.clone(),
            valid_from: boundary,
        }),
        _ => None,
    }
}

fn statement_preconditions(
    scene_id: &str,
    constraints: &[CompactString],
    evidence: &[EvidenceRef],
) -> Vec<RepairPrecondition> {
    let mut values = vec![RepairPrecondition::AuthorUnlocked {
        target_id: scene_id.into(),
    }];
    values.extend(
        constraints
            .iter()
            .cloned()
            .map(|constraint_id| RepairPrecondition::ConstraintExists { constraint_id }),
    );
    values.extend(
        evidence
            .iter()
            .map(|evidence| RepairPrecondition::EvidenceAnchored {
                evidence_id: evidence.evidence_id.clone(),
            }),
    );
    values
}

fn evidence_for_constraints(
    report: &RevisionImpactReport,
    constraint_ids: &[CompactString],
) -> Vec<EvidenceRef> {
    let ids = constraint_ids
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
        .filter(|constraint| ids.contains(constraint.constraint_id.as_str()))
        .flat_map(|constraint| constraint.evidence.iter().cloned())
        .collect::<Vec<_>>();
    evidence.sort_unstable_by(|left, right| left.evidence_id.cmp(&right.evidence_id));
    evidence.dedup_by(|left, right| left.evidence_id == right.evidence_id);
    evidence
}

fn all_violated_constraint_ids(report: &RevisionImpactReport) -> Vec<CompactString> {
    let mut constraints = report
        .authoritative_impacts
        .iter()
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

pub const fn templates_for_constraint(kind: ConstraintKind) -> &'static [RepairTemplateKind] {
    use RepairTemplateKind as Template;
    match kind {
        ConstraintKind::RequiresKnowledge => &[
            Template::ShiftReveal,
            Template::DowngradeKnowledge,
            Template::ReviseRequirementBearingStatement,
        ],
        ConstraintKind::RequiresWitness => &[Template::ReviseRequirementBearingStatement],
        ConstraintKind::RequiresAlive | ConstraintKind::RequiresState => &[
            Template::MoveStateTransition,
            Template::ReviseRequirementBearingStatement,
        ],
        ConstraintKind::RequiresPossession => &[
            Template::TransferPossessionEarlier,
            Template::ReviseRequirementBearingStatement,
        ],
        ConstraintKind::RequiresReachability | ConstraintKind::RequiresTemporalOrder => &[
            Template::InsertIntermediateTravelEvent,
            Template::MoveStateTransition,
            Template::ReviseRequirementBearingStatement,
        ],
        ConstraintKind::MutuallyExclusiveStates => &[
            Template::MoveStateTransition,
            Template::SplitEvent,
            Template::ReviseRequirementBearingStatement,
        ],
        ConstraintKind::CausalSupport | ConstraintKind::Motivation => &[
            Template::AddAlternativeCause,
            Template::ReviseRequirementBearingStatement,
        ],
        ConstraintKind::Foreshadowing => &[Template::ReviseRequirementBearingStatement],
        ConstraintKind::Mention | ConstraintKind::ThematicEcho => &[],
    }
}

const fn unsupported_reason(template: RepairTemplateKind) -> &'static str {
    match template {
        RepairTemplateKind::DowngradeKnowledge => {
            "no authoritative inferred-belief replacement is available"
        }
        RepairTemplateKind::InsertIntermediateTravelEvent => {
            "travel-event arithmetic is not projected into this validator"
        }
        RepairTemplateKind::TransferPossessionEarlier => {
            "multi-transition possession history is not available"
        }
        RepairTemplateKind::SplitEvent => "event partition operations are not available",
        RepairTemplateKind::AddAlternativeCause => {
            "no authoritative alternative-cause record is available"
        }
        RepairTemplateKind::ShiftReveal
        | RepairTemplateKind::MoveStateTransition
        | RepairTemplateKind::ReviseRequirementBearingStatement
        | RepairTemplateKind::RestoreOriginalFact => "template preconditions were not satisfied",
        RepairTemplateKind::ReassignCausalAttribution
        | RepairTemplateKind::RebindActionToPriorRecord
        | RepairTemplateKind::ReclassifyAssertionAsDeception
        | RepairTemplateKind::AddCostedCapabilityOverdraw
        | RepairTemplateKind::AddConstrainedTravelMethod
        | RepairTemplateKind::ReclassifyAccessAsEspionage
        | RepairTemplateKind::RebindPossessionDependentAction => {
            "author directive requires a rebuilt semantic sidecar"
        }
    }
}

pub(crate) fn mutation_target_id(mutation: &StoryMutation) -> CompactString {
    match mutation {
        StoryMutation::RetractFact { fact_id }
        | StoryMutation::SupersedeFact { fact_id, .. }
        | StoryMutation::ShiftValidity { fact_id, .. } => fact_id.0.clone(),
        StoryMutation::ChangeState {
            subject_id,
            state_kind,
            ..
        } => format_compact!("state:{}:{}", subject_id.0, state_kind.0),
    }
}

fn safe_id(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character
            } else {
                '_'
            }
        })
        .collect()
}

const fn template_rank(template: RepairTemplateKind) -> u8 {
    match template {
        RepairTemplateKind::ReviseRequirementBearingStatement => 0,
        RepairTemplateKind::DowngradeKnowledge => 1,
        RepairTemplateKind::MoveStateTransition => 2,
        RepairTemplateKind::InsertIntermediateTravelEvent => 3,
        RepairTemplateKind::TransferPossessionEarlier => 4,
        RepairTemplateKind::SplitEvent => 5,
        RepairTemplateKind::AddAlternativeCause => 6,
        RepairTemplateKind::ShiftReveal => 7,
        RepairTemplateKind::RestoreOriginalFact => 8,
        RepairTemplateKind::ReassignCausalAttribution => 9,
        RepairTemplateKind::RebindActionToPriorRecord => 10,
        RepairTemplateKind::ReclassifyAssertionAsDeception => 11,
        RepairTemplateKind::AddCostedCapabilityOverdraw => 12,
        RepairTemplateKind::AddConstrainedTravelMethod => 13,
        RepairTemplateKind::ReclassifyAccessAsEspionage => 14,
        RepairTemplateKind::RebindPossessionDependentAction => 15,
    }
}

const fn template_name(template: RepairTemplateKind) -> &'static str {
    match template {
        RepairTemplateKind::RestoreOriginalFact => "restore_fact",
        RepairTemplateKind::ShiftReveal => "shift_reveal",
        RepairTemplateKind::DowngradeKnowledge => "downgrade_knowledge",
        RepairTemplateKind::ReviseRequirementBearingStatement => "revise_statement",
        RepairTemplateKind::MoveStateTransition => "move_state_transition",
        RepairTemplateKind::InsertIntermediateTravelEvent => "insert_travel",
        RepairTemplateKind::TransferPossessionEarlier => "transfer_possession",
        RepairTemplateKind::SplitEvent => "split_event",
        RepairTemplateKind::AddAlternativeCause => "alternative_cause",
        RepairTemplateKind::ReassignCausalAttribution => "reassign_causal_attribution",
        RepairTemplateKind::RebindActionToPriorRecord => "rebind_prior_record",
        RepairTemplateKind::ReclassifyAssertionAsDeception => "reclassify_deception",
        RepairTemplateKind::AddCostedCapabilityOverdraw => "costed_overdraw",
        RepairTemplateKind::AddConstrainedTravelMethod => "constrained_travel",
        RepairTemplateKind::ReclassifyAccessAsEspionage => "access_as_espionage",
        RepairTemplateKind::RebindPossessionDependentAction => "rebind_possession_action",
    }
}
