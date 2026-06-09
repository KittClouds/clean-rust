use base64::{engine::general_purpose::STANDARD, Engine};
use hashbrown::{HashMap, HashSet};
use serde::{Deserialize, Serialize};
use serde_json::Value;

const VERSION: &str = "graph-scene-packet/v1";
const GOLDEN_ANGLE: f32 = 2.399_963_1;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphScenePacketRequest {
    pub source: Option<String>,
    pub manifold: Option<String>,
    pub layout_mode: Option<String>,
    pub source_mode: Option<String>,
    pub scope: Option<Value>,
    pub limit: Option<usize>,
    pub settings: Option<GraphScenePacketSettings>,
    pub nodes: Option<Vec<GraphScenePacketNodeInput>>,
    pub edges: Option<Vec<GraphScenePacketEdgeInput>>,
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphScenePacketSettings {
    pub edge_length: Option<f32>,
    pub node_distance: Option<f32>,
}

impl Default for GraphScenePacketSettings {
    fn default() -> Self {
        Self {
            edge_length: Some(0.8),
            node_distance: Some(1.0),
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphScenePacketNodeInput {
    pub id: String,
    pub label: String,
    pub kind: String,
    pub source_type: String,
    pub vector: Vec<f32>,
    pub base_vector: Option<[f32; 3]>,
    pub total_mentions: Option<u32>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphScenePacketEdgeInput {
    pub id: String,
    pub source_id: String,
    pub target_id: String,
    pub edge_type: String,
    pub confidence: f32,
}

#[derive(Debug)]
pub struct GraphScenePacketInput {
    pub source: String,
    pub manifold: String,
    pub layout_mode: String,
    pub source_mode: String,
    pub source_label: String,
    pub limit: usize,
    pub settings: GraphScenePacketSettings,
    pub nodes: Vec<GraphScenePacketNodeInput>,
    pub edges: Vec<GraphScenePacketEdgeInput>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphScenePacket {
    pub version: &'static str,
    pub source: String,
    pub source_label: String,
    pub manifold: String,
    pub layout_mode: String,
    pub source_mode: String,
    pub counters: GraphScenePacketCounters,
    pub ids: Vec<String>,
    pub labels: Vec<String>,
    pub kinds: Vec<String>,
    pub group_ids: Vec<String>,
    pub positions3d: String,
    pub positions2d: String,
    pub radii: String,
    pub colors: String,
    pub edge_ids: Vec<String>,
    pub edge_pairs: String,
    pub edge_colors: String,
    pub edge_alpha: String,
    pub edge_kinds: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hierarchy_shell_radii: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hierarchy_shell_ranks: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphScenePacketCounters {
    pub input_nodes: u32,
    pub input_edges: u32,
    pub rendered_nodes: u32,
    pub rendered_edges: u32,
    pub dropped_edges: u32,
    pub buffer_bytes: u32,
}

#[derive(Clone, Copy)]
struct Point3 {
    x: f32,
    y: f32,
    z: f32,
}

struct NodeView {
    input: GraphScenePacketNodeInput,
    point: Point3,
    radius: f32,
    color: [f32; 3],
    shell_rank: u8,
}

struct EdgeView {
    id: String,
    source: u32,
    target: u32,
    edge_type: String,
    confidence: f32,
}

pub fn compile_packet(input: GraphScenePacketInput) -> GraphScenePacket {
    let input_nodes = input.nodes.len();
    let input_edges = input.edges.len();
    let limit = input.limit.max(1);
    let mut nodes = select_nodes(input.nodes, limit);
    let id_to_index = nodes
        .iter()
        .enumerate()
        .map(|(index, node)| (node.input.id.clone(), index as u32))
        .collect::<HashMap<_, _>>();
    let edges = select_edges(input.edges, &id_to_index);
    apply_layout(&mut nodes, &edges, &input.layout_mode, input.settings);

    let mut ids = Vec::with_capacity(nodes.len());
    let mut labels = Vec::with_capacity(nodes.len());
    let mut kinds = Vec::with_capacity(nodes.len());
    let mut group_ids = Vec::with_capacity(nodes.len());
    let mut positions3d = Vec::<f32>::with_capacity(nodes.len() * 3);
    let mut positions2d = Vec::<f32>::with_capacity(nodes.len() * 3);
    let mut radii = Vec::<f32>::with_capacity(nodes.len());
    let mut colors = Vec::<f32>::with_capacity(nodes.len() * 3);
    let mut shell_radii = Vec::<f32>::with_capacity(nodes.len());
    let mut shell_ranks = Vec::<u8>::with_capacity(nodes.len());

    for node in &nodes {
        ids.push(node.input.id.clone());
        labels.push(node.input.label.clone());
        kinds.push(node.input.kind.clone());
        group_ids.push(String::new());
        push_point(&mut positions3d, node.point);
        push_point(&mut positions2d, Point3 { z: 0.0, ..node.point });
        radii.push(node.radius);
        colors.extend_from_slice(&node.color);
        shell_radii.push(shell_radius(node.shell_rank));
        shell_ranks.push(node.shell_rank);
    }

    let mut edge_pairs = Vec::<u32>::with_capacity(edges.len() * 2);
    let mut edge_ids = Vec::<String>::with_capacity(edges.len());
    let mut edge_colors = Vec::<f32>::with_capacity(edges.len() * 6);
    let mut edge_alpha = Vec::<f32>::with_capacity(edges.len());
    let mut edge_kinds = Vec::<u8>::with_capacity(edges.len());
    for edge in &edges {
        edge_ids.push(edge.id.clone());
        edge_pairs.push(edge.source);
        edge_pairs.push(edge.target);
        let source = &nodes[edge.source as usize];
        let target = &nodes[edge.target as usize];
        let color = relation_color(&edge.edge_type).unwrap_or_else(|| mix_color(source.color, target.color));
        edge_colors.extend_from_slice(&color);
        edge_colors.extend_from_slice(&color);
        edge_alpha.push((0.055 + edge.confidence.max(0.0) * 0.052).min(0.32));
        edge_kinds.push(if is_hierarchy_edge(&edge.edge_type) { 2 } else { 0 });
    }

    let buffer_bytes = bytes_len_f32(&positions3d)
        + bytes_len_f32(&positions2d)
        + bytes_len_f32(&radii)
        + bytes_len_f32(&colors)
        + bytes_len_u32(&edge_pairs)
        + bytes_len_f32(&edge_colors)
        + bytes_len_f32(&edge_alpha)
        + edge_kinds.len()
        + bytes_len_f32(&shell_radii)
        + shell_ranks.len();

    GraphScenePacket {
        version: VERSION,
        source: input.source,
        source_label: input.source_label,
        manifold: input.manifold,
        layout_mode: input.layout_mode,
        source_mode: input.source_mode,
        counters: GraphScenePacketCounters {
            input_nodes: count_for_wire(input_nodes),
            input_edges: count_for_wire(input_edges),
            rendered_nodes: count_for_wire(nodes.len()),
            rendered_edges: count_for_wire(edges.len()),
            dropped_edges: count_for_wire(input_edges.saturating_sub(edges.len())),
            buffer_bytes: count_for_wire(buffer_bytes),
        },
        ids,
        labels,
        kinds,
        group_ids,
        positions3d: encode_f32(&positions3d),
        positions2d: encode_f32(&positions2d),
        radii: encode_f32(&radii),
        colors: encode_f32(&colors),
        edge_ids,
        edge_pairs: encode_u32(&edge_pairs),
        edge_colors: encode_f32(&edge_colors),
        edge_alpha: encode_f32(&edge_alpha),
        edge_kinds: STANDARD.encode(edge_kinds),
        hierarchy_shell_radii: Some(encode_f32(&shell_radii)),
        hierarchy_shell_ranks: Some(STANDARD.encode(shell_ranks)),
    }
}

fn select_nodes(nodes: Vec<GraphScenePacketNodeInput>, limit: usize) -> Vec<NodeView> {
    nodes
        .into_iter()
        .take(limit)
        .enumerate()
        .map(|(index, input)| {
            let shell_rank = hierarchy_rank(&input);
            let point = input
                .base_vector
                .map(|v| Point3 { x: v[0], y: v[1], z: v[2] })
                .unwrap_or_else(|| project_vector(&input.vector, &input.id, index, limit));
            let mentions = input.total_mentions.unwrap_or(1).max(1) as f32;
            NodeView {
                color: color_for_node(&input, index),
                radius: (2.05 + mentions.sqrt() * 0.24).min(5.7),
                input,
                point,
                shell_rank,
            }
        })
        .collect()
}

fn select_edges(
    edges: Vec<GraphScenePacketEdgeInput>,
    id_to_index: &HashMap<String, u32>,
) -> Vec<EdgeView> {
    let mut seen = HashSet::<u64>::with_capacity(edges.len());
    let mut out = Vec::with_capacity(edges.len());
    for edge in edges {
        let Some(&source) = id_to_index.get(&edge.source_id) else { continue };
        let Some(&target) = id_to_index.get(&edge.target_id) else { continue };
        if source == target {
            continue;
        }
        let key = pair_key(source, target);
        if !seen.insert(key) {
            continue;
        }
        out.push(EdgeView {
            id: edge.id,
            source,
            target,
            edge_type: edge.edge_type,
            confidence: edge.confidence,
        });
    }
    out
}

fn apply_layout(
    nodes: &mut [NodeView],
    edges: &[EdgeView],
    layout_mode: &str,
    settings: GraphScenePacketSettings,
) {
    if layout_mode == "siegelFinsler" || layout_mode == "lorentzTree" {
        apply_hierarchy_bands(nodes, layout_mode);
        return;
    }
    if layout_mode == "hopfProjection" {
        apply_hopf_shell(nodes);
        return;
    }
    if layout_mode == "productManifold" {
        apply_product_shell(nodes);
        return;
    }
    if layout_mode == "hybridSpace" {
        apply_hybrid_shell(nodes);
        return;
    }
    relax(nodes, edges, settings);
}

fn apply_hierarchy_bands(nodes: &mut [NodeView], layout_mode: &str) {
    let len = nodes.len().max(1);
    for (index, node) in nodes.iter_mut().enumerate() {
        let rank = node.shell_rank.max(1) as f32;
        let lane = index as f32 / len as f32;
        let arc = (lane - 0.5) * 2.6;
        let z_scale = if layout_mode == "siegelFinsler" { 0.38 } else { 0.26 };
        node.point.x = -2.2 + rank * 0.72 + arc.sin() * 0.18;
        node.point.y = (lane - 0.5) * 1.9 + stable_signed(&node.input.id) * 0.08;
        node.point.z = arc.cos() * z_scale + stable_signed(&format!("{}:z", node.input.id)) * 0.16;
    }
}

fn apply_hopf_shell(nodes: &mut [NodeView]) {
    let total = nodes.len().max(1);
    for (index, node) in nodes.iter_mut().enumerate() {
        let phase = stable_unit(&node.input.id) * std::f32::consts::TAU;
        let ring = 0.82 + node.shell_rank as f32 * 0.13;
        let y = 1.0 - (index as f32 / total.max(2) as f32) * 2.0;
        node.point.x = phase.cos() * ring;
        node.point.y = y * 0.92;
        node.point.z = phase.sin() * ring;
    }
}

fn apply_product_shell(nodes: &mut [NodeView]) {
    for node in nodes {
        let rank = node.shell_rank.max(1) as f32;
        let phase = stable_unit(&node.input.id) * std::f32::consts::TAU;
        node.point.x = phase.cos() * (0.72 + rank * 0.18);
        node.point.y = (rank - 3.0) * 0.28 + stable_signed(&node.input.kind) * 0.12;
        node.point.z = phase.sin() * (0.72 + rank * 0.12);
    }
}

fn apply_hybrid_shell(nodes: &mut [NodeView]) {
    for node in nodes {
        let rank = node.shell_rank.max(1) as f32;
        let norm = (node.point.x * node.point.x + node.point.y * node.point.y + node.point.z * node.point.z)
            .sqrt()
            .max(1.0e-4);
        let radius = 0.78 + rank * 0.18;
        node.point.x = node.point.x / norm * radius;
        node.point.y = node.point.y / norm * radius;
        node.point.z = node.point.z / norm * radius;
    }
}

fn relax(nodes: &mut [NodeView], edges: &[EdgeView], settings: GraphScenePacketSettings) {
    let ticks = if nodes.len() > 900 { 8 } else if nodes.len() > 400 { 14 } else { 22 };
    let mut vx = vec![0.0_f32; nodes.len()];
    let mut vy = vec![0.0_f32; nodes.len()];
    let mut vz = vec![0.0_f32; nodes.len()];
    let edge_length = settings.edge_length.unwrap_or(0.8).clamp(0.2, 1.8);
    let node_distance = settings.node_distance.unwrap_or(1.0).clamp(0.4, 2.0);
    let spring = 0.018;
    for _ in 0..ticks {
        for edge in edges {
            let a = edge.source as usize;
            let b = edge.target as usize;
            let dx = nodes[b].point.x - nodes[a].point.x;
            let dy = nodes[b].point.y - nodes[a].point.y;
            let dz = nodes[b].point.z - nodes[a].point.z;
            let dist = (dx * dx + dy * dy + dz * dz).sqrt().max(0.001);
            let force = (dist - edge_length) * spring;
            let fx = dx / dist * force;
            let fy = dy / dist * force;
            let fz = dz / dist * force;
            vx[a] += fx;
            vy[a] += fy;
            vz[a] += fz;
            vx[b] -= fx;
            vy[b] -= fy;
            vz[b] -= fz;
        }
        for index in 0..nodes.len() {
            nodes[index].point.x += vx[index] * 0.72;
            nodes[index].point.y += vy[index] * 0.72;
            nodes[index].point.z += vz[index] * 0.72;
            let damping = 0.48 + node_distance * 0.07;
            vx[index] *= damping;
            vy[index] *= damping;
            vz[index] *= damping;
        }
    }
}

fn project_vector(vector: &[f32], id: &str, index: usize, total: usize) -> Point3 {
    let seed = stable_hash(id);
    let phase = seed as f32 / u32::MAX as f32;
    let mut point = Point3 { x: 0.0, y: 0.0, z: 0.0 };
    for (dim, value) in vector.iter().enumerate() {
        let n = dim as f32 + 1.0;
        point.x += value * (n * 12.9898 + phase * std::f32::consts::TAU).sin();
        point.y += value * (n * 78.233 + phase * 3.883_222).cos();
        point.z += value * (n * 37.719 + phase * GOLDEN_ANGLE).sin();
    }
    let norm = (point.x * point.x + point.y * point.y + point.z * point.z).sqrt();
    if norm <= 1.0e-6 || !norm.is_finite() {
        return fibonacci_point(index, total, 1.52, phase);
    }
    Point3 {
        x: point.x / norm * 1.52,
        y: point.y / norm * 1.52,
        z: point.z / norm * 1.52,
    }
}

fn fibonacci_point(index: usize, total: usize, radius: f32, phase: f32) -> Point3 {
    let y = 1.0 - (index as f32 / (total.saturating_sub(1).max(1) as f32)) * 2.0;
    let radial = (1.0 - y * y).max(0.0).sqrt();
    let angle = (index as f32 + phase) * GOLDEN_ANGLE;
    Point3 {
        x: angle.cos() * radial * radius,
        y: y * radius,
        z: angle.sin() * radial * radius,
    }
}

fn hierarchy_rank(node: &GraphScenePacketNodeInput) -> u8 {
    let text = format!(
        "{} {} {}",
        node.id.to_ascii_lowercase(),
        node.kind.to_ascii_lowercase(),
        node.source_type.to_ascii_lowercase()
    );
    if text.contains("doc") || text.contains("document") { 1 }
    else if text.contains("root") || text.contains("identity") || text.contains("context") { 2 }
    else if text.contains("chunk") || text.contains("leaf") { 3 }
    else if text.contains("entity") || text.contains("character") { 4 }
    else { 5 }
}

fn color_for_node(node: &GraphScenePacketNodeInput, index: usize) -> [f32; 3] {
    let text = format!("{} {}", node.kind.to_ascii_lowercase(), node.source_type.to_ascii_lowercase());
    if text.contains("doc") || text.contains("leaf") { [0.10, 0.77, 0.95] }
    else if text.contains("entity") || text.contains("character") { [0.78, 0.26, 0.96] }
    else if text.contains("causal") { [0.98, 0.67, 0.02] }
    else if text.contains("temporal") { [0.20, 0.88, 0.66] }
    else {
        const PALETTE: [[f32; 3]; 4] = [
            [0.18, 0.88, 0.78],
            [0.15, 0.72, 0.95],
            [0.78, 0.35, 0.95],
            [0.98, 0.60, 0.12],
        ];
        PALETTE[index % PALETTE.len()]
    }
}

fn relation_color(edge_type: &str) -> Option<[f32; 3]> {
    let text = edge_type.to_ascii_lowercase();
    if text.contains("causal") || text.contains("cause") || text.contains("explain") {
        Some([0.98, 0.68, 0.06])
    } else if text.contains("temporal") || text.contains("before") || text.contains("after") {
        Some([0.24, 0.92, 0.72])
    } else if text.contains("observ") || text.contains("watch") || text.contains("saw") {
        Some([0.15, 0.74, 0.98])
    } else if text.contains("said") || text.contains("told") || text.contains("ask") {
        Some([0.95, 0.28, 0.62])
    } else {
        None
    }
}

fn is_hierarchy_edge(edge_type: &str) -> bool {
    let text = edge_type.to_ascii_lowercase();
    text.contains("parent")
        || text.contains("chunk")
        || text.contains("anchor")
        || text.contains("document")
}

fn push_point(out: &mut Vec<f32>, point: Point3) {
    out.push(point.x);
    out.push(point.y);
    out.push(point.z);
}

fn mix_color(left: [f32; 3], right: [f32; 3]) -> [f32; 3] {
    [
        (left[0] + right[0]) * 0.5,
        (left[1] + right[1]) * 0.5,
        (left[2] + right[2]) * 0.5,
    ]
}

fn shell_radius(rank: u8) -> f32 {
    0.62 + rank.max(1) as f32 * 0.34
}

fn stable_unit(value: &str) -> f32 {
    stable_hash(value) as f32 / u32::MAX as f32
}

fn stable_signed(value: &str) -> f32 {
    stable_unit(value) * 2.0 - 1.0
}

fn stable_hash(value: &str) -> u32 {
    let mut hash = 2_166_136_261_u32;
    for byte in value.as_bytes() {
        hash ^= u32::from(*byte);
        hash = hash.wrapping_mul(16_777_619);
    }
    hash
}

fn pair_key(left: u32, right: u32) -> u64 {
    let a = left.min(right) as u64;
    let b = left.max(right) as u64;
    (a << 32) | b
}

fn count_for_wire(value: usize) -> u32 {
    u32::try_from(value).unwrap_or(u32::MAX)
}

fn bytes_len_f32(values: &[f32]) -> usize {
    values.len() * std::mem::size_of::<f32>()
}

fn bytes_len_u32(values: &[u32]) -> usize {
    values.len() * std::mem::size_of::<u32>()
}

fn encode_f32(values: &[f32]) -> String {
    let mut bytes = Vec::with_capacity(bytes_len_f32(values));
    for value in values {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    STANDARD.encode(bytes)
}

fn encode_u32(values: &[u32]) -> String {
    let mut bytes = Vec::with_capacity(bytes_len_u32(values));
    for value in values {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    STANDARD.encode(bytes)
}

#[cfg(test)]
mod tests {
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
        let ranks = STANDARD.decode(packet.hierarchy_shell_ranks.unwrap()).unwrap();
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

    fn node(id: &str, label: &str, source_type: &str) -> GraphScenePacketNodeInput {
        GraphScenePacketNodeInput {
            id: id.into(),
            label: label.into(),
            kind: label.into(),
            source_type: source_type.into(),
            vector: vec![0.1, 0.3, 0.5, 0.7],
            base_vector: None,
            total_mentions: Some(1),
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
}
