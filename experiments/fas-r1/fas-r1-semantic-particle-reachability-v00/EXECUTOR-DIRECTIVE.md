# FAS-R1 executor directive v0.2

Status: `SEALED_FOR_STAGE0_CONSTRUCTION` under [Amendment 01 and seal receipt](R1-AMENDMENT-01-SEAL.md). Stage 0 construction is authorized. This seal does not certify construction readiness. It records no model contact, training, or evaluation; those remain unauthorized by this Stage 0 directive.

## 0. Identity, boundaries, and first stop

Create R1 as `fas-r1-semantic-particle-reachability-v00`. Keep its sources/contracts/fixtures/receipts separate from FAS-00, S05, Phoenix, and active experiments. The only proposed shared identity is the LFM model family and revision; reverify both under a later R1 manifest. Implement Stage 0 only in the first executor pass: an exact synthetic world and validator, symmetry checker, deterministic search scheduler with stub features/controller, operation ledger, timestamped trajectory schema, and construction receipts. Exercise `V_reach` and `Q_terminal` through stubs without loading an encoder. Prove full-trace prefix replay without a runtime cutoff signal. Stop at `R1_CONSTRUCTION_READY` after the Stage 0 gates below. This status does not mean model contact, sensor qualification, training, or evaluation occurred.

Follow the repository's `:G` build / `:C` link convention when a build is actually authorized. Use an isolated worktree or checkout, carrying only this R1 packet from the dirty source tree, and a dedicated target directory. Keep unrelated dirty/running work intact. Do not reuse or alter sealed FAS inputs, caches, fits, or evaluations. Preserve a failed attempt as a versioned attempt rather than overwriting its receipt.

## 1. Task and inference projections

Generate the symbolic task first. Render language afterward. A typed `task-v1` record contains:

```text
task_id, latent_family_id, generator_version, split, seed
N, K, entity_surface[N], role_surface[K]
constraints[]: {clause_id, kind, entity_ids[], role_ids[]}
renderings[]: {clause_id, template_family, paraphrase_id, text, entity_spans[], role_spans[]}
global_text, graph_density_band, count_status
raw_solution_count, canonical_solution_class_count
automorphism_group_id, solver_receipt_hash
```

Typed clause kinds for v1: `SAME(i,j)`, `DIFFERENT(i,j)`, `FIXED_ROLE(i,r)`, `FORBIDDEN_ROLE(i,r)`, `EXACTLY_ONE_ROLE(entity_ids,r)`, and `IMPLIES_NOT_ROLE(i,r,j,r2)`. Fix clause ordering/tie rules and validator truth tables in the contract. Reject contradictory/no-solution tasks unless a separate unsatisfiable stratum is deliberately added; the primary outcome assumes at least one valid assignment. Do not permit duplicate clauses to create an accidental shortcut.

The private record holds typed constraints, exact solution set, and solver/canonicalizer evidence. The **inference projection** contains only rendered text, public entity/role names and IDs, clause-to-name mention incidence, `N`, `K`, and frozen features. It never contains typed clause kinds/arguments, validator output, solution counts, a valid-solution list, oracle distances, or a per-task automorphism group derived from hidden constraints. Name incidence only maps visible strings to candidate slots; it does not expose the relation semantics.

Split latent task-isomorphism families before assigning lexical surfaces or paraphrases. A family, its renamings, and every rendering stay in one split. Keep ID train/validation/test, held-out template, held-out invented-vocabulary, held-out graph-density, held-out multiplicity, and unseen-size slices separate. Record generator seeds and exact split manifests.

### Solution counts and feasibility

Use an exact solver/model enumerator with a proof of exhaustion for accepted tasks. Proposed accepted cap: `4096` raw solutions; if enumeration exceeds the cap or times out, mark `COUNT_UNKNOWN` and exclude the task from exact-count strata and class-coverage denominators. Do not label capped counts as exact. The proposed exact canonical-class strata are `1`, `2–4`, `5–16`, `17+`; record raw solution counts as a second axis. Measure generation and solver acceptance at `N=6,8,10,12,14,16,20` before locking cohort sizes. All `N=20` claims require exact accepted counts, not an extrapolated count.

## 2. State machine and exact validity

Use a **complete** assignment `a_t: u8[N]`, with values `0..K-1`. A legal edit is `(entity_id:u16, new_role:u8)` that overwrites exactly one coordinate; mask no-ops. The initial assignment is a deterministic function of task ID and initialization seed and is identical across arms for a paired comparison. A transition consumes one expansion charge even if it revisits a state or is later merged. The recurrent controller state is `s_t: f32[128]` in the primary design; `256` is a preregistered sensitivity only.

Do not use the exact validator for an online stop, rejection, selection, or resampling decision. Every arm runs to its full allocated expansion budget. After the trace is closed, the validator labels each visited complete assignment. `R(B)` counts whether any valid assignment appeared through charged expansion `B`. For every arm, the same frozen `Q_terminal(a,H)` head scores each distinct visited assignment; `S(B)` is the success rate of selecting the highest-scored assignment under one fixed tie rule. `V_reach(X,b)` never selects the final answer. It estimates continuation under the frozen learned proposal and may guide allocation, resampling, or representative retention after assignment merges in learned-proposal arms. On `RANDOM-WIDTH`, it is off-policy and must not control edits or allocation; omit it or report it only as an explicitly off-policy diagnostic. Report the initial state separately, both included and excluded from reachability.

For source correctness, the exact validator evaluates the typed AST independently of the model. A solver result and direct validator must agree on every enumerated solution and every checked non-solution in Stage 0. The private solver never crosses the inference API.

## 3. Role symmetry and merging

Let `Aut(C)` be role permutations that preserve the **entire** typed constraint task, including role-specific clauses. Define `kappa_C(a) = lexicographic minimum of pi(a) for pi in Aut(C)`. Check idempotence and validity invariance for each admitted permutation.

The primary canonical-merge contrast uses a preregistered **role-anonymous subfamily** (constraints without fixed role references), for which the full `S_K` symmetry is public from the task grammar. This avoids supplying a hidden-AST-derived group only to the canonical arm. Role-specific tasks remain separate secondary strata; their permitted group must be either public to every arm or the canonical arm must be marked a privileged diagnostic. No role permutation may be inferred from the private solver and passed silently into inference.

`MERGED-WIDTH` uses equality of raw assignments `a`; `CANONICAL-MERGE` uses equality of `(task_id,kappa_C(a))`. Since `s_t` can differ for identical `a`, these are **assignment-level merge interventions**, not proofs of dynamic-state equivalence. Retain the representative with higher `V_reach` under a fixed tie rule, and merge ancestry counters. The duplicate-generating expansion remains charged; merging frees a live slot and can redirect only future unspent expansions. Add a strict full-state duplicate diagnostic using bit-identical `(a,s_t,remaining_budget,RNG state)` to measure how often genuinely identical dynamic states occur. Log the `V_reach` and latent divergence of assignment-merged particles. Do not claim exact dynamic equivalence unless a later architecture establishes it.

## 4. Frozen semantic input and controller

Proposed LFM identity: `LiquidAI/LFM2.5-1.2B-Base@7453bca97ca1e67754c4035a4b4c584e1c9dd725`. The prior FAS execution plan expected hidden dimension `d_h=2048`; R1 verifies this live before encoding. R1 needs a new `R1_FEATURE_V1` contract: encode each rendered constraint independently as `H: f32[M,d_h]`, with `constraint_mask: bool[M]`, and the complete rendered problem as `h_global: f32[d_h]`. Proposed initial extraction is final hidden-layer arithmetic mean over model-visible tokens, float32 output, no padding or truncation, one example per call, eval mode, gradients off. Pin exact input strings, tokenizer revision/file hashes, model file hashes, token IDs, dtype, pooling, feature shape, and repeat hashes before any feature-based training. A different layer/pooling choice needs a versioned amendment, not an in-run search.

The controller receives `H`, `h_global`, `a`, `s`, remaining budget, and visible name-incidence masks. Proposed shape:

```text
H [M,2048] -> shared linear + norm -> C [M,128]
h_global [2048] -> linear + norm -> g [128]
assignment one-hot [N,K]
entity/role name-incidence masks [M,N], [M,K]
shared entity/role scoring + recurrent GRU state s [128]
proposal logits [N,K], masked on no-op edits
planning head V_reach(a,s,H,b_remaining) scalar in [0,1]
terminal head Q_terminal(a,H) scalar in [0,1]
```

Use shared scorers and masks so `N`, `K`, and `M` vary without a fixed-size output head. Do not feed private typed constraints or solution labels to inference. The exact encoder projection and model architecture must be the same for every learned arm and fixed before evaluation. The LFM has `Δθ=0` throughout.

Before proposal fitting, qualify the frozen features hierarchically on predeclared held-out render families:

1. **Semantic identity:** balanced clause-kind accuracy ≥`0.90`.
2. **Binding:** entity/role binding F1 ≥`0.90`.
3. **Action relevance:** predict `sign(ΔC(a,e)) ∈ {-1,0,+1}`, where `ΔC` is the change in satisfied-constraint count after edit `e`; require held-out macro-F1 ≥`0.90` and at least `100` labeled examples per class drawn across at least `20` held-out task-isomorphism families.

The action-relevance diagnostic receives only `H`, `h_global`, `a`, `e`, and public incidence, exactly the semantic/action inputs available to the controller for this probe. The private typed validator supplies labels offline. It receives no AST, solution set, solver status, or hidden automorphism metadata. Keep name-incidence-only and template-only shortcut controls, freeze probe support/thresholds before extraction, and stop the LFM-backed claim if any stage fails (`R1_SENSOR_FAIL`). A stub/symbolic Stage 0 can still validate interfaces without model contact, but it cannot pass sensor qualification.

## 5. Privileged training targets

For each training task, let `Y` be its exact valid assignments and `C=Y/Aut(C)` its valid equivalence classes. For complete assignment `a`, define `d_c(a)` as the minimum Hamming edit distance to any member of class `c`. For edit `e` producing `a_e`, define:

`G(e|a) = (1/|C|) * sum_{c in C} 1[d_c(a_e) < d_c(a)]`.

Name `q(e|a) ∝ G(e|a)` the **class-balanced one-step reachability teacher**. It rewards edits that improve access to multiple valid classes; it is not an optimal-edit target and need not minimize distance to the nearest solution. For invalid training states, normalize `G` over legal edits when its sum is positive; skip proposal loss for zero-mass states and record their count. Keep one proposal loss, `KL(q||p_phi)` or its exact cross-entropy equivalent, and do not choose one arbitrary target class.

Store training-only `n_improved_classes(e,a) = sum_c 1[d_c(a_e) < d_c(a)]` and `Δd_min = min_c d_c(a_e) - min_c d_c(a)` for each candidate edit used to construct the teacher. This telemetry distinguishes broad class coverage from nearest-solution greediness; it adds no loss and is never exposed at inference. Sample training states across distance-to-solution bands, from both random edits and the current learned policy; private solver labels are permitted only in training.

Freeze the proposal before value-head training. Train `V_reach(a,s,H,b)` on success-within-`b` labels from seeded rollouts that continue an individual state under the frozen learned proposal without particle resampling. This estimates proposal-conditioned continuation reachability, not exact logical feasibility or the full success probability of a multi-particle scheduler. It may rank learned-proposal particles for allocation/resampling, but it does not select the returned assignment.

Train `Q_terminal(a,H)` separately from private validator labels on a fixed mixture of assignments sampled from training worlds and training-policy traces. It predicts validity of an already visited assignment, has no `s` or remaining-budget input, and is the common final selector for every arm. Freeze both value heads before evaluation. Calibrate `V_reach` on policy-conditioned continuation rollouts and `Q_terminal` on held-out assignments using Brier score and reliability bins. No head or selector is tuned on evaluation traces.

Proposed development schedule after later model/sensor gates: `20,000` exact-count training worlds, `2,000` validation worlds, `2,000` ID evaluation worlds, three independent training seeds, at most `16` sampled training states per training world, proposal training for at most `20` epochs with early stopping on validation KL, then `128,000` fixed-policy `V_reach` continuation rollouts. Train `Q_terminal` separately on private validity labels from a declared training-assignment mixture and freeze both heads before evaluation. These are feasibility defaults, not frozen counts. Stage 0 measures only model-free generation/solver/scheduler costs; change counts only via a versioned amendment before protected evaluation.

## 6. Arms and budget allocation

All arms use the same frozen `Q_terminal` selector, task inputs, initialization policy, and paired task/RNG seeds. Learned-proposal arms share the same frozen proposal and `V_reach` parameters. Use the budget set `B ∈ {64,128,256,512,1024}`. For fixed-width arms use `W ∈ {1,2,4,8,16,32}` with nominal `D=floor(B/W)` and a predeclared remainder assignment. `PARTICLE` has a maximum live width `W` and an adaptive depth distribution; record actual depth per particle. Only learned-proposal allocation, resampling, and merge representative retention may use `V_reach`; `RANDOM-WIDTH` uses uniform edits and never consults it.

| Arm | Transition and allocation rule |
| --- | --- |
| `DEPTH` | One trajectory, greedy learned proposal, `B` charged expansions. |
| `SAMPLED-DEPTH` | One trajectory, learned sampled proposal; controls for stochasticity. This is `LEARNED-WIDTH` at `W=1`. |
| `RANDOM-WIDTH` | `W` trajectories, uniform legal edits; no learned proposal or `V_reach` allocation. |
| `LEARNED-WIDTH` | `W` independent trajectories sampled from learned proposal, no merge. |
| `MERGED-WIDTH` | Learned width with raw-assignment merge and deterministic expansion recycling. |
| `CANONICAL-MERGE` | Learned width with the public/task-legal canonical assignment key. |
| `PARTICLE` | Canonical merge plus fixed-period `V_reach` resampling and value-guided allocation, with a nonzero minimum allocation per live particle. |

After every arm's trace is closed, apply the same frozen `Q_terminal(a,H)` scoring and tie rule to its distinct visited assignments. This is the only model selector for `S(B)`.

`ORACLE-SELECT` is calculated post-hoc over each arm's **same trace** and equals that trace's `R(B)`. `ORACLE-PROPOSAL` may use the private teacher at inference for a diagnostic ceiling; its solver overhead and privilege are reported separately, and it is excluded from the advancement comparison. Publish all temperature, value tie, merge tie, resampling interval, RNG counter, and budget remainder rules before a run.

## 7. Compute ledger and result surface

For every arm/task, record proposal calls and logits scored, `V_reach` and `Q_terminal` calls separately, encoder forward calls/tokens, branch spawns, canonicalization calls/group size, hashes/probes, merges, recycled future expansions, resampling operations, CPU/GPU active nanoseconds, monotonic end-to-end nanoseconds, peak resident/device bytes, and trace bytes. Charge every proposal, value evaluation, edit/transition, and post-trace terminal-selector evaluation even when its child is discarded or merged. Charge common LFM encoding once per task. A cached-feature result remains secondary and labeled.

Report `R(B)` at matched charged expansions, `R(C_active)` at matched cumulative active resource time, and `R(C_wall)` at matched monotonic wall time on a named pinned host. `C_active` is the cumulative sum of CPU-active plus GPU-active nanoseconds; publish both components and the combined curve. `C_wall` starts at request dispatch and uses monotonic operation completion times. Timestamp operation starts/completions and the cumulative active-time counter in each full trace. Run every arm to its complete prescribed maximum; after all traces finish, derive each time curve by prefix-truncating completed events on a cutoff grid selected from development/runtime feasibility and frozen before protected evaluation. The scheduler never receives the cutoff or a time-stop signal. An assignment enters a reachability prefix when the charged expansion that produces it completes before the cutoff; count initial assignments separately at time zero and report curves both including and excluding them. `Q_terminal` finalization costs are included in end-to-end resource/latency totals and in `S(B)` reporting, while post-hoc validator and offline-analysis costs remain outside inference.

Include the full `B × W × N × canonical-solution-class` surface and actual per-particle depth distribution. The user-facing “under matched compute” claim requires the predeclared expansion, active-time, and wall-time comparisons to be reported together. Batched width may improve active compute and worsen latency, or the reverse; report both. Keep oracle validation and offline analysis time outside inference cost, with their own accounting.

Primary cell proposal: `B=256`, `W_max=8`, held-out `N=12`, `5–16` canonical valid classes; predesignated unseen size `N=14`. The proposed advancement rule and its caveat are in [DESIGN-AUDIT.md](DESIGN-AUDIT.md). All seed predicates must be computed **jointly within each training seed** before counting how many seeds pass.

## 8. Trajectory and analysis contracts

Save every transition, including failed/merged/resampled branches. A versioned JSONL event holds:

```text
run/task/split/arm/training_seed/action_seed
global_expansion_index, particle_id, parent_id, ancestry_id, particle_depth
assignment_before, assignment_after, canonical_key
latent_state_before, latent_state_after (or lossless sidecar offsets + hashes)
edit, log_probability, v_reach, remaining_budget
operation_start/end, cumulative_cpu_active, cumulative_gpu_active, monotonic_completion_time
resampled, raw_merge, canonical_merge, representative_id
proposal/v_reach/encoder/canonicalizer costs, RNG counter
posthoc_valid, posthoc_first_hit
```

For each training-only teacher candidate, separately log `n_improved_classes` and `Δd_min`; these privileged fields never enter inference traces or model inputs.

After the search trace closes, a terminal-selection sidecar records each distinct visited assignment, its `Q_terminal` score, whether it was selected, selector operation timestamps/costs, and the tie rule. Score each distinct assignment once per arm/task because `Q_terminal` does not depend on latent history or remaining budget. These post-trace selector records are part of the complete inference trace and cost ledger; validator labels remain in a separate post-hoc sidecar.

The `posthoc_*` validity/first-hit fields are joined into a separate analysis sidecar **after** the online trace is closed; they are never visible to search. The latent-state sidecar may be compressed, but it must remain lossless and replayable; hashes alone are insufficient. Bind sidecar offsets and trajectory files in the run manifest. Compute first-hit expansion/active-time/wall-time, raw and canonical unique counts, duplicate rate, future expansions redirected after merging, ancestry entropy, branch survival, pairwise assignment diversity, distinct reached valid classes, exact class coverage only when the denominator is exact, `V_reach` policy calibration, `Q_terminal` calibration, terminal selection regret, throughput, latency, and memory per live particle. Report `R(B)`, `S(B)`, and their paired difference by task, seed, size, and solution-class stratum. Use paired task/bootstrap intervals as annotations, not new pass gates.

Only after the primary run is locked, replay fixed trained weights and task/RNG seeds with one mechanism disabled at a time: width, learned sampling, raw merge, canonical merge, value resampling, selection, depth cap, and branch cap. These lesions are diagnostic; they do not license tuning against the held-out set.

## 9. Stage 0 construction gate and stop boundary

The first executor pass can implement and inspect without LFM/model contact:

1. Independent typed-constraint validator and exact solver/enumerator agree on exhaustive tiny tasks and accepted generated tasks; every accepted count has exhaustion proof/status.
2. Seeded generation produces stable task IDs and identical bytes on a second construction run. Proposed smoke: `96` accepted worlds spanning both role-anonymous and role-specific families, all proposed multiplicity strata, and `N≤6,K≤3` exhaustive checks where feasible.
3. The legal symmetry group is verified against the typed AST; `kappa` is deterministic/idempotent and preserves validity. Role-specific constraints show the expected symmetry reductions.
4. The inference projection cannot access private AST, `Y`, solver status, oracle distances, or hidden automorphism metadata.
5. A stub encoder/controller drives every non-oracle arm through the same deterministic scheduler and complete replay trace. Exercise separate stub `V_reach` planning and `Q_terminal` selection interfaces. Every expansion, future recycled slot, common terminal score, and charged operation balances in the ledger.
6. Every charged operation has start/completion timestamps sufficient to reconstruct active-time and wall-time prefixes from the completed trace without a scheduler time-stop signal.
7. Source/fixture/contract hashes, environment, host, command, and failures are recorded in a versioned construction receipt.

Stop at `R1_CONSTRUCTION_READY` or a specific construction failure. Stage 0 is strictly model-free: no model/tokenizer access, feature extraction, sensor probing, proposal/value fitting, or protected evaluation. Action-relevance qualification belongs to the later sensor gate and uses private validator labels only offline. Later model contact, fitting, and evaluation require their own R1-specific authority and manifests. No FAS-00 closure status can be promoted or superseded by an R1 construction receipt.
