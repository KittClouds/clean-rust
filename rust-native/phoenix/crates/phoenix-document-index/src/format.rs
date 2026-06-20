use std::fs::File;
use std::mem::size_of;
use std::ops::Range;
use std::path::Path;

use memmap2::Mmap;
use xxhash_rust::xxh3::xxh3_128;
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

use crate::{io_error, DocumentIndexError, DocumentIndexShardRef, DOCUMENT_INDEX_SCHEMA_VERSION};

pub(crate) const FILE_MAGIC: [u8; 8] = *b"PHXDIDX1";
pub(crate) const NONE_INDEX: u32 = u32::MAX;

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct BinaryStringRef {
    pub(crate) offset: [u8; 4],
    pub(crate) len: [u8; 4],
}

impl BinaryStringRef {
    pub(crate) fn new(offset: usize, len: usize) -> Result<Self, DocumentIndexError> {
        Ok(Self {
            offset: checked_u32(offset, "string offset")?.to_le_bytes(),
            len: checked_u32(len, "string length")?.to_le_bytes(),
        })
    }

    fn range(self) -> Result<Range<usize>, DocumentIndexError> {
        let start = u32::from_le_bytes(self.offset) as usize;
        let end = start
            .checked_add(u32::from_le_bytes(self.len) as usize)
            .ok_or_else(|| DocumentIndexError::Invalid("string range overflow".to_owned()))?;
        Ok(start..end)
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct FileHeader {
    pub(crate) magic: [u8; 8],
    pub(crate) schema_version: [u8; 2],
    pub(crate) header_len: [u8; 2],
    pub(crate) file_len: [u8; 8],
    pub(crate) unit_count: [u8; 4],
    pub(crate) unit_offset: [u8; 4],
    pub(crate) arena_offset: [u8; 4],
    pub(crate) arena_len: [u8; 4],
    pub(crate) text_len: [u8; 4],
    pub(crate) offset_encoding: u8,
    pub(crate) reserved: [u8; 3],
    pub(crate) document_id: BinaryStringRef,
    pub(crate) note_id: BinaryStringRef,
    pub(crate) title: BinaryStringRef,
    pub(crate) source_hash: [u8; 16],
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct UnitRow {
    pub(crate) kind: u8,
    pub(crate) depth: u8,
    pub(crate) flags: [u8; 2],
    pub(crate) parent_index: [u8; 4],
    pub(crate) start: [u8; 4],
    pub(crate) end: [u8; 4],
    pub(crate) ordinal: [u8; 4],
    pub(crate) label: BinaryStringRef,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u8)]
pub enum DocumentIndexUnitKind {
    Document = 1,
    Section = 2,
    Subsection = 3,
    Paragraph = 4,
}

impl DocumentIndexUnitKind {
    pub(crate) fn from_u8(value: u8) -> Result<Self, DocumentIndexError> {
        match value {
            1 => Ok(Self::Document),
            2 => Ok(Self::Section),
            3 => Ok(Self::Subsection),
            4 => Ok(Self::Paragraph),
            _ => Err(DocumentIndexError::Invalid(format!(
                "unknown unit kind {value}"
            ))),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DocumentIndexUnit<'a> {
    pub index: u32,
    pub kind: DocumentIndexUnitKind,
    pub depth: u8,
    pub parent_index: Option<u32>,
    pub start: u32,
    pub end: u32,
    pub ordinal: u32,
    pub label: &'a str,
}

pub struct MmapDocumentIndex {
    mmap: Mmap,
    header: FileHeader,
    content_hash: String,
}

impl MmapDocumentIndex {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, DocumentIndexError> {
        let path = path.as_ref();
        let file = File::open(path).map_err(|error| io_error(path, error))?;
        // Shards are immutable and published by same-directory atomic rename.
        let mmap = unsafe { Mmap::map(&file) }.map_err(|error| io_error(path, error))?;
        Self::from_mmap(mmap)
    }

    pub fn open_verified(
        path: impl AsRef<Path>,
        reference: &DocumentIndexShardRef,
    ) -> Result<Self, DocumentIndexError> {
        let index = Self::open(path)?;
        index.verify_reference(reference)?;
        Ok(index)
    }

    fn from_mmap(mmap: Mmap) -> Result<Self, DocumentIndexError> {
        let header = row_at::<FileHeader>(&mmap, 0)?;
        validate_header(&mmap, header)?;
        let content_hash = content_hash_hex(&mmap);
        let index = Self {
            mmap,
            header,
            content_hash,
        };
        index.validate_rows()?;
        Ok(index)
    }

    pub fn schema_version(&self) -> u16 {
        u16::from_le_bytes(self.header.schema_version)
    }

    pub fn text_len(&self) -> u32 {
        u32::from_le_bytes(self.header.text_len)
    }

    pub fn unit_count(&self) -> u32 {
        u32::from_le_bytes(self.header.unit_count)
    }

    pub fn content_hash(&self) -> &str {
        &self.content_hash
    }

    pub fn document_id(&self) -> Result<&str, DocumentIndexError> {
        self.string(self.header.document_id)
    }

    pub fn note_id(&self) -> Result<Option<&str>, DocumentIndexError> {
        let value = self.string(self.header.note_id)?;
        Ok((!value.is_empty()).then_some(value))
    }

    pub fn title(&self) -> Result<&str, DocumentIndexError> {
        self.string(self.header.title)
    }

    pub fn unit(&self, index: u32) -> Result<DocumentIndexUnit<'_>, DocumentIndexError> {
        if index >= self.unit_count() {
            return Err(DocumentIndexError::Invalid(format!(
                "unit index {index} out of bounds"
            )));
        }
        let unit_offset = u32::from_le_bytes(self.header.unit_offset) as usize;
        let offset = unit_offset + index as usize * size_of::<UnitRow>();
        let row = row_at::<UnitRow>(&self.mmap, offset)?;
        let parent = u32::from_le_bytes(row.parent_index);
        Ok(DocumentIndexUnit {
            index,
            kind: DocumentIndexUnitKind::from_u8(row.kind)?,
            depth: row.depth,
            parent_index: (parent != NONE_INDEX).then_some(parent),
            start: u32::from_le_bytes(row.start),
            end: u32::from_le_bytes(row.end),
            ordinal: u32::from_le_bytes(row.ordinal),
            label: self.string(row.label)?,
        })
    }

    pub fn units(
        &self,
    ) -> impl Iterator<Item = Result<DocumentIndexUnit<'_>, DocumentIndexError>> + '_ {
        (0..self.unit_count()).map(|index| self.unit(index))
    }

    fn verify_reference(
        &self,
        reference: &DocumentIndexShardRef,
    ) -> Result<(), DocumentIndexError> {
        if reference.schema_version != self.schema_version()
            || reference.byte_len != self.mmap.len() as u64
            || reference.unit_count != self.unit_count()
            || reference.content_hash != self.content_hash
            || reference.document_id != self.document_id()?
            || reference.note_id.as_deref() != self.note_id()?
        {
            return Err(DocumentIndexError::Invalid(
                "shard reference does not match mapped content".to_owned(),
            ));
        }
        Ok(())
    }

    fn validate_rows(&self) -> Result<(), DocumentIndexError> {
        for index in 0..self.unit_count() {
            let unit = self.unit(index)?;
            if unit.start > unit.end || unit.end > self.text_len() {
                return Err(DocumentIndexError::Invalid(format!(
                    "unit {index} has invalid source range"
                )));
            }
            if unit.parent_index.is_some_and(|parent| parent >= index) {
                return Err(DocumentIndexError::Invalid(format!(
                    "unit {index} has invalid parent"
                )));
            }
        }
        if self.document_id()?.is_empty() {
            return Err(DocumentIndexError::Invalid("empty document id".to_owned()));
        }
        Ok(())
    }

    fn string(&self, reference: BinaryStringRef) -> Result<&str, DocumentIndexError> {
        let range = reference.range()?;
        if range.is_empty() {
            return Ok("");
        }
        let arena_start = u32::from_le_bytes(self.header.arena_offset) as usize;
        let arena_end = arena_start + u32::from_le_bytes(self.header.arena_len) as usize;
        if range.start < arena_start || range.end > arena_end {
            return Err(DocumentIndexError::Invalid(
                "string reference outside arena".to_owned(),
            ));
        }
        let bytes = self
            .mmap
            .get(range)
            .ok_or_else(|| DocumentIndexError::Invalid("string range outside shard".to_owned()))?;
        std::str::from_utf8(bytes)
            .map_err(|error| DocumentIndexError::Invalid(format!("invalid string UTF-8: {error}")))
    }
}

pub(crate) fn content_hash_hex(bytes: &[u8]) -> String {
    format!("{:032x}", xxh3_128(bytes))
}

pub(crate) fn checked_u32(value: usize, field: &'static str) -> Result<u32, DocumentIndexError> {
    u32::try_from(value).map_err(|_| DocumentIndexError::InputTooLarge(field))
}

fn validate_header(bytes: &[u8], header: FileHeader) -> Result<(), DocumentIndexError> {
    let header_len = u16::from_le_bytes(header.header_len) as usize;
    let file_len = u64::from_le_bytes(header.file_len) as usize;
    let unit_count = u32::from_le_bytes(header.unit_count) as usize;
    let unit_offset = u32::from_le_bytes(header.unit_offset) as usize;
    let arena_offset = u32::from_le_bytes(header.arena_offset) as usize;
    let arena_len = u32::from_le_bytes(header.arena_len) as usize;
    let unit_end = unit_offset
        .checked_add(unit_count.saturating_mul(size_of::<UnitRow>()))
        .ok_or_else(|| DocumentIndexError::Invalid("unit table overflow".to_owned()))?;
    let arena_end = arena_offset
        .checked_add(arena_len)
        .ok_or_else(|| DocumentIndexError::Invalid("arena overflow".to_owned()))?;
    if header.magic != FILE_MAGIC
        || u16::from_le_bytes(header.schema_version) != DOCUMENT_INDEX_SCHEMA_VERSION
        || header_len != size_of::<FileHeader>()
        || file_len != bytes.len()
        || unit_offset != header_len
        || unit_end != arena_offset
        || arena_end != bytes.len()
        || header.offset_encoding != 1
    {
        return Err(DocumentIndexError::Invalid(
            "invalid document index header or table layout".to_owned(),
        ));
    }
    Ok(())
}

fn row_at<T>(bytes: &[u8], offset: usize) -> Result<T, DocumentIndexError>
where
    T: FromBytes + Unaligned + Copy,
{
    let end = offset
        .checked_add(size_of::<T>())
        .ok_or_else(|| DocumentIndexError::Invalid("row range overflow".to_owned()))?;
    Ref::<_, T>::new_unaligned(
        bytes
            .get(offset..end)
            .ok_or_else(|| DocumentIndexError::Invalid("row outside shard".to_owned()))?,
    )
    .map(|value| *value)
    .ok_or_else(|| DocumentIndexError::Invalid("invalid binary row".to_owned()))
}
