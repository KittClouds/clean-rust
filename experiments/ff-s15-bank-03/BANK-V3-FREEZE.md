# BANK-v3 FREEZE — constitution v0.1 (SCAFFOLD, pre-code)

**Experiment:** `FF-S15-BANK-03` **Release:** `BANK-v3` **Status:** `SCAFFOLD_PRE_CODE`
**Date:** 2026-09-30 **Version:** 0.1 **Public description:**
**human-grounded inputs with self-derived canonical labels**

Machine-readable companions: `bank-v3-objects.json`, `source-ledger-v1.json`,
`reconstruction-schema-v1.json`.

> **This document authorizes no corpus.** It freezes constitution and schemas only. External root
> reconstruction, curriculum allocation, target weighting, synthetic generation, render expansion
> and split construction are all **blocked** pending V2-0's disposition (§7).

---

## 0. What v3 is, and the one-sentence shape

\[
\boxed{\text{V2 exact semantic core} + \text{new capability curriculum} + \text{witnessed external reconstruction}}
\]

**Not** "v2 rows plus more rows." v3 is a **training-generation system descended from v2**; v2
remains an independent historical and evaluation artifact that v3 does not extend.

v1 taught where a small state/action machine breaks. v2 taught how to represent decision semantics
cleanly. v3 exists to address the third question — how a machine **acquires** the capabilities those
semantics require. That is also the step at which provenance discipline usually gets quietly
dropped, and it is the one thing v1 already demonstrated we cannot afford to skip.

---

## 1. Relationship to v2: inherit semantics, not row identity

> **V3 inherits V2's semantics and machinery, not V2's sealed row identity.**

v2 is **sealed** under constitution v0.7: freeze hash
`923fb971e513b038f42be2446f32a40d03d1ecba9b86f1d20c72df1c9903417e`, **18/18 gates PASS**,
725,000 canonical worlds, 800,000 rendered rows, `external_rows_imported = 0`, escrow intact.
That seal is a historical and evaluation artifact. v3 does not extend it, reopen it, or modify any
v2 file.

### 1.1 Inherited by pinned reference

v2's seal records **two** source manifests by design, because the G10 repair regenerated only the
paired panels. v3 pins against **`pairs_stage_source_manifest`** — the current on-disk state, all 22
entries verified matching on 2026-09-30. Pinning against the row-stage manifest would make v3's
inheritance contract unrestorable, because `build.py` and `interventions.py` legitimately differ
between the two stages.

| inherited item | pinned to | sha256 (pairs stage) |
|---|---|---|
| world schema | `bank-v2-objects.json` | `923fb971…03417e` |
| action algebra | `src/bank2/algebra.py` | `08384a17…192875` |
| obligation semantics (`required_facts.query` evaluator) | `src/bank2/requirements.py` | `c753efa6…94500e` |
| requestability semantics | `src/bank2/requirements.py` | `c753efa6…94500e` |
| contradiction / evidence semantics | `src/bank2/algebra.py` | `08384a17…192875` |
| `refsim` (independent second simulator) | `src/bank2/refsim.py` | `d812238c…318b82` |
| witness machinery | `src/bank2/targets.py` | `72c1cfa0…49211b` |
| paired-intervention grammar where applicable | `src/bank2/interventions.py` | `4c1d57cd…f1dfcd` |
| derivation rules that survive V2-0 | pending V2-0 | — (the one unpinned entry) |

Rebuilding any of this would be engineering amnesia. It is expensive, it is sealed, and it is
correct. Every pinned hash above was verified byte-for-byte against disk.

### 1.2 Explicitly not inherited

- the **800,000 rendered v2 rows**;
- v2 **row identity**, world ids, or split identity;
- **v2's G14 meaning** (`external_rows_imported == 0`) — see §2.

### 1.3 v3's own synthetic core

\[
W^{(3)}_{\text{synthetic}} \sim G_{\text{V2-compatible}}(\theta_3)
\]

v3 generates its own synthetic worlds through the pinned v2 simulator, so it can alter curriculum,
capability balance, topology, composition depth and contrast structure **without contaminating
v2's frozen bank identity**.

---

## 2. External data: allowed, expected, and the firewall inversion

`FF-S15-BANK-03` is a **new constitution and a new generation**.

v2's `external_rows_imported == 0` was a **defining invariant**, not an implementation detail. v3
intentionally violates that founding assumption, so **inheriting v2's G14 would make the seal
dishonest**. G14 is therefore **replaced, not inherited**.

```text
v2:  no outside material entered
v3:  no outside material entered anonymously or without an admissible transformation path
```

Every external source record must carry:

```text
source_dataset  source_item_id  source_version  license
training_allowed  derivatives_allowed  synthetic_seeding_allowed  redistribution_allowed
attribution_required  content_hash
```

The four permission flags are booleans because a permissive license can still forbid exactly the
operation v3 performs most. The documented precedent: a CC BY-SA 4.0 benchmark whose card forbids
using it **to generate synthetic training data seeded from it**. `synthetic_seeding_allowed` is
therefore first-class, and **no root may be ingested with it false**.

Full ledger, rubric and candidate inventory: `source-ledger-v1.json`. **On ambiguity all four flags
default to false** and the source is held. A code license does not transfer to separately hosted
data derived from it — the documented ProofWriter/RuleTaker wrinkle.

### 2.1 No v1 rows, ever

**v1 data is never imported as v3 semantic roots.** Every v1 row carries the coin-flip `ASK` label,
the folded reasons, and a 14-action schema in which 9 action types are unreachable. Importing v1
rows as roots would import precisely the catalogued defects. v1's *renderer-family ideas* may be
reimplemented cleanly. This closes the historical trapdoor and is gate-enforced (G-V1-EXCLUSION).

---

## 3. Label provenance: witnessed reconstruction, annotation as check

The path is fixed:

\[
\text{external item} \to \text{canonical reconstruction} \to \text{reconstruction witness}
\to \text{deterministic derivation} \to \text{BANK label}
\]

with the human annotation travelling **alongside** as \(y_{\text{human}}\), and BANK truth as
\(y_{\text{derived}} = f(W_{\text{canonical}})\). The reported statistic is

\[
\Pr(y_{\text{human}} = y_{\text{derived}})
\]

per source, per target family, and by reconstruction-confidence class.

**Why this is constitutional and not procedural:** a human annotation is incomplete and is not a
function of any record that can be written down. Inheriting it as truth means the provenance looks
human while the label is actually a generator's output — the v1 disease in new clothes, and much
harder to detect. A human annotation is **evidence about whether we reconstructed the source
correctly**; it does not become canonical truth merely because a human supplied it.

### 3.1 Constitutional prohibition (gate-enforced)

> **G-EXT-TRUTH.** For every externally sourced root used for supervised BANK targets:
> `canonical_world_present == true`, `reconstruction_witness_present == true`,
> `label_origin == DERIVED_FROM_CANONICAL_WORLD`,
> `human_annotation_role ∈ {CHECK, DISGREEMENT_SIGNAL, METADATA}`.
> **`label_origin == HUMAN_INHERITED` → FAIL.**

### 3.2 Three first-class reconstruction dispositions

| disposition | provides canonical target supervision | may contribute |
|---|---|---|
| `EXACT_RECONSTRUCTION` | **yes** | full descendant families |
| `PARTIAL_RECONSTRUCTION` | **no** | renderer / natural-language material only, with explicitly bounded preserved semantics; must **not** pretend to witness facts it cannot reconstruct |
| `REJECTED_RECONSTRUCTION` | **no** | nothing — but still recorded, because rejection rates are themselves a source-selection signal |

Disagreements are a **dataset diagnostic**, never silently reconciled. Where the human annotation
is itself ambiguous, the case is recorded as `ANNOTATION_AMBIGUOUS` rather than counted as a
derivation failure — separating a bad reconstruction from an ambiguous annotation is what makes the
agreement rate actionable.

---

## 4. Roots and lineage: the unit is a root, not a row

A human source produces a **semantic root** \(r\); BANK generates a controlled family around it:

\[
\mathcal{F}(r)=\{x_{\text{natural}}, x_{\text{paraphrase}}, x_{\text{distractor}},
x_{\text{support+}}, x_{\text{support-}}, x_{\text{missing}}, x_{\text{conflict}},
x_{\text{role-swap}}, x_{\text{transition}}, x_{\text{unanswerable}}\}
\]

Every descendant retains `root_id`, `source_dataset`, `source_item_id`, `transformation`,
`changed_semantics`, `preserved_semantics`, `canonical_world`, `verifier_receipt`.

> **G-LINEAGE.** Every descendant resolves to **exactly one** canonical root, with a declared
> transformation, declared preserved semantics, declared changed semantics, and a verifier receipt.

A descendant of a `PARTIAL` or `REJECTED` root may **not** supply canonical target supervision —
the root's disposition is carried on the descendant precisely so a partial root's children cannot
quietly claim supervision they did not earn.

The point is to **train on differences, not just classes** — which matches this program's strongest
prior engineering lesson: controlled contrasts beat duplicated supervision.

---

## 5. Capability axes

Every root and every descendant carries a **structural** capability annotation over ten frozen axes:

```text
binding · evidence_support · counterevidence · missing_requirements · conflict
composition_depth · transition_depth · candidate_comparison · globalization · nuisance_invariance
```

This makes curricula **constructible** — `support` → `support+conflict` → `support+conflict+transition`
— instead of shuffling a large row count and hoping. Annotations are structural, never free text.

---

## 6. Firewall gates for v3

| id | name | scope | asserts |
|---|---|---|---|
| G14-V3 | EXTERNAL-PROVENANCE FIREWALL | 100% | `external_roots_imported > 0`; `unregistered_external_roots == 0`; `roots_without_license_record == 0`; `roots_without_reconstruction_witness == 0`; `descendants_without_root_lineage == 0` |
| G-EXT-TRUTH | LABEL PROVENANCE | 100% | canonical world present; witness present; `label_origin == DERIVED_FROM_CANONICAL_WORLD`; annotation role ∈ {CHECK, DISAGREEMENT_SIGNAL, METADATA}; **`HUMAN_INHERITED` → FAIL** |
| G-LINEAGE | DESCENDANT LINEAGE | 100% | exactly one root; declared transformation; declared preserved and changed semantics; verifier receipt |
| G-V1-EXCLUSION | NO V1 ROWS AS ROOTS | 100% | no root carries a v1 `world_id` or `world_hash` |

All four are computed from data at 100%, not sampled — the same standard v2 adopted after finding
v1's gates weaker than their names.

---

## 7. Ordering: V2-0 first, and what that blocks

```text
V2-0  →  interpret cue findings  →  freeze v3 target/curriculum constitution  →  construct v3
```

**V2-0** (`experiments/ff-s15-v2-eval-00/V2-0-CONSTITUTION.md`) is `FROZEN_PRE_RUN` and **has not
run**. It is cheap, deterministic, and already frozen, and its entire purpose is to answer whether
obvious cue structure exists *before* v2's semantics are treated as substrate for model work.

**A `CUE_ACCESSIBLE` target does not necessarily die.** It changes how v3 must generate it:

- bar the cue-bearing renderer family, or
- decorrelate the target from the identified shortcut, or
- move the target to diagnostic-only status.

What must **not** happen is manufacturing millions of descendants around a target whose decision
boundary is already encoded in a cheap accidental cue. That would be an exquisitely efficient way
to train the wrong machine.

### 7.1 May proceed now (non-contact)

Source/license ledger schema · reconstruction-witness schema · source admissibility rubric ·
candidate seed inventory · canonical-root format · lineage/descendant schema · capability-axis
vocabulary · external-data firewall gates · rejection dispositions · per-source agreement
reporting format.

### 7.2 Waits for V2-0

External root reconstruction at scale · curriculum allocation · target-family weighting · synthetic
generation · render expansion · training split construction.

---

## 8. Open items

| id | item | state | note |
|---|---|---|---|
| **O1** | **reconstruction-yield probe** | **OPEN, high** | what fraction of candidate roots reach `EXACT_RECONSTRUCTION`, per source and target family. **V2-0 does not answer this** — V2-0 measures cue accessibility of v2's own synthetic semantics, not whether an external dataset can be reconstructed into that algebra at all. Cheap to run, and it decides source selection, the root budget, and whether v3 is mostly-synthetic-with-a-thin-human-veneer. A low yield is a legitimate outcome, but it must be discovered *before* building a corpus on the opposite assumption. |
| O2 | witness-machinery pin | **closed** (v0.1) | `targets.py` pinned to `72c1cfa0…49211b` and verified against disk |
| O3 | V2-0 disposition of derivation rules | **deferred to V2-0** | which v2 rules survive is an *input* to the inheritance contract, not an output; it is the single unpinned entry in §1.1 |

**O1 is the unblocking measurement.** It is not blocked by V2-0 and does not require a model.

---

## 9. Amendment rule

Any change to §1–§9 requires a versioned amendment to this document **written before** the
corresponding code or corpus change; a new `bank-v3-objects.json` with an incremented version and a
regenerated sha256 sidecar; and an amendment-log entry recording what changed, why, and which v1 or
v2 finding motivated it. Retroactive documentation is a defect.

---

## 10. Composition and honesty about scale

Target root estimate: **250k–400k semantic roots**, expandable to a few million examples. The
resulting corpus would be **85–95% synthetic by volume** while remaining human-grounded, because
the human contribution lives in the semantic roots.

One caveat stated plainly: that share is true of **volume**, not of **label provenance**. If labels
are self-derived — as §3 requires — then the honest description is **human-grounded inputs with
self-derived labels**, not "human-labeled BANK." Volume percentages must never be used to imply
provenance.

---

## 11. Summary of the frozen rulings

1. **External data ALLOWED and EXPECTED** in a new constitution; v2's G14 is replaced, not
   inherited. The firewall becomes: no outside material enters anonymously or without an admissible
   transformation path.
2. **Label provenance** is witnessed canonical reconstruction. Human annotations are checks and
   disagreement signals, never canonical truth. `HUMAN_INHERITED` fails the seal.
3. **v2 inheritance** is semantic and mechanical, by pinned hash — not row identity. v2 stays an
   independent historical and evaluation artifact.
4. **Ordering**: V2-0 runs first; scaffolding may proceed now; corpus construction waits.
5. **v1 data is never imported as v3 roots.** Renderer-family ideas may be reimplemented cleanly.
6. **Source selection is justified by reconstruction yield, not dataset reputation.** Some famous
   datasets may prove to be poor seeds; some obscure dataset with highly reconstructable structure
   may prove to be gold. The design must be able to reveal that, which is exactly why the agreement
   rate is measured per source rather than assumed.
