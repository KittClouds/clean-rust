//! Checkpoints: derived state snapshots bound to exact journal positions.
//!
//! A checkpoint is an accelerator only. It is trusted only when both bound heads equal the
//! journal events at those sequence numbers, and when its payload digest verifies. Anything
//! else is skipped (and reported), never repaired, and replay from genesis is always valid.
//!
//! ```text
//! "KMCKPT02" | version u32 | tag_len u32 | main_seq u64 | main_head [32]
//! | memory_seq u64 | memory_head [32] | payload_len u64 | payload_sha256 [32] | tag | payload
//! ```

use std::fs;
use std::path::{Path, PathBuf};

use kammi_jcs::{raw_id, Sha256Id};

use crate::durable;
use crate::error::{io, Result};

const MAGIC: [u8; 8] = *b"KMCKPT02";
const VERSION: u32 = 1;
const FIXED_LEN: usize = 8 + 4 + 4 + 8 + 32 + 8 + 32 + 8 + 32;
/// Checkpoints kept after a new one is published.
pub const KEEP: usize = 3;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Position {
    pub seq: u64,
    pub head: Sha256Id,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Checkpoint {
    pub path: PathBuf,
    pub tag: String,
    pub main: Position,
    pub memory: Position,
    pub payload: Vec<u8>,
}

pub struct Checkpoints {
    dir: PathBuf,
}

impl Checkpoints {
    pub fn open(dir: &Path) -> Result<Self> {
        durable::create_dir_all(dir)?;
        Ok(Checkpoints {
            dir: dir.to_path_buf(),
        })
    }

    fn file_name(main: &Position, memory: &Position) -> String {
        format!("ckpt-{:020}-{:020}.ckpt", main.seq, memory.seq)
    }

    /// Publishes a checkpoint atomically and prunes all but the newest [`KEEP`].
    pub fn write(
        &self,
        tag: &str,
        main: Position,
        memory: Position,
        payload: &[u8],
    ) -> Result<PathBuf> {
        let mut out = Vec::with_capacity(FIXED_LEN + tag.len() + payload.len());
        out.extend_from_slice(&MAGIC);
        out.extend_from_slice(&VERSION.to_le_bytes());
        out.extend_from_slice(&(tag.len() as u32).to_le_bytes());
        out.extend_from_slice(&main.seq.to_le_bytes());
        out.extend_from_slice(&main.head.0);
        out.extend_from_slice(&memory.seq.to_le_bytes());
        out.extend_from_slice(&memory.head.0);
        out.extend_from_slice(&(payload.len() as u64).to_le_bytes());
        out.extend_from_slice(&raw_id(payload).0);
        out.extend_from_slice(tag.as_bytes());
        out.extend_from_slice(payload);
        let path = self.dir.join(Self::file_name(&main, &memory));
        durable::publish_with(
            &self.dir.join("staging"),
            &path,
            &out,
            Some("checkpoint.after_write"),
            Some("checkpoint.after_rename"),
        )?;
        let mut names = self.names()?;
        while names.len() > KEEP {
            let oldest = names.remove(0);
            let _ = fs::remove_file(self.dir.join(oldest));
        }
        Ok(path)
    }

    fn names(&self) -> Result<Vec<String>> {
        let mut names: Vec<String> = fs::read_dir(&self.dir)
            .map_err(io(&self.dir))?
            .filter_map(|e| e.ok())
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| n.starts_with("ckpt-") && n.ends_with(".ckpt"))
            .collect();
        names.sort();
        Ok(names)
    }

    fn parse(path: &Path) -> Option<Checkpoint> {
        let bytes = fs::read(path).ok()?;
        if bytes.len() < FIXED_LEN || bytes[..8] != MAGIC {
            return None;
        }
        let u32_at = |at: usize| u32::from_le_bytes(bytes[at..at + 4].try_into().unwrap());
        let u64_at = |at: usize| u64::from_le_bytes(bytes[at..at + 8].try_into().unwrap());
        let id_at = |at: usize| Sha256Id(bytes[at..at + 32].try_into().unwrap());
        if u32_at(8) != VERSION {
            return None;
        }
        let tag_len = u32_at(12) as usize;
        let main = Position {
            seq: u64_at(16),
            head: id_at(24),
        };
        let memory = Position {
            seq: u64_at(56),
            head: id_at(64),
        };
        let payload_len = u64_at(96) as usize;
        let digest = id_at(104);
        if bytes.len() != FIXED_LEN + tag_len + payload_len {
            return None;
        }
        let tag = String::from_utf8(bytes[FIXED_LEN..FIXED_LEN + tag_len].to_vec()).ok()?;
        let payload = bytes[FIXED_LEN + tag_len..].to_vec();
        if raw_id(&payload) != digest {
            return None;
        }
        Some(Checkpoint {
            path: path.to_path_buf(),
            tag,
            main,
            memory,
            payload,
        })
    }

    /// Newest checkpoint for which `bound` confirms both journal positions. Returns it with
    /// the paths of any newer checkpoints that were rejected.
    pub fn latest(
        &self,
        bound: impl Fn(&Position, &Position) -> bool,
    ) -> Result<(Option<Checkpoint>, Vec<PathBuf>)> {
        let mut rejected = Vec::new();
        for name in self.names()?.into_iter().rev() {
            let path = self.dir.join(&name);
            match Self::parse(&path) {
                Some(checkpoint) if bound(&checkpoint.main, &checkpoint.memory) => {
                    return Ok((Some(checkpoint), rejected))
                }
                _ => rejected.push(path),
            }
        }
        Ok((None, rejected))
    }
}
