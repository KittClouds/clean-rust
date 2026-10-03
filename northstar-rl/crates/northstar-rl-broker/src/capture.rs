use std::{fs::OpenOptions, io::Write, path::Path};

use bytemuck::{Pod, Zeroable, cast_slice, try_cast_slice};
use memmap2::Mmap;
use northstar_rl_core::{Digest, identity};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout};

use crate::{
    BROKER_OBSERVATION_TAPE_V1, BrokerObservationTape, BrokerQuoteObservation, Error, Result,
};

const MAGIC: &[u8; 8] = b"NSBRO1\0\0";

/// Fixed-width, little-endian-host capture row. Prices are scaled binary64 because
/// exact conversion and non-finite rejection happen before this boundary.
#[derive(Clone, Copy, Debug, FromBytes, Immutable, IntoBytes, KnownLayout, Pod, Zeroable)]
#[repr(C)]
pub struct PackedBrokerQuote {
    pub event_time_ns: i64,
    pub received_time_ns: i64,
    pub recorded_time_ns: i64,
    pub bid: f64,
    pub ask: f64,
    pub last: f64,
    pub instrument_id: u32,
    pub connection_state: u8,
    pub has_last: u8,
    pub reserved: [u8; 2],
    pub raw_payload_hash: [u8; 32],
    pub normalized_payload_hash: [u8; 32],
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct BrokerCaptureHeader {
    pub schema_version: String,
    pub broker: String,
    pub account_environment: String,
    pub account_id_hash: Digest,
    pub row_count: u64,
    pub first_time_ns: i64,
    pub last_time_ns: i64,
    pub payload_hash: Digest,
    pub capture_id: Digest,
}

impl PackedBrokerQuote {
    fn from_observation(row: &BrokerQuoteObservation) -> Result<Self> {
        if !row.bid.is_finite() || !row.ask.is_finite() || row.last.is_some_and(|v| !v.is_finite())
        {
            return Err(Error::Contract("non-finite broker quote rejected".into()));
        }
        Ok(Self {
            event_time_ns: row.event_time_ns,
            received_time_ns: row.received_time_ns,
            recorded_time_ns: row.recorded_time_ns,
            bid: row.bid,
            ask: row.ask,
            last: row.last.unwrap_or_default(),
            instrument_id: row.instrument_id,
            connection_state: row.connection_state as u8,
            has_last: u8::from(row.last.is_some()),
            reserved: [0; 2],
            raw_payload_hash: row.raw_payload_hash.bytes(),
            normalized_payload_hash: row.normalized_payload_hash.bytes(),
        })
    }
}

pub fn seal_broker_capture(
    path: impl AsRef<Path>,
    tape: &BrokerObservationTape,
) -> Result<BrokerCaptureHeader> {
    if tape.schema_version != BROKER_OBSERVATION_TAPE_V1 || tape.rows.is_empty() {
        return Err(Error::Contract(
            "broker capture requires V1 and at least one row".into(),
        ));
    }
    let mut packed = Vec::with_capacity(tape.rows.len());
    for row in &tape.rows {
        packed.push(PackedBrokerQuote::from_observation(row)?);
    }
    let payload = cast_slice::<PackedBrokerQuote, u8>(&packed);
    let payload_hash = Digest::hash(b"northstar-broker-capture-payload-v1", payload);
    let mut header = BrokerCaptureHeader {
        schema_version: BROKER_OBSERVATION_TAPE_V1.into(),
        broker: tape.rows[0].broker.clone(),
        account_environment: tape.rows[0].account_environment.clone(),
        account_id_hash: tape.account_id_hash,
        row_count: packed.len() as u64,
        first_time_ns: packed[0].event_time_ns,
        last_time_ns: packed[packed.len() - 1].event_time_ns,
        payload_hash,
        capture_id: Digest::ZERO,
    };
    header.capture_id = identity(b"northstar-broker-capture-v1", &header)?;
    let header_bytes = serde_json::to_vec(&header)?;
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(path)?;
    file.write_all(MAGIC)?;
    file.write_all(&(header_bytes.len() as u64).to_le_bytes())?;
    file.write_all(&header_bytes)?;
    let padding = (align_of::<PackedBrokerQuote>()
        - ((16 + header_bytes.len()) % align_of::<PackedBrokerQuote>()))
        % align_of::<PackedBrokerQuote>();
    file.write_all(&vec![0_u8; padding])?;
    file.write_all(payload)?;
    file.sync_all()?;
    Ok(header)
}

pub struct MappedBrokerCapture {
    mmap: Mmap,
    header: BrokerCaptureHeader,
    row_offset: usize,
}

impl MappedBrokerCapture {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let file = std::fs::File::open(path)?;
        // SAFETY: mapping is read-only and owned for the lifetime of this view.
        let mmap = unsafe { Mmap::map(&file)? };
        if mmap.len() < 16 || &mmap[..8] != MAGIC {
            return Err(Error::Contract("invalid broker capture magic".into()));
        }
        let header_len = u64::from_le_bytes(mmap[8..16].try_into().expect("length slice")) as usize;
        if 16 + header_len > mmap.len() {
            return Err(Error::Contract("truncated broker capture header".into()));
        }
        let header: BrokerCaptureHeader = serde_json::from_slice(&mmap[16..16 + header_len])?;
        let row_offset = 16
            + header_len
            + (align_of::<PackedBrokerQuote>()
                - ((16 + header_len) % align_of::<PackedBrokerQuote>()))
                % align_of::<PackedBrokerQuote>();
        let expected = header.row_count as usize * size_of::<PackedBrokerQuote>();
        if row_offset + expected != mmap.len() {
            return Err(Error::Contract(
                "broker capture length does not match header".into(),
            ));
        }
        let rows = try_cast_slice::<u8, PackedBrokerQuote>(&mmap[row_offset..])
            .map_err(|_| Error::Contract("broker capture row alignment invalid".into()))?;
        let actual = Digest::hash(b"northstar-broker-capture-payload-v1", cast_slice(rows));
        if actual != header.payload_hash {
            return Err(Error::Contract(
                "broker capture payload hash mismatch".into(),
            ));
        }
        Ok(Self {
            mmap,
            header,
            row_offset,
        })
    }

    pub fn header(&self) -> &BrokerCaptureHeader {
        &self.header
    }

    pub fn rows(&self) -> &[PackedBrokerQuote] {
        try_cast_slice(&self.mmap[self.row_offset..]).expect("validated mapping")
    }
}

pub fn tape_content_hash(tape: &BrokerObservationTape) -> Result<Digest> {
    let mut copy = tape.clone();
    copy.content_hash = Digest::ZERO;
    Ok(identity(b"northstar-broker-observation-tape-v1", &copy)?)
}

pub fn observation_identity(row: &BrokerQuoteObservation) -> Result<Digest> {
    let mut copy = row.clone();
    copy.observation_id = Digest::ZERO;
    Ok(identity(b"northstar-broker-observation-v1", &copy)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::joint_fixture;

    #[test]
    fn mmap_capture_rejects_no_data_movement_corruption() {
        let directory = tempfile::tempdir().unwrap();
        let fixture = joint_fixture().unwrap();
        let path = directory.path().join("quotes.nsb1");
        let header = seal_broker_capture(&path, &fixture.tradelocker).unwrap();
        let mapped = MappedBrokerCapture::open(path).unwrap();
        assert_eq!(mapped.rows().len(), fixture.tradelocker.rows.len());
        assert_eq!(mapped.header().capture_id, header.capture_id);
    }
}
