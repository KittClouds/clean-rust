use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use phoenix_semantic_v2::{
    DirtyScopeRecord, DocumentArchive, DocumentManifest, DocumentOrd, DocumentSegmentKind,
    LexicalPostingsSegment,
};
use phoenix_store_native_core::{
    ArchiveSegmentMask, PhoenixScopeRuntimeStore, ScopeImageSpec, ScopeRuntimeImage,
    ScopeRuntimeIndices, ScopeSidecarBundle,
};
use phoenix_types::ScopeKey;
use serde::{Deserialize, Serialize};

use crate::{decode_archive, encode_archive, store_query_error};
use crate::{DatabaseEngine, PhoenixOvergraphStore, StoreError};

const SCOPE_RUNTIME_CACHE_LIMIT: usize = 64;
const SCOPE_RUNTIME_DISK_CACHE_DIR: &str = "scope-runtime-cache";

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ScopeRuntimeLoadTelemetry {
    pub manifest_group_us: u64,
    pub scope_count: usize,
    pub runtime_memory_cache_lookup_us: u64,
    pub runtime_memory_cache_hit_count: usize,
    pub runtime_disk_cache_lookup_us: u64,
    pub runtime_disk_cache_hit_count: usize,
    pub runtime_disk_cache_bypass_count: usize,
    pub runtime_disk_path_check_us: u64,
    pub runtime_disk_read_us: u64,
    pub runtime_disk_read_bytes: u64,
    pub runtime_disk_decode_us: u64,
    pub runtime_disk_decode_error_count: usize,
    pub runtime_disk_index_build_us: u64,
    pub runtime_disk_image_wrap_us: u64,
    pub runtime_cache_miss_count: usize,
    pub document_projection_us: u64,
    pub sidecar_bundle_us: u64,
    pub runtime_cache_write_us: u64,
    pub runtime_remember_us: u64,
}

#[derive(Debug)]
pub(crate) struct CachedScopeDocumentProjection {
    scope_key: String,
    updated_at: i64,
    document_ord_fingerprint: u64,
    archive_segments: ArchiveSegmentMask,
    manifests: Arc<[DocumentManifest]>,
    archives: Arc<[DocumentArchive]>,
    indices: Arc<ScopeRuntimeIndices>,
}

#[derive(Debug)]
pub(crate) struct CachedScopeRuntimeImage {
    scope_key: String,
    updated_at: i64,
    document_ord_fingerprint: u64,
    spec: ScopeImageSpec,
    image: Arc<ScopeRuntimeImage>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct ScopeDocumentProjectionCacheEntry {
    manifests: Vec<DocumentManifest>,
    archives: Vec<DocumentArchive>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct ScopeRuntimeImageCacheEntry {
    dirty: DirtyScopeRecord,
    manifests: Vec<DocumentManifest>,
    archives: Vec<DocumentArchive>,
    sidecars: ScopeSidecarBundle,
}

fn encode_runtime_image_cache_entry(
    value: &ScopeRuntimeImageCacheEntry,
) -> Result<Vec<u8>, StoreError> {
    // This is a derived hot-path cache, not canonical storage. Bump the
    // `.runtime.v*.bin` suffix if this positional payload shape changes.
    let payload = rmp_serde::to_vec(value).map_err(|error| StoreError::Query(error.to_string()))?;
    Ok(lz4_flex::compress_prepend_size(&payload))
}

fn decode_runtime_image_cache_entry(
    bytes: &[u8],
) -> Result<ScopeRuntimeImageCacheEntry, StoreError> {
    let payload = lz4_flex::decompress_size_prepended(bytes)
        .map_err(|error| StoreError::Query(error.to_string()))?;
    rmp_serde::from_slice(&payload).map_err(|error| StoreError::Query(error.to_string()))
}

impl PhoenixOvergraphStore {
    pub fn load_scope_runtime_images_with_telemetry(
        &self,
        spec: ScopeImageSpec,
    ) -> Result<(Vec<ScopeRuntimeImage>, ScopeRuntimeLoadTelemetry), StoreError> {
        self.with_engine(|engine| {
            let mut telemetry = ScopeRuntimeLoadTelemetry::default();
            let manifest_started = Instant::now();
            let mut grouped = BTreeMap::<String, (ScopeKey, Vec<DocumentManifest>)>::new();
            for manifest in self.load_latest_document_manifests_with_engine(engine, None)? {
                let entry = grouped
                    .entry(manifest.scope_key.clone())
                    .or_insert_with(|| (manifest.scope.clone(), Vec::new()));
                entry.1.push(manifest);
            }
            telemetry.manifest_group_us = elapsed_us(manifest_started);

            let mut images = Vec::with_capacity(grouped.len());
            for (_scope_key, (scope, manifests)) in grouped {
                if let Some(image) = self.load_scope_runtime_image_from_manifests_with_telemetry(
                    engine,
                    &scope,
                    manifests,
                    spec,
                    &mut telemetry,
                )? {
                    images.push(image);
                }
            }
            Ok((images, telemetry))
        })
    }

    fn document_ord_fingerprint(document_ords: &[DocumentOrd]) -> u64 {
        let mut fingerprint = 0xcbf29ce484222325u64 ^ (document_ords.len() as u64);
        for document_ord in document_ords {
            fingerprint ^= document_ord.0.wrapping_mul(0x9e37_79b9_7f4a_7c15);
            fingerprint = fingerprint.rotate_left(13).wrapping_mul(0x100000001b3);
        }
        fingerprint
    }

    fn runtime_cache_key_parts(dirty: &DirtyScopeRecord) -> (String, i64, u64) {
        (
            dirty.scope_key.clone(),
            dirty.updated_at,
            Self::document_ord_fingerprint(&dirty.document_ords),
        )
    }

    pub(crate) fn scope_runtime_cache_dir(&self) -> PathBuf {
        self.path.join(SCOPE_RUNTIME_DISK_CACHE_DIR)
    }

    pub(crate) fn document_projection_cache_path(
        &self,
        dirty: &DirtyScopeRecord,
        mask: ArchiveSegmentMask,
    ) -> PathBuf {
        let (_, updated_at, document_ord_fingerprint) = Self::runtime_cache_key_parts(dirty);
        self.scope_runtime_cache_dir().join(format!(
            "scope-{}-u{}-d{}-m{}.bin",
            dirty.scope_ord.0,
            updated_at,
            document_ord_fingerprint,
            mask.raw_bits()
        ))
    }

    pub(crate) fn scope_runtime_image_cache_path(
        &self,
        dirty: &DirtyScopeRecord,
        spec: ScopeImageSpec,
    ) -> PathBuf {
        let (_, updated_at, document_ord_fingerprint) = Self::runtime_cache_key_parts(dirty);
        self.scope_runtime_cache_dir().join(format!(
            "scope-{}-u{}-d{}-a{}-s{}.runtime.v3.bin",
            dirty.scope_ord.0,
            updated_at,
            document_ord_fingerprint,
            spec.archive_segments.raw_bits(),
            spec.sidecars.raw_bits()
        ))
    }

    fn retain_cache_limit<T>(entries: &mut Vec<Arc<T>>) {
        if entries.len() >= SCOPE_RUNTIME_CACHE_LIMIT {
            let overflow = entries.len() + 1 - SCOPE_RUNTIME_CACHE_LIMIT;
            entries.drain(0..overflow);
        }
    }

    fn load_cached_runtime_image(
        &self,
        dirty: &DirtyScopeRecord,
        spec: ScopeImageSpec,
    ) -> Result<Option<ScopeRuntimeImage>, StoreError> {
        let (scope_key, updated_at, document_ord_fingerprint) =
            Self::runtime_cache_key_parts(dirty);
        let cache = self.scope_runtime_image_cache.lock().map_err(|_| {
            StoreError::Query("scope runtime image cache mutex poisoned".to_owned())
        })?;
        Ok(cache
            .iter()
            .rev()
            .find(|cached| {
                cached.scope_key == scope_key
                    && cached.updated_at == updated_at
                    && cached.document_ord_fingerprint == document_ord_fingerprint
                    && cached.spec == spec
            })
            .map(|cached| cached.image.as_ref().clone()))
    }

    fn remember_runtime_image(
        &self,
        dirty: &DirtyScopeRecord,
        spec: ScopeImageSpec,
        image: ScopeRuntimeImage,
    ) -> Result<ScopeRuntimeImage, StoreError> {
        let (scope_key, updated_at, document_ord_fingerprint) =
            Self::runtime_cache_key_parts(dirty);
        let cached = Arc::new(CachedScopeRuntimeImage {
            scope_key,
            updated_at,
            document_ord_fingerprint,
            spec,
            image: Arc::new(image.clone()),
        });
        let mut cache = self.scope_runtime_image_cache.lock().map_err(|_| {
            StoreError::Query("scope runtime image cache mutex poisoned".to_owned())
        })?;
        cache.retain(|entry| {
            !(entry.scope_key == cached.scope_key
                && entry.updated_at == cached.updated_at
                && entry.document_ord_fingerprint == cached.document_ord_fingerprint
                && entry.spec == cached.spec)
        });
        Self::retain_cache_limit(&mut cache);
        cache.push(cached);
        Ok(image)
    }

    fn load_cached_document_projection(
        &self,
        dirty: &DirtyScopeRecord,
        requested_mask: ArchiveSegmentMask,
    ) -> Result<Option<Arc<CachedScopeDocumentProjection>>, StoreError> {
        let (scope_key, updated_at, document_ord_fingerprint) =
            Self::runtime_cache_key_parts(dirty);
        let cache = self.scope_runtime_document_cache.lock().map_err(|_| {
            StoreError::Query("scope runtime document cache mutex poisoned".to_owned())
        })?;

        let mut best = None::<Arc<CachedScopeDocumentProjection>>;
        for cached in cache.iter().rev() {
            if cached.scope_key != scope_key
                || cached.updated_at != updated_at
                || cached.document_ord_fingerprint != document_ord_fingerprint
                || !cached.archive_segments.contains_all(requested_mask)
            {
                continue;
            }
            match best.as_ref() {
                Some(current)
                    if current.archive_segments.bit_count()
                        <= cached.archive_segments.bit_count() => {}
                _ => best = Some(Arc::clone(cached)),
            }
        }
        Ok(best)
    }

    fn remember_document_projection(
        &self,
        projection: Arc<CachedScopeDocumentProjection>,
    ) -> Result<(), StoreError> {
        let mut cache = self.scope_runtime_document_cache.lock().map_err(|_| {
            StoreError::Query("scope runtime document cache mutex poisoned".to_owned())
        })?;
        cache.retain(|entry| {
            !(entry.scope_key == projection.scope_key
                && entry.updated_at == projection.updated_at
                && entry.document_ord_fingerprint == projection.document_ord_fingerprint
                && entry.archive_segments == projection.archive_segments)
        });
        Self::retain_cache_limit(&mut cache);
        cache.push(projection);
        Ok(())
    }

    pub(crate) fn invalidate_scope_runtime_image_cache(
        &self,
        scope_key: &str,
    ) -> Result<(), StoreError> {
        let mut cache = self.scope_runtime_image_cache.lock().map_err(|_| {
            StoreError::Query("scope runtime image cache mutex poisoned".to_owned())
        })?;
        cache.retain(|entry| entry.scope_key != scope_key);
        Ok(())
    }

    pub(crate) fn invalidate_scope_runtime_document_cache(
        &self,
        scope_key: &str,
    ) -> Result<(), StoreError> {
        let mut cache = self.scope_runtime_document_cache.lock().map_err(|_| {
            StoreError::Query("scope runtime document cache mutex poisoned".to_owned())
        })?;
        cache.retain(|entry| entry.scope_key != scope_key);
        Ok(())
    }

    pub(crate) fn invalidate_scope_runtime_caches(
        &self,
        scope_key: &str,
    ) -> Result<(), StoreError> {
        self.invalidate_scope_runtime_image_cache(scope_key)?;
        self.invalidate_scope_runtime_document_cache(scope_key)
    }

    fn load_runtime_manifests_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        dirty: &DirtyScopeRecord,
    ) -> Result<Vec<DocumentManifest>, StoreError> {
        if dirty.document_ords.is_empty() {
            return self.load_latest_document_manifests_with_engine(engine, Some(&dirty.scope));
        }

        let manifests = self.load_latest_document_manifests_for_ords_with_engine(
            engine,
            dirty.scope_ord,
            &dirty.document_ords,
        )?;
        if manifests.len() == dirty.document_ords.len() {
            return Ok(manifests);
        }

        let wanted = dirty
            .document_ords
            .iter()
            .map(|document_ord| document_ord.0)
            .collect::<BTreeSet<_>>();
        let mut fallback =
            self.load_latest_document_manifests_with_engine(engine, Some(&dirty.scope))?;
        fallback.retain(|manifest| wanted.contains(&manifest.document_ord.0));
        Ok(fallback)
    }

    fn load_projected_document_archive_from_manifest_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        manifest: &DocumentManifest,
        mask: ArchiveSegmentMask,
    ) -> Result<DocumentArchive, StoreError> {
        let mut archive = DocumentArchive {
            manifest: manifest.clone(),
            ..Default::default()
        };
        let mut lexical = None::<LexicalPostingsSegment>;

        for segment_ref in &manifest.segment_refs {
            if !mask.contains(segment_ref.kind) {
                continue;
            }

            let key = crate::segment_key(
                manifest.scope_ord,
                manifest.document_ord,
                manifest.revision,
                segment_ref.kind,
                segment_ref.ordinal,
            );
            let Some(node) = engine
                .get_node_by_key(crate::TYPE_DOCUMENT_SEGMENT, &key)
                .map_err(store_query_error)?
            else {
                return Err(StoreError::Query(format!(
                    "missing projected segment {} for {}@{}",
                    key, manifest.document_id, manifest.revision
                )));
            };
            match segment_ref.kind {
                DocumentSegmentKind::StringArena => {
                    archive.tokens = crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::SentenceTable => {
                    archive.sentences = crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::MentionTable => {
                    archive.mentions = crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::ResolverLinkTable => {
                    archive.resolver_links =
                        crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::ResolvedMentionTable => {
                    archive.resolved_mentions =
                        crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::AliasConfirmationTable => {
                    archive.alias_confirmations =
                        crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::CorefClusterTable => {
                    archive.coref_clusters =
                        crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::CausalSubstrateTable => {
                    archive.causal_substrate =
                        Some(crate::decode_segment_payload_from_node(&self.path, &node)?);
                }
                DocumentSegmentKind::TemporalSubstrateTable => {
                    archive.temporal_substrate =
                        Some(crate::decode_segment_payload_from_node(&self.path, &node)?);
                }
                DocumentSegmentKind::EventIdentitySubstrateTable => {
                    archive.event_identity_substrate =
                        Some(crate::decode_segment_payload_from_node(&self.path, &node)?);
                }
                DocumentSegmentKind::ChunkTable => {
                    archive.chunks = crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::EntityTable => {
                    archive.entities = crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::RelationTable => {
                    archive.relations = crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::EvidenceTable => {
                    archive.evidence_spans =
                        crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::LexicalPostings => {
                    lexical = Some(crate::decode_segment_payload_from_node(&self.path, &node)?);
                }
                DocumentSegmentKind::NarrativeHitTable => {
                    archive.relation_candidates =
                        crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::GraphMutation => {
                    archive.graph_batch =
                        crate::decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::StructureRelations => {
                    archive.structure =
                        Some(crate::decode_segment_payload_from_node(&self.path, &node)?);
                }
                DocumentSegmentKind::BoundaryTable => {}
            }
        }

        if let Some(lexical) = lexical {
            archive.indexed_spans = lexical.spans;
        }

        Ok(archive)
    }

    fn load_projected_document_archives_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        manifests: &[DocumentManifest],
        mask: ArchiveSegmentMask,
    ) -> Result<Vec<DocumentArchive>, StoreError> {
        manifests
            .iter()
            .map(|manifest| {
                self.load_projected_document_archive_from_manifest_with_engine(
                    engine, manifest, mask,
                )
            })
            .collect()
    }

    fn load_cached_document_projection_from_disk(
        &self,
        dirty: &DirtyScopeRecord,
        mask: ArchiveSegmentMask,
    ) -> Result<Option<ScopeDocumentProjectionCacheEntry>, StoreError> {
        let path = self.document_projection_cache_path(dirty, mask);
        if !path.exists() {
            return Ok(None);
        }
        match fs::read(&path)
            .map_err(|error| StoreError::Query(error.to_string()))
            .and_then(|bytes| decode_archive::<ScopeDocumentProjectionCacheEntry>(&bytes))
        {
            Ok(entry) => Ok(Some(entry)),
            Err(_) => {
                let _ = fs::remove_file(&path);
                Ok(None)
            }
        }
    }

    fn write_document_projection_cache_to_disk(
        &self,
        dirty: &DirtyScopeRecord,
        mask: ArchiveSegmentMask,
        manifests: &[DocumentManifest],
        archives: &[DocumentArchive],
    ) -> Result<(), StoreError> {
        let cache_dir = self.scope_runtime_cache_dir();
        fs::create_dir_all(&cache_dir).map_err(|error| StoreError::Query(error.to_string()))?;
        let path = self.document_projection_cache_path(dirty, mask);
        if path.exists() {
            return Ok(());
        }
        let bytes = encode_archive(&ScopeDocumentProjectionCacheEntry {
            manifests: manifests.to_vec(),
            archives: archives.to_vec(),
        })?;
        fs::write(path, bytes).map_err(|error| StoreError::Query(error.to_string()))
    }

    fn load_cached_runtime_image_from_disk(
        &self,
        dirty: &DirtyScopeRecord,
        spec: ScopeImageSpec,
    ) -> Result<Option<ScopeRuntimeImage>, StoreError> {
        let path = self.scope_runtime_image_cache_path(dirty, spec);
        if !path.exists() {
            return Ok(None);
        }
        let entry = match fs::read(&path)
            .map_err(|error| StoreError::Query(error.to_string()))
            .and_then(|bytes| decode_runtime_image_cache_entry(&bytes))
        {
            Ok(entry) => entry,
            Err(_) => {
                let _ = fs::remove_file(&path);
                return Ok(None);
            }
        };
        let indices = self.build_scope_runtime_indices(&entry.manifests);
        Ok(Some(ScopeRuntimeImage {
            dirty: entry.dirty,
            manifests: Arc::from(entry.manifests),
            archives: Arc::from(entry.archives),
            sidecars: Arc::new(entry.sidecars),
            indices: Arc::new(indices),
            archive_segments: spec.archive_segments,
            sidecar_mask: spec.sidecars,
        }))
    }

    fn load_cached_runtime_image_from_disk_with_telemetry(
        &self,
        dirty: &DirtyScopeRecord,
        spec: ScopeImageSpec,
        telemetry: &mut ScopeRuntimeLoadTelemetry,
    ) -> Result<Option<ScopeRuntimeImage>, StoreError> {
        let path_started = Instant::now();
        let path = self.scope_runtime_image_cache_path(dirty, spec);
        let path_exists = path.exists();
        telemetry.runtime_disk_path_check_us += elapsed_us(path_started);
        if !path_exists {
            return Ok(None);
        }

        let read_started = Instant::now();
        let bytes = match fs::read(&path) {
            Ok(bytes) => bytes,
            Err(_) => {
                telemetry.runtime_disk_read_us += elapsed_us(read_started);
                let _ = fs::remove_file(&path);
                return Ok(None);
            }
        };
        telemetry.runtime_disk_read_us += elapsed_us(read_started);
        telemetry.runtime_disk_read_bytes += bytes.len() as u64;

        let decode_started = Instant::now();
        let entry = match decode_runtime_image_cache_entry(&bytes) {
            Ok(entry) => entry,
            Err(_) => {
                telemetry.runtime_disk_decode_us += elapsed_us(decode_started);
                telemetry.runtime_disk_decode_error_count += 1;
                let _ = fs::remove_file(&path);
                return Ok(None);
            }
        };
        telemetry.runtime_disk_decode_us += elapsed_us(decode_started);

        let index_started = Instant::now();
        let indices = self.build_scope_runtime_indices(&entry.manifests);
        telemetry.runtime_disk_index_build_us += elapsed_us(index_started);

        let wrap_started = Instant::now();
        let image = ScopeRuntimeImage {
            dirty: entry.dirty,
            manifests: Arc::from(entry.manifests),
            archives: Arc::from(entry.archives),
            sidecars: Arc::new(entry.sidecars),
            indices: Arc::new(indices),
            archive_segments: spec.archive_segments,
            sidecar_mask: spec.sidecars,
        };
        telemetry.runtime_disk_image_wrap_us += elapsed_us(wrap_started);
        Ok(Some(image))
    }

    fn write_runtime_image_cache_to_disk(
        &self,
        image: &ScopeRuntimeImage,
    ) -> Result<(), StoreError> {
        let cache_dir = self.scope_runtime_cache_dir();
        fs::create_dir_all(&cache_dir).map_err(|error| StoreError::Query(error.to_string()))?;
        let path = self.scope_runtime_image_cache_path(
            &image.dirty,
            ScopeImageSpec {
                archive_segments: image.archive_segments,
                sidecars: image.sidecar_mask,
            },
        );
        if path.exists() {
            return Ok(());
        }
        let bytes = encode_runtime_image_cache_entry(&ScopeRuntimeImageCacheEntry {
            dirty: image.dirty.clone(),
            manifests: image.manifests.to_vec(),
            archives: image.archives.to_vec(),
            sidecars: image.sidecars.as_ref().clone(),
        })?;
        fs::write(path, bytes).map_err(|error| StoreError::Query(error.to_string()))
    }

    fn synthesize_scope_runtime_record(
        &self,
        scope: &ScopeKey,
        manifests: &[DocumentManifest],
    ) -> Option<DirtyScopeRecord> {
        let first = manifests.first()?;
        let mut document_ords = manifests
            .iter()
            .map(|manifest| manifest.document_ord)
            .collect::<Vec<_>>();
        document_ords.sort_unstable_by_key(|document_ord| document_ord.0);
        document_ords.dedup_by_key(|document_ord| document_ord.0);
        let updated_at = manifests
            .iter()
            .map(|manifest| manifest.created_at)
            .max()
            .unwrap_or_default();
        Some(DirtyScopeRecord {
            scope: scope.clone(),
            scope_key: first.scope_key.clone(),
            scope_ord: first.scope_ord,
            document_ords,
            updated_at,
        })
    }

    fn load_scope_sidecar_bundle_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        dirty: &DirtyScopeRecord,
        spec: ScopeImageSpec,
    ) -> Result<ScopeSidecarBundle, StoreError> {
        let mut bundle = ScopeSidecarBundle::default();
        if spec.sidecars.includes_lexical() {
            bundle.lexical = self.load_native_scope_sidecar_with_engine(engine, &dirty.scope)?;
        }
        if spec.sidecars.includes_er() {
            bundle.er = self.load_native_er_patch_sidecar_with_engine(engine, &dirty.scope)?;
        }
        if spec.sidecars.includes_relation() {
            bundle.relation =
                self.load_native_relation_patch_sidecar_with_engine(engine, &dirty.scope)?;
        }
        if spec.sidecars.includes_memory() {
            bundle.memory =
                self.load_native_memory_patch_sidecar_with_engine(engine, &dirty.scope)?;
        }
        if spec.sidecars.includes_event_identity() {
            bundle.event_identity =
                self.load_native_event_identity_patch_sidecar_with_engine(engine, &dirty.scope)?;
        }
        if spec.sidecars.includes_state_schema() {
            bundle.state_schema =
                self.load_native_state_schema_patch_sidecar_with_engine(engine, &dirty.scope)?;
        }
        if spec.sidecars.includes_causal() {
            bundle.causal =
                self.load_native_causal_patch_sidecar_with_engine(engine, &dirty.scope)?;
        }
        if spec.sidecars.includes_temporal() {
            bundle.temporal =
                self.load_native_temporal_patch_sidecar_with_engine(engine, &dirty.scope)?;
        }
        if spec.sidecars.includes_graph() {
            bundle.graph =
                self.load_native_graph_patch_sidecar_with_engine(engine, &dirty.scope)?;
        }
        if spec.sidecars.includes_semantic_graph() {
            bundle.semantic_graph =
                self.load_native_semantic_graph_patch_sidecar_with_engine(engine, &dirty.scope)?;
        }
        if spec.sidecars.includes_relation_seed() {
            bundle.relation_seed =
                self.load_native_relation_mention_seed_sidecar_with_engine(engine, &dirty.scope)?;
        }
        Ok(bundle)
    }

    fn build_scope_runtime_indices(&self, manifests: &[DocumentManifest]) -> ScopeRuntimeIndices {
        let document_ids = manifests
            .iter()
            .map(|manifest| manifest.document_id.clone())
            .collect::<Vec<_>>()
            .into();
        let document_created_at = manifests
            .iter()
            .map(|manifest| (manifest.document_id.clone(), manifest.created_at))
            .collect::<BTreeMap<_, _>>();
        ScopeRuntimeIndices {
            document_ids,
            document_created_at,
        }
    }

    fn load_or_build_document_projection_from_manifests_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        dirty: &DirtyScopeRecord,
        manifests: Vec<DocumentManifest>,
        mask: ArchiveSegmentMask,
    ) -> Result<Arc<CachedScopeDocumentProjection>, StoreError> {
        if let Some(cached) = self.load_cached_document_projection(dirty, mask)? {
            return Ok(cached);
        }

        if let Some(disk_cached) = self.load_cached_document_projection_from_disk(dirty, mask)? {
            let indices = self.build_scope_runtime_indices(&disk_cached.manifests);
            let (scope_key, updated_at, document_ord_fingerprint) =
                Self::runtime_cache_key_parts(dirty);
            let projection = Arc::new(CachedScopeDocumentProjection {
                scope_key,
                updated_at,
                document_ord_fingerprint,
                archive_segments: mask,
                manifests: Arc::from(disk_cached.manifests),
                archives: Arc::from(disk_cached.archives),
                indices: Arc::new(indices),
            });
            self.remember_document_projection(Arc::clone(&projection))?;
            return Ok(projection);
        }

        let archives =
            self.load_projected_document_archives_with_engine(engine, &manifests, mask)?;
        let indices = self.build_scope_runtime_indices(&manifests);
        self.write_document_projection_cache_to_disk(dirty, mask, &manifests, &archives)?;
        let (scope_key, updated_at, document_ord_fingerprint) =
            Self::runtime_cache_key_parts(dirty);
        let projection = Arc::new(CachedScopeDocumentProjection {
            scope_key,
            updated_at,
            document_ord_fingerprint,
            archive_segments: mask,
            manifests: Arc::from(manifests),
            archives: Arc::from(archives),
            indices: Arc::new(indices),
        });
        self.remember_document_projection(Arc::clone(&projection))?;
        Ok(projection)
    }

    fn load_or_build_document_projection_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        dirty: &DirtyScopeRecord,
        mask: ArchiveSegmentMask,
    ) -> Result<Arc<CachedScopeDocumentProjection>, StoreError> {
        if let Some(cached) = self.load_cached_document_projection(dirty, mask)? {
            return Ok(cached);
        }

        let manifests = self.load_runtime_manifests_with_engine(engine, dirty)?;
        self.load_or_build_document_projection_from_manifests_with_engine(
            engine, dirty, manifests, mask,
        )
    }

    fn load_scope_runtime_image_from_manifests_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
        manifests: Vec<DocumentManifest>,
        spec: ScopeImageSpec,
    ) -> Result<Option<ScopeRuntimeImage>, StoreError> {
        let Some(dirty) = self.synthesize_scope_runtime_record(scope, &manifests) else {
            return Ok(None);
        };
        if let Some(cached) = self.load_cached_runtime_image(&dirty, spec)? {
            return Ok(Some(cached));
        }
        if let Some(cached) = self.load_cached_runtime_image_from_disk(&dirty, spec)? {
            return self.remember_runtime_image(&dirty, spec, cached).map(Some);
        }

        let documents = self.load_or_build_document_projection_from_manifests_with_engine(
            engine,
            &dirty,
            manifests,
            spec.archive_segments,
        )?;
        let sidecars = self.load_scope_sidecar_bundle_with_engine(engine, &dirty, spec)?;
        let image = ScopeRuntimeImage {
            dirty: dirty.clone(),
            manifests: Arc::clone(&documents.manifests),
            archives: Arc::clone(&documents.archives),
            sidecars: Arc::new(sidecars),
            indices: Arc::clone(&documents.indices),
            archive_segments: documents.archive_segments,
            sidecar_mask: spec.sidecars,
        };
        self.write_runtime_image_cache_to_disk(&image)?;
        self.remember_runtime_image(&dirty, spec, image).map(Some)
    }

    fn load_scope_runtime_image_from_manifests_with_telemetry(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
        manifests: Vec<DocumentManifest>,
        spec: ScopeImageSpec,
        telemetry: &mut ScopeRuntimeLoadTelemetry,
    ) -> Result<Option<ScopeRuntimeImage>, StoreError> {
        let Some(dirty) = self.synthesize_scope_runtime_record(scope, &manifests) else {
            return Ok(None);
        };
        telemetry.scope_count += 1;

        let memory_started = Instant::now();
        if let Some(cached) = self.load_cached_runtime_image(&dirty, spec)? {
            telemetry.runtime_memory_cache_lookup_us += elapsed_us(memory_started);
            telemetry.runtime_memory_cache_hit_count += 1;
            return Ok(Some(cached));
        }
        telemetry.runtime_memory_cache_lookup_us += elapsed_us(memory_started);

        let disk_started = Instant::now();
        if let Some(cached) =
            self.load_cached_runtime_image_from_disk_with_telemetry(&dirty, spec, telemetry)?
        {
            telemetry.runtime_disk_cache_lookup_us += elapsed_us(disk_started);
            telemetry.runtime_disk_cache_hit_count += 1;

            let remember_started = Instant::now();
            let remembered = self.remember_runtime_image(&dirty, spec, cached).map(Some);
            telemetry.runtime_remember_us += elapsed_us(remember_started);
            return remembered;
        }
        telemetry.runtime_disk_cache_lookup_us += elapsed_us(disk_started);
        telemetry.runtime_cache_miss_count += 1;

        let projection_started = Instant::now();
        let documents = self.load_or_build_document_projection_from_manifests_with_engine(
            engine,
            &dirty,
            manifests,
            spec.archive_segments,
        )?;
        telemetry.document_projection_us += elapsed_us(projection_started);

        let sidecar_started = Instant::now();
        let sidecars = self.load_scope_sidecar_bundle_with_engine(engine, &dirty, spec)?;
        telemetry.sidecar_bundle_us += elapsed_us(sidecar_started);

        let image = ScopeRuntimeImage {
            dirty: dirty.clone(),
            manifests: Arc::clone(&documents.manifests),
            archives: Arc::clone(&documents.archives),
            sidecars: Arc::new(sidecars),
            indices: Arc::clone(&documents.indices),
            archive_segments: documents.archive_segments,
            sidecar_mask: spec.sidecars,
        };

        let write_started = Instant::now();
        self.write_runtime_image_cache_to_disk(&image)?;
        telemetry.runtime_cache_write_us += elapsed_us(write_started);

        let remember_started = Instant::now();
        let remembered = self.remember_runtime_image(&dirty, spec, image).map(Some);
        telemetry.runtime_remember_us += elapsed_us(remember_started);
        remembered
    }
}

impl PhoenixScopeRuntimeStore for PhoenixOvergraphStore {
    fn load_scope_runtime_image(
        &self,
        dirty: &DirtyScopeRecord,
        spec: ScopeImageSpec,
    ) -> Result<ScopeRuntimeImage, StoreError> {
        if let Some(cached) = self.load_cached_runtime_image(dirty, spec)? {
            return Ok(cached);
        }
        if let Some(cached) = self.load_cached_runtime_image_from_disk(dirty, spec)? {
            return self.remember_runtime_image(dirty, spec, cached);
        }

        let documents = self.with_engine(|engine| {
            self.load_or_build_document_projection_with_engine(engine, dirty, spec.archive_segments)
        })?;
        let sidecars = self.with_engine(|engine| {
            self.load_scope_sidecar_bundle_with_engine(engine, dirty, spec)
        })?;

        let image = ScopeRuntimeImage {
            dirty: dirty.clone(),
            manifests: Arc::clone(&documents.manifests),
            archives: Arc::clone(&documents.archives),
            sidecars: Arc::new(sidecars),
            indices: Arc::clone(&documents.indices),
            archive_segments: documents.archive_segments,
            sidecar_mask: spec.sidecars,
        };
        self.write_runtime_image_cache_to_disk(&image)?;
        self.remember_runtime_image(dirty, spec, image)
    }

    fn load_scope_runtime_image_for_scope(
        &self,
        scope: &ScopeKey,
        spec: ScopeImageSpec,
    ) -> Result<Option<ScopeRuntimeImage>, StoreError> {
        self.with_engine(|engine| {
            let manifests = self.load_latest_document_manifests_with_engine(engine, Some(scope))?;
            self.load_scope_runtime_image_from_manifests_with_engine(engine, scope, manifests, spec)
        })
    }

    fn load_scope_runtime_images(
        &self,
        spec: ScopeImageSpec,
    ) -> Result<Vec<ScopeRuntimeImage>, StoreError> {
        self.with_engine(|engine| {
            let mut grouped = BTreeMap::<String, (ScopeKey, Vec<DocumentManifest>)>::new();
            for manifest in self.load_latest_document_manifests_with_engine(engine, None)? {
                let entry = grouped
                    .entry(manifest.scope_key.clone())
                    .or_insert_with(|| (manifest.scope.clone(), Vec::new()));
                entry.1.push(manifest);
            }

            let mut images = Vec::with_capacity(grouped.len());
            for (_scope_key, (scope, manifests)) in grouped {
                if let Some(image) = self.load_scope_runtime_image_from_manifests_with_engine(
                    engine, &scope, manifests, spec,
                )? {
                    images.push(image);
                }
            }
            Ok(images)
        })
    }
}

fn elapsed_us(started: Instant) -> u64 {
    started.elapsed().as_micros() as u64
}
