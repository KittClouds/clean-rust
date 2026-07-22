use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::time::Instant;

use phoenix_revision_inference::{
    BundleBuildReceipt, GfmAssets, GfmEmbeddingBatchReceipt, build_gfm_bundle_with_encoder,
    embed_gfm_texts, project_gfm, run_gfm_complete,
};
use serde::Serialize;
use wide::f32x8;

use crate::corpus::{GoldTask, TASKS, TaskTarget, graph_with_first_dirty_suffix, node_rows};
use crate::metrics::{MetricsAccumulator, RetrievalMetrics};

const RESULT_LIMIT: usize = 12;
const SEED_LIMIT: usize = 4;
const RRF_K: f64 = 60.0;
type RankingObservation = (Vec<String>, Vec<String>);
type ArmRankingMap = BTreeMap<String, Vec<RankingObservation>>;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RetrievalArmReceipt {
    pub arm: String,
    pub metrics: RetrievalMetrics,
    pub total_micros: u64,
    pub p50_micros: u64,
    pub p95_micros: u64,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RetrievalCaseReceipt {
    pub task_id: String,
    pub family: String,
    pub gold_ids: Vec<String>,
    pub oracle_seed_ids: Vec<String>,
    pub resolved_seed_ids: Vec<String>,
    pub seed_hit: bool,
    pub rankings: BTreeMap<String, Vec<String>>,
    pub timings_micros: BTreeMap<String, u64>,
    pub graph_evidence_entities: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SeedResolutionReceipt {
    pub cases: usize,
    pub recall_at_1: f64,
    pub recall_at_3: f64,
    pub recall_at_4: f64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RetrievalDuelReceipt {
    pub schema: &'static str,
    pub asserted_truth_only: bool,
    pub candidate_edges_admitted: u64,
    pub oracle_start_nodes_used_only_by_ceiling_arm: bool,
    pub index_build: BundleBuildReceipt,
    pub corpus_embedding: EmbeddingReceipt,
    pub seed_resolution: SeedResolutionReceipt,
    pub arms: Vec<RetrievalArmReceipt>,
    pub selected_arm: String,
    pub promotion_eligible: bool,
    pub ranking_digest: String,
    pub cases: Vec<RetrievalCaseReceipt>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EmbeddingReceipt {
    pub encoder_resident_reused: bool,
    pub prepare_micros: u64,
    pub embedding_micros: u64,
    pub peak_resident_bytes: u64,
}

impl From<GfmEmbeddingBatchReceipt> for EmbeddingReceipt {
    fn from(receipt: GfmEmbeddingBatchReceipt) -> Self {
        Self {
            encoder_resident_reused: receipt.encoder_resident_reused,
            prepare_micros: receipt.prepare_micros,
            embedding_micros: receipt.embedding_micros,
            peak_resident_bytes: receipt.peak_resident_bytes,
        }
    }
}

pub fn execute_retrieval_duel(
    bundle_root: &std::path::Path,
    assets: &GfmAssets,
) -> Result<RetrievalDuelReceipt, Box<dyn std::error::Error>> {
    let graph = graph_with_first_dirty_suffix("", "");
    let index_build = build_gfm_bundle_with_encoder(bundle_root, 1, project_gfm(&graph)?, assets)?;
    let corpus_texts = node_rows().iter().map(|row| row.2).collect::<Vec<_>>();
    let embedded = embed_gfm_texts(assets, &corpus_texts)?;
    let corpus_embedding = embedded.receipt.into();
    let corpus = EmbeddedCorpus::new(embedded.rows)?;
    let tasks = TASKS
        .iter()
        .filter(|task| task.target == TaskTarget::Document)
        .collect::<Vec<_>>();
    let mut cases = Vec::with_capacity(tasks.len());
    let mut arm_rankings = ArmRankingMap::new();
    let mut arm_timings = BTreeMap::<String, Vec<u64>>::new();
    let mut seed_hits = [0_usize; SEED_LIMIT];

    for task in tasks {
        let query = embed_gfm_texts(assets, &[task.query])?;
        let query_micros = query.receipt.prepare_micros + query.receipt.embedding_micros;
        let query_row = query.rows.first().ok_or("query encoder returned no row")?;

        let started = Instant::now();
        let semantic = corpus.rank_documents(query_row, RESULT_LIMIT);
        let semantic_micros = query_micros + elapsed_micros(started);
        arm_timings
            .entry("semantic".into())
            .or_default()
            .push(semantic_micros);

        let started = Instant::now();
        let resolved_seeds = corpus.resolve_entity_seeds(task.query, query_row, SEED_LIMIT);
        let seed_micros = elapsed_micros(started);
        observe_seed_hits(&resolved_seeds, task, &mut seed_hits);
        let resolved_refs = resolved_seeds
            .iter()
            .map(String::as_str)
            .collect::<Vec<_>>();

        let started = Instant::now();
        let real = run_gfm_complete(
            bundle_root,
            assets,
            task.query,
            &resolved_refs,
            RESULT_LIMIT,
        )?;
        let real_inference_micros = elapsed_micros(started);
        let real_micros = query_micros + seed_micros + real_inference_micros;

        let started = Instant::now();
        let oracle = run_gfm_complete(
            bundle_root,
            assets,
            task.query,
            task.start_ids,
            RESULT_LIMIT,
        )?;
        let oracle_micros = elapsed_micros(started);
        let fusion_started = Instant::now();
        let fusion = reciprocal_rank_fusion(&semantic, &real.ordered_document_ids);
        let fusion_micros = elapsed_micros(fusion_started) + real_micros;

        let rankings = BTreeMap::from([
            ("semantic".into(), semantic.clone()),
            ("gfm_real_seed".into(), real.ordered_document_ids.clone()),
            (
                "gfm_oracle_ceiling".into(),
                oracle.ordered_document_ids.clone(),
            ),
            ("semantic_gfm_fusion".into(), fusion.clone()),
        ]);
        record_arm(&mut arm_rankings, "semantic", &semantic, task);
        record_arm(
            &mut arm_rankings,
            "gfm_real_seed",
            &real.ordered_document_ids,
            task,
        );
        record_arm(
            &mut arm_rankings,
            "gfm_oracle_ceiling",
            &oracle.ordered_document_ids,
            task,
        );
        record_arm(&mut arm_rankings, "semantic_gfm_fusion", &fusion, task);
        arm_timings
            .entry("gfm_real_seed".into())
            .or_default()
            .push(real_micros);
        arm_timings
            .entry("gfm_oracle_ceiling".into())
            .or_default()
            .push(oracle_micros);
        arm_timings
            .entry("semantic_gfm_fusion".into())
            .or_default()
            .push(fusion_micros);
        cases.push(RetrievalCaseReceipt {
            task_id: task.id.into(),
            family: task.family.into(),
            gold_ids: task.gold_ids.iter().map(|id| (*id).into()).collect(),
            oracle_seed_ids: task.start_ids.iter().map(|id| (*id).into()).collect(),
            seed_hit: resolved_seeds
                .iter()
                .any(|id| task.start_ids.contains(&id.as_str())),
            resolved_seed_ids: resolved_seeds,
            rankings,
            timings_micros: BTreeMap::from([
                ("seedResolution".into(), seed_micros),
                ("queryEmbedding".into(), query_micros),
                ("semantic".into(), semantic_micros),
                ("gfmInference".into(), real_inference_micros),
                ("gfmRealSeed".into(), real_micros),
                ("gfmOracleCeiling".into(), oracle_micros),
                ("semanticGfmFusion".into(), fusion_micros),
            ]),
            graph_evidence_entities: real.top_entity_ids,
        });
    }

    let arms = arm_rankings
        .into_iter()
        .map(|(arm, rankings)| {
            let timings = arm_timings.remove(&arm).unwrap_or_default();
            arm_receipt(arm, rankings, timings)
        })
        .collect::<Vec<_>>();
    let selected_arm = select_deployable_arm(&arms).to_string();
    let semantic = arm(&arms, "semantic")?;
    let selected = arm(&arms, &selected_arm)?;
    let seed_resolution = seed_receipt(seed_hits, cases.len());
    let promotion_eligible = selected_arm != "semantic"
        && selected.metrics.recall_at_3 >= semantic.metrics.recall_at_3
        && selected.metrics.mean_ndcg_at_5 >= semantic.metrics.mean_ndcg_at_5
        && seed_resolution.recall_at_3 >= 0.75;
    let ranking_digest = ranking_digest(&cases);
    Ok(RetrievalDuelReceipt {
        schema: "phoenix.retrieval-duel/v1",
        asserted_truth_only: true,
        candidate_edges_admitted: 0,
        oracle_start_nodes_used_only_by_ceiling_arm: true,
        index_build,
        corpus_embedding,
        seed_resolution,
        arms,
        selected_arm,
        promotion_eligible,
        ranking_digest,
        cases,
    })
}

struct EmbeddedCorpus {
    rows: Vec<Vec<f32>>,
    norms: Vec<f32>,
}

impl EmbeddedCorpus {
    fn new(rows: Vec<Vec<f32>>) -> Result<Self, Box<dyn std::error::Error>> {
        if rows.len() != node_rows().len() || rows.iter().any(|row| row.len() != 768) {
            return Err("corpus embedding shape mismatch".into());
        }
        let norms = rows.iter().map(|row| dot(row, row).sqrt()).collect();
        Ok(Self { rows, norms })
    }

    fn rank_documents(&self, query: &[f32], limit: usize) -> Vec<String> {
        self.rank_kind(query, "document", limit)
            .into_iter()
            .map(|(id, _)| id)
            .collect()
    }

    fn resolve_entity_seeds(&self, query: &str, embedding: &[f32], limit: usize) -> Vec<String> {
        let query_tokens = tokens(query);
        let mut ranked = self.rank_kind(embedding, "entity", node_rows().len());
        for (id, score) in &mut ranked {
            let text = node_rows()
                .iter()
                .find(|row| row.0 == id)
                .map_or("", |row| row.2);
            let entity_tokens = tokens(text);
            let hits = entity_tokens
                .iter()
                .filter(|token| query_tokens.contains(token))
                .count();
            let lexical = hits as f32 / entity_tokens.len().max(1) as f32;
            *score = *score * 0.78 + lexical * 0.22;
        }
        ranked.sort_by(score_order);
        ranked.into_iter().take(limit).map(|(id, _)| id).collect()
    }

    fn rank_kind(&self, query: &[f32], kind: &str, limit: usize) -> Vec<(String, f32)> {
        let query_norm = dot(query, query).sqrt();
        let mut ranked = node_rows()
            .iter()
            .enumerate()
            .filter(|(_, row)| row.1 == kind)
            .map(|(index, row)| {
                let denominator = (query_norm * self.norms[index]).max(f32::EPSILON);
                (
                    row.0.to_string(),
                    dot(query, &self.rows[index]) / denominator,
                )
            })
            .collect::<Vec<_>>();
        ranked.sort_by(score_order);
        ranked.truncate(limit);
        ranked
    }
}

fn dot(left: &[f32], right: &[f32]) -> f32 {
    let mut sum = f32x8::ZERO;
    let chunks = left.len().min(right.len()) / 8;
    for index in 0..chunks {
        let offset = index * 8;
        sum += load(left, offset) * load(right, offset);
    }
    let lanes: [f32; 8] = sum.into();
    let mut total = lanes.into_iter().sum::<f32>();
    for index in chunks * 8..left.len().min(right.len()) {
        total += left[index] * right[index];
    }
    total
}

fn load(values: &[f32], offset: usize) -> f32x8 {
    f32x8::from(<[f32; 8]>::try_from(&values[offset..offset + 8]).expect("SIMD row"))
}

fn tokens(text: &str) -> Vec<String> {
    text.to_lowercase()
        .split(|character: char| !character.is_alphanumeric())
        .filter(|token| token.len() > 2)
        .map(str::to_string)
        .collect()
}

fn reciprocal_rank_fusion(left: &[String], right: &[String]) -> Vec<String> {
    let mut scores = BTreeMap::<String, f64>::new();
    for ranking in [left, right] {
        for (index, id) in ranking.iter().enumerate() {
            *scores.entry(id.clone()).or_default() += 1.0 / (RRF_K + index as f64 + 1.0);
        }
    }
    let mut ranked = scores.into_iter().collect::<Vec<_>>();
    ranked.sort_by(|left, right| {
        right
            .1
            .total_cmp(&left.1)
            .then_with(|| left.0.cmp(&right.0))
    });
    ranked.into_iter().map(|(id, _)| id).collect()
}

fn arm_receipt(
    arm: String,
    rankings: Vec<(Vec<String>, Vec<String>)>,
    mut timings: Vec<u64>,
) -> RetrievalArmReceipt {
    let mut metrics = MetricsAccumulator::default();
    for (ranking, gold) in rankings {
        metrics.observe(&ranking, &gold);
    }
    timings.sort_unstable();
    RetrievalArmReceipt {
        arm,
        metrics: metrics.finish(),
        total_micros: timings.iter().sum(),
        p50_micros: percentile(&timings, 50),
        p95_micros: percentile(&timings, 95),
    }
}

fn record_arm(arms: &mut ArmRankingMap, arm: &str, ranking: &[String], task: &GoldTask) {
    arms.entry(arm.into()).or_default().push((
        ranking.to_vec(),
        task.gold_ids.iter().map(|id| (*id).into()).collect(),
    ));
}

fn observe_seed_hits(seeds: &[String], task: &GoldTask, hits: &mut [usize; SEED_LIMIT]) {
    for (index, hit) in hits.iter_mut().enumerate() {
        if seeds
            .iter()
            .take(index + 1)
            .any(|id| task.start_ids.contains(&id.as_str()))
        {
            *hit += 1;
        }
    }
}

fn ranking_digest(cases: &[RetrievalCaseReceipt]) -> String {
    let mut hasher = blake3::Hasher::new();
    for case in cases {
        hasher.update(case.task_id.as_bytes());
        for (arm, ranking) in &case.rankings {
            hasher.update(arm.as_bytes());
            for id in ranking {
                hasher.update(id.as_bytes());
                hasher.update(&[0]);
            }
        }
    }
    hasher.finalize().to_hex().to_string()
}

fn seed_receipt(hits: [usize; SEED_LIMIT], cases: usize) -> SeedResolutionReceipt {
    let denominator = cases.max(1) as f64;
    SeedResolutionReceipt {
        cases,
        recall_at_1: hits[0] as f64 / denominator,
        recall_at_3: hits[2] as f64 / denominator,
        recall_at_4: hits[3] as f64 / denominator,
    }
}

fn select_deployable_arm(arms: &[RetrievalArmReceipt]) -> &str {
    arms.iter()
        .filter(|arm| arm.arm != "gfm_oracle_ceiling")
        .max_by(|left, right| {
            left.metrics
                .recall_at_3
                .total_cmp(&right.metrics.recall_at_3)
                .then_with(|| {
                    left.metrics
                        .full_support_at_5
                        .total_cmp(&right.metrics.full_support_at_5)
                })
                .then_with(|| {
                    left.metrics
                        .mean_ndcg_at_5
                        .total_cmp(&right.metrics.mean_ndcg_at_5)
                })
                .then_with(|| right.p95_micros.cmp(&left.p95_micros))
        })
        .map_or("semantic", |arm| arm.arm.as_str())
}

fn arm<'a>(arms: &'a [RetrievalArmReceipt], id: &str) -> Result<&'a RetrievalArmReceipt, String> {
    arms.iter()
        .find(|arm| arm.arm == id)
        .ok_or_else(|| format!("missing retrieval arm {id}"))
}

fn score_order(left: &(String, f32), right: &(String, f32)) -> Ordering {
    right
        .1
        .total_cmp(&left.1)
        .then_with(|| left.0.cmp(&right.0))
}

fn percentile(sorted: &[u64], percentile: usize) -> u64 {
    if sorted.is_empty() {
        return 0;
    }
    let index = (sorted.len() - 1) * percentile / 100;
    sorted[index]
}

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fusion_is_deterministic_and_rewards_overlap() {
        let fused = reciprocal_rank_fusion(
            &["doc:a".into(), "doc:b".into()],
            &["doc:b".into(), "doc:c".into()],
        );
        assert_eq!(fused[0], "doc:b");
        assert_eq!(
            fused,
            reciprocal_rank_fusion(
                &["doc:a".into(), "doc:b".into()],
                &["doc:b".into(), "doc:c".into()]
            )
        );
    }

    #[test]
    fn simd_dot_matches_scalar_tail() {
        let left = (0..11).map(|value| value as f32).collect::<Vec<_>>();
        let right = (0..11).map(|value| (value * 2) as f32).collect::<Vec<_>>();
        let expected = left.iter().zip(&right).map(|(l, r)| l * r).sum::<f32>();
        assert_eq!(dot(&left, &right), expected);
    }
}
