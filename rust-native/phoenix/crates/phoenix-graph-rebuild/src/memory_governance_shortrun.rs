use std::collections::{BTreeMap, BTreeSet};
use std::time::Instant;

use compact_str::{format_compact, CompactString};
use phoenix_types::{EntityId, EntityKind, LexiconEntry, ScopeKey};
use serde::{Deserialize, Serialize};

use crate::types::{
    GraphMemoryGovernanceAction, GraphMemoryGovernanceCandidate, GraphMemoryGovernanceCommitPolicy,
    GraphMemoryGovernanceStatus,
};
use crate::{build_graph_rebuild_snapshot, GraphRebuildInput, GraphScopeKind};

use super::{
    assert_memory_governance_candidate_only, MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT,
    MEMORY_GOVERNANCE_SCHEMA_VERSION,
};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceShortrunGoldenReport {
    pub schema_version: CompactString,
    pub source_path: CompactString,
    pub golden_path: CompactString,
    pub fixture: MemoryGovernanceCounts,
    pub rust: MemoryGovernanceCounts,
    pub confidence: MemoryGovernanceConfidenceSummary,
    pub candidate_only_audit: MemoryGovernanceCandidateOnlyAudit,
    pub comparison: MemoryGovernanceShortrunComparison,
    pub representative_rows: Vec<MemoryGovernanceRepresentativeRow>,
    pub timing: MemoryGovernanceTimingReport,
    pub performance_budget: MemoryGovernancePerformanceBudget,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceCounts {
    pub total: usize,
    pub by_action: BTreeMap<CompactString, usize>,
    pub by_target_action: BTreeMap<CompactString, usize>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceConfidenceSummary {
    pub compress_distinct: usize,
    pub compress_min_millis: u16,
    pub compress_max_millis: u16,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceCandidateOnlyAudit {
    pub invalid_schema_version: usize,
    pub invalid_status: usize,
    pub invalid_commit_policy: usize,
    pub missing_no_topology_guard: usize,
    pub missing_no_topology_rationale: usize,
    pub governance_edge_rows: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceShortrunComparison {
    pub exact_counts_match: bool,
    pub total_delta: isize,
    pub by_action_delta: BTreeMap<CompactString, isize>,
    pub by_target_action_delta: BTreeMap<CompactString, isize>,
    pub compress_confidence_matches: bool,
    pub golden_sample_ids_seen: usize,
    pub golden_sample_ids_missing: Vec<CompactString>,
    pub golden_sample_mismatches: Vec<CompactString>,
    pub performance_budget_passed: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceRepresentativeRow {
    pub schema_version: CompactString,
    pub id: CompactString,
    pub target_id: CompactString,
    pub target_kind: CompactString,
    pub action: CompactString,
    pub reason: CompactString,
    pub status: CompactString,
    pub commit_policy: CompactString,
    pub no_topology_commit: bool,
    pub confidence: f32,
    pub evidence_count: usize,
    pub supporting_entity_count: usize,
    pub related_event_count: usize,
    pub related_chunk_count: usize,
    pub rationale: Vec<CompactString>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceTimingReport {
    pub snapshot_build_micros: u128,
    pub governance_build_micros: u128,
    pub total_micros: u128,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernancePerformanceBudget {
    pub max_snapshot_build_micros: u128,
    pub max_governance_build_micros: u128,
}

impl Default for MemoryGovernancePerformanceBudget {
    fn default() -> Self {
        Self {
            max_snapshot_build_micros: 500_000,
            max_governance_build_micros: 100_000,
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MemoryGovernanceGoldenFixture {
    counts: MemoryGovernanceCounts,
    confidence: MemoryGovernanceConfidenceSummary,
    #[serde(default)]
    samples: Vec<MemoryGovernanceRepresentativeRow>,
    #[serde(default)]
    performance_budget: MemoryGovernancePerformanceBudget,
}

pub fn build_memory_governance_shortrun_golden_report(
    shortrun_text: &str,
    fixture_json: &str,
) -> Result<MemoryGovernanceShortrunGoldenReport, String> {
    let started = Instant::now();
    let snapshot_started = Instant::now();
    let entities = shortrun_entities();
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:shortrun",
        note_id: "shortrun",
        text: shortrun_text,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: entities.len(),
        built_at: Some(1),
    })
    .map_err(|error| error.to_string())?;
    let snapshot_build_micros = snapshot_started.elapsed().as_micros();
    let candidates = &snapshot.memory_governance_candidates;
    let golden: MemoryGovernanceGoldenFixture =
        serde_json::from_str(fixture_json).map_err(|error| error.to_string())?;
    let rust = counts_for(candidates);
    let confidence = confidence_for(candidates);
    let timing = MemoryGovernanceTimingReport {
        snapshot_build_micros,
        governance_build_micros: snapshot.counters.memory_governance_build_micros as u128,
        total_micros: started.elapsed().as_micros(),
    };
    let comparison = compare_golden(
        &golden.counts,
        &rust,
        golden.confidence,
        confidence,
        &golden.samples,
        candidates,
        golden.performance_budget,
        timing,
    );

    Ok(MemoryGovernanceShortrunGoldenReport {
        schema_version: "phoenix-memory-governance-shortrun-rust-golden/v1".into(),
        source_path: "docs/shortrun.md".into(),
        golden_path: "src/app/graph-rebuild/fixtures/memory-governance-shortrun-golden.json".into(),
        fixture: golden.counts,
        rust,
        confidence,
        candidate_only_audit: candidate_only_audit(candidates, &snapshot.edges),
        comparison,
        representative_rows: representative_rows(candidates),
        timing,
        performance_budget: golden.performance_budget,
    })
}

fn counts_for(candidates: &[GraphMemoryGovernanceCandidate]) -> MemoryGovernanceCounts {
    let mut by_action = BTreeMap::<CompactString, usize>::new();
    let mut by_target_action = BTreeMap::<CompactString, usize>::new();
    for candidate in candidates {
        *by_action
            .entry(candidate.action.as_str().into())
            .or_insert(0) += 1;
        *by_target_action
            .entry(format_compact!(
                "{}:{}",
                candidate.target_kind.as_str(),
                candidate.action.as_str()
            ))
            .or_insert(0) += 1;
    }
    MemoryGovernanceCounts {
        total: candidates.len(),
        by_action,
        by_target_action,
    }
}

fn confidence_for(
    candidates: &[GraphMemoryGovernanceCandidate],
) -> MemoryGovernanceConfidenceSummary {
    let mut distinct = BTreeSet::<u16>::new();
    let mut min = u16::MAX;
    let mut max = 0_u16;
    for candidate in candidates
        .iter()
        .filter(|row| row.action == GraphMemoryGovernanceAction::Compress)
    {
        let millis = confidence_millis(candidate.confidence);
        distinct.insert(millis);
        min = min.min(millis);
        max = max.max(millis);
    }
    if distinct.is_empty() {
        min = 0;
    }
    MemoryGovernanceConfidenceSummary {
        compress_distinct: distinct.len(),
        compress_min_millis: min,
        compress_max_millis: max,
    }
}

fn candidate_only_audit(
    candidates: &[GraphMemoryGovernanceCandidate],
    edges: &[crate::GraphEdge],
) -> MemoryGovernanceCandidateOnlyAudit {
    let mut audit = MemoryGovernanceCandidateOnlyAudit::default();
    for candidate in candidates {
        if candidate.schema_version != MEMORY_GOVERNANCE_SCHEMA_VERSION {
            audit.invalid_schema_version += 1;
        }
        if candidate.status != GraphMemoryGovernanceStatus::Candidate {
            audit.invalid_status += 1;
        }
        if candidate.commit_policy != GraphMemoryGovernanceCommitPolicy::NoTopologyCommit {
            audit.invalid_commit_policy += 1;
        }
        if !candidate.no_topology_commit {
            audit.missing_no_topology_guard += 1;
        }
        if !candidate
            .rationale
            .iter()
            .any(|row| row == MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT)
        {
            audit.missing_no_topology_rationale += 1;
        }
    }
    if assert_memory_governance_candidate_only(candidates).is_err() {
        audit.invalid_status += 1;
    }
    audit.governance_edge_rows = edges
        .iter()
        .filter(|edge| is_governance_topology_row(edge.id.as_str(), edge.edge_type.as_str()))
        .count();
    audit
}

fn compare_golden(
    fixture: &MemoryGovernanceCounts,
    rust: &MemoryGovernanceCounts,
    fixture_confidence: MemoryGovernanceConfidenceSummary,
    rust_confidence: MemoryGovernanceConfidenceSummary,
    samples: &[MemoryGovernanceRepresentativeRow],
    candidates: &[GraphMemoryGovernanceCandidate],
    budget: MemoryGovernancePerformanceBudget,
    timing: MemoryGovernanceTimingReport,
) -> MemoryGovernanceShortrunComparison {
    let actual_rows = candidates
        .iter()
        .map(candidate_row)
        .map(|row| (row.id.clone(), row))
        .collect::<BTreeMap<_, _>>();
    let mut golden_sample_ids_missing = Vec::new();
    let mut golden_sample_mismatches = Vec::new();
    for expected in samples {
        let Some(actual) = actual_rows.get(&expected.id) else {
            golden_sample_ids_missing.push(expected.id.clone());
            continue;
        };
        if !row_matches(actual, expected) {
            golden_sample_mismatches.push(expected.id.clone());
        }
    }
    let performance_budget_passed = timing.snapshot_build_micros
        <= budget.max_snapshot_build_micros
        && timing.governance_build_micros <= budget.max_governance_build_micros;
    MemoryGovernanceShortrunComparison {
        exact_counts_match: fixture == rust,
        total_delta: rust.total as isize - fixture.total as isize,
        by_action_delta: delta_map(&fixture.by_action, &rust.by_action),
        by_target_action_delta: delta_map(&fixture.by_target_action, &rust.by_target_action),
        compress_confidence_matches: fixture_confidence == rust_confidence,
        golden_sample_ids_seen: samples.len() - golden_sample_ids_missing.len(),
        golden_sample_ids_missing,
        golden_sample_mismatches,
        performance_budget_passed,
    }
}

fn representative_rows(
    candidates: &[GraphMemoryGovernanceCandidate],
) -> Vec<MemoryGovernanceRepresentativeRow> {
    candidates.iter().take(32).map(candidate_row).collect()
}

fn candidate_row(candidate: &GraphMemoryGovernanceCandidate) -> MemoryGovernanceRepresentativeRow {
    MemoryGovernanceRepresentativeRow {
        schema_version: candidate.schema_version.clone(),
        id: candidate.id.clone(),
        target_id: candidate.target_id.clone(),
        target_kind: candidate.target_kind.as_str().into(),
        action: candidate.action.as_str().into(),
        reason: candidate.reason.clone(),
        status: candidate.status.as_str().into(),
        commit_policy: candidate.commit_policy.as_str().into(),
        no_topology_commit: candidate.no_topology_commit,
        confidence: confidence_millis(candidate.confidence) as f32 / 1000.0,
        evidence_count: candidate.evidence_ids.len(),
        supporting_entity_count: candidate.supporting_entity_ids.len(),
        related_event_count: candidate.related_event_ids.len(),
        related_chunk_count: candidate.related_chunk_ids.len(),
        rationale: candidate.rationale.clone(),
    }
}

fn row_matches(
    actual: &MemoryGovernanceRepresentativeRow,
    expected: &MemoryGovernanceRepresentativeRow,
) -> bool {
    actual.schema_version == expected.schema_version
        && actual.target_id == expected.target_id
        && actual.target_kind == expected.target_kind
        && actual.action == expected.action
        && actual.reason == expected.reason
        && actual.status == expected.status
        && actual.commit_policy == expected.commit_policy
        && actual.no_topology_commit == expected.no_topology_commit
        && confidence_millis(actual.confidence) == confidence_millis(expected.confidence)
        && actual.evidence_count == expected.evidence_count
        && actual.supporting_entity_count == expected.supporting_entity_count
        && actual.related_event_count == expected.related_event_count
        && actual.related_chunk_count == expected.related_chunk_count
        && actual.rationale == expected.rationale
}

fn delta_map(
    expected: &BTreeMap<CompactString, usize>,
    actual: &BTreeMap<CompactString, usize>,
) -> BTreeMap<CompactString, isize> {
    let mut out = BTreeMap::new();
    for key in expected.keys().chain(actual.keys()) {
        out.insert(
            key.clone(),
            *actual.get(key).unwrap_or(&0) as isize - *expected.get(key).unwrap_or(&0) as isize,
        );
    }
    out
}

fn is_governance_topology_row(id: &str, edge_type: &str) -> bool {
    let haystack = [id, edge_type].join("|");
    ["govern", "decay", "attenuat", "compress", "retain", "evict"]
        .iter()
        .any(|needle| haystack.contains(needle))
}

fn confidence_millis(confidence: f32) -> u16 {
    (confidence * 1000.0).round().clamp(0.0, 1000.0) as u16
}

fn shortrun_entities() -> Vec<LexiconEntry> {
    vec![
        entity("entity-ryan", "Ryan", EntityKind::Character, &["Quicksave"]),
        entity("entity-new-rome", "New Rome", EntityKind::Location, &[]),
        entity("entity-campania", "Campania", EntityKind::Location, &[]),
        entity("entity-italy", "Italy", EntityKind::Location, &[]),
        entity("entity-europe", "Europe", EntityKind::Location, &[]),
        entity("entity-naples", "Naples", EntityKind::Location, &[]),
        entity(
            "entity-mediterranean-sea",
            "Mediterranean Sea",
            EntityKind::Location,
            &[],
        ),
        entity("entity-mechron", "Mechron", EntityKind::Character, &[]),
        entity("entity-genome-wars", "Genome Wars", EntityKind::Event, &[]),
        entity("entity-dynamis", "Dynamis", EntityKind::Faction, &[]),
        entity(
            "entity-dynamis-tower",
            "Dynamis Tower",
            EntityKind::Location,
            &[],
        ),
        entity(
            "entity-golden-coast",
            "Golden Coast",
            EntityKind::Location,
            &[],
        ),
        entity("entity-wyvern", "Wyvern", EntityKind::Character, &[]),
        entity(
            "entity-hercules-elixir",
            "Hercules Elixir",
            EntityKind::Item,
            &[],
        ),
        entity("entity-renesco", "Renesco", EntityKind::Character, &[]),
        entity(
            "entity-jolie-wrangler",
            "Jolie Wrangler",
            EntityKind::Location,
            &[],
        ),
        entity("entity-len", "Len", EntityKind::Character, &[]),
        entity("entity-rust-town", "Rust Town", EntityKind::Location, &[]),
        entity("entity-junkyard", "Junkyard", EntityKind::Location, &[]),
        entity("entity-psychos", "Psychos", EntityKind::Faction, &[]),
        entity("entity-adam", "Adam", EntityKind::Character, &[]),
        entity(
            "entity-private-security",
            "Private Security",
            EntityKind::Faction,
            &[],
        ),
        entity("entity-augusti", "Augusti", EntityKind::Faction, &[]),
        entity(
            "entity-plymouth-fury",
            "Plymouth Fury",
            EntityKind::Item,
            &[],
        ),
        entity("entity-bliss", "Bliss", EntityKind::Item, &[]),
    ]
}

fn entity(id: &str, label: &str, kind: EntityKind, aliases: &[&str]) -> LexiconEntry {
    LexiconEntry {
        entity_id: EntityId(id.to_owned()),
        label: label.to_owned(),
        aliases: aliases.iter().map(|alias| (*alias).to_owned()).collect(),
        kind: Some(kind),
        scope: ScopeKey::default(),
        ..LexiconEntry::default()
    }
}
