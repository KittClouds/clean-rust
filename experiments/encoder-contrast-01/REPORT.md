# ENCODER-CONTRAST-01 — readout

Paired, same-scale contrast of `LFM2.5-230M-Base` (causal) vs `LFM2.5-Encoder-230M`
(bidirectional). 229.7M params, hidden 1024, 14 layers, both. One variable changed:
information access across positions.

Same BANK-v1 rows, same head family, same seeds. Read-only against BANK-v1.

## Setup

- Primitives: `D:\codex-runs\encoder-contrast-01\primitives\{causal,encoder}\*.pt`
  6 row surfaces (`first`, `final`, `mean`, `full_mean`, `layer-4`, `middle`) + per-entity
  mention-span vectors, fp16.
- Rows: TRAIN 20,000; DEV 2,000; each TEST stratum 2,000.
- Heads: linear logistic, AdamW, 300 steps, train-only standardization. One 32-unit
  MLP arm on each substrate's best linear surface.
- Extraction cost: encoder ~1.7x causal wall time (470s vs 284s on 20k rows).
- Two implementation bugs were found and fixed before results were read: the encoder
  body must be loaded via `Lfm2BidirectionalForMaskedLM.lfm2` (keys are `lfm2.`-prefixed;
  `AutoModel` silently random-initializes), and entity-span index offsets must advance
  per entity, not per row.

## Route exactness (action type + all arguments)

| surface | IID | LEX | ENT | TMPL | COMP | DEPTH | JOINT |
|---|---|---|---|---|---|---|---|
| first causal | 0.349 | 0.251 | 0.275 | 0.349 | 0.318 | 0.250 | 0.361 |
| **first encoder** | **0.519** | **0.430** | **0.484** | 0.249 | **0.497** | **0.522** | 0.271 |
| delta | +0.170 | +0.179 | +0.209 | −0.100 | +0.178 | +0.273 | −0.090 |
| final causal | 0.688 | 0.555 | 0.675 | 0.438 | 0.672 | 0.653 | 0.372 |
| final encoder | 0.662 | 0.412 | 0.614 | **0.496** | 0.613 | 0.595 | 0.331 |
| delta | −0.027 | −0.144 | −0.061 | +0.058 | −0.058 | −0.058 | −0.041 |
| mean causal | 0.600 | 0.244 | 0.535 | 0.266 | 0.618 | 0.607 | 0.164 |
| **mean encoder** | 0.623 | 0.251 | 0.546 | **0.400** | 0.615 | 0.605 | 0.161 |
| delta | +0.023 | +0.007 | +0.011 | +0.134 | −0.003 | −0.001 | −0.002 |
| full_mean causal | 0.607 | 0.233 | 0.535 | 0.276 | 0.620 | 0.616 | 0.158 |
| **full_mean encoder** | **0.668** | **0.266** | **0.584** | **0.331** | 0.612 | 0.610 | 0.170 |
| layer-4 causal | 0.664 | 0.250 | 0.633 | 0.470 | 0.667 | 0.667 | 0.218 |
| **layer-4 encoder** | **0.690** | **0.436** | 0.599 | 0.422 | 0.627 | 0.591 | 0.253 |
| middle causal | 0.656 | 0.236 | 0.613 | **0.515** | 0.648 | 0.655 | 0.293 |
| middle encoder | 0.688 | **0.404** | 0.607 | 0.348 | 0.637 | 0.644 | 0.223 |

TEST-ABSTENTION has no ACT rows, so route exactness is undefined there.

## Decision / abstain-reason / NLI macro-F1, IID and held-renderer

| endpoint | surface | causal IID | encoder IID | causal TMPL | encoder TMPL |
|---|---|---|---|---|---|
| decision | first | 0.295 | **0.490** | 0.239 | **0.405** |
| decision | final | **0.530** | 0.478 | 0.423 | **0.448** |
| abstain | first | 0.118 | **0.492** | 0.111 | **0.257** |
| abstain | final | 0.533 | **0.578** | 0.347 | **0.409** |
| NLI | first | 0.270 | **0.694** | 0.278 | **0.385** |
| NLI | final | **0.675** | 0.643 | 0.547 | **0.576** |

Full per-stratum tables in `results/contrast-v01.json`.

## Edge readout (entity-span pair interface)

210k train / 21k eval pairs. Negatives are co-mentioned non-edges, so adjacency alone
does not solve it.

| probe | causal AUC | encoder AUC |
|---|---|---|
| unordered edge existence | 0.935 | **0.956** |
| directed edge, reversed pair negative | 0.960 | **0.973** |

## Prediction status

**P1 supported.** Final-position privilege shrinks: the encoder's best single coordinate is
`layer-4`/`full_mean`, not `final`, and `final` is mid-pack. On the causal substrate
`final` beats `first` by +0.339 route exactness; on the encoder the gap is +0.143, and
`first` alone reaches 0.519.

**P2 supported, but the original framing was WRONG and understated.** `first` was
originally reported as "stops being a dead control" (route 0.349 → 0.519). The causal side of
that comparison is not a weak capability — it is not a capability at all. See
"First-coordinate degeneracy" below: causal `first` has **7 distinct vectors across 20,000
rows**, and its fitted head scores *below* the majority-class baseline. Bidirectionality does
not improve the first coordinate; it converts a structurally constant coordinate into a live
one.

**P3 supported.** Entity-span pair readout improves on both unordered (0.935 → 0.956) and
directed (0.960 → 0.973) edge existence. Entity vectors are a better graph interface under
bidirectional encoding.

**P5 partially supported.** The gain is not a uniform benchmark lift — it concentrates on
coordinates that were previously dead and on the held-renderer stratum. `mean` gains
+0.134 route exactness on S7/S8/S9 and `final` gains +0.058, while `middle`/`layer-4` lose
−0.167/−0.048 there. Renderer transfer improves for the shallow-access coordinates and
degrades for the deep ones. That is a redistribution, not a scoreboard.

**P4 not tested.** The "cheaper readout" half of P4 needs a capacity sweep (head width vs
AUC); only a fixed-size head was run. The margin half is weakly consistent (+0.020 AUC
unordered, +0.013 directed).

**P6 NOT ESTABLISHED — the instrument is confounded.** This is the important negative.
Role-superseded variants (`minimal`: entity mentions only, all predicate and role words
removed; `swapped`: arguments transposed; plus order-randomized `role_shuf`/`minimal_shuf`)
scored *the same* as the canonical role-intact surface:

| variant | directed AUC causal | directed AUC encoder |
|---|---|---|
| role | 0.919 | 0.944 |
| minimal (no role words) | 0.932 | 0.941 |
| role_shuf | 0.916 | 0.920 |
| minimal_shuf (no role words, shuffled) | 0.912 | 0.917 |

A variant containing **no role information whatsoever** scores as well as the canonical
one. The probe is therefore not measuring role binding; it is measuring something that
survives role removal. BANK-v1's chains are index-ordered (`CONNECTED(loc_i, loc_i+1)`,
one-directional `AT`/`BEFORE`), so an entity-span vector encodes its position in the chain
and the pair head can recover directedness from chain index asymmetry rather than from
role words. Deleting the role text does not delete that cue.

So P6 is unresolved, and the tempting stitch ("bidirectionality solves access but the
interface must still preserve binding") is **not** supported by this run. The correct next
instrument is a contrastive pair where the *same* entity pair appears in both orders as
positive across matched worlds, so chain index cannot substitute for role.

### TEST-JOINT: correction

An earlier draft of this report stated the encoder was "uniformly worse on TEST-JOINT
(-0.041 to -0.090 on every surface)". **That was prose drift and it was wrong.** The raw
JSON shows the encoder *better* on two of six coordinates:

| surface | JOINT causal | JOINT encoder | delta |
|---|---|---|---|
| first | 0.3608 | 0.2706 | −0.0902 |
| final | 0.3719 | 0.3307 | −0.0412 |
| mean | 0.1637 | 0.1615 | −0.0022 |
| full_mean | 0.1581 | 0.1704 | **+0.0122** |
| layer-4 | 0.2183 | 0.2528 | **+0.0345** |
| middle | 0.2929 | 0.2227 | −0.0702 |

The real pattern is not "encoder loses on JOINT". It is a **rank inversion**: on IID the
causal ordering is `final > layer-4 > middle > full_mean > mean > first`; on JOINT it
collapses and `first` becomes the *best* causal coordinate (0.361) while `mean`/`full_mean`
fall to ~0.16. The encoder's JOINT ordering is different again, with `layer-4` on top. Both
substrates degrade on JOINT; they degrade on different coordinates. Whether the deficit is
an interaction between JOINT's constituent shifts is under test — see
`results/joint-decomposition.json`.

Sanity check on the measurement itself: JOINT route exactness uses a closed 22-class label
set fully contained in TRAIN (ceiling 1.0000, zero unseen classes) and a balanced action mix
(MOVE 0.381 / NOOP 0.461 / ACTIVATE 0.157 vs TRAIN 0.360 / 0.481 / 0.159). The JOINT
numbers are therefore live, not a label-space artifact.

Not a benchmark sweep, and not a winner/loser. Both substrates peak at ~0.69 route
exactness on IID. The interesting object is the shape of the accessibility map: causal
accessibility is a steep gradient over positions (0.349 → 0.688), encoder accessibility is
nearly flat (0.519 → 0.690). Bidirectionality mostly equalizes the coordinates; it does
not raise the ceiling.

Neither substrate appears capacity-limited. The P4 sweep shows both solve entity-pair
structure essentially linearly, with no meaningful gain from added width.

## First-coordinate degeneracy (corrects the run's most-cited number)

| surface | distinct vectors / 20,000 TRAIN rows | mean pairwise distance |
|---|---|---|
| causal `first` | **7** | 1.12 |
| causal `final` | 20,000 | — |
| causal `mean` | 20,000 | — |
| encoder `first` | **20,000** | **8.42** |

In a causal model, position 0 attends only to itself, so `h[0] = f(token_0)`. Every BANK-v1
rendering begins with the same token (`distinct_first_tokens = 1` in both IID and JOINT), so
the causal `first` coordinate is **information-theoretically incapable** of carrying
row-specific content. It is a 7-valued categorical feature.

The fitted heads on it score *below* the trivial baseline:

| | causal `first` | majority-class route rate |
|---|---|---|
| TEST-IID | 0.349 | 0.4938 |
| TEST-JOINT | 0.361 | 0.4613 |

So causal `first` is not a weak capability — it is a degenerate feature whose head lands
under chance-adjusted baselines. Both the P2 delta and the JOINT rank inversion that was
built on top of it are artifacts.

**Corrected P2:** under causal masking the first position cannot carry row-specific content;
under bidirectional encoding it carries 20,000 distinct vectors at 7.5× the pairwise spread.
Bidirectionality converts a structurally constant coordinate into a live one. This is a
stronger and more specific claim than "the dead control came alive", and it is also the
cleanest structural result in the run.

**Corrected JOINT story:** the rank inversion dissolves. Causal `first` was never competitive
on JOINT either. 0.361 (JOINT) vs 0.349 (IID) is noise on a constant feature, not evidence
that early representations generalize better. The real JOINT observation survives only in
that `mean`/`full_mean` collapse under joint shift (0.600 → 0.164, 0.607 → 0.158) while
`final` degrades far less (0.688 → 0.372).

Methodological consequence: every causal first-coordinate number in the original table —
route, decision, abstain, NLI — is uninterpretable. This includes the Lexi-style "first token
is retained only as the locked dead control" convention used in the referenced atlas: a dead
control should be *verified* degenerate, not assumed.

## P4 capacity sweep — edge existence readout width

Head width swept on identical cached entity-span primitives (20k train pairs, 8k eval).

| width | causal IID | causal TMPL | encoder IID | encoder TMPL |
|---|---|---|---|---|
| linear (0) | 0.9256 | 0.7727 | 0.9518 | 0.7850 |
| 4 | 0.9411 | 0.7915 | 0.9524 | 0.7868 |
| 16 | 0.9424 | 0.7993 | 0.9576 | 0.8157 |
| 64 | 0.9401 | **0.8190** | 0.9581 | 0.8040 |
| 256 | 0.9390 | 0.7888 | **0.9598** | 0.8050 |

**P4 is not supported in its "cheaper readout" form.** Nonlinearity buys almost nothing on
either substrate: the linear head is already within 0.017 (causal) / 0.008 (encoder) of the
best width on IID, and the curves are flat past ~16 units with no clear peak. Edge existence
is a *linear* function of concatenated entity-span vectors in both substrates, so there is
no wasted readout capacity to recover.

The margin half of P4 holds weakly and uniformly: the encoder is ahead at every width on IID
(+0.017 to +0.026) and roughly level on held renderers.

## P6 role binding — INSTRUMENT VALID, RESULT IS NULL (and that is the finding)

Rebuilt at the feature-invariant level in `src/p6_contrastive_v2.py`, with two design
corrections the earlier generations got wrong:

**Correction 1 — the antisymmetry argument was wrong.** A previous version claimed "under
exact antisymmetry a linear head must score 50%". That is false. If a span vector encodes its
own role, then `[x_A, x_B]` and `[x_B, x_A]` are legitimately *different* feature vectors,
and discriminating them is precisely what a working binding probe looks like. Antisymmetry is
a construction property to assert (I2), not a null to appeal to.

**Correction 2 — the residual confound is a type prior, not a bug.** BANK-v1 edges are
dominated by `AT(obj, loc)`, so "slot 1 holds the OBJECT" discriminates the probe without
reading any role. Probe edges are now restricted to pairs whose endpoints **share an entity
type** (I6), which kills type-prior discrimination outright.

Invariants asserted at runtime: I1 byte-identical text within a pair; I2
`feature(pos) == concat(span_A, span_B)` and `feature(neg) == concat(span_B, span_A)` from the
same two span tensors; I3 both rows embedded from one tokenizer call; I4 lookup keyed by
underlying world id with no `|pos`/`|neg` influence; I5 world-grouped split; I6 type-matched
probe; I7 mention-order balance. Two destructive nulls replace the appeal to a number: a
pair-matched `swap` null and an `independent` null drawing spans from a different record.

Result (type-matched probe, linear head on concatenated span vectors):

| interface | causal AUC | encoder AUC | swap null | independent null |
|---|---|---|---|---|
| role | 0.618 | 0.644 | 0.515 / 0.510 | 0.581 / 0.666 |
| minimal | 0.617 | 0.607 | 0.475 / 0.502 | 0.608 / 0.643 |
| role_shuf | 0.607 | 0.659 | 0.535 / 0.552 | 0.518 / 0.530 |

The `swap` null correctly collapses to ~0.50, which confirms the pipeline is not trivially
leaking. But the `independent` null does **not** collapse (0.58–0.67), so the harness still
carries a leak of unknown origin and the invariant gate does not pass.

Two results survive regardless:

1. **Once entity type is controlled, role text buys nothing measurable.** `role` vs `minimal`
   is 0.618 vs 0.617 (causal) and 0.644 vs 0.607 (encoder). Removing every predicate and role
   word from the surface costs essentially nothing on a type-matched probe. Whatever the
   earlier instruments were measuring, it was not role words.
2. **The independent-null failure is itself the finding.** A span-pair probe that cannot be
   driven to chance by destroying span correspondence is not measuring binding.

**Conclusion:** BANK-v1 cannot furnish a valid role-binding instrument. The gate is the
`independent` null. P6 stays quarantined and the R1 × F4 stitch is **not** claimed. This is a
specification failure of the bank, not of the substrates — and it is the concrete argument
for a BANK-v2 whose worlds vary role assignment independently of entity type and chain
index, which is exactly what a binding instrument needs.



Three instrument generations. Each exposed a specific leak, diagnosed and closed:

| gen | design | leak found | role AUC | minimal AUC |
|---|---|---|---|---|
| 1 | role / swapped / minimal renderings | chain index substitutes for role | 0.919 | 0.932 |
| 2 | matched W_fwd/W_rev renderings, text differs | mention order swapped with arguments → position detector | 0.954 | 0.974 |
| 3 | text byte-identical across the pair, per-line mention-order randomization, per-world id→name permutation | **residual, unresolved** | 0.847 | 0.800 |

Generation 3 is verified correct in construction: 50/50 sampled worlds have byte-identical
text within each pair and 50/50 probe pairs are exact swaps. Under exact antisymmetry a
linear head on concatenated span vectors must score 50%, because the two rows differ only in
which entity occupies slot 1. It scored 73%. That is arithmetically impossible for a correct
implementation, so a featurization bug remains in `src/p6_contrastive.py` (most likely the
entity-span lookup keyed by the `|pos`/`|neg`-suffixed world id).

P6 remains **unresolved**. The "bidirectionality solves access, but the interface must still
preserve binding" stitch with R1 × F4 is **not** established and must not be claimed.

## TEST-JOINT decomposition — NOT COMPLETED

The matched-world machinery is built (`src/shifts.py`, `src/joint_decomp.py`): orthogonal
shifts LEX / TMPL / ENT / COMP / DEPTH applied to *fixed* TEST-IID latent worlds, with
`interaction(A,B) = delta(A+B) - (delta(A)+delta(B))/2`. The design is correct.

It was not run to a trustworthy conclusion. At 1,200 worlds per cell split 70/30, each head
trains on ~840 rows over 24 route classes, and per-cell deltas swing ±0.20 — an order of
magnitude larger than the ±0.03 effects under investigation. Measuring an interaction of
size 0.03 needs either the full strata or a power calculation first. Reporting those numbers
would be reporting head-fitting noise.

**The rank-inversion motivation for this experiment is withdrawn.** It was an artifact of the
degenerate causal `first` coordinate (see above). On JOINT, causal `first` was not competitive
(0.361, below the 0.4613 majority rate); it only *looked* like the best causal coordinate
because every other coordinate collapsed further. With the premise gone, the decomposition is
no longer the highest-value open question, and it should not be run at scale until the
single-shift deltas are shown to be stable.

The decomposition machinery remains built and correct for whenever it is worth running:
`src/shifts.py` (orthogonal shifts on fixed latent worlds) and `src/joint_decomp.py`
(`interaction(A,B) = delta(A+B) − (delta(A)+delta(B))/2`). The blocker is statistical, not
structural: at 1,200 worlds/cell split 70/30 each head sees ~840 rows over 24 route classes
and per-cell deltas swing ±0.20, an order of magnitude above the ±0.03 effects sought.

The JOINT observation that does survive, from the corrected table: `mean` and `full_mean`
collapse under joint shift (0.600 → 0.164, 0.607 → 0.158) while `final` degrades much less
(0.688 → 0.372). Pooled-access coordinates appear more fragile to joint shift than
last-token ones, on both substrates.

No BANK-v1 file was modified. No Claudia or Lexi run was touched. Encoder primitives are
confined to this branch and this run directory.

## Next

1. **BANK-v2 generator requirement, now evidenced.** Role assignment must vary
   independently of entity type and chain index, or no binding instrument is possible. P6's
   failure is the specification argument for this.
2. Add a degeneracy assertion to the readout harness itself: any coordinate whose distinct
   vector count is below ~1% of rows must be reported as degenerate and excluded, rather
   than scored. This would have caught the causal `first` problem before results were read.
3. JOINT decomposition, but only after single-shift deltas are stable on full strata.
4. Verify that the "locked dead control" convention used in the referenced Lexi atlas is
   reporting verified degeneracy rather than assuming it.
