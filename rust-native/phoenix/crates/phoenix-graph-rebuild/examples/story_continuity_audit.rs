use std::{env, fs, path::PathBuf, time::Instant};

use phoenix_graph_rebuild::{
    assert_story_continuity_candidate_only, build_chunk_semantic_bridge_candidates_from_snapshot,
    build_document_semantic_summary, build_graph_rebuild_snapshot, build_story_continuity_contract,
    ChunkSemanticBridgeSnapshotDocument, DocumentSemanticInput, DocumentSemanticRequest,
    DocumentSemanticSummary, GraphRebuildInput, GraphRebuildSnapshot, GraphScopeKind,
    StoryContinuityDocument, StoryContinuityInput,
};
use phoenix_types::ScopeKey;
use serde_json::json;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    let root = args
        .next()
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("../../../../.."));
    let requested = args.collect::<Vec<_>>();
    let names = if requested.is_empty() {
        vec![
            "shortrun.md".to_owned(),
            "midrun.md".to_owned(),
            "laterun.md".to_owned(),
            "endrun.md".to_owned(),
        ]
    } else {
        requested
    };
    let documents = names
        .iter()
        .map(|name| {
            let path = root.join("docs").join(name);
            let text = fs::read_to_string(&path)?;
            Ok(StoryContinuityDocument {
                note_id: name.as_str().into(),
                text,
            })
        })
        .collect::<Result<Vec<_>, std::io::Error>>()?;

    let total_started = Instant::now();
    let mut snapshots = Vec::new();
    let mut semantic_documents = Vec::new();
    let mut semantic_counters = None;
    let mut per_document = Vec::new();
    for document in &documents {
        let started = Instant::now();
        let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
            scope_kind: GraphScopeKind::MultiNote,
            scope_id: "trilogy-continuity-audit",
            note_id: document.note_id.as_str(),
            text: document.text.as_str(),
            scope: ScopeKey::default(),
            entities: &[],
            candidate_count: 0,
            built_at: Some(42),
        })?;
        let semantic = build_document_semantic_summary(&DocumentSemanticRequest {
            documents: vec![DocumentSemanticInput {
                note_id: document.note_id.to_string(),
                text: document.text.clone(),
            }],
            entities: Vec::new(),
        });
        per_document.push(json!({
            "noteId": document.note_id,
            "chars": document.text.chars().count(),
            "chunks": snapshot.chunks.len(),
            "legacyEvents": snapshot.events.len(),
            "semanticSituations": semantic.counters.situation_instances,
            "semanticOrderings": semantic.counters.event_orderings,
            "semanticStates": semantic.counters.state_intervals,
            "semanticConflicts": semantic.counters.temporal_conflicts,
            "buildMicros": started.elapsed().as_micros(),
        }));
        semantic_documents.extend(semantic.documents);
        semantic_counters.get_or_insert(semantic.counters);
        snapshots.push(snapshot);
    }

    let snapshot = merge_snapshots(snapshots);
    let semantic = DocumentSemanticSummary {
        schema_version: "phoenix-document-semantics/v1".to_owned(),
        source: "rust_document_semantics".to_owned(),
        documents: semantic_documents,
        counters: semantic_counters.unwrap_or_default(),
    };
    let bridge_documents = documents
        .iter()
        .map(|document| ChunkSemanticBridgeSnapshotDocument {
            note_id: document.note_id.as_str(),
            text: document.text.as_str(),
        })
        .collect::<Vec<_>>();
    let bridge_started = Instant::now();
    let bridges =
        build_chunk_semantic_bridge_candidates_from_snapshot(&snapshot, &bridge_documents);
    let bridge_micros = bridge_started.elapsed().as_micros();
    let continuity_started = Instant::now();
    let contract = build_story_continuity_contract(StoryContinuityInput {
        snapshot: &snapshot,
        documents: &documents,
        semantic_summary: Some(&semantic),
        bridge_candidates: &bridges,
    });
    assert_story_continuity_candidate_only(&contract)?;
    let continuity_micros = continuity_started.elapsed().as_micros();
    let cross_document_bridges = bridges
        .iter()
        .filter(|bridge| {
            let source = snapshot
                .chunks
                .iter()
                .find(|chunk| chunk.id == bridge.source_chunk_id);
            let target = snapshot
                .chunks
                .iter()
                .find(|chunk| chunk.id == bridge.target_chunk_id);
            matches!((source, target), (Some(left), Some(right)) if left.note_id != right.note_id)
        })
        .count();

    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "schemaVersion": "phoenix-story-continuity-audit/v1",
            "documents": per_document,
            "aggregate": {
                "chunks": snapshot.chunks.len(),
                "semanticBridges": bridges.len(),
                "crossDocumentBridges": cross_document_bridges,
                "continuity": contract.certificate.counters,
                "noTopologyWrites": contract.certificate.no_topology_writes,
                "allRowsEvidenced": contract.certificate.all_rows_evidenced,
                "stableSourceIdentities": contract.certificate.stable_source_identities,
                "fixedBatchingDetected": contract.certificate.fixed_batching_detected,
                "phaseMicros": {
                    "eventIdentity": contract.certificate.event_identity_micros,
                    "episodeBoundary": contract.certificate.episode_boundary_micros,
                    "relationResolution": contract.certificate.relation_resolution_micros,
                },
            },
            "timing": {
                "bridgeMicros": bridge_micros,
                "continuityMicros": continuity_micros,
                "totalMicros": total_started.elapsed().as_micros(),
            },
        }))?
    );
    Ok(())
}

fn merge_snapshots(mut snapshots: Vec<GraphRebuildSnapshot>) -> GraphRebuildSnapshot {
    let mut merged = snapshots.remove(0);
    merged.id = "graph-rebuild:trilogy-continuity-audit:42".into();
    merged.scope_id = "trilogy-continuity-audit".into();
    for mut snapshot in snapshots {
        merged.note_ids.append(&mut snapshot.note_ids);
        merged.chunks.append(&mut snapshot.chunks);
        merged.mentions.append(&mut snapshot.mentions);
        merged.entity_anchors.append(&mut snapshot.entity_anchors);
        merged.relationships.append(&mut snapshot.relationships);
        merged.events.append(&mut snapshot.events);
        merged.episodes.append(&mut snapshot.episodes);
        merged.temporal_edges.append(&mut snapshot.temporal_edges);
        merged.causal_edges.append(&mut snapshot.causal_edges);
        merged.memory_state.append(&mut snapshot.memory_state);
        merged.nodes.append(&mut snapshot.nodes);
        merged.edges.append(&mut snapshot.edges);
    }
    merged.note_ids.sort();
    merged.note_ids.dedup();
    merged
}
