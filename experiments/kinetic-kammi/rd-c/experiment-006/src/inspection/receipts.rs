use std::{
    fs::{File, OpenOptions},
    io::Write,
    path::Path,
};

use hashbrown::HashMap;
use memmap2::MmapOptions;
use rdc_experiment_004::Choice;
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout, Unaligned};

use super::source::{
    InspectionReply, InspectionResult, QueryId, QuerySimulator, TransportStatus, fixed_hash,
    source_digest,
};

const NO_CHOICE: u8 = u8::MAX;
const RECEIPT_MAGIC: [u8; 4] = *b"RDI6";
const JOURNAL_VERSION: u16 = 1;
const HEADER_BYTES: usize = 8;
#[derive(FromBytes, IntoBytes, KnownLayout, Immutable, Unaligned, Clone, Copy)]
#[repr(C)]
struct ReceiptRow {
    event: u8,
    outcome: u8,
    query_id: [u8; 16],
    episode_id_le: [u8; 4],
    active_action: u8,
    proposed_action: u8,
    attempt_le: [u8; 2],
    charged: u8,
    transport: u8,
    candidate_a: u8,
    candidate_b: u8,
    confidence_le: [u8; 2],
    signature_valid: u8,
    reported_revision: u8,
    payload_digest: [u8; 32],
    previous_hash: [u8; 32],
    hash: [u8; 32],
}

impl ReceiptRow {
    fn blank(
        event: u8,
        id: QueryId,
        episode_id: u32,
        active: Choice,
        previous_hash: [u8; 32],
    ) -> Self {
        Self {
            event,
            outcome: NO_CHOICE,
            query_id: id.0,
            episode_id_le: episode_id.to_le_bytes(),
            active_action: active as u8,
            proposed_action: NO_CHOICE,
            attempt_le: [0; 2],
            charged: 0,
            transport: TransportStatus::Complete as u8,
            candidate_a: NO_CHOICE,
            candidate_b: NO_CHOICE,
            confidence_le: [0; 2],
            signature_valid: 0,
            reported_revision: 0,
            payload_digest: [0; 32],
            previous_hash,
            hash: [0; 32],
        }
    }

    fn seal(&mut self) {
        self.hash = self.computed_hash();
    }

    fn computed_hash(self) -> [u8; 32] {
        let mut copy = self;
        copy.hash = [0; 32];
        fixed_hash(b"RDC-E006-QUERY-RECEIPT-V1\0", copy.as_bytes())
    }

    fn result(self) -> Result<InspectionResult, Box<dyn std::error::Error>> {
        let reply = InspectionReply {
            transport: TransportStatus::from_code(self.transport).ok_or("bad receipt transport")?,
            candidate_a: self.candidate_a,
            candidate_b: self.candidate_b,
            confidence: u16::from_le_bytes(self.confidence_le),
            signature_valid: self.signature_valid == 1,
            reported_revision: self.reported_revision,
            payload_digest: self.payload_digest,
        };
        let active = Choice::from_code(self.active_action).ok_or("bad active action in receipt")?;
        let result = InspectionResult::classify(active, reply);
        if self.signature_valid > 1
            || result.outcome as u8 != self.outcome
            || result
                .proposed_action
                .map_or(NO_CHOICE, |choice| choice as u8)
                != self.proposed_action
            || source_digest(u32::from_le_bytes(self.episode_id_le), reply) != reply.payload_digest
        {
            return Err("receipt outcome or proposal does not match recorded reply".into());
        }
        Ok(result)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct QueryProgress {
    episode_id: u32,
    active: Choice,
    attempts: u16,
    result: Option<InspectionResult>,
    paid: bool,
}

type ProgressMap = HashMap<QueryId, QueryProgress>;
type RecoveredReceiptLog = (ProgressMap, [u8; 32], u64);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CrashPoint {
    None,
    AfterIntent,
    AfterEndpointResponse,
    AfterOutcomeReceipt,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct QueryReceiptStats {
    pub queries: usize,
    pub attempts: usize,
    pub retries: usize,
    pub charges: usize,
    pub outcomes: usize,
    pub unresolved: usize,
    pub bytes: u64,
    pub identity: [u8; 32],
}

pub struct QueryReceiptLog {
    writer: std::io::BufWriter<File>,
    progress: HashMap<QueryId, QueryProgress>,
    previous_hash: [u8; 32],
    bytes: u64,
}

impl QueryReceiptLog {
    pub fn create(path: impl AsRef<Path>) -> Result<Self, Box<dyn std::error::Error>> {
        let file = OpenOptions::new().write(true).create_new(true).open(path)?;
        let mut writer = std::io::BufWriter::with_capacity(8 * 1024, file);
        writer.write_all(ReceiptJournalHeader::new().as_bytes())?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(Self {
            writer,
            progress: HashMap::with_capacity(80),
            previous_hash: [0; 32],
            bytes: HEADER_BYTES as u64,
        })
    }

    pub fn resume(path: impl AsRef<Path>) -> Result<Self, Box<dyn std::error::Error>> {
        let path = path.as_ref();
        let (progress, previous_hash, bytes) = read_receipt_progress(path)?;
        let file = OpenOptions::new().append(true).open(path)?;
        Ok(Self {
            writer: std::io::BufWriter::with_capacity(8 * 1024, file),
            progress,
            previous_hash,
            bytes,
        })
    }

    pub fn execute(
        &mut self,
        source: &mut QuerySimulator<'_>,
        id: QueryId,
        episode_id: u32,
        active: Choice,
        crash: CrashPoint,
    ) -> Result<InspectionResult, Box<dyn std::error::Error>> {
        if let Some(progress) = self.progress.get(&id).copied() {
            if progress.episode_id != episode_id || progress.active != active {
                return Err("query receipt ID reused with different inputs".into());
            }
            if let Some(result) = progress.result {
                return Ok(result);
            }
        } else {
            self.append(ReceiptRow::blank(
                1,
                id,
                episode_id,
                active,
                self.previous_hash,
            ))?;
            self.progress.insert(
                id,
                QueryProgress {
                    episode_id,
                    active,
                    attempts: 0,
                    result: None,
                    paid: false,
                },
            );
            if crash == CrashPoint::AfterIntent {
                return Err("injected crash after durable query intent".into());
            }
        }
        let progress = self
            .progress
            .get(&id)
            .copied()
            .ok_or("query progress missing")?;
        let attempt = progress
            .attempts
            .checked_add(1)
            .ok_or("query attempt overflow")?;
        let mut row = ReceiptRow::blank(2, id, episode_id, active, self.previous_hash);
        row.attempt_le = attempt.to_le_bytes();
        self.append(row)?;
        self.progress
            .get_mut(&id)
            .ok_or("query progress missing")?
            .attempts = attempt;
        let (reply, _charged_this_attempt) = source.query(id, episode_id)?;
        if crash == CrashPoint::AfterEndpointResponse {
            return Err("injected crash after endpoint response before result receipt".into());
        }
        let result = InspectionResult::classify(active, reply);
        let mut row = ReceiptRow::blank(3, id, episode_id, active, self.previous_hash);
        row.outcome = result.outcome as u8;
        row.proposed_action = result
            .proposed_action
            .map_or(NO_CHOICE, |choice| choice as u8);
        row.attempt_le = attempt.to_le_bytes();
        row.charged = source.paid_for(id) as u8;
        row.transport = reply.transport as u8;
        row.candidate_a = reply.candidate_a;
        row.candidate_b = reply.candidate_b;
        row.confidence_le = reply.confidence.to_le_bytes();
        row.signature_valid = reply.signature_valid as u8;
        row.reported_revision = reply.reported_revision;
        row.payload_digest = reply.payload_digest;
        self.append(row)?;
        let progress = self.progress.get_mut(&id).ok_or("query progress missing")?;
        progress.result = Some(result);
        progress.paid = source.paid_for(id);
        if crash == CrashPoint::AfterOutcomeReceipt {
            return Err("injected crash after durable result receipt".into());
        }
        Ok(result)
    }

    pub fn result(&self, id: QueryId) -> Option<InspectionResult> {
        self.progress.get(&id).and_then(|progress| progress.result)
    }

    fn append(&mut self, mut row: ReceiptRow) -> Result<(), Box<dyn std::error::Error>> {
        row.previous_hash = self.previous_hash;
        row.hash = [0; 32];
        row.seal();
        self.writer.write_all(row.as_bytes())?;
        self.writer.flush()?;
        self.writer.get_ref().sync_data()?;
        self.bytes = self.bytes.saturating_add(row.as_bytes().len() as u64);
        self.previous_hash = row.hash;
        Ok(())
    }

    pub fn close(self) -> Result<(), Box<dyn std::error::Error>> {
        let mut writer = self.writer;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(())
    }
}

pub fn verify_receipt_log(
    path: impl AsRef<Path>,
) -> Result<QueryReceiptStats, Box<dyn std::error::Error>> {
    let path = path.as_ref();
    let (progress, identity, bytes) = read_receipt_progress(path)?;
    let mut stats = QueryReceiptStats {
        queries: progress.len(),
        bytes,
        identity,
        ..QueryReceiptStats::default()
    };
    for query in progress.values() {
        stats.attempts += query.attempts as usize;
        stats.charges += usize::from(query.paid);
        if let Some(result) = query.result {
            stats.outcomes += 1;
            stats.unresolved += usize::from(result.proposed_action.is_none());
        }
    }
    stats.retries = stats.attempts.saturating_sub(stats.queries);
    Ok(stats)
}

fn read_receipt_progress(path: &Path) -> Result<RecoveredReceiptLog, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    // SAFETY: closed append-only logs are mapped read-only during replay.
    let map = unsafe { MmapOptions::new().map(&file)? };
    let (header, body) =
        ReceiptJournalHeader::ref_from_prefix(&map).map_err(|_| "bad receipt header")?;
    if header.magic != RECEIPT_MAGIC
        || header.version_le != JOURNAL_VERSION.to_le_bytes()
        || header.reserved != [0; 2]
    {
        return Err("unsupported query receipt version".into());
    }
    if body.len() % std::mem::size_of::<ReceiptRow>() != 0 {
        return Err("query receipt log has a partial row".into());
    }
    let mut progress = HashMap::with_capacity(body.len() / std::mem::size_of::<ReceiptRow>());
    let mut previous_hash = [0; 32];
    for bytes in body.chunks_exact(std::mem::size_of::<ReceiptRow>()) {
        let row = *ReceiptRow::ref_from_bytes(bytes).map_err(|_| "malformed query receipt row")?;
        if row.previous_hash != previous_hash || row.hash != row.computed_hash() {
            return Err("query receipt hash chain failed".into());
        }
        let id = QueryId(row.query_id);
        let episode_id = u32::from_le_bytes(row.episode_id_le);
        let active =
            Choice::from_code(row.active_action).ok_or("invalid active action in query log")?;
        match row.event {
            1 => {
                if progress
                    .insert(
                        id,
                        QueryProgress {
                            episode_id,
                            active,
                            attempts: 0,
                            result: None,
                            paid: false,
                        },
                    )
                    .is_some()
                {
                    return Err("duplicate query intent".into());
                }
            }
            2 => {
                let query = progress
                    .get_mut(&id)
                    .ok_or("attempt without query intent")?;
                let attempt = u16::from_le_bytes(row.attempt_le);
                if query.episode_id != episode_id
                    || query.active != active
                    || attempt != query.attempts + 1
                    || query.result.is_some()
                {
                    return Err("query attempt sequence invalid".into());
                }
                query.attempts = attempt;
            }
            3 => {
                let query = progress
                    .get_mut(&id)
                    .ok_or("outcome without query intent")?;
                let result = row.result()?;
                if query.episode_id != episode_id
                    || query.active != active
                    || query.result.is_some()
                    || query.attempts == 0
                    || row.charged > 1
                {
                    return Err("query outcome is not paired with one pending intent".into());
                }
                query.result = Some(result);
                query.paid = row.charged == 1;
            }
            _ => return Err("unknown query receipt event".into()),
        }
        previous_hash = row.hash;
    }
    Ok((progress, previous_hash, map.len() as u64))
}

#[derive(FromBytes, IntoBytes, KnownLayout, Immutable, Unaligned)]
#[repr(C)]
struct ReceiptJournalHeader {
    magic: [u8; 4],
    version_le: [u8; 2],
    reserved: [u8; 2],
}

impl ReceiptJournalHeader {
    fn new() -> Self {
        Self {
            magic: RECEIPT_MAGIC,
            version_le: JOURNAL_VERSION.to_le_bytes(),
            reserved: [0; 2],
        }
    }
}
