use bytes::{Buf, Bytes};

pub fn take_prefix(input: Bytes, count: usize) -> Bytes {
    // E012 candidate slot.
    let _ = count;
    input
}
