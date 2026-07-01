use compact_str::CompactString;
use serde::{Deserialize, Serialize};

use super::ChunkSemanticBridgeCandidate;

const OPAQUE_EVENT_CUES: &[&str] = &[
    "dialogue_event",
    "process_event",
    "authority_chain_event",
    "evidence_packet_event",
    "positioning_event",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BridgeQualityGateDecision {
    Accept,
    DemoteSameEntityOnly,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeQualityGateAudit {
    pub total: usize,
    pub accepted: usize,
    pub demoted_same_entity_only: usize,
}

pub fn bridge_quality_gate_decision(
    bridge: &ChunkSemanticBridgeCandidate,
) -> BridgeQualityGateDecision {
    if is_same_entity_only_bridge_suspect(bridge) {
        BridgeQualityGateDecision::DemoteSameEntityOnly
    } else {
        BridgeQualityGateDecision::Accept
    }
}

pub fn audit_chunk_semantic_bridge_quality_gate(
    bridges: &[ChunkSemanticBridgeCandidate],
) -> BridgeQualityGateAudit {
    let mut audit = BridgeQualityGateAudit {
        total: bridges.len(),
        ..BridgeQualityGateAudit::default()
    };
    for bridge in bridges {
        match bridge_quality_gate_decision(bridge) {
            BridgeQualityGateDecision::Accept => audit.accepted += 1,
            BridgeQualityGateDecision::DemoteSameEntityOnly => {
                audit.demoted_same_entity_only += 1;
            }
        }
    }
    audit
}

pub fn is_same_entity_only_bridge_suspect(bridge: &ChunkSemanticBridgeCandidate) -> bool {
    !bridge.supporting_entity_ids.is_empty()
        && !has_substantive_rationale(&bridge.rationale)
        && opaque_cue(bridge.source_cue.as_deref())
        && opaque_cue(bridge.target_cue.as_deref())
}

fn has_substantive_rationale(rationale: &[CompactString]) -> bool {
    rationale.iter().any(|row| {
        row.starts_with("causal_event_edge_seed")
            || row.starts_with("setup_cue_plus_later_payoff_cue")
            || row.starts_with("causal_language_spans_chunks")
            || row.starts_with("evidence_or_documentation_reframes_prior_chunk")
            || row.starts_with("relationship_cue_with_shared_participants")
            || row.starts_with("route_or_threshold_cue_spans_chunks")
            || row.starts_with("temporal_event_edge_route_seed")
            || row.starts_with("later_chunk_changes_prior_state")
            || row.starts_with("motif:")
    })
}

fn opaque_cue(cue: Option<&str>) -> bool {
    match cue {
        None => true,
        Some(value) => OPAQUE_EVENT_CUES.contains(&value),
    }
}
