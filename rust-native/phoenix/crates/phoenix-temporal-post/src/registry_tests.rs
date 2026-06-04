use std::collections::BTreeMap;
use std::fs;

use crate::registry::{
    parse_temporal_anchors, scan_temporal_registry_path, TemporalRegistryScanConfig,
};

#[test]
fn parses_explicit_and_relative_temporal_anchors() {
    let mut diagnostics = BTreeMap::new();
    let anchors = parse_temporal_anchors(
        "It was May 8th, 2020 for the third time. A second later, Ryan moved.",
        "doc:a",
        "a.md",
        &mut diagnostics,
    );

    assert!(anchors.iter().any(|row| {
        row.source_class == "explicit_month_date"
            && row.normalized_value.as_deref() == Some("2020-05-08")
    }));
    assert!(anchors
        .iter()
        .any(|row| row.source_class == "recurrence_marker"));
    assert!(anchors
        .iter()
        .any(|row| row.source_class == "relative_offset"));
}

#[test]
fn keeps_anchor_id_stable_when_offsets_move() {
    let mut left_diag = BTreeMap::new();
    let mut right_diag = BTreeMap::new();
    let left = parse_temporal_anchors(
        "Ryan arrived on May 8th, 2020.",
        "doc:a",
        "a.md",
        &mut left_diag,
    );
    let right = parse_temporal_anchors(
        "Preface. Ryan arrived on May 8th, 2020.",
        "doc:a",
        "a.md",
        &mut right_diag,
    );

    let left_date = left
        .iter()
        .find(|row| row.source_class == "explicit_month_date")
        .expect("left date");
    let right_date = right
        .iter()
        .find(|row| row.source_class == "explicit_month_date")
        .expect("right date");
    assert_eq!(left_date.anchor_id, right_date.anchor_id);
    assert_ne!(left_date.range.start, right_date.range.start);
}

#[test]
fn ignores_bare_numeric_code_values_as_years() {
    let mut diagnostics = BTreeMap::new();
    let anchors = parse_temporal_anchors(
        "const WIDTH = 1000; In 2020 Ryan arrived.",
        "doc:a",
        "a.md",
        &mut diagnostics,
    );

    assert!(!anchors.iter().any(|row| row.surface == "1000"));
    assert!(anchors.iter().any(|row| {
        row.source_class == "explicit_year" && row.normalized_value.as_deref() == Some("2020")
    }));
}

#[test]
fn scans_directory_documents() {
    let root = std::env::temp_dir().join(format!(
        "phoenix-temporal-registry-test-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).expect("create temp root");
    fs::write(root.join("one.md"), "# One\n\nToday Ryan arrived.").expect("write one");
    fs::write(root.join("two.md"), "Tomorrow he leaves.").expect("write two");

    let registry = scan_temporal_registry_path(
        &root,
        &TemporalRegistryScanConfig {
            generated_at: 42,
            ..Default::default()
        },
    )
    .expect("scan registry");

    assert_eq!(registry.summary.document_count, 2);
    assert_eq!(registry.summary.anchor_count, 2);
    assert_eq!(registry.generated_at, 42);
    let _ = fs::remove_dir_all(root);
}
