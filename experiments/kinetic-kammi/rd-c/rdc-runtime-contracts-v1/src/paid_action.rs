use std::{
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::Path,
};

use blake3::Hasher;
use hashbrown::HashMap;
use memchr::memchr_iter;
use memmap2::MmapOptions;
use serde::{Deserialize, Serialize};

const JOURNAL_HEADER: &[u8] = b"RDC-PAID-ACTION\t1\n";
const EVENT_DOMAIN: &[u8] = b"RDC-PAID-ACTION-RECEIPT-V1\0";

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
pub struct RequestId(pub [u8; 16]);

impl RequestId {
    pub fn derive(
        namespace: &[u8],
        run_id: u64,
        bank_id: u32,
        lane: u8,
        budget: u16,
        episode_id: u32,
    ) -> Self {
        let mut hasher = Hasher::new();
        hasher.update(b"RDC-STABLE-REQUEST-ID-V1\0");
        hasher.update(&(namespace.len() as u64).to_le_bytes());
        hasher.update(namespace);
        hasher.update(&run_id.to_le_bytes());
        hasher.update(&bank_id.to_le_bytes());
        hasher.update(&[lane]);
        hasher.update(&budget.to_le_bytes());
        hasher.update(&episode_id.to_le_bytes());
        let mut id = [0; 16];
        id.copy_from_slice(&hasher.finalize().as_bytes()[..16]);
        Self(id)
    }
}

/// Fixed-size opaque endpoint result. The caller owns its versioned encoding.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[repr(C)]
pub struct ResultBytes {
    pub first: [u8; 32],
    pub second: [u8; 32],
}

impl ResultBytes {
    pub fn from_array(value: [u8; 64]) -> Self {
        Self {
            first: value[..32].try_into().unwrap(),
            second: value[32..].try_into().unwrap(),
        }
    }

    pub fn into_array(self) -> [u8; 64] {
        let mut value = [0; 64];
        value[..32].copy_from_slice(&self.first);
        value[32..].copy_from_slice(&self.second);
        value
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EndpointResponse {
    pub result: ResultBytes,
    /// True means this request ID has incurred its one endpoint charge.
    pub charged_for_request: bool,
}

/// The service must durably deduplicate `request_id` and return its cached result on retry.
pub trait PaidActionEndpoint {
    fn invoke(
        &mut self,
        request_id: RequestId,
        cost_units: u32,
        request: &[u8],
    ) -> Result<EndpointResponse, String>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CrashPoint {
    None,
    AfterIntent,
    AfterEndpointResponse,
    AfterOutcomeReceipt,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct JournalStats {
    pub intents: usize,
    pub endpoint_attempts: usize,
    pub retries: usize,
    pub paid_requests: usize,
    pub paid_cost_units: u64,
    pub result_receipts: usize,
    pub unresolved: usize,
    pub bytes: u64,
    pub identity: [u8; 32],
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
enum EventKind {
    Intent,
    Attempt,
    Outcome,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Event {
    kind: EventKind,
    request_id: RequestId,
    request_digest: [u8; 32],
    attempt: u32,
    cost_units: u32,
    request_payload: Vec<u8>,
    charged_for_request: bool,
    result: ResultBytes,
    previous_hash: [u8; 32],
    hash: [u8; 32],
}

impl Event {
    fn new(
        kind: EventKind,
        request_id: RequestId,
        request_digest: [u8; 32],
        cost_units: u32,
        previous_hash: [u8; 32],
    ) -> Self {
        Self {
            kind,
            request_id,
            request_digest,
            attempt: 0,
            cost_units,
            request_payload: Vec::new(),
            charged_for_request: false,
            result: ResultBytes::default(),
            previous_hash,
            hash: [0; 32],
        }
    }

    fn seal(&mut self) -> Result<(), String> {
        self.hash = [0; 32];
        let encoded = serde_json::to_vec(self).map_err(|error| error.to_string())?;
        let mut hasher = Hasher::new();
        hasher.update(EVENT_DOMAIN);
        hasher.update(&encoded);
        self.hash = *hasher.finalize().as_bytes();
        Ok(())
    }

    fn verify(&self, expected_previous: [u8; 32]) -> Result<(), String> {
        if self.previous_hash != expected_previous {
            return Err("paid-action journal hash chain predecessor mismatch".into());
        }
        let mut copy = self.clone();
        let expected = copy.hash;
        copy.seal()?;
        if copy.hash != expected {
            return Err("paid-action journal event hash mismatch".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
struct Progress {
    request_digest: [u8; 32],
    request_payload: Vec<u8>,
    cost_units: u32,
    attempts: u32,
    result: Option<ResultBytes>,
    charged_for_request: bool,
}

pub struct QueryJournal {
    writer: BufWriter<File>,
    progress: HashMap<RequestId, Progress>,
    previous_hash: [u8; 32],
    bytes: u64,
}

impl QueryJournal {
    pub fn create(path: impl AsRef<Path>) -> Result<Self, String> {
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(|error| error.to_string())?;
        let mut writer = BufWriter::with_capacity(8 * 1024, file);
        writer
            .write_all(JOURNAL_HEADER)
            .map_err(|error| error.to_string())?;
        writer.flush().map_err(|error| error.to_string())?;
        writer
            .get_ref()
            .sync_all()
            .map_err(|error| error.to_string())?;
        Ok(Self {
            writer,
            progress: HashMap::with_capacity(64),
            previous_hash: [0; 32],
            bytes: JOURNAL_HEADER.len() as u64,
        })
    }

    pub fn resume(path: impl AsRef<Path>) -> Result<Self, String> {
        let path = path.as_ref();
        let file = File::open(path).map_err(|error| error.to_string())?;
        // SAFETY: the receipt log is immutable during this read-only recovery pass.
        let map = unsafe { MmapOptions::new().map(&file) }.map_err(|error| error.to_string())?;
        let mut newlines = memchr_iter(b'\n', &map);
        let header_end = newlines
            .next()
            .ok_or("paid-action journal header is incomplete")?;
        if &map[..=header_end] != JOURNAL_HEADER {
            return Err("paid-action journal header mismatch".into());
        }
        let mut progress = HashMap::with_capacity(64);
        let mut previous_hash = [0; 32];
        let mut start = header_end + 1;
        for end in newlines {
            if end <= start {
                return Err("paid-action journal has an empty event".into());
            }
            let event: Event = serde_json::from_slice(&map[start..end])
                .map_err(|error| format!("invalid paid-action event: {error}"))?;
            event.verify(previous_hash)?;
            apply_event(&mut progress, &event)?;
            previous_hash = event.hash;
            start = end + 1;
        }
        if start != map.len() {
            return Err("paid-action journal final event is incomplete".into());
        }
        let bytes = map.len() as u64;
        drop(map);
        let writer = OpenOptions::new()
            .append(true)
            .open(path)
            .map_err(|error| error.to_string())?;
        Ok(Self {
            writer: BufWriter::with_capacity(8 * 1024, writer),
            progress,
            previous_hash,
            bytes,
        })
    }

    pub fn execute<E: PaidActionEndpoint>(
        &mut self,
        endpoint: &mut E,
        request_id: RequestId,
        cost_units: u32,
        request: &[u8],
        crash: CrashPoint,
    ) -> Result<ResultBytes, String> {
        let request_digest = *blake3::hash(request).as_bytes();
        if let Some(progress) = self.progress.get(&request_id) {
            if progress.request_digest != request_digest
                || progress.request_payload != request
                || progress.cost_units != cost_units
            {
                return Err("stable request ID was reused with different input or cost".into());
            }
            if let Some(result) = progress.result {
                return Ok(result);
            }
        } else {
            let mut intent = Event::new(
                EventKind::Intent,
                request_id,
                request_digest,
                cost_units,
                self.previous_hash,
            );
            intent.request_payload.extend_from_slice(request);
            self.append(intent)?;
            self.progress.insert(
                request_id,
                Progress {
                    request_digest,
                    request_payload: request.to_vec(),
                    cost_units,
                    attempts: 0,
                    result: None,
                    charged_for_request: false,
                },
            );
            if crash == CrashPoint::AfterIntent {
                return Err("injected crash after durable paid-action intent".into());
            }
        }
        let progress = self
            .progress
            .get(&request_id)
            .ok_or("request progress missing")?;
        let attempt = progress
            .attempts
            .checked_add(1)
            .ok_or("attempt counter overflow")?;
        let mut event = Event::new(
            EventKind::Attempt,
            request_id,
            request_digest,
            cost_units,
            self.previous_hash,
        );
        event.attempt = attempt;
        self.append(event)?;
        self.progress
            .get_mut(&request_id)
            .ok_or("request progress missing")?
            .attempts = attempt;

        let request_payload = self
            .progress
            .get(&request_id)
            .ok_or("request progress missing")?
            .request_payload
            .clone();
        let response = endpoint.invoke(request_id, cost_units, &request_payload)?;
        if crash == CrashPoint::AfterEndpointResponse {
            return Err("injected crash after paid endpoint response".into());
        }
        let mut event = Event::new(
            EventKind::Outcome,
            request_id,
            request_digest,
            cost_units,
            self.previous_hash,
        );
        event.attempt = attempt;
        event.charged_for_request = response.charged_for_request;
        event.result = response.result;
        self.append(event)?;
        let progress = self
            .progress
            .get_mut(&request_id)
            .ok_or("request progress missing")?;
        progress.result = Some(response.result);
        progress.charged_for_request = response.charged_for_request;
        if crash == CrashPoint::AfterOutcomeReceipt {
            return Err("injected crash after durable paid-action outcome".into());
        }
        Ok(response.result)
    }

    pub fn result(&self, request_id: RequestId) -> Option<ResultBytes> {
        self.progress
            .get(&request_id)
            .and_then(|progress| progress.result)
    }

    pub fn stats(&self) -> JournalStats {
        let mut stats = JournalStats {
            intents: self.progress.len(),
            bytes: self.bytes,
            identity: self.previous_hash,
            ..JournalStats::default()
        };
        for progress in self.progress.values() {
            stats.endpoint_attempts += progress.attempts as usize;
            stats.retries += progress.attempts.saturating_sub(1) as usize;
            stats.paid_requests += progress.charged_for_request as usize;
            stats.paid_cost_units += if progress.charged_for_request {
                progress.cost_units as u64
            } else {
                0
            };
            stats.result_receipts += progress.result.is_some() as usize;
        }
        stats.unresolved = stats.intents.saturating_sub(stats.result_receipts);
        stats
    }

    fn append(&mut self, mut event: Event) -> Result<(), String> {
        event.previous_hash = self.previous_hash;
        event.seal()?;
        let encoded = serde_json::to_vec(&event).map_err(|error| error.to_string())?;
        self.writer
            .write_all(&encoded)
            .map_err(|error| error.to_string())?;
        self.writer
            .write_all(b"\n")
            .map_err(|error| error.to_string())?;
        self.writer.flush().map_err(|error| error.to_string())?;
        self.writer
            .get_ref()
            .sync_all()
            .map_err(|error| error.to_string())?;
        self.bytes += encoded.len() as u64 + 1;
        self.previous_hash = event.hash;
        Ok(())
    }
}

fn apply_event(progress: &mut HashMap<RequestId, Progress>, event: &Event) -> Result<(), String> {
    match event.kind {
        EventKind::Intent => {
            if event.attempt != 0
                || event.charged_for_request
                || event.result != ResultBytes::default()
                || blake3::hash(&event.request_payload).as_bytes() != &event.request_digest
                || progress.contains_key(&event.request_id)
            {
                return Err("invalid or duplicate paid-action intent".into());
            }
            progress.insert(
                event.request_id,
                Progress {
                    request_digest: event.request_digest,
                    request_payload: event.request_payload.clone(),
                    cost_units: event.cost_units,
                    attempts: 0,
                    result: None,
                    charged_for_request: false,
                },
            );
        }
        EventKind::Attempt => {
            let state = progress
                .get_mut(&event.request_id)
                .ok_or("paid-action attempt has no intent")?;
            validate_identity(state, event)?;
            if event.attempt != state.attempts + 1
                || event.charged_for_request
                || event.result != ResultBytes::default()
                || !event.request_payload.is_empty()
                || state.result.is_some()
            {
                return Err("invalid paid-action attempt sequence".into());
            }
            state.attempts = event.attempt;
        }
        EventKind::Outcome => {
            let state = progress
                .get_mut(&event.request_id)
                .ok_or("paid-action outcome has no intent")?;
            validate_identity(state, event)?;
            if event.attempt != state.attempts
                || event.attempt == 0
                || !event.request_payload.is_empty()
                || state.result.is_some()
            {
                return Err("invalid paid-action outcome sequence".into());
            }
            state.result = Some(event.result);
            state.charged_for_request = event.charged_for_request;
        }
    }
    Ok(())
}

fn validate_identity(state: &Progress, event: &Event) -> Result<(), String> {
    if event.request_digest != state.request_digest || event.cost_units != state.cost_units {
        return Err("paid-action event input differs from durable intent".into());
    }
    Ok(())
}
