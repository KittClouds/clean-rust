use crate::{
    ExternalDatasetError, ExternalDatasetKind, ExternalDatasetManifest, ExternalDatasetPaths,
    ExternalDatasetSnapshot, ExternalFactSplit, ExternalSplitPolicy,
    EXTERNAL_DATASET_BINARY_VERSION, EXTERNAL_DATASET_SCHEMA,
};
use hashbrown::{HashMap, HashSet};
use memmap2::Mmap;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::mem::size_of;
use std::path::{Component, Path};
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

const MAGIC: [u8; 8] = *b"PHXEXT01";
const FLAG_STATIC: u8 = 1;
const FLAG_HAS_TIME: u8 = 2;

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
struct ExternalHeader {
    magic: [u8; 8],
    version: [u8; 2],
    kind: u8,
    split_authority: u8,
    total_bytes: [u8; 8],
    entity_offset: [u8; 8],
    entity_count: [u8; 8],
    relation_offset: [u8; 8],
    relation_count: [u8; 8],
    fact_offset: [u8; 8],
    fact_count: [u8; 8],
    qualifier_offset: [u8; 8],
    qualifier_count: [u8; 8],
    arena_offset: [u8; 8],
    arena_bytes: [u8; 8],
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
struct StringRef {
    offset: [u8; 4],
    len: [u8; 4],
}

impl StringRef {
    fn new(offset: usize, len: usize) -> Result<Self, ExternalDatasetError> {
        Ok(Self {
            offset: checked_u32(offset)?.to_le_bytes(),
            len: checked_u32(len)?.to_le_bytes(),
        })
    }

    fn range(self, arena_offset: usize, arena_bytes: usize) -> Option<std::ops::Range<usize>> {
        let start = u32::from_le_bytes(self.offset) as usize;
        let end = start.checked_add(u32::from_le_bytes(self.len) as usize)?;
        (end <= arena_bytes).then_some(arena_offset + start..arena_offset + end)
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct ExternalFactRecord {
    subject: [u8; 4],
    predicate: [u8; 4],
    object: [u8; 4],
    qualifier_offset: [u8; 4],
    qualifier_count: [u8; 4],
    observed_at: [u8; 8],
    split: u8,
    flags: u8,
    reserved: [u8; 2],
}

impl ExternalFactRecord {
    pub fn subject(self) -> u32 {
        u32::from_le_bytes(self.subject)
    }
    pub fn predicate(self) -> u32 {
        u32::from_le_bytes(self.predicate)
    }
    pub fn object(self) -> u32 {
        u32::from_le_bytes(self.object)
    }
    pub fn qualifier_offset(self) -> u32 {
        u32::from_le_bytes(self.qualifier_offset)
    }
    pub fn qualifier_count(self) -> u32 {
        u32::from_le_bytes(self.qualifier_count)
    }
    pub fn observed_at(self) -> Option<i64> {
        (self.flags & FLAG_HAS_TIME != 0).then(|| i64::from_le_bytes(self.observed_at))
    }
    pub fn split(self) -> u8 {
        self.split
    }
    pub fn is_static(self) -> bool {
        self.flags & FLAG_STATIC != 0
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct ExternalQualifierRecord {
    predicate: [u8; 4],
    object: [u8; 4],
}

impl ExternalQualifierRecord {
    pub fn predicate(self) -> u32 {
        u32::from_le_bytes(self.predicate)
    }
    pub fn object(self) -> u32 {
        u32::from_le_bytes(self.object)
    }
}

#[derive(Default)]
struct StringArena<'a> {
    bytes: Vec<u8>,
    refs: HashMap<&'a str, StringRef>,
}

impl<'a> StringArena<'a> {
    fn intern(&mut self, value: &'a str) -> Result<StringRef, ExternalDatasetError> {
        if let Some(reference) = self.refs.get(value).copied() {
            return Ok(reference);
        }
        let reference = StringRef::new(self.bytes.len(), value.len())?;
        self.bytes.extend_from_slice(value.as_bytes());
        self.refs.insert(value, reference);
        Ok(reference)
    }
}

pub struct ExternalDatasetBundle;

impl ExternalDatasetBundle {
    pub fn write(
        snapshot: &ExternalDatasetSnapshot,
        root: impl AsRef<Path>,
    ) -> Result<ExternalDatasetPaths, ExternalDatasetError> {
        validate_snapshot(snapshot)?;
        let bytes = encode(snapshot)?;
        let binary_blake3 = format!("b3-{}", blake3::hash(&bytes).to_hex());
        let source_identity = source_identity(snapshot)?;
        let dataset_id = format!(
            "b3-{}",
            blake3::hash(&serde_json::to_vec(&(
                EXTERNAL_DATASET_SCHEMA,
                source_identity.as_str(),
                binary_blake3.as_str(),
            ))?)
            .to_hex()
        );
        let root = root.as_ref();
        std::fs::create_dir_all(root)?;
        let binary_file = format!("{dataset_id}.xgd");
        let manifest_file = format!("{dataset_id}.manifest.json");
        let binary_path = root.join(&binary_file);
        let manifest_path = root.join(manifest_file);
        if binary_path.exists() || manifest_path.exists() {
            return Err(ExternalDatasetError::ArtifactExists(binary_path));
        }
        write_immutable(&binary_path, &bytes)?;
        let temporal_facts = snapshot
            .facts
            .iter()
            .filter(|fact| fact.observed_at.is_some())
            .count() as u64;
        let static_facts = snapshot.facts.iter().filter(|fact| fact.is_static).count() as u64;
        let manifest = ExternalDatasetManifest {
            schema_version: EXTERNAL_DATASET_SCHEMA.into(),
            dataset_id: dataset_id.as_str().into(),
            name: snapshot.name.clone(),
            kind: snapshot.kind,
            upstream_url: snapshot.upstream_url.clone(),
            upstream_version: snapshot.upstream_version.clone(),
            license_notice: snapshot.license_notice.clone(),
            split_policy: snapshot.split_policy.clone(),
            source_identity: source_identity.as_str().into(),
            source_files: snapshot.source_files.clone(),
            binary_file: binary_file.into(),
            binary_blake3: binary_blake3.into(),
            binary_bytes: bytes.len() as u64,
            entities: snapshot.entities.len() as u64,
            relations: snapshot.relations.len() as u64,
            facts: snapshot.facts.len() as u64,
            temporal_facts,
            static_facts,
            qualifiers: snapshot.qualifiers.len() as u64,
        };
        let manifest_bytes = serde_json::to_vec_pretty(&manifest)?;
        if let Err(error) = write_immutable(&manifest_path, &manifest_bytes) {
            let _ = std::fs::remove_file(&binary_path);
            return Err(error);
        }
        Ok(ExternalDatasetPaths {
            manifest: manifest_path,
            binary: binary_path,
            dataset_id: dataset_id.into(),
        })
    }
}

pub struct ExternalDatasetMapped {
    manifest: ExternalDatasetManifest,
    mmap: Mmap,
    entity_offset: usize,
    relation_offset: usize,
    fact_offset: usize,
    qualifier_offset: usize,
    arena_offset: usize,
}

impl ExternalDatasetMapped {
    pub fn open(manifest_path: impl AsRef<Path>) -> Result<Self, ExternalDatasetError> {
        let manifest_path = manifest_path.as_ref();
        let manifest: ExternalDatasetManifest =
            serde_json::from_slice(&std::fs::read(manifest_path)?)?;
        validate_manifest(&manifest)?;
        let binary_name = Path::new(manifest.binary_file.as_str());
        let mut binary_components = binary_name.components();
        if !matches!(binary_components.next(), Some(Component::Normal(_)))
            || binary_components.next().is_some()
        {
            return Err(ExternalDatasetError::CorruptArtifact("binary file path"));
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
            return Err(ExternalDatasetError::CorruptArtifact("binary identity"));
        }
        let header = Ref::<_, ExternalHeader>::new(
            mmap.get(..size_of::<ExternalHeader>())
                .ok_or(ExternalDatasetError::CorruptArtifact("header"))?,
        )
        .ok_or(ExternalDatasetError::CorruptArtifact("header"))?;
        validate_header(&header, &manifest, mmap.len())?;
        Ok(Self {
            entity_offset: le_usize(header.entity_offset)?,
            relation_offset: le_usize(header.relation_offset)?,
            fact_offset: le_usize(header.fact_offset)?,
            qualifier_offset: le_usize(header.qualifier_offset)?,
            arena_offset: le_usize(header.arena_offset)?,
            manifest,
            mmap,
        })
    }

    pub fn manifest(&self) -> &ExternalDatasetManifest {
        &self.manifest
    }

    pub fn entity(&self, index: u32) -> Option<&str> {
        self.string_at(self.entity_offset, self.manifest.entities as usize, index)
    }

    pub fn relation(&self, index: u32) -> Option<&str> {
        self.string_at(
            self.relation_offset,
            self.manifest.relations as usize,
            index,
        )
    }

    pub fn facts(&self) -> Result<Ref<&[u8], [ExternalFactRecord]>, ExternalDatasetError> {
        mapped_slice(&self.mmap, self.fact_offset, self.manifest.facts as usize)
    }

    pub fn qualifiers(
        &self,
    ) -> Result<Ref<&[u8], [ExternalQualifierRecord]>, ExternalDatasetError> {
        mapped_slice(
            &self.mmap,
            self.qualifier_offset,
            self.manifest.qualifiers as usize,
        )
    }

    fn string_at(&self, offset: usize, count: usize, index: u32) -> Option<&str> {
        let refs = mapped_slice::<StringRef>(&self.mmap, offset, count).ok()?;
        let reference = *refs.get(index as usize)?;
        let arena_bytes = self.mmap.len().checked_sub(self.arena_offset)?;
        std::str::from_utf8(
            self.mmap
                .get(reference.range(self.arena_offset, arena_bytes)?)?,
        )
        .ok()
    }
}

fn encode(snapshot: &ExternalDatasetSnapshot) -> Result<Vec<u8>, ExternalDatasetError> {
    let mut arena = StringArena::default();
    let entities = snapshot
        .entities
        .iter()
        .map(|value| arena.intern(value))
        .collect::<Result<Vec<_>, _>>()?;
    let relations = snapshot
        .relations
        .iter()
        .map(|value| arena.intern(value))
        .collect::<Result<Vec<_>, _>>()?;
    let facts = snapshot
        .facts
        .iter()
        .map(|fact| ExternalFactRecord {
            subject: fact.subject.to_le_bytes(),
            predicate: fact.predicate.to_le_bytes(),
            object: fact.object.to_le_bytes(),
            qualifier_offset: fact.qualifier_offset.to_le_bytes(),
            qualifier_count: fact.qualifier_count.to_le_bytes(),
            observed_at: fact.observed_at.unwrap_or_default().to_le_bytes(),
            split: fact.split as u8,
            flags: (u8::from(fact.is_static) * FLAG_STATIC)
                | (u8::from(fact.observed_at.is_some()) * FLAG_HAS_TIME),
            reserved: [0; 2],
        })
        .collect::<Vec<_>>();
    let qualifiers = snapshot
        .qualifiers
        .iter()
        .map(|qualifier| ExternalQualifierRecord {
            predicate: qualifier.predicate.to_le_bytes(),
            object: qualifier.object.to_le_bytes(),
        })
        .collect::<Vec<_>>();
    let header_bytes = size_of::<ExternalHeader>();
    let entity_offset = header_bytes;
    let relation_offset = entity_offset + entities.len() * size_of::<StringRef>();
    let fact_offset = relation_offset + relations.len() * size_of::<StringRef>();
    let qualifier_offset = fact_offset + facts.len() * size_of::<ExternalFactRecord>();
    let arena_offset = qualifier_offset + qualifiers.len() * size_of::<ExternalQualifierRecord>();
    let total_bytes = arena_offset
        .checked_add(arena.bytes.len())
        .ok_or(ExternalDatasetError::IndexOverflow)?;
    let header = ExternalHeader {
        magic: MAGIC,
        version: EXTERNAL_DATASET_BINARY_VERSION.to_le_bytes(),
        kind: snapshot.kind as u8,
        split_authority: snapshot.split_policy.authority_code(),
        total_bytes: (total_bytes as u64).to_le_bytes(),
        entity_offset: (entity_offset as u64).to_le_bytes(),
        entity_count: (entities.len() as u64).to_le_bytes(),
        relation_offset: (relation_offset as u64).to_le_bytes(),
        relation_count: (relations.len() as u64).to_le_bytes(),
        fact_offset: (fact_offset as u64).to_le_bytes(),
        fact_count: (facts.len() as u64).to_le_bytes(),
        qualifier_offset: (qualifier_offset as u64).to_le_bytes(),
        qualifier_count: (qualifiers.len() as u64).to_le_bytes(),
        arena_offset: (arena_offset as u64).to_le_bytes(),
        arena_bytes: (arena.bytes.len() as u64).to_le_bytes(),
    };
    let mut bytes = Vec::with_capacity(total_bytes);
    bytes.extend_from_slice(header.as_bytes());
    bytes.extend_from_slice(entities.as_bytes());
    bytes.extend_from_slice(relations.as_bytes());
    bytes.extend_from_slice(facts.as_bytes());
    bytes.extend_from_slice(qualifiers.as_bytes());
    bytes.extend_from_slice(&arena.bytes);
    Ok(bytes)
}

fn validate_snapshot(snapshot: &ExternalDatasetSnapshot) -> Result<(), ExternalDatasetError> {
    if snapshot.name.is_empty()
        || snapshot.entities.is_empty()
        || snapshot.relations.is_empty()
        || snapshot.facts.is_empty()
        || snapshot.source_files.is_empty()
    {
        return Err(ExternalDatasetError::InvalidInput("empty required section"));
    }
    if snapshot.entities.len() > u32::MAX as usize
        || snapshot.relations.len() > u32::MAX as usize
        || snapshot.qualifiers.len() > u32::MAX as usize
    {
        return Err(ExternalDatasetError::IndexOverflow);
    }
    let temporal_contract = matches!(
        (&snapshot.kind, &snapshot.split_policy),
        (
            ExternalDatasetKind::TemporalKnowledgeGraph,
            ExternalSplitPolicy::TemporalQuantile { .. }
        )
    );
    let fixed_contract = matches!(
        (&snapshot.kind, &snapshot.split_policy),
        (
            ExternalDatasetKind::HyperRelationalKnowledgeGraph,
            ExternalSplitPolicy::OfficialFixed { .. }
        )
    );
    if !temporal_contract && !fixed_contract {
        return Err(ExternalDatasetError::InvalidInput("split authority"));
    }
    snapshot.split_policy.validate()?;
    if snapshot
        .entities
        .iter()
        .map(|value| value.as_str())
        .collect::<HashSet<_>>()
        .len()
        != snapshot.entities.len()
        || snapshot
            .relations
            .iter()
            .map(|value| value.as_str())
            .collect::<HashSet<_>>()
            .len()
            != snapshot.relations.len()
    {
        return Err(ExternalDatasetError::InvalidInput(
            "duplicate dictionary value",
        ));
    }
    let mut expected_qualifier_offset = 0_usize;
    for fact in &snapshot.facts {
        let qualifier_end = (fact.qualifier_offset as usize)
            .checked_add(fact.qualifier_count as usize)
            .ok_or(ExternalDatasetError::IndexOverflow)?;
        if fact.subject as usize >= snapshot.entities.len()
            || fact.object as usize >= snapshot.entities.len()
            || fact.predicate as usize >= snapshot.relations.len()
            || fact.qualifier_offset as usize != expected_qualifier_offset
            || qualifier_end > snapshot.qualifiers.len()
            || (fact.is_static
                && (fact.observed_at.is_some()
                    || fact.split != ExternalFactSplit::Unsplit
                    || fact.qualifier_count != 0))
            || (temporal_contract
                && !fact.is_static
                && (fact.observed_at.is_none() || fact.split == ExternalFactSplit::Unsplit))
            || (fixed_contract
                && (fact.is_static
                    || fact.observed_at.is_some()
                    || fact.split == ExternalFactSplit::Unsplit))
        {
            return Err(ExternalDatasetError::InvalidInput("fact contract"));
        }
        expected_qualifier_offset = qualifier_end;
    }
    if expected_qualifier_offset != snapshot.qualifiers.len() {
        return Err(ExternalDatasetError::InvalidInput("qualifier coverage"));
    }
    if snapshot.qualifiers.iter().any(|qualifier| {
        qualifier.predicate as usize >= snapshot.relations.len()
            || qualifier.object as usize >= snapshot.entities.len()
    }) {
        return Err(ExternalDatasetError::InvalidInput("qualifier bounds"));
    }
    Ok(())
}

fn source_identity(snapshot: &ExternalDatasetSnapshot) -> Result<String, ExternalDatasetError> {
    source_identity_parts(
        snapshot.name.as_str(),
        snapshot.kind,
        snapshot.upstream_url.as_str(),
        snapshot.upstream_version.as_str(),
        snapshot.license_notice.as_str(),
        &snapshot.split_policy,
        &snapshot.source_files,
    )
}

fn source_identity_parts(
    name: &str,
    kind: ExternalDatasetKind,
    upstream_url: &str,
    upstream_version: &str,
    license_notice: &str,
    split_policy: &ExternalSplitPolicy,
    source_files: &[crate::ExternalSourceFile],
) -> Result<String, ExternalDatasetError> {
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            name,
            kind,
            upstream_url,
            upstream_version,
            license_notice,
            split_policy,
            source_files,
        ))?)
        .to_hex()
    ))
}

fn validate_manifest(manifest: &ExternalDatasetManifest) -> Result<(), ExternalDatasetError> {
    if manifest.schema_version != EXTERNAL_DATASET_SCHEMA
        || manifest.dataset_id.is_empty()
        || manifest.binary_blake3.is_empty()
        || manifest.source_identity.is_empty()
    {
        return Err(ExternalDatasetError::CorruptArtifact("manifest"));
    }
    manifest
        .split_policy
        .validate()
        .map_err(|_| ExternalDatasetError::CorruptArtifact("split policy"))?;
    let expected_source = source_identity_parts(
        manifest.name.as_str(),
        manifest.kind,
        manifest.upstream_url.as_str(),
        manifest.upstream_version.as_str(),
        manifest.license_notice.as_str(),
        &manifest.split_policy,
        &manifest.source_files,
    )?;
    if expected_source != manifest.source_identity {
        return Err(ExternalDatasetError::CorruptArtifact("source identity"));
    }
    let expected = format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            EXTERNAL_DATASET_SCHEMA,
            manifest.source_identity.as_str(),
            manifest.binary_blake3.as_str(),
        ))?)
        .to_hex()
    );
    if expected != manifest.dataset_id {
        return Err(ExternalDatasetError::CorruptArtifact("dataset identity"));
    }
    Ok(())
}

fn validate_header(
    header: &ExternalHeader,
    manifest: &ExternalDatasetManifest,
    bytes: usize,
) -> Result<(), ExternalDatasetError> {
    let entity_offset = le_usize(header.entity_offset)?;
    let relation_offset = le_usize(header.relation_offset)?;
    let fact_offset = le_usize(header.fact_offset)?;
    let qualifier_offset = le_usize(header.qualifier_offset)?;
    let arena_offset = le_usize(header.arena_offset)?;
    let arena_bytes = le_usize(header.arena_bytes)?;
    let expected_relation = entity_offset
        .checked_add(manifest.entities as usize * size_of::<StringRef>())
        .ok_or(ExternalDatasetError::CorruptArtifact("layout"))?;
    let expected_fact = relation_offset
        .checked_add(manifest.relations as usize * size_of::<StringRef>())
        .ok_or(ExternalDatasetError::CorruptArtifact("layout"))?;
    let expected_qualifier = fact_offset
        .checked_add(manifest.facts as usize * size_of::<ExternalFactRecord>())
        .ok_or(ExternalDatasetError::CorruptArtifact("layout"))?;
    let expected_arena = qualifier_offset
        .checked_add(manifest.qualifiers as usize * size_of::<ExternalQualifierRecord>())
        .ok_or(ExternalDatasetError::CorruptArtifact("layout"))?;
    if header.magic != MAGIC
        || u16::from_le_bytes(header.version) != EXTERNAL_DATASET_BINARY_VERSION
        || le_usize(header.total_bytes)? != bytes
        || entity_offset != size_of::<ExternalHeader>()
        || relation_offset != expected_relation
        || fact_offset != expected_fact
        || qualifier_offset != expected_qualifier
        || arena_offset != expected_arena
        || arena_offset.checked_add(arena_bytes) != Some(bytes)
        || u64::from_le_bytes(header.entity_count) != manifest.entities
        || u64::from_le_bytes(header.relation_count) != manifest.relations
        || u64::from_le_bytes(header.fact_count) != manifest.facts
        || u64::from_le_bytes(header.qualifier_count) != manifest.qualifiers
        || header.kind != manifest.kind as u8
        || header.split_authority != manifest.split_policy.authority_code()
    {
        return Err(ExternalDatasetError::CorruptArtifact("layout"));
    }
    Ok(())
}

fn mapped_slice<T: FromBytes + Unaligned>(
    bytes: &[u8],
    offset: usize,
    count: usize,
) -> Result<Ref<&[u8], [T]>, ExternalDatasetError> {
    let byte_len = count
        .checked_mul(size_of::<T>())
        .ok_or(ExternalDatasetError::CorruptArtifact("slice"))?;
    let end = offset
        .checked_add(byte_len)
        .ok_or(ExternalDatasetError::CorruptArtifact("slice"))?;
    Ref::new_slice(
        bytes
            .get(offset..end)
            .ok_or(ExternalDatasetError::CorruptArtifact("slice"))?,
    )
    .ok_or(ExternalDatasetError::CorruptArtifact("slice"))
}

fn write_immutable(path: &Path, bytes: &[u8]) -> Result<(), ExternalDatasetError> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn checked_u32(value: usize) -> Result<u32, ExternalDatasetError> {
    u32::try_from(value).map_err(|_| ExternalDatasetError::IndexOverflow)
}

fn le_usize(value: [u8; 8]) -> Result<usize, ExternalDatasetError> {
    usize::try_from(u64::from_le_bytes(value))
        .map_err(|_| ExternalDatasetError::CorruptArtifact("integer overflow"))
}
