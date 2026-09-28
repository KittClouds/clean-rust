use std::{
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::Path,
};

use hashbrown::HashMap;
use serde::{Deserialize, Serialize};
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout, Unaligned};

use rdc_experiment_001::Action;

use crate::journal::{JournalError, read_framed_json_mmap, write_json_line};
use crate::model::JOURNAL_VERSION;

const ACTION_MAGIC: [u8; 4] = *b"RDA2";

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct ActionId(pub [u8; 16]);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
struct ActionEffectRow {
    action_id: ActionId,
    action: u8,
    effect_index: u64,
    previous_hash: [u8; 32],
    hash: [u8; 32],
}

#[derive(FromBytes, IntoBytes, KnownLayout, Immutable, Unaligned)]
#[repr(C)]
struct ActionHeader {
    magic: [u8; 4],
    version_le: [u8; 2],
    reserved: [u8; 2],
}

impl ActionHeader {
    fn new() -> Self {
        Self {
            magic: ACTION_MAGIC,
            version_le: JOURNAL_VERSION.to_le_bytes(),
            reserved: [0; 2],
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ActionResult {
    pub effect_index: u64,
    pub idempotent_reuse: bool,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ActionSimulatorStats {
    pub unique_effects: usize,
    pub invocations: usize,
    pub idempotent_reuses: usize,
    pub duplicate_effects: usize,
}

#[derive(Debug)]
pub enum ActionSimulatorError {
    Io(std::io::Error),
    Journal(JournalError),
    InvalidLedger,
    ActionIdConflict,
}

impl std::fmt::Display for ActionSimulatorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(f, "action simulator I/O error: {error}"),
            Self::Journal(error) => write!(f, "action ledger error: {error}"),
            Self::InvalidLedger => f.write_str("invalid action effect ledger"),
            Self::ActionIdConflict => f.write_str("action ID was reused for a different action"),
        }
    }
}

impl std::error::Error for ActionSimulatorError {}

impl From<std::io::Error> for ActionSimulatorError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<JournalError> for ActionSimulatorError {
    fn from(value: JournalError) -> Self {
        Self::Journal(value)
    }
}

pub struct ActionSimulator {
    writer: BufWriter<File>,
    effects: HashMap<ActionId, ActionEffectRow>,
    previous_hash: [u8; 32],
    invocations: usize,
    idempotent_reuses: usize,
    duplicate_effects: usize,
    bytes_written: u64,
}

impl ActionSimulator {
    pub fn create(path: impl AsRef<Path>) -> Result<Self, ActionSimulatorError> {
        let file = OpenOptions::new().write(true).create_new(true).open(path)?;
        let mut writer = BufWriter::with_capacity(8 * 1024, file);
        writer.write_all(ActionHeader::new().as_bytes())?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(Self {
            writer,
            effects: HashMap::with_capacity(16),
            previous_hash: [0; 32],
            invocations: 0,
            idempotent_reuses: 0,
            duplicate_effects: 0,
            bytes_written: 8,
        })
    }

    /// Opens a durable effect ledger after a simulated process restart.
    ///
    /// # Safety
    /// No process may mutate the action ledger while it is being mapped for recovery.
    pub unsafe fn resume(path: impl AsRef<Path>) -> Result<Self, ActionSimulatorError> {
        // SAFETY: this method delegates the no-concurrent-writer condition to its caller.
        let rows =
            unsafe { read_framed_json_mmap::<ActionEffectRow>(path.as_ref(), ACTION_MAGIC)? };
        let mut effects = HashMap::with_capacity(rows.len());
        let mut previous_hash = [0; 32];
        for (index, row) in rows.iter().enumerate() {
            if row.effect_index != index as u64 + 1
                || row.previous_hash != previous_hash
                || row.hash
                    != effect_hash(row.action_id, row.action, row.effect_index, previous_hash)
                || Action::try_from(row.action).is_err()
                || effects.insert(row.action_id, *row).is_some()
            {
                return Err(ActionSimulatorError::InvalidLedger);
            }
            previous_hash = row.hash;
        }
        let file = OpenOptions::new().append(true).open(path)?;
        let bytes_written = file.metadata()?.len();
        Ok(Self {
            writer: BufWriter::with_capacity(8 * 1024, file),
            effects,
            previous_hash,
            invocations: 0,
            idempotent_reuses: 0,
            duplicate_effects: 0,
            bytes_written,
        })
    }

    /// Records one simulated external effect durably under an idempotency key.
    pub fn perform(
        &mut self,
        action_id: ActionId,
        action: Action,
    ) -> Result<ActionResult, ActionSimulatorError> {
        self.invocations += 1;
        if let Some(existing) = self.effects.get(&action_id) {
            if existing.action != action as u8 {
                return Err(ActionSimulatorError::ActionIdConflict);
            }
            self.idempotent_reuses += 1;
            return Ok(ActionResult {
                effect_index: existing.effect_index,
                idempotent_reuse: true,
            });
        }

        let effect_index = self.effects.len() as u64 + 1;
        let row = ActionEffectRow {
            action_id,
            action: action as u8,
            effect_index,
            previous_hash: self.previous_hash,
            hash: effect_hash(action_id, action as u8, effect_index, self.previous_hash),
        };
        self.bytes_written = write_json_line(&mut self.writer, &row)
            .map_err(|error| ActionSimulatorError::Journal(error))?;
        self.effects.insert(action_id, row);
        self.previous_hash = row.hash;
        Ok(ActionResult {
            effect_index,
            idempotent_reuse: false,
        })
    }

    pub fn stats(&self) -> ActionSimulatorStats {
        ActionSimulatorStats {
            unique_effects: self.effects.len(),
            invocations: self.invocations,
            idempotent_reuses: self.idempotent_reuses,
            duplicate_effects: self.duplicate_effects,
        }
    }

    pub fn bytes_written(&self) -> u64 {
        self.bytes_written
    }

    pub fn effect_for(&self, id: ActionId) -> Option<(Action, u64)> {
        self.effects.get(&id).and_then(|row| {
            Action::try_from(row.action)
                .ok()
                .map(|action| (action, row.effect_index))
        })
    }

    pub fn flush_close(self) -> Result<(), ActionSimulatorError> {
        let mut writer = self.writer;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(())
    }
}

fn effect_hash(
    action_id: ActionId,
    action: u8,
    effect_index: u64,
    previous_hash: [u8; 32],
) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"RDC-EXPERIMENT-002-ACTION-EFFECT-V1\0");
    hasher.update(&previous_hash);
    hasher.update(&action_id.0);
    hasher.update(&[action]);
    hasher.update(&effect_index.to_le_bytes());
    *hasher.finalize().as_bytes()
}
