use super::*;

const TARGETS_PER_PROOF_FAMILY: usize = 4;
const SEMANTIC_TARGET_LIMIT: usize = 12;

const CAUSE_SOURCE_CUES: &[&str] = &[
    "because",
    "caused",
    "forced",
    "made ",
    "led to",
    "meant ",
    "triggered",
];
const CONSEQUENCE_CUES: &[&str] = &[
    "therefore",
    "as a result",
    "resulted",
    "answered by",
    "responded",
    "consequence",
];
const MOVEMENT_CUES: &[&str] = &[
    "entered", "arrived", "walked", "crossed", "left ", "returned", "opened", "through",
];
const SPECIFIC_ROUTE_KEYS: &[&str] = &[
    "red stone",
    "red-stone",
    "transit",
    "rail",
    "district",
    "station",
    "hallway",
    "arcadia",
    "kharon",
    "rome",
    "mesa",
];
const CONTEXT_CHANGE_CUES: &[&str] = &[
    "changed",
    "shifted",
    "became",
    "turned",
    "now ",
    "no longer",
    "answered",
    "revealed",
    "learned",
    "understood",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum SemanticEntitySupport {
    Zero,
    FrequencyFloorOnly,
}

#[derive(Clone, Debug)]
pub(super) struct SemanticEvidenceProof {
    pub kind: &'static str,
    pub key: CompactString,
    pub signal_count: u8,
}

impl SemanticEvidenceProof {
    pub(super) fn explicit_causal_edge() -> Self {
        Self {
            kind: "explicit_causal_edge",
            key: "causal_event_edge".into(),
            signal_count: 2,
        }
    }
}

pub(super) struct SemanticTargetIndex {
    payoff: Vec<usize>,
    consequence: Vec<usize>,
    evidence: Vec<usize>,
    change: Vec<usize>,
    relationship: Vec<usize>,
    route: HashMap<&'static str, Vec<usize>>,
    motif: HashMap<&'static str, Vec<usize>>,
}

impl SemanticTargetIndex {
    pub(super) fn new(
        input: ChunkSemanticBridgeEngineInput<'_>,
        index: &EngineIndex<'_>,
        target_rows: &[usize],
    ) -> Self {
        let mut out = Self {
            payoff: Vec::new(),
            consequence: Vec::new(),
            evidence: Vec::new(),
            change: Vec::new(),
            relationship: Vec::new(),
            route: HashMap::new(),
            motif: HashMap::new(),
        };
        for target_index in target_rows {
            let target = &input.chunks[*target_index];
            let Some(text) = lower_text(input, index, target) else {
                continue;
            };
            if cue_hit(text, PAYOFF_CUES).is_some() {
                out.payoff.push(*target_index);
            }
            if cue_hit(text, CONSEQUENCE_CUES).is_some() {
                out.consequence.push(*target_index);
            }
            if cue_hit(text, EVIDENCE_CUES).is_some() || !target.evidence_ids.is_empty() {
                out.evidence.push(*target_index);
            }
            if cue_hit(text, CHANGE_CUES).is_some() {
                out.change.push(*target_index);
            }
            if cue_hit(text, RELATIONSHIP_DELTA_CUES).is_some() {
                out.relationship.push(*target_index);
            }
            index_keys(&mut out.route, SPECIFIC_ROUTE_KEYS, text, *target_index);
            index_keys(&mut out.motif, MOTIF_CUES, text, *target_index);
        }
        out
    }

    pub(super) fn targets_for(
        &self,
        input: ChunkSemanticBridgeEngineInput<'_>,
        index: &EngineIndex<'_>,
        source: &ChunkSemanticBridgeChunk<'_>,
    ) -> Vec<usize> {
        let Some(text) = lower_text(input, index, source) else {
            return Vec::new();
        };
        let mut scores = HashMap::<usize, u8>::new();
        if cue_hit(text, SETUP_CUES).is_some() {
            add_family(&mut scores, &self.payoff, 8);
        }
        if cue_hit(text, CAUSE_SOURCE_CUES).is_some() {
            add_family(&mut scores, &self.consequence, 8);
        }
        if !source.evidence_ids.is_empty() || cue_hit(text, EVIDENCE_CUES).is_some() {
            add_family(&mut scores, &self.evidence, 7);
        }
        if cue_hit(text, STATE_CUES).is_some() {
            add_family(&mut scores, &self.change, 5);
        }
        if cue_hit(text, RELATIONSHIP_DELTA_CUES).is_some() {
            add_family(&mut scores, &self.relationship, 5);
        }
        add_keyed_families(&mut scores, &self.route, SPECIFIC_ROUTE_KEYS, text, 6);
        add_keyed_families(&mut scores, &self.motif, MOTIF_CUES, text, 4);

        let mut targets = scores.into_iter().collect::<Vec<_>>();
        targets.sort_by(|(left_index, left_score), (right_index, right_score)| {
            right_score
                .cmp(left_score)
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
        targets
            .into_iter()
            .take(SEMANTIC_TARGET_LIMIT)
            .map(|(target_index, _)| target_index)
            .collect()
    }
}

pub(super) fn classify_semantic_pair<'a>(
    input: ChunkSemanticBridgeEngineInput<'a>,
    index: &'a EngineIndex<'a>,
    source: &'a ChunkSemanticBridgeChunk<'a>,
    target: &'a ChunkSemanticBridgeChunk<'a>,
    support: SemanticEntitySupport,
) -> Option<BridgeClass<'a>> {
    let left = lower_text(input, index, source)?;
    let right = lower_text(input, index, target)?;

    if let (Some(source_cue), Some(target_cue)) =
        (cue_hit(left, SETUP_CUES), cue_hit(right, PAYOFF_CUES))
    {
        return Some(proven_class(
            ChunkSemanticBridgeType::SetupPayoff,
            &["sets_up", "pays_off", "answers"],
            source_cue,
            target_cue,
            support_confidence(support, 0.74),
            "setup_cue_plus_later_payoff_cue",
            "directional_setup_payoff",
            format_compact!("{source_cue}->{target_cue}"),
            2,
        ));
    }
    if let (Some(source_cue), Some(target_cue)) = (
        cue_hit(left, CAUSE_SOURCE_CUES),
        cue_hit(right, CONSEQUENCE_CUES),
    ) {
        return Some(proven_class(
            ChunkSemanticBridgeType::CauseEffect,
            &["causes", "explains", "answers"],
            source_cue,
            target_cue,
            support_confidence(support, 0.72),
            "causal_language_spans_chunks",
            "directional_cause_effect",
            format_compact!("{source_cue}->{target_cue}"),
            2,
        ));
    }
    if let (Some(lineage), Some(target_cue)) = (
        shared_evidence_lineage(index, source.evidence_ids, target.evidence_ids),
        cue_hit(right, EVIDENCE_CUES),
    ) {
        return Some(proven_class(
            ChunkSemanticBridgeType::EvidenceReframe,
            &["reframes", "documents", "explains"],
            lineage,
            target_cue,
            support_confidence(support, 0.70),
            "evidence_or_documentation_reframes_prior_chunk",
            "shared_evidence_lineage",
            lineage.into(),
            2,
        ));
    }
    if support == SemanticEntitySupport::FrequencyFloorOnly {
        if let (Some(source_cue), Some(target_cue)) = (
            cue_hit(left, RELATIONSHIP_DELTA_CUES),
            cue_hit(right, RELATIONSHIP_DELTA_CUES),
        ) {
            if source.entity_ids.len() >= 2 && target.entity_ids.len() >= 2 {
                return Some(proven_class(
                    ChunkSemanticBridgeType::RelationshipDelta,
                    &["shifts", "pressures", "realigns"],
                    source_cue,
                    target_cue,
                    support_confidence(support, 0.68),
                    "relationship_cue_with_shared_participants",
                    "typed_relationship_partner_shift",
                    format_compact!("{source_cue}->{target_cue}"),
                    3,
                ));
            }
        }
    }
    if let (Some(route_key), Some(source_cue), Some(target_cue)) = (
        shared_key(left, right, SPECIFIC_ROUTE_KEYS),
        cue_hit(left, MOVEMENT_CUES),
        cue_hit(right, MOVEMENT_CUES),
    ) {
        return Some(proven_class(
            ChunkSemanticBridgeType::RouteContinuity,
            &["continues", "crosses", "moves"],
            source_cue,
            target_cue,
            support_confidence(support, 0.68),
            "route_or_threshold_cue_spans_chunks",
            "specific_route_continuity",
            route_key.into(),
            3,
        ));
    }
    if support == SemanticEntitySupport::FrequencyFloorOnly {
        if let (Some(source_cue), Some(target_cue)) =
            (cue_hit(left, STATE_CUES), cue_hit(right, CHANGE_CUES))
        {
            return Some(proven_class(
                ChunkSemanticBridgeType::StateDelta,
                &["changes", "updates", "reverses"],
                source_cue,
                target_cue,
                support_confidence(support, 0.67),
                "later_chunk_changes_prior_state",
                "typed_state_change",
                format_compact!("{source_cue}->{target_cue}"),
                2,
            ));
        }
    }
    if let (Some(motif), Some(target_cue)) = (
        shared_key(left, right, MOTIF_CUES),
        cue_hit(right, CONTEXT_CHANGE_CUES),
    ) {
        return Some(proven_class(
            ChunkSemanticBridgeType::MotifEcho,
            &["echoes", "recurs", "recontextualizes"],
            motif,
            target_cue,
            support_confidence(support, 0.64),
            format_compact!("motif:{motif}"),
            "motif_context_shift",
            motif.into(),
            2,
        ));
    }
    None
}

fn proven_class<'a>(
    bridge_type: ChunkSemanticBridgeType,
    semantic_verbs: &'static [&'static str],
    source_cue: &'a str,
    target_cue: &'a str,
    confidence: f32,
    rationale: impl Into<CompactString>,
    proof_kind: &'static str,
    proof_key: CompactString,
    signal_count: u8,
) -> BridgeClass<'a> {
    BridgeClass {
        bridge_type,
        semantic_verbs,
        source_cue: Some(source_cue),
        target_cue: Some(target_cue),
        confidence,
        rationale: rationale.into(),
        semantic_proof: Some(SemanticEvidenceProof {
            kind: proof_kind,
            key: proof_key,
            signal_count,
        }),
    }
}

fn support_confidence(support: SemanticEntitySupport, confidence: f32) -> f32 {
    match support {
        SemanticEntitySupport::Zero => confidence.min(0.74),
        SemanticEntitySupport::FrequencyFloorOnly => (confidence - 0.06).min(0.78),
    }
}

fn shared_evidence_lineage<'a>(
    index: &'a EngineIndex<'a>,
    left: &[CompactString],
    right: &[CompactString],
) -> Option<&'a str> {
    let mut lineages = HashSet::<&str>::new();
    for evidence_id in left {
        if let Some(source_id) = index.evidence_source_by_id.get(evidence_id.as_str()) {
            lineages.insert(*source_id);
        }
    }
    right.iter().find_map(|evidence_id| {
        index
            .evidence_source_by_id
            .get(evidence_id.as_str())
            .copied()
            .filter(|source_id| lineages.contains(source_id))
    })
}

fn index_keys(
    index: &mut HashMap<&'static str, Vec<usize>>,
    keys: &'static [&'static str],
    text: &str,
    row: usize,
) {
    for key in keys.iter().copied().filter(|key| contains(text, key)) {
        index.entry(key).or_default().push(row);
    }
}

fn add_keyed_families(
    scores: &mut HashMap<usize, u8>,
    index: &HashMap<&'static str, Vec<usize>>,
    keys: &'static [&'static str],
    text: &str,
    score: u8,
) {
    for key in keys.iter().copied().filter(|key| contains(text, key)) {
        if let Some(rows) = index.get(key) {
            add_family(scores, rows, score);
        }
    }
}

fn add_family(scores: &mut HashMap<usize, u8>, rows: &[usize], score: u8) {
    for row in rows.iter().take(TARGETS_PER_PROOF_FAMILY) {
        scores
            .entry(*row)
            .and_modify(|current| *current = (*current).max(score))
            .or_insert(score);
    }
}

fn shared_key<'a>(left: &'a str, right: &str, keys: &[&'static str]) -> Option<&'a str> {
    for key in keys.iter().copied() {
        if !contains(right, key) {
            continue;
        }
        if let Some(start) = left.find(key) {
            return Some(&left[start..start + key.len()]);
        }
    }
    None
}

fn contains(text: &str, needle: &str) -> bool {
    memchr::memmem::find(text.as_bytes(), needle.as_bytes()).is_some()
}

#[cfg(test)]
mod tests {
    use super::super::*;

    #[test]
    fn admits_zero_entity_directional_setup_payoff_with_specific_proof() {
        let chunks = vec![
            chunk(
                "early:chunk:0",
                "early",
                0,
                "The sealed warning was needed before departure.",
                &[],
            ),
            chunk(
                "late:chunk:0",
                "late",
                0,
                "At dawn the gate answered and opened.",
                &[],
            ),
        ];

        let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
            chunks: &chunks,
            ..ChunkSemanticBridgeEngineInput::default()
        });

        assert_eq!(candidates.len(), 1);
        let bridge = &candidates[0];
        assert_eq!(bridge.bridge_type, ChunkSemanticBridgeType::SetupPayoff);
        assert!(bridge.supporting_entity_ids.is_empty());
        assert!(has_marker(bridge, "entity_support:zero"));
        assert!(has_marker(
            bridge,
            "semantic_proof:directional_setup_payoff"
        ));
        assert!(has_marker(bridge, "semantic_proof_count:2"));
        assert!(bridge.confidence <= 0.74);
        assert_chunk_semantic_bridge_candidate_only(&candidates).expect("zero entity candidate");
    }

    #[test]
    fn rejects_zero_entity_generic_lexical_overlap() {
        let chunks = vec![
            chunk(
                "early:chunk:0",
                "early",
                0,
                "They walked through the door before lunch.",
                &[],
            ),
            chunk(
                "late:chunk:0",
                "late",
                0,
                "They walked through another door after lunch.",
                &[],
            ),
        ];

        let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
            chunks: &chunks,
            ..ChunkSemanticBridgeEngineInput::default()
        });

        assert!(candidates.is_empty());
    }

    #[test]
    fn rejects_registry_wide_repetition_without_semantic_proof() {
        let ryan = EntityId("character:ryan".to_owned());
        let entities = vec![ryan];
        let chunks = registry_wide_chunks(
            &entities,
            "Ryan stood quietly in the room.",
            "Ryan remained quiet in the room.",
        );

        let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
            chunks: &chunks,
            ..ChunkSemanticBridgeEngineInput::default()
        });

        assert!(candidates.is_empty());
    }

    #[test]
    fn admits_and_bounds_registry_wide_rows_with_directional_semantic_proof() {
        let ryan = EntityId("character:ryan".to_owned());
        let entities = vec![ryan];
        let chunks = registry_wide_chunks(
            &entities,
            "Ryan warned that the sealed question had to be remembered.",
            "Ryan answered the warning and opened the gate.",
        );

        let candidates = build_chunk_semantic_bridge_candidates(ChunkSemanticBridgeEngineInput {
            chunks: &chunks,
            ..ChunkSemanticBridgeEngineInput::default()
        });
        let frequency_floor = candidates
            .iter()
            .filter(|bridge| has_marker(bridge, "entity_support:frequency_floor_only"))
            .collect::<Vec<_>>();

        assert!(!frequency_floor.is_empty());
        assert!(frequency_floor.len() <= 6);
        assert!(frequency_floor.iter().all(|bridge| {
            has_marker(bridge, "semantic_admission:passed")
                && bridge.confidence <= 0.78
                && bridge
                    .rationale
                    .iter()
                    .any(|row| row.starts_with("cross_document_budget_key:frequency_floor:"))
        }));
        assert_chunk_semantic_bridge_candidate_only(&candidates).expect("registry-wide candidates");
    }

    #[test]
    fn quality_gate_rejects_weak_support_rows_without_complete_proof() {
        let bridge = ChunkSemanticBridgeCandidate {
            schema_version: CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION.into(),
            id: "bridge:malformed-zero".into(),
            bridge_type: ChunkSemanticBridgeType::MotifEcho,
            source_chunk_id: "a:chunk:0".into(),
            target_chunk_id: "b:chunk:0".into(),
            source_event_id: None,
            target_event_id: None,
            source_episode_id: None,
            target_episode_id: None,
            claim: "generic echo".into(),
            evidence_ids: vec!["a:chunk:0".into(), "b:chunk:0".into()],
            supporting_entity_ids: Vec::new(),
            confidence: 0.70,
            status: ChunkSemanticBridgeStatus::Candidate,
            commit_policy: ChunkSemanticBridgeCommitPolicy::NoTopologyCommit,
            semantic_verbs: vec!["echoes".into()],
            source_cue: Some("door".into()),
            target_cue: Some("door".into()),
            rationale: vec![
                CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT.into(),
                "entity_support:zero".into(),
            ],
        };

        assert_eq!(
            bridge_quality_gate_decision(&bridge),
            BridgeQualityGateDecision::DemoteInsufficientSemanticEvidence
        );
    }

    fn registry_wide_chunks<'a>(
        entities: &'a [EntityId],
        source_text: &'a str,
        target_text: &'a str,
    ) -> Vec<ChunkSemanticBridgeChunk<'a>> {
        let mut chunks = Vec::new();
        for ordinal in 0..3 {
            chunks.push(chunk(
                match ordinal {
                    0 => "a:chunk:0",
                    1 => "a:chunk:1",
                    _ => "a:chunk:2",
                },
                "a",
                ordinal,
                source_text,
                entities,
            ));
            chunks.push(chunk(
                match ordinal {
                    0 => "b:chunk:0",
                    1 => "b:chunk:1",
                    _ => "b:chunk:2",
                },
                "b",
                ordinal,
                target_text,
                entities,
            ));
            chunks.push(chunk(
                match ordinal {
                    0 => "c:chunk:0",
                    1 => "c:chunk:1",
                    _ => "c:chunk:2",
                },
                "c",
                ordinal,
                "Ryan watched the ordinary street in silence.",
                entities,
            ));
        }
        chunks
    }

    fn chunk<'a>(
        id: &'a str,
        note_id: &'a str,
        ordinal: u32,
        text: &'a str,
        entity_ids: &'a [EntityId],
    ) -> ChunkSemanticBridgeChunk<'a> {
        ChunkSemanticBridgeChunk {
            id,
            note_id,
            ordinal,
            text,
            role: None,
            episode_id: None,
            entity_ids,
            evidence_ids: &[],
        }
    }

    fn has_marker(bridge: &ChunkSemanticBridgeCandidate, marker: &str) -> bool {
        bridge.rationale.iter().any(|row| row == marker)
    }
}
