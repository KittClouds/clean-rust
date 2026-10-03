use crate::model::{
    AnchorKind, CensorReason, Orientation, OutcomeReceipt, OutcomeState, SyntheticBar,
};
use wide::f64x4;

pub const HORIZONS_MINUTES: [u16; 9] = [1, 2, 5, 10, 15, 30, 60, 120, 240];
pub const RAW_PRICE_THRESHOLDS: [f64; 9] = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0];
pub const RANGE_Z_THRESHOLDS: [f64; 4] = [1.0, 2.0, 4.0, 8.0];

pub fn oriented_delta(price: f64, anchor: f64, orientation: Orientation) -> Option<f64> {
    match orientation {
        Orientation::Upper => Some(price - anchor),
        Orientation::Lower => Some(anchor - price),
        Orientation::None => None,
    }
}

pub fn range_z(price: f64, midpoint: f64, width: f64) -> Option<f64> {
    (width > 0.0 && width.is_finite() && price.is_finite() && midpoint.is_finite())
        .then_some((price - midpoint) / (width / 2.0))
}

pub fn realized_variation_simd(closes: &[f64]) -> f64 {
    if closes.len() < 2 {
        return 0.0;
    }
    let mut lanes = f64x4::from([0.0; 4]);
    let mut index = 0;
    while index + 4 < closes.len() {
        lanes += f64x4::from([
            (closes[index + 1] - closes[index]).abs(),
            (closes[index + 2] - closes[index + 1]).abs(),
            (closes[index + 3] - closes[index + 2]).abs(),
            (closes[index + 4] - closes[index + 3]).abs(),
        ]);
        index += 4;
    }
    let mut total: f64 = lanes.to_array().into_iter().sum();
    while index + 1 < closes.len() {
        total += (closes[index + 1] - closes[index]).abs();
        index += 1;
    }
    total
}

#[allow(clippy::too_many_arguments)]
pub fn fixed_horizon_terminal(
    outcome_id: &str,
    anchor_id: &str,
    anchor_kind: AnchorKind,
    anchor_known_at: i64,
    anchor_price: f64,
    orientation: Orientation,
    horizon_minutes: u16,
    session_end: i64,
    bars: &[SyntheticBar],
) -> OutcomeReceipt {
    let requested_end = anchor_known_at + i64::from(horizon_minutes) * 60;
    let mut support = 0_u32;
    for bar in bars.iter().filter(|b| {
        b.close_epoch > anchor_known_at && b.close_epoch <= requested_end.min(session_end)
    }) {
        if !bar.coverage {
            return receipt(
                outcome_id,
                anchor_id,
                anchor_kind,
                anchor_known_at,
                requested_end,
                bar.close_epoch,
                None,
                OutcomeState::SourcePathIncomplete,
                CensorReason::SourcePathGap,
                support,
                None,
            );
        }
        support += 1;
    }
    if requested_end > session_end {
        return receipt(
            outcome_id,
            anchor_id,
            anchor_kind,
            anchor_known_at,
            requested_end,
            session_end,
            Some(session_end),
            OutcomeState::SessionTerminated,
            CensorReason::SessionTermination,
            support,
            None,
        );
    }
    let terminal = bars
        .iter()
        .find(|b| b.close_epoch == requested_end && b.coverage);
    match terminal.and_then(|bar| oriented_delta(bar.close, anchor_price, orientation)) {
        Some(value) => receipt(
            outcome_id,
            anchor_id,
            anchor_kind,
            anchor_known_at,
            requested_end,
            requested_end,
            Some(requested_end),
            OutcomeState::ObservedComplete,
            CensorReason::None,
            support,
            Some(value),
        ),
        None => receipt(
            outcome_id,
            anchor_id,
            anchor_kind,
            anchor_known_at,
            requested_end,
            requested_end,
            None,
            OutcomeState::NotEvaluable,
            CensorReason::InvalidAnchor,
            support,
            None,
        ),
    }
}

#[allow(clippy::too_many_arguments)]
pub fn first_passage(
    outcome_id: &str,
    anchor_id: &str,
    anchor_known_at: i64,
    anchor_price: f64,
    orientation: Orientation,
    threshold: f64,
    parallel: bool,
    censor_at: i64,
    censor_reason: CensorReason,
    bars: &[SyntheticBar],
) -> OutcomeReceipt {
    let mut support = 0_u32;
    for bar in bars
        .iter()
        .filter(|b| b.close_epoch > anchor_known_at && b.close_epoch <= censor_at)
    {
        if !bar.coverage {
            return receipt(
                outcome_id,
                anchor_id,
                AnchorKind::ExtremeCandidateBirth,
                anchor_known_at,
                censor_at,
                bar.close_epoch,
                None,
                OutcomeState::SourcePathIncomplete,
                CensorReason::SourcePathGap,
                support,
                None,
            );
        }
        support += 1;
        let Some(delta) = oriented_delta(bar.close, anchor_price, orientation) else {
            return receipt(
                outcome_id,
                anchor_id,
                AnchorKind::ExtremeCandidateBirth,
                anchor_known_at,
                censor_at,
                bar.close_epoch,
                None,
                OutcomeState::NotEvaluable,
                CensorReason::InvalidAnchor,
                support,
                None,
            );
        };
        let crossed = if parallel {
            delta >= threshold
        } else {
            delta <= -threshold
        };
        if crossed {
            return receipt(
                outcome_id,
                anchor_id,
                AnchorKind::ExtremeCandidateBirth,
                anchor_known_at,
                censor_at,
                bar.close_epoch,
                Some(bar.close_epoch),
                OutcomeState::ObservedComplete,
                CensorReason::None,
                support,
                Some((bar.close_epoch - anchor_known_at) as f64 / 60.0),
            );
        }
    }
    receipt(
        outcome_id,
        anchor_id,
        AnchorKind::ExtremeCandidateBirth,
        anchor_known_at,
        censor_at,
        censor_at,
        Some(censor_at),
        OutcomeState::RightCensored,
        censor_reason,
        support,
        None,
    )
}

pub fn validate_receipt(receipt: &OutcomeReceipt) -> Result<(), &'static str> {
    if receipt.outcome_window_start != receipt.anchor_known_at {
        return Err("OUTCOME_WINDOW_DOES_NOT_BEGIN_AT_ANCHOR_KNOWLEDGE");
    }
    if receipt.observed_until < receipt.anchor_known_at {
        return Err("OBSERVATION_PRECEDES_ANCHOR");
    }
    if receipt
        .outcome_known_at
        .is_some_and(|known| known < receipt.anchor_known_at)
    {
        return Err("OUTCOME_KNOWN_BEFORE_ANCHOR");
    }
    if receipt.outcome_state == OutcomeState::ObservedComplete
        && (receipt.outcome_known_at.is_none() || receipt.value.is_none())
    {
        return Err("COMPLETED_OUTCOME_MISSING_KNOWLEDGE_OR_VALUE");
    }
    if matches!(
        receipt.outcome_state,
        OutcomeState::RightCensored
            | OutcomeState::SessionTerminated
            | OutcomeState::SourcePathIncomplete
            | OutcomeState::NotEvaluable
    ) && receipt.value.is_some()
    {
        return Err("NONCOMPLETE_OUTCOME_HAS_COMPLETED_VALUE");
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn receipt(
    outcome_id: &str,
    anchor_id: &str,
    anchor_kind: AnchorKind,
    anchor_known_at: i64,
    requested_end: i64,
    observed_until: i64,
    outcome_known_at: Option<i64>,
    outcome_state: OutcomeState,
    censor_reason: CensorReason,
    support_bars: u32,
    value: Option<f64>,
) -> OutcomeReceipt {
    OutcomeReceipt {
        outcome_id: outcome_id.to_owned(),
        anchor_id: anchor_id.to_owned(),
        anchor_kind,
        anchor_known_at,
        outcome_window_start: anchor_known_at,
        requested_window_end: requested_end,
        observed_until,
        outcome_known_at,
        outcome_state,
        censor_reason,
        support_bars,
        value,
    }
}
