use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Cursor, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use memmap2::MmapOptions;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};

const STORE_SCHEMA: &str = "phoenix-graph-run-store/v1";
const SECTION_SCHEMA: &str = "phoenix-graph-run-section/v1";

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DurableSectionRef {
    pub identity: String,
    pub encoding: String,
    pub row_count: u64,
    pub raw_bytes: u64,
    pub compressed_bytes: u64,
    pub dependencies: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DurableGraphRunManifest {
    pub schema_version: String,
    pub manifest_id: String,
    pub run_handle: String,
    pub scope_id: String,
    pub snapshot_id: String,
    pub committed_at: u64,
    pub sections: BTreeMap<String, DurableSectionRef>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DurableGraphRunReceipt {
    pub schema_version: String,
    pub run_handle: String,
    pub scope_id: String,
    pub snapshot_id: String,
    pub manifest_id: String,
    pub committed_at: u64,
    pub changed_sections: u32,
    pub reused_sections: u32,
    pub encoded_sections: u32,
    pub compressed_sections: u32,
    pub raw_bytes_written: u64,
    pub compressed_bytes_written: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DurableHandleIndex {
    scope_id: String,
    manifest_id: String,
}

pub(crate) struct GraphRunStoreTxn {
    root: PathBuf,
    scope_dir: PathBuf,
    run_handle: String,
    scope_id: String,
    snapshot_id: String,
    previous: Option<DurableGraphRunManifest>,
    sections: BTreeMap<String, DurableSectionRef>,
    changed_sections: u32,
    reused_sections: u32,
    raw_bytes_written: u64,
    compressed_bytes_written: u64,
}

impl GraphRunStoreTxn {
    pub(crate) fn open(
        root: PathBuf,
        run_handle: &str,
        scope_id: &str,
        snapshot_id: &str,
    ) -> Result<Self, String> {
        let scope_dir = root.join("scopes").join(scope_key(scope_id));
        let previous = read_json::<DurableGraphRunManifest>(&scope_dir.join("manifest.json"))?;
        Ok(Self {
            root,
            scope_dir,
            run_handle: run_handle.to_owned(),
            scope_id: scope_id.to_owned(),
            snapshot_id: snapshot_id.to_owned(),
            previous,
            sections: BTreeMap::new(),
            changed_sections: 0,
            reused_sections: 0,
            raw_bytes_written: 0,
            compressed_bytes_written: 0,
        })
    }

    pub(crate) fn persist_section<T: Serialize>(
        &mut self,
        name: &str,
        identity: String,
        row_count: usize,
        dependencies: Vec<String>,
        value: &T,
    ) -> Result<(), String> {
        let blob_path = self.root.join("blobs").join(format!("{identity}.zst"));
        if let Some(section) = self
            .previous
            .as_ref()
            .and_then(|manifest| manifest.sections.get(name))
            .filter(|section| section.identity == identity && blob_path.is_file())
        {
            self.sections.insert(name.to_owned(), section.clone());
            self.reused_sections += 1;
            return Ok(());
        }

        let encoded = serde_json::to_vec(value)
            .map_err(|error| format!("encode durable graph run section {name}: {error}"))?;
        let compressed = zstd::stream::encode_all(Cursor::new(&encoded), 3)
            .map_err(|error| format!("compress durable graph run section {name}: {error}"))?;
        write_immutable(&blob_path, &compressed)?;
        let section = DurableSectionRef {
            identity,
            encoding: "zstd+json".to_owned(),
            row_count: row_count as u64,
            raw_bytes: encoded.len() as u64,
            compressed_bytes: compressed.len() as u64,
            dependencies,
        };
        self.raw_bytes_written += section.raw_bytes;
        self.compressed_bytes_written += section.compressed_bytes;
        self.changed_sections += 1;
        self.sections.insert(name.to_owned(), section);
        Ok(())
    }

    pub(crate) fn commit(self) -> Result<DurableGraphRunReceipt, String> {
        fs::create_dir_all(&self.scope_dir)
            .map_err(|error| format!("create durable graph run scope directory: {error}"))?;
        let committed_at = unix_millis();
        let manifest_id = manifest_identity(&self.scope_id, &self.snapshot_id, &self.sections);
        let manifest = DurableGraphRunManifest {
            schema_version: STORE_SCHEMA.to_owned(),
            manifest_id: manifest_id.clone(),
            run_handle: self.run_handle.clone(),
            scope_id: self.scope_id.clone(),
            snapshot_id: self.snapshot_id.clone(),
            committed_at,
            sections: self.sections,
        };
        write_immutable_json(
            &self
                .root
                .join("manifests")
                .join(format!("{manifest_id}.json")),
            &manifest,
        )?;
        if self.previous.as_ref().map(|row| row.manifest_id.as_str()) != Some(manifest_id.as_str())
        {
            atomic_json(&self.scope_dir.join("manifest.json"), &manifest)?;
        }
        let receipt = DurableGraphRunReceipt {
            schema_version: "phoenix-graph-run-durable-receipt/v1".to_owned(),
            run_handle: self.run_handle,
            scope_id: self.scope_id,
            snapshot_id: self.snapshot_id,
            manifest_id,
            committed_at,
            changed_sections: self.changed_sections,
            reused_sections: self.reused_sections,
            encoded_sections: self.changed_sections,
            compressed_sections: self.changed_sections,
            raw_bytes_written: self.raw_bytes_written,
            compressed_bytes_written: self.compressed_bytes_written,
        };
        // The handle record is the durable receipt. Publishing it last means it
        // can never reference an uncommitted immutable manifest or missing blob.
        atomic_json(
            &self
                .root
                .join("handles")
                .join(format!("{}.json", scope_key(&receipt.run_handle))),
            &receipt,
        )?;
        Ok(receipt)
    }
}

pub(crate) fn section_identity(root: &str, name: &str, dependencies: &[String]) -> String {
    let mut hasher = blake3::Hasher::new();
    hash_part(&mut hasher, SECTION_SCHEMA.as_bytes());
    hash_part(&mut hasher, name.as_bytes());
    hash_part(&mut hasher, root.as_bytes());
    for dependency in dependencies {
        hash_part(&mut hasher, dependency.as_bytes());
    }
    format!("b3-{}", hasher.finalize().to_hex())
}

pub(crate) fn load_manifest_for_scope(
    root: &Path,
    scope_id: &str,
) -> Result<Option<DurableGraphRunManifest>, String> {
    read_json(
        &root
            .join("scopes")
            .join(scope_key(scope_id))
            .join("manifest.json"),
    )
}

pub(crate) fn section_blob_exists(root: &Path, section: &DurableSectionRef) -> bool {
    root.join("blobs").join(format!("{}.zst", section.identity)).is_file()
}

pub(crate) fn load_manifest_for_handle(
    root: &Path,
    run_handle: &str,
) -> Result<Option<DurableGraphRunManifest>, String> {
    let Some(index) = read_json::<DurableHandleIndex>(
        &root
            .join("handles")
            .join(format!("{}.json", scope_key(run_handle))),
    )?
    else {
        return Ok(None);
    };
    let manifest_path = root
        .join("manifests")
        .join(format!("{}.json", index.manifest_id));
    let manifest = read_json::<DurableGraphRunManifest>(&manifest_path)?;
    Ok(manifest.filter(|manifest| {
        manifest.manifest_id == index.manifest_id && manifest.scope_id == index.scope_id
    }))
}

pub(crate) fn load_section(root: &Path, section: &DurableSectionRef) -> Result<Vec<u8>, String> {
    let path = root.join("blobs").join(format!("{}.zst", section.identity));
    let file = File::open(&path)
        .map_err(|error| format!("open durable graph run blob {}: {error}", path.display()))?;
    let mapped = unsafe { MmapOptions::new().map(&file) }
        .map_err(|error| format!("mmap durable graph run blob {}: {error}", path.display()))?;
    zstd::stream::decode_all(Cursor::new(&mapped[..])).map_err(|error| {
        format!(
            "decompress durable graph run blob {}: {error}",
            path.display()
        )
    })
}

pub(crate) fn load_immutable_artifact<T: DeserializeOwned>(
    root: &Path,
    namespace: &str,
    identity: &str,
) -> Result<Option<T>, String> {
    let path = root
        .join("artifacts")
        .join(namespace)
        .join(format!("{identity}.zst"));
    if !path.is_file() {
        return Ok(None);
    }
    let file = File::open(&path)
        .map_err(|error| format!("open immutable artifact {}: {error}", path.display()))?;
    let mapped = unsafe { MmapOptions::new().map(&file) }
        .map_err(|error| format!("mmap immutable artifact {}: {error}", path.display()))?;
    let raw = zstd::stream::decode_all(Cursor::new(&mapped[..]))
        .map_err(|error| format!("decompress immutable artifact {}: {error}", path.display()))?;
    serde_json::from_slice(&raw)
        .map(Some)
        .map_err(|error| format!("decode immutable artifact {}: {error}", path.display()))
}

pub(crate) fn persist_immutable_artifact<T: Serialize>(
    root: &Path,
    namespace: &str,
    identity: &str,
    value: &T,
) -> Result<(usize, usize, bool), String> {
    let path = root
        .join("artifacts")
        .join(namespace)
        .join(format!("{identity}.zst"));
    if path.is_file() {
        return Ok((0, 0, false));
    }
    let raw = serde_json::to_vec(value)
        .map_err(|error| format!("encode immutable artifact {namespace}/{identity}: {error}"))?;
    let compressed = zstd::stream::encode_all(Cursor::new(&raw), 3)
        .map_err(|error| format!("compress immutable artifact {namespace}/{identity}: {error}"))?;
    write_immutable(&path, &compressed)?;
    Ok((raw.len(), compressed.len(), true))
}

fn manifest_identity(
    scope_id: &str,
    snapshot_id: &str,
    sections: &BTreeMap<String, DurableSectionRef>,
) -> String {
    let mut hasher = blake3::Hasher::new();
    hash_part(&mut hasher, STORE_SCHEMA.as_bytes());
    hash_part(&mut hasher, scope_id.as_bytes());
    hash_part(&mut hasher, snapshot_id.as_bytes());
    for (name, section) in sections {
        hash_part(&mut hasher, name.as_bytes());
        hash_part(&mut hasher, section.identity.as_bytes());
    }
    format!("b3-{}", hasher.finalize().to_hex())
}

pub(crate) fn scope_key(scope_id: &str) -> String {
    format!("b3-{}", blake3::hash(scope_id.as_bytes()).to_hex())
}

fn hash_part(hasher: &mut blake3::Hasher, bytes: &[u8]) {
    hasher.update(&(bytes.len() as u64).to_le_bytes());
    hasher.update(bytes);
}

fn unix_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<Option<T>, String> {
    let readable = if path.is_file() {
        path.to_path_buf()
    } else {
        let previous = previous_path(path);
        if !previous.is_file() {
            return Ok(None);
        }
        previous
    };
    let file =
        File::open(&readable).map_err(|error| format!("open {}: {error}", readable.display()))?;
    serde_json::from_reader(file)
        .map(Some)
        .map_err(|error| format!("decode {}: {error}", readable.display()))
}

fn write_immutable(path: &Path, bytes: &[u8]) -> Result<(), String> {
    if path.is_file() {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("create {}: {error}", parent.display()))?;
    }
    let temp = path.with_extension(format!("tmp-{}", std::process::id()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)
        .map_err(|error| format!("create {}: {error}", temp.display()))?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("write {}: {error}", temp.display()))?;
    match fs::rename(&temp, path) {
        Ok(()) => Ok(()),
        Err(_) if path.is_file() => {
            let _ = fs::remove_file(&temp);
            Ok(())
        }
        Err(error) => Err(format!("publish {}: {error}", path.display())),
    }
}

fn write_immutable_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    if path.is_file() {
        return Ok(());
    }
    let bytes = serde_json::to_vec(value)
        .map_err(|error| format!("encode immutable manifest {}: {error}", path.display()))?;
    write_immutable(path, &bytes)
}

pub(crate) fn atomic_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("create {}: {error}", parent.display()))?;
    }
    let temp = path.with_extension(format!("json.tmp-{}", std::process::id()));
    let mut file =
        File::create(&temp).map_err(|error| format!("create {}: {error}", temp.display()))?;
    serde_json::to_writer(&mut file, value)
        .map_err(|error| format!("encode {}: {error}", temp.display()))?;
    file.flush()
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("sync {}: {error}", temp.display()))?;
    let previous = previous_path(path);
    if previous.is_file() {
        fs::remove_file(&previous)
            .map_err(|error| format!("remove {}: {error}", previous.display()))?;
    }
    if path.is_file() {
        fs::rename(path, &previous)
            .map_err(|error| format!("preserve {}: {error}", path.display()))?;
    }
    if let Err(error) = fs::rename(&temp, path) {
        if previous.is_file() {
            let _ = fs::rename(&previous, path);
        }
        return Err(format!("publish {}: {error}", path.display()));
    }
    if previous.is_file() {
        let _ = fs::remove_file(previous);
    }
    Ok(())
}

fn previous_path(path: &Path) -> PathBuf {
    path.with_extension("previous")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::ser::Error as _;

    struct RefuseEncoding;

    impl Serialize for RefuseEncoding {
        fn serialize<S>(&self, _serializer: S) -> Result<S::Ok, S::Error>
        where
            S: serde::Serializer,
        {
            Err(S::Error::custom("unchanged section must not encode"))
        }
    }

    fn test_root(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "phoenix-graph-run-store-{name}-{}-{}",
            std::process::id(),
            unix_millis()
        ))
    }

    #[test]
    fn unchanged_identity_skips_encoding_and_compression() {
        let root = test_root("reuse");
        let dependencies = vec!["snapshot:b3-one".to_owned()];
        let identity = section_identity("root-one", "bridge", &dependencies);
        let mut first =
            GraphRunStoreTxn::open(root.clone(), "run:one", "scope:one", "snapshot:one").unwrap();
        first
            .persist_section(
                "bridge",
                identity.clone(),
                1,
                dependencies.clone(),
                &vec!["row"],
            )
            .unwrap();
        let first_receipt = first.commit().unwrap();
        assert_eq!(first_receipt.encoded_sections, 1);

        let mut warm =
            GraphRunStoreTxn::open(root.clone(), "run:two", "scope:one", "snapshot:one").unwrap();
        warm.persist_section("bridge", identity, 1, dependencies, &RefuseEncoding)
            .unwrap();
        let warm_receipt = warm.commit().unwrap();
        assert_eq!(warm_receipt.changed_sections, 0);
        assert_eq!(warm_receipt.reused_sections, 1);
        assert_eq!(warm_receipt.encoded_sections, 0);
        assert_eq!(warm_receipt.compressed_sections, 0);
        assert_eq!(warm_receipt.raw_bytes_written, 0);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn committed_manifest_reopens_blob_through_handle_index() {
        let root = test_root("restart");
        let identity = section_identity("root-two", "promotion", &[]);
        let mut transaction = GraphRunStoreTxn::open(
            root.clone(),
            "run:restart",
            "scope:restart",
            "snapshot:restart",
        )
        .unwrap();
        transaction
            .persist_section("promotion", identity, 2, vec![], &vec!["a", "b"])
            .unwrap();
        transaction.commit().unwrap();

        let manifest = load_manifest_for_handle(&root, "run:restart")
            .unwrap()
            .unwrap();
        let bytes = load_section(&root, manifest.sections.get("promotion").unwrap()).unwrap();
        assert_eq!(
            serde_json::from_slice::<Vec<String>>(&bytes).unwrap(),
            vec!["a", "b"]
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn immutable_artifact_reopens_exactly_after_restart() {
        let root = test_root("artifact-restart");
        let value = BTreeMap::from([
            ("noteId".to_owned(), "note-a".to_owned()),
            ("semantic".to_owned(), "exact".to_owned()),
        ]);
        let first =
            persist_immutable_artifact(&root, "document-semantics-v1", "b3-artifact", &value)
                .unwrap();
        let warm = persist_immutable_artifact(
            &root,
            "document-semantics-v1",
            "b3-artifact",
            &RefuseEncoding,
        )
        .unwrap();
        let loaded = load_immutable_artifact::<BTreeMap<String, String>>(
            &root,
            "document-semantics-v1",
            "b3-artifact",
        )
        .unwrap()
        .unwrap();

        assert!(first.0 > 0 && first.1 > 0 && first.2);
        assert_eq!(warm, (0, 0, false));
        assert_eq!(loaded, value);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn failed_changed_section_does_not_publish_a_new_manifest_or_receipt() {
        let root = test_root("failure");
        let mut first =
            GraphRunStoreTxn::open(root.clone(), "run:old", "scope:failure", "snapshot:old")
                .unwrap();
        first
            .persist_section(
                "bridge",
                section_identity("old", "bridge", &[]),
                1,
                vec![],
                &vec![1],
            )
            .unwrap();
        let prior = first.commit().unwrap();

        let mut failed =
            GraphRunStoreTxn::open(root.clone(), "run:new", "scope:failure", "snapshot:new")
                .unwrap();
        assert!(failed
            .persist_section(
                "bridge",
                section_identity("new", "bridge", &[]),
                1,
                vec![],
                &RefuseEncoding
            )
            .is_err());
        let manifest = load_manifest_for_scope(&root, "scope:failure").unwrap().unwrap();
        assert_eq!(manifest.manifest_id, prior.manifest_id);
        let receipt: DurableGraphRunReceipt = read_json(
            &root
                .join("handles")
                .join(format!("{}.json", scope_key("run:old"))),
        )
        .unwrap()
        .unwrap();
        assert_eq!(receipt.manifest_id, prior.manifest_id);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn changing_one_dependency_replaces_only_its_section() {
        let root = test_root("partial-change");
        let bridge_v1 = section_identity("snapshot:one", "bridge", &[]);
        let promotion = section_identity("commits:one", "promotion", &[]);
        let mut first =
            GraphRunStoreTxn::open(root.clone(), "run:first", "scope:partial", "snapshot:first")
                .unwrap();
        first
            .persist_section("bridge", bridge_v1, 1, vec![], &vec!["bridge-v1"])
            .unwrap();
        first
            .persist_section(
                "promotion",
                promotion.clone(),
                1,
                vec![],
                &vec!["promotion"],
            )
            .unwrap();
        first.commit().unwrap();

        let mut changed = GraphRunStoreTxn::open(
            root.clone(),
            "run:changed",
            "scope:partial",
            "snapshot:changed",
        )
        .unwrap();
        changed
            .persist_section(
                "bridge",
                section_identity("snapshot:two", "bridge", &[]),
                1,
                vec![],
                &vec!["bridge-v2"],
            )
            .unwrap();
        changed
            .persist_section("promotion", promotion, 1, vec![], &RefuseEncoding)
            .unwrap();
        let receipt = changed.commit().unwrap();
        assert_eq!(receipt.changed_sections, 1);
        assert_eq!(receipt.reused_sections, 1);
        assert_eq!(receipt.encoded_sections, 1);
        assert!(load_manifest_for_handle(&root, "run:first")
            .unwrap()
            .is_some());
        assert!(load_manifest_for_handle(&root, "run:changed")
            .unwrap()
            .is_some());
        let _ = fs::remove_dir_all(root);
    }
}
