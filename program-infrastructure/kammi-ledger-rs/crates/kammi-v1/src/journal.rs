//! Incremental, validating reader for v1 `events.log` files.

use std::fs::File;
use std::path::{Path, PathBuf};

use hashbrown::HashSet;
use kammi_jcs::{canonical, raw_id, strict_json, typed_id_of_canonical, Domain, Sha256Id, Value};

use crate::vocabulary::{is_event_type, EVENT_FIELDS, EVENT_SCHEMA};
use crate::{V1Error, MAX_EVENT_BYTES};

/// One committed event, validated exactly as `journal.py:_scan` validates it.
#[derive(Debug, Clone)]
pub struct V1Event {
    pub seq: u64,
    pub event_id: Sha256Id,
    /// Byte offset of the frame header.
    pub offset: u64,
    /// The exact canonical JCS bytes of the event envelope.
    pub raw: Box<[u8]>,
    pub event: Value,
}

impl V1Event {
    pub fn kind(&self) -> &str {
        self.event["type"].as_str().expect("validated type")
    }

    pub fn payload_artifact(&self) -> Sha256Id {
        Sha256Id::parse(self.event["payload_artifact"].as_str().expect("validated"))
            .expect("validated id")
    }

    pub fn request_id(&self) -> &str {
        self.event["request_id"]
            .as_str()
            .expect("validated request_id")
    }

    pub fn actor(&self) -> &str {
        self.event["actor"].as_str().expect("validated actor")
    }

    pub fn utc(&self) -> &str {
        self.event["utc"].as_str().expect("validated utc")
    }

    /// Bytes occupied by the frame on disk (header, body and checksum).
    pub fn frame_len(&self) -> u64 {
        4 + self.raw.len() as u64 + 32
    }
}

/// Reads committed frames in order and remembers where it stopped, so it can be polled
/// while the Python daemon keeps appending.
pub struct JournalReader {
    path: PathBuf,
    file: File,
    offset: u64,
    seq: u64,
    head: Sha256Id,
    /// 128-bit digests of every request ID seen, for Python's duplicate-request check.
    requests: HashSet<[u8; 16]>,
}

impl JournalReader {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, V1Error> {
        let path = path.as_ref().to_path_buf();
        // std opens with FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE on Windows,
        // so the owning writer can keep appending, truncating and renaming.
        let file = File::open(&path).map_err(|e| V1Error::io(&path, e))?;
        Ok(JournalReader {
            path,
            file,
            offset: 0,
            seq: 0,
            head: Sha256Id::ZERO,
            requests: HashSet::new(),
        })
    }

    /// Offset just past the last committed frame read so far.
    pub fn committed_offset(&self) -> u64 {
        self.offset
    }

    /// Sequence number of the last committed event read so far.
    pub fn seq(&self) -> u64 {
        self.seq
    }

    /// Event ID of the last committed event read so far, or the zero digest.
    pub fn head(&self) -> Sha256Id {
        self.head
    }

    /// Returns the next committed event, or `None` when no complete frame is available yet.
    /// A torn tail leaves the reader where it was, so a later call picks the frame up once the
    /// writer finishes it.
    pub fn next_event(&mut self) -> Result<Option<V1Event>, V1Error> {
        let length_on_disk = self
            .file
            .metadata()
            .map_err(|e| V1Error::io(&self.path, e))?
            .len();
        if length_on_disk < self.offset {
            return Err(V1Error::HistoryRewritten {
                expected: self.offset,
                actual: length_on_disk,
            });
        }
        let available = length_on_disk - self.offset;
        if available < 4 {
            return Ok(None);
        }
        let mut header = [0u8; 4];
        read_exact_at(&self.file, &mut header, self.offset)
            .map_err(|e| V1Error::io(&self.path, e))?;
        let length = u64::from(u32::from_be_bytes(header));
        if length == 0 || length > MAX_EVENT_BYTES as u64 {
            return Err(V1Error::FrameLength {
                offset: self.offset,
                length,
            });
        }
        if available < 4 + length + 32 {
            return Ok(None);
        }
        let mut frame = vec![0u8; (length + 32) as usize];
        read_exact_at(&self.file, &mut frame, self.offset + 4)
            .map_err(|e| V1Error::io(&self.path, e))?;
        let (raw, checksum) = frame.split_at(length as usize);
        let offset = self.offset;
        if raw_id(raw).as_bytes().as_slice() != checksum {
            return Err(V1Error::Checksum { offset });
        }
        let event = strict_json(raw).map_err(|source| V1Error::Json { offset, source })?;
        validate_envelope(&event, offset)?;
        let request = request_digest(event["request_id"].as_str().expect("validated"));
        if self.requests.contains(&request) {
            return Err(V1Error::DuplicateRequest { offset });
        }
        if canonical(&event)
            .map_err(|source| V1Error::Json { offset, source })?
            .as_slice()
            != raw
        {
            return Err(V1Error::NonCanonical { offset });
        }
        let seq = self.seq + 1;
        let prev = event["prev"].as_str().expect("validated");
        if event["seq"].as_u64() != Some(seq) || prev != self.head.to_string() {
            return Err(V1Error::Chain { offset });
        }
        let event_id = typed_id_of_canonical(Domain::Event, raw);
        self.requests.insert(request);
        self.seq = seq;
        self.head = event_id;
        self.offset += 4 + length + 32;
        frame.truncate(length as usize);
        Ok(Some(V1Event {
            seq,
            event_id,
            offset,
            raw: frame.into_boxed_slice(),
            event,
        }))
    }

    /// Reads every currently committed event.
    pub fn read_all(&mut self) -> Result<Vec<V1Event>, V1Error> {
        let mut events = Vec::new();
        while let Some(event) = self.next_event()? {
            events.push(event);
        }
        Ok(events)
    }
}

fn request_digest(request_id: &str) -> [u8; 16] {
    let digest = raw_id(request_id.as_bytes());
    digest.as_bytes()[..16].try_into().expect("16 bytes")
}

fn validate_envelope(event: &Value, offset: u64) -> Result<(), V1Error> {
    let fail = |reason| V1Error::Vocabulary { offset, reason };
    let object = event
        .as_object()
        .ok_or_else(|| fail("event is not an object"))?;
    if object.len() != EVENT_FIELDS.len()
        || !EVENT_FIELDS.iter().all(|key| object.contains_key(*key))
    {
        return Err(fail("event field set"));
    }
    if object["schema"].as_str() != Some(EVENT_SCHEMA) {
        return Err(fail("event schema"));
    }
    if !object["type"].as_str().is_some_and(is_event_type) {
        return Err(fail("event type"));
    }
    if object["request_id"].as_str().is_none_or(str::is_empty) {
        return Err(fail("request_id"));
    }
    for key in ["actor", "payload_artifact", "prev", "utc"] {
        if !object[key].is_string() {
            return Err(fail("envelope string field"));
        }
    }
    for key in ["payload_artifact", "prev"] {
        Sha256Id::parse(object[key].as_str().expect("string"))
            .map_err(|_| fail("envelope identity"))?;
    }
    if object["seq"].as_u64().is_none() {
        return Err(fail("seq"));
    }
    Ok(())
}

#[cfg(windows)]
fn read_exact_at(file: &File, mut buffer: &mut [u8], mut offset: u64) -> std::io::Result<()> {
    use std::os::windows::fs::FileExt;
    while !buffer.is_empty() {
        let read = file.seek_read(buffer, offset)?;
        if read == 0 {
            return Err(std::io::ErrorKind::UnexpectedEof.into());
        }
        buffer = &mut buffer[read..];
        offset += read as u64;
    }
    Ok(())
}

#[cfg(unix)]
fn read_exact_at(file: &File, buffer: &mut [u8], offset: u64) -> std::io::Result<()> {
    use std::os::unix::fs::FileExt;
    file.read_exact_at(buffer, offset)
}
