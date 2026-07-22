use blake3::Hasher;
use phoenix_graph_rebuild::{GraphEvent, GraphRebuildSnapshot, GraphTemporalEdge};
use phoenix_types::GraphTruthDigest;

pub(super) fn canonical_extractor_digest(snapshot: &GraphRebuildSnapshot) -> GraphTruthDigest {
    let mut hasher = Hasher::new();
    update_str(&mut hasher, "phoenix.revision-impact-corpus-adapter/v1");
    let mut events = snapshot.events.iter().collect::<Vec<_>>();
    events.sort_unstable_by(|left, right| left.id.cmp(&right.id));
    for event in events {
        digest_event(&mut hasher, event);
    }
    digest_edges(&mut hasher, "temporal", &snapshot.temporal_edges);
    digest_edges(&mut hasher, "causal", &snapshot.causal_edges);
    GraphTruthDigest(*hasher.finalize().as_bytes())
}

fn digest_event(hasher: &mut Hasher, event: &GraphEvent) {
    update_str(hasher, "event");
    update_str(hasher, &event.id);
    update_str(hasher, event.chunk_id.as_deref().unwrap_or_default());
    update_str(hasher, &event.label);
    hasher.update(&event.confidence.to_bits().to_le_bytes());
    let mut entities = event.entity_ids.iter().collect::<Vec<_>>();
    entities.sort_unstable_by(|left, right| left.0.cmp(&right.0));
    for entity in entities {
        update_str(hasher, &entity.0);
    }
    let mut evidence = event.evidence_anchor_ids.iter().collect::<Vec<_>>();
    evidence.sort_unstable();
    for id in evidence {
        update_str(hasher, id);
    }
}

fn digest_edges(hasher: &mut Hasher, lane: &str, edges: &[GraphTemporalEdge]) {
    let mut ordered = edges.iter().collect::<Vec<_>>();
    ordered.sort_unstable_by(|left, right| left.id.cmp(&right.id));
    for edge in ordered {
        update_str(hasher, lane);
        update_str(hasher, &edge.id);
        update_str(hasher, &edge.source_id);
        update_str(hasher, &edge.target_id);
        update_str(hasher, &edge.relation_type);
        hasher.update(&edge.confidence.to_bits().to_le_bytes());
        let mut evidence = edge.evidence_ids.iter().collect::<Vec<_>>();
        evidence.sort_unstable();
        for id in evidence {
            update_str(hasher, id);
        }
    }
}

fn update_str(hasher: &mut Hasher, value: &str) {
    hasher.update(&(value.len() as u64).to_le_bytes());
    hasher.update(value.as_bytes());
}
