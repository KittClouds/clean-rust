# Phase 5 — Split Forge: Frizz / Qwen

Date: 2026-10-02
Status: E_SURVIVES_VERIFIED; final lane sealing. F not run (E survived).

## Assignment and boundary

Candidate-relative semantics first; decision computation second.
Frizz builds the state. Lexi independently studies computation over LFM state.
This plan covers only Frizz's Qwen bridge and E -> F access ladder.
It does not authorize changes to Lexi's experiments or construction of BANK-v3.
No composite score and no combination of mechanisms during Phase 5.

Use the previously qualified Qwen/Qwen3.5-0.8B-Base checkpoint, revision
`dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68`, not the instruct checkpoint or
the older Qwen3-0.6B-Base. Local model directory:
`D:/codex-runs/s15-lepori-qwen-0.8b-base-v01/models/Qwen3.5-0.8B-Base`.
Preserve the completed two-run trial and its frozen sources unchanged.

## Current readiness evidence

Superseding the initial scaffold hold, the user supplied BANK-v3-core v0.4 at
`C:/phoenix-target-overgraph/bank-v3-core-20261002-v04`.
Release identity: `84f0a7e13032e8cdfcecc862217bb33ca23568fade64fafeef410327eb996f12`.
Manifest SHA-256: `2033aabd67bce5a018a32ee7417cf2b282c8bb269419ba2458a320b59002524d`.
Seal-bound manifest, handoff, report and replay hashes match; the build contract
also matches its manifest entry. No evaluation files were opened by Frizz.

Packaging defect: both the handoff and manifest split subobjects contain empty
input/supervision maps and identical hashes of `{}`. The top-level manifest DOES
bind actual shards. `release-binding-v01.json` separately records normalized
TRAIN/DEV public/data file maps and their verified hashes, without changing the
bank release. The user accepted those bindings. Corrected handoff v0.2 matches
all four TRAIN/DEV file maps and split identities. Its SHA-256 is
`08cab38d366d6a30d32af4b0391cafddb243a8ea9e6a7435ad53290462d41a4b`.
The packaging hold is cleared; original seal and corpus bytes are unchanged.

`adapter-audit-v01.json` records exhaustive ID alignment, public-input allowlisting,
paired-root supervision agreement and action eligibility across all 24,000 TRAIN
and 6,000 DEV rows. Nine boundary tests pass. Maximum candidates: TRAIN 171,
DEV 158; no truncation. Action support: 1,333 TRAIN / 333 DEV canonical roots.
Only MOVE (249 DEV roots) meets the 200-root per-class floor; all other DEV
action-type classes remain underpowered. Do not count paired renderings as
independent worlds. Conflict and aliases remain diagnostic-only, zero loss.
Unavailable ontology targets must be omitted, not filled with invented labels.
Do not substitute BANK-v1/v2 rows and call them v3.

## Phase 5A — mechanism-free Qwen bridge

BANK-v3 is the main experimental substrate. BANK-v1 is legacy regression and
historical phenotype only; never use v1-v3 score differences as a mechanism effect.
Establish one Qwen bridge baseline before judging E. No new access organ,
recurrence, stochasticity, LoRA, or IHA in the bridge.

After release inspection, freeze a bridge specification covering candidate
identity, observable inputs, target semantics, loss weights, training dose,
normalization, readout budgets, model surfaces, selection rule, seeds, and costs.
Carry forward repaired TRAIN-only consistency and differentiable regularization
where applicable. Do not copy v1 action vocabulary, tensor bounds, candidate
caps, or loss semantics without validating them against the v3 contract.

Common flight recorder, reported separately:

- Initialization accessibility and initialization-to-trained delta per channel.
- Frozen linear and tiny-MLP accessibility at matched doses.
- Production-head results and functional ablations.
- Exact logged action and optimal-set hit, with separate denominators.
- All ten capability axes and predeclared hard slices.
- Trainable/frozen parameter counts, training cost, inference latency and memory.

Keep selected actions outside the candidate set unscored; no coercion. Audit
empty optimal sets and exclude them from optimal-set hit unless the finalized
contract explicitly supplies a different justified definition. Include counts.
Recoverability instruments require known-solvable positive controls; if controls
collapse, classify instrument failure before interpreting the target.
Descriptive slices are not post-hoc selection criteria. Protected evaluation
failures must not steer architecture selection, curation, or training weights.

Capability axes: binding, evidence_support, counterevidence,
missing_requirements, conflict, composition_depth, transition_depth,
candidate_comparison, globalization, nuisance_invariance.

## Phase 5-E — structured candidate contextualization

Question: can explicit typed candidate/context integration improve robustness
over the generic dense graft while preserving candidate identity?

Typed contract:

- q_j: named candidate/action identity.
- r_j: candidate arguments and observable entity-role representations.
- g: observable goal representation.
- w: observable world/context representation.
- e_j = Phi(q_j, r_j, g, w): small candidate-preserving access organ.

Goal context must meet a named candidate without destroying candidate identity.
Select and freeze one bounded interaction design only after the v3 input schema
is known; gated, bilinear, or role-factorized interactions are candidates, not
permission for mechanism shopping. Never expose latent supervision as input.
Hold downstream computation and evaluation policy matched to the bridge.

Primary axes: binding, candidate_comparison, globalization.
Secondary diagnostics: evidence_support and counterevidence; retain all other
recorder outputs. Inspect unsatisfied-goal and legal-MOVE slices where v3 makes
them meaningful: the v1 isolation result was not a uniform slice improvement.

No recurrence, stochasticity, LoRA, or IHA. Predeclare survival criteria and
uncertainty reporting before E runs: improvement on hard primary cells while
preserving Qwen strengths, assessed as a response vector, not one aggregate.
Numerical thresholds remain unset until the bridge and sampling contract exist.

The verified bridge is now frozen. One E family was prospectively specified in
the artifact E/SPECIFICATION.json: typed gated relational residual, 169,708 extra
trainable parameters, zero residual at initialization, matched eight epochs.
All logical response-vector gates passed after persisted-probe replay. Hard
binding and globalization passed; candidate comparison did not meet its gain
threshold. Fixed e-linear goal accessibility improved by 0.064685 (paired-root
95% CI 0.050090–0.079880). Full axis/ablation replay also passed.
No F specification or training run was created because E survived. This is one
synthetic DEV acquisition result, not protected generalization or a substrate
ceiling. Final artifacts are in frizz-phase5-access-20261002-v01.

## Phase 5-F and handoff

If E does not survive the frozen rule, test F as an alternative access family:
sparse nonlinear expansion of the same qualified inputs. Do not combine E and F
or add an action-computation mechanism. Frizz's Phase 5 ladder stops at E -> F.

The bridge specification is BRIDGE.md; 21 unit tests and a deterministic CUDA
backward smoke pass. Full-context extraction completed in artifact version v02.
The local pipeline proceeds through dataset assembly, one bridge training run,
fixed-dose readouts, and fresh-process replay. E does not start automatically.
Preparation v01 qualified the substrate then failed before feature output on a
missing import; it is preserved and corrected in v02, without consuming training.
Assembly v01 then stopped before dataset serialization on observable action IDs
absent from public entity bindings. ASSEMBLY-REPAIR-v02.md preserves the argument
positions with zero-vector sentinels. Original pipeline failure and source v01
remain intact; frozen-source-v02 drives the first bridge training run.
The supplemental recorder persists every declared probe and verifies its saved
predictions in a fresh process before BRIDGE-FROZEN.json can be created.

Phase 6, separately authorized, may test composition of the surviving access
organ with Lexi's surviving computation organ. Corpus generation, protected
scoring and Phase 6 remain outside this implementation.
