# FAS-R1 v04 proposal fit

This entrypoint fits only the class-balanced action proposal on the frozen v04
world/sensor bundle. It uses the exact private solver teacher for train and
validation tasks, then selects epochs on validation. Qualification tasks may
be present in the public feature store for later evaluation, but they produce
no teacher rows and their embeddings are removed from the downstream feature
store before identity inference or proposal fitting. The common sensor loader
does integrity-check all rows first, including qualification row hashes.

The prior pilot opened qualification. Any output from this entrypoint is
therefore marked `ADAPTIVE_ENGINEERING` and is not eligible for scientific
confirmation.

The contract is pinned to 96 unique tasks/families: 64 train, 16 validation,
16 qualification; every task is N=20, K=3, with 36 clauses. The generation
receipt binds the v04 renderer source and its rendering seed rule
`render_task(task, task.seed ^ 0x0053_5552_4641_4345)`. The v04 sensor receipt
binds those public task bytes and the support manifest. This trainer does not
use `sensor/label-exporter`; its legacy renderer reconstruction uses a
different seed rule and is not a v04 parity tool.

Every train/validation teacher world is required to contain exactly 54 raw
solutions and 9 canonical solution classes. Each sampled start has 40 legal
single-entity edits. For each edit, the Rust teacher computes each class's
distance as the minimum Hamming distance to every raw assignment in that
class, then forms `q(e) = n_improved_classes / total_improved_class_mass`.
Zero-mass starts remain explicit all-zero targets. `delta_d_min` is retained
as telemetry and is not used in proposal features or loss. The exact teacher
and shared fitting/feature routines are source-hash pinned in the fit receipt.

The v01/v02 trainers are retained unchanged. They pin older support splits and
sensor receipts. This version reuses only their feature math, fixed identity
posterior inference, class-balanced teacher example conversion, and proposal
model/fitting routines. Qualification teacher rows are rejected before model
fit. The Rust teacher filters qualification before exact solution enumeration
and target construction.

## Inputs

- Worlds and support: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v75-stress-worlds-v04-v02\`
- Frozen LFM extraction: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v78-v04-sensor-v01\`
- Frozen identity head: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-probes-v03\identity.pt`
- Identity receipt: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-probes-v03\run-receipt.json`
- Frozen v01 proposal initializer: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\proposal-value-v01\proposal-weights.json`

The identity head and initializer are hash-pinned. All v04 task, support,
generation, and sensor receipts are checked before fitting. Run output must be
a new directory; the trainer writes a proposal checkpoint and a complete
`proposal-fit-receipt-v04-v01.json`. This entrypoint does not generate V_reach
labels or fit V_reach.

The fit artifact also contains `private-tasks-trainval-v04.jsonl`: exactly the
support-listed 64 train and 16 validation private task rows, with all 16
qualification rows omitted. Its `private_trainval` receipt record binds the
sidecar SHA-256 and byte count to the pinned full private source SHA-256. The
V04 request/start builder should consume this filtered sidecar, not the full
world bundle's private JSONL.

## Invocation

From the repository root:

```powershell
$target = 'G:\cargo-targets\fas-r1-v04-proposal-v01'
python .\experiments\fas-r1-semantic-particle-reachability-v00\stage1-v01\proposal\v04\train_proposal.py `
  --world-dir 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v75-stress-worlds-v04-v02' `
  --sensor-dir 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v78-v04-sensor-v01' `
  --identity-model 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-probes-v03\identity.pt' `
  --identity-receipt 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-probes-v03\run-receipt.json' `
  --initial-proposal 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\proposal-value-v01\proposal-weights.json' `
  --output 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v84-v04-proposal-v01' `
  --cargo-target-dir $target
```

The generated private JSONL is passed to the Stage1 teacher CLI so it can
derive exact labels. The CLI deserializes the roster, but it skips each
qualification task before solving it or building any target. The trainer
checks for zero qualification rows and exact per-task start coverage before
fitting. The resulting proposal weights use the v02 JSON schema and
`tanh_mlp_base_f10_h16_plus_adapter_bias_v02` architecture; v01's Rust
collector does not accept that schema.

Run only the focused contract tests while developing this entrypoint:

```powershell
python .\experiments\fas-r1-semantic-particle-reachability-v00\stage1-v01\proposal\v04\test_train_proposal.py
```
