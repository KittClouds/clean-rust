use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

use phoenix_graph_kernel::{
    project_graph_proposal_outcomes, GraphTruthLineage, KernelEdge, KernelGraphSnapshot,
    KernelVertex,
};
use phoenix_semantic_v2::DocumentArchive;
use phoenix_store_native_core::{
    PhoenixArchiveStoreV2, PhoenixGraphKernelStoreV2, PhoenixGraphLearningStore,
    PhoenixNativeRowStore,
};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use serde_json::{json, Value};

fn main() -> Result<(), String> {
    let config = Config::parse(std::env::args().skip(1))?;
    let report = audit(&config)?;
    println!(
        "{}",
        if config.json {
            serde_json::to_string_pretty(&report)
        } else {
            serde_json::to_string(&report)
        }
        .map_err(|error| format!("serialize audit: {error}"))?
    );
    Ok(())
}

struct Config {
    store_path: PathBuf,
    dump_scoped_documents: Option<PathBuf>,
    json: bool,
}

impl Config {
    fn parse(args: impl Iterator<Item = String>) -> Result<Self, String> {
        let mut store_path = None;
        let mut dump_scoped_documents = None;
        let mut json = false;
        let mut args = args.peekable();
        while let Some(argument) = args.next() {
            match argument.as_str() {
                "--store-path" => store_path = args.next().map(PathBuf::from),
                "--dump-scoped-documents" => dump_scoped_documents = args.next().map(PathBuf::from),
                "--json" => json = true,
                other => return Err(format!("unknown argument: {other}")),
            }
        }
        let store_path = store_path.ok_or("--store-path is required")?;
        if !store_path.is_dir() {
            return Err(format!(
                "store path does not exist: {}",
                store_path.display()
            ));
        }
        Ok(Self {
            store_path,
            dump_scoped_documents,
            json,
        })
    }
}

fn audit(config: &Config) -> Result<Value, String> {
    let store = PhoenixOvergraphStore::open(&config.store_path).map_err(display_error)?;
    let relation_counts = store.relation_counts().map_err(display_error)?;
    let scoped_documents = store
        .fetch_rows("scoped_documents")
        .map_err(display_error)?;
    if let Some(path) = &config.dump_scoped_documents {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("create {}: {error}", parent.display()))?;
        }
        fs::write(
            path,
            serde_json::to_vec_pretty(&scoped_documents)
                .map_err(|error| format!("serialize scoped documents: {error}"))?,
        )
        .map_err(|error| format!("write {}: {error}", path.display()))?;
    }

    let snapshot = store.load_live_kernel_snapshot().map_err(display_error)?;
    let checkpoint = store.load_kernel_checkpoint().map_err(display_error)?;
    let journal = store.load_kernel_journal_after(0).map_err(display_error)?;
    let commits = store.load_graph_truth_commits().map_err(display_error)?;
    let receipts = store
        .load_graph_proposal_receipts()
        .map_err(display_error)?;
    let outcomes = project_graph_proposal_outcomes(&receipts, &commits)
        .map_err(|error| format!("project proposal outcomes: {error}"))?;
    let lineage = GraphTruthLineage::build(commits.clone());
    let archives = store
        .load_latest_document_archives(None)
        .map_err(display_error)?;
    let generation = store.kernel_current_generation().map_err(display_error)?;
    let journal_len = store.kernel_journal_len().map_err(display_error)?;

    let report = json!({
        "schemaVersion": "phoenix-native-decision-surface-audit/v1",
        "storePath": config.store_path.display().to_string(),
        "readContract": "copied store; no init, append, checkpoint, or mutation methods invoked",
        "relations": {
            "nonEmpty": relation_counts.into_iter().collect::<BTreeMap<_, _>>(),
            "declaredCount": store.relation_names().len(),
        },
        "scopedDocuments": scoped_document_summary(&scoped_documents),
        "latestDocumentArchives": archive_summary(&archives),
        "kernel": kernel_summary(&snapshot, generation, journal_len),
        "checkpoint": checkpoint.as_ref().map(|value| json!({
            "checkpointId": value.meta.checkpoint_id,
            "generation": value.meta.generation,
            "sourceRevision": value.meta.source_revision,
            "createdAt": value.meta.created_at,
            "vertices": value.snapshot.vertices.len(),
            "assertedEdges": value.snapshot.asserted_edges.len(),
            "candidateEdges": value.snapshot.candidate_edges.len(),
        })),
        "journal": {
            "loadedAfterZero": journal.len(),
            "reportedLength": journal_len,
            "generationRange": range_u64(journal.iter().map(|row| row.generation)),
            "createdAtRange": range_i64(journal.iter().map(|row| row.created_at)),
            "batchEntries": journal.iter().filter(|row| row.batch.is_some()).count(),
            "commitMarkers": journal.iter().filter(|row| row.commit_id.is_some()).count(),
        },
        "graphTruth": graph_truth_summary(&commits, lineage),
        "proposalReceipts": proposal_summary(&receipts, &outcomes),
    });
    store.close_fast().map_err(display_error)?;
    Ok(report)
}

fn scoped_document_summary(rows: &[Value]) -> Value {
    let mut namespaces = BTreeMap::new();
    let mut document_keys = BTreeMap::new();
    let mut scopes = BTreeMap::new();
    let mut payload_schemas = BTreeMap::new();
    let mut metadata = Vec::with_capacity(rows.len());
    for row in rows {
        count(&mut namespaces, string_field(row, "namespace"));
        count(&mut document_keys, string_field(row, "document_key"));
        count(&mut scopes, string_field(row, "scope_folder_id"));
        let payload = row
            .get("payload")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let parsed = serde_json::from_str::<Value>(payload).ok();
        let schema = parsed
            .as_ref()
            .and_then(|value| value.get("schemaVersion"))
            .and_then(Value::as_str)
            .unwrap_or(if parsed.is_some() {
                "json-without-schema"
            } else {
                "non-json"
            });
        count(&mut payload_schemas, schema);
        metadata.push(json!({
            "id": string_field(row, "id"),
            "scope": string_field(row, "scope_folder_id"),
            "namespace": string_field(row, "namespace"),
            "documentKey": string_field(row, "document_key"),
            "createdAt": int_field(row, "created_at"),
            "updatedAt": int_field(row, "updated_at"),
            "payloadBytes": payload.len(),
            "payloadSchema": schema,
            "sourceSchema": parsed.as_ref()
                .and_then(|value| value.get("sourceSchemaVersion"))
                .and_then(Value::as_str),
        }));
    }
    json!({
        "count": rows.len(),
        "namespaces": namespaces,
        "documentKeys": document_keys,
        "scopes": scopes,
        "payloadSchemas": payload_schemas,
        "createdAtRange": range_i64(rows.iter().map(|row| int_field(row, "created_at"))),
        "updatedAtRange": range_i64(rows.iter().map(|row| int_field(row, "updated_at"))),
        "rows": metadata,
    })
}

fn archive_summary(archives: &[DocumentArchive]) -> Value {
    let mut scopes = BTreeMap::new();
    let mut revisions = BTreeMap::new();
    let mut totals = BTreeMap::<String, usize>::new();
    for archive in archives {
        count(&mut scopes, archive.manifest.scope_key.as_str());
        *revisions
            .entry(archive.manifest.revision.to_string())
            .or_insert(0) += 1;
        for (name, value) in [
            ("mentions", archive.mentions.len()),
            ("entities", archive.entities.len()),
            ("relations", archive.relations.len()),
            ("evidenceSpans", archive.evidence_spans.len()),
            ("relationCandidates", archive.relation_candidates.len()),
            ("graphVertices", archive.graph_batch.vertices.len()),
            ("graphEdges", archive.graph_batch.edges.len()),
            (
                "eventIdentitySubstrates",
                usize::from(archive.event_identity_substrate.is_some()),
            ),
            (
                "temporalSubstrates",
                usize::from(archive.temporal_substrate.is_some()),
            ),
            (
                "causalSubstrates",
                usize::from(archive.causal_substrate.is_some()),
            ),
        ] {
            *totals.entry(name.to_owned()).or_default() += value;
        }
    }
    json!({
        "count": archives.len(),
        "enumerationSemantics": "latest archive per document only",
        "scopes": scopes,
        "revisions": revisions,
        "createdAtRange": range_i64(archives.iter().map(|row| row.manifest.created_at)),
        "totals": totals,
    })
}

fn kernel_summary(snapshot: &KernelGraphSnapshot, generation: u64, journal_len: usize) -> Value {
    let mut vertex_classes = BTreeMap::new();
    let mut vertex_kinds = BTreeMap::new();
    let mut asserted_classes = BTreeMap::new();
    let mut candidate_classes = BTreeMap::new();
    let mut asserted_types = BTreeMap::new();
    let mut candidate_types = BTreeMap::new();
    for vertex in &snapshot.vertices {
        count(&mut vertex_classes, debug_key(&vertex.class));
        count(&mut vertex_kinds, vertex.kind.as_str());
    }
    for edge in &snapshot.asserted_edges {
        count(&mut asserted_classes, debug_key(&edge.relation_class));
        count(&mut asserted_types, edge.edge_type.0.as_str());
    }
    for edge in &snapshot.candidate_edges {
        count(&mut candidate_classes, debug_key(&edge.relation_class));
        count(&mut candidate_types, edge.edge_type.0.as_str());
    }
    json!({
        "generation": generation,
        "journalLength": journal_len,
        "vertices": snapshot.vertices.len(),
        "assertedEdges": snapshot.asserted_edges.len(),
        "candidateEdges": snapshot.candidate_edges.len(),
        "vertexClasses": vertex_classes,
        "vertexKinds": vertex_kinds,
        "assertedRelationClasses": asserted_classes,
        "candidateRelationClasses": candidate_classes,
        "assertedEdgeTypes": asserted_types,
        "candidateEdgeTypes": candidate_types,
        "vertexEvidenceRefs": snapshot.vertices.iter().map(vertex_evidence).sum::<usize>(),
        "assertedEdgeEvidenceRefs": snapshot.asserted_edges.iter().map(edge_evidence).sum::<usize>(),
        "candidateEdgeEvidenceRefs": snapshot.candidate_edges.iter().map(edge_evidence).sum::<usize>(),
        "verticesWithRecordedAt": snapshot.vertices.iter().filter(|row| row.temporal.recorded_at.is_some()).count(),
        "assertedEdgesWithRecordedAt": snapshot.asserted_edges.iter().filter(|row| row.temporal.recorded_at.is_some()).count(),
        "candidateEdgesWithRecordedAt": snapshot.candidate_edges.iter().filter(|row| row.temporal.recorded_at.is_some()).count(),
    })
}

fn graph_truth_summary(
    commits: &[phoenix_graph_kernel::GraphTruthCommit],
    lineage: Result<GraphTruthLineage, phoenix_graph_kernel::GraphTruthLineageError>,
) -> Value {
    let mut operations = BTreeMap::new();
    let mut truth_kinds = BTreeMap::new();
    let mut truth_planes = BTreeMap::new();
    let mut scopes = BTreeMap::new();
    for commit in commits {
        count(&mut operations, debug_key(&commit.header.operation));
        count(&mut truth_kinds, debug_key(&commit.header.truth.kind));
        count(
            &mut truth_planes,
            commit
                .header
                .truth
                .plane
                .as_ref()
                .map(debug_key)
                .unwrap_or_else(|| "None".to_owned()),
        );
        count(&mut scopes, commit.scope().scope_key());
    }
    let lineage_value = match lineage {
        Ok(lineage) => json!({"valid": true, "activeAtoms": lineage.active_atom_count()}),
        Err(error) => json!({"valid": false, "error": error.to_string()}),
    };
    json!({
        "commitCount": commits.len(),
        "operations": operations,
        "truthKinds": truth_kinds,
        "truthPlanes": truth_planes,
        "scopes": scopes,
        "generationRange": range_u64(commits.iter().map(|row| row.header.generation)),
        "committedAtRange": range_i64(commits.iter().map(|row| row.header.committed_at)),
        "sourceGenerationRefs": commits.iter().map(|row| row.header.source_generations.len()).sum::<usize>(),
        "receiptRefs": commits.iter().map(|row| row.header.receipt_ids.len()).sum::<usize>(),
        "predecessorRefs": commits.iter().map(|row| row.header.predecessor_commit_ids.len()).sum::<usize>(),
        "reversalRefs": commits.iter().filter(|row| row.header.reverses_commit_id.is_some()).count(),
        "vertexAtoms": commits.iter().map(|row| row.batch.vertices.len()).sum::<usize>(),
        "edgeAtoms": commits.iter().map(|row| row.batch.edges.len()).sum::<usize>(),
        "lineage": lineage_value,
    })
}

fn proposal_summary(
    receipts: &[phoenix_graph_kernel::GraphProposalBatchReceipt],
    outcomes: &[phoenix_graph_kernel::GraphProposalOutcome],
) -> Value {
    let mut statuses = BTreeMap::new();
    let mut families = BTreeMap::new();
    let mut source_kinds = BTreeMap::new();
    let mut target_kinds = BTreeMap::new();
    let mut outcome_counts = BTreeMap::new();
    for receipt in receipts {
        for proposal in &receipt.proposals {
            count(&mut statuses, debug_key(&proposal.status));
            count(&mut families, proposal.family.as_str());
            count(&mut source_kinds, proposal.source_kind.as_str());
            count(&mut target_kinds, proposal.target_kind.as_str());
        }
    }
    for outcome in outcomes {
        count(&mut outcome_counts, debug_key(&outcome.outcome));
    }
    json!({
        "receiptCount": receipts.len(),
        "proposalCount": receipts.iter().map(|row| row.proposals.len()).sum::<usize>(),
        "multiProposalReceiptCount": receipts.iter().filter(|row| row.proposals.len() > 1).count(),
        "maxProposalsPerReceipt": receipts.iter().map(|row| row.proposals.len()).max().unwrap_or(0),
        "scopes": distinct_count(receipts.iter().map(|row| row.scope_key.as_str())),
        "createdAtRange": range_i64(receipts.iter().map(|row| row.created_at)),
        "generationRange": range_u64(receipts.iter().map(|row| row.generation)),
        "sourceGenerationRefs": receipts.iter().map(|row| row.source_generations.len()).sum::<usize>(),
        "evidenceRefs": receipts.iter().flat_map(|row| &row.proposals).map(|row| row.evidence_refs.len()).sum::<usize>(),
        "shadowScores": receipts.iter().flat_map(|row| &row.proposals).filter(|row| row.shadow_score_millis.is_some()).count(),
        "statuses": statuses,
        "families": families,
        "sourceKinds": source_kinds,
        "targetKinds": target_kinds,
        "outcomes": outcome_counts,
    })
}

fn count(map: &mut BTreeMap<String, usize>, key: impl AsRef<str>) {
    *map.entry(key.as_ref().to_owned()).or_default() += 1;
}

fn distinct_count<'a>(values: impl Iterator<Item = &'a str>) -> usize {
    values.collect::<std::collections::BTreeSet<_>>().len()
}

fn debug_key(value: &impl std::fmt::Debug) -> String {
    format!("{value:?}")
}

fn string_field<'a>(row: &'a Value, key: &str) -> &'a str {
    row.get(key).and_then(Value::as_str).unwrap_or_default()
}

fn int_field(row: &Value, key: &str) -> i64 {
    row.get(key).and_then(Value::as_i64).unwrap_or_default()
}

fn range_i64(values: impl Iterator<Item = i64>) -> Value {
    let values = values.collect::<Vec<_>>();
    json!({"min": values.iter().min(), "max": values.iter().max()})
}

fn range_u64(values: impl Iterator<Item = u64>) -> Value {
    let values = values.collect::<Vec<_>>();
    json!({"min": values.iter().min(), "max": values.iter().max()})
}

fn vertex_evidence(vertex: &KernelVertex) -> usize {
    vertex.provenance.evidence_refs.len()
}

fn edge_evidence(edge: &KernelEdge) -> usize {
    edge.provenance.evidence_refs.len()
}

fn display_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}
