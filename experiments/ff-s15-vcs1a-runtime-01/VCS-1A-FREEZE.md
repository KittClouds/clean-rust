# VCS-1a freeze (2026-09-30)

The VCS-1a runtime machinery is frozen. `vcs1a-freeze.json` holds the sha256 of every file in `vcs/`, the synthetic golden fixtures and this record; `python tools/check_freeze.py` fails if any of them changes, and a test runs it.

Claudia now waits for Lepori's **operational** schema (observable or derived semantic coordinates, with an estimator per substrate), not merely the atlas schema. VCS-1b is not run against the current atlas.

## The eventual question (VCS-1b)

> Does a vector of observable semantic state outperform the best scalar authority rule at matched harm, coverage and acquisition cost?

## Conventions frozen here

1. **Dispositions and receipts.** EXECUTE(action), ASK(requirement), ESCALATE(reason), DECLINE_UNAVAILABLE(reason), NOOP; receipts carry the truth value of every region, the matched and unknown rules, the schema hash and the representation id, and replay byte-identically.
2. **Region semantics.** Exact rational arithmetic; the stated operator decides a boundary; Kleene three-valued logic; a missing or inapplicable coordinate makes a leaf unknown unless the leaf says otherwise; an unknown region never fires a rule; overlap is `first_match` (declaration order) or `conflict` (an author-declared conflict disposition).
3. **Matched comparison.** The vector policy is matched to the best scalar point with harm <= the vector's AND cost <= the vector's (inclusive, tolerance 1e-12). The coverage margin is the vector's coverage minus that scalar's; the harm margin is the symmetric quantity at matched coverage and cost.
4. **`dominates`.** If no scalar point is simultaneously no worse on harm and no worse on cost, `dominates = true`, the coverage margin is undefined (`None`, never an infinity and never zero), and the bootstrap reports `dominates_fraction` and `p_credit` (the share of resamples in which the vector policy dominates or has a positive margin).
5. **Two scalar comparisons, both kept.**
   - *Transported scalar:* chosen on TRAIN, frozen, applied unchanged. Reported per split with drift from TRAIN and as an explicit point comparison (`vs_transported_scalar`: differences, weak and strict dominance).
   - *Hindsight scalar:* the frontier re-tuned on the evaluated split, recomputed on every bootstrap resample. It is an upper bound that unfairly favours the scalar; beating it is the strong claim, beating only the transported scalar is a statement about transport geometry.
6. **A nasty scalar comparator is allowed.** A scalar source may be a list (a family: an observer's confidence, single coordinates, a fitted linear combination, ...). The scalar frontier is the union of the members' frontiers, so more scalar competition can only lower the vector's margin.
7. **Transport.** `fit` receives TRAIN cases only; the authorities are frozen (their ids are checked unchanged after every split); the same frozen authority is applied unchanged to DEV, renderer shift and representation shift.
8. **Substrate comparison.** One canonical semantic state is the common reference frame; each substrate supplies an *estimated* state for the same cases (same ids, truth and context; only the envelope differs). The same frozen authority is applied to the reference and to every substrate. Output: metrics, shortfall versus the reference, typed-disposition agreement and the confusion matrix, unknown-region rate. Substrates are not compared through head confidence.
9. **Evidence grading and circularity guard.**
   - A FIXTURE schema marks every output "NONE (fixture schema)".
   - A FROZEN schema is scored only under a preregistration file (its hash is recorded).
   - A FROZEN schema must declare, for every coordinate, a derivation audit: `target_derived` (is the target literally derived from this field), `downstream_of_target` (is the field computed after or from the target), `shared_generator` (does the field share generator logic with the target). A coordinate with `target_derived` or `downstream_of_target` true makes the run refuse to score (exit 2); `shared_generator` true is allowed and listed in the output. This is the circularity that bit VCS-0: a region over such a coordinate rediscovers the label-generation function and calls it geometry.

## What VCS-1b needs before it may start

1. Lepori's frozen operational schema: a `VCS_SCHEMA_DECL_V1` with `status: FROZEN`, a named owner and the derivation audit on every coordinate; the coordinate meanings and normalization; the estimator for each substrate (causal 230M, encoder 230M) that produces the estimated state.
2. The candidate coordinates must vary independently of the target disposition. The preregistration states how that was established (beyond cheap predictive cues: literal derivation, downstream position, shared generator logic).
3. A preregistration naming the scalar family (including a fitted scalarizer and the observer confidence), the matching rule above, the splits and transport definition, the decision rules and the substrate comparison. Frozen before any scoring, then score once.
4. BANK-v2 stays off limits to Claudia until V2-0 freezes its cue audit; Claudia asks that V2-0's audit report coordinate-target derivational dependence (item 9's three questions) alongside cheap predictive cues. V2-0 is the BANK agent's; nothing here edits it.

## Amending this freeze

A change to a frozen file needs a dated `AMENDMENT-<date>.md` stating what and why, a new `check_freeze.py --seal`, and must happen before the VCS-1b preregistration is frozen. After that, no change.
