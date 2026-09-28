use rdc_runtime_contracts_v1::{ActionCode, InspectionKind, InspectionResult};

use crate::domain::PublicEpisode;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum State {
    Idle = 0,
    Observing = 1,
    Deciding = 2,
    Acting = 3,
    Verifying = 4,
    Done = 5,
    Failed = 6,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
enum Event {
    Begin = 0,
    ObservationReady = 1,
    Commit = 2,
    Reobserve = 3,
    RejectProposal = 4,
    ActionApplied = 5,
    VerifyPass = 6,
    VerifyFail = 7,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct TransitionReceipt {
    from: State,
    event: Event,
    to: State,
    action: Option<ActionCode>,
    hash: [u8; 32],
}

#[derive(Clone, Copy, Debug)]
pub struct AuthorityResult {
    pub final_state: State,
    pub selected_action: Option<ActionCode>,
    pub task_completed: bool,
    pub illegal_commits: u32,
    pub rejected_proposals: u32,
    pub task_action_effects: u32,
    pub replay_identity_ok: bool,
    pub identity: [u8; 32],
}

pub fn execute(
    public: PublicEpisode,
    inspection: Option<InspectionResult>,
    correct: ActionCode,
) -> AuthorityResult {
    let proposed = inspection.map_or(Some(public.active), |result| result.proposed_action);
    let mut receipts = Vec::with_capacity(6);
    let mut state = State::Idle;
    let mut previous = [0; 32];
    let mut illegal_commits = 0;
    let mut rejected_proposals = 0;
    let mut task_action_effects = 0;

    record(&mut receipts, &mut state, &mut previous, Event::Begin, None);
    record(
        &mut receipts,
        &mut state,
        &mut previous,
        Event::ObservationReady,
        None,
    );
    match proposed {
        None => {
            record(
                &mut receipts,
                &mut state,
                &mut previous,
                Event::Reobserve,
                None,
            );
        }
        Some(action) if action.0 > 1 => {
            rejected_proposals += 1;
            record(
                &mut receipts,
                &mut state,
                &mut previous,
                Event::RejectProposal,
                Some(action),
            );
        }
        Some(action) => {
            let committed = record(
                &mut receipts,
                &mut state,
                &mut previous,
                Event::Commit,
                Some(action),
            );
            if !committed {
                illegal_commits += 1;
            } else {
                task_action_effects += 1;
                record(
                    &mut receipts,
                    &mut state,
                    &mut previous,
                    Event::ActionApplied,
                    Some(action),
                );
                let verification = if action == correct {
                    Event::VerifyPass
                } else {
                    Event::VerifyFail
                };
                record(
                    &mut receipts,
                    &mut state,
                    &mut previous,
                    verification,
                    Some(action),
                );
            }
        }
    }
    let selected_action = receipts
        .iter()
        .find(|receipt| receipt.event == Event::Commit)
        .and_then(|receipt| receipt.action);
    let replay_identity_ok = replay(&receipts, state, previous);
    AuthorityResult {
        final_state: state,
        selected_action,
        task_completed: state == State::Done,
        illegal_commits,
        rejected_proposals,
        task_action_effects,
        replay_identity_ok,
        identity: previous,
    }
}

fn record(
    receipts: &mut Vec<TransitionReceipt>,
    state: &mut State,
    previous: &mut [u8; 32],
    event: Event,
    action: Option<ActionCode>,
) -> bool {
    let from = *state;
    let Some(to) = transition(from, event) else {
        return false;
    };
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"RDC-E007-AUTHORITY-RECEIPT-V1\0");
    hasher.update(previous);
    hasher.update(&[from as u8, event as u8, to as u8]);
    hasher.update(&action.map_or(u16::MAX, |value| value.0).to_le_bytes());
    let hash = *hasher.finalize().as_bytes();
    receipts.push(TransitionReceipt {
        from,
        event,
        to,
        action,
        hash,
    });
    *state = to;
    *previous = hash;
    true
}

fn replay(
    receipts: &[TransitionReceipt],
    expected_state: State,
    expected_identity: [u8; 32],
) -> bool {
    let mut state = State::Idle;
    let mut previous = [0; 32];
    for receipt in receipts {
        if receipt.from != state || transition(state, receipt.event) != Some(receipt.to) {
            return false;
        }
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"RDC-E007-AUTHORITY-RECEIPT-V1\0");
        hasher.update(&previous);
        hasher.update(&[receipt.from as u8, receipt.event as u8, receipt.to as u8]);
        hasher.update(
            &receipt
                .action
                .map_or(u16::MAX, |value| value.0)
                .to_le_bytes(),
        );
        previous = *hasher.finalize().as_bytes();
        if previous != receipt.hash {
            return false;
        }
        state = receipt.to;
    }
    state == expected_state && previous == expected_identity
}

fn transition(state: State, event: Event) -> Option<State> {
    match (state, event) {
        (State::Idle, Event::Begin) => Some(State::Observing),
        (State::Observing, Event::ObservationReady) => Some(State::Deciding),
        (State::Deciding, Event::Commit) => Some(State::Acting),
        (State::Deciding, Event::Reobserve | Event::RejectProposal) => Some(State::Observing),
        (State::Acting, Event::ActionApplied) => Some(State::Verifying),
        (State::Verifying, Event::VerifyPass) => Some(State::Done),
        (State::Verifying, Event::VerifyFail) => Some(State::Failed),
        _ => None,
    }
}

pub fn outcome_kind(inspection: Option<InspectionResult>) -> Option<InspectionKind> {
    inspection.map(|result| result.kind)
}

#[cfg(test)]
mod tests {
    use rdc_runtime_contracts_v1::{
        ActionCode, InspectionKind, InspectionReply, InspectionResult, TransportStatus,
        inspection::NO_ACTION,
    };

    use super::{State, execute};
    use crate::domain::PublicEpisode;

    fn episode() -> PublicEpisode {
        PublicEpisode {
            id: 1,
            domain_id: 2,
            active: ActionCode(0),
            shadow: ActionCode(1),
            confidence_milli: 700,
            warning: false,
            source_age: 0,
            revision_gap: 0,
            audit_selected: false,
            query_cost_units: 1,
        }
    }

    #[test]
    fn unknown_and_failed_results_reobserve_without_fallback_actions() {
        for (transport, kind) in [
            (TransportStatus::Malformed, InspectionKind::Unknown),
            (TransportStatus::Timeout, InspectionKind::Failed),
        ] {
            let reply = InspectionReply {
                transport,
                candidate: NO_ACTION,
                competing_candidate: NO_ACTION,
                confidence_milli: 0,
                signature_valid: false,
                source_revision: 0,
                payload_digest: [0; 32],
            };
            let result = InspectionResult::classify(ActionCode(0), reply);
            assert_eq!(result.kind, kind);
            let run = execute(episode(), Some(result), ActionCode(0));
            assert_eq!(run.final_state, State::Observing);
            assert_eq!(run.selected_action, None);
            assert_eq!(run.task_action_effects, 0);
            assert!(run.replay_identity_ok);
        }
    }
}
