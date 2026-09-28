mod pipeline_parity_support;

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use compact_str::CompactString;
use phoenix_dynamic_ner::{
    DiscoveredSpan, DynamicNerModel, DynamicSchemaBuilder, EntityLabel, LabelPack,
    LexicalSemanticLabelRouter, LocalMentionId, MentionVote, ModelNerRequest, ModelNerWindow,
    NerModelError, PhoenixNerEngineBuilder, SemanticLabelRouter, SurfaceNerInput,
    SurfaceNerMetrics, SurfaceRouter, VerificationCase,
};
use phoenix_rel_post::{
    GlinerBiModel, GlinerBiOverlapPolicy, GlinerBiPredictOptions, GlinerXModel,
};
use phoenix_types::{ScopeKey, TextRange};

use pipeline_parity_support::{
    clean, print_delta, print_summary, story_lexicon, summarize, tokenize, DocSummary,
};

struct BiBackend {
    model: GlinerBiModel,
    threshold: f32,
    overlap_policy: GlinerBiOverlapPolicy,
}

struct XBackend {
    model: GlinerXModel,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let docs = args_or_default();
    let threshold = env_f32("PHOENIX_DYN_NER_THRESHOLD", 0.35);
    let max_labels = env_usize(
        "PHOENIX_DYN_NER_MAX_LABELS",
        DynamicSchemaBuilder::default().max_labels,
    );
    let max_model_windows = env_usize("PHOENIX_DYN_NER_MAX_MODEL_WINDOWS", 256);
    let bi_path = env::var("PHOENIX_DYN_NER_BI_MODEL_PATH")
        .or_else(|_| env::var("PHOENIX_DYN_NER_MODEL_PATH"))
        .unwrap_or_else(|_| {
            if Path::new("D:\\hf-models\\gliner-bi-base-v2.0-onnx").is_dir() {
                "D:\\hf-models\\gliner-bi-base-v2.0-onnx".to_owned()
            } else {
                "gliner-bi-small-onnx".to_owned()
            }
        });
    let x_path = env::var("PHOENIX_DYN_NER_X_MODEL_PATH").unwrap_or_else(|_| {
        if Path::new("D:\\hf-models\\gliner-x-small-bi-compat").is_dir() {
            "D:\\hf-models\\gliner-x-small-bi-compat".to_owned()
        } else {
            "G:\\hf-models\\gliner-x-small".to_owned()
        }
    });
    let backend_selection = env::var("PHOENIX_DYN_NER_BACKENDS").unwrap_or_else(|_| "both".into());
    let run_bi = backend_selection != "x";
    let run_x = backend_selection != "bi";
    let overlap_policy = env::var("PHOENIX_DYN_NER_OVERLAP_POLICY")
        .ok()
        .map(|value| GlinerBiOverlapPolicy::parse(&value))
        .transpose()?
        .unwrap_or_default();
    println!(
        "PARITY_CONFIG\tbackends={backend_selection}\tthreshold={threshold:.3}\tmax_labels={max_labels}\tmax_model_windows={max_model_windows}\tbi_model={}\tx_model={}",
        clean(&bi_path),
        clean(&x_path)
    );

    let bi = if run_bi {
        Some(load_bi(
            &bi_path,
            threshold,
            overlap_policy,
            max_labels,
            max_model_windows,
        )?)
    } else {
        None
    };
    let x = if run_x {
        Some(load_x(&x_path, threshold, max_labels, max_model_windows)?)
    } else {
        None
    };
    let mut by_doc = BTreeMap::<String, Vec<DocSummary>>::new();

    for doc in &docs {
        if let Some(engine) = bi.as_ref() {
            by_doc
                .entry(doc.clone())
                .or_default()
                .push(run_doc("bi", engine, doc)?);
        }
        if let Some(engine) = x.as_ref() {
            by_doc
                .entry(doc.clone())
                .or_default()
                .push(run_doc("x", engine, doc)?);
        }
    }

    for summaries in by_doc.values() {
        for summary in summaries {
            print_summary(summary);
        }
        if let [left, right] = summaries.as_slice() {
            print_delta(left, right);
        }
    }
    Ok(())
}

fn load_bi(
    path: &str,
    threshold: f32,
    overlap_policy: GlinerBiOverlapPolicy,
    max_labels: usize,
    max_model_windows: usize,
) -> Result<phoenix_dynamic_ner::PhoenixNerEngine, String> {
    let started = Instant::now();
    let backend = BiBackend {
        model: GlinerBiModel::load(Path::new(path)).map_err(|err| format!("{err:?}"))?,
        threshold,
        overlap_policy,
    };
    println!(
        "BACKEND_LOAD\tbackend=bi\tload_ms={}\tmodel={}",
        started.elapsed().as_millis(),
        clean(path)
    );
    engine(Box::new(backend), max_labels, max_model_windows)
}

fn load_x(
    path: &str,
    threshold: f32,
    max_labels: usize,
    max_model_windows: usize,
) -> Result<phoenix_dynamic_ner::PhoenixNerEngine, String> {
    let started = Instant::now();
    let backend = XBackend {
        model: GlinerXModel::load(Path::new(path), threshold).map_err(|err| format!("{err:?}"))?,
    };
    println!(
        "BACKEND_LOAD\tbackend=x\tload_ms={}\tmodel={}",
        started.elapsed().as_millis(),
        clean(path)
    );
    engine(Box::new(backend), max_labels, max_model_windows)
}

fn engine(
    model: Box<dyn DynamicNerModel>,
    max_labels: usize,
    max_model_windows: usize,
) -> Result<phoenix_dynamic_ner::PhoenixNerEngine, String> {
    let mut builder = PhoenixNerEngineBuilder::new()
        .schema(DynamicSchemaBuilder {
            max_labels,
            ..Default::default()
        })
        .router(SurfaceRouter { max_model_windows })
        .model(model);
    if let Some(router) = load_semantic_label_router()? {
        builder = builder.semantic_label_router(router);
    }
    Ok(builder.build())
}

fn load_semantic_label_router() -> Result<Option<Box<dyn SemanticLabelRouter + Send + Sync>>, String>
{
    let mode = env::var("PHOENIX_DYN_NER_LABEL_ROUTER").unwrap_or_else(|_| "auto".to_owned());
    match mode.trim().to_ascii_lowercase().as_str() {
        "off" | "none" | "0" => {
            println!("LABEL_ROUTER\tmode=off");
            Ok(None)
        }
        "lexical" => {
            println!("LABEL_ROUTER\tmode=lexical");
            Ok(Some(Box::new(LexicalSemanticLabelRouter::default())))
        }
        "jina" => {
            let router = phoenix_dynamic_ner::JinaSemanticLabelRouter::load_default()?;
            println!("LABEL_ROUTER\tmode=jina");
            Ok(Some(Box::new(router)))
        }
        "auto" | "" => {
            if jina_model_root().is_some() {
                match phoenix_dynamic_ner::JinaSemanticLabelRouter::load_default() {
                    Ok(router) => {
                        println!("LABEL_ROUTER\tmode=jina-auto");
                        Ok(Some(Box::new(router)))
                    }
                    Err(error) => {
                        println!(
                            "LABEL_ROUTER\tmode=lexical-fallback\treason={}",
                            clean(&error)
                        );
                        Ok(Some(Box::new(LexicalSemanticLabelRouter::default())))
                    }
                }
            } else {
                println!("LABEL_ROUTER\tmode=lexical-auto");
                Ok(Some(Box::new(LexicalSemanticLabelRouter::default())))
            }
        }
        other => Err(format!("unsupported PHOENIX_DYN_NER_LABEL_ROUTER={other}")),
    }
}

fn jina_model_root() -> Option<PathBuf> {
    if let Some(root) = env::var_os("PHOENIX_DYN_NER_JINA_MODEL_ROOT").map(PathBuf::from) {
        if root.is_dir() {
            return Some(root);
        }
    }
    [
        "D:\\phoenix-models\\jina-embeddings-v5-text-nano-retrieval",
        "G:\\phoenix-models\\jina-embeddings-v5-text-nano-retrieval",
        "D:\\hf-models\\jina-embeddings-v5-text-nano-retrieval",
        "G:\\hf-models\\jina-embeddings-v5-text-nano-retrieval",
    ]
    .into_iter()
    .map(PathBuf::from)
    .find(|path| path.is_dir())
}

impl DynamicNerModel for BiBackend {
    fn discover(
        &self,
        window: &ModelNerWindow<'_>,
        label_pack: &LabelPack,
    ) -> Result<Vec<DiscoveredSpan>, NerModelError> {
        let labels = model_labels(label_pack);
        if labels.is_empty() {
            return Ok(Vec::new());
        }
        self.model
            .predict_with_options(
                window.text,
                &labels,
                &GlinerBiPredictOptions {
                    threshold: self.threshold,
                    overlap_policy: self.overlap_policy,
                },
            )
            .map(map_bi_predictions)
            .map_err(|err| NerModelError::Inference(format!("{err:?}")))
    }

    fn discover_batch(
        &self,
        requests: &[ModelNerRequest<'_>],
    ) -> Result<Vec<Vec<DiscoveredSpan>>, NerModelError> {
        let mut per_request = (0..requests.len())
            .map(|_| BTreeMap::<(u32, u32, String), DiscoveredSpan>::new())
            .collect::<Vec<_>>();
        let mut groups = BTreeMap::<Vec<String>, Vec<(usize, &str)>>::new();

        for (request_index, request) in requests.iter().enumerate() {
            let labels = model_labels(request.label_pack);
            if labels.is_empty() {
                continue;
            }
            groups
                .entry(labels)
                .or_default()
                .push((request_index, request.window.text));
        }

        for (labels, items) in groups {
            let texts = items.iter().map(|(_, text)| *text).collect::<Vec<_>>();
            let predictions = self
                .model
                .predict_texts_with_options(
                    &texts,
                    &labels,
                    &GlinerBiPredictOptions {
                        threshold: self.threshold,
                        overlap_policy: self.overlap_policy,
                    },
                )
                .map_err(|err| NerModelError::Inference(format!("{err:?}")))?;
            for prediction in predictions {
                let Some((request_index, _)) = items.get(prediction.sequence) else {
                    continue;
                };
                insert_bi_prediction(
                    &mut per_request[*request_index],
                    phoenix_rel_post::GlinerBiPrediction {
                        text: prediction.text,
                        label: prediction.label,
                        span_start: prediction.span_start,
                        span_end: prediction.span_end,
                        score: prediction.score,
                    },
                );
            }
        }

        Ok(per_request
            .into_iter()
            .map(|spans| spans.into_values().collect())
            .collect())
    }

    fn verify(
        &self,
        _cases: &[VerificationCase],
    ) -> Result<Vec<(LocalMentionId, MentionVote)>, NerModelError> {
        Ok(Vec::new())
    }
}

impl DynamicNerModel for XBackend {
    fn discover(
        &self,
        window: &ModelNerWindow<'_>,
        label_pack: &LabelPack,
    ) -> Result<Vec<DiscoveredSpan>, NerModelError> {
        let mut spans = BTreeMap::<(u32, u32, String), DiscoveredSpan>::new();
        for labels in x_model_label_passes(label_pack) {
            let refs = labels
                .iter()
                .map(|(model_label, _)| model_label.as_str())
                .collect::<Vec<_>>();
            let predictions = self
                .model
                .predict_texts(&[window.text], &refs)
                .map_err(|err| NerModelError::Inference(format!("{err:?}")))?;
            for prediction in predictions {
                let start = prediction.span_start as u32;
                let end = prediction.span_end as u32;
                let label = canonical_x_label(&prediction.label, &labels);
                let span = DiscoveredSpan {
                    window_relative_range: TextRange { start, end },
                    surface: CompactString::new(prediction.text),
                    label: EntityLabel::new(&label),
                    confidence: prediction.score,
                };
                spans
                    .entry((start, end, label))
                    .and_modify(|current| {
                        if span.confidence > current.confidence {
                            *current = span.clone();
                        }
                    })
                    .or_insert(span);
            }
        }
        Ok(spans.into_values().collect())
    }

    fn discover_batch(
        &self,
        requests: &[ModelNerRequest<'_>],
    ) -> Result<Vec<Vec<DiscoveredSpan>>, NerModelError> {
        let mut per_request = (0..requests.len())
            .map(|_| BTreeMap::<(u32, u32, String), DiscoveredSpan>::new())
            .collect::<Vec<_>>();
        let mut groups = BTreeMap::<Vec<(String, String)>, Vec<(usize, &str)>>::new();

        for (request_index, request) in requests.iter().enumerate() {
            for labels in x_model_label_passes(request.label_pack) {
                if labels.is_empty() {
                    continue;
                }
                groups
                    .entry(labels)
                    .or_default()
                    .push((request_index, request.window.text));
            }
        }

        for (labels, items) in groups {
            let refs = labels
                .iter()
                .map(|(model_label, _)| model_label.as_str())
                .collect::<Vec<_>>();
            let texts = items.iter().map(|(_, text)| *text).collect::<Vec<_>>();
            let predictions = self
                .model
                .predict_texts(&texts, &refs)
                .map_err(|err| NerModelError::Inference(format!("{err:?}")))?;
            for prediction in predictions {
                let Some((request_index, _)) = items.get(prediction.sequence) else {
                    continue;
                };
                let start = prediction.span_start as u32;
                let end = prediction.span_end as u32;
                let label = canonical_x_label(&prediction.label, &labels);
                let span = DiscoveredSpan {
                    window_relative_range: TextRange { start, end },
                    surface: CompactString::new(prediction.text),
                    label: EntityLabel::new(&label),
                    confidence: prediction.score,
                };
                per_request[*request_index]
                    .entry((start, end, label))
                    .and_modify(|current| {
                        if span.confidence > current.confidence {
                            *current = span.clone();
                        }
                    })
                    .or_insert(span);
            }
        }

        Ok(per_request
            .into_iter()
            .map(|spans| spans.into_values().collect())
            .collect())
    }

    fn verify(
        &self,
        _cases: &[VerificationCase],
    ) -> Result<Vec<(LocalMentionId, MentionVote)>, NerModelError> {
        Ok(Vec::new())
    }
}

fn model_labels(label_pack: &LabelPack) -> Vec<String> {
    let mut labels = Vec::new();
    for label in &label_pack.labels {
        let mapped = canonical_model_label(label.as_str());
        if !labels
            .iter()
            .any(|existing: &String| existing.as_str() == mapped.as_str())
        {
            labels.push(mapped);
        }
    }
    labels
}

fn x_model_labels(label_pack: &LabelPack) -> Vec<(String, String)> {
    let mut labels = Vec::new();
    for label in &label_pack.labels {
        let canonical = canonical_model_label(label.as_str());
        let model = canonical.to_ascii_lowercase();
        if !labels
            .iter()
            .any(|(existing, _): &(String, String)| existing == &model)
        {
            labels.push((model, canonical));
        }
    }
    labels
}

fn x_model_label_passes(label_pack: &LabelPack) -> Vec<Vec<(String, String)>> {
    let labels = x_model_labels(label_pack);
    let groups: &[&[&str]] = &[
        &["Person", "Organization", "Location", "Event", "Artifact"],
        &[
            "Creature", "Species", "Monster", "Weapon", "Ability", "Spell",
        ],
        &["Concept", "Rank", "Role", "State", "Goal", "Relationship"],
        &["Item", "Object", "Place", "Region", "Landmark"],
    ];
    let mut passes = Vec::new();
    let mut grouped = BTreeSet::<String>::new();
    for group in groups {
        let pass = group
            .iter()
            .filter_map(|candidate| {
                labels
                    .iter()
                    .find(|(_, canonical)| canonical == *candidate)
                    .cloned()
            })
            .collect::<Vec<_>>();
        if !pass.is_empty() {
            grouped.extend(pass.iter().map(|(_, canonical)| canonical.clone()));
            passes.push(pass);
        }
    }
    let overflow = labels
        .into_iter()
        .filter(|(_, canonical)| !grouped.contains(canonical))
        .collect::<Vec<_>>();
    for chunk in overflow.chunks(6) {
        passes.push(chunk.to_vec());
    }
    passes
}

fn canonical_model_label(label: &str) -> String {
    match label {
        "Character" | "Npc" | "NPC" | "Person" => "Person".to_owned(),
        "Organization" | "Faction" | "Alliance" | "Department" => "Organization".to_owned(),
        "Location" | "Region" | "Landmark" => "Location".to_owned(),
        "Item" | "Object" | "Weapon" => "Artifact".to_owned(),
        "Species" | "Monster" | "Nonhuman" | "Denizen" => "Creature".to_owned(),
        "Rank" | "Role" | "State" | "Goal" | "Relationship" => "Concept".to_owned(),
        other => other.to_owned(),
    }
}

fn canonical_x_label(label: &str, labels: &[(String, String)]) -> String {
    labels
        .iter()
        .find(|(model_label, _)| model_label == label)
        .map(|(_, canonical)| canonical.clone())
        .unwrap_or_else(|| label.to_owned())
}

fn map_bi_predictions(
    predictions: Vec<phoenix_rel_post::GlinerBiPrediction>,
) -> Vec<DiscoveredSpan> {
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
}

fn insert_bi_prediction(
    by_key: &mut BTreeMap<(u32, u32, String), DiscoveredSpan>,
    prediction: phoenix_rel_post::GlinerBiPrediction,
) {
    let start = prediction.span_start as u32;
    let end = prediction.span_end as u32;
    let label = prediction.label;
    let span = DiscoveredSpan {
        window_relative_range: TextRange { start, end },
        surface: CompactString::new(prediction.text),
        label: EntityLabel::new(&label),
        confidence: prediction.score,
    };
    by_key
        .entry((start, end, label))
        .and_modify(|current| {
            if span.confidence > current.confidence {
                *current = span.clone();
            }
        })
        .or_insert(span);
}

fn run_doc(
    backend: &'static str,
    engine: &phoenix_dynamic_ner::PhoenixNerEngine,
    doc: &str,
) -> Result<DocSummary, Box<dyn std::error::Error>> {
    let text = fs::read_to_string(doc)?;
    let (tokens, sentences) = tokenize(&text);
    let lexicon = story_lexicon()?;
    let scope = ScopeKey::default();
    let input = SurfaceNerInput {
        document_id: "ner-pipeline-parity",
        text: &text,
        tokens: &tokens,
        sentences: &sentences,
        scope: &scope,
        lexicon: Some(&lexicon),
        surface_hits: &[],
        label_bank_context: None,
    };
    let started = Instant::now();
    let (output, metrics) = engine.extract_mentions_with_metrics(&input)?;
    print_phase_metrics(backend, doc, &metrics);
    Ok(summarize(
        backend,
        doc,
        started.elapsed().as_millis(),
        &output.mentions,
        &output.surface_memory,
    ))
}

fn print_phase_metrics(backend: &'static str, doc: &str, metrics: &SurfaceNerMetrics) {
    println!(
        "PHASE_METRICS\tbackend={backend}\tpath={}\ttotal_ms={}\tknown_ms={}\tnative_ms={}\troute_ms={}\tworkspace_ms={}\tmodel_ms={}\tfinal_packets_ms={}\tsurface_memory_ms={}\tgraph_ms={}\tchunk_hints_ms={}\tknown_count={}\tnative_count={}\troutes={}\tpackets={}\tgraph_edges={}\tchunk_hints={}",
        clean(doc),
        metrics.total_ms,
        metrics.known_surface_ms,
        metrics.native_discovery_ms,
        metrics.route_planning_ms,
        metrics.workspace_ingest_ms,
        metrics.model_and_adjudication_ms,
        metrics.final_packets_ms,
        metrics.surface_memory_ms,
        metrics.mention_graph_ms,
        metrics.chunk_hints_ms,
        metrics.known_count,
        metrics.native_count,
        metrics.route_count,
        metrics.packet_count,
        metrics.graph_edge_count,
        metrics.chunk_hint_count
    );
}

fn args_or_default() -> Vec<String> {
    let args = env::args().skip(1).collect::<Vec<_>>();
    if args.is_empty() {
        vec![
            "docs\\shortrun.md".to_owned(),
            "docs\\mother2.md".to_owned(),
        ]
    } else {
        args
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
