use compact_str::CompactString;
use hashbrown::HashMap;
use phoenix_graph_kernel::{
    project_graph_proposal_outcomes, GraphProposalBatchReceipt, GraphProposalOutcomeKind,
    GraphProposalReceiptError, GraphTruthCommit,
};
use thiserror::Error;

use crate::promotion_learner::{
    GraphPromotionLinearModel, GraphPromotionModelError, GraphPromotionTrainingConfig,
    GraphPromotionTrainingExample,
};

#[derive(Clone, Debug, PartialEq)]
pub struct GraphPromotionOutcomeTrainingExample {
    pub receipt_id: CompactString,
    pub proposal_id: CompactString,
    pub outcome: GraphProposalOutcomeKind,
    pub example: GraphPromotionTrainingExample,
}

pub fn build_outcome_backed_training_examples(
    receipts: &[GraphProposalBatchReceipt],
    commits: &[GraphTruthCommit],
) -> Result<Vec<GraphPromotionOutcomeTrainingExample>, GraphPromotionTrainingError> {
    let outcomes = project_graph_proposal_outcomes(receipts, commits)?;
    let mut outcome_by_key =
        HashMap::<(CompactString, CompactString), GraphProposalOutcomeKind>::with_capacity(
            outcomes.len(),
        );
    for outcome in outcomes {
        outcome_by_key.insert((outcome.receipt_id, outcome.proposal_id), outcome.outcome);
    }

    let mut examples = Vec::with_capacity(receipts.iter().map(|value| value.proposals.len()).sum());
    for receipt in receipts {
        for proposal in &receipt.proposals {
            let key = (receipt.receipt_id.clone(), proposal.proposal_id.clone());
            let Some(outcome) = outcome_by_key.get(&key).copied() else {
                return Err(GraphPromotionTrainingError::MissingOutcome {
                    receipt_id: key.0,
                    proposal_id: key.1,
                });
            };
            let (label, weight) = label_and_weight(outcome);
            examples.push(GraphPromotionOutcomeTrainingExample {
                receipt_id: receipt.receipt_id.clone(),
                proposal_id: proposal.proposal_id.clone(),
                outcome,
                example: GraphPromotionTrainingExample {
                    features: proposal.features,
                    label,
                    weight,
                },
            });
        }
    }
    examples.sort_unstable_by(|left, right| {
        left.receipt_id
            .cmp(&right.receipt_id)
            .then_with(|| left.proposal_id.cmp(&right.proposal_id))
    });
    Ok(examples)
}

pub fn fixed_width_training_examples(
    examples: &[GraphPromotionOutcomeTrainingExample],
) -> Vec<GraphPromotionTrainingExample> {
    examples.iter().map(|value| value.example).collect()
}

pub fn fit_shadow_promotion_model_from_history(
    model_id: impl Into<CompactString>,
    receipts: &[GraphProposalBatchReceipt],
    commits: &[GraphTruthCommit],
    config: GraphPromotionTrainingConfig,
) -> Result<GraphPromotionHistoryModel, GraphPromotionTrainingError> {
    let outcome_examples = build_outcome_backed_training_examples(receipts, commits)?;
    let examples = fixed_width_training_examples(&outcome_examples);
    let model = GraphPromotionLinearModel::fit_ftrl(model_id, &examples, config)?;
    Ok(GraphPromotionHistoryModel {
        model,
        outcome_examples,
    })
}

#[derive(Clone, Debug, PartialEq)]
pub struct GraphPromotionHistoryModel {
    pub model: GraphPromotionLinearModel,
    pub outcome_examples: Vec<GraphPromotionOutcomeTrainingExample>,
}

fn label_and_weight(outcome: GraphProposalOutcomeKind) -> (bool, f32) {
    match outcome {
        GraphProposalOutcomeKind::Active => (true, 1.0),
        GraphProposalOutcomeKind::Superseded => (false, 0.75),
        GraphProposalOutcomeKind::Retracted | GraphProposalOutcomeKind::Reverted => (false, 1.0),
        GraphProposalOutcomeKind::Uncommitted => (false, 0.35),
    }
}

#[derive(Debug, Error)]
pub enum GraphPromotionTrainingError {
    #[error(transparent)]
    OutcomeProjection(#[from] GraphProposalReceiptError),
    #[error(transparent)]
    Model(#[from] GraphPromotionModelError),
    #[error("missing graph proposal outcome for receipt '{receipt_id}' proposal '{proposal_id}'")]
    MissingOutcome {
        receipt_id: CompactString,
        proposal_id: CompactString,
    },
}
