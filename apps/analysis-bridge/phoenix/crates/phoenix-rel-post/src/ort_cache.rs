use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::UNIX_EPOCH;

const CACHE_VERSION: &[u8] = b"phoenix-ort-optimized-cache/v2-onnx\0";
const CACHE_DIR_ENV: &str = "PHOENIX_ORT_OPTIMIZED_CACHE_DIR";
const CACHE_ENABLE_ENV: &str = "PHOENIX_ORT_OPTIMIZED_CACHE";
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum OrtCacheStatus {
    #[default]
    Disabled,
    Hit,
    Miss,
    Built,
    WriteFailed,
}

impl OrtCacheStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Disabled => "disabled",
            Self::Hit => "hit",
            Self::Miss => "miss",
            Self::Built => "built",
            Self::WriteFailed => "write-failed",
        }
    }

    pub fn is_hit(self) -> bool {
        matches!(self, Self::Hit)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrtSessionLoadInfo {
    pub cache_status: OrtCacheStatus,
    pub cache_key: [u8; 32],
    pub load_micros: u64,
    pub optimized_model_path: Option<PathBuf>,
}

pub(crate) struct CachePlan {
    source_path: PathBuf,
    optimized_path: PathBuf,
    manifest_path: PathBuf,
    temp_optimized_path: Option<PathBuf>,
    temp_manifest_path: Option<PathBuf>,
    lock_path: Option<PathBuf>,
    lock: Option<File>,
    key: [u8; 32],
    status: OrtCacheStatus,
}

impl CachePlan {
    pub(crate) fn input_path(&self) -> &Path {
        if self.status.is_hit() {
            &self.optimized_path
        } else {
            &self.source_path
        }
    }

    pub(crate) fn optimized_output_path(&self) -> Option<&Path> {
        self.temp_optimized_path.as_deref()
    }

    pub(crate) fn status(&self) -> OrtCacheStatus {
        self.status
    }

    /// Drop a cache hit after ORT rejects the optimized artifact. Cache
    /// entries are an acceleration layer, never an authority: callers can
    /// retry from the original model without inheriting a poisoned hit.
    pub(crate) fn invalidate_hit(&mut self) {
        if !self.status.is_hit() {
            return;
        }
        quarantine_stale(&self.optimized_path);
        quarantine_stale(&self.manifest_path);

        let Some(root) = self.optimized_path.parent() else {
            self.status = OrtCacheStatus::Disabled;
            return;
        };
        let stem = self
            .optimized_path
            .file_stem()
            .and_then(|value| value.to_str())
            .unwrap_or("ort-cache");
        let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let prefix = format!("{stem}.{}.{}", std::process::id(), sequence);
        let lock_path = root.join(format!("{stem}.lock"));
        let lock = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
            .ok();
        let can_write = lock.is_some();
        self.temp_optimized_path = can_write.then(|| temp_optimized_model_path(root, &prefix));
        self.temp_manifest_path = can_write.then(|| root.join(format!("{prefix}.manifest.tmp")));
        self.lock_path = can_write.then_some(lock_path);
        self.lock = lock;
        self.status = OrtCacheStatus::Miss;
        eprintln!(
            "PHOENIX_ORT_OPTIMIZED_CACHE_INVALIDATED key={} source={}",
            hex(&self.key),
            self.source_path.display()
        );
    }

    pub(crate) fn finish(&mut self) {
        if self.temp_optimized_path.is_none() || self.lock.is_none() {
            return;
        }
        let Some(temp_model) = self.temp_optimized_path.as_ref() else {
            return;
        };
        let model_ready = fs::metadata(temp_model)
            .map(|metadata| metadata.is_file() && metadata.len() > 0)
            .unwrap_or(false);
        if !model_ready {
            self.status = OrtCacheStatus::WriteFailed;
            return;
        }
        let Some(temp_manifest) = self.temp_manifest_path.as_ref() else {
            self.status = OrtCacheStatus::WriteFailed;
            return;
        };
        let manifest = match File::create(temp_manifest).and_then(|mut file| {
            file.write_all(&self.manifest_bytes())?;
            file.sync_all()
        }) {
            Ok(()) => true,
            Err(_) => false,
        };
        if !manifest
            || fs::rename(temp_model, &self.optimized_path).is_err()
            || fs::rename(temp_manifest, &self.manifest_path).is_err()
        {
            self.status = OrtCacheStatus::WriteFailed;
            return;
        }
        self.temp_optimized_path = None;
        self.temp_manifest_path = None;
        self.status = OrtCacheStatus::Built;
    }

    pub(crate) fn info(&self, load_micros: u64) -> OrtSessionLoadInfo {
        OrtSessionLoadInfo {
            cache_status: self.status,
            cache_key: self.key,
            load_micros,
            optimized_model_path: if self.status.is_hit()
                || matches!(self.status, OrtCacheStatus::Built)
            {
                Some(self.optimized_path.clone())
            } else {
                None
            },
        }
    }

    fn manifest_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(256);
        bytes.extend_from_slice(b"version=2-onnx\n");
        bytes.extend_from_slice(b"key=");
        bytes.extend_from_slice(hex(&self.key).as_bytes());
        bytes.extend_from_slice(b"\nsource=");
        bytes.extend_from_slice(self.source_path.to_string_lossy().as_bytes());
        bytes.extend_from_slice(b"\n");
        bytes
    }
}

impl Drop for CachePlan {
    fn drop(&mut self) {
        let _ = self.lock.take();
        if let Some(path) = self.lock_path.as_ref() {
            let _ = fs::remove_file(path);
        }
        if let Some(path) = self.temp_optimized_path.as_ref() {
            let _ = fs::remove_file(path);
        }
        if let Some(path) = self.temp_manifest_path.as_ref() {
            let _ = fs::remove_file(path);
        }
    }
}

pub(crate) fn prepare(
    source_path: &Path,
    provider: &str,
    intra_threads: usize,
    memory_pattern: bool,
) -> CachePlan {
    let key = cache_key(source_path, provider, intra_threads, memory_pattern);
    let Some(root) = cache_root() else {
        return disabled_plan(source_path, key);
    };
    if fs::create_dir_all(&root).is_err() {
        return disabled_plan(source_path, key);
    }
    let stem = hex(&key);
    // Offline graph optimization emits a regular ONNX model. Keep the format
    // explicit in both the temporary and final names so ORT never has to infer
    // a different serialization format before an atomic rename.
    let optimized_path = optimized_model_path(&root, &stem);
    let manifest_path = root.join(format!("{stem}.manifest"));
    if valid_entry(source_path, &optimized_path, &manifest_path, &key) {
        return CachePlan {
            source_path: source_path.to_path_buf(),
            optimized_path,
            manifest_path,
            temp_optimized_path: None,
            temp_manifest_path: None,
            lock_path: None,
            lock: None,
            key,
            status: OrtCacheStatus::Hit,
        };
    }

    quarantine_stale(&optimized_path);
    quarantine_stale(&manifest_path);
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let prefix = format!("{stem}.{}.{}", std::process::id(), sequence);
    // The lock is deliberately stable per cache key. A process-unique lock
    // would let concurrent warmups all optimize the same final path.
    let lock_path = root.join(format!("{stem}.lock"));
    let lock = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&lock_path)
        .ok();
    let can_write = lock.is_some();
    CachePlan {
        source_path: source_path.to_path_buf(),
        optimized_path: optimized_path.clone(),
        manifest_path: manifest_path.clone(),
        temp_optimized_path: can_write.then(|| temp_optimized_model_path(&root, &prefix)),
        temp_manifest_path: can_write.then(|| root.join(format!("{prefix}.manifest.tmp"))),
        lock_path: can_write.then_some(lock_path),
        lock,
        key,
        status: OrtCacheStatus::Miss,
    }
}

fn disabled_plan(source_path: &Path, key: [u8; 32]) -> CachePlan {
    CachePlan {
        source_path: source_path.to_path_buf(),
        optimized_path: PathBuf::new(),
        manifest_path: PathBuf::new(),
        temp_optimized_path: None,
        temp_manifest_path: None,
        lock_path: None,
        lock: None,
        key,
        status: OrtCacheStatus::Disabled,
    }
}

fn optimized_model_path(root: &Path, stem: &str) -> PathBuf {
    root.join(format!("{stem}.onnx"))
}

fn temp_optimized_model_path(root: &Path, prefix: &str) -> PathBuf {
    root.join(format!("{prefix}.tmp.onnx"))
}

fn cache_root() -> Option<PathBuf> {
    if env::var(CACHE_ENABLE_ENV).ok().is_some_and(|value| {
        matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "0" | "off" | "false"
        )
    }) {
        return None;
    }
    if let Some(path) = env::var_os(CACHE_DIR_ENV).map(PathBuf::from) {
        return (!path.as_os_str().is_empty()).then_some(path);
    }
    env::var_os("LOCALAPPDATA").map(|root| {
        PathBuf::from(root)
            .join("Phoenix")
            .join("NativeShell")
            .join("ort-optimized-v1")
    })
}

fn valid_entry(
    source_path: &Path,
    optimized_path: &Path,
    manifest_path: &Path,
    key: &[u8; 32],
) -> bool {
    if !fs::metadata(optimized_path)
        .map(|metadata| metadata.is_file() && metadata.len() > 0)
        .unwrap_or(false)
    {
        return false;
    }
    let Ok(manifest) = fs::read_to_string(manifest_path) else {
        return false;
    };
    let expected = format!(
        "version=2-onnx\nkey={}\nsource={}\n",
        hex(key),
        source_path.to_string_lossy()
    );
    manifest == expected
}

fn quarantine_stale(path: &Path) {
    if !path.exists() {
        return;
    }
    let suffix = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let stale = path.with_extension(format!("stale-{}-{}", std::process::id(), suffix));
    let _ = fs::rename(path, stale);
}

fn cache_key(
    source_path: &Path,
    provider: &str,
    intra_threads: usize,
    memory_pattern: bool,
) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(CACHE_VERSION);
    hasher.update(provider.as_bytes());
    hasher.update(&intra_threads.max(1).to_le_bytes());
    hasher.update(&[u8::from(memory_pattern)]);
    hash_path_identity(&mut hasher, source_path);
    if let Some(path) = env::var_os("ORT_DYLIB_PATH") {
        hash_path_identity(&mut hasher, Path::new(&path));
    }
    for name in [
        "PHOENIX_ORT_CUDA_DEVICE_ID",
        "PHOENIX_ORT_DIRECTML_DEVICE_ID",
    ] {
        hasher.update(name.as_bytes());
        hasher.update(env::var(name).unwrap_or_default().as_bytes());
    }
    *hasher.finalize().as_bytes()
}

fn hash_path_identity(hasher: &mut blake3::Hasher, path: &Path) {
    hasher.update(path.to_string_lossy().as_bytes());
    if let Ok(metadata) = fs::metadata(path) {
        hasher.update(&metadata.len().to_le_bytes());
        if let Ok(modified) = metadata.modified() {
            if let Ok(duration) = modified.duration_since(UNIX_EPOCH) {
                hasher.update(&duration.as_nanos().to_le_bytes());
            }
        }
    }
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        output.push(DIGITS[usize::from(byte >> 4)] as char);
        output.push(DIGITS[usize::from(byte & 0x0f)] as char);
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn key_changes_with_source_metadata() {
        let root =
            std::env::temp_dir().join(format!("phoenix-ort-cache-test-{}", std::process::id()));
        let _ = fs::create_dir_all(&root);
        let path = root.join("model.onnx");
        fs::write(&path, b"one").expect("write source");
        let first = cache_key(&path, "cpu", 4, false);
        std::thread::sleep(Duration::from_millis(2));
        fs::write(&path, b"two").expect("rewrite source");
        let second = cache_key(&path, "cpu", 4, false);
        assert_ne!(first, second);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn status_names_are_stable() {
        assert_eq!(OrtCacheStatus::Hit.as_str(), "hit");
        assert!(OrtCacheStatus::Hit.is_hit());
        assert!(!OrtCacheStatus::Built.is_hit());
    }

    #[test]
    fn optimized_artifacts_keep_onnx_format_across_atomic_publish() {
        let root = Path::new("cache");
        let final_path = optimized_model_path(root, "key");
        let temp_path = temp_optimized_model_path(root, "key.pid.sequence");
        assert_eq!(
            final_path.extension().and_then(|value| value.to_str()),
            Some("onnx")
        );
        assert_eq!(
            temp_path.extension().and_then(|value| value.to_str()),
            Some("onnx")
        );
    }
}
