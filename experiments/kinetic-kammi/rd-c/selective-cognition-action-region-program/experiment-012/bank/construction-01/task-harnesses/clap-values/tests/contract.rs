use e012_clap_values_harness::accepts_speed;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let (value, expected) = match case.as_str() {
        "case-01" => ("fast", true),
        "case-02" => ("safe", true),
        "case-03" => ("auto", false),
        "case-04" => ("quick", false),
        _ => panic!("unknown sealed case"),
    };
    assert!(accepts_speed(value) == expected, "task contract failed");
}
