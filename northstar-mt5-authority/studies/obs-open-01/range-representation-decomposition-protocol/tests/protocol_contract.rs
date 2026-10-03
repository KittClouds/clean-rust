use obs_open_03b2p::algebra::Arm;
use obs_open_03b2p::contracts;

#[test]
fn exactly_two_primary_wagers_are_frozen() {
    let contract = contracts::wagers();
    assert_eq!(contract["wagers"].as_array().unwrap().len(), 2);
    assert_eq!(
        contract["wagers"][0]["wager_id"],
        "WIDTH_INFORMATION_INCREMENT"
    );
    assert_eq!(
        contract["wagers"][1]["wager_id"],
        "QUOTIENT_ACCESSIBILITY_INCREMENT"
    );
}

#[test]
fn representation_dimensions_are_explicit() {
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

#[test]
fn fresh_population_is_pending_and_dc_is_unopened() {
    let population = contracts::population_contract();
    let freshness = contracts::freshness_ledger();
    assert_eq!(population["state"], "FRESH_CONFIRMATION_POPULATION_PENDING");
    assert_eq!(population["execution_authorized_now"], false);
    assert_eq!(freshness["D_C"]["state"], "FROZEN_UNOPENED");
    assert_eq!(freshness["D_C"]["observations_read"], 0);
    assert_eq!(freshness["D_D"]["membership_materialized"], 0);
}

#[test]
fn fresh_clock_does_not_inherit_db_clock() {
    let temporal = contracts::temporal_contract();
    assert_eq!(temporal["lag_unit"], "ELIGIBLE_PROSPECTIVE_SESSION_ORDINAL");
    assert_eq!(
        temporal["inherits_P2T_selected_DB_ordinal_semantics"],
        false
    );
}
