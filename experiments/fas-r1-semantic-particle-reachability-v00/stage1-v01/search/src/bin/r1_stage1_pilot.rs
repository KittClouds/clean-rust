#[path = "r1_stage1_pilot/start_state.rs"]
mod start_state;

use hashbrown::HashMap;
use r1_search::{annotate_posthoc, prefix_metrics, PosthocSidecar, PrefixBudget};
use r1_stage1_search::{
    Arm, FrozenProposalPolicyV02, FrozenProposalValueV02, FrozenQTerminalDeltaV05,
    IdentityCompositionV03, MappedSensorExtraction, MergeMode, ProposalMixV03,
    ProposalScoreAuditV03, QDeltaProposalPolicy, RunConfig, SearchAllocationPolicy,
    Stage1RunConfig, TaskPooledIdentityTerminalV07, ValueRefreshPolicy,
    IDENTITY_LINEAR_V03_BINARY_SHA256, Q_TERMINAL_V06_CALIBRATION_BINARY_SHA256,
    Q_TERMINAL_V07_TASK_POOLED_WEIGHT, V_REACH_V02_64_SHA256, V_REACH_V03_SCALED_H_SHA256,
    V_REACH_V05_STRESS_SHA256, V_REACH_V06_STRESS_SHA256,
};
use r1_world::{InferenceTask, Task};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use start_state::{load_search_starts, SearchStartSource};
use std::env;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

const DEFAULT_BUDGET: u64 = 64;
const WIDTH: u16 = 8;
#[derive(Clone, Copy, Serialize)]
struct ArmCondition {
    id: &'static str,
    arm: Arm,
    merge_mode: MergeMode,
    allocation_policy: SearchAllocationPolicy,
}

const ARM_CONDITIONS: [ArmCondition; 15] = [
    ArmCondition {
        id: "depth",
        arm: Arm::Depth,
        merge_mode: MergeMode::None,
        allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
    },
    ArmCondition {
        id: "sampled_depth",
        arm: Arm::SampledDepth,
        merge_mode: MergeMode::None,
        allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
    },
    ArmCondition {
        id: "random_width",
        arm: Arm::RandomWidth,
        merge_mode: MergeMode::None,
        allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
    },
    ArmCondition {
        id: "learned_width",
        arm: Arm::LearnedWidth,
        merge_mode: MergeMode::None,
        allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
    },
    ArmCondition {
        id: "learned_spine128",
        arm: Arm::LearnedWidth,
        merge_mode: MergeMode::None,
        allocation_policy: SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget: 128 },
    },
    ArmCondition {
        id: "learned_spine160",
        arm: Arm::LearnedWidth,
        merge_mode: MergeMode::None,
        allocation_policy: SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget: 160 },
    },
    ArmCondition {
        id: "learned_spine192",
        arm: Arm::LearnedWidth,
        merge_mode: MergeMode::None,
        allocation_policy: SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget: 192 },
    },
    ArmCondition {
        id: "learned_spine224",
        arm: Arm::LearnedWidth,
        merge_mode: MergeMode::None,
        allocation_policy: SearchAllocationPolicy::ProtectedSpineThenWidth { spine_budget: 224 },
    },
    ArmCondition {
        id: "learned_fork192",
        arm: Arm::LearnedWidth,
        merge_mode: MergeMode::None,
        allocation_policy: SearchAllocationPolicy::ForkFromSpineThenWidth { spine_budget: 192 },
    },
    ArmCondition {
        id: "merged_width_assignment",
        arm: Arm::MergedWidth,
        merge_mode: MergeMode::RawAssignment,
        allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
    },
    ArmCondition {
        id: "merged_width_strict_dynamic",
        arm: Arm::MergedWidth,
        merge_mode: MergeMode::StrictDynamicState,
        allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
    },
    ArmCondition {
        id: "canonical_merge",
        arm: Arm::CanonicalMerge,
        merge_mode: MergeMode::CanonicalAssignment,
        allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
    },
    ArmCondition {
        id: "particle",
        arm: Arm::Particle,
        merge_mode: MergeMode::CanonicalAssignment,
        allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
    },
    ArmCondition {
        id: "particle_strict_dynamic",
        arm: Arm::Particle,
        merge_mode: MergeMode::StrictDynamicState,
        allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
    },
    ArmCondition {
        id: "particle_no_merge",
        arm: Arm::Particle,
        merge_mode: MergeMode::None,
        allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
    },
];

#[derive(Deserialize)]
struct SplitManifest {
    family_roster: Vec<SplitRow>,
    #[serde(default)]
    search_starts: Option<SearchStartSource>,
}

#[derive(Deserialize)]
struct SplitRow {
    task_id: String,
    family_id: String,
    split: String,
    #[serde(default)]
    paired_world_id: Option<String>,
    #[serde(default)]
    density_level: Option<String>,
    #[serde(default)]
    start_kind: Option<String>,
}

#[derive(Clone, Serialize)]
struct RunRow {
    condition: String,
    proposal_score_audit: ProposalScoreAuditV03,
    proposal_score_audit_scope: &'static str,
    task_id: String,
    family_id: String,
    split: String,
    paired_world_id: Option<String>,
    density_level: Option<String>,
    start_kind: Option<String>,
    arm: Arm,
    trace_file: String,
    trace_sha256: String,
    posthoc_file: String,
    posthoc_sha256: String,
    selector_file: String,
    selector_sha256: String,
    prefix_file: String,
    prefix_sha256: String,
    manifest: RunArtifactManifest,
    replay_checked: bool,
    replay_passed: bool,
    expansions: u64,
    active_cpu_ns: u64,
    active_gpu_ns: u64,
    wall_ns: u64,
}

#[derive(Clone, Serialize)]
struct RunArtifactManifest {
    #[serde(flatten)]
    stage1: r1_stage1_search::Stage1RunManifest,
    proposal_artifact_id: String,
    proposal_sha256: String,
    proposal_weights_path: Option<String>,
    base_planner_proposal_sha256: String,
    base_planner_proposal_weights_path: Option<String>,
    qdelta_manifest_path: Option<String>,
    qdelta_manifest_sha256: Option<String>,
    qdelta_checkpoint_sha256: Option<String>,
    qdelta_binary_sha256: Option<String>,
    qdelta_weights_path: Option<String>,
    qdelta_beta: Option<f64>,
    v_reach_sha256: String,
    v_reach_weights_path: Option<String>,
}

#[derive(Serialize)]
struct SelectorScoreFile<'a> {
    schema: &'static str,
    trace_id: &'a str,
    score_semantics: &'static str,
    negative_infinity_encoding: &'static str,
    initial_assignment_scores: &'a [f64],
    event_assignment_scores: &'a [f64],
}

#[derive(Serialize)]
struct PrefixRow {
    condition: String,
    task_id: String,
    family_id: String,
    split: String,
    arm: Arm,
    budget_kind: String,
    budget_value: u64,
    completed_expansions: u64,
    reachable_including_initial: bool,
    reachable_excluding_initial: bool,
    selected_valid: bool,
    distinct_valid_classes_reached: u64,
}

#[derive(Serialize)]
struct PilotManifest {
    schema: &'static str,
    status: &'static str,
    mode: &'static str,
    split: String,
    seed_salt: u64,
    task_limit: usize,
    public_task_count: usize,
    selected_task_count: usize,
    transition_budget: u64,
    width_max: u16,
    particle_resample_period: u64,
    particle_minimum_allocation: u64,
    proposal_mode: String,
    learned_sample_temperature: f64,
    value_budget_handling: &'static str,
    value_scoring_policy: &'static str,
    particle_allocation_policy: &'static str,
    stage1_allocation_policy: &'static str,
    timing_scope: &'static str,
    conditions: Vec<ArmCondition>,
    proposal_id: String,
    proposal_sha256: String,
    proposal_weights_path: Option<String>,
    base_planner_proposal_sha256: String,
    base_planner_proposal_weights_path: Option<String>,
    qdelta_manifest_path: Option<String>,
    qdelta_manifest_sha256: Option<String>,
    qdelta_checkpoint_sha256: Option<String>,
    qdelta_binary_sha256: Option<String>,
    qdelta_weights_path: Option<String>,
    qdelta_beta: Option<f64>,
    v_reach_sha256: String,
    v_reach_weights_path: Option<String>,
    v_reach_mode: String,
    identity_sha256: &'static str,
    q_calibration_sha256: &'static str,
    q_selection_mode: &'static str,
    public_tasks_sha256: String,
    private_tasks_sha256: String,
    support_manifest_sha256: String,
    search_start_file_path: Option<String>,
    search_start_file_sha256: Option<String>,
    initial_state_semantics: &'static str,
    sensor_receipt_sha256: String,
    executable_sha256: String,
    skipped_arms: Vec<SkippedArm>,
    run_rows: Vec<RunRow>,
}

#[derive(Serialize)]
struct SkippedArm {
    condition: String,
    task_id: String,
    arm: Arm,
    reason: &'static str,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse(env::args().skip(1))?;
    if args.output.exists() {
        return Err(format!("output already exists: {}", args.output.display()).into());
    }
    fs::create_dir_all(&args.output)?;

    let public_tasks: Vec<InferenceTask> = read_jsonl(&args.public_tasks)?;
    eprintln!("pilot: loaded public tasks");
    let private_tasks: Vec<Task> = read_jsonl(&args.private_tasks)?;
    eprintln!("pilot: loaded private tasks (not passed to inference)");
    let public_task_count = public_tasks.len();
    let private_task_count = private_tasks.len();
    if public_task_count == 0 || public_task_count != private_task_count {
        return Err("public/private task counts must match and be nonzero".into());
    }
    let inference_by_id = public_tasks
        .into_iter()
        .map(|task| (task.id.clone(), task))
        .collect::<HashMap<_, _>>();
    let private_by_id = private_tasks
        .into_iter()
        .map(|task| (task.id.clone(), task))
        .collect::<HashMap<_, _>>();
    if inference_by_id.len() != public_task_count || private_by_id.len() != private_task_count {
        return Err("public or private task file contains duplicate task IDs".into());
    }
    if inference_by_id
        .keys()
        .any(|id| !private_by_id.contains_key(id))
    {
        return Err("public/private task rosters do not match".into());
    }
    let support: SplitManifest = serde_json::from_slice(&fs::read(&args.support_manifest)?)?;
    eprintln!("pilot: loaded support manifest");
    let mut roster_by_task = HashMap::with_capacity(support.family_roster.len());
    for row in support.family_roster {
        if roster_by_task.insert(row.task_id.clone(), row).is_some() {
            return Err("support manifest contains duplicate task IDs".into());
        }
    }
    let split_by_task = roster_by_task
        .iter()
        .map(|(task_id, row)| (task_id.clone(), row.split.clone()))
        .collect::<HashMap<_, _>>();
    if split_by_task.len() != public_task_count
        || split_by_task
            .keys()
            .any(|task_id| !inference_by_id.contains_key(task_id))
    {
        return Err("support manifest roster does not match the task rows".into());
    }
    let loaded_search_starts = load_search_starts(
        args.search_start_file.as_deref(),
        support.search_starts.as_ref(),
        &roster_by_task,
        &inference_by_id,
    )?;
    let search_starts = loaded_search_starts.starts;
    let search_start_sha256 = loaded_search_starts.sha256;

    let extraction =
        MappedSensorExtraction::open(&args.sensor_dir, &args.public_tasks, &args.support_manifest)?;
    eprintln!("pilot: opened mapped sensor extraction");
    let heads = load_heads(&args)?;
    let base_planner_proposal_sha256 = heads.proposal_sha256().to_owned();
    let v_reach_sha256 = heads.value_sha256().to_owned();
    let v_reach_budget_max = heads.value_budget_max();
    let base_planner_proposal_weights_path = resolved_optional_path(&args.proposal_weights)?;
    let v_reach_weights_path = resolved_optional_path(&args.v_reach_weights)?;
    let qdelta_manifest_path = resolved_optional_path(&args.qdelta_manifest)?;
    let qdelta_weights_path = resolved_optional_path(&args.qdelta_weights)?;
    eprintln!("pilot: loaded proposal and reachability heads");
    let mut action_identity = IdentityCompositionV03::load_default()?;
    eprintln!("pilot: loaded action identity");
    let terminal = TaskPooledIdentityTerminalV07::load_default()?;
    eprintln!("pilot: loaded task-pooled terminal selector v07");
    let mut inner_policy = FrozenProposalPolicyV02::new(heads, &mut action_identity, terminal);
    inner_policy.set_proposal_mix(args.proposal_mix);
    let mut policy = attach_qdelta(inner_policy, &args)?;
    if policy.has_qdelta() {
        eprintln!("pilot: loaded frozen V05 Q-delta proposal scorer");
    }
    let qdelta_binary_sha256 = policy
        .has_qdelta()
        .then(|| policy.scorer().binary_sha256().to_owned());
    let qdelta_checkpoint_sha256 = policy
        .has_qdelta()
        .then(|| policy.scorer().checkpoint_sha256().to_owned());
    let qdelta_manifest_sha256 = args
        .qdelta_manifest
        .as_ref()
        .map(|path| sha256(path))
        .transpose()?;
    let proposal_sha256 = qdelta_binary_sha256
        .clone()
        .unwrap_or_else(|| base_planner_proposal_sha256.clone());
    let proposal_weights_path = qdelta_weights_path
        .clone()
        .or_else(|| base_planner_proposal_weights_path.clone());
    let conditions = ARM_CONDITIONS
        .iter()
        .copied()
        .filter(|condition| {
            args.conditions
                .as_ref()
                .is_none_or(|selected| selected.iter().any(|id| id == condition.id))
        })
        .collect::<Vec<_>>();
    if conditions.is_empty() {
        return Err("condition selection resolved to no arms".into());
    }
    let proposal_artifact_id = if let Some(beta) = args.qdelta_beta {
        format!("frozen-v05-qterminal-delta-beta-{beta:.9}")
    } else {
        args.proposal_id
            .clone()
            .unwrap_or_else(|| "frozen-v02-class-balanced-teacher-v02".to_owned())
    };
    let proposal_id = if args.qdelta_beta.is_some() {
        format!("{proposal_artifact_id}+direct_qdelta_delta_c")
    } else if args.proposal_id.is_some() {
        format!("{}+{}", proposal_artifact_id, args.proposal_mix.id())
    } else {
        format!(
            "frozen-v02-class-balanced-teacher-v02+{}",
            args.proposal_mix.id()
        )
    };
    let mut selected_ids = split_by_task
        .iter()
        .filter(|(_, split)| split.as_str() == args.split)
        .map(|(id, _)| id.clone())
        .collect::<Vec<_>>();
    selected_ids.sort();
    selected_ids.truncate(args.limit);
    if selected_ids.is_empty() {
        return Err(format!("split {:?} selected no tasks", args.split).into());
    }
    let selected_task_count = selected_ids.len();

    let mut runs = Vec::new();
    let mut skipped_arms = Vec::new();
    for task_id in selected_ids {
        eprintln!("pilot: task {task_id} begin");
        let inference = inference_by_id
            .get(&task_id)
            .ok_or("support manifest task is absent from public task roster")?;
        let private = private_by_id
            .get(&task_id)
            .ok_or("support manifest task is absent from private task roster")?;
        let split = split_by_task[&task_id].clone();
        let search_start = search_starts.get(&task_id);
        let features = extraction.load_task(inference)?;
        eprintln!("pilot: task {task_id} features loaded");
        policy
            .inner_mut()
            .prepare_bound_task(inference, &features)?;
        policy.prepare_qdelta_task(inference, &features)?;
        eprintln!("pilot: task {task_id} policy prepared");
        for condition in conditions.iter().copied() {
            let arm = condition.arm;
            if condition.merge_mode == MergeMode::CanonicalAssignment
                && !(inference.role_anonymous && inference.k <= 8)
            {
                skipped_arms.push(SkippedArm {
                    condition: condition.id.to_owned(),
                    task_id: task_id.clone(),
                    arm,
                    reason: "canonical merge arms require public role anonymity and k <= 8",
                });
                eprintln!("pilot: task {task_id} skips {arm:?} (ineligible grammar)");
                continue;
            }
            let seed = paired_seed(&task_id) ^ args.seed_salt;
            let mut base = RunConfig::new(arm, args.budget, WIDTH, seed);
            base.latent_dim = 128;
            base.resample_period = args.resample_period;
            base.minimum_particle_budget = args.minimum_particle_allocation;
            let mut config = Stage1RunConfig::from_stage0(base);
            config.initial_assignment = search_starts
                .get(&task_id)
                .map(|start| start.assignment.clone());
            config.merge_mode = condition.merge_mode;
            config.allocation_policy = condition.allocation_policy;
            config.learned_sample_temperature = args.learned_sample_temperature;
            config.value_refresh_policy = if arm != Arm::Particle {
                ValueRefreshPolicy::CachedTransition
            } else if args.resample_only_vreach {
                ValueRefreshPolicy::ResampleBoundary
            } else if args.refresh_vreach {
                ValueRefreshPolicy::EveryExpansion
            } else {
                ValueRefreshPolicy::CachedTransition
            };
            config.proposal_id = proposal_id.clone();
            config.selector_id = format!(
                "identity-task-pooled-ranking-v07-weight-{:.2}",
                Q_TERMINAL_V07_TASK_POOLED_WEIGHT
            );
            config.value_id = if args.v_reach_v06 {
                "stress-v06-vreach-hscale003-neighborhood-starts-budget256".to_owned()
            } else if args.v_reach_v05 {
                "stress-v05-vreach-hscale003-budget256".to_owned()
            } else if args.v_reach_v03 {
                "frozen-v03-vreach-scaled-h-groups-0.1".to_owned()
            } else if args.v_reach_weights.is_some() {
                format!("explicit-v-reach-{}", v_reach_sha256)
            } else {
                "frozen-v02-vreach-budget64".to_owned()
            };

            policy.inner_mut().reset_score_audit();
            let result = r1_stage1_search::run(inference, &features, config.clone(), &mut policy)?;
            eprintln!("pilot: task {task_id} arm {arm:?} finished");
            let trace_name = format!("{task_id}-{}.trace.jsonl", condition.id);
            let trace_path = args.output.join(&trace_name);
            r1_stage1_search::write_stage1_trace_v2(&trace_path, &result)?;

            // Private task and validator enter only after the full trace is closed.
            let sidecar = annotate_posthoc(private, &result.trace)?;
            let sidecar_name = format!("{task_id}-{}.posthoc.json", condition.id);
            let sidecar_path = args.output.join(&sidecar_name);
            write_json(&sidecar_path, &sidecar)?;

            let selector_name = format!("{task_id}-{}.selector.json", condition.id);
            let selector_path = args.output.join(&selector_name);
            write_json(
                &selector_path,
                &SelectorScoreFile {
                    schema: "r1-terminal-ranking-sidecar-v02",
                    trace_id: &result.trace.header.trace_id,
                    score_semantics: "sum of expected satisfaction using task-pooled identity weight 0.75; higher wins",
                    negative_infinity_encoding: "-f64::MAX",
                    initial_assignment_scores: &result.initial_selection_scores,
                    event_assignment_scores: &result.event_selection_scores,
                },
            )?;

            let prefix_name = format!("{task_id}-{}.prefix.jsonl", condition.id);
            let prefix_path = args.output.join(&prefix_name);
            let mut local_prefix = BufWriter::new(File::create(&prefix_path)?);
            for budget in expansion_checkpoints(args.budget) {
                let metrics =
                    prefix_metrics(&result.trace, &sidecar, PrefixBudget::Expansions(budget))?;
                let selected_valid = selected_valid_at_prefix(
                    &result.trace,
                    &result.initial_selection_scores,
                    &result.event_selection_scores,
                    &sidecar,
                    PrefixBudget::Expansions(budget),
                );
                write_prefix(
                    &mut local_prefix,
                    PrefixContext {
                        task: inference,
                        split: split.as_str(),
                        condition: condition.id,
                        arm,
                    },
                    "expansions",
                    budget,
                    metrics,
                    selected_valid,
                )?;
            }
            for cutoff in [
                10_000_000u64,
                25_000_000,
                50_000_000,
                100_000_000,
                250_000_000,
                500_000_000,
                1_000_000_000,
                2_500_000_000,
                5_000_000_000,
                10_000_000_000,
            ] {
                let metrics =
                    prefix_metrics(&result.trace, &sidecar, PrefixBudget::ActiveNs(cutoff))?;
                let selected_valid = selected_valid_at_prefix(
                    &result.trace,
                    &result.initial_selection_scores,
                    &result.event_selection_scores,
                    &sidecar,
                    PrefixBudget::ActiveNs(cutoff),
                );
                write_prefix(
                    &mut local_prefix,
                    PrefixContext {
                        task: inference,
                        split: split.as_str(),
                        condition: condition.id,
                        arm,
                    },
                    "active_ns",
                    cutoff,
                    metrics,
                    selected_valid,
                )?;
                let metrics =
                    prefix_metrics(&result.trace, &sidecar, PrefixBudget::WallNs(cutoff))?;
                let selected_valid = selected_valid_at_prefix(
                    &result.trace,
                    &result.initial_selection_scores,
                    &result.event_selection_scores,
                    &sidecar,
                    PrefixBudget::WallNs(cutoff),
                );
                write_prefix(
                    &mut local_prefix,
                    PrefixContext {
                        task: inference,
                        split: split.as_str(),
                        condition: condition.id,
                        arm,
                    },
                    "wall_ns",
                    cutoff,
                    metrics,
                    selected_valid,
                )?;
            }
            local_prefix.flush()?;
            let replay_checked = args.replay;
            let replay_passed = if args.replay {
                let fresh_heads = load_heads(&args)?;
                let fresh_identity = IdentityCompositionV03::load_default()?;
                let fresh_terminal = TaskPooledIdentityTerminalV07::load_default()?;
                let mut fresh_identity = fresh_identity;
                let mut fresh_inner =
                    FrozenProposalPolicyV02::new(fresh_heads, &mut fresh_identity, fresh_terminal);
                fresh_inner.set_proposal_mix(args.proposal_mix);
                let mut fresh_policy = attach_qdelta(fresh_inner, &args)?;
                fresh_policy
                    .inner_mut()
                    .prepare_bound_task(inference, &features)?;
                fresh_policy.prepare_qdelta_task(inference, &features)?;
                r1_stage1_search::verify_replay(
                    inference,
                    &features,
                    config,
                    &mut fresh_policy,
                    &result,
                )?
                .passed
            } else {
                false
            };
            runs.push(RunRow {
                condition: condition.id.to_owned(),
                proposal_score_audit: policy.inner().score_audit().clone(),
                proposal_score_audit_scope: if policy.has_qdelta() {
                    "base proposal head bypassed; audit is not the active Q-delta scorer"
                } else {
                    "active proposal head"
                },
                task_id: task_id.clone(),
                family_id: inference.family_id.clone(),
                split: split.clone(),
                paired_world_id: search_start.map(|start| start.paired_world_id.clone()),
                density_level: search_start.map(|start| start.density_level.clone()),
                start_kind: search_start.map(|start| start.start_kind.clone()),
                arm,
                trace_sha256: sha256(&trace_path)?,
                posthoc_sha256: sha256(&sidecar_path)?,
                selector_file: selector_name,
                selector_sha256: sha256(&selector_path)?,
                prefix_sha256: sha256(&prefix_path)?,
                trace_file: trace_name,
                posthoc_file: sidecar_name,
                prefix_file: prefix_name,
                manifest: RunArtifactManifest {
                    stage1: result.manifest,
                    proposal_artifact_id: proposal_artifact_id.clone(),
                    proposal_sha256: proposal_sha256.clone(),
                    proposal_weights_path: proposal_weights_path.clone(),
                    base_planner_proposal_sha256: base_planner_proposal_sha256.clone(),
                    base_planner_proposal_weights_path: base_planner_proposal_weights_path.clone(),
                    qdelta_manifest_path: qdelta_manifest_path.clone(),
                    qdelta_manifest_sha256: qdelta_manifest_sha256.clone(),
                    qdelta_checkpoint_sha256: qdelta_checkpoint_sha256.clone(),
                    qdelta_binary_sha256: qdelta_binary_sha256.clone(),
                    qdelta_weights_path: qdelta_weights_path.clone(),
                    qdelta_beta: args.qdelta_beta,
                    v_reach_sha256: v_reach_sha256.clone(),
                    v_reach_weights_path: v_reach_weights_path.clone(),
                },
                replay_checked,
                replay_passed,
                expansions: result.trace.ledger.expansions,
                active_cpu_ns: result.trace.ledger.cpu_active_ns,
                active_gpu_ns: result.trace.ledger.gpu_active_ns,
                wall_ns: result.trace.ledger.end_to_end_wall_ns,
            });
        }
    }
    let manifest = PilotManifest {
        schema: "FAS_R1_STAGE1_ENGINEERING_PILOT_V21",
        status: "COMPLETE",
        mode: "adaptive engineering pilot; not an independent confirmation",
        split: args.split,
        seed_salt: args.seed_salt,
        task_limit: args.limit,
        public_task_count,
        selected_task_count,
        transition_budget: args.budget,
        width_max: WIDTH,
        particle_resample_period: args.resample_period,
        particle_minimum_allocation: args.minimum_particle_allocation,
        proposal_mode: if policy.has_qdelta() {
            "direct_qdelta_delta_c".to_owned()
        } else {
            args.proposal_mix.id().to_owned()
        },
        learned_sample_temperature: args.learned_sample_temperature,
        value_budget_handling: if args.v_reach_v06 || args.v_reach_v05 {
            "stress V_reach v05 normalizes and clamps remaining budget at 256"
        } else if args.v_reach_weights.is_some() {
            if v_reach_budget_max > 64 {
                "explicit V_reach checkpoint normalizes and clamps to its declared horizon"
            } else {
                "explicit V_reach checkpoint uses its declared horizon"
            }
        } else {
            "V_reach /64 input clamps remaining budget to 64; searches above 64 are outside its trained horizon"
        },
        value_scoring_policy: if args.refresh_vreach {
            "same-horizon-live-and-merge-refresh-v01"
        } else if args.resample_only_vreach {
            "resample-boundary-live-and-merge-refresh-v01"
        } else {
            "cached-transition-score-v01"
        },
        particle_allocation_policy: if args.resample_only_vreach {
            "round-robin-between-resample-boundaries-v01"
        } else {
            "per-run manifest; default is greedy max-value after minimum allocation"
        },
        stage1_allocation_policy: "per condition; exact policy and parameters are recorded in conditions and run manifests",
        timing_scope: "scheduler/search only; sensor extraction plus base/Q-delta task preparation excluded",
        conditions,
        proposal_id: proposal_artifact_id,
        proposal_sha256,
        proposal_weights_path,
        base_planner_proposal_sha256,
        base_planner_proposal_weights_path,
        qdelta_manifest_path,
        qdelta_manifest_sha256,
        qdelta_checkpoint_sha256,
        qdelta_binary_sha256,
        qdelta_weights_path,
        qdelta_beta: args.qdelta_beta,
        v_reach_sha256,
        v_reach_weights_path,
        v_reach_mode: if args.v_reach_v06 {
            format!(
                "stress-world v03 fit with solution-neighborhood starts, H scale 0.03, /256 horizon, checkpoint {V_REACH_V06_STRESS_SHA256}"
            )
        } else if args.v_reach_v05 {
            format!(
                "stress-world v03 fit, H scale 0.03, /256 horizon, checkpoint {V_REACH_V05_STRESS_SHA256}"
            )
        } else if args.v_reach_v03 {
            format!("scaled H inputs, H scale 0.1, checkpoint {V_REACH_V03_SCALED_H_SHA256}")
        } else if let Some(expected_sha256) = &args.v_reach_sha256 {
            format!("explicit V_reach checkpoint {expected_sha256}")
        } else {
            format!("frozen v02 /64 checkpoint {V_REACH_V02_64_SHA256}")
        },
        identity_sha256: IDENTITY_LINEAR_V03_BINARY_SHA256,
        q_calibration_sha256: Q_TERMINAL_V06_CALIBRATION_BINARY_SHA256,
        q_selection_mode: "task-pooled expected satisfaction v07; pooled weight 0.75; probability calibration remains frozen v06",
        public_tasks_sha256: sha256(&args.public_tasks)?,
        private_tasks_sha256: sha256(&args.private_tasks)?,
        support_manifest_sha256: sha256(&args.support_manifest)?,
        search_start_file_path: resolved_optional_path(&args.search_start_file)?,
        search_start_file_sha256: search_start_sha256,
        initial_state_semantics: if args.search_start_file.is_some() {
            "explicit public sidecar assignment is the initial state for every arm; seed salt changes action RNG only"
        } else {
            "legacy Stage1 deterministic random initial assignment"
        },
        sensor_receipt_sha256: sha256(&args.sensor_dir.join("receipt.json"))?,
        executable_sha256: sha256(&env::current_exe()?)?,
        skipped_arms,
        run_rows: runs,
    };
    write_json(&args.output.join("pilot-manifest.json"), &manifest)?;
    Ok(())
}

fn expansion_checkpoints(limit: u64) -> Vec<u64> {
    let mut checkpoints = [0, 1, 4, 8, 16, 32, 64, 128, 256, 512]
        .into_iter()
        .filter(|value| *value <= limit)
        .collect::<Vec<_>>();
    if checkpoints.last().copied() != Some(limit) {
        checkpoints.push(limit);
    }
    checkpoints
}

struct PrefixContext<'a> {
    task: &'a InferenceTask,
    split: &'a str,
    condition: &'a str,
    arm: Arm,
}

fn write_prefix(
    writer: &mut impl Write,
    context: PrefixContext<'_>,
    kind: &str,
    value: u64,
    metrics: r1_stage1_search::PrefixMetrics,
    selected_valid: bool,
) -> Result<(), std::io::Error> {
    serde_json::to_writer(
        &mut *writer,
        &PrefixRow {
            condition: context.condition.to_owned(),
            task_id: context.task.id.clone(),
            family_id: context.task.family_id.clone(),
            split: context.split.to_owned(),
            arm: context.arm,
            budget_kind: kind.to_owned(),
            budget_value: value,
            completed_expansions: metrics.completed_expansions,
            reachable_including_initial: metrics.reachability_including_initial,
            reachable_excluding_initial: metrics.reachability_excluding_initial,
            selected_valid,
            distinct_valid_classes_reached: metrics.distinct_valid_classes_reached,
        },
    )?;
    writer.write_all(b"\n")
}

fn selected_valid_at_prefix(
    trace: &r1_stage1_search::RunTrace,
    initial_scores: &[f64],
    event_scores: &[f64],
    labels: &PosthocSidecar,
    prefix: PrefixBudget,
) -> bool {
    let initial_available = match prefix {
        PrefixBudget::Expansions(_) => true,
        PrefixBudget::ActiveNs(limit) => trace.header.initial_completion_active_ns <= limit,
        PrefixBudget::WallNs(limit) => trace.header.initial_completion_wall_ns <= limit,
    };
    let event_count = match prefix {
        PrefixBudget::Expansions(limit) => trace
            .events
            .iter()
            .take_while(|event| event.global_expansion_index <= limit)
            .count(),
        PrefixBudget::ActiveNs(limit) => trace
            .events
            .iter()
            .take_while(|event| event.cumulative_active_ns <= limit)
            .count(),
        PrefixBudget::WallNs(limit) => trace
            .events
            .iter()
            .take_while(|event| event.cumulative_wall_ns <= limit)
            .count(),
    };
    let mut best_score = f64::NEG_INFINITY;
    let mut best_valid = false;
    if initial_available {
        for (index, _) in trace.header.initial_particles.iter().enumerate() {
            let score = initial_scores
                .get(index)
                .copied()
                .unwrap_or(f64::NEG_INFINITY);
            if score > best_score {
                best_score = score;
                best_valid = labels.initial_valid;
            }
        }
    }
    for index in 0..event_count {
        let score = event_scores
            .get(index)
            .copied()
            .unwrap_or(f64::NEG_INFINITY);
        if score > best_score {
            best_score = score;
            best_valid = labels.events.get(index).is_some_and(|label| label.valid);
        }
    }
    best_valid
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<(), Box<dyn std::error::Error>> {
    let bytes = serde_json::to_vec_pretty(value)?;
    fs::write(path, bytes)?;
    Ok(())
}

fn read_jsonl<T: for<'de> Deserialize<'de>>(
    path: &Path,
) -> Result<Vec<T>, Box<dyn std::error::Error>> {
    let input = BufReader::new(File::open(path)?);
    input
        .lines()
        .enumerate()
        .map(|(index, line)| {
            let line = line?;
            serde_json::from_str(&line).map_err(|error| {
                format!("parse {} line {}: {error}", path.display(), index + 1).into()
            })
        })
        .collect()
}

fn sha256(path: &Path) -> Result<String, std::io::Error> {
    let bytes = fs::read(path)?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

fn paired_seed(task_id: &str) -> u64 {
    let digest = Sha256::digest(task_id.as_bytes());
    u64::from_le_bytes(digest[..8].try_into().unwrap_or([0; 8])) ^ 0xF45A_2026_0926_0001
}

struct Args {
    public_tasks: PathBuf,
    private_tasks: PathBuf,
    support_manifest: PathBuf,
    sensor_dir: PathBuf,
    search_start_file: Option<PathBuf>,
    output: PathBuf,
    split: String,
    limit: usize,
    budget: u64,
    resample_period: u64,
    minimum_particle_allocation: u64,
    seed_salt: u64,
    replay: bool,
    proposal_mix: ProposalMixV03,
    learned_sample_temperature: f64,
    proposal_weights: Option<PathBuf>,
    proposal_sha256: Option<String>,
    proposal_id: Option<String>,
    qdelta_manifest: Option<PathBuf>,
    qdelta_weights: Option<PathBuf>,
    qdelta_beta: Option<f64>,
    v_reach_weights: Option<PathBuf>,
    v_reach_sha256: Option<String>,
    conditions: Option<Vec<String>>,
    v_reach_v03: bool,
    v_reach_v05: bool,
    v_reach_v06: bool,
    refresh_vreach: bool,
    resample_only_vreach: bool,
}

impl Args {
    fn parse(mut values: impl Iterator<Item = String>) -> Result<Self, Box<dyn std::error::Error>> {
        let public_tasks = PathBuf::from(values.next().ok_or("missing public tasks JSONL")?);
        let private_tasks = PathBuf::from(values.next().ok_or("missing private tasks JSONL")?);
        let support_manifest = PathBuf::from(values.next().ok_or("missing support manifest")?);
        let sensor_dir = PathBuf::from(values.next().ok_or("missing sensor extraction dir")?);
        let output = PathBuf::from(values.next().ok_or("missing fresh output directory")?);
        let mut search_start_file = None;
        let split = values.next().unwrap_or_else(|| "qualification".to_owned());
        let limit = values
            .next()
            .map(|value| value.parse())
            .transpose()?
            .unwrap_or(8);
        let mut budget = DEFAULT_BUDGET;
        let mut resample_period = 8u64;
        let mut minimum_particle_allocation = 1u64;
        let mut seed_salt = 0u64;
        let mut replay = false;
        let mut proposal_mix = ProposalMixV03::PinnedRawV02;
        let mut learned_sample_temperature = 1.0f64;
        let mut learned_sample_temperature_seen = false;
        let mut proposal_weights = None;
        let mut proposal_sha256 = None;
        let mut proposal_id = None;
        let mut qdelta_manifest = None;
        let mut qdelta_weights = None;
        let mut qdelta_beta = None;
        let mut v_reach_weights = None;
        let mut v_reach_sha256 = None;
        let mut conditions = None;
        let mut v_reach_v03 = false;
        let mut v_reach_v05 = false;
        let mut v_reach_v06 = false;
        let mut refresh_vreach = false;
        let mut resample_only_vreach = false;
        while let Some(option) = values.next() {
            match option.as_str() {
                "--search-start-file" => {
                    if search_start_file.is_some() {
                        return Err("--search-start-file may only be supplied once".into());
                    }
                    search_start_file = Some(PathBuf::from(
                        values.next().ok_or("--search-start-file requires a path")?,
                    ));
                }
                "--replay" => replay = true,
                "--v-reach-v03" => v_reach_v03 = true,
                "--v-reach-v05" => v_reach_v05 = true,
                "--v-reach-v06" => v_reach_v06 = true,
                "--refresh-vreach" => refresh_vreach = true,
                "--particle-resample-only" => resample_only_vreach = true,
                "--proposal-mode" => {
                    proposal_mix = parse_proposal_mix(
                        &values.next().ok_or("--proposal-mode requires a mode")?,
                    )?;
                }
                "--learned-sample-temperature" => {
                    if learned_sample_temperature_seen {
                        return Err("--learned-sample-temperature may only be supplied once".into());
                    }
                    learned_sample_temperature_seen = true;
                    learned_sample_temperature = values
                        .next()
                        .ok_or("--learned-sample-temperature requires a positive number")?
                        .parse()?;
                }
                "--proposal-weights" => {
                    if proposal_weights.is_some() {
                        return Err("--proposal-weights may only be supplied once".into());
                    }
                    proposal_weights = Some(PathBuf::from(
                        values.next().ok_or("--proposal-weights requires a path")?,
                    ));
                }
                "--proposal-sha256" => {
                    if proposal_sha256.is_some() {
                        return Err("--proposal-sha256 may only be supplied once".into());
                    }
                    proposal_sha256 = Some(parse_sha256(
                        "--proposal-sha256",
                        &values.next().ok_or("--proposal-sha256 requires a digest")?,
                    )?);
                }
                "--proposal-id" => {
                    if proposal_id.is_some() {
                        return Err("--proposal-id may only be supplied once".into());
                    }
                    let id = values
                        .next()
                        .ok_or("--proposal-id requires an identifier")?;
                    if id.trim().is_empty() || id.len() > 128 || id.chars().any(char::is_control) {
                        return Err("--proposal-id must be 1-128 visible characters".into());
                    }
                    proposal_id = Some(id);
                }
                "--qdelta-manifest" => {
                    if qdelta_manifest.is_some() {
                        return Err("--qdelta-manifest may only be supplied once".into());
                    }
                    qdelta_manifest = Some(PathBuf::from(
                        values.next().ok_or("--qdelta-manifest requires a path")?,
                    ));
                }
                "--qdelta-weights" => {
                    if qdelta_weights.is_some() {
                        return Err("--qdelta-weights may only be supplied once".into());
                    }
                    qdelta_weights = Some(PathBuf::from(
                        values.next().ok_or("--qdelta-weights requires a path")?,
                    ));
                }
                "--qdelta-beta" => {
                    if qdelta_beta.is_some() {
                        return Err("--qdelta-beta may only be supplied once".into());
                    }
                    qdelta_beta = Some(
                        values
                            .next()
                            .ok_or("--qdelta-beta requires a positive number")?
                            .parse::<f64>()?,
                    );
                }
                "--v-reach-weights" => {
                    if v_reach_weights.is_some() {
                        return Err("--v-reach-weights may only be supplied once".into());
                    }
                    v_reach_weights = Some(PathBuf::from(
                        values.next().ok_or("--v-reach-weights requires a path")?,
                    ));
                }
                "--v-reach-sha256" => {
                    if v_reach_sha256.is_some() {
                        return Err("--v-reach-sha256 may only be supplied once".into());
                    }
                    v_reach_sha256 = Some(parse_sha256(
                        "--v-reach-sha256",
                        &values.next().ok_or("--v-reach-sha256 requires a digest")?,
                    )?);
                }
                "--conditions" => {
                    let parsed = values
                        .next()
                        .ok_or("--conditions requires a comma-separated arm list")?
                        .split(',')
                        .map(str::to_owned)
                        .collect::<Vec<_>>();
                    if parsed.iter().any(String::is_empty) {
                        return Err("--conditions contains an empty arm name".into());
                    }
                    if parsed
                        .iter()
                        .any(|name| !ARM_CONDITIONS.iter().any(|condition| condition.id == name))
                    {
                        return Err("--conditions contains an unknown arm name".into());
                    }
                    let mut unique = parsed.clone();
                    unique.sort();
                    unique.dedup();
                    if unique.len() != parsed.len() {
                        return Err("--conditions contains duplicate arm names".into());
                    }
                    conditions = Some(parsed);
                }
                "--budget" => {
                    budget = values
                        .next()
                        .ok_or("--budget requires a positive integer")?
                        .parse()?;
                }
                "--resample-period" => {
                    resample_period = values
                        .next()
                        .ok_or("--resample-period requires a positive integer")?
                        .parse()?;
                }
                "--minimum-particle-allocation" => {
                    minimum_particle_allocation = values
                        .next()
                        .ok_or("--minimum-particle-allocation requires a positive integer")?
                        .parse()?;
                }
                "--seed-salt" => {
                    seed_salt = values
                        .next()
                        .ok_or("--seed-salt requires a nonnegative integer")?
                        .parse()?;
                }
                _ => return Err(format!("unknown option: {option}").into()),
            }
        }
        if [v_reach_v03, v_reach_v05, v_reach_v06]
            .into_iter()
            .filter(|selected| *selected)
            .count()
            > 1
        {
            return Err("select at most one non-default V_reach checkpoint".into());
        }
        let proposal_option_count = [
            proposal_weights.is_some(),
            proposal_sha256.is_some(),
            proposal_id.is_some(),
        ]
        .into_iter()
        .filter(|present| *present)
        .count();
        if proposal_option_count != 0 && proposal_option_count != 3 {
            return Err(
                "custom proposals require --proposal-weights, --proposal-sha256, and --proposal-id"
                    .into(),
            );
        }
        let qdelta_option_count = [
            qdelta_manifest.is_some(),
            qdelta_weights.is_some(),
            qdelta_beta.is_some(),
        ]
        .into_iter()
        .filter(|present| *present)
        .count();
        if qdelta_option_count != 0 && qdelta_option_count != 3 {
            return Err(
                "Q-delta proposals require --qdelta-manifest, --qdelta-weights, and --qdelta-beta"
                    .into(),
            );
        }
        if qdelta_beta
            .is_some_and(|beta| !beta.is_finite() || beta <= 0.0 || !(beta as f32).is_finite())
        {
            return Err(
                "--qdelta-beta must be finite, positive, and representable as float32".into(),
            );
        }
        if v_reach_weights.is_some() != v_reach_sha256.is_some() {
            return Err(
                "custom V_reach requires both --v-reach-weights and --v-reach-sha256".into(),
            );
        }
        if v_reach_weights.is_some() && (v_reach_v03 || v_reach_v05 || v_reach_v06) {
            return Err(
                "custom V_reach path/hash cannot be combined with --v-reach-v03/v05/v06".into(),
            );
        }
        if refresh_vreach && resample_only_vreach {
            return Err("choose either --refresh-vreach or --particle-resample-only".into());
        }
        if limit == 0
            || budget == 0
            || budget > 4096
            || resample_period == 0
            || minimum_particle_allocation == 0
        {
            return Err(
                "limit, budget, resample period, and minimum particle allocation must be positive; budget maximum is 4096".into(),
            );
        }
        if !learned_sample_temperature.is_finite() || learned_sample_temperature <= 0.0 {
            return Err("--learned-sample-temperature must be finite and positive".into());
        }
        Ok(Self {
            public_tasks,
            private_tasks,
            support_manifest,
            sensor_dir,
            search_start_file,
            output,
            split,
            limit,
            budget,
            resample_period,
            minimum_particle_allocation,
            seed_salt,
            replay,
            proposal_mix,
            learned_sample_temperature,
            proposal_weights,
            proposal_sha256,
            proposal_id,
            qdelta_manifest,
            qdelta_weights,
            qdelta_beta,
            v_reach_weights,
            v_reach_sha256,
            conditions,
            v_reach_v03,
            v_reach_v05,
            v_reach_v06,
            refresh_vreach,
            resample_only_vreach,
        })
    }
}

fn attach_qdelta<P>(
    inner: P,
    args: &Args,
) -> Result<QDeltaProposalPolicy<P>, Box<dyn std::error::Error>> {
    match (
        &args.qdelta_manifest,
        &args.qdelta_weights,
        args.qdelta_beta,
    ) {
        (Some(manifest), Some(weights), Some(beta)) => Ok(QDeltaProposalPolicy::new(
            inner,
            FrozenQTerminalDeltaV05::load(manifest, weights)?,
            beta,
        )?),
        (None, None, None) => Ok(QDeltaProposalPolicy::baseline(inner)),
        _ => Err("incomplete Q-delta proposal configuration".into()),
    }
}

fn parse_sha256(option: &str, value: &str) -> Result<String, Box<dyn std::error::Error>> {
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(format!("{option} must be exactly 64 hexadecimal characters").into());
    }
    Ok(value.to_ascii_lowercase())
}

fn resolved_optional_path(path: &Option<PathBuf>) -> Result<Option<String>, std::io::Error> {
    path.as_ref()
        .map(|value| value.canonicalize().map(|path| path.display().to_string()))
        .transpose()
}

fn load_heads(args: &Args) -> Result<FrozenProposalValueV02, Box<dyn std::error::Error>> {
    if let (Some(value_path), Some(value_sha256)) = (&args.v_reach_weights, &args.v_reach_sha256) {
        let value_path = value_path.canonicalize()?;
        if let (Some(proposal_path), Some(proposal_sha256)) =
            (&args.proposal_weights, &args.proposal_sha256)
        {
            return Ok(FrozenProposalValueV02::load_explicit_heads(
                proposal_path.canonicalize()?,
                proposal_sha256,
                value_path,
                value_sha256,
            )?);
        }
        return Ok(FrozenProposalValueV02::load_explicit_value(
            value_path,
            value_sha256,
        )?);
    }

    if let (Some(proposal_path), Some(proposal_sha256)) =
        (&args.proposal_weights, &args.proposal_sha256)
    {
        let proposal_path = proposal_path.canonicalize()?;
        if args.v_reach_v06 {
            return Ok(FrozenProposalValueV02::load_explicit_proposal_v06(
                proposal_path,
                proposal_sha256,
            )?);
        }
        if args.v_reach_v05 {
            return Ok(FrozenProposalValueV02::load_explicit_proposal_v05(
                proposal_path,
                proposal_sha256,
            )?);
        }
        if args.v_reach_v03 {
            return Ok(FrozenProposalValueV02::load_explicit_proposal_v03(
                proposal_path,
                proposal_sha256,
            )?);
        }
        return Ok(FrozenProposalValueV02::load_explicit_proposal_default(
            proposal_path,
            proposal_sha256,
        )?);
    }

    if args.v_reach_v06 {
        Ok(FrozenProposalValueV02::load_default_v06()?)
    } else if args.v_reach_v05 {
        Ok(FrozenProposalValueV02::load_default_v05()?)
    } else if args.v_reach_v03 {
        Ok(FrozenProposalValueV02::load_default_v03()?)
    } else {
        Ok(FrozenProposalValueV02::load_default()?)
    }
}

fn parse_proposal_mix(value: &str) -> Result<ProposalMixV03, Box<dyn std::error::Error>> {
    match value {
        "pinned_raw_v02" => Ok(ProposalMixV03::PinnedRawV02),
        "base_only_v03" => Ok(ProposalMixV03::BaseOnlyV03),
        "raw_norm_1" => Ok(ProposalMixV03::RawNormalizedV03 { spread_ratio: 1.0 }),
        "incidence_masked_v03" => Ok(ProposalMixV03::IncidenceMaskedV03),
        "incidence_masked_norm_1" => {
            Ok(ProposalMixV03::IncidenceMaskedNormalizedV03 { spread_ratio: 1.0 })
        }
        "incidence_masked_norm_4" => {
            Ok(ProposalMixV03::IncidenceMaskedNormalizedV03 { spread_ratio: 4.0 })
        }
        _ => Err(format!("unknown proposal mode: {value}").into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse_options(options: &[&str]) -> Result<Args, Box<dyn std::error::Error>> {
        let mut values = [
            "public.jsonl",
            "private.jsonl",
            "support.json",
            "sensor-dir",
            "output-dir",
            "qualification",
            "1",
        ]
        .into_iter()
        .map(str::to_owned)
        .collect::<Vec<_>>();
        values.extend(options.iter().map(|value| (*value).to_owned()));
        Args::parse(values.into_iter())
    }

    fn error_text(options: &[&str]) -> String {
        match parse_options(options) {
            Ok(_) => panic!("expected CLI parse failure"),
            Err(error) => error.to_string(),
        }
    }

    #[test]
    fn legacy_cli_keeps_pinned_checkpoint_defaults() {
        let args = parse_options(&[]).unwrap();
        assert!(args.proposal_weights.is_none());
        assert!(args.proposal_sha256.is_none());
        assert!(args.proposal_id.is_none());
        assert!(args.v_reach_weights.is_none());
        assert!(args.v_reach_sha256.is_none());
        assert_eq!(args.proposal_mix.id(), "pinned_raw_v02");
        assert_eq!(args.learned_sample_temperature, 1.0);
    }

    #[test]
    fn learned_sample_temperature_is_explicit_and_validated() {
        let args = parse_options(&["--learned-sample-temperature", "0.17864354564164298"]).unwrap();
        assert_eq!(args.learned_sample_temperature, 0.17864354564164298);
        assert!(error_text(&["--learned-sample-temperature", "0"]).contains("finite and positive"));
        assert!(
            error_text(&["--learned-sample-temperature", "NaN"]).contains("finite and positive")
        );
        assert!(error_text(&[
            "--learned-sample-temperature",
            "1",
            "--learned-sample-temperature",
            "0.5",
        ])
        .contains("may only be supplied once"));
    }

    #[test]
    fn explicit_v04_proposal_and_vreach_pins_parse_together() {
        let expected_proposal_sha = "a".repeat(64);
        let expected_value_sha = "b".repeat(64);
        let args = parse_options(&[
            "--proposal-weights",
            "proposal-weights-v04.json",
            "--proposal-sha256",
            &expected_proposal_sha.to_ascii_uppercase(),
            "--proposal-id",
            "r1-v04-proposal-v01",
            "--proposal-mode",
            "base_only_v03",
            "--v-reach-weights",
            "v-reach-weights-v04.json",
            "--v-reach-sha256",
            &expected_value_sha,
        ])
        .unwrap();
        assert_eq!(
            args.proposal_sha256.as_deref(),
            Some(expected_proposal_sha.as_str())
        );
        assert_eq!(args.proposal_id.as_deref(), Some("r1-v04-proposal-v01"));
        assert_eq!(args.proposal_mix.id(), "base_only_v03");
        assert_eq!(
            args.v_reach_sha256.as_deref(),
            Some(expected_value_sha.as_str())
        );
    }

    #[test]
    fn custom_artifact_options_fail_closed_when_incomplete_or_ambiguous() {
        assert!(error_text(&["--proposal-weights", "proposal.json"])
            .contains("require --proposal-weights, --proposal-sha256, and --proposal-id"));
        assert!(error_text(&["--v-reach-weights", "value.json"])
            .contains("requires both --v-reach-weights and --v-reach-sha256"));
        assert!(error_text(&[
            "--v-reach-weights",
            "value.json",
            "--v-reach-sha256",
            &"c".repeat(64),
            "--v-reach-v06",
        ])
        .contains("cannot be combined with --v-reach-v03/v05/v06"));
        assert!(error_text(&[
            "--proposal-weights",
            "proposal.json",
            "--proposal-sha256",
            "bad-digest",
            "--proposal-id",
            "proposal-v04",
        ])
        .contains("exactly 64 hexadecimal characters"));
    }

    #[test]
    fn qdelta_cli_requires_a_complete_finite_configuration() {
        let args = parse_options(&[
            "--qdelta-manifest",
            "qdelta-manifest.json",
            "--qdelta-weights",
            "qdelta.bin",
            "--qdelta-beta",
            "0.20892961308540386",
        ])
        .unwrap();
        assert_eq!(
            args.qdelta_manifest.as_deref(),
            Some(Path::new("qdelta-manifest.json"))
        );
        assert_eq!(
            args.qdelta_weights.as_deref(),
            Some(Path::new("qdelta.bin"))
        );
        assert_eq!(args.qdelta_beta, Some(0.20892961308540386));

        assert!(error_text(&["--qdelta-manifest", "qdelta-manifest.json"])
            .contains("require --qdelta-manifest, --qdelta-weights, and --qdelta-beta"));
        assert!(error_text(&[
            "--qdelta-manifest",
            "qdelta-manifest.json",
            "--qdelta-weights",
            "qdelta.bin",
            "--qdelta-beta",
            "NaN",
        ])
        .contains("finite, positive"));
        assert!(error_text(&[
            "--qdelta-manifest",
            "qdelta-manifest.json",
            "--qdelta-weights",
            "qdelta.bin",
            "--qdelta-beta",
            "1",
            "--qdelta-beta",
            "2",
        ])
        .contains("may only be supplied once"));
    }

    #[test]
    fn per_run_manifest_serializes_exact_artifact_identity_and_hashes() {
        let manifest = RunArtifactManifest {
            stage1: r1_stage1_search::Stage1RunManifest {
                schema: "r1-stage1-run-manifest-v4".to_owned(),
                arm: Arm::Depth,
                merge_mode: MergeMode::None,
                proposal_id: "r1-v04-proposal-v01+base_only_v03".to_owned(),
                selector_id: "selector-v07".to_owned(),
                value_id: "explicit-v-reach-v04".to_owned(),
                learned_sample_temperature: None,
                selector_surface: "(H,a)".to_owned(),
                value_surface: "(H,a,s,b)".to_owned(),
                value_scoring_policy: "cached-transition-score-v01".to_owned(),
                particle_allocation_policy: "none".to_owned(),
                search_allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
                allocation_trace_semantics: "test".to_owned(),
                value_evaluated: false,
                selector_calls: 0,
                value_calls: 0,
            },
            proposal_artifact_id: "r1-v04-proposal-v01".to_owned(),
            proposal_sha256: "a".repeat(64),
            proposal_weights_path: Some("proposal-weights-v04.json".to_owned()),
            base_planner_proposal_sha256: "c".repeat(64),
            base_planner_proposal_weights_path: Some("base-proposal.json".to_owned()),
            qdelta_manifest_path: None,
            qdelta_manifest_sha256: None,
            qdelta_checkpoint_sha256: None,
            qdelta_binary_sha256: None,
            qdelta_weights_path: None,
            qdelta_beta: None,
            v_reach_sha256: "b".repeat(64),
            v_reach_weights_path: Some("v-reach-weights-v04.json".to_owned()),
        };
        let json = serde_json::to_value(manifest).unwrap();
        assert_eq!(json["proposal_artifact_id"], "r1-v04-proposal-v01");
        assert_eq!(json["proposal_sha256"], "a".repeat(64));
        assert_eq!(json["proposal_weights_path"], "proposal-weights-v04.json");
        assert_eq!(json["proposal_id"], "r1-v04-proposal-v01+base_only_v03");
        assert_eq!(json["v_reach_sha256"], "b".repeat(64));
        assert_eq!(json["v_reach_weights_path"], "v-reach-weights-v04.json");
        assert_eq!(json["base_planner_proposal_sha256"], "c".repeat(64));
        assert_eq!(json["qdelta_beta"], serde_json::Value::Null);
        assert_eq!(json["learned_sample_temperature"], serde_json::Value::Null);
    }
}
