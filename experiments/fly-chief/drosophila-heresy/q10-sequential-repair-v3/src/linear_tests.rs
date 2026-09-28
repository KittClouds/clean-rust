use crate::{capture::Snapshot, graph::Graph, linear::*, task::Task};
use nalgebra::DMatrix;

fn close(a: &[f64], b: &[f64]) {
    assert_eq!(a.len(), b.len());
    let error = norm(&a.iter().zip(b).map(|(x, y)| x - y).collect::<Vec<_>>());
    assert!(error < 1e-10, "error={error}, a={a:?}, b={b:?}");
}

#[test]
fn retained_subspace_inverse_handles_inconsistent_targets_minimum_norm() {
    // Arbitrary b, including components outside range(L). The expected
    // least-squares inverse is known independently of the SVD/projector.
    let matrix = DMatrix::from_row_slice(4, 3, &[1., 1., 0., 2., 2., 0., 0., 0., 3., 0., 0., 0.]);
    let factor = Factorization::new(&matrix).unwrap();
    let b = nalgebra::DVector::from_vec(vec![4., -1., 9., 7.]);
    let inverse = factor.pseudoinverse(b.as_slice());
    close(&inverse, &[0.2, 0.2, 3.]);
    let residual = &matrix * nalgebra::DVector::from_column_slice(&inverse) - b;
    assert!((matrix.transpose() * residual).norm() < 1e-12);
    assert!((inverse[0] - inverse[1]).abs() < 1e-12); // Orthogonal to ker(L).
}

#[test]
fn rank_deficient_compact_blocks_keep_pseudoinverse_consistent() {
    for fixture in 0..32u64 {
        let matrix = DMatrix::from_fn(97, 181, |r, c| {
            let mut bits = (c as u64 + 1)
                .wrapping_mul(0x9e3779b97f4a7c15)
                .wrapping_add(fixture.wrapping_mul(0xd1b54a32d192ed03));
            bits = (bits ^ (bits >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
            bits = (bits ^ (bits >> 27)).wrapping_mul(0x94d049bb133111eb);
            bits ^= bits >> 31;
            if r == 96 {
                (bits as f64 / u64::MAX as f64) - 0.5
            } else if c < 180 && r % 6 == c / 30 {
                ((bits >> ((r / 6) % 8)) & 1) as f64
            } else {
                0.
            }
        });
        let matrix = scale_rows(&matrix).0;
        let f = Factorization::new(&matrix).unwrap();
        let x: Vec<_> = (0..181).map(|i| ((i + 1) as f64).sin()).collect();
        let b = (&matrix * nalgebra::DVector::from_column_slice(&x))
            .as_slice()
            .to_vec();
        let p = f.project(&x);
        let inverse = f.pseudoinverse(&b);
        let error = norm(
            &p.iter()
                .zip(&inverse)
                .map(|(a, b)| a - b)
                .collect::<Vec<_>>(),
        ) / norm(&x);
        assert!(
            error < INTEGRITY_TOLERANCE,
            "fixture={fixture}, error={error}, condition={:?}",
            f.audit.condition_number
        );
    }
}

#[test]
fn uneven_rank_compact_blocks_keep_pseudoinverse_consistent() {
    for fixture in 0..8u64 {
        let matrix = DMatrix::from_fn(785, 1569, |r, c| {
            let mut bits = (c as u64 + 1)
                .wrapping_mul(0x9e3779b97f4a7c15)
                .wrapping_add(fixture.wrapping_mul(0xd1b54a32d192ed03));
            bits = (bits ^ (bits >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
            bits = (bits ^ (bits >> 27)).wrapping_mul(0x94d049bb133111eb);
            bits ^= bits >> 31;
            if r == 784 {
                (bits as f64 / u64::MAX as f64) - 0.5
            } else if c < 1568
                && r % 49 == c / 32
                && c % 32 < 7 + ((c / 32) * 13 + fixture as usize) % 25
            {
                f64::from(((bits >> (3 * (r / 49))) & 7) == 0)
            } else {
                0.
            }
        });
        let matrix = scale_rows(&matrix).0;
        let f = Factorization::new(&matrix).unwrap();
        let x: Vec<_> = (0..matrix.ncols())
            .map(|i| ((i + 1) as f64).sin())
            .collect();
        let b = (&matrix * nalgebra::DVector::from_column_slice(&x))
            .as_slice()
            .to_vec();
        let p = f.project(&x);
        let inverse = f.pseudoinverse(&b);
        let error = norm(
            &p.iter()
                .zip(&inverse)
                .map(|(a, b)| a - b)
                .collect::<Vec<_>>(),
        ) / norm(&x);
        assert!(
            error < INTEGRITY_TOLERANCE,
            "fixture={fixture}, error={error}, condition={:?}, svd_error={}",
            f.audit.condition_number,
            compact_svd_reconstruction_error(&matrix)
        );
    }
}

#[test]
#[ignore = "read-only geometry replay of an existing engineering receipt; no simulation"]
fn archived_engineering_geometry_subset_inverse_consistency() {
    #[derive(serde::Deserialize)]
    struct Input {
        snapshot: Snapshot,
        interior_indices: Vec<usize>,
        scaled_operator: Vec<Vec<f64>>,
    }
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("qualification/stage-a-9201-compact/replay-R-tau4-trial1.json");
    let input: Input =
        serde_json::from_reader(std::io::BufReader::new(std::fs::File::open(path).unwrap()))
            .unwrap();
    for fixture in 0..32usize {
        let columns: Vec<_> = (0..input.interior_indices.len())
            .filter(|&c| (c * 65537 + fixture * 977) % 101 < 40 + fixture)
            .collect();
        let matrix = DMatrix::from_fn(input.scaled_operator.len(), columns.len(), |r, c| {
            input.scaled_operator[r][columns[c]]
        });
        let matrix = scale_rows(&matrix).0;
        let x: Vec<_> = columns
            .iter()
            .map(|&c| {
                let i = input.interior_indices[c];
                f64::from(input.snapshot.target[i]) - f64::from(input.snapshot.base[i])
            })
            .collect();
        let f = Factorization::new(&matrix).unwrap();
        let b = &matrix * nalgebra::DVector::from_column_slice(&x);
        let p = f.project(&x);
        let inverse = f.pseudoinverse(b.as_slice());
        let error = norm(
            &p.iter()
                .zip(&inverse)
                .map(|(a, b)| a - b)
                .collect::<Vec<_>>(),
        ) / norm(&x);
        assert!(
            error < INTEGRITY_TOLERANCE,
            "fixture={fixture}, error={error}, condition={:?}, svd_error={}",
            f.audit.condition_number,
            compact_svd_reconstruction_error(&matrix)
        );
    }
}

#[test]
fn redundant_block_inverse_has_consistent_left_action() {
    // Duplicate cue rows and unused QR directions reproduce the compact
    // core's structural rank deficiency, without loading anatomy or seeds.
    for variant in 0..16 {
        let posts = 8;
        let width = 32;
        let matrix = DMatrix::from_fn(16 * posts + 1, width * posts, |r, c| {
            if r == 16 * posts {
                ((c * 17 + variant * 13 + 1) as f64).sin()
            } else if r % posts == c / width {
                let cue = (r / posts) % (4 + variant % 9);
                let bits = (c as u64 + 1)
                    .wrapping_mul(0x9e3779b97f4a7c15)
                    .rotate_left(variant as u32);
                f64::from(((bits >> cue) & 1) as u32)
            } else {
                0.
            }
        });
        let matrix = scale_rows(&matrix).0;
        let f = Factorization::new(&matrix).unwrap();
        let x: Vec<_> = (0..matrix.ncols())
            .map(|i| ((i + 1) as f64 * 0.37).sin())
            .collect();
        let b = &matrix * nalgebra::DVector::from_column_slice(&x);
        let projected = f.project(&x);
        let inverse = f.pseudoinverse(b.as_slice());
        let relative = norm(
            &projected
                .iter()
                .zip(&inverse)
                .map(|(a, b)| a - b)
                .collect::<Vec<_>>(),
        ) / norm(&x);
        assert!(
            relative < INTEGRITY_TOLERANCE,
            "variant={variant}, inverse disagreement={relative:e}, condition={:?}",
            f.audit.condition_number
        );
    }
}

fn compare_direct_svd(matrix: &DMatrix<f64>) {
    let f = Factorization::new(matrix).unwrap();
    let direct =
        nalgebra::linalg::SVD::try_new(matrix.clone(), true, true, SVD_EPSILON, SVD_MAX_ITERATIONS)
            .unwrap();
    let sigma = direct.singular_values.as_slice();
    let scale = sigma[0] * matrix.nrows().max(matrix.ncols()) as f64 * f64::EPSILON;
    assert_eq!(
        f.audit.rank,
        sigma
            .iter()
            .filter(|&&s| s > scale * RANK_MULTIPLIER)
            .count(),
        "compact={:?}, direct={sigma:?}, threshold={}, matrix={matrix:?}",
        f.audit.singular_values,
        f.audit.threshold
    );
    assert_eq!(
        f.audit.diagnostic_ranks,
        RANK_DIAGNOSTICS.map(|m| sigma.iter().filter(|&&s| s > scale * m).count())
    );
    assert_eq!(f.audit.singular_values.len(), matrix.nrows());
    for (&a, &b) in f.audit.singular_values.iter().zip(sigma) {
        assert!((a - b).abs() <= 2e-13 * sigma[0], "{a} != {b}");
    }
    assert!(
        f.audit.singular_values[sigma.len()..]
            .iter()
            .all(|&s| s == 0.)
    );
    let x: Vec<_> = (0..matrix.ncols())
        .map(|i| (i as f64 * 0.37).sin())
        .collect();
    let vt = direct.v_t.unwrap();
    let u = direct.u.unwrap();
    let mut projected = vec![0.; matrix.ncols()];
    for k in 0..f.audit.rank {
        let coefficient: f64 = x.iter().enumerate().map(|(i, x)| vt[(k, i)] * x).sum();
        for (i, p) in projected.iter_mut().enumerate() {
            *p += coefficient * vt[(k, i)];
        }
    }
    let actual_projected = f.project(&x);
    let conditioning = sigma[0] / sigma[f.audit.rank.saturating_sub(1)].max(f64::MIN_POSITIVE);
    // Retained subspaces are sensitive at O(eps / spectral gap). This is a
    // comparison bound for ill-conditioned fixtures, not an audit gate.
    let difference = norm(
        &actual_projected
            .iter()
            .zip(&projected)
            .map(|(a, b)| a - b)
            .collect::<Vec<_>>(),
    );
    assert!(difference <= 1e-10 + 64. * f64::EPSILON * conditioning * norm(&x));
    close(&f.project(&actual_projected), &actual_projected);
    let null: Vec<_> = x
        .iter()
        .zip(&actual_projected)
        .map(|(x, p)| x - p)
        .collect();
    assert!(dot(&actual_projected, &null).abs() < 1e-10);
    assert!(
        (matrix * nalgebra::DVector::from_column_slice(&null)).norm()
            < 1e-10 * (1. + matrix.norm() * norm(&x))
    );
    // Use retained left singular modes as an arbitrary consistent target, so
    // agreement is checked independently of project(x) or the original target.
    let mut b = vec![0.; matrix.nrows()];
    let mut inverse = vec![0.; matrix.ncols()];
    for k in 0..f.audit.rank {
        let coefficient = (k + 1) as f64;
        for (i, b) in b.iter_mut().enumerate() {
            *b += u[(i, k)] * sigma[k] * coefficient;
        }
        for (i, p) in inverse.iter_mut().enumerate() {
            *p += coefficient * vt[(k, i)];
        }
    }
    // Near-cutoff inversion has the expected O(eps/sigma_min) sensitivity;
    // compare reconstruction as well as the solution, without changing gates.
    let actual = f.pseudoinverse(&b);
    let error = norm(
        &actual
            .iter()
            .zip(&inverse)
            .map(|(a, b)| a - b)
            .collect::<Vec<_>>(),
    );
    assert!(error <= 1e-10 + 1e-13 * conditioning * norm(&inverse));
    let residual = matrix * nalgebra::DVector::from_column_slice(&actual)
        - nalgebra::DVector::from_column_slice(&b);
    assert!(residual.norm() < 1e-10 * (1. + norm(&b)));
}

#[test]
fn compact_factorization_matches_direct_svd_dense_sparse_tall_and_wide() {
    for (rows, cols) in [(7, 19), (19, 7), (8, 8), (1, 9), (9, 1)] {
        let dense = DMatrix::from_fn(rows, cols, |r, c| {
            ((r * 31 + c * 17 + 1) as f64).sin() + if r == c { 0.5 } else { 0. }
        });
        compare_direct_svd(&scale_rows(&dense).0);
    }
    // Disjoint cue blocks, duplicates, unused coordinates and a global row.
    let sparse = DMatrix::from_row_slice(
        6,
        9,
        &[
            1., 2., 0., 0., 0., 0., 0., 0., 0., 2., 4., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 1.,
            1., 0., 0., 0., 0., 0., 0., 0., 1., -1., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0.,
            0., 0., 1., 3., 2., 4., 5., 6., 0., 0., 0.,
        ],
    );
    compare_direct_svd(&scale_rows(&sparse).0);
    let zero = Factorization::new(&DMatrix::zeros(785, 11)).unwrap();
    assert_eq!(zero.audit.singular_values, vec![0.; 785]);
    assert_eq!(zero.project(&[1.; 11]), vec![0.; 11]);
}

#[test]
fn full_cue_mbon_layout_preserves_all_785_row_singular_values() {
    // Engineering dimensions only: 16 cues x 49 posts plus one global row.
    // No anatomy, task stream, config or qualification seeds are loaded.
    let matrix = DMatrix::from_fn(785, 101, |r, c| {
        if r == 784 {
            ((c + 1) as f64).sin()
        } else if c == 2 * (r % 49) + (r / 49) % 2 {
            1.
        } else {
            0.
        }
    });
    let matrix = scale_rows(&matrix).0;
    let f = Factorization::new(&matrix).unwrap();
    assert_eq!(f.audit.singular_values.len(), 785);
    assert_eq!(f.audit.rank, 99);
    assert_eq!(f.audit.nullity, 2);
    compare_direct_svd(&matrix);
}

#[test]
fn compact_factorization_preserves_frozen_near_cutoff_rank() {
    // A Gram eigensolve cannot resolve these modes reliably: their squared
    // singular values are far below eps, but the frozen SVD cutoff retains them.
    let cutoff = 8. * f64::EPSILON * RANK_MULTIPLIER;
    for multiplier in [0.01, 0.5, 1.9, 2.1, 19., 21., 200.] {
        let s = cutoff * multiplier;
        let matrix = DMatrix::from_row_slice(
            3,
            8,
            &[
                1., 0., 0., 0., 0., 0., 0., 0., 0., s, 0., 0., 0., 0., 0., 0., 1., 0., s, 0., 0.,
                0., 0., 0.,
            ],
        );
        compare_direct_svd(&matrix);
    }
    // At exact equality to the cutoff, one ulp of sigma_max can change a
    // strict `>` decision in either SVD. Do not demand bitwise rank parity
    // there: both must expose the same diagnostic-rank ambiguity, and the
    // frozen threshold formula must remain unchanged.
    let s = cutoff * 2.;
    let boundary = DMatrix::from_row_slice(
        3,
        8,
        &[
            1., 0., 0., 0., 0., 0., 0., 0., 0., s, 0., 0., 0., 0., 0., 0., 1., 0., s, 0., 0., 0.,
            0., 0.,
        ],
    );
    let f = Factorization::new(&boundary).unwrap();
    assert_eq!(f.audit.diagnostic_ranks, [3, f.audit.rank, 1]);
    assert!(f.audit.diagnostic_ranks.iter().any(|&r| r != f.audit.rank));
    assert_eq!(
        f.audit.threshold,
        f.audit.singular_values[0] * 8. * f64::EPSILON * RANK_MULTIPLIER
    );
    // The final row is almost dependent on the drive rows, with its only
    // independent part close to the rank cutoff after row scaling.
    let matrix = DMatrix::from_row_slice(
        3,
        8,
        &[
            1., 1., 0., 0., 0., 0., 0., 0., 0., 0., 1., 1., 0., 0., 0., 0., 1., 1., 1., 1., 2e-10,
            0., 0., 0.,
        ],
    );
    compare_direct_svd(&scale_rows(&matrix).0);
}

#[test]
#[ignore = "engineering fixture timing only; never loads anatomy or seeds"]
fn compact_factorization_performance_fixture() {
    let rows = 129;
    let cols = 4096;
    let matrix = DMatrix::from_fn(rows, cols, |r, c| {
        if r == rows - 1 {
            ((c + 1) as f64).sin()
        } else if r / 8 == c / 256 {
            ((r * 31 + c * 17 + 1) as f64).sin()
        } else {
            0.
        }
    });
    let matrix = scale_rows(&matrix).0;
    let start = std::time::Instant::now();
    let compact = Factorization::new(&matrix).unwrap();
    let elapsed = start.elapsed();
    let start = std::time::Instant::now();
    let direct =
        nalgebra::linalg::SVD::try_new(matrix, true, true, SVD_EPSILON, SVD_MAX_ITERATIONS)
            .unwrap();
    let direct_elapsed = start.elapsed();
    close(
        &compact.audit.singular_values,
        direct.singular_values.as_slice(),
    );
    eprintln!(
        "compact={elapsed:?}, direct={direct_elapsed:?}, speedup={:.2}x",
        direct_elapsed.as_secs_f64() / elapsed.as_secs_f64()
    );
}
#[test]
fn full_drive_operator_linearity_and_direct_agreement() {
    let graph = Graph::fixture();
    let task = Task::new(&graph, 123, 16, 12, 32);
    let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len()).unwrap();
    assert_eq!(op.rows.len(), 16 * graph.kc_mb.n_post);
    let a: Vec<_> = (0..op.coordinates).map(|i| i as f64 / 17.).collect();
    let b: Vec<_> = (0..op.coordinates).map(|i| -(i as f64) / 11.).collect();
    let sum: Vec<_> = a.iter().zip(&b).map(|(a, b)| a + b).collect();
    close(
        &op.apply(&sum),
        &op.apply(&a)
            .iter()
            .zip(op.apply(&b))
            .map(|(a, b)| a + b)
            .collect::<Vec<_>>(),
    );
    for cue in 0..16 {
        for post in 0..op.posts {
            let p = &task.patterns[cue];
            let direct = p.edges[p.offsets[post]..p.offsets[post + 1]]
                .iter()
                .map(|&i| a[i])
                .sum::<f64>();
            assert_eq!(op.apply(&a)[cue * op.posts + post], direct);
        }
    }
    let l = op.interior_matrix(&(0..op.coordinates).collect::<Vec<_>>(), &a);
    assert_eq!(l.nrows(), 16 * op.posts + 1);
    for i in 0..op.coordinates {
        assert_eq!(l[(16 * op.posts, i)], a[i]);
    }
}
#[test]
fn thin_svd_rank_projection_pseudoinverse_and_null_identities() {
    for matrix in [
        DMatrix::from_row_slice(3, 4, &[1., 0., 1., 0., 0., 1., 0., 1., 2., 0., 2., 0.]),
        DMatrix::zeros(3, 4),
    ] {
        let (l, scales) = scale_rows(&matrix);
        for r in 0..l.nrows() {
            for c in 0..l.ncols() {
                assert_eq!(l[(r, c)], matrix[(r, c)] * scales[r]);
            }
        }
        let f = Factorization::new(&l).unwrap();
        assert_eq!(f.audit.rank, if matrix.norm() > 0. { 2 } else { 0 });
        assert_eq!(f.audit.nullity, 4 - f.audit.rank);
        assert_eq!(f.audit.singular_values.len(), 3);
        let x = vec![1., 3., 7., 2.];
        let p = f.project(&x);
        close(&f.project(&p), &p);
        let n: Vec<_> = x.iter().zip(&p).map(|(x, p)| x - p).collect();
        assert!(norm(&f.project(&n)) < 1e-10);
        assert!(dot(&p, &n).abs() < 1e-10);
        assert!((dot(&x, &x) - dot(&p, &p) - dot(&n, &n)).abs() < 1e-10);
        let b = (&l * nalgebra::DVector::from_column_slice(&x))
            .as_slice()
            .to_vec();
        close(&p, &f.pseudoinverse(&b));
        assert!((&l * nalgebra::DVector::from_column_slice(&n)).norm() < 1e-10);
        close(
            &x,
            &p.iter().zip(&n).map(|(p, n)| p + n).collect::<Vec<_>>(),
        );
    }
}
#[test]
fn nullity_floor_cases_and_bruteforce_circle() {
    assert_eq!(floors(0, 2., 0.).absolute_minimum, Some(1.));
    assert_eq!(floors(1, 1., 3.).absolute_minimum, Some(0.5));
    assert_eq!(floors(2, 3., 1.).absolute_minimum, Some(0.5));
    assert_eq!(floors(2, 1., 3.).absolute_minimum, Some(0.));
    assert_eq!(floors(2, 1., 3.).signed_minimum, Some(-0.5));
    assert!(floors(2, 0., 0.).zero_residual);
    for (fixed, free) in [(1., 3.), (3., 1.), (1., 1.)] {
        let actual = (0..100000)
            .map(|i| {
                let theta = i as f64 * std::f64::consts::TAU / 100000.;
                ((fixed + free * theta.cos()) / (fixed + free)).abs()
            })
            .fold(1., f64::min);
        assert!((actual - floors(2, fixed, free).absolute_minimum.unwrap()).abs() < 1e-4);
    }
}
#[test]
fn committed_partition_projection_and_deterministic_receipt() {
    // Each MBON retains every cue row, even when rows are dependent.
    let op = DriveOperator {
        cues: 16,
        posts: 2,
        coordinates: 6,
        rows: (0..32)
            .map(|r| {
                if r % 2 == 0 {
                    vec![0, 1, 2]
                } else {
                    vec![3, 4, 5]
                }
            })
            .collect(),
    };
    let s = Snapshot {
        trial: 1,
        base: vec![1.; 6],
        target: vec![0., 1.1, 1.2, 2., 1.3, 1.],
        axis: vec![1., 2., 3., 4., 5., 6.],
        permitted: vec![true, true, true, true, true, false],
    };
    let before = serde_json::to_vec(&s).unwrap();
    let (a, replay) = audit(&op, &s, &[1., 1.], true).unwrap();
    assert!(a.integrity.valid, "{:?}", a.integrity.normalized_errors);
    assert_eq!(a.fixed_boundary_count, 2);
    assert_eq!(a.interior_variable_count, 3);
    let replay = replay.unwrap();
    assert_eq!(replay.d_star[0], -1.);
    assert_eq!(replay.d_star[3], 1.);
    assert_eq!(replay.d_star[5], 0.);
    assert_eq!(replay.n_true[0], 0.);
    assert_eq!(replay.n_true[3], 0.);
    assert_eq!(replay.n_true[5], 0.);
    assert!(a.integrity.axis_null < 1e-10);
    let (b, _) = audit(&op, &s, &[1., 1.], false).unwrap();
    assert_eq!(
        serde_json::to_vec(&a).unwrap(),
        serde_json::to_vec(&b).unwrap()
    );
    assert_eq!(before, serde_json::to_vec(&s).unwrap());
}
#[test]
fn empty_interior_and_zero_axis_are_explicit() {
    let op = DriveOperator {
        cues: 16,
        posts: 1,
        coordinates: 1,
        rows: vec![vec![0]; 16],
    };
    let s = Snapshot {
        trial: 1,
        base: vec![1.],
        target: vec![0.],
        axis: vec![0.],
        permitted: vec![true],
    };
    let (a, _) = audit(&op, &s, &[1.], false).unwrap();
    assert!(a.integrity.valid);
    assert_eq!(a.combined_rank.rank, 0);
    assert_eq!(a.combined_rank.nullity, 0);
    assert_eq!(a.axis_projection, None);
    assert_eq!(a.floors.absolute_minimum, Some(1.));
}
