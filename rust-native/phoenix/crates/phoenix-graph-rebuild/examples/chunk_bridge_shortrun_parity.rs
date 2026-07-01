use phoenix_graph_rebuild::build_chunk_semantic_bridge_shortrun_parity_report;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let report = build_chunk_semantic_bridge_shortrun_parity_report(
        include_str!("../../../../../docs/shortrun.md"),
        include_str!(
            "../../../../../src/app/graph-rebuild/fixtures/chunk-semantic-bridge-shortrun-golden.json"
        ),
    )?;
    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}
