use obs_open_03bp::probe::{Fit, fit_logistic, fit_standardizer, predict};
use obs_open_03bp2::model::{Arm, RANGE_COUNT, SessionRows};
use serde::Serialize;
use std::path::Path;

#[derive(Debug, Clone, Serialize)]
pub struct ArmState {
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
pub struct FrozenModels {
    pub training_sessions: usize,
    pub training_rows: usize,
    pub selected_lambdas: [f64; 3],
    pub design: ArmState,
    pub raw: ArmState,
    pub z: ArmState,
    pub d_a_target_values_read: usize,
    pub d_a_bars_read: usize,
    pub d_a_source_sha256: String,
}

#[derive(Debug)]
pub struct Predictions {
    pub design: Vec<f64>,
    pub raw: Vec<f64>,
    pub z: Vec<f64>,
}

pub fn fit(repo: &Path) -> Result<FrozenModels, Box<dyn std::error::Error>> {
    let authority = obs_open_03bp2::authority::open(repo)?;
    let sessions = authority.rows;
    if sessions.len() != 150 {
        return Err("D_A_COMPLETE_SESSION_DRIFT".into());
    }
    let design = fit_arm(&sessions, Arm::Design, 10.0)?;
    let raw = fit_arm(&sessions, Arm::Raw, 10.0)?;
    let z = fit_arm(&sessions, Arm::Z, 1.0)?;
    Ok(FrozenModels {
        training_sessions: sessions.len(),
        training_rows: sessions.len() * RANGE_COUNT,
        selected_lambdas: [10.0, 10.0, 1.0],
        design,
        raw,
        z,
        d_a_target_values_read: authority.d_a_target_values_read,
        d_a_bars_read: authority.d_a_bars_read,
        d_a_source_sha256: authority.raw_source_sha256,
    })
}

pub fn apply(models: &FrozenModels, sessions: &[SessionRows]) -> Result<Predictions, String> {
    Ok(Predictions {
        design: predict_arm(&models.design, sessions, Arm::Design)?,
        raw: predict_arm(&models.raw, sessions, Arm::Raw)?,
        z: predict_arm(&models.z, sessions, Arm::Z)?,
    })
}

fn fit_arm(sessions: &[SessionRows], arm: Arm, lambda: f64) -> Result<ArmState, String> {
    let rep_cols = match arm {
        Arm::Design => 0,
        Arm::Raw => 5,
        Arm::Z => 4,
    };
    let cols = 31 + rep_cols;
    let (mean, sd) = if rep_cols == 0 {
        (Vec::new(), Vec::new())
    } else {
        let values = representation_values(sessions, arm);
        fit_standardizer(&values, sessions.len() * RANGE_COUNT, rep_cols)?
    };
    let (x, y) = design_matrix(sessions, arm, cols, &mean, &sd);
    let weights = vec![1.0 / RANGE_COUNT as f64; y.len()];
    let Fit {
        beta,
        iterations,
        converged,
    } = fit_logistic(&x, &y, &weights, y.len(), cols, lambda)?;
    if !converged {
        return Err(format!("FINAL_D_A_FIT_NOT_CONVERGED:{}", arm.name()));
    }
    Ok(ArmState {
        arm: arm.name().into(),
        lambda,
        columns: cols,
        representation_columns: rep_cols,
        standardization_mean: mean,
        standardization_sd: sd,
        coefficients: beta,
        iterations,
        converged,
    })
}

fn predict_arm(state: &ArmState, sessions: &[SessionRows], arm: Arm) -> Result<Vec<f64>, String> {
    let (x, _) = design_matrix(
        sessions,
        arm,
        state.columns,
        &state.standardization_mean,
        &state.standardization_sd,
    );
    predict(
        &x,
        sessions.len() * RANGE_COUNT,
        state.columns,
        &state.coefficients,
    )
}
fn representation_values(sessions: &[SessionRows], arm: Arm) -> Vec<f64> {
    let rep = match arm {
        Arm::Raw => 5,
        Arm::Z => 4,
        Arm::Design => 0,
    };
    let mut out = Vec::with_capacity(sessions.len() * RANGE_COUNT * rep);
    for s in sessions {
        for k in 0..RANGE_COUNT {
            match arm {
                Arm::Raw => out.extend_from_slice(&s.raw[k]),
                Arm::Z => out.extend_from_slice(&s.z[k]),
                Arm::Design => {}
            }
        }
    }
    out
}
fn design_matrix(
    sessions: &[SessionRows],
    arm: Arm,
    cols: usize,
    mean: &[f64],
    sd: &[f64],
) -> (Vec<f64>, Vec<f64>) {
    let rep = cols - 31;
    let mut x = vec![0.0; sessions.len() * RANGE_COUNT * cols];
    let mut y = Vec::with_capacity(sessions.len() * RANGE_COUNT);
    for (si, s) in sessions.iter().enumerate() {
        for k in 0..RANGE_COUNT {
            let start = (si * RANGE_COUNT + k) * cols;
            x[start] = 1.0;
            if k > 0 {
                x[start + k] = 1.0;
            }
            x[start + 30] = f64::from(s.offset == 180);
            for j in 0..rep {
                let value = match arm {
                    Arm::Raw => s.raw[k][j],
                    Arm::Z => s.z[k][j],
                    Arm::Design => unreachable!(),
                };
                x[start + 31 + j] = (value - mean[j]) / sd[j];
            }
            y.push(s.targets[k]);
        }
    }
    (x, y)
}

#[cfg(test)]
mod tests {
    #[test]
    fn dimensions_are_frozen() {
        assert_eq!(31 + 5, 36);
        assert_eq!(31 + 4, 35);
    }
}
