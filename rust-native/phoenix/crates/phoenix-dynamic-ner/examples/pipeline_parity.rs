mod pipeline_parity_support;

use std::collections::hash_map::DefaultHasher;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::env;
use std::fs;
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Instant;

use compact_str::CompactString;
use phoenix_dynamic_ner::{
    labels_for_domain, DiscoveredSpan, DomainProfile, DynamicNerModel, DynamicSchemaBuilder,
    EntityLabel, LabelPack, LexicalSemanticLabelRouter, LocalMentionId, MentionVote,
    ModelNerRequest, ModelNerWindow, NerModelError, PhoenixNerEngineBuilder, SemanticLabelRouter,
    SemanticRouteHint, SemanticRouteInput, SurfaceNerInput, SurfaceNerMetrics, SurfaceRouter,
    VerificationCase, ROUTABLE_LABELS,
};
use phoenix_embed::{
    default_ort_dylib_path, workspace_root, OrtExecutionProviderPreference, OrtTextEmbedConfig,
    OrtTextEmbedder, TextEmbeddingInputPrefix, TextEmbeddingPooling, TextEmbeddingProfile,
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

struct JinaSemanticLabelRouter {
    embedder: Mutex<OrtTextEmbedder>,
    document_domains: Mutex<BTreeMap<u64, (DomainProfile, f32)>>,
    domain_queries: Vec<DomainPrototype>,
    label_queries: Vec<LabelPrototype>,
    min_confidence: f32,
    min_label_score: f32,
}

struct DomainPrototype {
    domain: DomainProfile,
    query: &'static str,
    vector: Vec<f32>,
}

struct LabelPrototype {
    label: &'static str,
    vector: Vec<f32>,
}

// The parity example runs the Jina embedder synchronously on one thread. ORT's
// memory-info handle is not marked Send, so the adapter protects inference with
// a mutex and keeps the unsafe boundary local to this smoke harness.
unsafe impl Send for JinaSemanticLabelRouter {}
unsafe impl Sync for JinaSemanticLabelRouter {}

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
            let root = jina_model_root()
                .ok_or_else(|| "Jina router requested but no model root was found".to_owned())?;
            let router = JinaSemanticLabelRouter::load(root)?;
            println!("LABEL_ROUTER\tmode=jina");
            Ok(Some(Box::new(router)))
        }
        "auto" | "" => {
            if let Some(root) = jina_model_root() {
                match JinaSemanticLabelRouter::load(root) {
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

impl JinaSemanticLabelRouter {
    fn load(model_root: PathBuf) -> Result<Self, String> {
        if env::var_os("ORT_DYLIB_PATH").is_none() {
            if let Some(path) = default_ort_dylib_path(&workspace_root()) {
                unsafe { env::set_var("ORT_DYLIB_PATH", path) };
            }
        }
        let config = OrtTextEmbedConfig {
            model_root: model_root.clone(),
            batch_size: 16,
            max_length: 1024,
            profile: TextEmbeddingProfile::Native768,
            prefix_passage: false,
            pooling: TextEmbeddingPooling::LastToken,
            input_prefix: TextEmbeddingInputPrefix::None,
            execution_provider: OrtExecutionProviderPreference::from_env(),
        };
        let started = Instant::now();
        let embedder =
            OrtTextEmbedder::load(&config).map_err(|error| format!("Jina load: {error}"))?;
        let mut query_texts = Vec::new();
        query_texts.extend(
            DOMAIN_PROTOTYPES
                .iter()
                .map(|(_, query)| format!("Query: {query}")),
        );
        query_texts.extend(
            ROUTABLE_LABELS
                .iter()
                .map(|label| format!("Query: entity label {label}. {}", label_description(label))),
        );
        let vectors = embedder
            .embed_texts(&query_texts)
            .map_err(|error| format!("Jina prototype embed: {error}"))?;
        let mut iter = vectors.into_iter();
        let domain_queries = DOMAIN_PROTOTYPES
            .iter()
            .filter_map(|(domain, query)| {
                iter.next().map(|vector| DomainPrototype {
                    domain: *domain,
                    query: *query,
                    vector,
                })
            })
            .collect::<Vec<_>>();
        let label_queries = ROUTABLE_LABELS
            .iter()
            .filter_map(|label| {
                iter.next().map(|vector| LabelPrototype {
                    label: *label,
                    vector,
                })
            })
            .collect::<Vec<_>>();
        println!(
            "JINA_ROUTER_LOAD\tmodel={}\tload_ms={}\tdomains={}\tlabels={}",
            clean(&model_root.display().to_string()),
            started.elapsed().as_millis(),
            domain_queries.len(),
            label_queries.len()
        );
        Ok(Self {
            embedder: Mutex::new(embedder),
            document_domains: Mutex::new(BTreeMap::new()),
            domain_queries,
            label_queries,
            min_confidence: env_f32("PHOENIX_DYN_NER_JINA_MIN_CONFIDENCE", 0.48),
            min_label_score: env_f32("PHOENIX_DYN_NER_JINA_MIN_LABEL_SCORE", 0.16),
        })
    }
}

impl SemanticLabelRouter for JinaSemanticLabelRouter {
    fn route_window(&self, input: &SemanticRouteInput<'_>) -> Option<SemanticRouteHint> {
        let doc_domain = self.document_domain(input.document_text);
        let text = format!("Document: {}", compact_window_text(input.window_text));
        let embedding = self
            .embedder
            .lock()
            .ok()?
            .embed_texts(&[text])
            .ok()?
            .into_iter()
            .next()?;
        self.route_embedding(&embedding, doc_domain)
    }
}

impl JinaSemanticLabelRouter {
    fn route_embedding(
        &self,
        embedding: &[f32],
        doc_domain: Option<(DomainProfile, f32)>,
    ) -> Option<SemanticRouteHint> {
        let domain_scores = self.score_domains(&embedding);
        let (mut domain, mut query, top_score) = *domain_scores.first()?;
        let runner_up = domain_scores
            .get(1)
            .map(|(_, _, score)| *score)
            .unwrap_or(0.0);
        let margin = (top_score - runner_up).max(0.0);
        if let Some((doc_domain, doc_confidence)) = doc_domain {
            if should_apply_document_domain_prior(doc_domain, domain, doc_confidence, margin) {
                domain = doc_domain;
                query = domain_query(doc_domain);
            }
        }
        let confidence = (0.38 + top_score.max(0.0) * 1.35 + margin * 1.65).clamp(0.0, 0.94);
        if confidence < self.min_confidence {
            return None;
        }

        let mut labels = domain_labels(domain);
        let mut scored_labels = self
            .label_queries
            .iter()
            .map(|prototype| (prototype.label, cosine(&embedding, &prototype.vector)))
            .collect::<Vec<_>>();
        scored_labels.sort_by(|left, right| {
            right
                .1
                .partial_cmp(&left.1)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        for (label, score) in scored_labels {
            if labels.len() >= 12 {
                break;
            }
            if score >= self.min_label_score {
                push_route_label(&mut labels, label);
            }
        }
        Some(SemanticRouteHint::new(
            domain,
            confidence,
            labels,
            format!("jina-v5-router:{query}:score={top_score:.3}:margin={margin:.3}"),
        ))
    }
}

impl JinaSemanticLabelRouter {
    fn document_domain(&self, document_text: &str) -> Option<(DomainProfile, f32)> {
        let key = stable_text_hash(document_text);
        if let Some(value) = self.document_domains.lock().ok()?.get(&key).copied() {
            return Some(value);
        }
        let text = format!("Document: {}", compact_document_text(document_text));
        let embedding = self
            .embedder
            .lock()
            .ok()?
            .embed_texts(&[text])
            .ok()?
            .into_iter()
            .next()?;
        let scores = self.score_domains(&embedding);
        let (domain, _, top_score) = *scores.first()?;
        let runner_up = scores.get(1).map(|(_, _, score)| *score).unwrap_or(0.0);
        let confidence =
            (0.38 + top_score.max(0.0) * 1.35 + (top_score - runner_up).max(0.0) * 1.65)
                .clamp(0.0, 0.94);
        let value = (domain, confidence);
        self.document_domains.lock().ok()?.insert(key, value);
        Some(value)
    }

    fn score_domains(&self, embedding: &[f32]) -> Vec<(DomainProfile, &'static str, f32)> {
        let mut scores = self
            .domain_queries
            .iter()
            .map(|prototype| {
                (
                    prototype.domain,
                    prototype.query,
                    cosine(embedding, &prototype.vector),
                )
            })
            .collect::<Vec<_>>();
        scores.sort_by(|left, right| {
            right
                .2
                .partial_cmp(&left.2)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        scores
    }
}

fn domain_labels(domain: DomainProfile) -> smallvec::SmallVec<[EntityLabel; 16]> {
    let mut labels = smallvec::SmallVec::<[EntityLabel; 16]>::new();
    for label in labels_for_domain(domain) {
        push_route_label(&mut labels, label);
    }
    labels
}

fn push_route_label(labels: &mut smallvec::SmallVec<[EntityLabel; 16]>, label: &str) {
    if !labels
        .iter()
        .any(|existing| existing.as_str().eq_ignore_ascii_case(label))
    {
        labels.push(EntityLabel::new(label));
    }
}

fn compact_window_text(text: &str) -> String {
    let mut out = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if out.len() > 1800 {
        out.truncate(1800);
    }
    out
}

fn compact_document_text(text: &str) -> String {
    let mut out = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if out.len() > 4200 {
        out.truncate(4200);
    }
    out
}

fn stable_text_hash(text: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    text.len().hash(&mut hasher);
    text.get(..text.len().min(4096))
        .unwrap_or(text)
        .hash(&mut hasher);
    hasher.finish()
}

fn should_apply_document_domain_prior(
    document_domain: DomainProfile,
    window_domain: DomainProfile,
    document_confidence: f32,
    window_margin: f32,
) -> bool {
    document_confidence >= 0.54
        && is_story_like_domain(document_domain)
        && !is_story_compatible_domain(window_domain)
        && window_margin < 0.22
}

fn is_story_like_domain(domain: DomainProfile) -> bool {
    matches!(
        domain,
        DomainProfile::Story | DomainProfile::Fantasy | DomainProfile::Memory
    )
}

fn is_story_compatible_domain(domain: DomainProfile) -> bool {
    matches!(
        domain,
        DomainProfile::Story
            | DomainProfile::Fantasy
            | DomainProfile::Memory
            | DomainProfile::General
    )
}

fn cosine(left: &[f32], right: &[f32]) -> f32 {
    left.iter().zip(right.iter()).map(|(a, b)| a * b).sum()
}

const DOMAIN_PROTOTYPES: &[(DomainProfile, &str)] = &[
    (
        DomainProfile::Story,
        "fiction story narrative with named characters, speakers, factions, places, items, relationships, and dialogue",
    ),
    (
        DomainProfile::Fantasy,
        "fantasy fiction with creatures, species, monsters, magic, spells, weapons, artifacts, ranks, and powers",
    ),
    (
        DomainProfile::Corporate,
        "business organization document with companies, departments, products, executives, metrics, initiatives, and risk",
    ),
    (
        DomainProfile::Technical,
        "software engineering technical document with modules, functions, libraries, embeddings, vectors, benchmarks, algorithms, and errors",
    ),
    (
        DomainProfile::Legal,
        "legal document with courts, statutes, rulings, parties, claims, and jurisdictions",
    ),
    (
        DomainProfile::Academic,
        "academic research document with papers, researchers, datasets, methods, institutions, and theories",
    ),
    (
        DomainProfile::Memory,
        "personal memory or state document with goals, emotions, relationships, remembered states, and intentions",
    ),
    (
        DomainProfile::General,
        "general prose with named entities, roles, objects, concepts, locations, organizations, and events",
    ),
];

fn domain_query(domain: DomainProfile) -> &'static str {
    DOMAIN_PROTOTYPES
        .iter()
        .find_map(|(candidate, query)| (*candidate == domain).then_some(*query))
        .unwrap_or("general prose with named entities")
}

fn label_description(label: &str) -> &'static str {
    match label {
        "Character" | "Npc" => "A named individual actor, speaker, or person in the document.",
        "Organization" | "Faction" => {
            "A named group, institution, company, gang, faction, or alliance."
        }
        "Location" | "Region" | "Landmark" => "A named place, city, area, base, or landmark.",
        "Event" => "A named happening, battle, meeting, incident, or process.",
        "Artifact" | "Item" | "Object" | "Weapon" => {
            "A named object, tool, weapon, document, machine, or created thing."
        }
        "Concept" | "Rank" | "Role" | "State" | "Goal" | "Relationship" => {
            "An abstract idea, rank, role, state, relation, rule, or goal."
        }
        "Creature" | "Species" | "Monster" => {
            "A nonhuman species, creature kind, monster, or denizen category."
        }
        "Ability" | "Spell" => "A named power, skill, spell, or capability.",
        _ => "A named entity label candidate.",
    }
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
