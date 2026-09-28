use std::env;
use std::path::PathBuf;
use std::time::Instant;

use phoenix_embed::{
    default_ort_dylib_path, workspace_root, EmbeddingBatchOrder, OrtExecutionProviderPreference,
    OrtTextEmbedConfig, OrtTextEmbedder, TextEmbeddingInputPrefix, TextEmbeddingPooling,
    TextEmbeddingProfile,
};

const DEFAULT_MODEL_ROOT: &str = "G:\\phoenix-models\\jina-embeddings-v5-text-nano-retrieval";

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    if env::var_os("ORT_DYLIB_PATH").is_none() {
        if let Some(path) = default_ort_dylib_path(&workspace_root()) {
            unsafe { env::set_var("ORT_DYLIB_PATH", &path) };
        }
    }

    let config = OrtTextEmbedConfig {
        model_root: args.model_root,
        batch_size: args.texts.len(),
        max_length: 1024,
        profile: TextEmbeddingProfile::Native768,
        prefix_passage: false,
        pooling: TextEmbeddingPooling::LastToken,
        input_prefix: TextEmbeddingInputPrefix::None,
        batch_order: EmbeddingBatchOrder::LengthBucketed,
        execution_provider: OrtExecutionProviderPreference::from_env(),
    };

    let load_started = Instant::now();
    let embedder = OrtTextEmbedder::load(&config)?;
    let load_ms = load_started.elapsed().as_millis();

    let embed_started = Instant::now();
    let embeddings = embedder.embed_texts(&args.texts)?;
    let embed_ms = embed_started.elapsed().as_millis();

    let query = &embeddings[0];
    println!("model_root={}", config.model_root.display());
    println!("profile={} dim={}", embedder.profile().label(), query.len());
    println!("load_ms={load_ms} embed_ms={embed_ms}");
    println!("query_norm={:.6}", l2_norm(query));
    for (index, embedding) in embeddings.iter().enumerate().skip(1) {
        println!(
            "doc#{index} cosine={:.6} norm={:.6} text={}",
            cosine(query, embedding),
            l2_norm(embedding),
            args.texts[index]
        );
    }
    Ok(())
}

struct Args {
    model_root: PathBuf,
    texts: Vec<String>,
}

impl Args {
    fn parse() -> Self {
        let mut model_root = PathBuf::from(DEFAULT_MODEL_ROOT);
        let mut query =
            "Query: how does the refuge tear open and threaten the characters?".to_owned();
        let mut docs = Vec::new();
        let mut iter = env::args().skip(1);
        while let Some(arg) = iter.next() {
            match arg.as_str() {
                "--model-root" => {
                    if let Some(value) = iter.next() {
                        model_root = PathBuf::from(value);
                    }
                }
                "--query" => {
                    if let Some(value) = iter.next() {
                        query = format_jina_text("Query: ", &value);
                    }
                }
                "--doc" => {
                    if let Some(value) = iter.next() {
                        docs.push(format_jina_text("Document: ", &value));
                    }
                }
                "--help" | "-h" => {
                    print_help();
                    std::process::exit(0);
                }
                _ => {}
            }
        }
        if docs.is_empty() {
            docs.extend(
                [
                    "Document: The refuge tore open while the room lost its certainty.",
                    "Document: Kai and Aella braced as the hidden structure began to fail.",
                    "Document: A recipe note describes lemon bread and quiet kitchen work.",
                ]
                .into_iter()
                .map(str::to_owned),
            );
        }
        let mut texts = Vec::with_capacity(docs.len() + 1);
        texts.push(query);
        texts.extend(docs);
        Self { model_root, texts }
    }
}

fn format_jina_text(prefix: &str, value: &str) -> String {
    let trimmed = value.trim();
    if trimmed.starts_with(prefix) {
        trimmed.to_owned()
    } else {
        format!("{prefix}{trimmed}")
    }
}

fn cosine(left: &[f32], right: &[f32]) -> f32 {
    left.iter().zip(right.iter()).map(|(a, b)| a * b).sum()
}

fn l2_norm(values: &[f32]) -> f32 {
    values.iter().map(|value| value * value).sum::<f32>().sqrt()
}

fn print_help() {
    println!(
        "phoenix-jina-embed-smoke --model-root <dir> --query <text> --doc <text> [--doc <text>...]"
    );
}
