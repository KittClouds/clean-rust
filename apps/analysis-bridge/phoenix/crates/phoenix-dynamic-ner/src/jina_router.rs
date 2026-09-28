use std::collections::hash_map::DefaultHasher;
use std::collections::BTreeMap;
use std::env;
use std::hash::{Hash, Hasher};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Instant;

use phoenix_embed::{
    default_ort_dylib_path, workspace_root, EmbeddingBatchOrder, OrtExecutionProviderPreference,
    OrtTextEmbedConfig, OrtTextEmbedder, TextEmbeddingInputPrefix, TextEmbeddingPooling,
    TextEmbeddingProfile,
};
use smallvec::SmallVec;

use crate::label_catalog::{self, labels_for_domain};
use crate::semantic_router::{
    LexicalSemanticLabelRouter, SemanticLabelRouter, SemanticRouteHint, SemanticRouteInput,
};
use crate::types::{DomainProfile, EntityLabel};

const DEFAULT_MIN_CONFIDENCE: f32 = 0.48;
const DEFAULT_MIN_LABEL_SCORE: f32 = 0.16;
const MAX_ROUTE_LABELS: usize = 12;

pub struct JinaSemanticLabelRouter {
    embedder: Mutex<OrtTextEmbedder>,
    document_domains: Mutex<BTreeMap<u64, (DomainProfile, f32)>>,
    domain_queries: Vec<DomainPrototype>,
    label_queries: Vec<LabelPrototype>,
    min_confidence: f32,
    min_label_score: f32,
    lexical_gate: LexicalSemanticLabelRouter,
    lexical_gate_confidence: f32,
    max_semantic_windows: usize,
    profile: TextEmbeddingProfile,
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

// ORT session handles include memory metadata that is not marked Send/Sync.
// Inference is serialized through the mutex, and all mutable state is guarded.
unsafe impl Send for JinaSemanticLabelRouter {}
unsafe impl Sync for JinaSemanticLabelRouter {}

impl JinaSemanticLabelRouter {
    pub fn load_default() -> Result<Self, String> {
        let root = jina_model_root()
            .ok_or_else(|| "Jina router requested but no model root was found".to_owned())?;
        Self::load(root, JinaRouterOptions::from_env())
    }

    pub fn load(model_root: PathBuf, options: JinaRouterOptions) -> Result<Self, String> {
        ensure_ort_dylib();
        let config = OrtTextEmbedConfig {
            model_root: model_root.clone(),
            batch_size: options.batch_size,
            max_length: options.max_length,
            profile: options.profile,
            prefix_passage: false,
            pooling: TextEmbeddingPooling::LastToken,
            input_prefix: TextEmbeddingInputPrefix::None,
            batch_order: EmbeddingBatchOrder::LengthBucketed,
            execution_provider: OrtExecutionProviderPreference::from_env(),
        };
        let started = Instant::now();
        let embedder =
            OrtTextEmbedder::load(&config).map_err(|error| format!("Jina load: {error}"))?;
        let prototypes = build_prototype_texts();
        let vectors = embedder
            .embed_texts(&prototypes)
            .map_err(|error| format!("Jina prototype embed: {error}"))?;
        let (domain_queries, label_queries) = split_prototypes(vectors);
        eprintln!(
            "JINA_ROUTER_LOAD\tmodel={}\tdim={}\tload_ms={}\tdomains={}\tlabels={}",
            model_root.display(),
            options.profile.target_dim(),
            started.elapsed().as_millis(),
            domain_queries.len(),
            label_queries.len()
        );
        Ok(Self {
            embedder: Mutex::new(embedder),
            document_domains: Mutex::new(BTreeMap::new()),
            domain_queries,
            label_queries,
            min_confidence: options.min_confidence,
            min_label_score: options.min_label_score,
            lexical_gate: LexicalSemanticLabelRouter::new(options.lexical_gate_confidence),
            lexical_gate_confidence: options.lexical_gate_confidence,
            max_semantic_windows: options.max_semantic_windows,
            profile: options.profile,
        })
    }

    fn route_embedding(
        &self,
        embedding: &[f32],
        doc_domain: Option<(DomainProfile, f32)>,
    ) -> Option<SemanticRouteHint> {
        let domain_scores = self.score_domains(embedding);
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
        let confidence = route_confidence(top_score, margin);
        if confidence < self.min_confidence {
            return None;
        }

        let mut labels = domain_labels(domain);
        let mut scored_labels = self
            .label_queries
            .iter()
            .map(|prototype| (prototype.label, cosine(embedding, &prototype.vector)))
            .collect::<Vec<_>>();
        scored_labels.sort_by(|left, right| {
            right
                .1
                .partial_cmp(&left.1)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        for (label, score) in scored_labels {
            if labels.len() >= MAX_ROUTE_LABELS {
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
            format!(
                "jina-v5-router:{}d:{query}:score={top_score:.3}:margin={margin:.3}",
                self.profile.target_dim()
            ),
        ))
    }

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
        let value = (domain, route_confidence(top_score, top_score - runner_up));
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

impl SemanticLabelRouter for JinaSemanticLabelRouter {
    fn route_window(&self, input: &SemanticRouteInput<'_>) -> Option<SemanticRouteHint> {
        if let Some(hint) = self.lexical_gate.route_window(input) {
            if hint.confidence >= self.lexical_gate_confidence {
                return Some(hint);
            }
        }
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

    fn route_windows(&self, inputs: &[SemanticRouteInput<'_>]) -> Vec<Option<SemanticRouteHint>> {
        if inputs.is_empty() {
            return Vec::new();
        }
        let mut results = self.lexical_gate.route_windows(inputs);
        let mut semantic_indexes = results
            .iter()
            .enumerate()
            .filter_map(|(index, hint)| {
                let use_semantic = hint
                    .as_ref()
                    .map(|hint| hint.confidence < self.lexical_gate_confidence)
                    .unwrap_or(true);
                use_semantic.then_some(index)
            })
            .collect::<Vec<_>>();
        if semantic_indexes.len() > self.max_semantic_windows {
            semantic_indexes.sort_by(|left, right| {
                lexical_confidence(results[*left].as_ref())
                    .total_cmp(&lexical_confidence(results[*right].as_ref()))
            });
            semantic_indexes.truncate(self.max_semantic_windows);
        }
        if semantic_indexes.is_empty() {
            return results;
        }
        let doc_domain = self.document_domain(inputs[0].document_text);
        let texts = semantic_indexes
            .iter()
            .map(|index| {
                format!(
                    "Document: {}",
                    compact_window_text(inputs[*index].window_text)
                )
            })
            .collect::<Vec<_>>();
        let embeddings = self
            .embedder
            .lock()
            .ok()
            .and_then(|embedder| embedder.embed_texts(&texts).ok());
        let Some(embeddings) = embeddings else {
            return results;
        };
        for (index, embedding) in semantic_indexes.into_iter().zip(embeddings.iter()) {
            if let Some(hint) = self.route_embedding(embedding, doc_domain) {
                results[index] = Some(hint);
            }
        }
        results
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct JinaRouterOptions {
    pub profile: TextEmbeddingProfile,
    pub batch_size: usize,
    pub max_length: usize,
    pub min_confidence: f32,
    pub min_label_score: f32,
    pub lexical_gate_confidence: f32,
    pub max_semantic_windows: usize,
}

impl JinaRouterOptions {
    pub fn from_env() -> Self {
        Self {
            profile: env::var("PHOENIX_DYN_NER_JINA_DIM")
                .ok()
                .and_then(|value| TextEmbeddingProfile::parse(&value))
                .unwrap_or(TextEmbeddingProfile::Truncate256),
            batch_size: env_usize("PHOENIX_DYN_NER_JINA_BATCH", 16),
            max_length: env_usize("PHOENIX_DYN_NER_JINA_MAX_LENGTH", 384),
            min_confidence: env_f32(
                "PHOENIX_DYN_NER_JINA_MIN_CONFIDENCE",
                DEFAULT_MIN_CONFIDENCE,
            ),
            min_label_score: env_f32(
                "PHOENIX_DYN_NER_JINA_MIN_LABEL_SCORE",
                DEFAULT_MIN_LABEL_SCORE,
            ),
            lexical_gate_confidence: env_f32("PHOENIX_DYN_NER_JINA_LEXICAL_GATE", 0.48),
            max_semantic_windows: env_usize("PHOENIX_DYN_NER_JINA_MAX_WINDOWS", 24),
        }
    }
}

fn lexical_confidence(hint: Option<&SemanticRouteHint>) -> f32 {
    hint.map(|hint| hint.confidence).unwrap_or(0.0)
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

fn ensure_ort_dylib() {
    if env::var_os("ORT_DYLIB_PATH").is_none() {
        if let Some(path) = default_ort_dylib_path(&workspace_root()) {
            unsafe { env::set_var("ORT_DYLIB_PATH", path) };
        }
    }
}

fn build_prototype_texts() -> Vec<String> {
    let mut texts =
        Vec::with_capacity(DOMAIN_PROTOTYPES.len() + label_catalog::ROUTABLE_LABELS.len());
    texts.extend(
        DOMAIN_PROTOTYPES
            .iter()
            .map(|(_, query)| format!("Query: {query}")),
    );
    texts.extend(label_catalog::ROUTABLE_LABELS.iter().map(|label| {
        format!(
            "Query: entity label {label}. {}",
            label_catalog::label_description(label).unwrap_or("A named entity label candidate.")
        )
    }));
    texts
}

fn split_prototypes(vectors: Vec<Vec<f32>>) -> (Vec<DomainPrototype>, Vec<LabelPrototype>) {
    let mut iter = vectors.into_iter();
    let domains = DOMAIN_PROTOTYPES
        .iter()
        .filter_map(|(domain, query)| {
            iter.next().map(|vector| DomainPrototype {
                domain: *domain,
                query: *query,
                vector,
            })
        })
        .collect();
    let labels = label_catalog::ROUTABLE_LABELS
        .iter()
        .filter_map(|label| iter.next().map(|vector| LabelPrototype { label, vector }))
        .collect();
    (domains, labels)
}

fn domain_labels(domain: DomainProfile) -> SmallVec<[EntityLabel; 16]> {
    let mut labels = SmallVec::<[EntityLabel; 16]>::new();
    for label in labels_for_domain(domain) {
        push_route_label(&mut labels, label);
    }
    labels
}

fn push_route_label(labels: &mut SmallVec<[EntityLabel; 16]>, label: &str) {
    if !labels
        .iter()
        .any(|existing| existing.as_str().eq_ignore_ascii_case(label))
    {
        labels.push(EntityLabel::new(label));
    }
}

fn compact_window_text(text: &str) -> String {
    compact_text(text, 1800)
}

fn compact_document_text(text: &str) -> String {
    compact_text(text, 4200)
}

fn compact_text(text: &str, max_len: usize) -> String {
    let mut out = String::with_capacity(text.len().min(max_len));
    for part in text.split_whitespace() {
        if !out.is_empty() {
            out.push(' ');
        }
        if out.len().saturating_add(part.len()).saturating_add(1) > max_len {
            break;
        }
        out.push_str(part);
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

fn route_confidence(top_score: f32, margin: f32) -> f32 {
    (0.38 + top_score.max(0.0) * 1.35 + margin.max(0.0) * 1.65).clamp(0.0, 0.94)
}

fn cosine(left: &[f32], right: &[f32]) -> f32 {
    left.iter().zip(right.iter()).map(|(a, b)| a * b).sum()
}

fn env_f32(name: &str, default: f32) -> f32 {
    env::var(name)
        .ok()
        .and_then(|value| value.parse::<f32>().ok())
        .unwrap_or(default)
}

fn env_usize(name: &str, default: usize) -> usize {
    env::var(name)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(default)
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
