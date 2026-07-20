use crate::{
    BoundedSeedSink, DiscoveryQueryError, DiscoveryScorePolicy, PreparedDiscoveryQuery,
    PreparedQueryRequest, PreparedSeedResolver, QueryLimits, QueryScratch, SeedChannel,
    SeedChannelReceipt, SeedHit,
};
use phoenix_discovery_community::{
    write_deterministic_community_artifact, DeterministicCommunityArtifact,
    DeterministicCommunityPolicy,
};
use phoenix_discovery_view::{
    write_asserted_discovery_view, AssertedDiscoveryView, DiscoveryAuthorityBinding,
    DiscoveryRelationPolicy,
};
use phoenix_graph_kernel::{
    KernelEdge, KernelEdgeType, KernelGraphLayer, KernelGraphSnapshot, KernelProvenance,
    KernelRelationClass, KernelVertex, KernelVertexClass, KernelVertexId,
};

struct FixedResolver {
    generation: u64,
    digest: String,
    lexical: Vec<SeedHit>,
    vector: Vec<SeedHit>,
}

impl PreparedSeedResolver for FixedResolver {
    fn generation(&self) -> u64 {
        self.generation
    }

    fn discovery_digest(&self) -> &str {
        &self.digest
    }

    fn resolve_lexical(
        &self,
        _query: &str,
        sink: &mut BoundedSeedSink<'_>,
    ) -> Result<SeedChannelReceipt, DiscoveryQueryError> {
        for hit in &self.lexical {
            sink.push(*hit);
        }
        Ok(self.receipt(SeedChannel::Lexical, self.lexical.len() as u32))
    }

    fn resolve_vector(
        &self,
        _query_vector: Option<&[f32]>,
        sink: &mut BoundedSeedSink<'_>,
    ) -> Result<SeedChannelReceipt, DiscoveryQueryError> {
        for hit in &self.vector {
            sink.push(*hit);
        }
        Ok(self.receipt(SeedChannel::Vector, self.vector.len() as u32))
    }
}

impl FixedResolver {
    fn receipt(&self, channel: SeedChannel, examined: u32) -> SeedChannelReceipt {
        SeedChannelReceipt {
            channel,
            index_generation: self.generation,
            index_digest: self.digest.clone(),
            source_discovery_digest: self.digest.clone(),
            encoder_id: "fixed-test".to_owned(),
            encoder_version: "1".to_owned(),
            examined,
            accepted: 0,
            truncated: false,
            hits: Vec::new(),
        }
    }
}

#[test]
fn prepared_query_is_deterministic_bounded_and_receipted() {
    let root = tempfile::tempdir().unwrap();
    let (source, communities, policy) = artifacts(root.path(), 71, 96);
    let seed = node(&source, "n0");
    let resolver = FixedResolver {
        generation: 71,
        digest: source.manifest().artifact_digest.clone(),
        lexical: vec![SeedHit {
            node: seed,
            raw_score_micros: 900_000,
            score_micros: 900_000,
        }],
        vector: vec![SeedHit {
            node: seed,
            raw_score_micros: 800_000,
            score_micros: 800_000,
        }],
    };
    let limits = QueryLimits::interactive();
    let runtime = PreparedDiscoveryQuery::prepare(
        &source,
        &communities,
        &policy,
        &DiscoveryScorePolicy::phoenix_discovery_v1(),
        limits,
    )
    .unwrap();
    let mut scratch = QueryScratch::new(limits).unwrap();
    let first = runtime
        .execute(
            PreparedQueryRequest {
                query: "n0",
                query_vector: None,
                narrative_time: None,
            },
            &resolver,
            &mut scratch,
        )
        .unwrap();
    let second = runtime
        .execute(
            PreparedQueryRequest {
                query: "n0",
                query_vector: None,
                narrative_time: None,
            },
            &resolver,
            &mut scratch,
        )
        .unwrap();

    assert_eq!(first, second);
    assert!(!first.paths.is_empty());
    assert!(first.paths.len() <= 24);
    assert!(first.paths.iter().all(|path| path.edges.len() <= 4));
    assert!(first.receipt.ppr_visited_vertices <= 4_096);
    assert!(first.receipt.ppr_examined_edges <= 8_192);
    assert!(first.receipt.total_examined_edges <= 16_384);
    assert_eq!(first.receipt.admitted_candidate_edges, 0);
    assert_eq!(first.receipt.topology_writes, 0);
    assert!(!first.receipt.fallback_used);
    assert_eq!(first.receipt.score_policy_version, "1");
    assert_eq!(first.receipt.score_policy_digest.len(), 64);
    for path in &first.paths {
        assert!(!path.score.evidence_quality.available);
        assert_eq!(path.score.evidence_quality.value_micros, 0);
        assert!(!path.score.model_frontier_boost.available);
        assert!(!path.score.temporal_relevance.available);
        assert_eq!(path.score.final_score_micros, contribution_sum(&path.score));
    }
    assert!(first
        .paths
        .iter()
        .skip(1)
        .any(|path| path.score.selected_path_redundancy.available));

    let one_edge = first
        .paths
        .iter()
        .find(|path| path.edges.len() == 1)
        .unwrap();
    let two_edges = first
        .paths
        .iter()
        .find(|path| path.edges.len() == 2)
        .unwrap();
    assert_eq!(
        one_edge.score.normalized_asserted_confidence.value_micros,
        two_edges.score.normalized_asserted_confidence.value_micros
    );
}

#[test]
fn resolver_authority_mismatch_fails_closed_before_lookup() {
    let root = tempfile::tempdir().unwrap();
    let (source, communities, policy) = artifacts(root.path(), 73, 8);
    let resolver = FixedResolver {
        generation: 72,
        digest: "wrong".to_owned(),
        lexical: Vec::new(),
        vector: Vec::new(),
    };
    let limits = QueryLimits::interactive();
    let runtime = PreparedDiscoveryQuery::prepare(
        &source,
        &communities,
        &policy,
        &DiscoveryScorePolicy::phoenix_discovery_v1(),
        limits,
    )
    .unwrap();
    let mut scratch = QueryScratch::new(limits).unwrap();
    let error = runtime
        .execute(
            PreparedQueryRequest {
                query: "anything",
                query_vector: None,
                narrative_time: None,
            },
            &resolver,
            &mut scratch,
        )
        .unwrap_err();
    assert!(error.to_string().contains("seed index authority"));
}

#[test]
fn seed_sink_and_high_degree_expansion_never_escape_caps() {
    let root = tempfile::tempdir().unwrap();
    let (source, communities, policy) = artifacts(root.path(), 79, 300);
    let lexical = (0..80)
        .map(|index| SeedHit {
            node: index,
            raw_score_micros: i64::from(1_000_000 - index * 1_000),
            score_micros: 1_000_000 - index * 1_000,
        })
        .collect();
    let resolver = FixedResolver {
        generation: 79,
        digest: source.manifest().artifact_digest.clone(),
        lexical,
        vector: Vec::new(),
    };
    let limits = QueryLimits::interactive();
    let runtime = PreparedDiscoveryQuery::prepare(
        &source,
        &communities,
        &policy,
        &DiscoveryScorePolicy::phoenix_discovery_v1(),
        limits,
    )
    .unwrap();
    let mut scratch = QueryScratch::new(limits).unwrap();
    let response = runtime
        .execute(
            PreparedQueryRequest {
                query: "hub",
                query_vector: None,
                narrative_time: None,
            },
            &resolver,
            &mut scratch,
        )
        .unwrap();
    assert_eq!(response.receipt.resolved_seeds, 32);
    assert!(response.receipt.exhaustion.seed_candidates);
    assert!(response.receipt.total_examined_edges <= 16_384);
    assert!(response.receipt.returned_paths <= 24);
}

#[test]
fn interactive_mode_cannot_silently_become_six_hop() {
    let mut invalid = QueryLimits::interactive();
    invalid.hops = 6;
    assert!(invalid.validate().is_err());
    assert_eq!(
        QueryLimits::background_six_hop().validate().unwrap().hops,
        6
    );
}

#[test]
#[ignore = "focused performance benchmark"]
fn prepared_query_10k_benchmark() {
    let root = tempfile::tempdir().unwrap();
    let (source, communities, policy) = artifacts(root.path(), 83, 10_000);
    let resolver = FixedResolver {
        generation: 83,
        digest: source.manifest().artifact_digest.clone(),
        lexical: vec![SeedHit {
            node: node(&source, "n0"),
            raw_score_micros: 1_000_000,
            score_micros: 1_000_000,
        }],
        vector: Vec::new(),
    };
    let limits = QueryLimits::interactive();
    let runtime = PreparedDiscoveryQuery::prepare(
        &source,
        &communities,
        &policy,
        &DiscoveryScorePolicy::phoenix_discovery_v1(),
        limits,
    )
    .unwrap();
    let mut scratch = QueryScratch::new(limits).unwrap();
    let request = PreparedQueryRequest {
        query: "benchmark",
        query_vector: None,
        narrative_time: None,
    };
    runtime
        .execute(request.clone(), &resolver, &mut scratch)
        .unwrap();
    let mut samples = Vec::with_capacity(100);
    let mut examined = 0;
    for _ in 0..100 {
        let started = std::time::Instant::now();
        let response = runtime
            .execute(request.clone(), &resolver, &mut scratch)
            .unwrap();
        samples.push(started.elapsed().as_micros());
        examined = response.receipt.total_examined_edges;
    }
    samples.sort_unstable();
    eprintln!(
        "prepared-query nodes=10000 edges={} p50_us={} p95_us={} examined={examined}",
        source.edge_count(),
        samples[50],
        samples[95]
    );
    assert!(examined <= 16_384);
}

fn artifacts(
    root: &std::path::Path,
    generation: u64,
    nodes: u32,
) -> (
    AssertedDiscoveryView,
    DeterministicCommunityArtifact,
    DiscoveryRelationPolicy,
) {
    let snapshot = fixture(nodes);
    let policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
    let authority = DiscoveryAuthorityBinding {
        generation,
        source_snapshot_id: format!("query-fixture-{generation}"),
        source_snapshot_digest: *blake3::hash(format!("snapshot-{generation}").as_bytes())
            .as_bytes(),
        evidence_registry_digest: *blake3::hash(format!("evidence-{generation}").as_bytes())
            .as_bytes(),
    };
    let source_root = root.join("discovery");
    let source_manifest =
        write_asserted_discovery_view(&snapshot, &authority, &policy, &source_root).unwrap();
    let source =
        AssertedDiscoveryView::open(source_root.join(source_manifest.artifact_digest)).unwrap();
    let community_root = root.join("communities");
    let community_manifest = write_deterministic_community_artifact(
        &source,
        &policy,
        &DeterministicCommunityPolicy::phoenix_semantic_core_v1(),
        &community_root,
    )
    .unwrap();
    let communities = DeterministicCommunityArtifact::open(
        community_root.join(community_manifest.artifact_digest),
    )
    .unwrap();
    (source, communities, policy)
}

fn fixture(nodes: u32) -> KernelGraphSnapshot {
    let vertices = (0..nodes)
        .map(|index| KernelVertex {
            id: KernelVertexId(format!("n{index}")),
            kind: "entity".to_owned(),
            class: KernelVertexClass::Entity,
            ..KernelVertex::default()
        })
        .collect();
    let mut asserted_edges = Vec::new();
    for target in 1..nodes {
        asserted_edges.push(edge(0, target, KernelRelationClass::Semantic));
        if target + 1 < nodes {
            asserted_edges.push(edge(target, target + 1, KernelRelationClass::Narrative));
        }
    }
    let candidate_edges = (nodes > 2)
        .then(|| {
            let mut candidate = edge(1, 2, KernelRelationClass::Candidate);
            candidate.layer = KernelGraphLayer::Candidate;
            candidate
        })
        .into_iter()
        .collect();
    KernelGraphSnapshot {
        vertices,
        asserted_edges,
        candidate_edges,
    }
}

fn edge(source: u32, target: u32, class: KernelRelationClass) -> KernelEdge {
    KernelEdge {
        source_id: KernelVertexId(format!("n{source}")),
        target_id: KernelVertexId(format!("n{target}")),
        edge_type: KernelEdgeType(format!("r-{source}-{target}")),
        relation_class: class,
        layer: KernelGraphLayer::Asserted,
        provenance: KernelProvenance {
            confidence: Some(0.9),
            evidence_refs: vec![format!("e-{source}-{target}")],
            ..KernelProvenance::default()
        },
        ..KernelEdge::default()
    }
}

fn node(source: &AssertedDiscoveryView, external: &str) -> u32 {
    (0..source.node_count() as u32)
        .find(|node| source.node_external_id(*node).unwrap() == external)
        .unwrap()
}

fn contribution_sum(score: &crate::PathScoreReceipt) -> i64 {
    [
        score.seed_relevance,
        score.local_ppr_importance,
        score.evidence_quality,
        score.normalized_asserted_confidence,
        score.bridge_strength,
        score.community_affinity,
        score.cross_community_novelty,
        score.temporal_relevance,
        score.model_frontier_boost,
        score.common_relation_penalty,
        score.path_length_penalty,
        score.selected_path_redundancy,
    ]
    .iter()
    .map(|signal| signal.value_micros)
    .sum()
}
