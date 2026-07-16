use std::collections::BTreeMap;
use std::time::Instant;

use compact_str::CompactString;
use phoenix_types::{EntityId, EntityKind, LexiconEntry, ScopeKey};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{build_graph_rebuild_snapshot, GraphRebuildInput, GraphScopeKind};

use super::{
    assert_chunk_semantic_bridge_candidate_only, audit_chunk_semantic_bridge_quality_gate,
    build_chunk_semantic_bridge_candidates_from_snapshot, ChunkSemanticBridgeCandidate,
    ChunkSemanticBridgeSnapshotDocument, CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY,
    CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT, CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION,
};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeShortrunParityReport {
    pub schema_version: CompactString,
    pub source_path: CompactString,
    pub golden_path: CompactString,
    pub fixture: BridgeCounts,
    pub rust: BridgeCounts,
    pub candidate_only_audit: BridgeCandidateOnlyAudit,
    pub comparison: BridgeShortrunParityComparison,
    pub representative_rows: Vec<BridgeRepresentativeRow>,
    pub timing: BridgeTimingReport,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeCounts {
    pub total: usize,
    pub by_type: BTreeMap<CompactString, usize>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeCandidateOnlyAudit {
    pub invalid_schema_version: usize,
    pub invalid_status: usize,
    pub invalid_commit_policy: usize,
    pub missing_no_topology_guard: usize,
    pub same_entity_only_false_positive_suspects: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeShortrunParityComparison {
    pub exact_counts_match: bool,
    pub total_delta: isize,
    pub by_type_delta: BTreeMap<CompactString, isize>,
    pub golden_sample_ids_seen: usize,
    pub golden_sample_ids_missing: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeRepresentativeRow {
    pub id: CompactString,
    pub bridge_type: CompactString,
    pub status: CompactString,
    pub commit_policy: CompactString,
    pub confidence: f32,
    pub source_chunk_id: CompactString,
    pub target_chunk_id: CompactString,
    pub source_event_id: Option<CompactString>,
    pub target_event_id: Option<CompactString>,
    pub source_episode_id: Option<CompactString>,
    pub target_episode_id: Option<CompactString>,
    pub semantic_verbs: Vec<CompactString>,
    pub source_cue: Option<CompactString>,
    pub target_cue: Option<CompactString>,
    pub supporting_entity_ids: Vec<CompactString>,
    pub evidence_ids: Vec<CompactString>,
    pub rationale: Vec<CompactString>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeTimingReport {
    pub snapshot_build_micros: u128,
    pub bridge_build_micros: u128,
    pub total_micros: u128,
}

pub fn build_chunk_semantic_bridge_shortrun_parity_report(
    shortrun_text: &str,
    fixture_json: &str,
) -> Result<BridgeShortrunParityReport, String> {
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

    let bridge_started = Instant::now();
    let candidates = build_chunk_semantic_bridge_candidates_from_snapshot(
        &snapshot,
        &[ChunkSemanticBridgeSnapshotDocument {
            note_id: "shortrun",
            text: shortrun_text,
        }],
    );
    let bridge_build_micros = bridge_started.elapsed().as_micros();
    let fixture = parse_fixture_counts(fixture_json)?;
    let fixture_sample_ids = parse_fixture_sample_ids(fixture_json)?;
    let rust = counts_for(&candidates);
    let comparison = compare_counts(&fixture, &rust, &candidates, &fixture_sample_ids);

    Ok(BridgeShortrunParityReport {
        schema_version: "phoenix-chunk-semantic-bridge-shortrun-rust-parity/v1".into(),
        source_path: "docs/shortrun.md".into(),
        golden_path: "src/app/graph-rebuild/fixtures/chunk-semantic-bridge-shortrun-golden.json"
            .into(),
        fixture,
        rust,
        candidate_only_audit: candidate_only_audit(&candidates),
        comparison,
        representative_rows: representative_rows(&candidates),
        timing: BridgeTimingReport {
            snapshot_build_micros,
            bridge_build_micros,
            total_micros: started.elapsed().as_micros(),
        },
    })
}

fn counts_for(candidates: &[ChunkSemanticBridgeCandidate]) -> BridgeCounts {
    let mut by_type = BTreeMap::<CompactString, usize>::new();
    for candidate in candidates {
        *by_type
            .entry(candidate.bridge_type.as_str().into())
            .or_insert(0) += 1;
    }
    BridgeCounts {
        total: candidates.len(),
        by_type,
    }
}

fn candidate_only_audit(candidates: &[ChunkSemanticBridgeCandidate]) -> BridgeCandidateOnlyAudit {
    let mut audit = BridgeCandidateOnlyAudit::default();
    let quality = audit_chunk_semantic_bridge_quality_gate(candidates);
    for candidate in candidates {
        if candidate.schema_version != CHUNK_SEMANTIC_BRIDGE_SCHEMA_VERSION {
            audit.invalid_schema_version += 1;
        }
        if candidate.status.as_str() != "candidate" {
            audit.invalid_status += 1;
        }
        if candidate.commit_policy.as_str() != CHUNK_SEMANTIC_BRIDGE_COMMIT_POLICY {
            audit.invalid_commit_policy += 1;
        }
        if !candidate
            .rationale
            .iter()
            .any(|row| row == CHUNK_SEMANTIC_BRIDGE_NO_TOPOLOGY_COMMIT)
        {
            audit.missing_no_topology_guard += 1;
        }
    }
    audit.same_entity_only_false_positive_suspects = quality.demoted_same_entity_only;
    if assert_chunk_semantic_bridge_candidate_only(candidates).is_err() {
        audit.invalid_status += 1;
    }
    audit
}

fn representative_rows(
    candidates: &[ChunkSemanticBridgeCandidate],
) -> Vec<BridgeRepresentativeRow> {
    let mut rows = candidates.to_vec();
    rows.sort_by(|left, right| {
        left.bridge_type
            .as_str()
            .cmp(right.bridge_type.as_str())
            .then_with(|| right.confidence.total_cmp(&left.confidence))
            .then_with(|| left.id.cmp(&right.id))
    });
    rows.into_iter()
        .take(32)
        .map(|candidate| BridgeRepresentativeRow {
            id: candidate.id,
            bridge_type: candidate.bridge_type.as_str().into(),
            status: candidate.status.as_str().into(),
            commit_policy: candidate.commit_policy.as_str().into(),
            confidence: (candidate.confidence * 1000.0).round() / 1000.0,
            source_chunk_id: candidate.source_chunk_id,
            target_chunk_id: candidate.target_chunk_id,
            source_event_id: candidate.source_event_id,
            target_event_id: candidate.target_event_id,
            source_episode_id: candidate.source_episode_id,
            target_episode_id: candidate.target_episode_id,
            semantic_verbs: candidate.semantic_verbs,
            source_cue: candidate.source_cue,
            target_cue: candidate.target_cue,
            supporting_entity_ids: candidate.supporting_entity_ids,
            evidence_ids: candidate.evidence_ids.into_iter().take(8).collect(),
            rationale: candidate.rationale,
        })
        .collect()
}

fn parse_fixture_counts(raw: &str) -> Result<BridgeCounts, String> {
    let value: Value = serde_json::from_str(raw).map_err(|error| error.to_string())?;
    let counts = value
        .get("counts")
        .ok_or_else(|| "golden missing counts".to_owned())?;
    let total = counts
        .get("total")
        .and_then(Value::as_u64)
        .ok_or_else(|| "golden missing counts.total".to_owned())? as usize;
    let mut by_type = BTreeMap::new();
    let Some(object) = counts.get("byType").and_then(Value::as_object) else {
        return Err("golden missing counts.byType".to_owned());
    };
    for (key, value) in object {
        by_type.insert(
            CompactString::from(key.as_str()),
            value.as_u64().unwrap_or_default() as usize,
        );
    }
    Ok(BridgeCounts { total, by_type })
}

fn parse_fixture_sample_ids(raw: &str) -> Result<Vec<CompactString>, String> {
    let value: Value = serde_json::from_str(raw).map_err(|error| error.to_string())?;
    Ok(value
        .get("samples")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|sample| sample.get("id").and_then(Value::as_str))
        .map(CompactString::from)
        .collect())
}

fn compare_counts(
    fixture: &BridgeCounts,
    rust: &BridgeCounts,
    candidates: &[ChunkSemanticBridgeCandidate],
    golden_sample_ids: &[CompactString],
) -> BridgeShortrunParityComparison {
    let mut by_type_delta = BTreeMap::<CompactString, isize>::new();
    for key in fixture.by_type.keys().chain(rust.by_type.keys()) {
        by_type_delta.insert(
            key.clone(),
            *rust.by_type.get(key).unwrap_or(&0) as isize
                - *fixture.by_type.get(key).unwrap_or(&0) as isize,
        );
    }
    let candidate_ids = candidates
        .iter()
        .map(|candidate| candidate.id.as_str())
        .collect::<std::collections::BTreeSet<_>>();
    let golden_sample_ids_missing = golden_sample_ids
        .iter()
        .filter(|id| !candidate_ids.contains(id.as_str()))
        .cloned()
        .collect::<Vec<_>>();
    BridgeShortrunParityComparison {
        exact_counts_match: fixture == rust,
        total_delta: rust.total as isize - fixture.total as isize,
        by_type_delta,
        golden_sample_ids_seen: golden_sample_ids.len() - golden_sample_ids_missing.len(),
        golden_sample_ids_missing,
    }
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
