use e012_bytes_composite_harness::read_selected_field;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let (input, expected): (&[u8], u16) = match case.as_str() {
        "case-01" => (&[0x12, 0x34, 0x56, 0x78], 0x1234),
        "case-02" => (&[0x12, 0x34, 0x56, 0x78], 0x3412),
        "case-03" => (&[0x12, 0x34, 0x56, 0x78], 0x5678),
        "case-04" => (&[0x12, 0x34, 0x56, 0x78], 0x7856),
        _ => panic!("unknown sealed case"),
    };
    assert_eq!(read_selected_field(input), expected, "selected frame field mismatch");
}
