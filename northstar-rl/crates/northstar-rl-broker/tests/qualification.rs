use northstar_rl_broker::{
    MappedBrokerCapture, NorthstarWindTunnel, RawRetention, WindTunnelWorld, joint_fixture,
    qualify_joint, seal_broker_capture,
};
use northstar_rl_core::{Environment, QualificationStatus, WindTunnelMode};

#[test]
fn joint_fixture_is_logically_identical_across_independent_builds() {
    let first = joint_fixture().unwrap();
    let second = joint_fixture().unwrap();
    assert_eq!(first, second);
    assert_eq!(
        first.source_class,
        "SYNTHETIC_CONTRACT_FIXTURE_NOT_LIVE_MARKET_EVIDENCE"
    );
    assert!(
        first
            .registry
            .instruments
            .iter()
            .all(|row| row.raw_metadata.retention == RawRetention::SyntheticFixture)
    );
}

#[test]
fn captured_bytes_are_the_offline_replay_authority() {
    let directory = tempfile::tempdir().unwrap();
    let fixture = joint_fixture().unwrap();
    let path = directory.path().join("capture.nsb1");
    let header = seal_broker_capture(&path, &fixture.tradelocker).unwrap();
    let first = MappedBrokerCapture::open(&path).unwrap();
    let second = MappedBrokerCapture::open(&path).unwrap();
    assert_eq!(header.capture_id, first.header().capture_id);
    assert_eq!(first.header(), second.header());
    assert_eq!(first.rows().len(), 4);
}

#[test]
fn wind_tunnel_abi_stages_then_advances_and_receipts() {
    let directory = tempfile::tempdir().unwrap();
    qualify_joint(directory.path(), None).unwrap();
    let environment = Environment::open(directory.path().join("environment_config.json")).unwrap();
    let mut world = NorthstarWindTunnel::new(WindTunnelMode::CrossSourceComparison, environment);
    let reset = world.reset(None, 42).unwrap();
    assert_eq!(world.observe().unwrap(), reset.observation);
    world.apply_action(0.5).unwrap();
    assert!(world.apply_action(0.25).is_err());
    let step = world.advance().unwrap();
    assert_eq!(step.step_id, world.receipt().unwrap().step_id);
}

#[test]
fn matrix_never_promotes_missing_live_connectivity() {
    let directory = tempfile::tempdir().unwrap();
    let output = qualify_joint(directory.path(), None).unwrap();
    let live = output
        .matrix
        .items
        .iter()
        .find(|item| item.name == "TRADELOCKER_CONNECTION")
        .unwrap();
    assert_eq!(live.status, QualificationStatus::Gap);
    let replay = output
        .matrix
        .items
        .iter()
        .find(|item| item.name == "TRADELOCKER_CAPTURE_REPLAY")
        .unwrap();
    assert_eq!(replay.status, QualificationStatus::Partial);
}
