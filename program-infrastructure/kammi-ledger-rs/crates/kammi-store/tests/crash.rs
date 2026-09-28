//! Crash matrix: a child process runs a deterministic workload and is killed (exit 91, no
//! unwinding, no flushing) at a chosen fault point on its n-th hit. The parent then demands:
//!
//! 1. the store opens and deep-verifies (no chimera: chain, frames, payloads, indexes);
//! 2. every committed event's referenced object exists (objects are durable before events);
//! 3. what is committed is a prefix of the reference history (checked via resumed heads);
//! 4. resuming the workload to completion reaches exactly the uninterrupted reference heads.
//!
//! `KAMMI_CRASH_RANDOM=<n>` adds n randomized runs (random point, hit and double crashes).

use std::path::Path;
use std::process::Command;

use kammi_store::fault::{FAULT_EXIT_CODE, FAULT_POINTS};

const DRIVER: &str = env!("CARGO_BIN_EXE_kammi-store-driver");
const EVENTS: &str = "60";

fn run(root: &Path, fault: Option<(&str, u64)>) -> Option<i32> {
    let mut command = Command::new(DRIVER);
    command.args(["workload", root.to_str().unwrap(), EVENTS]);
    command.env_remove("KAMMI_ACCEPTANCE_FAULTS");
    if let Some((point, hit)) = fault {
        command
            .env("KAMMI_ACCEPTANCE_FAULTS", "1")
            .env("KAMMI_FAULT_POINT", point)
            .env("KAMMI_FAULT_HIT", hit.to_string());
    }
    let output = command.output().unwrap();
    if !output.status.success() && output.status.code() != Some(FAULT_EXIT_CODE) {
        panic!(
            "workload failed {:?}: {}",
            fault,
            String::from_utf8_lossy(&output.stderr)
        );
    }
    output.status.code()
}

fn verify(root: &Path) -> String {
    let output = Command::new(DRIVER)
        .args(["verify", root.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "verify failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap()
}

fn heads(summary: &str) -> String {
    // "main=<seq> <head> memory=<seq> <head> objects=.. checkpoint=.."
    summary.split(" objects=").next().unwrap().to_string()
}

fn reference(dir: &Path) -> String {
    let root = dir.join("reference");
    assert_eq!(run(&root, None), Some(0));
    let summary = verify(&root);
    assert!(summary.starts_with("main=60 "), "{summary}");
    heads(&summary)
}

fn crash_then_resume(dir: &Path, name: &str, faults: &[(&str, u64)], expected: &str) -> bool {
    let root = dir.join(name);
    let mut crashed = false;
    for fault in faults {
        if run(&root, Some(*fault)) == Some(FAULT_EXIT_CODE) {
            crashed = true;
            verify(&root);
        }
    }
    assert_eq!(run(&root, None), Some(0));
    assert_eq!(heads(&verify(&root)), expected, "{name} {faults:?}");
    std::fs::remove_dir_all(&root).unwrap();
    crashed
}

#[test]
fn every_fault_point_recovers_to_the_reference_history() {
    let dir = tempfile::tempdir().unwrap();
    let expected = reference(dir.path());
    let mut crashes = 0;
    for point in FAULT_POINTS {
        let mut point_crashed = false;
        for hit in [1u64, 2, 3, 5, 8, 13, 21] {
            let name = format!("{}-{hit}", point.replace('.', "_"));
            if crash_then_resume(dir.path(), &name, &[(point, hit)], &expected) {
                crashes += 1;
                point_crashed = true;
            }
        }
        assert!(
            point_crashed,
            "fault point {point} was never reached by the workload"
        );
    }
    eprintln!("{crashes} interrupted runs recovered to the reference heads");
}

#[test]
fn randomized_repeated_crashes_converge() {
    let runs: u64 = std::env::var("KAMMI_CRASH_RANDOM")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(40);
    let dir = tempfile::tempdir().unwrap();
    let expected = reference(dir.path());
    // Small deterministic LCG so failures are reproducible from the printed run number.
    let mut state = 0x9E37_79B9_7F4A_7C15u64;
    let mut next = |bound: u64| {
        state = state
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        (state >> 33) % bound
    };
    for run_no in 0..runs {
        let count = 1 + next(3) as usize;
        let faults: Vec<(&str, u64)> = (0..count)
            .map(|_| {
                (
                    FAULT_POINTS[next(FAULT_POINTS.len() as u64) as usize],
                    1 + next(30),
                )
            })
            .collect();
        crash_then_resume(dir.path(), &format!("random-{run_no}"), &faults, &expected);
    }
}
