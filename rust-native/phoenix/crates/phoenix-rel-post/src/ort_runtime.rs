use std::env;
use std::path::{Path, PathBuf};
use std::sync::Once;
use std::thread;
use std::time::Instant;

use ort::execution_providers::{
    CUDAExecutionProvider, DirectMLExecutionProvider, ExecutionProviderDispatch,
};
use ort::session::builder::GraphOptimizationLevel;
use ort::session::Session;

use crate::ort_cache::{self, OrtCacheStatus, OrtSessionLoadInfo};

static ORT_DYLIB_INIT: Once = Once::new();
const ORT_EP_ENV: &str = "PHOENIX_ORT_EP";
const NLI_ORT_EP_ENV: &str = "PHOENIX_NLI_ORT_EP";
const CUDA_DEVICE_ENV: &str = "PHOENIX_ORT_CUDA_DEVICE_ID";
const DIRECTML_DEVICE_ENV: &str = "PHOENIX_ORT_DIRECTML_DEVICE_ID";

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum OrtExecutionProviderPreference {
    Cpu,
    #[default]
    AutoGpu,
    Cuda,
    DirectMl,
}

impl OrtExecutionProviderPreference {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Cpu => "cpu",
            Self::AutoGpu => "auto-gpu",
            Self::Cuda => "cuda",
            Self::DirectMl => "directml",
        }
    }

    fn prefers_gpu(self) -> bool {
        !matches!(self, Self::Cpu)
    }
}

pub fn configure_preferred_ort_dylib_path() {
    configure_preferred_ort_dylib_path_for(OrtExecutionProviderPreference::AutoGpu);
}

pub fn configure_preferred_ort_dylib_path_for(preference: OrtExecutionProviderPreference) {
    ORT_DYLIB_INIT.call_once(|| {
        if env::var_os("ORT_DYLIB_PATH").is_some() {
            return;
        }
        let root = project_root();
        let path = if preference.prefers_gpu() {
            default_gpu_ort_dylib_path(&root).or_else(|| default_ort_dylib_path(&root))
        } else {
            default_ort_dylib_path(&root)
        };
        if let Some(path) = path {
            env::set_var("ORT_DYLIB_PATH", path);
        }
    });
}

pub fn load_session(path: &Path) -> Result<Session, ort::Error> {
    load_session_with_intra_threads(path, recommended_thread_count())
}

pub fn load_session_with_intra_threads(
    path: &Path,
    intra_threads: usize,
) -> Result<Session, ort::Error> {
    load_session_with_intra_threads_and_memory_pattern(path, intra_threads, true)
}

pub fn load_session_with_intra_threads_and_memory_pattern(
    path: &Path,
    intra_threads: usize,
    enable_memory_pattern: bool,
) -> Result<Session, ort::Error> {
    configure_preferred_ort_dylib_path();
    build_session(
        path,
        intra_threads,
        OrtExecutionProviderPreference::Cpu,
        enable_memory_pattern,
    )
}

pub fn load_session_with_intra_threads_and_memory_pattern_with_info(
    path: &Path,
    intra_threads: usize,
    enable_memory_pattern: bool,
) -> Result<(Session, OrtSessionLoadInfo), ort::Error> {
    configure_preferred_ort_dylib_path();
    build_session_with_info(
        path,
        intra_threads,
        OrtExecutionProviderPreference::Cpu,
        enable_memory_pattern,
    )
}

pub fn load_nli_session_with_info(
    path: &Path,
) -> Result<(Session, OrtSessionLoadInfo), ort::Error> {
    let preference = nli_ort_preference();
    configure_preferred_ort_dylib_path_for(preference);
    // NLI pairs have document-dependent token lengths. A retained CPU memory
    // pattern keeps the largest ModernBERT activation arena alive for the whole
    // bridge process, which is hostile to bounded one-shot publication.
    build_session_with_info(path, recommended_thread_count(), preference, false)
}

fn build_session(
    path: &Path,
    intra_threads: usize,
    preference: OrtExecutionProviderPreference,
    enable_memory_pattern: bool,
) -> Result<Session, ort::Error> {
    build_session_with_info(path, intra_threads, preference, enable_memory_pattern)
        .map(|(session, _)| session)
}

fn build_session_with_info(
    path: &Path,
    intra_threads: usize,
    preference: OrtExecutionProviderPreference,
    enable_memory_pattern: bool,
) -> Result<(Session, OrtSessionLoadInfo), ort::Error> {
    let intra_threads = intra_threads.max(1);
    let mut cache = ort_cache::prepare(
        path,
        preference.as_str(),
        intra_threads,
        enable_memory_pattern,
    );
    let started = Instant::now();
    let session = match commit_session(&cache, intra_threads, preference, enable_memory_pattern) {
        Ok(session) => session,
        Err(error) if cache.status().is_hit() => {
            // An optimized artifact can be structurally present but rejected
            // by a newer ORT/provider build. Retry from source exactly once.
            eprintln!(
                "PHOENIX_ORT_OPTIMIZED_CACHE_REJECTED input={} error={error}",
                cache.input_path().display()
            );
            cache.invalidate_hit();
            commit_session(&cache, intra_threads, preference, enable_memory_pattern).map_err(
                |retry_error| {
                    eprintln!(
                    "PHOENIX_ORT_OPTIMIZED_CACHE_RETRY_FAILED first={error} retry={retry_error}"
                );
                    retry_error
                },
            )?
        }
        Err(error) => return Err(error),
    };
    cache.finish();
    let info = cache.info(started.elapsed().as_micros().try_into().unwrap_or(u64::MAX));
    if matches!(info.cache_status, OrtCacheStatus::WriteFailed) {
        eprintln!(
            "PHOENIX_ORT_OPTIMIZED_CACHE_WRITE_FAILED source={} key={}",
            path.display(),
            hex(&info.cache_key)
        );
    }
    Ok((session, info))
}

fn commit_session(
    cache: &ort_cache::CachePlan,
    intra_threads: usize,
    preference: OrtExecutionProviderPreference,
    enable_memory_pattern: bool,
) -> Result<Session, ort::Error> {
    let optimization_level = if cache.status().is_hit() {
        GraphOptimizationLevel::Disable
    } else {
        GraphOptimizationLevel::Level3
    };
    let builder = Session::builder()?
        .with_optimization_level(optimization_level)?
        .with_memory_pattern(enable_memory_pattern)?
        .with_parallel_execution(false)?
        .with_inter_threads(1)?
        .with_intra_threads(intra_threads)?;
    let builder = if let Some(output_path) = cache.optimized_output_path() {
        builder.with_optimized_model_path(output_path)?
    } else {
        builder
    };
    let providers = execution_providers_for(preference);
    let builder = if providers.is_empty() {
        builder
    } else {
        builder.with_execution_providers(providers)?
    };
    builder.commit_from_file(cache.input_path())
}

pub fn recommended_thread_count() -> usize {
    thread::available_parallelism()
        .map(|count| count.get().min(8))
        .unwrap_or(1)
}

pub fn nli_ort_preference() -> OrtExecutionProviderPreference {
    env::var(NLI_ORT_EP_ENV)
        .ok()
        .and_then(|value| parse_ort_preference(&value))
        .or_else(|| {
            env::var(ORT_EP_ENV)
                .ok()
                .and_then(|value| parse_ort_preference(&value))
        })
        .unwrap_or_default()
}

pub fn resolved_ort_dylib_path() -> Option<PathBuf> {
    env::var_os("ORT_DYLIB_PATH").map(PathBuf::from)
}

pub fn default_ort_dylib_path(project_root: &Path) -> Option<PathBuf> {
    [
        PathBuf::from(
            r"D:\phoenix-models\onnxruntime-1.20.1\pkg\runtimes\win-x64\native\onnxruntime.dll",
        ),
        PathBuf::from(
            r"G:\phoenix-models\onnxruntime-1.20.1\pkg\runtimes\win-x64\native\onnxruntime.dll",
        ),
        project_root
            .join("node_modules")
            .join("@huggingface")
            .join("transformers")
            .join("node_modules")
            .join("onnxruntime-node")
            .join("bin")
            .join("napi-v6")
            .join("win32")
            .join("x64")
            .join("onnxruntime.dll"),
        project_root
            .join("node_modules")
            .join("onnxruntime-node")
            .join("bin")
            .join("napi-v3")
            .join("win32")
            .join("x64")
            .join("onnxruntime.dll"),
    ]
    .into_iter()
    .find(|path| path.exists())
}

pub fn default_gpu_ort_dylib_path(project_root: &Path) -> Option<PathBuf> {
    [
        PathBuf::from(
            r"D:\phoenix-models\onnxruntime-gpu-1.20.1\pkg\runtimes\win-x64\native\onnxruntime.dll",
        ),
        PathBuf::from(
            r"D:\phoenix-models\onnxruntime-directml-1.20.1\pkg\runtimes\win-x64\native\onnxruntime.dll",
        ),
        project_root
            .join("node_modules")
            .join("@huggingface")
            .join("transformers")
            .join("node_modules")
            .join("onnxruntime-node")
            .join("bin")
            .join("napi-v6")
            .join("win32")
            .join("x64")
            .join("onnxruntime.dll"),
    ]
    .into_iter()
    .find(|path| path.exists())
}

pub fn project_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(4)
        .expect("project root")
        .to_path_buf()
}

fn execution_providers_for(
    preference: OrtExecutionProviderPreference,
) -> Vec<ExecutionProviderDispatch> {
    match preference {
        OrtExecutionProviderPreference::Cpu => Vec::new(),
        OrtExecutionProviderPreference::Cuda => vec![cuda_provider()],
        OrtExecutionProviderPreference::DirectMl => vec![directml_provider()],
        OrtExecutionProviderPreference::AutoGpu => {
            let mut providers = Vec::with_capacity(2);
            providers.push(cuda_provider());
            if cfg!(target_os = "windows") {
                providers.push(directml_provider());
            }
            providers
        }
    }
}

fn cuda_provider() -> ExecutionProviderDispatch {
    CUDAExecutionProvider::default()
        .with_device_id(env_i32(CUDA_DEVICE_ENV).unwrap_or(0))
        .with_tf32(true)
        .build()
        .fail_silently()
}

fn directml_provider() -> ExecutionProviderDispatch {
    DirectMLExecutionProvider::default()
        .with_device_id(env_i32(DIRECTML_DEVICE_ENV).unwrap_or(0))
        .build()
        .fail_silently()
}

fn parse_ort_preference(value: &str) -> Option<OrtExecutionProviderPreference> {
    match normalize_env_value(value).as_str() {
        "cpu" | "none" | "off" => Some(OrtExecutionProviderPreference::Cpu),
        "auto" | "gpu" | "auto_gpu" | "autogpu" => Some(OrtExecutionProviderPreference::AutoGpu),
        "cuda" | "nvidia" => Some(OrtExecutionProviderPreference::Cuda),
        "directml" | "dml" => Some(OrtExecutionProviderPreference::DirectMl),
        _ => None,
    }
}

fn env_i32(name: &str) -> Option<i32> {
    env::var(name)
        .ok()
        .and_then(|value| value.trim().parse::<i32>().ok())
}

fn normalize_env_value(value: &str) -> String {
    value.trim().to_ascii_lowercase().replace(['-', ' '], "_")
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

    #[test]
    fn parses_execution_provider_preferences() {
        assert_eq!(
            parse_ort_preference("CPU"),
            Some(OrtExecutionProviderPreference::Cpu)
        );
        assert_eq!(
            parse_ort_preference("auto-gpu"),
            Some(OrtExecutionProviderPreference::AutoGpu)
        );
        assert_eq!(
            parse_ort_preference("nvidia"),
            Some(OrtExecutionProviderPreference::Cuda)
        );
        assert_eq!(
            parse_ort_preference("dml"),
            Some(OrtExecutionProviderPreference::DirectMl)
        );
        assert_eq!(parse_ort_preference("mystery"), None);
    }
}
