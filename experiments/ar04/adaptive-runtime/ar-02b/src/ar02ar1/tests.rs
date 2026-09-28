use super::*;

#[test]
fn bayes_margin_bins_are_balanced_by_class_and_fixed_before_training() {
    let data = generate_gaussian_cells();
    let train = &data.samples[..TRAIN_SAMPLES];
    let margins = build_margin_strata(train);
    let mut counts = [0_usize; MARGIN_STRATA];
    for &stratum in &margins.ids {
        counts[stratum as usize] += 1;
    }
    assert_eq!(counts, [8; MARGIN_STRATA]);
    assert!(margins.margins.iter().all(|margin| margin.is_finite()));
}

#[test]
fn rotating_population_stratifiers_keep_exact_sample_size_and_weights() {
    let data = generate_gaussian_cells();
    let train = &data.samples[..TRAIN_SAMPLES];
    let class_index = StrataIndex::new(
        &std::array::from_fn(|index| train[index].target as u8),
        CLASSES,
    );
    let mut cell_ids = [0_u8; TRAIN_SAMPLES];
    for (index, cell) in cell_ids.iter_mut().enumerate() {
        *cell = (index / TRAIN_PER_CELL) as u8;
    }
    let cell_index = StrataIndex::new(&cell_ids, CELLS);
    let margins = build_margin_strata(train);
    let margin_index = StrataIndex::new(&margins.ids, MARGIN_STRATA);
    for kind in [VerifierKind::CellWeighted, VerifierKind::MarginWeighted] {
        for round in 0..3 {
            let batch = make_verifier(
                train,
                kind,
                16,
                R1_SEEDS[0],
                round,
                &class_index,
                &cell_index,
                &margin_index,
            );
            assert_eq!(batch.len, 16);
            let mut counts = [0_usize; CELLS];
            for &stratum in &batch.strata[..batch.len] {
                counts[stratum as usize] += 1;
            }
            assert_eq!(counts.iter().filter(|&&count| count == 2).count(), 4);
            assert_eq!(counts.iter().filter(|&&count| count == 1).count(), 8);
        }
    }
    let mut extra_class_seen = [false; CLASSES];
    for round in 0..CLASSES {
        let class_batch = make_verifier(
            train,
            VerifierKind::ClassWeighted,
            16,
            R1_SEEDS[0],
            round,
            &class_index,
            &cell_index,
            &margin_index,
        );
        assert_eq!(
            class_batch.loss(&Model::initial()),
            weighted_group_mean(&class_batch, &Model::initial(), CLASSES)
        );
        let counts = batch_group_counts(&class_batch, CLASSES);
        let extra = counts
            .iter()
            .position(|&count| count == 6)
            .expect("one class receives the rotating extra observation");
        extra_class_seen[extra] = true;
    }
    assert!(extra_class_seen.into_iter().all(|seen| seen));
    let cell_batch = make_verifier(
        train,
        VerifierKind::CellWeighted,
        48,
        R1_SEEDS[0],
        0,
        &class_index,
        &cell_index,
        &margin_index,
    );
    assert_eq!(cell_batch.len, 48);
    assert_eq!(batch_group_counts(&cell_batch, CELLS), [4; CELLS]);
}

#[test]
fn p16_v16_random_selection_matches_frozen_k2_at_initial_state() {
    let data = generate_gaussian_cells();
    let train = &data.samples[..TRAIN_SAMPLES];
    let seed = R1_SEEDS[0];
    let proposal_ids = batch_indices(seed, 0, PROPOSAL_STREAM);
    let proposal = indexed_samples(train, &proposal_ids);
    let class_index = StrataIndex::new(
        &std::array::from_fn(|index| train[index].target as u8),
        CLASSES,
    );
    let mut cell_ids = [0_u8; TRAIN_SAMPLES];
    for (index, cell) in cell_ids.iter_mut().enumerate() {
        *cell = (index / TRAIN_PER_CELL) as u8;
    }
    let cell_index = StrataIndex::new(&cell_ids, CELLS);
    let margins = build_margin_strata(train);
    let margin_index = StrataIndex::new(&margins.ids, MARGIN_STRATA);
    let verifier = make_verifier(
        train,
        VerifierKind::Random,
        16,
        seed,
        0,
        &class_index,
        &cell_index,
        &margin_index,
    );
    let group = Group {
        left: 0,
        right: 1,
        len: 2,
    };
    let baseline = Model::initial();
    let proposal_base = baseline.loss(&proposal);
    let verify_base = verifier.loss(&baseline);
    let expected = best_runtime_program(
        &baseline,
        &proposal,
        &[&verifier.samples[..16]],
        Arm::G2Balanced64,
        group,
    )
    .0;
    let observed = select_group(
        &baseline,
        &proposal,
        proposal_base,
        &verifier,
        verify_base,
        group,
    )
    .0;
    assert_eq!(
        expected.map(|program| (program.left, program.right, program.deltas)),
        observed.map(|program| (program.left, program.right, program.deltas))
    );
    assert!((expected.unwrap().utility - observed.unwrap().utility).abs() < 1e-7);
}

#[test]
fn short_r1_run_records_sparse_full_reference_regret() {
    let data = generate_gaussian_cells();
    let result = run_r1_method_for_commits(&data.samples, R1_METHODS[0], R1_SEEDS[0], 4);
    assert_eq!(result.optimizer_steps, 4);
    assert_eq!(result.proposal_evaluations, (PARAMS * 7 * 4) as u64);
    assert_eq!(result.regret_audits, 1);
    assert!(result.full_reference_candidate_evaluations > 0);
    assert!(result.compound_evaluations > 0);
}

fn weighted_group_mean(batch: &VerifierBatch, model: &Model, group_count: usize) -> f32 {
    let mut sums = [0.0_f32; CELLS];
    let mut counts = [0_u16; CELLS];
    for (index, &sample) in batch.samples[..batch.len].iter().enumerate() {
        let group = match batch.kind {
            VerifierKind::ClassWeighted => sample.target as usize,
            _ => batch.strata[index] as usize,
        };
        sums[group] += sample_loss(model, sample);
        counts[group] += 1;
    }
    equal_stratum_mean(&sums, &counts, group_count)
}

#[test]
fn unequal_quotas_do_not_change_equal_population_weights() {
    let sums = [100.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0];
    let counts = [2, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0];
    let corrected = equal_stratum_mean(&sums, &counts, 4);
    assert_eq!(corrected, 13.25);
    let raw_sample_mean = sums[..4].iter().sum::<f32>()
        / counts[..4]
            .iter()
            .map(|&count| f32::from(count))
            .sum::<f32>();
    assert_eq!(raw_sample_mean, 20.6);
}

fn batch_group_counts(batch: &VerifierBatch, groups: usize) -> [usize; CELLS] {
    let mut counts = [0; CELLS];
    for &stratum in &batch.strata[..batch.len] {
        counts[stratum as usize] += 1;
    }
    assert!(groups <= CELLS);
    counts
}
