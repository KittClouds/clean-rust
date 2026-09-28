use std::fs;
use std::path::{Path, PathBuf};

use bm25_turbo::{persistence, BM25Builder};
use phoenix_store_native_core::{
    PhoenixArchiveStoreV2, PhoenixLexicalQueryStore, ScopeLexicalQueryDoc,
    ScopeLexicalQuerySidecar, StoreError,
};
use phoenix_types::{IndexedSpan, LexicalField, ScopeKey};
use serde::{Deserialize, Serialize};

use crate::PhoenixOvergraphStore;

const LEXICAL_QUERY_META_VERSION: u32 = 1;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ScopeLexicalQueryCacheEntry {
    scope: ScopeKey,
    scope_key: String,
    generation: u64,
    generated_at: i64,
    docs: Vec<ScopeLexicalQueryDoc>,
}

impl PhoenixOvergraphStore {
    pub(crate) fn scope_lexical_query_index_path(
        &self,
        scope_key: &str,
        generation: u64,
    ) -> PathBuf {
        self.scope_runtime_cache_dir().join(format!(
            "scope-{}-g{generation}.lexical-query.bm25",
            sanitize_scope_key(scope_key)
        ))
    }

    pub(crate) fn scope_lexical_query_meta_path(
        &self,
        scope_key: &str,
        generation: u64,
    ) -> PathBuf {
        self.scope_runtime_cache_dir().join(format!(
            "scope-{}-g{generation}.lexical-query.v{LEXICAL_QUERY_META_VERSION}.bin",
            sanitize_scope_key(scope_key)
        ))
    }

    pub(crate) fn invalidate_scope_lexical_query_cache(
        &self,
        scope_key: &str,
    ) -> Result<(), StoreError> {
        let cache_dir = self.scope_runtime_cache_dir();
        if !cache_dir.exists() {
            return Ok(());
        }
        let prefix = format!("scope-{}", sanitize_scope_key(scope_key));
        for entry in fs::read_dir(&cache_dir).map_err(io_error)? {
            let entry = entry.map_err(io_error)?;
            let file_name = entry.file_name();
            let Some(file_name) = file_name.to_str() else {
                continue;
            };
            if !file_name.starts_with(prefix.as_str()) || !file_name.contains(".lexical-query.") {
                continue;
            }
            let _ = fs::remove_file(entry.path());
        }
        Ok(())
    }

    fn load_scope_lexical_query_sidecar_impl(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<ScopeLexicalQuerySidecar>, StoreError> {
        let lexical = self.load_materialized_scope_lexical(scope)?;
        if lexical.generation == 0 || lexical.spans.is_empty() {
            return Ok(None);
        }
        let index_path =
            self.scope_lexical_query_index_path(&lexical.scope_key, lexical.generation);
        let meta_path = self.scope_lexical_query_meta_path(&lexical.scope_key, lexical.generation);
        if index_path.exists() && meta_path.exists() {
            if let Some(cached) = load_query_cache_entry(&meta_path)? {
                if cached.scope_key == lexical.scope_key && cached.generation == lexical.generation
                {
                    return Ok(Some(ScopeLexicalQuerySidecar {
                        scope: lexical.scope.clone(),
                        scope_key: lexical.scope_key.clone(),
                        generation: lexical.generation,
                        generated_at: cached.generated_at,
                        index_path,
                        docs: cached.docs,
                    }));
                }
            }
        }
        build_scope_lexical_query_sidecar(self, &lexical, index_path, meta_path).map(Some)
    }
}

impl PhoenixLexicalQueryStore for PhoenixOvergraphStore {
    fn load_scope_lexical_query_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<ScopeLexicalQuerySidecar>, StoreError> {
        self.load_scope_lexical_query_sidecar_impl(scope)
    }
}

fn build_scope_lexical_query_sidecar(
    store: &PhoenixOvergraphStore,
    lexical: &phoenix_semantic_v2::ScopeLexSidecar,
    index_path: PathBuf,
    meta_path: PathBuf,
) -> Result<ScopeLexicalQuerySidecar, StoreError> {
    let mut corpus = Vec::<String>::with_capacity(lexical.spans.len());
    let mut docs = Vec::<ScopeLexicalQueryDoc>::with_capacity(lexical.spans.len());
    for span in &lexical.spans {
        let Some(text) = lexical_query_text(span) else {
            continue;
        };
        corpus.push(text);
        docs.push(scope_lexical_query_doc(span));
    }
    if corpus.is_empty() {
        return Ok(ScopeLexicalQuerySidecar {
            scope: lexical.scope.clone(),
            scope_key: lexical.scope_key.clone(),
            generation: lexical.generation,
            generated_at: lexical.generated_at,
            index_path,
            docs,
        });
    }

    fs::create_dir_all(store.scope_runtime_cache_dir()).map_err(io_error)?;
    if index_path.exists() {
        let _ = fs::remove_file(&index_path);
    }
    if meta_path.exists() {
        let _ = fs::remove_file(&meta_path);
    }
    let corpus_refs = corpus.iter().map(String::as_str).collect::<Vec<_>>();
    let index = BM25Builder::new()
        .cache_capacity(64)
        .build_from_corpus(&corpus_refs)
        .map_err(bm25_error)?;
    persistence::save(&index, &index_path).map_err(bm25_error)?;
    write_query_cache_entry(
        &meta_path,
        &ScopeLexicalQueryCacheEntry {
            scope: lexical.scope.clone(),
            scope_key: lexical.scope_key.clone(),
            generation: lexical.generation,
            generated_at: lexical.generated_at,
            docs: docs.clone(),
        },
    )?;
    Ok(ScopeLexicalQuerySidecar {
        scope: lexical.scope.clone(),
        scope_key: lexical.scope_key.clone(),
        generation: lexical.generation,
        generated_at: lexical.generated_at,
        index_path,
        docs,
    })
}

fn load_query_cache_entry(path: &Path) -> Result<Option<ScopeLexicalQueryCacheEntry>, StoreError> {
    if !path.exists() {
        return Ok(None);
    }
    match fs::read(path)
        .map_err(io_error)
        .and_then(|bytes| crate::decode_archive::<ScopeLexicalQueryCacheEntry>(&bytes))
    {
        Ok(entry) => Ok(Some(entry)),
        Err(_) => {
            let _ = fs::remove_file(path);
            Ok(None)
        }
    }
}

fn write_query_cache_entry(
    path: &Path,
    entry: &ScopeLexicalQueryCacheEntry,
) -> Result<(), StoreError> {
    let bytes = crate::encode_archive(entry)?;
    let temp_path = path.with_extension("tmp");
    if path.exists() {
        let _ = fs::remove_file(path);
    }
    fs::write(&temp_path, bytes).map_err(io_error)?;
    fs::rename(temp_path, path).map_err(io_error)
}

fn scope_lexical_query_doc(span: &IndexedSpan) -> ScopeLexicalQueryDoc {
    ScopeLexicalQueryDoc {
        node_id: span.span_id.clone(),
        node_kind: infer_node_kind(span.span_id.as_str()),
        document_id: span.document_id.as_ref().map(|value| value.0.clone()),
        evidence_refs: vec![format!("graph_vertex:{}", span.span_id)],
    }
}

fn infer_node_kind(span_id: &str) -> String {
    if let Some(rest) = span_id.strip_prefix("graph::") {
        if let Some((kind, _)) = rest.split_once("::") {
            return kind.to_owned();
        }
    }
    match span_id.split_once(':').map(|(kind, _)| kind) {
        Some("chunk") => "chunk".to_owned(),
        Some("note") => "note".to_owned(),
        Some("block") => "block".to_owned(),
        _ => "chunk".to_owned(),
    }
}

fn lexical_query_text(span: &IndexedSpan) -> Option<String> {
    let mut fields = span.fields.iter().collect::<Vec<_>>();
    fields.sort_by_key(|field| lexical_field_rank(&field.field));

    let mut text = String::new();
    for field in fields {
        let value = field.text.trim();
        if value.is_empty() {
            continue;
        }
        if !text.is_empty() {
            text.push('\n');
        }
        text.push_str(value);
        if matches!(field.field, LexicalField::Title) {
            text.push('\n');
            text.push_str(value);
        }
    }
    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

fn lexical_field_rank(field: &LexicalField) -> u8 {
    match field {
        LexicalField::Title => 0,
        LexicalField::Summary => 1,
        LexicalField::Tags => 2,
        LexicalField::Body => 3,
        LexicalField::Other => 4,
    }
}

fn sanitize_scope_key(scope_key: &str) -> String {
    let mut sanitized = String::with_capacity(scope_key.len());
    for ch in scope_key.chars() {
        if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
            sanitized.push(ch);
        } else {
            sanitized.push('_');
        }
    }
    sanitized
}

fn io_error(error: std::io::Error) -> StoreError {
    StoreError::Query(error.to_string())
}

fn bm25_error(error: bm25_turbo::Error) -> StoreError {
    StoreError::Query(error.to_string())
}
