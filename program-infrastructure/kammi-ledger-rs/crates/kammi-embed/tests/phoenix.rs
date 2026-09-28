//! Real-model tests. They skip (pass with a note) when the model directory is absent.

use kammi_core::{Embedder, Input};
use kammi_embed::{ensure_ort_dylib, Family, PhoenixEmbedder};
use phoenix_embed::OrtTextEmbedder;

fn cosine(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b).map(|(x, y)| x * y).sum::<f32>()
        / (a.iter().map(|x| x * x).sum::<f32>().sqrt()
            * b.iter().map(|x| x * x).sum::<f32>().sqrt())
}

fn check(family: Family) {
    let root = family.default_model_root();
    if !root.is_dir() || ensure_ort_dylib().is_none() {
        eprintln!("skipping {}: model or ONNX Runtime missing", family.label());
        return;
    }
    let embedder = PhoenixEmbedder::load(family, &root).expect("load");
    assert!(embedder
        .model_identity()
        .id
        .starts_with(&format!("phoenix-embed:{}:", family.label())));
    let again = PhoenixEmbedder::load(family, &root).expect("reload");
    assert_eq!(
        embedder.model_identity(),
        again.model_identity(),
        "identity is stable across loads"
    );

    let docs = [
        "Mars is known as the Red Planet because of iron oxide dust.",
        "The ledger commits events to an append-only journal.",
    ];
    let query = "Which planet is called the red planet?";
    let dv: Vec<Vec<f32>> = embedder
        .embed(&[Input::document(docs[0]), Input::document(docs[1])])
        .unwrap()
        .iter()
        .map(<[f32]>::to_vec)
        .collect();
    let qv = [embedder.embed_one(Input::query(query)).unwrap()];
    assert_eq!(qv[0].len(), embedder.dimension());
    assert_eq!(dv.len(), 2);
    assert_eq!(dv[0].len(), qv[0].len());
    let (relevant, other) = (cosine(&qv[0], &dv[0]), cosine(&qv[0], &dv[1]));
    eprintln!(
        "{}: dims={} relevant={relevant:.4} other={other:.4}",
        family.label(),
        qv[0].len()
    );
    assert!(relevant > other, "query ranks the relevant document first");

    // Single-session prefixing must equal the Phoenix runner's own query/document configs.
    let phoenix_query = match family {
        Family::Gemma300 => phoenix_embed::OrtTextEmbedConfig::embedding_gemma_query(root.clone()),
        Family::JinaV5 => phoenix_embed::OrtTextEmbedConfig::jina_v5_retrieval_query(root.clone()),
        Family::Mdbr => phoenix_embed::OrtTextEmbedConfig::mdbr_leaf_mt_query(root.clone()),
    };
    let reference = OrtTextEmbedder::load(&phoenix_query)
        .unwrap()
        .embed_texts(&[query])
        .unwrap();
    let parity = cosine(&reference[0], &qv[0]);
    assert!(
        parity > 0.99999,
        "query parity with Phoenix config: {parity}"
    );
    let phoenix_doc = OrtTextEmbedder::load(&family.config(root.clone()))
        .unwrap()
        .embed_texts(&docs[..1])
        .unwrap();
    let parity = cosine(&phoenix_doc[0], &dv[0]);
    assert!(
        parity > 0.99999,
        "document parity with Phoenix config: {parity}"
    );
}

#[test]
fn gemma300_embeds_and_matches_phoenix_configs() {
    check(Family::Gemma300);
}

#[test]
fn jina_v5_embeds_and_matches_phoenix_configs() {
    check(Family::JinaV5);
}
