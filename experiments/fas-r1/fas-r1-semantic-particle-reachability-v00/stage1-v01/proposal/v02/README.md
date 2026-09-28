# R1 proposal/value engineering v02

This version starts from the immutable v01 proposal and V_reach checkpoints. It adds the frozen semantic action-adapter v02 expected satisfaction-delta as a trainable scalar logit bias, then samples nonzero-latent V_reach states along the resulting frozen proposal trajectories. Qualification families and metrics are excluded from target generation, fitting, and model selection.

Run from this directory with the pinned artifacts:

```powershell
$env:CARGO_TARGET_DIR = 'D:\cargo-targets\fas-r1-stage1-v02'
python .\train_pipeline.py `
  --stage0-root 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage0-v01\construction-attempt-v02' `
  --sensor-dir 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-extraction-v01' `
  --support-manifest '..\..\manifests\sensor-support-manifest-v02.json' `
  --semantic-adapter-manifest '..\..\manifests\semantic-action-adapter-manifest-v02.json' `
  --semantic-adapter-source '..\..\sensor\action_semantic_adapter.py' `
  --semantic-adapter-report 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\semantic-adapter-v02\report.json' `
  --semantic-adapter-receipt 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\semantic-adapter-v02\receipt.json' `
  --identity-model 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-probes-v03\identity.pt' `
  --identity-probe-receipt 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-probes-v03\run-receipt.json' `
  --q-terminal-checkpoint 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-fit-v02\qterminal-v02.pt' `
  --q-terminal-receipt 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-fit-v02\fit-receipt.json' `
  --v01-dir 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\proposal-value-v01' `
  --output 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\proposal-value-v02-attempt-03' `
  --device auto
```

The run refuses to overwrite an attempt directory. Attempts 01 and 02 are retained with their pin-check and postcondition failures; the runnable third attempt therefore uses a new output name. The cargo target is pinned to the D: drive corresponding to `:G`.

`proposal-weights-v02.json` is written and digested before the Rust collector creates any V_reach labels. The Rust collector exports full seeded traces and labels from initial states plus states at trajectory steps 1, 4, and 8, with budgets 1, 2, 4, 8, and 16 on initial states and 1, 2, 4, and 8 on trajectory states. Every continuation rollout runs to its assigned budget; exact validation is post-hoc.

The receipt compares v01 and v02 proposal ranking on the same teacher rows. It compares the frozen v01 V_reach transfer checkpoint and its v02 fine-tuned successor on identical v02 validation labels, and includes a matched initial-state/budget-16 slice. V_reach targets aggregate the fixed seeded rollouts into state-level rates for training and fractional-label ranking/calibration metrics.
