use phoenix_types::ImpactClassification;
use serde::{Deserialize, Serialize};

pub const CORPUS_EXPERIMENT_SCHEMA: &str = "phoenix.revision-impact-corpus-run/v1";

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct CorpusManifest {
    pub schema: String,
    pub mode: String,
    pub series: Vec<ManifestSeries>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct ManifestSeries {
    pub series_id: String,
    pub books: Vec<ManifestBook>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct ManifestBook {
    pub book_id: String,
    pub ordinal: u32,
    pub path: String,
    pub bytes: u64,
    pub chapter_headings: usize,
    pub sha256: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CorpusBookReceipt {
    pub series_id: String,
    pub book_id: String,
    pub book_ordinal: u32,
    pub copied_path: String,
    pub source_bytes: usize,
    pub source_sha256: String,
    pub chapter_headings: usize,
    pub chunks: usize,
    pub mentions: usize,
    pub events: usize,
    pub temporal_edges: usize,
    pub causal_edges: usize,
    pub memory_states: usize,
    pub hard_constraints: usize,
    pub soft_constraints: usize,
    pub build_micros: u64,
    pub analysis_micros: u64,
    pub source_unchanged: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CorpusMutationReceipt {
    pub series_id: String,
    pub book_id: String,
    pub case_id: String,
    pub mutation_kind: String,
    pub source_event_id: String,
    pub expected_scene_id: Option<String>,
    pub expected_classification: Option<ImpactClassification>,
    pub observed_classification: Option<ImpactClassification>,
    pub impact_count: usize,
    pub report_digest: String,
    pub deterministic_rerun_match: bool,
    pub no_truth_writes: bool,
    pub passed: bool,
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CorpusExperimentTotals {
    pub series: usize,
    pub books: usize,
    pub source_bytes: usize,
    pub chunks: usize,
    pub events: usize,
    pub temporal_edges: usize,
    pub causal_edges: usize,
    pub cases: usize,
    pub passed_cases: usize,
    pub hard_cases: usize,
    pub hard_cases_found: usize,
    pub soft_cases: usize,
    pub soft_cases_not_broken: usize,
    pub negative_controls: usize,
    pub negative_controls_clean: usize,
}

impl CorpusExperimentTotals {
    pub(super) fn add_book(&mut self, book: &CorpusBookReceipt) {
        self.books += 1;
        self.source_bytes += book.source_bytes;
        self.chunks += book.chunks;
        self.events += book.events;
        self.temporal_edges += book.temporal_edges;
        self.causal_edges += book.causal_edges;
    }

    pub(super) fn add_case(&mut self, case: &CorpusMutationReceipt) {
        self.cases += 1;
        self.passed_cases += usize::from(case.passed);
        match case.expected_classification {
            Some(ImpactClassification::Broken) => {
                self.hard_cases += 1;
                self.hard_cases_found +=
                    usize::from(case.observed_classification == Some(ImpactClassification::Broken));
            }
            Some(ImpactClassification::Suspicious) => {
                self.soft_cases += 1;
                self.soft_cases_not_broken +=
                    usize::from(case.observed_classification != Some(ImpactClassification::Broken));
            }
            _ => {
                self.negative_controls += 1;
                self.negative_controls_clean += usize::from(case.impact_count == 0);
            }
        }
    }
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CorpusExperimentReceipt {
    pub schema: &'static str,
    pub manifest_schema: String,
    pub manifest_path: String,
    pub input_mode: String,
    pub authoritative_claim: &'static str,
    pub models_enabled: bool,
    pub persistence_writes: bool,
    pub working_set_start_bytes: u64,
    pub peak_working_set_bytes: u64,
    pub elapsed_micros: u64,
    pub books: Vec<CorpusBookReceipt>,
    pub mutations: Vec<CorpusMutationReceipt>,
    pub totals: CorpusExperimentTotals,
    pub all_source_copies_unchanged: bool,
    pub all_cases_passed: bool,
}
