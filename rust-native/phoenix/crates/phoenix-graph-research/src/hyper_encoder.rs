use crate::external_dataset_artifact::ExternalQualifierRecord;
use crate::{
    evaluate_hyper_relational_validation_batched, ExternalDatasetKind, ExternalDatasetMapped,
    ExternalFactSplit, HyperEncoderConfig, HyperEncoderError, HyperEncoderMode,
    HyperEncoderPairResult, HyperEncoderStagingProfile, HyperEncoderWeights,
    HyperRelationalCandidatePolicy, HyperRelationalQueryView, HyperRelationalTaskMapped,
    DEFAULT_HYPER_RELATIONAL_QUERY_BATCH, HYPER_ENCODER_DIRECTIONS, HYPER_ENCODER_HIDDEN,
    HYPER_ENCODER_SCHEMA,
};
use compact_str::CompactString;
use hashbrown::HashMap;
use std::time::Instant;
use wide::f32x8;

const HIDDEN: usize = HYPER_ENCODER_HIDDEN;
const MATRIX: usize = HIDDEN * HIDDEN;
const LANES: usize = 8;

#[derive(Clone, Debug)]
pub struct HyperRelationBatch {
    pub sources: Vec<u32>,
    pub targets: Vec<u32>,
    pub qualifier_offsets: Vec<u32>,
    pub qualifier_counts: Vec<u32>,
    pub normalizers: Vec<f32>,
}

pub struct HyperEncoderStagedInput {
    pub relation_batches: Vec<HyperRelationBatch>,
    pub canonical_qualifier_refs: Vec<u32>,
    pub shuffled_qualifier_refs: Vec<u32>,
    pub profile: HyperEncoderStagingProfile,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_id: CompactString,
    pub task_binary_blake3: CompactString,
    pub candidate_universe: u32,
    pub base_relation_count: u32,
}

pub struct HyperEncoderEncoded {
    model_id: CompactString,
    task_id: CompactString,
    mode: HyperEncoderMode,
    nodes: Vec<[f32; HIDDEN]>,
    candidate_planes: Vec<f32>,
    candidate_stride: usize,
    relation_states: Vec<[f32; HIDDEN]>,
    node_embeddings: Vec<f32>,
    relation_embeddings: Vec<f32>,
    qualifier_projection: Vec<f32>,
    decoder_bias: Vec<f32>,
    canonical_qualifier_refs: Vec<u32>,
}

pub fn stage_hyper_encoder(
    source: &ExternalDatasetMapped,
    task: &HyperRelationalTaskMapped,
) -> Result<HyperEncoderStagedInput, HyperEncoderError> {
    let started = Instant::now();
    let source_manifest = source.manifest();
    let task_manifest = task.manifest();
    if source_manifest.kind != ExternalDatasetKind::HyperRelationalKnowledgeGraph
        || source_manifest.dataset_id != task_manifest.source_dataset_id
        || source_manifest.binary_blake3 != task_manifest.source_binary_blake3
        || task_manifest.derived_relation_count != task_manifest.base_relation_count * 2
        || !task_manifest.qualifiers_borrowed_from_source
    {
        return Err(HyperEncoderError::InvalidContract("source authority"));
    }
    let facts = source.facts()?;
    let qualifiers = source.qualifiers()?;
    let nodes = task_manifest.candidate_universe;
    let base = task_manifest.base_relation_count;
    let directed = task_manifest.derived_relation_count as usize;
    let mut counts = vec![0_usize; directed];
    let mut degrees = HashMap::<(u32, u32), u32>::new();
    let mut canonical_refs = (0..qualifiers.len() as u32).collect::<Vec<_>>();
    let mut topology = blake3::Hasher::new();
    let mut train = 0_u64;
    for fact in facts.iter().copied() {
        validate_fact(fact.subject(), fact.predicate(), fact.object(), nodes, base)?;
        canonicalize_range(
            &mut canonical_refs,
            &qualifiers,
            fact.qualifier_offset(),
            fact.qualifier_count(),
        )?;
        if fact.split() != ExternalFactSplit::Train as u8 {
            continue;
        }
        let inverse = fact.predicate() + base;
        counts[fact.predicate() as usize] += 1;
        counts[inverse as usize] += 1;
        *degrees
            .entry((fact.predicate(), fact.object()))
            .or_default() += 1;
        *degrees.entry((inverse, fact.subject())).or_default() += 1;
        topology.update(&fact.subject().to_le_bytes());
        topology.update(&fact.predicate().to_le_bytes());
        topology.update(&fact.object().to_le_bytes());
        let start = fact.qualifier_offset() as usize;
        let end = start + fact.qualifier_count() as usize;
        for reference in &canonical_refs[start..end] {
            let qualifier = qualifiers[*reference as usize];
            topology.update(&qualifier.predicate().to_le_bytes());
            topology.update(&qualifier.object().to_le_bytes());
        }
        train += 1;
    }
    if train == 0 {
        return Err(HyperEncoderError::InvalidContract("empty train split"));
    }
    let shuffled_refs = shuffled_qualifier_refs(&facts, &canonical_refs);
    let mut batches = counts.into_iter().map(empty_batch).collect::<Vec<_>>();
    for fact in facts
        .iter()
        .copied()
        .filter(|fact| fact.split() == ExternalFactSplit::Train as u8)
    {
        let inverse = fact.predicate() + base;
        push_message(
            &mut batches[fact.predicate() as usize],
            fact.subject(),
            fact.object(),
            fact,
            degrees[&(fact.predicate(), fact.object())],
        );
        push_message(
            &mut batches[inverse as usize],
            fact.object(),
            fact.subject(),
            fact,
            degrees[&(inverse, fact.subject())],
        );
    }
    let staged_bytes = batches.iter().map(batch_bytes).sum::<usize>()
        + (canonical_refs.capacity() + shuffled_refs.capacity()) * size_of::<u32>();
    Ok(HyperEncoderStagedInput {
        relation_batches: batches,
        canonical_qualifier_refs: canonical_refs,
        shuffled_qualifier_refs: shuffled_refs,
        profile: HyperEncoderStagingProfile {
            train_statements: train,
            directed_messages: train * 2,
            canonical_qualifier_refs: qualifiers.len() as u64,
            canonical_ref_bytes: (qualifiers.len() * size_of::<u32>()) as u64,
            staged_bytes: staged_bytes as u64,
            staging_micros: started.elapsed().as_micros().try_into().unwrap_or(u64::MAX),
            train_topology_blake3: format!("b3-{}", topology.finalize().to_hex()).into(),
            original_filter_order_preserved: true,
            qualifier_payload_bytes_copied: 0,
            train_only: true,
        },
        source_dataset_id: source_manifest.dataset_id.clone(),
        source_binary_blake3: source_manifest.binary_blake3.clone(),
        task_id: task_manifest.task_id.clone(),
        task_binary_blake3: task_manifest.binary_blake3.clone(),
        candidate_universe: nodes,
        base_relation_count: base,
    })
}

pub fn initialize_hyper_encoder_weights(
    staged: &HyperEncoderStagedInput,
    seed: u64,
) -> HyperEncoderWeights {
    let nodes = staged.candidate_universe as usize;
    let relations = staged.relation_batches.len();
    let mut random = SplitMix64(seed);
    HyperEncoderWeights {
        node_embeddings: random.values(nodes * HIDDEN, 0.08),
        direction_weights: random.values(HYPER_ENCODER_DIRECTIONS * MATRIX, 0.08),
        relation_embeddings: random.values((relations + 1) * HIDDEN, 0.08),
        relation_projection: random.values(MATRIX, 0.08),
        qualifier_projection: random.values(MATRIX, 0.08),
        decoder_bias: vec![0.0; relations],
    }
}

pub fn hyper_encoder_model_identity(
    staged: &HyperEncoderStagedInput,
    config: HyperEncoderConfig,
    weights: &HyperEncoderWeights,
) -> Result<CompactString, HyperEncoderError> {
    hyper_encoder_model_identity_from_authority(
        staged.source_dataset_id.as_str(),
        staged.source_binary_blake3.as_str(),
        staged.task_id.as_str(),
        staged.task_binary_blake3.as_str(),
        config,
        weights,
    )
}

pub fn hyper_encoder_model_identity_from_authority(
    source_dataset_id: &str,
    source_binary_blake3: &str,
    task_id: &str,
    task_binary_blake3: &str,
    config: HyperEncoderConfig,
    weights: &HyperEncoderWeights,
) -> Result<CompactString, HyperEncoderError> {
    let mut hasher = blake3::Hasher::new();
    hasher.update(HYPER_ENCODER_SCHEMA.as_bytes());
    hasher.update(source_dataset_id.as_bytes());
    hasher.update(source_binary_blake3.as_bytes());
    hasher.update(task_id.as_bytes());
    hasher.update(task_binary_blake3.as_bytes());
    hasher.update(&serde_json::to_vec(&config)?);
    for tensor in [
        &weights.node_embeddings,
        &weights.direction_weights,
        &weights.relation_embeddings,
        &weights.relation_projection,
        &weights.qualifier_projection,
        &weights.decoder_bias,
    ] {
        for value in tensor {
            hasher.update(&value.to_bits().to_le_bytes());
        }
    }
    Ok(format!("b3-{}", hasher.finalize().to_hex()).into())
}

pub fn encode_hyper_encoder(
    source: &ExternalDatasetMapped,
    staged: &HyperEncoderStagedInput,
    config: HyperEncoderConfig,
    weights: &HyperEncoderWeights,
) -> Result<HyperEncoderEncoded, HyperEncoderError> {
    validate_weights(staged, weights)?;
    let qualifiers = source.qualifiers()?;
    let nodes_len = staged.candidate_universe as usize;
    let relations = staged.relation_batches.len();
    let mut nodes = vec![[0.0; HIDDEN]; nodes_len];
    let mut composed = [0.0; HIDDEN];
    let self_relation = row(&weights.relation_embeddings, relations);
    for (node, output) in nodes.iter_mut().enumerate() {
        multiply(
            &mut composed,
            row(&weights.node_embeddings, node),
            self_relation,
        );
        transform_add(
            output,
            &composed,
            matrix(&weights.direction_weights, 2),
            1.0,
        );
    }
    for (relation, batch) in staged.relation_batches.iter().enumerate() {
        let direction = usize::from(relation >= staged.base_relation_count as usize);
        for edge in 0..batch.sources.len() {
            let mut merged = copy_row(&weights.relation_embeddings, relation);
            if config.mode.uses_message_qualifiers() {
                add_qualifier_state(
                    &mut merged,
                    weights,
                    staged,
                    &qualifiers,
                    batch.qualifier_offsets[edge],
                    batch.qualifier_counts[edge],
                    config.mode,
                );
            }
            multiply(
                &mut composed,
                row(&weights.node_embeddings, batch.sources[edge] as usize),
                &merged,
            );
            transform_add(
                &mut nodes[batch.targets[edge] as usize],
                &composed,
                matrix(&weights.direction_weights, direction),
                batch.normalizers[edge],
            );
        }
    }
    for node in &mut nodes {
        for value in node {
            *value = value.max(0.0);
        }
    }
    let relation_states = (0..relations)
        .map(|relation| {
            let mut output = [0.0; HIDDEN];
            transform_add(
                &mut output,
                row(&weights.relation_embeddings, relation),
                &weights.relation_projection,
                1.0,
            );
            output
        })
        .collect::<Vec<_>>();
    let (candidate_planes, candidate_stride) = transpose_candidates(&nodes);
    Ok(HyperEncoderEncoded {
        model_id: hyper_encoder_model_identity(staged, config, weights)?,
        task_id: staged.task_id.clone(),
        mode: config.mode,
        nodes,
        candidate_planes,
        candidate_stride,
        relation_states,
        node_embeddings: weights.node_embeddings.clone(),
        relation_embeddings: weights.relation_embeddings.clone(),
        qualifier_projection: weights.qualifier_projection.clone(),
        decoder_bias: weights.decoder_bias.clone(),
        canonical_qualifier_refs: qualifier_refs(staged, config.mode).to_vec(),
    })
}

impl HyperEncoderEncoded {
    pub fn model_id(&self) -> &str {
        self.model_id.as_str()
    }
    pub fn task_id(&self) -> &str {
        self.task_id.as_str()
    }
    pub fn candidate_plane_bytes(&self) -> usize {
        self.candidate_planes.len() * size_of::<f32>()
    }

    pub fn score_candidate_batch(
        &self,
        source: &ExternalDatasetMapped,
        queries: &[HyperRelationalQueryView],
        candidates: &[u32],
        scores: &mut [f32],
    ) -> Result<(), String> {
        if scores.len() != queries.len() * candidates.len()
            || candidates
                .iter()
                .enumerate()
                .any(|(index, value)| *value as usize != index)
        {
            return Err("hyper encoder requires canonical candidates".into());
        }
        let qualifiers = source.qualifiers().map_err(|error| error.to_string())?;
        for (query, output) in queries
            .iter()
            .zip(scores.chunks_exact_mut(candidates.len()))
        {
            if query.source as usize >= self.nodes.len()
                || query.relation as usize >= self.relation_states.len()
            {
                return Err("hyper encoder query bounds".into());
            }
            let mut relation = self.relation_states[query.relation as usize];
            if self.mode.uses_query_qualifiers() {
                self.add_query_qualifiers(
                    &mut relation,
                    &qualifiers,
                    query.qualifier_offset,
                    query.qualifier_count,
                )?;
            }
            let mut features = [0.0; HIDDEN];
            multiply(&mut features, &self.nodes[query.source as usize], &relation);
            for start in (0..candidates.len()).step_by(LANES) {
                let block =
                    self.score_block(&features, self.decoder_bias[query.relation as usize], start);
                let valid = (candidates.len() - start).min(LANES);
                output[start..start + valid].copy_from_slice(&block[..valid]);
            }
        }
        Ok(())
    }

    fn add_query_qualifiers(
        &self,
        relation: &mut [f32; HIDDEN],
        qualifiers: &[ExternalQualifierRecord],
        offset: u32,
        count: u32,
    ) -> Result<(), String> {
        let range = checked_range(offset, count, self.canonical_qualifier_refs.len())
            .ok_or("qualifier range")?;
        let mut sum = [0.0; HIDDEN];
        for reference in &self.canonical_qualifier_refs[range] {
            let qualifier = qualifiers
                .get(*reference as usize)
                .ok_or("qualifier reference")?;
            for (feature, value) in sum.iter_mut().enumerate() {
                *value += qualifier_product(
                    self.mode,
                    self.node_embeddings[qualifier.object() as usize * HIDDEN + feature],
                    self.relation_embeddings[qualifier.predicate() as usize * HIDDEN + feature],
                );
            }
        }
        let mut projected = [0.0; HIDDEN];
        transform_add(&mut projected, &sum, &self.qualifier_projection, 1.0);
        for (target, value) in relation.iter_mut().zip(projected) {
            *target += value;
        }
        Ok(())
    }

    fn score_block(&self, features: &[f32; HIDDEN], bias: f32, start: usize) -> [f32; LANES] {
        let mut sum = f32x8::ZERO;
        for (feature, query_feature) in features.iter().copied().enumerate() {
            let plane = feature * self.candidate_stride + start;
            let target = f32x8::from(
                <[f32; LANES]>::try_from(&self.candidate_planes[plane..plane + LANES])
                    .expect("candidate plane"),
            );
            sum += f32x8::from([query_feature; LANES]) * target;
        }
        (sum + f32x8::from([bias; LANES])).into()
    }
}

pub fn evaluate_hyper_encoder_pair(
    source: &ExternalDatasetMapped,
    task: &HyperRelationalTaskMapped,
    staged: &HyperEncoderStagedInput,
    seed: u64,
    policy: HyperRelationalCandidatePolicy,
) -> Result<HyperEncoderPairResult, HyperEncoderError> {
    let weights = initialize_hyper_encoder_weights(staged, seed);
    let compgcn =
        encode_hyper_encoder(source, staged, HyperEncoderConfig::compgcn(seed), &weights)?;
    let stare = encode_hyper_encoder(source, staged, HyperEncoderConfig::stare(seed), &weights)?;
    let control_score = evaluate_hyper_relational_validation_batched(
        task,
        compgcn.model_id(),
        policy,
        DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
        |queries, candidates, scores| {
            compgcn.score_candidate_batch(source, queries, candidates, scores)
        },
    )?;
    let stare_score = evaluate_hyper_relational_validation_batched(
        task,
        stare.model_id(),
        policy,
        DEFAULT_HYPER_RELATIONAL_QUERY_BATCH,
        |queries, candidates, scores| {
            stare.score_candidate_batch(source, queries, candidates, scores)
        },
    )?;
    Ok(HyperEncoderPairResult {
        compgcn_model_id: compgcn.model_id,
        stare_model_id: stare.model_id,
        compgcn: control_score,
        stare: stare_score,
    })
}

fn add_qualifier_state(
    target: &mut [f32; HIDDEN],
    weights: &HyperEncoderWeights,
    staged: &HyperEncoderStagedInput,
    qualifiers: &[ExternalQualifierRecord],
    offset: u32,
    count: u32,
    mode: HyperEncoderMode,
) {
    let mut sum = [0.0; HIDDEN];
    let references = qualifier_refs(staged, mode);
    let range = checked_range(offset, count, references.len()).expect("validated qualifier range");
    for reference in &references[range] {
        let qualifier = qualifiers[*reference as usize];
        for (feature, value) in sum.iter_mut().enumerate() {
            *value += qualifier_product(
                mode,
                weights.node_embeddings[qualifier.object() as usize * HIDDEN + feature],
                weights.relation_embeddings[qualifier.predicate() as usize * HIDDEN + feature],
            );
        }
    }
    let mut projected = [0.0; HIDDEN];
    transform_add(&mut projected, &sum, &weights.qualifier_projection, 1.0);
    for feature in 0..HIDDEN {
        target[feature] += projected[feature];
    }
}

fn qualifier_product(mode: HyperEncoderMode, entity: f32, relation: f32) -> f32 {
    match mode {
        HyperEncoderMode::RoleOnly => relation,
        HyperEncoderMode::ValueOnly => entity,
        _ => entity * relation,
    }
}

fn qualifier_refs(staged: &HyperEncoderStagedInput, mode: HyperEncoderMode) -> &[u32] {
    if mode.uses_shuffled_qualifiers() {
        &staged.shuffled_qualifier_refs
    } else {
        &staged.canonical_qualifier_refs
    }
}

fn shuffled_qualifier_refs(facts: &[crate::ExternalFactRecord], canonical: &[u32]) -> Vec<u32> {
    let mut pools = HashMap::<(u8, u32), Vec<u32>>::new();
    for fact in facts.iter().copied().filter(|fact| {
        matches!(
            fact.split(),
            value if value == ExternalFactSplit::Train as u8
                || value == ExternalFactSplit::Validation as u8
        )
    }) {
        let start = fact.qualifier_offset() as usize;
        let end = start + fact.qualifier_count() as usize;
        pools
            .entry((fact.split(), fact.predicate()))
            .or_default()
            .extend_from_slice(&canonical[start..end]);
    }
    for pool in pools.values_mut() {
        if pool.len() > 1 {
            pool.rotate_left(1);
        }
    }
    let mut cursors = HashMap::<(u8, u32), usize>::new();
    let mut shuffled = canonical.to_vec();
    for fact in facts.iter().copied().filter(|fact| {
        fact.split() == ExternalFactSplit::Train as u8
            || fact.split() == ExternalFactSplit::Validation as u8
    }) {
        let key = (fact.split(), fact.predicate());
        let cursor = cursors.entry(key).or_default();
        let count = fact.qualifier_count() as usize;
        let start = fact.qualifier_offset() as usize;
        shuffled[start..start + count].copy_from_slice(&pools[&key][*cursor..*cursor + count]);
        *cursor += count;
    }
    shuffled
}

fn canonicalize_range(
    refs: &mut [u32],
    qualifiers: &[ExternalQualifierRecord],
    offset: u32,
    count: u32,
) -> Result<(), HyperEncoderError> {
    let range = checked_range(offset, count, refs.len())
        .ok_or(HyperEncoderError::InvalidContract("qualifier range"))?;
    refs[range].sort_unstable_by_key(|reference| {
        let q = qualifiers[*reference as usize];
        (q.predicate(), q.object(), *reference)
    });
    Ok(())
}

fn checked_range(offset: u32, count: u32, len: usize) -> Option<std::ops::Range<usize>> {
    let start = offset as usize;
    let end = start.checked_add(count as usize)?;
    (end <= len).then_some(start..end)
}
fn validate_fact(
    subject: u32,
    relation: u32,
    object: u32,
    nodes: u32,
    relations: u32,
) -> Result<(), HyperEncoderError> {
    if subject >= nodes || object >= nodes || relation >= relations {
        Err(HyperEncoderError::InvalidContract("fact bounds"))
    } else {
        Ok(())
    }
}
fn empty_batch(capacity: usize) -> HyperRelationBatch {
    HyperRelationBatch {
        sources: Vec::with_capacity(capacity),
        targets: Vec::with_capacity(capacity),
        qualifier_offsets: Vec::with_capacity(capacity),
        qualifier_counts: Vec::with_capacity(capacity),
        normalizers: Vec::with_capacity(capacity),
    }
}
fn push_message(
    batch: &mut HyperRelationBatch,
    source: u32,
    target: u32,
    fact: crate::external_dataset_artifact::ExternalFactRecord,
    degree: u32,
) {
    batch.sources.push(source);
    batch.targets.push(target);
    batch.qualifier_offsets.push(fact.qualifier_offset());
    batch.qualifier_counts.push(fact.qualifier_count());
    batch.normalizers.push((degree as f32).recip());
}
fn batch_bytes(batch: &HyperRelationBatch) -> usize {
    batch.sources.capacity() * size_of::<u32>() * 4
        + batch.normalizers.capacity() * size_of::<f32>()
}
fn row(values: &[f32], index: usize) -> &[f32] {
    &values[index * HIDDEN..(index + 1) * HIDDEN]
}
fn copy_row(values: &[f32], index: usize) -> [f32; HIDDEN] {
    row(values, index).try_into().expect("validated row")
}
fn matrix(values: &[f32], index: usize) -> &[f32] {
    &values[index * MATRIX..(index + 1) * MATRIX]
}
fn multiply(output: &mut [f32; HIDDEN], left: &[f32], right: &[f32]) {
    for feature in 0..HIDDEN {
        output[feature] = left[feature] * right[feature];
    }
}
fn transform_add(output: &mut [f32; HIDDEN], input: &[f32], weights: &[f32], scale: f32) {
    for target in 0..HIDDEN {
        let mut sum = 0.0;
        for source in 0..HIDDEN {
            sum += input[source] * weights[target * HIDDEN + source];
        }
        output[target] += sum * scale;
    }
}
fn transpose_candidates(rows: &[[f32; HIDDEN]]) -> (Vec<f32>, usize) {
    let stride = rows.len().div_ceil(LANES) * LANES;
    let mut planes = vec![0.0; stride * HIDDEN];
    for feature in 0..HIDDEN {
        for (candidate, row) in rows.iter().enumerate() {
            planes[feature * stride + candidate] = row[feature];
        }
    }
    (planes, stride)
}
fn validate_weights(
    staged: &HyperEncoderStagedInput,
    weights: &HyperEncoderWeights,
) -> Result<(), HyperEncoderError> {
    let nodes = staged.candidate_universe as usize;
    let relations = staged.relation_batches.len();
    if weights.node_embeddings.len() != nodes * HIDDEN
        || weights.direction_weights.len() != HYPER_ENCODER_DIRECTIONS * MATRIX
        || weights.relation_embeddings.len() != (relations + 1) * HIDDEN
        || weights.relation_projection.len() != MATRIX
        || weights.qualifier_projection.len() != MATRIX
        || weights.decoder_bias.len() != relations
    {
        Err(HyperEncoderError::InvalidContract("weight shape"))
    } else {
        Ok(())
    }
}

struct SplitMix64(u64);
impl SplitMix64 {
    fn values(&mut self, len: usize, scale: f32) -> Vec<f32> {
        (0..len).map(|_| self.signed() * scale).collect()
    }
    fn signed(&mut self) -> f32 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        z ^= z >> 31;
        (((z >> 40) as u32) as f32 / (1_u32 << 24) as f32) * 2.0 - 1.0
    }
}
