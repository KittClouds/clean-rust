//! Contextual memory projection: Python `MemoryGraph` (`memory_graph.py`) on the same engine.
//!
//! Tables and queries are Python's, with one deliberate difference: memory tags live in their
//! own `MemoryTag` table instead of the shared custody `Entity` table (where Python's tags
//! collide with custody entity ids).
//!
//! Lexical search reproduces Python's state machine exactly: a frozen Ladybug FTS index plus
//! an in-memory postings overlay of records added since the last rebuild, rebuilt only when
//! the overlay reaches the indexed size ("doubling boundaries"). Python holds that state per
//! daemon process and starts it by replaying every record into the overlay; the projector
//! holds it per projector process and starts it the same way from the projected rows.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

use kammi_jcs::{strict_json, Sha256Id, Value as Json};
use kammi_store::{JournalFollower, ObjectReader};
use lbug::{LogicalType, Value};

use super::{field, s, strings, Error, Graph};

/// Tables the memory projection owns (for dumps and parity).
pub const MEMORY_TABLES: &[&str] = &[
    "Memory",
    "CustodyRef",
    "MemoryTag",
    "Cites",
    "About",
    "Supersedes",
    "MemoryMeta",
];

pub fn memory_ddl(dims: usize) -> Vec<String> {
    vec![
        format!("CREATE NODE TABLE IF NOT EXISTS Memory(id STRING PRIMARY KEY, text STRING, scope STRING, kind STRING, embedding FLOAT[{dims}])"),
        "CREATE NODE TABLE IF NOT EXISTS CustodyRef(id STRING PRIMARY KEY)".into(),
        "CREATE NODE TABLE IF NOT EXISTS MemoryTag(id STRING PRIMARY KEY)".into(),
        "CREATE REL TABLE IF NOT EXISTS Cites(FROM Memory TO CustodyRef)".into(),
        "CREATE REL TABLE IF NOT EXISTS About(FROM Memory TO MemoryTag)".into(),
        "CREATE REL TABLE IF NOT EXISTS Supersedes(FROM Memory TO Memory)".into(),
        "CREATE NODE TABLE IF NOT EXISTS MemoryMeta(id STRING PRIMARY KEY, seq INT64, head STRING)".into(),
    ]
}

/// Python `re.findall(r"\w+", text.casefold())` as a set of terms.
pub fn terms(text: &str) -> BTreeSet<String> {
    let mut folded = String::with_capacity(text.len());
    for ch in text.chars() {
        match ch {
            'ß' | 'ẞ' => folded.push_str("ss"),
            'ſ' => folded.push('s'),
            'ς' => folded.push('σ'),
            _ => folded.extend(ch.to_lowercase()),
        }
    }
    let mut out = BTreeSet::new();
    let mut current = String::new();
    for ch in folded.chars() {
        if ch.is_alphanumeric() || ch == '_' {
            current.push(ch);
        } else if !current.is_empty() {
            out.insert(std::mem::take(&mut current));
        }
    }
    if !current.is_empty() {
        out.insert(current);
    }
    out
}

/// Per-process lexical index state (Python `MemoryGraph` attributes).
#[derive(Default)]
pub struct MemoryState {
    pub dims: usize,
    pub fts_exists: bool,
    pub vector_exists: bool,
    pub fts_dirty: bool,
    pub record_ids: HashSet<String>,
    pub delta_ids: HashSet<String>,
    pub delta_terms: HashMap<String, HashSet<String>>,
    pub indexed_count: usize,
    pub fts_rebuilds: u64,
}

impl MemoryState {
    fn add(&mut self, id: &str, text: &str) {
        self.fts_dirty = true;
        self.record_ids.insert(id.to_string());
        self.delta_ids.insert(id.to_string());
        for term in terms(text) {
            self.delta_terms
                .entry(term)
                .or_default()
                .insert(id.to_string());
        }
    }
}

fn float_array(values: &[f32]) -> Value {
    Value::Array(
        LogicalType::Float,
        values.iter().map(|v| Value::Float(*v)).collect(),
    )
}

fn as_f64(value: &Value) -> Result<f64, Error> {
    match value {
        Value::Double(v) => Ok(*v),
        Value::Float(v) => Ok(f64::from(*v)),
        Value::Int64(v) => Ok(*v as f64),
        other => Err(format!("expected a number, got {other:?}").into()),
    }
}

fn as_string(value: &Value) -> Result<String, Error> {
    match value {
        Value::String(v) => Ok(v.clone()),
        other => Err(format!("expected a string, got {other:?}").into()),
    }
}

/// Diagnostic trace to stderr when `KAMMI_PROJECTOR_TRACE=1`.
fn trace(message: std::fmt::Arguments<'_>) {
    if std::env::var_os("KAMMI_PROJECTOR_TRACE").is_some_and(|v| v == "1") {
        eprintln!("[projector-trace] {message}");
    }
}

/// `heapq.nsmallest(count, rows, key=lambda r: (-r[1], r[0]))`.
fn best(mut rows: Vec<(String, f64)>, count: usize) -> Vec<(String, f64)> {
    rows.sort_by(|a, b| {
        b.1.partial_cmp(&a.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.0.cmp(&b.0))
    });
    rows.truncate(count);
    rows
}

impl Graph<'_> {
    /// Creates the memory tables and starts the lexical state exactly as Python's replay
    /// leaves it: every projected record in the overlay, nothing indexed yet this process.
    pub fn init_memory(&self, dims: usize) -> Result<(), Error> {
        for ddl in memory_ddl(dims) {
            self.conn.query(&ddl)?;
        }
        if self
            .conn
            .query("MATCH (m:MemoryMeta {id:'memory'}) RETURN m.seq")?
            .count()
            == 0
        {
            self.conn.query(&format!(
                "CREATE (m:MemoryMeta {{id:'memory', seq:0, head:'{}'}})",
                Sha256Id::ZERO
            ))?;
        }
        let indexes: HashSet<String> = self
            .conn
            .query("CALL SHOW_INDEXES() RETURN *")?
            .filter_map(|row| match row.get(1) {
                Some(Value::String(name)) => Some(name.clone()),
                _ => None,
            })
            .collect();
        let mut state = MemoryState {
            dims,
            fts_exists: indexes.contains("memory_text"),
            vector_exists: indexes.contains("memory_vector"),
            fts_dirty: true,
            ..Default::default()
        };
        let rows: Vec<Vec<Value>> = self
            .conn
            .query("MATCH (m:Memory) RETURN m.id, m.text ORDER BY m.id")?
            .collect();
        for row in rows {
            state.add(&as_string(&row[0])?, &as_string(&row[1])?);
        }
        *self.memory.borrow_mut() = state;
        Ok(())
    }

    pub fn memory_position(&self) -> Result<(u64, Sha256Id), Error> {
        let rows: Vec<Vec<Value>> = self
            .conn
            .query("MATCH (m:MemoryMeta {id:'memory'}) RETURN m.seq, m.head")?
            .collect();
        let [row] = rows.as_slice() else {
            return Err("memory projection metadata missing or duplicated".into());
        };
        match (&row[0], &row[1]) {
            (Value::Int64(seq), Value::String(head)) => Ok((*seq as u64, Sha256Id::parse(head)?)),
            other => Err(format!("memory projection metadata malformed: {other:?}").into()),
        }
    }

    fn apply_memory(
        &self,
        kind: &str,
        payload: &Json,
        objects: &mut ObjectReader,
    ) -> Result<(), Error> {
        match kind {
            "MemoryRecorded" => {
                let record_id = Sha256Id::parse(field(payload, "record_artifact_id")?)?;
                let record = strict_json(
                    &objects
                        .get(&record_id)?
                        .ok_or("memory record object missing")?,
                )?;
                let vector_id = Sha256Id::parse(field(&record, "embedding_artifact_id")?)?;
                let raw = objects
                    .get(&vector_id)?
                    .ok_or("memory embedding object missing")?;
                if raw.len() % 4 != 0 {
                    return Err("memory embedding byte count".into());
                }
                let vector: Vec<f32> = raw
                    .chunks_exact(4)
                    .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
                    .collect();
                let dims = self.memory.borrow().dims;
                let id = field(&record, "memory_id")?;
                let text = field(&record, "text")?;
                if vector.len() == dims {
                    self.run(
                        "MERGE (m:Memory {id:$id}) SET m.text=$text, m.scope=$scope, m.kind=$kind, m.embedding=$embedding",
                        vec![("id", s(id)), ("text", s(text)), ("scope", s(field(&record, "scope")?)), ("kind", s(field(&record, "kind")?)), ("embedding", float_array(&vector))],
                    )?;
                } else {
                    // A record from an embedder of another dimension stays lexical/graph only.
                    self.run(
                        "MERGE (m:Memory {id:$id}) SET m.text=$text, m.scope=$scope, m.kind=$kind",
                        vec![
                            ("id", s(id)),
                            ("text", s(text)),
                            ("scope", s(field(&record, "scope")?)),
                            ("kind", s(field(&record, "kind")?)),
                        ],
                    )?;
                }
                for reference in strings(&record, "custody_refs") {
                    self.run("MATCH (m:Memory {id:$memory}) MERGE (r:CustodyRef {id:$ref}) MERGE (m)-[:Cites]->(r)", vec![("memory", s(id)), ("ref", s(reference))])?;
                }
                for tag in strings(&record, "tags") {
                    self.run("MATCH (m:Memory {id:$memory}) MERGE (t:MemoryTag {id:$tag}) MERGE (m)-[:About]->(t)", vec![("memory", s(id)), ("tag", s(tag))])?;
                }
                self.memory.borrow_mut().add(id, text);
            }
            "MemorySuperseded" => {
                self.run(
                    "MATCH (a:Memory {id:$new}), (b:Memory {id:$old}) MERGE (a)-[:Supersedes]->(b)",
                    vec![
                        ("new", s(field(payload, "new_id")?)),
                        ("old", s(field(payload, "old_id")?)),
                    ],
                )?;
            }
            _ => {}
        }
        Ok(())
    }

    /// Applies up to `batch` memory events, each in its own transaction (with its position),
    /// exactly as Python commits one memory record per transaction. Ladybug updates the FTS
    /// index incrementally per commit, so grouping records changes BM25 scores in the last
    /// bit, which would change search receipts and therefore the memory journal chain.
    pub fn step_memory(
        &self,
        follower: &mut JournalFollower,
        objects: &mut ObjectReader,
        batch: usize,
    ) -> Result<usize, Error> {
        let mut applied = 0;
        while applied < batch {
            let Some(stored) = follower.next_event()? else {
                break;
            };
            self.conn.query("BEGIN TRANSACTION")?;
            let event = strict_json(&stored.event)?;
            let payload = strict_json(&stored.payload)?;
            if let Err(e) = self.apply_memory(field(&event, "type")?, &payload, objects) {
                self.conn.query("ROLLBACK")?;
                return Err(format!("memory projection of seq {} failed: {e}", stored.seq).into());
            }
            self.run(
                "MATCH (m:MemoryMeta {id:'memory'}) SET m.seq = $seq, m.head = $head",
                vec![
                    ("seq", Value::Int64(follower.seq() as i64)),
                    ("head", s(&follower.head().to_string())),
                ],
            )?;
            self.conn.query("COMMIT")?;
            applied += 1;
        }
        Ok(applied)
    }

    /// Python `MemoryGraph.indexes(lexical=...)`.
    fn memory_indexes(&self, lexical: bool) -> Result<(), Error> {
        let mut state = self.memory.borrow_mut();
        if lexical
            && state.fts_dirty
            && (!state.fts_exists || state.delta_ids.len() >= state.indexed_count.max(1))
        {
            if state.fts_exists {
                self.conn
                    .query("CALL DROP_FTS_INDEX('Memory', 'memory_text')")?;
            }
            self.conn.query(
                "CALL CREATE_FTS_INDEX('Memory', 'memory_text', ['text'], stemmer := 'none')",
            )?;
            state.fts_exists = true;
            state.fts_dirty = false;
            state.indexed_count = state.record_ids.len();
            state.delta_ids.clear();
            state.delta_terms.clear();
            state.fts_rebuilds += 1;
            trace(format_args!(
                "fts rebuild #{} indexed={}",
                state.fts_rebuilds, state.indexed_count
            ));
        }
        if !state.vector_exists {
            self.conn.query("CALL CREATE_VECTOR_INDEX('Memory', 'memory_vector', 'embedding', metric := 'cosine')")?;
            state.vector_exists = true;
        }
        Ok(())
    }

    /// Python `MemoryGraph.fts`: native BM25 top-`count`, merged with the recent overlay.
    pub fn memory_fts(&self, query: &str, count: usize) -> Result<Vec<(String, f64)>, Error> {
        self.memory_indexes(true)?;
        let mut statement = self.conn.prepare("CALL QUERY_FTS_INDEX('Memory', 'memory_text', $query, TOP := $count) RETURN node.id, score ORDER BY score DESC, node.id")?;
        let mut merged: BTreeMap<String, f64> = BTreeMap::new();
        for row in self.conn.execute(
            &mut statement,
            vec![("query", s(query)), ("count", Value::Int64(count as i64))],
        )? {
            merged.insert(as_string(&row[0])?, as_f64(&row[1])?);
        }
        let state = self.memory.borrow();
        trace(format_args!(
            "fts base count={count} records={} delta={} rows={:?}",
            state.record_ids.len(),
            state.delta_ids.len(),
            merged
                .iter()
                .map(|(k, v)| (&k[7..15], *v))
                .collect::<Vec<_>>()
        ));
        let mut overlap: HashMap<&str, u64> = HashMap::new();
        for term in terms(query) {
            for id in state.delta_terms.get(&term).into_iter().flatten() {
                *overlap.entry(id.as_str()).or_default() += 1;
            }
        }
        let recent = best(
            overlap
                .into_iter()
                .map(|(id, n)| (id.to_string(), n as f64))
                .collect(),
            count,
        );
        for (id, score) in recent {
            let entry = merged.entry(id).or_insert(0.0);
            *entry = entry.max(score);
        }
        Ok(best(merged.into_iter().collect(), count))
    }

    /// Python `MemoryGraph.vector`: (id, 1 - cosine distance).
    pub fn memory_vector(&self, vector: &[f32], count: usize) -> Result<Vec<(String, f64)>, Error> {
        if vector.len() != self.memory.borrow().dims {
            return Err(format!(
                "query vector has {} dimensions, projection holds {}",
                vector.len(),
                self.memory.borrow().dims
            )
            .into());
        }
        self.memory_indexes(false)?;
        let mut statement = self.conn.prepare("CALL QUERY_VECTOR_INDEX('Memory', 'memory_vector', $vector, $count) RETURN node.id, distance ORDER BY distance, node.id")?;
        let mut out = Vec::new();
        for row in self.conn.execute(
            &mut statement,
            vec![
                ("vector", float_array(vector)),
                ("count", Value::Int64(count as i64)),
            ],
        )? {
            out.push((as_string(&row[0])?, 1.0 - as_f64(&row[1])?));
        }
        Ok(out)
    }

    /// Python `MemoryGraph.neighbors`: shared tag or shared custody reference, sorted.
    pub fn memory_neighbors(&self, id: &str) -> Result<Vec<String>, Error> {
        let mut ids = BTreeSet::new();
        for query in [
            "MATCH (a:Memory {id:$id})-[:About]->(t:MemoryTag)<-[:About]-(b:Memory) WHERE b.id<>$id RETURN DISTINCT b.id",
            "MATCH (a:Memory {id:$id})-[:Cites]->(t:CustodyRef)<-[:Cites]-(b:Memory) WHERE b.id<>$id RETURN DISTINCT b.id",
        ] {
            let mut statement = self.conn.prepare(query)?;
            for row in self.conn.execute(&mut statement, vec![("id", s(id))])? {
                ids.insert(as_string(&row[0])?);
            }
        }
        Ok(ids.into_iter().collect())
    }

    pub fn memory_counts(&self) -> Result<Json, Error> {
        let mut out = kammi_jcs::Map::new();
        for (name, query) in [
            ("memories", "MATCH (m:Memory) RETURN count(m)"),
            (
                "supersessions",
                "MATCH ()-[r:Supersedes]->() RETURN count(r)",
            ),
        ] {
            let rows: Vec<Vec<Value>> = self.conn.query(query)?.collect();
            if let Some(Value::Int64(n)) = rows.first().and_then(|r| r.first()) {
                out.insert(name.into(), Json::from(*n));
            }
        }
        let state = self.memory.borrow();
        out.insert("fts_rebuilds".into(), Json::from(state.fts_rebuilds));
        out.insert(
            "fts_pending_records".into(),
            Json::from(state.delta_ids.len()),
        );
        out.insert("dims".into(), Json::from(state.dims));
        Ok(Json::Object(out))
    }
}
