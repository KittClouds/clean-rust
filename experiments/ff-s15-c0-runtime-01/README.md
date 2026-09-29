# ff-s15-c0-runtime-01 — System 1.5, rung C0: the runtime contract

C0 is an ordinary deterministic package. It reads files and writes a receipt:

```
observation.json  +  decision vector (prerecorded observer outputs)  +  runtime policy
        +  decision contracts  +  observer bundles
                      │
                      ▼   s15 reference runtime (no model, no clock, no network, no randomness)
              decision + receipt.json
```

It has no live Library writes, no workspace dependency, no `/v2`, and needs no Chief online. It runs with no model at all.

**The gate:** the same inputs and the same contracts give a byte-identical decision and receipt.

**The invariant:** an observer's output may *propose* authority. It never *owns* authority.

Kammi integration comes only after C0 passes. Chief receives the artifacts this produces; Chief does not define the runtime.

## Run it

Standard library only; run on CPython 3.13.15 / Windows (the tests use `sys.stdlib_module_names`, so 3.10+ is the floor, untested). Run from this folder.

```bash
python -m unittest                                  # 106 tests, ~25 s
python tools/gate.py --out evidence/c0-gate-report.json   # the whole gate + a hash-anchored report
python -m s15 golden                                # 14 cases vs stored receipts (exit 1 on any difference)
python -m s15 check  --policy fixtures/policy.json --contracts fixtures/contracts --bundles fixtures/bundles
python -m s15 run    --policy … --contracts … --bundles … --observation O --vector V [--out receipt.json]
python -m s15 replay --policy … --contracts … --bundles … --observation O --vector V --receipt receipt.json
python tools/build_schemas.py [--check]             # regenerate / verify schemas/
python tools/make_fixtures.py [--check]             # regenerate / verify fixtures/
```

Exit codes: 0 success, 1 a check or comparison failed, 2 unusable input.
`golden --update` rewrites the stored receipts; it is the one deliberate way to change them, so review the diff.

## The records

Four normative contracts and three supporting records, as chartered — plus one more (see decisions).

| Record | Schema constant | Id field | Role |
| --- | --- | --- | --- |
| `DecisionContract` | `S15_DECISION_CONTRACT_V1` | `contract_id` | What an observer may answer: typed, closed. No free-form answer type. |
| `ObserverBundle` | `S15_OBSERVER_BUNDLE_V1` | `bundle_id` | The compatibility identity of one observer. Any compatibility field change is a different bundle. |
| `EscalationDecision` | `S15_ESCALATION_DECISION_V1` | — | DIRECT / USE_OBSERVER / USE_OBSERVER_SET / USE_LARGER_MODEL / USE_REASONER / ASK_HUMAN / ABSTAIN. Confidence does not authorize. |
| `AuthorityDecision` | `S15_AUTHORITY_DECISION_V1` | — | Fully deterministic: ALLOW / DENY / REQUIRE_ESCALATION with a reason code and the policy revision. |
| `ObservationEnvelope` | `S15_OBSERVATION_V1` | — | The input state: facts, actor, authority state. |
| `DecisionVector` | `S15_DECISION_VECTOR_V1` | `decision_vector_id` | The prerecorded observer outputs, keyed by bundle id. |
| `RuntimeReceipt` | `S15_RUNTIME_RECEIPT_V1` | `receipt_id` | Everything the run did and why: observers, traces, decisions, cost. |
| `RuntimePolicy` *(added)* | `S15_RUNTIME_POLICY_V1` | `policy_id` | The ordered escalation and authority rules, defaults, and costs. |

Schemas live in `schemas/` and are generated from one source (`tools/build_schemas.py`), so shared definitions cannot drift.
The validator (`s15/schema.py`) implements a deliberately small JSON Schema subset and *refuses* a schema that uses anything outside it.

## What happens in a run

1. **Escalation stage.** Rules are tried in order; the first whose condition is TRUE wins, else `default_escalation`. Conditions use three-valued logic (TRUE / FALSE / UNKNOWN), so a missing output can never make a rule fire.
   A tier that cannot act (`USE_LARGER_MODEL`, `USE_REASONER`, `ASK_HUMAN`, `ABSTAIN`) ends the run: `ESCALATED`, `ASKED` or `ABSTAINED`.
2. **Fail closed.** If any observer the rules consulted has no output, the tier becomes `on_incomplete_evidence` no matter what else matched.
3. **Authority stage** (only for `DIRECT`, `USE_OBSERVER`, `USE_OBSERVER_SET`). Fixed order: action not in the catalogue → DENY; action in `forbidden_actions` → DENY; then the policy's authority rules in order; then `default_authority`. `REQUIRE_ESCALATION` hands over to `on_require_escalation`.
4. **Disposition:** `EXECUTE_ALLOWED`, `DENIED`, `ESCALATED`, `ASKED`, `ABSTAINED`.
5. **Cost** (integer units): backbone once if any observer was consulted, plus each consulted head by cost class, plus the tier reached. `DIRECT` costs 0 and consults nothing.

Signals a condition may read: `obs.<fact>`, `actor`, `action.name`, `authority.granted`, `authority.forbidden`, `authority.flag.<name>`, `<alias>.top_label`, `<alias>.top_ppm`, `<alias>.margin_ppm`, `<alias>.p.<LABEL>`. Escalation rules cannot read the action or the grant — nothing has been proposed yet.

## How "proposes ≠ owns" is enforced

At load time (a policy that breaks these never runs):

- An `ALLOW` rule must require `authority.granted == true` as a top-level `all` child. A neural signal may only narrow a grant.
- An authority rule that reads observer signals must declare them, exactly, in `declared_neural_inputs`; the receipt lists `neural_inputs_used`.
- Defaults never act: `default_escalation`, `on_incomplete_evidence` and `on_require_escalation` are non-proceed labels; `default_authority` is DENY or REQUIRE_ESCALATION (the schema enum has no other values).
- `DIRECT` is the no-model tier: a literal action, and its condition may not read observers.
- `USE_OBSERVER_SET` must depend on an `agree` predicate. `ABSTAIN` must cite an observer whose contract allows abstention.
- Only a `CHOICE` observer with `PROPOSES_ACTION` can propose an action. No `authority_class` value says a neural output owns authority.

At run time: certainty (1,000,000 ppm) cannot turn a missing grant into an allow; forbidden beats granted; a missing observer is never an action; the same holds for the `DIRECT` tier.

## Determinism rules

- **No floats anywhere.** Probabilities, thresholds and costs are integer ppm (0..1,000,000). A model's floats are quantized once, at the boundary, by `canon.quantize_probabilities` — exact rationals and largest-remainder rounding, so the result is the same on every machine.
- Strings and keys are printable ASCII; integers are within ±(2^53−1); no wall-clock time in any record (time belongs to the Kammi journal envelope).
- Canonical form: sorted keys, no whitespace, ASCII escapes. Input files may use any key order, whitespace or line endings.
- Identity is content-derived: `sha256("s15-<kind>-v1\0" + canonical body without its id)`. Ids are checked on load, so a tampered or edited record is refused.
- Loader refuses duplicate keys, floats, NaN, BOM, invalid UTF-8, non-ASCII text.

## Decisions I made that you should review

These go beyond the charter or fill a gap in it. None is hidden in the code; each has a test.

1. **Integer ppm, not floats.** Chosen so byte-identity cannot depend on float formatting or a second implementation's rounding.
2. **A `RuntimePolicy` record.** The charter's seven records name rules but have nowhere to put them; the runtime needs an ordered rule set, defaults and costs. It is the eighth record and is content-identified like the others.
3. **Thresholds live in the policy, not the bundle.** This follows the bundle field list (no threshold field) and means retuning a threshold never changes an observer's identity.
4. **Extra fields.** `name` (a human label) on `DecisionContract` and `ObserverBundle`; `schema` on every record; `confidence_signal` and `rule_id` on `EscalationDecision`; `policy_id`, `rule_id` and `neural_inputs_used` on `AuthorityDecision`. `tests/test_schemas.py` pins the charter fields and lists these extras, so a later change is a visible diff.
5. **`question` is an identifier**, not free text (the "no free-form" rule applied to the question field too).
6. **`ABSTENTION` contracts need not contain a `NONE` label** — BANK-v1's own decision head is `ACT/ASK/ABSTAIN` (a CHOICE) and its reason head has 11 labels. The fixtures include a `NONE` label only because the fixture policy's abstain rule uses it.
7. **A missing consulted observer fails closed even if a later rule would have matched**, and evaluation runs to the end of the rule before the override, so its cost counts every head that was consulted.
8. **`REQUIRE_ESCALATION` resolving to `ASK_HUMAN` is disposition `ASKED`**, the same as an escalation-stage ask; the handed-over label's cost is added.

## What C0 proves, and what it does not

**Proves (for this implementation):**
- Golden gate: all 14 cases reproduce their stored receipt byte for byte, in-process and in separate processes under `PYTHONHASHSEED` 0 / 1 / 4242 / random, another working directory, `-O`, `-X utf8=0`, and after reformatting or reordering every input file.
- Every one of the seven escalation tiers and all three authority effects is reached by the golden cases and by a seeded 2,500-case fuzz that also checks: nothing is ever `EXECUTE_ALLOWED` unless it was granted, not forbidden and in the catalogue; a missing consulted observer always ends in `ASKED`; cost is consistent.
- The tests can fail: 17 of 18 deliberate sabotages of the runtime (ignoring forbidden, ignoring the grant, failing open on a missing observer, UNKNOWN-as-TRUE, default-ALLOW, dropped id check, dict order leaking into bytes, …) were caught. The one survivor is an equivalent mutant (a double guard against floats).

**Does not prove:**
- Nothing about whether observers are *good*. The fixture observers are invented, with hashes of fixture strings, not weights. That is C1's question.
- Cross-language identity. The format is designed for it (ASCII, integers, sorted keys) but only one implementation exists; a second one reproducing `GOLDEN.sha256` would be the real test.
- Behaviour on CPython versions other than 3.13.15 / Windows, which is what it was run on.

## Not in C0 (by charter)

Model execution, dynamic GLiClass schemas, latent scratchpads, memory retrieval, cached action embeddings, a learned controller, Kammi workspace integration, 1.2B escalation, tool execution.

## Pointing at C1

C1 plugs the existing 230M Rung 0 observers into this runtime by producing real `ObserverBundle`s and a real `DecisionVector`. What C1 will need, from the BANK-v1 Rung 0 README as pasted into the session (that README is not in this repo, so check these against the source before relying on them):

- Backbone `LFM2.5-230M-Base`, revision `9d2be55`.
- Surfaces carried forward: midpoint+final, final+mean, layer −4, full mean. First-token is a dead control.
- Decision head is `ACT/ASK/ABSTAIN` (CHOICE); reason head has 11 labels. Best surfaces: decision accuracy ≈0.666, macro-F1 ≈0.498, ASK recall ≤0.13.
- Calibration and coverage-versus-accuracy are not measured yet; C1's thresholds cannot be chosen honestly until they are.
- The TEST split has been opened twice, so any C1 gate needs a fresh sealed split.
- The normalization and calibration hashes in a bundle must be hashes of the real centre/scale and calibration parameters; `calibration.method` is `NONE` until a calibrator exists.

## Layout

```
s15/canon.py     canonical bytes, identity, strict loader, quantizers
s15/schema.py    the strict JSON Schema subset validator
s15/policy.py    signals, three-valued conditions, load-time checks
s15/model.py     records, id/compatibility checks, World, policy verification
s15/runtime.py   run() and replay()
s15/__main__.py  the CLI
schemas/         generated; fixtures/ generated + golden receipts; tests/; tools/
evidence/        gate reports (git-ignored)
```
