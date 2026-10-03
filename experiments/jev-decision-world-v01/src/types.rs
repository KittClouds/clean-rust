use serde::{Deserialize, Serialize};

pub const CONTRACT: &str = "jev-like-decision-world/v0.1";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum VariableRole {
    Latent,
    Observable,
    Derived,
    Nuisance,
    Context,
    DecisionRelevant,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum VariableKind {
    Boolean,
    Categorical,
    Ordinal,
    IntegerBounded,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Variable {
    pub id: String,
    pub role: VariableRole,
    pub kind: VariableKind,
    pub domain: Vec<String>,
    pub ordered: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Mechanism {
    pub target: String,
    pub parents: Vec<String>,
    pub table: Vec<f64>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Constraint {
    pub if_variable: String,
    pub if_value: u8,
    pub then_variable: String,
    pub then_value: u8,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct DerivedVariable {
    pub id: String,
    pub source_variable: String,
    pub mapping: Vec<u8>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ObservationChannel {
    pub id: String,
    pub source_variable: String,
    pub observed_domain: Vec<String>,
    pub likelihood_table: Vec<f64>,
    pub default_visibility_probability: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct WorldTemplate {
    pub family_id: String,
    pub template_id: String,
    pub version: u32,
    pub variables: Vec<Variable>,
    pub mechanisms: Vec<Mechanism>,
    pub constraints: Vec<Constraint>,
    pub observation_channels: Vec<ObservationChannel>,
    pub derived_variables: Vec<DerivedVariable>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct TemplateRef {
    pub family_id: String,
    pub template_id: String,
    pub version: u32,
}

impl From<&WorldTemplate> for TemplateRef {
    fn from(template: &WorldTemplate) -> Self {
        Self {
            family_id: template.family_id.clone(),
            template_id: template.template_id.clone(),
            version: template.version,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Visibility {
    Visible,
    Hidden,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct EvidenceFact {
    pub fact_id: String,
    pub source_variable: String,
    pub true_value: u8,
    pub visibility: Visibility,
    pub observed_value: Option<u8>,
    pub channel_id: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct EvidenceState {
    pub facts: Vec<EvidenceFact>,
    pub visible_fact_ids: Vec<String>,
    pub missing_fact_ids: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ChoiceMode {
    ClosedWorld,
    OpenWorld,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(tag = "primitive", rename_all = "snake_case")]
pub enum Query {
    Proposition {
        id: String,
        variable: String,
        value: u8,
    },
    Applicability {
        id: String,
        variable: String,
        value: u8,
    },
    Choice {
        id: String,
        variable: String,
        candidate_values: Vec<u8>,
        mode: ChoiceMode,
    },
    Ordinal {
        id: String,
        variable: String,
    },
    Abstain {
        id: String,
        variable: String,
        entropy_threshold: f64,
    },
}

impl Query {
    pub fn id(&self) -> &str {
        match self {
            Self::Proposition { id, .. }
            | Self::Applicability { id, .. }
            | Self::Choice { id, .. }
            | Self::Ordinal { id, .. }
            | Self::Abstain { id, .. } => id,
        }
    }

    pub fn variable(&self) -> &str {
        match self {
            Self::Proposition { variable, .. }
            | Self::Applicability { variable, .. }
            | Self::Choice { variable, .. }
            | Self::Ordinal { variable, .. }
            | Self::Abstain { variable, .. } => variable,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct NamedProbability {
    pub value: u8,
    pub probability: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(tag = "semantic_type", rename_all = "snake_case")]
pub enum GoldValue {
    Proposition {
        true_probability: f64,
        false_probability: f64,
    },
    IndependentApplicability {
        probability: f64,
    },
    Choice {
        mode: ChoiceMode,
        probabilities: Vec<NamedProbability>,
        other_probability: f64,
    },
    Ordinal {
        distribution: Vec<f64>,
        expected_value: f64,
        entropy: f64,
    },
    Abstention {
        posterior: Vec<f64>,
        entropy: f64,
        answerability: f64,
        abstain_recommended: bool,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SolverMethod {
    ExactEnumeration,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SolverReceipt {
    pub method: SolverMethod,
    pub template_id: String,
    pub conditioning_evidence: Vec<String>,
    pub approximation: bool,
    pub seed: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GoldTarget {
    pub query_id: String,
    pub value: GoldValue,
    pub solver: SolverReceipt,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RenderFormat {
    Prose,
    Json,
    Log,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Rendering {
    pub format: RenderFormat,
    pub text: String,
    pub source_fact_ids: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PerturbationClass {
    SurfaceInvariance,
    ObservationIntervention,
    WorldIntervention,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ExpectedRelation {
    StrictInvariant,
    Recomputed,
    DirectionalOnly,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct PerturbationLink {
    pub family_id: String,
    pub parent_episode_id: String,
    pub class: PerturbationClass,
    pub operation: String,
    pub affected_fact_ids: Vec<String>,
    pub affected_variable: Option<String>,
    pub expected_relation: ExpectedRelation,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AuthorityClass {
    SyntheticControl,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Provenance {
    pub generator_id: String,
    pub generator_version: String,
    pub seed: u64,
    pub world_sample_seed: u64,
    pub observation_seed: u64,
    pub renderer_seed: u64,
    pub semantic_fingerprint: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Episode {
    pub contract: String,
    pub episode_id: String,
    pub template: TemplateRef,
    pub authority: AuthorityClass,
    pub sampled_world: Vec<u8>,
    pub evidence_state: EvidenceState,
    pub queries: Vec<Query>,
    pub gold_targets: Vec<GoldTarget>,
    pub renderings: Vec<Rendering>,
    pub perturbation_links: Vec<PerturbationLink>,
    pub provenance: Provenance,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct PilotReport {
    pub contract: String,
    pub episode_count: usize,
    pub template_counts: std::collections::BTreeMap<String, usize>,
    pub entropy_bands: std::collections::BTreeMap<String, usize>,
    pub posterior_min: f64,
    pub posterior_max: f64,
    pub verified_episodes: usize,
    pub failed_episodes: usize,
}

impl WorldTemplate {
    pub fn variable_index(&self, id: &str) -> Option<usize> {
        self.variables.iter().position(|variable| variable.id == id)
    }

    pub fn variable(&self, id: &str) -> Option<&Variable> {
        self.variable_index(id).map(|index| &self.variables[index])
    }

    pub fn channel(&self, id: &str) -> Option<&ObservationChannel> {
        self.observation_channels
            .iter()
            .find(|channel| channel.id == id)
    }

    pub fn mechanism(&self, target: &str) -> Option<&Mechanism> {
        self.mechanisms
            .iter()
            .find(|mechanism| mechanism.target == target)
    }
}
