use galaxy_wgpu_lod_kernel::MortonRadixScratch;

#[test]
fn radix_order_exactly_matches_comparison_sort() {
    let mut state = 0xd1b5_4a32_d192_ed03u64;
    let keys = (0..131_071)
        .map(|node| {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            if node % 19 == 0 { state & !0xff } else { state }
        })
        .collect::<Vec<_>>();
    let mut expected = (0..keys.len() as u32).collect::<Vec<_>>();
    expected.sort_unstable_by_key(|node| (keys[*node as usize], *node));

    let mut scratch = MortonRadixScratch::new();
    assert_eq!(scratch.sort(&keys).unwrap(), expected);
}

#[test]
fn radix_workspace_reuses_capacity_and_preserves_duplicate_tie_order() {
    let mut scratch = MortonRadixScratch::new();
    assert_eq!(scratch.sort(&[9, 1, 9, 1, 9]).unwrap(), [1, 3, 0, 2, 4]);
    let resident_bytes = scratch.resident_bytes();
    assert_eq!(scratch.sort(&[3, 2, 1]).unwrap(), [2, 1, 0]);
    assert_eq!(scratch.resident_bytes(), resident_bytes);
}
