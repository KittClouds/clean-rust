use anyhow::{Context, Result};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

pub fn sha256(bytes: &[u8]) -> [u8; 32] { Sha256::digest(bytes).into() }

pub fn sha256_file(path: &Path) -> Result<String> {
    let mut file = fs::File::open(path).with_context(|| format!("open {}", path.display()))?;
    let mut hash = Sha256::new();
    let mut buffer = vec![0u8; 8 * 1024 * 1024];
    loop {
        let read = std::io::Read::read(&mut file, &mut buffer)?;
        if read == 0 { break; }
        hash.update(&buffer[..read]);
    }
    Ok(hex(&hash.finalize()))
}

pub fn hex(bytes: &[u8]) -> String { bytes.iter().map(|b| format!("{b:02x}")).collect() }

pub fn write_new_json<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    let bytes = serde_json::to_vec_pretty(value)?;
    anyhow::ensure!(!path.exists(), "refusing to overwrite {}", path.display());
    let nonce = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_nanos();
    let mut temp_name = path.as_os_str().to_os_string();
    temp_name.push(format!(".pending-{}-{nonce}", std::process::id()));
    let temp_path = std::path::PathBuf::from(temp_name);
    let mut file = OpenOptions::new().write(true).create_new(true).open(&temp_path)
        .with_context(|| format!("create immutable receipt temporary {}", temp_path.display()))?;
    file.write_all(&bytes)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    drop(file);
    fs::rename(&temp_path, path).with_context(|| format!("publish immutable receipt {}", path.display()))?;
    Ok(())
}
