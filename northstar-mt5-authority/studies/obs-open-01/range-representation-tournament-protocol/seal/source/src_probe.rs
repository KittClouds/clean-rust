use wide::f64x4;

#[derive(Debug, Clone)]
pub struct Fit {
    pub beta: Vec<f64>,
    pub iterations: usize,
    pub converged: bool,
}

pub fn fit_logistic(
    x: &[f64],
    y: &[f64],
    weights: &[f64],
    rows: usize,
    cols: usize,
    lambda: f64,
) -> Result<Fit, String> {
    if rows == 0
        || cols == 0
        || x.len() != rows * cols
        || y.len() != rows
        || weights.len() != rows
        || lambda <= 0.0
    {
        return Err("INVALID_PROBE_INPUT".into());
    }
    let mut beta = vec![0.0; cols];
    let mut gradient = vec![0.0; cols];
    let mut hessian = vec![0.0; cols * cols];
    let mut current = objective(x, y, weights, rows, cols, &beta, lambda)?;
    for iteration in 1..=100 {
        gradient.fill(0.0);
        hessian.fill(0.0);
        for i in 0..rows {
            let row = &x[i * cols..(i + 1) * cols];
            let p = sigmoid(dot(row, &beta));
            let w = weights[i];
            let residual = w * (p - y[i]);
            for j in 0..cols {
                gradient[j] += residual * row[j];
            }
            let curvature = w * p * (1.0 - p);
            for j in 0..cols {
                for k in 0..=j {
                    hessian[j * cols + k] += curvature * row[j] * row[k];
                }
            }
        }
        for j in 1..cols {
            gradient[j] += lambda * beta[j];
            hessian[j * cols + j] += lambda;
        }
        for j in 0..cols {
            for k in 0..j {
                hessian[k * cols + j] = hessian[j * cols + k];
            }
        }
        if gradient.iter().fold(0.0f64, |a, &b| a.max(b.abs())) <= 1e-10 {
            return Ok(Fit {
                beta,
                iterations: iteration - 1,
                converged: true,
            });
        }
        let step = solve_cholesky(&hessian, &gradient, cols)?;
        let mut factor = 1.0;
        let mut accepted = None;
        for _ in 0..=50 {
            let candidate: Vec<_> = beta
                .iter()
                .zip(&step)
                .map(|(b, s)| b - factor * s)
                .collect();
            let value = objective(x, y, weights, rows, cols, &candidate, lambda)?;
            if value <= current {
                accepted = Some((candidate, value));
                break;
            }
            factor *= 0.5;
        }
        let Some((next, value)) = accepted else {
            return Err("PROBE_STEP_HALVING_EXHAUSTED".into());
        };
        let rel = (current - value).abs() / current.abs().max(1.0);
        beta = next;
        current = value;
        if rel <= 1e-12 {
            return Ok(Fit {
                beta,
                iterations: iteration,
                converged: true,
            });
        }
    }
    Ok(Fit {
        beta,
        iterations: 100,
        converged: false,
    })
}

pub fn predict(x: &[f64], rows: usize, cols: usize, beta: &[f64]) -> Result<Vec<f64>, String> {
    if x.len() != rows * cols || beta.len() != cols {
        return Err("PREDICT_SHAPE_MISMATCH".into());
    }
    Ok(x.chunks_exact(cols)
        .map(|r| sigmoid(dot(r, beta)))
        .collect())
}

pub fn session_brier(pred: &[f64], y: &[f64], sessions: &[u32]) -> Result<f64, String> {
    if pred.len() != y.len() || y.len() != sessions.len() || pred.is_empty() {
        return Err("BRIER_SHAPE_MISMATCH".into());
    }
    let mut totals = std::collections::BTreeMap::<u32, (f64, usize)>::new();
    for ((&p, &target), &s) in pred.iter().zip(y).zip(sessions) {
        let e = p - target;
        let x = totals.entry(s).or_default();
        x.0 += e * e;
        x.1 += 1;
    }
    if totals.values().any(|&(_, n)| n != 30) {
        return Err("PARTIAL_SESSION_FORMAL_SCORE".into());
    }
    Ok(totals
        .values()
        .map(|(sum, n)| sum / (*n as f64))
        .sum::<f64>()
        / totals.len() as f64)
}

pub fn fit_standardizer(
    x: &[f64],
    rows: usize,
    cols: usize,
) -> Result<(Vec<f64>, Vec<f64>), String> {
    if rows < 2 || x.len() != rows * cols {
        return Err("SCALER_SHAPE_MISMATCH".into());
    }
    let mut mean = vec![0.0; cols];
    for row in x.chunks_exact(cols) {
        for j in 0..cols {
            mean[j] += row[j];
        }
    }
    for v in &mut mean {
        *v /= rows as f64;
    }
    let mut sd = vec![0.0; cols];
    for row in x.chunks_exact(cols) {
        for j in 0..cols {
            let d = row[j] - mean[j];
            sd[j] += d * d;
        }
    }
    for v in &mut sd {
        *v = (*v / (rows - 1) as f64).sqrt();
        if *v == 0.0 {
            *v = 1.0;
        }
    }
    Ok((mean, sd))
}

fn objective(
    x: &[f64],
    y: &[f64],
    weights: &[f64],
    rows: usize,
    cols: usize,
    beta: &[f64],
    lambda: f64,
) -> Result<f64, String> {
    let mut loss = 0.0;
    for i in 0..rows {
        let eta = dot(&x[i * cols..(i + 1) * cols], beta);
        loss += weights[i] * (softplus(eta) - y[i] * eta);
    }
    loss += 0.5 * lambda * beta.iter().skip(1).map(|b| b * b).sum::<f64>();
    if loss.is_finite() {
        Ok(loss)
    } else {
        Err("NONFINITE_PROBE_OBJECTIVE".into())
    }
}
fn sigmoid(x: f64) -> f64 {
    if x >= 0.0 {
        1.0 / (1.0 + (-x).exp())
    } else {
        let e = x.exp();
        e / (1.0 + e)
    }
}
fn softplus(x: f64) -> f64 {
    if x > 0.0 {
        x + (-x).exp().ln_1p()
    } else {
        x.exp().ln_1p()
    }
}

fn dot(a: &[f64], b: &[f64]) -> f64 {
    let mut i = 0;
    let mut lanes = f64x4::ZERO;
    while i + 4 <= a.len() {
        lanes += f64x4::from([a[i], a[i + 1], a[i + 2], a[i + 3]])
            * f64x4::from([b[i], b[i + 1], b[i + 2], b[i + 3]]);
        i += 4;
    }
    let mut sum: f64 = lanes.to_array().into_iter().sum();
    while i < a.len() {
        sum += a[i] * b[i];
        i += 1;
    }
    sum
}

fn solve_cholesky(a: &[f64], b: &[f64], n: usize) -> Result<Vec<f64>, String> {
    let mut l = vec![0.0; n * n];
    for i in 0..n {
        for j in 0..=i {
            let mut sum = a[i * n + j];
            for k in 0..j {
                sum -= l[i * n + k] * l[j * n + k];
            }
            if i == j {
                if !(sum > 1e-14) {
                    return Err("PROBE_HESSIAN_NOT_POSITIVE_DEFINITE".into());
                }
                l[i * n + j] = sum.sqrt();
            } else {
                l[i * n + j] = sum / l[j * n + j];
            }
        }
    }
    let mut y = vec![0.0; n];
    for i in 0..n {
        let mut sum = b[i];
        for k in 0..i {
            sum -= l[i * n + k] * y[k];
        }
        y[i] = sum / l[i * n + i];
    }
    let mut x = vec![0.0; n];
    for i in (0..n).rev() {
        let mut sum = y[i];
        for k in i + 1..n {
            sum -= l[k * n + i] * x[k];
        }
        x[i] = sum / l[i * n + i];
    }
    Ok(x)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn simd_dot_and_probe_are_deterministic() {
        let x = [1., -2., 3., 4., 5.];
        let y = [2., 3., -1., 0.5, 4.];
        let expected = x.iter().zip(y).map(|(a, b)| a * b).sum::<f64>();
        assert_eq!(dot(&x, &y), expected);
        let design = [1., -1., 1., 0., 1., 1., 1., 2.];
        let target = [0., 0., 1., 1.];
        let w = [1.; 4];
        let a = fit_logistic(&design, &target, &w, 4, 2, 0.1).unwrap();
        let b = fit_logistic(&design, &target, &w, 4, 2, 0.1).unwrap();
        assert_eq!(a.beta, b.beta);
    }
}
