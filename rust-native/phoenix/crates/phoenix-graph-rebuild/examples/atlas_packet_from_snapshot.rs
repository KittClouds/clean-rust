use std::io::{self, Read};

use phoenix_graph_rebuild::{
    build_atlas_packet, build_snapshot_embedding_targets, compile_legacy_snapshot,
    project_ui_edges, GraphRebuildSnapshot,
};
use serde_json::{json, Value};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input)?;
    let value: Value = serde_json::from_str(&input)?;
    let snapshot_value = value.get("snapshot").cloned().unwrap_or(value);
    let snapshot: GraphRebuildSnapshot = serde_json::from_value(snapshot_value)?;
    let fact_graph = compile_legacy_snapshot(&snapshot);
    let embedding_targets = build_snapshot_embedding_targets(&snapshot);
    let mut atlas_snapshot = snapshot.clone();
    atlas_snapshot.embedding_targets = embedding_targets.clone();
    let atlas_packet = build_atlas_packet(&atlas_snapshot);
    let output = json!({
        "factGraph": fact_graph,
        "projectedUiGraph": project_ui_edges(&fact_graph),
        "receipts": fact_graph.receipts,
        "atlasPacket": atlas_packet,
        "embeddingTargetSource": "rust-graph-family-targets/v1",
        "embeddingTargets": embedding_targets,
    });
    println!("{}", serde_json::to_string(&output)?);
    Ok(())
}
