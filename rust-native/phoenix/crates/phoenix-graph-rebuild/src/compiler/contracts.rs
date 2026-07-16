use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};

use super::types::{EvidenceBundleKind, FactLane, GraphCompilerOutput, RelationFact};

pub(super) fn validate_lane_promotion_contracts(
    output: &GraphCompilerOutput,
) -> Vec<CompactString> {
    let roles = roles_by_fact(output);
    let mut failures = Vec::new();
    for fact in &output.facts {
        if fact.predicate.is_empty() {
            failures.push(format_compact!("fact {} has empty predicate", fact.id));
        }
        match fact.lane {
            FactLane::RelationshipFact => relationship_contract(fact, &roles, &mut failures),
            FactLane::TemporalFact => {
                require_roles(fact, &roles, &["source", "target"], &mut failures)
            }
            FactLane::CausalFact => {
                require_roles(fact, &roles, &["cause", "effect"], &mut failures)
            }
            FactLane::MemoryState => {
                require_roles(fact, &roles, &["subject", "state"], &mut failures)
            }
            FactLane::CooccurrenceWeak => failures.push(format_compact!(
                "cooccurrence lane {} must be staged as bundle",
                fact.id
            )),
            FactLane::DocumentSpine
            | FactLane::ChunkSpine
            | FactLane::EntityAnchor
            | FactLane::EventIdentity
            | FactLane::EntityLinker
            | FactLane::AnchorEvidence => failures.push(format_compact!(
                "lane {:?} cannot promote fact {}",
                fact.lane,
                fact.id
            )),
        }
    }
    for bundle in &output.bundles {
        let allowed_lane = matches!(
            (bundle.bundle_kind, bundle.lane),
            (EvidenceBundleKind::Frame, FactLane::AnchorEvidence)
                | (EvidenceBundleKind::Span, FactLane::CooccurrenceWeak)
                | (EvidenceBundleKind::Neighborhood, FactLane::CooccurrenceWeak)
                | (
                    EvidenceBundleKind::SemanticSimilarity,
                    FactLane::CooccurrenceWeak
                )
                | (
                    EvidenceBundleKind::ShadowIdentity,
                    FactLane::CooccurrenceWeak
                )
                | (EvidenceBundleKind::ShadowIdentity, FactLane::EntityLinker)
        );
        if !allowed_lane {
            failures.push(format_compact!(
                "bundle {} has illegal {:?}/{:?} contract",
                bundle.id,
                bundle.bundle_kind,
                bundle.lane
            ));
        }
        if bundle.group_key.is_empty() {
            failures.push(format_compact!("bundle {} has empty group key", bundle.id));
        }
        if matches!(bundle.bundle_kind, EvidenceBundleKind::Span) && bundle.evidence_ids.len() > 2 {
            failures.push(format_compact!(
                "span bundle {} is not compressed",
                bundle.id
            ));
        }
    }
    failures
}

fn relationship_contract(
    fact: &RelationFact,
    roles: &HashMap<CompactString, HashSet<CompactString>>,
    failures: &mut Vec<CompactString>,
) {
    if fact.predicate.contains("co_occurs") || fact.predicate.contains("co-occurs") {
        failures.push(format_compact!(
            "relationship fact {} illegally promotes cooccurrence",
            fact.id
        ));
    }
    let Some(row) = roles.get(&fact.id) else {
        failures.push(format_compact!(
            "relationship fact {} has no roles",
            fact.id
        ));
        return;
    };
    let entity_pair = row.contains("source") && row.contains("target");
    let mention_pair = row.contains("leftMention") && row.contains("rightMention");
    if fact.semantic_situation_id.is_some() {
        let participant_roles = row
            .iter()
            .filter(|role| role.as_str() != "evidence")
            .count();
        if fact.semantic_frame.is_some() && row.contains("evidence") && participant_roles >= 2 {
            return;
        }
    }
    if !entity_pair && !mention_pair {
        failures.push(format_compact!(
            "relationship fact {} lacks pair roles",
            fact.id
        ));
    }
}

fn require_roles(
    fact: &RelationFact,
    roles: &HashMap<CompactString, HashSet<CompactString>>,
    required: &[&str],
    failures: &mut Vec<CompactString>,
) {
    let Some(row) = roles.get(&fact.id) else {
        failures.push(format_compact!("fact {} has no roles", fact.id));
        return;
    };
    for role in required {
        if !row.contains(*role) {
            failures.push(format_compact!("fact {} lacks role {}", fact.id, role));
        }
    }
}

fn roles_by_fact(output: &GraphCompilerOutput) -> HashMap<CompactString, HashSet<CompactString>> {
    let mut out = HashMap::new();
    for role in &output.roles {
        out.entry(role.fact_id.clone())
            .or_insert_with(HashSet::new)
            .insert(role.role.clone());
    }
    out
}
