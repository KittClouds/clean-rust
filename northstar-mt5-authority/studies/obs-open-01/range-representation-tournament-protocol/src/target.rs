use crate::model::*;
use obs_open_03a::PackedOutcome;

pub fn support(records: &[PackedOutcome]) -> Result<TargetSupportReceipt, String> {
    let mut seen = 0usize;
    let mut complete = 0usize;
    let mut per_session = vec![0usize; D_A_SESSIONS];
    for r in records.iter().filter(|r| {
        r.anchor_kind == 2
            && r.outcome_code == 101
            && r.representation == 1
            && r.horizon_minutes == TARGET_HORIZON_MINUTES
    }) {
        seen += 1;
        if r.k == 0 || r.k > 30 || r.session_index as usize >= D_A_SESSIONS {
            return Err("TARGET_RECORD_IDENTITY_DRIFT".into());
        }
        if r.outcome_state == 1
            && r.value_present == 1
            && r.support_bars == 60
            && r.outcome_known_present == 1
            && r.outcome_known_at == r.anchor_known_at + 3600
        {
            complete += 1;
            per_session[r.session_index as usize] += 1;
        }
    }
    if seen != RANGE_COUNT {
        return Err(format!("TARGET_RECORD_COUNT_DRIFT:{seen}"));
    }
    let complete_sessions = per_session.iter().filter(|&&n| n == 30).count();
    if per_session.iter().any(|&n| n > 30) {
        return Err("DUPLICATE_TARGET_RECORD".into());
    }
    Ok(TargetSupportReceipt {
        target_id: "STRICT_ABOVE_FROZEN_MIDPOINT_AT_60M_V1".into(),
        range_records_seen: seen,
        observed_complete_records: complete,
        unavailable_records: seen - complete,
        complete_sessions,
        incomplete_sessions: D_A_SESSIONS - complete_sessions,
        values_decoded: 0,
        equality_rule: "raw terminal displacement > 0; equality is false".into(),
        registry_binding: "OUTCOME_REGISTRY_V1 / RangeTerminalClose / RAW_PRICE / 60m".into(),
    })
}

pub fn predicate(raw_terminal_displacement: f64) -> bool {
    raw_terminal_displacement > 0.0
}
