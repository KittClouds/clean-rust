use anyhow::{Context, Result, ensure};

use crate::types::{
    CandidateDefinition, CandidateKind, CandidateSet, CandidateSetSemantics, PresentationProfile,
    PresentationProfileSpec, RuntimeSchema,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CandidateIntervention {
    Reorder,
    Subset(Vec<String>),
    Superset(CandidateDefinition),
    Rename {
        semantic_id: String,
        new_name: String,
    },
    OpaqueIdSubstitution {
        semantic_id: String,
        new_opaque_id: String,
    },
    DescriptionParaphrase {
        semantic_id: String,
        description: String,
    },
    DescriptionRemoval {
        semantic_id: String,
    },
    HierarchyExposure {
        semantic_id: String,
        parent: Option<String>,
    },
}

pub fn security_candidates() -> Vec<CandidateDefinition> {
    vec![
        candidate(
            "A17",
            "credential_compromise",
            "credential_compromise",
            "Unauthorized account access using otherwise valid credentials.",
            Some("security"),
            true,
        ),
        candidate(
            "A18",
            "maintenance",
            "maintenance",
            "A planned operational change explains the observed activity.",
            Some("operations"),
            true,
        ),
        candidate(
            "A19",
            "hardware_failure",
            "hardware_failure",
            "A device or component malfunction explains the observed activity.",
            Some("operations"),
            true,
        ),
        candidate(
            "A20",
            "benign_activity",
            "benign_activity",
            "The observed activity is ordinary and does not indicate an incident.",
            Some("benign"),
            true,
        ),
    ]
}

pub fn entity_type_candidates() -> Vec<CandidateDefinition> {
    vec![
        candidate_kind(
            "T-person",
            "person",
            CandidateKind::EntityType,
            "A person entity.",
            true,
        ),
        candidate_kind(
            "T-credential",
            "credential",
            CandidateKind::EntityType,
            "A credential, token, or access key.",
            true,
        ),
        candidate_kind(
            "T-system",
            "system",
            CandidateKind::EntityType,
            "A named system or service.",
            true,
        ),
    ]
}

pub fn relation_candidates() -> Vec<CandidateDefinition> {
    vec![
        candidate_kind(
            "R-possesses",
            "possesses",
            CandidateKind::RelationType,
            "The head entity possesses the tail entity.",
            false,
        ),
        candidate_kind(
            "R-belongs-to",
            "belongs_to",
            CandidateKind::RelationType,
            "The head entity belongs to or is assigned to the tail entity.",
            false,
        ),
        candidate_kind(
            "R-transferred-to",
            "transferred_to",
            CandidateKind::RelationType,
            "The head entity was transferred to the tail entity.",
            false,
        ),
    ]
}

pub fn security_runtime_schema(profile: PresentationProfile) -> RuntimeSchema {
    let candidates = security_candidates();
    let candidate_ids = candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect();
    RuntimeSchema {
        schema_id: "schema-security-routing-v0.2".to_string(),
        schema_family_id: "schema-security-routing".to_string(),
        candidates,
        candidate_sets: vec![CandidateSet {
            candidate_set_id: "cs-security-all".to_string(),
            candidate_ids,
            set_role: "choice-alternatives".to_string(),
            declared_semantics: CandidateSetSemantics::ChoiceConditional,
            ordered: false,
            parent_candidate_set_id: None,
        }],
        constraints: vec!["exactly_one_for_closed_choice".to_string()],
        presentation_profiles: vec![profile_spec(profile)],
    }
}

pub fn entity_runtime_schema() -> RuntimeSchema {
    let candidates = entity_type_candidates();
    let candidate_ids = candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect();
    RuntimeSchema {
        schema_id: "schema-entity-types-v0.2".to_string(),
        schema_family_id: "schema-entity-types".to_string(),
        candidates,
        candidate_sets: vec![CandidateSet {
            candidate_set_id: "cs-entity-types".to_string(),
            candidate_ids,
            set_role: "span-types".to_string(),
            declared_semantics: CandidateSetSemantics::SpanTypePairs,
            ordered: false,
            parent_candidate_set_id: None,
        }],
        constraints: vec!["contiguous_non_overlapping_mentions".to_string()],
        presentation_profiles: vec![profile_spec(PresentationProfile::NamePlusDefinition)],
    }
}

pub fn relation_runtime_schema() -> RuntimeSchema {
    let candidates = relation_candidates();
    let candidate_ids = candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect();
    RuntimeSchema {
        schema_id: "schema-relations-v0.2".to_string(),
        schema_family_id: "schema-relations".to_string(),
        candidates,
        candidate_sets: vec![CandidateSet {
            candidate_set_id: "cs-relations".to_string(),
            candidate_ids,
            set_role: "relation-types".to_string(),
            declared_semantics: CandidateSetSemantics::RelationPairs,
            ordered: false,
            parent_candidate_set_id: None,
        }],
        constraints: vec!["relation_polarity_has_three_states".to_string()],
        presentation_profiles: vec![profile_spec(PresentationProfile::NamePlusDefinition)],
    }
}

pub fn apply_candidate_intervention(
    schema: &RuntimeSchema,
    intervention: &CandidateIntervention,
) -> Result<RuntimeSchema> {
    let mut child = schema.clone();
    match intervention {
        CandidateIntervention::Reorder => {
            child.candidates.reverse();
            for candidate_set in &mut child.candidate_sets {
                candidate_set.candidate_ids.reverse();
            }
        }
        CandidateIntervention::Subset(keep) => {
            ensure!(!keep.is_empty(), "candidate subset cannot be empty");
            child
                .candidates
                .retain(|candidate| keep.iter().any(|id| id == &candidate.candidate_semantic_id));
            for candidate_set in &mut child.candidate_sets {
                candidate_set.candidate_ids.retain(|id| {
                    child
                        .candidates
                        .iter()
                        .any(|candidate| candidate.candidate_id == *id)
                });
            }
        }
        CandidateIntervention::Superset(candidate) => {
            ensure!(
                !child
                    .candidates
                    .iter()
                    .any(|existing| existing.candidate_semantic_id
                        == candidate.candidate_semantic_id),
                "superset candidate already exists"
            );
            child.candidates.push(candidate.clone());
            for candidate_set in &mut child.candidate_sets {
                candidate_set
                    .candidate_ids
                    .push(candidate.candidate_id.clone());
            }
        }
        CandidateIntervention::Rename {
            semantic_id,
            new_name,
        } => {
            let candidate = find_candidate_mut(&mut child, semantic_id)?;
            candidate.name = Some(new_name.clone());
        }
        CandidateIntervention::OpaqueIdSubstitution {
            semantic_id,
            new_opaque_id,
        } => {
            let candidate = find_candidate_mut(&mut child, semantic_id)?;
            let old_candidate_id = candidate.candidate_id.clone();
            candidate.opaque_id = Some(new_opaque_id.clone());
            candidate.candidate_id = new_opaque_id.clone();
            for candidate_set in &mut child.candidate_sets {
                for id in &mut candidate_set.candidate_ids {
                    if id == &old_candidate_id {
                        *id = new_opaque_id.clone();
                    }
                }
            }
        }
        CandidateIntervention::DescriptionParaphrase {
            semantic_id,
            description,
        } => {
            let candidate = find_candidate_mut(&mut child, semantic_id)?;
            candidate.description = Some(description.clone());
        }
        CandidateIntervention::DescriptionRemoval { semantic_id } => {
            let candidate = find_candidate_mut(&mut child, semantic_id)?;
            candidate.description = None;
        }
        CandidateIntervention::HierarchyExposure {
            semantic_id,
            parent,
        } => {
            let candidate = find_candidate_mut(&mut child, semantic_id)?;
            candidate.parent_candidate_semantic_id = parent.clone();
        }
    }
    Ok(child)
}

pub fn expected_candidate_intervention_relation(
    intervention: &CandidateIntervention,
) -> &'static str {
    match intervention {
        CandidateIntervention::Reorder
        | CandidateIntervention::Rename { .. }
        | CandidateIntervention::OpaqueIdSubstitution { .. }
        | CandidateIntervention::DescriptionParaphrase { .. }
        | CandidateIntervention::HierarchyExposure { .. } => {
            "strict_invariant_after_semantic_alignment"
        }
        CandidateIntervention::Subset(_) | CandidateIntervention::Superset(_) => {
            "retained_semantics_preserved_conditional_scores_may_change"
        }
        CandidateIntervention::DescriptionRemoval { .. } => "not_assumed_invariant",
    }
}

fn candidate(
    candidate_id: &str,
    semantic_id: &str,
    name: &str,
    description: &str,
    parent: Option<&str>,
    independent_allowed: bool,
) -> CandidateDefinition {
    CandidateDefinition {
        candidate_id: candidate_id.to_string(),
        candidate_semantic_id: semantic_id.to_string(),
        kind: CandidateKind::Label,
        name: Some(name.to_string()),
        description: Some(description.to_string()),
        aliases: Vec::new(),
        opaque_id: Some(candidate_id.to_string()),
        parent_candidate_semantic_id: parent.map(str::to_string),
        order_rank: None,
        mutually_exclusive_group_id: Some("security-choice".to_string()),
        independent_allowed,
    }
}

fn candidate_kind(
    candidate_id: &str,
    semantic_id: &str,
    kind: CandidateKind,
    description: &str,
    independent_allowed: bool,
) -> CandidateDefinition {
    CandidateDefinition {
        candidate_id: candidate_id.to_string(),
        candidate_semantic_id: semantic_id.to_string(),
        kind,
        name: Some(semantic_id.to_string()),
        description: Some(description.to_string()),
        aliases: Vec::new(),
        opaque_id: Some(candidate_id.to_string()),
        parent_candidate_semantic_id: None,
        order_rank: None,
        mutually_exclusive_group_id: None,
        independent_allowed,
    }
}

fn profile_spec(profile: PresentationProfile) -> PresentationProfileSpec {
    let exposed_fields = match &profile {
        PresentationProfile::SemanticNameOnly => vec!["name".to_string()],
        PresentationProfile::NamePlusDefinition => {
            vec!["name".to_string(), "description".to_string()]
        }
        PresentationProfile::OpaqueIdPlusDefinition => {
            vec!["opaque_id".to_string(), "description".to_string()]
        }
        PresentationProfile::OpaqueIdOnly => vec!["opaque_id".to_string()],
    };
    PresentationProfileSpec {
        profile_id: format!("profile-{:?}", profile).to_lowercase(),
        profile,
        exposed_fields,
    }
}

fn find_candidate_mut<'a>(
    schema: &'a mut RuntimeSchema,
    semantic_id: &str,
) -> Result<&'a mut CandidateDefinition> {
    schema
        .candidates
        .iter_mut()
        .find(|candidate| candidate.candidate_semantic_id == semantic_id)
        .with_context(|| format!("candidate {semantic_id} not found"))
}
