//! Entity identity resolution DAG.
//!
//! NER emits mention evidence. This layer turns that evidence into reversible
//! identity receipts: known links, aliases, run-local merges, splits, defers,
//! and new-entity decisions. It does not mutate the atlas.

use std::collections::{BTreeMap, BTreeSet};

use phoenix_types::{
    AtlasAliasEvidence, AtlasAliasProposalDecision, AtlasAliasProposalTarget,
    AtlasIdentityReceiptAction, AtlasIdentityReceiptSummary, AtlasIdentityTargetSummary,
    DocumentId, EntityId, EntityKind, MentionEntityRef, MentionId,
};
use rustc_hash::FxHashMap;
use smallvec::SmallVec;

use crate::alias_resolution::AliasRegistryEntity;
use crate::graph::MentionEdgeKind;
use crate::surface_memory::{SurfaceCandidateTarget, SurfaceMemoryEntry};
use crate::types::MentionPacket;

#[path = "identity_resolution/coref.rs"]
mod coref;
#[path = "identity_resolution/types.rs"]
mod dag_types;
#[path = "identity_resolution/support.rs"]
mod support;
pub use dag_types::{
    IdentityEdge, IdentityEdgeKind, IdentityLinkerCandidate, IdentityNode, IdentityNodeKind,
    IdentityResolutionDag, IdentityResolutionInput,
};
use support::*;

const KNOWN_ACCEPT_THRESHOLD: f32 = 0.62;
const LOCAL_ACCEPT_THRESHOLD: f32 = 0.58;
const DEFER_MARGIN: f32 = 0.08;

pub fn resolve_identity_dag(input: &IdentityResolutionInput<'_>) -> IdentityResolutionDag {
    let mut builder = DagBuilder::new(input);
    builder.seed_nodes();
    builder.ingest_known_refs();
    builder.ingest_surface_memory();
    builder.ingest_alias_report();
    builder.ingest_linker_candidates();
    builder.ingest_mention_graph();
    builder.ingest_document_coreference();
    builder.finalize()
}

struct DagBuilder<'a> {
    input: &'a IdentityResolutionInput<'a>,
    mentions_by_id: FxHashMap<u64, &'a MentionPacket>,
    registry_by_id: BTreeMap<String, &'a AliasRegistryEntity>,
    surface_entries: BTreeMap<String, &'a SurfaceMemoryEntry>,
    surface_mentions: BTreeMap<String, SmallVec<[u64; 8]>>,
    candidates: BTreeMap<u64, BTreeMap<String, ResolutionCandidate>>,
    nodes: Vec<IdentityNode>,
    node_ids: BTreeSet<String>,
    edges: Vec<IdentityEdge>,
    edge_keys: BTreeSet<String>,
    receipts: Vec<AtlasIdentityReceiptSummary>,
}

impl<'a> DagBuilder<'a> {
    fn new(input: &'a IdentityResolutionInput<'a>) -> Self {
        let mut mentions_by_id = FxHashMap::default();
        let mut surface_mentions = BTreeMap::<String, SmallVec<[u64; 8]>>::new();
        for mention in input
            .mentions
            .iter()
            .filter(|mention| identity_eligible(mention))
        {
            let id = mention.mention_id.0;
            mentions_by_id.insert(id, mention);
            if mention.mention_kind == crate::types::MentionKind::Named {
                surface_mentions
                    .entry(surface_key(mention.surface.as_str()))
                    .or_default()
                    .push(id);
            }
        }
        let registry_by_id = input
            .registry_entities
            .iter()
            .map(|entity| (entity.entity_id.0.clone(), entity))
            .collect::<BTreeMap<_, _>>();
        let surface_entries = input
            .surface_memory
            .entries
            .iter()
            .map(|entry| (entry.key.clone(), entry))
            .collect::<BTreeMap<_, _>>();
        Self {
            input,
            mentions_by_id,
            registry_by_id,
            surface_entries,
            surface_mentions,
            candidates: BTreeMap::new(),
            nodes: Vec::new(),
            node_ids: BTreeSet::new(),
            edges: Vec::new(),
            edge_keys: BTreeSet::new(),
            receipts: Vec::new(),
        }
    }

    fn seed_nodes(&mut self) {
        let mentions = self
            .mentions_by_id
            .values()
            .copied()
            .collect::<Vec<&MentionPacket>>();
        for mention in mentions {
            let mut mention_ids = SmallVec::new();
            mention_ids.push(mention.mention_id.0);
            self.push_node(IdentityNode {
                node_id: mention_node_id(mention.mention_id.0),
                kind: IdentityNodeKind::Mention,
                label: mention.surface.to_string(),
                entity_kind: best_entity_kind(mention),
                mention_ids,
            });
        }
        let entities = self.input.registry_entities.to_vec();
        for entity in entities {
            self.ensure_known_node(
                &entity.entity_id,
                &entity.canonical_name,
                entity.kind.clone(),
            );
        }
    }

    fn ingest_known_refs(&mut self) {
        let mentions = self
            .mentions_by_id
            .values()
            .copied()
            .collect::<Vec<&MentionPacket>>();
        for mention in mentions {
            let Some((entity_id, canonical_name, kind)) = self.known_ref_target(mention) else {
                continue;
            };
            let target = AtlasIdentityTargetSummary::KnownEntity {
                entity_id: entity_id.clone(),
                canonical_name: canonical_name.clone(),
                kind: kind.clone(),
            };
            let mention_key = surface_key(mention.surface.as_str());
            let canonical_key = surface_key(&canonical_name);
            let (action, rank, rationale) = if mention_key == canonical_key {
                (
                    AtlasIdentityReceiptAction::KnownEntity,
                    0,
                    "accepted known mention keeps its saved identity",
                )
            } else {
                (
                    AtlasIdentityReceiptAction::AliasOfKnown,
                    4,
                    "known ref links a non-canonical surface to a saved identity",
                )
            };
            self.ensure_known_node(&entity_id, &canonical_name, kind);
            self.add_candidate(
                mention.mention_id.0,
                ResolutionCandidate {
                    target_key: target_key(&target),
                    target,
                    action,
                    score: mention.confidence.max(0.90),
                    evidence: small_evidence(
                        "known_ref",
                        mention.confidence,
                        "mention already has a known entity ref",
                    ),
                    rationale: rationale.to_owned(),
                    rank,
                },
            );
            self.add_edge(
                mention_node_id(mention.mention_id.0),
                known_node_id(&entity_id.0),
                IdentityEdgeKind::KnownReference,
                mention.confidence.max(0.90),
                format!("mention:{}", mention.mention_id.0),
            );
        }
    }

    fn ingest_surface_memory(&mut self) {
        let edges = self.input.surface_memory.candidate_edges.clone();
        for edge in edges {
            let Some(mention) = self.mentions_by_id.get(&edge.mention_id).copied() else {
                continue;
            };
            match &edge.target {
                SurfaceCandidateTarget::KnownEntity(entity_id) => {
                    let (entity_id, canonical_name, kind) =
                        self.registry_target_or_fallback(entity_id);
                    let target = AtlasIdentityTargetSummary::KnownEntity {
                        entity_id: entity_id.clone(),
                        canonical_name: canonical_name.clone(),
                        kind: kind.clone(),
                    };
                    self.ensure_known_node(&entity_id, &canonical_name, kind);
                    self.add_candidate(
                        mention.mention_id.0,
                        ResolutionCandidate {
                            target_key: target_key(&target),
                            target,
                            action: AtlasIdentityReceiptAction::AliasOfKnown,
                            score: edge.confidence,
                            evidence: small_evidence(
                                "surface_memory",
                                edge.confidence,
                                surface_edge_note(edge.kind),
                            ),
                            rationale: "surface memory links the mention to a saved identity"
                                .to_owned(),
                            rank: 3,
                        },
                    );
                    self.add_edge(
                        mention_node_id(mention.mention_id.0),
                        known_node_id(&entity_id.0),
                        IdentityEdgeKind::SurfaceMemory,
                        edge.confidence,
                        edge.key,
                    );
                }
                SurfaceCandidateTarget::SpeculativeEntity(key) => {
                    let target = self.local_target(key, mention);
                    self.ensure_local_node(&target, &[mention.mention_id.0]);
                    self.add_candidate(
                        mention.mention_id.0,
                        ResolutionCandidate {
                            target_key: target_key(&target),
                            target,
                            action: AtlasIdentityReceiptAction::MergeRunLocal,
                            score: edge.confidence,
                            evidence: small_evidence(
                                "surface_memory",
                                edge.confidence,
                                surface_edge_note(edge.kind),
                            ),
                            rationale: "surface memory groups repeated unsaved mentions".to_owned(),
                            rank: 5,
                        },
                    );
                }
                SurfaceCandidateTarget::DeferredReview => {
                    self.add_defer_candidate(
                        mention,
                        edge.confidence,
                        "surface memory requested review",
                    );
                }
            }
        }
        let groups = self.surface_mentions.clone();
        for (key, ids) in groups {
            if ids.len() < 2
                || self
                    .surface_entries
                    .get(&key)
                    .is_some_and(|entry| entry.conflict)
            {
                continue;
            }
            for id in &ids {
                let Some(mention) = self.mentions_by_id.get(id).copied() else {
                    continue;
                };
                let target = self.local_target(&key, mention);
                self.ensure_local_node(&target, ids.as_slice());
                self.add_candidate(
                    *id,
                    ResolutionCandidate {
                        target_key: target_key(&target),
                        target,
                        action: AtlasIdentityReceiptAction::MergeRunLocal,
                        score: (mention.confidence + 0.10).min(0.82),
                        evidence: small_evidence(
                            "same_surface",
                            mention.confidence,
                            "same run-local surface repeats without kind conflict",
                        ),
                        rationale: "same surface cluster can merge into one run-local identity"
                            .to_owned(),
                        rank: 6,
                    },
                );
            }
        }
    }

    fn ingest_alias_report(&mut self) {
        let Some(report) = self.input.alias_report else {
            return;
        };
        for proposal in &report.proposals {
            if proposal.decision == AtlasAliasProposalDecision::Reject {
                continue;
            }
            let Ok(mention_id) = proposal.mention_id.0.parse::<u64>() else {
                continue;
            };
            let Some(mention) = self.mentions_by_id.get(&mention_id).copied() else {
                continue;
            };
            let (target, action) = match &proposal.target {
                AtlasAliasProposalTarget::KnownEntity {
                    entity_id,
                    canonical_name,
                    kind,
                } => (
                    AtlasIdentityTargetSummary::KnownEntity {
                        entity_id: entity_id.clone(),
                        canonical_name: canonical_name.clone(),
                        kind: kind.clone(),
                    },
                    action_for_relation(proposal.relation),
                ),
                AtlasAliasProposalTarget::RunLocalSurface { key, display, kind } => (
                    AtlasIdentityTargetSummary::RunLocalEntity {
                        key: key.clone(),
                        display: display.clone(),
                        kind: kind.clone(),
                    },
                    AtlasIdentityReceiptAction::MergeRunLocal,
                ),
                AtlasAliasProposalTarget::NewEntity => (
                    AtlasIdentityTargetSummary::NewEntity {
                        key: surface_key(&proposal.surface),
                        display: proposal.surface.clone(),
                        kind: best_entity_kind(mention).map(|kind| format!("{kind:?}")),
                    },
                    AtlasIdentityReceiptAction::NewEntity,
                ),
                AtlasAliasProposalTarget::Deferred => {
                    self.add_defer_candidate(mention, proposal.confidence, &proposal.rationale);
                    continue;
                }
            };
            self.ensure_target_node(&target, &[mention_id]);
            self.add_candidate(
                mention_id,
                ResolutionCandidate {
                    target_key: target_key(&target),
                    target: target.clone(),
                    action,
                    score: alias_decision_score(proposal.decision, proposal.confidence),
                    evidence: proposal.evidence.clone().into(),
                    rationale: proposal.rationale.clone(),
                    rank: relation_rank(proposal.relation),
                },
            );
            self.add_edge(
                mention_node_id(mention_id),
                target_node_id(&target),
                IdentityEdgeKind::AliasProposal,
                proposal.confidence,
                proposal.case_id.clone(),
            );
        }
    }

    fn ingest_linker_candidates(&mut self) {
        for candidate in self.input.linker_candidates {
            let Some(mention) = self.mentions_by_id.get(&candidate.mention_id.0).copied() else {
                continue;
            };
            let target = AtlasIdentityTargetSummary::KnownEntity {
                entity_id: candidate.entity_id.clone(),
                canonical_name: candidate.canonical_name.clone(),
                kind: candidate.kind.clone(),
            };
            self.ensure_known_node(
                &candidate.entity_id,
                &candidate.canonical_name,
                candidate.kind.clone(),
            );
            self.add_candidate(
                mention.mention_id.0,
                ResolutionCandidate {
                    target_key: target_key(&target),
                    target,
                    action: AtlasIdentityReceiptAction::AliasOfKnown,
                    score: candidate.score,
                    evidence: small_evidence(
                        "gliner_linker",
                        candidate.score,
                        &candidate.evidence_note,
                    ),
                    rationale: "linker score ranks this saved entity as the best identity"
                        .to_owned(),
                    rank: 2,
                },
            );
            self.add_edge(
                mention_node_id(mention.mention_id.0),
                known_node_id(&candidate.entity_id.0),
                IdentityEdgeKind::LinkerCandidate,
                candidate.score,
                "linker".to_owned(),
            );
        }
    }

    fn ingest_mention_graph(&mut self) {
        for edge in &self.input.mention_graph.edges {
            if !self.mentions_by_id.contains_key(&edge.left.0)
                || !self.mentions_by_id.contains_key(&edge.right.0)
            {
                continue;
            }
            self.add_edge(
                mention_node_id(edge.left.0),
                mention_node_id(edge.right.0),
                IdentityEdgeKind::MentionGraph,
                edge.weight,
                format!("{:?}", edge.kind),
            );
            if matches!(
                edge.kind,
                MentionEdgeKind::SameNormalizedSurface
                    | MentionEdgeKind::KnownAliasMatch
                    | MentionEdgeKind::ModelLabelCompatibility
            ) {
                self.propagate_known_candidate(edge.left.0, edge.right.0, edge.weight);
                self.propagate_known_candidate(edge.right.0, edge.left.0, edge.weight);
            }
        }
    }

    fn finalize(mut self) -> IdentityResolutionDag {
        let split_mentions = self.emit_split_receipts();
        let mut local_groups = BTreeMap::<String, LocalDecisionGroup>::new();
        let mut ids = self.mentions_by_id.keys().copied().collect::<Vec<_>>();
        ids.sort_unstable();
        for id in ids {
            if split_mentions.contains(&id) {
                continue;
            }
            let Some(mention) = self.mentions_by_id.get(&id).copied() else {
                continue;
            };
            let sorted = self.sorted_candidates(id);
            let Some(top) = sorted.first() else {
                self.emit_unresolved_identity_receipt(
                    mention,
                    0.50,
                    "no stronger saved identity candidate",
                    "reference mention lacked a safe document coreference antecedent",
                );
                continue;
            };
            if top.action == AtlasIdentityReceiptAction::Defer {
                self.emit_defer_receipt(mention, top.score, &top.rationale);
                continue;
            }
            if should_defer(top, sorted.get(1)) {
                let runner = sorted.get(1).expect("runner-up checked by should_defer");
                let rationale = format!(
                    "identity candidates are too close: {} {:.3} vs {} {:.3}",
                    top.target_key, top.score, runner.target_key, runner.score
                );
                self.emit_defer_receipt(mention, top.score, &rationale);
                continue;
            }
            match &top.target {
                AtlasIdentityTargetSummary::KnownEntity { .. }
                    if top.score >= KNOWN_ACCEPT_THRESHOLD =>
                {
                    self.receipt_for_candidate(mention, top);
                }
                AtlasIdentityTargetSummary::RunLocalEntity { key, display, kind }
                    if top.score >= LOCAL_ACCEPT_THRESHOLD =>
                {
                    local_groups
                        .entry(top.target_key.clone())
                        .or_default()
                        .push(
                            id,
                            mention.surface.as_str(),
                            top.score,
                            top.action,
                            AtlasIdentityTargetSummary::RunLocalEntity {
                                key: key.clone(),
                                display: display.clone(),
                                kind: kind.clone(),
                            },
                            top.evidence.iter().cloned(),
                        );
                }
                AtlasIdentityTargetSummary::NewEntity { .. } => {
                    self.receipt_for_candidate(mention, top)
                }
                _ => self.emit_defer_receipt(
                    mention,
                    top.score,
                    "best identity candidate stayed below threshold",
                ),
            }
        }
        for group in local_groups.into_values() {
            if group.mention_ids.len() > 1 {
                self.emit_group_receipt(
                    group.action,
                    group.mention_ids,
                    group.surface,
                    group.target,
                    group.confidence,
                    group.evidence,
                    "run-local mentions cluster into one provisional identity",
                );
            } else if let Some(id) = group.mention_ids.first().copied() {
                self.emit_single_local_group_receipt(id, group.confidence);
            }
        }
        let receipts = self.receipts.clone();
        let summary = summarize(self.nodes.len(), self.edges.len(), &receipts);
        IdentityResolutionDag {
            nodes: self.nodes,
            edges: self.edges,
            receipts,
            summary,
        }
    }

    fn emit_split_receipts(&mut self) -> BTreeSet<u64> {
        let mut split_mentions = BTreeSet::new();
        let groups = self.surface_mentions.clone();
        for (key, ids) in groups {
            if ids.len() < 2 {
                continue;
            }
            let mut known_targets = BTreeSet::new();
            for id in &ids {
                if let Some(candidates) = self.candidates.get(id) {
                    for candidate in candidates.values() {
                        if matches!(
                            candidate.target,
                            AtlasIdentityTargetSummary::KnownEntity { .. }
                        ) && candidate.score >= KNOWN_ACCEPT_THRESHOLD
                        {
                            known_targets.insert(candidate.target_key.clone());
                        }
                    }
                }
            }
            let kind_conflict = self
                .surface_entries
                .get(&key)
                .is_some_and(|entry| entry.conflict);
            if known_targets.len() > 1 || kind_conflict {
                split_mentions.extend(ids.iter().copied());
                let surface = self
                    .surface_entries
                    .get(&key)
                    .map(|entry| entry.display.clone())
                    .unwrap_or_else(|| key.clone());
                self.emit_group_receipt(
                    AtlasIdentityReceiptAction::Split,
                    ids.iter().copied().collect(),
                    surface,
                    AtlasIdentityTargetSummary::Deferred,
                    0.74,
                    vec![evidence(
                        "identity_conflict",
                        0.74,
                        "same surface has incompatible identity evidence",
                    )],
                    "same surface must remain split until a linker or user resolves it",
                );
            }
        }
        split_mentions
    }

    fn sorted_candidates(&self, mention_id: u64) -> Vec<ResolutionCandidate> {
        let mut candidates = self
            .candidates
            .get(&mention_id)
            .map(|inner| inner.values().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        candidates.sort_by(candidate_order);
        candidates
    }

    fn add_candidate(&mut self, mention_id: u64, candidate: ResolutionCandidate) {
        let inner = self.candidates.entry(mention_id).or_default();
        inner
            .entry(candidate.target_key.clone())
            .and_modify(|current| current.merge(&candidate))
            .or_insert(candidate);
    }

    fn add_defer_candidate(&mut self, mention: &MentionPacket, score: f32, note: &str) {
        let target = AtlasIdentityTargetSummary::Deferred;
        let score = score.min(0.54);
        self.add_candidate(
            mention.mention_id.0,
            ResolutionCandidate {
                target_key: target_key(&target),
                target,
                action: AtlasIdentityReceiptAction::Defer,
                score,
                evidence: small_evidence("defer", score, note),
                rationale: note.to_owned(),
                rank: 9,
            },
        );
    }

    fn propagate_known_candidate(&mut self, source_id: u64, target_id: u64, weight: f32) {
        let Some(candidates) = self.candidates.get(&source_id).cloned() else {
            return;
        };
        for candidate in candidates.into_values() {
            if !matches!(
                candidate.target,
                AtlasIdentityTargetSummary::KnownEntity { .. }
            ) {
                continue;
            }
            let mut propagated = candidate.clone();
            propagated.score = (candidate.score * weight * 0.82).min(0.76);
            propagated.rank += 1;
            propagated.evidence.push(evidence(
                "mention_graph",
                propagated.score,
                "neighboring mention carries compatible known identity",
            ));
            self.add_candidate(target_id, propagated);
        }
    }

    fn receipt_for_candidate(&mut self, mention: &MentionPacket, candidate: &ResolutionCandidate) {
        self.emit_group_receipt(
            candidate.action,
            vec![mention.mention_id.0],
            mention.surface.to_string(),
            candidate.target.clone(),
            candidate.score,
            candidate.evidence.iter().cloned().collect(),
            &candidate.rationale,
        );
    }

    fn emit_defer_receipt(&mut self, mention: &MentionPacket, confidence: f32, rationale: &str) {
        self.emit_group_receipt(
            AtlasIdentityReceiptAction::Defer,
            vec![mention.mention_id.0],
            mention.surface.to_string(),
            AtlasIdentityTargetSummary::Deferred,
            confidence,
            vec![evidence("identity_defer", confidence, rationale)],
            rationale,
        );
    }

    fn emit_new_entity_receipt(
        &mut self,
        mention: &MentionPacket,
        confidence: f32,
        rationale: &str,
    ) {
        let target = AtlasIdentityTargetSummary::NewEntity {
            key: surface_key(mention.surface.as_str()),
            display: mention.surface.to_string(),
            kind: best_entity_kind(mention).map(|kind| format!("{kind:?}")),
        };
        self.emit_group_receipt(
            AtlasIdentityReceiptAction::NewEntity,
            vec![mention.mention_id.0],
            mention.surface.to_string(),
            target,
            confidence,
            vec![evidence("identity_new", confidence, rationale)],
            rationale,
        );
    }

    fn emit_group_receipt(
        &mut self,
        action: AtlasIdentityReceiptAction,
        mut mention_ids: Vec<u64>,
        surface: String,
        target: AtlasIdentityTargetSummary,
        confidence: f32,
        evidence: Vec<AtlasAliasEvidence>,
        rationale: &str,
    ) {
        mention_ids.sort_unstable();
        mention_ids.dedup();
        self.ensure_target_node(&target, &mention_ids);
        let receipt_id = receipt_id(
            self.input.document_id,
            action,
            &mention_ids,
            &target,
            &surface,
        );
        self.receipts.push(AtlasIdentityReceiptSummary {
            receipt_id,
            document_id: DocumentId(self.input.document_id.to_owned()),
            action,
            mention_ids: mention_ids
                .iter()
                .map(|id| MentionId(id.to_string()))
                .collect(),
            surface,
            target,
            confidence: confidence.clamp(0.0, 1.0),
            reversible: true,
            evidence,
            rationale: rationale.to_owned(),
        });
    }

    fn ensure_target_node(&mut self, target: &AtlasIdentityTargetSummary, mention_ids: &[u64]) {
        match target {
            AtlasIdentityTargetSummary::KnownEntity {
                entity_id,
                canonical_name,
                kind,
            } => self.ensure_known_node(entity_id, canonical_name, kind.clone()),
            AtlasIdentityTargetSummary::RunLocalEntity { .. }
            | AtlasIdentityTargetSummary::NewEntity { .. } => {
                self.ensure_local_node(target, mention_ids)
            }
            AtlasIdentityTargetSummary::Deferred => self.push_node(IdentityNode {
                node_id: "deferred".to_owned(),
                kind: IdentityNodeKind::DeferredCase,
                label: "Deferred identity review".to_owned(),
                entity_kind: None,
                mention_ids: SmallVec::new(),
            }),
        }
    }

    fn ensure_known_node(&mut self, entity_id: &EntityId, label: &str, kind: Option<EntityKind>) {
        self.push_node(IdentityNode {
            node_id: known_node_id(&entity_id.0),
            kind: IdentityNodeKind::KnownEntity,
            label: label.to_owned(),
            entity_kind: kind,
            mention_ids: SmallVec::new(),
        });
    }

    fn ensure_local_node(&mut self, target: &AtlasIdentityTargetSummary, ids: &[u64]) {
        self.push_node(IdentityNode {
            node_id: target_node_id(target),
            kind: IdentityNodeKind::RunLocalEntity,
            label: target_display(target),
            entity_kind: None,
            mention_ids: ids.iter().copied().collect(),
        });
    }

    fn push_node(&mut self, node: IdentityNode) {
        if self.node_ids.insert(node.node_id.clone()) {
            self.nodes.push(node);
        }
    }

    fn add_edge(
        &mut self,
        left: String,
        right: String,
        kind: IdentityEdgeKind,
        weight: f32,
        evidence_ref: String,
    ) {
        let key = format!("{left}|{right}|{kind:?}|{evidence_ref}");
        if !self.edge_keys.insert(key) {
            return;
        }
        let mut evidence_refs = SmallVec::new();
        evidence_refs.push(evidence_ref);
        self.edges.push(IdentityEdge {
            left,
            right,
            kind,
            weight: weight.clamp(0.0, 1.0),
            evidence_refs,
        });
    }

    fn known_ref_target(
        &self,
        mention: &MentionPacket,
    ) -> Option<(EntityId, String, Option<EntityKind>)> {
        let MentionEntityRef::Known(entity_id) = mention.entity_ref.as_ref()? else {
            return None;
        };
        let (entity_id, canonical_name, kind) = self.registry_target_or_fallback(&entity_id.0);
        Some((entity_id, canonical_name, kind))
    }

    fn registry_target_or_fallback(
        &self,
        entity_id: &str,
    ) -> (EntityId, String, Option<EntityKind>) {
        if let Some(entity) = self.registry_by_id.get(entity_id) {
            return (
                entity.entity_id.clone(),
                entity.canonical_name.clone(),
                entity.kind.clone(),
            );
        }
        (EntityId(entity_id.to_owned()), entity_id.to_owned(), None)
    }

    fn local_target(&self, key: &str, mention: &MentionPacket) -> AtlasIdentityTargetSummary {
        let (display, kind) = self
            .surface_entries
            .get(key)
            .map(|entry| (entry.display.clone(), entry.kind.clone()))
            .unwrap_or_else(|| (mention.surface.to_string(), None));
        AtlasIdentityTargetSummary::RunLocalEntity {
            key: key.to_owned(),
            display,
            kind,
        }
    }
}
