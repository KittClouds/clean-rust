# Stage 1 hookable search runner

This crate implements the Stage 1 arm scheduler in a separate package. Its
Stage 0 dependencies are read-only path dependencies; it does not modify
stage0-v01.

## Callback contract

The entry point is:

    run(task, features, config, policy) -> Result<Stage1Run, SearchError>

where task is an InferenceTask, features is SemanticFeatures, config is
Stage1RunConfig, and policy implements SearchPolicy.

SearchPolicy has three hooks:

- score_edits(TransitionInput, candidates) returns one logit per legal edit,
  the next latent state, and operation costs. The runner applies greedy,
  learned-sampling, or uniform-sampling behavior according to the arm.
- q_terminal(SelectorInput) sees only immutable semantic features and the
  candidate assignment. It receives no latent state, task text, or budget.
  Return calibrated P(valid); apply sigmoid/calibration to raw checkpoint
  logits in the model adapter.
- v_reach(ValueInput) sees semantic features, the public inference
  projection, assignment, latent state, remaining budget, and depth. Its
  result is used for particle allocation only.

SemanticFeatures stores row-major float32 embeddings for H and h_global, plus
binary public clause/entity/role incidence and masks. from_projection derives
incidence from InferenceTask.entity_mentions and role_mentions. The extraction
adapter supplies the frozen embedding rows. validate_for checks dimensions
before any callback can run.

The runner receives only InferenceTask; it has no private solver, solution
set, or validator input. After run returns, call Stage 0 annotate_posthoc and
prefix_metrics with the private Task to join validity labels and compute
expansion, active-time, and wall-time prefixes. Stage 0 write_jsonl/read_jsonl
handle the lossless trace and full operation ledger. verify_replay here reruns
a fresh deterministic policy instance and compares semantic traces while
excluding measured timing fields.

The trace manifest records arm, merge mode, and caller-provided proposal,
selector, and value artifact IDs. Merge modes are none, raw assignment,
canonical assignment, and strict dynamic state. Strict identity includes the
assignment, latent bit patterns, remaining budget, and RNG state.

## Frozen Q-terminal delta proposal

`FrozenQTerminalDeltaV05` memory-maps a pinned float32 little-endian export of
the clausewise V05 Q-terminal network. It validates the export manifest, source
checkpoint identity, binary digest, dimensions, finite weights, and task-feature
binding. Task preparation caches global and clause projections. An edit scores
only clauses incident to its entity and returns the predicted change in
satisfied-clause count, `Delta C`.

`QDeltaProposalPolicy<P>` replaces only `score_edits` with `beta * Delta C`.
It delegates latent updates, terminal selection, and reachability value scoring
to the wrapped policy. The pilot's `--qdelta-manifest`, `--qdelta-weights`, and
`--qdelta-beta` options enable it; all three are required together. The common
V07 terminal selector and selected V_reach checkpoint remain separately pinned
in the run manifest.

`r1_v05_qdelta_parity` replays the train/validation-only parity bundle against
the Python CPU reference, including edit order, score deltas, proposal
probabilities, stable top-action decisions, and scored-clause accounting. It
does not load qualification or test records. The Python exporter is kept
separate from the runtime crate; Rust inference itself needs no Python runtime.

## Current boundary

The pilot now supports an end-to-end Q-delta proposal search on the declared
train/validation roster. The scorer affects proposals only. The terminal judge,
V_reach head, latent update, and scheduler are the existing independently pinned
components. This is an adaptive engineering run, not a confirmation result;
qualification and test rosters remain closed.

## Test command

PowerShell from the repository root:

    $env:CARGO_TARGET_DIR='D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\cargo-target'
    cargo test --manifest-path experiments/fas-r1-semantic-particle-reachability-v00/stage1-v01/search/Cargo.toml
