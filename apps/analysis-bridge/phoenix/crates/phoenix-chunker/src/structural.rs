use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::{build_chunks, split_sentence_ranges, ChunkerConfig};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum DialogueBoundaryHint {
    #[default]
    None,
    OpensQuote,
    ClosesQuote,
    QuotedSentence,
    DialogueLine,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum SentenceQuality {
    Empty,
    Fragment,
    #[default]
    Complete,
    RunOn,
    NoTerminalPunctuation,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SentenceSpan {
    pub start: usize,
    pub end: usize,
    pub paragraph_index: usize,
    pub chapter_index: usize,
    pub token_count: usize,
    pub content_hash: u64,
    pub quality: SentenceQuality,
    pub dialogue_hint: DialogueBoundaryHint,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ParagraphSpan {
    pub start: usize,
    pub end: usize,
    pub chapter_index: usize,
    pub sentence_start: usize,
    pub sentence_end: usize,
    pub token_count: usize,
    pub content_hash: u64,
    pub dialogue_hint: DialogueBoundaryHint,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChapterSpan {
    pub start: usize,
    pub end: usize,
    pub title: String,
    pub paragraph_start: usize,
    pub paragraph_end: usize,
    pub sentence_start: usize,
    pub sentence_end: usize,
    pub token_count: usize,
    pub content_hash: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BaseChunk {
    pub start: usize,
    pub end: usize,
    pub sentence_start: usize,
    pub sentence_end: usize,
    pub paragraph_start: usize,
    pub paragraph_end: usize,
    pub chapter_index: Option<usize>,
    pub token_count: usize,
    pub content_hash: u64,
    pub dialogue_hint: DialogueBoundaryHint,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StructuralSubstrate {
    pub base_chunks: Vec<BaseChunk>,
    pub sentences: Vec<SentenceSpan>,
    pub paragraphs: Vec<ParagraphSpan>,
    pub chapters: Vec<ChapterSpan>,
}

#[derive(Clone, Debug, Default)]
struct TextSignals {
    token_count: usize,
    sentence_count: usize,
    normalized_whitespace: String,
    quote_normalized: String,
    preprocessed: String,
}

pub fn build_structural_substrate(text: &str, config: &ChunkerConfig) -> StructuralSubstrate {
    if text.trim().is_empty() {
        return StructuralSubstrate {
            base_chunks: Vec::new(),
            sentences: Vec::new(),
            paragraphs: Vec::new(),
            chapters: Vec::new(),
        };
    }

    let paragraphs = raw_paragraph_ranges(text);
    let chapters = raw_chapter_ranges(text);
    let paragraph_by_sentence = paragraph_lookup(&paragraphs);
    let chapter_by_paragraph = chapter_lookup(&paragraphs, &chapters);

    let mut sentences = Vec::new();
    for (start, end) in split_sentence_ranges(text) {
        let paragraph_index = paragraph_by_sentence
            .iter()
            .position(|(paragraph_start, paragraph_end)| {
                start >= *paragraph_start && end <= *paragraph_end
            })
            .unwrap_or_else(|| paragraph_index_for_offset(&paragraphs, start));
        let chapter_index = chapter_by_paragraph
            .get(paragraph_index)
            .copied()
            .unwrap_or_default();
        let span_text = &text[start..end];
        let signals = text_signals(span_text);
        sentences.push(SentenceSpan {
            start,
            end,
            paragraph_index,
            chapter_index,
            token_count: signals.token_count,
            content_hash: content_hash(span_text),
            quality: sentence_quality(span_text, &signals),
            dialogue_hint: dialogue_hint(span_text, &signals),
        });
    }

    let mut paragraph_spans = Vec::with_capacity(paragraphs.len());
    for (paragraph_index, &(start, end)) in paragraphs.iter().enumerate() {
        let sentence_start = sentences
            .iter()
            .position(|sentence| sentence.paragraph_index == paragraph_index)
            .unwrap_or(sentences.len());
        let sentence_end = sentences
            .iter()
            .rposition(|sentence| sentence.paragraph_index == paragraph_index)
            .map(|index| index + 1)
            .unwrap_or(sentence_start);
        let chapter_index = chapter_by_paragraph
            .get(paragraph_index)
            .copied()
            .unwrap_or_default();
        let span_text = &text[start..end];
        let signals = text_signals(span_text);
        paragraph_spans.push(ParagraphSpan {
            start,
            end,
            chapter_index,
            sentence_start,
            sentence_end,
            token_count: signals.token_count,
            content_hash: content_hash(span_text),
            dialogue_hint: dialogue_hint(span_text, &signals),
        });
    }

    let mut chapter_spans = Vec::with_capacity(chapters.len());
    for (chapter_index, raw) in chapters.iter().enumerate() {
        let paragraph_start = paragraph_spans
            .iter()
            .position(|paragraph| paragraph.start >= raw.start && paragraph.end <= raw.end)
            .unwrap_or(paragraph_spans.len());
        let paragraph_end = paragraph_spans
            .iter()
            .rposition(|paragraph| paragraph.start >= raw.start && paragraph.end <= raw.end)
            .map(|index| index + 1)
            .unwrap_or(paragraph_start);
        let sentence_start = sentences
            .iter()
            .position(|sentence| sentence.chapter_index == chapter_index)
            .unwrap_or(sentences.len());
        let sentence_end = sentences
            .iter()
            .rposition(|sentence| sentence.chapter_index == chapter_index)
            .map(|index| index + 1)
            .unwrap_or(sentence_start);
        let span_text = &text[raw.start..raw.end];
        chapter_spans.push(ChapterSpan {
            start: raw.start,
            end: raw.end,
            title: raw.title.clone(),
            paragraph_start,
            paragraph_end,
            sentence_start,
            sentence_end,
            token_count: text_signals(span_text).token_count,
            content_hash: content_hash(span_text),
        });
    }

    let base_chunks = build_base_chunks(text, config, &sentences, &paragraph_spans);

    StructuralSubstrate {
        base_chunks,
        sentences,
        paragraphs: paragraph_spans,
        chapters: chapter_spans,
    }
}

fn build_base_chunks(
    text: &str,
    config: &ChunkerConfig,
    sentences: &[SentenceSpan],
    paragraphs: &[ParagraphSpan],
) -> Vec<BaseChunk> {
    build_chunks(text, config)
        .into_iter()
        .map(|chunk| {
            let sentence_start = sentences
                .iter()
                .position(|sentence| sentence.end > chunk.start && sentence.start < chunk.end)
                .unwrap_or(sentences.len());
            let sentence_end = sentences
                .iter()
                .rposition(|sentence| sentence.end > chunk.start && sentence.start < chunk.end)
                .map(|index| index + 1)
                .unwrap_or(sentence_start);
            let paragraph_start = paragraphs
                .iter()
                .position(|paragraph| paragraph.end > chunk.start && paragraph.start < chunk.end)
                .unwrap_or(paragraphs.len());
            let paragraph_end = paragraphs
                .iter()
                .rposition(|paragraph| paragraph.end > chunk.start && paragraph.start < chunk.end)
                .map(|index| index + 1)
                .unwrap_or(paragraph_start);
            let chapter_index = sentences
                .get(sentence_start)
                .map(|sentence| sentence.chapter_index)
                .or_else(|| {
                    paragraphs
                        .get(paragraph_start)
                        .map(|paragraph| paragraph.chapter_index)
                });
            let span_text = &text[chunk.start..chunk.end];
            let signals = text_signals(span_text);
            BaseChunk {
                start: chunk.start,
                end: chunk.end,
                sentence_start,
                sentence_end,
                paragraph_start,
                paragraph_end,
                chapter_index,
                token_count: signals.token_count,
                content_hash: content_hash(span_text),
                dialogue_hint: dialogue_hint(span_text, &signals),
            }
        })
        .collect()
}

#[derive(Clone, Debug)]
struct RawChapter {
    start: usize,
    end: usize,
    title: String,
}

fn raw_chapter_ranges(text: &str) -> Vec<RawChapter> {
    let mut headings = chapter_headings(text);
    if headings.is_empty() {
        let (start, end) = trim_range(text, 0, text.len());
        return vec![RawChapter {
            start,
            end,
            title: "Document".to_owned(),
        }];
    }

    headings.sort_by_key(|heading| heading.0);
    let mut chapters = Vec::with_capacity(headings.len());
    for (index, (start, title)) in headings.iter().enumerate() {
        let raw_end = headings
            .get(index + 1)
            .map(|(next_start, _)| *next_start)
            .unwrap_or(text.len());
        let (trimmed_start, trimmed_end) = trim_range(text, *start, raw_end);
        chapters.push(RawChapter {
            start: trimmed_start,
            end: trimmed_end,
            title: title.clone(),
        });
    }
    chapters
}

fn chapter_headings(text: &str) -> Vec<(usize, String)> {
    let mut headings = Vec::new();
    let mut line_start = 0usize;
    for line in text.split_inclusive('\n') {
        let line_without_newline = line.trim_end_matches(['\r', '\n']);
        let leading = line_without_newline.len() - line_without_newline.trim_start().len();
        let heading_start = line_start + leading;
        let trimmed = line_without_newline.trim_start();
        if is_chapter_heading(trimmed) {
            headings.push((heading_start, heading_title(trimmed)));
        }
        line_start += line.len();
    }
    if line_start < text.len() {
        let line = &text[line_start..];
        let leading = line.len() - line.trim_start().len();
        let trimmed = line.trim_start();
        if is_chapter_heading(trimmed) {
            headings.push((line_start + leading, heading_title(trimmed)));
        }
    }
    headings
}

fn is_chapter_heading(line: &str) -> bool {
    if line.starts_with('#') {
        let level = line.bytes().take_while(|byte| *byte == b'#').count();
        if level == 0 || level > 6 || !line[level..].starts_with(' ') {
            return false;
        }
        return starts_with_chapter_label(line[level..].trim());
    }
    is_plain_chapter_heading(line.trim())
}

fn starts_with_chapter_label(title: &str) -> bool {
    title
        .get(..8)
        .is_some_and(|prefix| prefix.eq_ignore_ascii_case("chapter "))
}

fn is_plain_chapter_heading(title: &str) -> bool {
    const MAX_PLAIN_HEADING_BYTES: usize = 160;
    if title.len() > MAX_PLAIN_HEADING_BYTES || !starts_with_chapter_label(title) {
        return false;
    }
    let rest = &title[8..];
    let designator_len = rest
        .bytes()
        .take_while(|byte| {
            byte.is_ascii_digit()
                || matches!(
                    byte.to_ascii_uppercase(),
                    b'I' | b'V' | b'X' | b'L' | b'C' | b'D' | b'M'
                )
        })
        .count();
    if designator_len == 0 {
        return false;
    }
    let suffix = rest[designator_len..].trim_start();
    matches!(suffix.chars().next(), None | Some(':' | '-' | '—'))
}

fn heading_title(line: &str) -> String {
    line.trim_start_matches('#').trim().to_owned()
}

fn raw_paragraph_ranges(text: &str) -> Vec<(usize, usize)> {
    let mut paragraphs = Vec::new();
    let mut current_start = None;
    let mut offset = 0usize;

    for line in text.split_inclusive('\n') {
        let line_start = offset;
        let line_end = offset + line.len();
        let content_end = line_end - line.ends_with('\n') as usize;
        let content_end = content_end
            - (content_end > line_start && text.as_bytes()[content_end - 1] == b'\r') as usize;
        let line_content = &text[line_start..content_end];
        if line_content.trim().is_empty() {
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

fn push_trimmed_range(text: &str, start: usize, end: usize, ranges: &mut Vec<(usize, usize)>) {
    let (start, end) = trim_range(text, start, end);
    if start < end {
        ranges.push((start, end));
    }
}

fn trim_range(text: &str, start: usize, end: usize) -> (usize, usize) {
    let mut trimmed_start = start;
    let mut trimmed_end = end;
    while trimmed_start < trimmed_end {
        let Some(ch) = text[trimmed_start..trimmed_end].chars().next() else {
            break;
        };
        if !ch.is_whitespace() {
            break;
        }
        trimmed_start += ch.len_utf8();
    }
    while trimmed_end > trimmed_start {
        let Some(ch) = text[trimmed_start..trimmed_end].chars().next_back() else {
            break;
        };
        if !ch.is_whitespace() {
            break;
        }
        trimmed_end -= ch.len_utf8();
    }
    (trimmed_start, trimmed_end)
}

fn paragraph_lookup(paragraphs: &[(usize, usize)]) -> Vec<(usize, usize)> {
    paragraphs.to_vec()
}

fn chapter_lookup(paragraphs: &[(usize, usize)], chapters: &[RawChapter]) -> Vec<usize> {
    paragraphs
        .iter()
        .map(|(start, end)| {
            chapters
                .iter()
                .position(|chapter| *start >= chapter.start && *end <= chapter.end)
                .unwrap_or_default()
        })
        .collect()
}

fn paragraph_index_for_offset(paragraphs: &[(usize, usize)], offset: usize) -> usize {
    paragraphs
        .iter()
        .position(|(start, end)| offset >= *start && offset <= *end)
        .unwrap_or_default()
}

fn sentence_quality(text: &str, signals: &TextSignals) -> SentenceQuality {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return SentenceQuality::Empty;
    }
    if signals.token_count <= 2 && !has_terminal_punctuation(trimmed) {
        return SentenceQuality::Fragment;
    }
    if !has_terminal_punctuation(trimmed) {
        return SentenceQuality::NoTerminalPunctuation;
    }
    if signals.token_count > 80 || signals.sentence_count > 1 {
        return SentenceQuality::RunOn;
    }
    SentenceQuality::Complete
}

fn has_terminal_punctuation(text: &str) -> bool {
    text.trim_end_matches(['"', '\'', ')', ']', '}', '\u{201d}', '\u{2019}'])
        .ends_with(['.', '!', '?'])
}

fn dialogue_hint(text: &str, signals: &TextSignals) -> DialogueBoundaryHint {
    let trimmed = signals.normalized_whitespace.trim();
    let quote_text = signals.quote_normalized.trim();
    let starts_quote = trimmed.starts_with(['"', '\u{201c}'])
        || quote_text.starts_with('"')
        || text.lines().any(|line| {
            let trimmed = line.trim_start();
            trimmed.starts_with(['"', '\u{201c}'])
        });
    if starts_quote {
        if trimmed.ends_with(['"', '\u{201d}']) || quote_text.ends_with('"') {
            DialogueBoundaryHint::QuotedSentence
        } else {
            DialogueBoundaryHint::OpensQuote
        }
    } else if trimmed.ends_with(['"', '\u{201d}']) || quote_text.ends_with('"') {
        DialogueBoundaryHint::ClosesQuote
    } else if trimmed.starts_with(['-', '\u{2013}', '\u{2014}'])
        || signals.preprocessed.contains(" said")
        || signals.preprocessed.contains(" asked")
        || signals.preprocessed.contains(" replied")
    {
        DialogueBoundaryHint::DialogueLine
    } else {
        DialogueBoundaryHint::None
    }
}

fn content_hash(text: &str) -> u64 {
    const FNV_OFFSET: u64 = 0xcbf29ce484222325;
    const FNV_PRIME: u64 = 0x100000001b3;
    let mut hash = FNV_OFFSET;
    for byte in text.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(FNV_PRIME);
    }
    hash
}

#[cfg(not(target_arch = "wasm32"))]
fn text_signals(text: &str) -> TextSignals {
    use scirs2_text::cleansing::{normalize_dashes, normalize_quotes};
    use scirs2_text::{
        normalize_unicode, normalize_whitespace, BasicNormalizer, BasicTextCleaner, TextCleaner,
        TextNormalizer, TextStatistics, Tokenizer, WordTokenizer,
    };

    let unicode_normalized = normalize_unicode(text).unwrap_or_else(|_| text.to_owned());
    let quote_normalized = normalize_quotes(&normalize_dashes(&unicode_normalized));
    let normalized_whitespace = normalize_whitespace(&quote_normalized);
    let normalizer = BasicNormalizer::new(false, true);
    let cleaner = BasicTextCleaner::new(false, false, true);
    let preprocessed = normalizer
        .normalize(text)
        .and_then(|normalized| cleaner.clean(&normalized))
        .unwrap_or_else(|_| normalized_whitespace.clone());
    let tokenizer = WordTokenizer::new(false);
    let token_count = tokenizer
        .tokenize(&preprocessed)
        .map(|tokens| tokens.len())
        .unwrap_or_else(|_| fallback_token_count(text));
    let stats = TextStatistics::new();
    let sentence_count = stats.sentence_count(text).unwrap_or_default();

    TextSignals {
        token_count,
        sentence_count,
        normalized_whitespace,
        quote_normalized,
        preprocessed,
    }
}

#[cfg(target_arch = "wasm32")]
fn text_signals(text: &str) -> TextSignals {
    let normalized_whitespace = text.split_whitespace().collect::<Vec<_>>().join(" ");
    TextSignals {
        token_count: fallback_token_count(text),
        sentence_count: split_sentence_ranges(text).len(),
        quote_normalized: normalized_whitespace.replace(['\u{201c}', '\u{201d}'], "\""),
        preprocessed: normalized_whitespace.clone(),
        normalized_whitespace,
    }
}

fn fallback_token_count(text: &str) -> usize {
    text.split(|ch: char| !(ch.is_alphanumeric() || ch == '\'' || ch == '-'))
        .filter(|token| !token.is_empty())
        .count()
}

#[allow(dead_code)]
fn _debug_span_counts(substrate: &StructuralSubstrate) -> BTreeMap<&'static str, usize> {
    BTreeMap::from([
        ("base_chunks", substrate.base_chunks.len()),
        ("sentences", substrate.sentences.len()),
        ("paragraphs", substrate.paragraphs.len()),
        ("chapters", substrate.chapters.len()),
    ])
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_text() -> &'static str {
        "## Chapter 1: Dawn\n\n\"Aella, wait,\" Kai said. The beacon flashed twice.\n\nBefore noon, Rowan crossed the bridge.\n\n## Chapter 2: Dusk\n\nBrynwyn mapped the harbor. She marked the old gate."
    }

    #[test]
    fn structural_offsets_are_valid_utf8_boundaries() {
        let text = "## Chapter 1: Élan\n\n“Aella,” Kai said. Café lights flickered.";
        let substrate = build_structural_substrate(text, &ChunkerConfig::default());
        for (start, end) in all_ranges(&substrate) {
            assert!(text.is_char_boundary(start), "invalid start {start}");
            assert!(text.is_char_boundary(end), "invalid end {end}");
            assert!(start <= end);
            let _ = &text[start..end];
        }
    }

    #[test]
    fn structural_chunks_are_deterministic() {
        let config = ChunkerConfig {
            chunk_size: 80,
            overlap: 20,
        };
        let left = build_structural_substrate(sample_text(), &config);
        let right = build_structural_substrate(sample_text(), &config);
        assert_eq!(left, right);
    }

    #[test]
    fn content_hash_depends_only_on_span_text() {
        let first =
            build_structural_substrate("Alpha spoke. Beta listened.", &ChunkerConfig::default());
        let second = build_structural_substrate(
            "Prelude. Alpha spoke. Beta listened.",
            &ChunkerConfig::default(),
        );
        let first_hash = first
            .sentences
            .iter()
            .find(|sentence| {
                &"Alpha spoke. Beta listened."[sentence.start..sentence.end] == "Alpha spoke."
            })
            .map(|sentence| sentence.content_hash)
            .unwrap_or_else(|| content_hash("Alpha spoke."));
        let second_hash = second
            .sentences
            .iter()
            .find(|sentence| {
                &"Prelude. Alpha spoke. Beta listened."[sentence.start..sentence.end]
                    == "Alpha spoke."
            })
            .map(|sentence| sentence.content_hash)
            .expect("shifted sentence exists");
        assert_eq!(first_hash, second_hash);
        assert_ne!(
            content_hash("Alpha spoke."),
            content_hash("Alpha whispered.")
        );
    }

    #[test]
    fn hierarchy_is_stable() {
        let substrate = build_structural_substrate(sample_text(), &ChunkerConfig::default());
        assert_eq!(substrate.chapters.len(), 2);
        assert_eq!(substrate.chapters[0].title, "Chapter 1: Dawn");
        assert_eq!(substrate.chapters[1].title, "Chapter 2: Dusk");
        assert!(substrate.paragraphs.len() >= 5);
        assert!(substrate
            .sentences
            .iter()
            .any(|sentence| sentence.chapter_index == 0));
        assert!(substrate
            .sentences
            .iter()
            .any(|sentence| sentence.chapter_index == 1));
        for paragraph in &substrate.paragraphs {
            assert!(paragraph.sentence_start <= paragraph.sentence_end);
        }
        for chapter in &substrate.chapters {
            assert!(chapter.paragraph_start <= chapter.paragraph_end);
            assert!(chapter.sentence_start <= chapter.sentence_end);
        }
    }

    #[test]
    fn plain_numbered_chapters_define_authoritative_ranges() {
        let text = "Chapter 1: Quicksave!?\n\n```\nOpening epigraph.\n```\n\nAlpha arrived.\n\nChapter 2: Story Branching\n\n```\nSecond epigraph.\n```\n\nBeta waited.";
        let old_chunks = build_chunks(text, &ChunkerConfig::default());
        let substrate = build_structural_substrate(text, &ChunkerConfig::default());

        assert_eq!(substrate.chapters.len(), 2);
        assert_eq!(substrate.chapters[0].title, "Chapter 1: Quicksave!?");
        assert_eq!(substrate.chapters[1].title, "Chapter 2: Story Branching");
        assert!(substrate
            .sentences
            .iter()
            .any(|span| span.chapter_index == 0));
        assert!(substrate
            .sentences
            .iter()
            .any(|span| span.chapter_index == 1));
        assert_eq!(substrate.base_chunks.len(), old_chunks.len());
        assert!(substrate
            .base_chunks
            .iter()
            .zip(old_chunks)
            .all(|(base, old)| (base.start, base.end) == (old.start, old.end)));
    }

    #[test]
    fn plain_chapter_grammar_rejects_prose_lookalikes() {
        for heading in [
            "Chapter 1",
            "chapter 10: Heroes & Villains",
            "CHAPTER IV — Return",
        ] {
            assert!(is_chapter_heading(heading), "rejected {heading:?}");
        }
        for prose in [
            "Chapter One begins here",
            "Chapter 1 was difficult to draft.",
            "Chapterhouse 2: Not a chapter",
        ] {
            assert!(!is_chapter_heading(prose), "accepted {prose:?}");
        }
    }

    #[test]
    fn old_chunk_output_remains_compatible() {
        let config = ChunkerConfig {
            chunk_size: 80,
            overlap: 20,
        };
        let old_chunks = build_chunks(sample_text(), &config);
        let substrate = build_structural_substrate(sample_text(), &config);
        let base_ranges = substrate
            .base_chunks
            .iter()
            .map(|chunk| (chunk.start, chunk.end))
            .collect::<Vec<_>>();
        let old_ranges = old_chunks
            .iter()
            .map(|chunk| (chunk.start, chunk.end))
            .collect::<Vec<_>>();
        assert_eq!(base_ranges, old_ranges);
    }

    #[test]
    fn dialogue_hints_detect_quoted_lines() {
        let substrate = build_structural_substrate(sample_text(), &ChunkerConfig::default());
        assert!(substrate
            .sentences
            .iter()
            .any(|sentence| sentence.dialogue_hint != DialogueBoundaryHint::None));
    }

    fn all_ranges(substrate: &StructuralSubstrate) -> Vec<(usize, usize)> {
        let mut ranges = Vec::new();
        ranges.extend(
            substrate
                .base_chunks
                .iter()
                .map(|span| (span.start, span.end)),
        );
        ranges.extend(
            substrate
                .sentences
                .iter()
                .map(|span| (span.start, span.end)),
        );
        ranges.extend(
            substrate
                .paragraphs
                .iter()
                .map(|span| (span.start, span.end)),
        );
        ranges.extend(substrate.chapters.iter().map(|span| (span.start, span.end)));
        ranges
    }
}
