use e012_clap_color_harness::rendered_help;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let want_color = match case.as_str() {
        "case-01" | "case-03" => true,
        "case-02" | "case-04" => false,
        _ => panic!("unknown sealed case"),
    };
    let has_ansi = rendered_help().contains('\u{1b}');
    assert!(has_ansi == want_color, "task contract failed");
}
