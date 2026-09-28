use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::Path;
use std::time::{Duration, Instant};

use compact_str::CompactString;
use phoenix_alex::Lexicon;
use phoenix_dynamic_ner::{
    resolve_aliases, resolve_identity_dag, AliasRegistryEntity, AliasResolutionInput,
    DiscoveredSpan, DynamicNerModel, DynamicSchemaBuilder, EntityLabel, IdentityResolutionInput,
    LabelPack, LocalMentionId, MentionKind, MentionPacket, MentionVote, ModelNerWindow,
    NerModelError, PhoenixNerEngineBuilder, SurfaceNerInput, SurfaceRouter, VerificationCase,
};
use phoenix_rel_post::{GlinerBiModel, GlinerBiOverlapPolicy, GlinerBiPredictOptions};
use phoenix_types::{
    EntityId, EntityKind, LexiconEntry, ScopeKey, SentenceSpan, TextRange, TokenClass, TokenSpan,
};

const STORY_NAMES: &[&str] = &[
    "Aella", "Aurora", "Brynwyn", "Iriane", "Isolde", "Kai", "Phaeris", "Rowan", "Siofra",
];

struct CliGlinerModel {
    model: GlinerBiModel,
    threshold: f32,
    overlap_policy: GlinerBiOverlapPolicy,
}

impl CliGlinerModel {
    fn load(
        path: impl AsRef<Path>,
        threshold: f32,
        overlap_policy: GlinerBiOverlapPolicy,
    ) -> Result<Self, String> {
        let model = GlinerBiModel::load(path.as_ref()).map_err(|err| format!("{err:?}"))?;
        Ok(Self {
            model,
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

        let options = GlinerBiPredictOptions {
            threshold: self.threshold,
            overlap_policy: self.overlap_policy,
            ..Default::default()
        };
        let predictions = self
            .model
            .predict_with_options(window.text, &model_labels, &options)
            .map_err(|err| NerModelError::Inference(err.to_string()))?;

        Ok(predictions
            .into_iter()
            .map(|prediction| {
                let label = match prediction.label.as_str() {
                    "Person" => "Character",
                    "Organization" => "Organization",
                    "Location" => "Location",
                    other => other,
                };
                DiscoveredSpan {
                    window_relative_range: TextRange {
                        start: prediction.span_start as u32,
                        end: prediction.span_end as u32,
                    },
                    surface: CompactString::new(&prediction.text),
                    label: EntityLabel::new(label),
                    confidence: prediction.score,
                }
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

fn story_lexicon() -> Result<Lexicon, String> {
    let entries = STORY_NAMES
        .iter()
        .map(|name| LexiconEntry {
            entity_id: EntityId(name.to_ascii_lowercase()),
            label: (*name).to_owned(),
            aliases: Vec::new(),
            kind: Some(EntityKind::Character),
            gender: None,
            number: None,
            scope: ScopeKey::default(),
        })
        .collect::<Vec<_>>();
    Lexicon::from_entries(&entries).map_err(|err| format!("{err:?}"))
}

fn story_alias_registry() -> Vec<AliasRegistryEntity> {
    STORY_NAMES
        .iter()
        .map(|name| AliasRegistryEntity {
            entity_id: EntityId(name.to_ascii_lowercase()),
            canonical_name: (*name).to_owned(),
            kind: Some(EntityKind::Character),
            aliases: Vec::new(),
        })
        .collect()
}

fn naive_tokenize(text: &str) -> (Vec<TokenSpan>, Vec<SentenceSpan>) {
    let mut tokens = Vec::new();
    let mut sentences = Vec::new();
    let mut sent_start = 0usize;
    let mut start = None;
    for (idx, ch) in text.char_indices() {
        if ch.is_alphanumeric() || ch == '\'' || ch == '-' {
            start.get_or_insert(idx);
        } else if let Some(s) = start.take() {
            tokens.push(TokenSpan {
                range: TextRange {
                    start: s as u32,
                    end: idx as u32,
                },
                capitalized: text[s..].starts_with(|c: char| c.is_uppercase()),
                pos: None,
                token_class: Some(TokenClass::Word),
                masked: false,
            });
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
        tokens.push(TokenSpan {
            range: TextRange {
                start: s as u32,
                end: text.len() as u32,
            },
            capitalized: text[s..].starts_with(|c: char| c.is_uppercase()),
            pos: None,
            token_class: Some(TokenClass::Word),
            masked: false,
        });
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

fn median(mut values: Vec<u128>) -> u128 {
    if values.is_empty() {
        return 0;
    }
    values.sort_unstable();
    values[values.len() / 2]
}

fn format_duration_us(us: u128) -> String {
    if us >= 1_000 {
        format!("{:.3} ms", us as f64 / 1_000.0)
    } else {
        format!("{us} us")
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = env::args()
        .nth(1)
        .unwrap_or_else(|| "docs\\shortrun.md".to_owned());
    let runs = env::args()
        .nth(2)
        .and_then(|arg| arg.parse::<usize>().ok())
        .unwrap_or(3)
        .max(1);
    let model_path = env::args()
        .nth(3)
        .unwrap_or_else(|| "gliner-bi-onnx".to_owned());
    let threshold = env::var("PHOENIX_DYN_NER_THRESHOLD")
        .ok()
        .and_then(|value| value.parse::<f32>().ok())
        .unwrap_or(0.35);
    let overlap_policy = env::var("PHOENIX_DYN_NER_OVERLAP_POLICY")
        .ok()
        .map(|value| GlinerBiOverlapPolicy::parse(&value))
        .transpose()?
        .unwrap_or_default();
    let max_labels = env::var("PHOENIX_DYN_NER_MAX_LABELS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or_else(|| DynamicSchemaBuilder::default().max_labels);
    let summary_only = env::var("PHOENIX_DYN_NER_SUMMARY_ONLY")
        .ok()
        .is_some_and(|value| matches!(value.as_str(), "1" | "true" | "TRUE" | "yes" | "YES"));
    let max_model_windows = env::var("PHOENIX_DYN_NER_MAX_MODEL_WINDOWS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|&value| value > 0);

    let text = fs::read_to_string(&path)?;
    let (tokens, sentences) = naive_tokenize(&text);
    let lexicon = story_lexicon()?;
    let scope = ScopeKey::default();

    let load_started = Instant::now();
    let model = CliGlinerModel::load(&model_path, threshold, overlap_policy)?;
    let load_us = load_started.elapsed().as_micros();
    let schema = DynamicSchemaBuilder {
        max_labels,
        ..Default::default()
    };
    let mut builder = PhoenixNerEngineBuilder::new()
        .schema(schema)
        .model(Box::new(model));
    if let Some(max_model_windows) = max_model_windows {
        builder = builder.router(SurfaceRouter { max_model_windows });
    }
    let engine = builder.build();

    let input = SurfaceNerInput {
        document_id: "shortrun",
        text: &text,
        scope: &scope,
        tokens: &tokens,
        sentences: &sentences,
        lexicon: Some(&lexicon),
        surface_hits: &[],
        label_bank_context: None,
    };

    let warm_started = Instant::now();
    let _ = engine.extract_mentions(&input)?;
    let warm_us = warm_started.elapsed().as_micros();

    let mut timings = Vec::with_capacity(runs);
    let mut last_output = None;
    for _ in 0..runs {
        let started = Instant::now();
        let output = engine.extract_mentions(&input)?;
        timings.push(started.elapsed());
        last_output = Some(output);
    }

    let output = last_output.expect("at least one run");
    let registry_entities = story_alias_registry();
    let alias_report = resolve_aliases(&AliasResolutionInput {
        document_id: "shortrun",
        mentions: &output.mentions,
        surface_memory: &output.surface_memory,
        registry_entities: &registry_entities,
    });
    let identity_dag = resolve_identity_dag(&IdentityResolutionInput {
        document_id: "shortrun",
        mentions: &output.mentions,
        mention_graph: &output.mention_graph,
        surface_memory: &output.surface_memory,
        alias_report: Some(&alias_report),
        registry_entities: &registry_entities,
        linker_candidates: &[],
    });
    let timing_us: Vec<u128> = timings.iter().map(Duration::as_micros).collect();
    let best = timing_us.iter().copied().min().unwrap_or(0);
    let worst = timing_us.iter().copied().max().unwrap_or(0);
    let med = median(timing_us.clone());

    let mut grouped: BTreeMap<&'static str, BTreeMap<String, String>> = BTreeMap::new();
    let mut source_counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut status_counts: BTreeMap<String, usize> = BTreeMap::new();
    for mention in &output.mentions {
        if mention.mention_kind == MentionKind::Named {
            let label = best_label(mention);
            let group = normalize_group(&label);
            grouped
                .entry(group)
                .or_default()
                .entry(mention.normalized.to_string())
                .or_insert_with(|| mention.surface.to_string());
        }
        for vote in &mention.source_votes {
            *source_counts
                .entry(format!("{:?}", vote.source))
                .or_default() += 1;
        }
        *status_counts
            .entry(format!("{:?}", mention.status))
            .or_default() += 1;
    }

    println!("ENGINE dynamic_ner");
    println!("DOC {path}");
    println!("MODEL {model_path}");
    println!("THRESHOLD {threshold:.2}");
    println!("OVERLAP_POLICY {overlap_policy:?}");
    println!("MAX_LABELS {max_labels}");
    if let Some(max_model_windows) = max_model_windows {
        println!("MAX_MODEL_WINDOWS {max_model_windows}");
    }
    println!("BYTES {}", text.len());
    println!("CHARS {}", text.chars().count());
    println!("TOKENS {}", tokens.len());
    println!("RUNS {runs} warm_only=true");
    println!(
        "COLD load={} warmup={} excluded=true",
        format_duration_us(load_us),
        format_duration_us(warm_us)
    );
    println!(
        "TIME best={} median={} worst={}",
        format_duration_us(best),
        format_duration_us(med),
        format_duration_us(worst)
    );
    println!(
        "COUNTS mentions={} mention_edges={}",
        output.mentions.len(),
        output.mention_graph.edges.len()
    );
    println!(
        "ALIAS proposals={} known={} run_local={} deferred={}",
        alias_report.question_count,
        alias_report.known_candidate_count,
        alias_report.run_local_candidate_count,
        alias_report.deferred_count
    );
    println!(
        "IDENTITY nodes={} edges={} receipts={} known={} alias={} merge={} split={} defer={} new={}",
        identity_dag.summary.node_count,
        identity_dag.summary.edge_count,
        identity_dag.summary.receipt_count,
        identity_dag.summary.known_decisions,
        identity_dag.summary.alias_decisions,
        identity_dag.summary.merge_decisions,
        identity_dag.summary.split_decisions,
        identity_dag.summary.deferred_decisions,
        identity_dag.summary.new_entity_decisions
    );
    println!("SOURCES");
    for (source, count) in source_counts {
        println!("  {source}: {count}");
    }
    println!("STATUS");
    for (status, count) in status_counts {
        println!("  {status}: {count}");
    }
    println!(
        "SUMMARY model={} threshold={threshold:.2} overlap={overlap_policy:?} max_labels={max_labels} load_us={load_us} warm_us={warm_us} best_us={best} median_us={med} worst_us={worst} mentions={} mention_edges={} identity_receipts={}",
        model_path,
        output.mentions.len(),
        output.mention_graph.edges.len(),
        identity_dag.summary.receipt_count
    );

    if summary_only {
        return Ok(());
    }

    println!("GROUPS");
    for (group, surfaces) in grouped {
        let ordered: BTreeSet<_> = surfaces.values().cloned().collect();
        let list = ordered.into_iter().collect::<Vec<_>>().join(" | ");
        println!("  {group}: {} :: {list}", surfaces.len());
    }

    Ok(())
}
