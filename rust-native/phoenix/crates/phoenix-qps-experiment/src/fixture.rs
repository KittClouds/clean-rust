#[derive(Clone, Debug)]
pub struct FixtureDocument {
    pub external_id: u64,
    pub title: String,
    pub body: String,
}

impl FixtureDocument {
    pub fn flattened(&self) -> String {
        format!("{} {}", self.title, self.body)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct JudgedQuery {
    pub text: &'static str,
    pub relevant_external_id: u64,
}

/// Small, adversarial qrels for the behavior under test. These are not a
/// claim of broad retrieval superiority; they isolate phrase, order, field,
/// and sentence concentration from raw term frequency.
pub fn judged_fixture() -> (Vec<FixtureDocument>, Vec<JudgedQuery>) {
    let documents = vec![
        FixtureDocument {
            external_id: 101,
            title: "red dragon armor".into(),
            body: "The artisan repaired the ceremonial plate before dawn.".into(),
        },
        FixtureDocument {
            external_id: 102,
            title: "inventory fragments".into(),
            body: scattered("red", "dragon", "armor"),
        },
        FixtureDocument {
            external_id: 201,
            title: "memory correction policy".into(),
            body: "Corrections retain old evidence and publish supersession.".into(),
        },
        FixtureDocument {
            external_id: 202,
            title: "policy notebook".into(),
            body: scattered("memory", "correction", "policy"),
        },
        FixtureDocument {
            external_id: 301,
            title: "camera controls".into(),
            body: "The graph rotates around its central axis without orbit drift.".into(),
        },
        FixtureDocument {
            external_id: 302,
            title: "camera axis notes".into(),
            body:
                "axis axis axis. unrelated filler. rotates later around many scattered words graph."
                    .into(),
        },
        FixtureDocument {
            external_id: 401,
            title: "release proof".into(),
            body: "A cold restart reopens the verified generation exactly.".into(),
        },
        FixtureDocument {
            external_id: 402,
            title: "restart log".into(),
            body: scattered("cold", "restart", "generation"),
        },
        FixtureDocument {
            external_id: 501,
            title: "temporal account".into(),
            body: "Alpha beta gamma occurred in that exact order.".into(),
        },
        FixtureDocument {
            external_id: 502,
            title: "alphabet archive".into(),
            body: "gamma repeated gamma. beta repeated beta. alpha repeated alpha.".into(),
        },
        FixtureDocument {
            external_id: 900,
            title: "unrelated background".into(),
            body: "Phoenix stores immutable packed graph generations for native retrieval.".into(),
        },
    ];
    let queries = vec![
        JudgedQuery {
            text: "red dragon armor",
            relevant_external_id: 101,
        },
        JudgedQuery {
            text: "memory correction policy",
            relevant_external_id: 201,
        },
        JudgedQuery {
            text: "graph rotates central axis",
            relevant_external_id: 301,
        },
        JudgedQuery {
            text: "cold restart generation",
            relevant_external_id: 401,
        },
        JudgedQuery {
            text: "alpha beta gamma",
            relevant_external_id: 501,
        },
    ];
    (documents, queries)
}

/// Ordinary product-search qrels. These deliberately use natural Phoenix
/// concepts and include one realistic ambiguity where an exact topical title
/// should beat a body that merely repeats the words far apart.
pub fn representative_fixture() -> (Vec<FixtureDocument>, Vec<JudgedQuery>) {
    let documents = vec![
        FixtureDocument {
            external_id: 1_001,
            title: "memory graph retrieval".into(),
            body: "Phoenix retrieves evidence from an immutable memory graph generation.".into(),
        },
        FixtureDocument {
            external_id: 1_002,
            title: "renderer memory budget".into(),
            body: "The graph renderer tracks memory while retrieval runs elsewhere.".into(),
        },
        FixtureDocument {
            external_id: 1_101,
            title: "document revision history".into(),
            body: "Each saved note revision keeps its source hash and durable receipt.".into(),
        },
        FixtureDocument {
            external_id: 1_102,
            title: "workspace revision counter".into(),
            body: "Document edits increment a counter while history remains available.".into(),
        },
        FixtureDocument {
            external_id: 1_201,
            title: "gpu buffer reuse".into(),
            body: "Prepared graph buffers update in place across manifold switches.".into(),
        },
        FixtureDocument {
            external_id: 1_202,
            title: "gpu device recovery".into(),
            body: "A lost surface is recreated without discarding resident graph authority.".into(),
        },
        FixtureDocument {
            external_id: 1_301,
            title: "candidate review workflow".into(),
            body: "A reviewer accepts or rejects evidence-bound semantic candidates.".into(),
        },
        FixtureDocument {
            external_id: 1_302,
            title: "workflow activity report".into(),
            body: "candidate candidate candidate appears here. review appears later. workflow closes the report."
                .into(),
        },
        FixtureDocument {
            external_id: 1_401,
            title: "conversation turn recall".into(),
            body: "Recall reads committed history before the pending assistant turn is ingested."
                .into(),
        },
        FixtureDocument {
            external_id: 1_402,
            title: "conversation import".into(),
            body: "Imported turns retain speaker roles, timestamps, and reply relationships.".into(),
        },
        FixtureDocument {
            external_id: 1_501,
            title: "dynamic chunk boundaries".into(),
            body: "The compiler consumes exact chunk records instead of rebuilding paragraphs."
                .into(),
        },
        FixtureDocument {
            external_id: 1_502,
            title: "paragraph display".into(),
            body: "The editor lays out paragraphs independently from retrieval chunk boundaries."
                .into(),
        },
    ];
    let queries = vec![
        JudgedQuery {
            text: "memory graph retrieval",
            relevant_external_id: 1_001,
        },
        JudgedQuery {
            text: "document revision history",
            relevant_external_id: 1_101,
        },
        JudgedQuery {
            text: "gpu buffer reuse",
            relevant_external_id: 1_201,
        },
        JudgedQuery {
            text: "candidate review workflow",
            relevant_external_id: 1_301,
        },
        JudgedQuery {
            text: "conversation turn recall",
            relevant_external_id: 1_401,
        },
        JudgedQuery {
            text: "dynamic chunk boundaries",
            relevant_external_id: 1_501,
        },
    ];
    (documents, queries)
}

fn scattered(first: &str, second: &str, third: &str) -> String {
    format!(
        "{first} {first} {first} appears in one sentence with padding padding padding. \
         {second} {second} {second} appears much later among unrelated inventory words. \
         {third} {third} {third} closes a separate final sentence."
    )
}

pub fn benchmark_corpus(document_count: usize) -> Vec<String> {
    let vocabulary = (0..512)
        .map(|index| format!("term{index}"))
        .collect::<Vec<_>>();
    (0..document_count)
        .map(|document| {
            let mut state = (document as u64 + 1).wrapping_mul(0x9E37_79B9_7F4A_7C15);
            let mut text = String::with_capacity(768);
            for token in 0..96 {
                state ^= state >> 12;
                state ^= state << 25;
                state ^= state >> 27;
                let word = &vocabulary[(state as usize) & (vocabulary.len() - 1)];
                text.push_str(word);
                text.push(if token % 24 == 23 { '.' } else { ' ' });
            }
            if document % 97 == 0 {
                text.push_str(" graph memory retrieval.");
            }
            text
        })
        .collect()
}

/// Corpus-size sensitivity fixture with a posting set that stays fixed while
/// unrelated documents are added.
pub fn fixed_match_corpus(document_count: usize, matching_documents: usize) -> Vec<String> {
    benchmark_corpus(document_count)
        .into_iter()
        .enumerate()
        .map(|(document, mut text)| {
            if document < matching_documents.min(document_count) {
                text.push_str(" needle cobalt anchor.");
            }
            text
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::{benchmark_corpus, fixed_match_corpus};

    #[test]
    fn benchmark_corpus_is_deterministic() {
        assert_eq!(benchmark_corpus(8), benchmark_corpus(8));
    }

    #[test]
    fn fixed_match_posting_set_does_not_grow_with_corpus() {
        assert_eq!(
            fixed_match_corpus(8, 2)
                .iter()
                .filter(|text| text.contains("needle cobalt anchor"))
                .count(),
            2
        );
        assert_eq!(
            fixed_match_corpus(64, 2)
                .iter()
                .filter(|text| text.contains("needle cobalt anchor"))
                .count(),
            2
        );
    }
}
