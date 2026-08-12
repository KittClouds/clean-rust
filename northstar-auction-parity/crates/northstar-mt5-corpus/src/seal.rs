use std::{
    fs::{self, File},
    path::{Path, PathBuf},
};

use hashbrown::{HashMap, HashSet};
use memmap2::MmapOptions;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{
    CorpusError, DatasetCounts, RelationalReport, Result, error::io, validate_run_relations,
};
use northstar_auction_contract::{DATASET_CONTRACT, DATASET_SCHEMA, RESEARCH_GENERATION};

const CORPUS_CONTRACT: &str = "MST_RG2_IMMUTABLE_CORPUS_SEAL_V1";
const RUN_CONTRACT: &str = "MST_IMMUTABLE_RUN_SEAL_V1";
const CORPUS_HASH_DOMAIN: &[u8] = b"MST_RG2_CANONICAL_CORPUS_V1\0";

#[derive(Debug, Deserialize)]
pub struct CorpusSeal {
    pub contract: String,
    pub status: String,
    pub research_generation: u16,
    pub run_count: usize,
    pub canonical_corpus_sha256: String,
    pub campaign_manifest_sha256: String,
    pub configuration_hash: String,
    pub dataset_contract: String,
    pub dataset_schema: String,
    pub artifacts: HashMap<String, String>,
}

#[derive(Debug, Deserialize)]
pub struct RunSeal {
    pub contract: String,
    pub status: String,
    pub run_key: String,
    pub invocation_id: String,
    pub window_id: String,
    pub manifest_sha256: String,
    pub canonical_dataset_hash: String,
    pub sealed_payload_sha256: String,
    pub file_count: usize,
    pub files: Vec<SealedFile>,
}

#[derive(Debug, Deserialize)]
pub struct SealedFile {
    pub path: String,
    pub bytes: u64,
    pub sha256: String,
}

#[derive(Debug, Deserialize)]
pub struct TerminalReceipt {
    pub dataset_schema: String,
    pub contract_id: String,
    pub research_generation: String,
    pub run_key: String,
    pub invocation_id: String,
    pub record_type: String,
    pub run_status: String,
    pub canonical_instrument: String,
    pub data_source_id: String,
    pub data_fingerprint: String,
    pub config_hash: String,
    pub run_complete: String,
    pub contract_valid: String,
    pub relational_valid: String,
    pub events_emitted: String,
    pub attempts_started: String,
    pub attempts_resolved: String,
    pub attempts_censored: String,
    pub episodes_started: String,
    pub episodes_resolved: String,
    pub episodes_censored: String,
    pub transits_started: String,
    pub transits_resolved: String,
    pub transits_censored: String,
    pub active_attempts: String,
    pub active_episodes: String,
    pub active_transits: String,
    pub event_rows: String,
    pub attempt_rows: String,
    pub episode_rows: String,
    pub context_rows: String,
    pub feature_rows: String,
    pub transit_rows: String,
    pub timestamp_encoding: String,
    pub timestamp_timezone: String,
    pub null_token: String,
}

#[derive(Debug, Deserialize)]
struct AdmissionReceipt {
    contract: String,
    status: String,
    run_key: String,
    invocation_id: String,
    canonical_dataset_hash: String,
}

#[derive(Debug, Serialize)]
pub struct RunReport {
    pub run_key: String,
    pub canonical_instrument: String,
    pub sealed_files: usize,
    pub sealed_bytes: u64,
    pub relational: RelationalReport,
}

#[derive(Debug, Serialize)]
pub struct CorpusReport {
    pub canonical_corpus_sha256: String,
    pub run_count: usize,
    pub sealed_file_count: usize,
    pub sealed_bytes: u64,
    pub datasets: DatasetCounts,
    pub runs: Vec<RunReport>,
}

pub struct CorpusVerifier {
    corpus_root: PathBuf,
    corpus_seal_path: PathBuf,
}

impl CorpusVerifier {
    #[must_use]
    pub fn new(corpus_root: impl Into<PathBuf>, corpus_seal_path: impl Into<PathBuf>) -> Self {
        Self {
            corpus_root: corpus_root.into(),
            corpus_seal_path: corpus_seal_path.into(),
        }
    }

    pub fn verify(&self) -> Result<CorpusReport> {
        let corpus_seal: CorpusSeal = read_json(&self.corpus_seal_path)?;
        validate_corpus_identity(&corpus_seal)?;
        self.verify_seal_artifacts(&corpus_seal)?;

        let mut directories = fs::read_dir(&self.corpus_root)
            .map_err(|error| io(&self.corpus_root, error))?
            .filter_map(|entry| entry.ok())
            .filter(|entry| entry.file_type().is_ok_and(|kind| kind.is_dir()))
            .map(|entry| entry.path())
            .collect::<Vec<_>>();
        directories.sort_unstable();
        if directories.len() != corpus_seal.run_count {
            return Err(CorpusError::Contract(format!(
                "corpus has {} run directories, seal declares {}",
                directories.len(),
                corpus_seal.run_count
            )));
        }

        let mut canonical_rows = Vec::with_capacity(directories.len());
        let mut reports = Vec::with_capacity(directories.len());
        let mut sealed_file_count = 0_usize;
        let mut sealed_bytes = 0_u64;
        let mut datasets = DatasetCounts::default();
        let mut run_keys = HashSet::with_capacity(directories.len());

        for run_dir in directories {
            let (run_seal, terminal) = self.verify_run(&run_dir, &corpus_seal)?;
            if !run_keys.insert(run_seal.run_key.clone()) {
                return Err(CorpusError::Contract(format!(
                    "duplicate run key {}",
                    run_seal.run_key
                )));
            }
            let relational = validate_run_relations(&run_dir, &terminal)?;
            datasets += relational.counts;
            let run_bytes = run_seal.files.iter().map(|file| file.bytes).sum::<u64>();
            sealed_file_count += run_seal.file_count;
            sealed_bytes += run_bytes;
            canonical_rows.push(canonical_row(&terminal, &run_seal));
            reports.push(RunReport {
                run_key: run_seal.run_key.clone(),
                canonical_instrument: terminal.canonical_instrument.clone(),
                sealed_files: run_seal.file_count,
                sealed_bytes: run_bytes,
                relational,
            });
        }

        canonical_rows.sort_unstable();
        let canonical_hash = corpus_hash(&corpus_seal.campaign_manifest_sha256, &canonical_rows);
        if canonical_hash != corpus_seal.canonical_corpus_sha256 {
            return Err(CorpusError::Mutation {
                path: self.corpus_seal_path.clone(),
                detail: format!("canonical corpus hash {canonical_hash} does not match seal"),
            });
        }
        reports.sort_unstable_by(|left, right| left.run_key.cmp(&right.run_key));
        Ok(CorpusReport {
            canonical_corpus_sha256: canonical_hash,
            run_count: reports.len(),
            sealed_file_count,
            sealed_bytes,
            datasets,
            runs: reports,
        })
    }

    fn verify_seal_artifacts(&self, seal: &CorpusSeal) -> Result<()> {
        let root = self
            .corpus_seal_path
            .parent()
            .ok_or_else(|| CorpusError::Contract("corpus seal has no parent directory".into()))?;
        for (relative, expected) in &seal.artifacts {
            let path = root.join(relative);
            let actual = sha256_file(&path)?;
            if actual != *expected {
                return Err(CorpusError::Mutation {
                    path,
                    detail: "Phase 10 artifact SHA-256 mismatch".into(),
                });
            }
        }
        Ok(())
    }

    fn verify_run(
        &self,
        run_dir: &Path,
        corpus: &CorpusSeal,
    ) -> Result<(RunSeal, TerminalReceipt)> {
        let seal_path = run_dir.join("seal.json");
        let seal: RunSeal = read_json(&seal_path)?;
        if seal.contract != RUN_CONTRACT || seal.status != "SEALED" {
            return Err(CorpusError::Contract(format!(
                "invalid run seal at {}",
                seal_path.display()
            )));
        }
        if seal.file_count != seal.files.len()
            || seal.manifest_sha256 != corpus.campaign_manifest_sha256
        {
            return Err(CorpusError::Contract(format!(
                "run seal accounting failed for {}",
                seal.run_key
            )));
        }
        if run_dir.file_name().and_then(|name| name.to_str()) != Some(seal.run_key.as_str()) {
            return Err(CorpusError::Contract(format!(
                "run directory does not equal run key {}",
                seal.run_key
            )));
        }

        let expected_paths = seal
            .files
            .iter()
            .map(|item| item.path.as_str())
            .collect::<HashSet<_>>();
        let actual_paths = collect_relative_files(run_dir)?;
        for relative in &actual_paths {
            if relative != "seal.json" && !expected_paths.contains(relative.as_str()) {
                return Err(CorpusError::ExtraFile(run_dir.join(relative)));
            }
        }
        drop(expected_paths);
        for item in &seal.files {
            let path = run_dir.join(item.path.replace('/', "\\"));
            verify_sealed_file(&path, item)?;
        }
        let payload_hash = sealed_payload_hash(&seal.files);
        if payload_hash != seal.sealed_payload_sha256 {
            return Err(CorpusError::Mutation {
                path: seal_path,
                detail: "sealed payload hash mismatch".into(),
            });
        }

        let terminal_path = run_dir.join("receipts/terminal_run_receipt.json");
        let terminal: TerminalReceipt = read_json(&terminal_path)?;
        validate_terminal(&terminal, &seal, corpus)?;
        let admission: AdmissionReceipt =
            read_json(&run_dir.join("receipts/admission_receipt.json"))?;
        if !matches!(
            admission.contract.as_str(),
            "MST_CORPUS_ADMISSION_V1" | "MST_CORPUS_ADMISSION_V2"
        ) || admission.status != "ADMITTED"
            || admission.run_key != seal.run_key
            || admission.invocation_id != seal.invocation_id
            || admission.canonical_dataset_hash != seal.canonical_dataset_hash
        {
            return Err(CorpusError::Contract(format!(
                "admission identity mismatch for {}",
                seal.run_key
            )));
        }
        Ok((seal, terminal))
    }
}

fn validate_corpus_identity(seal: &CorpusSeal) -> Result<()> {
    if seal.contract != CORPUS_CONTRACT
        || seal.status != "SEALED"
        || seal.research_generation != RESEARCH_GENERATION
        || seal.dataset_contract != DATASET_CONTRACT
        || seal.dataset_schema != DATASET_SCHEMA.to_string()
    {
        return Err(CorpusError::Contract(
            "unsupported corpus semantic identity".into(),
        ));
    }
    Ok(())
}

fn validate_terminal(terminal: &TerminalReceipt, run: &RunSeal, corpus: &CorpusSeal) -> Result<()> {
    let valid = terminal.dataset_schema == DATASET_SCHEMA.to_string()
        && terminal.contract_id == DATASET_CONTRACT
        && terminal.research_generation == RESEARCH_GENERATION.to_string()
        && terminal.run_key == run.run_key
        && terminal.invocation_id == run.invocation_id
        && terminal.record_type == "END"
        && terminal.run_status == "COMPLETE"
        && terminal.config_hash == corpus.configuration_hash
        && terminal.run_complete == "1"
        && terminal.contract_valid == "1"
        && terminal.relational_valid == "1"
        && terminal.timestamp_encoding == "unix_seconds"
        && terminal.timestamp_timezone == "MT5_SERVER"
        && terminal.null_token == "\\N";
    if !valid {
        return Err(CorpusError::Contract(format!(
            "terminal receipt failed closed for {}",
            run.run_key
        )));
    }
    Ok(())
}

fn canonical_row(terminal: &TerminalReceipt, seal: &RunSeal) -> String {
    [
        terminal.run_key.as_str(),
        terminal.config_hash.as_str(),
        terminal.dataset_schema.as_str(),
        terminal.data_source_id.as_str(),
        terminal.data_fingerprint.as_str(),
        seal.canonical_dataset_hash.as_str(),
        seal.sealed_payload_sha256.as_str(),
    ]
    .join("\t")
        + "\n"
}

fn corpus_hash(manifest_hash: &str, rows: &[String]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(CORPUS_HASH_DOMAIN);
    hasher.update(manifest_hash.as_bytes());
    for row in rows {
        hasher.update(row.as_bytes());
    }
    hex_digest(hasher.finalize())
}

fn sealed_payload_hash(files: &[SealedFile]) -> String {
    let rows = files
        .iter()
        .map(|file| format!("{}\t{}\t{}", file.path, file.bytes, file.sha256))
        .collect::<Vec<_>>();
    let mut hasher = Sha256::new();
    hasher.update(rows.join("\n").as_bytes());
    hex_digest(hasher.finalize())
}

fn sha256_file(path: &Path) -> Result<String> {
    let file = File::open(path).map_err(|error| io(path, error))?;
    let metadata = file.metadata().map_err(|error| io(path, error))?;
    if metadata.len() == 0 {
        return Ok(hex_digest(Sha256::digest([])));
    }
    // SAFETY: read-only map over an immutable sealed artifact.
    let mmap = unsafe { MmapOptions::new().map(&file) }.map_err(|error| io(path, error))?;
    Ok(hex_digest(Sha256::digest(&mmap)))
}

fn verify_sealed_file(path: &Path, receipt: &SealedFile) -> Result<()> {
    let metadata = fs::metadata(path).map_err(|error| io(path, error))?;
    if metadata.len() != receipt.bytes {
        return Err(CorpusError::Mutation {
            path: path.to_path_buf(),
            detail: "byte length mismatch".into(),
        });
    }
    if sha256_file(path)? != receipt.sha256 {
        return Err(CorpusError::Mutation {
            path: path.to_path_buf(),
            detail: "SHA-256 mismatch".into(),
        });
    }
    Ok(())
}

fn hex_digest(bytes: impl AsRef<[u8]>) -> String {
    let bytes = bytes.as_ref();
    let mut output = String::with_capacity(bytes.len() * 2);
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for &byte in bytes {
        output.push(HEX[usize::from(byte >> 4)] as char);
        output.push(HEX[usize::from(byte & 0x0f)] as char);
    }
    output
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T> {
    let bytes = fs::read(path).map_err(|error| io(path, error))?;
    let json = bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&bytes);
    serde_json::from_slice(json).map_err(|source| CorpusError::Json {
        path: path.to_path_buf(),
        source,
    })
}

fn collect_relative_files(root: &Path) -> Result<HashSet<String>> {
    fn walk(root: &Path, current: &Path, output: &mut HashSet<String>) -> Result<()> {
        for entry in fs::read_dir(current).map_err(|error| io(current, error))? {
            let entry = entry.map_err(|error| io(current, error))?;
            let path = entry.path();
            if entry
                .file_type()
                .map_err(|error| io(&path, error))?
                .is_dir()
            {
                walk(root, &path, output)?;
            } else {
                let relative = path
                    .strip_prefix(root)
                    .map_err(|_| CorpusError::Contract("path escaped run root".into()))?;
                output.insert(relative.to_string_lossy().replace('\\', "/"));
            }
        }
        Ok(())
    }
    let mut output = HashSet::new();
    walk(root, root, &mut output)?;
    Ok(output)
}

#[cfg(test)]
mod tests {
    use std::io::{Seek, SeekFrom, Write};

    use tempfile::NamedTempFile;

    use super::*;

    #[test]
    fn sealed_file_verification_rejects_same_length_mutation() {
        let mut file = NamedTempFile::new().unwrap();
        file.write_all(b"immutable-auction-ledger").unwrap();
        file.flush().unwrap();
        let receipt = SealedFile {
            path: "ledger.tsv".into(),
            bytes: file.as_file().metadata().unwrap().len(),
            sha256: sha256_file(file.path()).unwrap(),
        };
        verify_sealed_file(file.path(), &receipt).unwrap();

        file.seek(SeekFrom::Start(0)).unwrap();
        file.write_all(b"X").unwrap();
        file.flush().unwrap();
        assert!(matches!(
            verify_sealed_file(file.path(), &receipt),
            Err(CorpusError::Mutation { .. })
        ));
    }
}
