use criterion::{BatchSize, Criterion, black_box, criterion_group, criterion_main};
use fas_frozen_capability_fabric_e4_population_v02::identity::{
    FreshnessIndex, choose_collision_free,
};
use fas_frozen_capability_fabric_e4_population_v02::schema::{ModelInputRow, SemanticQuartet};
use serde_json::to_writer;

fn collision_index_and_jsonl_serialization(c: &mut Criterion) {
    c.bench_function("synthetic_512_quartets_collision_and_jsonl", |b| {
        b.iter_batched(
            FreshnessIndex::default,
            |mut freshness| {
                let mut output = Vec::with_capacity(1 << 20);
                for ordinal in 0..512_u64 {
                    let semantic = SemanticQuartet {
                        schedule_ordinal: ordinal,
                        track_code: 0,
                        context_split: (ordinal % 2) as u8,
                        entity_split: ((ordinal / 2) % 2) as u8,
                        family_id: (ordinal % 8) as u8,
                        relation_id: (ordinal % 2) as u8,
                        state_id: (ordinal % 3) as u8,
                        context_pair_id: (ordinal % 16) as u8,
                        entity_pair_id: ((ordinal * 7) % 16) as u8,
                    };
                    let accepted =
                        choose_collision_free(&mut freshness, semantic, |counter, _, _| {
                            Ok(std::array::from_fn(|row| {
                                format!("synthetic:{ordinal}:{counter}:{row}")
                            }))
                        })
                        .expect("synthetic deterministic choices never exhaust");
                    for row in 0..8_u8 {
                        let item = ModelInputRow {
                            row_id: format!("{}:00:{row:02x}", accepted.quartet_id),
                            quartet_id: accepted.quartet_id.clone(),
                            variant_id: (row % 4).to_string(),
                            input_text: format!("synthetic-row:{ordinal}:{row}"),
                        };
                        output.clear();
                        to_writer(&mut output, &item).expect("serialize synthetic row");
                        output.push(b'\n');
                        black_box(&output);
                    }
                }
                black_box(freshness);
            },
            BatchSize::SmallInput,
        )
    });
}

criterion_group!(benches, collision_index_and_jsonl_serialization);
criterion_main!(benches);
