use std::path::PathBuf;

use clap::{Parser, Subcommand};
use e013_episode_factory::{materialize_snapshot, verify_episode, RepoTemplate};

#[derive(Debug, Parser)]
#[command(
    name = "e013-factory",
    about = "Verify sealed E013 episode artifacts and freeze repo templates"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Verify canonical manifests, private/public boundaries, and every package hash.
    Verify {
        #[arg(value_name = "EPISODE_DIR")]
        episode_dir: PathBuf,
    },
    /// Materialize a family-owned source tree as a deterministic local Git snapshot.
    Snapshot {
        #[arg(long)]
        repo_id: String,
        #[arg(long)]
        template_root: PathBuf,
        #[arg(long)]
        destination: PathBuf,
    },
}

fn main() {
    if let Err(error) = run() {
        eprintln!("e013-factory: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    match Cli::parse().command {
        Command::Verify { episode_dir } => {
            let verified = verify_episode(&episode_dir)?;
            println!(
                "verified episode={} protocol={} files={} root_sha256={}",
                verified.manifest.episode_id,
                verified.manifest.protocol_version,
                verified.seal.entry_count,
                verified.seal.root_sha256
            );
        }
        Command::Snapshot {
            repo_id,
            template_root,
            destination,
        } => {
            let snapshot = materialize_snapshot(
                &RepoTemplate {
                    repo_id,
                    template_root,
                },
                &destination,
            )?;
            println!(
                "repo_id={} commit={} tree={}",
                snapshot.repo_id, snapshot.commit_sha, snapshot.tree_sha
            );
        }
    }
    Ok(())
}
