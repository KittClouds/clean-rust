use std::collections::{BTreeSet, HashMap};

use compact_str::{format_compact, CompactString};
use phoenix_types::EntityId;

use super::{
    representative_anchors, safe_prefix, structure_root_id, structure_root_targets, temporal_target,
};
use crate::types::{
    GraphDiscourseSpineSummary, GraphDocumentCompilerHyperedge, GraphDocumentCompilerHyperedgeRole,
    GraphDocumentCompilerSummary, GraphDocumentEvidenceSpan, GraphDocumentReviewSummary,
    GraphDocumentSidecarSummary, GraphDocumentUnitSummary, GraphEmbeddingTarget,
    GraphRebuildSnapshot,
};

pub fn build_snapshot_embedding_targets(
    snapshot: &GraphRebuildSnapshot,
) -> Vec<GraphEmbeddingTarget> {
    let mut targets = if snapshot.embedding_targets.is_empty() {
        base_targets_from_snapshot(snapshot)
    } else {
        snapshot.embedding_targets.clone()
    };
    let mut seen = targets
        .iter()
        .map(|target| target.id.clone())
        .collect::<BTreeSet<_>>();
    let sidecar = snapshot.document_sidecar_summary.as_ref();
    let evidence_by_id = evidence_spans_by_id(sidecar);
    if let Some(summary) = sidecar {
        add_document_sidecar_targets(&mut targets, &mut seen, summary);
    }
    add_document_review_targets(
        &mut targets,
        &mut seen,
        snapshot.document_review_summary.as_ref(),
    );
    add_document_compiler_targets(
        &mut targets,
        &mut seen,
        snapshot.document_compiler_summary.as_ref(),
        &evidence_by_id,
        snapshot.note_ids.first(),
    );
    add_discourse_targets(
        &mut targets,
        &mut seen,
        snapshot.discourse_spine_summary.as_ref(),
    );
    targets.sort_by(|left, right| left.id.cmp(&right.id));
    targets
}

fn base_targets_from_snapshot(snapshot: &GraphRebuildSnapshot) -> Vec<GraphEmbeddingTarget> {
    let mut targets = Vec::with_capacity(
        snapshot.note_ids.len() * 6
            + snapshot.chunks.len()
            + snapshot.entity_anchors.len()
            + snapshot.nodes.len()
            + snapshot.relationships.len()
            + snapshot.events.len()
            + snapshot.temporal_edges.len()
            + snapshot.causal_edges.len()
            + snapshot.memory_state.len(),
    );
    for note_id in &snapshot.note_ids {
        targets.push(GraphEmbeddingTarget {
            id: format_compact!("embed:note:{note_id}"),
            kind: "note".into(),
            source_id: note_id.clone(),
            note_id: Some(note_id.clone()),
            chunk_id: None,
            entity_id: None,
            label: format_compact!("Note {note_id}"),
            text: format_compact!("note:{note_id}"),
            evidence_ids: Vec::new(),
            parent_ids: Vec::new(),
            ..GraphEmbeddingTarget::default()
        });
        targets.extend(structure_root_targets(note_id));
    }
    targets.extend(snapshot.chunks.iter().map(|chunk| GraphEmbeddingTarget {
        id: format_compact!("embed:chunk:{}", chunk.id),
        kind: "chunk".into(),
        source_id: chunk.id.clone(),
        note_id: Some(chunk.note_id.clone()),
        chunk_id: Some(chunk.id.clone()),
        entity_id: None,
        label: format_compact!("Chunk {}", chunk.ordinal + 1),
        text: format_compact!(
            "chunk:{} note:{} range:{}-{} source:{}",
            chunk.id,
            chunk.note_id,
            chunk.start,
            chunk.end,
            chunk.source
        ),
        evidence_ids: Vec::new(),
        parent_ids: vec![structure_root_id(&chunk.note_id, "document-structure")],
        ..GraphEmbeddingTarget::default()
    }));
    targets.extend(snapshot.nodes.iter().map(|node| GraphEmbeddingTarget {
        id: format_compact!("embed:entity:{}", node.entity_id.0),
        kind: "entity".into(),
        source_id: node.entity_id.0.as_str().into(),
        note_id: None,
        chunk_id: None,
        entity_id: Some(node.entity_id.clone()),
        label: node.label.clone(),
        text: format_compact!(
            "{} kind:{} aliases:{} mentions:{}",
            node.label,
            node.kind,
            join_compact(&node.aliases),
            node.total_mentions
        ),
        evidence_ids: node.anchor_ids.clone(),
        parent_ids: Vec::new(),
        ..GraphEmbeddingTarget::default()
    }));
    targets.extend(
        representative_anchors(&snapshot.entity_anchors)
            .into_iter()
            .map(|anchor| GraphEmbeddingTarget {
                id: format_compact!("embed:anchor:{}", anchor.id),
                kind: "anchor".into(),
                source_id: anchor.id.clone(),
                note_id: Some(anchor.note_id.clone()),
                chunk_id: anchor.chunk_id.clone(),
                entity_id: Some(anchor.entity_id.clone()),
                label: anchor.surface.clone(),
                text: format_compact!(
                    "surface:{} source:{} confidence:{:.2}",
                    anchor.surface,
                    anchor.source,
                    anchor.confidence
                ),
                evidence_ids: vec![anchor.id.clone()],
                parent_ids: vec![structure_root_id(&anchor.note_id, "evidence")],
                ..GraphEmbeddingTarget::default()
            }),
    );
    targets.extend(snapshot.relationships.iter().filter_map(|relationship| {
        if relationship.status == "rejected" {
            return None;
        }
        Some(GraphEmbeddingTarget {
            id: format_compact!("embed:graph-fact:{}", relationship.id),
            kind: "graphFact".into(),
            source_id: relationship.id.clone(),
            note_id: None,
            chunk_id: None,
            entity_id: None,
            label: format_compact!(
                "{} {} {}",
                relationship.source_entity_id.0,
                relationship.relation_type,
                relationship.target_entity_id.0
            ),
            text: format_compact!(
                "{} {} {} [{}] confidence:{:.2}",
                relationship.source_entity_id.0,
                relationship.relation_type,
                relationship.target_entity_id.0,
                relationship.status,
                relationship.confidence
            ),
            evidence_ids: relationship.evidence_anchor_ids.clone(),
            parent_ids: vec![
                format_compact!("embed:entity:{}", relationship.source_entity_id.0),
                format_compact!("embed:entity:{}", relationship.target_entity_id.0),
            ],
            ..GraphEmbeddingTarget::default()
        })
    }));
    targets.extend(snapshot.events.iter().map(|event| GraphEmbeddingTarget {
        id: format_compact!("embed:event:{}", event.id),
        kind: "event".into(),
        source_id: event.id.clone(),
        note_id: Some(event.note_id.clone()),
        chunk_id: event.chunk_id.clone(),
        entity_id: event.entity_ids.first().cloned(),
        label: event.label.clone(),
        text: event.label.clone(),
        evidence_ids: event.evidence_anchor_ids.clone(),
        parent_ids: vec![structure_root_id(&event.note_id, "temporal")],
        ..GraphEmbeddingTarget::default()
    }));
    let default_note = snapshot
        .note_ids
        .first()
        .map(CompactString::as_str)
        .unwrap_or("scope");
    targets.extend(
        snapshot
            .temporal_edges
            .iter()
            .map(|edge| temporal_target(default_note, edge, "temporalFact")),
    );
    targets.extend(
        snapshot
            .causal_edges
            .iter()
            .map(|edge| temporal_target(default_note, edge, "causalFact")),
    );
    targets.extend(snapshot.memory_state.iter().map(|state| {
        GraphEmbeddingTarget {
            id: format_compact!("embed:memory:{}", state.id),
            kind: "memoryState".into(),
            source_id: state.id.clone(),
            note_id: state.note_id.clone(),
            chunk_id: None,
            entity_id: Some(state.entity_id.clone()),
            label: state.key.clone(),
            text: format_compact!("{} {}", state.key, state.value),
            evidence_ids: state.evidence_ids.clone(),
            parent_ids: state
                .note_id
                .as_ref()
                .map(|note_id| vec![structure_root_id(note_id, "identity")])
                .unwrap_or_default(),
            ..GraphEmbeddingTarget::default()
        }
    }));
    targets
}

fn add_document_sidecar_targets(
    targets: &mut Vec<GraphEmbeddingTarget>,
    seen: &mut BTreeSet<CompactString>,
    summary: &GraphDocumentSidecarSummary,
) {
    for unit in &summary.units {
        push_target(
            targets,
            seen,
            document_unit_target(unit, "documentUnit", "document_unit"),
        );
    }
    for unit in &summary.sections {
        push_target(
            targets,
            seen,
            document_unit_target(unit, "documentUnit", "section"),
        );
    }
    for unit in &summary.regions {
        push_target(
            targets,
            seen,
            document_unit_target(unit, "documentUnit", "region"),
        );
    }
    for unit in &summary.rhetorical_units {
        push_target(
            targets,
            seen,
            document_unit_target(unit, "documentUnit", "rhetorical_unit"),
        );
    }
    for unit in &summary.retrieval_units {
        push_target(
            targets,
            seen,
            document_unit_target(unit, "documentUnit", "retrieval_unit"),
        );
    }
    for unit in &summary.graph_fact_candidates {
        push_target(
            targets,
            seen,
            document_unit_target(unit, "graphFact", "graph_fact"),
        );
    }
    for span in &summary.evidence_spans {
        push_target(targets, seen, evidence_span_target(span));
    }
}

fn document_unit_target(
    unit: &GraphDocumentUnitSummary,
    kind: &str,
    family: &str,
) -> GraphEmbeddingTarget {
    let evidence_ids = unit.evidence_span_ids.clone();
    let parent_ids = unit
        .parent_id
        .iter()
        .map(|parent| format_compact!("embed:document-unit:{parent}"))
        .chain(std::iter::once(structure_root_id(
            &unit.note_id,
            if kind == "graphFact" {
                "causal"
            } else {
                "document-structure"
            },
        )))
        .collect::<Vec<_>>();
    let label = unit
        .predicate
        .as_ref()
        .or(unit.relation_type.as_ref())
        .unwrap_or(&unit.label)
        .clone();
    let target_id = if kind == "graphFact" {
        format_compact!("embed:document-fact:{}", unit.id)
    } else {
        format_compact!("embed:document-unit:{}", unit.id)
    };
    GraphEmbeddingTarget {
        id: target_id,
        kind: kind.into(),
        source_id: unit.id.clone(),
        note_id: Some(unit.note_id.clone()),
        chunk_id: unit.target_chunk_ids.first().cloned(),
        entity_id: None,
        label,
        text: compact_lines([
            format_compact!("document_sidecar:{family}"),
            format_compact!("kind:{}", unit.kind),
            format_compact!("label:{}", unit.label),
            format_compact!("range:{}-{}", unit.start, unit.end),
            format_compact!("depth:{}", unit.depth),
            optional_line("predicate", unit.predicate.as_ref()),
            optional_line("relation_type", unit.relation_type.as_ref()),
            optional_line("frame_family", unit.frame_family.as_ref()),
            optional_line("semantic_situation", unit.semantic_situation_id.as_ref()),
            list_line("subjects", &unit.subject_surfaces),
            list_line("objects", &unit.object_surfaces),
            list_line("evidence", &unit.evidence_span_ids),
        ]),
        evidence_ids,
        parent_ids,
        ..GraphEmbeddingTarget::default()
    }
}

fn evidence_span_target(span: &GraphDocumentEvidenceSpan) -> GraphEmbeddingTarget {
    GraphEmbeddingTarget {
        id: format_compact!("embed:document-evidence:{}", span.id),
        kind: "evidenceSpan".into(),
        source_id: span.id.clone(),
        note_id: Some(span.note_id.clone()),
        chunk_id: span.chunk_id.clone(),
        entity_id: None,
        label: format_compact!("Evidence {}", span.id),
        text: compact_lines([
            format_compact!("document_evidence_span:{}", span.id),
            format_compact!("range:{}-{}", span.start, span.end),
            optional_line("unit", span.unit_id.as_ref()),
            optional_line("preview", span.preview.as_ref()),
            format_compact!("confidence:{:.2}", span.confidence.score),
        ]),
        evidence_ids: vec![span.id.clone()],
        parent_ids: vec![structure_root_id(&span.note_id, "evidence")],
        ..GraphEmbeddingTarget::default()
    }
}

fn add_document_review_targets(
    targets: &mut Vec<GraphEmbeddingTarget>,
    seen: &mut BTreeSet<CompactString>,
    review: Option<&GraphDocumentReviewSummary>,
) {
    let Some(review) = review else {
        return;
    };
    for row in &review.rows {
        push_target(
            targets,
            seen,
            GraphEmbeddingTarget {
                id: format_compact!("embed:review:{}", row.id),
                kind: "graphFact".into(),
                source_id: format_compact!("review:{}", row.object_id),
                note_id: Some(row.note_id.clone()),
                chunk_id: None,
                entity_id: None,
                label: row.title.clone(),
                text: compact_lines([
                    format_compact!("review_state:{}", row.state),
                    format_compact!("object_kind:{}", row.object_kind),
                    format_compact!("object_id:{}", row.object_id),
                    format_compact!("confidence:{:.2}", row.confidence),
                    optional_line("subtitle", Some(&row.subtitle)),
                    optional_line("detail", Some(&row.detail)),
                    optional_line("detector", Some(&row.detector)),
                    list_line("why", &row.why),
                    list_line("related", &row.related_object_ids),
                ]),
                evidence_ids: row.evidence_span_ids.clone(),
                parent_ids: review_parent_ids(row),
                ..GraphEmbeddingTarget::default()
            },
        );
    }
}

fn review_parent_ids(row: &crate::types::GraphDocumentReviewRow) -> Vec<CompactString> {
    let mut parents = row
        .parent_unit_ids
        .iter()
        .map(|id| format_compact!("embed:document-unit:{id}"))
        .collect::<Vec<_>>();
    parents.push(structure_root_id(&row.note_id, "document-structure"));
    parents
}

fn add_document_compiler_targets(
    targets: &mut Vec<GraphEmbeddingTarget>,
    seen: &mut BTreeSet<CompactString>,
    compiler: Option<&GraphDocumentCompilerSummary>,
    evidence_by_id: &HashMap<CompactString, &GraphDocumentEvidenceSpan>,
    default_note_id: Option<&CompactString>,
) {
    let Some(compiler) = compiler else {
        return;
    };
    for hyperedge in &compiler.hyperedges {
        let note_id = hyperedge_note_id(hyperedge, evidence_by_id, default_note_id);
        let role_ids = hyperedge
            .roles
            .iter()
            .map(|role| hyperedge_role_target_id(role))
            .collect::<Vec<_>>();
        for role in &hyperedge.roles {
            push_target(
                targets,
                seen,
                hyperedge_role_target(hyperedge, role, &note_id),
            );
        }
        push_target(
            targets,
            seen,
            GraphEmbeddingTarget {
                id: format_compact!("embed:fact:document-hyperedge:{}", hyperedge.id),
                kind: "graphFact".into(),
                source_id: format_compact!("fact:document-hyperedge:{}", hyperedge.id),
                note_id: Some(note_id.clone()),
                chunk_id: None,
                entity_id: None,
                label: hyperedge
                    .frame
                    .as_ref()
                    .or(hyperedge.trigger_predicate.as_ref())
                    .unwrap_or(&hyperedge.predicate)
                    .clone(),
                text: hyperedge_text(hyperedge),
                evidence_ids: hyperedge.evidence_span_ids.clone(),
                parent_ids: role_ids,
                ..GraphEmbeddingTarget::default()
            },
        );
    }
}

fn hyperedge_role_target(
    hyperedge: &GraphDocumentCompilerHyperedge,
    role: &GraphDocumentCompilerHyperedgeRole,
    note_id: &CompactString,
) -> GraphEmbeddingTarget {
    let semantic_role = role.semantic_role.as_ref().unwrap_or(&role.role);
    let target_kind = role.target_kind.as_str();
    let kind = match target_kind {
        "evidence_span" => "evidenceSpan",
        "document_unit" | "retrieval_unit" => "documentUnit",
        _ => "concept",
    };
    let entity_id = if target_kind == "entity" {
        Some(EntityId(role.target_id.to_string()))
    } else {
        None
    };
    GraphEmbeddingTarget {
        id: hyperedge_role_target_id(role),
        kind: kind.into(),
        source_id: role.id.clone(),
        note_id: Some(note_id.clone()),
        chunk_id: None,
        entity_id,
        label: role.surface.as_ref().unwrap_or(semantic_role).clone(),
        text: compact_lines([
            format_compact!("hypergraph_role:{semantic_role}"),
            format_compact!("hyperedge:{}", hyperedge.id),
            format_compact!("target_kind:{}", role.target_kind),
            format_compact!("target_id:{}", role.target_id),
            optional_line("slot_type", role.slot_type.as_ref()),
            optional_line("surface", role.surface.as_ref()),
            format_compact!("resolved:{}", role.resolved.unwrap_or(true)),
            format_compact!("required:{}", role.required.unwrap_or(false)),
            format_compact!("confidence:{:.2}", role.confidence),
        ]),
        evidence_ids: if role.target_kind == "evidence_span" {
            vec![role.target_id.clone()]
        } else {
            hyperedge.evidence_span_ids.clone()
        },
        parent_ids: hyperedge_role_parent_ids(role, note_id),
        ..GraphEmbeddingTarget::default()
    }
}

fn hyperedge_role_target_id(role: &GraphDocumentCompilerHyperedgeRole) -> CompactString {
    format_compact!("embed:hypergraph-role:{}", role.id)
}

fn hyperedge_role_parent_ids(
    role: &GraphDocumentCompilerHyperedgeRole,
    note_id: &CompactString,
) -> Vec<CompactString> {
    match role.target_kind.as_str() {
        "entity" => vec![format_compact!("embed:entity:{}", role.target_id)],
        "entity_mention" => vec![structure_root_id(note_id, "identity")],
        "evidence_span" => vec![format_compact!(
            "embed:document-evidence:{}",
            role.target_id
        )],
        _ => vec![format_compact!("embed:document-unit:{}", role.target_id)],
    }
}

fn hyperedge_text(hyperedge: &GraphDocumentCompilerHyperedge) -> CompactString {
    let roles = hyperedge
        .roles
        .iter()
        .map(|role| {
            format_compact!(
                "{}:{}",
                role.semantic_role.as_ref().unwrap_or(&role.role),
                role.surface.as_ref().unwrap_or(&role.target_id)
            )
        })
        .collect::<Vec<_>>();
    compact_lines([
        format_compact!(
            "semantic_situation:{}",
            optional_value(&hyperedge.semantic_situation_id)
        ),
        format_compact!("predicate:{}", hyperedge.predicate),
        optional_line("frame", hyperedge.frame.as_ref()),
        optional_line("frame_family", hyperedge.frame_family.as_ref()),
        optional_line("situation_kind", hyperedge.situation_kind.as_ref()),
        optional_line("factuality", hyperedge.factuality.as_ref()),
        optional_line("speech_act", hyperedge.speech_act.as_ref()),
        format_compact!("status:{}", hyperedge.status),
        format_compact!("confidence:{:.2}", hyperedge.confidence),
        list_line("roles", &roles),
        list_line("evidence", &hyperedge.evidence_span_ids),
    ])
}

fn add_discourse_targets(
    targets: &mut Vec<GraphEmbeddingTarget>,
    seen: &mut BTreeSet<CompactString>,
    discourse: Option<&GraphDiscourseSpineSummary>,
) {
    let Some(discourse) = discourse else {
        return;
    };
    for cluster in &discourse.clusters {
        push_target(
            targets,
            seen,
            GraphEmbeddingTarget {
                id: format_compact!("embed:discourse-cluster:{}", cluster.id),
                kind: "graphFact".into(),
                source_id: cluster.id.clone(),
                note_id: None,
                chunk_id: None,
                entity_id: None,
                label: cluster.label.clone(),
                text: compact_lines([
                    format_compact!("discourse_cluster:{}", cluster.kind),
                    format_compact!("score:{:.2}", cluster.score),
                    list_line("target_ids", &cluster.target_ids),
                ]),
                evidence_ids: cluster.target_ids.clone(),
                parent_ids: cluster.target_ids.clone(),
                ..GraphEmbeddingTarget::default()
            },
        );
    }
    for bridge in &discourse.bridges {
        push_target(
            targets,
            seen,
            GraphEmbeddingTarget {
                id: format_compact!("embed:discourse-bridge:{}", bridge.id),
                kind: "graphFact".into(),
                source_id: bridge.id.clone(),
                note_id: None,
                chunk_id: None,
                entity_id: None,
                label: bridge.label.clone(),
                text: compact_lines([
                    format_compact!("discourse_bridge:{}", bridge.kind),
                    format_compact!("status:{}", bridge.status),
                    list_line("shared_labels", &bridge.shared_label_ids),
                    list_line("shared_entities", &bridge.shared_entity_ids),
                ]),
                evidence_ids: bridge.evidence_target_ids.clone(),
                parent_ids: vec![
                    bridge.source_target_id.clone(),
                    bridge.target_target_id.clone(),
                ],
                ..GraphEmbeddingTarget::default()
            },
        );
    }
}

fn evidence_spans_by_id(
    sidecar: Option<&GraphDocumentSidecarSummary>,
) -> HashMap<CompactString, &GraphDocumentEvidenceSpan> {
    sidecar
        .map(|summary| {
            summary
                .evidence_spans
                .iter()
                .map(|span| (span.id.clone(), span))
                .collect()
        })
        .unwrap_or_default()
}

fn hyperedge_note_id(
    hyperedge: &GraphDocumentCompilerHyperedge,
    evidence_by_id: &HashMap<CompactString, &GraphDocumentEvidenceSpan>,
    default_note_id: Option<&CompactString>,
) -> CompactString {
    if let Some(provenance) = &hyperedge.provenance {
        return provenance.note_id.clone();
    }
    hyperedge
        .evidence_span_ids
        .iter()
        .find_map(|id| evidence_by_id.get(id).map(|span| span.note_id.clone()))
        .or_else(|| default_note_id.cloned())
        .unwrap_or_else(|| "scope".into())
}

fn push_target(
    targets: &mut Vec<GraphEmbeddingTarget>,
    seen: &mut BTreeSet<CompactString>,
    target: GraphEmbeddingTarget,
) {
    if seen.insert(target.id.clone()) {
        targets.push(target);
    }
}

fn compact_lines<const N: usize>(lines: [CompactString; N]) -> CompactString {
    let mut text = String::new();
    for line in lines {
        if line.is_empty() {
            continue;
        }
        if !text.is_empty() {
            text.push('\n');
        }
        text.push_str(&line);
    }
    safe_prefix(&text, 2400).into()
}

fn optional_line(key: &str, value: Option<&CompactString>) -> CompactString {
    value
        .filter(|value| !value.is_empty())
        .map(|value| format_compact!("{key}:{value}"))
        .unwrap_or_default()
}

fn optional_value(value: &Option<CompactString>) -> CompactString {
    value.as_ref().cloned().unwrap_or_else(|| "unknown".into())
}

fn list_line(key: &str, values: &[CompactString]) -> CompactString {
    if values.is_empty() {
        CompactString::default()
    } else {
        format_compact!("{key}:{}", join_compact(values))
    }
}

fn join_compact(values: &[CompactString]) -> String {
    let mut out = String::new();
    for value in values {
        if value.is_empty() {
            continue;
        }
        if !out.is_empty() {
            out.push('|');
        }
        out.push_str(value);
    }
    out
}
