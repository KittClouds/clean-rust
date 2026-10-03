//! Q10 Stage 1: continuous bounded geometry qualification.
//!
//! The constructor starts from the committed true null component and moves on
//! a fixed-norm geodesic in the same linear nullspace.  It never commits an
//! alternate f32 endpoint and never runs a scientific seed.  Stage 2 is a
//! separate protocol because sequential f32 readout is a different seam.
use crate::{
    graph::Graph,
    linear::{self, DriveOperator, Factorization},
    policy::Policy,
    simulation::{Dh07Condition, Simulator},
    task::Task,
};
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{fs::{File, OpenOptions}, io::{BufWriter, Write}, path::{Path, PathBuf}};

const SEED_A: &[u64] = &[9301];
const SEEDS_B: &[u64] = &[9302, 9303, 9304, 9305];
const STAGE_A_STATES: usize = 1024;
const STAGE_B_STATES: usize = 4096;
const CANDIDATES: usize = 8;
const BISECTIONS: usize = 32;
const ZERO_NORM_SQ: f64 = 1.0e-24;
const NUMERIC_TOLERANCE: f64 = 2.0e-10;
const FREEDOM_ANGLE_EPS: f64 = 1.0e-8;

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
}

fn validate_config(config: &Config) -> Result<&'static [u64]> {
    ensure!(config.stage == "stage1-a" || config.stage == "stage1-b");
    let seeds = if config.stage == "stage1-a" { SEED_A } else { SEEDS_B };
    ensure!(config.seeds == seeds, "unauthorized Q10 engineering seed set");
    ensure!(config.observe && config.taus == [4.0, 16.0] && config.sides == ["R", "L"]);
    ensure!(config.conditions == ["true_perpendicular"] && config.arms == ["E", "Z"]);
    ensure!(config.cues == 16 && config.delay_steps == 12 && config.trials == 512);
    ensure!(config.eta == 0.05 && config.glut_sign == -1.0 && config.input_salt == 858980352);
    ensure!(config.threads == 8);
    ensure!(config.candidate_directions == CANDIDATES);
    ensure!(config.angle_bisections == BISECTIONS);
    Ok(seeds)
}

fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let mut writer = BufWriter::new(
        OpenOptions::new().write(true).create_new(true).open(path)?,
    );
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
    paths.iter().map(|path| {
        Ok(json!({"path": path, "sha256": hash_bytes(&std::fs::read(root.join(path))?)}))
    }).collect()
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

fn candidate_tangent(
    factor: &Factorization,
    z_true: &[f64],
    key: u64,
) -> Option<Vec<f64>> {
    let mut raw = Vec::with_capacity(z_true.len());
    for i in 0..z_true.len() {
        raw.push(unit_from_key(key ^ (i as u64).wrapping_mul(0xd6e8_feb8_6659_fd93)));
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
    center.iter().zip(z_true).zip(tangent)
        .map(|((c, z), v)| c + z * cos + v * sin)
        .collect()
}

fn feasible(endpoint: &[f64]) -> bool {
    endpoint.iter().all(|value| value.is_finite() && *value > 0.0 && *value < 2.0)
}

fn best_rotation(
    center: &[f64],
    z_true: &[f64],
    factor: &Factorization,
    key: u64,
) -> Option<(Vec<f64>, f64, usize)> {
    let true_norm = norm(z_true);
    if true_norm * true_norm <= ZERO_NORM_SQ || factor.audit.nullity < 2 {
        return None;
    }
    let mut best: Option<(Vec<f64>, f64, usize)> = None;
    for candidate in 0..CANDIDATES {
        let Some(tangent) = candidate_tangent(
            factor,
            z_true,
            key ^ (candidate as u64).wrapping_mul(0xa076_1d64_78bd_642f),
        ) else { continue };
        let high = std::f64::consts::FRAC_PI_2;
        let at_high = endpoint_for_angle(center, z_true, &tangent, high);
        let theta = if feasible(&at_high) {
            high
        } else {
            let mut low = 0.0;
            let mut high = high;
            for _ in 0..BISECTIONS {
                let middle = (low + high) * 0.5;
                if feasible(&endpoint_for_angle(center, z_true, &tangent, middle)) {
                    low = middle;
                } else {
                    high = middle;
                }
            }
            low
        };
        let endpoint = endpoint_for_angle(center, z_true, &tangent, theta);
        let score = theta.cos().abs();
        if best.as_ref().is_none_or(|(_, old_score, _)| score < *old_score) {
            best = Some((endpoint, score, candidate));
        }
    }
    best.map(|(endpoint, cosine, candidate)| (endpoint, cosine, candidate))
}

fn boundary(value: f32) -> bool {
    value == 0.0 || value == 2.0
}

#[derive(Clone, Serialize)]
struct Event {
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
    cue_drive_max_abs_error: f64,
    axis_displacement_error: f64,
    null_annihilation_max_abs: f64,
    total_norm_error: f64,
    reconstruction_error: f64,
    outside_support_changes: usize,
    boundary_membership_symmetric_difference: usize,
    new_boundary_memberships: usize,
    bounds_violation_count: usize,
    status: &'static str,
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

fn analyze_event(
    op: &DriveOperator,
    snapshot: &crate::capture::Snapshot,
    key: u64,
    save_replay: bool,
) -> Result<(Event, Option<Replay>)> {
    let n = snapshot.base.len();
    let true_d: Vec<_> = snapshot.target.iter().zip(&snapshot.base)
        .map(|(&target, &base)| f64::from(target) - f64::from(base)).collect();
    ensure!(snapshot.axis.len() == n && snapshot.permitted.len() == n);
    let mut fixed = vec![0.0; n];
    let mut interior = Vec::new();
    for i in 0..n {
        ensure!(!snapshot.permitted[i] || true_d[i] != 0.0 || snapshot.target[i] == snapshot.base[i]);
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
    let z_true: Vec<_> = x_true.iter().zip(&x_star).map(|(x, star)| x - star).collect();
    let mut constrained = fixed.clone();
    let mut true_null = vec![0.0; n];
    for (j, &i) in interior.iter().enumerate() {
        constrained[i] = x_star[j];
        true_null[i] = z_true[j];
    }
    let center: Vec<_> = interior.iter().map(|&i| f64::from(snapshot.base[i]) + constrained[i]).collect();
    let Some((alternate_x, cosine, candidate_index)) = best_rotation(&center, &z_true, &factor, key) else {
        let event = Event {
            trial: snapshot.trial,
            support_count: snapshot.permitted.iter().filter(|&&x| x).count(),
            interior_variable_count: interior.len(),
            fixed_boundary_count: fixed.iter().filter(|&&x| x != 0.0).count(),
            combined_rank: factor.audit.rank,
            combined_nullity: factor.audit.nullity,
            true_norm: norm(&true_d), constrained_norm: norm(&constrained),
            true_null_norm: norm(&true_null), alternate_norm: 0.0,
            rotation_angle: 0.0, residual_cosine: 1.0, candidate_index: 0,
            cue_drive_max_abs_error: 0.0, axis_displacement_error: 0.0,
            null_annihilation_max_abs: 0.0, total_norm_error: 0.0,
            reconstruction_error: 0.0, outside_support_changes: 0,
            boundary_membership_symmetric_difference: 0, new_boundary_memberships: 0,
            bounds_violation_count: 0,
            status: if factor.audit.nullity < 2 { "CONTINUOUS_BOUNDED_VALID__CONSTRAINT_DOMINATED" }
                else { "CONTINUOUS_BOUNDED_VALID__ZERO_NULL_ENERGY" },
            f32_commit_status: "NOT_TESTED",
        };
        return Ok((event, None));
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
    let drive_error: Vec<_> = drive_alt.iter().zip(&drive_true).map(|(a, t)| a - t).collect();
    let null_drive = op.apply(&alternate_null);
    let axis_error = dot(&alternate_d, &snapshot.axis) - dot(&true_d, &snapshot.axis);
    let mut outside = 0;
    let mut boundary_diff = 0;
    let mut new_boundary = 0;
    let mut bounds = 0;
    for i in 0..n {
        let alternate_target = f64::from(snapshot.base[i]) + alternate_d[i];
        ensure!(alternate_target.is_finite());
        outside += usize::from(!snapshot.permitted[i] && alternate_d[i] != 0.0);
        let true_bound = boundary(snapshot.target[i]);
        let alternate_bound = alternate_target == 0.0 || alternate_target == 2.0;
        boundary_diff += usize::from(true_bound != alternate_bound);
        new_boundary += usize::from(!true_bound && alternate_bound);
        bounds += usize::from(!(0.0..=2.0).contains(&alternate_target));
    }
    let reconstruction = max_abs(&true_d.iter().zip(&constrained).zip(&true_null)
        .map(|((t, c), z)| t - c - z).collect::<Vec<_>>());
    let event = Event {
        trial: snapshot.trial,
        support_count: snapshot.permitted.iter().filter(|&&x| x).count(),
        interior_variable_count: interior.len(),
        fixed_boundary_count: fixed.iter().filter(|&&x| x != 0.0).count(),
        combined_rank: factor.audit.rank,
        combined_nullity: factor.audit.nullity,
        true_norm: norm(&true_d),
        constrained_norm: norm(&constrained),
        true_null_norm: norm(&true_null),
        alternate_norm: norm(&alternate_d),
        rotation_angle: theta,
        residual_cosine: cosine,
        candidate_index,
        cue_drive_max_abs_error: max_abs(&drive_error),
        axis_displacement_error: axis_error.abs(),
        null_annihilation_max_abs: max_abs(&null_drive).max(dot(&alternate_null, &snapshot.axis).abs()),
        total_norm_error: (norm(&alternate_d) - norm(&true_d)).abs(),
        reconstruction_error: reconstruction,
        outside_support_changes: outside,
        boundary_membership_symmetric_difference: boundary_diff,
        new_boundary_memberships: new_boundary,
        bounds_violation_count: bounds,
        status: if cosine < FREEDOM_ANGLE_EPS { "CONTINUOUS_BOUNDED_VALID__FREEDOM_PRESENT" }
            else { "CONTINUOUS_BOUNDED_VALID__BOUNDED_DIRECTIONAL_FREEDOM" },
        f32_commit_status: "NOT_TESTED",
    };
    ensure!(event.cue_drive_max_abs_error <= NUMERIC_TOLERANCE);
    ensure!(event.axis_displacement_error <= NUMERIC_TOLERANCE);
    ensure!(event.null_annihilation_max_abs <= NUMERIC_TOLERANCE);
    ensure!(event.total_norm_error <= NUMERIC_TOLERANCE);
    ensure!(event.reconstruction_error <= NUMERIC_TOLERANCE);
    ensure!(event.outside_support_changes == 0 && event.boundary_membership_symmetric_difference == 0);
    ensure!(event.new_boundary_memberships == 0 && event.bounds_violation_count == 0);
    let replay = save_replay.then(|| Replay {
        snapshot: snapshot.clone(), operator: op.clone(), interior_indices: interior,
        true_displacement: true_d, constrained_displacement: constrained,
        true_null, alternate_null, event: event.clone(),
    });
    Ok((event, replay))
}

fn stage_expected(stage: &str) -> usize {
    if stage == "stage1-a" { STAGE_A_STATES } else { STAGE_B_STATES }
}

pub fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(args.len() == 5, "usage: q10 stage1-a|stage1-b CONFIG ANATOMY OUTPUT");
    let config: Config = serde_json::from_reader(File::open(&args[2])?)?;
    let seeds = validate_config(&config)?;
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let contract: Value = serde_json::from_reader(File::open(root.join("CONTRACT.json"))?)?;
    ensure!(contract["protocol"] == "Q10-BG");
    let plan_hash = hash_bytes(&std::fs::read(root.join("PLAN.md"))?);
    ensure!(contract["plan_sha256"].as_str().is_some_and(|hash| hash.eq_ignore_ascii_case(&plan_hash)));
    let out = Path::new(&args[4]);
    std::fs::create_dir_all(out)?;
    let executable = std::env::current_exe()?;
    write_json(&out.join("pre-execution.json"), &json!({
        "protocol":"Q10-BG", "schema_version":1, "stage":config.stage,
        "source":source_manifest(root)?, "executable":executable,
        "executable_sha256":hash_bytes(&std::fs::read(&executable)?),
        "config_sha256":hash_bytes(&std::fs::read(&args[2])?), "seeds":seeds,
        "scientific_seed_bundles":0, "behavioral_inference":false,
        "box_feasibility":"TESTED_CONTINUOUS_ONLY",
        "sequential_f32_endpoint_equality":"NOT_TESTED",
        "candidate_directions":CANDIDATES, "angle_bisections":BISECTIONS,
        "numeric_tolerance":NUMERIC_TOLERANCE
    }))?;
    let anatomy = Path::new(&args[3]);
    let mut total = 0usize;
    let mut freedom = 0usize;
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
                let run = sim.run_dh07(&task, Dh07Condition::TruePerpendicular, &shuffled, config.observe, 0)
                    .context("Q10 Stage 1 simulator")?;
                ensure!(run.result.outcome.hot_allocations == 0);
                let policy = sim.policy.take().context("missing Q10 policy capture")?;
                ensure!(policy.count == 256);
                let mut events = Vec::with_capacity(policy.count);
                for snapshot in policy.snapshots.iter().take(policy.count) {
                    let save = !replay_written && seed == seeds[0] && side == "R" && tau == 4.0 && snapshot.trial == 1;
                    let (event, replay) = analyze_event(&op, snapshot, seed ^ (tau.to_bits() as u64) ^ snapshot.trial as u64, save)?;
                    freedom += usize::from(event.status == "CONTINUOUS_BOUNDED_VALID__FREEDOM_PRESENT"
                        || event.status == "CONTINUOUS_BOUNDED_VALID__BOUNDED_DIRECTIONAL_FREEDOM");
                    total += 1;
                    if let Some(replay) = replay {
                        write_json(&out.join("replay-R-tau4-trial1.json"), &replay)?;
                        replay_written = true;
                    }
                    events.push(event);
                }
                write_json(&out.join(format!("seed{seed}-{side}-tau{tau}.json")), &json!({
                    "protocol":"Q10-BG", "schema_version":1, "seed":seed,
                    "side":side, "tau":tau, "post_len":graph.kc_mb.n_post,
                    "drive_rows":op.rows.len(), "events":events
                }))?;
                println!("Q10 Stage 1 complete seed={seed} {side} tau={tau}");
            }
        }
    }
    ensure!(total == stage_expected(&config.stage));
    ensure!(replay_written);
    write_json(&out.join("execution.json"), &json!({
        "protocol":"Q10-BG", "schema_version":1, "stage":config.stage,
        "complete":true, "audited_states":total, "freedom_events":freedom,
        "scientific_seed_bundles":0, "behavioral_inference":false,
        "box_feasibility":"TESTED_CONTINUOUS_ONLY",
        "sequential_f32_endpoint_equality":"NOT_TESTED",
        "stage2_authorized_by_this_receipt":false
    }))?;
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
        let (endpoint, cosine, _) = best_rotation(&center, &z, &factor, 99).unwrap();
        assert!(feasible(&endpoint));
        assert!((cosine - 0.0).abs() < 1e-12);
    }
}
