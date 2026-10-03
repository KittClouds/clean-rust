#![deny(unsafe_op_in_unsafe_fn)]

pub mod census;
pub mod overlap;
pub mod source_registry;
pub mod splits;

/// The bridge owns orchestration and audit policy; the parsers live beside the
/// canonical v0.2 types and are re-exported here as the source-adapter surface.
pub mod adapters {
    pub use jev_decision_world_v02::adapters::{
        chaos_nli, clinc_oos, common, docred, go_emotions, massive, multitask_classification,
        tasksource,
    };
}

use anyhow::Result;
use jev_decision_world_v02::types::CanonicalEpisode;

pub fn validate_all(episodes: &[CanonicalEpisode]) -> Result<()> {
    for episode in episodes {
        jev_decision_world_v02::validate::validate_episode(episode)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use jev_decision_world_v02::structured::{
        StructuredRenderer, structured_span_relation_episode,
    };

    #[test]
    fn census_keeps_probability_regimes_separate() {
        let first =
            structured_span_relation_episode(StructuredRenderer::MaraFirst).expect("episode");
        let report = census::census(&[first]);
        assert_eq!(
            report
                .probability_source_counts
                .get("exact_generative_posterior"),
            Some(&2)
        );
        assert!(
            report
                .target_entropy_by_probability_source
                .contains_key("exact_generative_posterior")
        );
    }

    #[test]
    fn split_groups_renderer_siblings_by_perturbation_family() {
        let first = structured_span_relation_episode(StructuredRenderer::MaraFirst).expect("first");
        let second =
            structured_span_relation_episode(StructuredRenderer::OrionFirst).expect("second");
        let report = splits::build(&[first, second]);
        assert_eq!(
            report
                .group_key_by_episode
                .values()
                .collect::<std::collections::HashSet<_>>()
                .len(),
            1
        );
    }

    #[test]
    fn overlap_audit_reports_exact_text_duplicates() {
        let first = structured_span_relation_episode(StructuredRenderer::MaraFirst).expect("first");
        let mut second = first.clone();
        second.identity.episode_id = "copy".to_string();
        let report = overlap::audit(&[first, second]);
        assert_eq!(report.exact_text_collisions.len(), 1);
    }
}
