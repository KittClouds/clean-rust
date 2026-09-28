use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

pub const CONTRACT_V1: &str = "jev-like-decision-dataset/v1";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ContractStatus {
    V1Compatible,
    V1PlusProposedE01,
    V1PlusProposedE02,
    V1PlusProposedE01E02,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AuthorityClass {
    Authoritative,
    ExternallyAnnotated,
    Adjudicated,
    Weak,
    SyntheticControl,
    Unverified,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AuthorityDomain {
    SyntheticControl,
    PhoenixNative,
    ExternalDataset,
    Adjudication,
    Unknown,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Identity {
    pub episode_id: String,
    pub world_family_id: String,
    pub world_instance_id: String,
    pub surface_renderer_id: String,
    pub paraphrase_family_id: String,
    pub perturbation_family_id: String,
    pub schema_family_id: String,
    pub task_family_ids: Vec<String>,
    pub domain_family_id: String,
    pub semantic_fingerprint: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Representation {
    Prose,
    Json,
    Table,
    EventStream,
    KeyValue,
    Dialogue,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ObservableState {
    pub content: String,
    pub items: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Default)]
pub struct VariableVisibility {
    pub observed: Vec<String>,
    pub missing: Vec<String>,
    pub hidden: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct State {
    pub representation: Representation,
    pub observable: ObservableState,
    pub latent: Option<serde_json::Value>,
    pub variables: VariableVisibility,
    pub structured_state: Option<StructuredState>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct EvidenceItem {
    pub evidence_id: String,
    pub kind: String,
    pub content: String,
    pub source_ref: String,
    pub available_at: Option<i64>,
    pub character_span: Option<[usize; 2]>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CandidateKind {
    Label,
    EntityType,
    RelationType,
    Oos,
    OrdinalScale,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct CandidateDefinition {
    pub candidate_id: String,
    pub candidate_semantic_id: String,
    pub kind: CandidateKind,
    pub name: Option<String>,
    pub description: Option<String>,
    pub aliases: Vec<String>,
    pub opaque_id: Option<String>,
    pub parent_candidate_semantic_id: Option<String>,
    pub order_rank: Option<i32>,
    pub mutually_exclusive_group_id: Option<String>,
    pub independent_allowed: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CandidateSetSemantics {
    ChoiceConditional,
    IndependentApplicability,
    OrdinalScale,
    SpanTypePairs,
    RelationPairs,
    UnnormalizedCompatibility,
    Unknown,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CandidateSet {
    pub candidate_set_id: String,
    pub candidate_ids: Vec<String>,
    pub set_role: String,
    pub declared_semantics: CandidateSetSemantics,
    pub ordered: bool,
    pub parent_candidate_set_id: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PresentationProfile {
    SemanticNameOnly,
    NamePlusDefinition,
    OpaqueIdPlusDefinition,
    OpaqueIdOnly,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct PresentationProfileSpec {
    pub profile_id: String,
    pub profile: PresentationProfile,
    pub exposed_fields: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Default)]
pub struct RuntimeSchema {
    pub schema_id: String,
    pub schema_family_id: String,
    pub candidates: Vec<CandidateDefinition>,
    pub candidate_sets: Vec<CandidateSet>,
    pub constraints: Vec<String>,
    pub presentation_profiles: Vec<PresentationProfileSpec>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum QueryView {
    Choice,
    IndependentApplicability,
    OrdinalScore,
    Abstain,
    SpanType,
    Relation,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ArgumentScope {
    pub span_ids: Vec<String>,
    pub entity_ids: Vec<String>,
    pub relation_direction: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Query {
    pub query_id: String,
    pub query_semantic_id: String,
    pub view: QueryView,
    pub instruction: Option<String>,
    pub candidate_set_id: Option<String>,
    pub argument_scope: Option<ArgumentScope>,
    pub abstention_policy: Option<String>,
    pub exposed_fields: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ScoreSemantics {
    ChoiceConditional,
    IndependentApplicability,
    OrdinalDistribution,
    AbstentionProbability,
    SpanTypeCompatibility,
    RelationCompatibility,
    HardLabelOnly,
    Unknown,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ProbabilityEntry {
    pub candidate_semantic_id: String,
    pub probability: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ApplicabilityEntry {
    pub candidate_semantic_id: String,
    pub applies: Option<bool>,
    pub probability: Option<f64>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SpanTarget {
    pub span_id: String,
    pub start: usize,
    pub end: usize,
    pub type_targets: Vec<ApplicabilityEntry>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RelationPolarity {
    Holds,
    DoesNotHold,
    Unknown,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RelationTarget {
    pub relation_instance_id: String,
    pub head_span_id: String,
    pub tail_span_id: String,
    pub candidate_semantic_id: String,
    pub direction: String,
    pub polarity: RelationPolarity,
    pub probability: Option<f64>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(tag = "target_kind", rename_all = "snake_case")]
pub enum TargetPayload {
    Choice {
        selected_candidate_semantic_id: Option<String>,
        distribution: Option<Vec<ProbabilityEntry>>,
        other_probability: Option<f64>,
        abstain_allowed: bool,
    },
    IndependentApplicability {
        candidates: Vec<ApplicabilityEntry>,
    },
    Ordinal {
        scale_id: String,
        ordered_values: Vec<i32>,
        distribution: Option<Vec<f64>>,
        expected_value: Option<f64>,
        interval: Option<[i32; 2]>,
    },
    Abstention {
        evidence_status: String,
        abstain: Option<bool>,
        reason: Option<String>,
        distribution: Option<Vec<ProbabilityEntry>>,
    },
    SpanType {
        spans: Vec<SpanTarget>,
    },
    Relation {
        relations: Vec<RelationTarget>,
    },
    HardLabel {
        labels: Vec<String>,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct AuthorityRecord {
    pub authority_record_id: String,
    pub authority_class: AuthorityClass,
    pub authority_domain: AuthorityDomain,
    pub authority_scope: String,
    pub creator_or_system: String,
    pub source_identity: String,
    pub source_revision_or_snapshot: String,
    pub annotation_or_generator_protocol: String,
    pub created_at: Option<String>,
    pub available_at: Option<String>,
    pub license_or_access_basis: Option<String>,
    pub parent_authority_ids: Vec<String>,
    pub quality_limitations: Vec<String>,
    pub lineage: Lineage,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ProbabilitySourceMetadata {
    pub probability_source: ProbabilitySource,
    pub sample_count: Option<u64>,
    pub annotator_count: Option<u32>,
    #[serde(default)]
    pub raw_label_counts: Option<BTreeMap<String, u64>>,
    pub aggregation_method: String,
    pub normalization_scope: String,
    pub distribution_interpretation: DistributionInterpretation,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProbabilitySource {
    ExactGenerativePosterior,
    EmpiricalAnnotatorDistribution,
    ElicitedSubjectiveProbability,
    AdjudicatedDistribution,
    HardLabel,
    WeakScore,
    NoProbability,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DistributionInterpretation {
    WorldPosterior,
    HumanOpinionFrequency,
    ReportedSubjectiveBelief,
    AdjudicatedBelief,
    NotApplicable,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Annotation {
    pub annotator_id: Option<String>,
    pub labels: Vec<String>,
    pub source_label: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GoldTarget {
    pub query_id: String,
    pub authority_record_id: String,
    pub score_semantics: ScoreSemantics,
    pub candidate_set_id: Option<String>,
    pub probability_source: ProbabilitySourceMetadata,
    pub target: TargetPayload,
    pub annotations: Option<Vec<Annotation>>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct EvidenceLink {
    pub evidence_link_id: String,
    pub target_ref: String,
    pub evidence_item_ids: Vec<String>,
    pub role: String,
    pub locations: Vec<EvidenceLocation>,
    pub required_for_target: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct EvidenceLocation {
    pub evidence_id: String,
    pub start: usize,
    pub end: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Perturbation {
    pub family_id: String,
    pub parent_episode_id: Option<String>,
    pub operation: String,
    pub class: String,
    pub expected_relation: String,
    pub affected_query_ids: Vec<String>,
    pub unaffected_query_ids: Vec<String>,
    pub alignment: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Default)]
pub struct WorkloadMetadata {
    pub state_length_tokens: Option<u32>,
    pub schema_length_tokens: Option<u32>,
    pub query_count: usize,
    pub candidate_cardinality: Option<u32>,
    pub candidate_token_length: Option<u32>,
    pub candidate_description_length: Option<u32>,
    pub branch_width: Option<u32>,
    pub label_density: Option<f64>,
    pub relevant_evidence_count: Option<u32>,
    pub distractor_count: Option<u32>,
    pub contradiction_count: Option<u32>,
    pub span_count: Option<u32>,
    pub relation_count: Option<u32>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Default)]
pub struct EvaluationConstraints {
    pub split_regime: Option<String>,
    pub excluded_from_primary_benchmark: bool,
    pub notes: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Lineage {
    pub source_dataset_id: String,
    pub source_revision: String,
    pub source_split: String,
    pub source_row_id: String,
    pub upstream_dataset_id: Option<String>,
    pub upstream_row_id: Option<String>,
    pub adapter_id: String,
    pub adapter_revision: String,
    pub transformation_chain: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct AuthoritySummary {
    pub episode_authority_class: AuthorityClass,
    pub authority_record_ids: Vec<String>,
    pub phoenix_authority_domain: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct StructuredState {
    pub offset_unit: String,
    pub entities: Vec<EntityRecord>,
    pub semantic_relations: Vec<SemanticRelation>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct EntityRecord {
    pub entity_semantic_id: String,
    pub type_semantic_id: String,
    pub canonical_name: String,
    pub mentions: Vec<MentionRecord>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct MentionRecord {
    pub mention_id: String,
    pub entity_semantic_id: String,
    pub character_start: usize,
    pub character_end: usize,
    pub surface: String,
    pub type_semantic_id: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SemanticRelation {
    pub relation_instance_id: String,
    pub relation_semantic_id: String,
    pub head_entity_id: String,
    pub tail_entity_id: String,
    pub direction: String,
    pub polarity: RelationPolarity,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CanonicalEpisode {
    pub contract: String,
    pub contract_status: ContractStatus,
    pub identity: Identity,
    pub state: State,
    pub evidence_items: Vec<EvidenceItem>,
    pub runtime_schema: RuntimeSchema,
    pub queries: Vec<Query>,
    pub gold_targets: Vec<GoldTarget>,
    pub evidence_links: Vec<EvidenceLink>,
    pub perturbation: Option<Perturbation>,
    pub authority: AuthoritySummary,
    pub authority_records: Vec<AuthorityRecord>,
    pub workload: WorkloadMetadata,
    pub evaluation_constraints: EvaluationConstraints,
}

impl CanonicalEpisode {
    pub fn semantic_content_bytes(&self) -> Result<Vec<u8>, serde_json::Error> {
        let mut candidates: Vec<Value> = self
            .runtime_schema
            .candidates
            .iter()
            .map(|candidate| {
                json!({
                    "semantic_id": candidate.candidate_semantic_id,
                    "kind": candidate.kind,
                    "parent": candidate.parent_candidate_semantic_id,
                    "order_rank": candidate.order_rank,
                    "exclusive_group": candidate.mutually_exclusive_group_id,
                    "independent_allowed": candidate.independent_allowed,
                })
            })
            .collect();
        candidates.sort_by_key(|candidate| {
            candidate["semantic_id"]
                .as_str()
                .unwrap_or_default()
                .to_string()
        });
        let mut candidate_sets: Vec<Value> = self
            .runtime_schema
            .candidate_sets
            .iter()
            .map(|candidate_set| {
                let mut members = candidate_set
                    .candidate_ids
                    .iter()
                    .filter_map(|candidate_id| {
                        self.runtime_schema
                            .candidates
                            .iter()
                            .find(|candidate| candidate.candidate_id == *candidate_id)
                            .map(|candidate| candidate.candidate_semantic_id.clone())
                    })
                    .collect::<Vec<_>>();
                members.sort();
                json!({
                    "set_id": candidate_set.candidate_set_id,
                    "members": members,
                    "role": candidate_set.set_role,
                    "semantics": candidate_set.declared_semantics,
                    "ordered": candidate_set.ordered,
                    "parent": candidate_set.parent_candidate_set_id,
                })
            })
            .collect();
        candidate_sets.sort_by_key(|candidate_set| {
            candidate_set["set_id"]
                .as_str()
                .unwrap_or_default()
                .to_string()
        });

        let mut queries: Vec<Value> = self
            .queries
            .iter()
            .map(|query| {
                json!({
                    "query_id": query.query_id,
                    "query_semantic_id": query.query_semantic_id,
                    "view": query.view,
                    "candidate_set_id": query.candidate_set_id,
                    "argument_scope": query.argument_scope,
                    "abstention_policy": query.abstention_policy,
                })
            })
            .collect();
        queries.sort_by_key(|query| query["query_id"].as_str().unwrap_or_default().to_string());
        let mut targets: Vec<Value> = self
            .gold_targets
            .iter()
            .map(|target| {
                let mut value = serde_json::to_value(target).expect("gold target is serializable");
                canonicalize_target(&mut value);
                value
            })
            .collect();
        targets.sort_by_key(|target| target["query_id"].as_str().unwrap_or_default().to_string());
        let mut evidence_links: Vec<Value> = self
            .evidence_links
            .iter()
            .map(|link| {
                let mut evidence_ids = link.evidence_item_ids.clone();
                evidence_ids.sort();
                json!({
                    "target_ref": link.target_ref,
                    "evidence_item_ids": evidence_ids,
                    "role": link.role,
                    "required_for_target": link.required_for_target,
                })
            })
            .collect();
        evidence_links
            .sort_by_key(|link| link["target_ref"].as_str().unwrap_or_default().to_string());

        let mut observed = self.state.variables.observed.clone();
        let mut missing = self.state.variables.missing.clone();
        let mut hidden = self.state.variables.hidden.clone();
        observed.sort();
        missing.sort();
        hidden.sort();
        let structured = self.state.structured_state.as_ref().map(|structured| {
            let mut entities: Vec<Value> = structured
                .entities
                .iter()
                .map(|entity| json!({"entity_semantic_id": entity.entity_semantic_id, "type_semantic_id": entity.type_semantic_id}))
                .collect();
            entities.sort_by_key(|entity| entity["entity_semantic_id"].as_str().unwrap_or_default().to_string());
            let mut relations: Vec<Value> = structured
                .semantic_relations
                .iter()
                .map(|relation| {
                    json!({
                        "relation_instance_id": relation.relation_instance_id,
                        "relation_semantic_id": relation.relation_semantic_id,
                        "head_entity_id": relation.head_entity_id,
                        "tail_entity_id": relation.tail_entity_id,
                        "direction": relation.direction,
                        "polarity": relation.polarity,
                    })
                })
                .collect();
            relations.sort_by_key(|relation| relation["relation_instance_id"].as_str().unwrap_or_default().to_string());
            json!({"entities": entities, "semantic_relations": relations})
        });
        serde_json::to_vec(&json!({
            "world_family_id": self.identity.world_family_id,
            "world_instance_id": self.identity.world_instance_id,
            "latent": self.state.latent,
            "variables": {"observed": observed, "missing": missing, "hidden": hidden},
            "structured": structured,
            "candidates": candidates,
            "candidate_sets": candidate_sets,
            "queries": queries,
            "gold_targets": targets,
            "evidence_links": evidence_links,
        }))
    }
}

fn canonicalize_target(value: &mut Value) {
    let Some(object) = value.as_object_mut() else {
        return;
    };
    object.remove("authority_record_id");
    if let Some(target) = object.get_mut("target") {
        canonicalize_target_payload(target);
    }
}

fn canonicalize_target_payload(value: &mut Value) {
    let Some(object) = value.as_object_mut() else {
        return;
    };
    for key in [
        "distribution",
        "candidates",
        "spans",
        "relations",
        "type_targets",
    ] {
        let Some(array) = object.get_mut(key).and_then(Value::as_array_mut) else {
            continue;
        };
        if key == "spans" {
            for item in array.iter_mut() {
                if let Some(item) = item.as_object_mut() {
                    item.remove("start");
                    item.remove("end");
                }
            }
        }
        if array.iter().all(Value::is_object) {
            array.sort_by_key(|item| {
                ["candidate_semantic_id", "span_id", "relation_instance_id"]
                    .iter()
                    .find_map(|field| item.get(*field).and_then(Value::as_str))
                    .unwrap_or_default()
                    .to_string()
            });
        }
    }
}
