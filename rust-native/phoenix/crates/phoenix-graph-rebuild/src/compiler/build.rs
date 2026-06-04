use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};
use phoenix_types::{EntityId, TextRange};

use super::commitment::score_fact_bundle_commitments;
use super::compression::compress_fact_bundles;
use super::ids::{
    anchor_evidence_id, atom_id, entity_atom_id, event_evidence_id, mention_evidence_id,
};
use super::prepared::prepared_artifacts;
use super::projection::{legacy_projections, ProjectionProvenance};
use super::relationship::{legacy_relationship_keys, relationship_artifacts};
use super::types::{
    EvidenceAnchor, EvidenceKind, FactLane, FactRole, GraphAtom, GraphAtomKind,
    GraphCompileReceipts, GraphCompilerInput, GraphCompilerOutput, ProjectedGraphEdge,
    RelationFact,
};
use super::verify::verify_graph_compile_output;
use crate::types::{
    GraphAnchor, GraphCalendarRegistryBridgeSummary, GraphCalendarRegistryReceipt, GraphChunk,
    GraphEvent, GraphMemoryState, GraphMention, GraphNode, GraphScopeKind, GraphTemporalEdge,
};

pub fn compile_graph_snapshot(input: GraphCompilerInput<'_>) -> GraphCompilerOutput {
    let mut build = CompilerBuild::new(input.scope_kind, input.scope_id, input.built_at);
    build.documents(input.note_ids);
    build.chunks(input.chunks);
    build.mentions(input.mentions);
    prepared_artifacts(
        &mut build.output,
        &mut build.evidence_seen,
        input.note_ids.first().cloned(),
        input.surface_hits,
        input.mention_graph,
        input.lens_frames,
    );
    build.entity_anchors(input.entity_anchors);
    build.nodes(input.nodes);
    build.events(input.events);
    build.memory_states(input.memory_state);
    relationship_artifacts(
        &mut build.output,
        &mut build.evidence_seen,
        &mut build.relation_by_edge,
        input.relationships,
    );
    build.story_edges(
        input.temporal_edges,
        FactLane::TemporalFact,
        "source",
        "target",
    );
    build.story_edges(input.causal_edges, FactLane::CausalFact, "cause", "effect");
    build.calendar_registry(input.calendar_registry);
    legacy_relationship_keys(&mut build.relation_by_edge, input.relationships);
    legacy_projections(
        &mut build.output,
        input.legacy_edges,
        &build.relation_by_edge,
    );
    score_fact_bundle_commitments(&mut build.output, input.bundle_commitment);
    compress_fact_bundles(&mut build.output, input.bundle_compression);
    let mut output = build.finish();
    output.receipts = verify_graph_compile_output(&output);
    output
}

struct CompilerBuild {
    output: GraphCompilerOutput,
    evidence_seen: HashSet<CompactString>,
    relation_by_edge: HashMap<CompactString, ProjectionProvenance>,
}

impl CompilerBuild {
    fn new(scope_kind: GraphScopeKind, scope_id: &str, built_at: u64) -> Self {
        let mut build = Self {
            output: GraphCompilerOutput {
                schema_version: "phoenix-graph-compiler/v1".into(),
                scope_kind,
                scope_id: scope_id.into(),
                built_at,
                atoms: Vec::new(),
                evidence_anchors: Vec::new(),
                bundles: Vec::new(),
                facts: Vec::new(),
                roles: Vec::new(),
                projected_edges: Vec::new(),
                receipts: GraphCompileReceipts::default(),
            },
            evidence_seen: HashSet::new(),
            relation_by_edge: HashMap::new(),
        };
        build.lane_roots();
        build
    }

    fn documents(&mut self, note_ids: &[CompactString]) {
        for note_id in note_ids {
            self.atom(
                GraphAtomKind::Document,
                atom_id("document", note_id),
                note_id.clone(),
                format_compact!("Document {}", note_id),
                Some(note_id.clone()),
                None,
                None,
                Vec::new(),
            );
            self.atom(
                GraphAtomKind::DocumentRoot,
                atom_id("documentRoot", note_id),
                note_id.clone(),
                format_compact!("Document root {}", note_id),
                Some(note_id.clone()),
                None,
                None,
                Vec::new(),
            );
        }
    }

    fn lane_roots(&mut self) {
        for lane in compiler_lanes() {
            let source_id = format_compact!("{}:{:?}", self.output.scope_id, lane);
            self.atom(
                GraphAtomKind::LaneRoot,
                atom_id("laneRoot", &source_id),
                source_id,
                format_compact!("{:?} root", lane),
                None,
                None,
                None,
                Vec::new(),
            );
        }
    }

    fn chunks(&mut self, chunks: &[GraphChunk]) {
        for chunk in chunks {
            self.atom(
                GraphAtomKind::Chunk,
                atom_id("chunk", &chunk.id),
                chunk.id.clone(),
                format_compact!("Chunk {}", chunk.ordinal + 1),
                Some(chunk.note_id.clone()),
                Some(chunk.id.clone()),
                None,
                Vec::new(),
            );
        }
    }

    fn mentions(&mut self, mentions: &[GraphMention]) {
        for mention in mentions
            .iter()
            .filter(|mention| mention.status != "dropped")
        {
            self.evidence(
                mention_evidence_id(&mention.id),
                EvidenceKind::MentionPacket,
                Some(mention.note_id.clone()),
                mention.chunk_id.clone(),
                mention.id.clone(),
                Some(TextRange {
                    start: mention.source_start,
                    end: mention.source_end,
                }),
                mention.confidence,
            );
        }
    }

    fn entity_anchors(&mut self, anchors: &[GraphAnchor]) {
        for anchor in anchors {
            let evidence_id = anchor_evidence_id(&anchor.id);
            self.evidence(
                evidence_id.clone(),
                EvidenceKind::SourceSpan,
                Some(anchor.note_id.clone()),
                anchor.chunk_id.clone(),
                anchor.id.clone(),
                Some(TextRange {
                    start: anchor.source_start,
                    end: anchor.source_end,
                }),
                anchor.confidence,
            );
            self.atom(
                GraphAtomKind::EvidenceAnchor,
                evidence_id.clone(),
                anchor.id.clone(),
                anchor.surface.clone(),
                Some(anchor.note_id.clone()),
                anchor.chunk_id.clone(),
                Some(anchor.entity_id.clone()),
                vec![evidence_id],
            );
        }
    }

    fn nodes(&mut self, nodes: &[GraphNode]) {
        for node in nodes {
            let kind = if node.kind.eq_ignore_ascii_case("concept") {
                GraphAtomKind::Concept
            } else {
                GraphAtomKind::Entity
            };
            self.atom(
                kind,
                entity_atom_id(&node.entity_id),
                node.entity_id.0.as_str().into(),
                node.label.clone(),
                None,
                None,
                Some(node.entity_id.clone()),
                node.anchor_ids.iter().map(anchor_evidence_id).collect(),
            );
        }
    }

    fn events(&mut self, events: &[GraphEvent]) {
        for event in events {
            let event_atom = atom_id("event", &event.id);
            let evidence_id = event_evidence_id(&event.id);
            self.evidence(
                evidence_id.clone(),
                EvidenceKind::EventReference,
                Some(event.note_id.clone()),
                event.chunk_id.clone(),
                event.id.clone(),
                None,
                event.confidence,
            );
            self.atom(
                GraphAtomKind::Event,
                event_atom,
                event.id.clone(),
                event.label.clone(),
                Some(event.note_id.clone()),
                event.chunk_id.clone(),
                event.entity_ids.first().cloned(),
                vec![evidence_id],
            );
        }
    }

    fn memory_states(&mut self, states: &[GraphMemoryState]) {
        for state in states {
            self.atom(
                GraphAtomKind::State,
                atom_id("state", &state.id),
                state.id.clone(),
                state.key.clone(),
                state.note_id.clone(),
                None,
                Some(state.entity_id.clone()),
                state.evidence_ids.iter().map(anchor_evidence_id).collect(),
            );
            let fact_id = format_compact!("fact:memory:{}", state.id);
            let evidence = self.ensure_evidence_ids(&state.evidence_ids, EvidenceKind::SourceSpan);
            self.fact(
                fact_id.clone(),
                FactLane::MemoryState,
                state.key.clone(),
                state.id.clone(),
                "accepted".into(),
                evidence.clone(),
                0.72,
            );
            self.role(&fact_id, "subject", entity_atom_id(&state.entity_id), 0.72);
            self.role(&fact_id, "state", atom_id("state", &state.id), 0.72);
            self.evidence_roles(&fact_id, &evidence, 0.72);
        }
    }

    fn story_edges(
        &mut self,
        edges: &[GraphTemporalEdge],
        lane: FactLane,
        left_role: &str,
        right_role: &str,
    ) {
        for edge in edges {
            let fact_id = format_compact!("fact:{:?}:{}", lane, edge.id);
            let evidence =
                self.ensure_evidence_ids(&edge.evidence_ids, EvidenceKind::EventReference);
            self.fact(
                fact_id.clone(),
                lane,
                edge.relation_type.clone(),
                edge.id.clone(),
                "accepted".into(),
                evidence.clone(),
                edge.confidence,
            );
            self.role(
                &fact_id,
                left_role,
                atom_id("event", &edge.source_id),
                edge.confidence,
            );
            self.role(
                &fact_id,
                right_role,
                atom_id("event", &edge.target_id),
                edge.confidence,
            );
            self.evidence_roles(&fact_id, &evidence, edge.confidence);
            self.projection(
                format_compact!("projection:{:?}:{}", lane, edge.id),
                atom_id("event", &edge.source_id),
                atom_id("event", &edge.target_id),
                edge.relation_type.clone(),
                "legacyBinary".into(),
                Some(fact_id),
                edge.confidence,
            );
        }
    }

    fn calendar_registry(&mut self, summary: Option<&GraphCalendarRegistryBridgeSummary>) {
        let Some(summary) = summary else {
            return;
        };
        for receipt in summary.receipts.iter().filter(|receipt| {
            receipt.status == "accepted_temporal_receipt" && !receipt.mutation_allowed
        }) {
            self.calendar_time_anchor(receipt);
        }
    }

    fn calendar_time_anchor(&mut self, receipt: &GraphCalendarRegistryReceipt) {
        let evidence_id = format_compact!("evidence:calendar:{}", receipt.id);
        let note_id = receipt.source_note_ids.first().cloned();
        self.evidence(
            evidence_id.clone(),
            EvidenceKind::CalendarRegistry,
            note_id.clone(),
            None,
            receipt.id.clone(),
            None,
            0.86,
        );
        let atom_id = receipt
            .affected_graph_atoms
            .first()
            .cloned()
            .unwrap_or_else(|| atom_id("timeAnchor", &receipt.calendar_anchor_id));
        self.atom(
            GraphAtomKind::TimeAnchor,
            atom_id,
            receipt.calendar_anchor_id.clone(),
            receipt.display_date.clone(),
            note_id,
            None,
            None,
            vec![evidence_id],
        );
    }

    fn ensure_evidence_ids(
        &mut self,
        source_ids: &[CompactString],
        fallback_kind: EvidenceKind,
    ) -> Vec<CompactString> {
        source_ids
            .iter()
            .map(|source_id| {
                if self.evidence_seen.contains(&anchor_evidence_id(source_id)) {
                    anchor_evidence_id(source_id)
                } else if self.evidence_seen.contains(&event_evidence_id(source_id)) {
                    event_evidence_id(source_id)
                } else {
                    let id = anchor_evidence_id(source_id);
                    self.evidence(
                        id.clone(),
                        fallback_kind,
                        None,
                        None,
                        source_id.clone(),
                        None,
                        0.62,
                    );
                    id
                }
            })
            .collect()
    }

    fn evidence_roles(
        &mut self,
        fact_id: &CompactString,
        evidence: &[CompactString],
        confidence: f32,
    ) {
        for evidence_id in evidence {
            self.role(fact_id, "evidence", evidence_id.clone(), confidence);
        }
    }

    fn fact(
        &mut self,
        id: CompactString,
        lane: FactLane,
        predicate: CompactString,
        source_record_id: CompactString,
        status: CompactString,
        evidence_ids: Vec<CompactString>,
        confidence: f32,
    ) {
        self.atom(
            GraphAtomKind::RelationFact,
            atom_id("relationFact", &id),
            id.clone(),
            predicate.clone(),
            None,
            None,
            None,
            evidence_ids.clone(),
        );
        self.output.facts.push(RelationFact {
            id,
            lane,
            predicate,
            source_record_id,
            status,
            evidence_ids,
            confidence,
        });
    }

    fn role(
        &mut self,
        fact_id: &CompactString,
        role: &str,
        atom_id: CompactString,
        confidence: f32,
    ) {
        self.output.roles.push(FactRole {
            fact_id: fact_id.clone(),
            role: role.into(),
            atom_id,
            confidence,
        });
    }

    #[allow(clippy::too_many_arguments)]
    fn atom(
        &mut self,
        kind: GraphAtomKind,
        id: CompactString,
        source_id: CompactString,
        label: CompactString,
        note_id: Option<CompactString>,
        chunk_id: Option<CompactString>,
        entity_id: Option<EntityId>,
        evidence_ids: Vec<CompactString>,
    ) {
        self.output.atoms.push(GraphAtom {
            id,
            kind,
            source_id,
            label,
            note_id,
            chunk_id,
            entity_id,
            evidence_ids,
        });
    }

    fn evidence(
        &mut self,
        id: CompactString,
        kind: EvidenceKind,
        note_id: Option<CompactString>,
        chunk_id: Option<CompactString>,
        source_id: CompactString,
        source_range: Option<TextRange>,
        confidence: f32,
    ) {
        if !self.evidence_seen.insert(id.clone()) {
            return;
        }
        self.output.evidence_anchors.push(EvidenceAnchor {
            id,
            kind,
            note_id,
            chunk_id,
            source_range,
            source_id,
            confidence,
        });
    }

    fn projection(
        &mut self,
        id: CompactString,
        source_id: CompactString,
        target_id: CompactString,
        edge_type: CompactString,
        projection_kind: CompactString,
        source_fact_id: Option<CompactString>,
        confidence: f32,
    ) {
        self.output.projected_edges.push(ProjectedGraphEdge {
            id,
            source_id,
            target_id,
            edge_type,
            projection_kind,
            source_fact_id,
            source_bundle_id: None,
            confidence,
        });
    }

    fn finish(self) -> GraphCompilerOutput {
        self.output
    }
}

fn compiler_lanes() -> [FactLane; 11] {
    [
        FactLane::DocumentSpine,
        FactLane::ChunkSpine,
        FactLane::EntityAnchor,
        FactLane::RelationshipFact,
        FactLane::CooccurrenceWeak,
        FactLane::EventIdentity,
        FactLane::TemporalFact,
        FactLane::CausalFact,
        FactLane::MemoryState,
        FactLane::EntityLinker,
        FactLane::AnchorEvidence,
    ]
}
