# CAPABILITY LADDER — measurement grammar scaffold v0.1

**Status:** `SCAFFOLD_FROZEN` — measurement grammar only. **Not** a full constitution.
**Date:** 2026-09-30 **Program:** `FF-S15-LADDER-SCAFFOLD-00`

> **What this freezes:** the things V2-0 cannot reasonably invalidate — capability axes,
> per-cell provenance, scale/family identity, the five stages, the response-vector schema, the
> no-composite-score rule, residual-family identity, the interface-declaration requirement, the
> graduation predicate *structure*, and the data axis as `(N, coverage_vector; M, I)`.
>
> **What this does NOT freeze, and waits for V2-0:** capability cells, target membership, target
> weights, thresholds tied to V2 semantics, and which interventions each rung must run.

---

## 0. The governing lesson, stated so it cannot be re-bought

> **Persistent residual ≠ substrate limit** — until the interface family has actually flattened on
> *the current rung's current task*.

This is not a platitude; it is a ledgered, concrete failure mode. The Jev frozen-saturation v0.4
gate is the worked example, and its scope must be stated precisely to avoid two opposite errors.

### 0.1 What Jev v0.4 Gate A does and does not establish

Directly verified receipt: `D:\codex-runs\jev-frozen-saturation-v04\reports\qlora-final-gate.json`
— `status: EVALUATED_UNAUTHORIZED`. For `minicpm5-1b-base`: **A FAIL, B PASS, C PASS, D PASS, E
PASS, F PASS, `authorized: false`**. Identical A-FAIL pattern for Qwen3-0.6B and K2-0.9B.

**It DOES establish:** on that semantic-stress program, with that target family, that readout
family, and that evaluation contract, the best reasonable *frozen* interfaces had **not** been
shown to have flattened. Therefore adaptation was not authorized *there*.

**It does NOT establish:**

- that MiniCPM, Qwen3 or K2 had reached a **substrate** limit;
- that any System 1.5 model-level intervention is unauthorized;
- anything about the causal Lexi lane, the Lepori lane, or any other task, target family, readout
  family, or evaluation contract.

**Ruling:** a good gate must not become a universal traffic cop. Gate A is **scoped evidence**,
carried forward as a *method* (the A–F ledger and its named controls), not as a *verdict* about
substrates.

---

## 1. Lane specificity: three corrected findings

An earlier handoff flattened three lane-specific results into program-wide findings. Corrected
here, because the entire point of this program is substrate/interface specificity.

| claim as previously stated | corrected statement |
|---|---|
| "recurrence got a clean negative" | **encoder recurrence failed badly; causal recurrence produced a modest useful gain.** Different tasks, different interfaces, different experiments. The encoder result is a clean negative *for that encoder lane only*. |
| "MOVE is 0.0000 in two independent lanes as a general program finding" | **MOVE was dead in the failed encoder-recurrence lane; the causal Lexi lane has MOVE far above that.** The 0.0000 figure is real but is a property of the lane that produced it. |
| (implied) "QLoRA/micro-LoRA is unauthorized everywhere" | **Unauthorized on the Jev v0.4 scope.** Unchanged and correct on that scope. No other scope inherits the verdict. |

**Open provenance item (L1).** The causal-Lexi MOVE figure is stated in program memory as roughly
**0.48–0.49**. That figure could **not** be located in the repository; the nearest located value is
`encoder-contrast-01/REPORT.md:146` (MOVE 0.381, encoder lane). The causal-Lexi figure must be
pinned from its run receipt before it enters any matrix cell. **Do not record an unverified number
in a matrix.**

---

## 2. Capability axes (frozen)

Structural, per-cell, never free text. These are the `k` in the data axis (§6).

```text
binding                    evidence_support          counterevidence
missing_requirements       conflict                  composition_depth
transition_depth           candidate_comparison      globalization
nuisance_invariance
```

Axis definitions and their measurement predicates are **not** frozen here; they bind to the
response-vector schema (§4) and to whichever bank's targets are admitted by V2-0.

---

## 3. Scale and family identity (frozen)

### 3.1 Two axes are kept separate, always

```text
within-family scale   M varies, architecture and training recipe held fixed
between-family        architecture/training history varies, M roughly matched
```

Reporting must state which axis a comparison moves. A between-family comparison that has silently
also varied scale is void.

### 3.2 Recipe maturity is a third, undeclared confound — record it

Between-family comparisons additionally confound **accumulated recipe knowledge**. A family with a
long experimental trail has had more attempts at target ontology, surfaces, candidate
representation, loss, curriculum and adapters than a fresh one. Any between-family cell therefore
carries a `recipe_maturity` field (`fresh` | `tuned` | `tuned-extensively`) so the confound is
visible rather than absorbed into "architecture."

### 3.3 Available substrates (surveyed 2026-09-30, on-disk)

| substrate | size | family | path root |
|---|---|---|---|
| LFM2.5-230M-Base (causal) | 230M | LFM | `C:\phoenix-target-overgraph\lexi-h2-rebuild-20260930\inputs\lfm2.5-230m-base-9d2be55` |
| LFM2.5-Encoder-230M | 230M | LFM (bidirectional) | `D:\codex-runs\encoder-contrast-01\models\LFM2.5-Encoder-230M` |
| LFM2.5-1.2B-Base | 1.2B | LFM | `D:\codex-runs\jev-lfm-variable-v07\models\lfm2.5-1.2b-base` |
| Qwen3-0.6B-Base | 0.6B | Qwen3 | `D:\codex-runs\jev-zero-training-recon-v01\models\qwen3-0.6b-base` |
| K2-Horizon-0.9B | 0.9B | K2 | `D:\codex-runs\jev-zero-training-recon-v01\models\k2-horizon-0.9b` |
| MiniCPM5-1B-Base | 1B | MiniCPM | `D:\codex-runs\jev-zero-training-recon-v01\models\minicpm5-1b-base` |

**Ladder reality check.** LFM is the only family with a genuine multi-rung pair on disk
(230M → 1.2B, ~5×). **No 350M and no 2.6B substrate exists anywhere**, and MiniCPM has a single
size. So the program currently has **one real ladder (LFM) plus three singletons**. Any claim of a
two-family ladder or a 350M/2.6B rung requires a substrate acquisition step first. Do not write
matrix cells for rungs that have no pinned substrate.

Absent entirely: SmolLM, OLMo, Granite, GGUF/GGML, ONNX weight graphs.

---

## 4. Response-vector schema (frozen)

A cell reports **five separate coordinates and never a composite**:

| coordinate | question it answers |
|---|---|
| `direction` | is the capability signalled in the right direction at all? |
| `gain` | how much probability/margin moved? |
| `boundary_crossing` | did it cross from inaccessible to reliable, or merely move? |
| `locality` | is the effect where it should be (vs sham controls)? |
| `preservation` | did prior capabilities survive the change? |

**Hard rule, inherited from the existing schema:** *no composite capability score is permitted.*
Direction without boundary crossing is not competence. Gain without locality is not the effect you
think it is. Preservation failure disqualifies a gain.

`boundary_crossing` is the coordinate that makes "turns on" operational, and it requires a
**preregistered reliability floor per capability** — which is *not* frozen here, because it depends
on admitted targets.

---

## 5. The five stages (frozen)

| stage | question | failure means |
|---|---|---|
| **1 Accessibility** | can the distinction be recovered at all? | representation/readout problem |
| **2 Acquisition** | can training make it reliable? | data/curriculum problem |
| **3 Composition** | can accessible pieces be combined? | architectural/composability problem |
| **4 Operationalization** | can the state improve the final action? | grounding problem — *good semantic state ≠ good action selection* |
| **5 Robustness** | does it survive renderer, candidate reorder, schema, world-family, sibling and counterfactual shift? | not yet a capability |

Stage 4 is a distinct stage, not a corollary of stage 1, precisely because the program has
replicated evidence that a good semantic state does not produce a good action.

---

## 6. The data axis (frozen): `A_c(N, k; M, I)`

The acquisition object is

\[
A_c\,(N,\ \mathbf{k};\ M,\ I)
\]

- \(c\) = capability
- \(N\) = number of examples
- \(\mathbf{k}\) = **capability-axis coverage vector**
- \(M\) = substrate
- \(I\) = interface

**`N` alone is not a data axis.** 100k examples concentrated on one easy pattern is not equivalent
to 100k examples spanning support, conflict, missingness, composition, transition and nuisance
invariance. Acquisition curves are plotted against **coverage** with `N` as a secondary label.

**Consequence to state plainly in every acquisition report:** with O1 yielding **zero**
permission-cleared human roots, acquisition curves are currently **synthetic-only** until source
permissions resolve. A synthetic-only curve is a real measurement; it is not evidence about
human-grounded data and must not be described as such.

---

## 7. Interface budget (frozen) — the gate on "substrate limit"

Before any backbone adaptation is invoked on a rung, that rung declares and **exhausts** an
interface set on **its own task**:

```text
Rung interface budget
---------------------
I1  linear readout
I2  small nonlinear readout
I3  larger reasonable nonlinear readout
I4  high-capacity frozen-feature oracle
I5  structured graft
I6  task-specific recurrence, if earned on this rung
I7  micro-LoRA / backbone adaptation   <- only reachable after I1..I6 are exhausted
```

**Only after I1–I6 are exhausted on the current rung's current task** may a residual be described
as having survived reasonable access machinery. Only then is I7 a legitimate next move.

The interface set for a rung is **declared before the rung runs**, so that "reasonable" cannot be
defined retroactively by whatever happened to be tried. This is the direct inheritance from Jev
v0.4 gate A, generalized: gate A failed because saturation was never established, and the fix is a
declared budget plus a named saturation predicate, not a stronger claim.

---

## 8. Graduation predicate (structure frozen; thresholds not)

A rung graduates upward when all three hold **on its own task, within its declared interface
budget**:

1. **interface flattening** — the rung's declared interface set has flattened (the rung-local
   analogue of Jev gate A: a named terminal transition plus declared controls, not a vibe);
2. **data diminishing returns** — more capability-targeted data, measured on the coverage vector
   not the raw count, gives diminishing gains;
3. **replicated residual identity** — the same residual failure families persist across at least a
   few materially different interventions, quantified by family-level Jaccard overlap.

**The handoff artifact is the residual set, not the old benchmark.** The next-size sibling begins by
facing exactly what killed its little sibling. This mechanism already exists and is quantitative —
`jev-frozen-saturation-v04` reports `larger_preserves_residual_family: true` and
`oracle_preserves_residual_family: true` over 456 families — so it is adopted rather than invented.

**Rule against premature graduation:** a rung that skipped an interface because it "obviously
wouldn't help" has not flattened. Undeclared skipped interfaces are recorded as undeclared, and
condition 1 fails.

---

## 9. Residual-family identity (frozen)

Failure families are identified by **stable ids**, compared by Jaccard overlap, and carried
forward as the next rung's exam. They are never summarized away into a single failure rate, because
the identity is the information: *which* families persist is what distinguishes a data wall from an
architecture wall from a composition wall.

---

## 10. Interpretation rule (frozen)

> No rung failure may be reported as a substrate deficit until a **rung-local** interface
> saturation check exists for that rung's task.

This is the rule that prevents re-buying the Jev mistake, and it is symmetric: it protects a rung
from being understated (as MiniCPM's causal lane was nearly) and from being overstated (as the
encoder lane nearly was).

Corollary, also frozen: **IHA-style cross-head mixing has no definition in this program.** It
appears in the repository only as a twice-deferred, never-expanded phrase. Any matrix cell or rung
that depends on IHA is **unspecifiable** until it is defined, and defining it is a separate
frozen artifact.

---

## 11. Program state and ordering

```text
V2-0
  ↓
admissible target set                     (V2-0 dispositions applied)
  ↓
capability matrix, populated with valid cells only
  ↓
smallest-rung accessibility / acquisition
  ↓
rung-local interface saturation gate
  ↓
constructive interventions (I5, I6, I7 in order)
  ↓
graduation upward, carrying the residual set
```

**MiniCPM may continue its causal Phase 0/1 System 1.5 interface.** That work is not invalidated
by Jev v0.4 gate A, which is scoped to a different program. It inherits exactly one rule: §10.

**Lexi remains frozen.**

**No micro-LoRA yet** — not by fiat, but because no rung has yet exhausted a declared interface
budget on any task.

---

## 12. What remains unfrozen, and who unfreezes it

| unfrozen item | unfrozen by |
|---|---|
| capability cells and target membership | V2-0 disposition |
| target weights | V2-0 disposition |
| thresholds tied to V2 semantics | V2-0 disposition |
| which interventions each rung must run | per-rung contract, after V2-0 |
| reliability floors per capability | after cells are admitted |
| the causal-Lexi MOVE figure (L1) | its run receipt |
| IHA definition | a separate frozen artifact |
| 350M / 2.6B substrates | a substrate acquisition step |
| concrete axis measurement predicates | after cells are admitted |

No cell may be populated from any of the above before it is unfrozen by its named owner.
