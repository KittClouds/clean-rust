use std::fs;
use std::path::PathBuf;
use std::time::Instant;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Deserialize;

use crate::{
    build_document_index_shard, document_index_family_routes,
    document_index_family_routes_with_mask, document_index_shard_path,
    persist_document_index_shard, DocumentIndexFamilyMask, DocumentIndexFamilyRouteLimits,
    DocumentIndexInput, DocumentIndexRouteFamily, DocumentIndexUnit, DocumentIndexUnitKind,
    MmapDocumentIndex,
};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct GoldenFixture {
    schema_version: String,
    cases: Vec<GoldenCase>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct GoldenCase {
    note_id: String,
    text: String,
    sections: Vec<GoldenSection>,
    paragraphs: Vec<GoldenParagraph>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct GoldenSection {
    label: String,
    kind: String,
    depth: u8,
    parent: String,
    starts_at: String,
    ends_before: Option<String>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct GoldenParagraph {
    text: String,
    parent: String,
    ancestors: Vec<String>,
}

#[test]
fn shared_golden_fixture_matches_mmap_hierarchy() {
    let fixture: GoldenFixture = serde_json::from_str(include_str!(
        "../../../../../src/app/graph-rebuild/fixtures/document-hierarchy-golden.json"
    ))
    .expect("shared hierarchy fixture");
    assert_eq!(
        fixture.schema_version,
        "phoenix-document-hierarchy-golden/v1"
    );
    let root = temp_root("golden");

    for case in fixture.cases {
        let shard = build_document_index_shard(DocumentIndexInput {
            document_id: &case.note_id,
            note_id: Some(&case.note_id),
            title: &case.note_id,
            text: &case.text,
        })
        .expect("build shard");
        let write = persist_document_index_shard(&root, &shard).expect("persist shard");
        let index = MmapDocumentIndex::open_verified(&write.path, &shard.reference)
            .expect("open mapped shard");
        let units = index
            .units()
            .collect::<Result<Vec<_>, _>>()
            .expect("mapped units");

        for expected in case.sections {
            let unit = units
                .iter()
                .find(|unit| {
                    matches!(
                        unit.kind,
                        DocumentIndexUnitKind::Section | DocumentIndexUnitKind::Subsection
                    ) && unit.label == expected.label
                })
                .unwrap_or_else(|| panic!("missing section {}", expected.label));
            assert_eq!(unit.depth, expected.depth, "{} depth", expected.label);
            assert_eq!(
                parent_label(&index, unit),
                Some(expected.parent.as_str()),
                "{} parent",
                expected.label
            );
            assert_eq!(
                unit.kind,
                if expected.kind == "section" {
                    DocumentIndexUnitKind::Section
                } else {
                    DocumentIndexUnitKind::Subsection
                }
            );
            assert_eq!(
                unit.start as usize,
                case.text.find(&expected.starts_at).expect("section start")
            );
            assert_eq!(
                unit.end as usize,
                expected
                    .ends_before
                    .as_deref()
                    .map(|marker| case.text.find(marker).expect("section end"))
                    .unwrap_or(case.text.len())
            );
        }

        for expected in case.paragraphs {
            let start = case.text.find(&expected.text).expect("paragraph text") as u32;
            let unit = units
                .iter()
                .find(|unit| unit.kind == DocumentIndexUnitKind::Paragraph && unit.start == start)
                .unwrap_or_else(|| panic!("missing paragraph {}", expected.text));
            assert_eq!(parent_label(&index, unit), Some(expected.parent.as_str()));
            assert_eq!(ancestor_labels(&index, unit), expected.ancestors);
        }
        drop(units);
        drop(index);
    }
    let _ = fs::remove_dir_all(root);
}

#[test]
fn paragraph_outline_routes_keep_nearest_heading_first() {
    let fixture: GoldenFixture = serde_json::from_str(include_str!(
        "../../../../../src/app/graph-rebuild/fixtures/document-hierarchy-golden.json"
    ))
    .expect("shared hierarchy fixture");
    let case = fixture
        .cases
        .into_iter()
        .find(|case| case.note_id == "hierarchy-golden")
        .expect("nested hierarchy case");
    let shard = build_document_index_shard(DocumentIndexInput {
        document_id: &case.note_id,
        note_id: Some(&case.note_id),
        title: &case.note_id,
        text: &case.text,
    })
    .expect("build shard");
    let root = temp_root("outline-routes");
    let write = persist_document_index_shard(&root, &shard).expect("persist shard");
    let index = MmapDocumentIndex::open_verified(&write.path, &shard.reference).expect("map shard");
    let routes = paragraph_outline_routes(&index, &case.text);

    assert_eq!(
        route_targets(&routes, "Book opening."),
        ["Book", "Document"]
    );
    assert_eq!(
        route_targets(&routes, "Beat A body."),
        ["Beat A", "Scene A", "Chapter One", "Book", "Document"]
    );
    assert_eq!(
        route_targets(&routes, "Deep jump body."),
        ["Deep Jump", "Chapter Two", "Book", "Document"]
    );
    assert_eq!(
        route_targets(&routes, "Notes body."),
        ["Notes", "Appendix", "Document"]
    );
    drop(index);
    let _ = fs::remove_dir_all(root);
}

#[test]
fn family_routes_extract_entity_state_and_timeline_cues() {
    let text = "# Root\n\nAmara was captain after March 3.\n\nKai became wary on 2026-06-19.\n\nRift hesitated but refused the command.\n";
    let shard = build_document_index_shard(DocumentIndexInput {
        document_id: "family-routes",
        note_id: Some("family-routes"),
        title: "Families",
        text,
    })
    .expect("build shard");
    let root = temp_root("families");
    let write = persist_document_index_shard(&root, &shard).expect("persist shard");
    let index = MmapDocumentIndex::open_verified(&write.path, &shard.reference).expect("map shard");
    let families = document_index_family_routes(
        &index,
        text,
        DocumentIndexFamilyRouteLimits {
            max_routes_per_family: 1,
            max_targets_per_route: 1,
            max_label_chars: 32,
        },
    )
    .expect("family routes");

    let entity_state = family(&families, DocumentIndexRouteFamily::EntityState);
    let timeline = family(&families, DocumentIndexRouteFamily::Timeline);
    let tension = family(&families, DocumentIndexRouteFamily::Tension);
    assert_eq!(entity_state.route_count, 2);
    assert_eq!(entity_state.routes.len(), 1);
    assert_eq!(entity_state.routes[0].targets[0].label, "Amara");
    assert_eq!(timeline.route_count, 2);
    assert_eq!(timeline.routes.len(), 1);
    assert_eq!(timeline.routes[0].targets[0].label, "after");
    assert_eq!(tension.route_count, 1);
    assert_eq!(tension.routes.len(), 1);
    assert_eq!(tension.routes[0].targets[0].label, "hesitated");

    drop(index);
    let _ = fs::remove_dir_all(root);
}

#[test]
fn family_ablation_runs_are_deterministic_before_learned_gates() {
    let text = "# Root\n\nAmara was captain after March 3.\n\nKai became wary on 2026-06-19.\n\nRift hesitated but refused the command.\n";
    let shard = build_document_index_shard(DocumentIndexInput {
        document_id: "family-ablation",
        note_id: Some("family-ablation"),
        title: "Ablation",
        text,
    })
    .expect("build shard");
    let root = temp_root("family-ablation");
    let write = persist_document_index_shard(&root, &shard).expect("persist shard");
    let index = MmapDocumentIndex::open_verified(&write.path, &shard.reference).expect("map shard");
    let limits = DocumentIndexFamilyRouteLimits {
        max_routes_per_family: 16,
        max_targets_per_route: 8,
        max_label_chars: 32,
    };

    let baseline = ablation_counts(
        &document_index_family_routes(&index, text, limits).expect("baseline routes"),
    );
    assert_eq!(
        baseline,
        FamilyAblationCounts {
            families: 3,
            routes: 5,
            targets: 8,
        }
    );

    for (family, expected_removed) in [
        (
            DocumentIndexRouteFamily::EntityState,
            FamilyAblationCounts {
                families: 1,
                routes: 2,
                targets: 2,
            },
        ),
        (
            DocumentIndexRouteFamily::Timeline,
            FamilyAblationCounts {
                families: 1,
                routes: 2,
                targets: 3,
            },
        ),
        (
            DocumentIndexRouteFamily::Tension,
            FamilyAblationCounts {
                families: 1,
                routes: 1,
                targets: 3,
            },
        ),
    ] {
        let ablated = ablation_counts(
            &document_index_family_routes_with_mask(
                &index,
                text,
                limits,
                DocumentIndexFamilyMask::all().without(family),
            )
            .unwrap_or_else(|error| panic!("ablate {family:?}: {error}")),
        );
        assert_eq!(baseline.minus(ablated), expected_removed, "{family:?}");
    }

    drop(index);
    let _ = fs::remove_dir_all(root);
}

#[test]
fn content_address_is_timestamp_free_and_reused() {
    let root = temp_root("reuse");
    let input = DocumentIndexInput {
        document_id: "doc-1",
        note_id: Some("note-1"),
        title: "Book",
        text: "# Book\n\nOpening.",
    };
    let first = build_document_index_shard(input).expect("first shard");
    let second = build_document_index_shard(DocumentIndexInput {
        document_id: "doc-1",
        note_id: Some("note-1"),
        title: "Book",
        text: "# Book\n\nOpening.",
    })
    .expect("second shard");
    assert_eq!(first.reference, second.reference);
    assert_eq!(first.bytes, second.bytes);

    let first_write = persist_document_index_shard(&root, &first).expect("first write");
    let second_write = persist_document_index_shard(&root, &second).expect("second write");
    assert!(first_write.wrote);
    assert!(!second_write.wrote);
    assert_eq!(first_write.path, second_write.path);

    let changed = build_document_index_shard(DocumentIndexInput {
        document_id: "doc-1",
        note_id: Some("note-1"),
        title: "Book",
        text: "# Book\n\nChanged opening.",
    })
    .expect("changed shard");
    assert_ne!(first.reference.content_hash, changed.reference.content_hash);
    assert_ne!(
        first_write.path,
        document_index_shard_path(&root, &changed.reference).expect("changed path")
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn mapped_reader_rejects_truncated_shards() {
    let root = temp_root("truncated");
    fs::create_dir_all(&root).expect("temp root");
    let path = root.join("bad.pdx");
    fs::write(&path, b"PHXDIDX1").expect("truncated shard");
    assert!(MmapDocumentIndex::open(&path).is_err());
    let _ = fs::remove_dir_all(root);
}

#[test]
fn builds_and_maps_25k_note_with_bounded_bytes() {
    let mut text = String::with_capacity(26_000);
    for section in 0..32 {
        text.push_str(&format!("# Section {section}\n\n"));
        for paragraph in 0..8 {
            text.push_str(&format!(
                "Paragraph {paragraph} keeps the document hierarchy explicit while the native index remains compact and queryable.\n\n"
            ));
        }
    }
    while text.len() < 25_000 {
        text.push_str("A final paragraph extends the performance fixture without adding another representation.\n\n");
    }
    let root = temp_root("perf-25k");
    let build_started = Instant::now();
    let shard = build_document_index_shard(DocumentIndexInput {
        document_id: "doc-perf-25k",
        note_id: Some("note-perf-25k"),
        title: "Performance Fixture",
        text: &text,
    })
    .expect("build 25k shard");
    let build_elapsed = build_started.elapsed();
    assert!(build_elapsed.as_millis() < 500, "build: {build_elapsed:?}");
    assert!(shard.bytes.len() < text.len() * 2);

    let write = persist_document_index_shard(&root, &shard).expect("persist 25k shard");
    let map_started = Instant::now();
    let index =
        MmapDocumentIndex::open_verified(&write.path, &shard.reference).expect("map 25k shard");
    let map_elapsed = map_started.elapsed();
    assert!(map_elapsed.as_millis() < 250, "mmap: {map_elapsed:?}");
    assert_eq!(index.text_len() as usize, text.len());
    drop(index);
    let _ = fs::remove_dir_all(root);
}

fn parent_label<'a>(index: &'a MmapDocumentIndex, unit: &DocumentIndexUnit<'_>) -> Option<&'a str> {
    unit.parent_index
        .map(|parent| index.unit(parent).expect("parent unit").label)
}

fn ancestor_labels(index: &MmapDocumentIndex, unit: &DocumentIndexUnit<'_>) -> Vec<String> {
    let mut labels = Vec::new();
    let mut parent = unit.parent_index;
    while let Some(parent_index) = parent {
        let unit = index.unit(parent_index).expect("ancestor unit");
        labels.push(unit.label.to_owned());
        parent = unit.parent_index;
    }
    labels
}

#[derive(Debug, PartialEq, Eq)]
struct OutlineRoute {
    paragraph: String,
    targets: Vec<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct FamilyAblationCounts {
    families: usize,
    routes: usize,
    targets: usize,
}

impl FamilyAblationCounts {
    fn minus(self, other: Self) -> Self {
        Self {
            families: self.families.saturating_sub(other.families),
            routes: self.routes.saturating_sub(other.routes),
            targets: self.targets.saturating_sub(other.targets),
        }
    }
}

fn paragraph_outline_routes(index: &MmapDocumentIndex, text: &str) -> Vec<OutlineRoute> {
    index
        .units()
        .collect::<Result<Vec<_>, _>>()
        .expect("mapped units")
        .into_iter()
        .filter(|unit| unit.kind == DocumentIndexUnitKind::Paragraph)
        .map(|unit| {
            let paragraph = text[unit.start as usize..unit.end as usize].to_owned();
            OutlineRoute {
                paragraph,
                targets: ancestor_labels(index, &unit),
            }
        })
        .collect()
}

fn ablation_counts(families: &[crate::DocumentIndexFamilyRoutes]) -> FamilyAblationCounts {
    FamilyAblationCounts {
        families: families.len(),
        routes: families.iter().map(|family| family.route_count).sum(),
        targets: families.iter().map(|family| family.target_count).sum(),
    }
}

fn route_targets<'a>(routes: &'a [OutlineRoute], paragraph: &str) -> Vec<&'a str> {
    routes
        .iter()
        .find(|route| route.paragraph == paragraph)
        .unwrap_or_else(|| panic!("missing outline route for {paragraph}"))
        .targets
        .iter()
        .map(String::as_str)
        .collect()
}

fn family(
    families: &[crate::DocumentIndexFamilyRoutes],
    family: DocumentIndexRouteFamily,
) -> &crate::DocumentIndexFamilyRoutes {
    families
        .iter()
        .find(|routes| routes.family == family)
        .unwrap_or_else(|| panic!("missing {family:?} family"))
}

fn temp_root(label: &str) -> PathBuf {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    std::env::temp_dir().join(format!(
        "phoenix-document-index-{label}-{}-{stamp}",
        std::process::id()
    ))
}
