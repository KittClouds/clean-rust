use crate::{
    execute_and_publish, CandidateReviewDecision, DiscoveryCandidateLedger, ProductionSeedAdapter,
    ProductionSeedLimits,
};
use phoenix_discovery_community::{
    write_deterministic_community_artifact, DeterministicCommunityArtifact,
    DeterministicCommunityPolicy,
};
use phoenix_discovery_query::{
    BoundedSeedSink, BudgetExhaustion, DiscoveryPath, DiscoveryQueryError, DiscoveryScorePolicy,
    PathScoreReceipt, PreparedDiscoveryQuery, PreparedQueryReceipt, PreparedQueryRequest,
    PreparedQueryResponse, PreparedSeedResolver, QueryLimits, QueryScratch, QueryStableId,
    SeedChannel, SeedChannelReceipt, SeedHit,
};
use phoenix_discovery_view::{
    write_asserted_discovery_view, AssertedDiscoveryView, DiscoveryAuthorityBinding,
    DiscoveryRelationPolicy,
};
use phoenix_graph_kernel::{
    KernelEdge, KernelEdgeType, KernelGraphLayer, KernelGraphSnapshot, KernelProvenance,
    KernelRelationClass, KernelVertex, KernelVertexClass, KernelVertexId,
};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::ScopeKey;

struct E2eResolver {
    generation: u64,
    digest: String,
    seed: SeedHit,
}

impl PreparedSeedResolver for E2eResolver {
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
        sink.push(self.seed);
        Ok(seed_channel_receipt(
            SeedChannel::Lexical,
            self.generation,
            &self.digest,
            1,
        ))
    }

    fn resolve_vector(
        &self,
        _query_vector: Option<&[f32]>,
        _sink: &mut BoundedSeedSink<'_>,
    ) -> Result<SeedChannelReceipt, DiscoveryQueryError> {
        Ok(seed_channel_receipt(
            SeedChannel::Vector,
            self.generation,
            &self.digest,
            0,
        ))
    }
}

#[test]
fn prepared_query_executes_and_publishes_candidate_only_e2e() {
    let root = tempfile::tempdir().unwrap();
    let (discovery, communities, relation_policy) = discovery_fixture(root.path(), 19);
    let limits = QueryLimits::interactive();
    let prepared = PreparedDiscoveryQuery::prepare(
        &discovery,
        &communities,
        &relation_policy,
        &DiscoveryScorePolicy::phoenix_discovery_v1(),
        limits,
    )
    .unwrap();
    let seed = (0..discovery.node_count() as u32)
        .find(|node| discovery.node_external_id(*node).unwrap() == "n0")
        .unwrap();
    let resolver = E2eResolver {
        generation: 19,
        digest: discovery.manifest().artifact_digest.clone(),
        seed: SeedHit {
            node: seed,
            raw_score_micros: 725_000,
            score_micros: 900_000,
        },
    };
    let ledger = DiscoveryCandidateLedger::open(root.path().join("ledger")).unwrap();
    let mut scratch = QueryScratch::new(limits).unwrap();
    let first = execute_and_publish(
        &prepared,
        PreparedQueryRequest {
            query: "where does n0 lead?",
            query_vector: None,
            narrative_time: None,
        },
        &resolver,
        &mut scratch,
        &ledger,
    )
    .unwrap();
    let second = execute_and_publish(
        &prepared,
        PreparedQueryRequest {
            query: "where does n0 lead?",
            query_vector: None,
            narrative_time: None,
        },
        &resolver,
        &mut scratch,
        &ledger,
    )
    .unwrap();

    assert_eq!(first, second);
    assert!(!first.response.paths.is_empty());
    assert_eq!(
        first.publication.candidates.len(),
        first.response.paths.len()
    );
    assert_eq!(first.publication.run.topology_writes, 0);
    assert!(first
        .publication
        .candidates
        .iter()
        .all(|candidate| candidate.topology_writes == 0
            && candidate.initial_review_status == "pending"
            && candidate.exhaustion == first.response.receipt.exhaustion));
    let lexical = &first.publication.run.receipt.lexical_seed_receipt;
    assert_eq!(lexical.hits, vec![resolver.seed]);
    assert_eq!(lexical.accepted, 1);
    assert_eq!(lexical.encoder_id, "test-index");
}

#[test]
fn candidate_publication_is_content_addressed_and_review_chain_is_append_only() {
    let root = tempfile::tempdir().unwrap();
    let ledger = DiscoveryCandidateLedger::open(root.path()).unwrap();
    let response = response();
    let first = ledger.publish("where is the bridge?", &response).unwrap();
    let second = ledger.publish("where is the bridge?", &response).unwrap();
    assert_eq!(first, second);
    assert_eq!(first.candidates.len(), 1);
    assert_eq!(first.candidates[0].topology_writes, 0);

    let candidate = &first.candidates[0].candidate_id;
    let rejected = ledger
        .record_review(
            candidate,
            None,
            CandidateReviewDecision::Rejected,
            "reviewer-a".to_owned(),
            10,
            vec!["evidence:counterexample".to_owned()],
            None,
        )
        .unwrap();
    assert_eq!(
        ledger.latest_review(candidate).unwrap(),
        Some(rejected.clone())
    );
    assert!(ledger
        .record_review(
            candidate,
            None,
            CandidateReviewDecision::Reopened,
            "reviewer-a".to_owned(),
            11,
            Vec::new(),
            None,
        )
        .is_err());
    let reopened = ledger
        .record_review(
            candidate,
            Some(rejected.event_id),
            CandidateReviewDecision::Reopened,
            "reviewer-b".to_owned(),
            12,
            Vec::new(),
            None,
        )
        .unwrap();
    assert_eq!(ledger.latest_review(candidate).unwrap(), Some(reopened));
}

#[test]
fn promotion_requires_an_external_receipt_and_never_writes_topology() {
    let root = tempfile::tempdir().unwrap();
    let ledger = DiscoveryCandidateLedger::open(root.path()).unwrap();
    let publication = ledger.publish("promote?", &response()).unwrap();
    let candidate = &publication.candidates[0].candidate_id;
    assert!(ledger
        .record_review(
            candidate,
            None,
            CandidateReviewDecision::PromotionApproved,
            "reviewer".to_owned(),
            20,
            Vec::new(),
            None,
        )
        .is_err());
    let event = ledger
        .record_review(
            candidate,
            None,
            CandidateReviewDecision::PromotionApproved,
            "reviewer".to_owned(),
            20,
            vec!["evidence:verified".to_owned()],
            Some("promotion-receipt-1".to_owned()),
        )
        .unwrap();
    assert_eq!(event.topology_writes, 0);
}

#[test]
fn concurrent_review_writers_cannot_fork_the_immutable_head() {
    let root = tempfile::tempdir().unwrap();
    let ledger = DiscoveryCandidateLedger::open(root.path()).unwrap();
    let candidate = ledger
        .publish("concurrent?", &response())
        .unwrap()
        .candidates[0]
        .candidate_id
        .clone();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(3));
    let workers = (0..2)
        .map(|worker| {
            let root = root.path().to_path_buf();
            let candidate = candidate.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                let ledger = DiscoveryCandidateLedger::open(root).unwrap();
                barrier.wait();
                ledger
                    .record_review(
                        &candidate,
                        None,
                        CandidateReviewDecision::Reopened,
                        format!("reviewer-{worker}"),
                        1_800_000_100 + worker,
                        vec![format!("evidence-{worker}")],
                        None,
                    )
                    .is_ok()
            })
        })
        .collect::<Vec<_>>();
    barrier.wait();
    let outcomes = workers
        .into_iter()
        .map(|worker| worker.join().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(outcomes.iter().filter(|outcome| **outcome).count(), 1);
    assert!(ledger.latest_review(&candidate).unwrap().is_some());
}

#[test]
fn production_limits_reject_unbounded_shapes() {
    assert_eq!(ProductionSeedLimits::default().query_bytes, 16_384);
    assert_eq!(ProductionSeedLimits::default().lexical_postings, 16_384);
    assert_eq!(ProductionSeedLimits::default().vector_oversample, 64);
}

#[test]
fn production_adapter_fails_closed_when_bound_indexes_are_missing() {
    let root = tempfile::tempdir().unwrap();
    let (discovery, _communities, _policy) = discovery_fixture(root.path(), 23);
    let store = PhoenixOvergraphStore::open(root.path().join("store")).unwrap();
    assert!(ProductionSeedAdapter::prepare(
        &store,
        ScopeKey::default(),
        &discovery,
        "encoder-v1",
        ProductionSeedLimits::default(),
    )
    .is_err());
}

fn response() -> PreparedQueryResponse {
    let discovery = "a".repeat(64);
    let lexical = receipt(SeedChannel::Lexical, &discovery);
    let vector = receipt(SeedChannel::Vector, &discovery);
    let seed_receipt_digest = blake3::hash(&serde_json::to_vec(&(&lexical, &vector)).unwrap())
        .to_hex()
        .to_string();
    PreparedQueryResponse {
        paths: vec![DiscoveryPath {
            dense_nodes: vec![3],
            node_identities: vec![QueryStableId {
                hash: 33,
                collision: 0,
            }],
            edges: Vec::new(),
            terminal_community: None,
            score: PathScoreReceipt::default(),
        }],
        receipt: PreparedQueryReceipt {
            generation: 7,
            discovery_digest: discovery,
            community_digest: "b".repeat(64),
            relation_policy_digest: "c".repeat(64),
            score_policy_id: "score".to_owned(),
            score_policy_version: "1".to_owned(),
            score_policy_digest: "d".repeat(64),
            limits_digest: "e".repeat(64),
            mode: QueryLimits::interactive().mode,
            limits: QueryLimits::interactive(),
            lexical_candidates: 1,
            vector_candidates: 1,
            invalid_seed_candidates: 0,
            lexical_seed_receipt: lexical,
            vector_seed_receipt: vector,
            seed_receipt_digest,
            resolved_seeds: 1,
            ppr_visited_vertices: 1,
            ppr_pushes: 1,
            ppr_examined_edges: 0,
            beam_states: 1,
            beam_examined_edges: 0,
            total_examined_edges: 0,
            returned_paths: 1,
            exhaustion: BudgetExhaustion::default(),
            admitted_candidate_edges: 0,
            topology_writes: 0,
            fallback_used: false,
        },
    }
}

fn receipt(channel: SeedChannel, discovery: &str) -> SeedChannelReceipt {
    SeedChannelReceipt {
        channel,
        index_generation: 7,
        index_digest: "9".repeat(64),
        source_discovery_digest: discovery.to_owned(),
        encoder_id: "encoder".to_owned(),
        encoder_version: "1".to_owned(),
        examined: 1,
        accepted: 1,
        truncated: false,
        hits: vec![SeedHit {
            node: 0,
            raw_score_micros: 1_000_000,
            score_micros: 1_000_000,
        }],
    }
}

fn seed_channel_receipt(
    channel: SeedChannel,
    generation: u64,
    discovery: &str,
    examined: u32,
) -> SeedChannelReceipt {
    SeedChannelReceipt {
        channel,
        index_generation: generation,
        index_digest: blake3::hash(format!("{channel:?}-index").as_bytes())
            .to_hex()
            .to_string(),
        source_discovery_digest: discovery.to_owned(),
        encoder_id: "test-index".to_owned(),
        encoder_version: "1".to_owned(),
        examined,
        accepted: 0,
        truncated: false,
        hits: Vec::new(),
    }
}

fn discovery_fixture(
    root: &std::path::Path,
    generation: u64,
) -> (
    AssertedDiscoveryView,
    DeterministicCommunityArtifact,
    DiscoveryRelationPolicy,
) {
    let vertices = (0..4)
        .map(|index| KernelVertex {
            id: KernelVertexId(format!("n{index}")),
            kind: "entity".to_owned(),
            class: KernelVertexClass::Entity,
            ..KernelVertex::default()
        })
        .collect::<Vec<_>>();
    let asserted_edges = (0..3)
        .map(|index| KernelEdge {
            source_id: KernelVertexId(format!("n{index}")),
            target_id: KernelVertexId(format!("n{}", index + 1)),
            edge_type: KernelEdgeType(format!("r-{index}")),
            relation_class: KernelRelationClass::Semantic,
            layer: KernelGraphLayer::Asserted,
            provenance: KernelProvenance {
                confidence: Some(0.95),
                evidence_refs: vec![format!("e-{index}")],
                ..KernelProvenance::default()
            },
            ..KernelEdge::default()
        })
        .collect();
    let snapshot = KernelGraphSnapshot {
        vertices,
        asserted_edges,
        candidate_edges: Vec::new(),
    };
    let relation_policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
    let authority = DiscoveryAuthorityBinding {
        generation,
        source_snapshot_id: format!("runtime-fixture-{generation}"),
        source_snapshot_digest: *blake3::hash(b"runtime-snapshot").as_bytes(),
        evidence_registry_digest: *blake3::hash(b"runtime-evidence").as_bytes(),
    };
    let discovery_root = root.join("discovery");
    let discovery_manifest =
        write_asserted_discovery_view(&snapshot, &authority, &relation_policy, &discovery_root)
            .unwrap();
    let discovery =
        AssertedDiscoveryView::open(discovery_root.join(discovery_manifest.artifact_digest))
            .unwrap();
    let community_root = root.join("communities");
    let community_manifest = write_deterministic_community_artifact(
        &discovery,
        &relation_policy,
        &DeterministicCommunityPolicy::phoenix_semantic_core_v1(),
        &community_root,
    )
    .unwrap();
    let communities = DeterministicCommunityArtifact::open(
        community_root.join(community_manifest.artifact_digest),
    )
    .unwrap();
    (discovery, communities, relation_policy)
}
