use serde::de::DeserializeOwned;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter};
use std::path::{Path, PathBuf};

pub(super) fn derive_seed(base: u64, state_id: &str, rollout_index: u32) -> u64 {
    let mut hash = Sha256::new();
    hash.update(base.to_le_bytes());
    hash.update(state_id.as_bytes());
    hash.update(rollout_index.to_le_bytes());
    u64::from_le_bytes(hash.finalize()[..8].try_into().expect("SHA-256 prefix"))
}

pub(super) struct StableRng {
    pub(super) state: u64,
}

impl StableRng {
    pub(super) fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    pub(super) fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        value ^ (value >> 31)
    }

    pub(super) fn unit_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / ((1u64 << 53) as f64))
    }
}

pub(super) fn read_jsonl_bytes<T: DeserializeOwned>(
    bytes: &[u8],
    source: &Path,
) -> Result<Vec<T>, String> {
    BufReader::new(bytes)
        .lines()
        .enumerate()
        .filter_map(|(index, line)| match line {
            Ok(value) if value.trim().is_empty() => None,
            Ok(value) => Some(
                serde_json::from_str(&value)
                    .map_err(|error| format!("parse {}:{}: {error}", source.display(), index + 1)),
            ),
            Err(error) => Some(Err(format!(
                "read {}:{}: {error}",
                source.display(),
                index + 1
            ))),
        })
        .collect()
}

pub(super) fn new_writer(path: &Path) -> Result<BufWriter<File>, String> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| format!("create {}: {error}", path.display()))?;
    Ok(BufWriter::new(file))
}

pub(super) fn ensure_distinct_new_paths(paths: &[&Path]) -> Result<(), String> {
    let mut unique = hashbrown::HashSet::with_capacity(paths.len());
    for path in paths {
        let absolute = canonical_output_path(path)?;
        if !unique.insert(absolute.clone()) {
            return Err(format!(
                "output paths must be distinct: {}",
                absolute.display()
            ));
        }
        if absolute.exists() {
            return Err(format!("refusing to overwrite {}", absolute.display()));
        }
    }
    Ok(())
}

fn canonical_output_path(path: &Path) -> Result<PathBuf, String> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let parent = parent
        .canonicalize()
        .map_err(|error| format!("resolve output directory {}: {error}", parent.display()))?;
    let name = path.file_name().ok_or("output path has no filename")?;
    Ok(parent.join(name))
}

pub(super) fn sha256_hex(bytes: &[u8]) -> String {
    hex_bytes(&Sha256::digest(bytes))
}

pub(super) fn sha256_file(path: &Path) -> Result<String, String> {
    let bytes =
        fs::read(path).map_err(|error| format!("read {} for digest: {error}", path.display()))?;
    Ok(sha256_hex(&bytes))
}

pub(super) fn file_record(path: &Path, expected_sha256: &str) -> Result<Value, String> {
    let metadata =
        fs::metadata(path).map_err(|error| format!("stat {}: {error}", path.display()))?;
    let actual = sha256_file(path)?;
    if actual != expected_sha256 {
        return Err(format!(
            "file digest changed while writing {}",
            path.display()
        ));
    }
    Ok(json!({
        "path": path.canonicalize().unwrap_or_else(|_| path.to_path_buf()),
        "sha256": actual,
        "bytes": metadata.len()
    }))
}

pub(super) fn count_jsonl_lines(path: &Path) -> Result<usize, String> {
    let file = File::open(path).map_err(|error| format!("open {}: {error}", path.display()))?;
    let mut count = 0;
    for (index, line) in BufReader::new(file).lines().enumerate() {
        let line =
            line.map_err(|error| format!("read {}:{}: {error}", path.display(), index + 1))?;
        if !line.trim().is_empty() {
            count += 1;
        }
    }
    Ok(count)
}

pub(super) fn parse_digest(value: &str) -> Result<[u8; 32], String> {
    if value.len() != 64 {
        return Err("SHA-256 digest must be 64 hexadecimal characters".into());
    }
    let mut result = [0u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = (pair[0] as char).to_digit(16).ok_or("invalid hex digest")? as u8;
        let low = (pair[1] as char).to_digit(16).ok_or("invalid hex digest")? as u8;
        result[index] = (high << 4) | low;
    }
    Ok(result)
}

pub(super) fn hex_bytes(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(HEX[usize::from(byte >> 4)] as char);
        output.push(HEX[usize::from(byte & 0x0f)] as char);
    }
    output
}
