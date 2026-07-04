use compact_str::CompactString;
use hashbrown::{HashMap, HashSet};
use phoenix_graph_kernel::{
    project_graph_proposal_outcomes, GraphProposalBatchReceipt, GraphProposalObservation,
    GraphProposalOutcomeKind, GraphProposalReceiptError, GraphProposalStatus, GraphTruthAtomKey,
    GraphTruthCommit, GraphTruthLineage, GraphTruthLineageError,
};
use phoenix_types::{GraphTruthDescriptor, GraphTruthKind, GraphTruthOperation};
use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fmt;

pub const GRAPH_PROMOTION_VERDICT_SCHEMA_VERSION: &str = "phoenix-graph-promotion-verdict/v1";

const NLI_SUPPORT_FEATURE: usize = 2;
const NLI_CONTRADICTION_FEATURE: usize = 3;
const NLI_PRESENT_FEATURE: usize = 15;
const MIN_NLI_SUPPORT_MILLIS: i16 = 500;
const CONTRADICTION_MARGIN_MILLIS: i16 = 50;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphPromotionUserOverrideKind {
    Approve,
    Reject,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphPromotionUserOverride {
    pub receipt_id: CompactString,
    pub proposal_id: CompactString,
    pub kind: GraphPromotionUserOverrideKind,
    pub user_id: CompactString,
    pub rationale: CompactString,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphPromotionVerdictStatus {
    Acceptable,
    AlreadyCommitted,
    Blocked,
    Deferred,
    Rejected,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphPromotionGateKind {
    Receipt,
    Evidence,
    WitnessCount,
    Contradiction,
    TemporalCausalFit,
    NliFit,
    UserOverride,
    Rollback,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GraphPromotionGateStatus {
    Pass,
    Block,
    NotRequired,
    Override,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphPromotionVerdictGate {
    pub kind: GraphPromotionGateKind,
    pub status: GraphPromotionGateStatus,
    pub summary: CompactString,
    pub score_millis: Option<i16>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphPromotionRollbackPlan {
    pub operation: Option<GraphTruthOperation>,
    pub reverses_commit_id: Option<CompactString>,
    pub available_now: bool,
    pub available_after_commit: bool,
    pub rationale: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphPromotionApplyPlan {
    pub operation: Option<GraphTruthOperation>,
    pub predecessor_commit_id: Option<CompactString>,
    pub rationale: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphPromotionVerdictRow {
    pub id: CompactString,
    pub receipt_id: CompactString,
    pub proposal_id: CompactString,
    pub atom: GraphTruthAtomKey,
    pub family: CompactString,
    pub truth: GraphTruthDescriptor,
    pub candidate_status: GraphProposalStatus,
    pub outcome: GraphProposalOutcomeKind,
    pub status: GraphPromotionVerdictStatus,
    pub commit_id: Option<CompactString>,
    pub evidence_refs: Vec<CompactString>,
    pub witness_count: u16,
    pub nli_support_millis: Option<i16>,
    pub nli_contradiction_millis: Option<i16>,
    pub user_override: Option<GraphPromotionUserOverrideKind>,
    pub deterministic_score_millis: Option<u16>,
    pub apply_plan: GraphPromotionApplyPlan,
    pub rollback_plan: GraphPromotionRollbackPlan,
    pub gates: Vec<GraphPromotionVerdictGate>,
    pub rationale: CompactString,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphPromotionVerdictAudit {
    pub total: usize,
    pub acceptable: usize,
    pub already_committed: usize,
    pub blocked: usize,
    pub deferred: usize,
    pub rejected: usize,
    pub rollback_available: usize,
    pub evidence_blocked: usize,
    pub contradiction_blocked: usize,
    pub nli_blocked: usize,
    pub user_overrides: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphPromotionVerdictCertificate {
    pub schema_version: CompactString,
    pub source: CompactString,
    pub no_topology_writes: bool,
    pub receipt_count: usize,
    pub commit_count: usize,
    pub audit: GraphPromotionVerdictAudit,
    pub rows: Vec<GraphPromotionVerdictRow>,
}

pub fn build_graph_promotion_verdict_certificate(
    receipts: &[GraphProposalBatchReceipt],
    commits: &[GraphTruthCommit],
    user_overrides: &[GraphPromotionUserOverride],
) -> Result<GraphPromotionVerdictCertificate, GraphPromotionVerdictError> {
    let outcomes = project_graph_proposal_outcomes(receipts, commits)?;
    let lineage = GraphTruthLineage::build(commits.to_vec())?;
    let outcome_by_proposal = outcomes
        .into_iter()
        .map(|outcome| {
            (
                (outcome.receipt_id.clone(), outcome.proposal_id.clone()),
                outcome,
            )
        })
        .collect::<HashMap<_, _>>();
    let overrides = user_overrides
        .iter()
        .map(|row| ((row.receipt_id.clone(), row.proposal_id.clone()), row.kind))
        .collect::<HashMap<_, _>>();

    let mut rows = Vec::with_capacity(receipts.iter().map(|row| row.proposals.len()).sum());
    for receipt in receipts {
        for proposal in &receipt.proposals {
            let key = (receipt.receipt_id.clone(), proposal.proposal_id.clone());
            let override_kind = overrides.get(&key).copied();
            let outcome = outcome_by_proposal
                .get(&key)
                .expect("validated proposal outcome must exist");
            rows.push(verdict_row(
                receipt,
                proposal,
                outcome.outcome,
                outcome.commit_id.clone(),
                override_kind,
                lineage.active_commit_for_atom(&proposal.atom),
            ));
        }
    }
    rows.sort_unstable_by(|left, right| {
        status_rank(left.status)
            .cmp(&status_rank(right.status))
            .then_with(|| left.receipt_id.cmp(&right.receipt_id))
            .then_with(|| left.proposal_id.cmp(&right.proposal_id))
    });
    let audit = audit_rows(&rows);
    Ok(GraphPromotionVerdictCertificate {
        schema_version: GRAPH_PROMOTION_VERDICT_SCHEMA_VERSION.into(),
        source: "rust-deterministic-promotion-verdict".into(),
        no_topology_writes: true,
        receipt_count: receipts.len(),
        commit_count: commits.len(),
        audit,
        rows,
    })
}

fn verdict_row(
    receipt: &GraphProposalBatchReceipt,
    proposal: &GraphProposalObservation,
    outcome: GraphProposalOutcomeKind,
    commit_id: Option<CompactString>,
    override_kind: Option<GraphPromotionUserOverrideKind>,
    active_atom_commit: Option<&GraphTruthCommit>,
) -> GraphPromotionVerdictRow {
    let semantic = is_semantic_receipt(receipt, proposal);
    let witness_count = unique_witness_count(proposal);
    let nli_support = nli_support(proposal);
    let nli_contradiction = nli_contradiction(proposal);
    let mut gates = Vec::with_capacity(8);
    gates.push(gate(
        GraphPromotionGateKind::Receipt,
        GraphPromotionGateStatus::Pass,
        "receipt validated before verdict projection",
        None,
    ));
    gates.push(evidence_gate(semantic, witness_count));
    gates.push(witness_gate(semantic, witness_count));
    gates.push(contradiction_gate(proposal, nli_support, nli_contradiction));
    gates.push(temporal_causal_gate(proposal));
    gates.push(nli_gate(semantic, proposal, nli_support, nli_contradiction));
    gates.push(user_override_gate(override_kind));
    gates.push(rollback_gate(outcome, commit_id.as_deref()));

    let hard_block = gates.iter().any(|gate| {
        gate.status == GraphPromotionGateStatus::Block
            && !matches!(gate.kind, GraphPromotionGateKind::UserOverride)
    });
    let status = verdict_status(proposal.status, outcome, override_kind, hard_block);
    let apply_plan = apply_plan(status, outcome, active_atom_commit);
    let rollback_plan = rollback_plan(outcome, commit_id.as_deref());
    let rationale = rationale(status, outcome, proposal.status, override_kind, hard_block);

    GraphPromotionVerdictRow {
        id: format!(
            "promotion-verdict:{}:{}",
            receipt.receipt_id, proposal.proposal_id
        )
        .into(),
        receipt_id: receipt.receipt_id.clone(),
        proposal_id: proposal.proposal_id.clone(),
        atom: proposal.atom.clone(),
        family: proposal.family.clone(),
        truth: proposal.truth,
        candidate_status: proposal.status,
        outcome,
        status,
        commit_id,
        evidence_refs: proposal.evidence_refs.iter().cloned().collect(),
        witness_count,
        nli_support_millis: nli_support,
        nli_contradiction_millis: nli_contradiction,
        user_override: override_kind,
        deterministic_score_millis: proposal.shadow_score_millis,
        apply_plan,
        rollback_plan,
        gates,
        rationale,
    }
}

fn is_semantic_receipt(
    receipt: &GraphProposalBatchReceipt,
    proposal: &GraphProposalObservation,
) -> bool {
    receipt
        .compiler_policy
        .policy_id
        .as_str()
        .contains("semantic-phase5")
        || proposal.truth.kind == GraphTruthKind::Semantic
}

fn unique_witness_count(proposal: &GraphProposalObservation) -> u16 {
    let mut seen = HashSet::with_capacity(proposal.evidence_refs.len());
    for evidence in &proposal.evidence_refs {
        seen.insert(evidence.as_str());
    }
    seen.len().min(u16::MAX as usize) as u16
}

fn nli_support(proposal: &GraphProposalObservation) -> Option<i16> {
    nli_present(proposal).then_some(proposal.features.0[NLI_SUPPORT_FEATURE])
}

fn nli_contradiction(proposal: &GraphProposalObservation) -> Option<i16> {
    nli_present(proposal).then_some(proposal.features.0[NLI_CONTRADICTION_FEATURE])
}

fn nli_present(proposal: &GraphProposalObservation) -> bool {
    proposal.features.0[NLI_PRESENT_FEATURE] > 0
}

fn evidence_gate(semantic: bool, witness_count: u16) -> GraphPromotionVerdictGate {
    if !semantic {
        return gate(
            GraphPromotionGateKind::Evidence,
            GraphPromotionGateStatus::NotRequired,
            "structural projection lanes carry source generations instead of evidence refs",
            None,
        );
    }
    if witness_count == 0 {
        return gate(
            GraphPromotionGateKind::Evidence,
            GraphPromotionGateStatus::Block,
            "semantic promotion requires evidence refs",
            None,
        );
    }
    gate(
        GraphPromotionGateKind::Evidence,
        GraphPromotionGateStatus::Pass,
        "semantic evidence refs present",
        Some(witness_count as i16),
    )
}

fn witness_gate(semantic: bool, witness_count: u16) -> GraphPromotionVerdictGate {
    if !semantic {
        return gate(
            GraphPromotionGateKind::WitnessCount,
            GraphPromotionGateStatus::NotRequired,
            "structural projection lanes are witnessed by source generation receipts",
            None,
        );
    }
    if witness_count == 0 {
        return gate(
            GraphPromotionGateKind::WitnessCount,
            GraphPromotionGateStatus::Block,
            "zero distinct semantic witnesses",
            None,
        );
    }
    gate(
        GraphPromotionGateKind::WitnessCount,
        GraphPromotionGateStatus::Pass,
        "distinct semantic witnesses present",
        Some(witness_count as i16),
    )
}

fn contradiction_gate(
    proposal: &GraphProposalObservation,
    support: Option<i16>,
    contradiction: Option<i16>,
) -> GraphPromotionVerdictGate {
    if proposal.status == GraphProposalStatus::ReviewedContradiction {
        return gate(
            GraphPromotionGateKind::Contradiction,
            GraphPromotionGateStatus::Block,
            "reviewed contradiction cannot become accepted truth",
            contradiction,
        );
    }
    if contradiction.is_some_and(|value| {
        value >= MIN_NLI_SUPPORT_MILLIS
            && value > support.unwrap_or_default() + CONTRADICTION_MARGIN_MILLIS
    }) {
        return gate(
            GraphPromotionGateKind::Contradiction,
            GraphPromotionGateStatus::Block,
            "NLI contradiction exceeds support margin",
            contradiction,
        );
    }
    gate(
        GraphPromotionGateKind::Contradiction,
        GraphPromotionGateStatus::Pass,
        "no blocking contradiction",
        contradiction,
    )
}

fn temporal_causal_gate(proposal: &GraphProposalObservation) -> GraphPromotionVerdictGate {
    let status = match proposal.truth.kind {
        GraphTruthKind::Temporal | GraphTruthKind::Causal => GraphPromotionGateStatus::Pass,
        _ => GraphPromotionGateStatus::NotRequired,
    };
    let summary = match status {
        GraphPromotionGateStatus::Pass => "temporal/causal truth kind is explicitly typed",
        _ => "not a temporal or causal truth candidate",
    };
    gate(
        GraphPromotionGateKind::TemporalCausalFit,
        status,
        summary,
        None,
    )
}

fn nli_gate(
    semantic: bool,
    proposal: &GraphProposalObservation,
    support: Option<i16>,
    contradiction: Option<i16>,
) -> GraphPromotionVerdictGate {
    if !semantic || !nli_present(proposal) {
        return gate(
            GraphPromotionGateKind::NliFit,
            GraphPromotionGateStatus::NotRequired,
            "no NLI score required for this candidate",
            support,
        );
    }
    let support = support.unwrap_or_default();
    let contradiction = contradiction.unwrap_or_default();
    if support < MIN_NLI_SUPPORT_MILLIS || contradiction > support + CONTRADICTION_MARGIN_MILLIS {
        return gate(
            GraphPromotionGateKind::NliFit,
            GraphPromotionGateStatus::Block,
            "NLI support is below promotion margin",
            Some(support),
        );
    }
    gate(
        GraphPromotionGateKind::NliFit,
        GraphPromotionGateStatus::Pass,
        "NLI support clears contradiction margin",
        Some(support),
    )
}

fn user_override_gate(
    override_kind: Option<GraphPromotionUserOverrideKind>,
) -> GraphPromotionVerdictGate {
    match override_kind {
        Some(GraphPromotionUserOverrideKind::Approve) => gate(
            GraphPromotionGateKind::UserOverride,
            GraphPromotionGateStatus::Override,
            "explicit user approval recorded",
            None,
        ),
        Some(GraphPromotionUserOverrideKind::Reject) => gate(
            GraphPromotionGateKind::UserOverride,
            GraphPromotionGateStatus::Block,
            "explicit user rejection recorded",
            None,
        ),
        None => gate(
            GraphPromotionGateKind::UserOverride,
            GraphPromotionGateStatus::NotRequired,
            "no user override",
            None,
        ),
    }
}

fn rollback_gate(
    outcome: GraphProposalOutcomeKind,
    commit_id: Option<&str>,
) -> GraphPromotionVerdictGate {
    if outcome == GraphProposalOutcomeKind::Active && commit_id.is_some() {
        return gate(
            GraphPromotionGateKind::Rollback,
            GraphPromotionGateStatus::Pass,
            "active commit can be reverted by GraphTruthOperation::Revert",
            None,
        );
    }
    gate(
        GraphPromotionGateKind::Rollback,
        GraphPromotionGateStatus::NotRequired,
        "rollback becomes available after a durable accept commit",
        None,
    )
}

fn gate(
    kind: GraphPromotionGateKind,
    status: GraphPromotionGateStatus,
    summary: &str,
    score_millis: Option<i16>,
) -> GraphPromotionVerdictGate {
    GraphPromotionVerdictGate {
        kind,
        status,
        summary: summary.into(),
        score_millis,
    }
}

fn verdict_status(
    candidate_status: GraphProposalStatus,
    outcome: GraphProposalOutcomeKind,
    override_kind: Option<GraphPromotionUserOverrideKind>,
    hard_block: bool,
) -> GraphPromotionVerdictStatus {
    if outcome == GraphProposalOutcomeKind::Active {
        return GraphPromotionVerdictStatus::AlreadyCommitted;
    }
    if matches!(
        outcome,
        GraphProposalOutcomeKind::Superseded
            | GraphProposalOutcomeKind::Retracted
            | GraphProposalOutcomeKind::Reverted
    ) {
        return GraphPromotionVerdictStatus::Blocked;
    }
    if override_kind == Some(GraphPromotionUserOverrideKind::Reject)
        || candidate_status == GraphProposalStatus::Rejected
    {
        return GraphPromotionVerdictStatus::Rejected;
    }
    if hard_block {
        return GraphPromotionVerdictStatus::Blocked;
    }
    if candidate_status == GraphProposalStatus::ReviewedSupport
        || override_kind == Some(GraphPromotionUserOverrideKind::Approve)
    {
        return GraphPromotionVerdictStatus::Acceptable;
    }
    GraphPromotionVerdictStatus::Deferred
}

fn apply_plan(
    status: GraphPromotionVerdictStatus,
    outcome: GraphProposalOutcomeKind,
    active_atom_commit: Option<&GraphTruthCommit>,
) -> GraphPromotionApplyPlan {
    if status == GraphPromotionVerdictStatus::AlreadyCommitted {
        return GraphPromotionApplyPlan {
            operation: None,
            predecessor_commit_id: None,
            rationale: "proposal already has active durable truth".into(),
        };
    }
    if status != GraphPromotionVerdictStatus::Acceptable
        || outcome != GraphProposalOutcomeKind::Uncommitted
    {
        return GraphPromotionApplyPlan {
            operation: None,
            predecessor_commit_id: None,
            rationale: "candidate is not acceptable for durable promotion".into(),
        };
    }
    if let Some(commit) = active_atom_commit {
        return GraphPromotionApplyPlan {
            operation: Some(GraphTruthOperation::Supersede),
            predecessor_commit_id: Some(commit.header.commit_id.clone()),
            rationale: "acceptance would supersede the currently active atom".into(),
        };
    }
    GraphPromotionApplyPlan {
        operation: Some(GraphTruthOperation::Assert),
        predecessor_commit_id: None,
        rationale: "acceptance would assert a new durable truth atom".into(),
    }
}

fn rollback_plan(
    outcome: GraphProposalOutcomeKind,
    commit_id: Option<&str>,
) -> GraphPromotionRollbackPlan {
    if outcome == GraphProposalOutcomeKind::Active {
        return GraphPromotionRollbackPlan {
            operation: Some(GraphTruthOperation::Revert),
            reverses_commit_id: commit_id.map(CompactString::new),
            available_now: commit_id.is_some(),
            available_after_commit: false,
            rationale: "active accepted truth can be rolled back with a revert commit".into(),
        };
    }
    GraphPromotionRollbackPlan {
        operation: Some(GraphTruthOperation::Revert),
        reverses_commit_id: None,
        available_now: false,
        available_after_commit: true,
        rationale: "rollback is defined once an accept commit exists".into(),
    }
}

fn rationale(
    status: GraphPromotionVerdictStatus,
    outcome: GraphProposalOutcomeKind,
    candidate_status: GraphProposalStatus,
    override_kind: Option<GraphPromotionUserOverrideKind>,
    hard_block: bool,
) -> CompactString {
    match status {
        GraphPromotionVerdictStatus::Acceptable => "all required gates passed".into(),
        GraphPromotionVerdictStatus::AlreadyCommitted => {
            "proposal already maps to active truth".into()
        }
        GraphPromotionVerdictStatus::Rejected => {
            "candidate rejected by review or user override".into()
        }
        GraphPromotionVerdictStatus::Deferred => {
            "candidate awaits review support or explicit user approval".into()
        }
        GraphPromotionVerdictStatus::Blocked if hard_block => {
            "candidate failed a hard promotion gate".into()
        }
        GraphPromotionVerdictStatus::Blocked
            if outcome != GraphProposalOutcomeKind::Uncommitted =>
        {
            "candidate lineage is no longer active".into()
        }
        GraphPromotionVerdictStatus::Blocked => {
            format!("candidate blocked: status={candidate_status:?} override={override_kind:?}")
                .into()
        }
    }
}

fn audit_rows(rows: &[GraphPromotionVerdictRow]) -> GraphPromotionVerdictAudit {
    let mut audit = GraphPromotionVerdictAudit {
        total: rows.len(),
        ..Default::default()
    };
    for row in rows {
        match row.status {
            GraphPromotionVerdictStatus::Acceptable => audit.acceptable += 1,
            GraphPromotionVerdictStatus::AlreadyCommitted => audit.already_committed += 1,
            GraphPromotionVerdictStatus::Blocked => audit.blocked += 1,
            GraphPromotionVerdictStatus::Deferred => audit.deferred += 1,
            GraphPromotionVerdictStatus::Rejected => audit.rejected += 1,
        }
        if row.rollback_plan.available_now {
            audit.rollback_available += 1;
        }
        if row.user_override.is_some() {
            audit.user_overrides += 1;
        }
        for gate in &row.gates {
            if gate.status != GraphPromotionGateStatus::Block {
                continue;
            }
            match gate.kind {
                GraphPromotionGateKind::Evidence | GraphPromotionGateKind::WitnessCount => {
                    audit.evidence_blocked += 1;
                }
                GraphPromotionGateKind::Contradiction => audit.contradiction_blocked += 1,
                GraphPromotionGateKind::NliFit => audit.nli_blocked += 1,
                _ => {}
            }
        }
    }
    audit
}

fn status_rank(status: GraphPromotionVerdictStatus) -> u8 {
    match status {
        GraphPromotionVerdictStatus::Acceptable => 0,
        GraphPromotionVerdictStatus::AlreadyCommitted => 1,
        GraphPromotionVerdictStatus::Blocked => 2,
        GraphPromotionVerdictStatus::Deferred => 3,
        GraphPromotionVerdictStatus::Rejected => 4,
    }
}

#[derive(Debug)]
pub enum GraphPromotionVerdictError {
    Receipt(GraphProposalReceiptError),
    Lineage(GraphTruthLineageError),
}

impl fmt::Display for GraphPromotionVerdictError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "invalid graph promotion verdict input: {self:?}")
    }
}

impl Error for GraphPromotionVerdictError {}

impl From<GraphProposalReceiptError> for GraphPromotionVerdictError {
    fn from(value: GraphProposalReceiptError) -> Self {
        Self::Receipt(value)
    }
}

impl From<GraphTruthLineageError> for GraphPromotionVerdictError {
    fn from(value: GraphTruthLineageError) -> Self {
        Self::Lineage(value)
    }
}
