use std::sync::OnceLock;

use compact_str::CompactString;
use daachorse::{DoubleArrayAhoCorasick, DoubleArrayAhoCorasickBuilder, MatchKind};
use phoenix_types::{KnownMatch, TextRange};
use serde::{Deserialize, Serialize};

use crate::{canonicalize_with_offsets, normalize_raw};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct AlexSnapshotId(pub u64);

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct PatternId(pub u64);

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum SurfaceHitKind {
    EntityAlias,
    RelationCue,
    TemporalCue,
    CausalCue,
    EvidenceCue,
    StructureCue,
    GuardCue,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SurfaceHit {
    pub snapshot_id: AlexSnapshotId,
    pub pattern_id: PatternId,
    pub kind: SurfaceHitKind,
    pub source_range: TextRange,
    pub normalized_range: TextRange,
    pub surface: CompactString,
    pub normalized: CompactString,
    pub confidence: f32,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SurfaceHitBatch {
    pub snapshot_id: AlexSnapshotId,
    pub hits: Vec<SurfaceHit>,
}

#[derive(Clone, Copy)]
struct CuePattern {
    id: PatternId,
    surface: &'static str,
    kind: SurfaceHitKind,
}

const CUE_PATTERNS: &[CuePattern] = &[
    cue(10_001, "father", SurfaceHitKind::RelationCue),
    cue(10_002, "daughter", SurfaceHitKind::RelationCue),
    cue(10_003, "family", SurfaceHitKind::RelationCue),
    cue(10_011, "approved", SurfaceHitKind::RelationCue),
    cue(10_012, "accepted", SurfaceHitKind::RelationCue),
    cue(10_013, "warned", SurfaceHitKind::RelationCue),
    cue(10_014, "gave", SurfaceHitKind::RelationCue),
    cue(10_015, "handed", SurfaceHitKind::RelationCue),
    cue(20_001, "before", SurfaceHitKind::TemporalCue),
    cue(20_002, "after", SurfaceHitKind::TemporalCue),
    cue(20_003, "during", SurfaceHitKind::TemporalCue),
    cue(20_004, "later", SurfaceHitKind::TemporalCue),
    cue(20_005, "meanwhile", SurfaceHitKind::TemporalCue),
    cue(30_001, "because", SurfaceHitKind::CausalCue),
    cue(30_002, "therefore", SurfaceHitKind::CausalCue),
    cue(30_003, "which meant", SurfaceHitKind::CausalCue),
    cue(30_004, "that meant", SurfaceHitKind::CausalCue),
    cue(40_001, "documented", SurfaceHitKind::EvidenceCue),
    cue(40_002, "records", SurfaceHitKind::EvidenceCue),
    cue(40_003, "packet", SurfaceHitKind::EvidenceCue),
    cue(40_004, "evidence", SurfaceHitKind::EvidenceCue),
    cue(50_001, "chapter", SurfaceHitKind::StructureCue),
    cue(50_002, "scene", SurfaceHitKind::StructureCue),
];

const fn cue(id: u64, surface: &'static str, kind: SurfaceHitKind) -> CuePattern {
    CuePattern {
        id: PatternId(id),
        surface,
        kind,
    }
}

pub fn build_surface_hit_batch(
    snapshot_id: AlexSnapshotId,
    text: &str,
    known: Vec<KnownMatch>,
) -> SurfaceHitBatch {
    let mut hits = Vec::with_capacity(known.len() + 16);
    for known in known {
        let normalized = normalize_raw(&known.surface);
        hits.push(SurfaceHit {
            snapshot_id,
            pattern_id: PatternId(stable_hash(normalized.as_bytes())),
            kind: SurfaceHitKind::EntityAlias,
            source_range: known.range,
            normalized_range: TextRange {
                start: 0,
                end: normalized.len() as u32,
            },
            surface: CompactString::from(known.surface),
            normalized: CompactString::from(normalized),
            confidence: known.confidence,
        });
    }
    scan_cue_hits(snapshot_id, text, &mut hits);
    hits.sort_by(|left, right| {
        left.source_range
            .start
            .cmp(&right.source_range.start)
            .then_with(|| left.source_range.end.cmp(&right.source_range.end))
            .then_with(|| (left.pattern_id.0).cmp(&right.pattern_id.0))
    });
    SurfaceHitBatch { snapshot_id, hits }
}

fn scan_cue_hits(snapshot_id: AlexSnapshotId, text: &str, hits: &mut Vec<SurfaceHit>) {
    let Some(matcher) = cue_matcher() else {
        return;
    };
    let (canonicalized, offsets) = canonicalize_with_offsets(text);
    for matched in matcher.leftmost_find_iter(canonicalized.as_bytes()) {
        if !is_token_boundary(canonicalized.as_bytes(), matched.start(), matched.end()) {
            continue;
        }
        let pattern = CUE_PATTERNS[matched.value() as usize];
        let start = offsets.get(matched.start()).copied().unwrap_or(0);
        let end = offsets.get(matched.end()).copied().unwrap_or(text.len());
        let surface = text.get(start..end).unwrap_or_default();
        hits.push(SurfaceHit {
            snapshot_id,
            pattern_id: pattern.id,
            kind: pattern.kind,
            source_range: TextRange {
                start: start as u32,
                end: end as u32,
            },
            normalized_range: TextRange {
                start: matched.start() as u32,
                end: matched.end() as u32,
            },
            surface: CompactString::from(surface),
            normalized: CompactString::from(pattern.surface),
            confidence: 1.0,
        });
    }
}

fn cue_matcher() -> Option<&'static DoubleArrayAhoCorasick> {
    static MATCHER: OnceLock<Option<DoubleArrayAhoCorasick>> = OnceLock::new();
    MATCHER
        .get_or_init(|| {
            let surfaces = CUE_PATTERNS
                .iter()
                .map(|pattern| pattern.surface)
                .collect::<Vec<_>>();
            DoubleArrayAhoCorasickBuilder::new()
                .match_kind(MatchKind::LeftmostLongest)
                .build(&surfaces)
                .ok()
        })
        .as_ref()
}

fn is_token_boundary(text: &[u8], start: usize, end: usize) -> bool {
    let left = start == 0 || !is_word_byte(text[start.saturating_sub(1)]);
    let right = end >= text.len() || !is_word_byte(text[end]);
    left && right
}

fn is_word_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

fn stable_hash(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

#[cfg(test)]
mod tests {
    use phoenix_types::{EntityId, EntityKind, LexiconEntry, ScopeKey};

    use crate::Lexicon;

    #[test]
    fn surface_hits_include_entity_and_cue_evidence() {
        let entries = vec![LexiconEntry {
            entity_id: EntityId("e-kai".to_owned()),
            label: "Kai".to_owned(),
            kind: Some(EntityKind::Character),
            scope: ScopeKey::default(),
            ..LexiconEntry::default()
        }];
        let lexicon = Lexicon::from_entries(&entries).expect("lexicon");
        let batch = lexicon.scan_surface_hits(
            "Kai approved the packet because Hazel warned Kai.",
            &ScopeKey::default(),
        );

        assert!(batch.hits.iter().any(|hit| hit.normalized == "kai"));
        assert!(batch.hits.iter().any(|hit| hit.normalized == "approved"));
        assert!(batch.hits.iter().any(|hit| hit.normalized == "because"));
        assert!(batch.hits.iter().any(|hit| hit.normalized == "packet"));
    }

    #[test]
    fn cue_hits_respect_token_boundaries() {
        let lexicon = Lexicon::from_entries(&[]).expect("lexicon");
        let batch =
            lexicon.scan_surface_hits("The forefatherly title is noise.", &ScopeKey::default());

        assert!(!batch.hits.iter().any(|hit| hit.normalized == "father"));
    }
}
