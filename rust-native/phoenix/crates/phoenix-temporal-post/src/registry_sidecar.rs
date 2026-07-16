use std::collections::BTreeMap;

use hashbrown::HashMap;
use phoenix_semantic_v2::{
    TemporalAnchorId, TemporalAnchorRecord, TemporalAxisId, TemporalAxisKind, TemporalAxisRecord,
    TemporalCompilerSummary, TemporalScopeSidecar, TemporalTimexId, TemporalTimexRecord,
};
use phoenix_types::{BiTemporalWindow, ScopeKey};

use crate::registry::{TemporalRegistry, TemporalRegistryAnchor};

const DAY_MS: i64 = 86_400_000;

pub fn build_temporal_registry_sidecar(registry: &TemporalRegistry) -> TemporalScopeSidecar {
    let mut axes = Vec::<TemporalAxisRecord>::with_capacity(registry.documents.len());
    let mut axis_by_doc = HashMap::<&str, TemporalAxisId>::with_capacity(registry.documents.len());
    for doc in &registry.documents {
        let axis_id = TemporalAxisId(format!("axis:registry:{}:world", doc.document_id));
        axis_by_doc.insert(doc.document_id.as_str(), axis_id.clone());
        axes.push(TemporalAxisRecord {
            axis_id,
            document_id: doc.document_id.clone(),
            kind: TemporalAxisKind::World,
            label: format!("registry world: {}", doc.title),
            evidence_refs: vec![format!("registry:{}", doc.relative_path)],
        });
    }

    let mut timex_records = Vec::<TemporalTimexRecord>::with_capacity(registry.anchors.len());
    let mut anchors = Vec::<TemporalAnchorRecord>::with_capacity(registry.anchors.len());
    for anchor in &registry.anchors {
        let axis_id = axis_by_doc
            .get(anchor.document_id.as_str())
            .cloned()
            .unwrap_or_else(|| {
                TemporalAxisId(format!("axis:registry:{}:world", anchor.document_id))
            });
        let timex_id = timex_id_for(anchor);
        let temporal = temporal_for(anchor, registry.generated_at);
        let evidence_refs = evidence_refs(anchor);

        timex_records.push(TemporalTimexRecord {
            timex_id: timex_id.clone(),
            document_id: anchor.document_id.clone(),
            proposition_id: None,
            sentence_index: anchor.sentence_index,
            label: anchor.surface.clone(),
            normalized_value: anchor.normalized_value.clone(),
            range: Some(anchor.range.clone()),
            axis_id: axis_id.clone(),
            temporal: temporal.clone(),
            confidence_millis: anchor.confidence_millis,
            source_class: anchor.source_class.clone(),
            evidence_refs: evidence_refs.clone(),
        });
        anchors.push(TemporalAnchorRecord {
            anchor_id: TemporalAnchorId(anchor.anchor_id.clone()),
            document_id: anchor.document_id.clone(),
            proposition_id: None,
            event_id: None,
            canonical_event_id: None,
            timex_id: Some(timex_id),
            reference_event_id: None,
            canonical_reference_event_id: None,
            axis_id,
            label: anchor.surface.clone(),
            anchor_kind: anchor_kind(anchor, &temporal),
            temporal,
            confidence_millis: anchor.confidence_millis,
            source_class: anchor.source_class.clone(),
            evidence_refs,
        });
    }

    TemporalScopeSidecar {
        scope: ScopeKey {
            folder_id: Some(registry.scope_key.clone()),
            folder_path: Some(registry.root.clone()),
            ..ScopeKey::default()
        },
        scope_key: registry.scope_key.clone(),
        scope_ord: None,
        session_id: None,
        updated_at: registry.generated_at,
        generation: 1,
        timex_records,
        anchors,
        axes,
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

fn timex_id_for(anchor: &TemporalRegistryAnchor) -> TemporalTimexId {
    let suffix = anchor
        .anchor_id
        .strip_prefix("tanchor:")
        .unwrap_or(anchor.anchor_id.as_str());
    TemporalTimexId(format!("timex:registry:{suffix}"))
}

fn temporal_for(anchor: &TemporalRegistryAnchor, recorded_from: i64) -> BiTemporalWindow {
    let (valid_from, valid_to) = anchor
        .normalized_value
        .as_deref()
        .and_then(calendar_window)
        .unwrap_or((None, None));
    BiTemporalWindow {
        valid_from,
        valid_to,
        recorded_from: Some(recorded_from),
        recorded_to: None,
    }
}

fn calendar_window(value: &str) -> Option<(Option<i64>, Option<i64>)> {
    if let Some((year, month, day)) = parse_ymd(value) {
        let start = date_epoch_ms(year, month, day)?;
        return Some((Some(start), Some(start + DAY_MS - 1)));
    }
    let year = parse_year(value)?;
    let start = date_epoch_ms(year, 1, 1)?;
    let end = date_epoch_ms(year + 1, 1, 1)? - 1;
    Some((Some(start), Some(end)))
}

fn parse_ymd(value: &str) -> Option<(i32, u32, u32)> {
    if value.len() != 10 {
        return None;
    }
    let bytes = value.as_bytes();
    if bytes[4] != b'-' || bytes[7] != b'-' {
        return None;
    }
    let year = value[0..4].parse::<i32>().ok()?;
    let month = value[5..7].parse::<u32>().ok()?;
    let day = value[8..10].parse::<u32>().ok()?;
    valid_date(year, month, day).then_some((year, month, day))
}

fn parse_year(value: &str) -> Option<i32> {
    if value.len() == 4 && value.as_bytes().iter().all(u8::is_ascii_digit) {
        let year = value.parse::<i32>().ok()?;
        return (1000..=2999).contains(&year).then_some(year);
    }
    None
}

fn date_epoch_ms(year: i32, month: u32, day: u32) -> Option<i64> {
    valid_date(year, month, day).then(|| days_from_civil(year, month, day) * DAY_MS)
}

fn valid_date(year: i32, month: u32, day: u32) -> bool {
    (1000..=3000).contains(&year)
        && (1..=12).contains(&month)
        && (1..=days_in_month(year, month)).contains(&day)
}

fn days_in_month(year: i32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if leap_year(year) => 29,
        2 => 28,
        _ => 0,
    }
}

fn leap_year(year: i32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

fn days_from_civil(year: i32, month: u32, day: u32) -> i64 {
    let y = year - i32::from(month <= 2);
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let month_shifted = month as i32 + if month > 2 { -3 } else { 9 };
    let doy = (153 * month_shifted + 2) / 5 + day as i32 - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    i64::from(era * 146_097 + doe - 719_468)
}

fn evidence_refs(anchor: &TemporalRegistryAnchor) -> Vec<String> {
    vec![
        format!(
            "registry:{}:{}..{}",
            anchor.relative_path, anchor.range.start, anchor.range.end
        ),
        format!("stability:{}", anchor.stability_key),
    ]
}

fn anchor_kind(anchor: &TemporalRegistryAnchor, temporal: &BiTemporalWindow) -> String {
    if anchor.source_class.starts_with("explicit") && temporal.valid_from.is_some() {
        "explicit_timex".to_owned()
    } else if anchor.source_class.starts_with("explicit") {
        "partial_timex".to_owned()
    } else if anchor.source_class.starts_with("deictic") {
        "deictic_timex".to_owned()
    } else if anchor.source_class == "recurrence_marker" {
        "recurrence_marker".to_owned()
    } else {
        "relative_anchor".to_owned()
    }
}

fn summary_for(registry: &TemporalRegistry) -> TemporalCompilerSummary {
    let mut axis_counts = BTreeMap::<String, usize>::new();
    axis_counts.insert("world".to_owned(), registry.documents.len());
    TemporalCompilerSummary {
        timex_count: registry.anchors.len(),
        anchor_count: registry.anchors.len(),
        axis_counts,
        source_class_counts: registry.summary.source_class_counts.clone(),
        ..TemporalCompilerSummary::default()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use crate::registry::parse_temporal_anchors;

    use super::*;

    #[test]
    fn exact_dates_project_to_epoch_windows() {
        let registry =
            registry_from_text("Ryan arrived on May 8th, 2020. A second later, he left.");
        let sidecar = build_temporal_registry_sidecar(&registry);
        let date = sidecar
            .timex_records
            .iter()
            .find(|row| row.source_class == "explicit_month_date")
            .expect("date timex");

        assert_eq!(sidecar.summary.timex_count, registry.summary.anchor_count);
        assert_eq!(date.temporal.valid_from, Some(1_588_896_000_000));
        assert_eq!(date.temporal.valid_to, Some(1_588_982_399_999));
        assert_eq!(date.temporal.recorded_from, Some(1234));
        assert_eq!(sidecar.axes.len(), 1);
    }

    #[test]
    fn relative_anchors_stay_unresolved_but_receipted() {
        let registry = registry_from_text("Today Ryan arrived. A second later, he left.");
        let sidecar = build_temporal_registry_sidecar(&registry);
        let relative = sidecar
            .anchors
            .iter()
            .find(|row| row.source_class == "relative_offset")
            .expect("relative anchor");

        assert_eq!(relative.temporal.valid_from, None);
        assert_eq!(relative.temporal.recorded_from, Some(1234));
        assert!(relative.timex_id.is_some());
        assert!(relative
            .evidence_refs
            .iter()
            .any(|value| value.starts_with("stability:")));
    }

    fn registry_from_text(text: &str) -> TemporalRegistry {
        let mut diagnostics = BTreeMap::new();
        let document_id = "tdoc:test".to_owned();
        let anchors = parse_temporal_anchors(text, &document_id, "test.md", &mut diagnostics);
        TemporalRegistry {
            registry_id: "tregistry:test".to_owned(),
            root: "test-root".to_owned(),
            scope_key: "tscope:test".to_owned(),
            generated_at: 1234,
            parser_version: "test".to_owned(),
            documents: vec![crate::registry::TemporalRegistryDocument {
                document_id,
                relative_path: "test.md".to_owned(),
                title: "test".to_owned(),
                text_len: text.len(),
                fingerprint: "tfp:test".to_owned(),
                anchor_count: anchors.len(),
            }],
            summary: crate::registry::TemporalRegistrySummary {
                document_count: 1,
                anchor_count: anchors.len(),
                explicit_anchor_count: anchors
                    .iter()
                    .filter(|anchor| anchor.source_class.starts_with("explicit"))
                    .count(),
                relative_anchor_count: anchors
                    .iter()
                    .filter(|anchor| !anchor.source_class.starts_with("explicit"))
                    .count(),
                source_class_counts: BTreeMap::new(),
                diagnostics,
            },
            anchors,
        }
    }
}
