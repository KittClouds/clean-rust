//! Moving authority between the Python (v1) layout and the v2 store.
//!
//! [`sync`] is both the one-shot import and one step of the future shadow follower: it
//! appends every v1 event the v2 store does not have yet, after proving that the history the
//! two share is identical, and it copies every v1 object first so that no imported event can
//! name a missing object. Running it again is a no-op; running it after Python appended more
//! events imports exactly those.
//!
//! [`export_v1`] writes the v2 store back in the exact v1 layout: `events.log` frames are
//! byte-identical and objects are loose files at v1 paths. It is the rollback path and the
//! strongest round-trip check.

use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

use hashbrown::HashSet;
use kammi_jcs::{canonical, raw_id, Sha256Id};
use kammi_store::{NewEvent, Store, StoreError};
use kammi_v1::{V1Error, V1Event, V1Store};
use serde_json::json;

#[derive(Debug, thiserror::Error)]
pub enum MigrateError {
    #[error(transparent)]
    V1(#[from] V1Error),
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Jcs(#[from] kammi_jcs::JcsError),
    #[error("I/O error on {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("{journal} journal diverged from v1 at seq {seq}")]
    Diverged { journal: &'static str, seq: u64 },
    #[error("{journal} journal in v2 is ahead of v1 ({v2} > {v1}); v1 is still the authority")]
    Ahead {
        journal: &'static str,
        v2: u64,
        v1: u64,
    },
    #[error("export destination already exists: {0}")]
    DestinationExists(PathBuf),
}

type Result<T> = std::result::Result<T, MigrateError>;

fn io(path: impl Into<PathBuf>) -> impl FnOnce(std::io::Error) -> MigrateError {
    let path = path.into();
    move |source| MigrateError::Io { path, source }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct StreamSync {
    pub v1_seq: u64,
    pub v1_head: Option<Sha256Id>,
    pub already_present: u64,
    pub appended: u64,
}

#[derive(Debug, Clone, Default)]
pub struct SyncReport {
    pub main: StreamSync,
    pub memory: StreamSync,
    pub v1_objects: u64,
    pub objects_copied: u64,
    pub object_bytes_copied: u64,
    pub payload_objects_inlined: u64,
    pub seconds: f64,
}

/// Events appended per batch (one flush each).
const EVENT_BATCH: usize = 512;
/// Upper bound of small-object bytes buffered before one packed flush.
const OBJECT_BATCH_BYTES: usize = 32 * 1024 * 1024;

/// Brings `store` up to date with `v1`. See the module documentation.
pub fn sync(v1: &V1Store, store: &mut Store) -> Result<SyncReport> {
    let started = Instant::now();
    let main_events = v1.main_journal()?.read_all()?;
    let memory_events = match v1.memory_journal()? {
        Some(mut journal) => journal.read_all()?,
        None => Vec::new(),
    };
    check_shared_prefix("main", &main_events, &store.main)?;
    check_shared_prefix("memory", &memory_events, &store.memory)?;

    // Payloads travel inline with their events; everything else is copied as an object,
    // before any event is appended.
    let payloads: HashSet<Sha256Id> = main_events
        .iter()
        .chain(&memory_events)
        .map(V1Event::payload_artifact)
        .collect();
    let mut report = SyncReport {
        payload_objects_inlined: payloads.len() as u64,
        ..Default::default()
    };
    let ids = v1.object_ids()?;
    report.v1_objects = ids.len() as u64;
    let threshold = small_object_threshold();
    let mut batch: Vec<Vec<u8>> = Vec::new();
    let mut batch_bytes = 0usize;
    for id in ids {
        if payloads.contains(&id) || store.contains_object(&id) {
            continue;
        }
        let length = v1.object_len(&id)?;
        report.objects_copied += 1;
        report.object_bytes_copied += length;
        if (length as usize) < threshold {
            batch_bytes += length as usize;
            batch.push(v1.read_object(&id)?);
            if batch_bytes >= OBJECT_BATCH_BYTES {
                flush_objects(store, &mut batch)?;
                batch_bytes = 0;
            }
        } else {
            let path = v1.object_path(&id);
            let mut source = File::open(&path).map_err(io(&path))?;
            store.objects.put_stream(&mut source, Some(id))?;
        }
    }
    flush_objects(store, &mut batch)?;

    report.main = append_new(v1, "main", &main_events, &mut store.main)?;
    report.memory = append_new(v1, "memory", &memory_events, &mut store.memory)?;
    write_genesis(store, v1, &report)?;
    report.seconds = started.elapsed().as_secs_f64();
    Ok(report)
}

fn small_object_threshold() -> usize {
    kammi_store::ObjectOptions::default().pack_threshold
}

fn flush_objects(store: &mut Store, batch: &mut Vec<Vec<u8>>) -> Result<()> {
    if batch.is_empty() {
        return Ok(());
    }
    let refs: Vec<&[u8]> = batch.iter().map(Vec::as_slice).collect();
    store.objects.put_many(&refs)?;
    batch.clear();
    Ok(())
}

fn check_shared_prefix(
    journal: &'static str,
    v1: &[V1Event],
    v2: &kammi_store::Journal,
) -> Result<()> {
    if v2.seq() > v1.len() as u64 {
        return Err(MigrateError::Ahead {
            journal,
            v2: v2.seq(),
            v1: v1.len() as u64,
        });
    }
    for event in &v1[..v2.seq() as usize] {
        if v2.record(event.seq)?.event_id != event.event_id.0 {
            return Err(MigrateError::Diverged {
                journal,
                seq: event.seq,
            });
        }
    }
    Ok(())
}

fn append_new(
    v1: &V1Store,
    journal_name: &'static str,
    events: &[V1Event],
    journal: &mut kammi_store::Journal,
) -> Result<StreamSync> {
    let mut sync = StreamSync {
        v1_seq: events.len() as u64,
        v1_head: events.last().map(|e| e.event_id),
        already_present: journal.seq(),
        appended: 0,
    };
    for chunk in events[journal.seq() as usize..].chunks(EVENT_BATCH) {
        let payloads: Vec<Vec<u8>> = chunk
            .iter()
            .map(|e| v1.read_object(&e.payload_artifact()))
            .collect::<std::result::Result<_, _>>()?;
        let batch: Vec<NewEvent> = chunk
            .iter()
            .zip(&payloads)
            .map(|(e, p)| NewEvent {
                event: &e.raw,
                payload: p,
            })
            .collect();
        journal.append_batch(&batch)?;
        sync.appended += chunk.len() as u64;
    }
    if journal.head() != sync.v1_head.unwrap_or(Sha256Id::ZERO) {
        let seq = journal.seq();
        return Err(MigrateError::Diverged {
            journal: journal_name,
            seq,
        });
    }
    Ok(sync)
}

fn write_genesis(store: &Store, v1: &V1Store, report: &SyncReport) -> Result<()> {
    let head = |h: Option<Sha256Id>| h.map_or(serde_json::Value::Null, |h| json!(h.to_string()));
    let record = canonical(&json!({
        "schema": "KAMMI_V1_IMPORT_V1",
        "v1_root": v1.root().to_string_lossy(),
        "main": {"seq": report.main.v1_seq, "head": head(report.main.v1_head)},
        "memory": {"seq": report.memory.v1_seq, "head": head(report.memory.v1_head)},
        "v1_objects": report.v1_objects,
    }))?;
    let dir = store.root().join("genesis");
    fs::create_dir_all(&dir).map_err(io(&dir))?;
    let temp = dir.join("v1-import.json.tmp");
    let target = dir.join("v1-import.json");
    {
        let mut file = File::create(&temp).map_err(io(&temp))?;
        file.write_all(&record).map_err(io(&temp))?;
        file.sync_all().map_err(io(&temp))?;
    }
    fs::rename(&temp, &target).map_err(io(&target))?;
    Ok(())
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ExportReport {
    pub main_events: u64,
    pub memory_events: u64,
    pub objects: u64,
    pub object_bytes: u64,
}

/// Writes `store` into a new directory in the exact v1 layout.
pub fn export_v1(store: &Store, destination: &Path) -> Result<ExportReport> {
    if destination.exists() {
        return Err(MigrateError::DestinationExists(destination.to_path_buf()));
    }
    let mut report = ExportReport::default();
    let journal_dir = destination.join("journal");
    fs::create_dir_all(&journal_dir).map_err(io(&journal_dir))?;
    report.main_events = write_v1_journal(&store.main, &journal_dir.join("events.log"))?;
    if store.memory.seq() > 0 {
        let memory_dir = destination.join("memory").join("journal");
        fs::create_dir_all(&memory_dir).map_err(io(&memory_dir))?;
        report.memory_events = write_v1_journal(&store.memory, &memory_dir.join("events.log"))?;
    }
    let mut ids: HashSet<Sha256Id> = store.objects.ids()?.into_iter().collect();
    for journal in [&store.main, &store.memory] {
        for seq in 1..=journal.seq() {
            ids.insert(Sha256Id(journal.record(seq)?.payload_id));
        }
    }
    let mut ids: Vec<Sha256Id> = ids.into_iter().collect();
    ids.sort_unstable();
    for id in ids {
        let text = id.to_string();
        let dir = destination.join("objects").join("sha256").join(&text[7..9]);
        fs::create_dir_all(&dir).map_err(io(&dir))?;
        let path = dir.join(&text[9..]);
        let mut out = BufWriter::new(
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&path)
                .map_err(io(&path))?,
        );
        if store.objects.contains(&id) {
            report.object_bytes += store.objects.copy_to(&id, &mut out)?;
        } else {
            let bytes = store
                .get_object(&id)?
                .ok_or(StoreError::ObjectMissing(id))?;
            out.write_all(&bytes).map_err(io(&path))?;
            report.object_bytes += bytes.len() as u64;
        }
        let file = out.into_inner().map_err(|e| MigrateError::Io {
            path: path.clone(),
            source: e.into_error(),
        })?;
        file.sync_all().map_err(io(&path))?;
        report.objects += 1;
    }
    Ok(report)
}

fn write_v1_journal(journal: &kammi_store::Journal, path: &Path) -> Result<u64> {
    let mut out = BufWriter::new(File::create(path).map_err(io(path))?);
    for seq in 1..=journal.seq() {
        let stored = journal.read(seq)?;
        out.write_all(&(stored.event.len() as u32).to_be_bytes())
            .map_err(io(path))?;
        out.write_all(&stored.event).map_err(io(path))?;
        out.write_all(raw_id(&stored.event).as_bytes())
            .map_err(io(path))?;
    }
    let file = out.into_inner().map_err(|e| MigrateError::Io {
        path: path.to_path_buf(),
        source: e.into_error(),
    })?;
    file.sync_all().map_err(io(path))?;
    Ok(journal.seq())
}

/// Byte-level comparison of two v1 stores: committed journal bytes must be identical and the
/// verified object sets equal. Returns (main bytes, memory bytes, objects) compared.
pub fn compare_v1(original: &V1Store, exported: &V1Store) -> Result<(u64, u64, usize)> {
    let main = compare_journal(
        "main",
        Some(original.main_journal()?),
        Some(exported.main_journal()?),
        &original.root().join("journal").join("events.log"),
        &exported.root().join("journal").join("events.log"),
    )?;
    let memory = compare_journal(
        "memory",
        original.memory_journal()?,
        exported.memory_journal()?,
        &original
            .root()
            .join("memory")
            .join("journal")
            .join("events.log"),
        &exported
            .root()
            .join("memory")
            .join("journal")
            .join("events.log"),
    )?;
    let ids_a = original.object_ids()?;
    let ids_b = exported.object_ids()?;
    if ids_a != ids_b {
        return Err(MigrateError::Diverged {
            journal: "objects",
            seq: 0,
        });
    }
    for id in &ids_b {
        if !exported.verify_object(id)? {
            return Err(StoreError::ObjectCorrupt(*id).into());
        }
    }
    Ok((main, memory, ids_b.len()))
}

fn compare_journal(
    name: &'static str,
    original: Option<kammi_v1::JournalReader>,
    exported: Option<kammi_v1::JournalReader>,
    original_path: &Path,
    exported_path: &Path,
) -> Result<u64> {
    let diverged = |seq| MigrateError::Diverged { journal: name, seq };
    let (mut a, mut b) = match (original, exported) {
        (None, None) => return Ok(0),
        (Some(mut a), None) => {
            // An exported store omits a journal that holds no events.
            return if a.read_all()?.is_empty() {
                Ok(0)
            } else {
                Err(diverged(1))
            };
        }
        (None, Some(_)) => return Err(diverged(1)),
        (Some(a), Some(b)) => (a, b),
    };
    let events_a = a.read_all()?;
    let events_b = b.read_all()?;
    if events_a.len() != events_b.len() {
        return Err(diverged(events_a.len().min(events_b.len()) as u64 + 1));
    }
    if let Some(x) = events_a
        .iter()
        .zip(&events_b)
        .find(|(x, y)| x.raw != y.raw || x.event_id != y.event_id)
    {
        return Err(diverged(x.0.seq));
    }
    let mut bytes_a = fs::read(original_path).map_err(io(original_path))?;
    bytes_a.truncate(a.committed_offset() as usize);
    let bytes_b = fs::read(exported_path).map_err(io(exported_path))?;
    if bytes_a != bytes_b {
        return Err(diverged(0));
    }
    Ok(bytes_a.len() as u64)
}
