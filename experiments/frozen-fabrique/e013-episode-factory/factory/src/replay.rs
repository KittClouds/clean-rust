use std::{
    fs::{self, File},
    io::Read,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

use serde::{Deserialize, Serialize};
use tempfile::{Builder, TempDir};

use crate::{
    audit::audit_candidate_patch_firewall,
    error::io_error,
    hash::hash_bytes,
    materialize::{run_git, verify_snapshot},
    paths::validate_relative_path,
    Asset, BuildEpisodeOptions, CandidatePatch, CommandSpec, EpisodeDraft, FactoryError,
    GenerationContext, RepoSnapshot,
};

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PhaseStatus {
    Passed,
    Failed,
    Skipped,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PhaseOutcome {
    pub status: PhaseStatus,
    pub timed_out: bool,
    pub exit_code: Option<i32>,
    pub stdout_sha256: Option<String>,
    pub stderr_sha256: Option<String>,
    pub detail: Option<String>,
}

impl PhaseOutcome {
    fn passed() -> Self {
        Self {
            status: PhaseStatus::Passed,
            timed_out: false,
            exit_code: Some(0),
            stdout_sha256: None,
            stderr_sha256: None,
            detail: None,
        }
    }

    fn skipped(detail: &str) -> Self {
        Self {
            status: PhaseStatus::Skipped,
            timed_out: false,
            exit_code: None,
            stdout_sha256: None,
            stderr_sha256: None,
            detail: Some(detail.to_owned()),
        }
    }

    fn failed(detail: &str) -> Self {
        Self {
            status: PhaseStatus::Failed,
            timed_out: false,
            exit_code: None,
            stdout_sha256: None,
            stderr_sha256: None,
            detail: Some(detail.to_owned()),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CandidateReplay {
    pub candidate_id: String,
    pub patch_sha256: String,
    pub source_firewall: PhaseOutcome,
    pub apply: PhaseOutcome,
    pub patched_tree_sha: Option<String>,
    pub compile: PhaseOutcome,
    pub visible: PhaseOutcome,
    pub hidden: PhaseOutcome,
    pub valid: bool,
}

/// Applies each candidate to a separate clone at the same commit and records all four phases.
pub fn replay_candidates(
    context: &GenerationContext,
    draft: &EpisodeDraft,
    options: &BuildEpisodeOptions,
) -> Result<Vec<CandidateReplay>, FactoryError> {
    verify_snapshot(&context.repo_snapshot_root, &context.repo)?;
    let mut results = Vec::with_capacity(draft.candidates.len());
    for candidate in &draft.candidates {
        results.push(replay_one(
            &context.repo_snapshot_root,
            &context.repo,
            candidate,
            draft,
            options,
        )?);
    }
    Ok(results)
}

fn replay_one(
    source_root: &Path,
    snapshot: &RepoSnapshot,
    candidate: &CandidatePatch,
    draft: &EpisodeDraft,
    options: &BuildEpisodeOptions,
) -> Result<CandidateReplay, FactoryError> {
    let scratch = Builder::new()
        .prefix("e013-candidate-")
        .tempdir_in(&options.scratch_root)
        .map_err(|error| io_error(&options.scratch_root, error))?;
    let candidate_root = scratch.path().join("repo");
    clone_snapshot(source_root, &candidate_root, snapshot)?;
    let patch_path = scratch.path().join("candidate.patch");
    fs::write(&patch_path, &candidate.unified_diff)
        .map_err(|error| io_error(&patch_path, error))?;

    let firewall = match audit_candidate_patch_firewall(candidate) {
        Ok(()) => PhaseOutcome::passed(),
        Err(error) => PhaseOutcome::failed(&error.to_string()),
    };
    let apply = apply_patch(&candidate_root, &patch_path);
    let patch_sha256 = hash_bytes(&candidate.unified_diff);
    let mut result = CandidateReplay {
        candidate_id: candidate.candidate_id.clone(),
        patch_sha256,
        source_firewall: firewall,
        apply: apply.0,
        patched_tree_sha: apply.1,
        compile: PhaseOutcome::skipped("candidate patch did not apply"),
        visible: PhaseOutcome::skipped("candidate patch did not apply"),
        hidden: PhaseOutcome::skipped("candidate patch did not apply"),
        valid: false,
    };
    if result.apply.status != PhaseStatus::Passed {
        return Ok(result);
    }
    if result.source_firewall.status != PhaseStatus::Passed {
        result.compile = PhaseOutcome::skipped("source firewall rejected candidate");
        result.visible = PhaseOutcome::skipped("source firewall rejected candidate");
        result.hidden = PhaseOutcome::skipped("source firewall rejected candidate");
        return Ok(result);
    }

    let visible_root = scratch.path().join("visible");
    let hidden_root = scratch.path().join("hidden");
    write_visible_assets(&visible_root, draft)?;
    fs::create_dir_all(&hidden_root).map_err(|error| io_error(&hidden_root, error))?;
    let hidden_relative = Path::new(&draft.hidden_adjudicator.path);
    validate_relative_path(&draft.hidden_adjudicator.path)?;
    let hidden_path = hidden_root.join(hidden_relative);
    if let Some(parent) = hidden_path.parent() {
        fs::create_dir_all(parent).map_err(|error| io_error(parent, error))?;
    }
    fs::write(&hidden_path, &draft.hidden_adjudicator.bytes)
        .map_err(|error| io_error(&hidden_path, error))?;
    result.compile = run_phase(
        &draft.validation.compile,
        &candidate_root,
        &scratch,
        &options.cargo_target_dir,
        &candidate.candidate_id,
        None,
        options.compile_timeout_secs,
        "compile",
    );
    if result.compile.status != PhaseStatus::Passed {
        result.visible = PhaseOutcome::skipped("candidate failed compile phase");
        result.hidden = PhaseOutcome::skipped("candidate failed compile phase");
        return Ok(result);
    }
    result.visible = run_phase(
        &draft.validation.visible,
        &candidate_root,
        &scratch,
        &options.cargo_target_dir,
        &candidate.candidate_id,
        Some(("E013_VISIBLE_ROOT", &visible_root)),
        options.validation_timeout_secs,
        "visible",
    );
    result.hidden = run_phase(
        &draft.validation.hidden,
        &candidate_root,
        &scratch,
        &options.cargo_target_dir,
        &candidate.candidate_id,
        Some(("E013_HIDDEN_ADJUDICATOR", &hidden_path)),
        options.validation_timeout_secs,
        "hidden",
    );
    // Visible screening is evidence available to a future router, not the truth label.
    // The sealed valid-action set is determined only by hidden completion adjudication.
    result.valid = result.hidden.status == PhaseStatus::Passed;
    Ok(result)
}

fn clone_snapshot(
    source: &Path,
    destination: &Path,
    snapshot: &RepoSnapshot,
) -> Result<(), FactoryError> {
    let output = Command::new("git")
        .args(["clone", "--shared", "--no-checkout", "--no-tags", "--quiet"])
        .arg(source)
        .arg(destination)
        .output()
        .map_err(|source| FactoryError::CommandSetup {
            phase: "candidate clone".into(),
            source,
        })?;
    if !output.status.success() {
        return Err(FactoryError::Git {
            command: "git clone --shared --no-checkout".into(),
            stderr: String::from_utf8_lossy(&output.stderr).trim().to_owned(),
        });
    }
    run_git(
        destination,
        ["checkout", "--quiet", "--detach", &snapshot.commit_sha],
    )?;
    verify_snapshot(destination, snapshot)
}

fn apply_patch(root: &Path, patch_path: &Path) -> (PhaseOutcome, Option<String>) {
    let check = git_patch(root, patch_path, true);
    if let Err(outcome) = check {
        return (outcome, None);
    }
    if let Err(outcome) = git_patch(root, patch_path, false) {
        return (outcome, None);
    }
    if let Err(error) = run_git(root, ["add", "--all"]) {
        return (PhaseOutcome::failed(&error.to_string()), None);
    }
    match run_git(root, ["write-tree"]) {
        Ok(tree_sha) => (PhaseOutcome::passed(), Some(tree_sha)),
        Err(error) => (PhaseOutcome::failed(&error.to_string()), None),
    }
}

fn git_patch(root: &Path, patch_path: &Path, check: bool) -> Result<(), PhaseOutcome> {
    let mut command = Command::new("git");
    command.current_dir(root).arg("apply");
    if check {
        command.arg("--check");
    }
    let output = command
        .arg(patch_path)
        .output()
        .map_err(|error| PhaseOutcome::failed(&format!("git apply could not start: {error}")))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(PhaseOutcome {
            status: PhaseStatus::Failed,
            timed_out: false,
            exit_code: output.status.code(),
            stdout_sha256: Some(hash_bytes(&output.stdout)),
            stderr_sha256: Some(hash_bytes(&output.stderr)),
            detail: Some("git apply rejected candidate patch".into()),
        })
    }
}

fn run_phase(
    spec: &CommandSpec,
    candidate_root: &Path,
    scratch: &TempDir,
    target_dir: &Path,
    candidate_id: &str,
    fixture_root: Option<(&str, &Path)>,
    timeout_secs: u64,
    phase: &str,
) -> PhaseOutcome {
    let mut command = Command::new(&spec.program);
    command
        .args(&spec.args)
        .current_dir(candidate_root)
        .envs(&spec.env)
        .env_remove("E013_HIDDEN_ADJUDICATOR")
        .env_remove("E013_HIDDEN_ROOT")
        .env_remove("E013_VISIBLE_ROOT")
        .env("CARGO_NET_OFFLINE", "true")
        .env("CARGO_TARGET_DIR", target_dir)
        .env("E013_MODEL_CONTACT_AUTHORIZED", "false")
        .env("E013_CANDIDATE_ID", candidate_id);
    if let Some((key, path)) = fixture_root {
        command.env(key, path);
        if key == "E013_HIDDEN_ADJUDICATOR" {
            if let Some(parent) = path.parent() {
                command.env("E013_HIDDEN_ROOT", parent);
            }
        }
    }
    let stdout_path = scratch.path().join(format!("{phase}.stdout.log"));
    let stderr_path = scratch.path().join(format!("{phase}.stderr.log"));
    let stdout = match File::create(&stdout_path) {
        Ok(file) => file,
        Err(error) => return PhaseOutcome::failed(&format!("cannot create stdout log: {error}")),
    };
    let stderr = match File::create(&stderr_path) {
        Ok(file) => file,
        Err(error) => return PhaseOutcome::failed(&format!("cannot create stderr log: {error}")),
    };
    let mut child = match command
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
    {
        Ok(child) => child,
        Err(error) => return PhaseOutcome::failed(&format!("command could not start: {error}")),
    };
    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if start.elapsed() < Duration::from_secs(timeout_secs) => {
                thread::sleep(Duration::from_millis(25));
            }
            Ok(None) => {
                kill_process_tree(&mut child);
                break child.wait().ok();
            }
            Err(_) => {
                kill_process_tree(&mut child);
                break child.wait().ok();
            }
        }
    };
    let timed_out = start.elapsed() >= Duration::from_secs(timeout_secs);
    let stdout_sha256 = hash_log(&stdout_path).ok();
    let stderr_sha256 = hash_log(&stderr_path).ok();
    let succeeded = status.as_ref().is_some_and(|status| status.success()) && !timed_out;
    let exit_code = status.and_then(|value| value.code());
    PhaseOutcome {
        timed_out,
        status: if succeeded {
        PhaseStatus::Passed
    } else {
        PhaseStatus::Failed
        },
        exit_code,
        stdout_sha256,
        stderr_sha256,
        detail: if timed_out {
            Some(format!("{phase} phase timed out after {timeout_secs}s"))
        } else if succeeded {
            None
        } else {
            Some(format!("{phase} command failed: {}", spec.program))
        },
    }
}

fn hash_log(path: &Path) -> std::io::Result<String> {
    let mut file = File::open(path)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    Ok(hash_bytes(&bytes))
}

fn kill_process_tree(child: &mut std::process::Child) {
    #[cfg(windows)]
    {
        let id = child.id().to_string();
        let _ = Command::new("taskkill")
            .args(["/PID", id.as_str(), "/T", "/F"])
            .output();
    }
    let _ = child.kill();
}

fn write_visible_assets(root: &Path, draft: &EpisodeDraft) -> Result<(), FactoryError> {
    for (group, assets) in [
        ("fixtures", draft.visible_fixtures.as_slice()),
        ("evidence", draft.visible_evidence.as_slice()),
    ] {
        for asset in assets {
            write_asset(root, group, asset)?;
        }
    }
    Ok(())
}

fn write_asset(root: &Path, group: &str, asset: &Asset) -> Result<(), FactoryError> {
    validate_relative_path(&asset.path)?;
    let path = root.join(group).join(&asset.path);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| io_error(parent, error))?;
    }
    fs::write(&path, &asset.bytes).map_err(|error| io_error(&path, error))
}

#[allow(dead_code)]
fn _path_buf_typecheck(_: PathBuf) {}
