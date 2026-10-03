use obs_open_disc02e::{
    CONFIRMATION_SESSIONS, DISC02P_ROOT, DISCOVERY_PREFIX_ROWS, DISCOVERY_SESSIONS, MEAS02_ROOT,
};
use obs_open_disc02p::{minimum_attainable_p, resolution_pass};

#[test]
fn frozen_authorities_and_population_are_exact() {
    assert_eq!(DISCOVERY_SESSIONS, 257);
    assert_eq!(CONFIRMATION_SESSIONS, 69);
    assert_eq!(DISCOVERY_PREFIX_ROWS, 633_322);
    assert_eq!(DISC02P_ROOT.len(), 64);
    assert_eq!(MEAS02_ROOT.len(), 64);
}

#[test]
fn numerical_resolution_has_frozen_headroom() {
    assert_eq!(minimum_attainable_p(9_999), 0.0001);
    assert!(resolution_pass(9_999, 0.05, 3, 10));
}

#[test]
fn packed_records_have_stable_compact_sizes() {
    assert_eq!(
        std::mem::size_of::<obs_open_disc02e::corpus::PackedCandidatePath>(),
        48
    );
    assert_eq!(
        std::mem::size_of::<obs_open_disc02e::corpus::PackedRangeSurface>(),
        80
    );
}
