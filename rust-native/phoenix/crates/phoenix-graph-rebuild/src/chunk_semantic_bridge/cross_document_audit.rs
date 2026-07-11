use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};

use super::selection::{
    CROSS_DOCUMENT_EPISODE_PAIR_QUOTA, CROSS_DOCUMENT_FREQUENCY_FLOOR_PAIR_QUOTA,
    CROSS_DOCUMENT_PAIR_QUOTA, CROSS_DOCUMENT_TYPE_PAIR_QUOTA,
    CROSS_DOCUMENT_WEAK_SUPPORT_PAIR_QUOTA, CROSS_DOCUMENT_ZERO_ENTITY_PAIR_QUOTA,
};
use super::*;

const AUDIT_ROW_LIMIT: usize = 24;
const WEAKEST_ROW_LIMIT: usize = 8;

pub(super) fn build_cross_document_certificate(
    input: ChunkSemanticBridgeEngineInput<'_>,
    generated: &[ChunkSemanticBridgeCandidate],
    selected: &[ChunkSemanticBridgeCandidate],
) -> CrossDocumentBridgeRunCertificate {
    let chunk_by_id = input
        .chunks
        .iter()
        .map(|chunk| (chunk.id, chunk))
        .collect::<HashMap<_, _>>();
    let selected_ids = selected
        .iter()
        .map(|row| row.id.as_str())
        .collect::<HashSet<_>>();
    let cross_generated = generated
        .iter()
        .filter(|row| is_cross_document(row))
        .collect::<Vec<_>>();
    let cross_selected = selected
        .iter()
        .filter(|row| is_cross_document(row))
        .collect::<Vec<_>>();
    let selected_counts = SelectedCounts::new(&cross_selected);
    let eligible_candidates = cross_generated
        .iter()
        .filter(|row| bridge_quality_gate_decision(row) == BridgeQualityGateDecision::Accept)
        .count();

    let mut rejected = cross_generated
        .iter()
        .filter(|row| !selected_ids.contains(row.id.as_str()))
        .map(|row| {
            let reason = rejection_reason(row, &selected_counts, selected.len());
            (row, reason)
        })
        .collect::<Vec<_>>();
    rejected.sort_by(|(left, left_reason), (right, right_reason)| {
        left_reason
            .cmp(right_reason)
            .then_with(|| right.confidence.total_cmp(&left.confidence))
            .then_with(|| left.id.cmp(&right.id))
    });

    let mut rejection_counts = HashMap::<CompactString, usize>::new();
    for (_, reason) in &rejected {
        *rejection_counts.entry(reason.clone()).or_default() += 1;
    }
    let mut rejection_counts = rejection_counts
        .into_iter()
        .map(|(reason, count)| CrossDocumentBridgeRejectionCount { reason, count })
        .collect::<Vec<_>>();
    rejection_counts.sort_by(|left, right| left.reason.cmp(&right.reason));

    let mut weakest = cross_selected.clone();
    weakest.sort_by(|left, right| {
        left.confidence
            .total_cmp(&right.confidence)
            .then_with(|| left.id.cmp(&right.id))
    });

    let no_topology_writes = generated.iter().all(|row| {
        row.status == ChunkSemanticBridgeStatus::Candidate
            && row.commit_policy == ChunkSemanticBridgeCommitPolicy::NoTopologyCommit
            && row
                .rationale
                .iter()
                .any(|receipt| receipt == CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT)
    });

    CrossDocumentBridgeRunCertificate {
        schema_version: CROSS_DOCUMENT_BRIDGE_CERTIFICATE_SCHEMA_VERSION.into(),
        source_document_ids: document_ids(input.chunks),
        generated_candidates: cross_generated.len(),
        eligible_candidates,
        selected_candidates: cross_selected.len(),
        rejected_candidates: rejected.len(),
        pair_coverage: pair_coverage(&cross_generated, &cross_selected),
        rejection_counts,
        selected_rows: cross_selected
            .iter()
            .map(|row| audit_row(row, None, &chunk_by_id))
            .collect(),
        rejected_rows: rejected
            .iter()
            .take(AUDIT_ROW_LIMIT)
            .map(|(row, reason)| audit_row(row, Some(reason.clone()), &chunk_by_id))
            .collect(),
        weakest_rows: weakest
            .iter()
            .take(WEAKEST_ROW_LIMIT)
            .map(|row| audit_row(row, None, &chunk_by_id))
            .collect(),
        no_topology_writes,
        invariant_receipts: vec![
            "cross_document_pair_coverage:measured".into(),
            "cross_document_rejections:accounted".into(),
            "cross_document_excerpts:source_derived".into(),
            CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT.into(),
        ],
    }
}

struct SelectedCounts {
    pair: HashMap<CompactString, usize>,
    pair_type: HashMap<CompactString, usize>,
    episode_pair: HashMap<CompactString, usize>,
    zero_by_pair: HashMap<CompactString, usize>,
    frequency_by_pair: HashMap<CompactString, usize>,
}

impl SelectedCounts {
    fn new(rows: &[&ChunkSemanticBridgeCandidate]) -> Self {
        let mut counts = Self {
            pair: HashMap::new(),
            pair_type: HashMap::new(),
            episode_pair: HashMap::new(),
            zero_by_pair: HashMap::new(),
            frequency_by_pair: HashMap::new(),
        };
        for row in rows {
            let Some(pair) = document_pair(row) else {
                continue;
            };
            *counts.pair.entry(pair.clone()).or_default() += 1;
            *counts
                .pair_type
                .entry(format_compact!("{pair}:{}", row.bridge_type.as_str()))
                .or_default() += 1;
            if let Some(episodes) = episode_pair(row) {
                *counts.episode_pair.entry(episodes).or_default() += 1;
            }
            if has_rationale(row, "entity_support:zero") {
                *counts.zero_by_pair.entry(pair.clone()).or_default() += 1;
            }
            if has_rationale(row, "entity_support:frequency_floor_only") {
                *counts.frequency_by_pair.entry(pair).or_default() += 1;
            }
        }
        counts
    }
}

fn rejection_reason(
    row: &ChunkSemanticBridgeCandidate,
    selected: &SelectedCounts,
    selected_total: usize,
) -> CompactString {
    if bridge_quality_gate_decision(row) != BridgeQualityGateDecision::Accept {
        return "quality_gate".into();
    }
    let Some(pair) = document_pair(row) else {
        return "not_cross_document".into();
    };
    if selected.pair.get(&pair).copied().unwrap_or_default() >= CROSS_DOCUMENT_PAIR_QUOTA {
        return "document_pair_quota".into();
    }
    let pair_type = format_compact!("{pair}:{}", row.bridge_type.as_str());
    if selected
        .pair_type
        .get(&pair_type)
        .copied()
        .unwrap_or_default()
        >= CROSS_DOCUMENT_TYPE_PAIR_QUOTA
    {
        return "document_pair_type_quota".into();
    }
    if episode_pair(row)
        .and_then(|key| selected.episode_pair.get(&key).copied())
        .unwrap_or_default()
        >= CROSS_DOCUMENT_EPISODE_PAIR_QUOTA
    {
        return "episode_pair_quota".into();
    }
    let zero = selected
        .zero_by_pair
        .get(&pair)
        .copied()
        .unwrap_or_default();
    let frequency = selected
        .frequency_by_pair
        .get(&pair)
        .copied()
        .unwrap_or_default();
    if has_rationale(row, "entity_support:zero")
        && (zero >= CROSS_DOCUMENT_ZERO_ENTITY_PAIR_QUOTA
            || zero + frequency >= CROSS_DOCUMENT_WEAK_SUPPORT_PAIR_QUOTA)
    {
        return "zero_entity_support_quota".into();
    }
    if has_rationale(row, "entity_support:frequency_floor_only")
        && (frequency >= CROSS_DOCUMENT_FREQUENCY_FLOOR_PAIR_QUOTA
            || zero + frequency >= CROSS_DOCUMENT_WEAK_SUPPORT_PAIR_QUOTA)
    {
        return "frequency_floor_support_quota".into();
    }
    if selected_total >= BRIDGE_LIMIT {
        return "global_candidate_limit".into();
    }
    "fair_selection_rank".into()
}

fn pair_coverage(
    generated: &[&ChunkSemanticBridgeCandidate],
    selected: &[&ChunkSemanticBridgeCandidate],
) -> Vec<CrossDocumentBridgePairCoverage> {
    let mut generated_by_pair = HashMap::<CompactString, Vec<&ChunkSemanticBridgeCandidate>>::new();
    for row in generated {
        if let Some(pair) = document_pair(row) {
            generated_by_pair.entry(pair).or_default().push(row);
        }
    }
    let mut selected_by_pair = HashMap::<CompactString, Vec<&ChunkSemanticBridgeCandidate>>::new();
    for row in selected {
        if let Some(pair) = document_pair(row) {
            selected_by_pair.entry(pair).or_default().push(row);
        }
    }
    let mut rows = generated_by_pair
        .into_iter()
        .map(|(pair, generated)| {
            let (source, target) = pair.split_once("->").unwrap_or((pair.as_str(), "unknown"));
            let selected = selected_by_pair.get(&pair).cloned().unwrap_or_default();
            let eligible = generated
                .iter()
                .filter(|row| {
                    bridge_quality_gate_decision(row) == BridgeQualityGateDecision::Accept
                })
                .count();
            let mut types = selected
                .iter()
                .map(|row| row.bridge_type)
                .collect::<Vec<_>>();
            types.sort_by_key(|kind| kind.as_str());
            types.dedup();
            CrossDocumentBridgePairCoverage {
                source_document_id: source.into(),
                target_document_id: target.into(),
                generated_candidates: generated.len(),
                eligible_candidates: eligible,
                selected_candidates: selected.len(),
                rejected_candidates: generated.len().saturating_sub(selected.len()),
                selected_bridge_types: types,
                coverage_millis: if eligible == 0 {
                    1000
                } else {
                    ((selected.len().min(eligible) * 1000) / eligible) as u16
                },
            }
        })
        .collect::<Vec<_>>();
    rows.sort_by(|left, right| {
        left.source_document_id
            .cmp(&right.source_document_id)
            .then_with(|| left.target_document_id.cmp(&right.target_document_id))
    });
    rows
}

fn audit_row(
    row: &ChunkSemanticBridgeCandidate,
    rejection_reason: Option<CompactString>,
    chunks: &HashMap<&str, &ChunkSemanticBridgeChunk<'_>>,
) -> CrossDocumentBridgeAuditRow {
    let source = chunks.get(row.source_chunk_id.as_str());
    let target = chunks.get(row.target_chunk_id.as_str());
    CrossDocumentBridgeAuditRow {
        id: row.id.clone(),
        source_document_id: source
            .map(|chunk| chunk.note_id)
            .unwrap_or("unknown")
            .into(),
        target_document_id: target
            .map(|chunk| chunk.note_id)
            .unwrap_or("unknown")
            .into(),
        source_chunk_id: row.source_chunk_id.clone(),
        target_chunk_id: row.target_chunk_id.clone(),
        source_excerpt: excerpt(source.map(|chunk| chunk.text).unwrap_or_default()),
        target_excerpt: excerpt(target.map(|chunk| chunk.text).unwrap_or_default()),
        bridge_type: row.bridge_type,
        claim: row.claim.clone(),
        evidence_ids: row.evidence_ids.clone(),
        supporting_entity_ids: row.supporting_entity_ids.clone(),
        confidence_millis: (row.confidence.clamp(0.0, 1.0) * 1000.0).round() as u16,
        rejection_reason,
        no_topology_commit: row.status == ChunkSemanticBridgeStatus::Candidate
            && row.commit_policy == ChunkSemanticBridgeCommitPolicy::NoTopologyCommit
            && row
                .rationale
                .iter()
                .any(|receipt| receipt == CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT),
    }
}

fn excerpt(text: &str) -> CompactString {
    let normalized = text.split_whitespace().collect::<Vec<_>>().join(" ");
    let mut chars = normalized.chars();
    let excerpt = chars.by_ref().take(240).collect::<String>();
    if chars.next().is_some() {
        format_compact!("{excerpt}...")
    } else {
        excerpt.into()
    }
}

fn document_ids(chunks: &[ChunkSemanticBridgeChunk<'_>]) -> Vec<CompactString> {
    let mut ids = chunks
        .iter()
        .map(|chunk| CompactString::from(chunk.note_id))
        .collect::<Vec<_>>();
    ids.sort();
    ids.dedup();
    ids
}

fn is_cross_document(row: &ChunkSemanticBridgeCandidate) -> bool {
    document_pair(row).is_some()
}

fn document_pair(row: &ChunkSemanticBridgeCandidate) -> Option<CompactString> {
    row.rationale.iter().find_map(|receipt| {
        receipt
            .strip_prefix("document_pair:")
            .filter(|pair| {
                pair.split_once("->")
                    .is_some_and(|(source, target)| source != target)
            })
            .map(CompactString::from)
    })
}

fn episode_pair(row: &ChunkSemanticBridgeCandidate) -> Option<CompactString> {
    Some(format_compact!(
        "{}->{}",
        row.source_episode_id.as_deref()?,
        row.target_episode_id.as_deref()?
    ))
}

fn has_rationale(row: &ChunkSemanticBridgeCandidate, value: &str) -> bool {
    row.rationale.iter().any(|receipt| receipt == value)
}
