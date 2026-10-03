use std::collections::BTreeSet;
use std::hash::Hash;

use hashbrown::HashSet;
use memchr::memmem;

use crate::{
    hash::hash_bytes,
    paths::{validate_identifier, validate_relative_path},
    CandidatePatch, EpisodeDraft, EpisodeManifest, FactoryError, GenerationContext,
    PrivateConstructionReceipt,
};

#[derive(Clone, Debug)]
pub struct DraftAudit {
    pub candidate_count: usize,
    pub visible_fixture_count: usize,
    pub visible_evidence_count: usize,
    pub public_payload_sha256: String,
}

#[derive(Clone, Debug, Default)]
pub struct BankAudit {
    pub d_episode_count: usize,
    pub c_episode_count: usize,
    pub shared_repo_ids: usize,
    pub shared_family_ids: usize,
    pub shared_task_ids: usize,
    pub shared_episode_ids: usize,
    pub shared_candidate_patch_hashes: usize,
    pub shared_visible_file_hashes: usize,
    pub shared_hidden_file_hashes: usize,
    pub cross_surface_hashes: usize,
    pub shared_seeds: usize,
}

const FIREWALL_PATTERNS: &[&[u8]] = &[
    b"E013_HIDDEN_ADJUDICATOR",
    b"E013_HIDDEN_ROOT",
    b"E013_VISIBLE_ROOT",
    b"std::env",
    b"env::var",
    b"env::var_os",
    b"getenv(",
    b"std::fs::",
    b"fs::read",
    b"fs::write",
    b"File::open",
    b"OpenOptions",
    b"read_to_string",
    b"std::io::stdin",
    b"std::process::Command::new",
];

pub fn audit_episode_draft(
    context: &GenerationContext,
    draft: &EpisodeDraft,
) -> Result<DraftAudit, FactoryError> {
    for (value, label) in [
        (&context.bank_id, "bank id"),
        (&context.family_id, "family id"),
        (&context.episode_id, "episode id"),
        (&context.task_id, "task id"),
        (&context.cell_id, "cell id"),
        (&context.repo.repo_id, "repository id"),
    ] {
        crate::paths::validate_identifier(value, label)?;
    }
    if context.family_id != context.family_id.trim() || context.family_id.is_empty() {
        return Err(FactoryError::Invalid("family id is empty or padded".into()));
    }
    if context.cell_task_count == 0
        || context.cell_task_ordinal >= context.cell_task_count
        || context.cell_empty_ordinal >= context.cell_task_count
    {
        return Err(FactoryError::Invalid(
            "cell ordinal or empty-slot assignment is out of range".into(),
        ));
    }
    if let Some(pair) = &context.matched_pair {
        validate_identifier(&pair.pair_id, "matched-pair id")?;
        if pair.member_index > 1 || pair.candidate_order_seed != context.candidate_order_seed {
            return Err(FactoryError::Invalid(
                "malformed private matched-pair assignment".into(),
            ));
        }
    }
    if context.repo.commit_sha.len() != 40 || context.repo.tree_sha.len() != 40 {
        return Err(FactoryError::Invalid(
            "repo commit/tree ids must be 40-character git object IDs".into(),
        ));
    }
    if draft.task.text.trim().is_empty() {
        return Err(FactoryError::Invalid("task text is empty".into()));
    }
    if draft.candidates.len() < 2 {
        return Err(FactoryError::Invalid(
            "episode must offer at least two candidate patches".into(),
        ));
    }
    validate_provenance(&draft.provenance)?;
    validate_command(&draft.validation.compile, "compile")?;
    validate_command(&draft.validation.visible, "visible")?;
    validate_command(&draft.validation.hidden, "hidden")?;

    let mut candidate_ids = HashSet::with_capacity(draft.candidates.len());
    for candidate in &draft.candidates {
        crate::paths::validate_identifier(&candidate.candidate_id, "candidate id")?;
        let lower = candidate.candidate_id.to_ascii_lowercase();
        if [
            "valid", "invalid", "correct", "gold", "answer", "oracle", "empty",
        ]
        .iter()
        .any(|token| lower.contains(token))
        {
            return Err(FactoryError::Invalid(format!(
                "candidate id exposes semantic status: {}",
                candidate.candidate_id
            )));
        }
        if !candidate_ids.insert(candidate.candidate_id.as_str()) {
            return Err(FactoryError::Invalid(format!(
                "duplicate candidate id: {}",
                candidate.candidate_id
            )));
        }
        if candidate.unified_diff.is_empty() {
            return Err(FactoryError::Invalid(format!(
                "empty candidate patch: {}",
                candidate.candidate_id
            )));
        }
        std::str::from_utf8(&candidate.unified_diff).map_err(|_| {
            FactoryError::Invalid(format!(
                "candidate patch must be UTF-8 unified diff: {}",
                candidate.candidate_id
            ))
        })?;
        validate_provenance(&candidate.provenance)?;
    }

    let mut visible_paths =
        HashSet::with_capacity(draft.visible_fixtures.len() + draft.visible_evidence.len());
    for asset in draft.visible_fixtures.iter().chain(&draft.visible_evidence) {
        validate_relative_path(&asset.path)?;
        if asset.media_type.trim().is_empty() {
            return Err(FactoryError::Invalid(format!(
                "empty asset media type: {}",
                asset.path
            )));
        }
        if !visible_paths.insert(asset.path.as_str()) {
            return Err(FactoryError::Invalid(format!(
                "duplicate visible asset path: {}",
                asset.path
            )));
        }
    }
    validate_relative_path(&draft.hidden_adjudicator.path)?;
    if draft.hidden_adjudicator.bytes.is_empty() {
        return Err(FactoryError::Invalid("hidden adjudicator is empty".into()));
    }
    for canary in &draft.hidden_adjudicator.leakage_canaries {
        if canary.len() < 6 {
            return Err(FactoryError::Invalid(
                "leakage canaries must be at least six bytes and content-specific".into(),
            ));
        }
    }
    let hidden_sha = hash_bytes(&draft.hidden_adjudicator.bytes);
    if draft
        .visible_fixtures
        .iter()
        .chain(&draft.visible_evidence)
        .any(|asset| hash_bytes(&asset.bytes) == hidden_sha)
    {
        return Err(FactoryError::Invalid(
            "visible and hidden fixture bytes must be hash-disjoint".into(),
        ));
    }
    let mut public_bytes: Vec<&[u8]> = Vec::with_capacity(
        1 + draft.candidates.len() + draft.visible_fixtures.len() + draft.visible_evidence.len(),
    );
    public_bytes.push(draft.task.text.as_bytes());
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
    public_bytes.extend(
        draft
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.as_bytes()),
    );
    for canary in &draft.hidden_adjudicator.leakage_canaries {
        if public_bytes
            .iter()
            .any(|bytes| memmem::find(bytes, canary.as_bytes()).is_some())
        {
            return Err(FactoryError::Invalid(format!(
                "hidden leakage canary appears in visible bytes: {canary:?}"
            )));
        }
    }

    let total_public_bytes = public_bytes.iter().map(|bytes| bytes.len()).sum::<usize>();
    let mut digest_input = Vec::with_capacity(total_public_bytes);
    for bytes in public_bytes {
        digest_input.extend_from_slice(bytes);
    }
    Ok(DraftAudit {
        candidate_count: draft.candidates.len(),
        visible_fixture_count: draft.visible_fixtures.len(),
        visible_evidence_count: draft.visible_evidence.len(),
        public_payload_sha256: hash_bytes(&digest_input),
    })
}

pub(crate) fn audit_candidate_patch_firewall(patch: &CandidatePatch) -> Result<(), FactoryError> {
    let mut old_path: Option<String> = None;
    let mut touched = 0usize;
    for line in patch.unified_diff.split(|byte| *byte == b'\n') {
        if let Some(raw_path) = line.strip_prefix(b"--- ") {
            if raw_path == b"/dev/null" {
                old_path = None;
                continue;
            }
            old_path = Some(normalize_diff_path(raw_path, b'a/')?);
            continue;
        }
        if let Some(raw_path) = line.strip_prefix(b"+++ ") {
            if raw_path == b"/dev/null" {
                return Err(FactoryError::Invalid(format!(
                    "candidate {} deletes a source path",
                    patch.candidate_id
                )));
            }
            let new_path = normalize_diff_path(raw_path, b'b/')?;
            if !allowed_rust_source_path(&new_path) {
                return Err(FactoryError::Invalid(format!(
                    "candidate {} touches disallowed path {new_path:?}",
                    patch.candidate_id
                )));
            }
            if let Some(old_path) = old_path.take() {
                if old_path != new_path || !allowed_rust_source_path(&old_path) {
                    return Err(FactoryError::Invalid(format!(
                        "candidate {} changes or renames disallowed path {old_path:?} -> {new_path:?}",
                        patch.candidate_id
                    )));
                }
            }
            touched += 1;
            continue;
        }
        if !line.starts_with(b"+") || line.starts_with(b"+++") {
            continue;
        }
        let addition = &line[1..];
        if let Some(pattern) = FIREWALL_PATTERNS
            .iter()
            .find(|pattern| memmem::find(addition, pattern).is_some())
        {
            return Err(FactoryError::Invalid(format!(
                "candidate {} added a reserved environment or filesystem access token ({})",
                patch.candidate_id,
                String::from_utf8_lossy(pattern)
            )));
        }
    }
    if touched == 0 || old_path.is_some() {
        return Err(FactoryError::Invalid(format!(
            "candidate {} has incomplete or absent Rust source path headers",
            patch.candidate_id
        )));
    }
    Ok(())
}

fn normalize_diff_path(raw: &[u8], prefix: &[u8]) -> Result<String, FactoryError> {
    let raw = raw
        .split(|byte| *byte == b'\t' || *byte == b' ')
        .next()
        .unwrap_or_default();
    let path = raw.strip_prefix(prefix).ok_or_else(|| {
        FactoryError::Invalid("unified diff path lacks the expected a/ or b/ prefix".into())
    })?;
    let path = std::str::from_utf8(path)
        .map_err(|_| FactoryError::Invalid("unified diff path is not UTF-8".into()))?;
    validate_relative_path(path)?;
    Ok(path.to_owned())
}

fn allowed_rust_source_path(path: &str) -> bool {
    path.starts_with("src/") && path.ends_with(".rs") && !path.starts_with("src/bin/")
}

pub fn audit_bank_disjointness(
    d_public: &[EpisodeManifest],
    d_private: &[PrivateConstructionReceipt],
    c_public: &[EpisodeManifest],
    c_private: &[PrivateConstructionReceipt],
) -> Result<BankAudit, FactoryError> {
    let d_repo = set(d_public.iter().map(|row| row.repo.repo_id.as_str()));
    let c_repo = set(c_public.iter().map(|row| row.repo.repo_id.as_str()));
    let d_family = set(d_public.iter().map(|row| row.family_id.as_str()));
    let c_family = set(c_public.iter().map(|row| row.family_id.as_str()));
    let d_task = set(d_public.iter().map(|row| row.task_id.as_str()));
    let c_task = set(c_public.iter().map(|row| row.task_id.as_str()));
    let d_episode = set(d_public.iter().map(|row| row.episode_id.as_str()));
    let c_episode = set(c_public.iter().map(|row| row.episode_id.as_str()));
    let d_patches = set(d_public.iter().flat_map(|row| {
        row.candidates
            .iter()
            .map(|candidate| candidate.patch_sha256.as_str())
    }));
    let c_patches = set(c_public.iter().flat_map(|row| {
        row.candidates
            .iter()
            .map(|candidate| candidate.patch_sha256.as_str())
    }));
    let d_visible = set(d_public.iter().flat_map(|row| {
        row.visible_fixtures
            .iter()
            .chain(&row.visible_evidence)
            .map(|asset| asset.sha256.as_str())
    }));
    let c_visible = set(c_public.iter().flat_map(|row| {
        row.visible_fixtures
            .iter()
            .chain(&row.visible_evidence)
            .map(|asset| asset.sha256.as_str())
    }));
    let d_hidden = set(d_private.iter().map(|row| row.hidden_adjudicator.sha256.as_str()));
    let c_hidden = set(c_private.iter().map(|row| row.hidden_adjudicator.sha256.as_str()));
    let shared_cross_surface = intersection_count(&d_visible, &c_hidden)
        + intersection_count(&c_visible, &d_hidden);
    let d_seeds = d_private
        .iter()
        .map(|row| row.generation_seed)
        .collect::<HashSet<_>>();
    let c_seeds = c_private
        .iter()
        .map(|row| row.generation_seed)
        .collect::<HashSet<_>>();
    let audit = BankAudit {
        d_episode_count: d_public.len(),
        c_episode_count: c_public.len(),
        shared_repo_ids: intersection_count(&d_repo, &c_repo),
        shared_family_ids: intersection_count(&d_family, &c_family),
        shared_task_ids: intersection_count(&d_task, &c_task),
        shared_episode_ids: intersection_count(&d_episode, &c_episode),
        shared_candidate_patch_hashes: intersection_count(&d_patches, &c_patches),
        shared_visible_file_hashes: intersection_count(&d_visible, &c_visible),
        shared_hidden_file_hashes: intersection_count(&d_hidden, &c_hidden),
        cross_surface_hashes: shared_cross_surface,
        shared_seeds: intersection_count(&d_seeds, &c_seeds),
    };
    if audit.shared_repo_ids
        + audit.shared_family_ids
        + audit.shared_task_ids
        + audit.shared_episode_ids
        + audit.shared_candidate_patch_hashes
        + audit.shared_visible_file_hashes
        + audit.shared_hidden_file_hashes
        + audit.cross_surface_hashes
        + audit.shared_seeds
        > 0
    {
        return Err(FactoryError::Disjointness(format!(
            "overlap summary: {audit:?}"
        )));
    }
    Ok(audit)
}

fn validate_command(spec: &crate::CommandSpec, phase: &str) -> Result<(), FactoryError> {
    if spec.program.trim().is_empty() {
        return Err(FactoryError::Invalid(format!(
            "empty {phase} command program"
        )));
    }
    for key in spec.env.keys() {
        if key.starts_with("E013_") {
            return Err(FactoryError::Invalid(format!(
                "command may not override reserved environment key {key}"
            )));
        }
    }
    Ok(())
}

fn validate_provenance(provenance: &crate::Provenance) -> Result<(), FactoryError> {
    if provenance.generator_name.trim().is_empty()
        || provenance.generator_version.trim().is_empty()
        || provenance.generator_source_sha256.len() != 64
        || !provenance
            .generator_source_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(FactoryError::Invalid(
            "incomplete or malformed generator provenance".into(),
        ));
    }
    let mut source_ids = BTreeSet::new();
    for source in &provenance.source_refs {
        if source.artifact_id.trim().is_empty()
            || source.role.trim().is_empty()
            || source.sha256.len() != 64
            || !source.sha256.bytes().all(|byte| byte.is_ascii_hexdigit())
            || !source_ids.insert(source.artifact_id.as_str())
        {
            return Err(FactoryError::Invalid(
                "invalid or duplicate provenance source reference".into(),
            ));
        }
    }
    Ok(())
}

fn set<'a>(items: impl Iterator<Item = &'a str>) -> HashSet<String> {
    items.map(str::to_owned).collect()
}

fn intersection_count<T: Eq + Hash>(left: &HashSet<T>, right: &HashSet<T>) -> usize {
    left.iter().filter(|value| right.contains(*value)).count()
}
