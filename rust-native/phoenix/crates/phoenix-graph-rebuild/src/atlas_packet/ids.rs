use compact_str::{format_compact, CompactString};
use phoenix_types::EntityId;

pub(super) fn note_object_id(note_id: &CompactString) -> CompactString {
    format_compact!("atlas:note:{note_id}")
}

pub(super) fn entity_object_id(entity_id: &EntityId) -> CompactString {
    entity_id.0.as_str().into()
}

pub(super) fn chunk_object_id(chunk_id: &CompactString) -> CompactString {
    format_compact!("atlas:chunk:{chunk_id}")
}

pub(super) fn anchor_object_id(anchor_id: &CompactString) -> CompactString {
    format_compact!("atlas:anchor:{anchor_id}")
}

pub(super) fn fact_object_id(fact_id: &CompactString) -> CompactString {
    format_compact!("atlas:fact:{fact_id}")
}

pub(super) fn event_object_id(event_id: &CompactString) -> CompactString {
    format_compact!("atlas:event:{event_id}")
}

pub(super) fn story_edge_object_id(kind: &str, edge_id: &CompactString) -> CompactString {
    format_compact!("atlas:{kind}:{edge_id}")
}

pub(super) fn memory_object_id(memory_id: &CompactString) -> CompactString {
    format_compact!("atlas:memory:{memory_id}")
}

pub(super) fn hyperedge_object_id(hyperedge_id: &CompactString) -> CompactString {
    format_compact!("atlas:hyperedge:{hyperedge_id}")
}

pub(super) fn hyperedge_role_object_id(
    hyperedge_id: &CompactString,
    role_id: &CompactString,
) -> CompactString {
    format_compact!("atlas:hyperedge-role:{hyperedge_id}:{role_id}")
}

pub(super) fn review_object_id(review_id: &CompactString) -> CompactString {
    format_compact!("atlas:review:{review_id}")
}

pub(super) fn discourse_cluster_object_id(cluster_id: &CompactString) -> CompactString {
    format_compact!("atlas:discourse-cluster:{cluster_id}")
}

pub(super) fn discourse_bridge_object_id(bridge_id: &CompactString) -> CompactString {
    format_compact!("atlas:discourse-bridge:{bridge_id}")
}
