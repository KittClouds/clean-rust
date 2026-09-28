use serde::{Deserialize, Serialize};

pub const OBSERVER_SCHEMA_VERSION: u16 = 1;
pub const OBSERVER_OUTPUT_SCHEMA: &str = "rdc-coding-observer-output.v1";
pub const OBSERVER_OUTPUT_SCHEMA_V2: &str = "rdc-coding-observer-output.v2";
pub const OBSERVER_INPUT_SCHEMA: &str = "rdc-real-coding-observation.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActionOption {
    pub id: u16,
    pub schema_id: u16,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObserverOutput {
    /// `None` is an explicit action-choice abstention.
    pub action_choice: Option<u16>,
    /// All scores use the closed interval [0, 1000].
    pub applicability_milli: u16,
    pub abstention_milli: u16,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HeadThresholds {
    pub minimum_applicability_milli: u16,
    pub maximum_abstention_milli: u16,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum TypedDecision {
    Propose { action_id: u16 },
    Abstain(AbstentionReason),
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum AbstentionReason {
    Explicit,
    NotApplicable,
    Uncertain,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OutputError {
    ScoreOutOfRange,
    ThresholdOutOfRange,
    DuplicateAction,
    UnknownAction,
}

impl ObserverOutput {
    pub fn compile(
        self,
        allowed_actions: &[ActionOption],
        thresholds: HeadThresholds,
    ) -> Result<TypedDecision, OutputError> {
        if self.applicability_milli > 1000 || self.abstention_milli > 1000 {
            return Err(OutputError::ScoreOutOfRange);
        }
        if thresholds.minimum_applicability_milli > 1000
            || thresholds.maximum_abstention_milli > 1000
        {
            return Err(OutputError::ThresholdOutOfRange);
        }
        for (index, action) in allowed_actions.iter().enumerate() {
            if allowed_actions[..index]
                .iter()
                .any(|prior| prior.id == action.id)
            {
                return Err(OutputError::DuplicateAction);
            }
        }
        if self.abstention_milli > thresholds.maximum_abstention_milli {
            return Ok(TypedDecision::Abstain(AbstentionReason::Uncertain));
        }
        if self.applicability_milli < thresholds.minimum_applicability_milli {
            return Ok(TypedDecision::Abstain(AbstentionReason::NotApplicable));
        }
        let Some(action_id) = self.action_choice else {
            return Ok(TypedDecision::Abstain(AbstentionReason::Explicit));
        };
        if !allowed_actions.iter().any(|action| action.id == action_id) {
            return Err(OutputError::UnknownAction);
        }
        Ok(TypedDecision::Propose { action_id })
    }
}
