#[path = "support/harness.rs"] mod harness;

#[test]
fn hidden_rows() {
    let path = std::env::var_os("E013_HIDDEN_ADJUDICATOR").expect("core supplies separated fixture path");
    harness::check_rows(path.into());
}
