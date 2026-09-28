use std::{env, fs, path::PathBuf};

use rdc_e011_runtime_integration::{
    PresentationBinding, PresentedOption, hex_digest, parse_hex_digest, resolve_response,
};
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
    frame_digest_hex: String,
    request_id_hex: String,
    response_request_id_hex: String,
    request_receipt_digest_hex: String,
    response_receipt_digest_hex: String,
    presentation_receipt_hex: String,
    action_ledger_path: PathBuf,
    ordered_options: Vec<PresentedOption>,
    observer_output: ObserverOutput,
    thresholds: HeadThresholds,
    completion_check_passed: bool,
}

#[derive(Debug, Serialize)]
struct AuthorizationResult {
    task_id: String,
    presentation_verified: bool,
    presentation_rejection: Option<String>,
    safe_fallback: Option<&'static str>,
    request_id_hex: String,
    receipt_digest_hex: String,
    action_choice: Option<u16>,
    selected_patch_sha256: Option<String>,
    typed_decision: String,
    completion_check_passed: bool,
    final_state: String,
    illegal_commits: usize,
    rejected_transitions: usize,
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
        eprintln!("e011-authorize: {error}");
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
    if input.task_id.trim().is_empty() {
        return Err("task ID is empty".into());
    }

    let task_digest = parse_hex_digest(&input.frame_digest_hex)?;
    let request_id = parse_hex_digest(&input.request_id_hex)?;
    let response_request_id = parse_hex_digest(&input.response_request_id_hex)?;
    let request_receipt_digest = parse_hex_digest(&input.request_receipt_digest_hex)?;
    let response_receipt_digest = parse_hex_digest(&input.response_receipt_digest_hex)?;
    let receipt = decode_hex(&input.presentation_receipt_hex)?;
    let echoed_request_id = request_id == response_request_id;
    let decision = input.observer_output.compile(
        &input
            .ordered_options
            .iter()
            .map(|option| option.action)
            .collect::<Vec<ActionOption>>(),
        input.thresholds,
    );
    let proposal = match decision {
        Ok(TypedDecision::Propose { action_id }) => Some(action_id),
        Ok(TypedDecision::Abstain(_)) | Err(_) => None,
    };
    let resolved = if echoed_request_id {
        resolve_response(
            PresentationBinding {
                task_digest,
                receipt: &receipt,
                request_receipt_digest,
                response_receipt_digest,
                request_id,
                response_request_id,
            },
            &input.ordered_options,
            proposal,
        )
    } else {
        Err(rdc_e011_runtime_integration::PresentationRuntimeError::RequestResponseReceiptMismatch)
    };
    let (presentation_verified, presentation_rejection, selected_option) = match resolved {
        Ok(option) => (true, None, option),
        Err(error) => (false, Some(error.to_string()), None),
    };
    let compiled_decision = if !presentation_verified {
        format!(
            "RejectedPresentation({})",
            presentation_rejection.as_deref().unwrap_or("unknown")
        )
    } else {
        match decision {
            Ok(value) => format!("{value:?}"),
            Err(error) => format!("Rejected({error:?})"),
        }
    };

    let mut authority = CompiledAuthority::standard();
    let evidence = Evidence {
        code: 911,
        digest: first_16(&task_digest),
    };
    let mut proposals = Vec::with_capacity(5);
    let observe = Proposal::new(State::Idle, State::Observing, Action::Observe);
    let decide_proposal =
        Proposal::new(State::Observing, State::Deciding, Action::Decide).with_evidence(evidence);
    authority.apply(observe);
    authority.apply(decide_proposal);
    proposals.push(observe);
    proposals.push(decide_proposal);

    let mut action_id = None;
    let mut unique_action_effects = 0;
    let mut duplicate_action_effects = 0;
    let mut idempotent_action_reuse = false;
    if let Some(option) = selected_option.as_ref() {
        let execute = Proposal::new(State::Deciding, State::Acting, Action::Execute)
            .with_confidence(input.observer_output.applicability_milli)
            .with_evidence(evidence);
        let receipt = authority.apply(execute);
        proposals.push(execute);
        if receipt.authorized_action == Some(Action::Execute) {
            let stable_id =
                stable_action_id(&input.task_id, option.action.id, &option.patch_sha256);
            let mut simulator = ActionSimulator::create(&input.action_ledger_path)?;
            let effect = simulator.perform(stable_id, Action::Execute)?;
            unique_action_effects = simulator.stats().unique_effects;
            simulator.flush_close()?;
            // SAFETY: the only writer is closed before reopening the action ledger.
            let mut resumed = unsafe { ActionSimulator::resume(&input.action_ledger_path)? };
            let reused = resumed.perform(stable_id, Action::Execute)?;
            duplicate_action_effects = resumed.stats().duplicate_effects;
            idempotent_action_reuse = reused.idempotent_reuse;
            resumed.flush_close()?;
            if !idempotent_action_reuse || effect.effect_index != reused.effect_index {
                return Err("stable action ID did not replay idempotently".into());
            }
            action_id = Some(hex(&stable_id.0));
            let verify = Proposal::new(State::Acting, State::Verifying, Action::Verify);
            authority.apply(verify);
            proposals.push(verify);
            let completion = if input.completion_check_passed {
                Proposal::new(State::Verifying, State::Done, Action::Complete)
                    .with_evidence(evidence)
            } else {
                Proposal::new(State::Verifying, State::Failed, Action::Fail)
            };
            authority.apply(completion);
            proposals.push(completion);
        } else {
            push_failure(&mut authority, &mut proposals);
        }
    } else {
        push_failure(&mut authority, &mut proposals);
    }

    let snapshots = authority
        .receipts()
        .iter()
        .copied()
        .map(Into::into)
        .collect::<Vec<ReceiptSnapshot>>();
    let mut replay = CompiledAuthority::standard();
    let replay_snapshots = proposals
        .iter()
        .copied()
        .map(|proposal| replay.apply(proposal).into())
        .collect::<Vec<ReceiptSnapshot>>();
    let replay_state_identical =
        replay.state() == authority.state() && replay_snapshots == snapshots;
    let replay_identity = blake3::hash(&serde_json::to_vec(&snapshots)?)
        .to_hex()
        .to_string();
    let rejected_transitions = snapshots
        .iter()
        .filter(|item| item.rejection.is_some())
        .count();
    let illegal_commits = usize::from(
        snapshots
            .iter()
            .any(|item| item.rejection.is_some() && item.authorized_action.is_some())
            || (rejected_transitions > 0 && unique_action_effects > 0),
    );
    let action_choice = selected_option.as_ref().map(|option| option.action.id);
    let selected_patch_sha256 = selected_option.map(|option| option.patch_sha256);
    let result = AuthorizationResult {
        task_id: input.task_id,
        presentation_verified,
        presentation_rejection,
        safe_fallback: (!presentation_verified).then_some("ABSTAIN_AND_ABORT_ACTION"),
        request_id_hex: hex_digest(&request_id),
        receipt_digest_hex: hex_digest(&request_receipt_digest),
        action_choice,
        selected_patch_sha256,
        typed_decision: compiled_decision,
        completion_check_passed: input.completion_check_passed,
        final_state: authority.state().label().to_owned(),
        illegal_commits,
        rejected_transitions,
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

fn push_failure(authority: &mut CompiledAuthority, proposals: &mut Vec<Proposal>) {
    let failure = Proposal::new(State::Deciding, State::Failed, Action::Fail);
    authority.apply(failure);
    proposals.push(failure);
}

fn decode_hex(value: &str) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    if !value.len().is_multiple_of(2) || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("receipt must be even-length hexadecimal".into());
    }
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| Ok((hex_nibble(pair[0])? << 4) | hex_nibble(pair[1])?))
        .collect()
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
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(output, "{byte:02x}");
    }
    output
}
