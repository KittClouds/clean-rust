use std::mem::size_of;

use hashbrown::HashMap;
use memchr::memchr_iter;
use xxhash_rust::xxh3::Xxh3;
use zerocopy::AsBytes;

use crate::format::{
    checked_u32, content_hash_hex, BinaryStringRef, DocumentIndexUnitKind, FileHeader, UnitRow,
    FILE_MAGIC, NONE_INDEX,
};
use crate::{
    DocumentIndexError, DocumentIndexShardRef, PreparedDocumentIndexShard,
    DOCUMENT_INDEX_SCHEMA_VERSION,
};

pub struct DocumentIndexInput<'a> {
    pub document_id: &'a str,
    pub note_id: Option<&'a str>,
    pub title: &'a str,
    pub text: &'a str,
}

#[derive(Clone, Copy)]
struct ArenaRef {
    offset: usize,
    len: usize,
}

#[derive(Default)]
struct StringArena {
    bytes: Vec<u8>,
    refs: HashMap<String, ArenaRef>,
}

impl StringArena {
    fn intern(&mut self, value: &str) -> ArenaRef {
        if value.is_empty() {
            return ArenaRef { offset: 0, len: 0 };
        }
        if let Some(reference) = self.refs.get(value) {
            return *reference;
        }
        let reference = ArenaRef {
            offset: self.bytes.len(),
            len: value.len(),
        };
        self.bytes.extend_from_slice(value.as_bytes());
        self.refs.insert(value.to_owned(), reference);
        reference
    }
}

#[derive(Clone, Copy)]
struct LogicalUnit {
    kind: DocumentIndexUnitKind,
    depth: u8,
    parent_index: Option<u32>,
    start: usize,
    end: usize,
    ordinal: u32,
    label: ArenaRef,
}

#[derive(Clone, Copy)]
struct HeadingSpan<'a> {
    start: usize,
    level: u8,
    label: &'a str,
}

#[derive(Clone, Copy)]
struct TextSpan {
    start: usize,
    end: usize,
}

pub fn build_document_index_shard(
    input: DocumentIndexInput<'_>,
) -> Result<PreparedDocumentIndexShard, DocumentIndexError> {
    if input.document_id.is_empty() {
        return Err(DocumentIndexError::Invalid("empty document id".to_owned()));
    }
    let text_len = checked_u32(input.text.len(), "document text")?;
    let mut arena = StringArena::default();
    let document_id = arena.intern(input.document_id);
    let note_id = arena.intern(input.note_id.unwrap_or_default());
    let title = arena.intern(input.title);
    let units = build_units(input.text, &mut arena)?;
    let unit_count = checked_u32(units.len(), "unit count")?;
    let unit_offset = size_of::<FileHeader>();
    let unit_bytes = units
        .len()
        .checked_mul(size_of::<UnitRow>())
        .ok_or(DocumentIndexError::InputTooLarge("unit table"))?;
    let arena_offset = unit_offset
        .checked_add(unit_bytes)
        .ok_or(DocumentIndexError::InputTooLarge("arena offset"))?;
    let file_len = arena_offset
        .checked_add(arena.bytes.len())
        .ok_or(DocumentIndexError::InputTooLarge("file length"))?;

    let header = FileHeader {
        magic: FILE_MAGIC,
        schema_version: DOCUMENT_INDEX_SCHEMA_VERSION.to_le_bytes(),
        header_len: u16::try_from(size_of::<FileHeader>())
            .map_err(|_| DocumentIndexError::InputTooLarge("header length"))?
            .to_le_bytes(),
        file_len: (file_len as u64).to_le_bytes(),
        unit_count: unit_count.to_le_bytes(),
        unit_offset: checked_u32(unit_offset, "unit offset")?.to_le_bytes(),
        arena_offset: checked_u32(arena_offset, "arena offset")?.to_le_bytes(),
        arena_len: checked_u32(arena.bytes.len(), "arena length")?.to_le_bytes(),
        text_len: text_len.to_le_bytes(),
        offset_encoding: 1,
        reserved: [0; 3],
        document_id: absolute_string_ref(document_id, arena_offset)?,
        note_id: absolute_string_ref(note_id, arena_offset)?,
        title: absolute_string_ref(title, arena_offset)?,
        source_hash: source_hash(&input),
    };
    let mut bytes = Vec::with_capacity(file_len);
    bytes.extend_from_slice(header.as_bytes());
    for unit in units {
        bytes.extend_from_slice(
            UnitRow {
                kind: unit.kind as u8,
                depth: unit.depth,
                flags: [0; 2],
                parent_index: unit.parent_index.unwrap_or(NONE_INDEX).to_le_bytes(),
                start: checked_u32(unit.start, "unit start")?.to_le_bytes(),
                end: checked_u32(unit.end, "unit end")?.to_le_bytes(),
                ordinal: unit.ordinal.to_le_bytes(),
                label: absolute_string_ref(unit.label, arena_offset)?,
            }
            .as_bytes(),
        );
    }
    bytes.extend_from_slice(&arena.bytes);
    debug_assert_eq!(bytes.len(), file_len);
    let content_hash = content_hash_hex(&bytes);
    Ok(PreparedDocumentIndexShard {
        reference: DocumentIndexShardRef {
            schema_version: DOCUMENT_INDEX_SCHEMA_VERSION,
            document_id: input.document_id.to_owned(),
            note_id: input.note_id.map(str::to_owned),
            content_hash,
            byte_len: bytes.len() as u64,
            unit_count,
        },
        bytes: bytes.into(),
    })
}

fn build_units(
    text: &str,
    arena: &mut StringArena,
) -> Result<Vec<LogicalUnit>, DocumentIndexError> {
    let headings = heading_spans(text);
    let mut units = Vec::with_capacity(1 + headings.len() + paragraph_count_hint(text));
    units.push(LogicalUnit {
        kind: DocumentIndexUnitKind::Document,
        depth: 0,
        parent_index: None,
        start: 0,
        end: text.len(),
        ordinal: 0,
        label: arena.intern("Document"),
    });
    let mut section_indices = Vec::with_capacity(headings.len().max(1));
    if headings.is_empty() {
        section_indices.push(push_unit(
            &mut units,
            LogicalUnit {
                kind: DocumentIndexUnitKind::Section,
                depth: 1,
                parent_index: Some(0),
                start: 0,
                end: text.len(),
                ordinal: 0,
                label: arena.intern("Document body"),
            },
        )?);
    } else {
        let ends = heading_section_ends(&headings, text.len());
        let mut open = Vec::<(u8, u32)>::new();
        for (ordinal, heading) in headings.iter().enumerate() {
            while open
                .last()
                .is_some_and(|(level, _)| *level >= heading.level)
            {
                open.pop();
            }
            let parent_index = open.last().map(|(_, index)| *index).unwrap_or(0);
            let unit_index = push_unit(
                &mut units,
                LogicalUnit {
                    kind: if heading.level == 1 {
                        DocumentIndexUnitKind::Section
                    } else {
                        DocumentIndexUnitKind::Subsection
                    },
                    depth: heading.level,
                    parent_index: Some(parent_index),
                    start: heading.start,
                    end: ends[ordinal],
                    ordinal: ordinal as u32,
                    label: arena.intern(heading.label),
                },
            )?;
            section_indices.push(unit_index);
            open.push((heading.level, unit_index));
        }
    }

    for (ordinal, paragraph) in paragraph_spans(text).into_iter().enumerate() {
        let parent_index = section_indices
            .iter()
            .rev()
            .copied()
            .find(|index| {
                let section = units[*index as usize];
                section.start <= paragraph.start && section.end >= paragraph.start
            })
            .unwrap_or(0);
        let label = format!("Paragraph {}", ordinal + 1);
        let depth = units[parent_index as usize].depth.saturating_add(1);
        push_unit(
            &mut units,
            LogicalUnit {
                kind: DocumentIndexUnitKind::Paragraph,
                depth,
                parent_index: Some(parent_index),
                start: paragraph.start,
                end: paragraph.end,
                ordinal: ordinal as u32,
                label: arena.intern(&label),
            },
        )?;
    }
    Ok(units)
}

fn push_unit(units: &mut Vec<LogicalUnit>, unit: LogicalUnit) -> Result<u32, DocumentIndexError> {
    let index = checked_u32(units.len(), "unit index")?;
    units.push(unit);
    Ok(index)
}

fn heading_spans(text: &str) -> Vec<HeadingSpan<'_>> {
    let mut headings = Vec::new();
    for_each_line(text.as_bytes(), |start, end| {
        let line = &text.as_bytes()[start..end];
        let level = line.iter().take_while(|byte| **byte == b'#').count();
        if !(1..=6).contains(&level) || line.get(level) != Some(&b' ') {
            return;
        }
        let label_start = start + level + 1;
        let label = text[label_start..end].trim();
        if !label.is_empty() {
            headings.push(HeadingSpan {
                start,
                level: level as u8,
                label,
            });
        }
    });
    headings
}

fn heading_section_ends(headings: &[HeadingSpan<'_>], text_end: usize) -> Vec<usize> {
    let mut ends = vec![text_end; headings.len()];
    let mut open = Vec::<usize>::new();
    for index in 0..headings.len() {
        while open
            .last()
            .is_some_and(|open_index| headings[*open_index].level >= headings[index].level)
        {
            ends[open.pop().expect("open heading")] = headings[index].start;
        }
        open.push(index);
    }
    ends
}

fn paragraph_spans(text: &str) -> Vec<TextSpan> {
    let mut paragraphs = Vec::with_capacity(paragraph_count_hint(text));
    let mut paragraph_start = None;
    let mut paragraph_end = 0usize;
    for_each_line(text.as_bytes(), |start, end| {
        let line = &text.as_bytes()[start..end];
        if line.iter().all(u8::is_ascii_whitespace) {
            if let Some(paragraph_start) = paragraph_start.take() {
                paragraphs.push(TextSpan {
                    start: paragraph_start,
                    end: paragraph_end,
                });
            }
        } else {
            paragraph_start.get_or_insert(start);
            paragraph_end = end;
        }
    });
    if let Some(paragraph_start) = paragraph_start {
        paragraphs.push(TextSpan {
            start: paragraph_start,
            end: paragraph_end,
        });
    }
    paragraphs
}

fn paragraph_count_hint(text: &str) -> usize {
    memchr::memmem::find_iter(text.as_bytes(), b"\n\n").count() + 1
}

fn for_each_line(bytes: &[u8], mut callback: impl FnMut(usize, usize)) {
    let mut start = 0usize;
    for newline in memchr_iter(b'\n', bytes) {
        let end = if newline > start && bytes[newline - 1] == b'\r' {
            newline - 1
        } else {
            newline
        };
        callback(start, end);
        start = newline + 1;
    }
    if start <= bytes.len() {
        let end = if bytes.len() > start && bytes[bytes.len() - 1] == b'\r' {
            bytes.len() - 1
        } else {
            bytes.len()
        };
        callback(start, end);
    }
}

fn absolute_string_ref(
    reference: ArenaRef,
    arena_offset: usize,
) -> Result<BinaryStringRef, DocumentIndexError> {
    if reference.len == 0 {
        return BinaryStringRef::new(0, 0);
    }
    BinaryStringRef::new(arena_offset + reference.offset, reference.len)
}

fn source_hash(input: &DocumentIndexInput<'_>) -> [u8; 16] {
    let mut hasher = Xxh3::new();
    for value in [
        input.document_id.as_bytes(),
        input.note_id.unwrap_or_default().as_bytes(),
        input.title.as_bytes(),
        input.text.as_bytes(),
    ] {
        hasher.update(&(value.len() as u64).to_le_bytes());
        hasher.update(value);
    }
    hasher.digest128().to_le_bytes()
}
