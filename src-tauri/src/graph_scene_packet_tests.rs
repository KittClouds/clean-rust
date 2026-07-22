use super::*;

#[test]
fn hierarchy_packet_keeps_document_chunk_entity_order() {
    let packet = compile_packet(GraphScenePacketInput {
        source: "inline".into(),
        manifold: "siegel".into(),
        layout_mode: "siegelFinsler".into(),
        source_mode: "embeddings".into(),
        source_label: "test".into(),
        limit: 16,
        settings: GraphScenePacketSettings::default(),
        nodes: vec![
            node("doc-1", "Document", "document"),
            node("root-1", "Identity Root", "identity_root"),
            node("chunk-1", "Chunk", "chunk"),
            node("entity-1", "Entity", "entity"),
        ],
        edges: vec![],
    });
    assert_eq!(packet.counters.rendered_nodes, 4);
    let ranks = STANDARD
        .decode(packet.hierarchy_shell_ranks.unwrap())
        .unwrap();
    assert_eq!(ranks, vec![1, 2, 3, 4]);
}

#[test]
fn invalid_edges_do_not_cross_packet_boundary() {
    let packet = compile_packet(GraphScenePacketInput {
        source: "inline".into(),
        manifold: "hybrid".into(),
        layout_mode: "hybridSpace".into(),
        source_mode: "embeddings".into(),
        source_label: "test".into(),
        limit: 16,
        settings: GraphScenePacketSettings::default(),
        nodes: vec![node("a", "A", "entity"), node("b", "B", "entity")],
        edges: vec![
            edge("ab", "a", "b"),
            edge("missing", "a", "c"),
            edge("dupe", "b", "a"),
        ],
    });
    assert_eq!(packet.counters.input_edges, 3);
    assert_eq!(packet.counters.rendered_edges, 1);
    assert_eq!(packet.counters.dropped_edges, 2);
}

#[test]
fn packet_preserves_native_hierarchy_hints() {
    let mut child = node("embed:causalFact:cause-1", "causes_or_explains", "causal");
    child.hierarchy_hint = Some(hierarchy_hint(
        &child.id,
        "event:event-b",
        "event:event-b:causal",
        Some("embed:event:event-b"),
        "causalFact",
        5,
        1,
    ));
    let packet = compile_packet(GraphScenePacketInput {
        source: "inline".into(),
        manifold: "siegel".into(),
        layout_mode: "siegelFinsler".into(),
        source_mode: "embeddings".into(),
        source_label: "test".into(),
        limit: 16,
        settings: GraphScenePacketSettings::default(),
        nodes: vec![node("embed:event:event-b", "Event", "event"), child],
        edges: vec![],
    });

    let hints = packet.hierarchy_hints.expect("native hierarchy hints");
    assert_eq!(hints.len(), 1);
    assert_eq!(hints[0].cap_id, "event:event-b:causal");
    assert_eq!(
        hints[0].parent_node_id.as_deref(),
        Some("embed:event:event-b")
    );
}

#[test]
fn product_packet_uses_native_hierarchy_hint_route_order() {
    let mut doc = node("embed:note:note-1", "Document", "document");
    doc.hierarchy_hint = Some(hierarchy_hint(
        &doc.id,
        "document:note-1",
        "document:note-1",
        None,
        "document",
        0,
        0,
    ));
    let mut root = node("embed:structure-root:note-1:identity", "Root", "root");
    root.hierarchy_hint = Some(hierarchy_hint(
        &root.id,
        "document:note-1",
        "document:note-1:root:identity",
        Some("embed:note:note-1"),
        "documentRoot",
        1,
        1,
    ));
    let mut chunk = node("embed:chunk:chunk-1", "Chunk", "chunk");
    chunk.hierarchy_hint = Some(hierarchy_hint(
        &chunk.id,
        "document:note-1",
        "document:note-1:chunk:chunk-1",
        Some("embed:structure-root:note-1:identity"),
        "chunk",
        2,
        2,
    ));
    let mut entity = node("embed:entity:kai", "Kai", "entity");
    entity.hierarchy_hint = Some(hierarchy_hint(
        &entity.id,
        "identity:kai",
        "identity:kai",
        Some("embed:structure-root:note-1:identity"),
        "canonicalEntity",
        3,
        3,
    ));
    let mut fact = node("embed:causalFact:cause-1", "causes_or_explains", "causal");
    fact.hierarchy_hint = Some(hierarchy_hint(
        &fact.id,
        "event:event-b",
        "event:event-b:causal",
        Some("embed:event:event-b"),
        "causalFact",
        5,
        4,
    ));
    let packet = compile_packet(GraphScenePacketInput {
        source: "inline".into(),
        manifold: "product".into(),
        layout_mode: "productManifold".into(),
        source_mode: "embeddings".into(),
        source_label: "test".into(),
        limit: 16,
        settings: GraphScenePacketSettings::default(),
        nodes: vec![doc, root, chunk, entity, fact],
        edges: vec![],
    });
    let positions = decode_points(&packet.positions3d);

    assert!(positions[0].x < positions[1].x);
    assert!(positions[1].x < positions[2].x);
    assert!(positions[2].x < positions[3].x);
    assert!(positions[3].x < positions[4].x);
    assert!(positions[2].y > positions[3].y);
    assert!(positions[4].y < positions[3].y);
}

fn node(id: &str, label: &str, source_type: &str) -> GraphScenePacketNodeInput {
    GraphScenePacketNodeInput {
        id: id.into(),
        label: label.into(),
        kind: label.into(),
        source_type: source_type.into(),
        vector: vec![0.1, 0.3, 0.5, 0.7],
        base_vector: None,
        total_mentions: Some(1),
        hierarchy_hint: None,
    }
}

fn edge(id: &str, source_id: &str, target_id: &str) -> GraphScenePacketEdgeInput {
    GraphScenePacketEdgeInput {
        id: id.into(),
        source_id: source_id.into(),
        target_id: target_id.into(),
        edge_type: "semantic-neighbor".into(),
        confidence: 0.5,
    }
}

fn hierarchy_hint(
    node_id: &str,
    tree_id: &str,
    cap_id: &str,
    parent: Option<&str>,
    role: &str,
    level: u16,
    local_rank: u32,
) -> GraphScenePacketHierarchyHint {
    GraphScenePacketHierarchyHint {
        node_id: node_id.into(),
        primary_tree_id: tree_id.into(),
        cap_id: cap_id.into(),
        parent_node_id: parent.map(str::to_owned),
        shell_radius: match role {
            "document" => 2.08,
            "documentRoot" => 1.92,
            "chunk" => 1.66,
            "canonicalEntity" => 1.42,
            _ => 1.14,
        },
        hierarchy_level: level,
        role: role.into(),
        confidence: 0.94,
        memberships: vec![GraphScenePacketHierarchyMembership {
            tree_id: tree_id.into(),
            node_id: node_id.into(),
            parent_node_id: parent.map(str::to_owned),
            depth: level,
            local_rank,
            path_key: format!("{}/{}/{}", tree_id, parent.unwrap_or("root"), node_id),
            role: role.into(),
            confidence: 0.94,
            primary: true,
        }],
    }
}

fn decode_points(encoded: &str) -> Vec<Point3> {
    STANDARD
        .decode(encoded)
        .unwrap()
        .chunks_exact(12)
        .map(|chunk| Point3 {
            x: f32::from_le_bytes(chunk[0..4].try_into().unwrap()),
            y: f32::from_le_bytes(chunk[4..8].try_into().unwrap()),
            z: f32::from_le_bytes(chunk[8..12].try_into().unwrap()),
        })
        .collect()
}
