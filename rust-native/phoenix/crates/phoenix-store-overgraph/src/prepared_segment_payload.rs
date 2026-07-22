use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use memmap2::Mmap;
use phoenix_store_native_core::StoreError;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SegmentPayloadWrite {
    pub relative_path: String,
    pub bytes: usize,
    pub wrote: bool,
}

pub fn write_segment_payload(
    store_path: &Path,
    scope_ord: u64,
    document_ord: u64,
    revision: u64,
    kind: u8,
    ordinal: u32,
    payload: &[u8],
) -> Result<SegmentPayloadWrite, StoreError> {
    let relative_path =
        segment_payload_relative_path(scope_ord, document_ord, revision, kind, ordinal);
    let path = resolve_relative(store_path, &relative_path)?;
    if let Ok(metadata) = fs::metadata(&path) {
        if metadata.len() == payload.len() as u64 {
            return Ok(SegmentPayloadWrite {
                relative_path,
                bytes: payload.len(),
                wrote: false,
            });
        }
    }

    let parent = path.parent().ok_or_else(|| {
        StoreError::Query(format!("invalid segment payload path {}", path.display()))
    })?;
    fs::create_dir_all(parent).map_err(|error| io_error("create segment payload dir", error))?;
    let tmp = temp_path(&path);
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&tmp)
        .map_err(|error| io_error("create segment payload temp", error))?;
    file.write_all(payload)
        .map_err(|error| io_error("write segment payload", error))?;
    file.sync_data()
        .map_err(|error| io_error("sync segment payload", error))?;
    drop(file);
    if path.exists() {
        fs::remove_file(&path).map_err(|error| io_error("replace segment payload", error))?;
    }
    fs::rename(&tmp, &path).map_err(|error| {
        let _ = fs::remove_file(&tmp);
        io_error("publish segment payload", error)
    })?;
    Ok(SegmentPayloadWrite {
        relative_path,
        bytes: payload.len(),
        wrote: true,
    })
}

pub fn with_segment_payload<T>(
    store_path: &Path,
    relative_path: &str,
    f: impl FnOnce(&[u8]) -> Result<T, StoreError>,
) -> Result<T, StoreError> {
    let path = resolve_relative(store_path, relative_path)?;
    let file = File::open(&path).map_err(|error| io_error("open segment payload", error))?;
    let mmap =
        unsafe { Mmap::map(&file) }.map_err(|error| io_error("mmap segment payload", error))?;
    f(&mmap)
}

fn segment_payload_relative_path(
    scope_ord: u64,
    document_ord: u64,
    revision: u64,
    kind: u8,
    ordinal: u32,
) -> String {
    format!(
        "prepared-segments/s{scope_ord:016x}/d{document_ord:016x}/r{revision:016x}/k{kind:02x}-o{ordinal:08x}.pseg"
    )
}

fn resolve_relative(store_path: &Path, relative_path: &str) -> Result<PathBuf, StoreError> {
    let relative = Path::new(relative_path);
    if relative.is_absolute() {
        return Err(StoreError::Query(format!(
            "absolute segment payload path rejected: {relative_path}"
        )));
    }
    let mut path = store_path.to_path_buf();
    for component in relative.components() {
        match component {
            Component::Normal(part) => path.push(part),
            _ => {
                return Err(StoreError::Query(format!(
                    "invalid segment payload path: {relative_path}"
                )))
            }
        }
    }
    Ok(path)
}

fn temp_path(path: &Path) -> PathBuf {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    path.with_extension(format!("tmp-{stamp}"))
}

fn io_error(context: &str, error: std::io::Error) -> StoreError {
    StoreError::Query(format!("{context}: {error}"))
}
