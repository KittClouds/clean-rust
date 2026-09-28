//! Mention Graph Builder — links mention evidence into a graph.
//!
//! Nodes are MentionPackets. Edges connect mentions that might refer to the
//! same entity: same normalized surface, known alias, fuzzy match, dependency
//! links, speaker continuity, pronoun candidates, nearby repetition.

use rustc_hash::FxHashMap;
use smallvec::SmallVec;

use crate::types::{LocalMentionId, MentionKind, MentionPacket};
use phoenix_types::TextRange;

// ---------------------------------------------------------------------------
// Edge types
// ---------------------------------------------------------------------------

/// Kind of evidence linking two mentions.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum MentionEdgeKind {
    SameNormalizedSurface,
    KnownAliasMatch,
    FuzzyAliasMatch,
    Apposition,
    DependencyCoreArgument,
    SpeakerContinuity,
    PronounCandidate,
    NearbyRepetition,
    ModelLabelCompatibility,
}

/// An edge in the mention graph.
#[derive(Clone, Debug)]
pub struct MentionEdge {
    pub left: LocalMentionId,
    pub right: LocalMentionId,
    pub kind: MentionEdgeKind,
    pub weight: f32,
    pub evidence: SmallVec<[TextRange; 2]>,
}

// ---------------------------------------------------------------------------
// MentionGraph
// ---------------------------------------------------------------------------

/// Graph over mention evidence.
#[derive(Clone, Debug, Default)]
pub struct MentionGraph {
    pub edges: Vec<MentionEdge>,
}

impl MentionGraph {
    /// Number of edges.
    #[inline]
    pub fn edge_count(&self) -> usize {
        self.edges.len()
    }

    /// All edges incident to a mention.
    pub fn edges_for(&self, id: LocalMentionId) -> Vec<&MentionEdge> {
        self.edges
            .iter()
            .filter(|e| e.left == id || e.right == id)
            .collect()
    }
}

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

/// Max sentence distance for cross-sentence same-surface edges.
const CROSS_SENTENCE_WINDOW: u32 = 8;

/// Builds the mention graph from finalized packets.
pub struct MentionGraphBuilder;

impl MentionGraphBuilder {
    /// Build edges from a set of finalized mention packets.
    pub fn build(packets: &[MentionPacket]) -> MentionGraph {
        let mut edges = Vec::new();

        // Index: normalized surface -> list of packet indices.
        let mut surface_index = FxHashMap::<&str, SmallVec<[usize; 8]>>::default();
        for (i, p) in packets.iter().enumerate() {
            surface_index
                .entry(p.normalized.as_str())
                .or_default()
                .push(i);
        }

        // Same-normalized-surface edges (within cross-sentence window).
        for (_surface, indices) in &surface_index {
            if indices.len() < 2 {
                continue;
            }
            let mut indices = indices.iter().copied().collect::<Vec<_>>();
            indices.sort_by_key(|idx| {
                let packet = &packets[*idx];
                (packet.sentence_index, packet.range.start, packet.range.end)
            });
            for (a_pos, &a_idx) in indices.iter().enumerate() {
                let a = &packets[a_idx];
                for &b_idx in indices.iter().skip(a_pos + 1) {
                    let b = &packets[b_idx];
                    if b.sentence_index > a.sentence_index + CROSS_SENTENCE_WINDOW {
                        break;
                    }
                    let sent_dist = a.sentence_index.abs_diff(b.sentence_index);
                    if sent_dist <= CROSS_SENTENCE_WINDOW {
                        let weight = 1.0 / (1.0 + sent_dist as f32);
                        edges.push(MentionEdge {
                            left: a.mention_id,
                            right: b.mention_id,
                            kind: MentionEdgeKind::SameNormalizedSurface,
                            weight,
                            evidence: SmallVec::from_buf([a.range, b.range]),
                        });
                    }
                }
            }
        }

        // Nearby-repetition edges (different surface, same sentence).
        let by_sentence = packet_indices_by_sentence(packets);
        for sentence_packets in by_sentence {
            if sentence_packets.len() < 2 {
                continue;
            }
            for (a_pos, &a_idx) in sentence_packets.iter().enumerate() {
                let a = &packets[a_idx];
                if a.mention_kind == MentionKind::Pronoun {
                    continue;
                }
                for &b_idx in sentence_packets.iter().skip(a_pos + 1) {
                    let b = &packets[b_idx];
                    if b.mention_kind == MentionKind::Pronoun {
                        continue;
                    }
                    if a.normalized != b.normalized
                        && a.entity_ref.is_some()
                        && a.entity_ref == b.entity_ref
                    {
                        edges.push(MentionEdge {
                            left: a.mention_id,
                            right: b.mention_id,
                            kind: MentionEdgeKind::KnownAliasMatch,
                            weight: 0.85,
                            evidence: SmallVec::from_buf([a.range, b.range]),
                        });
                    }
                }
            }
        }

        // Pronoun-candidate edges.
        for (i, pronoun) in packets.iter().enumerate() {
            if pronoun.mention_kind != MentionKind::Pronoun {
                continue;
            }
            // Look backward for nearest named mention in same sentence or prior.
            for j in (0..i).rev() {
                let antecedent = &packets[j];
                if antecedent.mention_kind != MentionKind::Named {
                    continue;
                }
                let sent_dist = pronoun.sentence_index.abs_diff(antecedent.sentence_index);
                if sent_dist > 3 {
                    break;
                }
                edges.push(MentionEdge {
                    left: antecedent.mention_id,
                    right: pronoun.mention_id,
                    kind: MentionEdgeKind::PronounCandidate,
                    weight: 0.6 / (1.0 + sent_dist as f32),
                    evidence: SmallVec::from_buf([antecedent.range, pronoun.range]),
                });
                break; // Only nearest.
            }
        }

        MentionGraph { edges }
    }
}

fn packet_indices_by_sentence(packets: &[MentionPacket]) -> Vec<Vec<usize>> {
    let bucket_count = packets
        .iter()
        .map(|packet| packet.sentence_index as usize + 1)
        .max()
        .unwrap_or_default();
    let mut by_sentence = vec![Vec::new(); bucket_count];
    for (idx, packet) in packets.iter().enumerate() {
        if let Some(bucket) = by_sentence.get_mut(packet.sentence_index as usize) {
            bucket.push(idx);
        }
    }
    by_sentence
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{MentionContext, MentionSemantics, MentionStatus};
    use compact_str::CompactString;
    use smallvec::SmallVec;

    fn make_packet(
        id: u64,
        surface: &str,
        sentence: u32,
        kind: MentionKind,
        start: u32,
        end: u32,
    ) -> MentionPacket {
        MentionPacket {
            mention_id: LocalMentionId(id),
            document_id: CompactString::from("doc"),
            chunk_id: None,
            sentence_index: sentence,
            range: TextRange { start, end },
            surface: CompactString::from(surface),
            normalized: CompactString::from(surface.to_ascii_lowercase()),
            mention_kind: kind,
            label_distribution: SmallVec::new(),
            entity_ref: None,
            source_votes: SmallVec::new(),
            context: MentionContext::default(),
            syntax: None,
            semantics: MentionSemantics::default(),
            confidence: 0.8,
            status: MentionStatus::AcceptedNew,
        }
    }

    #[test]
    fn same_surface_creates_edge() {
        let packets = vec![
            make_packet(0, "Kamaria", 0, MentionKind::Named, 0, 7),
            make_packet(1, "Kamaria", 2, MentionKind::Named, 50, 57),
        ];
        let graph = MentionGraphBuilder::build(&packets);
        assert_eq!(graph.edge_count(), 1);
        assert_eq!(graph.edges[0].kind, MentionEdgeKind::SameNormalizedSurface);
    }

    #[test]
    fn no_self_edges() {
        let packets = vec![make_packet(0, "Kamaria", 0, MentionKind::Named, 0, 7)];
        let graph = MentionGraphBuilder::build(&packets);
        assert_eq!(graph.edge_count(), 0);
    }

    #[test]
    fn pronoun_candidate_edge() {
        let packets = vec![
            make_packet(0, "Adrian", 0, MentionKind::Named, 0, 6),
            make_packet(1, "he", 0, MentionKind::Pronoun, 10, 12),
        ];
        let graph = MentionGraphBuilder::build(&packets);
        assert!(graph
            .edges
            .iter()
            .any(|e| e.kind == MentionEdgeKind::PronounCandidate));
    }

    #[test]
    fn cross_sentence_window_limit() {
        let packets = vec![
            make_packet(0, "Kamaria", 0, MentionKind::Named, 0, 7),
            make_packet(1, "Kamaria", 20, MentionKind::Named, 500, 507),
        ];
        let graph = MentionGraphBuilder::build(&packets);
        // Sentence distance 20 exceeds window of 8.
        assert_eq!(graph.edge_count(), 0);
    }

    #[test]
    fn edges_for_filters_correctly() {
        let packets = vec![
            make_packet(0, "Kamaria", 0, MentionKind::Named, 0, 7),
            make_packet(1, "Kamaria", 1, MentionKind::Named, 30, 37),
            make_packet(2, "Adrian", 0, MentionKind::Named, 10, 16),
        ];
        let graph = MentionGraphBuilder::build(&packets);
        let edges_for_0 = graph.edges_for(LocalMentionId(0));
        assert!(!edges_for_0.is_empty());
        // Adrian (id=2) should have no same-surface edge with Kamaria.
        let edges_for_2 = graph.edges_for(LocalMentionId(2));
        assert!(edges_for_2.is_empty());
    }
}
