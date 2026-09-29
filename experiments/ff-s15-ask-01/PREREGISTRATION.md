# ASK rung preregistration — can a cheap observer be built specifically for "should we ask?"

Written 2026-09-29, **before** any dedicated ASK head is trained. Scoring code refuses to read HOLD unless this file's SHA-256 matches the hash recorded at freeze.
Changes go in an addendum with the reason; the criteria and verdict rules are not edited afterwards.

## Question

C1 gave the cheap tier no ASK capability. C2a showed that combining more surfaces of the same backbone does not help. The ASK rung asks one thing:
**can a dedicated head, trained only to answer SHOULD_ASK vs DO_NOT_ASK on the locked 230M surfaces, beat the existing decision head's ASK signal enough to give the controller a usable ASK rule?**
Linear first; a tiny MLP only if the linear head leaves obvious headroom (defined below). No new backbone, no coordination, no 1.2B, no ASK heuristic, no reason head yet.

## What ASK is in BANK (TRAIN-only reading, done before this plan)

In TRAIN every ASK row has exactly one missing fact (`missing_fact_count` = 1.0) and the policy is always `REQUEST` a fact; ACT rows have none; ABSTAIN rows mostly lack it for other reasons
(mean 0.23). So ASK is "a required, requestable fact is absent" — negative evidence that a pooled representation may not expose. That is the hard part, and why later NER/NLI evidence is the
natural independent source.

## Disclosed before fixing the bars

On the CAL half, the *existing* decision head's P(ASK) as a scorer already ranks ASK rows: AP 0.235–0.320 against prevalence 0.049, AUROC 0.78–0.83 (four surfaces). Its precision is about 0.5 at
recall 0.11–0.32 (P(ASK) ≥ 0.3–0.5), and it never reaches 0.8 — which is why C1's rule (precision ≥ 0.8, tuned for *executing actions*) never fitted. **The cost model differs:** a false ask costs a human
question, an unsafe execution costs harm. The ASK rung therefore uses lower precision targets. No dedicated-head result had been seen when the bars below were fixed.

## Data and split

- **Fitting the head:** BANK-v1 TRAIN (143,996 rows: cached features and `labels.policy.decision`). Label `SHOULD_ASK` = decision is ASK. Nothing else is used to fit.
- **Calibration/holdout:** BANK-v1 DEV split exactly as C1 (same CAL/HOLD mask, read from C1's verified evidence). Thresholds are fitted on CAL only; HOLD is scored once per head type.
- No TEST row is read. HOLD was already scored once for C1 (other heads), so it is not virgin: results are **development evidence**. Confirmation needs the fresh sealed split.

## Heads (fixed recipe; nothing is tuned)

Input: the surface's Rung 0 standardization (the surface's train-only mean/scale from its Rung 0 checkpoint). Four surfaces as in C1; **primary `middle_plus_final`**; the rest are sensitivity.
Recipe: AdamW, lr 1e-3, weight decay 1e-4, 8 epochs, batch 2048, seed 20260929, unweighted binary cross-entropy, one output logit.
- **linear:** one linear layer. **mlp:** one hidden layer of 256 ReLU units. Same recipe. The MLP is trained and scored only under the rule below.
Outputs are quantized once to integer ppm `[P(DO_NOT_ASK), P(SHOULD_ASK)]` and carried as C0 `DecisionVector`s bound to C0 `ObserverBundle`s that carry the Rung 0 hashes.

## Baseline scorer

The existing Rung 0 decision head's `P(ASK)` on the same surface and rows (from C1's evidence). It gets the same fitting procedure as the dedicated head, so the comparison is at matched operating points.

## The ASK rule and how it is fitted (CAL only)

Rule: `<observer>.p.<positive label> >= T` → `ASK_HUMAN`. No argmax gating (C1's rule required the ASK label to be the top class; that shrinks the candidate set).
Grid `T` = 50,000…995,000 ppm in steps of 5,000, plus 999,000. Choose the **smallest** `T` such that at least 100 CAL rows have score ≥ `T` and the one-sided 95% Wilson lower bound of
their precision (truth ASK) is ≥ `1 − α`. If none qualifies the rule is omitted. **α_ask ∈ {0.60, 0.50, 0.40, 0.30, 0.20}; primary α_ask = 0.50.** All are reported.

## Measures on HOLD

- **Signal:** AP and AUROC for the dedicated head and the baseline scorer (tie-aware). **Recall at matched precision** `p ∈ {0.4, 0.5, 0.6, 0.7}`: the highest recall of any threshold with precision ≥ `p` and at least 50 selected rows.
- **Fitted rule (through the real C0 runtime):** asks, precision, recall of ASK rows, for the dedicated head and the baseline.
- **Controller cost** (primary surface): the C1 controller at α = 0.05 with its frozen abstain and act thresholds, with and without the ASK rule placed first (α_ask = 0.50): correct-executed rows, harmful rate,
  coverage, and correct asks. Every HOLD row goes through the C0 runtime; a numpy re-implementation must agree row for row.

## Criteria — primary surface, per head type

- **A1 (beats the existing head, at matched precision):** HOLD `AP_dedicated ≥ 1.25 × AP_baseline` **and** recall at matched precision `≥ 1.25 ×` the baseline's at **at least 3 of the 4** precision levels
  (baseline 0 and dedicated > 0 counts as a pass; both 0 does not).
- **A2 (usable fitted rule):** at α_ask = 0.50 a threshold exists on CAL, and on HOLD the rule makes **≥ 100 asks** with **precision ≥ 0.45** and **recall ≥ 0.25**.
- **A3 (does not damage the acting tier):** with the ASK rule added, HOLD correct-executed rows **≥ 90%** of the C1 controller's, and the harmful-execution rate **≤ C1's + 0.5 points**.

Verdict per head: **USEFUL ASK OBSERVER** = A1, A2 and A3. **SIGNAL, NOT USABLE** = A1 but not both A2 and A3. **NO GAIN OVER THE EXISTING HEAD** = not A1.
A criterion that cannot be evaluated (no threshold, too few asks) fails.

## When the MLP is tried (fixed now)

The MLP stage runs **iff** the linear head is not USEFUL **and** the linear head's CAL average precision is at least 0.10 (twice the prevalence: some signal exists, "obvious headroom").
If the linear head is USEFUL, or shows no signal at all, the MLP is not trained. The MLP then goes through the same calibrate, freeze and score-once procedure.

## What this cannot show

DEV only, one seed, synthetic BANK, no calibrator beyond thresholding. A pass means the dedicated observer works on this distribution; the fresh sealed split decides whether it is real.
The reason head (which kind of missing information) is a later step.

## Addenda

**Addendum 1 — output-bias initialisation (2026-09-29, before calibration and before any dedicated-head result on DEV).**
The first training run followed the recipe above exactly and did not converge: after 568 steps the linear heads' final TRAIN loss was about 0.49, far above the 0.191 of a constant
predictor at 4.76% prevalence, with mean predicted P(SHOULD_ASK) ≈ 0.37 against a true 0.045 and the output bias at −0.52 against the −3.0 the prior needs (Adam at lr 1e-3 moves it at most 0.001 per step).
That is a training defect, not a finding, and it was diagnosed on TRAIN rows only. **Change:** the output bias (of the linear layer, or of the MLP's output layer) starts at `ln(p/(1−p))` for the TRAIN prior `p`.
Everything else in the recipe is unchanged (optimizer, learning rate, weight decay, epochs, batch, seed, unweighted loss), and the MLP, if ever run, uses the same initialisation. With it, the primary surface's TRAIN loss
falls to 0.155 (below the constant predictor). No criterion, threshold rule, baseline or verdict rule is changed. The heads were retrained before calibration, so the freeze covers the corrected heads.
