use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
};

use crate::{
    error::io_error, paths::validate_identifier, FactoryError, RepoSnapshot, RepoTemplate,
};

/// Copies a family-owned template into a clean repository and creates a deterministic base commit.
pub fn materialize_snapshot(
    template: &RepoTemplate,
    destination: &Path,
) -> Result<RepoSnapshot, FactoryError> {
    validate_identifier(&template.repo_id, "repository id")?;
    let source = fs::canonicalize(&template.template_root)
        .map_err(|error| io_error(&template.template_root, error))?;
    let parent = destination.parent().ok_or_else(|| {
        FactoryError::Invalid(format!(
            "snapshot destination has no parent: {}",
            destination.display()
        ))
    })?;
    fs::create_dir_all(parent).map_err(|error| io_error(parent, error))?;
    if destination.exists() {
        return Err(FactoryError::Invalid(format!(
            "snapshot destination already exists: {}",
            destination.display()
        )));
    }
    fs::create_dir(destination).map_err(|error| io_error(destination, error))?;
    if let Err(error) = copy_tree(&source, destination) {
        return Err(error);
    }
    let files = fs::read_dir(destination)
        .map_err(|error| io_error(destination, error))?
        .count();
    if files == 0 {
        return Err(FactoryError::Invalid(format!(
            "template is empty: {}",
            source.display()
        )));
    }

    run_git(destination, ["init", "--quiet", "--initial-branch=main"])?;
    run_git(destination, ["add", "--all"])?;
    let commit = Command::new("git")
        .current_dir(destination)
        .args([
            "-c",
            "user.name=E013 Factory",
            "-c",
            "user.email=e013-factory@invalid",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "E013 frozen repository template",
        ])
        .env("GIT_AUTHOR_DATE", "2000-01-01T00:00:00Z")
        .env("GIT_COMMITTER_DATE", "2000-01-01T00:00:00Z")
        .output()
        .map_err(|source| crate::FactoryError::CommandSetup {
            phase: "snapshot commit".into(),
            source,
        })?;
    ensure_git_success("git commit template", commit)?;
    let (commit_sha, tree_sha) = read_snapshot_ids(destination)?;
    let snapshot = RepoSnapshot {
        repo_id: template.repo_id.clone(),
        commit_sha,
        tree_sha,
    };
    verify_snapshot(destination, &snapshot)?;
    Ok(snapshot)
}

/// Confirms that a runtime checkout still names the pinned commit/tree and has no dirty files.
pub fn verify_snapshot(root: &Path, snapshot: &RepoSnapshot) -> Result<(), FactoryError> {
    validate_identifier(&snapshot.repo_id, "repository id")?;
    let (commit, tree) = read_snapshot_ids(root)?;
    if commit != snapshot.commit_sha || tree != snapshot.tree_sha {
        return Err(FactoryError::Invalid(format!(
            "snapshot mismatch for {}: expected {}@{}, found {}@{}",
            snapshot.repo_id, snapshot.commit_sha, snapshot.tree_sha, commit, tree
        )));
    }
    let output = run_git_output(root, ["status", "--porcelain", "--untracked-files=all"])?;
    let dirty = String::from_utf8_lossy(&output.stdout);
    if !dirty.trim().is_empty() {
        return Err(FactoryError::Invalid(format!(
            "snapshot checkout is dirty: {}",
            root.display()
        )));
    }
    Ok(())
}

pub(crate) fn run_git<I, S>(root: &Path, args: I) -> Result<String, FactoryError>
where
    I: IntoIterator<Item = S>,
    S: AsRef<std::ffi::OsStr>,
{
    let output = run_git_output(root, args)?;
    let text = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    Ok(text)
}

pub(crate) fn run_git_output<I, S>(root: &Path, args: I) -> Result<Output, FactoryError>
where
    I: IntoIterator<Item = S>,
    S: AsRef<std::ffi::OsStr>,
{
    let args: Vec<S> = args.into_iter().collect();
    let printable = args
        .iter()
        .map(|arg| arg.as_ref().to_string_lossy())
        .collect::<Vec<_>>()
        .join(" ");
    let output = Command::new("git")
        .current_dir(root)
        .args(&args)
        .output()
        .map_err(|source| FactoryError::CommandSetup {
            phase: format!("git {printable}"),
            source,
        })?;
    if !output.status.success() {
        return Err(FactoryError::Git {
            command: format!("git {printable}"),
            stderr: String::from_utf8_lossy(&output.stderr).trim().to_owned(),
        });
    }
    Ok(output)
}

fn read_snapshot_ids(root: &Path) -> Result<(String, String), FactoryError> {
    let commit = run_git(root, ["rev-parse", "--verify", "HEAD"])?;
    let tree = run_git(root, ["rev-parse", "--verify", "HEAD^{tree}"])?;
    Ok((commit, tree))
}

fn copy_tree(source: &Path, destination: &Path) -> Result<(), FactoryError> {
    let mut entries = fs::read_dir(source)
        .map_err(|error| io_error(source, error))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| io_error(source, error))?;
    entries.sort_unstable_by_key(|entry| entry.file_name());
    for entry in entries {
        let name = entry.file_name();
        if name == ".git" || name == "target" {
            continue;
        }
        let source_path = entry.path();
        let destination_path = destination.join(&name);
        let metadata =
            fs::symlink_metadata(&source_path).map_err(|error| io_error(&source_path, error))?;
        if metadata.file_type().is_symlink() {
            return Err(FactoryError::Invalid(format!(
                "template symlink rejected: {}",
                source_path.display()
            )));
        }
        if metadata.is_dir() {
            fs::create_dir(&destination_path)
                .map_err(|error| io_error(&destination_path, error))?;
            copy_tree(&source_path, &destination_path)?;
        } else if metadata.is_file() {
            fs::copy(&source_path, &destination_path)
                .map_err(|error| io_error(&destination_path, error))?;
        } else {
            return Err(FactoryError::Invalid(format!(
                "unsupported template entry: {}",
                source_path.display()
            )));
        }
    }
    Ok(())
}

fn ensure_git_success(command: &str, output: Output) -> Result<(), FactoryError> {
    if output.status.success() {
        return Ok(());
    }
    Err(FactoryError::Git {
        command: command.to_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).trim().to_owned(),
    })
}

#[allow(dead_code)]
fn _path_buf_is_runtime_only(_: PathBuf) {}
