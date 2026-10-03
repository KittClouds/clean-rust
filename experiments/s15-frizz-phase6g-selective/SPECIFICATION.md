# Phase 6G — selective legality under observable uncertainty

Prospective specification. No model extraction, backbone adaptation, bank
mutation or protected evaluation. Frozen Qwen revision and E machinery inherit
their sealed Phase6F input pins. Conditional EXECUTE 1333/333 TRAIN/DEV roots,
all candidates, both renderings grouped, exact inherited root/renderer joins.

Targets are sealed Phase6F STRICT statuses only: 0 CERTAIN_LEGAL,
1 CERTAIN_ILLEGAL, 2 UNRESOLVED. Clause internals, hidden legality and selected
candidate IDs never enter training. Canonical legality is diagnostic only.
The sealed clause stream supplies targets, and all row/candidate/family joins
and simulator-derived diagnostic truth are checked. No recipe-closed-graph
labels substitute for strict statuses.

ABI: [c256; shared s64] = cs320, concatenated with trained E e32, nine action
type bits and four argument-vector presence bits: 365 inputs. Presence means
packed argument index >= 0, not existence in canonical truth. All continuous
features standardized with root-balanced TRAIN-only mean/variance; no DEV fit.
Three-way MLP 365->128 GELU->64 GELU->3. Seed0; CPU FP32 four threads;
AdamW 3e-4, weight decay .01, gradient clip1, 12 fixed epochs, epoch12 endpoint.
16 roots/batch; paired renderings retained together. Class weights inverse
root-balanced TRAIN prevalence, normalized to mean1. Weighted CE averages
valid candidates per rendering, then root pairs equally. No other loss.

Before training: all saved D init/trained, ten E raw/E-state init/trained arms
and final micro-LoRA binary logits are mapped by frozen threshold >0 to CL,
otherwise CI. Binary arms never abstain. Report entire panel, no best-arm
selection. D trained is the prospectively fixed exact-partition comparison.

False certainty = predicted CL/CI among TRUE UNRESOLVED (conditional denominator).
False abstention = predicted U among TRUE CERTAIN. Also report absolute error
fractions among all candidates, canonical correctness only as diagnostic,
confusion matrix, macroF1, mean class recall/BA, per-class precision/recall,
root exact three-way partition and separate CL/CI/U sets, certainty per root,
zero/all/any-certain root supports, and both renderers separately.

Frozen consequence cost from Phase6C is the unchanged ranker, ascending cost
with stable candidate-index tie breaking. Filter CI only; retain CL and U.
Full and gold-selected-type-conditioned rankings report logged selected and
optimal-set endpoints separately. Primary uncertainty slices use TRUE strict
oracle statuses: non-logged same-type U competitor absent/present. Predicted
slices separately descriptive. Oracle filter is a status-perfect REFERENCE,
not an upper bound on decision accuracy or a gold legality filter.

Authorization uses MODEL-CHOSEN winner, never gold logged selection. Chosen
candidate must be predicted CL; all rivals whose frozen cost <= winner cost
(ties conservatively included) must be resolved. Empty retained menus abstain.
Report full-menu authorization as primary and gold-type-conditioned version
as diagnostic only. Report logged exact accuracy and optimal hit separately
on authorized eligible roots, and gold-status authorization consistency.
This is procedural epistemic authorization under frozen ranking, not action
permission, optimality certification or guaranteed canonical legality.

SURVIVAL: primary renderer epoch12 false-certainty <=.05, certainty coverage
>=.70, and exact three-way root reconstruction improves >=.05 absolute over
the fixed D-trained binary baseline. Paired renderer reported, never selected.
No thresholds, extra epoch or architecture rescues. Otherwise retire as built;
localize unknown detection versus certain grounding using the declared panel.

Fresh process replay must reproduce all DEV logits, metrics and dispositions
exactly. Independent target-stream verification and known-solvable controls
must pass. Freeze sources/inputs before baseline scoring and before any fit;
seal checkpoint, targets, outputs, costs and replay. Ordinary repairs preserve
failed identities and are versioned, never silently rewrite a completed run.
