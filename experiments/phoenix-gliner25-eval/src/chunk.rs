use memchr::memchr_iter;
use regex::Regex;
use smallvec::SmallVec;
use std::sync::OnceLock;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Chunk {
    pub index: u32,
    pub chapter: u32,
    pub word_start: u32,
    pub word_end: u32,
    pub byte_start: usize,
    pub byte_end: usize,
}

impl Chunk {
    pub fn text<'a>(&self, document: &'a str) -> &'a str {
        &document[self.byte_start..self.byte_end]
    }
}

pub fn chapter_windows(text: &str, size: usize, overlap: usize) -> Vec<Chunk> {
    assert!(size > 0 && overlap < size);
    let words = word_ranges(text.as_bytes());
    if words.is_empty() {
        return Vec::new();
    }
    let chapter_bytes = chapter_starts(text.as_bytes());
    let mut chapter_words = Vec::with_capacity(chapter_bytes.len() + 1);
    for byte in chapter_bytes {
        chapter_words.push(words.partition_point(|&(_, end)| end <= byte));
    }
    chapter_words.sort_unstable();
    chapter_words.dedup();
    if chapter_words.first().copied() != Some(0) {
        chapter_words.insert(0, 0);
    }
    if chapter_words.last().copied() != Some(words.len()) {
        chapter_words.push(words.len());
    }

    let mut chunks = Vec::with_capacity(words.len().div_ceil(size));
    let step = size - overlap;
    for (chapter, bounds) in chapter_words.windows(2).enumerate() {
        let (region_start, region_end) = (bounds[0], bounds[1]);
        let mut start = region_start;
        while start < region_end {
            let end = (start + size).min(region_end);
            let (byte_start, _) = words[start];
            let (_, byte_end) = words[end - 1];
            chunks.push(Chunk {
                index: chunks.len() as u32,
                chapter: chapter as u32,
                word_start: start as u32,
                word_end: end as u32,
                byte_start,
                byte_end,
            });
            if end == region_end {
                break;
            }
            start += step;
        }
    }
    chunks
}

pub fn model_word_count(text: &str) -> usize {
    word_ranges(text.as_bytes()).len()
}

fn word_ranges(bytes: &[u8]) -> Vec<(usize, usize)> {
    // This is deliberately identical to gliner25-rs::WhitespaceTokenSplitter.
    // Whitespace counts are not sufficient for punctuation-heavy fiction.
    static SPLITTER: OnceLock<Regex> = OnceLock::new();
    let splitter = SPLITTER.get_or_init(|| {
        Regex::new(
            r"(?xi)
            (?:https?://[^\s]+|www\.[^\s]+)
            |[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}
            |@[a-z0-9_]+
            |\w+(?:[-_]\w+)*
            |\S
        ",
        )
        .expect("frozen model word splitter must compile")
    });
    let text =
        std::str::from_utf8(bytes).expect("documents are validated as UTF-8 before chunking");
    splitter
        .find_iter(text)
        .map(|m| (m.start(), m.end()))
        .collect()
}

fn chapter_starts(bytes: &[u8]) -> SmallVec<[usize; 64]> {
    let mut starts = SmallVec::new();
    starts.push(0);
    for line_start in std::iter::once(0).chain(memchr_iter(b'\n', bytes).map(|p| p + 1)) {
        let line = &bytes[line_start..line_end(bytes, line_start)];
        let trim = line
            .iter()
            .position(|b| !b.is_ascii_whitespace())
            .unwrap_or(line.len());
        let candidate = &line[trim..];
        if starts_with_ignore_ascii_case(candidate, b"chapter ") {
            starts.push(line_start + trim);
        }
    }
    starts.sort_unstable();
    starts.dedup();
    starts
}

fn line_end(bytes: &[u8], start: usize) -> usize {
    memchr::memchr(b'\n', &bytes[start..]).map_or(bytes.len(), |p| start + p)
}

fn starts_with_ignore_ascii_case(haystack: &[u8], needle: &[u8]) -> bool {
    haystack.len() >= needle.len() && haystack[..needle.len()].eq_ignore_ascii_case(needle)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_do_not_cross_chapters() {
        let text = "preamble words\nChapter 1\none two three four five\nChapter 2\nsix seven";
        let chunks = chapter_windows(text, 4, 1);
        assert!(chunks.len() >= 4);
        for chunk in chunks {
            let body = chunk.text(text);
            assert!(!(body.contains("Chapter 1") && body.contains("Chapter 2")));
        }
    }

    #[test]
    fn byte_ranges_preserve_utf8() {
        let text = "Chapter 1\nRyan’s café was open.";
        for chunk in chapter_windows(text, 3, 1) {
            assert!(text.is_char_boundary(chunk.byte_start));
            assert!(text.is_char_boundary(chunk.byte_end));
            assert!(!chunk.text(text).is_empty());
        }
    }
}
