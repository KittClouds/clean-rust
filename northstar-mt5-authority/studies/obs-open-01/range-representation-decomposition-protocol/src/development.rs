use crate::algebra::{Arm, feature_value, features};
use hashbrown::HashMap;
use obs_open_03bp::probe::{fit_logistic, fit_standardizer, predict};
use obs_open_03bp2::model::{LAMBDAS, RANGE_COUNT, SessionRows};
use serde::Serialize;

const FOLDS: [(usize, usize); 4] = [(30, 31), (61, 31), (92, 31), (123, 31)];

#[derive(Debug, Clone, Serialize)]
pub struct Selection {
    pub arm: String,
    pub lambda: f64,
    pub validation_brier: f64,
    pub validation_sessions: usize,
}
#[derive(Debug, Clone, Serialize)]
pub struct ModelState {
    pub arm: String,
    pub lambda: f64,
    pub columns: usize,
    pub representation_columns: usize,
    pub standardization_mean: Vec<f64>,
    pub standardization_sd: Vec<f64>,
    pub coefficients: Vec<f64>,
    pub iterations: usize,
    pub converged: bool,
}
#[derive(Debug, Clone, Serialize)]
pub struct Development {
    pub complete_sessions: usize,
    pub target_rows: usize,
    pub fold_validation_sessions: [usize; 4],
    pub lambda_grid: [f64; 6],
    pub selections: Vec<Selection>,
    pub final_models: Vec<ModelState>,
    pub parent_raw_selection_reproduced: bool,
    pub parent_z_selection_reproduced: bool,
    #[serde(rename = "D_B_new_scores")]
    pub d_b_new_scores: usize,
    #[serde(rename = "D_C_accesses")]
    pub d_c_accesses: usize,
}
#[derive(Clone)]
struct Score {
    arm: Arm,
    lambda_index: usize,
    brier: f64,
}

pub fn qualify(rows: &[SessionRows]) -> Result<Development, String> {
    let by = rows
        .iter()
        .map(|s| (s.session_index, s))
        .collect::<HashMap<_, _>>();
    let mut scores = Vec::new();
    let mut counts = [0usize; 4];
    for (fi, (start, len)) in FOLDS.into_iter().enumerate() {
        let train = (0..start)
            .filter_map(|i| by.get(&i).copied())
            .collect::<Vec<_>>();
        let valid = (start..start + len)
            .filter_map(|i| by.get(&i).copied())
            .collect::<Vec<_>>();
        if train.len() < 25 || valid.len() < 25 {
            return Err("D_A_FOLD_SUPPORT".into());
        }
        counts[fi] = valid.len();
        for arm in [Arm::Z, Arm::Zw, Arm::Raw, Arm::Rawz] {
            let m = matrices(&train, &valid, arm)?;
            for (li, lambda) in LAMBDAS.into_iter().enumerate() {
                let fit = fit_logistic(&m.tx, &m.ty, &m.weights, m.ty.len(), m.cols, lambda)?;
                if !fit.converged {
                    return Err(format!("D_A_FOLD_FIT_FAILURE:{}:{fi}:{lambda}", arm.name()));
                }
                let p = predict(&m.vx, m.vy.len(), m.cols, &fit.beta)?;
                for s in 0..valid.len() {
                    let lo = s * RANGE_COUNT;
                    let hi = lo + RANGE_COUNT;
                    let b = p[lo..hi]
                        .iter()
                        .zip(&m.vy[lo..hi])
                        .map(|(a, y)| (a - y) * (a - y))
                        .sum::<f64>()
                        / RANGE_COUNT as f64;
                    scores.push(Score {
                        arm,
                        lambda_index: li,
                        brier: b,
                    });
                }
            }
        }
    }
    let mut selections = Vec::new();
    let mut final_models = Vec::new();
    for arm in [Arm::Z, Arm::Zw, Arm::Raw, Arm::Rawz] {
        let mut candidates = Vec::new();
        for li in 0..LAMBDAS.len() {
            let v = scores
                .iter()
                .filter(|x| x.arm == arm && x.lambda_index == li)
                .map(|x| x.brier)
                .collect::<Vec<_>>();
            if v.len() != counts.iter().sum::<usize>() {
                return Err("VALIDATION_SCORE_COUNT".into());
            }
            candidates.push((li, v.iter().sum::<f64>() / v.len() as f64, v.len()));
        }
        candidates.sort_by(|a, b| a.1.total_cmp(&b.1).then_with(|| b.0.cmp(&a.0)));
        let best_value = candidates[0].1;
        let best = *candidates
            .iter()
            .filter(|x| (x.1 - best_value).abs() <= 1e-12)
            .max_by_key(|x| x.0)
            .unwrap();
        let lambda = LAMBDAS[best.0];
        selections.push(Selection {
            arm: arm.name().into(),
            lambda,
            validation_brier: best.1,
            validation_sessions: best.2,
        });
        final_models.push(final_fit(rows, arm, lambda)?);
    }
    let raw = selections.iter().find(|x| x.arm == "RAW").unwrap();
    let z = selections.iter().find(|x| x.arm == "Z").unwrap();
    let raw_ok = raw.lambda == 10.0 && (raw.validation_brier - 0.23153923808998525).abs() <= 1e-15;
    let z_ok = z.lambda == 1.0 && (z.validation_brier - 0.22797617811887166).abs() <= 1e-15;
    if !raw_ok || !z_ok {
        return Err("PARENT_SELECTION_REPRODUCTION_FAILURE".into());
    }
    Ok(Development {
        complete_sessions: rows.len(),
        target_rows: rows.len() * RANGE_COUNT,
        fold_validation_sessions: counts,
        lambda_grid: LAMBDAS,
        selections,
        final_models,
        parent_raw_selection_reproduced: raw_ok,
        parent_z_selection_reproduced: z_ok,
        d_b_new_scores: 0,
        d_c_accesses: 0,
    })
}

struct Matrices {
    tx: Vec<f64>,
    ty: Vec<f64>,
    weights: Vec<f64>,
    vx: Vec<f64>,
    vy: Vec<f64>,
    cols: usize,
}
fn matrices(train: &[&SessionRows], valid: &[&SessionRows], arm: Arm) -> Result<Matrices, String> {
    let rep = arm.columns();
    let values = representation_values(train, arm);
    let (mean, sd) = fit_standardizer(&values, train.len() * RANGE_COUNT, rep)?;
    let cols = 31 + rep;
    let (tx, ty) = design(train, arm, cols, &mean, &sd);
    let (vx, vy) = design(valid, arm, cols, &mean, &sd);
    let weights = vec![1.0 / RANGE_COUNT as f64; ty.len()];
    Ok(Matrices {
        tx,
        ty,
        weights,
        vx,
        vy,
        cols,
    })
}
fn final_fit(rows: &[SessionRows], arm: Arm, lambda: f64) -> Result<ModelState, String> {
    let refs = rows.iter().collect::<Vec<_>>();
    let values = representation_values(&refs, arm);
    let rep = arm.columns();
    let (mean, sd) = fit_standardizer(&values, rows.len() * RANGE_COUNT, rep)?;
    let cols = 31 + rep;
    let (x, y) = design(&refs, arm, cols, &mean, &sd);
    let w = vec![1.0 / RANGE_COUNT as f64; y.len()];
    let fit = fit_logistic(&x, &y, &w, y.len(), cols, lambda)?;
    if !fit.converged {
        return Err("FINAL_FIT_FAILURE".into());
    }
    Ok(ModelState {
        arm: arm.name().into(),
        lambda,
        columns: cols,
        representation_columns: rep,
        standardization_mean: mean,
        standardization_sd: sd,
        coefficients: fit.beta,
        iterations: fit.iterations,
        converged: fit.converged,
    })
}
fn representation_values(rows: &[&SessionRows], arm: Arm) -> Vec<f64> {
    let mut out = Vec::with_capacity(rows.len() * RANGE_COUNT * arm.columns());
    for s in rows {
        for k in 0..RANGE_COUNT {
            features(s, k, arm, &mut out);
        }
    }
    out
}
fn design(
    rows: &[&SessionRows],
    arm: Arm,
    cols: usize,
    mean: &[f64],
    sd: &[f64],
) -> (Vec<f64>, Vec<f64>) {
    let mut x = vec![0.0; rows.len() * RANGE_COUNT * cols];
    let mut y = Vec::with_capacity(rows.len() * RANGE_COUNT);
    for (si, s) in rows.iter().enumerate() {
        for k in 0..RANGE_COUNT {
            let o = (si * RANGE_COUNT + k) * cols;
            x[o] = 1.0;
            if k > 0 {
                x[o + k] = 1.0;
            }
            x[o + 30] = f64::from(s.offset == 180);
            for j in 0..arm.columns() {
                x[o + 31 + j] = (feature_value(s, k, arm, j) - mean[j]) / sd[j];
            }
            y.push(s.targets[k]);
        }
    }
    (x, y)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn folds_are_frozen() {
        assert_eq!(FOLDS, [(30, 31), (61, 31), (92, 31), (123, 31)]);
    }
}
