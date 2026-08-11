use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use anyhow::{bail, Context, Result};
use serde::Deserialize;

#[derive(Deserialize)]
pub struct BundleFile {
    pub contract: String,
    pub source_packet: BoundFile,
    pub phase_5: BoundFile,
    pub selected_bundles: usize,
    pub bundles: Vec<Bundle>,
}

#[derive(Clone, Deserialize, serde::Serialize)]
pub struct BoundFile {
    pub path: String,
    pub bytes: u64,
    pub sha256: String,
}

#[derive(Deserialize)]
pub struct Bundle {
    pub dataset: String,
    pub query_id: String,
    pub query: String,
    pub positive: Candidate,
    pub challengers: Vec<Challenger>,
}

#[derive(Clone, Deserialize)]
pub struct Candidate {
    pub id: String,
    #[serde(default)]
    pub title: String,
    pub text: String,
}

#[derive(Deserialize)]
pub struct Challenger {
    pub negative: Candidate,
}

pub struct FrozenInput {
    pub source_contract: String,
    pub source_packet: BoundFile,
    pub phase_5: BoundFile,
    pub corpus: Vec<CorpusItem>,
    pub queries: Vec<QueryItem>,
    pub dataset_counts: BTreeMap<String, usize>,
    pub bundle_hash: [u8; 32],
}

pub struct CorpusItem {
    pub stable_id: String,
    pub text: String,
}

pub struct QueryItem {
    pub stable_id: String,
    pub dataset: String,
    pub text: String,
}

pub fn load(path: &Path) -> Result<FrozenInput> {
    let bytes = fs::read(path).with_context(|| format!("read {}", path.display()))?;
    let bundle_hash = *blake3::hash(&bytes).as_bytes();
    let parsed: BundleFile =
        serde_json::from_slice(&bytes).with_context(|| format!("decode {}", path.display()))?;
    if parsed.selected_bundles != parsed.bundles.len() || parsed.bundles.is_empty() {
        bail!("bundle count does not match selected_bundles");
    }

    let mut corpus = BTreeMap::<String, String>::new();
    let mut queries = Vec::with_capacity(parsed.bundles.len());
    let mut dataset_counts = BTreeMap::new();
    for bundle in parsed.bundles {
        if bundle.query.trim().is_empty() || bundle.query_id.trim().is_empty() {
            bail!("empty query or query identity");
        }
        *dataset_counts.entry(bundle.dataset.clone()).or_insert(0) += 1;
        queries.push(QueryItem {
            stable_id: bundle.query_id,
            dataset: bundle.dataset,
            text: bundle.query,
        });
        insert_candidate(&mut corpus, bundle.positive)?;
        for challenger in bundle.challengers {
            insert_candidate(&mut corpus, challenger.negative)?;
        }
    }
    let corpus = corpus
        .into_iter()
        .map(|(stable_id, text)| CorpusItem { stable_id, text })
        .collect();
    Ok(FrozenInput {
        source_contract: parsed.contract,
        source_packet: parsed.source_packet,
        phase_5: parsed.phase_5,
        corpus,
        queries,
        dataset_counts,
        bundle_hash,
    })
}

fn insert_candidate(corpus: &mut BTreeMap<String, String>, candidate: Candidate) -> Result<()> {
    if candidate.id.trim().is_empty() || candidate.text.trim().is_empty() {
        bail!("candidate has empty id or text");
    }
    let text = if candidate.title.trim().is_empty() {
        candidate.text
    } else {
        format!("{}\n{}", candidate.title, candidate.text)
    };
    if let Some(existing) = corpus.get(&candidate.id) {
        if existing != &text {
            bail!(
                "candidate identity maps to multiple texts: {}",
                candidate.id
            );
        }
    } else {
        corpus.insert(candidate.id, text);
    }
    Ok(())
}
