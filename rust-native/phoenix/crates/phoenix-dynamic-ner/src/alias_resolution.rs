//! Alias resolution turns NER surfaces into reversible identity questions.
//!
//! This layer does not mutate the atlas. It proposes known aliases, full
//! designations, spelling variants, and run-local surface joins for later
//! linker/GLiClass adjudication or user policy.

use std::cmp::Ordering;
use std::collections::BTreeMap;

use phoenix_alex::tokenize_norm;
use phoenix_types::{
    AtlasAliasEvidence, AtlasAliasProposalDecision, AtlasAliasProposalSummary,
    AtlasAliasProposalTarget, AtlasAliasRelation, DocumentId, EntityId, EntityKind, MentionId,
};

use crate::surface_memory::{
    SurfaceCandidateKind, SurfaceCandidateTarget, SurfaceMemoryEntry, SurfaceMemoryReport,
};
use crate::types::{MentionKind, MentionPacket, MentionStatus};

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AliasResolutionReport {
    pub proposals: Vec<AtlasAliasProposalSummary>,
    pub question_count: usize,
    pub known_candidate_count: usize,
    pub run_local_candidate_count: usize,
    pub deferred_count: usize,
}

pub struct AliasResolutionInput<'a> {
    pub document_id: &'a str,
    pub mentions: &'a [MentionPacket],
    pub surface_memory: &'a SurfaceMemoryReport,
    pub registry_entities: &'a [AliasRegistryEntity],
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AliasRegistryEntity {
    pub entity_id: EntityId,
    pub canonical_name: String,
    pub kind: Option<EntityKind>,
    pub aliases: Vec<String>,
}

pub fn resolve_aliases(input: &AliasResolutionInput<'_>) -> AliasResolutionReport {
    let registry = RegistryIndex::new(input.registry_entities);
    let surface_entries = input
        .surface_memory
        .entries
        .iter()
        .map(|entry| (entry.key.as_str(), entry))
        .collect::<BTreeMap<_, _>>();
    let surface_edges = input.surface_memory.candidate_edges.iter().fold(
        BTreeMap::<u64, Vec<_>>::new(),
        |mut acc, edge| {
            acc.entry(edge.mention_id).or_default().push(edge);
            acc
        },
    );

    let mut report = AliasResolutionReport::default();
    let mut by_case = BTreeMap::<String, AtlasAliasProposalSummary>::new();

    for mention in input.mentions.iter().filter(alias_eligible_mention) {
        let surface_key = alias_key(mention.surface.as_str());
        if surface_key.is_empty() {
            continue;
        }

        let mut candidates = Vec::new();
        push_registry_candidates(mention, &surface_key, &registry, &mut candidates);
        if let Some(edges) = surface_edges.get(&mention.mention_id.0) {
            push_surface_memory_candidates(
                mention,
                &surface_key,
                edges,
                &surface_entries,
                &registry,
                &mut candidates,
            );
        }
        push_run_local_designation_candidates(
            mention,
            &surface_key,
            &surface_entries,
            &mut candidates,
        );

        let Some(proposal) = select_proposal(input.document_id, mention, candidates) else {
            continue;
        };
        let case_id = proposal.case_id.clone();
        by_case
            .entry(case_id)
            .and_modify(|current| {
                if proposal_is_better(&proposal, current) {
                    *current = proposal.clone();
                }
            })
            .or_insert(proposal);
    }

    report.proposals = by_case.into_values().collect();
    report.question_count = report.proposals.len();
    for proposal in &report.proposals {
        match &proposal.target {
            AtlasAliasProposalTarget::KnownEntity { .. } => report.known_candidate_count += 1,
            AtlasAliasProposalTarget::RunLocalSurface { .. } => {
                report.run_local_candidate_count += 1
            }
            AtlasAliasProposalTarget::Deferred | AtlasAliasProposalTarget::NewEntity => {}
        }
        if proposal.decision == AtlasAliasProposalDecision::Defer {
            report.deferred_count += 1;
        }
    }
    report
}

fn alias_eligible_mention(mention: &&MentionPacket) -> bool {
    mention.mention_kind == MentionKind::Named && mention.status != MentionStatus::Rejected
}

#[derive(Clone, Debug)]
struct RegistrySurface<'a> {
    entity: &'a AliasRegistryEntity,
    key: String,
    tokens: Vec<String>,
    is_canonical: bool,
}

#[derive(Clone, Debug, Default)]
struct RegistryIndex<'a> {
    by_id: BTreeMap<&'a str, &'a AliasRegistryEntity>,
    surfaces: Vec<RegistrySurface<'a>>,
    exact: BTreeMap<String, Vec<usize>>,
}

impl<'a> RegistryIndex<'a> {
    fn new(entities: &'a [AliasRegistryEntity]) -> Self {
        let mut index = Self::default();
        for entity in entities {
            index.by_id.insert(entity.entity_id.0.as_str(), entity);
            index.add_surface(entity, &entity.canonical_name, true);
            for alias in &entity.aliases {
                index.add_surface(entity, alias, false);
            }
        }
        index
    }

    fn add_surface(&mut self, entity: &'a AliasRegistryEntity, surface: &str, is_canonical: bool) {
        let key = alias_key(surface);
        if key.is_empty() {
            return;
        }
        let offset = self.surfaces.len();
        self.exact.entry(key.clone()).or_default().push(offset);
        self.surfaces.push(RegistrySurface {
            entity,
            tokens: tokenize_norm(surface),
            key,
            is_canonical,
        });
    }
}

#[derive(Clone, Debug)]
struct Candidate {
    relation: AtlasAliasRelation,
    target: AtlasAliasProposalTarget,
    confidence: f32,
    evidence: Vec<AtlasAliasEvidence>,
    rationale: &'static str,
    conflict: bool,
}

fn push_registry_candidates(
    mention: &MentionPacket,
    surface_key: &str,
    registry: &RegistryIndex<'_>,
    candidates: &mut Vec<Candidate>,
) {
    if let Some(entity_id) = known_entity_id(mention) {
        if let Some(entity) = registry.by_id.get(entity_id.as_str()) {
            push_known_entity_candidate(mention, surface_key, entity, candidates);
        }
    }

    if let Some(exact) = registry.exact.get(surface_key) {
        for index in exact {
            let surface = &registry.surfaces[*index];
            candidates.push(candidate_for_entity(
                mention,
                surface.entity,
                AtlasAliasRelation::ExactKnownAlias,
                0.97,
                "registryAlias",
                if surface.is_canonical {
                    "surface is already a saved canonical name"
                } else {
                    "surface is already a saved alias"
                },
                false,
            ));
        }
    }

    let mention_tokens = tokenize_norm(mention.surface.as_str());
    for surface in &registry.surfaces {
        if surface.key == surface_key {
            continue;
        }
        if let Some((relation, confidence, note)) =
            classify_registry_surface(&mention_tokens, surface_key, surface)
        {
            candidates.push(candidate_for_entity(
                mention,
                surface.entity,
                relation,
                confidence,
                "registryShape",
                note,
                false,
            ));
        }
    }
}

fn push_known_entity_candidate(
    mention: &MentionPacket,
    surface_key: &str,
    entity: &AliasRegistryEntity,
    candidates: &mut Vec<Candidate>,
) {
    let canonical_key = alias_key(&entity.canonical_name);
    if canonical_key == surface_key {
        return;
    }
    let known_alias = entity
        .aliases
        .iter()
        .any(|alias| alias_key(alias) == surface_key);
    let relation = if known_alias {
        AtlasAliasRelation::ExactKnownAlias
    } else {
        classify_known_surface(mention.surface.as_str(), &entity.canonical_name)
            .unwrap_or(AtlasAliasRelation::Codename)
    };
    let confidence = if known_alias {
        0.98
    } else {
        mention.confidence.max(0.82)
    };
    candidates.push(candidate_for_entity(
        mention,
        entity,
        relation,
        confidence,
        "mentionLink",
        "NER mention already links to this known entity",
        false,
    ));
}

fn push_surface_memory_candidates(
    mention: &MentionPacket,
    surface_key: &str,
    edges: &[&crate::surface_memory::SurfaceCandidateEdge],
    entries: &BTreeMap<&str, &SurfaceMemoryEntry>,
    registry: &RegistryIndex<'_>,
    candidates: &mut Vec<Candidate>,
) {
    for edge in edges {
        match &edge.target {
            SurfaceCandidateTarget::KnownEntity(id) => {
                let Some(entity) = registry.by_id.get(id.as_str()) else {
                    continue;
                };
                let relation = match edge.kind {
                    SurfaceCandidateKind::KnownExactOrAlias => {
                        if entity_has_surface(entity, surface_key) {
                            AtlasAliasRelation::ExactKnownAlias
                        } else {
                            classify_known_surface(mention.surface.as_str(), &entity.canonical_name)
                                .unwrap_or(AtlasAliasRelation::Codename)
                        }
                    }
                    SurfaceCandidateKind::NormalizedAlias => AtlasAliasRelation::FullDesignation,
                    SurfaceCandidateKind::SameSurfaceCluster => AtlasAliasRelation::SameSurface,
                    SurfaceCandidateKind::ReviewOnly => AtlasAliasRelation::Ambiguous,
                };
                candidates.push(candidate_for_entity(
                    mention,
                    entity,
                    relation,
                    edge.confidence.max(0.72),
                    "surfaceMemory",
                    "surface memory found a known target",
                    false,
                ));
            }
            SurfaceCandidateTarget::SpeculativeEntity(key) if key != surface_key => {
                if let Some(entry) = entries.get(key.as_str()) {
                    candidates.push(Candidate {
                        relation: AtlasAliasRelation::SameSurface,
                        target: AtlasAliasProposalTarget::RunLocalSurface {
                            key: entry.key.clone(),
                            display: entry.display.clone(),
                            kind: entry.kind.clone(),
                        },
                        confidence: edge.confidence.max(0.66),
                        evidence: vec![evidence(
                            "surfaceMemory",
                            edge.confidence,
                            "run-local repeated surface cluster",
                        )],
                        rationale: "run-local surface cluster may be one entity",
                        conflict: false,
                    });
                }
            }
            SurfaceCandidateTarget::DeferredReview
            | SurfaceCandidateTarget::SpeculativeEntity(_) => {}
        }
    }
}

fn push_run_local_designation_candidates(
    mention: &MentionPacket,
    surface_key: &str,
    entries: &BTreeMap<&str, &SurfaceMemoryEntry>,
    candidates: &mut Vec<Candidate>,
) {
    let mention_tokens = tokenize_norm(mention.surface.as_str());
    if mention_tokens.len() < 2 {
        return;
    }
    for (key, entry) in entries {
        if *key == surface_key {
            continue;
        }
        if entry.known_count > 0 {
            continue;
        }
        let entry_tokens = tokenize_norm(&entry.display);
        if entry_tokens.is_empty() || entry_tokens.len() >= mention_tokens.len() {
            continue;
        }
        if tokens_contain_ordered(&mention_tokens, &entry_tokens)
            || first_token_prefix(&mention_tokens, &entry_tokens)
        {
            candidates.push(Candidate {
                relation: AtlasAliasRelation::FullDesignation,
                target: AtlasAliasProposalTarget::RunLocalSurface {
                    key: entry.key.clone(),
                    display: entry.display.clone(),
                    kind: entry.kind.clone(),
                },
                confidence: (0.60 + mention.confidence * 0.25).min(0.84),
                evidence: vec![evidence(
                    "runLocalSurface",
                    mention.confidence,
                    "longer mention expands a run-local surface",
                )],
                rationale: "longer surfaced name may designate a shorter surfaced name",
                conflict: false,
            });
        }
    }
}

fn select_proposal(
    document_id: &str,
    mention: &MentionPacket,
    mut candidates: Vec<Candidate>,
) -> Option<AtlasAliasProposalSummary> {
    if candidates.is_empty() {
        if mention.status == MentionStatus::AcceptedNew && mention.confidence >= 0.70 {
            return Some(build_proposal(
                document_id,
                mention,
                Candidate {
                    relation: AtlasAliasRelation::NewEntity,
                    target: AtlasAliasProposalTarget::NewEntity,
                    confidence: mention.confidence,
                    evidence: vec![evidence(
                        "nerSurface",
                        mention.confidence,
                        "accepted surface has no known alias candidate",
                    )],
                    rationale: "surface is likely a new entity",
                    conflict: false,
                },
            ));
        }
        return None;
    }

    for candidate in &mut candidates {
        if has_kind_conflict(mention, &candidate.target) {
            candidate.relation = AtlasAliasRelation::TypeConflict;
            candidate.decision_hint_conflict();
        }
    }
    candidates.sort_by(candidate_order);
    let top = candidates.remove(0);
    if candidates.first().is_some_and(|next| {
        next.confidence + 0.08 >= top.confidence && target_key(next) != target_key(&top)
    }) {
        return Some(build_proposal(
            document_id,
            mention,
            Candidate {
                relation: AtlasAliasRelation::Ambiguous,
                target: AtlasAliasProposalTarget::Deferred,
                confidence: top.confidence,
                evidence: top.evidence,
                rationale: "multiple alias targets are too close to choose automatically",
                conflict: true,
            },
        ));
    }
    Some(build_proposal(document_id, mention, top))
}

impl Candidate {
    fn decision_hint_conflict(&mut self) {
        self.conflict = true;
        self.confidence = self.confidence.min(0.74);
        self.evidence.push(evidence(
            "kindGuard",
            self.confidence,
            "mention kind conflicts with target kind",
        ));
        self.rationale = "kind evidence conflicts with the alias target";
    }
}

fn build_proposal(
    document_id: &str,
    mention: &MentionPacket,
    candidate: Candidate,
) -> AtlasAliasProposalSummary {
    let normalized = alias_key(mention.surface.as_str());
    let decision = decision_for(&candidate);
    let case_seed = format!(
        "{}:{}:{}:{}",
        document_id,
        mention.mention_id.0,
        normalized,
        relation_name(candidate.relation)
    );
    AtlasAliasProposalSummary {
        case_id: format!("alias-{:016x}", stable_hash(case_seed.as_bytes())),
        document_id: DocumentId(document_id.to_owned()),
        mention_id: MentionId(mention.mention_id.0.to_string()),
        surface: mention.surface.to_string(),
        normalized,
        range: mention.range,
        relation: candidate.relation,
        target: candidate.target,
        confidence: candidate.confidence.clamp(0.0, 1.0),
        decision,
        evidence: candidate.evidence,
        rationale: candidate.rationale.to_owned(),
    }
}

fn candidate_for_entity(
    mention: &MentionPacket,
    entity: &AliasRegistryEntity,
    relation: AtlasAliasRelation,
    confidence: f32,
    source: &str,
    note: &str,
    conflict: bool,
) -> Candidate {
    Candidate {
        relation,
        target: AtlasAliasProposalTarget::KnownEntity {
            entity_id: entity.entity_id.clone(),
            canonical_name: entity.canonical_name.clone(),
            kind: entity.kind.clone(),
        },
        confidence,
        evidence: vec![evidence(
            source,
            confidence.min(mention.confidence.max(0.55)),
            note,
        )],
        rationale: relation_rationale(relation),
        conflict,
    }
}

fn classify_registry_surface(
    mention_tokens: &[String],
    mention_key: &str,
    surface: &RegistrySurface<'_>,
) -> Option<(AtlasAliasRelation, f32, &'static str)> {
    if mention_tokens.len() > surface.tokens.len()
        && tokens_contain_ordered(mention_tokens, &surface.tokens)
    {
        return Some((
            AtlasAliasRelation::FullDesignation,
            if surface.is_canonical { 0.88 } else { 0.84 },
            "mention expands a saved name surface",
        ));
    }
    if mention_tokens.len() > surface.tokens.len()
        && first_token_prefix(mention_tokens, &surface.tokens)
    {
        return Some((
            AtlasAliasRelation::FullDesignation,
            0.74,
            "mention first token expands a saved short name",
        ));
    }
    if bounded_levenshtein(mention_key, &surface.key, 2).is_some() {
        return Some((
            AtlasAliasRelation::SpellingVariant,
            0.78,
            "mention is a close spelling variant of a saved surface",
        ));
    }
    if mention_tokens.len() > surface.tokens.len()
        && first_token_edit_distance(mention_tokens, &surface.tokens)
            .is_some_and(|distance| distance <= 1)
    {
        return Some((
            AtlasAliasRelation::SpellingVariant,
            0.71,
            "mention first token is a likely spelling variant",
        ));
    }
    None
}

fn classify_known_surface(surface: &str, canonical: &str) -> Option<AtlasAliasRelation> {
    let surface_tokens = tokenize_norm(surface);
    let canonical_tokens = tokenize_norm(canonical);
    if surface_tokens.len() > canonical_tokens.len()
        && (tokens_contain_ordered(&surface_tokens, &canonical_tokens)
            || first_token_prefix(&surface_tokens, &canonical_tokens))
    {
        Some(AtlasAliasRelation::FullDesignation)
    } else if first_token_edit_distance(&surface_tokens, &canonical_tokens)
        .is_some_and(|distance| distance <= 1)
    {
        Some(AtlasAliasRelation::SpellingVariant)
    } else {
        None
    }
}

fn entity_has_surface(entity: &AliasRegistryEntity, surface_key: &str) -> bool {
    alias_key(&entity.canonical_name) == surface_key
        || entity
            .aliases
            .iter()
            .any(|alias| alias_key(alias) == surface_key)
}

fn has_kind_conflict(mention: &MentionPacket, target: &AtlasAliasProposalTarget) -> bool {
    let Some(mention_group) = mention_kind_group(mention) else {
        return false;
    };
    let Some(target_group) = target_kind_group(target) else {
        return false;
    };
    !kind_groups_compatible(mention_group, target_group)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum KindGroup {
    Person,
    Location,
    Network,
    Item,
    Event,
    Concept,
}

fn mention_kind_group(mention: &MentionPacket) -> Option<KindGroup> {
    mention
        .label_distribution
        .iter()
        .max_by(|left, right| left.1.partial_cmp(&right.1).unwrap_or(Ordering::Equal))
        .and_then(|(label, _)| label_group(label.as_str()))
}

fn target_kind_group(target: &AtlasAliasProposalTarget) -> Option<KindGroup> {
    match target {
        AtlasAliasProposalTarget::KnownEntity { kind, .. } => kind.as_ref().and_then(entity_group),
        AtlasAliasProposalTarget::RunLocalSurface { kind, .. } => {
            kind.as_deref().and_then(label_group)
        }
        AtlasAliasProposalTarget::NewEntity | AtlasAliasProposalTarget::Deferred => None,
    }
}

fn entity_group(kind: &EntityKind) -> Option<KindGroup> {
    match kind {
        EntityKind::Character | EntityKind::Npc => Some(KindGroup::Person),
        EntityKind::Location => Some(KindGroup::Location),
        EntityKind::Faction | EntityKind::Organization => Some(KindGroup::Network),
        EntityKind::Item => Some(KindGroup::Item),
        EntityKind::Event => Some(KindGroup::Event),
        EntityKind::Concept => Some(KindGroup::Concept),
        EntityKind::Other => None,
    }
}

fn label_group(label: &str) -> Option<KindGroup> {
    match label.trim().to_ascii_lowercase().as_str() {
        "character" | "person" | "npc" | "creature" | "species" | "monster" => {
            Some(KindGroup::Person)
        }
        "location" | "place" | "region" | "landmark" | "city" | "country" => {
            Some(KindGroup::Location)
        }
        "organization" | "organisation" | "faction" | "group" | "network" | "alliance" => {
            Some(KindGroup::Network)
        }
        "artifact" | "item" | "weapon" | "object" => Some(KindGroup::Item),
        "event" => Some(KindGroup::Event),
        "concept" | "ability" | "spell" | "role" | "title" | "library" | "librarian" => {
            Some(KindGroup::Concept)
        }
        _ => None,
    }
}

fn kind_groups_compatible(left: KindGroup, right: KindGroup) -> bool {
    left == right
}

fn decision_for(candidate: &Candidate) -> AtlasAliasProposalDecision {
    if candidate.conflict || candidate.relation == AtlasAliasRelation::Ambiguous {
        return AtlasAliasProposalDecision::Defer;
    }
    match candidate.relation {
        AtlasAliasRelation::ExactKnownAlias => AtlasAliasProposalDecision::Accept,
        AtlasAliasRelation::FullDesignation | AtlasAliasRelation::SameSurface => {
            AtlasAliasProposalDecision::Propose
        }
        AtlasAliasRelation::Nickname | AtlasAliasRelation::Codename => {
            AtlasAliasProposalDecision::Propose
        }
        AtlasAliasRelation::SpellingVariant if candidate.confidence >= 0.76 => {
            AtlasAliasProposalDecision::Propose
        }
        AtlasAliasRelation::NewEntity => AtlasAliasProposalDecision::Propose,
        AtlasAliasRelation::SpellingVariant
        | AtlasAliasRelation::TitleOrRole
        | AtlasAliasRelation::RelatedButDistinct
        | AtlasAliasRelation::TypeConflict => AtlasAliasProposalDecision::Defer,
        AtlasAliasRelation::Ambiguous => AtlasAliasProposalDecision::Defer,
    }
}

fn relation_rationale(relation: AtlasAliasRelation) -> &'static str {
    match relation {
        AtlasAliasRelation::ExactKnownAlias => "surface is already known for this entity",
        AtlasAliasRelation::FullDesignation => "surface looks like a fuller designation",
        AtlasAliasRelation::SpellingVariant => "surface looks like a spelling variant",
        AtlasAliasRelation::SameSurface => "surface memory clusters these mentions together",
        AtlasAliasRelation::NewEntity => "surface looks like a new entity",
        AtlasAliasRelation::Nickname
        | AtlasAliasRelation::Codename
        | AtlasAliasRelation::TitleOrRole
        | AtlasAliasRelation::RelatedButDistinct
        | AtlasAliasRelation::TypeConflict
        | AtlasAliasRelation::Ambiguous => "surface needs alias adjudication",
    }
}

fn relation_name(relation: AtlasAliasRelation) -> &'static str {
    match relation {
        AtlasAliasRelation::ExactKnownAlias => "exact",
        AtlasAliasRelation::FullDesignation => "full",
        AtlasAliasRelation::Nickname => "nickname",
        AtlasAliasRelation::Codename => "codename",
        AtlasAliasRelation::SpellingVariant => "spelling",
        AtlasAliasRelation::TitleOrRole => "role",
        AtlasAliasRelation::SameSurface => "same",
        AtlasAliasRelation::RelatedButDistinct => "related",
        AtlasAliasRelation::TypeConflict => "conflict",
        AtlasAliasRelation::Ambiguous => "ambiguous",
        AtlasAliasRelation::NewEntity => "new",
    }
}

fn alias_key(surface: &str) -> String {
    tokenize_norm(surface).join(" ")
}

fn known_entity_id(mention: &MentionPacket) -> Option<String> {
    match mention.entity_ref.as_ref()? {
        phoenix_types::MentionEntityRef::Known(entity_id) => Some(entity_id.0.clone()),
        phoenix_types::MentionEntityRef::Speculative(_) => None,
    }
}

fn tokens_contain_ordered(tokens: &[String], needle: &[String]) -> bool {
    if needle.is_empty() || needle.len() > tokens.len() {
        return false;
    }
    tokens
        .windows(needle.len())
        .any(|window| window.iter().zip(needle).all(|(left, right)| left == right))
}

fn first_token_prefix(tokens: &[String], needle: &[String]) -> bool {
    let (Some(first), Some(saved)) = (tokens.first(), needle.first()) else {
        return false;
    };
    saved.len() >= 3 && first.len() > saved.len() + 1 && first.starts_with(saved)
}

fn first_token_edit_distance(tokens: &[String], needle: &[String]) -> Option<usize> {
    let (Some(first), Some(saved)) = (tokens.first(), needle.first()) else {
        return None;
    };
    bounded_levenshtein(first, saved, 2)
}

fn bounded_levenshtein(left: &str, right: &str, max_distance: usize) -> Option<usize> {
    if left == right {
        return Some(0);
    }
    let left_chars = left.chars().collect::<Vec<_>>();
    let right_chars = right.chars().collect::<Vec<_>>();
    if left_chars.len().abs_diff(right_chars.len()) > max_distance {
        return None;
    }
    let mut prev = (0..=right_chars.len()).collect::<Vec<_>>();
    let mut curr = vec![0; right_chars.len() + 1];
    for (i, left_ch) in left_chars.iter().enumerate() {
        curr[0] = i + 1;
        let mut row_min = curr[0];
        for (j, right_ch) in right_chars.iter().enumerate() {
            let cost = usize::from(left_ch != right_ch);
            curr[j + 1] = (prev[j + 1] + 1).min(curr[j] + 1).min(prev[j] + cost);
            row_min = row_min.min(curr[j + 1]);
        }
        if row_min > max_distance {
            return None;
        }
        std::mem::swap(&mut prev, &mut curr);
    }
    (prev[right_chars.len()] <= max_distance).then_some(prev[right_chars.len()])
}

fn evidence(source: &str, confidence: f32, note: &str) -> AtlasAliasEvidence {
    AtlasAliasEvidence {
        source: source.to_owned(),
        confidence: confidence.clamp(0.0, 1.0),
        note: note.to_owned(),
    }
}

fn candidate_order(left: &Candidate, right: &Candidate) -> Ordering {
    right
        .confidence
        .partial_cmp(&left.confidence)
        .unwrap_or(Ordering::Equal)
        .then_with(|| relation_rank(left.relation).cmp(&relation_rank(right.relation)))
}

fn relation_rank(relation: AtlasAliasRelation) -> u8 {
    match relation {
        AtlasAliasRelation::ExactKnownAlias => 0,
        AtlasAliasRelation::FullDesignation => 1,
        AtlasAliasRelation::SpellingVariant => 2,
        AtlasAliasRelation::SameSurface => 3,
        AtlasAliasRelation::NewEntity => 4,
        _ => 5,
    }
}

fn target_key(candidate: &Candidate) -> String {
    match &candidate.target {
        AtlasAliasProposalTarget::KnownEntity { entity_id, .. } => format!("known:{}", entity_id.0),
        AtlasAliasProposalTarget::RunLocalSurface { key, .. } => format!("local:{key}"),
        AtlasAliasProposalTarget::NewEntity => "new".to_owned(),
        AtlasAliasProposalTarget::Deferred => "deferred".to_owned(),
    }
}

fn proposal_is_better(left: &AtlasAliasProposalSummary, right: &AtlasAliasProposalSummary) -> bool {
    left.confidence > right.confidence
        || (left.confidence == right.confidence
            && decision_rank(left.decision) < decision_rank(right.decision))
}

fn decision_rank(decision: AtlasAliasProposalDecision) -> u8 {
    match decision {
        AtlasAliasProposalDecision::Accept => 0,
        AtlasAliasProposalDecision::Propose => 1,
        AtlasAliasProposalDecision::Defer => 2,
        AtlasAliasProposalDecision::Reject => 3,
    }
}

fn stable_hash(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}
