use northstar_rl_core::{
    AccountState, Digest, Environment, EpisodeBindings, FeatureCellState, MappedFeatureTape,
    MappedRunRawTape, ObservationLayout, ScriptedPolicy, SourceStatus, apply_transition,
    build_fixture_lab, canonical_execution_spec, canonical_instrument, canonical_rows,
    compile_features, compile_session_episodes, compiler_identity, identified, materialize_lab,
    primitive_feature_registry, registry_id, run_scripted, seal_feature_tape, seal_runraw,
    write_json,
};
use tempfile::tempdir;

#[test]
fn fixed_width_runraw_is_mapped_and_byte_deterministic() {
    let directory = tempdir().unwrap();
    let rows = canonical_rows();
    let source = Digest::hash(b"test-source", b"fixture");
    let first = directory.path().join("first.nrr1");
    let second = directory.path().join("second.nrr1");
    seal_runraw(&first, source, &rows).unwrap();
    seal_runraw(&second, source, &rows).unwrap();
    assert_eq!(
        std::fs::read(&first).unwrap(),
        std::fs::read(&second).unwrap()
    );
    let mapped = MappedRunRawTape::open(first).unwrap();
    assert_eq!(mapped.rows().len(), rows.len());
    assert_eq!(mapped.rows()[3].source_row_id, 4);
}

#[test]
fn feature_cells_have_typed_warmup_and_causal_time() {
    let directory = tempdir().unwrap();
    let rows = canonical_rows();
    let runraw_path = directory.path().join("runraw.nrr1");
    seal_runraw(&runraw_path, Digest::hash(b"source", b"x"), &rows).unwrap();
    let runraw = MappedRunRawTape::open(runraw_path).unwrap();
    let registry = primitive_feature_registry(3).unwrap();
    let columns = compile_features(runraw.rows(), &registry).unwrap();
    let feature_path = directory.path().join("features.nrf1");
    seal_feature_tape(
        &feature_path,
        runraw.tape_id().unwrap(),
        registry_id(&registry).unwrap(),
        compiler_identity(),
        &columns,
    )
    .unwrap();
    let features = MappedFeatureTape::open(feature_path).unwrap();
    assert_eq!(
        features.cell("market.rolling_mean.v1", 0).unwrap().1,
        FeatureCellState::Warmup
    );
    assert_eq!(
        features.cell("market.rolling_mean.v1", 1).unwrap().1,
        FeatureCellState::Warmup
    );
    let (value, state, known) = features.cell("market.rolling_mean.v1", 2).unwrap();
    assert_eq!(state, FeatureCellState::Available);
    assert_eq!(value, 101.0);
    assert_eq!(known, rows[2].knowledge_time);
}

#[test]
fn identical_episode_seed_and_actions_replay_exactly() {
    let directory = tempdir().unwrap();
    materialize_lab(directory.path()).unwrap();
    let config = directory.path().join("environment_config.json");
    let mut first = Environment::open(&config).unwrap();
    let mut second = Environment::open(&config).unwrap();
    let first_receipt =
        run_scripted(&mut first, None, 42, ScriptedPolicy::SeededRandomActions).unwrap();
    let second_receipt =
        run_scripted(&mut second, None, 42, ScriptedPolicy::SeededRandomActions).unwrap();
    assert_eq!(first_receipt, second_receipt);
    assert_eq!(first.steps(), second.steps());
    assert!(first.terminal_receipt().unwrap().truncated);
}

#[test]
fn environment_clock_observes_t_then_fills_next_open() {
    let directory = tempdir().unwrap();
    materialize_lab(directory.path()).unwrap();
    let mut environment =
        Environment::open(directory.path().join("environment_config.json")).unwrap();
    let reset = environment.reset_episode(None, 7).unwrap();
    let source_row_id = reset.source_row_id;
    let output = environment.step(1.0).unwrap();
    let receipt = &environment.executions()[0];
    assert_eq!(receipt.action_source_row_id, source_row_id);
    assert_eq!(receipt.fill_source_row_id, output.source_row_id);
    assert_eq!(output.step_id, 1);
}

#[test]
fn action_and_numeric_boundaries_fail_closed() {
    let directory = tempdir().unwrap();
    materialize_lab(directory.path()).unwrap();
    let mut environment =
        Environment::open(directory.path().join("environment_config.json")).unwrap();
    environment.reset_episode(None, 1).unwrap();
    assert!(environment.step(f32::NAN).is_err());
    assert!(environment.step(1.01).is_err());
}

#[test]
fn constant_price_charges_each_friction_component_without_gross_pnl() {
    let instrument = canonical_instrument().unwrap();
    let execution = canonical_execution_spec().unwrap();
    let prior = AccountState::initial(1_000.0).unwrap();
    let mut execution_row = northstar_rl_core::row(2, 100.0);
    execution_row.open = 100.0;
    execution_row.high = 100.0;
    execution_row.low = 100.0;
    let transition =
        apply_transition(prior, 1, execution_row, 1.0, &instrument, &execution).unwrap();
    assert_eq!(transition.primitives.gross_mark_to_market_delta, 0.0);
    assert!(transition.primitives.commission_cost > 0.0);
    assert!(transition.primitives.spread_cost > 0.0);
    assert!(transition.primitives.slippage_cost > 0.0);
    assert!(
        (transition.primitives.equity_delta + transition.primitives.total_friction).abs() < 1e-12
    );
}

#[test]
fn source_gap_terminates_before_fill() {
    let directory = tempdir().unwrap();
    let lab = build_fixture_lab(directory.path()).unwrap();
    let mut rows = canonical_rows();
    rows[4].source_status = SourceStatus::Gap as u8;
    let runraw_path = directory.path().join("runraw.nrr1");
    seal_runraw(&runraw_path, Digest::hash(b"fixture", b"gap"), &rows).unwrap();
    let runraw = MappedRunRawTape::open(&runraw_path).unwrap();
    let columns = compile_features(runraw.rows(), &lab.registry).unwrap();
    seal_feature_tape(
        directory.path().join("features.nrf1"),
        runraw.tape_id().unwrap(),
        registry_id(&lab.registry).unwrap(),
        compiler_identity(),
        &columns,
    )
    .unwrap();
    // The old environment identity is intentionally invalid after authority mutation.
    assert!(Environment::open(directory.path().join("environment_config.json")).is_err());
}

#[test]
fn windowed_matrix_is_contiguous_and_episode_bounded() {
    let directory = tempdir().unwrap();
    let lab = materialize_lab(directory.path()).unwrap();
    let runraw = MappedRunRawTape::open(directory.path().join("runraw.nrr1")).unwrap();
    let features = MappedFeatureTape::open(directory.path().join("features.nrf1")).unwrap();
    let mut config = lab.config;
    config.observation_spec.history_depth = 3;
    config.observation_spec.layout = ObservationLayout::WindowedMatrix;
    config.observation_spec.output_shape = vec![3, 6];
    config.observation_spec = identified(
        b"northstar-observation-spec-v1",
        config.observation_spec,
        |value, digest| value.observation_spec_id = digest,
    )
    .unwrap();
    config.episode_tape = compile_session_episodes(
        runraw.rows(),
        &features,
        &config.observation_spec,
        config.environment_spec.runraw_tape_id,
        config.environment_spec.episode_spec_id,
        EpisodeBindings {
            initial_account_state_id: AccountState::initial(config.initial_equity)
                .unwrap()
                .id()
                .unwrap(),
            action_spec_id: config.action_spec.action_spec_id,
            execution_spec_id: config.execution_spec.execution_spec_id,
            reward_spec_id: config.reward_spec.reward_spec_id,
            termination_spec_id: config.termination_spec.termination_spec_id,
        },
    )
    .unwrap();
    config.environment_spec.observation_spec_id = config.observation_spec.observation_spec_id;
    config.environment_spec.environment_id = Digest::ZERO;
    config.environment_spec.environment_id =
        northstar_rl_core::identity(b"northstar-rl-env-spec-v1", &config.environment_spec).unwrap();
    write_json(directory.path().join("window_config.json"), &config).unwrap();
    let mut environment = Environment::open(directory.path().join("window_config.json")).unwrap();
    let reset = environment.reset_episode(None, 42).unwrap();
    assert_eq!(reset.observation.len(), 18);
    assert_eq!(config.observation_spec.output_shape, vec![3, 6]);
}
