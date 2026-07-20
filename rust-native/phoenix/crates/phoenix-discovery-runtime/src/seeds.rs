use bm25_turbo::persistence::{self, MmapBM25Index};
use hashbrown::HashMap;
use phoenix_discovery_query::{
    BoundedSeedSink, DiscoveryQueryError, PreparedSeedResolver, SeedChannel, SeedChannelReceipt,
    SeedHit,
};
use phoenix_discovery_view::AssertedDiscoveryView;
use phoenix_store_native_core::{
    PhoenixLexicalQueryStore, PhoenixSemanticIndexStore, ScopeLexicalQuerySidecar,
    SemanticIndexAuthorityReceipt,
};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::ScopeKey;
use std::cmp::Ordering;
use std::fs::File;
use std::io::Read;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ProductionSeedLimits {
    pub query_bytes: u32,
    pub lexical_postings: u32,
    pub vector_oversample: u16,
}

impl Default for ProductionSeedLimits {
    fn default() -> Self {
        Self {
            query_bytes: 16_384,
            lexical_postings: 16_384,
            vector_oversample: 64,
        }
    }
}

pub struct ProductionSeedAdapter<'a> {
    store: &'a PhoenixOvergraphStore,
    discovery: &'a AssertedDiscoveryView,
    scope: ScopeKey,
    generation: u64,
    discovery_digest: String,
    lexical: MmapBM25Index,
    lexical_dense: Vec<Option<u32>>,
    lexical_digest: String,
    vector_authority: SemanticIndexAuthorityReceipt,
    limits: ProductionSeedLimits,
}

impl<'a> ProductionSeedAdapter<'a> {
    pub fn prepare(
        store: &'a PhoenixOvergraphStore,
        scope: ScopeKey,
        discovery: &'a AssertedDiscoveryView,
        model_version: &str,
        limits: ProductionSeedLimits,
    ) -> Result<Self, DiscoveryQueryError> {
        if limits.query_bytes == 0 || limits.lexical_postings == 0 || limits.vector_oversample == 0
        {
            return Err(DiscoveryQueryError::Invalid(
                "production seed limits must be non-zero".to_owned(),
            ));
        }
        let sidecar = store
            .load_scope_lexical_query_sidecar(&scope)
            .map_err(resolver_error)?
            .ok_or_else(|| DiscoveryQueryError::Resolver("lexical sidecar is missing".into()))?;
        if sidecar.generation != discovery.manifest().generation {
            return Err(DiscoveryQueryError::Invalid(
                "lexical generation does not match asserted discovery generation".to_owned(),
            ));
        }
        let lexical = persistence::load_mmap(&sidecar.index_path).map_err(resolver_error)?;
        if lexical.num_docs as usize != sidecar.docs.len() {
            return Err(DiscoveryQueryError::Invalid(
                "lexical index rows do not match its identity sidecar".to_owned(),
            ));
        }
        let lexical_dense = sidecar
            .docs
            .iter()
            .map(|doc| {
                discovery
                    .node_dense_for_external_id(&doc.node_id)
                    .map_err(resolver_error)
            })
            .collect::<Result<Vec<_>, _>>()?;
        let lexical_digest = lexical_digest(&sidecar)?;
        let vector_authority = store
            .semantic_leaf_index_authority_for_model(
                store.semantic_model_id(),
                model_version,
                store.semantic_vector_dim(),
                &scope,
            )
            .map_err(resolver_error)?
            .ok_or_else(|| DiscoveryQueryError::Resolver("semantic ANN index is missing".into()))?;
        Ok(Self {
            store,
            discovery,
            scope,
            generation: discovery.manifest().generation,
            discovery_digest: discovery.manifest().artifact_digest.clone(),
            lexical,
            lexical_dense,
            lexical_digest,
            vector_authority,
            limits,
        })
    }

    fn lexical_hits(
        &self,
        query: &str,
        cap: usize,
    ) -> Result<(Vec<SeedHit>, u32, bool), DiscoveryQueryError> {
        if query.len() > self.limits.query_bytes as usize {
            return Err(DiscoveryQueryError::Invalid(
                "discovery query exceeds the production byte limit".to_owned(),
            ));
        }
        bounded_lexical_hits(
            &self.lexical,
            &self.lexical_dense,
            query,
            self.limits.lexical_postings,
            cap,
        )
    }

    fn vector_hits(
        &self,
        vector: Option<&[f32]>,
        cap: usize,
    ) -> Result<(Vec<SeedHit>, u32, bool), DiscoveryQueryError> {
        let Some(vector) = vector else {
            return Ok((Vec::new(), 0, false));
        };
        let oversample = usize::from(self.limits.vector_oversample).max(cap);
        let neighbors = self
            .store
            .query_semantic_neighbors(vector, &self.scope, cap, oversample)
            .map_err(resolver_error)?;
        let maximum = neighbors
            .iter()
            .map(|neighbor| distance_similarity(neighbor.distance))
            .fold(0.0_f64, f64::max)
            .max(f64::EPSILON);
        let examined = neighbors.len() as u32;
        let mut hits = Vec::with_capacity(neighbors.len().min(cap));
        for neighbor in neighbors.into_iter().take(cap) {
            let Some(node) = self
                .discovery
                .node_dense_for_external_id(&neighbor.span_id)
                .map_err(resolver_error)?
            else {
                continue;
            };
            let raw = distance_similarity(neighbor.distance);
            hits.push(SeedHit {
                node,
                raw_score_micros: quantize_raw(raw),
                score_micros: normalize(raw, maximum),
            });
        }
        Ok((hits, examined, examined as usize > cap))
    }
}

fn bounded_lexical_hits(
    lexical: &MmapBM25Index,
    lexical_dense: &[Option<u32>],
    query: &str,
    posting_budget: u32,
    cap: usize,
) -> Result<(Vec<SeedHit>, u32, bool), DiscoveryQueryError> {
    let tokens = lexical.tokenizer.tokenize(query);
    let token_ids = tokens
        .iter()
        .filter_map(|token| lexical.vocab.get(token).copied())
        .collect::<Vec<_>>();
    let mut columns = token_ids
        .into_iter()
        .map(|token| {
            let (weights, docs) = lexical.column(token);
            (weights, docs, 0_usize)
        })
        .filter(|(_, docs, _)| !docs.is_empty())
        .collect::<Vec<_>>();
    let mut scores = HashMap::<u32, f64>::with_capacity(cap.saturating_mul(8));
    let mut examined = 0_u32;
    while examined < posting_budget {
        let mut advanced = false;
        for (weights, docs, cursor) in &mut columns {
            if examined >= posting_budget {
                break;
            }
            let Some((&weight, &doc)) = weights.get(*cursor).zip(docs.get(*cursor)) else {
                continue;
            };
            *cursor += 1;
            examined += 1;
            advanced = true;
            if lexical_dense.get(doc as usize).is_some_and(Option::is_some) {
                *scores.entry(doc).or_default() += f64::from(weight);
            }
        }
        if !advanced {
            break;
        }
    }
    let mut truncated = columns.iter().any(|(_, docs, cursor)| *cursor < docs.len());
    let mut ranked = scores.into_iter().collect::<Vec<_>>();
    ranked.sort_unstable_by(|left, right| {
        right
            .1
            .partial_cmp(&left.1)
            .unwrap_or(Ordering::Equal)
            .then_with(|| left.0.cmp(&right.0))
    });
    truncated |= ranked.len() > cap;
    ranked.truncate(cap);
    let maximum = ranked.first().map(|(_, score)| *score).unwrap_or(1.0);
    let hits = ranked
        .into_iter()
        .filter_map(|(doc, raw)| {
            let node = lexical_dense.get(doc as usize).copied().flatten()?;
            Some(SeedHit {
                node,
                raw_score_micros: quantize_raw(raw),
                score_micros: normalize(raw, maximum),
            })
        })
        .collect();
    Ok((hits, examined, truncated))
}

impl PreparedSeedResolver for ProductionSeedAdapter<'_> {
    fn generation(&self) -> u64 {
        self.generation
    }

    fn discovery_digest(&self) -> &str {
        &self.discovery_digest
    }

    fn resolve_lexical(
        &self,
        query: &str,
        sink: &mut BoundedSeedSink<'_>,
    ) -> Result<SeedChannelReceipt, DiscoveryQueryError> {
        let cap = sink.remaining();
        let (hits, examined, truncated) = self.lexical_hits(query, cap)?;
        for hit in hits {
            sink.push(hit);
        }
        Ok(SeedChannelReceipt {
            channel: SeedChannel::Lexical,
            index_generation: self.generation,
            index_digest: self.lexical_digest.clone(),
            source_discovery_digest: self.discovery_digest.clone(),
            encoder_id: "bm25-turbo-tokenizer".to_owned(),
            encoder_version: "0.2.0".to_owned(),
            examined,
            accepted: 0,
            truncated,
            hits: Vec::new(),
        })
    }

    fn resolve_vector(
        &self,
        query_vector: Option<&[f32]>,
        sink: &mut BoundedSeedSink<'_>,
    ) -> Result<SeedChannelReceipt, DiscoveryQueryError> {
        let cap = sink.remaining();
        let (hits, examined, truncated) = self.vector_hits(query_vector, cap)?;
        for hit in hits {
            sink.push(hit);
        }
        Ok(SeedChannelReceipt {
            channel: SeedChannel::Vector,
            index_generation: self.vector_authority.index_generation,
            index_digest: self.vector_authority.index_digest.clone(),
            source_discovery_digest: self.discovery_digest.clone(),
            encoder_id: self.vector_authority.model_id.clone(),
            encoder_version: self.vector_authority.model_version.clone(),
            examined,
            accepted: 0,
            truncated,
            hits: Vec::new(),
        })
    }
}

fn lexical_digest(sidecar: &ScopeLexicalQuerySidecar) -> Result<String, DiscoveryQueryError> {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix-prepared-lexical-index/v1\0");
    hasher.update(&sidecar.generation.to_le_bytes());
    hasher.update(
        &serde_json::to_vec(&sidecar.docs).map_err(|error| resolver_error(error.to_string()))?,
    );
    let mut file = File::open(&sidecar.index_path).map_err(resolver_error)?;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer).map_err(resolver_error)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hasher.finalize().to_hex().to_string())
}

fn distance_similarity(distance: f64) -> f64 {
    if !distance.is_finite() {
        return 0.0;
    }
    1.0 / (1.0 + distance.max(0.0))
}

fn normalize(value: f64, maximum: f64) -> u32 {
    ((value / maximum.max(f64::EPSILON)).clamp(0.000_001, 1.0) * 1_000_000.0).round() as u32
}

fn quantize_raw(value: f64) -> i64 {
    (value.clamp(i64::MIN as f64 / 1_000_000.0, i64::MAX as f64 / 1_000_000.0) * 1_000_000.0)
        .round() as i64
}

fn resolver_error(error: impl std::fmt::Display) -> DiscoveryQueryError {
    DiscoveryQueryError::Resolver(error.to_string())
}

#[cfg(test)]
mod tests {
    use super::bounded_lexical_hits;
    use bm25_turbo::{persistence, BM25Builder};

    #[test]
    fn sparse_lexical_lookup_cost_is_independent_of_corpus_size() {
        let root = tempfile::tempdir().unwrap();
        let small = sparse_lookup(root.path(), 128);
        let large = sparse_lookup(root.path(), 4_096);
        assert_eq!(small.1, 17);
        assert_eq!(large.1, 17);
        assert!(small.2 && large.2);
        assert!(small.0.len() <= 4 && large.0.len() <= 4);
    }

    fn sparse_lookup(
        root: &std::path::Path,
        corpus_size: usize,
    ) -> (Vec<phoenix_discovery_query::SeedHit>, u32, bool) {
        let corpus = (0..corpus_size)
            .map(|index| format!("common token-{index}"))
            .collect::<Vec<_>>();
        let refs = corpus.iter().map(String::as_str).collect::<Vec<_>>();
        let index = BM25Builder::new().build_from_corpus(&refs).unwrap();
        let path = root.join(format!("lexical-{corpus_size}.bm25"));
        persistence::save(&index, &path).unwrap();
        let mapped = persistence::load_mmap(&path).unwrap();
        let dense = (0..corpus_size as u32).map(Some).collect::<Vec<_>>();
        bounded_lexical_hits(&mapped, &dense, "common", 17, 4).unwrap()
    }
}
