use phoenix_types::{
    AtlasEvidenceArtifactKind, AtlasEvidenceDecisionStatus, AtlasEvidenceReceiptSummary,
    DocumentId, FrameFactCandidate, MentionEntityRef, NoteId, StructureArtifact, TextRange,
    UmrLiteArgument, UmrLiteFrame,
};
use serde::Serialize;
use serde_json::{json, Value};

const FRAME_SOURCE_VERSION: &str = "atlas-umr-lite-v1";

pub(crate) struct FrameExtractionInput<'a> {
    pub scan_id: &'a str,
    pub document_id: &'a DocumentId,
    pub note_id: Option<&'a NoteId>,
    pub text: &'a str,
    pub structure: &'a StructureArtifact,
    pub created_at: i64,
}

#[derive(Default)]
pub(crate) struct FrameExtractionRows {
    pub frame_rows: Vec<Value>,
    pub argument_rows: Vec<Value>,
    pub fact_rows: Vec<Value>,
    pub receipts: Vec<AtlasEvidenceReceiptSummary>,
}

impl FrameExtractionRows {
    pub(crate) fn frame_count(&self) -> usize {
        self.frame_rows.len()
    }

    pub(crate) fn argument_count(&self) -> usize {
        self.argument_rows.len()
    }

    pub(crate) fn fact_count(&self) -> usize {
        self.fact_rows.len()
    }
}

pub(crate) fn build_rows(input: FrameExtractionInput<'_>) -> FrameExtractionRows {
    let mut rows = FrameExtractionRows::default();
    for frame in &input.structure.umr_frames {
        let frame_id = persisted_frame_id(input.scan_id, input.document_id, &frame.frame_id);
        let evidence_refs = vec![
            format!("document:{}", input.document_id.0),
            format!("frame:{frame_id}"),
        ];
        rows.frame_rows.push(json!({
            "frame_id": frame_id,
            "scan_id": input.scan_id,
            "document_id": input.document_id.0,
            "note_id": input.note_id.map(|id| id.0.as_str()),
            "sentence_index": frame.sentence_index as i64,
            "trigger_range": range_value(frame.trigger_range),
            "lemma": frame.lemma,
            "event_class": frame.event_class,
            "relation_type": frame.relation_type,
            "clause_range": range_value(frame.clause_range),
            "confidence": frame.confidence,
            "scope_ops": frame.scopes,
            "payload": to_value(frame),
            "evidence_refs": evidence_refs,
            "created_at": input.created_at,
        }));
        rows.receipts.push(frame_trigger_receipt(
            &input,
            frame,
            &frame_id,
            evidence_refs,
        ));
        for (index, argument) in frame.arguments.iter().enumerate() {
            let argument_id = stable_id(
                "framearg",
                &format!("{frame_id}:{index}:{:?}", argument.role),
            );
            let evidence_refs = vec![
                format!("document:{}", input.document_id.0),
                format!("frame:{frame_id}"),
                format!("argument:{argument_id}"),
            ];
            rows.argument_rows.push(json!({
                "argument_id": argument_id,
                "frame_id": frame_id,
                "scan_id": input.scan_id,
                "document_id": input.document_id.0,
                "role": enum_name(&argument.role),
                "range": range_value(argument.range),
                "surface": argument.surface,
                "entity_ref": entity_ref_value(argument.entity_ref.as_ref()),
                "confidence": argument.confidence,
                "source": argument.source.as_ref().map(enum_name),
                "payload": to_value(argument),
                "evidence_refs": evidence_refs,
                "created_at": input.created_at,
            }));
            rows.receipts.push(frame_argument_receipt(
                &input,
                frame,
                argument,
                &argument_id,
                evidence_refs,
            ));
        }
    }
    for fact in &input.structure.frame_facts {
        let frame_id = persisted_frame_id(input.scan_id, input.document_id, &fact.frame_id);
        let fact_id = persisted_fact_id(input.scan_id, input.document_id, &fact.fact_id);
        let evidence_refs = vec![
            format!("document:{}", input.document_id.0),
            format!("frame:{frame_id}"),
            format!("frame_fact:{fact_id}"),
        ];
        rows.fact_rows.push(json!({
            "fact_id": fact_id,
            "frame_id": frame_id,
            "scan_id": input.scan_id,
            "document_id": input.document_id.0,
            "fact_kind": fact.fact_kind,
            "subject": fact.subject,
            "predicate": fact.predicate,
            "object": fact.object,
            "confidence": fact.confidence,
            "payload": to_value(fact),
            "evidence_refs": evidence_refs,
            "created_at": input.created_at,
        }));
        rows.receipts
            .push(frame_fact_receipt(&input, fact, &fact_id, evidence_refs));
    }
    rows
}

pub(crate) fn persisted_frame_id(
    scan_id: &str,
    document_id: &DocumentId,
    frame_id: &str,
) -> String {
    stable_id("frame", &format!("{scan_id}:{}:{frame_id}", document_id.0))
}

pub(crate) fn fact_entity_id(value: &str) -> Option<&str> {
    value
        .strip_prefix("entity:")
        .filter(|entity_id| !entity_id.is_empty())
}

fn frame_trigger_receipt(
    input: &FrameExtractionInput<'_>,
    frame: &UmrLiteFrame,
    frame_id: &str,
    evidence_refs: Vec<String>,
) -> AtlasEvidenceReceiptSummary {
    AtlasEvidenceReceiptSummary {
        receipt_id: stable_id("frame-trigger", &format!("{}:{frame_id}", input.scan_id)),
        scan_id: input.scan_id.to_owned(),
        document_id: Some(input.document_id.clone()),
        note_id: input.note_id.cloned(),
        stage: "frameExtraction".to_owned(),
        artifact_kind: AtlasEvidenceArtifactKind::FrameTrigger,
        decision_status: AtlasEvidenceDecisionStatus::Observed,
        subject: format!("frame:{frame_id}"),
        predicate: Some(frame.relation_type.clone()),
        object: Some(frame.lemma.clone()),
        surface: Some(span_text(input.text, frame.trigger_range)),
        normalized: Some(frame.lemma.to_ascii_lowercase()),
        range: Some(frame.trigger_range),
        confidence: frame.confidence,
        source: "umrLite".to_owned(),
        source_version: FRAME_SOURCE_VERSION.to_owned(),
        evidence_refs,
        payload: to_value(frame),
        created_at: input.created_at,
        ..AtlasEvidenceReceiptSummary::default()
    }
}

fn frame_argument_receipt(
    input: &FrameExtractionInput<'_>,
    frame: &UmrLiteFrame,
    argument: &UmrLiteArgument,
    argument_id: &str,
    evidence_refs: Vec<String>,
) -> AtlasEvidenceReceiptSummary {
    AtlasEvidenceReceiptSummary {
        receipt_id: stable_id(
            "frame-argument",
            &format!("{}:{argument_id}", input.scan_id),
        ),
        scan_id: input.scan_id.to_owned(),
        document_id: Some(input.document_id.clone()),
        note_id: input.note_id.cloned(),
        stage: "frameExtraction".to_owned(),
        artifact_kind: AtlasEvidenceArtifactKind::FrameArgument,
        decision_status: AtlasEvidenceDecisionStatus::Observed,
        subject: format!(
            "frame:{}",
            persisted_frame_id(input.scan_id, input.document_id, &frame.frame_id)
        ),
        predicate: Some(enum_name(&argument.role)),
        object: Some(argument_key(argument)),
        surface: Some(argument.surface.clone()),
        range: Some(argument.range),
        confidence: argument.confidence,
        source: argument
            .source
            .as_ref()
            .map(enum_name)
            .unwrap_or_else(|| "umrLite".to_owned()),
        source_version: FRAME_SOURCE_VERSION.to_owned(),
        evidence_refs,
        payload: to_value(argument),
        created_at: input.created_at,
        ..AtlasEvidenceReceiptSummary::default()
    }
}

fn frame_fact_receipt(
    input: &FrameExtractionInput<'_>,
    fact: &FrameFactCandidate,
    fact_id: &str,
    evidence_refs: Vec<String>,
) -> AtlasEvidenceReceiptSummary {
    AtlasEvidenceReceiptSummary {
        receipt_id: stable_id("frame-fact", &format!("{}:{fact_id}", input.scan_id)),
        scan_id: input.scan_id.to_owned(),
        document_id: Some(input.document_id.clone()),
        note_id: input.note_id.cloned(),
        stage: "frameExtraction".to_owned(),
        artifact_kind: AtlasEvidenceArtifactKind::FrameFact,
        decision_status: AtlasEvidenceDecisionStatus::Proposed,
        subject: fact.subject.clone(),
        predicate: Some(fact.predicate.clone()),
        object: Some(fact.object.clone()),
        confidence: fact.confidence,
        source: "umrLite".to_owned(),
        source_version: FRAME_SOURCE_VERSION.to_owned(),
        evidence_refs,
        payload: to_value(fact),
        created_at: input.created_at,
        ..AtlasEvidenceReceiptSummary::default()
    }
}

fn persisted_fact_id(scan_id: &str, document_id: &DocumentId, fact_id: &str) -> String {
    stable_id(
        "framefact",
        &format!("{scan_id}:{}:{fact_id}", document_id.0),
    )
}

fn argument_key(argument: &UmrLiteArgument) -> String {
    match &argument.entity_ref {
        Some(MentionEntityRef::Known(entity_id)) => format!("entity:{}", entity_id.0),
        Some(MentionEntityRef::Speculative(key)) => format!("candidate:{key}"),
        None => argument.surface.clone(),
    }
}

fn entity_ref_value(entity_ref: Option<&MentionEntityRef>) -> Value {
    match entity_ref {
        Some(MentionEntityRef::Known(entity_id)) => json!({ "known": entity_id.0 }),
        Some(MentionEntityRef::Speculative(key)) => json!({ "speculative": key }),
        None => Value::Null,
    }
}

fn span_text(text: &str, range: TextRange) -> String {
    let start = floor_boundary(text, range.start as usize);
    let end = floor_boundary(text, range.end as usize);
    text.get(start.min(text.len())..end.min(text.len()))
        .unwrap_or_default()
        .trim()
        .to_owned()
}

fn floor_boundary(text: &str, mut index: usize) -> usize {
    index = index.min(text.len());
    while index > 0 && !text.is_char_boundary(index) {
        index -= 1;
    }
    index
}

fn range_value(range: TextRange) -> Value {
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
