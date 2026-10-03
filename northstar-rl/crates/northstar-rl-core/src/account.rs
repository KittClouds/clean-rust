use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::{
    Digest, Error, ExecutionSpec, InstrumentContract, QuantityRounding, REWARD_PRIMITIVES_V1,
    Result, RunRawRow, identity,
};

#[derive(Clone, Copy, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct AccountState {
    pub cash: f64,
    pub equity: f64,
    pub realized_pnl: f64,
    pub unrealized_pnl: f64,
    pub target_exposure: f64,
    pub actual_exposure: f64,
    pub quantity: f64,
    pub average_price: f64,
    pub cumulative_turnover: f64,
    pub cumulative_friction: f64,
    pub peak_equity: f64,
    pub drawdown: f64,
}

impl AccountState {
    pub fn initial(equity: f64) -> Result<Self> {
        if !equity.is_finite() || equity <= 0.0 {
            return Err(Error::InvalidContract(
                "initial equity must be finite and positive".into(),
            ));
        }
        Ok(Self {
            cash: equity,
            equity,
            realized_pnl: 0.0,
            unrealized_pnl: 0.0,
            target_exposure: 0.0,
            actual_exposure: 0.0,
            quantity: 0.0,
            average_price: 0.0,
            cumulative_turnover: 0.0,
            cumulative_friction: 0.0,
            peak_equity: equity,
            drawdown: 0.0,
        })
    }

    pub fn id(&self) -> Result<Digest> {
        identity(b"northstar-account-state-v1", self)
    }
}

#[derive(Clone, Copy, Debug, Default, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct RewardPrimitives {
    pub schema_version_code: u32,
    pub gross_mark_to_market_delta: f64,
    pub realized_pnl_delta: f64,
    pub unrealized_pnl_delta: f64,
    pub equity_delta: f64,
    pub turnover: f64,
    pub commission_cost: f64,
    pub spread_cost: f64,
    pub slippage_cost: f64,
    pub total_friction: f64,
    pub exposure: f64,
    pub exposure_change: f64,
    pub drawdown: f64,
    pub drawdown_change: f64,
}

impl RewardPrimitives {
    pub const SCHEMA: &'static str = REWARD_PRIMITIVES_V1;

    pub fn vector(self) -> [f64; 13] {
        [
            self.gross_mark_to_market_delta,
            self.realized_pnl_delta,
            self.unrealized_pnl_delta,
            self.equity_delta,
            self.turnover,
            self.commission_cost,
            self.spread_cost,
            self.slippage_cost,
            self.total_friction,
            self.exposure,
            self.exposure_change,
            self.drawdown,
            self.drawdown_change,
        ]
    }
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ExecutionReceipt {
    pub execution_receipt_id: Digest,
    pub action_source_row_id: u64,
    pub fill_source_row_id: u64,
    pub action: f32,
    pub reference_price: f64,
    pub target_quantity: f64,
    pub prior_quantity: f64,
    pub quantity_delta: f64,
    pub rounded: bool,
    pub turnover: f64,
    pub commission_cost: f64,
    pub spread_cost: f64,
    pub slippage_cost: f64,
    pub total_friction: f64,
}

#[derive(Clone, Debug)]
pub struct Transition {
    pub after: AccountState,
    pub receipt: ExecutionReceipt,
    pub primitives: RewardPrimitives,
}

pub fn apply_transition(
    prior: AccountState,
    action_source_row_id: u64,
    execution_row: RunRawRow,
    action: f32,
    instrument: &InstrumentContract,
    execution: &ExecutionSpec,
) -> Result<Transition> {
    if !action.is_finite() || !(-1.0..=1.0).contains(&action) {
        return Err(Error::Environment(
            "action must be finite and in [-1, 1]".into(),
        ));
    }
    if execution_row.open <= 0.0 || execution_row.close <= 0.0 {
        return Err(Error::Environment(
            "execution prices must be positive".into(),
        ));
    }
    let raw_target = action as f64 * prior.equity / (execution_row.open * instrument.contract_size);
    let target_quantity = round_quantity(raw_target, instrument, &execution.quantity_rounding);
    let quantity_delta = target_quantity - prior.quantity;
    let turnover = quantity_delta.abs() * execution_row.open * instrument.contract_size;
    let traded = quantity_delta != 0.0;
    let commission_cost = if traded {
        execution.fixed_commission
    } else {
        0.0
    } + turnover * execution.proportional_commission;
    let spread_cost = quantity_delta.abs() * execution.spread_ticks * instrument.tick_value;
    let slippage_cost = quantity_delta.abs() * execution.slippage_ticks * instrument.tick_value;
    let total_friction = commission_cost + spread_cost + slippage_cost;

    let (realized_delta, average_price) = position_transition(
        prior.quantity,
        prior.average_price,
        target_quantity,
        execution_row.open,
        instrument.contract_size,
    );
    let unrealized_pnl = if target_quantity == 0.0 {
        0.0
    } else {
        (execution_row.close - average_price) * target_quantity * instrument.contract_size
    };
    let gross_mark_to_market_delta = realized_delta + unrealized_pnl - prior.unrealized_pnl;
    let cash = prior.cash + realized_delta - total_friction;
    let equity = cash + unrealized_pnl;
    let peak_equity = prior.peak_equity.max(equity);
    let drawdown = if peak_equity > 0.0 {
        (peak_equity - equity) / peak_equity
    } else {
        1.0
    };
    let actual_exposure = if equity.abs() > f64::EPSILON {
        target_quantity * execution_row.close * instrument.contract_size / equity
    } else {
        0.0
    };
    let after = AccountState {
        cash,
        equity,
        realized_pnl: prior.realized_pnl + realized_delta,
        unrealized_pnl,
        target_exposure: action as f64,
        actual_exposure,
        quantity: target_quantity,
        average_price,
        cumulative_turnover: prior.cumulative_turnover + turnover,
        cumulative_friction: prior.cumulative_friction + total_friction,
        peak_equity,
        drawdown,
    };
    if !account_finite(&after) {
        return Err(Error::Environment(
            "account transition produced a non-finite value".into(),
        ));
    }
    let primitives = RewardPrimitives {
        schema_version_code: 1,
        gross_mark_to_market_delta,
        realized_pnl_delta: realized_delta,
        unrealized_pnl_delta: unrealized_pnl - prior.unrealized_pnl,
        equity_delta: equity - prior.equity,
        turnover,
        commission_cost,
        spread_cost,
        slippage_cost,
        total_friction,
        exposure: actual_exposure,
        exposure_change: actual_exposure - prior.actual_exposure,
        drawdown,
        drawdown_change: drawdown - prior.drawdown,
    };
    let mut receipt = ExecutionReceipt {
        execution_receipt_id: Digest::ZERO,
        action_source_row_id,
        fill_source_row_id: execution_row.source_row_id,
        action,
        reference_price: execution_row.open,
        target_quantity,
        prior_quantity: prior.quantity,
        quantity_delta,
        rounded: (raw_target - target_quantity).abs() > f64::EPSILON,
        turnover,
        commission_cost,
        spread_cost,
        slippage_cost,
        total_friction,
    };
    receipt.execution_receipt_id = identity(b"northstar-execution-receipt-v1", &receipt)?;
    Ok(Transition {
        after,
        receipt,
        primitives,
    })
}

fn round_quantity(raw: f64, instrument: &InstrumentContract, policy: &QuantityRounding) -> f64 {
    let units = raw / instrument.quantity_step;
    let rounded = match policy {
        QuantityRounding::TowardZero => units.trunc(),
        QuantityRounding::Nearest => units.round(),
    } * instrument.quantity_step;
    if rounded.abs() < instrument.minimum_quantity {
        0.0
    } else {
        rounded.clamp(-instrument.maximum_quantity, instrument.maximum_quantity)
    }
}

fn position_transition(
    old: f64,
    old_average: f64,
    new: f64,
    price: f64,
    contract: f64,
) -> (f64, f64) {
    if old == new {
        return (0.0, old_average);
    }
    if old == 0.0 {
        return (0.0, if new == 0.0 { 0.0 } else { price });
    }
    if new == 0.0 {
        return ((price - old_average) * old * contract, 0.0);
    }
    if old.signum() == new.signum() {
        if new.abs() > old.abs() {
            let added = new.abs() - old.abs();
            let average = (old_average * old.abs() + price * added) / new.abs();
            (0.0, average)
        } else {
            let closed = old.abs() - new.abs();
            (
                (price - old_average) * old.signum() * closed * contract,
                old_average,
            )
        }
    } else {
        let realized = (price - old_average) * old * contract;
        (realized, price)
    }
}

fn account_finite(state: &AccountState) -> bool {
    [
        state.cash,
        state.equity,
        state.realized_pnl,
        state.unrealized_pnl,
        state.target_exposure,
        state.actual_exposure,
        state.quantity,
        state.average_price,
        state.cumulative_turnover,
        state.cumulative_friction,
        state.peak_equity,
        state.drawdown,
    ]
    .iter()
    .all(|value| value.is_finite())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fixtures::{canonical_execution_spec, canonical_instrument};

    #[test]
    fn positive_to_negative_realizes_old_side_and_opens_new_side() {
        let instrument = canonical_instrument().unwrap();
        let execution = canonical_execution_spec().unwrap();
        let mut prior = AccountState::initial(1_000.0).unwrap();
        prior.quantity = 5.0;
        prior.average_price = 100.0;
        let row = RunRawRow {
            open: 110.0,
            close: 109.0,
            source_row_id: 2,
            ..crate::fixtures::row(1, 110.0)
        };
        let transition = apply_transition(prior, 1, row, -0.5, &instrument, &execution).unwrap();
        assert!(transition.primitives.realized_pnl_delta > 0.0);
        assert!(transition.after.quantity < 0.0);
        assert_eq!(transition.after.average_price, 110.0);
    }
}
