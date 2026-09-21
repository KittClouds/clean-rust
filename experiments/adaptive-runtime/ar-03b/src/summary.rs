use std::collections::BTreeMap;

use hashbrown::HashMap;

use crate::records::{ErrorRecord, StateMetricRecord, SummaryRecord};

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
struct GroupKey {
    phase: String,
    state_step: usize,
    anchor: Option<usize>,
    offset: Option<usize>,
    partition_age: usize,
    method: String,
    evidence_examples: usize,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct StreamKey {
    group: GroupKey,
    dataset: u8,
    initialization: u8,
    seed: u64,
}

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
struct CellKey {
    group: GroupKey,
    dataset: u8,
    initialization: u8,
}

#[derive(Clone, Copy, Debug, Default)]
struct Accumulator {
    n: usize,
    within: f64,
    predicted: f64,
    observed: f64,
    sign: f64,
    cross: f64,
    selected: f64,
    false_authorization: f64,
}

impl Accumulator {
    fn add_values(&mut self, values: [f64; 7]) {
        self.n += 1;
        self.within += values[0];
        self.predicted += values[1];
        self.observed += values[2];
        self.sign += values[3];
        self.cross += values[4];
        self.selected += values[5];
        self.false_authorization += values[6];
    }

    fn means(self) -> [f64; 7] {
        let n = self.n.max(1) as f64;
        [
            self.within / n,
            self.predicted / n,
            self.observed / n,
            self.sign / n,
            self.cross / n,
            self.selected / n,
            self.false_authorization / n,
        ]
    }
}

pub fn summarize_v48(rows: &[StateMetricRecord]) -> Vec<SummaryRecord> {
    let mut streams: HashMap<StreamKey, Accumulator> = HashMap::new();
    for row in rows {
        let key = StreamKey {
            group: GroupKey {
                phase: row.context.phase.clone(),
                state_step: row.context.state_step,
                anchor: row.context.anchor_step,
                offset: row.context.offset_from_anchor,
                partition_age: row.context.partition_age,
                method: row.method.clone(),
                evidence_examples: 48,
            },
            dataset: row.context.dataset_index,
            initialization: row.context.initialization_index,
            seed: row.context.stream_seed,
        };
        streams.entry(key).or_default().add_values([
            row.within_stratum_variance,
            row.predicted_rmse_v48,
            row.observed_rmse_v48,
            row.sign_error_rate_v48,
            row.cross_block_regret_v48,
            row.selected_program_regret_v48,
            row.false_authorization_rate_v48,
        ]);
    }
    let mut cells: HashMap<CellKey, Accumulator> = HashMap::new();
    for (key, accumulator) in streams {
        let values = accumulator.means();
        let cell = CellKey {
            group: key.group,
            dataset: key.dataset,
            initialization: key.initialization,
        };
        cells.entry(cell).or_default().add_values(values);
    }
    let mut overall: HashMap<GroupKey, Accumulator> = HashMap::new();
    for (key, accumulator) in &cells {
        overall
            .entry(key.group.clone())
            .or_default()
            .add_values(accumulator.means());
    }

    let mut result = Vec::with_capacity(cells.len() + overall.len());
    let ordered_cells: BTreeMap<_, _> = cells.into_iter().collect();
    for (key, accumulator) in ordered_cells {
        let values = accumulator.means();
        result.push(SummaryRecord {
            level: "cell".to_owned(),
            dataset_index: Some(key.dataset),
            initialization_index: Some(key.initialization),
            phase: key.group.phase,
            state_step: key.group.state_step,
            anchor_step: key.group.anchor,
            offset_from_anchor: key.group.offset,
            partition_age: key.group.partition_age,
            method: key.group.method,
            evidence_examples: key.group.evidence_examples,
            n_aggregation_units: accumulator.n,
            within_stratum_variance: values[0],
            predicted_rmse: values[1],
            observed_rmse_v48: Some(values[2]),
            sign_error_rate_v48: Some(values[3]),
            cross_block_regret_v48: Some(values[4]),
            selected_program_regret_v48: Some(values[5]),
            false_authorization_rate_v48: Some(values[6]),
        });
    }
    let ordered_overall: BTreeMap<_, _> = overall.into_iter().collect();
    for (key, accumulator) in ordered_overall {
        let values = accumulator.means();
        result.push(SummaryRecord {
            level: "overall_equal_cell".to_owned(),
            dataset_index: None,
            initialization_index: None,
            phase: key.phase,
            state_step: key.state_step,
            anchor_step: key.anchor,
            offset_from_anchor: key.offset,
            partition_age: key.partition_age,
            method: key.method,
            evidence_examples: key.evidence_examples,
            n_aggregation_units: accumulator.n,
            within_stratum_variance: values[0],
            predicted_rmse: values[1],
            observed_rmse_v48: Some(values[2]),
            sign_error_rate_v48: Some(values[3]),
            cross_block_regret_v48: Some(values[4]),
            selected_program_regret_v48: Some(values[5]),
            false_authorization_rate_v48: Some(values[6]),
        });
    }
    result
}

pub fn summarize_error_curve(rows: &[ErrorRecord]) -> Vec<SummaryRecord> {
    let mut streams: HashMap<StreamKey, Accumulator> = HashMap::new();
    for row in rows {
        let key = StreamKey {
            group: GroupKey {
                phase: row.context.phase.clone(),
                state_step: row.context.state_step,
                anchor: row.context.anchor_step,
                offset: row.context.offset_from_anchor,
                partition_age: row.context.partition_age,
                method: row.method.clone(),
                evidence_examples: row.evidence_examples,
            },
            dataset: row.context.dataset_index,
            initialization: row.context.initialization_index,
            seed: row.context.stream_seed,
        };
        streams.entry(key).or_default().add_values([
            row.within_stratum_variance,
            row.predicted_rmse,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ]);
    }
    let mut cells: HashMap<CellKey, Accumulator> = HashMap::new();
    for (key, accumulator) in streams {
        cells
            .entry(CellKey {
                group: key.group,
                dataset: key.dataset,
                initialization: key.initialization,
            })
            .or_default()
            .add_values(accumulator.means());
    }
    let mut overall: HashMap<GroupKey, Accumulator> = HashMap::new();
    for (key, accumulator) in &cells {
        overall
            .entry(key.group.clone())
            .or_default()
            .add_values(accumulator.means());
    }
    let mut result = Vec::with_capacity(cells.len() + overall.len());
    let ordered_cells: BTreeMap<_, _> = cells.into_iter().collect();
    for (key, accumulator) in ordered_cells {
        let values = accumulator.means();
        result.push(SummaryRecord {
            level: "cell".to_owned(),
            dataset_index: Some(key.dataset),
            initialization_index: Some(key.initialization),
            phase: key.group.phase,
            state_step: key.group.state_step,
            anchor_step: key.group.anchor,
            offset_from_anchor: key.group.offset,
            partition_age: key.group.partition_age,
            method: key.group.method,
            evidence_examples: key.group.evidence_examples,
            n_aggregation_units: accumulator.n,
            within_stratum_variance: values[0],
            predicted_rmse: values[1],
            observed_rmse_v48: None,
            sign_error_rate_v48: None,
            cross_block_regret_v48: None,
            selected_program_regret_v48: None,
            false_authorization_rate_v48: None,
        });
    }
    let ordered_overall: BTreeMap<_, _> = overall.into_iter().collect();
    for (key, accumulator) in ordered_overall {
        let values = accumulator.means();
        result.push(SummaryRecord {
            level: "overall_equal_cell".to_owned(),
            dataset_index: None,
            initialization_index: None,
            phase: key.phase,
            state_step: key.state_step,
            anchor_step: key.anchor,
            offset_from_anchor: key.offset,
            partition_age: key.partition_age,
            method: key.method,
            evidence_examples: key.evidence_examples,
            n_aggregation_units: accumulator.n,
            within_stratum_variance: values[0],
            predicted_rmse: values[1],
            observed_rmse_v48: None,
            sign_error_rate_v48: None,
            cross_block_regret_v48: None,
            selected_program_regret_v48: None,
            false_authorization_rate_v48: None,
        });
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::records::Context;

    #[test]
    fn freshness_summaries_keep_anchor_windows_separate() {
        let make_row = |anchor_step| ErrorRecord {
            context: Context {
                dataset_index: 0,
                initialization_index: 0,
                stream_seed: 1,
                state_step: anchor_step + 25,
                phase: "freshness_stale".to_owned(),
                anchor_step: Some(anchor_step),
                offset_from_anchor: Some(25),
                partition_age: 25,
                candidate_count: 7,
            },
            method: "full_gradient_171".to_owned(),
            evidence_examples: 48,
            samples_per_stratum: 4,
            within_stratum_variance: 0.5,
            predicted_rmse: 0.25,
        };
        let summaries = summarize_error_curve(&[make_row(600), make_row(2_400)]);
        assert_eq!(summaries.len(), 4);
        assert!(summaries.iter().any(|row| row.anchor_step == Some(600)));
        assert!(summaries.iter().any(|row| row.anchor_step == Some(2_400)));
    }
}
