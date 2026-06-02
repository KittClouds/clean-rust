use std::collections::BTreeMap;

use phoenix_dynamic_ner::{
    AliasResolutionReport, MentionGraph, MentionKind, MentionPacket, MentionSourceKind,
    MentionStatus,
};
use phoenix_types::{
    AtlasAliasProposalDecision, AtlasAliasProposalSummary, AtlasAliasProposalTarget,
    AtlasDatasetExampleKind, AtlasDatasetExampleSummary, AtlasDatasetFactorySummary,
    AtlasDatasetSnapshotSummary, AtlasEvidenceArtifactKind, AtlasEvidenceDecisionStatus,
    AtlasEvidenceLedgerSummary, AtlasEvidenceReceiptSummary, AtlasIdentityReceiptAction,
    AtlasIdentityReceiptSummary, AtlasIdentityTargetSummary, AtlasRichScanCandidateSummary,
    DocumentId, MentionEntityRef, MentionId, NoteId, TextRange,
};
use serde::Serialize;
use serde_json::{json, Value};

const LEDGER_SOURCE_VERSION: &str = "atlas-evidence-ledger-v1";
const DATASET_KIND: &str = "atlas-rich-scan-v1";
const SUMMARY_EXAMPLE_PREVIEW_LIMIT: usize = 64;

pub(crate) struct DocumentEvidenceInput<'a> {
    pub scan_id: &'a str,
    pub document_id: &'a DocumentId,
    pub note_id: Option<&'a NoteId>,
    pub text: &'a str,
    pub mentions: &'a [MentionPacket],
    pub mention_graph: &'a MentionGraph,
    pub alias_report: &'a AliasResolutionReport,
    pub identity_receipts: &'a [AtlasIdentityReceiptSummary],
    pub created_at: i64,
}

pub(crate) struct DatasetFactoryBuild {
    pub summary: AtlasDatasetFactorySummary,
    pub snapshot_rows: Vec<Value>,
    pub example_rows: Vec<Value>,
}

pub(crate) fn build_document_receipts(
    input: DocumentEvidenceInput<'_>,
) -> Vec<AtlasEvidenceReceiptSummary> {
    let mut receipts = Vec::with_capacity(
        input.mentions.len()
            + input
                .mentions
                .iter()
                .map(|m| m.label_distribution.len())
                .sum::<usize>()
            + input.alias_report.proposals.len()
            + input.identity_receipts.len()
            + input.mention_graph.edge_count(),
    );
    for mention in input.mentions {
        push_mention_receipt(&mut receipts, &input, mention);
        push_kind_vote_receipts(&mut receipts, &input, mention);
    }
    for proposal in &input.alias_report.proposals {
        receipts.push(alias_receipt(
            input.scan_id,
            input.note_id,
            proposal,
            input.created_at,
        ));
    }
    for receipt in input.identity_receipts {
        receipts.push(identity_receipt(
            input.scan_id,
            input.note_id,
            receipt,
            input.created_at,
        ));
    }
    for edge in &input.mention_graph.edges {
        let left = edge.left.0.to_string();
        let right = edge.right.0.to_string();
        let seed = format!(
            "{}:{}:{}:{:?}:{}",
            input.scan_id, input.document_id.0, left, edge.kind, right
        );
        receipts.push(AtlasEvidenceReceiptSummary {
            receipt_id: stable_id("graph-edge", &seed),
            scan_id: input.scan_id.to_owned(),
            document_id: Some(input.document_id.clone()),
            note_id: input.note_id.cloned(),
            stage: "mentionGraph".to_owned(),
            artifact_kind: AtlasEvidenceArtifactKind::GraphEdge,
            decision_status: AtlasEvidenceDecisionStatus::Observed,
            subject: mention_subject(&left),
            predicate: Some(format!("{:?}", edge.kind)),
            object: Some(mention_subject(&right)),
            surface: None,
            normalized: None,
            range: None,
            confidence: edge.weight,
            source: "dynamicMentionGraph".to_owned(),
            source_version: LEDGER_SOURCE_VERSION.to_owned(),
            mention_ids: vec![MentionId(left.clone()), MentionId(right.clone())],
            evidence_refs: vec![
                format!("document:{}", input.document_id.0),
                format!("mention:{left}"),
                format!("mention:{right}"),
            ],
            payload: json!({
                "edgeKind": format!("{:?}", edge.kind),
                "evidenceRanges": edge.evidence.iter().map(range_value).collect::<Vec<_>>(),
            }),
            created_at: input.created_at,
            ..AtlasEvidenceReceiptSummary::default()
        });
    }
    receipts
}

pub(crate) fn build_candidate_receipts(
    scan_id: &str,
    candidates: &[AtlasRichScanCandidateSummary],
    created_at: i64,
) -> Vec<AtlasEvidenceReceiptSummary> {
    candidates
        .iter()
        .map(|candidate| {
            let seed = format!(
                "{scan_id}:{}:{}:{}",
                candidate.id, candidate.label, candidate.kind
            );
            AtlasEvidenceReceiptSummary {
                receipt_id: stable_id("candidate", &seed),
                scan_id: scan_id.to_owned(),
                document_id: candidate.source_document_id.clone(),
                note_id: candidate.source_note_id.clone(),
                stage: "candidateSuggestion".to_owned(),
                artifact_kind: AtlasEvidenceArtifactKind::CandidateSuggestion,
                decision_status: candidate_decision(&candidate.decision_status),
                subject: candidate.id.clone(),
                predicate: Some("kindSuggestion".to_owned()),
                object: Some(candidate.kind.clone()),
                surface: Some(candidate.label.clone()),
                normalized: Some(candidate.label.to_ascii_lowercase()),
                range: candidate.range,
                confidence: candidate.confidence,
                source: candidate.source_stage.clone(),
                source_version: LEDGER_SOURCE_VERSION.to_owned(),
                evidence_refs: candidate_refs(candidate),
                payload: to_value(candidate),
                created_at,
                ..AtlasEvidenceReceiptSummary::default()
            }
        })
        .collect()
}

pub(crate) fn summarize_ledger(
    receipts: &[AtlasEvidenceReceiptSummary],
) -> AtlasEvidenceLedgerSummary {
    let mut summary = AtlasEvidenceLedgerSummary {
        receipt_count: receipts.len(),
        ..AtlasEvidenceLedgerSummary::default()
    };
    for receipt in receipts {
        *summary
            .counts_by_stage
            .entry(receipt.stage.clone())
            .or_default() += 1;
        *summary
            .counts_by_kind
            .entry(enum_name(&receipt.artifact_kind))
            .or_default() += 1;
        *summary
            .counts_by_decision
            .entry(enum_name(&receipt.decision_status))
            .or_default() += 1;
    }
    summary
}

pub(crate) fn receipt_rows(receipts: &[AtlasEvidenceReceiptSummary]) -> Vec<Value> {
    receipts
        .iter()
        .map(|receipt| {
            json!({
                "receipt_id": receipt.receipt_id,
                "scan_id": receipt.scan_id,
                "document_id": receipt.document_id.as_ref().map(|id| id.0.as_str()),
                "note_id": receipt.note_id.as_ref().map(|id| id.0.as_str()),
                "stage": receipt.stage,
                "artifact_kind": enum_name(&receipt.artifact_kind),
                "decision_status": enum_name(&receipt.decision_status),
                "subject": receipt.subject,
                "predicate": receipt.predicate,
                "object": receipt.object,
                "surface": receipt.surface,
                "normalized": receipt.normalized,
                "range": receipt.range.as_ref().map(range_value),
                "confidence": receipt.confidence,
                "source": receipt.source,
                "source_version": receipt.source_version,
                "mention_ids": receipt.mention_ids.iter().map(|id| id.0.as_str()).collect::<Vec<_>>(),
                "payload": receipt.payload,
                "evidence_refs": receipt.evidence_refs,
                "supersedes": receipt.supersedes,
                "reverts": receipt.reverts,
                "created_at": receipt.created_at,
            })
        })
        .collect()
}

pub(crate) fn build_dataset_factory(
    scan_id: &str,
    receipts: &[AtlasEvidenceReceiptSummary],
    created_at: i64,
) -> DatasetFactoryBuild {
    if receipts.is_empty() {
        return DatasetFactoryBuild {
            summary: AtlasDatasetFactorySummary::default(),
            snapshot_rows: Vec::new(),
            example_rows: Vec::new(),
        };
    }
    let snapshot_id = dataset_snapshot_id(scan_id, receipts);
    let mut counts_by_kind = BTreeMap::<String, usize>::new();
    let mut examples = Vec::with_capacity(receipts.len());
    for receipt in receipts {
        let example_kind = dataset_example_kind(receipt.artifact_kind);
        *counts_by_kind.entry(enum_name(&example_kind)).or_default() += 1;
        let source_receipt_ids = vec![receipt.receipt_id.clone()];
        let target = json!({
            "artifactKind": enum_name(&receipt.artifact_kind),
            "decisionStatus": enum_name(&receipt.decision_status),
            "subject": receipt.subject,
            "predicate": receipt.predicate,
            "object": receipt.object,
            "confidence": receipt.confidence,
            "payload": receipt.payload,
        });
        examples.push(AtlasDatasetExampleSummary {
            example_id: stable_id(
                "dataset-example",
                &format!("{}:{}", snapshot_id, receipt.receipt_id),
            ),
            snapshot_id: snapshot_id.clone(),
            dataset_kind: DATASET_KIND.to_owned(),
            example_kind,
            document_id: receipt.document_id.clone(),
            label: receipt
                .object
                .clone()
                .or_else(|| receipt.predicate.clone())
                .unwrap_or_default(),
            input_text: dataset_input_text(receipt),
            target,
            source_receipt_ids,
            split: stable_split(&receipt.receipt_id).to_owned(),
            payload: json!({
                "stage": receipt.stage,
                "receiptId": receipt.receipt_id,
            }),
            created_at,
        });
    }
    let preview = examples
        .iter()
        .take(SUMMARY_EXAMPLE_PREVIEW_LIMIT)
        .cloned()
        .collect::<Vec<_>>();
    let snapshot = AtlasDatasetSnapshotSummary {
        snapshot_id: snapshot_id.clone(),
        scan_id: scan_id.to_owned(),
        dataset_kind: DATASET_KIND.to_owned(),
        example_count: examples.len(),
        source_receipt_count: receipts.len(),
        counts_by_kind: counts_by_kind.clone(),
        examples: preview,
        created_at,
    };
    let snapshot_rows = vec![json!({
        "snapshot_id": snapshot_id,
        "scan_id": scan_id,
        "dataset_kind": DATASET_KIND,
        "example_count": examples.len(),
        "source_receipt_count": receipts.len(),
        "counts_by_kind": counts_by_kind,
        "payload": {
            "summaryExampleLimit": SUMMARY_EXAMPLE_PREVIEW_LIMIT,
        },
        "created_at": created_at,
    })];
    let example_rows = examples
        .iter()
        .map(|example| {
            json!({
                "example_id": example.example_id,
                "snapshot_id": example.snapshot_id,
                "dataset_kind": example.dataset_kind,
                "example_kind": enum_name(&example.example_kind),
                "document_id": example.document_id.as_ref().map(|id| id.0.as_str()),
                "label": example.label,
                "input_text": example.input_text,
                "target_json": example.target,
                "source_receipt_ids": example.source_receipt_ids,
                "split": example.split,
                "payload": example.payload,
                "created_at": example.created_at,
            })
        })
        .collect();
    DatasetFactoryBuild {
        summary: AtlasDatasetFactorySummary {
            snapshot_count: 1,
            example_count: examples.len(),
            snapshots: vec![snapshot],
        },
        snapshot_rows,
        example_rows,
    }
}

fn push_mention_receipt(
    receipts: &mut Vec<AtlasEvidenceReceiptSummary>,
    input: &DocumentEvidenceInput<'_>,
    mention: &MentionPacket,
) {
    let mention_id = mention.mention_id.0.to_string();
    let seed = format!(
        "{}:{}:{}:{}:{}",
        input.scan_id, input.document_id.0, mention_id, mention.range.start, mention.range.end
    );
    receipts.push(AtlasEvidenceReceiptSummary {
        receipt_id: stable_id("mention", &seed),
        scan_id: input.scan_id.to_owned(),
        document_id: Some(input.document_id.clone()),
        note_id: input.note_id.cloned(),
        stage: "dynamicNer".to_owned(),
        artifact_kind: AtlasEvidenceArtifactKind::Mention,
        decision_status: mention_decision(mention.status),
        subject: mention_subject(&mention_id),
        predicate: Some("extracts".to_owned()),
        object: primary_label(mention),
        surface: Some(mention.surface.to_string()),
        normalized: Some(mention.normalized.to_string()),
        range: Some(mention.range),
        confidence: mention.confidence,
        source: "dynamicNer".to_owned(),
        source_version: LEDGER_SOURCE_VERSION.to_owned(),
        mention_ids: vec![MentionId(mention_id.clone())],
        evidence_refs: vec![
            format!("document:{}", input.document_id.0),
            format!("mention:{mention_id}"),
        ],
        payload: mention_payload(mention, input.text),
        created_at: input.created_at,
        ..AtlasEvidenceReceiptSummary::default()
    });
}

fn push_kind_vote_receipts(
    receipts: &mut Vec<AtlasEvidenceReceiptSummary>,
    input: &DocumentEvidenceInput<'_>,
    mention: &MentionPacket,
) {
    let mention_id = mention.mention_id.0.to_string();
    for (idx, (label, confidence)) in mention.label_distribution.iter().enumerate() {
        let seed = format!(
            "{}:{}:{}:{}:{}",
            input.scan_id, input.document_id.0, mention_id, label, idx
        );
        receipts.push(AtlasEvidenceReceiptSummary {
            receipt_id: stable_id("kind-vote", &seed),
            scan_id: input.scan_id.to_owned(),
            document_id: Some(input.document_id.clone()),
            note_id: input.note_id.cloned(),
            stage: "dynamicNer".to_owned(),
            artifact_kind: AtlasEvidenceArtifactKind::KindVote,
            decision_status: AtlasEvidenceDecisionStatus::Observed,
            subject: mention_subject(&mention_id),
            predicate: Some("kindVote".to_owned()),
            object: Some(label.as_str().to_owned()),
            surface: Some(mention.surface.to_string()),
            normalized: Some(mention.normalized.to_string()),
            range: Some(mention.range),
            confidence: *confidence,
            source: "labelDistribution".to_owned(),
            source_version: LEDGER_SOURCE_VERSION.to_owned(),
            mention_ids: vec![MentionId(mention_id.clone())],
            evidence_refs: vec![
                format!("document:{}", input.document_id.0),
                format!("mention:{mention_id}"),
            ],
            payload: json!({
                "label": label.as_str(),
                "mentionStatus": mention_status_name(mention.status),
            }),
            created_at: input.created_at,
            ..AtlasEvidenceReceiptSummary::default()
        });
    }
}

fn alias_receipt(
    scan_id: &str,
    note_id: Option<&NoteId>,
    proposal: &AtlasAliasProposalSummary,
    created_at: i64,
) -> AtlasEvidenceReceiptSummary {
    AtlasEvidenceReceiptSummary {
        receipt_id: stable_id("alias", &format!("{scan_id}:{}", proposal.case_id)),
        scan_id: scan_id.to_owned(),
        document_id: Some(proposal.document_id.clone()),
        note_id: note_id.cloned(),
        stage: "aliasResolution".to_owned(),
        artifact_kind: AtlasEvidenceArtifactKind::AliasProposal,
        decision_status: alias_decision(proposal.decision),
        subject: mention_subject(&proposal.mention_id.0),
        predicate: Some(enum_name(&proposal.relation)),
        object: Some(alias_target_label(&proposal.target)),
        surface: Some(proposal.surface.clone()),
        normalized: Some(proposal.normalized.clone()),
        range: Some(proposal.range),
        confidence: proposal.confidence,
        source: "aliasResolution".to_owned(),
        source_version: LEDGER_SOURCE_VERSION.to_owned(),
        mention_ids: vec![proposal.mention_id.clone()],
        evidence_refs: vec![
            format!("document:{}", proposal.document_id.0),
            format!("mention:{}", proposal.mention_id.0),
        ],
        payload: to_value(proposal),
        created_at,
        ..AtlasEvidenceReceiptSummary::default()
    }
}

fn identity_receipt(
    scan_id: &str,
    note_id: Option<&NoteId>,
    receipt: &AtlasIdentityReceiptSummary,
    created_at: i64,
) -> AtlasEvidenceReceiptSummary {
    AtlasEvidenceReceiptSummary {
        receipt_id: stable_id("identity", &format!("{scan_id}:{}", receipt.receipt_id)),
        scan_id: scan_id.to_owned(),
        document_id: Some(receipt.document_id.clone()),
        note_id: note_id.cloned(),
        stage: "identityResolution".to_owned(),
        artifact_kind: AtlasEvidenceArtifactKind::IdentityReceipt,
        decision_status: identity_decision(receipt.action),
        subject: format!("identity:{}", receipt.receipt_id),
        predicate: Some(enum_name(&receipt.action)),
        object: Some(identity_target_label(&receipt.target)),
        surface: Some(receipt.surface.clone()),
        confidence: receipt.confidence,
        source: "identityResolution".to_owned(),
        source_version: LEDGER_SOURCE_VERSION.to_owned(),
        mention_ids: receipt.mention_ids.clone(),
        evidence_refs: receipt
            .mention_ids
            .iter()
            .map(|id| format!("mention:{}", id.0))
            .chain(std::iter::once(format!(
                "document:{}",
                receipt.document_id.0
            )))
            .collect(),
        payload: to_value(receipt),
        created_at,
        ..AtlasEvidenceReceiptSummary::default()
    }
}

fn mention_payload(mention: &MentionPacket, text: &str) -> Value {
    json!({
        "mentionKind": mention_kind_name(mention.mention_kind),
        "mentionStatus": mention_status_name(mention.status),
        "sentenceIndex": mention.sentence_index,
        "chunkId": mention.chunk_id.as_ref().map(|value| value.as_str()),
        "entityRef": entity_ref_value(mention.entity_ref.as_ref()),
        "textWindow": text_window(text, mention.range, 180),
        "labelDistribution": mention.label_distribution.iter().map(|(label, confidence)| {
            json!({ "label": label.as_str(), "confidence": confidence })
        }).collect::<Vec<_>>(),
        "sourceVotes": mention.source_votes.iter().map(|vote| {
            json!({
                "source": vote_source_name(vote.source),
                "label": vote.label.as_ref().map(|label| label.as_str()),
                "entityRef": entity_ref_value(vote.entity_ref.as_ref()),
                "confidence": vote.confidence,
                "reason": format!("{:?}", vote.reason),
            })
        }).collect::<Vec<_>>(),
    })
}

fn dataset_input_text(receipt: &AtlasEvidenceReceiptSummary) -> String {
    receipt
        .surface
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| receipt.object.as_deref())
        .or_else(|| receipt.predicate.as_deref())
        .unwrap_or(receipt.subject.as_str())
        .chars()
        .take(320)
        .collect()
}

fn dataset_example_kind(kind: AtlasEvidenceArtifactKind) -> AtlasDatasetExampleKind {
    match kind {
        AtlasEvidenceArtifactKind::Mention => AtlasDatasetExampleKind::NerSpan,
        AtlasEvidenceArtifactKind::KindVote => AtlasDatasetExampleKind::KindVote,
        AtlasEvidenceArtifactKind::AliasProposal => AtlasDatasetExampleKind::AliasDecision,
        AtlasEvidenceArtifactKind::IdentityReceipt => AtlasDatasetExampleKind::IdentityResolution,
        AtlasEvidenceArtifactKind::CandidateSuggestion => {
            AtlasDatasetExampleKind::CandidateSuggestion
        }
        AtlasEvidenceArtifactKind::GraphEdge => AtlasDatasetExampleKind::GraphEdge,
        AtlasEvidenceArtifactKind::FrameTrigger
        | AtlasEvidenceArtifactKind::FrameArgument
        | AtlasEvidenceArtifactKind::FrameFact => AtlasDatasetExampleKind::FrameExtraction,
        AtlasEvidenceArtifactKind::UserCorrection
        | AtlasEvidenceArtifactKind::Rejection
        | AtlasEvidenceArtifactKind::DatasetExample => AtlasDatasetExampleKind::IdentityResolution,
    }
}

fn dataset_snapshot_id(scan_id: &str, receipts: &[AtlasEvidenceReceiptSummary]) -> String {
    let mut seed = format!("{scan_id}:{}:", receipts.len());
    for receipt in receipts.iter().take(4096) {
        seed.push_str(&receipt.receipt_id);
        seed.push('|');
    }
    stable_id("dataset-snapshot", &seed)
}

fn stable_split(key: &str) -> &'static str {
    match hash64(key.as_bytes()) % 10 {
        0 => "holdout",
        1 => "eval",
        _ => "train",
    }
}

fn mention_decision(status: MentionStatus) -> AtlasEvidenceDecisionStatus {
    match status {
        MentionStatus::AcceptedKnown | MentionStatus::AcceptedNew => {
            AtlasEvidenceDecisionStatus::Accepted
        }
        MentionStatus::AliasCandidate => AtlasEvidenceDecisionStatus::Proposed,
        MentionStatus::NeedsAdjudication => AtlasEvidenceDecisionStatus::Deferred,
        MentionStatus::Rejected => AtlasEvidenceDecisionStatus::Rejected,
    }
}

fn alias_decision(decision: AtlasAliasProposalDecision) -> AtlasEvidenceDecisionStatus {
    match decision {
        AtlasAliasProposalDecision::Accept => AtlasEvidenceDecisionStatus::Accepted,
        AtlasAliasProposalDecision::Propose => AtlasEvidenceDecisionStatus::Proposed,
        AtlasAliasProposalDecision::Defer => AtlasEvidenceDecisionStatus::Deferred,
        AtlasAliasProposalDecision::Reject => AtlasEvidenceDecisionStatus::Rejected,
    }
}

fn identity_decision(action: AtlasIdentityReceiptAction) -> AtlasEvidenceDecisionStatus {
    match action {
        AtlasIdentityReceiptAction::KnownEntity
        | AtlasIdentityReceiptAction::AliasOfKnown
        | AtlasIdentityReceiptAction::FullDesignation => AtlasEvidenceDecisionStatus::Accepted,
        AtlasIdentityReceiptAction::Coreference
        | AtlasIdentityReceiptAction::MergeRunLocal
        | AtlasIdentityReceiptAction::NewEntity => AtlasEvidenceDecisionStatus::Proposed,
        AtlasIdentityReceiptAction::Split | AtlasIdentityReceiptAction::Defer => {
            AtlasEvidenceDecisionStatus::Deferred
        }
    }
}

fn candidate_decision(status: &str) -> AtlasEvidenceDecisionStatus {
    match status {
        "accepted" => AtlasEvidenceDecisionStatus::Accepted,
        "review" => AtlasEvidenceDecisionStatus::Proposed,
        "rejected" => AtlasEvidenceDecisionStatus::Rejected,
        _ => AtlasEvidenceDecisionStatus::Observed,
    }
}

fn primary_label(mention: &MentionPacket) -> Option<String> {
    mention
        .label_distribution
        .iter()
        .max_by(|left, right| left.1.total_cmp(&right.1))
        .map(|(label, _)| label.as_str().to_owned())
}

fn mention_subject(id: &str) -> String {
    format!("mention:{id}")
}

fn candidate_refs(candidate: &AtlasRichScanCandidateSummary) -> Vec<String> {
    let mut refs = Vec::new();
    if let Some(document_id) = &candidate.source_document_id {
        refs.push(format!("document:{}", document_id.0));
    }
    refs.push(format!("candidate:{}", candidate.id));
    refs
}

fn alias_target_label(target: &AtlasAliasProposalTarget) -> String {
    match target {
        AtlasAliasProposalTarget::KnownEntity { canonical_name, .. } => canonical_name.clone(),
        AtlasAliasProposalTarget::RunLocalSurface { display, .. } => display.clone(),
        AtlasAliasProposalTarget::NewEntity => "newEntity".to_owned(),
        AtlasAliasProposalTarget::Deferred => "deferred".to_owned(),
    }
}

fn identity_target_label(target: &AtlasIdentityTargetSummary) -> String {
    match target {
        AtlasIdentityTargetSummary::KnownEntity { canonical_name, .. } => canonical_name.clone(),
        AtlasIdentityTargetSummary::RunLocalEntity { display, .. }
        | AtlasIdentityTargetSummary::NewEntity { display, .. } => display.clone(),
        AtlasIdentityTargetSummary::Deferred => "deferred".to_owned(),
    }
}

fn mention_kind_name(kind: MentionKind) -> &'static str {
    match kind {
        MentionKind::Named => "named",
        MentionKind::Nominal => "nominal",
        MentionKind::Pronoun => "pronoun",
    }
}

fn mention_status_name(status: MentionStatus) -> &'static str {
    match status {
        MentionStatus::AcceptedKnown => "acceptedKnown",
        MentionStatus::AcceptedNew => "acceptedNew",
        MentionStatus::AliasCandidate => "aliasCandidate",
        MentionStatus::NeedsAdjudication => "needsAdjudication",
        MentionStatus::Rejected => "rejected",
    }
}

fn vote_source_name(source: MentionSourceKind) -> &'static str {
    match source {
        MentionSourceKind::KnownLexicon => "knownLexicon",
        MentionSourceKind::NativeDiscovery => "nativeDiscovery",
        MentionSourceKind::Scirs2Rule => "scirs2Rule",
        MentionSourceKind::Scirs2Pattern => "scirs2Pattern",
        MentionSourceKind::ModelDiscovery => "modelDiscovery",
        MentionSourceKind::ModelVerify => "modelVerify",
        MentionSourceKind::Adjudication => "adjudication",
        MentionSourceKind::Pronoun => "pronoun",
    }
}

fn entity_ref_value(entity_ref: Option<&MentionEntityRef>) -> Value {
    match entity_ref {
        Some(MentionEntityRef::Known(entity_id)) => json!({ "known": entity_id.0 }),
        Some(MentionEntityRef::Speculative(key)) => json!({ "speculative": key }),
        None => Value::Null,
    }
}

fn text_window(text: &str, range: TextRange, limit: usize) -> String {
    if text.is_empty() {
        return String::new();
    }
    let start = floor_boundary(text, range.start as usize).min(text.len());
    let end = floor_boundary(text, range.end as usize).min(text.len());
    let left = start.saturating_sub(limit / 2);
    let right = end.saturating_add(limit / 2).min(text.len());
    text.get(floor_boundary(text, left)..floor_boundary(text, right))
        .unwrap_or_default()
        .trim()
        .chars()
        .take(limit)
        .collect()
}

fn floor_boundary(text: &str, mut index: usize) -> usize {
    index = index.min(text.len());
    while index > 0 && !text.is_char_boundary(index) {
        index -= 1;
    }
    index
}

fn range_value(range: &TextRange) -> Value {
    json!({ "start": range.start, "end": range.end })
}

fn enum_name<T: Serialize>(value: &T) -> String {
    serde_json::to_value(value)
        .ok()
        .and_then(|value| value.as_str().map(str::to_owned))
        .unwrap_or_default()
}

fn to_value<T: Serialize>(value: &T) -> Value {
    serde_json::to_value(value).unwrap_or(Value::Null)
}

fn stable_id(prefix: &str, seed: &str) -> String {
    format!("{prefix}-{:016x}", hash64(seed.as_bytes()))
}

fn hash64(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}
