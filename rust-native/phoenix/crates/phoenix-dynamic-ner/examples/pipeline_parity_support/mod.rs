use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};

use phoenix_alex::Lexicon;
use phoenix_dynamic_ner::{
    MentionKind, MentionPacket, SurfaceCandidateTarget, SurfaceMemoryReport,
};
use phoenix_types::{
    EntityId, EntityKind, GenderHint, LexiconEntry, ScopeKey, SentenceSpan, TextRange, TokenClass,
    TokenSpan,
};

#[derive(Clone, Debug)]
pub(super) struct DocSummary {
    pub(super) doc: String,
    pub(super) backend: &'static str,
    pub(super) run_ms: u128,
    pub(super) total: usize,
    pub(super) exportable: usize,
    pub(super) hint_eligible: usize,
    resolution: ResolutionSummary,
    labels: BTreeMap<String, usize>,
    evidence: BTreeMap<String, usize>,
    surfaces: BTreeMap<String, SurfaceSummary>,
}

#[derive(Clone, Debug, Default)]
struct ResolutionSummary {
    surfaces: usize,
    edges: usize,
    known_edges: usize,
    speculative_edges: usize,
    deferred_edges: usize,
    conflicts: usize,
    aliases: usize,
}

#[derive(Clone, Debug, Default)]
struct SurfaceSummary {
    surface: String,
    count: usize,
    label: String,
    confidence: f32,
    labels: BTreeMap<String, usize>,
}

pub(super) fn summarize(
    backend: &'static str,
    doc: &str,
    run_ms: u128,
    mentions: &[MentionPacket],
    surface_memory: &SurfaceMemoryReport,
) -> DocSummary {
    let debug_watched_votes = std::env::var_os("PHOENIX_DYN_NER_DEBUG_WATCH_VOTES").is_some();
    let watched = if debug_watched_votes {
        watched_surfaces().into_iter().collect::<BTreeSet<_>>()
    } else {
        BTreeSet::new()
    };
    let mut summary = DocSummary {
        doc: doc.to_owned(),
        backend,
        run_ms,
        total: mentions.len(),
        exportable: mentions.iter().filter(|m| m.is_exportable()).count(),
        hint_eligible: mentions.iter().filter(|m| m.is_hint_eligible()).count(),
        resolution: summarize_resolution(surface_memory),
        labels: BTreeMap::new(),
        evidence: BTreeMap::new(),
        surfaces: BTreeMap::new(),
    };
    for mention in mentions {
        for vote in &mention.source_votes {
            let label = vote.label.as_ref().map(|l| l.as_str()).unwrap_or("-");
            *summary
                .evidence
                .entry(format!("{:?}:{:?}:{label}", vote.source, vote.reason))
                .or_default() += 1;
        }
        if mention.mention_kind != MentionKind::Named {
            continue;
        }
        let label = best_label(mention);
        let key = normalize_key(mention.surface.as_str());
        if debug_watched_votes && watched.contains(&key) {
            let votes = mention
                .source_votes
                .iter()
                .map(|vote| {
                    let label = vote
                        .label
                        .as_ref()
                        .map(|label| label.as_str())
                        .unwrap_or("-");
                    format!(
                        "{:?}:{:?}:{label}:{:.3}",
                        vote.source, vote.reason, vote.confidence
                    )
                })
                .collect::<Vec<_>>()
                .join("|");
            println!(
                "WATCH_VOTES\tbackend={backend}\t{}\tstatus={:?}\tconf={:.3}\tbest={}\tvotes={}",
                clean(mention.surface.as_str()),
                mention.status,
                mention.confidence,
                clean(&label),
                clean(&votes)
            );
        }
        if mention.is_exportable() {
            *summary.labels.entry(label.clone()).or_default() += 1;
        }
        let entry = summary
            .surfaces
            .entry(key)
            .or_insert_with(|| SurfaceSummary {
                surface: mention.surface.to_string(),
                label: label.clone(),
                confidence: mention.confidence,
                ..Default::default()
            });
        entry.count += 1;
        *entry.labels.entry(label.clone()).or_default() += 1;
        entry.confidence = entry.confidence.max(mention.confidence);
        if entry.labels.get(&label).copied().unwrap_or_default()
            >= entry.labels.get(&entry.label).copied().unwrap_or_default()
        {
            entry.label = label;
        }
    }
    summary
}

pub(super) fn print_summary(summary: &DocSummary) {
    println!(
        "DOC\tbackend={}\tpath={}\trun_ms={}\ttotal={}\texportable={}\thint_eligible={}\tunique_named={}",
        summary.backend,
        clean(&summary.doc),
        summary.run_ms,
        summary.total,
        summary.exportable,
        summary.hint_eligible,
        summary.surfaces.len()
    );
    println!(
        "LABEL_COUNTS\tbackend={}\t{}",
        summary.backend,
        join_counts(&summary.labels)
    );
    println!(
        "EVIDENCE_COUNTS\tbackend={}\t{}",
        summary.backend,
        join_counts(&summary.evidence)
    );
    println!(
        "RESOLUTION_COUNTS\tbackend={}\tsurfaces={}\tedges={}\tknown={}\tspeculative={}\tdeferred={}\tconflicts={}\taliases={}",
        summary.backend,
        summary.resolution.surfaces,
        summary.resolution.edges,
        summary.resolution.known_edges,
        summary.resolution.speculative_edges,
        summary.resolution.deferred_edges,
        summary.resolution.conflicts,
        summary.resolution.aliases
    );
    println!("TOP_SURFACES\tbackend={}", summary.backend);
    for surface in top_surfaces(summary, 16) {
        println!(
            "SURFACE\tbackend={}\t{}\tlabel={}\tcount={}\tmax_conf={:.3}",
            summary.backend,
            clean(&surface.surface),
            clean(&surface.label),
            surface.count,
            surface.confidence
        );
    }
    let watched = watched_surfaces();
    if !watched.is_empty() {
        println!("WATCH_SURFACES\tbackend={}", summary.backend);
        for key in watched {
            match summary.surfaces.get(&key) {
                Some(surface) => println!(
                    "WATCH_SURFACE\tbackend={}\t{}\tlabel={}\tcount={}\tmax_conf={:.3}",
                    summary.backend,
                    clean(&surface.surface),
                    clean(&surface.label),
                    surface.count,
                    surface.confidence
                ),
                None => println!(
                    "WATCH_SURFACE\tbackend={}\t{}\tlabel=missing\tcount=0\tmax_conf=0.000",
                    summary.backend,
                    clean(&key)
                ),
            }
        }
    }
}

pub(super) fn print_delta(left: &DocSummary, right: &DocSummary) {
    let left_keys = left.surfaces.keys().cloned().collect::<BTreeSet<_>>();
    let right_keys = right.surfaces.keys().cloned().collect::<BTreeSet<_>>();
    let common = left_keys.intersection(&right_keys).count();
    let left_only = left_keys
        .difference(&right_keys)
        .cloned()
        .collect::<Vec<_>>();
    let right_only = right_keys
        .difference(&left_keys)
        .cloned()
        .collect::<Vec<_>>();
    println!(
        "DELTA\tpath={}\tcommon={common}\tbi_only={}\tx_only={}\texportable_delta={}",
        clean(&left.doc),
        left_only.len(),
        right_only.len(),
        right.exportable as isize - left.exportable as isize
    );
    print_delta_surfaces("BI_ONLY", left, &left_only);
    print_delta_surfaces("X_ONLY", right, &right_only);
    for key in left_keys.intersection(&right_keys) {
        let bi = &left.surfaces[key];
        let x = &right.surfaces[key];
        if normalize_group(&bi.label) != normalize_group(&x.label) {
            println!(
                "LABEL_SHIFT\t{}\tbi={}\tx={}",
                clean(&bi.surface),
                clean(&bi.label),
                clean(&x.label)
            );
        }
    }
}

fn summarize_resolution(surface_memory: &SurfaceMemoryReport) -> ResolutionSummary {
    let mut summary = ResolutionSummary {
        surfaces: surface_memory.entries.len(),
        edges: surface_memory.candidate_edges.len(),
        conflicts: surface_memory
            .entries
            .iter()
            .filter(|entry| entry.conflict)
            .count(),
        aliases: surface_memory
            .entries
            .iter()
            .map(|entry| entry.aliases.len().saturating_sub(1))
            .sum(),
        ..Default::default()
    };
    for edge in &surface_memory.candidate_edges {
        match edge.target {
            SurfaceCandidateTarget::KnownEntity(_) => summary.known_edges += 1,
            SurfaceCandidateTarget::SpeculativeEntity(_) => summary.speculative_edges += 1,
            SurfaceCandidateTarget::DeferredReview => summary.deferred_edges += 1,
        }
    }
    summary
}

fn print_delta_surfaces(title: &str, summary: &DocSummary, keys: &[String]) {
    println!("{title}\tpath={}", clean(&summary.doc));
    let mut rows = keys
        .iter()
        .filter_map(|key| summary.surfaces.get(key))
        .collect::<Vec<_>>();
    rows.sort_by(|left, right| {
        right.count.cmp(&left.count).then_with(|| {
            right
                .confidence
                .partial_cmp(&left.confidence)
                .unwrap_or(Ordering::Equal)
        })
    });
    for row in rows.into_iter().take(16) {
        println!(
            "{title}_SURFACE\t{}\tlabel={}\tcount={}\tmax_conf={:.3}",
            clean(&row.surface),
            clean(&row.label),
            row.count,
            row.confidence
        );
    }
}

fn top_surfaces(summary: &DocSummary, limit: usize) -> Vec<&SurfaceSummary> {
    let mut rows = summary.surfaces.values().collect::<Vec<_>>();
    rows.sort_by(|left, right| {
        right.count.cmp(&left.count).then_with(|| {
            right
                .confidence
                .partial_cmp(&left.confidence)
                .unwrap_or(Ordering::Equal)
        })
    });
    rows.truncate(limit);
    rows
}

fn best_label(mention: &MentionPacket) -> String {
    mention
        .label_distribution
        .iter()
        .max_by(|left, right| left.1.partial_cmp(&right.1).unwrap_or(Ordering::Equal))
        .map(|(label, _)| label.to_string())
        .unwrap_or_else(|| "unknown".to_owned())
}

fn normalize_group(label: &str) -> &'static str {
    match label {
        "Character" | "Npc" | "NPC" | "Person" => "person",
        "Creature" | "Species" | "Monster" => "creature",
        "Organization" | "Faction" | "Department" | "Alliance" => "organization",
        "Location" | "Region" | "Landmark" => "location",
        "Event" => "event",
        "Artifact" | "Item" | "Weapon" => "item",
        "Concept" | "Ability" | "Spell" | "Rank" => "concept",
        "Pronoun" => "pronoun",
        _ => "other",
    }
}

fn normalize_key(surface: &str) -> String {
    surface
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_ascii_lowercase()
}

fn join_counts(counts: &BTreeMap<String, usize>) -> String {
    counts
        .iter()
        .map(|(key, value)| format!("{key}:{value}"))
        .collect::<Vec<_>>()
        .join("|")
}

pub(super) fn clean(value: &str) -> String {
    value
        .replace('\t', " ")
        .replace('\r', " ")
        .replace('\n', " ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn watched_surfaces() -> Vec<String> {
    std::env::var("PHOENIX_DYN_NER_WATCH_SURFACES")
        .ok()
        .map(|value| {
            value
                .split(',')
                .map(normalize_key)
                .filter(|key| !key.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

pub(super) fn story_lexicon() -> Result<Lexicon, String> {
    let entries = [
        ("aella", "Aella", EntityKind::Character),
        ("aurora", "Aurora", EntityKind::Character),
        ("brynwyn", "Brynwyn", EntityKind::Character),
        ("iriane", "Iriane", EntityKind::Character),
        ("isolde", "Isolde", EntityKind::Character),
        ("kai", "Kai", EntityKind::Character),
        ("phaeris", "Phaeris", EntityKind::Character),
        ("rowan", "Rowan", EntityKind::Character),
        ("siofra", "Siofra", EntityKind::Character),
    ]
    .into_iter()
    .map(|(id, label, kind)| LexiconEntry {
        entity_id: EntityId(id.to_owned()),
        label: label.to_owned(),
        aliases: Vec::new(),
        kind: Some(kind),
        gender: Some(GenderHint::Unknown),
        number: None,
        scope: ScopeKey::default(),
    })
    .collect::<Vec<_>>();
    Lexicon::from_entries(&entries).map_err(|err| format!("{err:?}"))
}

pub(super) fn tokenize(text: &str) -> (Vec<TokenSpan>, Vec<SentenceSpan>) {
    let mut tokens = Vec::new();
    let mut sentences = Vec::new();
    let mut sent_start = 0usize;
    let mut start = None;
    for (idx, ch) in text.char_indices() {
        if ch.is_alphanumeric() || ch == '\'' || ch == '-' {
            start.get_or_insert(idx);
        } else if let Some(s) = start.take() {
            tokens.push(token(text, s, idx));
        }
        if matches!(ch, '.' | '!' | '?') {
            sentences.push(SentenceSpan {
                index: sentences.len(),
                range: TextRange {
                    start: sent_start as u32,
                    end: (idx + ch.len_utf8()) as u32,
                },
            });
            sent_start = idx + ch.len_utf8();
        }
    }
    if let Some(s) = start {
        tokens.push(token(text, s, text.len()));
    }
    if sent_start < text.len() {
        sentences.push(SentenceSpan {
            index: sentences.len(),
            range: TextRange {
                start: sent_start as u32,
                end: text.len() as u32,
            },
        });
    }
    (tokens, sentences)
}

fn token(text: &str, start: usize, end: usize) -> TokenSpan {
    TokenSpan {
        range: TextRange {
            start: start as u32,
            end: end as u32,
        },
        capitalized: text[start..].starts_with(char::is_uppercase),
        pos: None,
        token_class: Some(TokenClass::Word),
        masked: false,
    }
}
