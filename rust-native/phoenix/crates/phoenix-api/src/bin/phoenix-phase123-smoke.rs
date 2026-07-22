use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use phoenix_alex::{Lexicon, SurfaceHit, SurfaceHitKind};
use phoenix_chunker_native::{
    build_lens_chunks, build_structural_substrate, ChunkerConfig, GraphBuildContext, GraphDelta,
    LensChunk, LensChunkConsumer, LensChunkHint, LensChunkHintKind, LensChunkHintSource,
    LensChunkInput, LensChunkerConfig, LensKind, LensMention, LensMentionEdge, LensMentionEdgeKind,
    LensMentionGraph, LensMentionKind, LensSurfaceHit, LensSurfaceHitKind, LensVoteReason,
    StructuralSubstrate,
};
use phoenix_dynamic_ner::{
    ChunkHint, ChunkHintKind, ChunkHintSource, MentionEdgeKind, MentionKind, MentionPacket,
    PhoenixNerEngineBuilder, SurfaceNerInput, VoteReason,
};
use phoenix_types::{
    EntityId, EntityKind, GenderHint, LexiconEntry, PosTag, ScopeKey, SentenceSpan, TextRange,
    TokenClass, TokenSpan,
};
use serde::Serialize;

#[derive(Clone, Debug)]
struct Config {
    input_path: PathBuf,
    json: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct Phase123SmokeReport {
    input_path: String,
    text_bytes: usize,
    phase1: Phase1Report,
    phase2: Phase2Report,
    phase3: Phase3Report,
    phase6: Phase6Report,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct Phase1Report {
    base_chunks: usize,
    sentences: usize,
    paragraphs: usize,
    chapters: usize,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct Phase2Report {
    mentions: usize,
    chunk_hints: usize,
    hint_counts: BTreeMap<String, usize>,
    graph_edges: usize,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct Phase3Report {
    lens_chunks: usize,
    lens_counts: BTreeMap<String, usize>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct Phase6Report {
    consumers: usize,
    graph_deltas: Vec<GraphDelta>,
}

fn main() {
    let config = parse_args(std::env::args().skip(1).collect());
    let json = config.json;
    match run(config) {
        Ok(report) => {
            if report.phase3.lens_chunks == 0 {
                eprintln!("phase 3 emitted no lens chunks");
                std::process::exit(1);
            }
            if report.phase3.lens_counts.values().any(|count| *count == 0) {
                eprintln!("phase 3 did not emit all required lens kinds");
                std::process::exit(1);
            }
            if report.phase2.chunk_hints == 0 {
                eprintln!("phase 2 emitted no chunk hints");
                std::process::exit(1);
            }
            if report
                .phase6
                .graph_deltas
                .iter()
                .any(|delta| delta.consumed_chunk_count == 0)
            {
                eprintln!("phase 6 had a graph consumer with no lens chunks");
                std::process::exit(1);
            }

            if json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&report).expect("serialize smoke report")
                );
            } else {
                println!("phase123 smoke passed: {}", report.input_path);
                println!(
                    "phase1 base={} sentences={} paragraphs={} chapters={}",
                    report.phase1.base_chunks,
                    report.phase1.sentences,
                    report.phase1.paragraphs,
                    report.phase1.chapters
                );
                println!(
                    "phase2 mentions={} hints={} graphEdges={}",
                    report.phase2.mentions, report.phase2.chunk_hints, report.phase2.graph_edges
                );
                println!("phase3 lensCounts={:?}", report.phase3.lens_counts);
                println!("phase6 consumers={}", report.phase6.consumers);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(1);
        }
    }
}

fn run(config: Config) -> Result<Phase123SmokeReport, String> {
    let text = fs::read_to_string(&config.input_path)
        .map_err(|error| format!("failed to read {}: {error}", config.input_path.display()))?;
    if text.trim().is_empty() {
        return Err("input text is empty".to_owned());
    }

    let substrate = build_structural_substrate(&text, &ChunkerConfig::default());
    validate_phase1(&text, &substrate)?;

    let (tokens, sentences) = tokenize_for_ner(&text);
    let lexicon = shortrun_lexicon()?;
    let scope = ScopeKey::default();
    let surface_hit_batch = lexicon.scan_surface_hits(&text, &scope);
    let engine = PhoenixNerEngineBuilder::new().build();
    let ner_output = engine
        .extract_mentions(&SurfaceNerInput {
            document_id: "shortrun-smoke",
            text: &text,
            tokens: &tokens,
            sentences: &sentences,
            scope: &scope,
            lexicon: Some(&lexicon),
            surface_hits: &surface_hit_batch.hits,
            label_bank_context: None,
        })
        .map_err(|error| format!("dynamic NER failed: {error}"))?;
    validate_phase2(&ner_output.mentions, &ner_output.chunk_hints)?;

    let active_mentions = ner_output
        .mentions
        .iter()
        .filter(|mention| mention.is_exportable())
        .collect::<Vec<_>>();
    let active_mention_ids = active_mentions
        .iter()
        .map(|mention| mention.mention_id.0)
        .collect::<BTreeSet<_>>();
    let lens_mentions = active_mentions
        .iter()
        .copied()
        .map(to_lens_mention)
        .collect::<Vec<_>>();
    let lens_hints = ner_output
        .chunk_hints
        .iter()
        .filter(|hint| hint_mentions_overlap_active(hint, &active_mention_ids))
        .map(to_lens_hint)
        .collect::<Vec<_>>();
    let lens_graph = to_lens_graph(&ner_output.mention_graph, &active_mention_ids);
    let lens_surface_hits = to_lens_surface_hits(&surface_hit_batch.hits);
    let lens_chunks = build_lens_chunks(
        &LensChunkInput {
            text: &text,
            base_chunks: &substrate.base_chunks,
            mentions: &lens_mentions,
            ner_hints: &lens_hints,
            mention_graph: &lens_graph,
            surface_hits: &lens_surface_hits,
        },
        &LensChunkerConfig::default(),
    );
    validate_phase3(&text, &lens_chunks)?;
    let graph_deltas = run_phase6_consumers(&lens_chunks);
    validate_phase6(&graph_deltas)?;

    Ok(Phase123SmokeReport {
        input_path: config.input_path.display().to_string(),
        text_bytes: text.len(),
        phase1: Phase1Report {
            base_chunks: substrate.base_chunks.len(),
            sentences: substrate.sentences.len(),
            paragraphs: substrate.paragraphs.len(),
            chapters: substrate.chapters.len(),
        },
        phase2: Phase2Report {
            mentions: ner_output.mentions.len(),
            chunk_hints: ner_output.chunk_hints.len(),
            hint_counts: hint_counts(&ner_output.chunk_hints),
            graph_edges: ner_output.mention_graph.edge_count(),
        },
        phase3: Phase3Report {
            lens_chunks: lens_chunks.len(),
            lens_counts: lens_counts(&lens_chunks),
        },
        phase6: Phase6Report {
            consumers: graph_deltas.len(),
            graph_deltas,
        },
    })
}

fn validate_phase1(text: &str, substrate: &StructuralSubstrate) -> Result<(), String> {
    if substrate.base_chunks.is_empty() {
        return Err("phase 1 emitted no base chunks".to_owned());
    }
    if substrate.sentences.is_empty()
        || substrate.paragraphs.is_empty()
        || substrate.chapters.is_empty()
    {
        return Err("phase 1 emitted incomplete sentence/paragraph/chapter hierarchy".to_owned());
    }
    for chunk in &substrate.base_chunks {
        validate_range(text, chunk.start, chunk.end, "base chunk")?;
    }
    for sentence in &substrate.sentences {
        validate_range(text, sentence.start, sentence.end, "sentence")?;
    }
    for paragraph in &substrate.paragraphs {
        validate_range(text, paragraph.start, paragraph.end, "paragraph")?;
    }
    for chapter in &substrate.chapters {
        validate_range(text, chapter.start, chapter.end, "chapter")?;
    }
    Ok(())
}

fn validate_phase2(mentions: &[MentionPacket], hints: &[ChunkHint]) -> Result<(), String> {
    if mentions.is_empty() {
        return Err("phase 2 emitted no mentions".to_owned());
    }
    if hints.is_empty() {
        return Err("phase 2 emitted no chunk hints".to_owned());
    }
    Ok(())
}

fn validate_phase3(text: &str, lens_chunks: &[LensChunk]) -> Result<(), String> {
    if lens_chunks.is_empty() {
        return Err("phase 3 emitted no lens chunks".to_owned());
    }
    let counts = lens_counts(lens_chunks);
    for lens in [
        "entity",
        "relationship",
        "event",
        "temporal",
        "causal",
        "attribute",
        "worldbuilding",
        "evidence",
    ] {
        if counts.get(lens).copied().unwrap_or_default() == 0 {
            return Err(format!("phase 3 emitted no {lens} lens chunks"));
        }
    }
    for chunk in lens_chunks {
        validate_range(text, chunk.start, chunk.end, "lens chunk")?;
    }
    Ok(())
}

fn validate_phase6(graph_deltas: &[GraphDelta]) -> Result<(), String> {
    if graph_deltas.len() < 8 {
        return Err(format!(
            "phase 6 expected at least 8 graph consumers, got {}",
            graph_deltas.len()
        ));
    }
    for delta in graph_deltas {
        if delta.consumed_chunk_count == 0 {
            return Err(format!(
                "phase 6 consumer {} consumed no chunks",
                delta.consumer
            ));
        }
    }
    Ok(())
}

fn run_phase6_consumers(lens_chunks: &[LensChunk]) -> Vec<GraphDelta> {
    let context = GraphBuildContext {
        graph_name: "shortrun-smoke".to_owned(),
        document_id: Some("docs/shortrun.md".to_owned()),
        scope_key: Some("default".to_owned()),
        created_at: Some(1_700_000_000_000),
    };
    vec![
        phoenix_er_post::EntityLensChunkConsumer.consume(lens_chunks, context.clone()),
        phoenix_rel_post::RelationshipLensChunkConsumer.consume(lens_chunks, context.clone()),
        phoenix_event_identity_post::EventLensChunkConsumer.consume(lens_chunks, context.clone()),
        phoenix_temporal_post::TemporalLensChunkConsumer.consume(lens_chunks, context.clone()),
        phoenix_causal_post::CausalLensChunkConsumer.consume(lens_chunks, context.clone()),
        phoenix_state_schema_post::AttributeLensChunkConsumer.consume(lens_chunks, context.clone()),
        phoenix_memory_post::WorldbuildingLensChunkConsumer.consume(lens_chunks, context.clone()),
        phoenix_evidence_graph::EvidenceLensChunkConsumer.consume(lens_chunks, context.clone()),
        phoenix_graph_post::WorldProjectionLensChunkConsumer.consume(lens_chunks, context.clone()),
        phoenix_graph_post::EvidenceProjectionLensChunkConsumer.consume(lens_chunks, context),
    ]
}

fn validate_range(text: &str, start: usize, end: usize, label: &str) -> Result<(), String> {
    if start >= end
        || end > text.len()
        || !text.is_char_boundary(start)
        || !text.is_char_boundary(end)
    {
        return Err(format!("invalid {label} range {start}..{end}"));
    }
    Ok(())
}

fn to_lens_mention(mention: &MentionPacket) -> LensMention {
    LensMention {
        mention_id: mention.mention_id.0,
        range: mention.range,
        sentence_index: mention.sentence_index,
        surface: mention.surface.to_string(),
        normalized: mention.normalized.to_string(),
        mention_kind: match mention.mention_kind {
            MentionKind::Named => LensMentionKind::Named,
            MentionKind::Nominal => LensMentionKind::Nominal,
            MentionKind::Pronoun => LensMentionKind::Pronoun,
        },
        vote_reasons: mention
            .source_votes
            .iter()
            .map(|vote| match vote.reason {
                VoteReason::ExactCanonical => LensVoteReason::ExactCanonical,
                VoteReason::ExactAlias => LensVoteReason::ExactAlias,
                VoteReason::AutoAlias => LensVoteReason::AutoAlias,
                VoteReason::FuzzyAnchor => LensVoteReason::FuzzyAnchor,
                VoteReason::TitlePattern => LensVoteReason::TitlePattern,
                VoteReason::CapSpan => LensVoteReason::CapSpan,
                VoteReason::NominalRole => LensVoteReason::NominalRole,
                VoteReason::DependencyRole => LensVoteReason::DependencyRole,
                VoteReason::DialogueSpeaker => LensVoteReason::DialogueSpeaker,
                VoteReason::ModelSpan => LensVoteReason::ModelSpan,
                VoteReason::ModelLabel => LensVoteReason::ModelLabel,
                _ => LensVoteReason::Other,
            })
            .collect(),
    }
}

fn hint_mentions_overlap_active(hint: &ChunkHint, active_mention_ids: &BTreeSet<u64>) -> bool {
    hint.mention_ids
        .iter()
        .any(|mention_id| active_mention_ids.contains(mention_id))
}

fn to_lens_hint(hint: &ChunkHint) -> LensChunkHint {
    LensChunkHint {
        id: hint.id.to_string(),
        kind: match hint.kind {
            ChunkHintKind::EntityDenseRegion => LensChunkHintKind::EntityDenseRegion,
            ChunkHintKind::EntityPair => LensChunkHintKind::EntityPair,
            ChunkHintKind::NamedEventCandidate => LensChunkHintKind::NamedEventCandidate,
            ChunkHintKind::RoleTitleAppositive => LensChunkHintKind::RoleTitleAppositive,
            ChunkHintKind::AliasIdentity => LensChunkHintKind::AliasIdentity,
            ChunkHintKind::DialogueSpeaker => LensChunkHintKind::DialogueSpeaker,
            ChunkHintKind::Relationship => LensChunkHintKind::Relationship,
            ChunkHintKind::Adjudication => LensChunkHintKind::Adjudication,
        },
        source: match hint.source {
            ChunkHintSource::SurfaceRouter => LensChunkHintSource::SurfaceRouter,
            ChunkHintSource::MentionWorkspace => LensChunkHintSource::MentionWorkspace,
            ChunkHintSource::MentionGraph => LensChunkHintSource::MentionGraph,
            ChunkHintSource::NativeDiscovery => LensChunkHintSource::NativeDiscovery,
            ChunkHintSource::ModelDiscovery => LensChunkHintSource::ModelDiscovery,
        },
        range: hint.range,
        sentence_start: hint.sentence_start,
        sentence_end: hint.sentence_end,
        mention_ids: hint.mention_ids.clone(),
        surfaces: hint.surfaces.iter().map(ToString::to_string).collect(),
        score_millis: hint.score_millis,
    }
}

fn to_lens_graph(
    graph: &phoenix_dynamic_ner::MentionGraph,
    active_mention_ids: &BTreeSet<u64>,
) -> LensMentionGraph {
    LensMentionGraph {
        edges: graph
            .edges
            .iter()
            .filter(|edge| {
                active_mention_ids.contains(&edge.left.0)
                    && active_mention_ids.contains(&edge.right.0)
            })
            .map(|edge| LensMentionEdge {
                left: edge.left.0,
                right: edge.right.0,
                kind: match edge.kind {
                    MentionEdgeKind::SameNormalizedSurface => {
                        LensMentionEdgeKind::SameNormalizedSurface
                    }
                    MentionEdgeKind::KnownAliasMatch => LensMentionEdgeKind::KnownAliasMatch,
                    MentionEdgeKind::FuzzyAliasMatch => LensMentionEdgeKind::FuzzyAliasMatch,
                    MentionEdgeKind::Apposition => LensMentionEdgeKind::Apposition,
                    MentionEdgeKind::DependencyCoreArgument => {
                        LensMentionEdgeKind::DependencyCoreArgument
                    }
                    MentionEdgeKind::SpeakerContinuity => LensMentionEdgeKind::SpeakerContinuity,
                    MentionEdgeKind::PronounCandidate => LensMentionEdgeKind::PronounCandidate,
                    MentionEdgeKind::NearbyRepetition => LensMentionEdgeKind::NearbyRepetition,
                    MentionEdgeKind::ModelLabelCompatibility => {
                        LensMentionEdgeKind::ModelLabelCompatibility
                    }
                },
                weight: edge.weight,
            })
            .collect(),
    }
}

fn to_lens_surface_hits(hits: &[SurfaceHit]) -> Vec<LensSurfaceHit> {
    hits.iter()
        .map(|hit| LensSurfaceHit {
            id: format!(
                "surface-hit:{}:{}:{}-{}",
                hit.snapshot_id.0, hit.pattern_id.0, hit.source_range.start, hit.source_range.end
            ),
            kind: to_lens_surface_hit_kind(hit.kind),
            range: hit.source_range,
            surface: hit.surface.to_string(),
            normalized: hit.normalized.to_string(),
        })
        .collect()
}

fn to_lens_surface_hit_kind(kind: SurfaceHitKind) -> LensSurfaceHitKind {
    match kind {
        SurfaceHitKind::EntityAlias => LensSurfaceHitKind::EntityAlias,
        SurfaceHitKind::RelationCue => LensSurfaceHitKind::RelationCue,
        SurfaceHitKind::TemporalCue => LensSurfaceHitKind::TemporalCue,
        SurfaceHitKind::CausalCue => LensSurfaceHitKind::CausalCue,
        SurfaceHitKind::EvidenceCue => LensSurfaceHitKind::EvidenceCue,
        SurfaceHitKind::StructureCue => LensSurfaceHitKind::StructureCue,
        SurfaceHitKind::GuardCue => LensSurfaceHitKind::GuardCue,
    }
}

fn hint_counts(hints: &[ChunkHint]) -> BTreeMap<String, usize> {
    let mut counts = BTreeMap::new();
    for hint in hints {
        *counts.entry(format!("{:?}", hint.kind)).or_insert(0) += 1;
    }
    counts
}

fn lens_counts(chunks: &[LensChunk]) -> BTreeMap<String, usize> {
    let mut counts = BTreeMap::from([
        ("entity".to_owned(), 0usize),
        ("relationship".to_owned(), 0usize),
        ("event".to_owned(), 0usize),
        ("temporal".to_owned(), 0usize),
        ("causal".to_owned(), 0usize),
        ("attribute".to_owned(), 0usize),
        ("worldbuilding".to_owned(), 0usize),
        ("evidence".to_owned(), 0usize),
    ]);
    for chunk in chunks {
        let key = match chunk.lens {
            LensKind::Entity => "entity",
            LensKind::Relationship => "relationship",
            LensKind::Event => "event",
            LensKind::Temporal => "temporal",
            LensKind::Causal => "causal",
            LensKind::Attribute => "attribute",
            LensKind::Worldbuilding => "worldbuilding",
            LensKind::Evidence => "evidence",
        };
        *counts.entry(key.to_owned()).or_insert(0) += 1;
    }
    counts
}

fn tokenize_for_ner(text: &str) -> (Vec<TokenSpan>, Vec<SentenceSpan>) {
    let mut tokens = Vec::new();
    let mut start = None;
    for (idx, ch) in text.char_indices() {
        if ch.is_alphanumeric() || ch == '\'' || ch == '-' {
            start.get_or_insert(idx);
        } else if let Some(s) = start.take() {
            tokens.push(token_span(text, s, idx));
        }
    }
    if let Some(s) = start {
        tokens.push(token_span(text, s, text.len()));
    }

    let sentences = phoenix_chunker_native::api::sentence_ranges(text)
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

fn pronoun_pos(surface: &str) -> Option<PosTag> {
    matches!(
        surface.to_ascii_lowercase().as_str(),
        "he" | "him" | "his" | "she" | "her" | "hers" | "they" | "them" | "their"
    )
    .then_some(PosTag::Pronoun)
}

fn shortrun_lexicon() -> Result<Lexicon, String> {
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
    Lexicon::from_entries(&entries).map_err(|error| format!("failed to build lexicon: {error:?}"))
}

fn parse_args(args: Vec<String>) -> Config {
    let root = workspace_root();
    let mut config = Config {
        input_path: root.join("docs").join("shortrun.md"),
        json: false,
    };
    if let Some(path) = string_arg(&args, "--input") {
        config.input_path = PathBuf::from(path);
    }
    config.json = args.iter().any(|arg| arg == "--json");
    config
}

fn string_arg(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find_map(|window| (window[0] == flag).then(|| window[1].clone()))
}

fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(4)
        .expect("workspace root")
        .to_path_buf()
}
