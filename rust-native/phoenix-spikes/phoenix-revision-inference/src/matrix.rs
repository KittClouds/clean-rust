use std::fs::{File, OpenOptions};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

use memmap2::{Mmap, MmapOptions};
use serde::{Deserialize, Serialize};

use crate::error::io_error;
use crate::{InferenceArtifactError, Result};

const MAGIC: [u8; 8] = *b"PHXF32M1";
const VERSION: u32 = 1;
const HEADER_BYTES: usize = 64;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MatrixArtifact {
    pub file: String,
    pub rows: u64,
    pub columns: u32,
    pub byte_length: u64,
    pub blake3: String,
}

pub fn write_matrix(
    path: impl AsRef<Path>,
    rows: usize,
    columns: usize,
    values: &[f32],
) -> Result<MatrixArtifact> {
    let path = path.as_ref();
    if rows.checked_mul(columns) != Some(values.len()) || columns > u32::MAX as usize {
        return Err(InferenceArtifactError::InvalidArtifact(
            "matrix shape does not match values".into(),
        ));
    }
    let mut header = [0_u8; HEADER_BYTES];
    header[0..8].copy_from_slice(&MAGIC);
    header[8..12].copy_from_slice(&VERSION.to_le_bytes());
    header[12..16].copy_from_slice(&(HEADER_BYTES as u32).to_le_bytes());
    header[16..24].copy_from_slice(&(rows as u64).to_le_bytes());
    header[24..28].copy_from_slice(&(columns as u32).to_le_bytes());
    header[32..40].copy_from_slice(&(values.len() as u64).to_le_bytes());
    let file = File::create(path).map_err(|source| io_error(path, source))?;
    let mut writer = BufWriter::new(file);
    writer
        .write_all(&header)
        .and_then(|_| writer.write_all(bytemuck::cast_slice(values)))
        .and_then(|_| writer.flush())
        .map_err(|source| io_error(path, source))?;
    drop(writer);
    let (byte_length, blake3) = digest_file(path)?;
    let file = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| InferenceArtifactError::InvalidArtifact("non-UTF8 matrix file".into()))?;
    Ok(MatrixArtifact {
        file: file.into(),
        rows: rows as u64,
        columns: columns as u32,
        byte_length,
        blake3,
    })
}

pub struct MappedF32Matrix {
    mmap: Mmap,
    rows: usize,
    columns: usize,
    path: PathBuf,
}

impl std::fmt::Debug for MappedF32Matrix {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("MappedF32Matrix")
            .field("path", &self.path)
            .field("rows", &self.rows)
            .field("columns", &self.columns)
            .finish()
    }
}

impl MappedF32Matrix {
    pub fn open(path: impl AsRef<Path>, expected: &MatrixArtifact) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        let (byte_length, digest) = digest_file(&path)?;
        if byte_length != expected.byte_length || digest != expected.blake3 {
            return Err(InferenceArtifactError::InvalidArtifact(format!(
                "matrix digest mismatch for {}",
                path.display()
            )));
        }
        let file = OpenOptions::new()
            .read(true)
            .open(&path)
            .map_err(|source| io_error(&path, source))?;
        // SAFETY: the artifact is immutable after atomic bundle publication.
        let mmap =
            unsafe { MmapOptions::new().map(&file) }.map_err(|source| io_error(&path, source))?;
        if mmap.len() < HEADER_BYTES
            || memchr::memmem::find(&mmap[..HEADER_BYTES], &MAGIC) != Some(0)
        {
            return Err(InferenceArtifactError::InvalidArtifact(
                "bad matrix header".into(),
            ));
        }
        let version = read_u32(&mmap, 8)?;
        let header = read_u32(&mmap, 12)? as usize;
        let rows = usize::try_from(read_u64(&mmap, 16)?)
            .map_err(|_| InferenceArtifactError::InvalidArtifact("matrix rows overflow".into()))?;
        let columns = read_u32(&mmap, 24)? as usize;
        let count = usize::try_from(read_u64(&mmap, 32)?)
            .map_err(|_| InferenceArtifactError::InvalidArtifact("matrix size overflow".into()))?;
        let expected_bytes = HEADER_BYTES
            .checked_add(count.checked_mul(4).ok_or_else(|| {
                InferenceArtifactError::InvalidArtifact("matrix byte size overflow".into())
            })?)
            .ok_or_else(|| {
                InferenceArtifactError::InvalidArtifact("matrix length overflow".into())
            })?;
        if version != VERSION
            || header != HEADER_BYTES
            || rows.checked_mul(columns) != Some(count)
            || mmap.len() != expected_bytes
            || rows as u64 != expected.rows
            || columns as u32 != expected.columns
        {
            return Err(InferenceArtifactError::InvalidArtifact(
                "non-canonical matrix layout".into(),
            ));
        }
        Ok(Self {
            mmap,
            rows,
            columns,
            path,
        })
    }

    pub const fn rows(&self) -> usize {
        self.rows
    }

    pub const fn columns(&self) -> usize {
        self.columns
    }

    pub fn values(&self) -> &[f32] {
        bytemuck::cast_slice(&self.mmap[HEADER_BYTES..])
    }

    pub fn row(&self, row: usize) -> Option<&[f32]> {
        let start = row.checked_mul(self.columns)?;
        self.values().get(start..start + self.columns)
    }
}

pub(crate) fn digest_file(path: &Path) -> Result<(u64, String)> {
    let file = File::open(path).map_err(|source| io_error(path, source))?;
    let mut reader = BufReader::new(file);
    let mut hasher = blake3::Hasher::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut bytes = 0_u64;
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|source| io_error(path, source))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
        bytes += read as u64;
    }
    Ok((bytes, hasher.finalize().to_hex().to_string()))
}

fn read_u32(bytes: &[u8], offset: usize) -> Result<u32> {
    let raw = bytes
        .get(offset..offset + 4)
        .ok_or_else(|| InferenceArtifactError::InvalidArtifact("truncated matrix u32".into()))?;
    let value = zerocopy::Ref::<_, zerocopy::little_endian::U32>::new(raw)
        .ok_or_else(|| InferenceArtifactError::InvalidArtifact("unaligned matrix u32".into()))?;
    Ok(value.get())
}

fn read_u64(bytes: &[u8], offset: usize) -> Result<u64> {
    let raw = bytes
        .get(offset..offset + 8)
        .ok_or_else(|| InferenceArtifactError::InvalidArtifact("truncated matrix u64".into()))?;
    let value = zerocopy::Ref::<_, zerocopy::little_endian::U64>::new(raw)
        .ok_or_else(|| InferenceArtifactError::InvalidArtifact("unaligned matrix u64".into()))?;
    Ok(value.get())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matrix_is_borrowed_from_read_only_mmap() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("values.f32m");
        let manifest = write_matrix(&path, 2, 2, &[1.0, 2.0, 3.0, 4.0]).unwrap();
        let mapped = MappedF32Matrix::open(&path, &manifest).unwrap();
        assert_eq!(mapped.row(1), Some(&[3.0, 4.0][..]));
    }
}
