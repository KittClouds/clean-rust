use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;

use phoenix_graph_rebuild::{
    build_document_semantic_summary, DocumentSemanticInput, DocumentSemanticRequest,
};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("../../../../docs/midrun.md"));
    let text = fs::read_to_string(&path)?;
    let started = Instant::now();
    let summary = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![DocumentSemanticInput {
            note_id: path
                .file_stem()
                .and_then(|value| value.to_str())
                .unwrap_or("document")
                .to_owned(),
            text,
        }],
        entities: Vec::new(),
    });
    let elapsed = started.elapsed();
    let counters = &summary.counters;
    println!("schema={}", summary.schema_version);
    println!("source={}", path.display());
    println!("elapsed_ms={}", elapsed.as_millis());
    println!("sentences={}", counters.sentences);
    println!("propositions={}", counters.propositions);
    println!("arguments={}", counters.arguments);
    println!("role_annotations={}", counters.role_annotations);
    println!(
        "unresolved_role_surfaces={}",
        counters.unresolved_role_surfaces
    );
    println!("role_failure_reasons={}", counters.role_failure_reasons);
    println!("frame_annotations={}", counters.frame_annotations);
    println!("lexical_frame_matches={}", counters.lexical_frame_matches);
    println!("fallback_frame_matches={}", counters.fallback_frame_matches);
    println!("low_confidence_frames={}", counters.low_confidence_frames);
    println!("frame_failure_reasons={}", counters.frame_failure_reasons);
    println!("factuality_annotations={}", counters.factuality_annotations);
    println!("scoped_factuality={}", counters.scoped_factuality);
    println!("attributed_factuality={}", counters.attributed_factuality);
    println!("quoted_factuality={}", counters.quoted_factuality);
    println!("conditional_factuality={}", counters.conditional_factuality);
    println!(
        "speech_or_belief_frames={}",
        counters.speech_or_belief_frames
    );
    println!(
        "low_confidence_factuality={}",
        counters.low_confidence_factuality
    );
    println!(
        "factuality_failure_reasons={}",
        counters.factuality_failure_reasons
    );
    println!(
        "document_argument_recoveries={}",
        counters.document_argument_recoveries
    );
    println!(
        "local_coreference_recoveries={}",
        counters.local_coreference_recoveries
    );
    println!(
        "alias_continuity_recoveries={}",
        counters.alias_continuity_recoveries
    );
    println!(
        "omitted_subject_recoveries={}",
        counters.omitted_subject_recoveries
    );
    println!(
        "quote_speaker_recoveries={}",
        counters.quote_speaker_recoveries
    );
    println!("repeated_event_links={}", counters.repeated_event_links);
    println!(
        "window_argument_completions={}",
        counters.window_argument_completions
    );
    println!(
        "low_confidence_recoveries={}",
        counters.low_confidence_recoveries
    );
    println!(
        "recovery_failure_reasons={}",
        counters.recovery_failure_reasons
    );
    println!("situation_instances={}", counters.situation_instances);
    println!("state_intervals={}", counters.state_intervals);
    println!("event_orderings={}", counters.event_orderings);
    println!(
        "explicit_event_orderings={}",
        counters.explicit_event_orderings
    );
    println!("recurrence_orderings={}", counters.recurrence_orderings);
    println!(
        "persistent_state_intervals={}",
        counters.persistent_state_intervals
    );
    println!(
        "terminated_state_intervals={}",
        counters.terminated_state_intervals
    );
    println!("temporal_conflicts={}", counters.temporal_conflicts);
    println!(
        "world_state_ineligible_situations={}",
        counters.world_state_ineligible_situations
    );
    println!("negated={}", counters.negated);
    println!("modal={}", counters.modal);
    println!("conditional={}", counters.conditional);
    println!("attributed={}", counters.attributed);
    println!("quoted={}", counters.quoted);
    println!("questions={}", counters.questions);
    println!("directives={}", counters.directives);
    println!("n_ary={}", counters.n_ary);
    println!("reviewable={}", counters.reviewable);
    println!("ledger_only={}", counters.ledger_only);
    println!("predicate_modifiers={}", counters.predicate_modifiers);
    println!("predicate_noise={}", counters.predicate_noise);
    for proposition in summary
        .documents
        .iter()
        .flat_map(|document| &document.propositions)
        .take(12)
    {
        println!(
            "sample={} [{}] frame={}/{} factuality={} quality={} admission={} args={} recovered={} confidence={} :: {}",
            proposition.predicate,
            proposition.relation_type,
            proposition.frame.frame,
            proposition.frame.source,
            proposition.factuality.factuality,
            proposition.predicate_quality,
            proposition.predicate_admission,
            proposition.arguments.len(),
            proposition.document_argument_recoveries.len(),
            proposition.confidence_millis,
            proposition.preview
        );
    }
    Ok(())
}
