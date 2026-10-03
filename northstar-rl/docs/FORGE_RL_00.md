# FORGE-RL-00 contract note

`NORTHSTAR_RL_SURFACE_V1` is an inert learning world. It is not a strategy,
backtest claim, model, allocation policy, or trading authority. Its canonical
fixture is synthetic and exists only to qualify arithmetic and protocol
semantics.

## Authority chain

```text
source manifest
  -> RUNRAW_TAPE_V1 (fixed width, chronological, mmap)
  -> FEATURE_REGISTRY_V1 + compiler identity
  -> FEATURE_TAPE_V1 (columnar values/state/knowledge time, mmap)
  -> EPISODE_TAPE_V1 (explicit session objects)
  -> RL_ENV_SPEC_V1 (complete immutable world identity)
  -> ENV_STEP_TAPE_V1 + execution/terminal receipts
  -> trajectory root
```

RunRaw preserves source-native rows. Derived values never overwrite it. A
feature cell is observable only when its state is `AVAILABLE` and its
`knowledge_time` is no later than the environment's completed-bar clock.

## Frozen step clock

At row `t`, the environment exposes the declared observation ending at the
completed bar. Action `A_t` is a target normalized exposure in `[-1, 1]`. The
kernel converts it to instrument quantity using prior equity and the next
eligible bar's open, applies deterministic rounding and separately receipted
friction, then marks the resulting position at that bar's close. Reward is:

```text
(equity_after - equity_before) / initial_equity
```

The final session boundary is a Gymnasium truncation in the canonical contract.
An account-floor event is a termination. A source gap fails closed before fill
and is a termination. Both booleans and the typed reason are recorded.

## Layout and numerical contract

Authoritative market/account math is IEEE-754 `f64`. Gym actions and
observations are finite `float32`. Non-finite authority, actions, or conversion
results are rejected. Flat vectors and row-major window matrices use the same
ordered feature IDs and machine-readable observation dictionary.

The packed path uses dense fixed-width records, SIMD candle transforms,
`hashbrown` lookup tables, `memchr` header validation, explicit `zerocopy` and
`bytemuck` layout guarantees, and read-only `memmap2` mappings. No hot step
performs source parsing, feature compilation, logging, or filesystem I/O.

## First learner seam

The next project should consume `environment_config.json` through
`NorthstarEnv.from_spec`, pin a declared learner specification and library
versions, and run a tiny deterministic training smoke on the synthetic fixture
before any financial corpus is admitted. That project must create learner,
evaluation, and promotion receipts outside this surface. FORGE-RL-00 does not
call `.learn()`.

