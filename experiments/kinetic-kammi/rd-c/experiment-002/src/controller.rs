use rdc_experiment_001::{
    Action, DecisionCompiler, Proposal, Receipt, RejectionReason, Runtime, State, TransitionSpec,
    receipt_identity, standard_schema,
};

pub trait Authority {
    fn apply(&mut self, proposal: Proposal) -> Receipt;
    fn state(&self) -> State;
    fn recovery_count(&self) -> u8;
    fn receipts(&self) -> &[Receipt];
    fn reset(&mut self);
}

pub struct CompiledAuthority {
    runtime: Runtime,
}

impl CompiledAuthority {
    pub fn standard() -> Self {
        Self::from_schema(&standard_schema()).expect("standard schema is valid")
    }

    pub fn from_compiler(compiler: DecisionCompiler) -> Self {
        Self {
            runtime: Runtime::new(compiler),
        }
    }

    pub fn from_schema(
        schema: &[TransitionSpec],
    ) -> Result<Self, rdc_experiment_001::CompileError> {
        Ok(Self {
            runtime: Runtime::new(DecisionCompiler::compile(schema)?),
        })
    }
}

impl Authority for CompiledAuthority {
    fn apply(&mut self, proposal: Proposal) -> Receipt {
        self.runtime.apply(proposal)
    }

    fn state(&self) -> State {
        self.runtime.state()
    }

    fn recovery_count(&self) -> u8 {
        self.runtime.recovery_count()
    }

    fn receipts(&self) -> &[Receipt] {
        self.runtime.receipts()
    }

    fn reset(&mut self) {
        self.runtime.reset();
    }
}

pub struct HandwrittenAuthority {
    state: State,
    recovery_count: u8,
    receipts: Vec<Receipt>,
}

impl Default for HandwrittenAuthority {
    fn default() -> Self {
        Self::with_capacity(0)
    }
}

impl HandwrittenAuthority {
    pub fn with_capacity(receipt_capacity: usize) -> Self {
        Self {
            state: State::Idle,
            recovery_count: 0,
            receipts: Vec::with_capacity(receipt_capacity),
        }
    }

    fn validate(&self, proposal: Proposal) -> Option<RejectionReason> {
        if proposal.from != self.state {
            return Some(RejectionReason::StaleFromState);
        }
        if proposal
            .confidence
            .is_some_and(|confidence| confidence > 1000)
        {
            return Some(RejectionReason::InvalidConfidence);
        }
        let guard = match (proposal.from, proposal.requested_to, proposal.action) {
            (State::Idle, State::Observing, Action::Observe) => (None, false, None),
            (State::Observing, State::Deciding, Action::Decide) => (None, true, None),
            (State::Deciding, State::Acting, Action::Execute) => (Some(700), true, None),
            (State::Deciding, State::Failed, Action::Fail) => (None, false, None),
            (State::Acting, State::Verifying, Action::Verify) => (None, false, None),
            (State::Acting, State::Failed, Action::Fail) => (None, false, None),
            (State::Verifying, State::Done, Action::Complete) => (None, true, None),
            (State::Verifying, State::Failed, Action::Fail) => (None, false, None),
            (State::Failed, State::Observing, Action::Recover) => (Some(600), true, Some(2)),
            _ => return Some(RejectionReason::UnknownTransition),
        };

        if let Some(minimum) = guard.0 {
            let Some(confidence) = proposal.confidence else {
                return Some(RejectionReason::ConfidenceMissing);
            };
            if confidence < minimum {
                return Some(RejectionReason::ConfidenceTooLow);
            }
        }
        if guard.1 && proposal.evidence.is_none() {
            return Some(RejectionReason::EvidenceMissing);
        }
        if guard.2.is_some_and(|limit| self.recovery_count >= limit) {
            return Some(RejectionReason::RecoveryLimit);
        }
        None
    }
}

impl Authority for HandwrittenAuthority {
    fn apply(&mut self, proposal: Proposal) -> Receipt {
        let before = self.state;
        let previous_hash = self.receipts.last().map_or([0; 32], |receipt| receipt.hash);
        let rejection = self.validate(proposal);
        let authorized_action = if rejection.is_none() {
            self.state = proposal.requested_to;
            if proposal.action == Action::Recover {
                self.recovery_count = self.recovery_count.saturating_add(1);
            }
            Some(proposal.action)
        } else {
            None
        };
        let sequence = self.receipts.len() as u64;
        let hash = receipt_identity(
            sequence,
            before,
            self.state,
            proposal,
            authorized_action,
            rejection,
            previous_hash,
        );
        let receipt = Receipt {
            sequence,
            before,
            after: self.state,
            proposal,
            authorized_action,
            rejection,
            previous_hash,
            hash,
        };
        self.receipts.push(receipt);
        receipt
    }

    fn state(&self) -> State {
        self.state
    }

    fn recovery_count(&self) -> u8 {
        self.recovery_count
    }

    fn receipts(&self) -> &[Receipt] {
        &self.receipts
    }

    fn reset(&mut self) {
        self.state = State::Idle;
        self.recovery_count = 0;
        self.receipts.clear();
    }
}
