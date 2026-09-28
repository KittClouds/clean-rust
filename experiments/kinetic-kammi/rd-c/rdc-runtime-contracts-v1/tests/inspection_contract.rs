use rdc_runtime_contracts_v1::{
    ActionCode, InspectionKind, InspectionReply, InspectionResult, TransportStatus,
    inspection::{NO_ACTION, REPLY_BYTES},
};

fn reply(transport: TransportStatus, candidate: u16, competing: u16) -> InspectionReply {
    InspectionReply {
        transport,
        candidate,
        competing_candidate: competing,
        confidence_milli: 950,
        signature_valid: true,
        source_revision: 7,
        payload_digest: [0xA5; 32],
    }
}

#[test]
fn only_confirmed_and_unique_contradicted_results_propose_actions() {
    let active = ActionCode(3);
    let confirmed = InspectionResult::classify(
        active,
        reply(TransportStatus::Complete, active.0, NO_ACTION),
    );
    assert_eq!(confirmed.kind, InspectionKind::Confirmed);
    assert_eq!(confirmed.proposed_action, Some(active));

    let contradicted =
        InspectionResult::classify(active, reply(TransportStatus::Complete, 9, NO_ACTION));
    assert_eq!(contradicted.kind, InspectionKind::Contradicted);
    assert_eq!(contradicted.proposed_action, Some(ActionCode(9)));

    for transport in [TransportStatus::Timeout, TransportStatus::Unavailable] {
        let result = InspectionResult::classify(active, reply(transport, NO_ACTION, NO_ACTION));
        assert_eq!(result.kind, InspectionKind::Failed);
        assert_eq!(result.proposed_action, None);
    }
    for value in [
        reply(TransportStatus::Malformed, NO_ACTION, NO_ACTION),
        reply(TransportStatus::Complete, 7, 8),
    ] {
        let result = InspectionResult::classify(active, value);
        assert_eq!(result.kind, InspectionKind::Unknown);
        assert_eq!(result.proposed_action, None);
    }
}

#[test]
fn typed_reply_round_trips_as_a_fixed_zero_copy_surface() {
    let original = reply(TransportStatus::Complete, 7, NO_ACTION);
    let bytes = original.encode().unwrap();
    assert_eq!(bytes.len(), REPLY_BYTES);
    assert_eq!(InspectionReply::decode(&bytes).unwrap(), original);
    let mut invalid = bytes;
    invalid[63] = 1;
    assert!(InspectionReply::decode(&invalid).is_err());
}
