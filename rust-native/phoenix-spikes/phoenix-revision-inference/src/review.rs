use std::fmt::Write;

use compact_str::CompactString;
use phoenix_types::{
    GoldExpectedImpact, GoldExpectedUnknown, GoldRepairExpectation, RevisionImpactGoldCase,
};
use serde::{Deserialize, Serialize};

use crate::{Result, build_gold_duel_projection, snapshot_digest};

pub const GOLD_REVIEW_PACKET_SCHEMA: &str = "phoenix.revision-impact-gold-review/v2";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GoldReviewPacket {
    pub schema: CompactString,
    pub review_token: CompactString,
    pub review_digest: CompactString,
    pub corpus_digest: CompactString,
    pub inference_snapshot_digest: CompactString,
    pub labels_author_reviewed: bool,
    pub integration_enabled: bool,
    pub cases: Vec<GoldReviewCase>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GoldReviewCase {
    pub case_id: CompactString,
    pub title: CompactString,
    pub mutation: phoenix_types::StoryMutation,
    pub proposed_impacts: Vec<GoldExpectedImpact>,
    pub proposed_unknowns: Vec<GoldExpectedUnknown>,
    pub proposed_repairs: Vec<GoldRepairExpectation>,
    pub proposed_preferred_repair_id: CompactString,
    pub preference_basis: CompactString,
    pub evidence_targets: Vec<SceneEvidenceProposal>,
    pub machine_checks: GoldReviewMachineChecks,
    pub author_decision: AuthorReviewDecision,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SceneEvidenceProposal {
    pub scene_id: CompactString,
    pub evidence_ids: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GoldReviewMachineChecks {
    pub deterministic_labels_match: bool,
    pub coverage_is_honest: bool,
    pub evidence_targets_present: bool,
    pub repairs_are_unranked: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuthorReviewDecision {
    pub status: CompactString,
    pub labels_accepted: Option<bool>,
    pub evidence_targets_accepted: Option<bool>,
    pub repairs_accepted: Option<bool>,
    pub preferred_repair_id: Option<CompactString>,
    pub notes: Option<CompactString>,
}

pub fn build_gold_review_packet() -> Result<GoldReviewPacket> {
    let duel = build_gold_duel_projection()?;
    let corpus = duel
        .cases
        .iter()
        .map(|case| case.gold.clone())
        .collect::<Vec<_>>();
    let corpus_encoded = serde_json::to_vec(&corpus)?;
    let corpus_digest = blake3::hash(&corpus_encoded).to_hex().to_string();
    let cases = duel
        .cases
        .iter()
        .map(|case| review_case(&case.gold, case))
        .collect::<Vec<_>>();
    let inference_snapshot_digest = snapshot_digest(&duel.graph);
    let mut review_hasher = blake3::Hasher::new();
    review_hasher.update(GOLD_REVIEW_PACKET_SCHEMA.as_bytes());
    review_hasher.update(&corpus_encoded);
    review_hasher.update(inference_snapshot_digest.as_bytes());
    for case in &cases {
        review_hasher.update(case.case_id.as_bytes());
        review_hasher.update(case.proposed_preferred_repair_id.as_bytes());
    }
    let review_digest = review_hasher.finalize().to_hex().to_string();
    let review_token = format!("gold-review-v2:{}", &review_digest[..16]);
    Ok(GoldReviewPacket {
        schema: GOLD_REVIEW_PACKET_SCHEMA.into(),
        review_token: review_token.into(),
        review_digest: review_digest.into(),
        corpus_digest: corpus_digest.into(),
        inference_snapshot_digest: inference_snapshot_digest.into(),
        labels_author_reviewed: false,
        integration_enabled: false,
        cases,
    })
}

pub fn render_gold_review_markdown(packet: &GoldReviewPacket) -> String {
    let mut markdown = String::with_capacity(16 * 1024);
    writeln!(markdown, "# Revision-impact gold author review").unwrap();
    writeln!(markdown).unwrap();
    writeln!(markdown, "Review token: `{}`", packet.review_token).unwrap();
    writeln!(markdown).unwrap();
    writeln!(markdown, "Corpus digest: `{}`", packet.corpus_digest).unwrap();
    writeln!(markdown).unwrap();
    writeln!(markdown, "Models remain disabled experimental overlays. This packet does not change graph truth or review status.").unwrap();
    for case in &packet.cases {
        writeln!(markdown).unwrap();
        writeln!(markdown, "## {}", case.title).unwrap();
        writeln!(markdown).unwrap();
        writeln!(markdown, "Case: `{}`", case.case_id).unwrap();
        writeln!(markdown).unwrap();
        writeln!(markdown, "Mutation: `{:?}`", case.mutation).unwrap();
        writeln!(markdown).unwrap();
        writeln!(markdown, "### Proposed impacts").unwrap();
        writeln!(markdown).unwrap();
        for impact in &case.proposed_impacts {
            writeln!(
                markdown,
                "- **{:?}** `{}` — {} Constraints: `{:?}`.",
                impact.classification, impact.scene_id.0, impact.rationale, impact.constraint_kinds
            )
            .unwrap();
        }
        writeln!(markdown).unwrap();
        writeln!(markdown, "### Proposed unknowns").unwrap();
        writeln!(markdown).unwrap();
        for unknown in &case.proposed_unknowns {
            writeln!(
                markdown,
                "- `{}` — {} Missing planes: `{:?}`.",
                unknown.scene_id.0, unknown.rationale, unknown.missing_planes
            )
            .unwrap();
        }
        writeln!(markdown).unwrap();
        writeln!(markdown, "### Proposed evidence targets").unwrap();
        writeln!(markdown).unwrap();
        for evidence in &case.evidence_targets {
            writeln!(
                markdown,
                "- `{}` -> `{}`",
                evidence.scene_id,
                evidence
                    .evidence_ids
                    .iter()
                    .map(CompactString::as_str)
                    .collect::<Vec<_>>()
                    .join("`, `")
            )
            .unwrap();
        }
        writeln!(markdown).unwrap();
        writeln!(markdown, "### Proposed reasonable repairs (unranked)").unwrap();
        writeln!(markdown).unwrap();
        for repair in &case.proposed_repairs {
            writeln!(
                markdown,
                "- `{}` ({:?}) — {} Targets: `{}`.",
                repair.repair_id.0,
                repair.kind,
                repair.rationale,
                repair
                    .target_scene_ids
                    .iter()
                    .map(|scene| scene.0.as_str())
                    .collect::<Vec<_>>()
                    .join("`, `")
            )
            .unwrap();
        }
        writeln!(markdown).unwrap();
        writeln!(
            markdown,
            "Proposed preferred repair: `{}` -- {}",
            case.proposed_preferred_repair_id, case.preference_basis
        )
        .unwrap();
        writeln!(markdown).unwrap();
        writeln!(markdown, "### Author decision").unwrap();
        writeln!(markdown).unwrap();
        writeln!(markdown, "- [ ] Impact and unknown labels are accurate").unwrap();
        writeln!(markdown, "- [ ] Evidence targets are accurate").unwrap();
        writeln!(markdown, "- [ ] The reasonable-repair set is accurate").unwrap();
        writeln!(markdown, "- Preferred repair ID: `________________`").unwrap();
        writeln!(
            markdown,
            "- Corrections or notes: ________________________________"
        )
        .unwrap();
    }
    writeln!(markdown).unwrap();
    writeln!(markdown, "## Acceptance").unwrap();
    writeln!(markdown).unwrap();
    writeln!(
        markdown,
        "Approve unchanged by replying: `approve {}`. Otherwise list corrections by case ID.",
        packet.review_token
    )
    .unwrap();
    markdown
}

fn review_case(gold: &RevisionImpactGoldCase, duel: &crate::GoldDuelCase) -> GoldReviewCase {
    let evidence_targets = gold
        .expected_impacts
        .iter()
        .map(|impact| SceneEvidenceProposal {
            scene_id: impact.scene_id.0.clone(),
            evidence_ids: duel
                .scene_evidence
                .get(&impact.scene_id.0)
                .into_iter()
                .flatten()
                .filter(|id| id.contains(":impact:"))
                .cloned()
                .collect(),
        })
        .collect::<Vec<_>>();
    let expected = gold
        .expected_impacts
        .iter()
        .map(|impact| (impact.scene_id.0.as_str(), impact.classification))
        .chain(gold.expected_unknowns.iter().map(|unknown| {
            (
                unknown.scene_id.0.as_str(),
                phoenix_types::ImpactClassification::Unknown,
            )
        }))
        .collect::<std::collections::BTreeMap<_, _>>();
    let actual = duel
        .deterministic_report
        .authoritative_impacts
        .iter()
        .map(|impact| (impact.scene_id.0.as_str(), impact.classification))
        .collect::<std::collections::BTreeMap<_, _>>();
    GoldReviewCase {
        case_id: gold.case_id.0.clone(),
        title: gold.title.clone(),
        mutation: gold.mutation.clone(),
        proposed_impacts: gold.expected_impacts.clone(),
        proposed_unknowns: gold.expected_unknowns.clone(),
        proposed_repairs: gold.reasonable_repairs.clone(),
        proposed_preferred_repair_id: proposed_preferred_repair(gold).into(),
        preference_basis: "Preserves the explicit mutation while minimizing downstream edits."
            .into(),
        machine_checks: GoldReviewMachineChecks {
            deterministic_labels_match: actual == expected,
            coverage_is_honest: duel.deterministic_report.authoritative_impacts.iter().all(
                |impact| {
                    impact.classification == phoenix_types::ImpactClassification::Unknown
                        || impact.coverage.classification_supported
                },
            ),
            evidence_targets_present: evidence_targets
                .iter()
                .all(|evidence| !evidence.evidence_ids.is_empty()),
            repairs_are_unranked: true,
        },
        evidence_targets,
        author_decision: AuthorReviewDecision {
            status: "pending_author_review".into(),
            labels_accepted: None,
            evidence_targets_accepted: None,
            repairs_accepted: None,
            preferred_repair_id: None,
            notes: None,
        },
    }
}

const fn proposed_preferred_repair(gold: &RevisionImpactGoldCase) -> &'static str {
    match gold.family {
        phoenix_types::GoldMutationFamily::DelayedReveal => {
            "repair:delayed_reveal:revise_assignment"
        }
        phoenix_types::GoldMutationFamily::EarlierDeath => "repair:earlier_death:revise_warning",
        phoenix_types::GoldMutationFamily::ChangedWitness => {
            "repair:changed_witness:revise_testimony"
        }
        phoenix_types::GoldMutationFamily::ChangedPowerLimitation => {
            "repair:power_limit:revise_escape"
        }
        phoenix_types::GoldMutationFamily::ChangedTravelDuration => {
            "repair:travel_duration:insert_event"
        }
        phoenix_types::GoldMutationFamily::RemovedRelationship => {
            "repair:relationship:revise_access"
        }
        phoenix_types::GoldMutationFamily::ChangedPossession => "repair:possession:revise_vault",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn review_packet_is_deterministic_and_cannot_self_approve() {
        let first = build_gold_review_packet().unwrap();
        let second = build_gold_review_packet().unwrap();
        assert_eq!(first, second);
        assert!(!first.labels_author_reviewed);
        assert!(!first.integration_enabled);
        assert_eq!(first.cases.len(), 7);
        assert!(first.cases.iter().all(|case| {
            case.author_decision.status == "pending_author_review"
                && case.author_decision.labels_accepted.is_none()
                && case.machine_checks.deterministic_labels_match
                && case.machine_checks.evidence_targets_present
                && case
                    .proposed_repairs
                    .iter()
                    .any(|repair| repair.repair_id.0 == case.proposed_preferred_repair_id)
        }));
    }

    #[test]
    fn markdown_carries_digest_bound_acceptance_phrase() {
        let packet = build_gold_review_packet().unwrap();
        let markdown = render_gold_review_markdown(&packet);
        assert!(markdown.contains(packet.review_token.as_str()));
        assert!(markdown.contains("Models remain disabled experimental overlays"));
    }
}
