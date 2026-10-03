use std::path::{Path, PathBuf};

use crate::{
    ACTION_SPEC_TARGET_EXPOSURE_V1, AccountState, ActionSpec, Digest, EPISODE_TAPE_V1,
    EnvironmentConfig, EpisodeBindings, EpisodeSpec, ExecutionSpec, FEATURE_REGISTRY_V1,
    INSTRUMENT_CONTRACT_V1, InstrumentContract, MappedFeatureTape, MappedRunRawTape,
    NumericContract, OBSERVATION_SPEC_V1, ObservationDictionaryEntry, ObservationLayout,
    ObservationSpec, QuantityRounding, REWARD_SPEC_V1, RL_ENV_SPEC_V1, Result, RewardSpec,
    RlEnvSpec, RunRawRow, SeedContract, SourceStatus, TERMINATION_SPEC_V1, TerminationSpec,
    compile_features, compile_session_episodes, compiler_identity, identified, identity,
    kernel_implementation_hashes, primitive_feature_registry, registry_id, seal_feature_tape,
    seal_runraw,
};

#[derive(Clone, Debug)]
pub struct BuiltLab {
    pub config: EnvironmentConfig,
    pub registry: crate::FeatureRegistry,
    pub observation_dictionary: Vec<ObservationDictionaryEntry>,
}

pub fn row(source_row_id: u64, close: f64) -> RunRawRow {
    let event_time = 1_800_000_000_000_000_000_i64 + source_row_id as i64 * 60_000_000_000;
    RunRawRow {
        source_row_id,
        event_time,
        knowledge_time: event_time,
        open: close - 0.25,
        high: close + 1.0,
        low: close - 1.0,
        close,
        volume: 1_000.0 + source_row_id as f64 * 10.0,
        tick_volume: 500.0 + source_row_id as f64,
        spread: 1.0,
        instrument_id: 3,
        source_id: 1,
        session_id: 20260814,
        trading_day: 20260814,
        source_clock: 1,
        source_status: SourceStatus::Available as u8,
        reserved: [0; 6],
    }
}

pub fn canonical_rows() -> Vec<RunRawRow> {
    [
        100.0, 101.0, 102.0, 103.0, 104.0, 103.0, 102.0, 104.0, 106.0, 105.0, 107.0, 108.0,
    ]
    .into_iter()
    .enumerate()
    .map(|(index, close)| row(index as u64 + 1, close))
    .collect()
}

pub fn canonical_instrument() -> Result<InstrumentContract> {
    identified(
        b"northstar-instrument-contract-v1",
        InstrumentContract {
            schema_version: INSTRUMENT_CONTRACT_V1.into(),
            instrument_contract_id: Digest::ZERO,
            instrument_id: 3,
            price_precision: 2,
            tick_size: 0.01,
            tick_value: 0.01,
            contract_size: 1.0,
            quantity_step: 0.1,
            minimum_quantity: 0.1,
            maximum_quantity: 100.0,
            quote_currency: "USD".into(),
            account_currency: "USD".into(),
            conversion_rule: "identity_quote_equals_account".into(),
        },
        |value, digest| value.instrument_contract_id = digest,
    )
}

pub fn canonical_execution_spec() -> Result<ExecutionSpec> {
    identified(
        b"northstar-execution-spec-v1",
        ExecutionSpec {
            schema_version: crate::EXECUTION_SPEC_V1.into(),
            execution_spec_id: Digest::ZERO,
            action_source: "completed_bar_close".into(),
            fill_timing: "next_eligible_bar_open".into(),
            reference_fill_price: "source_open".into(),
            quantity_rounding: QuantityRounding::TowardZero,
            fixed_commission: 0.25,
            proportional_commission: 0.0001,
            spread_ticks: 1.0,
            slippage_ticks: 0.5,
            calibration_id: None,
        },
        |value, digest| value.execution_spec_id = digest,
    )
}

pub fn build_fixture_lab(output: impl AsRef<Path>) -> Result<BuiltLab> {
    let output = output.as_ref();
    std::fs::create_dir_all(output)?;
    let rows = canonical_rows();
    let runraw_path = output.join("runraw.nrr1");
    let source_manifest_hash = Digest::hash(
        b"northstar-fixture-source-manifest-v1",
        b"FORGE-RL-00 hand-computable canonical session; synthetic non-market authority",
    );
    seal_runraw(&runraw_path, source_manifest_hash, &rows)?;
    let runraw = MappedRunRawTape::open(&runraw_path)?;
    let runraw_tape_id = runraw.tape_id()?;

    let registry = primitive_feature_registry(3)?;
    debug_assert_eq!(registry.schema_version, FEATURE_REGISTRY_V1);
    let registry_identity = registry_id(&registry)?;
    let columns = compile_features(runraw.rows(), &registry)?;
    let feature_path = output.join("features.nrf1");
    seal_feature_tape(
        &feature_path,
        runraw_tape_id,
        registry_identity,
        compiler_identity(),
        &columns,
    )?;
    let features = MappedFeatureTape::open(&feature_path)?;
    let feature_tape_id = features.tape_id()?;

    let ordered_feature_ids = vec![
        "market.simple_return.v1".into(),
        "market.candle_range.v1".into(),
        "market.rolling_mean.v1".into(),
        "clock.time_of_day_sin.v1".into(),
        "clock.time_of_day_cos.v1".into(),
        "clock.session_progress.v1".into(),
    ];
    let observation_spec = identified(
        b"northstar-observation-spec-v1",
        ObservationSpec {
            schema_version: OBSERVATION_SPEC_V1.into(),
            observation_spec_id: Digest::ZERO,
            ordered_feature_ids: ordered_feature_ids.clone(),
            history_depth: 1,
            stacking_semantics: "feature_major_declared_order".into(),
            dtype: crate::FeatureDType::Float32,
            output_shape: vec![ordered_feature_ids.len() as u32],
            availability_rule: "all_cells_AVAILABLE_and_t_known_lte_step_time".into(),
            layout: ObservationLayout::Flat,
        },
        |value, digest| value.observation_spec_id = digest,
    )?;
    let episode_spec = identified(
        b"northstar-episode-spec-v1",
        EpisodeSpec {
            schema_version: EPISODE_TAPE_V1.into(),
            episode_spec_id: Digest::ZERO,
            mode: "one_qualified_market_session_per_episode".into(),
            source_gap_policy: "typed_terminal".into(),
        },
        |value, digest| value.episode_spec_id = digest,
    )?;
    let action_spec = identified(
        b"northstar-action-spec-target-exposure-v1",
        ActionSpec {
            schema_version: ACTION_SPEC_TARGET_EXPOSURE_V1.into(),
            action_spec_id: Digest::ZERO,
            low: -1.0,
            high: 1.0,
            shape: vec![1],
            dtype: "float32".into(),
            semantics: "target_normalized_exposure".into(),
        },
        |value, digest| value.action_spec_id = digest,
    )?;
    let instrument_contract = canonical_instrument()?;
    let execution_spec = canonical_execution_spec()?;
    let reward_spec = identified(
        b"northstar-reward-spec-v1",
        RewardSpec {
            schema_version: REWARD_SPEC_V1.into(),
            reward_spec_id: Digest::ZERO,
            formula: "equity_delta / initial_equity".into(),
        },
        |value, digest| value.reward_spec_id = digest,
    )?;
    let termination_spec = identified(
        b"northstar-termination-spec-v1",
        TerminationSpec {
            schema_version: TERMINATION_SPEC_V1.into(),
            termination_spec_id: Digest::ZERO,
            account_floor: 100.0,
            episode_end_is_truncation: true,
            source_gap_is_termination: true,
        },
        |value, digest| value.termination_spec_id = digest,
    )?;
    let numeric_contract = identified(
        b"northstar-numeric-contract-v1",
        NumericContract {
            schema_version: "NUMERIC_CONTRACT_V1".into(),
            numeric_contract_id: Digest::ZERO,
            authority_float: "ieee754_binary64_little_endian".into(),
            observation_float: "ieee754_binary32_contiguous".into(),
            action_float: "ieee754_binary32_scalar_box_1".into(),
            non_finite_policy: "reject_authority_reject_observation_reject_action".into(),
        },
        |value, digest| value.numeric_contract_id = digest,
    )?;
    let seed_contract = identified(
        b"northstar-seed-contract-v1",
        SeedContract {
            schema_version: "SEED_CONTRACT_V1".into(),
            seed_contract_id: Digest::ZERO,
            derivation:
                "domain_separated_blake3(root_seed, component_identity) -> little_endian_u64".into(),
        },
        |value, digest| value.seed_contract_id = digest,
    )?;
    let initial_account = AccountState::initial(1_000.0)?;
    let episode_tape = compile_session_episodes(
        runraw.rows(),
        &features,
        &observation_spec,
        runraw_tape_id,
        episode_spec.episode_spec_id,
        EpisodeBindings {
            initial_account_state_id: initial_account.id()?,
            action_spec_id: action_spec.action_spec_id,
            execution_spec_id: execution_spec.execution_spec_id,
            reward_spec_id: reward_spec.reward_spec_id,
            termination_spec_id: termination_spec.termination_spec_id,
        },
    )?;
    let mut environment_spec = RlEnvSpec {
        schema_version: RL_ENV_SPEC_V1.into(),
        environment_id: Digest::ZERO,
        runraw_tape_id,
        feature_tape_id,
        observation_spec_id: observation_spec.observation_spec_id,
        episode_spec_id: episode_spec.episode_spec_id,
        action_spec_id: action_spec.action_spec_id,
        instrument_contract_id: instrument_contract.instrument_contract_id,
        execution_spec_id: execution_spec.execution_spec_id,
        reward_spec_id: reward_spec.reward_spec_id,
        termination_spec_id: termination_spec.termination_spec_id,
        numeric_contract_id: numeric_contract.numeric_contract_id,
        seed_contract_id: seed_contract.seed_contract_id,
        market_source_contract: None,
        broker_contract_tape_id: None,
        execution_calibration_id: None,
        instrument_binding_id: None,
        wind_tunnel_mode: Some(crate::WindTunnelMode::RunRawReplay),
        implementation_hashes: kernel_implementation_hashes(),
        extension_implementation_hashes: Vec::new(),
    };
    environment_spec.environment_id = identity(b"northstar-rl-env-spec-v1", &environment_spec)?;

    let observation_dictionary = ordered_feature_ids
        .iter()
        .enumerate()
        .map(|(array_index, feature_id)| {
            let declaration = registry
                .features
                .iter()
                .find(|feature| &feature.feature_id == feature_id)
                .expect("registry member");
            ObservationDictionaryEntry {
                array_index: array_index as u32,
                feature_id: feature_id.clone(),
                feature_implementation_hash: declaration.implementation_hash,
                source_dependencies: declaration.source_dependencies.clone(),
            }
        })
        .collect();
    let config = EnvironmentConfig {
        schema_version: "NORTHSTAR_ENV_CONFIG_V1".into(),
        runraw_tape_path: PathBuf::from("runraw.nrr1"),
        feature_tape_path: PathBuf::from("features.nrf1"),
        environment_spec,
        observation_spec,
        action_spec,
        instrument_contract,
        execution_spec,
        reward_spec,
        termination_spec,
        numeric_contract,
        seed_contract,
        episode_tape,
        initial_equity: 1_000.0,
    };
    Ok(BuiltLab {
        config,
        registry,
        observation_dictionary,
    })
}
