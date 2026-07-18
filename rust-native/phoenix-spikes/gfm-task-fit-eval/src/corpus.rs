use compact_str::CompactString;
use phoenix_revision_impact::{
    GraphGeneration, InferenceAuthority, InferenceEdgeSeed, InferenceNodeSeed,
    InferenceProjectionInput, RevisionAnalysisViews,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TaskTarget {
    Document,
    Entity,
    Chapter,
}

impl TaskTarget {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Document => "document",
            Self::Entity => "entity",
            Self::Chapter => "chapter",
        }
    }
}

#[derive(Clone, Debug)]
pub struct GoldTask {
    pub id: &'static str,
    pub family: &'static str,
    pub query: &'static str,
    pub start_ids: &'static [&'static str],
    pub target: TaskTarget,
    pub gold_ids: &'static [&'static str],
}

#[cfg(test)]
pub fn graph() -> phoenix_revision_impact::InferenceGraph {
    graph_with_first_embedding_suffix("")
}

pub fn graph_with_first_embedding_suffix(suffix: &str) -> phoenix_revision_impact::InferenceGraph {
    graph_with_first_dirty_suffix(suffix, "")
}

pub fn graph_with_first_dirty_suffix(
    embedding_suffix: &str,
    relation_suffix: &str,
) -> phoenix_revision_impact::InferenceGraph {
    let mut input = InferenceProjectionInput::default();
    for (index, (id, kind, text)) in NODES.iter().enumerate() {
        let embedding_text = if index == 0 && !embedding_suffix.is_empty() {
            format!("{text}{embedding_suffix}")
        } else {
            (*text).to_string()
        };
        input.accepted_nodes.push(InferenceNodeSeed {
            node_id: (*id).into(),
            node_type: (*kind).into(),
            embedding_text: embedding_text.into(),
        });
    }
    for (index, (source, relation, target)) in RELATIONS.iter().enumerate() {
        let relation = if index == 0 && !relation_suffix.is_empty() {
            format!("{relation}{relation_suffix}")
        } else {
            (*relation).to_string()
        };
        input
            .relations
            .push(edge(format!("relation:{index}"), source, &relation, target));
    }
    for (index, (document, entity)) in MEMBERSHIPS.iter().enumerate() {
        input.memberships.push(edge(
            format!("membership:{index}"),
            document,
            "contains",
            entity,
        ));
    }
    RevisionAnalysisViews::project(GraphGeneration(1), Vec::new(), input)
        .expect("task-fit graph must be valid")
        .inference_graph
}

fn edge(id: String, source: &str, relation: &str, target: &str) -> InferenceEdgeSeed {
    InferenceEdgeSeed {
        edge_id: CompactString::from(id),
        source_id: CompactString::from(source),
        target_id: CompactString::from(target),
        relation_type: CompactString::from(relation),
        authority: InferenceAuthority::Asserted,
        evidence_ids: vec![CompactString::from(format!("evidence:{source}:{target}"))],
        confidence_millis: 1_000,
    }
}

pub const TASKS: &[GoldTask] = &[
    GoldTask {
        id: "direct_fact",
        family: "direct_document",
        query: "Which document states who guards the Glass Archive?",
        start_ids: &["entity:glass_archive"],
        target: TaskTarget::Document,
        gold_ids: &["document:glass_archive"],
    },
    GoldTask {
        id: "direct_paraphrase",
        family: "direct_document",
        query: "Find the source describing the keeper responsible for the crystal records hall.",
        start_ids: &["entity:glass_archive"],
        target: TaskTarget::Document,
        gold_ids: &["document:glass_archive"],
    },
    GoldTask {
        id: "two_hop_apprentice",
        family: "multi_hop_document",
        query: "Which sources identify the archive guarded by the apprentice mentored by Ilyra?",
        start_ids: &["entity:ilyra"],
        target: TaskTarget::Document,
        gold_ids: &["document:ilyra_and_niko", "document:glass_archive"],
    },
    GoldTask {
        id: "four_hop_city",
        family: "multi_hop_document",
        query: "In which city is the archive guarded by Ilyra's apprentice located?",
        start_ids: &["entity:ilyra"],
        target: TaskTarget::Document,
        gold_ids: &[
            "document:ilyra_and_niko",
            "document:glass_archive",
            "document:veyra",
        ],
    },
    GoldTask {
        id: "possession_chain",
        family: "multi_hop_document",
        query: "Which sources explain how the unique Chronal Key could be used to open the Northern Vault?",
        start_ids: &["entity:chronal_key"],
        target: TaskTarget::Document,
        gold_ids: &["document:chronal_key", "document:northern_vault"],
    },
    GoldTask {
        id: "causal_chain",
        family: "causal_temporal_document",
        query: "Why did the beacon fail after Mara's warning was delivered?",
        start_ids: &["entity:mara_warning"],
        target: TaskTarget::Document,
        gold_ids: &["document:mara_recording", "document:beacon_failure"],
    },
    GoldTask {
        id: "temporal_order",
        family: "causal_temporal_document",
        query: "What happened after the eclipse and before the Northern Beacon failed?",
        start_ids: &["entity:eclipse"],
        target: TaskTarget::Document,
        gold_ids: &["document:mara_recording", "document:beacon_failure"],
    },
    GoldTask {
        id: "true_false_form",
        family: "query_form_robustness",
        query: "True or false: Hazel, rather than Kai, possesses the only Chronal Key.",
        start_ids: &["entity:chronal_key"],
        target: TaskTarget::Document,
        gold_ids: &["document:chronal_key"],
    },
    GoldTask {
        id: "multiple_choice_form",
        family: "query_form_robustness",
        query: "Who operates the Chronal Key at the vault: A) Kai, B) Hazel, C) Silas, or D) Mara?",
        start_ids: &["entity:chronal_key"],
        target: TaskTarget::Document,
        gold_ids: &["document:chronal_key", "document:northern_vault"],
    },
    GoldTask {
        id: "open_ended_form",
        family: "query_form_robustness",
        query: "Explain the chain connecting Ilyra to the city of Veyra through her student and his duty.",
        start_ids: &["entity:ilyra"],
        target: TaskTarget::Document,
        gold_ids: &[
            "document:ilyra_and_niko",
            "document:glass_archive",
            "document:veyra",
        ],
    },
    GoldTask {
        id: "near_name_distractors",
        family: "distractor_resistance",
        query: "Where is Niko's Glass Archive located? Do not confuse it with Nika's Iron Archive.",
        start_ids: &["entity:niko"],
        target: TaskTarget::Document,
        gold_ids: &["document:glass_archive", "document:veyra"],
    },
    GoldTask {
        id: "rare_relation",
        family: "distractor_resistance",
        query: "Which source records the lunar fracture as the cause of the Northern Beacon failure?",
        start_ids: &["entity:lunar_fracture"],
        target: TaskTarget::Document,
        gold_ids: &["document:beacon_failure"],
    },
    GoldTask {
        id: "entity_apprentice",
        family: "typed_entity",
        query: "Who was mentored by Ilyra?",
        start_ids: &["entity:ilyra"],
        target: TaskTarget::Entity,
        gold_ids: &["entity:niko"],
    },
    GoldTask {
        id: "entity_possessor",
        family: "typed_entity",
        query: "Who possesses the unique Chronal Key?",
        start_ids: &["entity:chronal_key"],
        target: TaskTarget::Entity,
        gold_ids: &["entity:hazel"],
    },
    GoldTask {
        id: "entity_cause",
        family: "typed_entity",
        query: "What caused the Northern Beacon to fail?",
        start_ids: &["entity:northern_beacon"],
        target: TaskTarget::Entity,
        gold_ids: &["entity:lunar_fracture"],
    },
    GoldTask {
        id: "hierarchy_archive",
        family: "hierarchical_node",
        query: "Which chapter contains the scene where Niko guards the Glass Archive?",
        start_ids: &["entity:niko"],
        target: TaskTarget::Chapter,
        gold_ids: &["chapter:archive"],
    },
    GoldTask {
        id: "hierarchy_beacon",
        family: "hierarchical_node",
        query: "Which chapter contains Mara's warning and the later beacon failure?",
        start_ids: &["entity:mara_warning"],
        target: TaskTarget::Chapter,
        gold_ids: &["chapter:beacon"],
    },
];

const NODES: &[(&str, &str, &str)] = &[
    (
        "document:ilyra_and_niko",
        "document",
        "Ilyra trained Niko as her apprentice in the observatory school.",
    ),
    (
        "document:glass_archive",
        "document",
        "Niko guards the Glass Archive, a crystal records hall in Veyra.",
    ),
    (
        "document:veyra",
        "document",
        "Veyra is the city containing the Glass Archive and the observatory school.",
    ),
    (
        "document:chronal_key",
        "document",
        "Hazel possesses the only Chronal Key. Kai knows she is its keeper.",
    ),
    (
        "document:northern_vault",
        "document",
        "Hazel operates the Chronal Key to open the Northern Vault at the Northern Fort.",
    ),
    (
        "document:mara_recording",
        "document",
        "Mara recorded a warning after the eclipse and before her death. The warning was delivered later.",
    ),
    (
        "document:beacon_failure",
        "document",
        "A lunar fracture triggered by the delivered warning caused the Northern Beacon to fail.",
    ),
    (
        "document:iron_archive",
        "document",
        "Nika guards the Iron Archive in Veira. It stores metal tax records.",
    ),
    (
        "document:glass_foundry",
        "document",
        "Nikolas operates a glass foundry outside Veyra and has no archive duties.",
    ),
    (
        "document:southern_beacon",
        "document",
        "The Southern Beacon survived the eclipse because its mirror was shielded.",
    ),
    (
        "document:duplicate_key_rumor",
        "document",
        "Silas repeats a false rumor that Kai owns a duplicate key.",
    ),
    (
        "document:ordinary_route",
        "document",
        "Ordinary travel from Veyra to the Northern Fort takes eight hours.",
    ),
    ("entity:ilyra", "entity", "Ilyra, an observatory mentor"),
    (
        "entity:niko",
        "entity",
        "Niko, apprentice of Ilyra and guard of the Glass Archive",
    ),
    (
        "entity:glass_archive",
        "entity",
        "Glass Archive, crystal records hall in Veyra",
    ),
    ("entity:veyra", "entity", "Veyra, city of the Glass Archive"),
    (
        "entity:chronal_key",
        "entity",
        "Chronal Key, unique vault key",
    ),
    (
        "entity:hazel",
        "entity",
        "Hazel, possessor and operator of the Chronal Key",
    ),
    (
        "entity:northern_vault",
        "entity",
        "Northern Vault at the Northern Fort",
    ),
    ("entity:northern_fort", "entity", "Northern Fort"),
    ("entity:eclipse", "entity", "the eclipse"),
    (
        "entity:mara_warning",
        "entity",
        "Mara's prerecorded warning",
    ),
    (
        "entity:lunar_fracture",
        "entity",
        "lunar fracture caused by the warning",
    ),
    ("entity:northern_beacon", "entity", "Northern Beacon"),
    ("entity:nika", "entity", "Nika, guard of the Iron Archive"),
    ("entity:iron_archive", "entity", "Iron Archive in Veira"),
    (
        "entity:veira",
        "entity",
        "Veira, a mining town distinct from Veyra",
    ),
    (
        "entity:nikolas",
        "entity",
        "Nikolas, glass foundry operator",
    ),
    ("entity:southern_beacon", "entity", "Southern Beacon"),
    (
        "entity:kai",
        "entity",
        "Kai, companion who does not possess the Chronal Key",
    ),
    (
        "entity:silas",
        "entity",
        "Silas, source of the duplicate-key rumor",
    ),
    (
        "chapter:archive",
        "chapter",
        "Archive chapter containing Ilyra, Niko, the Glass Archive, and Veyra",
    ),
    (
        "chapter:key",
        "chapter",
        "Vault chapter containing Hazel, the Chronal Key, and the Northern Vault",
    ),
    (
        "chapter:beacon",
        "chapter",
        "Beacon chapter containing the eclipse, Mara's warning, lunar fracture, and beacon failure",
    ),
];

const RELATIONS: &[(&str, &str, &str)] = &[
    ("entity:ilyra", "mentored", "entity:niko"),
    ("entity:niko", "guards", "entity:glass_archive"),
    ("entity:glass_archive", "located_in", "entity:veyra"),
    ("entity:chronal_key", "possessed_by", "entity:hazel"),
    ("entity:hazel", "operates", "entity:chronal_key"),
    ("entity:chronal_key", "opens", "entity:northern_vault"),
    (
        "entity:northern_vault",
        "located_in",
        "entity:northern_fort",
    ),
    ("entity:eclipse", "followed_by", "entity:mara_warning"),
    ("entity:mara_warning", "triggered", "entity:lunar_fracture"),
    (
        "entity:lunar_fracture",
        "caused_failure_of",
        "entity:northern_beacon",
    ),
    ("entity:nika", "guards", "entity:iron_archive"),
    ("entity:iron_archive", "located_in", "entity:veira"),
    ("entity:nikolas", "operates", "entity:glass_archive"),
    ("entity:silas", "spread_false_rumor_about", "entity:kai"),
    ("chapter:archive", "contains", "entity:ilyra"),
    ("chapter:archive", "contains", "entity:niko"),
    ("chapter:archive", "contains", "entity:glass_archive"),
    ("chapter:key", "contains", "entity:chronal_key"),
    ("chapter:key", "contains", "entity:hazel"),
    ("chapter:key", "contains", "entity:northern_vault"),
    ("chapter:beacon", "contains", "entity:eclipse"),
    ("chapter:beacon", "contains", "entity:mara_warning"),
    ("chapter:beacon", "contains", "entity:northern_beacon"),
];

const MEMBERSHIPS: &[(&str, &str)] = &[
    ("document:ilyra_and_niko", "entity:ilyra"),
    ("document:ilyra_and_niko", "entity:niko"),
    ("document:glass_archive", "entity:niko"),
    ("document:glass_archive", "entity:glass_archive"),
    ("document:glass_archive", "entity:veyra"),
    ("document:veyra", "entity:veyra"),
    ("document:chronal_key", "entity:chronal_key"),
    ("document:chronal_key", "entity:hazel"),
    ("document:chronal_key", "entity:kai"),
    ("document:northern_vault", "entity:hazel"),
    ("document:northern_vault", "entity:chronal_key"),
    ("document:northern_vault", "entity:northern_vault"),
    ("document:northern_vault", "entity:northern_fort"),
    ("document:mara_recording", "entity:eclipse"),
    ("document:mara_recording", "entity:mara_warning"),
    ("document:beacon_failure", "entity:mara_warning"),
    ("document:beacon_failure", "entity:lunar_fracture"),
    ("document:beacon_failure", "entity:northern_beacon"),
    ("document:iron_archive", "entity:nika"),
    ("document:iron_archive", "entity:iron_archive"),
    ("document:iron_archive", "entity:veira"),
    ("document:glass_foundry", "entity:nikolas"),
    ("document:glass_foundry", "entity:veyra"),
    ("document:southern_beacon", "entity:eclipse"),
    ("document:southern_beacon", "entity:southern_beacon"),
    ("document:duplicate_key_rumor", "entity:silas"),
    ("document:duplicate_key_rumor", "entity:kai"),
    ("document:duplicate_key_rumor", "entity:chronal_key"),
    ("document:ordinary_route", "entity:veyra"),
    ("document:ordinary_route", "entity:northern_fort"),
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn task_contract_covers_advertised_retrieval_shapes() {
        assert!(TASKS.iter().any(|task| task.family == "multi_hop_document"));
        assert!(TASKS.iter().any(|task| task.target == TaskTarget::Entity));
        assert!(TASKS.iter().any(|task| task.target == TaskTarget::Chapter));
        let graph = graph();
        assert_eq!(graph.receipt().excluded_candidate_edges, 0);
        assert!(!graph.nodes().is_empty());
    }
}
