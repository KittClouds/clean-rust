use std::{
    fs::File,
    path::{Path, PathBuf},
};

use hashbrown::HashMap;
use memchr::{memchr, memchr_iter};
use memmap2::{Mmap, MmapOptions};

use crate::{CorpusError, Result, error::io};

pub struct MappedTsv {
    path: PathBuf,
    mmap: Mmap,
    header_end: usize,
    columns: HashMap<Box<[u8]>, usize>,
    column_count: usize,
}

impl MappedTsv {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        let file = File::open(&path).map_err(|error| io(&path, error))?;
        let metadata = file.metadata().map_err(|error| io(&path, error))?;
        if metadata.len() == 0 {
            return Err(CorpusError::Tsv {
                path,
                row: 0,
                detail: "empty file".into(),
            });
        }
        // SAFETY: the map is read-only and the corpus contract forbids mutation while read.
        let mmap = unsafe { MmapOptions::new().map(&file) }.map_err(|error| io(&path, error))?;
        let header_end = memchr(b'\n', &mmap).unwrap_or(mmap.len());
        let header = trim_cr(&mmap[..header_end]);
        let mut columns = HashMap::new();
        for (index, field) in split_fields(header).enumerate() {
            if columns.insert(field.into(), index).is_some() {
                return Err(CorpusError::Tsv {
                    path,
                    row: 0,
                    detail: "duplicate header column".into(),
                });
            }
        }
        let column_count = columns.len();
        Ok(Self {
            path,
            mmap,
            header_end,
            columns,
            column_count,
        })
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    #[must_use]
    pub fn column_count(&self) -> usize {
        self.column_count
    }

    pub fn column(&self, name: &str) -> Result<usize> {
        self.columns
            .get(name.as_bytes())
            .copied()
            .ok_or_else(|| CorpusError::Tsv {
                path: self.path.clone(),
                row: 0,
                detail: format!("missing column {name}"),
            })
    }

    #[must_use]
    pub fn rows(&self) -> Rows<'_> {
        let start = (self.header_end + 1).min(self.mmap.len());
        Rows {
            bytes: &self.mmap,
            cursor: start,
            row_number: 1,
            expected_fields: self.column_count,
        }
    }
}

#[derive(Clone, Copy)]
pub struct Row<'a> {
    bytes: &'a [u8],
    number: usize,
}

impl<'a> Row<'a> {
    #[must_use]
    pub fn number(self) -> usize {
        self.number
    }

    pub fn fields(self) -> impl Iterator<Item = &'a [u8]> {
        split_fields(self.bytes)
    }

    #[must_use]
    pub fn field(self, index: usize) -> Option<&'a [u8]> {
        self.fields().nth(index)
    }
}

pub struct Rows<'a> {
    bytes: &'a [u8],
    cursor: usize,
    row_number: usize,
    expected_fields: usize,
}

impl<'a> Iterator for Rows<'a> {
    type Item = Result<Row<'a>>;

    fn next(&mut self) -> Option<Self::Item> {
        while self.cursor < self.bytes.len() {
            let remaining = &self.bytes[self.cursor..];
            let width = memchr(b'\n', remaining).unwrap_or(remaining.len());
            let start = self.cursor;
            self.cursor += width + usize::from(width < remaining.len());
            self.row_number += 1;
            let line = trim_cr(&self.bytes[start..start + width]);
            if line.is_empty() {
                continue;
            }
            let actual = memchr_iter(b'\t', line).count() + 1;
            if actual != self.expected_fields {
                return Some(Err(CorpusError::Contract(format!(
                    "row {} has {} fields, expected {}",
                    self.row_number, actual, self.expected_fields
                ))));
            }
            return Some(Ok(Row {
                bytes: line,
                number: self.row_number,
            }));
        }
        None
    }
}

fn trim_cr(bytes: &[u8]) -> &[u8] {
    bytes.strip_suffix(b"\r").unwrap_or(bytes)
}

fn split_fields(bytes: &[u8]) -> impl Iterator<Item = &[u8]> {
    bytes.split(|byte| *byte == b'\t')
}

macro_rules! parse_unsigned {
    ($name:ident, $type:ty) => {
        pub fn $name(bytes: &[u8]) -> Option<$type> {
            if bytes.is_empty() {
                return None;
            }
            let mut value: $type = 0;
            for &byte in bytes {
                if !byte.is_ascii_digit() {
                    return None;
                }
                value = value.checked_mul(10)?.checked_add((byte - b'0') as $type)?;
            }
            Some(value)
        }
    };
}

parse_unsigned!(parse_u16, u16);
parse_unsigned!(parse_u64, u64);

pub fn parse_i16(bytes: &[u8]) -> Option<i16> {
    let (negative, digits) = match bytes.first() {
        Some(b'-') => (true, &bytes[1..]),
        Some(b'+') => (false, &bytes[1..]),
        Some(_) => (false, bytes),
        None => return None,
    };
    let magnitude = parse_u16(digits)?;
    if negative {
        i16::try_from(magnitude).ok()?.checked_neg()
    } else {
        i16::try_from(magnitude).ok()
    }
}

pub fn parse_i64(bytes: &[u8]) -> Option<i64> {
    let (negative, digits) = match bytes.first() {
        Some(b'-') => (true, &bytes[1..]),
        Some(b'+') => (false, &bytes[1..]),
        Some(_) => (false, bytes),
        None => return None,
    };
    let magnitude = parse_u64(digits)?;
    if negative {
        if magnitude == (i64::MAX as u64) + 1 {
            Some(i64::MIN)
        } else {
            i64::try_from(magnitude).ok()?.checked_neg()
        }
    } else {
        i64::try_from(magnitude).ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn maps_and_slices_rows_without_copying_fields() {
        let mut file = NamedTempFile::new().unwrap();
        file.write_all(b"id\tname\r\n42\tAPPROACH\r\n").unwrap();
        let table = MappedTsv::open(file.path()).unwrap();
        let row = table.rows().next().unwrap().unwrap();
        assert_eq!(row.field(table.column("id").unwrap()), Some(&b"42"[..]));
        assert_eq!(
            row.field(table.column("name").unwrap()),
            Some(&b"APPROACH"[..])
        );
        assert_eq!(parse_u64(b"18446744073709551615"), Some(u64::MAX));
    }
}
