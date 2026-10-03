# Jev-like Zero-Training Reconnaissance v0.1

Status: frozen exploratory protocol; no model weights are modified.

## Purpose

This slice measures how much of the decision primitive is already exposed by
frozen causal language models. It is not a benchmark claim and it does not
replace the architecture-neutral episode contract. The canonical target stays
the world- or annotator-derived object; model outputs remain readout scores
until a declared normalization is applied for a declared query view.

The experiment is deliberately split into four questions:

1. Is useful semantic signal present in the frozen representation?
2. Can a native language-model next-token surface recover that signal?
3. Do runtime names and definitions bind, or do lexical priors dominate?
4. Does the score respond to controlled changes in evidence and surface form?

## Frozen inputs

The run consumes the validated bridge JSONL outside the repository:

`D:\codex-runs\jev-corpus-bridge-v01\pilot-episodes.jsonl`

The current reconnaissance bank contains 1,063 episodes and approximately
6.4k query objects after the 350-per-template synthetic expansion. Synthetic
episodes retain exact generative posteriors. External rows retain their native
hard-label, empirical-distribution, or no-probability semantics.

Mandatory frozen snapshots:

| model | revision |
|---|---|
| `openbmb/MiniCPM5-1B-Base` | `156170697656c48f69915b33a2fb44110242187c` |
| `Qwen/Qwen3-0.6B-Base` | `da87bfb608c14b7cf20ba1ce41287e8de496c0cd` |

Weights live only under the external run directory. Phoenix paths and
production datasets are out of scope.

## Frozen prompt surface

The evaluator uses a finite, predeclared set of templates. No per-example
prompt search is allowed.

* `A`: state, question, enumerated options, answer.
* `B`: evidence, criterion, candidate, compatibility.
* `C`: state, proposition, `True` or `False` answer.

Candidate presentation profiles are also fixed:

* `name`
* `name_definition`
* `opaque_definition`
* `opaque_only`

Opaque IDs are deterministic local presentation symbols. Replacing a name by
an opaque ID without an equivalent definition is intentionally information
poor and is not expected to be invariant.

## Frozen readouts

The evaluator records, separately:

* direct next-token logits for the first continuation token;
* full candidate sequence log-likelihood sum;
* length-normalized candidate sequence score;
* proposition `True`/`False` restricted readout;
* candidate token IDs, token counts, and surface lengths.

Choice distributions are normalized only within the supplied candidate set
when the query declares a closed conditional choice. Independent applicability
is scored per candidate and is never forced into one softmax. Open choices
retain an `other` bucket when the canonical target provides one. Raw scores
are never called probabilities.

## Calibration protocol

NLL, Brier, ECE, and accuracy are reported separately by probability source:

* exact generative posterior;
* empirical annotator distribution;
* elicited/adjudicated distribution;
* hard label;
* no-probability rows, which are excluded from probability calibration.

One scalar temperature may be fit on a designated exact-synthetic development
partition and then applied once to the held-out synthetic calibration slice.
No weights change. Human disagreement is not pooled with world posterior
calibration.

## Perturbation protocol

Candidate order is permuted at readout time with target alignment preserved.
Existing renderer siblings are grouped by semantic fingerprint. Evidence
removal/revelation and world interventions are reported as unavailable unless
the input bank contains verified sibling links with recomputed gold targets;
the evaluator must not invent a directional gold label.

Strict invariants and expected tendencies are reported separately. A drift on
an unavailable perturbation is not silently treated as a model failure.

## Systems measurements

For each model, the run records model load time, forward time, input length,
batch size, peak CUDA allocation, and candidate cardinality. A cache-branch
benchmark is attempted through the model's `past_key_values` interface. If the
installed Transformers API cannot provide numerically equivalent branched
execution, the report records the reason and does not fabricate a shared-state
speedup.

## Failure taxonomy

* `F1` lexical/tokenization artifact
* `F2` schema-binding failure
* `F3` semantic reasoning failure
* `F4` normalization/readout failure
* `F5` calibration-only failure
* `F6` representation invariance failure
* `F7` evidence sensitivity failure
* `F8` shared-state numerical/system failure

Representative rows are retained by episode ID in the JSON reports. The
experiment ends with a recommendation about what training would improve; it
does not start QLoRA, LoRA, SFT, PPO, or any other weight update.

