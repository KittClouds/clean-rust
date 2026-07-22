#[cfg(feature = "gold-harness")]
mod enabled {
    use std::alloc::{GlobalAlloc, Layout, System};
    use std::collections::BTreeSet;
    use std::hint::black_box;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::time::{Duration, Instant};

    use phoenix_revision_impact::gold_harness::{
        analyze_case, case_fixture, gold_fixtures, CaseFixture,
    };
    use phoenix_revision_impact::{
        execute_shadow_semantic_repair, generate_author_directed_repairs,
        generate_deterministic_repairs, simulate_repair_candidate, AuthorDirectiveGenerationInput,
        AuthorRepairDirectiveCorpus, ProposedEdit, RepairDisposition, RepairGenerationInput,
        RepairSimulationInput, RevisionImpactReport, RippleConfig,
    };
    use phoenix_types::StoryMutation;

    const SAMPLES: usize = 7;

    pub struct TrackingAllocator;

    static CURRENT_BYTES: AtomicUsize = AtomicUsize::new(0);
    static PEAK_BYTES: AtomicUsize = AtomicUsize::new(0);
    static ALLOCATION_CALLS: AtomicUsize = AtomicUsize::new(0);

    unsafe impl GlobalAlloc for TrackingAllocator {
        unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
            let pointer = unsafe { System.alloc(layout) };
            if !pointer.is_null() {
                record_allocation(layout.size());
            }
            pointer
        }

        unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
            let pointer = unsafe { System.alloc_zeroed(layout) };
            if !pointer.is_null() {
                record_allocation(layout.size());
            }
            pointer
        }

        unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
            CURRENT_BYTES.fetch_sub(layout.size(), Ordering::Relaxed);
            unsafe { System.dealloc(pointer, layout) };
        }

        unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
            let resized = unsafe { System.realloc(pointer, layout, size) };
            if !resized.is_null() {
                ALLOCATION_CALLS.fetch_add(1, Ordering::Relaxed);
                if size >= layout.size() {
                    increase_current(size - layout.size());
                } else {
                    CURRENT_BYTES.fetch_sub(layout.size() - size, Ordering::Relaxed);
                }
            }
            resized
        }
    }

    struct Scenario {
        fixture: CaseFixture,
        report: RevisionImpactReport,
        mutations: Vec<StoryMutation>,
        candidates: Vec<ProposedEdit>,
    }

    #[derive(Clone, Copy)]
    struct Sample {
        elapsed: Duration,
        allocation_calls: usize,
        peak_additional_bytes: usize,
        validations: usize,
    }

    pub fn run() {
        let scenarios = scenarios();
        let mut samples = Vec::with_capacity(SAMPLES);
        for _ in 0..SAMPLES {
            let baseline_bytes = CURRENT_BYTES.load(Ordering::Relaxed);
            PEAK_BYTES.store(baseline_bytes, Ordering::Relaxed);
            let baseline_calls = ALLOCATION_CALLS.load(Ordering::Relaxed);
            let started = Instant::now();
            let mut validations = 0;
            for scenario in &scenarios {
                for edit in &scenario.candidates {
                    let candidate = simulate_repair_candidate(
                        RepairSimulationInput {
                            base: &scenario.fixture.base,
                            mutations: &scenario.mutations,
                            requirements: &scenario.fixture.requirements,
                            temporal: Some(&scenario.fixture.temporal),
                            memory: Some(&scenario.fixture.memory),
                            causal: Some(&scenario.fixture.causal),
                            original_report: &scenario.report,
                            author_locked_ids: &BTreeSet::new(),
                            ripple_config: RippleConfig::default(),
                        },
                        edit,
                    )
                    .expect("repair benchmark simulation");
                    assert!(candidate.validation_receipt.full_revalidation_completed);
                    black_box(candidate);
                    validations += 1;
                }
            }
            samples.push(Sample {
                elapsed: started.elapsed(),
                allocation_calls: ALLOCATION_CALLS
                    .load(Ordering::Relaxed)
                    .saturating_sub(baseline_calls),
                peak_additional_bytes: PEAK_BYTES
                    .load(Ordering::Relaxed)
                    .saturating_sub(baseline_bytes),
                validations,
            });
        }
        samples.sort_unstable_by_key(|sample| sample.elapsed);
        let median = samples[SAMPLES / 2];
        println!("gold_cases={}", scenarios.len());
        println!("candidates_per_sample={}", median.validations);
        println!("samples_ms={}", format_samples(&samples));
        println!("median_ms={:.3}", median.elapsed.as_secs_f64() * 1_000.0);
        println!(
            "median_micros_per_candidate={:.3}",
            median.elapsed.as_micros() as f64 / median.validations as f64
        );
        println!("allocation_calls={}", median.allocation_calls);
        println!(
            "peak_additional_kib={:.3}",
            median.peak_additional_bytes as f64 / 1024.0
        );
        measure_shadow_semantic();
    }

    fn measure_shadow_semantic() {
        let (gold, projection) = gold_fixtures();
        let directives: AuthorRepairDirectiveCorpus = serde_json::from_str(include_str!(
            "../../fixtures/revision-repair-author-directives-v1.json"
        ))
        .expect("author directive fixture");
        for case_index in 0..7 {
            let gold_case = &gold.cases[case_index];
            let projection_case = &projection.cases[case_index];
            assert_eq!(projection_case.case_id, gold_case.case_id.0);
            let fixture = case_fixture(gold_case, projection_case);
            let report = analyze_case(gold_case, projection_case).report;
            let mutations = vec![fixture.mutation.clone()];
            let edit = generate_author_directed_repairs(AuthorDirectiveGenerationInput {
                report: &report,
                directives: std::slice::from_ref(&directives.cases[case_index]),
                author_locked_ids: &BTreeSet::new(),
            })
            .candidates
            .remove(0);
            let mut samples = Vec::with_capacity(SAMPLES);
            for _ in 0..SAMPLES {
                let baseline_bytes = CURRENT_BYTES.load(Ordering::Relaxed);
                PEAK_BYTES.store(baseline_bytes, Ordering::Relaxed);
                let baseline_calls = ALLOCATION_CALLS.load(Ordering::Relaxed);
                let started = Instant::now();
                let result = execute_shadow_semantic_repair(
                    RepairSimulationInput {
                        base: &fixture.base,
                        mutations: &mutations,
                        requirements: &fixture.requirements,
                        temporal: Some(&fixture.temporal),
                        memory: Some(&fixture.memory),
                        causal: Some(&fixture.causal),
                        original_report: &report,
                        author_locked_ids: &BTreeSet::new(),
                        ripple_config: RippleConfig::default(),
                    },
                    &edit,
                )
                .expect("shadow semantic benchmark");
                assert_eq!(result.candidate.disposition, RepairDisposition::ProvenFix);
                black_box(result);
                samples.push(Sample {
                    elapsed: started.elapsed(),
                    allocation_calls: ALLOCATION_CALLS
                        .load(Ordering::Relaxed)
                        .saturating_sub(baseline_calls),
                    peak_additional_bytes: PEAK_BYTES
                        .load(Ordering::Relaxed)
                        .saturating_sub(baseline_bytes),
                    validations: 1,
                });
            }
            samples.sort_unstable_by_key(|sample| sample.elapsed);
            let median = samples[SAMPLES / 2];
            let label = gold_case
                .case_id
                .0
                .strip_prefix("gold:")
                .unwrap_or("shadow");
            println!("shadow_{label}_samples_ms={}", format_samples(&samples));
            println!(
                "shadow_{label}_median_ms={:.3}",
                median.elapsed.as_secs_f64() * 1_000.0
            );
            println!(
                "shadow_{label}_allocation_calls={}",
                median.allocation_calls
            );
            println!(
                "shadow_{label}_peak_additional_kib={:.3}",
                median.peak_additional_bytes as f64 / 1024.0
            );
        }
    }

    fn scenarios() -> Vec<Scenario> {
        let (gold, projection) = gold_fixtures();
        gold.cases
            .iter()
            .map(|gold_case| {
                let projection_case = projection
                    .cases
                    .iter()
                    .find(|case| case.case_id == gold_case.case_id.0)
                    .expect("projection case");
                let fixture = case_fixture(gold_case, projection_case);
                let report = analyze_case(gold_case, projection_case).report;
                let mutations = vec![fixture.mutation.clone()];
                let candidates = generate_deterministic_repairs(RepairGenerationInput {
                    base: &fixture.base,
                    mutations: &mutations,
                    requirements: &fixture.requirements,
                    report: &report,
                    author_locked_ids: &BTreeSet::new(),
                })
                .candidates;
                Scenario {
                    fixture,
                    report,
                    mutations,
                    candidates,
                }
            })
            .collect()
    }

    fn record_allocation(bytes: usize) {
        ALLOCATION_CALLS.fetch_add(1, Ordering::Relaxed);
        increase_current(bytes);
    }

    fn increase_current(bytes: usize) {
        let current = CURRENT_BYTES.fetch_add(bytes, Ordering::Relaxed) + bytes;
        let mut peak = PEAK_BYTES.load(Ordering::Relaxed);
        while current > peak {
            match PEAK_BYTES.compare_exchange_weak(
                peak,
                current,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(actual) => peak = actual,
            }
        }
    }

    fn format_samples(samples: &[Sample]) -> String {
        samples
            .iter()
            .map(|sample| format!("{:.3}", sample.elapsed.as_secs_f64() * 1_000.0))
            .collect::<Vec<_>>()
            .join(",")
    }
}

#[cfg(feature = "gold-harness")]
#[global_allocator]
static ALLOCATOR: enabled::TrackingAllocator = enabled::TrackingAllocator;

#[cfg(feature = "gold-harness")]
fn main() {
    enabled::run();
}

#[cfg(not(feature = "gold-harness"))]
fn main() {
    eprintln!("revision_repair_perf requires --features gold-harness");
}
