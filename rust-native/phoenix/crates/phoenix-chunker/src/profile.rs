use memchr::memmem;
use serde::{Deserialize, Serialize};
use smallvec::SmallVec;

const PROFILE_COUNT: usize = 9;
const MAX_SIGNALS: usize = 24;
const MAX_REGIONS: usize = 192;
const TARGET_REGION_BYTES: usize = 4_096;
const MAX_REGION_BYTES: usize = 6_144;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DocumentProfileKind {
    ProseFiction,
    ResearchPaper,
    LegalPolicy,
    TechnicalDocs,
    MeetingNotes,
    CodeHeavyNotes,
    TradingSystemSpecs,
    ReferenceArticle,
    MixedNotebook,
}

impl DocumentProfileKind {
    const ALL: [Self; PROFILE_COUNT] = [
        Self::ProseFiction,
        Self::ResearchPaper,
        Self::LegalPolicy,
        Self::TechnicalDocs,
        Self::MeetingNotes,
        Self::CodeHeavyNotes,
        Self::TradingSystemSpecs,
        Self::ReferenceArticle,
        Self::MixedNotebook,
    ];

    fn index(self) -> usize {
        Self::ALL
            .iter()
            .position(|profile| *profile == self)
            .unwrap_or(0)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentProfileInput {
    pub note_id: String,
    pub text: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentProfileRequest {
    pub documents: Vec<DocumentProfileInput>,
    pub built_at: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentProfileWeight {
    pub profile: DocumentProfileKind,
    pub score: f32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentProfileSignal {
    pub id: String,
    pub profile: DocumentProfileKind,
    pub cue: String,
    pub occurrences: u32,
    pub contribution: f32,
    pub start: usize,
    pub end: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentUnitWeight {
    pub kind: String,
    pub weight: f32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentRegionProfile {
    pub id: String,
    pub note_id: String,
    pub start: usize,
    pub end: usize,
    pub dominant_profile: DocumentProfileKind,
    pub confidence: f32,
    pub weights: Vec<DocumentProfileWeight>,
    pub signals: Vec<DocumentProfileSignal>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentProfile {
    pub note_id: String,
    pub dominant_profile: DocumentProfileKind,
    pub confidence: f32,
    pub weights: Vec<DocumentProfileWeight>,
    pub unit_weights: Vec<DocumentUnitWeight>,
    pub signals: Vec<DocumentProfileSignal>,
    pub regions: Vec<DocumentRegionProfile>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentProfileCounters {
    pub documents: usize,
    pub regions: usize,
    pub signals: usize,
    pub native_profiles: usize,
    pub by_profile: std::collections::BTreeMap<String, usize>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentProfileSummary {
    pub schema_version: String,
    pub source: String,
    pub built_at: u64,
    pub profiles: Vec<DocumentProfile>,
    pub counters: DocumentProfileCounters,
}

#[derive(Clone, Copy)]
struct Cue {
    profile: DocumentProfileKind,
    needle: &'static str,
    weight: f32,
}

const CUES: &[Cue] = &[
    cue(DocumentProfileKind::ProseFiction, "chapter ", 2.4),
    cue(DocumentProfileKind::ProseFiction, "scene ", 2.2),
    cue(DocumentProfileKind::ProseFiction, "said", 0.65),
    cue(DocumentProfileKind::ProseFiction, "asked", 0.6),
    cue(DocumentProfileKind::ProseFiction, "replied", 0.65),
    cue(DocumentProfileKind::ResearchPaper, "abstract", 2.0),
    cue(DocumentProfileKind::ResearchPaper, "method", 1.5),
    cue(DocumentProfileKind::ResearchPaper, "results", 1.6),
    cue(DocumentProfileKind::ResearchPaper, "discussion", 1.2),
    cue(DocumentProfileKind::ResearchPaper, "we show", 1.4),
    cue(DocumentProfileKind::ResearchPaper, "et al.", 1.4),
    cue(DocumentProfileKind::LegalPolicy, "shall", 1.6),
    cue(DocumentProfileKind::LegalPolicy, "pursuant", 1.8),
    cue(DocumentProfileKind::LegalPolicy, "herein", 1.6),
    cue(DocumentProfileKind::LegalPolicy, "compliance", 1.2),
    cue(DocumentProfileKind::LegalPolicy, "prohibited", 1.5),
    cue(DocumentProfileKind::TechnicalDocs, "api", 1.1),
    cue(DocumentProfileKind::TechnicalDocs, "install", 1.2),
    cue(DocumentProfileKind::TechnicalDocs, "configure", 1.3),
    cue(DocumentProfileKind::TechnicalDocs, "architecture", 1.0),
    cue(DocumentProfileKind::TechnicalDocs, "input", 0.7),
    cue(DocumentProfileKind::TechnicalDocs, "output", 0.7),
    cue(DocumentProfileKind::MeetingNotes, "agenda", 1.7),
    cue(DocumentProfileKind::MeetingNotes, "attendees", 1.8),
    cue(DocumentProfileKind::MeetingNotes, "action item", 1.8),
    cue(DocumentProfileKind::MeetingNotes, "next steps", 1.5),
    cue(DocumentProfileKind::MeetingNotes, "owner:", 1.4),
    cue(DocumentProfileKind::MeetingNotes, "decision:", 1.4),
    cue(DocumentProfileKind::CodeHeavyNotes, "```", 2.4),
    cue(DocumentProfileKind::CodeHeavyNotes, "fn ", 1.4),
    cue(DocumentProfileKind::CodeHeavyNotes, "class ", 1.1),
    cue(DocumentProfileKind::CodeHeavyNotes, "const ", 1.1),
    cue(DocumentProfileKind::CodeHeavyNotes, "import ", 1.2),
    cue(DocumentProfileKind::TradingSystemSpecs, "entry", 1.0),
    cue(DocumentProfileKind::TradingSystemSpecs, "exit", 1.0),
    cue(DocumentProfileKind::TradingSystemSpecs, "stop loss", 1.8),
    cue(DocumentProfileKind::TradingSystemSpecs, "take profit", 1.8),
    cue(
        DocumentProfileKind::TradingSystemSpecs,
        "position size",
        1.6,
    ),
    cue(DocumentProfileKind::TradingSystemSpecs, "backtest", 1.5),
    cue(DocumentProfileKind::TradingSystemSpecs, "risk", 0.8),
    cue(DocumentProfileKind::ReferenceArticle, "overview", 1.4),
    cue(DocumentProfileKind::ReferenceArticle, "learn more", 1.5),
    cue(DocumentProfileKind::ReferenceArticle, "according to", 1.2),
    cue(DocumentProfileKind::ReferenceArticle, "researchers", 0.8),
    cue(DocumentProfileKind::ReferenceArticle, "scientists", 0.8),
    cue(DocumentProfileKind::ReferenceArticle, "for example", 0.7),
    cue(DocumentProfileKind::ReferenceArticle, "refers to", 0.9),
    cue(DocumentProfileKind::ReferenceArticle, "is known as", 0.9),
    cue(DocumentProfileKind::ReferenceArticle, "standard", 0.8),
];

const fn cue(profile: DocumentProfileKind, needle: &'static str, weight: f32) -> Cue {
    Cue {
        profile,
        needle,
        weight,
    }
}

pub fn classify_document_profiles(request: &DocumentProfileRequest) -> DocumentProfileSummary {
    let profiles = request
        .documents
        .iter()
        .map(|document| classify_document(&document.note_id, &document.text))
        .collect::<Vec<_>>();
    let mut by_profile = std::collections::BTreeMap::new();
    for profile in &profiles {
        *by_profile
            .entry(profile_name(profile.dominant_profile).to_owned())
            .or_insert(0) += 1;
    }
    DocumentProfileSummary {
        schema_version: "phoenix-document-profile/v1".to_owned(),
        source: "native_rust".to_owned(),
        built_at: request.built_at,
        counters: DocumentProfileCounters {
            documents: profiles.len(),
            regions: profiles.iter().map(|profile| profile.regions.len()).sum(),
            signals: profiles.iter().map(|profile| profile.signals.len()).sum(),
            native_profiles: profiles.len(),
            by_profile,
        },
        profiles,
    }
}

fn classify_document(note_id: &str, text: &str) -> DocumentProfile {
    let classified = classify_span(note_id, text, 0, text.len(), true);
    let regions = region_ranges(text)
        .into_iter()
        .take(MAX_REGIONS)
        .map(|(start, end)| {
            let region = classify_span(note_id, &text[start..end], start, end, false);
            DocumentRegionProfile {
                id: format!("{note_id}:profile-region:{start}:{end}"),
                note_id: note_id.to_owned(),
                start,
                end,
                dominant_profile: region.dominant_profile,
                confidence: region.confidence,
                weights: region.weights,
                signals: region.signals,
            }
        })
        .collect();
    DocumentProfile {
        note_id: note_id.to_owned(),
        dominant_profile: classified.dominant_profile,
        confidence: classified.confidence,
        unit_weights: blended_unit_weights(&classified.weights),
        weights: classified.weights,
        signals: classified.signals,
        regions,
    }
}

struct ClassifiedSpan {
    dominant_profile: DocumentProfileKind,
    confidence: f32,
    weights: Vec<DocumentProfileWeight>,
    signals: Vec<DocumentProfileSignal>,
}

fn classify_span(
    note_id: &str,
    text: &str,
    start: usize,
    end: usize,
    include_mixed: bool,
) -> ClassifiedSpan {
    let lower = text.to_ascii_lowercase();
    let bytes = lower.as_bytes();
    let mut raw = [0.35_f32; PROFILE_COUNT];
    raw[DocumentProfileKind::ReferenceArticle.index()] = if include_mixed { 0.55 } else { 0.45 };
    raw[DocumentProfileKind::MixedNotebook.index()] = if include_mixed { 0.12 } else { 0.5 };
    let mut signals: SmallVec<[DocumentProfileSignal; 16]> = SmallVec::new();

    for entry in CUES {
        let count = count_bounded(bytes, entry.needle.trim().as_bytes());
        if count == 0 {
            continue;
        }
        let contribution = entry.weight * (count as f32).sqrt();
        raw[entry.profile.index()] += contribution;
        if signals.len() < MAX_SIGNALS {
            signals.push(DocumentProfileSignal {
                id: format!(
                    "{note_id}:profile-signal:{}:{}",
                    profile_name(entry.profile),
                    signals.len()
                ),
                profile: entry.profile,
                cue: entry.needle.trim().to_owned(),
                occurrences: count.min(u32::MAX as usize) as u32,
                contribution: round3(contribution),
                start,
                end,
            });
        }
    }
    add_shape_scores(text, &lower, start, end, &mut raw, &mut signals, note_id);
    if include_mixed {
        let active = raw[..PROFILE_COUNT - 1]
            .iter()
            .filter(|score| **score >= 1.6)
            .count();
        let mut ranked = raw[..PROFILE_COUNT - 1].to_vec();
        ranked.sort_by(|left, right| right.total_cmp(left));
        let closeness = ranked.get(1).copied().unwrap_or(0.0)
            / ranked.first().copied().unwrap_or(1.0).max(0.01);
        raw[DocumentProfileKind::MixedNotebook.index()] +=
            active.saturating_sub(1) as f32 * 0.9 + closeness * 0.8;
    }
    let weights = normalize_weights(raw);
    let (dominant_profile, top, second) = dominant(&weights);
    ClassifiedSpan {
        dominant_profile,
        confidence: round3((top + (top - second).max(0.0) * 0.7).clamp(0.0, 1.0)),
        weights,
        signals: signals.into_vec(),
    }
}

fn add_shape_scores(
    text: &str,
    lower: &str,
    start: usize,
    end: usize,
    raw: &mut [f32; PROFILE_COUNT],
    signals: &mut SmallVec<[DocumentProfileSignal; 16]>,
    note_id: &str,
) {
    let dialogue_lines = text
        .lines()
        .filter(|line| {
            let line = line.trim_start();
            line.starts_with('"') || line.starts_with('“') || line.starts_with("â€œ")
        })
        .count();
    let code_lines = lower
        .lines()
        .filter(|line| {
            let line = line.trim_start();
            line.starts_with("fn ")
                || line.starts_with("class ")
                || line.starts_with("const ")
                || line.starts_with("let ")
                || line.starts_with("def ")
                || line.ends_with(';')
        })
        .count();
    let checklist = lower
        .lines()
        .filter(|line| {
            let line = line.trim_start();
            line.starts_with("- [") || line.starts_with("* [")
        })
        .count();
    let citations = memmem::find_iter(lower.as_bytes(), b"(")
        .count()
        .min(memmem::find_iter(lower.as_bytes(), b")").count());
    let headings = lower
        .lines()
        .filter(|line| line.trim_start().starts_with('#'))
        .count();
    add_shape_signal(
        raw,
        signals,
        note_id,
        DocumentProfileKind::ProseFiction,
        "dialogue-shaped lines",
        dialogue_lines,
        0.45,
        start,
        end,
    );
    add_shape_signal(
        raw,
        signals,
        note_id,
        DocumentProfileKind::CodeHeavyNotes,
        "code-shaped lines",
        code_lines,
        0.85,
        start,
        end,
    );
    add_shape_signal(
        raw,
        signals,
        note_id,
        DocumentProfileKind::MeetingNotes,
        "checklist lines",
        checklist,
        0.75,
        start,
        end,
    );
    add_shape_signal(
        raw,
        signals,
        note_id,
        DocumentProfileKind::ReferenceArticle,
        "sectioned explanatory prose",
        headings,
        0.55,
        start,
        end,
    );
    if lower.contains("references") || lower.contains("bibliography") {
        let research_shaped =
            lower.contains("abstract") || lower.contains("method") || lower.contains("results");
        add_shape_signal(
            raw,
            signals,
            note_id,
            if research_shaped {
                DocumentProfileKind::ResearchPaper
            } else {
                DocumentProfileKind::ReferenceArticle
            },
            "citation structure",
            citations.max(1),
            0.32,
            start,
            end,
        );
    }
}

fn add_shape_signal(
    raw: &mut [f32; PROFILE_COUNT],
    signals: &mut SmallVec<[DocumentProfileSignal; 16]>,
    note_id: &str,
    profile: DocumentProfileKind,
    cue: &str,
    count: usize,
    weight: f32,
    start: usize,
    end: usize,
) {
    if count == 0 {
        return;
    }
    let contribution = weight * (count as f32).sqrt();
    raw[profile.index()] += contribution;
    if signals.len() < MAX_SIGNALS {
        signals.push(DocumentProfileSignal {
            id: format!(
                "{note_id}:profile-shape:{}:{}",
                profile_name(profile),
                signals.len()
            ),
            profile,
            cue: cue.to_owned(),
            occurrences: count.min(u32::MAX as usize) as u32,
            contribution: round3(contribution),
            start,
            end,
        });
    }
}

fn normalize_weights(raw: [f32; PROFILE_COUNT]) -> Vec<DocumentProfileWeight> {
    let total = raw.iter().sum::<f32>().max(f32::EPSILON);
    let mut weights = DocumentProfileKind::ALL
        .iter()
        .enumerate()
        .map(|(index, profile)| DocumentProfileWeight {
            profile: *profile,
            score: round3(raw[index] / total),
        })
        .collect::<Vec<_>>();
    weights.sort_by(|left, right| right.score.total_cmp(&left.score));
    weights
}

fn dominant(weights: &[DocumentProfileWeight]) -> (DocumentProfileKind, f32, f32) {
    let first = weights
        .first()
        .map(|row| (row.profile, row.score))
        .unwrap_or((DocumentProfileKind::MixedNotebook, 0.0));
    let second = weights.get(1).map(|row| row.score).unwrap_or(0.0);
    (first.0, first.1, second)
}

fn region_ranges(text: &str) -> Vec<(usize, usize)> {
    let paragraphs = paragraph_ranges(text);
    if paragraphs.is_empty() {
        return if text.trim().is_empty() {
            Vec::new()
        } else {
            vec![(0, text.len())]
        };
    }
    let mut regions = Vec::with_capacity(paragraphs.len().min(MAX_REGIONS));
    let mut region_start = paragraphs[0].0;
    let mut region_end = paragraphs[0].1;
    for &(start, end) in paragraphs.iter().skip(1) {
        let current_len = region_end.saturating_sub(region_start);
        let extended_len = end.saturating_sub(region_start);
        if is_region_boundary(&text[start..end])
            || current_len >= TARGET_REGION_BYTES
            || extended_len > MAX_REGION_BYTES
        {
            regions.push((region_start, region_end));
            region_start = start;
        }
        region_end = end;
    }
    regions.push((region_start, region_end));
    regions
}

fn is_region_boundary(paragraph: &str) -> bool {
    let first_line = paragraph.lines().next().unwrap_or_default().trim_start();
    if first_line.starts_with('#') {
        return true;
    }
    let lower = first_line.to_ascii_lowercase();
    lower.starts_with("chapter ") || lower.starts_with("scene ")
}

fn paragraph_ranges(text: &str) -> Vec<(usize, usize)> {
    let mut paragraphs = Vec::new();
    let mut current_start = None;
    let mut offset = 0usize;
    for line in text.split_inclusive('\n') {
        let line_start = offset;
        let line_end = offset + line.len();
        let mut content_end = line_end - line.ends_with('\n') as usize;
        if content_end > line_start && text.as_bytes()[content_end - 1] == b'\r' {
            content_end -= 1;
        }
        if text[line_start..content_end].trim().is_empty() {
            if let Some(start) = current_start.take() {
                push_trimmed_range(text, start, line_start, &mut paragraphs);
            }
        } else if current_start.is_none() {
            current_start = Some(line_start);
        }
        offset = line_end;
    }
    if let Some(start) = current_start {
        push_trimmed_range(text, start, text.len(), &mut paragraphs);
    }
    paragraphs
}

fn count_bounded(haystack: &[u8], needle: &[u8]) -> usize {
    if needle.is_empty() {
        return 0;
    }
    memmem::find_iter(haystack, needle)
        .filter(|index| {
            let before = index.checked_sub(1).and_then(|value| haystack.get(value));
            let after = haystack.get(index + needle.len());
            before.is_none_or(|byte| !is_word_byte(*byte))
                && after.is_none_or(|byte| !is_word_byte(*byte))
        })
        .count()
}

fn is_word_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

fn push_trimmed_range(
    text: &str,
    mut start: usize,
    mut end: usize,
    ranges: &mut Vec<(usize, usize)>,
) {
    let bytes = text.as_bytes();
    while start < end && bytes[start].is_ascii_whitespace() {
        start += 1;
    }
    while end > start && bytes[end - 1].is_ascii_whitespace() {
        end -= 1;
    }
    if end > start {
        ranges.push((start, end));
    }
}

fn blended_unit_weights(weights: &[DocumentProfileWeight]) -> Vec<DocumentUnitWeight> {
    const KINDS: &[&str] = &[
        "chapter",
        "scene",
        "dialogue_block",
        "action_block",
        "claim",
        "evidence",
        "definition",
        "example",
        "contrast",
        "method",
        "result",
        "instruction",
        "decision",
        "question",
        "event",
        "state_change",
        "relation_bundle",
        "procedure_step",
        "n_ary_claim",
        "code_block",
        "citation_span",
        "parent_chunk",
        "cross_doc_topic_packet",
    ];
    KINDS
        .iter()
        .map(|kind| {
            let weight = weights
                .iter()
                .map(|row| row.score * profile_unit_weight(row.profile, kind))
                .sum::<f32>();
            DocumentUnitWeight {
                kind: (*kind).to_owned(),
                weight: round3(weight.clamp(0.55, 1.55)),
            }
        })
        .collect()
}

fn profile_unit_weight(profile: DocumentProfileKind, kind: &str) -> f32 {
    match profile {
        DocumentProfileKind::ProseFiction => match kind {
            "chapter" | "scene" => 1.5,
            "dialogue_block" | "action_block" => 1.4,
            "event" | "state_change" => 1.25,
            _ => 0.9,
        },
        DocumentProfileKind::ResearchPaper => match kind {
            "method" | "result" => 1.5,
            "claim" | "evidence" | "citation_span" => 1.4,
            "n_ary_claim" => 1.25,
            _ => 0.9,
        },
        DocumentProfileKind::LegalPolicy => match kind {
            "definition" | "decision" => 1.4,
            "claim" | "evidence" | "n_ary_claim" => 1.2,
            "instruction" => 1.3,
            _ => 0.92,
        },
        DocumentProfileKind::TechnicalDocs => match kind {
            "instruction" | "procedure_step" | "code_block" => 1.5,
            "definition" | "example" => 1.25,
            _ => 0.92,
        },
        DocumentProfileKind::MeetingNotes => match kind {
            "decision" | "question" | "instruction" => 1.45,
            "event" | "procedure_step" => 1.2,
            _ => 0.9,
        },
        DocumentProfileKind::CodeHeavyNotes => match kind {
            "code_block" => 1.55,
            "instruction" | "procedure_step" | "example" => 1.35,
            _ => 0.85,
        },
        DocumentProfileKind::TradingSystemSpecs => match kind {
            "instruction" | "procedure_step" | "state_change" => 1.45,
            "event" | "relation_bundle" => 1.25,
            _ => 0.9,
        },
        DocumentProfileKind::ReferenceArticle => match kind {
            "definition" | "example" => 1.4,
            "claim" | "evidence" | "relation_bundle" => 1.3,
            "n_ary_claim" | "citation_span" => 1.2,
            _ => 0.92,
        },
        DocumentProfileKind::MixedNotebook => 1.0,
    }
}

fn profile_name(profile: DocumentProfileKind) -> &'static str {
    match profile {
        DocumentProfileKind::ProseFiction => "prose_fiction",
        DocumentProfileKind::ResearchPaper => "research_paper",
        DocumentProfileKind::LegalPolicy => "legal_policy",
        DocumentProfileKind::TechnicalDocs => "technical_docs",
        DocumentProfileKind::MeetingNotes => "meeting_notes",
        DocumentProfileKind::CodeHeavyNotes => "code_heavy_notes",
        DocumentProfileKind::TradingSystemSpecs => "trading_system_specs",
        DocumentProfileKind::ReferenceArticle => "reference_article",
        DocumentProfileKind::MixedNotebook => "mixed_notebook",
    }
}

fn round3(value: f32) -> f32 {
    (value * 1000.0).round() / 1000.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn research_profile_prioritizes_method_result_and_evidence() {
        let summary = classify_document_profiles(&DocumentProfileRequest {
            built_at: 1,
            documents: vec![DocumentProfileInput {
                note_id: "paper".to_owned(),
                text: "# Abstract\nWe show the result.\n\n# Methods\nThe method compares samples.\n\n# Results\nEvidence supports the hypothesis.\n\n# References\nSmith et al. (2025).".to_owned(),
            }],
        });
        let profile = &summary.profiles[0];
        assert_eq!(profile.dominant_profile, DocumentProfileKind::ResearchPaper);
        assert!(
            profile
                .unit_weights
                .iter()
                .find(|row| row.kind == "method")
                .unwrap()
                .weight
                > 1.2
        );
        assert_eq!(summary.source, "native_rust");
    }

    #[test]
    fn mixed_document_keeps_region_specific_profiles() {
        let summary = classify_document_profiles(&DocumentProfileRequest {
            built_at: 2,
            documents: vec![DocumentProfileInput {
                note_id: "mixed".to_owned(),
                text: "## Agenda\nAttendees: Kai\nAction item: review deployment.\n\n## API\n```rust\nfn deploy() {}\n```\nConfigure the service.".to_owned(),
            }],
        });
        let profile = &summary.profiles[0];
        assert!(profile
            .regions
            .iter()
            .any(|row| row.dominant_profile == DocumentProfileKind::MeetingNotes));
        assert!(profile.regions.iter().any(|row| matches!(
            row.dominant_profile,
            DocumentProfileKind::TechnicalDocs | DocumentProfileKind::CodeHeavyNotes
        )));
    }

    #[test]
    fn profile_summary_serializes_with_the_tauri_camel_case_contract() {
        let summary = classify_document_profiles(&DocumentProfileRequest {
            built_at: 3,
            documents: vec![DocumentProfileInput {
                note_id: "spec".to_owned(),
                text: "Configure the API and run the procedure.".to_owned(),
            }],
        });
        let value = serde_json::to_value(summary).unwrap();

        assert_eq!(value["schemaVersion"], "phoenix-document-profile/v1");
        assert_eq!(value["source"], "native_rust");
        assert!(value["profiles"][0].get("dominantProfile").is_some());
        assert!(value["profiles"][0].get("unitWeights").is_some());
    }

    #[test]
    fn regions_handle_windows_newlines_and_group_paragraph_context() {
        let paragraph =
            "Ryan said the city had changed, and Amara asked why the scene felt unfamiliar.";
        let text = (0..40)
            .map(|index| format!("Chapter {index}\r\n\r\n{paragraph}"))
            .collect::<Vec<_>>()
            .join("\r\n\r\n");
        let summary = classify_document_profiles(&DocumentProfileRequest {
            built_at: 4,
            documents: vec![DocumentProfileInput {
                note_id: "windows-story".to_owned(),
                text,
            }],
        });

        assert!(summary.profiles[0].regions.len() > 1);
        assert!(summary.profiles[0].regions.len() <= 40);
        assert!(summary.profiles[0]
            .regions
            .iter()
            .all(|region| region.dominant_profile == DocumentProfileKind::ProseFiction));
    }

    #[test]
    fn cue_matching_does_not_find_api_inside_capital() {
        let summary = classify_document_profiles(&DocumentProfileRequest {
            built_at: 5,
            documents: vec![DocumentProfileInput {
                note_id: "boundaries".to_owned(),
                text: "The capital city contains historical districts and civic institutions."
                    .to_owned(),
            }],
        });

        assert!(!summary.profiles[0]
            .signals
            .iter()
            .any(|signal| signal.cue == "api"));
    }

    #[test]
    fn explanatory_article_uses_reference_profile_without_story_anchors() {
        let summary = classify_document_profiles(&DocumentProfileRequest {
            built_at: 6,
            documents: vec![DocumentProfileInput {
                note_id: "reference".to_owned(),
                text: "# Earthquake overview\n\nScientists use instruments to explain how faults move.\n\n# Learn more\n\nFor example, a seismometer records ground motion according to physical standards.".to_owned(),
            }],
        });
        let profile = &summary.profiles[0];

        assert_eq!(
            profile.dominant_profile,
            DocumentProfileKind::ReferenceArticle
        );
        assert!(profile
            .unit_weights
            .iter()
            .find(|row| row.kind == "definition")
            .is_some_and(|row| row.weight > 1.1));
        assert!(profile
            .unit_weights
            .iter()
            .find(|row| row.kind == "chapter")
            .is_some_and(|row| row.weight < 1.0));
    }
}
