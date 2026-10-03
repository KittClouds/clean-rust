//! Qualification artifact generation and sealing.

use std::{
    fs::{File, OpenOptions},
    hint::black_box,
    io::{Read, Write},
    path::{Path, PathBuf},
    time::Instant,
};

use schemars::{JsonSchema, schema_for};
use serde::{Deserialize, Serialize, de::DeserializeOwned};

use crate::{
    ActionSpec, Digest, EnvStepRecord, Environment, EnvironmentConfig, EpisodeTape, ExecutionSpec,
    FeatureRegistry, FeatureTapeHeader, InstrumentContract, NumericContract, ObservationSpec,
    ReplayReceipt, Result, RewardPrimitives, RewardSpec, RlEnvSpec, RunRawHeader, ScriptedPolicy,
    SeedContract, TerminalReceipt, TerminationSpec, build_fixture_lab, canonical_rows,
    compile_features, primitive_feature_registry, run_scripted,
};

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum QualificationStatus {
    Qualified,
    Partial,
    Gap,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct QualificationItem {
    pub name: String,
    pub status: QualificationStatus,
    pub reason_code: String,
    pub receipts: Vec<String>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct QualificationMatrix {
    pub project: String,
    pub surface: String,
    pub learner_execution: String,
    pub items: Vec<QualificationItem>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct DoubleBuildReceipt {
    pub schema_version: String,
    pub compared_files: Vec<String>,
    pub first_root: Digest,
    pub second_root: Digest,
    pub byte_identical: bool,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct PerformanceMetric {
    pub name: String,
    pub value: f64,
    pub unit: String,
    pub workload: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct PerformanceReport {
    pub schema_version: String,
    pub optimization_posture: String,
    pub metrics: Vec<PerformanceMetric>,
    pub gaps: Vec<String>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct AuthorityManifestEntry {
    pub path: String,
    pub bytes: u64,
    pub content_hash: Digest,
    pub authority: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct AuthorityManifest {
    pub schema_version: String,
    pub surface: String,
    pub entries: Vec<AuthorityManifestEntry>,
    pub root_identity: Digest,
}

#[derive(Clone, Debug)]
pub struct QualificationOutput {
    pub environment_id: Digest,
    pub trajectory_root: Digest,
    pub surface_root: Digest,
    pub matrix: QualificationMatrix,
}

pub fn qualify(output: impl AsRef<Path>) -> Result<QualificationOutput> {
    let output = output.as_ref();
    std::fs::create_dir_all(output)?;
    let double_root = output.join("double_rebuild");
    let first = double_root.join("first");
    let second = double_root.join("second");
    materialize_lab(&first)?;
    materialize_lab(&second)?;
    let compared = deterministic_lab_files();
    let first_root = directory_root(&first, compared)?;
    let second_root = directory_root(&second, compared)?;
    let byte_identical = compared
        .iter()
        .all(|name| std::fs::read(first.join(name)).ok() == std::fs::read(second.join(name)).ok());
    let double_receipt = DoubleBuildReceipt {
        schema_version: "DOUBLE_REBUILD_RECEIPT_V1".into(),
        compared_files: compared.iter().map(|value| (*value).into()).collect(),
        first_root,
        second_root,
        byte_identical,
    };
    write_json(output.join("double_build_receipt.json"), &double_receipt)?;
    if !byte_identical || first_root != second_root {
        return Err(crate::Error::InvalidContract(
            "independent fixture lab rebuilds were not byte-identical".into(),
        ));
    }

    let lab = materialize_lab(output)?;
    emit_schemas(output.join("schemas"))?;
    emit_hand_fixtures(output.join("fixtures"))?;
    let mut environment = Environment::open(output.join("environment_config.json"))?;
    let replay_receipt = run_scripted(
        &mut environment,
        None,
        42,
        ScriptedPolicy::AlternateExtremes,
    )?;
    write_json(output.join("replay_receipt.json"), &replay_receipt)?;
    write_json(output.join("env_step_tape.json"), &environment.steps())?;
    write_json(
        output.join("execution_receipts.json"),
        &environment.executions(),
    )?;
    write_json(
        output.join("terminal_receipt.json"),
        environment.terminal_receipt().expect("replay terminal"),
    )?;
    let action_count = lab.config.episode_tape.episodes[0].actionable_rows as usize;
    let policies = [
        ScriptedPolicy::AlwaysFlat,
        ScriptedPolicy::AlwaysFullPositive,
        ScriptedPolicy::AlwaysFullNegative,
        ScriptedPolicy::AlternateExtremes,
        ScriptedPolicy::FixedActionSequence(
            (0..action_count)
                .map(|index| [0.0, 0.25, 1.0, -1.0, -0.5][index % 5])
                .collect(),
        ),
        ScriptedPolicy::SeededRandomActions,
    ];
    let mut oracle_receipts = Vec::with_capacity(policies.len());
    for policy in policies {
        let mut oracle_environment = Environment::open(output.join("environment_config.json"))?;
        oracle_receipts.push(run_scripted(&mut oracle_environment, None, 42, policy)?);
    }
    write_json(
        output.join("scripted_oracle_receipts.json"),
        &oracle_receipts,
    )?;
    let performance = benchmark(output.join("environment_config.json"))?;
    write_json(output.join("performance_report.json"), &performance)?;

    let matrix = default_matrix(true, output.join("sb3_compatibility_receipt.json").exists());
    write_json(output.join("qualification_matrix.json"), &matrix)?;
    let manifest = seal_artifacts(output)?;
    Ok(QualificationOutput {
        environment_id: lab.config.environment_spec.environment_id,
        trajectory_root: replay_receipt.trajectory_root,
        surface_root: manifest.root_identity,
        matrix,
    })
}

pub fn materialize_lab(output: impl AsRef<Path>) -> Result<crate::BuiltLab> {
    let output = output.as_ref();
    let lab = build_fixture_lab(output)?;
    write_json(output.join("feature_registry.json"), &lab.registry)?;
    write_json(
        output.join("observation_dictionary.json"),
        &lab.observation_dictionary,
    )?;
    write_json(output.join("episode_tape.json"), &lab.config.episode_tape)?;
    write_json(
        output.join("rl_env_spec.json"),
        &lab.config.environment_spec,
    )?;
    write_json(output.join("environment_config.json"), &lab.config)?;
    Ok(lab)
}

pub fn benchmark(config_path: impl AsRef<Path>) -> Result<PerformanceReport> {
    let config_path = config_path.as_ref();
    let config: EnvironmentConfig = read_json(config_path)?;
    let base = config_path.parent().unwrap_or_else(|| Path::new("."));
    let runraw_path = base.join(&config.runraw_tape_path);
    let feature_path = base.join(&config.feature_tape_path);
    let loops = 300_u64;

    let start = Instant::now();
    for _ in 0..loops {
        black_box(crate::MappedRunRawTape::open(&runraw_path)?);
    }
    let decode_seconds = start.elapsed().as_secs_f64().max(f64::MIN_POSITIVE);
    let rows = canonical_rows();
    let registry = primitive_feature_registry(3)?;
    let start = Instant::now();
    for _ in 0..loops {
        black_box(compile_features(&rows, &registry)?);
    }
    let compile_seconds = start.elapsed().as_secs_f64().max(f64::MIN_POSITIVE);

    let feature_bytes = std::fs::metadata(&feature_path)?.len();
    let mapped = crate::MappedFeatureTape::open(&feature_path)?;
    let start = Instant::now();
    let mut checksum = 0.0;
    for _ in 0..10_000 {
        for meta in &mapped.header().columns {
            let (values, states, known) = mapped.column(&meta.feature_id).expect("declared column");
            checksum += values.iter().sum::<f64>()
                + states.iter().map(|&value| value as f64).sum::<f64>()
                + known[0] as f64;
        }
    }
    black_box(checksum);
    let scan_seconds = start.elapsed().as_secs_f64().max(f64::MIN_POSITIVE);
    let scanned_cell_bytes = mapped.header().columns.len() as f64
        * mapped.header().row_count as f64
        * (size_of::<f64>() * 2 + size_of::<u8>()) as f64;

    let mut metrics = vec![
        PerformanceMetric {
            name: "runraw_decode".into(),
            value: loops as f64 * rows.len() as f64 / decode_seconds,
            unit: "rows_per_second".into(),
            workload: "mmap_open_validate_hash_canonical_fixture".into(),
        },
        PerformanceMetric {
            name: "feature_compile".into(),
            value: loops as f64 * rows.len() as f64 / compile_seconds,
            unit: "rows_per_second".into(),
            workload: "21_primitive_features_window_3".into(),
        },
        PerformanceMetric {
            name: "feature_tape_scan".into(),
            value: scanned_cell_bytes * 10_000.0 / scan_seconds / 1_000_000_000.0,
            unit: "GB_per_second_payload".into(),
            workload: "mmap_value_state_knowledge_column_scan".into(),
        },
        PerformanceMetric {
            name: "mapped_artifact_footprint".into(),
            value: (std::fs::metadata(&runraw_path)?.len() + feature_bytes) as f64,
            unit: "bytes".into(),
            workload: "canonical_fixture".into(),
        },
    ];
    for count in [1_usize, 8, 32] {
        let start = Instant::now();
        let mut steps = 0_u64;
        for lane in 0..count {
            let mut environment = Environment::open(config_path)?;
            for cycle in 0..30 {
                let receipt = run_scripted(
                    &mut environment,
                    None,
                    (lane * 100 + cycle) as u64,
                    ScriptedPolicy::SeededRandomActions,
                )?;
                steps += receipt.action_count;
            }
        }
        metrics.push(PerformanceMetric {
            name: "environment_step".into(),
            value: steps as f64 / start.elapsed().as_secs_f64().max(f64::MIN_POSITIVE),
            unit: "steps_per_second".into(),
            workload: format!("{count}_environments_sequential_batch"),
        });
    }
    let mut environment = Environment::open(config_path)?;
    let start = Instant::now();
    for seed in 0..10_000 {
        black_box(environment.reset_episode(None, seed)?);
    }
    metrics.push(PerformanceMetric {
        name: "reset_latency".into(),
        value: start.elapsed().as_secs_f64() * 1e6 / 10_000.0,
        unit: "microseconds_per_reset".into(),
        workload: "canonical_episode".into(),
    });
    let start = Instant::now();
    for _ in 0..100_000 {
        black_box(environment.current_observation()?);
    }
    metrics.push(PerformanceMetric {
        name: "observation_serialization".into(),
        value: start.elapsed().as_secs_f64() * 1e9 / 100_000.0,
        unit: "nanoseconds_per_f32_vector".into(),
        workload: "6_feature_flat_vector".into(),
    });
    Ok(PerformanceReport {
        schema_version: "PERFORMANCE_REPORT_V1".into(),
        optimization_posture: "baseline_receipt_before_further_hot_path_optimization".into(),
        metrics,
        gaps: vec![
            "Python-to-Rust call rate is populated by sb3_compatibility_receipt.json after native import".into(),
            "random episode seek is represented by reset latency because the qualification corpus contains one episode".into(),
            "8/32 environment baselines are sequential ownership lanes, not a parallel throughput claim".into(),
        ],
    })
}

pub fn seal_artifacts(root: impl AsRef<Path>) -> Result<AuthorityManifest> {
    let root = root.as_ref();
    let mut paths = Vec::new();
    collect_files(root, root, &mut paths)?;
    paths.retain(|path| {
        let text = path.to_string_lossy().replace('\\', "/");
        !text.starts_with("double_rebuild/")
            && text != "authority_manifest.json"
            && text != "NORTHSTAR_RL_SURFACE_V1"
    });
    paths.sort();
    let mut entries = Vec::with_capacity(paths.len());
    for relative in paths {
        let bytes = std::fs::read(root.join(&relative))?;
        entries.push(AuthorityManifestEntry {
            path: relative.to_string_lossy().replace('\\', "/"),
            bytes: bytes.len() as u64,
            content_hash: Digest::hash(b"northstar-artifact-file-v1", &bytes),
            authority: if relative.to_string_lossy().contains("performance") {
                "DIAGNOSTIC".into()
            } else {
                "FORGE_RL_00".into()
            },
        });
    }
    let mut manifest = AuthorityManifest {
        schema_version: "NORTHSTAR_AUTHORITY_MANIFEST_V1".into(),
        surface: "NORTHSTAR_RL_SURFACE_V1".into(),
        entries,
        root_identity: Digest::ZERO,
    };
    manifest.root_identity = crate::identity(b"northstar-rl-surface-v1", &manifest)?;
    write_json(root.join("authority_manifest.json"), &manifest)?;
    std::fs::write(
        root.join("NORTHSTAR_RL_SURFACE_V1"),
        format!("{}\n", manifest.root_identity),
    )?;
    Ok(manifest)
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
    schema!("RUNRAW_TAPE_V1", RunRawHeader);
    schema!("FEATURE_REGISTRY_V1", FeatureRegistry);
    schema!("FEATURE_TAPE_V1", FeatureTapeHeader);
    schema!("OBSERVATION_SPEC_V1", ObservationSpec);
    schema!("EPISODE_TAPE_V1", EpisodeTape);
    schema!("ACTION_SPEC_TARGET_EXPOSURE_V1", ActionSpec);
    schema!("INSTRUMENT_CONTRACT_V1", InstrumentContract);
    schema!("EXECUTION_SPEC_V1", ExecutionSpec);
    schema!("REWARD_PRIMITIVES_V1", RewardPrimitives);
    schema!("REWARD_SPEC_V1", RewardSpec);
    schema!("TERMINATION_SPEC_V1", TerminationSpec);
    schema!("ENV_STEP_TAPE_V1", EnvStepRecord);
    schema!("RL_ENV_SPEC_V1", RlEnvSpec);
    schema!("NUMERIC_CONTRACT_V1", NumericContract);
    schema!("SEED_CONTRACT_V1", SeedContract);
    schema!("TERMINAL_RECEIPT_V1", TerminalReceipt);
    schema!("REPLAY_RECEIPT_V1", ReplayReceipt);
    schema!("AUTHORITY_MANIFEST_V1", AuthorityManifest);
    Ok(())
}

#[derive(Serialize)]
struct HandFixture<'a> {
    name: &'a str,
    purpose: &'a str,
    rows: Vec<(f64, f64, f64, f64)>,
    actions: Vec<f32>,
    expected: &'a str,
}

fn emit_hand_fixtures(output: PathBuf) -> Result<()> {
    std::fs::create_dir_all(&output)?;
    let fixtures = [
        HandFixture {
            name: "constant_price",
            purpose: "zero gross PnL and explicit friction",
            rows: vec![(100.0, 100.0, 100.0, 100.0); 4],
            actions: vec![0.0, 1.0, 0.0],
            expected: "equity changes only by declared friction",
        },
        HandFixture {
            name: "monotonic_rise",
            purpose: "positive and negative exposure signs",
            rows: (0..4)
                .map(|i| {
                    let p = 100.0 + i as f64;
                    (p, p, p, p)
                })
                .collect(),
            actions: vec![1.0, 1.0, 1.0],
            expected: "long gross mark-to-market deltas are non-negative after entry",
        },
        HandFixture {
            name: "monotonic_fall",
            purpose: "negative exposure",
            rows: (0..4)
                .map(|i| {
                    let p = 100.0 - i as f64;
                    (p, p, p, p)
                })
                .collect(),
            actions: vec![-1.0, -1.0, -1.0],
            expected: "short gross mark-to-market deltas are non-negative after entry",
        },
        HandFixture {
            name: "gap_and_terminal",
            purpose: "gap/source terminal typing",
            rows: vec![(100.0, 101.0, 99.0, 100.0), (105.0, 106.0, 104.0, 105.0)],
            actions: vec![0.5],
            expected: "next-open execution includes the bar gap; typed source gaps stop before execution",
        },
        HandFixture {
            name: "exposure_crossings",
            purpose: "flat/positive/negative/fractional/rounding",
            rows: vec![(100.0, 101.0, 99.0, 100.0); 6],
            actions: vec![1.0, 0.0, -1.0, 1.0, 0.333],
            expected: "each target is rounded by quantity_step toward zero",
        },
    ];
    write_json(output.join("micro_fixtures.json"), &fixtures)?;
    Ok(())
}

fn default_matrix(rust_qualified: bool, sb3_receipt: bool) -> QualificationMatrix {
    let mut items = Vec::new();
    let core = [
        "RUNRAW_TAPE",
        "KNOWLEDGE_TIME",
        "FEATURE_REGISTRY",
        "FEATURE_TAPE",
        "OBSERVATION_SPEC",
        "EPISODE_TAPE",
        "STEP_CLOCK",
        "ACTION_CONTRACT",
        "INSTRUMENT_CONTRACT",
        "ACCOUNT_MACHINE",
        "EXECUTION_KERNEL",
        "REWARD_PRIMITIVES",
        "REWARD_SPEC",
        "TERMINATION_SPEC",
        "ENV_STEP_TAPE",
        "SEEDED_REPLAY",
        "DOUBLE_REBUILD",
        "PERFORMANCE_BASELINE",
    ];
    for name in core {
        items.push(QualificationItem {
            name: name.into(),
            status: if rust_qualified {
                QualificationStatus::Qualified
            } else {
                QualificationStatus::Partial
            },
            reason_code: if rust_qualified {
                "RUST_CONTRACT_AND_RECEIPT_PASS"
            } else {
                "RUST_VERIFICATION_PENDING"
            }
            .into(),
            receipts: vec![
                "replay_receipt.json".into(),
                "double_build_receipt.json".into(),
            ],
        });
    }
    for name in ["PYO3_BRIDGE", "GYMNASIUM_CONTRACT", "SB3_ENV_COMPATIBILITY"] {
        items.push(QualificationItem {
            name: name.into(),
            status: if sb3_receipt {
                QualificationStatus::Qualified
            } else if name == "PYO3_BRIDGE" {
                QualificationStatus::Partial
            } else {
                QualificationStatus::Gap
            },
            reason_code: if sb3_receipt {
                "PYTHON_QUALIFICATION_RECEIPT_PASS"
            } else if name == "PYO3_BRIDGE" {
                "SOURCE_PRESENT_NATIVE_IMPORT_NOT_YET_RECEIPTED"
            } else {
                "PYTHON_RUNTIME_QUALIFICATION_PENDING"
            }
            .into(),
            receipts: if sb3_receipt {
                vec!["sb3_compatibility_receipt.json".into()]
            } else {
                Vec::new()
            },
        });
    }
    items.sort_by(|left, right| left.name.cmp(&right.name));
    QualificationMatrix {
        project: "FORGE-RL-00".into(),
        surface: "NORTHSTAR_RL_SURFACE_V1".into(),
        learner_execution: "PROHIBITED_UNTIL_LATER_GATE".into(),
        items,
    }
}

fn deterministic_lab_files() -> &'static [&'static str] {
    &[
        "runraw.nrr1",
        "features.nrf1",
        "feature_registry.json",
        "observation_dictionary.json",
        "episode_tape.json",
        "rl_env_spec.json",
        "environment_config.json",
    ]
}

fn directory_root(root: &Path, names: &[&str]) -> Result<Digest> {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"northstar-double-rebuild-v1");
    for name in names {
        let bytes = std::fs::read(root.join(name))?;
        hasher.update(&(name.len() as u64).to_le_bytes());
        hasher.update(name.as_bytes());
        hasher.update(&(bytes.len() as u64).to_le_bytes());
        hasher.update(&bytes);
    }
    Ok(Digest(*hasher.finalize().as_bytes()))
}

fn collect_files(root: &Path, directory: &Path, paths: &mut Vec<PathBuf>) -> Result<()> {
    for entry in std::fs::read_dir(directory)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            collect_files(root, &path, paths)?;
        } else {
            paths.push(path.strip_prefix(root).expect("descendant").to_path_buf());
        }
    }
    Ok(())
}

pub fn write_json(path: impl AsRef<Path>, value: &impl Serialize) -> Result<()> {
    let path = path.as_ref();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let bytes = serde_json::to_vec_pretty(value)?;
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(path)?;
    file.write_all(&bytes)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

pub fn read_json<T: DeserializeOwned>(path: impl AsRef<Path>) -> Result<T> {
    let mut bytes = Vec::new();
    File::open(path)?.read_to_end(&mut bytes)?;
    Ok(serde_json::from_slice(&bytes)?)
}
