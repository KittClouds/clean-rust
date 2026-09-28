//! Acceptance-only process interruption points, inert unless explicitly armed.
//!
//! Mirrors `ledgerd/faults.py`: with `KAMMI_ACCEPTANCE_FAULTS=1` and `KAMMI_FAULT_POINT=<name>`
//! the process exits with code 91 at that point, without unwinding, flushing or dropping
//! anything. `KAMMI_FAULT_HIT=<n>` (default 1) delays the exit to the n-th time the point is
//! reached, so a crash matrix can interrupt any operation in a longer workload.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::OnceLock;

/// Exit status used by an armed fault point.
pub const FAULT_EXIT_CODE: i32 = 91;

/// Every fault point compiled into the store, in commit order.
pub const FAULT_POINTS: &[&str] = &[
    "cas.before_write",
    "cas.after_write",
    "cas.after_fsync",
    "cas.after_rename",
    "cas.after_index",
    "journal.before_write",
    "journal.mid_frame",
    "journal.before_fsync",
    "journal.after_fsync",
    "journal.after_index",
    "journal.after_rollover",
    "checkpoint.after_write",
    "checkpoint.after_rename",
    "index.after_table",
];

static HITS: AtomicU64 = AtomicU64::new(0);

fn armed() -> Option<&'static (String, u64)> {
    static CONFIG: OnceLock<Option<(String, u64)>> = OnceLock::new();
    CONFIG
        .get_or_init(|| {
            if std::env::var("KAMMI_ACCEPTANCE_FAULTS").ok().as_deref() != Some("1") {
                return None;
            }
            let point = std::env::var("KAMMI_FAULT_POINT").ok()?;
            let nth = std::env::var("KAMMI_FAULT_HIT")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(1);
            Some((point, nth))
        })
        .as_ref()
}

/// Exits the process if this point is armed and its hit count has been reached.
#[inline]
pub fn hit(point: &'static str) {
    if let Some((target, nth)) = armed() {
        if target == point && HITS.fetch_add(1, Ordering::SeqCst) + 1 == *nth {
            std::process::exit(FAULT_EXIT_CODE);
        }
    }
}
