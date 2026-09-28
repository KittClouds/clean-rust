//! Q10-SM Stage 1: continuous bounded geometry with an f32 safety reserve.
//!
//! The constructor starts from the committed true null component and moves on
//! a fixed-norm geodesic in the same linear nullspace.  It performs only the
//! diagnostic f32 storage conversion required by the safety receipt and never
//! runs a scientific seed.  Stage 2 is a separate protocol because sequential
//! f32 readout is a different seam.
use crate::{
    graph::Graph,
    linear::{self, DriveOperator, Factorization},
    policy::Policy,
    simulation::{Dh07Condition, Simulator},
    task::Task,
};
use anyhow::{Context, Result, ensure};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
};

const PROTOCOL: &str = "Q10-SM";
const SEED_A: &[u64] = &[9401];
const SEEDS_B: &[u64] = &[9402, 9403, 9404, 9405];
const STAGE_A_STATES: usize = 1024;
const STAGE_B_STATES: usize = 4096;
const CANDIDATES: usize = 8;
const BISECTIONS: usize = 32;
const ZERO_NORM_SQ: f64 = 1.0e-24;
const NUMERIC_TOLERANCE: f64 = 2.0e-10;
const FREEDOM_ANGLE_EPS: f64 = 1.0e-8;
const RESERVE_ULPS: u32 = 32;
const WEIGHT_MIN: f64 = 0.0;
const WEIGHT_MAX: f64 = 2.0;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    stage: String,
    observe: bool,
    seeds: Vec<u64>,
    taus: Vec<f32>,
    sides: Vec<String>,
    conditions: Vec<String>,
    arms: Vec<String>,
    cues: usize,
    delay_steps: usize,
    trials: usize,
    eta: f32,
    glut_sign: f32,
    input_salt: u64,
    threads: usize,
    candidate_directions: usize,
    angle_bisections: usize,
    reserve_ulps: u32,
}

fn validate_config(config: &Config) -> Result<&'static [u64]> {
    ensure!(config.stage == "stage1-a" || config.stage == "stage1-b");
    let seeds = if config.stage == "stage1-a" {
        SEED_A
    } else {
        SEEDS_B
    };
    ensure!(
        config.seeds == seeds,
        "unauthorized Q10 engineering seed set"
    );
    ensure!(config.observe && config.taus == [4.0, 16.0] && config.sides == ["R", "L"]);
    ensure!(config.conditions == ["true_perpendicular"] && config.arms == ["E", "Z"]);
    ensure!(config.cues == 16 && config.delay_steps == 12 && config.trials == 512);
    ensure!(config.eta == 0.05 && config.glut_sign == -1.0 && config.input_salt == 858980352);
    ensure!(config.threads == 8);
    ensure!(config.candidate_directions == CANDIDATES);
    ensure!(config.angle_bisections == BISECTIONS);
    ensure!(config.reserve_ulps == RESERVE_ULPS);
    Ok(seeds)
}

fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let mut writer = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(path)?);
    serde_json::to_writer_pretty(&mut writer, value)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

fn source_manifest(root: &Path) -> Result<Vec<Value>> {
    fn visit(root: &Path, dir: &Path, paths: &mut Vec<PathBuf>) -> Result<()> {
        for entry in std::fs::read_dir(dir)? {
            let path = entry?.path();
            if path.is_dir() {
                visit(root, &path, paths)?;
            } else if path.extension().is_some_and(|x| x == "rs") {
                paths.push(path.strip_prefix(root)?.to_owned());
            }
        }
        Ok(())
    }
    let mut paths = vec![
        PathBuf::from("Cargo.toml"),
        PathBuf::from("Cargo.lock"),
        PathBuf::from("PLAN.md"),
        PathBuf::from("CONTRACT.json"),
    ];
    visit(root, &root.join("src"), &mut paths)?;
    paths.sort();
    paths
        .iter()
        .map(|path| {
            Ok(json!({"path": path, "sha256": hash_bytes(&std::fs::read(root.join(path))?)}))
        })
        .collect()
}

fn mix(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e3779b97f4a7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
    value ^ (value >> 31)
}

fn unit_from_key(key: u64) -> f64 {
    let mantissa = mix(key) >> 11;
    (mantissa as f64 / (1_u64 << 53) as f64) * 2.0 - 1.0
}

fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}

fn norm(values: &[f64]) -> f64 {
    dot(values, values).sqrt()
}

fn max_abs(values: &[f64]) -> f64 {
    values.iter().map(|x| x.abs()).fold(0.0, f64::max)
}

fn cosine_between(a: &[f64], b: &[f64]) -> f64 {
    let denominator = norm(a) * norm(b);
    if denominator > 0.0 {
        dot(a, b) / denominator
    } else {
        1.0
    }
}

fn candidate_tangent(factor: &Factorization, z_true: &[f64], key: u64) -> Option<Vec<f64>> {
    let mut raw = Vec::with_capacity(z_true.len());
    for i in 0..z_true.len() {
        raw.push(unit_from_key(
            key ^ (i as u64).wrapping_mul(0xd6e8_feb8_6659_fd93),
        ));
    }
    let row_part = factor.project(&raw);
    for (value, row) in raw.iter_mut().zip(row_part) {
        *value -= row;
    }
    let coefficient = dot(&raw, z_true) / dot(z_true, z_true);
    for (value, z) in raw.iter_mut().zip(z_true) {
        *value -= coefficient * z;
    }
    let length = norm(&raw);
    (length * length > ZERO_NORM_SQ).then(|| {
        let scale = norm(z_true) / length;
        raw.into_iter().map(|value| value * scale).collect()
    })
}

fn endpoint_for_angle(center: &[f64], z_true: &[f64], tangent: &[f64], theta: f64) -> Vec<f64> {
    let (sin, cos) = theta.sin_cos();
    center
        .iter()
        .zip(z_true)
        .zip(tangent)
        .map(|((c, z), v)| c + z * cos + v * sin)
        .collect()
}

fn nextafter32(value: f32, toward_lower: bool) -> f32 {
    assert!(value.is_finite() && value > 0.0 && value < 2.0);
    let bits = value.to_bits();
    if toward_lower {
        f32::from_bits(bits - 1)
    } else {
        f32::from_bits(bits + 1)
    }
}

fn ulp32_spacings(value: f32) -> (f64, f64) {
    let down = f64::from(value) - f64::from(nextafter32(value, true));
    let up = f64::from(nextafter32(value, false)) - f64::from(value);
    assert!(down.is_finite() && down > 0.0 && up.is_finite() && up > 0.0);
    (down, up)
}

fn safety_bounds(reference: f32) -> (f64, f64) {
    let (down, up) = ulp32_spacings(reference);
    (
        WEIGHT_MIN + f64::from(RESERVE_ULPS) * down,
        WEIGHT_MAX - f64::from(RESERVE_ULPS) * up,
    )
}

fn safety_slack(value: f64, reference: f32) -> f64 {
    let (lower, upper) = safety_bounds(reference);
    (value - lower).min(upper - value)
}

fn feasible(endpoint: &[f64], interior: &[usize], references: &[f32]) -> bool {
    endpoint.iter().zip(interior).all(|(value, &i)| {
        let (lower, upper) = safety_bounds(references[i]);
        value.is_finite() && *value >= lower && *value <= upper
    })
}

fn interior_steps(value: f32, toward_lower: bool) -> u32 {
    let mut current = value;
    let mut steps = 0;
    while steps < RESERVE_ULPS {
        let next = nextafter32(current, toward_lower);
        if !next.is_finite() || f64::from(next) <= WEIGHT_MIN || f64::from(next) >= WEIGHT_MAX {
            break;
        }
        current = next;
        steps += 1;
    }
    steps
}

fn committed_f32_safe(endpoint: &[f64], interior: &[usize], references: &[f32]) -> bool {
    endpoint.iter().zip(interior).all(|(value, &i)| {
        let committed = *value as f32;
        let (lower, upper) = safety_bounds(references[i]);
        committed.is_finite()
            && f64::from(committed) >= lower
            && f64::from(committed) <= upper
            && !boundary(committed)
            && interior_steps(committed, true) >= RESERVE_ULPS
            && interior_steps(committed, false) >= RESERVE_ULPS
    })
}

fn best_rotation(
    center: &[f64],
    z_true: &[f64],
    factor: &Factorization,
    key: u64,
    interior: &[usize],
    references: &[f32],
) -> Option<(Vec<f64>, f64, usize, u64, usize)> {
    let true_norm = norm(z_true);
    if true_norm * true_norm <= ZERO_NORM_SQ || factor.audit.nullity < 2 {
        return None;
    }
    let mut best: Option<(Vec<f64>, f64, usize, u64, usize)> = None;
    let mut degeneracies = 0;
    for candidate in 0..CANDIDATES {
        for (sign_index, sign) in [1.0, -1.0].into_iter().enumerate() {
            let Some(mut tangent) = candidate_tangent(
                factor,
                z_true,
                key ^ (candidate as u64).wrapping_mul(0xa076_1d64_78bd_642f),
            ) else {
                degeneracies += 1;
                continue;
            };
            if sign < 0.0 {
                tangent.iter_mut().for_each(|value| *value = -*value);
            }
            let high = std::f64::consts::FRAC_PI_2;
            let at_high = endpoint_for_angle(center, z_true, &tangent, high);
            let at_high_safe = feasible(&at_high, interior, references)
                && committed_f32_safe(&at_high, interior, references);
            let at_zero = endpoint_for_angle(center, z_true, &tangent, 0.0);
            if !feasible(&at_zero, interior, references)
                || !committed_f32_safe(&at_zero, interior, references)
            {
                continue;
            }
            let theta = if at_high_safe {
                high
            } else {
                let mut low = 0.0;
                let mut high = high;
                for _ in 0..BISECTIONS {
                    let middle = (low + high) * 0.5;
                    let endpoint = endpoint_for_angle(center, z_true, &tangent, middle);
                    if feasible(&endpoint, interior, references)
                        && committed_f32_safe(&endpoint, interior, references)
                    {
                        low = middle;
                    } else {
                        high = middle;
                    }
                }
                low
            };
            let (sin, cos) = theta.sin_cos();
            let residual = z_true
                .iter()
                .zip(&tangent)
                .map(|(z, v)| z * cos + v * sin)
                .collect();
            let score = theta.cos().abs();
            if best
                .as_ref()
                .is_none_or(|(_, old_score, _, _, _)| score < *old_score)
            {
                let candidate_key = key
                    ^ (candidate as u64).wrapping_mul(0xa076_1d64_78bd_642f)
                    ^ sign_index as u64;
                best = Some((
                    residual,
                    score,
                    candidate * 2 + sign_index,
                    candidate_key,
                    degeneracies,
                ));
            }
        }
    }
    best.map(|(endpoint, cosine, candidate, candidate_key, _)| {
        (endpoint, cosine, candidate, candidate_key, degeneracies)
    })
}

fn boundary(value: f32) -> bool {
    lower_boundary(value) || upper_boundary(value)
}

fn lower_boundary(value: f32) -> bool {
    value.to_bits() == 0.0_f32.to_bits()
}

fn upper_boundary(value: f32) -> bool {
    value.to_bits() == 2.0_f32.to_bits()
}

#[derive(Clone, Serialize)]
pub(crate) struct Event {
    trial: usize,
    support_count: usize,
    interior_variable_count: usize,
    fixed_boundary_count: usize,
    combined_rank: usize,
    combined_nullity: usize,
    true_norm: f64,
    constrained_norm: f64,
    true_null_norm: f64,
    alternate_norm: f64,
    rotation_angle: f64,
    residual_cosine: f64,
    candidate_index: usize,
    candidate_key: u64,
    candidate_count: usize,
    degeneracy_count: usize,
    minimum_interior_slack: f64,
    true_minimum_safety_slack: f64,
    continuous_minimum_down_surplus: f64,
    continuous_minimum_up_surplus: f64,
    continuous_minimum_down_surplus_ulps: f64,
    continuous_minimum_up_surplus_ulps: f64,
    minimum_safety_slack: f64,
    reserve_ulps: u32,
    limiting_coordinate: usize,
    cue_drive_max_abs_error: f64,
    normalized_cue_drive_error: f64,
    axis_displacement_error: f64,
    normalized_axis_error: f64,
    null_annihilation_max_abs: f64,
    normalized_null_annihilation_error: f64,
    total_norm_error: f64,
    normalized_total_norm_error: f64,
    reconstruction_error: f64,
    normalized_reconstruction_error: f64,
    outside_support_changes: usize,
    boundary_membership_symmetric_difference: usize,
    lower_boundary_membership_difference: usize,
    upper_boundary_membership_difference: usize,
    new_boundary_memberships: usize,
    bounds_violation_count: usize,
    f32_safety_violation_count: usize,
    f32_boundary_membership_symmetric_difference: usize,
    f32_lower_boundary_membership_difference: usize,
    f32_upper_boundary_membership_difference: usize,
    f32_new_boundary_memberships: usize,
    f32_minimum_safety_slack: f64,
    f32_minimum_down_steps_capped: u32,
    f32_minimum_up_steps_capped: u32,
    f32_cue_drive_drift: f64,
    f32_axis_drift: f64,
    f32_total_norm_drift: f64,
    f32_storage_displacement_drift: f64,
    f32_residual_cosine_drift: f64,
    exhaustion_status: &'static str,
    pub(crate) status: &'static str,
    f32_commit_status: &'static str,
}

#[derive(Serialize)]
struct Replay {
    snapshot: crate::capture::Snapshot,
    operator: DriveOperator,
    interior_indices: Vec<usize>,
    true_displacement: Vec<f64>,
    constrained_displacement: Vec<f64>,
    true_null: Vec<f64>,
    alternate_null: Vec<f64>,
    event: Event,
}

pub(crate) struct Analysis {
    pub(crate) event: Event,
    pub(crate) interior_indices: Vec<usize>,
    pub(crate) true_displacement: Vec<f64>,
    pub(crate) constrained_displacement: Vec<f64>,
    pub(crate) true_null: Vec<f64>,
    pub(crate) alternate_null: Vec<f64>,
}

pub(crate) fn analyze_event(
    op: &DriveOperator,
    snapshot: &crate::capture::Snapshot,
    key: u64,
) -> Result<Analysis> {
    let n = snapshot.base.len();
    let true_d: Vec<_> = snapshot
        .target
        .iter()
        .zip(&snapshot.base)
        .map(|(&target, &base)| f64::from(target) - f64::from(base))
        .collect();
    ensure!(snapshot.axis.len() == n && snapshot.permitted.len() == n);
    let mut fixed = vec![0.0; n];
    let mut interior = Vec::new();
    for i in 0..n {
        ensure!(
            !snapshot.permitted[i] || true_d[i] != 0.0 || snapshot.target[i] == snapshot.base[i]
        );
        if snapshot.permitted[i] && boundary(snapshot.target[i]) {
            fixed[i] = true_d[i];
        } else if snapshot.permitted[i] {
            interior.push(i);
        } else {
            ensure!(true_d[i] == 0.0);
        }
    }
    let matrix = op.interior_matrix(&interior, &snapshot.axis);
    let (scaled, _scales) = linear::scale_rows(&matrix);
    let factor = Factorization::new(&scaled)?;
    let x_true: Vec<_> = interior.iter().map(|&i| true_d[i]).collect();
    let x_star = factor.project(&x_true);
    let z_true: Vec<_> = x_true
        .iter()
        .zip(&x_star)
        .map(|(x, star)| x - star)
        .collect();
    let mut constrained = fixed.clone();
    let mut true_null = vec![0.0; n];
    for (j, &i) in interior.iter().enumerate() {
        constrained[i] = x_star[j];
        true_null[i] = z_true[j];
    }
    let center: Vec<_> = interior
        .iter()
        .map(|&i| f64::from(snapshot.base[i]) + constrained[i])
        .collect();
    let mut true_down_surplus = f64::INFINITY;
    let mut true_up_surplus = f64::INFINITY;
    let mut true_down_surplus_ulps = f64::INFINITY;
    let mut true_up_surplus_ulps = f64::INFINITY;
    for &i in &interior {
        let (down_ulp, up_ulp) = ulp32_spacings(snapshot.target[i]);
        let (lower, upper) = safety_bounds(snapshot.target[i]);
        let value = f64::from(snapshot.target[i]);
        true_down_surplus = true_down_surplus.min(value - lower);
        true_up_surplus = true_up_surplus.min(upper - value);
        true_down_surplus_ulps = true_down_surplus_ulps.min((value - lower) / down_ulp);
        true_up_surplus_ulps = true_up_surplus_ulps.min((upper - value) / up_ulp);
    }
    let Some((alternate_x, cosine, candidate_index, candidate_key, degeneracy_count)) =
        best_rotation(&center, &z_true, &factor, key, &interior, &snapshot.target)
    else {
        let event = Event {
            trial: snapshot.trial,
            support_count: snapshot.permitted.iter().filter(|&&x| x).count(),
            interior_variable_count: interior.len(),
            fixed_boundary_count: snapshot.target.iter().filter(|&&x| boundary(x)).count(),
            combined_rank: factor.audit.rank,
            combined_nullity: factor.audit.nullity,
            true_norm: norm(&true_d),
            constrained_norm: norm(&constrained),
            true_null_norm: norm(&true_null),
            alternate_norm: 0.0,
            rotation_angle: 0.0,
            residual_cosine: 1.0,
            candidate_index: 0,
            candidate_key: 0,
            candidate_count: CANDIDATES * 2,
            degeneracy_count: CANDIDATES * 2,
            minimum_interior_slack: 0.0,
            true_minimum_safety_slack: true_down_surplus.min(true_up_surplus),
            continuous_minimum_down_surplus: true_down_surplus,
            continuous_minimum_up_surplus: true_up_surplus,
            continuous_minimum_down_surplus_ulps: true_down_surplus_ulps,
            continuous_minimum_up_surplus_ulps: true_up_surplus_ulps,
            minimum_safety_slack: 0.0,
            reserve_ulps: RESERVE_ULPS,
            limiting_coordinate: usize::MAX,
            cue_drive_max_abs_error: 0.0,
            normalized_cue_drive_error: 0.0,
            axis_displacement_error: 0.0,
            normalized_axis_error: 0.0,
            null_annihilation_max_abs: 0.0,
            normalized_null_annihilation_error: 0.0,
            total_norm_error: 0.0,
            normalized_total_norm_error: 0.0,
            reconstruction_error: 0.0,
            normalized_reconstruction_error: 0.0,
            outside_support_changes: 0,
            boundary_membership_symmetric_difference: 0,
            lower_boundary_membership_difference: 0,
            upper_boundary_membership_difference: 0,
            new_boundary_memberships: 0,
            bounds_violation_count: 0,
            f32_safety_violation_count: 0,
            f32_boundary_membership_symmetric_difference: 0,
            f32_lower_boundary_membership_difference: 0,
            f32_upper_boundary_membership_difference: 0,
            f32_new_boundary_memberships: 0,
            f32_minimum_safety_slack: 0.0,
            f32_minimum_down_steps_capped: 0,
            f32_minimum_up_steps_capped: 0,
            f32_cue_drive_drift: 0.0,
            f32_axis_drift: 0.0,
            f32_total_norm_drift: 0.0,
            f32_storage_displacement_drift: 0.0,
            f32_residual_cosine_drift: 0.0,
            exhaustion_status: "NO_SAFE_CANDIDATE",
            status: "Q10_SM_STAGE1_VALID__SAFETY_MARGIN_DOMINATED",
            f32_commit_status: "NOT_CONSTRUCTED",
        };
        return Ok(Analysis {
            event,
            interior_indices: interior,
            true_displacement: true_d,
            constrained_displacement: constrained,
            true_null,
            alternate_null: vec![0.0; n],
        });
    };
    let mut alternate_d = constrained.clone();
    let mut alternate_null = vec![0.0; n];
    for (j, &i) in interior.iter().enumerate() {
        alternate_d[i] += alternate_x[j];
        alternate_null[i] = alternate_x[j];
    }
    let theta = cosine.acos();
    let drive_true = op.apply(&true_d);
    let drive_alt = op.apply(&alternate_d);
    let drive_error: Vec<_> = drive_alt
        .iter()
        .zip(&drive_true)
        .map(|(a, t)| a - t)
        .collect();
    let null_drive = op.apply(&alternate_null);
    let axis_error = dot(&alternate_d, &snapshot.axis) - dot(&true_d, &snapshot.axis);
    let mut outside = 0;
    let mut boundary_diff = 0;
    let mut lower_boundary_diff = 0;
    let mut upper_boundary_diff = 0;
    let mut new_boundary = 0;
    let mut bounds = 0;
    let mut minimum_slack = f64::INFINITY;
    let mut minimum_down_surplus = f64::INFINITY;
    let mut minimum_up_surplus = f64::INFINITY;
    let mut minimum_down_surplus_ulps = f64::INFINITY;
    let mut minimum_up_surplus_ulps = f64::INFINITY;
    let mut minimum_safety = f64::INFINITY;
    let mut f32_safety_violations = 0;
    let mut f32_boundary_diff = 0;
    let mut f32_lower_boundary_diff = 0;
    let mut f32_upper_boundary_diff = 0;
    let mut f32_new_boundary = 0;
    let mut f32_minimum_safety = f64::INFINITY;
    let mut f32_minimum_down_steps = RESERVE_ULPS;
    let mut f32_minimum_up_steps = RESERVE_ULPS;
    let mut committed_d = vec![0.0; n];
    let mut committed_null = vec![0.0; n];
    let mut limiting_coordinate = usize::MAX;
    for (i, alternate_value) in alternate_d.iter().enumerate().take(n) {
        let alternate_target = f64::from(snapshot.base[i]) + *alternate_value;
        ensure!(alternate_target.is_finite());
        let committed_target = alternate_target as f32;
        committed_d[i] = f64::from(committed_target) - f64::from(snapshot.base[i]);
        outside += usize::from(!snapshot.permitted[i] && alternate_d[i] != 0.0);
        let true_bound = boundary(snapshot.target[i]);
        let alternate_lower = alternate_target == WEIGHT_MIN;
        let alternate_upper = alternate_target == WEIGHT_MAX;
        let alternate_bound = alternate_lower || alternate_upper;
        let true_lower = lower_boundary(snapshot.target[i]);
        let true_upper = upper_boundary(snapshot.target[i]);
        lower_boundary_diff += usize::from(true_lower != alternate_lower);
        upper_boundary_diff += usize::from(true_upper != alternate_upper);
        boundary_diff +=
            usize::from(true_lower != alternate_lower || true_upper != alternate_upper);
        new_boundary += usize::from(!true_bound && alternate_bound);
        bounds += usize::from(!(0.0..=2.0).contains(&alternate_target));
        if interior.binary_search(&i).is_ok() {
            committed_null[i] = committed_d[i] - constrained[i];
            let slack = alternate_target.min(2.0 - alternate_target);
            if slack < minimum_slack {
                minimum_slack = slack;
                limiting_coordinate = i;
            }
            let safety = safety_slack(alternate_target, snapshot.target[i]);
            minimum_safety = minimum_safety.min(safety);
            let (down_ulp, up_ulp) = ulp32_spacings(snapshot.target[i]);
            let (lower, upper) = safety_bounds(snapshot.target[i]);
            minimum_down_surplus = minimum_down_surplus.min(alternate_target - lower);
            minimum_up_surplus = minimum_up_surplus.min(upper - alternate_target);
            minimum_down_surplus_ulps =
                minimum_down_surplus_ulps.min((alternate_target - lower) / down_ulp);
            minimum_up_surplus_ulps =
                minimum_up_surplus_ulps.min((upper - alternate_target) / up_ulp);
            let committed_safety = safety_slack(f64::from(committed_target), snapshot.target[i]);
            f32_minimum_safety = f32_minimum_safety.min(committed_safety);
            f32_safety_violations += usize::from(committed_safety < 0.0);
            f32_minimum_down_steps =
                f32_minimum_down_steps.min(interior_steps(committed_target, true));
            f32_minimum_up_steps =
                f32_minimum_up_steps.min(interior_steps(committed_target, false));
        }
        let true_lower = lower_boundary(snapshot.target[i]);
        let true_upper = upper_boundary(snapshot.target[i]);
        let committed_lower = lower_boundary(committed_target);
        let committed_upper = upper_boundary(committed_target);
        f32_lower_boundary_diff += usize::from(true_lower != committed_lower);
        f32_upper_boundary_diff += usize::from(true_upper != committed_upper);
        f32_boundary_diff +=
            usize::from(true_lower != committed_lower || true_upper != committed_upper);
        f32_new_boundary +=
            usize::from(!boundary(snapshot.target[i]) && boundary(committed_target));
    }
    let committed_drive = op.apply(&committed_d);
    let f32_cue_drive_drift = max_abs(
        &committed_drive
            .iter()
            .zip(&drive_alt)
            .map(|(committed, continuous)| committed - continuous)
            .collect::<Vec<_>>(),
    );
    let f32_axis_drift =
        (dot(&committed_d, &snapshot.axis) - dot(&alternate_d, &snapshot.axis)).abs();
    let f32_total_norm_drift = (norm(&committed_d) - norm(&alternate_d)).abs();
    let f32_storage_displacement_drift = max_abs(
        &committed_d
            .iter()
            .zip(&alternate_d)
            .map(|(committed, continuous)| committed - continuous)
            .collect::<Vec<_>>(),
    );
    let f32_residual_cosine_drift = (cosine_between(&committed_null, &true_null) - cosine).abs();
    let reconstruction = max_abs(
        &true_d
            .iter()
            .zip(&constrained)
            .zip(&true_null)
            .map(|((t, c), z)| t - c - z)
            .collect::<Vec<_>>(),
    );
    let event = Event {
        trial: snapshot.trial,
        support_count: snapshot.permitted.iter().filter(|&&x| x).count(),
        interior_variable_count: interior.len(),
        fixed_boundary_count: snapshot.target.iter().filter(|&&x| boundary(x)).count(),
        combined_rank: factor.audit.rank,
        combined_nullity: factor.audit.nullity,
        true_norm: norm(&true_d),
        constrained_norm: norm(&constrained),
        true_null_norm: norm(&true_null),
        alternate_norm: norm(&alternate_d),
        rotation_angle: theta,
        residual_cosine: cosine,
        candidate_index,
        candidate_key,
        candidate_count: CANDIDATES * 2,
        degeneracy_count,
        minimum_interior_slack: minimum_slack,
        true_minimum_safety_slack: true_down_surplus.min(true_up_surplus),
        continuous_minimum_down_surplus: minimum_down_surplus,
        continuous_minimum_up_surplus: minimum_up_surplus,
        continuous_minimum_down_surplus_ulps: minimum_down_surplus_ulps,
        continuous_minimum_up_surplus_ulps: minimum_up_surplus_ulps,
        minimum_safety_slack: minimum_safety,
        reserve_ulps: RESERVE_ULPS,
        limiting_coordinate,
        cue_drive_max_abs_error: max_abs(&drive_error),
        normalized_cue_drive_error: max_abs(&drive_error) / (1.0 + max_abs(&drive_true)),
        axis_displacement_error: axis_error.abs(),
        normalized_axis_error: axis_error.abs() / (1.0 + dot(&true_d, &snapshot.axis).abs()),
        null_annihilation_max_abs: max_abs(&null_drive)
            .max(dot(&alternate_null, &snapshot.axis).abs()),
        normalized_null_annihilation_error: max_abs(&null_drive)
            .max(dot(&alternate_null, &snapshot.axis).abs())
            / (1.0 + norm(&alternate_null)),
        total_norm_error: (norm(&alternate_d) - norm(&true_d)).abs(),
        normalized_total_norm_error: (norm(&alternate_d) - norm(&true_d)).abs()
            / (1.0 + norm(&true_d)),
        reconstruction_error: reconstruction,
        normalized_reconstruction_error: reconstruction / (1.0 + norm(&true_d)),
        outside_support_changes: outside,
        boundary_membership_symmetric_difference: boundary_diff,
        lower_boundary_membership_difference: lower_boundary_diff,
        upper_boundary_membership_difference: upper_boundary_diff,
        new_boundary_memberships: new_boundary,
        bounds_violation_count: bounds,
        f32_safety_violation_count: f32_safety_violations,
        f32_boundary_membership_symmetric_difference: f32_boundary_diff,
        f32_lower_boundary_membership_difference: f32_lower_boundary_diff,
        f32_upper_boundary_membership_difference: f32_upper_boundary_diff,
        f32_new_boundary_memberships: f32_new_boundary,
        f32_minimum_safety_slack: f32_minimum_safety,
        f32_minimum_down_steps_capped: f32_minimum_down_steps,
        f32_minimum_up_steps_capped: f32_minimum_up_steps,
        f32_cue_drive_drift,
        f32_axis_drift,
        f32_total_norm_drift,
        f32_storage_displacement_drift,
        f32_residual_cosine_drift,
        exhaustion_status: "ACCEPTED",
        status: if cosine < 1.0 - FREEDOM_ANGLE_EPS {
            "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT"
        } else {
            "Q10_SM_STAGE1_VALID__SAFETY_MARGIN_DOMINATED"
        },
        f32_commit_status: "SAFETY_AUDITED_ONLY",
    };
    ensure!(event.cue_drive_max_abs_error <= NUMERIC_TOLERANCE);
    ensure!(event.axis_displacement_error <= NUMERIC_TOLERANCE);
    ensure!(event.null_annihilation_max_abs <= NUMERIC_TOLERANCE);
    ensure!(event.total_norm_error <= NUMERIC_TOLERANCE);
    ensure!(event.reconstruction_error <= NUMERIC_TOLERANCE);
    ensure!(
        event.outside_support_changes == 0 && event.boundary_membership_symmetric_difference == 0
    );
    ensure!(
        event.lower_boundary_membership_difference == 0
            && event.upper_boundary_membership_difference == 0
    );
    ensure!(event.new_boundary_memberships == 0 && event.bounds_violation_count == 0);
    ensure!(event.f32_safety_violation_count == 0);
    ensure!(event.f32_boundary_membership_symmetric_difference == 0);
    ensure!(
        event.f32_lower_boundary_membership_difference == 0
            && event.f32_upper_boundary_membership_difference == 0
    );
    ensure!(event.f32_new_boundary_memberships == 0);
    ensure!(event.f32_minimum_down_steps_capped >= RESERVE_ULPS);
    ensure!(event.f32_minimum_up_steps_capped >= RESERVE_ULPS);
    Ok(Analysis {
        event,
        interior_indices: interior,
        true_displacement: true_d,
        constrained_displacement: constrained,
        true_null,
        alternate_null,
    })
}

fn write_replay(
    path: &Path,
    snapshot: &crate::capture::Snapshot,
    op: &DriveOperator,
    analysis: &Analysis,
) -> Result<()> {
    write_json(
        path,
        &Replay {
            snapshot: snapshot.clone(),
            operator: op.clone(),
            interior_indices: analysis.interior_indices.clone(),
            true_displacement: analysis.true_displacement.clone(),
            constrained_displacement: analysis.constrained_displacement.clone(),
            true_null: analysis.true_null.clone(),
            alternate_null: analysis.alternate_null.clone(),
            event: analysis.event.clone(),
        },
    )
}

fn stage_expected(stage: &str) -> usize {
    if stage == "stage1-a" {
        STAGE_A_STATES
    } else {
        STAGE_B_STATES
    }
}

pub fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(
        args.len() == 5,
        "usage: q10 stage1-a|stage1-b CONFIG ANATOMY OUTPUT"
    );
    let config: Config = serde_json::from_reader(File::open(&args[2])?)?;
    let seeds = validate_config(&config)?;
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let contract: Value = serde_json::from_reader(File::open(root.join("CONTRACT.json"))?)?;
    ensure!(contract["protocol"] == PROTOCOL);
    let plan_hash = hash_bytes(&std::fs::read(root.join("PLAN.md"))?);
    ensure!(
        contract["plan_sha256"]
            .as_str()
            .is_some_and(|hash| hash.eq_ignore_ascii_case(&plan_hash))
    );
    let out = Path::new(&args[4]);
    std::fs::create_dir_all(out)?;
    let executable = std::env::current_exe()?;
    write_json(
        &out.join("pre-execution.json"),
        &json!({
            "protocol":PROTOCOL, "schema_version":1, "stage":config.stage,
            "source":source_manifest(root)?, "executable":executable,
            "executable_sha256":hash_bytes(&std::fs::read(&executable)?),
            "config_sha256":hash_bytes(&std::fs::read(&args[2])?), "seeds":seeds,
            "scientific_seed_bundles":0, "behavioral_inference":false,
            "box_feasibility":"TESTED_CONTINUOUS_WITH_F32_SAFETY_RESERVE",
            "sequential_f32_endpoint_equality":"NOT_TESTED",
            "candidate_directions":CANDIDATES, "angle_bisections":BISECTIONS,
            "numeric_tolerance":NUMERIC_TOLERANCE, "reserve_ulps":RESERVE_ULPS
        }),
    )?;
    let anatomy = Path::new(&args[3]);
    let analysis_pool = rayon::ThreadPoolBuilder::new()
        .num_threads(config.threads)
        .build()?;
    let mut total = 0usize;
    let mut freedom = 0usize;
    let mut dominated = 0usize;
    let mut replay_written = false;
    for &seed in seeds {
        for side in &config.sides {
            for &tau in &config.taus {
                let graph = Graph::load(anatomy, side, config.glut_sign)?;
                let (shuffled, rewire) = graph.route.rewired(seed ^ 0x887733);
                ensure!(rewire.accepted > 0 && rewire.degree_preserved);
                let task = Task::new(&graph, seed ^ config.input_salt, 16, 12, 512);
                let op = DriveOperator::new(&task, graph.kc_mb.n_post, graph.kc_mb.edges.len())?;
                let mut sim = Simulator::new(&graph, &graph.route, seed, tau, config.eta, "E");
                sim.capture = Some(crate::capture::Capture::new(sim.weights.len()));
                sim.policy = Some(Policy::new(sim.weights.len()));
                let run = sim
                    .run_dh07(
                        &task,
                        Dh07Condition::TruePerpendicular,
                        &shuffled,
                        config.observe,
                        0,
                    )
                    .context("Q10 Stage 1 simulator")?;
                ensure!(run.result.outcome.hot_allocations == 0);
                let policy = sim.policy.take().context("missing Q10 policy capture")?;
                ensure!(policy.count == 256);
                let analyzed = analysis_pool.install(|| {
                    policy.snapshots[..policy.count]
                        .par_iter()
                        .map(|snapshot| {
                            analyze_event(
                                &op,
                                snapshot,
                                seed ^ (tau.to_bits() as u64) ^ snapshot.trial as u64,
                            )
                        })
                        .collect::<Result<Vec<_>>>()
                })?;
                let mut events = Vec::with_capacity(policy.count);
                for (index, analysis) in analyzed.into_iter().enumerate() {
                    let event = analysis.event.clone();
                    freedom += usize::from(
                        event.status == "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT",
                    );
                    dominated +=
                        usize::from(event.status == "Q10_SM_STAGE1_VALID__SAFETY_MARGIN_DOMINATED");
                    total += 1;
                    if !replay_written
                        && seed == seeds[0]
                        && side == "R"
                        && tau == 4.0
                        && index == 0
                    {
                        let snapshot = &policy.snapshots[index];
                        write_replay(
                            &out.join("replay-R-tau4-trial1.json"),
                            snapshot,
                            &op,
                            &analysis,
                        )?;
                        replay_written = true;
                    }
                    events.push(event);
                }
                write_json(
                    &out.join(format!("seed{seed}-{side}-tau{tau}.json")),
                    &json!({
                        "protocol":PROTOCOL, "schema_version":1, "seed":seed,
                        "side":side, "tau":tau, "post_len":graph.kc_mb.n_post,
                        "drive_rows":op.rows.len(), "events":events
                    }),
                )?;
                println!("Q10 Stage 1 complete seed={seed} {side} tau={tau}");
            }
        }
    }
    ensure!(total == stage_expected(&config.stage));
    ensure!(replay_written);
    let status = if freedom > 0 {
        "Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT"
    } else if dominated == total {
        "Q10_SM_STAGE1_VALID__SAFETY_MARGIN_DOMINATED"
    } else {
        "Q10_SM_STAGE1_VALID__NUMERICALLY_AMBIGUOUS"
    };
    let cumulative = if config.stage == "stage1-b" {
        total + STAGE_A_STATES
    } else {
        total
    };
    write_json(
        &out.join("execution.json"),
        &json!({
            "protocol":PROTOCOL, "schema_version":1, "stage":config.stage,
            "status":status, "complete":true, "audited_states":total, "freedom_events":freedom,
            "cumulative_audited_states":cumulative,
            "scientific_seed_bundles":0, "behavioral_inference":false,
            "box_feasibility":"TESTED_CONTINUOUS_WITH_F32_SAFETY_RESERVE",
            "sequential_f32_endpoint_equality":"NOT_TESTED",
            "stage2_authorized_by_this_receipt":false,
            "reserve_ulps":RESERVE_ULPS
        }),
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use nalgebra::DMatrix;

    #[test]
    fn geodesic_preserves_norm_and_orthogonalizes_tangent() {
        let matrix = DMatrix::from_row_slice(1, 4, &[1.0, 0.0, 0.0, 0.0]);
        let factor = Factorization::new(&matrix).unwrap();
        let z = vec![0.0, 1.0, 0.0, 0.0];
        let tangent = candidate_tangent(&factor, &z, 17).unwrap();
        assert!((dot(&z, &tangent)).abs() < 1e-12);
        assert!((norm(&z) - norm(&tangent)).abs() < 1e-12);
        let center = vec![1.0; 4];
        let endpoint = endpoint_for_angle(&center, &z, &tangent, std::f64::consts::FRAC_PI_2);
        assert!((norm(&endpoint) - norm(&center)).is_finite());
    }

    #[test]
    fn bounded_rotation_starts_from_feasible_true_endpoint() {
        let matrix = DMatrix::from_row_slice(1, 3, &[1.0, 0.0, 0.0]);
        let factor = Factorization::new(&matrix).unwrap();
        let z = vec![0.0, 0.4, 0.0];
        let center = vec![1.0, 1.0, 1.0];
        let interior = vec![0, 1, 2];
        let references = vec![1.0_f32; 3];
        let (residual, cosine, _, _, _) =
            best_rotation(&center, &z, &factor, 99, &interior, &references).unwrap();
        let endpoint: Vec<_> = center.iter().zip(residual).map(|(c, z)| c + z).collect();
        assert!(feasible(&endpoint, &interior, &references));
        assert!((cosine - 0.0).abs() < 1e-12);
    }

    #[test]
    fn safety_reserve_uses_asymmetric_binary32_spacing() {
        let reference = f32::from_bits(0x3f80_0000);
        let (lower, upper) = safety_bounds(reference);
        assert_eq!(
            lower,
            32.0 * (1.0 - f64::from(nextafter32(reference, true)))
        );
        assert_eq!(
            upper,
            2.0 - 32.0 * (f64::from(nextafter32(reference, false)) - 1.0)
        );
        assert_eq!(interior_steps(reference, true), RESERVE_ULPS);
        assert_eq!(interior_steps(reference, false), RESERVE_ULPS);
    }

    #[test]
    fn event_audit_preserves_linear_drives_norm_and_support() {
        let operator = DriveOperator {
            cues: 1,
            posts: 1,
            coordinates: 4,
            rows: vec![vec![0, 1]],
        };
        let snapshot = crate::capture::Snapshot {
            trial: 1,
            base: vec![0.2, 0.3, 0.4, 0.8],
            target: vec![0.4, 0.5, 0.7, 0.9],
            axis: vec![0.0, 0.0, 0.0, 0.0],
            permitted: vec![true, true, true, true],
        };
        let analysis = analyze_event(&operator, &snapshot, 123).unwrap();
        let event = analysis.event;
        assert_eq!(event.outside_support_changes, 0);
        assert_eq!(event.boundary_membership_symmetric_difference, 0);
        assert!(event.total_norm_error <= NUMERIC_TOLERANCE);
        assert!(event.cue_drive_max_abs_error <= NUMERIC_TOLERANCE);
        assert!(analysis.alternate_null.iter().any(|value| *value != 0.0));
    }
}
