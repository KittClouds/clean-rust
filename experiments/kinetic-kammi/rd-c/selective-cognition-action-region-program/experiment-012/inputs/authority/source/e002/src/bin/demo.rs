use std::{
    error::Error,
    fs,
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

use rdc_experiment_001::{Evidence, Observation, Signal, State};
use rdc_experiment_002::{
    CompiledAuthority, CrashPoint, ObserverSwitchboard, TaskRunner, TaskRunnerError,
    WorkflowAdapter, WorkflowBehavior,
};

fn board() -> ObserverSwitchboard {
    ObserverSwitchboard::new(
        Box::new(WorkflowAdapter::new(
            "workflow/active-v1",
            WorkflowBehavior::Normal,
        )),
        Box::new(WorkflowAdapter::new(
            "workflow/shadow-misroute-v1",
            WorkflowBehavior::MisrouteApprove,
        )),
    )
    .expect("valid observer manifests")
}

fn observation(signal: Signal) -> Observation {
    let mut value = Observation::new(signal);
    if signal != Signal::Start {
        value = value.with_evidence(Evidence {
            code: 44,
            digest: [0x44; 16],
        });
    }
    if matches!(signal, Signal::Approve | Signal::Recover) {
        value = value.with_confidence(900);
    }
    value
}

fn main() -> Result<(), Box<dyn Error>> {
    let task_id = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos() as u64;
    let artifacts = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("artifacts");
    fs::create_dir_all(&artifacts)?;
    let journal = artifacts.join(format!("task-{task_id}.journal"));
    let actions = artifacts.join(format!("task-{task_id}.actions"));

    let mut runner = TaskRunner::create(
        CompiledAuthority::standard(),
        board(),
        task_id,
        &journal,
        &actions,
    )?;
    let signals = [
        Signal::Start,
        Signal::Observed,
        Signal::Approve,
        Signal::ActionFailed,
        Signal::Recover,
        Signal::Observed,
        Signal::Approve,
        Signal::ActionSucceeded,
        Signal::Verified,
    ];

    for (step, signal) in signals.into_iter().enumerate() {
        let crash = (signal == Signal::ActionFailed).then_some(CrashPoint::AfterActionEffect);
        match runner.step(&observation(signal), crash) {
            Ok(outcome) => {
                println!(
                    "step {}: active={} shadow={} disagree={} state={} accepted={} action_id={:?}",
                    step,
                    outcome.active.action.label(),
                    outcome.shadow.action.label(),
                    outcome.disagreement,
                    outcome.receipt.after.label(),
                    outcome.receipt.accepted(),
                    outcome.action_id,
                );
            }
            Err(TaskRunnerError::InjectedCrash(point)) => {
                println!("simulated crash at {point:?}; reopening journals");
                drop(runner);
                // SAFETY: dropping runner closes both writers before mapped replay.
                runner = unsafe {
                    TaskRunner::resume(
                        CompiledAuthority::standard(),
                        board(),
                        task_id,
                        &journal,
                        &actions,
                    )?
                };
            }
            Err(error) => return Err(error.into()),
        }
    }

    let metrics = runner.metrics();
    let expected_hash = metrics.replay_identity.expect("journal has receipts");
    println!(
        "state={} receipts={} disagreements={} recoveries={} duplicate_actions={} missing_actions={} journal_bytes={} action_bytes={}",
        metrics.final_state.unwrap_or(State::Failed).label(),
        runner.receipts().len(),
        metrics.observer_disagreements,
        metrics.recoveries,
        metrics.duplicate_actions,
        metrics.missing_actions,
        metrics.journal_bytes,
        metrics.action_ledger_bytes,
    );
    runner.close()?;

    // SAFETY: no writer remains open; resume replays immutable journals and verifies identity.
    let replayed = unsafe {
        TaskRunner::resume(
            CompiledAuthority::standard(),
            board(),
            task_id,
            &journal,
            &actions,
        )?
    };
    let replay_metrics = replayed.metrics();
    if replay_metrics.final_state != Some(State::Done)
        || replay_metrics.replay_identity != Some(expected_hash)
        || replay_metrics.duplicate_actions != 0
        || replay_metrics.missing_actions != 0
    {
        return Err("resume did not preserve task state and action identity".into());
    }
    println!(
        "replay identity={} duplicate_actions={} resumed_state={}",
        hex(&expected_hash),
        replay_metrics.duplicate_actions,
        replayed.state().label(),
    );
    replayed.close()?;
    println!("journal: {}", journal.display());
    println!("action ledger: {}", actions.display());
    Ok(())
}

fn hex(bytes: &[u8; 32]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}
