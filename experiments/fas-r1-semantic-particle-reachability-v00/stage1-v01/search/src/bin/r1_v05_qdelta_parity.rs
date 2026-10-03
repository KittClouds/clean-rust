//! Train/validation-only parity replay for the frozen V05 Q-terminal delta.

use r1_stage1_search::{
    Edit, FrozenQTerminalDeltaV05, MappedSensorExtraction, PolicyCosts, PolicyError,
    PolicyLatentUpdate, PolicyScores, PolicyValue, ProposalStrategy, QDeltaProposalPolicy,
    SearchPolicy, SelectorInput, SemanticFeatures, TransitionInput, ValueInput,
};
use r1_world::InferenceTask;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};

#[derive(Deserialize)]
struct FilePin {
    sha256: String,
    bytes: u64,
}

#[derive(Deserialize)]
struct BundleOutputs {
    public_tasks: FilePin,
    support_manifest: FilePin,
    python_predictions: FilePin,
    sanitized_states: FilePin,
}

#[derive(Deserialize)]
struct BundleManifest {
    schema: String,
    status: String,
    qdelta_beta: f64,
    outputs: BundleOutputs,
    train_validation_only: bool,
    qualification_labels_read: bool,
}

#[derive(Deserialize)]
struct StateRow {
    task_id: String,
    state_index: u32,
    split: String,
    assignment: Vec<u8>,
}

#[derive(Deserialize)]
struct PredictionRow {
    task_id: String,
    state_index: u32,
    #[serde(rename = "predicted_delta_satisfied")]
    delta: Vec<f64>,
    #[serde(rename = "qterminal_delta_proposal")]
    proposal: Vec<f64>,
}

struct NoopPolicy;

impl SearchPolicy for NoopPolicy {
    fn score_edits(
        &mut self,
        _input: TransitionInput<'_>,
        _candidates: &[Edit],
    ) -> Result<PolicyScores, PolicyError> {
        Err(PolicyError(
            "wrapped scorer must be bypassed in parity".to_owned(),
        ))
    }

    fn advance_latent(
        &mut self,
        input: TransitionInput<'_>,
        _selected: Edit,
    ) -> Result<PolicyLatentUpdate, PolicyError> {
        Ok(PolicyLatentUpdate {
            next_state: input.latent_state.to_vec(),
            costs: PolicyCosts::default(),
        })
    }

    fn q_terminal(&mut self, _input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError> {
        Ok(PolicyValue::default())
    }

    fn v_reach(&mut self, _input: ValueInput<'_>) -> Result<PolicyValue, PolicyError> {
        Ok(PolicyValue::default())
    }
}

#[derive(Default)]
struct ErrorStats {
    count: u64,
    sum_abs: f64,
    sum_square: f64,
    max_abs: f64,
}

impl ErrorStats {
    fn add(&mut self, actual: f64, expected: f64) {
        let error = (actual - expected).abs();
        self.count += 1;
        self.sum_abs += error;
        self.sum_square += error * error;
        self.max_abs = self.max_abs.max(error);
    }

    fn report(&self) -> serde_json::Value {
        serde_json::json!({
            "count": self.count,
            "mae": self.sum_abs / self.count.max(1) as f64,
            "rmse": (self.sum_square / self.count.max(1) as f64).sqrt(),
            "max_abs": self.max_abs,
        })
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("R1_V05_QDELTA_PARITY_FAILED: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args = parse_args()?;
    let bundle_dir = args.bundle.canonicalize()?;
    let bundle_path = bundle_dir.join("bundle-manifest-v01.json");
    let bundle: BundleManifest = serde_json::from_slice(&fs::read(&bundle_path)?)?;
    if bundle.schema != "R1_V05_QDELTA_RUST_PARITY_BUNDLE_V01"
        || bundle.status != "TRAIN_VALIDATION_PARITY_BUNDLE_READY"
        || !bundle.train_validation_only
        || bundle.qualification_labels_read
        || !bundle.qdelta_beta.is_finite()
        || bundle.qdelta_beta <= 0.0
    {
        return Err("unexpected or out-of-scope parity bundle manifest".into());
    }

    let public_tasks = bundle_dir.join("public-tasks-trainval.jsonl");
    let support = bundle_dir.join("support-trainval.json");
    let predictions_path = bundle_dir.join("python-predictions-trainval.jsonl");
    let states_path = bundle_dir.join("states-trainval.jsonl");
    verify_file(&public_tasks, &bundle.outputs.public_tasks)?;
    verify_file(&support, &bundle.outputs.support_manifest)?;
    verify_file(&predictions_path, &bundle.outputs.python_predictions)?;
    verify_file(&states_path, &bundle.outputs.sanitized_states)?;

    let tasks = read_tasks(&public_tasks)?;
    let mut tasks_by_id = HashMap::with_capacity(tasks.len());
    for task in tasks {
        if tasks_by_id.insert(task.id.clone(), task).is_some() {
            return Err("duplicate public task id in parity view".into());
        }
    }
    let feature_store =
        MappedSensorExtraction::open(bundle_dir.join("features"), &public_tasks, &support)?;
    let scorer = FrozenQTerminalDeltaV05::load(&args.model_manifest, &args.weights)?;
    let mut policy = QDeltaProposalPolicy::new(NoopPolicy, scorer, bundle.qdelta_beta)?;
    let predictions = read_predictions(&predictions_path)?;
    let states = read_states(&states_path)?;
    if states.len() != 2_560 || predictions.len() != states.len() {
        return Err(format!(
            "expected 2560 aligned states/predictions, got {}/{}",
            states.len(),
            predictions.len()
        )
        .into());
    }

    let mut raw_delta_error = ErrorStats::default();
    let mut proposal_probability_error = ErrorStats::default();
    let mut top_margin_error = ErrorStats::default();
    let mut top_action_matches = 0u64;
    let mut stable_top_action_matches = 0u64;
    let mut stable_top_action_states = 0u64;
    let mut near_tie_mismatches = 0u64;
    let mut sign_matches = 0u64;
    let mut non_near_zero_sign_matches = 0u64;
    let mut non_near_zero_sign_actions = 0u64;
    let mut clause_logits_scored = 0u64;
    let mut total_actions = 0u64;
    let mut split_states = HashMap::<String, u64>::new();
    let mut seen = HashMap::with_capacity(states.len());
    let mut current_task_id = String::new();
    let mut current_features: Option<SemanticFeatures> = None;
    for state in &states {
        if state.split != "train" && state.split != "validation" {
            return Err(format!(
                "state {} has unsupported split {:?}",
                state.task_id, state.split
            )
            .into());
        }
        let key = (state.task_id.as_str(), state.state_index);
        if seen.insert(key, ()).is_some() {
            return Err(format!(
                "duplicate state key {}/{}",
                state.task_id, state.state_index
            )
            .into());
        }
        let task = tasks_by_id
            .get(&state.task_id)
            .ok_or_else(|| format!("state references absent public task {}", state.task_id))?;
        let prediction_key = (state.task_id.clone(), state.state_index);
        let expected = predictions.get(&prediction_key).ok_or_else(|| {
            format!(
                "Python predictions omit {}/{}",
                state.task_id, state.state_index
            )
        })?;
        if state.assignment.len() != usize::from(task.n)
            || state.assignment.iter().any(|role| *role >= task.k)
        {
            return Err(format!(
                "invalid assignment in {}/{}",
                state.task_id, state.state_index
            )
            .into());
        }
        if expected.delta.len() != 40 || expected.proposal.len() != 40 {
            return Err(format!(
                "expected 40 actions in {}/{}",
                state.task_id, state.state_index
            )
            .into());
        }
        if current_task_id != state.task_id {
            current_features = Some(feature_store.load_task(task)?);
            current_task_id.clone_from(&state.task_id);
        }
        let features = current_features
            .as_ref()
            .ok_or("parity feature cache lost its current task")?;
        let mut candidates = Vec::with_capacity(40);
        for (entity, old_role) in state.assignment.iter().copied().enumerate() {
            for new_role in 0..task.k {
                if new_role != old_role {
                    candidates.push(Edit {
                        entity: u16::try_from(entity)?,
                        new_role,
                    });
                }
            }
        }
        if candidates.len() != 40 {
            return Err(format!(
                "task {0} has {1} candidate edits, expected 40",
                task.id,
                candidates.len()
            )
            .into());
        }
        let scores = policy.score_edits(
            TransitionInput {
                features,
                task,
                assignment: &state.assignment,
                latent_state: &[],
                remaining_budget: 0,
                strategy: ProposalStrategy::LearnedSample,
            },
            &candidates,
        )?;
        clause_logits_scored += scores.costs.logits_scored;
        if scores.logits.len() != expected.delta.len() {
            return Err("Rust action order/length differs from Python prediction".into());
        }
        let beta32 = f64::from(policy.beta());
        let actual: Vec<f64> = scores
            .logits
            .iter()
            .map(|logit| f64::from(*logit) / beta32)
            .collect();
        let rust_probabilities = softmax_logits(&scores.logits)?;
        let rust_top = argmax_f32(&scores.logits);
        let python_top = argmax_f64(&expected.delta);
        top_action_matches += u64::from(rust_top == python_top);
        let rust_margin = top_two_margin_f32(&scores.logits) / beta32;
        let python_margin = top_two_margin_f64(&expected.delta);
        top_margin_error.add(rust_margin, python_margin);
        let near_tie = rust_margin <= 1e-5 || python_margin <= 1e-5;
        near_tie_mismatches += u64::from(near_tie && rust_top != python_top);
        if !near_tie {
            stable_top_action_states += 1;
            stable_top_action_matches += u64::from(rust_top == python_top);
        }
        for index in 0..actual.len() {
            let score = actual[index];
            let python_delta = expected.delta[index];
            raw_delta_error.add(score, python_delta);
            proposal_probability_error.add(rust_probabilities[index], expected.proposal[index]);
            sign_matches += u64::from(score.signum() == python_delta.signum());
            if python_delta.abs() > 1e-5 {
                non_near_zero_sign_actions += 1;
                non_near_zero_sign_matches += u64::from(score.signum() == python_delta.signum());
            }
            total_actions += 1;
        }
        *split_states.entry(state.split.clone()).or_default() += 1;
    }
    if seen.len() != predictions.len() {
        return Err("Python prediction roster contains unmatched states".into());
    }

    let report = serde_json::json!({
        "schema": "R1_V05_QDELTA_RUST_PARITY_REPORT_V01",
        "status": "TRAIN_VALIDATION_PARITY_MEASURED",
        "scope": "train and validation only; no qualification or test labels read",
        "states": states.len(),
        "actions": total_actions,
        "states_by_split": split_states,
        "beta": bundle.qdelta_beta,
        "raw_delta_error": raw_delta_error.report(),
        "proposal_probability_error": proposal_probability_error.report(),
        "top_two_margin_error": top_margin_error.report(),
        "top_action_agreement": top_action_matches as f64 / states.len() as f64,
        "top_action_agreement_outside_1e_5_ties": stable_top_action_matches as f64
            / stable_top_action_states.max(1) as f64,
        "stable_top_action_states": stable_top_action_states,
        "top_action_mismatches": states.len() as u64 - top_action_matches,
        "stable_top_action_mismatches": stable_top_action_states - stable_top_action_matches,
        "near_tie_mismatches": near_tie_mismatches,
        "sign_agreement": sign_matches as f64 / total_actions as f64,
        "sign_agreement_when_python_abs_delta_gt_1e_5": non_near_zero_sign_matches as f64
            / non_near_zero_sign_actions.max(1) as f64,
        "non_near_zero_sign_actions": non_near_zero_sign_actions,
        "model_checkpoint_sha256": policy.scorer().checkpoint_sha256(),
        "weights_binary_sha256": policy.scorer().binary_sha256(),
        "weights_manifest_sha256": sha256_file(&args.model_manifest)?,
        "clause_logits_scored": clause_logits_scored,
        "bundle_manifest_sha256": sha256_file(&bundle_path)?,
        "python_predictions_sha256": bundle.outputs.python_predictions.sha256,
        "rust_executable_sha256": sha256_file(&std::env::current_exe()?)?,
        "parity_thresholds": {
            "delta_rmse": 1e-4,
            "delta_max_abs": 1e-3,
            "proposal_probability_mae": 1e-6,
            "stable_top_action_agreement": 1.0,
            "near_tie_epsilon_delta": 1e-5,
        },
        "within_thresholds": {
            "delta_rmse": ((raw_delta_error.sum_square / raw_delta_error.count.max(1) as f64).sqrt() < 1e-4),
            "delta_max_abs": (raw_delta_error.max_abs < 1e-3),
            "proposal_probability_mae": ((proposal_probability_error.sum_abs / proposal_probability_error.count.max(1) as f64) < 1e-6),
            "stable_top_action_agreement": (stable_top_action_matches == stable_top_action_states),
        },
    });
    let output = args.output;
    fs::create_dir(&output)?;
    let report_path = output.join("parity-report-v01.json");
    fs::write(&report_path, serde_json::to_vec_pretty(&report)?)?;
    println!(
        "TRAIN_VALIDATION_PARITY_MEASURED states={} actions={} report={}",
        states.len(),
        total_actions,
        report_path.display()
    );
    Ok(())
}

fn read_tasks(path: &Path) -> Result<Vec<InferenceTask>, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mut tasks = Vec::new();
    for (index, line) in BufReader::new(file).lines().enumerate() {
        let line = line?;
        if !line.trim().is_empty() {
            tasks.push(
                serde_json::from_str(&line)
                    .map_err(|error| format!("parse public task line {}: {error}", index + 1))?,
            );
        }
    }
    Ok(tasks)
}

fn read_states(path: &Path) -> Result<Vec<StateRow>, Box<dyn std::error::Error>> {
    read_jsonl(path)
}

fn read_predictions(
    path: &Path,
) -> Result<HashMap<(String, u32), PredictionRow>, Box<dyn std::error::Error>> {
    let rows: Vec<PredictionRow> = read_jsonl(path)?;
    let mut predictions = HashMap::with_capacity(rows.len());
    for row in rows {
        let key = (row.task_id.clone(), row.state_index);
        if predictions.insert(key, row).is_some() {
            return Err("duplicate Python prediction key".into());
        }
    }
    Ok(predictions)
}

fn read_jsonl<T: for<'de> Deserialize<'de>>(
    path: &Path,
) -> Result<Vec<T>, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mut rows = Vec::new();
    for (index, line) in BufReader::new(file).lines().enumerate() {
        let line = line?;
        if !line.trim().is_empty() {
            rows.push(serde_json::from_str(&line).map_err(|error| {
                format!("parse {} line {}: {error}", path.display(), index + 1)
            })?);
        }
    }
    Ok(rows)
}

fn verify_file(path: &Path, expected: &FilePin) -> Result<(), Box<dyn std::error::Error>> {
    let metadata = path.metadata()?;
    if metadata.len() != expected.bytes || sha256_file(path)? != expected.sha256 {
        return Err(format!(
            "bundle file failed hash/size verification: {}",
            path.display()
        )
        .into());
    }
    Ok(())
}

fn sha256_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut file = File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        use std::io::Read;
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn softmax_logits(scores: &[f32]) -> Result<Vec<f64>, Box<dyn std::error::Error>> {
    let logits: Vec<f64> = scores.iter().map(|score| f64::from(*score)).collect();
    let maximum = logits.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let mut probabilities: Vec<f64> = logits.iter().map(|score| (score - maximum).exp()).collect();
    let total = probabilities.iter().sum::<f64>();
    if !total.is_finite() || total <= 0.0 {
        return Err("proposal softmax could not normalize".into());
    }
    for probability in &mut probabilities {
        *probability /= total;
    }
    Ok(probabilities)
}

fn argmax_f32(scores: &[f32]) -> usize {
    (1..scores.len()).fold(0, |best, index| {
        if scores[index].total_cmp(&scores[best]).is_gt() {
            index
        } else {
            best
        }
    })
}

fn argmax_f64(scores: &[f64]) -> usize {
    (1..scores.len()).fold(0, |best, index| {
        if scores[index].total_cmp(&scores[best]).is_gt() {
            index
        } else {
            best
        }
    })
}

fn top_two_margin_f32(scores: &[f32]) -> f64 {
    let mut best = f32::NEG_INFINITY;
    let mut second = f32::NEG_INFINITY;
    for score in scores.iter().copied() {
        if score > best {
            second = best;
            best = score;
        } else if score > second {
            second = score;
        }
    }
    f64::from(best - second)
}

fn top_two_margin_f64(scores: &[f64]) -> f64 {
    let mut best = f64::NEG_INFINITY;
    let mut second = f64::NEG_INFINITY;
    for score in scores.iter().copied() {
        if score > best {
            second = best;
            best = score;
        } else if score > second {
            second = score;
        }
    }
    best - second
}

fn parse_args() -> Result<Args, Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let mut values = HashMap::<String, PathBuf>::new();
    while let Some(flag) = args.next() {
        let flag = flag.to_string_lossy().into_owned();
        let value = args
            .next()
            .ok_or_else(|| format!("{flag} requires a path"))?;
        values.insert(flag, PathBuf::from(value));
    }
    let take = |name: &str| -> Result<PathBuf, Box<dyn std::error::Error>> {
        values
            .get(name)
            .cloned()
            .ok_or_else(|| format!("missing {name}").into())
    };
    Ok(Args {
        bundle: take("--bundle")?,
        model_manifest: take("--model-manifest")?,
        weights: take("--weights")?,
        output: take("--output")?,
    })
}

struct Args {
    bundle: PathBuf,
    model_manifest: PathBuf,
    weights: PathBuf,
    output: PathBuf,
}
