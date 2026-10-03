# X0/X2/X4 — the smallest graph-native System 1.5 sandbox (exploratory)

**Lane: X-series (exploratory).** Loose ceremony, allowed to fail fast. It uses BANK-v1 TRAIN/DEV symbolic records only. It touches no sealed split, changes no C-series rule and earns no C-series claim. If something here survives twice it graduates to a C-series experiment with a real contract.

## Question

If the runtime's world is a typed weighted graph (state, action, goal, requirement and evidence nodes; REQUIRES / SUPPORTS / CONTRADICTS / APPLICABLE_TO / CAUSES / ACHIEVES edges) instead of a flat policy class, which of the old capabilities (act, abstain, conflict, unknown entity, ask) become structural readouts, which stay hard, and which new ones appear? Specifically:

- **X2:** can ACT / ABSTAIN / NOOP be read off the graph by a deterministic controller with no training?
- **X4:** is ASK just a graph deficiency, i.e. "a requirement on the goal's path has no support and no contradiction, and adding one single fact would repair the path"?

## Setup

- Input is BANK's canonical symbolic record (facts, goal, available actions), i.e. the oracle edge producer. Text-to-graph is not tested here. The noise sweep stands in for a real producer.
- Builder: schema rules give each action its REQUIRES / CAUSES / ACHIEVES edges; each fact gives SUPPORTS / CONTRADICTS edges with weight = producer confidence.
- Controller: delete-relaxed reachability over the requirement graph (hmax, depth cap 4 as in BANK's oracle), conflict, unknown-entity and out-of-closure checks, and a single-fact repair search for ASK.
- Labels are scored as BANK gives them. BANK's labels come from the generation mode, not from a physical check, so some labels have no structural signature in the record. Each such case is reported as a floor, not counted against the graph.

## Competing representations

- **Flat:** a decision tree over raw counts (fact predicates, entities, actions, goal type). Trained on TRAIN, scored on DEV.
- **Flat+:** the same plus three cheap booleans (goal already holds, goal entity unknown, duplicated STATE with two values). The gap between flat+ and the graph controller is exactly reachability and deficiency.
- **Graph controller:** zero training.

## Experiments and failure conditions

1. **Clean graph (full DEV).** Decision agreement (3-way ACT/ASK/ABSTAIN) with BANK's labels, by label class. ACT actions are judged by the BANK simulator (the action must lie on a shortest plan). Failure: the graph controller does not beat flat+ on the reachability classes, in which case the graph adds nothing over booleans.
2. **ASK as deficiency.** Recall of BANK's ASK label, identifiability (size of the repair set; was the true missing fact in it), and how many ASK labels are even structurally about a needed fact (the removed fact may be irrelevant to the goal). Failure: the deficiency rule cannot separate ASK from ABSTAIN-insufficient more often than chance.
3. **Noisy producer (5,000-world DEV subsample, seeded).** True facts get confidence clip(0.8+σz); hallucinated supports get clip(0.35+σz). Compare a hard-threshold controller swept over τ with a KEEP/DEFER/DROP controller whose deferred edges on the goal path become ASK. Report the executed-action error vs coverage frontier (matched-harm). Failure: the DEFER point does not lie below the hard-threshold frontier at any σ.

## Receipt

`results/x0-receipt.json` plus a short `RESULTS.md` generated from it with prose guards. Nothing here is a result about System 1.5's models.
