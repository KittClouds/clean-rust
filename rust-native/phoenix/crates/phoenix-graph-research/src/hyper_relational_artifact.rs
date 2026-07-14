use crate::external_dataset_artifact::{ExternalFactRecord, ExternalQualifierRecord};
use crate::hyper_relational_binary::{
    mapped, Header, HyperLeU32, HyperQualifierContextRecord, HyperQueryRecord,
    HyperTruthGroupRecord, MAGIC,
};
use crate::{
    ExternalDatasetMapped, HyperRelationalTaskError, HyperRelationalTaskManifest,
    HyperRelationalTaskPaths, HyperRelationalTaskSnapshot, LinkPredictionSplit, ENTITY_ROLE_OBJECT,
    ENTITY_ROLE_PRIMARY, ENTITY_ROLE_QUALIFIER, ENTITY_ROLE_SUBJECT,
    HYPER_RELATIONAL_TASK_BINARY_VERSION, HYPER_RELATIONAL_TASK_SCHEMA, RELATION_ROLE_PRIMARY,
    RELATION_ROLE_QUALIFIER,
};
use memmap2::Mmap;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::mem::size_of;
use std::path::{Component, Path};
use zerocopy::{AsBytes, Ref};

pub(crate) fn write_hyper_relational_task(
    snapshot: &HyperRelationalTaskSnapshot,
    root: impl AsRef<Path>,
) -> Result<HyperRelationalTaskPaths, HyperRelationalTaskError> {
    validate_snapshot(snapshot)?;
    let bytes = encode(snapshot)?;
    let binary_blake3 = format!("b3-{}", blake3::hash(&bytes).to_hex());
    let task_id = task_identity(snapshot, &binary_blake3)?;
    let root = root.as_ref();
    std::fs::create_dir_all(root)?;
    let binary_file = format!("{task_id}.hrl");
    let binary_path = root.join(&binary_file);
    let manifest_path = root.join(format!("{task_id}.manifest.json"));
    if binary_path.exists() || manifest_path.exists() {
        return Err(HyperRelationalTaskError::ArtifactExists(binary_path));
    }
    let validation_queries = snapshot
        .queries
        .iter()
        .filter(|query| query.split == LinkPredictionSplit::Validation)
        .count() as u64;
    let test_queries = snapshot.queries.len() as u64 - validation_queries;
    let primary_entities = snapshot
        .entity_roles
        .iter()
        .filter(|role| **role & ENTITY_ROLE_PRIMARY != 0)
        .count() as u64;
    let qualifier_only_entities = snapshot
        .entity_roles
        .iter()
        .filter(|role| **role & ENTITY_ROLE_QUALIFIER != 0 && **role & ENTITY_ROLE_PRIMARY == 0)
        .count() as u64;
    let primary_relations = snapshot
        .relation_roles
        .iter()
        .filter(|role| **role & RELATION_ROLE_PRIMARY != 0)
        .count() as u64;
    let qualifier_only_relations = snapshot
        .relation_roles
        .iter()
        .filter(|role| **role & RELATION_ROLE_QUALIFIER != 0 && **role & RELATION_ROLE_PRIMARY == 0)
        .count() as u64;
    let manifest = HyperRelationalTaskManifest {
        schema_version: HYPER_RELATIONAL_TASK_SCHEMA.into(),
        task_id: task_id.as_str().into(),
        source_dataset_id: snapshot.source_dataset_id.clone(),
        source_binary_blake3: snapshot.source_binary_blake3.clone(),
        strategy: "wd50k-stare-ordered-qualifier-filtered-full-and-primary-role".into(),
        candidate_universe: snapshot.candidate_universe,
        base_relation_count: snapshot.base_relation_count,
        derived_relation_count: snapshot.base_relation_count * 2,
        official_split_blake3: snapshot.official_split_blake3.clone(),
        statement_blake3: snapshot.statement_blake3.clone(),
        original_qualifier_order_blake3: snapshot.original_qualifier_order_blake3.clone(),
        canonical_qualifier_order_blake3: snapshot.canonical_qualifier_order_blake3.clone(),
        leakage_audit: snapshot.leakage_audit.clone(),
        binary_file: binary_file.into(),
        binary_blake3: binary_blake3.into(),
        binary_bytes: bytes.len() as u64,
        train_statements: snapshot.train_statements,
        validation_statements: snapshot.validation_statements,
        test_statements: snapshot.test_statements,
        validation_queries,
        test_queries,
        truth_groups: snapshot.truth_groups.len() as u64,
        truth_targets: snapshot.truth_targets.len() as u64,
        qualifier_contexts: snapshot.qualifier_contexts.len() as u64,
        train_qualifier_statements: snapshot.train_qualifier_statements,
        validation_qualifier_statements: snapshot.validation_qualifier_statements,
        test_qualifier_statements: snapshot.test_qualifier_statements,
        max_qualifiers: snapshot.max_qualifiers,
        primary_entities,
        qualifier_only_entities,
        primary_relations,
        qualifier_only_relations,
        qualifiers_borrowed_from_source: true,
        test_locked: true,
    };
    write_new(&binary_path, &bytes)?;
    if let Err(error) = write_new(&manifest_path, &serde_json::to_vec_pretty(&manifest)?) {
        let _ = std::fs::remove_file(&binary_path);
        return Err(error);
    }
    Ok(HyperRelationalTaskPaths {
        manifest: manifest_path,
        binary: binary_path,
        task_id: task_id.into(),
    })
}

pub struct HyperRelationalTaskMapped {
    manifest: HyperRelationalTaskManifest,
    mmap: Mmap,
    query_offset: usize,
    group_offset: usize,
    target_offset: usize,
    entity_role_offset: usize,
    relation_role_offset: usize,
    validation_queries: usize,
}

impl HyperRelationalTaskMapped {
    pub fn open(
        manifest_path: impl AsRef<Path>,
        source: &ExternalDatasetMapped,
    ) -> Result<Self, HyperRelationalTaskError> {
        let manifest_path = manifest_path.as_ref();
        let manifest: HyperRelationalTaskManifest =
            serde_json::from_slice(&std::fs::read(manifest_path)?)?;
        validate_manifest(&manifest, source)?;
        let binary_name = Path::new(manifest.binary_file.as_str());
        let mut components = binary_name.components();
        if !matches!(components.next(), Some(Component::Normal(_))) || components.next().is_some() {
            return Err(HyperRelationalTaskError::CorruptArtifact("binary path"));
        }
        let file = File::open(
            manifest_path
                .parent()
                .unwrap_or_else(|| Path::new("."))
                .join(binary_name),
        )?;
        let mmap = unsafe { Mmap::map(&file)? };
        if mmap.len() as u64 != manifest.binary_bytes
            || format!("b3-{}", blake3::hash(&mmap).to_hex()) != manifest.binary_blake3
        {
            return Err(HyperRelationalTaskError::CorruptArtifact("binary identity"));
        }
        let header = Ref::<_, Header>::new(
            mmap.get(..size_of::<Header>())
                .ok_or(HyperRelationalTaskError::CorruptArtifact("header"))?,
        )
        .ok_or(HyperRelationalTaskError::CorruptArtifact("header"))?;
        let offsets = validate_header(&header, &manifest, mmap.len())?;
        let source_facts = source.facts()?;
        let source_qualifiers = source.qualifiers()?;
        validate_records(&mmap, &manifest, offsets, &source_facts, &source_qualifiers)?;
        Ok(Self {
            query_offset: offsets[0],
            group_offset: offsets[1],
            target_offset: offsets[2],
            entity_role_offset: offsets[4],
            relation_role_offset: offsets[5],
            validation_queries: manifest.validation_queries as usize,
            manifest,
            mmap,
        })
    }

    pub fn manifest(&self) -> &HyperRelationalTaskManifest {
        &self.manifest
    }

    pub fn entity_roles(&self) -> &[u8] {
        &self.mmap[self.entity_role_offset
            ..self.entity_role_offset + self.manifest.candidate_universe as usize]
    }

    pub fn relation_roles(&self) -> &[u8] {
        &self.mmap[self.relation_role_offset
            ..self.relation_role_offset + self.manifest.base_relation_count as usize]
    }

    pub(crate) fn queries(
        &self,
        split: LinkPredictionSplit,
    ) -> Result<Ref<&[u8], [HyperQueryRecord]>, HyperRelationalTaskError> {
        let (start, count) = match split {
            LinkPredictionSplit::Validation => (0, self.validation_queries),
            LinkPredictionSplit::Test => {
                (self.validation_queries, self.manifest.test_queries as usize)
            }
        };
        mapped(
            &self.mmap,
            self.query_offset + start * size_of::<HyperQueryRecord>(),
            count,
        )
    }

    pub(crate) fn truth_groups(
        &self,
    ) -> Result<Ref<&[u8], [HyperTruthGroupRecord]>, HyperRelationalTaskError> {
        mapped(
            &self.mmap,
            self.group_offset,
            self.manifest.truth_groups as usize,
        )
    }

    pub(crate) fn truth_targets(
        &self,
    ) -> Result<Ref<&[u8], [HyperLeU32]>, HyperRelationalTaskError> {
        mapped(
            &self.mmap,
            self.target_offset,
            self.manifest.truth_targets as usize,
        )
    }
}

fn encode(snapshot: &HyperRelationalTaskSnapshot) -> Result<Vec<u8>, HyperRelationalTaskError> {
    let queries = snapshot
        .queries
        .iter()
        .map(|query| HyperQueryRecord {
            statement_id: query.statement_id.to_le_bytes(),
            source: query.source.to_le_bytes(),
            target: query.target.to_le_bytes(),
            relation: query.relation.to_le_bytes(),
            qualifier_context: query.qualifier_context.to_le_bytes(),
            truth_group: query.truth_group.to_le_bytes(),
            qualifier_offset: query.qualifier_offset.to_le_bytes(),
            qualifier_count: query.qualifier_count.to_le_bytes(),
        })
        .collect::<Vec<_>>();
    let groups = snapshot
        .truth_groups
        .iter()
        .map(|group| HyperTruthGroupRecord {
            source: group.source.to_le_bytes(),
            relation: group.relation.to_le_bytes(),
            qualifier_context: group.qualifier_context.to_le_bytes(),
            target_offset: group.target_offset.to_le_bytes(),
            target_count: group.target_count.to_le_bytes(),
        })
        .collect::<Vec<_>>();
    let targets = snapshot
        .truth_targets
        .iter()
        .map(|target| HyperLeU32(target.to_le_bytes()))
        .collect::<Vec<_>>();
    let contexts = snapshot
        .qualifier_contexts
        .iter()
        .map(|context| HyperQualifierContextRecord {
            qualifier_offset: context.qualifier_offset.to_le_bytes(),
            qualifier_count: context.qualifier_count.to_le_bytes(),
        })
        .collect::<Vec<_>>();
    let query_offset = size_of::<Header>();
    let group_offset = query_offset + queries.len() * size_of::<HyperQueryRecord>();
    let target_offset = group_offset + groups.len() * size_of::<HyperTruthGroupRecord>();
    let context_offset = target_offset + targets.len() * size_of::<HyperLeU32>();
    let entity_role_offset =
        context_offset + contexts.len() * size_of::<HyperQualifierContextRecord>();
    let relation_role_offset = entity_role_offset + snapshot.entity_roles.len();
    let total_bytes = relation_role_offset
        .checked_add(snapshot.relation_roles.len())
        .ok_or(HyperRelationalTaskError::InvalidInput("binary size"))?;
    let header = Header {
        magic: MAGIC,
        version: HYPER_RELATIONAL_TASK_BINARY_VERSION.to_le_bytes(),
        reserved: [0; 6],
        total_bytes: (total_bytes as u64).to_le_bytes(),
        query_offset: (query_offset as u64).to_le_bytes(),
        query_count: (queries.len() as u64).to_le_bytes(),
        group_offset: (group_offset as u64).to_le_bytes(),
        group_count: (groups.len() as u64).to_le_bytes(),
        target_offset: (target_offset as u64).to_le_bytes(),
        target_count: (targets.len() as u64).to_le_bytes(),
        context_offset: (context_offset as u64).to_le_bytes(),
        context_count: (contexts.len() as u64).to_le_bytes(),
        entity_role_offset: (entity_role_offset as u64).to_le_bytes(),
        entity_role_count: (snapshot.entity_roles.len() as u64).to_le_bytes(),
        relation_role_offset: (relation_role_offset as u64).to_le_bytes(),
        relation_role_count: (snapshot.relation_roles.len() as u64).to_le_bytes(),
    };
    let mut bytes = Vec::with_capacity(total_bytes);
    bytes.extend_from_slice(header.as_bytes());
    bytes.extend_from_slice(queries.as_bytes());
    bytes.extend_from_slice(groups.as_bytes());
    bytes.extend_from_slice(targets.as_bytes());
    bytes.extend_from_slice(contexts.as_bytes());
    bytes.extend_from_slice(&snapshot.entity_roles);
    bytes.extend_from_slice(&snapshot.relation_roles);
    Ok(bytes)
}

fn validate_snapshot(
    snapshot: &HyperRelationalTaskSnapshot,
) -> Result<(), HyperRelationalTaskError> {
    if snapshot.source_dataset_id.is_empty()
        || snapshot.source_binary_blake3.is_empty()
        || snapshot.candidate_universe == 0
        || snapshot.base_relation_count == 0
        || snapshot.queries.is_empty()
        || snapshot.truth_groups.is_empty()
        || snapshot.truth_targets.is_empty()
        || snapshot.qualifier_contexts.is_empty()
        || snapshot.entity_roles.len() != snapshot.candidate_universe as usize
        || snapshot.relation_roles.len() != snapshot.base_relation_count as usize
        || snapshot.train_statements == 0
        || snapshot.validation_statements == 0
        || snapshot.test_statements == 0
    {
        return Err(HyperRelationalTaskError::InvalidInput("empty task section"));
    }
    let derived = snapshot
        .base_relation_count
        .checked_mul(2)
        .ok_or(HyperRelationalTaskError::InvalidInput("relation overflow"))?;
    let mut saw_test = false;
    for query in &snapshot.queries {
        saw_test |= query.split == LinkPredictionSplit::Test;
        if (saw_test && query.split == LinkPredictionSplit::Validation)
            || query.source >= snapshot.candidate_universe
            || query.target >= snapshot.candidate_universe
            || query.relation >= derived
            || query.qualifier_context as usize >= snapshot.qualifier_contexts.len()
            || query.inverse != (query.relation >= snapshot.base_relation_count)
            || query.truth_group as usize >= snapshot.truth_groups.len()
            || !matches!(query.target_role, ENTITY_ROLE_SUBJECT | ENTITY_ROLE_OBJECT)
        {
            return Err(HyperRelationalTaskError::InvalidInput("query contract"));
        }
        let group = snapshot.truth_groups[query.truth_group as usize];
        let start = group.target_offset as usize;
        let end = start
            .checked_add(group.target_count as usize)
            .ok_or(HyperRelationalTaskError::InvalidInput("truth range"))?;
        if (group.source, group.relation, group.qualifier_context)
            != (query.source, query.relation, query.qualifier_context)
            || snapshot
                .truth_targets
                .get(start..end)
                .is_none_or(|targets| targets.binary_search(&query.target).is_err())
            || snapshot.entity_roles[query.target as usize] & query.target_role == 0
        {
            return Err(HyperRelationalTaskError::InvalidInput("query truth"));
        }
    }
    let mut expected = 0_usize;
    for group in &snapshot.truth_groups {
        if group.source >= snapshot.candidate_universe
            || group.relation >= derived
            || group.qualifier_context as usize >= snapshot.qualifier_contexts.len()
            || group.target_count == 0
            || group.target_offset as usize != expected
        {
            return Err(HyperRelationalTaskError::InvalidInput("truth group"));
        }
        expected = expected
            .checked_add(group.target_count as usize)
            .ok_or(HyperRelationalTaskError::InvalidInput("truth overflow"))?;
    }
    if expected != snapshot.truth_targets.len()
        || snapshot
            .truth_targets
            .iter()
            .any(|target| *target >= snapshot.candidate_universe)
        || snapshot
            .entity_roles
            .iter()
            .any(|role| *role & !(ENTITY_ROLE_PRIMARY | ENTITY_ROLE_QUALIFIER) != 0)
        || snapshot
            .relation_roles
            .iter()
            .any(|role| *role & !(RELATION_ROLE_PRIMARY | RELATION_ROLE_QUALIFIER) != 0)
    {
        return Err(HyperRelationalTaskError::InvalidInput("truth targets"));
    }
    Ok(())
}

fn task_identity(
    snapshot: &HyperRelationalTaskSnapshot,
    binary_blake3: &str,
) -> Result<String, HyperRelationalTaskError> {
    identity(&(
        HYPER_RELATIONAL_TASK_SCHEMA,
        snapshot.source_dataset_id.as_str(),
        snapshot.source_binary_blake3.as_str(),
        snapshot.official_split_blake3.as_str(),
        snapshot.statement_blake3.as_str(),
        snapshot.original_qualifier_order_blake3.as_str(),
        snapshot.canonical_qualifier_order_blake3.as_str(),
        &snapshot.leakage_audit,
        binary_blake3,
    ))
}

fn validate_manifest(
    manifest: &HyperRelationalTaskManifest,
    source: &ExternalDatasetMapped,
) -> Result<(), HyperRelationalTaskError> {
    if manifest.schema_version != HYPER_RELATIONAL_TASK_SCHEMA
        || manifest.strategy != "wd50k-stare-ordered-qualifier-filtered-full-and-primary-role"
        || !manifest.qualifiers_borrowed_from_source
        || !manifest.test_locked
        || manifest.source_dataset_id != source.manifest().dataset_id
        || manifest.source_binary_blake3 != source.manifest().binary_blake3
        || manifest.candidate_universe as u64 != source.manifest().entities
        || manifest.base_relation_count as u64 != source.manifest().relations
        || manifest.base_relation_count.checked_mul(2) != Some(manifest.derived_relation_count)
        || manifest.validation_queries != manifest.validation_statements * 2
        || manifest.test_queries != manifest.test_statements * 2
    {
        return Err(HyperRelationalTaskError::CorruptArtifact("manifest"));
    }
    let expected = identity(&(
        HYPER_RELATIONAL_TASK_SCHEMA,
        manifest.source_dataset_id.as_str(),
        manifest.source_binary_blake3.as_str(),
        manifest.official_split_blake3.as_str(),
        manifest.statement_blake3.as_str(),
        manifest.original_qualifier_order_blake3.as_str(),
        manifest.canonical_qualifier_order_blake3.as_str(),
        &manifest.leakage_audit,
        manifest.binary_blake3.as_str(),
    ))?;
    if expected != manifest.task_id {
        return Err(HyperRelationalTaskError::CorruptArtifact("task identity"));
    }
    Ok(())
}

fn validate_header(
    header: &Header,
    manifest: &HyperRelationalTaskManifest,
    bytes: usize,
) -> Result<[usize; 6], HyperRelationalTaskError> {
    let offsets = [
        le_usize(header.query_offset)?,
        le_usize(header.group_offset)?,
        le_usize(header.target_offset)?,
        le_usize(header.context_offset)?,
        le_usize(header.entity_role_offset)?,
        le_usize(header.relation_role_offset)?,
    ];
    let query_count = manifest
        .validation_queries
        .checked_add(manifest.test_queries)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or(HyperRelationalTaskError::CorruptArtifact("layout"))?;
    let expected = [
        size_of::<Header>(),
        section_end(offsets[0], query_count, size_of::<HyperQueryRecord>())?,
        section_end(
            offsets[1],
            manifest.truth_groups,
            size_of::<HyperTruthGroupRecord>(),
        )?,
        section_end(offsets[2], manifest.truth_targets, size_of::<HyperLeU32>())?,
        section_end(
            offsets[3],
            manifest.qualifier_contexts,
            size_of::<HyperQualifierContextRecord>(),
        )?,
        section_end(offsets[4], u64::from(manifest.candidate_universe), 1)?,
    ];
    let total = offsets[5]
        .checked_add(manifest.base_relation_count as usize)
        .ok_or(HyperRelationalTaskError::CorruptArtifact("layout"))?;
    if header.magic != MAGIC
        || u16::from_le_bytes(header.version) != HYPER_RELATIONAL_TASK_BINARY_VERSION
        || le_usize(header.total_bytes)? != bytes
        || offsets != expected
        || total != bytes
        || u64::from_le_bytes(header.query_count)
            != manifest.validation_queries + manifest.test_queries
        || u64::from_le_bytes(header.group_count) != manifest.truth_groups
        || u64::from_le_bytes(header.target_count) != manifest.truth_targets
        || u64::from_le_bytes(header.context_count) != manifest.qualifier_contexts
        || u64::from_le_bytes(header.entity_role_count) != u64::from(manifest.candidate_universe)
        || u64::from_le_bytes(header.relation_role_count) != u64::from(manifest.base_relation_count)
    {
        return Err(HyperRelationalTaskError::CorruptArtifact("layout"));
    }
    Ok(offsets)
}

fn validate_records(
    bytes: &[u8],
    manifest: &HyperRelationalTaskManifest,
    offsets: [usize; 6],
    source_facts: &[ExternalFactRecord],
    source_qualifiers: &[ExternalQualifierRecord],
) -> Result<(), HyperRelationalTaskError> {
    let query_count = (manifest.validation_queries + manifest.test_queries) as usize;
    let queries = mapped::<HyperQueryRecord>(bytes, offsets[0], query_count)?;
    let groups =
        mapped::<HyperTruthGroupRecord>(bytes, offsets[1], manifest.truth_groups as usize)?;
    let targets = mapped::<HyperLeU32>(bytes, offsets[2], manifest.truth_targets as usize)?;
    let contexts = mapped::<HyperQualifierContextRecord>(
        bytes,
        offsets[3],
        manifest.qualifier_contexts as usize,
    )?;
    for context in contexts.iter().copied() {
        qualifier_range(
            context.qualifier_offset(),
            context.qualifier_count(),
            source_qualifiers,
        )?;
    }
    let mut expected = 0_usize;
    for (index, group) in groups.iter().copied().enumerate() {
        if group.target_offset() as usize != expected
            || group.target_count() == 0
            || group.source() >= manifest.candidate_universe
            || group.relation() >= manifest.derived_relation_count
            || group.qualifier_context() as usize >= contexts.len()
            || (index > 0
                && (
                    groups[index - 1].source(),
                    groups[index - 1].relation(),
                    groups[index - 1].qualifier_context(),
                ) >= (group.source(), group.relation(), group.qualifier_context()))
        {
            return Err(HyperRelationalTaskError::CorruptArtifact("truth group"));
        }
        expected = expected
            .checked_add(group.target_count() as usize)
            .ok_or(HyperRelationalTaskError::CorruptArtifact("truth range"))?;
    }
    if expected != targets.len()
        || targets
            .iter()
            .copied()
            .any(|target| target.get() >= manifest.candidate_universe)
    {
        return Err(HyperRelationalTaskError::CorruptArtifact("truth target"));
    }
    let mut validation = 0_u64;
    for (index, query) in queries.iter().copied().enumerate() {
        let is_validation = index < manifest.validation_queries as usize;
        if query.source() >= manifest.candidate_universe
            || query.target() >= manifest.candidate_universe
            || query.relation() >= manifest.derived_relation_count
            || query.qualifier_context() as usize >= contexts.len()
            || query.truth_group() as usize >= groups.len()
        {
            return Err(HyperRelationalTaskError::CorruptArtifact("query"));
        }
        let group = groups[query.truth_group() as usize];
        let start = group.target_offset() as usize;
        let end = start
            .checked_add(group.target_count() as usize)
            .ok_or(HyperRelationalTaskError::CorruptArtifact("truth range"))?;
        let fact = source_facts
            .get(query.statement_id() as usize)
            .copied()
            .ok_or(HyperRelationalTaskError::CorruptArtifact("statement id"))?;
        let expected_inverse = query.relation() >= manifest.base_relation_count;
        let expected_source = if expected_inverse {
            fact.object()
        } else {
            fact.subject()
        };
        let expected_target = if expected_inverse {
            fact.subject()
        } else {
            fact.object()
        };
        let expected_relation =
            fact.predicate() + u32::from(expected_inverse) * manifest.base_relation_count;
        let expected_split = if is_validation {
            crate::ExternalFactSplit::Validation as u8
        } else {
            crate::ExternalFactSplit::Test as u8
        };
        let context = contexts[query.qualifier_context() as usize];
        let query_qualifiers = qualifier_range(
            query.qualifier_offset(),
            query.qualifier_count(),
            source_qualifiers,
        )?;
        let context_qualifiers = qualifier_range(
            context.qualifier_offset(),
            context.qualifier_count(),
            source_qualifiers,
        )?;
        if (group.source(), group.relation(), group.qualifier_context())
            != (query.source(), query.relation(), query.qualifier_context())
            || targets[start..end]
                .binary_search_by_key(&query.target(), |target| target.get())
                .is_err()
            || query.source() != expected_source
            || query.target() != expected_target
            || query.relation() != expected_relation
            || query.qualifier_offset() != fact.qualifier_offset()
            || query.qualifier_count() != fact.qualifier_count()
            || !same_qualifiers(query_qualifiers, context_qualifiers)
            || fact.split() != expected_split
        {
            return Err(HyperRelationalTaskError::CorruptArtifact(
                "query source binding",
            ));
        }
        validation += u64::from(is_validation);
    }
    if validation != manifest.validation_queries {
        return Err(HyperRelationalTaskError::CorruptArtifact("query counts"));
    }
    let entity_roles = bytes
        .get(offsets[4]..offsets[5])
        .ok_or(HyperRelationalTaskError::CorruptArtifact("entity roles"))?;
    let relation_roles = bytes
        .get(offsets[5]..)
        .ok_or(HyperRelationalTaskError::CorruptArtifact("relation roles"))?;
    if entity_roles
        .iter()
        .any(|role| *role & !(ENTITY_ROLE_PRIMARY | ENTITY_ROLE_QUALIFIER) != 0)
        || relation_roles
            .iter()
            .any(|role| *role & !(RELATION_ROLE_PRIMARY | RELATION_ROLE_QUALIFIER) != 0)
    {
        return Err(HyperRelationalTaskError::CorruptArtifact("role bits"));
    }
    for group in groups.iter().copied() {
        let target_role = if group.relation() < manifest.base_relation_count {
            ENTITY_ROLE_OBJECT
        } else {
            ENTITY_ROLE_SUBJECT
        };
        let start = group.target_offset() as usize;
        let end = start + group.target_count() as usize;
        if targets[start..end]
            .iter()
            .copied()
            .any(|target| entity_roles[target.get() as usize] & target_role == 0)
        {
            return Err(HyperRelationalTaskError::CorruptArtifact("truth role"));
        }
    }
    Ok(())
}

fn qualifier_range(
    offset: u32,
    count: u32,
    qualifiers: &[ExternalQualifierRecord],
) -> Result<&[ExternalQualifierRecord], HyperRelationalTaskError> {
    let start = offset as usize;
    let end =
        start
            .checked_add(count as usize)
            .ok_or(HyperRelationalTaskError::CorruptArtifact(
                "qualifier context",
            ))?;
    qualifiers
        .get(start..end)
        .ok_or(HyperRelationalTaskError::CorruptArtifact(
            "qualifier context",
        ))
}

fn same_qualifiers(left: &[ExternalQualifierRecord], right: &[ExternalQualifierRecord]) -> bool {
    left.len() == right.len()
        && left.iter().zip(right).all(|(left, right)| {
            left.predicate() == right.predicate() && left.object() == right.object()
        })
}

fn section_end(
    offset: usize,
    count: impl TryInto<usize>,
    width: usize,
) -> Result<usize, HyperRelationalTaskError> {
    let count = count
        .try_into()
        .map_err(|_| HyperRelationalTaskError::CorruptArtifact("layout"))?;
    count
        .checked_mul(width)
        .and_then(|length| offset.checked_add(length))
        .ok_or(HyperRelationalTaskError::CorruptArtifact("layout"))
}

fn identity<T: serde::Serialize>(value: &T) -> Result<String, HyperRelationalTaskError> {
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), HyperRelationalTaskError> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn le_usize(value: [u8; 8]) -> Result<usize, HyperRelationalTaskError> {
    usize::try_from(u64::from_le_bytes(value))
        .map_err(|_| HyperRelationalTaskError::CorruptArtifact("integer overflow"))
}
