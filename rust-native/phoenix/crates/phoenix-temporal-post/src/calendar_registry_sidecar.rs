use std::collections::BTreeMap;

use phoenix_semantic_v2::{
    TemporalAnchorId, TemporalAnchorRecord, TemporalAxisId, TemporalAxisKind, TemporalAxisRecord,
    TemporalCompilerSummary, TemporalScopeSidecar, TemporalTimexId, TemporalTimexRecord,
};
use phoenix_types::{BiTemporalWindow, ScopeKey};
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CalendarRegistrySnapshot {
    pub schema_version: String,
    pub id: String,
    pub built_at: i64,
    pub calendar: CalendarRegistryCalendarReceipt,
    #[serde(default)]
    pub scope: Option<CalendarRegistryScope>,
    #[serde(default)]
    pub anchors: Vec<CalendarRegistryAnchor>,
    #[serde(default)]
    pub summary: CalendarRegistrySummary,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CalendarRegistryCalendarReceipt {
    pub id: String,
    pub name: String,
    pub fingerprint: String,
    pub mode: String,
    pub created_from: String,
    pub month_count: usize,
    pub weekday_count: usize,
    pub has_year_zero: bool,
    #[serde(default)]
    pub default_era_id: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CalendarRegistryScope {
    pub kind: Option<String>,
    pub scope_id: Option<String>,
    pub narrative_id: Option<String>,
    pub folder_id: Option<String>,
    #[serde(default)]
    pub note_ids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CalendarRegistryAnchor {
    pub id: String,
    pub kind: String,
    pub source_id: String,
    pub source_label: String,
    pub calendar_id: String,
    pub calendar_fingerprint: String,
    pub date_key: String,
    #[serde(default)]
    pub end_date_key: Option<String>,
    pub normalized_value: String,
    pub display_date: String,
    pub granularity: String,
    #[serde(default)]
    pub ordinal: i64,
    #[serde(default)]
    pub end_ordinal: Option<i64>,
    #[serde(default)]
    pub real_epoch_ms: Option<i64>,
    #[serde(default)]
    pub real_interval_end_ms: Option<i64>,
    #[serde(default)]
    pub note_id: Option<String>,
    #[serde(default)]
    pub folder_id: Option<String>,
    #[serde(default)]
    pub narrative_id: Option<String>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub confidence: f32,
    #[serde(default)]
    pub evidence_refs: Vec<String>,
    #[serde(default)]
    pub attributes: BTreeMap<String, Value>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CalendarRegistrySummary {
    #[serde(default)]
    pub anchor_count: usize,
    #[serde(default)]
    pub event_anchor_count: usize,
    #[serde(default)]
    pub folder_anchor_count: usize,
    #[serde(default)]
    pub period_anchor_count: usize,
    #[serde(default)]
    pub marker_anchor_count: usize,
    #[serde(default)]
    pub real_compatible_anchor_count: usize,
    #[serde(default)]
    pub custom_ordinal_anchor_count: usize,
    #[serde(default)]
    pub source_kind_counts: BTreeMap<String, usize>,
    #[serde(default)]
    pub diagnostics: BTreeMap<String, usize>,
}

pub fn build_calendar_registry_temporal_sidecar(
    registry: &CalendarRegistrySnapshot,
) -> TemporalScopeSidecar {
    let scope_key = scope_key(registry);
    let axis_id = TemporalAxisId(format!("axis:calendar:{}:world", registry.calendar.id));
    let axis = TemporalAxisRecord {
        axis_id: axis_id.clone(),
        document_id: scope_key.clone(),
        kind: TemporalAxisKind::World,
        label: format!("calendar world: {}", registry.calendar.name),
        evidence_refs: vec![
            format!("calendar:{}", registry.calendar.id),
            format!("calendarFingerprint:{}", registry.calendar.fingerprint),
        ],
    };

    let mut timex_records = Vec::with_capacity(registry.anchors.len());
    let mut anchors = Vec::with_capacity(registry.anchors.len());
    for anchor in &registry.anchors {
        let document_id = document_id_for(registry, anchor);
        let temporal = temporal_for(registry, anchor);
        let timex_id = TemporalTimexId(format!("timex:calendar:{}", stable_suffix(&anchor.id)));
        let evidence_refs = evidence_refs(registry, anchor);
        timex_records.push(TemporalTimexRecord {
            timex_id: timex_id.clone(),
            document_id: document_id.clone(),
            proposition_id: None,
            sentence_index: 0,
            label: anchor.display_date.clone(),
            normalized_value: Some(anchor.normalized_value.clone()),
            range: None,
            axis_id: axis_id.clone(),
            temporal: temporal.clone(),
            confidence_millis: confidence_millis(anchor.confidence),
            source_class: source_class(anchor),
            evidence_refs: evidence_refs.clone(),
        });
        anchors.push(TemporalAnchorRecord {
            anchor_id: TemporalAnchorId(format!("tanchor:calendar:{}", stable_suffix(&anchor.id))),
            document_id,
            proposition_id: None,
            event_id: (anchor.kind == "user_calendar_event").then(|| anchor.source_id.clone()),
            canonical_event_id: None,
            timex_id: Some(timex_id),
            reference_event_id: None,
            canonical_reference_event_id: None,
            axis_id: axis_id.clone(),
            label: anchor.source_label.clone(),
            anchor_kind: anchor_kind(registry, anchor),
            temporal,
            confidence_millis: confidence_millis(anchor.confidence),
            source_class: source_class(anchor),
            evidence_refs,
        });
    }

    TemporalScopeSidecar {
        scope: ScopeKey {
            narrative_id: registry
                .scope
                .as_ref()
                .and_then(|scope| scope.narrative_id.clone()),
            folder_id: registry
                .scope
                .as_ref()
                .and_then(|scope| scope.folder_id.clone()),
            folder_path: registry
                .scope
                .as_ref()
                .and_then(|scope| scope.scope_id.clone()),
            ..ScopeKey::default()
        },
        scope_key,
        scope_ord: None,
        session_id: None,
        updated_at: registry.built_at,
        generation: 1,
        timex_records,
        anchors,
        axes: vec![axis],
        reference_edges: Vec::new(),
        claim_atoms: Vec::new(),
        belief_atoms: Vec::new(),
        constraints: Vec::new(),
        intervals: Vec::new(),
        timeline_segments: Vec::new(),
        conflicts: Vec::new(),
        gaps: Vec::new(),
        memory_cards: Vec::new(),
        belief_cards: Vec::new(),
        summary: summary_for(registry),
    }
}

fn temporal_for(
    registry: &CalendarRegistrySnapshot,
    anchor: &CalendarRegistryAnchor,
) -> BiTemporalWindow {
    let (valid_from, valid_to) = if registry.calendar.mode == "realEpochCompatible" {
        (anchor.real_epoch_ms, anchor.real_interval_end_ms)
    } else {
        (None, None)
    };
    BiTemporalWindow {
        valid_from,
        valid_to,
        recorded_from: Some(registry.built_at),
        recorded_to: None,
    }
}

fn summary_for(registry: &CalendarRegistrySnapshot) -> TemporalCompilerSummary {
    let mut axis_counts = BTreeMap::new();
    let mut source_class_counts = BTreeMap::new();
    axis_counts.insert("calendar_world".to_owned(), 1);
    for anchor in &registry.anchors {
        *source_class_counts.entry(source_class(anchor)).or_default() += 1;
    }
    TemporalCompilerSummary {
        timex_count: registry.anchors.len(),
        anchor_count: registry.anchors.len(),
        axis_counts,
        source_class_counts,
        ..TemporalCompilerSummary::default()
    }
}

fn evidence_refs(
    registry: &CalendarRegistrySnapshot,
    anchor: &CalendarRegistryAnchor,
) -> Vec<String> {
    let mut refs = Vec::with_capacity(anchor.evidence_refs.len() + 4);
    refs.extend(anchor.evidence_refs.iter().cloned());
    refs.push(format!("calendarRegistry:{}", registry.id));
    refs.push(format!("calendar:{}", registry.calendar.id));
    refs.push(format!("dateKey:{}", anchor.date_key));
    refs.push(format!("ordinal:{}", anchor.ordinal));
    refs
}

fn source_class(anchor: &CalendarRegistryAnchor) -> String {
    format!("calendar_registry:{}", anchor.kind)
}

fn anchor_kind(registry: &CalendarRegistrySnapshot, anchor: &CalendarRegistryAnchor) -> String {
    if anchor.kind == "calendar_now_marker" {
        "calendar_now_marker".to_owned()
    } else if registry.calendar.mode == "realEpochCompatible" && anchor.real_epoch_ms.is_some() {
        "calendar_epoch_anchor".to_owned()
    } else {
        "calendar_ordinal_anchor".to_owned()
    }
}

fn document_id_for(registry: &CalendarRegistrySnapshot, anchor: &CalendarRegistryAnchor) -> String {
    anchor
        .note_id
        .clone()
        .or_else(|| anchor.folder_id.clone())
        .or_else(|| {
            registry
                .scope
                .as_ref()
                .and_then(|scope| scope.scope_id.clone())
        })
        .unwrap_or_else(|| registry.calendar.id.clone())
}

fn scope_key(registry: &CalendarRegistrySnapshot) -> String {
    registry
        .scope
        .as_ref()
        .and_then(|scope| scope.scope_id.clone())
        .unwrap_or_else(|| format!("calendar:{}", registry.calendar.id))
}

fn confidence_millis(confidence: f32) -> u32 {
    (confidence.clamp(0.0, 1.0) * 1000.0).round() as u32
}

fn stable_suffix(value: &str) -> &str {
    value.strip_prefix("calendar-anchor:").unwrap_or(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn calendar_registry_projects_epoch_and_ordinal_receipts() {
        let mut registry = registry("realEpochCompatible");
        registry.anchors[0].real_epoch_ms = Some(1_588_896_000_000);
        registry.anchors[0].real_interval_end_ms = Some(1_588_982_399_999);
        let sidecar = build_calendar_registry_temporal_sidecar(&registry);

        assert_eq!(sidecar.axes.len(), 1);
        assert_eq!(sidecar.timex_records.len(), 1);
        assert_eq!(sidecar.anchors.len(), 1);
        assert_eq!(sidecar.summary.timex_count, 1);
        assert_eq!(sidecar.anchors[0].event_id.as_deref(), Some("event-1"));
        assert_eq!(sidecar.anchors[0].anchor_kind, "calendar_epoch_anchor");
        assert_eq!(
            sidecar.anchors[0].temporal.valid_from,
            Some(1_588_896_000_000)
        );
        assert!(sidecar.anchors[0]
            .evidence_refs
            .iter()
            .any(|value| value == "ordinal:0"));
    }

    #[test]
    fn custom_calendar_keeps_ordinals_without_fake_epoch() {
        let sidecar = build_calendar_registry_temporal_sidecar(&registry("customOrdinal"));

        assert_eq!(sidecar.anchors[0].anchor_kind, "calendar_ordinal_anchor");
        assert_eq!(sidecar.anchors[0].temporal.valid_from, None);
        assert_eq!(sidecar.anchors[0].temporal.recorded_from, Some(99));
    }

    fn registry(mode: &str) -> CalendarRegistrySnapshot {
        CalendarRegistrySnapshot {
            schema_version: "phoenix-calendar-registry/v1".to_owned(),
            id: "calendar-registry:test".to_owned(),
            built_at: 99,
            calendar: CalendarRegistryCalendarReceipt {
                id: "calendar:test".to_owned(),
                name: "Test Calendar".to_owned(),
                fingerprint: "calendar:fingerprint:test".to_owned(),
                mode: mode.to_owned(),
                created_from: "manual".to_owned(),
                month_count: 12,
                weekday_count: 7,
                has_year_zero: false,
                default_era_id: "era-1".to_owned(),
            },
            scope: Some(CalendarRegistryScope {
                kind: Some("note".to_owned()),
                scope_id: Some("note:one".to_owned()),
                note_ids: vec!["note-1".to_owned()],
                ..CalendarRegistryScope::default()
            }),
            anchors: vec![CalendarRegistryAnchor {
                id: "calendar-anchor:event-1".to_owned(),
                kind: "user_calendar_event".to_owned(),
                source_id: "event-1".to_owned(),
                source_label: "Festival".to_owned(),
                calendar_id: "calendar:test".to_owned(),
                calendar_fingerprint: "calendar:fingerprint:test".to_owned(),
                date_key: "cal:calendar:test|era:era-1|y:1|m:0|d:0".to_owned(),
                end_date_key: None,
                normalized_value: "CAL:calendar:test:cal:calendar:test|era:era-1|y:1|m:0|d:0"
                    .to_owned(),
                display_date: "Month 1 1, 1 CE".to_owned(),
                granularity: "day".to_owned(),
                ordinal: 0,
                end_ordinal: None,
                real_epoch_ms: None,
                real_interval_end_ms: None,
                note_id: Some("note-1".to_owned()),
                folder_id: None,
                narrative_id: None,
                description: None,
                status: None,
                confidence: 0.91,
                evidence_refs: vec!["calendar:event:event-1".to_owned()],
                attributes: BTreeMap::new(),
            }],
            summary: CalendarRegistrySummary {
                anchor_count: 1,
                event_anchor_count: 1,
                custom_ordinal_anchor_count: usize::from(mode == "customOrdinal"),
                real_compatible_anchor_count: usize::from(mode == "realEpochCompatible"),
                source_kind_counts: BTreeMap::from([(
                    "calendar_registry:user_calendar_event".to_owned(),
                    1,
                )]),
                ..CalendarRegistrySummary::default()
            },
        }
    }
}
