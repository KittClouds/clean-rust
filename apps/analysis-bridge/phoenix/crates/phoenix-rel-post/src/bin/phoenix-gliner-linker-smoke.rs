use std::fs::File;
use std::path::{Path, PathBuf};

use hashbrown::{HashMap, HashSet};
use memmap2::Mmap;
use phoenix_rel_post::{
    GlinerBiInputSpan, GlinerBiModel, GlinerBiModelMetadata, GlinerBiOverlapPolicy,
    GlinerBiPredictOptions,
};
use serde::Serialize;

#[derive(Debug, Clone)]
struct LinkEntity {
    id: String,
    label: String,
    kind: String,
    aliases: Vec<String>,
    description: String,
}

#[derive(Debug, Clone)]
struct LinkMention {
    surface: String,
    start: usize,
    end: usize,
    kind: Option<String>,
}

#[derive(Debug, Clone)]
struct SmokeConfig {
    model_root: PathBuf,
    text: String,
    entities: Vec<LinkEntity>,
    mentions: Vec<LinkMention>,
    threshold: f32,
    template: String,
    window_chars: usize,
    candidates_per_mention: usize,
    prediction_limit: usize,
    json: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SmokeReport {
    ok: bool,
    entity_count: usize,
    mention_count: usize,
    label_count: usize,
    threshold: f32,
    template: String,
    window_chars: usize,
    window_count: usize,
    candidate_evaluations: usize,
    candidates_per_mention: usize,
    prediction_limit: usize,
    raw_prediction_count: usize,
    model: GlinerBiModelMetadata,
    predictions: Vec<LinkPrediction>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct LinkPrediction {
    requested_surface: String,
    mention_text: String,
    mention_start: usize,
    mention_end: usize,
    candidate_entity_id: String,
    candidate_label: String,
    candidate_kind: String,
    model_label: String,
    score: f32,
}

fn main() -> Result<(), String> {
    let mut config = parse_args(&std::env::args().collect::<Vec<_>>())?;
    if config.mentions.is_empty() {
        config.mentions = auto_mentions(&config.text, &config.entities);
    }
    config
        .mentions
        .sort_by_key(|mention| (mention.start, mention.end));

    let mention_surface_by_span = config
        .mentions
        .iter()
        .map(|mention| ((mention.start, mention.end), mention.surface.as_str()))
        .collect::<HashMap<_, _>>();

    let model = GlinerBiModel::load(&config.model_root).map_err(|error| {
        format!(
            "failed to load GLiNER linker-compatible model {}: {error}",
            config.model_root.display()
        )
    })?;
    let options = GlinerBiPredictOptions {
        threshold: config.threshold,
        overlap_policy: GlinerBiOverlapPolicy::HighestScore,
    };
    let (raw_predictions, window_count, candidate_evaluations) =
        predict_linker_windows(&model, &config, &options)?;
    let mut predictions = raw_predictions
        .into_iter()
        .map(|prediction| {
            let entity = &config.entities[prediction.entity_index];
            LinkPrediction {
                requested_surface: mention_surface_by_span
                    .get(&(prediction.span_start, prediction.span_end))
                    .copied()
                    .unwrap_or(prediction.mention_text.as_str())
                    .to_owned(),
                mention_text: prediction.mention_text,
                mention_start: prediction.span_start,
                mention_end: prediction.span_end,
                candidate_entity_id: entity.id.clone(),
                candidate_label: entity.label.clone(),
                candidate_kind: entity.kind.clone(),
                model_label: prediction.label,
                score: prediction.score,
            }
        })
        .collect::<Vec<_>>();
    let raw_prediction_count = predictions.len();
    if config.prediction_limit > 0 && predictions.len() > config.prediction_limit {
        predictions.truncate(config.prediction_limit);
    }

    let report = SmokeReport {
        ok: true,
        entity_count: config.entities.len(),
        mention_count: config.mentions.len(),
        label_count: config.entities.len(),
        threshold: config.threshold,
        template: config.template,
        window_chars: config.window_chars,
        window_count,
        candidate_evaluations,
        candidates_per_mention: config.candidates_per_mention,
        prediction_limit: config.prediction_limit,
        raw_prediction_count,
        model: model.metadata().clone(),
        predictions,
    };

    if config.json {
        println!("{}", serde_json::to_string_pretty(&report).unwrap());
    } else {
        print_report(&report);
    }
    Ok(())
}

fn parse_args(args: &[String]) -> Result<SmokeConfig, String> {
    let mut model_root = None;
    let mut text = None;
    let mut text_file = None;
    let mut entities = Vec::new();
    let mut mentions = Vec::new();
    let mut threshold = 0.5;
    let mut template = "{label}: {description}".to_owned();
    let mut window_chars = 900;
    let mut candidates_per_mention = 6;
    let mut prediction_limit = 64;
    let mut json = false;
    let mut i = 1;

    while i < args.len() {
        let arg = &args[i];
        if arg == "--model" && i + 1 < args.len() {
            model_root = Some(PathBuf::from(&args[i + 1]));
            i += 2;
        } else if arg == "--text" && i + 1 < args.len() {
            text = Some(args[i + 1].clone());
            i += 2;
        } else if arg == "--text-file" && i + 1 < args.len() {
            text_file = Some(PathBuf::from(&args[i + 1]));
            i += 2;
        } else if arg == "--entity" && i + 1 < args.len() {
            entities.push(parse_entity(&args[i + 1])?);
            i += 2;
        } else if arg == "--mention" && i + 1 < args.len() {
            mentions.push(parse_mention(&args[i + 1])?);
            i += 2;
        } else if arg == "--threshold" && i + 1 < args.len() {
            threshold = args[i + 1].parse().map_err(|_| "invalid threshold")?;
            i += 2;
        } else if arg == "--template" && i + 1 < args.len() {
            template = args[i + 1].clone();
            i += 2;
        } else if arg == "--window-chars" && i + 1 < args.len() {
            window_chars = args[i + 1].parse().map_err(|_| "invalid window chars")?;
            i += 2;
        } else if arg == "--candidates-per-mention" && i + 1 < args.len() {
            candidates_per_mention = args[i + 1]
                .parse()
                .map_err(|_| "invalid candidates per mention")?;
            i += 2;
        } else if arg == "--limit" && i + 1 < args.len() {
            prediction_limit = args[i + 1].parse().map_err(|_| "invalid limit")?;
            i += 2;
        } else if arg == "--json" {
            json = true;
            i += 1;
        } else {
            return Err(format!("unknown argument: {arg}"));
        }
    }

    let text = match (text, text_file) {
        (Some(text), _) => text,
        (None, Some(path)) => read_text_file(&path)?,
        (None, None) => "Ryan met Renesco in New Rome.".to_owned(),
    };
    if entities.is_empty() {
        entities = vec![
            entity("e-ryan", "Ryan", "CHARACTER", "time-loop courier"),
            entity(
                "e-renesco",
                "Renesco",
                "CHARACTER",
                "barman at Jolie Wrangler",
            ),
            entity("e-new-rome", "New Rome", "LOCATION", "metropolis in Italy"),
        ];
    }

    Ok(SmokeConfig {
        model_root: model_root.unwrap_or_else(|| PathBuf::from("gliner-linker-onnx")),
        text,
        entities,
        mentions,
        threshold,
        template,
        window_chars,
        candidates_per_mention,
        prediction_limit,
        json,
    })
}

fn parse_entity(value: &str) -> Result<LinkEntity, String> {
    let parts = value.split('|').collect::<Vec<_>>();
    if parts.len() < 2 {
        return Err("--entity expects id|label|kind|aliases|description".to_owned());
    }
    Ok(LinkEntity {
        id: parts[0].trim().to_owned(),
        label: parts[1].trim().to_owned(),
        kind: parts.get(2).copied().unwrap_or("").trim().to_owned(),
        aliases: parts
            .get(3)
            .copied()
            .unwrap_or("")
            .split([',', ';'])
            .map(str::trim)
            .filter(|alias| !alias.is_empty())
            .map(ToOwned::to_owned)
            .collect(),
        description: parts.get(4).copied().unwrap_or("").trim().to_owned(),
    })
}

fn parse_mention(value: &str) -> Result<LinkMention, String> {
    let parts = value.split('|').collect::<Vec<_>>();
    if parts.len() < 3 {
        return Err("--mention expects surface|start|end or surface|start|end|kind".to_owned());
    }
    Ok(LinkMention {
        surface: parts[0].trim().to_owned(),
        start: parts[1]
            .trim()
            .parse()
            .map_err(|_| "invalid mention start")?,
        end: parts[2].trim().parse().map_err(|_| "invalid mention end")?,
        kind: parts
            .get(3)
            .map(|value| value.trim())
            .filter(|value| !value.is_empty())
            .map(ToOwned::to_owned),
    })
}

fn read_text_file(path: &Path) -> Result<String, String> {
    let file = File::open(path).map_err(|error| format!("open {}: {error}", path.display()))?;
    let mmap =
        unsafe { Mmap::map(&file) }.map_err(|error| format!("mmap {}: {error}", path.display()))?;
    String::from_utf8(mmap.to_vec()).map_err(|error| format!("utf8 {}: {error}", path.display()))
}

fn auto_mentions(text: &str, entities: &[LinkEntity]) -> Vec<LinkMention> {
    let haystack = text.to_ascii_lowercase();
    let mut seen = HashSet::<(usize, usize)>::new();
    let mut mentions = Vec::new();
    for entity in entities {
        for surface in entity_surfaces(entity) {
            if surface.len() < 2 {
                continue;
            }
            let needle = surface.to_ascii_lowercase();
            let mut cursor = 0;
            while let Some(relative) = haystack[cursor..].find(&needle) {
                let start = cursor + relative;
                let end = start + needle.len();
                cursor = end;
                if !is_boundary(text, start, end) || !seen.insert((start, end)) {
                    continue;
                }
                mentions.push(LinkMention {
                    surface: text[start..end].to_owned(),
                    start,
                    end,
                    kind: Some(entity.kind.clone()),
                });
            }
        }
    }
    mentions.sort_by_key(|mention| (mention.start, mention.end));
    mentions
}

fn entity_surfaces(entity: &LinkEntity) -> Vec<&str> {
    let mut out = Vec::with_capacity(entity.aliases.len() + 1);
    out.push(entity.label.as_str());
    out.extend(entity.aliases.iter().map(String::as_str));
    out
}

fn is_boundary(text: &str, start: usize, end: usize) -> bool {
    let left = text[..start].chars().next_back();
    let right = text[end..].chars().next();
    !left.is_some_and(is_word_char) && !right.is_some_and(is_word_char)
}

fn is_word_char(value: char) -> bool {
    value.is_alphanumeric() || value == '_'
}

fn format_candidate_label(template: &str, entity: &LinkEntity) -> String {
    template
        .replace("{entity_id}", &entity.id)
        .replace("{label}", &entity.label)
        .replace("{aliases}", &entity.aliases.join(", "))
        .replace("{description}", &entity.description)
        .replace("{entity_type}", &entity.kind)
}

fn predict_linker_windows(
    model: &GlinerBiModel,
    config: &SmokeConfig,
    options: &GlinerBiPredictOptions,
) -> Result<(Vec<LinkerRawPrediction>, usize, usize), String> {
    if config.mentions.is_empty() {
        return Ok((Vec::new(), 0, 0));
    }
    if config.window_chars == 0 || config.text.len() <= config.window_chars {
        let all_indices = (0..config.mentions.len()).collect::<Vec<_>>();
        let window = MentionWindow {
            start: 0,
            end: config.text.len(),
            mention_indices: all_indices,
        };
        let (predictions, evaluations) = predict_linker_window(model, config, &window, options)?;
        return Ok((predictions, 1, evaluations));
    }

    let windows = mention_windows(&config.text, &config.mentions, config.window_chars);
    let mut predictions = Vec::new();
    let mut candidate_evaluations = 0;
    for window in &windows {
        let (local, evaluations) = predict_linker_window(model, config, window, options)?;
        candidate_evaluations += evaluations;
        predictions.extend(local);
    }
    Ok((predictions, windows.len(), candidate_evaluations))
}

#[derive(Debug)]
struct LinkerRawPrediction {
    mention_text: String,
    span_start: usize,
    span_end: usize,
    entity_index: usize,
    label: String,
    score: f32,
}

fn predict_linker_window(
    model: &GlinerBiModel,
    config: &SmokeConfig,
    window: &MentionWindow,
    options: &GlinerBiPredictOptions,
) -> Result<(Vec<LinkerRawPrediction>, usize), String> {
    let local_text = &config.text[window.start..window.end];
    let local_spans = window
        .mention_indices
        .iter()
        .map(|&idx| GlinerBiInputSpan {
            start: config.mentions[idx].start - window.start,
            end: config.mentions[idx].end - window.start,
        })
        .collect::<Vec<_>>();
    let label_rows = retrieve_window_candidates(config, &window.mention_indices);
    if label_rows.is_empty() || local_spans.is_empty() {
        return Ok((Vec::new(), 0));
    }
    let labels = label_rows
        .iter()
        .map(|row| row.label.clone())
        .collect::<Vec<_>>();
    let label_to_entity = label_rows
        .iter()
        .map(|row| (row.label.as_str(), row.entity_index))
        .collect::<HashMap<_, _>>();
    let mut local = model
        .predict_constrained(local_text, &labels, &local_spans, options)
        .map_err(|error| format!("GLiNER linker inference failed: {error}"))?;
    let mut out = Vec::with_capacity(local.len());
    for row in local.drain(..) {
        let Some(&entity_index) = label_to_entity.get(row.label.as_str()) else {
            continue;
        };
        out.push(LinkerRawPrediction {
            mention_text: row.text,
            span_start: row.span_start + window.start,
            span_end: row.span_end + window.start,
            entity_index,
            label: row.label,
            score: row.score,
        });
    }
    Ok((out, labels.len() * local_spans.len()))
}

#[derive(Debug)]
struct CandidateLabel {
    entity_index: usize,
    label: String,
}

fn retrieve_window_candidates(
    config: &SmokeConfig,
    mention_indices: &[usize],
) -> Vec<CandidateLabel> {
    let mut seen = HashSet::<usize>::new();
    let mut out = Vec::new();
    for &mention_idx in mention_indices {
        let mention = &config.mentions[mention_idx];
        for candidate in retrieve_mention_candidates(config, mention) {
            if !seen.insert(candidate) {
                continue;
            }
            out.push(CandidateLabel {
                entity_index: candidate,
                label: format_candidate_label(&config.template, &config.entities[candidate]),
            });
        }
    }
    out
}

fn retrieve_mention_candidates(config: &SmokeConfig, mention: &LinkMention) -> Vec<usize> {
    let mut ranked = config
        .entities
        .iter()
        .enumerate()
        .filter_map(|(index, entity)| {
            let score = candidate_score(mention, entity);
            (score > 0.0).then_some((index, score))
        })
        .collect::<Vec<_>>();
    ranked.sort_by(|left, right| {
        right
            .1
            .partial_cmp(&left.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                config.entities[left.0]
                    .label
                    .cmp(&config.entities[right.0].label)
            })
    });
    ranked
        .into_iter()
        .take(config.candidates_per_mention.max(1))
        .map(|(index, _)| index)
        .collect()
}

fn candidate_score(mention: &LinkMention, entity: &LinkEntity) -> f32 {
    let mention_norm = normalize_for_match(&mention.surface);
    if mention_norm.is_empty() {
        return 0.0;
    }
    let mut score = surface_score(&mention_norm, &normalize_for_match(&entity.label));
    for alias in &entity.aliases {
        score = score.max(surface_score(&mention_norm, &normalize_for_match(alias)) * 0.98);
    }
    if let Some(kind) = &mention.kind {
        let mention_kind = kind_family(kind);
        let entity_kind = kind_family(&entity.kind);
        if !mention_kind.is_empty() && mention_kind == entity_kind {
            score += 0.12;
        } else if !mention_kind.is_empty() && !entity_kind.is_empty() {
            score -= 0.08;
        }
    }
    score.clamp(0.0, 1.0)
}

fn surface_score(left: &str, right: &str) -> f32 {
    if left.is_empty() || right.is_empty() {
        return 0.0;
    }
    if left == right {
        return 1.0;
    }
    if left.contains(right) || right.contains(left) {
        return 0.72;
    }
    let left_tokens = token_set(left);
    let right_tokens = token_set(right);
    if left_tokens.is_empty() || right_tokens.is_empty() {
        return 0.0;
    }
    let shared = left_tokens
        .iter()
        .filter(|token| right_tokens.contains(**token))
        .count();
    let union = left_tokens.len() + right_tokens.len() - shared;
    let jaccard = shared as f32 / union.max(1) as f32;
    if jaccard >= 0.34 {
        return 0.42 + jaccard * 0.24;
    }
    0.0
}

fn token_set(value: &str) -> HashSet<&str> {
    value
        .split(' ')
        .filter(|token| token.len() > 1)
        .collect::<HashSet<_>>()
}

fn normalize_for_match(value: &str) -> String {
    value
        .to_ascii_lowercase()
        .split(|ch: char| !ch.is_alphanumeric())
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

fn kind_family(value: &str) -> String {
    match value.trim().to_ascii_uppercase().as_str() {
        "PERSON" | "NPC" => "CHARACTER".to_owned(),
        "ORGANIZATION" | "FACTION" => "NETWORK".to_owned(),
        other => other.to_owned(),
    }
}

#[derive(Debug)]
struct MentionWindow {
    start: usize,
    end: usize,
    mention_indices: Vec<usize>,
}

fn mention_windows(
    text: &str,
    mentions: &[LinkMention],
    window_chars: usize,
) -> Vec<MentionWindow> {
    let mut windows = Vec::new();
    let mut idx = 0;
    while idx < mentions.len() {
        let mention = &mentions[idx];
        let half = window_chars / 2;
        let mut start = mention.start.saturating_sub(half);
        let mut end = (start + window_chars).min(text.len());
        if mention.end > end {
            end = mention.end;
        }
        start = snap_left_char_boundary(text, start);
        end = snap_right_char_boundary(text, end);

        let mut mention_indices = Vec::new();
        while idx < mentions.len() {
            let candidate = &mentions[idx];
            if candidate.start < start || candidate.end > end {
                break;
            }
            mention_indices.push(idx);
            idx += 1;
        }
        if mention_indices.is_empty() {
            mention_indices.push(idx);
            idx += 1;
        }
        windows.push(MentionWindow {
            start,
            end,
            mention_indices,
        });
    }
    windows
}

fn snap_left_char_boundary(text: &str, mut idx: usize) -> usize {
    while idx > 0 && !text.is_char_boundary(idx) {
        idx -= 1;
    }
    idx
}

fn snap_right_char_boundary(text: &str, mut idx: usize) -> usize {
    while idx < text.len() && !text.is_char_boundary(idx) {
        idx += 1;
    }
    idx
}

fn entity(id: &str, label: &str, kind: &str, description: &str) -> LinkEntity {
    LinkEntity {
        id: id.to_owned(),
        label: label.to_owned(),
        kind: kind.to_owned(),
        aliases: Vec::new(),
        description: description.to_owned(),
    }
}

fn print_report(report: &SmokeReport) {
    println!("\n=== GLiNER Linker Smoke ===");
    println!("Model: {}", report.model.model_path);
    println!(
        "Entities: {} | Mentions: {} | Labels: {} | Windows: {} @ {} chars | Candidate evals: {} | TopK: {} | Threshold: {:.2}",
        report.entity_count,
        report.mention_count,
        report.label_count,
        report.window_count,
        report.window_chars,
        report.candidate_evaluations,
        report.candidates_per_mention,
        report.threshold
    );
    if report.prediction_limit > 0 {
        println!(
            "Predictions: {} shown / {} total",
            report.predictions.len(),
            report.raw_prediction_count
        );
    }
    for (index, row) in report.predictions.iter().enumerate() {
        println!(
            "  [{}] {:?} -> {} ({}) {:.1}%",
            index + 1,
            row.mention_text,
            row.candidate_label,
            row.candidate_kind,
            row.score * 100.0
        );
    }
    if report.predictions.is_empty() {
        println!("  (No links above threshold)");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retriever_prefers_exact_alias_for_dynamic_anchor() {
        let config = SmokeConfig {
            model_root: PathBuf::new(),
            text: "Chapter 1: Quicksave".to_owned(),
            entities: vec![
                LinkEntity {
                    id: "e-ryan".to_owned(),
                    label: "Ryan".to_owned(),
                    kind: "CHARACTER".to_owned(),
                    aliases: vec!["Quicksave".to_owned()],
                    description: "time-loop courier".to_owned(),
                },
                LinkEntity {
                    id: "e-new-rome".to_owned(),
                    label: "New Rome".to_owned(),
                    kind: "LOCATION".to_owned(),
                    aliases: Vec::new(),
                    description: "metropolis in Italy".to_owned(),
                },
            ],
            mentions: vec![LinkMention {
                surface: "Quicksave".to_owned(),
                start: 11,
                end: 20,
                kind: Some("CHARACTER".to_owned()),
            }],
            threshold: 0.5,
            template: "{label}; aliases: {aliases}; {description}".to_owned(),
            window_chars: 900,
            candidates_per_mention: 2,
            prediction_limit: 64,
            json: false,
        };

        let candidates = retrieve_mention_candidates(&config, &config.mentions[0]);

        assert_eq!(candidates.first().copied(), Some(0));
    }

    #[test]
    fn window_candidates_use_only_mentioned_anchor_candidates() {
        let config = SmokeConfig {
            model_root: PathBuf::new(),
            text: "Ryan crossed New Rome.".to_owned(),
            entities: vec![
                LinkEntity {
                    id: "e-ryan".to_owned(),
                    label: "Ryan".to_owned(),
                    kind: "CHARACTER".to_owned(),
                    aliases: Vec::new(),
                    description: String::new(),
                },
                LinkEntity {
                    id: "e-new-rome".to_owned(),
                    label: "New Rome".to_owned(),
                    kind: "LOCATION".to_owned(),
                    aliases: Vec::new(),
                    description: String::new(),
                },
                LinkEntity {
                    id: "e-renesco".to_owned(),
                    label: "Renesco".to_owned(),
                    kind: "CHARACTER".to_owned(),
                    aliases: Vec::new(),
                    description: String::new(),
                },
            ],
            mentions: vec![LinkMention {
                surface: "Ryan".to_owned(),
                start: 0,
                end: 4,
                kind: Some("CHARACTER".to_owned()),
            }],
            threshold: 0.5,
            template: "{label}".to_owned(),
            window_chars: 900,
            candidates_per_mention: 1,
            prediction_limit: 64,
            json: false,
        };

        let labels = retrieve_window_candidates(&config, &[0]);

        assert_eq!(labels.len(), 1);
        assert_eq!(labels[0].entity_index, 0);
        assert_eq!(labels[0].label, "Ryan");
    }
}
