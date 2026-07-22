use crate::score::{confidence_micros, log2_lift_micros, probability_log2_micros, weighted};
use crate::scratch::PathLink;
use crate::{DiscoveryQueryError, DiscoveryScorePolicy, PathScoreReceipt, SignalContribution};
use hashbrown::HashMap;
use phoenix_discovery_community::DeterministicCommunityArtifact;
use phoenix_discovery_view::AssertedDiscoveryView;

pub(crate) struct PathScoreContext<'a> {
    pub discovery: &'a AssertedDiscoveryView,
    pub communities: &'a DeterministicCommunityArtifact,
    pub policy: &'a DiscoveryScorePolicy,
    pub ppr: &'a HashMap<u32, u64>,
    pub ppr_max: u64,
    pub narrative_time: Option<i64>,
}

impl PathScoreContext<'_> {
    pub(crate) fn score(
        &self,
        paths: &[PathLink],
        link: u32,
        seed_score_micros: u32,
        redundancy_micros: Option<u32>,
    ) -> Result<PathScoreReceipt, DiscoveryQueryError> {
        let (nodes, edges, node_len, edge_len) = trace(paths, link);
        let terminal = nodes[node_len - 1];
        let seed_relevance = available(weighted(
            probability_log2_micros(seed_score_micros),
            self.policy.seed_weight_millis,
        ));
        let ppr_value = self.ppr.get(&terminal).copied().unwrap_or(1);
        let ppr_micros = ((ppr_value.saturating_mul(1_000_000) / self.ppr_max.max(1))
            .clamp(1, 1_000_000)) as u32;
        let local_ppr_importance = available(weighted(
            probability_log2_micros(ppr_micros),
            self.policy.ppr_weight_millis,
        ));

        let normalized_asserted_confidence = self.confidence(&edges, edge_len)?;
        let bridge_strength = self.bridge(terminal)?;
        let (community_affinity, cross_community_novelty) = self.communities(&nodes, node_len)?;
        let temporal_relevance = self.temporal(&edges, edge_len)?;
        let common_relation_penalty = self.relation_penalty(&edges, edge_len)?;
        let path_length_penalty = available(
            -i64::try_from(edge_len)
                .unwrap_or(i64::MAX)
                .saturating_mul(self.policy.path_length_penalty_micros),
        );
        let selected_path_redundancy = redundancy_micros.map_or_else(unavailable, |ratio| {
            available(
                -i64::from(ratio).saturating_mul(self.policy.redundancy_penalty_micros) / 1_000_000,
            )
        });
        let evidence_quality = unavailable();
        let model_frontier_boost = unavailable();
        let contributions = [
            seed_relevance,
            local_ppr_importance,
            evidence_quality,
            normalized_asserted_confidence,
            bridge_strength,
            community_affinity,
            cross_community_novelty,
            temporal_relevance,
            model_frontier_boost,
            common_relation_penalty,
            path_length_penalty,
            selected_path_redundancy,
        ];
        let final_score_micros = contributions.iter().fold(0_i64, |sum, contribution| {
            sum.saturating_add(contribution.value_micros)
        });
        Ok(PathScoreReceipt {
            seed_relevance,
            local_ppr_importance,
            evidence_quality,
            normalized_asserted_confidence,
            bridge_strength,
            community_affinity,
            cross_community_novelty,
            temporal_relevance,
            model_frontier_boost,
            common_relation_penalty,
            path_length_penalty,
            selected_path_redundancy,
            final_score_micros,
        })
    }

    fn confidence(
        &self,
        edges: &[u32; 6],
        edge_len: usize,
    ) -> Result<SignalContribution, DiscoveryQueryError> {
        if edge_len == 0 {
            return Ok(unavailable());
        }
        let mut sum = 0_i64;
        for edge in &edges[..edge_len] {
            sum = sum.saturating_add(probability_log2_micros(confidence_micros(
                self.discovery.edge(*edge)?.confidence,
            )));
        }
        Ok(available(weighted(
            sum / edge_len as i64,
            self.policy.confidence_weight_millis,
        )))
    }

    fn bridge(&self, node: u32) -> Result<SignalContribution, DiscoveryQueryError> {
        Ok(self
            .communities
            .bridge_for_node(node)?
            .map_or_else(unavailable, |bridge| {
                available(weighted(
                    log2_lift_micros(bridge.score_micros),
                    self.policy.bridge_weight_millis,
                ))
            }))
    }

    fn communities(
        &self,
        nodes: &[u32; 7],
        node_len: usize,
    ) -> Result<(SignalContribution, SignalContribution), DiscoveryQueryError> {
        let mut seen = [None; 7];
        let mut seen_len = 0_usize;
        let mut affinity_sum = 0_i64;
        let mut affinity_count = 0_i64;
        let mut novel = 0_i64;
        let mut previous = None;
        for node in &nodes[..node_len] {
            let community = self.communities.node_community(*node)?;
            if let Some(community) = community {
                if !seen[..seen_len].contains(&Some(community)) {
                    if seen_len > 0 {
                        novel += 1;
                    }
                    seen[seen_len] = Some(community);
                    seen_len += 1;
                }
                if let Some(source) = previous.filter(|source| *source != community) {
                    if let Some(value) = normalized_affinity(self.communities, source, community)? {
                        affinity_sum += log2_lift_micros(value);
                        affinity_count += 1;
                    }
                }
                previous = Some(community);
            }
        }
        let affinity = if affinity_count == 0 {
            unavailable()
        } else {
            available(weighted(
                affinity_sum / affinity_count,
                self.policy.affinity_weight_millis,
            ))
        };
        let novelty = available(novel.saturating_mul(self.policy.novelty_bonus_micros));
        Ok((affinity, novelty))
    }

    fn temporal(
        &self,
        edges: &[u32; 6],
        edge_len: usize,
    ) -> Result<SignalContribution, DiscoveryQueryError> {
        let Some(query_time) = self.narrative_time else {
            return Ok(unavailable());
        };
        let mut available_edges = 0_u32;
        let mut matching_edges = 0_u32;
        for edge in &edges[..edge_len] {
            let temporal = self.discovery.edge(*edge)?.temporal;
            if temporal.valid_from.is_none() && temporal.valid_to.is_none() {
                continue;
            }
            available_edges += 1;
            let after_start = temporal.valid_from.is_none_or(|start| query_time >= start);
            let before_end = temporal.valid_to.is_none_or(|end| query_time <= end);
            matching_edges += u32::from(after_start && before_end);
        }
        if available_edges == 0 {
            return Ok(unavailable());
        }
        let relevance = (matching_edges.saturating_mul(1_000_000) / available_edges).max(1);
        Ok(available(weighted(
            probability_log2_micros(relevance),
            self.policy.temporal_weight_millis,
        )))
    }

    fn relation_penalty(
        &self,
        edges: &[u32; 6],
        edge_len: usize,
    ) -> Result<SignalContribution, DiscoveryQueryError> {
        if edge_len == 0 {
            return Ok(unavailable());
        }
        let mut relations = [0_u16; 6];
        for (index, edge) in edges[..edge_len].iter().enumerate() {
            relations[index] = self.discovery.edge(*edge)?.relation_code;
        }
        let mut duplicates = 0_u32;
        for index in 0..edge_len {
            duplicates += u32::from(relations[..index].contains(&relations[index]));
        }
        Ok(available(
            -i64::from(duplicates).saturating_mul(self.policy.common_relation_penalty_micros)
                / edge_len as i64,
        ))
    }
}

fn normalized_affinity(
    communities: &DeterministicCommunityArtifact,
    source: u32,
    target: u32,
) -> Result<Option<u32>, DiscoveryQueryError> {
    let row = communities.affinities(source)?;
    let mut maximum = 0_u64;
    let mut selected = None;
    for (neighbor, weight) in row.iter() {
        maximum = maximum.max(weight);
        if neighbor == target {
            selected = Some(weight);
        }
    }
    Ok(selected
        .map(|weight| ((weight.saturating_mul(1_000_000) / maximum.max(1)).min(1_000_000)) as u32))
}

fn trace(paths: &[PathLink], link: u32) -> ([u32; 7], [u32; 6], usize, usize) {
    let mut reverse_nodes = [0_u32; 7];
    let mut reverse_edges = [0_u32; 6];
    let mut node_len = 0_usize;
    let mut edge_len = 0_usize;
    let mut cursor = Some(link);
    while let Some(index) = cursor {
        let entry = paths[index as usize];
        reverse_nodes[node_len] = entry.node;
        node_len += 1;
        if let Some(edge) = entry.edge {
            reverse_edges[edge_len] = edge;
            edge_len += 1;
        }
        cursor = entry.parent;
    }
    reverse_nodes[..node_len].reverse();
    reverse_edges[..edge_len].reverse();
    (reverse_nodes, reverse_edges, node_len, edge_len)
}

fn available(value_micros: i64) -> SignalContribution {
    SignalContribution {
        available: true,
        value_micros,
    }
}

fn unavailable() -> SignalContribution {
    SignalContribution {
        available: false,
        value_micros: 0,
    }
}
