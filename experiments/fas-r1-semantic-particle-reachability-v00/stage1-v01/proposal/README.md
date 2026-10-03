# R1 Stage 1 Proposal and Reachability Targets

This package defines offline target construction and the first engineering
fit pipeline. The trainer does not load a model or tokenizer; it reads the
completed frozen sensor artifact and qualified public feature vectors.

## Proposal target

`ExactSolutionClasses::solve` exhausts the Stage 0 exact solver and groups all
solutions by the task's declared public role automorphisms. For each
individual assignment, `build_teacher_target` implements the
**class-balanced one-step reachability teacher**:

```text
G(e|a) = mean over canonical valid classes c of [d_c(a_e) < d_c(a)]
q(e|a) ∝ G(e|a)
```

`d_c` is minimum Hamming distance to any represented assignment in class c.
Each training-only edit row exports `n_improved_classes`, the signed
`delta_d_min = d_min(after) - d_min(before)`, `G`, and normalized `q`. A
zero-mass state is explicit and leaves all q probabilities at zero; consumers
must mask it rather than normalize it.

## Continuation-value labels

`build_reachability_dataset` creates seeded, independent rollouts from
individual `(assignment, latent_state, remaining_budget)` states under one
fixed proposal snapshot. The proposal sees only `InferenceTask`, supplied
sensor features `(h_global, h_j)`, the current assignment, and latent state.
The private task is used only to label whether a complete assignment is valid.
After a hit, the rollout continues for the full transition budget; no validator
signal or early-stop signal reaches the proposal. No particles or resampling
are used. `success_within_budget` includes the initial state, and
`first_hit_step=0` records that case.

The label builder refuses a proposal whose snapshot digest changes during the
dataset build. Derived seeds and stored terminal RNG state make individual
rollouts replayable. The dataset supplies Bernoulli observations for fitting
`V_reach(a,s,H,b)` after the proposal has been frozen.

## Current boundary

The trainer performs no LFM/tokenizer contact or encoder extraction; it reads
the completed frozen sensor artifact. No search-arm comparison occurs here.
`PublicFeatures` is an input contract for that artifact. Teacher labels and
reachability labels are training-only and must remain out of runtime proposal
inputs. The initial V_reach pass starts from zero latent states; later work can
add continuation states sampled from live proposal trajectories.

## Runnable first pass

From the repository root, supply the Stage0 construction directory, completed
frozen sensor extraction, frozen support manifest, exact Q_terminal v02
checkpoint/receipt, compositional action-adapter diagnostic, and a new output
path. Q_terminal is hash-pinned as the common post-trace selector companion;
its scores do not enter proposal or V_reach training. The adapter report is
also hash-pinned for lineage, but this v01 proposal does not consume its
identity probabilities or compositional action features.

```powershell
$env:CARGO_TARGET_DIR = 'D:\cargo-targets\fas-r1-stage1-v01'
python experiments\fas-r1-semantic-particle-reachability-v00\stage1-v01\proposal\train_pipeline.py `
  --stage0-root 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage0-v01\construction-attempt-v02' `
  --sensor-dir 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-extraction-v01' `
  --support-manifest 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\manifests\sensor-support-manifest-v02.json' `
  --q-terminal-checkpoint 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-fit-v02\qterminal-v02.pt' `
  --q-terminal-receipt 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\qterminal-fit-v02\fit-receipt.json' `
  --semantic-adapter-report 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\semantic-adapter-v01\report.json' `
  --semantic-adapter-receipt 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\semantic-adapter-v01\receipt.json' `
  --output 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\proposal-value-v01'
```

Defaults use 32 seeded assignment states per family, all 48 train families and
16 validation families, continuation budgets 16/32/64, and two independent
rollouts per state. The 32 qualification families are not opened. Python
requires NumPy and PyTorch; the Rust target builder uses this package's Cargo
manifest. The output directory must not already exist.
