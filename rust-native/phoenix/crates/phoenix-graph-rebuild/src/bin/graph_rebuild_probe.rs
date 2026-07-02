use std::{env, fs, process, time::Instant};

use phoenix_graph_rebuild::{build_graph_rebuild_snapshot, GraphRebuildInput, GraphScopeKind};
use phoenix_types::{EntityId, EntityKind, LexiconEntry, ScopeKey};

fn main() {
    let args = Args::parse(env::args().skip(1).collect());
    let text = args.text.unwrap_or_else(|| {
        eprintln!("graph_rebuild_probe requires --text or --text-file");
        process::exit(2);
    });
    let entities = if args.entities.is_empty() {
        sample_entities()
    } else {
        args.entities
    };
    let repeat = args.repeat.max(1);
    let scope_id = format!("note:{}", args.note_id);
    let started = Instant::now();
    let mut snapshot = None;
    let mut memory_governance_build_us = 0_u64;
    for _ in 0..repeat {
        let built = build_graph_rebuild_snapshot(GraphRebuildInput {
            scope_kind: GraphScopeKind::Note,
            scope_id: &scope_id,
            note_id: &args.note_id,
            text: &text,
            scope: ScopeKey::default(),
            entities: &entities,
            candidate_count: 0,
            built_at: Some(1),
        })
        .unwrap_or_else(|error| {
            eprintln!("graph rebuild failed: {error}");
            process::exit(1);
        });
        memory_governance_build_us = memory_governance_build_us
            .saturating_add(built.counters.memory_governance_build_micros);
        snapshot = Some(built);
    }
    let elapsed_us = started.elapsed().as_micros() as u64;
    let mean_us = elapsed_us / repeat as u64;
    let memory_governance_build_mean_us = memory_governance_build_us / repeat as u64;
    let snapshot = snapshot.expect("repeat always runs at least once");

    if args.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&snapshot).expect("snapshot json")
        );
        return;
    }

    println!("graph_rebuild_probe");
    println!("schema={}", snapshot.schema_version);
    println!("note_id={}", args.note_id);
    println!("repeat={repeat}");
    println!("elapsed_us={elapsed_us}");
    println!("mean_us={mean_us}");
    println!("chunks={}", snapshot.counters.chunks);
    println!("candidates={}", snapshot.counters.candidates);
    println!("mentions={}", snapshot.counters.mentions);
    println!("accepted_anchors={}", snapshot.counters.accepted_anchors);
    println!("anchor_evidence={}", snapshot.counters.anchor_evidence);
    println!("relation_signals={}", snapshot.counters.relation_signals);
    println!("promoted_facts={}", snapshot.counters.promoted_facts);
    println!(
        "relationship_candidates={}",
        snapshot.counters.relationship_candidates
    );
    println!("relationships={}", snapshot.counters.relationships);
    println!(
        "accepted_relationships={}",
        snapshot.counters.accepted_relationships
    );
    println!(
        "review_relationships={}",
        snapshot.counters.review_relationships
    );
    println!(
        "rejected_relationships={}",
        snapshot.counters.rejected_relationships
    );
    println!("events={}", snapshot.counters.events);
    println!("episodes={}", snapshot.counters.episodes);
    println!("temporal_edges={}", snapshot.counters.temporal_edges);
    println!("causal_edges={}", snapshot.counters.causal_edges);
    println!("memory_state={}", snapshot.counters.memory_state);
    println!(
        "memory_governance_build_us={}",
        snapshot.counters.memory_governance_build_micros
    );
    println!("memory_governance_build_elapsed_us={memory_governance_build_us}");
    println!("memory_governance_build_mean_us={memory_governance_build_mean_us}");
    println!(
        "memory_governance_candidates={}",
        snapshot.counters.memory_governance_candidates
    );
    println!(
        "memory_governance_retain={}",
        snapshot.counters.memory_governance_retain
    );
    println!(
        "memory_governance_attenuate={}",
        snapshot.counters.memory_governance_attenuate
    );
    println!(
        "memory_governance_compress={}",
        snapshot.counters.memory_governance_compress
    );
    println!("embedding_targets={}", snapshot.counters.embedding_targets);
    println!("nodes={}", snapshot.counters.nodes);
    println!("edges={}", snapshot.counters.edges);
    println!("persisted_rows=0");
    println!("frontend_payload_rows={}", frontend_payload_rows(&snapshot));
    println!(
        "drop_missing_entity={}",
        snapshot.counters.drop_reasons.missing_entity
    );
    println!(
        "drop_invalid_span={}",
        snapshot.counters.drop_reasons.invalid_span
    );
    println!(
        "drop_duplicate_anchor={}",
        snapshot.counters.drop_reasons.duplicate_anchor
    );
    println!(
        "drop_singleton_bucket={}",
        snapshot.counters.drop_reasons.singleton_bucket
    );
    println!(
        "drop_missing_chunk={}",
        snapshot.counters.drop_reasons.missing_chunk
    );
}

struct Args {
    note_id: String,
    text: Option<String>,
    entities: Vec<LexiconEntry>,
    repeat: usize,
    json: bool,
}

impl Args {
    fn parse(args: Vec<String>) -> Self {
        let mut parsed = Args {
            note_id: "probe-note".to_owned(),
            text: None,
            entities: Vec::new(),
            repeat: 1,
            json: false,
        };
        let mut index = 0;
        while index < args.len() {
            match args[index].as_str() {
                "--note-id" => {
                    index += 1;
                    parsed.note_id = args.get(index).cloned().unwrap_or(parsed.note_id);
                }
                "--text" => {
                    index += 1;
                    parsed.text = args.get(index).cloned();
                }
                "--text-file" => {
                    index += 1;
                    let path = args.get(index).cloned().unwrap_or_default();
                    parsed.text = Some(fs::read_to_string(&path).unwrap_or_else(|error| {
                        eprintln!("failed to read {path}: {error}");
                        process::exit(2);
                    }));
                }
                "--entity" => {
                    index += 1;
                    if let Some(raw) = args.get(index) {
                        parsed.entities.push(parse_entity(raw));
                    }
                }
                "--repeat" => {
                    index += 1;
                    parsed.repeat = args
                        .get(index)
                        .and_then(|raw| raw.parse::<usize>().ok())
                        .unwrap_or(parsed.repeat);
                }
                "--json" => parsed.json = true,
                "--help" | "-h" => print_help_and_exit(),
                other => {
                    eprintln!("unknown argument: {other}");
                    print_help_and_exit();
                }
            }
            index += 1;
        }
        parsed
    }
}

fn parse_entity(raw: &str) -> LexiconEntry {
    let mut parts = raw.split('|');
    let id = parts.next().unwrap_or("entity").trim();
    let label = parts.next().unwrap_or(id).trim();
    let kind = parts.next().unwrap_or("character").trim();
    let aliases = parts
        .next()
        .unwrap_or_default()
        .split(',')
        .map(str::trim)
        .filter(|alias| !alias.is_empty())
        .map(str::to_owned)
        .collect();
    LexiconEntry {
        entity_id: EntityId(id.to_owned()),
        label: label.to_owned(),
        aliases,
        kind: Some(parse_kind(kind)),
        scope: ScopeKey::default(),
        ..LexiconEntry::default()
    }
}

fn parse_kind(kind: &str) -> EntityKind {
    match kind.to_ascii_lowercase().as_str() {
        "location" => EntityKind::Location,
        "item" => EntityKind::Item,
        "faction" => EntityKind::Faction,
        "organization" => EntityKind::Organization,
        "event" => EntityKind::Event,
        "concept" => EntityKind::Concept,
        "npc" => EntityKind::Npc,
        _ => EntityKind::Character,
    }
}

fn sample_entities() -> Vec<LexiconEntry> {
    vec![
        parse_entity("e-kai|Kai|character|Captain Kai"),
        parse_entity("e-hazel|Hazel|character|"),
        parse_entity("e-rift|Rift|character|"),
    ]
}

fn frontend_payload_rows(snapshot: &phoenix_graph_rebuild::GraphRebuildSnapshot) -> usize {
    snapshot.chunks.len()
        + snapshot.mentions.len()
        + snapshot.entity_anchors.len()
        + snapshot.relationships.len()
        + snapshot.embedding_targets.len()
        + snapshot.nodes.len()
        + snapshot.edges.len()
}

fn print_help_and_exit() -> ! {
    println!("Usage: graph_rebuild_probe --text-file note.txt [--entity id|label|kind|alias1,alias2] [--repeat N] [--json]");
    process::exit(0);
}
