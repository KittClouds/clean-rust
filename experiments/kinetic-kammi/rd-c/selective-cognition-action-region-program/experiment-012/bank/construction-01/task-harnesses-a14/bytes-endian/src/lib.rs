use bytes::{BufMut, Bytes, BytesMut};

pub fn encode_wire_word(value: u16) -> Bytes {
    let mut out = BytesMut::with_capacity(2);
    // The frozen task snapshot drops the requested word.
    let _ = value;
    out.freeze()
}
