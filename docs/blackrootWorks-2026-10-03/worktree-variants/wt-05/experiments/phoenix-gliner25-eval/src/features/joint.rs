use std::collections::{BTreeMap, BTreeSet};

use anyhow::{Result, bail};
use gliner25_rs::processor::{SchemaTask, TaskType};
use gliner25_rs::runtime::sigmoid;
use serde::{Deserialize, Serialize};

use super::{FeatureEngine, FeatureTrace};

type WordSpan = (usize, usize);
type RelationProposal = (usize, WordSpan, WordSpan);

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct JointEntitySpec {
    pub name: String,
    #[serde(default = "decision_threshold")]
    pub threshold: f32,
    #[serde(default = "candidate_threshold")]
    pub candidate_threshold: f32,
    #[serde(default)]
    pub allow_nested: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct JointRelationSpec {
    pub name: String,
    pub head: Vec<String>,
    pub tail: Vec<String>,
    #[serde(default = "decision_threshold")]
    pub threshold: f32,
    #[serde(default = "candidate_threshold")]
    pub candidate_threshold: f32,
    #[serde(default)]
    pub allow_self: bool,
    #[serde(default)]
    pub max_per_head: Option<usize>,
    #[serde(default)]
    pub max_per_tail: Option<usize>,
}

fn decision_threshold() -> f32 {
    0.5
}
fn candidate_threshold() -> f32 {
    0.05
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct JointSchemaSpec {
    pub entities: Vec<JointEntitySpec>,
    pub relations: Vec<JointRelationSpec>,
    #[serde(default = "default_true")]
    pub no_self_loops: bool,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct JointConfig {
    #[serde(default = "beam_width")]
    pub beam_width: usize,
    #[serde(default = "top_entities")]
    pub top_k_entities: usize,
    #[serde(default = "top_roles")]
    pub top_k_roles: usize,
}

fn beam_width() -> usize {
    32
}
fn top_entities() -> usize {
    32
}
fn top_roles() -> usize {
    12
}

impl Default for JointConfig {
    fn default() -> Self {
        Self {
            beam_width: beam_width(),
            top_k_entities: top_entities(),
            top_k_roles: top_roles(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct JointEntity {
    pub id: String,
    #[serde(rename = "type")]
    pub entity_type: String,
    pub text: String,
    pub start: usize,
    pub end: usize,
    pub confidence: f32,
}

#[derive(Debug, Clone, Serialize)]
pub struct JointRelation {
    #[serde(rename = "type")]
    pub relation_type: String,
    pub head: String,
    pub tail: String,
    pub confidence: f32,
}

#[derive(Debug, Clone, Serialize)]
pub struct JointOutput {
    pub entities: Vec<JointEntity>,
    pub relations: Vec<JointRelation>,
    pub feasible: bool,
}

#[derive(Debug, Clone)]
struct Node {
    entity_type: String,
    word_start: usize,
    word_end: usize,
    char_start: usize,
    char_end: usize,
    logit: f32,
    probability: f32,
}

impl Node {
    fn key(&self) -> (String, usize, usize) {
        (self.entity_type.clone(), self.word_start, self.word_end)
    }
}

#[derive(Debug, Clone)]
struct Edge {
    relation_type: String,
    relation_index: usize,
    head: (String, usize, usize),
    tail: (String, usize, usize),
    logit: f32,
    probability: f32,
    max_per_head: Option<usize>,
    max_per_tail: Option<usize>,
}

#[derive(Clone, Default)]
struct BeamState {
    nodes: BTreeSet<(String, usize, usize)>,
    edges: Vec<usize>,
    score: f32,
}

impl FeatureEngine {
    pub fn extract_joint(
        &mut self,
        text: &str,
        schema: &JointSchemaSpec,
        config: &JointConfig,
    ) -> Result<JointOutput> {
        validate_schema(schema, config)?;
        let entity_names: Vec<String> = schema
            .entities
            .iter()
            .map(|value| value.name.clone())
            .collect();
        let mut tasks = vec![SchemaTask::Entities(entity_names.clone())];
        tasks.extend(schema.relations.iter().map(|relation| {
            SchemaTask::Relations(relation.name.clone(), vec!["head".into(), "tail".into()])
        }));
        let trace = self.trace(text, &tasks)?;
        let entity_queries: BTreeMap<String, usize> = entity_names
            .iter()
            .map(|name| {
                let query = trace
                    .query_id(TaskType::Entities, "entities", name)
                    .ok_or_else(|| anyhow::anyhow!("missing entity query {name}"))?;
                Ok((name.clone(), query))
            })
            .collect::<Result<_>>()?;
        let relation_roles: Vec<(usize, usize)> = schema
            .relations
            .iter()
            .map(|relation| {
                let head = trace
                    .query_id(TaskType::Relations, &relation.name, "head")
                    .ok_or_else(|| anyhow::anyhow!("missing head role for {}", relation.name))?;
                let tail = trace
                    .query_id(TaskType::Relations, &relation.name, "tail")
                    .ok_or_else(|| anyhow::anyhow!("missing tail role for {}", relation.name))?;
                Ok((head, tail))
            })
            .collect::<Result<_>>()?;

        let mut nodes = collect_entity_nodes(self, &trace, schema, &entity_queries, config);
        let proposals = relation_proposals(self, &trace, schema, &relation_roles, config);
        let endpoint_spans: Vec<(usize, usize)> = proposals
            .iter()
            .flat_map(|(_, head, tail)| [*head, *tail])
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        if !endpoint_spans.is_empty() {
            let query_ids: Vec<usize> = schema
                .entities
                .iter()
                .map(|value| entity_queries[&value.name])
                .collect();
            let logits = self.explicit_logits(&trace, &query_ids, &endpoint_spans)?;
            for (entity_index, entity) in schema.entities.iter().enumerate() {
                for (span_index, &(start, end)) in endpoint_spans.iter().enumerate() {
                    let logit = logits[entity_index * endpoint_spans.len() + span_index];
                    let probability = sigmoid(logit);
                    insert_best_node(
                        &mut nodes,
                        node_from_span(&trace, &entity.name, start, end, logit, probability),
                    );
                }
            }
        }

        let relation_states = self.relation_states(&trace, &relation_roles)?;
        let pair_rows: Vec<[i64; 5]> = proposals
            .iter()
            .map(|&(relation, head, tail)| {
                [
                    relation as i64,
                    head.0 as i64,
                    head.1 as i64,
                    tail.0 as i64,
                    tail.1 as i64,
                ]
            })
            .collect();
        let relation_logits =
            self.relation_logits(&trace, &relation_states, schema.relations.len(), &pair_rows)?;
        let mut edges = Vec::new();
        for ((relation_index, head_span, tail_span), logit) in
            proposals.into_iter().zip(relation_logits)
        {
            let relation = &schema.relations[relation_index];
            let probability = sigmoid(logit);
            if probability < relation.candidate_threshold {
                continue;
            }
            for head_type in &relation.head {
                for tail_type in &relation.tail {
                    let head = (head_type.clone(), head_span.0, head_span.1);
                    let tail = (tail_type.clone(), tail_span.0, tail_span.1);
                    if !nodes.contains_key(&head) || !nodes.contains_key(&tail) {
                        continue;
                    }
                    edges.push(Edge {
                        relation_type: relation.name.clone(),
                        relation_index,
                        head,
                        tail,
                        logit: logit - probability_to_logit(relation.threshold),
                        probability,
                        max_per_head: relation.max_per_head,
                        max_per_tail: relation.max_per_tail,
                    });
                }
            }
        }
        edges.sort_by(|a, b| {
            b.logit
                .partial_cmp(&a.logit)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.relation_type.cmp(&b.relation_type))
                .then(a.head.cmp(&b.head))
                .then(a.tail.cmp(&b.tail))
        });
        let selected = beam_decode(&nodes, &edges, schema, config.beam_width);
        Ok(build_output(text, &nodes, &edges, selected))
    }
}

fn collect_entity_nodes(
    engine: &FeatureEngine,
    trace: &FeatureTrace,
    schema: &JointSchemaSpec,
    entity_queries: &BTreeMap<String, usize>,
    config: &JointConfig,
) -> BTreeMap<(String, usize, usize), Node> {
    let pool = engine.manifest().pool_size;
    let mut per_type: BTreeMap<String, Vec<Node>> = BTreeMap::new();
    for entity in &schema.entities {
        let query = entity_queries[&entity.name];
        for candidate in 0..pool {
            let offset = query * pool + candidate;
            if !trace.cand_valid[offset] {
                continue;
            }
            let start = trace.cand_indices[offset * 2] as usize;
            let end = trace.cand_indices[offset * 2 + 1] as usize;
            if end <= start || end > trace.num_words() {
                continue;
            }
            let logit = trace.pair_logits[offset] / engine.manifest().pair_temperature;
            let probability = sigmoid(logit);
            if probability < entity.candidate_threshold {
                continue;
            }
            per_type
                .entry(entity.name.clone())
                .or_default()
                .push(node_from_span(
                    trace,
                    &entity.name,
                    start,
                    end,
                    logit - probability_to_logit(entity.threshold),
                    probability,
                ));
        }
    }
    let mut output = BTreeMap::new();
    for values in per_type.values_mut() {
        values.sort_by(|a, b| {
            b.probability
                .partial_cmp(&a.probability)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.word_start.cmp(&b.word_start))
                .then(a.word_end.cmp(&b.word_end))
        });
        for node in values.drain(..).take(config.top_k_entities) {
            insert_best_node(&mut output, node);
        }
    }
    output
}

fn relation_proposals(
    engine: &FeatureEngine,
    trace: &FeatureTrace,
    schema: &JointSchemaSpec,
    roles: &[WordSpan],
    config: &JointConfig,
) -> Vec<RelationProposal> {
    let pool = engine.manifest().pool_size;
    let threshold = engine.manifest().relation_argument_proposal_threshold;
    let mut output = Vec::new();
    for (relation_index, &(head_query, tail_query)) in roles.iter().enumerate() {
        let candidates = |query: usize| {
            let mut values: Vec<(f32, (usize, usize))> = (0..pool)
                .filter_map(|candidate| {
                    let offset = query * pool + candidate;
                    if !trace.cand_valid[offset] {
                        return None;
                    }
                    let start = trace.cand_indices[offset * 2] as usize;
                    let end = trace.cand_indices[offset * 2 + 1] as usize;
                    if end <= start || end > trace.num_words() {
                        return None;
                    }
                    let probability = sigmoid(trace.pair_logits[offset]);
                    (probability >= threshold).then_some((probability, (start, end)))
                })
                .collect();
            values.sort_by(|a, b| {
                b.0.partial_cmp(&a.0)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then(a.1.cmp(&b.1))
            });
            values.truncate(
                config
                    .top_k_roles
                    .min(engine.manifest().relation_heads_per_type),
            );
            values
        };
        let heads = candidates(head_query);
        let tails = candidates(tail_query);
        let relation = &schema.relations[relation_index];
        let mut pairs = Vec::new();
        for &(head_probability, head) in &heads {
            for &(tail_probability, tail) in &tails {
                if (schema.no_self_loops || !relation.allow_self) && head == tail {
                    continue;
                }
                pairs.push((head_probability * tail_probability, head, tail));
            }
        }
        pairs.sort_by(|a, b| {
            b.0.partial_cmp(&a.0)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.1.cmp(&b.1))
                .then(a.2.cmp(&b.2))
        });
        output.extend(
            pairs
                .into_iter()
                .take(engine.manifest().relation_pair_cap)
                .map(|(_, head, tail)| (relation_index, head, tail)),
        );
    }
    output
}

fn beam_decode(
    nodes: &BTreeMap<(String, usize, usize), Node>,
    edges: &[Edge],
    schema: &JointSchemaSpec,
    width: usize,
) -> BeamState {
    let mut beam = vec![BeamState::default()];
    for (edge_index, edge) in edges.iter().enumerate() {
        let mut expanded = beam.clone();
        for state in &beam {
            if !edge_allowed(edge, state, edges) {
                continue;
            }
            let mut proposed = state.clone();
            let mut gain = edge.logit;
            for key in [&edge.head, &edge.tail] {
                if !proposed.nodes.contains(key) {
                    let node = &nodes[key];
                    if overlaps_selected(node, &proposed.nodes, nodes, schema) {
                        gain = f32::NEG_INFINITY;
                        break;
                    }
                    proposed.nodes.insert(key.clone());
                    gain += node.logit;
                }
            }
            if !gain.is_finite() || gain < 0.0 {
                continue;
            }
            proposed.edges.push(edge_index);
            proposed.score += gain;
            expanded.push(proposed);
        }
        expanded.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.nodes.cmp(&b.nodes))
                .then(a.edges.cmp(&b.edges))
        });
        expanded.dedup_by(|a, b| a.nodes == b.nodes && a.edges == b.edges);
        expanded.truncate(width);
        beam = expanded;
    }
    for state in &mut beam {
        for (key, node) in nodes.iter().filter(|(_, node)| node.logit > 0.0) {
            if state.nodes.contains(key) || overlaps_selected(node, &state.nodes, nodes, schema) {
                continue;
            }
            state.nodes.insert(key.clone());
            state.score += node.logit;
        }
    }
    beam.into_iter()
        .max_by(|a, b| {
            a.score
                .partial_cmp(&b.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .unwrap_or_default()
}

fn edge_allowed(edge: &Edge, state: &BeamState, edges: &[Edge]) -> bool {
    if state.edges.iter().any(|&index| {
        let selected = &edges[index];
        selected.relation_type == edge.relation_type
            && selected.head == edge.head
            && selected.tail == edge.tail
    }) {
        return false;
    }
    if edge.max_per_head.is_some_and(|max| {
        state
            .edges
            .iter()
            .filter(|&&index| {
                edges[index].relation_index == edge.relation_index && edges[index].head == edge.head
            })
            .count()
            >= max
    }) {
        return false;
    }
    if edge.max_per_tail.is_some_and(|max| {
        state
            .edges
            .iter()
            .filter(|&&index| {
                edges[index].relation_index == edge.relation_index && edges[index].tail == edge.tail
            })
            .count()
            >= max
    }) {
        return false;
    }
    true
}

fn overlaps_selected(
    node: &Node,
    selected: &BTreeSet<(String, usize, usize)>,
    nodes: &BTreeMap<(String, usize, usize), Node>,
    schema: &JointSchemaSpec,
) -> bool {
    let policy_allow = schema.entities.iter().all(|value| value.allow_nested);
    selected.iter().any(|key| {
        let other = &nodes[key];
        if node.word_end <= other.word_start || other.word_end <= node.word_start {
            return false;
        }
        if policy_allow {
            let nested = (node.word_start <= other.word_start && other.word_end <= node.word_end)
                || (other.word_start <= node.word_start && node.word_end <= other.word_end);
            !nested
        } else {
            true
        }
    })
}

fn build_output(
    text: &str,
    nodes: &BTreeMap<(String, usize, usize), Node>,
    edges: &[Edge],
    state: BeamState,
) -> JointOutput {
    let mut selected: Vec<&Node> = state
        .nodes
        .iter()
        .filter_map(|key| nodes.get(key))
        .collect();
    selected.sort_by(|a, b| {
        a.char_start
            .cmp(&b.char_start)
            .then(a.char_end.cmp(&b.char_end))
            .then(a.entity_type.cmp(&b.entity_type))
    });
    let mut ids = BTreeMap::new();
    let entities: Vec<JointEntity> = selected
        .iter()
        .enumerate()
        .map(|(index, node)| {
            let id = format!("e{}", index + 1);
            ids.insert(node.key(), id.clone());
            JointEntity {
                id,
                entity_type: node.entity_type.clone(),
                text: text[node.char_start..node.char_end].into(),
                start: node.char_start,
                end: node.char_end,
                confidence: node.probability,
            }
        })
        .collect();
    let mut relations: Vec<JointRelation> = state
        .edges
        .iter()
        .filter_map(|&index| {
            let edge = &edges[index];
            Some(JointRelation {
                relation_type: edge.relation_type.clone(),
                head: ids.get(&edge.head)?.clone(),
                tail: ids.get(&edge.tail)?.clone(),
                confidence: edge.probability,
            })
        })
        .collect();
    relations.sort_by(|a, b| {
        a.relation_type
            .cmp(&b.relation_type)
            .then(a.head.cmp(&b.head))
            .then(a.tail.cmp(&b.tail))
    });
    JointOutput {
        entities,
        relations,
        feasible: true,
    }
}

fn node_from_span(
    trace: &FeatureTrace,
    entity_type: &str,
    start: usize,
    end: usize,
    logit: f32,
    probability: f32,
) -> Node {
    let (char_start, _) = trace.record.word_to_char_maps[start];
    let (_, char_end) = trace.record.word_to_char_maps[end - 1];
    Node {
        entity_type: entity_type.into(),
        word_start: start,
        word_end: end,
        char_start,
        char_end,
        logit,
        probability,
    }
}

fn insert_best_node(nodes: &mut BTreeMap<(String, usize, usize), Node>, node: Node) {
    let key = node.key();
    if nodes.get(&key).is_none_or(|old| node.logit > old.logit) {
        nodes.insert(key, node);
    }
}

fn probability_to_logit(value: f32) -> f32 {
    let value = value.clamp(1e-6, 1.0 - 1e-6);
    (value / (1.0 - value)).ln()
}

fn validate_schema(schema: &JointSchemaSpec, config: &JointConfig) -> Result<()> {
    if schema.entities.is_empty() {
        bail!("joint IE requires at least one entity type");
    }
    if config.beam_width == 0 || config.top_k_entities == 0 || config.top_k_roles == 0 {
        bail!("joint IE caps must be positive");
    }
    let names: BTreeSet<&str> = schema
        .entities
        .iter()
        .map(|value| value.name.as_str())
        .collect();
    if names.len() != schema.entities.len() {
        bail!("duplicate entity type");
    }
    for relation in &schema.relations {
        if relation
            .head
            .iter()
            .chain(&relation.tail)
            .any(|value| !names.contains(value.as_str()))
        {
            bail!(
                "relation {} references an unknown endpoint type",
                relation.name
            );
        }
    }
    Ok(())
}
