use serde::{Deserialize, Serialize};

use crate::model_split::{PhoenixModelLane, PhoenixModelRole};
use crate::nli::{NliError, NliScorer, NliScores};

const DEFAULT_MAX_PAIRS_PER_BATCH: usize = 32;
const DEFAULT_SUPPORT_THRESHOLD_MILLIS: u32 = 720;
const DEFAULT_CONTRADICTION_THRESHOLD_MILLIS: u32 = 720;
const DEFAULT_DECISION_MARGIN_MILLIS: u32 = 80;

pub const NLI_CLAIM_INPUT_SCHEMA_VERSION: &str = "phoenix-nli-claim-input/v1";
pub const NLI_CLAIM_ADJUDICATION_SCHEMA_VERSION: &str = "phoenix-nli-claim-adjudication/v1";

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum NliClaimPurpose {
    #[default]
    EvidenceClaim,
    CanonFact,
    HumanReviewTriage,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ClassificationVote {
    pub source: PhoenixModelLane,
    pub role: PhoenixModelRole,
    pub label: String,
    pub score_millis: u32,
    #[serde(default)]
    pub rationale: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NliClaimInput {
    #[serde(default = "default_nli_claim_input_schema_version")]
    pub schema_version: String,
    pub claim_id: String,
    pub evidence_id: String,
    pub premise: String,
    pub hypothesis: String,
    pub purpose: NliClaimPurpose,
    #[serde(default)]
    pub classification_vote: Option<ClassificationVote>,
    #[serde(default)]
    pub evidence_refs: Vec<String>,
}

fn default_nli_claim_input_schema_version() -> String {
    NLI_CLAIM_INPUT_SCHEMA_VERSION.to_owned()
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum NliClaimDecisionKind {
    Supported,
    Contradicted,
    #[default]
    Unknown,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NliClaimAdjudicationOptions {
    pub max_pairs_per_batch: usize,
    pub support_threshold_millis: u32,
    pub contradiction_threshold_millis: u32,
    pub decision_margin_millis: u32,
}

impl Default for NliClaimAdjudicationOptions {
    fn default() -> Self {
        Self {
            max_pairs_per_batch: DEFAULT_MAX_PAIRS_PER_BATCH,
            support_threshold_millis: DEFAULT_SUPPORT_THRESHOLD_MILLIS,
            contradiction_threshold_millis: DEFAULT_CONTRADICTION_THRESHOLD_MILLIS,
            decision_margin_millis: DEFAULT_DECISION_MARGIN_MILLIS,
        }
    }
}

impl NliClaimAdjudicationOptions {
    fn batch_size(self) -> usize {
        self.max_pairs_per_batch.max(1)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NliClaimVote {
    pub source: PhoenixModelLane,
    pub role: PhoenixModelRole,
    pub decision: NliClaimDecisionKind,
    pub scores: NliScores,
    pub entailment_millis: u32,
    pub contradiction_millis: u32,
    pub neutral_millis: u32,
    pub confidence_millis: u32,
    pub rationale: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NliClaimAdjudication {
    #[serde(default = "default_nli_claim_adjudication_schema_version")]
    pub schema_version: String,
    pub claim_id: String,
    pub evidence_id: String,
    pub purpose: NliClaimPurpose,
    pub nli_vote: NliClaimVote,
    #[serde(default)]
    pub classification_vote: Option<ClassificationVote>,
    pub review_priority_millis: u32,
    pub needs_human_review: bool,
    #[serde(default)]
    pub evidence_refs: Vec<String>,
    #[serde(default)]
    pub receipts: Vec<String>,
}

fn default_nli_claim_adjudication_schema_version() -> String {
    NLI_CLAIM_ADJUDICATION_SCHEMA_VERSION.to_owned()
}

pub fn adjudicate_claims_with_nli<S: NliScorer + ?Sized>(
    claims: &[NliClaimInput],
    scorer: &S,
    options: NliClaimAdjudicationOptions,
) -> Result<Vec<NliClaimAdjudication>, NliError> {
    if claims.is_empty() {
        return Ok(Vec::new());
    }
    let batch_size = options.batch_size();
    let mut out = Vec::with_capacity(claims.len());
    for chunk in claims.chunks(batch_size) {
        let pairs = chunk
            .iter()
            .map(|claim| (claim.premise.as_str(), claim.hypothesis.as_str()))
            .collect::<Vec<_>>();
        let scores = scorer.score_batch(&pairs)?;
        if scores.len() != chunk.len() {
            return Err(NliError::Inference(format!(
                "NLI scorer returned {} scores for {} claim pairs",
                scores.len(),
                chunk.len()
            )));
        }
        out.extend(
            chunk
                .iter()
                .zip(scores)
                .map(|(claim, scores)| adjudicate_claim(claim, scores, options)),
        );
    }
    Ok(out)
}

fn adjudicate_claim(
    claim: &NliClaimInput,
    scores: NliScores,
    options: NliClaimAdjudicationOptions,
) -> NliClaimAdjudication {
    let entailment_millis = score_millis(scores.entailment);
    let contradiction_millis = score_millis(scores.contradiction);
    let neutral_millis = score_millis(scores.neutral);
    let decision = choose_decision(
        entailment_millis,
        contradiction_millis,
        options.support_threshold_millis,
        options.contradiction_threshold_millis,
        options.decision_margin_millis,
    );
    let confidence_millis = match decision {
        NliClaimDecisionKind::Supported => entailment_millis,
        NliClaimDecisionKind::Contradicted => contradiction_millis,
        NliClaimDecisionKind::Unknown => neutral_millis,
    };
    let review_priority_millis = review_priority_millis(
        decision,
        entailment_millis,
        contradiction_millis,
        neutral_millis,
        claim.classification_vote.as_ref(),
    );
    let needs_human_review = decision == NliClaimDecisionKind::Unknown
        || matches!(claim.purpose, NliClaimPurpose::HumanReviewTriage);
    let nli_vote = NliClaimVote {
        source: PhoenixModelLane::ModernBertNli,
        role: role_for_purpose(claim.purpose),
        decision,
        scores,
        entailment_millis,
        contradiction_millis,
        neutral_millis,
        confidence_millis,
        rationale: rationale_for_decision(decision).to_owned(),
    };
    NliClaimAdjudication {
        schema_version: default_nli_claim_adjudication_schema_version(),
        claim_id: claim.claim_id.clone(),
        evidence_id: claim.evidence_id.clone(),
        purpose: claim.purpose,
        nli_vote,
        classification_vote: claim.classification_vote.clone(),
        review_priority_millis,
        needs_human_review,
        evidence_refs: claim.evidence_refs.clone(),
        receipts: vec![format!(
            "nli:claim={};evidence={};decision={:?};entailment={:.3};contradiction={:.3};neutral={:.3}",
            claim.claim_id,
            claim.evidence_id,
            decision,
            scores.entailment,
            scores.contradiction,
            scores.neutral
        )],
    }
}

fn role_for_purpose(purpose: NliClaimPurpose) -> PhoenixModelRole {
    match purpose {
        NliClaimPurpose::EvidenceClaim => PhoenixModelRole::EvidenceClaimAdjudication,
        NliClaimPurpose::CanonFact => PhoenixModelRole::CanonFactAdjudication,
        NliClaimPurpose::HumanReviewTriage => PhoenixModelRole::HumanReviewTriage,
    }
}

fn choose_decision(
    entailment_millis: u32,
    contradiction_millis: u32,
    support_threshold_millis: u32,
    contradiction_threshold_millis: u32,
    margin_millis: u32,
) -> NliClaimDecisionKind {
    if contradiction_millis >= contradiction_threshold_millis
        && contradiction_millis >= entailment_millis.saturating_add(margin_millis)
    {
        return NliClaimDecisionKind::Contradicted;
    }
    if entailment_millis >= support_threshold_millis
        && entailment_millis >= contradiction_millis.saturating_add(margin_millis)
    {
        return NliClaimDecisionKind::Supported;
    }
    NliClaimDecisionKind::Unknown
}

fn review_priority_millis(
    decision: NliClaimDecisionKind,
    entailment_millis: u32,
    contradiction_millis: u32,
    neutral_millis: u32,
    classification_vote: Option<&ClassificationVote>,
) -> u32 {
    let route_priority = classification_vote
        .map(|vote| vote.score_millis)
        .unwrap_or_default();
    let nli_priority = match decision {
        NliClaimDecisionKind::Supported => 0,
        NliClaimDecisionKind::Contradicted => contradiction_millis,
        NliClaimDecisionKind::Unknown => {
            let gap = entailment_millis.abs_diff(contradiction_millis);
            neutral_millis.max(1000u32.saturating_sub(gap))
        }
    };
    nli_priority.max(route_priority).min(1000)
}

fn rationale_for_decision(decision: NliClaimDecisionKind) -> &'static str {
    match decision {
        NliClaimDecisionKind::Supported => {
            "modernbert nli found direct support for the claim in the evidence"
        }
        NliClaimDecisionKind::Contradicted => {
            "modernbert nli found contradiction between the evidence and the claim"
        }
        NliClaimDecisionKind::Unknown => {
            "modernbert nli did not find enough support or contradiction to adjudicate the claim"
        }
    }
}

fn score_millis(score: f32) -> u32 {
    (score.clamp(0.0, 1.0) * 1000.0).round() as u32
}

#[cfg(test)]
mod tests {
    use std::cell::RefCell;

    use super::*;

    struct FakeScorer {
        call_sizes: RefCell<Vec<usize>>,
    }

    impl FakeScorer {
        fn new() -> Self {
            Self {
                call_sizes: RefCell::new(Vec::new()),
            }
        }
    }

    impl NliScorer for FakeScorer {
        fn score_batch(&self, pairs: &[(&str, &str)]) -> Result<Vec<NliScores>, NliError> {
            self.call_sizes.borrow_mut().push(pairs.len());
            Ok(pairs
                .iter()
                .map(|(_, hypothesis)| match *hypothesis {
                    "Alice works for Dynamis." => scores(0.91, 0.03, 0.06),
                    "Alice never entered the harbor." => scores(0.04, 0.88, 0.08),
                    _ => scores(0.32, 0.22, 0.46),
                })
                .collect())
        }
    }

    fn scores(entailment: f32, contradiction: f32, neutral: f32) -> NliScores {
        NliScores {
            contradiction,
            entailment,
            neutral,
        }
    }

    fn claim(id: &str, hypothesis: &str) -> NliClaimInput {
        NliClaimInput {
            schema_version: default_nli_claim_input_schema_version(),
            claim_id: id.to_owned(),
            evidence_id: format!("ev-{id}"),
            premise: "Alice works for Dynamis and reports to its director.".to_owned(),
            hypothesis: hypothesis.to_owned(),
            purpose: NliClaimPurpose::EvidenceClaim,
            classification_vote: None,
            evidence_refs: vec![format!("ref-{id}")],
        }
    }

    #[test]
    fn claim_adjudication_batches_pairs() {
        let scorer = FakeScorer::new();
        let claims = vec![
            claim("a", "Alice works for Dynamis."),
            claim("b", "Alice never entered the harbor."),
            claim("c", "Alice likes tea."),
        ];
        let result = adjudicate_claims_with_nli(
            &claims,
            &scorer,
            NliClaimAdjudicationOptions {
                max_pairs_per_batch: 2,
                ..Default::default()
            },
        )
        .expect("adjudication");

        assert_eq!(result.len(), 3);
        assert_eq!(*scorer.call_sizes.borrow(), vec![2, 1]);
    }

    #[test]
    fn claim_adjudication_emits_nli_truth_vote() {
        let scorer = FakeScorer::new();
        let claims = vec![
            claim("supported", "Alice works for Dynamis."),
            claim("contradicted", "Alice never entered the harbor."),
            claim("unknown", "Alice likes tea."),
        ];
        let result =
            adjudicate_claims_with_nli(&claims, &scorer, Default::default()).expect("votes");

        assert_eq!(result[0].nli_vote.decision, NliClaimDecisionKind::Supported);
        assert_eq!(
            result[1].nli_vote.decision,
            NliClaimDecisionKind::Contradicted
        );
        assert_eq!(result[2].nli_vote.decision, NliClaimDecisionKind::Unknown);
        assert_eq!(result[0].nli_vote.source, PhoenixModelLane::ModernBertNli);
        assert_eq!(
            result[0].nli_vote.role,
            PhoenixModelRole::EvidenceClaimAdjudication
        );
    }

    #[test]
    fn classification_vote_affects_review_priority_not_truth_vote() {
        let scorer = FakeScorer::new();
        let mut input = claim("triage", "Alice likes tea.");
        input.purpose = NliClaimPurpose::HumanReviewTriage;
        input.classification_vote = Some(ClassificationVote {
            source: PhoenixModelLane::Gliclass,
            role: PhoenixModelRole::FastLabelRouting,
            label: "review.gap".to_owned(),
            score_millis: 940,
            rationale: Some("gliclass routed this to review".to_owned()),
        });

        let result =
            adjudicate_claims_with_nli(&[input], &scorer, Default::default()).expect("triage vote");
        let row = &result[0];

        assert_eq!(row.nli_vote.decision, NliClaimDecisionKind::Unknown);
        assert_eq!(row.review_priority_millis, 940);
        assert!(row.needs_human_review);
        assert_eq!(
            row.classification_vote.as_ref().map(|vote| vote.source),
            Some(PhoenixModelLane::Gliclass)
        );
    }

    #[test]
    fn claim_contract_serializes_v1_schema_and_accepts_legacy_input() {
        let input = claim("fixture", "Alice works for Dynamis.");
        let input_value = serde_json::to_value(&input).expect("claim input json");
        assert_eq!(input_value["schemaVersion"], NLI_CLAIM_INPUT_SCHEMA_VERSION);

        let legacy = serde_json::json!({
            "claimId": "legacy",
            "evidenceId": "ev-legacy",
            "premise": "Alice works for Dynamis.",
            "hypothesis": "Alice works for Dynamis.",
            "purpose": "evidenceClaim"
        });
        let parsed: NliClaimInput = serde_json::from_value(legacy).expect("legacy input");
        assert_eq!(parsed.schema_version, NLI_CLAIM_INPUT_SCHEMA_VERSION);

        let scorer = FakeScorer::new();
        let adjudication =
            adjudicate_claims_with_nli(&[input], &scorer, Default::default()).expect("vote");
        let output_value = serde_json::to_value(&adjudication[0]).expect("adjudication json");
        assert_eq!(
            output_value["schemaVersion"],
            NLI_CLAIM_ADJUDICATION_SCHEMA_VERSION
        );
        assert_eq!(output_value["nliVote"]["decision"], "supported");
    }
}
