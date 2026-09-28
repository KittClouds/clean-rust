//! Journal segment frames.
//!
//! ```text
//! segment header  "KMJSEG02" | first_seq u64 LE                       (16 bytes)
//! frame           body_len u32 LE | body | sha256(body) (32 bytes)
//! body            kind u8 (=1) | event_len u32 LE | event JCS | payload bytes
//! ```
//!
//! The event bytes are the unchanged canonical v1 envelope, so event IDs and the hash chain
//! are identical to v1. The payload travels inline instead of as a separate CAS file.

use kammi_jcs::raw_id;

pub const SEGMENT_MAGIC: [u8; 8] = *b"KMJSEG02";
pub const SEGMENT_HEADER_LEN: u64 = 16;
pub const FRAME_KIND_EVENT: u8 = 1;
/// Largest event envelope (`journal.py:MAX_EVENT_BYTES`).
pub const MAX_EVENT_BYTES: usize = 16 * 1024 * 1024;
/// Largest inline payload.
pub const MAX_PAYLOAD_BYTES: usize = 64 * 1024 * 1024;
const MAX_BODY: u64 = (5 + MAX_EVENT_BYTES + MAX_PAYLOAD_BYTES) as u64;

pub fn segment_header(first_seq: u64) -> [u8; 16] {
    let mut header = [0u8; 16];
    header[..8].copy_from_slice(&SEGMENT_MAGIC);
    header[8..].copy_from_slice(&first_seq.to_le_bytes());
    header
}

pub fn parse_segment_header(bytes: &[u8]) -> Option<u64> {
    if bytes.len() < 16 || bytes[..8] != SEGMENT_MAGIC {
        return None;
    }
    Some(u64::from_le_bytes(bytes[8..16].try_into().ok()?))
}

/// Total on-disk size of a frame holding these bytes.
pub fn frame_len(event_len: usize, payload_len: usize) -> u64 {
    (4 + 5 + event_len + payload_len + 32) as u64
}

pub fn encode(event: &[u8], payload: &[u8], out: &mut Vec<u8>) {
    let body_len = (5 + event.len() + payload.len()) as u32;
    out.extend_from_slice(&body_len.to_le_bytes());
    let body_start = out.len();
    out.push(FRAME_KIND_EVENT);
    out.extend_from_slice(&(event.len() as u32).to_le_bytes());
    out.extend_from_slice(event);
    out.extend_from_slice(payload);
    let digest = raw_id(&out[body_start..]);
    out.extend_from_slice(digest.as_bytes());
}

/// A decoded frame, expressed as ranges into the buffer it was decoded from.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Frame {
    pub event: std::ops::Range<usize>,
    pub payload: std::ops::Range<usize>,
    pub total_len: usize,
}

#[derive(Debug, PartialEq, Eq)]
pub enum Decoded {
    Frame(Frame),
    /// The buffer ends before the frame does: a torn tail if this is the end of the file.
    Incomplete,
    Invalid(&'static str),
}

pub fn decode(buf: &[u8]) -> Decoded {
    if buf.len() < 4 {
        return Decoded::Incomplete;
    }
    let body_len = u64::from(u32::from_le_bytes(buf[..4].try_into().unwrap()));
    if !(5..=MAX_BODY).contains(&body_len) {
        return Decoded::Invalid("frame length");
    }
    let total = 4 + body_len as usize + 32;
    if buf.len() < total {
        return Decoded::Incomplete;
    }
    let body = &buf[4..4 + body_len as usize];
    if raw_id(body).as_bytes().as_slice() != &buf[4 + body_len as usize..total] {
        return Decoded::Invalid("frame checksum");
    }
    if body[0] != FRAME_KIND_EVENT {
        return Decoded::Invalid("frame kind");
    }
    let event_len = u32::from_le_bytes(body[1..5].try_into().unwrap()) as usize;
    if event_len == 0 || event_len > MAX_EVENT_BYTES || 5 + event_len > body.len() {
        return Decoded::Invalid("event length");
    }
    if body.len() - 5 - event_len > MAX_PAYLOAD_BYTES {
        return Decoded::Invalid("payload length");
    }
    Decoded::Frame(Frame {
        event: 9..9 + event_len,
        payload: 9 + event_len..4 + body_len as usize,
        total_len: total,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_and_every_truncation_is_incomplete() {
        let mut out = Vec::new();
        encode(b"{\"e\":1}", b"payload", &mut out);
        assert_eq!(out.len() as u64, frame_len(7, 7));
        let Decoded::Frame(frame) = decode(&out) else {
            panic!("frame")
        };
        assert_eq!(&out[frame.event.clone()], b"{\"e\":1}");
        assert_eq!(&out[frame.payload.clone()], b"payload");
        for cut in 0..out.len() {
            assert_eq!(decode(&out[..cut]), Decoded::Incomplete, "cut {cut}");
        }
        for index in 4..out.len() {
            let mut flipped = out.clone();
            flipped[index] ^= 0x40;
            assert!(
                matches!(decode(&flipped), Decoded::Invalid(_)),
                "flip {index}"
            );
        }
    }
}
