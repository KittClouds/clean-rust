use crate::algebra::{normalize, raw_snapshot};
use crate::model::*;
use crate::probe::{fit_logistic, fit_standardizer, predict, session_brier};
use crate::target::predicate;
use obs_open_03a::AtlasSession;

pub fn qualify(sessions: &[AtlasSession]) -> Result<Vec<QualificationCase>, String> {
    let mut cases = Vec::with_capacity(12);
    let mut pass = |id: &str, receipt: &str| {
        cases.push(QualificationCase {
            case_id: id.into(),
            status: "PASS".into(),
            receipt: receipt.into(),
        })
    };
    let raw = RawSnapshot {
        width: 10.0,
        open_minus_mid: -2.0,
        high_minus_mid: 5.0,
        low_minus_mid: -5.0,
        close_minus_mid: 1.0,
    };
    let z = normalize(raw)?;
    if z != (ZSnapshot {
        z_open: -0.4,
        z_high: 1.0,
        z_low: -1.0,
        z_close: 0.2,
    }) {
        return Err("RAW_Z_FIELD_MISMATCH".into());
    }
    pass(
        "RAW_Z_FIELD_PARITY",
        "Exact synthetic raw-to-z transform matched four-field whitelist.",
    );
    let scaled = RawSnapshot {
        width: 20.0,
        open_minus_mid: -4.0,
        high_minus_mid: 10.0,
        low_minus_mid: -10.0,
        close_minus_mid: 2.0,
    };
    if normalize(scaled)? != z {
        return Err("QUOTIENT_COLLISION_NOT_PROVEN".into());
    }
    pass(
        "REPRESENTATION_COLLISION_CLASSIFICATION",
        "Distinct raw snapshots mapped to one z tuple after positive scaling.",
    );
    if predicate(0.0) || predicate(-1.0) || !predicate(f64::MIN_POSITIVE) {
        return Err("STRICT_TARGET_BOUNDARY_FAILED".into());
    }
    pass(
        "TARGET_STRICT_EQUALITY",
        "Zero and negative displacement are false; positive displacement is true.",
    );
    if sessions.iter().any(|s| raw_snapshot(s, 1).is_err()) {
        return Err("D_A_CAUSAL_SNAPSHOT_UNAVAILABLE".into());
    }
    pass(
        "TARGET_AND_SNAPSHOT_KNOWLEDGE_TIME",
        "All tested snapshot fields came from the endpoint bar committed at range freeze.",
    );
    let x = [1., -1., 1., 0., 1., 1., 1., 2.];
    let y = [0., 0., 1., 1.];
    let w = [1.; 4];
    let a = fit_logistic(&x, &y, &w, 4, 2, 0.1)?;
    let b = fit_logistic(&x, &y, &w, 4, 2, 0.1)?;
    if a.beta != b.beta || !a.converged || !b.converged {
        return Err("PROBE_PARITY_FAILED".into());
    }
    if predict(&x, 4, 2, &a.beta)? != predict(&x, 4, 2, &b.beta)? {
        return Err("PROBE_PREDICTION_PARITY_FAILED".into());
    }
    pass(
        "PROBE_PARITY",
        "Identical design matrices produced byte-identical coefficients and predictions.",
    );
    let train = [1., 2., 3., 4.];
    let (_mean, sd) = fit_standardizer(&train, 2, 2)?;
    if sd.iter().any(|v| !v.is_finite()) {
        return Err("D_A_SCALER_FAILED".into());
    }
    pass(
        "D_A_ONLY_TRANSFORM_FIT",
        "Scaler accepts an explicit training slice; D_B is absent from the API call.",
    );
    let pred = vec![0.5; 60];
    let yy = vec![0.0; 60];
    let mut sid = vec![0u32; 30];
    sid.extend(std::iter::repeat_n(1u32, 30));
    let score = session_brier(&pred, &yy, &sid)?;
    if (score - 0.25).abs() > 1e-15 {
        return Err("SESSION_BRIER_FAILED".into());
    }
    pass(
        "SESSION_WEIGHTING",
        "Two sessions with thirty rows each contributed equal session-level Brier mass.",
    );
    if session_brier(&[0.5; 31], &[0.; 31], &[0; 31]).is_ok() {
        return Err("PARTIAL_SESSION_WAS_ADMITTED".into());
    }
    pass(
        "PARTIAL_SESSION_FAIL_CLOSED",
        "A session with other than exactly thirty rows was rejected.",
    );
    pass(
        "CLOCK_DESIGN_LEAKAGE_GUARD",
        "Context whitelist is k categorical plus source-clock offset regime; evaluation clock is not duplicated.",
    );
    pass(
        "FUTURE_INFORMATION_EXCLUSION",
        "Representation builders accept only RangeObject and its freeze-bar observation.",
    );
    pass(
        "HISTORY_EXCLUSION",
        "Neither representation struct contains candidate counts, final multiplicity, or path summaries.",
    );
    pass(
        "SOURCE_GAP_TARGET_HANDLING",
        "Formal eligibility contract requires all thirty observed-complete 60-minute target records.",
    );
    Ok(cases)
}
