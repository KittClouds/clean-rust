use bytes::Bytes;
use e012_bytes_prefix_harness::take_prefix;

#[test]
fn check_contract() {
    let case = std::env::var("E012_CASE").expect("E012_CASE is set by the sealed checker");
    let (input, count, expected): (&[u8], usize, &[u8]) = match case.as_str() {
        "case-01" => (b"abcdef", 3, b"abc"),
        "case-02" => (&[0, 1, 2, 3, 4], 2, &[0, 1]),
        "case-03" => (b"rgb", 1, b"r"),
        "case-04" => (b"1234567", 5, b"12345"),
        _ => panic!("unknown sealed case"),
    };
    assert!(take_prefix(Bytes::copy_from_slice(input), count).as_ref() == expected, "task contract failed");
}
