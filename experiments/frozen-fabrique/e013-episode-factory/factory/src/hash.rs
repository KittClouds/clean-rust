use std::{fs::File, io::Read, path::Path};

use memmap2::MmapOptions;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{error::io_error, FactoryError, SealEntry};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct FileDigest {
    pub byte_len: u64,
    pub sha256: String,
}

pub fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

/// Hashes a frozen local artifact through a read-only mapping to avoid a second full-file copy.
pub fn hash_file(path: &Path) -> Result<FileDigest, FactoryError> {
    let file = File::open(path).map_err(|error| io_error(path, error))?;
    let byte_len = file
        .metadata()
        .map_err(|error| io_error(path, error))?
        .len();
    if byte_len == 0 {
        return Ok(FileDigest {
            byte_len,
            sha256: hash_bytes(&[]),
        });
    }
    // The factory owns package writes and maps only after all files are closed.
    // Callers must not mutate a file concurrently with this hash operation.
    let mapping =
        unsafe { MmapOptions::new().map(&file) }.map_err(|error| io_error(path, error))?;
    Ok(FileDigest {
        byte_len,
        sha256: hash_bytes(&mapping),
    })
}

pub fn root_hash(entries: &[SealEntry]) -> String {
    let mut ordered: Vec<&SealEntry> = entries.iter().collect();
    ordered.sort_unstable_by(|left, right| left.path.cmp(&right.path));
    let mut digest = Sha256::new();
    for entry in ordered {
        digest.update(entry.path.as_bytes());
        digest.update([0]);
        digest.update(entry.byte_len.to_be_bytes());
        digest.update([0]);
        digest.update(entry.sha256.as_bytes());
        digest.update(b"\n");
    }
    format!("{:x}", digest.finalize())
}

pub(crate) fn hash_reader(mut reader: impl Read) -> Result<FileDigest, FactoryError> {
    let mut digest = Sha256::new();
    let mut byte_len = 0u64;
    let mut chunk = [0u8; 64 * 1024];
    loop {
        let count = reader
            .read(&mut chunk)
            .map_err(|error| io_error("<reader>", error))?;
        if count == 0 {
            break;
        }
        byte_len += count as u64;
        digest.update(&chunk[..count]);
    }
    Ok(FileDigest {
        byte_len,
        sha256: format!("{:x}", digest.finalize()),
    })
}
