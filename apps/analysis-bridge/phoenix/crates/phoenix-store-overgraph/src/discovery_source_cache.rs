use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use phoenix_discovery_view::{
    write_asserted_discovery_view, write_asserted_discovery_view_from_source,
    AssertedDiscoveryView, DiscoveryAuthorityBinding, DiscoveryRelationPolicy,
    PagedAssertedDiscoverySource,
};
use phoenix_kernel::KernelGraphSnapshot;
use phoenix_store_native_core::StoreError;
use serde::{Deserialize, Serialize};

use super::{
    optional_string_prop, store_query_error, PhoenixOvergraphStore, KERNEL_CHECKPOINT_KEY,
    PROP_DISCOVERY_SOURCE_CACHE_SCHEMA, PROP_GENERATION, PROP_SOURCE_REVISION,
    TYPE_KERNEL_CHECKPOINT,
};

pub(crate) const CACHE_SCHEMA: &str = "phoenix-discovery-source-cache/v1";
const CACHE_ROOT: &str = "discovery-source-cache";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoverySourceCacheReceipt {
    pub schema_version: String,
    pub generation: u64,
    pub source_revision: String,
    pub artifact_digest: String,
    pub payload_digest: String,
    pub node_count: u64,
    pub edge_count: u64,
    pub excluded_candidate_edges: u64,
}

impl PhoenixOvergraphStore {
    pub fn rebuild_discovery_source_cache(
        &self,
    ) -> Result<DiscoverySourceCacheReceipt, StoreError> {
        let (generation, source_revision) = self.with_engine(|engine| {
            let checkpoint = engine
                .get_node_by_key(TYPE_KERNEL_CHECKPOINT, KERNEL_CHECKPOINT_KEY)
                .map_err(store_query_error)?;
            let generation = self.kernel_current_generation_with_engine(engine)?.max(
                checkpoint
                    .as_ref()
                    .and_then(|node| super::optional_u64_prop(node, PROP_GENERATION))
                    .unwrap_or(0),
            );
            let source_revision = checkpoint
                .as_ref()
                .and_then(|node| optional_string_prop(node, PROP_SOURCE_REVISION))
                .unwrap_or_else(|| format!("generation-{generation}"));
            Ok((generation, source_revision))
        })?;
        if generation == 0 {
            return Err(StoreError::Query(
                "cannot build discovery source cache without a kernel generation".to_owned(),
            ));
        }
        let receipt = prepare_from_source(&self.path, self, generation, &source_revision)?;
        install_receipt(&self.path, &receipt)?;
        self.clear_discovery_source_cache();
        Ok(receipt)
    }

    pub(crate) fn prepare_discovery_source_cache(
        &self,
        generation: u64,
        source_revision: &str,
        snapshot: &KernelGraphSnapshot,
    ) -> Result<DiscoverySourceCacheReceipt, StoreError> {
        prepare_from_snapshot(&self.path, snapshot, generation, source_revision)
    }

    pub(crate) fn install_discovery_source_cache(
        &self,
        receipt: &DiscoverySourceCacheReceipt,
    ) -> Result<(), StoreError> {
        install_receipt(&self.path, receipt)?;
        self.clear_discovery_source_cache();
        Ok(())
    }

    pub(crate) fn open_discovery_source_cache(
        &self,
        generation: u64,
    ) -> Result<Option<Arc<AssertedDiscoveryView>>, StoreError> {
        if let Some((cached_generation, view)) = self
            .discovery_source_view_cache
            .lock()
            .map_err(|_| StoreError::Query("discovery source cache lock poisoned".to_owned()))?
            .as_ref()
        {
            if *cached_generation == generation {
                return Ok(Some(Arc::clone(view)));
            }
        }
        let Some(receipt) = read_receipt(&self.path, generation)? else {
            if self.discovery_source_cache_required(generation)? {
                return Err(StoreError::Query(format!(
                    "required discovery source cache receipt is missing for generation {generation}"
                )));
            }
            return Ok(None);
        };
        let view = Arc::new(
            AssertedDiscoveryView::open(objects_root(&self.path).join(&receipt.artifact_digest))
                .map_err(view_error)?,
        );
        if view.manifest().generation != generation
            || view.manifest().payload_digest != receipt.payload_digest
            || view.manifest().node_count != receipt.node_count
            || view.manifest().edge_count != receipt.edge_count
            || view.manifest().excluded_candidate_edges != receipt.excluded_candidate_edges
        {
            return Err(StoreError::Query(
                "discovery source cache receipt does not match its mmap artifact".to_owned(),
            ));
        }
        view.validate_payload().map_err(view_error)?;
        let mut cache = self
            .discovery_source_view_cache
            .lock()
            .map_err(|_| StoreError::Query("discovery source cache lock poisoned".to_owned()))?;
        *cache = Some((generation, Arc::clone(&view)));
        Ok(Some(view))
    }

    pub(crate) fn clear_discovery_source_cache(&self) {
        if let Ok(mut cache) = self.discovery_source_view_cache.lock() {
            *cache = None;
        }
    }

    fn discovery_source_cache_required(&self, generation: u64) -> Result<bool, StoreError> {
        self.with_engine(|engine| {
            let checkpoint = engine
                .get_node_by_key(TYPE_KERNEL_CHECKPOINT, KERNEL_CHECKPOINT_KEY)
                .map_err(store_query_error)?;
            Ok(checkpoint.is_some_and(|node| {
                super::optional_u64_prop(&node, PROP_GENERATION) == Some(generation)
                    && optional_string_prop(&node, PROP_DISCOVERY_SOURCE_CACHE_SCHEMA).as_deref()
                        == Some(CACHE_SCHEMA)
            }))
        })
    }
}

fn prepare_from_snapshot(
    store_path: &Path,
    snapshot: &KernelGraphSnapshot,
    generation: u64,
    source_revision: &str,
) -> Result<DiscoverySourceCacheReceipt, StoreError> {
    if let Some(existing) = reusable_receipt(store_path, generation, source_revision)? {
        return Ok(existing);
    }
    let manifest = write_asserted_discovery_view(
        snapshot,
        &cache_authority(generation, source_revision),
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        objects_root(store_path),
    )
    .map_err(view_error)?;
    Ok(receipt(source_revision, &manifest))
}

fn prepare_from_source(
    store_path: &Path,
    source: &impl PagedAssertedDiscoverySource,
    generation: u64,
    source_revision: &str,
) -> Result<DiscoverySourceCacheReceipt, StoreError> {
    if let Some(existing) = reusable_receipt(store_path, generation, source_revision)? {
        return Ok(existing);
    }
    let manifest = write_asserted_discovery_view_from_source(
        source,
        &cache_authority(generation, source_revision),
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        objects_root(store_path),
    )
    .map_err(view_error)?;
    Ok(receipt(source_revision, &manifest))
}

fn reusable_receipt(
    store_path: &Path,
    generation: u64,
    source_revision: &str,
) -> Result<Option<DiscoverySourceCacheReceipt>, StoreError> {
    let Some(existing) = read_receipt(store_path, generation)? else {
        return Ok(None);
    };
    if existing.source_revision != source_revision {
        return Err(StoreError::Query(format!(
            "discovery source generation {generation} conflicts with immutable source revision"
        )));
    }
    Ok(Some(existing))
}

fn receipt(
    source_revision: &str,
    manifest: &phoenix_discovery_view::DiscoveryViewManifest,
) -> DiscoverySourceCacheReceipt {
    DiscoverySourceCacheReceipt {
        schema_version: CACHE_SCHEMA.to_owned(),
        generation: manifest.generation,
        source_revision: source_revision.to_owned(),
        artifact_digest: manifest.artifact_digest.clone(),
        payload_digest: manifest.payload_digest.clone(),
        node_count: manifest.node_count,
        edge_count: manifest.edge_count,
        excluded_candidate_edges: manifest.excluded_candidate_edges,
    }
}

fn cache_authority(generation: u64, source_revision: &str) -> DiscoveryAuthorityBinding {
    let snapshot =
        blake3::hash(format!("phoenix-discovery-source-snapshot/v1\0{source_revision}").as_bytes());
    let evidence =
        blake3::hash(format!("phoenix-discovery-source-evidence/v1\0{source_revision}").as_bytes());
    DiscoveryAuthorityBinding {
        generation,
        source_snapshot_id: format!("kernel-source:{source_revision}"),
        source_snapshot_digest: *snapshot.as_bytes(),
        evidence_registry_digest: *evidence.as_bytes(),
    }
}

fn install_receipt(
    store_path: &Path,
    receipt: &DiscoverySourceCacheReceipt,
) -> Result<(), StoreError> {
    let directory = generations_root(store_path);
    fs::create_dir_all(&directory).map_err(io_error)?;
    let final_path = receipt_path(store_path, receipt.generation);
    if final_path.exists() {
        let existing = read_receipt(store_path, receipt.generation)?
            .ok_or_else(|| StoreError::Query("discovery source receipt disappeared".to_owned()))?;
        return if existing == *receipt {
            Ok(())
        } else {
            Err(StoreError::Query(format!(
                "discovery source generation {} conflicts with immutable receipt",
                receipt.generation
            )))
        };
    }
    let temporary = final_path.with_extension(format!(
        "publishing-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ));
    let file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .map_err(io_error)?;
    let mut writer = BufWriter::new(file);
    serde_json::to_writer(&mut writer, receipt)
        .map_err(|error| StoreError::Query(error.to_string()))?;
    writer.write_all(b"\n").map_err(io_error)?;
    writer.flush().map_err(io_error)?;
    writer.get_ref().sync_all().map_err(io_error)?;
    drop(writer);
    match fs::rename(&temporary, &final_path) {
        Ok(()) => Ok(()),
        Err(error) if final_path.exists() => {
            let _ = fs::remove_file(&temporary);
            let existing = read_receipt(store_path, receipt.generation)?.ok_or_else(|| {
                StoreError::Query("discovery source receipt disappeared".to_owned())
            })?;
            if existing == *receipt {
                Ok(())
            } else {
                Err(StoreError::Query(error.to_string()))
            }
        }
        Err(error) => {
            let _ = fs::remove_file(&temporary);
            Err(io_error(error))
        }
    }
}

fn read_receipt(
    store_path: &Path,
    generation: u64,
) -> Result<Option<DiscoverySourceCacheReceipt>, StoreError> {
    let path = receipt_path(store_path, generation);
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(io_error(error)),
    };
    let receipt: DiscoverySourceCacheReceipt =
        serde_json::from_slice(&bytes).map_err(|error| StoreError::Query(error.to_string()))?;
    if receipt.schema_version != CACHE_SCHEMA || receipt.generation != generation {
        return Err(StoreError::Query(
            "invalid discovery source cache receipt".to_owned(),
        ));
    }
    Ok(Some(receipt))
}

fn cache_root(store_path: &Path) -> PathBuf {
    store_path.join(CACHE_ROOT)
}

fn objects_root(store_path: &Path) -> PathBuf {
    cache_root(store_path).join("objects")
}

fn generations_root(store_path: &Path) -> PathBuf {
    cache_root(store_path).join("generations")
}

fn receipt_path(store_path: &Path, generation: u64) -> PathBuf {
    generations_root(store_path).join(format!("{generation:020}.json"))
}

fn view_error(error: phoenix_discovery_view::DiscoveryViewError) -> StoreError {
    StoreError::Query(format!("discovery source cache: {error}"))
}

fn io_error(error: std::io::Error) -> StoreError {
    StoreError::Query(format!("discovery source cache I/O: {error}"))
}

#[cfg(test)]
mod tests {
    use std::io::{Read, Seek, SeekFrom, Write};

    use phoenix_discovery_view::PagedAssertedDiscoverySource;
    use phoenix_kernel::{
        KernelEdge, KernelEdgeType, KernelGraphLayer, KernelGraphSnapshot, KernelRelationClass,
        KernelVertex, KernelVertexId,
    };
    use phoenix_store_native_core::PhoenixGraphKernelStoreV2;

    use super::*;

    #[test]
    fn checkpoint_cache_reopens_exactly_and_corruption_fails_closed() {
        let root = tempfile::tempdir().unwrap();
        let store = PhoenixOvergraphStore::open(root.path()).unwrap();
        let snapshot = KernelGraphSnapshot {
            vertices: vec![vertex("b"), vertex("a")],
            asserted_edges: vec![edge("a", "b", "knows", KernelGraphLayer::Asserted)],
            candidate_edges: vec![edge(
                "b",
                "a",
                "candidate-poison",
                KernelGraphLayer::Candidate,
            )],
        };
        store
            .write_kernel_checkpoint(71, "cache-restart", &snapshot)
            .unwrap();
        assert_eq!(PagedAssertedDiscoverySource::node_count(&store).unwrap(), 2);
        assert_eq!(store.asserted_edge_count().unwrap(), 1);
        assert_eq!(store.candidate_edge_count().unwrap(), 1);
        let receipt = read_receipt(root.path(), 71).unwrap().unwrap();
        assert_eq!(receipt.excluded_candidate_edges, 1);
        drop(store);

        let reopened = PhoenixOvergraphStore::open(root.path()).unwrap();
        assert_eq!(
            PagedAssertedDiscoverySource::node_count(&reopened).unwrap(),
            2
        );
        let mut ids = Vec::new();
        reopened
            .visit_nodes(1, &mut |_, node| {
                ids.push(node.id.0.clone());
                Ok(())
            })
            .unwrap();
        assert_eq!(ids, ["a", "b"]);
        drop(reopened);

        let binary = objects_root(root.path())
            .join(receipt.artifact_digest)
            .join("view.bin");
        let mut file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(binary)
            .unwrap();
        file.seek(SeekFrom::End(-1)).unwrap();
        let mut byte = [0_u8; 1];
        file.read_exact(&mut byte).unwrap();
        file.seek(SeekFrom::End(-1)).unwrap();
        byte[0] ^= 0x5a;
        file.write_all(&byte).unwrap();
        file.sync_all().unwrap();
        drop(file);

        let corrupted = PhoenixOvergraphStore::open(root.path()).unwrap();
        let error = PagedAssertedDiscoverySource::node_count(&corrupted).unwrap_err();
        assert!(error.to_string().contains("payload digest mismatch"));
    }

    #[test]
    fn same_generation_source_conflict_preserves_installed_topology() {
        let root = tempfile::tempdir().unwrap();
        let store = PhoenixOvergraphStore::open(root.path()).unwrap();
        let installed = KernelGraphSnapshot {
            vertices: vec![vertex("installed")],
            ..Default::default()
        };
        store
            .write_kernel_checkpoint(81, "source-a", &installed)
            .unwrap();

        let conflicting = KernelGraphSnapshot {
            vertices: vec![vertex("conflicting")],
            ..Default::default()
        };
        let error = store
            .write_kernel_checkpoint(81, "source-b", &conflicting)
            .unwrap_err();
        assert!(error.to_string().contains("immutable source revision"));
        assert!(store
            .kernel_topology_vertex_id("installed")
            .unwrap()
            .is_some());
        assert!(store
            .kernel_topology_vertex_id("conflicting")
            .unwrap()
            .is_none());
    }

    #[test]
    fn checkpoint_marked_cache_cannot_fall_back_when_receipt_is_missing() {
        let root = tempfile::tempdir().unwrap();
        let store = PhoenixOvergraphStore::open(root.path()).unwrap();
        store
            .write_kernel_checkpoint(
                82,
                "required-cache",
                &KernelGraphSnapshot {
                    vertices: vec![vertex("only")],
                    ..Default::default()
                },
            )
            .unwrap();
        drop(store);
        fs::remove_file(receipt_path(root.path(), 82)).unwrap();

        let reopened = PhoenixOvergraphStore::open(root.path()).unwrap();
        let error = PagedAssertedDiscoverySource::node_count(&reopened).unwrap_err();
        assert!(error
            .to_string()
            .contains("required discovery source cache receipt is missing"));
    }

    fn vertex(id: &str) -> KernelVertex {
        KernelVertex {
            id: KernelVertexId(id.to_owned()),
            kind: "entity".to_owned(),
            ..Default::default()
        }
    }

    fn edge(source: &str, target: &str, relation: &str, layer: KernelGraphLayer) -> KernelEdge {
        KernelEdge {
            source_id: KernelVertexId(source.to_owned()),
            target_id: KernelVertexId(target.to_owned()),
            edge_type: KernelEdgeType(relation.to_owned()),
            relation_class: if layer == KernelGraphLayer::Candidate {
                KernelRelationClass::Candidate
            } else {
                KernelRelationClass::Semantic
            },
            layer,
            ..Default::default()
        }
    }
}
