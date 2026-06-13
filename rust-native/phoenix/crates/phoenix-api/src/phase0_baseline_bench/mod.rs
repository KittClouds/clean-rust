use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use phoenix_alex::Lexicon;
use phoenix_api::{PhoenixPipelineApi, SidecarContinuityRunReport};
use phoenix_chunker_native::ChunkerConfig;
use phoenix_dynamic_ner::{MentionStatus, PhoenixNerEngineBuilder, SurfaceNerInput};
use phoenix_graph_kernel::KernelGraphSnapshot;
use phoenix_ingest_overgraph::{InvarantV3Config, PhoenixInvarantV3};
use phoenix_rel_post::{
    benchmark_scope_review_pipeline, default_relation_type_specs, RelationBenchmarkCounts,
};
use phoenix_store_native_core::{
    PhoenixArchiveStoreV2, PhoenixCausalPatchStore, PhoenixErPatchStore,
    PhoenixEventIdentityPatchStore, PhoenixGraphKernelStoreV2, PhoenixGraphPatchStore,
    PhoenixMemoryPatchStore, PhoenixRelationMentionSeedStore, PhoenixRelationPatchStore,
    PhoenixSemanticGraphPatchStore, PhoenixStateSchemaPatchStore, PhoenixTemporalPatchStore,
};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{
    DocumentId, EntityId, EntityKind, IngestDocument, LexiconEntry, ResolverEntitySeed, ScopeKey,
    SentenceSpan, TextRange, TokenClass, TokenSpan,
};
use serde::Serialize;

#[derive(Debug, Clone)]
pub struct Config {
    pub warmups: usize,
    pub iterations: usize,
    pub chapter: usize,
    pub json: bool,
    pub output_path: Option<PathBuf>,
    pub case_filter: Option<String>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            warmups: 0,
            iterations: 1,
            chapter: 1,
            json: false,
            output_path: None,
            case_filter: None,
        }
    }
}

#[derive(Debug, Clone)]
struct CaseInput {
    case_id: String,
    title: String,
    source_path: String,
    text: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PhaseStats {
    pub runs_us: Vec<u64>,
    pub min_us: u64,
    pub mean_us: f64,
    pub median_us: f64,
    pub p95_us: u64,
    pub max_us: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CandidatePreservationReport {
    pub accepted_candidate_count: usize,
    pub rejected_candidate_count: usize,
    pub preserved_candidate_count: usize,
    pub preservation_ratio: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphDeltaReport {
    pub projection_vertex_count: usize,
    pub projection_edge_count: usize,
    pub size: usize,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CaseMetrics {
    pub base_chunk_count: usize,
    pub lens_chunk_count_by_lens: BTreeMap<String, usize>,
    pub dynamic_ner_mention_count: usize,
    pub native_ner_mention_count: usize,
    pub entity_grounding_ratio: f64,
    pub orphan_entity_count: usize,
    pub event_candidate_count: usize,
    pub temporal_edge_count: usize,
    pub causal_edge_count: usize,
    pub relationship_candidate_count: usize,
    pub duplicate_candidate_rate: f64,
    pub accepted_rejected_candidate_preservation: CandidatePreservationReport,
    pub graph_delta_size: usize,
    pub graph_delta: GraphDeltaReport,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeReport {
    pub phases: BTreeMap<String, PhaseStats>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CaseReport {
    pub case_id: String,
    pub title: String,
    pub source_path: String,
    pub text_bytes: usize,
    pub metrics: CaseMetrics,
    pub ingest_counts: phoenix_ingest_overgraph::IngestBenchmarkCounts,
    pub relation_counts: RelationBenchmarkCounts,
    pub sidecar_continuity: SidecarContinuityRunReport,
    pub runtime: RuntimeReport,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BenchReport {
    pub corpus: String,
    pub warmups: usize,
    pub iterations: usize,
    pub cases: Vec<CaseReport>,
}

#[derive(Debug, Clone)]
struct Phase0Run {
    total_us: u64,
    chunker_us: u64,
    dynamic_ner_us: u64,
    native_ner_us: u64,
    ingest_us: u64,
    relation_us: u64,
    sidecar_continuity_us: u64,
    metrics: CaseMetrics,
    ingest_counts: phoenix_ingest_overgraph::IngestBenchmarkCounts,
    relation_counts: RelationBenchmarkCounts,
    sidecar_continuity: SidecarContinuityRunReport,
}

pub fn run(config: &Config) -> Result<BenchReport, String> {
    if config.iterations == 0 {
        return Err("--iterations must be greater than 0".to_owned());
    }

    let root = workspace_root();
    let cases = load_cases(&root, config.chapter, config.case_filter.as_deref())?;
    let ingest = PhoenixInvarantV3::new(InvarantV3Config::default());
    let lexicon = story_lexicon()?;
    let resolver_seeds = story_seeds();
    let relation_specs = default_relation_type_specs();

    let mut reports = Vec::with_capacity(cases.len());
    for input in cases {
        for warmup in 0..config.warmups {
            let _ = run_once(
                &root,
                &ingest,
                &lexicon,
                &resolver_seeds,
                &relation_specs,
                &input,
                format!("warmup-{warmup}"),
            )?;
        }

        let mut runs = Vec::with_capacity(config.iterations);
        for iteration in 0..config.iterations {
            runs.push(run_once(
                &root,
                &ingest,
                &lexicon,
                &resolver_seeds,
                &relation_specs,
                &input,
                format!("run-{iteration}"),
            )?);
        }
        let last = runs
            .last()
            .cloned()
            .ok_or_else(|| format!("no runs captured for {}", input.case_id))?;

        reports.push(CaseReport {
            case_id: input.case_id,
            title: input.title,
            source_path: input.source_path,
            text_bytes: input.text.len(),
            metrics: last.metrics,
            ingest_counts: last.ingest_counts,
            relation_counts: last.relation_counts,
            sidecar_continuity: last.sidecar_continuity,
            runtime: RuntimeReport {
                phases: phase_stats(&runs),
            },
        });
    }

    Ok(BenchReport {
        corpus: "phase0-baseline".to_owned(),
        warmups: config.warmups,
        iterations: config.iterations,
        cases: reports,
    })
}

pub fn default_output_path() -> PathBuf {
    workspace_root()
        .join("rust-native")
        .join("phoenix")
        .join("reports")
        .join("phase0-baseline-bench.json")
}

pub fn mean_ms(stats: Option<&PhaseStats>) -> f64 {
    stats
        .map(|value| value.mean_us / 1000.0)
        .unwrap_or_default()
}

fn run_once(
    root: &Path,
    ingest: &PhoenixInvarantV3,
    lexicon: &Lexicon,
    resolver_seeds: &[ResolverEntitySeed],
    relation_specs: &[phoenix_rel_post::GlirelRelationTypeSpec],
    input: &CaseInput,
    lane: String,
) -> Result<Phase0Run, String> {
    let total_started = Instant::now();

    let started = Instant::now();
    let base_chunks = phoenix_chunker_native::api::default_chunk_ranges(&input.text);
    let lens_chunk_count_by_lens = lens_chunk_counts(&input.text);
    let chunker_us = elapsed_us(started);

    let scope = ScopeKey::default();
    let (tokens, sentences) = tokenize_for_ner(&input.text);
    let started = Instant::now();
    let dynamic_ner = PhoenixNerEngineBuilder::new().build();
    let surface_hit_batch = lexicon.scan_surface_hits(&input.text, &scope);
    let dynamic_output = dynamic_ner
        .extract_mentions(&SurfaceNerInput {
            document_id: &input.case_id,
            text: &input.text,
            tokens: &tokens,
            sentences: &sentences,
            scope: &scope,
            lexicon: Some(lexicon),
            surface_hits: &surface_hit_batch.hits,
            label_bank_context: None,
        })
        .map_err(|error| format!("dynamic NER failed for {}: {error}", input.case_id))?;
    let dynamic_ner_us = elapsed_us(started);

    let started = Instant::now();
    let native_ner = ingest.benchmark_native_ner(&input.text, &scope, resolver_seeds);
    let native_ner_us = elapsed_us(started);

    let document = IngestDocument {
        document_id: DocumentId(input.case_id.clone()),
        note_id: None,
        title: input.title.clone(),
        text: input.text.clone(),
        scope: ScopeKey::default(),
    };

    let started = Instant::now();
    let ingest_report = ingest
        .benchmark_document_pipeline(&document, None, benchmark_created_at())
        .map_err(|error| format!("ingest benchmark failed for {}: {error}", input.case_id))?;
    let ingest_us = elapsed_us(started);

    let archive = ingest
        .build_archive_for_benchmark(&document, None, benchmark_created_at())
        .map_err(|error| format!("archive build failed for {}: {error}", input.case_id))?;

    let started = Instant::now();
    let relation_report = benchmark_scope_review_pipeline(
        std::slice::from_ref(&archive),
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        relation_specs,
    )
    .map_err(|error| format!("relation benchmark failed for {}: {error}", input.case_id))?;
    let relation_us = elapsed_us(started);

    let (store, store_path) = seed_store(root, ingest, input, lane)?;
    let started = Instant::now();
    let api = PhoenixPipelineApi::new(store);
    let sidecar_continuity = api
        .run_sidecar_continuity_scope(None, benchmark_created_at() + 100)
        .map_err(|error| format!("sidecar continuity failed for {}: {error}", input.case_id))?;
    let sidecar_continuity_us = elapsed_us(started);
    drop(api.into_store());
    cleanup_seed_store(&store_path);

    let metrics = build_case_metrics(
        base_chunks.len(),
        lens_chunk_count_by_lens,
        &dynamic_output,
        native_ner.mention_count,
        &ingest_report.counts,
        &relation_report.counts,
        &sidecar_continuity,
    );

    Ok(Phase0Run {
        total_us: elapsed_us(total_started),
        chunker_us,
        dynamic_ner_us,
        native_ner_us,
        ingest_us,
        relation_us,
        sidecar_continuity_us,
        metrics,
        ingest_counts: ingest_report.counts,
        relation_counts: relation_report.counts,
        sidecar_continuity,
    })
}

fn build_case_metrics(
    base_chunk_count: usize,
    lens_chunk_count_by_lens: BTreeMap<String, usize>,
    dynamic_output: &phoenix_dynamic_ner::SurfaceNerOutput,
    native_ner_mention_count: usize,
    ingest_counts: &phoenix_ingest_overgraph::IngestBenchmarkCounts,
    relation_counts: &RelationBenchmarkCounts,
    sidecar: &SidecarContinuityRunReport,
) -> CaseMetrics {
    let dynamic_ner_mention_count = dynamic_output.mentions.len();
    let grounded_count = dynamic_output
        .mentions
        .iter()
        .filter(|mention| mention.entity_ref.is_some())
        .count();
    let orphan_entity_count = dynamic_output
        .mentions
        .iter()
        .filter(|mention| {
            dynamic_output
                .mention_graph
                .edges_for(mention.mention_id)
                .is_empty()
        })
        .count();
    let duplicate_candidate_rate = duplicate_candidate_rate(&dynamic_output.mentions);
    let accepted_candidate_count = dynamic_output
        .mentions
        .iter()
        .filter(|mention| {
            matches!(
                mention.status,
                MentionStatus::AcceptedKnown
                    | MentionStatus::AcceptedNew
                    | MentionStatus::AliasCandidate
            )
        })
        .count();
    let rejected_candidate_count = dynamic_output
        .mentions
        .iter()
        .filter(|mention| mention.status == MentionStatus::Rejected)
        .count();
    let preserved_candidate_count = accepted_candidate_count + rejected_candidate_count;
    let graph_delta = GraphDeltaReport {
        projection_vertex_count: sidecar.graph.graph_projection_vertex_count,
        projection_edge_count: sidecar.graph.graph_projection_edge_count,
        size: sidecar.graph.graph_projection_vertex_count
            + sidecar.graph.graph_projection_edge_count,
    };

    CaseMetrics {
        base_chunk_count,
        lens_chunk_count_by_lens,
        dynamic_ner_mention_count,
        native_ner_mention_count,
        entity_grounding_ratio: ratio(grounded_count, dynamic_ner_mention_count),
        orphan_entity_count,
        event_candidate_count: ingest_counts.event_identity_seed_count,
        temporal_edge_count: sidecar.temporal.temporal_interval_count
            + sidecar.temporal.temporal_segment_count,
        causal_edge_count: sidecar.causal.causal_edge_count,
        relationship_candidate_count: relation_counts.total_candidate_relation_type_count,
        duplicate_candidate_rate,
        accepted_rejected_candidate_preservation: CandidatePreservationReport {
            accepted_candidate_count,
            rejected_candidate_count,
            preserved_candidate_count,
            preservation_ratio: ratio(preserved_candidate_count, dynamic_ner_mention_count),
        },
        graph_delta_size: graph_delta.size,
        graph_delta,
    }
}

fn lens_chunk_counts(text: &str) -> BTreeMap<String, usize> {
    [
        ("base", ChunkerConfig::default()),
        (
            "dialogue-tight",
            ChunkerConfig {
                chunk_size: 300,
                overlap: 60,
            },
        ),
        (
            "temporal-wide",
            ChunkerConfig {
                chunk_size: 800,
                overlap: 160,
            },
        ),
        (
            "causal-medium",
            ChunkerConfig {
                chunk_size: 600,
                overlap: 120,
            },
        ),
        (
            "lore-wide",
            ChunkerConfig {
                chunk_size: 1000,
                overlap: 200,
            },
        ),
        (
            "attribute-tight",
            ChunkerConfig {
                chunk_size: 250,
                overlap: 50,
            },
        ),
    ]
    .into_iter()
    .map(|(name, config)| {
        (
            name.to_owned(),
            phoenix_chunker_native::api::chunk_ranges(text, &config).len(),
        )
    })
    .collect()
}

fn seed_store(
    root: &Path,
    ingest: &PhoenixInvarantV3,
    input: &CaseInput,
    lane: String,
) -> Result<(PhoenixOvergraphStore, PathBuf), String> {
    let store_path = root
        .join("rust-native")
        .join("phoenix")
        .join("reports")
        .join("phase0-bench-stores")
        .join(format!("{}-{}-{}", input.case_id, std::process::id(), lane));
    let _ = fs::remove_dir_all(&store_path);

    let store = PhoenixOvergraphStore::open(&store_path)
        .map_err(|error| format!("failed to open {}: {error}", store_path.display()))?;
    init_store_schemas(&store)?;
    store
        .write_kernel_checkpoint(1, "phase0-baseline-seed", &KernelGraphSnapshot::default())
        .map_err(|error| format!("failed to seed kernel checkpoint: {error}"))?;

    let document = IngestDocument {
        document_id: DocumentId(input.case_id.clone()),
        note_id: None,
        title: input.title.clone(),
        text: input.text.clone(),
        scope: ScopeKey::default(),
    };
    ingest
        .ingest_documents_native(&store, None, &[document], 0, benchmark_created_at())
        .map_err(|error| format!("failed to seed store for {}: {error}", input.case_id))?;
    Ok((store, store_path))
}

fn init_store_schemas(store: &PhoenixOvergraphStore) -> Result<(), String> {
    store
        .init_archive_schema()
        .map_err(|error| format!("failed to init archive schema: {error}"))?;
    store
        .init_graph_kernel_schema()
        .map_err(|error| format!("failed to init graph kernel schema: {error}"))?;
    store
        .init_er_patch_schema()
        .map_err(|error| format!("failed to init er patch schema: {error}"))?;
    store
        .init_event_identity_patch_schema()
        .map_err(|error| format!("failed to init event identity schema: {error}"))?;
    store
        .init_temporal_patch_schema()
        .map_err(|error| format!("failed to init temporal schema: {error}"))?;
    store
        .init_causal_patch_schema()
        .map_err(|error| format!("failed to init causal schema: {error}"))?;
    store
        .init_relation_patch_schema()
        .map_err(|error| format!("failed to init relation schema: {error}"))?;
    store
        .init_relation_mention_seed_schema()
        .map_err(|error| format!("failed to init relation mention seed schema: {error}"))?;
    store
        .init_state_schema_patch_schema()
        .map_err(|error| format!("failed to init state schema schema: {error}"))?;
    store
        .init_memory_patch_schema()
        .map_err(|error| format!("failed to init memory schema: {error}"))?;
    store
        .init_graph_patch_schema()
        .map_err(|error| format!("failed to init graph schema: {error}"))?;
    store
        .init_semantic_graph_patch_schema()
        .map_err(|error| format!("failed to init semantic graph schema: {error}"))?;
    Ok(())
}

fn load_cases(
    root: &Path,
    chapter: usize,
    case_filter: Option<&str>,
) -> Result<Vec<CaseInput>, String> {
    let shortrun_path = root.join("docs").join("shortrun.md");
    let shortrun = fs::read_to_string(&shortrun_path)
        .map_err(|error| format!("failed to read {}: {error}", shortrun_path.display()))?;
    let mut cases = vec![
        CaseInput {
            case_id: "shortrun-full".to_owned(),
            title: "Shortrun Full".to_owned(),
            source_path: relative_path(root, &shortrun_path),
            text: shortrun.clone(),
        },
        extract_chapter_case(&shortrun, chapter)?,
    ];

    for (case_id, title, file_name) in [
        ("single-chapter", "Single Chapter", "single-chapter.md"),
        (
            "dialogue-heavy",
            "Dialogue Heavy Scene",
            "dialogue-heavy.md",
        ),
        (
            "temporal-heavy",
            "Temporal Heavy Scene",
            "temporal-heavy.md",
        ),
        ("causal-heavy", "Causal Heavy Scene", "causal-heavy.md"),
        (
            "worldbuilding-lore",
            "Worldbuilding Lore",
            "worldbuilding-lore.md",
        ),
        (
            "attribute-heavy-character",
            "Attribute Heavy Character",
            "attribute-heavy-character.md",
        ),
    ] {
        let path = root
            .join("rust-native")
            .join("phoenix")
            .join("fixtures")
            .join("phase0")
            .join(file_name);
        let text = fs::read_to_string(&path)
            .map_err(|error| format!("failed to read {}: {error}", path.display()))?;
        cases.push(CaseInput {
            case_id: case_id.to_owned(),
            title: title.to_owned(),
            source_path: relative_path(root, &path),
            text,
        });
    }
    if let Some(case_filter) = case_filter {
        cases.retain(|case| case.case_id == case_filter);
        if cases.is_empty() {
            return Err(format!("case '{case_filter}' not found"));
        }
    }
    Ok(cases)
}

fn extract_chapter_case(text: &str, chapter: usize) -> Result<CaseInput, String> {
    let mut headings = text
        .match_indices("## Chapter ")
        .map(|(offset, _)| offset)
        .collect::<Vec<_>>();
    if headings.is_empty() {
        return Err("no chapter headings found in shortrun.md".to_owned());
    }
    headings.sort_unstable();
    let chapter_index = chapter.saturating_sub(1);
    let Some(&start) = headings.get(chapter_index) else {
        return Err(format!("chapter {chapter} not found"));
    };
    let end = headings
        .get(chapter_index + 1)
        .copied()
        .unwrap_or(text.len());
    let slice = text[start..end].trim().to_owned();
    let title = slice
        .lines()
        .next()
        .unwrap_or("Chapter Slice")
        .trim()
        .to_owned();
    Ok(CaseInput {
        case_id: format!("shortrun-chapter-{chapter}"),
        title,
        source_path: format!("docs/shortrun.md#chapter-{chapter}"),
        text: slice,
    })
}

fn story_lexicon() -> Result<Lexicon, String> {
    let entries = story_names()
        .into_iter()
        .map(|name| LexiconEntry {
            entity_id: EntityId(name.to_ascii_lowercase()),
            label: name.to_owned(),
            aliases: Vec::new(),
            kind: Some(EntityKind::Character),
            gender: None,
            number: None,
            scope: ScopeKey::default(),
        })
        .collect::<Vec<_>>();
    Lexicon::from_entries(&entries).map_err(|error| format!("failed to build lexicon: {error:?}"))
}

fn story_seeds() -> Vec<ResolverEntitySeed> {
    story_names()
        .into_iter()
        .map(|name| ResolverEntitySeed {
            entity_id: EntityId(name.to_ascii_lowercase()),
            canonical_name: name.to_owned(),
            aliases: Vec::new(),
            kind: Some(EntityKind::Character),
            gender: None,
            number: None,
            scope: ScopeKey::default(),
        })
        .collect()
}

fn story_names() -> [&'static str; 9] {
    [
        "Aella", "Aurora", "Brynwyn", "Iriane", "Isolde", "Kai", "Phaeris", "Rowan", "Siofra",
    ]
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
    TokenSpan {
        range: TextRange {
            start: start as u32,
            end: end as u32,
        },
        capitalized: text[start..].starts_with(|ch: char| ch.is_uppercase()),
        pos: None,
        token_class: Some(TokenClass::Word),
        masked: false,
    }
}

fn duplicate_candidate_rate(mentions: &[phoenix_dynamic_ner::MentionPacket]) -> f64 {
    if mentions.is_empty() {
        return 0.0;
    }
    let unique = mentions
        .iter()
        .map(|mention| mention.normalized.to_string())
        .collect::<BTreeSet<_>>()
        .len();
    ratio(mentions.len().saturating_sub(unique), mentions.len())
}

fn phase_stats(runs: &[Phase0Run]) -> BTreeMap<String, PhaseStats> {
    BTreeMap::from([
        phase_entry("total_us", runs.iter().map(|run| run.total_us).collect()),
        phase_entry(
            "chunker_us",
            runs.iter().map(|run| run.chunker_us).collect(),
        ),
        phase_entry(
            "dynamic_ner_us",
            runs.iter().map(|run| run.dynamic_ner_us).collect(),
        ),
        phase_entry(
            "native_ner_us",
            runs.iter().map(|run| run.native_ner_us).collect(),
        ),
        phase_entry("ingest_us", runs.iter().map(|run| run.ingest_us).collect()),
        phase_entry(
            "relation_us",
            runs.iter().map(|run| run.relation_us).collect(),
        ),
        phase_entry(
            "sidecar_continuity_us",
            runs.iter().map(|run| run.sidecar_continuity_us).collect(),
        ),
    ])
}

fn phase_entry(name: &str, runs_us: Vec<u64>) -> (String, PhaseStats) {
    (name.to_owned(), compute_phase_stats(runs_us))
}

fn compute_phase_stats(mut runs_us: Vec<u64>) -> PhaseStats {
    runs_us.sort_unstable();
    let sum = runs_us.iter().copied().sum::<u64>() as f64;
    let len = runs_us.len().max(1);
    PhaseStats {
        min_us: *runs_us.first().unwrap_or(&0),
        mean_us: sum / len as f64,
        median_us: percentile(&runs_us, 0.5),
        p95_us: percentile(&runs_us, 0.95).round() as u64,
        max_us: *runs_us.last().unwrap_or(&0),
        runs_us,
    }
}

fn percentile(sorted: &[u64], q: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let pos = ((sorted.len() - 1) as f64 * q).round() as usize;
    sorted[pos.min(sorted.len() - 1)] as f64
}

fn ratio(numerator: usize, denominator: usize) -> f64 {
    if denominator == 0 {
        0.0
    } else {
        numerator as f64 / denominator as f64
    }
}

fn cleanup_seed_store(path: &Path) {
    let _ = fs::remove_dir_all(path);
}

fn relative_path(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .display()
        .to_string()
        .replace('\\', "/")
}

fn elapsed_us(started: Instant) -> u64 {
    started.elapsed().as_micros() as u64
}

fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(4)
        .expect("workspace root")
        .to_path_buf()
}

fn benchmark_created_at() -> i64 {
    1_700_000_000_000
}
