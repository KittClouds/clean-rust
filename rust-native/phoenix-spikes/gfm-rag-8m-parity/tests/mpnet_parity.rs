#![cfg(feature = "mpnet-onnx")]

use std::path::{Path, PathBuf};

use gfm_rag_8m_parity::constants::MPNET_REVISION;
use gfm_rag_8m_parity::mpnet::MpnetEmbedder;
use safetensors::SafeTensors;
use serde::Deserialize;

#[derive(Deserialize)]
struct Metadata {
    revision: String,
    normalize: bool,
    texts: Vec<String>,
}

#[test]
fn unnormalized_mpnet_matches_pinned_onnx_fixture() {
    let fixture_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures");
    let metadata: Metadata =
        serde_json::from_slice(&std::fs::read(fixture_root.join("mpnet-parity.json")).unwrap())
            .unwrap();
    assert_eq!(metadata.revision, MPNET_REVISION);
    assert!(!metadata.normalize);
    let bytes = std::fs::read(fixture_root.join("mpnet-parity.safetensors")).unwrap();
    let tensors = SafeTensors::deserialize(&bytes).unwrap();
    let view = tensors.tensor("embeddings").unwrap();
    let expected: &[f32] = bytemuck::cast_slice(view.data());
    let asset_root = std::env::var_os("GFM_MPNET_ASSET_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\mpnet"));
    let mut embedder = MpnetEmbedder::open(
        asset_root.join("onnx").join("model.onnx"),
        asset_root.join("tokenizer.json"),
    )
    .unwrap();
    let texts = metadata
        .texts
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>();
    let actual_rows = embedder.embed_unnormalized_batch(&texts).unwrap();
    let chunked_rows = embedder.embed_unnormalized_chunked(&texts, 2).unwrap();
    assert_eq!(actual_rows.len(), chunked_rows.len());
    for (row, actual) in actual_rows.iter().enumerate() {
        let expected = &expected[row * 768..(row + 1) * 768];
        let error = actual
            .iter()
            .zip(expected)
            .map(|(left, right)| (left - right).abs())
            .fold(0_f32, f32::max);
        let norm = actual.iter().map(|value| value * value).sum::<f32>().sqrt();
        assert!(error <= 2e-5, "MPNet row {row} max abs error {error}");
        assert!(
            (norm - 1.0).abs() > 1e-3,
            "embedding was unexpectedly normalized"
        );
        let chunk_error = actual
            .iter()
            .zip(&chunked_rows[row])
            .map(|(left, right)| (left - right).abs())
            .fold(0_f32, f32::max);
        assert!(
            chunk_error <= 2e-5,
            "MPNet chunked row {row} max abs error {chunk_error}"
        );
        eprintln!("MPNET row={row} max_abs={error:.9} l2_norm={norm:.6}");
    }
}
