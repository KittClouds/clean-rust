use crate::temporal_rgcn_artifact::TemporalLeF32;
use crate::temporal_rgcn_candidate_simd::{CandidateFeaturePlanes, CANDIDATE_SIMD_LANES};
use crate::{
    CanonicalScoreMatrixMut, ExternalDatasetKind, ExternalDatasetMapped, ExternalFactSplit,
    LinkPredictionQueryView, LinkPredictionScoreCertificate, LinkPredictionTaskMapped,
    RgcnGraphBatch, RgcnQueryBatch, RgcnRelationBatch, TemporalRgcnConfig, TemporalRgcnError,
    TemporalRgcnMapped, TemporalRgcnStagingProfile, TemporalRgcnWeights,
    DEFAULT_LINK_PREDICTION_QUERY_BATCH, TEMPORAL_RGCN_HIDDEN,
};
use compact_str::CompactString;
use hashbrown::{HashMap, HashSet};
use rayon::prelude::*;
use std::marker::PhantomData;
use std::time::Instant;
use wide::f32x8;

pub const TEMPORAL_RGCN_QUERY_TILE: usize = 4;
pub const TEMPORAL_RGCN_CANDIDATE_TILE: usize = 4_096;

pub struct TemporalRgcnStagedInput {
    pub graph: RgcnGraphBatch,
    pub train: RgcnQueryBatch,
    pub profile: TemporalRgcnStagingProfile,
    pub source_dataset_id: CompactString,
    pub source_binary_blake3: CompactString,
    pub task_id: CompactString,
    pub task_binary_blake3: CompactString,
    pub base_relation_count: u32,
    pub config: TemporalRgcnConfig,
}

pub struct TemporalRgcnEncoded {
    pub model_id: CompactString,
    pub task_id: CompactString,
    nodes: Vec<[f32; TEMPORAL_RGCN_HIDDEN]>,
    candidate_planes: CandidateFeaturePlanes,
    candidate_plane_build_micros: u64,
    decoder: Vec<[f32; TEMPORAL_RGCN_HIDDEN]>,
    bias: Vec<f32>,
    residual_scale: f32,
    frequencies: Vec<Vec<(u32, u32)>>,
}

pub fn stage_temporal_rgcn(
    source: &ExternalDatasetMapped,
    task: &LinkPredictionTaskMapped,
    config: TemporalRgcnConfig,
) -> Result<TemporalRgcnStagedInput, TemporalRgcnError> {
    let started = Instant::now();
    config.validate()?;
    let source_manifest = source.manifest();
    let task_manifest = task.manifest();
    if source_manifest.kind != ExternalDatasetKind::TemporalKnowledgeGraph
        || source_manifest.dataset_id != task_manifest.source_dataset_id
        || source_manifest.binary_blake3 != task_manifest.source_binary_blake3
        || task_manifest.candidate_universe == 0
        || task_manifest.derived_relation_count != task_manifest.base_relation_count * 2
    {
        return Err(TemporalRgcnError::InvalidContract("source authority"));
    }
    let facts = source.facts()?;
    let nodes = task_manifest.candidate_universe;
    let base_relations = task_manifest.base_relation_count;
    let directed_relations = task_manifest.derived_relation_count;
    let mut counts = vec![0_usize; directed_relations as usize];
    let mut degrees = HashMap::<(u32, u32), u32>::with_capacity(
        usize::try_from(source_manifest.temporal_facts).unwrap_or_default(),
    );
    let mut positives = HashSet::with_capacity(
        usize::try_from(source_manifest.temporal_facts)
            .unwrap_or_default()
            .saturating_mul(2),
    );
    let mut train_facts = 0_u64;
    let mut topology = blake3::Hasher::new();
    for fact in facts.iter().copied() {
        if fact.is_static() {
            continue;
        }
        let split = fact.split();
        let time = fact
            .observed_at()
            .ok_or(TemporalRgcnError::InvalidContract("temporal fact"))?;
        if !(ExternalFactSplit::Train as u8..=ExternalFactSplit::Test as u8).contains(&split)
            || fact.subject() >= nodes
            || fact.object() >= nodes
            || fact.predicate() >= base_relations
        {
            return Err(TemporalRgcnError::InvalidContract("temporal bounds"));
        }
        if split != ExternalFactSplit::Train as u8 {
            continue;
        }
        let inverse = fact.predicate() + base_relations;
        counts[fact.predicate() as usize] += 1;
        counts[inverse as usize] += 1;
        *degrees
            .entry((fact.predicate(), fact.object()))
            .or_default() += 1;
        *degrees.entry((inverse, fact.subject())).or_default() += 1;
        positives.insert((fact.subject(), fact.predicate(), fact.object()));
        positives.insert((fact.object(), inverse, fact.subject()));
        topology.update(&time.to_le_bytes());
        topology.update(&fact.subject().to_le_bytes());
        topology.update(&fact.predicate().to_le_bytes());
        topology.update(&fact.object().to_le_bytes());
        train_facts += 1;
    }
    if train_facts == 0 {
        return Err(TemporalRgcnError::InvalidContract("empty train split"));
    }
    let mut batches = counts
        .into_iter()
        .map(|count| RgcnRelationBatch {
            sources: Vec::with_capacity(count),
            targets: Vec::with_capacity(count),
            normalizers: Vec::with_capacity(count),
        })
        .collect::<Vec<_>>();
    let examples_per_fact = 2_usize * (1 + usize::from(config.negatives_per_positive));
    let capacity = usize::try_from(train_facts)
        .ok()
        .and_then(|count| count.checked_mul(examples_per_fact))
        .ok_or(TemporalRgcnError::InvalidContract("training capacity"))?;
    let mut train = RgcnQueryBatch {
        sources: Vec::with_capacity(capacity),
        targets: Vec::with_capacity(capacity),
        relations: Vec::with_capacity(capacity),
        labels: Vec::with_capacity(capacity),
    };
    let mut random = SplitMix64::new(config.seed);
    for fact in facts
        .iter()
        .copied()
        .filter(|fact| !fact.is_static() && fact.split() == ExternalFactSplit::Train as u8)
    {
        let inverse = fact.predicate() + base_relations;
        push_message(
            &mut batches[fact.predicate() as usize],
            fact.subject(),
            fact.object(),
            degrees[&(fact.predicate(), fact.object())],
        );
        push_message(
            &mut batches[inverse as usize],
            fact.object(),
            fact.subject(),
            degrees[&(inverse, fact.subject())],
        );
        push_training_direction(
            &mut train,
            &positives,
            &mut random,
            nodes,
            fact.subject(),
            fact.predicate(),
            fact.object(),
            config.negatives_per_positive,
        )?;
        push_training_direction(
            &mut train,
            &positives,
            &mut random,
            nodes,
            fact.object(),
            inverse,
            fact.subject(),
            config.negatives_per_positive,
        )?;
    }
    let node_types = (0..nodes).collect::<Vec<_>>();
    let staged_bytes = node_types.capacity() * size_of::<u32>()
        + batches.iter().fold(0_usize, |total, batch| {
            total
                + batch.sources.capacity() * size_of::<u32>()
                + batch.targets.capacity() * size_of::<u32>()
                + batch.normalizers.capacity() * size_of::<f32>()
        })
        + train.sources.capacity() * size_of::<u32>() * 3
        + train.labels.capacity() * size_of::<bool>();
    Ok(TemporalRgcnStagedInput {
        graph: RgcnGraphBatch {
            node_types,
            relation_batches: batches,
            relation_count: directed_relations,
        },
        train,
        profile: TemporalRgcnStagingProfile {
            source_facts: source_manifest.facts,
            train_facts,
            directed_messages: train_facts * 2,
            training_examples: capacity as u64,
            staged_bytes: staged_bytes as u64,
            staging_micros: started.elapsed().as_micros().try_into().unwrap_or(u64::MAX),
            train_topology_blake3: format!("b3-{}", topology.finalize().to_hex()).into(),
            train_only: true,
        },
        source_dataset_id: source_manifest.dataset_id.clone(),
        source_binary_blake3: source_manifest.binary_blake3.clone(),
        task_id: task_manifest.task_id.clone(),
        task_binary_blake3: task_manifest.binary_blake3.clone(),
        base_relation_count: base_relations,
        config,
    })
}

pub fn encode_temporal_rgcn(
    model: &TemporalRgcnMapped,
    staged: &TemporalRgcnStagedInput,
) -> Result<TemporalRgcnEncoded, TemporalRgcnError> {
    let manifest = model.manifest();
    if manifest.source_dataset_id != staged.source_dataset_id
        || manifest.source_binary_blake3 != staged.source_binary_blake3
        || manifest.task_id != staged.task_id
        || manifest.task_binary_blake3 != staged.task_binary_blake3
        || manifest.candidate_universe as usize != staged.graph.node_types.len()
        || manifest.directed_relation_count as usize != staged.graph.relation_batches.len()
        || manifest.training.train_topology_blake3 != staged.profile.train_topology_blake3
        || manifest.config != staged.config
    {
        return Err(TemporalRgcnError::InvalidContract("model source"));
    }
    let weights = TemporalRgcnWeights {
        node_embeddings: values(&model.node_embeddings()?),
        self_weight: values(&model.self_weight()?),
        relation_weights: values(&model.relation_weights()?),
        decoder_relations: values(&model.decoder_relations()?),
        decoder_bias: values(&model.decoder_bias()?),
    };
    encode_values(
        manifest.model_id.clone(),
        manifest.task_id.clone(),
        &weights,
        staged,
    )
}

pub fn encode_temporal_rgcn_weights(
    model_id: CompactString,
    task_id: CompactString,
    weights: &TemporalRgcnWeights,
    staged: &TemporalRgcnStagedInput,
) -> Result<TemporalRgcnEncoded, TemporalRgcnError> {
    if task_id != staged.task_id {
        return Err(TemporalRgcnError::InvalidContract("weight task"));
    }
    encode_values(model_id, task_id, weights, staged)
}

fn encode_values(
    model_id: CompactString,
    task_id: CompactString,
    weights: &TemporalRgcnWeights,
    staged: &TemporalRgcnStagedInput,
) -> Result<TemporalRgcnEncoded, TemporalRgcnError> {
    let nodes_len = staged.graph.node_types.len() * TEMPORAL_RGCN_HIDDEN;
    let relations = staged.graph.relation_batches.len();
    if weights.node_embeddings.len() != nodes_len
        || weights.self_weight.len() != TEMPORAL_RGCN_HIDDEN.pow(2)
        || weights.relation_weights.len() != relations * TEMPORAL_RGCN_HIDDEN.pow(2)
        || weights.decoder_relations.len() != relations * TEMPORAL_RGCN_HIDDEN
        || weights.decoder_bias.len() != relations
    {
        return Err(TemporalRgcnError::InvalidContract("weight shape"));
    }
    let nodes = &weights.node_embeddings;
    let self_weight = &weights.self_weight;
    let relation_weights = &weights.relation_weights;
    let decoder_values = &weights.decoder_relations;
    let bias = weights.decoder_bias.clone();
    let frequencies = frequency_rows(&staged.graph);
    let mut encoded = vec![[0.0_f32; TEMPORAL_RGCN_HIDDEN]; staged.graph.node_types.len()];
    for node in 0..encoded.len() {
        let source: &[f32; TEMPORAL_RGCN_HIDDEN] = nodes
            [node * TEMPORAL_RGCN_HIDDEN..(node + 1) * TEMPORAL_RGCN_HIDDEN]
            .try_into()
            .map_err(|_| TemporalRgcnError::CorruptArtifact("node embedding"))?;
        transform_add(&mut encoded[node], source, self_weight, 1.0)?;
    }
    for (relation, batch) in staged.graph.relation_batches.iter().enumerate() {
        let start = relation * TEMPORAL_RGCN_HIDDEN.pow(2);
        let matrix = &relation_weights[start..start + TEMPORAL_RGCN_HIDDEN.pow(2)];
        for edge in 0..batch.sources.len() {
            let source_index = batch.sources[edge] as usize;
            let source: &[f32; TEMPORAL_RGCN_HIDDEN] = nodes
                [source_index * TEMPORAL_RGCN_HIDDEN..(source_index + 1) * TEMPORAL_RGCN_HIDDEN]
                .try_into()
                .map_err(|_| TemporalRgcnError::CorruptArtifact("node embedding"))?;
            let target = batch.targets[edge] as usize;
            transform_add(
                &mut encoded[target],
                source,
                matrix,
                batch.normalizers[edge],
            )?;
        }
    }
    encoded.iter_mut().for_each(|row| {
        row.iter_mut().for_each(|value| *value = value.max(0.0));
    });
    let decoder = decoder_values
        .chunks_exact(TEMPORAL_RGCN_HIDDEN)
        .map(|row| <[f32; TEMPORAL_RGCN_HIDDEN]>::try_from(row).expect("exact decoder row"))
        .collect();
    finish_temporal_encoding(
        model_id,
        task_id,
        encoded,
        decoder,
        bias,
        staged.config.residual_scale,
        frequencies,
    )
}

pub(crate) fn finish_temporal_encoding(
    model_id: CompactString,
    task_id: CompactString,
    nodes: Vec<[f32; TEMPORAL_RGCN_HIDDEN]>,
    decoder: Vec<[f32; TEMPORAL_RGCN_HIDDEN]>,
    bias: Vec<f32>,
    residual_scale: f32,
    frequencies: Vec<Vec<(u32, u32)>>,
) -> Result<TemporalRgcnEncoded, TemporalRgcnError> {
    if nodes.is_empty()
        || decoder.is_empty()
        || bias.len() != decoder.len()
        || frequencies.len() != decoder.len()
        || !residual_scale.is_finite()
        || residual_scale <= 0.0
    {
        return Err(TemporalRgcnError::InvalidContract("encoded shape"));
    }
    let plane_started = Instant::now();
    let candidate_planes = CandidateFeaturePlanes::from_rows(&nodes);
    let candidate_plane_build_micros = plane_started
        .elapsed()
        .as_micros()
        .try_into()
        .unwrap_or(u64::MAX);
    Ok(TemporalRgcnEncoded {
        model_id,
        task_id,
        nodes,
        candidate_planes,
        candidate_plane_build_micros,
        decoder,
        bias,
        residual_scale,
        frequencies,
    })
}

impl TemporalRgcnEncoded {
    pub fn candidate_plane_bytes(&self) -> u64 {
        self.candidate_planes.bytes().try_into().unwrap_or(u64::MAX)
    }

    pub fn candidate_plane_build_micros(&self) -> u64 {
        self.candidate_plane_build_micros
    }

    pub fn score_candidates(
        &self,
        query: LinkPredictionQueryView,
        candidates: &[u32],
        scores: &mut [f32],
    ) -> Result<(), String> {
        if query.source as usize >= self.nodes.len()
            || query.relation as usize >= self.decoder.len()
            || candidates.len() != scores.len()
            || !canonical_candidates(candidates, self.nodes.len())
        {
            return Err("temporal R-GCN query bounds".to_owned());
        }
        self.score_canonical(query, scores)
    }

    pub fn score_candidate_batch(
        &self,
        queries: &[LinkPredictionQueryView],
        candidates: &[u32],
        scores: &mut [f32],
    ) -> Result<(), String> {
        self.score_candidate_batch_layout(queries, candidates, scores, self.nodes.len(), 0)
    }

    pub fn score_candidate_batch_canonical(
        &self,
        queries: &[LinkPredictionQueryView],
        candidates: &[u32],
        matrix: CanonicalScoreMatrixMut<'_>,
    ) -> Result<(), String> {
        if matrix.rows() != queries.len() || matrix.candidates() != self.nodes.len() {
            return Err("temporal R-GCN canonical batch shape".to_owned());
        }
        let (scores, row_stride, score_offset) = matrix.into_layout();
        self.score_candidate_batch_layout(queries, candidates, scores, row_stride, score_offset)
    }

    fn score_candidate_batch_layout(
        &self,
        queries: &[LinkPredictionQueryView],
        candidates: &[u32],
        scores: &mut [f32],
        row_stride: usize,
        score_offset: usize,
    ) -> Result<(), String> {
        let candidate_count = self.nodes.len();
        let score_count = queries
            .len()
            .checked_mul(row_stride)
            .ok_or_else(|| "temporal R-GCN batch shape".to_owned())?;
        if queries.is_empty()
            || !canonical_candidates(candidates, candidate_count)
            || scores.len() != score_count
            || row_stride < score_offset.saturating_add(candidate_count)
            || queries.iter().any(|query| {
                query.source as usize >= self.nodes.len()
                    || query.relation as usize >= self.decoder.len()
            })
        {
            return Err("temporal R-GCN batch shape".to_owned());
        }
        let query_tiles = queries.len().div_ceil(TEMPORAL_RGCN_QUERY_TILE);
        let candidate_tiles = candidate_count.div_ceil(TEMPORAL_RGCN_CANDIDATE_TILE);
        let tile_count = query_tiles
            .checked_mul(candidate_tiles)
            .ok_or_else(|| "temporal R-GCN batch shape".to_owned())?;
        {
            let output = DisjointScoreMatrix::new(
                scores,
                queries.len(),
                candidate_count,
                row_stride,
                score_offset,
            );
            (0..tile_count).into_par_iter().for_each(|tile| {
                let query_tile = tile / candidate_tiles;
                let candidate_tile = tile % candidate_tiles;
                let query_start = query_tile * TEMPORAL_RGCN_QUERY_TILE;
                let query_end = (query_start + TEMPORAL_RGCN_QUERY_TILE).min(queries.len());
                let candidate_start = candidate_tile * TEMPORAL_RGCN_CANDIDATE_TILE;
                let candidate_end =
                    (candidate_start + TEMPORAL_RGCN_CANDIDATE_TILE).min(candidate_count);
                self.score_rectangle(
                    &queries[query_start..query_end],
                    query_start,
                    candidate_start,
                    candidate_end,
                    &output,
                );
            });
        }
        queries
            .par_iter()
            .zip(scores.par_chunks_mut(row_stride))
            .for_each(|(query, row)| {
                let row = &mut row[score_offset..score_offset + candidate_count];
                for (candidate, frequency) in &self.frequencies[query.relation as usize] {
                    row[*candidate as usize] += *frequency as f32;
                }
            });
        Ok(())
    }

    fn score_canonical(
        &self,
        query: LinkPredictionQueryView,
        scores: &mut [f32],
    ) -> Result<(), String> {
        if query.source as usize >= self.nodes.len()
            || query.relation as usize >= self.decoder.len()
            || scores.len() != self.nodes.len()
        {
            return Err("temporal R-GCN query bounds".to_owned());
        }
        let prepared = self.prepare_query(query)?;
        let features = [prepared.features];
        let biases = [prepared.bias];
        for candidate_start in (0..self.nodes.len()).step_by(CANDIDATE_SIMD_LANES) {
            let block = self.candidate_planes.score_block(
                &features,
                &biases,
                self.residual_scale,
                candidate_start,
            )[0];
            let candidate_end = (candidate_start + CANDIDATE_SIMD_LANES).min(self.nodes.len());
            scores[candidate_start..candidate_end]
                .copy_from_slice(&block[..candidate_end - candidate_start]);
        }
        for (candidate, frequency) in &self.frequencies[prepared.relation] {
            scores[*candidate as usize] += *frequency as f32;
        }
        Ok(())
    }

    // Fixed indices keep the four-query hot path unrolled and its writes branch-free.
    #[allow(clippy::needless_range_loop)]
    fn score_rectangle(
        &self,
        queries: &[LinkPredictionQueryView],
        query_start: usize,
        candidate_start: usize,
        candidate_end: usize,
        output: &DisjointScoreMatrix<'_>,
    ) {
        let first = self.prepare_query(queries[0]).expect("validated query");
        let mut prepared = [first; TEMPORAL_RGCN_QUERY_TILE];
        for (slot, query) in prepared.iter_mut().zip(queries.iter().copied()) {
            *slot = self.prepare_query(query).expect("validated query");
        }
        let prepared = &prepared[..queries.len()];
        let mut row_starts = [0_usize; TEMPORAL_RGCN_QUERY_TILE];
        for (row, start) in row_starts[..queries.len()].iter_mut().enumerate() {
            *start = output.row_start(query_start + row, candidate_start);
        }
        let features: [[f32; TEMPORAL_RGCN_HIDDEN]; TEMPORAL_RGCN_QUERY_TILE] =
            std::array::from_fn(|query| prepared.get(query).unwrap_or(&prepared[0]).features);
        let biases: [f32; TEMPORAL_RGCN_QUERY_TILE] =
            std::array::from_fn(|query| prepared.get(query).unwrap_or(&prepared[0]).bias);
        for block_start in (candidate_start..candidate_end).step_by(CANDIDATE_SIMD_LANES) {
            let block = self.candidate_planes.score_block(
                &features,
                &biases,
                self.residual_scale,
                block_start,
            );
            let valid = (candidate_end - block_start).min(CANDIDATE_SIMD_LANES);
            let offset = block_start - candidate_start;
            if prepared.len() == TEMPORAL_RGCN_QUERY_TILE {
                for lane in 0..valid {
                    output.write_index(row_starts[0] + offset + lane, block[0][lane]);
                    output.write_index(row_starts[1] + offset + lane, block[1][lane]);
                    output.write_index(row_starts[2] + offset + lane, block[2][lane]);
                    output.write_index(row_starts[3] + offset + lane, block[3][lane]);
                }
            } else {
                for row in 0..prepared.len() {
                    for lane in 0..valid {
                        output.write_index(row_starts[row] + offset + lane, block[row][lane]);
                    }
                }
            }
        }
    }

    fn prepare_query(&self, query: LinkPredictionQueryView) -> Result<PreparedQuery, String> {
        let source = self
            .nodes
            .get(query.source as usize)
            .ok_or_else(|| "temporal R-GCN query bounds".to_owned())?;
        let relation = self
            .decoder
            .get(query.relation as usize)
            .ok_or_else(|| "temporal R-GCN query bounds".to_owned())?;
        Ok(PreparedQuery {
            features: std::array::from_fn(|index| source[index] * relation[index]),
            bias: self.bias[query.relation as usize],
            relation: query.relation as usize,
        })
    }
}

#[derive(Clone, Copy)]
struct PreparedQuery {
    features: [f32; TEMPORAL_RGCN_HIDDEN],
    bias: f32,
    relation: usize,
}

struct DisjointScoreMatrix<'a> {
    pointer: *mut f32,
    rows: usize,
    columns: usize,
    row_stride: usize,
    score_offset: usize,
    marker: PhantomData<&'a mut [f32]>,
}

// Each parallel rectangle owns a unique Cartesian product of query rows and candidate columns.
// The matrix is not exposed outside the scoring join, and frequency writes begin only after every
// rectangle completes.
unsafe impl Sync for DisjointScoreMatrix<'_> {}

impl<'a> DisjointScoreMatrix<'a> {
    fn new(
        scores: &'a mut [f32],
        rows: usize,
        columns: usize,
        row_stride: usize,
        score_offset: usize,
    ) -> Self {
        debug_assert_eq!(scores.len(), rows * row_stride);
        debug_assert!(row_stride >= score_offset + columns);
        Self {
            pointer: scores.as_mut_ptr(),
            rows,
            columns,
            row_stride,
            score_offset,
            marker: PhantomData,
        }
    }

    fn row_start(&self, row: usize, column: usize) -> usize {
        debug_assert!(row < self.rows && column < self.columns);
        row * self.row_stride + self.score_offset + column
    }

    #[inline(always)]
    fn write_index(&self, index: usize, value: f32) {
        debug_assert!(index < self.rows * self.row_stride);
        // SAFETY: score_candidate_batch assigns each (row, column) to exactly one rectangle.
        // The backing slice remains exclusively borrowed by this matrix until the join completes.
        unsafe {
            self.pointer.add(index).write(value);
        }
    }
}

pub fn evaluate_temporal_frequency_baseline(
    task: &LinkPredictionTaskMapped,
    staged: &TemporalRgcnStagedInput,
) -> Result<LinkPredictionScoreCertificate, TemporalRgcnError> {
    let rows = frequency_rows(&staged.graph);
    let model_id = format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            "train-relation-destination-frequency/v1",
            staged.source_dataset_id.as_str(),
            staged.task_id.as_str(),
            staged.profile.train_topology_blake3.as_str(),
        ))?)
        .to_hex()
    );
    let candidate_count = staged.graph.node_types.len();
    crate::evaluate_link_prediction_validation_batched(
        task,
        &model_id,
        DEFAULT_LINK_PREDICTION_QUERY_BATCH,
        |queries, candidates, scores| {
            if !canonical_candidates(candidates, candidate_count)
                || scores.len() != queries.len().saturating_mul(candidate_count)
            {
                return Err("frequency baseline candidate universe".to_owned());
            }
            queries
                .par_iter()
                .zip(scores.par_chunks_mut(candidate_count))
                .try_for_each(|(query, row)| {
                    let frequencies = rows
                        .get(query.relation as usize)
                        .ok_or_else(|| "frequency baseline relation".to_owned())?;
                    row.fill(0.0);
                    for (candidate, count) in frequencies {
                        row[*candidate as usize] = *count as f32;
                    }
                    Ok(())
                })
        },
    )
    .map_err(TemporalRgcnError::Task)
}

fn canonical_candidates(candidates: &[u32], expected: usize) -> bool {
    candidates.len() == expected
        && candidates
            .iter()
            .copied()
            .enumerate()
            .all(|(index, candidate)| candidate as usize == index)
}

pub(crate) fn frequency_rows(graph: &RgcnGraphBatch) -> Vec<Vec<(u32, u32)>> {
    graph
        .relation_batches
        .iter()
        .map(|batch| {
            let mut counts = HashMap::<u32, u32>::with_capacity(batch.targets.len());
            for target in &batch.targets {
                *counts.entry(*target).or_default() += 1;
            }
            let mut row = counts.into_iter().collect::<Vec<_>>();
            row.sort_unstable_by_key(|(target, _)| *target);
            row
        })
        .collect()
}

fn push_message(batch: &mut RgcnRelationBatch, source: u32, target: u32, degree: u32) {
    batch.sources.push(source);
    batch.targets.push(target);
    batch.normalizers.push(1.0 / degree as f32);
}

#[allow(clippy::too_many_arguments)]
fn push_training_direction(
    train: &mut RgcnQueryBatch,
    positives: &HashSet<(u32, u32, u32)>,
    random: &mut SplitMix64,
    nodes: u32,
    source: u32,
    relation: u32,
    positive: u32,
    negatives: u16,
) -> Result<(), TemporalRgcnError> {
    train.sources.push(source);
    train.targets.push(positive);
    train.relations.push(relation);
    train.labels.push(true);
    for _ in 0..negatives {
        let mut candidate = random.next_u64() as u32 % nodes;
        let start = candidate;
        while positives.contains(&(source, relation, candidate)) {
            candidate = (candidate + 1) % nodes;
            if candidate == start {
                return Err(TemporalRgcnError::InvalidContract("dense train query"));
            }
        }
        train.sources.push(source);
        train.targets.push(candidate);
        train.relations.push(relation);
        train.labels.push(false);
    }
    Ok(())
}

fn values(values: &[TemporalLeF32]) -> Vec<f32> {
    values.iter().copied().map(|value| value.get()).collect()
}

fn transform_add(
    target: &mut [f32; TEMPORAL_RGCN_HIDDEN],
    source: &[f32; TEMPORAL_RGCN_HIDDEN],
    matrix: &[f32],
    scale: f32,
) -> Result<(), TemporalRgcnError> {
    for (row, output) in target.iter_mut().enumerate() {
        let weights: &[f32; TEMPORAL_RGCN_HIDDEN] = matrix
            [row * TEMPORAL_RGCN_HIDDEN..(row + 1) * TEMPORAL_RGCN_HIDDEN]
            .try_into()
            .map_err(|_| TemporalRgcnError::CorruptArtifact("message matrix"))?;
        let low: [f32; 8] = (f32x8::from(<[f32; 8]>::try_from(&weights[..8]).expect("low"))
            * f32x8::from(<[f32; 8]>::try_from(&source[..8]).expect("low")))
        .into();
        let high: [f32; 8] = (f32x8::from(<[f32; 8]>::try_from(&weights[8..]).expect("high"))
            * f32x8::from(<[f32; 8]>::try_from(&source[8..]).expect("high")))
        .into();
        *output += low.into_iter().chain(high).sum::<f32>() * scale;
    }
    Ok(())
}

struct SplitMix64(u64);

impl SplitMix64 {
    fn new(seed: u64) -> Self {
        Self(seed)
    }

    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }
}

use std::mem::size_of;
