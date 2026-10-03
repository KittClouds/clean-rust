use crate::model::*;
use memmap2::Mmap;
use obs_open_03a::{AtlasSession, PackedOutcome, load_atlas_authority, raw_path};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::path::{Path, PathBuf};

pub struct BoundAuthority {
    pub sessions: Vec<AtlasSession>,
    ledger: Mmap,
    pub atlas_member_count: usize,
    pub atlas_ledger_sha256: String,
    pub raw_source_sha256: String,
    pub d_a_bars_read: usize,
    pub d_a_gap_sessions: usize,
    pub atlas_root: PathBuf,
}

impl BoundAuthority {
    pub fn open(repository: &Path, atlas_root: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        verify_repo_parents(repository)?;
        let atlas_root = fs::canonicalize(atlas_root)?;
        let receipt: Value = serde_json::from_slice(&fs::read(
            atlas_root.join("OBS_OPEN_03A_ROOT_RECEIPT.json"),
        )?)?;
        if receipt["obs_open_03a_root"].as_str() != Some(ATLAS_ROOT)
            || receipt["D_B_outcome_registry_applications"].as_u64() != Some(0)
            || receipt["D_C_observations_read"].as_u64() != Some(0)
        {
            return Err("ATLAS_ROOT_OR_FIREWALL_DRIFT".into());
        }
        let manifest = fs::read(atlas_root.join("content_manifest.tsv"))?;
        if sha256(&manifest) != ATLAS_ROOT {
            return Err("ATLAS_MANIFEST_ROOT_DRIFT".into());
        }
        let atlas_member_count = verify_manifest(&atlas_root, &manifest)?;
        let ledger_path = atlas_root.join("atlas/outcome_ledger.bin");
        let atlas_ledger_sha256 = sha256_file(&ledger_path)?;
        let ledger = unsafe { Mmap::map(&File::open(&ledger_path)?) }?;
        bytemuck::try_cast_slice::<u8, PackedOutcome>(&ledger)
            .map_err(|_| "OUTCOME_LEDGER_LAYOUT_DRIFT")?;

        let loaded = load_atlas_authority(repository, &raw_path())?;
        if loaded.sessions.len() != D_A_SESSIONS
            || loaded.access.d_b_outcome_registry_applications != 0
            || loaded.access.d_c_observations_read != 0
        {
            return Err("D_A_SOURCE_FIREWALL_DRIFT".into());
        }
        Ok(Self {
            sessions: loaded.sessions,
            ledger,
            atlas_member_count,
            atlas_ledger_sha256,
            raw_source_sha256: loaded.raw_source_hash,
            d_a_bars_read: loaded.access.d_a_retained_causal_bars,
            d_a_gap_sessions: loaded.access.d_a_path_gap_sessions,
            atlas_root,
        })
    }

    pub fn records(&self) -> &[PackedOutcome] {
        bytemuck::cast_slice(&self.ledger)
    }
}

fn verify_repo_parents(repo: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let checks = [
        (
            "studies/obs-open-01/future-process-protocol/seal/obs_open_03ap_root_receipt.json",
            "obs_open_03ap_root",
            FUTURE_PROTOCOL_ROOT,
        ),
        (
            "studies/obs-open-01/future-process-atlas/seal/OBS_OPEN_03A_ROOT_RECEIPT.json",
            "obs_open_03a_root",
            ATLAS_ROOT,
        ),
        (
            "studies/obs-open-01/future-process-atlas-inspection/seal/OBS_OPEN_03AI_ROOT_RECEIPT.json",
            "obs_open_03ai_root",
            ANATOMY_ROOT,
        ),
        (
            "studies/obs-open-01/measurement-surface/seal/meas02_root_receipt.json",
            "meas02_root",
            MEAS02_ROOT,
        ),
        (
            "studies/obs-open-01/qualification/universe/seal/universe_qualification_root_receipt.json",
            "qualification_root_sha256",
            UNIVERSE_ROOT,
        ),
    ];
    for (relative, field, expected) in checks {
        let value: Value = serde_json::from_slice(&fs::read(repo.join(relative))?)?;
        if value[field].as_str() != Some(expected) {
            return Err(format!("PARENT_ROOT_DRIFT:{relative}:{field}").into());
        }
    }
    Ok(())
}

fn verify_manifest(root: &Path, bytes: &[u8]) -> Result<usize, Box<dyn std::error::Error>> {
    let text = std::str::from_utf8(bytes)?;
    let mut count = 0;
    for line in text.lines().skip(1) {
        let mut f = line.split('\t');
        let relative = f.next().ok_or("MANIFEST_PATH_MISSING")?;
        let size: u64 = f.next().ok_or("MANIFEST_SIZE_MISSING")?.parse()?;
        let hash = f.next().ok_or("MANIFEST_HASH_MISSING")?;
        if relative.contains("..") || Path::new(relative).is_absolute() {
            return Err("UNSAFE_ATLAS_MEMBER".into());
        }
        let path = root.join(relative);
        if fs::metadata(&path)?.len() != size || sha256_file(&path)? != hash {
            return Err(format!("ATLAS_MEMBER_DRIFT:{relative}").into());
        }
        count += 1;
    }
    Ok(count)
}

pub fn sha256_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mmap = unsafe { Mmap::map(&File::open(path)?) }?;
    Ok(sha256(&mmap))
}

pub fn sha256(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    format!("{:x}", h.finalize())
}
