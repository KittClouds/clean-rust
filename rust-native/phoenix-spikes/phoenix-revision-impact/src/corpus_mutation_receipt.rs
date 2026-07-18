use serde::Serialize;

pub const CORPUS_MUTATION_EXPERIMENT_SCHEMA: &str = "phoenix.revision-impact-text-mutation-run/v1";

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MutationReviewPacket {
    pub case_id: String,
    pub series_id: String,
    pub source_book_id: String,
    pub target_book_id: String,
    pub case_kind: String,
    pub review_status: &'static str,
    pub proposed_classification: &'static str,
    pub source_event_id: String,
    pub target_event_id: String,
    pub source_event_label: String,
    pub source_chunk_id: String,
    pub target_chunk_id: String,
    pub original_excerpt: String,
    pub mutated_excerpt: String,
    pub target_excerpt: String,
    pub mutation_description: String,
    pub mutated_copy_path: String,
    pub mutated_copy_sha256: String,
    pub baseline_copy_unchanged: bool,
    pub extraction_retraction_detected: bool,
    pub collateral_event_delta: i64,
    pub deleted_identity_unmatched: bool,
    pub identity_outcome: String,
    pub replacement_event_id: Option<String>,
    pub replacement_score_millis: Option<u16>,
    pub event_identity_matches: usize,
    pub scene_identity_matches: usize,
    pub identity_ambiguities: usize,
    pub deterministic_classification: Option<String>,
    pub deterministic_report_digest: String,
    pub deterministic_rerun_match: bool,
    pub no_truth_writes: bool,
    pub passed: bool,
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MutationExperimentTotals {
    pub cases: usize,
    pub intra_book_cases: usize,
    pub cross_book_cases: usize,
    pub extraction_retractions_found: usize,
    pub deterministic_broken_found: usize,
    pub deleted_identities_unmatched: usize,
    pub retyped_identity_matches: usize,
    pub safe_identity_outcomes: usize,
    pub identity_ambiguities: usize,
    pub passed_cases: usize,
    pub mutated_bytes: usize,
}

impl MutationExperimentTotals {
    pub(super) fn add(&mut self, row: &MutationReviewPacket, bytes: usize) {
        self.cases += 1;
        if row.case_kind == "cross_book_temporal" {
            self.cross_book_cases += 1;
        } else {
            self.intra_book_cases += 1;
        }
        self.extraction_retractions_found += usize::from(row.extraction_retraction_detected);
        self.deterministic_broken_found +=
            usize::from(row.deterministic_classification.as_deref() == Some("broken"));
        self.deleted_identities_unmatched += usize::from(row.deleted_identity_unmatched);
        self.retyped_identity_matches +=
            usize::from(row.identity_outcome == "matched_retyped_event");
        self.safe_identity_outcomes += usize::from(matches!(
            row.identity_outcome.as_str(),
            "unmatched_retraction" | "matched_retyped_event"
        ));
        self.identity_ambiguities += row.identity_ambiguities;
        self.passed_cases += usize::from(row.passed);
        self.mutated_bytes += bytes;
    }
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CorpusMutationExperimentReceipt {
    pub schema: &'static str,
    pub manifest_path: String,
    pub mutation_root: String,
    pub label_authority: &'static str,
    pub identity_adapter: &'static str,
    pub continuity_container_status: &'static str,
    pub models_enabled: bool,
    pub persistence_writes: bool,
    pub source_copies_modified: bool,
    pub elapsed_micros: u64,
    pub peak_working_set_bytes: u64,
    pub totals: MutationExperimentTotals,
    pub review_packets: Vec<MutationReviewPacket>,
    pub all_cases_passed: bool,
}
