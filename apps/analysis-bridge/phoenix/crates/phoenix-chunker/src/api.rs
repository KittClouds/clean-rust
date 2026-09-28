//! Stable public entrypoints for sentence splitting and chunk windowing.
//!
//! This stage owns only text segmentation. It expects raw text and returns
//! sentence or chunk ranges. It persists nothing and should be the preferred
//! entrypoint when callers want chunking without pulling in the rest of the
//! pipeline.

use crate::{
    build_chunks, build_structural_substrate, split_sentence_ranges, BaseChunk, ChapterSpan, Chunk,
    ChunkerConfig, ParagraphSpan, SentenceSpan, StructuralSubstrate,
};

#[cfg(not(target_arch = "wasm32"))]
use crate::{build_lens_chunks, LensChunk, LensChunkInput, LensChunkerConfig, LensKind};

pub fn sentence_ranges(text: &str) -> Vec<(usize, usize)> {
    split_sentence_ranges(text)
}

pub fn chunk_ranges(text: &str, config: &ChunkerConfig) -> Vec<Chunk> {
    build_chunks(text, config)
}

pub fn default_chunk_ranges(text: &str) -> Vec<Chunk> {
    build_chunks(text, &ChunkerConfig::default())
}

pub fn structural_substrate(text: &str, config: &ChunkerConfig) -> StructuralSubstrate {
    build_structural_substrate(text, config)
}

pub fn default_structural_substrate(text: &str) -> StructuralSubstrate {
    build_structural_substrate(text, &ChunkerConfig::default())
}

pub fn base_chunks(text: &str, config: &ChunkerConfig) -> Vec<BaseChunk> {
    build_structural_substrate(text, config).base_chunks
}

pub fn sentence_spans(text: &str) -> Vec<SentenceSpan> {
    build_structural_substrate(text, &ChunkerConfig::default()).sentences
}

pub fn paragraph_spans(text: &str) -> Vec<ParagraphSpan> {
    build_structural_substrate(text, &ChunkerConfig::default()).paragraphs
}

pub fn chapter_spans(text: &str) -> Vec<ChapterSpan> {
    build_structural_substrate(text, &ChunkerConfig::default()).chapters
}

#[cfg(not(target_arch = "wasm32"))]
pub fn lens_chunks(input: &LensChunkInput<'_>, config: &LensChunkerConfig) -> Vec<LensChunk> {
    build_lens_chunks(input, config)
}

#[cfg(not(target_arch = "wasm32"))]
pub fn default_lens_chunks(input: &LensChunkInput<'_>) -> Vec<LensChunk> {
    build_lens_chunks(input, &LensChunkerConfig::default())
}

#[cfg(not(target_arch = "wasm32"))]
pub fn lens_chunks_by_kind(input: &LensChunkInput<'_>, lens: LensKind) -> Vec<LensChunk> {
    let config = LensChunkerConfig {
        enabled_lenses: vec![lens],
        ..LensChunkerConfig::default()
    };
    build_lens_chunks(input, &config)
}
