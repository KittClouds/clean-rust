use std::io::{self, Read};
use std::time::Instant;

use phoenix_graph_rebuild::{
    assert_chunk_semantic_bridge_candidate_only, audit_chunk_semantic_bridge_quality_gate,
    build_chunk_semantic_bridge_candidates_from_snapshot, BridgeQualityGateAudit,
    ChunkSemanticBridgeCandidate, ChunkSemanticBridgeSnapshotDocument, GraphRebuildSnapshot,
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ChunkSemanticBridgeRequest {
    snapshot: GraphRebuildSnapshot,
    documents: Vec<DocumentInput>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DocumentInput {
    note_id: String,
    text: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ChunkSemanticBridgeTiming {
    bridge_build_micros: u128,
    total_micros: u128,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ChunkSemanticBridgeOutput {
    schema_version: &'static str,
    source: &'static str,
    candidates: Vec<ChunkSemanticBridgeCandidate>,
    quality_gate: BridgeQualityGateAudit,
    timing: ChunkSemanticBridgeTiming,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let mut input = String::new();
    io::stdin().read_to_string(&mut input)?;
    let request: ChunkSemanticBridgeRequest = serde_json::from_str(&input)?;
    let documents = request
        .documents
        .iter()
        .map(|document| ChunkSemanticBridgeSnapshotDocument {
            note_id: document.note_id.as_str(),
            text: document.text.as_str(),
        })
        .collect::<Vec<_>>();

    let bridge_started = Instant::now();
    let candidates =
        build_chunk_semantic_bridge_candidates_from_snapshot(&request.snapshot, &documents);
    assert_chunk_semantic_bridge_candidate_only(&candidates)?;
    let bridge_build_micros = bridge_started.elapsed().as_micros();
    let quality_gate = audit_chunk_semantic_bridge_quality_gate(&candidates);
    let output = ChunkSemanticBridgeOutput {
        schema_version: "phoenix-chunk-semantic-bridge-native-output/v1",
        source: "rust",
        candidates,
        quality_gate,
        timing: ChunkSemanticBridgeTiming {
            bridge_build_micros,
            total_micros: started.elapsed().as_micros(),
        },
    };
    println!("{}", serde_json::to_string(&output)?);
    Ok(())
}
