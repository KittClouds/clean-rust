use crate::model::*;
use hashbrown::HashMap;
use obs_open_03bp::probe::{fit_logistic, fit_standardizer, predict};

const FOLDS: [(usize, usize); 4] = [(30, 31), (61, 31), (92, 31), (123, 31)];

#[derive(Debug)]
pub struct PseudoDbResult {
    pub score_rows: Vec<ScoreRow>,
    pub selected_lambdas: Vec<SelectedLambda>,
    pub complete_sessions: usize,
    pub validation_sessions: usize,
    pub fold_session_counts: [usize; 4],
}

#[derive(Debug, Clone)]
struct FoldScore {
    fold: u8,
    arm: Arm,
    lambda_index: usize,
    session_index: usize,
    brier: f64,
}

pub fn construct(sessions: &[SessionRows]) -> Result<PseudoDbResult, String> {
    let by_index = sessions
        .iter()
        .map(|s| (s.session_index, s))
        .collect::<HashMap<_, _>>();
    let mut fold_scores = Vec::with_capacity(4 * 3 * LAMBDAS.len() * 31);
    let mut fold_session_counts = [0usize; 4];
    for (fold_index, &(validation_start, validation_len)) in FOLDS.iter().enumerate() {
        let training = (0..validation_start)
            .filter_map(|index| by_index.get(&index).copied())
            .collect::<Vec<_>>();
        let validation = (validation_start..validation_start + validation_len)
            .filter_map(|index| by_index.get(&index).copied())
            .collect::<Vec<_>>();
        if training.len() < 25 || validation.len() < 25 {
            return Err(format!(
                "PSEUDO_DB_FOLD_SUPPORT:{}:{}",
                training.len(),
                validation.len()
            ));
        }
        fold_session_counts[fold_index] = validation.len();
        for arm in [Arm::Design, Arm::Raw, Arm::Z] {
            let matrices = matrices(&training, &validation, arm)?;
            for (lambda_index, &lambda) in LAMBDAS.iter().enumerate() {
                let fit = fit_logistic(
                    &matrices.train_x,
                    &matrices.train_y,
                    &matrices.weights,
                    matrices.train_y.len(),
                    matrices.cols,
                    lambda,
                )?;
                if !fit.converged {
                    continue;
                }
                let predictions = predict(
                    &matrices.valid_x,
                    matrices.valid_y.len(),
                    matrices.cols,
                    &fit.beta,
                )?;
                for (session_position, session) in validation.iter().enumerate() {
                    let start = session_position * RANGE_COUNT;
                    let end = start + RANGE_COUNT;
                    fold_scores.push(FoldScore {
                        fold: (fold_index + 1) as u8,
                        arm,
                        lambda_index,
                        session_index: session.session_index,
                        brier: brier(&predictions[start..end], &matrices.valid_y[start..end]),
                    });
                }
            }
        }
    }
    let selected_lambdas = select_lambdas(&fold_scores)?;
    let selection = selected_lambdas
        .iter()
        .map(|s| {
            let arm = match s.arm.as_str() {
                "DESIGN" => Arm::Design,
                "RAW" => Arm::Raw,
                "Z" => Arm::Z,
                _ => unreachable!(),
            };
            (arm, LAMBDAS.iter().position(|x| *x == s.lambda).unwrap())
        })
        .collect::<HashMap<_, _>>();
    let selected_scores = fold_scores
        .iter()
        .filter(|score| selection.get(&score.arm) == Some(&score.lambda_index))
        .map(|score| ((score.fold, score.arm, score.session_index), score.brier))
        .collect::<HashMap<_, _>>();
    let mut score_rows = Vec::new();
    for (fold_index, &(start, len)) in FOLDS.iter().enumerate() {
        let fold = (fold_index + 1) as u8;
        for session_index in start..start + len {
            let Some(session) = by_index.get(&session_index).copied() else {
                continue;
            };
            let baseline = *selected_scores
                .get(&(fold, Arm::Design, session_index))
                .ok_or("SELECTED_BASELINE_SCORE_MISSING")?;
            for arm in [Arm::Raw, Arm::Z] {
                let representation_brier = *selected_scores
                    .get(&(fold, arm, session_index))
                    .ok_or("SELECTED_REPRESENTATION_SCORE_MISSING")?;
                let baseline_lambda = selected_lambdas
                    .iter()
                    .find(|x| x.arm == "DESIGN")
                    .unwrap()
                    .lambda;
                let representation_lambda = selected_lambdas
                    .iter()
                    .find(|x| x.arm == arm.name())
                    .unwrap()
                    .lambda;
                score_rows.push(ScoreRow {
                    fold_id: fold,
                    model_state_id: format!("PSEUDO_DB_F{fold}_BASE_L{baseline_lambda:.4}_{}_L{representation_lambda:.4}", arm.name()),
                    representation: arm.name().into(),
                    session_index,
                    session_id: session.session_id.clone(),
                    civil_date: session.civil_date.clone(),
                    month: session.month.clone(),
                    offset: session.offset,
                    baseline_brier: baseline,
                    representation_brier,
                    difference: baseline - representation_brier,
                });
            }
        }
    }
    score_rows.sort_by_key(|row| (row.representation.clone(), row.session_index));
    let validation_sessions = score_rows.len() / 2;
    Ok(PseudoDbResult {
        score_rows,
        selected_lambdas,
        complete_sessions: sessions.len(),
        validation_sessions,
        fold_session_counts,
    })
}

struct Matrices {
    train_x: Vec<f64>,
    train_y: Vec<f64>,
    weights: Vec<f64>,
    valid_x: Vec<f64>,
    valid_y: Vec<f64>,
    cols: usize,
}

fn matrices(train: &[&SessionRows], valid: &[&SessionRows], arm: Arm) -> Result<Matrices, String> {
    let rep_cols = match arm {
        Arm::Design => 0,
        Arm::Raw => 5,
        Arm::Z => 4,
    };
    let cols = 31 + rep_cols;
    let scaler = if rep_cols == 0 {
        None
    } else {
        let mut values = Vec::with_capacity(train.len() * RANGE_COUNT * rep_cols);
        for session in train {
            for k in 0..RANGE_COUNT {
                append_representation(&mut values, session, k, arm);
            }
        }
        Some(fit_standardizer(
            &values,
            train.len() * RANGE_COUNT,
            rep_cols,
        )?)
    };
    let (train_x, train_y) = design(train, arm, cols, scaler.as_ref());
    let (valid_x, valid_y) = design(valid, arm, cols, scaler.as_ref());
    let weights = vec![1.0 / RANGE_COUNT as f64; train_y.len()];
    Ok(Matrices {
        train_x,
        train_y,
        weights,
        valid_x,
        valid_y,
        cols,
    })
}

fn design(
    sessions: &[&SessionRows],
    arm: Arm,
    cols: usize,
    scaler: Option<&(Vec<f64>, Vec<f64>)>,
) -> (Vec<f64>, Vec<f64>) {
    let mut x = Vec::with_capacity(sessions.len() * RANGE_COUNT * cols);
    let mut y = Vec::with_capacity(sessions.len() * RANGE_COUNT);
    let rep_cols = cols - 31;
    for session in sessions {
        for k in 0..RANGE_COUNT {
            let start = x.len();
            x.resize(start + cols, 0.0);
            x[start] = 1.0;
            if k > 0 {
                x[start + k] = 1.0;
            }
            x[start + 30] = f64::from(session.offset == 180);
            if rep_cols > 0 {
                let (mean, sd) = scaler.unwrap();
                for j in 0..rep_cols {
                    x[start + 31 + j] =
                        (representation_value(session, k, arm, j) - mean[j]) / sd[j];
                }
            }
            y.push(session.targets[k]);
        }
    }
    (x, y)
}

fn representation_value(session: &SessionRows, k: usize, arm: Arm, field: usize) -> f64 {
    match arm {
        Arm::Design => unreachable!(),
        Arm::Raw => session.raw[k][field],
        Arm::Z => session.z[k][field],
    }
}

fn append_representation(out: &mut Vec<f64>, session: &SessionRows, k: usize, arm: Arm) {
    match arm {
        Arm::Design => {}
        Arm::Raw => out.extend_from_slice(&session.raw[k]),
        Arm::Z => out.extend_from_slice(&session.z[k]),
    }
}

fn select_lambdas(scores: &[FoldScore]) -> Result<Vec<SelectedLambda>, String> {
    let mut selected = Vec::new();
    for arm in [Arm::Design, Arm::Raw, Arm::Z] {
        let mut candidates = Vec::new();
        for lambda_index in 0..LAMBDAS.len() {
            let values = scores
                .iter()
                .filter(|x| x.arm == arm && x.lambda_index == lambda_index)
                .map(|x| x.brier)
                .collect::<Vec<_>>();
            if values.is_empty() {
                continue;
            }
            candidates.push((
                lambda_index,
                values.iter().sum::<f64>() / values.len() as f64,
                values.len(),
            ));
        }
        if candidates.len() != LAMBDAS.len() {
            return Err(format!("LAMBDA_INELIGIBLE:{}", arm.name()));
        }
        candidates.sort_by(|a, b| a.1.total_cmp(&b.1).then_with(|| b.0.cmp(&a.0)));
        let best_value = candidates[0].1;
        let best = candidates
            .iter()
            .filter(|x| (x.1 - best_value).abs() <= 1e-12)
            .max_by_key(|x| x.0)
            .unwrap();
        selected.push(SelectedLambda {
            arm: arm.name().into(),
            lambda: LAMBDAS[best.0],
            validation_brier: best.1,
            validation_sessions: best.2,
        });
    }
    Ok(selected)
}

fn brier(predictions: &[f64], targets: &[f64]) -> f64 {
    predictions
        .iter()
        .zip(targets)
        .map(|(p, y)| {
            let e = p - y;
            e * e
        })
        .sum::<f64>()
        / predictions.len() as f64
}
