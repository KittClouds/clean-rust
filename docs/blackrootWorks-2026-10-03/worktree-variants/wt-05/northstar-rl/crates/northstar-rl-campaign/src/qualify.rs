use std::{
    hint::black_box,
    path::{Path, PathBuf},
    time::Instant,
};

use northstar_rl_core::{
    AuthorityManifest, AuthorityManifestEntry, Digest, EnvStepRecord, Environment,
    EnvironmentBatch, QualificationItem, QualificationMatrix, QualificationStatus, ScriptedPolicy,
    identity, materialize_lab, run_scripted, write_json,
};
use schemars::{JsonSchema, schema_for};
use serde::{Deserialize, Serialize};

use crate::{
    CampaignReceipt, CampaignRunReceipt, CampaignSpec, EvaluationReceipt, EvaluationSpec,
    ExperimentSpec, LearnerSpec, PartitionTape, PolicyArtifact, Result, TransformState,
    build_campaign_fixture, evaluate_step_tapes, observation_dictionary_hash,
    validate_campaign_fixture,
};

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct CampaignPerformanceMetric {
    pub name: String,
    pub value: f64,
    pub unit: String,
    pub workload: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct CampaignPerformanceReport {
    pub schema_version: String,
    pub metrics: Vec<CampaignPerformanceMetric>,
    pub limitations: Vec<String>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct CampaignDoubleBuildReceipt {
    pub schema_version: String,
    pub first_root: Digest,
    pub second_root: Digest,
    pub byte_identical: bool,
    pub files: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct CampaignQualificationOutput {
    pub campaign_id: Digest,
    pub experiment_id: Digest,
    pub surface_root: Digest,
}

pub fn qualify_campaign(output: impl AsRef<Path>) -> Result<CampaignQualificationOutput> {
    let output = output.as_ref();
    std::fs::create_dir_all(output)?;
    let lab = materialize_lab(output)?;
    let dictionary_hash = observation_dictionary_hash(&lab.observation_dictionary)?;
    let fixture = build_campaign_fixture(&lab.config.environment_spec, dictionary_hash)?;
    validate_campaign_fixture(&fixture)?;
    write_fixture(output, &fixture)?;
    emit_schemas(output.join("schemas"))?;

    let evaluation = qualify_evaluator(output, &fixture.evaluation)?;
    write_json(
        output.join("evaluation_qualification_receipt.json"),
        &evaluation,
    )?;
    let performance = benchmark_batches(output.join("environment_config.json"))?;
    write_json(
        output.join("campaign_performance_report.json"),
        &performance,
    )?;
    let double = double_build(output, &lab.config.environment_spec, dictionary_hash)?;
    write_json(output.join("campaign_double_build_receipt.json"), &double)?;
    let py_receipt = output
        .join("batched_pyo3_compatibility_receipt.json")
        .exists();
    let matrix = qualification_matrix(double.byte_identical, py_receipt);
    write_json(output.join("campaign_qualification_matrix.json"), &matrix)?;
    let manifest = seal_campaign(output)?;
    Ok(CampaignQualificationOutput {
        campaign_id: fixture.campaign.campaign_id,
        experiment_id: fixture.experiment.experiment_id,
        surface_root: manifest.root_identity,
    })
}

fn write_fixture(root: &Path, fixture: &crate::CampaignFixture) -> Result<()> {
    write_json(root.join("partition_tape.json"), &fixture.partition)?;
    write_json(root.join("transform_state.json"), &fixture.transform)?;
    write_json(root.join("learner_spec.json"), &fixture.learner)?;
    write_json(root.join("evaluation_spec.json"), &fixture.evaluation)?;
    write_json(root.join("experiment_spec.json"), &fixture.experiment)?;
    write_json(root.join("campaign_spec.json"), &fixture.campaign)?;
    write_json(
        root.join("planned_run_receipts.json"),
        &fixture.planned_runs,
    )?;
    write_json(
        root.join("campaign_receipt.json"),
        &fixture.campaign_receipt,
    )?;
    write_json(
        root.join("policy_artifact_contract.json"),
        &fixture.policy_contract,
    )?;
    write_json(root.join("partition_input_fixture.json"), &fixture.inputs)?;
    Ok(())
}

fn qualify_evaluator(root: &Path, spec: &EvaluationSpec) -> Result<EvaluationReceipt> {
    let mut environment = Environment::open(root.join("environment_config.json"))?;
    let replay = run_scripted(&mut environment, None, 7, ScriptedPolicy::AlwaysFlat)?;
    let template = environment.steps().to_vec();
    let episodes = spec
        .evaluation_episode_ids
        .iter()
        .map(|&episode_id| {
            let steps = template
                .iter()
                .cloned()
                .map(|mut step| {
                    step.episode_id = episode_id;
                    step
                })
                .collect::<Vec<_>>();
            (episode_id, steps)
        })
        .collect::<Vec<_>>();
    let first = evaluate_step_tapes(
        spec,
        "SCRIPTED_ORACLE_NOT_LEARNED_POLICY",
        replay.trajectory_root,
        &episodes,
    )?;
    let second = evaluate_step_tapes(
        spec,
        "SCRIPTED_ORACLE_NOT_LEARNED_POLICY",
        replay.trajectory_root,
        &episodes,
    )?;
    if first != second {
        return Err(crate::Error::Contract(
            "evaluator double execution differed".into(),
        ));
    }
    Ok(first)
}

fn benchmark_batches(config: PathBuf) -> Result<CampaignPerformanceReport> {
    let mut metrics = Vec::new();
    for lanes in [1_usize, 32, 128] {
        let mut batch = EnvironmentBatch::open(&config, lanes)?;
        let seeds = (0..lanes as u64).collect::<Vec<_>>();
        let actions = vec![0.0_f32; lanes];
        let cycles = if lanes == 128 { 50 } else { 100 };
        let start = Instant::now();
        for _ in 0..cycles {
            black_box(batch.reset_many(&[], &seeds)?);
        }
        metrics.push(metric(
            "reset_many",
            cycles as f64 * lanes as f64 / start.elapsed().as_secs_f64().max(f64::MIN_POSITIVE),
            "lane_resets_per_second",
            &format!("{lanes}_lanes_one_native_call"),
        ));
        let start = Instant::now();
        for _ in 0..cycles {
            batch.reset_many(&[], &seeds)?;
            black_box(batch.step_many(&actions)?);
        }
        metrics.push(metric(
            "step_many",
            cycles as f64 * lanes as f64 / start.elapsed().as_secs_f64().max(f64::MIN_POSITIVE),
            "lane_steps_per_second",
            &format!("{lanes}_lanes_reset_then_one_step"),
        ));
    }
    Ok(CampaignPerformanceReport { schema_version: "CAMPAIGN_PERFORMANCE_REPORT_V1".into(), metrics,
        limitations: vec!["Lane execution is currently contiguous single-owner sequential Rust; batching removes boundary crossings but is not a parallelism claim".into(),
            "Qualification corpus has one executable market episode; campaign partition episodes are sealed synthetic control-plane fixtures".into(),
            "No learner, optimizer, backward pass, or checkpoint operation was executed".into()] })
}

fn metric(name: &str, value: f64, unit: &str, workload: &str) -> CampaignPerformanceMetric {
    CampaignPerformanceMetric {
        name: name.into(),
        value,
        unit: unit.into(),
        workload: workload.into(),
    }
}

fn double_build(
    root: &Path,
    env: &northstar_rl_core::RlEnvSpec,
    dictionary_hash: Digest,
) -> Result<CampaignDoubleBuildReceipt> {
    let base = root.join("double_rebuild_campaign");
    let first = base.join("first");
    let second = base.join("second");
    std::fs::create_dir_all(&first)?;
    std::fs::create_dir_all(&second)?;
    for directory in [&first, &second] {
        let fixture = build_campaign_fixture(env, dictionary_hash)?;
        write_fixture(directory, &fixture)?;
    }
    let files = vec![
        "partition_tape.json",
        "transform_state.json",
        "learner_spec.json",
        "evaluation_spec.json",
        "experiment_spec.json",
        "campaign_spec.json",
        "planned_run_receipts.json",
        "campaign_receipt.json",
        "policy_artifact_contract.json",
    ];
    let directory_root = |directory: &Path| -> Result<Digest> {
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"northstar-campaign-double-build-v1");
        for name in &files {
            let bytes = std::fs::read(directory.join(name))?;
            hasher.update(name.as_bytes());
            hasher.update(&bytes);
        }
        Ok(Digest(*hasher.finalize().as_bytes()))
    };
    let first_root = directory_root(&first)?;
    let second_root = directory_root(&second)?;
    Ok(CampaignDoubleBuildReceipt {
        schema_version: "CAMPAIGN_DOUBLE_BUILD_RECEIPT_V1".into(),
        first_root,
        second_root,
        byte_identical: first_root == second_root,
        files: files.into_iter().map(str::to_owned).collect(),
    })
}

fn qualification_matrix(rebuild: bool, py: bool) -> QualificationMatrix {
    let mut items = Vec::new();
    for name in [
        "PARTITION_TAPE",
        "PARTITION_IMMUTABILITY",
        "GROUP_AWARE_CHRONOLOGY",
        "HOLDOUT_FIREWALL",
        "TRANSFORM_TRAIN_ONLY",
        "TRANSFORM_REBUILD",
        "LEARNER_SPEC",
        "EXPERIMENT_IDENTITY",
        "EVALUATION_SPEC_PRECOMMIT",
        "EVALUATOR_DETERMINISM",
        "POLICY_ARTIFACT_CONTRACT",
        "CAMPAIGN_RUN_RECEIPTS",
        "MULTI_SEED_PLAN",
        "BATCHED_RUST_ABI",
        "PERFORMANCE_BASELINE",
        "LEARNER_EXECUTION_PROHIBITION",
    ] {
        items.push(item(
            name,
            QualificationStatus::Qualified,
            "INERT_CONTROL_PLANE_CONTRACT_AND_RECEIPT_PASS",
        ));
    }
    items.push(item(
        "DOUBLE_REBUILD",
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
        "BATCHED_PYO3_ABI",
        if py {
            QualificationStatus::Qualified
        } else {
            QualificationStatus::Partial
        },
        if py {
            "PYTHON_BATCH_COMPATIBILITY_RECEIPT_PASS"
        } else {
            "NATIVE_SOURCE_PRESENT_PYTHON_RECEIPT_PENDING"
        },
    ));
    items.sort_by(|a, b| a.name.cmp(&b.name));
    QualificationMatrix {
        project: "FORGE-RL-02".into(),
        surface: "NORTHSTAR_STRATEGY_EXPERIMENT_RUNTIME_V1".into(),
        learner_execution: "PROHIBITED_UNTIL_DEGEN_RL_01".into(),
        items,
    }
}

fn item(name: &str, status: QualificationStatus, reason: &str) -> QualificationItem {
    QualificationItem {
        name: name.into(),
        status,
        reason_code: reason.into(),
        receipts: vec![
            "campaign_double_build_receipt.json".into(),
            "campaign_receipt.json".into(),
        ],
    }
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
    schema!("PARTITION_TAPE_V1", PartitionTape);
    schema!("TRANSFORM_STATE_V1", TransformState);
    schema!("LEARNER_SPEC_V1", LearnerSpec);
    schema!("EXPERIMENT_SPEC_V1", ExperimentSpec);
    schema!("EVALUATION_SPEC_V1", EvaluationSpec);
    schema!("POLICY_ARTIFACT_V1", PolicyArtifact);
    schema!("CAMPAIGN_SPEC_V1", CampaignSpec);
    schema!("CAMPAIGN_RUN_RECEIPT_V1", CampaignRunReceipt);
    schema!("CAMPAIGN_RECEIPT_V1", CampaignReceipt);
    schema!("EVALUATION_RECEIPT_V1", EvaluationReceipt);
    Ok(())
}

fn seal_campaign(root: &Path) -> Result<AuthorityManifest> {
    let mut paths = Vec::new();
    collect(root, root, &mut paths)?;
    paths.retain(|path| {
        let name = path.to_string_lossy().replace('\\', "/");
        !name.starts_with("double_rebuild_campaign/")
            && name != "campaign_authority_manifest.json"
            && name != "NORTHSTAR_STRATEGY_EXPERIMENT_RUNTIME_V1"
    });
    paths.sort();
    let mut entries = Vec::with_capacity(paths.len());
    for relative in paths {
        let bytes = std::fs::read(root.join(&relative))?;
        entries.push(AuthorityManifestEntry {
            path: relative.to_string_lossy().replace('\\', "/"),
            bytes: bytes.len() as u64,
            content_hash: Digest::hash(b"northstar-campaign-artifact-file-v1", &bytes),
            authority: if relative.to_string_lossy().contains("performance") {
                "DIAGNOSTIC".into()
            } else {
                "FORGE_RL_02".into()
            },
        });
    }
    let mut manifest = AuthorityManifest {
        schema_version: "NORTHSTAR_CAMPAIGN_AUTHORITY_MANIFEST_V1".into(),
        surface: "NORTHSTAR_STRATEGY_EXPERIMENT_RUNTIME_V1".into(),
        entries,
        root_identity: Digest::ZERO,
    };
    manifest.root_identity = identity(b"northstar-strategy-experiment-runtime-v1", &manifest)?;
    write_json(root.join("campaign_authority_manifest.json"), &manifest)?;
    std::fs::write(
        root.join("NORTHSTAR_STRATEGY_EXPERIMENT_RUNTIME_V1"),
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

pub fn evaluator_input_hash(steps: &[EnvStepRecord]) -> Result<Digest> {
    Ok(identity(b"northstar-evaluator-input-v1", &steps)?)
}
