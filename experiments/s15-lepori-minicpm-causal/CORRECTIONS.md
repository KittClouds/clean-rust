# Correction ledger — Lepori causal lane

Every entry is a correction to something I previously wrote, with the evidence that forced it.
Ordered newest first. Nothing here is a retcon of a measurement; where a measurement stands it
is restated unchanged.

## C14. Reciprocal mean candidate count is not expected row-wise random accuracy

For a random policy choosing uniformly within each world's candidate set,
expected exact accuracy is `mean(1 / m_i)`, not `1 / mean(m_i)`. They differ when
cardinalities vary. Qwen's independently replayed 931-row eligible DEV subset
gives 0.0801 versus 0.0637. C9's measured reciprocal-mean values remain historical
descriptive statistics, but its labeling of them as exact "true chance" is too
strong. No old score is overwritten and no new chance statistic enters selection.

## C13. Qwen preparation exposes additional historical harness defects

**Scope:** source audit on 2026-10-01, not a rerun or a reconstructed execution
seal. Original receipts do not bind all inspected source bytes, so these findings
qualify interpretation without inventing corrected historical scores.

- `src/phase1.py`: training obtains `pair_context(dv, ...)` and
  `renderer_pairs("DEV", ...)`; consistency gradients therefore use DEV features.
- `src/phase1b.py`: the declared retained pair loss is absent from the training
  total. Its `js_penalty` has `@torch.no_grad()`, detaching the variance penalty.
- `src/data.py`: candidate argument indices use `raw_base + ordinal - off`, but
  `CausalGraft.candidate_states` indexes the global packed entity tensor. With
  equal raw/packed offsets, later rows address the first world's entities instead
  of their own. Correct addressing is `packed_offset + local_ordinal`.
- `src/graft.py`: padded action scores are multiplied by zero. Zero does not
  exclude a class from softmax/argmax and can beat negative valid scores.
- The inspected top-up `reorder` constructs positions from the new ordering and
  uses them to index old arrays. Whether a particular historical order changed is
  not established here. Qwen independently re-extracts features, using historical
  caches only for row-ID population identity.

**User decision:** repair Qwen only; retain MiniCPM as a historical reference.
No old checkpoint, tensor cache, or numerical receipt is overwritten. The new
trial has TRAIN-only consistency, correctly identity-aligned entity indices,
differentiable variance loss and excluded padded action classes. It is therefore
not a strictly substrate-only, fully matched MiniCPM/Qwen comparison.

**Interpretation:** the old isolation result cannot cleanly rule out objective
competition; source/graft/harness-level negatives do not convict the raw substrate.
The initialization probe result supports `ACCESSIBLE_AT_INIT=yes`,
`ACQUIRED_BY_TRAINING=no evidence`, and a slightly negative measured probe delta.
It is not proof that training can never acquire legality. C12's positive-control
stop rule is mandatory for the repaired recoverability instrument.

---

## C11. "MOVE is provably capped at ~0.37" — **withdrawn; the 0.37 was an estimator, not a bound**

**Was:** legality-only state caps MOVE at ~0.37, so a recurrent action workspace over legality
state was never going to fix MOVE.

**Why that was wrong.** The 0.3699 was the **1-NN result**, not a MOVE-specific determinism
ceiling. Review was right that only a within-MOVE grouping supports the claim. Computed
properly, by grouping worlds whose true action is MOVE and taking the largest agreeing subset
inside each gold-state group:

| gold state | MOVE ceiling | MOVE 1-NN | ACTIVATE ceiling | NOOP ceiling |
|---|---|---|---|---|
| L1 legality only | **0.9335** (n=346) | 0.3699 | 0.9733 | 1.0000 |
| L2 + `candidate_satisfies_goal` | **0.9942** | 0.9306 | 0.9867 | 1.0000 |
| L4 + `optimal_next_actions` | 1.0000 | 0.9855 | 1.0000 | 1.0000 |

So **MOVE is not information-capped at 0.37.** Legality-only state contains enough information to
identify the logged MOVE choice in 93.35% of cases, and the 0.37 figure is the weakness of a
crude 1-NN extractor, not an information bound. There is a large **estimation** gap, not an
information gap, and those call for different responses.

**What survives.** The practically decisive point is unchanged in force but restated honestly:
legality-only is **not crudely learnable** (1-NN 0.3699 on MOVE), whereas legality + the
goal-relative channel is (1-NN 0.9306). Adding the goal channel is what makes the endpoint
*learnable by a simple estimator*, and that is why a workspace built only over legality state
remains a poor bet — not because it is provably impossible, but because it starts from a
representation where the distinction is 0.37-achievable at best under simple extraction.

Also recorded: these ceilings are **in-sample DEV statistics** (grouping DEV worlds with identical
gold state), so they bound what a memorising extractor could achieve, not what a generalising
learner achieves. Stated that way in the receipt.

Receipt: `gold-sufficiency-addendum.json`.

---

## C12. Recoverability readout arms all returned exactly 0.5000 — my probe was broken, not the representation

The first run of the recoverability ladder returned **exactly 0.5000 balanced accuracy on every
arm, including the capability control** that the production head solves at 0.7495. A uniform
0.5000 is the signature of weights that have gone NaN, not of a representation lacking
information, so I debugged before reporting anything.

**Cause:** padded candidate slots carry `NaN` labels, and the loss computed
`(l * mask).sum() / mask.sum()`. `NaN * 0` is still `NaN`, so a single padded slot poisoned the
whole sum, the gradient became NaN, and every readout collapsed to a constant predictor. This is
the same class of bug the Phase 0 `semantic_loss` guards against with `torch.nan_to_num`, and I
dropped that guard when writing the probe.

**Verification before trusting the rerun:** a closed-form ridge solve on the same frozen `e_j`
recovered legality at TRAIN 0.7785 / DEV 0.7509, confirming the representation and the metric
were fine and the fault was in the training loop only.

Recorded because a clean 0.5000 across every arm would have read as a strong negative result —
that is, as a substantive finding — when it was an arithmetic bug in my own probe.

---

## C4. "Candidate legality is a property of the interface, not the backbone" — **over-claimed**

**Was:** candidate legality at 0.7495 (MiniCPM) and 0.7509 (encoder) means the capability belongs
to the interface, not the backbone.

**Now:** candidate legality **transfers strikingly across two very different substrates under
related candidate-local interfaces, suggesting that this capability is interface-dominant or
cheaply accessible across substrates.** Two substrates are enough for a strong engineering clue,
not enough to remove the backbone from the causal story.

**Further weakened by C6**, which shows the legality signal comes from the candidate-local branch
`c_j` alone on this lane.

---

## C5. "Capacity isn't the lever" — **over-claimed**

**Was:** capacity isn't the lever; the interface and contract are.

**Now:** increasing substrate size from the encoder/230M regime to 1.08B **did not rescue global
semantics under this interface.** There is currently **no evidence that capacity alone is the
lever.** This preserves exactly what was measured and does not assert the converse.

---

## C6. "Depth redundancy" from the single-surface ablation — **withdrawn**

**Was:** zeroing any one projected `u_i` changed almost nothing, therefore the information is
*redundant across six surfaces*, and there is no privileged layer to aim surgery at.

**Why that reading was wrong.** A single-surface ablation cannot distinguish redundancy from
"the global path is barely used at all". Two joint inference-only ablations settle it:

| ablation | candidate_legal bal acc | Δ |
|---|---|---|
| baseline | 0.7495 | — |
| **all six `u_i` → 0** before `rho_s` | 0.7491 | **−0.0004** |
| **`s` → 0 inside `rho_e`**, `c_j` intact | 0.7499 | **−0.0004** |
| `s` → 0 everywhere | 0.7499 | −0.0004 |

**Candidate legality is produced entirely by `c_j`, the candidate/entity branch. Destroying the
whole six-surface global path costs nothing at all.** So the earlier "redundant across depth"
reading was wrong: the global path was not carrying the load to begin with.

**Consequence.** The identical cross-substrate legality numbers (0.7495 / 0.7509) are explained by
both lanes having a similar candidate-local construction, not by the global path doing transferable
work. Any global-path mechanism aimed at "depth" would have been aimed at an unused path.

Receipt: `joint-surface-ablation.json`.

---

## C7. "Composition gap, not perception gap" — **withdrawn, and replaced**

**Was:** the graft knows which candidates are legal and cannot turn that into which action to take,
therefore the bottleneck is composition.

**Why that was premature.** Action choice needs more than legality — it needs something like
"does this candidate advance the goal". Our `candidate_satisfies_goal` is at **0.5216**, essentially
dead. Legal candidate state plus dead goal-relative candidate state, followed by dead action, is
not yet evidence that composition is the bottleneck. It may simply be missing action-relevant
content upstream.

**Now:** **candidate legality is accessible, but the candidate state is not yet
action-sufficient.**

**And the gold ladder makes it specific** — see the table in `PHASE1.md`. Legality alone has a
determinism ceiling of **0.7605 overall**. The earlier claim that this implied a **~0.37 MOVE
information cap** is withdrawn by C11: 0.3699 was the L1 MOVE 1-NN estimate, while the L1
conditional MOVE determinism ceiling is **0.9335**. Adding the existing
`candidate_satisfies_goal` channel raises the L2 ceilings to **0.9925 overall** and **0.9942 on
MOVE** (with MOVE 1-NN at **0.9306**). The gap identifies an estimator limitation, not an
impossibility result for a recurrent action workspace.

---

## C8. "Lexi's ~75% action may be a majority-class artifact" — **checked, and it is not**

I flagged Lexi's endpoint number for the same de-degeneracy check that caught MiniCPM's. It
passes.

| lane | head shape | overall | MOVE | ACTIVATE | NOOP |
|---|---|---|---|---|---|
| Lexi (causal, LFM2.5-230M), P2-CONSIST | **correct** `[B, m]`, argmax over `m` | **0.7492** | **0.4770** (n=369) | **0.8400** (n=150) | 0.9631 (n=406) |
| Lepori (causal, MiniCPM5-1B), P1 | **correct** `[B, m]`, argmax over `m` | 0.4672 | **0.0000** (n=346) | **0.0000** (n=150) | 1.0000 (n=435) |

Lexi's strongest *measured* trivial baseline is 0.1308, and MOVE's is 0.1870, so Lexi's MOVE at
0.4770 is above the measured trivial baselines, so the endpoint is not explained by majority-class
degeneracy. This establishes a measured lane difference, not a substrate-only effect: the graft
and training configuration also differ. Lexi reported measured trivial baselines rather than an
analytic "chance" rate.

---

## C9. The encoder lane's action endpoint is mis-shaped — and the defect ran the *other* way

Lineage audit across all three lanes:

| lane | head | shape | verdict |
|---|---|---|---|
| Encoder | `nn.Linear(d_e, m_cap)` at `graft.py:140` | `[B, m, m_cap]`, CE over **flattened `m·m_cap`**, argmax over flattened | **mis-shaped** |
| Lexi | `nn.Linear(epistemic_dim, 1)` | `[B, m]`, CE over `m`, argmax over `m`, padding `-1e9` | correct |
| Lepori (this lane) | `nn.Linear(d_e, 1)` | `[B, m]`, CE over `m`, padded masked to 0 | correct |

I previously wrote that this invalidated the encoder's Phase 4A "action crossed chance". Having
measured it, the correction is **larger than I said and points the other way**: the encoder's
reported chance of `1/28 = 0.0357` is **1.78× too low**. The correct chance is `1/15.69 = 0.0637`.
So the encoder's best action result, 0.0451, is **0.71× of true chance** — worse than reported,
not better. The encoder's "never beats random choice" verdict survives with a *larger* margin
(0.0451 vs 0.0637, not 0.0451 vs 0.0357).

Phase 1 of the encoder reported chance `1/24 = 0.0417`; the correct value is `1/13.53 = 0.0739`,
again 1.77× too low, and the encoder's 0.0118 is 0.16× of true chance.

---

## C10. Per-surface standardisation: the "6× scale change" justification was the wrong statistic

**Was:** the final layer is ~6× smaller than mid-depth, so per-surface standardisation is
mandatory.

**Why:** that 6× was a **token-level** standard deviation across all sequence positions. The
relevant quantity for a pooled per-row surface is the **row-level** pooled standard deviation,
measured on real BANK data:

```
lt@24 3.85   mf@24 2.84   ms@24 2.95   mf@18 4.50   mf@12 2.03   mf@6 1.38
```

a spread of **1.58×** relative to the final surface, 3.3× between shallowest and `mf@18`.
Per-surface standardisation is still correct and still applied, but the honest justification is a
1.6–3.3× spread, not 6×. Both statistics are recorded in `surface-stats.json`.

**A more serious version of the same class of bug was also found and fixed:** the first extractor
standardised by **per-batch** mean and std, so DEV rows were standardised with DEV batch statistics
and the cache was not replayable. Surfaces are now stored raw, statistics are fitted on TRAIN
canonical rows only and frozen. Verified: post-normalisation per-surface std is exactly 1.0 on
TRAIN and 0.9928–1.0047 on DEV.
