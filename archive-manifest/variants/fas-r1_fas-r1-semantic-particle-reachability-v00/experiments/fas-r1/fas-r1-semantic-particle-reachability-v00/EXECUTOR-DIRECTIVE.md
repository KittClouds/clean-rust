# FAS-R1 executor directive v0.1

Status: `DRAFT_FOR_REVIEW`. This is an implementation directive for a future executor, with proposed numerical defaults. The authorized work in the present packet is the audit, seam inventory, and directive itself. No model contact, fitting, or protected evaluation follows from this document.

## 0. Identity, boundaries, and first stop

Create R1 as `fas-r1-semantic-particle-reachability-v00`. Keep its sources/contracts/fixtures/receipts separate from FAS-00, S05, Phoenix, and active experiments. The only proposed shared identity is the LFM model family and revision; reverify both under an R1 manifest. Implement Stage 0 only in the first executor pass: an exact synthetic world and validator, symmetry checker, deterministic search scheduler with stub features/controller, operation ledger, trajectory schema, and construction receipts. Stop at `R1_CONSTRUCTION_READY` after the Stage 0 gates below. This status does not mean model contact, sensor qualification, training, or evaluation occurred.

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

Do not use the exact validator for an online stop, rejection, selection, or resampling decision. Every arm runs to its allocated budget. After the trace is fixed, the validator labels each visited complete assignment. `R(B)` counts any valid assignment encountered through charged expansion `B`; `S(B)` labels the model-selected visited assignment at `B`. Keep the initial state in the visited set and report whether it was already valid; report reachability both including and excluding those trivial starts.

For source correctness, the exact validator evaluates the typed AST independently of the model. A solver result and direct validator must agree on every enumerated solution and every checked non-solution in Stage 0. The private solver never crosses the inference API.

## 3. Role symmetry and merging

Let `Aut(C)` be role permutations that preserve the **entire** typed constraint task, including role-specific clauses. Define `kappa_C(a) = lexicographic minimum of pi(a) for pi in Aut(C)`. Check idempotence and validity invariance for each admitted permutation.

The primary canonical-merge contrast uses a preregistered **role-anonymous subfamily** (constraints without fixed role references), for which the full `S_K` symmetry is public from the task grammar. This avoids supplying a hidden-AST-derived group only to the canonical arm. Role-specific tasks remain separate secondary strata; their permitted group must be either public to every arm or the canonical arm must be marked a privileged diagnostic. No role permutation may be inferred from the private solver and passed silently into inference.

`MERGED-WIDTH` uses equality of raw assignments `a`; `CANONICAL-MERGE` uses equality of `(task_id,kappa_C(a))`. Since `s_t` can differ for identical `a`, these are **assignment-level merge interventions**, not proofs of dynamic-state equivalence. Retain the representative by fixed value/tie rules and merge ancestry counters. The duplicate-generating expansion remains charged; merging frees a live slot and can redirect only future unspent expansions. Add a strict full-state duplicate diagnostic using bit-identical `(a,s_t,remaining_budget,RNG state)` to measure how often genuinely identical dynamic states occur. Log the value/latent divergence of assignment-merged particles. Do not claim exact dynamic equivalence unless a later architecture establishes it.

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
value V(a,s,H,b_remaining) scalar in [0,1]
```

Use shared scorers and masks so `N`, `K`, and `M` vary without a fixed-size output head. Do not feed private typed constraints or solution labels to inference. The exact encoder projection and model architecture must be the same for every learned arm and fixed before evaluation. The LFM has `Δθ=0` throughout.

Before proposal fitting, qualify that the frozen features carry usable clause semantics and entity/role binding across held-out lexical/template surfaces. Proposed qualification probes: balanced clause-kind accuracy ≥`0.90` and binding F1 ≥`0.90` on predeclared held-out render families, with a name-incidence-only and template-only shortcut control. Freeze the metrics/support thresholds before extraction. If qualification fails, record `R1_SENSOR_FAIL`; a stub/symbolic engineering run can continue for mechanism debugging but cannot support the LFM-backed reachability claim.

## 5. Privileged training targets

For each training task, let `Y` be its exact valid assignments and `C=Y/Aut(C)` its valid equivalence classes. For complete assignment `a`, define `d_c(a)` as the minimum Hamming edit distance to any member of class `c`. For edit `e` producing `a_e`, define a class-balanced improvement score:

`G(e|a) = (1/|C|) * sum_{c in C} 1[d_c(a_e) < d_c(a)]`.

Train only on invalid states and set `q(e|a) = G(e|a) / sum_{legal e'} G(e'|a)` when the denominator is positive. This gives every valid class a defined opportunity to contribute and excludes merely reversible edits that do not move closer to a solution. Record the exact teacher rule and target entropy. Sample training states across distance-to-solution bands, with states from both random edits and the current learned policy; training-only solver labels are permitted. Use `KL(q||p_phi)` or its exact cross-entropy equivalent as the proposal objective. No arbitrary single target is selected.

Freeze the proposal before value training. Train `V_psi(a,s,H,b)` on **policy-conditioned** success-within-`b` labels from seeded rollouts of the frozen proposal, with private validator labels applied offline. This is a prediction about that continuation policy, not exact logical feasibility. Calibrate on validation worlds with Brier score and reliability bins. Freeze both heads before comparing arms; do not tune them on evaluation traces.

Proposed development schedule after model/sensor gates: `20,000` exact-count training worlds, `2,000` validation worlds, `2,000` ID evaluation worlds, three independent training seeds, at most `16` sampled training states per training world, proposal training for at most `20` epochs with early stopping on validation KL, then `128,000` fixed-policy value rollouts. These are feasibility defaults, not frozen counts. Stage 0 must measure generation/solver/feature cost; change counts only via a versioned amendment before protected evaluation.

## 6. Arms and budget allocation

All learned arms use the same frozen proposal/value parameters, task inputs, initialization policy, and paired task/RNG seeds. Use the budget set `B ∈ {64,128,256,512,1024}`. For fixed-width arms use `W ∈ {1,2,4,8,16,32}` with nominal `D=floor(B/W)` and a predeclared remainder assignment. `PARTICLE` has a maximum live width `W` and an adaptive depth distribution; record actual depth per particle.

| Arm | Transition and selection rule |
| --- | --- |
| `DEPTH` | One trajectory, greedy learned proposal, `B` charged expansions; common value selector over visited states. |
| `SAMPLED-DEPTH` | One trajectory, learned sampled proposal; controls for stochasticity. This is `LEARNED-WIDTH` at `W=1`. |
| `RANDOM-WIDTH` | `W` trajectories, uniform legal edits, same selector interface and charged value calls. |
| `LEARNED-WIDTH` | `W` independent trajectories sampled from learned proposal, no merge. |
| `MERGED-WIDTH` | Learned width with raw-assignment merge and deterministic expansion recycling. |
| `CANONICAL-MERGE` | Learned width with the public/task-legal canonical assignment key. |
| `PARTICLE` | Canonical merge plus fixed-period value resampling and value-guided allocation, with a nonzero minimum allocation per live particle. |

`ORACLE-SELECT` is calculated post-hoc over each arm's **same trace** and equals that trace's `R(B)`. `ORACLE-PROPOSAL` may use the private teacher at inference for a diagnostic ceiling; its solver overhead and privilege are reported separately, and it is excluded from the advancement comparison. Publish all temperature, value tie, merge tie, resampling interval, RNG counter, and budget remainder rules before a run.

## 7. Compute ledger and result surface

For every arm/task, record `proposal_calls`, logits scored, `value_calls`, encoder forward calls/tokens, canonicalization calls and group size, hashes/probes, merges, resampling operations, CPU active nanoseconds, GPU active nanoseconds, end-to-end nanoseconds, peak resident/device bytes, and trace bytes. Charge a proposal/value operation even if its child is discarded or merged. The common LFM encoding is charged once per task in the end-to-end result; a cached-feature result is secondary and labeled.

Report two curves: `R_B` at matched charged expansions and `R_C` at matched measured end-to-end time on a named pinned host. Include the full `B × W × N × canonical-solution-class` surface and actual per-particle depth distribution. The user-facing “matched compute” claim requires both the predeclared expansion comparison and the measured-cost comparison to support it. Batched width may improve latency; report active compute and latency separately. Keep oracle validation and offline analysis time outside inference cost, with their own accounting.

Primary cell proposal: `B=256`, `W_max=8`, held-out `N=12`, `5–16` canonical valid classes; predesignated unseen size `N=14`. The proposed advancement rule and its caveat are in [DESIGN-AUDIT.md](DESIGN-AUDIT.md). All seed predicates must be computed **jointly within each training seed** before counting how many seeds pass.

## 8. Trajectory and analysis contracts

Save every transition, including failed/merged/resampled branches. A versioned JSONL event holds:

```text
run/task/split/arm/training_seed/action_seed
global_expansion_index, particle_id, parent_id, ancestry_id, particle_depth
assignment_before, assignment_after, canonical_key
latent_state_before, latent_state_after (or lossless sidecar offsets + hashes)
edit, log_probability, value, remaining_budget
selected, resampled, raw_merge, canonical_merge, representative_id
proposal/value/encoder/canonicalizer costs, RNG counter
posthoc_valid, posthoc_first_hit
```

The `posthoc_*` fields are joined into a separate analysis sidecar **after** the online trace is closed; they are never visible to search. The latent-state sidecar may be compressed, but it must remain lossless and replayable; hashes alone are insufficient. Bind sidecar offsets and trajectory files in the run manifest. Compute first-hit expansion/cost, raw and canonical unique counts, duplicate rate, future expansions redirected after merging, ancestry entropy, branch survival, pairwise assignment diversity, distinct reached valid classes, exact class coverage only when the denominator is exact, value calibration, selection regret, throughput, latency, and memory per live particle. Report `R(B)`, `S(B)`, and their paired difference by task, seed, size, and solution-class stratum. Use paired task/bootstrap intervals as annotations, not new pass gates.

Only after the primary run is locked, replay fixed trained weights and task/RNG seeds with one mechanism disabled at a time: width, learned sampling, raw merge, canonical merge, value resampling, selection, depth cap, and branch cap. These lesions are diagnostic; they do not license tuning against the held-out set.

## 9. Stage 0 construction gate and stop boundary

The first executor pass can implement and inspect without LFM/model contact:

1. Independent typed-constraint validator and exact solver/enumerator agree on exhaustive tiny tasks and accepted generated tasks; every accepted count has exhaustion proof/status.
2. Seeded generation produces stable task IDs and identical bytes on a second construction run. Proposed smoke: `96` accepted worlds spanning both role-anonymous and role-specific families, all proposed multiplicity strata, and `N≤6,K≤3` exhaustive checks where feasible.
3. The legal symmetry group is verified against the typed AST; `kappa` is deterministic/idempotent and preserves validity. Role-specific constraints show the expected symmetry reductions.
4. The inference projection cannot access private AST, `Y`, solver status, oracle distances, or hidden automorphism metadata.
5. A stub encoder/controller drives every non-oracle arm through the same deterministic scheduler and complete replay trace. Every expansion and recycled slot balances in the ledger.
6. Source/fixture/contract hashes, environment, host, command, and failures are recorded in a versioned construction receipt.

Stop at `R1_CONSTRUCTION_READY` or a specific construction failure. Model/tokenizer access, feature extraction, proposal/value fitting, and protected evaluation require later R1-specific gates and run manifests. No FAS-00 closure status can be promoted or superseded by an R1 construction receipt.
