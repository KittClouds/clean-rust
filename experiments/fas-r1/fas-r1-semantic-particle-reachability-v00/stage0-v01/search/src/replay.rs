use crate::scheduler::{run, SearchError};
use crate::types::{OperationLedger, RunTrace, TraceEvent, TraceHeader};
use memchr::memchr_iter;
use memmap2::MmapOptions;
use r1_world::InferenceTask;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::Path;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TraceIoError(pub String);

impl std::fmt::Display for TraceIoError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for TraceIoError {}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "record", content = "payload", rename_all = "snake_case")]
enum TraceRecord {
    Header(TraceHeader),
    Event(Box<TraceEvent>),
    Footer(TraceFooter),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
struct TraceFooter {
    ledger: OperationLedger,
    selected_event: Option<u64>,
    selected_initial_particle: Option<u32>,
    selected_q_terminal: f32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ReplayReport {
    pub passed: bool,
    pub semantic_match: bool,
    pub timestamps_monotone: bool,
    pub event_count: u64,
    pub trace_digest: String,
    pub replay_digest: String,
}

/// Write a lossless JSONL stream: one header, every transition, then a footer.
pub fn write_jsonl(path: impl AsRef<Path>, trace: &RunTrace) -> Result<(), TraceIoError> {
    let file = File::create(path.as_ref()).map_err(io_error)?;
    let mut writer = BufWriter::new(file);
    write_record(&mut writer, &TraceRecord::Header(trace.header.clone()))?;
    for event in &trace.events {
        write_record(&mut writer, &TraceRecord::Event(Box::new(event.clone())))?;
    }
    write_record(
        &mut writer,
        &TraceRecord::Footer(TraceFooter {
            ledger: trace.ledger.clone(),
            selected_event: trace.selected_event,
            selected_initial_particle: trace.selected_initial_particle,
            selected_q_terminal: trace.selected_q_terminal,
        }),
    )?;
    writer.flush().map_err(io_error)
}

/// Read a completed JSONL stream through a read-only memory map and newline
/// scans. Latent states and assignments are stored as full JSON float/integer
/// arrays, so this is a lossless trace rather than a hash-only summary.
pub fn read_jsonl(path: impl AsRef<Path>) -> Result<RunTrace, TraceIoError> {
    let file = File::open(path.as_ref()).map_err(io_error)?;
    let metadata = file.metadata().map_err(io_error)?;
    if metadata.len() == 0 {
        return Err(TraceIoError("trace file is empty".to_owned()));
    }
    // SAFETY: the mapping is read-only, the file handle remains alive until
    // parsing finishes, and no writes are made through the mapped bytes.
    let mapping = unsafe { MmapOptions::new().map(&file) }.map_err(io_error)?;
    if mapping.last() != Some(&b'\n') {
        return Err(TraceIoError(
            "trace is incomplete: final JSONL record lacks newline".to_owned(),
        ));
    }

    let mut header: Option<TraceHeader> = None;
    let mut events = Vec::new();
    let mut footer: Option<TraceFooter> = None;
    let mut start = 0usize;
    for end in memchr_iter(b'\n', &mapping) {
        let line = &mapping[start..end];
        start = end + 1;
        if line.is_empty() {
            return Err(TraceIoError(
                "trace contains an empty JSONL record".to_owned(),
            ));
        }
        let record: TraceRecord = serde_json::from_slice(line).map_err(json_error)?;
        match record {
            TraceRecord::Header(value) if header.is_none() && events.is_empty() => {
                header = Some(value);
            }
            TraceRecord::Event(value) if header.is_some() && footer.is_none() => {
                if value.event_index != events.len() as u64
                    || value.global_expansion_index != events.len() as u64 + 1
                {
                    return Err(TraceIoError(
                        "trace event indices are not contiguous".to_owned(),
                    ));
                }
                events.push(*value);
            }
            TraceRecord::Footer(value) if header.is_some() && footer.is_none() => {
                footer = Some(value);
            }
            _ => return Err(TraceIoError("trace record order is invalid".to_owned())),
        }
    }
    let header = header.ok_or_else(|| TraceIoError("trace header is missing".to_owned()))?;
    let footer = footer.ok_or_else(|| TraceIoError("trace footer is missing".to_owned()))?;
    if header.config.budget != events.len() as u64
        || footer.ledger.expansions != events.len() as u64
    {
        return Err(TraceIoError(
            "trace expansion count does not match its header/footer".to_owned(),
        ));
    }
    Ok(RunTrace {
        header,
        events,
        ledger: footer.ledger,
        selected_event: footer.selected_event,
        selected_initial_particle: footer.selected_initial_particle,
        selected_q_terminal: footer.selected_q_terminal,
    })
}

/// Rerun fixed inference inputs and compare semantic dynamics, RNG, charges,
/// merges, resampling, and selections. Real measured timings are excluded from
/// equality, but each recorded trace must have monotone completion times.
pub fn verify_replay(task: &InferenceTask, trace: &RunTrace) -> Result<ReplayReport, SearchError> {
    let replay = run(task, trace.header.config.clone())?;
    let timestamps_monotone = timestamps_monotone(trace) && timestamps_monotone(&replay);
    let original_normalized = normalize_timing(trace);
    let replay_normalized = normalize_timing(&replay);
    let trace_digest = semantic_digest(&original_normalized);
    let replay_digest = semantic_digest(&replay_normalized);
    let semantic_match = original_normalized == replay_normalized;
    Ok(ReplayReport {
        passed: semantic_match && timestamps_monotone,
        semantic_match,
        timestamps_monotone,
        event_count: trace.events.len() as u64,
        trace_digest,
        replay_digest,
    })
}

fn write_record(writer: &mut impl Write, record: &TraceRecord) -> Result<(), TraceIoError> {
    serde_json::to_writer(&mut *writer, record).map_err(json_error)?;
    writer.write_all(b"\n").map_err(io_error)
}

fn timestamps_monotone(trace: &RunTrace) -> bool {
    let mut active = trace.header.initial_completion_active_ns;
    let mut wall = trace.header.initial_completion_wall_ns;
    for event in &trace.events {
        if event.cumulative_active_ns < active || event.cumulative_wall_ns < wall {
            return false;
        }
        active = event.cumulative_active_ns;
        wall = event.cumulative_wall_ns;
    }
    trace.ledger.end_to_end_wall_ns >= wall
}

fn normalize_timing(trace: &RunTrace) -> RunTrace {
    let mut normalized = trace.clone();
    normalized.header.timing_kind = "timing_excluded_for_replay".to_owned();
    normalized.header.initial_completion_active_ns = 0;
    normalized.header.initial_completion_wall_ns = 0;
    normalized.header.initial_costs.cpu_active_ns = 0;
    normalized.header.initial_costs.gpu_active_ns = 0;
    normalized.ledger.cpu_active_ns = 0;
    normalized.ledger.gpu_active_ns = 0;
    normalized.ledger.end_to_end_wall_ns = 0;
    normalized.ledger.trace_bytes_estimate = 0;
    for event in &mut normalized.events {
        event.cumulative_active_ns = 0;
        event.cumulative_wall_ns = 0;
        event.costs.cpu_active_ns = 0;
        event.costs.gpu_active_ns = 0;
    }
    normalized
}

fn semantic_digest(trace: &RunTrace) -> String {
    let bytes = serde_json::to_vec(trace).unwrap_or_default();
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn io_error(error: std::io::Error) -> TraceIoError {
    TraceIoError(error.to_string())
}

fn json_error(error: serde_json::Error) -> TraceIoError {
    TraceIoError(error.to_string())
}
