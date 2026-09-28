use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
    time::{SystemTime, UNIX_EPOCH},
};

use rdc_experiment_001::{Evidence, Observation, Signal, State};
use rdc_experiment_002::{
    CompiledAuthority, CrashPoint, HandwrittenAuthority, JournalEvent, ObserverContractError,
    ObserverManifest, ObserverSwitchboard, TaskRunner, TaskRunnerError, VersionedObserver,
    WorkflowAdapter, WorkflowBehavior, read_task_journal_mmap,
};

static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

struct TempFiles {
    directory: PathBuf,
    journal: PathBuf,
    actions: PathBuf,
}

impl TempFiles {
    fn new(label: &str) -> Self {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let nonce = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
        let directory = std::env::temp_dir().join(format!("rdc002-{label}-{stamp}-{nonce}"));
        fs::create_dir_all(&directory).unwrap();
        Self {
            journal: directory.join("task.journal"),
            actions: directory.join("actions.ledger"),
            directory,
        }
    }
}

impl Drop for TempFiles {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

fn board(
    active: WorkflowBehavior,
    active_id: &str,
    shadow: WorkflowBehavior,
    shadow_id: &str,
) -> ObserverSwitchboard {
    ObserverSwitchboard::new(
        Box::new(WorkflowAdapter::new(active_id, active)),
        Box::new(WorkflowAdapter::new(shadow_id, shadow)),
    )
    .unwrap()
}

fn observation(signal: Signal) -> Observation {
    let mut value = Observation::new(signal);
    if signal != Signal::Start {
        value = value.with_evidence(Evidence {
            code: 21,
            digest: [0x77; 16],
        });
    }
    if matches!(signal, Signal::Approve | Signal::Recover) {
        value = value.with_confidence(900);
    }
    value
}

fn task_signals() -> [Signal; 5] {
    [
        Signal::Start,
        Signal::Observed,
        Signal::Approve,
        Signal::ActionSucceeded,
        Signal::Verified,
    ]
}

#[test]
fn shadow_proposal_is_recorded_without_authority() {
    let files = TempFiles::new("shadow");
    let mut runner = TaskRunner::create(
        CompiledAuthority::standard(),
        board(
            WorkflowBehavior::Normal,
            "workflow/v1",
            WorkflowBehavior::MisrouteApprove,
            "shadow/v1",
        ),
        101,
        &files.journal,
        &files.actions,
    )
    .unwrap();

    let start = runner.step(&observation(Signal::Start), None).unwrap();
    assert_eq!(start.active, start.shadow);
    let observed = runner.step(&observation(Signal::Observed), None).unwrap();
    assert_eq!(observed.active, observed.shadow);
    let approve = runner.step(&observation(Signal::Approve), None).unwrap();
    assert!(approve.disagreement);
    assert!(approve.receipt.accepted());
    assert_eq!(
        approve.receipt.authorized_action,
        Some(approve.active.action)
    );
    assert_eq!(runner.state(), State::Acting);
    assert_eq!(runner.metrics().unique_actions, 3);

    let expected_hash = runner.metrics().replay_identity.unwrap();
    runner.close().unwrap();
    // SAFETY: the runner closed both writers and this test is the sole owner of the files.
    let records = unsafe { read_task_journal_mmap(&files.journal).unwrap() };
    let stored_shadow = records
        .iter()
        .find_map(|record| match &record.event {
            JournalEvent::Proposals {
                step: 2,
                active,
                shadow,
                disagreement,
                ..
            } => Some((*active, *shadow, *disagreement)),
            _ => None,
        })
        .unwrap();
    assert!(stored_shadow.2);
    assert_ne!(stored_shadow.0, stored_shadow.1);

    // SAFETY: no writer remains open; resume validates the hash chain and replays recorded proposals.
    let resumed = unsafe {
        TaskRunner::resume(
            CompiledAuthority::standard(),
            board(
                WorkflowBehavior::Normal,
                "workflow/v1",
                WorkflowBehavior::MisrouteApprove,
                "shadow/v1",
            ),
            101,
            &files.journal,
            &files.actions,
        )
        .unwrap()
    };
    assert_eq!(resumed.state(), State::Acting);
    assert_eq!(resumed.metrics().replay_identity, Some(expected_hash));
    resumed.close().unwrap();
}

#[test]
fn active_observer_can_be_swapped_and_registry_epoch_replays() {
    let files = TempFiles::new("swap");
    let mut runner = TaskRunner::create(
        HandwrittenAuthority::default(),
        board(
            WorkflowBehavior::MisrouteApprove,
            "bad-router/v1",
            WorkflowBehavior::Normal,
            "shadow/v1",
        ),
        202,
        &files.journal,
        &files.actions,
    )
    .unwrap();

    runner.step(&observation(Signal::Start), None).unwrap();
    runner.step(&observation(Signal::Observed), None).unwrap();
    let bad = runner.step(&observation(Signal::Approve), None).unwrap();
    assert!(!bad.receipt.accepted());
    assert_eq!(runner.state(), State::Deciding);

    let swap_ns = runner
        .replace_active(Box::new(WorkflowAdapter::new(
            "repaired-router/v1",
            WorkflowBehavior::Normal,
        )))
        .unwrap();
    assert!(runner.metrics().observer_swap_ns >= swap_ns as u128);
    let good = runner.step(&observation(Signal::Approve), None).unwrap();
    assert!(good.receipt.accepted());
    for signal in [Signal::ActionSucceeded, Signal::Verified] {
        runner.step(&observation(signal), None).unwrap();
    }
    let metrics = runner.metrics();
    assert_eq!(metrics.final_state, Some(State::Done));
    assert_eq!(metrics.observer_swaps, 1);
    assert_eq!(metrics.observer_registry_epochs, 2);
    assert_eq!(metrics.rejected_proposals, 1);
    let replay_hash = metrics.replay_identity;
    runner.close().unwrap();

    // SAFETY: both journals are closed and this test exclusively owns them.
    let resumed = unsafe {
        TaskRunner::resume(
            HandwrittenAuthority::default(),
            board(
                WorkflowBehavior::Normal,
                "repaired-router/v1",
                WorkflowBehavior::Normal,
                "shadow/v1",
            ),
            202,
            &files.journal,
            &files.actions,
        )
        .unwrap()
    };
    assert_eq!(resumed.state(), State::Done);
    assert_eq!(resumed.metrics().observer_swaps, 1);
    assert_eq!(resumed.metrics().replay_identity, replay_hash);
    resumed.close().unwrap();
}

#[test]
fn crashes_at_each_action_boundary_resume_without_loss_or_duplicate_effects() {
    for (index, point) in [
        CrashPoint::AfterTransitionReceipt,
        CrashPoint::AfterActionIntent,
        CrashPoint::AfterActionEffect,
        CrashPoint::AfterActionCompletion,
    ]
    .into_iter()
    .enumerate()
    {
        let files = TempFiles::new(&format!("crash-{index}"));
        let mut runner = TaskRunner::create(
            CompiledAuthority::standard(),
            board(
                WorkflowBehavior::Normal,
                "workflow/v1",
                WorkflowBehavior::MisrouteApprove,
                "shadow/v1",
            ),
            303 + index as u64,
            &files.journal,
            &files.actions,
        )
        .unwrap();
        let result = runner.step(&observation(Signal::Start), Some(point));
        assert!(matches!(result, Err(TaskRunnerError::InjectedCrash(actual)) if actual == point));
        drop(runner);

        // SAFETY: the simulated process and its writers have been dropped before replay.
        let mut runner = unsafe {
            TaskRunner::resume(
                CompiledAuthority::standard(),
                board(
                    WorkflowBehavior::Normal,
                    "workflow/v1",
                    WorkflowBehavior::MisrouteApprove,
                    "shadow/v1",
                ),
                303 + index as u64,
                &files.journal,
                &files.actions,
            )
            .unwrap()
        };
        assert_eq!(runner.next_step(), 1);
        assert_eq!(runner.metrics().unique_actions, 1);
        if point == CrashPoint::AfterActionEffect {
            assert_eq!(runner.metrics().idempotent_reuses, 1);
        }
        for signal in task_signals().into_iter().skip(1) {
            runner.step(&observation(signal), None).unwrap();
        }

        let metrics = runner.metrics();
        assert_eq!(metrics.final_state, Some(State::Done));
        assert_eq!(metrics.authorized_actions, 5);
        assert_eq!(metrics.unique_actions, 5);
        assert_eq!(metrics.duplicate_actions, 0);
        assert_eq!(metrics.missing_actions, 0);
        let final_hash = metrics.replay_identity;
        runner.close().unwrap();

        // SAFETY: closed immutable journals are reopened read-only before resume.
        let replayed = unsafe {
            TaskRunner::resume(
                CompiledAuthority::standard(),
                board(
                    WorkflowBehavior::Normal,
                    "workflow/v1",
                    WorkflowBehavior::MisrouteApprove,
                    "shadow/v1",
                ),
                303 + index as u64,
                &files.journal,
                &files.actions,
            )
            .unwrap()
        };
        assert_eq!(replayed.state(), State::Done);
        assert_eq!(replayed.metrics().replay_identity, final_hash);
        assert_eq!(replayed.metrics().duplicate_actions, 0);
        replayed.close().unwrap();
    }
}

#[test]
fn observer_contract_rejects_an_unversioned_implementation() {
    struct BadObserver(ObserverManifest);
    impl VersionedObserver for BadObserver {
        fn manifest(&self) -> &ObserverManifest {
            &self.0
        }
        fn propose(
            &mut self,
            state: State,
            observation: &Observation,
            recovery_count: u8,
        ) -> rdc_experiment_001::Proposal {
            let mut workflow = rdc_experiment_001::WorkflowObserver;
            rdc_experiment_001::Observer::propose(&mut workflow, state, observation, recovery_count)
        }
    }

    let manifest = ObserverManifest {
        interface_version: 99,
        implementation_id: "unversioned".to_owned(),
        input_schema: "rdc.observation.v1".to_owned(),
        output_schema: "rdc.transition-proposal.v1".to_owned(),
        normalization_contract: "identity-v1".to_owned(),
    };
    let result = ObserverSwitchboard::new(
        Box::new(BadObserver(manifest)),
        Box::new(WorkflowAdapter::new("shadow/v1", WorkflowBehavior::Normal)),
    );
    assert!(matches!(
        result,
        Err(ObserverContractError::UnsupportedInterfaceVersion(99))
    ));
}
