# FORGE-RL-02 — Learning Campaign Control Plane

FORGE-RL-02 freezes experimental method before learner execution. It turns a
future learning run into a content-addressed engineering object:

```text
World -> Partition -> Transform fit -> Experiment -> Learner spec
      -> Campaign -> Evaluation -> Policy artifact contract
```

The sealed surface is `NORTHSTAR_STRATEGY_EXPERIMENT_RUNTIME_V1`.

## Hard prohibition

This gate contains no learner executor. It does not call `.learn()`, construct an
optimizer, perform a gradient update, create weights, or emit a checkpoint. The
future PPO declaration in `LEARNER_SPEC_V1` is configuration data whose
`execution_permission` is `PROHIBITED_UNTIL_DEGEN_RL_01`.

## Authority contracts

- `PARTITION_TAPE_V1` assigns complete episode groups chronologically to train,
  development, evaluation, or boundary embargo. Its sealed identity is bound by
  every downstream campaign object.
- `TRANSFORM_STATE_V1` is fitted only from declared training episode IDs. The
  initial implementation uses f64 Welford mean/sample-standard-deviation state,
  explicit clipping, and an f32 observation boundary.
- `LEARNER_SPEC_V1` records the future executor and hyperparameters as data.
- `EXPERIMENT_SPEC_V1` binds environment, features, observation, partition,
  transform, learner, evaluator, seed, immutable inputs, and implementations.
- `EVALUATION_SPEC_V1` freezes episodes, deterministic inference, metrics,
  stresses, missingness, and aggregation. Evaluation data cannot select policy.
- `POLICY_ARTIFACT_V1` defines weights, transforms, observation/action contracts,
  environment, executor version, inference signature, and future ONNX lineage.
  Its qualification instance is `CONTRACT_ONLY_PRE_LEARNER` with no weights.
- `CAMPAIGN_SPEC_V1` binds multiple planned seed runs to one experiment.
  Qualification run receipts contain zero learner steps.

## Batched environment ABI

Rust owns a dense `EnvironmentBatch` and exposes `reset_many` and `step_many`
through one PyO3 call. The Python `NorthstarBatch` shell only validates shapes
and translates contiguous NumPy arrays. Lanes are currently single-owner and
sequential inside Rust; this gate makes no parallel-speedup claim.

## Qualification

```powershell
northstar-rl campaign-qualify artifacts/campaign
python -m northstar_rl.campaign_qualify artifacts/campaign/environment_config.json
northstar-rl campaign-qualify artifacts/campaign
```

The final reseal includes the Python batch receipt. The included partition and
transform population is a deterministic synthetic control-plane fixture, not a
scientific or financial promotion population.
