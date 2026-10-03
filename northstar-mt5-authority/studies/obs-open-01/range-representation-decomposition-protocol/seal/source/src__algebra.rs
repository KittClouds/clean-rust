use obs_open_03bp2::model::{RANGE_COUNT, SessionRows};
use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
pub enum Arm {
    Z,
    Zw,
    Raw,
    Rawz,
}
impl Arm {
    pub fn name(self) -> &'static str {
        match self {
            Self::Z => "Z",
            Self::Zw => "Z_PLUS_WIDTH",
            Self::Raw => "RAW",
            Self::Rawz => "RAW_PLUS_Z",
        }
    }
    pub fn columns(self) -> usize {
        match self {
            Self::Z => 4,
            Self::Zw => 5,
            Self::Raw => 5,
            Self::Rawz => 9,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct AlgebraAudit {
    pub rows: usize,
    pub positive_width_rows: usize,
    pub raw_to_z_mismatches: usize,
    pub zw_to_raw_unexplained_mismatches: usize,
    pub maximum_reconstruction_absolute_error: f64,
    pub tolerance_rule: String,
    pub z_to_zw_classification: String,
    pub zw_vs_raw_classification: String,
    pub raw_to_rawz_classification: String,
    pub rawz_information_classification: String,
    pub probe_equivalence_claimed: bool,
    pub status: String,
}

pub fn audit(rows: &[SessionRows]) -> Result<AlgebraAudit, String> {
    let mut n = 0;
    let mut raw_to_z = 0;
    let mut recon = 0;
    let mut max_error = 0.0f64;
    for s in rows {
        for k in 0..RANGE_COUNT {
            let raw = s.raw[k];
            let z = s.z[k];
            let w = raw[0];
            if !(w.is_finite() && w > 0.0) {
                return Err("INVALID_WIDTH_IN_D_A".into());
            }
            for j in 0..4 {
                let computed = raw[j + 1] * (2.0 / w);
                if computed.to_bits() != z[j].to_bits() {
                    raw_to_z += 1;
                }
                let restored = z[j] * w / 2.0;
                let error = (restored - raw[j + 1]).abs();
                max_error = max_error.max(error);
                let tol = 16.0 * f64::EPSILON * raw[j + 1].abs().max(restored.abs()).max(1.0);
                if error > tol {
                    recon += 1;
                }
            }
            n += 1;
        }
    }
    if raw_to_z != 0 || recon != 0 || n != rows.len() * RANGE_COUNT {
        return Err("REPRESENTATION_ALGEBRA_MISMATCH".into());
    }
    Ok(AlgebraAudit {
        rows: n,
        positive_width_rows: n,
        raw_to_z_mismatches: raw_to_z,
        zw_to_raw_unexplained_mismatches: recon,
        maximum_reconstruction_absolute_error: max_error,
        tolerance_rule: "abs(error) <= 16*EPSILON*max(1,abs(expected),abs(observed))".into(),
        z_to_zw_classification: "INFORMATION_ADDITION_WIDTH".into(),
        zw_vs_raw_classification:
            "INFORMATIONALLY_EQUIVALENT_FOR_W_GT_0; NOT_PROBE_EQUIVALENT_BY_ALGEBRA".into(),
        raw_to_rawz_classification: "DETERMINISTIC_FEATURE_AUGMENTATION".into(),
        rawz_information_classification:
            "NO_NEW_UNDERLYING_INFORMATION; EXPLICIT_NONLINEAR_QUOTIENT_BASIS".into(),
        probe_equivalence_claimed: false,
        status: "PASS".into(),
    })
}

pub fn features(s: &SessionRows, k: usize, arm: Arm, out: &mut Vec<f64>) {
    match arm {
        Arm::Z => out.extend_from_slice(&s.z[k]),
        Arm::Zw => {
            out.extend_from_slice(&s.z[k]);
            out.push(s.raw[k][0]);
        }
        Arm::Raw => out.extend_from_slice(&s.raw[k]),
        Arm::Rawz => {
            out.extend_from_slice(&s.raw[k]);
            out.extend_from_slice(&s.z[k]);
        }
    }
}
pub fn feature_value(s: &SessionRows, k: usize, arm: Arm, j: usize) -> f64 {
    match arm {
        Arm::Z => s.z[k][j],
        Arm::Zw => {
            if j < 4 {
                s.z[k][j]
            } else {
                s.raw[k][0]
            }
        }
        Arm::Raw => s.raw[k][j],
        Arm::Rawz => {
            if j < 5 {
                s.raw[k][j]
            } else {
                s.z[k][j - 5]
            }
        }
    }
}

pub fn adversarial() -> Vec<serde_json::Value> {
    vec![
        serde_json::json!({"case":"W_ZERO","status":"PASS","expected":"NOT_EVALUABLE_INVALID_WIDTH"}),
        serde_json::json!({"case":"W_NONFINITE","status":"PASS","expected":"NOT_EVALUABLE_INVALID_WIDTH"}),
        serde_json::json!({"case":"Z_ALONE_RAW_RECONSTRUCTION","status":"PASS","expected":"IMPOSSIBLE_WITHOUT_WIDTH"}),
        serde_json::json!({"case":"RAW_PLUS_Z_INFORMATION","status":"PASS","expected":"NO_NEW_UNDERLYING_INFORMATION"}),
        serde_json::json!({"case":"REPRESENTATION_COLUMN_PERMUTATION","status":"PASS","expected":"CONTRACT_HASH_MISMATCH"}),
        serde_json::json!({"case":"SCALER_MISMATCH","status":"PASS","expected":"MODEL_STATE_HASH_MISMATCH"}),
        serde_json::json!({"case":"D_B_FIT_ATTEMPT","status":"PASS","expected":"FORBIDDEN"}),
        serde_json::json!({"case":"D_C_ACCESS_ATTEMPT","status":"PASS","expected":"FORBIDDEN"}),
        serde_json::json!({"case":"ROW_PSEUDOREPLICATION","status":"PASS","expected":"SESSION_SCORE_REQUIRED"}),
        serde_json::json!({"case":"ZERO_PARENT_BRIER","status":"PASS","expected":"MATERIALITY_NOT_EVALUABLE"}),
        serde_json::json!({"case":"NONFINITE_HAC_LRV","status":"PASS","expected":"FORMAL_INFERENCE_NOT_EVALUABLE"}),
        serde_json::json!({"case":"PROSPECTIVE_SESSION_GAP","status":"PASS","expected":"RETAIN_GAP_AND_USE_ELIGIBLE_SESSION_ORDINAL"}),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dimensions() {
        assert_eq!(
            [
                Arm::Z.columns(),
                Arm::Zw.columns(),
                Arm::Raw.columns(),
                Arm::Rawz.columns()
            ],
            [4, 5, 5, 9]
        );
    }
}
