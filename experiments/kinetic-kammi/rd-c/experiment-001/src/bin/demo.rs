use std::{error::Error, fs, path::PathBuf};

use rdc_experiment_001::{
    DecisionCompiler, Evidence, Observation, Runtime, Signal, WorkflowObserver, replay_mmap,
    standard_schema, write_journal,
};

fn main() -> Result<(), Box<dyn Error>> {
    let compiler = DecisionCompiler::compile(&standard_schema())?;
    let mut runtime = Runtime::with_capacity(compiler.clone(), 6);
    let mut observer = WorkflowObserver;
    let evidence = Evidence {
        code: 1,
        digest: [0x42; 16],
    };

    let invalid = runtime.step(&Observation::new(Signal::Unexpected), &mut observer);
    println!(
        "proposal: {} -> {} / {} ; accepted={} ; rejection={:?}",
        invalid.before.label(),
        invalid.proposal.requested_to.label(),
        invalid.proposal.action.label(),
        invalid.accepted(),
        invalid.rejection
    );

    for signal in [
        Signal::Start,
        Signal::Observed,
        Signal::Approve,
        Signal::ActionSucceeded,
        Signal::Verified,
    ] {
        let mut observation = Observation::new(signal);
        if signal != Signal::Start {
            observation = observation.with_evidence(evidence);
        }
        if signal == Signal::Approve {
            observation = observation.with_confidence(900);
        }
        let receipt = runtime.step(&observation, &mut observer);
        println!(
            "receipt #{:02}: {} -> {} ; action={:?} ; accepted={}",
            receipt.sequence,
            receipt.before.label(),
            receipt.after.label(),
            receipt.authorized_action,
            receipt.accepted()
        );
    }

    let artifacts = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("artifacts");
    fs::create_dir_all(&artifacts)?;
    let journal = artifacts.join("experiment-001.journal");
    write_journal(&journal, runtime.receipts())?;
    drop(runtime);

    // SAFETY: the demo closed its only journal writer before mapping, and does not mutate
    // the file until replay returns.
    let (_replayed, replay) = unsafe {
        replay_mmap(
            journal.as_path(),
            DecisionCompiler::compile(&standard_schema())?,
        )?
    };
    println!(
        "replay: {} receipts, {} rejected, completed={}, identity={}",
        replay.receipt_count,
        replay.rejected_count,
        replay.completed,
        hex(&replay.final_hash)
    );
    println!("journal: {}", journal.display());
    if replay.completed && replay.receipt_count == 6 {
        Ok(())
    } else {
        Err("demo did not reach the expected replayed state".into())
    }
}

fn hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut result = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        result.push(HEX[(byte >> 4) as usize] as char);
        result.push(HEX[(byte & 0xf) as usize] as char);
    }
    result
}
