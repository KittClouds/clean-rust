use super::*;

pub(super) const CROSS_DOCUMENT_PAIR_QUOTA: usize = 24;
pub(super) const CROSS_DOCUMENT_TYPE_PAIR_QUOTA: usize = 3;
pub(super) const CROSS_DOCUMENT_EPISODE_PAIR_QUOTA: usize = 4;
pub(super) const CROSS_DOCUMENT_ZERO_ENTITY_PAIR_QUOTA: usize = 3;
pub(super) const CROSS_DOCUMENT_FREQUENCY_FLOOR_PAIR_QUOTA: usize = 4;
pub(super) const CROSS_DOCUMENT_WEAK_SUPPORT_PAIR_QUOTA: usize = 6;

const BRIDGE_TYPES: [ChunkSemanticBridgeType; 8] = [
    ChunkSemanticBridgeType::SetupPayoff,
    ChunkSemanticBridgeType::CauseEffect,
    ChunkSemanticBridgeType::EvidenceReframe,
    ChunkSemanticBridgeType::RelationshipDelta,
    ChunkSemanticBridgeType::StateDelta,
    ChunkSemanticBridgeType::RouteContinuity,
    ChunkSemanticBridgeType::MotifEcho,
    ChunkSemanticBridgeType::TopicContinuation,
];

#[derive(Default)]
struct WeakSupportCounts {
    zero: usize,
    frequency_floor: usize,
}

#[derive(Default)]
struct PairSelectionState {
    selected: HashSet<CompactString>,
    episode_counts: HashMap<CompactString, usize>,
    type_counts: HashMap<ChunkSemanticBridgeType, usize>,
    weak_support: WeakSupportCounts,
}

struct PairPool<'a> {
    by_sponsor: HashMap<CompactString, Vec<&'a ChunkSemanticBridgeCandidate>>,
    by_type_and_sponsor: HashMap<
        ChunkSemanticBridgeType,
        HashMap<CompactString, Vec<&'a ChunkSemanticBridgeCandidate>>,
    >,
    state: PairSelectionState,
}

pub(super) fn select_bridge_rows_fair(
    bridges: Vec<ChunkSemanticBridgeCandidate>,
) -> Vec<ChunkSemanticBridgeCandidate> {
    if !bridges.iter().any(is_cross_document) {
        return select_bridge_rows(bridges);
    }

    let baseline = select_bridge_rows(
        bridges
            .iter()
            .filter(|bridge| !is_cross_document(bridge))
            .cloned()
            .collect(),
    );
    let mut pair_keys = bridges
        .iter()
        .filter_map(document_pair)
        .collect::<HashSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    pair_keys.sort();
    let mut pools = pair_keys
        .iter()
        .map(|pair_key| {
            let mut rows = bridges
                .iter()
                .filter(|bridge| document_pair(bridge).as_ref() == Some(pair_key))
                .collect::<Vec<_>>();
            rows.sort_by(compare_cross_document_rows);
            let mut pool = PairPool {
                by_sponsor: HashMap::new(),
                by_type_and_sponsor: HashMap::new(),
                state: PairSelectionState::default(),
            };
            for bridge in rows {
                let key = selection_key(bridge).expect("cross-document row has support key");
                pool.by_sponsor.entry(key.clone()).or_default().push(bridge);
                pool.by_type_and_sponsor
                    .entry(bridge.bridge_type)
                    .or_default()
                    .entry(key)
                    .or_default()
                    .push(bridge);
            }
            pool
        })
        .collect::<Vec<_>>();

    let mut selected = HashMap::<CompactString, ChunkSemanticBridgeCandidate>::new();
    let mut sponsor_exposure = HashMap::<CompactString, usize>::new();
    let mut selection_round = 0usize;

    for bridge_type in BRIDGE_TYPES {
        loop {
            let mut progressed = false;
            for pool in &mut pools {
                if selected.len() >= BRIDGE_LIMIT
                    || pool.state.selected.len() >= CROSS_DOCUMENT_PAIR_QUOTA
                    || pool
                        .state
                        .type_counts
                        .get(&bridge_type)
                        .copied()
                        .unwrap_or_default()
                        >= CROSS_DOCUMENT_TYPE_PAIR_QUOTA
                {
                    continue;
                }
                let Some(bridge) = best_eligible_row(
                    &pool.by_sponsor,
                    pool.by_type_and_sponsor.get(&bridge_type),
                    &pool.state,
                    &sponsor_exposure,
                ) else {
                    continue;
                };
                take_cross_document_row(
                    bridge,
                    &mut selected,
                    &mut pool.state,
                    &mut sponsor_exposure,
                    &mut selection_round,
                );
                progressed = true;
            }
            if !progressed || selected.len() >= BRIDGE_LIMIT {
                break;
            }
        }
    }

    loop {
        let mut progressed = false;
        for pool in &mut pools {
            if selected.len() >= BRIDGE_LIMIT
                || pool.state.selected.len() >= CROSS_DOCUMENT_PAIR_QUOTA
            {
                continue;
            }
            let Some(bridge) =
                best_eligible_row(&pool.by_sponsor, None, &pool.state, &sponsor_exposure)
            else {
                continue;
            };
            take_cross_document_row(
                bridge,
                &mut selected,
                &mut pool.state,
                &mut sponsor_exposure,
                &mut selection_round,
            );
            progressed = true;
        }
        if !progressed || selected.len() >= BRIDGE_LIMIT {
            break;
        }
    }
    drop(pools);

    for bridge in baseline {
        if selected.len() >= BRIDGE_LIMIT {
            break;
        }
        selected.entry(bridge.id.clone()).or_insert(bridge);
    }
    if selected.len() < BRIDGE_LIMIT {
        let mut remainder = bridges;
        remainder.sort_by(compare_bridge_rows);
        for bridge in remainder
            .into_iter()
            .filter(|bridge| !is_cross_document(bridge))
        {
            if selected.len() >= BRIDGE_LIMIT {
                break;
            }
            selected.entry(bridge.id.clone()).or_insert(bridge);
        }
    }

    let mut out = selected.into_values().collect::<Vec<_>>();
    out.sort_by(compare_bridge_rows);
    out
}

fn best_eligible_row<'a>(
    all_groups: &'a HashMap<CompactString, Vec<&'a ChunkSemanticBridgeCandidate>>,
    typed_groups: Option<&'a HashMap<CompactString, Vec<&'a ChunkSemanticBridgeCandidate>>>,
    state: &PairSelectionState,
    sponsor_exposure: &HashMap<CompactString, usize>,
) -> Option<&'a ChunkSemanticBridgeCandidate> {
    let groups = typed_groups.unwrap_or(all_groups);
    groups
        .iter()
        .filter_map(|(sponsor, rows)| {
            rows.iter()
                .copied()
                .find(|bridge| row_is_eligible(bridge, state))
                .map(|bridge| (sponsor, bridge))
        })
        .min_by(|(left_sponsor, left), (right_sponsor, right)| {
            sponsor_exposure
                .get(*left_sponsor)
                .copied()
                .unwrap_or_default()
                .cmp(
                    &sponsor_exposure
                        .get(*right_sponsor)
                        .copied()
                        .unwrap_or_default(),
                )
                .then_with(|| compare_cross_document_rows(left, right))
                .then_with(|| left_sponsor.cmp(right_sponsor))
        })
        .map(|(_, bridge)| bridge)
}

fn row_is_eligible(bridge: &ChunkSemanticBridgeCandidate, state: &PairSelectionState) -> bool {
    if state.selected.contains(&bridge.id) {
        return false;
    }
    if episode_pair(bridge)
        .as_ref()
        .and_then(|key| state.episode_counts.get(key))
        .copied()
        .unwrap_or_default()
        >= CROSS_DOCUMENT_EPISODE_PAIR_QUOTA
    {
        return false;
    }
    let zero_entity = has_rationale(bridge, "entity_support:zero");
    let frequency_floor = has_rationale(bridge, "entity_support:frequency_floor_only");
    if zero_entity && state.weak_support.zero >= CROSS_DOCUMENT_ZERO_ENTITY_PAIR_QUOTA {
        return false;
    }
    if frequency_floor
        && state.weak_support.frequency_floor >= CROSS_DOCUMENT_FREQUENCY_FLOOR_PAIR_QUOTA
    {
        return false;
    }
    if (zero_entity || frequency_floor)
        && state.weak_support.zero + state.weak_support.frequency_floor
            >= CROSS_DOCUMENT_WEAK_SUPPORT_PAIR_QUOTA
    {
        return false;
    }
    selection_key(bridge).is_some()
}

fn take_cross_document_row(
    bridge: &ChunkSemanticBridgeCandidate,
    selected: &mut HashMap<CompactString, ChunkSemanticBridgeCandidate>,
    state: &mut PairSelectionState,
    sponsor_exposure: &mut HashMap<CompactString, usize>,
    selection_round: &mut usize,
) {
    let key = selection_key(bridge).expect("eligible row has a support key");
    let exposure_before = sponsor_exposure.get(&key).copied().unwrap_or_default();
    let mut selected_bridge = bridge.clone();
    push_unique(
        &mut selected_bridge.rationale,
        "registry_max_min_selection:passed".into(),
    );
    push_unique(
        &mut selected_bridge.rationale,
        format_compact!("registry_support_exposure_before:{exposure_before}"),
    );
    push_unique(
        &mut selected_bridge.rationale,
        format_compact!("registry_support_exposure_after:{}", exposure_before + 1),
    );
    push_unique(
        &mut selected_bridge.rationale,
        format_compact!("registry_fair_selection_round:{}", *selection_round),
    );

    state.selected.insert(bridge.id.clone());
    if let Some(key) = episode_pair(bridge) {
        *state.episode_counts.entry(key).or_default() += 1;
    }
    *state.type_counts.entry(bridge.bridge_type).or_default() += 1;
    state.weak_support.zero += usize::from(has_rationale(bridge, "entity_support:zero"));
    state.weak_support.frequency_floor +=
        usize::from(has_rationale(bridge, "entity_support:frequency_floor_only"));
    sponsor_exposure.insert(key, exposure_before + 1);
    selected.insert(bridge.id.clone(), selected_bridge);
    *selection_round += 1;
}

fn selection_key(bridge: &ChunkSemanticBridgeCandidate) -> Option<CompactString> {
    bridge
        .rationale
        .iter()
        .find_map(|row| row.strip_prefix("primary_support_entity:"))
        .map(|entity_id| format_compact!("entity:{entity_id}"))
        .or_else(|| budget_key(bridge))
}

fn select_bridge_rows(
    mut bridges: Vec<ChunkSemanticBridgeCandidate>,
) -> Vec<ChunkSemanticBridgeCandidate> {
    bridges.sort_by(compare_bridge_rows);
    let mut selected = HashMap::<CompactString, ChunkSemanticBridgeCandidate>::new();
    for bridge_type in BRIDGE_TYPES {
        for row in bridges
            .iter()
            .filter(|bridge| bridge.bridge_type == bridge_type)
            .take(BRIDGE_TYPE_QUOTA)
        {
            selected.insert(row.id.clone(), row.clone());
        }
    }
    for row in bridges {
        if selected.len() >= BRIDGE_LIMIT {
            break;
        }
        selected.insert(row.id.clone(), row);
    }
    let mut out = selected.into_values().collect::<Vec<_>>();
    out.sort_by(compare_bridge_rows);
    out.truncate(BRIDGE_LIMIT);
    out
}

fn compare_bridge_rows(
    left: &ChunkSemanticBridgeCandidate,
    right: &ChunkSemanticBridgeCandidate,
) -> std::cmp::Ordering {
    bridge_rank(left.bridge_type)
        .cmp(&bridge_rank(right.bridge_type))
        .then_with(|| right.confidence.total_cmp(&left.confidence))
        .then_with(|| left.source_chunk_id.cmp(&right.source_chunk_id))
        .then_with(|| left.target_chunk_id.cmp(&right.target_chunk_id))
}

fn compare_cross_document_rows(
    left: &&ChunkSemanticBridgeCandidate,
    right: &&ChunkSemanticBridgeCandidate,
) -> std::cmp::Ordering {
    right
        .confidence
        .total_cmp(&left.confidence)
        .then_with(|| bridge_rank(left.bridge_type).cmp(&bridge_rank(right.bridge_type)))
        .then_with(|| left.source_chunk_id.cmp(&right.source_chunk_id))
        .then_with(|| left.target_chunk_id.cmp(&right.target_chunk_id))
}

fn bridge_rank(bridge_type: ChunkSemanticBridgeType) -> u8 {
    BRIDGE_TYPES
        .iter()
        .position(|candidate| *candidate == bridge_type)
        .unwrap_or(BRIDGE_TYPES.len()) as u8
}

fn is_cross_document(bridge: &ChunkSemanticBridgeCandidate) -> bool {
    document_pair(bridge).is_some()
}

fn document_pair(bridge: &ChunkSemanticBridgeCandidate) -> Option<CompactString> {
    bridge.rationale.iter().find_map(|row| {
        row.strip_prefix("document_pair:")
            .filter(|pair| {
                pair.split_once("->")
                    .is_some_and(|(source, target)| source != target)
            })
            .map(CompactString::from)
    })
}

fn episode_pair(bridge: &ChunkSemanticBridgeCandidate) -> Option<CompactString> {
    Some(format_compact!(
        "{}->{}",
        bridge.source_episode_id.as_deref()?,
        bridge.target_episode_id.as_deref()?
    ))
}

fn budget_key(bridge: &ChunkSemanticBridgeCandidate) -> Option<CompactString> {
    bridge.rationale.iter().find_map(|row| {
        row.strip_prefix("cross_document_budget_key:")
            .or_else(|| row.strip_prefix("cross_document_budget_entity:"))
            .map(CompactString::from)
    })
}

fn has_rationale(bridge: &ChunkSemanticBridgeCandidate, value: &str) -> bool {
    bridge.rationale.iter().any(|row| row == value)
}
