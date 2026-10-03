# X1 — non-oracle graph materialization (exploratory; plan fixed before the first run)

**Lane:** X-series (exploratory). **Data:** BANK-v1 TRAIN and DEV only. No sealed or escrowed truth. **Not** a confirmation of C-G1b. **Not** BANK-v2 (V2-0 is still characterizing that instrument; nothing here reads it).
**Frozen, not modified:** the X0 graph kernel, builder and controller (`ff-s15-x0-graph-sandbox-01/xg/*.py`, committed in `13d87e83`). Their source hashes go into the receipt and the run refuses to start if they differ. Only the **materializer** changes.

## Question

Does representing uncertain propositions as graph edges create downstream utility that a flat score merger cannot recover?
The question is not which producer has the best edge AUC, and "graph helped" is not an answer: the receipt must name the mechanism.

## What is held fixed

- The controller: `xg.control.decide(G, hi=0.6, lo=0.4, completeness=True, ambiguity=True, verify=True)` for the main runs, and `verify=False` (asymmetric thresholds without ASK) plus a **symmetric** control (`lo=None`, one threshold) for the X0 attribution.
- The candidate universe, the truth, the label conventions, and the evaluation subset (below).
- Every producer and merger parameter listed here. Nothing is tuned on the evaluation fold.

## Candidate propositions (the universe per world)

`AT(e, l)` for each object or agent `e` and location `l`; `CONNECTED(a, b)` and `BLOCKED(a, b)` for each ordered pair of distinct locations; `STATE(sw, ACTIVE)` and `STATE(sw, INACTIVE)` for each switch; `REQUIRES(dst, sw, ACTIVE)` (a gate) for each location and switch.
Truth = membership in the world's `initial_state` (a fact removed by BANK's MISSING mode is therefore absent, as in X0). Distractor predicates are not candidates.

## One ABI, no authority

Every producer emits `CandidateEdge{candidate_edge, relation_type, source_node, target_node, confidence, producer_id, provenance}`. `relation_type` may be `UNTYPED_LL` (a location-to-location edge whose predicate the producer cannot tell) or `UNTYPED_EL`. No producer decides anything; only the merger layer produces KEEP / DROP / DEFER.

## Producers

| id | what | cost | notes |
|---|---|---|---|
| T0 | deterministic schema/type prior | 0 | confidence = TRAIN rate of the predicate and argument types given the number of locations (for `AT`: one location per entity) |
| T1 | lexical/surface extractor | 1 | BANK-v1's own renderer produces the text (families S0–S6, S10, S11 occur in DEV); clause-level cue words plus entity mentions; confidence = TRAIN-calibrated precision of the cue pattern. A **controlled mention-miss rate** `m` drops each entity mention with probability `m` (seeded by world and mention): a stand-in for imperfect entity detection. `m` in {0, 0.2, 0.4}; **primary m = 0.2** |
| T2 | the frozen 230M `edge_existence` observer | 100 (proxy) | **cached scores only**: Lexi's run directory is no longer on disk, so the observer cannot be re-run. `universe-DEV.npz` from C-G0 holds its score for every typed ordered pair of every DEV world; rows realign to worlds by order, pair count, type sequence and label sequence (verified world by world; a world that does not align is excluded and counted). It covers `AT` and location-to-location existence only (`UNTYPED_LL`), never state, gates or block/connect typing. Confidence = calibrated on fold A |
| T3 | synthetic producer with controlled error structure | n/a | true facts with recall 0.90, confidence ~ N(0.75, 0.15); hallucinations at 0.03 per candidate, N(0.45, 0.15); **structured errors:** AT displacement to a neighbouring location (rate 0.15, N(0.65, 0.15)), STATE polarity flip (0.10, N(0.60, 0.15)), CONNECTED inversion (0.10, N(0.60, 0.15)). Levels low / mid / high multiply every error rate by 0.5 / 1 / 2 |

Producer sets compared at the same cost: **real = {T0, T1, T2}**; **controlled = {T0, T1, T2, T3}** at the three T3 levels.

## Mergers (all see exactly the same emitted candidates)

**Flat.** Score per candidate proposition, with `UNTYPED_LL` mapped naively to `CONNECTED`. Three variants: `max`, `mean` over emitting producers, and `calibrated` (logistic regression on `[logit(confidence), emitted]` per producer, fit on fold A). Output is a scalar; KEEP if `>= theta`, DEFER if `>= theta - 0.2`, else DROP.

**Graph.** Same base evidence, plus structure:
1. *provenance and relation semantics:* per `(producer, relation_type)` calibration (fit on fold A), `UNTYPED_LL` resolved between CONNECTED and BLOCKED by the typed evidence and priors, CONNECTED treated as undirected (the two directions share evidence), naive-Bayes combination of independent producers (*multi-producer agreement*);
2. *structural consistency (functional slots):* an entity has one location; KEEP the winning `AT` if it leads the runner-up by margin `0.25`, DEFER both if close, DROP the rest;
3. *contradiction handling:* two values of one switch state are both KEPT if both clear `theta` (a real contradiction is a label), otherwise the weaker is dropped or both are deferred;
4. *requirement deficiency (slot and link completion):* an entity with no location above `theta - 0.2` promotes its best `AT` candidate if that candidate has posterior `>= 0.25` and leads by the margin; a location graph split into components promotes the best bridging candidate by the same rule (*graph reachability*).
Output per candidate: KEEP / DEFER / DROP. KEEP is given weight 0.9, DEFER 0.5, DROP is omitted; flat output is mapped to the same three weights, so the controller treats both identically.

Operating points: `theta` in {0.30, 0.35, ..., 0.90} (13 points) for every merger.

## Evaluation

Fold A (calibration, never scored): DEV worlds with `hash(world_id) mod 2 = 0`. Fold B (evaluated): `= 1`. T0 and T1 calibrations come from a fixed 3,000-world TRAIN sample. **Evaluation subset:** fold-B worlds on which the oracle X0 controller (the frozen controller on the true facts) agrees with the label, so the comparison measures materialization and not BANK's label conventions; results on all fold-B worlds are also reported.

Three levels, reported separately:
1. **Edge quality**, per producer and per merger output: precision and recall at KEEP, and ranking (AP), by relation type.
2. **Graph quality**, per merger and operating point: contradiction rate (conflict seen by the controller on a world whose label is not a conflict), entities with two or more KEPT locations, goal entities with no kept location, missing-requirement agreement (a slot the controller sees empty versus a slot truly absent).
3. **Controller utility**: *coverage* = correct executions on ACT-labelled worlds over the ACT-labelled count (a first action on a shortest plan, judged by BANK's simulator); *harm* = wrong executions over all evaluated worlds; decision accuracy; ASK, ABSTAIN and stop agreement.

## Controls and ablations

Producer alone (each producer's own weights into the controller); flat `max`, `mean`, `calibrated`; graph; graph without provenance/relation semantics (one calibration for all relation types, directed CONNECTED, no UNTYPED_LL resolution); without contradiction handling; without deficiency handling; without multi-producer agreement (evidence by `max`); without structural consistency. The X0 asymmetric-threshold control is preserved: every merger runs under the DEFER controller, the asymmetric no-ASK controller and the symmetric controller.

## Decision rules (fixed now)

- **Matched comparison.** At coverage levels {0.50, 0.70, 0.85}, compare harm of the graph merger with the **best** flat variant at each level (lower envelope, linear interpolation), with a 1,000-resample world-level bootstrap, fixed seed `20260930`.
- **X1 earns continuation** iff, on the real set at primary `m = 0.2`, the graph merger has lower harm than the best flat variant at **at least two of the three** coverage levels with the 95% interval excluding zero, **and** the gain survives the controller controls (it does not vanish under the symmetric or asymmetric-no-ASK controllers). The receipt then attributes the gain: the mechanism whose ablation removes at least half of it is named; if none does, the gain is reported as unattributed and not as a finding.
- **Stop X1** if the graph merger is not better than the best flat variant on the real set across the useful region (intervals include zero, or favor flat). The graph remains a good representation; there is then no evidence that graph-aware arbitration buys anything over score fusion.
- **X5 (NLI as a producer) is earned only by X1 continuing.** It may add SUPPORTS / CONTRADICTS / UNKNOWN evidence on the same ABI and is stopped immediately if proposition quality does not improve downstream graph utility. It is never trained on ASK, action, escalation or disposition.
- No controller change to rescue a result. Every surprising result is reported as found; sensitivity sweeps of the fixed parameters are exploratory and labelled so.

## Receipt

`results/x1-receipt.json`, `RESULTS.md` generated from it with prose guards, source hashes of the frozen X0 files and of this folder, the alignment report for T2, and counts per stratum. Tests check the ABI, the producers' determinism, the merger algebra on hand-built cases, and that the frozen X0 sources are unchanged.
