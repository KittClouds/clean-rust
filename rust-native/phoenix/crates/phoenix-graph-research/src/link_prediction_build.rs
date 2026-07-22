use crate::external_dataset_artifact::ExternalFactRecord;
use crate::link_prediction_artifact::write_link_prediction_task;
use crate::tgb_pickle::{parse_tgb_conflict_pickle, TgbConflictEntry};
use crate::{
    ExternalDatasetKind, ExternalDatasetMapped, ExternalFactSplit, LinkPredictionError,
    LinkPredictionQuery, LinkPredictionSplit, LinkPredictionTaskPaths, LinkPredictionTaskSnapshot,
};
use hashbrown::{HashMap, HashSet};
use memmap2::Mmap;
use std::fs::File;
use std::path::Path;

const VALIDATION_PICKLE: &str = "tkgl-smallpedia_val_ns.pkl";
const TEST_PICKLE: &str = "tkgl-smallpedia_test_ns.pkl";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
struct QueryKey {
    observed_at: i64,
    source: u32,
    relation: u32,
}

pub fn build_canonical_link_prediction_task(
    source: &ExternalDatasetMapped,
    source_root: impl AsRef<Path>,
    output_root: impl AsRef<Path>,
) -> Result<LinkPredictionTaskPaths, LinkPredictionError> {
    let manifest = source.manifest();
    if manifest.name != "tkgl-smallpedia"
        || manifest.kind != ExternalDatasetKind::TemporalKnowledgeGraph
        || manifest.temporal_facts == 0
        || manifest.qualifiers != 0
    {
        return Err(LinkPredictionError::InvalidInput(
            "Smallpedia temporal source",
        ));
    }
    let facts = source
        .facts()
        .map_err(|_| LinkPredictionError::InvalidInput("source facts"))?;
    let (candidate_universe, base_relation_count) = temporal_domain(&facts)?;
    let validation = regenerate_conflicts(
        &facts,
        ExternalFactSplit::Validation as u8,
        base_relation_count,
    )?;
    let test = regenerate_conflicts(&facts, ExternalFactSplit::Test as u8, base_relation_count)?;

    let source_root = source_root.as_ref();
    let (validation_pickle, validation_pickle_blake3) = map_and_verify_pickle(
        source,
        source_root.join(VALIDATION_PICKLE),
        VALIDATION_PICKLE,
    )?;
    let (test_pickle, test_pickle_blake3) =
        map_and_verify_pickle(source, source_root.join(TEST_PICKLE), TEST_PICKLE)?;
    let validation_official = parse_tgb_conflict_pickle(&validation_pickle)?;
    let test_official = parse_tgb_conflict_pickle(&test_pickle)?;
    if validation != validation_official {
        return Err(LinkPredictionError::NegativeParity(
            LinkPredictionSplit::Validation,
        ));
    }
    if test != test_official {
        return Err(LinkPredictionError::NegativeParity(
            LinkPredictionSplit::Test,
        ));
    }
    let validation_parity_blake3 = parity_digest(&validation);
    let test_parity_blake3 = parity_digest(&test);
    let (queries, conflicts) = flatten_queries(&validation, &test, base_relation_count)?;
    write_link_prediction_task(
        &LinkPredictionTaskSnapshot {
            source_dataset_id: manifest.dataset_id.clone(),
            source_binary_blake3: manifest.binary_blake3.clone(),
            candidate_universe,
            base_relation_count,
            validation_pickle_blake3: validation_pickle_blake3.into(),
            test_pickle_blake3: test_pickle_blake3.into(),
            validation_parity_blake3: validation_parity_blake3.into(),
            test_parity_blake3: test_parity_blake3.into(),
            queries,
            conflicts,
        },
        output_root,
    )
}

fn temporal_domain(facts: &[ExternalFactRecord]) -> Result<(u32, u32), LinkPredictionError> {
    let mut entities = HashSet::with_capacity(48_000);
    let mut relations = HashSet::with_capacity(300);
    let mut max_entity = 0_u32;
    let mut max_relation = 0_u32;
    for fact in facts.iter().copied().filter(|fact| !fact.is_static()) {
        if fact.observed_at().is_none() || fact.split() == ExternalFactSplit::Unsplit as u8 {
            return Err(LinkPredictionError::InvalidInput("temporal fact"));
        }
        entities.insert(fact.subject());
        entities.insert(fact.object());
        relations.insert(fact.predicate());
        max_entity = max_entity.max(fact.subject()).max(fact.object());
        max_relation = max_relation.max(fact.predicate());
    }
    let candidate_universe = max_entity
        .checked_add(1)
        .ok_or(LinkPredictionError::InvalidInput("entity domain"))?;
    let base_relation_count = max_relation
        .checked_add(1)
        .ok_or(LinkPredictionError::InvalidInput("relation domain"))?;
    if entities.len() != candidate_universe as usize
        || relations.len() != base_relation_count as usize
    {
        return Err(LinkPredictionError::InvalidInput(
            "non-contiguous temporal domain",
        ));
    }
    Ok((candidate_universe, base_relation_count))
}

fn regenerate_conflicts(
    facts: &[ExternalFactRecord],
    split: u8,
    base_relation_count: u32,
) -> Result<Vec<TgbConflictEntry>, LinkPredictionError> {
    let split_facts = facts
        .iter()
        .copied()
        .filter(|fact| !fact.is_static() && fact.split() == split)
        .collect::<Vec<_>>();
    if split_facts.is_empty() {
        return Err(LinkPredictionError::InvalidInput("empty evaluation split"));
    }
    let mut entries = Vec::with_capacity(split_facts.len() * 2);
    let mut query_index = HashMap::with_capacity(split_facts.len() * 2);
    let mut seen_destination = HashSet::with_capacity(split_facts.len() * 2);
    append_direction(
        &split_facts,
        false,
        base_relation_count,
        &mut entries,
        &mut query_index,
        &mut seen_destination,
    )?;
    append_direction(
        &split_facts,
        true,
        base_relation_count,
        &mut entries,
        &mut query_index,
        &mut seen_destination,
    )?;
    Ok(entries)
}

fn append_direction(
    facts: &[ExternalFactRecord],
    inverse: bool,
    base_relation_count: u32,
    entries: &mut Vec<TgbConflictEntry>,
    query_index: &mut HashMap<QueryKey, usize>,
    seen_destination: &mut HashSet<(usize, u32)>,
) -> Result<(), LinkPredictionError> {
    for fact in facts {
        let observed_at = fact
            .observed_at()
            .ok_or(LinkPredictionError::InvalidInput("evaluation time"))?;
        let (source, destination, relation) = if inverse {
            (
                fact.object(),
                fact.subject(),
                fact.predicate()
                    .checked_add(base_relation_count)
                    .ok_or(LinkPredictionError::InvalidInput("inverse relation"))?,
            )
        } else {
            (fact.subject(), fact.object(), fact.predicate())
        };
        let key = QueryKey {
            observed_at,
            source,
            relation,
        };
        let index = match query_index.get(&key).copied() {
            Some(index) => index,
            None => {
                let index = entries.len();
                entries.push(TgbConflictEntry {
                    observed_at,
                    source,
                    relation,
                    destinations: Vec::new(),
                });
                query_index.insert(key, index);
                index
            }
        };
        if seen_destination.insert((index, destination)) {
            entries[index].destinations.push(destination);
        }
    }
    Ok(())
}

fn map_and_verify_pickle(
    source: &ExternalDatasetMapped,
    path: impl AsRef<Path>,
    logical_name: &str,
) -> Result<(Mmap, String), LinkPredictionError> {
    let receipt = source
        .manifest()
        .source_files
        .iter()
        .find(|file| file.logical_name == logical_name)
        .ok_or(LinkPredictionError::InvalidInput("pickle receipt"))?;
    let file = File::open(path)?;
    if file.metadata()?.len() != receipt.bytes {
        return Err(LinkPredictionError::InvalidInput("pickle bytes"));
    }
    let mmap = unsafe { Mmap::map(&file)? };
    let digest = format!("b3-{}", blake3::hash(&mmap).to_hex());
    if digest != receipt.blake3 {
        return Err(LinkPredictionError::InvalidInput("pickle identity"));
    }
    Ok((mmap, digest))
}

fn parity_digest(entries: &[TgbConflictEntry]) -> String {
    let mut hasher = blake3::Hasher::new();
    hasher.update(&(entries.len() as u64).to_le_bytes());
    for entry in entries {
        hasher.update(&entry.observed_at.to_le_bytes());
        hasher.update(&entry.source.to_le_bytes());
        hasher.update(&entry.relation.to_le_bytes());
        hasher.update(&(entry.destinations.len() as u32).to_le_bytes());
        for destination in &entry.destinations {
            hasher.update(&destination.to_le_bytes());
        }
    }
    format!("b3-{}", hasher.finalize().to_hex())
}

fn flatten_queries(
    validation: &[TgbConflictEntry],
    test: &[TgbConflictEntry],
    base_relation_count: u32,
) -> Result<(Vec<LinkPredictionQuery>, Vec<u32>), LinkPredictionError> {
    let query_capacity = validation
        .len()
        .checked_add(test.len())
        .ok_or(LinkPredictionError::InvalidInput("query count"))?;
    let conflict_capacity = validation
        .iter()
        .chain(test)
        .try_fold(0_usize, |total, entry| {
            total.checked_add(entry.destinations.len())
        })
        .ok_or(LinkPredictionError::InvalidInput("conflict count"))?;
    let mut queries = Vec::with_capacity(query_capacity);
    let mut conflicts = Vec::with_capacity(conflict_capacity);
    for (split, entries) in [
        (LinkPredictionSplit::Validation, validation),
        (LinkPredictionSplit::Test, test),
    ] {
        for entry in entries {
            let conflict_offset = u32::try_from(conflicts.len())
                .map_err(|_| LinkPredictionError::InvalidInput("conflict offset"))?;
            let conflict_count = u32::try_from(entry.destinations.len())
                .map_err(|_| LinkPredictionError::InvalidInput("conflict count"))?;
            conflicts.extend_from_slice(&entry.destinations);
            queries.push(LinkPredictionQuery {
                observed_at: entry.observed_at,
                source: entry.source,
                relation: entry.relation,
                conflict_offset,
                conflict_count,
                split,
                inverse: entry.relation >= base_relation_count,
            });
        }
    }
    Ok((queries, conflicts))
}
