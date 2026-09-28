# LFM Architecture-Variable Experiment v0.7

Status: prospective frozen-backbone architecture control.

This slice tests whether the decision-compiler phenomenon survives a materially different pretrained architecture. It does not authorize QLoRA, LoRA, SFT, RL, Phoenix access, or changes to v0.4-v0.6 artifacts. The LFM result is a fourth architectural observation, not a leaderboard entry.

## Research question

Can the fixed dynamic compatibility head recover useful runtime-schema decision behavior from `LiquidAI/LFM2.5-1.2B-Base` while the backbone remains frozen?

The controlled comparison is:

```text
same canonical S100 banks
same candidate surface and loss
same head function
same protected evaluation families
different frozen backbone architecture
```

The model snapshot is pinned to Hub revision `7453bca97ca1e67754c4035a4b4c584e1c9dd725`, as reported by the official model repository: [LiquidAI/LFM2.5-1.2B-Base](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Base).

The pinned config identifies `Lfm2ForCausalLM` with hidden size 2048 and 16 layers. The experiment truncates each input at 1,024 tokens; this is an experiment boundary, not a claim about the model's maximum context.

## Frozen protocol

Primary model: `LiquidAI/LFM2.5-1.2B-Base`, Base checkpoint, not an instruct derivative.

Inherited variables:

- S100 synthetic-only training;
- 50k and 100k points, using the existing family-safe v0.5 banks;
- 250k only after the declared 50k-to-100k promotion rule;
- final-layer `mean_full` representations;
- `name_definition` candidate surfaces;
- the validated v0.6 dynamic MLP compatibility head, projection dimension 128;
- the v0.4 L3 source-typed semantic + Brier + certified-invariance objective;
- AdamW, learning rate, schedule, epochs, batch size, clipping, seed, and augmentation inherited from v0.6;
- no LFM-specific tuning or internal-layer search.

The head accepts one state representation and a variable number of candidate representations. It is not a fixed classifier inventory. Candidate scores are normalized according to the canonical query semantics by the inherited adapter.

## Snapshot and integrity

The complete model snapshot is materialized outside the repository under `D:\codex-runs\jev-lfm-variable-v07\models\lfm2.5-1.2b-base`. Reports record the immutable Hub revision, tokenizer/config hashes, Transformers version, dtype, hidden dimension, and extraction path. Model weights are never written by the experiment.

The LFM integration receipt must prove:

- revision and local snapshot are fixed;
- tokenizer and model load locally;
- model parameters have `requires_grad=False`;
- extraction is deterministic, state-sensitive, candidate-sensitive, and its batch-shape/padding behavior is characterized with a declared mitigation;
- the v0.4 gate and v0.5/v0.6 reports are unchanged;
- no real-data mixtures, prompt search, native LM-head contest, or LFM-specific optimization occurred.

## Bank and execution order

The canonical bank is the existing v0.5 S100 synthetic bank. The 50k point is the existing nested family-safe `s50k` training subset; the 100k point is the existing `s100k` training bank. Dev, test, and external evaluation files remain protected and are not regenerated.

The LFM hybrid convolution path is sensitive to padded sequence shapes under the installed reference implementation. The adapter therefore uses exact-length, single-row, no-padding extraction and records the observed batch-shape/padding drift in the feature-validation report. This is a declared systems constraint, not a semantic result; no padded or variable-length batch feature enters the cache.

Execution:

1. pin and hash the model snapshot;
2. validate the LFM representation adapter on a small deterministic bank;
3. build the immutable feature cache for the S100 bank;
4. fit the fixed head at 50k and 100k;
5. run binding and open-world diagnostic extensions using the 100k head;
6. promote to 250k only if 50k-to-100k semantic learning is materially positive under the declared rule;
7. compute failure overlap, complementarity, and cost receipts.

## 250k promotion

Run 250k only when either exact accuracy improves by at least `.03` absolute from 50k to 100k, or at least two major semantic/OOD rank metrics show material improvement under the existing v0.6 materiality definitions. This is a characterization rule, not a new QLoRA gate. If not promoted, the 250k report is explicitly recorded as `not_run` with the reason.

## Interpretation

The result is classified as one of: same phenomenon/similar curve; same phenomenon/different learning curve; strong early/fast plateau; strong but behaviorally different; or fixed compiler fails after extraction parity. No single composite score is used. Ranking, calibration, OOD transfer, interventions, binding, open-world behavior, and compute cost remain separate.

The strongest supported claim, if positive, is limited to the tested four small pretrained backbones: lightweight dynamic compatibility readouts recover useful runtime-schema decision behavior without modifying backbone weights.

## Artifacts

Repository contract and runner files live in `experiments/jev-lfm-variable-v07`. External immutable snapshots, caches, model outputs, and reports live under `D:\codex-runs\jev-lfm-variable-v07`. Generated corpora and run outputs are not committed to the repository.
