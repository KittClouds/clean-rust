use crate::format::hex;
use crate::{
    write_asserted_discovery_view, AssertedDiscoveryView, DiscoveryAuthorityBinding,
    DiscoveryRelationPolicy, DiscoveryViewError, DiscoveryViewManifest,
};
use phoenix_graph_kernel::KernelGraphSnapshot;
use serde::{Deserialize, Serialize};
use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

const RECEIPT_SCHEMA: &str = "phoenix-asserted-discovery-generation/v1";
static RECEIPT_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveryGenerationReceipt {
    pub schema_version: String,
    pub generation: u64,
    pub artifact_digest: String,
    pub source_snapshot_id: String,
    pub source_snapshot_digest: String,
    pub evidence_registry_digest: String,
    pub relation_policy_digest: String,
    pub admitted_candidate_edges: u64,
}

impl DiscoveryGenerationReceipt {
    fn from_manifest(manifest: &DiscoveryViewManifest) -> Self {
        Self {
            schema_version: RECEIPT_SCHEMA.to_owned(),
            generation: manifest.generation,
            artifact_digest: manifest.artifact_digest.clone(),
            source_snapshot_id: manifest.source_snapshot_id.clone(),
            source_snapshot_digest: manifest.source_snapshot_digest.clone(),
            evidence_registry_digest: manifest.evidence_registry_digest.clone(),
            relation_policy_digest: manifest.relation_policy_digest.clone(),
            admitted_candidate_edges: manifest.admitted_candidate_edges,
        }
    }

    fn validate(&self) -> Result<(), DiscoveryViewError> {
        if self.schema_version != RECEIPT_SCHEMA {
            return Err(DiscoveryViewError::Invalid(format!(
                "unsupported generation receipt schema {}",
                self.schema_version
            )));
        }
        if self.generation == 0 || self.admitted_candidate_edges != 0 {
            return Err(DiscoveryViewError::Invalid(
                "generation receipt violates asserted-only authority".to_owned(),
            ));
        }
        if !is_digest(&self.artifact_digest)
            || !is_digest(&self.source_snapshot_digest)
            || !is_digest(&self.evidence_registry_digest)
            || !is_digest(&self.relation_policy_digest)
        {
            return Err(DiscoveryViewError::Invalid(
                "generation receipt contains a malformed digest".to_owned(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct DiscoveryViewRegistry {
    root: PathBuf,
}

impl DiscoveryViewRegistry {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn publish(
        &self,
        snapshot: &KernelGraphSnapshot,
        authority: &DiscoveryAuthorityBinding,
        policy: &DiscoveryRelationPolicy,
    ) -> Result<DiscoveryGenerationReceipt, DiscoveryViewError> {
        fs::create_dir_all(self.objects_root())?;
        fs::create_dir_all(self.generations_root())?;
        let receipt_path = self.receipt_path(authority.generation);
        if receipt_path.exists() {
            let existing = self.receipt(authority.generation)?;
            let policy_digest = hex(&policy.digest()?);
            if existing.source_snapshot_id == authority.source_snapshot_id
                && existing.source_snapshot_digest == hex(&authority.source_snapshot_digest)
                && existing.evidence_registry_digest == hex(&authority.evidence_registry_digest)
                && existing.relation_policy_digest == policy_digest
            {
                self.open_generation(authority.generation)?;
                return Ok(existing);
            }
            return Err(DiscoveryViewError::GenerationConflict {
                generation: authority.generation,
                existing: existing.artifact_digest,
            });
        }
        let manifest =
            write_asserted_discovery_view(snapshot, authority, policy, self.objects_root())?;
        let expected = DiscoveryGenerationReceipt::from_manifest(&manifest);
        self.install_receipt(&expected)?;
        Ok(expected)
    }

    pub fn receipt(
        &self,
        generation: u64,
    ) -> Result<DiscoveryGenerationReceipt, DiscoveryViewError> {
        let bytes = fs::read(self.receipt_path(generation))?;
        let receipt: DiscoveryGenerationReceipt = serde_json::from_slice(&bytes)?;
        receipt.validate()?;
        if receipt.generation != generation {
            return Err(DiscoveryViewError::Invalid(format!(
                "generation receipt {} is stored in slot {generation}",
                receipt.generation
            )));
        }
        Ok(receipt)
    }

    pub fn open_generation(
        &self,
        generation: u64,
    ) -> Result<AssertedDiscoveryView, DiscoveryViewError> {
        let receipt = self.receipt(generation)?;
        let view = AssertedDiscoveryView::open(self.objects_root().join(&receipt.artifact_digest))?;
        let actual = DiscoveryGenerationReceipt::from_manifest(view.manifest());
        if actual != receipt {
            return Err(DiscoveryViewError::Invalid(format!(
                "generation {generation} receipt does not match its artifact"
            )));
        }
        Ok(view)
    }

    fn install_receipt(
        &self,
        expected: &DiscoveryGenerationReceipt,
    ) -> Result<(), DiscoveryViewError> {
        let final_path = self.receipt_path(expected.generation);
        if final_path.exists() {
            return self.compare_existing(expected);
        }
        let sequence = RECEIPT_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let temporary = self.generations_root().join(format!(
            ".publishing-{}-{}-{sequence}.json",
            std::process::id(),
            expected.generation
        ));
        let result = (|| {
            let file = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&temporary)?;
            let mut writer = BufWriter::new(file);
            serde_json::to_writer(&mut writer, expected)?;
            writer.write_all(b"\n")?;
            writer.flush()?;
            writer.get_ref().sync_all()?;
            match fs::hard_link(&temporary, &final_path) {
                Ok(()) => Ok(()),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                    self.compare_existing(expected)
                }
                Err(error) => Err(error.into()),
            }
        })();
        let _ = fs::remove_file(&temporary);
        result
    }

    fn compare_existing(
        &self,
        expected: &DiscoveryGenerationReceipt,
    ) -> Result<(), DiscoveryViewError> {
        let existing = self.receipt(expected.generation)?;
        if existing == *expected {
            return Ok(());
        }
        Err(DiscoveryViewError::GenerationConflict {
            generation: expected.generation,
            existing: existing.artifact_digest,
        })
    }

    fn objects_root(&self) -> PathBuf {
        self.root.join("objects")
    }

    fn generations_root(&self) -> PathBuf {
        self.root.join("generations")
    }

    fn receipt_path(&self, generation: u64) -> PathBuf {
        self.generations_root()
            .join(format!("{generation:020}.json"))
    }
}

fn is_digest(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}
