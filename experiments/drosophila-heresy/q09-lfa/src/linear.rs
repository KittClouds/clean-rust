//! Q09 unbounded linear geometry, from committed f32 endpoints.
//! Rows are cue-major/MBON-minor, then ONE global acquisition-axis row.
use crate::{capture::Snapshot, task::Task};
use anyhow::{Result, ensure};
use nalgebra::{DMatrix, DVector};
use serde::Serialize;

pub const RANK_MULTIPLIER: f64 = 1000.0;
pub const RANK_DIAGNOSTICS: [f64; 3] = [100.0, 1000.0, 10000.0];
pub const INTEGRITY_TOLERANCE: f64 = 1e-9;
pub const SVD_EPSILON: f64 = 1e-14;
pub const SVD_MAX_ITERATIONS: usize = 100_000;

pub fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}
pub fn norm(a: &[f64]) -> f64 {
    dot(a, a).sqrt()
}

#[derive(Clone, Serialize)]
pub struct DriveOperator {
    pub cues: usize,
    pub posts: usize,
    pub coordinates: usize,
    /// Exact Pattern.edges slices in canonical sequential order.
    pub rows: Vec<Vec<usize>>,
}
impl DriveOperator {
    pub fn new(task: &Task, posts: usize, coordinates: usize) -> Result<Self> {
        ensure!(task.cues == 16 && task.patterns.len() >= 16 && posts > 0);
        let mut rows = Vec::with_capacity(16 * posts);
        for p in &task.patterns[..16] {
            ensure!(p.offsets.len() == posts + 1 && p.offsets[0] == 0);
            ensure!(p.offsets[posts] == p.edges.len());
            ensure!(p.edges.iter().all(|&i| i < coordinates));
            ensure!(p.offsets.windows(2).all(|w| w[0] <= w[1]));
            for j in 0..posts {
                rows.push(p.edges[p.offsets[j]..p.offsets[j + 1]].to_vec());
            }
        }
        Ok(Self {
            cues: 16,
            posts,
            coordinates,
            rows,
        })
    }
    pub fn apply(&self, values: &[f64]) -> Vec<f64> {
        assert_eq!(values.len(), self.coordinates);
        self.rows
            .iter()
            .map(|ids| ids.iter().map(|&i| values[i]).sum())
            .collect()
    }
    pub fn sequential(&self, values: &[f32]) -> Vec<f32> {
        assert_eq!(values.len(), self.coordinates);
        self.rows
            .iter()
            .map(|ids| ids.iter().map(|&i| values[i]).sum())
            .collect()
    }
    pub fn interior_matrix(&self, interior: &[usize], axis: &[f64]) -> DMatrix<f64> {
        let mut columns = vec![usize::MAX; self.coordinates];
        for (col, &i) in interior.iter().enumerate() {
            columns[i] = col;
        }
        let mut l = DMatrix::zeros(self.rows.len() + 1, interior.len());
        for (row, ids) in self.rows.iter().enumerate() {
            for &i in ids {
                if columns[i] != usize::MAX {
                    l[(row, columns[i])] += 1.0;
                }
            }
        }
        for (col, &i) in interior.iter().enumerate() {
            l[(self.rows.len(), col)] = axis[i];
        }
        l
    }
}

#[derive(Serialize, Clone)]
pub struct RankAudit {
    pub rows: usize,
    pub columns: usize,
    /// Includes structural zero rows; padded with zeros if rows > columns.
    pub singular_values: Vec<f64>,
    pub rank: usize,
    pub nullity: usize,
    pub threshold: f64,
    pub diagnostic_thresholds: [f64; 3],
    pub diagnostic_ranks: [usize; 3],
    pub smallest_retained: Option<f64>,
    pub largest_discarded: Option<f64>,
    pub retained_discarded_ratio: Option<f64>,
    pub condition_number: Option<f64>,
}
pub struct Factorization {
    pub audit: RankAudit,
    pub u: DMatrix<f64>,
    pub vt: DMatrix<f64>,
}
impl Factorization {
    pub fn new(matrix: &DMatrix<f64>) -> Result<Self> {
        let (rows, cols) = matrix.shape();
        ensure!(matrix.iter().all(|x| x.is_finite()));
        if rows == 0 || cols == 0 {
            return Ok(Self {
                audit: RankAudit {
                    rows,
                    columns: cols,
                    singular_values: vec![0.; rows],
                    rank: 0,
                    nullity: cols,
                    threshold: 0.,
                    diagnostic_thresholds: [0.; 3],
                    diagnostic_ranks: [0; 3],
                    smallest_retained: None,
                    largest_discarded: (rows > 0).then_some(0.),
                    retained_discarded_ratio: None,
                    condition_number: None,
                },
                u: DMatrix::zeros(rows, 0),
                vt: DMatrix::zeros(0, cols),
            });
        }
        // Direct rectangular thin SVD. Never square L to decide numerical rank.
        let svd = nalgebra::linalg::SVD::try_new(
            matrix.clone(),
            true,
            true,
            SVD_EPSILON,
            SVD_MAX_ITERATIONS,
        )
        .ok_or_else(|| anyhow::anyhow!("thin SVD failed to converge"))?;
        let u = svd.u.expect("requested U");
        let vt = svd.v_t.expect("requested Vt");
        let mut sigma = svd.singular_values.as_slice().to_vec();
        ensure!(sigma.iter().all(|s| s.is_finite() && *s >= 0.));
        ensure!(sigma.windows(2).all(|s| s[0] >= s[1]), "SVD not sorted");
        let scale = sigma.first().copied().unwrap_or(0.) * rows.max(cols) as f64 * f64::EPSILON;
        let threshold = scale * RANK_MULTIPLIER;
        let rank = sigma.iter().filter(|&&s| s > threshold).count();
        let diagnostic_thresholds = RANK_DIAGNOSTICS.map(|m| scale * m);
        let diagnostic_ranks =
            diagnostic_thresholds.map(|t| sigma.iter().filter(|&&s| s > t).count());
        let smallest_retained = (rank > 0).then(|| sigma[rank - 1]);
        let largest_discarded = if rank < sigma.len() {
            Some(sigma[rank])
        } else {
            (rows > sigma.len()).then_some(0.)
        };
        let retained_discarded_ratio = smallest_retained
            .zip(largest_discarded)
            .and_then(|(a, b)| (b > 0.).then_some(a / b));
        let condition_number = smallest_retained.map(|s| sigma[0] / s);
        sigma.resize(rows, 0.);
        Ok(Self {
            audit: RankAudit {
                rows,
                columns: cols,
                singular_values: sigma,
                rank,
                nullity: cols - rank,
                threshold,
                diagnostic_thresholds,
                diagnostic_ranks,
                smallest_retained,
                largest_discarded,
                retained_discarded_ratio,
                condition_number,
            },
            u,
            vt,
        })
    }
    pub fn project(&self, x: &[f64]) -> Vec<f64> {
        let mut out = vec![0.; x.len()];
        for k in 0..self.audit.rank {
            let q = (0..x.len()).map(|i| self.vt[(k, i)] * x[i]).sum::<f64>();
            for (i, y) in out.iter_mut().enumerate() {
                *y += q * self.vt[(k, i)];
            }
        }
        out
    }
    pub fn pseudoinverse(&self, b: &[f64]) -> Vec<f64> {
        let mut out = vec![0.; self.audit.columns];
        for k in 0..self.audit.rank {
            let q = (0..b.len()).map(|i| self.u[(i, k)] * b[i]).sum::<f64>()
                / self.audit.singular_values[k];
            for (i, y) in out.iter_mut().enumerate() {
                *y += q * self.vt[(k, i)];
            }
        }
        out
    }
}

pub fn scale_rows(l: &DMatrix<f64>) -> (DMatrix<f64>, Vec<f64>) {
    let mut out = l.clone();
    let scales: Vec<_> = (0..l.nrows())
        .map(|r| {
            let n = (0..l.ncols())
                .map(|c| l[(r, c)].powi(2))
                .sum::<f64>()
                .sqrt();
            if n > 0. { 1. / n } else { 1. }
        })
        .collect();
    for r in 0..l.nrows() {
        for c in 0..l.ncols() {
            out[(r, c)] *= scales[r];
        }
    }
    (out, scales)
}

#[derive(Clone, Serialize, Debug)]
pub struct Floors {
    pub signed_minimum: Option<f64>,
    pub absolute_minimum: Option<f64>,
    pub zero_residual: bool,
}
pub fn floors(k: usize, fixed: f64, free: f64) -> Floors {
    let total = fixed + free;
    if total == 0. {
        return Floors {
            signed_minimum: None,
            absolute_minimum: None,
            zero_residual: true,
        };
    }
    let signed = if k == 0 {
        1.
    } else {
        ((fixed - free) / total).clamp(-1., 1.)
    };
    let absolute = match k {
        0 => 1.,
        1 => signed.abs(),
        _ => signed.max(0.),
    };
    Floors {
        signed_minimum: Some(signed),
        absolute_minimum: Some(absolute),
        zero_residual: false,
    }
}

#[derive(Clone, Serialize)]
pub struct Integrity {
    pub true_reconstruction: f64,
    pub minimum_reconstruction: f64,
    pub null_annihilation: f64,
    pub row_null_orthogonality: f64,
    pub axis_null: f64,
    pub energy_identity: f64,
    pub residual_energy_identity: f64,
    pub pseudoinverse_agreement: f64,
    pub projector_idempotence: f64,
    pub outside_support_changes: usize,
    /// Dimensionless checks in the same order as the nine errors above.
    pub normalized_errors: [f64; 9],
    pub valid: bool,
}
#[derive(Clone, Serialize)]
pub struct Arithmetic {
    pub max_abs: f64,
    pub max_normalized: f64,
    pub l2: f64,
    pub worst_signed_error: f64,
    pub worst_cue: usize,
    pub worst_mbon: usize,
    pub signed_errors: Vec<f64>,
}
#[derive(Clone, Serialize)]
pub struct EventAudit {
    pub trial: usize,
    pub support_count: usize,
    pub fixed_boundary_count: usize,
    pub interior_variable_count: usize,
    pub drive_rank: RankAudit,
    pub combined_rank: RankAudit,
    pub row_scales: Vec<f64>,
    pub true_norm: f64,
    pub fixed_boundary_norm: f64,
    pub constraint_forced_norm: f64,
    pub null_norm: f64,
    pub null_energy_fraction: Option<f64>,
    pub axis_projection: Option<f64>,
    pub residual_norm: f64,
    pub fixed_residual_energy: f64,
    pub free_residual_energy: f64,
    pub floors: Floors,
    pub integrity: Integrity,
    pub arithmetic: Arithmetic,
    pub status: &'static str,
    pub box_feasibility: &'static str,
    pub alternative_seq32_equality: &'static str,
}
#[derive(Serialize)]
pub struct Replay {
    pub snapshot: Snapshot,
    pub operator: DriveOperator,
    pub denominators: Vec<f32>,
    pub interior_indices: Vec<usize>,
    pub fixed_boundary_indices: Vec<usize>,
    pub row_scales: Vec<f64>,
    pub targets: Vec<f64>,
    /// Row-major matrix representation for independent reviewers.
    pub scaled_operator: Vec<Vec<f64>>,
    pub d_star: Vec<f64>,
    pub n_true: Vec<f64>,
    pub audit: EventAudit,
}

pub fn audit(
    operator: &DriveOperator,
    s: &Snapshot,
    denom: &[f32],
    replay: bool,
) -> Result<(EventAudit, Option<Replay>)> {
    let n = operator.coordinates;
    ensure!(
        s.base.len() == n && s.target.len() == n && s.axis.len() == n && s.permitted.len() == n
    );
    ensure!(denom.len() == operator.posts && denom.iter().all(|&x| x.is_finite() && x > 0.));
    ensure!(
        s.base
            .iter()
            .chain(&s.target)
            .all(|&x| x.is_finite() && (0. ..=2.).contains(&x))
    );
    ensure!(s.axis.iter().all(|x| x.is_finite()));
    let d: Vec<_> = s
        .target
        .iter()
        .zip(&s.base)
        .map(|(&t, &b)| f64::from(t) - f64::from(b))
        .collect();
    let mut fixed = vec![0.; n];
    let mut interior = Vec::new();
    let mut fixed_ids = Vec::new();
    let mut outside = 0;
    for i in 0..n {
        if !s.permitted[i] {
            outside += usize::from(d[i] != 0.);
        } else if s.target[i] == 0. || s.target[i] == 2. {
            fixed[i] = d[i];
            fixed_ids.push(i);
        } else {
            interior.push(i);
        }
    }
    ensure!(
        outside == 0,
        "committed displacement outside permitted support"
    );
    let l = operator.interior_matrix(&interior, &s.axis);
    let (scaled, row_scales) = scale_rows(&l);
    let full_drive = operator.apply(&d);
    let fixed_drive = operator.apply(&fixed);
    let mut b: Vec<_> = full_drive
        .iter()
        .zip(&fixed_drive)
        .map(|(t, f)| t - f)
        .collect();
    b.push(dot(&d, &s.axis) - dot(&fixed, &s.axis));
    let bs: Vec<_> = b.iter().zip(&row_scales).map(|(v, s)| v * s).collect();
    let x: Vec<_> = interior.iter().map(|&i| d[i]).collect();
    let drive_factor = Factorization::new(&scaled.rows(0, operator.rows.len()).into_owned())?;
    let factor = Factorization::new(&scaled)?;
    let star = factor.project(&x);
    let inverse = factor.pseudoinverse(&bs);
    let null: Vec<_> = x.iter().zip(&star).map(|(x, s)| x - s).collect();
    let mut dstar = fixed.clone();
    let mut nt = vec![0.; n];
    for (j, &i) in interior.iter().enumerate() {
        dstar[i] = star[j];
        nt[i] = null[j];
    }
    let ax_norm = norm(&s.axis);
    let axis_projection = (ax_norm > 0.).then(|| dot(&d, &s.axis) / ax_norm);
    let mut rt = d.clone();
    let mut rs = dstar.clone();
    if let Some(p) = axis_projection {
        for i in 0..n {
            let axial = p * s.axis[i] / ax_norm;
            rt[i] -= axial;
            rs[i] -= axial;
        }
    }
    let et = dot(&d, &d);
    let en = dot(&nt, &nt);
    let ef = dot(&rs, &rs);
    let mul = |v: &[f64]| -> Vec<f64> {
        (&scaled * DVector::from_column_slice(v))
            .as_slice()
            .to_vec()
    };
    let error = |v: &[f64]| -> f64 {
        norm(
            &mul(v)
                .iter()
                .zip(&bs)
                .map(|(a, b)| a - b)
                .collect::<Vec<_>>(),
        )
    };
    let true_error = error(&x);
    let star_error = error(&star);
    let null_error = norm(&mul(&null));
    let orth = dot(&star, &null).abs();
    let axial = dot(&nt, &s.axis).abs();
    let energy = (et - dot(&dstar, &dstar) - en).abs();
    let residual_energy = (dot(&rt, &rt) - ef - en).abs();
    let inverse_error = norm(
        &star
            .iter()
            .zip(&inverse)
            .map(|(a, b)| a - b)
            .collect::<Vec<_>>(),
    );
    let star2 = factor.project(&star);
    let idempotence = norm(
        &star2
            .iter()
            .zip(&star)
            .map(|(a, b)| a - b)
            .collect::<Vec<_>>(),
    );
    let tiny = f64::MIN_POSITIVE;
    // Relative norm bounds with no unit-size absolute floor that could hide tiny updates.
    let matrix_norm = norm(scaled.as_slice());
    let constraint_scale = (matrix_norm * norm(&x) + norm(&bs)).max(tiny);
    let normalized = [
        true_error / constraint_scale,
        star_error / constraint_scale,
        null_error / (matrix_norm * norm(&x)).max(tiny),
        orth / et.max(tiny),
        axial / (et.sqrt() * ax_norm).max(tiny),
        energy / et.max(tiny),
        residual_energy / et.max(tiny),
        inverse_error / et.sqrt().max(tiny),
        idempotence / et.sqrt().max(tiny),
    ];
    let valid = normalized
        .iter()
        .all(|e| e.is_finite() && *e <= INTEGRITY_TOLERANCE);
    let seq_t = operator.sequential(&s.target);
    let seq_b = operator.sequential(&s.base);
    let errors: Vec<_> = seq_t
        .iter()
        .zip(&seq_b)
        .zip(&full_drive)
        .map(|((&t, &b), &lin)| f64::from(t - b) - lin)
        .collect();
    let worst = errors
        .iter()
        .enumerate()
        .max_by(|(_, a), (_, b)| a.abs().total_cmp(&b.abs()))
        .map(|(i, _)| i)
        .unwrap_or(0);
    let ambiguous = factor
        .audit
        .diagnostic_ranks
        .iter()
        .any(|&r| r != factor.audit.rank)
        || drive_factor
            .audit
            .diagnostic_ranks
            .iter()
            .any(|&r| r != drive_factor.audit.rank);
    let floor = floors(factor.audit.nullity, ef, en);
    let status = if !valid {
        "LINEAR_AUDIT_INVALID"
    } else if ambiguous {
        "LINEAR_AUDIT_VALID__NUMERICALLY_AMBIGUOUS"
    } else {
        "LINEAR_AUDIT_VALID__UNBOUNDED_GEOMETRY_ONLY"
    };
    let out = EventAudit {
        trial: s.trial,
        support_count: interior.len() + fixed_ids.len(),
        fixed_boundary_count: fixed_ids.len(),
        interior_variable_count: interior.len(),
        drive_rank: drive_factor.audit,
        combined_rank: factor.audit,
        row_scales: row_scales.clone(),
        true_norm: et.sqrt(),
        fixed_boundary_norm: norm(&fixed),
        constraint_forced_norm: norm(&dstar),
        null_norm: en.sqrt(),
        null_energy_fraction: (et > 0.).then_some(en / et),
        axis_projection,
        residual_norm: norm(&rt),
        fixed_residual_energy: ef,
        free_residual_energy: en,
        floors: floor,
        integrity: Integrity {
            true_reconstruction: true_error,
            minimum_reconstruction: star_error,
            null_annihilation: null_error,
            row_null_orthogonality: orth,
            axis_null: axial,
            energy_identity: energy,
            residual_energy_identity: residual_energy,
            pseudoinverse_agreement: inverse_error,
            projector_idempotence: idempotence,
            outside_support_changes: outside,
            normalized_errors: normalized,
            valid,
        },
        arithmetic: Arithmetic {
            max_abs: errors[worst].abs(),
            max_normalized: errors
                .iter()
                .enumerate()
                .map(|(i, e)| e.abs() / f64::from(denom[i % operator.posts]))
                .fold(0., f64::max),
            l2: norm(&errors),
            worst_signed_error: errors[worst],
            worst_cue: worst / operator.posts,
            worst_mbon: worst % operator.posts,
            signed_errors: errors,
        },
        status,
        box_feasibility: "NOT_TESTED",
        alternative_seq32_equality: "NOT_TESTED",
    };
    let saved = replay.then(|| Replay {
        snapshot: s.clone(),
        operator: operator.clone(),
        denominators: denom.to_vec(),
        interior_indices: interior,
        fixed_boundary_indices: fixed_ids,
        row_scales,
        targets: b,
        scaled_operator: (0..scaled.nrows())
            .map(|r| (0..scaled.ncols()).map(|c| scaled[(r, c)]).collect())
            .collect(),
        d_star: dstar,
        n_true: nt,
        audit: out.clone(),
    });
    Ok((out, saved))
}
