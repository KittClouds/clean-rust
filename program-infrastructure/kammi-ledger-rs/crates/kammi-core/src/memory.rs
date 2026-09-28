//! Contextual institutional memory (`memory.py`, `memory_graph.py`).
//!
//! Records, supersession, trace and idempotent search receipts are Python-identical. Vectors
//! come from a pluggable [`Embedder`] (Phoenix runners such as EmbeddingGemma or Jina v5);
//! each record stores its exact vector bytes and the embedder identity, so replay never
//! re-embeds. Retrieval is native: BM25 over record text, cosine over vectors from the same
//! embedder, and graph neighbours through shared tags or custody references, fused with the
//! same reciprocal-rank rule and adaptive over-fetch as Python.

use std::sync::Arc;

use hashbrown::{HashMap, HashSet};
use indexmap::IndexMap;
use kammi_jcs::{canonical, raw_id, strict_json, Sha256Id, Value};
use kammi_store::NewEvent;

use crate::error::{value_error, LedgerError, Result};
use crate::json::{get_str, merged, without};
use crate::ledger::Ledger;

pub const KINDS: [&str; 9] = [
    "OBSERVED",
    "DERIVED",
    "INTERPRETIVE",
    "HYPOTHESIS",
    "PREFERENCE",
    "PROCEDURE",
    "DECISION",
    "FAILURE_MODE",
    "RESULT_SUMMARY",
];

pub use crate::embed::{Embedder, Embeddings, Input, ModelIdentity, Role};

/// The three retrieval channels of `/v1` memory search. The daemon serves them from the
/// Ladybug projection (FTS and vector indexes, graph relationships) in the supervised
/// projector, exactly as Python serves them from its `MemoryGraph`; the in-process native
/// channels are the fallback for embedded use and tests. Every call carries the memory
/// journal position the caller has committed, so answers always include its own writes.
pub trait MemoryIndex: Send + Sync {
    /// Top `count` lexical matches as (memory id, score), best first.
    fn fts(&self, query: &str, count: usize, memory_seq: u64) -> Result<Vec<(String, f64)>>;
    /// Top `count` vector matches as (memory id, similarity), best first.
    fn vector(&self, vector: &[f32], count: usize, memory_seq: u64) -> Result<Vec<(String, f64)>>;
    /// Memories sharing a tag or a custody reference with `identity`, sorted.
    fn neighbors(&self, identity: &str, memory_seq: u64) -> Result<Vec<String>>;
}

pub fn pack_vector(vector: &[f32]) -> Vec<u8> {
    vector.iter().flat_map(|v| v.to_le_bytes()).collect()
}

pub fn unpack_vector(raw: &[u8]) -> Result<Vec<f32>> {
    if raw.is_empty() || !raw.len().is_multiple_of(4) {
        return value_error("invalid embedding byte count");
    }
    Ok(raw
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
        .collect())
}

fn tokens(text: &str) -> Vec<String> {
    // Python `re.findall(r"\w+", text.casefold())`.
    let folded = text.to_lowercase();
    let mut out = Vec::new();
    let mut current = String::new();
    for ch in folded.chars() {
        if ch.is_alphanumeric() || ch == '_' {
            current.push(ch);
        } else if !current.is_empty() {
            out.push(std::mem::take(&mut current));
        }
    }
    if !current.is_empty() {
        out.push(current);
    }
    out
}

struct Indexed {
    terms: HashMap<String, u32>,
    length: u32,
    vector: Vec<f32>,
    model: String,
}

pub struct Memory {
    pub records: IndexMap<String, Value>,
    /// old -> [new]
    pub superseded: HashMap<String, Vec<String>>,
    indexed: HashMap<String, Indexed>,
    postings: HashMap<String, HashSet<String>>,
    total_length: u64,
    embedder: Arc<dyn Embedder>,
    /// When set, retrieval channels come from the projection instead of native indexes.
    index: Option<Arc<dyn MemoryIndex>>,
}

impl Memory {
    /// Replays the memory journal (`MemoryService.__init__`).
    pub fn replay(ledger: &Ledger, embedder: Arc<dyn Embedder>) -> Result<Memory> {
        let mut memory = Memory {
            records: IndexMap::new(),
            superseded: HashMap::new(),
            indexed: HashMap::new(),
            postings: HashMap::new(),
            total_length: 0,
            embedder,
            index: None,
        };
        for seq in 1..=ledger.store.memory.seq() {
            let stored = ledger.store.memory.read(seq)?;
            let event = strict_json(&stored.event)?;
            let payload = strict_json(&stored.payload)?;
            memory
                .apply(ledger, get_str(&event, "type")?, &payload)
                .map_err(|e| {
                    LedgerError::Value(format!(
                        "memory replay of event {seq} failed: {}",
                        e.detail()
                    ))
                })?;
        }
        Ok(memory)
    }

    fn apply(&mut self, ledger: &Ledger, kind: &str, payload: &Value) -> Result<()> {
        match kind {
            "MemoryRecorded" => {
                let record = ledger.object_json(get_str(payload, "record_artifact_id")?)?;
                let identity = get_str(&record, "memory_id")?.to_string();
                if raw_id(&canonical(&without(&record, &["memory_id"]))?).to_string() != identity {
                    return value_error("memory identity mismatch");
                }
                for reference in crate::json::string_list(&record, "custody_refs")? {
                    if !ledger.valid_custody_ref(&reference) {
                        return value_error("memory refers to unavailable custody evidence");
                    }
                }
                let vector = unpack_vector(
                    &ledger.object_bytes(get_str(&record, "embedding_artifact_id")?)?,
                )?;
                self.index(&identity, &record, vector);
                self.records.insert(identity, record);
            }
            "MemorySuperseded" => {
                let (old, new) = (get_str(payload, "old_id")?, get_str(payload, "new_id")?);
                if !self.records.contains_key(old) || !self.records.contains_key(new) {
                    return value_error("supersession references unknown memory");
                }
                let targets = self.superseded.entry(old.to_string()).or_default();
                if !targets.iter().any(|t| t == new) {
                    targets.push(new.to_string());
                }
            }
            _ => {}
        }
        Ok(())
    }

    fn index(&mut self, identity: &str, record: &Value, vector: Vec<f32>) {
        let words = tokens(record["text"].as_str().unwrap_or(""));
        let mut terms: HashMap<String, u32> = HashMap::new();
        for word in &words {
            *terms.entry(word.clone()).or_default() += 1;
        }
        for term in terms.keys() {
            self.postings
                .entry(term.clone())
                .or_default()
                .insert(identity.to_string());
        }
        self.total_length += words.len() as u64;
        let model = record["embedding_model_id"]
            .as_str()
            .unwrap_or("")
            .to_string();
        self.indexed.insert(
            identity.to_string(),
            Indexed {
                terms,
                length: words.len() as u32,
                vector,
                model,
            },
        );
    }

    pub fn set_index(&mut self, index: Arc<dyn MemoryIndex>) {
        self.index = Some(index);
    }

    pub fn embedder_identity(&self) -> &str {
        &self.embedder.model_identity().id
    }

    fn view(&self, identity: &str) -> Result<Value> {
        let record = self
            .records
            .get(identity)
            .ok_or_else(|| LedgerError::Value("unknown memory".into()))?;
        let grounded = record["custody_refs"]
            .as_array()
            .is_some_and(|r| !r.is_empty());
        Ok(merged(
            record,
            crate::obj! {
                "superseded_by" => self.superseded.get(identity).cloned().unwrap_or_default(),
                "grounding" => if grounded { "EVIDENCE_CITED" } else { "UNGROUNDED" },
            },
        ))
    }

    /// BM25 over record text (k1 = 1.2, b = 0.75), ranked by score then identity.
    fn fts(&self, query: &str) -> Vec<(String, f64)> {
        let n = self.indexed.len() as f64;
        let average = if self.indexed.is_empty() {
            1.0
        } else {
            self.total_length as f64 / n
        };
        let mut scores: HashMap<&str, f64> = HashMap::new();
        let unique: HashSet<String> = tokens(query).into_iter().collect();
        for term in &unique {
            let Some(documents) = self.postings.get(term) else {
                continue;
            };
            let df = documents.len() as f64;
            let idf = ((n - df + 0.5) / (df + 0.5) + 1.0).ln();
            for id in documents {
                let doc = &self.indexed[id];
                let tf = f64::from(doc.terms[term]);
                let norm = 1.2 * (1.0 - 0.75 + 0.75 * f64::from(doc.length) / average);
                *scores.entry(id.as_str()).or_default() += idf * tf * 2.2 / (tf + norm);
            }
        }
        let mut ranked: Vec<(String, f64)> = scores
            .into_iter()
            .map(|(k, v)| (k.to_string(), v))
            .collect();
        ranked.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap().then_with(|| a.0.cmp(&b.0)));
        ranked
    }

    /// Cosine similarity against records embedded by the current embedder.
    fn vector(&self, query: &[f32]) -> Vec<(String, f64)> {
        let model = self.embedder.model_identity().id.as_str();
        let norm = |v: &[f32]| {
            v.iter()
                .map(|x| f64::from(*x) * f64::from(*x))
                .sum::<f64>()
                .sqrt()
        };
        let query_norm = norm(query);
        let mut ranked: Vec<(String, f64)> = self
            .indexed
            .iter()
            .filter(|(_, d)| d.model == model && d.vector.len() == query.len())
            .map(|(id, d)| {
                let dot: f64 = d
                    .vector
                    .iter()
                    .zip(query)
                    .map(|(a, b)| f64::from(*a) * f64::from(*b))
                    .sum();
                let denom = norm(&d.vector) * query_norm;
                (id.clone(), if denom == 0.0 { 0.0 } else { dot / denom })
            })
            .collect();
        ranked.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap().then_with(|| a.0.cmp(&b.0)));
        ranked
    }

    /// Memories sharing a tag or a custody reference (`MemoryGraph.neighbors`).
    pub fn neighbors(&self, identity: &str) -> Vec<String> {
        let Some(record) = self.records.get(identity) else {
            return Vec::new();
        };
        let tags: HashSet<&str> = record["tags"]
            .as_array()
            .map(|t| t.iter().filter_map(Value::as_str).collect())
            .unwrap_or_default();
        let refs: HashSet<&str> = record["custody_refs"]
            .as_array()
            .map(|t| t.iter().filter_map(Value::as_str).collect())
            .unwrap_or_default();
        let mut out: Vec<String> = self
            .records
            .iter()
            .filter(|(id, _)| id.as_str() != identity)
            .filter(|(_, r)| {
                r["tags"].as_array().is_some_and(|t| {
                    t.iter()
                        .any(|x| x.as_str().is_some_and(|s| tags.contains(s)))
                }) || r["custody_refs"].as_array().is_some_and(|t| {
                    t.iter()
                        .any(|x| x.as_str().is_some_and(|s| refs.contains(s)))
                })
            })
            .map(|(id, _)| id.clone())
            .collect();
        out.sort();
        out
    }
}

impl Ledger {
    fn memory_ref(&self) -> Result<&Memory> {
        self.memory
            .as_ref()
            .ok_or_else(|| LedgerError::Value("memory runtime is not configured".into()))
    }

    /// Appends to the memory journal (`MemoryService._emit`), with its own chain and the
    /// `+00:00` timestamp form.
    fn memory_emit(
        &mut self,
        kind: &str,
        payload: &Value,
        actor: &str,
        request_id: &str,
    ) -> Result<String> {
        let payload_bytes = canonical(payload)?;
        let payload_id = raw_id(&payload_bytes).to_string();
        if let Some(prior) = self.store.memory.by_request(request_id)? {
            let event = strict_json(&prior.event)?;
            if event["type"].as_str() != Some(kind)
                || event["payload_artifact"].as_str() != Some(payload_id.as_str())
            {
                return value_error("memory request ID reused for another action");
            }
            return Ok(prior.event_id.to_string());
        }
        let event = crate::obj! {
            "schema" => "KAMMI_EVENT_V1",
            "seq" => self.store.memory.seq() + 1,
            "prev" => self.store.memory.head().to_string(),
            "type" => kind,
            "payload_artifact" => payload_id,
            "actor" => actor,
            "request_id" => request_id,
            "utc" => self.now().isoformat(),
        };
        let event_bytes = canonical(&event)?;
        let ids = self.store.memory.append_batch(&[NewEvent {
            event: &event_bytes,
            payload: &payload_bytes,
        }])?;
        Ok(ids[0].to_string())
    }

    #[allow(clippy::too_many_arguments)]
    pub fn memory_record(
        &mut self,
        kind: &str,
        scope: &str,
        text: &str,
        actor: &str,
        custody_refs: &[String],
        tags: &[String],
        confidence: Option<f64>,
        request_id: &str,
    ) -> Result<(String, String)> {
        self.memory_ref()?;
        if !KINDS.contains(&kind)
            || scope.is_empty()
            || text.is_empty()
            || text.chars().count() > 65_536
        {
            return value_error("invalid memory kind, scope, or content");
        }
        if confidence.is_some_and(|c| !(0.0..=1.0).contains(&c)) {
            return value_error("invalid memory confidence");
        }
        if matches!(kind, "OBSERVED" | "DERIVED") && custody_refs.is_empty() {
            return value_error("observed/derived memory requires custody references");
        }
        if custody_refs.iter().any(|r| !self.valid_custody_ref(r)) {
            return value_error("unknown or corrupt custody reference");
        }
        if tags.len() > 64 || tags.iter().any(|t| t.is_empty() || t.chars().count() > 160) {
            return value_error("invalid memory tags");
        }
        let sorted = |items: &[String]| -> Vec<String> {
            let set: std::collections::BTreeSet<&String> = items.iter().collect();
            set.into_iter().cloned().collect()
        };
        let intent = crate::obj! {
            "kind" => kind, "scope" => scope, "text" => text, "created_by" => actor,
            "confidence" => confidence.map_or(Value::Null, Value::from),
            "custody_refs" => sorted(custody_refs), "tags" => sorted(tags),
        };
        let intent_hash = raw_id(&canonical(&intent)?).to_string();
        if let Some(prior) = self.store.memory.by_request(request_id)? {
            let event = strict_json(&prior.event)?;
            let payload = strict_json(&prior.payload)?;
            if event["type"] != "MemoryRecorded"
                || payload["intent_hash"].as_str() != Some(intent_hash.as_str())
            {
                return value_error("memory request ID reused");
            }
            return Ok((
                get_str(&payload, "memory_id")?.to_string(),
                prior.event_id.to_string(),
            ));
        }
        let embedder = self.memory_ref()?.embedder.clone();
        let vector = embedder
            .embed_one(Input::document(text))
            .map_err(LedgerError::Value)?;
        let embedding_bytes = pack_vector(&vector);
        let (embedding_id, _) = self.put_bytes(&embedding_bytes)?;
        let mut record = merged(
            &intent,
            crate::obj! {
                "created_at" => self.now().isoformat(),
                "embedding_status" => "READY",
                "embedding_artifact_id" => embedding_id,
                "embedding_model_id" => embedder.model_identity().id.clone(),
                "authority" => "CONTEXTUAL_NOT_CUSTODY",
            },
        );
        let memory_id = raw_id(&canonical(&record)?).to_string();
        record = merged(&record, crate::obj! {"memory_id" => memory_id.clone()});
        let (record_id, _) = self.put_bytes(&canonical(&record)?)?;
        let payload = crate::obj! {"memory_id" => memory_id.clone(), "record_artifact_id" => record_id, "intent_hash" => intent_hash};
        let event = self.memory_emit("MemoryRecorded", &payload, actor, request_id)?;
        let memory = self.memory.as_mut().unwrap();
        memory.index(&memory_id, &record, vector);
        memory.records.insert(memory_id.clone(), record);
        Ok((memory_id, event))
    }

    pub fn memory_get(&self, identity: &str) -> Result<Value> {
        self.memory_ref()?.view(identity)
    }

    pub fn memory_supersede(
        &mut self,
        old_id: &str,
        new_id: &str,
        actor: &str,
        request_id: &str,
    ) -> Result<String> {
        let memory = self.memory_ref()?;
        let old = memory.view(old_id)?;
        let new = memory.view(new_id)?;
        if old_id == new_id || old["scope"] != new["scope"] {
            return value_error("invalid memory supersession");
        }
        let mut seen = HashSet::new();
        let mut pending = vec![new_id.to_string()];
        while let Some(current) = pending.pop() {
            if current == old_id {
                return value_error("memory supersession cycle");
            }
            if seen.insert(current.clone()) {
                pending.extend(memory.superseded.get(&current).cloned().unwrap_or_default());
            }
        }
        let payload = crate::obj! {"old_id" => old_id, "new_id" => new_id};
        let event = self.memory_emit("MemorySuperseded", &payload, actor, request_id)?;
        let targets = self
            .memory
            .as_mut()
            .unwrap()
            .superseded
            .entry(old_id.to_string())
            .or_default();
        if !targets.iter().any(|t| t == new_id) {
            targets.push(new_id.to_string());
        }
        Ok(event)
    }

    pub fn memory_trace(&self, identity: &str) -> Result<Value> {
        let record = self.memory_get(identity)?;
        let references: Vec<Value> = crate::json::string_list(&record, "custody_refs")?
            .into_iter()
            .map(|r| {
                let verified = self.valid_custody_ref(&r);
                crate::obj! {"custody_ref" => r, "verified" => verified}
            })
            .collect();
        Ok(
            crate::obj! {"memory_id" => identity, "authority" => "CONTEXTUAL_NOT_CUSTODY", "references" => references},
        )
    }

    pub fn memory_neighbors(&self, identity: &str) -> Result<Vec<Value>> {
        let memory = self.memory_ref()?;
        let scope = memory.view(identity)?["scope"].clone();
        let neighbors = match &memory.index {
            Some(index) => index.neighbors(identity, self.store.memory.seq())?,
            None => memory.neighbors(identity),
        };
        neighbors
            .into_iter()
            .map(|id| memory.view(&id))
            .filter(|v| v.as_ref().map_or(true, |v| v["scope"] == scope))
            .collect()
    }

    #[allow(clippy::too_many_arguments)]
    pub fn memory_search(
        &mut self,
        query: &str,
        scope: &str,
        actor: &str,
        request_id: &str,
        mode: &str,
        limit: i64,
        grounded_only: bool,
        exclude_kinds: &[String],
        include_superseded: bool,
        seed_memory: Option<&str>,
    ) -> Result<Value> {
        self.memory_ref()?;
        if !matches!(mode, "fts" | "vector" | "graph" | "hybrid") || !(1..=100).contains(&limit) {
            return value_error("invalid memory search mode or limit");
        }
        if query.chars().count() > 4096 || scope.is_empty() {
            return value_error("invalid memory query or scope");
        }
        let intent = crate::obj! {
            "query" => query, "scope" => scope, "actor" => actor, "mode" => mode,
            "limit" => limit, "grounded_only" => grounded_only,
            "exclude_kinds" => exclude_kinds.to_vec(), "include_superseded" => include_superseded,
            "seed_memory" => seed_memory.map_or(Value::Null, Value::from),
        };
        let intent_hash = raw_id(&canonical(&intent)?).to_string();
        if let Some(prior) = self.store.memory.by_request(request_id)? {
            let event = strict_json(&prior.event)?;
            let payload = strict_json(&prior.payload)?;
            if event["type"] != "MemoryRetrieved"
                || payload["intent_hash"].as_str() != Some(intent_hash.as_str())
            {
                return value_error("memory search request ID reused");
            }
            return self.object_json(get_str(&payload, "response_artifact_id")?);
        }
        let memory = self.memory_ref()?;
        let eligible = |identity: &str| -> bool {
            let record = &memory.records[identity];
            record["scope"].as_str() == Some(scope)
                && (!grounded_only
                    || record["custody_refs"]
                        .as_array()
                        .is_some_and(|r| !r.is_empty()))
                && !exclude_kinds
                    .iter()
                    .any(|k| record["kind"].as_str() == Some(k.as_str()))
                && (include_superseded || !memory.superseded.contains_key(identity))
        };
        let maximum = memory.records.len().max(1);
        let limit_usize = limit as usize;
        // Adaptive over-fetch: the ranks that fuse are positions in the fetched pool, which
        // may include ineligible records, exactly as in Python.
        // Python calls `fetch(count)` again with a doubled count; the index is asked again
        // (not sliced) because approximate indexes and the FTS overlay may reorder.
        let filtered_pool =
            |fetch: &dyn Fn(usize) -> Result<Vec<(String, f64)>>| -> Result<Vec<(String, f64)>> {
                let mut count = maximum.min(32.max(limit_usize * 4));
                loop {
                    let rows = fetch(count)?;
                    let enough = rows
                        .iter()
                        .filter(|(id, _)| memory.records.contains_key(id.as_str()) && eligible(id))
                        .count()
                        >= limit_usize;
                    if enough || count == maximum || rows.len() < count {
                        return Ok(rows);
                    }
                    count = maximum.min(count * 2);
                }
            };
        let memory_seq = self.store.memory.seq();
        let mut lists: Vec<(&str, Vec<(String, f64)>)> = Vec::new();
        if !memory.records.is_empty() && matches!(mode, "fts" | "hybrid") {
            let rows = match &memory.index {
                Some(index) => filtered_pool(&|count| index.fts(query, count, memory_seq))?,
                None => {
                    let full = memory.fts(query);
                    filtered_pool(&|count| Ok(full.iter().take(count).cloned().collect()))?
                }
            };
            lists.push(("fts", rows));
        }
        if !memory.records.is_empty() && matches!(mode, "vector" | "hybrid") {
            let query_vector = memory
                .embedder
                .embed_one(Input::query(query))
                .map_err(LedgerError::Value)?;
            let rows = match &memory.index {
                Some(index) => {
                    filtered_pool(&|count| index.vector(&query_vector, count, memory_seq))?
                }
                None => {
                    let full = memory.vector(&query_vector);
                    filtered_pool(&|count| Ok(full.iter().take(count).cloned().collect()))?
                }
            };
            lists.push(("vector", rows));
        }
        if let Some(seed) = seed_memory.filter(|_| matches!(mode, "graph" | "hybrid")) {
            memory.view(seed)?;
            let neighbors = match &memory.index {
                Some(index) => index.neighbors(seed, memory_seq)?,
                None => memory.neighbors(seed),
            };
            lists.push(("graph", neighbors.into_iter().map(|id| (id, 1.0)).collect()));
        }
        let mut scores: IndexMap<String, (f64, kammi_jcs::Map<String, Value>)> = IndexMap::new();
        for (surface, rows) in &lists {
            for (rank, (identity, score)) in rows.iter().enumerate() {
                if memory.records.contains_key(identity.as_str()) && eligible(identity) {
                    let entry = scores
                        .entry(identity.clone())
                        .or_insert((0.0, kammi_jcs::Map::new()));
                    entry.0 += 1.0 / (60.0 + (rank + 1) as f64);
                    entry.1.insert(surface.to_string(), Value::from(*score));
                }
            }
        }
        let mut ids: Vec<String> = scores.keys().cloned().collect();
        ids.sort_by(|a, b| {
            scores[b]
                .0
                .partial_cmp(&scores[a].0)
                .unwrap()
                .then_with(|| a.cmp(b))
        });
        ids.truncate(limit_usize);
        let mut results = Vec::new();
        for id in &ids {
            let (fused, surfaces) = &scores[id];
            let mut reason: Vec<String> = surfaces.keys().cloned().collect();
            reason.sort();
            results.push(crate::obj! {
                "memory" => memory.view(id)?,
                "scores" => crate::obj! {"fused" => *fused, "surfaces" => Value::Object(surfaces.clone())},
                "reason" => reason,
            });
        }
        let result = crate::obj! {"results" => results, "authority" => "CONTEXTUAL_NOT_CUSTODY", "mode" => mode};
        let (response_id, _) = self.put_bytes(&canonical(&result)?)?;
        let payload = crate::obj! {
            "query" => query, "scope" => scope, "mode" => mode, "result_ids" => ids,
            "request_id" => request_id, "intent_hash" => intent_hash, "response_artifact_id" => response_id,
        };
        self.memory_emit("MemoryRetrieved", &payload, actor, request_id)?;
        Ok(result)
    }
}

/// A deterministic embedder for tests and for stores that need memory without a model.
/// Hashes character trigrams into a fixed-size, L2-normalized vector.
pub struct HashingEmbedder {
    identity: ModelIdentity,
    dims: usize,
}

impl HashingEmbedder {
    pub fn new(dims: usize) -> Self {
        let id = format!("kammi-hashing-embedder-v1:{dims}");
        HashingEmbedder {
            identity: ModelIdentity {
                id,
                family: "kammi-hashing".into(),
                dims,
            },
            dims,
        }
    }

    fn embed_text(&self, text: &str) -> Vec<f32> {
        let mut vector = vec![0f32; self.dims];
        let chars: Vec<char> = text.to_lowercase().chars().collect();
        for window in chars.windows(3) {
            let gram: String = window.iter().collect();
            let digest = raw_id(gram.as_bytes());
            let bucket =
                u32::from_le_bytes(digest.as_bytes()[..4].try_into().unwrap()) as usize % self.dims;
            vector[bucket] += 1.0;
        }
        let norm = vector.iter().map(|v| v * v).sum::<f32>().sqrt();
        if norm > 0.0 {
            vector.iter_mut().for_each(|v| *v /= norm);
        }
        vector
    }
}

impl Embedder for HashingEmbedder {
    fn embed(&self, batch: &[Input<'_>]) -> std::result::Result<Embeddings, String> {
        Embeddings::new(
            batch.iter().flat_map(|i| self.embed_text(i.text)).collect(),
            self.dims,
        )
    }
    fn dimension(&self) -> usize {
        self.dims
    }
    fn model_identity(&self) -> &ModelIdentity {
        &self.identity
    }
}

/// Checks an actor-scope rule used by the memory routes: the scope must equal the actor's lab.
pub fn scope_matches(ledger: &Ledger, actor_id: &str, scope: &str) -> bool {
    ledger.state.authority.actor_lab(actor_id) == Some(scope)
}

/// Resolves a stored object identity in either journal (helper for tests).
pub fn object_exists(ledger: &Ledger, id: &str) -> bool {
    Sha256Id::parse(id).is_ok_and(|id| ledger.store.contains_object(&id))
}
