use crate::graph::WIDTH;
use anyhow::{Result, ensure};
use serde::Serialize;

#[derive(Serialize)]
pub struct MatrixCensus {
    pub rank: usize,
    pub frobenius_norm: f64,
    pub sigma_max: f64,
    pub sigma_min: f64,
    pub singular_values_descending: Vec<f64>,
    pub rank_tolerance: f64,
    pub condition_number: Option<f64>,
    pub row_sums: Vec<f64>,
    pub zero_rows: usize,
    pub exact_zero_entries: usize,
    pub density: f64,
    pub row_entropy_nats: Vec<f64>,
    pub mean_row_entropy_nats: f64,
    pub max_row_entropy_nats: f64,
    pub bucket_populations: Option<Vec<u64>>,
}

pub fn analyze_matrix(matrix: &[f64], bucket_populations: Option<[u64; WIDTH]>) -> Result<MatrixCensus> {
    ensure!(matrix.len() == WIDTH * WIDTH, "matrix has wrong dimensions");
    ensure!(matrix.iter().all(|x| x.is_finite() && *x >= 0.0), "matrix contains nonfinite or negative value");
    let mut frobenius_sq = 0.0;
    let mut zero_entries = 0usize;
    let mut row_sums = Vec::with_capacity(WIDTH);
    let mut entropies = Vec::with_capacity(WIDTH);
    let mut zero_rows = 0usize;
    for row in matrix.chunks_exact(WIDTH) {
        let mut sum = 0.0;
        let mut entropy = 0.0;
        for &x in row {
            frobenius_sq += x * x;
            sum += x;
            if x == 0.0 { zero_entries += 1; }
        }
        if sum == 0.0 {
            zero_rows += 1;
        } else {
            for &x in row { if x > 0.0 { let p = x / sum; entropy -= p * p.ln(); } }
        }
        row_sums.push(sum);
        entropies.push(entropy);
    }
    let singular = one_sided_jacobi_singular_values(matrix);
    let sigma_max = singular.first().copied().unwrap_or(0.0);
    let sigma_min = singular.last().copied().unwrap_or(0.0);
    let rank_tolerance = WIDTH as f64 * f64::EPSILON * sigma_max;
    let rank = singular.iter().filter(|&&s| s > rank_tolerance).count();
    let condition_number = if sigma_min > rank_tolerance { Some(sigma_max / sigma_min) } else { None };
    let mean_entropy = entropies.iter().sum::<f64>() / WIDTH as f64;
    let max_entropy = entropies.iter().copied().fold(0.0, f64::max);
    Ok(MatrixCensus {
        rank,
        frobenius_norm: frobenius_sq.sqrt(),
        sigma_max,
        sigma_min,
        singular_values_descending: singular,
        rank_tolerance,
        condition_number,
        row_sums,
        zero_rows,
        exact_zero_entries: zero_entries,
        density: 1.0 - zero_entries as f64 / (WIDTH * WIDTH) as f64,
        row_entropy_nats: entropies,
        mean_row_entropy_nats: mean_entropy,
        max_row_entropy_nats: max_entropy,
        bucket_populations: bucket_populations.map(|counts| counts.to_vec()),
    })
}

pub(crate) fn verify_fixture() -> Result<()> {
    let mut hadamard = vec![0.0f64; WIDTH * WIDTH];
    for row in 0..WIDTH {
        for col in 0..WIDTH {
            hadamard[row * WIDTH + col] = if (row & col).count_ones() % 2 == 0 { 1.0 } else { -1.0 };
        }
    }
    let mut known = vec![0.0f64; WIDTH * WIDTH];
    for row in 0..WIDTH {
        for col in 0..WIDTH {
            known[row * WIDTH + col] = (0..WIDTH)
                .map(|k| hadamard[row * WIDTH + k] * (WIDTH as f64 - k as f64) * hadamard[col * WIDTH + k])
                .sum::<f64>() / WIDTH as f64;
        }
    }
    let census = analyze_matrix(&known, None)?;
    ensure!(census.rank == WIDTH, "Jacobi census fixture rank mismatch");
    ensure!((census.sigma_max - WIDTH as f64).abs() < 1e-9, "Jacobi census fixture sigma_max mismatch");
    ensure!((census.sigma_min - 1.0).abs() < 1e-9, "Jacobi census fixture sigma_min mismatch");
    for (i, &sigma) in census.singular_values_descending.iter().enumerate() {
        ensure!((sigma - (WIDTH - i) as f64).abs() < 1e-8, "Jacobi census fixture spectrum mismatch at {i}");
    }
    Ok(())
}

fn one_sided_jacobi_singular_values(matrix: &[f64]) -> Vec<f64> {
    let mut columns = vec![0.0f64; WIDTH * WIDTH];
    for row in 0..WIDTH {
        for col in 0..WIDTH { columns[col * WIDTH + row] = matrix[row * WIDTH + col]; }
    }
    for _sweep in 0..100 {
        let mut max_corr = 0.0f64;
        let mut changed = false;
        for p in 0..WIDTH {
            for q in (p + 1)..WIDTH {
                let mut alpha = 0.0;
                let mut beta = 0.0;
                let mut gamma = 0.0;
                for row in 0..WIDTH {
                    let a = columns[p * WIDTH + row];
                    let b = columns[q * WIDTH + row];
                    alpha += a * a;
                    beta += b * b;
                    gamma += a * b;
                }
                let scale = (alpha * beta).sqrt();
                if scale == 0.0 { continue; }
                let corr = gamma.abs() / scale;
                max_corr = max_corr.max(corr);
                if corr <= 8.0 * f64::EPSILON { continue; }
                changed = true;
                let zeta = (beta - alpha) / (2.0 * gamma);
                let sign = if zeta >= 0.0 { 1.0 } else { -1.0 };
                let t = sign / (zeta.abs() + (1.0 + zeta * zeta).sqrt());
                let c = 1.0 / (1.0 + t * t).sqrt();
                let s = c * t;
                for row in 0..WIDTH {
                    let a = columns[p * WIDTH + row];
                    let b = columns[q * WIDTH + row];
                    columns[p * WIDTH + row] = c * a - s * b;
                    columns[q * WIDTH + row] = s * a + c * b;
                }
            }
        }
        if !changed || max_corr <= 32.0 * f64::EPSILON { break; }
    }
    let mut values = (0..WIDTH).map(|col| {
        columns[col * WIDTH..(col + 1) * WIDTH].iter().map(|x| x * x).sum::<f64>().sqrt()
    }).collect::<Vec<_>>();
    values.sort_by(|a, b| b.total_cmp(a));
    values
}
