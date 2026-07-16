use phoenix_semantic_v2::{
    DocumentArchive, EventIdentityScopeSidecar, MemoryClaimAtom, MemoryEventRecord, MemoryModality,
    MemoryScopeSidecar, MemoryStateRecord, SemanticCandidateStatus, SemanticEdgeFamily,
    SemanticGraphNodeKind, SemanticGraphNodeRecord,
};
use phoenix_types::{ClaimRecord, EventRecord, Proposition, SourceRange, StateRecord};
use rustc_hash::{FxHashMap, FxHasher};
use std::hash::{Hash, Hasher};

pub(crate) const CHUNK_KIND: &str = "chunk";
pub(crate) const CLAIM_KIND: &str = "claim";
pub(crate) const STATE_KIND: &str = "state";
pub(crate) const EVENT_KIND: &str = "event";
pub(crate) const ENTITY_KIND: &str = "entity";
pub(crate) const SEMANTIC_UNIT_PREFIX: &str = "semantic-unit::";
const MAX_UNIT_TEXT_BYTES: usize = 768;

#[derive(Clone)]
pub(crate) struct Prototype {
    pub(crate) node_id: String,
    pub(crate) ann_kind: &'static str,
    pub(crate) node_kind: SemanticGraphNodeKind,
    pub(crate) text_key: String,
    pub(crate) text: String,
    pub(crate) truth_plane: Option<String>,
    pub(crate) document_id: Option<String>,
    pub(crate) note_id: Option<String>,
    pub(crate) narrative_id: Option<String>,
    pub(crate) folder_id: Option<String>,
    pub(crate) folder_path: Option<String>,
    pub(crate) evidence_refs: Vec<String>,
    pub(crate) semantic_node: SemanticGraphNodeRecord,
    pub(crate) slot_key: Option<String>,
    pub(crate) value_key: Option<String>,
    pub(crate) primary_entity_id: Option<String>,
    pub(crate) secondary_entity_id: Option<String>,
}

pub(crate) fn build_prototypes(
    archives: &[DocumentArchive],
    event_identity_sidecar: Option<&EventIdentityScopeSidecar>,
    memory_sidecar: Option<&MemoryScopeSidecar>,
) -> Vec<Prototype> {
    let mut rows = Vec::new();
    for archive in archives {
        for chunk in &archive.chunks {
            rows.push(prototype(
                format!(
                    "chunk::{}::{}",
                    archive.manifest.document_id, chunk.chunk_id.0
                ),
                CHUNK_KIND,
                SemanticGraphNodeKind::Chunk,
                format!(
                    "chunk:{}:{}",
                    archive.manifest.document_id, chunk.chunk_id.0
                ),
                chunk.text.clone(),
                None,
                Some(archive.manifest.document_id.clone()),
                archive
                    .manifest
                    .note_id
                    .as_ref()
                    .map(|note_id| note_id.0.clone()),
                archive.manifest.scope.narrative_id.clone(),
                archive.manifest.scope.folder_id.clone(),
                archive.manifest.scope.folder_path.clone(),
                vec![format!(
                    "document:{}#bytes:{}-{}",
                    archive.manifest.document_id, chunk.range.start, chunk.range.end
                )],
                None,
                None,
                None,
                None,
            ));
        }
        push_document_semantic_unit_prototypes(&mut rows, archive);
    }
    if let Some(memory) = memory_sidecar {
        for claim in &memory.claims {
            rows.push(claim_prototype(claim, &memory.scope.narrative_id));
        }
        for state in &memory.states {
            rows.push(state_prototype(state, &memory.scope.narrative_id));
        }
        for event in &memory.events {
            rows.push(event_prototype(event, &memory.scope.narrative_id));
        }
        for entity in &memory.entity_cards {
            let mut text = entity.identity.canonical_name.clone();
            if !entity.identity.aliases.is_empty() {
                text.push_str(" aliases ");
                text.push_str(&entity.identity.aliases.join(" ; "));
            }
            if !entity.current_state.is_empty() {
                text.push_str(" states ");
                text.push_str(
                    &entity
                        .current_state
                        .iter()
                        .map(|state| format!("{} {}", state.slot_key, state.value))
                        .collect::<Vec<_>>()
                        .join(" ; "),
                );
            }
            rows.push(prototype(
                format!("entity::{}", entity.entity_id.0),
                ENTITY_KIND,
                SemanticGraphNodeKind::Entity,
                format!("entity:{}", entity.entity_id.0),
                text,
                None,
                None,
                None,
                memory.scope.narrative_id.clone(),
                memory.scope.folder_id.clone(),
                memory.scope.folder_path.clone(),
                entity.identity.continuity_refs.clone(),
                None,
                None,
                Some(entity.entity_id.0.clone()),
                None,
            ));
        }
    }
    if let Some(events) = event_identity_sidecar {
        for event in &events.canonical_events {
            rows.push(prototype(
                format!("graph::event::canonical::{}", event.canonical_event_id.0),
                EVENT_KIND,
                SemanticGraphNodeKind::Event,
                format!("canonical-event:{}", event.canonical_event_id.0),
                format!(
                    "{} {} {:?}",
                    event.canonical_label, event.normalized_predicate, event.participant_slots
                ),
                Some(modality_plane_label(Some(MemoryModality::Asserted))),
                event.document_ids.first().cloned(),
                None,
                events.scope.narrative_id.clone(),
                events.scope.folder_id.clone(),
                events.scope.folder_path.clone(),
                event.evidence_refs.clone(),
                None,
                None,
                None,
                None,
            ));
        }
    }
    rows
}

fn push_document_semantic_unit_prototypes(rows: &mut Vec<Prototype>, archive: &DocumentArchive) {
    let Some(substrate) = archive.causal_substrate.as_ref() else {
        return;
    };
    let proposition_by_id = substrate
        .propositions
        .iter()
        .map(|proposition| (proposition.proposition_id.as_str(), proposition))
        .collect::<FxHashMap<_, _>>();
    for claim in &substrate.semantic_claims {
        if let Some(prototype) = document_claim_prototype(archive, claim, &proposition_by_id) {
            rows.push(prototype);
        }
    }
    for state in &substrate.semantic_states {
        if let Some(prototype) = document_state_prototype(archive, state, &proposition_by_id) {
            rows.push(prototype);
        }
    }
    for event in &substrate.semantic_events {
        if let Some(prototype) = document_event_prototype(archive, event, &proposition_by_id) {
            rows.push(prototype);
        }
    }
}

fn document_claim_prototype(
    archive: &DocumentArchive,
    claim: &ClaimRecord,
    proposition_by_id: &FxHashMap<&str, &Proposition>,
) -> Option<Prototype> {
    let claim_id = claim.claim_id.as_ref()?.0.as_str();
    let proposition = proposition_by_id
        .get(claim.proposition_id.as_str())
        .copied();
    document_semantic_unit_prototype(
        archive,
        CLAIM_KIND,
        SemanticGraphNodeKind::Claim,
        claim_id,
        claim.label.as_str(),
        proposition,
    )
}

fn document_state_prototype(
    archive: &DocumentArchive,
    state: &StateRecord,
    proposition_by_id: &FxHashMap<&str, &Proposition>,
) -> Option<Prototype> {
    let state_id = state.state_id.as_ref()?.0.as_str();
    let proposition = proposition_by_id
        .get(state.proposition_id.as_str())
        .copied();
    document_semantic_unit_prototype(
        archive,
        STATE_KIND,
        SemanticGraphNodeKind::State,
        state_id,
        state.label.as_str(),
        proposition,
    )
}

fn document_event_prototype(
    archive: &DocumentArchive,
    event: &EventRecord,
    proposition_by_id: &FxHashMap<&str, &Proposition>,
) -> Option<Prototype> {
    let event_id = event.event_id.as_ref()?.0.as_str();
    let proposition = proposition_by_id
        .get(event.proposition_id.as_str())
        .copied();
    document_semantic_unit_prototype(
        archive,
        EVENT_KIND,
        SemanticGraphNodeKind::Event,
        event_id,
        event.label.as_str(),
        proposition,
    )
}

fn document_semantic_unit_prototype(
    archive: &DocumentArchive,
    ann_kind: &'static str,
    node_kind: SemanticGraphNodeKind,
    raw_id: &str,
    fallback_label: &str,
    proposition: Option<&Proposition>,
) -> Option<Prototype> {
    let proposition = proposition.filter(|value| has_complete_situation_frame(value))?;
    let document_id = archive.manifest.document_id.as_str();
    let node_id = format!("{SEMANTIC_UNIT_PREFIX}{ann_kind}::{document_id}::{raw_id}");
    let text = proposition_unit_text(proposition, fallback_label);
    let slot_key = Some(proposition_slot_key(proposition));
    let value_key = proposition_value_key(proposition);
    let primary_entity_id = proposition_entity_id(proposition, 0);
    let secondary_entity_id = proposition_entity_id(proposition, 1);
    let truth_plane = Some(proposition_truth_plane(proposition));
    let evidence_refs = semantic_unit_evidence_refs(ann_kind, document_id, raw_id, proposition);
    Some(prototype(
        node_id,
        ann_kind,
        node_kind,
        format!("{ann_kind}:{document_id}:{raw_id}"),
        text,
        truth_plane,
        Some(document_id.to_owned()),
        archive
            .manifest
            .note_id
            .as_ref()
            .map(|note_id| note_id.0.clone()),
        archive.manifest.scope.narrative_id.clone(),
        archive.manifest.scope.folder_id.clone(),
        archive.manifest.scope.folder_path.clone(),
        evidence_refs,
        slot_key,
        value_key,
        primary_entity_id,
        secondary_entity_id,
    ))
}

fn has_complete_situation_frame(proposition: &Proposition) -> bool {
    let has_predicate = !proposition.predicate.predicate.trim().is_empty();
    let has_role = proposition.arguments.iter().any(|argument| {
        !argument.role.trim().is_empty()
            && (argument.entity_id.is_some() || argument.range.is_some())
    });
    let has_evidence = !proposition.evidence.is_empty();
    let has_plane = !proposition_truth_plane(proposition).is_empty();
    let has_time = proposition_unit_range(proposition).is_some();
    has_predicate && has_role && has_evidence && has_plane && has_time
}

fn proposition_unit_text(proposition: &Proposition, fallback_label: &str) -> String {
    if let Some(evidence_label) = proposition
        .evidence
        .iter()
        .map(|evidence| evidence.label.as_str().trim())
        .find(|label| !label.is_empty())
    {
        return truncate_unit_text(evidence_label);
    }
    let predicate = proposition.predicate.predicate.as_str().trim();
    if predicate.is_empty() {
        truncate_unit_text(fallback_label)
    } else {
        truncate_unit_text(predicate)
    }
}

fn truncate_unit_text(value: &str) -> String {
    let value = value.trim();
    if value.len() <= MAX_UNIT_TEXT_BYTES {
        return value.to_owned();
    }
    let mut end = MAX_UNIT_TEXT_BYTES;
    while end > 0 && !value.is_char_boundary(end) {
        end -= 1;
    }
    value[..end].trim_end().to_owned()
}

fn proposition_slot_key(proposition: &Proposition) -> String {
    let relation = proposition.predicate.relation_type.as_str().trim();
    if relation.is_empty() {
        normalized_key(proposition.predicate.predicate.as_str())
    } else {
        normalized_key(relation)
    }
}

fn proposition_value_key(proposition: &Proposition) -> Option<String> {
    proposition
        .arguments
        .get(1)
        .and_then(|argument| argument.entity_id.as_ref())
        .map(|entity_id| entity_id.0.clone())
}

fn proposition_entity_id(proposition: &Proposition, index: usize) -> Option<String> {
    proposition
        .arguments
        .get(index)
        .and_then(|argument| argument.entity_id.as_ref())
        .map(|entity_id| entity_id.0.clone())
}

fn proposition_truth_plane(proposition: &Proposition) -> String {
    if proposition.conditional.is_some() {
        return "conditional".to_owned();
    }
    if proposition.quote.is_some() || proposition.attribution.is_some() {
        return "reported".to_owned();
    }
    proposition
        .scope_ops
        .iter()
        .find_map(|operation| operation.modality.as_ref())
        .map(|modality| normalized_key(modality.as_str()))
        .filter(|modality| !modality.is_empty())
        .unwrap_or_else(|| "world".to_owned())
}

fn semantic_unit_evidence_refs(
    ann_kind: &str,
    document_id: &str,
    raw_id: &str,
    proposition: &Proposition,
) -> Vec<String> {
    let mut refs = vec![format!("semantic-unit:{ann_kind}:{document_id}:{raw_id}")];
    refs.push(format!("proposition:{}", proposition.proposition_id));
    if let Some(range) = proposition_unit_range(proposition) {
        refs.push(format!(
            "document:{document_id}#bytes:{}-{}",
            range.start, range.end
        ));
    }
    refs
}

fn proposition_unit_range(proposition: &Proposition) -> Option<SourceRange> {
    proposition
        .clause_range
        .or_else(|| proposition.evidence.first().map(|evidence| evidence.range))
        .or(Some(proposition.predicate.trigger_range))
}

pub(crate) fn neighbor_families(
    kind: SemanticGraphNodeKind,
) -> [(&'static str, SemanticEdgeFamily); 2] {
    match kind {
        SemanticGraphNodeKind::Chunk => [
            (CHUNK_KIND, SemanticEdgeFamily::ChunkNeighbor),
            ("", SemanticEdgeFamily::Unknown),
        ],
        SemanticGraphNodeKind::Claim => [
            (CLAIM_KIND, SemanticEdgeFamily::ClaimSupport),
            ("", SemanticEdgeFamily::Unknown),
        ],
        SemanticGraphNodeKind::State => [
            (STATE_KIND, SemanticEdgeFamily::StateSupport),
            ("", SemanticEdgeFamily::Unknown),
        ],
        SemanticGraphNodeKind::Entity => [
            (STATE_KIND, SemanticEdgeFamily::EntityStateSupport),
            (EVENT_KIND, SemanticEdgeFamily::EntityEventSupport),
        ],
        SemanticGraphNodeKind::Event => [
            ("", SemanticEdgeFamily::Unknown),
            ("", SemanticEdgeFamily::Unknown),
        ],
        SemanticGraphNodeKind::Unknown => [
            ("", SemanticEdgeFamily::Unknown),
            ("", SemanticEdgeFamily::Unknown),
        ],
    }
}

pub(crate) fn resolve_family(
    base: SemanticEdgeFamily,
    source: &Prototype,
    target: &Prototype,
) -> SemanticEdgeFamily {
    match base {
        SemanticEdgeFamily::ClaimSupport
            if source.slot_key == target.slot_key && source.value_key != target.value_key =>
        {
            SemanticEdgeFamily::ClaimContradiction
        }
        SemanticEdgeFamily::StateSupport
            if source.slot_key == target.slot_key && source.value_key != target.value_key =>
        {
            SemanticEdgeFamily::StateContradiction
        }
        _ => base,
    }
}

pub(crate) fn truth_planes_compatible(left: Option<&str>, right: Option<&str>) -> bool {
    match (left, right) {
        (Some(left), Some(right)) => left == right || left == "world" || right == "world",
        _ => true,
    }
}

pub(crate) fn node_kind_label(kind: SemanticGraphNodeKind) -> &'static str {
    match kind {
        SemanticGraphNodeKind::Chunk => CHUNK_KIND,
        SemanticGraphNodeKind::Claim => CLAIM_KIND,
        SemanticGraphNodeKind::State => STATE_KIND,
        SemanticGraphNodeKind::Event => EVENT_KIND,
        SemanticGraphNodeKind::Entity => ENTITY_KIND,
        SemanticGraphNodeKind::Unknown => "unknown",
    }
}

pub(crate) fn family_label(family: SemanticEdgeFamily) -> &'static str {
    match family {
        SemanticEdgeFamily::ChunkNeighbor => "chunk_neighbor",
        SemanticEdgeFamily::ClaimSupport => "claim_support",
        SemanticEdgeFamily::ClaimContradiction => "claim_contradiction",
        SemanticEdgeFamily::StateSupport => "state_support",
        SemanticEdgeFamily::StateContradiction => "state_contradiction",
        SemanticEdgeFamily::ContradictorySupportRegion => "contradictory_support_region",
        SemanticEdgeFamily::SameSlotFamily => "same_slot_family",
        SemanticEdgeFamily::SameProcess => "same_process",
        SemanticEdgeFamily::RelatedEvent => "related_event",
        SemanticEdgeFamily::MissingIntermediateCause => "missing_intermediate_cause",
        SemanticEdgeFamily::EntityStateSupport => "entity_state_support",
        SemanticEdgeFamily::EntityEventSupport => "entity_event_support",
        SemanticEdgeFamily::EventNeighbor => "event_neighbor",
        SemanticEdgeFamily::EntityRoleNeighbor => "entity_role_neighbor",
        SemanticEdgeFamily::Unknown => "unknown",
    }
}

pub(crate) fn status_label(status: SemanticCandidateStatus) -> &'static str {
    match status {
        SemanticCandidateStatus::Generated => "generated",
        SemanticCandidateStatus::ReviewedSupport => "reviewed_support",
        SemanticCandidateStatus::ReviewedContradiction => "reviewed_contradiction",
        SemanticCandidateStatus::Deferred => "deferred",
        SemanticCandidateStatus::Rejected => "rejected",
    }
}

fn prototype(
    node_id: String,
    ann_kind: &'static str,
    node_kind: SemanticGraphNodeKind,
    text_key: String,
    text: String,
    truth_plane: Option<String>,
    document_id: Option<String>,
    note_id: Option<String>,
    narrative_id: Option<String>,
    folder_id: Option<String>,
    folder_path: Option<String>,
    evidence_refs: Vec<String>,
    slot_key: Option<String>,
    value_key: Option<String>,
    primary_entity_id: Option<String>,
    secondary_entity_id: Option<String>,
) -> Prototype {
    let text_hash = fx_hash64(&text);
    Prototype {
        semantic_node: SemanticGraphNodeRecord {
            node_id: node_id.clone(),
            node_kind,
            document_id: document_id.clone(),
            narrative_id: narrative_id.clone(),
            text_key: text_key.clone(),
            text_hash,
            truth_plane: truth_plane.clone(),
            evidence_refs: evidence_refs.clone(),
        },
        node_id,
        ann_kind,
        node_kind,
        text_key,
        text,
        truth_plane,
        document_id,
        note_id,
        narrative_id,
        folder_id,
        folder_path,
        evidence_refs,
        slot_key,
        value_key,
        primary_entity_id,
        secondary_entity_id,
    }
}

fn claim_prototype(claim: &MemoryClaimAtom, narrative_id: &Option<String>) -> Prototype {
    prototype(
        format!("graph::claim::{}", claim.claim_id),
        CLAIM_KIND,
        SemanticGraphNodeKind::Claim,
        format!("claim:{}", claim.claim_id),
        format!(
            "{} {} {} {}",
            claim.subject_label, claim.slot_key, claim.object_label, claim.object_value
        ),
        Some(modality_plane_label(Some(claim.modality))),
        Some(claim.document_id.clone()),
        None,
        narrative_id.clone(),
        None,
        None,
        claim.evidence_refs.clone(),
        Some(claim.slot_key.clone()),
        Some(normalized_key(&claim.object_value)),
        claim
            .source_entity_id
            .as_ref()
            .map(|entity_id| entity_id.0.clone()),
        claim
            .object_entity_id
            .as_ref()
            .or(claim.target_entity_id.as_ref())
            .map(|entity_id| entity_id.0.clone()),
    )
}

fn state_prototype(state: &MemoryStateRecord, narrative_id: &Option<String>) -> Prototype {
    prototype(
        format!("graph::state::{}", state.state_id),
        STATE_KIND,
        SemanticGraphNodeKind::State,
        format!("state:{}", state.state_id),
        format!("{} {}", state.slot_key, state.value),
        Some(state.source_class.clone()),
        None,
        None,
        narrative_id.clone(),
        None,
        None,
        state
            .claim_ids
            .iter()
            .map(|claim_id| format!("claim:{claim_id}"))
            .collect(),
        Some(state.slot_key.clone()),
        Some(normalized_key(&state.value)),
        Some(state.entity_id.0.clone()),
        state
            .value_entity_id
            .as_ref()
            .map(|entity_id| entity_id.0.clone()),
    )
}

fn event_prototype(event: &MemoryEventRecord, narrative_id: &Option<String>) -> Prototype {
    prototype(
        format!("graph::event::memory::{}", event.event_id),
        EVENT_KIND,
        SemanticGraphNodeKind::Event,
        format!("event:{}", event.event_id),
        format!(
            "{} {} {} {}",
            event.kind,
            event.slot_key,
            event.old_value.clone().unwrap_or_default(),
            event.new_value.clone().unwrap_or_default()
        ),
        None,
        Some(event.document_id.clone()),
        None,
        narrative_id.clone(),
        None,
        None,
        event.evidence_refs.clone(),
        Some(event.slot_key.clone()),
        Some(normalized_key(
            event.new_value.as_deref().unwrap_or_default(),
        )),
        event
            .subject_entity_id
            .as_ref()
            .map(|entity_id| entity_id.0.clone()),
        event
            .object_entity_id
            .as_ref()
            .map(|entity_id| entity_id.0.clone()),
    )
}

fn modality_plane_label(modality: Option<MemoryModality>) -> String {
    match modality.unwrap_or(MemoryModality::Asserted) {
        MemoryModality::Asserted | MemoryModality::Observed | MemoryModality::Inferred => "world",
        MemoryModality::Reported => "reported",
        MemoryModality::Planned => "planned",
        MemoryModality::Conditional => "conditional",
        MemoryModality::Hypothetical => "hypothetical",
    }
    .to_owned()
}

fn normalized_key(value: &str) -> String {
    value.trim().to_ascii_lowercase()
}

fn fx_hash64(value: &str) -> u64 {
    let mut hasher = FxHasher::default();
    value.hash(&mut hasher);
    hasher.finish()
}

#[cfg(test)]
mod tests {
    use super::{prototype, resolve_family, truth_planes_compatible, CLAIM_KIND, STATE_KIND};
    use phoenix_semantic_v2::{SemanticEdgeFamily, SemanticGraphNodeKind};

    #[test]
    fn resolve_family_promotes_slot_value_mismatches_to_contradiction() {
        let left = prototype(
            "graph::state::1".to_owned(),
            STATE_KIND,
            SemanticGraphNodeKind::State,
            "state:1".to_owned(),
            "entity.employer Acme".to_owned(),
            Some("world".to_owned()),
            None,
            None,
            None,
            None,
            None,
            Vec::new(),
            Some("entity.employer".to_owned()),
            Some("acme".to_owned()),
            None,
            None,
        );
        let right = prototype(
            "graph::state::2".to_owned(),
            STATE_KIND,
            SemanticGraphNodeKind::State,
            "state:2".to_owned(),
            "entity.employer Globex".to_owned(),
            Some("world".to_owned()),
            None,
            None,
            None,
            None,
            None,
            Vec::new(),
            Some("entity.employer".to_owned()),
            Some("globex".to_owned()),
            None,
            None,
        );
        assert_eq!(
            resolve_family(SemanticEdgeFamily::StateSupport, &left, &right),
            SemanticEdgeFamily::StateContradiction
        );
        let claim_left = prototype(
            "graph::claim::1".to_owned(),
            CLAIM_KIND,
            SemanticGraphNodeKind::Claim,
            "claim:1".to_owned(),
            "Alice employer Acme".to_owned(),
            Some("world".to_owned()),
            None,
            None,
            None,
            None,
            None,
            Vec::new(),
            Some("entity.employer".to_owned()),
            Some("acme".to_owned()),
            None,
            None,
        );
        let claim_right = prototype(
            "graph::claim::2".to_owned(),
            CLAIM_KIND,
            SemanticGraphNodeKind::Claim,
            "claim:2".to_owned(),
            "Alice employer Globex".to_owned(),
            Some("world".to_owned()),
            None,
            None,
            None,
            None,
            None,
            Vec::new(),
            Some("entity.employer".to_owned()),
            Some("globex".to_owned()),
            None,
            None,
        );
        assert_eq!(
            resolve_family(SemanticEdgeFamily::ClaimSupport, &claim_left, &claim_right),
            SemanticEdgeFamily::ClaimContradiction
        );
    }

    #[test]
    fn truth_plane_compatibility_keeps_world_open_but_blocks_cross_branch_leaks() {
        assert!(truth_planes_compatible(Some("world"), Some("reported")));
        assert!(truth_planes_compatible(
            Some("conditional"),
            Some("conditional")
        ));
        assert!(!truth_planes_compatible(Some("reported"), Some("planned")));
    }
}
