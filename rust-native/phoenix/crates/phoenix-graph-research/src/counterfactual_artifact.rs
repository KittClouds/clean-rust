use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use compact_str::{format_compact, CompactString};
use memmap2::{Mmap, MmapOptions};

use crate::{
    validate_counterfactual_candidate_groups, CounterfactualCandidateGroupsError,
    CounterfactualCandidateGroupsManifest, CounterfactualCandidateGroupsPaths,
    FrozenCounterfactualCandidateGroups, COUNTERFACTUAL_CANDIDATE_GROUPS_BINARY_VERSION,
    COUNTERFACTUAL_CANDIDATE_GROUPS_SCHEMA,
};

pub struct CounterfactualCandidateGroupsBundle;

impl CounterfactualCandidateGroupsBundle {
    pub fn write(
        directory: &Path,
        snapshot: &FrozenCounterfactualCandidateGroups,
    ) -> Result<CounterfactualCandidateGroupsPaths, CounterfactualCandidateGroupsError> {
        validate_counterfactual_candidate_groups(snapshot)?;
        fs::create_dir_all(directory)?;
        let payload_name = format!("{}.counterfactual.bin", snapshot.dataset_id);
        let manifest_name = format!("{}.counterfactual.manifest.json", snapshot.dataset_id);
        let payload = directory.join(&payload_name);
        let manifest_path = directory.join(manifest_name);
        let payload_bytes = serde_json::to_vec(snapshot)?;
        write_new(&payload, &payload_bytes)?;

        let manifest = CounterfactualCandidateGroupsManifest {
            schema_version: COUNTERFACTUAL_CANDIDATE_GROUPS_SCHEMA.into(),
            dataset_id: snapshot.dataset_id.clone(),
            source_trajectory_id: snapshot.source_trajectory_id.clone(),
            binary_version: COUNTERFACTUAL_CANDIDATE_GROUPS_BINARY_VERSION,
            payload_file: PathBuf::from(payload_name),
            payload_bytes: payload_bytes.len() as u64,
            payload_blake3: digest(&payload_bytes),
            group_count: snapshot.groups.len() as u64,
            candidate_count: snapshot.candidates.len() as u64,
            certificate: snapshot.certificate.clone(),
        };
        let manifest_bytes = serde_json::to_vec(&manifest)?;
        if let Err(error) = write_new(&manifest_path, &manifest_bytes) {
            let _ = fs::remove_file(&payload);
            return Err(error);
        }
        sync_directory(directory)?;
        Ok(CounterfactualCandidateGroupsPaths {
            manifest: manifest_path,
            payload,
        })
    }
}

pub struct CounterfactualCandidateGroupsMapped {
    manifest: CounterfactualCandidateGroupsManifest,
    payload: Mmap,
}

impl CounterfactualCandidateGroupsMapped {
    pub fn open(manifest_path: &Path) -> Result<Self, CounterfactualCandidateGroupsError> {
        let manifest_bytes = fs::read(manifest_path)?;
        let manifest: CounterfactualCandidateGroupsManifest =
            serde_json::from_slice(&manifest_bytes)?;
        validate_manifest(&manifest)?;
        let directory =
            manifest_path
                .parent()
                .ok_or(CounterfactualCandidateGroupsError::CorruptArtifact(
                    "manifest parent",
                ))?;
        let payload_path = directory.join(&manifest.payload_file);
        if manifest.payload_file.components().count() != 1 {
            return Err(CounterfactualCandidateGroupsError::CorruptArtifact(
                "payload path",
            ));
        }
        let file = File::open(payload_path)?;
        let payload = unsafe { MmapOptions::new().map(&file)? };
        if payload.len() as u64 != manifest.payload_bytes
            || digest(&payload) != manifest.payload_blake3
        {
            return Err(CounterfactualCandidateGroupsError::CorruptArtifact(
                "payload digest",
            ));
        }
        let snapshot: FrozenCounterfactualCandidateGroups = serde_json::from_slice(&payload)?;
        validate_counterfactual_candidate_groups(&snapshot)?;
        if snapshot.dataset_id != manifest.dataset_id
            || snapshot.source_trajectory_id != manifest.source_trajectory_id
            || snapshot.groups.len() as u64 != manifest.group_count
            || snapshot.candidates.len() as u64 != manifest.candidate_count
            || snapshot.certificate != manifest.certificate
        {
            return Err(CounterfactualCandidateGroupsError::CorruptArtifact(
                "manifest binding",
            ));
        }
        Ok(Self { manifest, payload })
    }

    pub const fn manifest(&self) -> &CounterfactualCandidateGroupsManifest {
        &self.manifest
    }

    pub fn snapshot(
        &self,
    ) -> Result<FrozenCounterfactualCandidateGroups, CounterfactualCandidateGroupsError> {
        let snapshot = serde_json::from_slice(&self.payload)?;
        validate_counterfactual_candidate_groups(&snapshot)?;
        Ok(snapshot)
    }
}

fn validate_manifest(
    manifest: &CounterfactualCandidateGroupsManifest,
) -> Result<(), CounterfactualCandidateGroupsError> {
    if manifest.schema_version != COUNTERFACTUAL_CANDIDATE_GROUPS_SCHEMA
        || manifest.binary_version != COUNTERFACTUAL_CANDIDATE_GROUPS_BINARY_VERSION
        || !is_blake3(&manifest.dataset_id)
        || !is_blake3(&manifest.source_trajectory_id)
        || !is_blake3(&manifest.payload_blake3)
        || manifest.payload_bytes == 0
        || manifest.group_count == 0
        || manifest.candidate_count
            != manifest.group_count * crate::CounterfactualCandidateRole::ALL.len() as u64
        || !manifest.certificate.passes()
    {
        return Err(CounterfactualCandidateGroupsError::CorruptArtifact(
            "manifest contract",
        ));
    }
    Ok(())
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), CounterfactualCandidateGroupsError> {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                CounterfactualCandidateGroupsError::ArtifactExists(path.to_path_buf())
            } else {
                CounterfactualCandidateGroupsError::Io(error)
            }
        })?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

#[cfg(not(windows))]
fn sync_directory(directory: &Path) -> Result<(), CounterfactualCandidateGroupsError> {
    File::open(directory)?.sync_all()?;
    Ok(())
}

#[cfg(windows)]
fn sync_directory(_directory: &Path) -> Result<(), CounterfactualCandidateGroupsError> {
    // Windows denies opening a directory through std::fs::File. The payload and
    // manifest files are individually flushed before this boundary.
    Ok(())
}

fn digest(bytes: &[u8]) -> CompactString {
    format_compact!("b3-{}", blake3::hash(bytes).to_hex())
}

fn is_blake3(value: &str) -> bool {
    value.len() == 67
        && value.starts_with("b3-")
        && value[3..].bytes().all(|byte| byte.is_ascii_hexdigit())
}
