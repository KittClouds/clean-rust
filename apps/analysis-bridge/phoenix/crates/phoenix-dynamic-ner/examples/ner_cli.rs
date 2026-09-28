use phoenix_dynamic_ner::{
    DynamicNerModel, DynamicSchemaBuilder, LabelPack, LocalMentionId, MentionVote, ModelNerWindow,
    NerModelError, PhoenixNerEngineBuilder, SurfaceNerInput, SurfaceRouter,
};
use phoenix_rel_post::{GlinerBiModel, GlinerBiPredictOptions};
use phoenix_types::{ScopeKey, SentenceSpan, TextRange, TokenSpan};
use std::env;
use std::path::Path;

struct CliGlinerModel {
    gliner: GlinerBiModel,
}

impl DynamicNerModel for CliGlinerModel {
    fn discover(
        &self,
        window: &ModelNerWindow<'_>,
        label_pack: &LabelPack,
    ) -> Result<Vec<phoenix_dynamic_ner::DiscoveredSpan>, NerModelError> {
        println!(
            "*** [CLI Model] discover called! Text: {:?}, Labels: {:?}",
            window.text, label_pack.labels
        );
        let labels: Vec<String> = vec!["Person".into(), "Organization".into(), "Location".into()];
        let predictions = self
            .gliner
            .predict_with_options(
                window.text,
                &labels,
                &GlinerBiPredictOptions {
                    threshold: 0.01,
                    ..Default::default()
                },
            )
            .map_err(|e| NerModelError::Inference(e.to_string()))?;

        println!(
            "GLiNER found {} predictions: {:?}",
            predictions.len(),
            predictions
        );

        let mut spans = Vec::new();
        for p in predictions {
            let label_str = if p.label == "Person" {
                "Character"
            } else {
                &p.label
            };
            spans.push(phoenix_dynamic_ner::DiscoveredSpan {
                window_relative_range: phoenix_types::TextRange {
                    start: p.span_start as u32,
                    end: p.span_end as u32,
                },
                surface: compact_str::CompactString::new(&p.text),
                label: phoenix_dynamic_ner::EntityLabel::new(label_str),
                confidence: p.score,
            });
        }

        Ok(spans)
    }

    fn verify(
        &self,
        _cases: &[phoenix_dynamic_ner::VerificationCase],
    ) -> Result<Vec<(LocalMentionId, MentionVote)>, NerModelError> {
        Ok(Vec::new())
    }
}

fn naive_tokenize(text: &str) -> (Vec<TokenSpan>, Vec<SentenceSpan>) {
    let mut tokens = Vec::new();
    let mut sentences = Vec::new();

    let mut sent_start = 0;
    let mut token_start = 0;
    let mut in_token = false;

    for (i, c) in text.char_indices() {
        if c.is_whitespace() || c.is_ascii_punctuation() {
            if in_token {
                tokens.push(TokenSpan {
                    range: TextRange {
                        start: token_start as u32,
                        end: i as u32,
                    },
                    capitalized: text[token_start..].starts_with(|ch: char| ch.is_uppercase()),
                    pos: None,
                    token_class: Some(phoenix_types::TokenClass::Word),
                    masked: false,
                });
                in_token = false;
            }
            if c == '.' || c == '!' || c == '?' {
                sentences.push(SentenceSpan {
                    index: sentences.len(),
                    range: TextRange {
                        start: sent_start as u32,
                        end: (i + c.len_utf8()) as u32,
                    },
                });
                sent_start = i + c.len_utf8();
            }
        } else if !in_token {
            token_start = i;
            in_token = true;
        }
    }

    if in_token {
        tokens.push(TokenSpan {
            range: TextRange {
                start: token_start as u32,
                end: text.len() as u32,
            },
            capitalized: text[token_start..].starts_with(|ch: char| ch.is_uppercase()),
            pos: None,
            token_class: Some(phoenix_types::TokenClass::Word),
            masked: false,
        });
    }
    if sent_start < text.len() {
        sentences.push(SentenceSpan {
            index: sentences.len(),
            range: TextRange {
                start: sent_start as u32,
                end: text.len() as u32,
            },
        });
    }

    (tokens, sentences)
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: cargo run --example ner_cli -- <text_to_analyze>");
        std::process::exit(1);
    }
    let text = &args[1];

    let model_dir = Path::new("..")
        .join("..")
        .join("..")
        .join("..")
        .join("gliner-bi-onnx");
    println!("Loading GLiNER model from {}...", model_dir.display());

    let gliner = GlinerBiModel::load(&model_dir)?;
    let model = CliGlinerModel { gliner };

    let engine = PhoenixNerEngineBuilder::new()
        .router(SurfaceRouter::default())
        .schema(DynamicSchemaBuilder::default())
        .model(Box::new(model))
        .build();

    println!("\nText: {}", text);
    let (tokens, sentences) = naive_tokenize(text);

    let input = SurfaceNerInput {
        document_id: "doc_test",
        text,
        tokens: &tokens,
        sentences: &sentences,
        scope: &ScopeKey::default(),
        lexicon: None, // No known lexicon for this simple test
        surface_hits: &[],
        label_bank_context: None,
    };

    println!("Running NER pipeline...");
    let result = engine.extract_mentions(&input)?;

    println!("\n--- ROUTES ---");
    let router = SurfaceRouter::default();
    let native = phoenix_dynamic_ner::NativeDiscoveryLane::discover(
        input.text,
        input.tokens,
        input.sentences,
        &[],
        0,
    );
    let needs = router.build_need_vectors(
        input.text,
        input.sentences,
        &[],
        &native,
        input.surface_hits,
    );
    for (i, need) in needs.iter().enumerate() {
        println!("Sentence {}: {:?}", i, need);
    }
    let schema_builder = phoenix_dynamic_ner::DynamicSchemaBuilder::default();
    let routes = router.plan_routes(
        input.text,
        input.sentences,
        &needs,
        &schema_builder,
        &[],
        &native,
        None,
        None,
    );
    for route in routes {
        println!("Route: {:?}", route);
    }

    println!("\n--- MENTIONS ---");
    for mention in result.mentions {
        println!(
            "[{}] '{}' (conf: {:.2}, status: {:?})",
            mention.mention_kind.as_str_approx(),
            mention.surface,
            mention.confidence,
            mention.status
        );
        for vote in mention.source_votes {
            println!(
                "   <- {:?} (conf: {:.2}, reason: {:?})",
                vote.source, vote.confidence, vote.reason
            );
        }
    }

    println!("\n--- GRAPH ---");
    for edge in result.mention_graph.edges {
        println!(
            "Edge: {:?} <-> {:?} via {:?}",
            edge.left, edge.right, edge.kind
        );
    }

    if !result.diagnostics.is_empty() {
        println!("\n--- DIAGNOSTICS ---");
        for d in result.diagnostics {
            println!("[{}] {}", d.code, d.message);
        }
    }

    Ok(())
}

trait MentionKindExt {
    fn as_str_approx(&self) -> &str;
}
impl MentionKindExt for phoenix_dynamic_ner::MentionKind {
    fn as_str_approx(&self) -> &str {
        match self {
            phoenix_dynamic_ner::MentionKind::Named => "Named",
            phoenix_dynamic_ner::MentionKind::Nominal => "Nominal",
            phoenix_dynamic_ner::MentionKind::Pronoun => "Pronoun",
        }
    }
}
