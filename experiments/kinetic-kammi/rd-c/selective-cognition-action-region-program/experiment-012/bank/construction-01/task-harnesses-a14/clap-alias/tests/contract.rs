use e012_clap_alias_harness::parse_color;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let (argv, expected): (&[&str], Option<bool>) = match case.as_str() {
        "case-01" => (&["demo", "--color"], Some(true)),
        "case-02" => (&["demo", "--colour"], Some(true)),
        "case-03" => (&["demo", "--no-color"], Some(false)),
        "case-04" => (&["demo", "--color", "--no-color"], Some(false)),
        _ => panic!("unknown sealed case"),
    };
    assert_eq!(parse_color(argv), expected, "task contract failed");
}
