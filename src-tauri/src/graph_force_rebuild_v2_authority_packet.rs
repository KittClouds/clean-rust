use serde_json::Value;

pub(super) fn validate_compact_authority_packet(
    packet: &Value,
    scope_id: &str,
    snapshot_id: &str,
    authority_hash: &str,
    manifest_id: &str,
    run_handle: Option<&str>,
) -> Result<(), String> {
    if text(packet, "schemaVersion") != "phoenix-graph-rebuild/v1"
        || text(packet, "id") != snapshot_id
        || text(packet, "scopeId") != scope_id
        || manifest_id.is_empty()
    {
        return Err("compact packet snapshot identity drift".to_owned());
    }
    let authority = object(packet, "authorityContract")?;
    if text(authority, "schemaVersion") != "phoenix-graph-snapshot-authority/v1"
        || text(authority, "authority") != "graph_rebuild_live_contract"
        || text(authority, "snapshotId") != snapshot_id
        || text(authority, "scopeId") != scope_id
        || text(authority, "contentHash") != authority_hash
    {
        return Err("compact packet authority seal drift".to_owned());
    }
    let manifest = object(packet, "contentManifest")?;
    if text(manifest, "snapshotId") != snapshot_id || text(manifest, "scopeId") != scope_id {
        return Err("compact packet content manifest drift".to_owned());
    }
    let interactive = object(packet, "interactiveRunAuthority")?;
    let durable = object(interactive, "durable")?;
    if text(interactive, "snapshotId") != snapshot_id
        || text(interactive, "scopeId") != scope_id
        || text(durable, "snapshotId") != snapshot_id
        || text(durable, "scopeId") != scope_id
        || text(durable, "manifestId") != manifest_id
        || text(durable, "runHandle").is_empty()
        || run_handle.is_some_and(|expected| text(durable, "runHandle") != expected)
    {
        return Err("compact packet durable authority drift".to_owned());
    }
    if text(packet, "generationReceiptId").is_empty()
        || !text(packet, "generationDigestSha256").starts_with("sha256-")
    {
        return Err("compact packet generation identity missing".to_owned());
    }

    let counts = object(authority, "counts")?;
    let counters = object(packet, "counters")?;
    for (authority_name, counter_name) in [
        ("chunks", "chunks"),
        ("mentions", "mentions"),
        ("anchors", "acceptedAnchors"),
        ("relationships", "relationships"),
        ("events", "events"),
        ("temporalEdges", "temporalEdges"),
        ("causalEdges", "causalEdges"),
        ("memoryState", "memoryState"),
        (
            "coreferenceRecoveries",
            "documentSemanticLocalCoreferenceRecoveries",
        ),
        ("nodes", "nodes"),
        ("edges", "edges"),
        ("embeddingTargets", "embeddingTargets"),
    ] {
        if number(counts, authority_name)? != number(counters, counter_name)? {
            return Err(format!("compact packet counter drift: {counter_name}"));
        }
    }
    let note_count = packet
        .get("noteIds")
        .and_then(Value::as_array)
        .map_or(0, |rows| rows.len() as u64);
    let embedding_targets = number(counts, "embeddingTargets")?;
    if number(counts, "notes")? != note_count
        || number(counts, "admittedEmbeddingTargets")? > embedding_targets
        || number(counts, "packetTargets")? != embedding_targets
        || number(counts, "packetObjects")? == 0
        || counts
            .get("packetFamilies")
            .and_then(Value::as_object)
            .is_none()
    {
        return Err("compact packet authority summary drift".to_owned());
    }
    for name in [
        "chunks",
        "mentions",
        "entityAnchors",
        "relationships",
        "events",
        "episodes",
        "temporalEdges",
        "causalEdges",
        "memoryState",
        "embeddingTargets",
        "embeddingVectors",
        "nodes",
        "edges",
        "projectionRefs",
        "resolutionSuggestions",
        "chunkSemanticBridges",
        "memoryGovernanceCandidates",
        "episodeConnections",
        "episodeProjectionEdges",
    ] {
        if packet
            .get(name)
            .is_some_and(|value| !value.as_array().is_some_and(Vec::is_empty))
        {
            return Err(format!("compact packet materialized legacy array: {name}"));
        }
    }

    let registry = object(packet, "evidenceTargetRegistry")?;
    let canonical = number(registry, "canonicalTargets")?;
    let exposed = number(registry, "exposedTargets")?;
    let chunks = number(registry, "chunks")?;
    let typed = number(registry, "typedGraphObjects")?;
    let support = number(registry, "supportTargets")?;
    if text(registry, "sourceSnapshotId") != snapshot_id
        || text(registry, "sourceScopeId") != scope_id
        || canonical != number(counts, "embeddingTargets")?
        || chunks != number(counts, "chunks")?
        || exposed + support != canonical
        || chunks + typed != exposed
        || number(registry, "duplicateTargets")? != 0
        || number(registry, "orphanTargets")? != 0
        || !text(registry, "identityHash").starts_with("fnv32-")
    {
        return Err("compact packet evidence registry drift".to_owned());
    }
    Ok(())
}

fn object<'a>(value: &'a Value, name: &str) -> Result<&'a Value, String> {
    value
        .get(name)
        .filter(|row| row.is_object())
        .ok_or_else(|| format!("compact packet object missing: {name}"))
}

fn text<'a>(value: &'a Value, name: &str) -> &'a str {
    value.get(name).and_then(Value::as_str).unwrap_or_default()
}

fn number(value: &Value, name: &str) -> Result<u64, String> {
    value
        .get(name)
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("compact packet counter missing: {name}"))
}
