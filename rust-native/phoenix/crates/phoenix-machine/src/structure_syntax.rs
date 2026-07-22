use phoenix_types::{
    ChunkKind, ChunkSpan, DependencyLabel, Diagnostic, EvidenceSpan, FrameSlot, FrameSlotSource,
    MentionEntityRef, MentionSpan, NarrativeVerbHit, RelationCandidate, ResolverLink, ScanArtifact,
    SentenceFrame, SentenceSyntax, StructureArtifact, TextRange, TokenSpan, VerbFrame,
};

pub(crate) fn build_structure_artifact(text: &str, scan: &ScanArtifact) -> StructureArtifact {
    let sentence_mention_ranges =
        super::sentence_item_ranges(scan.sentences.len(), &scan.mentions, |mention| {
            mention.sentence_index
        });
    let sentence_chunk_ranges =
        super::sentence_item_ranges(scan.sentences.len(), &scan.chunks, |chunk| {
            chunk.sentence_index
        });
    let sentence_hit_ranges =
        super::sentence_item_ranges(scan.sentences.len(), &scan.narrative_hits, |hit| {
            hit.sentence_index
        });
    let sentence_link_ranges =
        super::sentence_item_ranges(scan.sentences.len(), &scan.resolver_links, |link| {
            link.sentence_index
        });
    let sentence_syntax_ranges =
        super::sentence_item_ranges(scan.sentences.len(), &scan.sentence_syntax, |syntax| {
            syntax.sentence_index
        });

    let mut sentence_frames = Vec::with_capacity(scan.sentences.len());
    let mut relations = Vec::new();
    let mut evidence_spans = Vec::new();

    for sentence in &scan.sentences {
        let index = sentence.index;
        let mention_slice =
            &scan.mentions[sentence_mention_ranges.get(index).cloned().unwrap_or(0..0)];
        let chunk_slice = &scan.chunks[sentence_chunk_ranges.get(index).cloned().unwrap_or(0..0)];
        let hit_slice =
            &scan.narrative_hits[sentence_hit_ranges.get(index).cloned().unwrap_or(0..0)];
        let link_slice =
            &scan.resolver_links[sentence_link_ranges.get(index).cloned().unwrap_or(0..0)];
        let syntax = scan.sentence_syntax
            [sentence_syntax_ranges.get(index).cloned().unwrap_or(0..0)]
        .first();

        let mut diagnostics = syntax
            .map(|value| value.diagnostics.clone())
            .unwrap_or_default();
        let mut verb_frames = Vec::with_capacity(hit_slice.len());

        for hit in hit_slice {
            let bundle = build_relation_bundle(
                text,
                &scan.tokens,
                sentence.range,
                mention_slice,
                chunk_slice,
                link_slice,
                syntax,
                hit,
            );
            if bundle.subject_gap {
                diagnostics.push(Diagnostic {
                    code: "PX_MACHINE_STRUCTURE_SUBJECT_GAP".to_owned(),
                    message: format!(
                        "Machine inferred relation '{}' without a clear subject.",
                        hit.relation_type
                    ),
                });
            }
            evidence_spans.extend(bundle.evidence.iter().cloned());
            relations.push(bundle.relation);
            verb_frames.push(bundle.frame);
        }

        sentence_frames.push(SentenceFrame {
            sentence: sentence.clone(),
            mentions: mention_slice.to_vec(),
            chunks: chunk_slice.to_vec(),
            verb_frames,
            clause_ranges: syntax
                .map(|value| value.clause_ranges.clone())
                .filter(|value| !value.is_empty())
                .unwrap_or_else(|| vec![sentence.range]),
            diagnostics,
        });
    }

    StructureArtifact {
        sentence_frames,
        relations,
        umr_frames: Vec::new(),
        frame_facts: Vec::new(),
        evidence_spans,
        diagnostics: vec![Diagnostic {
            code: "PX_MACHINE_STRUCTURE".to_owned(),
            message: "Machine built sentence frames and relation candidates.".to_owned(),
        }],
    }
}

struct RelationBundle {
    relation: RelationCandidate,
    frame: VerbFrame,
    evidence: Vec<EvidenceSpan>,
    subject_gap: bool,
}

fn build_relation_bundle(
    text: &str,
    tokens: &[TokenSpan],
    sentence_range: TextRange,
    mentions: &[MentionSpan],
    chunks: &[ChunkSpan],
    resolver_links: &[ResolverLink],
    syntax: Option<&SentenceSyntax>,
    hit: &NarrativeVerbHit,
) -> RelationBundle {
    let subject_fallback = mentions
        .iter()
        .filter(|mention| mention.range.end <= hit.range.start)
        .max_by_key(|mention| mention.range.end)
        .map(|mention| fallback_slot_from_mention(mention, mentions, resolver_links));
    let (object_fallback_mention, recipient_fallback_mention) =
        super::first_two_trailing_mentions(mentions, hit.range.end);
    let object_fallback = object_fallback_mention
        .map(|mention| fallback_slot_from_mention(mention, mentions, resolver_links));
    let recipient_fallback = recipient_fallback_mention
        .map(|mention| fallback_slot_from_mention(mention, mentions, resolver_links));

    let verb_token_index = locate_token_index(tokens, sentence_range, hit.range);
    let subject = syntax
        .and_then(|value| {
            verb_token_index.and_then(|verb| {
                dependency_slot_for_labels(
                    tokens,
                    chunks,
                    mentions,
                    resolver_links,
                    value,
                    verb,
                    &[DependencyLabel::Subject, DependencyLabel::ClausalSubject],
                    FrameSlotSource::Dependency,
                )
            })
        })
        .or(subject_fallback.clone());
    let object = syntax
        .and_then(|value| {
            verb_token_index.and_then(|verb| {
                dependency_slot_for_labels(
                    tokens,
                    chunks,
                    mentions,
                    resolver_links,
                    value,
                    verb,
                    &[
                        DependencyLabel::Object,
                        DependencyLabel::ClausalComplement,
                        DependencyLabel::OpenClausalComplement,
                    ],
                    FrameSlotSource::Dependency,
                )
            })
        })
        .or_else(|| {
            syntax.and_then(|value| {
                verb_token_index.and_then(|verb| {
                    let labels = attachment_object_labels(&hit.relation_type);
                    (!labels.is_empty()).then(|| {
                        attachment_slot_for_labels(
                            tokens,
                            chunks,
                            mentions,
                            resolver_links,
                            value,
                            verb,
                            labels,
                        )
                    })?
                })
            })
        })
        .or_else(|| location_object_fallback(hit, mentions, subject.as_ref(), resolver_links))
        .or(object_fallback.clone());
    let recipient = syntax
        .and_then(|value| {
            verb_token_index.and_then(|verb| {
                dependency_slot_for_labels(
                    tokens,
                    chunks,
                    mentions,
                    resolver_links,
                    value,
                    verb,
                    &[DependencyLabel::IndirectObject],
                    FrameSlotSource::Dependency,
                )
            })
        })
        .or_else(|| {
            syntax.and_then(|value| {
                verb_token_index.and_then(|verb| {
                    attachment_slot_for_labels(
                        tokens,
                        chunks,
                        mentions,
                        resolver_links,
                        value,
                        verb,
                        &["to", "for"],
                    )
                })
            })
        })
        .or(recipient_fallback.clone());
    let attachments = syntax
        .and_then(|value| {
            verb_token_index.map(|verb| {
                let anchor = tokens[verb].range;
                value
                    .attachments
                    .iter()
                    .filter(|attachment| attachment.anchor_range == anchor)
                    .map(|attachment| attachment.target_range)
                    .collect::<Vec<_>>()
            })
        })
        .unwrap_or_default();

    let evidence = vec![EvidenceSpan {
        document_id: None,
        note_id: None,
        label: super::slice_or_empty(text, sentence_range)
            .trim()
            .to_owned(),
        kind: Some("sentence".to_owned()),
        range: sentence_range,
    }];

    let relation = RelationCandidate {
        sentence_index: hit.sentence_index,
        verb_range: hit.range,
        lemma: hit.lemma.clone(),
        event_class: hit.event_class.clone(),
        relation_type: hit.relation_type.clone(),
        subject: subject.clone(),
        object: object.clone(),
        recipient: recipient.clone(),
        attachments: attachments.clone(),
        evidence: evidence.clone(),
    };
    let subject_gap = relation.subject.is_none();
    let frame = VerbFrame {
        verb_range: hit.range,
        lemma: hit.lemma.clone(),
        event_class: hit.event_class.clone(),
        relation_type: hit.relation_type.clone(),
        transitivity: hit.transitivity.clone(),
        subject_candidates: subject.into_iter().collect(),
        object_candidates: object.into_iter().collect(),
        recipient_candidates: recipient.into_iter().collect(),
        pp_attachments: attachments,
        clause_range: syntax
            .and_then(|value| {
                value
                    .clause_ranges
                    .iter()
                    .copied()
                    .find(|range| contains(*range, hit.range))
            })
            .unwrap_or(sentence_range),
        evidence: evidence.clone(),
    };

    RelationBundle {
        relation,
        frame,
        evidence,
        subject_gap,
    }
}

fn dependency_slot_for_labels(
    tokens: &[TokenSpan],
    chunks: &[ChunkSpan],
    mentions: &[MentionSpan],
    resolver_links: &[ResolverLink],
    syntax: &SentenceSyntax,
    verb_token_index: usize,
    labels: &[DependencyLabel],
    source: FrameSlotSource,
) -> Option<FrameSlot> {
    syntax
        .arcs
        .iter()
        .find(|arc| {
            arc.head_token_index == Some(verb_token_index)
                && arc
                    .label
                    .as_ref()
                    .is_some_and(|label| labels.iter().any(|candidate| candidate == label))
        })
        .map(|arc| {
            slot_for_token_index(
                tokens,
                chunks,
                mentions,
                resolver_links,
                arc.dependent_token_index,
                source,
            )
        })
}

fn attachment_slot_for_labels(
    tokens: &[TokenSpan],
    chunks: &[ChunkSpan],
    mentions: &[MentionSpan],
    resolver_links: &[ResolverLink],
    syntax: &SentenceSyntax,
    verb_token_index: usize,
    labels: &[&str],
) -> Option<FrameSlot> {
    let anchor = tokens[verb_token_index].range;
    syntax
        .attachments
        .iter()
        .find(|attachment| {
            attachment.anchor_range == anchor
                && labels
                    .iter()
                    .any(|candidate| attachment.label.eq_ignore_ascii_case(candidate))
        })
        .map(|attachment| {
            slot_for_range(
                chunks,
                mentions,
                resolver_links,
                attachment.target_range,
                FrameSlotSource::DependencyAttachment,
                0.82,
            )
        })
}

fn attachment_object_labels(relation_type: &str) -> &'static [&'static str] {
    match relation_type {
        "located_in" | "moves" => &[
            "in", "at", "on", "inside", "within", "into", "near", "around",
        ],
        "works_for" | "member_of" => &["at", "in", "with"],
        _ => &[],
    }
}

fn slot_for_token_index(
    tokens: &[TokenSpan],
    chunks: &[ChunkSpan],
    mentions: &[MentionSpan],
    resolver_links: &[ResolverLink],
    token_index: usize,
    source: FrameSlotSource,
) -> FrameSlot {
    slot_for_range(
        chunks,
        mentions,
        resolver_links,
        tokens[token_index].range,
        source,
        0.76,
    )
}

fn slot_for_range(
    chunks: &[ChunkSpan],
    mentions: &[MentionSpan],
    resolver_links: &[ResolverLink],
    seed_range: TextRange,
    source: FrameSlotSource,
    base_confidence: f32,
) -> FrameSlot {
    let range = chunks
        .iter()
        .find(|chunk| chunk.kind == Some(ChunkKind::Np) && contains(chunk.range, seed_range))
        .map(|chunk| chunk.range)
        .unwrap_or(seed_range);
    let entity_ref = resolve_entity_ref(range, mentions, resolver_links);
    let has_entity_ref = entity_ref.is_some();
    FrameSlot {
        range,
        entity_ref,
        confidence: if range == seed_range && source == FrameSlotSource::ProximityFallback {
            base_confidence
        } else if has_entity_ref {
            (base_confidence + 0.14).min(0.95)
        } else {
            base_confidence
        },
        source: Some(source),
    }
}

fn resolve_entity_ref(
    range: TextRange,
    mentions: &[MentionSpan],
    resolver_links: &[ResolverLink],
) -> Option<MentionEntityRef> {
    mentions
        .iter()
        .find(|mention| overlaps(range, mention.range))
        .and_then(|mention| mention.entity_ref.clone())
        .or_else(|| {
            resolver_links
                .iter()
                .find(|link| overlaps(range, link.source_range))
                .and_then(|link| link.target_entity.clone())
        })
}

fn fallback_slot_from_mention(
    mention: &MentionSpan,
    mentions: &[MentionSpan],
    resolver_links: &[ResolverLink],
) -> FrameSlot {
    FrameSlot {
        range: mention.range,
        entity_ref: resolve_entity_ref(mention.range, mentions, resolver_links)
            .or_else(|| mention.entity_ref.clone()),
        confidence: mention.confidence,
        source: Some(FrameSlotSource::ProximityFallback),
    }
}

fn location_object_fallback(
    hit: &NarrativeVerbHit,
    mentions: &[MentionSpan],
    subject: Option<&FrameSlot>,
    resolver_links: &[ResolverLink],
) -> Option<FrameSlot> {
    if hit.relation_type != "located_in" {
        return None;
    }
    mentions
        .iter()
        .filter(|mention| mention.range.end <= hit.range.start)
        .filter(|mention| Some(mention.range) != subject.map(|slot| slot.range))
        .max_by_key(|mention| {
            (
                mention.kind == Some(phoenix_types::EntityKind::Location),
                mention.range.end,
            )
        })
        .map(|mention| fallback_slot_from_mention(mention, mentions, resolver_links))
}

fn locate_token_index(
    tokens: &[TokenSpan],
    sentence_range: TextRange,
    target: TextRange,
) -> Option<usize> {
    let start = tokens.partition_point(|token| token.range.end <= sentence_range.start);
    tokens[start..]
        .iter()
        .take_while(|token| token.range.start < sentence_range.end)
        .enumerate()
        .find(|(_, token)| contains(sentence_range, token.range) && overlaps(token.range, target))
        .map(|(offset, _)| start + offset)
}

fn contains(outer: TextRange, inner: TextRange) -> bool {
    outer.start <= inner.start && outer.end >= inner.end
}

fn overlaps(left: TextRange, right: TextRange) -> bool {
    left.start < right.end && right.start < left.end
}
