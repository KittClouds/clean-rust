use compact_str::{format_compact, CompactString};
use hashbrown::HashMap;

use super::{push_unique, MemoryGovernanceEngineInput, TargetStats};
use crate::types::{GraphMemoryState, GraphRelationship, GraphTemporalEdge};

pub(super) fn assign_contradiction_pressure<'a>(
    input: MemoryGovernanceEngineInput<'a>,
    stats: &mut HashMap<&'a str, TargetStats>,
) {
    let anchor_chunk = input
        .anchors
        .iter()
        .filter_map(|anchor| {
            anchor
                .chunk_id
                .as_ref()
                .map(|chunk_id| (anchor.id.as_str(), chunk_id))
        })
        .collect::<HashMap<_, _>>();
    let event_chunk = input
        .events
        .iter()
        .filter_map(|event| {
            event
                .chunk_id
                .as_ref()
                .map(|chunk_id| (event.id.as_str(), chunk_id))
        })
        .collect::<HashMap<_, _>>();
    let chunk_ordinal = input
        .chunks
        .iter()
        .map(|chunk| (chunk.id.as_str(), chunk.ordinal))
        .collect::<HashMap<_, _>>();
    mark_state_value_conflicts(input.memory_state, &anchor_chunk, &chunk_ordinal, stats);
    mark_relationship_polarity_conflicts(input.relationships, &anchor_chunk, &chunk_ordinal, stats);
    mark_edge_order_conflicts(
        input.temporal_edges,
        &event_chunk,
        stats,
        "temporal_conflict",
    );
    mark_edge_order_conflicts(input.causal_edges, &event_chunk, stats, "causal_conflict");
}

fn mark_relationship_polarity_conflicts<'a>(
    relationships: &[GraphRelationship],
    anchor_chunk: &HashMap<&str, &'a CompactString>,
    chunk_ordinal: &HashMap<&str, u32>,
    stats: &mut HashMap<&'a str, TargetStats>,
) {
    let mut by_pair = HashMap::<CompactString, Vec<RelationshipPolarityRow>>::new();
    for relationship in relationships {
        if relationship.status == "rejected" {
            continue;
        }
        let Some(polarity) = relation_polarity(&relationship.relation_type) else {
            continue;
        };
        let evidence_ids = relationship_evidence_ids(relationship);
        if evidence_ids.is_empty() {
            continue;
        }
        let chunk_ids = chunk_ids_for_evidence(&evidence_ids, anchor_chunk);
        by_pair
            .entry(entity_pair_key(
                relationship.source_entity_id.0.as_str(),
                relationship.target_entity_id.0.as_str(),
            ))
            .or_default()
            .push(RelationshipPolarityRow {
                polarity,
                evidence_ids,
                chunk_ids,
            });
    }

    for rows in by_pair.values() {
        for left_index in 0..rows.len() {
            for right in rows.iter().skip(left_index + 1) {
                let left = &rows[left_index];
                if left.polarity == right.polarity {
                    continue;
                }
                let mut chunk_ids = Vec::new();
                let mut evidence_ids = Vec::new();
                for row in [left, right] {
                    for chunk_id in &row.chunk_ids {
                        push_unique(&mut chunk_ids, chunk_id.clone());
                    }
                    for evidence_id in &row.evidence_ids {
                        push_unique(&mut evidence_ids, evidence_id.clone());
                    }
                }
                if relationship_conflict_is_local(left, right) {
                    for chunk_id in chunk_ids {
                        if let Some(stats_row) = stats.get_mut(chunk_id.as_str()) {
                            mark_contradiction(
                                stats_row,
                                0.74,
                                "relationship_conflict",
                                &evidence_ids,
                                &[],
                            );
                        }
                    }
                } else if let Some(older) = older_relationship_row(left, right, chunk_ordinal) {
                    for chunk_id in &older.chunk_ids {
                        if let Some(stats_row) = stats.get_mut(chunk_id.as_str()) {
                            mark_supersession(
                                stats_row,
                                0.70,
                                "relationship_supersession",
                                &evidence_ids,
                            );
                        }
                    }
                }
            }
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum RelationPolarity {
    Positive,
    Negative,
}

struct RelationshipPolarityRow {
    polarity: RelationPolarity,
    evidence_ids: Vec<CompactString>,
    chunk_ids: Vec<CompactString>,
}

fn relation_polarity(relation_type: &str) -> Option<RelationPolarity> {
    let relation = relation_type.to_ascii_lowercase();
    if contains_any(
        &relation,
        &[
            "approves", "accepts", "accepted", "agrees", "ally", "allied", "alliance", "protect",
            "support", "loyal",
        ],
    ) {
        Some(RelationPolarity::Positive)
    } else if contains_any(
        &relation,
        &[
            "reject",
            "refuse",
            "oppose",
            "opposes",
            "opposition",
            "threat",
            "hostile",
            "enemy",
            "betray",
            "conflict",
            "attack",
            "harm",
        ],
    ) {
        Some(RelationPolarity::Negative)
    } else {
        None
    }
}

fn relationship_evidence_ids(relationship: &GraphRelationship) -> Vec<CompactString> {
    let mut out = Vec::with_capacity(
        relationship.evidence_anchor_ids.len() + relationship.decision_evidence.len(),
    );
    for evidence_id in &relationship.evidence_anchor_ids {
        push_unique(&mut out, evidence_id.clone());
    }
    for evidence_id in &relationship.decision_evidence {
        push_unique(&mut out, evidence_id.clone());
    }
    out
}

fn chunk_ids_for_evidence(
    evidence_ids: &[CompactString],
    anchor_chunk: &HashMap<&str, &CompactString>,
) -> Vec<CompactString> {
    let mut out = Vec::new();
    for evidence_id in evidence_ids {
        if let Some(chunk_id) = anchor_chunk.get(evidence_id.as_str()) {
            push_unique(&mut out, (*chunk_id).clone());
        } else if let Some(chunk_id) = evidence_id.as_str().strip_prefix("chunk:") {
            push_unique(&mut out, chunk_id.into());
        }
    }
    out
}

fn relationship_conflict_is_local(
    left: &RelationshipPolarityRow,
    right: &RelationshipPolarityRow,
) -> bool {
    if left.chunk_ids.is_empty() || right.chunk_ids.is_empty() {
        return true;
    }
    left.chunk_ids
        .iter()
        .any(|chunk_id| right.chunk_ids.iter().any(|other| other == chunk_id))
}

fn older_relationship_row<'a>(
    left: &'a RelationshipPolarityRow,
    right: &'a RelationshipPolarityRow,
    chunk_ordinal: &HashMap<&str, u32>,
) -> Option<&'a RelationshipPolarityRow> {
    let left_order = relationship_row_order(left, chunk_ordinal)?;
    let right_order = relationship_row_order(right, chunk_ordinal)?;
    if left_order < right_order {
        Some(left)
    } else if right_order < left_order {
        Some(right)
    } else {
        None
    }
}

fn relationship_row_order(
    row: &RelationshipPolarityRow,
    chunk_ordinal: &HashMap<&str, u32>,
) -> Option<u32> {
    row.chunk_ids
        .iter()
        .filter_map(|chunk_id| chunk_ordinal.get(chunk_id.as_str()).copied())
        .min()
}

fn entity_pair_key(left: &str, right: &str) -> CompactString {
    if left <= right {
        format_compact!("{left}|{right}")
    } else {
        format_compact!("{right}|{left}")
    }
}

fn mark_state_value_conflicts<'a>(
    memory_state: &[GraphMemoryState],
    anchor_chunk: &HashMap<&str, &'a CompactString>,
    chunk_ordinal: &HashMap<&str, u32>,
    stats: &mut HashMap<&'a str, TargetStats>,
) {
    let mut by_slot = HashMap::<CompactString, Vec<StateValueRow>>::new();
    for state in memory_state {
        let evidence_ids = state.evidence_ids.clone();
        let chunk_ids = chunk_ids_for_evidence(&evidence_ids, anchor_chunk);
        by_slot
            .entry(format_compact!("{}|{}", state.entity_id.0, state.key))
            .or_default()
            .push(StateValueRow {
                key: state.key.clone(),
                value: state.value.clone(),
                evidence_ids,
                chunk_ids,
            });
    }
    for states in by_slot.values() {
        for left_index in 0..states.len() {
            for right in states.iter().skip(left_index + 1) {
                let left = &states[left_index];
                if !memory_values_conflict(&left.key, &left.value, &right.value) {
                    continue;
                }
                let mut chunk_ids = Vec::new();
                let mut evidence_ids = Vec::new();
                for row in [left, right] {
                    for chunk_id in &row.chunk_ids {
                        push_unique(&mut chunk_ids, chunk_id.clone());
                    }
                    for evidence_id in &row.evidence_ids {
                        push_unique(&mut evidence_ids, evidence_id.clone());
                    }
                }
                if state_conflict_is_local(left, right) {
                    for chunk_id in chunk_ids {
                        if let Some(row) = stats.get_mut(chunk_id.as_str()) {
                            mark_contradiction(row, 0.78, "state_conflict", &evidence_ids, &[]);
                        }
                    }
                } else if let Some(older) = older_state_row(left, right, chunk_ordinal) {
                    for chunk_id in &older.chunk_ids {
                        if let Some(row) = stats.get_mut(chunk_id.as_str()) {
                            mark_supersession(row, 0.72, "state_supersession", &evidence_ids);
                        }
                    }
                }
            }
        }
    }
}

struct StateValueRow {
    key: CompactString,
    value: CompactString,
    evidence_ids: Vec<CompactString>,
    chunk_ids: Vec<CompactString>,
}

fn state_conflict_is_local(left: &StateValueRow, right: &StateValueRow) -> bool {
    if left.chunk_ids.is_empty() || right.chunk_ids.is_empty() {
        return true;
    }
    left.chunk_ids
        .iter()
        .any(|chunk_id| right.chunk_ids.iter().any(|other| other == chunk_id))
}

fn older_state_row<'a>(
    left: &'a StateValueRow,
    right: &'a StateValueRow,
    chunk_ordinal: &HashMap<&str, u32>,
) -> Option<&'a StateValueRow> {
    let left_order = state_row_order(left, chunk_ordinal)?;
    let right_order = state_row_order(right, chunk_ordinal)?;
    if left_order < right_order {
        Some(left)
    } else if right_order < left_order {
        Some(right)
    } else {
        None
    }
}

fn state_row_order(row: &StateValueRow, chunk_ordinal: &HashMap<&str, u32>) -> Option<u32> {
    row.chunk_ids
        .iter()
        .filter_map(|chunk_id| chunk_ordinal.get(chunk_id.as_str()).copied())
        .min()
}

fn mark_edge_order_conflicts<'a>(
    edges: &[GraphTemporalEdge],
    event_chunk: &HashMap<&str, &'a CompactString>,
    stats: &mut HashMap<&'a str, TargetStats>,
    kind: &'static str,
) {
    let mut seen = HashMap::<CompactString, &GraphTemporalEdge>::with_capacity(edges.len());
    for edge in edges {
        let Some((source, target)) = normalized_order(edge) else {
            continue;
        };
        let forward = format_compact!("{source}->{target}");
        let inverse = format_compact!("{target}->{source}");
        if let Some(other) = seen.get(inverse.as_str()) {
            mark_edge_conflict(edge, other, event_chunk, stats, kind);
        }
        seen.insert(forward, edge);
    }
}

fn mark_edge_conflict<'a>(
    left: &GraphTemporalEdge,
    right: &GraphTemporalEdge,
    event_chunk: &HashMap<&str, &'a CompactString>,
    stats: &mut HashMap<&'a str, TargetStats>,
    kind: &'static str,
) {
    let mut chunk_ids = Vec::new();
    let mut evidence_ids = Vec::new();
    let mut event_ids = Vec::new();
    for edge in [left, right] {
        for event_id in [edge.source_id.as_str(), edge.target_id.as_str()] {
            push_unique(&mut event_ids, event_id.into());
            if let Some(chunk_id) = event_chunk.get(event_id) {
                push_unique(&mut chunk_ids, (*chunk_id).clone());
            }
        }
        for evidence_id in &edge.evidence_ids {
            push_unique(&mut evidence_ids, evidence_id.clone());
        }
    }
    for chunk_id in chunk_ids {
        if let Some(row) = stats.get_mut(chunk_id.as_str()) {
            mark_contradiction(row, 0.72, kind, &evidence_ids, &event_ids);
        }
    }
}

fn mark_contradiction(
    row: &mut TargetStats,
    risk: f32,
    kind: &'static str,
    evidence_ids: &[CompactString],
    event_ids: &[CompactString],
) {
    row.contradiction_count += 1;
    row.contradiction_risk = row.contradiction_risk.max(risk).min(1.0);
    row.contradiction_kinds.insert(kind.into());
    for evidence_id in evidence_ids {
        push_unique(&mut row.evidence_ids, evidence_id.clone());
    }
    for event_id in event_ids {
        push_unique(&mut row.event_ids, event_id.clone());
    }
}

fn mark_supersession(
    row: &mut TargetStats,
    risk: f32,
    kind: &'static str,
    evidence_ids: &[CompactString],
) {
    row.supersession_count += 1;
    row.supersession_risk = row.supersession_risk.max(risk).min(1.0);
    row.supersession_kinds.insert(kind.into());
    for evidence_id in evidence_ids {
        push_unique(&mut row.evidence_ids, evidence_id.clone());
    }
}

fn memory_values_conflict(key: &str, left: &str, right: &str) -> bool {
    let left = normalize_memory_value(left);
    let right = normalize_memory_value(right);
    if left.is_empty() || right.is_empty() || left == right {
        return false;
    }
    if left.contains("cue:") || right.contains("cue:") {
        return false;
    }
    if negates_same_value(&left, &right) {
        return true;
    }
    let decision = key.contains("decision") || key.contains("approval");
    (decision
        && opposite_bucket(
            &left,
            &right,
            &["approved", "accepted", "agreed", "yes"],
            &["rejected", "refused", "denied", "no"],
        ))
        || opposite_bucket(&left, &right, &["alive", "living"], &["dead", "killed"])
        || opposite_bucket(
            &left,
            &right,
            &["present", "arrived", "here"],
            &["absent", "missing", "gone"],
        )
        || opposite_bucket(
            &left,
            &right,
            &["ally", "allied", "friend", "loyal"],
            &["enemy", "hostile", "betray", "opposes"],
        )
        || opposite_bucket(&left, &right, &["open", "unlocked"], &["closed", "locked"])
        || opposite_bucket(
            &left,
            &right,
            &["true", "confirmed"],
            &["false", "uncertain", "rumor"],
        )
}

fn normalize_memory_value(value: &str) -> CompactString {
    value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == ':' {
                ch.to_ascii_lowercase()
            } else {
                ' '
            }
        })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .into()
}

fn negates_same_value(left: &str, right: &str) -> bool {
    let left_negated = strip_negation(left);
    let right_negated = strip_negation(right);
    matches!((left_negated, right_negated), (Some(a), None) if a == right)
        || matches!((left_negated, right_negated), (None, Some(b)) if left == b)
}

fn strip_negation(value: &str) -> Option<&str> {
    value
        .strip_prefix("not ")
        .or_else(|| value.strip_prefix("no "))
        .or_else(|| value.strip_prefix("never "))
}

fn opposite_bucket(left: &str, right: &str, positive: &[&str], negative: &[&str]) -> bool {
    (contains_any(left, positive) && contains_any(right, negative))
        || (contains_any(left, negative) && contains_any(right, positive))
}

fn contains_any(value: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| value.contains(needle))
}

fn normalized_order(edge: &GraphTemporalEdge) -> Option<(&str, &str)> {
    let relation = edge.relation_type.as_str();
    if relation.contains("before") || relation.contains("cause") || relation.contains("explain") {
        Some((edge.source_id.as_str(), edge.target_id.as_str()))
    } else if relation.contains("after") {
        Some((edge.target_id.as_str(), edge.source_id.as_str()))
    } else {
        None
    }
}
