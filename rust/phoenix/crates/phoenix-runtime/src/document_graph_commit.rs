use hashbrown::HashSet;
use serde::Deserialize;
use serde_json::{json, Map, Value};

use super::{PhoenixRuntime, StoreCommandResult, StoreError};

const COMMIT_SCHEMA: &str = "phoenix-document-graph-commit/v1";
const UNDO_SCHEMA: &str = "phoenix-document-graph-undo/v1";
const COMMIT_ATTRIBUTE: &str = "documentCompilerCommitId";
const REMOVE_ATTRIBUTE: &str = "documentCompilerRemoveOnUndo";

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CommitRequest {
    schema_version: String,
    commit_id: String,
    scope_id: String,
    topology_diff_id: String,
    source_object_id: String,
    receipt_id: String,
    built_at: u64,
    vertices: Vec<CommitVertex>,
    edges: Vec<CommitEdge>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CommitVertex {
    id: String,
    kind: String,
    label: String,
    remove_on_undo: bool,
    #[serde(default)]
    attributes: Map<String, Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CommitEdge {
    source: String,
    target: String,
    edge_type: String,
    weight: i64,
    #[serde(default)]
    attributes: Map<String, Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UndoRequest {
    schema_version: String,
    commit_id: String,
    undone_at: u64,
}

pub(super) fn commit(
    runtime: &PhoenixRuntime,
    payload: &Value,
) -> Result<StoreCommandResult, StoreError> {
    let request: CommitRequest = parse_payload(payload, "documentGraph:commit")?;
    if request.schema_version != COMMIT_SCHEMA {
        return Err(StoreError::Query(format!(
            "unsupported document graph commit schema: {}",
            request.schema_version
        )));
    }
    if request.commit_id.is_empty() || request.vertices.is_empty() || request.edges.is_empty() {
        return Err(StoreError::Query(
            "document graph commit requires a commit id, vertices, and edges".to_owned(),
        ));
    }

    let store = runtime.native_row_store()?;
    let original_vertices = store.fetch_rows("graph_vertices")?;
    let original_labels = store.fetch_rows("graph_vertex_labels")?;
    let original_edges = store.fetch_rows("graph_edges")?;
    let mut vertices = original_vertices.clone();
    let mut labels = original_labels.clone();
    let mut edges = original_edges.clone();
    let mut changed = false;

    for vertex in &request.vertices {
        if let Some(existing) = vertices
            .iter()
            .find(|row| vertex_id(row) == Some(vertex.id.as_str()))
        {
            if vertex.remove_on_undo && !owned_by(existing, &request.commit_id) {
                return Err(StoreError::Query(format!(
                    "document graph vertex conflict for {}",
                    vertex.id
                )));
            }
            continue;
        }
        let attributes = vertex_attributes(&request, vertex);
        vertices.push(json!({
            "id": vertex.id,
            "value": { "id": vertex.id, "kind": vertex.kind, "label": vertex.label },
            "weight": 1,
            "attributes": attributes,
        }));
        if !labels
            .iter()
            .any(|row| label_vertex_id(row) == Some(vertex.id.as_str()))
        {
            labels.push(json!({ "vertex_id": vertex.id, "label": vertex.label }));
        }
        changed = true;
    }

    for edge in &request.edges {
        if let Some(existing) = edges.iter().find(|row| edge_key_matches(row, edge)) {
            if !owned_by(existing, &request.commit_id) {
                return Err(StoreError::Query(format!(
                    "document graph edge conflict for {} -> {}",
                    edge.source, edge.target
                )));
            }
            continue;
        }
        let attributes = edge_attributes(&request, edge);
        edges.push(json!({
            "source_id": edge.source,
            "target_id": edge.target,
            "edge_type": edge.edge_type,
            "weight": edge.weight.max(1),
            "attributes": attributes,
            "data": null,
        }));
        changed = true;
    }

    replace_graph_rows(
        store,
        &original_vertices,
        &original_labels,
        &original_edges,
        &vertices,
        &labels,
        &edges,
    )?;

    let vertex_ids = request
        .vertices
        .iter()
        .filter(|vertex| vertex.remove_on_undo)
        .map(|vertex| vertex.id.clone())
        .collect::<Vec<_>>();
    let edge_keys = request
        .edges
        .iter()
        .map(|edge| format!("{}\0{}", edge.source, edge.target))
        .collect::<Vec<_>>();
    Ok(success(json!({
        "commitId": request.commit_id,
        "createdVertexIds": vertex_ids,
        "createdEdgeKeys": edge_keys,
        "idempotent": !changed,
    })))
}

pub(super) fn undo(
    runtime: &PhoenixRuntime,
    payload: &Value,
) -> Result<StoreCommandResult, StoreError> {
    let request: UndoRequest = parse_payload(payload, "documentGraph:undo")?;
    if request.schema_version != UNDO_SCHEMA {
        return Err(StoreError::Query(format!(
            "unsupported document graph undo schema: {}",
            request.schema_version
        )));
    }
    if request.commit_id.is_empty() {
        return Err(StoreError::Query(
            "document graph undo requires a commit id".to_owned(),
        ));
    }

    let store = runtime.native_row_store()?;
    let original_vertices = store.fetch_rows("graph_vertices")?;
    let original_labels = store.fetch_rows("graph_vertex_labels")?;
    let original_edges = store.fetch_rows("graph_edges")?;
    let removed_vertex_ids = original_vertices
        .iter()
        .filter(|row| owned_and_removable(row, &request.commit_id))
        .filter_map(|row| vertex_id(row).map(str::to_owned))
        .collect::<Vec<_>>();
    let removed_vertex_set = removed_vertex_ids
        .iter()
        .map(String::as_str)
        .collect::<HashSet<_>>();
    let vertices = original_vertices
        .iter()
        .filter(|row| !owned_and_removable(row, &request.commit_id))
        .cloned()
        .collect::<Vec<_>>();
    let labels = original_labels
        .iter()
        .filter(|row| {
            label_vertex_id(row)
                .map(|id| !removed_vertex_set.contains(id))
                .unwrap_or(true)
        })
        .cloned()
        .collect::<Vec<_>>();
    let edges = original_edges
        .iter()
        .filter(|row| !owned_by(row, &request.commit_id))
        .cloned()
        .collect::<Vec<_>>();
    let removed_edges = original_edges.len().saturating_sub(edges.len());
    let removed_labels = original_labels.len().saturating_sub(labels.len());

    replace_graph_rows(
        store,
        &original_vertices,
        &original_labels,
        &original_edges,
        &vertices,
        &labels,
        &edges,
    )?;
    Ok(success(json!({
        "commitId": request.commit_id,
        "undoneAt": request.undone_at,
        "removedVertices": removed_vertex_ids.len(),
        "removedEdges": removed_edges,
        "removedLabels": removed_labels,
        "idempotent": removed_vertex_ids.is_empty() && removed_edges == 0,
    })))
}

fn replace_graph_rows(
    store: &dyn phoenix_store_native::PhoenixNativeRowStore,
    original_vertices: &[Value],
    original_labels: &[Value],
    original_edges: &[Value],
    vertices: &[Value],
    labels: &[Value],
    edges: &[Value],
) -> Result<(), StoreError> {
    store.replace_relation_rows("graph_vertices", vertices)?;
    if let Err(error) = store.replace_relation_rows("graph_vertex_labels", labels) {
        let _ = store.replace_relation_rows("graph_vertices", original_vertices);
        return Err(error);
    }
    if let Err(error) = store.replace_relation_rows("graph_edges", edges) {
        let _ = store.replace_relation_rows("graph_vertices", original_vertices);
        let _ = store.replace_relation_rows("graph_vertex_labels", original_labels);
        let _ = store.replace_relation_rows("graph_edges", original_edges);
        return Err(error);
    }
    Ok(())
}

fn vertex_attributes(request: &CommitRequest, vertex: &CommitVertex) -> Value {
    let mut attributes = vertex.attributes.clone();
    if vertex.remove_on_undo {
        insert_commit_metadata(&mut attributes, request);
        attributes.insert(REMOVE_ATTRIBUTE.to_owned(), Value::Bool(true));
    }
    Value::Object(attributes)
}

fn edge_attributes(request: &CommitRequest, edge: &CommitEdge) -> Value {
    let mut attributes = edge.attributes.clone();
    insert_commit_metadata(&mut attributes, request);
    Value::Object(attributes)
}

fn insert_commit_metadata(attributes: &mut Map<String, Value>, request: &CommitRequest) {
    attributes.insert(COMMIT_ATTRIBUTE.to_owned(), json!(request.commit_id));
    attributes.insert(
        "documentCompilerScopeId".to_owned(),
        json!(request.scope_id),
    );
    attributes.insert(
        "documentCompilerTopologyDiffId".to_owned(),
        json!(request.topology_diff_id),
    );
    attributes.insert(
        "documentCompilerSourceObjectId".to_owned(),
        json!(request.source_object_id),
    );
    attributes.insert(
        "documentCompilerReceiptId".to_owned(),
        json!(request.receipt_id),
    );
    attributes.insert(
        "documentCompilerBuiltAt".to_owned(),
        json!(request.built_at),
    );
}

fn parse_payload<T: for<'de> Deserialize<'de>>(
    payload: &Value,
    command: &str,
) -> Result<T, StoreError> {
    serde_json::from_value(payload.clone())
        .map_err(|error| StoreError::Query(format!("invalid {command} payload: {error}")))
}

fn owned_by(row: &Value, commit_id: &str) -> bool {
    row.get("attributes")
        .and_then(Value::as_object)
        .and_then(|attributes| attributes.get(COMMIT_ATTRIBUTE))
        .and_then(Value::as_str)
        == Some(commit_id)
}

fn owned_and_removable(row: &Value, commit_id: &str) -> bool {
    owned_by(row, commit_id)
        && row
            .get("attributes")
            .and_then(Value::as_object)
            .and_then(|attributes| attributes.get(REMOVE_ATTRIBUTE))
            .and_then(Value::as_bool)
            .unwrap_or(false)
}

fn vertex_id(row: &Value) -> Option<&str> {
    row.get("id")?.as_str()
}

fn label_vertex_id(row: &Value) -> Option<&str> {
    row.get("vertex_id")?.as_str()
}

fn edge_key_matches(row: &Value, edge: &CommitEdge) -> bool {
    row.get("source_id").and_then(Value::as_str) == Some(edge.source.as_str())
        && row.get("target_id").and_then(Value::as_str) == Some(edge.target.as_str())
}

fn success(payload: Value) -> StoreCommandResult {
    StoreCommandResult {
        success: true,
        payload: Some(payload),
        error: None,
    }
}
