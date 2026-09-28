use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use crate::format::content_hash_hex;
use crate::{
    io_error, DocumentIndexError, DocumentIndexShardRef, MmapDocumentIndex,
    PreparedDocumentIndexShard, DOCUMENT_INDEX_SCHEMA_VERSION,
};

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DocumentIndexShardWrite {
    pub path: PathBuf,
    pub bytes: usize,
    pub wrote: bool,
}

pub fn document_index_shard_path(
    store_root: impl AsRef<Path>,
    reference: &DocumentIndexShardRef,
) -> Result<PathBuf, DocumentIndexError> {
    validate_hash(&reference.content_hash)?;
    if reference.schema_version != DOCUMENT_INDEX_SCHEMA_VERSION {
        return Err(DocumentIndexError::Invalid(format!(
            "unsupported shard schema {}",
            reference.schema_version
        )));
    }
    Ok(store_root
        .as_ref()
        .join("document-index")
        .join(format!("v{}", reference.schema_version))
        .join("shards")
        .join(&reference.content_hash[..2])
        .join(format!("{}.pdx", reference.content_hash)))
}

pub fn persist_document_index_shard(
    store_root: impl AsRef<Path>,
    shard: &PreparedDocumentIndexShard,
) -> Result<DocumentIndexShardWrite, DocumentIndexError> {
    validate_prepared_shard(shard)?;
    let path = document_index_shard_path(store_root, &shard.reference)?;
    if path.exists() {
        MmapDocumentIndex::open_verified(&path, &shard.reference)?;
        return Ok(DocumentIndexShardWrite {
            path,
            bytes: shard.bytes.len(),
            wrote: false,
        });
    }
    let parent = path
        .parent()
        .ok_or_else(|| DocumentIndexError::Invalid("shard path has no parent".to_owned()))?;
    fs::create_dir_all(parent).map_err(|error| io_error(parent, error))?;
    let temp_path = temp_path(&path);
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temp_path)
        .map_err(|error| io_error(&temp_path, error))?;
    file.write_all(&shard.bytes)
        .map_err(|error| io_error(&temp_path, error))?;
    file.sync_data()
        .map_err(|error| io_error(&temp_path, error))?;
    drop(file);
    match fs::rename(&temp_path, &path) {
        Ok(()) => {}
        Err(_) if path.exists() => {
            let _ = fs::remove_file(&temp_path);
            MmapDocumentIndex::open_verified(&path, &shard.reference)?;
            return Ok(DocumentIndexShardWrite {
                path,
                bytes: shard.bytes.len(),
                wrote: false,
            });
        }
        Err(error) => {
            let _ = fs::remove_file(&temp_path);
            return Err(io_error(&path, error));
        }
    }
    MmapDocumentIndex::open_verified(&path, &shard.reference)?;
    Ok(DocumentIndexShardWrite {
        path,
        bytes: shard.bytes.len(),
        wrote: true,
    })
}

fn validate_prepared_shard(shard: &PreparedDocumentIndexShard) -> Result<(), DocumentIndexError> {
    if shard.reference.byte_len != shard.bytes.len() as u64
        || shard.reference.content_hash != content_hash_hex(&shard.bytes)
    {
        return Err(DocumentIndexError::Invalid(
            "prepared shard reference does not match bytes".to_owned(),
        ));
    }
    Ok(())
}

fn validate_hash(hash: &str) -> Result<(), DocumentIndexError> {
    if hash.len() != 32 || !hash.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(DocumentIndexError::Invalid(
            "content hash must be 32 hexadecimal characters".to_owned(),
        ));
    }
    Ok(())
}

fn temp_path(path: &Path) -> PathBuf {
    let sequence = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
    path.with_extension(format!("tmp-{}-{sequence}", std::process::id()))
}
