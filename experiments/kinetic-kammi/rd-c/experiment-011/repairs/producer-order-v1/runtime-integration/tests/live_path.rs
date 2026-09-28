use rdc_e011_runtime_integration::{
    PresentationBinding, PresentationRuntimeError, PresentedOption, hex_digest,
    prepare_presentation, resolve_response,
};
use rdc_experiment_009::observer::ActionOption;
use rdc_runtime_contracts_v1::CandidatePresentationError;

fn option(ordinal: u16, action_id: u16, digest: u8) -> PresentedOption {
    PresentedOption {
        producer_ordinal: ordinal,
        action: ActionOption {
            id: action_id,
            schema_id: 1,
        },
        summary: format!("candidate {action_id}"),
        diff_excerpt: format!("diff {action_id}"),
        patch_sha256: format!("{digest:02x}").repeat(32),
    }
}

fn ordered_fixture() -> Vec<PresentedOption> {
    vec![
        option(0, 11, 1),
        option(1, 37, 2),
        option(2, 68, 3),
        option(3, 94, 4),
    ]
}

#[test]
fn normal_producer_order_path_binds_request_response_and_resolves_action() {
    let task_digest = [0xA5; 32];
    let prepared = prepare_presentation(task_digest, ordered_fixture()).unwrap();
    let resolved = resolve_response(
        PresentationBinding {
            task_digest,
            receipt: &prepared.receipt,
            request_receipt_digest: prepared.receipt_digest,
            response_receipt_digest: prepared.receipt_digest,
            request_id: prepared.request_id,
            response_request_id: prepared.request_id,
        },
        &prepared.ordered_options,
        Some(37),
    )
    .unwrap()
    .unwrap();
    assert_eq!(resolved.action.id, 37);
    assert_eq!(resolved.patch_sha256, format!("{:02x}", 2).repeat(32));
    assert_eq!(hex_digest(&prepared.receipt_digest).len(), 64);
}

#[test]
fn transport_scramble_is_restored_before_observer_serialization() {
    let task_digest = [0xA5; 32];
    let original = ordered_fixture();
    let expected = prepare_presentation(task_digest, original.clone()).unwrap();
    let scrambled = vec![
        original[2].clone(),
        original[0].clone(),
        original[3].clone(),
        original[1].clone(),
    ];
    let restored = prepare_presentation(task_digest, scrambled).unwrap();
    assert_eq!(restored.ordered_options, expected.ordered_options);
    assert_eq!(restored.receipt, expected.receipt);
    assert_eq!(restored.request_id, expected.request_id);
}

#[test]
fn mutation_after_receipt_is_rejected_and_uses_no_action_fallback() {
    let task_digest = [0xA5; 32];
    let prepared = prepare_presentation(task_digest, ordered_fixture()).unwrap();
    let mut mutated = prepared.ordered_options.clone();
    mutated.swap(0, 1);
    let result = resolve_response(
        PresentationBinding {
            task_digest,
            receipt: &prepared.receipt,
            request_receipt_digest: prepared.receipt_digest,
            response_receipt_digest: prepared.receipt_digest,
            request_id: prepared.request_id,
            response_request_id: prepared.request_id,
        },
        &mutated,
        Some(37),
    );
    assert_eq!(
        result,
        Err(PresentationRuntimeError::Candidate(
            CandidatePresentationError::CandidateSequenceChanged
        ))
    );
    // The authorizer's configured drift fallback is ABSTAIN_AND_ABORT_ACTION.
    assert!(result.is_err());
}

#[test]
fn response_replay_against_another_presentation_is_rejected() {
    let task_digest = [0xA5; 32];
    let first = prepare_presentation(task_digest, ordered_fixture()).unwrap();
    let second_options = vec![
        option(0, 37, 2),
        option(1, 11, 1),
        option(2, 68, 3),
        option(3, 94, 4),
    ];
    let second = prepare_presentation(task_digest, second_options).unwrap();
    let result = resolve_response(
        PresentationBinding {
            task_digest,
            receipt: &first.receipt,
            request_receipt_digest: first.receipt_digest,
            response_receipt_digest: second.receipt_digest,
            request_id: first.request_id,
            response_request_id: second.request_id,
        },
        &first.ordered_options,
        Some(37),
    );
    assert_eq!(
        result,
        Err(PresentationRuntimeError::RequestResponseReceiptMismatch)
    );
}
