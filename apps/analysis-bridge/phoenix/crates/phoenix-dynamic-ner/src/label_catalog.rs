//! Label catalog for dynamic NER packs.
//!
//! This module keeps label vocabulary policy separate from routing. Routers
//! decide which domain is active; the catalog decides which small label pack
//! that domain is allowed to expose to the span model.

use smallvec::SmallVec;

use crate::types::{DomainProfile, EntityLabel};

pub const LABEL_ONTOLOGY_VERSION: &str = "phoenix.label-ontology.v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LabelFamily {
    Character,
    Place,
    Group,
    Object,
    Narrative,
    Concept,
    Technical,
    Legal,
    Academic,
    Memory,
    Attribute,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KindCompatibility {
    Character,
    Npc,
    Creature,
    Location,
    Faction,
    Organization,
    Item,
    Event,
    Concept,
    Any,
    Review,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LabelSpec {
    pub label: &'static str,
    pub family: LabelFamily,
    pub description: &'static str,
    pub aliases: &'static [&'static str],
    pub compatibility: KindCompatibility,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ConfusionGroup {
    pub id: &'static str,
    pub labels: &'static [&'static str],
    pub rule: &'static str,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DomainLabelPack {
    pub version: &'static str,
    pub domain: DomainProfile,
    pub subdomain: &'static str,
    pub positive: &'static [&'static str],
    pub negative: &'static [&'static str],
    pub confusion_groups: &'static [&'static str],
    pub max_positive: usize,
}

pub const UNIVERSAL_CORE: &[&str] = &[
    "Character",
    "Organization",
    "Location",
    "Event",
    "Artifact",
    "Concept",
];

pub const STORY_LABELS: &[&str] = &[
    "Npc", "Creature", "Species", "Weapon", "Ability", "Rank", "Faction",
];

pub const FANTASY_LABELS: &[&str] = &[
    "Creature", "Species", "Monster", "Weapon", "Artifact", "Ability", "Spell",
];

pub const CORPORATE_LABELS: &[&str] = &[
    "Executive",
    "Department",
    "Product",
    "Metric",
    "Initiative",
    "Risk",
];

pub const TECHNICAL_LABELS: &[&str] = &[
    "Library",
    "Function",
    "Module",
    "Error",
    "Benchmark",
    "Algorithm",
];

pub const LEGAL_LABELS: &[&str] = &[
    "Statute",
    "Court",
    "Ruling",
    "Party",
    "Jurisdiction",
    "Claim",
];

pub const ACADEMIC_LABELS: &[&str] = &[
    "Researcher",
    "Institution",
    "Paper",
    "Theory",
    "Dataset",
    "Method",
];

pub const MEMORY_LABELS: &[&str] = &[
    "State",
    "Goal",
    "Relationship",
    "Object",
    "Ability",
    "Emotion",
];

pub const GENERAL_LABELS: &[&str] = &["Role", "Object", "Attribute"];

const TECHNICAL_NEGATIVES: &[&str] = &["FilePath", "CliFlag", "LogLevel"];
const LEGAL_NEGATIVES: &[&str] = &["Boilerplate"];
const EMPTY_LABELS: &[&str] = &[];

pub const CONFUSION_GROUPS: &[ConfusionGroup] = &[
    ConfusionGroup {
        id: "person-role-creature",
        labels: &["Character", "Npc", "Creature", "Species", "Role"],
        rule: "Prefer named identity labels for unique people; use Creature/Species for non-person beings or taxonomic classes.",
    },
    ConfusionGroup {
        id: "place-org-faction",
        labels: &["Location", "Region", "Landmark", "Organization", "Faction"],
        rule: "Places host events; organizations and factions act. Defer when a surface can be both.",
    },
    ConfusionGroup {
        id: "object-artifact-weapon",
        labels: &["Object", "Item", "Artifact", "Weapon"],
        rule: "Use Artifact for named/special objects, Weapon for combat tools, Item/Object for generic mentions.",
    },
    ConfusionGroup {
        id: "narrative-state-event",
        labels: &["Event", "Scene", "State", "Goal", "Relationship"],
        rule: "Use Event for happenings, State for conditions, Goal for desired outcomes, Relationship for durable links.",
    },
    ConfusionGroup {
        id: "technical-symbols",
        labels: &["Library", "Function", "Module", "Algorithm", "Benchmark"],
        rule: "Use Library/Module for containers, Function for callable symbols, Algorithm for methods, Benchmark for measurements.",
    },
];

pub const LABEL_SPECS: &[LabelSpec] = &[
    spec(
        "Character",
        LabelFamily::Character,
        "named story person or primary cast identity",
        &["person", "protagonist"],
        KindCompatibility::Character,
    ),
    spec(
        "Npc",
        LabelFamily::Character,
        "non-player or secondary story person",
        &["non player character", "supporting character"],
        KindCompatibility::Npc,
    ),
    spec(
        "Creature",
        LabelFamily::Character,
        "living non-human actor or being",
        &["beast", "being"],
        KindCompatibility::Creature,
    ),
    spec(
        "Species",
        LabelFamily::Character,
        "taxonomic or race-level being class",
        &["race", "people"],
        KindCompatibility::Creature,
    ),
    spec(
        "Monster",
        LabelFamily::Character,
        "hostile or mythic creature class",
        &["devil", "demon"],
        KindCompatibility::Creature,
    ),
    spec(
        "Organization",
        LabelFamily::Group,
        "formal organization, company, or institution",
        &["org", "company"],
        KindCompatibility::Organization,
    ),
    spec(
        "Faction",
        LabelFamily::Group,
        "story faction, clan, guild, gang, or alliance",
        &["clan", "guild", "gang"],
        KindCompatibility::Faction,
    ),
    spec(
        "Location",
        LabelFamily::Place,
        "named place, settlement, region, or venue",
        &["place", "site"],
        KindCompatibility::Location,
    ),
    spec(
        "Region",
        LabelFamily::Place,
        "larger bounded geographic area",
        &["area", "territory"],
        KindCompatibility::Location,
    ),
    spec(
        "Landmark",
        LabelFamily::Place,
        "specific point of interest or notable site",
        &["monument"],
        KindCompatibility::Location,
    ),
    spec(
        "Event",
        LabelFamily::Narrative,
        "happening, incident, battle, meeting, or plot occurrence",
        &["incident"],
        KindCompatibility::Event,
    ),
    spec(
        "Scene",
        LabelFamily::Narrative,
        "local narrative scene or beat container",
        &["beat"],
        KindCompatibility::Event,
    ),
    spec(
        "Artifact",
        LabelFamily::Object,
        "named or important object with narrative weight",
        &["relic"],
        KindCompatibility::Item,
    ),
    spec(
        "Item",
        LabelFamily::Object,
        "portable object or inventory-like thing",
        &["object"],
        KindCompatibility::Item,
    ),
    spec(
        "Object",
        LabelFamily::Object,
        "generic object when a sharper object label is unavailable",
        &["thing"],
        KindCompatibility::Item,
    ),
    spec(
        "Weapon",
        LabelFamily::Object,
        "weapon, blade, firearm, or combat tool",
        &["sword", "blade"],
        KindCompatibility::Item,
    ),
    spec(
        "Ability",
        LabelFamily::Concept,
        "skill, power, capability, or special technique",
        &["power", "skill"],
        KindCompatibility::Concept,
    ),
    spec(
        "Spell",
        LabelFamily::Concept,
        "magic spell or named supernatural technique",
        &["magic"],
        KindCompatibility::Concept,
    ),
    spec(
        "Concept",
        LabelFamily::Concept,
        "abstract idea, doctrine, mechanic, or named principle",
        &["idea"],
        KindCompatibility::Concept,
    ),
    spec(
        "Rank",
        LabelFamily::Attribute,
        "rank, title, level, or hierarchy marker",
        &["title"],
        KindCompatibility::Review,
    ),
    spec(
        "Role",
        LabelFamily::Attribute,
        "social or functional role mention",
        &["job"],
        KindCompatibility::Review,
    ),
    spec(
        "State",
        LabelFamily::Memory,
        "durable state or condition",
        &["condition"],
        KindCompatibility::Review,
    ),
    spec(
        "Goal",
        LabelFamily::Memory,
        "desired objective or intention",
        &["objective"],
        KindCompatibility::Review,
    ),
    spec(
        "Relationship",
        LabelFamily::Memory,
        "durable relation between entities",
        &["bond"],
        KindCompatibility::Review,
    ),
    spec(
        "Library",
        LabelFamily::Technical,
        "software library or reusable package",
        &["crate", "package"],
        KindCompatibility::Concept,
    ),
    spec(
        "Function",
        LabelFamily::Technical,
        "callable function, method, or command",
        &["method"],
        KindCompatibility::Concept,
    ),
    spec(
        "Module",
        LabelFamily::Technical,
        "software module, file unit, or namespace",
        &["namespace"],
        KindCompatibility::Concept,
    ),
    spec(
        "Error",
        LabelFamily::Technical,
        "software error, failure, or diagnostic",
        &["exception"],
        KindCompatibility::Event,
    ),
    spec(
        "Benchmark",
        LabelFamily::Technical,
        "performance measurement or benchmark suite",
        &["perf test"],
        KindCompatibility::Event,
    ),
    spec(
        "Algorithm",
        LabelFamily::Technical,
        "algorithmic method or computational procedure",
        &["methodology"],
        KindCompatibility::Concept,
    ),
    spec(
        "Executive",
        LabelFamily::Group,
        "corporate leader or decision maker",
        &["leader"],
        KindCompatibility::Npc,
    ),
    spec(
        "Department",
        LabelFamily::Group,
        "company department or business unit",
        &["team"],
        KindCompatibility::Organization,
    ),
    spec(
        "Product",
        LabelFamily::Object,
        "commercial product or product line",
        &["sku"],
        KindCompatibility::Item,
    ),
    spec(
        "Metric",
        LabelFamily::Attribute,
        "business metric or measurement",
        &["kpi"],
        KindCompatibility::Review,
    ),
    spec(
        "Initiative",
        LabelFamily::Narrative,
        "corporate initiative, program, or roadmap effort",
        &["program"],
        KindCompatibility::Event,
    ),
    spec(
        "Risk",
        LabelFamily::Attribute,
        "risk, exposure, or threat",
        &["hazard"],
        KindCompatibility::Review,
    ),
    spec(
        "Statute",
        LabelFamily::Legal,
        "law, statute, or regulatory rule",
        &["law"],
        KindCompatibility::Concept,
    ),
    spec(
        "Court",
        LabelFamily::Legal,
        "court or legal venue",
        &["tribunal"],
        KindCompatibility::Organization,
    ),
    spec(
        "Ruling",
        LabelFamily::Legal,
        "judgment, order, or legal decision",
        &["judgment"],
        KindCompatibility::Event,
    ),
    spec(
        "Party",
        LabelFamily::Legal,
        "legal party or litigant",
        &["litigant"],
        KindCompatibility::Npc,
    ),
    spec(
        "Jurisdiction",
        LabelFamily::Legal,
        "legal jurisdiction or governing authority",
        &["venue"],
        KindCompatibility::Location,
    ),
    spec(
        "Claim",
        LabelFamily::Legal,
        "legal claim, count, or asserted right",
        &["count"],
        KindCompatibility::Concept,
    ),
    spec(
        "Researcher",
        LabelFamily::Academic,
        "academic researcher or scholar",
        &["scholar"],
        KindCompatibility::Character,
    ),
    spec(
        "Institution",
        LabelFamily::Academic,
        "academic or research institution",
        &["university"],
        KindCompatibility::Organization,
    ),
    spec(
        "Paper",
        LabelFamily::Academic,
        "research paper or publication",
        &["publication"],
        KindCompatibility::Item,
    ),
    spec(
        "Theory",
        LabelFamily::Academic,
        "theory or conceptual framework",
        &["framework"],
        KindCompatibility::Concept,
    ),
    spec(
        "Dataset",
        LabelFamily::Academic,
        "dataset or corpus",
        &["corpus"],
        KindCompatibility::Item,
    ),
    spec(
        "Method",
        LabelFamily::Academic,
        "research method or protocol",
        &["protocol"],
        KindCompatibility::Concept,
    ),
    spec(
        "Attribute",
        LabelFamily::Attribute,
        "descriptive attribute or property",
        &["property"],
        KindCompatibility::Review,
    ),
    spec(
        "Member",
        LabelFamily::Group,
        "member of a faction or group",
        &["ally"],
        KindCompatibility::Npc,
    ),
    spec(
        "Enemy",
        LabelFamily::Group,
        "opposed actor or hostile group member",
        &["foe"],
        KindCompatibility::Npc,
    ),
    spec(
        "Alliance",
        LabelFamily::Group,
        "cooperation between factions or groups",
        &["pact"],
        KindCompatibility::Organization,
    ),
];

const fn spec(
    label: &'static str,
    family: LabelFamily,
    description: &'static str,
    aliases: &'static [&'static str],
    compatibility: KindCompatibility,
) -> LabelSpec {
    LabelSpec {
        label,
        family,
        description,
        aliases,
        compatibility,
    }
}

pub const ROUTABLE_LABELS: &[&str] = &[
    "Character",
    "Npc",
    "Organization",
    "Faction",
    "Location",
    "Event",
    "Artifact",
    "Item",
    "Object",
    "Weapon",
    "Concept",
    "Creature",
    "Species",
    "Monster",
    "Ability",
    "Spell",
    "Rank",
    "Role",
    "State",
    "Goal",
    "Relationship",
    "Region",
    "Landmark",
];

pub fn labels_for_domain(domain: DomainProfile) -> &'static [&'static str] {
    domain_pack(domain).positive
}

pub fn domain_pack(domain: DomainProfile) -> DomainLabelPack {
    match domain {
        DomainProfile::Fantasy => pack(
            domain,
            "fantasy-narrative",
            FANTASY_LABELS,
            EMPTY_LABELS,
            &["person-role-creature", "object-artifact-weapon"],
        ),
        DomainProfile::Corporate => pack(
            domain,
            "corporate-operations",
            CORPORATE_LABELS,
            EMPTY_LABELS,
            &["place-org-faction"],
        ),
        DomainProfile::Technical => pack(
            domain,
            "software-systems",
            TECHNICAL_LABELS,
            TECHNICAL_NEGATIVES,
            &["technical-symbols"],
        ),
        DomainProfile::Legal => pack(
            domain,
            "legal-analysis",
            LEGAL_LABELS,
            LEGAL_NEGATIVES,
            &["place-org-faction"],
        ),
        DomainProfile::Academic => pack(
            domain,
            "research",
            ACADEMIC_LABELS,
            EMPTY_LABELS,
            &["technical-symbols"],
        ),
        DomainProfile::Memory => pack(
            domain,
            "state-memory",
            MEMORY_LABELS,
            EMPTY_LABELS,
            &["narrative-state-event"],
        ),
        DomainProfile::Story => pack(
            domain,
            "story-cast-world",
            STORY_LABELS,
            EMPTY_LABELS,
            &[
                "person-role-creature",
                "place-org-faction",
                "object-artifact-weapon",
            ],
        ),
        DomainProfile::General => pack(
            domain,
            "general",
            GENERAL_LABELS,
            EMPTY_LABELS,
            &["narrative-state-event"],
        ),
    }
}

const fn pack(
    domain: DomainProfile,
    subdomain: &'static str,
    positive: &'static [&'static str],
    negative: &'static [&'static str],
    confusion_groups: &'static [&'static str],
) -> DomainLabelPack {
    DomainLabelPack {
        version: LABEL_ONTOLOGY_VERSION,
        domain,
        subdomain,
        positive,
        negative,
        confusion_groups,
        max_positive: 12,
    }
}

pub fn negative_labels_for_domain(domain: DomainProfile) -> SmallVec<[EntityLabel; 8]> {
    let mut labels = SmallVec::<[EntityLabel; 8]>::new();
    for label in domain_pack(domain).negative {
        let raw = label.trim();
        if raw.is_empty()
            || labels
                .iter()
                .any(|existing| existing.as_str().eq_ignore_ascii_case(raw))
        {
            continue;
        }
        labels.push(EntityLabel::new(canonical_label(raw).unwrap_or(raw)));
    }
    labels
}

pub fn push_domain_labels(
    target: &mut SmallVec<[EntityLabel; 16]>,
    domain: DomainProfile,
    limit: usize,
) {
    let pack = domain_pack(domain);
    push_labels(target, pack.positive, limit.min(pack.max_positive));
}

pub fn push_labels(target: &mut SmallVec<[EntityLabel; 16]>, labels: &[&str], limit: usize) {
    for label in labels {
        if target.len() >= limit {
            break;
        }
        push_unique_label(target, EntityLabel::new(label));
    }
}

pub fn push_unique_label(target: &mut SmallVec<[EntityLabel; 16]>, label: EntityLabel) {
    let raw = label.as_str().trim();
    if raw.is_empty() {
        return;
    }
    let label = EntityLabel::new(canonical_label(raw).unwrap_or(raw));
    if target
        .iter()
        .any(|existing| existing.as_str().eq_ignore_ascii_case(label.as_str()))
    {
        return;
    }
    target.push(label);
}

pub fn canonical_label(label: &str) -> Option<&'static str> {
    let trimmed = label.trim();
    LABEL_SPECS.iter().find_map(|spec| {
        if spec.label.eq_ignore_ascii_case(trimmed)
            || spec
                .aliases
                .iter()
                .any(|alias| alias.eq_ignore_ascii_case(trimmed))
        {
            Some(spec.label)
        } else {
            None
        }
    })
}

pub fn label_spec(label: &str) -> Option<&'static LabelSpec> {
    let canonical = canonical_label(label)?;
    LABEL_SPECS.iter().find(|spec| spec.label == canonical)
}

pub fn label_description(label: &str) -> Option<&'static str> {
    label_spec(label).map(|spec| spec.description)
}

pub fn label_family(label: &str) -> Option<LabelFamily> {
    label_spec(label).map(|spec| spec.family)
}

pub fn label_compatibility(label: &str) -> Option<KindCompatibility> {
    label_spec(label).map(|spec| spec.compatibility)
}

pub fn confusion_group(id: &str) -> Option<&'static ConfusionGroup> {
    CONFUSION_GROUPS.iter().find(|group| group.id == id)
}

pub fn labels_are_confusable(left: &str, right: &str) -> bool {
    let Some(left) = canonical_label(left) else {
        return false;
    };
    let Some(right) = canonical_label(right) else {
        return false;
    };
    if left == right {
        return false;
    }
    CONFUSION_GROUPS
        .iter()
        .any(|group| group.labels.contains(&left) && group.labels.contains(&right))
}
