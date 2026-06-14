use compact_str::{format_compact, CompactString};
use hashbrown::{HashMap, HashSet};

use super::contracts::validate_lane_promotion_contracts;
use super::types::{
    EvidenceAnchor, EvidenceKind, FactLane, GraphAtom, GraphAtomKind, GraphCompileCounters,
    GraphCompileReceipts, GraphCompilerOutput, GraphRootReceipt,
};

pub fn assert_graph_compile_invariants(output: &GraphCompilerOutput) -> Result<(), CompactString> {
    let receipts = verify_graph_compile_output(output);
    if let Some(failure) = receipts.invariant_failures.first() {
        return Err(failure.clone());
    }
    Ok(())
}

pub fn verify_graph_compile_output(output: &GraphCompilerOutput) -> GraphCompileReceipts {
    let atom_ids = output
        .atoms
        .iter()
        .map(|atom| atom.id.clone())
        .collect::<HashSet<_>>();
    let evidence_ids = output
        .evidence_anchors
        .iter()
        .map(|evidence| evidence.id.clone())
        .collect::<HashSet<_>>();
    let atom_kind_by_id = output
        .atoms
        .iter()
        .map(|atom| (atom.id.clone(), atom.kind))
        .collect::<HashMap<_, _>>();
    let evidence_kind_by_id = output
        .evidence_anchors
        .iter()
        .map(|evidence| (evidence.id.clone(), evidence.kind))
        .collect::<HashMap<_, _>>();
    let fact_ids = output
        .facts
        .iter()
        .map(|fact| fact.id.clone())
        .collect::<HashSet<_>>();
    let bundle_ids = output
        .bundles
        .iter()
        .map(|bundle| bundle.id.clone())
        .collect::<HashSet<_>>();
    let mut failures = Vec::new();

    for bundle in &output.bundles {
        if bundle.evidence_ids.is_empty() {
            failures.push(format_compact!("bundle {} has no evidence", bundle.id));
        }
        for evidence_id in &bundle.evidence_ids {
            if !evidence_ids.contains(evidence_id) {
                failures.push(format_compact!(
                    "bundle {} references missing evidence {}",
                    bundle.id,
                    evidence_id
                ));
            }
        }
    }
    for fact in &output.facts {
        if fact.evidence_ids.is_empty() {
            failures.push(format_compact!("fact {} has no evidence", fact.id));
        }
        for evidence_id in &fact.evidence_ids {
            if !evidence_ids.contains(evidence_id) {
                failures.push(format_compact!(
                    "fact {} references missing evidence {}",
                    fact.id,
                    evidence_id
                ));
            }
        }
    }
    for role in &output.roles {
        if !fact_ids.contains(&role.fact_id) {
            failures.push(format_compact!(
                "role references missing fact {}",
                role.fact_id
            ));
        }
        if !atom_ids.contains(&role.atom_id) && !evidence_ids.contains(&role.atom_id) {
            failures.push(format_compact!(
                "role {} references missing atom {}",
                role.fact_id,
                role.atom_id
            ));
        } else if !role_target_allowed(
            role.role.as_str(),
            atom_kind_by_id.get(&role.atom_id).copied(),
            evidence_kind_by_id.get(&role.atom_id).copied(),
        ) {
            failures.push(format_compact!(
                "role {}:{} has illegal target {}",
                role.fact_id,
                role.role,
                role.atom_id
            ));
        }
    }
    for edge in &output.projected_edges {
        let has_fact = edge.source_fact_id.is_some();
        let has_bundle = edge.source_bundle_id.is_some();
        if has_fact == has_bundle && edge.projection_kind != "structure" {
            failures.push(format_compact!(
                "projection {} must reference exactly one provenance",
                edge.id
            ));
        }
        if let Some(fact_id) = &edge.source_fact_id {
            if !fact_ids.contains(fact_id) {
                failures.push(format_compact!("projection {} has missing fact", edge.id));
            }
        }
        if let Some(bundle_id) = &edge.source_bundle_id {
            if !bundle_ids.contains(bundle_id) {
                failures.push(format_compact!("projection {} has missing bundle", edge.id));
            }
        }
    }
    for atom in &output.atoms {
        if matches!(atom.kind, GraphAtomKind::Entity | GraphAtomKind::Concept)
            && atom.evidence_ids.is_empty()
            && atom.source_id != "manual"
        {
            failures.push(format_compact!("entity atom {} has no evidence", atom.id));
        }
    }
    for evidence in &output.evidence_anchors {
        if evidence.kind == EvidenceKind::LensFrame && evidence.source_range.is_none() {
            failures.push(format_compact!("lens frame {} has no span", evidence.id));
        }
    }
    failures.extend(validate_lane_promotion_contracts(output));

    GraphCompileReceipts {
        counters: GraphCompileCounters {
            atoms: output.atoms.len(),
            evidence_anchors: output.evidence_anchors.len(),
            bundles: output.bundles.len(),
            facts: output.facts.len(),
            roles: output.roles.len(),
            projected_edges: output.projected_edges.len(),
            invariant_failures: failures.len(),
        },
        roots: receipt_roots(output),
        invariant_failures: failures,
    }
}

fn receipt_roots(output: &GraphCompilerOutput) -> Vec<GraphRootReceipt> {
    let mut roots = all_lanes()
        .into_iter()
        .map(|lane| (lane, empty_root(lane)))
        .collect::<HashMap<_, _>>();
    for atom in &output.atoms {
        roots
            .entry(atom_lane(atom))
            .or_insert_with(|| empty_root(atom_lane(atom)))
            .atoms += 1;
    }
    for evidence in &output.evidence_anchors {
        roots
            .entry(evidence_lane(evidence))
            .or_insert_with(|| empty_root(evidence_lane(evidence)))
            .evidence_anchors += 1;
    }
    for fact in &output.facts {
        roots
            .entry(fact.lane)
            .or_insert_with(|| empty_root(fact.lane))
            .facts += 1;
    }
    for bundle in &output.bundles {
        roots
            .entry(bundle.lane)
            .or_insert_with(|| empty_root(bundle.lane))
            .bundles += 1;
    }
    let fact_lane = output
        .facts
        .iter()
        .map(|fact| (fact.id.clone(), fact.lane))
        .collect::<HashMap<_, _>>();
    for role in &output.roles {
        if let Some(lane) = fact_lane.get(&role.fact_id).copied() {
            roots.entry(lane).or_insert_with(|| empty_root(lane)).roles += 1;
        }
    }
    for edge in &output.projected_edges {
        let lane = edge
            .source_fact_id
            .as_ref()
            .and_then(|fact_id| fact_lane.get(fact_id).copied())
            .or_else(|| {
                edge.source_bundle_id.as_ref().and_then(|bundle_id| {
                    output
                        .bundles
                        .iter()
                        .find(|bundle| &bundle.id == bundle_id)
                        .map(|bundle| bundle.lane)
                })
            })
            .unwrap_or(FactLane::RelationshipFact);
        roots
            .entry(lane)
            .or_insert_with(|| empty_root(lane))
            .projected_edges += 1;
    }
    let mut out = roots.into_values().collect::<Vec<_>>();
    out.sort_by_key(|root| root.lane);
    out
}

fn empty_root(lane: FactLane) -> GraphRootReceipt {
    GraphRootReceipt {
        lane,
        atoms: 0,
        evidence_anchors: 0,
        bundles: 0,
        facts: 0,
        roles: 0,
        projected_edges: 0,
    }
}

fn all_lanes() -> Vec<FactLane> {
    vec![
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

fn atom_lane(atom: &GraphAtom) -> FactLane {
    match atom.kind {
        GraphAtomKind::Document
        | GraphAtomKind::DocumentRoot
        | GraphAtomKind::LaneRoot
        | GraphAtomKind::Root => FactLane::DocumentSpine,
        GraphAtomKind::Chunk => FactLane::ChunkSpine,
        GraphAtomKind::Entity | GraphAtomKind::Concept => FactLane::EntityAnchor,
        GraphAtomKind::Event | GraphAtomKind::TimeAnchor => FactLane::EventIdentity,
        GraphAtomKind::State => FactLane::MemoryState,
        GraphAtomKind::SourceSpan | GraphAtomKind::EvidenceAnchor | GraphAtomKind::Frame => {
            FactLane::AnchorEvidence
        }
        GraphAtomKind::Claim | GraphAtomKind::RelationFact => FactLane::RelationshipFact,
    }
}

fn evidence_lane(_evidence: &EvidenceAnchor) -> FactLane {
    FactLane::AnchorEvidence
}

fn role_target_allowed(
    role: &str,
    atom_kind: Option<GraphAtomKind>,
    evidence_kind: Option<EvidenceKind>,
) -> bool {
    if role == "evidence" {
        return evidence_kind.is_some()
            || matches!(
                atom_kind,
                Some(
                    GraphAtomKind::EvidenceAnchor
                        | GraphAtomKind::SourceSpan
                        | GraphAtomKind::Chunk
                        | GraphAtomKind::Frame
                )
            );
    }
    if role == "leftMention" || role == "rightMention" {
        return evidence_kind.is_some()
            || matches!(
                atom_kind,
                Some(GraphAtomKind::EvidenceAnchor | GraphAtomKind::SourceSpan)
            );
    }
    if matches!(
        role,
        "subject"
            | "source"
            | "target"
            | "actor"
            | "speaker"
            | "listener"
            | "agent"
            | "patient"
            | "recipient"
            | "theme"
            | "bearer"
            | "experiencer"
            | "topic"
            | "value"
            | "instrument"
            | "manner"
            | "cause"
            | "effect"
            | "object"
            | "location"
            | "time"
            | "state"
    ) {
        return matches!(
            atom_kind,
            Some(
                GraphAtomKind::Entity
                    | GraphAtomKind::Concept
                    | GraphAtomKind::Event
                    | GraphAtomKind::State
                    | GraphAtomKind::Claim
                    | GraphAtomKind::TimeAnchor
            )
        );
    }
    false
}
