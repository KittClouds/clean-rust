use e012_serde_numeric_joint_harness::selected_numeric;
use serde_json::json;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let expected = match case.as_str() {
        "case-01" => json!(11),
        "case-02" => json!(12),
        "case-03" => json!(21),
        "case-04" => json!(22),
        _ => panic!("unknown sealed case"),
    };
    let input = r#"{"header":{"whole":11,"ratio":12},"payload":{"whole":21,"ratio":22}}"#;
    assert_eq!(selected_numeric(input), Some(expected), "selected numeric field mismatch");
}
