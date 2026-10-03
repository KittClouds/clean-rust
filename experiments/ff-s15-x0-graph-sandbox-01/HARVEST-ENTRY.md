# Harvest entry — X0/X2/X4 graph-native sandbox (draft, exploratory lane; no Harvest location found in the repo)

**FINDING**
On BANK's symbolic records a typed weighted graph turns ACT, first action, conflict, unknown-entity, out-of-scope, alias ambiguity and ASK into structural readouts of one deterministic controller (84.2% 3-way decision accuracy against 77.0% for a flat baseline with three cheap booleans; 4,791 of 4,791 first actions valid; ASK recall 89.6% against 30.4%). ASK works as schema-slot completeness ("required minus present" over entity slots), not as need on the goal's path (24.4% recall). Under a noisy edge producer the harm reduction over a symmetric threshold comes from accepting supports at a high weight while respecting negatives (contradictions, gates) at a low one; an ASK/DEFER branch changes nothing that is executed, and its value is recovery: one round of oracle answers on the named candidates lifts coverage from 30.5% to 98.6% at σ=0.2.

**ENGINEERING PRINCIPLE**
Put every producer's output on one graph with weights and provenance, and let the controller ask "what required thing has no support and no contradiction?" — that single deficiency query names the ASK, the abstention and the verification target. Accept positives at a high weight and negatives at a low one.

**RECIPE**
Fixed relation vocabulary; schema rules for action preconditions/effects; SUPPORTS and CONTRADICTS from the fact producer with weights; hmax for reachability and depth cap, hadd only to choose the first action; slot completeness for ASK; asymmetric (hi, lo) thresholds; a control with the same thresholds and no ASK to attribute any gain.

**KNOWN COST**
Oracle edge producer (the graph is built from canonical records, so agreement with the simulator is close to by construction); BANK-synthetic schema; noise model is independent per edge; the answer model is an oracle and one round only. Development-grade and exploratory.

**DO NOT CLAIM**
That a real text-to-graph producer would behave like the noise model; that ASK/DEFER reduces harm (the asymmetric control explains it); that flat+'s win on IMPOSSIBLE labels is a capability (it is a generator artifact); that anything here is a C-series result.

**PRODUCT CONSEQUENCE**
Candidate for graduation only for the pieces that survive again on a different world set: slot-completeness ASK and asymmetric thresholds. The next X-step that would matter is a non-oracle producer (X1/X5: heterogeneous edge proposers or an NLI adjudicator) feeding this same kernel.

Evidence: `results/x0-clean.json`, `results/x0-noise.json`, `RESULTS.md`, plan `PLAN.md`.
