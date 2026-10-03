//! Receipt-checked, memory-mapped reader for the frozen Stage 1 sensor arrays.
//!
//! The NPY payloads remain mapped for the lifetime of this store. Task-local
//! callback features are copied once into compact owned slices because the
//! scheduler's public callback contract takes an owned `SemanticFeatures`.

use crate::{FeatureError, SemanticFeatures};
use bytemuck::try_cast_slice;
use hashbrown::HashMap;
use memchr::memchr_iter;
use memmap2::{Mmap, MmapOptions};
use r1_world::InferenceTask;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

const EXTRACTION_SCHEMA: &str = "R1_STAGE1_SENSOR_EXTRACTION_V01";
const EXTRACTION_STATUS: &str = "R1_SENSOR_EXTRACTION_COMPLETE";
const HIDDEN_DIM: usize = 2048;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeatureLoadError(pub String);

impl std::fmt::Display for FeatureLoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for FeatureLoadError {}

impl From<std::io::Error> for FeatureLoadError {
    fn from(value: std::io::Error) -> Self {
        Self(value.to_string())
    }
}

impl From<serde_json::Error> for FeatureLoadError {
    fn from(value: serde_json::Error) -> Self {
        Self(value.to_string())
    }
}

impl From<FeatureError> for FeatureLoadError {
    fn from(value: FeatureError) -> Self {
        Self(value.0)
    }
}

#[derive(Deserialize)]
struct Receipt {
    schema: String,
    status: String,
    input: InputRecord,
    output_files: Vec<OutputRecord>,
}

#[derive(Deserialize)]
struct InputRecord {
    sha256: String,
    support_manifest: SupportRecord,
}

#[derive(Deserialize)]
struct SupportRecord {
    sha256: String,
}

#[derive(Deserialize)]
struct OutputRecord {
    path: String,
    sha256: String,
    bytes: u64,
}

#[derive(Deserialize)]
struct RowRecord {
    task_id: String,
    family_id: String,
    task_index: usize,
    kind: String,
    row: usize,
    clause_index: Option<usize>,
}

#[derive(Default)]
struct TaskRows {
    task_index: usize,
    family_id: String,
    global: Option<usize>,
    clauses: Vec<Option<usize>>,
}

struct MappedNpyF32 {
    map: Mmap,
    payload_offset: usize,
    rows: usize,
    columns: usize,
}

impl MappedNpyF32 {
    fn open(path: &Path) -> Result<Self, FeatureLoadError> {
        let file = File::open(path)?;
        // The mapping is read-only and owned by this value. The file is a
        // receipt-verified local artifact, never user-provided mutable input.
        let map = unsafe { MmapOptions::new().map(&file)? };
        if map.len() < 10 || &map[..6] != b"\x93NUMPY" {
            return Err(FeatureLoadError(format!(
                "{} is not an NPY file",
                path.display()
            )));
        }
        let major = map[6];
        let (prefix, header_len) = match major {
            1 => (10usize, usize::from(u16::from_le_bytes([map[8], map[9]]))),
            2 | 3 => {
                if map.len() < 12 {
                    return Err(FeatureLoadError("truncated NPY v2/v3 prefix".to_owned()));
                }
                (
                    12usize,
                    u32::from_le_bytes([map[8], map[9], map[10], map[11]]) as usize,
                )
            }
            _ => {
                return Err(FeatureLoadError(format!(
                    "unsupported NPY major version {major}"
                )))
            }
        };
        let header_end = prefix
            .checked_add(header_len)
            .filter(|end| *end <= map.len())
            .ok_or_else(|| FeatureLoadError("truncated NPY header".to_owned()))?;
        let header = std::str::from_utf8(&map[prefix..header_end])
            .map_err(|error| FeatureLoadError(format!("NPY header is not UTF-8: {error}")))?;
        if !(header.contains("'<f4'") || header.contains("\"<f4\"")) {
            return Err(FeatureLoadError(
                "NPY dtype must be little-endian float32".to_owned(),
            ));
        }
        if !(header.contains("False") || header.contains("false")) {
            return Err(FeatureLoadError(
                "Fortran-ordered NPY arrays are unsupported".to_owned(),
            ));
        }
        let shape = parse_shape(header)?;
        if shape.len() != 2 {
            return Err(FeatureLoadError(format!(
                "expected rank-2 NPY array, got shape {shape:?}"
            )));
        }
        let count = shape[0]
            .checked_mul(shape[1])
            .ok_or_else(|| FeatureLoadError("NPY shape product overflow".to_owned()))?;
        let payload = &map[header_end..];
        if payload.len() != count * std::mem::size_of::<f32>() {
            return Err(FeatureLoadError(
                "NPY payload length does not match shape".to_owned(),
            ));
        }
        try_cast_slice::<u8, f32>(payload)
            .map_err(|error| FeatureLoadError(format!("unaligned NPY float payload: {error}")))?;
        Ok(Self {
            map,
            payload_offset: header_end,
            rows: shape[0],
            columns: shape[1],
        })
    }

    fn row(&self, row: usize) -> Result<&[f32], FeatureLoadError> {
        if row >= self.rows {
            return Err(FeatureLoadError(format!(
                "NPY row {row} outside {} rows",
                self.rows
            )));
        }
        let start = row * self.columns;
        let byte_start = self.payload_offset + start * std::mem::size_of::<f32>();
        let byte_end = byte_start + self.columns * std::mem::size_of::<f32>();
        try_cast_slice::<u8, f32>(&self.map[byte_start..byte_end])
            .map_err(|error| FeatureLoadError(format!("unaligned NPY row {row}: {error}")))
    }
}

/// Mapped extraction with every payload checked against its extraction receipt.
pub struct MappedSensorExtraction {
    _root: PathBuf,
    constraint_h: MappedNpyF32,
    global_h: MappedNpyF32,
    task_rows: HashMap<String, TaskRows>,
}

impl MappedSensorExtraction {
    /// Open an extraction only when its input hashes match the supplied public
    /// tasks and support manifest. All receipt output files are rehashed.
    pub fn open(
        extraction_dir: impl AsRef<Path>,
        public_tasks_path: impl AsRef<Path>,
        support_manifest_path: impl AsRef<Path>,
    ) -> Result<Self, FeatureLoadError> {
        let root = extraction_dir.as_ref().canonicalize()?;
        let receipt_path = root.join("receipt.json");
        let receipt: Receipt = serde_json::from_slice(&std::fs::read(&receipt_path)?)?;
        if receipt.schema != EXTRACTION_SCHEMA || receipt.status != EXTRACTION_STATUS {
            return Err(FeatureLoadError(
                "unexpected sensor extraction receipt identity".to_owned(),
            ));
        }
        if sha256_file(public_tasks_path.as_ref())? != receipt.input.sha256 {
            return Err(FeatureLoadError(
                "public task hash differs from extraction receipt".to_owned(),
            ));
        }
        if sha256_file(support_manifest_path.as_ref())? != receipt.input.support_manifest.sha256 {
            return Err(FeatureLoadError(
                "support manifest hash differs from extraction receipt".to_owned(),
            ));
        }
        let outputs: HashMap<&str, &OutputRecord> = receipt
            .output_files
            .iter()
            .map(|record| (record.path.as_str(), record))
            .collect();
        for name in [
            "constraint_H.float32.npy",
            "global_h.float32.npy",
            "rows.jsonl",
        ] {
            let record = outputs
                .get(name)
                .ok_or_else(|| FeatureLoadError(format!("receipt omits {name}")))?;
            let path = root.join(name);
            let metadata = path.metadata()?;
            if metadata.len() != record.bytes || sha256_file(&path)? != record.sha256 {
                return Err(FeatureLoadError(format!(
                    "receipt hash/size mismatch for {name}"
                )));
            }
        }

        let constraint_h = MappedNpyF32::open(&root.join("constraint_H.float32.npy"))?;
        let global_h = MappedNpyF32::open(&root.join("global_h.float32.npy"))?;
        if constraint_h.columns != HIDDEN_DIM || global_h.columns != HIDDEN_DIM {
            return Err(FeatureLoadError(
                "sensor embedding width is not 2048".to_owned(),
            ));
        }

        let mut task_rows = HashMap::<String, TaskRows>::new();
        let rows_bytes = std::fs::read(root.join("rows.jsonl"))?;
        let mut start = 0usize;
        for end in memchr_iter(b'\n', &rows_bytes).chain(std::iter::once(rows_bytes.len())) {
            let line = &rows_bytes[start..end];
            start = end.saturating_add(1);
            if line.is_empty() {
                continue;
            }
            let record: RowRecord = serde_json::from_slice(line)?;
            let entry = task_rows.entry(record.task_id.clone()).or_default();
            if entry.family_id.is_empty() {
                entry.family_id = record.family_id.clone();
                entry.task_index = record.task_index;
            } else if entry.family_id != record.family_id || entry.task_index != record.task_index {
                return Err(FeatureLoadError(format!(
                    "task identity mismatch in rows for {}",
                    record.task_id
                )));
            }
            match record.kind.as_str() {
                "global" => {
                    if entry.global.replace(record.row).is_some() {
                        return Err(FeatureLoadError(format!(
                            "duplicate global feature row for {}",
                            record.task_id
                        )));
                    }
                }
                "constraint" => {
                    let clause = record.clause_index.ok_or_else(|| {
                        FeatureLoadError("constraint feature row omits clause_index".to_owned())
                    })?;
                    if entry.clauses.len() <= clause {
                        entry.clauses.resize(clause + 1, None);
                    }
                    if entry.clauses[clause].replace(record.row).is_some() {
                        return Err(FeatureLoadError(format!(
                            "duplicate constraint row for {}:{clause}",
                            record.task_id
                        )));
                    }
                }
                other => {
                    return Err(FeatureLoadError(format!(
                        "unknown extraction row kind {other:?}"
                    )))
                }
            }
        }
        if constraint_h.rows == 0 && global_h.rows == 0 {
            return Err(FeatureLoadError(
                "sensor extraction contains no rows".to_owned(),
            ));
        }
        Ok(Self {
            _root: root,
            constraint_h,
            global_h,
            task_rows,
        })
    }

    /// Materialize the compact callback view for one public task.
    pub fn load_task(&self, task: &InferenceTask) -> Result<SemanticFeatures, FeatureLoadError> {
        let rows = self.task_rows.get(&task.id).ok_or_else(|| {
            FeatureLoadError(format!("task {} is absent from extraction rows", task.id))
        })?;
        if rows.family_id != task.family_id || rows.clauses.len() != task.clauses.len() {
            return Err(FeatureLoadError(format!(
                "extraction row identity/clauses mismatch for {}",
                task.id
            )));
        }
        let global_row = rows
            .global
            .ok_or_else(|| FeatureLoadError("global embedding row is missing".to_owned()))?;
        let global = self.global_h.row(global_row)?.to_vec().into_boxed_slice();
        let mut clauses = Vec::with_capacity(rows.clauses.len() * HIDDEN_DIM);
        for (clause, row) in rows.clauses.iter().enumerate() {
            let row = row.ok_or_else(|| {
                FeatureLoadError(format!("clause row {clause} is missing for {}", task.id))
            })?;
            clauses.extend_from_slice(self.constraint_h.row(row)?);
        }
        Ok(SemanticFeatures::from_projection(
            task,
            HIDDEN_DIM,
            clauses.into_boxed_slice(),
            global,
        )?)
    }
}

fn parse_shape(header: &str) -> Result<Vec<usize>, FeatureLoadError> {
    let key = header
        .find("'shape'")
        .or_else(|| header.find("\"shape\""))
        .ok_or_else(|| FeatureLoadError("NPY shape field is absent".to_owned()))?;
    let remainder = &header[key..];
    let open = remainder
        .find('(')
        .ok_or_else(|| FeatureLoadError("NPY shape tuple is malformed".to_owned()))?;
    let close = remainder[open + 1..]
        .find(')')
        .map(|offset| open + 1 + offset)
        .ok_or_else(|| FeatureLoadError("NPY shape tuple is unterminated".to_owned()))?;
    remainder[open + 1..close]
        .split(',')
        .filter_map(|part| {
            let part = part.trim();
            (!part.is_empty()).then(|| part.parse::<usize>())
        })
        .map(|value| {
            value.map_err(|error| FeatureLoadError(format!("invalid NPY dimension: {error}")))
        })
        .collect()
}

fn sha256_file(path: &Path) -> Result<String, FeatureLoadError> {
    let mut file = File::open(path)?;
    let mut digest = Sha256::new();
    // Windows reserves only a 1 MiB main-thread stack by default. A 1 MiB
    // local buffer overflows when hashing from the already-nested receipt
    // validation path, so keep the reusable streaming buffer comfortably
    // below that limit.
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let bytes = file.read(&mut buffer)?;
        if bytes == 0 {
            break;
        }
        digest.update(&buffer[..bytes]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

#[cfg(test)]
mod tests {
    use super::{parse_shape, MappedSensorExtraction, HIDDEN_DIM};
    use r1_world::InferenceTask;
    use std::path::PathBuf;

    #[test]
    fn parses_rank_two_npy_shapes() {
        assert_eq!(
            parse_shape("{'shape': (872, 2048), }").unwrap(),
            [872, 2048]
        );
        assert_eq!(parse_shape("{\"shape\": (2, 3), }").unwrap(), [2, 3]);
    }

    #[test]
    fn rejects_missing_or_malformed_shapes() {
        assert!(parse_shape("{'descr': '<f4'}").is_err());
        assert!(parse_shape("{'shape': (2, bad), }").is_err());
    }

    #[test]
    fn receipt_checked_real_extraction_smoke_when_paths_are_configured() {
        let Some(extraction) = std::env::var_os("R1_STAGE1_SENSOR_DIR") else {
            return;
        };
        let public_path = PathBuf::from(
            std::env::var_os("R1_STAGE1_PUBLIC_TASKS").expect("public tasks path required"),
        );
        let support_path = PathBuf::from(
            std::env::var_os("R1_STAGE1_SUPPORT_MANIFEST").expect("support path required"),
        );
        let store = MappedSensorExtraction::open(extraction, &public_path, &support_path).unwrap();
        let first_line = std::fs::read(&public_path)
            .unwrap()
            .split(|byte| *byte == b'\n')
            .find(|line| !line.is_empty())
            .unwrap()
            .to_vec();
        let task: InferenceTask = serde_json::from_slice(&first_line).unwrap();
        let features = store.load_task(&task).unwrap();
        features.validate_for(&task).unwrap();
        assert_eq!(features.hidden_dim, HIDDEN_DIM);
        assert_eq!(features.global_embedding.len(), HIDDEN_DIM);
        assert_eq!(features.constraint_count, task.clauses.len());
    }
}
