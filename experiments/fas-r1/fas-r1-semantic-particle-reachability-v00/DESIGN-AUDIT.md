# FAS-R1 design audit v0.1

Status: `SEALED_FOR_STAGE0_CONSTRUCTION` under [Amendment 01 and seal receipt](R1-AMENDMENT-01-SEAL.md). Stage 0 construction is authorized; this audit does not record construction, model contact, training, or evaluation as complete.

## Claim and estimands

The primary fixed-expansion outcome is per-task **oracle reachability**:

`R(B) = P(any complete assignment visited by charged expansion budget B satisfies the exact task constraints)`.

Keep planning and terminal recognition as separate quantities:

- `V_reach(X,b) = P(a valid assignment is reached within b further expansions | X, frozen learned proposal π_learned)`. This proposal-conditioned continuation estimate is used for learned-proposal allocation/resampling, including retaining a representative after assignment merges. It is not a general value across policies and does not choose the final answer.
- `Q_terminal(a,H) = P(a is valid | assignment a, visible frozen features H)`. Train it from private validator labels, freeze it before evaluation, and use the same head and deterministic tie rule to select among distinct assignments visited by every arm.

`S(B) = P(argmax over visited a of Q_terminal(a,H) is valid)` is the common-selector success rate. `R(B)-S(B)` is the terminal-recognition loss on the same trace; it no longer uses `V_reach` as a final selector. Report proposal/search reachability, allocation behavior, and terminal recognition separately. The exact validator is post-hoc only and is unavailable to the controller, selector, merger, or resampler.

`ORACLE-SELECT` is the post-hoc ceiling on a fixed generated trace and equals its `R(B)` by definition. It is not an independently generated search arm. `ORACLE-PROPOSAL` uses privileged solutions and is a separately marked diagnostic ceiling.

For measured-time reachability, complete each arm's prescribed maximum trace and timestamp every charged inference operation. Define `R(C_active)` and `R(C_wall)` by post-hoc prefix truncation of those traces: a newly produced assignment enters the prefix when its charged expansion completes before the cutoff. `C_active` is cumulative CPU plus GPU active resource time, with each reported separately; `C_wall` is monotonic elapsed time from request dispatch. Choose the cutoff grid from development/runtime feasibility and freeze it before protected evaluation. The scheduler receives no time cutoff or early-stop signal, so one complete trace supports every frozen cutoff.

## Sensor qualification hierarchy

Before fitting a proposal, qualify the frozen representation in order: (1) semantic identity, (2) entity/role binding, then (3) action relevance. The action-relevance diagnostic predicts `sign(ΔC)` for an edit, where `ΔC` is the change in the number of satisfied constraints. It receives only `H`, `h_global`, current assignment `a`, proposed edit `e`, and public incidence. The private typed validator supplies labels offline. If semantic identity or binding passes but action relevance fails, stop the LFM-backed search claim at sensor qualification.

## Corrections required before a scientific run

| Priority | Seam | Required resolution |
| --- | --- | --- |
| P0 | State/action semantics | Freeze whether assignments are complete or partial, the initial state, edit/no-op rule, terminal and selection rules, and treatment of revisits. With monotone partial assignments, useful depth is at most `N`, so a `B=1024` depth baseline may merely be saturated. The directive proposes complete assignments with single-coordinate overwrite edits and no online validity signal. |
| P0 | Exact state equivalence | The proposed state is `(a,s)`. Equal assignments can have different latent histories and future transitions. Exact equality of `a`, or of its symmetry canonical form, is **assignment equivalence**, not exact dynamic-state equivalence. Keep a strict full-state-identity diagnostic; label assignment merging as a deliberate heuristic intervention unless the controller is redesigned to be history-free/equivariant. |
| P0 | Symmetry legality | A role permutation is admissible only if it preserves the entire typed constraint task, including explicit role references. Canonicalization under all `K!` permutations would merge different solutions on tasks with named-role constraints. Validate `V(a)=V(pi(a))` for every admitted permutation, and include the task identity in every merge key. |
| P0 | Symmetry information at inference | Computing a task-specific automorphism group from the private typed AST would give `CANONICAL-MERGE` extra semantic information. Make the primary canonical contrast use a role-anonymous grammar where `S_K` is public by design. If role-specific tasks use a group inferred from hidden constraints, label that result privileged and keep it out of the main claim. |
| P0 | Matched compute | Equal edit/transition counts do not imply equal inference cost. Charge proposals, both value heads, branch spawn, hashes/canonicalization, merge, resampling, common encoding, and terminal selection. Run each arm to its full prescribed maximum and timestamp each operation. Derive `R(C_active)` and `R(C_wall)` by prefix-truncating completed traces on a cutoff grid frozen before protected evaluation; do not send a time-stop signal to the scheduler. Report CPU/GPU active time and wall time separately. Reserve “under matched compute” for measured-cost comparisons. |
| P0 | Value semantics | `V_reach(X,b)` is a proposal-conditioned continuation reach estimate used for learned-proposal allocation/resampling and assignment-merge representative retention. `Q_terminal(a,H)` is a separate common selector over visited assignments, trained from private validity labels and frozen before evaluation. Use the same `Q_terminal` selector across all arms. Do not interpret `R(B)-S(B)` through an off-policy continuation-value head. |
| P0 | Recycled budget | A duplicate child has already spent its proposal/transition cost. Merging can free a live slot and redirect **future unspent** expansions; it cannot refund the transition that found the duplicate. Ledger both quantities separately. |
| P0 | Privileged teacher | Name `q(e|a) ∝ G(e|a)` the **class-balanced one-step reachability teacher**, not an optimal-edit teacher. `G` rewards edits that reduce distance to multiple valid classes and can disagree with nearest-solution progress. Record training-only `n_improved_classes(e,a)` and `Δd_min`; add no second loss and expose neither telemetry nor private labels at inference. |
| P0 | Split leakage | Split latent typed tasks and task-isomorphism families before generating names, templates, paraphrases, and clause order. No alternate rendering or role/entity renaming of an evaluation task may enter training. |
| P1 | Multiplicity | Raw `|Y|` can be inflated by symmetric role labels. Stratify primarily by the number of valid equivalence classes under each task's admissible symmetry group, and report raw counts too. Correct the supplied `2!-!4` notation to `2–4`. |
| P1 | Solver feasibility | `K^N` enumeration is not a credible plan at `N=20`. Use an exact constraint solver with bounded model enumeration. Accept a task into an exact-count stratum only when exhaustion is proven; reject timeout/capped cases from exact denominator metrics. Do not silently treat a lower bound as `|Y|`. |
| P1 | Width versus sampling | A deterministic depth path versus stochastic width confounds topology and sampling. Include a learned sampled `W=1` path using the same proposal and budget. Pair task and random-stream seeds across arms. |
| P1 | Fixed policy across arms | Freeze one proposal, `V_reach`, and `Q_terminal` before evaluation; no per-arm training or held-out tuning. `PARTICLE` may allocate uneven depths, so report actual per-particle depth rather than pretending every arm has `D=B/W`. |
| P1 | Extrapolation | Action scoring must operate on variable `N`, `K`, and clause counts with masks/shared parameters. A fixed `[12,K]` output layer cannot support the proposed `N=14,16,20` generalization claim. |
| P1 | First-hit versus selection | Continue the trace through the prescribed budget even after an offline-valid state appears. Otherwise the controller would indirectly gain an oracle stop signal and the terminal-recognition gap on a fixed trace would not be measured consistently. |

## Primary comparison to freeze

Proposed primary cell: `B=256`, maximum live width `W=8`, paired tasks at held-out `N=12` and solution-class stratum `5–16`. The direct contrast is `PARTICLE` versus `DEPTH`; `RANDOM-WIDTH` and sampled `W=1` test the branching and stochasticity explanations. A predesignated unseen-size cell at `N=14` tests persistence. All other `B × W × N × multiplicity` cells form the reported surface, without choosing a winner after inspection.

The practical margin is proposed as `+0.05` absolute reachability for `PARTICLE` over each relevant baseline in the predesignated hard stratum, with direction preserved in at least two of three independent training seeds and at the unseen size. This is an **engineering advancement proposal**, not a significance test. Freeze or amend it before any protected evaluation. Paired intervals describe uncertainty and do not create an extra gate.

The advancement claim additionally requires `R(B)` to improve and measured active-time and wall-time curves to show whether canonicalization/resampling overhead changes the result. Report `S(B)` and terminal-recognition accuracy separately; `R(B)-S(B)` is the miss rate of the frozen common selector on states the trace actually reached. If any stage of sensor qualification fails, report sensor failure and do not interpret a search comparison as evidence against organized width.

## Containment and provenance

The live FAS-00 closure at original-checkout provenance `C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\closure-v01\FAS00-CLOSURE.md` records `SENSOR_FAIL_NO_SIGNAL`, denies FAS Phase 4/5 authorization, and requires a new identity for subsequent sensor work. Its protocol at `C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\FAS-00-PROTOCOL.md` names the model family/revision as the only intended shared identity. Those documents do not authorize R1 to use FAS feature caches or run model inference.

The [GRAM paper](https://arxiv.org/abs/2605.19376) describes stochastic multi-trajectory recursive computation. R1's exact/assignment merging and resampling are new interventions in this packet; no GRAM reproduction claim is made.
