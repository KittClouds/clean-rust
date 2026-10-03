use crate::model_state::Predictions;
use libm::erfc;
use obs_open_03bp2::dependence::automatic_hac_lag;
use obs_open_03bp2::model::{RANGE_COUNT, SessionRows};
use serde::Serialize;
use wide::f64x4;

#[derive(Debug, Clone, Serialize)]
pub struct PredictionRow {
    pub session_id: String,
    pub civil_date: String,
    pub offset: i32,
    pub d_b_selected_ordinal: usize,
    pub k: usize,
    pub target: f64,
    pub design_probability: f64,
    pub raw_probability: f64,
    pub z_probability: f64,
    pub estimand_unit: String,
    pub row_independence_authority: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct SessionScore {
    pub session_id: String,
    pub civil_date: String,
    pub offset: i32,
    pub d_b_selected_ordinal: usize,
    pub design_brier: f64,
    pub raw_brier: f64,
    pub z_brier: f64,
    pub raw_difference: f64,
    pub z_difference: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct CovarianceTerm {
    pub lag: usize,
    pub autocovariance: f64,
    pub bartlett_weight: f64,
    pub weighted_lrv_contribution: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct InferenceReceipt {
    pub representation: String,
    pub n: usize,
    pub hac_lag: usize,
    pub mean_paired_difference: f64,
    pub ordinary_sample_variance: f64,
    pub autocovariance_terms: Vec<CovarianceTerm>,
    pub hac_long_run_variance: f64,
    pub hac_standard_error: f64,
    pub statistic: f64,
    pub raw_one_sided_p: f64,
    pub holm_rank: usize,
    pub holm_threshold: f64,
    pub holm_state: String,
    pub formal_state: String,
    pub inference_authority: String,
    pub temporal_index: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct RepresentationResult {
    pub representation: String,
    pub brier: f64,
    pub baseline_brier: f64,
    pub delta_brier: f64,
    pub relative_skill: f64,
    pub materiality_state: String,
    pub formal_inference_state: String,
    pub combined_epistemic_state: String,
    pub inference: InferenceReceipt,
}

#[derive(Debug, Clone, Serialize)]
pub struct PrimaryResult {
    pub prediction_rows: Vec<PredictionRow>,
    pub session_scores: Vec<SessionScore>,
    pub baseline_brier: f64,
    pub raw: RepresentationResult,
    pub z: RepresentationResult,
    pub tournament_state: String,
}

pub fn execute(sessions: &[SessionRows], pred: &Predictions) -> Result<PrimaryResult, String> {
    let expected = sessions.len() * RANGE_COUNT;
    if pred.design.len() != expected || pred.raw.len() != expected || pred.z.len() != expected {
        return Err("PREDICTION_SHAPE_DRIFT".into());
    }
    let mut prediction_rows = Vec::with_capacity(expected);
    let mut scores = Vec::with_capacity(sessions.len());
    for (si, s) in sessions.iter().enumerate() {
        let mut sums = [0.0; 3];
        for k in 0..RANGE_COUNT {
            let i = si * RANGE_COUNT + k;
            let y = s.targets[k];
            let ps = [pred.design[i], pred.raw[i], pred.z[i]];
            if ps.iter().any(|x| !x.is_finite()) {
                return Err("NONFINITE_PREDICTION".into());
            }
            for a in 0..3 {
                let e = ps[a] - y;
                sums[a] += e * e;
            }
            prediction_rows.push(PredictionRow {
                session_id: s.session_id.clone(),
                civil_date: s.civil_date.clone(),
                offset: s.offset,
                d_b_selected_ordinal: s.session_index + 1,
                k: k + 1,
                target: y,
                design_probability: ps[0],
                raw_probability: ps[1],
                z_probability: ps[2],
                estimand_unit: "SESSION".into(),
                row_independence_authority: false,
            });
        }
        for x in &mut sums {
            *x /= RANGE_COUNT as f64;
        }
        if sums.iter().any(|x| !x.is_finite()) || sums[0] <= 0.0 {
            return Err("INVALID_BRIER_RUNTIME".into());
        }
        scores.push(SessionScore {
            session_id: s.session_id.clone(),
            civil_date: s.civil_date.clone(),
            offset: s.offset,
            d_b_selected_ordinal: s.session_index + 1,
            design_brier: sums[0],
            raw_brier: sums[1],
            z_brier: sums[2],
            raw_difference: sums[0] - sums[1],
            z_difference: sums[0] - sums[2],
        });
    }
    scores.sort_unstable_by_key(|x| x.d_b_selected_ordinal);
    let b0 = mean(&scores.iter().map(|x| x.design_brier).collect::<Vec<_>>());
    let br = mean(&scores.iter().map(|x| x.raw_brier).collect::<Vec<_>>());
    let bz = mean(&scores.iter().map(|x| x.z_brier).collect::<Vec<_>>());
    if !(b0.is_finite() && b0 > 0.0 && br.is_finite() && bz.is_finite()) {
        return Err("INVALID_AGGREGATE_BRIER".into());
    }
    let raw_d = scores.iter().map(|x| x.raw_difference).collect::<Vec<_>>();
    let z_d = scores.iter().map(|x| x.z_difference).collect::<Vec<_>>();
    let mut raw_inf = hac("RAW", &raw_d)?;
    let mut z_inf = hac("Z", &z_d)?;
    apply_holm(&mut raw_inf, &mut z_inf);
    let raw = representation_result("RAW", b0, br, raw_inf);
    let z = representation_result("Z", b0, bz, z_inf);
    let raw_pays = raw.combined_epistemic_state == "REPRESENTATION_PAYS_RENT";
    let z_pays = z.combined_epistemic_state == "REPRESENTATION_PAYS_RENT";
    let tournament_state = match (raw_pays, z_pays) {
        (true, true) => "BOTH_PAY_RENT",
        (true, false) => "RAW_ONLY_PAYS_RENT",
        (false, true) => "Z_ONLY_PAYS_RENT",
        (false, false) if raw.combined_epistemic_state == z.combined_epistemic_state => {
            "NEITHER_PAYS_RENT"
        }
        _ => "MIXED_EPISTEMIC_STATE",
    }
    .into();
    Ok(PrimaryResult {
        prediction_rows,
        session_scores: scores,
        baseline_brier: b0,
        raw,
        z,
        tournament_state,
    })
}

fn representation_result(
    name: &str,
    b0: f64,
    b: f64,
    inf: InferenceReceipt,
) -> RepresentationResult {
    let skill = 1.0 - b / b0;
    let material = if skill >= 0.02 { "PASS" } else { "FAIL" };
    let formal = inf.formal_state.clone();
    let combined = match (material, formal.as_str()) {
        ("PASS", "PASS") => "REPRESENTATION_PAYS_RENT",
        ("FAIL", "PASS") => "STATISTICAL_BUT_SUBMATERIAL",
        ("PASS", "FAIL") => "MATERIAL_ON_DB_NOT_FORMALLY_SUPPORTED",
        ("PASS", "NOT_EVALUABLE") => "MATERIAL_ON_DB_FORMAL_INFERENCE_NOT_EVALUABLE",
        _ => "DOES_NOT_PAY_RENT",
    };
    RepresentationResult {
        representation: name.into(),
        brier: b,
        baseline_brier: b0,
        delta_brier: b0 - b,
        relative_skill: skill,
        materiality_state: material.into(),
        formal_inference_state: formal,
        combined_epistemic_state: combined.into(),
        inference: inf,
    }
}

fn hac(name: &str, values: &[f64]) -> Result<InferenceReceipt, String> {
    let n = values.len();
    let lag = automatic_hac_lag(n);
    let mu = mean(values);
    let var = values.iter().map(|x| (x - mu).powi(2)).sum::<f64>() / (n - 1) as f64;
    let mut terms = Vec::with_capacity(lag + 1);
    let g0 = cov(values, mu, 0);
    terms.push(CovarianceTerm {
        lag: 0,
        autocovariance: g0,
        bartlett_weight: 1.0,
        weighted_lrv_contribution: g0,
    });
    let mut lrv = g0;
    for j in 1..=lag {
        let g = cov(values, mu, j);
        let w = 1.0 - j as f64 / (lag + 1) as f64;
        let c = 2.0 * w * g;
        lrv += c;
        terms.push(CovarianceTerm {
            lag: j,
            autocovariance: g,
            bartlett_weight: w,
            weighted_lrv_contribution: c,
        });
    }
    if !(lrv.is_finite() && lrv > 0.0) {
        return Err(format!("NONPOSITIVE_OR_NONFINITE_LRV:{name}"));
    }
    let se = (lrv / n as f64).sqrt();
    if !(se.is_finite() && se > 0.0) {
        return Err("NONFINITE_STANDARD_ERROR".into());
    }
    let statistic = mu / se;
    let p = 0.5 * erfc(statistic / std::f64::consts::SQRT_2);
    Ok(InferenceReceipt {
        representation: name.into(),
        n,
        hac_lag: lag,
        mean_paired_difference: mu,
        ordinary_sample_variance: var,
        autocovariance_terms: terms,
        hac_long_run_variance: lrv,
        hac_standard_error: se,
        statistic,
        raw_one_sided_p: p,
        holm_rank: 0,
        holm_threshold: f64::NAN,
        holm_state: "PENDING".into(),
        formal_state: "PENDING".into(),
        inference_authority: "ASYMPTOTIC_MODEL_BASED".into(),
        temporal_index: "SELECTED_DB_SESSION_ORDINAL".into(),
    })
}
fn apply_holm(raw: &mut InferenceReceipt, z: &mut InferenceReceipt) {
    let raw_first = raw.raw_one_sided_p <= z.raw_one_sided_p;
    let (first, second) = if raw_first { (raw, z) } else { (z, raw) };
    first.holm_rank = 1;
    first.holm_threshold = 0.025;
    if first.raw_one_sided_p <= 0.025 {
        first.holm_state = "PASS".into();
        first.formal_state = "PASS".into();
        second.holm_rank = 2;
        second.holm_threshold = 0.05;
        if second.raw_one_sided_p <= 0.05 {
            second.holm_state = "PASS".into();
            second.formal_state = "PASS".into();
        } else {
            second.holm_state = "FAIL".into();
            second.formal_state = "FAIL".into();
        }
    } else {
        first.holm_state = "FAIL".into();
        first.formal_state = "FAIL".into();
        second.holm_rank = 2;
        second.holm_threshold = 0.05;
        second.holm_state = "FAIL_STEP_DOWN".into();
        second.formal_state = "FAIL".into();
    }
}
fn cov(x: &[f64], m: f64, lag: usize) -> f64 {
    x[lag..]
        .iter()
        .zip(&x[..x.len() - lag])
        .map(|(a, b)| (a - m) * (b - m))
        .sum::<f64>()
        / x.len() as f64
}
fn mean(x: &[f64]) -> f64 {
    let mut chunks = x.chunks_exact(4);
    let mut acc = f64x4::splat(0.0);
    for c in &mut chunks {
        acc += f64x4::new([c[0], c[1], c[2], c[3]]);
    }
    let sum = acc.to_array().iter().sum::<f64>() + chunks.remainder().iter().sum::<f64>();
    sum / x.len() as f64
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn holm_step_down() {
        let mut a = hac("A", &[1., 2., 1., 2., 1., 2.]).unwrap();
        let mut b = hac("B", &[1., 1., 2., 2., 1., 2.]).unwrap();
        apply_holm(&mut a, &mut b);
        assert!(a.holm_rank > 0 && b.holm_rank > 0);
    }
}
