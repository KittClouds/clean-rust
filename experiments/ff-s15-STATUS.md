# System 1.5 build — ladder status (2026-09-29)

**State: waiting.** The current controller has extracted what its inputs justify. No further C-rung starts until new capability evidence arrives from Lexi (representation ladder) or FF (source/implementation selection),
or until the program owner gives an explicit go for a controller-only rung (see "Proposed, not started").

## Where each rung ended

| Rung | Folder | Outcome |
|---|---|---|
| C0 typed deterministic controller | `ff-s15-c0-runtime-01` | **PASS** — byte-identical decision and receipt, 106 tests, 14 golden cases |
| C1 real 230M observers behind C0 | `ff-s15-c1-observers-01` | **PARTIAL** — confidence bounds harm (5.1% vs 38.5% baseline) and transfers; only 5.7% of rows get a correct execution; ASK rule never fitted |
| C2a same-backbone surface coordination | `ff-s15-c2-coordination-01` | **STOP** — oracle headroom 15.3% vs 25% bar; the four surfaces share errors |
| ASK dedicated head | `ff-s15-ask-01` | **STOP** — linear adds nothing; MLP +13% AP, below the 1.25× bar; existing head already asks at ~50% precision, 15–20% recall |
| NLI-UNKNOWN as independent ASK evidence | `ff-s15-nli-census-01` | **STOP** — a *perfect* NLI veto lifts ASK recall only +6.7% (bar 25%) |
| C3a selective-risk geometry census | `ff-s15-c3a-risk-geometry-01` | **STOP** — no zero-training score beats C1's `min(P_decision, P_action)` at matched harm (only a one-level win at 10% harm); C3b not earned |

All results are development evidence on BANK-v1 DEV. No TEST row was read. Confirmation needs the fresh sealed split.

## What the ASK line established

The failure is ASK versus ABSTAIN — two forms of missing information — and BANK's ASK is exactly one requestable fact that the goal needs. The missing computation looks like
*(facts the goal requires) − (facts present)*: goal-conditioned sufficiency, not NLI and not NER as BANK defines them. That is a hypothesis for the representation ladder (Lexi), then a source/implementation question for FF
(symbolic comparison? NER plus set difference? a tiny head? does the pretrained 230M buy anything?). It is deliberately **not** built inside System 1.5.

## Boundary

- Lexi discovers what information is accessible.
- FF determines the cheapest useful implementation.
- Claudia composes proven capabilities into runtime behaviour. System 1.5 consumes capabilities; it does not manufacture each missing one.

## Standing rules (from this run)

1. **Oracle ceiling first.** Before building a coordinator, compute whether perfect secondary information could even help enough.
2. **Independence is not enough.** A second observer must be independent *and* informative.
3. **Compare frontiers at matched cost/risk.** Do not credit a more complex architecture for moving along a tradeoff the simpler system could already reach.
4. Preregister, freeze, score once; do not patch criteria or rescue a verdict; disclose post-hoc looks as exploratory.

## Closed doors (until new capability evidence)

No more same-surface coordination. No more ASK/NLI rescue. No new representation search. No generic MLP observer sweep. No goal-sufficiency model inside System 1.5. No attention-head work.

## Queued, not sent

The fresh sealed split request (`ff-s15-c2-coordination-01/CONFIRM-SPLIT-REQUEST.md`) stays unsent until Lexi finishes the current rung; it matters only when there is a candidate architecture worth confirming.
Harvest-style drafts: `ff-s15-c2-coordination-01/HARVEST-ENTRY.md`, `ff-s15-ask-01/HARVEST-ENTRY.md`, `ff-s15-nli-census-01/HARVEST-ENTRY.md`, `ff-s15-c3a-risk-geometry-01/HARVEST-ENTRY.md`.

## Proposed, not started (needs an explicit go)

*C3a was run on the program owner's explicit go ("C3a only, then stop") and stopped at its own rule; the rest below has not been started.*

A controller-only ladder that uses only information the runtime already has: C4a action-conditional safety census, C5 paired-renderer stability, C6 applicability-boundary census, C7 escalation economics (break-even for the larger tier), C8 observer lifecycle / ABI stress.
This conflicts with "idle until new capability evidence", so it has not been started.
