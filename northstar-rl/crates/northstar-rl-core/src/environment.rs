use std::{
    path::{Path, PathBuf},
    sync::Arc,
};

use hashbrown::HashMap;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::{
    AccountState, ActionSpec, Digest, ENV_STEP_TAPE_V1, Episode, EpisodeTape, Error,
    ExecutionReceipt, ExecutionSpec, FeatureCellState, InstrumentContract, MappedFeatureTape,
    MappedRunRawTape, NumericContract, ObservationSpec, REWARD_PRIMITIVES_V1, Result,
    RewardPrimitives, RewardSpec, RlEnvSpec, SeedContract, SourceStatus, TerminationSpec,
    apply_transition, identity,
};

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum TerminalReason {
    EpisodeEnd,
    AccountFloor,
    DataEnd,
    SourceGap,
    ManualTestTermination,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct EnvironmentConfig {
    pub schema_version: String,
    pub runraw_tape_path: PathBuf,
    pub feature_tape_path: PathBuf,
    pub environment_spec: RlEnvSpec,
    pub observation_spec: ObservationSpec,
    pub action_spec: ActionSpec,
    pub instrument_contract: InstrumentContract,
    pub execution_spec: ExecutionSpec,
    pub reward_spec: RewardSpec,
    pub termination_spec: TerminationSpec,
    pub numeric_contract: NumericContract,
    pub seed_contract: SeedContract,
    pub episode_tape: EpisodeTape,
    pub initial_equity: f64,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct SeedAncestry {
    pub root_seed: u64,
    pub episode_seed: u64,
    pub component_seed: u64,
    pub component: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct EnvStepRecord {
    pub schema_version: String,
    pub episode_id: Digest,
    pub step_id: u64,
    pub source_row_id: u64,
    pub observation_hash: Digest,
    pub observation_spec_id: Digest,
    pub action: f32,
    pub action_spec_id: Digest,
    pub account_state_before_hash: Digest,
    pub account_state_after_hash: Digest,
    pub execution_receipt_id: Digest,
    pub reward: f64,
    pub reward_primitive_schema: String,
    pub reward_primitive_vector: [f64; 13],
    pub terminated: bool,
    pub truncated: bool,
    pub terminal_reason: Option<TerminalReason>,
    pub next_source_row_id: u64,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct TerminalReceipt {
    pub episode_id: Digest,
    pub final_step_id: u64,
    pub terminated: bool,
    pub truncated: bool,
    pub reason: TerminalReason,
    pub final_account_hash: Digest,
    pub trajectory_root: Digest,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ResetOutput {
    pub observation: Vec<f32>,
    pub episode_id: Digest,
    pub source_row_id: u64,
    pub seed_ancestry: SeedAncestry,
}

#[derive(Clone, Debug, PartialEq)]
pub struct StepOutput {
    pub observation: Vec<f32>,
    pub reward: f64,
    pub terminated: bool,
    pub truncated: bool,
    pub episode_id: Digest,
    pub step_id: u64,
    pub source_row_id: u64,
    pub execution_receipt_id: Digest,
    pub terminal_reason: Option<TerminalReason>,
}

pub struct Environment {
    runraw: Arc<MappedRunRawTape>,
    features: Arc<MappedFeatureTape>,
    config: EnvironmentConfig,
    row_lookup: HashMap<u64, usize>,
    episode: Option<Episode>,
    cursor: usize,
    last_index: usize,
    step_id: u64,
    initial_equity: f64,
    account: AccountState,
    steps: Vec<EnvStepRecord>,
    executions: Vec<ExecutionReceipt>,
    terminal_receipt: Option<TerminalReceipt>,
    closed: bool,
}

impl Environment {
    pub fn open(config_path: impl AsRef<Path>) -> Result<Self> {
        let config_path = config_path.as_ref();
        let bytes = std::fs::read(config_path)?;
        let mut config: EnvironmentConfig = serde_json::from_slice(&bytes)?;
        let base = config_path.parent().unwrap_or_else(|| Path::new("."));
        if config.runraw_tape_path.is_relative() {
            config.runraw_tape_path = base.join(&config.runraw_tape_path);
        }
        if config.feature_tape_path.is_relative() {
            config.feature_tape_path = base.join(&config.feature_tape_path);
        }
        Self::from_config(config)
    }

    pub fn from_config(config: EnvironmentConfig) -> Result<Self> {
        let runraw = Arc::new(MappedRunRawTape::open(&config.runraw_tape_path)?);
        let features = Arc::new(MappedFeatureTape::open(&config.feature_tape_path)?);
        validate_config(&config, &runraw, &features)?;
        let mut row_lookup = HashMap::with_capacity(runraw.rows().len());
        for (index, row) in runraw.rows().iter().enumerate() {
            if row_lookup.insert(row.source_row_id, index).is_some() {
                return Err(Error::InvalidTape(format!(
                    "duplicate source_row_id {}",
                    row.source_row_id
                )));
            }
        }
        let initial_equity = config.initial_equity;
        Ok(Self {
            runraw,
            features,
            config,
            row_lookup,
            episode: None,
            cursor: 0,
            last_index: 0,
            step_id: 0,
            initial_equity,
            account: AccountState::initial(initial_equity)?,
            steps: Vec::new(),
            executions: Vec::new(),
            terminal_receipt: None,
            closed: false,
        })
    }

    pub fn reset_episode(
        &mut self,
        episode_id: Option<Digest>,
        root_seed: u64,
    ) -> Result<ResetOutput> {
        self.ensure_open()?;
        let episode = match episode_id {
            Some(id) => self
                .config
                .episode_tape
                .episodes
                .iter()
                .find(|episode| episode.episode_id == id),
            None => self.config.episode_tape.episodes.first(),
        }
        .cloned()
        .ok_or_else(|| Error::Environment("episode ID is not present in EPISODE_TAPE_V1".into()))?;
        let cursor = *self
            .row_lookup
            .get(&episode.first_actionable_row)
            .ok_or_else(|| Error::InvalidTape("episode first actionable row is absent".into()))?;
        let last_index = *self
            .row_lookup
            .get(&episode.last_source_row)
            .ok_or_else(|| Error::InvalidTape("episode last row is absent".into()))?;
        self.episode = Some(episode.clone());
        self.cursor = cursor;
        self.last_index = last_index;
        self.step_id = 0;
        self.account = AccountState::initial(self.initial_equity)?;
        self.steps.clear();
        self.executions.clear();
        self.terminal_receipt = None;
        let observation = self.observation_at(cursor)?;
        let episode_seed = derive_seed(root_seed, episode.episode_id.as_ref());
        let component_seed = derive_seed(episode_seed, b"environment-kernel");
        Ok(ResetOutput {
            observation,
            episode_id: episode.episode_id,
            source_row_id: self.runraw.rows()[cursor].source_row_id,
            seed_ancestry: SeedAncestry {
                root_seed,
                episode_seed,
                component_seed,
                component: "environment_kernel".into(),
            },
        })
    }

    pub fn step(&mut self, action: f32) -> Result<StepOutput> {
        self.ensure_open()?;
        let episode = self
            .episode
            .clone()
            .ok_or_else(|| Error::Environment("reset must be called before step".into()))?;
        if self.terminal_receipt.is_some() {
            return Err(Error::Environment(
                "step called after terminal transition".into(),
            ));
        }
        if self.cursor >= self.last_index {
            return Err(Error::Environment(
                "episode contains no further execution interval".into(),
            ));
        }
        let source_row = self.runraw.rows()[self.cursor];
        let execution_row = self.runraw.rows()[self.cursor + 1];
        let observation = self.observation_at(self.cursor)?;
        let observation_hash = hash_observation(&observation);
        let before_hash = self.account.id()?;
        self.step_id += 1;

        let (reward, receipt_id, primitives, next_account, terminal_reason, terminated, truncated) =
            if execution_row.status() == SourceStatus::Gap {
                (
                    0.0,
                    Digest::ZERO,
                    RewardPrimitives::default(),
                    self.account,
                    Some(TerminalReason::SourceGap),
                    self.config.termination_spec.source_gap_is_termination,
                    !self.config.termination_spec.source_gap_is_termination,
                )
            } else {
                let transition = apply_transition(
                    self.account,
                    source_row.source_row_id,
                    execution_row,
                    action,
                    &self.config.instrument_contract,
                    &self.config.execution_spec,
                )?;
                let reward = transition.primitives.equity_delta / self.initial_equity;
                let receipt_id = transition.receipt.execution_receipt_id;
                let next_account = transition.after;
                let primitives = transition.primitives;
                self.executions.push(transition.receipt);
                if next_account.equity <= self.config.termination_spec.account_floor {
                    (
                        reward,
                        receipt_id,
                        primitives,
                        next_account,
                        Some(TerminalReason::AccountFloor),
                        true,
                        false,
                    )
                } else if self.cursor + 1 == self.last_index {
                    let truncation = self.config.termination_spec.episode_end_is_truncation;
                    (
                        reward,
                        receipt_id,
                        primitives,
                        next_account,
                        Some(TerminalReason::EpisodeEnd),
                        !truncation,
                        truncation,
                    )
                } else {
                    (
                        reward,
                        receipt_id,
                        primitives,
                        next_account,
                        None,
                        false,
                        false,
                    )
                }
            };

        self.account = next_account;
        self.cursor += 1;
        let after_hash = self.account.id()?;
        let next_observation = if terminated || truncated {
            self.observation_or_zeros(self.cursor)
        } else {
            self.observation_at(self.cursor)?
        };
        let record = EnvStepRecord {
            schema_version: ENV_STEP_TAPE_V1.into(),
            episode_id: episode.episode_id,
            step_id: self.step_id,
            source_row_id: source_row.source_row_id,
            observation_hash,
            observation_spec_id: self.config.observation_spec.observation_spec_id,
            action,
            action_spec_id: self.config.action_spec.action_spec_id,
            account_state_before_hash: before_hash,
            account_state_after_hash: after_hash,
            execution_receipt_id: receipt_id,
            reward,
            reward_primitive_schema: REWARD_PRIMITIVES_V1.into(),
            reward_primitive_vector: primitives.vector(),
            terminated,
            truncated,
            terminal_reason: terminal_reason.clone(),
            next_source_row_id: execution_row.source_row_id,
        };
        self.steps.push(record);
        if let Some(reason) = terminal_reason.clone() {
            let trajectory_root = self.trajectory_root()?;
            self.terminal_receipt = Some(TerminalReceipt {
                episode_id: episode.episode_id,
                final_step_id: self.step_id,
                terminated,
                truncated,
                reason,
                final_account_hash: after_hash,
                trajectory_root,
            });
        }
        Ok(StepOutput {
            observation: next_observation,
            reward,
            terminated,
            truncated,
            episode_id: episode.episode_id,
            step_id: self.step_id,
            source_row_id: execution_row.source_row_id,
            execution_receipt_id: receipt_id,
            terminal_reason,
        })
    }

    pub fn current_observation(&self) -> Result<Vec<f32>> {
        self.ensure_open()?;
        self.observation_at(self.cursor)
    }

    pub fn account(&self) -> AccountState {
        self.account
    }
    pub fn steps(&self) -> &[EnvStepRecord] {
        &self.steps
    }
    pub fn executions(&self) -> &[ExecutionReceipt] {
        &self.executions
    }
    pub fn terminal_receipt(&self) -> Option<&TerminalReceipt> {
        self.terminal_receipt.as_ref()
    }
    pub fn config(&self) -> &EnvironmentConfig {
        &self.config
    }
    pub fn close(&mut self) {
        self.closed = true;
    }

    pub fn trajectory_root(&self) -> Result<Digest> {
        identity(b"northstar-env-trajectory-v1", &self.steps)
    }

    pub fn render_text(&self) -> String {
        format!(
            "step={} row={} equity={:.6} quantity={:.6} exposure={:.6} drawdown={:.6}",
            self.step_id,
            self.runraw
                .rows()
                .get(self.cursor)
                .map_or(0, |row| row.source_row_id),
            self.account.equity,
            self.account.quantity,
            self.account.actual_exposure,
            self.account.drawdown,
        )
    }

    fn observation_at(&self, index: usize) -> Result<Vec<f32>> {
        let row = self
            .runraw
            .rows()
            .get(index)
            .ok_or_else(|| Error::Environment("observation row is outside RunRaw".into()))?;
        let depth = self.config.observation_spec.history_depth as usize;
        let first = index
            .checked_add(1)
            .and_then(|value| value.checked_sub(depth))
            .ok_or_else(|| Error::Environment("observation history precedes the episode".into()))?;
        if self.runraw.rows()[first].session_id != row.session_id
            || self.runraw.rows()[first].instrument_id != row.instrument_id
        {
            return Err(Error::Environment(
                "observation history crosses an episode boundary".into(),
            ));
        }
        let mut observation =
            Vec::with_capacity(self.config.observation_spec.ordered_feature_ids.len() * depth);
        for row_index in first..=index {
            for feature_id in &self.config.observation_spec.ordered_feature_ids {
                let (value, state, knowledge_time) =
                    self.features.cell(feature_id, row_index).ok_or_else(|| {
                        Error::InvalidTape(format!(
                            "missing feature cell {feature_id}[{row_index}]"
                        ))
                    })?;
                if state != FeatureCellState::Available || knowledge_time > row.event_time {
                    return Err(Error::Environment(format!(
                        "feature {feature_id} is not causally available at row {}",
                        row.source_row_id
                    )));
                }
                let converted = value as f32;
                if !converted.is_finite() {
                    return Err(Error::Environment(format!(
                        "feature {feature_id} cannot be represented as finite float32"
                    )));
                }
                observation.push(converted);
            }
        }
        Ok(observation)
    }

    fn observation_or_zeros(&self, index: usize) -> Vec<f32> {
        self.observation_at(index).unwrap_or_else(|_| {
            vec![
                0.0;
                self.config
                    .observation_spec
                    .output_shape
                    .iter()
                    .product::<u32>() as usize
            ]
        })
    }

    fn ensure_open(&self) -> Result<()> {
        if self.closed {
            Err(Error::Environment("environment is closed".into()))
        } else {
            Ok(())
        }
    }
}

fn validate_config(
    config: &EnvironmentConfig,
    runraw: &MappedRunRawTape,
    features: &MappedFeatureTape,
) -> Result<()> {
    let mut environment_spec = config.environment_spec.clone();
    let environment_id = environment_spec.environment_id;
    environment_spec.environment_id = Digest::ZERO;
    verify_id(
        environment_id,
        identity(b"northstar-rl-env-spec-v1", &environment_spec)?,
        "environment",
    )?;
    if config.environment_spec.implementation_hashes != crate::kernel_implementation_hashes() {
        return Err(Error::InvalidContract(
            "environment implementation hashes do not match this kernel".into(),
        ));
    }
    let mut observation_spec = config.observation_spec.clone();
    let observation_id = observation_spec.observation_spec_id;
    observation_spec.observation_spec_id = Digest::ZERO;
    verify_id(
        observation_id,
        identity(b"northstar-observation-spec-v1", &observation_spec)?,
        "observation",
    )?;
    let mut action_spec = config.action_spec.clone();
    let action_id = action_spec.action_spec_id;
    action_spec.action_spec_id = Digest::ZERO;
    verify_id(
        action_id,
        identity(b"northstar-action-spec-target-exposure-v1", &action_spec)?,
        "action",
    )?;
    let mut instrument = config.instrument_contract.clone();
    let instrument_id = instrument.instrument_contract_id;
    instrument.instrument_contract_id = Digest::ZERO;
    verify_id(
        instrument_id,
        identity(b"northstar-instrument-contract-v1", &instrument)?,
        "instrument",
    )?;
    let mut execution = config.execution_spec.clone();
    let execution_id = execution.execution_spec_id;
    execution.execution_spec_id = Digest::ZERO;
    verify_id(
        execution_id,
        identity(b"northstar-execution-spec-v1", &execution)?,
        "execution",
    )?;
    let mut reward = config.reward_spec.clone();
    let reward_id = reward.reward_spec_id;
    reward.reward_spec_id = Digest::ZERO;
    verify_id(
        reward_id,
        identity(b"northstar-reward-spec-v1", &reward)?,
        "reward",
    )?;
    let mut termination = config.termination_spec.clone();
    let termination_id = termination.termination_spec_id;
    termination.termination_spec_id = Digest::ZERO;
    verify_id(
        termination_id,
        identity(b"northstar-termination-spec-v1", &termination)?,
        "termination",
    )?;
    let mut numeric = config.numeric_contract.clone();
    let numeric_id = numeric.numeric_contract_id;
    numeric.numeric_contract_id = Digest::ZERO;
    verify_id(
        numeric_id,
        identity(b"northstar-numeric-contract-v1", &numeric)?,
        "numeric",
    )?;
    let mut seed = config.seed_contract.clone();
    let seed_id = seed.seed_contract_id;
    seed.seed_contract_id = Digest::ZERO;
    verify_id(
        seed_id,
        identity(b"northstar-seed-contract-v1", &seed)?,
        "seed",
    )?;
    if runraw.tape_id()? != config.environment_spec.runraw_tape_id {
        return Err(Error::InvalidContract(
            "RL_ENV_SPEC_V1 RunRaw identity mismatch".into(),
        ));
    }
    if features.tape_id()? != config.environment_spec.feature_tape_id {
        return Err(Error::InvalidContract(
            "RL_ENV_SPEC_V1 Feature Tape identity mismatch".into(),
        ));
    }
    let bindings = [
        (
            config.observation_spec.observation_spec_id,
            config.environment_spec.observation_spec_id,
            "observation",
        ),
        (
            config.action_spec.action_spec_id,
            config.environment_spec.action_spec_id,
            "action",
        ),
        (
            config.instrument_contract.instrument_contract_id,
            config.environment_spec.instrument_contract_id,
            "instrument",
        ),
        (
            config.execution_spec.execution_spec_id,
            config.environment_spec.execution_spec_id,
            "execution",
        ),
        (
            config.reward_spec.reward_spec_id,
            config.environment_spec.reward_spec_id,
            "reward",
        ),
        (
            config.termination_spec.termination_spec_id,
            config.environment_spec.termination_spec_id,
            "termination",
        ),
        (
            config.numeric_contract.numeric_contract_id,
            config.environment_spec.numeric_contract_id,
            "numeric",
        ),
        (
            config.seed_contract.seed_contract_id,
            config.environment_spec.seed_contract_id,
            "seed",
        ),
    ];
    for (actual, declared, name) in bindings {
        if actual != declared {
            return Err(Error::InvalidContract(format!("{name} identity mismatch")));
        }
    }
    let feature_count = config.observation_spec.ordered_feature_ids.len() as u32;
    let expected_shape = match config.observation_spec.layout {
        crate::ObservationLayout::Flat => vec![feature_count],
        crate::ObservationLayout::WindowedMatrix => {
            vec![config.observation_spec.history_depth, feature_count]
        }
    };
    if config.observation_spec.output_shape != expected_shape {
        return Err(Error::InvalidContract(
            "observation output shape does not match layout, history, and feature IDs".into(),
        ));
    }
    if config.action_spec.low != -1.0
        || config.action_spec.high != 1.0
        || config.action_spec.shape != vec![1]
        || config.action_spec.dtype != "float32"
        || config.action_spec.semantics != "target_normalized_exposure"
    {
        return Err(Error::InvalidContract(
            "unsupported action contract for ACTION_SPEC_TARGET_EXPOSURE_V1".into(),
        ));
    }
    if config.execution_spec.action_source != "completed_bar_close"
        || config.execution_spec.fill_timing != "next_eligible_bar_open"
        || config.execution_spec.reference_fill_price != "source_open"
    {
        return Err(Error::InvalidContract(
            "unsupported execution timing policy".into(),
        ));
    }
    if config.reward_spec.formula != "equity_delta / initial_equity" {
        return Err(Error::InvalidContract(
            "unsupported reward formula for REWARD_SPEC_V1".into(),
        ));
    }
    if config.numeric_contract.authority_float != "ieee754_binary64_little_endian"
        || config.numeric_contract.observation_float != "ieee754_binary32_contiguous"
        || config.numeric_contract.action_float != "ieee754_binary32_scalar_box_1"
        || config.numeric_contract.non_finite_policy
            != "reject_authority_reject_observation_reject_action"
    {
        return Err(Error::InvalidContract(
            "unsupported numerical contract".into(),
        ));
    }
    if config.instrument_contract.conversion_rule != "identity_quote_equals_account" {
        return Err(Error::InvalidContract(
            "unsupported currency conversion rule".into(),
        ));
    }
    Ok(())
}

fn verify_id(declared: Digest, calculated: Digest, name: &str) -> Result<()> {
    if declared != calculated {
        Err(Error::InvalidContract(format!(
            "{name} self-identity mismatch"
        )))
    } else {
        Ok(())
    }
}

fn hash_observation(observation: &[f32]) -> Digest {
    Digest::hash(
        b"northstar-observation-f32-v1",
        bytemuck::cast_slice(observation),
    )
}

pub fn derive_seed(parent: u64, component: &[u8]) -> u64 {
    let digest = Digest::hash_parts(
        b"northstar-seed-derivation-v1",
        [&parent.to_le_bytes(), component],
    );
    u64::from_le_bytes(digest.0[..8].try_into().expect("fixed digest"))
}

impl AsRef<[u8]> for Digest {
    fn as_ref(&self) -> &[u8] {
        &self.0
    }
}
