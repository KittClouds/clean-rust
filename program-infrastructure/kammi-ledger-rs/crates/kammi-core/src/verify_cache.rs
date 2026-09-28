//! Artifact-verification checkpoint: skips re-hashing large loose objects that were verified
//! before and are provably untouched since.
//!
//! An entry binds the object identity to the loose file's size, creation time and last-write
//! time, the journal head at verification, and the verifier version. It is used only when all
//! of them still match (and the head is still in this store's journal); any mismatch discards
//! it and the object is re-hashed. It is never authority: a failed hash is never overridden,
//! `KAMMI_OBJECT_VERIFY=full` bypasses it, and deep verification always re-hashes.
//!
//! Trust boundary, stated plainly: an unchanged file is recognised by its metadata, so a
//! same-size rewrite that also restores both timestamps would pass until the next full
//! verification. The file lives in `checkpoints/` and is disposable.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use kammi_jcs::{Sha256Id, Value};
use parking_lot::Mutex;

pub const VERIFIER: &str = "kammi-object-verify-v1";

#[derive(Clone, PartialEq, Eq)]
struct Entry {
    size: u64,
    created: u64,
    modified: u64,
    journal_head: String,
}

pub struct VerificationCache {
    path: PathBuf,
    entries: Mutex<HashMap<Sha256Id, Entry>>,
    enabled: bool,
}

/// (size, creation time, last-write time) of a file.
fn fingerprint(path: &Path) -> Option<(u64, u64, u64)> {
    let meta = std::fs::metadata(path).ok()?;
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        Some((meta.len(), meta.creation_time(), meta.last_write_time()))
    }
    #[cfg(not(windows))]
    {
        use std::os::unix::fs::MetadataExt;
        Some((
            meta.len(),
            meta.ino(),
            meta.mtime_nsec() as u64 ^ (meta.mtime() as u64) << 32,
        ))
    }
}

impl VerificationCache {
    /// Loads the checkpoint, keeping only entries whose journal head this store contains.
    pub fn load(store_root: &Path, head_known: impl Fn(&str) -> bool) -> VerificationCache {
        let path = store_root
            .join("checkpoints")
            .join("object-verification-v1.json");
        let enabled = std::env::var("KAMMI_OBJECT_VERIFY").map_or(true, |v| v != "full");
        let mut entries = HashMap::new();
        if enabled {
            // Not an identity document: plain serde_json, because file times (Windows
            // FILETIME ~1.3e17) exceed the 2^53 integers strict identity JSON accepts.
            let parsed: Value = std::fs::read(&path)
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok())
                .unwrap_or(Value::Null);
            if parsed["verifier"] == VERIFIER {
                for row in parsed["objects"].as_array().into_iter().flatten() {
                    let (Some(id), Some(size), Some(created), Some(modified), Some(head)) = (
                        row["object_id"]
                            .as_str()
                            .and_then(|s| Sha256Id::parse(s).ok()),
                        row["size"].as_u64(),
                        row["created"].as_u64(),
                        row["modified"].as_u64(),
                        row["journal_head"].as_str(),
                    ) else {
                        continue;
                    };
                    if head_known(head) {
                        entries.insert(
                            id,
                            Entry {
                                size,
                                created,
                                modified,
                                journal_head: head.to_string(),
                            },
                        );
                    }
                }
            }
        }
        VerificationCache {
            path,
            entries: Mutex::new(entries),
            enabled,
        }
    }

    /// True when `file` still matches a recorded verification of `id`.
    pub fn trusted(&self, id: &Sha256Id, file: &Path) -> bool {
        if !self.enabled {
            return false;
        }
        let Some((size, created, modified)) = fingerprint(file) else {
            return false;
        };
        self.entries
            .lock()
            .get(id)
            .is_some_and(|e| e.size == size && e.created == created && e.modified == modified)
    }

    /// Records a successful re-hash of `id` stored at `file` and persists the checkpoint.
    pub fn record(&self, id: &Sha256Id, file: &Path, journal_head: &str) {
        if !self.enabled {
            return;
        }
        let Some((size, created, modified)) = fingerprint(file) else {
            return;
        };
        let entry = Entry {
            size,
            created,
            modified,
            journal_head: journal_head.to_string(),
        };
        let snapshot = {
            let mut entries = self.entries.lock();
            if entries.get(id) == Some(&entry) {
                return;
            }
            entries.insert(*id, entry);
            let mut rows: Vec<Value> = entries
                .iter()
                .map(|(id, e)| {
                    crate::obj! {
                        "object_id" => id.to_string(), "size" => e.size, "sha256" => id.to_string(),
                        "created" => e.created, "modified" => e.modified, "journal_head" => e.journal_head.clone(),
                    }
                })
                .collect();
            rows.sort_by(|a, b| a["object_id"].as_str().cmp(&b["object_id"].as_str()));
            crate::obj! {"verifier" => VERIFIER, "objects" => rows}
        };
        // Best effort: the checkpoint only accelerates; failing to write it changes nothing.
        let temp = self.path.with_extension("json.tmp");
        if std::fs::create_dir_all(self.path.parent().unwrap_or(Path::new("."))).is_ok()
            && std::fs::write(&temp, snapshot.to_string()).is_ok()
        {
            let _ = std::fs::rename(&temp, &self.path);
        }
    }

    pub fn len(&self) -> usize {
        self.entries.lock().len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn checkpoint_round_trips_file_times_beyond_2_pow_53_and_detects_changes() {
        let root = tempfile::tempdir().unwrap();
        let object = root.path().join("object");
        std::fs::write(&object, b"large object bytes").unwrap();
        let id = kammi_jcs::raw_id(b"large object bytes");
        let head = Sha256Id::ZERO.to_string();
        let cache = VerificationCache::load(root.path(), |_| true);
        assert!(!cache.trusted(&id, &object));
        cache.record(&id, &object, &head);

        // Reloaded from disk: FILETIME-sized integers must survive (strict identity JSON
        // would reject them and silently disable the checkpoint).
        let reloaded = VerificationCache::load(root.path(), |_| true);
        assert_eq!(reloaded.len(), 1);
        assert!(reloaded.trusted(&id, &object));

        // Unknown journal head: entry dropped.
        assert!(VerificationCache::load(root.path(), |_| false).is_empty());

        // Rewritten file: size changes, entry no longer applies.
        std::fs::write(&object, b"different and longer bytes").unwrap();
        assert!(!reloaded.trusted(&id, &object));
    }
}
