# GC1 follow-up: reviewed constructor program

Date: 2026-09-18. Status: **DRAFT FOR REVIEW; NOT A SEALED EXECUTION PROTOCOL**.

This document reviews the supplied reviewer response and specifies the next work. It does not launch replay, candidate generation, a constructor, fresh-seed qualification, or behavior. Existing sealed artifacts remain unchanged. Proposed identities must be checked for collisions before creation.

## 1. Decision and evidence boundary

Proceed with failure anatomy before redesigning the constructor. Keep the palette/search-capacity alternatives alive alongside geometry and collateral. Reserve **GC2 for fresh-engineering-state qualification**, as in the earlier program; call a geometry-aware development successor **Q10-GC1-GA1**, not GC2.

The current audited result is 14 geometry-valid, baseline-improving, distinct outputs from 14 endpoint/set cases within seed9731. Aggregate mismatches decreased 3,386 to 2,454: 1,050 initially wrong rows were repaired and 118 initially exact rows became wrong. Zero exact alternative endpoints were constructed. The eight invalid saved best-search states are diagnostics, not unconstrained optima or the best states ever evaluated.

Hierarchical palette composition produced useful partial global repairs in this family. That supports its engineering usefulness; it does not establish that hierarchy is necessary or superior to flat search. Likewise, collateral is measured readout interference, not yet a continual-learning mechanism. No new support is claimed here for biological mechanisms, latent adaptive state, or future-learning divergence.

## 2. Corrections to the reviewer proposal

| Proposal | Reviewed disposition |
|---|---|
| D1 uses saved states | Accept. Reconstruct saved states only; do not silently add ablations or swaps. |
| Identify groups responsible for damage | Support incidence is association. Add a separately named counterfactual replay stage for contextual effects; there need not be a unique responsible group. |
| Test unused candidates | Replace a group's current choice with another choice, including ZERO. Never stack two alternatives from the same group. |
| Signed geometry can reveal cancellation | Yes for axis and each linear-drive component; unsigned norm/error summaries discard needed information. Matching one debt does not satisfy all gates. |
| One/pair cancellation is cheap and decisive | Cost must be counted first. Negative shortlisted pair results are bounded search failures, not impossibility or rejection of geometry-aware assembly. |
| Build four new beam lanes | Conditional on diagnostics, with a paired common-runtime control. Changing several policies together cannot isolate one mechanism. |
| Rename next constructor GC2 | Reject identity reuse. Preserve GC2's fresh-state validation role. |
| After six hours | Do not repeat an elapsed-time claim without a defined, verified timing source. Evaluation calls are not unique configurations. |

## 3. Current source bindings and preflight

Use the sealed PAR8 execution, palette library, PF0 topology, PF5 geometry definitions, parent data/runtime, and the reviewer packet as the source chain. Bind complete SHA-256 values, not shortened display hashes. Check input hashes before and after every stage; fail closed on drift.

Authoritative references relative to `experiments/drosophila-heresy/`:

- `q10-gc1-par8-v1/{PLAN.md,CONTRACT.json,PREEXECUTION.json,scripts/run_gc1.py,qualification/execution.json}`.
- `q10-gc0-gp1-par2-v1/qualification/palettes.jsonl` and its contract/status.
- `q10-gc1-pf0-v1/qualification/execution.json` and bound topology.
- `supervision/gc1-review-20260918/{AUDIT.md,REVIEWER_SUMMARY.md,verify_review.py,evidence.json,MANIFEST.json}`.

Keep these historical facts visible: 801 groups; 7,207 entries including 801 ZERO choices; one preserved palette shortfall; 323,648 evaluation calls. Four slice/tau endpoint files contribute 14 set cases, all from one seed. They are not independent replicates.

Before writing an executable contract, produce a workload inventory with exact case keys, group/candidate counts, mapping availability, unique saved weight hashes, raw-support incidence, legal replacement counts, and replay upper bounds. Do not infer stored beam history from aggregate traces. If only best-valid and final-beam best-search maps exist, report that scope.

## 4. Q10-GC1-D1: saved-state failure anatomy

### Scope and cohort

All 14 cases, each with baseline, target, selected best-valid, and saved best-search. Duplicate byte states may share computation, but preserve all case/state labels. No new endpoint choices or counterfactual states. Independent reconstruction of saved maps is permitted; no beam search.

### State and row outputs

For each state retain committed weight/readout hashes, canonical mapping, complete group selection, full global score, signed debts, final gate flags, support/bounds/boundary/reserve validity, and distinctness from baseline and target.

For each readout row record baseline/target/state bits, bitwise parity, ULP distance, signed numerical residual, baseline mismatch status, physical-support incidence, selected active groups, and selected coordinates/occurrence counts. Keep signed zero explicit: bitwise mismatch can coexist with zero arithmetic residual or zero numerical ULP distance under the inherited ordering.

Partition rows into four disjoint classes relative to baseline: wrong-to-exact, wrong-to-wrong, exact-to-wrong, exact-to-exact. Split wrong-to-wrong by ULP improvement/tie/worsening. Reconcile every case and the aggregate identity:

`final mismatches = baseline mismatches - repaired + newly damaged`.

The 118 damaged-row incidences are across cases, not necessarily 118 unique physical rows. Report both case incidence and any explicitly defined cross-case identity count.

### Signed geometry, with the correct reference

Let B be the repair-baseline weights, O the inherited geometry-origin weights (`state.base_weights`), T the target, a the stored acquisition-axis vector, and H the linear readout operator including repeated-coordinate multiplicities. Do not silently replace O with B or renormalize a.

For a committed state W retain:

- `qA = a dot (W - T)`.
- `qL = H(W - T)`, as the full signed row vector.
- `qN = norm(W - O) - norm(T - O)`.
- `qS = norm(W - O)^2 - norm(T - O)^2`, a diagnostic for decomposition.

Use the inherited target-based normalizers and 1e-12 floors. Report raw debts and gate-unit quantities separately. Gates remain axis <=2e-6, norm <=2e-7, and linear-drive L2 <=2e-6 after inherited normalization. No per-row substitute for the linear L2 gate.

At coordinate i, decompose axis by `a_i*(W_i-T_i)` and linear drive by the actual H multiplicity. For norm use squared terms, not an invented additive decomposition of norm itself.

For group contributions relative to B, verify disjoint coordinate ownership first. Preserve the baseline debt offset: group increments sum to state-minus-baseline debt, not automatically state-minus-target debt. With disjoint ownership, squared-norm increments sum exactly in ideal arithmetic; norm requires the final square root. If ownership overlaps, use explicit coordinate accounting and include cross terms where needed. Reconcile f64 summation against full inherited geometry; final checks always recompute the full state.

### Collateral and overlap

Report selected active-group degree for damaged, repaired, persistent-wrong, and initially exact undamaged rows. Compare denominators as well as counts: damage concentration on shared-support rows is uninformative without their exposure frequency. Keep group palette size, support size, and number of changed coordinates visible.

Support incidence does not identify cause. Do not label rows threshold-gated from endpoint bits or support alone. First-divergence accumulator traces or midpoint claims require a separate arithmetic replay protocol if not already available.

### New static check: geometry bucket resolution

PAR8 uses `round(debt*4096)` in exploration, where debt contains normalized signed axis/norm errors and an unsigned linear-error norm. Bucket width is approximately 2.4414e-4. Final-valid axis/linear debt is at most 2e-6 and norm debt at most 2e-7, so all final-valid states have geometry bucket `(0,0,0)` before active-group count is included.

This is a representation fact, not proof of lost repair opportunities. Record the actual guarded ranges and bucket assignments of saved states. Do not claim historical beam occupancy or diversity collapse across unretained candidates. A successor should qualify gate-unit bin resolution and preserve signed linear direction before claiming geometry diversity.

### Outputs and exit gate

Produce `STATE_ANATOMY`, `ROW_TRANSITIONS`, `SIGNED_GEOMETRY`, `GROUP_SUPPORT`, `BUCKET_RESOLUTION`, a reconciliation receipt, and a short interpretation. Use compact binary/columnar arrays for full row vectors if appropriate; include schema, ordering, dimensions and hashes.

Pass requires complete saved-map reconstruction, existing result reproduction, zero unexplained reconciliation differences, explicit missing-data fields, and stable parents. Missing historical data remains unavailable; it is never filled with zero. D1 ends without recommending a specific beam as proven necessary.

## 5. Q10-GC1-D1-R1: contextual removal replay

This is new counterfactual evidence, separate from D1. It answers the reviewer's group-attribution question without pretending support overlap is causality.

For every selected active group in each of the 28 labeled saved valid/search states, replace only that group's choice with ZERO, retaining all other choices. Materialize from baseline and replay the full endpoint. Deduplicate identical weight states but retain every intervention label. Upper bound is twice the 801 groups, before active-group filtering and deduplication; report the exact preflight count.

Record `g(W)-g(W_without_group)` row-wise, all score changes, reopened repairs, collateral repaired/created, and all geometry changes. An ablation need not pass final geometry to provide a diagnostic, but it cannot become a valid constructor output unless all gates pass.

Call these **leave-one-group-out contextual effects**. Do not sum them as an allocation of total effect; sequential-f32 interactions can make that sum wrong. A harmful group in one coalition may be useful elsewhere. No greedy deletion sequence is executed here.

Gate: each ablation has complete map semantics, exact replay, full legality checks, and unchanged parents. This can run beside cancellation after D1's state inventory is frozen.

## 6. Q10-GC1-CANCEL1: bounded palette replacement

### Cohort and intervention

All eight best-search states failing final geometry, selected by the audited flags before any new replay. Baseline comparison V is that case's historical best-valid output; S is its fixed invalid saved state. Do not update S after a successful replacement within this identity.

A move `(group, alternate palette identity)` replaces the group's existing choice. Include ZERO, activation of an inactive group, and replacement/deactivation of an active group. Prefixes remain relative to the original frozen B, not relative to S. A pair replaces two distinct groups simultaneously in S. Same-group alternatives cannot form a pair. Revalidate conflicts even though the parent reports zero coordinate overlap.

### Stage A: all single replacements

Enumerate every legal alternate choice for every group in each of the eight cases. Freeze exact counts before replay. There are at most 7,207 minus 801 = 6,406 alternatives across all 14 parent cases; this eight-case subset has no more. Deduplicate state bytes, retaining alias records.

Replay every resulting state with full final geometry. Record every score and gate, even for individually harmful moves. Do not filter by readout improvement, geometry improvement, or parent intermediate guards: this is endpoint-neighborhood diagnosis around an already invalid state, not a replay of beam admission. Hard support/bounds/reserve legality always applies.

### Stage B: a frozen, explicitly limited pair screen

Recommended first budget: at most 32 single-replacement records per case and all unordered, distinct-group pairs among them: at most 496 pairs/case, or 3,968 pairs across eight cases. This is a shortlisted pair domain, not complete two-group coverage.

Freeze selection before Stage A runs, using its measured records as declared inputs:

1. Up to 16 geometry-repair records, sorted by the maximum final gate ratio, then sum of gate excesses, then global Q.
2. Up to eight further collateral-repair records, sorted by newly damaged baseline-exact row count, then global Q, then gate excess.
3. Fill remaining slots to 32 by deterministic round-robin across distinct `(group, axis-change sign, linear-debt opposition sign)` buckets, with canonical identity ties. Consider all remaining legal records, including individually harmful ones. Empty/zero direction gets its own category.

Use full signed linear vector dot products to define opposition, not merely a smaller unsigned L2. Every tie ends in `(group id, candidate identity)`; deduplicate before fill. Freeze the precise bucket traversal and zero-sign convention in the executable contract. Preserve how many records/groups the shortlist excludes.

Commit both replacements simultaneously from S and replay. Do not add isolated readout effects. Do not demand that either constituent passes final geometry. Do not start another pair search around the winner.

### Outcomes

The principal constructive result is `VALID_ADVANTAGE_PRESERVED`: all final gates and hard legality pass, W differs from T and B, and `Q(W) < Q(V)` lexicographically. This avoids an undefined claim about retaining 'most' advantage. Report componentwise differences; a lexicographic tuple is not a scalar.

Also distinguish valid states tying/worsening V, invalid readout improvements, and exact alternate endpoints. For descriptive mismatch-gap retention use `(n(V)-n(W))/(n(V)-n(S))` only when the denominator is positive; report raw, unclipped values and all other score components. It is not a success gate.

If no single replacement succeeds after complete enumeration, the negative applies only to the one-group replacement domain around S. If no shortlisted pair succeeds, report `NO_VALID_ADVANTAGE_IN_SCREENED_PAIR_DOMAIN`. This does not rule out omitted pairs, three-group moves, another palette, or a different construction trajectory.

Preserve all results, not just first successes. Independently reconstruct any claimed exact or valid-advantage output. Construction remains development evidence on the same seed.

## 7. Runtime qualification before counterfactual execution

Create a new bounded replay runtime identity, Q10-GC1-RQ1. Do not patch sealed PAR8/AUDIT1 or rerun into their directories.

Required assertions and targeted qualification cases:

- Exactly one unique selection per expected group, including ZERO; complete canonical coordinate map; duplicate group/coordinate detection and conflict rejection.
- Baseline-relative legal prefixes and exact committed bytes; support, bounds, boundary membership, inherited reserve and unchanged outside support.
- Finite geometry; same frozen sequential-f32 order, negative-zero initialization and bitwise parity. No SIMD/reassociation/FMA change to the oracle.
- Exact status requires zero bitwise mismatch over every declared readout and W != T, plus every final validity gate. Record W != B separately and require it for a newly constructed alternative here.
- Partial status requires every final validity gate, W distinct from B/T, and strict baseline score improvement. No unconditional fallback success.
- Target-weight rediscovery, duplicate choices, missing groups, illegal reserve, signed-zero differences, no-improvement, and invalid-but-better fixtures must get the correct non-success status.
- Reconstruction order invariance, replacement vs prefix stacking, simultaneous pair semantics, and nonmonotonic intermediate cases.
- Count attempted evaluations, unique committed-state hashes, cache hits, conflicted/illegal maps, and completed full replays separately.
- Exclusive run-directory reservation, fail if output already exists, durable temporary receipt writing followed by atomic publication, terminal success marker only after finalized hashes. Interrupted runs remain explicitly incomplete; resumption needs frozen rules.
- Pin interpreter, dependencies, platform, parent and helper hashes. Any optimized cache/kernel must pass bytewise equivalence against the conservative oracle before use.

Use a fixed synthetic/previously exposed engineering fixture set to estimate replay throughput and peak memory before freezing workload caps. Stream rows, reuse buffers and avoid storing redundant full arrays per candidate. Do not sacrifice arithmetic semantics for speed. This plan does not authorize a Rust port; if later selected, use the workspace D: build-target convention and qualify exact parity first.

Cost gates: preflight exact count, declared wall-time/memory caps from the fixture benchmark, and fail-closed stop with completed-domain coverage on cap exhaustion. No unrecorded budget top-ups or new shortlist rules midrun. No speculative claim that pair replay is cheap.

## 8. Evidence-driven successor selection

| Diagnostic pattern | Next development option | Limit |
|---|---|---|
| Legal one/pair replacements recover valid advantage | GC1-GA1 geometry-complementarity policy | Local cancelability, not exact endpoint feasibility. |
| ZERO/removal or alternate choices repair collateral economically | GC1-CR1 collateral-aware assembly | Preserve reopened repairs and full global score. |
| Valid signed compensation exists but is poorly selected | Gate-unit/vector diversity qualification, then GA1 | Saved-state evidence alone cannot reconstruct lost historical beam states. |
| Current library alternatives make little headway | Palette coverage/expressivity diagnostic | Finite search failure still does not prove palette infeasibility. |
| Mixed pattern | Freeze a combined policy as an engineering candidate | Do not claim an isolated mechanism from a bundled change. |
| No clear pattern | Publish inconclusive diagnosis and remaining domains | Do not automatically spend a larger beam budget. |

GC1-GA1, if justified, should use paired execution against a qualified port of PAR8 on the same 14 cases. Keep palette, group order, horizon, oracle, final gates and total budget fixed. First compare beam retention/routing policy only; adding a post-hoc replacement phase is a separate factor or identity. Require the control to reproduce saved outputs or explain/requalify drift before comparison.

A possible treatment has readout, geometry, collateral and exploration lanes within the same maximum width 48. Lane counts and selection rules remain undecided until D1/CANCEL1 are reviewed; freeze before outcomes. Preserve full signed linear debt; a signed axis scalar plus unsigned linear norm is insufficient for complementary routing. Calibrate bin widths in gate units rather than inheriting `*4096`. Keep best-ever valid, best-ever search, and final-retained search distinct in receipts.

Budget equivalence must include additional ranking/replay overhead and actual calls, not just equal beam labels. Retain bounded nonmonotonic candidates and report paired wins/ties/losses, geometry validity, collateral, score components, unique states, time and memory. No independent-replicate statistics on these repeated seed9731 cases.

## 9. Deliverables, ownership and execution order

| Order | Identity / work | Deliverable and gate |
|---|---|---|
| 1 | D1 inventory/protocol | Exact sources, state coverage, row definitions, workload manifest frozen. |
| 2 | D1 saved-state audit | Signed anatomy, support associations, bucket resolution and reconciliations. |
| 3 | RQ1 qualification | Hardened fresh runtime, negative fixtures, oracle parity, cost measurements; reviewed before replay. |
| 4A | D1-R1 | Contextual removal evidence for saved coalitions. |
| 4B | CANCEL1 | Complete singles and bounded pair screen, exact domain coverage and reconstructions. |
| 5 | Joint interpretation | Choose one successor policy with explicit claim limits; do not loosen gates. |
| 6 | GA1 or another new constructor identity | Paired same-family engineering evaluation under sealed budget. |
| 7 | Independent exact-state audit | Only if an exact distinct alternative is found. |
| 8 | GC2 | Frozen constructor on fresh engineering states, no retuning. |
| 9 | AG1 then separate behavior protocol | Only after constructor qualification and an appropriate current-function matching contract. |

Suggested delegation for later authorized execution: Luna xhigh agent A owns D1 reports, agent B owns the new replay/qualification package, and agent C reviews predicates and counterfactual semantics read-only. After RQ1 passes, A/C may run disjoint R1/CANCEL scopes. The supervisor owns source binding, gate review and interpretation. No agent edits another identity or consumes scientific seeds.

An exact endpoint concerns the frozen readout panel only. AG1 must define useful-authority targets external to the matched pair: their mutual readout error is zero, so a helpful-authority spectrum relative to that zero error is undefined/trivial. Use a separately frozen probe perturbation/target battery shared by both states. All non-weight neural/plasticity states and future-probe coverage need explicit matching/control before any learning-trajectory claim.

## 10. Review disposition

The reviewer is right to propose diagnostic anatomy and signed cancellation before a larger constructor. The actionable next step is **D1 plus qualification of a bounded counterfactual runtime**, followed by distinct contextual-removal and replacement studies. Geometry-aware search is a candidate response to those results, not the preselected conclusion. No exact endpoint, adaptive-state difference, or behavioral result is claimed by this plan.
