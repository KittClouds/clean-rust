use rdc_experiment_001::{
    DecisionCompiler, Evidence, Observation, Observer, Runtime, Signal, State, WorkflowObserver,
    standard_schema,
};

struct DelegatingObserver {
    inner: WorkflowObserver,
    calls: usize,
}

impl Observer for DelegatingObserver {
    fn propose(
        &mut self,
        state: State,
        observation: &Observation,
        recovery_count: u8,
    ) -> rdc_experiment_001::Proposal {
        self.calls += 1;
        self.inner.propose(state, observation, recovery_count)
    }
}

#[test]
fn standalone_observer_to_receipt_to_replay_smoke() {
    let compiler = DecisionCompiler::compile(&standard_schema()).unwrap();
    let mut runtime = Runtime::with_capacity(compiler.clone(), 5);
    let mut observer = DelegatingObserver {
        inner: WorkflowObserver,
        calls: 0,
    };
    let evidence = Evidence {
        code: 19,
        digest: [0x5a; 16],
    };

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
            observation = observation.with_confidence(950);
        }
        let receipt = runtime.step(&observation, &mut observer);
        assert!(receipt.accepted());
        if signal != Signal::Verified {
            assert_eq!(receipt.authorized_action, Some(receipt.proposal.action));
        }
    }

    assert_eq!(observer.calls, 5);
    assert_eq!(runtime.state(), State::Done);
    assert_eq!(runtime.receipts().len(), 5);
}
