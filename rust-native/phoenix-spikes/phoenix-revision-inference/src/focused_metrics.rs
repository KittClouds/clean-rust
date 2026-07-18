use std::collections::{BTreeMap, BTreeSet};

use compact_str::CompactString;
use serde::{Deserialize, Serialize};

use crate::GoldDuelCase;

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceDiscoveryMetrics {
    pub evidence_recall_at_1_bp: u16,
    pub evidence_recall_at_3_bp: u16,
    pub evidence_recall_at_5_bp: u16,
    pub mean_first_evidence_rank_millis: u32,
    pub mean_reciprocal_rank_bp: u16,
    pub source_prefetch_precision_at_5_bp: u16,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RepairRankingMetrics {
    pub any_reasonable_repair_at_1_bp: u16,
    pub any_reasonable_repair_at_3_bp: u16,
    pub reasonable_repair_id_recall_at_3_bp: u16,
    pub mean_reciprocal_rank_bp: u16,
    pub cross_case_contamination_at_3_bp: u16,
    pub preferred_repair_metric_available: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FocusedModelQualityReceipt {
    pub provisional_pending_author_review: bool,
    pub gfm_dynamic_evidence: EvidenceDiscoveryMetrics,
    pub gfm_cached_evidence: EvidenceDiscoveryMetrics,
    pub reasoner_dynamic_evidence: EvidenceDiscoveryMetrics,
    pub reasoner_cached_evidence: EvidenceDiscoveryMetrics,
    pub reasoner_dynamic_repairs: RepairRankingMetrics,
    pub reasoner_cached_repairs: RepairRankingMetrics,
}

pub fn evaluate_evidence_discovery(
    cases: &[GoldDuelCase],
    rankings: &BTreeMap<CompactString, Vec<CompactString>>,
) -> EvidenceDiscoveryMetrics {
    let mut recall_hits = [0_usize; 3];
    let mut expected_total = 0_usize;
    let mut first_rank_sum = 0_usize;
    let mut reciprocal_rank_sum = 0_usize;
    let mut cases_with_hit = 0_usize;
    let mut prefetch_hits = 0_usize;
    let mut prefetch_total = 0_usize;

    for case in cases {
        let ranked = rankings
            .get(&case.gold.case_id.0)
            .map_or(&[][..], Vec::as_slice);
        let expected = expected_evidence(case);
        expected_total += expected.len();
        for (metric, k) in [1_usize, 3, 5].into_iter().enumerate() {
            let discovered = discovered_evidence(case, ranked.iter().take(k), &expected);
            recall_hits[metric] += discovered.len();
        }
        let first_rank = ranked.iter().position(|scene_id| {
            case.scene_evidence
                .get(scene_id)
                .is_some_and(|ids| ids.iter().any(|id| expected.contains(id)))
        });
        if let Some(rank) = first_rank.map(|rank| rank + 1) {
            first_rank_sum += rank;
            reciprocal_rank_sum += 10_000 / rank;
            cases_with_hit += 1;
        }
        for scene_id in ranked.iter().take(5) {
            prefetch_total += 1;
            if case
                .scene_evidence
                .get(scene_id)
                .is_some_and(|ids| ids.iter().any(|id| expected.contains(id)))
            {
                prefetch_hits += 1;
            }
        }
    }
    EvidenceDiscoveryMetrics {
        evidence_recall_at_1_bp: ratio_bp(recall_hits[0], expected_total),
        evidence_recall_at_3_bp: ratio_bp(recall_hits[1], expected_total),
        evidence_recall_at_5_bp: ratio_bp(recall_hits[2], expected_total),
        mean_first_evidence_rank_millis: first_rank_sum
            .saturating_mul(1_000)
            .checked_div(cases_with_hit)
            .unwrap_or(0) as u32,
        mean_reciprocal_rank_bp: reciprocal_rank_sum.checked_div(cases.len()).unwrap_or(0) as u16,
        source_prefetch_precision_at_5_bp: ratio_bp(prefetch_hits, prefetch_total),
    }
}

pub fn evaluate_repair_ranking(
    cases: &[GoldDuelCase],
    rankings: &BTreeMap<CompactString, Vec<CompactString>>,
) -> RepairRankingMetrics {
    let mut any_at_1 = 0_usize;
    let mut any_at_3 = 0_usize;
    let mut recalled_ids = 0_usize;
    let mut expected_ids = 0_usize;
    let mut reciprocal_rank_sum = 0_usize;
    let mut contamination = 0_usize;
    let mut inspected = 0_usize;

    for case in cases {
        let ranked = rankings
            .get(&case.gold.case_id.0)
            .map_or(&[][..], Vec::as_slice);
        let expected = case
            .gold
            .reasonable_repairs
            .iter()
            .map(|repair| repair.repair_id.0.as_str())
            .collect::<BTreeSet<_>>();
        expected_ids += expected.len();
        any_at_1 += usize::from(
            ranked
                .first()
                .is_some_and(|id| expected.contains(id.as_str())),
        );
        let top_3 = ranked.iter().take(3).collect::<Vec<_>>();
        any_at_3 += usize::from(top_3.iter().any(|id| expected.contains(id.as_str())));
        recalled_ids += top_3
            .iter()
            .filter(|id| expected.contains(id.as_str()))
            .count();
        inspected += top_3.len();
        contamination += top_3
            .iter()
            .filter(|id| !expected.contains(id.as_str()))
            .count();
        if let Some(rank) = ranked
            .iter()
            .position(|id| expected.contains(id.as_str()))
            .map(|rank| rank + 1)
        {
            reciprocal_rank_sum += 10_000 / rank;
        }
    }
    RepairRankingMetrics {
        any_reasonable_repair_at_1_bp: ratio_bp(any_at_1, cases.len()),
        any_reasonable_repair_at_3_bp: ratio_bp(any_at_3, cases.len()),
        reasonable_repair_id_recall_at_3_bp: ratio_bp(recalled_ids, expected_ids),
        mean_reciprocal_rank_bp: reciprocal_rank_sum.checked_div(cases.len()).unwrap_or(0) as u16,
        cross_case_contamination_at_3_bp: ratio_bp(contamination, inspected),
        preferred_repair_metric_available: false,
    }
}

fn expected_evidence(case: &GoldDuelCase) -> BTreeSet<CompactString> {
    case.gold
        .expected_impacts
        .iter()
        .flat_map(|impact| {
            case.scene_evidence
                .get(&impact.scene_id.0)
                .into_iter()
                .flatten()
                .filter(|id| id.contains(":impact:"))
                .cloned()
        })
        .collect()
}

fn discovered_evidence<'a>(
    case: &GoldDuelCase,
    ranked: impl Iterator<Item = &'a CompactString>,
    expected: &BTreeSet<CompactString>,
) -> BTreeSet<CompactString> {
    ranked
        .flat_map(|scene_id| case.scene_evidence.get(scene_id).into_iter().flatten())
        .filter(|id| expected.contains(*id))
        .cloned()
        .collect()
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
    use crate::build_gold_duel_projection;

    #[test]
    fn exact_gold_order_yields_perfect_evidence_discovery() {
        let duel = build_gold_duel_projection().unwrap();
        let rankings = duel
            .cases
            .iter()
            .map(|case| {
                (
                    case.gold.case_id.0.clone(),
                    case.gold
                        .expected_impacts
                        .iter()
                        .map(|impact| impact.scene_id.0.clone())
                        .collect(),
                )
            })
            .collect();
        let metrics = evaluate_evidence_discovery(&duel.cases, &rankings);
        assert_eq!(metrics.evidence_recall_at_5_bp, 10_000);
        assert_eq!(metrics.mean_first_evidence_rank_millis, 1_000);
    }

    #[test]
    fn exact_repair_order_has_no_cross_case_contamination() {
        let duel = build_gold_duel_projection().unwrap();
        let rankings = duel
            .cases
            .iter()
            .map(|case| {
                (
                    case.gold.case_id.0.clone(),
                    case.gold
                        .reasonable_repairs
                        .iter()
                        .map(|repair| repair.repair_id.0.clone())
                        .collect(),
                )
            })
            .collect();
        let metrics = evaluate_repair_ranking(&duel.cases, &rankings);
        assert_eq!(metrics.any_reasonable_repair_at_1_bp, 10_000);
        assert_eq!(metrics.reasonable_repair_id_recall_at_3_bp, 10_000);
        assert_eq!(metrics.cross_case_contamination_at_3_bp, 0);
        assert!(!metrics.preferred_repair_metric_available);
    }
}
