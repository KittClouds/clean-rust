//! Readout-preserving four-coordinate circles, with committed-f32 audits.
use crate::{capture::Snapshot, geometry, task::Task};
pub use geometry::Audit;
use serde::Serialize;
use std::f64::consts::TAU;
pub fn event_key(seed: u64, tau: f32, side: u8, trial: usize) -> u64 {
    mix(geometry::event_key(seed, tau, side, trial) ^ 0x513038524e563100)
}
const SWEEPS: usize = 8;
fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}
fn mix(mut x: u64) -> u64 {
    x = (x ^ (x >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94d049bb133111eb);
    x ^ (x >> 31)
}

#[derive(Default, Clone, Serialize)]
pub struct Budget {
    pub eligible_support: usize,
    pub interior_support: usize,
    pub groups: usize,
    pub rotatable_groups: usize,
    pub singleton_groups: usize,
    pub small_fixed_groups: usize,
    pub largest_group: usize,
    pub group_size_histogram: [usize; 9], // 1..8, then >=9
    pub rank_one_groups: usize,
    pub rank_two_groups: usize,
    pub nullspace_dimension: usize,
    pub total_energy: f64,
    pub fixed_energy: f64,
    pub rotatable_nullspace_energy: f64,
    pub all_group_nullspace_energy: f64,
    pub all_group_fixed_energy: f64,
    pub all_group_optimistic_residual_abs_cosine_floor: Option<f64>,
    pub residual_energy: f64,
    pub optimistic_cross_dot_min: f64,
    pub optimistic_cross_dot_max: f64,
    pub optimistic_residual_cross_dot_min: f64,
    pub optimistic_residual_cross_dot_max: f64,
    pub optimistic_residual_abs_cosine_floor: Option<f64>,
    pub structurally_overconstrained: bool,
    pub quadruples_considered: usize,
    pub rank_one_quadruples: usize,
    pub rank_two_quadruples: usize,
    pub zero_circle_quadruples: usize,
}
pub struct Rotation {
    pub committed: Vec<f32>,
    pub budget: Budget,
    geometry: geometry::Rotation,
    d: Vec<f64>,
    keys: Vec<u64>,
    order: Vec<usize>,
    groups: Vec<(usize, usize)>,
    initialized: bool,
    posts_initialized: bool,
}

// Orthonormal basis of span{ones, A}; rank loss is handled explicitly.
fn constraints(a: [f64; 4]) -> ([f64; 4], Option<[f64; 4]>) {
    let mean = a.iter().sum::<f64>() / 4.;
    let mut centered = a.map(|x| x - mean);
    // Reorthogonalize after cancellation when A is almost constant.
    let correction = centered.iter().sum::<f64>() / 4.;
    for x in &mut centered {
        *x -= correction;
    }
    let norm = dot(&centered, &centered).sqrt();
    ([0.5; 4], (norm > 0.).then(|| centered.map(|x| x / norm)))
}
fn circle(d: [f64; 4], a: [f64; 4]) -> Option<([f64; 4], [f64; 4], [f64; 4])> {
    let (one, axis) = constraints(a);
    let p = dot(&d, &one);
    let q = axis.map_or(0., |v| dot(&d, &v));
    let c = std::array::from_fn(|i| p * one[i] + q * axis.map_or(0., |v| v[i]));
    let u = std::array::from_fn(|i| d[i] - c[i]);
    let r = dot(&u, &u).sqrt();
    if r <= 1e-20 {
        return None;
    }
    let mut best = [0.; 4];
    let mut best_sq = 0.;
    for k in 0..4 {
        let mut v = [0.; 4];
        v[k] = 1.;
        let p = dot(&v, &one);
        for i in 0..4 {
            v[i] -= p * one[i];
        }
        if let Some(axis) = axis {
            let q = dot(&v, &axis);
            for i in 0..4 {
                v[i] -= q * axis[i];
            }
        }
        let q = dot(&v, &u) / (r * r);
        for i in 0..4 {
            v[i] -= q * u[i];
        }
        let sq = dot(&v, &v);
        if sq > best_sq {
            best_sq = sq;
            best = v;
        }
    }
    if best_sq < 1e-24 {
        return None;
    }
    Some((c, u, best.map(|x| x * r / best_sq.sqrt())))
}

fn rotate(
    d: [f64; 4],
    a: [f64; 4],
    orig: [f64; 4],
    base: [f64; 4],
    global: f64,
) -> Option<[f64; 4]> {
    let (c, u, v) = circle(d, a)?;
    let mut angles = [0.; 24];
    let mut len = 2;
    angles[1] = TAU;
    for i in 0..4 {
        let radius = u[i].hypot(v[i]);
        if radius == 0. {
            continue;
        }
        let phase = v[i].atan2(u[i]);
        for bound in [-base[i], 2. - base[i]] {
            let z = (bound - c[i]) / radius;
            if (-1. ..=1.).contains(&z) {
                for x in [phase + z.acos(), phase - z.acos()] {
                    angles[len] = x.rem_euclid(TAU);
                    len += 1;
                }
            }
        }
    }
    angles[..len].sort_unstable_by(f64::total_cmp);
    let alpha = dot(&u, &orig);
    let beta = dot(&v, &orig);
    let constant = global - dot(&d, &orig) + dot(&c, &orig);
    let phase = beta.atan2(alpha);
    let amplitude = alpha.hypot(beta);
    let mut chosen = None;
    let mut best = global.abs();
    for pair in angles[..len].windows(2) {
        let lo = pair[0];
        let hi = pair[1];
        let mut tests = [
            lo,
            hi,
            (lo + hi) / 2.,
            phase.rem_euclid(TAU),
            (phase + std::f64::consts::PI).rem_euclid(TAU),
            0.,
            0.,
        ];
        if amplitude > 0. && (-constant / amplitude).abs() <= 1. {
            let h = (-constant / amplitude).acos();
            tests[5] = (phase + h).rem_euclid(TAU);
            tests[6] = (phase - h).rem_euclid(TAU);
        }
        for theta in tests {
            if theta < lo || theta > hi {
                continue;
            }
            let (sn, cs) = theta.sin_cos();
            let candidate = std::array::from_fn(|i| c[i] + u[i] * cs + v[i] * sn);
            // Strict committed interior: boundary membership may never change.
            if (0..4).any(|i| {
                let w = (base[i] + candidate[i]) as f32;
                !(w > 0. && w < 2.)
            }) {
                continue;
            }
            let cost = (global + dot(&candidate, &orig) - dot(&d, &orig)).abs();
            if cost < best {
                best = cost;
                chosen = Some(candidate);
            }
        }
    }
    chosen
}

impl Rotation {
    pub fn new(n: usize) -> Self {
        Self {
            committed: vec![0.; n],
            budget: Budget::default(),
            geometry: geometry::Rotation::new(n),
            d: vec![0.; n],
            keys: vec![0; n],
            order: Vec::with_capacity(n),
            groups: Vec::with_capacity(n),
            initialized: false,
            posts_initialized: false,
        }
    }
    fn prepare(&mut self, task: &Task, post_len: usize) {
        if self.initialized {
            return;
        }
        assert_eq!(task.cues, 16);
        assert!(self.posts_initialized);
        // Edge IDs are dense; no map or model RNG is required.
        for cue in 0..16 {
            let p = &task.patterns[cue];
            for post in 0..post_len {
                for &i in &p.edges[p.offsets[post]..p.offsets[post + 1]] {
                    self.keys[i] |= 1 << cue;
                }
            }
        }
        // All coordinates, including signature zero, need their MBON ID.
        // Graph rows are contiguous. Task patterns do not cover signature-zero
        // edges, so row endpoints are supplied separately through set_posts.
        self.initialized = true;
    }
    pub fn set_posts(&mut self, posts: impl Iterator<Item = usize>) {
        assert!(!self.posts_initialized && !self.initialized);
        let mut count = 0;
        for (key, post) in self.keys.iter_mut().zip(posts) {
            *key = (post as u64) << 16;
            count += 1;
        }
        assert_eq!(count, self.keys.len());
        self.posts_initialized = true;
    }
    pub fn construct(&mut self, s: &Snapshot, key: u64, task: &Task, post_len: usize) -> Audit {
        let start = crate::allocations();
        self.prepare(task, post_len);
        self.order.clear();
        self.groups.clear();
        self.geometry.support.clear();
        self.budget = Budget::default();
        for i in 0..self.d.len() {
            let d = f64::from(s.target[i]) - f64::from(s.base[i]);
            self.d[i] = d;
            self.geometry.original[i] = d;
            self.budget.total_energy += d * d;
            if s.permitted[i] {
                self.budget.eligible_support += 1;
                if s.target[i] > 0. && s.target[i] < 2. {
                    self.order.push(i);
                    self.geometry.support.push(i);
                }
            }
        }
        self.budget.interior_support = self.order.len();
        self.order.sort_unstable_by_key(|&i| (self.keys[i], i));
        let mut lo = 0;
        while lo < self.order.len() {
            let mut hi = lo + 1;
            while hi < self.order.len() && self.keys[self.order[hi]] == self.keys[self.order[lo]] {
                hi += 1;
            }
            self.groups.push((lo, hi));
            lo = hi;
        }
        self.budget.groups = self.groups.len();
        for &(lo, hi) in &self.groups {
            let n = hi - lo;
            self.budget.largest_group = self.budget.largest_group.max(n);
            self.budget.group_size_histogram[(n - 1).min(8)] += 1;
            self.budget.singleton_groups += usize::from(n == 1);
            let ids = &self.order[lo..hi];
            let sum = ids.iter().map(|&i| self.d[i]).sum::<f64>();
            let mean = ids.iter().map(|&i| s.axis[i]).sum::<f64>() / n as f64;
            let a_sq = ids.iter().map(|&i| (s.axis[i] - mean).powi(2)).sum::<f64>();
            let a_dot = ids
                .iter()
                .map(|&i| self.d[i] * (s.axis[i] - mean))
                .sum::<f64>();
            let energy = ids.iter().map(|&i| self.d[i] * self.d[i]).sum::<f64>();
            let rank = if a_sq > 0. { 2 } else { 1 };
            self.budget.rank_one_groups += usize::from(rank == 1);
            self.budget.rank_two_groups += usize::from(rank == 2);
            self.budget.nullspace_dimension += n - rank;
            let null_energy =
                (energy - sum * sum / n as f64 - if a_sq > 0. { a_dot * a_dot / a_sq } else { 0. })
                    .max(0.);
            self.budget.all_group_nullspace_energy += null_energy;
            if n < 4 {
                self.budget.small_fixed_groups += 1;
                continue;
            }
            self.budget.rotatable_groups += 1;
            self.budget.rotatable_nullspace_energy += null_energy;
        }
        self.budget.fixed_energy =
            (self.budget.total_energy - self.budget.rotatable_nullspace_energy).max(0.);
        let axis_sq = dot(&s.axis, &s.axis);
        let p = dot(&self.d, &s.axis);
        let axial_sq = if axis_sq > 0. { p * p / axis_sq } else { 0. };
        let residual = (self.budget.total_energy - axial_sq).max(0.);
        self.budget.residual_energy = residual;
        self.budget.all_group_fixed_energy =
            (self.budget.total_energy - self.budget.all_group_nullspace_energy).max(0.);
        self.budget.all_group_optimistic_residual_abs_cosine_floor = (residual > 0.)
            .then(|| (residual - 2. * self.budget.all_group_nullspace_energy).max(0.) / residual);
        self.budget.optimistic_cross_dot_min =
            self.budget.fixed_energy - self.budget.rotatable_nullspace_energy;
        self.budget.optimistic_cross_dot_max = self.budget.total_energy;
        let low = self.budget.optimistic_cross_dot_min - axial_sq;
        let high = residual;
        self.budget.optimistic_residual_cross_dot_min = low;
        self.budget.optimistic_residual_cross_dot_max = high;
        self.budget.optimistic_residual_abs_cosine_floor =
            (residual > 0.).then(|| if low <= 0. { 0. } else { low / residual });
        self.budget.structurally_overconstrained = self
            .budget
            .optimistic_residual_abs_cosine_floor
            .is_some_and(|c| c > 1e-5);
        let mut global = residual;
        let mut moves = 0;
        let mut sweeps = 0;
        for sweep in 0..SWEEPS {
            if residual == 0. || global.abs() <= residual * 1e-10 {
                break;
            }
            sweeps = sweep + 1;
            let mut rng = mix(key ^ sweep as u64);
            for &(lo, hi) in &self.groups {
                for i in (lo + 1..hi).rev() {
                    rng = mix(rng.wrapping_add(0x9e3779b97f4a7c15));
                    let j = lo + rng as usize % (i - lo + 1);
                    self.order.swap(i, j);
                }
                for ids in self.order[lo..hi].chunks_exact(4) {
                    let ids = [ids[0], ids[1], ids[2], ids[3]];
                    let d = ids.map(|i| self.d[i]);
                    let a = ids.map(|i| s.axis[i]);
                    let original = ids.map(|i| self.geometry.original[i]);
                    let base = ids.map(|i| f64::from(s.base[i]));
                    self.budget.quadruples_considered += 1;
                    if constraints(a).1.is_some() {
                        self.budget.rank_two_quadruples += 1;
                    } else {
                        self.budget.rank_one_quadruples += 1;
                    }
                    if circle(d, a).is_none() {
                        self.budget.zero_circle_quadruples += 1;
                        continue;
                    }
                    if let Some(candidate) = rotate(d, a, original, base, global) {
                        global += dot(&candidate, &original) - dot(&d, &original);
                        for i in 0..4 {
                            self.d[ids[i]] = candidate[i];
                        }
                        moves += 1;
                    }
                }
            }
        }
        for i in 0..self.d.len() {
            self.committed[i] = if s.permitted[i] && s.target[i] > 0. && s.target[i] < 2. {
                (f64::from(s.base[i]) + self.d[i]) as f32
            } else {
                s.target[i]
            };
        }
        self.geometry.committed.copy_from_slice(&self.committed);
        self.geometry
            .audit(s, moves, sweeps, crate::allocations() - start)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn circles_preserve_both_linear_constraints_and_energy_for_all_ranks() {
        for a in [[1., 2., 3., 4.], [2.; 4], [0.; 4], [1., 1., 1., 1.00001]] {
            let d = [0.2, -0.1, 0.05, 0.3];
            let (c, u, v) = circle(d, a).unwrap();
            for angle in [0_f64, 0.2, 1., 2.8, 4.5] {
                let (sn, cs) = angle.sin_cos();
                let n = std::array::from_fn::<_, 4, _>(|i| c[i] + u[i] * cs + v[i] * sn);
                assert!((d.iter().sum::<f64>() - n.iter().sum::<f64>()).abs() < 1e-12);
                assert!((dot(&d, &a) - dot(&n, &a)).abs() < 1e-12);
                assert!((dot(&d, &d) - dot(&n, &n)).abs() < 1e-12);
            }
        }
    }
    fn task(n: usize) -> Task {
        Task {
            patterns: (0..16)
                .map(|_| crate::task::Pattern {
                    edges: (0..n).collect(),
                    offsets: vec![0, n],
                    dan: vec![],
                    active_kc: vec![],
                })
                .collect(),
            cues: 16,
            labels: vec![false; 16],
            schedule: vec![],
        }
    }
    #[test]
    fn optimistic_budget_detects_fixed_component_floor_without_gate_rescue() {
        let s = Snapshot {
            trial: 1,
            base: vec![1.; 8],
            target: vec![1.1; 8],
            axis: vec![0.; 8],
            permitted: vec![true; 8],
        };
        let mut r = Rotation::new(8);
        r.set_posts((0..8).map(|_| 0));
        let a = r.construct(&s, 1, &task(8), 1);
        assert!(r.budget.rotatable_nullspace_energy < 1e-14);
        assert!((r.budget.optimistic_residual_abs_cosine_floor.unwrap() - 1.).abs() < 1e-12);
        assert!(r.budget.structurally_overconstrained);
        assert_eq!(a.hot_allocations, 0);
    }
    #[test]
    fn deterministic_committed_rotations_preserve_group_drive_and_bound_membership() {
        let n = 120;
        let s = Snapshot {
            trial: 1,
            base: vec![1.; n],
            target: (0..n).map(|i| if i % 2 == 0 { 1.1 } else { 0.9 }).collect(),
            axis: (0..n).map(|i| (i % 7) as f64 - 3.).collect(),
            permitted: vec![true; n],
        };
        let t = task(n);
        let mut r = Rotation::new(n);
        r.set_posts((0..n).map(|_| 0));
        let a = r.construct(&s, 19, &t, 1);
        let saved = r.committed.clone();
        assert_eq!(a.hot_allocations, 0);
        assert_eq!(a.boundary_symmetric_difference, 0);
        assert_eq!(a.outside_support_changes, 0);
        assert!(a.norm_relative_error.is_finite());
        assert!(r.committed.iter().all(|w| w.is_finite()));
        assert!(
            (s.target.iter().map(|&x| f64::from(x)).sum::<f64>()
                - r.committed.iter().map(|&x| f64::from(x)).sum::<f64>())
            .abs()
                < 1e-5
        );
        r.construct(&s, 19, &t, 1);
        assert_eq!(saved, r.committed);
    }
    #[test]
    fn dense_group_keys_include_all_posts_and_exact_cue_memberships() {
        let g = crate::graph::Graph::fixture();
        let task = Task::new(&g, 9200, 16, 12, 512);
        let mut r = Rotation::new(g.kc_mb.edges.len());
        r.set_posts(g.kc_mb.edges.iter().map(|e| e.post as usize));
        r.prepare(&task, g.kc_mb.n_post);
        for (i, e) in g.kc_mb.edges.iter().enumerate() {
            assert_eq!(r.keys[i] >> 16, u64::from(e.post));
            let signature = (0..16).fold(0_u64, |s, cue| {
                s | if task.patterns[cue].edges.contains(&i) {
                    1 << cue
                } else {
                    0
                }
            });
            assert_eq!(r.keys[i] & 65535, signature);
        }
    }
    #[test]
    fn boundary_and_zero_residual_cases_stay_fixed_and_are_not_decorrelated() {
        for target in [0_f32, 2., 1.] {
            let s = Snapshot {
                trial: 1,
                base: vec![target; 8],
                target: vec![target; 8],
                axis: vec![1.; 8],
                permitted: vec![true; 8],
            };
            let mut r = Rotation::new(8);
            r.set_posts((0..8).map(|_| 0));
            let a = r.construct(&s, 1, &task(8), 1);
            assert_eq!(r.committed, s.target);
            assert_eq!(a.boundary_symmetric_difference, 0);
            assert_eq!(a.residual_abs_cosine, None);
            assert_eq!(r.budget.residual_energy, 0.);
            assert_eq!(a.hot_allocations, 0);
        }
    }
}
