#[path = "support/harness.rs"] mod harness;

#[test]
fn visible_rows() {
    let path = std::env::var_os("E013_VISIBLE_ROOT").expect("core supplies separated fixture path");
    harness::check_rows(path.into());
}
