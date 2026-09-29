//! `kammi-projector`: the disposable Ladybug projection of a v2 store.
//!
//! ```text
//! kammi-projector project --store <v2 store> --db <custody.lbdb> [--follow] [--batch 256] [--verify]
//! kammi-projector verify  --store <v2 store> --db <custody.lbdb>
//! kammi-projector counts  --db <custody.lbdb>
//! kammi-projector history --db <custody.lbdb> --run <run id>
//! ```
//!
//! Same tables and rows as the Python `CustodyGraph` (`graph.py`, `entities.py`,
//! `vault_projection.py`). It reads the store with a lock-free [`JournalFollower`] and never
//! touches authority. Its position lives inside the graph (`LedgerMeta`), updated in the same
//! transaction as the rows it covers, so a crash leaves the previous or the next position,
//! never a mix. A database that fails to open (for example a WAL that will not replay) is
//! moved to `quarantine/` and rebuilt from genesis.

mod bulk;
mod memory;
mod serve;

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use kammi_jcs::{strict_json, Sha256Id, Value as Json};
use kammi_store::{JournalFollower, ObjectReader};
use lbug::{Connection, Database, SystemConfig, Value};

type Error = Box<dyn std::error::Error + Send + Sync>;

const DDL: &[&str] = &[
    "CREATE NODE TABLE IF NOT EXISTS LedgerMeta(id STRING PRIMARY KEY, seq INT64, head STRING)",
    "CREATE NODE TABLE IF NOT EXISTS Artifact(id STRING PRIMARY KEY, byte_count INT64)",
    "CREATE NODE TABLE IF NOT EXISTS Event(id STRING PRIMARY KEY, seq INT64, typ STRING, payload STRING, prev STRING)",
    "CREATE NODE TABLE IF NOT EXISTS Seal(root STRING PRIMARY KEY, payload STRING)",
    "CREATE NODE TABLE IF NOT EXISTS Run(id STRING PRIMARY KEY, lab STRING)",
    "CREATE NODE TABLE IF NOT EXISTS CustodyFact(id STRING PRIMARY KEY, run_id STRING, kind STRING, subject STRING, target STRING, value STRING, evidence_id STRING, scope STRING)",
    "CREATE REL TABLE IF NOT EXISTS SealMember(FROM Seal TO Artifact)",
    "CREATE REL TABLE IF NOT EXISTS SealParent(FROM Seal TO Seal)",
    "CREATE REL TABLE IF NOT EXISTS HasEvent(FROM Run TO Event)",
    "CREATE REL TABLE IF NOT EXISTS HasFact(FROM Run TO CustodyFact)",
    "CREATE REL TABLE IF NOT EXISTS FactEvidence(FROM CustodyFact TO Artifact)",
    "CREATE NODE TABLE IF NOT EXISTS Entity(id STRING PRIMARY KEY, kind STRING, payload STRING)",
    "CREATE REL TABLE IF NOT EXISTS Link(FROM Entity TO Entity, kind STRING)",
    "CREATE NODE TABLE IF NOT EXISTS PhoenixVault(id STRING PRIMARY KEY, owner STRING, source_epoch INT64, generation_id INT64, generation_epoch INT64, manifest STRING, reader_source STRING, reader_revision INT64, reader_offset INT64)",
    "CREATE NODE TABLE IF NOT EXISTS PhoenixSource(id STRING PRIMARY KEY, vault_id STRING, source_id STRING, revision INT64, artifact STRING, byte_count INT64, epoch INT64)",
    "CREATE NODE TABLE IF NOT EXISTS PhoenixGeneration(id STRING PRIMARY KEY, vault_id STRING, generation_id INT64, source_epoch INT64, manifest STRING)",
    "CREATE NODE TABLE IF NOT EXISTS PhoenixProductPrimary(id STRING PRIMARY KEY, vault_id STRING, source_epoch INT64, receipt STRING)",
    "CREATE REL TABLE IF NOT EXISTS PhoenixHasSource(FROM PhoenixVault TO PhoenixSource)",
    "CREATE REL TABLE IF NOT EXISTS PhoenixHasGeneration(FROM PhoenixVault TO PhoenixGeneration)",
    "CREATE REL TABLE IF NOT EXISTS PhoenixHasProductPrimary(FROM PhoenixVault TO PhoenixProductPrimary)",
];

/// `entities.py`: payload fields that become typed entity nodes.
const ENTITY_FIELDS: &[(&str, &str)] = &[
    ("run_id", "Run"),
    ("stage_id", "Stage"),
    ("actor_id", "Actor"),
    ("lab", "Lab"),
    ("attempt_id", "Attempt"),
    ("resource_id", "Resource"),
    ("lease_id", "Lease"),
    ("panel_id", "Panel"),
    ("adapter_id", "Adapter"),
    ("authorization_id", "Authorization"),
    ("worker_actor_id", "Agent"),
    ("host", "Host"),
    ("bundle_artifact_id", "RemoteBundle"),
];
const ARTIFACT_FIELDS: &[&str] = &[
    "artifact_id",
    "evidence_artifact",
    "source_artifact_id",
    "derived_view_id",
    "receipt_artifact_id",
    "implementation_artifact",
];
const RUN_RELATIONS: &[(&str, &str)] = &[
    ("stage_id", "HAS_STAGE"),
    ("attempt_id", "HAS_ATTEMPT"),
    ("lab", "BELONGS_TO"),
    ("actor_id", "EXECUTED_BY"),
    ("resource_id", "USES_RESOURCE"),
    ("host", "RUNS_ON"),
];

fn s(value: &str) -> Value {
    Value::String(value.to_string())
}

fn field<'a>(payload: &'a Json, key: &str) -> Result<&'a str, Error> {
    payload[key]
        .as_str()
        .ok_or_else(|| format!("projection: payload field {key} missing").into())
}

fn int(payload: &Json, key: &str) -> Result<Value, Error> {
    payload[key]
        .as_i64()
        .map(Value::Int64)
        .ok_or_else(|| format!("projection: integer field {key} missing").into())
}

fn strings<'a>(payload: &'a Json, key: &str) -> Vec<&'a str> {
    payload[key]
        .as_array()
        .map(|a| a.iter().filter_map(Json::as_str).collect())
        .unwrap_or_default()
}

struct Graph<'db> {
    conn: Connection<'db>,
    /// Compiled once per statement text; the projection reuses a small fixed set.
    statements:
        std::cell::RefCell<std::collections::HashMap<&'static str, lbug::PreparedStatement>>,
    /// Python `MemoryGraph` per-process lexical state.
    memory: std::cell::RefCell<memory::MemoryState>,
    /// When set, `node`/`edge` record into it instead of executing (batched runs).
    recorder: std::cell::RefCell<Option<Recorded>>,
    /// Existing `Link` rows as 16-byte hashes of (from, to, kind). Ladybug checks relationship
    /// existence for `MERGE` by scanning, which grows with the table (quadratic ingest); the
    /// projector is the only writer, so it knows which links exist and creates only new ones.
    links: std::cell::RefCell<std::collections::HashSet<[u8; 16]>>,
    /// Links created in the open transaction; merged into `links` on commit, dropped on rollback.
    pending_links: std::cell::RefCell<std::collections::HashSet<[u8; 16]>>,
    /// Existing `Entity` and `Artifact` primary keys (16-byte hashes), same discipline: Ladybug
    /// resolves keys inside UNWIND by joining the whole table, so new rows are COPYed instead.
    entities: std::cell::RefCell<std::collections::HashSet<[u8; 16]>>,
    pending_entities: std::cell::RefCell<std::collections::HashSet<[u8; 16]>>,
    artifacts: std::cell::RefCell<std::collections::HashSet<[u8; 16]>>,
    pending_artifacts: std::cell::RefCell<std::collections::HashSet<[u8; 16]>>,
}

fn key_of(id: &str) -> [u8; 16] {
    kammi_jcs::raw_id(id.as_bytes()).0[..16].try_into().unwrap()
}

fn link_key(a: &str, b: &str, kind: &str) -> [u8; 16] {
    let digest = kammi_jcs::raw_id(format!("{a}\0{b}\0{kind}").as_bytes());
    digest.0[..16].try_into().unwrap()
}

/// Entity nodes (id, kind, payload) and links (from, to, kind) recorded in call order.
type Recorded = (Vec<(String, String, String)>, Vec<(String, String, String)>);

/// Events whose custody effects are only `Event` CREATE, optional `Artifact` MERGE, and
/// entities/links: they can be applied in batches with identical results. The others carry
/// MATCH-gated edges whose outcome depends on exact interleaving, so they stay per event.
fn batchable(kind: &str) -> bool {
    !matches!(kind, "RunCreated" | "SealCreated" | "FactRecorded") && !kind.starts_with("Vault")
}

fn struct_list(fields: &[(&str, lbug::LogicalType)], rows: Vec<Vec<Value>>) -> Value {
    let child = lbug::LogicalType::Struct {
        fields: fields
            .iter()
            .map(|(n, t)| (n.to_string(), t.clone()))
            .collect(),
    };
    Value::List(
        child,
        rows.into_iter()
            .map(|row| Value::Struct(fields.iter().map(|(n, _)| n.to_string()).zip(row).collect()))
            .collect(),
    )
}

/// Every table the projection declares (dumps ignore engine-internal index tables).
fn known_tables() -> Vec<&'static str> {
    let mut names: Vec<&'static str> = DDL
        .iter()
        .map(|ddl| {
            let rest = ddl.split("EXISTS ").nth(1).unwrap_or("");
            &rest[..rest.find('(').unwrap_or(rest.len())]
        })
        .collect();
    names.extend_from_slice(memory::MEMORY_TABLES);
    names
}

/// The qualified FTS and vector extensions (`KAMMI_EXTENSION_DIR`, else the pinned runtime).
fn extension_dir() -> PathBuf {
    std::env::var_os("KAMMI_EXTENSION_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../../kammi-ledger/vendor/runtime-v1/extensions")
        })
}

impl<'db> Graph<'db> {
    fn new(db: &'db Database, memory_dims: usize) -> Result<Self, Error> {
        let conn = Connection::new(db)?;
        for extension in ["fts", "vector"] {
            let path = extension_dir()
                .join(extension)
                .join(format!("lib{extension}.lbug_extension"));
            let path =
                std::fs::canonicalize(&path).map_err(|e| format!("{}: {e}", path.display()))?;
            let text = path
                .to_string_lossy()
                .trim_start_matches(r"\\?\")
                .replace('\\', "/");
            conn.query(&format!("LOAD EXTENSION '{}'", text.replace('\'', "\\'")))?;
        }
        for ddl in DDL {
            conn.query(ddl)?;
        }
        if conn
            .query("MATCH (m:LedgerMeta {id:'primary'}) RETURN m.seq")?
            .count()
            == 0
        {
            conn.query(&format!(
                "CREATE (m:LedgerMeta {{id:'primary', seq:0, head:'{}'}})",
                Sha256Id::ZERO
            ))?;
        }
        let graph = Graph {
            conn,
            statements: Default::default(),
            memory: Default::default(),
            recorder: Default::default(),
            links: Default::default(),
            pending_links: Default::default(),
            entities: Default::default(),
            pending_entities: Default::default(),
            artifacts: Default::default(),
            pending_artifacts: Default::default(),
        };
        graph.load_keys()?;
        graph.init_memory(memory_dims)?;
        Ok(graph)
    }

    fn run(&self, query: &'static str, params: Vec<(&str, Value)>) -> Result<(), Error> {
        let mut statements = self.statements.borrow_mut();
        let statement = match statements.entry(query) {
            std::collections::hash_map::Entry::Occupied(e) => e.into_mut(),
            std::collections::hash_map::Entry::Vacant(e) => e.insert(self.conn.prepare(query)?),
        };
        if std::env::var_os("KAMMI_PROJECTOR_TRACE").is_some_and(|v| v == "2") {
            eprintln!("[projector-trace] run {}", &query[..query.len().min(90)]);
        }
        let started = Instant::now();
        self.conn.execute(statement, params)?;
        if std::env::var_os("KAMMI_PROJECTOR_TRACE").is_some_and(|v| v == "1")
            && started.elapsed() > Duration::from_millis(50)
        {
            eprintln!(
                "[projector-trace] {:>8.1} ms  {}",
                started.elapsed().as_secs_f64() * 1e3,
                &query[..query.len().min(70)]
            );
        }
        Ok(())
    }

    fn position(&self) -> Result<(u64, Sha256Id), Error> {
        let rows: Vec<Vec<Value>> = self
            .conn
            .query("MATCH (m:LedgerMeta {id:'primary'}) RETURN m.seq, m.head")?
            .collect();
        let [row] = rows.as_slice() else {
            return Err("custody graph metadata missing or duplicated".into());
        };
        match (&row[0], &row[1]) {
            (Value::Int64(seq), Value::String(head)) => Ok((*seq as u64, Sha256Id::parse(head)?)),
            other => Err(format!("custody graph metadata malformed: {other:?}").into()),
        }
    }

    fn apply(&self, event: &Json, event_id: &str, payload: &Json) -> Result<(), Error> {
        let kind = field(event, "type")?;
        self.run(
            "CREATE (e:Event {id:$id, seq:$seq, typ:$typ, payload:$payload, prev:$prev})",
            vec![
                ("id", s(event_id)),
                ("seq", int(event, "seq")?),
                ("typ", s(kind)),
                ("payload", s(field(event, "payload_artifact")?)),
                ("prev", s(field(event, "prev")?)),
            ],
        )?;
        kammi_store::fault::hit("projection.mid_transaction");
        match kind {
            "ArtifactRegistered" => {
                let id = field(payload, "artifact_id")?;
                let key = key_of(id);
                let query = if self.artifacts.borrow().contains(&key)
                    || !self.pending_artifacts.borrow_mut().insert(key)
                {
                    "MATCH (a:Artifact {id:$id}) SET a.byte_count = $bytes"
                } else {
                    "CREATE (a:Artifact {id:$id, byte_count:$bytes})"
                };
                self.run(
                    query,
                    vec![("id", s(id)), ("bytes", int(payload, "byte_count")?)],
                )?
            }
            "RunCreated" => self.run(
                "CREATE (r:Run {id:$id, lab:$lab})",
                vec![
                    ("id", s(field(payload, "run_id")?)),
                    ("lab", s(field(payload, "lab")?)),
                ],
            )?,
            "SealCreated" => {
                let root = field(payload, "root")?;
                self.run(
                    "CREATE (s:Seal {root:$root, payload:$payload})",
                    vec![
                        ("root", s(root)),
                        ("payload", s(field(payload, "seal_artifact")?)),
                    ],
                )?;
                for member in strings(payload, "direct_members") {
                    self.run("MATCH (s:Seal {root:$root}), (a:Artifact {id:$id}) CREATE (s)-[:SealMember]->(a)", vec![("root", s(root)), ("id", s(member))])?;
                }
                for parent in strings(payload, "parents") {
                    self.run("MATCH (s:Seal {root:$root}), (p:Seal {root:$parent}) CREATE (s)-[:SealParent]->(p)", vec![("root", s(root)), ("parent", s(parent))])?;
                }
            }
            "FactRecorded" => {
                let (fact, run, evidence) = (
                    field(payload, "fact_id")?,
                    field(payload, "run_id")?,
                    field(payload, "evidence_artifact")?,
                );
                self.run(
                    "CREATE (f:CustodyFact {id:$id, run_id:$run, kind:$kind, subject:$subject, target:$target, value:$value, evidence_id:$evidence, scope:$scope})",
                    vec![
                        ("id", s(fact)),
                        ("run", s(run)),
                        ("kind", s(field(payload, "kind")?)),
                        ("subject", s(field(payload, "subject")?)),
                        ("target", s(field(payload, "object")?)),
                        ("value", s(field(payload, "value")?)),
                        ("evidence", s(evidence)),
                        ("scope", s(field(payload, "scope")?)),
                    ],
                )?;
                self.run(
                    "MATCH (r:Run {id:$run}), (f:CustodyFact {id:$id}) CREATE (r)-[:HasFact]->(f)",
                    vec![("run", s(run)), ("id", s(fact))],
                )?;
                self.run("MATCH (f:CustodyFact {id:$id}), (a:Artifact {id:$artifact}) CREATE (f)-[:FactEvidence]->(a)", vec![("id", s(fact)), ("artifact", s(evidence))])?;
            }
            _ => {}
        }
        self.entities(event, event_id, payload)?;
        self.vault(kind, payload)?;
        Ok(())
    }

    fn node(&self, id: &str, kind: &str, data: &str) -> Result<(), Error> {
        if let Some(recorded) = self.recorder.borrow_mut().as_mut() {
            recorded
                .0
                .push((id.to_string(), kind.to_string(), data.to_string()));
            return Ok(());
        }
        // MERGE ... SET semantics: update an existing node, create a new one.
        let key = key_of(id);
        if self.entities.borrow().contains(&key) || self.pending_entities.borrow().contains(&key) {
            self.run(
                "MATCH (n:Entity {id:$id}) SET n.kind=$kind, n.payload=$payload",
                vec![("id", s(id)), ("kind", s(kind)), ("payload", s(data))],
            )
        } else {
            self.pending_entities.borrow_mut().insert(key);
            self.run(
                "CREATE (n:Entity {id:$id, kind:$kind, payload:$payload})",
                vec![("id", s(id)), ("kind", s(kind)), ("payload", s(data))],
            )
        }
    }

    fn edge(&self, a: &str, b: &str, kind: &str) -> Result<(), Error> {
        if let Some(recorded) = self.recorder.borrow_mut().as_mut() {
            recorded
                .1
                .push((a.to_string(), b.to_string(), kind.to_string()));
            return Ok(());
        }
        // MERGE semantics without Ladybug's relationship scan: existing links are a no-op.
        let key = link_key(a, b, kind);
        if self.links.borrow().contains(&key) || !self.pending_links.borrow_mut().insert(key) {
            return Ok(());
        }
        self.run(
            "MATCH (a:Entity {id:$a}), (b:Entity {id:$b}) CREATE (a)-[r:Link {kind:$kind}]->(b)",
            vec![("a", s(a)), ("b", s(b)), ("kind", s(kind))],
        )
    }

    /// Loads the existing entity, artifact and link keys (startup, or after a bulk load).
    fn load_keys(&self) -> Result<(), Error> {
        let mut links = std::collections::HashSet::new();
        for row in self
            .conn
            .query("MATCH (a:Entity)-[l:Link]->(b:Entity) RETURN a.id, b.id, l.kind")?
        {
            if let (Value::String(a), Value::String(b), Value::String(k)) =
                (&row[0], &row[1], &row[2])
            {
                links.insert(link_key(a, b, k));
            }
        }
        *self.links.borrow_mut() = links;
        self.pending_links.borrow_mut().clear();
        for (query, set) in [
            ("MATCH (n:Entity) RETURN n.id", &self.entities),
            ("MATCH (a:Artifact) RETURN a.id", &self.artifacts),
        ] {
            let mut keys = std::collections::HashSet::new();
            for row in self.conn.query(query)? {
                if let Value::String(id) = &row[0] {
                    keys.insert(key_of(id));
                }
            }
            *set.borrow_mut() = keys;
        }
        self.pending_entities.borrow_mut().clear();
        self.pending_artifacts.borrow_mut().clear();
        Ok(())
    }

    fn commit(&self) -> Result<(), Error> {
        let started = Instant::now();
        self.conn.query("COMMIT")?;
        if std::env::var_os("KAMMI_PROJECTOR_TRACE").is_some() {
            eprintln!(
                "[projector-trace] {:>8.1} ms  COMMIT",
                started.elapsed().as_secs_f64() * 1e3
            );
        }
        for (pending, set) in [
            (&self.pending_links, &self.links),
            (&self.pending_entities, &self.entities),
            (&self.pending_artifacts, &self.artifacts),
        ] {
            let drained: Vec<[u8; 16]> = pending.borrow_mut().drain().collect();
            set.borrow_mut().extend(drained);
        }
        Ok(())
    }

    fn rollback(&self) -> Result<(), Error> {
        self.pending_links.borrow_mut().clear();
        self.pending_entities.borrow_mut().clear();
        self.pending_artifacts.borrow_mut().clear();
        self.conn.query("ROLLBACK")?;
        Ok(())
    }

    fn entities(&self, event: &Json, event_id: &str, payload: &Json) -> Result<(), Error> {
        let data = field(event, "payload_artifact")?;
        self.node(event_id, "Event", data)?;
        let mut ids = std::collections::HashMap::new();
        for (key, kind) in ENTITY_FIELDS {
            if let Some(value) = payload.get(*key).and_then(Json::as_str) {
                let id = format!("{kind}:{value}");
                self.node(&id, kind, data)?;
                self.edge(event_id, &id, "CITES")?;
                ids.insert(*key, id);
            }
        }
        for key in ARTIFACT_FIELDS {
            if let Some(value) = payload.get(*key).and_then(Json::as_str) {
                let id = format!("Artifact:{value}");
                self.node(&id, "Artifact", data)?;
                self.edge(event_id, &id, "CITES")?;
            }
        }
        if let Some(run) = ids.get("run_id") {
            self.edge(run, event_id, "HAS_EVENT")?;
            for (key, relation) in RUN_RELATIONS {
                if let Some(id) = ids.get(key) {
                    self.edge(run, id, relation)?;
                }
            }
        }
        if field(event, "type")? == "SealCreated" {
            let seal = format!("Seal:{}", field(payload, "root")?);
            self.node(&seal, "Seal", data)?;
            for member in strings(payload, "direct_members") {
                let artifact = format!("Artifact:{member}");
                self.node(&artifact, "Artifact", data)?;
                self.edge(&artifact, &seal, "SEALED_BY")?;
            }
            for parent in strings(payload, "parents") {
                let parent = format!("Seal:{parent}");
                self.node(&parent, "Seal", data)?;
                self.edge(&seal, &parent, "PARENT_SEAL")?;
            }
        }
        Ok(())
    }

    fn vault(&self, kind: &str, p: &Json) -> Result<(), Error> {
        match kind {
            "VaultCreated" => self.run(
                "CREATE (v:PhoenixVault {id:$id, owner:$owner, source_epoch:0, generation_id:0, generation_epoch:0, manifest:'', reader_source:'', reader_revision:0, reader_offset:0})",
                vec![("id", s(field(p, "vault_id")?)), ("owner", s(field(p, "owner_actor")?))],
            ),
            "VaultSourceCommitted" => {
                let vault = field(p, "vault_id")?;
                let key = format!("{vault}:{}", field(p, "source_id")?);
                self.run(
                    "MERGE (s:PhoenixSource {id:$id}) SET s.vault_id=$vault, s.source_id=$source, s.revision=$revision, s.artifact=$artifact, s.byte_count=$bytes, s.epoch=$epoch",
                    vec![
                        ("id", s(&key)),
                        ("vault", s(vault)),
                        ("source", s(field(p, "source_id")?)),
                        ("revision", int(p, "revision")?),
                        ("artifact", s(field(p, "artifact_id")?)),
                        ("bytes", int(p, "byte_count")?),
                        ("epoch", int(p, "epoch")?),
                    ],
                )?;
                self.run("MATCH (v:PhoenixVault {id:$id}) SET v.source_epoch=$epoch", vec![("id", s(vault)), ("epoch", int(p, "epoch")?)])?;
                self.run("MATCH (v:PhoenixVault {id:$vault}), (s:PhoenixSource {id:$source}) MERGE (v)-[:PhoenixHasSource]->(s)", vec![("vault", s(vault)), ("source", s(&key))])
            }
            "VaultGenerationSelected" => {
                let vault = field(p, "vault_id")?;
                let key = format!("{vault}:{}", p["generation_id"]);
                self.run(
                    "CREATE (g:PhoenixGeneration {id:$id, vault_id:$vault, generation_id:$generation, source_epoch:$epoch, manifest:$manifest})",
                    vec![("id", s(&key)), ("vault", s(vault)), ("generation", int(p, "generation_id")?), ("epoch", int(p, "source_epoch")?), ("manifest", s(field(p, "manifest_artifact_id")?))],
                )?;
                self.run(
                    "MATCH (v:PhoenixVault {id:$id}) SET v.generation_id=$generation, v.generation_epoch=$epoch, v.manifest=$manifest",
                    vec![("id", s(vault)), ("generation", int(p, "generation_id")?), ("epoch", int(p, "source_epoch")?), ("manifest", s(field(p, "manifest_artifact_id")?))],
                )?;
                self.run("MATCH (v:PhoenixVault {id:$vault}), (g:PhoenixGeneration {id:$generation}) MERGE (v)-[:PhoenixHasGeneration]->(g)", vec![("vault", s(vault)), ("generation", s(&key))])
            }
            "VaultReaderPositionSet" => self.run(
                "MATCH (v:PhoenixVault {id:$id}) SET v.reader_source=$source, v.reader_revision=$revision, v.reader_offset=$offset",
                vec![("id", s(field(p, "vault_id")?)), ("source", s(field(p, "source_id")?)), ("revision", int(p, "revision")?), ("offset", int(p, "offset")?)],
            ),
            "VaultProductPrimarySelected" => {
                let vault = field(p, "vault_id")?;
                self.run(
                    "CREATE (p:PhoenixProductPrimary {id:$id, vault_id:$id, source_epoch:$epoch, receipt:$receipt})",
                    vec![("id", s(vault)), ("epoch", int(p, "source_epoch")?), ("receipt", s(field(p, "receipt_artifact_id")?))],
                )?;
                self.run("MATCH (v:PhoenixVault {id:$id}), (p:PhoenixProductPrimary {id:$id}) MERGE (v)-[:PhoenixHasProductPrimary]->(p)", vec![("id", s(vault))])
            }
            _ => Ok(()),
        }
    }

    /// Applies a run of consecutive batchable events with the per-event semantics: events
    /// appended, artifacts and entities last-writer-wins, links de-duplicated. New rows are
    /// COPYed from per-batch CSV files (Ladybug resolves keys inside UNWIND by joining the
    /// whole table, which grows quadratically); updates to existing rows go one statement per
    /// key, which uses the primary-key index.
    fn apply_run(&self, run: &[(Json, String, Json)]) -> Result<(), Error> {
        use lbug::LogicalType::{Int64, String as Str};
        let mut artifacts: std::collections::HashMap<String, (usize, i64)> = Default::default();
        *self.recorder.borrow_mut() = Some((Vec::new(), Vec::new()));
        let recorded = (|| -> Result<(), Error> {
            for (index, (event, id, payload)) in run.iter().enumerate() {
                kammi_store::fault::hit("projection.mid_transaction");
                if field(event, "type")? == "ArtifactRegistered" {
                    let bytes = payload["byte_count"]
                        .as_i64()
                        .ok_or("projection: byte_count missing")?;
                    artifacts.insert(field(payload, "artifact_id")?.to_string(), (index, bytes));
                }
                self.entities(event, id, payload)?;
            }
            Ok(())
        })();
        let (nodes, edges) = self.recorder.borrow_mut().take().unwrap_or_default();
        recorded?;

        // Last writer per entity id, in first-seen order of the final write.
        let mut last: std::collections::HashMap<&str, usize> = Default::default();
        for (i, (id, _, _)) in nodes.iter().enumerate() {
            last.insert(id, i);
        }
        let mut order: Vec<usize> = last.into_values().collect();
        order.sort_unstable();
        let (mut new_entities, mut entity_updates) = (Vec::new(), Vec::new());
        {
            let existing = self.entities.borrow();
            let mut pending = self.pending_entities.borrow_mut();
            for i in order {
                let key = key_of(&nodes[i].0);
                if existing.contains(&key) || pending.contains(&key) {
                    entity_updates.push(i);
                } else {
                    pending.insert(key);
                    new_entities.push(i);
                }
            }
        }
        let mut artifact_order: Vec<(&String, &(usize, i64))> = artifacts.iter().collect();
        artifact_order.sort_by_key(|(_, (i, _))| *i);
        let (mut new_artifacts, mut artifact_updates) = (Vec::new(), Vec::new());
        {
            let existing = self.artifacts.borrow();
            let mut pending = self.pending_artifacts.borrow_mut();
            for (id, (_, bytes)) in artifact_order {
                let key = key_of(id);
                if existing.contains(&key) || pending.contains(&key) {
                    artifact_updates.push((id.as_str(), *bytes));
                } else {
                    pending.insert(key);
                    new_artifacts.push((id.as_str(), *bytes));
                }
            }
        }
        let new_links: Vec<&(String, String, String)> = {
            let links = self.links.borrow();
            let mut pending = self.pending_links.borrow_mut();
            edges
                .iter()
                .filter(|(a, b, k)| {
                    let key = link_key(a, b, k);
                    !links.contains(&key) && pending.insert(key)
                })
                .collect()
        };

        // New rows through UNWIND ... CREATE (no key lookup, so no table join). COPY is not
        // used here: mixing COPY with statement writes in one Ladybug 0.20.2 transaction
        // corrupts the transaction's local state and the next statement crashes the engine.
        let mut event_rows = Vec::with_capacity(run.len());
        for (event, id, _) in run {
            event_rows.push(vec![
                s(id),
                int(event, "seq")?,
                s(field(event, "type")?),
                s(field(event, "payload_artifact")?),
                s(field(event, "prev")?),
            ]);
        }
        self.run(
            "UNWIND $rows AS r CREATE (e:Event {id:r.id, seq:r.seq, typ:r.typ, payload:r.payload, prev:r.prev})",
            vec![("rows", struct_list(&[("id", Str), ("seq", Int64), ("typ", Str), ("payload", Str), ("prev", Str)], event_rows))],
        )?;
        if !new_artifacts.is_empty() {
            self.run(
                "UNWIND $rows AS r CREATE (a:Artifact {id:r.id, byte_count:r.bytes})",
                vec![(
                    "rows",
                    struct_list(
                        &[("id", Str), ("bytes", Int64)],
                        new_artifacts
                            .iter()
                            .map(|(id, bytes)| vec![s(id), Value::Int64(*bytes)])
                            .collect(),
                    ),
                )],
            )?;
        }
        for (id, bytes) in artifact_updates {
            self.run(
                "MATCH (a:Artifact {id:$id}) SET a.byte_count = $bytes",
                vec![("id", s(id)), ("bytes", Value::Int64(bytes))],
            )?;
        }
        if !new_entities.is_empty() {
            self.run(
                "UNWIND $rows AS r CREATE (n:Entity {id:r.id, kind:r.kind, payload:r.payload})",
                vec![(
                    "rows",
                    struct_list(
                        &[("id", Str), ("kind", Str), ("payload", Str)],
                        new_entities
                            .iter()
                            .map(|&i| vec![s(&nodes[i].0), s(&nodes[i].1), s(&nodes[i].2)])
                            .collect(),
                    ),
                )],
            )?;
        }
        for i in entity_updates {
            let (id, kind, data) = &nodes[i];
            self.run(
                "MATCH (n:Entity {id:$id}) SET n.kind=$kind, n.payload=$payload",
                vec![("id", s(id)), ("kind", s(kind)), ("payload", s(data))],
            )?;
        }
        // Links one statement each: both endpoints resolve through the primary-key index.
        for (a, b, k) in new_links {
            self.run(
                "MATCH (a:Entity {id:$a}), (b:Entity {id:$b}) CREATE (a)-[r:Link {kind:$kind}]->(b)",
                vec![("a", s(a)), ("b", s(b)), ("kind", s(k))],
            )?;
        }
        Ok(())
    }

    /// Applies up to `batch` followed events in one transaction; returns how many. Runs of
    /// batchable events go through `apply_run`; the others through the per-event path, in
    /// journal order.
    fn step(&self, follower: &mut JournalFollower, batch: usize) -> Result<usize, Error> {
        let mut pending = Vec::new();
        while pending.len() < batch {
            let Some(stored) = follower.next_event()? else {
                break;
            };
            pending.push((
                strict_json(&stored.event)?,
                stored.event_id.to_string(),
                strict_json(&stored.payload)?,
                stored.seq,
            ));
        }
        let applied = pending.len();
        if applied > 0 {
            kammi_store::fault::hit("projection.before");
            self.conn.query("BEGIN TRANSACTION")?;
            let mut run: Vec<(Json, String, Json)> = Vec::new();
            let result = (|| -> Result<(), Error> {
                for (event, id, payload, seq) in pending {
                    if batchable(field(&event, "type")?) {
                        run.push((event, id, payload));
                        continue;
                    }
                    if !run.is_empty() {
                        self.apply_run(&std::mem::take(&mut run))?;
                    }
                    self.apply(&event, &id, &payload)
                        .map_err(|e| format!("projection of seq {seq} failed: {e}"))?;
                }
                if !run.is_empty() {
                    self.apply_run(&run)?;
                }
                Ok(())
            })();
            if let Err(e) = result {
                self.rollback()?;
                return Err(e);
            }
            self.run(
                "MATCH (m:LedgerMeta {id:'primary'}) SET m.seq = $seq, m.head = $head",
                vec![
                    ("seq", Value::Int64(follower.seq() as i64)),
                    ("head", s(&follower.head().to_string())),
                ],
            )?;
            self.commit()?;
        }
        Ok(applied)
    }

    fn counts(&self) -> Result<Json, Error> {
        let mut out = kammi_jcs::Map::new();
        for table in [
            "Artifact",
            "Event",
            "Seal",
            "Run",
            "CustodyFact",
            "Entity",
            "PhoenixVault",
            "PhoenixSource",
        ] {
            let rows: Vec<Vec<Value>> = self
                .conn
                .query(&format!("MATCH (n:{table}) RETURN count(n)"))?
                .collect();
            let count = match rows.first().and_then(|r| r.first()) {
                Some(Value::Int64(n)) => *n,
                other => return Err(format!("count {table}: {other:?}").into()),
            };
            out.insert(format!("{}s", table.to_lowercase()), Json::from(count));
        }
        let links: Vec<Vec<Value>> = self
            .conn
            .query("MATCH ()-[r:Link]->() RETURN count(r)")?
            .collect();
        if let Some(Value::Int64(n)) = links.first().and_then(|r| r.first()) {
            out.insert("links".into(), Json::from(*n));
        }
        Ok(Json::Object(out))
    }

    /// Reads every row of every table (so Ladybug checks every page's checksum) and requires
    /// the Event table to be exactly the journal prefix up to the stored position.
    fn verify(&self, store: &Path) -> Result<Json, Error> {
        let mut rows = 0u64;
        let tables: Vec<Vec<Value>> = self
            .conn
            .query("CALL SHOW_TABLES() RETURN name, type")?
            .collect();
        for table in &tables {
            let (Value::String(name), Value::String(kind)) = (&table[0], &table[1]) else {
                continue;
            };
            let query = if kind == "NODE" {
                format!("MATCH (n:{name}) RETURN n")
            } else {
                format!("MATCH ()-[r:{name}]->() RETURN r")
            };
            rows += self.conn.query(&query)?.count() as u64;
        }
        let (seq, head) = self.position()?;
        let events: Vec<Vec<Value>> = self
            .conn
            .query("MATCH (e:Event) RETURN e.seq, e.id, e.prev ORDER BY e.seq")?
            .collect();
        if events.len() as u64 != seq {
            return Err(format!(
                "projection holds {} events but claims position {seq}",
                events.len()
            )
            .into());
        }
        let mut follower = JournalFollower::new(store, "main");
        for row in &events {
            let stored = follower
                .next_event()?
                .ok_or("projection is ahead of the journal")?;
            let envelope = strict_json(&stored.event)?;
            let expected = [
                Value::Int64(stored.seq as i64),
                s(&stored.event_id.to_string()),
                s(field(&envelope, "prev")?),
            ];
            if row.as_slice() != expected.as_slice() {
                return Err(
                    format!("projection event {} differs from the journal", stored.seq).into(),
                );
            }
        }
        if follower.head() != head {
            return Err("projection head differs from the journal".into());
        }
        Ok(
            kammi_core::obj! {"verified" => true, "rows_read" => rows, "events" => seq, "head" => head.to_string()},
        )
    }

    /// Every table's rows as sorted text, keyed by primary keys (never internal offsets),
    /// so two databases with the same content dump identically.
    fn dump(&self) -> Result<std::collections::BTreeMap<String, Vec<String>>, Error> {
        let key = |table: &str| if table == "Seal" { "root" } else { "id" };
        let mut out = std::collections::BTreeMap::new();
        let tables: Vec<Vec<Value>> = self
            .conn
            .query("CALL SHOW_TABLES() RETURN name, type")?
            .collect();
        for table in &tables {
            let (Value::String(name), Value::String(kind)) = (&table[0], &table[1]) else {
                continue;
            };
            if !known_tables().contains(&name.as_str()) {
                continue;
            }
            let props: Vec<String> = self
                .conn
                .query(&format!("CALL TABLE_INFO('{name}') RETURN name"))?
                .filter_map(|r| match r.first() {
                    Some(Value::String(p)) => Some(p.clone()),
                    _ => None,
                })
                .collect();
            let query = if kind == "NODE" {
                format!(
                    "MATCH (n:{name}) RETURN {}",
                    props
                        .iter()
                        .map(|p| format!("n.{p}"))
                        .collect::<Vec<_>>()
                        .join(", ")
                )
            } else {
                let connection: Vec<Vec<Value>> = self
                    .conn
                    .query(&format!("CALL SHOW_CONNECTION('{name}') RETURN *"))?
                    .collect();
                let (Some(Value::String(from)), Some(Value::String(to))) =
                    (connection[0].first(), connection[0].get(1))
                else {
                    return Err(format!("rel table {name} has no connection").into());
                };
                let extra: String = props.iter().map(|p| format!(", r.{p}")).collect();
                format!(
                    "MATCH (a:{from})-[r:{name}]->(b:{to}) RETURN a.{}, b.{}{extra}",
                    key(from),
                    key(to)
                )
            };
            let mut rows: Vec<String> = self
                .conn
                .query(&query)?
                .map(|row| format!("{row:?}"))
                .collect();
            rows.sort();
            out.insert(name.clone(), rows);
        }
        Ok(out)
    }

    fn history(&self, run: &str) -> Result<Json, Error> {
        let mut statement = self.conn.prepare(
            "MATCH (r:Run {id:$run})-[:HasFact]->(f:CustodyFact) RETURN f.id, f.kind, f.subject, f.target, f.value, f.evidence_id, f.scope ORDER BY f.kind, f.subject, f.id",
        )?;
        let keys = [
            "fact_id",
            "kind",
            "subject",
            "object",
            "value",
            "evidence_artifact",
            "scope",
        ];
        let rows = self.conn.execute(&mut statement, vec![("run", s(run))])?;
        Ok(Json::Array(
            rows.map(|row| {
                Json::Object(
                    keys.iter()
                        .zip(row)
                        .map(|(k, v)| (k.to_string(), Json::from(v.to_string())))
                        .collect(),
                )
            })
            .collect(),
        ))
    }
}

/// Buffer pool bytes, fixed once per process by [`size_pool`].
static POOL: std::sync::OnceLock<u64> = std::sync::OnceLock::new();

/// Sizes the buffer pool from the store: 4x the main journal bytes, at least Python's
/// 256 MiB and at most 16 GiB; `KAMMI_PROJECTOR_BUFFER_MB` overrides. Python's fixed 256 MiB
/// fills up at around a million events (the post-commit checkpoint then fails and the
/// projector crash-loops). The pool is claimed lazily, and its size does not change results.
fn size_pool(store: Option<&Path>) -> u64 {
    const FLOOR: u64 = 256 << 20;
    const CEILING: u64 = 16 << 30;
    let bytes = match std::env::var("KAMMI_PROJECTOR_BUFFER_MB")
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
    {
        Some(mb) => mb << 20,
        None => {
            let journal: u64 = store
                .and_then(|s| std::fs::read_dir(s.join("journal").join("main")).ok())
                .map(|dir| {
                    dir.flatten()
                        .filter_map(|e| e.metadata().ok())
                        .map(|m| m.len())
                        .sum()
                })
                .unwrap_or(0);
            journal.saturating_mul(4).clamp(FLOOR, CEILING)
        }
    };
    *POOL.get_or_init(|| bytes)
}

fn pool() -> u64 {
    *POOL.get_or_init(|| 256 << 20)
}

/// Python's projection settings (`projection_runtime.py`: 2 threads; its 256 MiB pool is the
/// floor of [`size_pool`]). The thread count is part of search parity: BM25 aggregation order
/// follows it, and a 4-thread pool changed FTS scores in the last bit, which changes search
/// receipts and the chain.
fn config() -> SystemConfig {
    SystemConfig::default()
        .buffer_pool_size(pool())
        .max_num_threads(2)
        .throw_on_wal_replay_failure(true)
        .enable_checksums(true)
}

/// Opens the projection database; one that will not open is quarantined whole and rebuilt.
///
/// A projector killed mid-write leaves a torn WAL that Ladybug refuses to replay. Dropping
/// only the WAL was tried and is unsafe: the database then opens but the process crashes
/// with an access violation on use (the main file depends on WAL state even at the last
/// checkpoint). The projection is disposable and bulk rebuilds take seconds, so the whole
/// projection goes to quarantine.
fn open(db_path: &Path) -> Result<Database, Error> {
    match Database::new(db_path, config()) {
        Ok(db) => Ok(db),
        Err(e) => {
            quarantine(db_path, &format!("unopenable: {e}"))?;
            Ok(Database::new(db_path, config())?)
        }
    }
}

/// Starts that never reached a healthy, serving state (crashes inside the engine included).
/// After `CRASH_LOOP_LIMIT` in a row the projection is quarantined before opening.
const CRASH_LOOP_LIMIT: u64 = 3;

fn begin_start(db_path: &Path) -> Result<(), Error> {
    let mut health = Health::load(db_path);
    if health.unhealthy_starts >= CRASH_LOOP_LIMIT && db_path.exists() {
        let starts = health.unhealthy_starts;
        quarantine(
            db_path,
            &format!("crash loop: {starts} starts never became healthy"),
        )?;
        health = Health::load(db_path);
        health.unhealthy_starts = 0;
    }
    health.unhealthy_starts += 1;
    health.save(db_path)
}

fn mark_healthy(db_path: &Path) -> Result<(), Error> {
    let mut health = Health::load(db_path);
    health.unhealthy_starts = 0;
    health.save(db_path)
}

/// A private scratch directory for bulk CSV files (never inside authority directories).
/// Removes `bulk-*` scratch directories a crashed bulk load left beside the database.
fn remove_stale_scratch(db_path: &Path) {
    let Some(Ok(dir)) = db_path.parent().map(std::fs::read_dir) else {
        return;
    };
    for entry in dir.flatten() {
        if entry.file_name().to_string_lossy().starts_with("bulk-") && entry.path().is_dir() {
            let _ = std::fs::remove_dir_all(entry.path());
        }
    }
}

fn scratch_dir(store: &Path) -> PathBuf {
    store
        .join("projection")
        .join(format!("bulk-{}", std::process::id()))
}

/// Bulk-loads custody from genesis into an empty projection; statement path otherwise.
fn bulk_if_empty(graph: &Graph, store: &Path) -> Result<Option<Json>, Error> {
    if graph.position()?.0 != 0 {
        return Ok(None);
    }
    let started = Instant::now();
    let (model, follower) = bulk::CustodyModel::derive(store, None)?;
    if follower.seq() == 0 {
        return Ok(None);
    }
    let loaded = graph.bulk_load(&model, &scratch_dir(store))?;
    eprintln!(
        "kammi-projector: bulk-loaded {} events in {:.2}s",
        follower.seq(),
        started.elapsed().as_secs_f64()
    );
    Ok(Some(
        kammi_core::obj! {"events" => follower.seq(), "seconds" => started.elapsed().as_secs_f64(), "rows" => loaded},
    ))
}

/// Re-derives the projection in memory up to the stored position and compares every row.
/// The engine does not catch every corrupt page (a damaged rel page can re-point edges
/// silently), so content is checked against a fresh derivation. Returns tables compared.
fn deep_verify(graph: &Graph, store: &Path) -> Result<usize, Error> {
    let target = graph.position()?.0;
    let memory_target = graph.memory_position()?.0;
    let fresh = Database::in_memory(
        SystemConfig::default()
            .buffer_pool_size(pool())
            .max_num_threads(2),
    )?;
    let expected = Graph::new(&fresh, graph.memory.borrow().dims)?;
    let mut objects = ObjectReader::new(store);
    let mut memory = JournalFollower::new(store, "memory");
    while memory.seq() < memory_target {
        let want = usize::try_from(memory_target - memory.seq())
            .unwrap_or(usize::MAX)
            .min(4096);
        if expected.step_memory(&mut memory, &mut objects, want)? == 0 {
            return Err("memory journal is shorter than the projection position".into());
        }
    }
    // Custody is re-derived through the bulk model, so this also cross-checks the bulk path
    // against the statement path that built the live projection.
    let (model, follower) = bulk::CustodyModel::derive(store, Some(target))?;
    if follower.seq() < target {
        return Err("journal is shorter than the projection position".into());
    }
    expected.bulk_load(&model, &scratch_dir(store))?;
    let (actual, wanted) = (graph.dump()?, expected.dump()?);
    let differing: std::collections::BTreeSet<&String> = wanted
        .keys()
        .chain(actual.keys())
        .filter(|t| actual.get(*t) != wanted.get(*t))
        .collect();
    if !differing.is_empty() {
        return Err(
            format!("projection content differs from the journal in tables {differing:?}").into(),
        );
    }
    Ok(wanted.len())
}

/// Last deep verification and last quarantine, kept beside the projection so they survive
/// projector restarts (`<db>.health.json`).
#[derive(Default)]
pub struct Health {
    pub last_verify: Json,
    pub last_quarantine: Json,
    /// Consecutive starts that did not reach serving (crash-loop breaker).
    pub unhealthy_starts: u64,
}

fn health_path(db_path: &Path) -> PathBuf {
    PathBuf::from(format!("{}.health.json", db_path.display()))
}

fn now_utc() -> String {
    use kammi_core::Clock;
    kammi_core::SystemClock.now().isoformat()
}

impl Health {
    fn load(db_path: &Path) -> Health {
        let value: Json = std::fs::read(health_path(db_path))
            .ok()
            .and_then(|b| serde_json::from_slice(&b).ok())
            .unwrap_or(Json::Null);
        Health {
            last_verify: value["last_verify"].clone(),
            last_quarantine: value["last_quarantine"].clone(),
            unhealthy_starts: value["unhealthy_starts"].as_u64().unwrap_or(0),
        }
    }

    fn save(&self, db_path: &Path) -> Result<(), Error> {
        let value = kammi_core::obj! {
            "last_verify" => self.last_verify.clone(),
            "last_quarantine" => self.last_quarantine.clone(),
            "unhealthy_starts" => self.unhealthy_starts,
        };
        let temp = PathBuf::from(format!("{}.tmp", health_path(db_path).display()));
        std::fs::write(&temp, value.to_string())?;
        std::fs::rename(&temp, health_path(db_path))?;
        Ok(())
    }
}

/// Moves an existing projection aside (it is derived data; authority is untouched).
fn quarantine(db_path: &Path, reason: &str) -> Result<(), Error> {
    let mut health = Health::load(db_path);
    health.last_quarantine =
        kammi_core::obj! {"utc" => now_utc(), "scope" => "database", "reason" => reason};
    health.save(db_path)?;
    let quarantine = db_path
        .parent()
        .unwrap_or(Path::new("."))
        .join("quarantine");
    std::fs::create_dir_all(&quarantine)?;
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_millis();
    for suffix in ["", ".wal", ".shadow"] {
        let from = PathBuf::from(format!("{}{suffix}", db_path.display()));
        if from.exists() {
            let name = format!(
                "{}{suffix}.{stamp}",
                db_path.file_name().unwrap_or_default().to_string_lossy()
            );
            std::fs::rename(&from, quarantine.join(name))?;
        }
    }
    prune_quarantine(&quarantine);
    eprintln!("kammi-projector: quarantined projection ({reason}); rebuilding from genesis");
    Ok(())
}

/// Quarantined databases kept for diagnosis; older ones are deleted (the projection is
/// derived, and a crash loop would otherwise fill the disk with full copies).
const QUARANTINE_KEEP: usize = 3;

fn prune_quarantine(quarantine: &Path) {
    let Ok(dir) = std::fs::read_dir(quarantine) else {
        return;
    };
    // Every file of one quarantine shares its millisecond stamp suffix.
    let mut stamps: std::collections::BTreeMap<u128, Vec<PathBuf>> = Default::default();
    for entry in dir.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        if let Some(stamp) = name.rsplit('.').next().and_then(|s| s.parse::<u128>().ok()) {
            stamps.entry(stamp).or_default().push(entry.path());
        }
    }
    let excess = stamps.len().saturating_sub(QUARANTINE_KEEP);
    for (_, paths) in stamps.into_iter().take(excess) {
        for path in paths {
            let _ = if path.is_dir() {
                std::fs::remove_dir_all(&path)
            } else {
                std::fs::remove_file(&path)
            };
        }
    }
}

fn flag(args: &[String], name: &str) -> Option<String> {
    args.windows(2).find(|w| w[0] == name).map(|w| w[1].clone())
}

/// Takes the OS lock `<db>.lock`, waiting up to `limit` for a previous owner to exit.
fn lock_projection(db_path: &Path, limit: Duration) -> Result<std::fs::File, Error> {
    let path = PathBuf::from(format!("{}.lock", db_path.display()));
    let file = std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(&path)?;
    let deadline = Instant::now() + limit;
    loop {
        match file.try_lock() {
            Ok(()) => return Ok(file),
            Err(std::fs::TryLockError::WouldBlock) if Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(100))
            }
            Err(e) => {
                return Err(format!(
                    "projection {} is owned by another projector: {e:?}",
                    db_path.display()
                )
                .into())
            }
        }
    }
}

/// Verifies an existing projection (quick scan plus deep re-derivation); quarantines it on
/// failure. Records the outcome in the health file.
fn verify_or_quarantine(db_path: &Path, store: &Path, dims: usize) -> Result<(), Error> {
    if !db_path.exists() {
        return Ok(());
    }
    let started = Instant::now();
    let failure = {
        let db = open(db_path)?;
        let graph = Graph::new(&db, dims)?;
        graph
            .verify(store)
            .and_then(|_| deep_verify(&graph, store))
            .err()
            .map(|e| e.to_string())
    };
    let mut health = Health::load(db_path);
    health.last_verify = kammi_core::obj! {
        "utc" => now_utc(), "ok" => failure.is_none(), "seconds" => started.elapsed().as_secs_f64(),
        "detail" => failure.clone().map_or(Json::Null, Json::from),
    };
    health.save(db_path)?;
    if let Some(reason) = failure {
        quarantine(db_path, &format!("verification failed: {reason}"))?;
    }
    Ok(())
}

fn main() -> Result<(), Error> {
    let args: Vec<String> = std::env::args().collect();
    let command = args.get(1).map(String::as_str).unwrap_or("");
    let db_path = PathBuf::from(flag(&args, "--db").ok_or("--db required")?);
    let dims: usize = flag(&args, "--memory-dims")
        .map(|d| d.parse())
        .transpose()?
        .unwrap_or(384);
    let store = flag(&args, "--store").map(PathBuf::from);
    if let Some(parent) = db_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    // One projector per database: a restarted daemon's new projector waits for the previous
    // one (which exits when its stdin closes) instead of racing it on the same files.
    let _owner = lock_projection(&db_path, Duration::from_secs(120))?;
    size_pool(store.as_deref());
    // Holding the lock, no other projector is bulk-loading: scratch left by a crashed one goes.
    remove_stale_scratch(&db_path);
    if command == "serve" {
        // The supervisor passes --reset after repeated fast crashes of a started projector.
        if args.iter().any(|a| a == "--reset") && db_path.exists() {
            quarantine(
                &db_path,
                "reset by supervisor: repeated crashes after start",
            )?;
        }
        begin_start(&db_path)?;
    }
    if matches!(command, "project" | "serve") && args.iter().any(|a| a == "--verify") {
        verify_or_quarantine(&db_path, store.as_deref().ok_or("--store required")?, dims)?;
    }
    if let Some(parent) = db_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let db = open(&db_path)?;
    let graph = Graph::new(&db, dims)?;
    match command {
        "serve" => {
            let store = store.ok_or("--store required")?;
            bulk_if_empty(&graph, &store)?;
            let (main, memory) = serve::followers(&graph, &store)?;
            graph.counts()?; // touch the tables: a start that crashes here stays unhealthy
            kammi_store::fault::hit("projector.before_healthy");
            mark_healthy(&db_path)?;
            let mut server = serve::Server {
                graph: &graph,
                main,
                memory,
                objects: ObjectReader::new(&store),
                health: Health::load(&db_path),
                started: Instant::now(),
            };
            server.run()?;
        }
        "verify" => {
            let store = store.ok_or("--store required")?;
            let mut report = graph.verify(&store)?;
            if args.iter().any(|a| a == "--deep") {
                let started = Instant::now();
                let tables = deep_verify(&graph, &store)?;
                report = kammi_core::json::merged(
                    &report,
                    kammi_core::obj! {"deep" => true, "tables_compared" => tables, "deep_seconds" => started.elapsed().as_secs_f64()},
                );
            }
            println!("{report}");
        }
        "project" => {
            let store = store.ok_or("--store required")?;
            let batch: usize = flag(&args, "--batch")
                .map(|b| b.parse())
                .transpose()?
                .unwrap_or(256);
            if args.iter().any(|a| a == "--bulk") {
                bulk_if_empty(&graph, &store)?;
            }
            let (mut follower, mut memory) = serve::followers(&graph, &store)?;
            let mut objects = ObjectReader::new(&store);
            let started = Instant::now();
            let mut total = 0;
            loop {
                let applied = graph.step(&mut follower, batch)?
                    + graph.step_memory(&mut memory, &mut objects, batch)?;
                total += applied;
                if applied == 0 {
                    if !args.iter().any(|a| a == "--follow") {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(100));
                }
            }
            let elapsed = started.elapsed().as_secs_f64();
            println!(
                "{}",
                kammi_core::obj! {
                    "projected" => total, "seconds" => elapsed, "events_per_second" => if elapsed > 0.0 { total as f64 / elapsed } else { 0.0 },
                    "seq" => follower.seq(), "head" => follower.head().to_string(), "memory_seq" => memory.seq(),
                    "counts" => graph.counts()?, "memory" => graph.memory_counts()?,
                }
            );
        }
        "counts" => println!("{}", graph.counts()?),
        // Diagnostic: raw FTS rows through this binding (no overlay, no index rebuild).
        "fts" => {
            let query = flag(&args, "--query").ok_or("--query required")?;
            let count: i64 = flag(&args, "--count")
                .map(|c| c.parse())
                .transpose()?
                .unwrap_or(40);
            if args.iter().any(|a| a == "--rebuild") {
                if graph.memory.borrow().fts_exists {
                    graph
                        .conn
                        .query("CALL DROP_FTS_INDEX('Memory', 'memory_text')")?;
                }
                graph.conn.query(
                    "CALL CREATE_FTS_INDEX('Memory', 'memory_text', ['text'], stemmer := 'none')",
                )?;
            }
            let mut statement = graph.conn.prepare("CALL QUERY_FTS_INDEX('Memory', 'memory_text', $query, TOP := $count) RETURN node.id, score ORDER BY score DESC, node.id")?;
            let rows: Vec<Json> = graph
                .conn
                .execute(
                    &mut statement,
                    vec![
                        ("query", Value::String(query)),
                        ("count", Value::Int64(count)),
                    ],
                )?
                .map(|row| {
                    Json::from(vec![
                        Json::from(format!("{:?}", row[0])),
                        Json::from(format!("{:?}", row[1])),
                    ])
                })
                .collect();
            println!("{}", Json::from(rows));
        }
        "history" => println!(
            "{}",
            graph.history(&flag(&args, "--run").ok_or("--run required")?)?
        ),
        _ => {
            return Err(
                "usage: kammi-projector serve|project|verify|counts|history --db <path> ...".into(),
            )
        }
    }
    Ok(())
}
