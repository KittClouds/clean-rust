use compact_str::CompactString;
use phoenix_machine::SurfaceCompileArtifacts;
use phoenix_types::{
    Argument, AttributionFrame, ConditionalFrame, FrameSlot, MentionEntityRef, PredicateFrame,
    Proposition, ProvenanceRef, QuoteFrame, RelationCandidate, SourceRange, TextRange,
};

mod scope;

use scope::{analyze_sentence_scope, attachment_role};

pub struct PropositionLowerer;

impl PropositionLowerer {
    pub fn lower(artifacts: &SurfaceCompileArtifacts) -> Vec<Proposition> {
        Self::lower_with_text("", artifacts)
    }

    pub fn lower_with_text(text: &str, artifacts: &SurfaceCompileArtifacts) -> Vec<Proposition> {
        artifacts
            .structure
            .relations
            .iter()
            .enumerate()
            .map(|(index, relation)| lower_relation(text, artifacts, relation, index))
            .collect()
    }
}

fn lower_relation(
    text: &str,
    artifacts: &SurfaceCompileArtifacts,
    relation: &RelationCandidate,
    index: usize,
) -> Proposition {
    let sentence_range = artifacts
        .scan
        .sentences
        .get(relation.sentence_index)
        .map(|sentence| sentence.range)
        .or_else(|| {
            artifacts
                .structure
                .sentence_frames
                .get(relation.sentence_index)
                .map(|frame| frame.sentence.range)
        });
    let clause_range = artifacts
        .structure
        .sentence_frames
        .get(relation.sentence_index)
        .and_then(|frame| frame.clause_ranges.first().copied())
        .or(sentence_range);
    let scope = sentence_range
        .map(|range| analyze_sentence_scope(text, range, relation))
        .unwrap_or_default();

    let mut arguments = smallvec::SmallVec::<[Argument; 4]>::new();
    push_slot_argument(
        &mut arguments,
        artifacts,
        relation,
        relation.subject.as_ref(),
        "subject",
    );
    push_slot_argument(
        &mut arguments,
        artifacts,
        relation,
        relation.object.as_ref(),
        "object",
    );
    push_slot_argument(
        &mut arguments,
        artifacts,
        relation,
        relation.recipient.as_ref(),
        "recipient",
    );
    for range in &relation.attachments {
        arguments.push(Argument {
            role: CompactString::from(attachment_role(text, *range)),
            mention_index: mention_index_for_range(artifacts, relation.sentence_index, *range),
            entity_id: entity_id_for_range(artifacts, relation.sentence_index, *range),
            range: Some(SourceRange::from(*range)),
        });
    }

    let subject_entity_id = relation
        .subject
        .as_ref()
        .and_then(slot_entity_id)
        .or_else(|| scope.speaker_entity_id.clone());

    Proposition {
        proposition_id: CompactString::from(format!(
            "prop:{}:{}:{}",
            relation.sentence_index, relation.verb_range.start, index
        )),
        sentence_index: relation.sentence_index,
        predicate: PredicateFrame {
            predicate: CompactString::from(relation.lemma.as_str()),
            trigger_range: SourceRange::from(relation.verb_range),
            relation_type: CompactString::from(relation.relation_type.as_str()),
        },
        clause_range: clause_range.map(SourceRange::from),
        arguments,
        scope_ops: scope.scope_ops,
        attribution: scope.attribution_range.map(|quote_range| AttributionFrame {
            source_entity_id: subject_entity_id.clone(),
            quote_range: Some(SourceRange::from(quote_range)),
        }),
        conditional: scope.conditional.map(|conditional| ConditionalFrame {
            condition_range: conditional.condition.map(SourceRange::from),
            consequent_range: conditional.consequent.map(SourceRange::from),
        }),
        quote: scope.quote_range.map(|quote_range| QuoteFrame {
            quote_range: SourceRange::from(quote_range),
            speaker_entity_id: subject_entity_id,
        }),
        evidence: relation
            .evidence
            .iter()
            .map(|evidence| ProvenanceRef {
                document_id: evidence.document_id.clone(),
                note_id: evidence.note_id.clone(),
                label: CompactString::from(evidence.label.as_str()),
                kind: evidence
                    .kind
                    .as_ref()
                    .map(|kind| CompactString::from(kind.as_str())),
                range: SourceRange::from(evidence.range),
            })
            .collect(),
    }
}

fn push_slot_argument(
    arguments: &mut smallvec::SmallVec<[Argument; 4]>,
    artifacts: &SurfaceCompileArtifacts,
    relation: &RelationCandidate,
    slot: Option<&FrameSlot>,
    role: &'static str,
) {
    let Some(slot) = slot else {
        return;
    };
    arguments.push(Argument {
        role: CompactString::from(role),
        mention_index: mention_index_for_range(artifacts, relation.sentence_index, slot.range),
        entity_id: slot_entity_id(slot),
        range: Some(SourceRange::from(slot.range)),
    });
}

fn slot_entity_id(slot: &FrameSlot) -> Option<phoenix_types::EntityId> {
    slot.entity_ref.as_ref().and_then(|entity| match entity {
        MentionEntityRef::Known(id) => Some(id.clone()),
        MentionEntityRef::Speculative(_) => None,
    })
}

fn mention_index_for_range(
    artifacts: &SurfaceCompileArtifacts,
    sentence_index: usize,
    range: TextRange,
) -> Option<usize> {
    artifacts.scan.mentions.iter().position(|mention| {
        mention.sentence_index == sentence_index
            && mention.range.start <= range.start
            && mention.range.end >= range.end
    })
}

fn entity_id_for_range(
    artifacts: &SurfaceCompileArtifacts,
    sentence_index: usize,
    range: TextRange,
) -> Option<phoenix_types::EntityId> {
    mention_index_for_range(artifacts, sentence_index, range)
        .and_then(|index| artifacts.scan.mentions.get(index))
        .and_then(|mention| mention.entity_ref.as_ref())
        .and_then(|entity| match entity {
            MentionEntityRef::Known(id) => Some(id.clone()),
            MentionEntityRef::Speculative(_) => None,
        })
}

#[cfg(test)]
mod tests {
    use phoenix_machine::{MachineConfig, MachineExtractionConfig, SurfaceCompiler};
    use phoenix_types::ScopeKey;

    use super::PropositionLowerer;

    fn compile(text: &str) -> Vec<phoenix_types::Proposition> {
        let compiler = SurfaceCompiler::new(MachineConfig {
            extraction: MachineExtractionConfig {
                enable_rustling_pos: true,
                enable_scirs2_rule_ner: false,
                enable_scirs2_pattern_ner: false,
                enable_native_refinement: true,
            },
        });
        let artifacts = compiler.compile(text, &ScopeKey::default(), &[]);
        PropositionLowerer::lower_with_text(text, &artifacts)
    }

    #[test]
    fn lowers_scope_quote_condition_and_recipient_roles() {
        let rows = compile("If Kai returns, Hazel might not tell Rift, \"the gate opened\"");
        assert!(!rows.is_empty());
        assert!(rows.iter().any(|row| row.conditional.is_some()));
        assert!(rows.iter().any(|row| row.quote.is_some()));
        assert!(rows.iter().any(|row| row.attribution.is_some()));
        assert!(rows
            .iter()
            .any(|row| row.scope_ops.iter().any(|op| op.polarity.is_some())));
        assert!(rows
            .iter()
            .any(|row| row.scope_ops.iter().any(|op| op.modality.is_some())));
    }

    #[test]
    fn lowers_question_scope_without_losing_assertion() {
        let rows = compile("Did Kai find Hazel?");
        assert!(!rows.is_empty());
        assert!(rows[0].scope_ops.iter().any(|op| op.kind == "question"));
        assert!(rows[0].scope_ops.iter().any(|op| op.kind == "assertion"));
    }
}
