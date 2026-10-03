//! Export the exact frozen Rust proposal scores on V04 train/validation
//! teacher states. This diagnostic never loads private task ASTs or validates
//! assignments; teacher rows must already be restricted to train/validation.

use hashbrown::HashMap;
use r1_stage1_search::{
    Edit, FrozenProposalPolicyV02, FrozenProposalValueV01, FrozenProposalValueV02,
    IdentityCompositionV03, MappedSensorExtraction, PolicyError, PolicyValue, ProposalMixV03,
    SearchPolicy, SelectorInput, SemanticFeatures, TerminalScorer, TransitionInput,
    V_REACH_V03_SCALED_H_SHA256,
};
use r1_world::InferenceTask;
#[path = "r1_v04_proposal_scores_contract.rs"]
mod contract;
use contract::{
    ensure_teacher_edit_order, legal_edits, read_public_tasks, read_support, read_teacher_rows,
    validate_public_roster, TeacherRow, EXPECTED_TRAIN_TASKS, EXPECTED_VALIDATION_TASKS,
    TRAIN_STATES_PER_TASK,
};
use serde::Serialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::env;
use std::error::Error;
use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

const OUTPUT_SCHEMA: &str = "R1_V04_RUNTIME_PROPOSAL_SCORE_ROWS_V01";
const RECEIPT_SCHEMA: &str = "R1_V04_RUNTIME_PROPOSAL_SCORE_RECEIPT_V01";
const V02_V03_VALUE_PATH: &str = r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v19-vreach-scale-v03\v-reach-weights-v03.json";

#[derive(Debug)]
struct Args {
    teacher_targets: PathBuf,
    public_tasks: PathBuf,
    support_manifest: PathBuf,
    sensor_dir: PathBuf,
    proposal_weights: PathBuf,
    output: PathBuf,
}

#[derive(Clone, Debug, Serialize)]
struct ScoreRow {
    schema: &'static str,
    proposal_weights_sha256: String,
    proposal_schema: String,
    task_id: String,
    family_id: String,
    family_split: String,
    state_index: usize,
    edit: EditRecord,
    base_logit: f32,
    delta_c_raw: f32,
    delta_c_incidence_masked: f32,
    /// Present for V02 proposals, which have the matching runtime mixtures.
    #[serde(skip_serializing_if = "Option::is_none")]
    logit_pinned_raw_v02: Option<f32>,
    /// Present for V02 proposals, which have the matching runtime mixtures.
    #[serde(skip_serializing_if = "Option::is_none")]
    logit_incidence_masked_norm_4: Option<f32>,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct EditRecord {
    entity: u16,
    new_role: u8,
}

#[derive(Clone, Debug, Serialize)]
struct FileRecord {
    path: String,
    sha256: String,
    bytes: u64,
}

struct OutputWriter {
    path: PathBuf,
    writer: BufWriter<File>,
    rows: u64,
}

impl OutputWriter {
    fn create(path: &Path) -> Result<Self, Box<dyn Error>> {
        if path.exists() {
            return Err(format!("refusing to overwrite score output {}", path.display()).into());
        }
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let file = OpenOptions::new().write(true).create_new(true).open(path)?;
        Ok(Self {
            path: path.to_owned(),
            writer: BufWriter::new(file),
            rows: 0,
        })
    }

    fn push(&mut self, row: &ScoreRow) -> Result<(), Box<dyn Error>> {
        serde_json::to_writer(&mut self.writer, row)?;
        self.writer.write_all(b"\n")?;
        self.rows += 1;
        Ok(())
    }

    fn finish(mut self) -> Result<(PathBuf, u64, FileRecord), Box<dyn Error>> {
        self.writer.flush()?;
        self.writer.get_ref().sync_all()?;
        drop(self.writer);
        let record = file_record(&self.path)?;
        Ok((self.path, self.rows, record))
    }
}

struct UnusedTerminal;

impl TerminalScorer for UnusedTerminal {
    fn q_terminal(&mut self, _input: SelectorInput<'_>) -> Result<PolicyValue, PolicyError> {
        Err(PolicyError(
            "score exporter never calls Q_terminal".to_owned(),
        ))
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("R1_V04_RUNTIME_PROPOSAL_SCORE_FAILED: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let args = parse_args()?;
    let support = read_support(&args.support_manifest)?;
    let public = read_public_tasks(&args.public_tasks)?;
    validate_public_roster(&support, &public)?;
    let teacher_rows = read_teacher_rows(&args.teacher_targets, &support, &public)?;

    let proposal_record = file_record(&args.proposal_weights)?;
    let proposal_bytes = fs::read(&args.proposal_weights)?;
    let proposal_json: Value = serde_json::from_slice(&proposal_bytes)?;
    let proposal_schema = proposal_json
        .get("schema")
        .and_then(Value::as_str)
        .ok_or("proposal weights omit a string schema")?
        .to_owned();

    let extraction =
        MappedSensorExtraction::open(&args.sensor_dir, &args.public_tasks, &args.support_manifest)?;
    let source_records = runtime_source_records()?;
    let mut output = OutputWriter::create(&args.output)?;

    let runtime = match proposal_schema.as_str() {
        "r1-proposal-weights-v01" => score_v01(
            &args,
            &teacher_rows,
            &public,
            &extraction,
            &proposal_record,
            &proposal_schema,
            &mut output,
        )?,
        "r1-proposal-weights-v02" => score_v02(
            &args,
            &teacher_rows,
            &public,
            &extraction,
            &proposal_record,
            &proposal_schema,
            &mut output,
        )?,
        other => return Err(format!("unsupported proposal schema {other:?}").into()),
    };

    let (output_path, row_count, output_record) = output.finish()?;
    let mut split_rows = HashMap::<String, u64>::new();
    for row in &teacher_rows {
        *split_rows.entry(row.family_split.clone()).or_default() +=
            (public[&row.task_id].n as u64) * (public[&row.task_id].k as u64 - 1);
    }
    let expected_rows = (EXPECTED_TRAIN_TASKS + EXPECTED_VALIDATION_TASKS) as u64
        * TRAIN_STATES_PER_TASK as u64
        * 40;
    if row_count != expected_rows {
        return Err(
            format!("score row count {row_count} differs from expected {expected_rows}").into(),
        );
    }

    let identity_paths = IdentityCompositionV03::default_paths();
    let identity_metadata = file_record(&identity_paths.0)?;
    let identity_binary = file_record(&identity_paths.1)?;
    let sensor_records = sensor_input_records(&args.sensor_dir)?;
    let receipt_path = receipt_path(&output_path);
    if receipt_path.exists() {
        return Err(format!(
            "refusing to overwrite score receipt {}",
            receipt_path.display()
        )
        .into());
    }
    let receipt = json!({
        "schema": RECEIPT_SCHEMA,
        "status": "R1_V04_RUNTIME_PROPOSAL_SCORE_EXPORT_COMPLETE",
        "output_schema": OUTPUT_SCHEMA,
        "row_count": row_count,
        "state_count": teacher_rows.len(),
        "split_row_counts": split_rows,
        "input_contract": "V04 train/validation teacher rows only; any qualification row is rejected before state/target decoding",
        "inputs": {
            "teacher_targets": file_record(&args.teacher_targets)?,
            "public_tasks": file_record(&args.public_tasks)?,
            "support_manifest": file_record(&args.support_manifest)?,
            "sensor_extraction": sensor_records,
            "proposal_weights": proposal_record,
        },
        "identity": {
            "implementation": "IdentityCompositionV03",
            "metadata": identity_metadata,
            "binary": identity_binary,
        },
        "runtime": runtime,
        "source": source_records,
        "output": output_record,
        "output_path": output_path,
    });
    let receipt_bytes = serde_json::to_vec_pretty(&receipt)?;
    let mut receipt_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&receipt_path)?;
    receipt_file.write_all(&receipt_bytes)?;
    receipt_file.write_all(b"\n")?;
    receipt_file.sync_all()?;
    println!("R1_V04_RUNTIME_PROPOSAL_SCORE_EXPORT_COMPLETE");
    println!("rows={row_count}");
    println!("output={}", output_path.display());
    println!("receipt={}", receipt_path.display());
    Ok(())
}

fn score_v01(
    args: &Args,
    rows: &[TeacherRow],
    public: &HashMap<String, InferenceTask>,
    extraction: &MappedSensorExtraction,
    proposal_record: &FileRecord,
    proposal_schema: &str,
    output: &mut OutputWriter,
) -> Result<Value, Box<dyn Error>> {
    let (_, value_path) = FrozenProposalValueV01::default_paths();
    let mut heads = FrozenProposalValueV01::load_from_paths(&args.proposal_weights, &value_path)?;
    if heads.proposal_sha256() != proposal_record.sha256 {
        return Err("V01 runtime loader and proposal file digest disagree".into());
    }
    let value_record = file_record(&value_path)?;
    let mut identity = load_identity()?;
    let mut identity_counts = HashMap::<String, usize>::new();
    let mut feature_cache = HashMap::<String, SemanticFeatures>::with_capacity(public.len());

    for row in rows {
        let task = &public[&row.task_id];
        let features = cached_task_features(&mut feature_cache, &row.task_id, || {
            extraction.load_task(task)
        })?;
        heads.prepare_task(task, features)?;
        identity.prepare_task(&task.id, features)?;
        let candidates = legal_edits(task, &row.assignment)?;
        ensure_teacher_edit_order(row, &candidates)?;
        let (raw, masked) =
            action_deltas(&mut identity, task, features, &row.assignment, &candidates)?;
        let base = heads.score_edits(task, features, &row.assignment, &candidates)?;
        write_state_rows(
            output,
            StateScores {
                teacher: row,
                proposal: proposal_record,
                proposal_schema,
                candidates: &candidates,
                base: &base,
                raw: &raw,
                masked: &masked,
                raw_composed: None,
                masked_norm4_composed: None,
            },
        )?;
        *identity_counts.entry(row.family_split.clone()).or_default() += candidates.len();
    }
    Ok(json!({
        "scorer": "FrozenProposalValueV01",
        "proposal_mix": "base-only; V01 runtime has no action adapter",
        "v_reach_dependency_loaded_for_runtime_head": value_record,
        "composed_v02_logits": "not applicable to V01 checkpoint",
        "identity_delta_counts": identity_counts,
        "proposal_sha256": heads.proposal_sha256(),
        "value_sha256": heads.value_sha256(),
    }))
}

fn score_v02(
    args: &Args,
    rows: &[TeacherRow],
    public: &HashMap<String, InferenceTask>,
    extraction: &MappedSensorExtraction,
    proposal_record: &FileRecord,
    proposal_schema: &str,
    output: &mut OutputWriter,
) -> Result<Value, Box<dyn Error>> {
    let heads = FrozenProposalValueV02::load_explicit_proposal_v03(
        &args.proposal_weights,
        &proposal_record.sha256,
    )?;
    let mut identity = load_identity()?;
    let mut policy = FrozenProposalPolicyV02::new(heads, &mut identity, UnusedTerminal);
    let latent: [f32; 0] = [];
    let mut score_counts = HashMap::<String, usize>::new();
    let mut feature_cache = HashMap::<String, SemanticFeatures>::with_capacity(public.len());

    for row in rows {
        let task = &public[&row.task_id];
        let features = cached_task_features(&mut feature_cache, &row.task_id, || {
            extraction.load_task(task)
        })?;
        policy.prepare_bound_task(task, features)?;
        let candidates = legal_edits(task, &row.assignment)?;
        ensure_teacher_edit_order(row, &candidates)?;
        let (raw, masked) = action_deltas(
            policy.identity_mut(),
            task,
            features,
            &row.assignment,
            &candidates,
        )?;
        policy.set_proposal_mix(ProposalMixV03::BaseOnlyV03);
        let base = policy
            .score_edits(
                TransitionInput {
                    features,
                    task,
                    assignment: &row.assignment,
                    latent_state: &latent,
                    remaining_budget: 256,
                    strategy: r1_stage1_search::ProposalStrategy::LearnedSample,
                },
                &candidates,
            )?
            .logits;
        policy.set_proposal_mix(ProposalMixV03::PinnedRawV02);
        let raw_composed = policy
            .score_edits(
                TransitionInput {
                    features,
                    task,
                    assignment: &row.assignment,
                    latent_state: &latent,
                    remaining_budget: 256,
                    strategy: r1_stage1_search::ProposalStrategy::LearnedSample,
                },
                &candidates,
            )?
            .logits;
        policy.set_proposal_mix(ProposalMixV03::IncidenceMaskedNormalizedV03 { spread_ratio: 4.0 });
        let masked_norm4_composed = policy
            .score_edits(
                TransitionInput {
                    features,
                    task,
                    assignment: &row.assignment,
                    latent_state: &latent,
                    remaining_budget: 256,
                    strategy: r1_stage1_search::ProposalStrategy::LearnedSample,
                },
                &candidates,
            )?
            .logits;
        write_state_rows(
            output,
            StateScores {
                teacher: row,
                proposal: proposal_record,
                proposal_schema,
                candidates: &candidates,
                base: &base,
                raw: &raw,
                masked: &masked,
                raw_composed: Some(&raw_composed),
                masked_norm4_composed: Some(&masked_norm4_composed),
            },
        )?;
        *score_counts.entry(row.family_split.clone()).or_default() += candidates.len();
    }
    Ok(json!({
        "scorer": "FrozenProposalPolicyV02 + runtime ProposalMixV03",
        "proposal_mix_logits": {
            "base_logit": "BaseOnlyV03",
            "logit_pinned_raw_v02": "PinnedRawV02 = base + adapter_logit_bias * delta_c_raw",
            "logit_incidence_masked_norm_4": "IncidenceMaskedNormalizedV03 spread_ratio=4.0",
        },
        "score_counts": score_counts,
        "proposal_sha256": policy.heads().proposal_sha256(),
        "value_sha256": policy.heads().value_sha256(),
        "value_head_path": V02_V03_VALUE_PATH,
        "value_head_sha256_expected": V_REACH_V03_SCALED_H_SHA256,
    }))
}

struct StateScores<'a> {
    teacher: &'a TeacherRow,
    proposal: &'a FileRecord,
    proposal_schema: &'a str,
    candidates: &'a [Edit],
    base: &'a [f32],
    raw: &'a [f32],
    masked: &'a [f32],
    raw_composed: Option<&'a [f32]>,
    masked_norm4_composed: Option<&'a [f32]>,
}

fn write_state_rows(
    output: &mut OutputWriter,
    scores: StateScores<'_>,
) -> Result<(), Box<dyn Error>> {
    let StateScores {
        teacher,
        proposal,
        proposal_schema,
        candidates,
        base,
        raw,
        masked,
        raw_composed,
        masked_norm4_composed,
    } = scores;
    let lengths = [base.len(), raw.len(), masked.len(), candidates.len()];
    if lengths.iter().any(|length| *length != candidates.len())
        || raw_composed.is_some_and(|values| values.len() != candidates.len())
        || masked_norm4_composed.is_some_and(|values| values.len() != candidates.len())
    {
        return Err(format!(
            "score vector lengths differ for {}:{}",
            teacher.task_id, teacher.state_index
        )
        .into());
    }
    for index in 0..candidates.len() {
        let edit = candidates[index];
        output.push(&ScoreRow {
            schema: OUTPUT_SCHEMA,
            proposal_weights_sha256: proposal.sha256.clone(),
            proposal_schema: proposal_schema.to_owned(),
            task_id: teacher.task_id.clone(),
            family_id: teacher.family_id.clone(),
            family_split: teacher.family_split.clone(),
            state_index: teacher.state_index,
            edit: EditRecord {
                entity: edit.entity,
                new_role: edit.new_role,
            },
            base_logit: base[index],
            delta_c_raw: raw[index],
            delta_c_incidence_masked: masked[index],
            logit_pinned_raw_v02: raw_composed.map(|values| values[index]),
            logit_incidence_masked_norm_4: masked_norm4_composed.map(|values| values[index]),
        })?;
    }
    Ok(())
}

fn action_deltas(
    identity: &mut IdentityCompositionV03,
    task: &InferenceTask,
    features: &SemanticFeatures,
    assignment: &[u8],
    candidates: &[Edit],
) -> Result<(Vec<f32>, Vec<f32>), Box<dyn Error>> {
    let raw = identity
        .expected_satisfaction_deltas_for_task(&task.id, features, assignment, candidates, false)?;
    let masked = identity
        .expected_satisfaction_deltas_for_task(&task.id, features, assignment, candidates, true)?;
    let to_f32 = |values: Vec<f64>| -> Result<Vec<f32>, Box<dyn Error>> {
        values
            .into_iter()
            .map(|value| {
                let converted = value as f32;
                if !converted.is_finite() {
                    Err("identity action delta is non-finite after f32 conversion".into())
                } else {
                    Ok(converted)
                }
            })
            .collect()
    };
    Ok((to_f32(raw.deltas)?, to_f32(masked.deltas)?))
}

fn cached_task_features<'a, E>(
    cache: &'a mut HashMap<String, SemanticFeatures>,
    task_id: &str,
    load: impl FnOnce() -> Result<SemanticFeatures, E>,
) -> Result<&'a SemanticFeatures, E> {
    // Runtime caches key prepared state by the feature buffers' pointers.
    if !cache.contains_key(task_id) {
        cache.insert(task_id.to_owned(), load()?);
    }
    Ok(cache
        .get(task_id)
        .expect("feature cache entry is present after insertion"))
}

fn load_identity() -> Result<IdentityCompositionV03, Box<dyn Error>> {
    let (metadata, binary) = IdentityCompositionV03::default_paths();
    Ok(IdentityCompositionV03::load_from_paths(metadata, binary)?)
}

fn sensor_input_records(sensor_dir: &Path) -> Result<Value, Box<dyn Error>> {
    let mut records = serde_json::Map::new();
    for filename in [
        "receipt.json",
        "constraint_H.float32.npy",
        "global_h.float32.npy",
        "rows.jsonl",
    ] {
        let path = sensor_dir.join(filename);
        records.insert(
            filename.to_owned(),
            serde_json::to_value(file_record(&path)?)?,
        );
    }
    Ok(Value::Object(records))
}

fn runtime_source_records() -> Result<Value, Box<dyn Error>> {
    let crate_root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let mut records = serde_json::Map::new();
    for (name, relative_path) in [
        ("score_exporter", "src/bin/r1_v04_proposal_scores.rs"),
        (
            "input_contract",
            "src/bin/r1_v04_proposal_scores_contract.rs",
        ),
        ("policy_runtime", "src/policy_v02.rs"),
        ("proposal_runtime", "src/inference_v02.rs"),
        ("identity_runtime", "src/terminal.rs"),
        ("sensor_runtime", "src/feature_io.rs"),
        ("crate_manifest", "Cargo.toml"),
        ("crate_lock", "Cargo.lock"),
    ] {
        records.insert(
            name.to_owned(),
            serde_json::to_value(file_record(&crate_root.join(relative_path))?)?,
        );
    }
    Ok(Value::Object(records))
}

fn receipt_path(output: &Path) -> PathBuf {
    let mut name = output.as_os_str().to_owned();
    name.push(".receipt.json");
    PathBuf::from(name)
}

fn file_record(path: &Path) -> Result<FileRecord, Box<dyn Error>> {
    let path = path.canonicalize()?;
    let bytes = fs::read(&path)?;
    Ok(FileRecord {
        path: path.display().to_string(),
        sha256: hex(&Sha256::digest(&bytes)),
        bytes: bytes.len() as u64,
    })
}

fn hex(bytes: &[u8]) -> String {
    let mut value = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(value, "{byte:02x}");
    }
    value
}

fn parse_args() -> Result<Args, Box<dyn Error>> {
    let mut values = env::args().skip(1);
    let mut parsed = HashMap::<String, String>::new();
    while let Some(flag) = values.next() {
        if !flag.starts_with("--") {
            return Err(format!("unexpected argument {flag:?}").into());
        }
        let value = values
            .next()
            .ok_or_else(|| format!("{flag} requires a path"))?;
        if parsed.insert(flag.clone(), value).is_some() {
            return Err(format!("duplicate argument {flag}").into());
        }
    }
    let take_path = |name: &str| -> Result<PathBuf, Box<dyn Error>> {
        parsed
            .get(name)
            .map(PathBuf::from)
            .ok_or_else(|| format!("missing required argument {name}").into())
    };
    for key in parsed.keys() {
        if !matches!(
            key.as_str(),
            "--teacher-targets"
                | "--public-tasks"
                | "--support-manifest"
                | "--sensor-dir"
                | "--proposal-weights"
                | "--output"
        ) {
            return Err(format!("unknown argument {key}").into());
        }
    }
    Ok(Args {
        teacher_targets: take_path("--teacher-targets")?,
        public_tasks: take_path("--public-tasks")?,
        support_manifest: take_path("--support-manifest")?,
        sensor_dir: take_path("--sensor-dir")?,
        proposal_weights: take_path("--proposal-weights")?,
        output: take_path("--output")?,
    })
}

#[cfg(test)]
mod runtime_tests {
    use super::*;
    use std::cell::Cell;

    fn test_features() -> SemanticFeatures {
        SemanticFeatures {
            hidden_dim: 1,
            constraint_count: 1,
            entity_count: 1,
            role_count: 1,
            constraint_embeddings: vec![1.0].into_boxed_slice(),
            global_embedding: vec![2.0].into_boxed_slice(),
            constraint_mask: vec![1].into_boxed_slice(),
            entity_incidence: vec![1].into_boxed_slice(),
            role_incidence: vec![1].into_boxed_slice(),
            entity_mask: vec![1].into_boxed_slice(),
            role_mask: vec![1].into_boxed_slice(),
        }
    }

    fn feature_buffer_pointers(features: &SemanticFeatures) -> [usize; 7] {
        [
            features.constraint_embeddings.as_ptr() as usize,
            features.global_embedding.as_ptr() as usize,
            features.constraint_mask.as_ptr() as usize,
            features.entity_incidence.as_ptr() as usize,
            features.role_incidence.as_ptr() as usize,
            features.entity_mask.as_ptr() as usize,
            features.role_mask.as_ptr() as usize,
        ]
    }

    #[test]
    fn repeated_teacher_states_reuse_the_same_feature_buffers() {
        let mut cache = HashMap::with_capacity(1);
        let load_count = Cell::new(0);
        let first_pointers = {
            let features = cached_task_features(&mut cache, "task", || {
                load_count.set(load_count.get() + 1);
                Ok::<_, ()>(test_features())
            })
            .unwrap();
            feature_buffer_pointers(features)
        };
        let second_pointers = {
            let features = cached_task_features(&mut cache, "task", || {
                load_count.set(load_count.get() + 1);
                Ok::<_, ()>(test_features())
            })
            .unwrap();
            feature_buffer_pointers(features)
        };

        assert_eq!(load_count.get(), 1);
        assert_eq!(first_pointers, second_pointers);
    }
}
