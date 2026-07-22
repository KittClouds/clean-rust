use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

use hashbrown::HashMap;
use memmap2::{Mmap, MmapMut, MmapOptions};

use crate::error::io_error;
use crate::{InferenceArtifactError, Result};

const INDEX_MAGIC: [u8; 8] = *b"PHXERI01";
const VALUES_MAGIC: [u8; 8] = *b"PHXERV01";
const VERSION: u32 = 1;
const INDEX_HEADER_BYTES: usize = 4_096;
const VALUES_HEADER_BYTES: usize = 64;
const SLOT_BYTES: usize = 48;
const SLOT_STATE_OFFSET: usize = 40;
const SLOT_OCCUPIED: u8 = 1;
const MIN_CAPACITY: usize = 4_096;
const MAX_LOAD_NUMERATOR: usize = 7;
const MAX_LOAD_DENOMINATOR: usize = 10;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EmbeddingCacheMiss {
    pub key: [u8; 32],
    pub positions: Box<[usize]>,
}

#[derive(Debug)]
pub struct EmbeddingCacheResolution {
    pub values: Vec<f32>,
    pub hit_rows: usize,
    pub misses: Vec<EmbeddingCacheMiss>,
}

impl EmbeddingCacheResolution {
    pub fn unique_miss_count(&self) -> usize {
        self.misses.len()
    }

    pub fn missing_row_count(&self) -> usize {
        self.misses.iter().map(|miss| miss.positions.len()).sum()
    }
}

pub struct EmbeddingRowCache {
    root: PathBuf,
    namespace: [u8; 32],
    columns: usize,
    index_file: File,
    index: Option<MmapMut>,
    values_file: File,
    capacity: usize,
    len: usize,
}

impl EmbeddingRowCache {
    pub fn open(
        root: impl AsRef<Path>,
        namespace: [u8; 32],
        columns: usize,
        expected_rows: usize,
    ) -> Result<Self> {
        if columns == 0 || columns > u32::MAX as usize {
            return Err(InferenceArtifactError::InvalidArtifact(
                "embedding cache columns must fit a nonzero u32".into(),
            ));
        }
        let root = root.as_ref().join(hex_digest(&namespace));
        std::fs::create_dir_all(&root).map_err(|source| io_error(&root, source))?;
        let index_path = root.join("rows.index");
        recover_index_replacement(&root, &index_path)?;
        let values_path = root.join("rows.f32");
        let creating = !index_path.exists();
        let index_file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&index_path)
            .map_err(|source| io_error(&index_path, source))?;
        let values_creating = !values_path.exists();
        let mut values_file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&values_path)
            .map_err(|source| io_error(&values_path, source))?;
        if creating != values_creating {
            return Err(InferenceArtifactError::InvalidArtifact(format!(
                "partial embedding cache at {}",
                root.display()
            )));
        }
        if creating {
            let capacity = capacity_for(expected_rows.max(1))?;
            initialize_index(&index_file, namespace, columns, capacity, &index_path)?;
            initialize_values(&values_file, namespace, columns, &values_path)?;
        }
        let (capacity, len) = read_index_header(&index_file, namespace, columns, &index_path)?;
        let value_rows = validate_values(&values_file, namespace, columns, len, &values_path)?;
        if value_rows > len {
            let recovered_length = VALUES_HEADER_BYTES
                + len
                    .checked_mul(columns)
                    .and_then(|count| count.checked_mul(std::mem::size_of::<f32>()))
                    .ok_or_else(|| {
                        InferenceArtifactError::InvalidArtifact(
                            "embedding values recovery size overflow".into(),
                        )
                    })?;
            values_file
                .set_len(recovered_length as u64)
                .map_err(|source| io_error(&values_path, source))?;
            write_u64_at(&mut values_file, 16, len as u64, &values_path)?;
            values_file
                .sync_data()
                .map_err(|source| io_error(&values_path, source))?;
        }
        let index = map_index_mut(&index_file, &index_path)?;
        let mut cache = Self {
            root,
            namespace,
            columns,
            index_file,
            index: Some(index),
            values_file,
            capacity,
            len,
        };
        cache.ensure_capacity(expected_rows)?;
        Ok(cache)
    }

    pub fn resolve(&self, keys: &[[u8; 32]]) -> Result<EmbeddingCacheResolution> {
        let value_count = keys.len().checked_mul(self.columns).ok_or_else(|| {
            InferenceArtifactError::InvalidArtifact("embedding output size overflow".into())
        })?;
        let mut output = vec![0.0_f32; value_count];
        let values = self.map_values()?;
        let mut misses = HashMap::<[u8; 32], Vec<usize>>::new();
        let mut hit_rows = 0;
        for (position, key) in keys.iter().enumerate() {
            if let Some(row) = self.lookup(key)? {
                let source = cached_row(&values, row, self.columns)?;
                output[position * self.columns..(position + 1) * self.columns]
                    .copy_from_slice(source);
                hit_rows += 1;
            } else {
                misses.entry(*key).or_default().push(position);
            }
        }
        let mut misses = misses
            .into_iter()
            .map(|(key, positions)| EmbeddingCacheMiss {
                key,
                positions: positions.into_boxed_slice(),
            })
            .collect::<Vec<_>>();
        misses.sort_unstable_by_key(|miss| miss.positions[0]);
        Ok(EmbeddingCacheResolution {
            values: output,
            hit_rows,
            misses,
        })
    }

    pub fn install(
        &mut self,
        resolution: &mut EmbeddingCacheResolution,
        encoded_unique_rows: &[f32],
    ) -> Result<u64> {
        let unique_rows = resolution.unique_miss_count();
        if encoded_unique_rows.len() != unique_rows.saturating_mul(self.columns)
            || encoded_unique_rows.iter().any(|value| !value.is_finite())
        {
            return Err(InferenceArtifactError::InvalidArtifact(
                "encoded cache miss matrix has invalid shape or values".into(),
            ));
        }
        if unique_rows == 0 {
            return Ok(0);
        }
        self.ensure_capacity(unique_rows)?;
        let first_row = self.len;
        self.values_file
            .seek(SeekFrom::End(0))
            .and_then(|_| {
                self.values_file
                    .write_all(bytemuck::cast_slice(encoded_unique_rows))
            })
            .and_then(|_| self.values_file.flush())
            .map_err(|source| io_error(self.root.join("rows.f32"), source))?;
        write_u64_at(
            &mut self.values_file,
            16,
            (first_row + unique_rows) as u64,
            &self.root.join("rows.f32"),
        )?;
        self.values_file
            .sync_data()
            .map_err(|source| io_error(self.root.join("rows.f32"), source))?;

        for (miss_index, miss) in resolution.misses.iter().enumerate() {
            let row =
                &encoded_unique_rows[miss_index * self.columns..(miss_index + 1) * self.columns];
            for &position in miss.positions.iter() {
                resolution.values[position * self.columns..(position + 1) * self.columns]
                    .copy_from_slice(row);
            }
            self.insert_slot(miss.key, first_row + miss_index)?;
        }
        self.len += unique_rows;
        let map = self.index.as_mut().expect("embedding index mapped");
        map[32..40].copy_from_slice(&(self.len as u64).to_le_bytes());
        map.flush()
            .map_err(|source| io_error(self.root.join("rows.index"), source))?;
        self.index_file
            .sync_data()
            .map_err(|source| io_error(self.root.join("rows.index"), source))?;
        Ok(std::mem::size_of_val(encoded_unique_rows) as u64)
    }

    pub fn row_count(&self) -> usize {
        self.len
    }

    fn lookup(&self, key: &[u8; 32]) -> Result<Option<usize>> {
        let map = self.index.as_ref().expect("embedding index mapped");
        let mut slot = slot_home(key, self.capacity);
        for _ in 0..self.capacity {
            let offset = INDEX_HEADER_BYTES + slot * SLOT_BYTES;
            match map[offset + SLOT_STATE_OFFSET] {
                0 => return Ok(None),
                SLOT_OCCUPIED if map[offset..offset + 32] == key[..] => {
                    let row = read_u64(&map[offset + 32..offset + 40])? as usize;
                    if row >= self.len {
                        return Err(InferenceArtifactError::InvalidArtifact(
                            "embedding cache index points beyond values".into(),
                        ));
                    }
                    return Ok(Some(row));
                }
                SLOT_OCCUPIED => slot = (slot + 1) & (self.capacity - 1),
                state => {
                    return Err(InferenceArtifactError::InvalidArtifact(format!(
                        "embedding cache slot has unknown state {state}"
                    )));
                }
            }
        }
        Err(InferenceArtifactError::InvalidArtifact(
            "embedding cache probe exhausted every slot".into(),
        ))
    }

    fn insert_slot(&mut self, key: [u8; 32], row: usize) -> Result<()> {
        if self.lookup(&key)?.is_some() {
            return Ok(());
        }
        let map = self.index.as_mut().expect("embedding index mapped");
        let mut slot = slot_home(&key, self.capacity);
        for _ in 0..self.capacity {
            let offset = INDEX_HEADER_BYTES + slot * SLOT_BYTES;
            if map[offset + SLOT_STATE_OFFSET] == 0 {
                map[offset..offset + 32].copy_from_slice(&key);
                map[offset + 32..offset + 40].copy_from_slice(&(row as u64).to_le_bytes());
                map[offset + SLOT_STATE_OFFSET] = SLOT_OCCUPIED;
                return Ok(());
            }
            slot = (slot + 1) & (self.capacity - 1);
        }
        Err(InferenceArtifactError::InvalidArtifact(
            "embedding cache has no free slot".into(),
        ))
    }

    fn map_values(&self) -> Result<Mmap> {
        // SAFETY: values are append-only and no append occurs while this map is alive.
        unsafe { MmapOptions::new().map(&self.values_file) }
            .map_err(|source| io_error(self.root.join("rows.f32"), source))
    }

    fn ensure_capacity(&mut self, additional: usize) -> Result<()> {
        let required = self.len.checked_add(additional).ok_or_else(|| {
            InferenceArtifactError::InvalidArtifact("embedding cache row count overflow".into())
        })?;
        if required.saturating_mul(MAX_LOAD_DENOMINATOR)
            <= self.capacity.saturating_mul(MAX_LOAD_NUMERATOR)
        {
            return Ok(());
        }
        let new_capacity = capacity_for(required)?;
        self.rehash(new_capacity)
    }

    fn rehash(&mut self, new_capacity: usize) -> Result<()> {
        let old_map = self.index.take().expect("embedding index mapped");
        let stage_path = self.root.join("rows.index.next");
        let final_path = self.root.join("rows.index");
        let previous_path = self.root.join("rows.index.previous");
        if stage_path.exists() {
            std::fs::remove_file(&stage_path).map_err(|source| io_error(&stage_path, source))?;
        }
        let stage = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&stage_path)
            .map_err(|source| io_error(&stage_path, source))?;
        initialize_index(
            &stage,
            self.namespace,
            self.columns,
            new_capacity,
            &stage_path,
        )?;
        let mut next = map_index_mut(&stage, &stage_path)?;
        for slot in 0..self.capacity {
            let offset = INDEX_HEADER_BYTES + slot * SLOT_BYTES;
            if old_map[offset + SLOT_STATE_OFFSET] != SLOT_OCCUPIED {
                continue;
            }
            let mut key = [0_u8; 32];
            key.copy_from_slice(&old_map[offset..offset + 32]);
            let row = read_u64(&old_map[offset + 32..offset + 40])? as usize;
            insert_into_map(&mut next, new_capacity, key, row)?;
        }
        next[32..40].copy_from_slice(&(self.len as u64).to_le_bytes());
        next.flush()
            .map_err(|source| io_error(&stage_path, source))?;
        stage
            .sync_all()
            .map_err(|source| io_error(&stage_path, source))?;
        drop(next);
        drop(old_map);
        let placeholder = self
            .values_file
            .try_clone()
            .map_err(|source| io_error(self.root.join("rows.f32"), source))?;
        let old_index_file = std::mem::replace(&mut self.index_file, placeholder);
        drop(old_index_file);
        drop(stage);
        if previous_path.exists() {
            std::fs::remove_file(&previous_path)
                .map_err(|source| io_error(&previous_path, source))?;
        }
        std::fs::rename(&final_path, &previous_path)
            .map_err(|source| io_error(&previous_path, source))?;
        if let Err(source) = std::fs::rename(&stage_path, &final_path) {
            let _ = std::fs::rename(&previous_path, &final_path);
            return Err(io_error(&final_path, source));
        }
        std::fs::remove_file(&previous_path).map_err(|source| io_error(&previous_path, source))?;
        self.index_file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&final_path)
            .map_err(|source| io_error(&final_path, source))?;
        self.index = Some(map_index_mut(&self.index_file, &final_path)?);
        self.capacity = new_capacity;
        Ok(())
    }
}

fn recover_index_replacement(root: &Path, index_path: &Path) -> Result<()> {
    let previous = root.join("rows.index.previous");
    if !index_path.exists() && previous.exists() {
        std::fs::rename(&previous, index_path).map_err(|source| io_error(index_path, source))?;
    } else if index_path.exists() && previous.exists() {
        std::fs::remove_file(&previous).map_err(|source| io_error(&previous, source))?;
    }
    Ok(())
}

pub fn embedding_namespace(parts: &[&str]) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix.embedding-row-cache.namespace.v1\0");
    for part in parts {
        hasher.update(&(part.len() as u64).to_le_bytes());
        hasher.update(part.as_bytes());
    }
    *hasher.finalize().as_bytes()
}

pub fn embedding_row_key(namespace: &[u8; 32], role: &str, text: &str) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix.embedding-row-cache.row.v1\0");
    hasher.update(namespace);
    hasher.update(&(role.len() as u64).to_le_bytes());
    hasher.update(role.as_bytes());
    hasher.update(&(text.len() as u64).to_le_bytes());
    hasher.update(text.as_bytes());
    *hasher.finalize().as_bytes()
}

fn initialize_index(
    file: &File,
    namespace: [u8; 32],
    columns: usize,
    capacity: usize,
    path: &Path,
) -> Result<()> {
    let length = INDEX_HEADER_BYTES
        .checked_add(capacity.checked_mul(SLOT_BYTES).ok_or_else(|| {
            InferenceArtifactError::InvalidArtifact("embedding index size overflow".into())
        })?)
        .ok_or_else(|| {
            InferenceArtifactError::InvalidArtifact("embedding index length overflow".into())
        })?;
    file.set_len(length as u64)
        .map_err(|source| io_error(path, source))?;
    let mut map = map_index_mut(file, path)?;
    map[0..8].copy_from_slice(&INDEX_MAGIC);
    map[8..12].copy_from_slice(&VERSION.to_le_bytes());
    map[12..16].copy_from_slice(&(INDEX_HEADER_BYTES as u32).to_le_bytes());
    map[16..20].copy_from_slice(&(columns as u32).to_le_bytes());
    map[20..24].copy_from_slice(&(SLOT_BYTES as u32).to_le_bytes());
    map[24..32].copy_from_slice(&(capacity as u64).to_le_bytes());
    map[32..40].copy_from_slice(&0_u64.to_le_bytes());
    map[40..72].copy_from_slice(&namespace);
    map.flush().map_err(|source| io_error(path, source))?;
    Ok(())
}

fn initialize_values(file: &File, namespace: [u8; 32], columns: usize, path: &Path) -> Result<()> {
    file.set_len(VALUES_HEADER_BYTES as u64)
        .map_err(|source| io_error(path, source))?;
    let mut file = file.try_clone().map_err(|source| io_error(path, source))?;
    file.seek(SeekFrom::Start(0))
        .and_then(|_| file.write_all(&VALUES_MAGIC))
        .and_then(|_| file.write_all(&VERSION.to_le_bytes()))
        .and_then(|_| file.write_all(&(columns as u32).to_le_bytes()))
        .and_then(|_| file.write_all(&0_u64.to_le_bytes()))
        .and_then(|_| file.write_all(&namespace))
        .and_then(|_| file.write_all(&[0_u8; 8]))
        .and_then(|_| file.flush())
        .map_err(|source| io_error(path, source))?;
    Ok(())
}

fn read_index_header(
    file: &File,
    namespace: [u8; 32],
    columns: usize,
    path: &Path,
) -> Result<(usize, usize)> {
    let mut header = [0_u8; 72];
    let mut file = file.try_clone().map_err(|source| io_error(path, source))?;
    file.seek(SeekFrom::Start(0))
        .and_then(|_| file.read_exact(&mut header))
        .map_err(|source| io_error(path, source))?;
    let capacity = read_u64(&header[24..32])? as usize;
    let len = read_u64(&header[32..40])? as usize;
    if header[0..8] != INDEX_MAGIC
        || read_u32(&header[8..12])? != VERSION
        || read_u32(&header[12..16])? as usize != INDEX_HEADER_BYTES
        || read_u32(&header[16..20])? as usize != columns
        || read_u32(&header[20..24])? as usize != SLOT_BYTES
        || header[40..72] != namespace
        || !capacity.is_power_of_two()
        || capacity < MIN_CAPACITY
        || len > capacity
    {
        return Err(InferenceArtifactError::InvalidArtifact(format!(
            "non-canonical embedding index at {}",
            path.display()
        )));
    }
    let expected = INDEX_HEADER_BYTES + capacity * SLOT_BYTES;
    if file
        .metadata()
        .map_err(|source| io_error(path, source))?
        .len()
        != expected as u64
    {
        return Err(InferenceArtifactError::InvalidArtifact(
            "embedding index length disagrees with header".into(),
        ));
    }
    Ok((capacity, len))
}

fn validate_values(
    file: &File,
    namespace: [u8; 32],
    columns: usize,
    index_len: usize,
    path: &Path,
) -> Result<usize> {
    let mut header = [0_u8; VALUES_HEADER_BYTES];
    let mut file = file.try_clone().map_err(|source| io_error(path, source))?;
    file.seek(SeekFrom::Start(0))
        .and_then(|_| file.read_exact(&mut header))
        .map_err(|source| io_error(path, source))?;
    let rows = read_u64(&header[16..24])? as usize;
    let bytes = rows
        .checked_mul(columns)
        .and_then(|count| count.checked_mul(std::mem::size_of::<f32>()))
        .and_then(|bytes| bytes.checked_add(VALUES_HEADER_BYTES))
        .ok_or_else(|| {
            InferenceArtifactError::InvalidArtifact("embedding values size overflow".into())
        })?;
    if header[0..8] != VALUES_MAGIC
        || read_u32(&header[8..12])? != VERSION
        || read_u32(&header[12..16])? as usize != columns
        || header[24..56] != namespace
        || rows < index_len
        || file
            .metadata()
            .map_err(|source| io_error(path, source))?
            .len()
            != bytes as u64
    {
        return Err(InferenceArtifactError::InvalidArtifact(format!(
            "non-canonical embedding values at {}",
            path.display()
        )));
    }
    Ok(rows)
}

fn capacity_for(rows: usize) -> Result<usize> {
    let requested = rows
        .checked_mul(MAX_LOAD_DENOMINATOR)
        .and_then(|value| value.checked_add(MAX_LOAD_NUMERATOR - 1))
        .map(|value| value / MAX_LOAD_NUMERATOR)
        .ok_or_else(|| {
            InferenceArtifactError::InvalidArtifact("embedding cache capacity overflow".into())
        })?;
    requested
        .max(MIN_CAPACITY)
        .checked_next_power_of_two()
        .ok_or_else(|| {
            InferenceArtifactError::InvalidArtifact("embedding cache capacity overflow".into())
        })
}

fn map_index_mut(file: &File, path: &Path) -> Result<MmapMut> {
    // SAFETY: the cache owns the only writer in the index-build lane.
    unsafe { MmapOptions::new().map_mut(file) }.map_err(|source| io_error(path, source))
}

fn insert_into_map(map: &mut MmapMut, capacity: usize, key: [u8; 32], row: usize) -> Result<()> {
    let mut slot = slot_home(&key, capacity);
    for _ in 0..capacity {
        let offset = INDEX_HEADER_BYTES + slot * SLOT_BYTES;
        if map[offset + SLOT_STATE_OFFSET] == 0 {
            map[offset..offset + 32].copy_from_slice(&key);
            map[offset + 32..offset + 40].copy_from_slice(&(row as u64).to_le_bytes());
            map[offset + SLOT_STATE_OFFSET] = SLOT_OCCUPIED;
            return Ok(());
        }
        slot = (slot + 1) & (capacity - 1);
    }
    Err(InferenceArtifactError::InvalidArtifact(
        "rehash destination exhausted every slot".into(),
    ))
}

fn cached_row(values: &Mmap, row: usize, columns: usize) -> Result<&[f32]> {
    let start = row
        .checked_mul(columns)
        .and_then(|value| value.checked_mul(std::mem::size_of::<f32>()))
        .and_then(|value| value.checked_add(VALUES_HEADER_BYTES))
        .ok_or_else(|| {
            InferenceArtifactError::InvalidArtifact("embedding cache row offset overflow".into())
        })?;
    let end = start + columns * std::mem::size_of::<f32>();
    let bytes = values.get(start..end).ok_or_else(|| {
        InferenceArtifactError::InvalidArtifact("embedding cache row is truncated".into())
    })?;
    Ok(bytemuck::cast_slice(bytes))
}

fn slot_home(key: &[u8; 32], capacity: usize) -> usize {
    u64::from_le_bytes(key[0..8].try_into().expect("eight digest bytes")) as usize & (capacity - 1)
}

fn write_u64_at(file: &mut File, offset: u64, value: u64, path: &Path) -> Result<()> {
    file.seek(SeekFrom::Start(offset))
        .and_then(|_| file.write_all(&value.to_le_bytes()))
        .and_then(|_| file.flush())
        .map_err(|source| io_error(path, source))
}

fn read_u32(bytes: &[u8]) -> Result<u32> {
    bytes.try_into().map(u32::from_le_bytes).map_err(|_| {
        InferenceArtifactError::InvalidArtifact("truncated embedding cache u32".into())
    })
}

fn read_u64(bytes: &[u8]) -> Result<u64> {
    bytes.try_into().map(u64::from_le_bytes).map_err(|_| {
        InferenceArtifactError::InvalidArtifact("truncated embedding cache u64".into())
    })
}

fn hex_digest(digest: &[u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for &byte in digest {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cache_encodes_unique_misses_once_and_reuses_after_reopen() {
        let directory = tempfile::tempdir().unwrap();
        let namespace = embedding_namespace(&["encoder", "revision", "passage"]);
        let keys = [
            embedding_row_key(&namespace, "relation", "guards"),
            embedding_row_key(&namespace, "node", "Niko"),
            embedding_row_key(&namespace, "node", "Niko"),
        ];
        let mut cache =
            EmbeddingRowCache::open(directory.path(), namespace, 2, keys.len()).unwrap();
        let mut cold = cache.resolve(&keys).unwrap();
        assert_eq!(cold.hit_rows, 0);
        assert_eq!(cold.unique_miss_count(), 2);
        assert_eq!(cold.missing_row_count(), 3);
        let encoded = cold
            .misses
            .iter()
            .flat_map(|miss| match miss.positions[0] {
                0 => [1.0, 2.0],
                _ => [3.0, 4.0],
            })
            .collect::<Vec<_>>();
        cache.install(&mut cold, &encoded).unwrap();
        assert_eq!(cold.values, [1.0, 2.0, 3.0, 4.0, 3.0, 4.0]);
        drop(cache);

        let cache = EmbeddingRowCache::open(directory.path(), namespace, 2, 0).unwrap();
        let warm = cache.resolve(&keys).unwrap();
        assert_eq!(warm.hit_rows, 3);
        assert!(warm.misses.is_empty());
        assert_eq!(warm.values, cold.values);
    }

    #[test]
    fn namespace_and_role_prevent_false_reuse() {
        let a = embedding_namespace(&["encoder-a"]);
        let b = embedding_namespace(&["encoder-b"]);
        assert_ne!(
            embedding_row_key(&a, "node", "same"),
            embedding_row_key(&b, "node", "same")
        );
        assert_ne!(
            embedding_row_key(&a, "node", "same"),
            embedding_row_key(&a, "relation", "same")
        );
    }

    #[test]
    fn cache_grows_without_losing_collision_chain() {
        let directory = tempfile::tempdir().unwrap();
        let namespace = embedding_namespace(&["grow"]);
        let mut cache = EmbeddingRowCache::open(directory.path(), namespace, 1, 1).unwrap();
        let count = MIN_CAPACITY * MAX_LOAD_NUMERATOR / MAX_LOAD_DENOMINATOR + 1;
        let keys = (0..count)
            .map(|index| {
                let mut key = embedding_row_key(&namespace, "node", &index.to_string());
                key[0..8].copy_from_slice(&7_u64.to_le_bytes());
                key
            })
            .collect::<Vec<_>>();
        let mut resolution = cache.resolve(&keys).unwrap();
        let encoded = resolution
            .misses
            .iter()
            .map(|miss| miss.positions[0] as f32)
            .collect::<Vec<_>>();
        cache.install(&mut resolution, &encoded).unwrap();
        drop(cache);
        let cache = EmbeddingRowCache::open(directory.path(), namespace, 1, 0).unwrap();
        let warm = cache.resolve(&keys).unwrap();
        assert_eq!(warm.hit_rows, count);
        assert_eq!(
            warm.values,
            (0..count).map(|value| value as f32).collect::<Vec<_>>()
        );
    }

    #[test]
    fn interrupted_index_replacement_recovers_previous_authority() {
        let directory = tempfile::tempdir().unwrap();
        let namespace = embedding_namespace(&["replacement-recovery"]);
        let key = embedding_row_key(&namespace, "node", "stable");
        let mut cache = EmbeddingRowCache::open(directory.path(), namespace, 1, 1).unwrap();
        let mut cold = cache.resolve(&[key]).unwrap();
        cache.install(&mut cold, &[7.0]).unwrap();
        drop(cache);
        let root = directory.path().join(hex_digest(&namespace));
        std::fs::rename(root.join("rows.index"), root.join("rows.index.previous")).unwrap();

        let cache = EmbeddingRowCache::open(directory.path(), namespace, 1, 0).unwrap();
        let warm = cache.resolve(&[key]).unwrap();
        assert_eq!(warm.values, [7.0]);
        assert_eq!(warm.hit_rows, 1);
    }
}
