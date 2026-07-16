use std::fs::{File, OpenOptions};
use std::io::{Seek, SeekFrom, Write};
use std::mem::size_of;
use std::path::PathBuf;

use hashbrown::HashMap;
use memmap2::{Mmap, MmapOptions};
use phoenix_store_native_core::{NativeDecisionReceiptAppend, StoreError};
use phoenix_types::{
    NativeDecisionOutcomeOperation, NativeDecisionOutcomeReceipt, NativeDecisionReceipt,
    NativeDecisionRewardEvidenceReceipt, NativeDecisionRewardObservationReceipt,
};
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

use super::native_decision_reward_persistence::{
    decode_reward_observation, decode_reward_observation_payload,
    validate_reward_observation_lineage,
};
use super::PhoenixOvergraphStore;

const LOG_FILE_NAME: &str = "native-decision-receipts-v1.bin";
const RECORD_MAGIC: [u8; 8] = *b"PHXNDR01";
const RECORD_SCHEMA_VERSION: u16 = 1;
const KIND_DECISION: u8 = 1;
const KIND_OUTCOME: u8 = 2;
const KIND_REWARD_OBSERVATION: u8 = 3;
const KIND_REWARD_EVIDENCE: u8 = 4;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum RecordKind {
    Decision,
    Outcome,
    RewardObservation,
    RewardEvidence,
}

impl RecordKind {
    const fn byte(self) -> u8 {
        match self {
            Self::Decision => KIND_DECISION,
            Self::Outcome => KIND_OUTCOME,
            Self::RewardObservation => KIND_REWARD_OBSERVATION,
            Self::RewardEvidence => KIND_REWARD_EVIDENCE,
        }
    }

    fn from_byte(value: u8) -> Result<Self, StoreError> {
        match value {
            KIND_DECISION => Ok(Self::Decision),
            KIND_OUTCOME => Ok(Self::Outcome),
            KIND_REWARD_OBSERVATION => Ok(Self::RewardObservation),
            KIND_REWARD_EVIDENCE => Ok(Self::RewardEvidence),
            _ => Err(StoreError::Snapshot(format!(
                "unknown native decision record kind {value}"
            ))),
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub(super) struct RecordLocation {
    pub(super) offset: usize,
    pub(super) byte_len: usize,
    pub(super) kind: RecordKind,
}

#[derive(Default)]
pub(super) struct NativeDecisionReceiptIndex {
    valid_byte_len: usize,
    pub(super) by_receipt_id: HashMap<String, RecordLocation>,
    decision_by_decision_id: HashMap<String, RecordLocation>,
    decision_locations: Vec<RecordLocation>,
    outcomes_by_decision_receipt: HashMap<String, Vec<RecordLocation>>,
    pub(super) reward_observations_by_decision_receipt: HashMap<String, Vec<RecordLocation>>,
    pub(super) reward_evidence_by_decision_receipt: HashMap<String, Vec<RecordLocation>>,
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
struct RecordHeader {
    magic: [u8; 8],
    total_len: [u8; 4],
    schema_version: [u8; 2],
    kind: u8,
    reserved: u8,
    payload_len: [u8; 4],
    payload_blake3: [u8; 32],
}

pub(super) enum DecodedRecord {
    Decision(Box<NativeDecisionReceipt>),
    Outcome(Box<NativeDecisionOutcomeReceipt>),
    RewardObservation(Box<NativeDecisionRewardObservationReceipt>),
    RewardEvidence(Box<NativeDecisionRewardEvidenceReceipt>),
}

impl DecodedRecord {
    fn receipt_id(&self) -> &str {
        match self {
            Self::Decision(value) => value.receipt_id.as_str(),
            Self::Outcome(value) => value.receipt_id.as_str(),
            Self::RewardObservation(value) => value.receipt_id.as_str(),
            Self::RewardEvidence(value) => value.receipt_id.as_str(),
        }
    }
}

impl PhoenixOvergraphStore {
    pub(super) fn native_decision_receipt_log_path(&self) -> PathBuf {
        self.path.join(LOG_FILE_NAME)
    }

    pub(super) fn refresh_native_decision_receipt_index(
        &self,
        index: &mut NativeDecisionReceiptIndex,
    ) -> Result<(), StoreError> {
        let path = self.native_decision_receipt_log_path();
        let Some(mapped) = map_existing(&path)? else {
            *index = NativeDecisionReceiptIndex::default();
            return Ok(());
        };
        if index.valid_byte_len > mapped.len() {
            *index = NativeDecisionReceiptIndex::default();
        }
        let mut offset = index.valid_byte_len;
        while offset < mapped.len() {
            let Some(view) = RecordView::at(&mapped, offset)? else {
                break;
            };
            let decoded = view.decode()?;
            let location = RecordLocation {
                offset,
                byte_len: view.byte_len,
                kind: view.kind,
            };
            if index
                .by_receipt_id
                .insert(decoded.receipt_id().to_owned(), location)
                .is_some()
            {
                return Err(StoreError::Snapshot(
                    "duplicate native decision receipt identity".to_owned(),
                ));
            }
            match decoded {
                DecodedRecord::Decision(value) => {
                    if index
                        .decision_by_decision_id
                        .insert(value.decision_id.to_string(), location)
                        .is_some()
                    {
                        return Err(StoreError::Snapshot(
                            "duplicate native decision id".to_owned(),
                        ));
                    }
                    index.decision_locations.push(location);
                }
                DecodedRecord::Outcome(value) => index
                    .outcomes_by_decision_receipt
                    .entry(value.decision_receipt_id.to_string())
                    .or_default()
                    .push(location),
                DecodedRecord::RewardObservation(value) => index
                    .reward_observations_by_decision_receipt
                    .entry(value.decision_receipt_id.to_string())
                    .or_default()
                    .push(location),
                DecodedRecord::RewardEvidence(value) => index
                    .reward_evidence_by_decision_receipt
                    .entry(value.decision_receipt_id.to_string())
                    .or_default()
                    .push(location),
            }
            offset += view.byte_len;
        }
        index.valid_byte_len = offset;
        Ok(())
    }

    pub(super) fn append_decision(
        &self,
        receipt: &NativeDecisionReceipt,
    ) -> Result<NativeDecisionReceiptAppend, StoreError> {
        receipt
            .validate()
            .map_err(|error| StoreError::Schema(error.to_string()))?;
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        if let Some(existing) = existing_record(self, &index, receipt.receipt_id.as_str())? {
            return match existing {
                DecodedRecord::Decision(value) if value.as_ref() == receipt => {
                    Ok(NativeDecisionReceiptAppend::AlreadyPresent {
                        receipt_id: receipt.receipt_id.to_string(),
                    })
                }
                _ => Err(StoreError::Query(format!(
                    "native decision receipt '{}' stores different content or kind",
                    receipt.receipt_id
                ))),
            };
        }
        if index
            .decision_by_decision_id
            .contains_key(receipt.decision_id.as_str())
        {
            return Err(StoreError::Query(format!(
                "native decision '{}' already has an immutable receipt",
                receipt.decision_id
            )));
        }
        let encoded = encode_record(RecordKind::Decision, receipt)?;
        append_encoded(self, &mut index, &encoded)?;
        Ok(NativeDecisionReceiptAppend::Appended {
            byte_len: encoded.len(),
        })
    }

    pub(super) fn append_outcome(
        &self,
        receipt: &NativeDecisionOutcomeReceipt,
    ) -> Result<NativeDecisionReceiptAppend, StoreError> {
        receipt
            .validate()
            .map_err(|error| StoreError::Schema(error.to_string()))?;
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        if let Some(existing) = existing_record(self, &index, receipt.receipt_id.as_str())? {
            return match existing {
                DecodedRecord::Outcome(value) if value.as_ref() == receipt => {
                    Ok(NativeDecisionReceiptAppend::AlreadyPresent {
                        receipt_id: receipt.receipt_id.to_string(),
                    })
                }
                _ => Err(StoreError::Query(format!(
                    "native decision outcome receipt '{}' stores different content or kind",
                    receipt.receipt_id
                ))),
            };
        }
        let mapped = map_existing(&self.native_decision_receipt_log_path())?.ok_or_else(|| {
            StoreError::Query("native decision outcome has no decision receipt".to_owned())
        })?;
        let decision_location = index
            .by_receipt_id
            .get(receipt.decision_receipt_id.as_str())
            .copied()
            .filter(|location| location.kind == RecordKind::Decision)
            .ok_or_else(|| {
                StoreError::Query("native decision outcome has no decision receipt".to_owned())
            })?;
        let decision = decode_decision(&mapped, decision_location)?;
        if decision.decision_id != receipt.decision_id
            || !decision
                .candidates
                .iter()
                .any(|candidate| candidate.action_identity == receipt.candidate_action_identity)
        {
            return Err(StoreError::Query(
                "native decision outcome binding mismatch".to_owned(),
            ));
        }
        validate_append_lineage(&mapped, &index, receipt)?;
        drop(mapped);
        let encoded = encode_record(RecordKind::Outcome, receipt)?;
        append_encoded(self, &mut index, &encoded)?;
        Ok(NativeDecisionReceiptAppend::Appended {
            byte_len: encoded.len(),
        })
    }

    pub(super) fn append_reward_observation(
        &self,
        receipt: &NativeDecisionRewardObservationReceipt,
    ) -> Result<NativeDecisionReceiptAppend, StoreError> {
        receipt
            .validate()
            .map_err(|error| StoreError::Schema(error.to_string()))?;
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        if let Some(existing) = existing_record(self, &index, receipt.receipt_id.as_str())? {
            return match existing {
                DecodedRecord::RewardObservation(value) if value.as_ref() == receipt => {
                    Ok(NativeDecisionReceiptAppend::AlreadyPresent {
                        receipt_id: receipt.receipt_id.to_string(),
                    })
                }
                _ => Err(StoreError::Query(format!(
                    "native reward observation '{}' stores different content or kind",
                    receipt.receipt_id
                ))),
            };
        }
        let mapped = map_existing(&self.native_decision_receipt_log_path())?.ok_or_else(|| {
            StoreError::Query("native reward observation has no decision receipt".to_owned())
        })?;
        let decision_location = index
            .by_receipt_id
            .get(receipt.decision_receipt_id.as_str())
            .copied()
            .filter(|location| location.kind == RecordKind::Decision)
            .ok_or_else(|| {
                StoreError::Query("native reward observation has no decision receipt".to_owned())
            })?;
        let decision = decode_decision(&mapped, decision_location)?;
        if decision.decision_id != receipt.decision_id
            || !decision
                .candidates
                .iter()
                .any(|candidate| candidate.action_identity == receipt.candidate_action_identity)
        {
            return Err(StoreError::Query(
                "native reward observation binding mismatch".to_owned(),
            ));
        }
        validate_reward_observation_lineage(&mapped, &index, receipt)?;
        drop(mapped);
        let encoded = encode_record(RecordKind::RewardObservation, receipt)?;
        append_encoded(self, &mut index, &encoded)?;
        Ok(NativeDecisionReceiptAppend::Appended {
            byte_len: encoded.len(),
        })
    }

    pub(super) fn load_decision(
        &self,
        receipt_id: &str,
    ) -> Result<Option<NativeDecisionReceipt>, StoreError> {
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        let Some(location) = index
            .by_receipt_id
            .get(receipt_id)
            .copied()
            .filter(|location| location.kind == RecordKind::Decision)
        else {
            return Ok(None);
        };
        let mapped = required_map(&self.native_decision_receipt_log_path())?;
        decode_decision(&mapped, location).map(Some)
    }

    pub(super) fn load_decision_by_decision_id(
        &self,
        decision_id: &str,
    ) -> Result<Option<NativeDecisionReceipt>, StoreError> {
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        let Some(location) = index.decision_by_decision_id.get(decision_id).copied() else {
            return Ok(None);
        };
        let mapped = required_map(&self.native_decision_receipt_log_path())?;
        decode_decision(&mapped, location).map(Some)
    }

    pub(super) fn load_decisions(&self) -> Result<Vec<NativeDecisionReceipt>, StoreError> {
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        if index.decision_locations.is_empty() {
            return Ok(Vec::new());
        }
        let mapped = required_map(&self.native_decision_receipt_log_path())?;
        index
            .decision_locations
            .iter()
            .copied()
            .map(|location| decode_decision(&mapped, location))
            .collect()
    }

    pub(super) fn load_outcome(
        &self,
        receipt_id: &str,
    ) -> Result<Option<NativeDecisionOutcomeReceipt>, StoreError> {
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        let Some(location) = index
            .by_receipt_id
            .get(receipt_id)
            .copied()
            .filter(|location| location.kind == RecordKind::Outcome)
        else {
            return Ok(None);
        };
        let mapped = required_map(&self.native_decision_receipt_log_path())?;
        decode_outcome(&mapped, location).map(Some)
    }

    pub(super) fn load_outcomes(
        &self,
        decision_receipt_id: &str,
    ) -> Result<Vec<NativeDecisionOutcomeReceipt>, StoreError> {
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        let Some(locations) = index.outcomes_by_decision_receipt.get(decision_receipt_id) else {
            return Ok(Vec::new());
        };
        let mapped = required_map(&self.native_decision_receipt_log_path())?;
        locations
            .iter()
            .copied()
            .map(|location| decode_outcome(&mapped, location))
            .collect()
    }

    pub(super) fn load_reward_observation(
        &self,
        receipt_id: &str,
    ) -> Result<Option<NativeDecisionRewardObservationReceipt>, StoreError> {
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        let Some(location) = index
            .by_receipt_id
            .get(receipt_id)
            .copied()
            .filter(|location| location.kind == RecordKind::RewardObservation)
        else {
            return Ok(None);
        };
        let mapped = required_map(&self.native_decision_receipt_log_path())?;
        decode_reward_observation(&mapped, location).map(Some)
    }

    pub(super) fn load_reward_observations(
        &self,
        decision_receipt_id: &str,
    ) -> Result<Vec<NativeDecisionRewardObservationReceipt>, StoreError> {
        let mut index = self
            .native_decision_receipt_index
            .lock()
            .map_err(|_| StoreError::Query("native decision receipt index poisoned".to_owned()))?;
        self.refresh_native_decision_receipt_index(&mut index)?;
        let Some(locations) = index
            .reward_observations_by_decision_receipt
            .get(decision_receipt_id)
        else {
            return Ok(Vec::new());
        };
        let mapped = required_map(&self.native_decision_receipt_log_path())?;
        locations
            .iter()
            .copied()
            .map(|location| decode_reward_observation(&mapped, location))
            .collect()
    }
}

fn validate_append_lineage(
    mapped: &[u8],
    index: &NativeDecisionReceiptIndex,
    receipt: &NativeDecisionOutcomeReceipt,
) -> Result<(), StoreError> {
    let locations = index
        .outcomes_by_decision_receipt
        .get(receipt.decision_receipt_id.as_str())
        .map(Vec::as_slice)
        .unwrap_or_default();
    let mut prior = locations
        .iter()
        .copied()
        .map(|location| decode_outcome(mapped, location))
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .filter(|outcome| outcome.candidate_action_identity == receipt.candidate_action_identity)
        .collect::<Vec<_>>();
    prior.sort_unstable_by_key(|outcome| outcome.observed_at);
    match prior.last() {
        None if receipt.operation != NativeDecisionOutcomeOperation::Observe => Err(
            StoreError::Query("first native decision outcome must observe".to_owned()),
        ),
        None => Ok(()),
        Some(latest)
            if receipt.operation == NativeDecisionOutcomeOperation::Observe
                || receipt.predecessor_outcome_receipt_id.as_ref() != Some(&latest.receipt_id)
                || receipt.observed_at <= latest.observed_at =>
        {
            Err(StoreError::Query(
                "native decision outcome must extend the latest immutable receipt".to_owned(),
            ))
        }
        Some(_) => Ok(()),
    }
}

pub(super) fn append_encoded(
    store: &PhoenixOvergraphStore,
    index: &mut NativeDecisionReceiptIndex,
    encoded: &[u8],
) -> Result<(), StoreError> {
    let path = store.native_decision_receipt_log_path();
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path)
        .map_err(io_error)?;
    file.set_len(index.valid_byte_len as u64)
        .map_err(io_error)?;
    file.seek(SeekFrom::End(0)).map_err(io_error)?;
    file.write_all(encoded).map_err(io_error)?;
    file.sync_data().map_err(io_error)?;
    // Rebuild only the newly durable tail through the same verifier used at restart.
    store.refresh_native_decision_receipt_index(index)
}

pub(super) fn existing_record(
    store: &PhoenixOvergraphStore,
    index: &NativeDecisionReceiptIndex,
    receipt_id: &str,
) -> Result<Option<DecodedRecord>, StoreError> {
    let Some(location) = index.by_receipt_id.get(receipt_id).copied() else {
        return Ok(None);
    };
    let mapped = required_map(&store.native_decision_receipt_log_path())?;
    decode_location(&mapped, location).map(Some)
}

pub(super) fn encode_record<T: serde::Serialize>(
    kind: RecordKind,
    value: &T,
) -> Result<Vec<u8>, StoreError> {
    let payload = rmp_serde::to_vec_named(value)
        .map_err(|error| StoreError::Snapshot(format!("native decision encode: {error}")))?;
    let total_len = size_of::<RecordHeader>()
        .checked_add(payload.len())
        .ok_or_else(|| StoreError::Snapshot("native decision record overflow".to_owned()))?;
    let header = RecordHeader {
        magic: RECORD_MAGIC,
        total_len: checked_u32(total_len, "record length")?.to_le_bytes(),
        schema_version: RECORD_SCHEMA_VERSION.to_le_bytes(),
        kind: kind.byte(),
        reserved: 0,
        payload_len: checked_u32(payload.len(), "payload length")?.to_le_bytes(),
        payload_blake3: *blake3::hash(&payload).as_bytes(),
    };
    let mut bytes = Vec::with_capacity(total_len);
    bytes.extend_from_slice(header.as_bytes());
    bytes.extend_from_slice(&payload);
    Ok(bytes)
}

struct RecordView<'a> {
    payload: &'a [u8],
    byte_len: usize,
    kind: RecordKind,
}

impl<'a> RecordView<'a> {
    fn at(bytes: &'a [u8], offset: usize) -> Result<Option<Self>, StoreError> {
        if bytes.len().saturating_sub(offset) < size_of::<RecordHeader>() {
            return Ok(None);
        }
        let header_bytes = &bytes[offset..offset + size_of::<RecordHeader>()];
        let header = *Ref::<_, RecordHeader>::new_unaligned(header_bytes)
            .ok_or_else(|| StoreError::Snapshot("invalid native decision header".to_owned()))?;
        if header.magic != RECORD_MAGIC
            || u16::from_le_bytes(header.schema_version) != RECORD_SCHEMA_VERSION
            || header.reserved != 0
        {
            return Err(StoreError::Snapshot(format!(
                "invalid native decision header at byte {offset}"
            )));
        }
        let byte_len = u32::from_le_bytes(header.total_len) as usize;
        let payload_len = u32::from_le_bytes(header.payload_len) as usize;
        if byte_len != size_of::<RecordHeader>() + payload_len {
            return Err(StoreError::Snapshot(
                "native decision record length mismatch".to_owned(),
            ));
        }
        let Some(end) = offset.checked_add(byte_len) else {
            return Err(StoreError::Snapshot(
                "native decision record offset overflow".to_owned(),
            ));
        };
        if end > bytes.len() {
            return Ok(None);
        }
        let payload = &bytes[offset + size_of::<RecordHeader>()..end];
        if blake3::hash(payload).as_bytes() != &header.payload_blake3 {
            return Err(StoreError::Snapshot(
                "native decision payload checksum mismatch".to_owned(),
            ));
        }
        Ok(Some(Self {
            payload,
            byte_len,
            kind: RecordKind::from_byte(header.kind)?,
        }))
    }

    fn decode(&self) -> Result<DecodedRecord, StoreError> {
        match self.kind {
            RecordKind::Decision => decode_decision_payload(self.payload)
                .map(Box::new)
                .map(DecodedRecord::Decision),
            RecordKind::Outcome => decode_outcome_payload(self.payload)
                .map(Box::new)
                .map(DecodedRecord::Outcome),
            RecordKind::RewardObservation => decode_reward_observation_payload(self.payload)
                .map(Box::new)
                .map(DecodedRecord::RewardObservation),
            RecordKind::RewardEvidence => {
                super::native_decision_evidence_persistence::decode_reward_evidence_payload(
                    self.payload,
                )
                .map(Box::new)
                .map(DecodedRecord::RewardEvidence)
            }
        }
    }
}

pub(super) fn decode_location(
    mapped: &[u8],
    location: RecordLocation,
) -> Result<DecodedRecord, StoreError> {
    let view = RecordView::at(mapped, location.offset)?
        .filter(|view| view.byte_len == location.byte_len && view.kind == location.kind)
        .ok_or_else(|| StoreError::Snapshot("missing native decision record".to_owned()))?;
    view.decode()
}

fn decode_decision(
    mapped: &[u8],
    location: RecordLocation,
) -> Result<NativeDecisionReceipt, StoreError> {
    match decode_location(mapped, location)? {
        DecodedRecord::Decision(value) => Ok(*value),
        DecodedRecord::Outcome(_)
        | DecodedRecord::RewardObservation(_)
        | DecodedRecord::RewardEvidence(_) => Err(StoreError::Snapshot(
            "native decision record kind mismatch".to_owned(),
        )),
    }
}

fn decode_outcome(
    mapped: &[u8],
    location: RecordLocation,
) -> Result<NativeDecisionOutcomeReceipt, StoreError> {
    match decode_location(mapped, location)? {
        DecodedRecord::Outcome(value) => Ok(*value),
        DecodedRecord::Decision(_)
        | DecodedRecord::RewardObservation(_)
        | DecodedRecord::RewardEvidence(_) => Err(StoreError::Snapshot(
            "native decision outcome record kind mismatch".to_owned(),
        )),
    }
}

fn decode_decision_payload(payload: &[u8]) -> Result<NativeDecisionReceipt, StoreError> {
    let value: NativeDecisionReceipt = rmp_serde::from_slice(payload)
        .map_err(|error| StoreError::Snapshot(format!("native decision decode: {error}")))?;
    value
        .validate()
        .map_err(|error| StoreError::Schema(error.to_string()))?;
    Ok(value)
}

fn decode_outcome_payload(payload: &[u8]) -> Result<NativeDecisionOutcomeReceipt, StoreError> {
    let value: NativeDecisionOutcomeReceipt = rmp_serde::from_slice(payload).map_err(|error| {
        StoreError::Snapshot(format!("native decision outcome decode: {error}"))
    })?;
    value
        .validate()
        .map_err(|error| StoreError::Schema(error.to_string()))?;
    Ok(value)
}

fn map_existing(path: &PathBuf) -> Result<Option<Mmap>, StoreError> {
    let Some(file) = File::open(path)
        .map(Some)
        .or_else(|error| {
            if error.kind() == std::io::ErrorKind::NotFound {
                Ok(None)
            } else {
                Err(error)
            }
        })
        .map_err(io_error)?
    else {
        return Ok(None);
    };
    let metadata = file.metadata().map_err(io_error)?;
    if metadata.len() == 0 {
        return Ok(None);
    }
    let mapped = unsafe { MmapOptions::new().map(&file).map_err(io_error)? };
    Ok(Some(mapped))
}

pub(super) fn required_map(path: &PathBuf) -> Result<Mmap, StoreError> {
    map_existing(path)?.ok_or_else(|| {
        StoreError::Snapshot("native decision receipt log is unavailable".to_owned())
    })
}

fn checked_u32(value: usize, label: &str) -> Result<u32, StoreError> {
    u32::try_from(value)
        .map_err(|_| StoreError::Snapshot(format!("native decision {label} exceeds u32")))
}

fn io_error(error: std::io::Error) -> StoreError {
    StoreError::Snapshot(format!("native decision receipt IO: {error}"))
}
