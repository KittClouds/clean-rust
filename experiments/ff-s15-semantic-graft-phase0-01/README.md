# Semantic + candidate epistemic graft: Phase 0

This package implements a trainable interface over four existing frozen substrate
caches. Phase 0 ends at executable training readiness. It does not train BANK,
reopen VCS/head masking, or change System 1.5.

The interface is `G(H,A) -> s[B,64], e[B,M,64]`. Semantic state describes the
world/task; each epistemic slot belongs to its own candidate. A global confidence
scalar cannot substitute for these slots. Scalar typed readouts supervise what the
slots must make recoverable; no latent dimension is assigned a named meaning.

## Architecture

- Frozen lanes: causal Base, NER-LoRA step500, NLI-LoRA step500, encoder Base.
- One earned interface: final+mean concatenation, 2,048 dimensions. Causal lanes
  use the existing `final_token + full_mean` cache. Encoder uses `final + mean`
  (last-layer masked mean). Their differing pooling definitions remain explicit
  in separate representation identities; this is not a pooling parity claim.
- Phase 0 supplies one row-level context token, `H[B,1,2048]`. Projection width
  128; four-head cross-attention; semantic and epistemic slots width 64 each.
- Global query reads H independently of A. Candidate queries combine action
  type and argument-role embeddings, read H, and fuse with s into separate e_j.
- With one H token, attention cannot select local spans. Candidate conditioning
  comes from the explicit action query in the epistemic fusion. No graph-local
  extraction, fresh surface search, or attention-head investigation is implied.
- 460,597 trainable graft parameters; backbone input is detached. Vector slots
  and their scalar readouts are part of one trained artifact.

Candidates come from observable binding IDs through the existing BANK-v1 action
schema: obj_0 MOVEs over ordered location pairs; ACTIVATE/DEACTIVATE for switches;
WAIT and NOOP. They are not selected by oracle legality or the selected action.
Binding ordinals are local schema references, not document/world identifiers.
Unbound arguments and capacity overflow raise errors rather than truncating.

The mathematical interface supports multiple H positions. This version's adapter
and frozen experiment use only one; changing that requires a later version.

## Supervision ABI

`supervision-abi.json` binds all 13 ontology names. Availability masks exclude
unavailable targets from loss, metrics, and runtime estimates. Zero-filled storage
is padding, not a negative judgment.

| Global target | Phase 0 source/status |
|---|---|
| solvable | unavailable; depth-four planner cannot certify unrestricted failure |
| goal_satisfied | canonical current-state goal evaluator |
| missing_information_present | canonical generator annotation present |
| contradiction_present | canonical generator contradiction annotation present |
| requestable_information_present | unavailable; ASK sampling is not requestability |
| number_or_structure_of_missing_requirements | **restricted annotation-count proxy**, len(missing_information), BANK-v1 0/1; not complete precondition structure |

| Candidate target | Phase 0 source/status |
|---|---|
| candidate_legal | canonical simulator legality |
| candidate_satisfies_goal | legal AND goal holds after one step |
| candidate_supported | unavailable |
| candidate_has_counterevidence | unavailable |
| candidate_has_unmet_requirements | unavailable |
| candidate_applicable | unavailable; not aliased to legality |
| candidate_requires_missing_information | unavailable |

Canonical world truth is distinct from evidence justified by visible text. A
contradictory or incomplete observation may not reveal simulator legality. The two
available candidate targets therefore constrain e_j only partially: this is an
executable candidate-conditioned state interface, not a completed epistemic
support estimator. Missing targets do not become synthetic truth.

## Data and feature firewall

Generated arrays, verification, locks, and future checkpoints live on the C: NVMe:
`C:\phoenix-target-overgraph\semantic-graft-phase0-20261001`.
Existing D: encoder caches are read-only inputs. No new D: work is generated.

The frozen development population is the first 20,000 TRAIN and first 2,000 DEV
rows in BANK-v1 file order, matching the existing encoder cache budget. These are
16,668 and 1,668 canonical worlds, respectively; paired renderings stay grouped.
They are not 22,000 independent worlds and are not a fresh qualification panel.
TRAIN/DEV canonical group overlap is checked and rejected. No TEST truth opens.

Model inputs are frozen H and the observable candidate schema A. The graft receives
no labels, evidence_facts, missing_information, selected_action, difficulty,
oracle action lists, renderer labels, world hashes, or world IDs. World/renderer
identities exist only for joins, receipts, and grouped evaluation. Source caches
are hash-verified. The encoder .pt contains old labels alongside tensors; only
row_ids and registered surface tensors are consumed.

Canonical worlds are used only in target construction. Their hashes and candidate
enumeration/legality are verified against the unmodified BANK simulator. Targets,
offsets, and candidates are compact NumPy arrays; H is memory mapped read-only;
only a minibatch's ragged candidates are padded.

## Training contract

One fixed graft per substrate; no model/width/surface sweep. Seed 20261001;
TRAIN-only mean/std stored in checkpoint; AdamW, learning rate .001, weight decay
.0001, clip 1, batch 64, five epochs. Last epoch is the checkpoint, with no
DEV-dependent selection. Available binary heads use BCEWithLogits; the count
proxy uses SmoothL1. Per-target means are averaged within branch, then semantic
and candidate losses are added. Candidate padding and unavailable dimensions
have no loss.

The training preflight performs forward/loss checks only. Phase 0's smoke test
performs five optimizer steps on random synthetic fixtures, and verifies frozen
H, deterministic inference, and checkpoint replay. It does not fit BANK labels.

## Evaluation contract

DEV is out of TRAIN, with unchanged fixed thresholds. Binary metrics: accuracy,
balanced accuracy, F1, AUROC (undefined for single-class populations), Brier,
calibration and class support. Counts: MAE, nearest nonnegative integer exactness,
Spearman (undefined for constant values), calibration by true count.

TRAIN-only global-frequency/action-type priors are the cheap control. Reports
include target availability, renderer partitions, held S7/S8/S9 presence, and
paired-renderer output movement. No held-renderer success is claimed if those
renderers are absent. Primary intervals use canonical-world grouped bootstrap,
1,000 seeded draws; paired renderings never resample independently. Candidate
accuracy is averaged within row and world before bootstrap, so candidate-rich
worlds do not dominate the primary interval. Pooled metrics remain descriptive.

Future trained exports contain `estimate.semantic.*` and
`estimate.candidate.*` with MODEL_ESTIMATE / AVAILABLE, attached graft hash and
representation identity. Count runtime values are nearest nonnegative integers;
raw values remain diagnostic. Unavailable targets are listed, not predicted.
Training truth is never renamed as a runtime estimate. s/e remain vector-valued
internal slots available through the model forward API.

## Execution

From this package directory, using the existing Python environment:

```powershell
python -m graft.checks
python -m graft.freeze
python -m graft.train --substrate causal_base
```

The last command verifies the frozen package and populations, then performs a
forward-only training preflight. To begin the next training phase explicitly:

```powershell
python -m graft.train --substrate causal_base --train
python -m graft.train --substrate ner_lora_step500 --train
python -m graft.train --substrate nli_lora_step500 --train
python -m graft.train --substrate encoder_base --train
```

CPU is the default for the small graft; `--device cuda` uses CUDA without loading
or adapting a backbone. Outputs are no-clobber per substrate. Source/data hash
changes invalidate the lock. Recreating data in a new output root uses
`python -m graft.prepare --split TRAIN --out <C-drive-path>` and the DEV equivalent;
the frozen run retains its original population and manifests.

The acceptance criterion for this phase is executable architecture, audited
supervision, constructed data, meaningful tests, and a verified training lock.
Learned capability quality is a result of the next phase, not a claim of this one.
