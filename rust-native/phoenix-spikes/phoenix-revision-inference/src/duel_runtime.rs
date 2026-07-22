use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use compact_str::{CompactString, ToCompactString};
use phoenix_revision_impact::{
    ExperimentalModelOverlayPermit, ModelOverlayKind, ModelQueryMode, ModelRankedNode,
    ModelRelevanceOverlay, attach_model_overlays,
};
use serde::{Deserialize, Serialize};

use crate::{
    DuelArmMetrics, FocusedModelQualityReceipt, GfmAssets, GfmBundle, GoldDuelProjection,
    InferencePerformanceReceipt, ReasonerAssets, ReasonerQueryEmbedding, Result,
    evaluate_evidence_discovery, evaluate_rankings, evaluate_repair_ranking, family_key,
    prepare_reasoner_query_embedding, run_gfm_complete, run_reasoner_complete,
    run_reasoner_precomputed, spotlight_types,
};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DuelArmReceipt {
    pub arm: CompactString,
    pub metrics: DuelArmMetrics,
    pub full_latency_micros: u64,
    pub peak_resident_bytes: u64,
    pub output_stable: bool,
    pub deterministic_traversal_unpruned: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QueryQualityReceipt {
    pub gfm_dynamic: DuelArmMetrics,
    pub gfm_cached: DuelArmMetrics,
    pub reasoner_dynamic: DuelArmMetrics,
    pub reasoner_cached: DuelArmMetrics,
    pub dynamic_repair_top_1_bp: u16,
    pub dynamic_repair_top_3_bp: u16,
    pub cached_repair_top_1_bp: u16,
    pub cached_repair_top_3_bp: u16,
    pub cached_query_precompute_micros: u64,
    pub cached_query_precompute_peak_resident_bytes: u64,
    pub cached_query_interactive_micros: u64,
    pub cached_query_interactive_peak_resident_bytes: u64,
    pub cached_query_encoder_misses: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DuelCaseReceipt {
    pub case_id: CompactString,
    pub authoritative_report: phoenix_revision_impact::RevisionImpactReport,
    pub gfm_scene_order: Vec<CompactString>,
    pub reasoner_scene_order: Vec<CompactString>,
    pub committee_scene_order: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ModelDuelExecution {
    pub arms: Vec<DuelArmReceipt>,
    pub query_quality: QueryQualityReceipt,
    pub focused_quality: FocusedModelQualityReceipt,
    pub cases: Vec<DuelCaseReceipt>,
    pub technical_integration_candidate: bool,
}

pub fn execute_model_duel(
    duel: &mut GoldDuelProjection,
    gfm_root: &Path,
    reasoner_root: &Path,
    gfm_assets: &GfmAssets,
    reasoner_assets: &ReasonerAssets,
    detector_latency_micros: u64,
    detector_peak_resident_bytes: u64,
) -> Result<ModelDuelExecution> {
    let gfm_bundle = GfmBundle::open(gfm_root)?;
    let scene_count = duel
        .graph
        .nodes()
        .iter()
        .filter(|node| duel.graph.node_types()[node.node_type_id as usize] == "scene")
        .count();
    let entity_count = gfm_bundle.manifest.node_ids.len();
    let repair_count = duel.cases.len() * 2;
    let mut precomputed = BTreeMap::<String, ReasonerQueryEmbedding>::new();
    let mut precompute_micros = 0_u64;
    let mut precompute_peak = 0_u64;
    for case in &duel.cases {
        for &node_type in spotlight_types() {
            let key = cached_query_key(case.gold.family, node_type);
            let query = prepare_reasoner_query_embedding(
                reasoner_assets,
                case.cached_queries[node_type].as_str(),
            )?;
            precompute_micros += query.prepare_micros;
            precompute_peak = precompute_peak.max(query.peak_resident_bytes);
            precomputed.insert(key, query);
        }
    }
    let mut detector = BTreeMap::new();
    let mut gfm_dynamic = BTreeMap::new();
    let mut gfm_cached = BTreeMap::new();
    let mut reasoner_dynamic = BTreeMap::new();
    let mut reasoner_cached = BTreeMap::new();
    let mut committee = BTreeMap::new();
    let mut dynamic_repairs = BTreeMap::new();
    let mut cached_repairs = BTreeMap::new();
    let mut cases = Vec::with_capacity(duel.cases.len());
    let mut gfm_latency = 0_u64;
    let mut reasoner_latency = 0_u64;
    let mut gfm_peak = 0_u64;
    let mut reasoner_peak = 0_u64;
    let mut cached_interactive_micros = 0_u64;
    let mut cached_interactive_peak = 0_u64;
    let mut cached_encoder_misses = 0_u64;
    let mut gfm_stable = true;
    let mut reasoner_stable = true;

    for case in &mut duel.cases {
        let case_id = case.gold.case_id.0.clone();
        let deterministic_order = case
            .deterministic_report
            .authoritative_impacts
            .iter()
            .map(|impact| impact.scene_id.0.clone())
            .collect::<Vec<_>>();
        detector.insert(case_id.clone(), deterministic_order);

        let gfm_starts = [case.start_entity_id.as_str()];
        let gfm_first = run_gfm_complete(
            gfm_root,
            gfm_assets,
            case.dynamic_query.as_str(),
            &gfm_starts,
            entity_count,
        )?;
        let gfm_repeat = run_gfm_complete(
            gfm_root,
            gfm_assets,
            case.dynamic_query.as_str(),
            &gfm_starts,
            entity_count,
        )?;
        let cached_scene_query = case.cached_queries["scene"].as_str();
        let gfm_cached_output = run_gfm_complete(
            gfm_root,
            gfm_assets,
            cached_scene_query,
            &gfm_starts,
            entity_count,
        )?;
        gfm_latency += gfm_first.receipt.complete_inference_micros;
        gfm_peak = gfm_peak.max(gfm_first.receipt.peak_resident_bytes);
        let gfm_scene = gfm_scene_order(&gfm_first);
        let gfm_repeat_scene = gfm_scene_order(&gfm_repeat);
        gfm_stable &= gfm_scene == gfm_repeat_scene;
        gfm_dynamic.insert(case_id.clone(), gfm_scene.clone());
        gfm_cached.insert(case_id.clone(), gfm_scene_order(&gfm_cached_output));

        let reasoner_starts = case
            .start_node_ids
            .iter()
            .map(CompactString::as_str)
            .collect::<Vec<_>>();
        let reasoner_first = run_reasoner_complete(
            reasoner_root,
            reasoner_assets,
            case.dynamic_query.as_str(),
            &reasoner_starts,
            "scene",
            scene_count,
        )?;
        let reasoner_repeat = run_reasoner_complete(
            reasoner_root,
            reasoner_assets,
            case.dynamic_query.as_str(),
            &reasoner_starts,
            "scene",
            scene_count,
        )?;
        let reasoner_scene = ranking_ids(&reasoner_first);
        reasoner_stable &= reasoner_scene == ranking_ids(&reasoner_repeat);
        reasoner_latency += reasoner_first.receipt.complete_inference_micros;
        reasoner_peak = reasoner_peak.max(reasoner_first.receipt.peak_resident_bytes);
        reasoner_dynamic.insert(case_id.clone(), reasoner_scene.clone());

        let dynamic_repair = run_reasoner_complete(
            reasoner_root,
            reasoner_assets,
            case.dynamic_query.as_str(),
            &reasoner_starts,
            "repair_candidate",
            repair_count,
        )?;
        dynamic_repairs.insert(case_id.clone(), ranking_ids(&dynamic_repair));

        let mut overlays = vec![
            gfm_entity_overlay(case, &gfm_bundle, &gfm_first),
            gfm_scene_overlay(case, &gfm_bundle, &gfm_first),
            reasoner_overlay(case, &reasoner_first, "scene", ModelQueryMode::Dynamic),
            reasoner_overlay(
                case,
                &dynamic_repair,
                "repair_candidate",
                ModelQueryMode::Dynamic,
            ),
        ];
        for &node_type in spotlight_types() {
            let cached_query = &precomputed[&cached_query_key(case.gold.family, node_type)];
            let output = run_reasoner_precomputed(
                reasoner_root,
                reasoner_assets,
                cached_query,
                &reasoner_starts,
                node_type,
                duel.graph.nodes().len(),
            )?;
            cached_interactive_micros += output.receipt.complete_inference_micros;
            cached_interactive_peak =
                cached_interactive_peak.max(output.receipt.peak_resident_bytes);
            cached_encoder_misses += output.receipt.cache.encoder_cache_misses;
            if node_type == "scene" {
                reasoner_cached.insert(case_id.clone(), ranking_ids(&output));
            } else if node_type == "repair_candidate" {
                cached_repairs.insert(case_id.clone(), ranking_ids(&output));
            }
            overlays.push(reasoner_overlay(
                case,
                &output,
                node_type,
                ModelQueryMode::Cached,
            ));
        }
        attach_model_overlays(
            &mut case.deterministic_report,
            overlays,
            ExperimentalModelOverlayPermit::for_isolated_harness(),
        )
        .map_err(|error| crate::InferenceArtifactError::InvalidArtifact(error.to_string()))?;

        let committee_scene = fuse_rankings(&gfm_scene, &reasoner_scene);
        committee.insert(case_id.clone(), committee_scene.clone());
        cases.push(DuelCaseReceipt {
            case_id,
            authoritative_report: case.deterministic_report.clone(),
            gfm_scene_order: gfm_scene,
            reasoner_scene_order: reasoner_scene,
            committee_scene_order: committee_scene,
        });
    }

    let detector_gfm = reorder_authoritative(&detector, &gfm_dynamic);
    let detector_committee = reorder_authoritative(&detector, &committee);
    let detector_metrics = evaluate_rankings(&duel.cases, &detector);
    let gfm_metrics = evaluate_rankings(&duel.cases, &gfm_dynamic);
    let reasoner_metrics = evaluate_rankings(&duel.cases, &reasoner_dynamic);
    let detector_gfm_metrics = evaluate_rankings(&duel.cases, &detector_gfm);
    let detector_committee_metrics = evaluate_rankings(&duel.cases, &detector_committee);
    let unpruned_gfm = same_members(&detector, &detector_gfm);
    let unpruned_committee = same_members(&detector, &detector_committee);
    let technical_integration_candidate = detector_gfm_metrics.suspicious_usefulness_proxy_bp
        > detector_metrics.suspicious_usefulness_proxy_bp
        || detector_committee_metrics.suspicious_usefulness_proxy_bp
            > detector_metrics.suspicious_usefulness_proxy_bp;
    let arms = vec![
        arm(
            "deterministic_detector",
            detector_metrics,
            detector_latency_micros,
            detector_peak_resident_bytes,
            true,
            true,
        ),
        arm(
            "gfm_rag_8m",
            gfm_metrics,
            gfm_latency,
            gfm_peak,
            gfm_stable,
            true,
        ),
        arm(
            "g_reasoner_34m",
            reasoner_metrics,
            reasoner_latency,
            reasoner_peak,
            reasoner_stable,
            true,
        ),
        arm(
            "deterministic_plus_8m",
            detector_gfm_metrics,
            detector_latency_micros + gfm_latency,
            detector_peak_resident_bytes.max(gfm_peak),
            gfm_stable,
            unpruned_gfm,
        ),
        arm(
            "deterministic_plus_8m_to_34m_committee",
            detector_committee_metrics,
            detector_latency_micros + gfm_latency + reasoner_latency,
            detector_peak_resident_bytes
                .max(gfm_peak)
                .max(reasoner_peak),
            gfm_stable && reasoner_stable,
            unpruned_committee,
        ),
    ];
    Ok(ModelDuelExecution {
        query_quality: QueryQualityReceipt {
            gfm_dynamic: evaluate_rankings(&duel.cases, &gfm_dynamic),
            gfm_cached: evaluate_rankings(&duel.cases, &gfm_cached),
            reasoner_dynamic: evaluate_rankings(&duel.cases, &reasoner_dynamic),
            reasoner_cached: evaluate_rankings(&duel.cases, &reasoner_cached),
            dynamic_repair_top_1_bp: repair_hit_bp(&duel.cases, &dynamic_repairs, 1),
            dynamic_repair_top_3_bp: repair_hit_bp(&duel.cases, &dynamic_repairs, 3),
            cached_repair_top_1_bp: repair_hit_bp(&duel.cases, &cached_repairs, 1),
            cached_repair_top_3_bp: repair_hit_bp(&duel.cases, &cached_repairs, 3),
            cached_query_precompute_micros: precompute_micros,
            cached_query_precompute_peak_resident_bytes: precompute_peak,
            cached_query_interactive_micros: cached_interactive_micros,
            cached_query_interactive_peak_resident_bytes: cached_interactive_peak,
            cached_query_encoder_misses: cached_encoder_misses,
        },
        focused_quality: FocusedModelQualityReceipt {
            provisional_pending_author_review: duel
                .cases
                .iter()
                .any(|case| !case.gold.is_author_reviewed()),
            gfm_dynamic_evidence: evaluate_evidence_discovery(&duel.cases, &gfm_dynamic),
            gfm_cached_evidence: evaluate_evidence_discovery(&duel.cases, &gfm_cached),
            reasoner_dynamic_evidence: evaluate_evidence_discovery(&duel.cases, &reasoner_dynamic),
            reasoner_cached_evidence: evaluate_evidence_discovery(&duel.cases, &reasoner_cached),
            reasoner_dynamic_repairs: evaluate_repair_ranking(&duel.cases, &dynamic_repairs),
            reasoner_cached_repairs: evaluate_repair_ranking(&duel.cases, &cached_repairs),
        },
        arms,
        cases,
        technical_integration_candidate,
    })
}

fn cached_query_key(family: phoenix_types::GoldMutationFamily, node_type: &str) -> String {
    format!("{}×{node_type}", family_key(family))
}

fn arm(
    name: &str,
    metrics: DuelArmMetrics,
    full_latency_micros: u64,
    peak_resident_bytes: u64,
    output_stable: bool,
    deterministic_traversal_unpruned: bool,
) -> DuelArmReceipt {
    DuelArmReceipt {
        arm: name.into(),
        metrics,
        full_latency_micros,
        peak_resident_bytes,
        output_stable,
        deterministic_traversal_unpruned,
    }
}

fn gfm_scene_order(output: &crate::GfmInferenceOutput) -> Vec<CompactString> {
    output
        .ordered_document_ids
        .iter()
        .map(|id| {
            id.strip_prefix("document:").map_or_else(
                || id.to_compact_string(),
                |suffix| format!("scene:{suffix}").into(),
            )
        })
        .collect()
}

fn ranking_ids(output: &crate::ReasonerInferenceOutput) -> Vec<CompactString> {
    output
        .ranking
        .ranked_nodes
        .iter()
        .map(|node| node.stable_id.to_compact_string())
        .collect()
}

fn fuse_rankings(left: &[CompactString], right: &[CompactString]) -> Vec<CompactString> {
    let mut scores = BTreeMap::<CompactString, f64>::new();
    for (index, id) in left.iter().enumerate() {
        *scores.entry(id.clone()).or_default() += 1.0 / (index + 1) as f64;
    }
    for (index, id) in right.iter().enumerate() {
        *scores.entry(id.clone()).or_default() += 1.0 / (index + 1) as f64;
    }
    let mut ranked = scores.into_iter().collect::<Vec<_>>();
    ranked.sort_by(|left, right| {
        right
            .1
            .total_cmp(&left.1)
            .then_with(|| left.0.cmp(&right.0))
    });
    ranked.into_iter().map(|(id, _)| id).collect()
}

fn reorder_authoritative(
    authoritative: &BTreeMap<CompactString, Vec<CompactString>>,
    relevance: &BTreeMap<CompactString, Vec<CompactString>>,
) -> BTreeMap<CompactString, Vec<CompactString>> {
    authoritative
        .iter()
        .map(|(case_id, scenes)| {
            let ranks = relevance
                .get(case_id)
                .into_iter()
                .flatten()
                .enumerate()
                .map(|(rank, id)| (id.as_str(), rank))
                .collect::<BTreeMap<_, _>>();
            let mut ordered = scenes.clone();
            ordered.sort_by_key(|id| ranks.get(id.as_str()).copied().unwrap_or(usize::MAX));
            (case_id.clone(), ordered)
        })
        .collect()
}

fn same_members(
    left: &BTreeMap<CompactString, Vec<CompactString>>,
    right: &BTreeMap<CompactString, Vec<CompactString>>,
) -> bool {
    left.iter().all(|(case_id, values)| {
        let left = values.iter().collect::<BTreeSet<_>>();
        let right = right
            .get(case_id)
            .into_iter()
            .flatten()
            .collect::<BTreeSet<_>>();
        left == right
    })
}

fn repair_hit_bp(
    cases: &[crate::GoldDuelCase],
    rankings: &BTreeMap<CompactString, Vec<CompactString>>,
    k: usize,
) -> u16 {
    let hits = cases
        .iter()
        .filter(|case| {
            let expected = case
                .gold
                .reasonable_repairs
                .iter()
                .map(|repair| repair.repair_id.0.as_str())
                .collect::<BTreeSet<_>>();
            rankings
                .get(&case.gold.case_id.0)
                .into_iter()
                .flatten()
                .take(k)
                .any(|id| expected.contains(id.as_str()))
        })
        .count();
    (hits * 10_000 / cases.len().max(1)) as u16
}

fn gfm_entity_overlay(
    case: &crate::GoldDuelCase,
    bundle: &GfmBundle,
    output: &crate::GfmInferenceOutput,
) -> ModelRelevanceOverlay {
    let scores = output
        .top_entity_ids
        .iter()
        .map(|id| {
            bundle
                .manifest
                .node_ids
                .iter()
                .position(|candidate| candidate == id)
                .map_or(0.0, |index| output.logits[index])
        })
        .collect::<Vec<_>>();
    overlay(
        case,
        OverlaySpec {
            model_id: "gfm-rag-8m",
            kind: ModelOverlayKind::Retrieval,
            query_mode: ModelQueryMode::Dynamic,
            node_type: "entity",
        },
        output.top_entity_ids.iter().map(String::as_str),
        &scores,
        &output.receipt,
    )
}

fn gfm_scene_overlay(
    case: &crate::GoldDuelCase,
    bundle: &GfmBundle,
    output: &crate::GfmInferenceOutput,
) -> ModelRelevanceOverlay {
    let ids = gfm_scene_order(output);
    let scores = output
        .ranked_documents
        .order
        .iter()
        .map(|index| output.ranked_documents.scores[*index])
        .collect::<Vec<_>>();
    debug_assert_eq!(bundle.manifest.document_ids.len(), ids.len());
    overlay(
        case,
        OverlaySpec {
            model_id: "gfm-rag-8m",
            kind: ModelOverlayKind::Retrieval,
            query_mode: ModelQueryMode::Dynamic,
            node_type: "scene",
        },
        ids.iter().map(CompactString::as_str),
        &scores,
        &output.receipt,
    )
}

fn reasoner_overlay(
    case: &crate::GoldDuelCase,
    output: &crate::ReasonerInferenceOutput,
    node_type: &str,
    query_mode: ModelQueryMode,
) -> ModelRelevanceOverlay {
    let scores = output
        .ranking
        .ranked_nodes
        .iter()
        .map(|node| node.logit)
        .collect::<Vec<_>>();
    overlay(
        case,
        OverlaySpec {
            model_id: "g-reasoner-34m",
            kind: ModelOverlayKind::GraphSpotlight,
            query_mode,
            node_type,
        },
        output
            .ranking
            .ranked_nodes
            .iter()
            .map(|node| node.stable_id.as_str()),
        &scores,
        &output.receipt,
    )
}

struct OverlaySpec<'a> {
    model_id: &'a str,
    kind: ModelOverlayKind,
    query_mode: ModelQueryMode,
    node_type: &'a str,
}

fn overlay<'a>(
    case: &crate::GoldDuelCase,
    spec: OverlaySpec<'_>,
    ids: impl Iterator<Item = &'a str>,
    scores: &[f32],
    performance: &InferencePerformanceReceipt,
) -> ModelRelevanceOverlay {
    let score_millis = relative_scores(scores);
    let ranked_nodes = ids
        .zip(scores.iter().copied())
        .enumerate()
        .map(|(index, (id, raw_score))| ModelRankedNode {
            node_id: id.into(),
            node_type: spec.node_type.into(),
            rank: index as u32 + 1,
            raw_score,
            score_millis: score_millis[index],
            evidence_targets: case.scene_evidence.get(id).cloned().unwrap_or_default(),
        })
        .collect();
    ModelRelevanceOverlay {
        model_id: spec.model_id.into(),
        generation: case.deterministic_report.deterministic_receipt.generation,
        kind: spec.kind,
        query_mode: spec.query_mode,
        start_node_ids: case.start_node_ids.clone(),
        target_node_type: Some(spec.node_type.into()),
        ranked_nodes,
        full_latency_micros: performance.complete_inference_micros,
        peak_resident_bytes: performance.peak_resident_bytes,
        presentation_only: true,
    }
}

fn relative_scores(scores: &[f32]) -> Vec<u16> {
    if scores.is_empty() {
        return Vec::new();
    }
    let minimum = scores.iter().copied().fold(f32::INFINITY, f32::min);
    let maximum = scores.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let span = maximum - minimum;
    scores
        .iter()
        .map(|score| {
            if span <= f32::EPSILON {
                1_000
            } else {
                (((score - minimum) / span) * 1_000.0).round() as u16
            }
        })
        .collect()
}
