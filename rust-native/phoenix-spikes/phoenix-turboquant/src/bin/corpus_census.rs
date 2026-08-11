use std::collections::BTreeMap;
use std::env;
use std::path::PathBuf;

use phoenix_memory_contract::{
    ContentUnitKind, ContentUnitRecord, PageKindV3, ParticipantRole, TurnRecord,
    VerifiedGraphGenerationV3,
};
use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Census {
    contract: &'static str,
    path: String,
    artifact_bytes: u64,
    generation_hash: String,
    source_set_hash: String,
    cohort_hash: String,
    source_count: u64,
    document_revision_count: u64,
    conversation_count: u64,
    turn_count: u64,
    content_unit_count: usize,
    embeddable_row_count: usize,
    content_units_by_kind: BTreeMap<&'static str, usize>,
    turns_by_role: BTreeMap<&'static str, usize>,
    human_turn_query_candidates: usize,
}

fn main() -> Result<(), String> {
    let path = parse_path()?;
    let generation = VerifiedGraphGenerationV3::open(&path).map_err(|error| error.to_string())?;
    let units = generation
        .typed_page::<ContentUnitRecord>(PageKindV3::ContentUnits)
        .map_err(|error| error.to_string())?;
    let turns = generation
        .typed_page::<TurnRecord>(PageKindV3::Turns)
        .map_err(|error| error.to_string())?;

    let mut content_units_by_kind = BTreeMap::new();
    let mut embeddable_row_count = 0usize;
    for unit in units {
        let kind = ContentUnitKind::from_raw(unit.kind).ok_or("invalid content unit kind")?;
        *content_units_by_kind
            .entry(content_kind_label(kind))
            .or_insert(0) += 1;
        if matches!(kind, ContentUnitKind::DynamicChunk | ContentUnitKind::Turn) {
            embeddable_row_count += 1;
        }
    }

    let mut turns_by_role = BTreeMap::new();
    let mut human_turn_query_candidates = 0usize;
    for turn in turns {
        let role = ParticipantRole::from_raw(turn.role).ok_or("invalid participant role")?;
        *turns_by_role.entry(role_label(role)).or_insert(0) += 1;
        human_turn_query_candidates += usize::from(role == ParticipantRole::User);
    }

    let header = generation.header();
    let census = Census {
        contract: "phoenix.turboquant-corpus-census/v1",
        path: path.display().to_string(),
        artifact_bytes: header.total_len,
        generation_hash: hex(header.generation_hash),
        source_set_hash: hex(header.source_set_hash),
        cohort_hash: hex(header.cohort_hash),
        source_count: header.source_count,
        document_revision_count: header.document_revision_count,
        conversation_count: header.conversation_count,
        turn_count: header.turn_count,
        content_unit_count: units.len(),
        embeddable_row_count,
        content_units_by_kind,
        turns_by_role,
        human_turn_query_candidates,
    };
    println!(
        "{}",
        serde_json::to_string_pretty(&census).map_err(|error| error.to_string())?
    );
    Ok(())
}

fn parse_path() -> Result<PathBuf, String> {
    let mut args = env::args_os().skip(1);
    let path = args
        .next()
        .map(PathBuf::from)
        .ok_or("usage: corpus_census <generation.phxgg3>")?;
    if args.next().is_some() {
        return Err("usage: corpus_census <generation.phxgg3>".to_owned());
    }
    Ok(path)
}

fn content_kind_label(kind: ContentUnitKind) -> &'static str {
    match kind {
        ContentUnitKind::Document => "document",
        ContentUnitKind::Chapter => "chapter",
        ContentUnitKind::Paragraph => "paragraph",
        ContentUnitKind::Sentence => "sentence",
        ContentUnitKind::DynamicChunk => "dynamicChunk",
        ContentUnitKind::Span => "span",
        ContentUnitKind::Turn => "turn",
        ContentUnitKind::TurnSubchunk => "turnSubchunk",
    }
}

fn role_label(role: ParticipantRole) -> &'static str {
    match role {
        ParticipantRole::System => "system",
        ParticipantRole::User => "user",
        ParticipantRole::Assistant => "assistant",
        ParticipantRole::Tool => "tool",
        ParticipantRole::Other => "other",
    }
}

fn hex(bytes: [u8; 32]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}
