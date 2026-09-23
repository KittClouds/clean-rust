use std::path::{Path, PathBuf};

use anyhow::{Context, Result, anyhow, bail};
use gliner25_rs::overlap::{OverlapPolicy, Spanned, resolve_overlaps};
use gliner25_rs::processor::{ProcessedRecord, SchemaTask, SchemaTransformer, TaskType};
use gliner25_rs::runtime::{
    IoDType, Precision, build_session, sigmoid, take_bool, take_float, take_i64,
};
use ort::session::Session;
use ort::value::TensorRef;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize)]
pub struct FeatureManifest {
    pub architecture: String,
    pub hidden_size: usize,
    pub pool_size: usize,
    pub length_buckets: Vec<usize>,
    pub enable_abstention: bool,
    pub feature_heads_version: u32,
    pub explicit_span_scorer: bool,
    pub explicit_query_cap: usize,
    pub explicit_span_cap: usize,
    #[serde(default)]
    pub explicit_tiers: Vec<[usize; 2]>,
    pub sparse_relation_scorer: bool,
    pub relation_type_cap: usize,
    pub relation_score_pair_cap: usize,
    pub directional_relation_states: bool,
    pub relation_heads_per_type: usize,
    pub relation_tails_per_type: usize,
    pub relation_pair_cap: usize,
    pub relation_argument_proposal_threshold: f32,
    pub relation_temperature: f32,
    pub pair_temperature: f32,
}

#[derive(Debug, Clone)]
pub struct RawClassification {
    pub task: String,
    pub labels: Vec<String>,
    pub logits: Vec<f32>,
    pub multi_label: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct RawMention {
    pub text: String,
    pub field: String,
    pub logit: f32,
    pub score: f32,
    pub char_start: usize,
    pub char_end: usize,
    pub word_start: usize,
    pub word_end: usize,
    pub query_id: usize,
}

impl Spanned for RawMention {
    fn start(&self) -> usize {
        self.word_start
    }
    fn end(&self) -> usize {
        self.word_end
    }
    fn score(&self) -> f32 {
        self.score
    }
}

pub struct FeatureTrace {
    pub text: String,
    pub record: ProcessedRecord,
    caller_words: usize,
    model_words: usize,
    pub bucket: usize,
    word_mask: Vec<i64>,
    pub text_states: Vec<f32>,
    pub query_states: Vec<f32>,
    pub query_specs: Vec<(usize, usize)>,
    pub cand_indices: Vec<i64>,
    pub pair_logits: Vec<f32>,
    pub cand_valid: Vec<bool>,
    pub null_logits: Vec<f32>,
    pub classifications: Vec<RawClassification>,
}

impl FeatureTrace {
    /// Number of caller-owned words. A synthetic terminal punctuation token is
    /// model context, never a caller-addressable span.
    pub fn num_words(&self) -> usize {
        self.caller_words
    }
    pub fn model_words(&self) -> usize {
        self.model_words
    }
    pub fn num_queries(&self) -> usize {
        self.query_specs.len()
    }

    pub fn query_id(&self, task_type: TaskType, task: &str, label: &str) -> Option<usize> {
        self.query_specs
            .iter()
            .enumerate()
            .find_map(|(query_id, &(group, role))| {
                let mapped = &self.record.tasks[group];
                (mapped.task_type == task_type
                    && mapped.task_name == task
                    && mapped.labels[role] == label)
                    .then_some(query_id)
            })
    }
}

pub struct FeatureEngine {
    encoder: Session,
    routed_gather: Session,
    classifier: Session,
    boundary_heads: Vec<(usize, Option<Session>)>,
    explicit_heads: Vec<ExplicitSessionSlot>,
    relation_heads: Vec<(usize, Option<Session>)>,
    transformer: SchemaTransformer,
    manifest: FeatureManifest,
    dtype: IoDType,
    dir: PathBuf,
    suffix: &'static str,
    threads: usize,
    tiered_explicit: bool,
}

struct ExplicitSessionSlot {
    bucket: usize,
    query_cap: usize,
    span_cap: usize,
    session: Option<Session>,
}

impl FeatureEngine {
    pub fn new(models_dir: impl Into<PathBuf>, threads: usize) -> Result<Self> {
        let dir = models_dir.into();
        let manifest_path = dir.join("boundary_manifest.json");
        let manifest: FeatureManifest = serde_json::from_slice(
            &std::fs::read(&manifest_path)
                .with_context(|| format!("read {}", manifest_path.display()))?,
        )?;
        if manifest.architecture != "boundary" || manifest.feature_heads_version != 2 {
            bail!("model directory is not a feature-head-v2 boundary export");
        }
        if !manifest.explicit_span_scorer || !manifest.sparse_relation_scorer {
            bail!("feature-head-v2 export is missing a required neural scorer");
        }
        let precision = Precision::Fp32;
        let suffix = precision.suffix();
        let load = |stem: &str| build_session(&dir.join(format!("{stem}{suffix}.onnx")), threads);
        let mut buckets = manifest.length_buckets.clone();
        buckets.sort_unstable();
        let slots = || buckets.iter().copied().map(|b| (b, None)).collect();
        let mut explicit_tiers = manifest.explicit_tiers.clone();
        if explicit_tiers.is_empty() {
            explicit_tiers.push([manifest.explicit_query_cap, manifest.explicit_span_cap]);
        }
        explicit_tiers.sort_unstable_by_key(|tier| (tier[0] * tier[1], tier[0], tier[1]));
        explicit_tiers.dedup();
        if !explicit_tiers.iter().any(|tier| {
            tier[0] == manifest.explicit_query_cap && tier[1] == manifest.explicit_span_cap
        }) {
            bail!("explicit tiers omit the manifest's maximum scorer shape");
        }
        let explicit_heads = buckets
            .iter()
            .flat_map(|&bucket| {
                explicit_tiers.iter().map(move |tier| ExplicitSessionSlot {
                    bucket,
                    query_cap: tier[0],
                    span_cap: tier[1],
                    session: None,
                })
            })
            .collect();
        let transformer = SchemaTransformer::from_tokenizer_file(&dir.join("tokenizer.json"))?;
        Ok(Self {
            encoder: load("encoder")?,
            routed_gather: load("routed_gather")?,
            classifier: load("classifier")?,
            boundary_heads: slots(),
            explicit_heads,
            relation_heads: slots(),
            transformer,
            manifest,
            dtype: precision.io_dtype(),
            dir,
            suffix,
            threads,
            tiered_explicit: true,
        })
    }

    pub fn set_tiered_explicit(&mut self, enabled: bool) {
        self.tiered_explicit = enabled;
    }

    pub fn manifest(&self) -> &FeatureManifest {
        &self.manifest
    }

    pub fn trace(&mut self, text: &str, tasks: &[SchemaTask]) -> Result<FeatureTrace> {
        self.trace_with_descriptions(text, tasks, &[])
    }

    pub fn trace_with_descriptions(
        &mut self,
        text: &str,
        tasks: &[SchemaTask],
        descriptions: &[Vec<(String, String)>],
    ) -> Result<FeatureTrace> {
        // GLiNER2's canonical processor always supplies sentence-final
        // punctuation to the encoder. Keep that token model-facing only: byte
        // offsets and returned text remain in the caller's coordinate space.
        let model_text;
        let encoded_text = if text.ends_with(['.', '!', '?']) {
            text
        } else {
            model_text = format!("{text}.");
            &model_text
        };
        let record =
            self.transformer
                .transform_with_descriptions(encoded_text, tasks, descriptions)?;
        let model_words = record.num_words();
        let caller_words = record
            .word_to_char_maps
            .iter()
            .take_while(|(start, _)| *start < text.len())
            .count();
        if caller_words == 0 {
            bail!("feature decoding requires at least one caller word");
        }
        let bucket = self.pick_bucket(model_words)?;
        let hidden_size = self.manifest.hidden_size;
        let seq = record.input_ids.len() as i64;
        let hidden = {
            let ids = TensorRef::from_array_view(([1, seq], record.input_ids.as_slice()))?;
            let mask = TensorRef::from_array_view(([1, seq], record.attention_mask.as_slice()))?;
            let output = self.encoder.run(ort::inputs![ids, mask])?;
            take_float(&output["last_hidden_state"], self.dtype)?.1
        };

        let mut word_indices = record.word_first_positions();
        let mut word_mask = vec![1_i64; model_words];
        word_indices.resize(bucket, 0);
        word_mask.resize(bucket, 0);
        let text_states = self.gather(&hidden, seq, &word_indices, &word_mask)?;

        let (query_indices, query_specs) = record.query_markers();
        let query_mask = vec![1_i64; query_indices.len()];
        let query_states = self.gather(&hidden, seq, &query_indices, &query_mask)?;
        let (cand_indices, pair_logits, cand_valid, null_logits) = if query_indices.is_empty() {
            (Vec::new(), Vec::new(), Vec::new(), Vec::new())
        } else {
            let dtype = self.dtype;
            let head = Self::session_for(
                &mut self.boundary_heads,
                bucket,
                &self.dir,
                self.suffix,
                self.threads,
                "boundary_head_L",
            )?;
            let output = head.run(ort::inputs![
                TensorRef::from_array_view((
                    [1, bucket as i64, hidden_size as i64],
                    text_states.as_slice()
                ))?,
                TensorRef::from_array_view(([1, bucket as i64], word_mask.as_slice()))?,
                TensorRef::from_array_view((
                    [1, query_indices.len() as i64, hidden_size as i64],
                    query_states.as_slice()
                ))?,
                TensorRef::from_array_view((
                    [1, query_indices.len() as i64],
                    query_mask.as_slice()
                ))?,
            ])?;
            (
                take_i64(&output["cand_indices"])?.1,
                take_float(&output["pair_logits"], dtype)?.1,
                take_bool(&output["cand_valid"])?.1,
                take_float(&output["null_logits"], dtype)?.1,
            )
        };
        let classifications = self.classification_logits(&record, &hidden, seq)?;
        Ok(FeatureTrace {
            text: text.to_owned(),
            record,
            caller_words,
            model_words,
            bucket,
            word_mask,
            text_states,
            query_states,
            query_specs,
            cand_indices,
            pair_logits,
            cand_valid,
            null_logits,
            classifications,
        })
    }

    pub fn decode_mentions(
        &self,
        trace: &FeatureTrace,
        threshold: f32,
        content_fields: &[String],
        policy: OverlapPolicy,
    ) -> Vec<RawMention> {
        let pool = self.manifest.pool_size;
        let mut output = Vec::new();
        for (query_id, &(group, role)) in trace.query_specs.iter().enumerate() {
            let task = &trace.record.tasks[group];
            let field = &task.labels[role];
            if task.task_type != TaskType::Entities || !content_fields.iter().any(|v| v == field) {
                continue;
            }
            if self.manifest.enable_abstention {
                let best = (0..pool)
                    .filter(|&i| trace.cand_valid[query_id * pool + i])
                    .map(|i| trace.pair_logits[query_id * pool + i])
                    .fold(f32::NEG_INFINITY, f32::max);
                if trace.null_logits[query_id] > best {
                    continue;
                }
            }
            let mut candidates = Vec::new();
            for candidate in 0..pool {
                let offset = query_id * pool + candidate;
                if !trace.cand_valid[offset] {
                    continue;
                }
                let logit = trace.pair_logits[offset] / self.manifest.pair_temperature;
                let score = sigmoid(logit);
                if score < threshold {
                    continue;
                }
                let start = trace.cand_indices[offset * 2] as usize;
                let end = trace.cand_indices[offset * 2 + 1] as usize;
                if end <= start || end > trace.num_words() {
                    continue;
                }
                let (char_start, _) = trace.record.word_to_char_maps[start];
                let (_, char_end) = trace.record.word_to_char_maps[end - 1];
                candidates.push(RawMention {
                    text: trace.text[char_start..char_end].to_owned(),
                    field: field.clone(),
                    logit,
                    score,
                    char_start,
                    char_end,
                    word_start: start,
                    word_end: end,
                    query_id,
                });
            }
            output.extend(resolve_overlaps(&candidates, policy));
        }
        output.sort_by(|a, b| {
            a.char_start
                .cmp(&b.char_start)
                .then(a.char_end.cmp(&b.char_end))
                .then(a.field.cmp(&b.field))
        });
        output
    }

    pub fn explicit_logits(
        &mut self,
        trace: &FeatureTrace,
        query_ids: &[usize],
        spans: &[(usize, usize)],
    ) -> Result<Vec<f32>> {
        if query_ids.is_empty() || spans.is_empty() {
            return Ok(Vec::new());
        }
        let maximum_query_cap = self.manifest.explicit_query_cap;
        let maximum_span_cap = self.manifest.explicit_span_cap;
        let hidden = self.manifest.hidden_size;
        let mut result = vec![f32::NEG_INFINITY; query_ids.len() * spans.len()];
        for (q_block, q_chunk) in query_ids.chunks(maximum_query_cap).enumerate() {
            for &query_id in q_chunk {
                if query_id >= trace.num_queries() {
                    bail!("query id {query_id} is out of range");
                }
            }
            for (s_block, s_chunk) in spans.chunks(maximum_span_cap).enumerate() {
                for &(start, end) in s_chunk {
                    if start >= end || end > trace.num_words() {
                        bail!("illegal explicit span [{start},{end})");
                    }
                }
                let [q_cap, s_cap] = choose_explicit_tier(
                    &self.manifest.explicit_tiers,
                    q_chunk.len(),
                    s_chunk.len(),
                    [maximum_query_cap, maximum_span_cap],
                    self.tiered_explicit,
                );
                let mut states = vec![0.0_f32; q_cap * hidden];
                let mut mask = vec![0_i64; q_cap];
                for (local, &query_id) in q_chunk.iter().enumerate() {
                    states[local * hidden..(local + 1) * hidden].copy_from_slice(
                        &trace.query_states[query_id * hidden..(query_id + 1) * hidden],
                    );
                    mask[local] = 1;
                }
                let mut indices = vec![0_i64; q_cap * s_cap * 2];
                for query in 0..q_cap {
                    for (local, &(start, end)) in s_chunk.iter().enumerate() {
                        let base = (query * s_cap + local) * 2;
                        indices[base] = start as i64;
                        indices[base + 1] = end as i64;
                    }
                    for local in s_chunk.len()..s_cap {
                        indices[(query * s_cap + local) * 2 + 1] = 1;
                    }
                }
                let dtype = self.dtype;
                let head = Self::explicit_session_for(
                    &mut self.explicit_heads,
                    trace.bucket,
                    q_cap,
                    s_cap,
                    &self.dir,
                    self.suffix,
                    self.threads,
                    maximum_query_cap,
                    maximum_span_cap,
                )?;
                let output = head.run(ort::inputs![
                    TensorRef::from_array_view((
                        [1, trace.bucket as i64, hidden as i64],
                        trace.text_states.as_slice()
                    ))?,
                    TensorRef::from_array_view((
                        [1, trace.bucket as i64],
                        trace.word_mask.as_slice()
                    ))?,
                    TensorRef::from_array_view((
                        [1, q_cap as i64, hidden as i64],
                        states.as_slice()
                    ))?,
                    TensorRef::from_array_view(([1, q_cap as i64], mask.as_slice()))?,
                    TensorRef::from_array_view((
                        [1, q_cap as i64, s_cap as i64, 2],
                        indices.as_slice()
                    ))?,
                ])?;
                let logits = take_float(&output["pair_logits"], dtype)?.1;
                for q in 0..q_chunk.len() {
                    for s in 0..s_chunk.len() {
                        result[(q_block * maximum_query_cap + q) * spans.len()
                            + s_block * maximum_span_cap
                            + s] = logits[q * s_cap + s] / self.manifest.pair_temperature;
                    }
                }
            }
        }
        Ok(result)
    }

    pub fn relation_states(
        &self,
        trace: &FeatureTrace,
        role_pairs: &[(usize, usize)],
    ) -> Result<Vec<f32>> {
        let h = self.manifest.hidden_size;
        let width = if self.manifest.directional_relation_states {
            h * 2
        } else {
            h
        };
        let mut output = Vec::with_capacity(role_pairs.len() * width);
        for &(head, tail) in role_pairs {
            if head >= trace.num_queries() || tail >= trace.num_queries() {
                bail!("relation role query out of range");
            }
            if self.manifest.directional_relation_states {
                output.extend_from_slice(&trace.query_states[head * h..(head + 1) * h]);
                output.extend_from_slice(&trace.query_states[tail * h..(tail + 1) * h]);
            } else {
                for index in 0..h {
                    output.push(
                        (trace.query_states[head * h + index]
                            + trace.query_states[tail * h + index])
                            * 0.5,
                    );
                }
            }
        }
        Ok(output)
    }

    pub fn relation_logits(
        &mut self,
        trace: &FeatureTrace,
        relation_states: &[f32],
        relation_count: usize,
        pairs: &[[i64; 5]],
    ) -> Result<Vec<f32>> {
        let r_cap = self.manifest.relation_type_cap;
        let p_cap = self.manifest.relation_score_pair_cap;
        if relation_count > r_cap {
            bail!("{relation_count} relations exceed export cap {r_cap}");
        }
        let state_width = if self.manifest.directional_relation_states {
            self.manifest.hidden_size * 2
        } else {
            self.manifest.hidden_size
        };
        if relation_states.len() != relation_count * state_width {
            bail!("relation state shape mismatch");
        }
        let mut padded_states = vec![0.0_f32; r_cap * state_width];
        padded_states[..relation_states.len()].copy_from_slice(relation_states);
        let mut result = Vec::with_capacity(pairs.len());
        for chunk in pairs.chunks(p_cap) {
            let mut padded_pairs = vec![0_i64; p_cap * 5];
            for row in 0..p_cap {
                padded_pairs[row * 5 + 2] = 1;
                padded_pairs[row * 5 + 4] = 1;
            }
            for (row, pair) in chunk.iter().enumerate() {
                if pair[0] < 0 || pair[0] as usize >= relation_count {
                    bail!("relation pair type index out of range");
                }
                padded_pairs[row * 5..row * 5 + 5].copy_from_slice(pair);
            }
            let dtype = self.dtype;
            let head = Self::session_for(
                &mut self.relation_heads,
                trace.bucket,
                &self.dir,
                self.suffix,
                self.threads,
                "relation_scorer_L",
            )?;
            let text_length = [trace.model_words() as i64];
            let output = head.run(ort::inputs![
                TensorRef::from_array_view((
                    [1, trace.bucket as i64, self.manifest.hidden_size as i64],
                    trace.text_states.as_slice()
                ))?,
                TensorRef::from_array_view((
                    [1, r_cap as i64, state_width as i64],
                    padded_states.as_slice()
                ))?,
                TensorRef::from_array_view(([p_cap as i64, 5], padded_pairs.as_slice()))?,
                TensorRef::from_array_view(([1], text_length.as_slice()))?,
            ])?;
            let logits = take_float(&output["relation_logits"], dtype)?.1;
            result.extend(
                logits
                    .into_iter()
                    .take(chunk.len())
                    .map(|v| v / self.manifest.relation_temperature),
            );
        }
        Ok(result)
    }

    fn classification_logits(
        &mut self,
        record: &ProcessedRecord,
        hidden: &[f32],
        seq: i64,
    ) -> Result<Vec<RawClassification>> {
        let (indices, specs) = record.cls_markers();
        if indices.is_empty() {
            return Ok(Vec::new());
        }
        let states = self.gather(hidden, seq, &indices, &vec![1_i64; indices.len()])?;
        let output = self
            .classifier
            .run(ort::inputs![TensorRef::from_array_view((
                [indices.len() as i64, self.manifest.hidden_size as i64],
                states.as_slice(),
            ))?])?;
        let flat = take_float(&output["logits"], self.dtype)?.1;
        let mut output = Vec::new();
        for (group, task) in record.tasks.iter().enumerate() {
            if task.task_type != TaskType::Classifications {
                continue;
            }
            let mut logits = vec![0.0; task.labels.len()];
            for (index, &(mapped_group, choice)) in specs.iter().enumerate() {
                if mapped_group == group {
                    logits[choice] = flat[index];
                }
            }
            output.push(RawClassification {
                task: task.task_name.clone(),
                labels: task.labels.clone(),
                logits,
                multi_label: task.multi_label,
            });
        }
        Ok(output)
    }

    fn gather(
        &mut self,
        hidden: &[f32],
        seq: i64,
        indices: &[i64],
        mask: &[i64],
    ) -> Result<Vec<f32>> {
        if indices.is_empty() {
            return Ok(Vec::new());
        }
        let count = indices.len() as i64;
        let output = self.routed_gather.run(ort::inputs![
            TensorRef::from_array_view(([1, seq, self.manifest.hidden_size as i64], hidden))?,
            TensorRef::from_array_view(([1, count], indices))?,
            TensorRef::from_array_view(([1, count], mask))?,
        ])?;
        Ok(take_float(&output["states"], self.dtype)?.1)
    }

    fn pick_bucket(&self, words: usize) -> Result<usize> {
        choose_length_bucket(&self.manifest.length_buckets, words)
            .ok_or_else(|| anyhow!("{words} words exceed the largest ONNX bucket"))
    }

    fn session_for<'a>(
        slots: &'a mut [(usize, Option<Session>)],
        bucket: usize,
        dir: &Path,
        suffix: &str,
        threads: usize,
        prefix: &str,
    ) -> Result<&'a mut Session> {
        let slot = slots
            .iter()
            .position(|(value, _)| *value == bucket)
            .ok_or_else(|| anyhow!("missing bucket {bucket}"))?;
        if slots[slot].1.is_none() {
            slots[slot].1 = Some(build_session(
                &dir.join(format!("{prefix}{bucket}{suffix}.onnx")),
                threads,
            )?);
        }
        Ok(slots[slot].1.as_mut().expect("session was loaded"))
    }

    #[allow(clippy::too_many_arguments)]
    fn explicit_session_for<'a>(
        slots: &'a mut [ExplicitSessionSlot],
        bucket: usize,
        query_cap: usize,
        span_cap: usize,
        dir: &Path,
        suffix: &str,
        threads: usize,
        maximum_query_cap: usize,
        maximum_span_cap: usize,
    ) -> Result<&'a mut Session> {
        let slot = slots
            .iter()
            .position(|value| {
                value.bucket == bucket && value.query_cap == query_cap && value.span_cap == span_cap
            })
            .ok_or_else(|| {
                anyhow!("missing explicit scorer tier Q{query_cap}/S{span_cap}/L{bucket}")
            })?;
        if slots[slot].session.is_none() {
            let stem = if query_cap == maximum_query_cap && span_cap == maximum_span_cap {
                format!("explicit_span_scorer_L{bucket}{suffix}.onnx")
            } else {
                format!("explicit_span_scorer_Q{query_cap}_S{span_cap}_L{bucket}{suffix}.onnx")
            };
            slots[slot].session = Some(build_session(&dir.join(stem), threads)?);
        }
        Ok(slots[slot]
            .session
            .as_mut()
            .expect("explicit session was loaded"))
    }
}

fn choose_length_bucket(buckets: &[usize], words: usize) -> Option<usize> {
    buckets.iter().copied().filter(|&b| b >= words).min()
}

fn choose_explicit_tier(
    tiers: &[[usize; 2]],
    queries: usize,
    spans: usize,
    maximum: [usize; 2],
    enabled: bool,
) -> [usize; 2] {
    if !enabled {
        return maximum;
    }
    tiers
        .iter()
        .copied()
        .filter(|tier| tier[0] >= queries && tier[1] >= spans)
        .min_by_key(|tier| (tier[0] * tier[1], tier[0], tier[1]))
        .unwrap_or(maximum)
}

#[cfg(test)]
mod tests {
    use super::{choose_explicit_tier, choose_length_bucket};

    #[test]
    fn length_bucket_uses_smallest_fitting_export() {
        let buckets = [64, 128, 256, 320, 384, 448, 512];
        assert_eq!(choose_length_bucket(&buckets, 1), Some(64));
        assert_eq!(choose_length_bucket(&buckets, 270), Some(320));
        assert_eq!(choose_length_bucket(&buckets, 385), Some(448));
        assert_eq!(choose_length_bucket(&buckets, 513), None);
    }

    #[test]
    fn explicit_tier_uses_smallest_fitting_surface() {
        let tiers = [[8, 32], [16, 64], [64, 128]];
        assert_eq!(
            choose_explicit_tier(&tiers, 4, 12, [64, 128], true),
            [8, 32]
        );
        assert_eq!(
            choose_explicit_tier(&tiers, 9, 33, [64, 128], true),
            [16, 64]
        );
        assert_eq!(
            choose_explicit_tier(&tiers, 17, 65, [64, 128], true),
            [64, 128]
        );
    }

    #[test]
    fn explicit_tier_can_reproduce_the_canonical_head() {
        let tiers = [[8, 32], [16, 64], [64, 128]];
        assert_eq!(
            choose_explicit_tier(&tiers, 4, 12, [64, 128], false),
            [64, 128]
        );
    }
}
