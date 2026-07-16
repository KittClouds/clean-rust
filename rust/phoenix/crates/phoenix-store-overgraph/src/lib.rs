use std::cell::{Cell, RefCell};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use overgraph::{DatabaseEngine, DbOptions, EngineError, NodeInput, PropValue};
use phoenix_store_native::{
    relation_spec, snapshot_relations_for_partition, PhoenixNativeRowStore,
    NATIVE_COVERED_RELATIONS,
};
use phoenix_store_native_core::{SnapshotEnvelope, SnapshotPartition, StoreError};
use serde_json::Value;

const ROW_JSON_PROP: &str = "row_json";
const RELATION_PROP: &str = "relation";
const RELATION_TYPE_BASE: u32 = 50_000;
const AUTO_FLUSH_LOGICAL_BYTES: usize = 8 * 1024 * 1024;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OvergraphFlushReport {
    pub flushed: bool,
    pub wal_bytes_before: u64,
    pub wal_bytes_after: u64,
    pub segment_count: usize,
}

pub struct PhoenixOvergraphStore {
    path: PathBuf,
    engine: RefCell<DatabaseEngine>,
    logical_bytes_since_flush: Cell<usize>,
    logical_flush_threshold: usize,
}

impl PhoenixOvergraphStore {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, StoreError> {
        Self::open_with_flush_threshold(path, AUTO_FLUSH_LOGICAL_BYTES)
    }

    fn open_with_flush_threshold(
        path: impl AsRef<Path>,
        logical_flush_threshold: usize,
    ) -> Result<Self, StoreError> {
        let path = path.as_ref().to_path_buf();
        std::fs::create_dir_all(&path).map_err(|error| StoreError::Init(error.to_string()))?;
        let engine =
            DatabaseEngine::open(&path, &DbOptions::default()).map_err(overgraph_init_error)?;
        Ok(Self {
            path,
            engine: RefCell::new(engine),
            logical_bytes_since_flush: Cell::new(0),
            logical_flush_threshold,
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn flush(&self) -> Result<OvergraphFlushReport, StoreError> {
        let wal_bytes_before = self.wal_bytes_on_disk()?;
        let mut engine = self.engine.borrow_mut();
        let flushed = engine.flush().map_err(overgraph_query_error)?.is_some();
        let segment_count = engine.stats().segment_count;
        drop(engine);
        self.logical_bytes_since_flush.set(0);
        Ok(OvergraphFlushReport {
            flushed,
            wal_bytes_before,
            wal_bytes_after: self.wal_bytes_on_disk()?,
            segment_count,
        })
    }

    fn record_logical_write(&self, bytes: usize) -> Result<(), StoreError> {
        let total = self.logical_bytes_since_flush.get().saturating_add(bytes);
        self.logical_bytes_since_flush.set(total);
        if self.logical_flush_threshold > 0 && total >= self.logical_flush_threshold {
            self.flush()?;
        }
        Ok(())
    }

    fn wal_bytes_on_disk(&self) -> Result<u64, StoreError> {
        let mut bytes = 0u64;
        for entry in fs_entries(&self.path)? {
            let entry = entry.map_err(|error| StoreError::Query(error.to_string()))?;
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if name.starts_with("wal_") && name.ends_with(".wal") {
                bytes = bytes.saturating_add(
                    entry
                        .metadata()
                        .map_err(|error| StoreError::Query(error.to_string()))?
                        .len(),
                );
            }
        }
        Ok(bytes)
    }
}

impl PhoenixNativeRowStore for PhoenixOvergraphStore {
    fn init_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn relation_names(&self) -> Vec<&'static str> {
        NATIVE_COVERED_RELATIONS.to_vec()
    }

    fn relation_counts(&self) -> Result<Vec<(String, usize)>, StoreError> {
        NATIVE_COVERED_RELATIONS
            .iter()
            .map(|relation| {
                let count = self.fetch_rows(relation)?.len();
                Ok(((*relation).to_owned(), count))
            })
            .collect()
    }

    fn fetch_rows(&self, relation: &str) -> Result<Vec<Value>, StoreError> {
        relation_spec(relation)?;
        let type_id = relation_type_id(relation);
        let rows = self
            .engine
            .borrow()
            .get_nodes_by_type(type_id)
            .map_err(overgraph_query_error)?
            .into_iter()
            .filter_map(|node| node.props.get(ROW_JSON_PROP).cloned())
            .map(row_from_prop)
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    fn put_row(&self, relation: &str, row: Value) -> Result<(), StoreError> {
        self.put_rows(relation, &[row])
    }

    fn put_rows(&self, relation: &str, rows: &[Value]) -> Result<(), StoreError> {
        relation_spec(relation)?;
        if rows.is_empty() {
            return Ok(());
        }
        let type_id = relation_type_id(relation);
        let mut inputs = Vec::with_capacity(rows.len());
        let mut logical_bytes = 0usize;
        for row in rows {
            let key = row_key(relation, row)?;
            let (props, row_bytes) = row_props(relation, row)?;
            logical_bytes = logical_bytes.saturating_add(key.len()).saturating_add(row_bytes);
            inputs.push(NodeInput {
                type_id,
                key,
                props,
                weight: 1.0,
                dense_vector: None,
                sparse_vector: None,
            });
        }
        self.engine
            .borrow_mut()
            .batch_upsert_nodes(&inputs)
            .map_err(overgraph_query_error)?;
        self.record_logical_write(logical_bytes)?;
        Ok(())
    }

    fn replace_relation_rows(&self, relation: &str, rows: &[Value]) -> Result<(), StoreError> {
        self.clear_relations(&[relation])?;
        self.put_rows(relation, rows)
    }

    fn delete_rows(&self, relation: &str, rows: &[Value]) -> Result<usize, StoreError> {
        relation_spec(relation)?;
        let type_id = relation_type_id(relation);
        let mut deleted = 0usize;
        let mut logical_bytes = 0usize;
        let mut engine = self.engine.borrow_mut();
        for row in rows {
            let key = row_key(relation, row)?;
            if let Some(node) = engine
                .get_node_by_key(type_id, &key)
                .map_err(overgraph_query_error)?
            {
                engine.delete_node(node.id).map_err(overgraph_query_error)?;
                deleted += 1;
                logical_bytes = logical_bytes.saturating_add(key.len() + 32);
            }
        }
        drop(engine);
        self.record_logical_write(logical_bytes)?;
        Ok(deleted)
    }

    fn clear_relations(&self, relations: &[&str]) -> Result<(), StoreError> {
        let mut engine = self.engine.borrow_mut();
        let mut deleted = 0usize;
        for relation in relations {
            relation_spec(relation)?;
            for node in engine
                .get_nodes_by_type(relation_type_id(relation))
                .map_err(overgraph_query_error)?
            {
                engine.delete_node(node.id).map_err(overgraph_query_error)?;
                deleted += 1;
            }
        }
        drop(engine);
        self.record_logical_write(deleted.saturating_mul(32))?;
        Ok(())
    }

    fn export_snapshot_partition(
        &self,
        partition: SnapshotPartition,
    ) -> Result<Vec<u8>, StoreError> {
        let mut relations = BTreeMap::new();
        for relation in snapshot_relations_for_partition(partition) {
            relations.insert((*relation).to_owned(), self.fetch_rows(relation)?);
        }
        let envelope = SnapshotEnvelope {
            schema_version: "overgraph-row-v1".to_owned(),
            relation_count: relations.len(),
            created_at: now_ms(),
            relations,
            checksum: None,
        };
        serde_json::to_vec(&envelope).map_err(|error| StoreError::Snapshot(error.to_string()))
    }

    fn import_snapshot(&self, bytes: &[u8]) -> Result<SnapshotEnvelope, StoreError> {
        let envelope: SnapshotEnvelope = serde_json::from_slice(bytes)
            .map_err(|error| StoreError::Snapshot(error.to_string()))?;
        let relation_names = envelope
            .relations
            .keys()
            .map(String::as_str)
            .collect::<Vec<_>>();
        self.clear_relations(&relation_names)?;
        for (relation, rows) in &envelope.relations {
            self.put_rows(relation, rows)?;
        }
        Ok(envelope)
    }
}

fn row_props(
    relation: &str,
    row: &Value,
) -> Result<(BTreeMap<String, PropValue>, usize), StoreError> {
    let mut props = BTreeMap::new();
    props.insert(
        RELATION_PROP.to_owned(),
        PropValue::String(relation.to_owned()),
    );
    let row_json = serde_json::to_string(row).map_err(|error| StoreError::Query(error.to_string()))?;
    let row_bytes = row_json.len();
    props.insert(ROW_JSON_PROP.to_owned(), PropValue::String(row_json));
    Ok((props, row_bytes))
}

fn fs_entries(path: &Path) -> Result<std::fs::ReadDir, StoreError> {
    std::fs::read_dir(path).map_err(|error| StoreError::Query(error.to_string()))
}

fn row_from_prop(prop: PropValue) -> Result<Value, StoreError> {
    match prop {
        PropValue::String(row) => {
            serde_json::from_str(&row).map_err(|error| StoreError::Snapshot(error.to_string()))
        }
        _ => Err(StoreError::Snapshot(
            "overgraph row payload was not JSON".to_owned(),
        )),
    }
}

fn row_key(relation: &str, row: &Value) -> Result<String, StoreError> {
    let object = row.as_object().ok_or(StoreError::InvalidRow)?;
    let spec = relation_spec(relation)?;
    let mut key = String::with_capacity(relation.len() + 32);
    key.push_str(relation);
    for column in spec.key_columns() {
        let value = object
            .get(column.name)
            .ok_or_else(|| StoreError::MissingColumn {
                relation: relation.to_owned(),
                column: column.name.to_owned(),
            })?;
        key.push('\x1f');
        key.push_str(column.name);
        key.push('=');
        push_stable_json(&mut key, value)?;
    }
    Ok(key)
}

fn push_stable_json(out: &mut String, value: &Value) -> Result<(), StoreError> {
    if let Some(text) = value.as_str() {
        out.push_str(text);
    } else {
        out.push_str(
            &serde_json::to_string(value).map_err(|error| StoreError::Query(error.to_string()))?,
        );
    }
    Ok(())
}

fn relation_type_id(relation: &str) -> u32 {
    RELATION_TYPE_BASE + (fnv1a32(relation.as_bytes()) % 1_000_000)
}

fn fnv1a32(bytes: &[u8]) -> u32 {
    let mut hash = 0x811c9dc5u32;
    for byte in bytes {
        hash ^= u32::from(*byte);
        hash = hash.wrapping_mul(0x01000193);
    }
    hash
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_millis() as i64)
        .unwrap_or_default()
}

fn overgraph_init_error(error: EngineError) -> StoreError {
    StoreError::Init(format!("overgraph: {error}"))
}

fn overgraph_query_error(error: EngineError) -> StoreError {
    StoreError::Query(format!("overgraph: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn overgraph_row_store_round_trips_and_deletes_rows() {
        let path = std::env::temp_dir().join(format!("phoenix-overgraph-test-{}", now_ms()));
        let store = PhoenixOvergraphStore::open(&path).expect("open");
        store
            .put_row(
                "notes",
                json!({"id":"n1","version":1,"world_id":null,"narrative_id":null,"entity_kind":null,"title":"One","body":"Aella","updated_at":1,"deleted":false}),
            )
            .expect("put row");
        store
            .put_row(
                "notes",
                json!({"id":"n1","version":1,"world_id":null,"narrative_id":null,"entity_kind":null,"title":"Updated","body":"Aella","updated_at":2,"deleted":false}),
            )
            .expect("update row in place");
        assert_eq!(store.fetch_rows("notes").expect("fetch").len(), 1);
        let snapshot = store
            .export_snapshot_partition(SnapshotPartition::Content)
            .expect("export");
        store.clear_relations(&["notes"]).expect("clear");
        assert!(store.fetch_rows("notes").expect("empty").is_empty());
        store.import_snapshot(&snapshot).expect("import");
        let rows = store.fetch_rows("notes").expect("fetch restored");
        assert_eq!(rows[0]["id"], "n1");
        assert_eq!(rows[0]["title"], "Updated");
        assert_eq!(store.delete_rows("notes", &rows).expect("delete"), 1);
        assert!(store.fetch_rows("notes").expect("deleted").is_empty());
        let _ = std::fs::remove_dir_all(path);
    }

    #[test]
    fn logical_write_budget_flushes_repeated_key_updates() {
        let path = std::env::temp_dir().join(format!("phoenix-overgraph-flush-test-{}", now_ms()));
        let store = PhoenixOvergraphStore::open_with_flush_threshold(&path, 128).expect("open");
        for version in 1..=3 {
            store
                .put_row(
                    "notes",
                    json!({"id":"n1","version":1,"world_id":null,"narrative_id":null,"entity_kind":null,"title":"Repeated","body":"Aella crossed the threshold","updated_at":version,"deleted":false}),
                )
                .expect("upsert repeated key");
        }
        assert_eq!(store.logical_bytes_since_flush.get(), 0);
        let report = store.flush().expect("final flush");
        assert!(report.segment_count > 0);
        assert_eq!(store.fetch_rows("notes").expect("fetch").len(), 1);
        let _ = std::fs::remove_dir_all(path);
    }
}
