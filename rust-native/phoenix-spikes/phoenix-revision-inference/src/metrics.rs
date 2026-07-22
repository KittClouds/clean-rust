use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::thread::JoinHandle;
use std::time::Duration;

#[cfg(feature = "encoders")]
use phoenix_model_hot_cache::{CacheOutcome, MaterializationReceipt};
use serde::{Deserialize, Serialize};
use sysinfo::{Pid, ProcessRefreshKind, ProcessesToUpdate, System};

use crate::ModelKind;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EncoderExecutionBackend {
    MpnetOnnxFp32,
    QwenCandleFp32,
    QwenOnnxFp32,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CacheReuseReceipt {
    pub relation_rows_reused: u64,
    pub node_rows_reused: u64,
    pub encoder_cache_hits: u64,
    pub encoder_cache_misses: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactHotCacheReceipt {
    pub hits: u64,
    pub materializations: u64,
    pub rebuilds: u64,
    pub bytes_copied: u64,
    pub chunks_copied: u64,
    pub probe_bytes_read: u64,
    pub elapsed_micros: u64,
}

#[cfg(feature = "encoders")]
impl ArtifactHotCacheReceipt {
    pub(crate) fn from_materializations<'a>(
        receipts: impl IntoIterator<Item = &'a MaterializationReceipt>,
    ) -> Self {
        let mut aggregate = Self::default();
        for receipt in receipts {
            match receipt.outcome {
                CacheOutcome::Reused => aggregate.hits += 1,
                CacheOutcome::Materialized => aggregate.materializations += 1,
                CacheOutcome::Rebuilt => aggregate.rebuilds += 1,
            }
            aggregate.bytes_copied += receipt.bytes_copied;
            aggregate.chunks_copied += receipt.chunks_copied;
            aggregate.probe_bytes_read += receipt.probe_bytes_read;
            aggregate.elapsed_micros += receipt.elapsed_micros;
        }
        aggregate
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct InferencePerformanceReceipt {
    pub schema: String,
    pub model: ModelKind,
    pub snapshot_digest: String,
    pub encoder_backend: EncoderExecutionBackend,
    pub encoder_resident_reused: bool,
    pub encoder_artifact_bundle_reused: bool,
    pub bundle_open_micros: u64,
    pub encoder_cold_micros: u64,
    pub encoder_warm_micros: u64,
    pub model_load_micros: u64,
    pub input_prepare_micros: u64,
    pub graph_inference_micros: u64,
    pub ranking_micros: u64,
    pub complete_inference_micros: u64,
    pub peak_resident_bytes: u64,
    pub artifact_hot_cache: ArtifactHotCacheReceipt,
    pub cache: CacheReuseReceipt,
}

pub struct PeakMemorySampler {
    stop: Arc<AtomicBool>,
    peak: Arc<AtomicU64>,
    worker: Option<JoinHandle<()>>,
}

impl PeakMemorySampler {
    pub fn start(sample_every: Duration) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let peak = Arc::new(AtomicU64::new(current_resident_bytes()));
        let worker_stop = Arc::clone(&stop);
        let worker_peak = Arc::clone(&peak);
        let worker = std::thread::spawn(move || {
            let pid = Pid::from_u32(std::process::id());
            let mut system = System::new();
            while !worker_stop.load(Ordering::Relaxed) {
                system.refresh_processes_specifics(
                    ProcessesToUpdate::Some(&[pid]),
                    true,
                    ProcessRefreshKind::nothing().with_memory(),
                );
                if let Some(process) = system.process(pid) {
                    worker_peak.fetch_max(process.memory(), Ordering::Relaxed);
                }
                std::thread::sleep(sample_every);
            }
        });
        Self {
            stop,
            peak,
            worker: Some(worker),
        }
    }

    pub fn finish(mut self) -> u64 {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
        self.peak
            .load(Ordering::Relaxed)
            .max(current_resident_bytes())
    }
}

impl Drop for PeakMemorySampler {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

fn current_resident_bytes() -> u64 {
    let pid = Pid::from_u32(std::process::id());
    let mut system = System::new();
    system.refresh_processes_specifics(
        ProcessesToUpdate::Some(&[pid]),
        true,
        ProcessRefreshKind::nothing().with_memory(),
    );
    system.process(pid).map_or(0, |process| process.memory())
}
