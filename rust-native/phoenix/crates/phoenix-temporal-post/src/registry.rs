use std::collections::BTreeMap;
use std::fs::{self, File};
use std::path::{Path, PathBuf};

use hashbrown::{HashMap, HashSet};
use memchr::memmem;
use memmap2::Mmap;
use phoenix_types::TextRange;
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::registry_lexicon::{MONTHS, PHRASES};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalRegistry {
    pub registry_id: String,
    pub root: String,
    pub scope_key: String,
    pub generated_at: i64,
    pub parser_version: String,
    #[serde(default)]
    pub documents: Vec<TemporalRegistryDocument>,
    #[serde(default)]
    pub anchors: Vec<TemporalRegistryAnchor>,
    pub summary: TemporalRegistrySummary,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalRegistryDocument {
    pub document_id: String,
    pub relative_path: String,
    pub title: String,
    pub text_len: usize,
    pub fingerprint: String,
    pub anchor_count: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalRegistryAnchor {
    pub anchor_id: String,
    pub document_id: String,
    pub relative_path: String,
    pub surface: String,
    pub normalized_value: Option<String>,
    pub source_class: String,
    pub stability_key: String,
    pub range: TextRange,
    pub sentence_index: usize,
    pub occurrence_index: usize,
    pub confidence_millis: u32,
    pub evidence: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalRegistrySummary {
    pub document_count: usize,
    pub anchor_count: usize,
    pub explicit_anchor_count: usize,
    pub relative_anchor_count: usize,
    #[serde(default)]
    pub source_class_counts: BTreeMap<String, usize>,
    #[serde(default)]
    pub diagnostics: BTreeMap<String, usize>,
}

#[derive(Clone, Debug)]
pub struct TemporalRegistryScanConfig {
    pub parser_version: String,
    pub generated_at: i64,
    pub max_file_bytes: usize,
    pub include_extensions: Vec<String>,
}

impl Default for TemporalRegistryScanConfig {
    fn default() -> Self {
        Self {
            parser_version: "temporal_registry_v3_alpha_1".to_owned(),
            generated_at: 0,
            max_file_bytes: 1_500_000,
            include_extensions: vec!["md".to_owned(), "txt".to_owned()],
        }
    }
}

#[derive(Debug, Error)]
pub enum TemporalRegistryError {
    #[error("failed to read {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("root path is not a directory: {0}")]
    NotDirectory(PathBuf),
}

pub fn scan_temporal_registry_path(
    root: impl AsRef<Path>,
    config: &TemporalRegistryScanConfig,
) -> Result<TemporalRegistry, TemporalRegistryError> {
    let root = root.as_ref();
    if !root.is_dir() {
        return Err(TemporalRegistryError::NotDirectory(root.to_path_buf()));
    }

    let mut diagnostics = BTreeMap::<String, usize>::new();
    let mut documents = Vec::<TemporalRegistryDocument>::new();
    let mut anchors = Vec::<TemporalRegistryAnchor>::new();
    let mut paths = Vec::<PathBuf>::new();
    collect_paths(root, config, &mut paths, &mut diagnostics)?;
    paths.sort();

    let scope_key = stable_scope_key(root);
    for path in paths {
        let relative_path = normalize_path(path.strip_prefix(root).unwrap_or(path.as_path()));
        let metadata = fs::metadata(&path).map_err(|source| TemporalRegistryError::Io {
            path: path.clone(),
            source,
        })?;
        if metadata.len() as usize > config.max_file_bytes {
            bump(&mut diagnostics, "skipped_oversize_file");
            continue;
        }

        let file = File::open(&path).map_err(|source| TemporalRegistryError::Io {
            path: path.clone(),
            source,
        })?;
        let mapped = if metadata.len() == 0 {
            None
        } else {
            // The file is opened read-only and the map is used during this scan only.
            Some(
                unsafe { Mmap::map(&file) }.map_err(|source| TemporalRegistryError::Io {
                    path: path.clone(),
                    source,
                })?,
            )
        };
        let bytes = mapped.as_ref().map(|map| map.as_ref()).unwrap_or(&[]);
        let text = match std::str::from_utf8(bytes) {
            Ok(value) => value,
            Err(_) => {
                bump(&mut diagnostics, "skipped_non_utf8_file");
                continue;
            }
        };

        let document_id = stable_id("tdoc", &[&scope_key, &relative_path]);
        let mut doc_anchors =
            parse_temporal_anchors(text, &document_id, &relative_path, &mut diagnostics);
        anchors.append(&mut doc_anchors);
        documents.push(TemporalRegistryDocument {
            document_id,
            relative_path: relative_path.clone(),
            title: title_for_doc(text, &relative_path),
            text_len: text.len(),
            fingerprint: stable_id("tfp", &[text]),
            anchor_count: anchors
                .iter()
                .filter(|anchor| anchor.relative_path == relative_path)
                .count(),
        });
    }

    anchors.sort_by(|left, right| {
        left.relative_path
            .cmp(&right.relative_path)
            .then_with(|| left.range.start.cmp(&right.range.start))
            .then_with(|| left.anchor_id.cmp(&right.anchor_id))
    });
    let summary = summarize(&documents, &anchors, diagnostics);
    Ok(TemporalRegistry {
        registry_id: stable_id("tregistry", &[&scope_key, config.parser_version.as_str()]),
        root: root.display().to_string(),
        scope_key,
        generated_at: config.generated_at,
        parser_version: config.parser_version.clone(),
        documents,
        anchors,
        summary,
    })
}

pub fn parse_temporal_anchors(
    text: &str,
    document_id: &str,
    relative_path: &str,
    diagnostics: &mut BTreeMap<String, usize>,
) -> Vec<TemporalRegistryAnchor> {
    let lower = text.as_bytes().to_ascii_lowercase();
    let sentence_starts = sentence_starts(text.as_bytes());
    let mut candidates = Vec::<AnchorCandidate>::new();
    collect_iso_dates(text, &mut candidates);
    collect_month_dates(text, &lower, &mut candidates);
    collect_years(text, &mut candidates);
    collect_phrase_anchors(text, &lower, &mut candidates);
    candidates.sort_by(|left, right| {
        left.start
            .cmp(&right.start)
            .then_with(|| right.priority.cmp(&left.priority))
            .then_with(|| right.end.cmp(&left.end))
    });

    let mut occupied = Vec::<(usize, usize)>::new();
    let mut seen_keys = HashMap::<String, usize>::new();
    let mut anchors = Vec::<TemporalRegistryAnchor>::new();
    for candidate in candidates {
        if occupied
            .iter()
            .any(|(start, end)| candidate.start < *end && candidate.end > *start)
        {
            bump(diagnostics, "overlapping_anchor_candidate");
            continue;
        }
        let surface = text[candidate.start..candidate.end].to_owned();
        let base_key = format!(
            "{}:{}:{}",
            candidate.source_class,
            candidate
                .normalized_value
                .as_deref()
                .unwrap_or(surface.as_str()),
            normalize_surface(&surface)
        );
        let occurrence = seen_keys.entry(base_key.clone()).or_insert(0);
        let occurrence_index = *occurrence;
        *occurrence += 1;
        let stability_key = format!("{relative_path}:{base_key}:{occurrence_index}");
        anchors.push(TemporalRegistryAnchor {
            anchor_id: stable_id("tanchor", &[document_id, &stability_key]),
            document_id: document_id.to_owned(),
            relative_path: relative_path.to_owned(),
            surface,
            normalized_value: candidate.normalized_value,
            source_class: candidate.source_class,
            stability_key,
            range: TextRange {
                start: candidate.start as u32,
                end: candidate.end as u32,
            },
            sentence_index: sentence_index_for(candidate.start, &sentence_starts),
            occurrence_index,
            confidence_millis: candidate.confidence_millis,
            evidence: evidence_window(text, candidate.start, candidate.end),
        });
        occupied.push((candidate.start, candidate.end));
    }
    anchors
}

fn collect_paths(
    root: &Path,
    config: &TemporalRegistryScanConfig,
    paths: &mut Vec<PathBuf>,
    diagnostics: &mut BTreeMap<String, usize>,
) -> Result<(), TemporalRegistryError> {
    let entries = fs::read_dir(root).map_err(|source| TemporalRegistryError::Io {
        path: root.to_path_buf(),
        source,
    })?;
    for entry in entries {
        let entry = entry.map_err(|source| TemporalRegistryError::Io {
            path: root.to_path_buf(),
            source,
        })?;
        let path = entry.path();
        if path.is_dir() {
            if should_skip_dir(&path) {
                bump(diagnostics, "skipped_hidden_or_build_dir");
                continue;
            }
            collect_paths(&path, config, paths, diagnostics)?;
            continue;
        }
        if path
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| config.include_extensions.iter().any(|ext| ext == value))
            .unwrap_or(false)
        {
            paths.push(path);
        }
    }
    Ok(())
}

#[derive(Clone, Debug)]
struct AnchorCandidate {
    start: usize,
    end: usize,
    source_class: String,
    normalized_value: Option<String>,
    confidence_millis: u32,
    priority: u8,
}

fn collect_iso_dates(text: &str, out: &mut Vec<AnchorCandidate>) {
    let bytes = text.as_bytes();
    let mut index = 0usize;
    while index + 10 <= bytes.len() {
        if is_digit_run(bytes, index, 4)
            && matches!(bytes[index + 4], b'-' | b'/')
            && is_digit_run(bytes, index + 5, 2)
            && bytes[index + 7] == bytes[index + 4]
            && is_digit_run(bytes, index + 8, 2)
            && boundary(bytes, index, index + 10)
        {
            let year = &text[index..index + 4];
            let month = &text[index + 5..index + 7];
            let day = &text[index + 8..index + 10];
            out.push(candidate(
                index,
                index + 10,
                "explicit_iso_date",
                Some(format!("{year}-{month}-{day}")),
                980,
                9,
            ));
            index += 10;
        } else {
            index += 1;
        }
    }
}

fn collect_month_dates(text: &str, lower: &[u8], out: &mut Vec<AnchorCandidate>) {
    for month in MONTHS {
        for found in memmem::find_iter(lower, month.name.as_bytes()) {
            if !boundary(lower, found, found + month.name.len()) {
                continue;
            }
            let Some((day, day_end)) = parse_day(text.as_bytes(), found + month.name.len()) else {
                continue;
            };
            let (year, end) = parse_optional_year(text.as_bytes(), day_end);
            let normalized = match year {
                Some(year) => Some(format!("{year:04}-{:02}-{day:02}", month.number)),
                None => Some(format!("XXXX-{:02}-{day:02}", month.number)),
            };
            out.push(candidate(
                found,
                end,
                if year.is_some() {
                    "explicit_month_date"
                } else {
                    "explicit_month_day"
                },
                normalized,
                if year.is_some() { 960 } else { 820 },
                8,
            ));
        }
    }
}

fn collect_years(text: &str, out: &mut Vec<AnchorCandidate>) {
    let bytes = text.as_bytes();
    let mut index = 0usize;
    while index + 4 <= bytes.len() {
        if is_digit_run(bytes, index, 4) && boundary(bytes, index, index + 4) {
            let year = text[index..index + 4].parse::<u16>().unwrap_or_default();
            if (1000..=2999).contains(&year) && has_year_context(bytes, index, index + 4) {
                out.push(candidate(
                    index,
                    index + 4,
                    "explicit_year",
                    Some(format!("{year:04}")),
                    700,
                    2,
                ));
            }
            index += 4;
        } else {
            index += 1;
        }
    }
}

fn has_year_context(bytes: &[u8], start: usize, end: usize) -> bool {
    let before_start = start.saturating_sub(24);
    let after_end = bytes.len().min(end + 24);
    let before = std::str::from_utf8(&bytes[before_start..start])
        .unwrap_or("")
        .to_ascii_lowercase();
    let after = std::str::from_utf8(&bytes[end..after_end])
        .unwrap_or("")
        .to_ascii_lowercase();
    let before_context = [
        " in ", " by ", " on ", " at ", " since ", " until ", " before ", " after ", " during ",
        "year ", "dated ",
    ];
    let after_context = [
        " ce",
        " ad",
        " bc",
        " for the",
        " timeline",
        " era",
        " loop",
    ];
    before_context
        .iter()
        .any(|needle| before.ends_with(needle) || before.contains(needle))
        || after_context.iter().any(|needle| after.starts_with(needle))
}

fn collect_phrase_anchors(text: &str, lower: &[u8], out: &mut Vec<AnchorCandidate>) {
    for phrase in PHRASES {
        for found in memmem::find_iter(lower, phrase.surface.as_bytes()) {
            if boundary(lower, found, found + phrase.surface.len()) {
                out.push(candidate(
                    found,
                    found + phrase.surface.len(),
                    phrase.source_class,
                    Some(phrase.normalized.to_owned()),
                    phrase.confidence_millis,
                    phrase.priority,
                ));
            }
        }
    }
    collect_unit_offsets(text, lower, out);
}

fn collect_unit_offsets(text: &str, lower: &[u8], out: &mut Vec<AnchorCandidate>) {
    for unit in ["second", "minute", "hour", "day", "week", "month", "year"] {
        for found in memmem::find_iter(lower, unit.as_bytes()) {
            let start = phrase_start_before_unit(lower, found).unwrap_or(found);
            let tail = &lower[found + unit.len()..lower.len().min(found + unit.len() + 8)];
            if tail.starts_with(b" later")
                || tail.starts_with(b" after")
                || tail.starts_with(b"s later")
                || tail.starts_with(b"s after")
            {
                let mut end = found + unit.len();
                if lower.get(end) == Some(&b's') {
                    end += 1;
                }
                while end < lower.len() && lower[end].is_ascii_whitespace() {
                    end += 1;
                }
                if lower[end..].starts_with(b"later") {
                    end += 5;
                } else if lower[end..].starts_with(b"after") {
                    end += 5;
                }
                out.push(candidate(
                    start,
                    end,
                    "relative_offset",
                    Some(format!(
                        "REL_OFFSET:{}",
                        normalize_surface(&text[start..end])
                    )),
                    760,
                    6,
                ));
            }
        }
    }
}

fn candidate(
    start: usize,
    end: usize,
    source_class: &str,
    normalized_value: Option<String>,
    confidence_millis: u32,
    priority: u8,
) -> AnchorCandidate {
    AnchorCandidate {
        start,
        end,
        source_class: source_class.to_owned(),
        normalized_value,
        confidence_millis,
        priority,
    }
}

fn parse_day(bytes: &[u8], mut index: usize) -> Option<(u8, usize)> {
    while index < bytes.len() && (bytes[index].is_ascii_whitespace() || bytes[index] == b',') {
        index += 1;
    }
    let start = index;
    while index < bytes.len() && bytes[index].is_ascii_digit() {
        index += 1;
    }
    if start == index || index - start > 2 {
        return None;
    }
    let day = std::str::from_utf8(&bytes[start..index])
        .ok()?
        .parse::<u8>()
        .ok()?;
    if !(1..=31).contains(&day) {
        return None;
    }
    if matches!(
        bytes.get(index..index + 2),
        Some(b"st" | b"nd" | b"rd" | b"th")
    ) {
        index += 2;
    }
    Some((day, index))
}

fn parse_optional_year(bytes: &[u8], mut index: usize) -> (Option<u16>, usize) {
    let mut cursor = index;
    while cursor < bytes.len() && (bytes[cursor].is_ascii_whitespace() || bytes[cursor] == b',') {
        cursor += 1;
    }
    if cursor + 4 <= bytes.len() && is_digit_run(bytes, cursor, 4) {
        let year = std::str::from_utf8(&bytes[cursor..cursor + 4])
            .ok()
            .and_then(|value| value.parse::<u16>().ok());
        if let Some(year) = year.filter(|year| (1000..=2999).contains(year)) {
            return (Some(year), cursor + 4);
        }
    }
    while index < bytes.len() && bytes[index].is_ascii_whitespace() {
        index += 1;
    }
    (None, index)
}

fn phrase_start_before_unit(lower: &[u8], unit_start: usize) -> Option<usize> {
    let mut cursor = unit_start;
    while cursor > 0 && lower[cursor - 1].is_ascii_whitespace() {
        cursor -= 1;
    }
    let word_end = cursor;
    while cursor > 0 && lower[cursor - 1].is_ascii_alphabetic() {
        cursor -= 1;
    }
    let word = &lower[cursor..word_end];
    if matches!(
        word,
        b"a" | b"an" | b"one" | b"two" | b"three" | b"four" | b"five" | b"less"
    ) {
        Some(cursor)
    } else {
        None
    }
}

fn is_digit_run(bytes: &[u8], start: usize, len: usize) -> bool {
    start + len <= bytes.len() && bytes[start..start + len].iter().all(u8::is_ascii_digit)
}

fn boundary(bytes: &[u8], start: usize, end: usize) -> bool {
    let left = start == 0 || !bytes[start - 1].is_ascii_alphanumeric();
    let right = end >= bytes.len() || !bytes[end].is_ascii_alphanumeric();
    left && right
}

fn sentence_starts(bytes: &[u8]) -> Vec<usize> {
    let mut starts = vec![0usize];
    let mut seen = HashSet::<usize>::new();
    for index in
        memchr::memchr3_iter(b'.', b'!', b'?', bytes).chain(memchr::memchr_iter(b'\n', bytes))
    {
        let mut next = index + 1;
        while next < bytes.len() && bytes[next].is_ascii_whitespace() {
            next += 1;
        }
        if next < bytes.len() && seen.insert(next) {
            starts.push(next);
        }
    }
    starts.sort_unstable();
    starts
}

fn sentence_index_for(offset: usize, starts: &[usize]) -> usize {
    match starts.binary_search(&offset) {
        Ok(index) => index,
        Err(index) => index.saturating_sub(1),
    }
}

fn evidence_window(text: &str, start: usize, end: usize) -> String {
    let left = text[..start]
        .rfind(['.', '!', '?', '\n'])
        .map_or(0, |index| index + 1);
    let right = text[end..]
        .find(['.', '!', '?', '\n'])
        .map_or(text.len(), |index| end + index + 1);
    text[left..right].trim().replace(char::is_whitespace, " ")
}

fn title_for_doc(text: &str, relative_path: &str) -> String {
    text.lines()
        .find_map(|line| line.trim().strip_prefix("# ").map(str::trim))
        .filter(|line| !line.is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| {
            Path::new(relative_path)
                .file_stem()
                .and_then(|value| value.to_str())
                .unwrap_or(relative_path)
                .to_owned()
        })
}

fn summarize(
    documents: &[TemporalRegistryDocument],
    anchors: &[TemporalRegistryAnchor],
    diagnostics: BTreeMap<String, usize>,
) -> TemporalRegistrySummary {
    let mut source_class_counts = BTreeMap::<String, usize>::new();
    let mut explicit_anchor_count = 0usize;
    let mut relative_anchor_count = 0usize;
    for anchor in anchors {
        *source_class_counts
            .entry(anchor.source_class.clone())
            .or_default() += 1;
        if anchor.source_class.starts_with("explicit") {
            explicit_anchor_count += 1;
        } else {
            relative_anchor_count += 1;
        }
    }
    TemporalRegistrySummary {
        document_count: documents.len(),
        anchor_count: anchors.len(),
        explicit_anchor_count,
        relative_anchor_count,
        source_class_counts,
        diagnostics,
    }
}

fn should_skip_dir(path: &Path) -> bool {
    path.file_name()
        .and_then(|value| value.to_str())
        .map(|name| matches!(name, ".git" | "node_modules" | "target" | "dist"))
        .unwrap_or(false)
}

fn normalize_path(path: &Path) -> String {
    path.components()
        .filter_map(|component| component.as_os_str().to_str())
        .collect::<Vec<_>>()
        .join("/")
}

fn normalize_surface(value: &str) -> String {
    value
        .trim()
        .to_ascii_lowercase()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join("_")
}

fn stable_scope_key(root: &Path) -> String {
    stable_id("tscope", &[root.to_string_lossy().as_ref()])
}

fn stable_id(prefix: &str, parts: &[&str]) -> String {
    let mut hash = 0xcbf29ce484222325u64;
    for part in parts {
        for byte in part.as_bytes() {
            hash ^= u64::from(*byte);
            hash = hash.wrapping_mul(0x100000001b3);
        }
        hash ^= 0xff;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{prefix}:{hash:016x}")
}

fn bump(counts: &mut BTreeMap<String, usize>, key: &str) {
    *counts.entry(key.to_owned()).or_default() += 1;
}
