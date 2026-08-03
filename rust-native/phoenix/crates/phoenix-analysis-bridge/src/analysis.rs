use crate::{identity, ner, nli};
use anyhow::{Context, Result};
use phoenix_analysis_contract::{
    capability, AnalysisChunkRecord, AnalysisModelIdentity, AnalysisSentenceRecord,
    AnalysisSpanRecord, AnalysisStageReceipt, DocumentAnalysisBinding, NliCandidateKind,
    PhoenixAnalysisRequestV1, PhoenixDocumentAnalysisV1, PhoenixNerArtifactV1,
    PhoenixNliArtifactV1, PhoenixProducerCoordinatorV1, PhoenixStructuralSubstrateV1,
    ProducerRunState, SemanticProduct, StructuralDialogueHint, StructuralSentenceQuality,
    StructuralSpanKind, ANALYSIS_CONTRACT, NO_STRUCTURAL_PARENT, PRODUCER_COORDINATOR_CONTRACT,
    PRODUCER_QUEUE_CAPACITY, STRUCTURAL_SUBSTRATE_CONTRACT,
};
use std::path::{Path, PathBuf};
use std::time::Instant;

pub struct AnalysisOutput {
    pub analysis: PhoenixDocumentAnalysisV1,
    pub structural: PhoenixStructuralSubstrateV1,
    pub coordinator: PhoenixProducerCoordinatorV1,
}

pub struct LoadedAnalysisRuntime {
    ner_root: PathBuf,
    nli_root: PathBuf,
    ner: ner::LoadedNer,
    nli: nli::LoadedNli,
    identities: ResidentAnalysisIdentities,
    pub ner_load_micros: u64,
    pub nli_load_micros: u64,
    pub total_load_micros: u64,
    pub ner_cache_hit: bool,
    pub nli_cache_hit: bool,
}

#[derive(Clone)]
struct ResidentAnalysisIdentities {
    producer_binary_hash: [u8; 32],
    chunker: AnalysisModelIdentity,
    dynamic_ner: AnalysisModelIdentity,
    nli: AnalysisModelIdentity,
}

impl LoadedAnalysisRuntime {
    pub fn load(ner_root: &Path, nli_root: &Path) -> Result<Self> {
        let total_started = Instant::now();
        // DirectML session construction performs graph optimization and GPU
        // resource initialization. Building both large sessions concurrently
        // can exhaust the driver's scheduling budget and trigger a TDR. Model
        // warmup is infrequent, so serialize it and keep inference resident.
        let ner = ner::LoadedNer::load(ner_root)?;
        let nli = nli::LoadedNli::load(nli_root)?;
        // Hash immutable executable/model assets once while the runtime is
        // warming. Re-hashing roughly 320 MiB for every unchanged document
        // run wastes memory bandwidth and adds no authority.
        let identities = resident_identities(&ner, &nli)?;
        let ner_load_micros = ner.load_micros;
        let nli_load_micros = nli.load_micros;
        let ner_cache_hit = ner.cache_status.is_hit();
        let nli_cache_hit = nli.cache_status.is_hit();
        Ok(Self {
            ner_root: ner_root.to_path_buf(),
            nli_root: nli_root.to_path_buf(),
            ner,
            nli,
            identities,
            ner_load_micros,
            nli_load_micros,
            total_load_micros: elapsed_micros(total_started),
            ner_cache_hit,
            nli_cache_hit,
        })
    }

    pub fn analyze(&self, request: &PhoenixAnalysisRequestV1) -> Result<AnalysisOutput> {
        if Path::new(&request.ner_model_root) != self.ner_root
            || Path::new(&request.nli_model_root) != self.nli_root
        {
            anyhow::bail!("analysis request model roots do not match the resident runtime");
        }
        analyze_loaded(request, &self.ner, &self.nli, &self.identities)
    }
}

pub fn analyze(request: &PhoenixAnalysisRequestV1) -> Result<AnalysisOutput> {
    let ner_model_root = PathBuf::from(&request.ner_model_root);
    let nli_model_root = PathBuf::from(&request.nli_model_root);
    let runtime = LoadedAnalysisRuntime::load(&ner_model_root, &nli_model_root)?;
    runtime.analyze(request)
}

fn analyze_loaded(
    request: &PhoenixAnalysisRequestV1,
    ner: &ner::LoadedNer,
    nli: &nli::LoadedNli,
    identities: &ResidentAnalysisIdentities,
) -> Result<AnalysisOutput> {
    let mut ner_run = ner.run(
        &request.binding.source_document_id,
        &request.binding.content_hash,
        &request.text,
        request.max_nli_candidates as usize,
    )?;
    let nli_run = nli.run(&ner_run.candidates)?;
    let binding = DocumentAnalysisBinding {
        source_document_id: request.binding.source_document_id.clone(),
        native_document_id: request.binding.native_document_id,
        document_revision: request.binding.document_revision,
        content_hash: request.binding.content_hash,
        analysis_generation: request.binding.analysis_generation,
        source_registry_revision: request.binding.source_registry_revision,
        target_registry_revision: request.binding.target_registry_revision,
        producer_binary_hash: identities.producer_binary_hash,
        chunker: identities.chunker.clone(),
        dynamic_ner: identities.dynamic_ner.clone(),
        nli: identities.nli.clone(),
    };
    let receipt = AnalysisStageReceipt {
        chunk_count: ner_run.chunk_count.try_into().unwrap_or(u32::MAX),
        sentence_count: ner_run.sentence_count.try_into().unwrap_or(u32::MAX),
        mention_count: ner_run.mentions.len().try_into().unwrap_or(u32::MAX),
        entity_count: ner_run.entities.len().try_into().unwrap_or(u32::MAX),
        nli_candidate_count: ner_run.candidates.len().try_into().unwrap_or(u32::MAX),
        nli_adjudication_count: nli_run.adjudications.len().try_into().unwrap_or(u32::MAX),
        chunker_micros: ner_run.chunker_micros,
        dynamic_ner_micros: ner_run.dynamic_ner_micros,
        nli_load_micros: nli_run.load_micros,
        nli_adjudication_micros: nli_run.adjudication_micros,
        promotion_count: 0,
    };
    let structural = convert_structural(&request.text, binding.clone(), &ner_run.structural)?;
    let artifact = PhoenixDocumentAnalysisV1 {
        schema: ANALYSIS_CONTRACT.to_owned(),
        ner: PhoenixNerArtifactV1 {
            binding: binding.clone(),
            ner_revision: request.binding.analysis_generation,
            entities: ner_run.entities,
            mentions: ner_run.mentions,
            receipt,
        },
        nli: PhoenixNliArtifactV1 {
            binding,
            nli_candidates: ner_run.candidates,
            nli_adjudications: nli_run.adjudications,
            promotion_count: 0,
        },
    };
    let identity_candidates = artifact
        .nli
        .nli_candidates
        .iter()
        .filter(|candidate| candidate.kind != NliCandidateKind::Related)
        .count()
        .min(u32::MAX as usize) as u32;
    let generic_related = artifact
        .nli
        .nli_candidates
        .iter()
        .filter(|candidate| candidate.kind == NliCandidateKind::Related)
        .count()
        .min(u32::MAX as usize) as u32;
    let coordinator = PhoenixProducerCoordinatorV1 {
        schema: PRODUCER_COORDINATOR_CONTRACT.to_owned(),
        binding: artifact.ner.binding.clone(),
        queue_capacity: PRODUCER_QUEUE_CAPACITY,
        queue_high_water: 1,
        cancellation_observed: false,
        promotion_count: 0,
        capabilities: vec![
            capability(
                SemanticProduct::DocumentStructure,
                "phoenix-chunker/structural-v1",
                ProducerRunState::Produced,
                Some(
                    structural
                        .sentences
                        .len()
                        .saturating_add(structural.spans.len())
                        .min(u32::MAX as usize) as u32,
                ),
            ),
            capability(
                SemanticProduct::DynamicChunksAndSpans,
                "phoenix-chunker/structural-v1",
                ProducerRunState::Produced,
                Some(structural.chunks.len().min(u32::MAX as usize) as u32),
            ),
            capability(
                SemanticProduct::MentionsAndEvidence,
                "phoenix-dynamic-ner",
                ProducerRunState::Produced,
                Some(artifact.ner.mentions.len().min(u32::MAX as usize) as u32),
            ),
            capability(
                SemanticProduct::CanonicalEntityBindings,
                "phoenix-native-atlas-registry",
                ProducerRunState::NotRun,
                None,
            ),
            capability(
                SemanticProduct::IdentityAliasCoreference,
                "phoenix-dynamic-ner+ModernBERT-NLI",
                ProducerRunState::Produced,
                Some(identity_candidates),
            ),
            capability(
                SemanticProduct::GenericRelatedEvidence,
                "phoenix-dynamic-ner+ModernBERT-NLI",
                ProducerRunState::Produced,
                Some(generic_related),
            ),
            capability(
                SemanticProduct::TypedRelationships,
                "none",
                ProducerRunState::Unsupported,
                None,
            ),
            capability(
                SemanticProduct::EventsTimeline,
                "none",
                ProducerRunState::Unsupported,
                None,
            ),
            capability(
                SemanticProduct::Causality,
                "none",
                ProducerRunState::Unsupported,
                None,
            ),
            capability(
                SemanticProduct::MemoryState,
                "none",
                ProducerRunState::Unsupported,
                None,
            ),
            capability(
                SemanticProduct::ContextualCoOccurrence,
                "phoenix-scene-compiler/contextual-cooccurrence-v1",
                ProducerRunState::NotRun,
                None,
            ),
        ],
        evidence_bindings: std::mem::take(&mut ner_run.candidate_evidence),
        contextual_evidence_bindings: Vec::new(),
    };
    artifact.validate().map_err(anyhow::Error::msg)?;
    structural.validate().map_err(anyhow::Error::msg)?;
    coordinator
        .validate_preliminary(&artifact, &structural)
        .map_err(anyhow::Error::msg)?;
    Ok(AnalysisOutput {
        analysis: artifact,
        structural,
        coordinator,
    })
}

fn resident_identities(
    ner: &ner::LoadedNer,
    nli_runtime: &nli::LoadedNli,
) -> Result<ResidentAnalysisIdentities> {
    let executable = std::env::current_exe().context("resolve analysis bridge executable")?;
    let producer_binary_hash = identity::file_hash(&executable)?;
    let ner_metadata = ner.metadata();
    let nli_metadata = nli_runtime.metadata();
    let chunker = identity::identity(
        "phoenix-chunker/structural-v1",
        producer_binary_hash,
        identity::config_hash(b"ChunkerConfig::default;sentence_ranges;structural_substrate"),
        "rust-native",
    );
    let dynamic_ner = identity::identity(
        "phoenix-dynamic-ner+gliner-bi-base-v2.0",
        identity::combined_file_hash(&[
            Path::new(&ner_metadata.model_path),
            Path::new(&ner_metadata.text_tokenizer_path),
            Path::new(&ner_metadata.labels_tokenizer_path),
        ])?,
        identity::config_hash(
            format!(
                "threshold=0.35;max_labels=14;max_model_windows=20;max_context_sentences=3;\
              model_window_merge=none;gliner_batch_size={};ort_memory_pattern=false;overlap=default;\
              nli_evidence_sentence_distance=1;nli_evidence_max_bytes=4096",
                ner::batch_size()
            )
            .as_bytes(),
        ),
        "ort-2.0.0-rc.9",
    );
    let nli = identity::identity(
        "onnx-community/ModernBERT-base-nli-ONNX",
        identity::combined_file_hash(&[
            Path::new(&nli_metadata.model_path),
            Path::new(&nli_metadata.tokenizer_path),
        ])?,
        identity::config_hash(
            format!(
                "max_length={};labels={},{},{};padding=dynamic-microbatch-v1;max_pairs_per_batch={};attention_work_budget={};ort_memory_pattern=false",
                nli_metadata.max_length,
                nli_metadata.contradiction_idx,
                nli_metadata.entailment_idx,
                nli_metadata.neutral_idx,
                nli::batch_size(),
                phoenix_rel_post::nli_attention_work_budget()
            )
            .as_bytes(),
        ),
        format!("ort:{}", nli_metadata.ort_execution_provider_preference),
    );
    Ok(ResidentAnalysisIdentities {
        producer_binary_hash,
        chunker,
        dynamic_ner,
        nli,
    })
}

fn elapsed_micros(started: Instant) -> u64 {
    started.elapsed().as_micros().try_into().unwrap_or(u64::MAX)
}

fn convert_structural(
    text: &str,
    binding: DocumentAnalysisBinding,
    source: &phoenix_chunker_native::StructuralSubstrate,
) -> Result<PhoenixStructuralSubstrateV1> {
    let chunks = source
        .base_chunks
        .iter()
        .map(|record| {
            Ok(AnalysisChunkRecord {
                start: checked(record.start, "chunk start")?,
                end: checked(record.end, "chunk end")?,
                sentence_start: checked(record.sentence_start, "chunk sentence start")?,
                sentence_end: checked(record.sentence_end, "chunk sentence end")?,
                paragraph_start: checked(record.paragraph_start, "chunk paragraph start")?,
                paragraph_end: checked(record.paragraph_end, "chunk paragraph end")?,
                chapter_index: record
                    .chapter_index
                    .map(|value| checked(value, "chunk chapter"))
                    .transpose()?
                    .unwrap_or(NO_STRUCTURAL_PARENT),
                token_count: checked(record.token_count, "chunk token count")?,
                content_hash: record.content_hash,
                dialogue_hint: dialogue(record.dialogue_hint),
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let sentences = source
        .sentences
        .iter()
        .map(|record| {
            Ok(AnalysisSentenceRecord {
                start: checked(record.start, "sentence start")?,
                end: checked(record.end, "sentence end")?,
                paragraph_index: checked(record.paragraph_index, "sentence paragraph")?,
                chapter_index: checked(record.chapter_index, "sentence chapter")?,
                token_count: checked(record.token_count, "sentence token count")?,
                content_hash: record.content_hash,
                quality: sentence_quality(record.quality),
                dialogue_hint: dialogue(record.dialogue_hint),
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let mut spans = Vec::with_capacity(source.paragraphs.len() + source.chapters.len());
    for record in &source.paragraphs {
        spans.push(AnalysisSpanRecord {
            kind: StructuralSpanKind::Paragraph,
            start: checked(record.start, "paragraph start")?,
            end: checked(record.end, "paragraph end")?,
            parent_index: checked(record.chapter_index, "paragraph chapter")?,
            child_start: checked(record.sentence_start, "paragraph sentence start")?,
            child_end: checked(record.sentence_end, "paragraph sentence end")?,
            token_count: checked(record.token_count, "paragraph token count")?,
            content_hash: record.content_hash,
            label: String::new(),
            dialogue_hint: dialogue(record.dialogue_hint),
        });
    }
    for record in &source.chapters {
        spans.push(AnalysisSpanRecord {
            kind: StructuralSpanKind::Chapter,
            start: checked(record.start, "chapter start")?,
            end: checked(record.end, "chapter end")?,
            parent_index: NO_STRUCTURAL_PARENT,
            child_start: checked(record.paragraph_start, "chapter paragraph start")?,
            child_end: checked(record.paragraph_end, "chapter paragraph end")?,
            token_count: checked(record.token_count, "chapter token count")?,
            content_hash: record.content_hash,
            label: record.title.clone(),
            dialogue_hint: StructuralDialogueHint::None,
        });
    }
    Ok(PhoenixStructuralSubstrateV1 {
        schema: STRUCTURAL_SUBSTRATE_CONTRACT.to_owned(),
        binding,
        source_len: checked(text.len(), "source length")?,
        chunks,
        sentences,
        spans,
    })
}

fn checked(value: usize, name: &'static str) -> Result<u32> {
    u32::try_from(value).with_context(|| format!("{name} exceeds the v1 u32 bound"))
}

fn dialogue(value: phoenix_chunker_native::DialogueBoundaryHint) -> StructuralDialogueHint {
    match value {
        phoenix_chunker_native::DialogueBoundaryHint::None => StructuralDialogueHint::None,
        phoenix_chunker_native::DialogueBoundaryHint::OpensQuote => {
            StructuralDialogueHint::OpensQuote
        }
        phoenix_chunker_native::DialogueBoundaryHint::ClosesQuote => {
            StructuralDialogueHint::ClosesQuote
        }
        phoenix_chunker_native::DialogueBoundaryHint::QuotedSentence => {
            StructuralDialogueHint::QuotedSentence
        }
        phoenix_chunker_native::DialogueBoundaryHint::DialogueLine => {
            StructuralDialogueHint::DialogueLine
        }
    }
}

fn sentence_quality(value: phoenix_chunker_native::SentenceQuality) -> StructuralSentenceQuality {
    match value {
        phoenix_chunker_native::SentenceQuality::Empty => StructuralSentenceQuality::Empty,
        phoenix_chunker_native::SentenceQuality::Fragment => StructuralSentenceQuality::Fragment,
        phoenix_chunker_native::SentenceQuality::Complete => StructuralSentenceQuality::Complete,
        phoenix_chunker_native::SentenceQuality::RunOn => StructuralSentenceQuality::RunOn,
        phoenix_chunker_native::SentenceQuality::NoTerminalPunctuation => {
            StructuralSentenceQuality::NoTerminalPunctuation
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use phoenix_analysis_contract::AnalysisModelIdentity;

    #[test]
    fn exact_chunker_records_survive_the_bridge_boundary() {
        let text = "## Chapter 1: Test\n\nAlpha arrived. Beta waited.";
        let source = phoenix_chunker_native::build_structural_substrate(
            text,
            &phoenix_chunker_native::ChunkerConfig::default(),
        );
        let identity = AnalysisModelIdentity {
            model_id: "fixture".into(),
            artifact_hash: [2; 32],
            config_hash: [3; 32],
            runtime_id: "test".into(),
        };
        let binding = DocumentAnalysisBinding {
            source_document_id: "fixture".into(),
            native_document_id: 1,
            document_revision: 1,
            content_hash: *blake3::hash(text.as_bytes()).as_bytes(),
            analysis_generation: 1,
            source_registry_revision: 0,
            target_registry_revision: 1,
            producer_binary_hash: [1; 32],
            chunker: identity.clone(),
            dynamic_ner: identity.clone(),
            nli: identity,
        };
        let converted = convert_structural(text, binding, &source).expect("convert exact records");
        converted.validate().expect("validate exact records");
        assert_eq!(converted.chunks.len(), source.base_chunks.len());
        assert_eq!(converted.sentences.len(), source.sentences.len());
        for (packed, exact) in converted.chunks.iter().zip(&source.base_chunks) {
            assert_eq!(
                (packed.start, packed.end, packed.content_hash),
                (exact.start as u32, exact.end as u32, exact.content_hash)
            );
            assert_eq!(
                (packed.sentence_start, packed.sentence_end),
                (exact.sentence_start as u32, exact.sentence_end as u32)
            );
        }
    }
}
