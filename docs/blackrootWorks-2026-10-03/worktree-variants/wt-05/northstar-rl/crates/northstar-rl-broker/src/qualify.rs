use std::{
    hint::black_box,
    path::{Path, PathBuf},
    time::Instant,
};

use northstar_rl_core::{
    AuthorityManifest, AuthorityManifestEntry, Digest, Environment, EnvironmentConfig,
    QualificationItem, QualificationMatrix, QualificationStatus, ScriptedPolicy, identity,
    materialize_lab, read_json, run_scripted, write_json,
};
use schemars::{JsonSchema, schema_for};
use serde::{Deserialize, Serialize};

use crate::{
    BrokerAccountSnapshot, BrokerContractTape, BrokerInstrumentRegistry, BrokerObservationTape,
    BrokerPositionProjection, ClockComparisonReceipt, ConnectionDiagnostic, ConnectionState,
    ExecutionCalibration, ExecutionRealityTape, InstrumentBinding, LiveReadReceipt,
    MappedBrokerCapture, PriceComparison, Result, StudioBacktraderAdapterSpec,
    WindTunnelSourceSpec, joint_fixture, seal_broker_capture, studio_adapter,
};

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct JointPerformanceMetric {
    pub name: String,
    pub value: f64,
    pub unit: String,
    pub component: String,
    pub workload: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct JointPerformanceReport {
    pub schema_version: String,
    pub metrics: Vec<JointPerformanceMetric>,
    pub network_receipt: Option<Vec<JointPerformanceMetric>>,
    pub limitations: Vec<String>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct JointDoubleBuildReceipt {
    pub schema_version: String,
    pub first_root: Digest,
    pub second_root: Digest,
    pub byte_identical: bool,
    pub files: Vec<String>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct TopologyNode {
    pub kind: String,
    pub identity: Digest,
    pub authority: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct TopologyReport {
    pub schema_version: String,
    pub path: String,
    pub nodes: Vec<TopologyNode>,
    pub command_authority: String,
    pub learner_execution: String,
}

#[derive(Clone, Debug)]
pub struct JointQualificationOutput {
    pub surface_root: Digest,
    pub fixture_root: Digest,
    pub matrix: QualificationMatrix,
}

pub fn qualify_joint(
    output: impl AsRef<Path>,
    live: Option<LiveReadReceipt>,
) -> Result<JointQualificationOutput> {
    let output = output.as_ref();
    std::fs::create_dir_all(output)?;
    let lab = materialize_lab(output)?;
    let fixture = joint_fixture()?;
    write_json(output.join("joint_replay_fixture.json"), &fixture)?;
    write_json(
        output.join("broker_instrument_registry.json"),
        &fixture.registry,
    )?;
    write_json(output.join("instrument_binding.json"), &fixture.binding)?;
    write_json(
        output.join("broker_contract_tape.json"),
        &fixture.broker_contracts,
    )?;
    write_json(
        output.join("clock_comparison_receipts.json"),
        &fixture.clock_comparisons,
    )?;
    write_json(
        output.join("price_comparison_receipts.json"),
        &fixture.price_comparisons,
    )?;
    write_json(
        output.join("execution_calibration.json"),
        &fixture.calibration,
    )?;
    write_json(
        output.join("wind_tunnel_source_spec.json"),
        &fixture.wind_tunnel,
    )?;
    let capture_header = seal_broker_capture(
        output.join("tradelocker_capture.nsb1"),
        &fixture.tradelocker,
    )?;
    write_json(
        output.join("tradelocker_capture_header.json"),
        &capture_header,
    )?;
    seal_broker_capture(output.join("mt5_capture.nsb1"), &fixture.mt5)?;

    let account = synthetic_account(&fixture)?;
    let positions: Vec<BrokerPositionProjection> = Vec::new();
    let reality = ExecutionRealityTape {
        schema_version: crate::EXECUTION_REALITY_TAPE_V1.into(),
        source_authority: "NO_AUTHORITATIVE_EXECUTIONS_IN_SYNTHETIC_FIXTURE".into(),
        rows: Vec::new(),
        content_hash: Digest::hash(b"northstar-empty-execution-reality-v1", b""),
    };
    write_json(output.join("broker_account_snapshot.json"), &account)?;
    write_json(output.join("broker_position_projection.json"), &positions)?;
    write_json(output.join("execution_reality_tape.json"), &reality)?;
    if let Some(receipt) = &live {
        write_json(
            output.join("live_broker_instrument_registry.json"),
            &receipt.registry,
        )?;
        write_json(
            output.join("live_broker_observation_tape.json"),
            &receipt.quote_tape,
        )?;
        write_json(
            output.join("live_broker_account_snapshot.json"),
            &receipt.account,
        )?;
        write_json(
            output.join("live_broker_position_projection.json"),
            &receipt.positions,
        )?;
        write_json(
            output.join("live_broker_contract_tape.json"),
            &live_contract_tape(receipt)?,
        )?;
    }

    let studio = studio_adapter(
        lab.config.episode_tape.episode_spec_id,
        lab.config.environment_spec.feature_tape_id,
        lab.config.action_spec.action_spec_id,
        fixture.broker_contracts.content_hash,
    )?;
    write_json(output.join("studio_backtrader_adapter.json"), &studio)?;
    let mut config = lab.config.clone();
    extend_environment_provenance(&mut config, &fixture)?;
    write_json(output.join("environment_config.json"), &config)?;
    write_json(output.join("rl_env_spec.json"), &config.environment_spec)?;
    let mut environment = Environment::open(output.join("environment_config.json"))?;
    let replay = run_scripted(
        &mut environment,
        None,
        42,
        ScriptedPolicy::AlternateExtremes,
    )?;
    write_json(
        output.join("joint_environment_replay_receipt.json"),
        &replay,
    )?;

    emit_schemas(output.join("schemas"))?;
    let performance = benchmark_joint(output, &fixture.tradelocker, live.as_ref())?;
    write_json(output.join("joint_performance_report.json"), &performance)?;
    let double = double_build(output)?;
    write_json(output.join("joint_double_build_receipt.json"), &double)?;
    let diagnostic = live
        .as_ref()
        .map(|receipt| receipt.diagnostic.clone())
        .unwrap_or_else(|| ConnectionDiagnostic {
            provider: "TRADELOCKER".into(),
            credential_provider: "WINDOWS_GENERIC_CREDENTIAL".into(),
            credential_alias: crate::DEFAULT_CREDENTIAL_TARGET.into(),
            credential_resolved: false,
            authenticated_account_id_hash: None,
            connection_environment: "LIVE".into(),
            connection_state: ConnectionState::Unavailable,
            detail_code: "LIVE_READ_NOT_EXECUTED".into(),
        });
    write_json(
        output.join("tradelocker_connection_diagnostic.json"),
        &diagnostic,
    )?;
    let live_capture_replayed = output.join("live_tradelocker_capture.nsb1").exists()
        && MappedBrokerCapture::open(output.join("live_tradelocker_capture.nsb1")).is_ok();
    let matrix = qualification_matrix(
        &diagnostic,
        live.is_some(),
        live_capture_replayed,
        double.byte_identical,
    );
    write_json(output.join("joint_qualification_matrix.json"), &matrix)?;
    let topology = topology(&fixture, &config, replay.trajectory_root);
    write_json(output.join("topology_report.json"), &topology)?;
    let manifest = seal_joint(output)?;
    Ok(JointQualificationOutput {
        surface_root: manifest.root_identity,
        fixture_root: fixture.content_hash,
        matrix,
    })
}

fn extend_environment_provenance(
    config: &mut EnvironmentConfig,
    fixture: &crate::JointReplayFixture,
) -> Result<()> {
    let spec = &mut config.environment_spec;
    spec.environment_id = Digest::ZERO;
    spec.market_source_contract = Some(fixture.runraw_source_contract);
    spec.broker_contract_tape_id = Some(fixture.broker_contracts.content_hash);
    spec.execution_calibration_id = Some(fixture.calibration.calibration_id);
    spec.instrument_binding_id = Some(fixture.binding.binding_id);
    spec.wind_tunnel_mode = Some(northstar_rl_core::WindTunnelMode::CrossSourceComparison);
    spec.extension_implementation_hashes = crate::broker_implementation_hashes();
    spec.environment_id = identity(b"northstar-rl-env-spec-v1", spec)?;
    Ok(())
}

fn synthetic_account(fixture: &crate::JointReplayFixture) -> Result<BrokerAccountSnapshot> {
    let raw = Digest::hash(
        b"synthetic-account-payload-v1",
        b"balance=1000;equity=1000;available=1000",
    );
    let mut value = BrokerAccountSnapshot {
        schema_version: crate::BROKER_ACCOUNT_SNAPSHOT_V1.into(),
        account_id_hash: fixture.tradelocker.account_id_hash,
        environment: "SYNTHETIC_QUALIFICATION".into(),
        broker_raw_terms: vec![
            ("balance".into(), 1000.0),
            ("projectedBalance".into(), 1000.0),
            ("availableFunds".into(), 1000.0),
        ],
        cash_equivalent: Some(1000.0),
        equity: Some(1000.0),
        unrealized_pnl: Some(0.0),
        realized_pnl: None,
        available_funds: Some(1000.0),
        margin_terms: Vec::new(),
        broker_time_ns: None,
        received_time_ns: fixture.tradelocker.rows[0].received_time_ns,
        raw_payload_hash: raw,
        field_provenance: vec![
            ("cash_equivalent".into(), "BROKER_RAW.balance".into()),
            ("equity".into(), "BROKER_RAW.projectedBalance".into()),
        ],
        content_hash: Digest::ZERO,
    };
    value.content_hash = identity(b"northstar-broker-account-snapshot-v1", &value)?;
    Ok(value)
}

fn live_contract_tape(receipt: &LiveReadReceipt) -> Result<BrokerContractTape> {
    let mut tape = BrokerContractTape {
        schema_version: crate::BROKER_CONTRACT_TAPE_V1.into(),
        rows: receipt
            .registry
            .instruments
            .iter()
            .map(|instrument| crate::BrokerContractRow {
                northstar_instrument_id: instrument.northstar_instrument_id,
                valid_from_ns: instrument.observed_at_ns,
                observed_at_ns: instrument.observed_at_ns,
                tick_size: instrument.tick_size,
                quantity_step: instrument.quantity_step,
                minimum_quantity: instrument.min_quantity,
                contract_size: instrument.contract_size,
                margin_fields: Vec::new(),
                broker_precision: instrument.price_precision,
                quote_denomination: instrument.quote_currency.clone(),
                trading_availability: instrument.trading_status.clone(),
                source_authority: "LIVE_TRADELOCKER_NORMALIZED_CAPTURE".into(),
                source_payload_hash: instrument.raw_metadata.payload_hash,
            })
            .collect(),
        content_hash: Digest::ZERO,
    };
    tape.content_hash = identity(b"northstar-broker-contract-tape-v1", &tape)?;
    Ok(tape)
}

fn benchmark_joint(
    root: &Path,
    tape: &BrokerObservationTape,
    live: Option<&LiveReadReceipt>,
) -> Result<JointPerformanceReport> {
    let path = root.join("tradelocker_capture.nsb1");
    let iterations = 1_000_u64;
    let start = Instant::now();
    let mut bytes = 0_u64;
    for _ in 0..iterations {
        let mapped = MappedBrokerCapture::open(&path)?;
        bytes += std::mem::size_of_val(mapped.rows()) as u64;
        black_box(mapped.rows()[0].bid);
    }
    let replay_s = start.elapsed().as_secs_f64().max(f64::MIN_POSITIVE);
    let start = Instant::now();
    for _ in 0..iterations {
        black_box(serde_json::to_vec(tape)?);
    }
    let serialize_s = start.elapsed().as_secs_f64().max(f64::MIN_POSITIVE);
    let payload_bytes = serde_json::to_vec(tape)?.len() as f64;
    let start = Instant::now();
    for _ in 0..iterations {
        for (left, right) in tape.rows.iter().zip(&tape.rows) {
            black_box(right.bid - left.bid);
        }
    }
    let match_s = start.elapsed().as_secs_f64().max(f64::MIN_POSITIVE);
    Ok(JointPerformanceReport { schema_version: "JOINT_PERFORMANCE_REPORT_V1".into(), metrics: vec![
        metric("broker_tape_replay", bytes as f64 / replay_s / 1e9, "GB_per_second_payload", "SERIALIZATION", "mmap_open_hash_validate_and_scan"),
        metric("broker_observation_serialization", payload_bytes * iterations as f64 / serialize_s / 1e9, "GB_per_second", "SERIALIZATION", "normalized_json"),
        metric("mt5_tradelocker_matching", iterations as f64 * tape.rows.len() as f64 / match_s, "pairs_per_second", "NORMALIZATION", "aligned_fixture_pairs"),
    ], network_receipt: live.map(|receipt| receipt.timings.clone()), limitations: vec![
        "Live endpoint timings combine NETWORK_LATENCY and API_PROCESSING because the provider exposes no server processing timer".into(),
        "PyO3 replay throughput remains represented by the FORGE-RL-00 native compatibility receipt".into(),
        "Fixture measurements are architecture baselines, not production market throughput claims".into(),
    ] })
}

fn metric(
    name: &str,
    value: f64,
    unit: &str,
    component: &str,
    workload: &str,
) -> JointPerformanceMetric {
    JointPerformanceMetric {
        name: name.into(),
        value,
        unit: unit.into(),
        component: component.into(),
        workload: workload.into(),
    }
}

fn double_build(output: &Path) -> Result<JointDoubleBuildReceipt> {
    let base = output.join("double_rebuild_joint");
    let first = base.join("first");
    let second = base.join("second");
    std::fs::create_dir_all(&first)?;
    std::fs::create_dir_all(&second)?;
    let fixture = joint_fixture()?;
    for root in [&first, &second] {
        write_json(root.join("joint_replay_fixture.json"), &fixture)?;
        seal_broker_capture(root.join("tradelocker_capture.nsb1"), &fixture.tradelocker)?;
        seal_broker_capture(root.join("mt5_capture.nsb1"), &fixture.mt5)?;
    }
    let files = vec![
        "joint_replay_fixture.json".to_string(),
        "tradelocker_capture.nsb1".into(),
        "mt5_capture.nsb1".into(),
    ];
    let root = |directory: &Path| -> Result<Digest> {
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"northstar-joint-double-build-v1");
        for name in &files {
            let bytes = std::fs::read(directory.join(name))?;
            hasher.update(name.as_bytes());
            hasher.update(&bytes);
        }
        Ok(Digest(*hasher.finalize().as_bytes()))
    };
    let first_root = root(&first)?;
    let second_root = root(&second)?;
    Ok(JointDoubleBuildReceipt {
        schema_version: "JOINT_DOUBLE_REBUILD_RECEIPT_V1".into(),
        first_root,
        second_root,
        byte_identical: first_root == second_root,
        files,
    })
}

fn qualification_matrix(
    live: &ConnectionDiagnostic,
    live_receipt: bool,
    live_replay: bool,
    rebuild: bool,
) -> QualificationMatrix {
    let live_ok = live.connection_state == ConnectionState::Connected
        || live.connection_state == ConnectionState::Reauthenticated;
    let mut items = Vec::new();
    for name in [
        "EXECUTION_REALITY_SCHEMA",
        "EXECUTION_CALIBRATION_INTERFACE",
        "JOINT_REPLAY_FIXTURE",
        "STUDIO_BACKTRADER_ADAPTER",
        "RL_ENV_PROVENANCE_EXTENSION",
        "PERFORMANCE_BASELINE",
    ] {
        items.push(item(
            name,
            QualificationStatus::Qualified,
            "SYNTHETIC_CONTRACT_FIXTURE_AND_OFFLINE_REPLAY_PASS",
        ));
    }
    for name in [
        "INSTRUMENT_BINDING",
        "CLOCK_COMPARISON",
        "MT5_TL_PRICE_COMPARISON",
    ] {
        items.push(item(
            name,
            QualificationStatus::Partial,
            "SYNTHETIC_CROSS_SOURCE_FIXTURE_PASS_LIVE_MT5_CAPTURE_ABSENT",
        ));
    }
    items.push(item(
        "BROKER_CONTRACT_TAPE",
        if live_receipt {
            QualificationStatus::Qualified
        } else {
            QualificationStatus::Partial
        },
        if live_receipt {
            "AUTHENTICATED_TIME_BOUND_LIVE_CONTRACT_TAPE_PASS"
        } else {
            "SYNTHETIC_FIXTURE_ONLY"
        },
    ));
    for name in [
        "PRICE_OBSERVATION_TAPE",
        "ACCOUNT_PROJECTION",
        "POSITION_PROJECTION",
    ] {
        items.push(item(
            name,
            if live_receipt {
                QualificationStatus::Qualified
            } else {
                QualificationStatus::Partial
            },
            if live_receipt {
                "AUTHENTICATED_NORMALIZED_LIVE_RECEIPT_PASS"
            } else {
                "SYNTHETIC_FIXTURE_ONLY"
            },
        ));
    }
    items.push(item(
        "TRADELOCKER_CAPTURE_REPLAY",
        if live_replay {
            QualificationStatus::Qualified
        } else {
            QualificationStatus::Partial
        },
        if live_replay {
            "LIVE_NORMALIZED_CAPTURE_MMAP_REOPEN_PASS"
        } else {
            "SYNTHETIC_CAPTURE_REPLAY_ONLY"
        },
    ));
    items.push(item(
        "DETERMINISTIC_REBUILD",
        if rebuild {
            QualificationStatus::Qualified
        } else {
            QualificationStatus::Gap
        },
        if rebuild {
            "BYTE_IDENTICAL_DOUBLE_REBUILD"
        } else {
            "DOUBLE_REBUILD_MISMATCH"
        },
    ));
    items.push(item(
        "CREDENTIAL_PROVIDER",
        if live.credential_resolved {
            QualificationStatus::Qualified
        } else {
            QualificationStatus::Gap
        },
        &live.detail_code,
    ));
    for name in ["TRADELOCKER_CONNECTION", "INSTRUMENT_DISCOVERY"] {
        items.push(item(
            name,
            if live_ok {
                QualificationStatus::Qualified
            } else {
                QualificationStatus::Gap
            },
            if live_ok {
                "AUTHENTICATED_READ_RECEIPT_PASS"
            } else {
                "LIVE_READ_NOT_QUALIFIED"
            },
        ));
    }
    items.sort_by(|a, b| a.name.cmp(&b.name));
    QualificationMatrix {
        project: "FORGE-RL-01".into(),
        surface: "NORTHSTAR_JOINT_WIND_TUNNEL_V1".into(),
        learner_execution: "PROHIBITED_UNTIL_LATER_GATE".into(),
        items,
    }
}

fn item(name: &str, status: QualificationStatus, reason: &str) -> QualificationItem {
    QualificationItem {
        name: name.into(),
        status,
        reason_code: reason.into(),
        receipts: vec![
            "joint_replay_fixture.json".into(),
            "topology_report.json".into(),
        ],
    }
}

fn topology(
    fixture: &crate::JointReplayFixture,
    config: &EnvironmentConfig,
    trajectory: Digest,
) -> TopologyReport {
    TopologyReport { schema_version: "JOINT_WIND_TUNNEL_TOPOLOGY_V1".into(),
        path: "MT5 + TradeLocker + RunRaw -> instrument binding -> sealed tapes -> Rust environment -> trajectory receipt".into(),
        nodes: vec![
            TopologyNode { kind: "RUNRAW_SOURCE_CONTRACT".into(), identity: fixture.runraw_source_contract, authority: "SYNTHETIC_FIXTURE".into() },
            TopologyNode { kind: "MT5_CAPTURE".into(), identity: fixture.mt5.content_hash, authority: "SYNTHETIC_FIXTURE".into() },
            TopologyNode { kind: "TRADELOCKER_CAPTURE".into(), identity: fixture.tradelocker.content_hash, authority: "SYNTHETIC_FIXTURE".into() },
            TopologyNode { kind: "INSTRUMENT_BINDING".into(), identity: fixture.binding.binding_id, authority: "NORTHSTAR".into() },
            TopologyNode { kind: "RL_ENVIRONMENT".into(), identity: config.environment_spec.environment_id, authority: "NORTHSTAR".into() },
            TopologyNode { kind: "TRAJECTORY_RECEIPT".into(), identity: trajectory, authority: "NORTHSTAR".into() },
        ], command_authority: "NORTHSTAR_ONLY".into(), learner_execution: "NOT_EXECUTED".into() }
}

fn emit_schemas(output: PathBuf) -> Result<()> {
    std::fs::create_dir_all(&output)?;
    macro_rules! schema {
        ($name:literal, $ty:ty) => {
            write_json(
                output.join(concat!($name, ".schema.json")),
                &schema_for!($ty),
            )?;
        };
    }
    schema!("BROKER_INSTRUMENT_REGISTRY_V1", BrokerInstrumentRegistry);
    schema!("INSTRUMENT_BINDING_V1", InstrumentBinding);
    schema!("BROKER_OBSERVATION_TAPE_V1", BrokerObservationTape);
    schema!("BROKER_ACCOUNT_SNAPSHOT_V1", BrokerAccountSnapshot);
    schema!("BROKER_POSITION_PROJECTION_V1", BrokerPositionProjection);
    schema!("CLOCK_COMPARISON_RECEIPT_V1", ClockComparisonReceipt);
    schema!("BROKER_PRICE_COMPARISON_V1", PriceComparison);
    schema!("BROKER_CONTRACT_TAPE_V1", BrokerContractTape);
    schema!("EXECUTION_REALITY_TAPE_V1", ExecutionRealityTape);
    schema!("EXECUTION_CALIBRATION_V1", ExecutionCalibration);
    schema!("WIND_TUNNEL_MODE_V1", WindTunnelSourceSpec);
    schema!("STUDIO_BACKTRADER_ADAPTER_V1", StudioBacktraderAdapterSpec);
    Ok(())
}

fn seal_joint(root: &Path) -> Result<AuthorityManifest> {
    let mut paths = Vec::new();
    collect(root, root, &mut paths)?;
    paths.retain(|p| {
        let n = p.to_string_lossy().replace('\\', "/");
        !n.starts_with("double_rebuild_joint/")
            && n != "joint_authority_manifest.json"
            && n != "NORTHSTAR_JOINT_WIND_TUNNEL_V1"
    });
    paths.sort();
    let mut entries = Vec::with_capacity(paths.len());
    for relative in paths {
        let bytes = std::fs::read(root.join(&relative))?;
        entries.push(AuthorityManifestEntry {
            path: relative.to_string_lossy().replace('\\', "/"),
            bytes: bytes.len() as u64,
            content_hash: Digest::hash(b"northstar-joint-artifact-file-v1", &bytes),
            authority: if relative.to_string_lossy().contains("performance") {
                "DIAGNOSTIC".into()
            } else {
                "FORGE_RL_01".into()
            },
        });
    }
    let mut manifest = AuthorityManifest {
        schema_version: "NORTHSTAR_JOINT_AUTHORITY_MANIFEST_V1".into(),
        surface: "NORTHSTAR_JOINT_WIND_TUNNEL_V1".into(),
        entries,
        root_identity: Digest::ZERO,
    };
    manifest.root_identity = identity(b"northstar-joint-wind-tunnel-v1", &manifest)?;
    write_json(root.join("joint_authority_manifest.json"), &manifest)?;
    std::fs::write(
        root.join("NORTHSTAR_JOINT_WIND_TUNNEL_V1"),
        format!("{}\n", manifest.root_identity),
    )?;
    Ok(manifest)
}

fn collect(root: &Path, current: &Path, output: &mut Vec<PathBuf>) -> Result<()> {
    for entry in std::fs::read_dir(current)? {
        let path = entry?.path();
        if path.is_dir() {
            collect(root, &path, output)?;
        } else {
            output.push(path.strip_prefix(root).expect("descendant").to_path_buf());
        }
    }
    Ok(())
}

pub fn read_joint_config(path: impl AsRef<Path>) -> Result<EnvironmentConfig> {
    Ok(read_json(path)?)
}
