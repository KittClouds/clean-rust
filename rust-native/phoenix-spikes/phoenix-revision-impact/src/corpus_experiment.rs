//! Read-only real-corpus stress harness for deterministic revision impact.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write as _;
use std::fs::File;
use std::path::{Path, PathBuf};
use std::time::Instant;

use compact_str::format_compact;
use memchr::memchr_iter;
use memmap2::MmapOptions;
use phoenix_graph_rebuild::{
    build_graph_rebuild_snapshot, GraphEvent, GraphRebuildInput, GraphRebuildSnapshot,
    GraphScopeKind, GraphTemporalEdge,
};
use phoenix_semantic_v2::{
    CausalClaimStatus, CausalEdgeAddition, CausalEdgeId, CausalRelationKind, CausalScopeSidecar,
    TemporalConstraintId, TemporalConstraintRecord, TemporalScopeSidecar,
};
use phoenix_types::{
    BiTemporalWindow, CausalKind, ConstraintKind, EntityId, EventId, FactId, FactValue,
    ImpactClassification, LexiconEntry, Polarity, ScopeKey, SemanticNodeRef, StoryInterval,
    StoryMutation, StoryTime,
};
use sha2::{Digest, Sha256};

use crate::{
    detect_revision_impacts, project_authoritative_constraints, AuthoritativeRevisionSources,
    CounterfactualGraphView, EvidenceRef, GraphGeneration, IdentityCoverage, InferenceAuthority,
    InferenceEdgeSeed, InferenceNodeSeed, InferenceProjectionInput, NamedSidecarDigest,
    RequirementDependency, RequirementTruthRef, RevisionAnalysisViews, RevisionDetectorInput,
    RevisionEdgeRecord, RevisionFactRecord, RevisionGraphSnapshot, RevisionRequirementRecord,
    RevisionRequirementSidecar, RippleConfig, SceneCoverageRequest,
    REVISION_REQUIREMENT_SIDECAR_SCHEMA,
};

#[path = "corpus_experiment_receipt.rs"]
mod receipt;
pub use receipt::*;
#[path = "corpus_experiment_digest.rs"]
mod canonical_digest;
use canonical_digest::canonical_extractor_digest;
#[path = "corpus_mutation_experiment.rs"]
mod mutation_experiment;
pub use mutation_experiment::*;

#[derive(Debug, thiserror::Error)]
#[error("{0}")]
pub struct CorpusExperimentError(String);

type ExperimentResult<T> = Result<T, CorpusExperimentError>;

struct AdaptedBook {
    base: RevisionGraphSnapshot,
    requirements: RevisionRequirementSidecar,
    temporal: TemporalScopeSidecar,
    causal: CausalScopeSidecar,
    inference: InferenceProjectionInput,
    scene_by_event: BTreeMap<String, String>,
}

pub fn run_corpus_experiment(manifest_path: &Path) -> ExperimentResult<CorpusExperimentReceipt> {
    let started = Instant::now();
    let working_set_start_bytes = process_memory().0;
    let manifest_bytes = std::fs::read(manifest_path).map_err(error)?;
    let manifest: CorpusManifest = serde_json::from_slice(&manifest_bytes).map_err(error)?;
    if manifest.schema != "phoenix.revision-impact-corpus/v1"
        || manifest.mode != "read_only_research"
    {
        return Err(CorpusExperimentError(
            "manifest is not the protected read-only corpus".into(),
        ));
    }
    let root = manifest_path
        .parent()
        .ok_or_else(|| CorpusExperimentError("manifest has no parent".into()))?;
    let mut books = Vec::new();
    let mut mutations = Vec::new();
    let mut totals = CorpusExperimentTotals {
        series: manifest.series.len(),
        ..Default::default()
    };

    for series in &manifest.series {
        let mut series_negative_done = false;
        for book in &series.books {
            let path = root.join(&book.path);
            let (book_receipt, mut case_receipts, negative_done) =
                run_book(&series.series_id, book, &path, !series_negative_done)?;
            series_negative_done |= negative_done;
            totals.add_book(&book_receipt);
            for case in &case_receipts {
                totals.add_case(case);
            }
            books.push(book_receipt);
            mutations.append(&mut case_receipts);
        }
    }
    let (working_set, peak_working_set_bytes) = process_memory();
    let all_source_copies_unchanged = books.iter().all(|book| book.source_unchanged);
    let all_cases_passed = mutations.iter().all(|case| case.passed);
    Ok(CorpusExperimentReceipt {
        schema: CORPUS_EXPERIMENT_SCHEMA,
        manifest_schema: manifest.schema,
        manifest_path: manifest_path.display().to_string(),
        input_mode: manifest.mode,
        authoritative_claim: "structural extractor stress test; not author-reviewed narrative gold",
        models_enabled: false,
        persistence_writes: false,
        working_set_start_bytes,
        peak_working_set_bytes: peak_working_set_bytes.max(working_set),
        elapsed_micros: micros(started.elapsed()),
        books,
        mutations,
        totals,
        all_source_copies_unchanged,
        all_cases_passed,
    })
}

fn run_book(
    series_id: &str,
    book: &ManifestBook,
    path: &Path,
    add_negative: bool,
) -> ExperimentResult<(CorpusBookReceipt, Vec<CorpusMutationReceipt>, bool)> {
    let file = File::open(path).map_err(error)?;
    // SAFETY: the file is opened read-only and the experiment never mutates corpus paths.
    let mmap = unsafe { MmapOptions::new().map(&file) }.map_err(error)?;
    let before_hash = sha256_upper(&mmap);
    let chapters = count_chapter_headings(&mmap);
    if mmap.len() as u64 != book.bytes
        || before_hash != book.sha256
        || chapters != book.chapter_headings
    {
        return Err(CorpusExperimentError(format!(
            "copy verification failed for {}",
            book.book_id
        )));
    }
    let text = std::str::from_utf8(&mmap).map_err(error)?;
    let scope = ScopeKey {
        narrative_id: Some(series_id.to_owned()),
        ..ScopeKey::default()
    };
    let lexicon = lexicon_for(series_id, &scope);
    let generation = generation_for(&book.book_id);
    let build_started = Instant::now();
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Narrative,
        scope_id: series_id,
        note_id: &book.book_id,
        text,
        scope,
        entities: &lexicon,
        candidate_count: 0,
        built_at: Some(0),
    })
    .map_err(error)?;
    let build_micros = micros(build_started.elapsed());
    let analysis_started = Instant::now();
    let adapted = adapt_snapshot(generation, &snapshot, None)?;
    let projected = project_authoritative_constraints(AuthoritativeRevisionSources {
        base: &adapted.base,
        requirements: &adapted.requirements,
        temporal: Some(&adapted.temporal),
        memory: None,
        causal: Some(&adapted.causal),
    })
    .map_err(error)?;
    let views = RevisionAnalysisViews::project(
        generation,
        projected.constraints,
        adapted.inference.clone(),
    )
    .map_err(error)?;
    let mut cases = Vec::new();
    if let Some(edge) = snapshot.temporal_edges.first() {
        cases.push(run_edge_case(
            series_id,
            &book.book_id,
            "hard_temporal",
            edge,
            ImpactClassification::Broken,
            &adapted,
            &views,
            &projected.receipt,
        )?);
    }
    if let Some(edge) = snapshot.causal_edges.first() {
        // The extractor emits every causal pair as a temporal pair too. Remove
        // only that companion edge to exercise the soft-only classification
        // invariant; the full graph remains in use for every other case.
        let isolated = adapt_snapshot(
            generation,
            &snapshot,
            Some((edge.source_id.as_str(), edge.target_id.as_str())),
        )?;
        let isolated_projection = project_authoritative_constraints(AuthoritativeRevisionSources {
            base: &isolated.base,
            requirements: &isolated.requirements,
            temporal: Some(&isolated.temporal),
            memory: None,
            causal: Some(&isolated.causal),
        })
        .map_err(error)?;
        let isolated_views = RevisionAnalysisViews::project(
            generation,
            isolated_projection.constraints,
            isolated.inference.clone(),
        )
        .map_err(error)?;
        cases.push(run_edge_case(
            series_id,
            &book.book_id,
            "soft_causal_isolated",
            edge,
            ImpactClassification::Suspicious,
            &isolated,
            &isolated_views,
            &isolated_projection.receipt,
        )?);
    }
    let mut negative_done = false;
    if add_negative {
        if let Some(event) = negative_control_event(&snapshot) {
            cases.push(run_negative_case(
                series_id,
                &book.book_id,
                event,
                &adapted,
                &views,
                &projected.receipt,
            )?);
            negative_done = true;
        }
    }
    let analysis_micros = micros(analysis_started.elapsed());
    drop(mmap);
    let after_bytes = std::fs::read(path).map_err(error)?;
    let after_hash = sha256_upper(&after_bytes);
    let receipt = CorpusBookReceipt {
        series_id: series_id.to_owned(),
        book_id: book.book_id.clone(),
        book_ordinal: book.ordinal,
        copied_path: path.display().to_string(),
        source_bytes: book.bytes as usize,
        source_sha256: before_hash.clone(),
        chapter_headings: chapters,
        chunks: snapshot.chunks.len(),
        mentions: snapshot.mentions.len(),
        events: snapshot.events.len(),
        temporal_edges: snapshot.temporal_edges.len(),
        causal_edges: snapshot.causal_edges.len(),
        memory_states: snapshot.memory_state.len(),
        hard_constraints: snapshot.temporal_edges.len(),
        soft_constraints: snapshot.causal_edges.len(),
        build_micros,
        analysis_micros,
        source_unchanged: before_hash == after_hash,
    };
    Ok((receipt, cases, negative_done))
}

fn adapt_snapshot(
    generation: GraphGeneration,
    snapshot: &GraphRebuildSnapshot,
    excluded_temporal_pair: Option<(&str, &str)>,
) -> ExperimentResult<AdaptedBook> {
    let interval = wide_interval();
    let mut facts = Vec::with_capacity(snapshot.events.len());
    let mut scene_by_event = BTreeMap::new();
    let mut inference_nodes = Vec::with_capacity(snapshot.events.len());
    for event in &snapshot.events {
        let fact_id = event_fact(&event.id);
        facts.push(RevisionFactRecord {
            fact_id,
            value: FactValue::Boolean(true),
            interval,
        });
        let scene = event
            .chunk_id
            .as_deref()
            .unwrap_or(event.id.as_str())
            .to_owned();
        scene_by_event.insert(event.id.to_string(), scene);
        inference_nodes.push(InferenceNodeSeed {
            node_id: event.id.clone(),
            node_type: "event".into(),
            embedding_text: event.label.clone(),
        });
    }
    let mut requirements =
        Vec::with_capacity(snapshot.temporal_edges.len() + snapshot.causal_edges.len());
    let mut revision_edges = Vec::with_capacity(requirements.capacity());
    let mut temporal = TemporalScopeSidecar {
        generation: generation.0,
        ..Default::default()
    };
    let mut causal = CausalScopeSidecar {
        generation: generation.0,
        ..Default::default()
    };
    let mut relations = Vec::with_capacity(requirements.capacity());
    for edge in &snapshot.temporal_edges {
        if excluded_temporal_pair.is_some_and(|pair| {
            edge.source_id.as_str() == pair.0 && edge.target_id.as_str() == pair.1
        }) {
            continue;
        }
        add_requirement(
            edge,
            ConstraintKind::RequiresTemporalOrder,
            generation,
            &scene_by_event,
            &mut requirements,
            &mut revision_edges,
            &mut temporal,
            &mut causal,
            &mut relations,
        )?;
    }
    for edge in &snapshot.causal_edges {
        add_requirement(
            edge,
            ConstraintKind::CausalSupport,
            generation,
            &scene_by_event,
            &mut requirements,
            &mut revision_edges,
            &mut temporal,
            &mut causal,
            &mut relations,
        )?;
    }
    let base = RevisionGraphSnapshot::new(
        generation,
        facts,
        Vec::new(),
        revision_edges,
        vec![NamedSidecarDigest {
            sidecar_id: "real-corpus-extractor".into(),
            digest: canonical_extractor_digest(snapshot),
        }],
    )
    .map_err(error)?;
    Ok(AdaptedBook {
        base,
        requirements: RevisionRequirementSidecar {
            schema_version: REVISION_REQUIREMENT_SIDECAR_SCHEMA.into(),
            generation,
            requirements,
        },
        temporal,
        causal,
        inference: InferenceProjectionInput {
            accepted_nodes: inference_nodes,
            relations,
            memberships: Vec::new(),
        },
        scene_by_event,
    })
}

#[allow(clippy::too_many_arguments)]
fn add_requirement(
    edge: &GraphTemporalEdge,
    kind: ConstraintKind,
    generation: GraphGeneration,
    scenes: &BTreeMap<String, String>,
    requirements: &mut Vec<RevisionRequirementRecord>,
    revision_edges: &mut Vec<RevisionEdgeRecord>,
    temporal: &mut TemporalScopeSidecar,
    causal: &mut CausalScopeSidecar,
    relations: &mut Vec<InferenceEdgeSeed>,
) -> ExperimentResult<()> {
    let scene = scenes
        .get(edge.target_id.as_str())
        .ok_or_else(|| CorpusExperimentError(format!("missing target event {}", edge.target_id)))?;
    let fact_id = event_fact(&edge.source_id);
    let constraint_id = format_compact!("constraint:{}", edge.id);
    let truth_id = format_compact!("truth:{}", edge.id);
    let confidence = confidence_millis(edge.confidence);
    let evidence = edge
        .evidence_ids
        .iter()
        .map(|id| EvidenceRef::anchored(id.clone()))
        .collect::<Vec<_>>();
    let truth_ref = if kind == ConstraintKind::RequiresTemporalOrder {
        temporal.constraints.push(TemporalConstraintRecord {
            constraint_id: TemporalConstraintId(truth_id.to_string()),
            document_id: edge.target_id.to_string(),
            source_event_id: Some(edge.source_id.to_string()),
            target_event_id: Some(edge.target_id.to_string()),
            hard: true,
            confidence_millis: confidence as u32,
            temporal: wide_window(),
            evidence_refs: edge.evidence_ids.iter().map(ToString::to_string).collect(),
            ..Default::default()
        });
        RequirementTruthRef::TemporalConstraint {
            constraint_id: truth_id,
        }
    } else {
        causal.edge_records.push(CausalEdgeAddition {
            edge_id: CausalEdgeId(truth_id.to_string()),
            case_id: constraint_id.to_string(),
            document_id: edge.target_id.to_string(),
            source: SemanticNodeRef::Event(EventId(edge.source_id.to_string())),
            canonical_cause_event_id: None,
            target: SemanticNodeRef::Event(EventId(edge.target_id.to_string())),
            canonical_effect_event_id: None,
            kind: CausalKind::Enables,
            relation_kind: CausalRelationKind::EnablingCondition,
            status: CausalClaimStatus::Active,
            first_seen_revision: generation.0,
            latest_decision_id: None,
            confidence_millis: confidence as u32,
            cue: Some(edge.relation_type.to_string()),
            attributed_to: None,
            polarity: Polarity::Positive,
            claim_atom_ids: Vec::new(),
            evidence_refs: edge.evidence_ids.iter().map(ToString::to_string).collect(),
            effective_interval: wide_window(),
            observation_interval: wide_window(),
            temporal_certainty_millis: confidence as u32,
            created_at: 0,
        });
        RequirementTruthRef::CausalEdge { edge_id: truth_id }
    };
    requirements.push(RevisionRequirementRecord {
        constraint_id: constraint_id.clone(),
        dependency: RequirementDependency::Fact {
            fact_id: fact_id.clone(),
        },
        expected_value: FactValue::Boolean(true),
        dependent_scene_id: scene.as_str().into(),
        kind,
        valid_interval: wide_interval(),
        truth_ref,
        evidence,
        confidence_millis: confidence,
    });
    revision_edges.push(RevisionEdgeRecord {
        edge_id: constraint_id,
        dependency_fact_ids: vec![fact_id],
        dependency_state_refs: Vec::new(),
    });
    relations.push(InferenceEdgeSeed {
        edge_id: edge.id.clone(),
        source_id: edge.source_id.clone(),
        target_id: edge.target_id.clone(),
        relation_type: edge.relation_type.clone(),
        authority: InferenceAuthority::Asserted,
        evidence_ids: edge.evidence_ids.clone(),
        confidence_millis: confidence,
    });
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn run_edge_case(
    series_id: &str,
    book_id: &str,
    kind: &str,
    edge: &GraphTemporalEdge,
    expected: ImpactClassification,
    adapted: &AdaptedBook,
    views: &RevisionAnalysisViews,
    receipt: &crate::ConstraintProjectionReceipt,
) -> ExperimentResult<CorpusMutationReceipt> {
    let expected_scene = adapted.scene_by_event.get(edge.target_id.as_str()).cloned();
    run_case(
        series_id,
        book_id,
        kind,
        &edge.source_id,
        expected_scene,
        Some(expected),
        adapted,
        views,
        receipt,
    )
}

fn run_negative_case(
    series_id: &str,
    book_id: &str,
    event: &GraphEvent,
    adapted: &AdaptedBook,
    views: &RevisionAnalysisViews,
    receipt: &crate::ConstraintProjectionReceipt,
) -> ExperimentResult<CorpusMutationReceipt> {
    run_case(
        series_id,
        book_id,
        "negative_control",
        &event.id,
        None,
        None,
        adapted,
        views,
        receipt,
    )
}

#[allow(clippy::too_many_arguments)]
fn run_case(
    series_id: &str,
    book_id: &str,
    kind: &str,
    source_event_id: &str,
    expected_scene: Option<String>,
    expected: Option<ImpactClassification>,
    adapted: &AdaptedBook,
    views: &RevisionAnalysisViews,
    projection_receipt: &crate::ConstraintProjectionReceipt,
) -> ExperimentResult<CorpusMutationReceipt> {
    let mutation = StoryMutation::RetractFact {
        fact_id: event_fact(source_event_id),
    };
    let base_before = adapted.base.digest();
    let overlay = CounterfactualGraphView::new(&adapted.base, vec![mutation]).map_err(error)?;
    let detect = || {
        detect_revision_impacts(
            RevisionDetectorInput {
                overlay: &overlay,
                constraint_graph: &views.constraint_graph,
                requirements: &adapted.requirements,
                projection_receipt,
                identity_coverage: IdentityCoverage::SameRevision,
                coverage_requests: &[] as &[SceneCoverageRequest],
            },
            RippleConfig::default(),
        )
        .map_err(error)
    };
    let first = detect()?;
    let second = detect()?;
    let observed = expected_scene.as_deref().and_then(|scene| {
        first
            .authoritative_impacts
            .iter()
            .find(|impact| impact.scene_id.0 == scene)
            .map(|impact| impact.classification)
    });
    let base_after = adapted.base.digest();
    let deterministic_rerun_match =
        first.deterministic_receipt.report_digest == second.deterministic_receipt.report_digest;
    let no_truth_writes = base_before == base_after && first.deterministic_receipt.no_truth_writes;
    let passed = match expected {
        Some(classification) => observed == Some(classification),
        None => first.authoritative_impacts.is_empty(),
    } && deterministic_rerun_match
        && no_truth_writes;
    Ok(CorpusMutationReceipt {
        series_id: series_id.to_owned(),
        book_id: book_id.to_owned(),
        case_id: format!("{book_id}:{kind}:{source_event_id}"),
        mutation_kind: kind.to_owned(),
        source_event_id: source_event_id.to_owned(),
        expected_scene_id: expected_scene,
        expected_classification: expected,
        observed_classification: observed,
        impact_count: first.authoritative_impacts.len(),
        report_digest: hex_digest(first.deterministic_receipt.report_digest.0),
        deterministic_rerun_match,
        no_truth_writes,
        passed,
    })
}

fn negative_control_event(snapshot: &GraphRebuildSnapshot) -> Option<&GraphEvent> {
    negative_control_event_from(
        &snapshot.events,
        snapshot.temporal_edges.iter().chain(&snapshot.causal_edges),
    )
}

fn negative_control_event_from<'a, 'b>(
    events: &'a [GraphEvent],
    edges: impl Iterator<Item = &'b GraphTemporalEdge>,
) -> Option<&'a GraphEvent> {
    let sources = edges
        .map(|edge| edge.source_id.as_str())
        .collect::<BTreeSet<_>>();
    events
        .iter()
        .rev()
        .find(|event| !sources.contains(event.id.as_str()))
}

fn lexicon_for(series_id: &str, scope: &ScopeKey) -> Vec<LexiconEntry> {
    let labels: &[&str] = match series_id {
        "series:mother-of-learning" => &["Zorian", "Kirielle", "Xvim", "Zach", "Aranea", "Cyoria"],
        "series:reborn-apocalypse" => &["Micheal", "Sophia", "Shin", "Prime", "Seer", "Godfather"],
        "series:perfect-run" => &["Ryan", "Quicksave", "Len", "Dynamis", "Augustus", "Jasmine"],
        _ => &[],
    };
    labels
        .iter()
        .map(|label| LexiconEntry {
            entity_id: EntityId(format!(
                "entity:{}:{}",
                series_id.trim_start_matches("series:"),
                label.to_ascii_lowercase()
            )),
            label: (*label).to_owned(),
            aliases: Vec::new(),
            kind: None,
            gender: None,
            number: None,
            scope: scope.clone(),
        })
        .collect()
}

fn generation_for(book_id: &str) -> GraphGeneration {
    let bytes = blake3::hash(book_id.as_bytes());
    GraphGeneration(
        u64::from_le_bytes(bytes.as_bytes()[..8].try_into().expect("eight bytes")).max(1),
    )
}

fn event_fact(event_id: &str) -> FactId {
    FactId(format_compact!("fact:{event_id}"))
}

fn wide_interval() -> StoryInterval {
    StoryInterval {
        valid_from: StoryTime(0),
        valid_to_exclusive: None,
    }
}

fn wide_window() -> BiTemporalWindow {
    BiTemporalWindow {
        valid_from: Some(0),
        valid_to: None,
        recorded_from: Some(0),
        recorded_to: None,
    }
}

fn confidence_millis(value: f32) -> u16 {
    (value.clamp(0.0, 1.0) * 1000.0).round() as u16
}

fn count_chapter_headings(bytes: &[u8]) -> usize {
    let mut count = usize::from(bytes.starts_with(b"Chapter "));
    for newline in memchr_iter(b'\n', bytes) {
        if bytes
            .get(newline + 1..)
            .is_some_and(|tail| tail.starts_with(b"Chapter "))
        {
            count += 1;
        }
    }
    count
}

fn sha256_upper(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut out = String::with_capacity(64);
    for byte in digest {
        let _ = write!(out, "{byte:02X}");
    }
    out
}

fn hex_digest(bytes: [u8; 32]) -> String {
    let mut out = String::with_capacity(64);
    for byte in bytes {
        let _ = write!(out, "{byte:02x}");
    }
    out
}

fn micros(duration: std::time::Duration) -> u64 {
    duration.as_micros().min(u128::from(u64::MAX)) as u64
}

fn error(value: impl std::fmt::Display) -> CorpusExperimentError {
    CorpusExperimentError(value.to_string())
}

#[cfg(windows)]
fn process_memory() -> (u64, u64) {
    use std::mem::{size_of, zeroed};
    use windows_sys::Win32::System::ProcessStatus::{
        K32GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS,
    };
    use windows_sys::Win32::System::Threading::GetCurrentProcess;
    // SAFETY: Windows fills a correctly sized process-counter record for the current process.
    unsafe {
        let mut counters: PROCESS_MEMORY_COUNTERS = zeroed();
        counters.cb = size_of::<PROCESS_MEMORY_COUNTERS>() as u32;
        if K32GetProcessMemoryInfo(GetCurrentProcess(), &mut counters, counters.cb) != 0 {
            (
                counters.WorkingSetSize as u64,
                counters.PeakWorkingSetSize as u64,
            )
        } else {
            (0, 0)
        }
    }
}

#[cfg(not(windows))]
fn process_memory() -> (u64, u64) {
    (0, 0)
}

pub fn write_corpus_experiment_receipt(
    receipt: &CorpusExperimentReceipt,
    path: &Path,
) -> ExperimentResult<()> {
    let parent = path
        .parent()
        .ok_or_else(|| CorpusExperimentError("receipt has no parent".into()))?;
    if path.components().any(|part| part.as_os_str() == "sources") {
        return Err(CorpusExperimentError(
            "refusing to write inside protected sources".into(),
        ));
    }
    std::fs::create_dir_all(parent).map_err(error)?;
    let bytes = serde_json::to_vec_pretty(receipt).map_err(error)?;
    std::fs::write(path, bytes).map_err(error)
}

pub fn default_receipt_path(manifest_path: &Path) -> PathBuf {
    manifest_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("receipts")
        .join("real-corpus-run-v1.json")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chapter_counter_requires_line_start() {
        assert_eq!(
            count_chapter_headings(b"Title\nChapter 1: A\nNot Chapter 2\nChapter 2: B"),
            2
        );
    }

    #[test]
    fn negative_control_ignores_events_that_seed_edges() {
        let events = vec![
            GraphEvent {
                id: "event:a".into(),
                ..Default::default()
            },
            GraphEvent {
                id: "event:b".into(),
                ..Default::default()
            },
        ];
        let edges = [GraphTemporalEdge {
            source_id: "event:a".into(),
            target_id: "event:b".into(),
            ..Default::default()
        }];
        assert_eq!(
            negative_control_event_from(&events, edges.iter()).map(|event| event.id.as_str()),
            Some("event:b")
        );
    }
}
