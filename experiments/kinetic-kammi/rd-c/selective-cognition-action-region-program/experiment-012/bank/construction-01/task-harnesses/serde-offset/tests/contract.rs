use e012_serde_offset_harness::first_item_offset;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let expected = match case.as_str() {
        "case-01" => 8,
        "case-02" => 9,
        "case-03" => 7,
        "case-04" => 0,
        _ => panic!("unknown sealed case"),
    };
    assert!(first_item_offset("{\"x\":42}") == expected, "task contract failed");
}
