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
use rdc_experiment_004::{Choice, episodes::contract_action};
use serde::{Deserialize, Serialize};
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout, Unaligned};

use crate::{
    episodes::{Episode, EpisodeClass, hidden_revision},
    routing::Lane,
};

const RECEIPT_MAGIC: [u8; 4] = *b"RDI5";
const RECEIPT_VERSION: u16 = 1;
const HEADER_BYTES: usize = 8;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct InspectionResult {
    pub evidence_family: u8,
    /// Stable `Choice` code. The result contains no task label or revision field.
    pub recommendation: u8,
    pub confidence: u16,
    pub signature_valid: bool,
    pub payload_digest: [u8; 32],
}

impl InspectionResult {
    pub fn choice(self) -> Option<Choice> {
        Choice::from_code(self.recommendation)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct InspectionSourceState {
    pub episode_id: u32,
    pub evidence_family: u8,
    pub recommendation: u8,
    pub confidence: u16,
    pub signature_valid: bool,
    pub payload_digest: [u8; 32],
}

impl InspectionSourceState {
    fn result(self) -> InspectionResult {
        InspectionResult {
            evidence_family: self.evidence_family,
            recommendation: self.recommendation,
            confidence: self.confidence,
            signature_valid: self.signature_valid,
            payload_digest: self.payload_digest,
        }
    }
}

#[derive(Default)]
pub struct SourceStateStore {
    records: HashMap<u32, InspectionSourceState>,
}

impl SourceStateStore {
    /// The fixture is immutable after creation, so this read-only mapping remains stable.
    pub fn load_mmap(path: impl AsRef<Path>) -> Result<Self, Box<dyn std::error::Error>> {
        let file = File::open(path)?;
        // SAFETY: callers write and close this fixture before loading it and do not mutate it.
        let map = unsafe { MmapOptions::new().map(&file)? };
        let mut rows = memchr_iter(b'\n', &map);
        let Some(header_end) = rows.next() else {
            return Err("source-state fixture is empty".into());
        };
        if &map[..header_end] != b"episode_id,evidence_family,recommendation,confidence,signature_valid,payload_digest" {
            return Err("source-state fixture header mismatch".into());
        }
        let mut records = HashMap::with_capacity(256);
        let mut start = header_end + 1;
        for end in rows {
            if end <= start {
                return Err("source-state fixture contains an empty record".into());
            }
            let row = std::str::from_utf8(&map[start..end])?;
            let mut fields = row.split(',');
            let episode_id = parse_field::<u32>(&mut fields)?;
            let evidence_family = parse_field::<u8>(&mut fields)?;
            let recommendation =
                parse_choice(fields.next().ok_or("missing source recommendation")?)?;
            let confidence = parse_field::<u16>(&mut fields)?;
            let signature_valid = match fields.next() {
                Some("true") => true,
                Some("false") => false,
                _ => return Err("invalid source signature flag".into()),
            };
            let payload_digest = parse_digest(fields.next().ok_or("missing source digest")?)?;
            if fields.next().is_some() {
                return Err("source-state fixture has extra fields".into());
            }
            if source_digest(
                episode_id,
                evidence_family,
                recommendation,
                confidence,
                signature_valid,
            ) != payload_digest
            {
                return Err(
                    format!("source-state payload digest mismatch for {episode_id}").into(),
                );
            }
            let state = InspectionSourceState {
                episode_id,
                evidence_family,
                recommendation,
                confidence,
                signature_valid,
                payload_digest,
            };
            if records.insert(episode_id, state).is_some() {
                return Err(format!("duplicate source-state episode {episode_id}").into());
            }
            start = end + 1;
        }
        if start != map.len() {
            return Err("source-state fixture has an incomplete final record".into());
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

/// On-demand lookup against source state held outside the public observation frame.
pub struct InspectionTool<'a> {
    store: &'a SourceStateStore,
}

impl<'a> InspectionTool<'a> {
    pub fn new(store: &'a SourceStateStore) -> Self {
        Self { store }
    }

    pub fn query(
        &self,
        episode_id: u32,
    ) -> Result<(InspectionResult, u64), Box<dyn std::error::Error>> {
        let started = Instant::now();
        let state = self
            .store
            .get(episode_id)
            .ok_or("inspection source is absent")?;
        Ok((
            state.result(),
            started.elapsed().as_nanos().min(u64::MAX as u128) as u64,
        ))
    }
}

#[derive(FromBytes, IntoBytes, KnownLayout, Immutable, Unaligned)]
#[repr(C)]
struct ReceiptHeader {
    magic: [u8; 4],
    version_le: [u8; 2],
    reserved: [u8; 2],
}

impl ReceiptHeader {
    fn new() -> Self {
        Self {
            magic: RECEIPT_MAGIC,
            version_le: RECEIPT_VERSION.to_le_bytes(),
            reserved: [0; 2],
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct InspectionReceipt {
    pub sequence: u64,
    pub previous_hash: [u8; 32],
    pub lane: String,
    pub budget: usize,
    pub episode_id: u32,
    pub source_id: u16,
    pub result: InspectionResult,
    pub hash: [u8; 32],
}

#[derive(Serialize)]
struct ReceiptBody<'a> {
    sequence: u64,
    previous_hash: [u8; 32],
    lane: &'a str,
    budget: usize,
    episode_id: u32,
    source_id: u16,
    result: InspectionResult,
}

pub struct QueryReceiptLog {
    writer: BufWriter<File>,
    lane: String,
    budget: usize,
    sequence: u64,
    previous_hash: [u8; 32],
    bytes_written: u64,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct QueryReceiptStats {
    pub calls: usize,
    pub bytes: u64,
    pub identity: [u8; 32],
}

impl QueryReceiptLog {
    pub fn create(
        path: impl AsRef<Path>,
        lane: Lane,
        budget: usize,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let file = OpenOptions::new().write(true).create_new(true).open(path)?;
        let mut writer = BufWriter::with_capacity(8 * 1024, file);
        writer.write_all(ReceiptHeader::new().as_bytes())?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(Self {
            writer,
            lane: lane.label().to_owned(),
            budget,
            sequence: 0,
            previous_hash: [0; 32],
            bytes_written: HEADER_BYTES as u64,
        })
    }

    pub fn append(
        &mut self,
        episode_id: u32,
        result: InspectionResult,
    ) -> Result<(u64, [u8; 32]), Box<dyn std::error::Error>> {
        let source_id = 50 + result.evidence_family as u16;
        let body = ReceiptBody {
            sequence: self.sequence,
            previous_hash: self.previous_hash,
            lane: &self.lane,
            budget: self.budget,
            episode_id,
            source_id,
            result,
        };
        let hash = receipt_hash(&body)?;
        let envelope = InspectionReceipt {
            sequence: self.sequence,
            previous_hash: self.previous_hash,
            lane: self.lane.clone(),
            budget: self.budget,
            episode_id,
            source_id,
            result,
            hash,
        };
        let before = self.bytes_written;
        serde_json::to_writer(&mut self.writer, &envelope)?;
        self.writer.write_all(b"\n")?;
        self.writer.flush()?;
        self.writer.get_ref().sync_data()?;
        self.bytes_written = self.writer.get_ref().metadata()?.len();
        self.sequence += 1;
        self.previous_hash = hash;
        Ok((self.bytes_written - before, hash))
    }

    pub fn close(self) -> Result<(), Box<dyn std::error::Error>> {
        let mut writer = self.writer;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(())
    }
}

/// Maps the closed receipt log and verifies every result-bound link before returning its digest.
pub fn verify_receipt_log(
    path: impl AsRef<Path>,
    source_state: &SourceStateStore,
) -> Result<QueryReceiptStats, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    // SAFETY: the writer is closed before verification and no other process mutates this file.
    let map = unsafe { MmapOptions::new().map(&file)? };
    let (header, body) =
        ReceiptHeader::ref_from_prefix(&map).map_err(|_| "invalid receipt header")?;
    if header.magic != RECEIPT_MAGIC
        || header.version_le != RECEIPT_VERSION.to_le_bytes()
        || header.reserved != [0; 2]
    {
        return Err("unsupported inspection receipt header".into());
    }
    let mut previous_hash = [0u8; 32];
    let mut calls = 0usize;
    let mut start = 0usize;
    for end in memchr_iter(b'\n', body) {
        if end <= start {
            return Err("inspection receipt log contains an empty record".into());
        }
        let receipt: InspectionReceipt = serde_json::from_slice(&body[start..end])?;
        let expected = receipt_hash(&ReceiptBody {
            sequence: receipt.sequence,
            previous_hash: receipt.previous_hash,
            lane: &receipt.lane,
            budget: receipt.budget,
            episode_id: receipt.episode_id,
            source_id: receipt.source_id,
            result: receipt.result,
        })?;
        if receipt.sequence != calls as u64
            || receipt.previous_hash != previous_hash
            || receipt.hash != expected
            || receipt.source_id != 50 + receipt.result.evidence_family as u16
            || source_state
                .get(receipt.episode_id)
                .map(InspectionSourceState::result)
                != Some(receipt.result)
        {
            return Err(format!("inspection receipt chain mismatch at sequence {calls}").into());
        }
        previous_hash = receipt.hash;
        calls += 1;
        start = end + 1;
    }
    if start != body.len() {
        return Err("inspection receipt log has an incomplete final record".into());
    }
    Ok(QueryReceiptStats {
        calls,
        bytes: map.len() as u64,
        identity: previous_hash,
    })
}

pub fn write_source_fixture(
    path: impl AsRef<Path>,
    episodes: &[Episode],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(8 * 1024, File::create(path)?);
    writeln!(
        writer,
        "episode_id,evidence_family,recommendation,confidence,signature_valid,payload_digest"
    )?;
    for episode in episodes {
        let state = fixture_for(episode);
        writeln!(
            writer,
            "{},{},{},{},{},{}",
            state.episode_id,
            state.evidence_family,
            Choice::from_code(state.recommendation)
                .ok_or("fixture action is invalid")?
                .label(),
            state.confidence,
            state.signature_valid,
            hex(&state.payload_digest),
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

pub fn fixture_for(episode: &Episode) -> InspectionSourceState {
    let revision = hidden_revision(episode.stratum as usize, episode.within_stratum as usize);
    let truth = contract_action(episode.frame.features.goal, revision);
    let primary = episode.frame.features.primary_action;
    let recommendation = match episode.class {
        EpisodeClass::FreshAgreement
        | EpisodeClass::StalePrimarySplit
        | EpisodeClass::MisleadingAuditSplit
        | EpisodeClass::LowConfidenceAgreement => truth,
        EpisodeClass::StaleSharedWrong if episode.within_stratum.is_multiple_of(2) => truth,
        EpisodeClass::StaleSharedWrong => primary,
        EpisodeClass::FreshConsistentWrong if !episode.within_stratum.is_multiple_of(4) => truth,
        EpisodeClass::FreshConsistentWrong => primary,
        EpisodeClass::InspectionHarm => rotate(truth, 1),
        EpisodeClass::DisagreementWithoutValue => primary,
    };
    let evidence_family = episode.frame.inspection_domain;
    let confidence = if episode.class == EpisodeClass::InspectionHarm {
        985
    } else {
        975
    };
    let signature_valid = true;
    let payload_digest = source_digest(
        episode.id,
        evidence_family,
        recommendation as u8,
        confidence,
        signature_valid,
    );
    InspectionSourceState {
        episode_id: episode.id,
        evidence_family,
        recommendation: recommendation as u8,
        confidence,
        signature_valid,
        payload_digest,
    }
}

fn source_digest(
    id: u32,
    family: u8,
    recommendation: u8,
    confidence: u16,
    valid: bool,
) -> [u8; 32] {
    let mut hasher = Hasher::new();
    hasher.update(b"RDC-E005-INDEPENDENT-SOURCE-V1\0");
    hasher.update(&id.to_le_bytes());
    hasher.update(&[family, recommendation]);
    hasher.update(&confidence.to_le_bytes());
    hasher.update(&[u8::from(valid)]);
    *hasher.finalize().as_bytes()
}

fn receipt_hash(body: &ReceiptBody<'_>) -> Result<[u8; 32], serde_json::Error> {
    let bytes = serde_json::to_vec(body)?;
    let mut hasher = Hasher::new();
    hasher.update(b"RDC-E005-INSPECTION-RECEIPT-V1\0");
    hasher.update(&bytes);
    Ok(*hasher.finalize().as_bytes())
}

fn parse_field<T: std::str::FromStr>(
    fields: &mut std::str::Split<'_, char>,
) -> Result<T, Box<dyn std::error::Error>>
where
    T::Err: std::error::Error + 'static,
{
    Ok(fields.next().ok_or("missing source-state field")?.parse()?)
}

fn parse_choice(value: &str) -> Result<u8, Box<dyn std::error::Error>> {
    Choice::ALL
        .iter()
        .find(|choice| choice.label() == value)
        .map(|choice| *choice as u8)
        .ok_or_else(|| "unknown source recommendation".into())
}

fn parse_digest(value: &str) -> Result<[u8; 32], Box<dyn std::error::Error>> {
    if value.len() != 64 {
        return Err("source digest has the wrong width".into());
    }
    let mut digest = [0u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        digest[index] = (hex_value(pair[0])? << 4) | hex_value(pair[1])?;
    }
    Ok(digest)
}

fn hex_value(value: u8) -> Result<u8, Box<dyn std::error::Error>> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err("invalid source digest hex".into()),
    }
}

fn rotate(action: Choice, by: usize) -> Choice {
    Choice::ALL[(action as usize + by) % Choice::ALL.len()]
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(DIGITS[(byte >> 4) as usize] as char);
        out.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    out
}
