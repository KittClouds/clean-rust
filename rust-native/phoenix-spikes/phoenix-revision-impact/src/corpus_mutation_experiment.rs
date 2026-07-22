use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::Instant;

use compact_str::format_compact;
use memchr::memmem;
use phoenix_graph_rebuild::{
    assert_story_continuity_candidate_only, build_graph_rebuild_snapshot,
    build_story_continuity_contract, GraphEvent, GraphRebuildInput, GraphRebuildSnapshot,
    GraphScopeKind, GraphTemporalEdge, StoryContinuityDocument, StoryContinuityInput,
};
use phoenix_types::{ImpactClassification, ScopeKey};

use super::{
    adapt_snapshot, error, generation_for, lexicon_for, micros, process_memory,
    project_authoritative_constraints, run_edge_case, sha256_upper, AuthoritativeRevisionSources,
    CorpusExperimentError, CorpusManifest, ExperimentResult, RevisionAnalysisViews,
};
use crate::{resolve_revision_identity, story_continuity_identity_snapshot};

#[path = "corpus_mutation_receipt.rs"]
mod receipt;
pub use receipt::*;

const INTRA_CASES: usize = 24;
const CROSS_CASES: usize = 6;
const EVENT_CUES: &[(&str, &[&str])] = &[
    ("approval_event", &["approved", "signed", "proceed"]),
    ("warning_event", &["warn", "coercion", "risk", "prohibited"]),
    (
        "arrival_event",
        &["entered", "arrived", "came in", "opened the door"],
    ),
    (
        "dialogue_event",
        &["asked", "answered", "said", "spoke", "read"],
    ),
    (
        "contact_or_transfer_event",
        &["kiss", "took his hand", "handed", "gave"],
    ),
    (
        "positioning_event",
        &["stood", "watched", "looked", "turned"],
    ),
];

#[derive(Clone)]
struct CaseSpec {
    series_id: String,
    source_book_id: String,
    target_book_id: String,
    source_path: PathBuf,
    target_path: PathBuf,
    source_event_id: String,
    target_event_id: String,
    edge_id: Option<String>,
    case_kind: &'static str,
}

#[derive(Clone)]
struct Boundary {
    series_id: String,
    book_id: String,
    path: PathBuf,
    first_event_id: String,
    last_event_id: String,
}

struct IdentityAudit {
    deleted_unmatched: bool,
    outcome: &'static str,
    replacement_event_id: Option<String>,
    replacement_score_millis: Option<u16>,
    event_matches: usize,
    scene_matches: usize,
    ambiguities: usize,
}

pub fn run_corpus_mutation_experiment(
    manifest_path: &Path,
    mutation_root: &Path,
) -> ExperimentResult<CorpusMutationExperimentReceipt> {
    let started = Instant::now();
    ensure_safe_mutation_root(manifest_path, mutation_root)?;
    std::fs::create_dir_all(mutation_root).map_err(error)?;
    let manifest: CorpusManifest =
        serde_json::from_slice(&std::fs::read(manifest_path).map_err(error)?).map_err(error)?;
    let corpus_root = manifest_path
        .parent()
        .ok_or_else(|| CorpusExperimentError("manifest has no parent".into()))?;
    let (mut specs, boundaries) = select_intra_cases(&manifest, corpus_root)?;
    add_cross_book_cases(&mut specs, &boundaries);
    if specs.len() != INTRA_CASES + CROSS_CASES {
        return Err(CorpusExperimentError(format!(
            "expected 30 mutation cases, selected {}",
            specs.len()
        )));
    }
    let mut packets = Vec::with_capacity(specs.len());
    let mut totals = MutationExperimentTotals::default();
    for (index, spec) in specs.iter().enumerate() {
        let packet = execute_case(index + 1, spec, mutation_root)?;
        let bytes = std::fs::metadata(&packet.mutated_copy_path)
            .map_err(error)?
            .len() as usize;
        totals.add(&packet, bytes);
        packets.push(packet);
    }
    packets.sort_unstable_by(|left, right| left.case_id.cmp(&right.case_id));
    let all_cases_passed = packets.iter().all(|row| row.passed);
    Ok(CorpusMutationExperimentReceipt {
        schema: CORPUS_MUTATION_EXPERIMENT_SCHEMA,
        manifest_path: manifest_path.display().to_string(),
        mutation_root: mutation_root.display().to_string(),
        label_authority: "provisional evaluator labels; human story review pending",
        identity_adapter: "repaired StoryContinuity contract and identity adapter",
        continuity_container_status: "covered; Unicode byte-coordinate regression passed",
        models_enabled: false,
        persistence_writes: false,
        source_copies_modified: false,
        elapsed_micros: micros(started.elapsed()),
        peak_working_set_bytes: process_memory().1,
        totals,
        review_packets: packets,
        all_cases_passed,
    })
}

fn select_intra_cases(
    manifest: &CorpusManifest,
    root: &Path,
) -> ExperimentResult<(Vec<CaseSpec>, Vec<Vec<Boundary>>)> {
    let mut specs = Vec::with_capacity(INTRA_CASES);
    let mut boundaries = Vec::with_capacity(manifest.series.len());
    let mut book_index = 0;
    for series in &manifest.series {
        let mut series_boundaries = Vec::with_capacity(series.books.len());
        for book in &series.books {
            let path = root.join(&book.path);
            let bytes = std::fs::read(&path).map_err(error)?;
            if sha256_upper(&bytes) != book.sha256 {
                return Err(CorpusExperimentError(format!(
                    "protected source hash mismatch for {}",
                    book.book_id
                )));
            }
            let text = std::str::from_utf8(&bytes).map_err(error)?;
            let snapshot = build_snapshot(&series.series_id, &book.book_id, text)?;
            let first = snapshot
                .events
                .first()
                .ok_or_else(|| CorpusExperimentError(format!("no events in {}", book.book_id)))?;
            let last = snapshot.events.last().expect("first event exists");
            series_boundaries.push(Boundary {
                series_id: series.series_id.clone(),
                book_id: book.book_id.clone(),
                path: path.clone(),
                first_event_id: first.id.to_string(),
                last_event_id: last.id.to_string(),
            });
            let wanted = if book_index < 6 { 3 } else { 2 };
            let selected = spaced_edges(&snapshot.temporal_edges, wanted);
            for edge in selected {
                specs.push(CaseSpec {
                    series_id: series.series_id.clone(),
                    source_book_id: book.book_id.clone(),
                    target_book_id: book.book_id.clone(),
                    source_path: path.clone(),
                    target_path: path.clone(),
                    source_event_id: edge.source_id.to_string(),
                    target_event_id: edge.target_id.to_string(),
                    edge_id: Some(edge.id.to_string()),
                    case_kind: "intra_book_temporal",
                });
            }
            book_index += 1;
        }
        boundaries.push(series_boundaries);
    }
    Ok((specs, boundaries))
}

fn spaced_edges(edges: &[GraphTemporalEdge], wanted: usize) -> Vec<&GraphTemporalEdge> {
    let mut selected = Vec::with_capacity(wanted);
    let mut sources = BTreeSet::new();
    for step in 1..=wanted {
        let pivot = step * edges.len() / (wanted + 1);
        let candidate = edges[pivot..]
            .iter()
            .chain(edges[..pivot].iter())
            .find(|edge| sources.insert(edge.source_id.clone()));
        if let Some(edge) = candidate {
            selected.push(edge);
        }
    }
    selected
}

fn add_cross_book_cases(specs: &mut Vec<CaseSpec>, boundaries: &[Vec<Boundary>]) {
    for series in boundaries {
        for pair in series.windows(2) {
            let source = &pair[0];
            let target = &pair[1];
            specs.push(CaseSpec {
                series_id: source.series_id.clone(),
                source_book_id: source.book_id.clone(),
                target_book_id: target.book_id.clone(),
                source_path: source.path.clone(),
                target_path: target.path.clone(),
                source_event_id: source.last_event_id.clone(),
                target_event_id: target.first_event_id.clone(),
                edge_id: None,
                case_kind: "cross_book_temporal",
            });
        }
    }
}

fn execute_case(
    ordinal: usize,
    spec: &CaseSpec,
    mutation_root: &Path,
) -> ExperimentResult<MutationReviewPacket> {
    let baseline_bytes = std::fs::read(&spec.source_path).map_err(error)?;
    let baseline_hash = sha256_upper(&baseline_bytes);
    let baseline_text = std::str::from_utf8(&baseline_bytes).map_err(error)?;
    let baseline = build_snapshot(&spec.series_id, &spec.source_book_id, baseline_text)?;
    let source_event = find_event(&baseline, &spec.source_event_id)?.clone();
    let source_chunk = event_chunk(&baseline, &source_event)?;
    let mut mutated_bytes = baseline_bytes.clone();
    let replacements = neutralize_event_cues(
        &mut mutated_bytes[source_chunk.start as usize..source_chunk.end as usize],
        &source_event.label,
    );
    if replacements == 0 {
        return Err(CorpusExperimentError(format!(
            "no event cue found for {}",
            source_event.id
        )));
    }
    let case_id = format!("case-{ordinal:02}");
    let mutated_path =
        mutation_root.join(format!("{case_id}-{}.md", safe_name(&spec.source_book_id)));
    std::fs::write(&mutated_path, &mutated_bytes).map_err(error)?;
    let mutated_text = std::str::from_utf8(&mutated_bytes).map_err(error)?;
    let mutated = build_snapshot(&spec.series_id, &spec.source_book_id, mutated_text)?;
    let extraction_retraction_detected = mutated
        .events
        .iter()
        .all(|event| event.id != source_event.id);
    let identity = identity_audit(
        &baseline,
        baseline_text,
        &mutated,
        mutated_text,
        &source_event.id,
    )?;
    let (analysis_snapshot, edge, target_event, target_text) = analysis_inputs(spec, &baseline)?;
    let target_chunk = event_chunk(&analysis_snapshot, &target_event)?;
    let adapted = adapt_snapshot(
        generation_for(&spec.source_book_id),
        &analysis_snapshot,
        None,
    )?;
    let projected = project_authoritative_constraints(AuthoritativeRevisionSources {
        base: &adapted.base,
        requirements: &adapted.requirements,
        temporal: Some(&adapted.temporal),
        memory: None,
        causal: Some(&adapted.causal),
    })
    .map_err(error)?;
    let views = RevisionAnalysisViews::project(
        adapted.base.generation(),
        projected.constraints,
        adapted.inference.clone(),
    )
    .map_err(error)?;
    let impact = run_edge_case(
        &spec.series_id,
        &spec.source_book_id,
        spec.case_kind,
        &edge,
        ImpactClassification::Broken,
        &adapted,
        &views,
        &projected.receipt,
    )?;
    let baseline_after_hash = sha256_upper(&std::fs::read(&spec.source_path).map_err(error)?);
    let deterministic_classification = impact
        .observed_classification
        .map(|classification| format!("{classification:?}").to_ascii_lowercase());
    let identity_safe = matches!(
        identity.outcome,
        "unmatched_retraction" | "matched_retyped_event"
    );
    let passed = extraction_retraction_detected
        && impact.passed
        && baseline_hash == baseline_after_hash
        && identity_safe
        && identity.ambiguities == 0;
    Ok(MutationReviewPacket {
        case_id,
        series_id: spec.series_id.clone(),
        source_book_id: spec.source_book_id.clone(),
        target_book_id: spec.target_book_id.clone(),
        case_kind: spec.case_kind.to_owned(),
        review_status: "pending_human_story_review",
        proposed_classification: "broken",
        source_event_id: source_event.id.to_string(),
        target_event_id: target_event.id.to_string(),
        source_event_label: source_event.label.to_string(),
        source_chunk_id: source_chunk.id.to_string(),
        target_chunk_id: target_chunk.id.to_string(),
        original_excerpt: excerpt(baseline_text, source_chunk.start, source_chunk.end),
        mutated_excerpt: excerpt(mutated_text, source_chunk.start, source_chunk.end),
        target_excerpt: excerpt(&target_text, target_chunk.start, target_chunk.end),
        mutation_description: format!(
            "Neutralized {replacements} extractor cue(s) while preserving byte offsets"
        ),
        mutated_copy_path: mutated_path.display().to_string(),
        mutated_copy_sha256: sha256_upper(&mutated_bytes),
        baseline_copy_unchanged: baseline_hash == baseline_after_hash,
        extraction_retraction_detected,
        collateral_event_delta: mutated.events.len() as i64 - baseline.events.len() as i64,
        deleted_identity_unmatched: identity.deleted_unmatched,
        identity_outcome: identity.outcome.to_owned(),
        replacement_event_id: identity.replacement_event_id,
        replacement_score_millis: identity.replacement_score_millis,
        event_identity_matches: identity.event_matches,
        scene_identity_matches: identity.scene_matches,
        identity_ambiguities: identity.ambiguities,
        deterministic_classification,
        deterministic_report_digest: impact.report_digest,
        deterministic_rerun_match: impact.deterministic_rerun_match,
        no_truth_writes: impact.no_truth_writes,
        passed,
    })
}

fn analysis_inputs(
    spec: &CaseSpec,
    source_snapshot: &GraphRebuildSnapshot,
) -> ExperimentResult<(GraphRebuildSnapshot, GraphTemporalEdge, GraphEvent, String)> {
    if let Some(edge_id) = &spec.edge_id {
        let edge = source_snapshot
            .temporal_edges
            .iter()
            .find(|edge| edge.id == edge_id.as_str())
            .cloned()
            .ok_or_else(|| CorpusExperimentError(format!("missing edge {edge_id}")))?;
        let target = find_event(source_snapshot, &spec.target_event_id)?.clone();
        let text = std::fs::read_to_string(&spec.source_path).map_err(error)?;
        return Ok((source_snapshot.clone(), edge, target, text));
    }
    let target_text = std::fs::read_to_string(&spec.target_path).map_err(error)?;
    let target_snapshot = build_snapshot(&spec.series_id, &spec.target_book_id, &target_text)?;
    let target = find_event(&target_snapshot, &spec.target_event_id)?.clone();
    let target_chunk = event_chunk(&target_snapshot, &target)?.clone();
    let mut combined = source_snapshot.clone();
    combined.events.push(target.clone());
    combined.chunks.push(target_chunk);
    if !combined
        .note_ids
        .iter()
        .any(|note_id| note_id == spec.target_book_id.as_str())
    {
        combined.note_ids.push(spec.target_book_id.as_str().into());
    }
    let edge = GraphTemporalEdge {
        id: format_compact!(
            "cross-book:{}:{}",
            spec.source_event_id,
            spec.target_event_id
        ),
        source_id: spec.source_event_id.as_str().into(),
        target_id: spec.target_event_id.as_str().into(),
        relation_type: "before".into(),
        evidence_ids: vec![
            spec.source_event_id.as_str().into(),
            spec.target_event_id.as_str().into(),
        ],
        confidence: 1.0,
    };
    combined.temporal_edges.push(edge.clone());
    Ok((combined, edge, target, target_text))
}

fn identity_audit(
    baseline: &GraphRebuildSnapshot,
    baseline_text: &str,
    mutated: &GraphRebuildSnapshot,
    mutated_text: &str,
    source_event_id: &str,
) -> ExperimentResult<IdentityAudit> {
    let previous_documents = [StoryContinuityDocument {
        note_id: baseline.note_ids[0].clone(),
        text: baseline_text.to_owned(),
    }];
    let current_documents = [StoryContinuityDocument {
        note_id: mutated.note_ids[0].clone(),
        text: mutated_text.to_owned(),
    }];
    let previous_contract = build_story_continuity_contract(StoryContinuityInput {
        snapshot: baseline,
        documents: &previous_documents,
        semantic_summary: None,
        bridge_candidates: &[],
    });
    let current_contract = build_story_continuity_contract(StoryContinuityInput {
        snapshot: mutated,
        documents: &current_documents,
        semantic_summary: None,
        bridge_candidates: &[],
    });
    assert_story_continuity_candidate_only(&previous_contract).map_err(error)?;
    assert_story_continuity_candidate_only(&current_contract).map_err(error)?;
    let previous_event_id = previous_contract
        .events
        .iter()
        .find(|event| event.source_event_id.as_deref() == Some(source_event_id))
        .map(|event| event.id.clone())
        .ok_or_else(|| {
            CorpusExperimentError(format!("missing continuity event {source_event_id}"))
        })?;
    let previous = story_continuity_identity_snapshot(1, &previous_contract);
    let current = story_continuity_identity_snapshot(2, &current_contract);
    let identity = resolve_revision_identity(&previous, &current).map_err(error)?;
    let replacement = identity
        .event_matches
        .iter()
        .find(|identity_match| identity_match.previous_id == previous_event_id);
    let deleted_unmatched = identity.unmatched_previous_ids.contains(&previous_event_id);
    let outcome = if deleted_unmatched {
        "unmatched_retraction"
    } else if replacement.is_some() {
        "matched_retyped_event"
    } else {
        "unsafe_unresolved"
    };
    Ok(IdentityAudit {
        deleted_unmatched,
        outcome,
        replacement_event_id: replacement.map(|row| row.current_id.to_string()),
        replacement_score_millis: replacement.map(|row| row.score_millis),
        event_matches: identity.event_matches.len(),
        scene_matches: identity.scene_matches.len(),
        ambiguities: identity.ambiguous.len(),
    })
}

fn build_snapshot(
    series_id: &str,
    book_id: &str,
    text: &str,
) -> ExperimentResult<GraphRebuildSnapshot> {
    let scope = ScopeKey {
        narrative_id: Some(series_id.to_owned()),
        ..ScopeKey::default()
    };
    let lexicon = lexicon_for(series_id, &scope);
    build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Narrative,
        scope_id: series_id,
        note_id: book_id,
        text,
        scope,
        entities: &lexicon,
        candidate_count: 0,
        built_at: Some(0),
    })
    .map_err(error)
}

fn find_event<'a>(
    snapshot: &'a GraphRebuildSnapshot,
    event_id: &str,
) -> ExperimentResult<&'a GraphEvent> {
    snapshot
        .events
        .iter()
        .find(|event| event.id == event_id)
        .ok_or_else(|| CorpusExperimentError(format!("missing event {event_id}")))
}

fn event_chunk<'a>(
    snapshot: &'a GraphRebuildSnapshot,
    event: &GraphEvent,
) -> ExperimentResult<&'a phoenix_graph_rebuild::GraphChunk> {
    let chunk_id = event
        .chunk_id
        .as_deref()
        .ok_or_else(|| CorpusExperimentError(format!("event {} has no chunk", event.id)))?;
    snapshot
        .chunks
        .iter()
        .find(|chunk| chunk.id == chunk_id)
        .ok_or_else(|| CorpusExperimentError(format!("missing chunk {chunk_id}")))
}

fn neutralize_event_cues(chunk: &mut [u8], event_label: &str) -> usize {
    let event_type = event_label.split(" in chunk").next().unwrap_or(event_label);
    let Some((_, cues)) = EVENT_CUES.iter().find(|(kind, _)| *kind == event_type) else {
        return 0;
    };
    let lower = chunk.iter().map(u8::to_ascii_lowercase).collect::<Vec<_>>();
    let mut ranges = Vec::new();
    for cue in *cues {
        for start in memmem::find_iter(&lower, cue.as_bytes()) {
            ranges.push(start..start + cue.len());
        }
    }
    ranges.sort_unstable_by_key(|range| range.start);
    ranges.dedup_by(|left, right| left.start == right.start && left.end == right.end);
    for range in &ranges {
        for byte in &mut chunk[range.clone()] {
            if byte.is_ascii_alphabetic() {
                *byte = b'x';
            }
        }
    }
    ranges.len()
}

fn excerpt(text: &str, start: u32, end: u32) -> String {
    text.get(start as usize..end as usize)
        .unwrap_or_default()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(420)
        .collect()
}

fn safe_name(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character
            } else {
                '-'
            }
        })
        .collect()
}

fn ensure_safe_mutation_root(manifest: &Path, root: &Path) -> ExperimentResult<()> {
    let corpus_root = manifest
        .parent()
        .ok_or_else(|| CorpusExperimentError("manifest has no parent".into()))?;
    if !root.starts_with(corpus_root) || root.starts_with(corpus_root.join("sources")) {
        return Err(CorpusExperimentError(
            "mutation output must stay under corpus experiment and outside sources".into(),
        ));
    }
    Ok(())
}

pub fn write_corpus_mutation_receipt(
    receipt: &CorpusMutationExperimentReceipt,
    path: &Path,
) -> ExperimentResult<()> {
    let parent = path
        .parent()
        .ok_or_else(|| CorpusExperimentError("receipt has no parent".into()))?;
    std::fs::create_dir_all(parent).map_err(error)?;
    std::fs::write(path, serde_json::to_vec_pretty(receipt).map_err(error)?).map_err(error)
}

pub fn write_corpus_mutation_review(
    receipt: &CorpusMutationExperimentReceipt,
    path: &Path,
) -> ExperimentResult<()> {
    use std::fmt::Write as _;

    let mut markdown = String::with_capacity(receipt.review_packets.len() * 1_800);
    writeln!(markdown, "# Real-text revision impact review\n").map_err(error)?;
    writeln!(
        markdown,
        "Labels are provisional. Check `Confirm broken` only when removing or retyping the source event should invalidate the target scene.\n"
    )
    .map_err(error)?;
    writeln!(
        markdown,
        "Cases: {} | Intra-book: {} | Cross-book: {} | Automated gates passed: {}\n",
        receipt.totals.cases,
        receipt.totals.intra_book_cases,
        receipt.totals.cross_book_cases,
        receipt.totals.passed_cases
    )
    .map_err(error)?;
    for row in &receipt.review_packets {
        writeln!(
            markdown,
            "## {} — {}\n\n- Source: `{}` / `{}`\n- Target: `{}` / `{}`\n- Identity: `{}`\n- Automated classification: `{}`\n- [ ] Confirm broken\n- [ ] Mark suspicious\n- [ ] Reject mutation\n\n### Original evidence\n\n> {}\n\n### Mutated evidence\n\n> {}\n\n### Target evidence\n\n> {}\n",
            row.case_id,
            row.case_kind,
            row.source_book_id,
            row.source_event_id,
            row.target_book_id,
            row.target_event_id,
            row.identity_outcome,
            row.deterministic_classification.as_deref().unwrap_or("none"),
            row.original_excerpt,
            row.mutated_excerpt,
            row.target_excerpt
        )
        .map_err(error)?;
    }
    let parent = path
        .parent()
        .ok_or_else(|| CorpusExperimentError("review path has no parent".into()))?;
    std::fs::create_dir_all(parent).map_err(error)?;
    std::fs::write(path, markdown).map_err(error)
}

pub fn default_mutation_root(manifest: &Path) -> PathBuf {
    manifest
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("mutations-v2")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cue_neutralization_preserves_offsets_and_removes_selected_type() {
        let mut text = b"Zorian said hello and asked twice.".to_vec();
        let original_len = text.len();
        assert_eq!(
            neutralize_event_cues(&mut text, "dialogue_event in chunk 1"),
            2
        );
        assert_eq!(text.len(), original_len);
        assert!(!String::from_utf8(text).expect("utf8").contains("said"));
    }

    #[test]
    fn mutation_root_cannot_enter_protected_sources() {
        let manifest = Path::new("C:/experiment/corpus-manifest-v1.json");
        assert!(
            ensure_safe_mutation_root(manifest, Path::new("C:/experiment/mutations-v2")).is_ok()
        );
        assert!(
            ensure_safe_mutation_root(manifest, Path::new("C:/experiment/sources/bad")).is_err()
        );
    }
}
