use std::time::Instant;

use phoenix_document_index::{
    build_document_index_shard, document_index_family_routes, persist_document_index_shard,
    DocumentIndexFamilyRouteLimits, DocumentIndexFamilyRoutes, DocumentIndexFamilyTargetKind,
    DocumentIndexInput, DocumentIndexRouteFamily, DocumentIndexShardRef, DocumentIndexUnit,
    DocumentIndexUnitKind, MmapDocumentIndex,
};
use serde::{Deserialize, Serialize};

const DEFAULT_MAX_UNITS: usize = 256;
const DEFAULT_MAX_ROUTES: usize = 96;
const DEFAULT_MAX_ROUTE_TARGETS: usize = 8;
const DEFAULT_MAX_FAMILY_ROUTES: usize = 96;
const DEFAULT_MAX_FAMILY_TARGETS: usize = 8;
const DEFAULT_MAX_LABEL_CHARS: usize = 120;
const HARD_MAX_UNITS: usize = 2_048;
const HARD_MAX_ROUTES: usize = 512;
const HARD_MAX_ROUTE_TARGETS: usize = 16;
const HARD_MAX_FAMILY_ROUTES: usize = 512;
const HARD_MAX_FAMILY_TARGETS: usize = 16;
const HARD_MAX_LABEL_CHARS: usize = 240;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopDocumentIndexReadRequest {
    pub document_id: String,
    pub note_id: Option<String>,
    pub title: Option<String>,
    pub text: String,
    pub max_units: Option<usize>,
    pub max_routes: Option<usize>,
    pub max_route_targets: Option<usize>,
    pub max_family_routes: Option<usize>,
    pub max_family_targets: Option<usize>,
    pub max_label_chars: Option<usize>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopDocumentIndexReadResponse {
    pub schema_version: &'static str,
    pub source: &'static str,
    pub reference: DocumentIndexShardRef,
    pub receipt: DesktopDocumentIndexReadReceipt,
    pub units: Vec<DesktopDocumentIndexUnit>,
    pub outline_routes: Vec<DesktopDocumentOutlineRoute>,
    pub families: Vec<DesktopDocumentFamilyRoutes>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopDocumentIndexReadReceipt {
    pub bounded: bool,
    pub mmap: bool,
    pub cache_reused: bool,
    pub text_bytes: usize,
    pub shard_bytes: u64,
    pub unit_count: u32,
    pub units_returned: usize,
    pub units_truncated: usize,
    pub route_count: usize,
    pub routes_returned: usize,
    pub routes_truncated: usize,
    pub family_route_count: usize,
    pub family_routes_returned: usize,
    pub family_routes_truncated: usize,
    pub family_target_count: usize,
    pub family_targets_returned: usize,
    pub family_targets_truncated: usize,
    pub max_units: usize,
    pub max_routes: usize,
    pub max_route_targets: usize,
    pub max_family_routes: usize,
    pub max_family_targets: usize,
    pub max_label_chars: usize,
    pub build_ms: u64,
    pub persist_ms: u64,
    pub mmap_ms: u64,
    pub read_ms: u64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopDocumentIndexUnit {
    pub index: u32,
    pub kind: &'static str,
    pub depth: u8,
    pub parent_index: Option<u32>,
    pub start: u32,
    pub end: u32,
    pub ordinal: u32,
    pub label: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopDocumentOutlineRoute {
    pub paragraph_index: u32,
    pub start: u32,
    pub end: u32,
    pub targets: Vec<DesktopDocumentOutlineTarget>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopDocumentOutlineTarget {
    pub index: u32,
    pub kind: &'static str,
    pub depth: u8,
    pub label: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopDocumentFamilyRoutes {
    pub family: &'static str,
    pub route_count: usize,
    pub routes_returned: usize,
    pub routes_truncated: usize,
    pub target_count: usize,
    pub targets_returned: usize,
    pub targets_truncated: usize,
    pub routes: Vec<DesktopDocumentFamilyRoute>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopDocumentFamilyRoute {
    pub paragraph_index: u32,
    pub start: u32,
    pub end: u32,
    pub targets: Vec<DesktopDocumentFamilyTarget>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopDocumentFamilyTarget {
    pub kind: &'static str,
    pub start: u32,
    pub end: u32,
    pub label: String,
}

pub fn read_document_index(
    request: DesktopDocumentIndexReadRequest,
) -> Result<DesktopDocumentIndexReadResponse, String> {
    let document_id = request.document_id.trim();
    if document_id.is_empty() {
        return Err("documentIndex:read requires documentId".to_owned());
    }
    let title = request
        .title
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or(document_id);
    let limits = ReadLimits::from_request(&request);
    let build_started = Instant::now();
    let shard = build_document_index_shard(DocumentIndexInput {
        document_id,
        note_id: request.note_id.as_deref(),
        title,
        text: &request.text,
    })
    .map_err(|error| error.to_string())?;
    let build_ms = elapsed_ms(build_started);

    let cache_root = std::env::temp_dir().join("phoenix-tauri-document-index");
    let persist_started = Instant::now();
    let write =
        persist_document_index_shard(&cache_root, &shard).map_err(|error| error.to_string())?;
    let persist_ms = elapsed_ms(persist_started);

    let mmap_started = Instant::now();
    let index = MmapDocumentIndex::open_verified(&write.path, &shard.reference)
        .map_err(|error| error.to_string())?;
    let mmap_ms = elapsed_ms(mmap_started);

    let read_started = Instant::now();
    let bounded = read_bounded_index(&index, &limits)?;
    let families = desktop_families(
        document_index_family_routes(
            &index,
            &request.text,
            DocumentIndexFamilyRouteLimits {
                max_routes_per_family: limits.max_family_routes,
                max_targets_per_route: limits.max_family_targets,
                max_label_chars: limits.max_label_chars,
            },
        )
        .map_err(|error| error.to_string())?,
    );
    let family_counts = family_counts(&families);
    let read_ms = elapsed_ms(read_started);

    Ok(DesktopDocumentIndexReadResponse {
        schema_version: "phoenix-document-index-read/v1",
        source: "tauri-editor-mmap",
        reference: shard.reference.clone(),
        receipt: DesktopDocumentIndexReadReceipt {
            bounded: bounded.units.len() < bounded.unit_count
                || bounded.routes.len() < bounded.route_count
                || family_counts.routes_returned < family_counts.route_count
                || family_counts.targets_returned < family_counts.target_count,
            mmap: true,
            cache_reused: !write.wrote,
            text_bytes: request.text.len(),
            shard_bytes: shard.reference.byte_len,
            unit_count: shard.reference.unit_count,
            units_returned: bounded.units.len(),
            units_truncated: bounded.unit_count.saturating_sub(bounded.units.len()),
            route_count: bounded.route_count,
            routes_returned: bounded.routes.len(),
            routes_truncated: bounded.route_count.saturating_sub(bounded.routes.len()),
            family_route_count: family_counts.route_count,
            family_routes_returned: family_counts.routes_returned,
            family_routes_truncated: family_counts
                .route_count
                .saturating_sub(family_counts.routes_returned),
            family_target_count: family_counts.target_count,
            family_targets_returned: family_counts.targets_returned,
            family_targets_truncated: family_counts
                .target_count
                .saturating_sub(family_counts.targets_returned),
            max_units: limits.max_units,
            max_routes: limits.max_routes,
            max_route_targets: limits.max_route_targets,
            max_family_routes: limits.max_family_routes,
            max_family_targets: limits.max_family_targets,
            max_label_chars: limits.max_label_chars,
            build_ms,
            persist_ms,
            mmap_ms,
            read_ms,
        },
        units: bounded.units,
        outline_routes: bounded.routes,
        families,
    })
}

struct ReadLimits {
    max_units: usize,
    max_routes: usize,
    max_route_targets: usize,
    max_family_routes: usize,
    max_family_targets: usize,
    max_label_chars: usize,
}

impl ReadLimits {
    fn from_request(request: &DesktopDocumentIndexReadRequest) -> Self {
        Self {
            max_units: clamp_limit(request.max_units, DEFAULT_MAX_UNITS, HARD_MAX_UNITS),
            max_routes: clamp_limit(request.max_routes, DEFAULT_MAX_ROUTES, HARD_MAX_ROUTES),
            max_route_targets: clamp_limit(
                request.max_route_targets,
                DEFAULT_MAX_ROUTE_TARGETS,
                HARD_MAX_ROUTE_TARGETS,
            ),
            max_family_routes: clamp_limit(
                request.max_family_routes,
                DEFAULT_MAX_FAMILY_ROUTES,
                HARD_MAX_FAMILY_ROUTES,
            ),
            max_family_targets: clamp_limit(
                request.max_family_targets,
                DEFAULT_MAX_FAMILY_TARGETS,
                HARD_MAX_FAMILY_TARGETS,
            ),
            max_label_chars: clamp_limit(
                request.max_label_chars,
                DEFAULT_MAX_LABEL_CHARS,
                HARD_MAX_LABEL_CHARS,
            ),
        }
    }
}

struct FamilyCounts {
    route_count: usize,
    routes_returned: usize,
    target_count: usize,
    targets_returned: usize,
}

struct BoundedIndexRead {
    unit_count: usize,
    route_count: usize,
    units: Vec<DesktopDocumentIndexUnit>,
    routes: Vec<DesktopDocumentOutlineRoute>,
}

fn read_bounded_index(
    index: &MmapDocumentIndex,
    limits: &ReadLimits,
) -> Result<BoundedIndexRead, String> {
    let unit_capacity = limits.max_units.min(index.unit_count() as usize);
    let mut read = BoundedIndexRead {
        unit_count: 0,
        route_count: 0,
        units: Vec::with_capacity(unit_capacity),
        routes: Vec::with_capacity(limits.max_routes.min(unit_capacity)),
    };

    for unit in index.units() {
        let unit = unit.map_err(|error| error.to_string())?;
        read.unit_count += 1;
        if read.units.len() < limits.max_units {
            read.units.push(desktop_unit(&unit, limits.max_label_chars));
        }
        if unit.kind == DocumentIndexUnitKind::Paragraph {
            read.route_count += 1;
            if read.routes.len() < limits.max_routes {
                read.routes.push(DesktopDocumentOutlineRoute {
                    paragraph_index: unit.index,
                    start: unit.start,
                    end: unit.end,
                    targets: outline_targets(index, &unit, limits)?,
                });
            }
        }
    }

    Ok(read)
}

fn desktop_families(families: Vec<DocumentIndexFamilyRoutes>) -> Vec<DesktopDocumentFamilyRoutes> {
    families
        .into_iter()
        .map(|family| {
            let targets_returned = family
                .routes
                .iter()
                .map(|route| route.targets.len())
                .sum::<usize>();
            DesktopDocumentFamilyRoutes {
                family: route_family_name(family.family),
                route_count: family.route_count,
                routes_returned: family.routes.len(),
                routes_truncated: family.route_count.saturating_sub(family.routes.len()),
                target_count: family.target_count,
                targets_returned,
                targets_truncated: family.target_count.saturating_sub(targets_returned),
                routes: family
                    .routes
                    .into_iter()
                    .map(|route| DesktopDocumentFamilyRoute {
                        paragraph_index: route.paragraph_index,
                        start: route.start,
                        end: route.end,
                        targets: route
                            .targets
                            .into_iter()
                            .map(|target| DesktopDocumentFamilyTarget {
                                kind: family_target_kind_name(target.kind),
                                start: target.start,
                                end: target.end,
                                label: target.label,
                            })
                            .collect(),
                    })
                    .collect(),
            }
        })
        .collect()
}

fn family_counts(families: &[DesktopDocumentFamilyRoutes]) -> FamilyCounts {
    families.iter().fold(
        FamilyCounts {
            route_count: 0,
            routes_returned: 0,
            target_count: 0,
            targets_returned: 0,
        },
        |mut counts, family| {
            counts.route_count += family.route_count;
            counts.routes_returned += family.routes_returned;
            counts.target_count += family.target_count;
            counts.targets_returned += family.targets_returned;
            counts
        },
    )
}

fn outline_targets(
    index: &MmapDocumentIndex,
    unit: &DocumentIndexUnit<'_>,
    limits: &ReadLimits,
) -> Result<Vec<DesktopDocumentOutlineTarget>, String> {
    let mut targets = Vec::with_capacity(limits.max_route_targets);
    let mut parent = unit.parent_index;
    while let Some(parent_index) = parent {
        if targets.len() >= limits.max_route_targets {
            break;
        }
        let parent_unit = index
            .unit(parent_index)
            .map_err(|error| error.to_string())?;
        targets.push(DesktopDocumentOutlineTarget {
            index: parent_unit.index,
            kind: unit_kind_name(parent_unit.kind),
            depth: parent_unit.depth,
            label: bounded_label(parent_unit.label, limits.max_label_chars),
        });
        parent = parent_unit.parent_index;
    }
    Ok(targets)
}

fn route_family_name(family: DocumentIndexRouteFamily) -> &'static str {
    family.as_str()
}

fn family_target_kind_name(kind: DocumentIndexFamilyTargetKind) -> &'static str {
    kind.as_str()
}

fn desktop_unit(unit: &DocumentIndexUnit<'_>, max_label_chars: usize) -> DesktopDocumentIndexUnit {
    DesktopDocumentIndexUnit {
        index: unit.index,
        kind: unit_kind_name(unit.kind),
        depth: unit.depth,
        parent_index: unit.parent_index,
        start: unit.start,
        end: unit.end,
        ordinal: unit.ordinal,
        label: bounded_label(unit.label, max_label_chars),
    }
}

fn unit_kind_name(kind: DocumentIndexUnitKind) -> &'static str {
    match kind {
        DocumentIndexUnitKind::Document => "document",
        DocumentIndexUnitKind::Section => "section",
        DocumentIndexUnitKind::Subsection => "subsection",
        DocumentIndexUnitKind::Paragraph => "paragraph",
    }
}

fn bounded_label(value: &str, max_chars: usize) -> String {
    if value.chars().count() <= max_chars {
        return value.to_owned();
    }
    value.chars().take(max_chars).collect()
}

fn clamp_limit(value: Option<usize>, default: usize, hard_max: usize) -> usize {
    value.unwrap_or(default).max(1).min(hard_max)
}

fn elapsed_ms(started: Instant) -> u64 {
    started.elapsed().as_millis().try_into().unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn document_index_read_returns_bounded_mmap_receipt() {
        let response = read_document_index(DesktopDocumentIndexReadRequest {
            document_id: "doc-1".to_owned(),
            note_id: Some("note-1".to_owned()),
            title: Some("Doc".to_owned()),
            text: "# Root\n\nIntro.\n\n## Scene\n\nBody.\n".to_owned(),
            max_units: Some(3),
            max_routes: Some(1),
            max_route_targets: Some(4),
            max_family_routes: Some(1),
            max_family_targets: Some(1),
            max_label_chars: Some(32),
        })
        .expect("read document index");

        assert_eq!(response.schema_version, "phoenix-document-index-read/v1");
        assert!(response.receipt.mmap);
        assert!(response.receipt.bounded);
        assert_eq!(response.receipt.units_returned, 3);
        assert_eq!(response.receipt.routes_returned, 1);
        assert_eq!(response.units[0].kind, "document");
        assert_eq!(response.outline_routes[0].targets[0].label, "Root");
        assert_eq!(
            response
                .families
                .iter()
                .map(|family| family.family)
                .collect::<Vec<_>>(),
            ["entityState", "timeline", "tension"]
        );
    }

    #[test]
    fn document_index_read_reuses_content_addressed_cache() {
        let request = || DesktopDocumentIndexReadRequest {
            document_id: "doc-cache".to_owned(),
            note_id: Some("note-cache".to_owned()),
            title: Some("Doc".to_owned()),
            text: "# Root\n\nIntro.\n".to_owned(),
            max_units: None,
            max_routes: None,
            max_route_targets: None,
            max_family_routes: None,
            max_family_targets: None,
            max_label_chars: None,
        };

        let _ = read_document_index(request()).expect("first read");
        let warm = read_document_index(request()).expect("warm read");

        assert!(warm.receipt.cache_reused);
        assert_eq!(warm.reference.document_id, "doc-cache");
    }

    #[test]
    fn document_index_read_returns_attention_families_without_truth_objects() {
        let response = read_document_index(DesktopDocumentIndexReadRequest {
            document_id: "doc-families".to_owned(),
            note_id: Some("note-families".to_owned()),
            title: Some("Families".to_owned()),
            text: "# Root\n\nAmara was captain after March 3.\n\nKai became wary on 2026-06-19.\n\nRift hesitated but refused the command.\n".to_owned(),
            max_units: None,
            max_routes: None,
            max_route_targets: None,
            max_family_routes: Some(1),
            max_family_targets: Some(1),
            max_label_chars: Some(32),
        })
        .expect("read document index");

        let entity_state = response
            .families
            .iter()
            .find(|family| family.family == "entityState")
            .expect("entity state family");
        let timeline = response
            .families
            .iter()
            .find(|family| family.family == "timeline")
            .expect("timeline family");
        let tension = response
            .families
            .iter()
            .find(|family| family.family == "tension")
            .expect("tension family");

        assert_eq!(entity_state.route_count, 2);
        assert_eq!(entity_state.routes_returned, 1);
        assert_eq!(entity_state.routes[0].targets[0].label, "Amara");
        assert_eq!(timeline.route_count, 2);
        assert_eq!(timeline.routes_returned, 1);
        assert_eq!(timeline.routes[0].targets[0].label, "after");
        assert_eq!(tension.route_count, 1);
        assert_eq!(tension.routes_returned, 1);
        assert_eq!(tension.routes[0].targets[0].kind, "tensionCue");
        assert_eq!(tension.routes[0].targets[0].label, "hesitated");
        assert!(response.receipt.bounded);
        assert_eq!(response.receipt.family_route_count, 5);
        assert_eq!(response.receipt.family_routes_returned, 3);
    }
}
