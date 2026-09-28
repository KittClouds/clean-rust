# R&D-C / Frozen Fabrique — E013 Trust-Signal Development Protocol v0.3

**Protocol ID:** `E013-TRUST-SIGNAL-DEVELOPMENT-v0.2`  
**Status:** `SEALED_PROTOCOL_DESIGN_ONLY_V0.2`  
**Current model-contact authorization:** `false`  
**Lineage:** follows the sealed E012 failure; precedes any frame decomposition.  
**Review amendment:** v0.2 incorporates independent precontact review deltas: all-task/empty-set risk accounting, executable T3/T4 definitions, explicit pooled-claim scope, and versioned E012 anatomy/control corrections.

## 1. Question and scope

**Question:** Which externally observable signal best ranks a small observer's proposed action by executable semantic correctness, and does a frozen region selected from that signal retain value against the large-model fallback on an untouched bank?

The object is the matched system:

`S = (P, Pi, O, tau, A)`

where `P` is the candidate producer, `Pi` the producer-order presentation/receipt contract, `O` the frozen observers, `tau` the recorded v5 thresholds and normalization, and `A` deterministic authority/replay. These remain frozen throughout E013-D and E013-C. Only the trust/routing layer is evaluated. No E012 fitting or subgroup carving is allowed.

This tests an engineering routing signal. It does not explain model mechanism, establish scientific validity, or use the large observer as truth.

## 2. E012 closeout and preserved boundary

E012 remains unchanged as a sealed failure artifact. Its failed claim is specifically that the v5 self-reported applicability/abstention rectangle transports as a reliable direct-action trust mechanism. The authority and presentation/replay contracts remain intact. The read-only anatomy addendum v1.1 is separately stored and hashed; v1 remains preserved as its reviewed predecessor.

The old applicability and abstention outputs remain logged and serve as baseline signals. They receive no privileged status. A candidate action is assessed against the independently sealed executable valid-action set, not against either model's opinion.

## 3. Frozen observer identity

Pin these identities to the E012 raw-output manifest before any future E013 contact:

| Field | Small | Large fallback |
|---|---|---|
| Bundle ID | `minicpm5-2b-q8-local-v5` | `ternary-bonsai-2-27b-ptq1-local-v5` |
| Bundle BLAKE3 | `03203842e1835233af8d9ef337bca1395be9c3828333c79eb96e199e52925842` | `6d933aba093307e0c333f022426af46f3f5b243a8a10a2e1bb2f4cfc93b17b9d` |
| Model SHA-256 | `c5415f8989bf88a8288f1b55a3cc371af53c07b0faa220a63bd7a990cfaba078` | `53107f530aa52eb00912263ab1ee29bd199261c87cd7b4ad4ca1318c1fe33ee3` |
| Runtime SHA-256 | `ffaee576ad271ede87b92a7d8c3863dc8f331bbac666ee00099c250e8809e743` | `e0ea4fd53e6f0c741cbd28093b427f333ada0eb03b83073e1f99c483793ea976` |
| Reasoning / output cap | `off / 1024` | `off / 1024` |
| System prompt SHA-256 | `976ef1cd914bacb366c64418825010124338a626a0400d459858acc7e48f5a48` | same |
| Output schema SHA-256 | `97170fa0d6a44681f680ad0ac533a3f3913709757e4ee6cbf96d9c9f40d1b2fb` | same |
| Normalization | `percent-0-100-to-milli-x10-v1+line-endings-lf-v1` | same |
| Recorded thresholds | `850 / 150` milli | `850 / 150` milli |

Also freeze the exact candidate producer, producer ordinal, receipt/authority binary and config, toolchain, sampling settings, prompt bytes, chat template, and request schema from the selected qualified runtime. The table is an identity cross-check, not sufficient alone to authorize model contact. Any mismatch creates a new observer bundle/experiment identity; no silent repair.

Raw candidate proposals with a non-null action are scored even if the legacy v5 rectangle rejects them. This lets the trust signals be evaluated without treating the rejected self-report coordinates as ground truth. The old rectangle is replayed as a baseline lane. Null proposals remain abstentions and are reported separately.

## 4. Fresh bank construction and information firewall

Construct all task snapshots, candidate patches, visible screening fixtures, and hidden completion fixtures before any future model contact. No E012 tasks are used for fitting, threshold choice, or confirmation. Freeze source commits, task/family/repository IDs, candidate patch identities and producer order, task prompts, fixture hashes, label code, seeds, and generator version.

### E013-D development bank

- Fixed design: 864 frozen local-commit task instances from six frozen Rust repositories, eight task families per repository, eighteen tasks per family.
- Task/family selection is outcome-blind and fixed before model contact. Candidate count, valid-set size, difficulty, repository, family, and empty-valid-set strata are predeclared and recorded.
- Include one truth-changing candidate-selection pair inside each repository/family cell (48 pairs / 96 task instances total). Each pair holds the offered four-patch content and producer order fixed while task evidence and the executable valid set change so the correct patch changes. Pair members are candidate-selection tasks, not empty-valid-set tasks, and count inside the fixed bank size. Pair IDs and labels remain hidden from observers.
- Fixed empty-valid-set strata are included before model contact: one genuine no-safe-candidate task in each development repository/family cell (48/864 tasks), and two in each confirmation repository/family cell (64/1,120 tasks). Pair members are not part of the empty-valid-set quotas. Each such task has four offered patches and an executable check showing every offered patch violates the task contract. If a required cell cannot be constructed, use only an outcome-blind reserve in that same cell before model contact; otherwise fail the bank construction gate rather than silently dropping the stratum. Never infer emptiness from model behavior.
- Labels come from frozen, executable task-completion checks and independent patch outcome receipts. Multiple valid patches are allowed. A proposal is correct iff its patch identity is in the sealed valid set.
- Development uses fixed six-fold leave-one-repository-out cross-fitting for any learned signal: one repository is held out per fold, and all fitting for that fold uses the other five repositories. Keep all task families and paired variants from one repository in the same fold; do not randomize task-level folds. T5 is eligible only if the fixed bank yields at least 100 correct and 100 wrong non-null small proposals. The E012-rate planning probability of reaching both counts on this 864-task design is 99.57% under an iid multinomial approximation; this is not a guarantee. If observed support falls short, T5 is unavailable; do not grow the bank after observing model outputs.

### E013-C confirmation bank

- Fixed design: 1,120 fresh frozen local-commit task instances from four new Rust repositories, eight new task families per repository, thirty-five tasks per family.
- Repositories and task-family identities are disjoint from E013-D and prior E009/E010/E012 task identities. No refitting, recalibration, threshold change, feature substitution, or bank replacement.
- Include one independent truth-changing matched pair inside each confirmation repository/family cell (32 pairs / 64 task instances total), under the same construction contract as E013-D. Pair members count inside the fixed confirmation size.
- Confirm once under the locked selection. If the required accepted support is not reached, report insufficient support; do not backfill based on outcomes.

### Visible/hidden evidence separation

The router may see task evidence, candidate patches, and explicitly designated pre-query or screening outputs. It may not see hidden completion-test files, hidden label fixtures, oracle valid-set IDs, or any deterministic encoding of them. Maintain separate source roots, identifiers, permissions, and manifests for visible screening and hidden completion fixtures. Require a precontact audit showing zero shared fixture hashes and no answer-bearing field or field combination in the public frame. The task-authoritative label writer is isolated from observers and routers. The large observer is never a label source.

All screens and queries are receipted with task ID, patch identity, tool/version, visible fixture hash, result, cost, latency, and replay identity. Any discovered leakage invalidates the affected bank before scoring; repair the generator, create a new bank identity, and preserve the failed construction.

## 4.1 Proposal-yield accounting and oracle ceiling

Before any trust signal is scored, report for every task and stratum exactly one of: `NO_PROPOSAL`, `RAW_CORRECT_PROPOSAL`, or `RAW_WRONG_PROPOSAL`. A non-null candidate on an empty-valid-set task is wrong by construction. The no-proposal category has its own count and is not included as an action error or allowed to disappear from denominators.

For each bank, report the evaluation-only oracle-trust ceiling that accepts exactly the correct non-null raw proposals. Report its correct accepted count, task coverage, and proposal-conditional precision. This oracle can reject wrong proposals but cannot manufacture a proposal where the observer returned null. It has no runtime authority and is never compared as a deployable policy.

The precontact feasibility receipt is `E013-FEASIBILITY-RECEIPT-v0.3.md`. It contains E012-rate and explicit nominal planning scenarios, gate-reachability probabilities, and per-signal call/compute estimates. Those projections are sizing illustrations only; the sealed bank's actual proposal yield replaces them descriptively after contact.

## 5. Candidate trust signals

Compute each coordinate on the same development proposals. First evaluate each separately; do not fit a broad feature search. Every score definition and transform is frozen before confirmation.

### T1 â€” Execution-grounded evidence

After the small proposal and before routing, use only designated visible screens: patch application, compile/type-check, lint, and visible tests. Store each result separately. Evaluate each component and one predeclared monotone lexicographic screen score (apply, compile, lint, visible-test pass fraction). Charge and receipt every screen. The visible screen fixture set must be hash-disjoint from hidden completion checks. Execution evidence is environmental evidence, not model confidence.

### T2 — Perturbation stability and evidence responsiveness

For each non-null baseline small proposal, run the three fixed, predeclared experimental candidate permutations and map each response back to semantic patch identity. Each presentation has its own valid receipt; all are shadow-only and none can commit an action. The primary T2 score is the fraction of permutation responses selecting the same semantic patch as the producer-order baseline. Record null and invalid responses separately. Tasks whose baseline result is `NO_PROPOSAL` remain in that category and are not rescued or assigned a T2 trust score.

The E013-D and E013-C truth-changing pairs hold offered candidate content and exact producer sequence constant while changing task evidence and the executable contract so a different offered patch is correct. Report per pair whether the observer selects the member-specific correct patch on both tasks, gets one correct, repeats the same patch across the changed truth, abstains, or returns another patch. Cross-tabulate this evidence responsiveness against permutation stability. High stability is not itself positive trust: a stable observer that repeats a now-wrong choice is classified as stable-wrong/evidence-insensitive. Production continues to preserve receipt-bound producer order as required by E011; these are experimental shadow interventions only.

### T3 — Token-level choice margin â€” Token-level choice margin

If and only if the frozen inference runtime exposes faithful token log-probabilities without changing prompt, schema, or observer identity, and the baseline small output is a non-null candidate proposal, score every offered numeric action ID under teacher forcing. A `NO_PROPOSAL` task has no chosen-action margin and remains outside T3 routing support. Use the exact rendered request plus the fixed response prefix `{"action_choice":`; serialize each offered ID as canonical base-10 digits followed by the same comma delimiter. For candidate `i`, let `T_i` be the tokenizer output for those digits and define `q_i = (1/|T_i|) * sum_t log p(T_i[t] | request, prefix, T_i[<t])`. The signal is `q_chosen - max(q_j)` over all other offered candidates. This mean token log-probability is a ranking heuristic, not a calibrated probability. Record tokenizer/model hashes and all exact token sequences. If token scores are unavailable, the response prefix is not valid for the frozen schema, or any candidate cannot be scored faithfully, mark T3 unavailable for the whole bank; do not substitute a verbal confidence field.

### T4 â€” Comparative candidate coherence

For each non-null baseline proposal and offered set of `k` candidates, issue one pairwise comparison for every unordered pair and repeat it with the two candidates reversed. A `NO_PROPOSAL` task is not eligible for direct-choice coherence and receives no T4 calls. Use the exact same task evidence, fixed pair prompt, and frozen observer; each presentation is receipt-bound and shadow-only. A pair has a decisive directed edge only when both orientations select the same semantic patch. If the orientations disagree, either response is null, or an unoffered candidate is returned, record that pair as unresolved (and record the invalid response separately). Record decisive-pair coverage and orientation-reversal rate. For every triple with all three edges decisive, count a cycle iff its three directed edges form a 3-cycle; `cycle_rate = cycles / fully_decisive_triples`, or unavailable when the denominator is zero. Separately define `direct_choice_win_rate` as decisive wins by the baseline direct proposal divided by decisive edges incident to that proposal; unavailable if the proposal is null or has no decisive incident edge. T4 risk-coverage uses `direct_choice_win_rate` (higher ranks as more coherent); cycle and reversal rates are separate diagnostics. Ties and invalid outputs have the definitions above and need no post-hoc tournament tie-break. These calls cannot authorize an action; record their inference cost.

### T5 â€” Internal-state correctness probe (development-only exploratory signal)

If the frozen small runtime permits a read-only forward hook, extract the final prompt-token representation at the penultimate transformer block before output generation. Verify hook/no-hook output identity on a precontact synthetic fixture and hash the extraction code. Fit one L2 logistic probe (`C=1`, fixed standardization, no class reweighting) to predict whether the proposed patch is in the executable valid set. Train only on E013-D; evaluate by repository-grouped cross-fitting. Do not fit or inspect E012 hidden states or labels. T5 is ineligible below 100 correct and 100 wrong non-null proposals. If extraction changes the model result, adds answer-bearing features, or the representation surface cannot be pinned, mark T5 unavailable rather than changing the frozen observer.

### T6 — Explicit NONE action (separate action-space arm)

The locked bank design contains genuine empty-valid-set tasks, so run `NONE` as a separate, frozen observer/schema arm on the development tasks and report it separately. `NONE` changes the action space to `{candidate_1, …, candidate_k, NONE}` and is not a confidence feature. Give it separate receipts and results; do not fold it into the frozen v5 signal comparison or call it a v5 trust-signal improvement. It does not enter the E013-C trust-route admission gate. If bank construction fails its predeclared empty-valid-set checks, fail construction rather than silently omitting this arm.

### Locked call accounting

Record logical inference evaluations separately from transport/API requests and wall time. On a four-candidate task with a non-null baseline proposal: T1 costs four separately receipted environment screen jobs; T2 costs three extra small-observer permutation evaluations; T3 costs four candidate-ID teacher-forced score evaluations; T4 costs twelve pairwise observer evaluations (six unordered pairs × two orientations). T5 captures one read-only internal state during the already-required baseline small forward pass if the hook/no-hook identity check passes; otherwise mark it unavailable or separately charge the extra forward pass. `NO_PROPOSAL` tasks incur only the baseline pass and any inline T5 capture. A combination's costs are the sum of its component signals. The separate T6 `NONE` schema arm costs one additional small-observer evaluation per task and is reported apart from the trust-signal lanes. Report model evaluation counts, batched request counts, screen jobs, input/generated tokens, wall time, and measured tool/inference costs separately.

### Legacy baselines and one combination

Record legacy applicability and abstention separately, plus the original `850/150` rectangle. Do not create another verbal confidence scalar. A single fixed-combination candidate may be evaluated only if at least two available individual coordinates improve development-set risk at matched coverage in repository-grouped cross-fitting. Its sole allowed form is L2 logistic regression (`C=1`) over standardized available T1â€“T5 coordinates; no hyperparameter sweep, feature search, or recursive combinations. Any fitted transform/probe/combination uses development labels only and is refit once on the whole development bank after operating-point lock.

## 6. Risk-coverage analysis

Primary object: risk-coverage curve for each individual signal and the one eligible combination.

- Primary routing denominator: every non-null small candidate proposal on every task, including empty-valid-set tasks. A candidate proposal on an empty-valid-set task is necessarily wrong. This measures false-accept risk when no offered action is correct.
- Also report a separate candidate-selection-only curve excluding empty-valid-set tasks; never use that conditional curve as the admission gate.
- Correctness: the selected patch identity is in the sealed executable valid-action set. On an empty set, every candidate proposal is wrong. A null proposal is an abstention and is not a direct action; separately report when a raw proposal exists but the legacy v5 rectangle rejects it.
- Risk at coverage `c`: wrong accepted proposals divided by accepted proposals at that operating point.
- Tied scores are admitted or rejected as a whole using a deterministic threshold rule; do not split ties by task ID or outcome.
- Report full all-task routing and candidate-selection-only curves, coverage at fixed maximum empirical risk targets `{1%, 2%, 5%, 10%}`, risk at fixed coverage targets `{5%, 10%, 20%, 40%, 60%}`, and AUROC as a secondary ranking diagnostic. Show denominators, ties, and per-repository/task-family/candidate-count/valid-set/difficulty/empty-valid-set strata.
- A score with a sign or ordering specified before outcomes is oriented high=more trusted. Transformations are fixed before inspecting correctness. No E012 subgroup, threshold, or error-derived rule is permitted.
- Bootstrap or resample by repository/task-family clusters only as descriptive uncertainty analysis; never treat the 48 E012 tasks as development data.

## 7. Development freeze procedure

E013-D selects at most one individual signal or the one predeclared eligible combination. Use repository-grouped cross-fitting for ranking/risk curves. Select the operating threshold as the highest-coverage threshold whose development cross-fitted exact one-sided 95% binomial upper error bound is at most 5%, with at least 60 accepted small candidate actions across the primary all-task denominator (including empty-valid-set tasks). If no threshold meets both conditions, select no router and close E013-D as no signal qualified. The precontact expectation is that T1 execution evidence is the only individual signal with a plausible path to the 59–93 accepted-action region; this is a prior expectation, not an eligibility privilege. T2–T5 can still produce an informative risk-coverage improvement without meeting the admission gate.
A trust signal may show a reproducible development risk-coverage improvement yet miss minimum support, the exact error bound, or fallback-relative value. Preserve and report such a result as an informative diagnostic about ranking/accessibility, but do not promote it or call the admission gate passed.

Freeze and hash the selected signal definition, feature code, all transforms, threshold, tie behavior, minimum support, routing rule, fallback, observer identities, authority/presentation contracts, label code, bank policy, and evaluation code before E013-C. E013-D is development only and cannot support a confirmation claim.

## 8. Fallback-relative evaluation

On identical E013-C episodes compare:

1. no direct small actions / always-large fallback;
2. original v5 self-report rectangle, as a baseline only;
3. each frozen E013 trust route selected on E013-D (only one promoted candidate is run as the primary route);
4. a matched-random acceptance control at the routed lane's accepted count and call count;
5. small-only and large-only descriptive lanes.

Use the same snapshots, candidates, tool screens, action simulator, deterministic authority, receipts, and journal policy. Hidden completion checks run only after the route decision is committed to the evaluation log.

Report direct coverage, direct precision/error, wrong-small/right-large false accepts, right-small/large-wrong complementary wins, false abstentions that invoke fallback, fallback recoveries, task completion, large calls, observer/tool calls, input/generated tokens, latency, and measured inference/tool costs. Show per repository and task family plus pooled descriptive values. Never label large-only output as truth.

Routing value is relational. A direct region is not useful solely because it predicts small-model correctness. Compare it to the fallback and report the two discordant outcome classes separately. Do not combine error, calls, tokens, latency, and money into an unregistered scalar utility.

## 9. Confirmation admission gate

E013-C can admit a bounded engineering routing region only if all conditions pass:

1. At least `n_min = 60` direct small candidate actions are accepted by the frozen E013 threshold across the primary all-task denominator. Any routed candidate on an empty-valid-set task counts as a wrong action.
2. The one-sided exact Clopper-Pearson 95% upper bound for semantic error across all accepted small candidate actions, including proposals on empty-valid-set tasks, is `<= epsilon = 5%`. For `x` wrong out of `n`, solve `P_{p=U}(X <= x) = 0.05`; for zero errors, `U = 1 - 0.05^(1/n)`. At `n=60,x=0`, `U≈4.87%`. The support and risk checks are both mandatory; `1/1` cannot pass. If errors occur, more support may be needed, but the bank is not extended after outcomes.
3. Presentation binding, authority checks, replay identity, and duplicate-effect checks have zero violations.
4. The frozen route has positive fallback-relative engineering value: no lower observed completed-task count than large-only, displaces at least one large call, and improves at least one separately reported resource axis (measured wall time or measured inference/tool cost). Tokens remain separately reported. If this gate fails, preserve the signal as diagnostic only.
5. No predeclared repository stratum with at least 20 accepted actions has observed error above 10%. Report all strata regardless of support; this guard prevents a favorable pooled mean from hiding an obvious harmful repository slice. It does not authorize subgroup thresholds.

The exact binomial bound is a task-level gate. Because tasks cluster by repository and family, report cluster-level uncertainty alongside it and state that the exact bound does not by itself establish broad repository generalization. The pooled four-repository gate supports only a bounded claim for the evaluated mixture, not per-repository portability. A per-repository portability claim requires at least 60 accepted actions and the same exact 5% upper-error gate independently in every claimed repository.

## 10. Integrity, crash, and replay checks

Retain E002/E011 authority and producer-order binding unchanged. For every route, receipt observer proposal, every external screen, score vector, threshold result, fallback request/response, chosen action, and completion outcome. Test crash/replay before and after screen receipt, trust decision receipt, large fallback intent/response, action intent/effect, and completion receipt. Stable IDs prevent duplicate simulated effects. Any authority/presentation/replay violation fails the run; semantic risk is scored separately.

## 11. Positive-control boundary

The user has authorized the separate 64-task E012 positive-control run. Its numeric contract is in `../e012-readonly-anatomy-addendum/E012-POSITIVE-CONTROL-DESIGN-v1.2.md`. That authorization does not authorize E013-D or E013-C model contact. The positive-control task bank is user-built and is not present in this work state, so the run remains pending; do not construct substitute tasks or contact either observer until the user-built bank and labels are sealed.

## 12. Review and stop boundaries

Before any separately authorized E013-D model contact, also build, test, and hash the executable implementations of T1–T5, pairwise scoring, risk-coverage, exact binomial bounds, grouped splits, and report generation. Include their source/version hashes in the precontact seal alongside bank and fixture hashes. This v0.3 document defines the scoring algorithms but is not a substitute for those executable, hashed implementations.

Lifecycle: `sealed v0.3 protocol and feasibility receipt -> user-built/sealed bank and fixtures -> sealed scoring/evaluation code -> precontact leakage audit -> separately authorized E013-D contact -> frozen selection -> fresh user-built/sealed E013-C confirmation -> separately authorized E013-C contact -> independent reviews -> synthesis`.

This document is the protocol design only. The user is building the banks. No bank has been built by this work; no E013 model contact, screen, or probe fit has occurred. E013 model-contact authorization remains false; E014 remains unauthorized; production routing is unchanged. E014 prospective frame decomposition is deferred unless E013-C admits a supported low-risk region.
