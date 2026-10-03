use crate::model::PARENT_ROOT;
use memmap2::Mmap;
use obs_open_03a::PackedOutcome;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::path::{Path, PathBuf};

pub struct AtlasAuthority {
    pub root: PathBuf,
    ledger: Mmap,
    pub member_count: usize,
    pub ledger_hash: String,
}

impl AtlasAuthority {
    pub fn open(root: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        let root = fs::canonicalize(root)?;
        let receipt: Value =
            serde_json::from_slice(&fs::read(root.join("OBS_OPEN_03A_ROOT_RECEIPT.json"))?)?;
        if receipt.get("obs_open_03a_root").and_then(Value::as_str) != Some(PARENT_ROOT)
            || receipt.get("status").and_then(Value::as_str) != Some("PASS")
            || receipt
                .get("D_B_outcome_registry_applications")
                .and_then(Value::as_u64)
                != Some(0)
            || receipt.get("D_C_observations_read").and_then(Value::as_u64) != Some(0)
        {
            return Err("PARENT_ATLAS_ROOT_OR_FIREWALL_MISMATCH".into());
        }
        let manifest = fs::read(root.join("content_manifest.tsv"))?;
        if sha256(&manifest) != PARENT_ROOT {
            return Err("PARENT_CONTENT_MANIFEST_ROOT_MISMATCH".into());
        }
        let text = std::str::from_utf8(&manifest)?;
        let mut member_count = 0;
        for line in text.lines().skip(1) {
            let mut fields = line.split('\t');
            let relative = fields.next().ok_or("MANIFEST_PATH_MISSING")?;
            let bytes: u64 = fields.next().ok_or("MANIFEST_BYTES_MISSING")?.parse()?;
            let hash = fields.next().ok_or("MANIFEST_HASH_MISSING")?;
            if relative.contains("..") || Path::new(relative).is_absolute() {
                return Err(format!("UNSAFE_PARENT_MEMBER:{relative}").into());
            }
            let path = root.join(relative);
            if fs::metadata(&path)?.len() != bytes || sha256_file(&path)? != hash {
                return Err(format!("PARENT_MEMBER_DRIFT:{relative}").into());
            }
            member_count += 1;
        }
        let ledger_path = root.join("atlas/outcome_ledger.bin");
        let ledger_hash = sha256_file(&ledger_path)?;
        let ledger = unsafe { Mmap::map(&File::open(ledger_path)?) }?;
        bytemuck::try_cast_slice::<u8, PackedOutcome>(&ledger)
            .map_err(|_| "PACKED_OUTCOME_LAYOUT_MISMATCH")?;
        Ok(Self {
            root,
            ledger,
            member_count,
            ledger_hash,
        })
    }

    pub fn records(&self) -> &[PackedOutcome] {
        bytemuck::cast_slice(&self.ledger)
    }
}

pub fn sha256_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file) }?;
    Ok(sha256(&mmap))
}

pub fn sha256(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}
