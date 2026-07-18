//! Content-addressed hot-tier materialization for immutable model artifacts.

use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{Receiver, SyncSender, sync_channel};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const SCHEMA: &str = "phoenix.model-hot-cache/v1";
const BUNDLE_SCHEMA: &str = "phoenix.model-hot-bundle/v1";
const PROBE_BYTES: usize = 64 * 1024;
const BUFFER_COUNT: usize = 3;
static STAGE_SEQUENCE: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, thiserror::Error)]
pub enum HotCacheError {
    #[error("I/O failed for {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("invalid hot-cache artifact: {0}")]
    Invalid(String),
    #[error("JSON failed: {0}")]
    Json(#[from] serde_json::Error),
    #[error("chunk reader terminated unexpectedly")]
    ReaderTerminated,
}

pub type Result<T> = std::result::Result<T, HotCacheError>;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CacheOutcome {
    Materialized,
    Reused,
    Rebuilt,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MaterializationReceipt {
    pub outcome: CacheOutcome,
    pub source_bytes: u64,
    pub bytes_copied: u64,
    pub chunks_copied: u64,
    pub chunk_bytes: usize,
    pub probe_bytes_read: u64,
    pub elapsed_micros: u64,
}

#[derive(Clone, Debug)]
pub struct MaterializedArtifact {
    source_path: PathBuf,
    hot_path: PathBuf,
    sha256: String,
    receipt_path: PathBuf,
    receipt: MaterializationReceipt,
}

#[derive(Clone, Debug)]
pub struct MaterializedBundle {
    root: PathBuf,
    digest: String,
    reused: bool,
}

impl MaterializedBundle {
    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn digest(&self) -> &str {
        &self.digest
    }

    pub fn reused(&self) -> bool {
        self.reused
    }
}

impl MaterializedArtifact {
    pub fn source_path(&self) -> &Path {
        &self.source_path
    }

    pub fn hot_path(&self) -> &Path {
        &self.hot_path
    }

    pub fn sha256(&self) -> &str {
        &self.sha256
    }

    pub fn receipt_path(&self) -> &Path {
        &self.receipt_path
    }

    pub fn receipt(&self) -> &MaterializationReceipt {
        &self.receipt
    }
}

#[derive(Clone, Debug)]
pub struct ModelHotCache {
    root: PathBuf,
    chunk_bytes: usize,
}

impl ModelHotCache {
    pub fn new(root: impl Into<PathBuf>, chunk_bytes: usize) -> Result<Self> {
        if chunk_bytes < 64 * 1024 {
            return Err(HotCacheError::Invalid(
                "chunk size must be at least 64 KiB".into(),
            ));
        }
        Ok(Self {
            root: root.into(),
            chunk_bytes,
        })
    }

    pub fn materialize(
        &self,
        source: impl AsRef<Path>,
        expected_sha256: &str,
    ) -> Result<MaterializedArtifact> {
        validate_sha256(expected_sha256)?;
        let started = Instant::now();
        let requested_source = source.as_ref().to_path_buf();
        std::fs::create_dir_all(&self.root).map_err(|error| io_error(&self.root, error))?;
        let final_dir = self.root.join(expected_sha256);
        if let Some(artifact) =
            self.try_reuse(&requested_source, expected_sha256, &final_dir, started)?
        {
            return Ok(artifact);
        }
        let source = std::fs::canonicalize(&requested_source)
            .map_err(|source_error| io_error(&requested_source, source_error))?;
        let rebuilt = final_dir.exists();
        if rebuilt {
            quarantine(&final_dir)?;
        }
        self.build(&source, expected_sha256, &final_dir, rebuilt, started)
    }

    /// Atomically assembles already-verified hot artifacts under exact names.
    /// NTFS hard links keep external-data model bundles zero-copy.
    pub fn assemble_bundle(
        &self,
        files: &[(&MaterializedArtifact, &str)],
    ) -> Result<MaterializedBundle> {
        if files.is_empty() {
            return Err(HotCacheError::Invalid("hot bundle cannot be empty".into()));
        }
        let mut ordered = files.to_vec();
        ordered.sort_unstable_by(|left, right| left.1.cmp(right.1));
        for (_, name) in &ordered {
            if Path::new(name).file_name().and_then(|value| value.to_str()) != Some(name) {
                return Err(HotCacheError::Invalid(format!(
                    "hot bundle name must be one safe path component: {name}"
                )));
            }
        }
        let mut digest = blake3::Hasher::new();
        for (artifact, name) in &ordered {
            digest.update(name.as_bytes());
            digest.update(&[0]);
            digest.update(artifact.sha256.as_bytes());
            digest.update(&[0]);
        }
        let digest = digest.finalize().to_hex().to_string();
        let bundles = self.root.join("bundles");
        std::fs::create_dir_all(&bundles).map_err(|error| io_error(&bundles, error))?;
        let final_dir = bundles.join(&digest);
        if bundle_matches(&final_dir, &digest, &ordered)? {
            return Ok(MaterializedBundle {
                root: final_dir,
                digest,
                reused: true,
            });
        }
        if final_dir.exists() {
            quarantine(&final_dir)?;
        }
        let stage = bundles.join(format!(".bundle-{}", unique_suffix()));
        std::fs::create_dir(&stage).map_err(|error| io_error(&stage, error))?;
        let mut records = Vec::with_capacity(ordered.len());
        for (artifact, name) in &ordered {
            let target = stage.join(name);
            std::fs::hard_link(&artifact.hot_path, &target)
                .map_err(|error| io_error(&target, error))?;
            records.push(BundleFile {
                name: (*name).into(),
                sha256: artifact.sha256.clone(),
            });
        }
        write_read_only_json(
            &stage.join("manifest.json"),
            &BundleManifest {
                schema: BUNDLE_SCHEMA.into(),
                digest: digest.clone(),
                files: records,
            },
        )?;
        std::fs::rename(&stage, &final_dir).map_err(|error| io_error(&final_dir, error))?;
        Ok(MaterializedBundle {
            root: final_dir,
            digest,
            reused: false,
        })
    }

    fn try_reuse(
        &self,
        source: &Path,
        expected_sha256: &str,
        final_dir: &Path,
        started: Instant,
    ) -> Result<Option<MaterializedArtifact>> {
        let receipt_path = final_dir.join("manifest.json");
        let Ok(encoded) = std::fs::read(&receipt_path) else {
            return Ok(None);
        };
        let Ok(manifest) = serde_json::from_slice::<CacheManifest>(&encoded) else {
            return Ok(None);
        };
        let hot_path = final_dir.join(&manifest.file);
        if manifest.schema != SCHEMA
            || manifest.sha256 != expected_sha256
            || manifest.chunk_bytes != self.chunk_bytes
            || !hot_path.is_file()
        {
            return Ok(None);
        }
        let Ok(identity) = file_identity(&hot_path) else {
            return Ok(None);
        };
        if !same_content_identity(&identity, &manifest.identity) || !identity.read_only {
            return Ok(None);
        }
        let (probe, probe_bytes_read) = probe_digest(&hot_path, manifest.bytes)?;
        if probe != manifest.probe_blake3 {
            return Ok(None);
        }
        Ok(Some(MaterializedArtifact {
            source_path: source.to_path_buf(),
            hot_path,
            sha256: expected_sha256.into(),
            receipt_path,
            receipt: MaterializationReceipt {
                outcome: CacheOutcome::Reused,
                source_bytes: manifest.bytes,
                bytes_copied: 0,
                chunks_copied: 0,
                chunk_bytes: self.chunk_bytes,
                probe_bytes_read,
                elapsed_micros: micros(started.elapsed()),
            },
        }))
    }

    fn build(
        &self,
        source: &Path,
        expected_sha256: &str,
        final_dir: &Path,
        rebuilt: bool,
        started: Instant,
    ) -> Result<MaterializedArtifact> {
        let source_bytes = std::fs::metadata(source)
            .map_err(|error| io_error(source, error))?
            .len();
        let stage = self.root.join(stage_name(expected_sha256));
        std::fs::create_dir(&stage).map_err(|error| io_error(&stage, error))?;
        let extension = source
            .extension()
            .and_then(|value| value.to_str())
            .filter(|value| value.bytes().all(|byte| byte.is_ascii_alphanumeric()))
            .unwrap_or("bin");
        let file_name = format!("artifact.{extension}");
        let stage_artifact = stage.join(&file_name);
        let copy = copy_chunked(source, &stage_artifact, self.chunk_bytes)?;
        if copy.sha256 != expected_sha256 {
            return Err(HotCacheError::Invalid(format!(
                "SHA-256 mismatch for {}: expected {expected_sha256}, got {}",
                source.display(),
                copy.sha256
            )));
        }
        let mut permissions = std::fs::metadata(&stage_artifact)
            .map_err(|error| io_error(&stage_artifact, error))?
            .permissions();
        permissions.set_readonly(true);
        std::fs::set_permissions(&stage_artifact, permissions)
            .map_err(|error| io_error(&stage_artifact, error))?;
        let identity = file_identity(&stage_artifact)?;
        let (probe_blake3, probe_bytes_read) = probe_digest(&stage_artifact, source_bytes)?;
        let manifest = CacheManifest {
            schema: SCHEMA.into(),
            source: source.to_string_lossy().into_owned(),
            file: file_name,
            sha256: expected_sha256.into(),
            bytes: source_bytes,
            chunk_bytes: self.chunk_bytes,
            chunk_blake3: copy.chunk_blake3,
            probe_blake3,
            identity,
        };
        let stage_receipt = stage.join("manifest.json");
        write_read_only_json(&stage_receipt, &manifest)?;
        std::fs::rename(&stage, final_dir).map_err(|error| io_error(final_dir, error))?;
        let hot_path = final_dir.join(&manifest.file);
        let receipt_path = final_dir.join("manifest.json");
        Ok(MaterializedArtifact {
            source_path: source.to_path_buf(),
            hot_path,
            sha256: expected_sha256.into(),
            receipt_path,
            receipt: MaterializationReceipt {
                outcome: if rebuilt {
                    CacheOutcome::Rebuilt
                } else {
                    CacheOutcome::Materialized
                },
                source_bytes,
                bytes_copied: copy.bytes,
                chunks_copied: copy.chunks,
                chunk_bytes: self.chunk_bytes,
                probe_bytes_read,
                elapsed_micros: micros(started.elapsed()),
            },
        })
    }
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BundleManifest {
    schema: String,
    digest: String,
    files: Vec<BundleFile>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BundleFile {
    name: String,
    sha256: String,
}

fn bundle_matches(
    root: &Path,
    digest: &str,
    expected: &[(&MaterializedArtifact, &str)],
) -> Result<bool> {
    let Ok(encoded) = std::fs::read(root.join("manifest.json")) else {
        return Ok(false);
    };
    let Ok(manifest) = serde_json::from_slice::<BundleManifest>(&encoded) else {
        return Ok(false);
    };
    if manifest.schema != BUNDLE_SCHEMA
        || manifest.digest != digest
        || manifest.files.len() != expected.len()
    {
        return Ok(false);
    }
    for ((artifact, name), record) in expected.iter().zip(&manifest.files) {
        if record.name != *name || record.sha256 != artifact.sha256 {
            return Ok(false);
        }
        let target = root.join(name);
        let Ok(target_identity) = file_identity(&target) else {
            return Ok(false);
        };
        if !same_content_identity(&target_identity, &file_identity(&artifact.hot_path)?) {
            return Ok(false);
        }
    }
    Ok(true)
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CacheManifest {
    schema: String,
    source: String,
    file: String,
    sha256: String,
    bytes: u64,
    chunk_bytes: usize,
    chunk_blake3: Vec<String>,
    probe_blake3: String,
    identity: FileIdentity,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct FileIdentity {
    bytes: u64,
    read_only: bool,
    modified_nanos: u64,
    volume_serial: Option<u64>,
    file_id: Option<String>,
    change_time: Option<i64>,
}

fn same_content_identity(left: &FileIdentity, right: &FileIdentity) -> bool {
    left.bytes == right.bytes
        && left.read_only == right.read_only
        && left.modified_nanos == right.modified_nanos
        && left.volume_serial == right.volume_serial
        && left.file_id == right.file_id
}

struct CopyReceipt {
    sha256: String,
    bytes: u64,
    chunks: u64,
    chunk_blake3: Vec<String>,
}

fn copy_chunked(source: &Path, target: &Path, chunk_bytes: usize) -> Result<CopyReceipt> {
    let mut target_file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(target)
        .map_err(|error| io_error(target, error))?;
    let (empty_tx, empty_rx) = sync_channel::<Vec<u8>>(BUFFER_COUNT);
    let (filled_tx, filled_rx) = sync_channel::<std::io::Result<Option<Vec<u8>>>>(BUFFER_COUNT);
    for _ in 0..BUFFER_COUNT {
        empty_tx
            .send(Vec::with_capacity(chunk_bytes))
            .map_err(|_| HotCacheError::ReaderTerminated)?;
    }
    let source_owned = source.to_path_buf();
    let reader =
        std::thread::spawn(move || read_chunks(source_owned, chunk_bytes, empty_rx, filled_tx));
    let mut sha256 = Sha256::new();
    let mut chunk_blake3 = Vec::new();
    let mut bytes = 0_u64;
    let mut chunks = 0_u64;
    loop {
        let message = filled_rx
            .recv()
            .map_err(|_| HotCacheError::ReaderTerminated)?;
        let Some(mut buffer) = message.map_err(|error| io_error(source, error))? else {
            break;
        };
        target_file
            .write_all(&buffer)
            .map_err(|error| io_error(target, error))?;
        sha256.update(&buffer);
        chunk_blake3.push(blake3::hash(&buffer).to_hex().to_string());
        bytes += buffer.len() as u64;
        chunks += 1;
        buffer.clear();
        let _ = empty_tx.send(buffer);
    }
    reader
        .join()
        .map_err(|_| HotCacheError::ReaderTerminated)??;
    target_file
        .sync_all()
        .map_err(|error| io_error(target, error))?;
    Ok(CopyReceipt {
        sha256: format!("{:x}", sha256.finalize()),
        bytes,
        chunks,
        chunk_blake3,
    })
}

fn read_chunks(
    source: PathBuf,
    chunk_bytes: usize,
    empty_rx: Receiver<Vec<u8>>,
    filled_tx: SyncSender<std::io::Result<Option<Vec<u8>>>>,
) -> Result<()> {
    let mut file = open_sequential(&source)?;
    while let Ok(mut buffer) = empty_rx.recv() {
        buffer.resize(chunk_bytes, 0);
        let mut filled = 0;
        while filled < chunk_bytes {
            match file.read(&mut buffer[filled..]) {
                Ok(0) => break,
                Ok(read) => filled += read,
                Err(error) => {
                    let _ = filled_tx.send(Err(error));
                    return Ok(());
                }
            }
        }
        if filled == 0 {
            let _ = filled_tx.send(Ok(None));
            return Ok(());
        }
        buffer.truncate(filled);
        if filled_tx.send(Ok(Some(buffer))).is_err() {
            return Ok(());
        }
    }
    Ok(())
}

fn open_sequential(path: &Path) -> Result<File> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_SEQUENTIAL_SCAN;
        options.custom_flags(FILE_FLAG_SEQUENTIAL_SCAN);
    }
    options.open(path).map_err(|error| io_error(path, error))
}

fn probe_digest(path: &Path, bytes: u64) -> Result<(String, u64)> {
    let mut file = File::open(path).map_err(|error| io_error(path, error))?;
    let width = (PROBE_BYTES as u64).min(bytes);
    let mut positions = vec![
        0,
        bytes.saturating_sub(width) / 2,
        bytes.saturating_sub(width),
    ];
    positions.sort_unstable();
    positions.dedup();
    let mut digest = blake3::Hasher::new();
    let mut total = 0_u64;
    let mut buffer = vec![0_u8; width as usize];
    for position in positions {
        file.seek(SeekFrom::Start(position))
            .map_err(|error| io_error(path, error))?;
        file.read_exact(&mut buffer)
            .map_err(|error| io_error(path, error))?;
        digest.update(&position.to_le_bytes());
        digest.update(&buffer);
        total += width;
    }
    Ok((digest.finalize().to_hex().to_string(), total))
}

fn file_identity(path: &Path) -> Result<FileIdentity> {
    let metadata = std::fs::metadata(path).map_err(|error| io_error(path, error))?;
    let modified_nanos = metadata
        .modified()
        .ok()
        .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
        .map(|duration| duration.as_nanos().min(u64::MAX as u128) as u64)
        .unwrap_or(0);
    let (volume_serial, file_id, change_time) = native_file_identity(path)?;
    Ok(FileIdentity {
        bytes: metadata.len(),
        read_only: metadata.permissions().readonly(),
        modified_nanos,
        volume_serial,
        file_id,
        change_time,
    })
}

#[cfg(windows)]
fn native_file_identity(path: &Path) -> Result<(Option<u64>, Option<String>, Option<i64>)> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::{
        FILE_BASIC_INFO, FILE_ID_INFO, FileBasicInfo, FileIdInfo, GetFileInformationByHandleEx,
    };

    let file = File::open(path).map_err(|error| io_error(path, error))?;
    let handle = file.as_raw_handle();
    let mut id = FILE_ID_INFO::default();
    let mut basic = FILE_BASIC_INFO::default();
    // SAFETY: both output buffers are valid for their exact Windows structure sizes.
    let id_ok = unsafe {
        GetFileInformationByHandleEx(
            handle,
            FileIdInfo,
            (&raw mut id).cast(),
            std::mem::size_of::<FILE_ID_INFO>() as u32,
        )
    };
    // SAFETY: both output buffers are valid for their exact Windows structure sizes.
    let basic_ok = unsafe {
        GetFileInformationByHandleEx(
            handle,
            FileBasicInfo,
            (&raw mut basic).cast(),
            std::mem::size_of::<FILE_BASIC_INFO>() as u32,
        )
    };
    if id_ok == 0 || basic_ok == 0 {
        return Err(io_error(path, std::io::Error::last_os_error()));
    }
    let file_id = id
        .FileId
        .Identifier
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    Ok((
        Some(id.VolumeSerialNumber),
        Some(file_id),
        Some(basic.ChangeTime),
    ))
}

#[cfg(not(windows))]
fn native_file_identity(_path: &Path) -> Result<(Option<u64>, Option<String>, Option<i64>)> {
    Ok((None, None, None))
}

fn write_read_only_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let encoded = serde_json::to_vec_pretty(value)?;
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| io_error(path, error))?;
    file.write_all(&encoded)
        .map_err(|error| io_error(path, error))?;
    file.sync_all().map_err(|error| io_error(path, error))?;
    let mut permissions = file
        .metadata()
        .map_err(|error| io_error(path, error))?
        .permissions();
    permissions.set_readonly(true);
    std::fs::set_permissions(path, permissions).map_err(|error| io_error(path, error))
}

fn quarantine(path: &Path) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| HotCacheError::Invalid("cache entry has no parent".into()))?;
    let file = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("entry");
    let destination = parent.join(format!("{file}.invalid-{}", unique_suffix()));
    std::fs::rename(path, &destination).map_err(|error| io_error(path, error))
}

fn stage_name(digest: &str) -> String {
    format!(".stage-{}-{}", &digest[..16], unique_suffix())
}

fn unique_suffix() -> String {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let sequence = STAGE_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!("{}-{timestamp}-{sequence}", std::process::id())
}

fn validate_sha256(value: &str) -> Result<()> {
    if value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        Ok(())
    } else {
        Err(HotCacheError::Invalid(
            "expected SHA-256 must contain 64 hexadecimal characters".into(),
        ))
    }
}

fn micros(duration: std::time::Duration) -> u64 {
    duration.as_micros().min(u64::MAX as u128) as u64
}

fn io_error(path: impl Into<PathBuf>, source: std::io::Error) -> HotCacheError {
    HotCacheError::Io {
        path: path.into(),
        source,
    }
}

#[cfg(test)]
mod tests {
    use std::io::{Seek, SeekFrom, Write};

    use sha2::{Digest, Sha256};
    use tempfile::tempdir;

    use super::{CacheOutcome, ModelHotCache};

    #[test]
    fn materializes_reuses_and_rebuilds_corrupt_hot_artifact() {
        let source_dir = tempdir().unwrap();
        let cache_dir = tempdir().unwrap();
        let source = source_dir.path().join("model.bin");
        let bytes = (0..(3 * 1024 * 1024 + 17))
            .map(|index| (index % 251) as u8)
            .collect::<Vec<_>>();
        std::fs::write(&source, &bytes).unwrap();
        let expected = format!("{:x}", Sha256::digest(&bytes));
        let cache = ModelHotCache::new(cache_dir.path(), 256 * 1024).unwrap();

        let first = cache.materialize(&source, &expected).unwrap();
        assert_eq!(first.receipt().outcome, CacheOutcome::Materialized);
        assert_eq!(first.receipt().bytes_copied, bytes.len() as u64);
        assert!(
            std::fs::metadata(first.hot_path())
                .unwrap()
                .permissions()
                .readonly()
        );

        let second = cache.materialize(&source, &expected).unwrap();
        assert_eq!(second.receipt().outcome, CacheOutcome::Reused);
        assert_eq!(second.receipt().bytes_copied, 0);

        make_writable(second.hot_path());
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .open(second.hot_path())
            .unwrap();
        file.seek(SeekFrom::Start((bytes.len() / 2) as u64))
            .unwrap();
        file.write_all(&[0xFF; 32]).unwrap();
        file.sync_all().unwrap();
        drop(file);

        let rebuilt = cache.materialize(&source, &expected).unwrap();
        assert_eq!(rebuilt.receipt().outcome, CacheOutcome::Rebuilt);
        assert_eq!(std::fs::read(rebuilt.hot_path()).unwrap(), bytes);
    }

    #[test]
    fn rejects_source_with_wrong_digest() {
        let source_dir = tempdir().unwrap();
        let cache_dir = tempdir().unwrap();
        let source = source_dir.path().join("model.bin");
        std::fs::write(&source, b"not the expected model").unwrap();
        let cache = ModelHotCache::new(cache_dir.path(), 64 * 1024).unwrap();
        let error = cache.materialize(&source, &"0".repeat(64)).unwrap_err();
        assert!(error.to_string().contains("SHA-256 mismatch"));
    }

    #[test]
    fn valid_hot_artifact_does_not_require_source_volume() {
        let source_dir = tempdir().unwrap();
        let cache_dir = tempdir().unwrap();
        let source = source_dir.path().join("model.bin");
        let bytes = vec![0x5A; 512 * 1024];
        std::fs::write(&source, &bytes).unwrap();
        let expected = format!("{:x}", Sha256::digest(&bytes));
        let cache = ModelHotCache::new(cache_dir.path(), 128 * 1024).unwrap();
        cache.materialize(&source, &expected).unwrap();
        std::fs::remove_file(&source).unwrap();

        let reused = cache.materialize(&source, &expected).unwrap();
        assert_eq!(reused.receipt().outcome, CacheOutcome::Reused);
        assert_eq!(reused.receipt().bytes_copied, 0);
    }

    #[test]
    fn assembles_and_reuses_zero_copy_external_data_bundle() {
        let source_dir = tempdir().unwrap();
        let cache_dir = tempdir().unwrap();
        let model = source_dir.path().join("model.onnx");
        let data = source_dir.path().join("model.onnx.data");
        std::fs::write(&model, b"graph").unwrap();
        std::fs::write(&data, b"weights").unwrap();
        let model_sha = format!("{:x}", Sha256::digest(b"graph"));
        let data_sha = format!("{:x}", Sha256::digest(b"weights"));
        let cache = ModelHotCache::new(cache_dir.path(), 64 * 1024).unwrap();
        let model = cache.materialize(model, &model_sha).unwrap();
        let data = cache.materialize(data, &data_sha).unwrap();

        let first = cache
            .assemble_bundle(&[(&model, "model.onnx"), (&data, "model.onnx.data")])
            .unwrap();
        assert!(!first.reused());
        assert_eq!(
            std::fs::read(first.root().join("model.onnx")).unwrap(),
            b"graph"
        );
        let second = cache
            .assemble_bundle(&[(&data, "model.onnx.data"), (&model, "model.onnx")])
            .unwrap();
        assert!(second.reused());
        assert_eq!(first.digest(), second.digest());
    }

    #[allow(clippy::permissions_set_readonly_false)]
    fn make_writable(path: &std::path::Path) {
        let mut permissions = std::fs::metadata(path).unwrap().permissions();
        permissions.set_readonly(false);
        std::fs::set_permissions(path, permissions).unwrap();
    }
}
