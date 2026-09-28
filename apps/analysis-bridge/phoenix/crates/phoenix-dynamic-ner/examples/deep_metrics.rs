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
    MentionKind, MentionPacket, MentionVote, ModelNerWindow, NerModelError,
    PhoenixNerEngineBuilder, SurfaceNerInput, SurfaceRouter, VerificationCase,
};
use phoenix_rel_post::{GlinerBiModel, GlinerBiOverlapPolicy, GlinerBiPredictOptions};
use phoenix_types::{
    EntityId, EntityKind, GenderHint, LexiconEntry, ScopeKey, SentenceSpan, TextRange, TokenClass,
    TokenSpan,
};

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

        self.model
            .predict_with_options(
                window.text,
                &model_labels,
                &GlinerBiPredictOptions {
                    threshold: self.threshold,
                    overlap_policy: self.overlap_policy,
                    ..Default::default()
                },
            )
            .map(|predictions| {
                predictions
                    .into_iter()
                    .map(|prediction| DiscoveredSpan {
                        window_relative_range: TextRange {
                            start: prediction.span_start as u32,
                            end: prediction.span_end as u32,
                        },
                        surface: CompactString::new(prediction.text),
                        label: EntityLabel::new(prediction.label.as_str()),
                        confidence: prediction.score,
                    })
                    .collect()
            })
            .map_err(|err| NerModelError::Inference(format!("{err:?}")))
    }

    fn verify(
        &self,
        _cases: &[VerificationCase],
    ) -> Result<Vec<(LocalMentionId, MentionVote)>, NerModelError> {
        Ok(Vec::new())
    }
}

#[derive(Default)]
struct SurfaceRollup {
    surface: String,
    count: usize,
    exportable_count: usize,
    hint_count: usize,
    confidence_sum: f32,
    max_confidence: f32,
    first_sentence: u32,
    first_range: TextRange,
    snippet: String,
    statuses: BTreeMap<String, usize>,
    sources: BTreeMap<String, usize>,
    source_labels: BTreeMap<String, usize>,
    best_labels: BTreeMap<String, usize>,
    groups: BTreeSet<&'static str>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let docs = {
        let args = env::args().skip(1).collect::<Vec<_>>();
        if args.is_empty() {
            vec![
                "docs\\shortrun.md".to_owned(),
                "docs\\mother2.md".to_owned(),
            ]
        } else {
            args
        }
    };
    let model_path = env::var("PHOENIX_DYN_NER_MODEL_PATH")
        .unwrap_or_else(|_| "gliner-bi-small-onnx".to_owned());
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

    let load_started = Instant::now();
    let model = CliGlinerModel::load(Path::new(&model_path), threshold, overlap_policy)?;
    let load_ms = load_started.elapsed().as_millis();
    println!(
        "NER_DEEP_METRICS\tmodel={}\tload_ms={load_ms}\tthreshold={threshold:.3}\tmax_labels={max_labels}\tmax_model_windows={max_model_windows}",
        clean(&model_path)
    );

    let engine = PhoenixNerEngineBuilder::new()
        .schema(DynamicSchemaBuilder {
            max_labels,
            ..Default::default()
        })
        .router(SurfaceRouter { max_model_windows })
        .model(Box::new(model))
        .build();
    let lexicon = story_lexicon()?;
    let scope = ScopeKey::default();

    for doc in docs {
        let text = fs::read_to_string(&doc)?;
        let (tokens, sentences) = tokenize(&text);
        let input = SurfaceNerInput {
            document_id: "ner-deep-metrics",
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
        print_doc_report(
            &doc,
            &text,
            tokens.len(),
            sentences.len(),
            run_ms,
            &output.mentions,
        );
    }
    Ok(())
}

fn print_doc_report(
    doc: &str,
    text: &str,
    tokens: usize,
    sentences: usize,
    run_ms: u128,
    mentions: &[MentionPacket],
) {
    let rollups = collect_rollups(text, mentions);
    let exportable = mentions
        .iter()
        .filter(|mention| mention.is_exportable())
        .count();
    let hint_eligible = mentions
        .iter()
        .filter(|mention| mention.is_hint_eligible())
        .count();
    println!(
        "DOC\tpath={}\tchars={}\ttokens={tokens}\tsentences={sentences}\trun_ms={run_ms}",
        clean(doc),
        text.len()
    );
    println!(
        "MENTION_COUNTS\ttotal={}\texportable={exportable}\thint_eligible={hint_eligible}\tunique_named_surfaces={}",
        mentions.len(),
        rollups.len()
    );
    print_counts(
        "STATUS_COUNTS",
        mentions.iter().map(|m| format!("{:?}", m.status)),
    );
    print_counts(
        "MENTION_KIND_COUNTS",
        mentions.iter().map(|m| format!("{:?}", m.mention_kind)),
    );
    print_counts(
        "BEST_LABEL_COUNTS",
        mentions
            .iter()
            .filter(|m| m.is_exportable())
            .map(best_label),
    );
    print_counts(
        "SOURCE_COUNTS",
        mentions
            .iter()
            .flat_map(|m| m.source_votes.iter().map(|v| format!("{:?}", v.source))),
    );
    print_counts(
        "SOURCE_LABEL_COUNTS",
        mentions.iter().flat_map(|m| {
            m.source_votes.iter().filter_map(|v| {
                v.label
                    .as_ref()
                    .map(|label| format!("{:?}:{}", v.source, label.as_str()))
            })
        }),
    );
    println!("SURFACE_COLUMNS\tsurface\tgroup\tbest_label\tcount\texportable\thint_eligible\tmax_conf\tavg_conf\tstatuses\tsources\tbest_labels\tsource_labels\tfirst_sentence\tfirst_range\tsnippet");
    for rollup in ordered_rollups(&rollups) {
        let best = mode(&rollup.best_labels).unwrap_or_else(|| "unknown".to_owned());
        let group = normalize_group(&best);
        let avg = rollup.confidence_sum / rollup.count.max(1) as f32;
        println!(
            "SURFACE\t{}\t{}\t{}\t{}\t{}\t{}\t{:.3}\t{:.3}\t{}\t{}\t{}\t{}\t{}\t{}-{}\t{}",
            clean(&rollup.surface),
            group,
            clean(&best),
            rollup.count,
            rollup.exportable_count,
            rollup.hint_count,
            rollup.max_confidence,
            avg,
            join_counts(&rollup.statuses),
            join_counts(&rollup.sources),
            join_counts(&rollup.best_labels),
            join_counts(&rollup.source_labels),
            rollup.first_sentence,
            rollup.first_range.start,
            rollup.first_range.end,
            clean(&rollup.snippet)
        );
    }
    println!("AMBIGUOUS_SURFACES");
    for rollup in ordered_rollups(&rollups)
        .into_iter()
        .filter(|rollup| rollup.groups.len() > 1 || rollup.best_labels.len() > 1)
    {
        println!(
            "AMBIGUOUS\t{}\tgroups={}\tbest_labels={}\tsource_labels={}",
            clean(&rollup.surface),
            rollup.groups.iter().copied().collect::<Vec<_>>().join("|"),
            join_counts(&rollup.best_labels),
            join_counts(&rollup.source_labels)
        );
    }
}

fn collect_rollups(text: &str, mentions: &[MentionPacket]) -> BTreeMap<String, SurfaceRollup> {
    let mut rollups = BTreeMap::<String, SurfaceRollup>::new();
    for mention in mentions
        .iter()
        .filter(|mention| mention.mention_kind == MentionKind::Named)
    {
        let key = normalize_key(mention.surface.as_str());
        let best = best_label(mention);
        let entry = rollups.entry(key).or_insert_with(|| SurfaceRollup {
            surface: mention.surface.to_string(),
            first_sentence: mention.sentence_index,
            first_range: mention.range,
            snippet: snippet(text, mention.range),
            ..Default::default()
        });
        entry.count += 1;
        entry.confidence_sum += mention.confidence;
        entry.max_confidence = entry.max_confidence.max(mention.confidence);
        entry.groups.insert(normalize_group(&best));
        *entry.best_labels.entry(best).or_default() += 1;
        *entry
            .statuses
            .entry(format!("{:?}", mention.status))
            .or_default() += 1;
        if mention.is_exportable() {
            entry.exportable_count += 1;
        }
        if mention.is_hint_eligible() {
            entry.hint_count += 1;
        }
        for vote in &mention.source_votes {
            *entry
                .sources
                .entry(format!("{:?}", vote.source))
                .or_default() += 1;
            if let Some(label) = vote.label.as_ref() {
                *entry
                    .source_labels
                    .entry(format!("{:?}:{}", vote.source, label.as_str()))
                    .or_default() += 1;
            }
        }
    }
    rollups
}

fn ordered_rollups(rollups: &BTreeMap<String, SurfaceRollup>) -> Vec<&SurfaceRollup> {
    let mut values = rollups.values().collect::<Vec<_>>();
    values.sort_by(|left, right| {
        let left_label = mode(&left.best_labels).unwrap_or_default();
        let right_label = mode(&right.best_labels).unwrap_or_default();
        normalize_group(&left_label)
            .cmp(normalize_group(&right_label))
            .then_with(|| right.count.cmp(&left.count))
            .then_with(|| left.surface.cmp(&right.surface))
    });
    values
}

fn print_counts<I>(title: &str, values: I)
where
    I: IntoIterator<Item = String>,
{
    let mut counts = BTreeMap::<String, usize>::new();
    for value in values {
        *counts.entry(value).or_default() += 1;
    }
    println!("{title}\t{}", join_counts(&counts));
}

fn join_counts(counts: &BTreeMap<String, usize>) -> String {
    counts
        .iter()
        .map(|(key, value)| format!("{key}:{value}"))
        .collect::<Vec<_>>()
        .join("|")
}

fn mode(counts: &BTreeMap<String, usize>) -> Option<String> {
    counts
        .iter()
        .max_by(|left, right| left.1.cmp(right.1).then_with(|| right.0.cmp(left.0)))
        .map(|(key, _)| key.clone())
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

fn clean(value: &str) -> String {
    value
        .replace('\t', " ")
        .replace('\r', " ")
        .replace('\n', " ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn snippet(text: &str, range: TextRange) -> String {
    let start = range.start as usize;
    let end = range.end as usize;
    let left = text[..start.min(text.len())]
        .rfind(['\n', '.', '!', '?'])
        .map(|idx| idx + 1)
        .unwrap_or(start.saturating_sub(96));
    let right = text[end.min(text.len())..]
        .find(['\n', '.', '!', '?'])
        .map(|idx| end.min(text.len()) + idx + 1)
        .unwrap_or((end + 96).min(text.len()));
    let left = floor_char_boundary(text, left.min(text.len()));
    let right = floor_char_boundary(text, right.min(text.len()));
    clean(text.get(left..right).unwrap_or(""))
}

fn floor_char_boundary(text: &str, mut index: usize) -> usize {
    while index > 0 && !text.is_char_boundary(index) {
        index -= 1;
    }
    index
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

fn env_usize(name: &str, default: usize) -> usize {
    env::var(name)
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}

fn env_f32(name: &str, default: f32) -> f32 {
    env::var(name)
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}
