use obs_open_03bp2::dependence::{automatic_hac_lag, bartlett_lrv};
use obs_open_03bp2::fixtures::qualify;
use obs_open_03bp2::model::{MIN_D_B_COMPLETE, MIN_D_B_OFFSET};

#[test]
fn support_gates_are_not_weakened() {
    assert_eq!(MIN_D_B_COMPLETE, 80);
    assert_eq!(MIN_D_B_OFFSET, 20);
}

#[test]
fn hac_contract_is_deterministic() {
    let x = [1.0, -1.0, 2.0, -2.0, 0.5, -0.5];
    let a = bartlett_lrv(&x, automatic_hac_lag(x.len())).unwrap();
    let b = bartlett_lrv(&x, automatic_hac_lag(x.len())).unwrap();
    assert_eq!(a.to_bits(), b.to_bits());
}

#[test]
fn permanent_inference_fixtures_pass() {
    let cases = qualify().unwrap();
    assert!(cases.len() >= 8);
    assert!(
        cases
            .iter()
            .all(|x| x.status == "PASS" && !x.establishes_real_d_b_assumption)
    );
}
