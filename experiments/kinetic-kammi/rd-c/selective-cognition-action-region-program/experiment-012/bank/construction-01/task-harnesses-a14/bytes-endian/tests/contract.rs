use e012_bytes_endian_harness::encode_wire_word;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let (value, expected): (u16, [u8; 2]) = match case.as_str() {
        "case-01" => (0x1234, [0x12, 0x34]),
        "case-02" => (0x1234, [0x34, 0x12]),
        "case-03" => (0x5a2c, [0x2c, 0x5a]),
        "case-04" => (0x5a2c, [0x5a, 0x2c]),
        _ => panic!("unknown sealed case"),
    };
    assert!(encode_wire_word(value).as_ref() == expected, "task contract failed");
}
