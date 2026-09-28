use e012_serde_raw_number_harness::normalize_json_number;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let input = match case.as_str() {
        "case-01" => r#"{"n":1.2300,"tag":"x"}"#,
        "case-02" => r#"{"n":9007199254740993,"tag":"x"}"#,
        "case-03" => r#"{"n":1e+02,"tag":"x"}"#,
        "case-04" => r#"{"n":18446744073709551617,"tag":"x"}"#,
        _ => panic!("unknown sealed case"),
    };
    assert_eq!(normalize_json_number(input).as_deref(), Some(input), "lossless-number contract failed");
}
