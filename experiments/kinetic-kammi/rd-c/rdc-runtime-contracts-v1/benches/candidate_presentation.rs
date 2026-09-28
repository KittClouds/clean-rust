use criterion::{BatchSize, BenchmarkId, Criterion, black_box, criterion_group, criterion_main};
use rdc_runtime_contracts_v1::{
    ActionCode, CandidateIdentity, SequencedCandidate, encode_candidate_presentation,
    order_by_producer_ordinal, validate_candidate_presentation,
};

fn candidates(count: usize) -> Vec<CandidateIdentity> {
    (0..count)
        .map(|index| {
            let mut patch_digest = [0; 32];
            patch_digest[..4].copy_from_slice(&(index as u32).to_le_bytes());
            patch_digest[4..8].copy_from_slice(&(!(index as u32)).to_le_bytes());
            CandidateIdentity {
                action: ActionCode(index as u16),
                patch_digest,
            }
        })
        .collect()
}

fn bench_candidate_presentation(criterion: &mut Criterion) {
    let mut group = criterion.benchmark_group("candidate_presentation_validate");
    for count in [4, 16, 64, 256] {
        let candidates = candidates(count);
        let receipt = encode_candidate_presentation([0xA5; 32], &candidates).unwrap();
        group.bench_with_input(BenchmarkId::from_parameter(count), &count, |bench, _| {
            bench.iter(|| {
                validate_candidate_presentation(
                    black_box(&receipt),
                    black_box([0xA5; 32]),
                    black_box(&candidates),
                )
                .unwrap()
            });
        });
    }
    group.finish();

    let mut order_group = criterion.benchmark_group("candidate_producer_order");
    for count in [4, 16, 64, 256] {
        let shuffled = (0..count)
            .rev()
            .map(|ordinal| SequencedCandidate {
                producer_ordinal: ordinal as u16,
                value: ordinal,
            })
            .collect::<Vec<_>>();
        order_group.bench_with_input(BenchmarkId::from_parameter(count), &count, |bench, _| {
            bench.iter_batched(
                || shuffled.clone(),
                |mut candidates| {
                    order_by_producer_ordinal(black_box(&mut candidates)).unwrap();
                },
                BatchSize::SmallInput,
            );
        });
    }
    order_group.finish();
}

criterion_group!(benches, bench_candidate_presentation);
criterion_main!(benches);
