use crate::{identity, ner, nli};
use anyhow::{Context, Result};
use phoenix_analysis_contract::{
    AnalysisStageReceipt, DocumentAnalysisBinding, PhoenixAnalysisRequestV1,
    PhoenixDocumentAnalysisV1, PhoenixNerArtifactV1, PhoenixNliArtifactV1, ANALYSIS_CONTRACT,
};
use std::path::{Path, PathBuf};

pub fn analyze(request: &PhoenixAnalysisRequestV1) -> Result<PhoenixDocumentAnalysisV1> {
    let ner_model_root = PathBuf::from(&request.ner_model_root);
    let nli_model_root = PathBuf::from(&request.nli_model_root);
    let (ner_run, ner_metadata) = ner::run(
        &request.binding.source_document_id,
        &request.binding.content_hash,
        &request.text,
        &ner_model_root,
        request.max_nli_candidates as usize,
    )?;
    let nli_run = nli::run(&ner_run.candidates, &nli_model_root)?;
    let executable = std::env::current_exe().context("resolve analysis bridge executable")?;
    let producer_binary_hash = identity::file_hash(&executable)?;
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
            b"threshold=0.35;max_labels=14;max_model_windows=20;max_context_sentences=3;\
              model_window_merge=none;gliner_batch_size=1;ort_memory_pattern=false;overlap=default;\
              nli_evidence_sentence_distance=1;nli_evidence_max_bytes=4096",
        ),
        "ort-2.0.0-rc.9",
    );
    let nli = identity::identity(
        "onnx-community/ModernBERT-base-nli-ONNX",
        identity::combined_file_hash(&[
            Path::new(&nli_run.metadata.model_path),
            Path::new(&nli_run.metadata.tokenizer_path),
        ])?,
        identity::config_hash(
            format!(
                "max_length={};labels={},{},{};max_pairs_per_batch=1;ort_memory_pattern=false",
                nli_run.metadata.max_length,
                nli_run.metadata.contradiction_idx,
                nli_run.metadata.entailment_idx,
                nli_run.metadata.neutral_idx
            )
            .as_bytes(),
        ),
        format!("ort:{}", nli_run.metadata.ort_execution_provider_preference),
    );
    let binding = DocumentAnalysisBinding {
        source_document_id: request.binding.source_document_id.clone(),
        native_document_id: request.binding.native_document_id,
        document_revision: request.binding.document_revision,
        content_hash: request.binding.content_hash,
        analysis_generation: request.binding.analysis_generation,
        source_registry_revision: request.binding.source_registry_revision,
        target_registry_revision: request.binding.target_registry_revision,
        producer_binary_hash,
        chunker,
        dynamic_ner,
        nli,
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
    artifact.validate().map_err(anyhow::Error::msg)?;
    Ok(artifact)
}
