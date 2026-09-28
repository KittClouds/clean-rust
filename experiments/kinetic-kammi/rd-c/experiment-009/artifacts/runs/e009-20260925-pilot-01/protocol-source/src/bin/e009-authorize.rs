use std::{env, fs, path::PathBuf};

use rdc_experiment_001::{Action, Evidence, Proposal, State};
use rdc_experiment_002::{
    ActionId, ActionSimulator, Authority, CompiledAuthority, ReceiptSnapshot,
};
use rdc_experiment_009::observer::{ActionOption, HeadThresholds, ObserverOutput, TypedDecision};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AuthorizationInput {
    task_id: String,
    frame_hash_hex: String,
    selected_patch_sha256: Option<String>,
    action_ledger_path: PathBuf,
    actions: Vec<ActionOption>,
    observer_output: ObserverOutput,
    thresholds: HeadThresholds,
    completion_check_passed: bool,
}

#[derive(Debug, Serialize)]
struct AuthorizationResult {
    task_id: String,
    action_choice: Option<u16>,
    typed_decision: String,
    completion_check_passed: bool,
    final_state: String,
    illegal_commits: usize,
    transition_receipts: Vec<ReceiptSnapshot>,
    replay_identity: String,
    replay_state_identical: bool,
    action_id: Option<String>,
    unique_action_effects: usize,
    duplicate_action_effects: usize,
    idempotent_action_reuse: bool,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("e009-authorize: {error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args_os().skip(1);
    let input_path = args.next().ok_or("missing input JSON path")?;
    let output_path = args.next().ok_or("missing output JSON path")?;
    if args.next().is_some() {
        return Err("expected exactly two paths".into());
    }
    let input: AuthorizationInput = serde_json::from_slice(&fs::read(input_path)?)?;
    validate_hash(&input.frame_hash_hex)?;
    if input.task_id.trim().is_empty() {
        return Err("task ID is empty".into());
    }

    let decision = input
        .observer_output
        .compile(&input.actions, input.thresholds);
    let decision_text = match &decision {
        Ok(value) => format!("{value:?}"),
        Err(error) => format!("Rejected({error:?})"),
    };
    let selected = match decision {
        Ok(TypedDecision::Propose { action_id }) => Some(action_id),
        Ok(TypedDecision::Abstain(_)) | Err(_) => None,
    };
    let evidence = Evidence {
        code: 900,
        digest: first_16(&decode_hex_32(&input.frame_hash_hex)?),
    };
    let mut authority = CompiledAuthority::standard();
    let mut proposals = Vec::with_capacity(5);
    let observe = Proposal::new(State::Idle, State::Observing, Action::Observe);
    let decide =
        Proposal::new(State::Observing, State::Deciding, Action::Decide).with_evidence(evidence);
    authority.apply(observe);
    authority.apply(decide);
    proposals.push(observe);
    proposals.push(decide);

    let mut action_id = None;
    let mut unique_action_effects = 0;
    let mut duplicate_action_effects = 0;
    let mut idempotent_action_reuse = false;

    if let Some(choice) = selected {
        let Some(patch_sha256) = input.selected_patch_sha256.as_deref() else {
            return Err("selected action is missing its patch hash".into());
        };
        validate_hash(patch_sha256)?;
        let execute = Proposal::new(State::Deciding, State::Acting, Action::Execute)
            .with_confidence(input.observer_output.applicability_milli)
            .with_evidence(evidence);
        let receipt = authority.apply(execute);
        proposals.push(execute);
        if receipt.authorized_action == Some(Action::Execute) {
            let stable_id = stable_action_id(&input.task_id, choice, patch_sha256);
            let mut simulator = ActionSimulator::create(&input.action_ledger_path)?;
            let effect = simulator.perform(stable_id, Action::Execute)?;
            unique_action_effects = simulator.stats().unique_effects;
            simulator.flush_close()?;

            // SAFETY: this invocation closed the only writer before reopening the ledger.
            let mut resumed = unsafe { ActionSimulator::resume(&input.action_ledger_path)? };
            let reused = resumed.perform(stable_id, Action::Execute)?;
            let replay_stats = resumed.stats();
            duplicate_action_effects = replay_stats.duplicate_effects;
            idempotent_action_reuse = reused.idempotent_reuse;
            resumed.flush_close()?;
            if !idempotent_action_reuse || effect.effect_index != reused.effect_index {
                return Err("stable action ID did not replay idempotently".into());
            }
            action_id = Some(hex(&stable_id.0));

            let verify = Proposal::new(State::Acting, State::Verifying, Action::Verify);
            authority.apply(verify);
            proposals.push(verify);
            let verification = if input.completion_check_passed {
                Proposal::new(State::Verifying, State::Done, Action::Complete)
                    .with_evidence(evidence)
            } else {
                Proposal::new(State::Verifying, State::Failed, Action::Fail)
            };
            authority.apply(verification);
            proposals.push(verification);
        } else {
            let fail = Proposal::new(State::Deciding, State::Failed, Action::Fail);
            authority.apply(fail);
            proposals.push(fail);
        }
    } else {
        let fail = Proposal::new(State::Deciding, State::Failed, Action::Fail);
        authority.apply(fail);
        proposals.push(fail);
    }
    let snapshots: Vec<ReceiptSnapshot> = authority
        .receipts()
        .iter()
        .copied()
        .map(Into::into)
        .collect();

    let mut replay = CompiledAuthority::standard();
    let mut replay_receipts = Vec::with_capacity(proposals.len());
    for proposal in proposals.iter().copied() {
        replay_receipts.push(replay.apply(proposal));
    }
    let replay_snapshots: Vec<ReceiptSnapshot> =
        replay_receipts.into_iter().map(Into::into).collect();
    let replay_state_identical =
        replay.state() == authority.state() && replay_snapshots == snapshots;
    let replay_identity = blake3::hash(&serde_json::to_vec(&snapshots)?)
        .to_hex()
        .to_string();
    let illegal_commits = snapshots
        .iter()
        .filter(|receipt| receipt.rejection.is_some())
        .count();

    let result = AuthorizationResult {
        task_id: input.task_id,
        action_choice: selected,
        typed_decision: decision_text,
        completion_check_passed: input.completion_check_passed,
        final_state: authority.state().label().to_owned(),
        illegal_commits,
        transition_receipts: snapshots,
        replay_identity,
        replay_state_identical,
        action_id,
        unique_action_effects,
        duplicate_action_effects,
        idempotent_action_reuse,
    };
    fs::write(output_path, serde_json::to_vec_pretty(&result)?)?;
    Ok(())
}

fn validate_hash(value: &str) -> Result<(), Box<dyn std::error::Error>> {
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("expected a 64-character hexadecimal hash".into());
    }
    Ok(())
}

fn decode_hex_32(value: &str) -> Result<[u8; 32], Box<dyn std::error::Error>> {
    validate_hash(value)?;
    let mut output = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        output[index] = (hex_nibble(pair[0])? << 4) | hex_nibble(pair[1])?;
    }
    Ok(output)
}

fn hex_nibble(value: u8) -> Result<u8, Box<dyn std::error::Error>> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        b'A'..=b'F' => Ok(value - b'A' + 10),
        _ => Err("invalid hexadecimal digit".into()),
    }
}

fn stable_action_id(task_id: &str, action_id: u16, patch_sha256: &str) -> ActionId {
    let digest = blake3::hash(format!("{task_id}\0{action_id}\0{patch_sha256}").as_bytes());
    let mut stable_id = [0_u8; 16];
    stable_id.copy_from_slice(&digest.as_bytes()[..16]);
    ActionId(stable_id)
}

fn first_16(value: &[u8; 32]) -> [u8; 16] {
    let mut output = [0_u8; 16];
    output.copy_from_slice(&value[..16]);
    output
}

fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write as _;

    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        let _ = write!(output, "{byte:02x}");
    }
    output
}
