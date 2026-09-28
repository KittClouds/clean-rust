//! Read-only view of a v1 store root: journals and the loose CAS.

use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};

use kammi_jcs::{raw_id, Sha256Hasher, Sha256Id};

use crate::{JournalReader, V1Error};

/// A v1 store laid out as the Python daemon writes it:
///
/// ```text
/// journal/events.log           main custody journal
/// memory/journal/events.log    contextual memory journal
/// objects/sha256/ab/cdef...    loose CAS objects
/// ```
///
/// `custody.lbdb`, `memory.lbdb`, `locks/` and secrets are never opened.
pub struct V1Store {
    root: PathBuf,
}

impl V1Store {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, V1Error> {
        let root = root.as_ref().to_path_buf();
        if !root.join("journal").join("events.log").is_file() {
            return Err(V1Error::NotAStore(root));
        }
        Ok(V1Store { root })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn main_journal(&self) -> Result<JournalReader, V1Error> {
        JournalReader::open(self.root.join("journal").join("events.log"))
    }

    /// The memory journal, if memory has ever been enabled on this store.
    pub fn memory_journal(&self) -> Result<Option<JournalReader>, V1Error> {
        let path = self.root.join("memory").join("journal").join("events.log");
        if path.is_file() {
            JournalReader::open(path).map(Some)
        } else {
            Ok(None)
        }
    }

    pub fn object_path(&self, id: &Sha256Id) -> PathBuf {
        let text = id.to_string();
        let hex = &text[7..];
        self.root
            .join("objects")
            .join("sha256")
            .join(&hex[..2])
            .join(&hex[2..])
    }

    /// Size of a loose object, without reading or verifying it.
    pub fn object_len(&self, id: &Sha256Id) -> Result<u64, V1Error> {
        let path = self.object_path(id);
        match fs::symlink_metadata(&path) {
            Ok(meta) if meta.is_file() => Ok(meta.len()),
            Ok(_) => Err(V1Error::ObjectMissing(*id)),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Err(V1Error::ObjectMissing(*id)),
            Err(e) => Err(V1Error::io(path, e)),
        }
    }

    /// Reads a whole object and verifies its digest (`cas.get`).
    pub fn read_object(&self, id: &Sha256Id) -> Result<Vec<u8>, V1Error> {
        let path = self.object_path(id);
        self.object_len(id)?;
        let bytes = fs::read(&path).map_err(|e| V1Error::io(&path, e))?;
        if raw_id(&bytes) != *id {
            return Err(V1Error::ObjectCorrupt(*id));
        }
        Ok(bytes)
    }

    /// Streams an object of any size through SHA-256 and reports whether it verifies
    /// (`cas.verify`). Large artifacts are never loaded whole.
    pub fn verify_object(&self, id: &Sha256Id) -> Result<bool, V1Error> {
        let path = self.object_path(id);
        if self.object_len(id).is_err() {
            return Ok(false);
        }
        let mut file = fs::File::open(&path).map_err(|e| V1Error::io(&path, e))?;
        let mut hasher = Sha256Hasher::new();
        let mut buffer = vec![0u8; 1 << 20];
        loop {
            let read = file.read(&mut buffer).map_err(|e| V1Error::io(&path, e))?;
            if read == 0 {
                break;
            }
            hasher.update(&buffer[..read]);
        }
        Ok(hasher.finish() == *id)
    }

    /// Every loose object identity currently published, in digest order.
    /// Staging files and anything not shaped like a CAS path are ignored.
    pub fn object_ids(&self) -> Result<Vec<Sha256Id>, V1Error> {
        let base = self.root.join("objects").join("sha256");
        let mut ids = Vec::new();
        let prefixes = match fs::read_dir(&base) {
            Ok(entries) => entries,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(ids),
            Err(e) => return Err(V1Error::io(base, e)),
        };
        for prefix in prefixes {
            let prefix = prefix.map_err(|e| V1Error::io(&base, e))?;
            let prefix_name = prefix.file_name().to_string_lossy().into_owned();
            if prefix_name.len() != 2 || !prefix.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                continue;
            }
            for entry in fs::read_dir(prefix.path()).map_err(|e| V1Error::io(prefix.path(), e))? {
                let entry = entry.map_err(|e| V1Error::io(prefix.path(), e))?;
                if !entry.file_type().map(|t| t.is_file()).unwrap_or(false) {
                    continue;
                }
                let text = format!(
                    "sha256:{prefix_name}{}",
                    entry.file_name().to_string_lossy()
                );
                if let Ok(id) = Sha256Id::parse(&text) {
                    ids.push(id);
                }
            }
        }
        ids.sort_unstable();
        Ok(ids)
    }
}
