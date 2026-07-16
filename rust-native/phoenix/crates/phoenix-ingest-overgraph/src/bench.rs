use super::*;
use serde::Serialize;

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct IngestBenchmarkCounts {
    pub text_bytes: usize,
    pub sentence_count: usize,
    pub mention_count: usize,
    pub chunk_count: usize,
    pub relation_seed_count: usize,
    pub entity_count: usize,
    pub relation_count: usize,
    pub alias_confirmation_count: usize,
    pub coref_cluster_count: usize,
    pub causal_proposition_count: usize,
    pub causal_link_count: usize,
    pub temporal_proposition_count: usize,
    pub temporal_anchor_count: usize,
    pub event_identity_seed_count: usize,
    pub lexical_span_count: usize,
    pub lexical_alias_entry_count: usize,
    pub segment_count: usize,
    pub segment_bytes: usize,
    pub graph_vertex_count: usize,
    pub graph_edge_count: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct IngestBenchmarkReport {
    pub document_id: String,
    pub document_total_us: u64,
    pub scan_bundle_us: u64,
    pub resolve_us: u64,
    pub post_resolve_total_us: u64,
    pub semantic_substrate_us: u64,
    pub causal_substrate_us: u64,
    pub temporal_substrate_us: u64,
    pub event_identity_substrate_us: u64,
    pub lexical_postings_us: u64,
    pub segment_encode_us: u64,
    pub counts: IngestBenchmarkCounts,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeGraphTruthAuditTimings {
    pub total_body_us: u64,
    pub prepare_ingest_context_us: u64,
    pub document_outcome_us: u64,
    pub scan_bundle_us: u64,
    pub structure_rows_us: u64,
    pub resolve_us: u64,
    pub prepared_document_us: u64,
    pub persist_prepared_documents_us: u64,
    pub graph_truth_commit_prepare_us: u64,
    pub graph_truth_commit_append_us: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeGraphTruthAuditBytes {
    pub prepared_manifest_bytes: usize,
    pub prepared_segment_compressed_bytes: usize,
    pub prepared_segment_uncompressed_bytes: usize,
    pub dirty_scope_record_bytes: usize,
    pub graph_truth_commit_record_bytes: usize,
    pub graph_truth_journal_record_bytes: usize,
    pub graph_truth_batch_record_bytes: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeGraphTruthAuditCounts {
    #[serde(flatten)]
    pub ingest: IngestBenchmarkCounts,
    pub dirty_scope_count: usize,
    pub graph_truth_commit_count: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeGraphTruthAuditReport {
    pub document_id: String,
    pub timings: NativeGraphTruthAuditTimings,
    pub bytes: NativeGraphTruthAuditBytes,
    pub counts: NativeGraphTruthAuditCounts,
    pub prepared_persist: PreparedDocumentPersistTelemetry,
}

#[derive(Default)]
struct GraphTruthCommitAudit {
    commit_count: usize,
    commit_record_bytes: usize,
    journal_record_bytes: usize,
    batch_record_bytes: usize,
    prepare_us: u64,
    append_us: u64,
}

#[derive(Default)]
struct ScanAuditTimings {
    scan_bundle_us: u64,
    structure_rows_us: u64,
}

impl PhoenixInvarantV3 {
    pub fn benchmark_document_pipeline(
        &self,
        document: &IngestDocument,
        session_id: Option<&SessionId>,
        created_at: i64,
    ) -> Result<IngestBenchmarkReport, StoreError> {
        let assignment = benchmark_assignment(document);
        let entity_memory = NativeEntityMemory::default();

        let document_started = Instant::now();

        let started = Instant::now();
        let scan_bundle = self.scan_document_bundle(document)?;
        let scan_bundle_us = elapsed_us(started);

        let started = Instant::now();
        let resolution_bundle =
            self.resolve_document_bundle(document, &scan_bundle, &entity_memory, created_at)?;
        let resolve_us = elapsed_us(started);

        let post_resolve_started = Instant::now();
        let mention_count = scan_bundle.scan.mentions.len();
        let _ = self.build_document_state(
            document,
            session_id,
            &assignment,
            created_at,
            &scan_bundle.boundaries,
            scan_bundle.chunks.len(),
            &resolution_bundle.entities,
            &resolution_bundle.kernel_batch,
            resolution_bundle.discovery_count,
            mention_count,
        );

        let started = Instant::now();
        let semantic_substrate =
            build_document_semantic_substrate(document, &scan_bundle, created_at);
        let semantic_substrate_us = elapsed_us(started);

        let started = Instant::now();
        let causal_substrate = build_document_causal_substrate(document, &semantic_substrate);
        let causal_substrate_us = elapsed_us(started);

        let started = Instant::now();
        let temporal_substrate =
            build_document_temporal_substrate(document, &semantic_substrate, created_at);
        let temporal_substrate_us = elapsed_us(started);

        let started = Instant::now();
        let event_identity_substrate = build_document_event_identity_substrate(
            document,
            assignment.revision,
            &causal_substrate,
            &temporal_substrate,
        );
        let event_identity_substrate_us = elapsed_us(started);

        let lexical_span_count = scan_bundle.indexed_spans.len();
        let started = Instant::now();
        let lexical = build_lexical_postings_segment(
            scan_bundle.indexed_spans,
            &resolution_bundle.entities,
            &document.document_id.0,
        );
        let lexical_postings_us = elapsed_us(started);

        let started = Instant::now();
        let mut segments = Vec::<PreparedDocumentSegment>::new();
        let mut segment_refs = Vec::<DocumentSegmentRef>::new();
        self.push_segment(
            &mut segments,
            &mut segment_refs,
            DocumentSegmentKind::AliasConfirmationTable,
            resolution_bundle.alias_confirmations.len(),
            &resolution_bundle.alias_confirmations,
        )?;
        if !resolution_bundle.coref_clusters.is_empty() {
            self.push_segment(
                &mut segments,
                &mut segment_refs,
                DocumentSegmentKind::CorefClusterTable,
                resolution_bundle.coref_clusters.len(),
                &resolution_bundle.coref_clusters,
            )?;
        }
        self.push_segment(
            &mut segments,
            &mut segment_refs,
            DocumentSegmentKind::ChunkTable,
            scan_bundle.chunks.len(),
            &scan_bundle.chunks,
        )?;
        self.push_segment(
            &mut segments,
            &mut segment_refs,
            DocumentSegmentKind::EntityTable,
            resolution_bundle.entities.len(),
            &resolution_bundle.entities,
        )?;
        self.push_segment(
            &mut segments,
            &mut segment_refs,
            DocumentSegmentKind::RelationTable,
            resolution_bundle.relations.len(),
            &resolution_bundle.relations,
        )?;
        self.push_segment(
            &mut segments,
            &mut segment_refs,
            DocumentSegmentKind::CausalSubstrateTable,
            causal_substrate.propositions.len()
                + causal_substrate.semantic_events.len()
                + causal_substrate.semantic_states.len()
                + causal_substrate.semantic_claims.len()
                + causal_substrate.semantic_relations.len()
                + causal_substrate.temporal_bindings.len()
                + causal_substrate.causal_candidates.len()
                + causal_substrate.causal_links.len()
                + causal_substrate.causal_diagnostics.len(),
            &causal_substrate,
        )?;
        self.push_segment(
            &mut segments,
            &mut segment_refs,
            DocumentSegmentKind::TemporalSubstrateTable,
            temporal_substrate.propositions.len()
                + temporal_substrate.semantic_events.len()
                + temporal_substrate.semantic_states.len()
                + temporal_substrate.semantic_claims.len()
                + temporal_substrate.surface_temporal_cues.len()
                + temporal_substrate.timex_records.len()
                + temporal_substrate.anchor_candidates.len()
                + temporal_substrate.axis_records.len()
                + temporal_substrate.reference_timex_edges.len()
                + temporal_substrate.reference_event_edges.len()
                + temporal_substrate.temporal_claims.len()
                + temporal_substrate.temporal_constraints.len()
                + temporal_substrate.temporal_diagnostics.len(),
            &temporal_substrate,
        )?;
        self.push_segment(
            &mut segments,
            &mut segment_refs,
            DocumentSegmentKind::EventIdentitySubstrateTable,
            event_identity_substrate.mention_seeds.len()
                + event_identity_substrate.diagnostics.len(),
            &event_identity_substrate,
        )?;
        self.push_segment(
            &mut segments,
            &mut segment_refs,
            DocumentSegmentKind::LexicalPostings,
            lexical.spans.len() + lexical.alias_entries.len(),
            &lexical,
        )?;
        let segment_encode_us = elapsed_us(started);
        let segment_bytes = segments.iter().map(|segment| segment.payload.len()).sum();

        Ok(IngestBenchmarkReport {
            document_id: document.document_id.0.clone(),
            document_total_us: elapsed_us(document_started),
            scan_bundle_us,
            resolve_us,
            post_resolve_total_us: elapsed_us(post_resolve_started),
            semantic_substrate_us,
            causal_substrate_us,
            temporal_substrate_us,
            event_identity_substrate_us,
            lexical_postings_us,
            segment_encode_us,
            counts: IngestBenchmarkCounts {
                text_bytes: document.text.len(),
                sentence_count: scan_bundle.scan.sentences.len(),
                mention_count,
                chunk_count: scan_bundle.chunks.len(),
                relation_seed_count: scan_bundle.structure.relation_seeds.len(),
                entity_count: resolution_bundle.entities.len(),
                relation_count: resolution_bundle.relations.len(),
                alias_confirmation_count: resolution_bundle.alias_confirmations.len(),
                coref_cluster_count: resolution_bundle.coref_clusters.len(),
                causal_proposition_count: causal_substrate.propositions.len(),
                causal_link_count: causal_substrate.causal_links.len(),
                temporal_proposition_count: temporal_substrate.propositions.len(),
                temporal_anchor_count: temporal_substrate.anchor_candidates.len(),
                event_identity_seed_count: event_identity_substrate.mention_seeds.len(),
                lexical_span_count,
                lexical_alias_entry_count: lexical.alias_entries.len(),
                segment_count: segments.len(),
                segment_bytes,
                graph_vertex_count: resolution_bundle.kernel_batch.vertices.len(),
                graph_edge_count: resolution_bundle.kernel_batch.edges.len(),
            },
        })
    }

    pub fn audit_native_graph_truth_slice<S>(
        &self,
        store: &S,
        document: &IngestDocument,
        session_id: Option<&SessionId>,
        revision: u64,
        created_at: i64,
    ) -> Result<NativeGraphTruthAuditReport, StoreError>
    where
        S: PhoenixArchiveStoreV2 + PhoenixGraphKernelStoreV2 + ?Sized,
    {
        let total_started = Instant::now();
        let started = Instant::now();
        let context =
            store.prepare_ingest_context(session_id, std::slice::from_ref(document), revision)?;
        let prepare_ingest_context_us = elapsed_us(started);
        let assignment = context
            .assignments
            .first()
            .ok_or_else(|| StoreError::Query("missing ingest assignment".to_owned()))?;
        let entity_memory = build_native_entity_memory(context.kernel_snapshot.as_ref());

        let document_started = Instant::now();
        let (scan_bundle, scan_timings) = self.scan_document_bundle_for_audit(document)?;
        let started = Instant::now();
        let resolution_bundle =
            self.resolve_document_bundle(document, &scan_bundle, &entity_memory, created_at)?;
        let resolve_us = elapsed_us(started);

        let counts = ingest_counts_for_audit(document, &scan_bundle, &resolution_bundle);
        let started = Instant::now();
        let draft = self.build_prepared_document(
            document,
            session_id,
            assignment,
            created_at,
            scan_bundle,
            resolution_bundle,
        )?;
        let prepared_document_us = elapsed_us(started);
        let document_outcome_us = elapsed_us(document_started);

        let prepared = draft.prepared;
        let outcome = IngestedDocumentOutcome {
            assignment: prepared.assignment.clone(),
            document_summary: draft.document_summary,
            session_document: draft.session_document,
            span_count: draft.span_count,
            discovery_count: draft.discovery_count,
            diagnostics: draft.diagnostics,
            candidate_kernel_batch: draft.candidate_kernel_batch,
        };
        let dirty_scopes =
            self.build_dirty_scope_records(std::slice::from_ref(&outcome), created_at);
        let mut bytes = prepared_document_bytes_for_audit(&prepared)?;
        bytes.dirty_scope_record_bytes = dirty_scopes
            .iter()
            .map(|value| encoded_len(value, "dirty scope record"))
            .collect::<Result<Vec<_>, _>>()?
            .into_iter()
            .sum();

        let prepared_persist = store.persist_prepared_documents_with_telemetry(
            std::slice::from_ref(&prepared),
            None,
            &dirty_scopes,
            created_at,
        )?;
        let persist_prepared_documents_us = prepared_persist.total_us;

        let commit_audit =
            persist_prepared_graph_truth_commits_for_audit(store, &[prepared], created_at)?;
        bytes.graph_truth_commit_record_bytes = commit_audit.commit_record_bytes;
        bytes.graph_truth_journal_record_bytes = commit_audit.journal_record_bytes;
        bytes.graph_truth_batch_record_bytes = commit_audit.batch_record_bytes;

        Ok(NativeGraphTruthAuditReport {
            document_id: document.document_id.0.clone(),
            timings: NativeGraphTruthAuditTimings {
                total_body_us: elapsed_us(total_started),
                prepare_ingest_context_us,
                document_outcome_us,
                scan_bundle_us: scan_timings.scan_bundle_us,
                structure_rows_us: scan_timings.structure_rows_us,
                resolve_us,
                prepared_document_us,
                persist_prepared_documents_us,
                graph_truth_commit_prepare_us: commit_audit.prepare_us,
                graph_truth_commit_append_us: commit_audit.append_us,
            },
            bytes,
            counts: NativeGraphTruthAuditCounts {
                ingest: counts,
                dirty_scope_count: dirty_scopes.len(),
                graph_truth_commit_count: commit_audit.commit_count,
            },
            prepared_persist,
        })
    }

    fn scan_document_bundle_for_audit(
        &self,
        document: &IngestDocument,
    ) -> Result<(NativeScanBundle, ScanAuditTimings), StoreError> {
        let bundle_started = Instant::now();
        let scan = scan_native_compact(
            &document.text,
            &document.scope,
            &[],
            &self.config.extraction,
        );
        let boundaries = extract_boundaries(&document.text);
        let chunk_ranges = build_chunks(
            &document.text,
            &ChunkerConfig {
                chunk_size: self.config.chunk_size,
                overlap: self.config.overlap,
            },
        );
        let (chunks, indexed_spans) = build_chunk_records(document, &boundaries, &chunk_ranges);
        let started = Instant::now();
        let structure = build_native_structure_rows(&document.text, &scan, &chunks);
        let structure_rows_us = elapsed_us(started);
        let coref = build_coref_rows(&scan, &structure, &self.config.coref);
        Ok((
            NativeScanBundle {
                scan,
                boundaries,
                chunks,
                indexed_spans,
                structure,
                coref,
            },
            ScanAuditTimings {
                scan_bundle_us: elapsed_us(bundle_started),
                structure_rows_us,
            },
        ))
    }

    pub fn build_archive_for_benchmark(
        &self,
        document: &IngestDocument,
        session_id: Option<&SessionId>,
        created_at: i64,
    ) -> Result<DocumentArchive, StoreError> {
        let assignment = benchmark_assignment(document);
        let entity_memory = NativeEntityMemory::default();
        let outcome = self.build_document_outcome(
            document,
            session_id,
            &assignment,
            &entity_memory,
            created_at,
        )?;
        Ok(outcome.archive)
    }
}

fn benchmark_assignment(document: &IngestDocument) -> DocumentOrdinalAssignment {
    DocumentOrdinalAssignment {
        document_id: document.document_id.0.clone(),
        scope: document.scope.clone(),
        scope_key: scope_storage_key(&document.scope),
        scope_ord: ScopeOrd(0),
        document_ord: DocumentOrd(0),
        revision: 1,
    }
}

fn ingest_counts_for_audit(
    document: &IngestDocument,
    scan_bundle: &NativeScanBundle,
    resolution_bundle: &NativeResolutionBundle,
) -> IngestBenchmarkCounts {
    IngestBenchmarkCounts {
        text_bytes: document.text.len(),
        sentence_count: scan_bundle.scan.sentences.len(),
        mention_count: scan_bundle.scan.mentions.len(),
        chunk_count: scan_bundle.chunks.len(),
        relation_seed_count: scan_bundle.structure.relation_seeds.len(),
        entity_count: resolution_bundle.entities.len(),
        relation_count: resolution_bundle.relations.len(),
        alias_confirmation_count: resolution_bundle.alias_confirmations.len(),
        coref_cluster_count: resolution_bundle.coref_clusters.len(),
        lexical_span_count: scan_bundle.indexed_spans.len(),
        segment_count: 0,
        graph_vertex_count: resolution_bundle.kernel_batch.vertices.len(),
        graph_edge_count: resolution_bundle.kernel_batch.edges.len(),
        ..IngestBenchmarkCounts::default()
    }
}

fn prepared_document_bytes_for_audit(
    document: &PreparedDocument,
) -> Result<NativeGraphTruthAuditBytes, StoreError> {
    let prepared_manifest_bytes = encoded_len(&document.manifest, "prepared manifest")?;
    let prepared_segment_compressed_bytes = document
        .segments
        .iter()
        .map(|segment| segment.payload.len())
        .sum();
    let prepared_segment_uncompressed_bytes = document
        .segments
        .iter()
        .map(|segment| segment.header.uncompressed_len as usize)
        .sum();
    Ok(NativeGraphTruthAuditBytes {
        prepared_manifest_bytes,
        prepared_segment_compressed_bytes,
        prepared_segment_uncompressed_bytes,
        ..NativeGraphTruthAuditBytes::default()
    })
}

fn persist_prepared_graph_truth_commits_for_audit<S>(
    store: &S,
    prepared: &[PreparedDocument],
    committed_at: i64,
) -> Result<GraphTruthCommitAudit, StoreError>
where
    S: PhoenixGraphKernelStoreV2 + ?Sized,
{
    let mut audit = GraphTruthCommitAudit::default();
    let mut next_generation = store.kernel_current_generation()?;
    for document in prepared {
        for lane in NativeTruthLane::ALL {
            let prepare_started = Instant::now();
            let batch = graph_truth_batch_for_document(document, lane);
            if batch.vertices.is_empty() && batch.edges.is_empty() {
                audit.prepare_us += elapsed_us(prepare_started);
                continue;
            }
            let digest = graph_truth_idempotency_hash(document, lane, &batch)?;
            let commit_id = graph_truth_commit_id(lane, digest);
            if let Some(existing) = store.load_graph_truth_commit(&commit_id)? {
                next_generation = next_generation.max(existing.header.generation);
                audit.prepare_us += elapsed_us(prepare_started);
                let append_started = Instant::now();
                store.append_graph_truth_commit(&existing)?;
                audit.append_us += elapsed_us(append_started);
                continue;
            }
            next_generation = next_generation
                .checked_add(1)
                .ok_or_else(|| StoreError::Query("graph truth generation overflow".to_owned()))?;
            let commit = build_graph_truth_commit(
                document,
                lane,
                batch,
                commit_id,
                digest,
                next_generation,
                committed_at,
            )?;
            audit.commit_record_bytes += encoded_len(&commit, "graph truth commit")?;
            audit.batch_record_bytes += encoded_len(&commit.batch, "graph truth batch")?;
            audit.journal_record_bytes += encoded_len(
                &KernelJournalEntry {
                    generation: commit.header.generation,
                    source_revision: commit.header.source_generations[0].source_id.to_string(),
                    batch: None,
                    commit_id: Some(commit.commit_id().to_owned()),
                    created_at: commit.header.committed_at,
                },
                "graph truth journal reference",
            )?;
            audit.prepare_us += elapsed_us(prepare_started);
            let append_started = Instant::now();
            store.append_graph_truth_commit(&commit)?;
            audit.append_us += elapsed_us(append_started);
            audit.commit_count += 1;
        }
    }
    Ok(audit)
}

fn encoded_len<T: Serialize>(value: &T, label: &str) -> Result<usize, StoreError> {
    rmp_serde::to_vec_named(value)
        .map(|bytes| bytes.len())
        .map_err(|error| StoreError::Snapshot(format!("{label} encode: {error}")))
}

fn elapsed_us(started: Instant) -> u64 {
    started.elapsed().as_micros() as u64
}
