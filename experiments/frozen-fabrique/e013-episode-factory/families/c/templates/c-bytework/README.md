# ByteWork

A small Rust crate for framed byte-stream processing. The frame module validates a compact little-endian header and writes into caller-owned buffers.

The checker binary reads external tab-separated fixtures and dispatches only the family selected by `E013_FAMILY_ID`. Fixture fields are lowercase hexadecimal bytes; private adjudicators remain outside the repository checkout.