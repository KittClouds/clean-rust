use compact_str::CompactString;

use crate::types::{GraphDocumentCompilerHyperedgeRole, GraphEmbeddingTarget};

use super::{AtlasObjectStatus, GraphFamily, ManifoldAdmission};

pub(super) fn admission_for_target(target: &GraphEmbeddingTarget) -> ManifoldAdmission {
    match target.admission_status.as_deref() {
        Some("admitted") => ManifoldAdmission::Admitted,
        Some("deferred") => ManifoldAdmission::Deferred,
        Some("rejected") => ManifoldAdmission::Rejected,
        _ => ManifoldAdmission::Candidate,
    }
}

pub(super) fn status_for_admission(admission: ManifoldAdmission) -> AtlasObjectStatus {
    match admission {
        ManifoldAdmission::Admitted => AtlasObjectStatus::Accepted,
        ManifoldAdmission::Deferred => AtlasObjectStatus::Deferred,
        ManifoldAdmission::Rejected => AtlasObjectStatus::Rejected,
        ManifoldAdmission::Candidate => AtlasObjectStatus::Proposed,
    }
}

pub(super) fn target_lane(
    target: &GraphEmbeddingTarget,
    family: GraphFamily,
) -> Option<CompactString> {
    target.lane.clone().or_else(|| match target.kind.as_str() {
        "note" | "structureRoot" => Some("document_spine".into()),
        "chunk" | "documentUnit" => Some("chunk_spine".into()),
        "entity" => Some("entity_anchor".into()),
        "anchor" | "evidenceSpan" => Some("anchor_evidence".into()),
        "event" => Some("event_identity".into()),
        "temporalFact" => Some("temporal_fact".into()),
        "causalFact" => Some("causal_fact".into()),
        "memoryState" => Some("memory_state".into()),
        "graphFact" if family == GraphFamily::Review => Some("review".into()),
        "graphFact" if family == GraphFamily::Discourse => Some("discourse".into()),
        "graphFact" => Some("relationship_fact".into()),
        _ if family == GraphFamily::Hypergraph => Some("hypergraph".into()),
        _ => None,
    })
}

pub(super) fn target_structural_role(
    target: &GraphEmbeddingTarget,
    family: GraphFamily,
    lane: Option<&str>,
) -> Option<CompactString> {
    target
        .structural_role
        .clone()
        .or_else(|| match target.kind.as_str() {
            "note" | "structureRoot" => Some("root".into()),
            "chunk" => Some("spine".into()),
            "anchor" | "evidenceSpan" => Some("evidence".into()),
            "entity" | "memoryState" => Some("child".into()),
            "graphFact" | "event" | "temporalFact" | "causalFact" => Some("fact".into()),
            "documentUnit" => Some("child".into()),
            _ if lane == Some("chunk_spine") => Some("spine".into()),
            _ if family == GraphFamily::Hypergraph => Some("role".into()),
            _ => None,
        })
}

pub(super) fn target_style_key(
    target: &GraphEmbeddingTarget,
    family: GraphFamily,
    document_unit_kind: Option<&str>,
) -> Option<CompactString> {
    match target.kind.as_str() {
        "note" | "structureRoot" => Some("document".into()),
        "chunk" => Some("chunk".into()),
        "documentUnit" => document_unit_kind
            .filter(|kind| !is_sentence_or_paragraph_kind(kind))
            .map(|_| "chunk".into())
            .or_else(|| Some("chunk".into())),
        "entity" => target
            .entity_kind
            .clone()
            .or_else(|| entity_kind_from_target(target)),
        "anchor" | "evidenceSpan" => Some("anchor".into()),
        "event" => Some("eventNode".into()),
        "temporalFact" => Some("temporalFact".into()),
        "causalFact" => Some("causalFact".into()),
        "memoryState" => Some(memory_style_key(
            target.label.as_str(),
            target.text.as_str(),
        )),
        "graphFact" if family == GraphFamily::Review => Some("rankStatus".into()),
        "graphFact" if family == GraphFamily::Discourse => Some("communication".into()),
        "graphFact" => Some(relation_style_key(
            target.label.as_str(),
            target.text.as_str(),
        )),
        _ if family == GraphFamily::Hypergraph => Some("relationship".into()),
        _ => None,
    }
}

pub(super) fn document_unit_kind(target: &GraphEmbeddingTarget) -> Option<CompactString> {
    if target.kind != "documentUnit" {
        return None;
    }
    target
        .document_unit_kind
        .clone()
        .or_else(|| line_value(target.text.as_str(), "kind:"))
        .or_else(|| line_value(target.text.as_str(), "document_sidecar:"))
}

pub(super) fn state_context_kind(target: &GraphEmbeddingTarget) -> Option<CompactString> {
    if target.kind != "memoryState" {
        return target.state_context_kind.clone();
    }
    target.state_context_kind.clone().or_else(|| {
        Some(memory_style_key(
            target.label.as_str(),
            target.text.as_str(),
        ))
    })
}

pub(super) fn entity_kind_from_target(target: &GraphEmbeddingTarget) -> Option<CompactString> {
    if target.kind != "entity" {
        return None;
    }
    line_value(target.text.as_str(), "kind:").or_else(|| {
        target
            .source_id
            .split_once(':')
            .map(|(kind, _)| kind.into())
    })
}

pub(super) fn story_edge_style_key(kind: &str) -> CompactString {
    match kind {
        "temporalFact" => "temporalFact".into(),
        "causalFact" => "causalFact".into(),
        _ => "graphFact".into(),
    }
}

pub(super) fn story_edge_lane(kind: &str) -> CompactString {
    match kind {
        "temporalFact" => "temporal_fact".into(),
        "causalFact" => "causal_fact".into(),
        _ => "relationship_fact".into(),
    }
}

pub(super) fn relation_style_key(kind: &str, label: &str) -> CompactString {
    let token = compact_token(&format!("{kind} {label}"));
    if token.contains("cooccurswith")
        || token.contains("cooccurrence")
        || token.contains("cooccurs")
    {
        "cooccurrence".into()
    } else if token.contains("observe") {
        "observation".into()
    } else if token.contains("comment") || token.contains("communication") {
        "communication".into()
    } else if token.contains("authority") || token.contains("command") {
        "authority".into()
    } else if token.contains("approval") {
        "approval".into()
    } else if token.contains("family") {
        "family".into()
    } else if token.contains("intimacy") {
        "intimacy".into()
    } else if token.contains("transfer") {
        "transfer".into()
    } else if token.contains("scenepresence") {
        "scenePresence".into()
    } else {
        "relationship".into()
    }
}

pub(super) fn memory_style_key(key: &str, value: &str) -> CompactString {
    let token = compact_token(&format!("{key} {value}"));
    if token.contains("decisionstate")
        || token.contains("decision")
        || token.contains("approved")
        || token.contains("accepted")
    {
        "decisionState".into()
    } else if token.contains("rankorstatus")
        || token.contains("rankstatus")
        || token.contains("rank")
    {
        "rankStatus".into()
    } else if token.contains("servicecontext")
        || token.contains("servicerank")
        || token.contains("service")
    {
        "serviceContext".into()
    } else if token.contains("affiliationcontext")
        || token.contains("affiliatecontext")
        || token.contains("affiliantcontext")
        || token.contains("affiliation")
    {
        "affiliationContext".into()
    } else if token.contains("familycontext") || token.contains("family") {
        "familyContext".into()
    } else {
        "memoryState".into()
    }
}

pub(super) fn hyperedge_role_style_key(role: &GraphDocumentCompilerHyperedgeRole) -> CompactString {
    match role.target_kind.as_str() {
        "entity" => "relationship".into(),
        "evidence_span" => "anchor".into(),
        "document_unit" | "retrieval_unit" => "chunk".into(),
        _ => "relationship".into(),
    }
}

fn line_value(text: &str, prefix: &str) -> Option<CompactString> {
    text.lines()
        .find_map(|line| line.trim().strip_prefix(prefix).map(str::trim))
        .filter(|value| !value.is_empty())
        .map(CompactString::from)
}

fn is_sentence_or_paragraph_kind(kind: &str) -> bool {
    matches!(
        compact_token(kind).as_str(),
        "sentence"
            | "textsentence"
            | "documentsentence"
            | "paragraph"
            | "textparagraph"
            | "documentparagraph"
            | "paragraphgroup"
    )
}

fn compact_token(value: &str) -> String {
    value
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}
