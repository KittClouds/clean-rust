//! The `kammi` shell (amendment v4 §3): agents reach the Library only through its HTTP API.
//!
//! [`client`] reproduces `ledgerd/client.py` (errors, JCS bodies, `/v1`-only escape hatch),
//! [`mcp`] reproduces `ledgerd/mcp.py` (fixed tools, no Cypher, 1 MiB frames), and the `kammi`
//! binary reproduces `ledgerd/cli.py` plus the frozen verb list. The Python originals stay
//! frozen with the rollback tree.

pub mod client;
pub mod mcp;
pub mod verbs;

/// Python's `json.dumps(value, indent=2, sort_keys=True)`: serde's pretty form with sorted
/// keys, plus `ensure_ascii` escaping.
pub fn dumps_pretty(value: &serde_json::Value) -> String {
    ascii(&serde_json::to_string_pretty(value).expect("JSON values serialize"))
}

/// Python's `ensure_ascii`: every non-ASCII character becomes `\uXXXX` (UTF-16 units).
pub fn ascii(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        if c.is_ascii() {
            out.push(c);
        } else {
            let mut units = [0u16; 2];
            for unit in c.encode_utf16(&mut units) {
                out.push_str(&format!("\\u{unit:04x}"));
            }
        }
    }
    out
}

/// A fresh request ID in UUID v4 form (the Python CLI uses `uuid4()`).
pub fn request_id() -> String {
    use sha2::{Digest, Sha256};
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    let mut seed = Sha256::new();
    seed.update(nanos.to_le_bytes());
    seed.update(std::process::id().to_le_bytes());
    seed.update(COUNTER.fetch_add(1, Ordering::Relaxed).to_le_bytes());
    seed.update(format!("{:p}", &seed).as_bytes());
    let mut b: [u8; 16] = seed.finalize()[..16].try_into().expect("16 bytes");
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    let hex: String = b.iter().map(|x| format!("{x:02x}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        &hex[..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..]
    )
}
