use crate::{FOSSIL_ROOT, RAW_SOURCE_HASH, ROADMAP_ROOT};
use obs_open_03a::{AccessAudit, AtlasSession};
use obs_open_meas02::sha256_file;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

const ROADMAP_DIR: &str = "studies/obs-open-01/sentinel-behavioral-qualification-compound";
const FOSSIL_SEAL: &str = "studies/obs-open-01/sentinel-memory-metrology/seal";
const EXPECTED_CANONICAL_HEAD: &str = "192e86c178c651a169f6984d8a7c4eea9a878524";
const CANONICAL_FILES: [(&str, &str); 4] = [
    (
        "src/data_plane/bars.rs",
        "cd5818bcbffbef2fedb74fa6216e58d66688a68c830cc99bf0cd78845b7ca941",
    ),
    (
        "src/data_plane/event.rs",
        "9683e54181388e45fe8eed446bd1cca51d9792306c5e7c4368c92fb1f6cdbb74",
    ),
    (
        "src/data_plane/catalog.rs",
        "00e97c679190b1d12a933b8ddccadc69f3d624f4aa7d509a9ff6e44d385bbd39",
    ),
    (
        "docs/CANONICAL_DATA_PLANE.md",
        "560419445d1e70c8ba00153375107dfb7550fe3495eda74f64721d27def013da",
    ),
];

pub struct BoundAuthority {
    pub sessions: Vec<AtlasSession>,
    pub access: AccessAudit,
    pub fossil_members: usize,
    pub roadmap_members: usize,
    pub canonical: CanonicalSubstrate,
}

#[derive(Debug, Serialize)]
pub struct CanonicalMember {
    pub path: String,
    pub bytes: u64,
    pub sha256: String,
}

#[derive(Debug, Serialize)]
pub struct CanonicalSubstrate {
    pub repository: String,
    pub git_head: String,
    pub worktree_clean: bool,
    pub members: Vec<CanonicalMember>,
    pub price_storage: &'static str,
    pub time_storage: &'static str,
    pub event_time_fields: [&'static str; 3],
    pub source_precision_field: &'static str,
    pub admitted_bar_timeframes: [&'static str; 4],
    pub m1_bar_timeframe_admitted: bool,
    pub historical_mt5_bar_source_admitted: bool,
    pub direct_drop_in_for_04a: bool,
}

pub fn open(
    repo: &Path,
    canonical_repo: &Path,
) -> Result<BoundAuthority, Box<dyn std::error::Error>> {
    let fossil = repo.join(FOSSIL_SEAL);
    let verified_root = obs_open_04a::seal::verify(&fossil)?;
    if verified_root != FOSSIL_ROOT {
        return Err(format!("FOSSIL_ROOT_DRIFT:{verified_root}").into());
    }
    let fossil_members = manifest_count(&fossil.join("content_manifest.tsv"))?;
    let roadmap = repo.join(ROADMAP_DIR);
    let roadmap_root = sha256_file(&roadmap.join("CANONICAL_ROADMAP_CONTENT_MANIFEST.tsv"))?;
    if roadmap_root != ROADMAP_ROOT {
        return Err(format!("ROADMAP_ROOT_DRIFT:{roadmap_root}").into());
    }
    let roadmap_members = verify_two_column_manifest(
        &roadmap,
        &roadmap.join("CANONICAL_ROADMAP_CONTENT_MANIFEST.tsv"),
    )?;
    let bound = obs_open_04a::authority::open(repo)?;
    if bound.raw_source_hash != RAW_SOURCE_HASH {
        return Err("04A_RAW_SOURCE_HASH_DRIFT".into());
    }
    if bound.access.d_a_outcome_registry_applications != 0
        || bound.access.d_b_ohlc_values_decoded != 0
        || bound.access.d_b_outcome_registry_applications != 0
        || bound.access.d_b_derived_outcomes_inspected != 0
        || bound.access.d_b_formal_scores != 0
        || bound.access.d_c_membership_rows_decoded != 0
        || bound.access.d_c_observations_read != 0
        || bound.access.d_c_outcomes_computed != 0
    {
        return Err("G0_ACCESS_FIREWALL_FAILURE".into());
    }
    let canonical = verify_canonical_substrate(canonical_repo)?;
    Ok(BoundAuthority {
        sessions: bound.sessions,
        access: bound.access,
        fossil_members,
        roadmap_members,
        canonical,
    })
}

fn verify_canonical_substrate(
    root: &Path,
) -> Result<CanonicalSubstrate, Box<dyn std::error::Error>> {
    let head = git(root, &["rev-parse", "HEAD"])?;
    if head != EXPECTED_CANONICAL_HEAD {
        return Err(format!("CANONICAL_HEAD_DRIFT:{head}").into());
    }
    let status = git(root, &["status", "--porcelain"])?;
    if !status.is_empty() {
        return Err("CANONICAL_WORKTREE_DIRTY".into());
    }
    let mut members = Vec::with_capacity(CANONICAL_FILES.len());
    for (relative, expected) in CANONICAL_FILES {
        let path = root.join(relative);
        let actual = sha256_file(&path)?;
        if actual != expected {
            return Err(format!("CANONICAL_MEMBER_DRIFT:{relative}:{actual}").into());
        }
        members.push(CanonicalMember {
            path: relative.into(),
            bytes: fs::metadata(path)?.len(),
            sha256: actual,
        });
    }
    audit_source_contract(root)?;
    Ok(CanonicalSubstrate {
        repository: root.display().to_string(),
        git_head: head,
        worktree_clean: true,
        members,
        price_storage: "SIGNED_I64_CANONICAL_UNITS_WITH_PROVIDER_PRICE_SCALE",
        time_storage: "SIGNED_I64_NANOSECONDS",
        event_time_fields: ["ts_event_ns", "ts_received_ns", "ts_effective_ns"],
        source_precision_field: "TIME_QUALITY_CLASS_PRESENT; NUMERIC_SOURCE_RESOLUTION_NOT_IN_CANONICAL_BAR",
        admitted_bar_timeframes: ["M4", "M20", "H2", "H4"],
        m1_bar_timeframe_admitted: false,
        historical_mt5_bar_source_admitted: false,
        direct_drop_in_for_04a: false,
    })
}

fn audit_source_contract(root: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let bars = fs::read_to_string(root.join("src/data_plane/bars.rs"))?;
    let events = fs::read_to_string(root.join("src/data_plane/event.rs"))?;
    let catalog = fs::read_to_string(root.join("src/data_plane/catalog.rs"))?;
    let doc = fs::read_to_string(root.join("docs/CANONICAL_DATA_PLANE.md"))?;
    for required in [
        "pub ts_open_ns: i64",
        "pub ts_close_ns: i64",
        "pub open: i64",
        "pub high: i64",
        "pub low: i64",
        "pub close: i64",
        "Self::M4",
        "Self::M20",
        "Self::H2",
        "Self::H4",
    ] {
        if !bars.contains(required) {
            return Err(format!("CANONICAL_BAR_CONTRACT_MISSING:{required}").into());
        }
    }
    for required in [
        "pub ts_event_ns: i64",
        "pub ts_received_ns: i64",
        "pub ts_effective_ns: i64",
    ] {
        if !events.contains(required) {
            return Err(format!("CANONICAL_TIME_CONTRACT_MISSING:{required}").into());
        }
    }
    if !catalog.contains("pub price_scale: i64")
        || !doc.contains("outputs: M4, M20, H2, and H4")
        || bars.contains("Self::M1")
    {
        return Err("CANONICAL_PRICE_OR_TIMEFRAME_CONTRACT_DRIFT".into());
    }
    Ok(())
}

fn git(root: &Path, args: &[&str]) -> Result<String, Box<dyn std::error::Error>> {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()?;
    if !output.status.success() {
        return Err(format!("GIT_FAILURE:{}", String::from_utf8_lossy(&output.stderr)).into());
    }
    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}

fn manifest_count(path: &Path) -> Result<usize, Box<dyn std::error::Error>> {
    Ok(fs::read_to_string(path)?.lines().skip(1).count())
}

fn verify_two_column_manifest(
    root: &Path,
    path: &Path,
) -> Result<usize, Box<dyn std::error::Error>> {
    let text = fs::read_to_string(path)?;
    let mut count = 0;
    for line in text.lines().skip(1) {
        let fields = line.split('\t').collect::<Vec<_>>();
        if fields.len() != 2 || fields[0].contains("..") || PathBuf::from(fields[0]).is_absolute() {
            return Err("ROADMAP_MANIFEST_MALFORMED".into());
        }
        let member = root.join(fields[0]);
        if sha256_file(&member)? != fields[1] {
            return Err(format!("ROADMAP_MEMBER_DRIFT:{}", fields[0]).into());
        }
        count += 1;
    }
    Ok(count)
}

pub fn sha256(bytes: &[u8]) -> String {
    let mut hash = Sha256::new();
    hash.update(bytes);
    format!("{:x}", hash.finalize())
}
