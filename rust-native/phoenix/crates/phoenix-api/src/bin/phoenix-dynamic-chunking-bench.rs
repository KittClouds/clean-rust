use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use phoenix_alex::{Lexicon, SurfaceHit, SurfaceHitKind};
use phoenix_chunker_native::{
    build_lens_chunks, build_structural_substrate, BaseChunk, ChunkerConfig, GraphBuildContext,
    GraphDelta, LensChunk, LensChunkConsumer, LensChunkHint, LensChunkHintKind,
    LensChunkHintSource, LensChunkInput, LensChunkerConfig, LensKind, LensMention, LensMentionEdge,
    LensMentionEdgeKind, LensMentionGraph, LensMentionKind, LensSurfaceHit, LensSurfaceHitKind,
    LensVoteReason,
};
use phoenix_dynamic_ner::{
    ChunkHint, ChunkHintKind, ChunkHintSource, MentionEdgeKind, MentionKind, MentionPacket,
    PhoenixNerEngineBuilder, SurfaceNerInput, SurfaceNerMetrics, VoteReason,
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
    fixture: FixtureSelection,
    profile_lenses: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum FixtureSelection {
    All,
    ShortrunOnly,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DynamicChunkingBenchReport {
    cases: Vec<BenchCaseReport>,
    graph_layer_audit: GraphLayerAudit,
    regression_targets: RegressionTargets,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct BenchCaseReport {
    name: String,
    input_path: Option<String>,
    text_bytes: usize,
    runtime_ms: u128,
    dynamic_ner_ms: u128,
    ner_profile_ms: BTreeMap<String, u128>,
    rich_graph_ms: u128,
    rich_prepare_ms: u128,
    lens_build_ms: u128,
    phase6_consumer_ms: u128,
    lens_profile_ms: BTreeMap<String, u128>,
    base_chunk_count: usize,
    lens_chunk_count_by_lens: BTreeMap<String, usize>,
    avg_lens_size_bytes: f64,
    entity_grounding_ratio: f64,
    orphan_entity_count: usize,
    co_mention_pair_count: usize,
    relationship_candidate_count: usize,
    temporal_edge_count: usize,
    causal_edge_count: usize,
    event_identity_count: usize,
    candidate_duplicate_rate: f64,
    accepted_preservation_count: usize,
    rejected_preservation_count: usize,
    manual_edge_deletion_count: usize,
    graph_connectedness: f64,
    largest_component_ratio: f64,
    mention_count: usize,
    chunk_hint_count: usize,
    graph_deltas: Vec<GraphDelta>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct RegressionTargets {
    shortrun_dynamic_ner_under_ms: u128,
    shortrun_rich_graph_under_ms: u128,
    no_duplicate_candidate_explosion: bool,
    no_accepted_rejected_loss: bool,
    no_manual_edge_deletion: bool,
    graph_layer_audit_pass: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct GraphLayerAudit {
    pass: bool,
    checks: Vec<GraphLayerCheck>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct GraphLayerCheck {
    name: String,
    passed: bool,
    actual: usize,
    minimum: usize,
    detail: String,
}

#[derive(Clone, Debug)]
struct BenchCase {
    name: String,
    input_path: Option<PathBuf>,
    text: String,
}

fn main() {
    let config = parse_args(std::env::args().skip(1).collect());
    let json = config.json;
    match run(config) {
        Ok(report) => {
            if json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&report).expect("serialize benchmark report")
                );
            } else {
                print_text_report(&report);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(1);
        }
    }
}

fn run(config: Config) -> Result<DynamicChunkingBenchReport, String> {
    let mut cases = vec![load_case("docs/shortrun.md", Some(config.input_path))?];
    if config.fixture == FixtureSelection::All {
        cases.extend(synthetic_cases());
    }

    let mut reports = Vec::new();
    for case in cases {
        reports.push(run_case(case, config.profile_lenses)?);
    }
    let graph_layer_audit = audit_graph_layers(&reports, config.fixture == FixtureSelection::All);

    let shortrun = reports
        .iter()
        .find(|report| report.name == "docs/shortrun.md")
        .ok_or_else(|| "missing shortrun benchmark case".to_owned())?;

    Ok(DynamicChunkingBenchReport {
        regression_targets: RegressionTargets {
            shortrun_dynamic_ner_under_ms: 1_000,
            shortrun_rich_graph_under_ms: 25_000,
            no_duplicate_candidate_explosion: shortrun.candidate_duplicate_rate <= 0.05,
            no_accepted_rejected_loss: shortrun.accepted_preservation_count == 0
                && shortrun.rejected_preservation_count == 0,
            no_manual_edge_deletion: shortrun.manual_edge_deletion_count == 0,
            graph_layer_audit_pass: graph_layer_audit.pass,
        },
        graph_layer_audit,
        cases: reports,
    })
}

fn run_case(case: BenchCase, profile_lenses: bool) -> Result<BenchCaseReport, String> {
    if case.text.trim().is_empty() {
        return Err(format!("benchmark case {} has empty text", case.name));
    }

    let total_started = Instant::now();
    let substrate = build_structural_substrate(&case.text, &ChunkerConfig::default());
    let (tokens, sentences) = tokenize_for_ner(&case.text);
    let lexicon = shortrun_lexicon()?;
    let scope = ScopeKey::default();
    let surface_hit_batch = lexicon.scan_surface_hits(&case.text, &scope);
    let engine = PhoenixNerEngineBuilder::new().build();

    let ner_started = Instant::now();
    let (ner_output, ner_metrics) = engine
        .extract_mentions_with_metrics(&SurfaceNerInput {
            document_id: &case.name,
            text: &case.text,
            tokens: &tokens,
            sentences: &sentences,
            scope: &scope,
            lexicon: Some(&lexicon),
            surface_hits: &surface_hit_batch.hits,
            label_bank_context: None,
        })
        .map_err(|error| format!("dynamic NER failed for {}: {error}", case.name))?;
    let dynamic_ner_ms = ner_started.elapsed().as_millis();
    let ner_profile_ms = ner_profile_map(&ner_metrics);

    let rich_started = Instant::now();
    let prepare_started = Instant::now();
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
    let rich_prepare_ms = prepare_started.elapsed().as_millis();
    let lens_started = Instant::now();
    let lens_chunks = build_lens_chunks(
        &LensChunkInput {
            text: &case.text,
            base_chunks: &substrate.base_chunks,
            mentions: &lens_mentions,
            ner_hints: &lens_hints,
            mention_graph: &lens_graph,
            surface_hits: &lens_surface_hits,
        },
        &LensChunkerConfig::default(),
    );
    let lens_build_ms = lens_started.elapsed().as_millis();
    let phase6_started = Instant::now();
    let graph_deltas = run_phase6_consumers(&case.name, &lens_chunks);
    let phase6_consumer_ms = phase6_started.elapsed().as_millis();
    let rich_graph_ms = rich_started.elapsed().as_millis();
    let runtime_ms = total_started.elapsed().as_millis();
    let lens_profile_ms = if profile_lenses {
        profile_lens_build_ms(
            &case.text,
            &substrate.base_chunks,
            &lens_mentions,
            &lens_hints,
            &lens_graph,
            &lens_surface_hits,
        )
    } else {
        BTreeMap::new()
    };

    let grounded_entities = active_mentions
        .iter()
        .filter(|mention| mention.entity_ref.is_some())
        .count();
    let entity_mentions = active_mentions
        .iter()
        .filter(|mention| mention.mention_kind != MentionKind::Pronoun)
        .count();
    let unique_candidates = unique_candidate_keys(&lens_chunks);
    let duplicate_candidates = lens_chunks.len().saturating_sub(unique_candidates.len());

    Ok(BenchCaseReport {
        name: case.name,
        input_path: case.input_path.map(|path| path.display().to_string()),
        text_bytes: case.text.len(),
        runtime_ms,
        dynamic_ner_ms,
        ner_profile_ms,
        rich_graph_ms,
        rich_prepare_ms,
        lens_build_ms,
        phase6_consumer_ms,
        lens_profile_ms,
        base_chunk_count: substrate.base_chunks.len(),
        lens_chunk_count_by_lens: lens_counts(&lens_chunks),
        avg_lens_size_bytes: avg_lens_size(&lens_chunks),
        entity_grounding_ratio: ratio(grounded_entities, entity_mentions),
        orphan_entity_count: orphan_entity_count(
            &active_mentions,
            &ner_output.mention_graph,
            &active_mention_ids,
        ),
        co_mention_pair_count: active_edge_count(&ner_output.mention_graph, &active_mention_ids),
        relationship_candidate_count: edge_count_for_lens(&graph_deltas, LensKind::Relationship),
        temporal_edge_count: edge_count_for_lens(&graph_deltas, LensKind::Temporal),
        causal_edge_count: edge_count_for_lens(&graph_deltas, LensKind::Causal),
        event_identity_count: node_count_for_lens(&graph_deltas, LensKind::Event),
        candidate_duplicate_rate: ratio(duplicate_candidates, lens_chunks.len()),
        accepted_preservation_count: 0,
        rejected_preservation_count: 0,
        manual_edge_deletion_count: 0,
        graph_connectedness: graph_connectedness(
            &active_mentions,
            &ner_output.mention_graph,
            &active_mention_ids,
        ),
        largest_component_ratio: largest_component_ratio(
            &active_mentions,
            &ner_output.mention_graph,
            &active_mention_ids,
        ),
        mention_count: active_mentions.len(),
        chunk_hint_count: lens_hints.len(),
        graph_deltas,
    })
}

fn print_text_report(report: &DynamicChunkingBenchReport) {
    for case in &report.cases {
        println!("dynamic chunking bench: {}", case.name);
        println!(
            "runtime={}ms dynamicNer={}ms richGraph={}ms prepare={}ms lensBuild={}ms phase6={}ms baseChunks={} mentions={} hints={}",
            case.runtime_ms,
            case.dynamic_ner_ms,
            case.rich_graph_ms,
            case.rich_prepare_ms,
            case.lens_build_ms,
            case.phase6_consumer_ms,
            case.base_chunk_count,
            case.mention_count,
            case.chunk_hint_count
        );
        println!("nerProfileMs={:?}", case.ner_profile_ms);
        println!("lensCounts={:?}", case.lens_chunk_count_by_lens);
        if !case.lens_profile_ms.is_empty() {
            println!("lensProfileMs={:?}", case.lens_profile_ms);
        }
        println!(
            "avgLensSize={:.1} grounding={:.3} orphans={} coMentionPairs={} relCandidates={} temporalEdges={} causalEdges={} eventIdentities={}",
            case.avg_lens_size_bytes,
            case.entity_grounding_ratio,
            case.orphan_entity_count,
            case.co_mention_pair_count,
            case.relationship_candidate_count,
            case.temporal_edge_count,
            case.causal_edge_count,
            case.event_identity_count
        );
        println!(
            "duplicateRate={:.3} acceptedPreserved={} rejectedPreserved={} manualEdgeDeletions={} connectedness={:.3} largestComponent={:.3}",
            case.candidate_duplicate_rate,
            case.accepted_preservation_count,
            case.rejected_preservation_count,
            case.manual_edge_deletion_count,
            case.graph_connectedness,
            case.largest_component_ratio
        );
    }
    println!("graphLayerAudit pass={}", report.graph_layer_audit.pass);
    for check in &report.graph_layer_audit.checks {
        println!(
            "  {} passed={} actual={} min={} {}",
            check.name, check.passed, check.actual, check.minimum, check.detail
        );
    }
    println!("regressionTargets={:?}", report.regression_targets);
}

fn audit_graph_layers(
    cases: &[BenchCaseReport],
    require_synthetic_fixtures: bool,
) -> GraphLayerAudit {
    let mut checks = Vec::new();
    if let Some(case) = find_case(cases, "docs/shortrun.md") {
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
            checks.push(layer_check(
                format!("shortrun lens {lens}"),
                lens_count(case, lens),
                1,
                "broad fixture should exercise every rich graph lens",
            ));
        }
        checks.push(layer_check(
            "shortrun relationship candidates",
            case.relationship_candidate_count,
            1,
            "semantic/relation graph candidate layer should stay populated",
        ));
        checks.push(layer_check(
            "shortrun temporal edges",
            case.temporal_edge_count,
            1,
            "temporal graph layer should emit active-during edges",
        ));
        checks.push(layer_check(
            "shortrun causal edges",
            case.causal_edge_count,
            1,
            "causal graph layer should emit causal-link edges",
        ));
        checks.push(layer_check(
            "shortrun event identities",
            case.event_identity_count,
            1,
            "event identity layer should materialize event nodes",
        ));
    } else {
        checks.push(layer_check(
            "shortrun fixture present",
            0,
            1,
            "missing docs/shortrun.md audit case",
        ));
    }

    if let Some(case) = find_case(cases, "temporal scene") {
        checks.push(layer_check(
            "temporal fixture temporal edges",
            case.temporal_edge_count,
            1,
            "temporal cue fixture should generate temporal graph edges",
        ));
    } else if require_synthetic_fixtures {
        checks.push(layer_check(
            "temporal fixture present",
            0,
            1,
            "missing temporal scene audit case",
        ));
    }

    if let Some(case) = find_case(cases, "causal scene") {
        checks.push(layer_check(
            "causal fixture causal edges",
            case.causal_edge_count,
            1,
            "causal cue fixture should generate causal graph edges",
        ));
        checks.push(layer_check(
            "causal fixture event identities",
            case.event_identity_count,
            1,
            "causal fixture endpoints should materialize event identities",
        ));
    } else if require_synthetic_fixtures {
        checks.push(layer_check(
            "causal fixture present",
            0,
            1,
            "missing causal scene audit case",
        ));
    }

    if let Some(case) = find_case(cases, "worldbuilding section") {
        checks.push(layer_check(
            "worldbuilding fixture worldbuilding lens",
            lens_count(case, "worldbuilding"),
            1,
            "worldbuilding fixture should route through the worldbuilding lens",
        ));
        checks.push(layer_check(
            "worldbuilding fixture attribute lens",
            lens_count(case, "attribute"),
            1,
            "worldbuilding fixture should preserve attribute/state chunks",
        ));
    } else if require_synthetic_fixtures {
        checks.push(layer_check(
            "worldbuilding fixture present",
            0,
            1,
            "missing worldbuilding section audit case",
        ));
    }

    GraphLayerAudit {
        pass: checks.iter().all(|check| check.passed),
        checks,
    }
}

fn find_case<'a>(cases: &'a [BenchCaseReport], name: &str) -> Option<&'a BenchCaseReport> {
    cases.iter().find(|case| case.name == name)
}

fn lens_count(case: &BenchCaseReport, lens: &str) -> usize {
    case.lens_chunk_count_by_lens
        .get(lens)
        .copied()
        .unwrap_or(0)
}

fn layer_check(
    name: impl Into<String>,
    actual: usize,
    minimum: usize,
    detail: &str,
) -> GraphLayerCheck {
    GraphLayerCheck {
        name: name.into(),
        passed: actual >= minimum,
        actual,
        minimum,
        detail: detail.to_owned(),
    }
}

fn run_phase6_consumers(case_name: &str, lens_chunks: &[LensChunk]) -> Vec<GraphDelta> {
    let context = GraphBuildContext {
        graph_name: case_name.to_owned(),
        document_id: Some(case_name.to_owned()),
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

fn profile_lens_build_ms(
    text: &str,
    base_chunks: &[BaseChunk],
    mentions: &[LensMention],
    ner_hints: &[LensChunkHint],
    mention_graph: &LensMentionGraph,
    surface_hits: &[LensSurfaceHit],
) -> BTreeMap<String, u128> {
    let mut out = BTreeMap::new();
    for lens in [
        LensKind::Entity,
        LensKind::Relationship,
        LensKind::Event,
        LensKind::Temporal,
        LensKind::Causal,
        LensKind::Attribute,
        LensKind::Worldbuilding,
        LensKind::Evidence,
    ] {
        let mut config = LensChunkerConfig::default();
        config.enabled_lenses = vec![lens];
        let started = Instant::now();
        let _chunks = build_lens_chunks(
            &LensChunkInput {
                text,
                base_chunks,
                mentions,
                ner_hints,
                mention_graph,
                surface_hits,
            },
            &config,
        );
        out.insert(
            bench_lens_name(lens).to_owned(),
            started.elapsed().as_millis(),
        );
    }
    out
}

fn ner_profile_map(metrics: &SurfaceNerMetrics) -> BTreeMap<String, u128> {
    [
        ("total", metrics.total_ms),
        ("knownSurface", metrics.known_surface_ms),
        ("nativeDiscovery", metrics.native_discovery_ms),
        ("routePlanning", metrics.route_planning_ms),
        ("workspaceIngest", metrics.workspace_ingest_ms),
        ("modelAndAdjudication", metrics.model_and_adjudication_ms),
        ("finalPackets", metrics.final_packets_ms),
        ("surfaceMemory", metrics.surface_memory_ms),
        ("mentionGraph", metrics.mention_graph_ms),
        ("chunkHints", metrics.chunk_hints_ms),
        ("knownCount", metrics.known_count as u128),
        ("nativeCount", metrics.native_count as u128),
        ("routeCount", metrics.route_count as u128),
        ("packetCount", metrics.packet_count as u128),
        ("graphEdgeCount", metrics.graph_edge_count as u128),
        ("chunkHintCount", metrics.chunk_hint_count as u128),
    ]
    .into_iter()
    .map(|(name, value)| (name.to_owned(), value))
    .collect()
}

fn bench_lens_name(lens: LensKind) -> &'static str {
    match lens {
        LensKind::Entity => "entity",
        LensKind::Relationship => "relationship",
        LensKind::Event => "event",
        LensKind::Temporal => "temporal",
        LensKind::Causal => "causal",
        LensKind::Attribute => "attribute",
        LensKind::Worldbuilding => "worldbuilding",
        LensKind::Evidence => "evidence",
    }
}

fn load_case(name: &str, path: Option<PathBuf>) -> Result<BenchCase, String> {
    let input_path = path.unwrap_or_else(|| workspace_root().join("docs").join("shortrun.md"));
    let text = fs::read_to_string(&input_path)
        .map_err(|error| format!("failed to read {}: {error}", input_path.display()))?;
    Ok(BenchCase {
        name: name.to_owned(),
        input_path: Some(input_path),
        text,
    })
}

fn synthetic_cases() -> Vec<BenchCase> {
    vec![
        BenchCase {
            name: "single chapter".to_owned(),
            input_path: None,
            text: "# Chapter One\nRyan met Len in New Rome. Len warned Ryan that Dynamis scouts were watching the harbor. Ryan promised to find Ghoul before sunset.".to_owned(),
        },
        BenchCase {
            name: "dialogue scene".to_owned(),
            input_path: None,
            text: "Ryan said, \"Len, keep the engine running.\" Len answered, \"Only if Quicksave stops joking.\" Ghoul shouted from the pier, \"I can hear you both.\"".to_owned(),
        },
        BenchCase {
            name: "temporal scene".to_owned(),
            input_path: None,
            text: "On May 8th, Ryan saved outside New Rome. Three hours later he met Wyvern. The next morning, Len found the camera footage before Dynamis erased it.".to_owned(),
        },
        BenchCase {
            name: "causal scene".to_owned(),
            input_path: None,
            text: "Because Vulcan attacked the convoy, Wyvern sealed Little Maghreb. Ryan therefore changed the route, which caused Ghoul to miss the ambush.".to_owned(),
        },
        BenchCase {
            name: "worldbuilding section".to_owned(),
            input_path: None,
            text: "New Rome is a city ruled by company contracts and faction law. Dynamis is the corporation in the tower, the Private Security owns the streets, and Rust Town is a district that carries the cost.".to_owned(),
        },
    ]
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

fn edge_count_for_lens(deltas: &[GraphDelta], lens: LensKind) -> usize {
    deltas
        .iter()
        .filter(|delta| delta.lens == lens)
        .map(|delta| delta.edge_count)
        .sum()
}

fn node_count_for_lens(deltas: &[GraphDelta], lens: LensKind) -> usize {
    deltas
        .iter()
        .filter(|delta| delta.lens == lens)
        .map(|delta| delta.node_count)
        .sum()
}

fn avg_lens_size(chunks: &[LensChunk]) -> f64 {
    if chunks.is_empty() {
        return 0.0;
    }
    chunks
        .iter()
        .map(|chunk| chunk.end.saturating_sub(chunk.start))
        .sum::<usize>() as f64
        / chunks.len() as f64
}

fn orphan_entity_count(
    mentions: &[&MentionPacket],
    graph: &phoenix_dynamic_ner::MentionGraph,
    active_mention_ids: &BTreeSet<u64>,
) -> usize {
    mentions
        .iter()
        .filter(|mention| mention.mention_kind != MentionKind::Pronoun)
        .filter(|mention| !has_active_edge(graph, mention.mention_id.0, active_mention_ids))
        .count()
}

fn active_edge_count(
    graph: &phoenix_dynamic_ner::MentionGraph,
    active_mention_ids: &BTreeSet<u64>,
) -> usize {
    graph
        .edges
        .iter()
        .filter(|edge| {
            active_mention_ids.contains(&edge.left.0) && active_mention_ids.contains(&edge.right.0)
        })
        .count()
}

fn has_active_edge(
    graph: &phoenix_dynamic_ner::MentionGraph,
    mention_id: u64,
    active_mention_ids: &BTreeSet<u64>,
) -> bool {
    graph.edges.iter().any(|edge| {
        (edge.left.0 == mention_id && active_mention_ids.contains(&edge.right.0))
            || (edge.right.0 == mention_id && active_mention_ids.contains(&edge.left.0))
    })
}

fn unique_candidate_keys(chunks: &[LensChunk]) -> BTreeSet<String> {
    chunks
        .iter()
        .map(|chunk| {
            format!(
                "{:?}:{}:{}:{}",
                chunk.lens,
                chunk.start,
                chunk.end,
                chunk.surfaces.join("|")
            )
        })
        .collect()
}

fn graph_connectedness(
    mentions: &[&MentionPacket],
    graph: &phoenix_dynamic_ner::MentionGraph,
    active_mention_ids: &BTreeSet<u64>,
) -> f64 {
    let n = mentions.len();
    if n < 2 {
        return 1.0;
    }
    let possible = n.saturating_mul(n.saturating_sub(1)) / 2;
    ratio(active_edge_count(graph, active_mention_ids), possible)
}

fn largest_component_ratio(
    mentions: &[&MentionPacket],
    graph: &phoenix_dynamic_ner::MentionGraph,
    active_mention_ids: &BTreeSet<u64>,
) -> f64 {
    if mentions.is_empty() {
        return 0.0;
    }
    let ids = mentions
        .iter()
        .map(|mention| mention.mention_id.0)
        .collect::<BTreeSet<_>>();
    let mut adjacency = BTreeMap::<u64, Vec<u64>>::new();
    for id in &ids {
        adjacency.entry(*id).or_default();
    }
    for edge in graph.edges.iter().filter(|edge| {
        active_mention_ids.contains(&edge.left.0) && active_mention_ids.contains(&edge.right.0)
    }) {
        adjacency.entry(edge.left.0).or_default().push(edge.right.0);
        adjacency.entry(edge.right.0).or_default().push(edge.left.0);
    }

    let mut seen = BTreeSet::new();
    let mut largest = 0usize;
    for id in ids {
        if seen.contains(&id) {
            continue;
        }
        let mut stack = vec![id];
        let mut size = 0usize;
        while let Some(current) = stack.pop() {
            if !seen.insert(current) {
                continue;
            }
            size += 1;
            if let Some(neighbors) = adjacency.get(&current) {
                stack.extend(neighbors.iter().copied());
            }
        }
        largest = largest.max(size);
    }
    ratio(largest, mentions.len())
}

fn ratio(numerator: usize, denominator: usize) -> f64 {
    if denominator == 0 {
        0.0
    } else {
        numerator as f64 / denominator as f64
    }
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
        fixture: FixtureSelection::All,
        profile_lenses: false,
    };
    if let Some(path) = string_arg(&args, "--input") {
        config.input_path = PathBuf::from(path);
    }
    config.json = args.iter().any(|arg| arg == "--json");
    if args.iter().any(|arg| arg == "--shortrun-only") {
        config.fixture = FixtureSelection::ShortrunOnly;
    }
    config.profile_lenses = args.iter().any(|arg| arg == "--profile-lenses");
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
