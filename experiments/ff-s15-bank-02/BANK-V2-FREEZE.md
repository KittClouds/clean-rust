# BANK-v2 FREEZE — constitution v0.7 (pre-code)

**Experiment:** `FF-S15-BANK-02` **Release:** `BANK-v2` **Status:** `FROZEN_PRE_CODE`
**Date:** 2026-09-30 **Version:** 0.7 (supersedes 0.6, accepted at
`92687c7756470389d7394a058cfb58da83553a3e03dc695549cf3b48800d306b`) **Branch:** `OPENED 2026-09-30 — new generation`
**Modifies BANK-v1:** no. **Reopens BANK-v1:** no. **Supersedes v1 scientifically:** no.

**Scope of v0.7:** written **before** the corresponding code, per §11, while building against v0.6. It
records six builder-forced clarifications (G1–G6, §10.7) found when the generator first ran: the `WAIT`
legality cell, the subject of a transitive relation requirement, obligation sources for opened closed
slots, the report/conflict/uncertainty conventions, the observation-sufficiency check, and the
step-1a query convention. **No decision-taxonomy change.** Gate count stays 18. Code remains authorized
(§0.5) and continues against this version once it seals.

Machine-readable companion: `bank-v2-objects.json`, sha256 in `bank-v2-objects.sha256`.
Prior versions are archived byte-for-byte in `lineage/`; `tools/check_freeze.py` re-hashes them.
v1 audit: `experiments/ff-s15-bank-01/BANK-V1-POSTMORTEM-2026-09-30/POSTMORTEM.md`.

---

## 0. Standing, scope, and lineage

### 0.1 BANK-v2 is a new generation, not a repair of BANK-v1

> BANK-v1 was built as a **state/action stress bank**. Its mixed label spread was intentional
> under that charter. The failure was that v1 was **later asked a different scientific question** —
> whether ASK is structurally derivable from the observable world — for which the v1 label
> contract was the wrong instrument.
>
> BANK-v2 is a **new bank designed for the new question**. It is not a corrected v1.

BANK-v1 stays sealed and untouched. Its defects are recorded in the postmortem and treated as
**historical fact, not as a work queue**. No v1 file is edited to produce v2.

### 0.2 Lineage, stated precisely

This wording is deliberate and must not drift:

- BANK-v2 **supersedes BANK-v1 as the active bank-generation program.**
- BANK-v2 **does not** amend, repair, supersede evidence from, or reopen BANK-v1.
- BANK-v1 **remains a valid historical instrument** for the question it was built to ask.

### 0.3 The question BANK-v2 exists to answer

> Given **only** what an agent can observe, under an **explicitly declared** information policy,
> can it determine — with a witness — what is true, what is next, what it may do, what it should
> ask for, and when it must **decline** or **escalate**?

The last two are distinct controls (§3.4, §6), not one "abstain" label.

### 0.4 Legal boundaries (inherited, non-negotiable)

- **NO** frozen-LFM features, probe scores, adapters, or downstream accuracy during construction.
- **NO** selecting generators because a model likes them.
- **NO** contamination from other branches into bank examples or splits.
- **NO** external rows, answers, entity ids, or benchmark-specific labels in core (§7).
- Builders see only inputs after freeze; terminal truth opens once, under a later contract.

### 0.5 Code authorization

This freeze pins semantics. **Code is authorized from the moment v0.6 sealed and remains authorized under v0.7** (`tools/check_freeze.py`
reports `ALL_CHECKS_PASS` and the sha256 sidecar is written), on the program owner's ruling of
2026-09-30: *"Fold O11 into v0.6 first, then plan/build from a fully coherent freeze."* Any change to
§1–§9 requires a versioned amendment **before** the corresponding code changes (§11); a code change
that would alter §1–§9 semantics without one is a defect.

---

## 1. The five-block world record, plus the action namespace

A BANK-v2 world is one canonical JSON object partitioned into blocks. The partition separates
**what is true**, **what is seen**, **what may be learned**, **what may be done**, **how actions
are named**, and **what is claimed**.

```
WORLD_TRUTH        — latent world. Authoritative. Never rendered, never revealed.
OBSERVATION        — what the agent receives. A function of WORLD_TRUTH + render policy.
INFORMATION_POLICY — which unobserved facts are requestable, at what cost, from what source.
ACTION_POLICY      — which environment actions are available, permitted, costed, escalatable.
ACTION_NAMESPACE   — the three action namespaces and the typing rules between them (§2).
TARGETS            — the claim set, each nontrivial target carrying a typed witness (§5).
```

`INFORMATION_POLICY` and `ACTION_POLICY` stay separate by ruling: conflating "can I get it?" with
"can I do it?" reproduces the v1 ambiguity.

### 1.1 `WORLD_TRUTH`

| field | meaning |
|---|---|
| `entities[]` | `{id, name, type, aliases[], introduced}` |
| `relations[]` | typed structural edges `{subj, pred, obj}` over the frozen fact language (§1.6) |
| `state` | fact base at `t = 0`: `{id, pred, args[], value?}` |
| `temporal_state[]` | `{fact_id, valid_from, valid_to, observed_at}` — discrete ticks (§4) |
| `transition_system` | action schemas `{type, preconditions[], effects[], inverse_of?, cost}` |
| `goal` | `{pred, args[], value?, required_facts}` — **typed**, see §3.1 |

`required_facts` is a five-scope object, not a list. This is the X0 correction (§3.1).

### 1.2 `OBSERVATION`

| field | meaning |
|---|---|
| `visible_facts[]` | fact ids actually exposed |
| `hidden_facts[]` | fact ids withheld |
| `supported_facts[]` | fact ids the observation supports — each either visible or derived from visible facts **with a derivation witness** |
| `uncertain_evidence[]` | `{fact_id, confidence, channel}` — disclosed unreliability |
| `aliases{}` | surface-form → entity id bindings |
| `rendered_text`, `renderer_id`, `renderer_family_id` | surface realization and its family (§3.3) |

`supported_facts` is the basis of the missingness subtraction (§3.2). It is **declared
explicitly**, never implied, so the algebra's arithmetic is well-defined.

### 1.3 `INFORMATION_POLICY`

| field | meaning |
|---|---|
| `requestable[]` / `non_requestable[]` | partition of acquirable vs never-acquirable |
| `acquisition_cost{}` / `source_constraints{}` | cost and provenance per fact |
| `request_objects[]` | **generated** request objects; each names the fact or query it can reveal |
| `policy_id` | policy variant identity, so a paired world can flip one bit |

`request_objects` is the v2 fix for the v1 `REQUEST`-with-no-surface failure (postmortem §1a):
every `ASK` resolves to one of these. Since v0.6 a request object names a **requirement** (§3.1) and
the **repair fact set** it reveals together, `{request_id, requirement_id, reveals: [fact ids]}`, so one
ask can acquire a multi-fact repair (*where is obj_7?* reveals `HOLDS` and the holder's `AT` together).

### 1.4 `ACTION_POLICY`

| field | meaning |
|---|---|
| `available_actions[]` | grounded environment action instances, **closed** |
| `permissions{}` | permitted / denied, with the denying authority named |
| `action_costs{}` | cost per action type |
| `escalation_rules[]` | conditions under which the correct disposition is `ESCALATE` |
| `conventions[]` | declared policy conventions |

`conventions[]` and `escalation_rules[]` are where v2 parks what v1 smuggled into labels. A
convention is a **world field**, so a paired world can hold it fixed while varying something else.

### 1.6 Relation vocabulary — two layers (O2, closed in v0.3)

v2 does **not** enumerate a large semantic ontology. It freezes a **two-layer** vocabulary: a
closed operational set for the simulator, plus one generic registered carrier for everything else.

#### Layer A — six operational world predicates

```text
AT(entity, location)                    current spatial location
CONNECTED(location_from, location_to)    directed traversable topology in principle;
                                        bidirectional connection is TWO facts
BLOCKED(location_from, location_to)      directed traversal prohibition;
                                        does NOT delete CONNECTED
HOLDS(agent, object)                     agent currently possesses object
CONTAINS(container, object)              container currently contains object
STATE(entity, attribute, value)          generic state slot
```

`STATE` is the extension point:

```text
STATE(door_1,   openness,   open)
STATE(switch_2, activation, active)
```

**`OPEN`, `CLOSED`, `ACTIVE`, `INACTIVE` are values of `STATE`, never separate predicates.** The
predicate set must not grow every time a device is invented.

These six make all nine environment actions physically meaningful:

| action | predicate footprint |
|---|---|
| `MOVE` | `AT`, `CONNECTED`, `BLOCKED` |
| `TAKE` | `AT`, `HOLDS` |
| `DROP` | `AT`, `HOLDS` |
| `TRANSFER` | `AT`, `HOLDS` |
| `OPEN` | `STATE`, `CONTAINS` |
| `CLOSE` | `STATE`, `CONTAINS` |
| `ACTIVATE` | `STATE` |
| `DEACTIVATE` | `STATE` |
| `WAIT` | — |

Worked examples as ruled:

```text
TAKE       AT(agent,L), AT(object,L)  →  HOLDS(agent,object),  remove AT(object,L)
TRANSFER   HOLDS(A,obj), AT(A,L), AT(B,L)  →  HOLDS(B,obj),  remove HOLDS(A,obj)
```

Container-mediated variants use `CONTAINS` and `STATE(container, openness, open)`.

#### Layer B — one generic registered carrier

```text
REL(source_entity, relation_id, target_entity)
```

with every `relation_id` drawn from a **generated, synthetic** relation registry:

```text
relation_id          bank-owned, never imported, no lexical content
domain_type          entity type constraint on source
range_type           entity type constraint on target
directionality       DIRECTED | SYMMETRIC
transitivity         NONE | TRANSITIVE
inverse_relation_id  optional
split_scope          TRAIN_VISIBLE | TEST_RELATION_ONLY | SHARED
```

**One bank-wide table, not per-split tables (v0.4).** There is one identity and one hash lineage.
G18's "existing registry entry" check is a lookup on `(relation_id, split)`.

Three constraints:

1. **Inverse pairs share a scope.** A `TEST_RELATION_ONLY` relation whose inverse is
   `TRAIN_VISIBLE` is a **schema error** — if the inverse is visible in train, the model has
   effectively seen the relation, and the holdout leaks.
2. **`TEST-RELATION` holds out property combinations, not just ids.** A member is valid only if its
   property combination (directionality, transitivity, `domain_type`, `range_type`) does **not**
   occur in train. Otherwise the split varies id and semantics at once, and a failure cannot be
   attributed to either. A separate **`TEST-RELATION-PROPERTY`** split is *named* for the
   property-combination holdout and deliberately **not** in the v0.4 budget.
3. **Ids carry no lexical content.** No morpheme, substring, or ordering may reveal the rendered
   relation word, or the id itself becomes the leak.

A canonical world holds `REL(e17, r03, e22)`; a renderer may express `r03` as *supplies*, *provides
material to*, or the inverse *receives goods from*, depending on family. This single carrier
supplies every relation axis the bank needs — relation-type OOD, role binding, inverse relations,
composition, isomorphism, multi-hop reasoning, surface paraphrase — **without adopting anybody's
ontology**.

**Symmetric normalization (frozen rule).** A `SYMMETRIC` fact is stored **exactly once**,
normalized to ascending entity ordinal; the mirror is **derived on demand, never stored**. Two
conditions make this safe:

- **S1** — entity ordinals are **shuffled within each world** and **uncorrelated with entity type**,
  so ascending order carries no signal;
- **S2** — symmetric-relation scoring is **unordered**, so a correct answer stored in the other
  direction is not penalized.

This is deliberately *different* from `CONNECTED`/`BLOCKED`, which stay directed with bidirectional
expressed as two facts.

#### Derived, never primitive

`BEFORE` and `AFTER` are **not base predicates**. They are targets derived from ticks and validity
intervals (§3.5), so a temporal label can never contradict the clock. Transitive closure over
`TRANSITIVE` relation ids is a **derived view** and is never written into world truth — a closure
inserted as facts would be unlabeled facts with no witness.

#### Forbidden as world predicates

```text
SUPPORTS   CONTRADICTS   REQUIRES   ACHIEVES   CAUSES   APPLICABLE_TO   REQUESTABLE
```

These are **not** canonical world predicates. Each has an owning layer:

| relation | proper home |
|---|---|
| `SUPPORTS`, `CONTRADICTS` | observation / evidence graph |
| `REQUESTABLE` | information policy |
| `REQUIRES`, `CAUSES`, `ACHIEVES`, `APPLICABLE_TO` | action schema / derived graph interface |

**Why this matters enormously:** otherwise BANK-v2 leaks its own solution graph into its world
truth, and a reason head becomes a lookup rather than a derivation.

#### One fact language across the bank

Every element of **all five** `required_facts` scopes must be a canonical fact object built only
from:

```text
AT   CONNECTED   BLOCKED   HOLDS   CONTAINS   STATE   REL
```

plus temporal qualifiers where applicable. No scope invents its own predicate language, and only
`required_facts.query` participates in the ASK algebra (§3.1, §3.2).

G18 (§9.5) enforces all of this at 100% coverage.

### 1.7 Openness is declared per slot, not per predicate (O10, closed in v0.5)

Declaring openness per predicate **contradicts itself** for object location. An object's location
can be `AT` a place, `HOLDS`-ed by an agent, or `CONTAINS`-ed by a container. If `AT` is open while
`HOLDS`/`CONTAINS` are closed, a missing location is **askable** when the object would be at a
place and **silently false** when it would be held or contained. So openness attaches to a **slot**:

| slot | openness | members | rule |
|---|---|---|---|
| `object_location` | **OPEN** | `AT`, `HOLDS`, `CONTAINS` | **disjunctive** — missing only when **no** member is present; if one member is present the others are closed-world false |
| `entity_attribute` | **OPEN** | `STATE` | keyed by `(entity, attribute)` |
| `traversable_edge` | CLOSED | `CONNECTED` | unless a slot marker says otherwise |
| `prohibited_edge` | CLOSED | `BLOCKED` | unless a slot marker says otherwise |
| `general_relation` | CLOSED | `REL` | a registry entry may set `required_slot: true`, making that relation an **open** slot |

`REL` is closed by default because an unasserted relation means not asserted — unless the relation
is semantically obligatory for its domain and range (an owner-of, say), which the registry marks
explicitly.

The disjunctive `object_location` rule is **slot-completeness logic**, and it is the pattern that
lifted ASK recall in the sandbox.

**Hidden facts and closed slots (v0.6).** A CLOSED slot reads an absent fact as *false*. So a fact of a
CLOSED slot may be **hidden only if** the world carries a slot marker that opens that slot for that
world; otherwise hiding it would silently turn a true fact into a false one. The generator may not hide
closed-slot facts without the marker, and G12 checks this at 100%.

**Schema rule.** Every canonical predicate is a member of **exactly one** declared slot or
explicitly closed; an **orphan predicate is a schema error**. All seven predicates are covered:
`AT`/`HOLDS`/`CONTAINS` → `object_location`; `STATE` → `entity_attribute`; `CONNECTED` →
`traversable_edge`; `BLOCKED` → `prohibited_edge`; `REL` → `general_relation`.

---

## 2. The action namespace (O1, closed)

v1 put environment actions, information acquisition, and controller dispositions in **one enum**.
That is precisely how `selected_action = REQUEST` escaped `available_actions` (postmortem §1a).
v2 freezes **three namespaces**:

```text
ENVIRONMENT ACTIONS        INFORMATION ACTIONS      CONTROLLER DISPOSITIONS
  MOVE                       REQUEST                   EXECUTE
  TAKE                                                 NOOP
  DROP                                                 ASK
  TRANSFER                                              ESCALATE
  OPEN                                                  DECLINE_UNAVAILABLE
  CLOSE
  ACTIVATE
  DEACTIVATE
  WAIT
```

Each disposition carries a **typed reference** to a real object in its own namespace:

| disposition | references | constraint |
|---|---|---|
| `EXECUTE` | `environment_action_id` | must be in `available_actions` **and** legal in the current state |
| `NOOP` | `goal_satisfying_witness` | goal already satisfied |
| `ASK` | `request_id` | must resolve to a generated `request_object` naming the unresolved **requirement** and the repair facts it reveals |
| `ESCALATE` | `escalation_policy_ref` + witness | must name a fired `escalation_rules[]` entry |
| `DECLINE_UNAVAILABLE` | `reason` + the reason's typed witness (§5.1) | for the two missing-information reasons: the **requirement** whose every repair contains a fact absent from `requestable`; every other reason carries its own §5.1 witness |

**These v1 patterns are now structurally impossible, not merely forbidden:**

```text
selected_action = REQUEST  while REQUEST ∉ available_actions
a disposition naming an object outside its namespace
EXECUTE referencing an environment action not in available_actions
```

Cross-namespace references are a schema violation, caught by G17 on 100% of rows.

### 2.1 Action coverage receipt (G06, strengthened in v0.2)

O1 also rules: *do not merely verify a simulator handler exists.* For every declared **core
environment action**, the sealed bank must carry a coverage receipt over six cells:

```text
generated
available
legal
illegal
truth_optimal
executed_in_shortest_plan_witness
```

Any declared core action that is **zero in any required cell fails the seal**. This is the direct
answer to v1, where nine of fourteen declared action types were unreachable in generation
(postmortem §3) and truth ACT actions were only `NOOP`/`MOVE`/`ACTIVATE`.

The `illegal` cell matters as much as `legal`: an action type that is *always* legal is not
exercising a precondition system, and one that is *never* legal is dead. Both are seal failures in
one direction or the other.

**`WAIT` exemption (v0.7, G2).** `WAIT` is defined **precondition-free** (§1.6: footprint "—") and is therefore
legal in every state in which it is available, so its `illegal` cell is empty *by definition*, not by
coverage failure. `WAIT` is the **only** declared core action exempt from the `illegal` cell; it must still
be nonzero in the other five, and every other core action must be nonzero in all six. The exemption is a
declared list in the companion (`precondition_free_actions`), so it cannot widen silently.

---

## 3. Typed requirements, the missingness taxonomy, renderer, and time

### 3.1 `required_facts` is typed, not one list (O2, closed)

X0 taught why: **schema completeness and immediate goal need are not the same notion of
"required."** A single flat list collapses them. v2 freezes:

```text
required_facts:
  schema: [...]                  facts for the world to be interpretable at all
  goal:    [...]                  facts for the goal predicate to hold
  plan:    [...]                  facts along a candidate plan prefix
  action:  { <action_id>: [...] } per-action preconditions
  query:   [QueryRequirement]     the obligation set for the information task (§3.1, v0.6)

requirement_scope: SCHEMA | GOAL | PLAN | ACTION
```

The `query` scope **declares its source scope** and is the only scope that drives the
missingness decision (§3.2). The other four are recorded so that v2 can *separately* score
schema-sufficiency and goal-sufficiency — the distinction X0 found is then **measurable rather
than invisible**.

**Fact-language rule (v0.3):** every element in every scope must be a canonical fact object built
only from `AT`, `CONNECTED`, `BLOCKED`, `HOLDS`, `CONTAINS`, `STATE`, `REL` (§1.6), plus temporal
qualifiers. The scopes must not invent their own predicate language.

#### `query` is a set of requirement objects (v0.6, replaces the v0.4 intersection rule)

v0.4 derived `query` as *the intersection of all minimal supports*. That is wrong for a **disjunctive**
slot: where-is-obj may be proven by `{AT(obj,L)}` **or** `{HOLDS(a,obj), AT(a,L)}`; the intersection is
empty, so nothing would be "required" and a deleted `AT(obj,L)` would be labelled irrelevant.
What is required is the **obligation**; its **evidence** is disjunctive. v0.6 (ruling **C**) therefore
freezes a two-level object, and requiredness lives at the obligation level while evidence stays at the
fact level:

```text
QUERY REQUIREMENT
  requirement_id       content-derived: sha256(slot, subject, source_scope), truncated
  slot                 one of the five declared slots (§1.7)
  subject              the slot key:
                         object_location   -> entity id
                         entity_attribute  -> (entity, attribute)
                         traversable_edge / prohibited_edge -> (from, to)    [only if a slot marker opens the slot]
                         general_relation  -> (source_entity, relation_id)   [only if the registry marks required_slot]
  required             true
  support_alternatives an antichain of MINIMAL fact sets; each is a subset of the true facts of
                       WORLD_TRUTH (or derivable from them with a witness) and is by itself sufficient
                       to satisfy the obligation
```

**Where the set comes from.** `required_facts.query` declares a **source scope** (`SCHEMA | GOAL | PLAN |
ACTION`). Take the facts of that scope (for `PLAN`: the preconditions used by the canonical plan prefix —
the lexicographically first shortest plan), keep those whose slot is **open** in this world, and group
them by `(slot, subject)`. Each group is one requirement. Facts of CLOSED slots create no obligation:
their absence is known-false.

**One evaluator, per-slot derivation rules** (single source of truth; it returns the requirement set and
every alternative):

| slot | alternatives for subject `e` whose true value is `L*` |
|---|---|
| `object_location` | `{AT(e,L*)}` if stated; `{HOLDS(a,e)} ∪ alt(loc(a)=L*)` if held (holder location by `AT` only); `{CONTAINS(c,e)} ∪ alt(loc(c)=L*)` if contained, recursively to the **declared nesting depth (≤ 2)** |
| `entity_attribute` | `{STATE(e,attr,v*)}` |
| `traversable_edge`, `prohibited_edge` (open by marker) | the single directed fact |
| `general_relation` (`required_slot`) | the direct `REL`, or, for a `TRANSITIVE` relation id, each chain of `REL` facts reaching the same target (derived, never stored) |

A world may carry **redundant truth** (for example `AT(obj,L)` **and** `CONTAINS(box,obj)`, `AT(box,L)`),
which yields more than one alternative; the generator has a declared redundancy mode so the gates
exercise this case.

**Satisfaction and missingness.** With `Sup = OBSERVATION.supported_facts`:

```text
SATISFIED(r)   iff  some alternative of r is fully contained in Sup
M              =    { r in R(q) : not SATISFIED(r) }          -- unresolved OBLIGATIONS, never absent facts
repairs(r)     =    { A - Sup : A in alternatives(r) }
legal(repair)  iff  every fact in it is in INFORMATION_POLICY.requestable (and acquisition is permitted)
r is REQUESTABLE    iff  it has at least one legal repair; otherwise r is UNAVAILABLE
nonreq         =    { r in M : r is UNAVAILABLE }
chosen repair  =    the legal repair minimizing (total acquisition cost, |repair|, sorted fact ids)
```

So one object-location obligation with three possible evidence forms and none observed is **one**
missing requirement, not three facts. An ASK names that requirement and the chosen repair's facts.

**Three derived fields, never collapsed:**

```text
required_requirements = R(q)                                        the obligations
support_facts         = union of every alternative of every r       facts in at least one minimal support
necessary_facts       = facts f in Sup such that deleting f from Sup makes some requirement
                        unsatisfied (f lies in EVERY currently complete alternative of that r)
```

A fact may be a support fact without being necessary (one member of a **redundant proof**), and a fact
outside every alternative is **irrelevant**. Keeping these three apart is deliberate and is expected to
be scientifically useful later.

**Counterfactual gate (G03/G12, 100%, mechanical, never sampled).** Deletion is applied to `Sup`:

1. for every satisfied requirement, deleting **all facts of all its currently complete alternatives**
   makes it unsatisfied (or changes the answer);
2. deleting a fact **outside every alternative** never changes the answer;
3. deleting **one** support fact while another complete alternative remains is **not** evidence of
   irrelevance (the requirement stays satisfied);
4. every fact claimed in `necessary_facts` passes its own single-fact deletion counterfactual (the
   requirement becomes unsatisfied).

This separates a **globally irrelevant** fact from **one member of a redundant proof**.

### 3.2 The three missingness families (from day one)

Let `M` be the set of **unsatisfied query requirements** and `nonreq` the subset with **no legal repair**
(§3.1). `|M|` counts unresolved **obligations**, not absent facts.

**Precedence: non-requestability dominates cardinality.** If *any* unresolved requirement is
UNAVAILABLE, the answer stays incomplete even after every permitted question is asked — so
`DECLINE_UNAVAILABLE` applies **whatever the count**.

| # | condition | disposition | reason |
|---|---|---|---|
| 2a | `nonreq ≠ ∅`, `\|M\| = 1` | `DECLINE_UNAVAILABLE` | `NECESSARY_MISSING_UNAVAILABLE` |
| 2a' | `nonreq ≠ ∅`, `\|M\| ≥ 2` — **mixed case** | `DECLINE_UNAVAILABLE` | `MULTIPLE_REQUIRED_MISSING_UNAVAILABLE` |
| 2b | `nonreq = ∅`, `\|M\| = 1` | `ASK` | `NECESSARY_MISSING_REQUESTABLE` |
| 2c | `nonreq = ∅`, `\|M\| ≥ 2` | **`ESCALATE`** | `MULTIPLE_REQUIRED_MISSING` |
| — | `M = ∅`, some hidden fact lies **outside every alternative** | none | classified `IRRELEVANT_MISSING` |
| — | `M = ∅`, every hidden fact is a support fact (or nothing is hidden) | none | classified `NO_MISSING_REQUIRED` |

The two `none` rows are **missingness classifications** recorded in the witness; they are not values of
the `reason` field (§5.3), and the algebra continues to step 3. A hidden *redundant* support fact with
`M = ∅` is recorded in the witness but is not irrelevant.

`ASK` is emitted only when **exactly one** requirement is unresolved, so the ask always names one
requirement and one repair. `ESCALATE` for `|M| ≥ 2` means the single-ask local controller cannot
finish the job and a higher authority can — which is what the O6 authority axis exists for.

**The mixed case is explicit:** one requestable plus one unavailable unresolved requirement is
`DECLINE_UNAVAILABLE`, not `ASK` and not `ESCALATE`.

**`|M|` is recorded in every missingness witness**, together with, per unresolved requirement: its id,
slot, subject, alternatives, repairs, and which repairs are legal. The label is therefore recoverable
from the record by counting unsatisfied obligations and checking whether each has a legal repair.
Reason and witness are separate per branch, so **reason → disposition stays a function**.

**Balance.** `ESCALATE`'s class share is **reported per split** in the manifest, with a declared
alert threshold. It is deliberately **monitored, not gated**: a fixed class-share bound would be
arbitrary, so a dumping ground is prevented by visibility plus the recorded `|M|` witness.

The partition is **exhaustive and disjoint**, and every branch is **derived** from `M`, `nonreq`,
and the policy — never sampled. The v1 60/40 coin flip has no analogue here.

#### 3.2.1 O11 — required-ness inside a disjunctive open slot (CLOSED in v0.6, ruling C)

Interaction found in v0.5: the v0.4 rule *required = intersection over all minimal supports* and the v0.5
disjunctive `object_location` slot together returned an **empty** required set for *where is obj*
(supports `{AT(obj,L1)}` and `{HOLDS(a,obj)}` do not intersect), which would have failed G03 at seal and
labelled such worlds `IRRELEVANT_MISSING`, never `ASK`.

| option | outcome |
|---|---|
| A slot-local intersection | kept fact-level testing but cannot say a *slot* is required when no fact is common |
| B slot-level requiredness only | abandons fact-level supports; a deleted fact becomes unaccounted for |
| **C both (ruled)** | **requiredness at the obligation level, evidence at the fact level** (§3.1) |

Ruling text: *O11 — choose C. Query requiredness is represented at the slot/obligation level while
preserving fact-level minimal support alternatives. A disjunctive slot is one required query obligation
with one or more minimal fact-set alternatives. A requirement is satisfied iff at least one alternative
is fully supported. `M` is the set of unsatisfied query obligations, so `|M|` counts unresolved
obligations, not absent alternative facts. Requestability is evaluated over minimal repair sets for each
unresolved obligation. G03 distinguishes irrelevant facts, redundant support facts and individually
necessary facts.*

### 3.3a Evaluator and observation conventions (v0.7)

These pin semantics the generator needs and the freeze left implicit.

**(G1) Subject of a `general_relation` requirement.** For a `TRANSITIVE` relation the subject is
`(source_entity, relation_id, target_entity)`: a reachability question has a target, and the alternatives
are the chains of `REL` facts from source to that target (as §3.1 already says). For a
non-transitive `required_slot` relation the subject is `(source_entity, relation_id)` and the single
alternative is the set of that source's direct `REL` facts. `SCHEMA`-scope obligations come from
**schema queries** declared in `WORLD_TRUTH.schema_queries` (`{source, relation_id, target?}`); they do not
come from consulted facts.

**(G3) Obligation sources for opened slots.** A slot marker (§1.7) opens a CLOSED slot for one world.
`traversable_edge`: the `CONNECTED` facts **consulted** by the scope (the canonical plan) become
obligations. `prohibited_edge`: a `BLOCKED` fact becomes an obligation iff the decision
**counterfactually depends on it**, meaning deleting that fact from the truth changes the canonical plan,
its depth, the tie set, or the legal set. Absence of a fact never creates an obligation (an absent fact has
nothing to support).

**(G4) Reports, supported facts, conflicts, uncertainty.** `OBSERVATION.reports[]` carry claim facts
`{fact_id, channel, confidence_pct}`. A claim may be true (its id equals a world fact) or false (its id is
not in `WORLD_TRUTH`). `supported_facts` = `visible_facts` ∪ the claims of `reports`; a report is a
**derived** fact whose derivation witness is the report itself. Two supported facts **conflict** iff they
occupy the same functional slot key with different facts: two direct location members for one entity
(`AT`/`HOLDS`/`CONTAINS` with that entity as subject), or two `STATE` facts for one `(entity, attribute)`
with different values and overlapping validity intervals (a report is valid throughout). A fact is
**uncertain** iff it is supported only through reports, none of which is visible, and every such report has
`confidence_pct` below the threshold of a declared `CONFIRM_UNCERTAIN` escalation rule (step 8).

**(G5) Observation sufficiency.** When `M = ∅`, algebra steps 3–10 are evaluated twice: on the full
truth `S`, and on the **observed state** (the true facts whose ids are supported). The dispositions, reasons
and executed actions must agree, otherwise the world is regenerated. This is part of G03's re-derivation:
it is what makes "determinable from what the agent can observe" mechanical.

**(G6) Decided at step 1a.** A world decided at step 1 or 1a never reaches the query evaluation; its
`required_facts.query` is recorded empty with `query_evaluated = false`. Nothing at step 2 or later depends
on it.

**Time, actions and policy.** Every environment action advances the tick by exactly one (§3.5); `WAIT`
changes nothing else. A fact scheduled in `[valid_from, valid_to)` holds at tick `t` iff
`valid_from ≤ t < valid_to`; only `STATE` facts of exogenous devices are scheduled. `available_actions` is the
closed grounded set of one world; a `NO_VALID_ACTION` world omits `WAIT` and has every other instance
illegal. The information policy, the action permissions and the escalation rules are **declared in the
rendered observation**, since `ASK` versus `DECLINE_UNAVAILABLE` could not otherwise be determined from
what the agent sees.

### 3.3 Renderer system (O3, closed)

```text
12 renderer families total:  8 seen (V1..V8) + 4 held (H1..H4) for TEST-TEMPLATE
```

Every `TEST-TEMPLATE` canonical world is rendered through **all four** held families, so renderer
comparisons are **paired on identical truth**. Within a family, seeded lexical variation is
permitted: a family identity describes **syntax and discourse realization**, not one fixed
string template. Four held families keep this a real family-level holdout without turning the bank
into a prose-generation project.

### 3.4 Two controls, never merged (O6, closed)

`ESCALATE` and `DECLINE_UNAVAILABLE` are **two distinct controller dispositions**:

- `DECLINE_UNAVAILABLE` — required information is **unavailable under the declared policy**. The
  world may be perfectly understood and still have **no permitted way to acquire** a needed fact.
- `ESCALATE` — the local controller **refuses authority**, **cannot safely resolve**, or requires
  a **stronger tier**. A world can have **enough information yet still require escalation**.

They are independently testable, each with its own witness type (§5.1). This refusal/authority
axis is exactly what the surviving typed-observer + confidence-gating + escalation architecture
needs; folding it into unavailability would repeat the v1 convention collapse (postmortem §2b).

### 3.5 Discrete time (O5, closed)

```text
t ∈ {0,1,2,...}
a_t is evaluated against S_t
if legal:  S_t --a_t--> S_{t+1}
WAIT advances exactly one tick
```

Facts may carry `valid_from`, `valid_to`, `observed_at`. Core v2 has **no concurrent actions**
and no ambiguous wall-clock semantics. `BEFORE`/`AFTER` are **derived from ticks**, never
independently generated labels. Simultaneous events, interval uncertainty, and asynchronous
agents are **challenge modes**, deferred so they cannot contaminate the base algebra.

---

## 4. Paired intervention catalog

Paired worlds are the primary product: a single example tells you a score, a pair tells you which
interface broke. Each is a **named, seeded** generation mode.

| id | intervention | varied | expected target delta |
|---|---|---|---|
| P1 | `SAME_TRUTH_DIFFERENT_WORDING` | `renderer_id` | none |
| P2 | `SAME_WORDING_DIFFERENT_BINDING` | `aliases` | binding target changes |
| P3 | `SAME_WORLD_DIFFERENT_GOAL` | `goal`, `required_facts` | disposition may change |
| P4 | `SAME_GOAL_ONE_REQUIRED_HIDDEN` | `supported_facts`, `hidden_facts` | missing family changes |
| P5 | `SAME_MISSING_REQUESTABLE_VS_NOT` | one bit of `requestable` | `ASK` ↔ `DECLINE_UNAVAILABLE` (**required**); built only on a requirement with a **single alternative and a single-fact repair**, so the one-bit flip is sharp |
| P6 | `SAME_EVIDENCE_ONE_CONTRADICTION` | `supported_facts` | `CONFLICTING_EVIDENCE` appears |
| P7 | `SAME_TOPOLOGY_NEW_VOCAB` | `relations` | relation target only |
| P8 | `SAME_SEMANTICS_NEW_TOPOLOGY` | `relations`, `state` | structure target changes |
| P9 | `SAME_WORLD_TEMPORAL_REORDER` | `temporal_state` | temporal target changes |
| P10 | `SAME_STATE_DIFFERENT_ACTION_POLICY` | `permissions`, `action_costs` | applicability flips |
| P11 | `SAME_POLICY_NEW_SOURCE_COST` | `acquisition_cost`, `source_constraints` | **none** (negative control) |
| P12 | `SAME_WORLD_OBSERVATION_COMPLETENESS` | `visible`/`hidden`/`supported` | evidence and missing targets change |

**Pair invariants (G10):** the canonical diff of a pair is confined to its declared `varied` field
set; each record is independently valid; an intentional structural overlap carries a **pair
identity** satisfying the split's collision policy (§6). P11 is the **negative control** — without
it, a generator that perturbs everything looks identical to one that perturbs the right thing.

---

## 5. Target and witness contract

Every target is a triple. `witness` is mandatory for all nontrivial targets and must
**re-derive** from the record without consulting the generator (G04).

| target | witness (typed) |
|---|---|
| `disposition` | the rule that fired + its inputs |
| `reason` | per-reason map (§5.1) |
| `executed_action` | `legal_transition` |
| `applicability` | `exhaustive_environment_legal_set` |
| `next_state` | `state_delta` |
| `missing_information` | `missing_set` from the **query** scope |
| `relation` | `relation_triple` |
| `edge_existence` | `edge_presence_or_absence` |
| `contradiction` | `conflicting_pair` |
| `temporal_order` | `derived_event_order` from ticks |
| `nli` | `entailment_witness` |
| `entity` | `mention_span` |
| `evidence` | `supporting_fact_set` |
| `plan_step` | `plan_prefix` |
| `impossibility` | `unsat_certificate` |
| `difficulty` | n/a (descriptive) |

### 5.1 Reason → witness

| reason | witness | verified by |
|---|---|---|
| `NO_MISSING_REQUIRED` *(classification, not a `reason` value)* | `M = ∅`, hidden facts listed | requirement satisfaction |
| `NECESSARY_MISSING_REQUESTABLE` | the single unresolved requirement, its alternatives, repairs, the chosen legal repair, + `request_object` | requirement satisfaction + counterfactual deletion |
| `NECESSARY_MISSING_UNAVAILABLE` | the single unresolved requirement and the fact in each repair that is absent from `requestable` | requirement satisfaction + counterfactual deletion |
| `MULTIPLE_REQUIRED_MISSING` | the ≥2 unresolved requirements (each with alternatives and repairs), with `\|M\|` recorded → `ESCALATE` | cardinality of unsatisfied obligations + counterfactual deletion |
| `MULTIPLE_REQUIRED_MISSING_UNAVAILABLE` | the chosen unavailable requirement, the `nonreq` subset, and `\|M\|` | cardinality + legal-repair check + counterfactual deletion |
| `CONFLICTING_EVIDENCE` | conflicting fact pair | simulator conflict check |
| `IMPOSSIBLE_GOAL` | `unsat_certificate` | **exhaustive** simulator search |
| `NO_VALID_ACTION` | `exhaustive_environment_legal_set = ∅` | **exhaustive** simulator search |
| `GOAL_SATISFIED` *(witness kind of `NOOP`, not a `reason` value)* | goal-satisfying fact set | simulator check |
| `AMBIGUOUS_REFERENCE` | a goal mention whose `OBSERVATION.aliases` binding names ≥2 entity ids | alias-table check |
| `MULTIPLE_UNRESOLVED_ACTIONS` | tied optimal action set | BFS tie enumeration |
| `OUT_OF_SCOPE` | goal predicate that no environment action type can assert (outside the action closure) | closure check |
| `UNKNOWN_ENTITY` | a goal argument in the **subject** role that is not an introduced entity | `introduced` flag |
| `UNKNOWN_TARGET` | a goal argument in a **target** role (destination or value) that is not an introduced entity | `introduced` flag |
| `POLICY_DENIED` | denying authority in `permissions` | permission lookup |
| `ESCALATION_REQUIRED` | fired `escalation_rules[]` entry | rule evaluation |

`IMPOSSIBLE_GOAL` (goal **unreachability**) and `NO_VALID_ACTION` (**no applicable action at
all**) are separated by ruling; both require an **exhaustive simulator certificate** (G13). The
v1 doubled-`BLOCKED`-pair label device is **forbidden** as a label shortcut, because it shipped a
perfect count artifact instead of a reachability fact (postmortem §2a).

### 5.2 Witness escalation rule

> If a nontrivial target cannot be given a witness that re-derives, the world is **regenerated** —
> never relabeled, never downgraded to a catch-all reason.

This forbids the v1 reason-folding failure mode by construction. There is **no code path** in v2
that rewrites a reason into `INSUFFICIENT_EVIDENCE`.

### 5.3 Label-consistency invariant

`reason` is non-null **iff** `disposition ∈ {ASK, ESCALATE, DECLINE_UNAVAILABLE}`; it is **null** for
`EXECUTE` and `NOOP`. The justification of a `NOOP` is its `goal_satisfying_witness` (witness kind
`GOAL_SATISFIED`), never a reason value. Every reason belongs to exactly one disposition, so
**reason → disposition is a function** (table in §6.1). v1 shipped 11,630 TRAIN rows with
`decision="ACT"` and a populated `abstain_reason="GOAL_SATISFIED"` (postmortem §2c); G01 rejects any
violation. *(v0.5 said "iff `DECLINE_UNAVAILABLE`", which contradicted its own `ASK` and `ESCALATE`
reasons; see F1, §10.6.)*

---

## 6. Decision algebra (executable specification)

The total function the founding rule requires. First match wins; no `random()` anywhere.

```
Inputs:  Rq   = goal.required_facts.query     (requirement objects, §3.1)
         Sup  = OBSERVATION.supported_facts
         Q    = INFORMATION_POLICY.requestable
         S    = WORLD_TRUTH.state
         G    = goal
         P    = ACTION_POLICY

 0. invariant preconditions (else REGENERATE, never a fallback branch):
      visible ∪ hidden = S ; visible ∩ hidden = ∅
      supported ⊆ visible ∪ derived, each derived with a witness
      requestable ∩ non_requestable = ∅ ; hidden ⊆ requestable ∪ non_requestable
      hidden facts of a CLOSED slot only under a slot marker
      every EXECUTE ∈ available_actions ; every ASK resolves to a request_object

 1. if ∃ conflicting supported pair            -> DECLINE_UNAVAILABLE / CONFLICTING_EVIDENCE
 1a. referential checks on the goal, before any plan reasoning:
      a goal mention whose alias binding names >= 2 entities   -> DECLINE_UNAVAILABLE / AMBIGUOUS_REFERENCE
      a SUBJECT-role goal argument not an introduced entity    -> DECLINE_UNAVAILABLE / UNKNOWN_ENTITY
      a TARGET-role goal argument not an introduced entity     -> DECLINE_UNAVAILABLE / UNKNOWN_TARGET
      goal predicate outside the ACTION CLOSURE                -> DECLINE_UNAVAILABLE / OUT_OF_SCOPE
 2. M := { r in Rq : no alternative of r is contained in Sup }   (unresolved obligations)
    nonreq := { r in M : r has no legal repair under Q }
 2a. if nonreq ≠ ∅         -> DECLINE_UNAVAILABLE   (non-requestability dominates count)
                               |M| = 1  -> NECESSARY_MISSING_UNAVAILABLE
                               |M| ≥ 2  -> MULTIPLE_REQUIRED_MISSING_UNAVAILABLE
 2b. if nonreq = ∅ and |M| = 1 -> ASK / NECESSARY_MISSING_REQUESTABLE (request_object naming r and its chosen repair)
 2c. if nonreq = ∅ and |M| ≥ 2 -> ESCALATE / MULTIPLE_REQUIRED_MISSING
     (M = ∅ falls through; the IRRELEVANT_MISSING / NO_MISSING_REQUIRED class is recorded in the witness)
 3.  if G already satisfied in S -> NOOP  (witness: goal-satisfying fact set; reason null)
 4.  L := legal environment actions in S
     if L = ∅ -> DECLINE_UNAVAILABLE / NO_VALID_ACTION (witness: exhaustive L = ∅)
 5.  if no plan S -> G (exhaustive) -> DECLINE_UNAVAILABLE / IMPOSSIBLE_GOAL (unsat certificate)
 6.  if an escalation_rule fires -> ESCALATE / ESCALATION_REQUIRED (witness: the fired rule)
 7.  if a convention forbids the action -> DECLINE_UNAVAILABLE / POLICY_DENIED
 8.  if a used fact is uncertain and an escalation rule of kind CONFIRM_UNCERTAIN applies
                                  -> ESCALATE / ESCALATION_REQUIRED (witness: that rule and fact)
 9.  if the optimal prefix has ≥2 tied first actions -> DECLINE_UNAVAILABLE / MULTIPLE_UNRESOLVED_ACTIONS
10.  else -> EXECUTE the unique optimal first environment action
               (witness: legal_transition + plan_prefix; reason null)
```

**Properties (all gate-checked):** deterministic (G02/G03); total, with `REGENERATE` as the escape
for malformed records rather than a silent branch; P5-sharp (steps 2a/2b differ on one bit of `Q`);
reason-complete, **reachable** (every reason is emitted by exactly one algebra step) and **fold-free**
(G12).

### 6.1 Reason → disposition → emitting step

| reason | disposition | step |
|---|---|---|
| `CONFLICTING_EVIDENCE` | DECLINE_UNAVAILABLE | 1 |
| `AMBIGUOUS_REFERENCE`, `UNKNOWN_ENTITY`, `UNKNOWN_TARGET`, `OUT_OF_SCOPE` | DECLINE_UNAVAILABLE | 1a |
| `NECESSARY_MISSING_UNAVAILABLE`, `MULTIPLE_REQUIRED_MISSING_UNAVAILABLE` | DECLINE_UNAVAILABLE | 2a |
| `NECESSARY_MISSING_REQUESTABLE` | ASK | 2b |
| `MULTIPLE_REQUIRED_MISSING` | ESCALATE | 2c |
| `NO_VALID_ACTION` | DECLINE_UNAVAILABLE | 4 |
| `IMPOSSIBLE_GOAL` | DECLINE_UNAVAILABLE | 5 |
| `ESCALATION_REQUIRED` | ESCALATE | 6, 8 |
| `POLICY_DENIED` | DECLINE_UNAVAILABLE | 7 |
| `MULTIPLE_UNRESOLVED_ACTIONS` | DECLINE_UNAVAILABLE | 9 |
| *(none: `NOOP`, `EXECUTE`)* | NOOP (3), EXECUTE (10) | reason null |

`GOAL_SATISFIED` and `NO_MISSING_REQUIRED` / `IRRELEVANT_MISSING` are witness kinds and classifications,
not `reason` values. v0.5 placed `OUT_OF_SCOPE` after the plan search, where `IMPOSSIBLE_GOAL` would
always pre-empt it, and gave `AMBIGUOUS_REFERENCE`, `UNKNOWN_ENTITY` and `UNKNOWN_TARGET` no emitting
step at all (F2, F3, §10.6).

---

## 7. External policy: declared abstract seeds, zero rows (O7 registry frozen)

BANK-v2 core is **zero-row synthetic**. External datasets contribute **declared abstract seed
descriptors** only, recorded with full provenance.

```text
BANK-v2 CORE
  synthetic canonical worlds, full symbolic truth, exact interventions,
  deterministic labels, typed witnesses, ZERO imported external rows

EXTERNAL SEED REGISTRY
  dataset identity, license, version_or_hash,
  which ABSTRACT properties inspired generation (abstract_properties_used[]),
  which properties are FORBIDDEN to copy (forbidden_properties[]),
  which v2 constructs are affected (v2_constructs_affected[])

EXTERNAL CHALLENGE PANELS   (separate releases; adapters deferred; never core rows)
  public datasets adapted read-only for transfer tests;
  never used to derive v2 generators after scoring begins
```

**Rule of thumb:** structure may be inspired; **strings and answers may not be imported**. An entry
with empty `abstract_properties_used` is inadmissible — it is a vibe, not a seed.

### 7.1 Challenge-panel registry v1 (O7, declared — adapters deferred)

| panel | axis | abstract properties used |
|---|---|---|
| Planetarium | planning / language ↔ formal state | planning structures, action/effect/goal schemas, reasoning-depth ranges |
| CLUTRR | role binding / compositional relations | role-binding structures, compositional depth ranges |
| GTSQA | topology / relation / hop generalization | graph motifs, hop-depth ranges, relation families, holdout designs |
| TGQA | temporal graph reasoning | temporal patterns, interval topologies |
| RuleTaker | evidence / entailment / contradiction | logical-closure structures, abstract predicate vocabularies |
| MQuAKE-ST | natural KG path + paraphrase | path structures, paraphrase ideas |
| GraphInfer | semantic node content + topology | graph motifs, node-attribute schemas |

All panels are **declared, not adapted**, and remain **external**. Freezing the registry is
sufficient to unblock core generator code; adapters are a later, separate step.

### 7.2 The narrowed structural-ecology channel (v0.3)

External structure may influence generation through a **closed parameter list only**:

```text
degree_distributions   path_lengths        relation_arity_patterns
inverse_frequency      symmetry_frequency  composition_depth
motif_frequency        entity_type_mixtures
```

Everything else stays synthetic and bank-owned — **relation ids, entity ids, lexical
realizations, questions, answers, rows**. This is the concrete form of the firewall: established
structural ecology in, synthetic causal control out.

Two conditions harden the channel:

- **E1 — aggregate only.** The parameters are measured as **aggregate statistics** and **never
  copied row by row**. Row-level copying would be import by another name.
- **E2 — the list is frozen at eight.** A **ninth parameter requires a versioned amendment**, so
  the external channel cannot widen silently.

---

## 8. Budgets (O4, closed)

Budgets are **post-dedup / post-stratification minimums**, not generation counts. The generator may
overproduce to satisfy them.

```text
TRAIN                 400,000 canonical worlds
DEV                    50,000
TEST-IID               50,000

each core OOD split    25,000
  TEST-TEMPLATE  TEST-VOCAB  TEST-RELATION  TEST-GRAPH-ISO  TEST-HOP-DEPTH
  TEST-ACTION-COMPOSITION  TEST-TEMPORAL-COMPOSITION  TEST-INFORMATION-POLICY  TEST-JOINT

per intervention axis   10,000 paired identities (pairs may share a canonical identity
                        only where the experiment explicitly requires it)
```

Floor ≈ 725,000 canonical worlds. Dedup and stratification consume rows, so a generation count is
not a deliverable count; scale must not become the experiment.

### 8.1 Budgets are canonical-world budgets (frozen in v0.3)

> **The budgets above are canonical-world budgets. They are NOT a requirement to render every
> canonical world through every renderer.**

`TRAIN` must **not** become `400,000 × 8`. Renderer allocation across `TRAIN` is **stratified and
balanced** across the eight seen families, with one rendering per canonical world. Renderer
multiplicity is a rendering decision, not a world-count decision; conflating them would inflate the
bank 8× for no experimental gain.

The **sole exception** is `TEST-TEMPLATE`, where every canonical world is rendered through **all
four** held families, because the paired comparison on identical truth *is* the experiment.

This yields a checkable accounting identity:

```text
rendered_rows = canonical_worlds + 3 × TEST-TEMPLATE_canonical_worlds
              = 725,000 + 3 × 25,000 = 800,000 rendered rows
```

| split | canonical worlds | renderings per world | rendered rows |
|---|---|---|---|
| TRAIN | 400,000 | 1 (stratified over V1–V8) | 400,000 |
| DEV | 50,000 | 1 | 50,000 |
| TEST-IID | 50,000 | 1 | 50,000 |
| 8 non-template OOD splits | 200,000 | 1 | 200,000 |
| **TEST-TEMPLATE** | 25,000 | **4 (H1–H4)** | **100,000** |
| **total** | **725,000** | — | **800,000** |

---

## 9. Splits, collision policy, and seal gates

### 9.1 Split identities are structural

Each split is verified by a **structural predicate** over the record — never by split name, never
by "it was generated that way" (G11). Escrow is tiered as in v1:
`public/test-inputs/` label-free, `protected/test-truth/` escrowed, `terminal_truth_opened=false`.

### 9.2 Collision-policy matrix (G09, redefined in v0.2)

Graph-isomorphic overlap is **not universally bad** — sometimes it is the entire experimental
design. So G09 does **not** say "remove all collisions." Each split declares, per held objective,
whether cross-split structural overlap is `FORBIDDEN`, `ALLOWED`, or `REQUIRED`:

| split | held objective | policy | note |
|---|---|---|---|
| TEST-IID | — | ALLOWED | exact world duplicate forbidden |
| TEST-TEMPLATE | renderer family | **REQUIRED** | identical truth through all four held families |
| TEST-VOCAB | surface vocabulary | ALLOWED | allowed when semantics and topology held fixed |
| TEST-RELATION | relation type | ALLOWED topology / FORBIDDEN held semantics | topology may repeat; held relation semantics must not |
| TEST-GRAPH-ISO | isomorphism class | **FORBIDDEN** | |
| TEST-HOP-DEPTH | depth structure | **FORBIDDEN** | |
| TEST-ACTION-COMPOSITION | action composition | **FORBIDDEN** | |
| TEST-TEMPORAL-COMPOSITION | temporal composition | **FORBIDDEN** | |
| TEST-INFORMATION-POLICY | policy regime | ALLOWED | world truth paired intentionally while policy changes |
| TEST-JOINT | topology + renderer | FORBIDDEN except declared pairs | only explicitly declared paired components may overlap |

**G09, as sealed:** every structural collision must satisfy its split's predeclared collision
policy **and** carry a pair or stratum identity when intentional. **An undeclared collision fails
the seal.** This protects experimental isolation without murdering the paired-intervention design
or the split budgets — the opposite of v1's blanket 7,981-collision carryover (postmortem §4a).

### 9.3 Seal gates G01–G18

Every gate **computes** its predicate from data. A gate that cannot compute its predicate **fails
closed**; `gate(x, True, ...)` is a build error (G07). Critical invariants run on **100% of rows**;
sampling is allowed only for gates declared expensive, which must state their rate in the manifest
(G16).

| id | gate | scope |
|---|---|---|
| G01 | schema + partition + reason-nullability invariant (§5.3) | 100% |
| G02 | deterministic regeneration by seed | 100% |
| G03 | every target re-derives from the record via §6, **including the four-part counterfactual deletion over requirement alternatives** (§3.1) | 100% |
| G04 | every nontrivial target has a re-verifying witness | 100% |
| G05 | action round-trip, all 8 steps (§2.1) | 100% |
| G06 | **action coverage receipt: all six cells nonzero per core action** (§2.1) | 100% |
| G07 | no hardcoded-True gate; every predicate computed or fails closed | build |
| G08 | textual dedup and structural dedup as **distinct** predicates | 100% |
| G09 | **every collision satisfies its declared policy with a pair identity** (§9.2) | 100% |
| G10 | paired interventions differ only in declared field sets (§4) | 100% pairs |
| G11 | holdout strata verified structurally (§9.1) | 100% |
| G12 | missingness derivability over **requirement objects and minimal supports**, `ASK` cardinality, precedence, **reason reachability**, closed-slot hidden-fact rule, **no folding** (§3.1, §3.2, §6.1) | 100% |
| G13 | `IMPOSSIBLE_GOAL` / `NO_VALID_ACTION` carry exhaustive certificates | 100% |
| G14 | external-row firewall, byte-level: zero imported rows | 100% |
| G15 | seed-registry **and** challenge-panel-registry completeness | registry |
| G16 | critical invariants at 100%; sampled gates declare their rate | manifest |
| G17 | **control-action consistency**, six referential checks (§9.4) | 100% |
| G18 | **relation vocabulary closure**, seven checks (§9.5) | 100% |

v1's G-numbers are **not** reused for v2 semantics. Within v2: G06 strengthened and G09 redefined
in v0.2; G17 added in v0.2; **G18 added in v0.3**. v1's `seal-gates.json` remains the record for
v1's numbering.

### 9.4 G17 — control-action consistency (from the REQUEST discovery)

For every row:

- every `EXECUTE` references an available **legal** environment action;
- every `ASK` references a **generated** `request_object`;
- every `request_object` names an unresolved requirement and the repair facts it reveals;
- every `DECLINE_UNAVAILABLE` has its reason-typed witness (§5.1); for the two missing-information reasons that witness is the requirement with no legal repair;
- every `ESCALATE` has an escalation-policy witness;
- **no disposition points at a nonexistent action namespace.**

This is a **100% whole-bank check**, not sampled. It is the direct guard against the v1 pattern
where every `ASK` row named an action that did not exist (postmortem §1a).

### 9.5 G18 — relation vocabulary closure (added in v0.3)

At **100%** bank coverage:

- every canonical fact uses a **frozen operational predicate or a registered `REL`** — nothing
  else appears in world truth;
- every `REL` references an **existing relation registry entry**;
- every relation respects its declared **domain and range types**;
- **symmetric relations are canonically normalized** per the one frozen rule (§1.6) — stored once,
  ascending entity ordinal;
- **inverse declarations are mutually consistent** (`r.inverse = s` implies `s.inverse = r`);
- **transitive closure used for targets is derived**, never silently inserted into world truth;
- **no renderer-specific lexical relation appears in canonical truth** — *supplies* and *receives
  goods from* are renderings of a synthetic `relation_id`, never facts.

This gate is what stops surface vocabulary from quietly becoming ontology.

---

## 10. Amendment log and resolved open items

### 10.1 v0.2 changes

| id | closes | change | why |
|---|---|---|---|
| A1 | O1 | three action namespaces; typed disposition references | postmortem §1a: all 7,141 v1 ASK rows named an absent action |
| A2 | O1 | G06 → per-action coverage receipt, six cells | a simulator handler existing is not coverage |
| A3 | O2 | typed five-scope `required_facts`; `M = query − supported` | X0: schema ≠ goal need must stay separable |
| A4 | O3 | 12 renderer families (8 seen, 4 held); all four render each TEST-TEMPLATE world | real family-level holdout, paired on truth |
| A5 | O4 | budgets as post-dedup minimums; 400k/50k/50k + 25k/OOD + 10k paired/axis | dedup consumes rows |
| A6 | O5 | discrete ticks, one-step transition, WAIT advances one tick, no concurrency | concurrency is challenge-mode material |
| A7 | O6 | `ESCALATE` and `DECLINE_UNAVAILABLE` stay two dispositions | refusal/authority is a distinct axis |
| A8 | — | G09 → per-split collision-policy matrix | overlap is sometimes the design |
| A9 | — | G17 control-action consistency added | postmortem §1a referential integrity |
| A10 | O7 | challenge-panel registry v1 frozen; adapters deferred | registry unblocks core code without importing rows |
| A11 | O8 | STATUS lineage entry drafted | branch state must be explicit, not imply v1 was wrong |
| A12 | — | gate count 16 → 17; G06 strengthened, G09 redefined, G17 added | cover the strengthened algebra |

### 10.2 v0.3 changes (closes O2)

| id | closes | change | why |
|---|---|---|---|
| B1 | O2 | two-layer vocabulary: six operational predicates + registered `REL` carrier | a closed operational set serves the simulator and `required_facts`; a large ontology is unnecessary and bakes in one world's semantics |
| B2 | — | `STATE` is a generic slot; `OPEN`/`CLOSED`/`ACTIVE`/`INACTIVE` are **values**, not predicates | the predicate set must not grow per invented device |
| B3 | — | `CONNECTED`/`BLOCKED` directed; bidirectional is two facts | traversability and prohibition stay distinguishable |
| B4 | — | `REL` references a registry entry with domain/range, directionality, transitivity, optional inverse | supplies relation-type OOD, role binding, inverse, composition, isomorphism, multi-hop, paraphrase without an external ontology |
| B5 | — | one frozen symmetric rule: **canonical normalization**, stored once ascending | G18 needs a single rule; avoids double-counting in graph hashes |
| B6 | — | `BEFORE`/`AFTER` confirmed derived, not primitive | temporal labels cannot contradict the clock |
| B7 | — | `SUPPORTS`/`CONTRADICTS`/`REQUIRES`/`ACHIEVES`/`CAUSES`/`APPLICABLE_TO`/`REQUESTABLE` forbidden in world truth, each assigned an owning layer | otherwise the bank leaks its solution graph into its own truth |
| B8 | — | all five `required_facts` scopes use the same seven-predicate fact language | one fact language across the bank |
| B9 | — | G18 relation vocabulary closure added at 100% with seven checks | stops surface vocabulary becoming ontology |
| B10 | — | budgets are **canonical-world** budgets; `TRAIN` stratified over 8 seen families, not `400k × 8`; `TEST-TEMPLATE` remains the sole 4-rendering exception | renderer multiplicity is a rendering decision, not a world count |
| B11 | — | external influence narrowed to structural ecology parameters | established structure informs generation while all ids, questions and rows stay synthetic |
| B12 | — | gate count 17 → 18 | cover the frozen fact language |

### 10.3 v0.4 changes (resolves the two builder questions)

| id | change | why |
|---|---|---|
| C1–C2 | relation registry is **one bank-wide table** with a `split_scope` column; G18 lookup is `(relation_id, split)` | one identity, one hash lineage |
| C3 | an **inverse pair must share a scope**; a test-only relation with a train-visible inverse is a schema error | otherwise the model has seen the relation and the holdout leaks |
| C4 | `TEST-RELATION` holds out **property combinations** absent from train, not just ids | otherwise id and semantics vary together and failure is unattributable |
| C5 | relation ids carry **no lexical content** | otherwise the id is the leak |
| C6 | `TEST-RELATION-PROPERTY` named for later | recorded, not scheduled |
| C7 | `required_facts.query` derived from **minimal supports** | the X0 lesson, made mechanical |
| C8 | G03/G12 gain **counterfactual-deletion** checks at 100% | one evaluator is the single source of truth |
| C9 | openness declared per predicate; total declaration, undeclared is a schema error | missing link vs absent link must differ |
| C10 | `ASK` iff **exactly one** missing and requestable | derived, so no coin flip |
| C11 | new reason `MULTIPLE_REQUIRED_MISSING` | two-or-more is a distinct condition needing its own witness |
| C12 | S1 ordinal shuffling + S2 unordered symmetric scoring | ascending order must carry no signal; a correct answer stored the other way must not be penalized |
| C13 | E1 aggregate-only measurement + E2 frozen eight-parameter list | keeps the firewall auditable and stops scope creep |
| C14 | `rendered_rows` identity confirmed as a standing invariant | prevents TRAIN re-inflation |

### 10.5 v0.5 changes (closes O9 and O10)

| id | change | why |
|---|---|---|
| D1 | **`ESCALATE`** frozen for `\|M\| ≥ 2` with everything requestable; reason `MULTIPLE_REQUIRED_MISSING` with `\|M\|` recorded | single-ask local controller cannot finish; this is what the O6 authority axis is for, and it keeps `ASK` single-target |
| D2 | **mixed case** frozen: any non-requestable critical fact → `DECLINE_UNAVAILABLE` **whatever the count** | the answer stays incomplete even after every question is asked; without explicit precedence it fell through the algebra |
| D3 | algebra step 2 reordered so **non-requestability precedes cardinality** | the label must be a total function of the record |
| D4 | new reason `MULTIPLE_REQUIRED_MISSING_UNAVAILABLE` | keeps **reason → disposition** a function |
| D5 | `\|M\|` recorded in every missingness witness | recoverability by counting |
| D6 | `ESCALATE` class share reported per split — **monitored, not gated** | prevents a dumping ground; a fixed bound would be arbitrary |
| D7 | openness declared **per slot**, not per predicate | the per-predicate version contradicted `AT` for held/contained objects |
| D8 | `object_location` is an **open disjunctive** slot over `AT`/`HOLDS`/`CONTAINS` | slot-completeness logic; the pattern that lifted ASK recall in the sandbox |
| D9 | `REL` closed by default, with a per-relation `required_slot` override | an unasserted relation means not asserted, unless obligatory |
| D10 | every predicate is a member of exactly one slot; orphan is a schema error | makes the declaration total and checkable |
| D11 | G12 gains precedence + slot-completeness checks; G03 gains slot-local required-ness | the new rules need 100% gate coverage |
| D12 | v1's 75% figure recorded **with its exact definition** | 737 of 978 ASK-labelled DEV worlds still had a simulator-findable plan after removal; "unneeded" = goal still reachable under the v1 simulator, **not** a minimal-support notion |

### 10.6 v0.6 changes (closes O11; builder-forced coherence fixes)

**Ruled changes (O11, option C):**

| id | change | why |
|---|---|---|
| E1 | `required_facts.query` is a list of **requirement objects** `{requirement_id, slot, subject, required, support_alternatives}` | requiredness is an obligation; evidence is disjunctive |
| E2 | requirement **satisfied iff some alternative is fully supported**; `M` = unsatisfied obligations, so `\|M\|` counts obligations | a disjunctive slot with nothing observed is one missing requirement, not several facts |
| E3 | requestability over **minimal repair sets**: REQUESTABLE iff at least one legal repair; `nonreq` = unresolved requirements with none | O9 precedence and the mixed case stay intact |
| E4 | `ASK` names one requirement and its chosen repair; `request_object` = `{request_id, requirement_id, reveals}` | one ask can acquire a multi-fact repair |
| E5 | derived fields `required_requirements`, `support_facts`, `necessary_facts`, **never collapsed** | irrelevant, redundant-proof and necessary facts are different things |
| E6 | G03 four-part counterfactual gate; G12 replaces the intersection check with requirement-level checks | intersection gave an empty set for disjunctive slots |
| E7 | evaluator contract: per-slot derivation rules, antichain of minimal supports, nesting depth ≤ 2, redundancy mode in the generator | the gate must exercise redundant truth |
| E8 | `IRRELEVANT_MISSING` means a hidden fact outside **every alternative**; hidden redundant support facts are not irrelevant | the three-way fact partition |

**Builder-forced coherence fixes (provisional; found by the build-readiness audit, open to override):**

| id | finding | fix |
|---|---|---|
| F1 | §5.3 said `reason` is non-null iff `DECLINE_UNAVAILABLE`, but `ASK` and `ESCALATE` carry reasons | non-null iff `ASK`, `ESCALATE` or `DECLINE_UNAVAILABLE`; null for `EXECUTE`/`NOOP`; `GOAL_SATISFIED` and `NO_MISSING_REQUIRED`/`IRRELEVANT_MISSING` are witness kinds and classifications |
| F2 | `AMBIGUOUS_REFERENCE`, `UNKNOWN_ENTITY`, `UNKNOWN_TARGET` were emitted by no algebra step | new step 1a with derivation rules (alias binding ≥2; subject role vs target role not introduced) |
| F3 | `OUT_OF_SCOPE` sat after the plan search, so `IMPOSSIBLE_GOAL` always pre-empted it | moved into step 1a; closure defined as predicates some environment action type can assert |
| F4 | G17 demanded a non-requestability witness on every `DECLINE_UNAVAILABLE`, impossible for `IMPOSSIBLE_GOAL` etc. | witness is the reason-typed witness of §5.1 |
| F5 | hiding a fact of a CLOSED slot would silently turn it false | hidden closed-slot facts only under a slot marker; checked by G12 |

`tools/check_freeze.py` now also audits **reason reachability** (each reason emitted by exactly one
step) and **reason → disposition functionality**, so F1–F3 cannot recur.

### 10.7 v0.7 changes (builder-forced clarifications, no taxonomy change)

| id | change | why |
|---|---|---|
| G1 | subject of a transitive `general_relation` requirement includes the target; schema-scope obligations come from declared schema queries | a reachability question needs its target; the v0.6 text already spoke of chains "reaching the same target" |
| G2 | `WAIT` is precondition-free and exempt from the **`illegal`** coverage cell only (declared list) | as defined it is always legal, so the cell could never fill and the bank would fail its own seal |
| G3 | obligation sources for opened slots: consulted `CONNECTED` facts; decision-dependent `BLOCKED` facts | without a source, an opened `prohibited_edge` slot could never produce a requirement |
| G4 | reports as derived support; conflict, uncertainty and validity-overlap defined | §1.2 said "derived" without defining how conflicts and uncertainty arise |
| G5 | observation-sufficiency evaluation inside G03 | makes the founding claim (derivable from what is observed) mechanical |
| G6 | step-1/1a worlds record `query_evaluated = false` | a world decided before step 2 has no certifiable query evaluation |

### 10.8 Postmortem classifications confirmed in v0.2

- **Reason folding** stays `[INSTRUMENT]`. Intent was legitimate; rewriting distinct reasons into
  `INSUFFICIENT_EVIDENCE` manufactured rows whose label was no longer derivable from the record.
- **The 60/40 ASK choice** stays `[CHARTER]`, not a defect. Legitimate for v1's state/action test;
  unsuitable only once we later asked a structural-sufficiency question.
- **`REQUEST` absent from `available_actions`** is `[INSTRUMENT]` and more serious than the coin
  flip for our later use: v1 never had an information-acquisition action surface at all.
- **The nine dormant action types** are a coverage hole `[SCOPE]`, not a simulator spelling bug.
- The `g["obj"]` / `g["object"]` theory is **rejected** in the postmortem; the simulator is
  internally consistent.

### 10.9 Open-item status

| id | state | resolution |
|---|---|---|
| O1 action vocabulary | **closed** (v0.2) | three namespaces (§2) |
| O2 relation vocabulary + requirements | **closed** (v0.3) | two-layer vocabulary, one fact language (§1.6, §3.1) |
| O3 renderer families | **closed** (v0.2) | 12 families, 4 held (§3.3) |
| O4 budgets | **closed** (v0.2), clarified (v0.3) | post-dedup minimums; canonical-world units (§8, §8.1) |
| O5 temporal semantics | **closed** (v0.2) | discrete ticks (§3.5) |
| O6 ESCALATE vs DECLINE | **closed** (v0.2) | two dispositions (§3.4) |
| O7 challenge panels | **deferred** (v0.2) | registry frozen, adapters later (§7.1) |
| O8 STATUS lineage | **drafted** (v0.2) | §12 / `ff-s15-STATUS.md` |
| O9 multiple-missing disposition | **closed** (v0.5) | `ESCALATE`, plus the explicit mixed case (§3.2) |
| O10 openness | **closed** (v0.5) | per-slot declaration across five slots (§1.7) |
| O11 required-ness in a disjunctive slot | **closed** (v0.6) | ruling C: obligation-level requiredness, fact-level alternatives (§3.1, §3.2.1) |

**O1–O6 and O8–O11 are closed. O7 is deferred by design.** No design item remains. Code is authorized
from the v0.6 seal (§0.5).

---

## 11. Amendment rule

Any change to §1–§9 requires:

1. a **versioned amendment** to this document (v0.3, …) **written before** the corresponding code
   change;
2. a new `bank-v2-objects.json` with an incremented `version` and a regenerated sha256 sidecar;
3. an **amendment log** entry recording what changed, why, and which v1 postmortem finding (if
   any) motivated it.

A code change that would alter §1–§9 semantics without a prior amendment is a **defect** and must
be reverted, not documented after the fact. Preregister, freeze, score once; disclose post-hoc
looks as exploratory.

---

## 12. Branch status (O8, drafted)

Lineage wording for `experiments/ff-s15-STATUS.md` — explicit that v2 supersedes v1 only as the
**active bank-generation program**, never scientifically:

```text
BANK-v1 policy/controller-mining branch:  CLOSED 2026-09-29.
  Historical BANK-v1 remains sealed and is not reopened.

BANK-v2 generation branch:  OPENED 2026-09-30 as a new experimental generation.
  BANK-v2 does not amend, repair, supersede evidence from, or reopen BANK-v1.
  Current phase: v0.6 sealed; implementation authorized (pilot before scale-up).
  (v1 postmortem: BANK-V1-POSTMORTEM-2026-09-30, historical audit.)
```

---

## 13. Done-when

BANK-v2 is sealed when:

- `BANK_v2_SEALED=true` and all **eighteen** gates `PASS`, none hardcoded, none sampled on a
  critical invariant;
- the founding rule holds on **100%** of rows and every nontrivial target re-verifies from its
  witness;
- **G18 relation vocabulary closure holds at 100%** — every canonical fact is a frozen operational
  predicate or a registered `REL` (§1.6);
- every declared core environment action is **nonzero in all six coverage cells** (§2.1);
- all holdouts pass their structural predicates and every structural collision satisfies its
  declared collision policy (§9.2);
- post-dedup **minimum** budgets are met, with
  `rendered_rows = canonical_worlds + 3 × TEST-TEMPLATE_worlds` (§8.1);
- `external_rows_imported == 0`, both registries complete, no external row anywhere in core;
- `frozen_fabric_contact=false`, `system_1_5_training=false`, `terminal_truth_opened=false`;
- O1–O6 and O8–O11 are closed and O7 is explicitly deferred with rationale.

Until then this document is `FROZEN_PRE_CODE` for §1–§9; `src/` may exist (§0.5) but nothing is sealed.

---

## 14. Summary of the founding claims

1. BANK-v2 is a **new generation**; BANK-v1 is sealed history, not repaired, not scientifically
   superseded (§0.1, §0.2).
2. Every target is a **pure function of the declared record**, with a typed witness (§5).
3. Missingness is a **three-way derivable taxonomy** over typed query-scope requirements, and ASK
   is the first-class case (§3.1, §3.2).
4. Environment actions, information actions, and controller dispositions are **three namespaces**,
   so a disposition cannot name an action that does not exist (§2).
5. `ESCALATE` and `DECLINE_UNAVAILABLE` are **two controls**; refusal-of-authority is not
   unavailability (§3.4).
6. Paired interventions, not row count, are the primary product, and each action must be
   **covered in every cell** of the coverage receipt (§2.1, §4).
7. Holdouts are **structural and verified**; collision policy is **declared per split**, so
   intentional overlap is protected (§9.2).
8. The seal is only as strong as its **weakest gate**: gates fail closed, compute their predicate,
   and run at 100% on critical invariants (§9.3).
9. There is **one fact language**: six operational predicates plus a registered `REL` carrier.
   Temporal, evidence, action, and policy relations are **derived or owned by their layer**, never
   written into world truth (§1.6).
10. Budgets count **canonical worlds**, not renderings; only `TEST-TEMPLATE` renders each world
    four times, because that pairing is the experiment (§8.1).
