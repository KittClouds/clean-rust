use phoenix_graph_rebuild::{build_graph_rebuild_snapshot, GraphRebuildInput, GraphScopeKind};
use phoenix_types::{EntityId, EntityKind, LexiconEntry, ScopeKey};
use serde::Deserialize;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct LiveEntity {
    id: String,
    label: String,
    kind: String,
    #[serde(default)]
    aliases: Vec<String>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    let markdown_path = PathBuf::from(args.next().ok_or("missing Markdown path")?);
    let entities_path = PathBuf::from(args.next().ok_or("missing entity registry path")?);
    let output_path = PathBuf::from(args.next().ok_or("missing snapshot output path")?);
    if args.next().is_some() {
        return Err("unexpected extra argument".into());
    }
    let markdown = fs::read_to_string(markdown_path)?;
    let entities = serde_json::from_slice::<Vec<LiveEntity>>(&fs::read(entities_path)?)?
        .into_iter()
        .map(|entity| LexiconEntry {
            entity_id: EntityId(entity.id),
            label: entity.label,
            aliases: entity.aliases,
            kind: map_kind(&entity.kind),
            gender: None,
            number: None,
            scope: ScopeKey::default(),
        })
        .collect::<Vec<_>>();
    let started = Instant::now();
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Global,
        scope_id: "global",
        note_id: "05dbbd93-e0f7-4fb2-937e-92a2352dcbae",
        text: &markdown,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 0,
        built_at: Some(1_784_769_182_797),
    })?;
    fs::write(&output_path, serde_json::to_vec(&snapshot)?)?;
    println!(
        "rebuilt entities={} nodes={} edges={} targets={} chunks={} anchors={} elapsed_ms={} output={}",
        entities.len(),
        snapshot.nodes.len(),
        snapshot.edges.len(),
        snapshot.embedding_targets.len(),
        snapshot.chunks.len(),
        snapshot.entity_anchors.len(),
        started.elapsed().as_millis(),
        output_path.display()
    );
    Ok(())
}

fn map_kind(kind: &str) -> Option<EntityKind> {
    match kind {
        "CHARACTER" => Some(EntityKind::Character),
        "LOCATION" => Some(EntityKind::Location),
        "NPC" => Some(EntityKind::Npc),
        "ITEM" => Some(EntityKind::Item),
        "FACTION" => Some(EntityKind::Faction),
        "NETWORK" | "ORGANIZATION" => Some(EntityKind::Organization),
        "EVENT" => Some(EntityKind::Event),
        "CONCEPT" => Some(EntityKind::Concept),
        _ => Some(EntityKind::Other),
    }
}
