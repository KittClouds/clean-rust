use phoenix_semantic_v2::{scope_storage_key, ScopeLexSidecar};
use phoenix_store_native_core::{PhoenixArchiveStoreV2, PhoenixLexicalQueryStore};
use phoenix_types::{IndexedSpan, IndexedTextField, LexicalField, ScopeKey};

use crate::*;

fn temp_store(name: &str) -> PhoenixOvergraphStore {
    let path = std::env::temp_dir().join(format!(
        "phoenix-overgraph-lexical-query-{name}-{}-{}",
        std::process::id(),
        now_ms()
    ));
    let _ = std::fs::remove_dir_all(&path);
    PhoenixOvergraphStore::open(&path).expect("open overgraph store")
}

#[test]
fn lexical_query_sidecar_persists_and_mmaps_chunk_index() {
    let store = temp_store("persist-and-mmap");
    store.init_archive_schema().expect("init archive schema");

    let scope = ScopeKey::default();
    let scope_key = scope_storage_key(&scope);
    store
        .with_engine(|engine| {
            let scope_ord = store.ensure_scope_ord(engine, &scope_key)?;
            store.persist_scope_sidecar_native_with_engine(
                engine,
                &ScopeLexSidecar {
                    scope: scope.clone(),
                    scope_key: scope_key.clone(),
                    scope_ord: Some(scope_ord),
                    spans: vec![IndexedSpan {
                        span_id: "graph::chunk::1".to_owned(),
                        note_id: None,
                        document_id: None,
                        scope: scope.clone(),
                        fields: vec![
                            IndexedTextField {
                                field: LexicalField::Title,
                                text: "Harbor Report".to_owned(),
                            },
                            IndexedTextField {
                                field: LexicalField::Body,
                                text: "Alice moved to the harbor and stayed there.".to_owned(),
                            },
                        ],
                    }],
                    alias_entries: Vec::new(),
                    document_ids: vec!["doc-1".to_owned()],
                    entity_count: 0,
                    generated_at: 11,
                    generation: 11,
                },
            )
        })
        .expect("persist lexical scope sidecar");

    let sidecar = store
        .load_scope_lexical_query_sidecar(&scope)
        .expect("load lexical query sidecar")
        .expect("lexical query sidecar present");

    assert!(sidecar.index_path.exists(), "expected persisted bm25 index");
    assert_eq!(sidecar.docs.len(), 1);
    assert_eq!(sidecar.docs[0].node_id, "graph::chunk::1");
    assert_eq!(sidecar.docs[0].node_kind, "chunk");

    let mmap_index =
        bm25_turbo::persistence::load_mmap(&sidecar.index_path).expect("load mmap bm25");
    let results = mmap_index.search("harbor", 4).expect("query mmap bm25");

    assert_eq!(results.doc_ids, vec![0]);
}
