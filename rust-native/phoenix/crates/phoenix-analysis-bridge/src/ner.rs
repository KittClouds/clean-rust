use anyhow::{Context, Result};
use compact_str::CompactString;
use phoenix_analysis_contract::{
    AnalysisEntity, AnalysisEntityKind, AnalysisMention, NliCandidate, NliCandidateKind,
};
use phoenix_dynamic_ner::{
    DiscoveredSpan, DynamicNerModel, DynamicSchemaBuilder, EntityLabel, LabelPack, LocalMentionId,
    MentionEdgeKind, MentionKind, MentionPacket, MentionVote, ModelNerRequest, ModelNerWindow,
    NerModelError, PhoenixNerEngineBuilder, SurfaceNerInput, VerificationCase,
};
use phoenix_rel_post::{
    GlinerBiModel, GlinerBiOverlapPolicy, GlinerBiPredictOptions, GlinerBiPrediction,
};
use phoenix_types::{
    MentionEntityRef, PosTag, ScopeKey, SentenceSpan, TextRange, TokenClass, TokenSpan,
};
use std::collections::{BTreeMap, HashMap};
use std::path::Path;
use std::time::Instant;

const MAX_NLI_SENTENCE_DISTANCE: u32 = 1;
const MAX_NLI_PREMISE_BYTES: u32 = 4_096;

pub struct NerRun {
    pub entities: Vec<AnalysisEntity>,
    pub mentions: Vec<AnalysisMention>,
    pub candidates: Vec<NliCandidate>,
    pub chunk_count: usize,
    pub sentence_count: usize,
    pub chunker_micros: u64,
    pub dynamic_ner_micros: u64,
}

struct AggregatedEntities {
    entities: Vec<AnalysisEntity>,
    mentions: Vec<AnalysisMention>,
    entity_by_mention: HashMap<u64, u64>,
}

struct BiBackend {
    model: GlinerBiModel,
    threshold: f32,
}

pub fn run(
    document_id: &str,
    document_hash: &[u8; 32],
    text: &str,
    model_root: &Path,
    max_nli_candidates: usize,
) -> Result<(NerRun, phoenix_rel_post::GlinerBiModelMetadata)> {
    let chunk_started = Instant::now();
    let substrate = phoenix_chunker_native::build_structural_substrate(
        text,
        &phoenix_chunker_native::ChunkerConfig::default(),
    );
    let (tokens, sentences) = tokenize(text);
    let chunk_elapsed = elapsed_micros(chunk_started);
    let model = GlinerBiModel::load(model_root)
        .with_context(|| format!("load GLiNER-BI from {}", model_root.display()))?;
    let metadata = model.metadata().clone();
    let engine = PhoenixNerEngineBuilder::new()
        .schema(DynamicSchemaBuilder {
            max_labels: 14,
            ..Default::default()
        })
        .model(Box::new(BiBackend {
            model,
            threshold: 0.35,
        }))
        .build();
    let scope = ScopeKey::default();
    let started = Instant::now();
    let output = engine
        .extract_mentions(&SurfaceNerInput {
            document_id,
            text,
            tokens: &tokens,
            sentences: &sentences,
            scope: &scope,
            lexicon: None,
            surface_hits: &[],
            label_bank_context: None,
        })
        .context("dynamic NER extraction")?;
    let dynamic_ner_micros = elapsed_micros(started);
    let aggregated = aggregate_entities(document_hash, &output.mentions)?;
    let candidates = build_nli_candidates(
        text,
        &sentences,
        &output.mentions,
        &output.mention_graph.edges,
        &aggregated.entity_by_mention,
        max_nli_candidates,
    );
    Ok((
        NerRun {
            entities: aggregated.entities,
            mentions: aggregated.mentions,
            candidates,
            chunk_count: substrate.base_chunks.len(),
            sentence_count: sentences.len(),
            chunker_micros: chunk_elapsed,
            dynamic_ner_micros,
        },
        metadata,
    ))
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
        let predictions = self
            .model
            .predict_with_options(
                window.text,
                &labels,
                &GlinerBiPredictOptions {
                    threshold: self.threshold,
                    overlap_policy: GlinerBiOverlapPolicy::default(),
                },
            )
            .map_err(|error| NerModelError::Inference(error.to_string()))?;
        let mut by_key = BTreeMap::new();
        for prediction in predictions {
            insert_model_prediction(&mut by_key, prediction);
        }
        Ok(by_key.into_values().collect())
    }

    fn discover_batch(
        &self,
        requests: &[ModelNerRequest<'_>],
    ) -> Result<Vec<Vec<DiscoveredSpan>>, NerModelError> {
        let options = GlinerBiPredictOptions {
            threshold: self.threshold,
            overlap_policy: GlinerBiOverlapPolicy::default(),
        };
        let mut per_request = (0..requests.len())
            .map(|_| BTreeMap::new())
            .collect::<Vec<_>>();
        let mut groups = BTreeMap::<Vec<String>, Vec<(usize, &str)>>::new();
        for (request_index, request) in requests.iter().enumerate() {
            let labels = model_labels(request.label_pack);
            if !labels.is_empty() {
                groups
                    .entry(labels)
                    .or_default()
                    .push((request_index, request.window.text));
            }
        }
        for (labels, items) in groups {
            let texts = items.iter().map(|(_, text)| *text).collect::<Vec<_>>();
            let predictions = self
                .model
                .predict_texts_with_options_batched(&texts, &labels, &options, 1)
                .map_err(|error| NerModelError::Inference(error.to_string()))?;
            for prediction in predictions {
                let Some((request_index, _)) = items.get(prediction.sequence) else {
                    continue;
                };
                insert_model_prediction(
                    &mut per_request[*request_index],
                    GlinerBiPrediction {
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

fn aggregate_entities(
    document_hash: &[u8; 32],
    packets: &[MentionPacket],
) -> Result<AggregatedEntities> {
    struct Group {
        stable_id: u64,
        label: String,
        kind: AnalysisEntityKind,
        count: u32,
        best_confidence: f32,
    }
    let mut groups = BTreeMap::<String, Group>::new();
    let mut entity_by_mention = HashMap::with_capacity(packets.len());
    let mut pending = Vec::with_capacity(packets.len());
    for packet in packets
        .iter()
        .filter(|packet| packet.is_exportable() && packet.mention_kind != MentionKind::Pronoun)
    {
        let kind = packet_kind(packet);
        let identity_key = mention_identity_key(packet, kind);
        let stable_id = stable_entity_id(document_hash, &identity_key);
        let group = groups.entry(identity_key).or_insert_with(|| Group {
            stable_id,
            label: packet.surface.to_string(),
            kind,
            count: 0,
            best_confidence: -1.0,
        });
        group.count = group.count.saturating_add(1);
        if packet.confidence > group.best_confidence {
            group.best_confidence = packet.confidence;
            group.label = packet.surface.to_string();
        }
        entity_by_mention.insert(packet.mention_id.0, stable_id);
        pending.push((packet, stable_id));
    }
    let entities = groups
        .into_values()
        .map(|group| AnalysisEntity {
            stable_id: group.stable_id,
            label: group.label,
            kind: group.kind,
            custom_kind: (group.kind == AnalysisEntityKind::Custom).then(|| "ENTITY".to_owned()),
            mention_count: group.count,
        })
        .collect::<Vec<_>>();
    let mentions = pending
        .into_iter()
        .map(|(packet, entity_id)| AnalysisMention {
            mention_id: packet.mention_id.0.saturating_add(1),
            entity_id,
            start: packet.range.start,
            end: packet.range.end,
            sentence_index: packet.sentence_index,
            confidence: packet.confidence.clamp(0.0, 1.0),
            accepted: packet.is_accepted(),
        })
        .collect();
    Ok(AggregatedEntities {
        entities,
        mentions,
        entity_by_mention,
    })
}

fn mention_identity_key(packet: &MentionPacket, kind: AnalysisEntityKind) -> String {
    let authority = match packet.entity_ref.as_ref() {
        Some(MentionEntityRef::Known(id)) => format!("known:{}", id.0),
        Some(MentionEntityRef::Speculative(id)) => format!("speculative:{id}"),
        None => format!("surface:{}", packet.normalized),
    };
    format!("{}:{authority}", kind as u16)
}

fn stable_entity_id(document_hash: &[u8; 32], identity_key: &str) -> u64 {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix.analysis.document-entity/v1\0");
    hasher.update(document_hash);
    hasher.update(identity_key.as_bytes());
    let mut raw = [0_u8; 8];
    raw.copy_from_slice(&hasher.finalize().as_bytes()[..8]);
    u64::from_le_bytes(raw).max(1)
}

fn build_nli_candidates(
    text: &str,
    sentences: &[SentenceSpan],
    packets: &[MentionPacket],
    edges: &[phoenix_dynamic_ner::MentionEdge],
    entity_by_mention: &HashMap<u64, u64>,
    limit: usize,
) -> Vec<NliCandidate> {
    let packet_by_id = packets
        .iter()
        .map(|packet| (packet.mention_id.0, packet))
        .collect::<HashMap<_, _>>();
    let mut candidates = BTreeMap::<[u8; 32], NliCandidate>::new();
    for edge in edges {
        let (Some(left), Some(right)) = (
            packet_by_id.get(&edge.left.0),
            packet_by_id.get(&edge.right.0),
        ) else {
            continue;
        };
        let (Some(&left_entity_id), Some(&right_entity_id)) = (
            entity_by_mention.get(&edge.left.0),
            entity_by_mention.get(&edge.right.0),
        ) else {
            continue;
        };
        let Some((premise_start, premise_end)) =
            enclosing_sentences(sentences, left.sentence_index, right.sentence_index)
        else {
            continue;
        };
        let Some(premise) = text.get(premise_start as usize..premise_end as usize) else {
            continue;
        };
        let kind = candidate_kind(edge.kind);
        let hypothesis = hypothesis(kind, &left.surface, &right.surface);
        let candidate_id = candidate_id(
            left_entity_id,
            right_entity_id,
            premise_start,
            premise_end,
            kind,
        );
        candidates
            .entry(candidate_id)
            .or_insert_with(|| NliCandidate {
                candidate_id,
                kind,
                left_entity_id,
                right_entity_id,
                premise_start,
                premise_end,
                premise: premise.to_owned(),
                hypothesis,
            });
        if candidates.len() >= limit {
            break;
        }
    }
    candidates.into_values().collect()
}

fn enclosing_sentences(sentences: &[SentenceSpan], left: u32, right: u32) -> Option<(u32, u32)> {
    if left.abs_diff(right) > MAX_NLI_SENTENCE_DISTANCE {
        return None;
    }
    let first = usize::try_from(left.min(right)).ok()?;
    let last = usize::try_from(left.max(right)).ok()?;
    let range = (
        sentences.get(first)?.range.start,
        sentences.get(last)?.range.end,
    );
    (range.1.saturating_sub(range.0) <= MAX_NLI_PREMISE_BYTES).then_some(range)
}

fn candidate_kind(kind: MentionEdgeKind) -> NliCandidateKind {
    match kind {
        MentionEdgeKind::SameNormalizedSurface => NliCandidateKind::SameSurface,
        MentionEdgeKind::KnownAliasMatch | MentionEdgeKind::FuzzyAliasMatch => {
            NliCandidateKind::Alias
        }
        MentionEdgeKind::PronounCandidate | MentionEdgeKind::SpeakerContinuity => {
            NliCandidateKind::Coreference
        }
        _ => NliCandidateKind::Related,
    }
}

fn hypothesis(kind: NliCandidateKind, left: &str, right: &str) -> String {
    match kind {
        NliCandidateKind::SameSurface | NliCandidateKind::Alias => {
            format!("{left} and {right} refer to the same entity.")
        }
        NliCandidateKind::Coreference => format!("{right} refers to {left}."),
        NliCandidateKind::Related => format!("{left} is related to {right} in this passage."),
    }
}

fn candidate_id(left: u64, right: u64, start: u32, end: u32, kind: NliCandidateKind) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix.analysis.nli-candidate/v1\0");
    hasher.update(&left.to_le_bytes());
    hasher.update(&right.to_le_bytes());
    hasher.update(&start.to_le_bytes());
    hasher.update(&end.to_le_bytes());
    hasher.update(&[kind as u8]);
    *hasher.finalize().as_bytes()
}

fn packet_kind(packet: &MentionPacket) -> AnalysisEntityKind {
    let label = packet
        .label_distribution
        .iter()
        .max_by(|left, right| left.1.total_cmp(&right.1))
        .map(|(label, _)| label.as_str())
        .unwrap_or("Concept")
        .to_ascii_lowercase();
    match label.as_str() {
        "character" | "person" => AnalysisEntityKind::Character,
        "npc" => AnalysisEntityKind::Npc,
        "location" | "place" | "region" | "landmark" => AnalysisEntityKind::Location,
        "faction" | "organization" | "organisation" | "alliance" => AnalysisEntityKind::Faction,
        "event" => AnalysisEntityKind::Event,
        "concept" | "role" | "state" | "goal" | "relationship" => AnalysisEntityKind::Concept,
        _ => AnalysisEntityKind::Custom,
    }
}

fn model_labels(label_pack: &LabelPack) -> Vec<String> {
    let mut labels = Vec::new();
    for label in &label_pack.labels {
        push_model_label_aliases(&mut labels, label.as_str());
    }
    labels
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

fn insert_model_prediction(
    by_key: &mut BTreeMap<(u32, u32, String), DiscoveredSpan>,
    prediction: GlinerBiPrediction,
) {
    let start = prediction.span_start as u32;
    let end = prediction.span_end as u32;
    let label = runtime_label(&prediction.label).to_owned();
    let key = (start, end, label.clone());
    let span = DiscoveredSpan {
        window_relative_range: TextRange { start, end },
        surface: CompactString::new(prediction.text),
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

fn tokenize(text: &str) -> (Vec<TokenSpan>, Vec<SentenceSpan>) {
    let mut tokens = Vec::new();
    let mut start = None;
    for (index, character) in text.char_indices() {
        if character.is_alphanumeric() || character == '\'' || character == '-' {
            start.get_or_insert(index);
        } else if let Some(start) = start.take() {
            tokens.push(token_span(text, start, index));
        }
    }
    if let Some(start) = start {
        tokens.push(token_span(text, start, text.len()));
    }
    let sentences = phoenix_chunker_native::api::sentence_ranges(text)
        .into_iter()
        .enumerate()
        .map(|(index, (start, end))| SentenceSpan {
            index,
            range: TextRange {
                start: start as u32,
                end: end as u32,
            },
        })
        .collect();
    (tokens, sentences)
}

fn token_span(text: &str, start: usize, end: usize) -> TokenSpan {
    let surface = &text[start..end];
    let lower = surface.to_ascii_lowercase();
    TokenSpan {
        range: TextRange {
            start: start as u32,
            end: end as u32,
        },
        capitalized: surface.starts_with(char::is_uppercase),
        pos: matches!(
            lower.as_str(),
            "he" | "him" | "his" | "she" | "her" | "hers" | "they" | "them" | "their"
        )
        .then_some(PosTag::Pronoun),
        token_class: Some(TokenClass::Word),
        masked: false,
    }
}

fn elapsed_micros(started: Instant) -> u64 {
    started.elapsed().as_micros().try_into().unwrap_or(u64::MAX)
}
