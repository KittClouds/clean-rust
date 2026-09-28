use std::collections::HashSet;
use std::fs::File;
use std::path::Path;

use anyhow::{Context, Result, ensure};
use memchr::memchr;
use memmap2::MmapOptions;

use crate::types::{
    AuthorityClass, CanonicalEpisode, ContractStatus, DistributionInterpretation, GoldTarget,
    ProbabilityEntry, ProbabilitySource, RelationPolarity, TargetPayload,
};

const EPSILON: f64 = 1.0e-8;

pub fn validate_episode(episode: &CanonicalEpisode) -> Result<()> {
    ensure!(
        episode.contract == crate::types::CONTRACT_V1,
        "unsupported contract {}",
        episode.contract
    );
    if episode.authority.phoenix_authority_domain {
        anyhow::bail!("Phoenix-native authority is outside this bridge and must not be ingested");
    }
    ensure!(
        episode.authority.authority_record_ids.len() == episode.authority_records.len(),
        "authority summary/record count mismatch"
    );
    let authority_ids: HashSet<&str> = episode
        .authority_records
        .iter()
        .map(|record| record.authority_record_id.as_str())
        .collect();
    ensure!(
        authority_ids.len() == episode.authority_records.len(),
        "authority record IDs are not unique"
    );
    for authority_id in &episode.authority.authority_record_ids {
        ensure!(
            authority_ids.contains(authority_id.as_str()),
            "authority summary references missing record {authority_id}"
        );
    }
    ensure!(
        episode.authority.episode_authority_class != AuthorityClass::Authoritative,
        "external bridge cannot mint authoritative truth"
    );
    ensure!(
        episode.authority.episode_authority_class != AuthorityClass::Adjudicated
            || episode.authority_records.iter().any(
                |record| record.authority_domain == crate::types::AuthorityDomain::Adjudication
            ),
        "adjudicated episode lacks adjudication domain"
    );

    validate_identity_fingerprint(episode)?;
    validate_schema(episode)?;
    validate_queries_and_targets(episode, &authority_ids)?;
    validate_evidence(episode)?;
    if episode.state.structured_state.is_some() {
        validate_structured_state(episode)?;
    }
    if matches!(
        episode.contract_status,
        ContractStatus::V1PlusProposedE01 | ContractStatus::V1PlusProposedE01E02
    ) {
        ensure!(
            episode.state.structured_state.is_some(),
            "E01 episode lacks structured state"
        );
    }
    Ok(())
}

pub fn validate_jsonl(path: impl AsRef<Path>) -> Result<usize> {
    let path = path.as_ref();
    let file = File::open(path).with_context(|| format!("open JSONL {}", path.display()))?;
    // SAFETY: the file descriptor remains open for the lifetime of the mapping and the mapping
    // is read-only. We never expose the mapped bytes beyond this function.
    let map = unsafe { MmapOptions::new().map(&file) }
        .with_context(|| format!("mmap JSONL {}", path.display()))?;
    let mut start = 0_usize;
    let mut count = 0_usize;
    while start < map.len() {
        let end = memchr(b'\n', &map[start..])
            .map(|offset| start + offset)
            .unwrap_or(map.len());
        let line = &map[start..end];
        if !line.iter().all(u8::is_ascii_whitespace) {
            let episode: CanonicalEpisode = serde_json::from_slice(line)
                .with_context(|| format!("parse JSONL record {count}"))?;
            validate_episode(&episode).with_context(|| format!("validate JSONL record {count}"))?;
            count += 1;
        }
        start = end.saturating_add(1);
    }
    Ok(count)
}

fn validate_identity_fingerprint(episode: &CanonicalEpisode) -> Result<()> {
    let bytes = episode
        .semantic_content_bytes()
        .context("serialize semantic content")?;
    let expected = blake3::hash(&bytes).to_hex().to_string();
    ensure!(
        episode.identity.semantic_fingerprint == expected,
        "semantic fingerprint mismatch: expected {expected}, found {}",
        episode.identity.semantic_fingerprint
    );
    Ok(())
}

fn validate_schema(episode: &CanonicalEpisode) -> Result<()> {
    let candidate_ids: HashSet<&str> = episode
        .runtime_schema
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_id.as_str())
        .collect();
    let semantic_ids: HashSet<&str> = episode
        .runtime_schema
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_semantic_id.as_str())
        .collect();
    ensure!(
        candidate_ids.len() == episode.runtime_schema.candidates.len(),
        "runtime candidate IDs are not unique"
    );
    ensure!(
        semantic_ids.len() == episode.runtime_schema.candidates.len(),
        "runtime semantic candidate IDs are not unique"
    );
    let mut set_ids = HashSet::new();
    for candidate_set in &episode.runtime_schema.candidate_sets {
        ensure!(
            set_ids.insert(candidate_set.candidate_set_id.as_str()),
            "candidate set IDs are not unique"
        );
        let mut members = HashSet::new();
        for candidate_id in &candidate_set.candidate_ids {
            ensure!(
                candidate_ids.contains(candidate_id.as_str()),
                "candidate set {} references missing candidate {}",
                candidate_set.candidate_set_id,
                candidate_id
            );
            ensure!(
                members.insert(candidate_id.as_str()),
                "candidate set {} repeats candidate {}",
                candidate_set.candidate_set_id,
                candidate_id
            );
        }
    }
    Ok(())
}

fn validate_queries_and_targets(
    episode: &CanonicalEpisode,
    authority_ids: &HashSet<&str>,
) -> Result<()> {
    let mut query_ids = HashSet::new();
    for query in &episode.queries {
        ensure!(
            query_ids.insert(query.query_id.as_str()),
            "query IDs are not unique"
        );
        if let Some(candidate_set_id) = &query.candidate_set_id {
            ensure!(
                episode
                    .runtime_schema
                    .candidate_sets
                    .iter()
                    .any(|candidate_set| candidate_set.candidate_set_id == *candidate_set_id),
                "query {} references missing candidate set {}",
                query.query_id,
                candidate_set_id
            );
        }
    }
    let mut target_ids = HashSet::new();
    for target in &episode.gold_targets {
        ensure!(
            target_ids.insert(target.query_id.as_str()),
            "gold target query IDs are not unique"
        );
        ensure!(
            query_ids.contains(target.query_id.as_str()),
            "gold target references missing query {}",
            target.query_id
        );
        ensure!(
            authority_ids.contains(target.authority_record_id.as_str()),
            "gold target references missing authority {}",
            target.authority_record_id
        );
        if let Some(candidate_set_id) = &target.candidate_set_id {
            ensure!(
                episode
                    .runtime_schema
                    .candidate_sets
                    .iter()
                    .any(|candidate_set| candidate_set.candidate_set_id == *candidate_set_id),
                "gold target references missing candidate set {}",
                candidate_set_id
            );
        }
        validate_target(target, episode)?;
    }
    Ok(())
}

fn validate_target(target: &GoldTarget, episode: &CanonicalEpisode) -> Result<()> {
    let source = &target.probability_source;
    ensure!(
        !source.aggregation_method.is_empty(),
        "probability aggregation method is empty"
    );
    if source.probability_source == ProbabilitySource::EmpiricalAnnotatorDistribution {
        ensure!(
            source.annotator_count.unwrap_or(0) > 0,
            "empirical distribution lacks annotator_count"
        );
        ensure!(
            source.distribution_interpretation == DistributionInterpretation::HumanOpinionFrequency,
            "empirical distribution has wrong interpretation"
        );
        validate_empirical_receipt(target)?;
    }
    if source.probability_source == ProbabilitySource::ExactGenerativePosterior {
        ensure!(
            source.distribution_interpretation == DistributionInterpretation::WorldPosterior,
            "exact posterior has wrong interpretation"
        );
    }
    if matches!(
        source.probability_source,
        ProbabilitySource::HardLabel | ProbabilitySource::NoProbability
    ) {
        ensure!(
            !contains_probability(&target.target),
            "{:#?} target contains a probability-bearing field",
            source.probability_source
        );
    }
    match &target.target {
        TargetPayload::Choice {
            distribution,
            other_probability,
            ..
        } => {
            if let Some(distribution) = distribution {
                validate_distribution(distribution)?;
                if other_probability.is_none() {
                    ensure!(
                        (sum_distribution(distribution) - 1.0).abs() <= EPSILON,
                        "choice distribution does not normalize"
                    );
                }
            }
            validate_candidate_semantics(distribution.as_deref(), episode)?;
            if let Some(other) = other_probability {
                ensure!(
                    other.is_finite() && (0.0..=1.0).contains(other),
                    "choice other probability outside [0,1]"
                );
                if let Some(distribution) = distribution {
                    ensure!(
                        (sum_distribution(distribution) + other - 1.0).abs() <= EPSILON,
                        "choice plus other probability does not normalize"
                    );
                }
            }
        }
        TargetPayload::IndependentApplicability { candidates } => {
            for entry in candidates {
                if let Some(probability) = entry.probability {
                    validate_probability(probability)?;
                }
                validate_semantic_id(&entry.candidate_semantic_id, episode)?;
            }
        }
        TargetPayload::Ordinal {
            distribution,
            expected_value,
            ..
        } => {
            if let Some(distribution) = distribution {
                ensure!(!distribution.is_empty(), "ordinal distribution is empty");
                for probability in distribution {
                    validate_probability(*probability)?;
                }
                ensure!(
                    (distribution.iter().sum::<f64>() - 1.0).abs() <= EPSILON,
                    "ordinal distribution does not normalize"
                );
            }
            if let Some(value) = expected_value {
                ensure!(value.is_finite(), "ordinal expected value is not finite");
            }
        }
        TargetPayload::Abstention { distribution, .. } => {
            if let Some(distribution) = distribution {
                validate_distribution(distribution)?;
                ensure!(
                    (sum_distribution(distribution) - 1.0).abs() <= EPSILON,
                    "abstention distribution does not normalize"
                );
            }
        }
        TargetPayload::SpanType { spans } => {
            for span in spans {
                ensure!(
                    span.start <= span.end && span.end <= episode.state.observable.content.len(),
                    "span target bounds are invalid"
                );
                for entry in &span.type_targets {
                    validate_semantic_id(&entry.candidate_semantic_id, episode)?;
                    if let Some(probability) = entry.probability {
                        validate_probability(probability)?;
                    }
                }
            }
        }
        TargetPayload::Relation { relations } => {
            let structured_mentions: HashSet<&str> = episode
                .state
                .structured_state
                .as_ref()
                .map(|structured| {
                    structured
                        .entities
                        .iter()
                        .flat_map(|entity| {
                            entity
                                .mentions
                                .iter()
                                .map(|mention| mention.mention_id.as_str())
                        })
                        .collect()
                })
                .unwrap_or_default();
            for relation in relations {
                validate_semantic_id(&relation.candidate_semantic_id, episode)?;
                ensure!(
                    relation.head_span_id != relation.tail_span_id,
                    "relation has identical head/tail mention"
                );
                if episode.state.structured_state.is_some() {
                    ensure!(
                        structured_mentions.contains(relation.head_span_id.as_str()),
                        "relation head mention is missing"
                    );
                    ensure!(
                        structured_mentions.contains(relation.tail_span_id.as_str()),
                        "relation tail mention is missing"
                    );
                }
                if let Some(probability) = relation.probability {
                    validate_probability(probability)?;
                }
                ensure!(
                    matches!(
                        relation.polarity,
                        RelationPolarity::Holds
                            | RelationPolarity::DoesNotHold
                            | RelationPolarity::Unknown
                    ),
                    "invalid relation polarity"
                );
            }
        }
        TargetPayload::HardLabel { labels } => {
            ensure!(!labels.is_empty(), "hard label target is empty")
        }
    }
    Ok(())
}

fn validate_empirical_receipt(target: &GoldTarget) -> Result<()> {
    let Some(raw_counts) = &target.probability_source.raw_label_counts else {
        return Ok(());
    };
    let total: u64 = raw_counts.values().sum();
    ensure!(
        total == target.probability_source.annotator_count.unwrap_or(0) as u64,
        "raw label counts do not sum to annotator_count"
    );
    if let Some(annotations) = &target.annotations {
        ensure!(
            annotations.len() == total as usize,
            "annotation rows do not match raw label count total"
        );
        for (label, expected) in raw_counts {
            let observed = annotations
                .iter()
                .filter(|annotation| annotation.labels.iter().any(|candidate| candidate == label))
                .count() as u64;
            ensure!(
                observed == *expected,
                "annotation rows do not reproduce count for {label}"
            );
        }
    }
    match &target.target {
        TargetPayload::Choice {
            distribution: Some(distribution),
            ..
        } => {
            for entry in distribution {
                if let Some(count) = raw_counts.get(&entry.candidate_semantic_id) {
                    ensure!(
                        (entry.probability - *count as f64 / total as f64).abs() <= EPSILON,
                        "choice frequency mismatch for {}",
                        entry.candidate_semantic_id
                    );
                }
            }
        }
        TargetPayload::IndependentApplicability { candidates } => {
            for entry in candidates {
                if let Some(probability) = entry.probability
                    && let Some(count) = raw_counts.get(&entry.candidate_semantic_id)
                {
                    ensure!(
                        (probability - *count as f64 / total as f64).abs() <= EPSILON,
                        "applicability frequency mismatch for {}",
                        entry.candidate_semantic_id
                    );
                }
            }
        }
        _ => {}
    }
    Ok(())
}

fn validate_evidence(episode: &CanonicalEpisode) -> Result<()> {
    let evidence_ids: HashSet<&str> = episode
        .evidence_items
        .iter()
        .map(|item| item.evidence_id.as_str())
        .collect();
    ensure!(
        evidence_ids.len() == episode.evidence_items.len(),
        "evidence IDs are not unique"
    );
    let content_len = episode.state.observable.content.len();
    for evidence in &episode.evidence_items {
        if let Some([start, end]) = evidence.character_span {
            ensure!(
                start <= end && end <= content_len,
                "evidence {} span is out of bounds",
                evidence.evidence_id
            );
        }
    }
    for link in &episode.evidence_links {
        for evidence_id in &link.evidence_item_ids {
            ensure!(
                evidence_ids.contains(evidence_id.as_str()),
                "evidence link references missing item {evidence_id}"
            );
        }
        for location in &link.locations {
            ensure!(
                evidence_ids.contains(location.evidence_id.as_str()),
                "evidence location references missing item {}",
                location.evidence_id
            );
            ensure!(
                location.start <= location.end && location.end <= content_len,
                "evidence location is out of bounds"
            );
        }
    }
    Ok(())
}

fn validate_structured_state(episode: &CanonicalEpisode) -> Result<()> {
    let structured = episode
        .state
        .structured_state
        .as_ref()
        .context("structured state disappeared")?;
    let content = episode.state.observable.content.as_bytes();
    let entity_ids: HashSet<&str> = structured
        .entities
        .iter()
        .map(|entity| entity.entity_semantic_id.as_str())
        .collect();
    ensure!(
        entity_ids.len() == structured.entities.len(),
        "structured entity IDs are not unique"
    );
    let mut mention_ids = HashSet::new();
    let mut spans = Vec::new();
    for entity in &structured.entities {
        for mention in &entity.mentions {
            ensure!(
                mention.entity_semantic_id == entity.entity_semantic_id,
                "mention/entity identity mismatch"
            );
            ensure!(
                mention_ids.insert(mention.mention_id.as_str()),
                "mention IDs are not unique"
            );
            ensure!(
                mention.character_start < mention.character_end
                    && mention.character_end <= content.len(),
                "structured mention bounds are invalid"
            );
            ensure!(
                &content[mention.character_start..mention.character_end]
                    == mention.surface.as_bytes(),
                "structured mention surface does not round-trip"
            );
            spans.push((mention.character_start, mention.character_end));
        }
    }
    spans.sort_unstable();
    for pair in spans.windows(2) {
        ensure!(pair[0].1 <= pair[1].0, "structured mentions overlap");
    }
    let relation_ids: HashSet<&str> = structured
        .semantic_relations
        .iter()
        .map(|relation| relation.relation_instance_id.as_str())
        .collect();
    ensure!(
        relation_ids.len() == structured.semantic_relations.len(),
        "semantic relation IDs are not unique"
    );
    for relation in &structured.semantic_relations {
        ensure!(
            entity_ids.contains(relation.head_entity_id.as_str()),
            "relation head entity is missing"
        );
        ensure!(
            entity_ids.contains(relation.tail_entity_id.as_str()),
            "relation tail entity is missing"
        );
    }
    Ok(())
}

fn validate_distribution(distribution: &[ProbabilityEntry]) -> Result<()> {
    ensure!(
        !distribution.is_empty(),
        "probability distribution is empty"
    );
    let mut ids = HashSet::new();
    for entry in distribution {
        ensure!(
            ids.insert(entry.candidate_semantic_id.as_str()),
            "probability distribution repeats a candidate"
        );
        validate_probability(entry.probability)?;
    }
    Ok(())
}

fn validate_probability(probability: f64) -> Result<()> {
    ensure!(
        probability.is_finite() && (0.0..=1.0).contains(&probability),
        "probability outside [0,1]"
    );
    Ok(())
}

fn validate_candidate_semantics(
    distribution: Option<&[ProbabilityEntry]>,
    episode: &CanonicalEpisode,
) -> Result<()> {
    if let Some(distribution) = distribution {
        for entry in distribution {
            validate_semantic_id(&entry.candidate_semantic_id, episode)?;
        }
    }
    Ok(())
}

fn validate_semantic_id(semantic_id: &str, episode: &CanonicalEpisode) -> Result<()> {
    ensure!(
        episode
            .runtime_schema
            .candidates
            .iter()
            .any(|candidate| candidate.candidate_semantic_id == semantic_id),
        "target references missing semantic candidate {semantic_id}"
    );
    Ok(())
}

fn contains_probability(target: &TargetPayload) -> bool {
    match target {
        TargetPayload::Choice {
            distribution,
            other_probability,
            ..
        } => distribution.is_some() || other_probability.is_some(),
        TargetPayload::IndependentApplicability { candidates } => {
            candidates.iter().any(|entry| entry.probability.is_some())
        }
        TargetPayload::Ordinal {
            distribution,
            expected_value,
            ..
        } => distribution.is_some() || expected_value.is_some(),
        TargetPayload::Abstention { distribution, .. } => distribution.is_some(),
        TargetPayload::SpanType { spans } => spans.iter().any(|span| {
            span.type_targets
                .iter()
                .any(|entry| entry.probability.is_some())
        }),
        TargetPayload::Relation { relations } => relations
            .iter()
            .any(|relation| relation.probability.is_some()),
        TargetPayload::HardLabel { .. } => false,
    }
}

fn sum_distribution(distribution: &[ProbabilityEntry]) -> f64 {
    distribution.iter().map(|entry| entry.probability).sum()
}
