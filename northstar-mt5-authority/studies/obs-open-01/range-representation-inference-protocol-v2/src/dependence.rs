use crate::model::*;
use crate::pseudo_db::PseudoDbResult;
use hashbrown::HashMap;
use serde::Serialize;
use wide::f64x4;

#[derive(Debug, Clone, Serialize)]
pub struct DependenceQualification {
    pub diagnostics: Vec<BlockDiagnostic>,
    pub compatible: bool,
    pub criteria: Vec<String>,
    pub failed_criteria: Vec<String>,
    pub selected_method: String,
    pub selection_state: String,
    pub d_a_proves_d_b_assumptions: bool,
}

pub fn diagnose(pseudo: &PseudoDbResult) -> Result<DependenceQualification, String> {
    let mut groups: HashMap<(String, u8), Vec<&ScoreRow>> = HashMap::new();
    for row in &pseudo.score_rows {
        groups
            .entry((row.representation.clone(), row.fold_id))
            .or_default()
            .push(row);
    }
    let mut diagnostics = Vec::with_capacity(groups.len());
    for ((representation, fold), mut rows) in groups {
        rows.sort_by_key(|row| row.session_index);
        let model_state_id = rows[0].model_state_id.clone();
        if rows.iter().any(|row| row.model_state_id != model_state_id) {
            return Err("MODEL_STATE_CROSSED_WITHIN_DIAGNOSTIC".into());
        }
        let values = rows.iter().map(|row| row.difference).collect::<Vec<_>>();
        let moments = moments(&values)?;
        let max_lag = 6.min(values.len().saturating_sub(1));
        let acf = (1..=max_lag)
            .map(|lag| autocorrelation(&values, lag))
            .collect::<Result<Vec<_>, _>>()?;
        let hac_lag = automatic_hac_lag(values.len());
        let lrv = bartlett_lrv(&values, hac_lag)?;
        diagnostics.push(BlockDiagnostic {
            representation,
            fold_id: fold,
            model_state_id,
            session_count: rows.len(),
            calendar_start: rows.first().unwrap().civil_date.clone(),
            calendar_end: rows.last().unwrap().civil_date.clone(),
            offset_plus120: rows.iter().filter(|row| row.offset == 120).count(),
            offset_plus180: rows.iter().filter(|row| row.offset == 180).count(),
            mean: moments.0,
            variance: moments.1,
            minimum: moments.2,
            maximum: moments.3,
            skewness: moments.4,
            excess_kurtosis: moments.5,
            acf,
            hac_lag,
            long_run_variance: lrv,
        });
    }
    diagnostics.sort_by(|a, b| {
        a.representation
            .cmp(&b.representation)
            .then(a.fold_id.cmp(&b.fold_id))
    });
    if diagnostics.len() != 8 {
        return Err(format!(
            "DIAGNOSTIC_BLOCK_COUNT_DRIFT:{}",
            diagnostics.len()
        ));
    }
    let criteria = vec![
        "four fixed-model validation blocks per representation".into(),
        "at least 25 complete sessions in every block".into(),
        "finite positive within-block variance and Bartlett long-run variance".into(),
        "absolute lag-1 ACF below 0.80 in every block".into(),
        "within-representation maximum/minimum block variance ratio no greater than 25".into(),
    ];
    let mut failed = Vec::new();
    for representation in ["RAW", "Z"] {
        let selected = diagnostics
            .iter()
            .filter(|x| x.representation == representation)
            .collect::<Vec<_>>();
        if selected.len() != 4 {
            failed.push(format!("{representation}:FIXED_MODEL_BLOCK_COUNT"));
            continue;
        }
        if selected.iter().any(|x| x.session_count < 25) {
            failed.push(format!("{representation}:BLOCK_SUPPORT"));
        }
        if selected.iter().any(|x| {
            !(x.variance.is_finite()
                && x.variance > 1e-15
                && x.long_run_variance.is_finite()
                && x.long_run_variance > 1e-15)
        }) {
            failed.push(format!("{representation}:NONPOSITIVE_VARIANCE"));
        }
        if selected
            .iter()
            .any(|x| x.acf.first().is_some_and(|v| v.abs() >= 0.80))
        {
            failed.push(format!("{representation}:LAG1_ACF"));
        }
        let min_variance = selected
            .iter()
            .map(|x| x.variance)
            .fold(f64::INFINITY, f64::min);
        let max_variance = selected.iter().map(|x| x.variance).fold(0.0, f64::max);
        if max_variance / min_variance > 25.0 {
            failed.push(format!("{representation}:VARIANCE_RATIO"));
        }
    }
    let compatible = failed.is_empty();
    Ok(DependenceQualification {
        diagnostics,
        compatible,
        criteria,
        failed_criteria: failed,
        selected_method: if compatible {
            "HAC_BARTLETT_AUTOMATIC_LAG_V1"
        } else {
            "NONE"
        }
        .into(),
        selection_state: if compatible {
            "PROCEDURE_SELECTED"
        } else {
            "FORMAL_INFERENCE_NOT_EVALUABLE"
        }
        .into(),
        d_a_proves_d_b_assumptions: false,
    })
}

pub fn automatic_hac_lag(n: usize) -> usize {
    if n < 2 {
        return 0;
    }
    ((4.0 * (n as f64 / 100.0).powf(2.0 / 9.0)).floor() as usize).min(n - 1)
}

pub fn bartlett_lrv(values: &[f64], lag: usize) -> Result<f64, String> {
    if values.len() < 2 || lag >= values.len() || values.iter().any(|x| !x.is_finite()) {
        return Err("INVALID_LRV_INPUT".into());
    }
    let mean = simd_sum(values) / values.len() as f64;
    let mut lrv = covariance(values, mean, 0);
    for j in 1..=lag {
        lrv += 2.0 * (1.0 - j as f64 / (lag + 1) as f64) * covariance(values, mean, j);
    }
    Ok(lrv)
}

fn autocorrelation(values: &[f64], lag: usize) -> Result<f64, String> {
    let mean = simd_sum(values) / values.len() as f64;
    let zero = covariance(values, mean, 0);
    if zero <= 0.0 {
        return Err("NONPOSITIVE_ACF_VARIANCE".into());
    }
    Ok(covariance(values, mean, lag) / zero)
}

fn covariance(values: &[f64], mean: f64, lag: usize) -> f64 {
    values[lag..]
        .iter()
        .zip(&values[..values.len() - lag])
        .map(|(a, b)| (a - mean) * (b - mean))
        .sum::<f64>()
        / values.len() as f64
}

fn moments(values: &[f64]) -> Result<(f64, f64, f64, f64, f64, f64), String> {
    if values.len() < 4 || values.iter().any(|x| !x.is_finite()) {
        return Err("INVALID_MOMENT_INPUT".into());
    }
    let mean = simd_sum(values) / values.len() as f64;
    let mut m2 = 0.0;
    let mut m3 = 0.0;
    let mut m4 = 0.0;
    let mut min = f64::INFINITY;
    let mut max = f64::NEG_INFINITY;
    for &x in values {
        let d = x - mean;
        let d2 = d * d;
        m2 += d2;
        m3 += d2 * d;
        m4 += d2 * d2;
        min = min.min(x);
        max = max.max(x);
    }
    let n = values.len() as f64;
    let variance = m2 / (n - 1.0);
    let pop = m2 / n;
    let skew = if pop > 0.0 {
        (m3 / n) / pop.powf(1.5)
    } else {
        0.0
    };
    let kurt = if pop > 0.0 {
        (m4 / n) / (pop * pop) - 3.0
    } else {
        0.0
    };
    Ok((mean, variance, min, max, skew, kurt))
}

fn simd_sum(values: &[f64]) -> f64 {
    let mut chunks = values.chunks_exact(4);
    let mut lanes = f64x4::ZERO;
    for chunk in &mut chunks {
        lanes += f64x4::from([chunk[0], chunk[1], chunk[2], chunk[3]]);
    }
    lanes.to_array().into_iter().sum::<f64>() + chunks.remainder().iter().sum::<f64>()
}

pub fn method_assessments(selected: bool) -> Vec<MethodAssessment> {
    vec![
        MethodAssessment {
            method: "HAC_BARTLETT_AUTOMATIC_LAG_V1",
            target_parameter: "mu_R=E[d_s^R]",
            stochastic_assumptions: vec![
                "fixed forecast models across evaluation",
                "covariance-stationary score-difference process",
                "finite 2+delta moments",
                "weak dependence with summable autocovariances",
                "positive finite long-run variance",
            ],
            stationarity_requirement: "COVARIANCE_STATIONARY_D_B_SCORE_DIFFERENCE_PROCESS",
            dependence_requirement: "WEAK_DEPENDENCE_SUPPORTING_HAC_CLT",
            authority: "ASYMPTOTIC_NORMAL",
            nuisance_parameters: vec!["Bartlett kernel", "lag=floor(4*(N/100)^(2/9))"],
            effective_sample_requirement: "N>=80 and both offset regimes >=20",
            failure_modes: vec![
                "nonpositive or nonfinite LRV",
                "support failure",
                "forecast state changes during evaluation",
                "assumption transport not scientifically admitted",
            ],
            selection_state: if selected {
                "SELECTED"
            } else {
                "NOT_SELECTED_INCOMPATIBLE_D_A_MORPHOLOGY"
            },
            reason: "Targets the unconditional mean directly; automatic lag is outcome-value independent; D_A blocks can expose obvious incompatibility without selecting by representation p-value.",
        },
        MethodAssessment {
            method: "DEPENDENT_WILD_BOOTSTRAP",
            target_parameter: "mu_R=E[d_s^R]",
            stochastic_assumptions: vec![
                "stationary time series",
                "smooth-function/distribution approximation conditions",
                "valid dependence-kernel and bandwidth",
            ],
            stationarity_requirement: "STATIONARY",
            dependence_requirement: "DWB_KERNEL_DEPENDENCE_MODEL",
            authority: "ASYMPTOTIC_BOOTSTRAP_APPROXIMATION",
            nuisance_parameters: vec![
                "dependent multiplier kernel",
                "bandwidth",
                "bootstrap draws",
            ],
            effective_sample_requirement: "Not independently qualified for four short D_A blocks",
            failure_modes: vec![
                "bandwidth transport",
                "nonstationarity",
                "small effective block support",
            ],
            selection_state: "DEFERRED_NOT_SELECTED",
            reason: "Mathematically admissible candidate, but adds an unqualified bandwidth/multiplier layer that the short fixed-model blocks do not identify.",
        },
        MethodAssessment {
            method: "STATIONARY_OR_MOVING_BLOCK_BOOTSTRAP",
            target_parameter: "mu_R=E[d_s^R]",
            stochastic_assumptions: vec![
                "stationary or locally stationary weakly dependent series as specified",
                "valid block-length sequence",
            ],
            stationarity_requirement: "METHOD_SPECIFIC_STATIONARITY",
            dependence_requirement: "BLOCK_RESAMPLING_APPROXIMATION",
            authority: "ASYMPTOTIC_BOOTSTRAP_APPROXIMATION",
            nuisance_parameters: vec![
                "block construction",
                "block length",
                "boundary policy",
                "bootstrap draws",
            ],
            effective_sample_requirement: "Not independently qualified for four short D_A blocks",
            failure_modes: vec![
                "block length instability",
                "few effective blocks",
                "nonstationarity",
            ],
            selection_state: "DEFERRED_NOT_SELECTED",
            reason: "No outcome-blind block-length authority is earned by the available short pseudo-D_B blocks.",
        },
        MethodAssessment {
            method: "NATURAL_CALENDAR_CLUSTER",
            target_parameter: "mu_R=E[d_s^R]",
            stochastic_assumptions: vec![
                "independence or suitable asymptotics across calendar clusters",
                "arbitrary dependence within clusters",
            ],
            stationarity_requirement: "NOT_NECESSARILY",
            dependence_requirement: "VALID_CLUSTER_PARTITION_AND_ENOUGH_CLUSTERS",
            authority: "ASYMPTOTIC_CLUSTER_ROBUST",
            nuisance_parameters: vec!["calendar cluster definition"],
            effective_sample_requirement: "Sufficient independent clusters not established prospectively for D_B",
            failure_modes: vec![
                "few clusters",
                "cross-cluster dependence",
                "calendar boundaries lack stochastic meaning",
            ],
            selection_state: "DEFERRED_NOT_SELECTED",
            reason: "Calendar boundaries are available but do not themselves establish independent inference units.",
        },
    ]
}
