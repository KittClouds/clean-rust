use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

use phoenix_store_native::PhoenixNativeRowStore;
use phoenix_store_overgraph::PhoenixOvergraphStore;
use serde_json::{json, Value};

fn main() -> Result<(), String> {
    let config = Config::parse(std::env::args().skip(1))?;
    let store = PhoenixOvergraphStore::open(&config.store_path).map_err(display_error)?;
    let counts = store.relation_counts().map_err(display_error)?;
    let scoped_documents = store
        .fetch_rows("scoped_documents")
        .map_err(display_error)?;
    let sessions = store
        .fetch_rows("phoenix_sessions")
        .map_err(display_error)?;
    let commits = store.fetch_rows("phoenix_commits").map_err(display_error)?;
    let ingest_log = store
        .fetch_rows("phoenix_ingest_log")
        .map_err(display_error)?;
    let evidence = store.fetch_rows("evidence_ledger").map_err(display_error)?;
    if let Some(path) = &config.dump_scoped_documents {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("create {}: {error}", parent.display()))?;
        }
        fs::write(
            path,
            serde_json::to_vec_pretty(&scoped_documents)
                .map_err(|error| format!("serialize scoped documents: {error}"))?,
        )
        .map_err(|error| format!("write {}: {error}", path.display()))?;
    }
    let non_empty = counts
        .into_iter()
        .filter(|(_, count)| *count > 0)
        .collect::<BTreeMap<_, _>>();
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "schemaVersion": "phoenix-runtime-decision-row-audit/v1",
            "storePath": config.store_path.display().to_string(),
            "readContract": "copied store; row reads only",
            "nonEmptyRelations": non_empty,
            "scopedDocuments": scoped_document_summary(&scoped_documents),
            "decisionSignals": decision_signal_summary(&sessions, &commits, &ingest_log, &evidence),
        }))
        .map_err(|error| format!("serialize report: {error}"))?
    );
    Ok(())
}

fn decision_signal_summary(
    sessions: &[Value],
    commits: &[Value],
    ingest_log: &[Value],
    evidence: &[Value],
) -> Value {
    let mut statuses = BTreeMap::new();
    let mut commit_requested = BTreeMap::new();
    for row in sessions {
        count(&mut statuses, string_field(row, "status"));
    }
    for row in ingest_log {
        count(
            &mut commit_requested,
            if row
                .get("commit_requested")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                "true"
            } else {
                "false"
            },
        );
    }
    json!({
        "sessions": {
            "count": sessions.len(),
            "statuses": statuses,
            "revisionRange": range_i64(sessions.iter().map(|row| int_field(row, "revision"))),
            "createdAtRange": range_i64(sessions.iter().map(|row| int_field(row, "created_at"))),
            "updatedAtRange": range_i64(sessions.iter().map(|row| int_field(row, "updated_at"))),
        },
        "commits": {
            "count": commits.len(),
            "revisionRange": range_i64(commits.iter().map(|row| int_field(row, "revision"))),
            "committedAtRange": range_i64(commits.iter().map(|row| int_field(row, "committed_at"))),
        },
        "ingestLog": {
            "count": ingest_log.len(),
            "commitRequested": commit_requested,
            "documentCount": ingest_log.iter().map(|row| int_field(row, "document_count")).sum::<i64>(),
            "createdAtRange": range_i64(ingest_log.iter().map(|row| int_field(row, "created_at"))),
        },
        "evidenceLedger": {"count": evidence.len()},
    })
}

struct Config {
    store_path: PathBuf,
    dump_scoped_documents: Option<PathBuf>,
}

impl Config {
    fn parse(args: impl Iterator<Item = String>) -> Result<Self, String> {
        let mut store_path = None;
        let mut dump_scoped_documents = None;
        let mut args = args.peekable();
        while let Some(argument) = args.next() {
            match argument.as_str() {
                "--store-path" => store_path = args.next().map(PathBuf::from),
                "--dump-scoped-documents" => dump_scoped_documents = args.next().map(PathBuf::from),
                other => return Err(format!("unknown argument: {other}")),
            }
        }
        let store_path = store_path.ok_or("--store-path is required")?;
        if !store_path.is_dir() {
            return Err(format!(
                "store path does not exist: {}",
                store_path.display()
            ));
        }
        Ok(Self {
            store_path,
            dump_scoped_documents,
        })
    }
}

fn scoped_document_summary(rows: &[Value]) -> Value {
    let mut namespaces = BTreeMap::new();
    let mut keys = BTreeMap::new();
    let mut scopes = BTreeMap::new();
    let mut schemas = BTreeMap::new();
    let mut metadata = Vec::with_capacity(rows.len());
    for row in rows {
        count(&mut namespaces, string_field(row, "namespace"));
        count(&mut keys, string_field(row, "document_key"));
        count(&mut scopes, string_field(row, "scope_folder_id"));
        let payload = row
            .get("payload")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let parsed = serde_json::from_str::<Value>(payload).ok();
        let schema = parsed
            .as_ref()
            .and_then(|value| value.get("schemaVersion"))
            .and_then(Value::as_str)
            .unwrap_or(if parsed.is_some() {
                "json-without-schema"
            } else {
                "non-json"
            });
        count(&mut schemas, schema);
        metadata.push(json!({
            "id": string_field(row, "id"),
            "scope": string_field(row, "scope_folder_id"),
            "namespace": string_field(row, "namespace"),
            "documentKey": string_field(row, "document_key"),
            "createdAt": int_field(row, "created_at"),
            "updatedAt": int_field(row, "updated_at"),
            "payloadBytes": payload.len(),
            "payloadSchema": schema,
            "sourceSchema": parsed.as_ref()
                .and_then(|value| value.get("sourceSchemaVersion"))
                .and_then(Value::as_str),
        }));
    }
    json!({
        "count": rows.len(),
        "namespaces": namespaces,
        "documentKeys": keys,
        "scopes": scopes,
        "payloadSchemas": schemas,
        "rows": metadata,
    })
}

fn count(map: &mut BTreeMap<String, usize>, key: &str) {
    *map.entry(key.to_owned()).or_default() += 1;
}

fn string_field<'a>(row: &'a Value, key: &str) -> &'a str {
    row.get(key).and_then(Value::as_str).unwrap_or_default()
}

fn int_field(row: &Value, key: &str) -> i64 {
    row.get(key).and_then(Value::as_i64).unwrap_or_default()
}

fn range_i64(values: impl Iterator<Item = i64>) -> Value {
    let values = values.collect::<Vec<_>>();
    json!({"min": values.iter().min(), "max": values.iter().max()})
}

fn display_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}
