use std::{
    fs::{File, OpenOptions},
    io::{self, BufWriter, Write},
    path::Path,
};

use memchr::memchr_iter;
use memmap2::MmapOptions;
use serde::{Serialize, de::DeserializeOwned};
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout, Unaligned};

use crate::model::{JOURNAL_VERSION, JournalEnvelope, JournalEvent};

const TASK_MAGIC: [u8; 4] = *b"RDC2";
const HEADER_BYTES: usize = 8;

#[derive(FromBytes, IntoBytes, KnownLayout, Immutable, Unaligned)]
#[repr(C)]
struct FileHeader {
    magic: [u8; 4],
    version_le: [u8; 2],
    reserved: [u8; 2],
}

impl FileHeader {
    fn new(magic: [u8; 4]) -> Self {
        Self {
            magic,
            version_le: JOURNAL_VERSION.to_le_bytes(),
            reserved: [0; 2],
        }
    }
}

#[derive(Debug)]
pub enum JournalError {
    Io(io::Error),
    Json(serde_json::Error),
    InvalidHeader,
    InvalidRecord,
    ChainMismatch { sequence: u64 },
}

impl std::fmt::Display for JournalError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(f, "journal I/O error: {error}"),
            Self::Json(error) => write!(f, "journal JSON error: {error}"),
            Self::InvalidHeader => f.write_str("invalid or unsupported journal header"),
            Self::InvalidRecord => f.write_str("invalid journal record framing"),
            Self::ChainMismatch { sequence } => {
                write!(f, "journal hash chain mismatch at {sequence}")
            }
        }
    }
}

impl std::error::Error for JournalError {}

impl From<io::Error> for JournalError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<serde_json::Error> for JournalError {
    fn from(value: serde_json::Error) -> Self {
        Self::Json(value)
    }
}

pub struct TaskJournal {
    writer: BufWriter<File>,
    next_sequence: u64,
    previous_hash: [u8; 32],
    bytes_written: u64,
}

impl TaskJournal {
    pub fn create(path: impl AsRef<Path>) -> Result<Self, JournalError> {
        let file = OpenOptions::new().write(true).create_new(true).open(path)?;
        let mut writer = BufWriter::with_capacity(16 * 1024, file);
        let header = FileHeader::new(TASK_MAGIC);
        writer.write_all(header.as_bytes())?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(Self {
            writer,
            next_sequence: 0,
            previous_hash: [0; 32],
            bytes_written: HEADER_BYTES as u64,
        })
    }

    pub fn open_append(
        path: impl AsRef<Path>,
        prior: &[JournalEnvelope],
    ) -> Result<Self, JournalError> {
        let file = OpenOptions::new().append(true).open(path)?;
        let bytes_written = file.metadata()?.len();
        let (next_sequence, previous_hash) = prior
            .last()
            .map_or((0, [0; 32]), |last| (last.sequence + 1, last.hash));
        Ok(Self {
            writer: BufWriter::with_capacity(16 * 1024, file),
            next_sequence,
            previous_hash,
            bytes_written,
        })
    }

    pub fn append(&mut self, event: JournalEvent) -> Result<JournalEnvelope, JournalError> {
        let envelope = JournalEnvelope {
            sequence: self.next_sequence,
            previous_hash: self.previous_hash,
            hash: event_hash(self.next_sequence, self.previous_hash, &event)?,
            event,
        };
        serde_json::to_writer(&mut self.writer, &envelope)?;
        self.writer.write_all(b"\n")?;
        self.writer.flush()?;
        self.writer.get_ref().sync_data()?;
        self.bytes_written = self.writer.get_ref().metadata()?.len();
        self.next_sequence += 1;
        self.previous_hash = envelope.hash;
        Ok(envelope)
    }

    pub fn last_hash(&self) -> Option<[u8; 32]> {
        (self.next_sequence != 0).then_some(self.previous_hash)
    }

    pub fn bytes_written(&self) -> u64 {
        self.bytes_written
    }

    pub fn flush_close(self) -> Result<(), JournalError> {
        let mut writer = self.writer;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(())
    }
}

pub fn event_hash(
    sequence: u64,
    previous_hash: [u8; 32],
    event: &JournalEvent,
) -> Result<[u8; 32], JournalError> {
    let event_bytes = serde_json::to_vec(event)?;
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"RDC-EXPERIMENT-002-JOURNAL-V2\0");
    hasher.update(&sequence.to_le_bytes());
    hasher.update(&previous_hash);
    hasher.update(&event_bytes);
    Ok(*hasher.finalize().as_bytes())
}

/// Reads and validates a task journal using a read-only memory map.
///
/// # Safety
/// The caller must ensure that no other thread or process mutates the file while it is mapped.
pub unsafe fn read_task_journal_mmap(
    path: impl AsRef<Path>,
) -> Result<Vec<JournalEnvelope>, JournalError> {
    // SAFETY: the caller guarantees the mapped journal remains immutable during this read.
    let records = unsafe { read_framed_json_mmap::<JournalEnvelope>(path, TASK_MAGIC)? };
    let mut previous_hash = [0; 32];
    for (index, record) in records.iter().enumerate() {
        let sequence = index as u64;
        if record.sequence != sequence
            || record.previous_hash != previous_hash
            || event_hash(sequence, previous_hash, &record.event)? != record.hash
        {
            return Err(JournalError::ChainMismatch { sequence });
        }
        previous_hash = record.hash;
    }
    Ok(records)
}

/// Reads JSON rows after a fixed zero-copy header.
///
/// # Safety
/// The caller must ensure that no other thread or process mutates the file while it is mapped.
pub(crate) unsafe fn read_framed_json_mmap<T: DeserializeOwned>(
    path: impl AsRef<Path>,
    expected_magic: [u8; 4],
) -> Result<Vec<T>, JournalError> {
    let file = File::open(path)?;
    if file.metadata()?.len() < HEADER_BYTES as u64 {
        return Err(JournalError::InvalidHeader);
    }
    // SAFETY: delegated to the caller's immutable-file guarantee.
    let map = unsafe { MmapOptions::new().map(&file)? };
    let (header, body) =
        FileHeader::ref_from_prefix(&map).map_err(|_| JournalError::InvalidHeader)?;
    if header.magic != expected_magic
        || header.version_le != JOURNAL_VERSION.to_le_bytes()
        || header.reserved != [0; 2]
    {
        return Err(JournalError::InvalidHeader);
    }
    let mut result = Vec::new();
    let mut start = 0usize;
    for end in memchr_iter(b'\n', body) {
        if end == start {
            return Err(JournalError::InvalidRecord);
        }
        result.push(serde_json::from_slice(&body[start..end])?);
        start = end + 1;
    }
    if start != body.len() {
        return Err(JournalError::InvalidRecord);
    }
    Ok(result)
}

pub(crate) fn write_json_line<T: Serialize>(
    writer: &mut BufWriter<File>,
    value: &T,
) -> Result<u64, JournalError> {
    serde_json::to_writer(&mut *writer, value)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    writer.get_ref().sync_data()?;
    Ok(writer.get_ref().metadata()?.len())
}
