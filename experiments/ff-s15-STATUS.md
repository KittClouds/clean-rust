# System 1.5 build — ladder status (2026-09-30)

## Bank generation lineage

- **BANK-v1 policy/controller-mining branch: CLOSED 2026-09-29.** Historical BANK-v1 remains
  sealed and is not reopened. Its known label-contract and seal-gate limitations are recorded as a
  historical audit in `ff-s15-bank-01/BANK-V1-POSTMORTEM-2026-09-30/POSTMORTEM.md`; that audit is
  history, not a work queue, and no v1 file is modified.
- **BANK-v2 generation branch: OPENED 2026-09-30 as a new experimental generation.** BANK-v2 does
  not amend, repair, supersede evidence from, or reopen BANK-v1. It supersedes BANK-v1 only as the
  **active bank-generation program**. Current phase (2026-09-30): constitution **v0.7 sealed**
  (`ff-s15-bank-02/BANK-V2-FREEZE.md`, O11 closed by ruling C); `src/bank2` built against it; the pilot
  passed all eighteen gates with every coverage requirement met; **`BANK_v2_SEALED = true`** (18/18 gates,
  725,000 canonical worlds, 800,000 rendered rows, 120,000 paired-panel pairs; receipts in `ff-s15-bank-02/receipts/`,
  data under `ff-s15-bank-02/out/full/`, git-ignored). No model has touched it: `frozen_fabric_contact=false`,
  `terminal_truth_opened=false`. The provisional amendments F1–F5 and G1–G6 are **ratified**
  (`ff-s15-bank-02/RATIFICATION-2026-09-30.md`); thin cells (`prohibited_edge` 0.6%, `TRANSFER`) are recorded, not
  regenerated, and any later need gets a targeted supplemental panel. **C-G1b stays separate:** BANK-v2 is not its
  confirmation split (it needs a fresh sealed sample from the BANK-v1 graph regime); BANK-v2 is a later independent
  generalization challenge.
- **Next on BANK-v2: rung V2-0 (instrument characterization), no neural model.** Its evaluation constitution is
  frozen before any run (`ff-s15-v2-eval-00/V2-0-CONSTITUTION.md`): six deterministic baselines (oracle, majority,
  schema/frequency, lexical, surface cue, graph-only) fit on TRAIN, scored once on DEV, stratified by action type,
  reason, query scope, slot type, missing cardinality, renderer and intervention family; a target is
  `CUE_ACCESSIBLE` if a cheap baseline reaches macro-F1 0.80; escrowed test truth stays unopened. Baselines and the driver are
  not written yet. The later rungs are V2-1 representation atlas (causal 230M vs bidirectional 230M encoder, same coordinate
  family and cheap heads), V2-2 graph interface (Claudia's clean X0), V2-3 adaptive prospecting; each needs its own constitution.
- **BANK-v1 remains a valid historical instrument** for the question it was built to ask (a
  state/action stress bank). It is not a failed bank; it is the wrong instrument for the later
  question of whether ASK is structurally derivable from the observable world.

**State: BANK-v1 policy/controller-mining branch CLOSED (program owner's decision, 2026-09-29).** Nothing further runs on it. The next work waits for Lexi's surviving graph operations (see "Next"); nothing has been started on that.

The surviving contribution is the architecture, not BANK's policy capability:
**typed observer + confidence gating + escalation + deterministic authority + replayable receipt.** Keep that machine. Retire the question of whether this particular frozen 230M can become a decent BANK actor.

## Where each rung ended

| Rung | Folder | Outcome |
|---|---|---|
| C0 typed deterministic controller | `ff-s15-c0-runtime-01` | **PASS** — byte-identical decision and receipt, 106 tests, 14 golden cases |
| C1 real 230M observers behind C0 | `ff-s15-c1-observers-01` | **PARTIAL** — confidence bounds harm (5.1% vs 38.5% baseline) and transfers; only 5.7% of rows get a correct execution, almost all of them NOOP (see below); ASK rule never fitted |
| C2a same-backbone surface coordination | `ff-s15-c2-coordination-01` | **STOP** — oracle headroom 15.3% vs 25% bar; the four surfaces share errors |
| ASK dedicated head | `ff-s15-ask-01` | **STOP** — linear adds nothing; MLP +13% AP, below the 1.25× bar; existing head already asks at ~50% precision, 15–20% recall |
| NLI-UNKNOWN as independent ASK evidence | `ff-s15-nli-census-01` | **STOP** — a *perfect* NLI veto lifts ASK recall only +6.7% (bar 25%) |
| C3a selective-risk geometry census | `ff-s15-c3a-risk-geometry-01` | **STOP** — no zero-training score beats C1's `min(P_decision, P_action)` at matched harm (only a one-level win at 10% harm); C3b not earned |
| C4a action-conditional safety census | `ff-s15-c4a-action-safety-01` | **STOP** — per-action thresholds add +7% at 3–5% harm (bar 10%); the cheap tier is a NOOP executor |

All results are development evidence on BANK-v1 DEV. No TEST row was read.

## What the branch established

**System 1.5 on BANK learned a selective NOOP lane, not a general action lane.** C1's "correct executions" are about 96% NOOP — a correct "nothing needs doing". On the primary surface the frozen rule correctly executes 25.9% of truth-NOOP rows and 0.9% of truth MOVE/ACTIVATE rows.
At the same threshold harm is 3.8% for NOOP, 22.7% for MOVE and 67% for ACTIVATE, and MOVE and ACTIVATE are at least ~20% harmful even among their most confident candidates, so a single confidence threshold already keeps them out. Real state-changing actions (about half of the ACT rows) almost always escalate.
Cheaply proving that no action is necessary is a legitimate System 1.5 capability; it is not evidence that a frozen substrate yields a general state-action machine.

The ASK line: the failure is ASK versus ABSTAIN — two forms of missing information — and BANK's ASK is exactly one requestable fact the goal needs, i.e. *(facts the goal requires) − (facts present)*: goal-conditioned sufficiency, which neither NLI nor NER as BANK defines them carries. That is a question for the representation ladder (Lexi) and then for FF; it is deliberately not built inside System 1.5.

**Scale sensitivity: unresolved and intentionally untested.** A 1.2B or 2.6B backbone might improve these numbers. The engineering question does not require resolving that, so it has not been run and is not planned.

## Boundary

- Lexi discovers what information is accessible.
- FF determines the cheapest useful implementation.
- Claudia composes proven capabilities into runtime behaviour. System 1.5 consumes capabilities; it does not manufacture each missing one, and it does not mine a capability for its own sake.

## Standing rules

1. **Oracle ceiling first.** Before building a coordinator, compute whether perfect secondary information could even help enough.
2. **Independence is not enough.** A second observer must be independent *and* informative.
3. **Compare frontiers at matched cost/risk.** Do not credit a more complex architecture for moving along a tradeoff the simpler system could already reach.
4. Preregister, freeze, score once; do not patch criteria or rescue a verdict; disclose post-hoc looks as exploratory.
5. **Break every coverage/harm figure down by the type of action** (C1's headline was almost entirely NOOP).

## Retired and postponed

- **C5 paired-renderer stability, C6 applicability boundary, C7 escalation economics: retired as BANK-policy experiments.** C5 would characterise a controller nobody now intends to carry forward; C6's answer is already visible (NOOP applicable; MOVE and ACTIVATE not safely applicable);
  C7 reduces to the value of filtering some NOOP cases minus observer cost, which should be computed against a real workload, not BANK's synthetic NOOP prevalence.
- **C8 observer lifecycle / ABI stress: postponed** until there are graph ObserverBundles worth hardening (hot-swaps, stale scalers, mismatched bundles, replay, corruption, upgrades).
- **Closed doors:** no more same-surface coordination; no more ASK/NLI rescue; no new representation search; no generic MLP observer sweep; no goal-sufficiency model inside System 1.5; no attention-head work; no BANK-policy capability mining.

## C-G0 residual edge-pruning census (2026-09-29; ran on the program owner's go)

`ff-s15-cg0-edge-pruning-01`: Lexi's frozen edge-existence observer (T1) on the natural ordered-pair universe vs a deterministic type-pair table (T0). **Preregistered gate PASSED** (pooled TEST gain +11.9 / +14.5 points at 1% / 2% edge loss, bar 10; positive on S7/S8/S9; above noise), development-grade.
Caveats that decide C-G1: T0 alone prunes 76% of non-edges at zero edge loss; the held-renderer gain is only +7.1 / +9.3 (S9 +4.3 / +5.2, where T1 alone is worse than T0); and T1's DEV-fitted threshold does not transfer (a 1% budget loses 6.65% of edges on TEST, 17% on S9).
C-G1 (contract) and later steps are not started.

## C-G1 score transport under shift (2026-09-29; ran on the program owner's go)

`ff-s15-cg1-score-transport-01`: four zero-training relative transforms of the frozen T1 edge score, one DEV threshold each applied unchanged to TEST, against a gate fixed in advance (pooled loss <= 2% / 4%, held <= 3% / 5%, pooled gain >= 5 points).
**No transform advances; C-G1 stops with the boundary result:** T1 supplies robust ranking but not a transportable selective-execution score under the tested shift. Type-pair percentile cuts the 1% target's pooled loss from 6.65% to 2.9% and fixes six of twelve renderers, but S9 stays at 11%.
Exploratory only (found after seeing TEST): the same transform at a derated DEV budget meets every bound on paper with about +5 points of gain left, a candidate for the fresh split. No bundle or C0 v2 is earned.
The sealed-split request is redrafted for graphs (`ff-s15-cg1-score-transport-01/CONFIRM-GRAPH-SPLIT-REQUEST.md`), unsent.

## X-series: exploratory lane (2026-09-30)

C-series stays confirmatory (frozen rules, sealed fresh data, no improvisation). X-series is exploratory: a cheap baseline, one or two competing representations, a stated failure condition and a short receipt; open data only (BANK TRAIN/DEV), never the sealed split; allowed to fail fast. Something that survives twice graduates to a C-series experiment with a real contract. C-G1b stays pristine.
Umbrella question: what useful machine appears if System 1.5 operates over a typed weighted graph instead of flat policy classes?

- **X0/X2/X4** (`ff-s15-x0-graph-sandbox-01`, exploratory, oracle edge producer): a zero-training graph controller reads ACT and its first action (4,791 of 4,791 valid), conflict, unknown entity and alias ambiguity off structure, and ASK off schema-slot completeness (recall 89.6% vs 30.4% for a flat baseline with three cheap booleans; only 24.4% as goal-path need); 84.2% vs 77.0% 3-way decision accuracy. Floors: 8% of DEV worlds have no structural signature, ASK vs ABSTAIN on a missing fact is a 60/40 label coin flip, and IMPOSSIBLE labels follow a generator artifact (doubled BLOCKED pair) that only the flat baseline picks up. Under a noisy producer the harm gain over a symmetric threshold comes from asymmetric thresholds (accept high, respect negatives low), not from DEFER; ASK's value is recovery (oracle answers lift coverage 30.5% to 98.6% at sigma 0.2).
- **X1 non-oracle graph materialization** (`ff-s15-x1-materializers-01`, exploratory, BANK-v1 TRAIN/DEV, frozen X0 controller hash-checked): **STOP.** Four producers behind one candidate-edge ABI (schema prior, lexical extractor with a controlled mention-miss rate, cached 230M edge-existence scores, synthetic structured noise); graph-aware arbitration (per-relation calibration, agreement, functional slots, contradiction handling, slot and link completion) never beat a **calibrated flat merger** at matched coverage and harm, and lost at low coverage in two settings (+0.8 points of harm at 21% coverage at mention-miss 0.2; +0.4 points at high synthetic noise). Multi-producer agreement is the only mechanism with a large effect and the calibrated flat merger recovers it; a merger cannot supply a fact no producer proposed. The preregistered coverage levels were unreachable at the primary setting (a planning error, recorded); a labelled exploratory comparison at reachable levels reaches the same conclusion. **X5 (NLI as a producer) is not earned and was not started.**
- **X6-A deficiency-guided acquisition** (`ff-s15-x6a-acquisition-01`, exploratory, BANK-v1 DEV fold B, frozen X0 graph/controller hash-checked; uncommitted): hidden fact slots, costed `QUERY(slot)`, random/confidence/broad-producer/graph-deficiency/oracle at matched cost. **Preregistered rule: CONTINUE** (D beats the best baseline at budgets 1-3 and on AUC at h=0.15/0.3/0.5; AUC 0.478 vs confidence 0.430 at h=0.3, oracle 0.667). **Attribution: schema closure, not graph inference.** The whole gain is signal 3 (slot completeness); the conflict signal never fires; the repair-set signal hurts (signal 3 alone 0.603). A post hoc graph-free schema rule (skip the GATE family) reaches 0.588 and beats D_full by 0.11 AUC; signal 3's increment over it is 0.015 (0.010 to 0.020) at h=0.3, n.s. at 0.15, with about +1 point of wrong-ACT rate. Next: only on BANK-v2 (conflicts, requestability, per-slot cost) after V2-0 freezes its cue audit, schema rule as the baseline. X5 stays closed; V2-2 stays design-only.
- **VCS-1a Vector Trust Region Runtime, infrastructure only** (`ff-s15-vcs1a-runtime-01`, ruled GO 2026-09-30; uncommitted): schema-agnostic authority over an externally supplied `VectorControlState` schema. Region DSL (axis rules plus ball/halfspace geometry, exact arithmetic, three-valued missing handling), ordered-rule authority with typed EXECUTE/ASK/ESCALATE/DECLINE_UNAVAILABLE/NOOP and byte-identical replay, scalar comparator, matched-harm/coverage/cost harness (the vector policy must beat the scalar frontier, not slide along it), TRAIN-fit/freeze/shift transport harness. **FROZEN 2026-09-30** (`vcs1a-freeze.json`, `VCS-1A-FREEZE.md`): `dominates` convention, both scalar comparisons (transported and hindsight), a nasty scalar family, substrate comparison against a canonical semantic state, and a derivation-audit circularity guard for FROZEN schemas. 71 tests, synthetic fixtures only, zero scientific evidence. **No provisional `z` and no BANK-v1 results by ruling; Lepori owns the schema.** VCS-1b does not run against the current atlas; it waits for Lepori's frozen *operational* schema (observable semantic state plus a per-substrate estimator). Claudia asks that V2-0's cue audit also report coordinate-target derivational dependence (target derived from the field, field downstream of the target, shared generator logic). BANK-v2 stays off limits until V2-0's cue audit freezes.
- **V2-2 graph interface on BANK-v2:** design draft only (`ff-s15-v2-graph-design-00/V2-2-DESIGN-DRAFT.md`, reads the constitution, no BANK-v2 data); it starts only after V2-0 completes and its cue audit is frozen, and its baseline is the calibrated flat merger.
- Not started: X3 state-action transition graph, X5 NLI as edge adjudicator, X6 frozen adaptive memory, X7 proposal-queue simulation.

## Next (not started; waits for Lexi)

```
Lexi finishes Rung 1
  -> held S7/S8/S9 decide which graph operations survive
     (current candidates: NODE_TYPE, EDGE_EXISTS, EDGE_LABEL, ONE_HOP, TWO_HOP, LINK_COMPLETION — Lexi decides)
  -> freeze the surviving operations
  -> package the cheapest adequate readout as an ObserverBundle
     (operation, representation contract, readout type, weights, calibration, applicability, confidence, provenance)
  -> Claudia runs them through typed confidence + escalation + deterministic authority + receipts
     (no policy head is retrained; the C0/C1 selective-execution skeleton is reused)
  -> measure selective graph utility
  -> FF asks whether the 230M is worth its cost on each operation that earned existence
     (source ladder: lexical / token / random / 230M pretrained / small from-scratch)
```

## Queued

The fresh sealed split request (`ff-s15-c2-coordination-01/CONFIRM-SPLIT-REQUEST.md`) stays unsent. It was drafted to confirm BANK-policy results; with that branch closed nothing is waiting on it. Keep the draft as a template for whenever a surviving graph architecture needs a sealed confirmation set.
Harvest-style drafts: `ff-s15-c2-coordination-01/HARVEST-ENTRY.md`, `ff-s15-ask-01/HARVEST-ENTRY.md`, `ff-s15-nli-census-01/HARVEST-ENTRY.md`, `ff-s15-c3a-risk-geometry-01/HARVEST-ENTRY.md`, `ff-s15-c4a-action-safety-01/HARVEST-ENTRY.md`, `ff-s15-cg0-edge-pruning-01/HARVEST-ENTRY.md`, `ff-s15-cg1-score-transport-01/HARVEST-ENTRY.md`, `ff-s15-x0-graph-sandbox-01/HARVEST-ENTRY.md`.
