# X6-A — deficiency-guided acquisition (exploratory; plan fixed before the first run)

**Lane:** X-series (exploratory). **Data:** BANK-v1 TRAIN/DEV only (DEV fold B, the same worlds as X1). No sealed data, no BANK-v2, not a confirmation of C-G1b. X1 is closed (STOP) and is not reopened; X5 stays closed; no merger is added.
**Frozen, not modified:** the X0 kernel, builder and controller (hash-checked against `13d87e83`). X6-A may call the controller's public diagnostics (`decide`, `repair_set`, `slot_deficiency`); it changes nothing in them. X1's producers are read only to give the confidence policy the same information a model would have.

## Question

X1 showed that once a proposition is a candidate, calibrated score fusion is enough, and that a merger cannot supply a fact nobody proposed. So: **can graph structure reduce the cost of acquiring missing information by identifying what to query next?**

```
partial graph -> frozen controller -> blocking deficiency -> choose a query -> reveal -> update graph -> retry
```

## The environment

- **Worlds:** fold-B DEV worlds on which the oracle controller (frozen X0 controller on the true facts) gives the correct decision **and that decision is ACT** (a correct execution or NOOP). Recovery therefore means reaching that correct ACT.
- **Slots (the unit of a query):** `LOC(e)` for each object and agent (its `AT` facts); `STATE(s)` for each switch; `GATE(d)` for each location (the `REQUIRES` facts with destination `d`); `NBR(l)` for each location (the `CONNECTED` and `BLOCKED` facts whose source is `l`). Every true fact belongs to exactly one slot.
- **Hiding:** each **fact-bearing** slot is hidden with probability `h` (primary `h = 0.3`; sensitivity `h = 0.15` and `0.5`), seeded by world. A hidden slot's facts are absent from the working graph. A slot that truly has no facts looks identical to a hidden one until queried (closed-world ambiguity is real).
- **Query API:** `QUERY(slot)` reveals every hidden fact of that slot at **cost 1**, including when nothing was hidden (an *empty query*). No free oracle information: the policies see only the working graph, the controller's diagnostics, and the X1 producers' confidences.
- **Episode:** run the frozen controller (`hi = 0.5`, completeness and ambiguity on, the oracle configuration). If it decides ACT or NOOP the episode stops (recovered if it is the correct ACT, otherwise **harm**: a silent wrong execution that no acquisition can fix). Otherwise the policy picks an unqueried slot, pays 1, the graph is updated, and the controller retries. Budget: 8 queries.
- **Needs-recovery set:** worlds whose partial graph leaves the controller at ASK, ABSTAIN or conflict (the acquisition setting). Silent wrong ACTs and already-correct worlds are counted and reported, not scored as acquisition.

## Policies (all stop under the same rule)

| id | policy | information it uses |
|---|---|---|
| A | **random** | none; 20 seeded rollouts per world averaged |
| B | **confidence** | among slots that look empty in the working graph, query the one holding the candidate proposition whose producer confidence is closest to 0.5 (X1's T0 prior and cached T2 scores; T0 alone for state and gate slots) |
| C | **broad producer** | query a whole family of slots (`LOC`, `STATE`, `GATE`, `NBR`) at cost 1 per slot: one seeded rollout for each of the 24 family orders (slots within a family in a random order), the controller retried after every query, the 24 rollouts averaged |
| D | **graph deficiency** | only the slots that currently block the controller (below) |
| O | **oracle selector** | knows the hidden slots; the smallest subset whose reveal recovers. An upper bound, never a competitor |

**D in detail**, strictly in this priority, falling back to B when no signal fires:
1. *reachability and prerequisite blockers:* the controller's single-fact repair set (`repair_set`): patterns whose addition makes the goal reachable, mapped to their slot (an `AT` pattern to `LOC(e)`, a state pattern to `STATE(sw)`, a `CONNECTED` pattern to `NBR` of the endpoint that looks empty);
2. *conflict resolution:* a supported conflicting pair names the switch to re-query;
3. *missing slot identification:* the controller's slot-completeness deficiency (an object or agent with no location, a switch with no state, a location with no links) to `LOC` / `STATE` / `NBR`.
`GATE` slots can never be identified as blockers (an absent gate is indistinguishable from none); requestability filtering is trivial in BANK-v1 (every fact is requestable) and is reported as not applicable.

## Measures

- **Recovery** (correct ACT reached) and **correct-action recovery** (the first action lies on a shortest plan, judged by BANK's simulator), **queries per recovered world**, **information cost per recovered world** (queries), **irrelevant queries** (empty queries, and queries that revealed facts outside the oracle's minimal recovering set), policy wall time.
- **The matched-cost frontier:** recovery as a function of budget `b = 0..8`, with its area (AUC over `b = 0..6`).

## Decision rules (fixed now)

- **Continue** iff, at primary `h = 0.3`, D's recovery exceeds the **best of A, B, C at each replicate** at **at least two of the budgets {1, 2, 3}** with the paired world-level bootstrap interval (1,000 resamples, seed `20260930`) excluding zero **and** the AUC difference's interval excludes zero.
- **Stop** otherwise: the graph is then a representation and a deterministic controller substrate, not an acquisition engine.
- **Attribution** (if D wins): ablate each D signal (D without 1, without 2, without 3, and each alone with the B fallback). The signal whose removal loses at least half of the gain over the best baseline is named; if the gain is carried entirely by knowing which slot is empty (signal 3), the receipt says exactly that.
- No rescue: no policy is added or tuned after the first run; sensitivity to `h` is reported as exploratory.

## Receipt

`results/x6a-receipt.json`, `RESULTS.md` generated from it with prose guards, hashes of the frozen X0 files and of this folder, counts per stratum (needs recovery, already correct, silent wrong ACT, unrecoverable). Tests check the slot partition, the hiding model, the query API, the stop rule, each policy's information limits, and that the frozen X0 sources are unchanged.
