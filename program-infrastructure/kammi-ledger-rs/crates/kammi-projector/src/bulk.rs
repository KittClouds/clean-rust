//! Bulk rebuild of the custody projection from genesis.
//!
//! The statement path runs ~10 Cypher statements per event (~100 events/s). A rebuild from an
//! empty projection instead derives every row in memory with the exact semantics of those
//! statements, writes CSV files and loads them with `COPY FROM`:
//!
//! - `CREATE` appends a row; `MERGE ... SET` is last-writer-wins per key;
//! - `MATCH (a), (b) CREATE (a)-[:R]->(b)` creates the edge only if both endpoints exist at
//!   that point of history (a seal member registered later gets no `SealMember` edge);
//! - `MERGE (a)-[:R {k}]->(b)` de-duplicates on (a, b, k).
//!
//! Journal semantics stay one event at a time; only the derived projection is bulk-loaded.
//! Memory tables keep the per-event statement path (Python's FTS behaviour depends on it).
//! `verify --deep` re-derives through this path, so every deep verification also compares
//! the bulk derivation with the statement-built database.

use std::collections::{BTreeMap, BTreeSet};
use std::io::Write;
use std::path::Path;

use kammi_jcs::{strict_json, Value as Json};
use kammi_store::JournalFollower;

use super::{field, strings, Error, Graph, ARTIFACT_FIELDS, ENTITY_FIELDS, RUN_RELATIONS};

#[derive(Default)]
struct Vault {
    owner: String,
    source_epoch: i64,
    generation_id: i64,
    generation_epoch: i64,
    manifest: String,
    reader_source: String,
    reader_revision: i64,
    reader_offset: i64,
}

#[derive(Default)]
pub struct CustodyModel {
    events: Vec<[String; 5]>,
    artifacts: BTreeMap<String, i64>,
    runs: BTreeMap<String, String>,
    seals: BTreeMap<String, String>,
    seal_members: Vec<(String, String)>,
    seal_parents: Vec<(String, String)>,
    facts: BTreeMap<String, [String; 8]>,
    has_fact: Vec<(String, String)>,
    fact_evidence: Vec<(String, String)>,
    entities: BTreeMap<String, (String, String)>,
    links: BTreeSet<(String, String, String)>,
    vaults: BTreeMap<String, Vault>,
    sources: BTreeMap<String, (String, String, i64, String, i64, i64)>,
    generations: BTreeMap<String, (String, i64, i64, String)>,
    products: BTreeMap<String, (i64, String)>,
    has_source: BTreeSet<(String, String)>,
    has_generation: BTreeSet<(String, String)>,
    has_product: BTreeSet<(String, String)>,
    pub seq: u64,
    pub head: String,
}

fn int(payload: &Json, key: &str) -> Result<i64, Error> {
    payload[key]
        .as_i64()
        .ok_or_else(|| format!("projection: integer field {key} missing").into())
}

impl CustodyModel {
    fn node(&mut self, id: &str, kind: &str, data: &str) {
        self.entities
            .insert(id.to_string(), (kind.to_string(), data.to_string()));
    }

    fn edge(&mut self, a: &str, b: &str, kind: &str) {
        // Both endpoints were just merged by `node`, so the MATCH always succeeds.
        self.links
            .insert((a.to_string(), b.to_string(), kind.to_string()));
    }

    pub fn apply(&mut self, event: &Json, event_id: &str, payload: &Json) -> Result<(), Error> {
        let kind = field(event, "type")?;
        self.events.push([
            event_id.into(),
            int(event, "seq")?.to_string(),
            kind.into(),
            field(event, "payload_artifact")?.into(),
            field(event, "prev")?.into(),
        ]);
        match kind {
            "ArtifactRegistered" => {
                self.artifacts.insert(
                    field(payload, "artifact_id")?.into(),
                    int(payload, "byte_count")?,
                );
            }
            "RunCreated" => {
                let run = field(payload, "run_id")?;
                if self
                    .runs
                    .insert(run.into(), field(payload, "lab")?.into())
                    .is_some()
                {
                    return Err(format!("duplicate Run {run}").into());
                }
            }
            "SealCreated" => {
                let root = field(payload, "root")?.to_string();
                if self
                    .seals
                    .insert(root.clone(), field(payload, "seal_artifact")?.into())
                    .is_some()
                {
                    return Err(format!("duplicate Seal {root}").into());
                }
                for member in strings(payload, "direct_members") {
                    if self.artifacts.contains_key(member) {
                        self.seal_members.push((root.clone(), member.into()));
                    }
                }
                for parent in strings(payload, "parents") {
                    if self.seals.contains_key(parent) {
                        self.seal_parents.push((root.clone(), parent.into()));
                    }
                }
            }
            "FactRecorded" => {
                let (fact, run, evidence) = (
                    field(payload, "fact_id")?,
                    field(payload, "run_id")?,
                    field(payload, "evidence_artifact")?,
                );
                let row = [
                    fact.to_string(),
                    run.to_string(),
                    field(payload, "kind")?.into(),
                    field(payload, "subject")?.into(),
                    field(payload, "object")?.into(),
                    field(payload, "value")?.into(),
                    evidence.to_string(),
                    field(payload, "scope")?.into(),
                ];
                if self.facts.insert(fact.into(), row).is_some() {
                    return Err(format!("duplicate CustodyFact {fact}").into());
                }
                if self.runs.contains_key(run) {
                    self.has_fact.push((run.into(), fact.into()));
                }
                if self.artifacts.contains_key(evidence) {
                    self.fact_evidence.push((fact.into(), evidence.into()));
                }
            }
            _ => {}
        }
        self.entities_for(event, event_id, payload)?;
        self.vault(kind, payload)?;
        self.seq = int(event, "seq")? as u64;
        self.head = event_id.to_string();
        Ok(())
    }

    fn entities_for(&mut self, event: &Json, event_id: &str, payload: &Json) -> Result<(), Error> {
        let data = field(event, "payload_artifact")?.to_string();
        self.node(event_id, "Event", &data);
        let mut ids = std::collections::HashMap::new();
        for (key, kind) in ENTITY_FIELDS {
            if let Some(value) = payload.get(*key).and_then(Json::as_str) {
                let id = format!("{kind}:{value}");
                self.node(&id, kind, &data);
                self.edge(event_id, &id, "CITES");
                ids.insert(*key, id);
            }
        }
        for key in ARTIFACT_FIELDS {
            if let Some(value) = payload.get(*key).and_then(Json::as_str) {
                let id = format!("Artifact:{value}");
                self.node(&id, "Artifact", &data);
                self.edge(event_id, &id, "CITES");
            }
        }
        if let Some(run) = ids.get("run_id").cloned() {
            self.edge(&run, event_id, "HAS_EVENT");
            for (key, relation) in RUN_RELATIONS {
                if let Some(id) = ids.get(key).cloned() {
                    self.edge(&run, &id, relation);
                }
            }
        }
        if field(event, "type")? == "SealCreated" {
            let seal = format!("Seal:{}", field(payload, "root")?);
            self.node(&seal, "Seal", &data);
            for member in strings(payload, "direct_members") {
                let artifact = format!("Artifact:{member}");
                self.node(&artifact, "Artifact", &data);
                self.edge(&artifact, &seal, "SEALED_BY");
            }
            for parent in strings(payload, "parents") {
                let parent = format!("Seal:{parent}");
                self.node(&parent, "Seal", &data);
                self.edge(&seal, &parent, "PARENT_SEAL");
            }
        }
        Ok(())
    }

    fn vault(&mut self, kind: &str, p: &Json) -> Result<(), Error> {
        match kind {
            "VaultCreated" => {
                let id = field(p, "vault_id")?;
                let vault = Vault {
                    owner: field(p, "owner_actor")?.into(),
                    ..Default::default()
                };
                if self.vaults.insert(id.into(), vault).is_some() {
                    return Err(format!("duplicate PhoenixVault {id}").into());
                }
            }
            "VaultSourceCommitted" => {
                let vault = field(p, "vault_id")?.to_string();
                let key = format!("{vault}:{}", field(p, "source_id")?);
                self.sources.insert(
                    key.clone(),
                    (
                        vault.clone(),
                        field(p, "source_id")?.into(),
                        int(p, "revision")?,
                        field(p, "artifact_id")?.into(),
                        int(p, "byte_count")?,
                        int(p, "epoch")?,
                    ),
                );
                if let Some(v) = self.vaults.get_mut(&vault) {
                    v.source_epoch = int(p, "epoch")?;
                    self.has_source.insert((vault, key));
                }
            }
            "VaultGenerationSelected" => {
                let vault = field(p, "vault_id")?.to_string();
                let key = format!("{vault}:{}", p["generation_id"]);
                let row = (
                    vault.clone(),
                    int(p, "generation_id")?,
                    int(p, "source_epoch")?,
                    field(p, "manifest_artifact_id")?.to_string(),
                );
                if self.generations.insert(key.clone(), row).is_some() {
                    return Err(format!("duplicate PhoenixGeneration {key}").into());
                }
                if let Some(v) = self.vaults.get_mut(&vault) {
                    v.generation_id = int(p, "generation_id")?;
                    v.generation_epoch = int(p, "source_epoch")?;
                    v.manifest = field(p, "manifest_artifact_id")?.into();
                    self.has_generation.insert((vault, key));
                }
            }
            "VaultReaderPositionSet" => {
                if let Some(v) = self.vaults.get_mut(field(p, "vault_id")?) {
                    v.reader_source = field(p, "source_id")?.into();
                    v.reader_revision = int(p, "revision")?;
                    v.reader_offset = int(p, "offset")?;
                }
            }
            "VaultProductPrimarySelected" => {
                let vault = field(p, "vault_id")?.to_string();
                if self
                    .products
                    .insert(
                        vault.clone(),
                        (
                            int(p, "source_epoch")?,
                            field(p, "receipt_artifact_id")?.into(),
                        ),
                    )
                    .is_some()
                {
                    return Err(format!("duplicate PhoenixProductPrimary {vault}").into());
                }
                if self.vaults.contains_key(&vault) {
                    self.has_product.insert((vault.clone(), vault));
                }
            }
            _ => {}
        }
        Ok(())
    }

    /// Follows the main journal to its end (or `limit`) and folds every event in.
    pub fn derive(
        store: &Path,
        limit: Option<u64>,
    ) -> Result<(CustodyModel, JournalFollower), Error> {
        let mut model = CustodyModel {
            head: kammi_jcs::Sha256Id::ZERO.to_string(),
            ..Default::default()
        };
        let mut follower = JournalFollower::new(store, "main");
        while limit.is_none_or(|l| follower.seq() < l) {
            let Some(stored) = follower.next_event()? else {
                break;
            };
            model.apply(
                &strict_json(&stored.event)?,
                &stored.event_id.to_string(),
                &strict_json(&stored.payload)?,
            )?;
        }
        Ok((model, follower))
    }
}

/// One CSV field: strings always quoted with `"` doubled; integers bare.
pub(crate) enum Cell<'a> {
    S(&'a str),
    I(i64),
}

pub(crate) fn write_csv<'a>(
    path: &Path,
    rows: impl Iterator<Item = Vec<Cell<'a>>>,
) -> Result<usize, Error> {
    let mut out = std::io::BufWriter::new(std::fs::File::create(path)?);
    let mut count = 0;
    for row in rows {
        for (i, cell) in row.iter().enumerate() {
            if i > 0 {
                out.write_all(b",")?;
            }
            match cell {
                Cell::S(text) => {
                    out.write_all(b"\"")?;
                    out.write_all(text.replace('"', "\"\"").as_bytes())?;
                    out.write_all(b"\"")?;
                }
                Cell::I(n) => write!(out, "{n}")?,
            }
        }
        out.write_all(b"\n")?;
        count += 1;
    }
    out.flush()?;
    Ok(count)
}

impl Graph<'_> {
    /// Loads a derived model into an empty custody projection (`position() == 0`).
    pub fn bulk_load(&self, model: &CustodyModel, scratch: &Path) -> Result<Json, Error> {
        use Cell::{I, S};
        if self.position()?.0 != 0 {
            return Err("bulk load requires an empty custody projection".into());
        }
        std::fs::create_dir_all(scratch)?;
        let mut loaded = kammi_jcs::Map::new();
        let mut copy = |table: &str, count: usize, file: &Path| -> Result<(), Error> {
            if count > 0 {
                let path = file.to_string_lossy().replace('\\', "/");
                self.conn.query(&format!("COPY {table} FROM '{path}' (HEADER=false, PARALLEL=false, QUOTE='\"', ESCAPE='\"', DELIM=',')"))?;
            }
            loaded.insert(table.into(), Json::from(count));
            Ok(())
        };
        let file = |name: &str| scratch.join(format!("{name}.csv"));
        macro_rules! load {
            ($table:literal, $rows:expr) => {{
                let path = file($table);
                let count = write_csv(&path, $rows)?;
                copy($table, count, &path)?;
            }};
        }
        load!(
            "Event",
            model.events.iter().map(|e| vec![
                S(&e[0]),
                I(e[1].parse().unwrap_or(0)),
                S(&e[2]),
                S(&e[3]),
                S(&e[4])
            ])
        );
        load!(
            "Artifact",
            model.artifacts.iter().map(|(id, n)| vec![S(id), I(*n)])
        );
        load!(
            "Seal",
            model
                .seals
                .iter()
                .map(|(root, payload)| vec![S(root), S(payload)])
        );
        load!(
            "Run",
            model.runs.iter().map(|(id, lab)| vec![S(id), S(lab)])
        );
        load!(
            "CustodyFact",
            model
                .facts
                .values()
                .map(|f| f.iter().map(|v| S(v)).collect())
        );
        load!(
            "Entity",
            model
                .entities
                .iter()
                .map(|(id, (kind, payload))| vec![S(id), S(kind), S(payload)])
        );
        load!(
            "PhoenixVault",
            model.vaults.iter().map(|(id, v)| vec![
                S(id),
                S(&v.owner),
                I(v.source_epoch),
                I(v.generation_id),
                I(v.generation_epoch),
                S(&v.manifest),
                S(&v.reader_source),
                I(v.reader_revision),
                I(v.reader_offset)
            ])
        );
        load!(
            "PhoenixSource",
            model.sources.iter().map(|(id, s)| vec![
                S(id),
                S(&s.0),
                S(&s.1),
                I(s.2),
                S(&s.3),
                I(s.4),
                I(s.5)
            ])
        );
        load!(
            "PhoenixGeneration",
            model
                .generations
                .iter()
                .map(|(id, g)| vec![S(id), S(&g.0), I(g.1), I(g.2), S(&g.3)])
        );
        load!(
            "PhoenixProductPrimary",
            model
                .products
                .iter()
                .map(|(id, p)| vec![S(id), S(id), I(p.0), S(&p.1)])
        );
        load!(
            "SealMember",
            model.seal_members.iter().map(|(a, b)| vec![S(a), S(b)])
        );
        load!(
            "SealParent",
            model.seal_parents.iter().map(|(a, b)| vec![S(a), S(b)])
        );
        load!(
            "HasFact",
            model.has_fact.iter().map(|(a, b)| vec![S(a), S(b)])
        );
        load!(
            "FactEvidence",
            model.fact_evidence.iter().map(|(a, b)| vec![S(a), S(b)])
        );
        load!(
            "Link",
            model.links.iter().map(|(a, b, k)| vec![S(a), S(b), S(k)])
        );
        load!(
            "PhoenixHasSource",
            model.has_source.iter().map(|(a, b)| vec![S(a), S(b)])
        );
        load!(
            "PhoenixHasGeneration",
            model.has_generation.iter().map(|(a, b)| vec![S(a), S(b)])
        );
        load!(
            "PhoenixHasProductPrimary",
            model.has_product.iter().map(|(a, b)| vec![S(a), S(b)])
        );
        self.conn.query(&format!(
            "MATCH (m:LedgerMeta {{id:'primary'}}) SET m.seq = {}, m.head = '{}'",
            model.seq, model.head
        ))?;
        let _ = std::fs::remove_dir_all(scratch);
        // The loaded entities, artifacts and links are now committed rows; the statement path
        // must see all of them or it would CREATE duplicates.
        self.load_keys()?;
        Ok(Json::Object(loaded))
    }
}
