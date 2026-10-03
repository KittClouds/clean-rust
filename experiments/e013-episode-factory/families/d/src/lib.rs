mod family;
mod patch;
mod spec;

use std::path::PathBuf;

use e013_episode_factory::{EpisodeFamily, RepoTemplate};

pub use family::DFamily;

const REPOSITORIES: [&str; 6] = [
    "e013-d-ledgerleaf",
    "e013-d-parcelpath",
    "e013-d-queueforge",
    "e013-d-cacheweave",
    "e013-d-receiptline",
    "e013-d-signalharbor",
];

/// Return the eight cross-cutting contract families owned by the D bank.
pub fn families() -> Vec<Box<dyn EpisodeFamily>> {
    spec::FAMILY_IDS
        .iter()
        .map(|family_id| Box::new(DFamily::new(family_id)) as Box<dyn EpisodeFamily>)
        .collect()
}

/// Return six authored, self-contained Rust repository templates for core materialization.
pub fn repository_templates() -> Vec<RepoTemplate> {
    let template_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("templates");
    REPOSITORIES
        .iter()
        .map(|repo_id| RepoTemplate {
            repo_id: (*repo_id).to_owned(),
            template_root: template_root.join(repo_id),
        })
        .collect()
}

#[cfg(test)]
mod tests;
