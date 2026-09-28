use clap::ColorChoice;
use e012_clap_color_harness::configured_color;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let expected = match case.as_str() {
        "case-01" | "case-03" => ColorChoice::Always,
        "case-02" | "case-04" => ColorChoice::Never,
        _ => panic!("unknown sealed case"),
    };
    assert!(configured_color() == expected, "task contract failed");
}
