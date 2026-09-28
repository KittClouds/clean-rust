use e012_serde_map_order_harness::display_keys;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let (input, expected): (&str, &[&str]) = match case.as_str() {
        "case-01" => (r#"{"z":1,"a":2}"#, &["a", "z"]),
        "case-02" => (r#"{"z":1,"a":2}"#, &["z", "a"]),
        "case-03" => (r#"{"c":1,"a":2,"b":3}"#, &["a", "b", "c"]),
        "case-04" => (r#"{"c":1,"a":2,"b":3}"#, &["c", "a", "b"]),
        _ => panic!("unknown sealed case"),
    };
    let actual = display_keys(input).expect("valid map input");
    assert!(actual.iter().map(String::as_str).eq(expected.iter().copied()), "task contract failed");
}
