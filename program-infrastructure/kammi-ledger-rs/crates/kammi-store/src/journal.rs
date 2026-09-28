//! Hash-chained event journal stored as append-only segments with inline payloads.

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use hashbrown::HashSet;
use kammi_jcs::{canonical, raw_id, strict_json, typed_id_of_canonical, Domain, Sha256Id, Value};
use memmap2::Mmap;

use crate::durable::{self, read_exact_at};
use crate::error::{corrupt, io, Result, StoreError};
use crate::fault;
use crate::frame::{self, Decoded, SEGMENT_HEADER_LEN};
use crate::idx::{self, request_key, IdxRecord, IdxStorage, IDX_RECORD_LEN};
use crate::keyindex::{remove_if_exists, KeyIndex, SortedTable};

/// Keys of every event envelope, in canonical order (`vocabulary.py:EVENT_FIELDS`).
pub const EVENT_FIELDS: [&str; 8] = [
    "actor",
    "payload_artifact",
    "prev",
    "request_id",
    "schema",
    "seq",
    "type",
    "utc",
];
pub const EVENT_SCHEMA: &str = "KAMMI_EVENT_V1";

#[derive(Debug, Clone)]
pub struct JournalOptions {
    /// A segment is sealed once appending would take it past this size.
    pub max_segment_bytes: u64,
}

impl Default for JournalOptions {
    fn default() -> Self {
        JournalOptions {
            max_segment_bytes: 64 * 1024 * 1024,
        }
    }
}

/// An event to append: its exact canonical envelope and the payload it names.
#[derive(Debug, Clone, Copy)]
pub struct NewEvent<'a> {
    pub event: &'a [u8],
    pub payload: &'a [u8],
}

/// A committed event read back from disk, with both hashes re-verified.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StoredEvent {
    pub seq: u64,
    pub event_id: Sha256Id,
    pub payload_id: Sha256Id,
    pub event: Vec<u8>,
    pub payload: Vec<u8>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct JournalReport {
    pub events: u64,
    pub segments: usize,
    pub bytes: u64,
    pub head: Option<Sha256Id>,
}

struct Segment {
    number: u32,
    first_seq: u64,
    path: PathBuf,
    idx_path: PathBuf,
    file: File,
    idx: IdxStorage,
    end: u64,
}

pub struct Journal {
    name: String,
    dir: PathBuf,
    opts: JournalOptions,
    segments: Vec<Segment>,
    writer: Option<File>,
    idx_writer: Option<File>,
    seq: u64,
    head: Sha256Id,
    requests: KeyIndex<16>,
    payloads: KeyIndex<32>,
    events: KeyIndex<32>,
    poisoned: bool,
    recovered: Vec<PathBuf>,
}

/// Why an event failed validation, before it is mapped to an append or a corruption error.
enum EventFault {
    Json(kammi_jcs::JcsError),
    Shape(&'static str),
    Chain,
    Payload(Sha256Id),
}

struct Validated {
    record: IdxRecord,
    request_id: String,
}

fn validate_event(
    event: &[u8],
    payload: &[u8],
    expected_seq: u64,
    prev: Sha256Id,
) -> std::result::Result<Validated, EventFault> {
    let value = strict_json(event).map_err(EventFault::Json)?;
    if canonical(&value).map_err(EventFault::Json)? != event {
        return Err(EventFault::Shape("event bytes are not canonical"));
    }
    let object = value
        .as_object()
        .ok_or(EventFault::Shape("event is not an object"))?;
    if object.len() != EVENT_FIELDS.len() || !EVENT_FIELDS.iter().all(|k| object.contains_key(*k)) {
        return Err(EventFault::Shape("event field set"));
    }
    if object["schema"].as_str() != Some(EVENT_SCHEMA) {
        return Err(EventFault::Shape("event schema"));
    }
    for key in ["actor", "type", "utc"] {
        if !object[key].is_string() {
            return Err(EventFault::Shape("envelope string field"));
        }
    }
    let request_id = match &object["request_id"] {
        Value::String(r) if !r.is_empty() => r.clone(),
        _ => return Err(EventFault::Shape("request_id")),
    };
    let seq = object["seq"].as_u64().ok_or(EventFault::Shape("seq"))?;
    let prev_text = object["prev"].as_str().ok_or(EventFault::Shape("prev"))?;
    if seq != expected_seq || prev_text != prev.to_string() {
        return Err(EventFault::Chain);
    }
    let payload_text = object["payload_artifact"]
        .as_str()
        .ok_or(EventFault::Shape("payload_artifact"))?;
    let named = Sha256Id::parse(payload_text).map_err(|_| EventFault::Shape("payload_artifact"))?;
    if raw_id(payload) != named {
        return Err(EventFault::Payload(named));
    }
    Ok(Validated {
        record: IdxRecord {
            seq,
            offset: 0,
            frame_len: frame::frame_len(event.len(), payload.len()) as u32,
            reserved: 0,
            event_id: typed_id_of_canonical(Domain::Event, event).0,
            payload_id: named.0,
            request: request_key(&request_id),
        },
        request_id,
    })
}

enum ScanEnd {
    Clean,
    Torn(u64),
}

impl Journal {
    fn segment_path(dir: &Path, number: u32) -> PathBuf {
        dir.join(format!("seg-{number:08}.seg"))
    }

    fn idx_path(dir: &Path, number: u32) -> PathBuf {
        dir.join(format!("seg-{number:08}.idx"))
    }

    fn staging(&self) -> PathBuf {
        self.dir.join("staging")
    }

    /// Opens (or creates) the journal in `dir`, repairing a torn tail of the active segment
    /// and rebuilding any missing or inconsistent index file.
    pub fn open(dir: &Path, name: &str, opts: JournalOptions) -> Result<Journal> {
        durable::create_dir_all(dir)?;
        let mut numbers = Vec::new();
        for entry in fs::read_dir(dir).map_err(io(dir))? {
            let entry = entry.map_err(io(dir))?;
            let file_name = entry.file_name().to_string_lossy().into_owned();
            if let Some(number) = file_name
                .strip_prefix("seg-")
                .and_then(|n| n.strip_suffix(".seg"))
                .and_then(|n| n.parse::<u32>().ok())
            {
                numbers.push(number);
            }
        }
        numbers.sort_unstable();
        for (index, number) in numbers.iter().enumerate() {
            if *number as usize != index + 1 {
                return Err(corrupt(
                    "journal",
                    dir,
                    0,
                    "segment numbers are not contiguous",
                ));
            }
        }
        let mut journal = Journal {
            name: name.to_string(),
            dir: dir.to_path_buf(),
            opts,
            segments: Vec::new(),
            writer: None,
            idx_writer: None,
            seq: 0,
            head: Sha256Id::ZERO,
            requests: KeyIndex::default(),
            payloads: KeyIndex::default(),
            events: KeyIndex::default(),
            poisoned: false,
            recovered: Vec::new(),
        };
        if numbers.is_empty() {
            journal.create_segment(1)?;
        } else {
            let last = numbers.len() - 1;
            for (index, number) in numbers.into_iter().enumerate() {
                journal.load_segment(number, index == last)?;
            }
        }
        journal.open_writers()?;
        journal.load_key_indexes()?;
        Ok(journal)
    }

    fn create_segment(&mut self, number: u32) -> Result<()> {
        let first_seq = self.seq + 1;
        let path = Self::segment_path(&self.dir, number);
        let idx_path = Self::idx_path(&self.dir, number);
        {
            let mut file = OpenOptions::new()
                .write(true)
                .create(true)
                .truncate(true)
                .open(&path)
                .map_err(io(&path))?;
            file.write_all(&frame::segment_header(first_seq))
                .map_err(io(&path))?;
            durable::sync(&file, &path)?;
        }
        fs::write(&idx_path, idx::idx_header(first_seq)).map_err(io(&idx_path))?;
        durable::sync_dir(&self.dir)?;
        let file = File::open(&path).map_err(io(&path))?;
        self.segments.push(Segment {
            number,
            first_seq,
            path,
            idx_path,
            file,
            idx: IdxStorage::Owned(Vec::new()),
            end: SEGMENT_HEADER_LEN,
        });
        fault::hit("journal.after_rollover");
        Ok(())
    }

    fn load_segment(&mut self, number: u32, last: bool) -> Result<()> {
        let path = Self::segment_path(&self.dir, number);
        let idx_path = Self::idx_path(&self.dir, number);
        let file = OpenOptions::new()
            .read(true)
            .write(last)
            .open(&path)
            .map_err(io(&path))?;
        let length = file.metadata().map_err(io(&path))?.len();
        let first_seq = self.seq + 1;
        if length < SEGMENT_HEADER_LEN {
            // A crash while a new segment was being created: it holds no frames yet.
            if !last {
                return Err(corrupt("journal segment", &path, 0, "truncated header"));
            }
            drop(file);
            fs::remove_file(&path).map_err(io(&path))?;
            let _ = fs::remove_file(&idx_path);
            return self.create_segment(number);
        }
        let mut header = [0u8; 16];
        read_exact_at(&file, &mut header, 0).map_err(io(&path))?;
        match frame::parse_segment_header(&header) {
            Some(seq) if seq == first_seq => {}
            Some(_) => {
                return Err(corrupt(
                    "journal segment",
                    &path,
                    0,
                    "first sequence does not continue the chain",
                ))
            }
            None => return Err(corrupt("journal segment", &path, 0, "bad segment header")),
        }

        // An index is trusted only if it is whole (no torn trailing record, which would
        // misalign later appends), structurally continuous, and its last record matches the
        // frame on disk. Anything else is rebuilt from the segment.
        let on_disk = fs::read(&idx_path)
            .ok()
            .filter(|bytes| {
                bytes.len() >= idx::IDX_HEADER_LEN
                    && (bytes.len() - idx::IDX_HEADER_LEN).is_multiple_of(IDX_RECORD_LEN)
            })
            .and_then(|bytes| idx::parse_records(&bytes, first_seq))
            .filter(|records| structurally_valid(records, first_seq, length));
        let (mut records, idx_ok) = match on_disk {
            Some(records)
                if records.is_empty() || self.frame_matches(&file, records.last().unwrap()) =>
            {
                (records, true)
            }
            _ => (Vec::new(), false),
        };
        let scan_from = records
            .last()
            .map_or(SEGMENT_HEADER_LEN, |r| r.offset + u64::from(r.frame_len));
        let mut seq = records.last().map_or(self.seq, |r| r.seq);
        let mut head = records.last().map_or(self.head, |r| Sha256Id(r.event_id));
        let before = records.len();
        let needs_scan = last || records.is_empty() && length > SEGMENT_HEADER_LEN;
        let mut end = scan_from;
        if needs_scan {
            let mut tail = vec![0u8; (length - scan_from) as usize];
            read_exact_at(&file, &mut tail, scan_from).map_err(io(&path))?;
            let (found, scan_end) = scan(&path, &tail, scan_from, &mut seq, &mut head, last)?;
            records.extend(found);
            end = records
                .last()
                .map_or(SEGMENT_HEADER_LEN, |r| r.offset + u64::from(r.frame_len));
            if let ScanEnd::Torn(offset) = scan_end {
                let recovery = self.dir.join("recovery");
                if let Some(saved) = durable::quarantine_tail(&file, &path, offset, &recovery)? {
                    self.recovered.push(saved);
                }
            }
        } else if length != end {
            return Err(corrupt(
                "journal segment",
                &path,
                end,
                "sealed segment has bytes beyond its index",
            ));
        }
        if records.len() != before || !idx_ok {
            let mut bytes = idx::idx_header(first_seq).to_vec();
            bytes.extend_from_slice(bytemuck::cast_slice(&records));
            durable::publish(&self.staging(), &idx_path, &bytes)?;
        }
        self.seq = seq;
        self.head = head;
        let storage = if last {
            IdxStorage::Owned(records)
        } else {
            map_idx(&idx_path).unwrap_or(IdxStorage::Owned(records))
        };
        let read_file = File::open(&path).map_err(io(&path))?;
        self.segments.push(Segment {
            number,
            first_seq,
            path,
            idx_path,
            file: read_file,
            idx: storage,
            end,
        });
        Ok(())
    }

    /// Cheap consistency check of one indexed frame against the segment bytes.
    fn frame_matches(&self, file: &File, record: &IdxRecord) -> bool {
        let mut bytes = vec![0u8; record.frame_len as usize];
        if read_exact_at(file, &mut bytes, record.offset).is_err() {
            return false;
        }
        match frame::decode(&bytes) {
            Decoded::Frame(f) => {
                typed_id_of_canonical(Domain::Event, &bytes[f.event.clone()]).0 == record.event_id
                    && raw_id(&bytes[f.payload.clone()]).0 == record.payload_id
            }
            _ => false,
        }
    }

    fn open_writers(&mut self) -> Result<()> {
        let segment = self.segments.last().expect("at least one segment");
        let writer = OpenOptions::new()
            .append(true)
            .open(&segment.path)
            .map_err(io(&segment.path))?;
        let idx_writer = OpenOptions::new()
            .append(true)
            .open(&segment.idx_path)
            .map_err(io(&segment.idx_path))?;
        self.writer = Some(writer);
        self.idx_writer = Some(idx_writer);
        Ok(())
    }

    fn tables(&self) -> (PathBuf, PathBuf) {
        (self.dir.join("requests.tbl"), self.dir.join("payloads.tbl"))
    }

    fn load_key_indexes(&mut self) -> Result<()> {
        let (requests_path, payloads_path) = self.tables();
        let requests = SortedTable::<16>::open(&requests_path).filter(|t| t.covered() <= self.seq);
        let payloads = SortedTable::<32>::open(&payloads_path).filter(|t| t.covered() <= self.seq);
        if requests.is_none() {
            remove_if_exists(&requests_path)?;
        }
        if payloads.is_none() {
            remove_if_exists(&payloads_path)?;
        }
        self.requests = KeyIndex::with_table(requests);
        self.payloads = KeyIndex::with_table(payloads);
        let (request_from, payload_from) = (self.requests.covered(), self.payloads.covered());
        let mut duplicate = None;
        let uncovered: Vec<IdxRecord> = self
            .all_records()
            .filter(|r| r.seq > request_from.min(payload_from))
            .collect();
        for record in uncovered {
            if record.seq > request_from {
                if self.requests.get(&record.request).is_some() {
                    duplicate = Some(record.seq);
                }
                self.requests.insert(record.request, record.seq);
            }
            if record.seq > payload_from {
                self.payloads.insert(record.payload_id, record.seq);
            }
        }
        if let Some(seq) = duplicate {
            return Err(corrupt("journal", &self.dir, seq, "duplicate request ID"));
        }
        let events_path = self.dir.join("events.tbl");
        let events = SortedTable::<32>::open(&events_path).filter(|t| t.covered() <= self.seq);
        if events.is_none() {
            remove_if_exists(&events_path)?;
        }
        self.events = KeyIndex::with_table(events);
        let from = self.events.covered();
        let uncovered: Vec<IdxRecord> = self.all_records().filter(|r| r.seq > from).collect();
        for record in uncovered {
            self.events.insert(record.event_id, record.seq);
        }
        Ok(())
    }

    fn all_records(&self) -> impl Iterator<Item = IdxRecord> + '_ {
        self.segments
            .iter()
            .flat_map(|s| s.idx.records().iter().copied())
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn seq(&self) -> u64 {
        self.seq
    }

    pub fn head(&self) -> Sha256Id {
        self.head
    }

    pub fn segment_count(&self) -> usize {
        self.segments.len()
    }

    /// Torn tails moved aside while opening.
    pub fn recovered_tails(&self) -> &[PathBuf] {
        &self.recovered
    }

    fn active_end(&self) -> u64 {
        self.segments.last().map_or(SEGMENT_HEADER_LEN, |s| s.end)
    }

    /// Validates and durably appends a batch of events with a single flush per segment.
    /// Either every event is accepted or none is written; an I/O failure mid-write poisons
    /// the journal until it is reopened (reopen repairs any torn tail).
    pub fn append_batch(&mut self, events: &[NewEvent<'_>]) -> Result<Vec<Sha256Id>> {
        if self.poisoned {
            return Err(StoreError::Poisoned(self.name.clone()));
        }
        let mut head = self.head;
        let mut batch_requests = HashSet::new();
        let mut validated = Vec::with_capacity(events.len());
        for (index, event) in events.iter().enumerate() {
            let seq = self.seq + index as u64;
            if event.event.len() > frame::MAX_EVENT_BYTES {
                return Err(StoreError::TooLarge("event"));
            }
            if event.payload.len() > frame::MAX_PAYLOAD_BYTES {
                return Err(StoreError::TooLarge("payload"));
            }
            let valid =
                validate_event(event.event, event.payload, seq + 1, head).map_err(|fault| {
                    match fault {
                        EventFault::Json(e) => StoreError::Jcs(e),
                        EventFault::Shape(reason) => StoreError::InvalidEvent(reason.to_string()),
                        EventFault::Chain => StoreError::Chain {
                            expected_seq: seq + 1,
                            expected_prev: head,
                        },
                        EventFault::Payload(id) => StoreError::PayloadMismatch(id),
                    }
                })?;
            if self.requests.get(&valid.record.request).is_some()
                || !batch_requests.insert(valid.record.request)
            {
                return Err(StoreError::DuplicateRequest(valid.request_id));
            }
            head = Sha256Id(valid.record.event_id);
            validated.push(valid.record);
        }
        let result = self.write_validated(events, &mut validated);
        if result.is_err() {
            self.poisoned = true;
        }
        result?;
        Ok(validated.iter().map(|r| Sha256Id(r.event_id)).collect())
    }

    fn write_validated(
        &mut self,
        events: &[NewEvent<'_>],
        records: &mut [IdxRecord],
    ) -> Result<()> {
        let mut buffer = Vec::new();
        let mut pending: Vec<IdxRecord> = Vec::new();
        for (event, record) in events.iter().zip(records.iter_mut()) {
            let frame_len = u64::from(record.frame_len);
            let end = self.active_end() + buffer.len() as u64;
            if end > SEGMENT_HEADER_LEN && end + frame_len > self.opts.max_segment_bytes {
                self.flush(&mut buffer, &mut pending)?;
                self.rollover()?;
            }
            record.offset = self.active_end() + buffer.len() as u64;
            frame::encode(event.event, event.payload, &mut buffer);
            pending.push(*record);
        }
        self.flush(&mut buffer, &mut pending)
    }

    fn flush(&mut self, buffer: &mut Vec<u8>, pending: &mut Vec<IdxRecord>) -> Result<()> {
        if pending.is_empty() {
            return Ok(());
        }
        let path = self.segments.last().unwrap().path.clone();
        let writer = self.writer.as_mut().expect("writer");
        fault::hit("journal.before_write");
        let split = buffer.len() / 2;
        writer.write_all(&buffer[..split]).map_err(io(&path))?;
        fault::hit("journal.mid_frame");
        writer.write_all(&buffer[split..]).map_err(io(&path))?;
        fault::hit("journal.before_fsync");
        writer.sync_data().map_err(io(&path))?;
        fault::hit("journal.after_fsync");
        let idx_path = self.segments.last().unwrap().idx_path.clone();
        self.idx_writer
            .as_mut()
            .expect("idx writer")
            .write_all(bytemuck::cast_slice(pending))
            .map_err(io(&idx_path))?;
        fault::hit("journal.after_index");
        for record in pending.iter() {
            self.requests.insert(record.request, record.seq);
            self.payloads.insert(record.payload_id, record.seq);
            self.events.insert(record.event_id, record.seq);
        }
        let segment = self.segments.last_mut().unwrap();
        let last = *pending.last().unwrap();
        segment.end = last.offset + u64::from(last.frame_len);
        if let IdxStorage::Owned(records) = &mut segment.idx {
            records.extend_from_slice(pending);
        }
        self.seq = last.seq;
        self.head = Sha256Id(last.event_id);
        buffer.clear();
        pending.clear();
        Ok(())
    }

    fn rollover(&mut self) -> Result<()> {
        self.writer = None;
        self.idx_writer = None;
        let segment = self.segments.last_mut().unwrap();
        if let Some(mapped) = map_idx(&segment.idx_path) {
            if mapped.records().len() == segment.idx.records().len() {
                segment.idx = mapped;
            }
        }
        let next = segment.number + 1;
        self.create_segment(next)?;
        self.open_writers()
    }

    fn locate(&self, seq: u64) -> Result<(&Segment, IdxRecord)> {
        if seq == 0 || seq > self.seq {
            return Err(StoreError::UnknownSeq(seq));
        }
        let index = self.segments.partition_point(|s| s.first_seq <= seq) - 1;
        let segment = &self.segments[index];
        let record = segment.idx.records()[(seq - segment.first_seq) as usize];
        Ok((segment, record))
    }

    /// Index record for `seq` without reading the frame.
    pub fn record(&self, seq: u64) -> Result<IdxRecord> {
        self.locate(seq).map(|(_, r)| r)
    }

    /// Reads one committed event and re-verifies its frame checksum and both identities.
    pub fn read(&self, seq: u64) -> Result<StoredEvent> {
        let (segment, record) = self.locate(seq)?;
        let mut bytes = vec![0u8; record.frame_len as usize];
        read_exact_at(&segment.file, &mut bytes, record.offset).map_err(io(&segment.path))?;
        let Decoded::Frame(frame) = frame::decode(&bytes) else {
            return Err(corrupt(
                "journal frame",
                &segment.path,
                record.offset,
                "frame does not decode",
            ));
        };
        let event = bytes[frame.event.clone()].to_vec();
        let payload = bytes[frame.payload.clone()].to_vec();
        if typed_id_of_canonical(Domain::Event, &event).0 != record.event_id
            || raw_id(&payload).0 != record.payload_id
        {
            return Err(corrupt(
                "journal frame",
                &segment.path,
                record.offset,
                "frame does not match its index record",
            ));
        }
        Ok(StoredEvent {
            seq,
            event_id: Sha256Id(record.event_id),
            payload_id: Sha256Id(record.payload_id),
            event,
            payload,
        })
    }

    /// The committed event that used `request_id`, if any.
    pub fn by_request(&self, request_id: &str) -> Result<Option<StoredEvent>> {
        let Some(seq) = self.requests.get(&request_key(request_id)) else {
            return Ok(None);
        };
        let stored = self.read(seq)?;
        let value = strict_json(&stored.event)?;
        Ok((value["request_id"].as_str() == Some(request_id)).then_some(stored))
    }

    /// Payload bytes named `id`, from the earliest event that carries them.
    pub fn payload(&self, id: &Sha256Id) -> Result<Option<Vec<u8>>> {
        match self.payloads.get(&id.0) {
            Some(seq) => Ok(Some(self.read(seq)?.payload)),
            None => Ok(None),
        }
    }

    pub fn contains_payload(&self, id: &Sha256Id) -> bool {
        self.payloads.get(&id.0).is_some()
    }

    /// Sequence number of the event with this identity, if it is committed here.
    pub fn seq_of_event(&self, id: &Sha256Id) -> Option<u64> {
        self.events.get(&id.0)
    }

    /// Rewrites the request and payload tables to cover every committed event and empties
    /// the in-memory tails.
    pub fn compact_indexes(&mut self) -> Result<()> {
        let (requests_path, payloads_path) = self.tables();
        let mut requests: Vec<([u8; 16], u64)> =
            self.all_records().map(|r| (r.request, r.seq)).collect();
        let mut payloads: Vec<([u8; 32], u64)> =
            self.all_records().map(|r| (r.payload_id, r.seq)).collect();
        drop(self.requests.release_table());
        drop(self.payloads.release_table());
        let staging = self.staging();
        SortedTable::write(&staging, &requests_path, self.seq, &mut requests)?;
        SortedTable::write(&staging, &payloads_path, self.seq, &mut payloads)?;
        drop(requests);
        drop(payloads);
        self.requests = KeyIndex::with_table(SortedTable::open(&requests_path));
        self.payloads = KeyIndex::with_table(SortedTable::open(&payloads_path));
        let events_path = self.dir.join("events.tbl");
        let mut events: Vec<([u8; 32], u64)> =
            self.all_records().map(|r| (r.event_id, r.seq)).collect();
        drop(self.events.release_table());
        SortedTable::write(&staging, &events_path, self.seq, &mut events)?;
        self.events = KeyIndex::with_table(SortedTable::open(&events_path));
        Ok(())
    }

    /// Bytes of the in-memory index tails (requests + payloads), for footprint reporting.
    pub fn tail_entries(&self) -> usize {
        self.requests.tail_len() + self.payloads.tail_len() + self.events.tail_len()
    }

    /// Re-reads every segment from disk and checks every frame, the chain, every payload
    /// hash, the index files and the lookup tables.
    pub fn verify_deep(&self) -> Result<JournalReport> {
        let mut seq = 0u64;
        let mut head = Sha256Id::ZERO;
        let mut bytes_total = 0u64;
        for segment in &self.segments {
            let bytes = fs::read(&segment.path).map_err(io(&segment.path))?;
            bytes_total += bytes.len() as u64;
            if frame::parse_segment_header(&bytes) != Some(seq + 1) {
                return Err(corrupt(
                    "journal segment",
                    &segment.path,
                    0,
                    "segment header",
                ));
            }
            let (records, end) = scan(
                &segment.path,
                &bytes[SEGMENT_HEADER_LEN as usize..],
                SEGMENT_HEADER_LEN,
                &mut seq,
                &mut head,
                false,
            )?;
            if !matches!(end, ScanEnd::Clean) {
                return Err(corrupt(
                    "journal segment",
                    &segment.path,
                    0,
                    "unexpected torn tail",
                ));
            }
            if records.as_slice() != segment.idx.records() {
                return Err(corrupt(
                    "journal index",
                    &segment.idx_path,
                    0,
                    "index differs from segment frames",
                ));
            }
            let on_disk = fs::read(&segment.idx_path)
                .ok()
                .and_then(|b| idx::parse_records(&b, segment.first_seq));
            if on_disk.as_deref() != Some(records.as_slice()) {
                return Err(corrupt(
                    "journal index",
                    &segment.idx_path,
                    0,
                    "index file differs from segment frames",
                ));
            }
        }
        if seq != self.seq || head != self.head {
            return Err(corrupt(
                "journal",
                &self.dir,
                seq,
                "in-memory head differs from disk",
            ));
        }
        for record in self.all_records() {
            if self.requests.get(&record.request) != Some(record.seq) {
                return Err(corrupt(
                    "journal request table",
                    &self.dir,
                    record.seq,
                    "request lookup mismatch",
                ));
            }
            if self.events.get(&record.event_id) != Some(record.seq) {
                return Err(corrupt(
                    "journal event table",
                    &self.dir,
                    record.seq,
                    "event lookup mismatch",
                ));
            }
            match self.payloads.get(&record.payload_id) {
                Some(first) if first <= record.seq => {}
                _ => {
                    return Err(corrupt(
                        "journal payload table",
                        &self.dir,
                        record.seq,
                        "payload lookup mismatch",
                    ))
                }
            }
        }
        for table in [
            self.requests.table.as_ref().map(|t| t.is_sorted_unique()),
            self.payloads.table.as_ref().map(|t| t.is_sorted_unique()),
            self.events.table.as_ref().map(|t| t.is_sorted_unique()),
        ] {
            if table == Some(false) {
                return Err(corrupt("journal table", &self.dir, 0, "table not sorted"));
            }
        }
        Ok(JournalReport {
            events: self.seq,
            segments: self.segments.len(),
            bytes: bytes_total,
            head: (self.seq > 0).then_some(self.head),
        })
    }
}

fn structurally_valid(records: &[IdxRecord], first_seq: u64, segment_len: u64) -> bool {
    let mut offset = SEGMENT_HEADER_LEN;
    for (index, record) in records.iter().enumerate() {
        if record.seq != first_seq + index as u64
            || record.offset != offset
            || record.frame_len == 0
        {
            return false;
        }
        offset += u64::from(record.frame_len);
    }
    offset <= segment_len
}

fn map_idx(path: &Path) -> Option<IdxStorage> {
    let file = File::open(path).ok()?;
    // SAFETY: a sealed segment's index is never modified again.
    let map = unsafe { Mmap::map(&file) }.ok()?;
    if map.len() < idx::IDX_HEADER_LEN
        || !(map.len() - idx::IDX_HEADER_LEN).is_multiple_of(IDX_RECORD_LEN)
    {
        return None;
    }
    Some(IdxStorage::Mapped(map))
}

/// Walks frames in `bytes` (which start at file offset `base`), validating each against the
/// running chain. `last` allows a torn tail; otherwise any incomplete frame is corruption.
fn scan(
    path: &Path,
    bytes: &[u8],
    base: u64,
    seq: &mut u64,
    head: &mut Sha256Id,
    last: bool,
) -> Result<(Vec<IdxRecord>, ScanEnd)> {
    let mut records = Vec::new();
    let mut position = 0usize;
    while position < bytes.len() {
        let offset = base + position as u64;
        match frame::decode(&bytes[position..]) {
            Decoded::Frame(frame) => {
                let slice = &bytes[position..];
                let valid = validate_event(
                    &slice[frame.event.clone()],
                    &slice[frame.payload.clone()],
                    *seq + 1,
                    *head,
                )
                .map_err(|fault| {
                    let reason = match fault {
                        EventFault::Json(e) => e.to_string(),
                        EventFault::Shape(r) => r.to_string(),
                        EventFault::Chain => "broken chain".to_string(),
                        EventFault::Payload(id) => format!("payload does not hash to {id}"),
                    };
                    corrupt("journal frame", path, offset, reason)
                })?;
                let mut record = valid.record;
                record.offset = offset;
                *seq += 1;
                *head = Sha256Id(record.event_id);
                records.push(record);
                position += frame.total_len;
            }
            Decoded::Incomplete if last => return Ok((records, ScanEnd::Torn(offset))),
            Decoded::Invalid(_) if last && bytes[position..].iter().all(|b| *b == 0) => {
                // Zero-filled space after a crash: allocated but never written.
                return Ok((records, ScanEnd::Torn(offset)));
            }
            Decoded::Incomplete => {
                return Err(corrupt("journal frame", path, offset, "incomplete frame"))
            }
            Decoded::Invalid(reason) => return Err(corrupt("journal frame", path, offset, reason)),
        }
    }
    Ok((records, ScanEnd::Clean))
}
