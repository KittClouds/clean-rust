//! Key → u64 lookup: a sorted, memory-mapped table plus an in-memory tail.
//!
//! The table covers everything up to a watermark and costs no heap; only entries added since
//! the last compaction live in the hash map. Tables are derived data: a missing, stale or
//! malformed table is ignored and rebuilt from the authoritative records.

use std::fs::File;
use std::path::Path;

use hashbrown::HashMap;
use memmap2::Mmap;

use crate::durable;
use crate::error::{io, Result};

const TABLE_MAGIC: [u8; 8] = *b"KMKTAB02";
const TABLE_HEADER_LEN: usize = 32;

pub struct SortedTable<const N: usize> {
    map: Mmap,
    count: usize,
    covered: u64,
}

impl<const N: usize> SortedTable<N> {
    const RECORD: usize = N + 8;

    /// Opens a table if its header is well-formed; `None` means "rebuild".
    pub fn open(path: &Path) -> Option<Self> {
        let file = File::open(path).ok()?;
        // SAFETY: tables are written once, atomically, and never modified in place.
        let map = unsafe { Mmap::map(&file) }.ok()?;
        if map.len() < TABLE_HEADER_LEN || map[..8] != TABLE_MAGIC {
            return None;
        }
        let key_len = u32::from_le_bytes(map[8..12].try_into().ok()?) as usize;
        let covered = u64::from_le_bytes(map[16..24].try_into().ok()?);
        let count = u64::from_le_bytes(map[24..32].try_into().ok()?) as usize;
        if key_len != N || map.len() != TABLE_HEADER_LEN + count * Self::RECORD {
            return None;
        }
        Some(SortedTable {
            map,
            count,
            covered,
        })
    }

    pub fn covered(&self) -> u64 {
        self.covered
    }

    fn key_at(&self, index: usize) -> &[u8] {
        let start = TABLE_HEADER_LEN + index * Self::RECORD;
        &self.map[start..start + N]
    }

    fn value_at(&self, index: usize) -> u64 {
        let start = TABLE_HEADER_LEN + index * Self::RECORD + N;
        u64::from_le_bytes(self.map[start..start + 8].try_into().unwrap())
    }

    pub fn get(&self, key: &[u8; N]) -> Option<u64> {
        let (mut low, mut high) = (0usize, self.count);
        while low < high {
            let mid = (low + high) / 2;
            match self.key_at(mid).cmp(key.as_slice()) {
                std::cmp::Ordering::Less => low = mid + 1,
                std::cmp::Ordering::Greater => high = mid,
                std::cmp::Ordering::Equal => return Some(self.value_at(mid)),
            }
        }
        None
    }

    /// True when keys are strictly increasing (deep verification).
    pub fn is_sorted_unique(&self) -> bool {
        (1..self.count).all(|i| self.key_at(i - 1) < self.key_at(i))
    }

    /// Writes a table atomically. `entries` may contain duplicate keys; the first value for
    /// each key (in input order) wins, which keeps "earliest occurrence" semantics.
    pub fn write(
        staging: &Path,
        path: &Path,
        covered: u64,
        entries: &mut [([u8; N], u64)],
    ) -> Result<()> {
        entries.sort_by_key(|entry| entry.0);
        let mut out = Vec::with_capacity(TABLE_HEADER_LEN + entries.len() * Self::RECORD);
        out.extend_from_slice(&TABLE_MAGIC);
        out.extend_from_slice(&(N as u32).to_le_bytes());
        out.extend_from_slice(&0u32.to_le_bytes());
        out.extend_from_slice(&covered.to_le_bytes());
        out.extend_from_slice(&0u64.to_le_bytes());
        let mut count = 0u64;
        let mut last: Option<[u8; N]> = None;
        for (key, value) in entries.iter() {
            if last.as_ref() == Some(key) {
                continue;
            }
            out.extend_from_slice(key);
            out.extend_from_slice(&value.to_le_bytes());
            last = Some(*key);
            count += 1;
        }
        out[24..32].copy_from_slice(&count.to_le_bytes());
        durable::publish_with(staging, path, &out, None, Some("index.after_table"))?;
        Ok(())
    }
}

pub struct KeyIndex<const N: usize> {
    pub(crate) table: Option<SortedTable<N>>,
    tail: HashMap<[u8; N], u64>,
}

impl<const N: usize> Default for KeyIndex<N> {
    fn default() -> Self {
        KeyIndex {
            table: None,
            tail: HashMap::new(),
        }
    }
}

impl<const N: usize> KeyIndex<N> {
    pub fn with_table(table: Option<SortedTable<N>>) -> Self {
        KeyIndex {
            table,
            tail: HashMap::new(),
        }
    }

    /// Watermark covered by the table (0 without one).
    pub fn covered(&self) -> u64 {
        self.table.as_ref().map_or(0, SortedTable::covered)
    }

    pub fn get(&self, key: &[u8; N]) -> Option<u64> {
        if let Some(value) = self.tail.get(key) {
            return Some(*value);
        }
        self.table.as_ref().and_then(|t| t.get(key))
    }

    /// Inserts unless the key exists (earliest occurrence wins).
    pub fn insert(&mut self, key: [u8; N], value: u64) {
        if self.get(&key).is_none() {
            self.tail.insert(key, value);
        }
    }

    pub fn tail_len(&self) -> usize {
        self.tail.len()
    }

    /// Drops the table mapping (required on Windows before replacing the file).
    pub fn release_table(&mut self) -> Option<SortedTable<N>> {
        self.table.take()
    }
}

/// Removes a file if present; used to discard stale derived tables.
pub fn remove_if_exists(path: &Path) -> Result<()> {
    match std::fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(io(path)(e)),
    }
}
