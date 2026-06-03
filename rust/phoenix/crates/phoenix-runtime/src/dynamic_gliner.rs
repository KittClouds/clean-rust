use std::collections::BTreeMap;
use std::env;
use std::path::{Path, PathBuf};
use std::sync::{Arc, OnceLock};

use phoenix_dynamic_ner::{
    DiscoveredSpan, DynamicNerModel, EntityLabel, LabelPack, LexicalSemanticLabelRouter,
    LocalMentionId, MentionVote, ModelNerRequest, ModelNerWindow, NerModelError,
    SemanticLabelRouter, VerificationCase,
};
use phoenix_rel_post::{
    GlinerBiModel, GlinerBiOverlapPolicy, GlinerBiPredictOptions, GlinerBiPrediction, GlinerXModel,
};
use phoenix_types::TextRange;

#[derive(Clone)]
enum LoadedGlinerModel {
    Bi(Arc<GlinerBiModel>),
    X(Arc<GlinerXModel>),
}

static GLINER_MODEL: OnceLock<Result<LoadedGlinerModel, String>> = OnceLock::new();

pub fn load_default_model() -> Result<Box<dyn DynamicNerModel + Send + Sync>, String> {
    let model = GLINER_MODEL.get_or_init(load_first_available_model);

    match model.as_ref().map_err(Clone::clone)?.clone() {
        LoadedGlinerModel::Bi(model) => Ok(Box::new(RuntimeGlinerBiModel {
            model,
            threshold: threshold(),
            overlap_policy: overlap_policy(),
        })),
        LoadedGlinerModel::X(model) => Ok(Box::new(RuntimeGlinerXModel { model })),
    }
}

pub fn load_default_label_router(
) -> Result<Option<Box<dyn SemanticLabelRouter + Send + Sync>>, String> {
    let mode = env::var("PHOENIX_DYN_NER_LABEL_ROUTER").unwrap_or_else(|_| "auto".to_owned());
    match mode.trim().to_ascii_lowercase().as_str() {
        "off" | "none" | "0" => Ok(None),
        "lexical" => Ok(Some(Box::new(LexicalSemanticLabelRouter::default()))),
        "jina" => load_jina_label_router().map(Some),
        "auto" | "" => match load_jina_label_router() {
            Ok(router) => Ok(Some(router)),
            Err(_) => Ok(Some(Box::new(LexicalSemanticLabelRouter::default()))),
        },
        other => Err(format!("unsupported PHOENIX_DYN_NER_LABEL_ROUTER={other}")),
    }
}

#[cfg(all(feature = "jina-router", not(target_arch = "wasm32")))]
fn load_jina_label_router() -> Result<Box<dyn SemanticLabelRouter + Send + Sync>, String> {
    Ok(Box::new(
        phoenix_dynamic_ner::JinaSemanticLabelRouter::load_default()?,
    ))
}

#[cfg(any(not(feature = "jina-router"), target_arch = "wasm32"))]
fn load_jina_label_router() -> Result<Box<dyn SemanticLabelRouter + Send + Sync>, String> {
    Err("Jina semantic router is not enabled for this runtime target".to_owned())
}

struct RuntimeGlinerBiModel {
    model: Arc<GlinerBiModel>,
    threshold: f32,
    overlap_policy: GlinerBiOverlapPolicy,
}

impl DynamicNerModel for RuntimeGlinerBiModel {
    fn discover(
        &self,
        window: &ModelNerWindow<'_>,
        label_pack: &LabelPack,
    ) -> Result<Vec<DiscoveredSpan>, NerModelError> {
        let labels = bi_model_labels(label_pack);
        if labels.is_empty() {
            return Ok(Vec::new());
        }

        let options = GlinerBiPredictOptions {
            threshold: self.threshold,
            overlap_policy: self.overlap_policy,
            ..Default::default()
        };
        let mut by_key = BTreeMap::<(u32, u32, String), DiscoveredSpan>::new();
        let predictions = self
            .model
            .predict_with_options(window.text, &labels, &options)
            .map_err(|error| NerModelError::Inference(error.to_string()))?;

        for prediction in predictions {
            insert_bi_prediction(&mut by_key, prediction);
        }

        Ok(by_key.into_values().collect())
    }

    fn discover_batch(
        &self,
        requests: &[ModelNerRequest<'_>],
    ) -> Result<Vec<Vec<DiscoveredSpan>>, NerModelError> {
        let options = GlinerBiPredictOptions {
            threshold: self.threshold,
            overlap_policy: self.overlap_policy,
            ..Default::default()
        };
        let mut per_request = (0..requests.len())
            .map(|_| BTreeMap::<(u32, u32, String), DiscoveredSpan>::new())
            .collect::<Vec<_>>();
        let mut groups = BTreeMap::<Vec<String>, Vec<(usize, &str)>>::new();

        for (request_index, request) in requests.iter().enumerate() {
            let labels = bi_model_labels(request.label_pack);
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
                .predict_texts_with_options(&texts, &labels, &options)
                .map_err(|error| NerModelError::Inference(error.to_string()))?;

            for prediction in predictions {
                let Some((request_index, _)) = items.get(prediction.sequence) else {
                    continue;
                };
                let span = GlinerBiPrediction {
                    text: prediction.text,
                    label: prediction.label,
                    span_start: prediction.span_start,
                    span_end: prediction.span_end,
                    score: prediction.score,
                };
                insert_bi_prediction(&mut per_request[*request_index], span);
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

struct RuntimeGlinerXModel {
    model: Arc<GlinerXModel>,
}

impl DynamicNerModel for RuntimeGlinerXModel {
    fn discover(
        &self,
        window: &ModelNerWindow<'_>,
        label_pack: &LabelPack,
    ) -> Result<Vec<DiscoveredSpan>, NerModelError> {
        let label_passes = model_label_passes(label_pack);
        if label_passes.is_empty() {
            return Ok(Vec::new());
        }

        let mut by_key = BTreeMap::<(u32, u32, String), DiscoveredSpan>::new();
        for labels in label_passes {
            let model_labels = labels
                .iter()
                .map(|label| label.to_ascii_lowercase())
                .collect::<Vec<_>>();
            let refs = model_labels.iter().map(String::as_str).collect::<Vec<_>>();
            let predictions = self
                .model
                .predict_texts(&[window.text], &refs)
                .map_err(|error| NerModelError::Inference(error.to_string()))?;

            for prediction in predictions {
                let start = prediction.span_start as u32;
                let end = prediction.span_end as u32;
                let label = runtime_label(&prediction.label).to_owned();
                let key = (start, end, label.clone());
                let span = DiscoveredSpan {
                    window_relative_range: TextRange { start, end },
                    surface: prediction.text.into(),
                    label: EntityLabel::new(&label),
                    confidence: prediction.score,
                };
                by_key
                    .entry(key)
                    .and_modify(|current| {
                        if span.confidence > current.confidence {
                            *current = span.clone();
                        }
                    })
                    .or_insert(span);
            }
        }

        Ok(by_key.into_values().collect())
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
            for labels in model_label_passes(request.label_pack) {
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
            let model_labels = labels
                .iter()
                .map(|label| label.to_ascii_lowercase())
                .collect::<Vec<_>>();
            let refs = model_labels.iter().map(String::as_str).collect::<Vec<_>>();
            let texts = items.iter().map(|(_, text)| *text).collect::<Vec<_>>();
            let predictions = self
                .model
                .predict_texts(&texts, &refs)
                .map_err(|error| NerModelError::Inference(error.to_string()))?;

            for prediction in predictions {
                let Some((request_index, _)) = items.get(prediction.sequence) else {
                    continue;
                };
                let start = prediction.span_start as u32;
                let end = prediction.span_end as u32;
                let label = runtime_label(&prediction.label).to_owned();
                let key = (start, end, label.clone());
                let span = DiscoveredSpan {
                    window_relative_range: TextRange { start, end },
                    surface: prediction.text.into(),
                    label: EntityLabel::new(&label),
                    confidence: prediction.score,
                };
                per_request[*request_index]
                    .entry(key)
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

fn model_label_passes(label_pack: &LabelPack) -> Vec<Vec<String>> {
    let labels = bi_model_labels(label_pack);
    let groups: &[&[&str]] = &[
        &["Person", "Organization", "Location", "Event", "Artifact"],
        &[
            "Creature", "Species", "Monster", "Weapon", "Ability", "Spell",
        ],
        &["Concept", "Rank", "Role", "State", "Goal", "Relationship"],
        &["Item", "Object", "Place", "Region", "Landmark"],
    ];
    let mut passes = Vec::new();
    for group in groups {
        let pass = group
            .iter()
            .filter(|candidate| labels.iter().any(|label| label == **candidate))
            .map(|label| (*label).to_owned())
            .collect::<Vec<_>>();
        if !pass.is_empty() {
            passes.push(pass);
        }
    }
    let overflow = labels
        .into_iter()
        .filter(|label| {
            !groups
                .iter()
                .flat_map(|group| group.iter())
                .any(|known| *known == label.as_str())
        })
        .collect::<Vec<_>>();
    for chunk in overflow.chunks(6) {
        passes.push(chunk.to_vec());
    }
    passes
}

fn bi_model_labels(label_pack: &LabelPack) -> Vec<String> {
    let mut labels = Vec::new();
    for label in &label_pack.labels {
        push_model_label_aliases(&mut labels, label.as_str());
    }
    labels
}

fn insert_bi_prediction(
    by_key: &mut BTreeMap<(u32, u32, String), DiscoveredSpan>,
    prediction: GlinerBiPrediction,
) {
    let start = prediction.span_start as u32;
    let end = prediction.span_end as u32;
    let label = runtime_label(&prediction.label).to_owned();
    let key = (start, end, label.clone());
    let span = DiscoveredSpan {
        window_relative_range: TextRange { start, end },
        surface: prediction.text.into(),
        label: EntityLabel::new(&label),
        confidence: prediction.score,
    };
    by_key
        .entry(key)
        .and_modify(|current| {
            if span.confidence > current.confidence {
                *current = span.clone();
            }
        })
        .or_insert(span);
}

fn push_model_label_aliases(labels: &mut Vec<String>, label: &str) {
    let normalized = label.trim().to_ascii_lowercase();
    let aliases: &[&str] = match normalized.as_str() {
        "character" | "npc" | "person" | "speaker" | "executive" | "researcher" | "party" => {
            &["Person"]
        }
        "organization" | "organisation" | "faction" | "alliance" | "department" | "institution"
        | "guild" | "council" => &["Organization"],
        "location" | "place" | "region" | "landmark" | "city" | "country" | "nation"
        | "jurisdiction" => &["Location", "Place", "Region", "Landmark"],
        "artifact" => &["Artifact", "Item", "Object"],
        "item" | "object" | "product" | "dataset" => &["Item", "Object"],
        "weapon" => &["Weapon", "Artifact"],
        "creature" => &["Creature", "Species", "Monster"],
        "species" | "monster" | "nonhuman" | "denizen" => &["Creature", "Species", "Monster"],
        "ability" => &["Ability"],
        "spell" => &["Spell", "Ability"],
        "rank" | "role" | "title" => &["Rank", "Role", "Concept"],
        "concept" | "theory" | "method" | "metric" | "initiative" | "risk" | "algorithm"
        | "state" | "goal" | "relationship" | "emotion" => &["Concept"],
        "event" | "ruling" | "claim" | "error" | "benchmark" => &["Event"],
        _ => &[],
    };
    if aliases.is_empty() {
        let trimmed = label.trim();
        if !trimmed.is_empty() && !labels.iter().any(|existing| existing == trimmed) {
            labels.push(trimmed.to_owned());
        }
        return;
    }
    for alias in aliases {
        if !labels.iter().any(|existing| existing == alias) {
            labels.push((*alias).to_owned());
        }
    }
}

fn runtime_label(label: &str) -> &str {
    let lower = label.to_ascii_lowercase();
    match lower.as_str() {
        "person" => "Character",
        "place" | "region" | "landmark" => "Location",
        "item" | "object" | "weapon" => "Artifact",
        "species" | "monster" | "nonhuman" | "denizen" => "Creature",
        "rank" | "role" | "state" | "goal" | "relationship" => "Concept",
        "organization" => "Organization",
        "location" => "Location",
        _ => label,
    }
}

fn threshold() -> f32 {
    env::var("PHOENIX_DYN_NER_THRESHOLD")
        .ok()
        .and_then(|value| value.parse::<f32>().ok())
        .filter(|value| value.is_finite() && *value > 0.0 && *value < 1.0)
        .unwrap_or(0.35)
}

fn overlap_policy() -> GlinerBiOverlapPolicy {
    env::var("PHOENIX_DYN_NER_OVERLAP_POLICY")
        .ok()
        .and_then(|value| GlinerBiOverlapPolicy::parse(&value).ok())
        .unwrap_or_default()
}

fn load_first_available_model() -> Result<LoadedGlinerModel, String> {
    let candidates = default_model_roots();
    let mut errors = Vec::new();
    for root in candidates {
        if !root.is_dir() {
            continue;
        }
        if looks_like_bi_root(&root) {
            match GlinerBiModel::load(&root) {
                Ok(model) => return Ok(LoadedGlinerModel::Bi(Arc::new(model))),
                Err(error) => errors.push(format!("BI {}: {error}", root.display())),
            }
        }
        if looks_like_x_root(&root) {
            match GlinerXModel::load(&root, threshold()) {
                Ok(model) => return Ok(LoadedGlinerModel::X(Arc::new(model))),
                Err(error) => errors.push(format!("X {}: {error}", root.display())),
            }
        }
    }

    let detail = if errors.is_empty() {
        "no usable GLiNER BI/X ONNX root found".to_owned()
    } else {
        errors.join("; ")
    };
    Err(format!(
        "missing PHOENIX_DYN_NER_MODEL_ROOT/PHOENIX_DYN_NER_X_MODEL_ROOT and default GLiNER search failed: {detail}"
    ))
}

fn default_model_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    for key in [
        "PHOENIX_DYN_NER_MODEL_ROOT",
        "PHOENIX_DYN_NER_BI_MODEL_ROOT",
        "PHOENIX_DYN_NER_X_MODEL_ROOT",
        "PHOENIX_DYN_NER_X_MODEL_PATH",
        "PHOENIX_DYN_NER_MODEL_PATH",
    ] {
        if let Some(root) = env::var_os(key).map(PathBuf::from) {
            push_unique_path(&mut roots, root);
        }
    }

    if let Ok(cwd) = env::current_dir() {
        for base in cwd.ancestors().take(6) {
            for name in [
                "gliner-bi-base-v2.0-onnx",
                "gliner-bi-small-onnx",
                "gliner-bi-onnx",
                "gliner-x-small-bi-compat",
                "gliner-x-small",
            ] {
                push_unique_path(&mut roots, base.join(name));
            }
        }
    }

    for model_root in [
        "D:\\hf-models",
        "G:\\hf-models",
        "D:\\phoenix-models",
        "G:\\phoenix-models",
    ] {
        let base = PathBuf::from(model_root);
        for name in [
            "gliner-bi-base-v2.0-onnx",
            "gliner-bi-small-onnx",
            "gliner-bi-onnx",
            "gliner-x-small-bi-compat",
            "gliner-x-small",
        ] {
            push_unique_path(&mut roots, base.join(name));
        }
    }

    roots
}

fn push_unique_path(roots: &mut Vec<PathBuf>, root: PathBuf) {
    if !roots.iter().any(|existing| existing == &root) {
        roots.push(root);
    }
}

fn looks_like_bi_root(path: &Path) -> bool {
    path.is_dir()
        && (path.join("tokenizer.json").is_file()
            || path.join("text_tokenizer").join("tokenizer.json").is_file())
        && path.join("labels_embeddings.json").is_file()
        && [
            "model_label_embeds_quantized.onnx",
            "onnx/model_label_embeds_quantized.onnx",
            "model_label_embeds.onnx",
            "onnx/model_label_embeds.onnx",
        ]
        .iter()
        .any(|candidate| path.join(candidate).is_file())
}

fn looks_like_x_root(path: &Path) -> bool {
    path.is_dir()
        && (path.join("tokenizer.json").is_file() || path.join("onnx/tokenizer.json").is_file())
        && [
            "onnx/model_quantized.onnx",
            "model_quantized.onnx",
            "onnx/model.onnx",
            "model.onnx",
        ]
        .iter()
        .any(|candidate| path.join(candidate).is_file())
}

#[cfg(test)]
mod tests {
    use super::*;
    use phoenix_dynamic_ner::DomainProfile;

    #[test]
    fn label_passes_expand_aliases_without_one_large_pack() {
        let mut labels = LabelPack::default().labels;
        for label in [
            "Character",
            "Organization",
            "Location",
            "Event",
            "Artifact",
            "Creature",
            "Ability",
            "Rank",
        ] {
            labels.push(EntityLabel::new(label));
        }
        let pack = LabelPack {
            domain: DomainProfile::Fantasy,
            labels,
            label_sources: Default::default(),
            seed_surfaces: Default::default(),
            negative_labels: Default::default(),
            max_labels: 14,
        };

        let passes = model_label_passes(&pack);

        assert!(passes.len() > 1);
        assert!(passes.iter().all(|pass| pass.len() <= 6));
        assert!(passes
            .iter()
            .any(|pass| pass.iter().any(|label| label == "Species")
                && pass.iter().any(|label| label == "Monster")));
        assert!(passes
            .iter()
            .any(|pass| pass.iter().any(|label| label == "Concept")));
    }

    #[test]
    fn runtime_labels_collapse_aliases_to_atlas_families() {
        assert_eq!(runtime_label("Species"), "Creature");
        assert_eq!(runtime_label("Monster"), "Creature");
        assert_eq!(runtime_label("Rank"), "Concept");
        assert_eq!(runtime_label("Place"), "Location");
        assert_eq!(runtime_label("person"), "Character");
        assert_eq!(runtime_label("weapon"), "Artifact");
    }
}
