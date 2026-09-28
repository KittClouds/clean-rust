use e012_clap_repeat_harness::parse_tag_values;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let (argv, expected): (&[&str], &[&str]) = match case.as_str() {
        "case-01" => (&["demo", "--tag", "red", "--tag", "blue"], &["red", "blue"]),
        "case-02" => (&["demo", "--tag", "red", "--tag", "blue"], &["blue"]),
        "case-03" => (&["demo", "--tag", "green", "--tag", "amber", "--tag", "violet"], &["green", "amber", "violet"]),
        "case-04" => (&["demo", "--tag", "green", "--tag", "amber", "--tag", "violet"], &["violet"]),
        _ => panic!("unknown sealed case"),
    };
    let actual = parse_tag_values(argv);
    assert!(actual.iter().map(String::as_str).eq(expected.iter().copied()), "task contract failed");
}
