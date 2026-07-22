use super::tests::{fixture_packet, normalize_row};
use super::*;

#[test]
fn runtime_kernel_matches_the_typescript_neighborhood_golden() {
    let rows = 240;
    let dimensions = 8;
    let mut target_ids = (0..rows)
        .map(|row| format!("embed:chunk:note-scale:block:{row}"))
        .collect::<Vec<_>>();
    target_ids.sort();
    let mut lexical_order = (0..rows).collect::<Vec<_>>();
    lexical_order.sort_by(|left, right| target_ids[*left].cmp(&target_ids[*right]));
    let mut lexical_ranks = vec![0_u32; rows];
    for (rank, row) in lexical_order.into_iter().enumerate() {
        lexical_ranks[row] = rank as u32;
    }
    let mut bytes = fixture_packet(rows, dimensions, 4, 12);
    let hashes_offset = REQUEST_HEADER_BYTES;
    let ranks_offset = hashes_offset + rows * 4;
    let vectors_offset = ranks_offset + rows * 4;
    for row in 0..rows {
        write_u32(
            &mut bytes,
            hashes_offset + row * 4,
            hash_text(&target_ids[row]),
        );
        write_u32(&mut bytes, ranks_offset + row * 4, lexical_ranks[row]);
        let mut vector = [0_f32; 8];
        vector[0] = 1.0;
        vector[1] = (row % 3) as f32 * 0.05;
        vector[2] = ((row + 1) % 3) as f32 * 0.025;
        normalize_row(&mut vector);
        for (dimension, value) in vector.iter().enumerate() {
            let offset = vectors_offset + (row * dimensions + dimension) * 4;
            bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
    }
    let output = build_index(PackedIndexRequest::parse(&bytes).unwrap()).unwrap();
    assert_eq!(
        neighborhood_hash(&target_ids, &output.neighborhoods),
        0x64db_fb68
    );
}

fn neighborhood_hash(target_ids: &[String], rows: &[Vec<(u32, i32)>]) -> u32 {
    let mut hash = 0x811c_9dc5;
    for (source, neighbors) in rows.iter().enumerate() {
        hash = fnv_word(hash, hash_text(&target_ids[source]));
        for (rank, &(target, micro_score)) in neighbors.iter().enumerate() {
            hash = fnv_word(hash, hash_text(&target_ids[target as usize]));
            hash = fnv_word(
                hash,
                hash_text(&format!("{}:{}", rank + 1, score_text(micro_score))),
            );
        }
    }
    hash
}

fn score_text(micro_score: i32) -> String {
    if micro_score % 1_000_000 == 0 {
        return (micro_score / 1_000_000).to_string();
    }
    let mut text = format!("{:.6}", micro_score as f64 / 1_000_000.0);
    while text.ends_with('0') {
        text.pop();
    }
    text
}

fn hash_text(value: &str) -> u32 {
    let mut hash = 0x811c_9dc5_u32;
    for code_unit in value.encode_utf16() {
        hash ^= code_unit as u32;
        hash = hash.wrapping_mul(0x0100_0193);
    }
    hash
}

fn fnv_word(mut hash: u32, word: u32) -> u32 {
    for byte in word.to_le_bytes() {
        hash ^= byte as u32;
        hash = hash.wrapping_mul(0x0100_0193);
    }
    hash
}
