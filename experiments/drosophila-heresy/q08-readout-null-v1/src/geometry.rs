//! Feasible triple-circle rotations; all diagnostics use final committed f32.
use crate::capture::Snapshot;
use serde::Serialize;
use std::f64::consts::TAU;

pub const SWEEPS: usize = 8;
#[derive(Serialize)]
pub struct Audit {
    pub trial: usize,
    pub moves: usize,
    pub sweeps: usize,
    pub support: usize,
    pub rotatable_support: usize,
    pub true_nonzero: usize,
    pub null_nonzero: usize,
    pub true_lower: usize,
    pub true_upper: usize,
    pub null_lower: usize,
    pub null_upper: usize,
    pub boundary_symmetric_difference: usize,
    pub true_norm: f64,
    pub true_axial: f64,
    pub null_axial: f64,
    pub axial_absolute_error: f64,
    pub axial_error_over_total_norm: f64,
    pub axial_relative_error: Option<f64>,
    pub norm_relative_error: f64,
    pub residual_norm_relative_error: f64,
    pub residual_abs_cosine: Option<f64>,
    pub support_residual_abs_cosine: Option<f64>,
    pub max_bound_violation: f64,
    pub outside_support_changes: usize,
    pub minimum_found_not_global_optimum: bool,
    pub hot_allocations: u64,
}
pub struct Rotation {
    pub committed: Vec<f32>,
    d: Vec<f64>,
    pub(crate) original: Vec<f64>,
    pub(crate) support: Vec<usize>,
}
fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}
fn dot3(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
fn mix(mut x: u64) -> u64 {
    x = (x ^ (x >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    x ^ (x >> 31)
}
pub fn event_key(seed: u64, tau: f32, side: u8, trial: usize) -> u64 {
    let mut key = 0x5130_3742_4e56_3100;
    // One plasticity event per trial; include both fields explicitly.
    for field in [
        seed,
        u64::from(tau.to_bits()),
        u64::from(side),
        trial as u64,
        trial as u64,
    ] {
        key = mix(key ^ field);
    }
    key
}
fn next(state: &mut u64) -> u64 {
    *state = state.wrapping_add(0x9e37_79b9_7f4a_7c15);
    mix(*state)
}
fn add_angle(angles: &mut [f64; 16], len: &mut usize, x: f64) {
    angles[*len] = x.rem_euclid(TAU);
    *len += 1;
}
// Return the best feasible point on a three-coordinate circle. Bound roots
// partition the circle into intervals on which feasibility is constant.
fn rotate_triple(
    d: [f64; 3],
    a: [f64; 3],
    orig: [f64; 3],
    base: [f64; 3],
    global_residual_dot: f64,
) -> Option<[f64; 3]> {
    let an = dot3(a, a).sqrt();
    let au = if an > 0. {
        a.map(|x| x / an)
    } else {
        // With no axial constraint choose a deterministic auxiliary plane.
        let n = dot3(d, d).sqrt();
        if n == 0. {
            return None;
        }
        let seed = if d[0].abs() < d[1].abs() {
            [1., 0., 0.]
        } else {
            [0., 1., 0.]
        };
        let cross = [
            d[1] * seed[2] - d[2] * seed[1],
            d[2] * seed[0] - d[0] * seed[2],
            d[0] * seed[1] - d[1] * seed[0],
        ];
        let cn = dot3(cross, cross).sqrt();
        if cn == 0. {
            return None;
        }
        cross.map(|x| x / cn)
    };
    let axial = dot3(d, au);
    let c = au.map(|x| x * axial);
    let u = std::array::from_fn::<_, 3, _>(|i| d[i] - c[i]);
    if dot3(u, u) < 1e-30 {
        return None;
    }
    let v = [
        au[1] * u[2] - au[2] * u[1],
        au[2] * u[0] - au[0] * u[2],
        au[0] * u[1] - au[1] * u[0],
    ];
    let mut angles = [0.; 16];
    let mut len = 2;
    angles[1] = TAU;
    for i in 0..3 {
        let r = u[i].hypot(v[i]);
        if r == 0. {
            continue;
        }
        let phase = v[i].atan2(u[i]);
        for bound in [-base[i], 2. - base[i]] {
            let z = (bound - c[i]) / r;
            if (-1. ..=1.).contains(&z) {
                let h = z.acos();
                add_angle(&mut angles, &mut len, phase + h);
                add_angle(&mut angles, &mut len, phase - h);
            }
        }
    }
    angles[..len].sort_unstable_by(f64::total_cmp);
    let alpha = dot3(u, orig);
    let beta = dot3(v, orig);
    let constant = global_residual_dot - alpha;
    let radius = alpha.hypot(beta);
    let phase = beta.atan2(alpha);
    let mut best = global_residual_dot.abs();
    let mut chosen = None;
    for window in angles[..len].windows(2) {
        let lo = window[0];
        let hi = window[1];
        if hi - lo <= 1e-13 {
            continue;
        }
        let midpoint = (lo + hi) * 0.5;
        let feasible = |theta: f64| -> Option<[f64; 3]> {
            let (s, cs) = theta.sin_cos();
            let candidate = std::array::from_fn(|i| c[i] + u[i] * cs + v[i] * s);
            candidate
                .iter()
                .zip(base)
                .all(|(&x, b)| {
                    let target = b + x;
                    let stored = target as f32;
                    (0. ..=2.).contains(&target) && stored > 0. && stored < 2.
                })
                .then_some(candidate)
        };
        if feasible(midpoint).is_none() {
            continue;
        }
        let inset = (hi - lo) * 1e-9 + 1e-14;
        let mut probes = [
            midpoint,
            lo + inset,
            hi - inset,
            phase.rem_euclid(TAU),
            (phase + std::f64::consts::PI).rem_euclid(TAU),
            midpoint,
            midpoint,
        ];
        if radius > 0. && (-1. ..=1.).contains(&(-constant / radius)) {
            let h = (-constant / radius).acos();
            probes[5] = (phase + h).rem_euclid(TAU);
            probes[6] = (phase - h).rem_euclid(TAU);
        }
        for theta in probes {
            if theta < lo || theta > hi {
                continue;
            }
            if let Some(candidate) = feasible(theta) {
                let cost = (global_residual_dot + dot3(candidate, orig) - dot3(d, orig)).abs();
                if cost < best {
                    best = cost;
                    chosen = Some(candidate);
                }
            }
        }
    }
    chosen
}
impl Rotation {
    pub fn new(n: usize) -> Self {
        Self {
            committed: vec![0.; n],
            d: vec![0.; n],
            original: vec![0.; n],
            support: Vec::with_capacity(n),
        }
    }
    pub fn construct(&mut self, snapshot: &Snapshot, key: u64) -> Audit {
        self.support.clear();
        for i in 0..self.d.len() {
            let d = f64::from(snapshot.target[i]) - f64::from(snapshot.base[i]);
            assert!(
                snapshot.base[i].is_finite()
                    && snapshot.target[i].is_finite()
                    && snapshot.axis[i].is_finite()
            );
            assert!(
                (0. ..=2.).contains(&snapshot.base[i]) && (0. ..=2.).contains(&snapshot.target[i])
            );
            assert!(snapshot.permitted[i] || d == 0.);
            self.d[i] = d;
            self.original[i] = d;
            // Development revision 2: preserve exact true bound memberships.
            if snapshot.permitted[i] && snapshot.target[i] > 0. && snapshot.target[i] < 2. {
                self.support.push(i);
            }
        }
        let start_alloc = crate::allocations();
        let axis_sq = dot(&snapshot.axis, &snapshot.axis);
        let true_dot = dot(&self.original, &snapshot.axis);
        let axial_sq = if axis_sq > 0. {
            true_dot * true_dot / axis_sq
        } else {
            0.
        };
        let residual_sq = (dot(&self.original, &self.original) - axial_sq).max(0.);
        let mut global_dot = residual_sq;
        let mut moves = 0;
        let mut sweeps = 0;
        for sweep in 0..SWEEPS {
            if residual_sq == 0. || global_dot.abs() <= residual_sq * 1e-10 {
                break;
            }
            sweeps = sweep + 1;
            let mut rng = mix(key ^ sweep as u64);
            for i in (1..self.support.len()).rev() {
                let j = next(&mut rng) as usize % (i + 1);
                self.support.swap(i, j);
            }
            for ids in self.support.chunks_exact(3) {
                let ids = [ids[0], ids[1], ids[2]];
                let d = ids.map(|i| self.d[i]);
                let a = ids.map(|i| snapshot.axis[i]);
                let original = ids.map(|i| self.original[i]);
                let base = ids.map(|i| f64::from(snapshot.base[i]));
                if let Some(candidate) = rotate_triple(d, a, original, base, global_dot) {
                    global_dot += dot3(candidate, original) - dot3(d, original);
                    for i in 0..3 {
                        self.d[ids[i]] = candidate[i];
                    }
                    moves += 1;
                }
                if global_dot.abs() <= residual_sq * 1e-10 {
                    break;
                }
            }
        }
        for (i, out) in self.committed.iter_mut().enumerate() {
            let target = f64::from(snapshot.base[i]) + self.d[i];
            assert!((0. ..=2.).contains(&target), "rotation left weight box");
            *out = target as f32;
        }
        let hot_allocations = crate::allocations() - start_alloc;
        self.audit(snapshot, moves, sweeps, hot_allocations)
    }
    pub(crate) fn audit(
        &self,
        s: &Snapshot,
        moves: usize,
        sweeps: usize,
        hot_allocations: u64,
    ) -> Audit {
        let mut nr = 0.;
        let mut tr = 0.;
        let mut np = 0.;
        let mut tp = 0.;
        let mut axis_sq = 0.;
        let mut sa = 0.;
        let mut cross = 0.;
        let mut violation = 0_f64;
        let mut tn = 0;
        let mut nn = 0;
        let mut tl = 0;
        let mut tu = 0;
        let mut nl = 0;
        let mut nu = 0;
        let mut boundary_diff = 0;
        let mut outside = 0;
        for (i, &target) in self.committed.iter().enumerate() {
            violation = violation.max((-f64::from(target)).max(f64::from(target) - 2.).max(0.));
            let t = self.original[i];
            let n = f64::from(target) - f64::from(s.base[i]);
            let a = s.axis[i];
            tr += t * t;
            nr += n * n;
            tp += t * a;
            np += n * a;
            axis_sq += a * a;
            cross += t * n;
            if s.permitted[i] {
                sa += a * a;
            } else {
                outside += usize::from(target != s.base[i]);
            }
            tn += usize::from(t != 0.);
            nn += usize::from(n != 0.);
            tl += usize::from(s.target[i] == 0.);
            tu += usize::from(s.target[i] == 2.);
            nl += usize::from(target == 0.);
            nu += usize::from(target == 2.);
            boundary_diff += usize::from((target == 0.) != (s.target[i] == 0.))
                + usize::from((target == 2.) != (s.target[i] == 2.));
        }
        let axial = |p: f64| if axis_sq > 0. { p / axis_sq.sqrt() } else { 0. };
        let tp = axial(tp);
        let np = axial(np);
        let rt = (tr - tp * tp).max(0.).sqrt();
        let rn = (nr - np * np).max(0.).sqrt();
        let full_cos = (rt * rn > 0.).then(|| ((cross - tp * np) / (rt * rn)).abs());
        let st = (tr - if sa > 0. { tp * tp * axis_sq / sa } else { 0. })
            .max(0.)
            .sqrt();
        let sn = (nr - if sa > 0. { np * np * axis_sq / sa } else { 0. })
            .max(0.)
            .sqrt();
        let support_cos = (st * sn > 0.).then(|| {
            ((cross - if sa > 0. { tp * np * axis_sq / sa } else { 0. }) / (st * sn)).abs()
        });
        Audit {
            trial: s.trial,
            moves,
            sweeps,
            support: s.permitted.iter().filter(|&&v| v).count(),
            rotatable_support: self.support.len(),
            true_nonzero: tn,
            null_nonzero: nn,
            true_lower: tl,
            true_upper: tu,
            null_lower: nl,
            null_upper: nu,
            boundary_symmetric_difference: boundary_diff,
            true_norm: tr.sqrt(),
            true_axial: tp,
            null_axial: np,
            axial_absolute_error: (np - tp).abs(),
            axial_error_over_total_norm: (np - tp).abs() / tr.sqrt().max(1e-30),
            axial_relative_error: (tp.abs() > 1e-12).then(|| (np - tp).abs() / tp.abs()),
            norm_relative_error: (nr.sqrt() - tr.sqrt()).abs() / tr.sqrt().max(1e-30),
            residual_norm_relative_error: (rn - rt).abs() / rt.max(1e-30),
            residual_abs_cosine: full_cos,
            support_residual_abs_cosine: support_cos,
            max_bound_violation: violation,
            outside_support_changes: outside,
            minimum_found_not_global_optimum: true,
            hot_allocations,
        }
    }
}
