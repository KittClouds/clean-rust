use std::path::Path;

use e013_episode_factory::{hash_bytes, Provenance, SourceReference};
use sha2::{Digest, Sha256};

use crate::generate::FactoryResult;

const SOURCE_INTAKE: &[u8] = include_bytes!("../../../SOURCE-INTAKE-v0.1.md");

pub fn family_provenance() -> Provenance {
    Provenance {
        generator_name: "e013-c-family-generator".to_string(),
        generator_version: "0.1.0".to_string(),
        generator_source_sha256: generator_sha256(),
        source_refs: vec![SourceReference {
            artifact_id: "E013-SOURCE-INTAKE-v0.1".to_string(),
            sha256: hash_bytes(SOURCE_INTAKE),
            role: "design-only provenance ledger; no released evaluation rows imported".to_string(),
        }],
    }
}

pub fn baseline_source(path: &Path) -> FactoryResult<SourceReference> {
    let bytes = std::fs::read(path).map_err(|error| {
        e013_episode_factory::FactoryError::Io { path: path.to_path_buf(), source: error }
    })?;
    Ok(SourceReference {
        artifact_id: path
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("c-baseline-module")
            .to_string(),
        sha256: hash_bytes(&bytes),
        role: "authored Rust template module used as the local patch base".to_string(),
    })
}

fn generator_sha256() -> String {
    let mut hash = Sha256::new();
    for source in [
        include_bytes!("lib.rs").as_slice(),
        include_bytes!("spec.rs").as_slice(),
        include_bytes!("generate.rs").as_slice(),
        include_bytes!("candidate.rs").as_slice(),
        include_bytes!("oracle.rs").as_slice(),
        include_bytes!("provenance.rs").as_slice(),
    ] {
        hash.update((source.len() as u64).to_le_bytes());
        hash.update(source);
    }
    format!("{:x}", hash.finalize())
}
