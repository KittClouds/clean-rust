use hashbrown::HashMap;

use crate::audit::{MetricMean, StateMetric};

pub fn by_stream(rows: &[StateMetric]) -> Vec<MetricMean> {
    let mut grouped: HashMap<(u8, u8, u64, String), Vec<&StateMetric>> = HashMap::new();
    for row in rows {
        let method = if row.method.starts_with("hash_placebo_") {
            "hash_placebo_mean".to_owned()
        } else {
            row.method.clone()
        };
        grouped
            .entry((
                row.dataset_index,
                row.initialization_index,
                row.seed,
                method,
            ))
            .or_default()
            .push(row);
    }
    let mut result: Vec<_> = grouped
        .into_iter()
        .map(|((dataset, initialization, seed, method), values)| {
            let mut mean = mean_state_metrics(method, &values);
            mean.dataset_index = dataset;
            mean.initialization_index = initialization;
            mean.seed = seed;
            mean
        })
        .collect();
    result.sort_by(|left, right| {
        left.dataset_index
            .cmp(&right.dataset_index)
            .then_with(|| left.initialization_index.cmp(&right.initialization_index))
            .then_with(|| left.method.cmp(&right.method))
            .then_with(|| left.seed.cmp(&right.seed))
    });
    result
}

pub fn cells(rows: &[MetricMean]) -> Vec<MetricMean> {
    let mut grouped: HashMap<(u8, u8, String), Vec<&MetricMean>> = HashMap::new();
    for row in rows {
        grouped
            .entry((
                row.dataset_index,
                row.initialization_index,
                row.method.clone(),
            ))
            .or_default()
            .push(row);
    }
    let mut result: Vec<_> = grouped
        .into_iter()
        .map(|((dataset, initialization, method), values)| {
            let mut mean = mean_metric_means(method, &values);
            mean.dataset_index = dataset;
            mean.initialization_index = initialization;
            mean
        })
        .collect();
    result.sort_by(|left, right| {
        left.dataset_index
            .cmp(&right.dataset_index)
            .then_with(|| left.initialization_index.cmp(&right.initialization_index))
            .then_with(|| left.method.cmp(&right.method))
    });
    result
}

pub fn datasets(rows: &[MetricMean]) -> Vec<MetricMean> {
    let mut grouped: HashMap<(u8, String), Vec<&MetricMean>> = HashMap::new();
    for row in rows {
        grouped
            .entry((row.dataset_index, row.method.clone()))
            .or_default()
            .push(row);
    }
    let mut result: Vec<_> = grouped
        .into_iter()
        .map(|((dataset, method), values)| {
            let mut mean = mean_metric_means(method, &values);
            mean.dataset_index = dataset;
            mean.initialization_index = u8::MAX;
            mean
        })
        .collect();
    result.sort_by(|left, right| {
        left.dataset_index
            .cmp(&right.dataset_index)
            .then_with(|| left.method.cmp(&right.method))
    });
    result
}

pub fn initializations(rows: &[MetricMean]) -> Vec<MetricMean> {
    let mut grouped: HashMap<(u8, String), Vec<&MetricMean>> = HashMap::new();
    for row in rows {
        grouped
            .entry((row.initialization_index, row.method.clone()))
            .or_default()
            .push(row);
    }
    let mut result: Vec<_> = grouped
        .into_iter()
        .map(|((initialization, method), values)| {
            let mut mean = mean_metric_means(method, &values);
            mean.dataset_index = u8::MAX;
            mean.initialization_index = initialization;
            mean
        })
        .collect();
    result.sort_by(|left, right| {
        left.initialization_index
            .cmp(&right.initialization_index)
            .then_with(|| left.method.cmp(&right.method))
    });
    result
}

pub fn overall(rows: &[MetricMean]) -> Vec<MetricMean> {
    let mut grouped: HashMap<String, Vec<&MetricMean>> = HashMap::new();
    for row in rows {
        grouped.entry(row.method.clone()).or_default().push(row);
    }
    let mut result: Vec<_> = grouped
        .into_iter()
        .map(|(method, values)| {
            let mut mean = mean_metric_means(method, &values);
            mean.dataset_index = u8::MAX;
            mean.initialization_index = u8::MAX;
            mean
        })
        .collect();
    result.sort_by(|left, right| left.method.cmp(&right.method));
    result
}

fn mean_state_metrics(method: String, rows: &[&StateMetric]) -> MetricMean {
    let count = rows.len().max(1) as f64;
    MetricMean {
        method,
        seed: 0,
        n_states: if rows
            .first()
            .is_some_and(|row| row.method.starts_with("hash_placebo_"))
        {
            rows.len() / 8
        } else {
            rows.len()
        },
        within_stratum_variance: rows
            .iter()
            .map(|row| row.within_stratum_variance)
            .sum::<f64>()
            / count,
        predicted_rmse: rows.iter().map(|row| row.predicted_rmse).sum::<f64>() / count,
        observed_rmse: rows.iter().map(|row| row.observed_rmse).sum::<f64>() / count,
        sign_error_rate: rows.iter().map(|row| row.sign_error_rate).sum::<f64>() / count,
        cross_block_regret: rows.iter().map(|row| row.cross_block_regret).sum::<f64>() / count,
        selected_program_regret: rows
            .iter()
            .map(|row| row.selected_program_regret)
            .sum::<f64>()
            / count,
        false_authorization_rate: rows
            .iter()
            .map(|row| row.false_authorization_rate)
            .sum::<f64>()
            / count,
        ..MetricMean::default()
    }
}

fn mean_metric_means(method: String, rows: &[&MetricMean]) -> MetricMean {
    let count = rows.len().max(1) as f64;
    MetricMean {
        method,
        seed: 0,
        n_states: rows.iter().map(|row| row.n_states).sum(),
        within_stratum_variance: rows
            .iter()
            .map(|row| row.within_stratum_variance)
            .sum::<f64>()
            / count,
        predicted_rmse: rows.iter().map(|row| row.predicted_rmse).sum::<f64>() / count,
        observed_rmse: rows.iter().map(|row| row.observed_rmse).sum::<f64>() / count,
        sign_error_rate: rows.iter().map(|row| row.sign_error_rate).sum::<f64>() / count,
        cross_block_regret: rows.iter().map(|row| row.cross_block_regret).sum::<f64>() / count,
        selected_program_regret: rows
            .iter()
            .map(|row| row.selected_program_regret)
            .sum::<f64>()
            / count,
        false_authorization_rate: rows
            .iter()
            .map(|row| row.false_authorization_rate)
            .sum::<f64>()
            / count,
        ..MetricMean::default()
    }
}
