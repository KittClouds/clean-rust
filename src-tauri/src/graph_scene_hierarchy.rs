use crate::graph_scene_packet::{
    GraphScenePacketHierarchyHint, GraphScenePacketHierarchyMembership,
};
use serde_json::Value;

pub fn graph_rebuild_hierarchy_hint(
    target: &Value,
    local_rank: usize,
) -> Option<GraphScenePacketHierarchyHint> {
    let node_id = str_field(target, "id", "id");
    if node_id.is_empty() {
        return None;
    }
    let source_type = packet_source_type(target);
    let parents = string_array_field(target, "parent_ids", "parentIds");
    let note_id = note_id(target);
    let chunk_id = chunk_id(target);
    let role = hierarchy_role(target, source_type);
    let cap_id = cap_id(target, &role, &note_id, &chunk_id, &parents);
    let parent_node_id = parent_node_id(target, &role, &note_id, &chunk_id, &parents);
    let primary_tree_id = primary_tree_id(&cap_id, &note_id);
    let level = hierarchy_level(&role);
    let confidence = if parent_node_id.is_some() || role == "document" {
        0.94
    } else {
        0.72
    };
    let membership = GraphScenePacketHierarchyMembership {
        tree_id: primary_tree_id.clone(),
        node_id: node_id.to_owned(),
        parent_node_id: parent_node_id.clone(),
        depth: level,
        local_rank: u32::try_from(local_rank).unwrap_or(u32::MAX),
        path_key: format!(
            "{}/{}/{}",
            primary_tree_id,
            parent_node_id.as_deref().unwrap_or("root"),
            node_id
        ),
        role: role.clone(),
        confidence,
        primary: true,
    };
    Some(GraphScenePacketHierarchyHint {
        node_id: node_id.to_owned(),
        primary_tree_id,
        cap_id,
        parent_node_id,
        shell_radius: shell_radius(&role),
        hierarchy_level: level,
        role,
        confidence,
        memberships: vec![membership],
    })
}

fn packet_source_type(target: &Value) -> &'static str {
    let lane = str_field(target, "lane", "lane");
    let role = str_field(target, "structural_role", "structuralRole");
    if role == "root" || lane == "document_spine" {
        "root"
    } else if lane == "chunk_spine" {
        "chunk"
    } else if lane == "entity_anchor" {
        "entity"
    } else if lane == "anchor_evidence" {
        "evidence"
    } else if lane == "event_identity" {
        "event"
    } else if lane == "temporal_fact" {
        "temporal"
    } else if lane == "causal_fact" {
        "causal"
    } else if lane == "memory_state" {
        "memory"
    } else if !role.is_empty() {
        "graph"
    } else {
        "target"
    }
}

fn hierarchy_role(target: &Value, source_type: &str) -> String {
    let id = str_field(target, "id", "id").to_ascii_lowercase();
    let kind = str_field(target, "kind", "kind").to_ascii_lowercase();
    let lane = str_field(target, "lane", "lane").to_ascii_lowercase();
    if id.contains("structure-root") || kind.contains("structureroot") {
        "documentRoot".to_owned()
    } else if source_type == "root" || kind == "note" || kind == "document" {
        "document".to_owned()
    } else if source_type == "chunk" {
        "chunk".to_owned()
    } else if source_type == "entity" {
        "canonicalEntity".to_owned()
    } else if source_type == "evidence" || kind.contains("anchor") {
        "evidence".to_owned()
    } else if source_type == "event" {
        "event".to_owned()
    } else if source_type == "causal" || lane == "causal_fact" {
        "causalFact".to_owned()
    } else if source_type == "temporal" || lane == "temporal_fact" {
        "temporalFact".to_owned()
    } else if source_type == "memory" {
        "memoryState".to_owned()
    } else {
        "fact".to_owned()
    }
}

fn cap_id(target: &Value, role: &str, note_id: &str, chunk_id: &str, parents: &[String]) -> String {
    let source_id = target_token(target, "source_id", "sourceId");
    match role {
        "document" => format!(
            "document:{}",
            first_non_empty(note_id, &source_id, "corpus")
        ),
        "documentRoot" => format!(
            "document:{}:root:{}",
            first_non_empty(note_id, "corpus", "corpus"),
            structure_root_key(target)
        ),
        "chunk" => format!(
            "document:{}:chunk:{}",
            first_non_empty(note_id, "corpus", "corpus"),
            first_non_empty(chunk_id, &source_id, "chunk")
        ),
        "canonicalEntity" => format!(
            "identity:{}",
            entity_token(target).unwrap_or_else(|| source_id.clone())
        ),
        "evidence" => {
            if !note_id.is_empty() && !chunk_id.is_empty() {
                format!("document:{note_id}:chunk:{chunk_id}:evidence")
            } else {
                format!("evidence:{source_id}")
            }
        }
        "event" => format!("event:{source_id}"),
        "causalFact" => last_parent_with_prefix(parents, "embed:event:")
            .map(|parent| {
                format!(
                    "event:{}:causal",
                    strip_prefix(parent.as_str(), "embed:event:")
                )
            })
            .unwrap_or_else(|| fallback_fact_cap(target, note_id, chunk_id, "causal")),
        "temporalFact" => first_parent_with_prefix(parents, "embed:event:")
            .map(|parent| {
                format!(
                    "event:{}:temporal",
                    strip_prefix(parent.as_str(), "embed:event:")
                )
            })
            .unwrap_or_else(|| fallback_fact_cap(target, note_id, chunk_id, "temporal")),
        "memoryState" => entity_token(target)
            .map(|entity| format!("identity:{entity}:memory"))
            .unwrap_or_else(|| fallback_fact_cap(target, note_id, chunk_id, "memory")),
        _ => fallback_fact_cap(target, note_id, chunk_id, &fact_family(target)),
    }
}

fn parent_node_id(
    target: &Value,
    role: &str,
    note_id: &str,
    chunk_id: &str,
    parents: &[String],
) -> Option<String> {
    match role {
        "document" => None,
        "documentRoot" => first_parent_with_prefix(parents, "embed:note:")
            .or_else(|| first_parent_with_prefix(parents, "embed:document:"))
            .or_else(|| (!note_id.is_empty()).then(|| format!("embed:note:{note_id}"))),
        "chunk" => first_parent_with_prefix(parents, "embed:structure-root:")
            .or_else(|| first_parent_with_prefix(parents, "embed:note:"))
            .or_else(|| first_parent_with_prefix(parents, "embed:document:"))
            .or_else(|| (!note_id.is_empty()).then(|| format!("embed:note:{note_id}"))),
        "canonicalEntity" => first_parent_with_prefix(parents, "embed:structure-root:")
            .filter(|parent| parent.contains(":identity"))
            .or_else(|| {
                (!note_id.is_empty()).then(|| format!("embed:structure-root:{note_id}:identity"))
            }),
        "evidence" => (!chunk_id.is_empty())
            .then(|| format!("embed:chunk:{chunk_id}"))
            .or_else(|| entity_token(target).map(|entity| format!("embed:entity:{entity}"))),
        "event" => (!chunk_id.is_empty()).then(|| format!("embed:chunk:{chunk_id}")),
        "causalFact" => last_parent_with_prefix(parents, "embed:event:")
            .or_else(|| first_parent_with_prefix(parents, "embed:structure-root:")),
        "temporalFact" => first_parent_with_prefix(parents, "embed:event:")
            .or_else(|| first_parent_with_prefix(parents, "embed:structure-root:")),
        "memoryState" => entity_token(target).map(|entity| format!("embed:entity:{entity}")),
        _ => (!chunk_id.is_empty())
            .then(|| format!("embed:chunk:{chunk_id}"))
            .or_else(|| first_parent_with_prefix(parents, "embed:entity:")),
    }
}

fn primary_tree_id(cap_id: &str, note_id: &str) -> String {
    if cap_id.starts_with("identity:")
        || cap_id.starts_with("event:")
        || cap_id.starts_with("document:")
    {
        cap_id.split(':').take(2).collect::<Vec<_>>().join(":")
    } else if !note_id.is_empty() {
        format!("document:{note_id}")
    } else {
        "document:corpus".to_owned()
    }
}

fn hierarchy_level(role: &str) -> u16 {
    match role {
        "document" => 0,
        "documentRoot" => 1,
        "chunk" => 2,
        "canonicalEntity" => 3,
        "event" => 4,
        "causalFact" | "temporalFact" | "fact" => 5,
        "memoryState" => 6,
        "evidence" => 7,
        _ => 5,
    }
}

fn shell_radius(role: &str) -> f32 {
    match role {
        "document" => 2.08,
        "documentRoot" => 1.92,
        "chunk" => 1.66,
        "canonicalEntity" => 1.42,
        "event" => 1.24,
        "causalFact" | "temporalFact" | "fact" => 1.14,
        "memoryState" => 1.04,
        "evidence" => 0.92,
        _ => 1.14,
    }
}

fn note_id(target: &Value) -> String {
    let explicit = str_field(target, "note_id", "noteId");
    if !explicit.is_empty() {
        return explicit.to_owned();
    }
    let document = str_field(target, "document_id", "documentId");
    if !document.is_empty() {
        return document.to_owned();
    }
    let id = str_field(target, "id", "id");
    if let Some(rest) = id.strip_prefix("embed:note:") {
        return rest.to_owned();
    }
    if let Some(rest) = id.strip_prefix("embed:document:") {
        return rest.to_owned();
    }
    if let Some(rest) = id.strip_prefix("embed:chunk:") {
        return rest.split(':').next().unwrap_or_default().to_owned();
    }
    String::new()
}

fn chunk_id(target: &Value) -> String {
    let explicit = str_field(target, "chunk_id", "chunkId");
    if !explicit.is_empty() {
        return explicit.to_owned();
    }
    let id = str_field(target, "id", "id");
    if let Some(rest) = id.strip_prefix("embed:chunk:") {
        return rest.to_owned();
    }
    String::new()
}

fn target_token(target: &Value, snake: &str, camel: &str) -> String {
    let explicit = str_field(target, snake, camel);
    if !explicit.is_empty() {
        return explicit.to_owned();
    }
    let id = str_field(target, "id", "id");
    for prefix in [
        "embed:note:",
        "embed:document:",
        "embed:structure-root:",
        "embed:chunk:",
        "embed:entity:",
        "embed:event:",
        "embed:anchor:",
        "embed:causalFact:",
        "embed:temporalFact:",
        "embed:graphFact:",
        "embed:memoryState:",
    ] {
        if let Some(rest) = id.strip_prefix(prefix) {
            return rest.to_owned();
        }
    }
    id.to_owned()
}

fn entity_token(target: &Value) -> Option<String> {
    let explicit = str_field(target, "entity_id", "entityId");
    if !explicit.is_empty() {
        return Some(explicit.to_owned());
    }
    let id = str_field(target, "id", "id");
    if let Some(rest) = id.strip_prefix("embed:entity:") {
        return Some(rest.to_owned());
    }
    let source_id = str_field(target, "source_id", "sourceId");
    (!source_id.is_empty() && packet_source_type(target) == "entity").then(|| source_id.to_owned())
}

fn structure_root_key(target: &Value) -> String {
    let id = str_field(target, "id", "id");
    if let Some(rest) = id.strip_prefix("embed:structure-root:") {
        return rest.rsplit(':').next().unwrap_or("root").to_owned();
    }
    let source_id = str_field(target, "source_id", "sourceId");
    if !source_id.is_empty() {
        return source_id.to_owned();
    }
    "root".to_owned()
}

fn fallback_fact_cap(target: &Value, note_id: &str, chunk_id: &str, family: &str) -> String {
    if !note_id.is_empty() && !chunk_id.is_empty() {
        format!("document:{note_id}:chunk:{chunk_id}:facts:{family}")
    } else if let Some(entity) = entity_token(target) {
        format!("identity:{entity}:facts:{family}")
    } else if !note_id.is_empty() {
        format!("document:{note_id}:facts:{family}")
    } else {
        format!("fact:{family}")
    }
}

fn fact_family(target: &Value) -> String {
    let text = format!(
        "{} {} {}",
        str_field(target, "label", "label"),
        str_field(target, "text", "text"),
        str_field(target, "source_id", "sourceId")
    )
    .to_ascii_lowercase();
    if text.contains("cause") || text.contains("explain") {
        "causal".to_owned()
    } else if text.contains("temporal") || text.contains("before") || text.contains("after") {
        "temporal".to_owned()
    } else if text.contains("authority") {
        "authority".to_owned()
    } else if text.contains("communication") || text.contains("said") || text.contains("told") {
        "communication".to_owned()
    } else if text.contains("approval") {
        "approval".to_owned()
    } else if text.contains("family") {
        "family".to_owned()
    } else if text.contains("intimacy") {
        "intimacy".to_owned()
    } else if text.contains("transfer") {
        "transfer".to_owned()
    } else {
        "relationship".to_owned()
    }
}

fn first_non_empty<'a>(first: &'a str, second: &'a str, fallback: &'a str) -> &'a str {
    if !first.is_empty() {
        first
    } else if !second.is_empty() {
        second
    } else {
        fallback
    }
}

fn first_parent_with_prefix(parents: &[String], prefix: &str) -> Option<String> {
    parents
        .iter()
        .find(|parent| parent.starts_with(prefix))
        .cloned()
}

fn last_parent_with_prefix(parents: &[String], prefix: &str) -> Option<String> {
    parents
        .iter()
        .rev()
        .find(|parent| parent.starts_with(prefix))
        .cloned()
}

fn strip_prefix<'a>(value: &'a str, prefix: &str) -> &'a str {
    value.strip_prefix(prefix).unwrap_or(value)
}

fn str_field<'a>(row: &'a Value, snake: &str, camel: &str) -> &'a str {
    row.get(snake)
        .or_else(|| row.get(camel))
        .and_then(Value::as_str)
        .unwrap_or_default()
}

fn string_array_field(row: &Value, snake: &str, camel: &str) -> Vec<String> {
    row.get(snake)
        .or_else(|| row.get(camel))
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(|value| value.as_str().map(str::to_owned))
                .collect()
        })
        .unwrap_or_default()
}
