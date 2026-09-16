use crate::{capture::Snapshot, graph::Graph, linear::*, task::Task};
use nalgebra::DMatrix;

fn close(a: &[f64], b: &[f64]) {
    assert_eq!(a.len(), b.len());
    assert!(norm(&a.iter().zip(b).map(|(x, y)| x - y).collect::<Vec<_>>()) < 1e-10);
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
