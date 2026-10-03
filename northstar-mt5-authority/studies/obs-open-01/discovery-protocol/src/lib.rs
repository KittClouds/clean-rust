use bytemuck::{Pod, Zeroable};
use hashbrown::{HashMap, HashSet};
use memchr::memchr_iter;
use memmap2::Mmap;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::File;
use std::path::{Path, PathBuf};
use wide::f64x4;

pub const MEAS02_ROOT: &str = "f7abf12d1473a5e1eddc8a7efb84ff7224811eda83ad62ba4fe300a7648ce5ea";
pub const INST01_ROOT: &str = "5930c7d4f5b2de4549bfedacbd2c3b9df7da78f68c7d765b9c0669d08a17490f";
pub const UNIVERSE_ROOT: &str = "6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235";
pub const OBSERVER_INSTANCE: &str = "CAUSAL_RANGE_EXTREME_M1_V1";
pub const DISCOVERY_SESSIONS: u64 = 257;
pub const CONFIRMATION_SESSIONS: u64 = 69;
pub const FORMAL_TESTS: usize = 3;
pub const ALPHA: f64 = 0.05;
pub const RANDOMIZATIONS: u64 = 9_999;
pub const RANDOM_SEED: u64 = 20_260_814;
pub const WILSON_Z_99: f64 = 2.575_829_303_548_900_4;

pub type AnyResult<T> = Result<T, Box<dyn std::error::Error>>;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReadReceipt {
    pub relative_path: String,
    pub purpose: String,
    pub sha256: String,
    pub bytes: u64,
}

#[derive(Debug)]
pub struct AuthorityReader {
    root: PathBuf,
    allowed: HashMap<String, String>,
    reads: Vec<ReadReceipt>,
}

impl AuthorityReader {
    pub fn new(
        root: &Path,
        allowed: impl IntoIterator<Item = (String, String)>,
    ) -> AnyResult<Self> {
        let root = std::fs::canonicalize(root)?;
        let allowed = allowed.into_iter().collect();
        Ok(Self {
            root,
            allowed,
            reads: Vec::new(),
        })
    }

    pub fn read(&mut self, relative: &str) -> AnyResult<Vec<u8>> {
        let purpose = self
            .allowed
            .get(relative)
            .cloned()
            .ok_or_else(|| format!("UNDECLARED_READ_ATTEMPT:{relative}"))?;
        if relative.contains("..") || Path::new(relative).is_absolute() {
            return Err(format!("UNSAFE_AUTHORITY_PATH:{relative}").into());
        }
        let path = std::fs::canonicalize(self.root.join(relative))?;
        if !path.starts_with(&self.root) {
            return Err(format!("READ_ESCAPES_REPOSITORY_ROOT:{}", path.display()).into());
        }
        let file = File::open(&path)?;
        let mmap = unsafe { Mmap::map(&file) }?;
        let bytes = mmap.as_ref().to_vec();
        self.reads.push(ReadReceipt {
            relative_path: relative.replace('\\', "/"),
            purpose,
            sha256: sha256_bytes(&bytes),
            bytes: bytes.len() as u64,
        });
        Ok(bytes)
    }

    pub fn read_json(&mut self, relative: &str) -> AnyResult<Value> {
        Ok(serde_json::from_slice(&self.read(relative)?)?)
    }

    pub fn receipts(&self) -> &[ReadReceipt] {
        &self.reads
    }

    pub fn assert_complete(&self) -> AnyResult<()> {
        let observed: HashSet<&str> = self
            .reads
            .iter()
            .map(|r| r.relative_path.as_str())
            .collect();
        let expected: HashSet<&str> = self.allowed.keys().map(String::as_str).collect();
        if observed != expected {
            return Err(format!(
                "DECLARED_READ_SET_MISMATCH expected={} observed={}",
                expected.len(),
                observed.len()
            )
            .into());
        }
        Ok(())
    }
}

pub fn sha256_bytes(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

pub fn sha256_file(path: &Path) -> AnyResult<String> {
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file) }?;
    Ok(sha256_bytes(&mmap))
}

pub fn canonical_json_bytes(value: &impl Serialize) -> AnyResult<Vec<u8>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    Ok(bytes)
}

pub fn tsv_row_count(bytes: &[u8]) -> usize {
    memchr_iter(b'\n', bytes).count().saturating_sub(1)
}

pub fn minimum_randomizations(alpha: f64, family_count: usize, headroom: usize) -> u64 {
    ((headroom as f64 * family_count as f64 / alpha).ceil() as u64).saturating_sub(1)
}

pub fn minimum_attainable_p(randomizations: u64) -> f64 {
    1.0 / (randomizations as f64 + 1.0)
}

pub fn resolution_pass(
    randomizations: u64,
    alpha: f64,
    family_count: usize,
    headroom: usize,
) -> bool {
    minimum_attainable_p(randomizations) <= alpha / (family_count as f64 * headroom as f64)
}

pub fn wilson_interval(successes: u64, trials: u64, z: f64) -> AnyResult<(f64, f64)> {
    if trials == 0 || successes > trials {
        return Err("INVALID_WILSON_COUNTS".into());
    }
    let n = trials as f64;
    let p = successes as f64 / n;
    let z2 = z * z;
    let denominator = 1.0 + z2 / n;
    let center = (p + z2 / (2.0 * n)) / denominator;
    let radius = z * ((p * (1.0 - p) / n + z2 / (4.0 * n * n)).sqrt()) / denominator;
    Ok(((center - radius).max(0.0), (center + radius).min(1.0)))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum NumericalDecision {
    Pass,
    Fail,
    Unresolved,
}

pub fn monte_carlo_decision(
    successes: u64,
    trials: u64,
    threshold: f64,
) -> AnyResult<NumericalDecision> {
    let (lower, upper) = wilson_interval(successes, trials, WILSON_Z_99)?;
    Ok(if upper <= threshold {
        NumericalDecision::Pass
    } else if lower > threshold {
        NumericalDecision::Fail
    } else {
        NumericalDecision::Unresolved
    })
}

pub fn holm_bonferroni(p_values: &[(String, f64)], alpha: f64) -> Vec<(String, bool, f64)> {
    let mut ordered = p_values.to_vec();
    ordered.sort_by(|a, b| a.1.total_cmp(&b.1).then_with(|| a.0.cmp(&b.0)));
    let total = ordered.len();
    let mut still_rejecting = true;
    ordered
        .into_iter()
        .enumerate()
        .map(|(rank, (id, p))| {
            let threshold = alpha / (total - rank) as f64;
            let pass = still_rejecting && p <= threshold;
            if !pass {
                still_rejecting = false;
            }
            (id, pass, threshold)
        })
        .collect()
}

#[derive(Clone, Copy, Debug, Pod, Zeroable)]
#[repr(C)]
pub struct PackedSurfaceCell {
    pub session: u32,
    pub coordinate: u32,
    pub value: f64,
}

pub fn packed_surface_hash(cells: &[PackedSurfaceCell]) -> String {
    sha256_bytes(bytemuck::cast_slice(cells))
}

pub fn session_balanced_values(rows: &[(u32, f64)]) -> Vec<(u32, f64)> {
    let mut values: HashMap<u32, Vec<f64>> = HashMap::with_capacity(rows.len());
    for &(session, value) in rows {
        values.entry(session).or_default().push(value);
    }
    let mut out: Vec<_> = values
        .into_iter()
        .map(|(session, mut values)| {
            values.sort_by(f64::total_cmp);
            let count = values.len();
            let mut sum = 0.0;
            let mut compensation = 0.0;
            for value in values {
                let adjusted = value - compensation;
                let next = sum + adjusted;
                compensation = (next - sum) - adjusted;
                sum = next;
            }
            (session, sum / count as f64)
        })
        .collect();
    out.sort_unstable_by_key(|x| x.0);
    out
}

fn splitmix64(mut x: u64) -> u64 {
    x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = x;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

fn sign(seed: u64, permutation: u64, session: usize) -> f64 {
    let key = seed
        ^ permutation.wrapping_mul(0xD6E8_FD9D_50A5_8B09)
        ^ (session as u64).wrapping_mul(0xA076_1D64_78BD_642F);
    if splitmix64(key) & 1 == 0 { -1.0 } else { 1.0 }
}

fn t_from_sum(sum: f64, sumsq: f64, n: usize) -> f64 {
    if n < 2 {
        return 0.0;
    }
    let nf = n as f64;
    let variance = ((sumsq - sum * sum / nf) / (nf - 1.0)).max(0.0);
    if variance == 0.0 {
        0.0
    } else {
        (sum / nf) / (variance / nf).sqrt()
    }
}

pub fn observed_max_abs_t(matrix: &[Vec<f64>]) -> AnyResult<f64> {
    let (sessions, cells) = matrix_shape(matrix)?;
    let mut max_t: f64 = 0.0;
    for cell in 0..cells {
        let mut sum = 0.0;
        let mut sumsq = 0.0;
        for row in matrix {
            sum += row[cell];
            sumsq += row[cell] * row[cell];
        }
        max_t = max_t.max(t_from_sum(sum, sumsq, sessions).abs());
    }
    Ok(max_t)
}

fn matrix_shape(matrix: &[Vec<f64>]) -> AnyResult<(usize, usize)> {
    let sessions = matrix.len();
    let cells = matrix.first().map(Vec::len).unwrap_or(0);
    if sessions < 2 || cells == 0 || matrix.iter().any(|row| row.len() != cells) {
        return Err("INVALID_SURFACE_MATRIX".into());
    }
    Ok((sessions, cells))
}

fn permutation_max_abs_t(matrix: &[Vec<f64>], seed: u64, permutation: u64) -> f64 {
    let sessions = matrix.len();
    let cells = matrix[0].len();
    let mut max_t: f64 = 0.0;
    let mut cell = 0usize;
    while cell + 4 <= cells {
        let mut signed_sum = f64x4::from([0.0; 4]);
        let mut sumsq = f64x4::from([0.0; 4]);
        for (session, row) in matrix.iter().enumerate() {
            let values = f64x4::from([row[cell], row[cell + 1], row[cell + 2], row[cell + 3]]);
            signed_sum += values * f64x4::splat(sign(seed, permutation, session));
            sumsq += values * values;
        }
        let sums = signed_sum.to_array();
        let squares = sumsq.to_array();
        for lane in 0..4 {
            max_t = max_t.max(t_from_sum(sums[lane], squares[lane], sessions).abs());
        }
        cell += 4;
    }
    while cell < cells {
        let mut sum = 0.0;
        let mut sumsq = 0.0;
        for (session, row) in matrix.iter().enumerate() {
            sum += sign(seed, permutation, session) * row[cell];
            sumsq += row[cell] * row[cell];
        }
        max_t = max_t.max(t_from_sum(sum, sumsq, sessions).abs());
        cell += 1;
    }
    max_t
}

pub fn sign_flip_max_t_distribution(
    matrix: &[Vec<f64>],
    randomizations: u64,
    seed: u64,
    threads: usize,
) -> AnyResult<Vec<f64>> {
    matrix_shape(matrix)?;
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build()?;
    Ok(pool.install(|| {
        (0..randomizations)
            .into_par_iter()
            .map(|permutation| permutation_max_abs_t(matrix, seed, permutation))
            .collect()
    }))
}

pub fn plus_one_p(observed: f64, reference: &[f64]) -> (u64, f64) {
    let exceedances = reference.iter().filter(|&&x| x >= observed).count() as u64;
    (
        exceedances,
        (exceedances as f64 + 1.0) / (reference.len() as f64 + 1.0),
    )
}

pub fn canonical_anchor(cells: &[(String, f64)]) -> Option<String> {
    let max = cells
        .iter()
        .map(|(_, value)| value.abs())
        .max_by(f64::total_cmp)?;
    cells
        .iter()
        .filter(|(_, value)| value.abs() == max)
        .map(|(id, _)| id)
        .min()
        .cloned()
}

pub fn temporal_sign_status(aggregate: f64, supported_slices: &[f64]) -> &'static str {
    if aggregate == 0.0 || supported_slices.is_empty() || supported_slices.contains(&0.0) {
        return "TEMPORAL_SUPPORT_INSUFFICIENT";
    }
    let sign = aggregate.is_sign_positive();
    if supported_slices
        .iter()
        .all(|x| x.is_sign_positive() == sign)
    {
        "TEMPORALLY_SUPPORTED"
    } else {
        "TEMPORALLY_UNSTABLE"
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LeaveOneMonthSupport {
    pub remaining_sessions: usize,
    pub supported_months: usize,
    pub offset_120_sessions: usize,
    pub offset_180_sessions: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SurfaceSupport {
    pub eligible_sessions: usize,
    pub month_counts: Vec<usize>,
    pub offset_120_sessions: usize,
    pub offset_180_sessions: usize,
    pub chronological_block_counts: [usize; 4],
    pub leave_one_month: Vec<LeaveOneMonthSupport>,
}

pub fn surface_support_status(support: &SurfaceSupport) -> &'static str {
    if support.eligible_sessions < 129 {
        return "SESSION_SUPPORT_INSUFFICIENT";
    }
    let supported_months = support
        .month_counts
        .iter()
        .filter(|&&count| count >= 10)
        .count();
    if supported_months < 4
        || support.offset_120_sessions < 20
        || support.offset_180_sessions < 20
        || support
            .chronological_block_counts
            .iter()
            .any(|&count| count < 20)
        || support.leave_one_month.len() != supported_months
        || support.leave_one_month.iter().any(|slice| {
            slice.remaining_sessions < 103
                || slice.supported_months < 3
                || slice.offset_120_sessions < 15
                || slice.offset_180_sessions < 15
        })
    {
        return "SURFACE_SUPPORT_INSUFFICIENT";
    }
    "PASS"
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CandidateGates {
    pub coverage_evaluable: bool,
    pub support_status: &'static str,
    pub numerical_resolution: bool,
    pub monte_carlo: NumericalDecision,
    pub omnibus_pass: bool,
    pub holm_pass: bool,
    pub temporal_status: &'static str,
}

pub fn candidate_terminal_state(gates: CandidateGates) -> &'static str {
    if !gates.coverage_evaluable {
        "NOT_EVALUABLE_COVERAGE"
    } else if gates.support_status != "PASS" {
        gates.support_status
    } else if !gates.numerical_resolution {
        "NUMERICAL_RESOLUTION_INSUFFICIENT"
    } else if gates.monte_carlo == NumericalDecision::Unresolved {
        "NUMERICAL_DECISION_UNRESOLVED"
    } else if gates.monte_carlo == NumericalDecision::Fail || !gates.omnibus_pass {
        "FAILS_OMNIBUS_EVIDENCE"
    } else if !gates.holm_pass {
        "FAILS_FAMILYWISE_CORRECTION"
    } else if gates.temporal_status == "TEMPORAL_SUPPORT_INSUFFICIENT" {
        "TEMPORAL_SUPPORT_INSUFFICIENT"
    } else if gates.temporal_status == "TEMPORALLY_UNSTABLE" {
        "TEMPORALLY_UNSTABLE"
    } else if gates.temporal_status == "TEMPORALLY_SUPPORTED" {
        "PROMOTED_DISCOVERY_ONLY"
    } else {
        "NOT_EVALUABLE_COVERAGE"
    }
}

pub fn validate_contracts(
    authority: &Value,
    measurements: &Value,
    inference: &Value,
    candidate: &Value,
    confirmation: &Value,
) -> AnyResult<()> {
    require_str(authority, "/authority_class", "PROTOCOL_ONLY")?;
    require_str(authority, "/parent_authorities/meas02_root", MEAS02_ROOT)?;
    require_str(
        authority,
        "/parent_authorities/instrument_root",
        INST01_ROOT,
    )?;
    require_str(
        authority,
        "/parent_authorities/universe_root",
        UNIVERSE_ROOT,
    )?;
    require_str(
        authority,
        "/parent_authorities/observer_instance",
        OBSERVER_INSTANCE,
    )?;
    require_u64(
        authority,
        "/populations/discovery_sessions",
        DISCOVERY_SESSIONS,
    )?;
    require_u64(
        authority,
        "/populations/confirmation_sessions",
        CONFIRMATION_SESSIONS,
    )?;
    require_str(
        authority,
        "/populations/discovery_state",
        "MEAS02_DISCOVERY_UNOPENED",
    )?;
    require_str(
        authority,
        "/populations/confirmation_state",
        "FROZEN_UNOPENED",
    )?;
    require_u64(inference, "/formal_tests", FORMAL_TESTS as u64)?;
    require_u64(inference, "/randomizations", RANDOMIZATIONS)?;
    require_u64(inference, "/seed", RANDOM_SEED)?;
    require_str(inference, "/independent_unit", "SESSION")?;
    require_str(confirmation, "/current_state", "FROZEN_UNOPENED")?;
    if confirmation
        .pointer("/confirmation_access_authorized_by_disc02p")
        .and_then(Value::as_bool)
        != Some(false)
    {
        return Err("CONFIRMATION_ACCESS_MUST_REMAIN_FALSE".into());
    }
    let formal = measurements
        .pointer("/formal_surfaces")
        .and_then(Value::as_array)
        .ok_or("FORMAL_SURFACES_MISSING")?;
    if formal.len() != FORMAL_TESTS {
        return Err("FORMAL_SURFACE_COUNT_DRIFT".into());
    }
    let unique: HashSet<&str> = formal
        .iter()
        .filter_map(|v| v.get("estimand_id").and_then(Value::as_str))
        .collect();
    if unique.len() != FORMAL_TESTS {
        return Err("FORMAL_ESTIMAND_IDS_NOT_UNIQUE".into());
    }
    if candidate
        .pointer("/discretionary_override")
        .and_then(Value::as_bool)
        != Some(false)
    {
        return Err("DISCRETIONARY_OVERRIDE_FORBIDDEN".into());
    }
    if !resolution_pass(RANDOMIZATIONS, ALPHA, FORMAL_TESTS, 10) {
        return Err("NUMERICAL_RESOLUTION_INSUFFICIENT".into());
    }
    Ok(())
}

fn require_str(value: &Value, pointer: &str, expected: &str) -> AnyResult<()> {
    if value.pointer(pointer).and_then(Value::as_str) != Some(expected) {
        return Err(format!("CONTRACT_MISMATCH:{pointer}:{expected}").into());
    }
    Ok(())
}

fn require_u64(value: &Value, pointer: &str, expected: u64) -> AnyResult<()> {
    if value.pointer(pointer).and_then(Value::as_u64) != Some(expected) {
        return Err(format!("CONTRACT_MISMATCH:{pointer}:{expected}").into());
    }
    Ok(())
}
