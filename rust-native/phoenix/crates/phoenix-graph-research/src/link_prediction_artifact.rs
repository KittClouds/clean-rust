use crate::{
    LinkPredictionError, LinkPredictionSplit, LinkPredictionTaskManifest, LinkPredictionTaskPaths,
    LinkPredictionTaskSnapshot, LINK_PREDICTION_TASK_BINARY_VERSION, LINK_PREDICTION_TASK_SCHEMA,
};
use memmap2::Mmap;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::mem::size_of;
use std::path::{Component, Path};
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

const MAGIC: [u8; 8] = *b"PHXLPT01";

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
struct TaskHeader {
    magic: [u8; 8],
    version: [u8; 2],
    reserved: [u8; 6],
    total_bytes: [u8; 8],
    candidate_universe: [u8; 4],
    base_relation_count: [u8; 4],
    query_offset: [u8; 8],
    query_count: [u8; 8],
    conflict_offset: [u8; 8],
    conflict_count: [u8; 8],
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct QueryRecord {
    observed_at: [u8; 8],
    source: [u8; 4],
    relation: [u8; 4],
    conflict_offset: [u8; 4],
    conflict_count: [u8; 4],
    split: u8,
    inverse: u8,
    reserved: [u8; 6],
}

impl QueryRecord {
    pub(crate) fn observed_at(self) -> i64 {
        i64::from_le_bytes(self.observed_at)
    }
    pub(crate) fn source(self) -> u32 {
        u32::from_le_bytes(self.source)
    }
    pub(crate) fn relation(self) -> u32 {
        u32::from_le_bytes(self.relation)
    }
    pub(crate) fn conflict_offset(self) -> u32 {
        u32::from_le_bytes(self.conflict_offset)
    }
    pub(crate) fn conflict_count(self) -> u32 {
        u32::from_le_bytes(self.conflict_count)
    }
    pub(crate) fn inverse(self) -> bool {
        self.inverse != 0
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub(crate) struct LeU32([u8; 4]);

impl LeU32 {
    pub(crate) fn get(self) -> u32 {
        u32::from_le_bytes(self.0)
    }
}

pub(crate) fn write_link_prediction_task(
    snapshot: &LinkPredictionTaskSnapshot,
    root: impl AsRef<Path>,
) -> Result<LinkPredictionTaskPaths, LinkPredictionError> {
    validate_snapshot(snapshot)?;
    let bytes = encode(snapshot);
    let binary_blake3 = format!("b3-{}", blake3::hash(&bytes).to_hex());
    let task_id = task_identity(snapshot, &binary_blake3)?;
    let root = root.as_ref();
    std::fs::create_dir_all(root)?;
    let binary_file = format!("{task_id}.lpt");
    let manifest_file = format!("{task_id}.manifest.json");
    let binary_path = root.join(&binary_file);
    let manifest_path = root.join(manifest_file);
    if binary_path.exists() || manifest_path.exists() {
        return Err(LinkPredictionError::ArtifactExists(binary_path));
    }
    write_immutable(&binary_path, &bytes)?;
    let mut validation_queries = 0_u64;
    let mut validation_positives = 0_u64;
    let mut test_queries = 0_u64;
    let mut test_positives = 0_u64;
    let mut inverse_queries = 0_u64;
    for query in &snapshot.queries {
        if query.inverse {
            inverse_queries += 1;
        }
        match query.split {
            LinkPredictionSplit::Validation => {
                validation_queries += 1;
                validation_positives += u64::from(query.conflict_count);
            }
            LinkPredictionSplit::Test => {
                test_queries += 1;
                test_positives += u64::from(query.conflict_count);
            }
        }
    }
    let manifest = LinkPredictionTaskManifest {
        schema_version: LINK_PREDICTION_TASK_SCHEMA.into(),
        task_id: task_id.as_str().into(),
        source_dataset_id: snapshot.source_dataset_id.clone(),
        source_binary_blake3: snapshot.source_binary_blake3.clone(),
        strategy: "tgb-time-filtered-all-dynamic-destinations".into(),
        candidate_universe: snapshot.candidate_universe,
        base_relation_count: snapshot.base_relation_count,
        derived_relation_count: snapshot
            .base_relation_count
            .checked_mul(2)
            .ok_or(LinkPredictionError::InvalidInput("relation overflow"))?,
        validation_pickle_blake3: snapshot.validation_pickle_blake3.clone(),
        test_pickle_blake3: snapshot.test_pickle_blake3.clone(),
        validation_parity_blake3: snapshot.validation_parity_blake3.clone(),
        test_parity_blake3: snapshot.test_parity_blake3.clone(),
        binary_file: binary_file.into(),
        binary_blake3: binary_blake3.into(),
        binary_bytes: bytes.len() as u64,
        validation_queries,
        validation_positives,
        test_queries,
        test_positives,
        inverse_queries,
        test_locked: true,
    };
    let manifest_bytes = serde_json::to_vec_pretty(&manifest)?;
    if let Err(error) = write_immutable(&manifest_path, &manifest_bytes) {
        let _ = std::fs::remove_file(&binary_path);
        return Err(error);
    }
    Ok(LinkPredictionTaskPaths {
        manifest: manifest_path,
        binary: binary_path,
        task_id: task_id.into(),
    })
}

pub struct LinkPredictionTaskMapped {
    manifest: LinkPredictionTaskManifest,
    mmap: Mmap,
    query_offset: usize,
    conflict_offset: usize,
    validation_count: usize,
}

impl LinkPredictionTaskMapped {
    pub fn open(manifest_path: impl AsRef<Path>) -> Result<Self, LinkPredictionError> {
        let manifest_path = manifest_path.as_ref();
        let manifest: LinkPredictionTaskManifest =
            serde_json::from_slice(&std::fs::read(manifest_path)?)?;
        validate_manifest(&manifest)?;
        let binary_name = Path::new(manifest.binary_file.as_str());
        let mut components = binary_name.components();
        if !matches!(components.next(), Some(Component::Normal(_))) || components.next().is_some() {
            return Err(LinkPredictionError::CorruptArtifact("binary file path"));
        }
        let binary_path = manifest_path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join(binary_name);
        let file = File::open(binary_path)?;
        let mmap = unsafe { Mmap::map(&file)? };
        if mmap.len() as u64 != manifest.binary_bytes
            || format!("b3-{}", blake3::hash(&mmap).to_hex()) != manifest.binary_blake3
        {
            return Err(LinkPredictionError::CorruptArtifact("binary identity"));
        }
        let header = Ref::<_, TaskHeader>::new(
            mmap.get(..size_of::<TaskHeader>())
                .ok_or(LinkPredictionError::CorruptArtifact("header"))?,
        )
        .ok_or(LinkPredictionError::CorruptArtifact("header"))?;
        validate_header(&header, &manifest, mmap.len())?;
        let query_offset = le_usize(header.query_offset)?;
        let conflict_offset = le_usize(header.conflict_offset)?;
        validate_records(&mmap, query_offset, conflict_offset, &manifest)?;
        Ok(Self {
            query_offset,
            conflict_offset,
            validation_count: manifest.validation_queries as usize,
            manifest,
            mmap,
        })
    }

    pub fn manifest(&self) -> &LinkPredictionTaskManifest {
        &self.manifest
    }

    pub fn validation_query_count(&self) -> u64 {
        self.manifest.validation_queries
    }

    pub fn test_query_count(&self) -> u64 {
        self.manifest.test_queries
    }

    pub(crate) fn queries(
        &self,
        split: LinkPredictionSplit,
    ) -> Result<Ref<&[u8], [QueryRecord]>, LinkPredictionError> {
        let (start, count) = match split {
            LinkPredictionSplit::Validation => (0, self.validation_count),
            LinkPredictionSplit::Test => {
                (self.validation_count, self.manifest.test_queries as usize)
            }
        };
        mapped_slice(
            &self.mmap,
            self.query_offset + start * size_of::<QueryRecord>(),
            count,
        )
    }

    pub(crate) fn conflicts(&self) -> Result<Ref<&[u8], [LeU32]>, LinkPredictionError> {
        mapped_slice(
            &self.mmap,
            self.conflict_offset,
            (self.manifest.validation_positives + self.manifest.test_positives) as usize,
        )
    }
}

fn encode(snapshot: &LinkPredictionTaskSnapshot) -> Vec<u8> {
    let records = snapshot
        .queries
        .iter()
        .map(|query| QueryRecord {
            observed_at: query.observed_at.to_le_bytes(),
            source: query.source.to_le_bytes(),
            relation: query.relation.to_le_bytes(),
            conflict_offset: query.conflict_offset.to_le_bytes(),
            conflict_count: query.conflict_count.to_le_bytes(),
            split: query.split as u8,
            inverse: u8::from(query.inverse),
            reserved: [0; 6],
        })
        .collect::<Vec<_>>();
    let conflicts = snapshot
        .conflicts
        .iter()
        .map(|value| LeU32(value.to_le_bytes()))
        .collect::<Vec<_>>();
    let query_offset = size_of::<TaskHeader>();
    let conflict_offset = query_offset + records.len() * size_of::<QueryRecord>();
    let total_bytes = conflict_offset + conflicts.len() * size_of::<LeU32>();
    let header = TaskHeader {
        magic: MAGIC,
        version: LINK_PREDICTION_TASK_BINARY_VERSION.to_le_bytes(),
        reserved: [0; 6],
        total_bytes: (total_bytes as u64).to_le_bytes(),
        candidate_universe: snapshot.candidate_universe.to_le_bytes(),
        base_relation_count: snapshot.base_relation_count.to_le_bytes(),
        query_offset: (query_offset as u64).to_le_bytes(),
        query_count: (records.len() as u64).to_le_bytes(),
        conflict_offset: (conflict_offset as u64).to_le_bytes(),
        conflict_count: (conflicts.len() as u64).to_le_bytes(),
    };
    let mut bytes = Vec::with_capacity(total_bytes);
    bytes.extend_from_slice(header.as_bytes());
    bytes.extend_from_slice(records.as_bytes());
    bytes.extend_from_slice(conflicts.as_bytes());
    bytes
}

fn validate_snapshot(snapshot: &LinkPredictionTaskSnapshot) -> Result<(), LinkPredictionError> {
    if snapshot.source_dataset_id.is_empty()
        || snapshot.source_binary_blake3.is_empty()
        || snapshot.candidate_universe == 0
        || snapshot.base_relation_count == 0
        || snapshot.queries.is_empty()
        || snapshot.conflicts.is_empty()
    {
        return Err(LinkPredictionError::InvalidInput("empty task section"));
    }
    let derived_relation_count = snapshot
        .base_relation_count
        .checked_mul(2)
        .ok_or(LinkPredictionError::InvalidInput("relation overflow"))?;
    let mut expected_offset = 0_usize;
    let mut saw_test = false;
    for query in &snapshot.queries {
        saw_test |= query.split == LinkPredictionSplit::Test;
        if (saw_test && query.split == LinkPredictionSplit::Validation)
            || query.observed_at <= 0
            || query.source >= snapshot.candidate_universe
            || query.relation >= derived_relation_count
            || query.inverse != (query.relation >= snapshot.base_relation_count)
            || query.conflict_count == 0
            || query.conflict_offset as usize != expected_offset
        {
            return Err(LinkPredictionError::InvalidInput("query contract"));
        }
        expected_offset = expected_offset
            .checked_add(query.conflict_count as usize)
            .ok_or(LinkPredictionError::InvalidInput("conflict overflow"))?;
    }
    if expected_offset != snapshot.conflicts.len()
        || snapshot
            .conflicts
            .iter()
            .any(|destination| *destination >= snapshot.candidate_universe)
    {
        return Err(LinkPredictionError::InvalidInput("conflict contract"));
    }
    Ok(())
}

fn task_identity(
    snapshot: &LinkPredictionTaskSnapshot,
    binary_blake3: &str,
) -> Result<String, LinkPredictionError> {
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            LINK_PREDICTION_TASK_SCHEMA,
            snapshot.source_dataset_id.as_str(),
            snapshot.source_binary_blake3.as_str(),
            snapshot.validation_pickle_blake3.as_str(),
            snapshot.test_pickle_blake3.as_str(),
            snapshot.validation_parity_blake3.as_str(),
            snapshot.test_parity_blake3.as_str(),
            binary_blake3,
        ))?)
        .to_hex()
    ))
}

fn validate_manifest(manifest: &LinkPredictionTaskManifest) -> Result<(), LinkPredictionError> {
    let derived_relation_count = manifest
        .base_relation_count
        .checked_mul(2)
        .ok_or(LinkPredictionError::CorruptArtifact("relation overflow"))?;
    if manifest.schema_version != LINK_PREDICTION_TASK_SCHEMA
        || !manifest.test_locked
        || manifest.strategy != "tgb-time-filtered-all-dynamic-destinations"
        || manifest.source_dataset_id.is_empty()
        || manifest.source_binary_blake3.is_empty()
        || manifest.candidate_universe == 0
        || manifest.base_relation_count == 0
        || manifest.derived_relation_count != derived_relation_count
        || manifest.validation_queries == 0
        || manifest.validation_positives == 0
        || manifest.test_queries == 0
        || manifest.test_positives == 0
    {
        return Err(LinkPredictionError::CorruptArtifact("manifest"));
    }
    let expected = format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            LINK_PREDICTION_TASK_SCHEMA,
            manifest.source_dataset_id.as_str(),
            manifest.source_binary_blake3.as_str(),
            manifest.validation_pickle_blake3.as_str(),
            manifest.test_pickle_blake3.as_str(),
            manifest.validation_parity_blake3.as_str(),
            manifest.test_parity_blake3.as_str(),
            manifest.binary_blake3.as_str(),
        ))?)
        .to_hex()
    );
    if expected != manifest.task_id {
        return Err(LinkPredictionError::CorruptArtifact("task identity"));
    }
    Ok(())
}

fn validate_header(
    header: &TaskHeader,
    manifest: &LinkPredictionTaskManifest,
    bytes: usize,
) -> Result<(), LinkPredictionError> {
    let query_offset = le_usize(header.query_offset)?;
    let query_count = checked_sum_usize(manifest.validation_queries, manifest.test_queries)?;
    let conflict_offset = le_usize(header.conflict_offset)?;
    let conflict_count = checked_sum_usize(manifest.validation_positives, manifest.test_positives)?;
    let expected_conflict_offset = query_count
        .checked_mul(size_of::<QueryRecord>())
        .and_then(|bytes| query_offset.checked_add(bytes))
        .ok_or(LinkPredictionError::CorruptArtifact("layout overflow"))?;
    let expected_total = conflict_count
        .checked_mul(size_of::<LeU32>())
        .and_then(|bytes| conflict_offset.checked_add(bytes))
        .ok_or(LinkPredictionError::CorruptArtifact("layout overflow"))?;
    if header.magic != MAGIC
        || u16::from_le_bytes(header.version) != LINK_PREDICTION_TASK_BINARY_VERSION
        || le_usize(header.total_bytes)? != bytes
        || u32::from_le_bytes(header.candidate_universe) != manifest.candidate_universe
        || u32::from_le_bytes(header.base_relation_count) != manifest.base_relation_count
        || u64::from_le_bytes(header.query_count) as usize != query_count
        || u64::from_le_bytes(header.conflict_count) as usize != conflict_count
        || query_offset != size_of::<TaskHeader>()
        || conflict_offset != expected_conflict_offset
        || expected_total != bytes
    {
        return Err(LinkPredictionError::CorruptArtifact("layout"));
    }
    Ok(())
}

fn validate_records(
    bytes: &[u8],
    query_offset: usize,
    conflict_offset: usize,
    manifest: &LinkPredictionTaskManifest,
) -> Result<(), LinkPredictionError> {
    let query_count = checked_sum_usize(manifest.validation_queries, manifest.test_queries)?;
    let conflict_count = checked_sum_usize(manifest.validation_positives, manifest.test_positives)?;
    let queries = mapped_slice::<QueryRecord>(bytes, query_offset, query_count)?;
    let conflicts = mapped_slice::<LeU32>(bytes, conflict_offset, conflict_count)?;
    let mut expected_offset = 0_usize;
    let mut validation_queries = 0_u64;
    let mut validation_positives = 0_u64;
    let mut test_queries = 0_u64;
    let mut test_positives = 0_u64;
    let mut inverse_queries = 0_u64;
    let mut saw_test = false;
    for query in queries.iter().copied() {
        let is_validation = query.split == LinkPredictionSplit::Validation as u8;
        let is_test = query.split == LinkPredictionSplit::Test as u8;
        saw_test |= is_test;
        if (!is_validation && !is_test)
            || (saw_test && is_validation)
            || query.observed_at() <= 0
            || query.source() >= manifest.candidate_universe
            || query.relation() >= manifest.derived_relation_count
            || query.inverse() != (query.relation() >= manifest.base_relation_count)
            || query.conflict_count() == 0
            || query.conflict_offset() as usize != expected_offset
        {
            return Err(LinkPredictionError::CorruptArtifact("query contract"));
        }
        expected_offset = expected_offset
            .checked_add(query.conflict_count() as usize)
            .ok_or(LinkPredictionError::CorruptArtifact("conflict overflow"))?;
        inverse_queries += u64::from(query.inverse());
        if is_validation {
            validation_queries += 1;
            validation_positives += u64::from(query.conflict_count());
        } else {
            test_queries += 1;
            test_positives += u64::from(query.conflict_count());
        }
    }
    if expected_offset != conflicts.len()
        || conflicts
            .iter()
            .copied()
            .any(|value| value.get() >= manifest.candidate_universe)
        || validation_queries != manifest.validation_queries
        || validation_positives != manifest.validation_positives
        || test_queries != manifest.test_queries
        || test_positives != manifest.test_positives
        || inverse_queries != manifest.inverse_queries
    {
        return Err(LinkPredictionError::CorruptArtifact("record counts"));
    }
    Ok(())
}

fn mapped_slice<T: FromBytes + Unaligned>(
    bytes: &[u8],
    offset: usize,
    count: usize,
) -> Result<Ref<&[u8], [T]>, LinkPredictionError> {
    let len = count
        .checked_mul(size_of::<T>())
        .ok_or(LinkPredictionError::CorruptArtifact("slice"))?;
    let end = offset
        .checked_add(len)
        .ok_or(LinkPredictionError::CorruptArtifact("slice"))?;
    Ref::new_slice(
        bytes
            .get(offset..end)
            .ok_or(LinkPredictionError::CorruptArtifact("slice"))?,
    )
    .ok_or(LinkPredictionError::CorruptArtifact("slice"))
}

fn write_immutable(path: &Path, bytes: &[u8]) -> Result<(), LinkPredictionError> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn le_usize(value: [u8; 8]) -> Result<usize, LinkPredictionError> {
    usize::try_from(u64::from_le_bytes(value))
        .map_err(|_| LinkPredictionError::CorruptArtifact("integer overflow"))
}

fn checked_sum_usize(left: u64, right: u64) -> Result<usize, LinkPredictionError> {
    left.checked_add(right)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or(LinkPredictionError::CorruptArtifact("integer overflow"))
}
