use std::{collections::BTreeMap, time::Instant};

use compact_str::{format_compact, CompactString};
use phoenix_types::{EntityId, EntityKind, LexiconEntry, ScopeKey};
use serde::{Deserialize, Serialize};

use crate::memory_governance::{
    assert_memory_governance_candidate_only, build_memory_governance_candidates,
    build_memory_governance_retrieval_preview, MemoryGovernanceEngineInput,
    MemoryGovernanceRetrievalCandidate, MemoryGovernanceRetrievalPreviewInput,
    MEMORY_GOVERNANCE_COMMIT_POLICY, MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT,
    MEMORY_GOVERNANCE_PIN_SOURCE_RATIONALE, MEMORY_GOVERNANCE_SCHEMA_VERSION,
};
use crate::types::{
    GraphAnchor, GraphChunk, GraphEpisode, GraphEvent, GraphMemoryGovernanceAction,
    GraphMemoryGovernanceCandidate, GraphMemoryGovernanceCommitPolicy, GraphMemoryGovernanceStatus,
    GraphMemoryGovernanceTargetKind, GraphMemoryState, GraphRelationship, GraphTemporalEdge,
};
use crate::{build_graph_rebuild_snapshot, GraphRebuildInput, GraphScopeKind};

pub const MEMORY_GOVERNANCE_ADVERSARIAL_CERTIFICATE_SCHEMA_VERSION: &str =
    "phoenix-memory-governance-adversarial-certificate/v1";

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceAdversarialCertificate {
    pub schema_version: CompactString,
    pub fixture_count: usize,
    pub passed_fixtures: usize,
    pub failed_fixtures: usize,
    pub total_candidate_rows: usize,
    pub total_negative_relation_rows: usize,
    pub no_topology_violations: usize,
    pub action_counts: BTreeMap<CompactString, usize>,
    pub attention_lanes: BTreeMap<CompactString, usize>,
    pub timing: MemoryGovernanceAdversarialTiming,
    pub fixtures: Vec<MemoryGovernanceAdversarialFixtureResult>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceAdversarialTiming {
    pub total_micros: u128,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceAdversarialFixtureResult {
    pub id: CompactString,
    pub title: CompactString,
    pub threat_lane: CompactString,
    pub expected_action: CompactString,
    pub expected_target_id: CompactString,
    pub passed: bool,
    pub candidates_by_action: BTreeMap<CompactString, usize>,
    pub no_topology_proof: MemoryGovernanceAdversarialNoTopologyProof,
    pub top_rows: Vec<MemoryGovernanceAdversarialCandidateRow>,
    pub weakest_rows: Vec<MemoryGovernanceAdversarialCandidateRow>,
    pub retrieval_rows: Vec<MemoryGovernanceAdversarialRetrievalRow>,
    pub negative_relation_rows: Vec<MemoryGovernanceAdversarialNegativeRelationRow>,
    pub checks: Vec<MemoryGovernanceAdversarialCheck>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceAdversarialNoTopologyProof {
    pub passed: bool,
    pub candidate_rows: usize,
    pub candidate_only_rows: usize,
    pub no_topology_commit_rows: usize,
    pub commit_policy_rows: usize,
    pub missing_no_topology_rationale_rows: usize,
    pub violations: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceAdversarialCandidateRow {
    pub id: CompactString,
    pub target_id: CompactString,
    pub target_kind: CompactString,
    pub action: CompactString,
    pub reason: CompactString,
    pub confidence_millis: u16,
    pub evidence_count: usize,
    pub no_topology_commit: bool,
    pub rationale: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceAdversarialRetrievalRow {
    pub target_id: CompactString,
    pub target_kind: CompactString,
    pub original_rank: usize,
    pub adjusted_rank: usize,
    pub score_delta_millis: i16,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceAdversarialNegativeRelationRow {
    pub relation_type: CompactString,
    pub source_entity_id: CompactString,
    pub target_entity_id: CompactString,
    pub status: CompactString,
    pub adjudication_source: CompactString,
    pub confidence_millis: u16,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceAdversarialCheck {
    pub name: CompactString,
    pub passed: bool,
    pub detail: CompactString,
}

pub fn build_memory_governance_adversarial_certificate() -> MemoryGovernanceAdversarialCertificate {
    let started = Instant::now();
    let fixtures = vec![
        contradiction_fixture(),
        supersession_fixture(),
        pinned_fixture(),
        celebrity_fixture(),
        weak_evidence_fixture(),
        compression_fixture(),
        negative_relation_fixture(),
    ];
    let mut action_counts = BTreeMap::new();
    let mut attention_lanes = BTreeMap::new();
    let mut total_candidate_rows = 0;
    let mut total_negative_relation_rows = 0;
    let mut no_topology_violations = 0;
    for fixture in &fixtures {
        total_candidate_rows += fixture.no_topology_proof.candidate_rows;
        total_negative_relation_rows += fixture.negative_relation_rows.len();
        no_topology_violations += fixture.no_topology_proof.violations.len();
        *attention_lanes
            .entry(fixture.threat_lane.clone())
            .or_insert(0) += 1;
        for (action, count) in &fixture.candidates_by_action {
            *action_counts.entry(action.clone()).or_insert(0) += count;
        }
    }
    let passed_fixtures = fixtures.iter().filter(|row| row.passed).count();

    MemoryGovernanceAdversarialCertificate {
        schema_version: MEMORY_GOVERNANCE_ADVERSARIAL_CERTIFICATE_SCHEMA_VERSION.into(),
        fixture_count: fixtures.len(),
        passed_fixtures,
        failed_fixtures: fixtures.len() - passed_fixtures,
        total_candidate_rows,
        total_negative_relation_rows,
        no_topology_violations,
        action_counts,
        attention_lanes,
        timing: MemoryGovernanceAdversarialTiming {
            total_micros: started.elapsed().as_micros(),
        },
        fixtures,
    }
}

fn contradiction_fixture() -> MemoryGovernanceAdversarialFixtureResult {
    let kai = entity("kai");
    let mut fixture = GovernanceFixture::new(vec![chunk("chunk:contradiction", 0)]);
    fixture.anchors = vec![
        anchor("anchor:kai:approved", &kai, "chunk:contradiction"),
        anchor("anchor:kai:rejected", &kai, "chunk:contradiction"),
    ];
    fixture.memory_state = vec![
        state(
            "memory:approved",
            &kai,
            "decision_state",
            "approved",
            "anchor:kai:approved",
        ),
        state(
            "memory:rejected",
            &kai,
            "decision_state",
            "rejected",
            "anchor:kai:rejected",
        ),
    ];
    candidate_fixture(
        "contradiction",
        "Contradiction quarantine",
        "contradiction",
        "chunk:contradiction",
        GraphMemoryGovernanceAction::Quarantine,
        "target_has_contradictory_memory_evidence",
        &["audit:state_conflict"],
        build_memory_governance_candidates(fixture.input()),
    )
}

fn supersession_fixture() -> MemoryGovernanceAdversarialFixtureResult {
    let kai = entity("kai");
    let mut fixture = GovernanceFixture::new(vec![chunk("chunk:old", 0), chunk("chunk:new", 1)]);
    fixture.anchors = vec![
        anchor("anchor:kai:old", &kai, "chunk:old"),
        anchor("anchor:kai:new", &kai, "chunk:new"),
    ];
    fixture.memory_state = vec![
        state(
            "memory:old",
            &kai,
            "decision_state",
            "approved",
            "anchor:kai:old",
        ),
        state(
            "memory:new",
            &kai,
            "decision_state",
            "rejected",
            "anchor:kai:new",
        ),
    ];
    let rows = build_memory_governance_candidates(fixture.input());
    let mut result = candidate_fixture(
        "supersession",
        "Supersession attenuation",
        "supersession",
        "chunk:old",
        GraphMemoryGovernanceAction::Attenuate,
        "target_superseded_by_later_memory_evidence",
        &["audit:state_supersession"],
        rows,
    );
    let newer_not_attenuated = result
        .top_rows
        .iter()
        .chain(&result.weakest_rows)
        .all(|row| {
            row.target_id != "chunk:new"
                || row.action != GraphMemoryGovernanceAction::Attenuate.as_str()
        });
    result.checks.push(check(
        "newer_target_not_attenuated",
        newer_not_attenuated,
        "newer chunk remains current",
    ));
    result.passed = result.checks.iter().all(|row| row.passed);
    result
}

fn pinned_fixture() -> MemoryGovernanceAdversarialFixtureResult {
    let kai = entity("kai");
    let mut fixture = GovernanceFixture::new(vec![chunk("chunk:pinned", 0)]);
    fixture.anchors = vec![
        anchor("anchor:kai:pin", &kai, "chunk:pinned"),
        anchor("anchor:kai:approved", &kai, "chunk:pinned"),
        anchor("anchor:kai:rejected", &kai, "chunk:pinned"),
    ];
    fixture.memory_state = vec![
        state_with_evidence(
            "memory:pin",
            &kai,
            "user_pinned",
            "true",
            &["anchor:kai:pin", "user_override:pin:kai"],
        ),
        state(
            "memory:approved",
            &kai,
            "decision_state",
            "approved",
            "anchor:kai:approved",
        ),
        state(
            "memory:rejected",
            &kai,
            "decision_state",
            "rejected",
            "anchor:kai:rejected",
        ),
    ];
    candidate_fixture(
        "pinned-memory",
        "Pinned memory protection",
        "pinned_memory",
        "chunk:pinned",
        GraphMemoryGovernanceAction::Retain,
        "target_user_pinned_memory",
        &["audit:user_pinned", MEMORY_GOVERNANCE_PIN_SOURCE_RATIONALE],
        build_memory_governance_candidates(fixture.input()),
    )
}

fn celebrity_fixture() -> MemoryGovernanceAdversarialFixtureResult {
    let kai = entity("kai");
    let rift = entity("rift");
    let mut fixture = GovernanceFixture::new(
        (0..5)
            .map(|index| chunk(&format!("chunk:{index}"), index))
            .collect(),
    );
    for index in 0..5 {
        fixture.anchors.push(anchor(
            &format!("anchor:kai:{index}"),
            &kai,
            &format!("chunk:{index}"),
        ));
        fixture.anchors.push(anchor(
            &format!("anchor:rift:{index}"),
            &rift,
            &format!("chunk:{index}"),
        ));
    }
    candidate_fixture(
        "celebrity-dominance",
        "Celebrity entity dominance",
        "celebrity_dominance",
        "chunk:3",
        GraphMemoryGovernanceAction::Quarantine,
        "chunk_entity_salience_dominated_by_celebrity_surface",
        &["audit:celebrity_entity_dominance"],
        build_memory_governance_candidates(fixture.input()),
    )
}

fn weak_evidence_fixture() -> MemoryGovernanceAdversarialFixtureResult {
    let kai = entity("kai");
    let rift = entity("rift");
    let mut fixture = GovernanceFixture::new(
        (0..4)
            .map(|index| chunk(&format!("weak:{index}"), index))
            .collect(),
    );
    for index in 0..4 {
        fixture.anchors.push(anchor(
            &format!("anchor:kai:weak:{index}"),
            &kai,
            &format!("weak:{index}"),
        ));
        fixture.anchors.push(anchor(
            &format!("anchor:rift:weak:{index}"),
            &rift,
            &format!("weak:{index}"),
        ));
    }
    candidate_fixture(
        "weak-evidence",
        "Weak evidence pressure",
        "weak_evidence",
        "weak:0",
        GraphMemoryGovernanceAction::Quarantine,
        "chunk_entity_salience_dominated_by_celebrity_surface",
        &["audit:weak_evidence:"],
        build_memory_governance_candidates(fixture.input()),
    )
}

fn compression_fixture() -> MemoryGovernanceAdversarialFixtureResult {
    let kai = entity("kai");
    let mut fixture = GovernanceFixture::new(vec![
        chunk("episode:chunk:0", 0),
        chunk("episode:chunk:1", 1),
        chunk("episode:chunk:2", 2),
    ]);
    for index in 0..3 {
        let event_id = format!("event:{index}");
        let chunk_id = format!("episode:chunk:{index}");
        let anchor_id = format!("anchor:kai:event:{index}");
        fixture.anchors.push(anchor(&anchor_id, &kai, &chunk_id));
        fixture
            .events
            .push(event(&event_id, &chunk_id, &[kai.clone()], &[&anchor_id]));
    }
    fixture.episodes.push(GraphEpisode {
        id: "episode:dominant".into(),
        note_id: "note:adversarial".into(),
        event_ids: vec!["event:0".into(), "event:1".into(), "event:2".into()],
        entity_ids: vec![kai],
        label: "Dominant episode".into(),
    });
    let rows = build_memory_governance_candidates(fixture.input());
    let retrieval = vec![retrieval(
        "hit:episode",
        "episode:dominant",
        GraphMemoryGovernanceTargetKind::Episode,
        0.97,
    )];
    let preview =
        build_memory_governance_retrieval_preview(MemoryGovernanceRetrievalPreviewInput {
            retrieval_candidates: &retrieval,
            governance_candidates: &rows,
        });
    let mut result = candidate_fixture(
        "compression-dominance",
        "Compression dominance",
        "compression_dominance",
        "episode:dominant",
        GraphMemoryGovernanceAction::Compress,
        "episode_can_compact_child_chunks",
        &["memory_governance:retrieval_policy_overlay"],
        rows,
    );
    result.retrieval_rows = preview.rows.iter().map(retrieval_row).collect();
    result.checks.push(check(
        "retrieval_report_only",
        preview.no_topology_commit,
        "retrieval preview is report-only",
    ));
    result.checks.push(check(
        "compression_score_capped",
        preview.rows[0].adjusted_score <= 1.0,
        "adjusted score capped",
    ));
    result.passed = result.checks.iter().all(|row| row.passed);
    result
}

fn negative_relation_fixture() -> MemoryGovernanceAdversarialFixtureResult {
    let entities = vec![lexicon("e-kai", "Kai"), lexicon("e-hazel", "Hazel")];
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:negative-adversarial",
        note_id: "note-negative-adversarial",
        text: "Kai betrays Hazel.",
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 2,
        built_at: Some(17),
    })
    .expect("negative relation adversarial fixture should build");
    let negative_rows = snapshot
        .relationships
        .iter()
        .filter(|row| row.relation_type == "betrays")
        .map(negative_relation_row)
        .collect::<Vec<_>>();
    let checks = vec![
        check(
            "negative_relation_present",
            !negative_rows.is_empty(),
            "betrays review row exists",
        ),
        check(
            "review_only",
            negative_rows.iter().all(|row| row.status == "review"),
            "negative cues stay in review",
        ),
        check(
            "no_committed_edge",
            snapshot
                .edges
                .iter()
                .all(|edge| edge.edge_type != "betrays"),
            "negative relation did not become topology",
        ),
    ];
    MemoryGovernanceAdversarialFixtureResult {
        id: "negative-relation".into(),
        title: "Negative relation review".into(),
        threat_lane: "negative_relation".into(),
        expected_action: "review_only".into(),
        expected_target_id: "e-kai->e-hazel".into(),
        passed: checks.iter().all(|row| row.passed),
        candidates_by_action: BTreeMap::new(),
        no_topology_proof: MemoryGovernanceAdversarialNoTopologyProof {
            passed: true,
            ..MemoryGovernanceAdversarialNoTopologyProof::default()
        },
        top_rows: Vec::new(),
        weakest_rows: Vec::new(),
        retrieval_rows: Vec::new(),
        negative_relation_rows: negative_rows,
        checks,
    }
}

fn candidate_fixture(
    id: &str,
    title: &str,
    threat_lane: &str,
    expected_target_id: &str,
    expected_action: GraphMemoryGovernanceAction,
    expected_reason: &str,
    rationale_needles: &[&str],
    rows: Vec<GraphMemoryGovernanceCandidate>,
) -> MemoryGovernanceAdversarialFixtureResult {
    let selected = rows.iter().find(|row| row.target_id == expected_target_id);
    let no_topology_proof = no_topology_proof(&rows);
    let mut checks = vec![
        check(
            "target_present",
            selected.is_some(),
            "expected target row exists",
        ),
        check(
            "no_topology_proof",
            no_topology_proof.passed,
            "candidate-only no topology proof",
        ),
    ];
    if let Some(row) = selected {
        checks.push(check(
            "expected_action",
            row.action == expected_action,
            expected_action.as_str(),
        ));
        checks.push(check(
            "expected_reason",
            row.reason == expected_reason,
            expected_reason,
        ));
        for needle in rationale_needles {
            checks.push(check(
                format_compact!("rationale:{needle}"),
                row.rationale.iter().any(|line| line.contains(needle)),
                *needle,
            ));
        }
    }
    MemoryGovernanceAdversarialFixtureResult {
        id: id.into(),
        title: title.into(),
        threat_lane: threat_lane.into(),
        expected_action: expected_action.as_str().into(),
        expected_target_id: expected_target_id.into(),
        passed: checks.iter().all(|row| row.passed),
        candidates_by_action: action_counts(&rows),
        no_topology_proof,
        top_rows: top_rows(&rows),
        weakest_rows: weakest_rows(&rows),
        retrieval_rows: Vec::new(),
        negative_relation_rows: Vec::new(),
        checks,
    }
}

fn no_topology_proof(
    rows: &[GraphMemoryGovernanceCandidate],
) -> MemoryGovernanceAdversarialNoTopologyProof {
    let mut violations = Vec::new();
    for row in rows {
        if row.schema_version != MEMORY_GOVERNANCE_SCHEMA_VERSION {
            violations.push(format_compact!("{}:schema", row.id));
        }
        if row.status != GraphMemoryGovernanceStatus::Candidate {
            violations.push(format_compact!("{}:status", row.id));
        }
        if row.commit_policy != GraphMemoryGovernanceCommitPolicy::NoTopologyCommit {
            violations.push(format_compact!("{}:commit_policy", row.id));
        }
        if row.commit_policy.as_str() != MEMORY_GOVERNANCE_COMMIT_POLICY {
            violations.push(format_compact!("{}:commit_policy_contract", row.id));
        }
        if !row.no_topology_commit {
            violations.push(format_compact!("{}:topology_write", row.id));
        }
        if !row
            .rationale
            .iter()
            .any(|line| line == MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT)
        {
            violations.push(format_compact!("{}:missing_no_topology_rationale", row.id));
        }
    }
    if assert_memory_governance_candidate_only(rows).is_err() {
        violations.push("candidate_only_guard_failed".into());
    }
    MemoryGovernanceAdversarialNoTopologyProof {
        passed: violations.is_empty(),
        candidate_rows: rows.len(),
        candidate_only_rows: rows
            .iter()
            .filter(|row| row.status == GraphMemoryGovernanceStatus::Candidate)
            .count(),
        no_topology_commit_rows: rows.iter().filter(|row| row.no_topology_commit).count(),
        commit_policy_rows: rows
            .iter()
            .filter(|row| row.commit_policy == GraphMemoryGovernanceCommitPolicy::NoTopologyCommit)
            .count(),
        missing_no_topology_rationale_rows: rows
            .iter()
            .filter(|row| {
                !row.rationale
                    .iter()
                    .any(|line| line == MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT)
            })
            .count(),
        violations,
    }
}

fn top_rows(
    rows: &[GraphMemoryGovernanceCandidate],
) -> Vec<MemoryGovernanceAdversarialCandidateRow> {
    let mut rows = rows.to_vec();
    rows.sort_by(confidence_desc);
    rows.iter().take(5).map(candidate_row).collect()
}

fn weakest_rows(
    rows: &[GraphMemoryGovernanceCandidate],
) -> Vec<MemoryGovernanceAdversarialCandidateRow> {
    let mut rows = rows.to_vec();
    rows.sort_by(confidence_asc);
    rows.iter().take(5).map(candidate_row).collect()
}

fn candidate_row(row: &GraphMemoryGovernanceCandidate) -> MemoryGovernanceAdversarialCandidateRow {
    MemoryGovernanceAdversarialCandidateRow {
        id: row.id.clone(),
        target_id: row.target_id.clone(),
        target_kind: row.target_kind.as_str().into(),
        action: row.action.as_str().into(),
        reason: row.reason.clone(),
        confidence_millis: confidence_millis(row.confidence),
        evidence_count: row.evidence_ids.len(),
        no_topology_commit: row.no_topology_commit,
        rationale: row.rationale.clone(),
    }
}

fn retrieval_row(
    row: &crate::MemoryGovernanceRetrievalPreviewRow,
) -> MemoryGovernanceAdversarialRetrievalRow {
    MemoryGovernanceAdversarialRetrievalRow {
        target_id: row.target_id.clone(),
        target_kind: row.target_kind.as_str().into(),
        original_rank: row.original_rank,
        adjusted_rank: row.adjusted_rank,
        score_delta_millis: (row.score_delta * 1000.0).round() as i16,
        no_topology_commit: row.no_topology_commit,
    }
}

fn negative_relation_row(
    row: &GraphRelationship,
) -> MemoryGovernanceAdversarialNegativeRelationRow {
    MemoryGovernanceAdversarialNegativeRelationRow {
        relation_type: row.relation_type.clone(),
        source_entity_id: row.source_entity_id.0.as_str().into(),
        target_entity_id: row.target_entity_id.0.as_str().into(),
        status: row.status.clone(),
        adjudication_source: row.adjudication_source.clone(),
        confidence_millis: confidence_millis(row.confidence),
    }
}

fn action_counts(rows: &[GraphMemoryGovernanceCandidate]) -> BTreeMap<CompactString, usize> {
    let mut counts = BTreeMap::new();
    for row in rows {
        *counts.entry(row.action.as_str().into()).or_insert(0) += 1;
    }
    counts
}

fn check(
    name: impl Into<CompactString>,
    passed: bool,
    detail: impl Into<CompactString>,
) -> MemoryGovernanceAdversarialCheck {
    MemoryGovernanceAdversarialCheck {
        name: name.into(),
        passed,
        detail: detail.into(),
    }
}

#[derive(Default)]
struct GovernanceFixture {
    chunks: Vec<GraphChunk>,
    episodes: Vec<GraphEpisode>,
    anchors: Vec<GraphAnchor>,
    relationships: Vec<GraphRelationship>,
    events: Vec<GraphEvent>,
    temporal_edges: Vec<GraphTemporalEdge>,
    causal_edges: Vec<GraphTemporalEdge>,
    memory_state: Vec<GraphMemoryState>,
}

impl GovernanceFixture {
    fn new(chunks: Vec<GraphChunk>) -> Self {
        Self {
            chunks,
            ..Self::default()
        }
    }

    fn input(&self) -> MemoryGovernanceEngineInput<'_> {
        MemoryGovernanceEngineInput {
            chunks: &self.chunks,
            episodes: &self.episodes,
            anchors: &self.anchors,
            relationships: &self.relationships,
            events: &self.events,
            temporal_edges: &self.temporal_edges,
            causal_edges: &self.causal_edges,
            memory_state: &self.memory_state,
        }
    }
}

fn chunk(id: &str, ordinal: u32) -> GraphChunk {
    GraphChunk {
        id: id.into(),
        note_id: "note:adversarial".into(),
        start: ordinal * 10,
        end: ordinal * 10 + 8,
        ordinal,
        source: "adversarial-fixture".into(),
    }
}

fn anchor(id: &str, entity_id: &EntityId, chunk_id: &str) -> GraphAnchor {
    GraphAnchor {
        id: id.into(),
        entity_id: entity_id.clone(),
        note_id: "note:adversarial".into(),
        chunk_id: Some(chunk_id.into()),
        surface: "entity".into(),
        source_start: 0,
        source_end: 6,
        source: "adversarial-fixture".into(),
        confidence: 1.0,
        generation: 1,
    }
}

fn state(
    id: &str,
    entity_id: &EntityId,
    key: &str,
    value: &str,
    evidence_id: &str,
) -> GraphMemoryState {
    state_with_evidence(id, entity_id, key, value, &[evidence_id])
}

fn state_with_evidence(
    id: &str,
    entity_id: &EntityId,
    key: &str,
    value: &str,
    evidence_ids: &[&str],
) -> GraphMemoryState {
    GraphMemoryState {
        id: id.into(),
        entity_id: entity_id.clone(),
        note_id: Some("note:adversarial".into()),
        key: key.into(),
        value: value.into(),
        evidence_ids: evidence_ids.iter().map(|id| (*id).into()).collect(),
    }
}

fn event(id: &str, chunk_id: &str, entity_ids: &[EntityId], evidence_ids: &[&str]) -> GraphEvent {
    GraphEvent {
        id: id.into(),
        note_id: "note:adversarial".into(),
        chunk_id: Some(chunk_id.into()),
        label: "event".into(),
        entity_ids: entity_ids.to_vec(),
        evidence_anchor_ids: evidence_ids
            .iter()
            .map(|value| CompactString::from(*value))
            .collect(),
        confidence: 0.82,
    }
}

fn retrieval(
    id: &str,
    target_id: &str,
    target_kind: GraphMemoryGovernanceTargetKind,
    score: f32,
) -> MemoryGovernanceRetrievalCandidate {
    MemoryGovernanceRetrievalCandidate {
        id: id.into(),
        target_id: target_id.into(),
        target_kind,
        score,
    }
}

fn entity(id: &str) -> EntityId {
    EntityId(format!("character:{id}"))
}

fn lexicon(id: &str, surface: &str) -> LexiconEntry {
    LexiconEntry {
        entity_id: EntityId(id.to_owned()),
        label: surface.to_owned(),
        aliases: Vec::new(),
        kind: Some(EntityKind::Character),
        scope: ScopeKey::default(),
        ..LexiconEntry::default()
    }
}

fn confidence_desc(
    left: &GraphMemoryGovernanceCandidate,
    right: &GraphMemoryGovernanceCandidate,
) -> std::cmp::Ordering {
    right
        .confidence
        .total_cmp(&left.confidence)
        .then_with(|| left.id.cmp(&right.id))
}

fn confidence_asc(
    left: &GraphMemoryGovernanceCandidate,
    right: &GraphMemoryGovernanceCandidate,
) -> std::cmp::Ordering {
    left.confidence
        .total_cmp(&right.confidence)
        .then_with(|| left.id.cmp(&right.id))
}

fn confidence_millis(confidence: f32) -> u16 {
    (confidence * 1000.0).round().clamp(0.0, 1000.0) as u16
}
