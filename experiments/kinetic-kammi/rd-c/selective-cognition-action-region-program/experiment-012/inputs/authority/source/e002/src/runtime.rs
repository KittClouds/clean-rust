use std::{collections::HashSet, path::Path, time::Instant};

use hashbrown::HashMap;
use rdc_experiment_001::{Action, Observation, Proposal, Receipt, State};

use crate::{
    action::{ActionId, ActionSimulator},
    controller::Authority,
    journal::{JournalError, TaskJournal, read_task_journal_mmap},
    model::{JournalEvent, ObserverRegistry, ReceiptSnapshot},
    observer::{ObserverContractError, ObserverSwitchboard, VersionedObserver},
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CrashPoint {
    AfterTransitionReceipt,
    AfterActionIntent,
    AfterActionEffect,
    AfterActionCompletion,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct StepOutcome {
    pub step: u32,
    pub active: Proposal,
    pub shadow: Proposal,
    pub disagreement: bool,
    pub receipt: Receipt,
    pub action_id: Option<ActionId>,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct TaskMetrics {
    pub active_observer_calls: usize,
    pub shadow_observer_calls: usize,
    pub active_observer_ns: u128,
    pub shadow_observer_ns: u128,
    pub observer_disagreements: usize,
    pub observer_swaps: usize,
    pub observer_registry_epochs: usize,
    pub observer_swap_ns: u128,
    pub rejected_proposals: usize,
    pub illegal_commits: usize,
    pub accepted_transitions: usize,
    pub authorized_actions: usize,
    pub recoveries: u8,
    pub unique_actions: usize,
    pub duplicate_actions: usize,
    pub missing_actions: usize,
    pub idempotent_reuses: usize,
    pub journal_bytes: u64,
    pub action_ledger_bytes: u64,
    pub final_state: Option<State>,
    pub replay_identity: Option<[u8; 32]>,
}

#[derive(Clone, Debug)]
struct ProposalRecord {
    step: u32,
    active: Proposal,
    shadow: Proposal,
    active_observer_ns: u64,
    shadow_observer_ns: u64,
    disagreement: bool,
    registry_epoch: u64,
}

#[derive(Clone, Copy, Debug)]
struct PendingIntent {
    action: Action,
    step: u32,
    transition_sequence: u64,
}

#[derive(Clone, Copy, Debug)]
struct PendingCompletion {
    effect_index: u64,
    idempotent_reuse: bool,
}

#[derive(Debug)]
pub enum TaskRunnerError {
    Io(std::io::Error),
    Journal(JournalError),
    Action(crate::action::ActionSimulatorError),
    Observer(ObserverContractError),
    InjectedCrash(CrashPoint),
    InvalidReplay(&'static str),
    ReceiptMismatch { sequence: u64 },
    ActionMismatch { sequence: u64 },
}

impl std::fmt::Display for TaskRunnerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(f, "task runtime I/O error: {error}"),
            Self::Journal(error) => write!(f, "task journal error: {error}"),
            Self::Action(error) => write!(f, "action simulator error: {error}"),
            Self::Observer(error) => write!(f, "observer contract error: {error}"),
            Self::InjectedCrash(point) => write!(f, "simulated crash at {point:?}"),
            Self::InvalidReplay(message) => write!(f, "invalid replay: {message}"),
            Self::ReceiptMismatch { sequence } => {
                write!(f, "transition receipt mismatch at {sequence}")
            }
            Self::ActionMismatch { sequence } => {
                write!(f, "action receipt mismatch at transition {sequence}")
            }
        }
    }
}

impl std::error::Error for TaskRunnerError {}

impl From<std::io::Error> for TaskRunnerError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<JournalError> for TaskRunnerError {
    fn from(value: JournalError) -> Self {
        Self::Journal(value)
    }
}

impl From<crate::action::ActionSimulatorError> for TaskRunnerError {
    fn from(value: crate::action::ActionSimulatorError) -> Self {
        Self::Action(value)
    }
}

impl From<ObserverContractError> for TaskRunnerError {
    fn from(value: ObserverContractError) -> Self {
        Self::Observer(value)
    }
}

pub struct TaskRunner<A: Authority> {
    authority: A,
    switchboard: ObserverSwitchboard,
    journal: TaskJournal,
    action_simulator: ActionSimulator,
    task_id: u64,
    next_step: u32,
    proposals: Vec<ProposalRecord>,
    intents: HashMap<ActionId, PendingIntent>,
    completions: HashMap<ActionId, PendingCompletion>,
    observer_swaps: usize,
    observer_swap_ns: u128,
}

impl<A: Authority> TaskRunner<A> {
    pub fn create(
        authority: A,
        switchboard: ObserverSwitchboard,
        task_id: u64,
        journal_path: impl AsRef<Path>,
        action_path: impl AsRef<Path>,
    ) -> Result<Self, TaskRunnerError> {
        let mut journal = TaskJournal::create(journal_path)?;
        let action_simulator = ActionSimulator::create(action_path)?;
        journal.append(JournalEvent::ObserverRegistry {
            registry: switchboard.registry(),
            observer_swap_ns: None,
        })?;
        Ok(Self {
            authority,
            switchboard,
            journal,
            action_simulator,
            task_id,
            next_step: 0,
            proposals: Vec::new(),
            intents: HashMap::with_capacity(16),
            completions: HashMap::with_capacity(16),
            observer_swaps: 0,
            observer_swap_ns: 0,
        })
    }

    /// Resumes a task from closed journals, replays every recorded active proposal, and
    /// resolves accepted but incomplete actions before returning.
    ///
    /// # Safety
    /// The prior process must be stopped, and no other thread or process may mutate either
    /// journal while the read-only replay mappings are active.
    pub unsafe fn resume(
        mut authority: A,
        switchboard: ObserverSwitchboard,
        task_id: u64,
        journal_path: impl AsRef<Path>,
        action_path: impl AsRef<Path>,
    ) -> Result<Self, TaskRunnerError> {
        // SAFETY: guaranteed by this function's caller contract.
        let events = unsafe { read_task_journal_mmap(journal_path.as_ref())? };
        // SAFETY: guaranteed by this function's caller contract.
        let action_simulator = unsafe { ActionSimulator::resume(action_path.as_ref())? };
        authority.reset();

        let mut runner = Self {
            authority,
            switchboard,
            journal: TaskJournal::open_append(journal_path, &events)?,
            action_simulator,
            task_id,
            next_step: 0,
            proposals: Vec::new(),
            intents: HashMap::with_capacity(16),
            completions: HashMap::with_capacity(16),
            observer_swaps: 0,
            observer_swap_ns: 0,
        };
        let mut registry: Option<ObserverRegistry> = None;
        let mut pending: Option<ProposalRecord> = None;
        let mut last_step = None;

        for envelope in &events {
            match &envelope.event {
                JournalEvent::ObserverRegistry {
                    registry: next,
                    observer_swap_ns,
                } => {
                    if pending.is_some() {
                        return Err(TaskRunnerError::InvalidReplay(
                            "observer registry changed mid-proposal",
                        ));
                    }
                    let expected_epoch = registry.as_ref().map_or(0, |old| old.epoch + 1);
                    if next.epoch != expected_epoch {
                        return Err(TaskRunnerError::InvalidReplay(
                            "observer registry epoch is not consecutive",
                        ));
                    }
                    if registry
                        .as_ref()
                        .is_some_and(|old| old.shadow != next.shadow)
                    {
                        return Err(TaskRunnerError::InvalidReplay(
                            "shadow replacement is not supported in v0",
                        ));
                    }
                    if let Some(duration) = observer_swap_ns {
                        runner.observer_swaps += 1;
                        runner.observer_swap_ns += *duration as u128;
                    }
                    registry = Some(next.clone());
                }
                JournalEvent::Proposals {
                    task_id: recorded_task,
                    step,
                    registry_epoch,
                    observation,
                    active,
                    shadow,
                    active_observer_ns,
                    shadow_observer_ns,
                    disagreement,
                } => {
                    if *recorded_task != task_id {
                        return Err(TaskRunnerError::InvalidReplay(
                            "task ID changed inside journal",
                        ));
                    }
                    let current = registry.as_ref().ok_or(TaskRunnerError::InvalidReplay(
                        "proposal appeared before observer registry",
                    ))?;
                    if *registry_epoch != current.epoch {
                        return Err(TaskRunnerError::InvalidReplay(
                            "proposal uses an unknown registry epoch",
                        ));
                    }
                    let expected_step = last_step.map_or(0, |step: u32| step + 1);
                    if *step != expected_step || pending.is_some() {
                        return Err(TaskRunnerError::InvalidReplay(
                            "proposal steps are not consecutive",
                        ));
                    }
                    let _observation = Observation::try_from(*observation)
                        .map_err(TaskRunnerError::InvalidReplay)?;
                    let active =
                        Proposal::try_from(*active).map_err(TaskRunnerError::InvalidReplay)?;
                    let shadow =
                        Proposal::try_from(*shadow).map_err(TaskRunnerError::InvalidReplay)?;
                    if *disagreement != (active != shadow) {
                        return Err(TaskRunnerError::InvalidReplay(
                            "shadow disagreement flag is incorrect",
                        ));
                    }
                    pending = Some(ProposalRecord {
                        step: *step,
                        active,
                        shadow,
                        active_observer_ns: *active_observer_ns,
                        shadow_observer_ns: *shadow_observer_ns,
                        disagreement: *disagreement,
                        registry_epoch: *registry_epoch,
                    });
                }
                JournalEvent::Transition { step, receipt } => {
                    let proposals = pending.take().ok_or(TaskRunnerError::InvalidReplay(
                        "transition has no recorded proposals",
                    ))?;
                    if *step != proposals.step {
                        return Err(TaskRunnerError::InvalidReplay(
                            "transition step differs from proposal step",
                        ));
                    }
                    let actual = runner.authority.apply(proposals.active);
                    if ReceiptSnapshot::from(actual) != *receipt {
                        return Err(TaskRunnerError::ReceiptMismatch {
                            sequence: actual.sequence,
                        });
                    }
                    last_step = Some(*step);
                    runner.next_step = *step + 1;
                    runner.proposals.push(proposals);
                }
                JournalEvent::ActionIntent {
                    action_id,
                    task_id: recorded_task,
                    step,
                    transition_sequence,
                    action,
                } => {
                    if *recorded_task != task_id
                        || runner.intents.contains_key(&ActionId(*action_id))
                    {
                        return Err(TaskRunnerError::InvalidReplay(
                            "duplicate or foreign action intent",
                        ));
                    }
                    let receipt = runner
                        .authority
                        .receipts()
                        .get(*transition_sequence as usize)
                        .ok_or(TaskRunnerError::InvalidReplay(
                            "intent references missing transition",
                        ))?;
                    let action = Action::try_from(*action)
                        .map_err(|_| TaskRunnerError::InvalidReplay("intent has unknown action"))?;
                    if receipt.sequence != *transition_sequence
                        || receipt.proposal.action != action
                        || receipt.authorized_action != Some(action)
                        || runner.proposals.get(*step as usize).is_none()
                    {
                        return Err(TaskRunnerError::ActionMismatch {
                            sequence: *transition_sequence,
                        });
                    }
                    let expected_id = action_id_for(task_id, *transition_sequence, action);
                    if expected_id.0 != *action_id {
                        return Err(TaskRunnerError::ActionMismatch {
                            sequence: *transition_sequence,
                        });
                    }
                    runner.intents.insert(
                        ActionId(*action_id),
                        PendingIntent {
                            action,
                            step: *step,
                            transition_sequence: *transition_sequence,
                        },
                    );
                }
                JournalEvent::ActionCompleted {
                    action_id,
                    effect_index,
                    idempotent_reuse,
                } => {
                    let id = ActionId(*action_id);
                    if !runner.intents.contains_key(&id)
                        || runner
                            .completions
                            .insert(
                                id,
                                PendingCompletion {
                                    effect_index: *effect_index,
                                    idempotent_reuse: *idempotent_reuse,
                                },
                            )
                            .is_some()
                    {
                        return Err(TaskRunnerError::InvalidReplay(
                            "completion has missing intent or is duplicated",
                        ));
                    }
                }
            }
        }

        let registry =
            registry.ok_or(TaskRunnerError::InvalidReplay("missing observer registry"))?;
        if registry.active != *runner.switchboard.active_manifest()
            || registry.shadow != *runner.switchboard.shadow_manifest()
        {
            return Err(TaskRunnerError::InvalidReplay(
                "resume observer manifests differ from recorded active versions",
            ));
        }
        runner.switchboard.restore_epoch(registry.epoch);

        if let Some(proposals) = pending {
            let actual = runner.authority.apply(proposals.active);
            runner.journal.append(JournalEvent::Transition {
                step: proposals.step,
                receipt: actual.into(),
            })?;
            last_step = Some(proposals.step);
            runner.next_step = proposals.step + 1;
            runner.proposals.push(proposals);
        }
        if last_step.is_none() {
            runner.next_step = 0;
        }

        runner.reconcile_actions()?;
        Ok(runner)
    }

    pub fn step(
        &mut self,
        observation: &Observation,
        crash_point: Option<CrashPoint>,
    ) -> Result<StepOutcome, TaskRunnerError> {
        let step = self.next_step;
        let state = self.authority.state();
        let registry_epoch = self.switchboard.epoch();
        let pair =
            self.switchboard
                .propose_pair(state, observation, self.authority.recovery_count());
        let proposal_record = ProposalRecord {
            step,
            active: pair.active,
            shadow: pair.shadow,
            active_observer_ns: pair.active_observer_ns,
            shadow_observer_ns: pair.shadow_observer_ns,
            disagreement: pair.disagreement,
            registry_epoch,
        };
        self.journal.append(JournalEvent::Proposals {
            task_id: self.task_id,
            step,
            registry_epoch,
            observation: (*observation).into(),
            active: pair.active.into(),
            shadow: pair.shadow.into(),
            active_observer_ns: pair.active_observer_ns,
            shadow_observer_ns: pair.shadow_observer_ns,
            disagreement: pair.disagreement,
        })?;

        let receipt = self.authority.apply(pair.active);
        self.journal.append(JournalEvent::Transition {
            step,
            receipt: receipt.into(),
        })?;
        self.next_step += 1;
        self.proposals.push(proposal_record);

        if crash_point == Some(CrashPoint::AfterTransitionReceipt) {
            return Err(TaskRunnerError::InjectedCrash(
                CrashPoint::AfterTransitionReceipt,
            ));
        }

        let action_id = if let Some(action) = receipt.authorized_action {
            let action_id = action_id_for(self.task_id, receipt.sequence, action);
            self.journal.append(JournalEvent::ActionIntent {
                action_id: action_id.0,
                task_id: self.task_id,
                step,
                transition_sequence: receipt.sequence,
                action: action as u8,
            })?;
            self.intents.insert(
                action_id,
                PendingIntent {
                    action,
                    step,
                    transition_sequence: receipt.sequence,
                },
            );
            if crash_point == Some(CrashPoint::AfterActionIntent) {
                return Err(TaskRunnerError::InjectedCrash(
                    CrashPoint::AfterActionIntent,
                ));
            }

            let result = self.action_simulator.perform(action_id, action)?;
            if crash_point == Some(CrashPoint::AfterActionEffect) {
                return Err(TaskRunnerError::InjectedCrash(
                    CrashPoint::AfterActionEffect,
                ));
            }
            self.journal.append(JournalEvent::ActionCompleted {
                action_id: action_id.0,
                effect_index: result.effect_index,
                idempotent_reuse: result.idempotent_reuse,
            })?;
            self.completions.insert(
                action_id,
                PendingCompletion {
                    effect_index: result.effect_index,
                    idempotent_reuse: result.idempotent_reuse,
                },
            );
            if crash_point == Some(CrashPoint::AfterActionCompletion) {
                return Err(TaskRunnerError::InjectedCrash(
                    CrashPoint::AfterActionCompletion,
                ));
            }
            Some(action_id)
        } else {
            None
        };

        Ok(StepOutcome {
            step,
            active: pair.active,
            shadow: pair.shadow,
            disagreement: pair.disagreement,
            receipt,
            action_id,
        })
    }

    pub fn replace_active(
        &mut self,
        next: Box<dyn VersionedObserver>,
    ) -> Result<u64, TaskRunnerError> {
        let started = Instant::now();
        let registry = self.switchboard.replace_active(next)?;
        let swap_ns = started.elapsed().as_nanos().min(u64::MAX as u128) as u64;
        self.journal.append(JournalEvent::ObserverRegistry {
            registry,
            observer_swap_ns: Some(swap_ns),
        })?;
        self.observer_swaps += 1;
        self.observer_swap_ns += swap_ns as u128;
        Ok(swap_ns)
    }

    pub fn state(&self) -> State {
        self.authority.state()
    }

    pub fn next_step(&self) -> u32 {
        self.next_step
    }

    pub fn receipts(&self) -> &[Receipt] {
        self.authority.receipts()
    }

    pub fn metrics(&self) -> TaskMetrics {
        let rejected_proposals = self
            .authority
            .receipts()
            .iter()
            .filter(|receipt| !receipt.accepted())
            .count();
        let illegal_commits = self
            .proposals
            .iter()
            .zip(self.authority.receipts())
            .filter(|(proposal, receipt)| {
                receipt.accepted() && !is_standard_transition(proposal.active)
            })
            .count();
        let action_stats = self.action_simulator.stats();
        let authorized_actions = self
            .authority
            .receipts()
            .iter()
            .filter(|receipt| receipt.authorized_action.is_some())
            .count();
        TaskMetrics {
            active_observer_calls: self.proposals.len(),
            shadow_observer_calls: self.proposals.len(),
            active_observer_ns: self
                .proposals
                .iter()
                .map(|record| record.active_observer_ns as u128)
                .sum(),
            shadow_observer_ns: self
                .proposals
                .iter()
                .map(|record| record.shadow_observer_ns as u128)
                .sum(),
            observer_disagreements: self
                .proposals
                .iter()
                .filter(|record| record.disagreement && record.active != record.shadow)
                .count(),
            observer_swaps: self.observer_swaps,
            observer_registry_epochs: self
                .proposals
                .iter()
                .map(|p| p.registry_epoch as usize + 1)
                .max()
                .unwrap_or(1),
            observer_swap_ns: self.observer_swap_ns,
            rejected_proposals,
            illegal_commits,
            accepted_transitions: self
                .authority
                .receipts()
                .iter()
                .filter(|receipt| receipt.accepted())
                .count(),
            authorized_actions,
            recoveries: self.authority.recovery_count(),
            unique_actions: action_stats.unique_effects,
            duplicate_actions: action_stats.duplicate_effects.max(
                action_stats
                    .unique_effects
                    .saturating_sub(authorized_actions),
            ),
            missing_actions: authorized_actions.saturating_sub(action_stats.unique_effects),
            idempotent_reuses: self
                .completions
                .values()
                .filter(|v| v.idempotent_reuse)
                .count(),
            journal_bytes: self.journal.bytes_written(),
            action_ledger_bytes: self.action_simulator.bytes_written(),
            final_state: Some(self.authority.state()),
            replay_identity: self.journal.last_hash(),
        }
    }

    pub fn close(self) -> Result<(), TaskRunnerError> {
        self.journal.flush_close()?;
        self.action_simulator.flush_close()?;
        Ok(())
    }

    fn reconcile_actions(&mut self) -> Result<(), TaskRunnerError> {
        let mut expected = HashSet::with_capacity(self.authority.receipts().len());
        let receipts = self.authority.receipts().to_vec();
        for receipt in receipts {
            let Some(action) = receipt.authorized_action else {
                continue;
            };
            let id = action_id_for(self.task_id, receipt.sequence, action);
            expected.insert(id);
            let step = self
                .proposals
                .get(receipt.sequence as usize)
                .ok_or(TaskRunnerError::InvalidReplay(
                    "receipt has no proposal event",
                ))?
                .step;
            if let Some(intent) = self.intents.get(&id) {
                if intent.action != action
                    || intent.step != step
                    || intent.transition_sequence != receipt.sequence
                {
                    return Err(TaskRunnerError::ActionMismatch {
                        sequence: receipt.sequence,
                    });
                }
            } else {
                self.journal.append(JournalEvent::ActionIntent {
                    action_id: id.0,
                    task_id: self.task_id,
                    step,
                    transition_sequence: receipt.sequence,
                    action: action as u8,
                })?;
                self.intents.insert(
                    id,
                    PendingIntent {
                        action,
                        step,
                        transition_sequence: receipt.sequence,
                    },
                );
            }

            let ledger_effect = self.action_simulator.effect_for(id);
            if ledger_effect.is_some_and(|(recorded_action, _)| recorded_action != action) {
                return Err(TaskRunnerError::ActionMismatch {
                    sequence: receipt.sequence,
                });
            }
            let existing_completion = self.completions.get(&id).copied();
            if let Some(completion) = existing_completion {
                let Some((recorded_action, effect_index)) = ledger_effect else {
                    return Err(TaskRunnerError::ActionMismatch {
                        sequence: receipt.sequence,
                    });
                };
                if recorded_action != action || effect_index != completion.effect_index {
                    return Err(TaskRunnerError::ActionMismatch {
                        sequence: receipt.sequence,
                    });
                }
                continue;
            }

            let result = self.action_simulator.perform(id, action)?;
            self.journal.append(JournalEvent::ActionCompleted {
                action_id: id.0,
                effect_index: result.effect_index,
                idempotent_reuse: result.idempotent_reuse,
            })?;
            self.completions.insert(
                id,
                PendingCompletion {
                    effect_index: result.effect_index,
                    idempotent_reuse: result.idempotent_reuse,
                },
            );
        }
        if self.action_simulator.stats().unique_effects != expected.len() {
            return Err(TaskRunnerError::InvalidReplay(
                "effect ledger contains an unknown or duplicate action",
            ));
        }
        Ok(())
    }
}

fn action_id_for(task_id: u64, sequence: u64, action: Action) -> ActionId {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"RDC-EXPERIMENT-002-ACTION-ID-V1\0");
    hasher.update(&task_id.to_le_bytes());
    hasher.update(&sequence.to_le_bytes());
    hasher.update(&[action as u8]);
    let mut id = [0; 16];
    id.copy_from_slice(&hasher.finalize().as_bytes()[..16]);
    ActionId(id)
}

fn is_standard_transition(proposal: Proposal) -> bool {
    use Action as A;
    use State as S;
    matches!(
        (proposal.from, proposal.requested_to, proposal.action),
        (S::Idle, S::Observing, A::Observe)
            | (S::Observing, S::Deciding, A::Decide)
            | (S::Deciding, S::Acting, A::Execute)
            | (S::Deciding, S::Failed, A::Fail)
            | (S::Acting, S::Verifying, A::Verify)
            | (S::Acting, S::Failed, A::Fail)
            | (S::Verifying, S::Done, A::Complete)
            | (S::Verifying, S::Failed, A::Fail)
            | (S::Failed, S::Observing, A::Recover)
    )
}
