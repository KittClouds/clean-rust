use std::cell::RefCell;
use std::fs::{self, File};
use std::hash::{Hash, Hasher};
use std::io::Write;
use std::path::{Path, PathBuf};

use hashbrown::HashMap;
use memmap2::Mmap;
use phoenix_embed::{OrtTextEmbedConfig, OrtTextEmbedder};
use rustc_hash::FxHasher;

use crate::semantic::{
    ensure_ort_dylib_path, SemanticEmbedConfig, SemanticEmbeddingBatch, SemanticNeighborError,
};

const CACHE_MAGIC: &[u8; 8] = b"PXEMB001";
const CACHE_HEADER_LEN: usize = 8 + 4 + 8 + 8;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct EmbedderCacheKey {
    model_root: PathBuf,
    batch_size: usize,
    max_length: usize,
    profile: &'static str,
    execution_provider: &'static str,
}

#[derive(Default)]
struct ThreadEmbedderCache {
    embedders: HashMap<EmbedderCacheKey, OrtTextEmbedder>,
}

thread_local! {
    static EMBEDDER_CACHE: RefCell<ThreadEmbedderCache> =
        RefCell::new(ThreadEmbedderCache::default());
}

pub(crate) fn clear_semantic_embedder_cache() {
    EMBEDDER_CACHE.with(|cell| cell.borrow_mut().embedders.clear());
}

pub(crate) fn embed_texts_flat_cached(
    config: &SemanticEmbedConfig,
    texts: &[&str],
) -> Result<SemanticEmbeddingBatch, SemanticNeighborError> {
    let dims = config.profile.target_dim();
    let mut values = vec![0.0; texts.len().saturating_mul(dims)];
    let mut misses = Vec::<usize>::new();
    let mut miss_texts = Vec::<&str>::new();
    let cache_namespace = config.embedding_cache_dir.as_ref().map(|cache_dir| {
        let namespace = semantic_cache_namespace(config);
        cache_dir.join("semantic-emb-v1").join(namespace)
    });

    if let Some(cache_dir) = cache_namespace.as_ref() {
        for (index, text) in texts.iter().copied().enumerate() {
            let row = &mut values[index * dims..(index + 1) * dims];
            if read_cached_embedding(cache_dir, text, dims, row).is_err() {
                misses.push(index);
                miss_texts.push(text);
            }
        }
    } else {
        misses.extend(0..texts.len());
        miss_texts.extend(texts.iter().copied());
    }

    if !miss_texts.is_empty() {
        let embedded =
            with_semantic_embedder(config, |embedder| embedder.embed_slices_flat(&miss_texts))?;
        if embedded.rows() != miss_texts.len() || embedded.dims() != dims {
            return Err(SemanticNeighborError::Cache(format!(
                "cached semantic embedding batch shape mismatch: expected {} rows x {} dims, got {} rows x {} dims",
                miss_texts.len(),
                dims,
                embedded.rows(),
                embedded.dims()
            )));
        }
        for (miss_offset, &prototype_index) in misses.iter().enumerate() {
            let row = embedded.row(miss_offset).ok_or_else(|| {
                SemanticNeighborError::Cache(format!("missing embedded row {miss_offset}"))
            })?;
            let target = &mut values[prototype_index * dims..(prototype_index + 1) * dims];
            target.copy_from_slice(row);
            if let Some(cache_dir) = cache_namespace.as_ref() {
                let _ = write_cached_embedding(cache_dir, miss_texts[miss_offset], row);
            }
        }
    }

    Ok(SemanticEmbeddingBatch {
        values,
        rows: texts.len(),
        dims,
        cache_hits: texts.len().saturating_sub(misses.len()),
        cache_misses: misses.len(),
    })
}

fn with_semantic_embedder<R>(
    config: &SemanticEmbedConfig,
    f: impl FnOnce(&OrtTextEmbedder) -> Result<R, phoenix_embed::OrtTextEmbedError>,
) -> Result<R, SemanticNeighborError> {
    let key = EmbedderCacheKey {
        model_root: config.model_root.clone(),
        batch_size: config.batch_size.max(1),
        max_length: config.max_length,
        profile: config.profile.label(),
        execution_provider: config.execution_provider().label(),
    };
    EMBEDDER_CACHE.with(|cell| {
        let mut cache = cell.borrow_mut();
        if !cache.embedders.contains_key(&key) {
            let _ = ensure_ort_dylib_path();
            let embedder = OrtTextEmbedder::load(&OrtTextEmbedConfig {
                model_root: config.model_root.clone(),
                batch_size: config.batch_size,
                max_length: config.max_length,
                profile: config.profile,
                prefix_passage: true,
                pooling: Default::default(),
                input_prefix: Default::default(),
                execution_provider: config.execution_provider(),
            })?;
            cache.embedders.insert(key.clone(), embedder);
        }
        let embedder = cache
            .embedders
            .get(&key)
            .ok_or_else(|| SemanticNeighborError::Cache("semantic embedder unavailable".into()))?;
        Ok(f(embedder)?)
    })
}

fn semantic_cache_namespace(config: &SemanticEmbedConfig) -> String {
    let mut hasher = FxHasher::default();
    config.model_id.hash(&mut hasher);
    config.model_root.hash(&mut hasher);
    config.profile.label().hash(&mut hasher);
    config.max_length.hash(&mut hasher);
    "passage-prefix".hash(&mut hasher);
    "pooling-default".hash(&mut hasher);
    format!("{:016x}", hasher.finish())
}

fn cache_row_path(cache_dir: &Path, text: &str) -> PathBuf {
    let hash = fnv1a64(text.as_bytes());
    let shard = (hash & 0xff) as u8;
    cache_dir
        .join(format!("{shard:02x}"))
        .join(format!("{hash:016x}-{}.bin", text.len()))
}

fn read_cached_embedding(
    cache_dir: &Path,
    text: &str,
    dims: usize,
    out: &mut [f32],
) -> Result<(), SemanticNeighborError> {
    if out.len() != dims {
        return Err(SemanticNeighborError::Cache(
            "cache output row mismatch".into(),
        ));
    }
    let path = cache_row_path(cache_dir, text);
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file)? };
    let expected_len = CACHE_HEADER_LEN + dims.saturating_mul(4);
    if mmap.len() != expected_len || mmap.get(..8) != Some(CACHE_MAGIC.as_slice()) {
        return Err(SemanticNeighborError::Cache(
            "cache row header mismatch".into(),
        ));
    }
    let cached_dims = read_u32(&mmap[8..12]) as usize;
    let cached_len = read_u64(&mmap[12..20]) as usize;
    let cached_hash = read_u64(&mmap[20..28]);
    if cached_dims != dims || cached_len != text.len() || cached_hash != fnv1a64(text.as_bytes()) {
        return Err(SemanticNeighborError::Cache(
            "cache row key mismatch".into(),
        ));
    }
    let mut offset = CACHE_HEADER_LEN;
    for value in out {
        *value = read_f32(&mmap[offset..offset + 4]);
        offset += 4;
    }
    Ok(())
}

fn write_cached_embedding(
    cache_dir: &Path,
    text: &str,
    row: &[f32],
) -> Result<(), SemanticNeighborError> {
    let path = cache_row_path(cache_dir, text);
    if path.exists() {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension(format!("tmp-{}", std::process::id()));
    let mut file = File::create(&tmp)?;
    file.write_all(CACHE_MAGIC)?;
    file.write_all(&(row.len() as u32).to_le_bytes())?;
    file.write_all(&(text.len() as u64).to_le_bytes())?;
    file.write_all(&fnv1a64(text.as_bytes()).to_le_bytes())?;
    for value in row {
        file.write_all(&value.to_le_bytes())?;
    }
    file.flush()?;
    drop(file);
    match fs::rename(&tmp, &path) {
        Ok(()) => Ok(()),
        Err(error) if path.exists() => {
            let _ = fs::remove_file(&tmp);
            let _ = error;
            Ok(())
        }
        Err(error) => Err(error.into()),
    }
}

fn read_u32(bytes: &[u8]) -> u32 {
    u32::from_le_bytes(bytes.try_into().unwrap_or([0; 4]))
}

fn read_u64(bytes: &[u8]) -> u64 {
    u64::from_le_bytes(bytes.try_into().unwrap_or([0; 8]))
}

fn read_f32(bytes: &[u8]) -> f32 {
    f32::from_le_bytes(bytes.try_into().unwrap_or([0; 4]))
}

fn fnv1a64(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}
