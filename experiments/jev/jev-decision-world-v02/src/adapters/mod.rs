pub mod chaos_nli;
pub mod clinc_oos;
pub mod common;
pub mod docred;
pub mod go_emotions;
pub mod massive;
pub mod multitask_classification;
pub mod tasksource;

use crate::types::QueryView;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AdapterDescriptor {
    pub adapter_id: &'static str,
    pub source_dataset_id: &'static str,
    pub supported_views: &'static [QueryView],
    pub disposition: &'static str,
}

pub fn registry() -> Vec<AdapterDescriptor> {
    vec![
        AdapterDescriptor {
            adapter_id: multitask_classification::ADAPTER_ID,
            source_dataset_id: "sr5434/multitask-classification-dataset",
            supported_views: &[QueryView::Choice],
            disposition: "conditional: license receipt and source label audit",
        },
        AdapterDescriptor {
            adapter_id: tasksource::ADAPTER_ID,
            source_dataset_id: "tasksource/zero-shot-label-nli",
            supported_views: &[QueryView::Choice],
            disposition: "lineage quarantine: aggregate wrapper",
        },
        AdapterDescriptor {
            adapter_id: chaos_nli::ADAPTER_ID,
            source_dataset_id: "ChaosNLI",
            supported_views: &[QueryView::Choice],
            disposition: "conditional: verify artifact terms",
        },
        AdapterDescriptor {
            adapter_id: go_emotions::ADAPTER_ID,
            source_dataset_id: "google-research-datasets/go_emotions",
            supported_views: &[QueryView::IndependentApplicability],
            disposition: "accepted for human-disagreement lane",
        },
        AdapterDescriptor {
            adapter_id: clinc_oos::ADAPTER_ID,
            source_dataset_id: "clinc/oos-eval",
            supported_views: &[QueryView::Choice, QueryView::Abstain],
            disposition: "conditional: license receipt and pinned inventory",
        },
        AdapterDescriptor {
            adapter_id: massive::ADAPTER_ID,
            source_dataset_id: "AmazonScience/massive",
            supported_views: &[QueryView::Choice, QueryView::SpanType],
            disposition: "accepted with proposed E01 structured extension",
        },
        AdapterDescriptor {
            adapter_id: docred::ADAPTER_ID,
            source_dataset_id: "thunlp/docred",
            supported_views: &[QueryView::Relation],
            disposition: "accepted for relation/evidence lane; distant split separate",
        },
    ]
}
