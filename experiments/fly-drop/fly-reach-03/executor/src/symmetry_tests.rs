use super::*;

#[test]
fn row_key_is_exactly_eighteen_little_endian_bytes() {
    let key = RowKey {
        substrate: 8,
        side: 1,
        block: 0x0102030405060708,
        trial: 0x11223344,
        coordinate: 0xaabbccdd,
    };
    assert_eq!(&key.bytes()[2..10], &0x0102030405060708_u64.to_le_bytes());
    assert_eq!(&key.bytes()[10..14], &0x11223344_u32.to_le_bytes());
    assert_eq!(&key.bytes()[14..18], &0xaabbccdd_u32.to_le_bytes());
    assert_eq!(key.bytes().len(), 18);
}

#[test]
fn cue_permutation_enumerates_s4_once() {
    let permutations = fixture_impl::all_permutations();
    let set: std::collections::HashSet<_> = permutations.iter().copied().collect();
    assert_eq!(permutations.len(), 24);
    assert_eq!(set.len(), 24);
}

#[test]
fn signed_zero_is_canonicalized_in_tuple_bytes() {
    let base = RelTuple {
        incidence: 0,
        role: 1,
        incidence_role: 0,
        delta: 0.0,
        incidence_delta: 0.0,
        role_delta: 0.0,
    };
    assert_eq!(&tuple_bytes(base)[3..7], &0.0_f32.to_bits().to_le_bytes());
}
