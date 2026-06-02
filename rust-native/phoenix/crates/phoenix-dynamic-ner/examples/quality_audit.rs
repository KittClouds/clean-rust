use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::Path;
use std::time::Instant;

use compact_str::CompactString;
use phoenix_alex::Lexicon;
use phoenix_dynamic_ner::{
    DiscoveredSpan, DynamicNerModel, DynamicSchemaBuilder, EntityLabel, LabelPack, LocalMentionId,
    MentionKind, MentionPacket, MentionStatus, MentionVote, ModelNerWindow, NerModelError,
    PhoenixNerEngineBuilder, SurfaceNerInput, SurfaceRouter, VerificationCase,
};
use phoenix_rel_post::{GlinerBiModel, GlinerBiOverlapPolicy, GlinerBiPredictOptions};
use phoenix_types::{
    EntityId, EntityKind, GenderHint, LexiconEntry, ScopeKey, SentenceSpan, TextRange, TokenClass,
    TokenSpan,
};

const EXPECTED: &[(&str, &str)] = &[
    ("Ryan", "person"),
    ("Quicksave", "person"),
    ("Len", "person"),
    ("Wyvern", "person"),
    ("Vulcan", "person"),
    ("Zanbato", "person"),
    ("Ki-jung", "person"),
    ("Lanka", "person"),
    ("Jamie", "person"),
    ("New Rome", "location"),
    ("Campania", "location"),
    ("Italy", "location"),
    ("Naples", "location"),
    ("Mediterranean Sea", "location"),
    ("Rust Town", "location"),
    ("Little Maghreb", "location"),
    ("Bakuto", "location"),
    ("Dynamis", "organization"),
    ("Private Security", "organization"),
    ("Il Migliore", "organization"),
    ("Augusti", "organization"),
    ("Cosa Nostra", "organization"),
];

const FALSE_POSITIVES: &[&str] = &[
    "A-place",
    "Abstract",
    "Energy",
    "Information",
    "Life",
    "Matter",
    "Men",
    "Welcome",
    "address",
    "barman",
    "brother",
    "captain",
    "courier",
    "father",
    "guard",
    "her",
    "her father",
    "manager",
    "orange",
    "waiter",
    "woman",
];

struct CliGlinerModel {
    model: GlinerBiModel,
    threshold: f32,
    overlap_policy: GlinerBiOverlapPolicy,
}

impl CliGlinerModel {
    fn load(
        path: &Path,
        threshold: f32,
        overlap_policy: GlinerBiOverlapPolicy,
    ) -> Result<Self, String> {
        Ok(Self {
            model: GlinerBiModel::load(path).map_err(|err| format!("{err:?}"))?,
            threshold,
            overlap_policy,
        })
    }
}

impl DynamicNerModel for CliGlinerModel {
    fn discover(
        &self,
        window: &ModelNerWindow<'_>,
        label_pack: &LabelPack,
    ) -> Result<Vec<DiscoveredSpan>, NerModelError> {
        let mut model_labels = Vec::new();
        for label in &label_pack.labels {
            let mapped = match label.as_str() {
                "Character" | "Npc" | "NPC" | "Person" | "Rank" => "Person",
                "Organization" | "Faction" | "Alliance" | "Department" => "Organization",
                "Location" | "Region" | "Landmark" => "Location",
                other => other,
            };
            if !model_labels
                .iter()
                .any(|existing: &String| existing == mapped)
            {
                model_labels.push(mapped.to_owned());
            }
        }

        let predictions = self
            .model
            .predict_with_options(
                window.text,
                &model_labels,
                &GlinerBiPredictOptions {
                    threshold: self.threshold,
                    overlap_policy: self.overlap_policy,
                    ..Default::default()
                },
            )
            .map_err(|err| NerModelError::Inference(err.to_string()))?;

        Ok(predictions
            .into_iter()
            .map(|prediction| DiscoveredSpan {
                window_relative_range: TextRange {
                    start: prediction.span_start as u32,
                    end: prediction.span_end as u32,
                },
                surface: CompactString::new(&prediction.text),
                label: EntityLabel::new(match prediction.label.as_str() {
                    "Person" => "Character",
                    "Organization" => "Organization",
                    "Location" => "Location",
                    other => other,
                }),
                confidence: prediction.score,
            })
            .collect())
    }

    fn verify(
        &self,
        _cases: &[VerificationCase],
    ) -> Result<Vec<(LocalMentionId, MentionVote)>, NerModelError> {
        Ok(Vec::new())
    }
}

#[derive(Clone, Debug)]
struct SurfaceStats {
    surface: String,
    count: usize,
    best_label: String,
    group: &'static str,
    max_confidence: f32,
    statuses: BTreeSet<String>,
    sources: BTreeSet<String>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let input_path = env::args()
        .nth(1)
        .unwrap_or_else(|| "docs\\shortrun.md".to_owned());
    let model_path = env::args()
        .nth(2)
        .unwrap_or_else(|| "..\\..\\..\\..\\gliner-bi-small-onnx".to_owned());
    let threshold = env_f32("PHOENIX_DYN_NER_THRESHOLD", 0.35);
    let max_labels = env_usize(
        "PHOENIX_DYN_NER_MAX_LABELS",
        DynamicSchemaBuilder::default().max_labels,
    );
    let max_model_windows = env_usize("PHOENIX_DYN_NER_MAX_MODEL_WINDOWS", 256);
    let overlap_policy = env::var("PHOENIX_DYN_NER_OVERLAP_POLICY")
        .ok()
        .map(|value| GlinerBiOverlapPolicy::parse(&value))
        .transpose()?
        .unwrap_or_default();

    let text = fs::read_to_string(&input_path)?;
    let (tokens, sentences) = tokenize(&text);
    let lexicon = story_lexicon()?;
    let scope = ScopeKey::default();

    let load_started = Instant::now();
    let model = CliGlinerModel::load(Path::new(&model_path), threshold, overlap_policy)?;
    let load_ms = load_started.elapsed().as_millis();
    let engine = PhoenixNerEngineBuilder::new()
        .schema(DynamicSchemaBuilder {
            max_labels,
            ..Default::default()
        })
        .router(SurfaceRouter { max_model_windows })
        .model(Box::new(model))
        .build();

    let input = SurfaceNerInput {
        document_id: "shortrun-quality",
        text: &text,
        tokens: &tokens,
        sentences: &sentences,
        scope: &scope,
        lexicon: Some(&lexicon),
        surface_hits: &[],
        label_bank_context: None,
    };

    let run_started = Instant::now();
    let output = engine.extract_mentions(&input)?;
    let run_ms = run_started.elapsed().as_millis();
    let surfaces = collect_surfaces(&output.mentions);
    print_audit(
        &input_path,
        &model_path,
        load_ms,
        run_ms,
        &output.mentions,
        &surfaces,
    );
    Ok(())
}

fn collect_surfaces(mentions: &[MentionPacket]) -> BTreeMap<String, SurfaceStats> {
    let mut surfaces = BTreeMap::<String, SurfaceStats>::new();
    for mention in mentions
        .iter()
        .filter(|mention| mention.mention_kind == MentionKind::Named && mention.is_exportable())
    {
        let normalized = normalize_key(mention.surface.as_str());
        let label = best_label(mention);
        let entry = surfaces.entry(normalized).or_insert_with(|| SurfaceStats {
            surface: mention.surface.to_string(),
            count: 0,
            best_label: label.clone(),
            group: normalize_group(&label),
            max_confidence: 0.0,
            statuses: BTreeSet::new(),
            sources: BTreeSet::new(),
        });
        entry.count += 1;
        entry.max_confidence = entry.max_confidence.max(mention.confidence);
        entry.statuses.insert(format!("{:?}", mention.status));
        for vote in &mention.source_votes {
            entry.sources.insert(format!("{:?}", vote.source));
        }
        if label_rank(&label) > label_rank(&entry.best_label) {
            entry.best_label = label.clone();
            entry.group = normalize_group(&label);
        }
    }
    surfaces
}

fn collect_surface_statuses(mentions: &[MentionPacket]) -> BTreeMap<String, BTreeSet<String>> {
    let mut statuses = BTreeMap::<String, BTreeSet<String>>::new();
    for mention in mentions
        .iter()
        .filter(|mention| mention.mention_kind == MentionKind::Named)
    {
        statuses
            .entry(normalize_key(mention.surface.as_str()))
            .or_default()
            .insert(format!("{:?}", mention.status));
    }
    statuses
}

fn print_audit(
    input_path: &str,
    model_path: &str,
    load_ms: u128,
    run_ms: u128,
    mentions: &[MentionPacket],
    surfaces: &BTreeMap<String, SurfaceStats>,
) {
    let mut expected_found = 0usize;
    let mut expected_correct = 0usize;
    let mut expected_failures = Vec::new();
    let all_surface_statuses = collect_surface_statuses(mentions);
    for (surface, expected_group) in EXPECTED {
        let key = normalize_key(surface);
        match surfaces.get(&key) {
            Some(stats) if stats.group == *expected_group => {
                expected_found += 1;
                expected_correct += 1;
            }
            Some(stats) => {
                expected_found += 1;
                expected_failures.push(format!(
                    "{} expected={} actual={} label={}",
                    surface, expected_group, stats.group, stats.best_label
                ));
            }
            None => {
                if let Some(statuses) = all_surface_statuses.get(&key) {
                    expected_failures.push(format!(
                        "{surface} expected={expected_group} actual=non_exportable statuses={}",
                        statuses.iter().cloned().collect::<Vec<_>>().join("|")
                    ));
                } else {
                    expected_failures.push(format!(
                        "{surface} expected={expected_group} actual=missing"
                    ));
                }
            }
        }
    }

    let false_hits = FALSE_POSITIVES
        .iter()
        .filter_map(|surface| {
            surfaces.get(&normalize_key(surface)).map(|stats| {
                format!(
                    "{} -> {} ({}) statuses={}",
                    stats.surface,
                    stats.group,
                    stats.best_label,
                    stats.statuses.iter().cloned().collect::<Vec<_>>().join("|")
                )
            })
        })
        .collect::<Vec<_>>();

    let unknown_unique = surfaces
        .values()
        .filter(|stats| stats.group == "other" || stats.best_label == "unknown")
        .count();
    let named_unique = surfaces.len();
    let model_labeled = surfaces
        .values()
        .filter(|stats| {
            stats
                .sources
                .iter()
                .any(|source| source == "ModelDiscovery" || source == "ModelVerify")
        })
        .count();
    let accepted = mentions
        .iter()
        .filter(|mention| mention.is_accepted())
        .count();
    let alias_candidates = mentions
        .iter()
        .filter(|mention| mention.status == MentionStatus::AliasCandidate)
        .count();
    let exportable = mentions
        .iter()
        .filter(|mention| mention.is_exportable())
        .count();
    let needs_adjudication = mentions
        .iter()
        .filter(|mention| mention.status == MentionStatus::NeedsAdjudication)
        .count();
    let rejected = mentions
        .iter()
        .filter(|mention| mention.status == MentionStatus::Rejected)
        .count();

    let expected_recall = expected_found as f32 / EXPECTED.len() as f32;
    let expected_kind_accuracy = expected_correct as f32 / EXPECTED.len() as f32;
    let false_hit_rate = false_hits.len() as f32 / FALSE_POSITIVES.len() as f32;
    let unknown_rate = unknown_unique as f32 / named_unique.max(1) as f32;
    let score = (expected_kind_accuracy * 0.55)
        + (expected_recall * 0.20)
        + ((1.0 - false_hit_rate) * 0.15)
        + ((1.0 - unknown_rate) * 0.10);
    let pass = expected_recall >= 0.90
        && expected_kind_accuracy >= 0.78
        && false_hits.len() <= 6
        && unknown_rate <= 0.35
        && exportable >= EXPECTED.len();

    println!("QUALITY {}", if pass { "PASS" } else { "FAIL" });
    println!("DOC {input_path}");
    println!("MODEL {model_path}");
    println!("TIMING load_ms={load_ms} run_ms={run_ms}");
    println!(
        "SCORE {:.3} expected_recall={:.3} expected_kind_accuracy={:.3} false_hit_rate={:.3} unknown_rate={:.3}",
        score, expected_recall, expected_kind_accuracy, false_hit_rate, unknown_rate
    );
    println!(
        "COUNTS mentions={} named_unique={} model_labeled_unique={} accepted_mentions={} alias_candidate_mentions={} exportable_mentions={} adjudication_mentions={} rejected_mentions={} false_hits={}",
        mentions.len(),
        named_unique,
        model_labeled,
        accepted,
        alias_candidates,
        exportable,
        needs_adjudication,
        rejected,
        false_hits.len()
    );
    println!("LABELS");
    for (label, count) in label_counts(surfaces) {
        println!("  {label}: {count}");
    }
    if !expected_failures.is_empty() {
        println!("EXPECTED_FAILURES");
        for failure in expected_failures {
            println!("  {failure}");
        }
    }
    if !false_hits.is_empty() {
        println!("FALSE_POSITIVE_HITS");
        for hit in false_hits {
            println!("  {hit}");
        }
    }
}

fn best_label(mention: &MentionPacket) -> String {
    mention
        .label_distribution
        .iter()
        .max_by(|left, right| left.1.partial_cmp(&right.1).unwrap_or(Ordering::Equal))
        .map(|(label, _)| label.to_string())
        .unwrap_or_else(|| "unknown".to_owned())
}

fn label_rank(label: &str) -> u8 {
    match normalize_group(label) {
        "person" | "location" | "organization" => 4,
        "event" | "item" | "concept" => 3,
        _ => 1,
    }
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
        _ => "other",
    }
}

fn label_counts(surfaces: &BTreeMap<String, SurfaceStats>) -> BTreeMap<&'static str, usize> {
    let mut counts = BTreeMap::new();
    for stats in surfaces.values() {
        *counts.entry(stats.group).or_default() += 1;
    }
    counts
}

fn story_lexicon() -> Result<Lexicon, String> {
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

fn tokenize(text: &str) -> (Vec<TokenSpan>, Vec<SentenceSpan>) {
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

fn normalize_key(surface: &str) -> String {
    surface
        .trim_matches(|ch: char| !ch.is_alphanumeric())
        .to_ascii_lowercase()
}

fn env_f32(key: &str, default: f32) -> f32 {
    env::var(key)
        .ok()
        .and_then(|value| value.parse::<f32>().ok())
        .unwrap_or(default)
}

fn env_usize(key: &str, default: usize) -> usize {
    env::var(key)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(default)
}
