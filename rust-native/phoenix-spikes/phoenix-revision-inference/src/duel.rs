use std::collections::{BTreeMap, BTreeSet};

use compact_str::{CompactString, format_compact};
use phoenix_revision_impact::truth_adapter::gold_harness::{
    GoldProjectionCase, analyze_case, gold_fixtures,
};
use phoenix_revision_impact::{
    GraphGeneration, InferenceAuthority, InferenceEdgeSeed, InferenceGraph, InferenceNodeSeed,
    InferenceProjectionInput, RevisionAnalysisViews, RevisionImpactReport,
};
use phoenix_types::{
    GoldMutationFamily, ImpactClassification, RevisionImpactGoldCase, StoryMutation,
};
use serde::{Deserialize, Serialize};

use crate::{InferenceArtifactError, Result};

pub const DUEL_GENERATION: GraphGeneration = GraphGeneration(73);

pub struct GoldDuelProjection {
    pub graph: InferenceGraph,
    pub cases: Vec<GoldDuelCase>,
    pub excluded_candidate_edges: usize,
}

pub struct GoldDuelCase {
    pub gold: RevisionImpactGoldCase,
    pub deterministic_report: RevisionImpactReport,
    pub start_entity_id: CompactString,
    pub start_node_ids: Vec<CompactString>,
    pub dynamic_query: CompactString,
    pub cached_queries: BTreeMap<CompactString, CompactString>,
    pub scene_evidence: BTreeMap<CompactString, Vec<CompactString>>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DuelArmMetrics {
    pub affected_scene_recall_at_1_bp: u16,
    pub affected_scene_recall_at_3_bp: u16,
    pub affected_scene_recall_at_5_bp: u16,
    pub mean_first_broken_rank_millis: u32,
    pub review_minutes_saved_proxy_millis: i64,
    pub suspicious_usefulness_proxy_bp: u16,
    pub overlap_with_deterministic_at_5_bp: u16,
}

pub fn build_gold_duel_projection() -> Result<GoldDuelProjection> {
    let (gold, projection) = gold_fixtures();
    let mut nodes = BTreeMap::<CompactString, InferenceNodeSeed>::new();
    let mut relations = Vec::new();
    let mut memberships = Vec::new();
    let mut cases = Vec::with_capacity(gold.cases.len());

    for gold_case in gold.cases {
        let projection_case = find_projection_case(&projection.cases, &gold_case);
        let analysis = analyze_case(&gold_case, projection_case);
        let family = family_key(gold_case.family);
        let start_entity_id = format_compact!("entity:mutation:{family}");
        let source_node_id = mutation_node_id(&gold_case.mutation, family);
        insert_node(
            &mut nodes,
            &start_entity_id,
            "entity",
            format_compact!("revision mutation: {}", gold_case.title),
        );
        insert_node(
            &mut nodes,
            &source_node_id,
            mutation_node_type(&gold_case.mutation),
            mutation_embedding_text(&gold_case),
        );
        push_relation(
            &mut relations,
            format_compact!("edge:{family}:mutation_source"),
            &start_entity_id,
            &source_node_id,
            "mutation_source",
            InferenceAuthority::Asserted,
            vec![format_compact!("evidence:{family}:mutation")],
        );

        let event_id = format_compact!("event:revision:{family}");
        let causal_id = format_compact!("causal_claim:revision:{family}");
        insert_node(
            &mut nodes,
            &event_id,
            "event",
            format_compact!("counterfactual event for {}", gold_case.title),
        );
        insert_node(
            &mut nodes,
            &causal_id,
            "causal_claim",
            format_compact!("causal consequences of {}", gold_case.title),
        );
        push_relation(
            &mut relations,
            format_compact!("edge:{family}:event"),
            &source_node_id,
            &event_id,
            "changes_event",
            InferenceAuthority::Accepted,
            Vec::new(),
        );
        push_relation(
            &mut relations,
            format_compact!("edge:{family}:causal"),
            &event_id,
            &causal_id,
            "causes_revision_ripple",
            InferenceAuthority::Accepted,
            Vec::new(),
        );

        let mut scene_evidence = BTreeMap::new();
        let mut added_scenes = BTreeSet::new();
        for (index, impact) in gold_case.expected_impacts.iter().enumerate() {
            let evidence = format_compact!("evidence:{family}:impact:{index}");
            if added_scenes.insert(impact.scene_id.0.clone()) {
                add_scene(
                    SceneSeedContext {
                        nodes: &mut nodes,
                        relations: &mut relations,
                        memberships: &mut memberships,
                        start_entity_id: &start_entity_id,
                        source_node_id: &source_node_id,
                        family,
                    },
                    impact.scene_id.0.as_str(),
                    impact.rationale.as_str(),
                    evidence.clone(),
                );
            }
            scene_evidence
                .entry(impact.scene_id.0.clone())
                .or_insert_with(Vec::new)
                .push(evidence.clone());
            for kind in &impact.constraint_kinds {
                let constraint_id = format_compact!("constraint:{family}:{index}:{kind:?}");
                insert_node(
                    &mut nodes,
                    &constraint_id,
                    "constraint",
                    format_compact!("{kind:?}: {}", impact.rationale),
                );
                push_relation(
                    &mut relations,
                    format_compact!("edge:{constraint_id}:source"),
                    &source_node_id,
                    &constraint_id,
                    "invalidates_constraint",
                    InferenceAuthority::Asserted,
                    vec![evidence.clone()],
                );
                push_relation(
                    &mut relations,
                    format_compact!("edge:{constraint_id}:scene"),
                    &constraint_id,
                    impact.scene_id.0.as_str(),
                    "constraint_affects_scene",
                    InferenceAuthority::Asserted,
                    vec![evidence.clone()],
                );
            }
        }
        for (index, unknown) in gold_case.expected_unknowns.iter().enumerate() {
            let evidence = format_compact!("evidence:{family}:unknown:{index}");
            if added_scenes.insert(unknown.scene_id.0.clone()) {
                add_scene(
                    SceneSeedContext {
                        nodes: &mut nodes,
                        relations: &mut relations,
                        memberships: &mut memberships,
                        start_entity_id: &start_entity_id,
                        source_node_id: &source_node_id,
                        family,
                    },
                    unknown.scene_id.0.as_str(),
                    unknown.rationale.as_str(),
                    evidence.clone(),
                );
            }
            scene_evidence
                .entry(unknown.scene_id.0.clone())
                .or_insert_with(Vec::new)
                .push(evidence);
        }
        for (index, repair) in gold_case.reasonable_repairs.iter().enumerate() {
            let repair_id = repair.repair_id.0.clone();
            insert_node(
                &mut nodes,
                &repair_id,
                "repair_candidate",
                format_compact!("{:?}: {}", repair.kind, repair.rationale),
            );
            push_relation(
                &mut relations,
                format_compact!("edge:{family}:repair:{index}"),
                &source_node_id,
                &repair_id,
                "suggests_repair",
                InferenceAuthority::Accepted,
                Vec::new(),
            );
            for (target_index, scene_id) in repair.target_scene_ids.iter().enumerate() {
                let evidence = format_compact!("evidence:{family}:repair:{index}:{target_index}");
                if added_scenes.insert(scene_id.0.clone()) {
                    add_scene(
                        SceneSeedContext {
                            nodes: &mut nodes,
                            relations: &mut relations,
                            memberships: &mut memberships,
                            start_entity_id: &start_entity_id,
                            source_node_id: &source_node_id,
                            family,
                        },
                        scene_id.0.as_str(),
                        repair.rationale.as_str(),
                        evidence.clone(),
                    );
                }
                push_relation(
                    &mut relations,
                    format_compact!("edge:{family}:repair_target:{index}:{target_index}"),
                    &repair_id,
                    scene_id.0.as_str(),
                    "repairs_scene",
                    InferenceAuthority::Accepted,
                    vec![evidence.clone()],
                );
                scene_evidence
                    .entry(scene_id.0.clone())
                    .or_insert_with(Vec::new)
                    .push(evidence);
            }
        }
        push_relation(
            &mut relations,
            format_compact!("edge:{family}:candidate_leak_trap"),
            &start_entity_id,
            &causal_id,
            "candidate_only_relation",
            InferenceAuthority::Candidate,
            Vec::new(),
        );

        let cached_queries = spotlight_types()
            .iter()
            .map(|node_type| {
                (
                    CompactString::new(*node_type),
                    cached_query(gold_case.family, node_type),
                )
            })
            .collect();
        cases.push(GoldDuelCase {
            dynamic_query: gold_case.title.clone(),
            cached_queries,
            start_node_ids: vec![start_entity_id.clone(), source_node_id],
            start_entity_id,
            scene_evidence,
            deterministic_report: analysis.report,
            gold: gold_case,
        });
    }

    let views = RevisionAnalysisViews::project(
        DUEL_GENERATION,
        Vec::new(),
        InferenceProjectionInput {
            accepted_nodes: nodes.into_values().collect(),
            relations,
            memberships,
        },
    )
    .map_err(|error| InferenceArtifactError::InvalidProjection(error.to_string()))?;
    let excluded_candidate_edges = views.inference_graph.receipt().excluded_candidate_edges;
    Ok(GoldDuelProjection {
        graph: views.inference_graph,
        cases,
        excluded_candidate_edges,
    })
}

pub fn evaluate_rankings(
    cases: &[GoldDuelCase],
    rankings: &BTreeMap<CompactString, Vec<CompactString>>,
) -> DuelArmMetrics {
    let mut hits = [0_usize; 3];
    let mut affected_total = 0;
    let mut first_broken_rank_sum = 0_usize;
    let mut first_broken_cases = 0_usize;
    let mut review_minutes_saved = 0_i64;
    let mut suspicious_hits = 0_usize;
    let mut suspicious_total = 0_usize;
    let mut overlap_sum_bp = 0_usize;

    for case in cases {
        let ranked = rankings
            .get(&case.gold.case_id.0)
            .map_or(&[][..], Vec::as_slice);
        let affected = case
            .gold
            .expected_impacts
            .iter()
            .map(|impact| impact.scene_id.0.as_str())
            .collect::<BTreeSet<_>>();
        let broken = case
            .gold
            .expected_impacts
            .iter()
            .filter(|impact| impact.classification == ImpactClassification::Broken)
            .map(|impact| impact.scene_id.0.as_str())
            .collect::<BTreeSet<_>>();
        let suspicious = case
            .gold
            .expected_impacts
            .iter()
            .filter(|impact| impact.classification == ImpactClassification::Suspicious)
            .map(|impact| impact.scene_id.0.as_str())
            .collect::<BTreeSet<_>>();
        affected_total += affected.len();
        suspicious_total += suspicious.len();
        for (metric, k) in [1_usize, 3, 5].into_iter().enumerate() {
            hits[metric] += ranked
                .iter()
                .take(k)
                .filter(|id| affected.contains(id.as_str()))
                .count();
        }
        if let Some(rank) = ranked
            .iter()
            .position(|id| broken.contains(id.as_str()))
            .map(|index| index + 1)
        {
            first_broken_rank_sum += rank;
            first_broken_cases += 1;
            let last_broken = ranked
                .iter()
                .rposition(|id| broken.contains(id.as_str()))
                .map_or(ranked.len(), |index| index + 1);
            review_minutes_saved += ranked.len().saturating_sub(last_broken) as i64 * 2;
        }
        suspicious_hits += ranked
            .iter()
            .take(5)
            .filter(|id| suspicious.contains(id.as_str()))
            .count();
        let deterministic = case
            .deterministic_report
            .authoritative_impacts
            .iter()
            .take(5)
            .map(|impact| impact.scene_id.0.as_str())
            .collect::<BTreeSet<_>>();
        let ranked_top = ranked
            .iter()
            .take(5)
            .map(CompactString::as_str)
            .collect::<BTreeSet<_>>();
        let union = deterministic.union(&ranked_top).count();
        overlap_sum_bp += ratio_bp(deterministic.intersection(&ranked_top).count(), union) as usize;
    }

    DuelArmMetrics {
        affected_scene_recall_at_1_bp: ratio_bp(hits[0], affected_total),
        affected_scene_recall_at_3_bp: ratio_bp(hits[1], affected_total),
        affected_scene_recall_at_5_bp: ratio_bp(hits[2], affected_total),
        mean_first_broken_rank_millis: first_broken_rank_sum
            .saturating_mul(1_000)
            .checked_div(first_broken_cases)
            .unwrap_or(0) as u32,
        review_minutes_saved_proxy_millis: review_minutes_saved * 1_000,
        suspicious_usefulness_proxy_bp: ratio_bp(suspicious_hits, suspicious_total),
        overlap_with_deterministic_at_5_bp: overlap_sum_bp.checked_div(cases.len()).unwrap_or(0)
            as u16,
    }
}

pub const fn spotlight_types() -> &'static [&'static str] {
    &[
        "scene",
        "event",
        "fact",
        "constraint",
        "state",
        "causal_claim",
        "repair_candidate",
    ]
}

struct SceneSeedContext<'a> {
    nodes: &'a mut BTreeMap<CompactString, InferenceNodeSeed>,
    relations: &'a mut Vec<InferenceEdgeSeed>,
    memberships: &'a mut Vec<InferenceEdgeSeed>,
    start_entity_id: &'a str,
    source_node_id: &'a str,
    family: &'a str,
}

fn add_scene(
    context: SceneSeedContext<'_>,
    scene_id: &str,
    rationale: &str,
    evidence: CompactString,
) {
    let scene_suffix = scene_id.strip_prefix("scene:").unwrap_or(scene_id);
    let proxy_id = format_compact!("entity:scene:{scene_suffix}");
    let document_id = format_compact!("document:{scene_suffix}");
    insert_node(context.nodes, scene_id, "scene", rationale);
    insert_node(context.nodes, &proxy_id, "entity", rationale);
    insert_node(context.nodes, &document_id, "document", rationale);
    let edge_suffix = stable_suffix(scene_id);
    push_relation(
        context.relations,
        format_compact!("edge:{}:scene:{edge_suffix}", context.family),
        context.start_entity_id,
        &proxy_id,
        format_compact!("revision affects scene: {rationale}"),
        InferenceAuthority::Asserted,
        vec![evidence.clone()],
    );
    push_relation(
        context.relations,
        format_compact!("edge:{}:typed_scene:{edge_suffix}", context.family),
        context.source_node_id,
        scene_id,
        "mutation_affects_scene",
        InferenceAuthority::Asserted,
        vec![evidence.clone()],
    );
    push_membership(
        context.memberships,
        format_compact!(
            "membership:{}:entity_document:{edge_suffix}",
            context.family
        ),
        &proxy_id,
        &document_id,
        "mentioned_in",
        evidence.clone(),
    );
    push_membership(
        context.memberships,
        format_compact!("membership:{}:document_scene:{edge_suffix}", context.family),
        &document_id,
        scene_id,
        "contains_scene",
        evidence,
    );
}

fn insert_node(
    nodes: &mut BTreeMap<CompactString, InferenceNodeSeed>,
    id: impl AsRef<str>,
    node_type: impl Into<CompactString>,
    text: impl Into<CompactString>,
) {
    let id = CompactString::new(id.as_ref());
    nodes
        .entry(id.clone())
        .or_insert_with(|| InferenceNodeSeed {
            node_id: id,
            node_type: node_type.into(),
            embedding_text: text.into(),
        });
}

fn push_relation(
    edges: &mut Vec<InferenceEdgeSeed>,
    edge_id: CompactString,
    source_id: impl AsRef<str>,
    target_id: impl AsRef<str>,
    relation_type: impl Into<CompactString>,
    authority: InferenceAuthority,
    evidence_ids: Vec<CompactString>,
) {
    edges.push(InferenceEdgeSeed {
        edge_id,
        source_id: CompactString::new(source_id.as_ref()),
        target_id: CompactString::new(target_id.as_ref()),
        relation_type: relation_type.into(),
        authority,
        evidence_ids,
        confidence_millis: 1_000,
    });
}

fn push_membership(
    edges: &mut Vec<InferenceEdgeSeed>,
    edge_id: CompactString,
    source_id: &str,
    target_id: &str,
    relation_type: &str,
    evidence: CompactString,
) {
    push_relation(
        edges,
        edge_id,
        source_id,
        target_id,
        relation_type,
        InferenceAuthority::Asserted,
        vec![evidence],
    );
}

fn find_projection_case<'a>(
    cases: &'a [GoldProjectionCase],
    gold: &RevisionImpactGoldCase,
) -> &'a GoldProjectionCase {
    cases
        .iter()
        .find(|case| case.case_id == gold.case_id.0)
        .expect("gold projection case")
}

fn mutation_node_id(mutation: &StoryMutation, family: &str) -> CompactString {
    match mutation {
        StoryMutation::RetractFact { fact_id }
        | StoryMutation::SupersedeFact { fact_id, .. }
        | StoryMutation::ShiftValidity { fact_id, .. } => fact_id.0.clone(),
        StoryMutation::ChangeState { .. } => format_compact!("state:mutation:{family}"),
    }
}

const fn mutation_node_type(mutation: &StoryMutation) -> &'static str {
    match mutation {
        StoryMutation::RetractFact { .. }
        | StoryMutation::SupersedeFact { .. }
        | StoryMutation::ShiftValidity { .. } => "fact",
        StoryMutation::ChangeState { .. } => "state",
    }
}

fn mutation_embedding_text(gold: &RevisionImpactGoldCase) -> CompactString {
    format_compact!("{:?}: {}", gold.mutation, gold.title)
}

fn stable_suffix(id: &str) -> String {
    id.chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character
            } else {
                '_'
            }
        })
        .collect()
}

pub const fn family_key(family: GoldMutationFamily) -> &'static str {
    match family {
        GoldMutationFamily::DelayedReveal => "delayed_reveal",
        GoldMutationFamily::EarlierDeath => "earlier_death",
        GoldMutationFamily::ChangedWitness => "changed_witness",
        GoldMutationFamily::ChangedPowerLimitation => "changed_power_limitation",
        GoldMutationFamily::ChangedTravelDuration => "changed_travel_duration",
        GoldMutationFamily::RemovedRelationship => "removed_relationship",
        GoldMutationFamily::ChangedPossession => "changed_possession",
    }
}

fn cached_query(family: GoldMutationFamily, node_type: &str) -> CompactString {
    format_compact!(
        "Rank {node_type} nodes affected by a {} revision mutation.",
        family_key(family)
    )
}

fn ratio_bp(numerator: usize, denominator: usize) -> u16 {
    numerator
        .saturating_mul(10_000)
        .checked_div(denominator)
        .unwrap_or(0)
        .min(10_000) as u16
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn union_projection_covers_every_spotlight_type_and_rejects_candidates() {
        let duel = build_gold_duel_projection().unwrap();
        let types = duel.graph.node_types().iter().map(CompactString::as_str);
        let actual = types.collect::<BTreeSet<_>>();
        for expected in spotlight_types() {
            assert!(actual.contains(expected));
        }
        assert_eq!(duel.cases.len(), 7);
        assert_eq!(duel.excluded_candidate_edges, 7);
        assert_eq!(
            duel.graph.receipt().admitted_relations + duel.graph.receipt().admitted_memberships,
            duel.graph.edge_metadata().len()
        );
    }

    #[test]
    fn deterministic_order_has_perfect_gold_recall() {
        let duel = build_gold_duel_projection().unwrap();
        let rankings = duel
            .cases
            .iter()
            .map(|case| {
                (
                    case.gold.case_id.0.clone(),
                    case.deterministic_report
                        .authoritative_impacts
                        .iter()
                        .map(|impact| impact.scene_id.0.clone())
                        .collect(),
                )
            })
            .collect();
        let metrics = evaluate_rankings(&duel.cases, &rankings);
        assert_eq!(metrics.affected_scene_recall_at_5_bp, 10_000);
        assert_eq!(metrics.mean_first_broken_rank_millis, 1_000);
    }
}
