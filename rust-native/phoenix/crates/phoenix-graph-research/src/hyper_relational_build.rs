use crate::external_dataset_artifact::{ExternalFactRecord, ExternalQualifierRecord};
use crate::hyper_relational_artifact::write_hyper_relational_task;
use crate::{
    ExternalDatasetKind, ExternalDatasetMapped, ExternalFactSplit, ExternalSplitPolicy,
    HyperRelationalLeakageAudit, HyperRelationalQualifierContext, HyperRelationalQuery,
    HyperRelationalTaskError, HyperRelationalTaskPaths, HyperRelationalTaskSnapshot,
    HyperRelationalTruthGroup, LinkPredictionSplit, ENTITY_ROLE_OBJECT, ENTITY_ROLE_QUALIFIER,
    ENTITY_ROLE_SUBJECT, RELATION_ROLE_PRIMARY, RELATION_ROLE_QUALIFIER,
};
use hashbrown::HashMap;
use std::path::Path;

const TRAIN_MASK: u8 = 1;
const VALIDATION_MASK: u8 = 2;
const TEST_MASK: u8 = 4;

#[derive(Default)]
struct StatementSeen {
    mask: u8,
    original: [Option<[u8; 32]>; 3],
}

pub fn build_canonical_hyper_relational_task(
    source: &ExternalDatasetMapped,
    output_root: impl AsRef<Path>,
) -> Result<HyperRelationalTaskPaths, HyperRelationalTaskError> {
    validate_source(source)?;
    let manifest = source.manifest();
    let facts = source.facts()?;
    let qualifiers = source.qualifiers()?;
    let candidate_universe = u32::try_from(manifest.entities)
        .map_err(|_| HyperRelationalTaskError::InvalidInput("entity count"))?;
    let base_relation_count = u32::try_from(manifest.relations)
        .map_err(|_| HyperRelationalTaskError::InvalidInput("relation count"))?;
    base_relation_count
        .checked_mul(2)
        .ok_or(HyperRelationalTaskError::InvalidInput("relation overflow"))?;
    let mut entity_roles = vec![0_u8; candidate_universe as usize];
    let mut relation_roles = vec![0_u8; base_relation_count as usize];
    let mut truth_entries = Vec::with_capacity(facts.len() * 2);
    let mut qualifier_contexts = vec![HyperRelationalQualifierContext {
        qualifier_offset: 0,
        qualifier_count: 0,
    }];
    let mut qualifier_context_index = HashMap::<[u8; 32], u32>::with_capacity(32_768);
    qualifier_context_index.insert(qualifier_context_digest(&[]), 0);
    let mut fact_contexts = Vec::with_capacity(facts.len());
    let mut primary_seen = HashMap::<(u32, u32, u32), u8>::with_capacity(facts.len());
    let mut statement_seen = HashMap::<[u8; 32], StatementSeen>::with_capacity(facts.len());
    let mut original_order = blake3::Hasher::new();
    let mut canonical_order = blake3::Hasher::new();
    let mut statement_hasher = blake3::Hasher::new();
    let mut canonical_pairs = Vec::<(u32, u32)>::new();
    let mut split_counts = [0_u64; 3];
    let mut qualifier_counts = [0_u64; 3];
    let mut max_qualifiers = 0_u32;

    for (statement_id, fact) in facts.iter().copied().enumerate() {
        let split_index = split_index(fact.split())?;
        let split_mask = 1_u8 << split_index;
        validate_fact(
            fact,
            qualifiers.len(),
            candidate_universe,
            base_relation_count,
        )?;
        split_counts[split_index] += 1;
        qualifier_counts[split_index] += u64::from(fact.qualifier_count() != 0);
        max_qualifiers = max_qualifiers.max(fact.qualifier_count());
        entity_roles[fact.subject() as usize] |= ENTITY_ROLE_SUBJECT;
        entity_roles[fact.object() as usize] |= ENTITY_ROLE_OBJECT;
        relation_roles[fact.predicate() as usize] |= RELATION_ROLE_PRIMARY;
        let statement_qualifiers = qualifier_slice(fact, &qualifiers)?;
        let qualifier_context = intern_qualifier_context(
            fact,
            statement_qualifiers,
            &qualifiers,
            &mut qualifier_contexts,
            &mut qualifier_context_index,
        )?;
        fact_contexts.push(qualifier_context);
        canonical_pairs.clear();
        for qualifier in statement_qualifiers.iter().copied() {
            if qualifier.object() >= candidate_universe
                || qualifier.predicate() >= base_relation_count
            {
                return Err(HyperRelationalTaskError::InvalidInput("qualifier"));
            }
            entity_roles[qualifier.object() as usize] |= ENTITY_ROLE_QUALIFIER;
            relation_roles[qualifier.predicate() as usize] |= RELATION_ROLE_QUALIFIER;
            canonical_pairs.push((qualifier.predicate(), qualifier.object()));
        }
        hash_qualifier_order(&mut original_order, statement_id as u32, &canonical_pairs);
        let original_digest = statement_digest(fact, &canonical_pairs);
        canonical_pairs.sort_unstable();
        hash_qualifier_order(&mut canonical_order, statement_id as u32, &canonical_pairs);
        hash_statement(&mut statement_hasher, fact, &canonical_pairs);
        let canonical_digest = statement_digest(fact, &canonical_pairs);
        let seen = statement_seen.entry(canonical_digest).or_default();
        seen.mask |= split_mask;
        seen.original[split_index].get_or_insert(original_digest);
        *primary_seen
            .entry((fact.subject(), fact.predicate(), fact.object()))
            .or_default() |= split_mask;
        truth_entries.push((
            fact.subject(),
            fact.predicate(),
            qualifier_context,
            fact.object(),
        ));
        truth_entries.push((
            fact.object(),
            fact.predicate() + base_relation_count,
            qualifier_context,
            fact.subject(),
        ));
    }
    truth_entries.sort_unstable();
    truth_entries.dedup();
    let (truth_groups, truth_targets) = group_truth(&truth_entries)?;
    let queries = build_queries(
        &facts,
        &fact_contexts,
        &truth_groups,
        &truth_targets,
        base_relation_count,
    )?;
    let leakage_audit = leakage_audit(&primary_seen, &statement_seen);
    let official_split_blake3 = format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(&(
            manifest.split_policy.clone(),
            &manifest.source_files,
            split_counts,
        ))?)
        .to_hex()
    );
    write_hyper_relational_task(
        &HyperRelationalTaskSnapshot {
            source_dataset_id: manifest.dataset_id.clone(),
            source_binary_blake3: manifest.binary_blake3.clone(),
            candidate_universe,
            base_relation_count,
            official_split_blake3: official_split_blake3.into(),
            statement_blake3: format!("b3-{}", statement_hasher.finalize().to_hex()).into(),
            original_qualifier_order_blake3: format!("b3-{}", original_order.finalize().to_hex())
                .into(),
            canonical_qualifier_order_blake3: format!("b3-{}", canonical_order.finalize().to_hex())
                .into(),
            leakage_audit,
            queries,
            truth_groups,
            truth_targets,
            qualifier_contexts,
            entity_roles,
            relation_roles,
            train_statements: split_counts[0],
            validation_statements: split_counts[1],
            test_statements: split_counts[2],
            train_qualifier_statements: qualifier_counts[0],
            validation_qualifier_statements: qualifier_counts[1],
            test_qualifier_statements: qualifier_counts[2],
            max_qualifiers,
        },
        output_root,
    )
}

fn validate_source(source: &ExternalDatasetMapped) -> Result<(), HyperRelationalTaskError> {
    let manifest = source.manifest();
    if manifest.name != "wd50k"
        || manifest.kind != ExternalDatasetKind::HyperRelationalKnowledgeGraph
        || manifest.qualifiers == 0
        || manifest.temporal_facts != 0
        || !matches!(
            manifest.split_policy,
            ExternalSplitPolicy::OfficialFixed { .. }
        )
    {
        return Err(HyperRelationalTaskError::InvalidInput("WD50K source"));
    }
    Ok(())
}

fn validate_fact(
    fact: ExternalFactRecord,
    qualifiers: usize,
    entities: u32,
    relations: u32,
) -> Result<(), HyperRelationalTaskError> {
    let end = (fact.qualifier_offset() as usize)
        .checked_add(fact.qualifier_count() as usize)
        .ok_or(HyperRelationalTaskError::InvalidInput("qualifier range"))?;
    if fact.is_static()
        || fact.observed_at().is_some()
        || fact.subject() >= entities
        || fact.object() >= entities
        || fact.predicate() >= relations
        || end > qualifiers
    {
        return Err(HyperRelationalTaskError::InvalidInput("statement"));
    }
    split_index(fact.split())?;
    Ok(())
}

fn qualifier_slice(
    fact: ExternalFactRecord,
    qualifiers: &[ExternalQualifierRecord],
) -> Result<&[ExternalQualifierRecord], HyperRelationalTaskError> {
    let start = fact.qualifier_offset() as usize;
    let end = start
        .checked_add(fact.qualifier_count() as usize)
        .ok_or(HyperRelationalTaskError::InvalidInput("qualifier range"))?;
    qualifiers
        .get(start..end)
        .ok_or(HyperRelationalTaskError::InvalidInput("qualifier range"))
}

fn intern_qualifier_context(
    fact: ExternalFactRecord,
    current: &[ExternalQualifierRecord],
    qualifiers: &[ExternalQualifierRecord],
    contexts: &mut Vec<HyperRelationalQualifierContext>,
    index: &mut HashMap<[u8; 32], u32>,
) -> Result<u32, HyperRelationalTaskError> {
    let digest = qualifier_context_digest(current);
    if let Some(context_id) = index.get(&digest).copied() {
        let context = contexts[context_id as usize];
        let representative = qualifiers
            .get(
                context.qualifier_offset as usize
                    ..context.qualifier_offset as usize + context.qualifier_count as usize,
            )
            .ok_or(HyperRelationalTaskError::InvalidInput("qualifier context"))?;
        if same_qualifiers(current, representative) {
            return Ok(context_id);
        }
        return Err(HyperRelationalTaskError::InvalidInput(
            "qualifier context hash collision",
        ));
    }
    let context_id = u32::try_from(contexts.len())
        .map_err(|_| HyperRelationalTaskError::InvalidInput("qualifier contexts"))?;
    contexts.push(HyperRelationalQualifierContext {
        qualifier_offset: fact.qualifier_offset(),
        qualifier_count: fact.qualifier_count(),
    });
    index.insert(digest, context_id);
    Ok(context_id)
}

fn qualifier_context_digest(qualifiers: &[ExternalQualifierRecord]) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(&(qualifiers.len() as u32).to_le_bytes());
    for qualifier in qualifiers {
        hasher.update(&qualifier.predicate().to_le_bytes());
        hasher.update(&qualifier.object().to_le_bytes());
    }
    *hasher.finalize().as_bytes()
}

fn same_qualifiers(left: &[ExternalQualifierRecord], right: &[ExternalQualifierRecord]) -> bool {
    left.len() == right.len()
        && left.iter().zip(right).all(|(left, right)| {
            left.predicate() == right.predicate() && left.object() == right.object()
        })
}

fn split_index(split: u8) -> Result<usize, HyperRelationalTaskError> {
    match split {
        value if value == ExternalFactSplit::Train as u8 => Ok(0),
        value if value == ExternalFactSplit::Validation as u8 => Ok(1),
        value if value == ExternalFactSplit::Test as u8 => Ok(2),
        _ => Err(HyperRelationalTaskError::InvalidInput("official split")),
    }
}

fn hash_qualifier_order(hasher: &mut blake3::Hasher, statement: u32, pairs: &[(u32, u32)]) {
    hasher.update(&statement.to_le_bytes());
    hasher.update(&(pairs.len() as u32).to_le_bytes());
    for (relation, entity) in pairs {
        hasher.update(&relation.to_le_bytes());
        hasher.update(&entity.to_le_bytes());
    }
}

fn hash_statement(hasher: &mut blake3::Hasher, fact: ExternalFactRecord, pairs: &[(u32, u32)]) {
    hasher.update(&[fact.split()]);
    hasher.update(&fact.subject().to_le_bytes());
    hasher.update(&fact.predicate().to_le_bytes());
    hasher.update(&fact.object().to_le_bytes());
    hasher.update(&(pairs.len() as u32).to_le_bytes());
    for (relation, entity) in pairs {
        hasher.update(&relation.to_le_bytes());
        hasher.update(&entity.to_le_bytes());
    }
}

fn statement_digest(fact: ExternalFactRecord, pairs: &[(u32, u32)]) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(&fact.subject().to_le_bytes());
    hasher.update(&fact.predicate().to_le_bytes());
    hasher.update(&fact.object().to_le_bytes());
    hasher.update(&(pairs.len() as u32).to_le_bytes());
    for (relation, entity) in pairs {
        hasher.update(&relation.to_le_bytes());
        hasher.update(&entity.to_le_bytes());
    }
    *hasher.finalize().as_bytes()
}

fn group_truth(
    entries: &[(u32, u32, u32, u32)],
) -> Result<(Vec<HyperRelationalTruthGroup>, Vec<u32>), HyperRelationalTaskError> {
    let mut groups = Vec::new();
    let mut targets = Vec::with_capacity(entries.len());
    let mut start = 0_usize;
    while start < entries.len() {
        let key = (entries[start].0, entries[start].1, entries[start].2);
        let mut end = start + 1;
        while end < entries.len() && (entries[end].0, entries[end].1, entries[end].2) == key {
            end += 1;
        }
        groups.push(HyperRelationalTruthGroup {
            source: key.0,
            relation: key.1,
            qualifier_context: key.2,
            target_offset: u32::try_from(targets.len())
                .map_err(|_| HyperRelationalTaskError::InvalidInput("truth offset"))?,
            target_count: u32::try_from(end - start)
                .map_err(|_| HyperRelationalTaskError::InvalidInput("truth count"))?,
        });
        targets.extend(entries[start..end].iter().map(|entry| entry.3));
        start = end;
    }
    Ok((groups, targets))
}

fn build_queries(
    facts: &[ExternalFactRecord],
    fact_contexts: &[u32],
    groups: &[HyperRelationalTruthGroup],
    targets: &[u32],
    base_relations: u32,
) -> Result<Vec<HyperRelationalQuery>, HyperRelationalTaskError> {
    let evaluation_statements = facts
        .iter()
        .filter(|fact| {
            fact.split() == ExternalFactSplit::Validation as u8
                || fact.split() == ExternalFactSplit::Test as u8
        })
        .count();
    let mut queries = Vec::with_capacity(evaluation_statements * 2);
    for (external_split, split) in [
        (
            ExternalFactSplit::Validation as u8,
            LinkPredictionSplit::Validation,
        ),
        (ExternalFactSplit::Test as u8, LinkPredictionSplit::Test),
    ] {
        for (statement_id, fact) in facts.iter().copied().enumerate() {
            if fact.split() != external_split {
                continue;
            }
            append_query(
                &mut queries,
                groups,
                targets,
                statement_id as u32,
                fact,
                fact_contexts[statement_id],
                split,
                false,
                base_relations,
            )?;
            append_query(
                &mut queries,
                groups,
                targets,
                statement_id as u32,
                fact,
                fact_contexts[statement_id],
                split,
                true,
                base_relations,
            )?;
        }
    }
    Ok(queries)
}

#[allow(clippy::too_many_arguments)]
fn append_query(
    queries: &mut Vec<HyperRelationalQuery>,
    groups: &[HyperRelationalTruthGroup],
    targets: &[u32],
    statement_id: u32,
    fact: ExternalFactRecord,
    qualifier_context: u32,
    split: LinkPredictionSplit,
    inverse: bool,
    base_relations: u32,
) -> Result<(), HyperRelationalTaskError> {
    let (source, target, relation, target_role) = if inverse {
        (
            fact.object(),
            fact.subject(),
            fact.predicate() + base_relations,
            ENTITY_ROLE_SUBJECT,
        )
    } else {
        (
            fact.subject(),
            fact.object(),
            fact.predicate(),
            ENTITY_ROLE_OBJECT,
        )
    };
    let group_index = groups
        .binary_search_by_key(&(source, relation, qualifier_context), |group| {
            (group.source, group.relation, group.qualifier_context)
        })
        .map_err(|_| HyperRelationalTaskError::InvalidInput("truth lookup"))?;
    let group = groups[group_index];
    let start = group.target_offset as usize;
    let end = start + group.target_count as usize;
    if targets[start..end].binary_search(&target).is_err() {
        return Err(HyperRelationalTaskError::InvalidInput("positive truth"));
    }
    queries.push(HyperRelationalQuery {
        statement_id,
        source,
        target,
        relation,
        qualifier_context,
        truth_group: group_index as u32,
        qualifier_offset: fact.qualifier_offset(),
        qualifier_count: fact.qualifier_count(),
        split,
        inverse,
        target_role,
    });
    Ok(())
}

fn leakage_audit(
    primary: &HashMap<(u32, u32, u32), u8>,
    statements: &HashMap<[u8; 32], StatementSeen>,
) -> HyperRelationalLeakageAudit {
    HyperRelationalLeakageAudit {
        train_validation_primary_overlap: cross_mask_count(
            primary.values().copied(),
            TRAIN_MASK,
            VALIDATION_MASK,
        ),
        train_test_primary_overlap: cross_mask_count(
            primary.values().copied(),
            TRAIN_MASK,
            TEST_MASK,
        ),
        validation_test_primary_overlap: cross_mask_count(
            primary.values().copied(),
            VALIDATION_MASK,
            TEST_MASK,
        ),
        train_validation_direct_inverse_overlap: inverse_count(
            primary,
            TRAIN_MASK,
            VALIDATION_MASK,
        ),
        train_test_direct_inverse_overlap: inverse_count(primary, TRAIN_MASK, TEST_MASK),
        validation_test_direct_inverse_overlap: inverse_count(primary, VALIDATION_MASK, TEST_MASK),
        train_validation_statement_duplicates: cross_mask_count(
            statements.values().map(|seen| seen.mask),
            TRAIN_MASK,
            VALIDATION_MASK,
        ),
        train_test_statement_duplicates: cross_mask_count(
            statements.values().map(|seen| seen.mask),
            TRAIN_MASK,
            TEST_MASK,
        ),
        validation_test_statement_duplicates: cross_mask_count(
            statements.values().map(|seen| seen.mask),
            VALIDATION_MASK,
            TEST_MASK,
        ),
        cross_split_reordered_qualifier_duplicates: statements
            .values()
            .filter(|seen| reordered_across_splits(seen))
            .count() as u64,
        semantic_inverse_policy: "source-declares-no-semantic-inverse-map".into(),
    }
}

fn cross_mask_count(values: impl Iterator<Item = u8>, left: u8, right: u8) -> u64 {
    values
        .filter(|mask| *mask & left != 0 && *mask & right != 0)
        .count() as u64
}

fn inverse_count(primary: &HashMap<(u32, u32, u32), u8>, left: u8, right: u8) -> u64 {
    primary
        .iter()
        .filter(|((subject, relation, object), mask)| {
            **mask & left != 0
                && primary
                    .get(&(*object, *relation, *subject))
                    .is_some_and(|reverse| *reverse & right != 0)
        })
        .count() as u64
}

fn reordered_across_splits(seen: &StatementSeen) -> bool {
    for left in 0..3 {
        for right in left + 1..3 {
            if let (Some(left), Some(right)) = (seen.original[left], seen.original[right]) {
                if left != right {
                    return true;
                }
            }
        }
    }
    false
}
