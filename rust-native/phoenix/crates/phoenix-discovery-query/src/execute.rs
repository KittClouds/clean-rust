use crate::budget::{EdgeBudget, EdgePhase};
use crate::path_score::PathScoreContext;
use crate::ppr::{collect_neighbors, run_ppr};
use crate::score::{confidence_micros, probability_log2_micros};
pub use crate::scratch::QueryScratch;
use crate::scratch::{BeamState, PathLink};
use crate::{
    BoundedSeedSink, BudgetExhaustion, CancellationPhase, CancellationProbe, DiscoveryPath,
    DiscoveryQueryError, DiscoveryScorePolicy, EdgeReceipt, NeverCancel, PathScoreReceipt,
    PreparedQueryReceipt, PreparedQueryRequest, PreparedQueryResponse, PreparedSeedResolver,
    QueryLimits, QueryStableId, SeedChannel, SeedChannelReceipt,
};
use hashbrown::HashMap;
use phoenix_discovery_community::DeterministicCommunityArtifact;
use phoenix_discovery_view::{AssertedDiscoveryView, DiscoveryRelationPolicy, DiscoveryStableId};

pub struct PreparedDiscoveryQuery<'a> {
    discovery: &'a AssertedDiscoveryView,
    communities: &'a DeterministicCommunityArtifact,
    limits: QueryLimits,
    relation_weights: [u16; 10],
    limits_digest: [u8; 32],
    score_policy: DiscoveryScorePolicy,
    score_policy_digest: [u8; 32],
}

impl<'a> PreparedDiscoveryQuery<'a> {
    pub fn prepare(
        discovery: &'a AssertedDiscoveryView,
        communities: &'a DeterministicCommunityArtifact,
        relation_policy: &DiscoveryRelationPolicy,
        score_policy: &DiscoveryScorePolicy,
        limits: QueryLimits,
    ) -> Result<Self, DiscoveryQueryError> {
        let limits = limits.validate()?;
        discovery.validate_payload()?;
        communities.validate_payload()?;
        let discovery_manifest = discovery.manifest();
        let community_manifest = communities.manifest();
        let relation_policy_digest = hex(relation_policy.digest()?);
        let score_policy_digest = score_policy.digest()?;
        if discovery_manifest.generation != community_manifest.generation
            || discovery_manifest.artifact_digest != community_manifest.source_discovery_digest
            || discovery_manifest.relation_policy_digest != relation_policy_digest
            || community_manifest.relation_policy_digest != relation_policy_digest
            || discovery_manifest.node_count != community_manifest.node_count
            || discovery_manifest.admitted_candidate_edges != 0
            || community_manifest.admitted_candidate_edges != 0
        {
            return Err(DiscoveryQueryError::Invalid(
                "prepared discovery and community authority do not match".to_owned(),
            ));
        }
        let mut relation_weights = [0_u16; 10];
        for rule in &relation_policy.families {
            relation_weights[rule.family.code() as usize] = rule.traversal_weight_millis;
        }
        Ok(Self {
            discovery,
            communities,
            limits,
            relation_weights,
            limits_digest: limits.digest()?,
            score_policy: score_policy.clone(),
            score_policy_digest,
        })
    }

    pub fn limits(&self) -> QueryLimits {
        self.limits
    }

    pub fn execute<R: PreparedSeedResolver>(
        &self,
        request: PreparedQueryRequest<'_>,
        resolver: &R,
        scratch: &mut QueryScratch,
    ) -> Result<PreparedQueryResponse, DiscoveryQueryError> {
        self.execute_with_cancellation(request, resolver, scratch, &NeverCancel)
    }

    pub fn execute_with_cancellation<R: PreparedSeedResolver>(
        &self,
        request: PreparedQueryRequest<'_>,
        resolver: &R,
        scratch: &mut QueryScratch,
        cancellation: &dyn CancellationProbe,
    ) -> Result<PreparedQueryResponse, DiscoveryQueryError> {
        self.validate_resolver(resolver)?;
        scratch.clear();
        let mut exhaustion = BudgetExhaustion::default();
        let (
            lexical_candidates,
            vector_candidates,
            invalid_seeds,
            lexical_seed_receipt,
            vector_seed_receipt,
        ) = self.resolve_seeds(&request, resolver, scratch, &mut exhaustion)?;
        let seed_receipt_digest = seed_receipt_digest(&lexical_seed_receipt, &vector_seed_receipt)?;
        scratch.pruning.seed_candidates = lexical_seed_receipt
            .examined
            .saturating_sub(lexical_seed_receipt.accepted)
            .saturating_add(
                vector_seed_receipt
                    .examined
                    .saturating_sub(vector_seed_receipt.accepted),
            );
        scratch
            .cancellation
            .check(cancellation, CancellationPhase::SeedResolution);
        let mut edge_budget = EdgeBudget::new(
            self.limits.total_examined_edges,
            self.limits.ppr_examined_edges,
        );
        let mut ppr = crate::ppr::PprStats::default();
        if !scratch.cancellation.observed() {
            self.fuse_seeds(scratch);
            ppr = run_ppr(
                self.discovery,
                &self.relation_weights,
                self.limits,
                scratch,
                &mut edge_budget,
                &mut exhaustion,
                cancellation,
            )?;
        }
        if !scratch.cancellation.observed() {
            self.run_beam(
                scratch,
                &mut edge_budget,
                &mut exhaustion,
                request.narrative_time,
                cancellation,
            )?;
        }
        let mut paths = if scratch.cancellation.observed() {
            Vec::new()
        } else {
            self.select_and_materialize(
                scratch,
                &mut exhaustion,
                request.narrative_time,
                cancellation,
            )?
        };
        if scratch.cancellation.observed() {
            paths.clear();
            scratch.pruning.path_candidates =
                scratch.candidates.len().min(u32::MAX as usize) as u32;
        }
        let discovery_manifest = self.discovery.manifest();
        let community_manifest = self.communities.manifest();
        let receipt = PreparedQueryReceipt {
            generation: discovery_manifest.generation,
            source_snapshot_id: discovery_manifest.source_snapshot_id.clone(),
            source_snapshot_digest: discovery_manifest.source_snapshot_digest.clone(),
            evidence_registry_digest: discovery_manifest.evidence_registry_digest.clone(),
            discovery_digest: discovery_manifest.artifact_digest.clone(),
            discovery_payload_digest: discovery_manifest.payload_digest.clone(),
            community_digest: community_manifest.artifact_digest.clone(),
            community_payload_digest: community_manifest.payload_digest.clone(),
            community_policy_id: community_manifest.community_policy_id.clone(),
            community_policy_version: community_manifest.community_policy_version.clone(),
            community_policy_digest: community_manifest.community_policy_digest.clone(),
            relation_policy_digest: discovery_manifest.relation_policy_digest.clone(),
            score_policy_id: self.score_policy.policy_id.clone(),
            score_policy_version: self.score_policy.policy_version.clone(),
            score_policy_digest: hex(self.score_policy_digest),
            limits_digest: hex(self.limits_digest),
            mode: self.limits.mode,
            limits: self.limits,
            lexical_candidates,
            vector_candidates,
            invalid_seed_candidates: invalid_seeds,
            lexical_seed_receipt,
            vector_seed_receipt,
            seed_receipt_digest,
            resolved_seeds: scratch.seeds.len() as u32,
            ppr_visited_vertices: ppr.visited,
            ppr_pushes: ppr.pushes,
            ppr_examined_edges: edge_budget.ppr_used(),
            beam_states: scratch.candidates.len() as u32,
            beam_examined_edges: edge_budget.beam_used(),
            total_examined_edges: edge_budget.total_used(),
            returned_paths: paths.len() as u32,
            exhaustion,
            pruning: scratch.pruning,
            cancellation: scratch.cancellation.receipt(),
            admitted_candidate_edges: 0,
            topology_writes: 0,
            fallback_used: false,
        };
        Ok(PreparedQueryResponse { paths, receipt })
    }

    fn validate_resolver<R: PreparedSeedResolver>(
        &self,
        resolver: &R,
    ) -> Result<(), DiscoveryQueryError> {
        if resolver.generation() != self.discovery.manifest().generation
            || resolver.discovery_digest() != self.discovery.manifest().artifact_digest
        {
            return Err(DiscoveryQueryError::Invalid(
                "prepared seed index authority does not match the discovery artifact".to_owned(),
            ));
        }
        Ok(())
    }

    fn resolve_seeds<R: PreparedSeedResolver>(
        &self,
        request: &PreparedQueryRequest<'_>,
        resolver: &R,
        scratch: &mut QueryScratch,
        exhaustion: &mut BudgetExhaustion,
    ) -> Result<(u32, u32, u32, SeedChannelReceipt, SeedChannelReceipt), DiscoveryQueryError> {
        let cap = usize::from(self.limits.seeds);
        let (lexical_stats, mut lexical_receipt) = {
            let mut sink = BoundedSeedSink::new(
                SeedChannel::Lexical,
                self.discovery.manifest().node_count,
                cap,
                &mut scratch.seed_hits,
            );
            let receipt = resolver.resolve_lexical(request.query, &mut sink)?;
            (sink.stats(), receipt)
        };
        let (vector_stats, mut vector_receipt) = {
            let mut sink = BoundedSeedSink::new(
                SeedChannel::Vector,
                self.discovery.manifest().node_count,
                cap,
                &mut scratch.seed_hits,
            );
            let receipt = resolver.resolve_vector(request.query_vector, &mut sink)?;
            (sink.stats(), receipt)
        };
        lexical_receipt.accepted = lexical_stats.0;
        lexical_receipt.truncated |= lexical_stats.2;
        vector_receipt.accepted = vector_stats.0;
        vector_receipt.truncated |= vector_stats.2;
        lexical_receipt.hits = scratch
            .seed_hits
            .iter()
            .filter_map(|(channel, hit)| (*channel == SeedChannel::Lexical).then_some(*hit))
            .collect();
        vector_receipt.hits = scratch
            .seed_hits
            .iter()
            .filter_map(|(channel, hit)| (*channel == SeedChannel::Vector).then_some(*hit))
            .collect();
        validate_seed_receipt(
            &lexical_receipt,
            SeedChannel::Lexical,
            self.discovery.manifest().artifact_digest.as_str(),
            self.discovery.manifest().node_count,
        )?;
        validate_seed_receipt(
            &vector_receipt,
            SeedChannel::Vector,
            self.discovery.manifest().artifact_digest.as_str(),
            self.discovery.manifest().node_count,
        )?;
        exhaustion.seed_candidates = lexical_stats.2 || vector_stats.2;
        Ok((
            lexical_stats.0,
            vector_stats.0,
            lexical_stats.1.saturating_add(vector_stats.1),
            lexical_receipt,
            vector_receipt,
        ))
    }

    fn fuse_seeds(&self, scratch: &mut QueryScratch) {
        for &(channel, hit) in &scratch.seed_hits {
            let scores = scratch.fused_seeds.entry(hit.node).or_default();
            match channel {
                SeedChannel::Lexical => scores.0 = scores.0.max(hit.score_micros),
                SeedChannel::Vector => scores.1 = scores.1.max(hit.score_micros),
            }
        }
        scratch.seeds.extend(
            scratch
                .fused_seeds
                .iter()
                .map(|(&node, &(lexical, vector))| {
                    let miss = u64::from(1_000_000 - lexical) * u64::from(1_000_000 - vector);
                    (node, 1_000_000 - (miss / 1_000_000) as u32)
                }),
        );
        scratch.seeds.sort_unstable_by(|left, right| {
            right.1.cmp(&left.1).then_with(|| {
                let left_id = self.discovery.node_identity(left.0).ok();
                let right_id = self.discovery.node_identity(right.0).ok();
                left_id
                    .map(|id| (id.hash, id.collision))
                    .cmp(&right_id.map(|id| (id.hash, id.collision)))
            })
        });
        scratch.seeds.truncate(usize::from(self.limits.seeds));
    }

    fn run_beam(
        &self,
        scratch: &mut QueryScratch,
        budget: &mut EdgeBudget,
        exhaustion: &mut BudgetExhaustion,
        narrative_time: Option<i64>,
        cancellation: &dyn CancellationProbe,
    ) -> Result<(), DiscoveryQueryError> {
        let ppr_max = scratch.reserve.values().copied().max().unwrap_or(1);
        for seed_index in 0..scratch.seeds.len() {
            if seed_index & 15 == 0
                && scratch
                    .cancellation
                    .check(cancellation, CancellationPhase::Beam)
            {
                return Ok(());
            }
            let (node, seed_score_micros) = scratch.seeds[seed_index];
            let link = scratch.paths.len() as u32;
            scratch.paths.push(PathLink {
                node,
                edge: None,
                parent: None,
            });
            let score = self
                .score_context(scratch, ppr_max, narrative_time)
                .score(&scratch.paths, link, seed_score_micros, None)?
                .final_score_micros;
            let state = BeamState {
                link,
                seed_score_micros,
                score,
            };
            scratch.beam.push(state);
            scratch.candidates.push(state);
        }
        sort_states(self.discovery, &scratch.paths, &mut scratch.beam)?;
        if scratch.beam.len() > usize::from(self.limits.beam_width) {
            let pruned = scratch.beam.len() - usize::from(self.limits.beam_width);
            scratch.pruning.beam_states = scratch
                .pruning
                .beam_states
                .saturating_add(pruned.min(u32::MAX as usize) as u32);
            scratch.beam.truncate(usize::from(self.limits.beam_width));
        }

        for _hop in 1..=self.limits.hops {
            scratch.next_beam.clear();
            let current = std::mem::take(&mut scratch.beam);
            for (state_index, state) in current.iter().copied().enumerate() {
                if state_index & 15 == 0
                    && scratch
                        .cancellation
                        .check(cancellation, CancellationPhase::Beam)
                {
                    break;
                }
                let node = scratch.paths[state.link as usize].node;
                collect_neighbors(
                    self.discovery,
                    &self.relation_weights,
                    node,
                    self.limits,
                    EdgePhase::Beam,
                    scratch,
                    budget,
                    exhaustion,
                    cancellation,
                )?;
                for neighbor_index in 0..scratch.neighbors.len() {
                    let neighbor = scratch.neighbors[neighbor_index];
                    if path_contains(&scratch.paths, state.link, neighbor.target) {
                        scratch.pruning.cycle_states =
                            scratch.pruning.cycle_states.saturating_add(1);
                        continue;
                    }
                    let link = scratch.paths.len() as u32;
                    scratch.paths.push(PathLink {
                        node: neighbor.target,
                        edge: Some(neighbor.edge),
                        parent: Some(state.link),
                    });
                    let score = state
                        .score
                        .saturating_add(probability_log2_micros(neighbor.quality_micros.max(1)))
                        .saturating_sub(self.score_policy.path_length_penalty_micros);
                    scratch.next_beam.push(BeamState {
                        link,
                        seed_score_micros: state.seed_score_micros,
                        score,
                    });
                }
                if exhaustion.total_edges || scratch.cancellation.observed() {
                    break;
                }
            }
            sort_states(self.discovery, &scratch.paths, &mut scratch.next_beam)?;
            if scratch.next_beam.len() > usize::from(self.limits.beam_width) {
                exhaustion.beam_width = true;
                let pruned = scratch.next_beam.len() - usize::from(self.limits.beam_width);
                scratch.pruning.beam_states = scratch
                    .pruning
                    .beam_states
                    .saturating_add(pruned.min(u32::MAX as usize) as u32);
                scratch
                    .next_beam
                    .truncate(usize::from(self.limits.beam_width));
            }
            for index in 0..scratch.next_beam.len() {
                let state = scratch.next_beam[index];
                let score = self
                    .score_context(scratch, ppr_max, narrative_time)
                    .score(&scratch.paths, state.link, state.seed_score_micros, None)?
                    .final_score_micros;
                scratch.next_beam[index].score = score;
            }
            sort_states(self.discovery, &scratch.paths, &mut scratch.next_beam)?;
            scratch.candidates.extend_from_slice(&scratch.next_beam);
            scratch.beam = current;
            scratch.beam.clear();
            std::mem::swap(&mut scratch.beam, &mut scratch.next_beam);
            if scratch.beam.is_empty() || exhaustion.total_edges || scratch.cancellation.observed()
            {
                break;
            }
        }
        Ok(())
    }

    fn select_and_materialize(
        &self,
        scratch: &mut QueryScratch,
        exhaustion: &mut BudgetExhaustion,
        narrative_time: Option<i64>,
        cancellation: &dyn CancellationProbe,
    ) -> Result<Vec<DiscoveryPath>, DiscoveryQueryError> {
        let mut selected = Vec::with_capacity(usize::from(self.limits.returned_paths));
        let mut selected_links = Vec::with_capacity(usize::from(self.limits.returned_paths));
        let mut used = vec![false; scratch.candidates.len()];
        let ppr_max = scratch.reserve.values().copied().max().unwrap_or(1);
        while selected.len() < usize::from(self.limits.returned_paths) {
            if scratch
                .cancellation
                .check(cancellation, CancellationPhase::Selection)
            {
                break;
            }
            let mut best: Option<(usize, i64, Option<u32>)> = None;
            for (index, is_used) in used.iter().copied().enumerate() {
                if index & 63 == 0
                    && scratch
                        .cancellation
                        .check(cancellation, CancellationPhase::Selection)
                {
                    break;
                }
                let state = scratch.candidates[index];
                if is_used {
                    continue;
                }
                let redundancy = (!selected_links.is_empty()).then(|| {
                    selected_links
                        .iter()
                        .map(|selected| path_redundancy(&scratch.paths, state.link, *selected))
                        .max()
                        .unwrap_or(0)
                });
                let penalty = redundancy.map(|ratio| {
                    i64::from(ratio).saturating_mul(self.score_policy.redundancy_penalty_micros)
                        / 1_000_000
                });
                let adjusted = state.score.saturating_sub(penalty.unwrap_or(0));
                if best
                    .as_ref()
                    .is_none_or(|(_, current, _)| adjusted > *current)
                {
                    best = Some((index, adjusted, redundancy));
                }
            }
            if scratch.cancellation.observed() {
                break;
            }
            let Some((index, _adjusted, redundancy)) = best else {
                break;
            };
            used[index] = true;
            let link = scratch.candidates[index].link;
            selected_links.push(link);
            let score = self.score_context(scratch, ppr_max, narrative_time).score(
                &scratch.paths,
                link,
                scratch.candidates[index].seed_score_micros,
                redundancy,
            )?;
            selected.push(self.materialize_path(scratch, link, score, exhaustion)?);
        }
        exhaustion.returned_paths = scratch.candidates.len() > selected.len();
        scratch.pruning.path_candidates = scratch.pruning.path_candidates.saturating_add(
            scratch
                .candidates
                .len()
                .saturating_sub(selected.len())
                .min(u32::MAX as usize) as u32,
        );
        Ok(selected)
    }

    fn materialize_path(
        &self,
        scratch: &mut QueryScratch,
        link: u32,
        score: PathScoreReceipt,
        exhaustion: &mut BudgetExhaustion,
    ) -> Result<DiscoveryPath, DiscoveryQueryError> {
        let mut links = Vec::with_capacity(self.limits.hops as usize + 1);
        let mut cursor = Some(link);
        while let Some(index) = cursor {
            let entry = scratch.paths[index as usize];
            links.push(entry);
            cursor = entry.parent;
        }
        links.reverse();
        let mut dense_nodes = Vec::with_capacity(links.len());
        let mut node_identities = Vec::with_capacity(links.len());
        let mut edges = Vec::with_capacity(links.len().saturating_sub(1));
        for link in &links {
            dense_nodes.push(link.node);
            node_identities.push(stable(self.discovery.node_identity(link.node)?));
            if let Some(edge_index) = link.edge {
                let edge = self.discovery.edge(edge_index)?;
                let evidence = self.discovery.edge_evidence(edge_index)?;
                let cap = usize::from(self.limits.evidence_per_edge);
                let evidence_truncated = evidence.len() > cap;
                exhaustion.evidence |= evidence_truncated;
                if evidence_truncated {
                    scratch.pruning.evidence_refs = scratch
                        .pruning
                        .evidence_refs
                        .saturating_add((evidence.len() - cap).min(u32::MAX as usize) as u32);
                }
                let identities = evidence
                    .iter()
                    .take(cap)
                    .map(|dense| self.discovery.evidence_identity(dense).map(stable))
                    .collect::<Result<Vec<_>, _>>()?;
                edges.push(EdgeReceipt {
                    dense_edge: edge_index,
                    identity: stable(edge.identity),
                    relation_code: edge.relation_code,
                    confidence_micros: confidence_micros(edge.confidence),
                    evidence: identities,
                    evidence_truncated,
                });
            }
        }
        let terminal = links.last().expect("beam path has at least one node");
        let terminal_community = self
            .communities
            .node_community(terminal.node)?
            .map(|community| self.communities.community_identity(community).map(stable))
            .transpose()?;
        Ok(DiscoveryPath {
            dense_nodes,
            node_identities,
            edges,
            terminal_community,
            score,
        })
    }

    fn score_context<'b>(
        &'b self,
        scratch: &'b QueryScratch,
        ppr_max: u64,
        narrative_time: Option<i64>,
    ) -> PathScoreContext<'b> {
        PathScoreContext {
            discovery: self.discovery,
            communities: self.communities,
            policy: &self.score_policy,
            ppr: &scratch.reserve,
            ppr_max,
            narrative_time,
        }
    }
}

fn path_redundancy(paths: &[PathLink], left: u32, right: u32) -> u32 {
    let (left_edges, left_len, left_terminal) = path_edges(paths, left);
    let (right_edges, right_len, right_terminal) = path_edges(paths, right);
    if left_len == 0 && right_len == 0 {
        return u32::from(left_terminal == right_terminal) * 1_000_000;
    }
    let shared = left_edges[..left_len]
        .iter()
        .filter(|edge| right_edges[..right_len].contains(edge))
        .count();
    (shared as u32).saturating_mul(1_000_000) / left_len.max(right_len).max(1) as u32
}

fn path_edges(paths: &[PathLink], link: u32) -> ([u32; 6], usize, u32) {
    let terminal = paths[link as usize].node;
    let mut edges = [0_u32; 6];
    let mut len = 0_usize;
    let mut cursor = Some(link);
    while let Some(index) = cursor {
        let entry = paths[index as usize];
        if let Some(edge) = entry.edge {
            edges[len] = edge;
            len += 1;
        }
        cursor = entry.parent;
    }
    (edges, len, terminal)
}

fn path_contains(paths: &[PathLink], link: u32, node: u32) -> bool {
    let mut cursor = Some(link);
    while let Some(index) = cursor {
        let entry = paths[index as usize];
        if entry.node == node {
            return true;
        }
        cursor = entry.parent;
    }
    false
}

fn sort_states(
    view: &AssertedDiscoveryView,
    paths: &[PathLink],
    states: &mut [BeamState],
) -> Result<(), DiscoveryQueryError> {
    let mut stable = HashMap::with_capacity(states.len());
    for state in states.iter() {
        let node = paths[state.link as usize].node;
        stable.entry(node).or_insert(view.node_identity(node)?);
    }
    states.sort_unstable_by(|left, right| {
        let left_node = paths[left.link as usize].node;
        let right_node = paths[right.link as usize].node;
        right.score.cmp(&left.score).then_with(|| {
            let left_id = stable[&left_node];
            let right_id = stable[&right_node];
            (left_id.hash, left_id.collision, left.link).cmp(&(
                right_id.hash,
                right_id.collision,
                right.link,
            ))
        })
    });
    Ok(())
}

fn stable(identity: DiscoveryStableId) -> QueryStableId {
    QueryStableId {
        hash: identity.hash,
        collision: identity.collision,
    }
}

fn hex(bytes: [u8; 32]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}

fn validate_seed_receipt(
    receipt: &SeedChannelReceipt,
    channel: SeedChannel,
    discovery_digest: &str,
    node_count: u64,
) -> Result<(), DiscoveryQueryError> {
    if receipt.channel != channel
        || receipt.index_generation == 0
        || !is_digest(&receipt.index_digest)
        || receipt.source_discovery_digest != discovery_digest
        || receipt.encoder_id.trim().is_empty()
        || receipt.encoder_version.trim().is_empty()
        || receipt.accepted as usize != receipt.hits.len()
        || receipt.hits.iter().any(|hit| {
            u64::from(hit.node) >= node_count || !(1..=1_000_000).contains(&hit.score_micros)
        })
    {
        return Err(DiscoveryQueryError::Invalid(
            "seed channel receipt is not bound to the prepared discovery authority".to_owned(),
        ));
    }
    Ok(())
}

fn is_digest(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn seed_receipt_digest(
    lexical: &SeedChannelReceipt,
    vector: &SeedChannelReceipt,
) -> Result<String, DiscoveryQueryError> {
    let bytes = serde_json::to_vec(&(lexical, vector))
        .map_err(|error| DiscoveryQueryError::Invalid(error.to_string()))?;
    Ok(hex(*blake3::hash(&bytes).as_bytes()))
}
