use e012_bytes_cursor_harness::byte_at_task_cursor;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let (input, expected): (&[u8], u8) = match case.as_str() {
        "case-01" => (&[0xa0, 0x11, 0x22], 0x11),
        "case-02" => (&[0xa0, 0x11, 0x22], 0x22),
        "case-03" => (&[0xc0, 0x33, 0x44, 0x55], 0x44),
        "case-04" => (&[0xc0, 0x33, 0x44, 0x55], 0x55),
        _ => panic!("unknown sealed case"),
    };
    assert_eq!(byte_at_task_cursor(input), expected, "cursor observation mismatch");
}
