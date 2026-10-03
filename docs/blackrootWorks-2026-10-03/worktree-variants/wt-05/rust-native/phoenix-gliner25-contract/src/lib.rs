//! Bounded, sequential IPC. ORT versions never share a process.
use anyhow::{ensure, Context, Result};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use std::{
    fs::File,
    io::{Read, Write},
    path::{Path, PathBuf},
};

pub const CONTRACT: &str = "phoenix.gliner25/v1";
pub const MAX_FRAME: usize = 4 * 1024 * 1024;
pub const MAX_TEXT: usize = 256 * 1024;
pub const POLICY: &str =
    "fp32;cpu;threshold=0.5;chunk=384;overlap=64;flat;dynamic-router-cap=20;schema-max=14";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Asset {
    pub path: PathBuf,
    pub hash: [u8; 32],
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Bundle {
    pub contract: String,
    pub worker: Asset,
    pub ort: Asset,
    pub model_root: PathBuf,
    pub model_revision: String,
    pub threads: usize,
    pub files: Vec<Asset>,
}
impl Bundle {
    pub fn read(path: &Path) -> Result<Self> {
        ensure!(
            std::fs::metadata(path)?.len() <= MAX_FRAME as u64,
            "bundle too large"
        );
        let value: Self = serde_json::from_slice(&std::fs::read(path)?)?;
        ensure!(value.contract == CONTRACT, "wrong GLiNER worker contract");
        ensure!(
            (1..=16).contains(&value.threads),
            "thread count outside bounds"
        );
        ensure!(
            !value.files.is_empty() && value.files.len() <= 256,
            "asset count outside bounds"
        );
        Ok(value)
    }
    pub fn digest(&self) -> Result<[u8; 32]> {
        let mut h = blake3::Hasher::new();
        h.update(CONTRACT.as_bytes());
        h.update(POLICY.as_bytes());
        h.update(&serde_json::to_vec(self)?);
        Ok(*h.finalize().as_bytes())
    }
}
pub fn pin(asset: &Asset) -> Result<File> {
    let mut options = File::options();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.share_mode(1); // Permit readers, deny writers and replacement.
    }
    let f = options
        .open(&asset.path)
        .with_context(|| format!("open {}", asset.path.display()))?;
    ensure!(f.metadata()?.len() > 0, "empty asset");
    // SAFETY: caller retains the read-only handle; Windows denies mutation.
    let mmap = unsafe { memmap2::Mmap::map(&f)? };
    ensure!(
        blake3::hash(&mmap).as_bytes() == &asset.hash,
        "asset hash mismatch: {}",
        asset.path.display()
    );
    Ok(f)
}
pub fn asset(path: PathBuf) -> Result<Asset> {
    let file = File::open(&path)?;
    // SAFETY: enrollment reads installed, immutable model assets.
    let mmap = unsafe { memmap2::Mmap::map(&file)? };
    Ok(Asset {
        path,
        hash: *blake3::hash(&mmap).as_bytes(),
    })
}
#[derive(Debug, Serialize, Deserialize)]
pub struct Request {
    pub sequence: u64,
    pub text: String,
    pub labels: Vec<String>,
}
impl Request {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.sequence > 0 && self.text.len() <= MAX_TEXT,
            "request bounds"
        );
        ensure!(
            !self.labels.is_empty() && self.labels.len() <= 64,
            "label count bounds"
        );
        ensure!(
            self.labels.iter().all(|s| !s.is_empty() && s.len() <= 128),
            "label bounds"
        );
        Ok(())
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Span {
    pub start: u32,
    pub end: u32,
    pub text: String,
    pub label: String,
    pub score: f32,
}
#[derive(Debug, Serialize, Deserialize)]
pub enum Response {
    Ready {
        contract: String,
        bundle: [u8; 32],
        pid: u32,
    },
    Completed {
        sequence: u64,
        text_hash: [u8; 32],
        spans: Vec<Span>,
        inference_micros: u64,
    },
    Failed {
        sequence: u64,
        message: String,
    },
}
pub fn validate_spans(text: &str, labels: &[String], spans: &[Span]) -> Result<()> {
    ensure!(spans.len() <= 32_768, "span count bounds");
    for span in spans {
        ensure!(
            span.start < span.end
                && text.get(span.start as usize..span.end as usize) == Some(span.text.as_str()),
            "invalid source range"
        );
        ensure!(labels.contains(&span.label), "unrequested label");
        ensure!(
            span.score.is_finite() && (0.0..=1.0).contains(&span.score),
            "invalid confidence"
        );
    }
    Ok(())
}
pub fn write_frame<T: Serialize>(output: &mut impl Write, value: &T) -> Result<()> {
    let body = serde_json::to_vec(value)?;
    ensure!(body.len() <= MAX_FRAME, "frame too large");
    output.write_all(&(body.len() as u32).to_le_bytes())?;
    output.write_all(&body)?;
    output.flush()?;
    Ok(())
}
pub fn read_frame<T: DeserializeOwned>(input: &mut impl Read) -> Result<T> {
    let mut size = [0; 4];
    input.read_exact(&mut size)?;
    let size = u32::from_le_bytes(size) as usize;
    ensure!(size > 0 && size <= MAX_FRAME, "frame bounds");
    let mut body = vec![0; size];
    input.read_exact(&mut body)?;
    Ok(serde_json::from_slice(&body)?)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_truncation_and_oversize_before_allocation() {
        assert!(read_frame::<Response>(&mut &((MAX_FRAME as u32 + 1).to_le_bytes())[..]).is_err());
        assert!(read_frame::<Response>(&mut &[4, 0, 0, 0, b'{'][..]).is_err());
    }
    #[test]
    fn spans_are_exact_utf8_and_finite() {
        let labels = vec!["person".into()];
        let mut s = Span {
            start: 0,
            end: 5,
            text: "Écho".into(),
            label: "person".into(),
            score: 0.7,
        };
        assert!(validate_spans("Écho", &labels, &[s.clone()]).is_ok());
        s.start = 1;
        assert!(validate_spans("Écho", &labels, &[s.clone()]).is_err());
        s.start = 0;
        s.score = f32::NAN;
        assert!(validate_spans("Écho", &labels, &[s]).is_err());
    }
}
