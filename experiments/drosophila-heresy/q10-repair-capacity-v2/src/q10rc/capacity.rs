use super::{
    readout::MoveColumn,
    types::{RankProjectionReceipt, RelaxedBudgetReceipt},
};
use anyhow::{Context, Result, ensure};
use nalgebra::{DMatrix, DVector};

const CUES: usize = 16;
const RANK_MULTIPLIER: f64 = 1000.0;
const SVD_EPSILON: f64 = 1.0e-14;
const SVD_MAX_ITERATIONS: usize = 100_000;
const COEFFICIENT_FLOOR: f64 = 1.0e-12;
const INTEGRITY_TOLERANCE: f64 = 2.0e-10;

struct BlockFactor<'a> {
    columns: &'a [MoveColumn],
    matrix: DMatrix<f64>,
    vt: DMatrix<f64>,
    singular_values: Vec<f64>,
}

pub(crate) struct CapacityAnalysis {
    pub rank: RankProjectionReceipt,
    pub relaxed: Option<RelaxedBudgetReceipt>,
}

fn l2(values: &[f64]) -> f64 {
    values.iter().map(|x| x * x).sum::<f64>().sqrt()
}

fn linf(values: &[f64]) -> f64 {
    values.iter().map(|x| x.abs()).fold(0.0, f64::max)
}

fn factor_blocks(columns_by_post: &[Vec<MoveColumn>]) -> Result<Vec<BlockFactor<'_>>> {
    let mut factors = Vec::with_capacity(columns_by_post.len());
    for (post, columns) in columns_by_post.iter().enumerate() {
        ensure!(columns.iter().all(|column| column.post == post));
        let matrix = DMatrix::from_fn(CUES, columns.len(), |row, column| {
            columns[column].effects[row]
        });
        if columns.is_empty() {
            factors.push(BlockFactor {
                columns,
                matrix,
                vt: DMatrix::zeros(0, 0),
                singular_values: vec![0.0; CUES],
            });
            continue;
        }
        let svd = nalgebra::linalg::SVD::try_new(
            matrix.clone(),
            false,
            true,
            SVD_EPSILON,
            SVD_MAX_ITERATIONS,
        )
        .context("Q10-RC move-bank SVD failed to converge")?;
        let vt = svd.v_t.context("Q10-RC SVD did not return Vt")?;
        let mut singular_values = svd.singular_values.as_slice().to_vec();
        singular_values.resize(CUES, 0.0);
        ensure!(singular_values.iter().all(|x| x.is_finite() && *x >= 0.0));
        ensure!(singular_values.windows(2).all(|x| x[0] >= x[1]));
        factors.push(BlockFactor {
            columns,
            matrix,
            vt,
            singular_values,
        });
    }
    Ok(factors)
}

pub(crate) fn analyze(
    columns_by_post: &[Vec<MoveColumn>],
    error: &[f64],
) -> Result<CapacityAnalysis> {
    let posts = columns_by_post.len();
    let rows = posts * CUES;
    ensure!(error.len() == rows);
    let factors = factor_blocks(columns_by_post)?;
    let active_columns: usize = columns_by_post.iter().map(Vec::len).sum();
    let sigma_max = factors
        .iter()
        .flat_map(|factor| factor.singular_values.iter().copied())
        .fold(0.0, f64::max);
    let rank_threshold =
        sigma_max * rows.max(active_columns) as f64 * f64::EPSILON * RANK_MULTIPLIER;
    let mut all_sigma: Vec<_> = factors
        .iter()
        .flat_map(|factor| factor.singular_values.iter().copied())
        .collect();
    all_sigma.sort_by(|a, b| b.total_cmp(a));
    let rank = all_sigma
        .iter()
        .filter(|&&sigma| sigma > rank_threshold)
        .count();
    let smallest_retained = (rank > 0).then(|| all_sigma[rank - 1]);
    let largest_discarded = (rank < all_sigma.len()).then(|| all_sigma[rank]);
    let condition_number = smallest_retained.map(|smallest| sigma_max / smallest);

    let mut reachable = vec![0.0; rows];
    let mut unreachable = vec![0.0; rows];
    let mut reconstructed = vec![0.0; rows];
    let mut coefficient_l1 = 0.0;
    let mut coefficient_l2_sq = 0.0;
    let mut coefficient_linf = 0.0_f64;
    let mut coefficients_above_floor = 0usize;
    let mut max_column_unreachable_inner = 0.0_f64;

    for (post, factor) in factors.iter().enumerate() {
        let e: Vec<_> = (0..CUES).map(|cue| error[cue * posts + post]).collect();
        let retained_rank = factor
            .singular_values
            .iter()
            .filter(|&&sigma| sigma > rank_threshold)
            .count();
        let mut projection = [0.0_f64; CUES];
        let mut block_coefficients = DVector::zeros(factor.columns.len());
        if retained_rank > 0 {
            // Keep the frozen SVD rank decision, but derive the projector and
            // pseudoinverse through the retained right subspace.  On highly
            // rank-deficient move banks nalgebra's returned U can violate
            // A*V = U*Sigma by more than the integrity gate even when V is
            // sound.  QR of A*V_r avoids normal equations and preserves the
            // exact retained subspace selected above.
            let vr = factor.vt.rows(0, retained_rank).transpose();
            let image = &factor.matrix * &vr;
            let qr = image.clone().qr();
            let r = qr.r();
            ensure!(
                r.iter().all(|x| x.is_finite()) && (0..retained_rank).all(|i| r[(i, i)] != 0.0),
                "Q10-RC retained-subspace QR is non-finite or singular"
            );
            let mut rhs = DVector::from_column_slice(&e);
            qr.q_tr_mul(&mut rhs);
            let mut coordinates = rhs.rows(0, retained_rank).into_owned();
            ensure!(r.solve_upper_triangular_mut(&mut coordinates));
            let projected = &image * &coordinates;
            projection.copy_from_slice(projected.as_slice());
            block_coefficients = -(&vr * coordinates);
        }
        let mut block_unreachable = [0.0_f64; CUES];
        for cue in 0..CUES {
            let row = cue * posts + post;
            reachable[row] = projection[cue];
            unreachable[row] = e[cue] - projection[cue];
            block_unreachable[cue] = unreachable[row];
        }
        for (column_index, column) in factor.columns.iter().enumerate() {
            let coefficient = block_coefficients[column_index];
            coefficient_l1 += coefficient.abs();
            coefficient_l2_sq += coefficient * coefficient;
            coefficient_linf = coefficient_linf.max(coefficient.abs());
            coefficients_above_floor += usize::from(coefficient.abs() > COEFFICIENT_FLOOR);
            let orthogonality: f64 = (0..CUES)
                .map(|cue| column.effects[cue] * block_unreachable[cue])
                .sum();
            max_column_unreachable_inner = max_column_unreachable_inner.max(orthogonality.abs());
            for cue in 0..CUES {
                reconstructed[cue * posts + post] += column.effects[cue] * coefficient;
            }
        }
    }

    let error_l2 = l2(error);
    let error_linf = linf(error);
    let reachable_l2 = l2(&reachable);
    let reachable_linf = linf(&reachable);
    let unreachable_l2 = l2(&unreachable);
    let unreachable_linf = linf(&unreachable);
    let projection_reconstruction = error
        .iter()
        .zip(&reachable)
        .zip(&unreachable)
        .map(|((&e, &r), &u)| (e - r - u).abs())
        .fold(0.0, f64::max)
        / (1.0 + error_linf);
    let projection_orthogonality =
        max_column_unreachable_inner / (1.0 + sigma_max * unreachable_l2);
    ensure!(projection_reconstruction <= INTEGRITY_TOLERANCE);
    ensure!(projection_orthogonality <= INTEGRITY_TOLERANCE);

    let rank_receipt = RankProjectionReceipt {
        row_count: rows,
        active_columns,
        rank,
        rank_fraction: rank as f64 / rows.max(1) as f64,
        rank_threshold,
        singular_values: all_sigma,
        smallest_retained,
        largest_discarded,
        condition_number,
        reachable_l2,
        reachable_linf,
        unreachable_l2,
        unreachable_linf,
        rho_2: if error_l2 > 0.0 {
            unreachable_l2 / error_l2
        } else {
            0.0
        },
        rho_inf: if error_linf > 0.0 {
            unreachable_linf / error_linf
        } else {
            0.0
        },
        max_column_unreachable_inner_product: max_column_unreachable_inner,
        normalized_projection_reconstruction_error: projection_reconstruction,
        normalized_projection_orthogonality_error: projection_orthogonality,
    };

    let relaxed = if error_l2 == 0.0 {
        None
    } else {
        let reconstructed_residual: Vec<_> = reconstructed
            .iter()
            .zip(error)
            .map(|(&rx, &e)| rx + e)
            .collect();
        let reconstruction_error = reconstructed_residual
            .iter()
            .zip(&unreachable)
            .map(|(&actual, &expected)| (actual - expected).abs())
            .fold(0.0, f64::max)
            / (1.0 + error_linf);
        ensure!(reconstruction_error <= INTEGRITY_TOLERANCE);
        Some(RelaxedBudgetReceipt {
            l1: coefficient_l1,
            l2: coefficient_l2_sq.sqrt(),
            linf: coefficient_linf,
            coefficients_above_floor,
            coefficient_fraction_above_floor: coefficients_above_floor as f64
                / active_columns.max(1) as f64,
            ceil_l1_one_ulp_equivalent_scale: coefficient_l1.ceil(),
            reconstructed_residual_l2: l2(&reconstructed_residual),
            reconstructed_residual_linf: linf(&reconstructed_residual),
            normalized_reconstruction_error: reconstruction_error,
        })
    };
    Ok(CapacityAnalysis {
        rank: rank_receipt,
        relaxed,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rank_projection_and_relaxed_inverse_share_one_subspace() {
        let mut columns = vec![Vec::new()];
        let mut first = [0.0; CUES];
        let mut second = [0.0; CUES];
        first[0] = 1.0;
        second[1] = 2.0;
        columns[0].push(MoveColumn {
            coordinate: 0,
            direction: -1,
            post: 0,
            effects: first,
        });
        columns[0].push(MoveColumn {
            coordinate: 1,
            direction: 1,
            post: 0,
            effects: second,
        });
        let mut error = vec![0.0; CUES];
        error[0] = 3.0;
        error[1] = -4.0;
        error[2] = 5.0;
        let result = analyze(&columns, &error).unwrap();
        assert_eq!(result.rank.rank, 2);
        assert!((result.rank.unreachable_l2 - 5.0).abs() < 1e-12);
        let relaxed = result.relaxed.unwrap();
        assert!(relaxed.normalized_reconstruction_error < 1e-12);
    }
}
