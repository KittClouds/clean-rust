# Phase 0 v02: shared supervision mathematics, separate fabrics

This version implements the shared S/E/A/CF/R objective. The previous Phase 0
source package, data and lock remain unchanged. All new outputs live on the
C: NVMe at `C:\phoenix-target-overgraph\semantic-graft-phase0-v02-20261001`.
Phase 0 ends ready to train, with no BANK fitting or accuracy gate.

## Same observable contract; separate hidden coordinates

Both fabrics implement frozen `F(x)->H`, followed by trainable
`G(H,A)->s[B,64],e[B,M,64]`. Scalar typed decoders supervise properties recoverable
from the slots. No latent dimension is declared to mean confidence or uncertainty.
The global semantic slot is independent of the candidate set. Each e_j receives
its own candidate query. Candidate permutation permutes candidate outputs.

Lexi's causal path is late integration over the existing final-token + full-mean
row vector. Causal Base, NER-LoRA step500 and NLI-LoRA step500 stay frozen.
This implementation does not inject a learned prefix into F or rerun extraction.
With one row token it cannot select local spans; explicit candidate-query fusion
provides conditioning.

Lepori's bidirectional path uses the existing encoder final+last-layer-mean row
vector plus the **already extracted** final-layer entity-local vectors. It attends
over row and valid entity tokens, and gathers local entity vectors separately for
each candidate argument role. Local IDs are remapped from cached binding order
into sorted observable binding ordinals. Exact-zero unresolved spans carry an
unavailable mask; they never mean semantic absence. First-mention pooling and the
512-token extraction boundary remain limitations of this existing interface.

The two model instances own their weights, normalization and coordinate systems.
There is no causal/encoder s/e alignment loss, distillation, or coordinate matching.
Identical scalar output meanings do not imply equal hidden vectors.

## Supervision provenance

The existing 13-target ontology and availability discipline remain intact:

- Global goal satisfaction, missing annotation presence, contradiction annotation
  presence, and restricted missing-annotation count have canonical supervision.
- Unrestricted solvability and requestability remain unavailable.
- Candidate legality and legal one-step goal achievement have simulator labels.
- Candidate support, counterevidence, unmet requirements, applicability and
  dependency on missing information remain unavailable.

The count target is specifically `len(missing_information)`, currently 0/1,
including unknown-entity annotations. It is not full unmet-precondition structure.
Simulator legality is not observation-supported epistemic justification.
This phase builds partially supervised candidate states without fabricating the
missing epistemic labels.

The action endpoint adds a separate canonical policy label: `selected_action`
only when decision is ACT and the exact action is in A. ASK/REQUEST and ABSTAIN
remain unavailable for this endpoint. They are not converted to WAIT/NOOP.
A genuine canonical NOOP remains eligible.

## One shared five-term objective

`objective.py` implements:

```text
L = 1.0 L_S + 0.1 L_E + 0.25 L_A + 1.0 L_CF + 0.1 L_R
```

S sums available scalar semantic coordinate losses per row, then averages eligible
rows. E sums available candidate-coordinate losses per row, then averages eligible
rows. Binary coordinates use BCEWithLogits and the count proxy uses SmoothL1.
Unavailable targets and padded candidates contribute no loss.

A is mean candidate-index CE on eligible canonical ACT endpoints. It is a task
endpoint, not the definition of e_j. Its readout is distinct from typed state heads.

CF implements `relu(margin - y*(r_positive-r_negative))`, margin 1, direction
+1/-1, and explicit availability. Its score contract is the candidate-supported
logit. **BANK provides no canonical candidate-support-changing matched pairs.**
The replayable CF bank is therefore empty and its active contribution is zero.
Legality, goal success, or selected-action differences are not substituted for
support changes. Unit fixtures verify the hinge mechanics; they are not training
supervision or new BANK truths.

R implements the squared semantic norm difference plus the candidate squared norm
difference averaged over identity-aligned candidates, then averages renderer pairs.
It operates strictly within one fabric. Eight TRAIN renderer pairs are sampled per
training minibatch with a fixed seeded RNG; pair evidence never comes from DEV.

## Replayable pairs and populations

The unchanged parent universe is 20,000 TRAIN rows / 16,668 canonical worlds and
2,000 DEV rows / 1,668 worlds. H, target arrays and schema candidates are read-only
parent mmap artifacts, bound by the original lock. New sidecars add endpoint
targets, renderer pairs, empty CF pairs and encoder-local arrays.

Every source observation is re-rendered from its canonical world and must exactly
match stored text and bindings. Meaning-preserving pairs require the same canonical
world/hash, goal, candidate identities and binding ordinals. Construction enumerates
all eligible different-renderer pairs in fixed canonical-world/row order.

S5 is excluded from R because its aliases/pronouns can collapse entity identity.
S9 is excluded because it drops STATE values and REQUIRES conditions. These rows
may still receive ordinary supervised losses; they are not invariance pairs.
The other existing renderer families remain eligible. No new renderer is introduced.

TRAIN/DEV canonical worlds must be disjoint. Pair families and evaluation intervals
group by canonical world. Metadata and targets never enter the forward call.
Encoder caches contain co-located old labels; only registered row/entity tensors
and identity alignment fields are consumed. No protected TEST truth opens.

## Fixed Phase 1 configuration and evaluation

One graft per substrate; seed 20261001; five epochs; batch 64; AdamW lr .001,
weight decay .0001, gradient clip 1; final epoch checkpoint. TRAIN-only row and,
for encoder, resolved-entity normalization are embedded in the checkpoint.
No width, surface, model or threshold search occurs in this version.

DEV reports masked binary accuracy, balanced accuracy, F1, AUROC, Brier and
calibration; count MAE/exact count/Spearman/calibration; action endpoint accuracy;
and state invariance on the fixed DEV renderer pairs. Unavailable or single-class
metrics remain explicitly undefined. A TRAIN frequency/action-type state baseline
remains available. Bootstrap intervals for world-mean accuracy/MAE group paired
renderings; pooled F1/AUROC/calibration remain descriptive without intervals.

S7/S8/S9 are absent from the current development slices, so this is not held-renderer
qualification. No success or failure of learning is claimed in Phase 0. Runtime
exports are MODEL_ESTIMATE with an attached artifact hash; absent targets are
listed as unavailable. The action endpoint is a prediction, not System 1.5 authority.

## Execution and compact exit gate

From this package directory:

```powershell
python -m graft.checks
python -m graft.freeze
python -m graft.train --substrate causal_base
python -m graft.train --substrate encoder_base
```

The training commands without `--train` only validate and run untrained forwards.
Actual Phase 1 uses the same command with `--train`; optional `--device cuda`
trains the graft over caches without modifying the backbone. All new artifacts
stay on C:. D: is read-only source storage. Existing outputs are not clobbered.

The frozen exit receipt contains exactly the nine charter conditions:

```ini
SUBSTRATE_IDENTITY_FROZEN = true
SURFACE_IDENTITY_FROZEN = true
STATE_ABI_FROZEN = true
TARGET_PROVENANCE_COMPLETE = true
PAIR_CONSTRUCTION_REPLAYABLE = true
TRAINING_OBJECTIVE_IMPLEMENTED = true
UNTRAINED_FORWARD_TESTS_PASS = true
NO_PROTECTED_TRUTH_CONTACT = true
PHASE1_CONFIG_READY = true
```

There is no Phase 0 accuracy gate. Tests and synthetic optimizer fixtures establish
execution, masking, gradients and checkpoint replay. Phase 1 determines whether
the partially supervised state interface learns.
