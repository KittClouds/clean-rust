use std::{
    collections::BTreeMap,
    env, fs,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use phoenix_chunker_native::{
    build_chunks, classify_document_profiles, ChunkerConfig, DocumentProfileInput,
    DocumentProfileKind, DocumentProfileRequest,
};
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct CorpusManifest {
    schema_version: String,
    documents: Vec<CorpusDocument>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct CorpusDocument {
    id: String,
    title: String,
    domain: String,
    source_type: String,
    expected_profiles: Vec<String>,
    path: PathBuf,
    source_url: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CorpusReport {
    schema_version: &'static str,
    manifest_schema_version: String,
    generated_at_ms: u64,
    documents: Vec<DocumentReport>,
    summary: CorpusSummary,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DocumentReport {
    id: String,
    title: String,
    domain: String,
    source_type: String,
    source_url: Option<String>,
    chars: usize,
    lines: usize,
    paragraphs: usize,
    headings: usize,
    chunks: usize,
    chunk_chars: Distribution,
    overlap_rate: f64,
    dominant_profile: String,
    confidence: f32,
    expected_profiles: Vec<String>,
    expectation_match: bool,
    top_profiles: Vec<ProfileScore>,
    region_count: usize,
    region_disagreement_rate: f64,
    neutral_region_rate: f64,
    top_signals: Vec<SignalScore>,
    top_unit_weights: Vec<UnitScore>,
    suspicious_reasons: Vec<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Distribution {
    min: usize,
    p10: usize,
    median: usize,
    p90: usize,
    max: usize,
    mean: f64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ProfileScore {
    profile: String,
    score: f32,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SignalScore {
    profile: String,
    cue: String,
    occurrences: u32,
    contribution: f32,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct UnitScore {
    kind: String,
    weight: f32,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CorpusSummary {
    documents: usize,
    total_chars: usize,
    total_chunks: usize,
    expectation_matches: usize,
    low_confidence_documents: usize,
    suspicious_documents: usize,
    by_source_type: BTreeMap<String, usize>,
    by_dominant_profile: BTreeMap<String, usize>,
}

fn main() -> Result<(), String> {
    let args = env::args().skip(1).collect::<Vec<_>>();
    let manifest_path = args
        .first()
        .map(PathBuf::from)
        .ok_or_else(|| "usage: profile_corpus <manifest.json> [--output report.json]".to_owned())?;
    let output_path = args
        .windows(2)
        .find(|pair| pair[0] == "--output")
        .map(|pair| PathBuf::from(&pair[1]));
    let manifest: CorpusManifest = serde_json::from_str(
        &fs::read_to_string(&manifest_path)
            .map_err(|error| format!("failed to read {}: {error}", manifest_path.display()))?,
    )
    .map_err(|error| format!("invalid corpus manifest: {error}"))?;
    let reports = manifest
        .documents
        .into_iter()
        .map(audit_document)
        .collect::<Result<Vec<_>, _>>()?;
    let report = CorpusReport {
        schema_version: "phoenix-document-profile-corpus-report/v1",
        manifest_schema_version: manifest.schema_version,
        generated_at_ms: now_ms(),
        summary: summarize(&reports),
        documents: reports,
    };
    let json = serde_json::to_string_pretty(&report)
        .map_err(|error| format!("failed to serialize report: {error}"))?;
    if let Some(path) = output_path {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("failed to create {}: {error}", parent.display()))?;
        }
        fs::write(&path, format!("{json}\n"))
            .map_err(|error| format!("failed to write {}: {error}", path.display()))?;
        eprintln!("wrote {}", path.display());
    }
    println!("{json}");
    Ok(())
}

fn audit_document(document: CorpusDocument) -> Result<DocumentReport, String> {
    let text = fs::read_to_string(&document.path)
        .map_err(|error| format!("failed to read {}: {error}", document.path.display()))?;
    let chunks = build_chunks(
        &text,
        &ChunkerConfig {
            chunk_size: 1_200,
            overlap: 160,
        },
    );
    let summary = classify_document_profiles(&DocumentProfileRequest {
        documents: vec![DocumentProfileInput {
            note_id: document.id.clone(),
            text: text.clone(),
        }],
        built_at: now_ms(),
    });
    let profile = summary
        .profiles
        .into_iter()
        .next()
        .ok_or_else(|| format!("classifier returned no profile for {}", document.id))?;
    let dominant_profile = profile_name(profile.dominant_profile).to_owned();
    let expectation_match = document.expected_profiles.contains(&dominant_profile);
    let strong_regions = profile
        .regions
        .iter()
        .filter(|region| {
            region.dominant_profile != DocumentProfileKind::MixedNotebook
                && region.confidence >= 0.3
        })
        .collect::<Vec<_>>();
    let region_disagreements = strong_regions
        .iter()
        .filter(|region| region.dominant_profile != profile.dominant_profile)
        .count();
    let region_disagreement_rate = ratio(region_disagreements, strong_regions.len());
    let neutral_region_rate = ratio(
        profile
            .regions
            .iter()
            .filter(|region| region.dominant_profile == DocumentProfileKind::MixedNotebook)
            .count(),
        profile.regions.len(),
    );
    let sizes = chunks
        .iter()
        .map(|chunk| chunk.end.saturating_sub(chunk.start))
        .collect::<Vec<_>>();
    let overlap_chars = chunks
        .windows(2)
        .map(|pair| pair[0].end.saturating_sub(pair[1].start))
        .sum::<usize>();
    let mut suspicious_reasons = Vec::new();
    if !expectation_match {
        suspicious_reasons.push(format!(
            "expected one of [{}], classified as {dominant_profile}",
            document.expected_profiles.join(", ")
        ));
    }
    if profile.confidence < 0.35 {
        suspicious_reasons.push(format!(
            "low document confidence {:.1}%",
            profile.confidence * 100.0
        ));
    }
    if region_disagreement_rate > 0.65 {
        suspicious_reasons.push(format!(
            "{:.1}% of regions disagree with the document profile",
            region_disagreement_rate * 100.0
        ));
    }
    if neutral_region_rate > 0.8 {
        suspicious_reasons.push(format!(
            "{:.1}% of regions have neutral profile evidence",
            neutral_region_rate * 100.0
        ));
    }
    if profile.signals.is_empty() {
        suspicious_reasons.push("no explanatory profile signals".to_owned());
    }
    if sizes.iter().copied().max().unwrap_or(0) > 3_000 {
        suspicious_reasons.push("leaf chunk exceeds 3,000 characters".to_owned());
    }
    let mut top_unit_weights = profile
        .unit_weights
        .iter()
        .map(|row| UnitScore {
            kind: row.kind.clone(),
            weight: row.weight,
        })
        .collect::<Vec<_>>();
    top_unit_weights.sort_by(|left, right| right.weight.total_cmp(&left.weight));
    top_unit_weights.truncate(6);
    Ok(DocumentReport {
        id: document.id,
        title: document.title,
        domain: document.domain,
        source_type: document.source_type,
        source_url: document.source_url,
        chars: text.len(),
        lines: text.lines().count(),
        paragraphs: paragraph_count(&text),
        headings: text
            .lines()
            .filter(|line| line.trim_start().starts_with('#'))
            .count(),
        chunks: chunks.len(),
        chunk_chars: distribution(&sizes),
        overlap_rate: ratio(overlap_chars, sizes.iter().sum()),
        dominant_profile,
        confidence: profile.confidence,
        expected_profiles: document.expected_profiles,
        expectation_match,
        top_profiles: profile
            .weights
            .iter()
            .take(4)
            .map(|row| ProfileScore {
                profile: profile_name(row.profile).to_owned(),
                score: row.score,
            })
            .collect(),
        region_count: profile.regions.len(),
        region_disagreement_rate,
        neutral_region_rate,
        top_signals: profile
            .signals
            .iter()
            .take(8)
            .map(|row| SignalScore {
                profile: profile_name(row.profile).to_owned(),
                cue: row.cue.clone(),
                occurrences: row.occurrences,
                contribution: row.contribution,
            })
            .collect(),
        top_unit_weights,
        suspicious_reasons,
    })
}

fn summarize(reports: &[DocumentReport]) -> CorpusSummary {
    let mut by_source_type = BTreeMap::new();
    let mut by_dominant_profile = BTreeMap::new();
    for report in reports {
        *by_source_type
            .entry(report.source_type.clone())
            .or_insert(0) += 1;
        *by_dominant_profile
            .entry(report.dominant_profile.clone())
            .or_insert(0) += 1;
    }
    CorpusSummary {
        documents: reports.len(),
        total_chars: reports.iter().map(|report| report.chars).sum(),
        total_chunks: reports.iter().map(|report| report.chunks).sum(),
        expectation_matches: reports
            .iter()
            .filter(|report| report.expectation_match)
            .count(),
        low_confidence_documents: reports
            .iter()
            .filter(|report| report.confidence < 0.35)
            .count(),
        suspicious_documents: reports
            .iter()
            .filter(|report| !report.suspicious_reasons.is_empty())
            .count(),
        by_source_type,
        by_dominant_profile,
    }
}

fn distribution(values: &[usize]) -> Distribution {
    if values.is_empty() {
        return Distribution {
            min: 0,
            p10: 0,
            median: 0,
            p90: 0,
            max: 0,
            mean: 0.0,
        };
    }
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    Distribution {
        min: sorted[0],
        p10: percentile(&sorted, 0.1),
        median: percentile(&sorted, 0.5),
        p90: percentile(&sorted, 0.9),
        max: *sorted.last().unwrap_or(&0),
        mean: sorted.iter().sum::<usize>() as f64 / sorted.len() as f64,
    }
}

fn percentile(sorted: &[usize], fraction: f64) -> usize {
    let index = ((sorted.len().saturating_sub(1)) as f64 * fraction).round() as usize;
    sorted[index.min(sorted.len().saturating_sub(1))]
}

fn ratio(numerator: usize, denominator: usize) -> f64 {
    if denominator == 0 {
        0.0
    } else {
        numerator as f64 / denominator as f64
    }
}

fn paragraph_count(text: &str) -> usize {
    let mut count = 0usize;
    let mut inside = false;
    for line in text.lines() {
        if line.trim().is_empty() {
            if inside {
                count += 1;
                inside = false;
            }
        } else {
            inside = true;
        }
    }
    count + inside as usize
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

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[allow(dead_code)]
fn _manifest_dir(path: &Path) -> &Path {
    path.parent().unwrap_or_else(|| Path::new("."))
}
