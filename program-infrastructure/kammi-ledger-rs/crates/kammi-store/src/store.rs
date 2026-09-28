//! The v2 store: one writer, two journals, packed objects and checkpoints.

use std::fs;
use std::path::{Path, PathBuf};

use kammi_jcs::{canonical, strict_json, Sha256Id};
use serde_json::json;

use crate::checkpoint::{Checkpoint, Checkpoints, Position};
use crate::durable;
use crate::error::{io, Result, StoreError};
use crate::journal::{Journal, JournalOptions, JournalReport};
use crate::lock::StoreLock;
use crate::objects::{ObjectOptions, ObjectReport, Objects};

pub const STORE_SCHEMA: &str = "KAMMI_STORE_V2";

#[derive(Debug, Clone, Default)]
pub struct StoreOptions {
    pub journal: JournalOptions,
    pub objects: ObjectOptions,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifyReport {
    pub main: JournalReport,
    pub memory: JournalReport,
    pub objects: ObjectReport,
    pub checkpoint: Option<PathBuf>,
    pub rejected_checkpoints: Vec<PathBuf>,
}

/// What opening had to repair. Every item is also preserved on disk under `recovery/`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Recovery {
    pub journal_tails: Vec<PathBuf>,
    pub object_tails: Vec<PathBuf>,
}

pub struct Store {
    root: PathBuf,
    pub main: Journal,
    pub memory: Journal,
    pub objects: Objects,
    pub checkpoints: Checkpoints,
    _lock: StoreLock,
}

impl Store {
    /// Creates a new store in an empty (or absent) directory.
    pub fn create(root: &Path, opts: StoreOptions) -> Result<Store> {
        if root.exists() && fs::read_dir(root).map_err(io(root))?.next().is_some() {
            return Err(StoreError::AlreadyExists(root.to_path_buf()));
        }
        durable::create_dir_all(root)?;
        let marker = canonical(&json!({"schema": STORE_SCHEMA, "version": 1}))?;
        durable::publish(&root.join("staging"), &root.join("STORE.json"), &marker)?;
        Store::open(root, opts)
    }

    /// Opens an existing store, taking the writer lock and repairing torn tails.
    pub fn open(root: &Path, opts: StoreOptions) -> Result<Store> {
        let marker = fs::read(root.join("STORE.json"))
            .map_err(|_| StoreError::NotAStore(root.to_path_buf()))?;
        let value = strict_json(&marker).map_err(|_| StoreError::NotAStore(root.to_path_buf()))?;
        if value["schema"].as_str() != Some(STORE_SCHEMA) {
            return Err(StoreError::NotAStore(root.to_path_buf()));
        }
        let lock = StoreLock::acquire(root)?;
        let main = Journal::open(
            &root.join("journal").join("main"),
            "main",
            opts.journal.clone(),
        )?;
        let memory = Journal::open(
            &root.join("journal").join("memory"),
            "memory",
            opts.journal.clone(),
        )?;
        let objects = Objects::open(&root.join("objects"), opts.objects.clone())?;
        let checkpoints = Checkpoints::open(&root.join("checkpoints"))?;
        Ok(Store {
            root: root.to_path_buf(),
            main,
            memory,
            objects,
            checkpoints,
            _lock: lock,
        })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn recovery(&self) -> Recovery {
        Recovery {
            journal_tails: self
                .main
                .recovered_tails()
                .iter()
                .chain(self.memory.recovered_tails())
                .cloned()
                .collect(),
            object_tails: self.objects.recovered_tails().to_vec(),
        }
    }

    /// An object by identity: packed or loose objects first, then journal payloads.
    pub fn get_object(&self, id: &Sha256Id) -> Result<Option<Vec<u8>>> {
        if let Some(bytes) = self.objects.get(id)? {
            return Ok(Some(bytes));
        }
        if let Some(bytes) = self.main.payload(id)? {
            return Ok(Some(bytes));
        }
        self.memory.payload(id)
    }

    pub fn contains_object(&self, id: &Sha256Id) -> bool {
        self.objects.contains(id)
            || self.main.contains_payload(id)
            || self.memory.contains_payload(id)
    }

    fn position(journal: &Journal) -> Position {
        Position {
            seq: journal.seq(),
            head: journal.head(),
        }
    }

    fn bound(&self, main: &Position, memory: &Position) -> bool {
        let check = |journal: &Journal, position: &Position| {
            if position.seq == 0 {
                position.head == Sha256Id::ZERO
            } else {
                journal
                    .record(position.seq)
                    .is_ok_and(|r| r.event_id == position.head.0)
            }
        };
        check(&self.main, main) && check(&self.memory, memory)
    }

    /// Compacts every lookup index and publishes a checkpoint of caller-supplied state bound
    /// to the current heads of both journals.
    pub fn checkpoint(&mut self, tag: &str, state: &[u8]) -> Result<PathBuf> {
        self.main.compact_indexes()?;
        self.memory.compact_indexes()?;
        self.objects.compact_index()?;
        self.checkpoints.write(
            tag,
            Self::position(&self.main),
            Self::position(&self.memory),
            state,
        )
    }

    /// The newest checkpoint still bound to this journal history.
    pub fn latest_checkpoint(&self) -> Result<(Option<Checkpoint>, Vec<PathBuf>)> {
        self.checkpoints
            .latest(|main, memory| self.bound(main, memory))
    }

    /// Full re-verification of every authoritative byte and every derived index.
    pub fn verify_deep(&self) -> Result<VerifyReport> {
        let main = self.main.verify_deep()?;
        let memory = self.memory.verify_deep()?;
        let objects = self.objects.verify_deep()?;
        let (checkpoint, rejected) = self.latest_checkpoint()?;
        Ok(VerifyReport {
            main,
            memory,
            objects,
            checkpoint: checkpoint.map(|c| c.path),
            rejected_checkpoints: rejected,
        })
    }
}
