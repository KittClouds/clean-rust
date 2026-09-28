use super::*;

struct SourceCatalog {
    node_ids: Vec<String>,
    node_hashes: Vec<LeU64>,
    node_collisions: Vec<LeU16>,
    node_kinds: Vec<LeU16>,
    node_evidence_offsets: Vec<LeU64>,
    node_evidence_indices: Vec<LeU32>,
    evidence: Vec<String>,
    evidence_hashes: Vec<LeU64>,
    evidence_collisions: Vec<LeU16>,
    edge_hashes: Vec<LeU64>,
    edge_collisions: Vec<LeU16>,
    edge_sources: Vec<LeU32>,
    edge_targets: Vec<LeU32>,
    edge_relations: Vec<LeU16>,
    edge_families: Vec<LeU16>,
    edge_confidences: Vec<LeF32>,
    edge_temporal_indices: Vec<LeU32>,
    edge_temporal_flags: Vec<u8>,
    edge_valid_from: Vec<LeI64>,
    edge_valid_to: Vec<LeI64>,
    edge_recorded_at: Vec<LeI64>,
    edge_expired_at: Vec<LeI64>,
    edge_evidence_offsets: Vec<LeU64>,
    edge_evidence_indices: Vec<LeU32>,
    relations: Vec<DiscoveryRelationEntry>,
    node_count: usize,
    edge_count: usize,
}

pub(super) fn write_source_sections(
    source: &impl PagedAssertedDiscoverySource,
    _policy: &DiscoveryRelationPolicy,
    writer: &mut BinaryWriter,
) -> Result<PreparedMetadata, DiscoveryViewError> {
    let mut catalog = SourceCatalog::read(source)?;
    let node_evidence_links = catalog.node_evidence_indices.len();
    let edge_evidence_links = catalog.edge_evidence_indices.len();
    let temporal_edge_count = catalog.edge_temporal_flags.len();

    writer.section(SectionKind::NodeStableHash, &catalog.node_hashes)?;
    writer.section(SectionKind::NodeCollision, &catalog.node_collisions)?;
    writer.section(SectionKind::NodeKind, &catalog.node_kinds)?;
    writer.section(
        SectionKind::NodeEvidenceOffsets,
        &catalog.node_evidence_offsets,
    )?;
    writer.section(
        SectionKind::NodeEvidenceIndices,
        &catalog.node_evidence_indices,
    )?;
    writer.section(SectionKind::EdgeStableHash, &catalog.edge_hashes)?;
    writer.section(SectionKind::EdgeCollision, &catalog.edge_collisions)?;
    writer.section(SectionKind::EdgeSource, &catalog.edge_sources)?;
    writer.section(SectionKind::EdgeTarget, &catalog.edge_targets)?;
    writer.section(SectionKind::EdgeRelation, &catalog.edge_relations)?;
    writer.section(SectionKind::EdgeFamily, &catalog.edge_families)?;
    writer.section(SectionKind::EdgeConfidence, &catalog.edge_confidences)?;
    writer.section(
        SectionKind::EdgeTemporalIndex,
        &catalog.edge_temporal_indices,
    )?;
    writer.section(SectionKind::EdgeTemporalFlags, &catalog.edge_temporal_flags)?;
    writer.section(SectionKind::EdgeValidFrom, &catalog.edge_valid_from)?;
    writer.section(SectionKind::EdgeValidTo, &catalog.edge_valid_to)?;
    writer.section(SectionKind::EdgeRecordedAt, &catalog.edge_recorded_at)?;
    writer.section(SectionKind::EdgeExpiredAt, &catalog.edge_expired_at)?;
    writer.section(
        SectionKind::EdgeEvidenceOffsets,
        &catalog.edge_evidence_offsets,
    )?;
    writer.section(
        SectionKind::EdgeEvidenceIndices,
        &catalog.edge_evidence_indices,
    )?;
    writer.section(SectionKind::EvidenceStableHash, &catalog.evidence_hashes)?;
    writer.section(SectionKind::EvidenceCollision, &catalog.evidence_collisions)?;

    let (outgoing_offsets, outgoing_edges) = adjacency(
        catalog.node_count,
        catalog.edge_sources.iter().map(|value| value.get()),
    )?;
    writer.section(SectionKind::OutgoingOffsets, &outgoing_offsets)?;
    writer.section(SectionKind::OutgoingEdges, &outgoing_edges)?;
    drop((outgoing_offsets, outgoing_edges));
    catalog.edge_sources.clear();
    catalog.edge_sources.shrink_to_fit();

    let (incoming_offsets, incoming_edges) = adjacency(
        catalog.node_count,
        catalog.edge_targets.iter().map(|value| value.get()),
    )?;
    writer.section(SectionKind::IncomingOffsets, &incoming_offsets)?;
    writer.section(SectionKind::IncomingEdges, &incoming_edges)?;
    drop((incoming_offsets, incoming_edges));

    let (identity_refs, identity_slab) =
        identity_slab_from_strings(&catalog.node_ids, &catalog.evidence)?;
    writer.section(SectionKind::IdentityRefs, &identity_refs)?;
    writer.bytes(SectionKind::IdentitySlab, &identity_slab)?;

    Ok(PreparedMetadata {
        node_count: catalog.node_count,
        edge_count: catalog.edge_count,
        temporal_edge_count,
        evidence_count: catalog.evidence.len(),
        node_evidence_links,
        edge_evidence_links,
        relations: catalog.relations,
    })
}

impl SourceCatalog {
    fn read(source: &impl PagedAssertedDiscoverySource) -> Result<Self, DiscoveryViewError> {
        let generation = source.generation()?;
        let node_count = source.node_count()?;
        let edge_count = source.asserted_edge_count()?;
        require_u32_capacity(node_count, "source vertex")?;
        require_u32_capacity(edge_count, "source edge")?;

        let mut node_ids = Vec::with_capacity(node_count);
        let mut node_dense = HashMap::with_capacity(node_count);
        let mut node_kinds = Vec::with_capacity(node_count);
        let mut node_evidence_offsets = vec![LeU64::new(0)];
        let mut node_evidence_identities = Vec::new();
        let mut evidence = Vec::new();
        let mut last_node = None::<String>;
        source.visit_nodes(DISCOVERY_SOURCE_PAGE_SIZE, &mut |storage_id, vertex| {
            if vertex.id.0.is_empty() {
                return Err(DiscoveryViewError::Invalid(
                    "asserted source vertex identity is empty".to_owned(),
                ));
            }
            if last_node
                .as_deref()
                .is_some_and(|last| last >= vertex.id.0.as_str())
            {
                return Err(DiscoveryViewError::Invalid(format!(
                    "asserted source vertices are not strictly canonical at {}",
                    vertex.id.0
                )));
            }
            let dense = u32::try_from(node_ids.len()).map_err(|_| {
                DiscoveryViewError::Invalid("source vertex count exceeds u32 capacity".to_owned())
            })?;
            if node_dense.insert(storage_id, dense).is_some() {
                return Err(DiscoveryViewError::Invalid(format!(
                    "duplicate asserted source storage vertex {storage_id}"
                )));
            }
            node_kinds.push(LeU16::new(vertex_kind_code(&vertex.class)));
            append_source_evidence_identities(
                &vertex.provenance.evidence_refs,
                &mut evidence,
                &mut node_evidence_identities,
            );
            node_evidence_offsets.push(LeU64::new(node_evidence_identities.len() as u64));
            last_node = Some(vertex.id.0.clone());
            node_ids.push(vertex.id.0.clone());
            Ok(())
        })?;
        require_exact_count(node_ids.len(), node_count, "source vertex")?;
        let node_identity_refs = node_ids.iter().map(String::as_str).collect::<Vec<_>>();
        let (node_hashes, node_collisions) =
            stable_string_identities(b"phoenix-discovery-node/v1\0", &node_identity_refs)?;
        drop(node_identity_refs);

        let mut relation_dense = HashMap::<String, u16>::new();
        let mut relation_values = Vec::<(String, DiscoveryRelationFamily)>::new();
        let mut edge_relation_tokens = Vec::with_capacity(edge_count);
        let mut edge_identities = Vec::with_capacity(edge_count);
        let mut edge_sources = Vec::with_capacity(edge_count);
        let mut edge_targets = Vec::with_capacity(edge_count);
        let mut edge_families = Vec::with_capacity(edge_count);
        let mut edge_confidences = Vec::with_capacity(edge_count);
        let mut edge_temporal_indices = Vec::with_capacity(edge_count);
        let mut edge_temporal_flags = Vec::new();
        let mut edge_valid_from = Vec::new();
        let mut edge_valid_to = Vec::new();
        let mut edge_recorded_at = Vec::new();
        let mut edge_expired_at = Vec::new();
        let mut edge_evidence_offsets = vec![LeU64::new(0)];
        let mut edge_evidence_identities = Vec::new();
        let mut last_edge = None::<(String, String, String)>;
        let mut observed_edges = 0_usize;
        source.visit_asserted_edges(
            DISCOVERY_SOURCE_PAGE_SIZE,
            &mut |source_storage, target_storage, edge| {
                validate_asserted_edge(edge)?;
                let source_dense = source_dense_endpoint(
                    &node_dense,
                    &node_ids,
                    source_storage,
                    &edge.source_id.0,
                    "source",
                )?;
                let target_dense = source_dense_endpoint(
                    &node_dense,
                    &node_ids,
                    target_storage,
                    &edge.target_id.0,
                    "target",
                )?;
                let key = (
                    edge.source_id.0.clone(),
                    edge.target_id.0.clone(),
                    edge.edge_type.0.clone(),
                );
                if last_edge.as_ref().is_some_and(|last| last >= &key) {
                    return Err(DiscoveryViewError::Invalid(format!(
                        "asserted source edges are not strictly canonical at {} -> {} ({})",
                        edge.source_id.0, edge.target_id.0, edge.edge_type.0
                    )));
                }
                let family = DiscoveryRelationFamily::from_kernel(&edge.relation_class)
                    .expect("asserted edge validation rejected candidates");
                let relation_token = if let Some(&token) = relation_dense.get(&edge.edge_type.0) {
                    if relation_values[token as usize].1 != family {
                        return Err(DiscoveryViewError::Invalid(format!(
                            "relation {} has conflicting families",
                            edge.edge_type.0
                        )));
                    }
                    token
                } else {
                    let token = u16::try_from(relation_values.len()).map_err(|_| {
                        DiscoveryViewError::Invalid(
                            "relation dictionary exceeds u16 capacity".to_owned(),
                        )
                    })?;
                    relation_dense.insert(edge.edge_type.0.clone(), token);
                    relation_values.push((edge.edge_type.0.clone(), family));
                    token
                };
                edge_relation_tokens.push(relation_token);
                edge_identities.push(stable_identity(
                    b"phoenix-discovery-edge/v1\0",
                    &[
                        edge.source_id.0.as_bytes(),
                        edge.target_id.0.as_bytes(),
                        edge.edge_type.0.as_bytes(),
                    ],
                ));
                edge_sources.push(LeU32::new(source_dense));
                edge_targets.push(LeU32::new(target_dense));
                edge_families.push(LeU16::new(family.code()));
                edge_confidences.push(LeF32::new(edge_confidence(edge)?));
                if let Some((flags, valid_from, valid_to, recorded_at, expired_at)) =
                    temporal(edge.temporal.clone())
                {
                    edge_temporal_indices.push(LeU32::new(
                        u32::try_from(edge_temporal_flags.len()).map_err(|_| {
                            DiscoveryViewError::Invalid(
                                "temporal edge count exceeds u32 capacity".to_owned(),
                            )
                        })?,
                    ));
                    edge_temporal_flags.push(flags);
                    edge_valid_from.push(LeI64::new(valid_from));
                    edge_valid_to.push(LeI64::new(valid_to));
                    edge_recorded_at.push(LeI64::new(recorded_at));
                    edge_expired_at.push(LeI64::new(expired_at));
                } else {
                    edge_temporal_indices.push(LeU32::new(u32::MAX));
                }
                append_source_evidence_identities(
                    &edge.provenance.evidence_refs,
                    &mut evidence,
                    &mut edge_evidence_identities,
                );
                edge_evidence_offsets.push(LeU64::new(edge_evidence_identities.len() as u64));
                last_edge = Some(key);
                observed_edges += 1;
                Ok(())
            },
        )?;
        require_exact_count(observed_edges, edge_count, "source asserted edge")?;
        if source.generation()? != generation {
            return Err(DiscoveryViewError::Invalid(
                "asserted source generation changed during cataloging".to_owned(),
            ));
        }

        evidence.par_sort_unstable();
        evidence.dedup();
        require_u32_capacity(evidence.len(), "source evidence identity")?;
        let evidence_refs = evidence.iter().map(String::as_str).collect::<Vec<_>>();
        let (evidence_hashes, evidence_collisions) =
            stable_string_identities(b"phoenix-discovery-evidence/v1\0", &evidence_refs)?;
        let mut evidence_dense = HashMap::with_capacity(evidence.len());
        for (index, (hash, collision)) in
            evidence_hashes.iter().zip(&evidence_collisions).enumerate()
        {
            evidence_dense.insert((hash.get(), collision.get()), index as u32);
        }
        let node_evidence_indices =
            resolve_source_evidence(&node_evidence_identities, &evidence_dense)?;
        let edge_evidence_indices =
            resolve_source_evidence(&edge_evidence_identities, &evidence_dense)?;
        drop((
            node_evidence_identities,
            edge_evidence_identities,
            evidence_dense,
        ));

        let mut relation_order = (0..relation_values.len()).collect::<Vec<_>>();
        relation_order.sort_unstable_by(|&left, &right| {
            relation_values[left].0.cmp(&relation_values[right].0)
        });
        let mut relation_remap = vec![0_u16; relation_values.len()];
        let mut relations = Vec::with_capacity(relation_values.len());
        for (code, token) in relation_order.into_iter().enumerate() {
            let code = u16::try_from(code).map_err(|_| {
                DiscoveryViewError::Invalid("relation dictionary exceeds u16 capacity".to_owned())
            })?;
            relation_remap[token] = code;
            let (relation, family) = relation_values[token].clone();
            relations.push(DiscoveryRelationEntry {
                code,
                relation,
                family,
            });
        }
        let edge_relations = edge_relation_tokens
            .into_iter()
            .map(|token| LeU16::new(relation_remap[token as usize]))
            .collect::<Vec<_>>();

        reject_stable_collisions(&edge_identities)?;
        let edge_hashes = edge_identities
            .iter()
            .map(|(hash, _)| LeU64::new(*hash))
            .collect::<Vec<_>>();
        let edge_collisions = edge_identities
            .iter()
            .map(|(_, collision)| LeU16::new(*collision))
            .collect::<Vec<_>>();

        Ok(Self {
            node_ids,
            node_hashes,
            node_collisions,
            node_kinds,
            node_evidence_offsets,
            node_evidence_indices,
            evidence,
            evidence_hashes,
            evidence_collisions,
            edge_hashes,
            edge_collisions,
            edge_sources,
            edge_targets,
            edge_relations,
            edge_families,
            edge_confidences,
            edge_temporal_indices,
            edge_temporal_flags,
            edge_valid_from,
            edge_valid_to,
            edge_recorded_at,
            edge_expired_at,
            edge_evidence_offsets,
            edge_evidence_indices,
            relations,
            node_count,
            edge_count,
        })
    }
}

fn source_dense_endpoint(
    node_dense: &HashMap<u64, u32>,
    node_ids: &[String],
    storage_id: u64,
    external_id: &str,
    label: &str,
) -> Result<u32, DiscoveryViewError> {
    let dense = *node_dense.get(&storage_id).ok_or_else(|| {
        DiscoveryViewError::Invalid(format!("source edge {label} storage id is missing"))
    })?;
    if node_ids[dense as usize] != external_id {
        return Err(DiscoveryViewError::Invalid(format!(
            "source edge {label} identity does not match storage topology"
        )));
    }
    Ok(dense)
}

fn append_source_evidence_identities(
    evidence_refs: &[String],
    evidence: &mut Vec<String>,
    identities: &mut Vec<(u64, u16)>,
) {
    let mut values = evidence_refs
        .iter()
        .filter_map(|value| (!value.is_empty()).then_some(value.as_str()))
        .collect::<SmallVec<[&str; 4]>>();
    values.sort_unstable();
    values.dedup();
    for value in values {
        evidence.push(value.to_owned());
        identities.push(stable_identity(
            b"phoenix-discovery-evidence/v1\0",
            &[value.as_bytes()],
        ));
    }
}

fn resolve_source_evidence(
    identities: &[(u64, u16)],
    evidence_dense: &HashMap<(u64, u16), u32>,
) -> Result<Vec<LeU32>, DiscoveryViewError> {
    identities
        .iter()
        .map(|identity| {
            evidence_dense
                .get(identity)
                .copied()
                .map(LeU32::new)
                .ok_or_else(|| {
                    DiscoveryViewError::Invalid(
                        "source evidence identity disappeared during packing".to_owned(),
                    )
                })
        })
        .collect()
}

fn require_exact_count(
    actual: usize,
    expected: usize,
    label: &str,
) -> Result<(), DiscoveryViewError> {
    if actual != expected {
        return Err(DiscoveryViewError::Invalid(format!(
            "{label} count changed during packed build: {actual} != {expected}"
        )));
    }
    Ok(())
}

fn identity_slab_from_strings(
    node_ids: &[String],
    evidence: &[String],
) -> Result<(Vec<IdentityRefRecord>, Vec<u8>), DiscoveryViewError> {
    let capacity = node_ids
        .iter()
        .map(String::len)
        .chain(evidence.iter().map(String::len))
        .sum();
    let mut slab = Vec::with_capacity(capacity);
    let mut refs = Vec::with_capacity(node_ids.len() + evidence.len());
    for value in node_ids.iter().chain(evidence) {
        push_identity(&mut refs, &mut slab, value)?;
    }
    Ok((refs, slab))
}
