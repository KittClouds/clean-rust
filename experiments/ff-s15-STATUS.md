# System 1.5 build — ladder status (2026-09-29)

**State: BANK policy/controller-mining branch CLOSED (program owner's decision, 2026-09-29).** Nothing further runs on it. The next work waits for Lexi's surviving graph operations (see "Next"); nothing has been started on that.

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
Harvest-style drafts: `ff-s15-c2-coordination-01/HARVEST-ENTRY.md`, `ff-s15-ask-01/HARVEST-ENTRY.md`, `ff-s15-nli-census-01/HARVEST-ENTRY.md`, `ff-s15-c3a-risk-geometry-01/HARVEST-ENTRY.md`, `ff-s15-c4a-action-safety-01/HARVEST-ENTRY.md`.
