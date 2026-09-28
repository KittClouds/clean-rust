use crate::domain::{Availability, SourceOffer};
use blake3::Hasher;
use memchr::memchr_iter;
use memmap2::MmapOptions;
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
};

const OFFER_JOURNAL_HEADER: &[u8] = b"RDC-E008-OFFER-RECEIPT-V1\n";
const RECEIPT_DOMAIN: &[u8] = b"RDC-E008-OFFER-RECEIPT-HASH-V1\0";
pub const CRASH_SEED: u64 = 0xE008_2026_0928;

#[derive(Clone, Debug, Serialize, Deserialize)]
struct OfferReceipt {
    world_id: u32,
    episode_id: u32,
    source_id: u8,
    schema_version: u16,
    offer_version: u16,
    availability: u8,
    source_local_age_bucket: u8,
    provenance_family: u8,
    independence_from_active_source: bool,
    historical_reliability_bucket: u8,
    quoted_query_price: u32,
    offer_expiry: u64,
    acquisition_provenance: String,
    acquisition_cost_units: u32,
    previous_hash: [u8; 32],
    hash: [u8; 32],
}

pub(crate) struct OfferLog {
    writer: BufWriter<File>,
    path: PathBuf,
    previous_hash: [u8; 32],
    bytes: u64,
}

impl OfferLog {
    pub(crate) fn create(path: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        let file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)?;
        let mut writer = BufWriter::with_capacity(8 * 1024, file);
        writer.write_all(OFFER_JOURNAL_HEADER)?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        Ok(Self {
            writer,
            path: path.to_path_buf(),
            previous_hash: [0; 32],
            bytes: OFFER_JOURNAL_HEADER.len() as u64,
        })
    }

    pub(crate) fn append(
        &mut self,
        world_id: u32,
        episode_id: u32,
        offer: SourceOffer,
        provenance: &str,
        cost: u32,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let mut receipt = OfferReceipt {
            world_id,
            episode_id,
            source_id: offer.source_id,
            schema_version: offer.schema_version,
            offer_version: offer.version,
            availability: offer.availability as u8,
            source_local_age_bucket: offer.source_local_age_bucket,
            provenance_family: offer.provenance_family,
            independence_from_active_source: offer.independence_from_active_source,
            historical_reliability_bucket: offer.historical_reliability_bucket,
            quoted_query_price: offer.quoted_query_price,
            offer_expiry: offer.offer_expiry,
            acquisition_provenance: provenance.to_owned(),
            acquisition_cost_units: cost,
            previous_hash: self.previous_hash,
            hash: [0; 32],
        };
        receipt.hash = receipt_hash(&receipt)?;
        let encoded = serde_json::to_vec(&receipt)?;
        self.writer.write_all(&encoded)?;
        self.writer.write_all(b"\n")?;
        self.bytes += encoded.len() as u64 + 1;
        self.previous_hash = receipt.hash;
        Ok(())
    }

    pub(crate) fn sync(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        self.writer.flush()?;
        self.writer.get_ref().sync_all()?;
        Ok(())
    }

    pub(crate) fn finish(mut self) -> Result<OfferJournalStats, Box<dyn std::error::Error>> {
        self.sync()?;
        verify_offer_log(&self.path)
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct OfferJournalStats {
    pub receipts: usize,
    pub bytes: u64,
    pub identity: [u8; 32],
    pub replay_ok: bool,
}

fn receipt_hash(receipt: &OfferReceipt) -> Result<[u8; 32], Box<dyn std::error::Error>> {
    let mut copy = receipt.clone();
    copy.hash = [0; 32];
    let bytes = serde_json::to_vec(&copy)?;
    let mut h = Hasher::new();
    h.update(RECEIPT_DOMAIN);
    h.update(&bytes);
    Ok(*h.finalize().as_bytes())
}

pub(crate) fn verify_offer_log(
    path: &Path,
) -> Result<OfferJournalStats, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    // SAFETY: runtime has closed the append writer before this immutable verification pass.
    let map = unsafe { MmapOptions::new().map(&file)? };
    let mut lines = memchr_iter(b'\n', &map);
    let header_end = lines.next().ok_or("offer receipt header missing")?;
    if &map[..=header_end] != OFFER_JOURNAL_HEADER {
        return Err("offer receipt header mismatch".into());
    }
    let mut start = header_end + 1;
    let mut previous = [0; 32];
    let mut receipts = 0usize;
    for end in lines {
        if end <= start {
            return Err("empty offer receipt".into());
        }
        let receipt: OfferReceipt = serde_json::from_slice(&map[start..end])?;
        if receipt.previous_hash != previous || receipt_hash(&receipt)? != receipt.hash {
            return Err("offer receipt chain failed verification".into());
        }
        previous = receipt.hash;
        receipts += 1;
        start = end + 1;
    }
    if start != map.len() {
        return Err("offer receipt journal ends in an incomplete record".into());
    }
    Ok(OfferJournalStats {
        receipts,
        bytes: map.len() as u64,
        identity: previous,
        replay_ok: true,
    })
}

pub(crate) fn encode_offer(offer: SourceOffer) -> [u8; 64] {
    let mut bytes = [0u8; 64];
    bytes[0..2].copy_from_slice(&offer.schema_version.to_le_bytes());
    bytes[2..4].copy_from_slice(&offer.version.to_le_bytes());
    bytes[4] = offer.source_id;
    bytes[5] = offer.availability as u8;
    bytes[6] = offer.source_local_age_bucket;
    bytes[7] = offer.provenance_family;
    bytes[8] = offer.independence_from_active_source as u8;
    bytes[9] = offer.historical_reliability_bucket;
    bytes[10..14].copy_from_slice(&offer.quoted_query_price.to_le_bytes());
    bytes[14..22].copy_from_slice(&offer.offer_expiry.to_le_bytes());
    bytes
}

pub(crate) fn decode_offer(bytes: &[u8; 64]) -> Result<SourceOffer, Box<dyn std::error::Error>> {
    if bytes[8] > 1 || bytes[22..].iter().any(|byte| *byte != 0) {
        return Err("offer response has invalid boolean or reserved bytes".into());
    }
    let availability = match bytes[5] {
        0 => Availability::Available,
        1 => Availability::Degraded,
        2 => Availability::Unavailable,
        _ => return Err("unknown offer availability".into()),
    };
    let schema_version = u16::from_le_bytes(bytes[0..2].try_into()?);
    if schema_version != crate::domain::OFFER_SCHEMA_VERSION {
        return Err("offer response schema version mismatch".into());
    }
    Ok(SourceOffer {
        schema_version,
        version: u16::from_le_bytes(bytes[2..4].try_into()?),
        source_id: bytes[4],
        availability,
        source_local_age_bucket: bytes[6],
        provenance_family: bytes[7],
        independence_from_active_source: bytes[8] == 1,
        historical_reliability_bucket: bytes[9],
        quoted_query_price: u32::from_le_bytes(bytes[10..14].try_into()?),
        offer_expiry: u64::from_le_bytes(bytes[14..22].try_into()?),
    })
}
