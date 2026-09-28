use crate::{DocumentIndexError, DocumentIndexUnitKind, MmapDocumentIndex};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DocumentIndexRouteFamily {
    EntityState,
    Tension,
    Timeline,
}

impl DocumentIndexRouteFamily {
    const fn bit(self) -> u8 {
        match self {
            Self::EntityState => 1 << 0,
            Self::Tension => 1 << 1,
            Self::Timeline => 1 << 2,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::EntityState => "entityState",
            Self::Tension => "tension",
            Self::Timeline => "timeline",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DocumentIndexFamilyMask {
    bits: u8,
}

impl DocumentIndexFamilyMask {
    pub const fn all() -> Self {
        Self {
            bits: DocumentIndexRouteFamily::EntityState.bit()
                | DocumentIndexRouteFamily::Tension.bit()
                | DocumentIndexRouteFamily::Timeline.bit(),
        }
    }

    pub const fn without(self, family: DocumentIndexRouteFamily) -> Self {
        Self {
            bits: self.bits & !family.bit(),
        }
    }

    pub const fn contains(self, family: DocumentIndexRouteFamily) -> bool {
        self.bits & family.bit() != 0
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DocumentIndexFamilyTargetKind {
    EntityMention,
    StateCue,
    TensionCue,
    Date,
    TemporalCue,
}

impl DocumentIndexFamilyTargetKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::EntityMention => "entityMention",
            Self::StateCue => "stateCue",
            Self::TensionCue => "tensionCue",
            Self::Date => "date",
            Self::TemporalCue => "temporalCue",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DocumentIndexFamilyRouteLimits {
    pub max_routes_per_family: usize,
    pub max_targets_per_route: usize,
    pub max_label_chars: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DocumentIndexFamilyRoutes {
    pub family: DocumentIndexRouteFamily,
    pub route_count: usize,
    pub target_count: usize,
    pub routes: Vec<DocumentIndexFamilyRoute>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DocumentIndexFamilyRoute {
    pub paragraph_index: u32,
    pub start: u32,
    pub end: u32,
    pub targets: Vec<DocumentIndexFamilyTarget>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DocumentIndexFamilyTarget {
    pub kind: DocumentIndexFamilyTargetKind,
    pub start: u32,
    pub end: u32,
    pub label: String,
}

#[derive(Clone, Copy)]
struct Token<'a> {
    start: usize,
    end: usize,
    text: &'a str,
}

#[derive(Default)]
struct TargetRead {
    count: usize,
    targets: Vec<DocumentIndexFamilyTarget>,
}

pub fn document_index_family_routes(
    index: &MmapDocumentIndex,
    text: &str,
    limits: DocumentIndexFamilyRouteLimits,
) -> Result<Vec<DocumentIndexFamilyRoutes>, DocumentIndexError> {
    document_index_family_routes_with_mask(index, text, limits, DocumentIndexFamilyMask::all())
}

pub fn document_index_family_routes_with_mask(
    index: &MmapDocumentIndex,
    text: &str,
    limits: DocumentIndexFamilyRouteLimits,
    mask: DocumentIndexFamilyMask,
) -> Result<Vec<DocumentIndexFamilyRoutes>, DocumentIndexError> {
    if text.len() != index.text_len() as usize {
        return Err(DocumentIndexError::Invalid(
            "family route text does not match mapped document".to_owned(),
        ));
    }
    let mut entity_state = DocumentIndexFamilyRoutes::new(DocumentIndexRouteFamily::EntityState);
    let mut tension = DocumentIndexFamilyRoutes::new(DocumentIndexRouteFamily::Tension);
    let mut timeline = DocumentIndexFamilyRoutes::new(DocumentIndexRouteFamily::Timeline);

    for unit in index.units() {
        let unit = unit?;
        if unit.kind != DocumentIndexUnitKind::Paragraph {
            continue;
        }
        let start = unit.start as usize;
        let end = unit.end as usize;
        let paragraph = text.get(start..end).ok_or_else(|| {
            DocumentIndexError::Invalid("paragraph range outside text".to_owned())
        })?;

        if mask.contains(DocumentIndexRouteFamily::EntityState) {
            push_family_route(
                &mut entity_state,
                unit.index,
                unit.start,
                unit.end,
                extract_entity_state_targets(paragraph, start, limits),
                limits.max_routes_per_family,
            );
        }
        if mask.contains(DocumentIndexRouteFamily::Timeline) {
            push_family_route(
                &mut timeline,
                unit.index,
                unit.start,
                unit.end,
                extract_timeline_targets(paragraph, start, limits),
                limits.max_routes_per_family,
            );
        }
        if mask.contains(DocumentIndexRouteFamily::Tension) {
            push_family_route(
                &mut tension,
                unit.index,
                unit.start,
                unit.end,
                extract_tension_targets(paragraph, start, limits),
                limits.max_routes_per_family,
            );
        }
    }

    let mut families = Vec::with_capacity(3);
    if mask.contains(DocumentIndexRouteFamily::EntityState) {
        families.push(entity_state);
    }
    if mask.contains(DocumentIndexRouteFamily::Timeline) {
        families.push(timeline);
    }
    if mask.contains(DocumentIndexRouteFamily::Tension) {
        families.push(tension);
    }
    Ok(families)
}

impl DocumentIndexFamilyRoutes {
    fn new(family: DocumentIndexRouteFamily) -> Self {
        Self {
            family,
            route_count: 0,
            target_count: 0,
            routes: Vec::new(),
        }
    }
}

fn push_family_route(
    family: &mut DocumentIndexFamilyRoutes,
    paragraph_index: u32,
    start: u32,
    end: u32,
    read: TargetRead,
    max_routes: usize,
) {
    if read.count == 0 {
        return;
    }
    family.route_count += 1;
    family.target_count += read.count;
    if family.routes.len() < max_routes {
        family.routes.push(DocumentIndexFamilyRoute {
            paragraph_index,
            start,
            end,
            targets: read.targets,
        });
    }
}

fn extract_entity_state_targets(
    paragraph: &str,
    base: usize,
    limits: DocumentIndexFamilyRouteLimits,
) -> TargetRead {
    let mut state_cue = None;
    let mut entities = Vec::with_capacity(limits.max_targets_per_route.min(4));
    for token in tokens(paragraph, base) {
        if state_cue.is_none() && is_state_cue(token.text) {
            state_cue = Some(token);
        }
        if is_entity_token(token.text)
            && !entities
                .iter()
                .any(|existing: &Token<'_>| existing.text == token.text)
        {
            entities.push(token);
        }
    }
    if state_cue.is_none() {
        return TargetRead::default();
    }

    let mut read = TargetRead {
        count: entities.len().max(1),
        targets: Vec::with_capacity(limits.max_targets_per_route.min(entities.len().max(1))),
    };
    for entity in entities.into_iter().take(limits.max_targets_per_route) {
        read.targets.push(target(
            DocumentIndexFamilyTargetKind::EntityMention,
            entity,
            limits.max_label_chars,
        ));
    }
    if read.targets.is_empty() {
        read.targets.push(target(
            DocumentIndexFamilyTargetKind::StateCue,
            state_cue.expect("state cue"),
            limits.max_label_chars,
        ));
    }
    read
}

fn extract_timeline_targets(
    paragraph: &str,
    base: usize,
    limits: DocumentIndexFamilyRouteLimits,
) -> TargetRead {
    let mut read = TargetRead {
        count: 0,
        targets: Vec::with_capacity(limits.max_targets_per_route.min(4)),
    };
    for token in tokens(paragraph, base) {
        let kind = if is_date_token(token.text) {
            Some(DocumentIndexFamilyTargetKind::Date)
        } else if is_temporal_cue(token.text) {
            Some(DocumentIndexFamilyTargetKind::TemporalCue)
        } else {
            None
        };
        let Some(kind) = kind else {
            continue;
        };
        read.count += 1;
        if read.targets.len() < limits.max_targets_per_route {
            read.targets
                .push(target(kind, token, limits.max_label_chars));
        }
    }
    read
}

fn extract_tension_targets(
    paragraph: &str,
    base: usize,
    limits: DocumentIndexFamilyRouteLimits,
) -> TargetRead {
    let mut read = TargetRead {
        count: 0,
        targets: Vec::with_capacity(limits.max_targets_per_route.min(4)),
    };
    for token in tokens(paragraph, base) {
        if !is_tension_cue(token.text) {
            continue;
        }
        read.count += 1;
        if read.targets.len() < limits.max_targets_per_route {
            read.targets.push(target(
                DocumentIndexFamilyTargetKind::TensionCue,
                token,
                limits.max_label_chars,
            ));
        }
    }
    read
}

fn target(
    kind: DocumentIndexFamilyTargetKind,
    token: Token<'_>,
    max_label_chars: usize,
) -> DocumentIndexFamilyTarget {
    DocumentIndexFamilyTarget {
        kind,
        start: token.start as u32,
        end: token.end as u32,
        label: bounded_label(token.text, max_label_chars),
    }
}

fn tokens<'a>(text: &'a str, base: usize) -> impl Iterator<Item = Token<'a>> {
    TokenIter {
        text,
        bytes: text.as_bytes(),
        cursor: 0,
        base,
    }
}

struct TokenIter<'a> {
    text: &'a str,
    bytes: &'a [u8],
    cursor: usize,
    base: usize,
}

impl<'a> Iterator for TokenIter<'a> {
    type Item = Token<'a>;

    fn next(&mut self) -> Option<Self::Item> {
        while self.cursor < self.bytes.len() && !is_token_byte(self.bytes[self.cursor]) {
            self.cursor += 1;
        }
        if self.cursor >= self.bytes.len() {
            return None;
        }
        let start = self.cursor;
        while self.cursor < self.bytes.len() && is_token_byte(self.bytes[self.cursor]) {
            self.cursor += 1;
        }
        let end = trim_token_end(self.bytes, start, self.cursor);
        if end == start {
            return self.next();
        }
        Some(Token {
            start: self.base + start,
            end: self.base + end,
            text: &self.text[start..end],
        })
    }
}

fn is_token_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'/' | b'\'')
}

fn trim_token_end(bytes: &[u8], start: usize, mut end: usize) -> usize {
    while end > start && matches!(bytes[end - 1], b'-' | b'/' | b'\'') {
        end -= 1;
    }
    end
}

fn is_entity_token(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() > 1
        && bytes[0].is_ascii_uppercase()
        && bytes.iter().any(u8::is_ascii_lowercase)
        && !is_month(value)
}

fn is_state_cue(value: &str) -> bool {
    eq_any(
        value,
        &[
            "is",
            "are",
            "was",
            "were",
            "becomes",
            "became",
            "felt",
            "feels",
            "knows",
            "knew",
            "remembers",
            "remembered",
            "decides",
            "decided",
            "needs",
            "needed",
            "wants",
            "wanted",
            "serves",
            "served",
            "rank",
            "status",
            "affiliation",
            "memory",
            "decision",
            "context",
        ],
    )
}

fn is_date_token(value: &str) -> bool {
    is_iso_date(value) || is_slash_date(value) || is_month(value)
}

fn is_iso_date(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() == 10
        && bytes[4] == b'-'
        && bytes[7] == b'-'
        && bytes[..4].iter().all(u8::is_ascii_digit)
        && bytes[5..7].iter().all(u8::is_ascii_digit)
        && bytes[8..].iter().all(u8::is_ascii_digit)
}

fn is_slash_date(value: &str) -> bool {
    let slash_count = value
        .as_bytes()
        .iter()
        .filter(|byte| **byte == b'/')
        .count();
    slash_count == 2
        && value
            .as_bytes()
            .iter()
            .all(|byte| byte.is_ascii_digit() || *byte == b'/')
}

fn is_month(value: &str) -> bool {
    eq_any(
        value,
        &[
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
    )
}

fn is_temporal_cue(value: &str) -> bool {
    eq_any(
        value,
        &[
            "before",
            "after",
            "during",
            "until",
            "since",
            "yesterday",
            "today",
            "tomorrow",
            "tonight",
            "morning",
            "evening",
            "later",
            "earlier",
            "deadline",
            "schedule",
            "calendar",
            "timeline",
            "dawn",
            "dusk",
        ],
    )
}

fn is_tension_cue(value: &str) -> bool {
    eq_any(
        value,
        &[
            "but",
            "however",
            "though",
            "although",
            "except",
            "against",
            "conflict",
            "conflicted",
            "tension",
            "uneasy",
            "hesitated",
            "hesitates",
            "refused",
            "refuses",
            "resisted",
            "resists",
            "risk",
            "threat",
            "danger",
            "doubt",
            "fear",
            "feared",
            "hated",
            "hates",
            "pressure",
            "betrayal",
            "rival",
            "rivals",
            "secret",
            "suspicion",
        ],
    )
}

fn eq_any(value: &str, needles: &[&str]) -> bool {
    needles
        .iter()
        .any(|needle| value.eq_ignore_ascii_case(needle))
}

fn bounded_label(value: &str, max_chars: usize) -> String {
    if value.chars().count() <= max_chars {
        return value.to_owned();
    }
    value.chars().take(max_chars).collect()
}
