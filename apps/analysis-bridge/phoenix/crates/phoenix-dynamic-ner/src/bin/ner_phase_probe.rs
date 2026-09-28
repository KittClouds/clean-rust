use std::path::PathBuf;
use std::time::Instant;

use phoenix_alex::Lexicon;
use phoenix_dynamic_ner::{PhoenixNerEngineBuilder, SurfaceNerInput};
use phoenix_types::{
    EntityId, EntityKind, GenderHint, LexiconEntry, PosTag, ScopeKey, SentenceSpan, TextRange,
    TokenClass, TokenSpan,
};

fn main() {
    let input_path = input_path();
    let text = std::fs::read_to_string(&input_path)
        .unwrap_or_else(|error| panic!("failed to read {}: {error}", input_path.display()));
    let (tokens, sentences) = tokenize_for_ner(&text);
    let lexicon = fixture_lexicon();
    let scope = ScopeKey::default();
    let engine = PhoenixNerEngineBuilder::new().build();

    let started = Instant::now();
    let (output, metrics) = engine
        .extract_mentions_with_metrics(&SurfaceNerInput {
            document_id: input_path.to_string_lossy().as_ref(),
            text: &text,
            tokens: &tokens,
            sentences: &sentences,
            scope: &scope,
            lexicon: Some(&lexicon),
            surface_hits: &[],
            label_bank_context: None,
        })
        .expect("dynamic NER probe");
    let wall_ms = started.elapsed().as_millis();

    println!("ner phase probe: {}", input_path.display());
    println!(
        "wall={}ms total={}ms knownSurface={}ms nativeDiscovery={}ms routePlanning={}ms workspaceIngest={}ms modelAndAdjudication={}ms finalPackets={}ms surfaceMemory={}ms mentionGraph={}ms chunkHints={}ms",
        wall_ms,
        metrics.total_ms,
        metrics.known_surface_ms,
        metrics.native_discovery_ms,
        metrics.route_planning_ms,
        metrics.workspace_ingest_ms,
        metrics.model_and_adjudication_ms,
        metrics.final_packets_ms,
        metrics.surface_memory_ms,
        metrics.mention_graph_ms,
        metrics.chunk_hints_ms
    );
    println!(
        "tokens={} sentences={} known={} native={} routes={} packets={} exportable={} graphEdges={} chunkHints={} surfaceMemoryEntries={}",
        tokens.len(),
        sentences.len(),
        metrics.known_count,
        metrics.native_count,
        metrics.route_count,
        metrics.packet_count,
        output.mentions.iter().filter(|mention| mention.is_exportable()).count(),
        metrics.graph_edge_count,
        metrics.chunk_hint_count,
        output.surface_memory.entries.len()
    );
}

fn input_path() -> PathBuf {
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        if arg == "--input" {
            if let Some(path) = args.next() {
                return PathBuf::from(path);
            }
        }
    }
    PathBuf::from("..")
        .join("..")
        .join("docs")
        .join("shortrun.md")
}

fn tokenize_for_ner(text: &str) -> (Vec<TokenSpan>, Vec<SentenceSpan>) {
    let mut tokens = Vec::new();
    let mut start = None::<usize>;
    for (idx, ch) in text.char_indices() {
        if is_token_char(ch) {
            start.get_or_insert(idx);
            continue;
        }
        if let Some(token_start) = start.take() {
            tokens.push(token_span(text, token_start, idx));
        }
    }
    if let Some(token_start) = start {
        tokens.push(token_span(text, token_start, text.len()));
    }

    let sentences = phoenix_alex::split_sentence_ranges(text)
        .into_iter()
        .enumerate()
        .map(|(index, (start, end))| SentenceSpan {
            index,
            range: TextRange {
                start: start as u32,
                end: end as u32,
            },
        })
        .collect();
    (tokens, sentences)
}

fn token_span(text: &str, start: usize, end: usize) -> TokenSpan {
    let surface = &text[start..end];
    TokenSpan {
        range: TextRange {
            start: start as u32,
            end: end as u32,
        },
        capitalized: surface.starts_with(|ch: char| ch.is_uppercase()),
        pos: pronoun_pos(surface),
        token_class: Some(TokenClass::Word),
        masked: false,
    }
}

fn is_token_char(ch: char) -> bool {
    ch.is_alphanumeric() || matches!(ch, '\'' | '\u{2019}' | '-')
}

fn pronoun_pos(surface: &str) -> Option<PosTag> {
    matches!(
        surface.to_ascii_lowercase().as_str(),
        "he" | "him" | "his" | "she" | "her" | "hers" | "they" | "them" | "their"
    )
    .then_some(PosTag::Pronoun)
}

fn fixture_lexicon() -> Lexicon {
    let entries = [
        ("ryan", "Ryan", EntityKind::Character),
        ("quicksave", "Quicksave", EntityKind::Character),
        ("len", "Len", EntityKind::Character),
        ("ghoul", "Ghoul", EntityKind::Character),
        ("renesco", "Renesco", EntityKind::Character),
        ("wyvern", "Wyvern", EntityKind::Character),
        ("vulcan", "Vulcan", EntityKind::Character),
        ("zanbato", "Zanbato", EntityKind::Character),
        ("lanka", "Lanka", EntityKind::Character),
        ("jamie", "Jamie", EntityKind::Character),
        ("ki-jung", "Ki-jung", EntityKind::Character),
        ("new-rome", "New Rome", EntityKind::Location),
        ("dynamis", "Dynamis", EntityKind::Organization),
        ("bakuto", "Bakuto", EntityKind::Location),
    ]
    .into_iter()
    .map(|(entity_id, label, kind)| LexiconEntry {
        entity_id: EntityId(entity_id.to_owned()),
        label: label.to_owned(),
        aliases: Vec::new(),
        kind: Some(kind),
        gender: Some(GenderHint::Unknown),
        number: None,
        scope: ScopeKey::default(),
    })
    .collect::<Vec<_>>();
    Lexicon::from_entries(&entries).expect("fixture lexicon")
}
