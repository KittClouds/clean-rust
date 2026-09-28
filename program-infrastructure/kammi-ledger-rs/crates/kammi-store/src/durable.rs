//! Durability primitives: flushed files, atomic publication and positional reads.

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

use crate::error::{io, Result};
use crate::fault;

/// Flushes file data and metadata to stable storage (`FlushFileBuffers` on Windows).
pub fn sync(file: &File, path: &Path) -> Result<()> {
    file.sync_all().map_err(io(path))
}

/// Makes a rename or creation inside `dir` durable where the platform supports it.
/// Windows has no directory flush; NTFS journals the metadata change itself.
pub fn sync_dir(dir: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        File::open(dir)
            .and_then(|d| d.sync_all())
            .map_err(io(dir))?;
    }
    #[cfg(not(unix))]
    let _ = dir;
    Ok(())
}

pub fn create_dir_all(dir: &Path) -> Result<()> {
    fs::create_dir_all(dir).map_err(io(dir))
}

fn unique_suffix() -> String {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    format!(
        "{}-{}",
        std::process::id(),
        COUNTER.fetch_add(1, Ordering::Relaxed)
    )
}

/// Writes `bytes` to a new temporary file in `staging`, flushes it, then renames it onto
/// `target`. Readers see either nothing or the complete file.
pub fn publish(staging: &Path, target: &Path, bytes: &[u8]) -> Result<()> {
    publish_with(staging, target, bytes, None, None)
}

/// [`publish`] with fault points after the flushed write and after the rename.
pub fn publish_with(
    staging: &Path,
    target: &Path,
    bytes: &[u8],
    after_write: Option<&'static str>,
    after_rename: Option<&'static str>,
) -> Result<()> {
    create_dir_all(staging)?;
    let temp = staging.join(format!("tmp-{}", unique_suffix()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)
            .map_err(io(&temp))?;
        file.write_all(bytes).map_err(io(&temp))?;
        sync(&file, &temp)?;
        drop(file);
        if let Some(point) = after_write {
            fault::hit(point);
        }
        if let Some(parent) = target.parent() {
            create_dir_all(parent)?;
        }
        fs::rename(&temp, target).map_err(io(target))?;
        if let Some(point) = after_rename {
            fault::hit(point);
        }
        if let Some(parent) = target.parent() {
            sync_dir(parent)?;
        }
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}

/// Fills `buffer` from `offset` without moving any file cursor.
pub fn read_exact_at(file: &File, buffer: &mut [u8], offset: u64) -> std::io::Result<()> {
    #[cfg(windows)]
    {
        use std::os::windows::fs::FileExt;
        let mut buffer = buffer;
        let mut offset = offset;
        while !buffer.is_empty() {
            let read = file.seek_read(buffer, offset)?;
            if read == 0 {
                return Err(std::io::ErrorKind::UnexpectedEof.into());
            }
            buffer = &mut buffer[read..];
            offset += read as u64;
        }
        Ok(())
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::FileExt;
        file.read_exact_at(buffer, offset)
    }
}

/// Moves a torn tail aside, then truncates the file to `offset`. The quarantine copy is
/// flushed before the truncation, so the discarded bytes survive a crash in between.
pub fn quarantine_tail(
    file: &File,
    path: &Path,
    offset: u64,
    recovery_dir: &Path,
) -> Result<Option<std::path::PathBuf>> {
    let length = file.metadata().map_err(io(path))?.len();
    if length <= offset {
        return Ok(None);
    }
    let mut tail = vec![0u8; (length - offset) as usize];
    read_exact_at(file, &mut tail, offset).map_err(io(path))?;
    create_dir_all(recovery_dir)?;
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default();
    let digest = kammi_jcs::raw_id(&tail).to_string();
    let target = recovery_dir.join(format!("{name}-{offset}-{}.partial", &digest[7..23]));
    if !target.exists() {
        let mut out = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&target)
            .map_err(io(&target))?;
        out.write_all(&tail).map_err(io(&target))?;
        sync(&out, &target)?;
    }
    file.set_len(offset).map_err(io(path))?;
    sync(file, path)?;
    Ok(Some(target))
}
