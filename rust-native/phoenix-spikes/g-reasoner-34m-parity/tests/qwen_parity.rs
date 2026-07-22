#![cfg(feature = "qwen")]

use std::path::{Path, PathBuf};

use g_reasoner_34m_parity::constants::{FEATURE_DIM, QWEN_REVISION};
use g_reasoner_34m_parity::qwen::QwenEmbedder;
use serde::Deserialize;

#[derive(Deserialize)]
struct Fixture {
    revision: String,
    query: String,
    token_ids: Vec<u32>,
    dimensions: usize,
}

fn fixture_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures")
}

fn expected_embedding() -> Vec<f32> {
    let bytes = std::fs::read(fixture_dir().join("qwen-parity.safetensors")).unwrap();
    let tensors = safetensors::SafeTensors::deserialize(&bytes).unwrap();
    let view = tensors.tensor("query_embedding").unwrap();
    bytemuck::cast_slice::<u8, f32>(view.data()).to_vec()
}

#[test]
#[ignore = "requires the pinned 1.2 GB Qwen artifact"]
fn native_qwen_matches_float32_reference() {
    let fixture: Fixture =
        serde_json::from_slice(&std::fs::read(fixture_dir().join("qwen-parity.json")).unwrap())
            .unwrap();
    assert_eq!(fixture.revision, QWEN_REVISION);
    assert_eq!(fixture.dimensions, FEATURE_DIM);
    let model_dir = std::env::var_os("G_REASONER_QWEN_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\qwen"));
    let embedder = QwenEmbedder::load(model_dir, 512).unwrap();
    assert_eq!(
        embedder.token_ids(&fixture.query).unwrap(),
        fixture.token_ids
    );

    let actual = embedder.embed_query(&fixture.query).unwrap();
    let expected = expected_embedding();
    assert_eq!(actual.len(), FEATURE_DIM);
    let max_abs = actual
        .iter()
        .zip(&expected)
        .map(|(left, right)| (left - right).abs())
        .fold(0.0f32, f32::max);
    let cosine = actual
        .iter()
        .zip(&expected)
        .map(|(left, right)| left * right)
        .sum::<f32>();
    println!("QWEN max_abs={max_abs:.9} cosine={cosine:.9}");
    assert!(max_abs <= 0.01, "Qwen max_abs {max_abs} exceeded 0.01");
    assert!(cosine >= 0.999, "Qwen cosine {cosine} fell below 0.999");

    let passages = [
        "Ryan arrives in New Rome.",
        "Dynamis controls the temporal signature.",
        "Quicksave preserves the previous state.",
    ];
    let batched = embedder.embed_passages_batch(&passages).unwrap();
    let chunked = embedder.embed_passages_chunked(&passages, 1).unwrap();
    for (row, (batch, chunk)) in batched.iter().zip(&chunked).enumerate() {
        let error = batch
            .iter()
            .zip(chunk)
            .map(|(left, right)| (left - right).abs())
            .fold(0.0f32, f32::max);
        assert!(error <= 1e-5, "Qwen chunked row {row} error {error}");
    }
}
