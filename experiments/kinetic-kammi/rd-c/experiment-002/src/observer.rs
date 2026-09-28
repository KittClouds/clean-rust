use std::time::Instant;

use rdc_experiment_001::{
    Action, Observation, Observer, Proposal, Signal, State, WorkflowObserver,
};

use crate::model::{
    INPUT_SCHEMA_V1, OBSERVER_INTERFACE_VERSION, OUTPUT_SCHEMA_V1, ObserverManifest,
    ObserverRegistry,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WorkflowBehavior {
    Normal,
    MisrouteApprove,
}

pub trait VersionedObserver {
    fn manifest(&self) -> &ObserverManifest;
    fn propose(&mut self, state: State, observation: &Observation, recovery_count: u8) -> Proposal;
}

pub struct WorkflowAdapter {
    manifest: ObserverManifest,
    behavior: WorkflowBehavior,
    inner: WorkflowObserver,
}

impl WorkflowAdapter {
    pub fn new(implementation_id: &str, behavior: WorkflowBehavior) -> Self {
        Self {
            manifest: ObserverManifest {
                interface_version: OBSERVER_INTERFACE_VERSION,
                implementation_id: implementation_id.to_owned(),
                input_schema: INPUT_SCHEMA_V1.to_owned(),
                output_schema: OUTPUT_SCHEMA_V1.to_owned(),
                normalization_contract: "identity-v1".to_owned(),
            },
            behavior,
            inner: WorkflowObserver,
        }
    }
}

impl VersionedObserver for WorkflowAdapter {
    fn manifest(&self) -> &ObserverManifest {
        &self.manifest
    }

    fn propose(&mut self, state: State, observation: &Observation, recovery_count: u8) -> Proposal {
        if self.behavior == WorkflowBehavior::MisrouteApprove
            && state == State::Deciding
            && observation.signal == Signal::Approve
        {
            return Proposal {
                from: state,
                requested_to: State::Done,
                action: Action::Complete,
                confidence: observation.confidence,
                evidence: observation.evidence,
            };
        }
        self.inner.propose(state, observation, recovery_count)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObserverContractError {
    UnsupportedInterfaceVersion(u16),
    WrongInputSchema(String),
    WrongOutputSchema(String),
    EmptyImplementationId,
    EmptyNormalizationContract,
}

impl std::fmt::Display for ObserverContractError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::UnsupportedInterfaceVersion(version) => {
                write!(f, "unsupported observer interface version {version}")
            }
            Self::WrongInputSchema(schema) => {
                write!(f, "unsupported observer input schema {schema}")
            }
            Self::WrongOutputSchema(schema) => {
                write!(f, "unsupported observer output schema {schema}")
            }
            Self::EmptyImplementationId => {
                f.write_str("observer implementation ID must be nonempty")
            }
            Self::EmptyNormalizationContract => {
                f.write_str("normalization contract must be nonempty")
            }
        }
    }
}

impl std::error::Error for ObserverContractError {}

pub struct ObserverPairOutput {
    pub active: Proposal,
    pub shadow: Proposal,
    pub active_observer_ns: u64,
    pub shadow_observer_ns: u64,
    pub disagreement: bool,
}

pub struct ObserverSwitchboard {
    active: Box<dyn VersionedObserver>,
    shadow: Box<dyn VersionedObserver>,
    epoch: u64,
}

impl ObserverSwitchboard {
    pub fn new(
        active: Box<dyn VersionedObserver>,
        shadow: Box<dyn VersionedObserver>,
    ) -> Result<Self, ObserverContractError> {
        validate_manifest(active.manifest())?;
        validate_manifest(shadow.manifest())?;
        Ok(Self {
            active,
            shadow,
            epoch: 0,
        })
    }

    pub fn epoch(&self) -> u64 {
        self.epoch
    }

    pub fn active_manifest(&self) -> &ObserverManifest {
        self.active.manifest()
    }

    pub fn shadow_manifest(&self) -> &ObserverManifest {
        self.shadow.manifest()
    }

    pub fn registry(&self) -> ObserverRegistry {
        ObserverRegistry {
            epoch: self.epoch,
            active: self.active.manifest().clone(),
            shadow: self.shadow.manifest().clone(),
        }
    }

    pub(crate) fn restore_epoch(&mut self, epoch: u64) {
        self.epoch = epoch;
    }

    pub fn replace_active(
        &mut self,
        next: Box<dyn VersionedObserver>,
    ) -> Result<ObserverRegistry, ObserverContractError> {
        validate_manifest(next.manifest())?;
        self.active = next;
        self.epoch = self.epoch.saturating_add(1);
        Ok(self.registry())
    }

    pub fn propose_pair(
        &mut self,
        state: State,
        observation: &Observation,
        recovery_count: u8,
    ) -> ObserverPairOutput {
        // Both observers see the identical immutable observation and authoritative state.
        let started = Instant::now();
        let active = self.active.propose(state, observation, recovery_count);
        let active_observer_ns = started.elapsed().as_nanos().min(u64::MAX as u128) as u64;

        let started = Instant::now();
        let shadow = self.shadow.propose(state, observation, recovery_count);
        let shadow_observer_ns = started.elapsed().as_nanos().min(u64::MAX as u128) as u64;

        ObserverPairOutput {
            active,
            shadow,
            active_observer_ns,
            shadow_observer_ns,
            disagreement: active != shadow,
        }
    }
}

fn validate_manifest(manifest: &ObserverManifest) -> Result<(), ObserverContractError> {
    if manifest.interface_version != OBSERVER_INTERFACE_VERSION {
        return Err(ObserverContractError::UnsupportedInterfaceVersion(
            manifest.interface_version,
        ));
    }
    if manifest.implementation_id.trim().is_empty() {
        return Err(ObserverContractError::EmptyImplementationId);
    }
    if manifest.input_schema != INPUT_SCHEMA_V1 {
        return Err(ObserverContractError::WrongInputSchema(
            manifest.input_schema.clone(),
        ));
    }
    if manifest.output_schema != OUTPUT_SCHEMA_V1 {
        return Err(ObserverContractError::WrongOutputSchema(
            manifest.output_schema.clone(),
        ));
    }
    if manifest.normalization_contract.trim().is_empty() {
        return Err(ObserverContractError::EmptyNormalizationContract);
    }
    Ok(())
}
