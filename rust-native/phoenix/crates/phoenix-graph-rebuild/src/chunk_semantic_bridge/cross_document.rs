use super::frequency_profile::EntityFrequencyIndex;
use super::semantic_admission::{
    classify_semantic_pair, SemanticEntitySupport, SemanticTargetIndex,
};
use super::*;

const CROSS_DOCUMENT_TARGET_SCAN_PER_CHUNK: usize = 12;

pub(super) fn extend_cross_document_bridges<'a>(
    bridges: &mut HashMap<CompactString, ChunkSemanticBridgeCandidate>,
    input: ChunkSemanticBridgeEngineInput<'a>,
    index: &'a EngineIndex<'a>,
    frequency: &EntityFrequencyIndex<'a>,
) {
    let notes = note_buckets(input.chunks);
    if notes.len() < 2 {
        return;
    }

    for source_note in 0..notes.len() - 1 {
        for target_note in source_note + 1..notes.len() {
            compare_document_pair(
                bridges,
                input,
                index,
                &notes[source_note],
                &notes[target_note],
                frequency,
            );
        }
    }
}

fn compare_document_pair<'a>(
    bridges: &mut HashMap<CompactString, ChunkSemanticBridgeCandidate>,
    input: ChunkSemanticBridgeEngineInput<'a>,
    index: &'a EngineIndex<'a>,
    source_rows: &[usize],
    target_rows: &[usize],
    frequency: &EntityFrequencyIndex<'a>,
) {
    let semantic_targets = SemanticTargetIndex::new(input, index, target_rows);
    let mut target_by_entity = HashMap::<&EntityId, Vec<usize>>::new();
    for target_index in target_rows {
        for entity_id in input.chunks[*target_index]
            .entity_ids
            .iter()
            .filter(|entity_id| !frequency.is_frequency_floor(entity_id))
        {
            target_by_entity
                .entry(entity_id)
                .or_default()
                .push(*target_index);
        }
    }

    for source_index in source_rows {
        let source = &input.chunks[*source_index];
        let mut support = HashMap::<usize, u16>::new();
        for entity_id in source
            .entity_ids
            .iter()
            .filter(|entity_id| !frequency.is_frequency_floor(entity_id))
        {
            for target_index in target_by_entity.get(entity_id).into_iter().flatten() {
                let specificity = frequency.specificity_millis(entity_id);
                support
                    .entry(*target_index)
                    .and_modify(|current| *current = (*current).max(specificity))
                    .or_insert(specificity);
            }
        }

        let mut targets = support.into_iter().collect::<Vec<_>>();
        targets.sort_by(|(left_index, left_support), (right_index, right_support)| {
            right_support
                .cmp(left_support)
                .then_with(|| {
                    input.chunks[*left_index]
                        .ordinal
                        .cmp(&input.chunks[*right_index].ordinal)
                })
                .then_with(|| {
                    input.chunks[*left_index]
                        .id
                        .cmp(input.chunks[*right_index].id)
                })
        });

        for (target_index, _) in targets
            .into_iter()
            .take(CROSS_DOCUMENT_TARGET_SCAN_PER_CHUNK)
        {
            let target = &input.chunks[target_index];
            let shared = shared_entity_refs(source.entity_ids, target.entity_ids);
            if frequency.all_frequency_floor(&shared) {
                continue;
            }
            let Some(primary_entity) = frequency.primary(&shared) else {
                continue;
            };
            let source_event = index
                .event_by_chunk
                .get(source.id)
                .map(|row| &input.events[*row]);
            let target_event = index
                .event_by_chunk
                .get(target.id)
                .map(|row| &input.events[*row]);
            let Some(class) = classify_pair(
                input,
                index,
                source,
                target,
                source_event,
                target_event,
                shared.len(),
            ) else {
                continue;
            };
            let bridge_id = format_compact!(
                "chunk_semantic_bridge:{}:{}:{}",
                class.bridge_type.as_str(),
                slug(source.id),
                slug(target.id)
            );
            insert_bridge(
                bridges,
                input,
                Some(source),
                Some(target),
                class,
                source_event,
                target_event,
                &[],
            );
            if let Some(bridge) = bridges.get_mut(&bridge_id) {
                push_unique(
                    &mut bridge.rationale,
                    format_compact!("cross_document_budget_entity:{}", primary_entity.0),
                );
                push_unique(
                    &mut bridge.rationale,
                    format_compact!("primary_support_entity:{}", primary_entity.0),
                );
                push_unique(
                    &mut bridge.rationale,
                    format_compact!("cross_document_budget_key:entity:{}", primary_entity.0),
                );
                push_unique(
                    &mut bridge.rationale,
                    format_compact!(
                        "episode_pair:{}->{}",
                        source.episode_id.unwrap_or("none"),
                        target.episode_id.unwrap_or("none")
                    ),
                );
            }
        }

        for target_index in semantic_targets.targets_for(input, index, source) {
            let target = &input.chunks[target_index];
            let shared = shared_entity_refs(source.entity_ids, target.entity_ids);
            let support = if shared.is_empty() {
                SemanticEntitySupport::Zero
            } else if frequency.all_frequency_floor(&shared) {
                SemanticEntitySupport::FrequencyFloorOnly
            } else {
                continue;
            };
            let Some(class) = classify_semantic_pair(input, index, source, target, support) else {
                continue;
            };
            let Some(proof) = class.semantic_proof.clone() else {
                continue;
            };
            let source_event = index
                .event_by_chunk
                .get(source.id)
                .map(|row| &input.events[*row]);
            let target_event = index
                .event_by_chunk
                .get(target.id)
                .map(|row| &input.events[*row]);
            let bridge_id = format_compact!(
                "chunk_semantic_bridge:{}:{}:{}",
                class.bridge_type.as_str(),
                slug(source.id),
                slug(target.id)
            );
            insert_bridge(
                bridges,
                input,
                Some(source),
                Some(target),
                class,
                source_event,
                target_event,
                &[],
            );
            if let Some(bridge) = bridges.get_mut(&bridge_id) {
                let support_label = match support {
                    SemanticEntitySupport::Zero => "zero",
                    SemanticEntitySupport::FrequencyFloorOnly => "frequency_floor_only",
                };
                push_unique(
                    &mut bridge.rationale,
                    format_compact!("entity_support:{support_label}"),
                );
                let budget_key = match support {
                    SemanticEntitySupport::Zero => {
                        format_compact!("semantic:{}:{}", proof.kind, proof.key)
                    }
                    SemanticEntitySupport::FrequencyFloorOnly => {
                        let primary = frequency
                            .primary(&shared)
                            .expect("registry-wide support is non-empty");
                        push_unique(
                            &mut bridge.rationale,
                            format_compact!("primary_support_entity:{}", primary.0),
                        );
                        format_compact!("frequency_floor:{}:{}", primary.0, proof.kind)
                    }
                };
                push_unique(
                    &mut bridge.rationale,
                    format_compact!("cross_document_budget_key:{budget_key}"),
                );
                push_unique(
                    &mut bridge.rationale,
                    format_compact!(
                        "episode_pair:{}->{}",
                        source.episode_id.unwrap_or("none"),
                        target.episode_id.unwrap_or("none")
                    ),
                );
            }
        }
    }
}

fn note_buckets(chunks: &[ChunkSemanticBridgeChunk<'_>]) -> Vec<Vec<usize>> {
    let mut note_indexes = HashMap::<&str, usize>::new();
    let mut buckets = Vec::<Vec<usize>>::new();
    for (index, chunk) in chunks.iter().enumerate() {
        let bucket = match note_indexes.get(chunk.note_id) {
            Some(bucket) => *bucket,
            None => {
                let bucket = buckets.len();
                note_indexes.insert(chunk.note_id, bucket);
                buckets.push(Vec::new());
                bucket
            }
        };
        buckets[bucket].push(index);
    }
    for rows in &mut buckets {
        rows.sort_by_key(|index| chunks[*index].ordinal);
    }
    buckets
}

fn shared_entity_refs<'a>(left: &'a [EntityId], right: &'a [EntityId]) -> Vec<&'a EntityId> {
    let right = right.iter().collect::<HashSet<_>>();
    left.iter()
        .filter(|entity_id| right.contains(entity_id))
        .collect()
}
