use std::{
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::Path,
    time::Instant,
};

use blake3::Hasher;
use hashbrown::HashMap;
use memchr::memchr_iter;
use memmap2::MmapOptions;
use rdc_experiment_004::Choice;
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout, Unaligned};

use crate::episodes::{Episode, Scenario, contract_action, hidden_revision, rotated};

const NO_CHOICE: u8 = u8::MAX;
const SOURCE_MAGIC: [u8; 4] = *b"RDS6";
const JOURNAL_VERSION: u16 = 1;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct QueryId(pub [u8; 16]);

impl QueryId {
    pub fn from_parts(run_seed: u64, lane: u8, budget: usize, episode_id: u32) -> Self {
        let mut hash = Hasher::new();
        hash.update(b"RDC-E006-QUERY-ID-V1\0");
        hash.update(&run_seed.to_le_bytes());
        hash.update(&[lane]);
        hash.update(&(budget as u64).to_le_bytes());
        hash.update(&episode_id.to_le_bytes());
        let mut id = [0; 16];
        id.copy_from_slice(&hash.finalize().as_bytes()[..16]);
        Self(id)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum TransportStatus {
    Complete = 0,
    Timeout = 1,
    Unavailable = 2,
    Malformed = 3,
}

impl TransportStatus {
    pub(super) fn from_code(value: u8) -> Option<Self> {
        match value {
            0 => Some(Self::Complete),
            1 => Some(Self::Timeout),
            2 => Some(Self::Unavailable),
            3 => Some(Self::Malformed),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum InspectionOutcome {
    Confirmed = 0,
    Contradicted = 1,
    Unknown = 2,
    Failed = 3,
}

impl InspectionOutcome {
    pub fn label(self) -> &'static str {
        match self {
            Self::Confirmed => "confirmed",
            Self::Contradicted => "contradicted",
            Self::Unknown => "unknown",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct InspectionReply {
    pub transport: TransportStatus,
    pub candidate_a: u8,
    pub candidate_b: u8,
    pub confidence: u16,
    pub signature_valid: bool,
    pub reported_revision: u8,
    pub payload_digest: [u8; 32],
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct InspectionResult {
    pub outcome: InspectionOutcome,
    /// `None` is an explicit re-observe proposal, never a fallback to the active action.
    pub proposed_action: Option<Choice>,
    pub reply: InspectionReply,
}

impl InspectionResult {
    pub fn classify(active: Choice, reply: InspectionReply) -> Self {
        let outcome = match reply.transport {
            TransportStatus::Timeout | TransportStatus::Unavailable => InspectionOutcome::Failed,
            TransportStatus::Malformed => InspectionOutcome::Unknown,
            TransportStatus::Complete
                if !reply.signature_valid
                    || reply.confidence < 800
                    || Choice::from_code(reply.candidate_a).is_none()
                    || reply.candidate_b != NO_CHOICE =>
            {
                InspectionOutcome::Unknown
            }
            TransportStatus::Complete if reply.candidate_a == active as u8 => {
                InspectionOutcome::Confirmed
            }
            TransportStatus::Complete => InspectionOutcome::Contradicted,
        };
        let proposed_action = match outcome {
            InspectionOutcome::Confirmed => Some(active),
            InspectionOutcome::Contradicted => Choice::from_code(reply.candidate_a),
            InspectionOutcome::Unknown | InspectionOutcome::Failed => None,
        };
        Self {
            outcome,
            proposed_action,
            reply,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct InspectionSourceState {
    pub episode_id: u32,
    pub reply: InspectionReply,
}

#[derive(Default)]
pub struct InspectionSourceStore {
    records: HashMap<u32, InspectionSourceState>,
}

impl InspectionSourceStore {
    pub fn load_mmap(path: impl AsRef<Path>) -> Result<Self, Box<dyn std::error::Error>> {
        let file = File::open(path)?;
        // SAFETY: benchmark source fixtures are closed before mapping and remain immutable.
        let map = unsafe { MmapOptions::new().map(&file)? };
        let mut rows = memchr_iter(b'\n', &map);
        let Some(header_end) = rows.next() else {
            return Err("source fixture is empty".into());
        };
        if &map[..header_end]
            != b"episode_id,transport,candidate_a,candidate_b,confidence,signature_valid,reported_revision,payload_digest"
        {
            return Err("source fixture header mismatch".into());
        }
        let mut records = HashMap::with_capacity(512);
        let mut start = header_end + 1;
        for end in rows {
            if end <= start {
                return Err("source fixture contains an empty row".into());
            }
            let line = std::str::from_utf8(&map[start..end])?;
            let mut fields = line.split(',');
            let episode_id = next::<u32>(&mut fields)?;
            let transport = TransportStatus::from_code(next::<u8>(&mut fields)?)
                .ok_or("invalid source transport status")?;
            let candidate_a = next::<u8>(&mut fields)?;
            let candidate_b = next::<u8>(&mut fields)?;
            let confidence = next::<u16>(&mut fields)?;
            let signature_valid = parse_bool(fields.next().ok_or("missing signature flag")?)?;
            let reported_revision = next::<u8>(&mut fields)?;
            let payload_digest = parse_digest(fields.next().ok_or("missing payload digest")?)?;
            if fields.next().is_some() {
                return Err("source fixture has extra fields".into());
            }
            let reply = InspectionReply {
                transport,
                candidate_a,
                candidate_b,
                confidence,
                signature_valid,
                reported_revision,
                payload_digest,
            };
            if source_digest(episode_id, reply) != reply.payload_digest {
                return Err(format!("source payload digest mismatch at {episode_id}").into());
            }
            if records
                .insert(episode_id, InspectionSourceState { episode_id, reply })
                .is_some()
            {
                return Err(format!("duplicate source fixture episode {episode_id}").into());
            }
            start = end + 1;
        }
        if start != map.len() {
            return Err("source fixture final row is incomplete".into());
        }
        Ok(Self { records })
    }

    pub fn get(&self, episode_id: u32) -> Option<InspectionSourceState> {
        self.records.get(&episode_id).copied()
    }

    pub fn len(&self) -> usize {
        self.records.len()
    }

    pub fn is_empty(&self) -> bool {
        self.records.is_empty()
    }
}

pub fn write_source_fixture(
    path: impl AsRef<Path>,
    episodes: &[Episode],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(16 * 1024, File::create(path)?);
    writeln!(
        writer,
        "episode_id,transport,candidate_a,candidate_b,confidence,signature_valid,reported_revision,payload_digest"
    )?;
    for episode in episodes {
        let revision = hidden_revision(episode.domain as usize, episode.within as usize);
        let correct = contract_action(episode.frame.features.goal, revision);
        let reply = fixture_reply(episode, correct);
        writeln!(
            writer,
            "{},{},{},{},{},{},{},{}",
            episode.id,
            reply.transport as u8,
            reply.candidate_a,
            reply.candidate_b,
            reply.confidence,
            reply.signature_valid,
            reply.reported_revision,
            hex(&reply.payload_digest)
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn fixture_reply(episode: &Episode, correct: Choice) -> InspectionReply {
    let frame = episode.frame.features;
    let active = frame.primary_action;
    let (transport, candidate_a, candidate_b, confidence, signature_valid) = match episode.scenario
    {
        Scenario::ConfirmedCorrect => (
            TransportStatus::Complete,
            active as u8,
            NO_CHOICE,
            970,
            true,
        ),
        Scenario::HelpfulContradiction => (
            TransportStatus::Complete,
            correct as u8,
            NO_CHOICE,
            970,
            true,
        ),
        Scenario::HarmfulContradiction => (
            TransportStatus::Complete,
            rotated(correct, 1) as u8,
            NO_CHOICE,
            970,
            true,
        ),
        Scenario::StaleEchoWrong => (
            TransportStatus::Complete,
            active as u8,
            NO_CHOICE,
            980,
            true,
        ),
        Scenario::SelfConflict => (
            TransportStatus::Complete,
            active as u8,
            correct as u8,
            940,
            true,
        ),
        Scenario::Timeout => (TransportStatus::Timeout, NO_CHOICE, NO_CHOICE, 0, false),
        Scenario::TransportFailure => {
            (TransportStatus::Unavailable, NO_CHOICE, NO_CHOICE, 0, false)
        }
        Scenario::MalformedEvidence => (
            TransportStatus::Malformed,
            active as u8,
            NO_CHOICE,
            980,
            false,
        ),
    };
    let reported_revision = match episode.scenario {
        Scenario::StaleEchoWrong | Scenario::HelpfulContradiction => frame.primary_revision,
        _ => frame.audit_revision,
    };
    let mut reply = InspectionReply {
        transport,
        candidate_a,
        candidate_b,
        confidence,
        signature_valid,
        reported_revision,
        payload_digest: [0; 32],
    };
    reply.payload_digest = source_digest(episode.id, reply);
    reply
}

pub(super) fn source_digest(episode_id: u32, reply: InspectionReply) -> [u8; 32] {
    let mut hasher = Hasher::new();
    hasher.update(b"RDC-E006-SOURCE-PAYLOAD-V1\0");
    hasher.update(&episode_id.to_le_bytes());
    hasher.update(&[
        reply.transport as u8,
        reply.candidate_a,
        reply.candidate_b,
        reply.signature_valid as u8,
        reply.reported_revision,
    ]);
    hasher.update(&reply.confidence.to_le_bytes());
    *hasher.finalize().as_bytes()
}

#[derive(FromBytes, IntoBytes, KnownLayout, Immutable, Unaligned, Clone, Copy)]
#[repr(C)]
struct JournalHeader {
    magic: [u8; 4],
    version_le: [u8; 2],
    reserved: [u8; 2],
}

impl JournalHeader {
    fn new(magic: [u8; 4]) -> Self {
        Self {
            magic,
            version_le: JOURNAL_VERSION.to_le_bytes(),
            reserved: [0; 2],
        }
    }
}

#[derive(FromBytes, IntoBytes, KnownLayout, Immutable, Unaligned, Clone, Copy)]
#[repr(C)]
struct SourceCacheRow {
    query_id: [u8; 16],
    episode_id_le: [u8; 4],
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

impl SourceCacheRow {
    fn new(
        query_id: QueryId,
        episode_id: u32,
        reply: InspectionReply,
        previous_hash: [u8; 32],
    ) -> Self {
        let mut row = Self {
            query_id: query_id.0,
            episode_id_le: episode_id.to_le_bytes(),
            transport: reply.transport as u8,
            candidate_a: reply.candidate_a,
            candidate_b: reply.candidate_b,
            confidence_le: reply.confidence.to_le_bytes(),
            signature_valid: reply.signature_valid as u8,
            reported_revision: reply.reported_revision,
            payload_digest: reply.payload_digest,
            previous_hash,
            hash: [0; 32],
        };
        row.hash = row.computed_hash();
        row
    }

    fn computed_hash(self) -> [u8; 32] {
        let mut copy = self;
        copy.hash = [0; 32];
        fixed_hash(b"RDC-E006-SOURCE-CACHE-V1\0", copy.as_bytes())
    }

    fn reply(self) -> Result<InspectionReply, Box<dyn std::error::Error>> {
        let reply = InspectionReply {
            transport: TransportStatus::from_code(self.transport).ok_or("bad cached transport")?,
            candidate_a: self.candidate_a,
            candidate_b: self.candidate_b,
            confidence: u16::from_le_bytes(self.confidence_le),
            signature_valid: self.signature_valid == 1,
            reported_revision: self.reported_revision,
            payload_digest: self.payload_digest,
        };
        if self.signature_valid > 1
            || source_digest(u32::from_le_bytes(self.episode_id_le), reply) != reply.payload_digest
        {
            return Err("invalid cached source payload".into());
        }
        Ok(reply)
    }
}

pub struct QuerySimulator<'a> {
    writer: std::io::BufWriter<File>,
    fixtures: &'a InspectionSourceStore,
    cache: HashMap<QueryId, (u32, InspectionReply)>,
    previous_hash: [u8; 32],
    pub attempts: usize,
    pub retries: usize,
    pub charges: usize,
}

impl<'a> QuerySimulator<'a> {
    pub fn create(
        path: impl AsRef<Path>,
        fixtures: &'a InspectionSourceStore,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let file = OpenOptions::new().write(true).create_new(true).open(path)?;
        let mut writer = std::io::BufWriter::with_capacity(8 * 1024, file);
        writer.write_all(JournalHeader::new(SOURCE_MAGIC).as_bytes())?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(Self {
            writer,
            fixtures,
            cache: HashMap::with_capacity(80),
            previous_hash: [0; 32],
            attempts: 0,
            retries: 0,
            charges: 0,
        })
    }

    pub fn resume(
        path: impl AsRef<Path>,
        fixtures: &'a InspectionSourceStore,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let path = path.as_ref();
        let rows = map_source_cache(path)?;
        let mut cache = HashMap::with_capacity(rows.len());
        let mut previous_hash = [0; 32];
        for row in rows {
            if row.previous_hash != previous_hash || row.hash != row.computed_hash() {
                return Err("source cache hash chain failed".into());
            }
            let id = QueryId(row.query_id);
            let episode_id = u32::from_le_bytes(row.episode_id_le);
            let reply = row.reply()?;
            if fixtures
                .get(episode_id)
                .is_none_or(|source| source.reply != reply)
                || cache.insert(id, (episode_id, reply)).is_some()
            {
                return Err("source cache does not match immutable fixture".into());
            }
            previous_hash = row.hash;
        }
        let file = OpenOptions::new().append(true).open(path)?;
        Ok(Self {
            writer: std::io::BufWriter::with_capacity(8 * 1024, file),
            fixtures,
            charges: cache.len(),
            cache,
            previous_hash,
            attempts: 0,
            retries: 0,
        })
    }

    pub fn query(
        &mut self,
        query_id: QueryId,
        episode_id: u32,
    ) -> Result<(InspectionReply, bool), Box<dyn std::error::Error>> {
        let _started = Instant::now();
        self.attempts += 1;
        if let Some((existing_episode, reply)) = self.cache.get(&query_id).copied() {
            if existing_episode != episode_id {
                return Err("query ID was reused for a different episode".into());
            }
            self.retries += 1;
            return Ok((reply, false));
        }
        let source = self
            .fixtures
            .get(episode_id)
            .ok_or("query source fixture missing")?;
        let row = SourceCacheRow::new(query_id, episode_id, source.reply, self.previous_hash);
        self.writer.write_all(row.as_bytes())?;
        self.writer.flush()?;
        self.writer.get_ref().sync_data()?;
        self.previous_hash = row.hash;
        self.cache.insert(query_id, (episode_id, source.reply));
        self.charges += 1;
        Ok((source.reply, true))
    }

    pub fn paid_for(&self, query_id: QueryId) -> bool {
        self.cache.contains_key(&query_id)
    }

    pub fn close(self) -> Result<(), Box<dyn std::error::Error>> {
        let mut writer = self.writer;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(())
    }
}

#[derive(FromBytes, IntoBytes, KnownLayout, Immutable, Unaligned)]
#[repr(C)]
struct SourceHeader {
    magic: [u8; 4],
    version_le: [u8; 2],
    reserved: [u8; 2],
}

fn map_source_cache(path: &Path) -> Result<Vec<SourceCacheRow>, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    // SAFETY: service cache files are closed before recovery mapping.
    let map = unsafe { MmapOptions::new().map(&file)? };
    let (header, body) =
        SourceHeader::ref_from_prefix(&map).map_err(|_| "bad source cache header")?;
    if header.magic != SOURCE_MAGIC
        || header.version_le != JOURNAL_VERSION.to_le_bytes()
        || header.reserved != [0; 2]
        || body.len() % std::mem::size_of::<SourceCacheRow>() != 0
    {
        return Err("unsupported or partial source cache".into());
    }
    body.chunks_exact(std::mem::size_of::<SourceCacheRow>())
        .map(|bytes| {
            SourceCacheRow::ref_from_bytes(bytes)
                .copied()
                .map_err(|_| "bad source cache row".into())
        })
        .collect()
}

pub(super) fn fixed_hash(domain: &[u8], bytes: &[u8]) -> [u8; 32] {
    let mut hasher = Hasher::new();
    hasher.update(domain);
    hasher.update(bytes);
    *hasher.finalize().as_bytes()
}

fn next<T: std::str::FromStr>(
    fields: &mut std::str::Split<'_, char>,
) -> Result<T, Box<dyn std::error::Error>>
where
    T::Err: std::error::Error + 'static,
{
    Ok(fields
        .next()
        .ok_or("missing source fixture field")?
        .parse()?)
}

fn parse_bool(value: &str) -> Result<bool, Box<dyn std::error::Error>> {
    match value {
        "true" => Ok(true),
        "false" => Ok(false),
        _ => Err("invalid source signature flag".into()),
    }
}

fn parse_digest(value: &str) -> Result<[u8; 32], Box<dyn std::error::Error>> {
    if value.len() != 64 {
        return Err("invalid source digest length".into());
    }
    let mut digest = [0; 32];
    for (index, byte) in digest.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)?;
    }
    Ok(digest)
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}
