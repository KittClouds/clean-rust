use crate::{
    execute_and_publish, execute_and_publish_with_cancellation, CandidateReviewDecision,
    DiscoveryCandidateLedger, HumanGraphProposalIdentification, ProductionSeedAdapter,
    ProductionSeedLimits, PublishedDiscoveryQuery,
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
    GraphProposalStatus, GraphTruthAtomKey, KernelEdge, KernelEdgeType, KernelGraphLayer,
    KernelGraphSnapshot, KernelProvenance, KernelRelationClass, KernelVertex, KernelVertexClass,
    KernelVertexId,
};
use phoenix_graph_post::promotion_verdict::{
    build_graph_promotion_verdict_certificate, GraphPromotionUserOverride,
    GraphPromotionUserOverrideKind, GraphPromotionVerdictStatus,
};
use phoenix_store_native_core::{
    GraphProposalReceiptAppend, PhoenixGraphKernelStoreV2, PhoenixGraphLearningStore,
};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{GraphTruthDescriptor, GraphTruthKind, GraphTruthOperation, ScopeKey};

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
    let receipt_id = first.publication.path_receipts[0].receipt_id.clone();
    let receipt_path = root
        .path()
        .join("ledger")
        .join("receipts")
        .join(&receipt_id)
        .join("receipt.json");
    let first_receipt_bytes = std::fs::read(&receipt_path).unwrap();
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
    let second_receipt_bytes = std::fs::read(receipt_path).unwrap();

    assert_eq!(first, second);
    assert_eq!(first_receipt_bytes, second_receipt_bytes);
    assert!(!first.response.paths.is_empty());
    assert_eq!(
        first.publication.candidates.len(),
        first.response.paths.len()
    );
    assert_eq!(first.publication.run.topology_writes, 0);
    assert_eq!(
        first.publication.path_receipts.len(),
        first.response.paths.len()
    );
    assert_eq!(first.publication.run.path_receipt_ids[0], receipt_id);
    assert_eq!(first.publication.candidates[0].path_receipt_id, receipt_id);
    assert!(first
        .publication
        .path_receipts
        .iter()
        .all(|receipt| receipt.candidate_only
            && receipt.asserted_edges_traversed as usize == receipt.path.edges.len()
            && receipt.candidate_edges_traversed == 0
            && receipt.topology_writes == 0));
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
fn cancelled_query_publishes_only_its_run_receipt() {
    let root = tempfile::tempdir().unwrap();
    let (discovery, communities, relation_policy) = discovery_fixture(root.path(), 29);
    let limits = QueryLimits::interactive();
    let prepared = PreparedDiscoveryQuery::prepare(
        &discovery,
        &communities,
        &relation_policy,
        &DiscoveryScorePolicy::phoenix_discovery_v1(),
        limits,
    )
    .unwrap();
    let resolver = E2eResolver {
        generation: 29,
        digest: discovery.manifest().artifact_digest.clone(),
        seed: SeedHit {
            node: 0,
            raw_score_micros: 1_000_000,
            score_micros: 1_000_000,
        },
    };
    let ledger = DiscoveryCandidateLedger::open(root.path().join("ledger")).unwrap();
    let mut scratch = QueryScratch::new(limits).unwrap();
    let publication = execute_and_publish_with_cancellation(
        &prepared,
        PreparedQueryRequest {
            query: "cancel this run",
            query_vector: None,
            narrative_time: None,
        },
        &resolver,
        &mut scratch,
        &ledger,
        &|| true,
    )
    .unwrap();

    assert!(publication.response.paths.is_empty());
    assert!(publication.publication.path_receipts.is_empty());
    assert!(publication.publication.candidates.is_empty());
    assert!(publication.publication.run.receipt.cancellation.observed);
    assert_eq!(publication.publication.run.receipt.returned_paths, 0);
    assert_eq!(publication.publication.run.topology_writes, 0);
}

#[test]
fn human_identified_atom_enters_existing_native_proposal_boundary() {
    let root = tempfile::tempdir().unwrap();
    let (ledger, discovery) = published_discovery(root.path(), 41);
    let path = discovery
        .publication
        .path_receipts
        .iter()
        .find(|receipt| !receipt.path.edges.is_empty())
        .unwrap();
    let store = PhoenixOvergraphStore::open(root.path().join("store")).unwrap();
    let identification = proposal_identification(path.receipt_id.clone());
    let first = ledger
        .publish_human_graph_proposal(&store, identification.clone())
        .unwrap();
    let second = ledger
        .publish_human_graph_proposal(&store, identification)
        .unwrap();

    assert!(matches!(
        first.append,
        GraphProposalReceiptAppend::Appended { .. }
    ));
    assert!(matches!(
        second.append,
        GraphProposalReceiptAppend::AlreadyPresent { .. }
    ));
    assert_eq!(first.receipt, second.receipt);
    assert_eq!(first.receipt.proposals.len(), 1);
    assert_eq!(
        first.receipt.proposals[0].status,
        GraphProposalStatus::Generated
    );
    assert!(!first.receipt.proposals[0].evidence_refs.is_empty());
    assert!(first.receipt.proposals[0]
        .evidence_refs
        .iter()
        .all(|value| value.starts_with("query-stable-id:")));
    assert_eq!(
        first
            .receipt
            .discovery_origin
            .as_ref()
            .unwrap()
            .source_path_receipt_id,
        path.receipt_id
    );
    assert_eq!(first.topology_writes, 0);
    assert_eq!(store.kernel_journal_len().unwrap(), 0);
    assert_eq!(
        store
            .load_graph_proposal_receipt(first.receipt.receipt_id.as_str())
            .unwrap(),
        Some(first.receipt.clone())
    );

    let deferred =
        build_graph_promotion_verdict_certificate(std::slice::from_ref(&first.receipt), &[], &[])
            .unwrap();
    assert_eq!(
        deferred.rows[0].status,
        GraphPromotionVerdictStatus::Deferred
    );
    assert_eq!(deferred.rows[0].apply_plan.operation, None);
    let authorized = build_graph_promotion_verdict_certificate(
        std::slice::from_ref(&first.receipt),
        &[],
        &[GraphPromotionUserOverride {
            receipt_id: first.receipt.receipt_id.clone(),
            proposal_id: first.receipt.proposals[0].proposal_id.clone(),
            kind: GraphPromotionUserOverrideKind::Approve,
            user_id: "reviewer-2".into(),
            rationale: "evidence independently reviewed".into(),
        }],
    )
    .unwrap();
    assert_eq!(
        authorized.rows[0].status,
        GraphPromotionVerdictStatus::Acceptable
    );
    assert_eq!(
        authorized.rows[0].apply_plan.operation,
        Some(GraphTruthOperation::Assert)
    );
    assert_eq!(store.kernel_journal_len().unwrap(), 0);
}

#[test]
fn discovery_proposal_rejects_broken_links_and_implicit_path_promotion() {
    let root = tempfile::tempdir().unwrap();
    let (ledger, discovery) = published_discovery(root.path(), 43);
    let store = PhoenixOvergraphStore::open(root.path().join("store")).unwrap();
    assert!(ledger
        .publish_human_graph_proposal(&store, proposal_identification("f".repeat(64)))
        .is_err());

    let path = discovery
        .publication
        .path_receipts
        .iter()
        .find(|receipt| !receipt.path.edges.is_empty())
        .unwrap();
    let mut missing_support = proposal_identification(path.receipt_id.clone());
    missing_support.supporting_path_edge_indices.clear();
    assert!(ledger
        .publish_human_graph_proposal(&store, missing_support)
        .is_err());
    assert!(store.load_graph_proposal_receipts().unwrap().is_empty());
    assert_eq!(store.kernel_journal_len().unwrap(), 0);
}

#[test]
fn tampered_or_missing_path_receipt_blocks_candidate_review() {
    let root = tempfile::tempdir().unwrap();
    let ledger = DiscoveryCandidateLedger::open(root.path()).unwrap();
    let publication = ledger.publish("tamper?", &response()).unwrap();
    let candidate = &publication.candidates[0];
    let receipt_path = root
        .path()
        .join("receipts")
        .join(&candidate.path_receipt_id)
        .join("receipt.json");
    let original = std::fs::read(&receipt_path).unwrap();
    let mut tampered: serde_json::Value = serde_json::from_slice(&original).unwrap();
    tampered["candidateEdgesTraversed"] = serde_json::Value::from(1);
    std::fs::write(&receipt_path, serde_json::to_vec(&tampered).unwrap()).unwrap();
    assert!(ledger
        .record_review(
            &candidate.candidate_id,
            None,
            CandidateReviewDecision::Rejected,
            "reviewer".to_owned(),
            30,
            Vec::new(),
            None,
        )
        .is_err());

    std::fs::write(&receipt_path, original).unwrap();
    std::fs::remove_file(&receipt_path).unwrap();
    assert!(ledger
        .record_review(
            &candidate.candidate_id,
            None,
            CandidateReviewDecision::Rejected,
            "reviewer".to_owned(),
            31,
            Vec::new(),
            None,
        )
        .is_err());
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
    let candidate_json: serde_json::Value = serde_json::from_slice(
        &std::fs::read(
            root.path()
                .join("candidates")
                .join(candidate)
                .join("candidate.json"),
        )
        .unwrap(),
    )
    .unwrap();
    assert!(candidate_json.get("path").is_none());
    assert_eq!(
        candidate_json["pathReceiptId"],
        first.candidates[0].path_receipt_id
    );
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
    let limits = QueryLimits::interactive();
    let limits_digest = blake3::Hash::from_bytes(limits.digest().unwrap())
        .to_hex()
        .to_string();
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
            source_snapshot_id: "snapshot-7".to_owned(),
            source_snapshot_digest: "1".repeat(64),
            evidence_registry_digest: "2".repeat(64),
            discovery_digest: discovery,
            discovery_payload_digest: "3".repeat(64),
            community_digest: "b".repeat(64),
            community_payload_digest: "4".repeat(64),
            community_policy_id: "community".to_owned(),
            community_policy_version: "1".to_owned(),
            community_policy_digest: "5".repeat(64),
            relation_policy_digest: "c".repeat(64),
            score_policy_id: "score".to_owned(),
            score_policy_version: "1".to_owned(),
            score_policy_digest: "d".repeat(64),
            limits_digest,
            mode: limits.mode,
            limits,
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
            pruning: Default::default(),
            cancellation: Default::default(),
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

fn published_discovery(
    root: &std::path::Path,
    generation: u64,
) -> (DiscoveryCandidateLedger, PublishedDiscoveryQuery) {
    let (discovery, communities, relation_policy) = discovery_fixture(root, generation);
    let limits = QueryLimits::interactive();
    let prepared = PreparedDiscoveryQuery::prepare(
        &discovery,
        &communities,
        &relation_policy,
        &DiscoveryScorePolicy::phoenix_discovery_v1(),
        limits,
    )
    .unwrap();
    let resolver = E2eResolver {
        generation,
        digest: discovery.manifest().artifact_digest.clone(),
        seed: SeedHit {
            node: 0,
            raw_score_micros: 900_000,
            score_micros: 900_000,
        },
    };
    let ledger = DiscoveryCandidateLedger::open(root.join("ledger")).unwrap();
    let mut scratch = QueryScratch::new(limits).unwrap();
    let publication = execute_and_publish(
        &prepared,
        PreparedQueryRequest {
            query: "find a possible missing atom",
            query_vector: None,
            narrative_time: None,
        },
        &resolver,
        &mut scratch,
        &ledger,
    )
    .unwrap();
    (ledger, publication)
}

fn proposal_identification(source_path_receipt_id: String) -> HumanGraphProposalIdentification {
    HumanGraphProposalIdentification {
        source_path_receipt_id,
        scope_key: "global".to_owned(),
        identified_by_user_id: "human-1".to_owned(),
        identification_rationale: "the asserted path suggests one missing bridge".to_owned(),
        created_at: 1_700_000_000,
        atom: GraphTruthAtomKey::edge("n0", "n2", "structural::discovery_bridge"),
        family: "discovery_bridge".to_owned(),
        source_kind: "entity".to_owned(),
        target_kind: "entity".to_owned(),
        truth: GraphTruthDescriptor {
            kind: GraphTruthKind::Structural,
            plane: None,
        },
        supporting_path_node_indices: vec![0, 1],
        supporting_path_edge_indices: vec![0],
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
