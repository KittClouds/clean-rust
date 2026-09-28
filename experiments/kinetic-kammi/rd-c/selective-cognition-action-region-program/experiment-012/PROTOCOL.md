# E012 — Prospective Frame Decomposition

**Program:** Selective Cognition / Action Region Program  
**Protocol version:** 0  
**Status:** `FROZEN_FOR_BANK_CONSTRUCTION`  
**Model contact:** prohibited until the bank, truth labels, audit, and run lock are complete  
**Classification:** downstream R&D; no upstream scientific authority

## 1. Question and object

The question is: **which information structures support the frozen small observer's reliable direct-action region, and when does it appropriately abstain?**

The object is the matched decision system:

```text
S = (P, Pi, O, tau, A)
```

where `P` is the candidate producer, `Pi` is the versioned producer-order/presentation contract, `O` is the frozen E009 v5 observer bundle, `tau` is the frozen `850/150` applicability/abstention threshold pair, and `A` is the E002 deterministic authority plus E011 presentation receipt and replay path.

Freeze the observer(s), prompt, schema, normalizer, routing rule, candidate-generation algorithm, receipt format, thresholds, action semantics, and scoring rules. E012 makes no prompt, threshold, model, authority, or post-hoc ordering changes. The only observer-visible changes are the preregistered frame-channel treatments below. Each treatment frame is compiled from separately stored source channels before observer contact.

## 2. Channels and truth support

The canonical task record stores these fields separately:

| Symbol | Channel | Contents |
| --- | --- | --- |
| `E_t` | Task/request evidence | User objective, requested behavior, and task constraints. It contains no repository identity or test result. |
| `E_c` | Candidate/action evidence | Stable candidate IDs, action summaries, and patch content. It contains no task prompt or candidate-specific test outcome. |
| `E_x` | Test/execution evidence | Pre-action observations from the broken/base snapshot: exact failing test output, logs, traces, or execution facts. It contains no candidate-specific pass/fail result and no hidden completion label. |
| `E_r` | Repository/context metadata | Typed language, toolchain, package/build boundary, compatibility constraints, and repository provenance metadata. Content duplicated into `E_t`, `E_c`, or `E_x` is prohibited. |
| `E_p` | Candidate coordinates | The mapping from semantic candidate identity to producer ordinal/array position. It is a representation factor, not presumed task truth. |

For every task, the bank records `D_i`, the channels among `{E_t,E_c,E_x,E_r}` that contain task-relevant truth by construction. `D_i` is derived from the task generator's hidden construction and verified by paired counterfactual fixtures, not assigned from observer outputs or an annotator's guess. `E_p` is recorded separately as a coordinate assignment; it is not part of semantic truth support and must never encode the gold action by design. Position can still affect accessibility, which is analyzed as a paired representation factor.

Use at least these strata:

1. task/request-dominant (`D_i={E_t}`);
2. candidate/action-dominant (`D_i={E_c}`);
3. pre-action test/execution-dominant (`D_i={E_x}`);
4. joint support (`D_i` includes at least one preregistered pair, initially `E_t+E_c` or `E_c+E_x`);
5. context-sensitive (`D_i` includes `E_r` and the compatibility/build fact genuinely changes which candidate is admissible);
6. abstention-positive (even the full frame does not justify any offered action, so the correct direct decision is abstain).

At least two independently authored task families must instantiate each stratum. A family is not a prompt paraphrase: it has a distinct repository behavior, hidden construction rule, and executable completion check. Build at least 48 tasks across at least 12 families and at least three repositories not used as evaluation repositories in E009/E010/E011. Keep the task language fixed within E012 unless the bank audit shows language variation is required to instantiate `E_r`; record any such decision before task generation.

## 3. Channel operations

For truth-bearing channels `E_t`, `E_c`, `E_x`, and `E_r`, use these exact meanings:

- **PRESENT:** the authentic, task-specific channel payload generated for that task.
- **ABSENT:** the channel value is replaced by a fixed typed sentinel; the source channel remains separately preserved in the bank vault. Frame schema and neighboring channels are unchanged.
- **NONINFORMATIVE CONTROL:** a valid, matched-size payload from the same schema that is independent of the recipient's correct action and task truth. It must not contradict a runtime constraint or create a new valid action.
- **SWAPPED:** the channel payload from a preregistered, isomorphic donor task is inserted while all recipient channels and recipient truth stay fixed. Donor assignment is fixed before model contact; incompatible donors are forbidden.

Absence and noninformative controls are distinct. No missing field may cause the projector to drop other fields or change candidate ordering. The projector preserves the frozen observer schema and uses the same serializer for all conditions.

`E_p` is different: an ordered candidate array always has positions, so literal positional ABSENT is not representable to this observer and is preregistered `NOT_APPLICABLE`. Its coordinate conditions are assigned prospectively by the same frozen producer algorithm:

- **PRESENT:** producer-native sequence, with ordinal assigned as each candidate is created.
- **NONINFORMATIVE CONTROL:** a committed-seed, truth-balanced candidate-to-position schedule assigned during frame construction. Candidate IDs remain attached to semantic candidates and are independently randomized from correctness and position.
- **SWAPPED:** for predeclared isomorphic task pairs only, apply the donor's candidate-role-to-position schedule while constructing the recipient frame. The donor map is assigned before ordinals and receipt are created.
- **ABSENT:** `NOT_APPLICABLE`; do not claim a sequence model has received a set without coordinates.

Every coordinate condition has a distinct frame digest and receipt. The runtime restores the ordinals assigned by that condition before serialization. No candidate is moved after its presentation receipt is created. This tests the effect of prospectively specified coordinates while retaining E011's interface invariant.

## 4. Frozen conditions and sequence

All conditions and analysis code are fixed before task construction. Construct every condition from its source channels; do not mutilate scored natural frames after the fact.

Run in this order:

1. **Full-frame baseline:** all authentic channels and producer-native coordinate schedule.
2. **Single-channel necessity:** four paired leave-one-out conditions, `F\E_t`, `F\E_c`, `F\E_x`, and `F\E_r`.
3. **Single-channel sufficiency:** `E_t` alone, `E_c` alone, `E_x` alone, and `E_r` alone, with typed sentinels in other channels.
4. **Preregistered pair sufficiency:** `E_t+E_c`, `E_c+E_x`, `E_t+E_x`, and `E_t+E_r`.
5. **Control checks:** for each truth channel, its noninformative-control and swapped condition on matched tasks; for `E_p`, the paired truth-balanced and eligible donor-coordinate conditions.

The same tasks, candidate content, candidate IDs, task truth, and outcome checks are paired across conditions. Only the named source channel or coordinate assignment changes. If a stratum cannot support an isomorphic donor or a specified subset by construction, record `NOT_APPLICABLE` before generating that task; do not invent a substitute after results.

## 5. Bank construction and precontact admission

Select repositories and task families without inspecting E009 v5 outputs on those tasks. Pin repository commits and archive hashes. Each task has multiple offered actions where practical; more than one action may be valid. The authoritative outcome is the set of offered patch identities that pass the frozen task completion check, plus whether the visible channels justify direct action. An abstention-positive task has no authorized candidate even if a patch happens to pass an incomplete local check.

Keep source channel payloads, task truth, executable checks, and observer frames in separate fixtures. Before model contact:

- execute every candidate check in an isolated snapshot and confirm the expected valid-action set;
- verify every `D_i` with the generator's paired truth/counterfactual construction;
- verify absence, controls, swaps, and projection changed only their declared field;
- verify candidate IDs and position assignments are independent of correctness, with exact balance by correctness class and task stratum; if exact balance is impossible, redesign the block rather than waive the check;
- test ID-only, position-only, candidate-length, evidence-count, test-count/status, repository-code, family-code, and simple lexical baselines with family-grouped splits;
- for every claimed necessary channel, include paired worlds identical on all other channels but with different correct-action sets; for every claimed sufficient set, confirm it resolves the bank's declared action ambiguity by construction;
- reject or repair a bank if any nuisance feature or undeclared channel deterministically identifies the correct action or completion label, or if a required-channel twin can be distinguished without that channel;
- hash all inputs, fixtures, scripts, and audit outputs in a precontact lock.

The audit can see labels; the observers cannot. Bank repair happens before model contact, and failed builder/audit attempts remain preserved. No task can be selected, excluded, or rewritten based on observer behavior.

## 6. Observer runs and scoring

The frozen small observer sees every channel condition. The large observer is called only for the full-frame baseline and the frozen hybrid's abstention fallback there; channel-condition runs are small-observer diagnostics and do not silently add deliberation. All calls use the E009 v5 bundles, prompt, output schema, reasoning/runtime settings, normalization, and thresholds inherited by the E011 integration lock. The E012 precontact lock must copy exact hashes and reject drift.

All candidate execution occurs in isolated snapshots. No external action is authorized. Every frame condition has its own request ID, producer-order receipt, authority receipt, and replay record. The normal E002 authority decides legality; a correct receipt does not certify semantic correctness.

For every repository, task family, dependency stratum, and condition, report exact counts and paired differences for:

- direct-action coverage and abstention;
- direct-action precision among tasks whose visible channels justify action;
- unsupported direct actions when the matched construction says the view is insufficient;
- selected-action identity changes;
- exact completion-test pass rate for selected actions;
- large fallback recovery and hybrid completion on the full-frame baseline;
- calls, input/generated tokens, latency, receipts, illegal commits, duplicate effects, and replay identity.

Keep coverage, precision, abstention, test completion, and unsupported action separate. Do not collapse them into one score. Repository and family rows are primary; pooled counts are descriptive. Resample at task-family level for descriptive uncertainty intervals; do not treat variants or condition rows as independent tasks.

### Full-frame admission gate

Proceed to channel interpretation only if the frozen full-frame small observer acts on at least eight tasks spanning at least three task families and at least two repositories, with zero wrong or unsupported direct actions, and the full-frame hybrid does not underperform always-large completion within each repository. Require zero illegal commits, duplicate action effects, presentation-binding failures, or replay mismatches. If the gate fails, seal the result and stop this decomposition bank; do not tune or replace the observer in E012.

## 7. Interpretation and stop boundaries

Removing a channel can change coverage, precision, proposal identity, or all three. Reduced coverage with stable precision may be appropriate abstention; it is not automatically lost capability. A channel is not called necessary or sufficient from observer output alone: those words refer to the precontact construction and paired truth tests, while behavior is reported as sensitivity/accessibility under that intervention.

E012 is a discovery and capability-characterization run. It does not prove internal mechanism, broad repository transfer, or that a useful channel effect will transfer. A post-E012 hypothesis earns a fresh prospective E013 bank before it changes the runtime. No findings flow back into upstream science.

## 8. Independent review loop

After raw scoring and the output seal, prepare one immutable review packet containing protocol and lock hashes, bank/audit summary, raw result tables, known failures, and analysis code. Independent reviewers receive identical packets separately and submit before seeing other reviews. Preserve each review verbatim, then produce a cross-review delta that lists agreements, disagreements, missing checks, and proposed interpretations without averaging away disagreement. A synthesis document follows the delta; only that synthesis directs the next experiment. Reviewers cannot edit sealed inputs, labels, outputs, or scores.

## 9. Stop boundary

This protocol freeze authorizes bank construction and precontact auditing only. It does not authorize observer contact. Model contact requires a separate `FROZEN_BEFORE_MODEL_CONTACT` run lock over the completed bank, exact task and truth fixtures, audit report, runtime/bundle hashes, and all analysis scripts.
