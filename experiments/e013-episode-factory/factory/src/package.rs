use std::{
    collections::BTreeSet,
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};

use memchr::memmem;
use serde::{de::DeserializeOwned, Serialize};

use crate::{
    audit::audit_episode_draft,
    canonical::canonical_json,
    error::io_error,
    hash::{hash_bytes, hash_file, root_hash},
    order::candidate_order,
    paths::{validate_identifier, validate_relative_path},
    replay::{replay_candidates, CandidateReplay, PhaseStatus},
    ArtifactRecord, CandidateProvenanceRecord, CandidateRecord, EpisodeDraft, EpisodeManifest,
    EpisodeSeal, FactoryError, GenerationContext, PrivateConstructionReceipt, RepoSnapshot,
    SealEntry, ARTIFACT_SCHEMA_VERSION, PROTOCOL_VERSION,
};

#[derive(Clone, Debug)]
pub struct BuildEpisodeOptions {
    pub output_dir: PathBuf,
    pub protocol_sha256: String,
    pub protocol_lock_sha256: String,
    pub construction_contract_sha256: String,
    pub scratch_root: PathBuf,
    pub cargo_target_dir: PathBuf,
    pub compile_timeout_secs: u64,
    pub validation_timeout_secs: u64,
}

#[derive(Clone, Debug)]
pub struct EpisodeBuildResult {
    pub manifest: EpisodeManifest,
    pub private_receipt: PrivateConstructionReceipt,
    pub seal: EpisodeSeal,
}

#[derive(Serialize)]
struct FailedConstruction<'a> {
    schema_version: &'static str,
    protocol_version: &'static str,
    protocol_sha256: &'a str,
    protocol_lock_sha256: &'a str,
    construction_contract_sha256: &'a str,
    episode_id: &'a str,
    bank_id: &'a str,
    family_id: &'a str,
    task_id: &'a str,
    cell_id: &'a str,
    cell_task_ordinal: u16,
    cell_task_count: u16,
    cell_empty_ordinal: u16,
    cell_seed: u64,
    generation_seed: u64,
    candidate_order_seed: u64,
    matched_pair: &'a Option<crate::MatchedPairContext>,
    repo: &'a RepoSnapshot,
    failure: &'a str,
    replay: &'a [CandidateReplay],
    draft: &'a EpisodeDraft,
}

/// Validates one draft, replays all patches from independent checkouts, writes the two-surface
/// episode package, and seals every file. A package seal is not a bank-readiness claim.
pub fn build_episode(
    context: &GenerationContext,
    draft: &EpisodeDraft,
    options: &BuildEpisodeOptions,
) -> Result<EpisodeBuildResult, FactoryError> {
    audit_episode_draft(context, draft)?;
    validate_digest(&options.protocol_sha256, "protocol SHA-256")?;
    validate_digest(&options.protocol_lock_sha256, "protocol lock SHA-256")?;
    validate_digest(
        &options.construction_contract_sha256,
        "construction contract SHA-256",
    )?;
    validate_execution_dirs(context, options)?;
    if options.compile_timeout_secs == 0 || options.validation_timeout_secs == 0 {
        return Err(FactoryError::Invalid("replay command timeouts must be positive".into()));
    }
    if context.is_empty_valid_task() && draft.candidates.len() != 4 {
        return Err(FactoryError::Invalid(
            "empty-valid task must offer exactly four candidates".into(),
        ));
    }
    if options.output_dir.exists() {
        return Err(FactoryError::Invalid(format!(
            "episode output already exists: {}",
            options.output_dir.display()
        )));
    }
    if context.family_id.is_empty() {
        return Err(FactoryError::Invalid("empty family id".into()));
    }
    crate::materialize::verify_snapshot(&context.repo_snapshot_root, &context.repo)?;

    let replay = replay_candidates(context, draft, options)?;
    let required_failure = replay.iter().find(|row| {
        row.source_firewall.status != PhaseStatus::Passed
            || row.apply.status != PhaseStatus::Passed
            || row.compile.status != PhaseStatus::Passed
    });
    if let Some(failed) = required_failure {
        let failure = format!(
            "candidate {} failed a required source-firewall/apply/compile phase",
            failed.candidate_id
        );
        preserve_failed_attempt(context, draft, options, &replay, &failure)?;
        return Err(FactoryError::Invalid(format!(
            "{failure}; exact draft and phase receipts preserved under {}",
            options.output_dir.display()
        )));
    }
    let valid_candidate_ids = replay
        .iter()
        .filter(|row| row.valid)
        .map(|row| row.candidate_id.clone())
        .collect::<Vec<_>>();
    if context.is_empty_valid_task() && !valid_candidate_ids.is_empty() {
        let failure = "assigned empty-valid task has a hidden-valid candidate";
        preserve_failed_attempt(context, draft, options, &replay, failure)?;
        return Err(FactoryError::Invalid(format!(
            "{failure}; exact draft and phase receipts preserved under {}",
            options.output_dir.display()
        )));
    }
    if !context.is_empty_valid_task() && valid_candidate_ids.is_empty() {
        let failure = "non-empty task has no hidden-valid candidate";
        preserve_failed_attempt(context, draft, options, &replay, failure)?;
        return Err(FactoryError::Invalid(format!(
            "{failure}; exact draft and phase receipts preserved under {}",
            options.output_dir.display()
        )));
    }
    let mut candidates = draft.candidates.iter().collect::<Vec<_>>();
    candidates.sort_unstable_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let candidate_ids = candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<Vec<_>>();
    let order = candidate_order(context.candidate_order_seed, &candidate_ids);
    let candidate_records = candidates
        .iter()
        .map(|candidate| CandidateRecord {
            candidate_id: candidate.candidate_id.clone(),
            patch_path: format!("candidates/{}.patch", candidate.candidate_id),
            patch_sha256: hash_bytes(&candidate.unified_diff),
        })
        .collect::<Vec<_>>();
    let fixture_records = draft
        .visible_fixtures
        .iter()
        .map(|asset| asset_record(&format!("visible/fixtures/{}", asset.path), &asset.bytes))
        .collect::<Vec<_>>();
    let evidence_records = draft
        .visible_evidence
        .iter()
        .map(|asset| asset_record(&format!("visible/evidence/{}", asset.path), &asset.bytes))
        .collect::<Vec<_>>();
    let manifest = EpisodeManifest {
        schema_version: ARTIFACT_SCHEMA_VERSION.into(),
        protocol_version: PROTOCOL_VERSION.into(),
        protocol_sha256: options.protocol_sha256.clone(),
        protocol_lock_sha256: options.protocol_lock_sha256.clone(),
        episode_id: context.episode_id.clone(),
        task_id: context.task_id.clone(),
        family_id: context.family_id.clone(),
        repo: context.repo.clone(),
        task: draft.task.clone(),
        candidates: candidate_records,
        candidate_order: order,
        visible_fixtures: fixture_records,
        visible_evidence: evidence_records,
        provenance: draft.provenance.clone(),
    };
    let hidden_record = asset_record(
        &format!("private/adjudicator/{}", draft.hidden_adjudicator.path),
        &draft.hidden_adjudicator.bytes,
    );
    let mut candidate_provenance = draft
        .candidates
        .iter()
        .map(|candidate| CandidateProvenanceRecord {
            candidate_id: candidate.candidate_id.clone(),
            provenance: candidate.provenance.clone(),
        })
        .collect::<Vec<_>>();
    candidate_provenance.sort_unstable_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let private_receipt = PrivateConstructionReceipt {
        schema_version: ARTIFACT_SCHEMA_VERSION.into(),
        protocol_version: PROTOCOL_VERSION.into(),
        episode_id: context.episode_id.clone(),
        bank_id: context.bank_id.clone(),
        family_id: context.family_id.clone(),
        cell_id: context.cell_id.clone(),
        cell_task_ordinal: context.cell_task_ordinal,
        cell_task_count: context.cell_task_count,
        cell_empty_ordinal: context.cell_empty_ordinal,
        cell_seed: context.cell_seed,
        generation_seed: context.generation_seed,
        candidate_order_seed: context.candidate_order_seed,
        matched_pair: context.matched_pair.clone(),
        scratch_root: options.scratch_root.to_string_lossy().into_owned(),
        cargo_target_dir: options.cargo_target_dir.to_string_lossy().into_owned(),
        compile_timeout_secs: options.compile_timeout_secs,
        validation_timeout_secs: options.validation_timeout_secs,
        hidden_adjudicator: hidden_record,
        leakage_canaries: draft.hidden_adjudicator.leakage_canaries.clone(),
        valid_candidate_ids,
        candidate_provenance,
        replay,
    };

    let public_manifest_bytes = canonical_json(&manifest)?;
    let candidate_order_bytes = canonical_json(&manifest.candidate_order)?;
    audit_public_projection(
        &manifest,
        draft,
        &public_manifest_bytes,
        &candidate_order_bytes,
    )?;
    fs::create_dir_all(&options.output_dir)
        .map_err(|error| io_error(&options.output_dir, error))?;
    write_new(
        &options.output_dir.join("episode.json"),
        &public_manifest_bytes,
    )?;
    write_new(
        &options.output_dir.join("candidate_order.json"),
        &candidate_order_bytes,
    )?;
    for candidate in &draft.candidates {
        write_relative(
            &options.output_dir,
            &format!("candidates/{}.patch", candidate.candidate_id),
            &candidate.unified_diff,
        )?;
    }
    for asset in &draft.visible_fixtures {
        write_relative(
            &options.output_dir,
            &format!("visible/fixtures/{}", asset.path),
            &asset.bytes,
        )?;
    }
    for asset in &draft.visible_evidence {
        write_relative(
            &options.output_dir,
            &format!("visible/evidence/{}", asset.path),
            &asset.bytes,
        )?;
    }
    write_relative(
        &options.output_dir,
        &hidden_record.path,
        &draft.hidden_adjudicator.bytes,
    )?;
    let private_bytes = canonical_json(&private_receipt)?;
    write_new(
        &options.output_dir.join("private/construction.json"),
        &private_bytes,
    )?;

    let mut entries = collect_seal_entries(&options.output_dir)?;
    entries.sort_unstable_by(|left, right| left.path.cmp(&right.path));
    let seal = EpisodeSeal {
        schema_version: ARTIFACT_SCHEMA_VERSION.into(),
        seal_id: format!(
            "E013_EPISODE_{}_SEAL_V01",
            context.episode_id.to_ascii_uppercase()
        ),
        status: "EPISODE_ARTIFACT_SEALED_PENDING_BANK_AUDIT".into(),
        protocol_version: PROTOCOL_VERSION.into(),
        protocol_sha256: options.protocol_sha256.clone(),
        protocol_lock_sha256: options.protocol_lock_sha256.clone(),
        construction_contract_sha256: options.construction_contract_sha256.clone(),
        root_sha256: root_hash(&entries),
        entry_count: entries.len(),
        entries,
    };
    write_new(
        &options.output_dir.join("seal.json"),
        &canonical_json(&seal)?,
    )?;
    Ok(EpisodeBuildResult {
        manifest,
        private_receipt,
        seal,
    })
}

/// Rehashes every sealed byte, checks the root and public/private split, and rejects extra files.
pub fn verify_episode(directory: &Path) -> Result<EpisodeBuildResult, FactoryError> {
    let manifest: EpisodeManifest = read_canonical(&directory.join("episode.json"))?;
    let order: Vec<String> = read_canonical(&directory.join("candidate_order.json"))?;
    let private_receipt: PrivateConstructionReceipt =
        read_canonical(&directory.join("private/construction.json"))?;
    let seal: EpisodeSeal = read_canonical(&directory.join("seal.json"))?;
    if manifest.schema_version != ARTIFACT_SCHEMA_VERSION
        || private_receipt.schema_version != ARTIFACT_SCHEMA_VERSION
        || seal.schema_version != ARTIFACT_SCHEMA_VERSION
        || manifest.protocol_version != PROTOCOL_VERSION
        || private_receipt.protocol_version != PROTOCOL_VERSION
        || seal.protocol_version != PROTOCOL_VERSION
    {
        return Err(FactoryError::Seal("protocol version mismatch".into()));
    }
    if order != manifest.candidate_order || private_receipt.episode_id != manifest.episode_id {
        return Err(FactoryError::Seal(
            "manifest, order, and private receipt identities disagree".into(),
        ));
    }
    validate_digest(&seal.protocol_sha256, "sealed protocol SHA-256")?;
    validate_digest(&seal.protocol_lock_sha256, "sealed protocol lock SHA-256")?;
    validate_digest(
        &seal.construction_contract_sha256,
        "sealed construction contract SHA-256",
    )?;
    if manifest.protocol_sha256 != seal.protocol_sha256
        || manifest.protocol_lock_sha256 != seal.protocol_lock_sha256
    {
        return Err(FactoryError::Seal(
            "manifest and seal protocol identities disagree".into(),
        ));
    }
    let candidate_ids = manifest
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_id.as_str())
        .collect::<BTreeSet<_>>();
    if candidate_ids.len() != manifest.candidates.len()
        || order.iter().map(String::as_str).collect::<BTreeSet<_>>() != candidate_ids
    {
        return Err(FactoryError::Seal(
            "candidate order is not an exact candidate permutation".into(),
        ));
    }
    let valid_ids = private_receipt
        .valid_candidate_ids
        .iter()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let replay_valid_ids = private_receipt
        .replay
        .iter()
        .filter(|row| row.valid)
        .map(|row| row.candidate_id.as_str())
        .collect::<BTreeSet<_>>();
    if valid_ids != replay_valid_ids || !valid_ids.is_subset(&candidate_ids) {
        return Err(FactoryError::Seal(
            "private valid set disagrees with replay receipts".into(),
        ));
    }
    if private_receipt.cell_task_count == 0
        || private_receipt.cell_task_ordinal >= private_receipt.cell_task_count
        || private_receipt.cell_empty_ordinal >= private_receipt.cell_task_count
    {
        return Err(FactoryError::Seal(
            "private cell assignment out of range".into(),
        ));
    }
    if let Some(canary) =
        find_public_leak(directory, &seal.entries, &private_receipt.leakage_canaries)?
    {
        return Err(FactoryError::Seal(format!(
            "public leakage canary found: {canary:?}"
        )));
    }

    let mut entry_paths = BTreeSet::new();
    for entry in &seal.entries {
        validate_relative_path(&entry.path)
            .map_err(|error| FactoryError::Seal(error.to_string()))?;
        if entry.path == "seal.json" || !entry_paths.insert(entry.path.as_str()) {
            return Err(FactoryError::Seal(format!(
                "duplicate or recursive seal entry: {}",
                entry.path
            )));
        }
        let full_path = directory.join(&entry.path);
        let metadata =
            fs::symlink_metadata(&full_path).map_err(|error| io_error(&full_path, error))?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(FactoryError::Seal(format!(
                "sealed entry is not a regular file: {}",
                entry.path
            )));
        }
        let actual = hash_file(&full_path)?;
        if actual.byte_len != entry.byte_len || actual.sha256 != entry.sha256 {
            return Err(FactoryError::Seal(format!(
                "sealed file changed: {}",
                entry.path
            )));
        }
    }
    if seal.entry_count != seal.entries.len() || root_hash(&seal.entries) != seal.root_sha256 {
        return Err(FactoryError::Seal(
            "seal count or root hash mismatch".into(),
        ));
    }
    let mut actual_paths = Vec::new();
    walk_files(directory, directory, &mut actual_paths)?;
    actual_paths.sort_unstable();
    let mut expected_paths = entry_paths
        .into_iter()
        .map(str::to_owned)
        .collect::<Vec<_>>();
    expected_paths.push("seal.json".into());
    expected_paths.sort_unstable();
    if actual_paths != expected_paths {
        return Err(FactoryError::Seal(
            "package contains unlisted or missing files".into(),
        ));
    }
    Ok(EpisodeBuildResult {
        manifest,
        private_receipt,
        seal,
    })
}

fn audit_public_projection(
    manifest: &EpisodeManifest,
    draft: &EpisodeDraft,
    manifest_bytes: &[u8],
    order_bytes: &[u8],
) -> Result<(), FactoryError> {
    let mut public_bytes = vec![manifest_bytes, order_bytes, draft.task.text.as_bytes()];
    public_bytes.extend(
        draft
            .candidates
            .iter()
            .map(|candidate| candidate.unified_diff.as_slice()),
    );
    public_bytes.extend(
        draft
            .visible_fixtures
            .iter()
            .map(|asset| asset.bytes.as_slice()),
    );
    public_bytes.extend(
        draft
            .visible_evidence
            .iter()
            .map(|asset| asset.bytes.as_slice()),
    );
    for canary in &draft.hidden_adjudicator.leakage_canaries {
        if public_bytes
            .iter()
            .any(|bytes| memmem::find(bytes, canary.as_bytes()).is_some())
        {
            return Err(FactoryError::Invalid(format!(
                "hidden leakage canary appears in public projection: {canary:?}"
            )));
        }
    }
    if manifest
        .candidates
        .iter()
        .any(|candidate| candidate.patch_path.contains("private/"))
    {
        return Err(FactoryError::Invalid(
            "public candidate path enters private root".into(),
        ));
    }
    Ok(())
}

fn asset_record(path: &str, bytes: &[u8]) -> ArtifactRecord {
    ArtifactRecord {
        path: path.to_owned(),
        byte_len: bytes.len() as u64,
        sha256: hash_bytes(bytes),
    }
}

fn collect_seal_entries(root: &Path) -> Result<Vec<SealEntry>, FactoryError> {
    let mut paths = Vec::new();
    walk_files(root, root, &mut paths)?;
    paths.sort_unstable();
    let mut entries = Vec::with_capacity(paths.len());
    for relative in paths {
        if relative == "seal.json" {
            continue;
        }
        let path = root.join(&relative);
        let digest = hash_file(&path)?;
        entries.push(SealEntry {
            artifact_id: relative.clone(),
            path: relative,
            byte_len: digest.byte_len,
            sha256: digest.sha256,
        });
    }
    Ok(entries)
}

fn find_public_leak(
    root: &Path,
    entries: &[SealEntry],
    canaries: &[String],
) -> Result<Option<String>, FactoryError> {
    for entry in entries {
        if !(entry.path == "episode.json"
            || entry.path == "candidate_order.json"
            || entry.path.starts_with("candidates/")
            || entry.path.starts_with("visible/"))
        {
            continue;
        }
        let path = root.join(&entry.path);
        let bytes = fs::read(&path).map_err(|error| io_error(&path, error))?;
        if let Some(canary) = canaries
            .iter()
            .find(|canary| memmem::find(&bytes, canary.as_bytes()).is_some())
        {
            return Ok(Some(canary.clone()));
        }
    }
    Ok(None)
}

fn write_relative(root: &Path, relative: &str, bytes: &[u8]) -> Result<(), FactoryError> {
    validate_relative_path(relative)?;
    let path = root.join(relative);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| io_error(parent, error))?;
    }
    write_new(&path, bytes)
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), FactoryError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| io_error(parent, error))?;
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| io_error(path, error))?;
    file.write_all(bytes)
        .map_err(|error| io_error(path, error))?;
    file.sync_all().map_err(|error| io_error(path, error))
}

fn preserve_failed_attempt(
    context: &GenerationContext,
    draft: &EpisodeDraft,
    options: &BuildEpisodeOptions,
    replay: &[CandidateReplay],
    failure: &str,
) -> Result<(), FactoryError> {
    fs::create_dir_all(&options.output_dir)
        .map_err(|error| io_error(&options.output_dir, error))?;
    let attempt = FailedConstruction {
        schema_version: ARTIFACT_SCHEMA_VERSION,
        protocol_version: PROTOCOL_VERSION,
        protocol_sha256: &options.protocol_sha256,
        protocol_lock_sha256: &options.protocol_lock_sha256,
        construction_contract_sha256: &options.construction_contract_sha256,
        episode_id: &context.episode_id,
        bank_id: &context.bank_id,
        family_id: &context.family_id,
        task_id: &context.task_id,
        cell_id: &context.cell_id,
        cell_task_ordinal: context.cell_task_ordinal,
        cell_task_count: context.cell_task_count,
        cell_empty_ordinal: context.cell_empty_ordinal,
        cell_seed: context.cell_seed,
        generation_seed: context.generation_seed,
        candidate_order_seed: context.candidate_order_seed,
        matched_pair: &context.matched_pair,
        scratch_root: options.scratch_root.to_string_lossy().into_owned(),
        cargo_target_dir: options.cargo_target_dir.to_string_lossy().into_owned(),
        compile_timeout_secs: options.compile_timeout_secs,
        validation_timeout_secs: options.validation_timeout_secs,
        repo: &context.repo,
        failure,
        replay,
        draft,
    };
    let bytes = canonical_json(&attempt)?;
    write_new(
        &options.output_dir.join("private/failed-construction.json"),
        &bytes,
    )
}

fn read_canonical<T: DeserializeOwned + serde::Serialize>(path: &Path) -> Result<T, FactoryError> {
    let bytes = fs::read(path).map_err(|error| io_error(path, error))?;
    let value: T = serde_json::from_slice(&bytes)?;
    if canonical_json(&value)? != bytes {
        return Err(FactoryError::Seal(format!(
            "noncanonical JSON: {}",
            path.display()
        )));
    }
    Ok(value)
}

fn walk_files(root: &Path, current: &Path, output: &mut Vec<String>) -> Result<(), FactoryError> {
    let mut entries = fs::read_dir(current)
        .map_err(|error| io_error(current, error))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| io_error(current, error))?;
    entries.sort_unstable_by_key(|entry| entry.file_name());
    for entry in entries {
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path).map_err(|error| io_error(&path, error))?;
        if metadata.file_type().is_symlink() {
            return Err(FactoryError::Seal(format!(
                "package symlink rejected: {}",
                path.display()
            )));
        }
        if metadata.is_dir() {
            walk_files(root, &path, output)?;
        } else if metadata.is_file() {
            let relative = path
                .strip_prefix(root)
                .map_err(|_| FactoryError::Seal("package entry escaped root".into()))?
                .to_string_lossy()
                .replace('\\', "/");
            output.push(relative);
        } else {
            return Err(FactoryError::Seal(format!(
                "unsupported package entry: {}",
                path.display()
            )));
        }
    }
    Ok(())
}

fn validate_digest(digest: &str, label: &str) -> Result<(), FactoryError> {
    if digest.len() != 64 || !digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(FactoryError::Invalid(format!("malformed {label}")));
    }
    Ok(())
}

fn validate_execution_dirs(
    context: &GenerationContext,
    options: &BuildEpisodeOptions,
) -> Result<(), FactoryError> {
    for (label, path) in [
        ("scratch root", &options.scratch_root),
        ("cargo target directory", &options.cargo_target_dir),
    ] {
        if !path.is_absolute() {
            return Err(FactoryError::Invalid(format!("{label} must be an absolute path")));
        }
        let metadata = fs::metadata(path).map_err(|error| io_error(path, error))?;
        if !metadata.is_dir() {
            return Err(FactoryError::Invalid(format!("{label} is not a directory: {}", path.display())));
        }
        let canonical = fs::canonicalize(path).map_err(|error| io_error(path, error))?;
        let snapshot = fs::canonicalize(&context.repo_snapshot_root)
            .map_err(|error| io_error(&context.repo_snapshot_root, error))?;
        let output_parent = options
            .output_dir
            .parent()
            .ok_or_else(|| FactoryError::Invalid("episode output has no parent".into()))?;
        fs::create_dir_all(output_parent).map_err(|error| io_error(output_parent, error))?;
        let output_parent = fs::canonicalize(output_parent)
            .map_err(|error| io_error(output_parent, error))?;
        if canonical.starts_with(&snapshot) || canonical.starts_with(&output_parent) {
            return Err(FactoryError::Invalid(format!(
                "{label} overlaps frozen input or bank output: {}",
                path.display()
            )));
        }
    }
    Ok(())
}

#[allow(dead_code)]
fn _identity_types(_: &RepoSnapshot, _: &CandidateReplay, _: &PhaseStatus) {}

#[allow(dead_code)]
fn _identifier_check(value: &str) -> Result<(), FactoryError> {
    validate_identifier(value, "episode field")
}
