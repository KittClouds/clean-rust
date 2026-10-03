# BANK-V1 POSTMORTEM — historical audit, 2026-09-30

**Status: HISTORICAL RECORD. BANK-v1 is sealed and is NOT being modified.**

This artifact exists so that BANK-v1's known defects and quirks are documented rather than
silently patched. Nothing in `experiments/ff-s15-bank-01/src/`, `releases/BANK-v1/`, or
`seed-registry-v1.json` was touched to produce this file. No v1 gate was fixed in place.

The v1 science that came out of this bank remains valid as history. What follows is a catalogue
of where the *instrument* was weaker than its seal claimed, so that the next generation does not
inherit the same blind spots.

---

## 0. What v1 was built to be, and what it was later asked

This distinction is load-bearing and must not be rewritten.

> BANK-v1 was built as a **state/action stress bank**. The 60/40 generator choice on the MISSING
> branch was **intentional** under that charter: the bank was meant to exercise a controller over
> a spread of decision labels, not to make any one label a deterministic function of the record.
>
> The failure was **not** in the generator. The failure was that v1 was **later asked a different
> scientific question** — *is ASK structurally derivable from the observable world?* — for which
> the v1 label contract was simply the wrong instrument.
>
> Consequence: several items below are **not** v1 bugs. They are **v1 design choices that became
> defects under a question v1 was never chartered to answer.** BANK-v2 is a new generation
> designed for the new question, not a repair of v1.

Each finding below is tagged accordingly:

- `[INSTRUMENT]` — the seal/verifier was weaker than it appeared. Applies regardless of charter.
- `[CHARTER]` — correct for v1's charter, wrong for the derivability question. Not a v1 bug.
- `[SCOPE]`  — v1 simply did not build this. A gap, not a defect.

---

## 1. The headline finding: ASK was not a function of the world record

`src/worldgen.py:196-199`, MISSING mode:

```python
if len(missing) == 1 and r2.random() < 0.6:
    decision, selected, abstain_reason = "ASK", {"type":"REQUEST","args":{"fact":missing[0]["fact_id"]}}, None
else:
    decision, selected, abstain_reason = "ABSTAIN", None, "INSUFFICIENT_EVIDENCE"
```

Both branches remove **the same fact** and produce **the same `missing_information`**. Only the
decision differs, and it is decided by `random.random() < 0.6`. Measured in the sealed data:

| split | ASK | ABSTAIN via MISSING | total MISSING |
|---|---|---|---|
| TRAIN | 5,724 | (folded into INSUFFICIENT_EVIDENCE) | — |

Independent confirmation of the resulting unlearnability, from the downstream sandbox
(`experiments/ff-s15-x0-graph-sandbox-01/RESULTS.md` §2): 978 ASK vs 641 ABSTAIN among 1,619
worlds with a removed fact; *"Any system that reads the gap predicts ASK and is wrong on the 641."*

### 1b. The "unneeded removal" figure, with its exact definition

A later figure from the same sandbox: **737 of 978 ASK-labelled DEV worlds** still had a plan that
BANK's own simulator could find — or an already-satisfied goal — *after* the removed fact was taken
out. That is **737/978 ≈ 75%** of `ASK` rows where the removed fact was not actually needed for the
goal to remain reachable.

**Definition, stated precisely so the number is not over-read:** "unneeded" here means *the goal
remained reachable under the v1 simulator after deletion*. This is **not** a minimal-support
notion. It is weaker than "this fact is in every minimal support of the answer", and it is a
statement about v1's simulator rather than about the v2 fact language.

It is recorded here as history and as motivation. It is **not load-bearing** for any v2 rule: the
v2 `required_facts` machinery (§3.1 of the BANK-v2 freeze) is specified from minimal supports
independently of this measurement.

**`[CHARTER]`** The label is a coin flip by construction. v1 was chartered as a stress bank, so a
mixed label spread was acceptable *as a stress condition*. It is fatal to the derivability
question, which needs ASK to be a **derived** quantity.

### 1a. Second, independent ASK defect (not previously catalogued)

Every ASK row's `selected_action` is `{"type":"REQUEST"}`, but `REQUEST` is **never present in
`available_actions`**. Verified across all 145,000 sampled worlds:

| decision | selected type | present in `available_actions`? |
|---|---|---|
| ASK | REQUEST (7,141 of 7,141) | **no — 7,141 of 7,141** |
| ACT | NOOP / MOVE / ACTIVATE | yes |

`available_actions` only ever contains `MOVE`, `ACTIVATE`, `DEACTIVATE`, `WAIT`, `NOOP`
(`worldgen.py:142-152`). So the ASK label is not merely undeclared, it names an action the
available-action set never offers. No information-acquisition action exists in v1's action space
at all. This is the root cause of the second downstream finding in
`experiments/ff-s15-ask-01/RESULTS.md`: ASK collapses to a pure negative-evidence task.

---

## 2. Abstain reasons that are conventions, not physics

### 2a. IMPOSSIBLE / NO_VALID_ACTION were not verified against the simulator

`src/worldgen.py:218-225` (IMPOSSIBLE mode) appends a **doubled BLOCKED pair** sealing the goal
location, then picks a reason from `["NO_VALID_ACTION", "IMPOSSIBLE_GOAL"]` **without consulting
the simulator**:

```python
state.append({"id": "f_seal",  "pred": "BLOCKED", "args": [loc_ids[0], goal_loc]})
state.append({"id": "f_seal2", "pred": "BLOCKED", "args": [goal_loc, loc_ids[0]]})
decision, selected, abstain_reason = "ABSTAIN", None, r2.choice(["NO_VALID_ACTION", "IMPOSSIBLE_GOAL"])
```

The comment on line 222 says *"remove switches so gate can never open if gated"* — but **no
switches are removed**, and the doubled-BLOCKED construction does not seal the goal against a
detour in general.

Downstream measurement (`ff-s15-x0-graph-sandbox-01/RESULTS.md`): *"721 of 856 of them carry a
doubled BLOCKED pair, and a detour usually exists (the simulator finds a plan in most). A BLOCKED
count of two or more occurs in exactly those labels and no others (0 elsewhere)."* So the label is
a **perfectly learnable count artifact** that does not track the underlying unreachability.

Also note the two reasons are drawn from one coin flip, so `NO_VALID_ACTION` and `IMPOSSIBLE_GOAL`
are **not distinguishable from each other** even in principle.

**`[INSTRUMENT]` + `[CHARTER]`** The label is not derived from truth, and it is a count giveaway.

### 2b. The reason firewall destroys the signature it was meant to create

`src/worldgen.py:264-268`:

```python
if split in ("TRAIN","DEV","TEST-IID","TEST-LEXICAL","TEST-ENTITY","TEST-TEMPLATE","TEST-COMPOSITION","TEST-DEPTH"):
    if abstain_reason in RESERVED_ABSTAIN_TRAIN_EXCLUDE:
        decision, selected, abstain_reason = "ABSTAIN", None, "INSUFFICIENT_EVIDENCE"
```

Verified effect on TRAIN — the train-visible reason vocabulary is only six values, and three
test-only constructions are silently folded into the catch-all:

| reason | TRAIN count | fate |
|---|---|---|
| INSUFFICIENT_EVIDENCE | 32,700 | includes 3 folded test-only constructions |
| CONFLICTING_EVIDENCE | 9,444 | genuine |
| UNKNOWN_ENTITY | 5,065 | genuine |
| UNKNOWN_TARGET | 5,037 | genuine |
| NO_VALID_ACTION | 3,299 | not simulator-verified (§2a) |
| IMPOSSIBLE_GOAL | 2,375 | not simulator-verified (§2a) |
| GOAL_SATISFIED | 0 as ABSTAIN | appears on ACT rows only (§2c) |
| AMBIGUOUS_REFERENCE | — | **folded** in TRAIN/DEV |
| MULTIPLE_UNRESOLVED_ACTIONS | — | **folded** in TRAIN/DEV |
| OUT_OF_SCOPE | — | **folded** in TRAIN/DEV |

Downstream: *"**No structural signature** (1597 worlds, 8.0% of DEV). ABSTAIN/INSUFFICIENT worlds
with a complete, unremarkable record (BANK's reserved reasons folded into INSUFFICIENT_EVIDENCE).
Nothing in the record separates them from solvable worlds."*

**`[INSTRUMENT]`** Folding distinct reasons into one catch-all **manufactures** unlearnable rows.
This is a self-inflicted wound, independent of charter: the intent (protect train from test-only
constructions) was sound, the mechanism was not.

### 2c. Label-consistency defect: ACT rows carry an abstain reason

`src/worldgen.py:184-185` (ALREADY_TRUE mode) sets `decision="ACT"` **and**
`abstain_reason="GOAL_SATISFIED"`. `verify.py:53` only rejects this combination when
`decision == "ABSTAIN"`, so it passes the seal. Measured:

| split | ACT rows with non-null `abstain_reason` |
|---|---|
| TRAIN | 9,998 of 56,356 |
| DEV | 1,632 of 9,320 |

**`[INSTRUMENT]`** A populated reason field on a non-ABSTAIN row is an inconsistent record, and
any consumer keying on `abstain_reason` without also keying on `decision` will mislabel 17.7% of
TRAIN ACT rows.

---

## 3. Nine of fourteen declared action types can never be legal

`schema.py` declares 14 actions: `MOVE, ACTIVATE, DEACTIVATE, TAKE, DROP, TRANSFER, OPEN, CLOSE,
SELECT, ASSIGN, REQUEST, VERIFY, WAIT, NOOP`. But `worldgen.py:142-152` only ever populates
`available_actions` with five: `MOVE, ACTIVATE, DEACTIVATE, WAIT, NOOP`.

Measured over TRAIN + DEV + TEST-ABSTENTION (145,000 worlds):

| action type | in `available_actions` | ever a truth ACT action |
|---|---|---|
| WAIT | 145,000 | no |
| NOOP | 145,000 | 31,735 |
| MOVE | 145,000 | 23,441 |
| ACTIVATE | 145,000 | 10,500 |
| DEACTIVATE | 145,000 | no |
| TAKE, DROP, TRANSFER, OPEN, CLOSE, SELECT, ASSIGN, REQUEST, VERIFY | **0** | **0** |

`simulator.py` implements preconditions and effects for TAKE/DROP/TRANSFER/OPEN/CLOSE (lines
55-64, 88-97), but the generator never emits them, so that code is **unreachable in v1**. Truth
ACT actions are only `NOOP`, `MOVE`, `ACTIVATE` — independently confirmed in
`ff-s15-c4a-action-safety-01/RESULTS.md`.

**`[SCOPE]`** This is not a code bug: the schema and the generator agree, and the seal passed
correctly. It is a **coverage gap** — the action algebra in the contract is far wider than the
executable world, and no gate checked the difference.

### 3a. Correction: there is no `g["obj"]` / `g["object"]` simulator mismatch

An earlier draft of this audit attributed the dormant action types to a **key-name disagreement**
between the generator and the simulator (`g["object"]` in one, `g["obj"]` in the other). **That
attribution is wrong and is withdrawn.**

Verified directly against the sealed source:

- `src/simulator.py:55-64` (`_action_legal`) and `src/simulator.py:88-97` (`apply_action`) both
  read the argument key **`"object"`**, consistently, for `TAKE`, `DROP`, `TRANSFER`, `OPEN`, and
  `CLOSE`. There is no `"obj"` key anywhere in the simulator's action handling.
- `src/worldgen.py` contains **no** `TAKE`, `DROP`, `TRANSFER`, `OPEN`, or `CLOSE` emission at
  all, so there is no second spelling to disagree with. The generator's action vocabulary stops at
  `MOVE`, `ACTIVATE`, `DEACTIVATE`, `WAIT`, `NOOP` (`worldgen.py:142-152`).

So the simulator is **internally consistent** and the correct diagnosis is the one in §3: a
**coverage hole**, not a spelling bug. The dormant handlers are unreachable because nothing
constructs their arguments, not because the argument names are wrong.

This correction is retained deliberately: the distinction between "the code disagrees with itself"
and "the code is never called" matters, because only the second is fixed by a coverage gate. BANK-v2
addresses it with the per-action-type **coverage receipt** (six cells, including `illegal` and
`truth_optimal`), not with a key-name audit.

---

## 4. Seal-gate weaknesses `[INSTRUMENT]`

All 25 gates report `PASS` in `releases/BANK-v1/manifests/seal-gates.json`. Five of them do not
establish what their names imply.

| gate | line | defect |
|---|---|---|
| G11 | `seal.py:108` | `gate("G11", True, "lexical pool disjoint by construction")` — **hardcoded True**, never computed |
| G12 | `seal.py:109` | `gate("G12", True, "entity combo forced in TEST-ENTITY")` — **hardcoded True** |
| G17 | `seal.py:118` | `gate("G17", True, "joint stratum present")` — **hardcoded True** |
| G19 | `seal.py:123` | re-tests the *same* `lit` list as G18 (line 122) under the name `textual_dup_proxy` — **textual dedup is never actually performed** |
| G01, G03, G04, G08, G09, G14, G15, G16, G20 | `seal.py:95-128` | inspect only the **first 100-200 rows** of each split, not the full set |

So "25 gates PASS" overstates coverage. Nine gates are sample-limited and three are assertions of
nothing. G19 is a duplicate of G18 with a misleading name.

### 4a. Graph-isomorphism collisions: reported, never removed

`releases/BANK-v1/manifests/release.json`:

```json
"unique_fill": {
  "version": "v1-skip-later-literal-dups-global-order",
  "skipped_lups": 4,
  "graph_iso_collisions": 7981
}
```

`FLIGHT_DIRECTIVE.md:28-30` states the done-condition honestly (*"literal dups = 0; graph-iso
collisions reported"*), so v1 is internally consistent. But the consequence matters for
interpretation: **7,981 cross-split structural collisions exist**, meaning a TEST-world
isomorphic to a TRAIN-world can occur. Any claim that a v1 holdout is structurally disjoint is
unsupported. Literal duplicates were eliminated (4 skipped during unique-fill; G18/G25 = 0).

---

## 5. Targets that do not exist in v1 `[SCOPE]`

From `src/projections.py`, the supervision heads are: decision, abstain reason, policy
(action+args), NLI 3-way, entity, relation, transition (next state), evidence, difficulty.

Two targets that BANK-v2's world model implies are **absent**:

- **action applicability** — `legal_actions` and `available_actions` exist in the world record but
  are never projected into `labels`. Downstream had to rebuild it
  (`ff-s15-c0-runtime-01/fixtures/contracts/applicable.json`).
- **edge existence** — not a v1 target. Downstream had to construct the ordered-pair edge
  universe from sealed worlds (`ff-s15-cg0-edge-pruning-01`).

Also dead: `projections.py:25` builds a `five_head` dict that `build_bank.py:90-93` never writes.

---

## 6. What the surviving conclusion actually was

From `experiments/ff-s15-STATUS.md:24-28`, preserved here so the postmortem is not read as a
refutation of the branch:

- System 1.5 on BANK learned **a selective NOOP lane, not a general action lane** — ~96% of
  "correct executions" were NOOP; on the primary surface the frozen rule hit 25.9% of truth-NOOP
  rows and **0.9%** of truth MOVE/ACTIVATE rows.
- The declared surviving contribution is **the architecture** — typed observer + confidence gating +
  escalation + deterministic authority + replayable receipt — **not BANK's policy capability**.
- The branch was **CLOSED** by program-owner decision, 2026-09-29.

This postmortem is consistent with that: the architecture is the product, the bank was the
instrument, and the instrument's limits are now documented.

---

## 7. Carry-forward list for BANK-v2

Each item below is a v2 **requirement**, derived from a finding above. Cross-referenced to the
v2 freeze document in `experiments/ff-s15-bank-02/`.

| # | v1 finding | v2 requirement |
|---|---|---|
| C1 | ASK = coin flip, §1 | Missingness is a **declared three-way taxonomy**; the decision is derived from the observation + information-policy record, never sampled |
| C2 | REQUEST never in `available_actions`, §1a | The action space is **closed**: every action named by any target is present in the available set with an acquisition path |
| C3 | IMPOSSIBLE/NO_VALID_ACTION unverified, §2a | Every abstention reason is **simulator-derived**, and carries a typed witness; a reason with no witness regenerates the world |
| C4 | reason firewall folds signatures, §2b | **No reason folding, ever.** A convention is expressed as an explicit policy field, not a post-hoc rewrite |
| C5 | ACT rows carry abstain_reason, §2c | Invariant: `abstain_reason` is non-null **iff** `decision == "ABSTAIN"` |
| C6 | 9 of 14 actions unreachable, §3 | Gate asserts **every declared action type appears legally** in generated worlds, with a round-trip check |
| C7 | 3 hardcoded-True gates, §4 | **No hardcoded-True gate.** Every gate computes its predicate from data or fails closed |
| C8 | G19 duplicates G18, §4 | Textual and structural dedup are **distinct predicates** with distinct checks |
| C9 | 9 gates sample 100-200 rows, §4 | Critical invariants are checked on **100% of rows**; sampling allowed only for declared-expensive checks |
| C10 | 7,981 graph-iso collisions, §4a | Collisions are **removed**, or **intentionally stratified** and declared as such per split |
| C11 | no applicability/edge targets, §5 | Applicability and edge-existence become **first-class projected targets** with witnesses |

---

## 8. Integrity statement

- BANK-v1 was **read only** to produce this postmortem. No file under
  `experiments/ff-s15-bank-01/src/`, `releases/`, or `seed-registry-v1.json` was modified.
- All quoted line numbers refer to the state of v1 as of 2026-09-30.
- All counts in §1a, §2b, §2c, §3 were measured directly from
  `releases/BANK-v1/worlds/{TRAIN,DEV,TEST-ABSTENTION}.jsonl`.
- The three hardcoded gates and the G18/G19 duplication were read from `src/seal.py`.
- This artifact carries no v1 release hash and does not re-seal anything.
