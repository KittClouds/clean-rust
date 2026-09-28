//! Fixed-width, memory-mappable segment index records.

use bytemuck::{Pod, Zeroable};
use memmap2::Mmap;

#[cfg(target_endian = "big")]
compile_error!("kammi-store index files are little-endian and mapped directly");

pub const IDX_MAGIC: [u8; 8] = *b"KMJIDX02";
pub const IDX_HEADER_LEN: usize = 16;

/// One committed event: where its frame is and the identities needed without reading it.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Pod, Zeroable)]
pub struct IdxRecord {
    pub seq: u64,
    pub offset: u64,
    pub frame_len: u32,
    pub reserved: u32,
    pub event_id: [u8; 32],
    pub payload_id: [u8; 32],
    pub request: [u8; 16],
}

pub const IDX_RECORD_LEN: usize = std::mem::size_of::<IdxRecord>();
const _: () = assert!(IDX_RECORD_LEN == 104);

pub fn idx_header(first_seq: u64) -> [u8; 16] {
    let mut header = [0u8; 16];
    header[..8].copy_from_slice(&IDX_MAGIC);
    header[8..].copy_from_slice(&first_seq.to_le_bytes());
    header
}

/// Truncated digest of a request ID, used as its index key.
pub fn request_key(request_id: &str) -> [u8; 16] {
    kammi_jcs::raw_id(request_id.as_bytes()).as_bytes()[..16]
        .try_into()
        .expect("16 bytes")
}

/// Records of one segment: mapped for sealed segments, owned for the active one.
pub enum IdxStorage {
    Mapped(Mmap),
    Owned(Vec<IdxRecord>),
}

impl IdxStorage {
    pub fn records(&self) -> &[IdxRecord] {
        match self {
            IdxStorage::Mapped(map) => {
                let body = &map[IDX_HEADER_LEN..];
                let whole = body.len() / IDX_RECORD_LEN * IDX_RECORD_LEN;
                // The map starts page-aligned and the header is 16 bytes, so records are
                // 8-byte aligned as the u64 fields require.
                bytemuck::cast_slice(&body[..whole])
            }
            IdxStorage::Owned(records) => records,
        }
    }
}

/// Parses an index file's bytes into records if the header and structure are valid.
/// Structural checks only; frame contents are checked by the journal.
pub fn parse_records(bytes: &[u8], first_seq: u64) -> Option<Vec<IdxRecord>> {
    if bytes.len() < IDX_HEADER_LEN || bytes[..8] != IDX_MAGIC {
        return None;
    }
    if u64::from_le_bytes(bytes[8..16].try_into().ok()?) != first_seq {
        return None;
    }
    let body = &bytes[IDX_HEADER_LEN..];
    let whole = body.len() / IDX_RECORD_LEN * IDX_RECORD_LEN;
    Some(
        body[..whole]
            .chunks_exact(IDX_RECORD_LEN)
            .map(bytemuck::pod_read_unaligned)
            .collect(),
    )
}
