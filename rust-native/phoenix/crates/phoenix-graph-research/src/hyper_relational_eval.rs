use crate::hyper_relational_binary::{HyperLeU32, HyperQueryRecord};
use crate::{
    HyperRelationalCandidatePolicy, HyperRelationalMetricSlice, HyperRelationalQueryView,
    HyperRelationalRankingMetrics, HyperRelationalScoreCertificate, HyperRelationalTaskError,
    HyperRelationalTaskMapped, HyperRelationalTestLock, HyperRelationalTestLockInput,
    HyperRelationalTestLockPaths, HyperRelationalTestResultPaths, LinkPredictionSplit,
    ENTITY_ROLE_OBJECT, ENTITY_ROLE_PRIMARY, ENTITY_ROLE_QUALIFIER, ENTITY_ROLE_SUBJECT,
    HYPER_RELATIONAL_SCORE_SCHEMA, HYPER_RELATIONAL_TEST_LOCK_SCHEMA,
};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};
use wide::{f32x8, CmpGe, CmpGt};
use zerocopy::AsBytes;

pub const DEFAULT_HYPER_RELATIONAL_QUERY_BATCH: usize = 64;

#[derive(Clone, Copy, Debug, Default)]
struct MetricAccumulator {
    reciprocal_rank: f64,
    hits: [u64; 4],
    queries: u64,
    candidates_scored: u64,
}

struct EvaluationAccumulators {
    overall: MetricAccumulator,
    presence: [MetricAccumulator; 2],
    qualifier_count: Vec<MetricAccumulator>,
    relation: Vec<MetricAccumulator>,
    provenance: [MetricAccumulator; 3],
}

impl MetricAccumulator {
    fn push(&mut self, rank: f64, candidates: u64) {
        self.reciprocal_rank += rank.recip();
        for (slot, threshold) in self.hits.iter_mut().zip([1.0, 3.0, 5.0, 10.0]) {
            *slot += u64::from(rank <= threshold);
        }
        self.queries += 1;
        self.candidates_scored += candidates;
    }

    fn finish(self) -> HyperRelationalRankingMetrics {
        let denominator = self.queries.max(1) as f64;
        HyperRelationalRankingMetrics {
            mean_reciprocal_rank: self.reciprocal_rank / denominator,
            hits_at_1: self.hits[0] as f64 / denominator,
            hits_at_3: self.hits[1] as f64 / denominator,
            hits_at_5: self.hits[2] as f64 / denominator,
            hits_at_10: self.hits[3] as f64 / denominator,
            queries: self.queries,
            candidates_scored: self.candidates_scored,
        }
    }
}

pub fn evaluate_hyper_relational_validation_batched<F>(
    task: &HyperRelationalTaskMapped,
    model_id: &str,
    candidate_policy: HyperRelationalCandidatePolicy,
    batch_size: usize,
    scorer: F,
) -> Result<HyperRelationalScoreCertificate, HyperRelationalTaskError>
where
    F: FnMut(&[HyperRelationalQueryView], &[u32], &mut [f32]) -> Result<(), String>,
{
    evaluate_split_batched(
        task,
        model_id,
        LinkPredictionSplit::Validation,
        candidate_policy,
        batch_size,
        scorer,
    )
}

pub fn create_hyper_relational_test_lock(
    task: &HyperRelationalTaskMapped,
    input: &HyperRelationalTestLockInput,
    root: impl AsRef<Path>,
) -> Result<HyperRelationalTestLockPaths, HyperRelationalTaskError> {
    if input.task_id != task.manifest().task_id
        || input.selection_ledger_id.is_empty()
        || input.selected_model_id.is_empty()
        || input.validation_certificate_id.is_empty()
    {
        return Err(HyperRelationalTaskError::InvalidInput("test lock input"));
    }
    let lock_id = lock_identity(input)?;
    let lock = HyperRelationalTestLock {
        schema_version: HYPER_RELATIONAL_TEST_LOCK_SCHEMA.into(),
        lock_id: lock_id.as_str().into(),
        task_id: input.task_id.clone(),
        selection_ledger_id: input.selection_ledger_id.clone(),
        selected_model_id: input.selected_model_id.clone(),
        validation_certificate_id: input.validation_certificate_id.clone(),
        candidate_policy: input.candidate_policy,
    };
    let root = root.as_ref();
    std::fs::create_dir_all(root)?;
    let receipt = root.join(format!("{lock_id}.test-lock.json"));
    write_new_durable(&receipt, &serde_json::to_vec_pretty(&lock)?)?;
    Ok(HyperRelationalTestLockPaths {
        receipt,
        lock_id: lock_id.into(),
    })
}

pub fn evaluate_locked_hyper_relational_test_batched<F>(
    task: &HyperRelationalTaskMapped,
    lock_receipt: impl AsRef<Path>,
    output_root: impl AsRef<Path>,
    batch_size: usize,
    scorer: F,
) -> Result<HyperRelationalTestResultPaths, HyperRelationalTaskError>
where
    F: FnMut(&[HyperRelationalQueryView], &[u32], &mut [f32]) -> Result<(), String>,
{
    let (lock, root, claim) = claim_locked_test(task, lock_receipt, output_root)?;
    let certificate = evaluate_split_batched(
        task,
        lock.selected_model_id.as_str(),
        LinkPredictionSplit::Test,
        lock.candidate_policy,
        batch_size,
        scorer,
    )?;
    let certificate_path = root.join(format!("{}.test-score.json", certificate.certificate_id));
    write_new_durable(&certificate_path, &serde_json::to_vec_pretty(&certificate)?)?;
    Ok(HyperRelationalTestResultPaths {
        claim,
        certificate: certificate_path,
    })
}

fn evaluate_split_batched<F>(
    task: &HyperRelationalTaskMapped,
    model_id: &str,
    split: LinkPredictionSplit,
    candidate_policy: HyperRelationalCandidatePolicy,
    batch_size: usize,
    mut scorer: F,
) -> Result<HyperRelationalScoreCertificate, HyperRelationalTaskError>
where
    F: FnMut(&[HyperRelationalQueryView], &[u32], &mut [f32]) -> Result<(), String>,
{
    if model_id.is_empty() || batch_size == 0 {
        return Err(HyperRelationalTaskError::InvalidInput("evaluation input"));
    }
    let candidate_count = task.manifest().candidate_universe as usize;
    let score_elements = candidate_count
        .checked_mul(batch_size)
        .ok_or(HyperRelationalTaskError::InvalidInput("score arena"))?;
    let candidates = (0..task.manifest().candidate_universe).collect::<Vec<_>>();
    let queries = task.queries(split)?;
    let groups = task.truth_groups()?;
    let targets = task.truth_targets()?;
    let entity_roles = task.entity_roles();
    let eligible_subject = entity_roles
        .iter()
        .filter(|role| **role & ENTITY_ROLE_SUBJECT != 0)
        .count() as u64;
    let eligible_object = entity_roles
        .iter()
        .filter(|role| **role & ENTITY_ROLE_OBJECT != 0)
        .count() as u64;
    let mut views = Vec::with_capacity(batch_size);
    let mut scores = vec![f32::NAN; score_elements];
    let mut score_hasher = blake3::Hasher::new();
    let mut overall = MetricAccumulator::default();
    let mut presence = [MetricAccumulator::default(); 2];
    let mut qualifier_count =
        vec![MetricAccumulator::default(); task.manifest().max_qualifiers as usize + 1];
    let mut relation =
        vec![MetricAccumulator::default(); task.manifest().base_relation_count as usize];
    let mut provenance = [MetricAccumulator::default(); 3];

    for records in queries.chunks(batch_size) {
        views.clear();
        views.extend(
            records
                .iter()
                .copied()
                .map(|record| query_view(record, split, task.manifest().base_relation_count)),
        );
        let active_len = records.len() * candidate_count;
        let active_scores = &mut scores[..active_len];
        active_scores.fill(f32::NAN);
        scorer(&views, &candidates, active_scores).map_err(HyperRelationalTaskError::Scorer)?;
        for (record, row) in records
            .iter()
            .copied()
            .zip(active_scores.chunks_exact(candidate_count))
        {
            if row.iter().any(|score| !score.is_finite()) {
                return Err(HyperRelationalTaskError::Scorer(
                    "scorer returned non-finite score".to_owned(),
                ));
            }
            hash_score_row(
                &mut score_hasher,
                record,
                split,
                task.manifest().base_relation_count,
                row,
            );
            let group = groups
                .get(record.truth_group() as usize)
                .copied()
                .ok_or(HyperRelationalTaskError::CorruptArtifact("truth group"))?;
            let start = group.target_offset() as usize;
            let end = start
                .checked_add(group.target_count() as usize)
                .ok_or(HyperRelationalTaskError::CorruptArtifact("truth range"))?;
            let filtered = targets
                .get(start..end)
                .ok_or(HyperRelationalTaskError::CorruptArtifact("truth range"))?;
            let target_role = target_role(record, task.manifest().base_relation_count);
            let rank = filtered_rank(
                row,
                filtered,
                record.target(),
                candidate_policy,
                target_role,
                entity_roles,
            )?;
            let eligible = match candidate_policy {
                HyperRelationalCandidatePolicy::FullEntity => candidate_count as u64,
                HyperRelationalCandidatePolicy::PrimaryRole
                    if target_role == ENTITY_ROLE_SUBJECT =>
                {
                    eligible_subject
                }
                HyperRelationalCandidatePolicy::PrimaryRole => eligible_object,
            };
            overall.push(rank, eligible);
            presence[usize::from(record.qualifier_count() != 0)].push(rank, eligible);
            qualifier_count[record.qualifier_count() as usize].push(rank, eligible);
            relation[(record.relation() % task.manifest().base_relation_count) as usize]
                .push(rank, eligible);
            let role = entity_roles[record.target() as usize];
            let provenance_index = if role & ENTITY_ROLE_PRIMARY == 0 {
                2
            } else if role & ENTITY_ROLE_QUALIFIER != 0 {
                1
            } else {
                0
            };
            provenance[provenance_index].push(rank, eligible);
        }
    }
    certificate(
        task,
        model_id,
        split,
        candidate_policy,
        format!("b3-{}", score_hasher.finalize().to_hex()),
        EvaluationAccumulators {
            overall,
            presence,
            qualifier_count,
            relation,
            provenance,
        },
    )
}

fn filtered_rank(
    scores: &[f32],
    filtered: &[HyperLeU32],
    target: u32,
    policy: HyperRelationalCandidatePolicy,
    target_role: u8,
    entity_roles: &[u8],
) -> Result<f64, HyperRelationalTaskError> {
    let positive = *scores
        .get(target as usize)
        .ok_or(HyperRelationalTaskError::CorruptArtifact("positive"))?;
    let mut optimistic = 0_u64;
    let mut pessimistic = 0_u64;
    if policy == HyperRelationalCandidatePolicy::FullEntity {
        let threshold = f32x8::splat(positive);
        let mut chunks = scores.chunks_exact(8);
        for chunk in &mut chunks {
            let lanes = f32x8::from(
                <[f32; 8]>::try_from(chunk)
                    .map_err(|_| HyperRelationalTaskError::CorruptArtifact("SIMD score chunk"))?,
            );
            optimistic += u64::from(lanes.cmp_gt(threshold).move_mask().count_ones());
            pessimistic += u64::from(lanes.cmp_ge(threshold).move_mask().count_ones());
        }
        for score in chunks.remainder() {
            optimistic += u64::from(*score > positive);
            pessimistic += u64::from(*score >= positive);
        }
    } else {
        for (score, role) in scores.iter().zip(entity_roles) {
            if *role & target_role != 0 {
                optimistic += u64::from(*score > positive);
                pessimistic += u64::from(*score >= positive);
            }
        }
    }
    for destination in filtered.iter().copied().map(HyperLeU32::get) {
        if policy == HyperRelationalCandidatePolicy::FullEntity
            || entity_roles[destination as usize] & target_role != 0
        {
            let score = scores[destination as usize];
            optimistic -= u64::from(score > positive);
            pessimistic -= u64::from(score >= positive);
        }
    }
    Ok(0.5 * (optimistic + pessimistic) as f64 + 1.0)
}

fn query_view(
    record: HyperQueryRecord,
    split: LinkPredictionSplit,
    base_relations: u32,
) -> HyperRelationalQueryView {
    HyperRelationalQueryView {
        source: record.source(),
        relation: record.relation(),
        qualifier_offset: record.qualifier_offset(),
        qualifier_count: record.qualifier_count(),
        split,
        inverse: record.relation() >= base_relations,
        target_role: target_role(record, base_relations),
    }
}

fn target_role(record: HyperQueryRecord, base_relations: u32) -> u8 {
    if record.relation() >= base_relations {
        ENTITY_ROLE_SUBJECT
    } else {
        ENTITY_ROLE_OBJECT
    }
}

fn certificate(
    task: &HyperRelationalTaskMapped,
    model_id: &str,
    split: LinkPredictionSplit,
    candidate_policy: HyperRelationalCandidatePolicy,
    score_blake3: String,
    accumulators: EvaluationAccumulators,
) -> Result<HyperRelationalScoreCertificate, HyperRelationalTaskError> {
    let qualifier_presence = labeled_slices(
        ["without-qualifiers", "with-qualifiers"],
        accumulators.presence.into_iter(),
        false,
    );
    let qualifier_count = accumulators
        .qualifier_count
        .into_iter()
        .enumerate()
        .filter(|(_, value)| value.queries != 0)
        .map(|(count, value)| HyperRelationalMetricSlice {
            label: format!("qualifiers-{count}").into(),
            metrics: value.finish(),
        })
        .collect::<Vec<_>>();
    let primary_relation = accumulators
        .relation
        .into_iter()
        .enumerate()
        .filter(|(_, value)| value.queries != 0)
        .map(|(relation, value)| HyperRelationalMetricSlice {
            label: format!("relation-{relation}").into(),
            metrics: value.finish(),
        })
        .collect::<Vec<_>>();
    let target_provenance = labeled_slices(
        ["primary-only", "primary-and-qualifier", "qualifier-only"],
        accumulators.provenance.into_iter(),
        true,
    );
    let metrics = accumulators.overall.finish();
    let certificate_id = certificate_identity(
        task.manifest().task_id.as_str(),
        model_id,
        split,
        candidate_policy,
        &score_blake3,
        &metrics,
        [
            &qualifier_presence,
            &qualifier_count,
            &primary_relation,
            &target_provenance,
        ],
    );
    Ok(HyperRelationalScoreCertificate {
        schema_version: HYPER_RELATIONAL_SCORE_SCHEMA.into(),
        certificate_id: certificate_id.into(),
        task_id: task.manifest().task_id.clone(),
        model_id: model_id.into(),
        split,
        candidate_policy,
        score_blake3: score_blake3.into(),
        metrics,
        qualifier_presence,
        qualifier_count,
        primary_relation,
        target_provenance,
    })
}

fn labeled_slices<const N: usize>(
    labels: [&str; N],
    values: impl Iterator<Item = MetricAccumulator>,
    keep_empty: bool,
) -> Vec<HyperRelationalMetricSlice> {
    labels
        .into_iter()
        .zip(values)
        .filter(|(_, value)| keep_empty || value.queries != 0)
        .map(|(label, value)| HyperRelationalMetricSlice {
            label: label.into(),
            metrics: value.finish(),
        })
        .collect()
}

fn certificate_identity<const N: usize>(
    task_id: &str,
    model_id: &str,
    split: LinkPredictionSplit,
    policy: HyperRelationalCandidatePolicy,
    score_blake3: &str,
    metrics: &HyperRelationalRankingMetrics,
    slices: [&[HyperRelationalMetricSlice]; N],
) -> String {
    let mut hasher = blake3::Hasher::new();
    hash_text(&mut hasher, HYPER_RELATIONAL_SCORE_SCHEMA);
    hash_text(&mut hasher, task_id);
    hash_text(&mut hasher, model_id);
    hasher.update(&[split as u8, policy as u8]);
    hash_text(&mut hasher, score_blake3);
    hash_metrics(&mut hasher, metrics);
    for family in slices {
        hasher.update(&(family.len() as u64).to_le_bytes());
        for slice in family {
            hash_text(&mut hasher, slice.label.as_str());
            hash_metrics(&mut hasher, &slice.metrics);
        }
    }
    format!("b3-{}", hasher.finalize().to_hex())
}

fn hash_metrics(hasher: &mut blake3::Hasher, metrics: &HyperRelationalRankingMetrics) {
    for value in [
        metrics.mean_reciprocal_rank,
        metrics.hits_at_1,
        metrics.hits_at_3,
        metrics.hits_at_5,
        metrics.hits_at_10,
    ] {
        hasher.update(&value.to_bits().to_le_bytes());
    }
    hasher.update(&metrics.queries.to_le_bytes());
    hasher.update(&metrics.candidates_scored.to_le_bytes());
}

fn hash_text(hasher: &mut blake3::Hasher, value: &str) {
    hasher.update(&(value.len() as u64).to_le_bytes());
    hasher.update(value.as_bytes());
}

fn hash_score_row(
    hasher: &mut blake3::Hasher,
    record: HyperQueryRecord,
    split: LinkPredictionSplit,
    base_relations: u32,
    scores: &[f32],
) {
    hasher.update(&record.statement_id().to_le_bytes());
    hasher.update(&record.source().to_le_bytes());
    hasher.update(&record.target().to_le_bytes());
    hasher.update(&record.relation().to_le_bytes());
    hasher.update(&record.qualifier_context().to_le_bytes());
    hasher.update(&record.qualifier_offset().to_le_bytes());
    hasher.update(&record.qualifier_count().to_le_bytes());
    hasher.update(&[
        split as u8,
        u8::from(record.relation() >= base_relations),
        target_role(record, base_relations),
    ]);
    hash_scores(hasher, scores);
}

#[cfg(target_endian = "little")]
fn hash_scores(hasher: &mut blake3::Hasher, scores: &[f32]) {
    hasher.update(scores.as_bytes());
}

#[cfg(not(target_endian = "little"))]
fn hash_scores(hasher: &mut blake3::Hasher, scores: &[f32]) {
    for score in scores {
        hasher.update(&score.to_bits().to_le_bytes());
    }
}

fn claim_locked_test(
    task: &HyperRelationalTaskMapped,
    lock_receipt: impl AsRef<Path>,
    output_root: impl AsRef<Path>,
) -> Result<(HyperRelationalTestLock, PathBuf, PathBuf), HyperRelationalTaskError> {
    let lock: HyperRelationalTestLock =
        serde_json::from_slice(&std::fs::read(lock_receipt.as_ref())?)?;
    validate_lock(task, &lock)?;
    let root = output_root.as_ref().to_path_buf();
    std::fs::create_dir_all(&root)?;
    let claim = root.join(format!("{}.test-claimed.json", lock.task_id));
    let claim_body = serde_json::to_vec_pretty(&(
        HYPER_RELATIONAL_TEST_LOCK_SCHEMA,
        lock.lock_id.as_str(),
        lock.task_id.as_str(),
        lock.selected_model_id.as_str(),
        lock.candidate_policy,
    ))?;
    match write_new_durable(&claim, &claim_body) {
        Err(HyperRelationalTaskError::Io(error))
            if error.kind() == std::io::ErrorKind::AlreadyExists =>
        {
            return Err(HyperRelationalTaskError::TestAlreadyClaimed(claim));
        }
        Err(error) => return Err(error),
        Ok(()) => {}
    }
    Ok((lock, root, claim))
}

fn validate_lock(
    task: &HyperRelationalTaskMapped,
    lock: &HyperRelationalTestLock,
) -> Result<(), HyperRelationalTaskError> {
    let input = HyperRelationalTestLockInput {
        task_id: lock.task_id.clone(),
        selection_ledger_id: lock.selection_ledger_id.clone(),
        selected_model_id: lock.selected_model_id.clone(),
        validation_certificate_id: lock.validation_certificate_id.clone(),
        candidate_policy: lock.candidate_policy,
    };
    if lock.schema_version != HYPER_RELATIONAL_TEST_LOCK_SCHEMA
        || lock.task_id != task.manifest().task_id
        || lock.lock_id != lock_identity(&input)?
    {
        return Err(HyperRelationalTaskError::CorruptArtifact("test lock"));
    }
    Ok(())
}

fn lock_identity(input: &HyperRelationalTestLockInput) -> Result<String, HyperRelationalTaskError> {
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            HYPER_RELATIONAL_TEST_LOCK_SCHEMA,
            input.task_id.as_str(),
            input.selection_ledger_id.as_str(),
            input.selected_model_id.as_str(),
            input.validation_certificate_id.as_str(),
            input.candidate_policy,
        ))?)
        .to_hex()
    ))
}

fn write_new_durable(path: &Path, bytes: &[u8]) -> Result<(), HyperRelationalTaskError> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
