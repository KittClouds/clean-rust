use phoenix_types::{GraphTruthDescriptor, GraphTruthKind, GraphTruthPlane};

use crate::promotion_lanes::PromotionLane;

impl PromotionLane {
    pub(crate) fn truth_descriptor(self) -> GraphTruthDescriptor {
        match self {
            Self::SituationWorldState => GraphTruthDescriptor {
                kind: GraphTruthKind::Assertion,
                plane: Some(GraphTruthPlane::WorldState),
            },
            Self::ModalFact(plane) => GraphTruthDescriptor {
                kind: GraphTruthKind::Assertion,
                plane: Some(plane),
            },
            Self::EventIdentityRoles | Self::CrossDocumentIdentity => GraphTruthDescriptor {
                kind: GraphTruthKind::Identity,
                plane: None,
            },
            Self::TemporalAnchors => GraphTruthDescriptor {
                kind: GraphTruthKind::Temporal,
                plane: Some(GraphTruthPlane::WorldState),
            },
            Self::CausalEdges => GraphTruthDescriptor {
                kind: GraphTruthKind::Causal,
                plane: Some(GraphTruthPlane::WorldState),
            },
            Self::SemanticPhase5(plane) => GraphTruthDescriptor {
                kind: GraphTruthKind::Semantic,
                plane: Some(plane),
            },
        }
    }

    pub(crate) fn policy_id(self) -> &'static str {
        match self {
            Self::SituationWorldState => "graph-post-promotion:situation-world-state",
            Self::ModalFact(GraphTruthPlane::Reported) => "graph-post-promotion:reported-facts",
            Self::ModalFact(GraphTruthPlane::Conditional) => {
                "graph-post-promotion:conditional-facts"
            }
            Self::ModalFact(GraphTruthPlane::Hypothetical) => {
                "graph-post-promotion:hypothetical-facts"
            }
            Self::ModalFact(GraphTruthPlane::Planned) => "graph-post-promotion:planned-facts",
            Self::ModalFact(_) => "graph-post-promotion:modal-facts",
            Self::EventIdentityRoles => "graph-post-promotion:event-identity-roles",
            Self::TemporalAnchors => "graph-post-promotion:temporal-anchors-relations",
            Self::CausalEdges => "graph-post-promotion:causal-edges",
            Self::SemanticPhase5(GraphTruthPlane::Reported) => {
                "graph-post-promotion:semantic-phase5-reported"
            }
            Self::SemanticPhase5(GraphTruthPlane::Conditional) => {
                "graph-post-promotion:semantic-phase5-conditional"
            }
            Self::SemanticPhase5(GraphTruthPlane::Hypothetical) => {
                "graph-post-promotion:semantic-phase5-hypothetical"
            }
            Self::SemanticPhase5(GraphTruthPlane::Planned) => {
                "graph-post-promotion:semantic-phase5-planned"
            }
            Self::SemanticPhase5(_) => "graph-post-promotion:semantic-phase5-world-state",
            Self::CrossDocumentIdentity => "graph-post-promotion:cross-document-identity",
        }
    }

    pub(crate) fn slug(self) -> &'static str {
        self.policy_id()
            .strip_prefix("graph-post-promotion:")
            .unwrap_or("promotion")
    }
}
