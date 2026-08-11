use super::*;

#[test]
fn profiles_parse_expected_labels() {
    assert_eq!(
        TextEmbeddingProfile::parse("256-truncated"),
        Some(TextEmbeddingProfile::Truncate256)
    );
    assert_eq!(
        TextEmbeddingProfile::parse("384"),
        Some(TextEmbeddingProfile::Native384)
    );
    assert_eq!(
        TextEmbeddingProfile::parse("768"),
        Some(TextEmbeddingProfile::Native768)
    );
    assert_eq!(
        TextEmbeddingProfile::parse("786"),
        Some(TextEmbeddingProfile::Native768)
    );
    assert_eq!(
        TextEmbeddingProfile::parse("1024"),
        Some(TextEmbeddingProfile::Native1024)
    );
}

#[test]
fn truncate_profile_projects_first_256_dims() {
    let values = (0..384).map(|value| value as f32 + 1.0).collect::<Vec<_>>();
    let projected = TextEmbeddingProfile::Truncate256
        .project(&values)
        .expect("truncate profile");
    assert_eq!(projected.len(), 256);
}

#[test]
fn native_profile_rejects_wrong_dimension() {
    let error = TextEmbeddingProfile::Native384
        .project(&vec![1.0; 256])
        .expect_err("dimension mismatch");
    assert!(matches!(
        error,
        OrtTextEmbedError::EmbeddingDimension {
            expected: 384,
            actual: 256,
            ..
        }
    ));
}

#[test]
fn last_token_pooling_uses_final_non_padding_token() {
    assert_eq!(last_non_padding_index(&[1, 1, 1, 0, 0]), 2);
    assert_eq!(last_non_padding_index(&[0, 0, 0]), 0);
}

#[test]
fn length_bucket_order_is_stable_for_equal_lengths() {
    let texts = ["four", "a", "also", "bb"];
    assert_eq!(length_bucket_order(&texts), vec![1, 3, 0, 2]);
}

#[test]
fn telemetry_reports_padding_amplification() {
    let mut telemetry = EmbeddingRunTelemetry::default();
    telemetry.include(BatchTelemetry {
        useful_tokens: 10,
        padded_tokens: 16,
        useful_attention_cells: 58,
        padded_attention_cells: 128,
        max_sequence_tokens: 8,
    });
    assert_eq!(telemetry.batches, 1);
    assert_eq!(telemetry.max_sequence_tokens, 8);
    assert!((telemetry.token_padding_ratio() - 1.6).abs() < f64::EPSILON);
    assert!((telemetry.attention_padding_ratio() - 128.0 / 58.0).abs() < f64::EPSILON);
}
