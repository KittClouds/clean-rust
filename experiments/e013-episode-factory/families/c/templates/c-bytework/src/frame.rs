#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FrameHeader {
    pub tag: u8,
    pub payload_len: u16,
}

impl FrameHeader {
    pub fn parse(bytes: &[u8]) -> Option<(Self, &[u8])> {
        let header = bytes.get(..3)?;
        let payload_len = u16::from_le_bytes([header[1], header[2]]);
        let end = 3_usize.checked_add(payload_len as usize)?;
        let payload = bytes.get(3..end)?;
        Some((Self { tag: header[0], payload_len }, payload))
    }

    pub fn encode(self, payload: &[u8], destination: &mut Vec<u8>) -> Option<()> {
        if payload.len() != self.payload_len as usize {
            return None;
        }
        destination.reserve(3 + payload.len());
        destination.push(self.tag);
        destination.extend_from_slice(&self.payload_len.to_le_bytes());
        destination.extend_from_slice(payload);
        Some(())
    }
}
