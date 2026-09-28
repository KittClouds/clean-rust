use rdc_experiment_009::{
    observer::{
        AbstentionReason, ActionOption, HeadThresholds, ObserverOutput, OutputError, TypedDecision,
    },
    policy::{PaidInspection, RuntimePolicy},
};

#[test]
fn paid_inspection_is_disabled_by_default_and_requires_explicit_enablement() {
    let policy = RuntimePolicy::default();
    assert_eq!(policy.paid_inspection, PaidInspection::Disabled);
    assert!(!policy.may_request_paid_inspection());
    assert!(
        RuntimePolicy {
            paid_inspection: PaidInspection::Enabled
        }
        .may_request_paid_inspection()
    );
}

#[test]
fn typed_heads_abstain_on_uncertainty_and_reject_actions_outside_the_offer() {
    let actions = [ActionOption {
        id: 4,
        schema_id: 2,
    }];
    let thresholds = HeadThresholds {
        minimum_applicability_milli: 600,
        maximum_abstention_milli: 400,
    };
    let good = ObserverOutput {
        action_choice: Some(4),
        applicability_milli: 900,
        abstention_milli: 100,
    };
    assert_eq!(
        good.compile(&actions, thresholds),
        Ok(TypedDecision::Propose { action_id: 4 })
    );
    let uncertain = ObserverOutput {
        abstention_milli: 700,
        ..good
    };
    assert_eq!(
        uncertain.compile(&actions, thresholds),
        Ok(TypedDecision::Abstain(AbstentionReason::Uncertain))
    );
    let invalid_action = ObserverOutput {
        action_choice: Some(5),
        ..good
    };
    assert_eq!(
        invalid_action.compile(&actions, thresholds),
        Err(OutputError::UnknownAction)
    );
    let invalid_score = ObserverOutput {
        applicability_milli: 1001,
        ..good
    };
    assert_eq!(
        invalid_score.compile(&actions, thresholds),
        Err(OutputError::ScoreOutOfRange)
    );
}
