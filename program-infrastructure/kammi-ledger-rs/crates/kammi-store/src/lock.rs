//! Operating-system-held single-writer ownership of one store root.

use std::fs::{File, OpenOptions, TryLockError};
use std::path::Path;

use crate::durable;
use crate::error::{io, Result, StoreError};

/// Held for the lifetime of a writable [`crate::Store`]. The OS releases the lock when the
/// process exits for any reason, so a crashed writer never blocks its successor.
pub struct StoreLock {
    _file: File,
}

impl StoreLock {
    pub fn acquire(root: &Path) -> Result<Self> {
        let locks = root.join("locks");
        durable::create_dir_all(&locks)?;
        let path = locks.join("writer.lock");
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&path)
            .map_err(io(&path))?;
        match file.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(StoreError::Busy(root.to_path_buf())),
            Err(TryLockError::Error(e)) => return Err(io(&path)(e)),
        }
        // Diagnostic only: the OS lock above is the authority.
        let owner = format!("{{\"pid\":{}}}\n", std::process::id());
        let _ = durable::publish(
            &locks.join("staging"),
            &locks.join("owner.json"),
            owner.as_bytes(),
        );
        Ok(StoreLock { _file: file })
    }
}
