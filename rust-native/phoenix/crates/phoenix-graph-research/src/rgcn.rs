use crate::{
    FrozenGraphResearchError, FrozenModelError, FrozenModelFamily, FrozenModelMapped,
    FrozenModelTensor, FrozenTensorMapped, ResearchEvaluationError, TrainTopologyFeatureMapped,
    RGCN_DECODER_BIAS, RGCN_DECODER_RELATION, RGCN_NODE_TYPE_EMBEDDING, RGCN_RELATION_WEIGHT,
    RGCN_SELF_WEIGHT,
};
use hashbrown::{HashMap, HashSet};
use serde::{Deserialize, Serialize};
use std::time::Instant;
use wide::f32x8;

const HIDDEN: usize = 16;
const TRAIN_SPLIT: u8 = 1;
const VALIDATION_SPLIT: u8 = 2;
const TEST_SPLIT: u8 = 3;
const ASSERTED_AUTHORITY: u8 = 1;

#[derive(Clone, Debug, PartialEq)]
pub struct RgcnRelationBatch {
    pub sources: Vec<u32>,
    pub targets: Vec<u32>,
    pub normalizers: Vec<f32>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct RgcnGraphBatch {
    pub node_types: Vec<u32>,
    pub relation_batches: Vec<RgcnRelationBatch>,
    pub relation_count: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct RgcnQueryBatch {
    pub sources: Vec<u32>,
    pub targets: Vec<u32>,
    pub relations: Vec<u32>,
    pub labels: Vec<bool>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RgcnStagingProfile {
    pub source_edges: u64,
    pub train_message_edges: u64,
    pub train_queries: u64,
    pub validation_queries: u64,
    pub incidence_rows_validated: u64,
    pub staged_bytes: u64,
    pub staging_micros: u64,
    pub frozen_relation_batch_required: bool,
}

pub struct RgcnStagedInput {
    pub graph: RgcnGraphBatch,
    pub train: RgcnQueryBatch,
    pub validation: RgcnQueryBatch,
    pub profile: RgcnStagingProfile,
}

#[derive(Debug, thiserror::Error)]
pub enum RgcnResearchError {
    #[error("R-GCN input contract is invalid: {0}")]
    InvalidContract(&'static str),
    #[error("R-GCN tensor artifact failed validation: {0}")]
    Tensor(#[from] FrozenGraphResearchError),
    #[error("R-GCN topology artifact failed validation: {0}")]
    Topology(#[from] ResearchEvaluationError),
    #[error("R-GCN model artifact failed validation: {0}")]
    Model(#[from] FrozenModelError),
}

pub fn stage_rgcn_input(
    tensors: &FrozenTensorMapped,
    topology: &TrainTopologyFeatureMapped,
) -> Result<RgcnStagedInput, RgcnResearchError> {
    let started = Instant::now();
    if tensors.manifest().tensor_id != topology.manifest().source_tensor_id
        || tensors.manifest().source_dataset_id != topology.manifest().source_dataset_id
        || tensors.manifest().relation_vocabulary.is_empty()
        || tensors.manifest().node_type_vocabulary.is_empty()
    {
        return Err(RgcnResearchError::InvalidContract("source identity"));
    }
    let node_types = tensors
        .node_type_ids()?
        .iter()
        .map(|value| value.get())
        .collect::<Vec<_>>();
    let sources = tensors.coo_sources()?;
    let targets = tensors.coo_targets()?;
    let relations = tensors.coo_relation_types()?;
    let authorities = tensors.coo_authority()?;
    let splits = tensors.coo_splits()?;
    let weights = tensors.coo_weights()?;
    let incidence_hyperedges = tensors.incidence_hyperedges()?;
    let incidence_participants = tensors.incidence_participants()?;
    let incidence_roles = tensors.incidence_role_types()?;
    let incidence_splits = tensors.incidence_splits()?;
    let incidence_resolved = tensors.incidence_resolved()?;
    let negatives = tensors.negatives()?;
    let relation_count = u32::try_from(tensors.manifest().relation_vocabulary.len())
        .map_err(|_| RgcnResearchError::InvalidContract("relation count"))?;
    let role_count = u32::try_from(tensors.manifest().role_vocabulary.len())
        .map_err(|_| RgcnResearchError::InvalidContract("role count"))?;
    let message_kinds = relation_count
        .checked_add(role_count)
        .ok_or(RgcnResearchError::InvalidContract("message kind count"))?;
    if message_kinds > u32::MAX / 2
        || node_types
            .iter()
            .any(|value| *value as usize >= tensors.manifest().node_type_vocabulary.len())
    {
        return Err(RgcnResearchError::InvalidContract(
            "message or node type bounds",
        ));
    }
    let message_relations = usize::try_from(message_kinds)
        .ok()
        .and_then(|count| count.checked_mul(2))
        .ok_or(RgcnResearchError::InvalidContract("message relation count"))?;
    let mut counts = vec![0_usize; message_relations];
    let mut degrees = HashMap::<(u32, u32), u32>::new();
    let mut train_edges = 0_u64;
    for edge in 0..sources.len() {
        let relation = relations[edge].get();
        let source = sources[edge].get();
        let target = targets[edge].get();
        let weight = weights[edge].get();
        if !(TRAIN_SPLIT..=TEST_SPLIT).contains(&splits[edge])
            || ![ASSERTED_AUTHORITY, 2].contains(&authorities[edge])
            || !weight.is_finite()
        {
            return Err(RgcnResearchError::InvalidContract("edge metadata"));
        }
        validate_edge(source, target, relation, node_types.len(), relation_count)?;
        if splits[edge] != TRAIN_SPLIT || authorities[edge] != ASSERTED_AUTHORITY {
            continue;
        }
        let inverse = relation + message_kinds;
        counts[relation as usize] += 1;
        counts[inverse as usize] += 1;
        *degrees.entry((relation, target)).or_default() += 1;
        *degrees.entry((inverse, source)).or_default() += 1;
        train_edges += 1;
    }
    for incidence in 0..incidence_hyperedges.len() {
        let source = incidence_hyperedges[incidence].get();
        let target = incidence_participants[incidence].get();
        let role = incidence_roles[incidence].get();
        if !(TRAIN_SPLIT..=TEST_SPLIT).contains(&incidence_splits[incidence])
            || incidence_resolved[incidence] > 1
            || role >= role_count
            || source as usize >= node_types.len()
            || target as usize >= node_types.len()
        {
            return Err(RgcnResearchError::InvalidContract("incidence bounds"));
        }
        if incidence_splits[incidence] != TRAIN_SPLIT || incidence_resolved[incidence] == 0 {
            continue;
        }
        let relation = relation_count + role;
        let inverse = relation + message_kinds;
        counts[relation as usize] += 1;
        counts[inverse as usize] += 1;
        *degrees.entry((relation, target)).or_default() += 1;
        *degrees.entry((inverse, source)).or_default() += 1;
        train_edges += 1;
    }
    let mut batches = counts
        .into_iter()
        .map(|count| RgcnRelationBatch {
            sources: Vec::with_capacity(count),
            targets: Vec::with_capacity(count),
            normalizers: Vec::with_capacity(count),
        })
        .collect::<Vec<_>>();
    for edge in 0..sources.len() {
        if splits[edge] != TRAIN_SPLIT || authorities[edge] != ASSERTED_AUTHORITY {
            continue;
        }
        let relation = relations[edge].get();
        let source = sources[edge].get();
        let target = targets[edge].get();
        let weight = weights[edge].get();
        if !weight.is_finite() {
            return Err(RgcnResearchError::InvalidContract("edge weight"));
        }
        push_message(
            &mut batches[relation as usize],
            source,
            target,
            weight,
            degrees[&(relation, target)],
        );
        let inverse = relation + message_kinds;
        push_message(
            &mut batches[inverse as usize],
            target,
            source,
            weight,
            degrees[&(inverse, source)],
        );
    }
    for incidence in 0..incidence_hyperedges.len() {
        if incidence_splits[incidence] != TRAIN_SPLIT || incidence_resolved[incidence] == 0 {
            continue;
        }
        let source = incidence_hyperedges[incidence].get();
        let target = incidence_participants[incidence].get();
        let relation = relation_count + incidence_roles[incidence].get();
        push_message(
            &mut batches[relation as usize],
            source,
            target,
            1.0,
            degrees[&(relation, target)],
        );
        let inverse = relation + message_kinds;
        push_message(
            &mut batches[inverse as usize],
            target,
            source,
            1.0,
            degrees[&(inverse, source)],
        );
    }
    let rows = topology.link_rows()?;
    let mut train_count = 0_usize;
    let mut validation_count = 0_usize;
    for row in rows.iter() {
        match row.split() {
            TRAIN_SPLIT => train_count += 1,
            VALIDATION_SPLIT => validation_count += 1,
            TEST_SPLIT => {}
            _ => return Err(RgcnResearchError::InvalidContract("query split")),
        }
    }
    let mut train = RgcnQueryBatch::with_capacity(train_count);
    let mut validation = RgcnQueryBatch::with_capacity(validation_count);
    let mut negative_keys = HashSet::with_capacity(negatives.len());
    for negative in negatives.iter() {
        let positive = negative.positive_edge() as usize;
        let source = negative.source();
        let target = negative.target();
        let relation = negative.relation_type();
        let split = negative.split();
        if positive >= sources.len()
            || source != sources[positive].get()
            || relation != relations[positive].get()
            || split != splits[positive]
            || !(TRAIN_SPLIT..=TEST_SPLIT).contains(&split)
            || source as usize >= node_types.len()
            || target as usize >= node_types.len()
            || node_types[target as usize] != node_types[targets[positive].get() as usize]
        {
            return Err(RgcnResearchError::InvalidContract("negative sample"));
        }
        negative_keys.insert((negative.positive_edge(), target, relation, split));
    }
    for row in rows.iter() {
        let positive = row.positive_index() as usize;
        let source = sources
            .get(positive)
            .ok_or(RgcnResearchError::InvalidContract("positive edge"))?
            .get();
        let relation = relations[positive].get();
        let target = row.candidate();
        validate_edge(source, target, relation, node_types.len(), relation_count)?;
        if authorities[positive] != ASSERTED_AUTHORITY
            || splits[positive] != row.split()
            || (row.label() && target != targets[positive].get())
            || (!row.label()
                && !negative_keys.contains(&(row.positive_index(), target, relation, row.split())))
        {
            return Err(RgcnResearchError::InvalidContract("query authority"));
        }
        if row.split() == TEST_SPLIT {
            continue;
        }
        let target_batch = if row.split() == TRAIN_SPLIT {
            &mut train
        } else {
            &mut validation
        };
        target_batch.push(source, target, relation, row.label());
    }
    validate_query_labels(&train)?;
    validate_query_labels(&validation)?;
    let graph = RgcnGraphBatch {
        node_types,
        relation_batches: batches,
        relation_count,
    };
    let staged_bytes = graph
        .staged_bytes()
        .checked_add(train.staged_bytes())
        .and_then(|bytes| bytes.checked_add(validation.staged_bytes()))
        .ok_or(RgcnResearchError::InvalidContract("staged byte overflow"))?;
    let staging_micros = started.elapsed().as_micros().try_into().unwrap_or(u64::MAX);
    Ok(RgcnStagedInput {
        profile: RgcnStagingProfile {
            source_edges: sources.len() as u64,
            train_message_edges: train_edges * 2,
            train_queries: train.len() as u64,
            validation_queries: validation.len() as u64,
            incidence_rows_validated: incidence_hyperedges.len() as u64,
            staged_bytes,
            staging_micros,
            frozen_relation_batch_required: false,
        },
        graph,
        train,
        validation,
    })
}

pub fn score_rgcn16(
    model: &FrozenModelMapped,
    graph: &RgcnGraphBatch,
    queries: &RgcnQueryBatch,
) -> Result<Vec<f32>, RgcnResearchError> {
    if model.manifest().architecture.family != FrozenModelFamily::Rgcn16 {
        return Err(RgcnResearchError::InvalidContract("model family"));
    }
    let tensors = model.snapshot()?.tensors;
    score_rgcn16_tensors(&tensors, graph, queries)
}

pub fn score_rgcn16_tensors(
    tensors: &[FrozenModelTensor],
    graph: &RgcnGraphBatch,
    queries: &RgcnQueryBatch,
) -> Result<Vec<f32>, RgcnResearchError> {
    let weights = RgcnWeights::new(tensors, graph)?;
    validate_queries(queries, graph)?;
    let mut initial = vec![[0.0_f32; HIDDEN]; graph.node_types.len()];
    for (node, &node_type) in graph.node_types.iter().enumerate() {
        let start = node_type as usize * HIDDEN;
        initial[node].copy_from_slice(&weights.node_types[start..start + HIDDEN]);
    }
    let mut encoded = vec![[0.0_f32; HIDDEN]; initial.len()];
    for (target, features) in initial.iter().enumerate() {
        transform_add(&mut encoded[target], features, weights.self_weight, 1.0);
    }
    for (relation, batch) in graph.relation_batches.iter().enumerate() {
        let start = relation * HIDDEN * HIDDEN;
        let matrix = &weights.relation_weights[start..start + HIDDEN * HIDDEN];
        for edge in 0..batch.sources.len() {
            transform_add(
                &mut encoded[batch.targets[edge] as usize],
                &initial[batch.sources[edge] as usize],
                matrix,
                batch.normalizers[edge],
            );
        }
    }
    encoded.iter_mut().for_each(|row| {
        row.iter_mut().for_each(|value| *value = value.max(0.0));
    });
    let mut scores = Vec::with_capacity(queries.len());
    for index in 0..queries.len() {
        let relation = queries.relations[index] as usize;
        let decoder = &weights.decoder[relation * HIDDEN..(relation + 1) * HIDDEN];
        let logit = simd_triple(
            &encoded[queries.sources[index] as usize],
            &encoded[queries.targets[index] as usize],
            decoder,
        ) + weights.bias[relation];
        scores.push(sigmoid(logit));
    }
    Ok(scores)
}

impl RgcnQueryBatch {
    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            sources: Vec::with_capacity(capacity),
            targets: Vec::with_capacity(capacity),
            relations: Vec::with_capacity(capacity),
            labels: Vec::with_capacity(capacity),
        }
    }

    pub fn len(&self) -> usize {
        self.labels.len()
    }

    pub fn is_empty(&self) -> bool {
        self.labels.is_empty()
    }

    fn push(&mut self, source: u32, target: u32, relation: u32, label: bool) {
        self.sources.push(source);
        self.targets.push(target);
        self.relations.push(relation);
        self.labels.push(label);
    }

    fn staged_bytes(&self) -> u64 {
        (self.sources.capacity() * 4
            + self.targets.capacity() * 4
            + self.relations.capacity() * 4
            + self.labels.capacity()) as u64
    }
}

impl RgcnGraphBatch {
    fn staged_bytes(&self) -> u64 {
        let messages = self.relation_batches.iter().fold(0_usize, |total, batch| {
            total
                + batch.sources.capacity() * 4
                + batch.targets.capacity() * 4
                + batch.normalizers.capacity() * 4
        });
        (self.node_types.capacity() * 4 + messages) as u64
    }
}

fn push_message(batch: &mut RgcnRelationBatch, source: u32, target: u32, weight: f32, degree: u32) {
    batch.sources.push(source);
    batch.targets.push(target);
    batch.normalizers.push(weight / degree as f32);
}

fn validate_edge(
    source: u32,
    target: u32,
    relation: u32,
    nodes: usize,
    relations: u32,
) -> Result<(), RgcnResearchError> {
    if source as usize >= nodes || target as usize >= nodes || relation >= relations {
        return Err(RgcnResearchError::InvalidContract("edge bounds"));
    }
    Ok(())
}

fn validate_query_labels(queries: &RgcnQueryBatch) -> Result<(), RgcnResearchError> {
    if queries.is_empty()
        || !queries.labels.iter().any(|label| *label)
        || !queries.labels.iter().any(|label| !*label)
    {
        return Err(RgcnResearchError::InvalidContract("query labels"));
    }
    Ok(())
}

fn validate_queries(
    queries: &RgcnQueryBatch,
    graph: &RgcnGraphBatch,
) -> Result<(), RgcnResearchError> {
    if queries.sources.len() != queries.len()
        || queries.targets.len() != queries.len()
        || queries.relations.len() != queries.len()
    {
        return Err(RgcnResearchError::InvalidContract("query shape"));
    }
    for index in 0..queries.len() {
        validate_edge(
            queries.sources[index],
            queries.targets[index],
            queries.relations[index],
            graph.node_types.len(),
            graph.relation_count,
        )?;
    }
    Ok(())
}

struct RgcnWeights<'a> {
    node_types: &'a [f32],
    self_weight: &'a [f32],
    relation_weights: &'a [f32],
    decoder: &'a [f32],
    bias: &'a [f32],
}

impl<'a> RgcnWeights<'a> {
    fn new(
        tensors: &'a [FrozenModelTensor],
        graph: &RgcnGraphBatch,
    ) -> Result<Self, RgcnResearchError> {
        if tensors.len() != 5
            || tensors[0].name != RGCN_NODE_TYPE_EMBEDDING
            || tensors[1].name != RGCN_SELF_WEIGHT
            || tensors[2].name != RGCN_RELATION_WEIGHT
            || tensors[3].name != RGCN_DECODER_RELATION
            || tensors[4].name != RGCN_DECODER_BIAS
        {
            return Err(RgcnResearchError::InvalidContract("weight tensors"));
        }
        let relations = graph.relation_count as usize;
        let node_type_count = tensors[0].shape.first().copied().unwrap_or_default() as usize;
        let message_relations = graph.relation_batches.len();
        if tensors[0].shape != [node_type_count as u64, HIDDEN as u64]
            || tensors[1].shape != [HIDDEN as u64, HIDDEN as u64]
            || tensors[2].shape != [message_relations as u64, HIDDEN as u64, HIDDEN as u64]
            || tensors[3].shape != [relations as u64, HIDDEN as u64]
            || tensors[4].shape != [relations as u64]
            || tensors[0].values.len() != node_type_count * HIDDEN
            || tensors[1].values.len() != HIDDEN * HIDDEN
            || tensors[2].values.len() != message_relations * HIDDEN * HIDDEN
            || tensors[3].values.len() != relations * HIDDEN
            || tensors[4].values.len() != relations
            || tensors
                .iter()
                .any(|tensor| tensor.values.iter().any(|value| !value.is_finite()))
            || graph
                .node_types
                .iter()
                .any(|value| *value as usize >= node_type_count)
        {
            return Err(RgcnResearchError::InvalidContract("weight shapes"));
        }
        Ok(Self {
            node_types: &tensors[0].values,
            self_weight: &tensors[1].values,
            relation_weights: &tensors[2].values,
            decoder: &tensors[3].values,
            bias: &tensors[4].values,
        })
    }
}

fn transform_add(target: &mut [f32; HIDDEN], source: &[f32; HIDDEN], matrix: &[f32], scale: f32) {
    for (row, output) in target.iter_mut().enumerate() {
        let weights: &[f32; HIDDEN] = matrix[row * HIDDEN..(row + 1) * HIDDEN]
            .try_into()
            .expect("R-GCN matrix row");
        *output += simd_dot(weights, source) * scale;
    }
}

fn simd_dot(left: &[f32; HIDDEN], right: &[f32; HIDDEN]) -> f32 {
    let left_low: [f32; 8] = left[..8].try_into().expect("low left");
    let right_low: [f32; 8] = right[..8].try_into().expect("low right");
    let left_high: [f32; 8] = left[8..].try_into().expect("high left");
    let right_high: [f32; 8] = right[8..].try_into().expect("high right");
    let low: [f32; 8] = (f32x8::from(left_low) * f32x8::from(right_low)).into();
    let high: [f32; 8] = (f32x8::from(left_high) * f32x8::from(right_high)).into();
    low.into_iter().chain(high).sum()
}

fn simd_triple(left: &[f32; HIDDEN], right: &[f32; HIDDEN], relation: &[f32]) -> f32 {
    let relation: &[f32; HIDDEN] = relation.try_into().expect("decoder relation");
    let left_low: [f32; 8] = left[..8].try_into().expect("low left");
    let right_low: [f32; 8] = right[..8].try_into().expect("low right");
    let relation_low: [f32; 8] = relation[..8].try_into().expect("low relation");
    let left_high: [f32; 8] = left[8..].try_into().expect("high left");
    let right_high: [f32; 8] = right[8..].try_into().expect("high right");
    let relation_high: [f32; 8] = relation[8..].try_into().expect("high relation");
    let low: [f32; 8] =
        (f32x8::from(left_low) * f32x8::from(right_low) * f32x8::from(relation_low)).into();
    let high: [f32; 8] =
        (f32x8::from(left_high) * f32x8::from(right_high) * f32x8::from(relation_high)).into();
    low.into_iter().chain(high).sum()
}

fn sigmoid(value: f32) -> f32 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exp = value.exp();
        exp / (1.0 + exp)
    }
}
