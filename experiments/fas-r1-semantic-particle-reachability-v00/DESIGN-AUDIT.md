# FAS-R1 design audit v0.1

Status: `DRAFT_FOR_REVIEW`. This audit changes the interpretation of several proposed comparisons. It is not a result or a frozen analysis plan.

## Claim and estimands

The core outcome is per-task **oracle reachability**:

`R(B) = P(any complete assignment visited by budget B satisfies the exact task constraints)`.

Selection is separately scored as `S(B) = P(the model-selected visited assignment is valid)`. `R(B) - S(B)` is selection loss. The exact validator is an offline labeler and evaluator; it is unavailable to the inference controller, selector, merger, and resampler.

`ORACLE-SELECT` is the post-hoc ceiling on a fixed generated trace and equals its `R(B)` by definition. It is not an independently generated search arm. `ORACLE-PROPOSAL` uses privileged solutions and is a separately marked diagnostic ceiling.

## Corrections required before a scientific run

| Priority | Seam | Required resolution |
| --- | --- | --- |
| P0 | State/action semantics | Freeze whether assignments are complete or partial, the initial state, edit/no-op rule, terminal and selection rules, and treatment of revisits. With monotone partial assignments, useful depth is at most `N`, so a `B=1024` depth baseline may merely be saturated. The directive proposes complete assignments with single-coordinate overwrite edits and no online validity signal. |
| P0 | Exact state equivalence | The proposed state is `(a,s)`. Equal assignments can have different latent histories and future transitions. Exact equality of `a`, or of its symmetry canonical form, is **assignment equivalence**, not exact dynamic-state equivalence. Keep a strict full-state-identity diagnostic; label assignment merging as a deliberate heuristic intervention unless the controller is redesigned to be history-free/equivariant. |
| P0 | Symmetry legality | A role permutation is admissible only if it preserves the entire typed constraint task, including explicit role references. Canonicalization under all `K!` permutations would merge different solutions on tasks with named-role constraints. Validate `V(a)=V(pi(a))` for every admitted permutation, and include the task identity in every merge key. |
| P0 | Symmetry information at inference | Computing a task-specific automorphism group from the private typed AST would give `CANONICAL-MERGE` extra semantic information. Make the primary canonical contrast use a role-anonymous grammar where `S_K` is public by design. If role-specific tasks use a group inferred from hidden constraints, label that result privileged and keep it out of the main claim. |
| P0 | Matched compute | Equal edit/transition counts do not imply equal inference cost. Charge every proposal and value evaluation, branch spawn, hash/canonicalization, merge, resampling, and common encoder pass. Report both transition-matched and measured end-to-end time-matched reachability on one pinned machine. Reserve the phrase “under matched compute” for the latter confirmation. |
| P0 | Recycled budget | A duplicate child has already spent its proposal/transition cost. Merging can free a live slot and redirect **future unspent** expansions; it cannot refund the transition that found the duplicate. Ledger both quantities separately. |
| P0 | Privileged teacher | With unrestricted reassignment and an unbounded future, almost every edit “preserves reachability.” Define a finite-budget teacher target. The directive proposes solver-derived distance reduction toward **all** valid solution classes, with no solver query at inference. |
| P0 | Split leakage | Split latent typed tasks and task-isomorphism families before generating names, templates, paraphrases, and clause order. No alternate rendering or role/entity renaming of an evaluation task may enter training. |
| P1 | Multiplicity | Raw `|Y|` can be inflated by symmetric role labels. Stratify primarily by the number of valid equivalence classes under each task's admissible symmetry group, and report raw counts too. Correct the supplied `2!-!4` notation to `2–4`. |
| P1 | Solver feasibility | `K^N` enumeration is not a credible plan at `N=20`. Use an exact constraint solver with bounded model enumeration. Accept a task into an exact-count stratum only when exhaustion is proven; reject timeout/capped cases from exact denominator metrics. Do not silently treat a lower bound as `|Y|`. |
| P1 | Width versus sampling | A deterministic depth path versus stochastic width confounds topology and sampling. Include a learned sampled `W=1` path using the same proposal and budget. Pair task and random-stream seeds across arms. |
| P1 | Fixed policy across arms | Freeze one proposal/value model before evaluation; no per-arm training or held-out tuning. `PARTICLE` may allocate uneven depths, so report actual per-particle depth rather than pretending every arm has `D=B/W`. |
| P1 | Extrapolation | Action scoring must operate on variable `N`, `K`, and clause counts with masks/shared parameters. A fixed `[12,K]` output layer cannot support the proposed `N=14,16,20` generalization claim. |
| P1 | First-hit versus selection | Continue the trace through the prescribed budget even after an offline-valid state appears. Otherwise the controller would indirectly gain an oracle stop signal and selection loss could not be measured consistently. |

## Primary comparison to freeze

Proposed primary cell: `B=256`, maximum live width `W=8`, paired tasks at held-out `N=12` and solution-class stratum `5–16`. The direct contrast is `PARTICLE` versus `DEPTH`; `RANDOM-WIDTH` and sampled `W=1` test the branching and stochasticity explanations. A predesignated unseen-size cell at `N=14` tests persistence. All other `B × W × N × multiplicity` cells form the reported surface, without choosing a winner after inspection.

The practical margin is proposed as `+0.05` absolute reachability for `PARTICLE` over each relevant baseline in the predesignated hard stratum, with direction preserved in at least two of three independent training seeds and at the unseen size. This is an **engineering advancement proposal**, not a significance test. Freeze or amend it before any protected evaluation. Paired intervals describe uncertainty and do not create an extra gate.

The advancement claim additionally requires `R(B)` to improve, acceptable selection loss, and a measured compute curve showing that canonicalization/resampling overhead does not erase the advantage. If the sensor qualification fails, report sensor failure; do not interpret a search comparison as evidence against organized width.

## Containment and provenance

The live [FAS-00 closure](../fas-frozen-adaptive-substrate-v00/closure-v01/FAS00-CLOSURE.md) records `SENSOR_FAIL_NO_SIGNAL`, denies FAS Phase 4/5 authorization, and requires a new identity for subsequent sensor work. Its [protocol](../fas-frozen-adaptive-substrate-v00/FAS-00-PROTOCOL.md) names the model family/revision as the only intended shared identity. Those documents do not authorize R1 to use FAS feature caches or run model inference.

The [GRAM paper](https://arxiv.org/abs/2605.19376) describes stochastic multi-trajectory recursive computation. R1's exact/assignment merging and resampling are new interventions in this packet; no GRAM reproduction claim is made.
